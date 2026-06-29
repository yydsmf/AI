from .core import load_input_drafts, save_input_drafts


class AgentInputDraftMixin:
    """智能体输入框草稿保存和恢复。"""

    def restore_agent_input_draft(self):
        """
        恢复当前会话自己的输入框草稿。
        """
        try:
            data = load_input_drafts()

            sid = self.current_session_id or ""
            drafts = data.get("agent_inputs", {})
            if not isinstance(drafts, dict):
                drafts = {}

            if sid:
                text = drafts.get(sid, "")
            else:
                text = data.get("agent_input", "")
            if not isinstance(text, str):
                text = ""

            self.input.blockSignals(True)
            self.input.setPlainText(text)
            self.input.blockSignals(False)

            try:
                self.adjust_input_height()
            except Exception:
                pass
        except Exception:
            try:
                self.input.blockSignals(False)
            except Exception:
                pass

    def save_agent_input_draft(self, *args):
        """
        保存当前会话自己的输入框草稿。
        """
        try:
            data = load_input_drafts()

            drafts = data.get("agent_inputs", {})
            if not isinstance(drafts, dict):
                drafts = {}

            sid = self.current_session_id or ""
            text = self.input.toPlainText()
            if sid:
                drafts[sid] = text
                data["agent_inputs"] = drafts

            # 保留兼容字段，供历史草稿格式读取。
            data["agent_input"] = text
            save_input_drafts(data)
        except Exception:
            pass

    def schedule_agent_input_draft_save(self, delay_ms=300):
        try:
            self._draft_save_timer.start(int(delay_ms))
        except Exception:
            try:
                self.save_agent_input_draft()
            except Exception:
                pass
