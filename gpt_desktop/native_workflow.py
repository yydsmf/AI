import copy
import json
import math
import os
import uuid

from PySide6.QtCore import QLineF, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsProxyWidget,
    QGraphicsScene,
    QGraphicsView,
    QGraphicsPixmapItem,
    QHBoxLayout,
    QFileDialog,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .core import (
    VIDEO_HISTORY_FILE,
    get_provider,
    load_json_file,
    load_thumbnail_pixmap,
    load_video_thumbnail_pixmap,
    now_str,
    open_local_file,
    save_config,
    save_json_file,
)
from .chat_worker import ChatWorker
from .image_history_store import (
    append_image_result,
    iter_image_items as iter_image_history_items,
    migrate_json_history_once,
)
from .model_list_loader import ModelListRequestPool
from .widgets import WideComboBox, show_image_preview
from .workers import ImageWorker, ModelListWorker, VideoWorker


class WorkflowComboBox(WideComboBox):
    """节点内紧凑下拉框：用原生菜单避免临时弹窗导致 macOS 偶发闪退。"""

    def showPopup(self):
        if self.count() <= 0:
            return

        menu = QMenu()
        menu.setWindowFlags(menu.windowFlags() | Qt.Popup)
        menu.setStyleSheet("""
            QMenu {
                background-color: #151922;
                color: #e6edf5;
                border: 1px solid #343b46;
                padding: 2px;
                font-size: 12px;
            }
            QMenu::item {
                padding: 4px 22px 4px 8px;
                min-height: 18px;
            }
            QMenu::item:selected {
                background-color: #2f80ed;
                color: #ffffff;
            }
        """)
        fm = self.fontMetrics()
        menu_width = max(self.width(), 96)
        current_index = self.currentIndex()
        for index in range(self.count()):
            text = self.itemText(index) or " "
            menu_width = max(menu_width, min(fm.horizontalAdvance(text) + 38, 260))
            action = menu.addAction(text)
            action.setData(index)
            action.setCheckable(True)
            action.setChecked(index == current_index)

        menu.setMinimumWidth(menu_width)
        action = menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
        if action is None:
            return
        index = action.data()
        if isinstance(index, int):
            self.setCurrentIndex(index)


NODE_CATALOG = {
    "prompt_input": {
        "title": "提示词输入节点",
        "accent": "#2f80ed",
        "inputs": [],
        "outputs": [{"id": "text", "label": "文本", "data_type": "text"}],
        "value": "一段提示词",
    },
    "upload_image": {
        "title": "上传图片节点",
        "accent": "#d29922",
        "inputs": [],
        "outputs": [{"id": "image", "label": "图片", "data_type": "image"}],
        "value": "请选择本地图片",
    },
    "text_to_image": {
        "title": "文生图节点",
        "accent": "#67b34d",
        "inputs": [{"id": "text", "label": "文本", "data_type": "text"}],
        "outputs": [{"id": "image", "label": "图片", "data_type": "image"}],
        "value": "等待上游节点输入",
    },
    "image_to_image": {
        "title": "图生图节点",
        "accent": "#b36b2f",
        "inputs": [
            {"id": "text", "label": "文本", "data_type": "text"},
            {"id": "image", "label": "图片", "data_type": "image"},
        ],
        "outputs": [{"id": "image", "label": "图片", "data_type": "image"}],
        "value": "等待上游节点输入",
    },
    "image_to_video": {
        "title": "图生视频节点",
        "accent": "#d97706",
        "inputs": [
            {"id": "text", "label": "提示词", "data_type": "text"},
            {"id": "image", "label": "参考图", "data_type": "image"},
        ],
        "outputs": [{"id": "video", "label": "视频", "data_type": "video"}],
        "value": "等待上游提示词或参考图输入",
    },
    "prompt_optimize": {
        "title": "提示词优化节点",
        "accent": "#9b59b6",
        "inputs": [{"id": "text", "label": "文本", "data_type": "text"}],
        "outputs": [{"id": "text", "label": "文本", "data_type": "text"}],
        "value": "等待上游节点输入",
    },
}

LEGACY_NODE_TYPE_MAP = {
    "base_input": "prompt_input",
    "base_output": "text_to_image",
}

IMAGE_MODE_OPTIONS = ["文生图", "图生图"]
IMAGE_SIZE_OPTIONS = [
    "自动",
    "4096*4096",
    "3840*3840（4K）",
    "3840*2160（横屏4K）",
    "3840*1920（2:1 4K）",
    "2160*3840（竖屏4K）",
    "2880*2880",
    "2048*2048",
    "2560*1440",
    "2048*1024",
    "1024*1536（竖屏）",
    "1536*1024（横屏）",
    "1024*1024",
]
IMAGE_COUNT_OPTIONS = ["1", "2", "3"]
IMAGE_QUALITY_OPTIONS = ["自动", "低", "中", "高"]
VIDEO_SIZE_OPTIONS = ["1280x720（横屏）", "720x1280（竖屏）", "1024x1024（方形）"]
VIDEO_SIZE_MAP = {
    "1280x720（横屏）": (1280, 720),
    "720x1280（竖屏）": (720, 1280),
    "1024x1024（方形）": (1024, 1024),
}
VIDEO_FRAME_OPTIONS = ["81", "121", "161", "241", "441"]
VIDEO_FPS_OPTIONS = ["24", "30"]
IMAGE_FALLBACK_MODELS = ["gpt-image-1", "dall-e-3", "dall-e-2"]
VIDEO_FALLBACK_MODELS = ["agnes-video-v2.0"]
AGENT_FALLBACK_MODELS = ["gpt-4o", "gpt-4.1", "gpt-3.5-turbo"]
NODE_PLACEHOLDER_TEXTS = {"等待上游节点输入", "请选择本地图片"}

def make_node_data(node_type, pos):
    node_type = LEGACY_NODE_TYPE_MAP.get(node_type, node_type)
    spec = NODE_CATALOG[node_type]
    data = {
        "id": uuid.uuid4().hex,
        "type": node_type,
        "title": spec["title"],
        "accent": spec["accent"],
        "value": spec["value"],
        "provider_id": "",
        "model": "",
        "image_mode": "图生图" if node_type == "image_to_image" else "文生图",
        "image_size": "",
        "image_count": "",
        "image_quality": "",
        "video_size": "",
        "video_frames": "",
        "video_fps": "",
        "video_path": "",
        "image_path": "",
        "x": float(pos.x()),
        "y": float(pos.y()),
    }
    return data


class WorkflowPortItem(QGraphicsEllipseItem):
    def __init__(self, node, port_id, data_type, is_output, parent=None):
        super().__init__(-6, -6, 12, 12, parent)
        self.node = node
        self.port_id = port_id
        self.data_type = data_type
        self.is_output = is_output
        self.setBrush(QColor("#10151c"))
        self.setPen(QPen(QColor("#d7e2ef"), 2))
        self.setZValue(4)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptedMouseButtons(Qt.LeftButton | Qt.RightButton)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            scene = self.scene()
            if isinstance(scene, WorkflowScene):
                scene.handle_port_click(self)
            event.accept()
            return
        super().mousePressEvent(event)


class WorkflowEdgeItem(QGraphicsPathItem):
    def __init__(self, source_port, target_port, edge_id=None):
        super().__init__()
        self.id = edge_id or uuid.uuid4().hex
        self.source_port = source_port
        self.target_port = target_port
        self.setPen(QPen(QColor("#7d9ab8"), 2))
        self.setZValue(-10)
        self.setAcceptedMouseButtons(Qt.RightButton)
        self.update_path()

    def update_path(self):
        start = self.source_port.scenePos()
        end = self.target_port.scenePos()
        dx = max(80, abs(end.x() - start.x()) * 0.5)
        path = QPainterPath(start)
        path.cubicTo(QPointF(start.x() + dx, start.y()), QPointF(end.x() - dx, end.y()), end)
        self.setPath(path)

    def contextMenuEvent(self, event):
        menu = QMenu()
        delete_action = menu.addAction("删除连线")
        if menu.exec(event.screenPos()) == delete_action:
            scene = self.scene()
            if isinstance(scene, WorkflowScene):
                scene.remove_edge(self)


class WorkflowThumbnailItem(QGraphicsPixmapItem):
    def __init__(self, node):
        super().__init__(node)
        self.node = node
        self.path = ""
        self.media_type = "image"
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setCursor(Qt.PointingHandCursor)

    def set_media_path(self, path, media_type="image"):
        self.path = path or ""
        self.media_type = media_type or "image"

    def set_image_path(self, path):
        self.set_media_path(path, "image")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.path and os.path.exists(self.path):
            if self.media_type == "video":
                open_local_file(self.path)
                event.accept()
                return
            scene = self.scene()
            parent = None
            if scene and scene.views():
                parent = scene.views()[0].window()
            show_image_preview(parent, self.path, "工作流图片预览")
            event.accept()
            return
        super().mousePressEvent(event)


class HistoryImageTile(QFrame):
    clicked = Signal(object)
    double_clicked = Signal(object)

    def __init__(self, path, prompt="", parent=None):
        super().__init__(parent)
        self.path = path
        self._checked = False
        name = os.path.basename(path)
        prompt = (prompt or "").replace("\n", " ").strip()
        self.setToolTip(f"{name}\n{prompt}" if prompt else name)
        self.setFixedSize(160, 160)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(0)

        self.thumb_label = QLabel()
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setFixedSize(150, 150)
        self.thumb_label.setStyleSheet("""
            QLabel {
                background-color:#0e0f12;
                color:#8b949e;
                font-size:12px;
                border: 1px solid #25272e;
                border-radius:6px;
            }
        """)
        layout.addWidget(self.thumb_label)

        pix = load_thumbnail_pixmap(path, 150, 150, generate_missing=True)
        if pix.isNull():
            pix = QPixmap(path)
            if not pix.isNull():
                pix = pix.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if not pix.isNull():
            self.thumb_label.setPixmap(pix)
        else:
            self.thumb_label.setText("无预览")
        self._apply_style()

    def _apply_style(self):
        border = "#2f80ed" if self._checked else "#25272e"
        bg = "#1a2a3f" if self._checked else "#1a1b20"
        hover_border = "#2f80ed" if self._checked else "#1f6feb"
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            QFrame:hover {{
                border-color: {hover_border};
                background-color: #1d2028;
            }}
        """)

    def setChecked(self, checked):
        self._checked = bool(checked)
        self._apply_style()

    def isChecked(self):
        return self._checked

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self)
        super().mouseDoubleClickEvent(event)


class ImageHistoryPickerDialog(QDialog):
    PAGE_SIZE = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_path = ""
        self.items = []
        self.tiles = []
        self.loaded_count = 0
        self.setWindowTitle("选择历史图片")
        self.resize(900, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("选择图片生成历史中的图片（最近 30 张）")
        title.setStyleSheet("color:#e8e8ea; font-weight:700;")
        root.addWidget(title)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: 1px solid #303640; border-radius: 8px; background: #10151c; }")
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(10, 10, 10, 10)
        self.grid.setSpacing(10)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.load_more_btn = buttons.addButton("加载更早 30 张", QDialogButtonBox.ActionRole)
        self.load_more_btn.clicked.connect(self.load_more)
        preview_btn = buttons.addButton("预览", QDialogButtonBox.ActionRole)
        preview_btn.clicked.connect(self.preview_current)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        migrate_json_history_once()
        self.load_more()

    def load_more(self):
        new_items = list(iter_image_history_items(self.PAGE_SIZE, self.loaded_count))
        if not new_items and not self.tiles:
            self._show_empty_hint()
            self.load_more_btn.setEnabled(False)
            return

        for path, prompt, _refs in new_items:
            tile = HistoryImageTile(path, prompt)
            tile.clicked.connect(self.select_tile)
            tile.double_clicked.connect(self.accept_tile)
            row = len(self.tiles) // 5
            col = len(self.tiles) % 5
            self.grid.addWidget(tile, row, col)
            self.tiles.append(tile)
        self.loaded_count += len(new_items)
        if self.tiles and not any(tile.isChecked() for tile in self.tiles):
            self.select_tile(self.tiles[0])
        self.load_more_btn.setEnabled(len(new_items) >= self.PAGE_SIZE)

    def _show_empty_hint(self):
        if self.grid.count() > 0:
            return
        label = QLabel("没有找到可用的历史图片")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color:#8b95a5; padding: 40px;")
        self.grid.addWidget(label, 0, 0)

    def select_tile(self, tile):
        for item in self.tiles:
            item.setChecked(item is tile)
        self.selected_path = tile.path

    def accept_tile(self, tile):
        self.select_tile(tile)
        self.accept()

    def current_path(self):
        if self.selected_path:
            return self.selected_path
        for tile in self.tiles:
            if tile.isChecked():
                return tile.path
        return ""

    def preview_current(self):
        path = self.current_path()
        if path:
            show_image_preview(self, path, "历史图片预览")

    def accept(self):
        self.selected_path = self.current_path()
        if not self.selected_path:
            return
        super().accept()


class WorkflowNodeItem(QGraphicsItem):
    HEADER = 44
    ACTION_BOTTOM_MARGIN = 18
    ACTION_BUTTON_HEIGHT = 30
    RESIZE_HANDLE_SIZE = 16

    def __init__(self, data):
        super().__init__()
        self.data = dict(data)
        self.width = max(self._min_width(), float(self.data.get("width", self._preferred_width())))
        self.body = max(self._min_body(), float(self.data.get("body", self._preferred_body())))
        self.input_ports = {}
        self.output_ports = {}
        self.value_edit = None
        self.value_proxy = None
        self.provider_combo = None
        self.provider_proxy = None
        self.model_combo = None
        self.model_proxy = None
        self.refresh_models_button = None
        self.refresh_models_proxy = None
        self.image_param_combos = {}
        self.image_param_proxies = {}
        self.thumbnail_item = None
        self.generate_button = None
        self.generate_proxy = None
        self.history_button = None
        self.history_proxy = None
        self._resizing = False
        self._resize_corner = ""
        self._resize_start_scene_rect = QRectF()
        self._hover_resize_corner = ""
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(0)
        self.setCursor(Qt.OpenHandCursor)
        self.setPos(float(self.data.get("x", 0)), float(self.data.get("y", 0)))
        self._build_config_widgets()
        self._build_image_param_widgets()
        self._build_editor()
        self._build_ports()
        self._build_action_widgets()
        self._refresh_tooltip()
        self._relayout_widgets()

    def _preferred_width(self):
        node_type = self.data.get("type")
        if node_type in ("text_to_image", "image_to_image"):
            return 430
        if node_type == "image_to_video":
            return 430
        if node_type == "upload_image":
            return 360
        if node_type == "prompt_optimize":
            return 320
        return 300

    def _min_width(self):
        node_type = self.data.get("type")
        if node_type in ("text_to_image", "image_to_image", "image_to_video"):
            return 430
        if node_type == "upload_image":
            return 360
        if node_type == "prompt_optimize":
            return 320
        return 300

    def _preferred_body(self):
        node_type = self.data.get("type")
        if node_type in ("text_to_image", "image_to_image"):
            return 640
        if node_type == "image_to_video":
            return 640
        if node_type == "upload_image":
            return 450
        if node_type == "prompt_optimize":
            return 320
        return 210

    def _min_body(self):
        node_type = self.data.get("type")
        if node_type in ("text_to_image", "image_to_image", "image_to_video"):
            return 620
        if node_type == "upload_image":
            return 430
        if node_type == "prompt_optimize":
            return 240
        return 160

    def _has_config_widgets(self):
        return self.data.get("type") in ("text_to_image", "image_to_image", "image_to_video", "prompt_optimize")

    def _has_thumbnail(self):
        return self.data.get("type") in ("upload_image", "text_to_image", "image_to_image", "image_to_video")

    def _has_image_params(self):
        return self.data.get("type") in ("text_to_image", "image_to_image")

    def _has_video_params(self):
        return self.data.get("type") == "image_to_video"

    def _content_label_y(self):
        if self._has_image_params() or self._has_video_params():
            return self.HEADER + 190
        return self.HEADER + (72 if self._has_config_widgets() else 12)

    def _editor_y(self):
        if self._has_image_params() or self._has_video_params():
            return self.HEADER + 220
        return self.HEADER + (96 if self._has_config_widgets() else 42)

    def _editor_height(self):
        node_type = self.data.get("type")
        if node_type in ("text_to_image", "image_to_image"):
            return 82
        if node_type == "image_to_video":
            return 82
        if node_type == "upload_image":
            return 54
        if node_type == "prompt_optimize":
            return max(118, self._action_y() - self._editor_y() - 54)
        return self.body - 56

    def _preview_label_y(self):
        if self.data.get("type") == "upload_image":
            return self.HEADER + 126
        if self.data.get("type") == "image_to_video":
            return self.HEADER + 318
        return self.HEADER + 318

    def _preview_rect(self):
        bottom = self._action_y() - 18
        if self.data.get("type") == "upload_image":
            top = self.HEADER + 154
            size = min(self.width - 28, max(160, bottom - top))
            return QRectF((self.width - size) / 2, top, size, size)
        top = self.HEADER + 346
        size = min(self.width - 28, max(160, bottom - top))
        return QRectF((self.width - size) / 2, top, size, size)

    def _action_y(self):
        return self.HEADER + self.body - self.ACTION_BUTTON_HEIGHT - self.ACTION_BOTTOM_MARGIN

    def _combo_style(self):
        return """
            QComboBox {
                background-color: #10151c;
                color: #d9e2ee;
                border: 1px solid #343b46;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QComboBox:hover { border-color: #5f7899; }
            QComboBox QAbstractItemView {
                background-color: #151922;
                color: #e6edf5;
                selection-background-color: #2f80ed;
                border: 1px solid #343b46;
            }
        """

    def _build_config_widgets(self):
        if not self._has_config_widgets():
            return

        combo_style = self._combo_style()
        half_width = int((self.width - 36) / 2)
        self.provider_combo = WorkflowComboBox()
        self.provider_combo.setFixedSize(half_width, 34)
        self.provider_combo.setStyleSheet(combo_style)
        self.provider_combo.currentIndexChanged.connect(self._sync_provider_from_combo)

        self.model_combo = WorkflowComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(QComboBox.NoInsert)
        self.model_combo.setFixedSize(half_width, 34)
        self.model_combo.setStyleSheet(combo_style)
        self.model_combo.currentTextChanged.connect(self._sync_model_from_combo)

        self.provider_proxy = QGraphicsProxyWidget(self)
        self.provider_proxy.setWidget(self.provider_combo)
        self.provider_proxy.setZValue(3)

        self.model_proxy = QGraphicsProxyWidget(self)
        self.model_proxy.setWidget(self.model_combo)
        self.model_proxy.setZValue(3)

        self.refresh_models_button = QPushButton("刷新")
        self.refresh_models_button.setFixedSize(48, 24)
        self.refresh_models_button.setToolTip("重新拉取当前厂商的模型列表")
        self.refresh_models_button.setStyleSheet("""
            QPushButton {
                background-color: #2a2c33;
                color: #d9e2ee;
                border: 1px solid #343b46;
                border-radius: 6px;
                font-size: 11px;
                padding: 0;
            }
            QPushButton:hover {
                background-color: #353740;
                border-color: #5f7899;
            }
            QPushButton:pressed {
                background-color: #2f80ed;
                color: #ffffff;
            }
        """)
        self.refresh_models_button.clicked.connect(self.refresh_node_models)
        self.refresh_models_button.setParent(None)
        self.refresh_models_proxy = QGraphicsProxyWidget(self)
        self.refresh_models_proxy.setWidget(self.refresh_models_button)
        self.refresh_models_proxy.setZValue(3)

    def _build_image_param_widgets(self):
        if not self._has_image_params() and not self._has_video_params():
            return

        combo_style = self._combo_style()

        def add_combo(key, options, x, y, width):
            combo = WorkflowComboBox()
            combo.addItems(options)
            combo.setFixedSize(width, 34)
            combo.setStyleSheet(combo_style)
            combo.currentTextChanged.connect(lambda text, k=key: self._sync_image_param_from_combo(k, text))
            proxy = QGraphicsProxyWidget(self)
            proxy.setWidget(combo)
            proxy.setZValue(3)
            self.image_param_combos[key] = combo
            self.image_param_proxies[key] = proxy

        base_y = self.HEADER + 106
        if self._has_video_params():
            add_combo("video_size", VIDEO_SIZE_OPTIONS, 56, base_y, 180)
            add_combo("video_frames", VIDEO_FRAME_OPTIONS, 292, base_y, 76)
            add_combo("video_fps", VIDEO_FPS_OPTIONS, 56, base_y + 42, 80)
            return

        mode_options = ["图生图"] if self.data.get("type") == "image_to_image" else ["文生图"]
        add_combo("image_mode", mode_options, 56, base_y, 120)
        add_combo("image_size", IMAGE_SIZE_OPTIONS, 232, base_y, 180)
        add_combo("image_count", IMAGE_COUNT_OPTIONS, 56, base_y + 42, 80)
        add_combo("image_quality", IMAGE_QUALITY_OPTIONS, 192, base_y + 42, 90)

    def _build_editor(self):
        self.value_edit = QTextEdit()
        self.value_edit.setPlainText(str(self.data.get("value", "")))
        self.value_edit.setAcceptRichText(False)
        self.value_edit.setFrameShape(QTextEdit.NoFrame)
        self.value_edit.setStyleSheet("""
            QTextEdit {
                background-color: #10151c;
                color: #d9e2ee;
                border: 1px solid #343b46;
                border-radius: 6px;
                padding: 8px;
                selection-background-color: #2f80ed;
                font-size: 12px;
            }
        """)
        self.value_edit.textChanged.connect(self._sync_value_from_editor)

        self.value_proxy = QGraphicsProxyWidget(self)
        self.value_proxy.setWidget(self.value_edit)
        self.value_proxy.setZValue(3)
        self.value_proxy.setFlag(QGraphicsItem.ItemIsSelectable, False)

    def _build_action_widgets(self):
        node_type = self.data.get("type")
        if node_type not in ("upload_image", "text_to_image", "image_to_image", "image_to_video", "prompt_optimize"):
            return

        if node_type == "upload_image":
            button_text = "本地图片"
        elif node_type == "image_to_video":
            button_text = "生成视频"
        else:
            button_text = "生成"
        self.generate_button = QPushButton(button_text)
        self.generate_button.setFixedSize(78 if node_type in ("upload_image", "image_to_video") else 70, self.ACTION_BUTTON_HEIGHT)
        button_style = """
            QPushButton {
                background-color: #2a2c33;
                color: #e8e8ea;
                border: 1px solid #3a3c43;
                border-radius: 6px;
                margin: 1px;
                padding: 0 2px 1px 2px;
            }
            QPushButton:hover { background-color: #353740; }
        """
        self.generate_button.setStyleSheet(button_style)
        self.generate_button.clicked.connect(self.run_generation)
        self.generate_button.setParent(None)
        self.generate_proxy = QGraphicsProxyWidget(self)
        self.generate_proxy.setWidget(self.generate_button)
        self.generate_proxy.setZValue(3)

        if node_type == "upload_image":
            self.history_button = QPushButton("历史图片")
            self.history_button.setFixedSize(78, self.ACTION_BUTTON_HEIGHT)
            self.history_button.setStyleSheet(button_style)
            self.history_button.clicked.connect(self.pick_history_image)
            self.history_button.setParent(None)
            self.history_proxy = QGraphicsProxyWidget(self)
            self.history_proxy.setWidget(self.history_button)
            self.history_proxy.setZValue(3)

        if self._has_thumbnail():
            self.thumbnail_item = WorkflowThumbnailItem(self)
            self.thumbnail_item.setZValue(2)
            if self.data.get("image_path"):
                self.set_thumbnail(self.data.get("image_path"))
            elif self.data.get("video_path"):
                self.set_video_thumbnail(self.data.get("video_path"))

    def _relayout_widgets(self):
        if self.provider_combo is not None and self.model_combo is not None:
            half_width = int((self.width - 36) / 2)
            self.provider_combo.setFixedSize(half_width, 34)
            self.model_combo.setFixedSize(half_width, 34)
            if self.provider_proxy is not None:
                self.provider_proxy.setPos(14, self.HEADER + 34)
            if self.model_proxy is not None:
                self.model_proxy.setPos(22 + half_width, self.HEADER + 34)
            if self.refresh_models_proxy is not None:
                self.refresh_models_proxy.setPos(self.width - 62, self.HEADER + 8)

        if self.image_param_combos:
            base_y = self.HEADER + 106
            if self._has_video_params():
                layout = {
                    "video_size": (56, base_y, max(150, int(self.width * 0.42))),
                    "video_frames": (max(250, int(self.width * 0.68)), base_y, 76),
                    "video_fps": (56, base_y + 42, 80),
                }
            else:
                layout = {
                    "image_mode": (56, base_y, 120),
                    "image_size": (232, base_y, max(160, int(self.width - 246))),
                    "image_count": (56, base_y + 42, 80),
                    "image_quality": (192, base_y + 42, 90),
                }
            for key, combo in self.image_param_combos.items():
                x, y, width = layout.get(key, (56, base_y, 120))
                combo.setFixedSize(max(60, int(width)), 34)
                proxy = self.image_param_proxies.get(key)
                if proxy is not None:
                    proxy.setPos(x, y)

        if self.value_edit is not None:
            self.value_edit.setFixedSize(max(120, int(self.width - 28)), max(40, int(self._editor_height())))
        if self.value_proxy is not None:
            self.value_proxy.setPos(14, self._editor_y())

        action_y = self._action_y()
        if self.generate_proxy is not None:
            node_type = self.data.get("type")
            button_w = 180 if node_type == "upload_image" else (94 if node_type == "image_to_video" else 86)
            self.generate_proxy.setPos(self.width - button_w, action_y)
        if self.history_proxy is not None:
            self.history_proxy.setPos(self.width - 94, action_y)

        if self.thumbnail_item is not None:
            if self.data.get("video_path"):
                self.set_video_thumbnail(self.data.get("video_path"))
            elif self.data.get("image_path"):
                self.set_thumbnail(self.data.get("image_path"))
            else:
                self.thumbnail_item.setPos(16, self._preview_rect().top() + 2)

        self._relayout_ports()

    def _relayout_ports(self):
        for i, item in enumerate(self.input_ports.values()):
            y = self.HEADER + (76 if self._has_config_widgets() else 34) + i * 34
            item.setPos(0, y)
        for i, item in enumerate(self.output_ports.values()):
            y = self.HEADER + (76 if self._has_config_widgets() else 34) + i * 34
            item.setPos(self.width, y)

    def detach_proxy_widgets(self):
        proxies = [
            self.value_proxy,
            self.provider_proxy,
            self.model_proxy,
            self.refresh_models_proxy,
            self.generate_proxy,
            self.history_proxy,
        ]
        proxies.extend(self.image_param_proxies.values())
        for proxy in proxies:
            if proxy is None:
                continue
            try:
                widget = proxy.widget()
                if widget is not None:
                    proxy.setWidget(None)
                    widget.setParent(None)
                    widget.deleteLater()
            except Exception:
                pass

    def _sync_value_from_editor(self):
        if self.value_edit is not None:
            self.data["value"] = self.value_edit.toPlainText()
            if self.data.get("type") == "upload_image":
                path = self.data["value"].strip()
                if path and os.path.exists(path) and path != self.data.get("image_path"):
                    self.data["image_path"] = path
                    self.set_thumbnail(path)
            scene = self.scene()
            if isinstance(scene, WorkflowScene):
                scene.mark_changed()

    def _build_ports(self):
        spec = NODE_CATALOG.get(self.data.get("type"), {})
        inputs = spec.get("inputs", [])
        outputs = spec.get("outputs", [])

        for i, port in enumerate(inputs):
            item = WorkflowPortItem(self, port["id"], port["data_type"], False, self)
            y = self.HEADER + (76 if self._has_config_widgets() else 34) + i * 34
            item.setPos(0, y)
            self.input_ports[port["id"]] = item

        for i, port in enumerate(outputs):
            item = WorkflowPortItem(self, port["id"], port["data_type"], True, self)
            y = self.HEADER + (76 if self._has_config_widgets() else 34) + i * 34
            item.setPos(self.width, y)
            self.output_ports[port["id"]] = item

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.HEADER + self.body)

    def _resize_corner_at(self, pos):
        rect = self.boundingRect()
        size = self.RESIZE_HANDLE_SIZE
        left = pos.x() <= rect.left() + size
        right = pos.x() >= rect.right() - size
        top = pos.y() <= rect.top() + size
        bottom = pos.y() >= rect.bottom() - size
        if top and left:
            return "top_left"
        if top and right:
            return "top_right"
        if bottom and left:
            return "bottom_left"
        if bottom and right:
            return "bottom_right"
        return ""

    def _cursor_for_corner(self, corner):
        if corner in ("top_left", "bottom_right"):
            return Qt.SizeFDiagCursor
        if corner in ("top_right", "bottom_left"):
            return Qt.SizeBDiagCursor
        return Qt.OpenHandCursor

    def _apply_resize_from_scene_pos(self, scene_pos):
        if not self._resizing or not self._resize_corner:
            return
        start = self._resize_start_scene_rect
        min_w = self._min_width()
        min_h = self.HEADER + self._min_body()
        left = start.left()
        right = start.right()
        top = start.top()
        bottom = start.bottom()

        if "left" in self._resize_corner:
            left = min(scene_pos.x(), right - min_w)
        if "right" in self._resize_corner:
            right = max(scene_pos.x(), left + min_w)
        if "top" in self._resize_corner:
            top = min(scene_pos.y(), bottom - min_h)
        if "bottom" in self._resize_corner:
            bottom = max(scene_pos.y(), top + min_h)

        self.prepareGeometryChange()
        self.setPos(QPointF(left, top))
        self.width = max(min_w, right - left)
        self.body = max(self._min_body(), bottom - top - self.HEADER)
        self.data["width"] = float(self.width)
        self.data["body"] = float(self.body)
        self._relayout_widgets()
        self.update()
        scene = self.scene()
        if isinstance(scene, WorkflowScene):
            scene.update_edges_for_node(self)
            scene.mark_changed()

    def paint(self, painter, option, widget=None):
        del option, widget
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.boundingRect().adjusted(1, 1, -1, -1)
        border = QColor("#5f7899") if self.isSelected() else QColor("#303640")
        painter.setPen(QPen(border, 2 if self.isSelected() else 1))
        painter.setBrush(QColor("#171b22"))
        painter.drawRoundedRect(rect, 8, 8)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self.data.get("accent", "#2f80ed")))
        painter.drawRoundedRect(QRectF(1, 1, self.width - 2, self.HEADER), 8, 8)
        painter.drawRect(QRectF(1, self.HEADER - 8, self.width - 2, 9))

        painter.setPen(QColor("#ffffff"))
        painter.setFont(painter.font())
        painter.drawText(QRectF(14, 0, self.width - 28, self.HEADER), Qt.AlignVCenter, self.data.get("title", "节点"))

        painter.setPen(QColor("#9ca7b4"))
        if self._has_config_widgets():
            painter.drawText(QRectF(14, self.HEADER + 12, self.width - 28, 22), Qt.AlignLeft, "厂商 / 模型")

        if self._has_image_params() or self._has_video_params():
            painter.setPen(QColor("#9ca7b4"))
            painter.drawText(QRectF(14, self.HEADER + 80, self.width - 28, 22), Qt.AlignLeft, "生成参数")
            base_y = self.HEADER + 106
            if self._has_video_params():
                labels = [
                    ("尺寸", 14, base_y + 6, 36),
                    ("帧数", 252, base_y + 6, 36),
                    ("FPS", 14, base_y + 48, 36),
                ]
            else:
                labels = [
                    ("模式", 14, base_y + 6, 36),
                    ("尺寸", 190, base_y + 6, 36),
                    ("数量", 14, base_y + 48, 36),
                    ("质量", 150, base_y + 48, 36),
                ]
            for text, x, y, width in labels:
                painter.drawText(QRectF(x, y, width, 22), Qt.AlignLeft | Qt.AlignVCenter, text)

        content_label = "图片路径" if self.data.get("type") == "upload_image" else ("视频结果" if self.data.get("type") == "image_to_video" else "内容")
        painter.drawText(QRectF(14, self._content_label_y(), self.width - 28, 22), Qt.AlignLeft, content_label)

        value_rect = QRectF(14, self._editor_y(), self.width - 28, self._editor_height())
        painter.setPen(QPen(QColor("#343b46"), 1))
        painter.setBrush(QColor("#10151c"))
        painter.drawRoundedRect(value_rect, 6, 6)
        if self.data.get("type") == "prompt_optimize":
            painter.setPen(QColor("#9ca7b4"))
            painter.drawText(value_rect, Qt.AlignCenter, "生成新的提示词")

        if self._has_thumbnail():
            painter.setPen(QColor("#9ca7b4"))
            preview_label = "预览"
            painter.drawText(QRectF(14, self._preview_label_y(), self.width - 28, 22), Qt.AlignLeft, preview_label)
            thumb_rect = self._preview_rect()
            painter.setPen(QPen(QColor("#343b46"), 1))
            painter.setBrush(QColor("#10151c"))
            painter.drawRoundedRect(thumb_rect, 6, 6)
            if not self.data.get("image_path"):
                painter.setPen(QColor("#6f7a88"))
                placeholder = "选择后显示缩略图" if self.data.get("type") == "upload_image" else "生成后显示缩略图"
                painter.drawText(thumb_rect, Qt.AlignCenter, placeholder)

        handle_color = QColor("#5f7899") if self._hover_resize_corner else QColor("#3a4350")
        painter.setPen(QPen(handle_color, 1))
        corner = 10
        pad = 9
        bottom = self.HEADER + self.body - pad
        lines = [
            (QPointF(pad, pad + corner), QPointF(pad, pad), QPointF(pad + corner, pad)),
            (QPointF(self.width - pad - corner, pad), QPointF(self.width - pad, pad), QPointF(self.width - pad, pad + corner)),
            (QPointF(pad, bottom - corner), QPointF(pad, bottom), QPointF(pad + corner, bottom)),
            (QPointF(self.width - pad - corner, bottom), QPointF(self.width - pad, bottom), QPointF(self.width - pad, bottom - corner)),
        ]
        for a, b, c in lines:
            painter.drawLine(a, b)
            painter.drawLine(b, c)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.data["x"] = float(self.pos().x())
            self.data["y"] = float(self.pos().y())
            scene = self.scene()
            if isinstance(scene, WorkflowScene):
                scene.update_edges_for_node(self)
                scene.mark_changed()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        corner = self._resize_corner_at(event.pos())
        if event.button() == Qt.LeftButton and corner:
            self._resizing = True
            self._resize_corner = corner
            self._resize_start_scene_rect = self.mapToScene(self.boundingRect()).boundingRect()
            self.setCursor(self._cursor_for_corner(corner))
            event.accept()
            return
        if self.value_proxy is not None and self.value_proxy.geometry().contains(event.pos()):
            super().mousePressEvent(event)
            return
        if self.provider_proxy is not None and self.provider_proxy.geometry().contains(event.pos()):
            super().mousePressEvent(event)
            return
        if self.model_proxy is not None and self.model_proxy.geometry().contains(event.pos()):
            super().mousePressEvent(event)
            return
        if self.refresh_models_proxy is not None and self.refresh_models_proxy.geometry().contains(event.pos()):
            super().mousePressEvent(event)
            return
        for proxy in self.image_param_proxies.values():
            if proxy.geometry().contains(event.pos()):
                super().mousePressEvent(event)
                return
        if self.generate_proxy is not None and self.generate_proxy.geometry().contains(event.pos()):
            super().mousePressEvent(event)
            return
        if self.history_proxy is not None and self.history_proxy.geometry().contains(event.pos()):
            super().mousePressEvent(event)
            return
        self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            self._apply_resize_from_scene_pos(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self._resize_corner = ""
            self.setCursor(self._cursor_for_corner(self._hover_resize_corner))
            event.accept()
            return
        self.setCursor(self._cursor_for_corner(self._hover_resize_corner))
        super().mouseReleaseEvent(event)

    def hoverMoveEvent(self, event):
        self._hover_resize_corner = self._resize_corner_at(event.pos())
        if not self._resizing:
            self.setCursor(self._cursor_for_corner(self._hover_resize_corner))
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover_resize_corner = ""
        if not self._resizing:
            self.setCursor(Qt.OpenHandCursor)
        super().hoverLeaveEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu()
        delete_action = menu.addAction("删除节点")
        action = menu.exec(event.screenPos())
        scene = self.scene()
        if action == delete_action and isinstance(scene, WorkflowScene):
            scene.remove_node(self)

    def to_json(self):
        self._sync_value_from_editor()
        out = dict(self.data)
        out["x"] = float(self.pos().x())
        out["y"] = float(self.pos().y())
        out["width"] = float(self.width)
        out["body"] = float(self.body)
        return out

    def _refresh_tooltip(self):
        title = str(self.data.get("title", "") or "")
        value = str(self.data.get("value", "") or "").strip()
        self.setToolTip(f"{title}\n{value}" if value else title)

    def set_provider_model(self, provider_id, model):
        self.data["provider_id"] = provider_id or ""
        self.data["model"] = model or ""
        self.refresh_config_controls()

    def selected_provider(self):
        scene = self.scene()
        if isinstance(scene, WorkflowScene):
            provider_id = self.data.get("provider_id", "")
            if provider_id:
                return get_provider(scene.config, provider_id)
        return None

    def selected_model(self):
        return self.data.get("model", "")

    def set_thumbnail(self, path):
        if self.thumbnail_item is None:
            return
        pix = QPixmap(path)
        if pix.isNull():
            return
        rect = self._preview_rect()
        pix = pix.scaled(int(rect.width() - 4), int(rect.height() - 4), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumbnail_item.setPixmap(pix)
        self.thumbnail_item.set_image_path(path)
        x = rect.left() + (rect.width() - pix.width()) / 2
        y = rect.top() + (rect.height() - pix.height()) / 2
        self.thumbnail_item.setPos(x, y)

    def set_video_thumbnail(self, path):
        if self.thumbnail_item is None:
            return
        rect = self._preview_rect()
        pix = load_video_thumbnail_pixmap(path, int(rect.width() - 4), int(rect.height() - 4), generate_missing=True)
        if pix.isNull():
            pix = QPixmap(int(rect.width() - 4), int(rect.height() - 4))
            pix.fill(QColor("#10151c"))
            painter = QPainter(pix)
            try:
                painter.setPen(QColor("#9ca7b4"))
                painter.drawText(pix.rect(), Qt.AlignCenter, "点击播放视频")
            finally:
                painter.end()
        else:
            pix = pix.scaled(int(rect.width() - 4), int(rect.height() - 4), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumbnail_item.setPixmap(pix)
        self.thumbnail_item.set_media_path(path, "video")
        x = rect.left() + (rect.width() - pix.width()) / 2
        y = rect.top() + (rect.height() - pix.height()) / 2
        self.thumbnail_item.setPos(x, y)

    def refresh_config_controls(self, config=None):
        if not self._has_config_widgets() or self.provider_combo is None or self.model_combo is None:
            return
        if config is None:
            scene = self.scene()
            config = scene.config if isinstance(scene, WorkflowScene) else {}
        providers = list((config or {}).get("providers", []))
        current_provider = self.data.get("provider_id") or self._default_provider_id(config)
        current_model = self.data.get("model") or self._default_model(config)

        self.provider_combo.blockSignals(True)
        self.provider_combo.clear()
        if not providers:
            self.provider_combo.addItem("未配置厂商", "")
        else:
            for provider in providers:
                self.provider_combo.addItem(provider.get("name") or provider.get("id") or "未命名", provider.get("id", ""))
        index = self.provider_combo.findData(current_provider)
        self.provider_combo.setCurrentIndex(index if index >= 0 else 0)
        selected_provider = self.provider_combo.currentData() or ""
        self.data["provider_id"] = selected_provider
        self.provider_combo.blockSignals(False)

        self.set_model_options(self._initial_model_options(config), current_model)

        self.refresh_image_param_controls(config)
        self.refresh_video_param_controls(config)

    def _initial_model_options(self, config=None):
        options = []
        provider_id = self.data.get("provider_id") or self._default_provider_id(config)
        cached_models = []
        if provider_id:
            cached_models = list(((config or {}).get("model_cache", {}) or {}).get(provider_id, []) or [])
        for candidate in (self.data.get("model", ""), self._default_model(config)):
            candidate = (candidate or "").strip()
            if candidate and candidate not in options:
                options.append(candidate)
        for model in cached_models:
            model = str(model or "").strip()
            if model and model not in options:
                options.append(model)
        if self.data.get("type") in ("text_to_image", "image_to_image"):
            fallback = IMAGE_FALLBACK_MODELS
        elif self.data.get("type") == "image_to_video":
            fallback = VIDEO_FALLBACK_MODELS
        else:
            fallback = AGENT_FALLBACK_MODELS
        for model in fallback:
            if model and model not in options:
                options.append(model)
        return options or [""]

    def set_model_options(self, models, current_model=None, keep_current=True):
        if self.model_combo is None:
            return
        current_model = (current_model if current_model is not None else self.data.get("model", "")) or ""
        options = []
        for model in models or []:
            model = str(model or "").strip()
            if model and model not in options:
                options.append(model)
        if current_model and keep_current and current_model not in options:
            options.insert(0, current_model)
        if not options:
            options = [""]

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model in options:
            self.model_combo.addItem(model)
        if current_model and current_model in options:
            self.model_combo.setCurrentText(current_model)
        else:
            self.model_combo.setCurrentIndex(0)
        self.data["model"] = self.model_combo.currentText().strip()
        self.model_combo.blockSignals(False)

    def set_model_loading(self):
        if self.model_combo is None:
            return
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem("正在加载模型...")
        self.model_combo.setCurrentIndex(0)
        self.data["model"] = ""
        self.model_combo.blockSignals(False)

    def refresh_image_param_controls(self, config=None):
        if not self._has_image_params() or not self.image_param_combos:
            return
        if config is None:
            scene = self.scene()
            config = scene.config if isinstance(scene, WorkflowScene) else {}
        image_cfg = (config or {}).get("image", {})
        defaults = {
            "image_mode": "图生图" if self.data.get("type") == "image_to_image" else "文生图",
            "image_size": image_cfg.get("size", "自动"),
            "image_count": image_cfg.get("count", "1"),
            "image_quality": image_cfg.get("quality", "自动"),
        }
        option_map = {
            "image_mode": IMAGE_MODE_OPTIONS,
            "image_size": IMAGE_SIZE_OPTIONS,
            "image_count": IMAGE_COUNT_OPTIONS,
            "image_quality": IMAGE_QUALITY_OPTIONS,
        }
        for key, combo in self.image_param_combos.items():
            value = self.data.get(key) or defaults.get(key, "")
            if value not in option_map.get(key, []):
                value = defaults.get(key, "")
            combo.blockSignals(True)
            idx = combo.findText(value)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.data[key] = combo.currentText()
            combo.blockSignals(False)

    def refresh_video_param_controls(self, config=None):
        if not self._has_video_params() or not self.image_param_combos:
            return
        if config is None:
            scene = self.scene()
            config = scene.config if isinstance(scene, WorkflowScene) else {}
        video_cfg = (config or {}).get("video", {})
        defaults = {
            "video_size": _video_size_label(video_cfg.get("width", "1280"), video_cfg.get("height", "720")),
            "video_frames": str(video_cfg.get("num_frames", "81")),
            "video_fps": str(video_cfg.get("frame_rate", "24")),
        }
        option_map = {
            "video_size": VIDEO_SIZE_OPTIONS,
            "video_frames": VIDEO_FRAME_OPTIONS,
            "video_fps": VIDEO_FPS_OPTIONS,
        }
        for key, combo in self.image_param_combos.items():
            value = self.data.get(key) or defaults.get(key, "")
            if value not in option_map.get(key, []):
                value = defaults.get(key, "")
            combo.blockSignals(True)
            idx = combo.findText(value)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.data[key] = combo.currentText()
            combo.blockSignals(False)

    def _default_provider_id(self, config):
        node_type = self.data.get("type")
        if node_type in ("text_to_image", "image_to_image"):
            return (config or {}).get("image", {}).get("provider_id", "")
        if node_type == "image_to_video":
            return (config or {}).get("video", {}).get("provider_id", "")
        if node_type == "prompt_optimize":
            return (config or {}).get("agent", {}).get("provider_id", "")
        return ""

    def _default_model(self, config):
        node_type = self.data.get("type")
        if node_type in ("text_to_image", "image_to_image"):
            return (config or {}).get("image", {}).get("model", "")
        if node_type == "image_to_video":
            return (config or {}).get("video", {}).get("model", "")
        if node_type == "prompt_optimize":
            return (config or {}).get("agent", {}).get("model", "")
        return ""

    def _sync_provider_from_combo(self):
        if self.provider_combo is None:
            return
        old_provider_id = self.data.get("provider_id", "")
        self.data["provider_id"] = self.provider_combo.currentData() or ""
        provider_changed = old_provider_id != self.data["provider_id"]
        scene = self.scene()
        if isinstance(scene, WorkflowScene):
            if provider_changed:
                self.data["model"] = ""
                provider_id = self.data.get("provider_id", "")
                cached = scene.model_cache.get(provider_id) or scene.config.get("model_cache", {}).get(provider_id)
                if cached:
                    self.set_model_options(cached, "", keep_current=False)
                    scene.mark_changed()
                    return
                self.set_model_loading()
            else:
                self.set_model_options(
                    self._initial_model_options(scene.config),
                    self.data.get("model", ""),
                    keep_current=True,
                )
            scene.request_models_for_node(self)
            scene.mark_changed()

    def _sync_model_from_combo(self, text):
        self.data["model"] = (text or "").strip()
        scene = self.scene()
        if isinstance(scene, WorkflowScene):
            scene.mark_changed()

    def _sync_image_param_from_combo(self, key, text):
        self.data[key] = text or ""
        scene = self.scene()
        if isinstance(scene, WorkflowScene):
            scene.mark_changed()

    def refresh_node_models(self):
        scene = self.scene()
        if not isinstance(scene, WorkflowScene):
            return
        self.set_model_loading()
        scene.request_models_for_node(self, force=True)
        scene.notify("正在刷新节点模型列表...")

    def run_generation(self):
        scene = self.scene()
        if not isinstance(scene, WorkflowScene):
            return
        scene.run_node_generation(self)

    def pick_history_image(self):
        scene = self.scene()
        if isinstance(scene, WorkflowScene):
            scene.pick_history_image(self)



class NodeConfigDialog(QDialog):
    MODEL_REQUEST_KEY = "node_config_dialog"

    def __init__(self, config, node, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self.node = node
        self.model_worker = None
        self._model_request_id = ""
        self._build_ui()
        self._load_providers()

    def _model_loader(self):
        loader = getattr(self, "_model_list_loader", None)
        if loader is None:
            loader = ModelListRequestPool(
                self.config,
                owner=self,
                worker_attr="model_worker",
                worker_factory=ModelListWorker,
            )
            self._model_list_loader = loader
        return loader

    def _build_ui(self):
        self.setWindowTitle("节点配置")
        self.resize(420, 180)
        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.provider_combo = QComboBox()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(QComboBox.NoInsert)
        self.model_combo.setToolTip("可直接输入模型名，也可从加载结果中选择")
        self.refresh_btn = QPushButton("刷新模型")
        self.refresh_btn.clicked.connect(self.load_models)

        provider_row = QHBoxLayout()
        provider_row.addWidget(self.provider_combo, 1)
        provider_row.addWidget(self.refresh_btn)

        form.addRow("API 厂商", provider_row)
        form.addRow("模型", self.model_combo)
        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.provider_combo.currentIndexChanged.connect(self.load_models)

    def _load_providers(self):
        self.providers = list(self.config.get("providers", []))
        self.provider_combo.clear()
        for provider in self.providers:
            self.provider_combo.addItem(provider.get("name") or provider.get("id") or "未命名", provider.get("id", ""))

        current_provider = self.node.data.get("provider_id") or self._default_provider_id()
        for i in range(self.provider_combo.count()):
            if self.provider_combo.itemData(i) == current_provider:
                self.provider_combo.setCurrentIndex(i)
                break
        self.load_models()

    def _default_provider_id(self):
        node_type = self.node.data.get("type")
        if node_type in ("text_to_image", "image_to_image"):
            return self.config.get("image", {}).get("provider_id", "")
        if node_type == "image_to_video":
            return self.config.get("video", {}).get("provider_id", "")
        if node_type == "prompt_optimize":
            return self.config.get("agent", {}).get("provider_id", "")
        return ""

    def current_provider(self):
        idx = self.provider_combo.currentIndex()
        if idx < 0 or idx >= len(self.providers):
            return None
        provider_id = self.provider_combo.itemData(idx)
        for provider in self.providers:
            if provider.get("id") == provider_id:
                return provider
        return None

    def load_models(self):
        provider = self.current_provider()
        self.model_combo.clear()
        self.model_combo.setEditable(True)
        if provider is None:
            return

        current_model = self.node.data.get("model") or self._default_model()
        self.model_combo.addItem(current_model or "")
        self.model_combo.setCurrentText(current_model or "")

        self._model_loader().start(
            provider.get("id", ""),
            key=self.MODEL_REQUEST_KEY,
            replace=True,
            on_started=self._on_models_started,
            on_loaded=self.on_models_loaded,
            on_failed=self.on_models_failed,
        )

    def _on_models_started(self, _provider_id, request_id):
        self._model_request_id = request_id
        self.refresh_btn.setEnabled(False)

    def _default_model(self):
        node_type = self.node.data.get("type")
        if node_type in ("text_to_image", "image_to_image"):
            return self.config.get("image", {}).get("model", "")
        if node_type == "image_to_video":
            return self.config.get("video", {}).get("model", "")
        if node_type == "prompt_optimize":
            return self.config.get("agent", {}).get("model", "")
        return ""

    def _fallback_models(self):
        node_type = self.node.data.get("type")
        if node_type in ("text_to_image", "image_to_image"):
            return IMAGE_FALLBACK_MODELS
        if node_type == "image_to_video":
            return VIDEO_FALLBACK_MODELS
        return AGENT_FALLBACK_MODELS

    def on_models_loaded(self, provider_id, request_id, models):
        if not self._model_loader().is_current(self.MODEL_REQUEST_KEY, provider_id, request_id):
            return
        current = self.model_combo.currentText().strip()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model in models:
            self.model_combo.addItem(model)
        if current:
            self.model_combo.setCurrentText(current)
        elif models:
            self.model_combo.setCurrentIndex(0)
        self.model_combo.blockSignals(False)
        self.refresh_btn.setEnabled(True)

    def on_models_failed(self, provider_id, request_id, err):
        if not self._model_loader().is_current(self.MODEL_REQUEST_KEY, provider_id, request_id):
            return
        current = self.model_combo.currentText().strip()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for model in self._fallback_models():
            self.model_combo.addItem(model)
        if current:
            self.model_combo.setCurrentText(current)
        elif self.model_combo.count() > 0:
            self.model_combo.setCurrentIndex(0)
        self.model_combo.blockSignals(False)
        self.refresh_btn.setEnabled(True)

    def closeEvent(self, event):
        try:
            self._model_loader().stop(self.MODEL_REQUEST_KEY)
        except Exception:
            pass
        super().closeEvent(event)

    def selected_provider(self):
        return self.current_provider()

    def selected_model(self):
        return self.model_combo.currentText().strip()




class WorkflowScene(QGraphicsScene):
    def __init__(self, config=None, status_callback=None, parent=None, load_defaults=True):
        super().__init__(parent)
        self.config = config if config is not None else {}
        self.status_callback = status_callback
        self.changed_callback = None
        self.workers = {}
        self.model_workers = {}
        self.model_loader = ModelListRequestPool(
            self.config,
            owner=self,
            worker_map_attr="model_workers",
            worker_factory=ModelListWorker,
        )
        self.model_cache = dict((self.config.get("model_cache", {}) or {}))
        self.model_waiting_nodes = {}
        self.nodes = {}
        self.edges = []
        self.pending_port = None
        self.pending_line = None
        self.setSceneRect(-5000, -5000, 10000, 10000)
        if load_defaults:
            self.add_default_nodes()

    def add_default_nodes(self):
        if self.nodes:
            return
        self.add_node("prompt_input", QPointF(-310, -90))
        self.add_node("text_to_image", QPointF(60, -110))

    def notify(self, text):
        if self.status_callback:
            self.status_callback(text)

    def mark_changed(self):
        if self.changed_callback:
            self.changed_callback()

    def add_node(self, node_type, pos):
        if node_type not in NODE_CATALOG:
            return None
        item = WorkflowNodeItem(make_node_data(node_type, pos))
        self.nodes[item.data["id"]] = item
        self.addItem(item)
        item.refresh_config_controls(self.config)
        self.notify("节点已添加。")
        self.mark_changed()
        return item

    def configure_node(self, node):
        if not self.config.get("providers"):
            self.notify("请先在主程序设置里添加 API 厂商。")
            return
        dlg = NodeConfigDialog(self.config, node)
        if dlg.exec() == QDialog.Accepted:
            provider = dlg.selected_provider()
            model = dlg.selected_model()
            if provider is None:
                self.notify("未选择有效厂商。")
                return
            node.set_provider_model(provider.get("id", ""), model)
            self.notify("节点厂商和模型已设置。")
            self.mark_changed()

    def _default_model_for_node(self, node):
        if node.data.get("type") in ("text_to_image", "image_to_image"):
            return self.config.get("image", {}).get("model", "")
        if node.data.get("type") == "image_to_video":
            return self.config.get("video", {}).get("model", "")
        if node.data.get("type") == "prompt_optimize":
            return self.config.get("agent", {}).get("model", "")
        return ""

    def _provider_for_node(self, node):
        provider_id = node.data.get("provider_id", "")
        if not provider_id:
            if node.data.get("type") in ("text_to_image", "image_to_image"):
                provider_id = self.config.get("image", {}).get("provider_id", "")
            elif node.data.get("type") == "image_to_video":
                provider_id = self.config.get("video", {}).get("provider_id", "")
            elif node.data.get("type") == "prompt_optimize":
                provider_id = self.config.get("agent", {}).get("provider_id", "")
        return get_provider(self.config, provider_id)

    def _default_provider_for_node(self, node):
        if node.data.get("type") in ("text_to_image", "image_to_image"):
            return self.config.get("image", {}).get("provider_id", "")
        if node.data.get("type") == "image_to_video":
            return self.config.get("video", {}).get("provider_id", "")
        if node.data.get("type") == "prompt_optimize":
            return self.config.get("agent", {}).get("provider_id", "")
        return ""

    def _model_for_node(self, node):
        return node.data.get("model") or self._default_model_for_node(node)

    def request_models_for_node(self, node, force=False):
        if node.model_combo is None:
            return
        provider_id = node.data.get("provider_id", "") or self._default_provider_for_node(node)
        if not provider_id:
            return
        if force:
            self.model_cache.pop(provider_id, None)
            self.config.setdefault("model_cache", {}).pop(provider_id, None)
        elif provider_id in self.model_cache:
            node.set_model_options(self.model_cache.get(provider_id, []), node.data.get("model", ""))
            return

        self.model_waiting_nodes.setdefault(provider_id, set()).add(node.data.get("id", ""))
        self.model_loader.start(
            provider_id,
            key=provider_id,
            replace=False,
            on_loaded=lambda pid, _request_id, models: self.on_node_models_loaded(pid, models),
            on_failed=lambda pid, _request_id, _err: self.on_node_models_failed(pid),
            on_missing_provider=self.on_node_models_failed,
        )

    def on_node_models_loaded(self, provider_id, models):
        models = [str(model).strip() for model in (models or []) if str(model).strip()]
        self.model_cache[provider_id] = models
        self.config.setdefault("model_cache", {})[provider_id] = list(models)
        save_config(self.config)
        updated = 0
        for node in list(self.nodes.values()):
            if node is not None and node.data.get("provider_id") == provider_id:
                node.set_model_options(models, node.data.get("model", ""), keep_current=False)
                updated += 1
        if updated:
            self.notify(f"模型列表已刷新，共 {len(models)} 个模型。")
        self.model_waiting_nodes.pop(provider_id, None)

    def on_node_models_failed(self, provider_id):
        updated = 0
        for node_id in list(self.model_waiting_nodes.get(provider_id, set())):
            node = self.nodes.get(node_id)
            if node is None or node.data.get("provider_id") != provider_id:
                continue
            if node.data.get("type") in ("text_to_image", "image_to_image"):
                fallback = IMAGE_FALLBACK_MODELS
            elif node.data.get("type") == "image_to_video":
                fallback = VIDEO_FALLBACK_MODELS
            else:
                fallback = AGENT_FALLBACK_MODELS
            node.set_model_options(fallback, "", keep_current=False)
            updated += 1
        if updated:
            self.notify("模型列表刷新失败，已显示保底模型。")
        self.model_waiting_nodes.pop(provider_id, None)

    def cleanup_model_worker(self, provider_id):
        self.model_loader.stop(provider_id)
        self.model_waiting_nodes.pop(provider_id, None)

    def upstream_edges(self, node, target_port_id=None):
        result = []
        for edge in self.edges:
            if edge.target_port.node is node:
                if target_port_id is None or edge.target_port.port_id == target_port_id:
                    result.append(edge)
        return result

    def upstream_text(self, node):
        for edge in self.upstream_edges(node, "text"):
            source = edge.source_port.node
            node_type = source.data.get("type")
            if node_type in ("prompt_input", "prompt_optimize"):
                source._sync_value_from_editor()
                return str(source.data.get("value", "") or "").strip()
            if node_type in ("text_to_image", "image_to_image"):
                source._sync_value_from_editor()
                text = str(source.data.get("value", "") or "").strip()
                if text:
                    return text
        node._sync_value_from_editor()
        text = str(node.data.get("value", "") or "").strip()
        return "" if text in NODE_PLACEHOLDER_TEXTS else text

    def upstream_image(self, node):
        for edge in self.upstream_edges(node, "image"):
            source = edge.source_port.node
            if edge.source_port.data_type == "image":
                path = source.data.get("image_path", "")
                if path:
                    return path
        return ""

    def run_node_generation(self, node):
        node_type = node.data.get("type")
        if node_type == "upload_image":
            self.pick_upload_image(node)
        elif node_type in ("text_to_image", "image_to_image"):
            self.run_image_node(node, edit=(node_type == "image_to_image"))
        elif node_type == "image_to_video":
            self.run_video_node(node)
        elif node_type == "prompt_optimize":
            self.run_prompt_optimize_node(node)

    def _node_by_id(self, node_id):
        node = self.nodes.get(node_id)
        if isinstance(node, WorkflowNodeItem):
            return node
        return None

    def _stop_worker_for_node(self, node_id):
        worker = self.workers.pop(node_id, None)
        if worker is None:
            return
        try:
            if hasattr(worker, "stop"):
                worker.stop()
            else:
                worker.requestInterruption()
        except Exception:
            pass

    def _cleanup_worker_for_node(self, node_id, worker):
        def cleanup():
            try:
                if self.workers.get(node_id) is worker:
                    self.workers.pop(node_id, None)
                if worker is not None:
                    worker.deleteLater()
            except Exception:
                pass
        QTimer.singleShot(0, cleanup)

    def pick_upload_image(self, node):
        path, _ = QFileDialog.getOpenFileName(
            None,
            "选择图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*)",
        )
        if not path:
            return
        self.set_upload_image_path(node, path)

    def pick_history_image(self, node):
        parent = None
        if self.views():
            parent = self.views()[0].window()
        dlg = ImageHistoryPickerDialog(parent)
        if dlg.exec() != QDialog.Accepted:
            return
        self.set_upload_image_path(node, dlg.selected_path)

    def set_upload_image_path(self, node, path):
        if not os.path.exists(path):
            self.notify("图片文件不存在。")
            return
        node.data["image_path"] = path
        node.data["value"] = path
        if node.value_edit is not None:
            node.value_edit.setPlainText(path)
        node.set_thumbnail(path)
        self.notify("图片已载入上传图片节点。")
        self.mark_changed()

    def run_image_node(self, node, edit=False):
        provider = self._provider_for_node(node)
        model = self._model_for_node(node)
        prompt = self.upstream_text(node)
        image_mode = node.data.get("image_mode") or ("图生图" if node.data.get("type") == "image_to_image" else "文生图")
        image_size = node.data.get("image_size") or self.config.get("image", {}).get("size", "自动")
        image_quality = node.data.get("image_quality") or self.config.get("image", {}).get("quality", "自动")
        image_count = node.data.get("image_count") or self.config.get("image", {}).get("count", "1")
        upload_optimization = self.config.get("image", {}).get("upload_optimization", "高质量")
        if not provider:
            self.notify("请先给节点选择 API 厂商。")
            return
        if not model:
            self.notify("请先给节点设置模型。")
            return
        if not prompt:
            self.notify("没有找到可用提示词。")
            return

        refs = []
        needs_ref = edit or image_mode == "图生图" or node.data.get("type") == "image_to_image"
        if needs_ref:
            ref = self.upstream_image(node)
            if not ref:
                self.notify("图生图节点没有收到上游图片。")
                return
            refs = [ref]

        self.notify("正在生成图片...")
        worker = ImageWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            image_size,
            image_quality,
            image_count,
            prompt,
            refs,
            provider.get("proxy_url", ""),
            upload_optimization,
            provider.get("proxy_mode", "仅下载图片" if provider.get("proxy_url") else "不使用代理"),
        )
        node_id = node.data["id"]
        self.workers[node_id] = worker
        worker.progress.connect(self.notify)
        worker.result_ready.connect(lambda result, nid=node_id: self.on_image_node_finished(nid, result))
        worker.failed.connect(lambda err, nid=node_id: self.on_node_failed(nid, err))
        worker.finished.connect(lambda nid=node_id, w=worker: self._cleanup_worker_for_node(nid, w))
        worker.start()

    def on_image_node_finished(self, node_id, result):
        node = self._node_by_id(node_id)
        images = result.get("images", []) if isinstance(result, dict) else []
        if not images:
            self.notify("图片生成完成，但没有返回图片。")
            return
        path = images[0]
        if node is None:
            self.sync_image_result_to_history(result)
            self.notify("图片节点已不存在，结果已同步到图片历史。")
            return
        node.data["image_path"] = path
        node.data["value"] = result.get("prompt", node.data.get("value", ""))
        if node.value_edit is not None:
            node.value_edit.setPlainText(node.data["value"])
        node.set_thumbnail(path)
        self.sync_image_result_to_history(result)
        self.notify("图片节点生成完成。")
        self.mark_changed()

    def run_video_node(self, node):
        provider = self._provider_for_node(node)
        model = self._model_for_node(node)
        prompt = self.upstream_text(node)

        if not provider:
            self.notify("请先给视频节点选择 API 厂商。")
            return
        if not model:
            self.notify("请先给视频节点设置模型。")
            return
        if not prompt.strip():
            self.notify("视频节点没有找到可用提示词。")
            return

        ref = self.upstream_image(node)
        if not ref:
            self.notify("图生视频节点没有收到上游参考图。")
            return

        size_label = node.data.get("video_size") or _video_size_label(
            self.config.get("video", {}).get("width", "1280"),
            self.config.get("video", {}).get("height", "720"),
        )
        width, height = VIDEO_SIZE_MAP.get(size_label, (1280, 720))
        frames = node.data.get("video_frames") or self.config.get("video", {}).get("num_frames", "81")
        fps = node.data.get("video_fps") or self.config.get("video", {}).get("frame_rate", "24")

        self.notify("正在生成视频...")
        worker = VideoWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            prompt,
            width,
            height,
            frames,
            fps,
            [ref],
            provider.get("proxy_url", ""),
            provider.get("proxy_mode", "仅下载图片" if provider.get("proxy_url") else "不使用代理"),
        )
        node_id = node.data["id"]
        self.workers[node_id] = worker
        worker.progress.connect(self.notify)
        worker.result_ready.connect(lambda result, nid=node_id: self.on_video_node_finished(nid, result))
        worker.failed.connect(lambda err, nid=node_id: self.on_node_failed(nid, err))
        worker.finished.connect(lambda nid=node_id, w=worker: self._cleanup_worker_for_node(nid, w))
        worker.start()

    def on_video_node_finished(self, node_id, result):
        node = self._node_by_id(node_id)
        path = result.get("video", "") if isinstance(result, dict) else ""
        if not path or not os.path.exists(path):
            self.notify("视频生成完成，但没有找到本地视频文件。")
            return
        if node is None:
            self.sync_video_result_to_history(result)
            self.notify("视频节点已不存在，结果已同步到视频历史。")
            return
        node.data["video_path"] = path
        node.data["value"] = f"视频已生成：\n{path}"
        if node.value_edit is not None:
            node.value_edit.setPlainText(node.data["value"])
        node.set_video_thumbnail(path)
        self.sync_video_result_to_history(result)
        self.notify("视频节点生成完成。")
        self.mark_changed()

    def sync_image_result_to_history(self, result):
        if not isinstance(result, dict):
            return
        images = [
            path for path in result.get("images", [])
            if isinstance(path, str) and os.path.exists(path)
        ]
        if not images:
            return

        history_result = dict(result)
        history_result["images"] = images
        refs = history_result.get("refs", [])
        if not isinstance(refs, list):
            refs = []
        history_result["refs"] = [path for path in refs if isinstance(path, str) and os.path.exists(path)]
        history_result.setdefault("prompt", "")

        image_tab = self.find_image_tab()
        if image_tab is not None:
            try:
                image_tab.history.append(history_result)
                image_tab.save_persistent_history()
                image_tab.add_images_to_gallery(history_result)
                return
            except Exception:
                pass

        try:
            append_image_result(history_result)
        except Exception as e:
            self.notify(f"图片历史保存失败，但节点结果已保留：{e}")

    def sync_video_result_to_history(self, result):
        if not isinstance(result, dict):
            return
        path = result.get("video", "")
        if not isinstance(path, str) or not os.path.exists(path):
            return
        video_tab = self.find_video_tab()
        if video_tab is not None:
            try:
                video_tab.history.append(dict(result))
                video_tab.save_persistent_history()
                video_tab.refresh_history_list()
                return
            except Exception:
                pass
        try:
            history = load_json_file(VIDEO_HISTORY_FILE, [])
            history = history if isinstance(history, list) else []
            history.append(dict(result))
            save_json_file(VIDEO_HISTORY_FILE, history[-200:])
        except Exception as e:
            self.notify(f"视频历史保存失败，但节点结果已保留：{e}")

    def find_image_tab(self):
        try:
            if self.views():
                win = self.views()[0].window()
                image_tab = getattr(win, "image_tab", None)
                if image_tab is not None:
                    return image_tab
        except Exception:
            pass
        return None

    def find_video_tab(self):
        try:
            if self.views():
                win = self.views()[0].window()
                video_tab = getattr(win, "video_tab", None)
                if video_tab is not None:
                    return video_tab
        except Exception:
            pass
        return None

    def run_prompt_optimize_node(self, node):
        provider = self._provider_for_node(node)
        model = self._model_for_node(node)
        prompt = self.upstream_text(node)
        if not provider:
            self.notify("请先给节点选择 API 厂商。")
            return
        if not model:
            self.notify("请先给节点设置模型。")
            return
        if not prompt:
            self.notify("没有找到可用提示词。")
            return

        messages = [
            {
                "role": "system",
                "content": "你是专业图像生成提示词优化器。请在不改变用户核心意图的前提下，把提示词优化为更清晰、可执行、细节丰富的图像生成提示词。只输出优化后的提示词。",
            },
            {"role": "user", "content": prompt},
        ]
        self.notify("正在优化提示词...")
        worker = ChatWorker(provider.get("base_url", ""), provider.get("api_key", ""), model, messages)
        node_id = node.data["id"]
        self.workers[node_id] = worker
        worker.result_ready.connect(lambda result, nid=node_id: self.on_prompt_node_finished(nid, result))
        worker.failed.connect(lambda err, nid=node_id: self.on_node_failed(nid, err))
        worker.finished.connect(lambda nid=node_id, w=worker: self._cleanup_worker_for_node(nid, w))
        worker.start()

    def on_prompt_node_finished(self, node_id, result):
        node = self._node_by_id(node_id)
        if node is None:
            self.notify("提示词优化节点已不存在，已忽略返回结果。")
            return
        text = result.get("content", "") if isinstance(result, dict) else ""
        if not text.strip():
            self.notify("提示词优化没有返回内容。")
            return
        node.data["value"] = text.strip()
        if node.value_edit is not None:
            node.value_edit.setPlainText(node.data["value"])
        self.notify("提示词优化完成。")
        self.mark_changed()

    def on_node_failed(self, node_id, err):
        node = self._node_by_id(node_id)
        title = node.data.get("title", "节点") if node is not None else "节点"
        self.notify(f"{title}失败：{err}")

    def remove_node(self, node):
        node_id = node.data.get("id")
        if node_id:
            self._stop_worker_for_node(node_id)
        for edge in list(self.edges):
            if edge.source_port.node is node or edge.target_port.node is node:
                self.remove_edge(edge)
        self.nodes.pop(node_id, None)
        try:
            node.detach_proxy_widgets()
        except Exception:
            pass
        self.removeItem(node)
        self.notify("节点已删除。")
        self.mark_changed()

    def remove_edge(self, edge):
        if edge in self.edges:
            self.edges.remove(edge)
        self.removeItem(edge)
        self.notify("连线已删除。")
        self.mark_changed()

    def update_edges_for_node(self, node):
        for edge in self.edges:
            if edge.source_port.node is node or edge.target_port.node is node:
                edge.update_path()

    def handle_port_click(self, port):
        if self.pending_port is None:
            if not port.is_output:
                self.notify("请从右侧输出端口开始连线。")
                return
            self.pending_port = port
            self.pending_line = QGraphicsPathItem()
            self.pending_line.setPen(QPen(QColor("#58a6ff"), 2, Qt.DashLine))
            self.pending_line.setZValue(-9)
            self.addItem(self.pending_line)
            self.update_pending_line(port.scenePos())
            self.notify("选择目标输入端口完成连线。")
            return

        if port is self.pending_port:
            self.cancel_pending_connection()
            return

        if port.is_output:
            self.notify("目标必须是左侧输入端口。")
            return

        if self.pending_port.node is port.node:
            self.notify("节点不能连接到自己。")
            return

        if self.pending_port.data_type != port.data_type:
            self.notify("端口类型不匹配。")
            return

        edge = WorkflowEdgeItem(self.pending_port, port)
        self.edges.append(edge)
        self.addItem(edge)
        self.cancel_pending_connection(notify=False)
        self.notify("连线已创建。")
        self.mark_changed()

    def update_pending_line(self, scene_pos):
        if not self.pending_port or not self.pending_line:
            return
        start = self.pending_port.scenePos()
        end = scene_pos
        dx = max(80, abs(end.x() - start.x()) * 0.5)
        path = QPainterPath(start)
        path.cubicTo(QPointF(start.x() + dx, start.y()), QPointF(end.x() - dx, end.y()), end)
        self.pending_line.setPath(path)

    def cancel_pending_connection(self, notify=True):
        if self.pending_line is not None:
            self.removeItem(self.pending_line)
        self.pending_line = None
        self.pending_port = None
        if notify:
            self.notify("连线已取消。")

    def contextMenuEvent(self, event):
        item = self.itemAt(event.scenePos(), self.views()[0].transform() if self.views() else QTransform())
        if item is not None:
            super().contextMenuEvent(event)
            return

        menu = QMenu()
        add_prompt = menu.addAction("添加提示词输入节点")
        add_upload = menu.addAction("添加上传图片节点")
        add_t2i = menu.addAction("添加文生图节点")
        add_i2i = menu.addAction("添加图生图节点")
        add_i2v = menu.addAction("添加图生视频节点")
        add_opt = menu.addAction("添加提示词优化节点")
        clear_action = menu.addAction("清空画布")
        action = menu.exec(event.screenPos())
        if action == add_prompt:
            self.add_node("prompt_input", event.scenePos())
        elif action == add_upload:
            self.add_node("upload_image", event.scenePos())
        elif action == add_t2i:
            self.add_node("text_to_image", event.scenePos())
        elif action == add_i2i:
            self.add_node("image_to_image", event.scenePos())
        elif action == add_i2v:
            self.add_node("image_to_video", event.scenePos())
        elif action == add_opt:
            self.add_node("prompt_optimize", event.scenePos())
        elif action == clear_action:
            self.clear_workflow()

    def clear_workflow(self):
        self.cancel_pending_connection(notify=False)
        for node_id in list(self.workers.keys()):
            self._stop_worker_for_node(node_id)
        for edge in list(self.edges):
            try:
                self.removeItem(edge)
            except Exception:
                pass
        for node in list(self.nodes.values()):
            try:
                node.detach_proxy_widgets()
                self.removeItem(node)
            except Exception:
                pass
        self.nodes = {}
        self.edges = []
        self.notify("画布已清空。")
        self.mark_changed()

    def to_json_text(self):
        data = {
            "version": 1,
            "nodes": [node.to_json() for node in self.nodes.values()],
            "edges": [
                {
                    "id": edge.id,
                    "source": edge.source_port.node.data["id"],
                    "source_port": edge.source_port.port_id,
                    "target": edge.target_port.node.data["id"],
                    "target_port": edge.target_port.port_id,
                }
                for edge in self.edges
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    def load_json_text(self, text):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("JSON 格式不正确。")
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValueError("JSON 必须包含 nodes 和 edges。")

        self.clear_workflow()
        for node_data in nodes:
            if not isinstance(node_data, dict):
                continue
            node_type = node_data.get("type")
            node_type = LEGACY_NODE_TYPE_MAP.get(node_type, node_type)
            if node_type not in NODE_CATALOG:
                continue
            node_data = dict(node_data)
            node_data["type"] = node_type
            node_data.setdefault("title", NODE_CATALOG[node_type]["title"])
            node_data.setdefault("accent", NODE_CATALOG[node_type]["accent"])
            item = WorkflowNodeItem(node_data)
            self.nodes[item.data["id"]] = item
            self.addItem(item)
            item.refresh_config_controls(self.config)

        for edge_data in edges:
            try:
                source = self.nodes[edge_data["source"]]
                target = self.nodes[edge_data["target"]]
                source_port = source.output_ports[edge_data["source_port"]]
                target_port = target.input_ports[edge_data["target_port"]]
            except Exception:
                continue
            edge = WorkflowEdgeItem(source_port, target_port, edge_data.get("id"))
            self.edges.append(edge)
            self.addItem(edge)
        self.notify("工作流已导入。")
        self.mark_changed()


class WorkflowView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._panning = False
        self._last_pan_pos = None
        self._zoom = 1.0
        self._min_zoom = 0.08
        self._max_zoom = 3.5
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setBackgroundBrush(QColor("#0f131a"))
        self.setCursor(Qt.OpenHandCursor)
        self.viewport().setCursor(Qt.OpenHandCursor)

    def _set_view_cursor(self, cursor):
        self.setCursor(cursor)
        self.viewport().setCursor(cursor)

    def fit_nodes(self, margin=80):
        scene = self.scene()
        if not isinstance(scene, WorkflowScene) or not scene.nodes:
            self.centerOn(0, 0)
            return
        rect = QRectF()
        for node in scene.nodes.values():
            node_rect = node.mapToScene(node.boundingRect()).boundingRect()
            rect = node_rect if rect.isNull() else rect.united(node_rect)
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            return
        rect = rect.adjusted(-margin, -margin, margin, margin)
        view_size = self.viewport().rect().size()
        if view_size.width() <= 0 or view_size.height() <= 0:
            return
        scale_x = view_size.width() / rect.width()
        scale_y = view_size.height() / rect.height()
        self._zoom = max(self._min_zoom, min(1.0, scale_x, scale_y))
        self.setTransform(QTransform().scale(self._zoom, self._zoom))
        self.centerOn(rect.center())

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)

        minor = 32
        major = 160
        left = int(rect.left()) - (int(rect.left()) % minor)
        top = int(rect.top()) - (int(rect.top()) % minor)

        minor_lines = []
        major_lines = []

        x = left
        while x < rect.right():
            target = major_lines if x % major == 0 else minor_lines
            target.append(QLineF(x, rect.top(), x, rect.bottom()))
            x += minor

        y = top
        while y < rect.bottom():
            target = major_lines if y % major == 0 else minor_lines
            target.append(QLineF(rect.left(), y, rect.right(), y))
            y += minor

        painter.setPen(QPen(QColor("#1d2530"), 1))
        painter.drawLines(minor_lines)
        painter.setPen(QPen(QColor("#273341"), 1))
        painter.drawLines(major_lines)
        painter.restore()

    def wheelEvent(self, event):
        if event.angleDelta().y() == 0:
            event.ignore()
            return

        cursor_pos = event.position().toPoint()
        scene_pos = self.mapToScene(cursor_pos)
        factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        next_zoom = max(self._min_zoom, min(self._max_zoom, self._zoom * factor))
        if abs(next_zoom - self._zoom) < 0.0001:
            event.accept()
            return

        self._zoom = next_zoom
        self.setTransform(QTransform().scale(self._zoom, self._zoom))
        after_pos = self.mapToScene(cursor_pos)
        delta = after_pos - scene_pos
        self.translate(delta.x(), delta.y())
        event.accept()

    def mousePressEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.MiddleButton):
            item = self.itemAt(event.position().toPoint())
            if event.button() == Qt.LeftButton and item is not None:
                super().mousePressEvent(event)
                return
            self._panning = True
            self._last_pan_pos = event.position().toPoint()
            self._set_view_cursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene = self.scene()
        if isinstance(scene, WorkflowScene):
            scene.update_pending_line(self.mapToScene(event.position().toPoint()))

        if self._panning and self._last_pan_pos is not None:
            pos = event.position().toPoint()
            delta = pos - self._last_pan_pos
            self._last_pan_pos = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.MiddleButton) and self._panning:
            self._panning = False
            self._last_pan_pos = None
            self._set_view_cursor(Qt.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not self._panning:
            self._set_view_cursor(Qt.OpenHandCursor)
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            scene = self.scene()
            if isinstance(scene, WorkflowScene):
                scene.cancel_pending_connection()
            return
        super().keyPressEvent(event)


def _video_size_label(width, height):
    try:
        pair = (int(width), int(height))
    except Exception:
        pair = (1280, 720)
    for label, value in VIDEO_SIZE_MAP.items():
        if value == pair:
            return label
    return "1280x720（横屏）"
