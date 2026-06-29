import os
import re

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox


class AgentMessageActionsMixin:
    """聊天消息复制、删除和重发操作。"""

    def copy_text_to_clipboard(self, text, status="已复制"):
        """
        复制文本到系统剪贴板，并在模型栏显示反馈。
        """
        try:
            QGuiApplication.clipboard().setText(text or "")
            try:
                self.bar.set_status(status)
            except Exception:
                pass
        except Exception as e:
            try:
                QMessageBox.warning(self, "复制失败", str(e))
            except Exception:
                pass

    def _valid_message_index(self, index):
        try:
            index = int(index)
        except Exception:
            return -1
        if index < 0 or index >= len(self.messages):
            return -1
        return index

    def _clamp_message_index(self, index):
        try:
            index = int(index)
        except Exception:
            index = 0
        return max(0, min(index, len(self.messages)))

    def copy_message_at(self, index):
        """
        复制整条消息内容。
        """
        index = self._valid_message_index(index)
        if index < 0:
            return

        try:
            msg = self.messages[index]
            if not isinstance(msg, dict):
                return

            text = self._extract_display_text(msg)
            self.copy_text_to_clipboard(text, "已复制消息")
        except Exception as e:
            try:
                QMessageBox.warning(self, "复制失败", str(e))
            except Exception:
                pass

    def delete_message_at(self, index):
        """
        删除指定消息。

        当前实现：
        - 点哪条删哪条；
        - 不自动删除前后消息；
        - 删除后立即保存当前会话。
        """
        index = self._valid_message_index(index)
        if index < 0:
            return

        before_cutoff = self.get_context_cutoff()

        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "提示", "智能体正在回复时不能删除消息，请先中止或等待完成。")
            return

        ret = QMessageBox.warning(
            self,
            "删除消息",
            "确定删除这段对话吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if ret != QMessageBox.Yes:
            return

        try:
            bar = self.chat_view.verticalScrollBar()
            old_value = bar.value()
            old_max = bar.maximum()
            restore_token = self._chat_scroll_restore_token + 1
            self._chat_scroll_restore_token = restore_token

            del self.messages[index]

            new_cutoff = before_cutoff
            if index < before_cutoff:
                new_cutoff = max(0, before_cutoff - 1)

            self.set_context_cutoff(self._clamp_message_index(new_cutoff))
            self.save_persistent_chat()
            self.render_chat(force=True)
            self._restore_chat_scroll_after_content_change(old_value, old_max, restore_token)
            self.bar.set_status("已删除消息")
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))

    def _restore_chat_scroll_after_content_change(self, old_value, old_max, token):
        def restore(final=False):
            try:
                if token != self._chat_scroll_restore_token:
                    return
                bar = self.chat_view.verticalScrollBar()
                delta = bar.maximum() - old_max
                bar.setValue(max(0, min(bar.maximum(), old_value + delta)))
                if final and token == self._chat_scroll_restore_token:
                    self._chat_scroll_restore_token = 0
            except Exception:
                pass

        delays = (0, 40, 120, 240)
        for ms in delays:
            QTimer.singleShot(ms, lambda m=ms: restore(final=(m == delays[-1])))

    def _find_user_message_index_for_resubmit(self, index):
        """
        重新提交时确定要重发哪条用户消息。

        - 如果点击的是用户气泡：重发该用户消息；
        - 如果点击的是智能体气泡：向前找到最近一条用户消息并重发。
        """
        index = self._valid_message_index(index)
        if index < 0:
            return -1

        if self.messages[index].get("role") == "user":
            return index

        for i in range(index - 1, -1, -1):
            msg = self.messages[i]
            if isinstance(msg, dict) and msg.get("role") == "user":
                return i

        return -1

    def _fallback_resubmit_text_from_message(self, msg):
        """
        老消息可能没有 _resubmit_text 元数据。
        这里尽量从显示内容里提取一份纯文本用于重新提交。
        """
        content = msg.get("content", "")

        if isinstance(content, list):
            texts = []
            for it in content:
                if isinstance(it, dict) and it.get("type") == "text":
                    texts.append(it.get("text", ""))
            text = "\n".join(texts)
        else:
            text = str(content)

        # 去掉附件摘要和图片提示，避免把说明文字当成用户输入再次发送。
        text = re.sub(r'\n?\[附件\][\s\S]*?文件内容已发送给模型，但不在聊天记录中展开显示。', '', text)
        text = re.sub(r'\n?\[已附加图片\s*\d+\s*张\]\s*', '', text)
        return text.strip()

    def _restore_pending_resubmit(self, text, file_paths, image_paths):
        self.input.setPlainText(text or "")
        self.uploaded_files = list(file_paths or [])
        self.uploaded_images = list(image_paths or [])
        self.update_attachment_list()

    def _resubmit_attachment_paths(self, msg):
        file_paths = msg.get("_uploaded_file_paths", [])
        image_paths = msg.get("_uploaded_image_paths", [])

        if not isinstance(file_paths, list):
            file_paths = []
        if not isinstance(image_paths, list):
            image_paths = []

        valid_images = []
        missing_images = []
        for pth in image_paths:
            if isinstance(pth, str) and os.path.exists(pth):
                valid_images.append(pth)
            else:
                missing_images.append(str(pth))

        valid_files = [pth for pth in file_paths if isinstance(pth, str) and pth]
        return valid_files, valid_images, missing_images

    def resubmit_message_at(self, index):
        """
        重新提交指定气泡对应的用户输入。

        说明：
        - 用户气泡：重发这条用户输入；
        - 智能体气泡：重发它前面最近一条用户输入；
        - 如果原消息带有文件/图片路径，会重新读取这些文件/图片发送；
        - 历史里仍然只保存附件摘要，不保存文件全文或图片 base64。
        """
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "提示", "智能体正在回复，请先中止或等待完成后再重新提交。")
            return

        user_index = self._find_user_message_index_for_resubmit(index)
        if user_index < 0:
            QMessageBox.warning(self, "提示", "没有找到可重新提交的用户消息。")
            return

        msg = self.messages[user_index]
        if not isinstance(msg, dict):
            return

        text = msg.get("_resubmit_text")
        if not isinstance(text, str):
            text = self._fallback_resubmit_text_from_message(msg)

        valid_files, valid_images, missing_images = self._resubmit_attachment_paths(msg)

        if not text and not valid_files and not valid_images:
            QMessageBox.warning(self, "提示", "这条消息没有可重新提交的内容。")
            return

        if missing_images:
            QMessageBox.warning(
                self,
                "部分图片不存在",
                "以下图片文件不存在，重新提交时将跳过：\n\n" + "\n".join(missing_images[:10])
            )

        # 临时恢复为待发送状态，然后复用 send()。
        try:
            self._restore_pending_resubmit(text, valid_files, valid_images)
            self.send()
        except Exception as e:
            QMessageBox.warning(self, "重新提交失败", str(e))
