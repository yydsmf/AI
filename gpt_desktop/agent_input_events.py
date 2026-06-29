from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QGuiApplication


class AgentInputEventsMixin:
    """智能体输入框高度、拖拽、粘贴和快捷键事件。"""

    def adjust_input_height(self):
        """根据输入内容自动调整输入框高度。"""
        try:
            doc = self.input.document()
            doc.setTextWidth(self.input.viewport().width())
            content_height = int(doc.size().height()) + 12
            target_height = max(
                self.input_min_height,
                min(self.input_max_height, content_height)
            )
            self.input.setFixedHeight(target_height)

            if target_height >= self.input_max_height:
                self.input.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            else:
                self.input.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        except Exception:
            pass

    def eventFilter(self, obj, event):
        """
        智能体输入框快捷键：

        - Enter：发送
        - Shift+Enter：换行
        - Ctrl+V / Command+V：
            1. 如果剪贴板是文件 URL，优先按原始文件路径添加；
            2. 图片文件路径添加为图片附件；
            3. 普通文件路径添加为文件附件；
            4. 如果没有 URL 但有图片数据，才按截图/剪贴板图片处理；
            5. 普通文本放行给 QTextEdit 正常粘贴。
        """
        try:
            try:
                if obj is self.chat_view or obj is self.chat_view.viewport():
                    if event.type() == QEvent.MouseMove:
                        pos = event.position().toPoint()
                        href = self.chat_view.anchorAt(pos)
                        if href:
                            self.chat_view.viewport().setCursor(Qt.PointingHandCursor)
                        elif self._chat_mouse_over_text(pos):
                            self.chat_view.viewport().setCursor(Qt.IBeamCursor)
                        else:
                            self.chat_view.viewport().unsetCursor()
                        return False
                    if event.type() in (QEvent.Leave, QEvent.FocusOut):
                        self.chat_view.viewport().unsetCursor()
                        return False
                    if event.type() == QEvent.ContextMenu:
                        self.show_chat_context_menu(event.globalPos())
                        return True
            except Exception:
                pass

            if (obj is self.chat_view or obj is self.chat_view.viewport()) and event.type() in (
                QEvent.KeyPress,
                QEvent.ShortcutOverride,
            ):
                key = event.key()
                modifiers = event.modifiers()
                if key == Qt.Key_C and (modifiers & Qt.ControlModifier or modifiers & Qt.MetaModifier):
                    if self.copy_selected_chat_text():
                        try:
                            event.accept()
                        except Exception:
                            pass
                        return True

            is_input_or_viewport = obj is self.input
            if not is_input_or_viewport:
                try:
                    is_input_or_viewport = obj is self.input.viewport()
                except Exception:
                    is_input_or_viewport = False

            if is_input_or_viewport and event.type() in (QEvent.DragEnter, QEvent.DragMove):
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True

            if is_input_or_viewport and event.type() == QEvent.Drop:
                paths = []
                try:
                    for url in event.mimeData().urls():
                        path = url.toLocalFile()
                        if path:
                            paths.append(path)
                except Exception:
                    paths = []

                if paths and self.add_dropped_paths(paths):
                    event.acceptProposedAction()
                    return True

            if obj is self.input and event.type() == event.Type.KeyPress:
                key = event.key()
                modifiers = event.modifiers()

                # Ctrl+V / Command+V：优先处理文件 URL。
                if key == Qt.Key_V and (modifiers & Qt.ControlModifier or modifiers & Qt.MetaModifier):
                    cb = QGuiApplication.clipboard()
                    mime = cb.mimeData()

                    # 1. 优先处理从 Finder / 文件管理器复制的原始文件路径。
                    if mime.hasUrls():
                        paths = [u.toLocalFile() for u in mime.urls()]
                        image_paths, file_paths = self.classify_attachment_paths(paths)

                        if self._add_attachments(image_paths=image_paths, file_paths=file_paths):
                            return True

                    # 2. 没有 URL 时，才处理真正的剪贴板图片，例如截图。
                    if mime.hasImage():
                        self.paste_image_from_clipboard()
                        return True

                    # 3. 普通文本不拦截。
                    return False

                if key in (Qt.Key_Return, Qt.Key_Enter):
                    # Shift + Enter：插入换行
                    if modifiers & Qt.ShiftModifier:
                        cursor = self.input.textCursor()
                        cursor.insertText("\n")
                        self.input.setTextCursor(cursor)
                        self.adjust_input_height()
                        return True

                    # 只有 Enter：发送
                    self.send()
                    return True
        except Exception:
            pass

        return super().eventFilter(obj, event)
