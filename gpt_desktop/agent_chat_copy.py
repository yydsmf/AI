from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import QMenu


class AgentChatCopyMixin:
    """聊天区选中文本复制、右键菜单和鼠标文本反馈。"""

    def _chat_mouse_over_text(self, pos):
        try:
            cursor = self.chat_view.cursorForPosition(pos)
            rect = self.chat_view.cursorRect(cursor)
            if not rect.isValid():
                return False

            if abs(pos.y() - rect.center().y()) > max(8, rect.height()):
                return False
            if pos.x() < 0 or pos.x() > self.chat_view.viewport().width():
                return False

            probe = QTextCursor(cursor)
            probe.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor)
            if probe.selectedText().strip():
                return abs(pos.x() - rect.left()) <= 24

            if cursor.position() <= 0:
                return False

            probe = QTextCursor(cursor)
            probe.setPosition(cursor.position() - 1)
            prev_rect = self.chat_view.cursorRect(probe)
            probe.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor)
            if probe.selectedText().strip() and prev_rect.isValid():
                return prev_rect.left() - 4 <= pos.x() <= rect.left() + 4

        except Exception:
            pass
        return False

    def _clean_chat_selection_text(self, text):
        if not isinstance(text, str):
            return ""
        text = text.replace("\u2029", "\n").replace("\u2028", "\n")
        lines = [line.rstrip() for line in text.splitlines()]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            return ""

        cleaned = []
        previous_blank = False
        for line in lines:
            if not line.strip():
                if not previous_blank:
                    cleaned.append("")
                previous_blank = True
                continue
            cleaned.append(line.strip())
            previous_blank = False
        return "\n".join(cleaned).strip()

    def copy_selected_chat_text(self):
        try:
            cursor = self.chat_view.textCursor()
            if not cursor.hasSelection():
                return False
            text = self._clean_chat_selection_text(cursor.selectedText())
            if not text:
                return False
            QGuiApplication.clipboard().setText(text)
            try:
                self.bar.set_status("已复制选中文本")
            except Exception:
                pass
            return True
        except Exception:
            return False

    def show_chat_context_menu(self, global_pos):
        menu = QMenu(self.chat_view)
        copy_action = menu.addAction("复制")
        copy_action.setEnabled(self.chat_view.textCursor().hasSelection())
        selected = menu.exec(global_pos)
        if selected is copy_action:
            self.copy_selected_chat_text()
            return True
        return False

    def show_chat_context_menu_at(self, pos):
        try:
            global_pos = self.chat_view.viewport().mapToGlobal(pos)
        except Exception:
            try:
                global_pos = self.chat_view.mapToGlobal(pos)
            except Exception:
                return
        self.show_chat_context_menu(global_pos)
