import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .core import format_cache_size, make_clickable
from .widgets import ThumbnailWidget


AGENT_ATTACHMENT_CLOSE_BUTTON_STYLE = """
QPushButton {
    background-color: rgba(20, 20, 24, 170);
    color: rgba(255, 255, 255, 220);
    border: none;
    border-radius: 10px;
    padding: 0px;
    margin: 0px;
    font-size: 12px;
    font-weight: 700;
    min-width: 20px;
    min-height: 20px;
    max-width: 20px;
    max-height: 20px;
}
QPushButton:hover {
    background-color: #e5484d;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #b4232a;
}
"""

AGENT_FILE_TYPE_COLORS = {
    **dict.fromkeys((".doc", ".docx"), "#2b6cb0"),
    ".pdf": "#c53030",
    **dict.fromkeys((".txt", ".md", ".log"), "#4a5568"),
    **dict.fromkeys(
        (".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".csv", ".xls", ".xlsx"),
        "#2f855a",
    ),
}


class AgentAttachmentCardBase(QFrame):
    def make_close_button(self, tooltip):
        btn = QPushButton("×", self)
        make_clickable(btn, tooltip)
        btn.setFixedSize(20, 20)
        btn.setStyleSheet(AGENT_ATTACHMENT_CLOSE_BUTTON_STYLE)
        return btn

    def _place_close(self):
        try:
            self.close_btn.move(self.width() - self.close_btn.width() - 4, 4)
            self.close_btn.raise_()
            self.close_btn.show()
        except Exception:
            pass


class AgentFileAttachmentCard(AgentAttachmentCardBase):
    """
    智能体文件附件卡片。
    删除按钮是右上角悬浮小 x，和图片缩略图风格一致。
    """

    delete_requested = Signal(str)

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path

        self.setObjectName("agent_file_attachment_card")
        self.setFixedSize(194, 68)
        self.setToolTip(path)

        self.setStyleSheet("""
            QFrame#agent_file_attachment_card {
                background-color: #1b1d23;
                border: 1px solid #343741;
                border-radius: 8px;
            }
            QFrame#agent_file_attachment_card:hover {
                border-color: #4b5563;
                background-color: #20232b;
            }
        """)

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 10, 8)
        root.setSpacing(8)

        ext = self._ext_label(path)
        color = self._type_color(path)

        icon = QLabel(ext)
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(42, 42)
        icon.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 7px;
                font-size: 11px;
                font-weight: 800;
            }}
        """)

        text_box = QWidget()
        text_box.setStyleSheet("background: transparent; border: none;")
        text_lay = QVBoxLayout(text_box)
        text_lay.setContentsMargins(0, 0, 0, 0)
        text_lay.setSpacing(2)

        name = os.path.basename(path)
        shown = self._elide(name, 118)

        name_label = QLabel(shown)
        name_label.setToolTip(path)
        name_label.setStyleSheet("""
            QLabel {
                color: #f3f4f6;
                background: transparent;
                border: none;
                font-size: 12px;
                font-weight: 700;
            }
        """)

        size_label = QLabel(self._size_text(path))
        size_label.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                background: transparent;
                border: none;
                font-size: 11px;
            }
        """)

        text_lay.addWidget(name_label)
        text_lay.addWidget(size_label)

        root.addWidget(icon)
        root.addWidget(text_box, 1)

        self.close_btn = self.make_close_button("移除这个文件")
        self.close_btn.setObjectName("agent_file_attachment_close")
        self.close_btn.clicked.connect(lambda: self.delete_requested.emit(self.path))
        self._place_close()

    def resizeEvent(self, event):
        try:
            super().resizeEvent(event)
        except Exception:
            pass
        self._place_close()

    def _elide(self, text, width):
        try:
            return self.fontMetrics().elidedText(str(text), Qt.ElideMiddle, int(width))
        except Exception:
            text = str(text)
            return text if len(text) <= 18 else text[:8] + "..." + text[-7:]

    def _ext_label(self, path):
        try:
            ext = os.path.splitext(path)[1].lower().lstrip(".")
            return (ext or "FILE")[:5].upper()
        except Exception:
            return "FILE"

    def _type_color(self, path):
        try:
            ext = os.path.splitext(path)[1].lower()
        except Exception:
            ext = ""

        return AGENT_FILE_TYPE_COLORS.get(ext, "#5a67d8")

    def _size_text(self, path):
        try:
            return format_cache_size(os.path.getsize(path))
        except Exception:
            return "文件"


class AgentAttachmentList(QScrollArea):
    """
    统一附件栏。

    数据来源只看：
    - owner.uploaded_files
    - owner.uploaded_images

    UI 每次 render() 整体重建。
    所以删除图片不会误删文件，删除文件也不会误删图片。
    """

    preview_requested = Signal(str)
    item_removed = Signal(str)

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner

        self.setObjectName("agent_attachment_list")
        self.setFixedHeight(84)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)

        self.setStyleSheet("""
            QScrollArea#agent_attachment_list {
                background-color: #15161a;
                border: 1px solid #2a2c33;
                border-radius: 6px;
            }
            QScrollArea#agent_attachment_list QWidget {
                background: transparent;
            }
        """)

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.row = QHBoxLayout(self.container)
        self.row.setContentsMargins(6, 6, 6, 6)
        self.row.setSpacing(8)
        self.row.addStretch()

        self.setWidget(self.container)
        self.hide()

    def _clear_row_widgets(self):
        while self.row.count():
            item = self.row.takeAt(0)
            widget = item.widget()
            self._delete_row_widget(widget)

    def _delete_row_widget(self, widget):
        if widget is None:
            return
        widget.setParent(None)
        widget.deleteLater()

    def _valid_unique_paths(self, paths):
        result = []
        seen = set()
        for path in list(paths or []):
            try:
                if not path or not os.path.isfile(path):
                    continue
                key = os.path.abspath(path)
                if key in seen:
                    continue
                result.append(path)
                seen.add(key)
            except Exception:
                pass
        return result

    def _clean_paths(self):
        owner = self.owner
        owner.uploaded_files = self._valid_unique_paths(owner.uploaded_files)
        owner.uploaded_images = self._valid_unique_paths(owner.uploaded_images)

    def render(self):
        try:
            self._clean_paths()
            self._clear_row_widgets()

            owner = self.owner
            files = list(owner.uploaded_files)
            images = list(owner.uploaded_images)

            if not files and not images:
                self.hide()
                return

            for path in files:
                card = AgentFileAttachmentCard(path)
                card.delete_requested.connect(owner.remove_uploaded_file_path)
                self.row.addWidget(card)

            for path in images:
                card = ThumbnailWidget(path, size=56)
                card.preview_requested.connect(self.preview_requested.emit)
                card.delete_requested.connect(self.item_removed.emit)
                self.row.addWidget(card)

            self.row.addStretch()

            clear_btn = QPushButton("全部清空")
            clear_btn.setObjectName("danger")
            make_clickable(clear_btn, "清空当前待发送的全部图片附件和文件附件")
            clear_btn.setMinimumHeight(30)
            clear_btn.setMinimumWidth(86)
            clear_btn.clicked.connect(owner.clear_all_attachments)
            self.row.addWidget(clear_btn)

            self.show()
        except Exception:
            pass

    def clear(self):
        try:
            self._clear_row_widgets()
            self.hide()
        except Exception:
            pass

    def paths(self):
        return list(self.owner.uploaded_images)
