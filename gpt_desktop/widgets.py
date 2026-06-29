import gc
import os
import shutil
import subprocess
import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .core import (
    get_open_file_names_cn,
    get_save_file_name_cn,
    load_thumbnail_pixmap,
    make_clickable,
    save_config,
)

class WideComboBox(QComboBox):
    """弹出菜单宽度按内容自动撑开，并在右侧显示上下小箭头。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMinimumHeight(34)

    def showPopup(self):
        view = self.view()
        fm = view.fontMetrics()
        widths = [fm.horizontalAdvance(self.itemText(i)) for i in range(self.count())]
        if widths:
            popup_width = max(max(widths) + 70, self.width(), 120)
            view.setMinimumWidth(popup_width)
        super().showPopup()

    def paintEvent(self, event):
        super().paintEvent(event)

        # 右侧画一个清晰的上下箭头，提示这里是可选择列表
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor("#c8ccd6" if self.isEnabled() else "#6a6c72"))

        x = self.width() - 18
        cy = self.height() // 2

        # 上三角
        up = [
            (x, cy - 6),
            (x - 4, cy - 1),
            (x + 4, cy - 1),
        ]
        # 下三角
        down = [
            (x, cy + 6),
            (x - 4, cy + 1),
            (x + 4, cy + 1),
        ]

        from PySide6.QtGui import QPolygon
        from PySide6.QtCore import QPoint

        painter.setBrush(QColor("#c8ccd6" if self.isEnabled() else "#6a6c72"))
        painter.drawPolygon(QPolygon([QPoint(a, b) for a, b in up]))
        painter.drawPolygon(QPolygon([QPoint(a, b) for a, b in down]))
        painter.end()


class ReferenceDropArea(QFrame):
    files_added = Signal(list)
    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(70)
        self.setStyleSheet("""
            QFrame {
                border: 2px dashed #3a3c43;
                border-radius: 8px;
                background-color: #1a1b20;
            }
            QFrame:hover {
                border-color: #1f6feb;
                background-color: #1c1e25;
            }
        """)
        layout = QVBoxLayout(self)
        label = QLabel("拖拽图片到这里  ·  点击选择文件  ·  Ctrl+V 粘贴")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color:#8b8f99; border:none; background:transparent;")
        layout.addWidget(label)

    def mousePressEvent(self, event):
        files = get_open_file_names_cn(
            self, "打开", "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*)"
        )
        if files:
            self.files_added.emit(files)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith(self.IMAGE_EXTS):
                paths.append(p)
        if paths:
            self.files_added.emit(paths)


class ThumbnailWidget(QFrame):
    """单个缩略图：右上角有删除按钮，双击预览原图。"""
    delete_requested = Signal(str)
    preview_requested = Signal(str)

    def __init__(self, path, size=64):
        super().__init__()
        self.path = path
        self.setFixedSize(size + 12, size + 12)
        self.setStyleSheet("""
            ThumbnailWidget {
                background-color: #1a1b20;
                border: 1px solid #2a2c33;
                border-radius: 6px;
            }
            ThumbnailWidget:hover { border-color: #1f6feb; }
        """)
        self.setToolTip(f"双击预览原图\n{path}")

        self.thumb = QLabel(self)
        self.thumb.setGeometry(6, 6, size, size)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("background: transparent; border: none;")
        thumb_pix = load_thumbnail_pixmap(path, size, size)
        if not thumb_pix.isNull():
            self.thumb.setPixmap(thumb_pix)

        self.del_btn = QToolButton(self)
        self.del_btn.setText("✕")
        self.del_btn.setFixedSize(20, 20)
        self.del_btn.move(self.width() - 24, 4)
        make_clickable(self.del_btn, "移除这张图片")
        self.del_btn.setStyleSheet("""
            QToolButton {
                background-color: rgba(20, 20, 24, 170);
                color: rgba(255, 255, 255, 220);
                border: none;
                border-radius: 10px;
                font-size: 12px;
                font-weight: 700;
                padding: 0;
                margin: 0;
                min-width: 20px;
                min-height: 20px;
                max-width: 20px;
                max-height: 20px;
                width: 20px;
                height: 20px;
            }
            QToolButton:hover {
                background-color: #e5484d;
                color: #ffffff;
            }
            QToolButton:pressed {
                background-color: #b4232a;
            }
        """)
        self.del_btn.clicked.connect(lambda: self.delete_requested.emit(self.path))

    def mouseDoubleClickEvent(self, event):
        self.preview_requested.emit(self.path)


class ThumbnailList(QScrollArea):
    """横向缩略图列表，每张图右上角有删除按钮。"""
    preview_requested = Signal(str)
    item_removed = Signal(str)

    def __init__(self, icon_size=64, max_height=92):
        super().__init__()
        self.icon_size = icon_size
        self.setFixedHeight(max_height)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("""
            QScrollArea {
                background-color: #15161a;
                border: 1px solid #2a2c33;
                border-radius: 6px;
            }
        """)

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self._row = QHBoxLayout(self.container)
        self._row.setContentsMargins(6, 6, 6, 6)
        self._row.setSpacing(6)
        self._row.addStretch()
        self.setWidget(self.container)

        self._widgets = {}  # path -> ThumbnailWidget

    def _remove_widget(self, widget):
        if widget is None:
            return
        try:
            self._row.removeWidget(widget)
        except Exception:
            pass
        try:
            widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        except Exception:
            pass

    def add_path(self, path):
        if path in self._widgets:
            return
        w = ThumbnailWidget(path, self.icon_size)
        w.preview_requested.connect(self.preview_requested.emit)
        w.delete_requested.connect(self._on_delete)
        # 插到 stretch 之前
        self._row.insertWidget(self._row.count() - 1, w)
        self._widgets[path] = w

    def _on_delete(self, path):
        w = self._widgets.pop(path, None)
        self._remove_widget(w)
        self.item_removed.emit(path)

    def clear(self):
        for path, w in list(self._widgets.items()):
            self._remove_widget(w)
        self._widgets.clear()

    def set_paths(self, paths):
        self.clear()
        for path in paths or []:
            if isinstance(path, str) and path:
                self.add_path(path)
        try:
            self.container.adjustSize()
            self.container.update()
            self.viewport().update()
        except Exception:
            pass

    def paths(self):
        return list(self._widgets.keys())


class ZoomableImageViewer(QScrollArea):
    """
    可缩放、可拖动的图片预览控件。

    功能：
    1. 默认适应窗口完整显示图片；
    2. 支持放大、缩小、100%、适应窗口；
    3. 鼠标滚轮缩放；
    4. 放大后按住鼠标左键拖动查看图片细节。
    """

    zoom_changed = Signal(int)

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.original_pixmap = QPixmap(image_path)
        self.zoom_factor = 1.0
        self.min_zoom = 0.05
        self.max_zoom = 8.0
        self._dragging = False
        self._drag_start_pos = None
        self._drag_start_h = 0
        self._drag_start_v = 0

        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignCenter)
        self.setBackgroundRole(self.backgroundRole())
        self.setStyleSheet("""
            QScrollArea {
                background-color: #0e0f12;
                border: 1px solid #2a2c33;
                border-radius: 8px;
            }
        """)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color:#0e0f12;")
        self.image_label.setMouseTracking(True)
        self.setWidget(self.image_label)

        self.setCursor(Qt.OpenHandCursor)
        self._apply_zoom()

    def has_image(self):
        return not self.original_pixmap.isNull()

    def _emit_zoom(self):
        try:
            self.zoom_changed.emit(int(self.zoom_factor * 100))
        except Exception:
            pass

    def _apply_zoom(self):
        if self.original_pixmap.isNull():
            self.image_label.setText("图片无法加载")
            self.image_label.adjustSize()
            return

        w = max(1, int(self.original_pixmap.width() * self.zoom_factor))
        h = max(1, int(self.original_pixmap.height() * self.zoom_factor))

        scaled = self.original_pixmap.scaled(
            w, h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.image_label.setPixmap(scaled)
        self.image_label.resize(scaled.size())
        self._emit_zoom()

    def fit_to_window(self):
        """适应当前预览窗口，完整显示图片。"""
        if self.original_pixmap.isNull():
            return

        viewport = self.viewport().size()
        if viewport.width() <= 0 or viewport.height() <= 0:
            return

        # 留一点边距，避免贴边
        margin = 24
        available_w = max(1, viewport.width() - margin)
        available_h = max(1, viewport.height() - margin)

        zw = available_w / self.original_pixmap.width()
        zh = available_h / self.original_pixmap.height()
        self.zoom_factor = max(self.min_zoom, min(zw, zh, self.max_zoom))

        self._apply_zoom()
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)

    def set_actual_size(self):
        """100% 原始大小。"""
        self.set_zoom(1.0)

    def set_zoom(self, factor):
        if self.original_pixmap.isNull():
            return

        old_zoom = self.zoom_factor
        factor = max(self.min_zoom, min(float(factor), self.max_zoom))
        if abs(factor - old_zoom) < 0.0001:
            return

        # 记录缩放前视口中心在图片中的相对位置，缩放后尽量保持中心不跳动
        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()
        viewport = self.viewport().size()

        center_x = hbar.value() + viewport.width() / 2
        center_y = vbar.value() + viewport.height() / 2

        ratio_x = center_x / max(1, self.image_label.width())
        ratio_y = center_y / max(1, self.image_label.height())

        self.zoom_factor = factor
        self._apply_zoom()

        new_center_x = ratio_x * self.image_label.width()
        new_center_y = ratio_y * self.image_label.height()

        hbar.setValue(int(new_center_x - viewport.width() / 2))
        vbar.setValue(int(new_center_y - viewport.height() / 2))

    def zoom_in(self):
        self.set_zoom(self.zoom_factor * 1.2)

    def zoom_out(self):
        self.set_zoom(self.zoom_factor / 1.2)

    def wheelEvent(self, event):
        """
        鼠标滚轮缩放。
        为了图片预览更直观，这里不要求按 Ctrl，直接滚轮缩放。
        """
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_start_pos = event.position().toPoint()
            self._drag_start_h = self.horizontalScrollBar().value()
            self._drag_start_v = self.verticalScrollBar().value()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and self._drag_start_pos is not None:
            pos = event.position().toPoint()
            delta = pos - self._drag_start_pos

            self.horizontalScrollBar().setValue(self._drag_start_h - delta.x())
            self.verticalScrollBar().setValue(self._drag_start_v - delta.y())

            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self._drag_start_pos = None
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


def show_image_preview(parent, path, title="图片预览"):
    """
    自适应屏幕的图片预览窗口。

    功能：
    1. 根据当前屏幕可用区域自动设置弹窗大小，适配 13 寸笔记本；
    2. 默认完整显示图片；
    3. 支持放大、缩小、适应窗口、100%；
    4. 鼠标滚轮缩放；
    5. 放大后按住鼠标左键拖动图片。
    """
    if not path or not os.path.exists(path):
        QMessageBox.warning(parent, "提示", "图片文件不存在。")
        return

    dlg = QDialog(parent)
    dlg.setWindowTitle(title)

    # 根据当前屏幕大小自适应弹窗尺寸，避免 13 寸笔记本打开过大
    try:
        screen = None
        if parent and parent.window() and parent.window().windowHandle():
            screen = parent.window().windowHandle().screen()
        if screen is None:
            screen = QGuiApplication.primaryScreen()

        geo = screen.availableGeometry()
        max_w = int(geo.width() * 0.86)
        max_h = int(geo.height() * 0.86)

        # 13 寸笔记本上通常比较舒服的默认上限
        target_w = min(980, max_w)
        target_h = min(760, max_h)

        dlg.resize(max(640, target_w), max(480, target_h))
    except Exception:
        dlg.resize(900, 700)

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)

    viewer = ZoomableImageViewer(path, dlg)
    layout.addWidget(viewer, 1)

    bottom = QHBoxLayout()
    bottom.setSpacing(8)

    zoom_label = QLabel("缩放：100%")
    zoom_label.setObjectName("hint")
    zoom_label.setStyleSheet("""
        QLabel {
            color: #a8b0bd;
            background: transparent;
            border: none;
            font-weight: 700;
            padding-left: 2px;
        }
    """)

    # 图片预览弹窗底部工具栏按钮专用样式。
    preview_btn_style = """
    QPushButton {
        background-color: #20232b;
        color: #f3f4f6;
        border: 1px solid #3a3d46;
        border-radius: 6px;
        padding: 7px 14px;
        min-height: 22px;
        font-weight: 700;
    }
    QPushButton:hover {
        background-color: #29364a;
        border-color: #2f81f7;
        color: #ffffff;
    }
    QPushButton:pressed {
        background-color: #1f6feb;
        border-color: #58a6ff;
        color: #ffffff;
    }
    QPushButton:disabled {
        background-color: #17191f;
        color: #6f737c;
        border-color: #2a2d35;
    }
    """

    preview_small_btn_style = """
    QPushButton {
        background-color: #20232b;
        color: #f3f4f6;
        border: 1px solid #3a3d46;
        border-radius: 6px;
        padding: 7px 0px;
        min-height: 22px;
        font-size: 15px;
        font-weight: 800;
    }
    QPushButton:hover {
        background-color: #29364a;
        border-color: #2f81f7;
        color: #ffffff;
    }
    QPushButton:pressed {
        background-color: #1f6feb;
        border-color: #58a6ff;
        color: #ffffff;
    }
    QPushButton:disabled {
        background-color: #17191f;
        color: #6f737c;
        border-color: #2a2d35;
    }
    """

    close_btn_style = """
    QPushButton {
        background-color: #1f3b66;
        color: #ffffff;
        border: 1px solid #2f81f7;
        border-radius: 6px;
        padding: 7px 16px;
        min-height: 22px;
        font-weight: 800;
    }
    QPushButton:hover {
        background-color: #2f81f7;
        border-color: #58a6ff;
        color: #ffffff;
    }
    QPushButton:pressed {
        background-color: #1a5fb4;
        border-color: #1a5fb4;
        color: #ffffff;
    }
    QPushButton:disabled {
        background-color: #17191f;
        color: #6f737c;
        border-color: #2a2d35;
    }
    """

    fit_btn = QPushButton("适应窗口")
    make_clickable(fit_btn, "让图片完整适应当前预览窗口")
    fit_btn.setMouseTracking(True)
    fit_btn.setStyleSheet(preview_btn_style)

    actual_btn = QPushButton("100%")
    make_clickable(actual_btn, "按图片原始大小显示")
    actual_btn.setMouseTracking(True)
    actual_btn.setStyleSheet(preview_btn_style)

    zoom_out_btn = QPushButton("－")
    make_clickable(zoom_out_btn, "缩小图片")
    zoom_out_btn.setMouseTracking(True)
    zoom_out_btn.setFixedWidth(44)
    zoom_out_btn.setStyleSheet(preview_small_btn_style)

    zoom_in_btn = QPushButton("＋")
    make_clickable(zoom_in_btn, "放大图片")
    zoom_in_btn.setMouseTracking(True)
    zoom_in_btn.setFixedWidth(44)
    zoom_in_btn.setStyleSheet(preview_small_btn_style)

    close_btn = QPushButton("关闭")
    make_clickable(close_btn, "关闭图片预览窗口")
    close_btn.setMouseTracking(True)
    close_btn.setStyleSheet(close_btn_style)

    bottom.addWidget(fit_btn)
    bottom.addWidget(actual_btn)
    bottom.addWidget(zoom_out_btn)
    bottom.addWidget(zoom_in_btn)
    bottom.addWidget(zoom_label)
    bottom.addStretch()
    bottom.addWidget(close_btn)

    layout.addLayout(bottom)

    viewer.zoom_changed.connect(lambda v: zoom_label.setText(f"缩放：{v}%"))
    fit_btn.clicked.connect(viewer.fit_to_window)
    actual_btn.clicked.connect(viewer.set_actual_size)
    zoom_out_btn.clicked.connect(viewer.zoom_out)
    zoom_in_btn.clicked.connect(viewer.zoom_in)
    close_btn.clicked.connect(dlg.accept)

    if not viewer.has_image():
        QMessageBox.warning(parent, "提示", "图片无法加载。")
        try:
            viewer.image_label.clear()
            viewer.original_pixmap = QPixmap()
            viewer.deleteLater()
            dlg.deleteLater()
        except Exception:
            pass
        return

    # 等窗口完成布局后再适应窗口，否则 viewport 尺寸可能还没初始化
    QTimer.singleShot(0, viewer.fit_to_window)
    QTimer.singleShot(80, viewer.fit_to_window)

    dlg.exec()

    try:
        viewer.image_label.clear()
        viewer.original_pixmap = QPixmap()
        viewer.deleteLater()
        dlg.deleteLater()
        QTimer.singleShot(200, gc.collect)
    except Exception:
        pass


# ============================================================
# 图片预览卡片交互反馈：
# 1. “下载 / 预览 / 作参考 / 再编辑”按钮增加 hover / pressed / 手型反馈
# 2. 图片卡片增加右键菜单
# 3. 点击按钮或右键功能后，在状态栏显示反馈
# ============================================================

IMAGE_CARD_BUTTON_STYLE = """
QPushButton {
    background-color: #252831;
    color: #e8e8ea;
    border: 1px solid #3a3c43;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 24px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #263246;
    border-color: #1f6feb;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #1f6feb;
    border-color: #1f6feb;
    color: #ffffff;
}
QPushButton:disabled {
    background-color: #1f2026;
    color: #6a6c72;
    border-color: #2a2c33;
}
"""

IMAGE_CARD_DANGER_BUTTON_STYLE = """
QPushButton {
    background-color: transparent;
    color: #e06c75;
    border: 1px solid #b3434c;
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 24px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #3a2226;
    border-color: #e06c75;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #b3434c;
    border-color: #e06c75;
    color: #ffffff;
}
QPushButton:disabled {
    background-color: #1f2026;
    color: #6a6c72;
    border-color: #2a2c33;
}
"""

IMAGE_CARD_MENU_STYLE = """
QMenu {
    background-color: #1a1b20;
    color: #e8e8ea;
    border: 1px solid #343741;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    padding: 7px 28px 7px 24px;
    border-radius: 5px;
}
QMenu::item:selected {
    background-color: #1f6feb;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background-color: #343741;
    margin: 6px 8px;
}
"""



class ImageCard(QFrame):
    def __init__(self, image_path, prompt, refs, on_use_ref, on_reedit):
        super().__init__()

        self.image_path = image_path
        self.prompt = prompt or ""
        self.refs = list(refs or [])
        self.source_label = self._source_label_from_prompt(self.prompt)
        self._on_use_ref = on_use_ref
        self._on_reedit = on_reedit
        self._thumbnail_cache_path = ""

        self.setObjectName("card")
        self.setFixedWidth(230)
        self.setContextMenuPolicy(Qt.DefaultContextMenu)

        self.setStyleSheet("""
            QFrame#card {
                background-color: #1a1b20;
                border: 1px solid #25272e;
                border-radius: 10px;
            }
            QFrame#card:hover {
                border-color: #1f6feb;
                background-color: #1d2028;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(9)

        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setFixedSize(210, 210)
        make_clickable(self.thumb_label, "点击预览原图")
        self.thumb_label.setText("")
        self.thumb_label.setStyleSheet("""
            QLabel {
                background-color:#0e0f12;
                color:#8b949e;
                font-size:12px;
                border: 1px solid #25272e;
                border-radius:6px;
            }
            QLabel:hover {
                border-color: #1f6feb;
                background-color: #111827;
            }
        """)

        self.set_thumbnail_from_cache()

        display_prompt = self._display_prompt()
        tooltip_parts = [
            "左键双击或点“预览”查看大图",
            "右键打开更多操作",
        ]
        if self.source_label:
            tooltip_parts.append(f"来源：{self.source_label}")
        tooltip_parts.append("")
        tooltip_parts.append(f"提示词：\n{display_prompt}")
        tooltip_parts.append("")
        tooltip_parts.append("参考图：\n" + "\n".join(self.refs))
        tooltip = "\n".join(tooltip_parts)
        self.thumb_label.setToolTip(tooltip)
        self.setToolTip(tooltip)
        self.thumb_label.mouseDoubleClickEvent = lambda ev: self.preview_image()
        layout.addWidget(self.thumb_label)
        layout.addSpacing(2)

        if self.source_label:
            source = QLabel(self.source_label)
            source.setFixedHeight(22)
            source.setAlignment(Qt.AlignCenter)
            source.setStyleSheet("""
                QLabel {
                    color: #d6e4ff;
                    background: #1f3b66;
                    border: 1px solid #2f81f7;
                    border-radius: 6px;
                    font-size: 11px;
                    font-weight: 700;
                    padding: 2px 6px;
                }
            """)
            layout.addWidget(source)

        preview_text = display_prompt
        preview = QLabel(preview_text[:44] + ("..." if len(preview_text) > 44 else ""))
        preview.setFixedHeight(32 if self.source_label else 38)
        preview.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        preview.setStyleSheet("""
            QLabel {
                color:#9aa0a6;
                font-size:11px;
                line-height:16px;
                background:#1a1b20;
                border:none;
                padding:2px 0 0 0;
                margin:0;
            }
        """)
        preview.setWordWrap(True)
        layout.addWidget(preview)

        def add_button_row(*buttons):
            row = QHBoxLayout()
            row.setSpacing(6)
            for button in buttons:
                row.addWidget(button)
            layout.addLayout(row)

        download_btn = self.make_button("下载", "保存这张图片到本地")
        open_btn = self.make_button("预览", "打开大图预览窗口")
        add_button_row(download_btn, open_btn)

        ref_btn = self.make_button("作参考", "把这张图片加入参考图")
        edit_btn = self.make_button("再编辑", "载入这张图的提示词和参考图继续编辑")
        add_button_row(ref_btn, edit_btn)

        delete_btn = self.make_button(
            "删除这张图片",
            "从历史记录和本地缓存中删除这张图片",
            style=IMAGE_CARD_DANGER_BUTTON_STYLE,
        )
        delete_btn.setObjectName("danger")
        add_button_row(delete_btn)

        download_btn.clicked.connect(self.download)
        open_btn.clicked.connect(self.preview_image)
        ref_btn.clicked.connect(self.use_as_reference)
        edit_btn.clicked.connect(self.reedit_image)
        delete_btn.clicked.connect(self.delete_this_image)

    def _source_label_from_prompt(self, prompt):
        return ""

    def _display_prompt(self):
        return self.prompt or ""

    def set_thumbnail_from_cache(self, cache_path=None):
        try:
            if cache_path and cache_path == self._thumbnail_cache_path:
                return

            pix = QPixmap(str(cache_path)) if cache_path else load_thumbnail_pixmap(
                self.image_path,
                210,
                210,
                generate_missing=False,
            )
            if not pix.isNull():
                self._thumbnail_cache_path = cache_path or ""
                self.thumb_label.setText("")
                self.thumb_label.setPixmap(pix)
        except Exception:
            pass

    def find_image_tab(self):
        try:
            from .image_tab import ImageGeneratorTab

            w = self
            for _ in range(20):
                if w is None:
                    return None
                if isinstance(w, ImageGeneratorTab):
                    return w
                w = w.parentWidget()
        except Exception:
            pass
        return None

    def set_status(self, text):
        try:
            tab = self.find_image_tab()
            if tab is not None and hasattr(tab, "bar"):
                tab.bar.set_status(text)
                return
        except Exception:
            pass

        try:
            win = self.window()
            if hasattr(win, "statusBar"):
                win.statusBar().showMessage(text, 2500)
        except Exception:
            pass

    def make_button(self, text, tooltip="", style="default"):
        btn = QPushButton(text)
        make_clickable(btn, tooltip or text)
        if style == "default":
            style = IMAGE_CARD_BUTTON_STYLE
        if style:
            btn.setStyleSheet(style)
        btn.setMinimumHeight(30)
        return btn

    def open_in_file_manager(self):
        try:
            if not self.image_path or not os.path.exists(self.image_path):
                return False

            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", self.image_path])
            elif os.name == "nt":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(self.image_path)])
            else:
                folder = os.path.dirname(self.image_path)
                subprocess.Popen(["xdg-open", folder])

            return True
        except Exception:
            return False

    def download(self):
        try:
            tab = self.find_image_tab()
            image_cfg = tab.config.setdefault("image", {}) if tab is not None else {}
            start_dir = image_cfg.get("last_save_dir", "")
            target = get_save_file_name_cn(
                self,
                "保存图片",
                os.path.basename(self.image_path),
                "图片文件 (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tiff);;所有文件 (*)",
                start_dir=start_dir,
            )
            if target:
                shutil.copy(self.image_path, target)
                if tab is not None:
                    tab._set_image_config(last_save_dir=os.path.dirname(target))
                    save_config(tab.config)
                self.set_status(f"已下载图片：{os.path.basename(target)}")
            else:
                self.set_status("已取消下载")
        except Exception as e:
            self.set_status(f"下载失败：{e}")
            try:
                QMessageBox.warning(self, "下载失败", str(e))
            except Exception:
                pass

    def preview_image(self):
        try:
            self.set_status("正在打开图片预览...")
            show_image_preview(self, self.image_path)
            self.set_status("图片预览已关闭")
        except Exception as e:
            self.set_status(f"预览失败：{e}")

    def use_as_reference(self):
        try:
            if callable(self._on_use_ref):
                self._on_use_ref(self.image_path)
                self.set_status("已加入参考图")
        except Exception as e:
            self.set_status(f"加入参考图失败：{e}")

    def reedit_image(self):
        try:
            if callable(self._on_reedit):
                self._on_reedit(self.prompt, self.refs)
                self.set_status("已载入提示词，可继续编辑")
        except Exception as e:
            self.set_status(f"再编辑失败：{e}")

    def copy_image_path(self):
        try:
            QGuiApplication.clipboard().setText(self.image_path or "")
            self.set_status("已复制图片路径")
        except Exception as e:
            self.set_status(f"复制路径失败：{e}")

    def open_image_folder(self):
        try:
            if self.open_in_file_manager():
                self.set_status("已打开图片所在文件夹")
            else:
                self.set_status("打开文件夹失败")
        except Exception as e:
            self.set_status(f"打开文件夹失败：{e}")

    def delete_this_image(self):
        tab = self.find_image_tab()
        if tab is None:
            try:
                QMessageBox.warning(self, "提示", "没有找到图片生成页面，无法删除。")
            except Exception:
                pass
            return

        try:
            tab.delete_generated_image(self.image_path)
        except Exception as e:
            try:
                QMessageBox.warning(self, "删除失败", str(e))
            except Exception:
                pass

    def contextMenuEvent(self, event):
        try:
            menu = QMenu(self)
            try:
                menu.setStyleSheet(IMAGE_CARD_MENU_STYLE)
            except Exception:
                pass

            act_download = menu.addAction("下载图片")
            act_preview = menu.addAction("预览图片")
            menu.addSeparator()
            act_ref = menu.addAction("作参考图")
            act_reedit = menu.addAction("再编辑")
            menu.addSeparator()
            act_copy_path = menu.addAction("复制图片路径")
            act_open_folder = menu.addAction("打开所在文件夹")
            menu.addSeparator()
            act_delete = menu.addAction("删除这张图片")

            try:
                action = menu.exec(event.globalPos())

                if action == act_download:
                    self.download()
                elif action == act_preview:
                    self.preview_image()
                elif action == act_ref:
                    self.use_as_reference()
                elif action == act_reedit:
                    self.reedit_image()
                elif action == act_copy_path:
                    self.copy_image_path()
                elif action == act_open_folder:
                    self.open_image_folder()
                elif action == act_delete:
                    self.delete_this_image()
            finally:
                menu.deleteLater()
            event.accept()
        except Exception:
            try:
                return super().contextMenuEvent(event)
            except Exception:
                pass

    def enterEvent(self, event):
        try:
            self.setCursor(Qt.PointingHandCursor)
            self.set_status("右键图片卡片可打开更多操作")
        except Exception:
            pass
        try:
            return super().enterEvent(event)
        except Exception:
            pass

    def leaveEvent(self, event):
        try:
            self.unsetCursor()
        except Exception:
            pass
        try:
            return super().leaveEvent(event)
        except Exception:
            pass


class ProviderModelBar(QWidget):
    """统一的 [厂商] [模型] [刷新] [设置] 控件条。"""
    provider_changed = Signal(str)
    model_changed = Signal(str)
    refresh_clicked = Signal()
    settings_clicked = Signal()

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        lbl_p = QLabel("厂商")
        lbl_p.setObjectName("field_label")
        layout.addWidget(lbl_p)

        self.provider_combo = WideComboBox()
        self.provider_combo.setMinimumWidth(180)
        layout.addWidget(self.provider_combo)

        lbl_m = QLabel("模型")
        lbl_m.setObjectName("field_label")
        layout.addWidget(lbl_m)

        self.model_combo = WideComboBox()
        self.model_combo.setEditable(False)
        self.model_combo.setMinimumWidth(280)
        self.model_combo.setToolTip("点击选择模型，刷新可重新拉取列表")
        layout.addWidget(self.model_combo)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setObjectName("ghost")
        self.refresh_btn.setToolTip("从接口重新拉取模型列表")
        layout.addWidget(self.refresh_btn)

        self.settings_btn = QPushButton("设置")
        self.settings_btn.setObjectName("ghost")
        layout.addWidget(self.settings_btn)

        # 设置按钮改为由各功能页右上角单独放置，这里隐藏，避免误点
        self.settings_btn.setVisible(False)

        self.status_label = QLabel("")
        self.status_label.setObjectName("hint")
        self.status_label.setMinimumWidth(160)
        layout.addWidget(self.status_label)

        layout.addStretch()

        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        self.refresh_btn.clicked.connect(self.refresh_clicked.emit)
        self.settings_btn.clicked.connect(self.settings_clicked.emit)

    def _on_provider_changed(self, idx):
        pid = self.provider_combo.itemData(idx) or ""
        self.provider_changed.emit(pid)

    def _on_model_changed(self, text):
        # 加载状态时不触发
        if text == "正在加载模型..." or text.startswith("（"):
            return
        self.model_changed.emit(text)

    def set_status(self, text):
        self.status_label.setText(text)

    def set_providers(self, providers, current_id):
        self.provider_combo.blockSignals(True)
        self.provider_combo.clear()
        if not providers:
            self.provider_combo.addItem("（未配置厂商，请点击设置）", "")
        else:
            for p in providers:
                self.provider_combo.addItem(p.get("name", "未命名"), p.get("id", ""))
            target = 0
            for i in range(self.provider_combo.count()):
                if self.provider_combo.itemData(i) == current_id:
                    target = i
                    break
            self.provider_combo.setCurrentIndex(target)
        self.provider_combo.blockSignals(False)

    def current_provider_id(self):
        return self.provider_combo.currentData() or ""

    def set_models(self, models, current_model):
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        if not models:
            self.model_combo.addItem("（暂无模型，请刷新）")
            self.model_combo.setEnabled(False)
        else:
            self.model_combo.setEnabled(True)
            self.model_combo.addItems(models)
            target = 0
            if current_model:
                for i, m in enumerate(models):
                    if m == current_model:
                        target = i
                        break
            self.model_combo.setCurrentIndex(target)
        self.model_combo.blockSignals(False)

    def set_models_loading(self):
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem("正在加载模型...")
        self.model_combo.setEnabled(True)
        self.model_combo.blockSignals(False)

    def current_model(self):
        text = self.model_combo.currentText().strip()
        if not text or text == "正在加载模型..." or text.startswith("（"):
            return ""
        return text
