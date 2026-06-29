from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from .conversation_dialog import ConversationListDialog


class AgentConversationStateMixin:
    """智能体会话加载、保存、切换、新建和上下文清除流程。"""

    def _reset_streaming_state(self):
        try:
            if self._render_timer.isActive():
                self._render_timer.stop()
        except Exception:
            pass
        self.streaming_text = None
        self._last_streaming_html = ""
        self._streaming_doc_start = None

    def _reset_send_controls(self):
        self.send_btn.setEnabled(True)
        self.send_btn.setText("发送")
        self.stop_btn.setText("中止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)

    def _set_receiving_controls(self):
        self.send_btn.setEnabled(False)
        self.send_btn.setText("接收中")
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)

    def load_persistent_chat(self):
        data = self._load_sessions_data()

        self.sessions = data.get("sessions", [])
        self.current_session_id = data.get("current_session_id", "")

        sess = self._current_session()
        if sess is None:
            sess = self._make_session()
            self.sessions = [sess]
            self.current_session_id = sess["id"]

        messages = sess.get("messages", [])
        if not isinstance(messages, list):
            messages = []

        self.messages = messages
        self.max_render_messages = 30
        self.clear_all_attachments(show_status=False)
        self._reset_streaming_state()
        self._user_reading_chat_history = False
        self._follow_streaming_output = True
        self.ensure_session_model_fields()
        self._save_sessions_data()

        self._save_legacy_current_history_copy(self._serialize_messages_for_save(self.messages))

        self._request_chat_bottom_lock("load_history")
        self._chat_history_render_pending = True
        self._render_chat_history_fast_then_complete()
        self.restore_agent_input_draft()
        QTimer.singleShot(300, self.restore_session_model_config)

    def _render_chat_history_after_layout_ready(self):
        try:
            if not getattr(self, "_chat_history_render_pending", False):
                return
            try:
                if self.chat_view.viewport().width() <= 240:
                    QTimer.singleShot(80, self._render_chat_history_after_layout_ready)
                    return
            except Exception:
                pass

            self._chat_history_render_pending = False
            self._render_chat_history_fast_then_complete()
        except Exception:
            pass

    def _render_chat_history_fast_then_complete(self):
        try:
            self._chat_history_render_pending = False
            target = 30
            self._chat_incremental_render_target = target
            self.max_render_messages = target
            self.render_chat(force=True)
            self.scroll_chat_to_bottom_later(force=True)
        except Exception:
            self._chat_history_render_pending = False
            self.max_render_messages = 30
            self.render_chat(force=True)

    def save_persistent_chat(self):
        """
        保存当前会话。

        注意：
        - 智能体历史不限制保存条数；
        - 多会话统一保存到 AGENT_SESSIONS_FILE；
        - AGENT_HISTORY_FILE 只保留当前会话的兼容副本。
        """
        safe = self._serialize_messages_for_save(self.messages)
        self.save_current_session_model_config(persist=False)
        self._update_current_session_messages(safe)
        self._save_sessions_data()

        self._save_legacy_current_history_copy(safe)

    def schedule_persistent_chat_save(self, delay_ms=350):
        try:
            self._chat_save_timer.start(int(delay_ms))
        except Exception:
            try:
                self.save_persistent_chat()
            except Exception:
                pass

    def open_conversation_list(self):
        """
        打开会话列表，选择要继续的会话。
        """
        try:
            if self.worker and self.worker.isRunning():
                ret = QMessageBox.warning(
                    self,
                    "正在接收回复",
                    "当前智能体正在生成回复。切换会话前需要先中止当前任务，是否继续？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if ret != QMessageBox.Yes:
                    return
                self.stop_current_task()
        except Exception:
            pass

        # 打开列表前先保存当前会话和输入草稿
        self.save_agent_input_draft()
        self.save_current_session_model_config(persist=False)
        self.save_persistent_chat()
        before_session_id = self.current_session_id

        dlg = ConversationListDialog(self.sessions, self.current_session_id, self)
        if not dlg.exec():
            return

        sessions, selected_id = dlg.get_result()
        if not sessions:
            return

        self.sessions = sessions
        self.current_session_id = selected_id or sessions[0].get("id", "")

        sess = self._current_session()
        if sess is None:
            sess = sessions[0]
            self.current_session_id = sess.get("id", "")

        messages = sess.get("messages", [])
        if not isinstance(messages, list):
            messages = []

        self.messages = messages
        self.max_render_messages = 30
        self.clear_all_attachments(show_status=False)
        self._reset_streaming_state()
        self._user_reading_chat_history = False
        self._follow_streaming_output = True
        self._request_chat_bottom_lock("switch_session")

        self._save_sessions_data()
        self._save_legacy_current_history_copy(self._serialize_messages_for_save(self.messages))

        self.render_chat(force=True)
        self.scroll_chat_to_bottom_later(force=True)
        self.restore_agent_input_draft()
        self.ensure_session_model_fields()
        if self.current_session_id != before_session_id:
            self.restore_session_model_config()
        else:
            self._save_sessions_data()
        QTimer.singleShot(80, lambda: self._request_chat_bottom_lock("switch_session_after_layout"))
        self.bar.set_status(f"已打开会话：{sess.get('title', '未命名会话')}")

    def new_chat(self):
        """
        开启一个新会话。

        行为：
        - 保留旧会话记录；
        - 当前会话会先保存；
        - 然后创建一个新的空会话并切换过去。
        """
        try:
            if self.worker and self.worker.isRunning():
                self.stop_current_task()
        except Exception:
            pass

        # 保存当前会话，不丢记录
        try:
            self.save_agent_input_draft()
            self.save_current_session_model_config(persist=True)
            self.save_persistent_chat()
        except Exception:
            pass

        sess = self._make_session()
        self.sessions.insert(0, sess)
        self.current_session_id = sess["id"]

        self.messages = []
        self.max_render_messages = 30
        self.clear_all_attachments(show_status=False)
        self._reset_streaming_state()
        self._stopping_task = False

        self._reset_send_controls()

        self.input.clear()
        self.save_agent_input_draft()

        self._save_sessions_data()
        self._save_legacy_current_history_copy([])

        self.render_chat(force=True)
        self.restore_agent_input_draft()
        self.save_current_session_model_config(persist=True)
        self.restore_session_model_config()
        self.bar.set_status("已开启新对话，旧会话记录已保留")

    def clear_context(self):
        """
        清除当前会话上下文。

        说明：
        - 不删除聊天历史，只截断模型后续可读上下文；
        - 聊天窗口仍保留完整历史，方便回看。
        """
        ret = QMessageBox.warning(
            self,
            "清除当前会话上下文",
            (
                "确定要清除智能体后续可读取的上下文吗？\n\n"
                "注意：\n"
                "1. 聊天历史不会删除，仍然可以在界面中查看。\n"
                "2. 智能体之后只会读取从此刻之后的新消息。\n"
                "3. 如果需要真正删除历史，请使用消息下方的删除按钮或清理缓存。"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if ret != QMessageBox.Yes:
            return

        try:
            if self.worker and self.worker.isRunning():
                self.stop_current_task()
        except Exception:
            pass

        self.messages.append({
            "role": "assistant",
            "content": (
                "【上下文已清除】\n\n"
                "此前聊天记录仍保留在界面中，方便查看；"
                "但智能体后续不会再读取这条提示之前的历史内容。"
            ),
            "_local_status": "context_cleared",
        })

        try:
            sess = self._current_session()
            if isinstance(sess, dict):
                sess["context_summary"] = ""
                sess["context_summary_source_count"] = 0
        except Exception:
            pass

        self.set_context_cutoff(len(self.messages))

        try:
            self.save_persistent_chat()
        except Exception:
            pass

        try:
            self._user_reading_chat_history = False
            self._follow_streaming_output = True
            self.render_chat(force=True)
            self.scroll_chat_to_bottom_later(force=True)
        except Exception:
            pass

        try:
            self.bar.set_status("已清除模型可读上下文，历史记录已保留")
        except Exception:
            pass
