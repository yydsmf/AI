import mimetypes
import os
import re
import uuid

from PySide6.QtGui import QGuiApplication

from .core import (
    IMAGE_DIR,
    format_file_size,
    get_open_file_names_cn,
    image_file_to_base64,
    read_uploaded_files_text,
)


class AgentAttachmentsMixin:
    """智能体附件上传、清理和用户消息构造。"""

    def add_dropped_paths(self, paths):
        """
        把拖入的路径加入附件。
        图片进入 uploaded_images，普通文件进入 uploaded_files。
        """
        try:
            images, files = self.classify_attachment_paths(paths)

            changed = self._add_attachments(
                image_paths=images,
                file_paths=files,
                show_status=False,
            )

            if changed:
                try:
                    self.bar.set_status(
                        f"已拖入附件：图片 {len(images)} 张，文件 {len(files)} 个"
                    )
                except Exception:
                    pass

            return changed
        except Exception:
            return False

    def classify_attachment_paths(self, paths):
        images = []
        files = []

        for path in paths or []:
            try:
                if not path or not os.path.isfile(path):
                    continue

                lower = path.lower()
                if lower.endswith(self.IMAGE_ATTACHMENT_EXTS):
                    images.append(path)
                else:
                    files.append(path)
            except Exception:
                pass

        return images, files

    # ---- 图片附件 ----


    def upload_files(self):
        """上传文件。当前以文本方式读取并附加到下一条消息中。"""
        files = get_open_file_names_cn(
            self,
            "打开",
            "文档文件 (*.txt *.md *.py *.js *.ts *.json *.csv *.log *.html *.css *.xml *.yaml *.yml *.doc *.docx *.pdf);;所有文件 (*)"
        )
        if not files:
            return

        self._add_attachments(file_paths=files)

    def _read_uploaded_files_text(self):
        """
        读取已上传文件内容。

        支持：
        - .docx：使用 python-docx 提取段落和表格文本
        - .pdf：使用 pypdf 提取文本
        - .doc：暂不支持，提示另存为 .docx
        - 其他文件：按普通文本读取

        限制：
        - 单文件超过 10MB 时不读取正文，直接提示用户
        """
        return read_uploaded_files_text(self.uploaded_files)

    def upload_images(self):
        files = get_open_file_names_cn(
            self, "打开", "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*)"
        )
        if not files:
            return

        self._add_attachments(image_paths=files, cleanup_file_note=False)

    def _on_image_removed(self, path):
        """
        删除图片附件，只改 uploaded_images，不碰 uploaded_files。
        """
        try:
            self.uploaded_images = self._paths_without_target(self.uploaded_images, path)
            self.update_attachment_list()
            self.set_clean_status("已移除附件")
        except Exception:
            pass

    def clear_all_attachments(self, show_status=True):
        """
        清空当前待发送的所有附件：图片 + 文件。
        """
        try:
            self.uploaded_files = []
            self.uploaded_images = []

            self.image_list.clear()

            try:
                self.update_attachment_list()
            except Exception:
                pass

            if show_status:
                try:
                    self.bar.set_status("已清空全部附件")
                except Exception:
                    pass

        except Exception:
            pass

    def paste_image_from_clipboard(self):
        """
        智能体页粘贴附件。
        URL 是图片则加入图片附件，URL 是普通文件则加入文件附件；
        无 URL 但有图片数据时，保存为临时图片附件。
        """
        cb = QGuiApplication.clipboard()
        mime = cb.mimeData()

        if mime.hasUrls():
            paths = [u.toLocalFile() for u in mime.urls()]
            image_paths, file_paths = self.classify_attachment_paths(paths)

            if self._add_attachments(image_paths=image_paths, file_paths=file_paths):
                return

        if mime.hasImage():
            image = cb.image()
            path = os.path.join(IMAGE_DIR, f"agent_clipboard_{uuid.uuid4().hex}.png")
            image.save(path)
            self._add_attachments(image_paths=[path], cleanup_file_note=False)

    def cleanup_uploaded_file_note(self):
        """
        清理输入框里的 [已添加文件...] 标记。
        """
        try:
            old = self.input.toPlainText()
            new = re.sub(
                r"\[已添加文件\s*\d+\s*个\s*[:：]\s*[^\]]+\]\s*",
                "",
                old
            ).strip()

            if new != old.strip():
                self.input.blockSignals(True)
                self.input.setPlainText(new)
                self.input.blockSignals(False)
                self.input.moveCursor(self.input.textCursor().End)
                self.adjust_input_height()
                self.schedule_agent_input_draft_save(120)
        except Exception:
            try:
                self.input.blockSignals(False)
            except Exception:
                pass

    def set_clean_status(self, text=""):
        """
        状态栏不显示具体文件名，避免右侧出现不可操作长文本。
        """
        try:
            self.bar.set_status(text or "")
        except Exception:
            pass

    def update_attachment_list(self):
        try:
            self.image_list.render()
        except Exception:
            pass

    def _add_unique_existing_paths(self, target_list, paths):
        added = False
        for path in paths or []:
            try:
                if path and os.path.isfile(path) and path not in target_list:
                    target_list.append(path)
                    added = True
            except Exception:
                pass
        return added

    def _add_attachments(self, image_paths=None, file_paths=None, cleanup_file_note=True, show_status=True):
        added_images = self._add_unique_existing_paths(self.uploaded_images, image_paths or [])
        added_files = self._add_unique_existing_paths(self.uploaded_files, file_paths or [])
        added = added_images or added_files

        if not added:
            return False

        if cleanup_file_note and added_files:
            self.cleanup_uploaded_file_note()
        self.update_attachment_list()
        if show_status:
            self.set_clean_status("已添加附件")
        return True

    def _paths_without_target(self, paths, path):
        try:
            target = os.path.abspath(path)
        except Exception:
            target = path

        kept = []
        for item in list(paths or []):
            try:
                if os.path.abspath(item) == target:
                    continue
            except Exception:
                if item == path:
                    continue
            kept.append(item)
        return kept

    def remove_uploaded_file_path(self, path):
        """
        删除文件附件，只改 uploaded_files，不碰 uploaded_images。
        """
        try:
            self.uploaded_files = self._paths_without_target(self.uploaded_files, path)
            self.update_attachment_list()
            self.set_clean_status("已移除附件")
        except Exception:
            pass

    def _strip_uploaded_file_note(self, text):
        """
        去掉输入框里自动插入的：
        [已添加文件 1 个：main.py]

        这个提示只是给用户看的，不需要发送给模型，也不需要保存进会话正文。
        """
        if not isinstance(text, str):
            return ""

        return re.sub(
            r'\[已添加文件\s*\d+\s*个\s*[:：]\s*[^\]]+\]\s*',
            '',
            text
        ).strip()

    def _uploaded_files_display_text(self):
        """
        只用于聊天窗口显示和会话历史保存。

        注意：
        - 不包含文件正文；
        - 不会撑大聊天记录；
        - 完整文件内容只在本次 API 请求里临时发送给模型。
        """
        if not self.uploaded_files:
            return ""

        lines = ["[附件]"]

        for path in self.uploaded_files:
            try:
                name = os.path.basename(path)
                size = os.path.getsize(path) if path and os.path.exists(path) else 0
                size_text = format_file_size(size)
                if size_text:
                    lines.append(f"{name}    {size_text}")
                else:
                    lines.append(name)
            except Exception:
                lines.append(str(path))

        lines.append("文件内容已发送给模型，但不在聊天记录中展开显示。")
        return "\n".join(lines)

    def build_user_message(self, text, include_uploaded_file_content=True, include_uploaded_images=True):
        """
        构造用户消息。

        include_uploaded_file_content=True:
            用于 API 请求，包含完整文件内容。

        include_uploaded_file_content=False:
            用于聊天窗口和历史保存，只包含附件摘要。

        include_uploaded_images=True:
            用于 API 请求，包含图片 base64。

        include_uploaded_images=False:
            用于聊天窗口和历史保存，只显示图片数量，不保存 base64。

        注意：
        - 只有展示版消息会附带 _resubmit_text / _uploaded_file_paths / _uploaded_image_paths；
        - API 消息不能带这些自定义字段，避免接口拒绝。
        """
        base_text = self._strip_uploaded_file_note(text)
        final_text = base_text

        if include_uploaded_file_content:
            file_text = self._read_uploaded_files_text()
            if file_text:
                final_text = (final_text + "\n\n" + file_text).strip()
        else:
            file_display_text = self._uploaded_files_display_text()
            if file_display_text:
                final_text = (final_text + "\n\n" + file_display_text).strip()

        uploaded_images = list(self.uploaded_images)
        uploaded_files = list(self.uploaded_files)

        if not uploaded_images:
            msg = {"role": "user", "content": final_text}

            # 展示版消息保存重新提交需要的元数据。
            if not include_uploaded_file_content and not include_uploaded_images:
                msg["_resubmit_text"] = base_text
                msg["_uploaded_file_paths"] = uploaded_files
                msg["_uploaded_image_paths"] = uploaded_images

            return msg

        if include_uploaded_images:
            content = [{"type": "text", "text": final_text}]
            for pth in uploaded_images:
                mime = mimetypes.guess_type(pth)[0] or "image/png"
                b64 = image_file_to_base64(pth)
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"}
                })
            return {"role": "user", "content": content}

        # 历史保存 / 界面显示：不保存图片 base64，只显示数量。
        if uploaded_images:
            final_text = (final_text + f"\n\n[已附加图片 {len(uploaded_images)} 张]").strip()

        msg = {
            "role": "user",
            "content": final_text,
            "_resubmit_text": base_text,
            "_uploaded_file_paths": uploaded_files,
            "_uploaded_image_paths": uploaded_images,
        }
        return msg
