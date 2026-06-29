from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QTextBrowser


class AgentChatScrollMixin:
    """智能体聊天区滚动、贴底和“到最新消息”按钮状态。"""

    def scroll_chat_to_bottom(self):
        """强制把聊天框右侧滑动条滚动到最下面。"""
        try:
            if self.chat_view is None:
                return False

            try:
                if isinstance(self.chat_view, QTextBrowser):
                    self.chat_view.moveCursor(QTextCursor.End)
                    self.chat_view.ensureCursorVisible()

                bar = self.chat_view.verticalScrollBar()
                bar.setValue(bar.maximum())
                if bar.value() >= bar.maximum() - 2:
                    self._user_reading_chat_history = False
                    self._follow_streaming_output = True
                self._update_scroll_to_bottom_button()
                return bar.value() >= bar.maximum() - 2
            except Exception:
                pass
        except Exception:
            pass
        return False

    def _position_scroll_to_bottom_button(self):
        try:
            if not hasattr(self, "scroll_bottom_btn"):
                return
            size = self.scroll_bottom_btn.width()
            x = max(0, (self.chat_view.viewport().width() - size) // 2)
            y = max(0, self.chat_view.viewport().height() - size - 16)
            self.scroll_bottom_btn.move(x, y)
            self.scroll_bottom_btn.raise_()
        except Exception:
            pass

    def _update_scroll_to_bottom_button(self):
        try:
            if not hasattr(self, "scroll_bottom_btn"):
                return
            bar = self.chat_view.verticalScrollBar()
            should_show = (
                bar.maximum() > 0
                and (
                    bool(getattr(self, "_user_reading_chat_history", False))
                    or not self._is_chat_near_bottom(threshold=96)
                )
            )
            self.scroll_bottom_btn.setVisible(bool(should_show))
            if should_show:
                self._position_scroll_to_bottom_button()
        except Exception:
            pass

    def _scroll_to_latest_from_button(self):
        self._user_reading_chat_history = False
        self._follow_streaming_output = True
        self.scroll_chat_to_bottom_later(force=True)
        try:
            self.scroll_bottom_btn.hide()
        except Exception:
            pass

    def _is_chat_near_bottom(self, threshold=48):
        """
        判断聊天区当前是否接近底部。
        只有已经在底部附近，或者正在流式输出时，才允许自动贴底。
        这样用户向上翻历史时，不会被定时器强行拉回底部。
        """
        try:
            if self.chat_view is None:
                return True

            bar = self.chat_view.verticalScrollBar()
            return bar.value() >= bar.maximum() - int(threshold)
        except Exception:
            return True

    def scroll_chat_to_bottom_later(self, force=False):
        """
        延迟滚到底部。
        默认只在当前接近底部或正在流式输出时自动贴底，
        避免用户向上浏览历史时被拉回底部。
        """
        try:
            should_scroll = (
                bool(force)
                or (
                    self.streaming_text is not None
                    and self._follow_streaming_output
                    and not getattr(self, "_user_reading_chat_history", False)
                )
                or (
                    self._is_chat_near_bottom()
                    and not getattr(self, "_user_reading_chat_history", False)
                )
            )

            if not should_scroll:
                return

            def do_scroll():
                try:
                    if (
                        bool(force)
                        or (
                            self.streaming_text is not None
                            and self._follow_streaming_output
                            and not getattr(self, "_user_reading_chat_history", False)
                        )
                        or (
                            self._is_chat_near_bottom()
                            and not getattr(self, "_user_reading_chat_history", False)
                        )
                    ):
                        self.scroll_chat_to_bottom()
                except Exception:
                    pass

            for ms in (0, 40, 120):
                QTimer.singleShot(ms, do_scroll)

        except Exception:
            pass

    def scroll_streaming_to_bottom_if_following(self):
        """
        流式输出期间的温和贴底。
        只在用户没有向上阅读历史、且仍允许跟随输出时贴底；
        用户滚轮向上后不再用 force 抢回到底部。
        """
        try:
            if (
                self.streaming_text is not None
                and self._follow_streaming_output
                and not getattr(self, "_user_reading_chat_history", False)
            ):
                self.scroll_chat_to_bottom_later(force=False)
            else:
                self._update_scroll_to_bottom_button()
        except Exception:
            pass

    def _request_chat_bottom_lock(self, reason=""):
        """
        启动/切会话后进入贴底状态。
        Qt 布局、模型栏恢复、resize 都可能在后续 1-2 秒改变滚动范围，
        所以这里不靠固定延迟，而是由 rangeChanged/render 持续推进到底部。
        """
        try:
            self._chat_bottom_lock = True
            self._chat_bottom_lock_reason = reason or ""
            self._chat_bottom_lock_attempts = 0
            QTimer.singleShot(0, self._apply_chat_bottom_lock)
        except Exception:
            pass

    def _release_chat_bottom_lock_later(self):
        try:
            if not getattr(self, "_chat_bottom_lock", False):
                return

            def release_if_still_bottom():
                try:
                    if getattr(self, "_chat_bottom_lock", False) and self._is_chat_near_bottom(threshold=4):
                        self._chat_bottom_lock = False
                        self._chat_bottom_lock_reason = ""
                except Exception:
                    pass

            QTimer.singleShot(180, release_if_still_bottom)
        except Exception:
            pass

    def _apply_chat_bottom_lock(self):
        try:
            if not getattr(self, "_chat_bottom_lock", False):
                return

            reached = self.scroll_chat_to_bottom()
            self._chat_bottom_lock_attempts += 1

            if reached:
                self._release_chat_bottom_lock_later()
                return

            if self._chat_bottom_lock_attempts < 80:
                QTimer.singleShot(50, self._apply_chat_bottom_lock)
            else:
                self._chat_bottom_lock = False
                self._chat_bottom_lock_reason = ""
        except Exception:
            pass

    def showEvent(self, event):
        """
        智能体页面显示时的滚动策略。

        目标：
        1. 第一次打开智能体界面时，自动滚到底部，让用户直接看到最新内容；
        2. 只做很短的几次延迟滚动，避免布局还没完成导致滚动失败；
        3. 后续切换回来时避免打断用户浏览历史；
        4. 正在流式输出时，仍然允许跟随到底部。
        """
        try:
            super().showEvent(event)
        except Exception:
            pass

        try:
            if not self._agent_initial_scroll_done:
                self._agent_initial_scroll_done = True
                self._suppress_resize_rerender_once = True
                self._request_chat_bottom_lock("initial_show")
                self._render_chat_history_fast_then_complete()
                QTimer.singleShot(300, lambda: setattr(self, "_suppress_resize_rerender_once", False))
                return

            if self.streaming_text is not None and self._follow_streaming_output:
                self.scroll_streaming_to_bottom_if_following()

        except Exception:
            pass

    def resizeEvent(self, event):
        try:
            super().resizeEvent(event)
        except Exception:
            pass

        try:
            self._chat_resize_timer.start(120)
            self._position_scroll_to_bottom_button()
            self._update_scroll_to_bottom_button()
        except Exception:
            pass

    def _rerender_chat_after_resize(self):
        try:
            if getattr(self, "_chat_scroll_restore_token", 0):
                return
            if getattr(self, "_chat_history_render_pending", False):
                return
            if getattr(self, "_suppress_resize_rerender_once", False):
                return
            if getattr(self, "_chat_bottom_lock", False) or self._is_chat_near_bottom(threshold=96):
                self._request_chat_bottom_lock("resize")
            self.render_chat(force=True)
        except Exception:
            pass

    def _on_chat_scroll_value_changed(self, _value):
        """
        用户流式输出时向上滚动，就暂停自动贴底。
        滚回底部附近后，恢复跟随输出。
        """
        try:
            if getattr(self, "_chat_bottom_lock", False):
                if not self._is_chat_near_bottom(threshold=220):
                    self._chat_bottom_lock = False
                    self._chat_bottom_lock_reason = ""
                    self._user_reading_chat_history = True
                    self._follow_streaming_output = False
                    self._update_scroll_to_bottom_button()
                return

            if getattr(self, "_chat_rendering_html", False):
                self._update_scroll_to_bottom_button()
                return
            near_bottom = self._is_chat_near_bottom(threshold=96)
            self._user_reading_chat_history = not near_bottom
            if self.streaming_text is not None:
                self._follow_streaming_output = near_bottom
            self._update_scroll_to_bottom_button()
        except Exception:
            pass

    def _on_chat_scroll_range_changed(self, _min, _max):
        """
        聊天内容高度变化时的滚动策略。

        只有两种情况自动贴底：
        1. 正在流式接收回复；
        2. 用户本来就在底部附近。

        如果用户已经向上滚动查看历史，则不打断用户。
        """
        try:
            if getattr(self, "_chat_bottom_lock", False):
                self._apply_chat_bottom_lock()
                return

            if (
                self.streaming_text is not None
                and self._follow_streaming_output
                and not getattr(self, "_user_reading_chat_history", False)
            ):
                self.scroll_chat_to_bottom()
                return

            if self._is_chat_near_bottom() and not getattr(self, "_user_reading_chat_history", False):
                self.scroll_chat_to_bottom()
            self._update_scroll_to_bottom_button()
        except Exception:
            pass
