from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor

from .agent_chat_renderer import AgentChatRenderer
from .core import CHAT_CODE_COPY_STORE


class AgentChatRenderMixin:
    """聊天区完整渲染和流式局部刷新。"""

    def _chat_renderer(self):
        return AgentChatRenderer(
            self.messages,
            max_render_messages=self.max_render_messages or 30,
            streaming_text=self.streaming_text,
        )

    def _extract_display_text(self, msg):
        return AgentChatRenderer.extract_display_text(msg)

    def _display_text_with_balanced_code_fence(self, text):
        return AgentChatRenderer.display_text_with_balanced_code_fence(text)

    def _chat_action_links_html(self, index, role):
        return self._chat_renderer().action_links_html(index, role)

    def _message_table_html(self, box_html, actions_html="", align="left", role="assistant"):
        return AgentChatRenderer.message_table_html(box_html, actions_html, align, role)

    def _message_attachments_html(self, msg, message_index=None):
        return AgentChatRenderer.message_attachments_html(msg, message_index)

    def _message_to_html(self, msg, index):
        return self._chat_renderer().message_to_html(msg, index)

    def _chat_history_notice_html(self, hidden_count):
        return AgentChatRenderer.chat_history_notice_html(hidden_count)

    def _render_chat_html(self, include_streaming=True):
        return self._chat_renderer().render_chat_html(include_streaming=include_streaming)

    def render_chat(self, force=False):
        """
        聊天区渲染。

        长任务时的渲染策略：
        1. 普通刷新 / 强制刷新：完整重建聊天区；
        2. 流式输出中：只用定时器更新最后一个智能体气泡。
        """
        if self.streaming_text is not None and not force:
            self._schedule_streaming_render()
            return

        self._render_chat_now()

    def _append_outgoing_chat_widgets(self, display_user_msg):
        try:
            self._last_streaming_html = ""
            self.render_chat(force=True)
            self.scroll_chat_to_bottom_later(force=True)
        except Exception:
            self.render_chat(force=True)

    def _finalize_streaming_chat_widget(self, content, should_follow_output=True):
        try:
            self.render_chat(force=True)
            if should_follow_output:
                self.scroll_chat_to_bottom_later(force=True)
        except Exception:
            self.render_chat(force=True)

    def _replace_streaming_chat_widget(self, content, should_follow_output=True):
        try:
            self.streaming_text = None
            self._last_streaming_html = ""
            self.render_chat(force=True)
            if should_follow_output:
                self.scroll_chat_to_bottom_later(force=True)
        except Exception:
            self.streaming_text = None
            self._last_streaming_html = ""
            self.render_chat(force=True)

    def _streaming_render_interval(self):
        """
        根据当前回复长度动态降低刷新频率。
        长回复每次都要重新生成富文本，固定高频刷新会让界面越来越卡。
        """
        try:
            length = len(self.streaming_text or "")
            if not self._follow_streaming_output:
                return max(320, self._chat_render_interval_ms)
            if length >= 30000:
                return 360
            if length >= 12000:
                return 220
            if length >= 4000:
                return 140
            return self._chat_render_interval_ms
        except Exception:
            return self._chat_render_interval_ms

    def _schedule_streaming_render(self):
        if self._render_timer.isActive():
            return
        self._render_timer.setInterval(self._streaming_render_interval())
        self._render_timer.start()

    def _streaming_html_from_text(self, text):
        return AgentChatRenderer.streaming_html_from_text(text)

    def _streaming_html(self):
        return self._chat_renderer().streaming_html()

    def _streaming_message_html(self, body):
        return AgentChatRenderer.streaming_message_html(body, outer_margin=True)

    def _replace_streaming_doc_fragment(self, html_text):
        """
        QTextBrowser.setHtml() 会重建整页，流式输出时容易闪烁。
        这里只替换文档末尾的流式回复片段，历史内容保持不动。
        """
        try:
            doc = self.chat_view.document()
            if self._streaming_doc_start is None:
                return False

            cursor = QTextCursor(doc)
            start_pos = max(0, min(int(self._streaming_doc_start), doc.characterCount() - 1))
            cursor.setPosition(start_pos)
            cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertHtml(self._streaming_message_html(html_text))
            if self._follow_streaming_output and not getattr(self, "_user_reading_chat_history", False):
                self.scroll_streaming_to_bottom_if_following()
            else:
                self._update_scroll_to_bottom_button()
            return True
        except Exception:
            self._streaming_doc_start = None
            return False

    def _flush_streaming_bubble(self):
        """
        定时刷新流式气泡。

        重点：
        - 优先只替换文档末尾的流式片段；
        - 避免每个流式片段都 setHtml() 导致聊天区闪烁；
        - 失败时才完整重建。
        """
        try:
            if self.streaming_text is None:
                return
            html_text = self._streaming_html()
            if html_text == self._last_streaming_html:
                if self._follow_streaming_output and not getattr(self, "_user_reading_chat_history", False):
                    self.scroll_streaming_to_bottom_if_following()
                else:
                    self._update_scroll_to_bottom_button()
                return
            self._last_streaming_html = html_text
            if not self._replace_streaming_doc_fragment(html_text):
                self.render_chat(force=True)
            if self._follow_streaming_output and not getattr(self, "_user_reading_chat_history", False):
                self.scroll_streaming_to_bottom_if_following()
            else:
                self._update_scroll_to_bottom_button()
        except Exception:
            try:
                self._render_chat_now()
            except Exception:
                pass

    def _render_chat_now(self):
        bar = self.chat_view.verticalScrollBar()
        prev_pos = bar.value()
        preserve_scroll = bool(getattr(self, "_preserve_chat_scroll_once", False))
        if preserve_scroll:
            self._preserve_chat_scroll_once = False
        bottom_locked = bool(getattr(self, "_chat_bottom_lock", False))
        at_bottom = (not preserve_scroll) and (bottom_locked or prev_pos >= bar.maximum() - 40)

        self.chat_view.setUpdatesEnabled(False)
        self._chat_rendering_html = True
        try:
            self._streaming_doc_start = None
            CHAT_CODE_COPY_STORE.clear()
            render_streaming_separately = bool(self.streaming_text is not None)
            self.chat_view.setHtml(self._render_chat_html(include_streaming=not render_streaming_separately))
            if self.streaming_text is not None:
                try:
                    cursor = QTextCursor(self.chat_view.document())
                    cursor.movePosition(QTextCursor.End)
                    stream_start = cursor.position()
                    stream_html = self._streaming_html_from_text(self.streaming_text)
                    cursor.insertHtml(self._streaming_message_html(stream_html))
                    self._streaming_doc_start = stream_start
                    self._last_streaming_html = stream_html
                except Exception:
                    self._streaming_doc_start = None
        finally:
            self._chat_rendering_html = False
            self.chat_view.setUpdatesEnabled(True)

        if preserve_scroll:
            self._update_scroll_to_bottom_button()
            return
        if bottom_locked:
            QTimer.singleShot(0, self._apply_chat_bottom_lock)
        elif at_bottom or (self.streaming_text is not None and self._follow_streaming_output):
            self.scroll_streaming_to_bottom_if_following()
        else:
            QTimer.singleShot(0, lambda: self.chat_view.verticalScrollBar().setValue(
                min(prev_pos, self.chat_view.verticalScrollBar().maximum())
            ))
        QTimer.singleShot(0, self._update_scroll_to_bottom_button)
