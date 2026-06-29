from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from .core import CHAT_CODE_COPY_STORE
from .widgets import show_image_preview


class AgentChatLinksMixin:
    """聊天区 app:// 链接点击分发。"""

    def _on_chat_link_clicked(self, url):
        try:
            if isinstance(url, QUrl):
                action = url.host()
                path = url.path().strip("/")
                query = url.query()
            else:
                u = QUrl(str(url))
                action = u.host()
                path = u.path().strip("/")
                query = u.query()

            if action == "load-more":
                bar = self.chat_view.verticalScrollBar()
                old_value = bar.value()
                old_max = bar.maximum()
                self._chat_scroll_restore_token += 1
                restore_token = self._chat_scroll_restore_token
                self.max_render_messages = int(self.max_render_messages or 30) + 30
                self._preserve_chat_scroll_once = True
                self.render_chat(force=True)

                def restore_view_position(token=restore_token, final=False):
                    try:
                        if token != self._chat_scroll_restore_token:
                            return
                        new_bar = self.chat_view.verticalScrollBar()
                        added_height = max(0, new_bar.maximum() - old_max)
                        new_bar.setValue(min(new_bar.maximum(), old_value + added_height))
                        if final and token == self._chat_scroll_restore_token:
                            self._chat_scroll_restore_token = 0
                    except Exception:
                        pass

                delays = (0, 40, 120, 240, 400)
                for ms in delays:
                    QTimer.singleShot(ms, lambda m=ms: restore_view_position(final=(m == delays[-1])))

                self.bar.set_status(f"已加载更早 30 条，当前显示最近 {self.max_render_messages} 条")
                return

            path_parts = [p for p in path.split("/") if p]
            idx = int(path_parts[0]) if path_parts else -1
            if action == "copy-code":
                code_id = ""
                for part in (query or "").split("&"):
                    if part.startswith("id="):
                        code_id = part[3:]
                        break
                if not code_id:
                    code_id = path
                code_text = CHAT_CODE_COPY_STORE.get(code_id, "")
                if code_text:
                    self.copy_text_to_clipboard(code_text, "已复制代码")
                return
            if action == "copy":
                self.copy_message_at(idx)
            elif action == "retry":
                self.resubmit_message_at(idx)
            elif action == "delete":
                self.delete_message_at(idx)
            elif action == "preview-image":
                image_idx = int(path_parts[1]) if len(path_parts) > 1 else -1
                msg = self.messages[idx] if 0 <= idx < len(self.messages) else {}
                images = msg.get("_uploaded_image_paths", []) if isinstance(msg, dict) else []
                if 0 <= image_idx < len(images):
                    show_image_preview(self, images[image_idx], "附图预览")
            else:
                QDesktopServices.openUrl(url)
        except Exception:
            pass
