import copy
import json
import math
import os
import re
import sys
import uuid

from PySide6.QtCore import QLineF, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QCheckBox,
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
from .blender_director_project import (
    build_blender_director_action_matches,
    build_blender_director_storyboard,
    launch_blender_director_project,
    load_blender_director_metadata,
    prepare_blender_director_project,
    summarize_blender_director_metadata,
    write_blender_director_actor_schedule_csv,
    write_blender_director_actor_schedule_manifest,
    write_blender_director_actor_schedule_report,
    write_blender_director_action_matches_csv,
    write_blender_director_action_matches_manifest,
    write_blender_director_action_matches_report,
    write_blender_director_asset_requirements_csv,
    write_blender_director_asset_requirements_manifest,
    write_blender_director_asset_requirements_report,
    write_blender_director_asset_usage_csv,
    write_blender_director_batch_render_jobs_csv,
    write_blender_director_batch_render_jobs_manifest,
    write_blender_director_batch_render_jobs_report,
    write_blender_director_batch_render_command,
    write_blender_director_call_sheet_csv,
    write_blender_director_call_sheet_manifest,
    write_blender_director_call_sheet_report,
    write_blender_director_continuity_check_csv,
    write_blender_director_continuity_check_manifest,
    write_blender_director_continuity_check_report,
    write_blender_director_delivery_audit,
    write_blender_director_delivery_audit_report,
    write_blender_director_delivery_package,
    write_blender_director_duration_summary,
    write_blender_director_edit_decision_list,
    write_blender_director_edit_timeline_csv,
    write_blender_director_edit_timeline_manifest,
    write_blender_director_edit_timeline_report,
    write_blender_director_episode_delivery_csv,
    write_blender_director_episode_delivery_manifest,
    write_blender_director_episode_delivery_packages,
    write_blender_director_episode_delivery_report,
    write_blender_director_final_cut_xml,
    write_blender_director_post_handoff_csv,
    write_blender_director_post_handoff_manifest,
    write_blender_director_post_handoff_report,
    write_blender_director_production_manifest,
    write_blender_director_production_report,
    write_blender_director_production_check_csv,
    write_blender_director_production_check_manifest,
    write_blender_director_production_check_report,
    write_blender_director_project_dashboard,
    write_blender_director_render_queue_csv,
    write_blender_director_render_queue_manifest,
    write_blender_director_render_queue_report,
    write_blender_director_render_versions_csv,
    write_blender_director_render_versions_manifest,
    write_blender_director_render_versions_report,
    write_blender_director_scene_breakdown_csv,
    write_blender_director_scene_breakdown_manifest,
    write_blender_director_scene_breakdown_report,
    write_blender_director_storyboard_csv,
    write_blender_director_storyboard_manifest,
    write_blender_director_storyboard_report,
)
from .workers import (
    BlenderDirectorWorker,
    BlenderStoryboardWorker,
    ImageWorker,
    ModelListWorker,
    VideoWorker,
    blender_detection_issue,
    resolve_blender_executable,
)


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
    "blender_storyboard": {
        "title": "Blender分镜节点",
        "accent": "#2563eb",
        "inputs": [{"id": "text", "label": "镜头描述", "data_type": "text"}],
        "outputs": [{"id": "image", "label": "分镜图", "data_type": "image"}],
        "value": "输入镜头描述，例如：会议室里，男主站在门口，众人回头，低角度中景。",
    },
    "blender_model": {
        "title": "Blender模型节点",
        "accent": "#0f766e",
        "inputs": [],
        "outputs": [{"id": "blender", "label": "模型", "data_type": "blender"}],
        "value": "选择或输入 .glb/.gltf/.fbx/.obj 模型路径",
    },
    "blender_scene": {
        "title": "Blender场景节点",
        "accent": "#0e7490",
        "inputs": [
            {"id": "blender", "label": "Blender", "data_type": "blender"},
            {"id": "text", "label": "场景说明", "data_type": "text"},
        ],
        "outputs": [{"id": "blender", "label": "场景", "data_type": "blender"}],
        "value": "房间/街道/舞台，主要道具和灯光说明",
    },
    "blender_character": {
        "title": "Blender人物节点",
        "accent": "#7c3aed",
        "inputs": [
            {"id": "blender", "label": "Blender", "data_type": "blender"},
            {"id": "text", "label": "人物动作", "data_type": "text"},
        ],
        "outputs": [{"id": "blender", "label": "人物", "data_type": "blender"}],
        "value": "人物数量、站位、朝向、姿势、动作",
    },
    "blender_camera": {
        "title": "Blender镜头节点",
        "accent": "#be123c",
        "inputs": [
            {"id": "blender", "label": "Blender", "data_type": "blender"},
            {"id": "text", "label": "镜头说明", "data_type": "text"},
        ],
        "outputs": [{"id": "blender", "label": "镜头", "data_type": "blender"}],
        "value": "中景/近景/远景/俯拍/仰拍/推镜/侧拍",
    },
    "blender_render": {
        "title": "Blender渲染节点",
        "accent": "#ea580c",
        "inputs": [
            {"id": "blender", "label": "Blender", "data_type": "blender"},
            {"id": "text", "label": "渲染说明", "data_type": "text"},
        ],
        "outputs": [{"id": "image", "label": "参考图", "data_type": "image"}],
        "value": "输出导演台参考图，可继续接图生图或图生视频",
    },
    "blender_director_project": {
        "title": "Blender导演台工程",
        "accent": "#14b8a6",
        "inputs": [
            {"id": "blender", "label": "Blender", "data_type": "blender"},
            {"id": "text", "label": "工程说明", "data_type": "text"},
        ],
        "outputs": [{"id": "blender", "label": "工程", "data_type": "blender"}],
        "value": "打开可拖动、可摆位、可调镜头的 Blender 导演台工程。",
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
IMAGE_FALLBACK_MODELS = ["gpt-image-2", "gpt-image-2-vip", "gpt-image-1", "dall-e-3", "dall-e-2"]
VIDEO_FALLBACK_MODELS = ["agnes-video-v2.0"]
AGENT_FALLBACK_MODELS = ["gpt-4o", "gpt-4.1", "gpt-3.5-turbo"]
NODE_PLACEHOLDER_TEXTS = {"等待上游节点输入", "请选择本地图片"}
BLENDER_PLAN_NODE_TYPES = ("blender_model", "blender_scene", "blender_character", "blender_camera", "blender_director_project")
BLENDER_RENDER_NODE_TYPES = ("blender_storyboard", "blender_render")
BLENDER_NODE_TYPES = BLENDER_PLAN_NODE_TYPES + BLENDER_RENDER_NODE_TYPES

def re_split_model_paths(text):
    return re.split(r"[\n,;；，]+", str(text or ""))

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
        "blender_width": "",
        "blender_height": "",
        "blender_plan": {},
        "director_project": {},
        "director_project_id": "",
        "director_synced_renders": [],
        "model_paths": [],
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


class BlenderDirectorProjectDialog(QDialog):
    IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    ASSET_KIND_LABELS = {
        "character": "人物",
        "prop": "道具",
        "scene": "场景",
        "action": "动作",
        "model": "通用模型",
        "material": "材质",
        "texture": "贴图",
        "hdri": "HDRI",
    }
    ACTION_STATUS_LABELS = {
        "applied": "已套用",
        "failed": "套用失败",
        "not_applied": "未套用",
    }
    RENDER_MODE_LABELS = {
        "current": "当前镜头",
        "batch": "批量渲染",
    }
    ASSET_FILTER_OPTIONS = [
        ("all", "全部资产"),
        ("character", "人物"),
        ("prop", "道具"),
        ("scene", "场景"),
        ("action", "动作"),
        ("model", "通用模型"),
        ("material", "材质"),
        ("texture", "贴图"),
        ("hdri", "HDRI"),
    ]
    LIBRARY_ITEM_PREVIEW_LIMIT = 200

    @staticmethod
    def _actor_record_label(actor):
        if not isinstance(actor, dict):
            return ""
        name = str(actor.get("name") or actor.get("id") or "").strip()
        role = str(actor.get("role") or "").strip()
        if name and role:
            return f"{name}（{role}）"
        return name or role

    def __init__(self, metadata, parent=None):
        super().__init__(parent)
        self.metadata = metadata if isinstance(metadata, dict) else {}
        self.setWindowTitle("Blender 导演台工程清单")
        self.resize(1120, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = str(self.metadata.get("project_name") or "Blender 导演台工程").strip()
        summary = summarize_blender_director_metadata(self.metadata)
        title_label = QLabel(f"{title}\n{summary}")
        title_label.setStyleSheet("color:#e8e8ea; font-weight:700;")
        root.addWidget(title_label)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        root.addLayout(grid, 1)

        self.asset_list = QListWidget()
        self.action_list = QListWidget()
        self.shot_list = QListWidget()
        self.render_list = QListWidget()
        self.asset_filter_combo = QComboBox()
        self.asset_search_edit = QLineEdit()
        self.asset_favorites_only = QCheckBox("只看收藏")
        for value, label in self.ASSET_FILTER_OPTIONS:
            self.asset_filter_combo.addItem(label, value)
        self.asset_filter_combo.currentIndexChanged.connect(self._load_assets)
        self.asset_search_edit.setPlaceholderText("搜索资产名称、路径、格式")
        self.asset_search_edit.textChanged.connect(self._load_assets)
        self.asset_favorites_only.toggled.connect(self._load_assets)
        self._style_list(self.asset_list)
        self._style_list(self.action_list)
        self._style_list(self.shot_list)
        self._style_list(self.render_list)
        self.asset_filter_combo.setStyleSheet("""
            QComboBox {
                background-color:#151922;
                color:#d9e2ee;
                border:1px solid #303640;
                border-radius:6px;
                padding:5px 8px;
            }
            QComboBox QAbstractItemView {
                background-color:#151922;
                color:#d9e2ee;
                selection-background-color:#23415f;
            }
        """)
        self.asset_search_edit.setStyleSheet("""
            QLineEdit {
                background-color:#151922;
                color:#d9e2ee;
                border:1px solid #303640;
                border-radius:6px;
                padding:5px 8px;
            }
            QLineEdit::placeholder {
                color:#758195;
            }
        """)
        self.asset_favorites_only.setStyleSheet("""
            QCheckBox {
                color:#c9d4e2;
                spacing:6px;
            }
            QCheckBox::indicator {
                width:14px;
                height:14px;
            }
        """)

        grid.addWidget(self._section_title("资产库"), 0, 0)
        grid.addWidget(self._section_title("场景/动作/机位记录"), 0, 1)
        grid.addWidget(self._section_title("镜头"), 0, 2)
        grid.addWidget(self._section_title("输出"), 0, 3)
        asset_panel = QVBoxLayout()
        asset_panel.setContentsMargins(0, 0, 0, 0)
        asset_panel.setSpacing(6)
        asset_panel.addWidget(self.asset_filter_combo)
        asset_panel.addWidget(self.asset_search_edit)
        asset_panel.addWidget(self.asset_favorites_only)
        asset_panel.addWidget(self.asset_list, 1)
        grid.addLayout(asset_panel, 1, 0)
        grid.addWidget(self.action_list, 1, 1)
        grid.addWidget(self.shot_list, 1, 2)
        grid.addWidget(self.render_list, 1, 3)

        asset_btn = QPushButton("打开选中资产")
        asset_btn.clicked.connect(self.open_selected_asset)
        asset_folder_btn = QPushButton("打开资产目录")
        asset_folder_btn.clicked.connect(self.open_asset_folder)
        render_btn = QPushButton("打开选中输出")
        render_btn.clicked.connect(self.open_selected_render)
        render_folder_btn = QPushButton("打开渲染目录")
        render_folder_btn.clicked.connect(self.open_render_folder)
        shot_btn = QPushButton("打开选中镜头")
        shot_btn.clicked.connect(self.open_selected_shot)
        action_record_btn = QPushButton("打开选中记录")
        action_record_btn.clicked.connect(self.open_selected_action_record)
        storyboard_btn = QPushButton("打开分镜表")
        storyboard_btn.clicked.connect(self.open_storyboard_manifest)
        render_queue_btn = QPushButton("渲染队列")
        render_queue_btn.clicked.connect(self.open_render_queue_report)
        scene_breakdown_btn = QPushButton("分场表")
        scene_breakdown_btn.clicked.connect(self.open_scene_breakdown_report)
        actor_schedule_btn = QPushButton("演员调度")
        actor_schedule_btn.clicked.connect(self.open_actor_schedule_report)
        production_btn = QPushButton("制作清单")
        production_btn.clicked.connect(self.open_production_report)
        audit_btn = QPushButton("交付检查")
        audit_btn.clicked.connect(self.open_delivery_audit)
        delivery_btn = QPushButton("生成交付包")
        delivery_btn.clicked.connect(self.open_delivery_package)
        asset_buttons = QHBoxLayout()
        asset_buttons.addWidget(asset_btn)
        asset_buttons.addWidget(asset_folder_btn)
        grid.addLayout(asset_buttons, 2, 0)
        action_buttons = QHBoxLayout()
        action_buttons.addWidget(action_record_btn)
        action_buttons.addWidget(storyboard_btn)
        action_buttons.addWidget(render_queue_btn)
        action_buttons.addWidget(scene_breakdown_btn)
        action_buttons.addWidget(actor_schedule_btn)
        action_buttons.addWidget(production_btn)
        action_buttons.addWidget(audit_btn)
        action_buttons.addWidget(delivery_btn)
        grid.addLayout(action_buttons, 2, 1)
        grid.addWidget(shot_btn, 2, 2)
        render_buttons = QHBoxLayout()
        render_buttons.addWidget(render_btn)
        render_buttons.addWidget(render_folder_btn)
        grid.addLayout(render_buttons, 2, 3)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        files_btn = buttons.addButton("制作文件", QDialogButtonBox.ActionRole)
        files_menu = QMenu(files_btn)
        for label, handler in (
            ("工程总览", self.open_project_dashboard),
            ("分镜表", self.open_storyboard_manifest),
            ("渲染队列", self.open_render_queue_report),
            ("批量渲染任务", self.open_batch_render_jobs_report),
            ("后台渲染命令", self.open_batch_render_command_report),
            ("镜头版本索引", self.open_render_versions_report),
            ("分场表", self.open_scene_breakdown_report),
            ("分集交付清单", self.open_episode_delivery_report),
            ("生成分集交付包", self.open_episode_delivery_packages),
            ("拍摄单", self.open_call_sheet_report),
            ("演员调度", self.open_actor_schedule_report),
            ("剪辑时间线", self.open_edit_timeline_report),
            ("剪辑 EDL", self.open_edit_decision_list),
            ("剪辑 FCPXML", self.open_final_cut_xml),
            ("后期交接清单", self.open_post_handoff_report),
            ("连续性检查", self.open_continuity_check_report),
            ("制作问题检查", self.open_production_check_report),
            ("制作清单", self.open_production_report),
            ("资产需求清单", self.open_asset_requirements_report),
            ("动作匹配清单", self.open_action_matches_report),
            ("交付检查", self.open_delivery_audit),
            ("生成交付包", self.open_delivery_package),
        ):
            action = files_menu.addAction(label)
            action.triggered.connect(lambda checked=False, fn=handler: fn())
        files_btn.setMenu(files_menu)
        dashboard_btn = buttons.addButton("工程总览", QDialogButtonBox.ActionRole)
        dashboard_btn.clicked.connect(self.open_project_dashboard)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load_assets()
        self._load_action_applications()
        self._load_shots()
        self._load_renders()

    def _section_title(self, text):
        label = QLabel(text)
        label.setStyleSheet("color:#c9d4e2; font-weight:700;")
        return label

    def _style_list(self, widget):
        widget.setAlternatingRowColors(True)
        widget.setStyleSheet("""
            QListWidget {
                background-color:#10151c;
                color:#d9e2ee;
                border:1px solid #303640;
                border-radius:8px;
                padding:6px;
            }
            QListWidget::item {
                padding:7px;
                border-bottom:1px solid #242b36;
            }
            QListWidget::item:selected {
                background-color:#23415f;
            }
        """)

    def _asset_item_matches_query(self, item, query, fields):
        if not query:
            return True
        haystack = " ".join(str(item.get(field) or "") for field in fields).lower()
        return query in haystack

    def _load_assets(self):
        self.asset_list.clear()
        assets = self.metadata.get("assets") if isinstance(self.metadata.get("assets"), list) else []
        builtin_asset_pack = (
            self.metadata.get("builtin_asset_pack") if isinstance(self.metadata.get("builtin_asset_pack"), list) else []
        )
        open_asset_source_profiles = (
            self.metadata.get("open_asset_source_profiles")
            if isinstance(self.metadata.get("open_asset_source_profiles"), list)
            else []
        )
        asset_sources = (
            self.metadata.get("asset_sources") if isinstance(self.metadata.get("asset_sources"), list) else []
        )
        asset_libraries = (
            self.metadata.get("asset_libraries") if isinstance(self.metadata.get("asset_libraries"), list) else []
        )
        asset_library_items = (
            self.metadata.get("asset_library_items")
            if isinstance(self.metadata.get("asset_library_items"), list)
            else []
        )
        selected_kind = str(self.asset_filter_combo.currentData() or "all") if self.asset_filter_combo else "all"
        query = str(self.asset_search_edit.text() or "").strip().lower() if self.asset_search_edit else ""
        favorites_only = bool(self.asset_favorites_only.isChecked()) if self.asset_favorites_only else False
        added = 0
        if selected_kind == "all" and not favorites_only:
            for source in asset_sources:
                if not isinstance(source, dict):
                    continue
                if not self._asset_item_matches_query(
                    source,
                    query,
                    ("name", "path", "profile_id", "profile_name", "route", "scanned_at"),
                ):
                    continue
                name = str(source.get("name") or os.path.basename(str(source.get("path") or "")) or "资产源")
                profile_name = str(source.get("profile_name") or source.get("profile_id") or "通用本地资产库")
                path = str(source.get("path") or "").strip()
                item_count = source.get("item_count")
                scanned_at = str(source.get("scanned_at") or "").strip()
                route = str(source.get("route") or "").strip()
                details = [profile_name]
                if item_count is not None:
                    details.append(f"文件 {item_count} 个")
                if route:
                    details.append(route)
                if path:
                    details.append(path)
                if scanned_at:
                    details.append(scanned_at)
                item = QListWidgetItem("资产源｜" + name + (("\n" + "\n".join(details)) if details else ""))
                item.setToolTip(json.dumps(source, ensure_ascii=False, indent=2))
                if path:
                    item.setData(Qt.UserRole, path)
                self.asset_list.addItem(item)
                added += 1
            if not asset_sources:
                for profile in open_asset_source_profiles:
                    if not isinstance(profile, dict):
                        continue
                    if not self._asset_item_matches_query(
                        profile,
                        query,
                        ("id", "name", "route"),
                    ):
                        continue
                    name = str(profile.get("name") or profile.get("id") or "开源资产生态")
                    formats = profile.get("formats") if isinstance(profile.get("formats"), list) else []
                    route = str(profile.get("route") or "").strip()
                    details = []
                    if formats:
                        details.append("格式：" + " / ".join(str(item).upper() for item in formats[:8]))
                    if route:
                        details.append(route)
                    item = QListWidgetItem("生态方案｜" + name + (("\n" + "\n".join(details)) if details else ""))
                    item.setToolTip(json.dumps(profile, ensure_ascii=False, indent=2))
                    self.asset_list.addItem(item)
                    added += 1
            for library in asset_libraries:
                if not isinstance(library, dict):
                    continue
                if not self._asset_item_matches_query(library, query, ("name", "path", "scanned_at")):
                    continue
                path = str(library.get("path") or "").strip()
                name = str(library.get("name") or os.path.basename(path) or "资产库目录")
                item_count = library.get("item_count")
                scanned_at = str(library.get("scanned_at") or "").strip()
                details = []
                source_profile_name = str(library.get("source_profile_name") or "").strip()
                if source_profile_name:
                    details.append("来源：" + source_profile_name)
                if item_count is not None:
                    details.append(f"文件 {item_count} 个")
                if path:
                    details.append(path)
                if scanned_at:
                    details.append(scanned_at)
                item = QListWidgetItem("资产库目录｜" + name + (("\n" + "\n".join(details)) if details else ""))
                item.setToolTip(json.dumps(library, ensure_ascii=False, indent=2))
                if path:
                    item.setData(Qt.UserRole, path)
                self.asset_list.addItem(item)
                added += 1
        library_candidates = [
            item
            for item in asset_library_items
            if isinstance(item, dict)
            and (selected_kind == "all" or str(item.get("kind_hint") or "") == selected_kind)
            and (not favorites_only or bool(item.get("favorite")))
            and self._asset_item_matches_query(
                item,
                query,
                (
                    "name",
                    "file_name",
                    "relative_path",
                    "path",
                    "format",
                    "kind_hint",
                    "tags",
                    "usage_note",
                    "modified_at",
                    "source_profile_name",
                ),
            )
        ]
        visible_library_items = library_candidates[: self.LIBRARY_ITEM_PREVIEW_LIMIT]
        for library_item in visible_library_items:
            path = str(library_item.get("path") or "").strip()
            name = str(library_item.get("name") or library_item.get("file_name") or os.path.basename(path) or "库资产")
            file_format = str(library_item.get("format") or "").strip()
            relative_path = str(library_item.get("relative_path") or "").strip()
            modified_at = str(library_item.get("modified_at") or "").strip()
            kind_hint = self.ASSET_KIND_LABELS.get(str(library_item.get("kind_hint") or ""), "")
            favorite = bool(library_item.get("favorite"))
            favorited_at = str(library_item.get("favorited_at") or "").strip()
            tags = str(library_item.get("tags") or "").strip()
            usage_note = str(library_item.get("usage_note") or "").strip()
            usage_count = library_item.get("usage_count")
            last_used_at = str(library_item.get("last_used_at") or "").strip()
            source_profile_name = str(library_item.get("source_profile_name") or "").strip()
            texture_role = str(library_item.get("texture_role") or "").strip()
            details = []
            if source_profile_name:
                details.append("来源：" + source_profile_name)
            if favorite:
                details.append("已收藏" + (f"：{favorited_at}" if favorited_at else ""))
            if kind_hint:
                details.append(kind_hint)
            if texture_role:
                details.append("贴图：" + texture_role)
            if file_format:
                details.append(file_format.upper())
            if usage_count not in (None, ""):
                details.append(f"使用 {usage_count} 次" + (f"：{last_used_at}" if last_used_at else ""))
            if tags:
                details.append("标签：" + tags)
            if usage_note:
                details.append("备注：" + usage_note)
            if relative_path:
                details.append(relative_path)
            if modified_at:
                details.append(modified_at)
            prefix = "★ " if favorite else ""
            item = QListWidgetItem("库资产｜" + prefix + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(library_item, ensure_ascii=False, indent=2))
            if path:
                item.setData(Qt.UserRole, path)
            self.asset_list.addItem(item)
            added += 1
        remaining = len(library_candidates) - len(visible_library_items)
        if remaining > 0:
            self.asset_list.addItem(f"还有 {remaining} 个库资产未在清单预览，完整列表请在 Blender 面板里选择")
            added += 1
        visible_assets = []
        visible_builtin_assets = []
        for asset in builtin_asset_pack:
            if not isinstance(asset, dict):
                continue
            if selected_kind != "all" and str(asset.get("type") or "") != selected_kind:
                continue
            if favorites_only:
                continue
            if not self._asset_item_matches_query(
                asset,
                query,
                ("id", "name", "type", "format", "license", "description"),
            ):
                continue
            visible_builtin_assets.append(asset)
        for asset in visible_builtin_assets:
            kind = self.ASSET_KIND_LABELS.get(str(asset.get("type") or ""), "资产")
            name = str(asset.get("name") or asset.get("id") or "内置资产")
            asset_format = str(asset.get("format") or "").strip()
            license_label = str(asset.get("license") or "").strip()
            controls = asset.get("controls") if isinstance(asset.get("controls"), list) else []
            description = str(asset.get("description") or "").strip()
            details = []
            if asset_format:
                details.append(asset_format.upper())
            if license_label:
                details.append("授权：" + license_label)
            if controls:
                details.append("控制：" + " / ".join(str(item) for item in controls[:5]))
            if description:
                details.append(description)
            item = QListWidgetItem(f"内置{kind}｜{name}" + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(asset, ensure_ascii=False, indent=2))
            self.asset_list.addItem(item)
            added += 1
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            if selected_kind != "all" and str(asset.get("type") or "") != selected_kind:
                continue
            if favorites_only and not bool(asset.get("favorite")):
                continue
            if not self._asset_item_matches_query(
                asset,
                query,
                ("name", "file_name", "path", "format", "type", "imported_at"),
            ):
                continue
            visible_assets.append(asset)
        if not visible_assets:
            if added <= 0:
                label = self.asset_filter_combo.currentText() if self.asset_filter_combo else "当前类型"
                suffix = "收藏资产" if favorites_only else "资产"
                self.asset_list.addItem(f"{label}暂无{suffix}")
            return
        for asset in visible_assets:
            kind = self.ASSET_KIND_LABELS.get(str(asset.get("type") or ""), "资产")
            path = str(asset.get("path") or "").strip()
            name = str(asset.get("name") or asset.get("file_name") or os.path.basename(path) or "未命名资产")
            imported_at = str(asset.get("imported_at") or "").strip()
            favorite = bool(asset.get("favorite"))
            details = []
            if favorite:
                details.append("已收藏")
            asset_format = str(asset.get("format") or "").strip()
            objects = asset.get("objects") if isinstance(asset.get("objects"), list) else []
            collections = asset.get("collections") if isinstance(asset.get("collections"), list) else []
            actions = asset.get("actions") if isinstance(asset.get("actions"), list) else []
            texture_paths = asset.get("texture_paths") if isinstance(asset.get("texture_paths"), list) else []
            material_name = str(asset.get("material_name") or "").strip()
            world = str(asset.get("world") or "").strip()
            counts = []
            if asset_format:
                counts.append(asset_format.upper())
            if objects:
                counts.append(f"对象 {len(objects)} 个")
            if collections:
                counts.append(f"集合 {len(collections)} 个")
            if actions:
                counts.append(f"动作 {len(actions)} 个")
            if texture_paths:
                counts.append(f"贴图 {len(texture_paths)} 张")
            if counts:
                details.append(" · ".join(counts))
            if material_name:
                details.append("材质：" + material_name)
            if world:
                details.append("环境：" + world)
            source_profile_name = str(asset.get("source_profile_name") or "").strip()
            if source_profile_name:
                details.append("来源：" + source_profile_name)
            if asset.get("type") == "action":
                status = self.ACTION_STATUS_LABELS.get(str(asset.get("auto_apply_status") or ""), "")
                target = str(asset.get("target_armature") or "").strip()
                message = str(asset.get("auto_apply_message") or "").strip()
                if status:
                    details.append(status + (f"：{target}" if target else ""))
                if message:
                    details.append(message)
            if imported_at:
                details.append(imported_at)
            prefix = "★ " if favorite else ""
            item = QListWidgetItem(f"{kind}｜{prefix}{name}" + (("\n" + "\n".join(details)) if details else ""))
            if path:
                item.setToolTip(path)
                item.setData(Qt.UserRole, path)
            self.asset_list.addItem(item)

    def _load_action_applications(self):
        self.action_list.clear()
        records = self.metadata.get("action_applications") if isinstance(self.metadata.get("action_applications"), list) else []
        render_templates = self.metadata.get("render_templates") if isinstance(self.metadata.get("render_templates"), list) else []
        light_templates = self.metadata.get("light_templates") if isinstance(self.metadata.get("light_templates"), list) else []
        action_clips = self.metadata.get("action_clips") if isinstance(self.metadata.get("action_clips"), list) else []
        pose_templates = self.metadata.get("pose_templates") if isinstance(self.metadata.get("pose_templates"), list) else []
        animation_templates = self.metadata.get("animation_templates") if isinstance(self.metadata.get("animation_templates"), list) else []
        material_templates = self.metadata.get("material_templates") if isinstance(self.metadata.get("material_templates"), list) else []
        material_applications = self.metadata.get("material_applications") if isinstance(self.metadata.get("material_applications"), list) else []
        camera_motions = self.metadata.get("camera_motions") if isinstance(self.metadata.get("camera_motions"), list) else []
        camera_templates = self.metadata.get("camera_templates") if isinstance(self.metadata.get("camera_templates"), list) else []
        object_templates = self.metadata.get("object_templates") if isinstance(self.metadata.get("object_templates"), list) else []
        object_motions = self.metadata.get("object_motions") if isinstance(self.metadata.get("object_motions"), list) else []
        actors = self.metadata.get("actors") if isinstance(self.metadata.get("actors"), list) else []
        scene_presets = self.metadata.get("scene_presets") if isinstance(self.metadata.get("scene_presets"), list) else []
        shot_packages = self.metadata.get("shot_packages") if isinstance(self.metadata.get("shot_packages"), list) else []
        set_packages = self.metadata.get("set_packages") if isinstance(self.metadata.get("set_packages"), list) else []
        if (
            not records
            and not render_templates
            and not light_templates
            and not action_clips
            and not pose_templates
            and not animation_templates
            and not material_templates
            and not material_applications
            and not camera_motions
            and not camera_templates
            and not object_templates
            and not object_motions
            and not actors
            and not scene_presets
            and not shot_packages
            and not set_packages
        ):
            self.action_list.addItem("暂无场景/动作/机位记录")
            return
        for actor in actors:
            if not isinstance(actor, dict):
                continue
            name = str(actor.get("name") or actor.get("id") or "演员位")
            role = str(actor.get("role") or "").strip()
            note = str(actor.get("note") or "").strip()
            saved_at = str(actor.get("saved_at") or "").strip()
            object_count = actor.get("object_count")
            object_names = actor.get("object_names") if isinstance(actor.get("object_names"), list) else []
            if not object_names:
                objects = actor.get("objects") if isinstance(actor.get("objects"), list) else []
                object_names = [
                    str(item.get("name") or "").strip()
                    for item in objects
                    if isinstance(item, dict) and str(item.get("name") or "").strip()
                ]
            object_label = "、".join(str(item).strip() for item in object_names[:4] if str(item).strip())
            if len(object_names) > 4:
                object_label += f" 等 {len(object_names)} 个"
            actions = actor.get("actions") if isinstance(actor.get("actions"), list) else []
            action_label = "、".join(str(item).strip() for item in actions[:4] if str(item).strip())
            if len(actions) > 4:
                action_label += f" 等 {len(actions)} 个"
            details = []
            if role:
                details.append(role)
            if object_count not in (None, ""):
                details.append(f"对象 {object_count} 个")
            elif object_names:
                details.append(f"对象 {len(object_names)} 个")
            if object_label:
                details.append(object_label)
            if action_label:
                details.append(f"动作：{action_label}")
            if note:
                details.append(note)
            if saved_at:
                details.append(saved_at)
            item = QListWidgetItem("演员位｜" + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(actor, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for preset in scene_presets:
            if not isinstance(preset, dict):
                continue
            name = str(preset.get("name") or preset.get("id") or "场景预设")
            note = str(preset.get("note") or "").strip()
            saved_at = str(preset.get("saved_at") or "").strip()
            output_label = str(preset.get("output_label") or preset.get("output_type") or "").strip()
            frame_start = preset.get("frame_start")
            frame_end = preset.get("frame_end")
            objects = preset.get("objects") if isinstance(preset.get("objects"), list) else []
            camera = preset.get("camera") if isinstance(preset.get("camera"), dict) else {}
            camera_name = str(camera.get("name") or "").strip()
            details = []
            if output_label:
                details.append(output_label)
            if objects:
                details.append(f"对象 {len(objects)} 个")
            if camera_name:
                details.append(f"相机：{camera_name}")
            if frame_start is not None and frame_end is not None:
                details.append(f"帧：{frame_start}-{frame_end}")
            if note:
                details.append(note)
            if saved_at:
                details.append(saved_at)
            item = QListWidgetItem("场景预设｜" + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(preset, ensure_ascii=False, indent=2))
            preset_path = self._preset_file_path(preset)
            if preset_path:
                item.setData(Qt.UserRole, preset_path)
            self.action_list.addItem(item)
        for package in shot_packages:
            if not isinstance(package, dict):
                continue
            name = str(package.get("name") or package.get("id") or "镜头包")
            note = str(package.get("note") or "").strip()
            saved_at = str(package.get("saved_at") or "").strip()
            shots = package.get("shots") if isinstance(package.get("shots"), list) else []
            shot_names = [
                str(item.get("name") or item.get("id") or "").strip()
                for item in shots
                if isinstance(item, dict) and str(item.get("name") or item.get("id") or "").strip()
            ]
            shot_label = "、".join(shot_names[:4])
            if len(shot_names) > 4:
                shot_label += f" 等 {len(shot_names)} 个"
            details = []
            if shots:
                details.append(f"镜头 {len(shots)} 个")
            if shot_label:
                details.append(shot_label)
            if note:
                details.append(note)
            if saved_at:
                details.append(saved_at)
            item = QListWidgetItem("镜头包｜" + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(package, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for package in set_packages:
            if not isinstance(package, dict):
                continue
            name = str(package.get("name") or package.get("id") or "布景包")
            note = str(package.get("note") or "").strip()
            saved_at = str(package.get("saved_at") or "").strip()
            object_count = package.get("object_count")
            collection_count = package.get("collection_count")
            object_names = package.get("object_names") if isinstance(package.get("object_names"), list) else []
            if not object_names:
                objects = package.get("objects") if isinstance(package.get("objects"), list) else []
                object_names = [
                    str(item.get("name") or "").strip()
                    for item in objects
                    if isinstance(item, dict) and str(item.get("name") or "").strip()
                ]
            object_label = "、".join(str(name).strip() for name in object_names[:4] if str(name).strip())
            if len(object_names) > 4:
                object_label += f" 等 {len(object_names)} 个"
            details = []
            if object_count not in (None, ""):
                details.append(f"对象 {object_count} 个")
            elif object_names:
                details.append(f"对象 {len(object_names)} 个")
            if collection_count not in (None, ""):
                details.append(f"集合 {collection_count} 个")
            collections = package.get("collections") if isinstance(package.get("collections"), list) else []
            collection_label = "、".join(str(item).strip() for item in collections[:3] if str(item).strip())
            if len(collections) > 3:
                collection_label += f" 等 {len(collections)} 个"
            if object_label:
                details.append(object_label)
            if collection_label:
                details.append(collection_label)
            if note:
                details.append(note)
            if saved_at:
                details.append(saved_at)
            item = QListWidgetItem("布景包｜" + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(package, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for template in render_templates:
            if not isinstance(template, dict):
                continue
            name = str(template.get("name") or template.get("id") or "渲染模板")
            note = str(template.get("note") or "").strip()
            saved_at = str(template.get("saved_at") or "").strip()
            output_label = str(template.get("output_label") or template.get("output_type") or "").strip()
            width = template.get("resolution_x")
            height = template.get("resolution_y")
            fps = template.get("fps")
            frame_start = template.get("frame_start")
            frame_end = template.get("frame_end")
            engine = str(template.get("engine") or "").strip()
            details = []
            if output_label:
                details.append(output_label)
            if width and height:
                details.append(f"{width}x{height}")
            if fps:
                details.append(f"{fps}fps")
            if frame_start is not None and frame_end is not None:
                details.append(f"帧：{frame_start}-{frame_end}")
            if engine:
                details.append(engine)
            if note:
                details.append(note)
            if saved_at:
                details.append(saved_at)
            item = QListWidgetItem("渲染模板｜" + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(template, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for template in light_templates:
            if not isinstance(template, dict):
                continue
            name = str(template.get("name") or template.get("id") or "灯光模板")
            note = str(template.get("note") or "").strip()
            saved_at = str(template.get("saved_at") or "").strip()
            lights = template.get("lights") if isinstance(template.get("lights"), list) else []
            light_names = [
                str(item.get("name") or "").strip()
                for item in lights
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ]
            light_label = "、".join(light_names[:4])
            if len(light_names) > 4:
                light_label += f" 等 {len(light_names)} 盏"
            details = []
            if lights:
                details.append(f"灯光 {len(lights)} 盏")
            if light_label:
                details.append(light_label)
            if note:
                details.append(note)
            if saved_at:
                details.append(saved_at)
            item = QListWidgetItem("灯光模板｜" + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(template, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for template in camera_templates:
            if not isinstance(template, dict):
                continue
            name = str(template.get("name") or template.get("id") or "机位模板")
            note = str(template.get("note") or "").strip()
            saved_at = str(template.get("saved_at") or "").strip()
            camera = template.get("camera") if isinstance(template.get("camera"), dict) else {}
            camera_name = str(camera.get("name") or "").strip()
            lens = camera.get("lens")
            details = []
            if camera_name:
                details.append(f"相机：{camera_name}")
            if lens not in (None, ""):
                details.append(f"焦距：{lens}")
            if note:
                details.append(note)
            if saved_at:
                details.append(saved_at)
            item = QListWidgetItem("机位模板｜" + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(template, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for template in object_templates:
            if not isinstance(template, dict):
                continue
            name = str(template.get("name") or template.get("id") or "站位模板")
            note = str(template.get("note") or "").strip()
            saved_at = str(template.get("saved_at") or "").strip()
            objects = template.get("objects") if isinstance(template.get("objects"), list) else []
            object_names = [
                str(item.get("name") or "").strip()
                for item in objects
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ]
            object_label = "、".join(object_names[:4])
            if len(object_names) > 4:
                object_label += f" 等 {len(object_names)} 个"
            details = []
            if objects:
                details.append(f"对象 {len(objects)} 个")
            if object_label:
                details.append(object_label)
            if note:
                details.append(note)
            if saved_at:
                details.append(saved_at)
            item = QListWidgetItem("站位模板｜" + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(template, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for clip in action_clips:
            if not isinstance(clip, dict):
                continue
            name = str(clip.get("name") or clip.get("action") or clip.get("id") or "动作片段")
            note = str(clip.get("note") or "").strip()
            saved_at = str(clip.get("saved_at") or "").strip()
            action = str(clip.get("action") or "").strip()
            target_armature = str(clip.get("target_armature") or "").strip()
            source_profile_name = str(clip.get("source_profile_name") or "").strip()
            library_relative_path = str(clip.get("library_relative_path") or "").strip()
            frame_start = clip.get("frame_start")
            frame_end = clip.get("frame_end")
            frame_count = clip.get("frame_count")
            actor_label = self._actor_record_label(clip.get("actor"))
            details = []
            if actor_label:
                details.append(f"演员：{actor_label}")
            if target_armature:
                details.append(f"骨骼：{target_armature}")
            if action:
                details.append(f"动作：{action}")
            if frame_start is not None and frame_end is not None:
                frame_text = f"帧：{frame_start}-{frame_end}"
                if frame_count not in (None, ""):
                    frame_text += f"（{frame_count}帧）"
                details.append(frame_text)
            if source_profile_name:
                details.append("来源：" + source_profile_name)
            if library_relative_path:
                details.append(library_relative_path)
            if note:
                details.append(note)
            if saved_at:
                details.append(saved_at)
            item = QListWidgetItem("动作片段｜" + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(clip, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for template in pose_templates:
            if not isinstance(template, dict):
                continue
            name = str(template.get("name") or template.get("id") or "姿势模板")
            note = str(template.get("note") or "").strip()
            saved_at = str(template.get("saved_at") or "").strip()
            armature = str(template.get("armature") or "").strip()
            action = str(template.get("action") or "").strip()
            bone_count = template.get("bone_count")
            details = []
            if armature:
                details.append(f"骨骼：{armature}")
            if bone_count not in (None, ""):
                details.append(f"骨骼数：{bone_count}")
            if action:
                details.append(f"动作：{action}")
            if note:
                details.append(note)
            if saved_at:
                details.append(saved_at)
            item = QListWidgetItem("姿势模板｜" + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(template, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for template in animation_templates:
            if not isinstance(template, dict):
                continue
            name = str(template.get("name") or template.get("id") or "动画片段")
            note = str(template.get("note") or "").strip()
            saved_at = str(template.get("saved_at") or "").strip()
            objects = template.get("objects") if isinstance(template.get("objects"), list) else []
            object_names = [
                str(item.get("name") or "").strip()
                for item in objects
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ]
            object_label = "、".join(object_names[:4])
            if len(object_names) > 4:
                object_label += f" 等 {len(object_names)} 个"
            object_count = template.get("object_count")
            keyframe_count = template.get("keyframe_count")
            frame_start = template.get("frame_start")
            frame_end = template.get("frame_end")
            details = []
            if object_count not in (None, ""):
                details.append(f"对象 {object_count} 个")
            elif objects:
                details.append(f"对象 {len(objects)} 个")
            if keyframe_count not in (None, ""):
                details.append(f"关键帧 {keyframe_count} 个")
            if frame_start is not None and frame_end is not None:
                details.append(f"帧：{frame_start}-{frame_end}")
            if object_label:
                details.append(object_label)
            if note:
                details.append(note)
            if saved_at:
                details.append(saved_at)
            item = QListWidgetItem("动画片段｜" + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(template, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for template in material_templates:
            if not isinstance(template, dict):
                continue
            name = str(template.get("name") or template.get("id") or "材质模板")
            note = str(template.get("note") or "").strip()
            saved_at = str(template.get("saved_at") or "").strip()
            objects = template.get("objects") if isinstance(template.get("objects"), list) else []
            object_names = [
                str(item.get("name") or "").strip()
                for item in objects
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ]
            object_label = "、".join(object_names[:4])
            if len(object_names) > 4:
                object_label += f" 等 {len(object_names)} 个"
            object_count = template.get("object_count")
            material_count = template.get("material_count")
            materials = template.get("materials") if isinstance(template.get("materials"), list) else []
            material_names = [
                str(item.get("name") or "").strip()
                for item in materials
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ]
            material_label = "、".join(material_names[:4])
            if len(material_names) > 4:
                material_label += f" 等 {len(material_names)} 个"
            details = []
            if object_count not in (None, ""):
                details.append(f"对象 {object_count} 个")
            elif objects:
                details.append(f"对象 {len(objects)} 个")
            if material_count not in (None, ""):
                details.append(f"材质 {material_count} 个")
            elif materials:
                details.append(f"材质 {len(materials)} 个")
            if object_label:
                details.append(object_label)
            if material_label:
                details.append(material_label)
            if note:
                details.append(note)
            if saved_at:
                details.append(saved_at)
            item = QListWidgetItem("材质模板｜" + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(template, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for application in material_applications:
            if not isinstance(application, dict):
                continue
            name = str(application.get("name") or application.get("material_name") or application.get("id") or "材质应用")
            app_type = str(application.get("type") or "").strip()
            material_name = str(application.get("material_name") or "").strip()
            source_profile_name = str(application.get("source_profile_name") or "").strip()
            applied_at = str(application.get("applied_at") or "").strip()
            objects = application.get("objects") if isinstance(application.get("objects"), list) else []
            texture_paths = application.get("texture_paths") if isinstance(application.get("texture_paths"), list) else []
            texture_roles = application.get("texture_roles") if isinstance(application.get("texture_roles"), list) else []
            world = str(application.get("world") or "").strip()
            object_label = "、".join(str(item).strip() for item in objects[:4] if str(item).strip())
            if len(objects) > 4:
                object_label += f" 等 {len(objects)} 个"
            details = []
            if app_type == "hdri":
                details.append("HDRI 环境光")
            elif app_type:
                details.append(app_type)
            if material_name:
                details.append("材质：" + material_name)
            if world:
                details.append("环境：" + world)
            if objects:
                details.append(f"对象 {len(objects)} 个")
            if object_label:
                details.append(object_label)
            if texture_paths:
                details.append(f"贴图 {len(texture_paths)} 张")
            if texture_roles:
                details.append("通道：" + " / ".join(str(item) for item in texture_roles[:6]))
            if source_profile_name:
                details.append("来源：" + source_profile_name)
            if applied_at:
                details.append(applied_at)
            item = QListWidgetItem("材质应用｜" + name + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(application, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for record in records:
            if not isinstance(record, dict):
                continue
            status = self.ACTION_STATUS_LABELS.get(str(record.get("status") or ""), str(record.get("status") or ""))
            target = str(record.get("target") or "未选择骨骼")
            action = str(record.get("action") or "未指定动作")
            actor_label = self._actor_record_label(record.get("actor"))
            clip = record.get("action_clip") if isinstance(record.get("action_clip"), dict) else {}
            clip_name = str(clip.get("name") or clip.get("id") or "").strip()
            message = str(record.get("message") or "").strip()
            applied_at = str(record.get("applied_at") or "").strip()
            label = f"{status}｜{target}\n{action}"
            if actor_label:
                label += f"\n演员：{actor_label}"
            if clip_name:
                label += f"\n片段：{clip_name}"
            if message:
                label += f"\n{message}"
            if applied_at:
                label += f"\n{applied_at}"
            item = QListWidgetItem(label)
            item.setToolTip(json.dumps(record, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for motion in camera_motions:
            if not isinstance(motion, dict):
                continue
            label = str(motion.get("label") or motion.get("motion") or "镜头运动")
            camera = str(motion.get("camera") or "").strip()
            frame_start = motion.get("frame_start")
            frame_end = motion.get("frame_end")
            created_at = str(motion.get("created_at") or "").strip()
            details = []
            if camera:
                details.append(camera)
            if frame_start is not None and frame_end is not None:
                details.append(f"帧：{frame_start}-{frame_end}")
            if created_at:
                details.append(created_at)
            item = QListWidgetItem("镜头运动｜" + label + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(motion, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)
        for motion in object_motions:
            if not isinstance(motion, dict):
                continue
            label = str(motion.get("label") or motion.get("motion") or "角色走位")
            objects = motion.get("objects") if isinstance(motion.get("objects"), list) else []
            object_label = "、".join(str(item) for item in objects[:4] if item)
            if len(objects) > 4:
                object_label += f" 等 {len(objects)} 个"
            actor_label = self._actor_record_label(motion.get("actor"))
            frame_start = motion.get("frame_start")
            frame_end = motion.get("frame_end")
            created_at = str(motion.get("created_at") or "").strip()
            details = []
            if actor_label:
                details.append(f"演员：{actor_label}")
            if object_label:
                details.append(object_label)
            if frame_start is not None and frame_end is not None:
                details.append(f"帧：{frame_start}-{frame_end}")
            if created_at:
                details.append(created_at)
            item = QListWidgetItem("角色走位｜" + label + (("\n" + "\n".join(details)) if details else ""))
            item.setToolTip(json.dumps(motion, ensure_ascii=False, indent=2))
            self.action_list.addItem(item)

    def _load_shots(self):
        shots = self.metadata.get("shots") if isinstance(self.metadata.get("shots"), list) else []
        if not shots:
            self.shot_list.addItem("暂无镜头")
            return
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            name = str(shot.get("name") or shot.get("id") or "未命名镜头")
            shot_id = str(shot.get("id") or "").strip()
            note = str(shot.get("note") or "").strip()
            saved_at = str(shot.get("saved_at") or "").strip()
            output_label = str(shot.get("output_label") or shot.get("output_type") or "").strip()
            shot_status = str(shot.get("shot_status_label") or shot.get("shot_status") or "").strip()
            render_version = shot.get("render_version")
            frame_start = shot.get("frame_start")
            frame_end = shot.get("frame_end")
            assets = shot.get("assets") if isinstance(shot.get("assets"), list) else []
            asset_names = [
                str(item.get("name") or item.get("id") or "").strip()
                for item in assets
                if isinstance(item, dict) and str(item.get("name") or item.get("id") or "").strip()
            ]
            asset_label = "、".join(asset_names[:4])
            if len(asset_names) > 4:
                asset_label += f" 等 {len(asset_names)} 个"
            details = []
            if shot_id:
                details.append(f"ID：{shot_id}")
            if output_label:
                details.append(output_label)
            if shot_status:
                details.append(shot_status)
            if render_version not in (None, ""):
                details.append(f"v{render_version}")
            if asset_label:
                details.append(f"资产：{asset_label}")
            if frame_start is not None and frame_end is not None:
                details.append(f"帧：{frame_start}-{frame_end}")
            if note:
                details.append(note)
            if saved_at:
                details.append(saved_at)
            label = f"{name}" + (("\n" + "\n".join(details)) if details else "")
            item = QListWidgetItem(label)
            item.setToolTip(json.dumps(shot, ensure_ascii=False, indent=2))
            shot_path = self._shot_file_path(shot)
            if shot_path:
                item.setData(Qt.UserRole, shot_path)
            self.shot_list.addItem(item)

    def _load_renders(self):
        renders = self.metadata.get("renders") if isinstance(self.metadata.get("renders"), list) else []
        if not renders:
            self.render_list.addItem("暂无渲染图")
            return
        for render in renders:
            if isinstance(render, dict):
                path = str(render.get("path") or "").strip()
                output_path = str(render.get("output_path") or "").strip()
                shot_name = str(render.get("shot_name") or "").strip()
                shot_id = str(render.get("shot_id") or "").strip()
                created_at = str(render.get("created_at") or "").strip()
                mode = self.RENDER_MODE_LABELS.get(str(render.get("mode") or ""), "")
                output_label = str(render.get("output_label") or render.get("output_type") or "").strip()
                render_version = render.get("render_version")
                layer_paths = render.get("layer_paths") if isinstance(render.get("layer_paths"), dict) else {}
                manifest_path = str(render.get("manifest_path") or "").strip()
            else:
                path = str(render or "").strip()
                output_path = path
                shot_name = ""
                shot_id = ""
                created_at = ""
                mode = ""
                output_label = ""
                render_version = None
                layer_paths = {}
                manifest_path = ""
            name = shot_name or os.path.basename(path) or "未命名渲染"
            details = []
            if shot_id:
                details.append(f"ID：{shot_id}")
            if output_label:
                details.append(output_label)
            if render_version not in (None, ""):
                details.append(f"v{render_version}")
            if layer_paths:
                layer_names = "、".join(str(key) for key in layer_paths.keys() if key)
                if layer_names:
                    details.append(f"素材层：{layer_names}")
            if manifest_path:
                details.append("含素材清单")
            if mode:
                details.append(mode)
            if created_at:
                details.append(created_at)
            item = QListWidgetItem(f"{name}" + (("\n" + "\n".join(details)) if details else ""))
            open_path = output_path or path
            if open_path:
                item.setToolTip(json.dumps(render, ensure_ascii=False, indent=2) if isinstance(render, dict) else open_path)
                item.setData(Qt.UserRole, open_path)
            self.render_list.addItem(item)

    def _selected_path(self, widget):
        item = widget.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "").strip()

    def _safe_director_id(self, text, fallback="shot"):
        text = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(text or ""))
        text = "_".join(part for part in text.split("_") if part)
        return text[:48] or fallback

    def _shot_file_path(self, shot):
        if not isinstance(shot, dict):
            return ""
        shots_dir = str(self.metadata.get("shots_dir") or "").strip()
        if not shots_dir:
            return ""
        shot_key = shot.get("id") or shot.get("name") or "shot"
        return os.path.join(shots_dir, self._safe_director_id(shot_key, "shot") + ".json")

    def _preset_file_path(self, preset):
        if not isinstance(preset, dict):
            return ""
        presets_dir = str(self.metadata.get("presets_dir") or "").strip()
        if not presets_dir:
            return ""
        preset_key = preset.get("id") or preset.get("name") or "preset"
        return os.path.join(presets_dir, self._safe_director_id(preset_key, "preset") + ".json")

    def open_selected_asset(self):
        path = self._selected_path(self.asset_list)
        if path and os.path.exists(path):
            open_local_file(path)

    def open_selected_render(self):
        path = self._selected_path(self.render_list)
        if path and os.path.exists(path):
            if os.path.isfile(path) and path.lower().endswith(self.IMAGE_EXTENSIONS):
                show_image_preview(self, path, "Blender 渲染图")
            else:
                open_local_file(path)

    def open_selected_shot(self):
        path = self._selected_path(self.shot_list)
        if path and os.path.exists(path):
            open_local_file(path)

    def open_selected_action_record(self):
        path = self._selected_path(self.action_list)
        if path and os.path.exists(path):
            open_local_file(path)

    def open_storyboard_manifest(self):
        path = str(self.metadata.get("storyboard_report_path") or "").strip()
        if not path:
            project_dir = str(self.metadata.get("project_dir") or "").strip()
            if project_dir:
                path = os.path.join(project_dir, "storyboard_report.html")
        if not path or not os.path.exists(path):
            path = str(self.metadata.get("storyboard_manifest_path") or "").strip()
        if not path or not os.path.exists(path):
            project_dir = str(self.metadata.get("project_dir") or "").strip()
            if project_dir:
                path = os.path.join(project_dir, "storyboard_manifest.json")
        if path and os.path.exists(path):
            open_local_file(path)

    def open_production_report(self):
        path = str(self.metadata.get("production_report_path") or "").strip()
        if not path:
            project_dir = str(self.metadata.get("project_dir") or "").strip()
            if project_dir:
                path = os.path.join(project_dir, "production_report.html")
        if not path or not os.path.exists(path):
            path = str(self.metadata.get("production_manifest_path") or "").strip()
        if not path or not os.path.exists(path):
            project_dir = str(self.metadata.get("project_dir") or "").strip()
            if project_dir:
                path = os.path.join(project_dir, "production_manifest.json")
        if path and os.path.exists(path):
            open_local_file(path)

    def open_render_queue_report(self):
        try:
            manifest_path = write_blender_director_render_queue_manifest(self.metadata)
            report_path = write_blender_director_render_queue_report(self.metadata)
            csv_path = write_blender_director_render_queue_csv(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成渲染队列失败", str(e))
            return
        if manifest_path:
            self.metadata["render_queue_manifest_path"] = manifest_path
        if report_path:
            self.metadata["render_queue_report_path"] = report_path
        if csv_path:
            self.metadata["render_queue_csv_path"] = csv_path
        path = report_path or manifest_path or csv_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_actor_schedule_report(self):
        try:
            manifest_path = write_blender_director_actor_schedule_manifest(self.metadata)
            report_path = write_blender_director_actor_schedule_report(self.metadata)
            csv_path = write_blender_director_actor_schedule_csv(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成演员调度失败", str(e))
            return
        if manifest_path:
            self.metadata["actor_schedule_manifest_path"] = manifest_path
        if report_path:
            self.metadata["actor_schedule_report_path"] = report_path
        if csv_path:
            self.metadata["actor_schedule_csv_path"] = csv_path
        path = report_path or manifest_path or csv_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_scene_breakdown_report(self):
        try:
            manifest_path = write_blender_director_scene_breakdown_manifest(self.metadata)
            report_path = write_blender_director_scene_breakdown_report(self.metadata)
            csv_path = write_blender_director_scene_breakdown_csv(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成分场表失败", str(e))
            return
        if manifest_path:
            self.metadata["scene_breakdown_manifest_path"] = manifest_path
        if report_path:
            self.metadata["scene_breakdown_report_path"] = report_path
        if csv_path:
            self.metadata["scene_breakdown_csv_path"] = csv_path
        path = report_path or manifest_path or csv_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_call_sheet_report(self):
        try:
            manifest_path = write_blender_director_call_sheet_manifest(self.metadata)
            report_path = write_blender_director_call_sheet_report(self.metadata)
            csv_path = write_blender_director_call_sheet_csv(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成拍摄单失败", str(e))
            return
        if manifest_path:
            self.metadata["call_sheet_manifest_path"] = manifest_path
        if report_path:
            self.metadata["call_sheet_report_path"] = report_path
        if csv_path:
            self.metadata["call_sheet_csv_path"] = csv_path
        path = report_path or manifest_path or csv_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_episode_delivery_report(self):
        try:
            manifest_path = write_blender_director_episode_delivery_manifest(self.metadata)
            report_path = write_blender_director_episode_delivery_report(self.metadata)
            csv_path = write_blender_director_episode_delivery_csv(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成分集交付清单失败", str(e))
            return
        if manifest_path:
            self.metadata["episode_delivery_manifest_path"] = manifest_path
        if report_path:
            self.metadata["episode_delivery_report_path"] = report_path
        if csv_path:
            self.metadata["episode_delivery_csv_path"] = csv_path
        path = report_path or manifest_path or csv_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_episode_delivery_packages(self):
        try:
            data = write_blender_director_episode_delivery_packages(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成分集交付包失败", str(e))
            return
        if data.get("manifest_path"):
            self.metadata["episode_delivery_packages_manifest_path"] = data.get("manifest_path")
        if data.get("report_path"):
            self.metadata["episode_delivery_packages_report_path"] = data.get("report_path")
        if data.get("csv_path"):
            self.metadata["episode_delivery_packages_csv_path"] = data.get("csv_path")
        self.metadata["episode_delivery_packages"] = data.get("packages", [])
        path = data.get("report_path") or data.get("manifest_path") or data.get("csv_path")
        if path and os.path.exists(path):
            open_local_file(path)

    def open_edit_timeline_report(self):
        try:
            manifest_path = write_blender_director_edit_timeline_manifest(self.metadata)
            report_path = write_blender_director_edit_timeline_report(self.metadata)
            csv_path = write_blender_director_edit_timeline_csv(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成剪辑时间线失败", str(e))
            return
        if manifest_path:
            self.metadata["edit_timeline_manifest_path"] = manifest_path
        if report_path:
            self.metadata["edit_timeline_report_path"] = report_path
        if csv_path:
            self.metadata["edit_timeline_csv_path"] = csv_path
        path = report_path or manifest_path or csv_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_render_versions_report(self):
        try:
            manifest_path = write_blender_director_render_versions_manifest(self.metadata)
            report_path = write_blender_director_render_versions_report(self.metadata)
            csv_path = write_blender_director_render_versions_csv(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成镜头版本索引失败", str(e))
            return
        if manifest_path:
            self.metadata["render_versions_manifest_path"] = manifest_path
        if report_path:
            self.metadata["render_versions_report_path"] = report_path
        if csv_path:
            self.metadata["render_versions_csv_path"] = csv_path
        path = report_path or manifest_path or csv_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_batch_render_jobs_report(self):
        try:
            manifest_path = write_blender_director_batch_render_jobs_manifest(self.metadata)
            report_path = write_blender_director_batch_render_jobs_report(self.metadata)
            csv_path = write_blender_director_batch_render_jobs_csv(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成批量渲染任务失败", str(e))
            return
        if manifest_path:
            self.metadata["batch_render_jobs_manifest_path"] = manifest_path
        if report_path:
            self.metadata["batch_render_jobs_report_path"] = report_path
        if csv_path:
            self.metadata["batch_render_jobs_csv_path"] = csv_path
        path = report_path or manifest_path or csv_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_batch_render_command_report(self):
        try:
            data = write_blender_director_batch_render_command(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成后台渲染命令失败", str(e))
            return
        if data.get("script_path"):
            self.metadata["batch_render_script_path"] = data.get("script_path")
        if data.get("command_path"):
            self.metadata["batch_render_command_path"] = data.get("command_path")
        if data.get("report_path"):
            self.metadata["batch_render_command_report_path"] = data.get("report_path")
        path = data.get("report_path") or data.get("command_path") or data.get("script_path")
        if path and os.path.exists(path):
            open_local_file(path)

    def open_edit_decision_list(self):
        try:
            path = write_blender_director_edit_decision_list(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成剪辑 EDL 失败", str(e))
            return
        if path:
            self.metadata["edit_timeline_edl_path"] = path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_final_cut_xml(self):
        try:
            path = write_blender_director_final_cut_xml(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成剪辑 FCPXML 失败", str(e))
            return
        if path:
            self.metadata["edit_timeline_fcpxml_path"] = path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_post_handoff_report(self):
        try:
            manifest_path = write_blender_director_post_handoff_manifest(self.metadata)
            report_path = write_blender_director_post_handoff_report(self.metadata)
            csv_path = write_blender_director_post_handoff_csv(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成后期交接清单失败", str(e))
            return
        if manifest_path:
            self.metadata["post_handoff_manifest_path"] = manifest_path
        if report_path:
            self.metadata["post_handoff_report_path"] = report_path
        if csv_path:
            self.metadata["post_handoff_csv_path"] = csv_path
        path = report_path or manifest_path or csv_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_production_check_report(self):
        try:
            manifest_path = write_blender_director_production_check_manifest(self.metadata)
            report_path = write_blender_director_production_check_report(self.metadata)
            csv_path = write_blender_director_production_check_csv(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成制作问题检查失败", str(e))
            return
        if manifest_path:
            self.metadata["production_check_manifest_path"] = manifest_path
        if report_path:
            self.metadata["production_check_report_path"] = report_path
        if csv_path:
            self.metadata["production_check_csv_path"] = csv_path
        path = report_path or manifest_path or csv_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_continuity_check_report(self):
        try:
            manifest_path = write_blender_director_continuity_check_manifest(self.metadata)
            report_path = write_blender_director_continuity_check_report(self.metadata)
            csv_path = write_blender_director_continuity_check_csv(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成连续性检查失败", str(e))
            return
        if manifest_path:
            self.metadata["continuity_check_manifest_path"] = manifest_path
        if report_path:
            self.metadata["continuity_check_report_path"] = report_path
        if csv_path:
            self.metadata["continuity_check_csv_path"] = csv_path
        path = report_path or manifest_path or csv_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_asset_requirements_report(self):
        try:
            manifest_path = write_blender_director_asset_requirements_manifest(self.metadata)
            report_path = write_blender_director_asset_requirements_report(self.metadata)
            csv_path = write_blender_director_asset_requirements_csv(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成资产需求清单失败", str(e))
            return
        if manifest_path:
            self.metadata["asset_requirements_manifest_path"] = manifest_path
        if report_path:
            self.metadata["asset_requirements_report_path"] = report_path
        if csv_path:
            self.metadata["asset_requirements_csv_path"] = csv_path
        path = report_path or manifest_path or csv_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_action_matches_report(self):
        try:
            manifest_path = write_blender_director_action_matches_manifest(self.metadata)
            report_path = write_blender_director_action_matches_report(self.metadata)
            csv_path = write_blender_director_action_matches_csv(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成动作匹配清单失败", str(e))
            return
        if manifest_path:
            self.metadata["action_matches_manifest_path"] = manifest_path
        if report_path:
            self.metadata["action_matches_report_path"] = report_path
        if csv_path:
            self.metadata["action_matches_csv_path"] = csv_path
        path = report_path or manifest_path or csv_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_project_dashboard(self):
        try:
            path = write_blender_director_project_dashboard(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成工程总览失败", str(e))
            return
        if path:
            self.metadata["project_dashboard_path"] = path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_delivery_package(self):
        try:
            path = write_blender_director_delivery_package(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成交付包失败", str(e))
            return
        if path and os.path.exists(path):
            open_local_file(path)

    def open_delivery_audit(self):
        try:
            audit_path = write_blender_director_delivery_audit(self.metadata)
            report_path = write_blender_director_delivery_audit_report(self.metadata)
        except Exception as e:
            QMessageBox.warning(self, "生成交付检查失败", str(e))
            return
        if audit_path:
            self.metadata["delivery_audit_path"] = audit_path
        if report_path:
            self.metadata["delivery_audit_report_path"] = report_path
        path = report_path or audit_path
        if path and os.path.exists(path):
            open_local_file(path)

    def open_render_folder(self):
        path = str(self.metadata.get("renders_dir") or "").strip()
        if path and os.path.exists(path):
            open_local_file(path)

    def open_asset_folder(self):
        path = str(self.metadata.get("assets_dir") or "").strip()
        if path and os.path.exists(path):
            open_local_file(path)


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
        self.project_folder_button = None
        self.project_folder_proxy = None
        self.asset_folder_button = None
        self.asset_folder_proxy = None
        self.render_folder_button = None
        self.render_folder_proxy = None
        self.storyboard_report_button = None
        self.storyboard_report_proxy = None
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
        if node_type in ("image_to_video", "blender_storyboard", "blender_render"):
            return 430
        if node_type == "blender_director_project":
            return 548
        if node_type in BLENDER_PLAN_NODE_TYPES:
            return 380
        if node_type == "upload_image":
            return 360
        if node_type == "prompt_optimize":
            return 320
        return 300

    def _min_width(self):
        node_type = self.data.get("type")
        if node_type in ("text_to_image", "image_to_image", "image_to_video", "blender_storyboard", "blender_render"):
            return 430
        if node_type == "blender_director_project":
            return 548
        if node_type in BLENDER_PLAN_NODE_TYPES:
            return 360
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
        if node_type in ("blender_storyboard", "blender_render"):
            return 520
        if node_type in BLENDER_PLAN_NODE_TYPES:
            return 300
        if node_type == "upload_image":
            return 450
        if node_type == "prompt_optimize":
            return 320
        return 210

    def _min_body(self):
        node_type = self.data.get("type")
        if node_type in ("text_to_image", "image_to_image", "image_to_video"):
            return 620
        if node_type in ("blender_storyboard", "blender_render"):
            return 500
        if node_type in BLENDER_PLAN_NODE_TYPES:
            return 260
        if node_type == "upload_image":
            return 430
        if node_type == "prompt_optimize":
            return 240
        return 160

    def _has_config_widgets(self):
        return self.data.get("type") in ("text_to_image", "image_to_image", "image_to_video", "prompt_optimize")

    def _has_thumbnail(self):
        return self.data.get("type") in ("upload_image", "text_to_image", "image_to_image", "image_to_video", "blender_storyboard", "blender_render")

    def _has_image_params(self):
        return self.data.get("type") in ("text_to_image", "image_to_image")

    def _has_video_params(self):
        return self.data.get("type") == "image_to_video"

    def _content_label_y(self):
        if self.data.get("type") in ("blender_storyboard", "blender_render"):
            return self.HEADER + 62
        if self._has_image_params() or self._has_video_params():
            return self.HEADER + 190
        return self.HEADER + (72 if self._has_config_widgets() else 12)

    def _editor_y(self):
        if self.data.get("type") in ("blender_storyboard", "blender_render"):
            return self.HEADER + 92
        if self._has_image_params() or self._has_video_params():
            return self.HEADER + 220
        return self.HEADER + (96 if self._has_config_widgets() else 42)

    def _editor_height(self):
        node_type = self.data.get("type")
        if node_type in ("text_to_image", "image_to_image"):
            return 82
        if node_type == "image_to_video":
            return 82
        if node_type in ("blender_storyboard", "blender_render"):
            return 110
        if node_type == "blender_director_project":
            return max(96, self._action_y() - self._editor_y() - 82)
        if node_type in BLENDER_PLAN_NODE_TYPES:
            return max(118, self._action_y() - self._editor_y() - 54)
        if node_type == "upload_image":
            return 54
        if node_type == "prompt_optimize":
            return max(118, self._action_y() - self._editor_y() - 54)
        return self.body - 56

    def _preview_label_y(self):
        if self.data.get("type") == "upload_image":
            return self.HEADER + 126
        if self.data.get("type") in ("blender_storyboard", "blender_render"):
            return self.HEADER + 226
        if self.data.get("type") == "image_to_video":
            return self.HEADER + 318
        return self.HEADER + 318

    def _preview_rect(self):
        bottom = self._action_y() - 18
        if self.data.get("type") == "upload_image":
            top = self.HEADER + 154
            size = min(self.width - 28, max(160, bottom - top))
            return QRectF((self.width - size) / 2, top, size, size)
        if self.data.get("type") in ("blender_storyboard", "blender_render"):
            top = self.HEADER + 254
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
        if node_type not in ("upload_image", "text_to_image", "image_to_image", "image_to_video", "blender_storyboard", "prompt_optimize", "blender_model", "blender_scene", "blender_character", "blender_camera", "blender_render", "blender_director_project"):
            return

        if node_type == "upload_image":
            button_text = "本地图片"
        elif node_type == "image_to_video":
            button_text = "生成视频"
        elif node_type == "blender_storyboard":
            button_text = "渲染分镜"
        elif node_type == "blender_model":
            button_text = "选择模型"
        elif node_type == "blender_scene":
            button_text = "应用场景"
        elif node_type == "blender_character":
            button_text = "应用人物"
        elif node_type == "blender_camera":
            button_text = "应用镜头"
        elif node_type == "blender_render":
            button_text = "渲染参考"
        elif node_type == "blender_director_project":
            button_text = "打开导演台"
        else:
            button_text = "生成"
        self.generate_button = QPushButton(button_text)
        if node_type == "blender_director_project":
            generate_width = 94
        elif node_type in ("upload_image", "image_to_video", "blender_storyboard", "blender_model", "blender_scene", "blender_character", "blender_camera", "blender_render"):
            generate_width = 104
        else:
            generate_width = 70
        self.generate_button.setFixedSize(generate_width, self.ACTION_BUTTON_HEIGHT)
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

        if node_type in ("upload_image", "blender_director_project"):
            self.history_button = QPushButton("同步渲染" if node_type == "blender_director_project" else "历史图片")
            self.history_button.setFixedSize(78 if node_type == "blender_director_project" else 78, self.ACTION_BUTTON_HEIGHT)
            self.history_button.setStyleSheet(button_style)
            self.history_button.clicked.connect(self.pick_history_image)
            self.history_button.setParent(None)
            self.history_proxy = QGraphicsProxyWidget(self)
            self.history_proxy.setWidget(self.history_button)
            self.history_proxy.setZValue(3)

        if node_type == "blender_director_project":
            self.project_folder_button = QPushButton("工程目录")
            self.project_folder_button.setFixedSize(70, self.ACTION_BUTTON_HEIGHT)
            self.project_folder_button.setStyleSheet(button_style)
            self.project_folder_button.clicked.connect(self.open_director_project_folder)
            self.project_folder_button.setParent(None)
            self.project_folder_proxy = QGraphicsProxyWidget(self)
            self.project_folder_proxy.setWidget(self.project_folder_button)
            self.project_folder_proxy.setZValue(3)

            self.asset_folder_button = QPushButton("资产目录")
            self.asset_folder_button.setFixedSize(70, self.ACTION_BUTTON_HEIGHT)
            self.asset_folder_button.setStyleSheet(button_style)
            self.asset_folder_button.clicked.connect(self.open_director_asset_folder)
            self.asset_folder_button.setParent(None)
            self.asset_folder_proxy = QGraphicsProxyWidget(self)
            self.asset_folder_proxy.setWidget(self.asset_folder_button)
            self.asset_folder_proxy.setZValue(3)

            self.render_folder_button = QPushButton("渲染目录")
            self.render_folder_button.setFixedSize(70, self.ACTION_BUTTON_HEIGHT)
            self.render_folder_button.setStyleSheet(button_style)
            self.render_folder_button.clicked.connect(self.open_director_render_folder)
            self.render_folder_button.setParent(None)
            self.render_folder_proxy = QGraphicsProxyWidget(self)
            self.render_folder_proxy.setWidget(self.render_folder_button)
            self.render_folder_proxy.setZValue(3)

            self.storyboard_report_button = QPushButton("分镜表")
            self.storyboard_report_button.setFixedSize(70, self.ACTION_BUTTON_HEIGHT)
            self.storyboard_report_button.setStyleSheet(button_style)
            self.storyboard_report_button.clicked.connect(self.open_director_storyboard_report)
            self.storyboard_report_button.setParent(None)
            self.storyboard_report_proxy = QGraphicsProxyWidget(self)
            self.storyboard_report_proxy.setWidget(self.storyboard_report_button)
            self.storyboard_report_proxy.setZValue(3)

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
            if node_type == "blender_director_project":
                self.generate_proxy.setPos(self.width - 212, action_y)
            else:
                button_w = 180 if node_type == "upload_image" else (104 if node_type in ("image_to_video", "blender_storyboard", "blender_model", "blender_scene", "blender_character", "blender_camera", "blender_render") else 86)
                self.generate_proxy.setPos(self.width - button_w, action_y)
        if self.history_proxy is not None:
            if self.data.get("type") == "blender_director_project":
                self.history_proxy.setPos(self.width - 98, action_y)
            else:
                self.history_proxy.setPos(self.width - 94, action_y)
        if self.data.get("type") == "blender_director_project":
            x = max(14, self.width - 506)
            if self.project_folder_proxy is not None:
                self.project_folder_proxy.setPos(x, action_y)
                x += 78
            if self.asset_folder_proxy is not None:
                self.asset_folder_proxy.setPos(x, action_y)
                x += 78
            if self.render_folder_proxy is not None:
                self.render_folder_proxy.setPos(x, action_y)
                x += 78
            if self.storyboard_report_proxy is not None:
                self.storyboard_report_proxy.setPos(x, action_y)
                x += 78
            if self.generate_proxy is not None:
                self.generate_proxy.setPos(x, action_y)
                x += 102
            if self.history_proxy is not None:
                self.history_proxy.setPos(x, action_y)

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
            self.project_folder_proxy,
            self.asset_folder_proxy,
            self.render_folder_proxy,
            self.storyboard_report_proxy,
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

        if self.data.get("type") == "upload_image":
            content_label = "图片路径"
        elif self.data.get("type") == "image_to_video":
            content_label = "视频结果"
        elif self.data.get("type") == "blender_storyboard":
            content_label = "镜头描述"
        elif self.data.get("type") == "blender_model":
            content_label = "模型路径"
        elif self.data.get("type") == "blender_scene":
            content_label = "场景说明"
        elif self.data.get("type") == "blender_character":
            content_label = "人物/动作"
        elif self.data.get("type") == "blender_camera":
            content_label = "摄影机"
        elif self.data.get("type") == "blender_render":
            content_label = "渲染说明"
        elif self.data.get("type") == "blender_director_project":
            content_label = "工程说明"
        else:
            content_label = "内容"
        painter.drawText(QRectF(14, self._content_label_y(), self.width - 28, 22), Qt.AlignLeft, content_label)

        value_rect = QRectF(14, self._editor_y(), self.width - 28, self._editor_height())
        painter.setPen(QPen(QColor("#343b46"), 1))
        painter.setBrush(QColor("#10151c"))
        painter.drawRoundedRect(value_rect, 6, 6)
        if self.data.get("type") == "prompt_optimize":
            painter.setPen(QColor("#9ca7b4"))
            painter.drawText(value_rect, Qt.AlignCenter, "生成新的提示词")
        if self.data.get("type") == "blender_director_project":
            summary = str(self.data.get("director_project_summary") or "").strip()
            if not summary:
                summary = "未创建工程 · 点击打开导演台后生成"
            summary_rect = QRectF(
                14,
                self._editor_y() + self._editor_height() + 10,
                self.width - 28,
                44,
            )
            painter.setPen(QColor("#8fb6ac"))
            painter.drawText(summary_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, summary)

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
                if self.data.get("type") == "upload_image":
                    placeholder = "选择后显示缩略图"
                elif self.data.get("type") == "blender_storyboard":
                    placeholder = "渲染后显示分镜图"
                elif self.data.get("type") == "blender_render":
                    placeholder = "渲染后显示参考图"
                else:
                    placeholder = "生成后显示缩略图"
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
        if self.project_folder_proxy is not None and self.project_folder_proxy.geometry().contains(event.pos()):
            super().mousePressEvent(event)
            return
        if self.asset_folder_proxy is not None and self.asset_folder_proxy.geometry().contains(event.pos()):
            super().mousePressEvent(event)
            return
        if self.render_folder_proxy is not None and self.render_folder_proxy.geometry().contains(event.pos()):
            super().mousePressEvent(event)
            return
        if self.storyboard_report_proxy is not None and self.storyboard_report_proxy.geometry().contains(event.pos()):
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
        inspect_action = None
        open_project_action = None
        open_asset_action = None
        open_render_action = None
        open_storyboard_action = None
        if self.data.get("type") == "blender_director_project":
            inspect_action = menu.addAction("查看工程清单")
            open_storyboard_action = menu.addAction("打开分镜表")
            open_project_action = menu.addAction("打开工程目录")
            open_asset_action = menu.addAction("打开资产目录")
            open_render_action = menu.addAction("打开渲染目录")
            menu.addSeparator()
        delete_action = menu.addAction("删除节点")
        action = menu.exec(event.screenPos())
        scene = self.scene()
        if not isinstance(scene, WorkflowScene):
            return
        if action == inspect_action:
            scene.show_blender_director_project_dialog(self)
        elif action == open_storyboard_action:
            scene.open_blender_director_storyboard_report(self)
        elif action == open_project_action:
            scene.open_blender_director_project_folder(self)
        elif action == open_asset_action:
            scene.open_blender_director_asset_folder(self)
        elif action == open_render_action:
            scene.open_blender_director_render_folder(self)
        elif action == delete_action:
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
        if not isinstance(scene, WorkflowScene):
            return
        if self.data.get("type") == "blender_director_project":
            scene.sync_blender_director_project_renders(self)
        else:
            scene.pick_history_image(self)

    def open_director_project_folder(self):
        scene = self.scene()
        if isinstance(scene, WorkflowScene):
            scene.open_blender_director_project_folder(self)

    def open_director_asset_folder(self):
        scene = self.scene()
        if isinstance(scene, WorkflowScene):
            scene.open_blender_director_asset_folder(self)

    def open_director_render_folder(self):
        scene = self.scene()
        if isinstance(scene, WorkflowScene):
            scene.open_blender_director_render_folder(self)

    def open_director_storyboard_report(self):
        scene = self.scene()
        if isinstance(scene, WorkflowScene):
            scene.open_blender_director_storyboard_report(self)



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

    def _text_from_node_value(self, node):
        if not isinstance(node, WorkflowNodeItem):
            return ""
        node._sync_value_from_editor()
        text = str(node.data.get("value", "") or "").strip()
        return "" if text in NODE_PLACEHOLDER_TEXTS else text

    def _upstream_texts_for_node(self, node):
        texts = []
        for edge in self.upstream_edges(node, "text"):
            source = edge.source_port.node
            text = self._text_from_node_value(source)
            if text:
                texts.append(text)
        return texts

    def _empty_blender_plan(self):
        return {
            "asset_paths": [],
            "scene_prompt": "",
            "character_prompt": "",
            "camera_prompt": "",
            "render_prompt": "",
            "project_prompt": "",
        }

    def _merge_blender_plan(self, base, extra):
        plan = copy.deepcopy(base or self._empty_blender_plan())
        extra = extra or {}
        seen = set(plan.get("asset_paths", []) or [])
        for path in extra.get("asset_paths", []) or []:
            path = str(path or "").strip()
            if path and path not in seen:
                plan.setdefault("asset_paths", []).append(path)
                seen.add(path)
        for key in ("scene_prompt", "character_prompt", "camera_prompt", "render_prompt", "project_prompt"):
            incoming = str(extra.get(key, "") or "").strip()
            if not incoming:
                continue
            current = str(plan.get(key, "") or "").strip()
            plan[key] = f"{current}\n{incoming}".strip() if current else incoming
        return plan

    def _append_blender_prompt(self, plan, key, parts):
        text = "\n".join(str(part or "").strip() for part in parts if str(part or "").strip()).strip()
        if not text:
            return plan
        return self._merge_blender_plan(plan, {key: text})

    def _parse_model_paths_from_node(self, node):
        paths = []
        for path in node.data.get("model_paths", []) or []:
            path = str(path or "").strip()
            if path:
                paths.append(path)
        text = self._text_from_node_value(node)
        for raw in re_split_model_paths(text):
            path = raw.strip().strip('"').strip("'")
            if path.lower().endswith((".glb", ".gltf", ".fbx", ".obj")):
                paths.append(path)
        result = []
        seen = set()
        for path in paths:
            path = os.path.expanduser(path)
            if path and path not in seen:
                result.append(path)
                seen.add(path)
        return result

    def blender_plan_for_node(self, node, visited=None):
        if not isinstance(node, WorkflowNodeItem):
            return self._empty_blender_plan()
        visited = visited or set()
        node_id = node.data.get("id", "")
        if node_id in visited:
            return self._empty_blender_plan()
        visited.add(node_id)

        plan = self._empty_blender_plan()
        for edge in self.upstream_edges(node, "blender"):
            plan = self._merge_blender_plan(plan, self.blender_plan_for_node(edge.source_port.node, visited))

        node_type = node.data.get("type")
        texts = self._upstream_texts_for_node(node)
        own_text = self._text_from_node_value(node)
        if own_text:
            texts.append(own_text)

        if node_type == "blender_model":
            plan = self._merge_blender_plan(plan, {"asset_paths": self._parse_model_paths_from_node(node)})
        elif node_type == "blender_scene":
            plan = self._append_blender_prompt(plan, "scene_prompt", texts)
        elif node_type == "blender_character":
            plan = self._append_blender_prompt(plan, "character_prompt", texts)
        elif node_type == "blender_camera":
            plan = self._append_blender_prompt(plan, "camera_prompt", texts)
        elif node_type == "blender_render":
            plan = self._append_blender_prompt(plan, "render_prompt", texts)
        elif node_type == "blender_director_project":
            plan = self._append_blender_prompt(plan, "project_prompt", texts)
        return plan

    def upstream_blender_plan(self, node):
        plan = self._empty_blender_plan()
        for edge in self.upstream_edges(node, "blender"):
            plan = self._merge_blender_plan(plan, self.blender_plan_for_node(edge.source_port.node))
        return plan

    def run_node_generation(self, node):
        node_type = node.data.get("type")
        if node_type == "upload_image":
            self.pick_upload_image(node)
        elif node_type in ("text_to_image", "image_to_image"):
            self.run_image_node(node, edit=(node_type == "image_to_image"))
        elif node_type == "image_to_video":
            self.run_video_node(node)
        elif node_type == "blender_storyboard":
            self.run_blender_storyboard_node(node)
        elif node_type == "blender_model":
            self.pick_blender_model(node)
        elif node_type in ("blender_scene", "blender_character", "blender_camera"):
            self.run_blender_plan_node(node)
        elif node_type == "blender_render":
            self.run_blender_render_node(node)
        elif node_type == "blender_director_project":
            self.run_blender_director_project_node(node)
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

    def _select_blender_executable(self):
        blender_cfg = self.config.setdefault("blender", {})
        configured = str(blender_cfg.get("path", "") or "").strip()
        resolved = resolve_blender_executable(configured)
        if resolved:
            if configured != resolved:
                blender_cfg["path"] = resolved
                save_config(self.config)
            return resolved

        parent = self.views()[0].window() if self.views() else None
        issue = blender_detection_issue(configured)
        message = (
            issue
            if issue
            else "没有自动找到 Blender。请选择本机 Blender 可执行文件，Windows 通常是 blender.exe，macOS 可以选择 Blender.app 内的 Contents/MacOS/Blender。"
        )
        QMessageBox.information(
            parent,
            "选择 Blender",
            message,
        )
        path = ""
        if sys.platform == "darwin":
            path = QFileDialog.getExistingDirectory(
                parent,
                "选择 Blender.app 或 Blender 所在文件夹",
                "/Applications" if os.path.exists("/Applications") else "",
            )
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                parent,
                "选择 Blender 可执行文件",
                "/Applications" if os.path.exists("/Applications") else "",
                "Blender (blender.exe Blender);;所有文件 (*)",
            )
        resolved = resolve_blender_executable(path)
        if not resolved:
            issue = blender_detection_issue(path)
            self.notify(issue or "没有找到可用的 Blender 可执行文件。")
            return ""
        blender_cfg["path"] = resolved
        save_config(self.config)
        return resolved

    def pick_blender_model(self, node):
        paths, _ = QFileDialog.getOpenFileNames(
            None,
            "选择 Blender 模型/动作资产",
            "",
            "Blender资产 (*.blend *.glb *.gltf *.fbx *.obj *.bvh);;所有文件 (*)",
        )
        if not paths:
            return
        clean_paths = [path for path in paths if os.path.exists(path)]
        if not clean_paths:
            self.notify("没有找到可用的模型文件。")
            return
        node.data["model_paths"] = clean_paths
        node.data["value"] = "\n".join(clean_paths)
        if node.value_edit is not None:
            node.value_edit.setPlainText(node.data["value"])
        node.data["blender_plan"] = self.blender_plan_for_node(node)
        self.notify(f"已选择 {len(clean_paths)} 个 Blender 模型。")
        self.mark_changed()

    def _refresh_blender_director_project_summary(self, node, metadata=None):
        if not isinstance(node, WorkflowNodeItem):
            return ""
        meta = metadata if isinstance(metadata, dict) else load_blender_director_metadata(node.data.get("director_project"))
        summary = summarize_blender_director_metadata(meta)
        node.data["director_project_summary"] = summary
        node.update()
        return summary

    def _open_blender_director_project_path(self, node, key, missing_message):
        project = node.data.get("director_project") if isinstance(node.data.get("director_project"), dict) else {}
        path = str(project.get(key) or "").strip()
        if not path or not os.path.exists(path):
            self.notify(missing_message)
            return
        if open_local_file(path):
            self.notify("已打开目录。")
        else:
            self.notify("打开目录失败，请先确认目录仍然存在。")

    def open_blender_director_project_folder(self, node):
        self._open_blender_director_project_path(
            node,
            "project_dir",
            "请先打开 Blender 导演台工程，再查看工程目录。",
        )

    def open_blender_director_asset_folder(self, node):
        self._open_blender_director_project_path(
            node,
            "assets_dir",
            "请先打开 Blender 导演台工程，再查看资产目录。",
        )

    def open_blender_director_render_folder(self, node):
        self._open_blender_director_project_path(
            node,
            "renders_dir",
            "请先打开 Blender 导演台工程，再查看渲染目录。",
        )

    def open_blender_director_storyboard_report(self, node):
        project = node.data.get("director_project") if isinstance(node.data.get("director_project"), dict) else {}
        meta = load_blender_director_metadata(project)
        path = ""
        if meta:
            try:
                storyboard_manifest_path = write_blender_director_storyboard_manifest(meta)
                storyboard_report_path = write_blender_director_storyboard_report(meta)
                storyboard_csv_path = write_blender_director_storyboard_csv(meta)
            except Exception as e:
                self.notify(f"生成 Blender 分镜表失败：{e}")
                return
            if storyboard_manifest_path:
                meta["storyboard_manifest_path"] = storyboard_manifest_path
                project["storyboard_manifest_path"] = storyboard_manifest_path
            if storyboard_report_path:
                meta["storyboard_report_path"] = storyboard_report_path
                project["storyboard_report_path"] = storyboard_report_path
            if storyboard_csv_path:
                meta["storyboard_csv_path"] = storyboard_csv_path
                project["storyboard_csv_path"] = storyboard_csv_path
            node.data["director_project"] = project
            self._refresh_blender_director_project_summary(node, meta)
            self.mark_changed()
            path = storyboard_report_path or storyboard_manifest_path
        if not path:
            candidates = [
                project.get("storyboard_report_path"),
                os.path.join(str(project.get("project_dir") or ""), "storyboard_report.html")
                if project.get("project_dir")
                else "",
                project.get("storyboard_manifest_path"),
                os.path.join(str(project.get("project_dir") or ""), "storyboard_manifest.json")
                if project.get("project_dir")
                else "",
            ]
            path = next((str(candidate) for candidate in candidates if candidate and os.path.exists(str(candidate))), "")
        if not path or not os.path.exists(path):
            self.notify("请先打开 Blender 导演台工程，再查看分镜表。")
            return
        if open_local_file(path):
            self.notify("已打开分镜表。")
        else:
            self.notify("打开分镜表失败，请先确认文件仍然存在。")

    def show_blender_director_project_dialog(self, node):
        project = node.data.get("director_project") if isinstance(node.data.get("director_project"), dict) else {}
        meta = load_blender_director_metadata(project)
        if not meta:
            self.notify("请先打开 Blender 导演台工程，再查看工程清单。")
            return
        self._refresh_blender_director_project_summary(node, meta)
        parent = self.views()[0].window() if self.views() else None
        dlg = BlenderDirectorProjectDialog(meta, parent)
        dlg.exec()

    def run_blender_plan_node(self, node):
        plan = self.blender_plan_for_node(node)
        node.data["blender_plan"] = plan
        asset_count = len(plan.get("asset_paths", []) or [])
        self.notify(f"Blender 导演信息已应用，当前模型 {asset_count} 个。")
        self.mark_changed()

    def run_blender_director_project_node(self, node):
        blender_path = self._select_blender_executable()
        if not blender_path:
            return
        plan = self.blender_plan_for_node(node)
        node.data["blender_plan"] = plan
        project_id = str(node.data.get("director_project_id") or "").strip()
        if not project_id:
            project_id = f"workflow_{node.data.get('id') or uuid.uuid4().hex}"
            node.data["director_project_id"] = project_id
        project_text = str(plan.get("project_prompt") or "").strip()
        project_name = project_text.splitlines()[0].strip() if project_text else "AI短剧导演台"
        try:
            project = prepare_blender_director_project(project_id, project_name, plan)
            launch_blender_director_project(blender_path, project)
        except Exception as e:
            self.notify(f"打开 Blender 导演台失败：{e}")
            return
        node.data["director_project"] = project
        self._refresh_blender_director_project_summary(node, load_blender_director_metadata(project))
        node.data["value"] = project_text or node.data.get("value", "")
        if node.value_edit is not None and project_text:
            node.value_edit.setPlainText(project_text)
        self.notify("Blender 导演台工程已打开，可在 Blender 里拖动、摆位、调镜头。")
        self.mark_changed()

    def sync_blender_director_project_renders(self, node):
        project = node.data.get("director_project") if isinstance(node.data.get("director_project"), dict) else {}
        meta_path = str(project.get("meta_path") or "").strip()
        if not meta_path or not os.path.exists(meta_path):
            self.notify("请先打开 Blender 导演台工程，再同步渲染结果。")
            return
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as e:
            self.notify(f"读取 Blender 导演台工程失败：{e}")
            return
        meta.setdefault("meta_path", meta_path)
        storyboard_manifest_path = write_blender_director_storyboard_manifest(meta)
        storyboard_report_path = write_blender_director_storyboard_report(meta)
        storyboard_csv_path = write_blender_director_storyboard_csv(meta)
        render_queue_manifest_path = write_blender_director_render_queue_manifest(meta)
        render_queue_report_path = write_blender_director_render_queue_report(meta)
        render_queue_csv_path = write_blender_director_render_queue_csv(meta)
        batch_render_jobs_manifest_path = write_blender_director_batch_render_jobs_manifest(meta)
        batch_render_jobs_report_path = write_blender_director_batch_render_jobs_report(meta)
        batch_render_jobs_csv_path = write_blender_director_batch_render_jobs_csv(meta)
        batch_render_command = write_blender_director_batch_render_command(meta)
        render_versions_manifest_path = write_blender_director_render_versions_manifest(meta)
        render_versions_report_path = write_blender_director_render_versions_report(meta)
        render_versions_csv_path = write_blender_director_render_versions_csv(meta)
        scene_breakdown_manifest_path = write_blender_director_scene_breakdown_manifest(meta)
        scene_breakdown_report_path = write_blender_director_scene_breakdown_report(meta)
        scene_breakdown_csv_path = write_blender_director_scene_breakdown_csv(meta)
        episode_delivery_manifest_path = write_blender_director_episode_delivery_manifest(meta)
        episode_delivery_report_path = write_blender_director_episode_delivery_report(meta)
        episode_delivery_csv_path = write_blender_director_episode_delivery_csv(meta)
        episode_delivery_packages = write_blender_director_episode_delivery_packages(meta)
        call_sheet_manifest_path = write_blender_director_call_sheet_manifest(meta)
        call_sheet_report_path = write_blender_director_call_sheet_report(meta)
        call_sheet_csv_path = write_blender_director_call_sheet_csv(meta)
        actor_schedule_manifest_path = write_blender_director_actor_schedule_manifest(meta)
        actor_schedule_report_path = write_blender_director_actor_schedule_report(meta)
        actor_schedule_csv_path = write_blender_director_actor_schedule_csv(meta)
        edit_timeline_manifest_path = write_blender_director_edit_timeline_manifest(meta)
        edit_timeline_report_path = write_blender_director_edit_timeline_report(meta)
        edit_timeline_csv_path = write_blender_director_edit_timeline_csv(meta)
        edit_timeline_edl_path = write_blender_director_edit_decision_list(meta)
        edit_timeline_fcpxml_path = write_blender_director_final_cut_xml(meta)
        post_handoff_manifest_path = write_blender_director_post_handoff_manifest(meta)
        post_handoff_report_path = write_blender_director_post_handoff_report(meta)
        post_handoff_csv_path = write_blender_director_post_handoff_csv(meta)
        continuity_check_manifest_path = write_blender_director_continuity_check_manifest(meta)
        continuity_check_report_path = write_blender_director_continuity_check_report(meta)
        continuity_check_csv_path = write_blender_director_continuity_check_csv(meta)
        production_check_manifest_path = write_blender_director_production_check_manifest(meta)
        production_check_report_path = write_blender_director_production_check_report(meta)
        production_check_csv_path = write_blender_director_production_check_csv(meta)
        duration_summary_path = write_blender_director_duration_summary(meta)
        production_manifest_path = write_blender_director_production_manifest(meta)
        production_report_path = write_blender_director_production_report(meta)
        asset_usage_csv_path = write_blender_director_asset_usage_csv(meta)
        asset_requirements_manifest_path = write_blender_director_asset_requirements_manifest(meta)
        asset_requirements_report_path = write_blender_director_asset_requirements_report(meta)
        asset_requirements_csv_path = write_blender_director_asset_requirements_csv(meta)
        action_matches_manifest_path = write_blender_director_action_matches_manifest(meta)
        action_matches_report_path = write_blender_director_action_matches_report(meta)
        action_matches_csv_path = write_blender_director_action_matches_csv(meta)
        project_dashboard_path = write_blender_director_project_dashboard(meta)
        storyboard_entries = build_blender_director_storyboard(meta)
        action_matches = build_blender_director_action_matches(meta)
        storyboard_by_shot = {
            str(entry.get("shot_id") or ""): entry
            for entry in storyboard_entries
            if isinstance(entry, dict) and str(entry.get("shot_id") or "").strip()
        }
        if storyboard_manifest_path:
            meta["storyboard_manifest_path"] = storyboard_manifest_path
            project["storyboard_manifest_path"] = storyboard_manifest_path
        if storyboard_report_path:
            meta["storyboard_report_path"] = storyboard_report_path
            project["storyboard_report_path"] = storyboard_report_path
        if storyboard_csv_path:
            meta["storyboard_csv_path"] = storyboard_csv_path
            project["storyboard_csv_path"] = storyboard_csv_path
        if render_queue_manifest_path:
            meta["render_queue_manifest_path"] = render_queue_manifest_path
            project["render_queue_manifest_path"] = render_queue_manifest_path
        if render_queue_report_path:
            meta["render_queue_report_path"] = render_queue_report_path
            project["render_queue_report_path"] = render_queue_report_path
        if render_queue_csv_path:
            meta["render_queue_csv_path"] = render_queue_csv_path
            project["render_queue_csv_path"] = render_queue_csv_path
        if batch_render_jobs_manifest_path:
            meta["batch_render_jobs_manifest_path"] = batch_render_jobs_manifest_path
            project["batch_render_jobs_manifest_path"] = batch_render_jobs_manifest_path
        if batch_render_jobs_report_path:
            meta["batch_render_jobs_report_path"] = batch_render_jobs_report_path
            project["batch_render_jobs_report_path"] = batch_render_jobs_report_path
        if batch_render_jobs_csv_path:
            meta["batch_render_jobs_csv_path"] = batch_render_jobs_csv_path
            project["batch_render_jobs_csv_path"] = batch_render_jobs_csv_path
        if batch_render_command.get("script_path"):
            meta["batch_render_script_path"] = batch_render_command.get("script_path")
            project["batch_render_script_path"] = batch_render_command.get("script_path")
        if batch_render_command.get("command_path"):
            meta["batch_render_command_path"] = batch_render_command.get("command_path")
            project["batch_render_command_path"] = batch_render_command.get("command_path")
        if batch_render_command.get("report_path"):
            meta["batch_render_command_report_path"] = batch_render_command.get("report_path")
            project["batch_render_command_report_path"] = batch_render_command.get("report_path")
        if render_versions_manifest_path:
            meta["render_versions_manifest_path"] = render_versions_manifest_path
            project["render_versions_manifest_path"] = render_versions_manifest_path
        if render_versions_report_path:
            meta["render_versions_report_path"] = render_versions_report_path
            project["render_versions_report_path"] = render_versions_report_path
        if render_versions_csv_path:
            meta["render_versions_csv_path"] = render_versions_csv_path
            project["render_versions_csv_path"] = render_versions_csv_path
        if scene_breakdown_manifest_path:
            meta["scene_breakdown_manifest_path"] = scene_breakdown_manifest_path
            project["scene_breakdown_manifest_path"] = scene_breakdown_manifest_path
        if scene_breakdown_report_path:
            meta["scene_breakdown_report_path"] = scene_breakdown_report_path
            project["scene_breakdown_report_path"] = scene_breakdown_report_path
        if scene_breakdown_csv_path:
            meta["scene_breakdown_csv_path"] = scene_breakdown_csv_path
            project["scene_breakdown_csv_path"] = scene_breakdown_csv_path
        if episode_delivery_manifest_path:
            meta["episode_delivery_manifest_path"] = episode_delivery_manifest_path
            project["episode_delivery_manifest_path"] = episode_delivery_manifest_path
        if episode_delivery_report_path:
            meta["episode_delivery_report_path"] = episode_delivery_report_path
            project["episode_delivery_report_path"] = episode_delivery_report_path
        if episode_delivery_csv_path:
            meta["episode_delivery_csv_path"] = episode_delivery_csv_path
            project["episode_delivery_csv_path"] = episode_delivery_csv_path
        if episode_delivery_packages.get("manifest_path"):
            meta["episode_delivery_packages_manifest_path"] = episode_delivery_packages.get("manifest_path")
            project["episode_delivery_packages_manifest_path"] = episode_delivery_packages.get("manifest_path")
        if episode_delivery_packages.get("report_path"):
            meta["episode_delivery_packages_report_path"] = episode_delivery_packages.get("report_path")
            project["episode_delivery_packages_report_path"] = episode_delivery_packages.get("report_path")
        if episode_delivery_packages.get("csv_path"):
            meta["episode_delivery_packages_csv_path"] = episode_delivery_packages.get("csv_path")
            project["episode_delivery_packages_csv_path"] = episode_delivery_packages.get("csv_path")
        if episode_delivery_packages.get("packages") is not None:
            meta["episode_delivery_packages"] = episode_delivery_packages.get("packages")
            project["episode_delivery_packages"] = episode_delivery_packages.get("packages")
        if call_sheet_manifest_path:
            meta["call_sheet_manifest_path"] = call_sheet_manifest_path
            project["call_sheet_manifest_path"] = call_sheet_manifest_path
        if call_sheet_report_path:
            meta["call_sheet_report_path"] = call_sheet_report_path
            project["call_sheet_report_path"] = call_sheet_report_path
        if call_sheet_csv_path:
            meta["call_sheet_csv_path"] = call_sheet_csv_path
            project["call_sheet_csv_path"] = call_sheet_csv_path
        if actor_schedule_manifest_path:
            meta["actor_schedule_manifest_path"] = actor_schedule_manifest_path
            project["actor_schedule_manifest_path"] = actor_schedule_manifest_path
        if actor_schedule_report_path:
            meta["actor_schedule_report_path"] = actor_schedule_report_path
            project["actor_schedule_report_path"] = actor_schedule_report_path
        if actor_schedule_csv_path:
            meta["actor_schedule_csv_path"] = actor_schedule_csv_path
            project["actor_schedule_csv_path"] = actor_schedule_csv_path
        if edit_timeline_manifest_path:
            meta["edit_timeline_manifest_path"] = edit_timeline_manifest_path
            project["edit_timeline_manifest_path"] = edit_timeline_manifest_path
        if edit_timeline_report_path:
            meta["edit_timeline_report_path"] = edit_timeline_report_path
            project["edit_timeline_report_path"] = edit_timeline_report_path
        if edit_timeline_csv_path:
            meta["edit_timeline_csv_path"] = edit_timeline_csv_path
            project["edit_timeline_csv_path"] = edit_timeline_csv_path
        if edit_timeline_edl_path:
            meta["edit_timeline_edl_path"] = edit_timeline_edl_path
            project["edit_timeline_edl_path"] = edit_timeline_edl_path
        if edit_timeline_fcpxml_path:
            meta["edit_timeline_fcpxml_path"] = edit_timeline_fcpxml_path
            project["edit_timeline_fcpxml_path"] = edit_timeline_fcpxml_path
        if post_handoff_manifest_path:
            meta["post_handoff_manifest_path"] = post_handoff_manifest_path
            project["post_handoff_manifest_path"] = post_handoff_manifest_path
        if post_handoff_report_path:
            meta["post_handoff_report_path"] = post_handoff_report_path
            project["post_handoff_report_path"] = post_handoff_report_path
        if post_handoff_csv_path:
            meta["post_handoff_csv_path"] = post_handoff_csv_path
            project["post_handoff_csv_path"] = post_handoff_csv_path
        if continuity_check_manifest_path:
            meta["continuity_check_manifest_path"] = continuity_check_manifest_path
            project["continuity_check_manifest_path"] = continuity_check_manifest_path
        if continuity_check_report_path:
            meta["continuity_check_report_path"] = continuity_check_report_path
            project["continuity_check_report_path"] = continuity_check_report_path
        if continuity_check_csv_path:
            meta["continuity_check_csv_path"] = continuity_check_csv_path
            project["continuity_check_csv_path"] = continuity_check_csv_path
        if production_check_manifest_path:
            meta["production_check_manifest_path"] = production_check_manifest_path
            project["production_check_manifest_path"] = production_check_manifest_path
        if production_check_report_path:
            meta["production_check_report_path"] = production_check_report_path
            project["production_check_report_path"] = production_check_report_path
        if production_check_csv_path:
            meta["production_check_csv_path"] = production_check_csv_path
            project["production_check_csv_path"] = production_check_csv_path
        if duration_summary_path:
            meta["duration_summary_path"] = duration_summary_path
            project["duration_summary_path"] = duration_summary_path
        if production_manifest_path:
            meta["production_manifest_path"] = production_manifest_path
            project["production_manifest_path"] = production_manifest_path
        if production_report_path:
            meta["production_report_path"] = production_report_path
            project["production_report_path"] = production_report_path
        if asset_usage_csv_path:
            meta["asset_usage_csv_path"] = asset_usage_csv_path
            project["asset_usage_csv_path"] = asset_usage_csv_path
        if asset_requirements_manifest_path:
            meta["asset_requirements_manifest_path"] = asset_requirements_manifest_path
            project["asset_requirements_manifest_path"] = asset_requirements_manifest_path
        if asset_requirements_report_path:
            meta["asset_requirements_report_path"] = asset_requirements_report_path
            project["asset_requirements_report_path"] = asset_requirements_report_path
        if asset_requirements_csv_path:
            meta["asset_requirements_csv_path"] = asset_requirements_csv_path
            project["asset_requirements_csv_path"] = asset_requirements_csv_path
        if action_matches_manifest_path:
            meta["action_matches_manifest_path"] = action_matches_manifest_path
            project["action_matches_manifest_path"] = action_matches_manifest_path
        if action_matches_report_path:
            meta["action_matches_report_path"] = action_matches_report_path
            project["action_matches_report_path"] = action_matches_report_path
        if action_matches_csv_path:
            meta["action_matches_csv_path"] = action_matches_csv_path
            project["action_matches_csv_path"] = action_matches_csv_path
        if project_dashboard_path:
            meta["project_dashboard_path"] = project_dashboard_path
            project["project_dashboard_path"] = project_dashboard_path
        if production_manifest_path or production_report_path:
            try:
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        if storyboard_manifest_path or storyboard_report_path or storyboard_csv_path or render_queue_manifest_path or render_queue_report_path or render_queue_csv_path or batch_render_jobs_manifest_path or batch_render_jobs_report_path or batch_render_jobs_csv_path or batch_render_command.get("report_path") or render_versions_manifest_path or render_versions_report_path or render_versions_csv_path or scene_breakdown_manifest_path or scene_breakdown_report_path or scene_breakdown_csv_path or episode_delivery_manifest_path or episode_delivery_report_path or episode_delivery_csv_path or episode_delivery_packages.get("report_path") or call_sheet_manifest_path or call_sheet_report_path or call_sheet_csv_path or actor_schedule_manifest_path or actor_schedule_report_path or actor_schedule_csv_path or edit_timeline_manifest_path or edit_timeline_report_path or edit_timeline_csv_path or edit_timeline_edl_path or edit_timeline_fcpxml_path or post_handoff_manifest_path or post_handoff_report_path or post_handoff_csv_path or continuity_check_manifest_path or continuity_check_report_path or continuity_check_csv_path or production_check_manifest_path or production_check_report_path or production_check_csv_path or duration_summary_path or production_manifest_path or production_report_path or asset_usage_csv_path or asset_requirements_manifest_path or asset_requirements_report_path or asset_requirements_csv_path or action_matches_manifest_path or action_matches_report_path or action_matches_csv_path or project_dashboard_path:
            node.data["director_project"] = project
        self._refresh_blender_director_project_summary(node, meta)
        renders = meta.get("renders", [])
        if not isinstance(renders, list):
            renders = []
        image_exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        records = []
        for item in renders:
            path = ""
            record = {}
            if isinstance(item, dict):
                record = dict(item)
                path = item.get("preview_path") or item.get("path") or ""
            elif isinstance(item, str):
                path = item
                record = {"path": item}
            path = str(path or "").strip()
            if path and os.path.exists(path) and os.path.isfile(path) and path.lower().endswith(image_exts):
                record["path"] = path
                records.append(record)
        if not records:
            if storyboard_manifest_path or storyboard_report_path:
                self.notify("分镜表已更新，当前还没有可同步到图片历史的预览图。")
                self.mark_changed()
            else:
                self.notify("当前导演台工程还没有可同步到图片历史的预览图。")
            return
        synced = set(path for path in (node.data.get("director_synced_renders") or []) if isinstance(path, str))
        new_records = [record for record in records if str(record.get("path") or "") not in synced]
        if not new_records:
            if storyboard_manifest_path or storyboard_report_path:
                self.notify("分镜表已更新，没有新的 Blender 预览图需要同步。")
                self.mark_changed()
            else:
                self.notify("没有新的 Blender 预览图需要同步。")
            return
        project_info = {
            "project_id": meta.get("project_id", project.get("project_id", "")),
            "project_name": meta.get("project_name", project.get("project_name", "")),
            "project_dir": meta.get("project_dir", project.get("project_dir", "")),
            "storyboard_manifest_path": storyboard_manifest_path,
            "storyboard_report_path": storyboard_report_path,
            "storyboard_csv_path": storyboard_csv_path,
            "render_queue_manifest_path": render_queue_manifest_path,
            "render_queue_report_path": render_queue_report_path,
            "render_queue_csv_path": render_queue_csv_path,
            "batch_render_jobs_manifest_path": batch_render_jobs_manifest_path,
            "batch_render_jobs_report_path": batch_render_jobs_report_path,
            "batch_render_jobs_csv_path": batch_render_jobs_csv_path,
            "batch_render_script_path": batch_render_command.get("script_path", ""),
            "batch_render_command_path": batch_render_command.get("command_path", ""),
            "batch_render_command_report_path": batch_render_command.get("report_path", ""),
            "render_versions_manifest_path": render_versions_manifest_path,
            "render_versions_report_path": render_versions_report_path,
            "render_versions_csv_path": render_versions_csv_path,
            "scene_breakdown_manifest_path": scene_breakdown_manifest_path,
            "scene_breakdown_report_path": scene_breakdown_report_path,
            "scene_breakdown_csv_path": scene_breakdown_csv_path,
            "episode_delivery_manifest_path": episode_delivery_manifest_path,
            "episode_delivery_report_path": episode_delivery_report_path,
            "episode_delivery_csv_path": episode_delivery_csv_path,
            "episode_delivery_packages_manifest_path": episode_delivery_packages.get("manifest_path", ""),
            "episode_delivery_packages_report_path": episode_delivery_packages.get("report_path", ""),
            "episode_delivery_packages_csv_path": episode_delivery_packages.get("csv_path", ""),
            "episode_delivery_packages": episode_delivery_packages.get("packages", []),
            "call_sheet_manifest_path": call_sheet_manifest_path,
            "call_sheet_report_path": call_sheet_report_path,
            "call_sheet_csv_path": call_sheet_csv_path,
            "actor_schedule_manifest_path": actor_schedule_manifest_path,
            "actor_schedule_report_path": actor_schedule_report_path,
            "actor_schedule_csv_path": actor_schedule_csv_path,
            "edit_timeline_manifest_path": edit_timeline_manifest_path,
            "edit_timeline_report_path": edit_timeline_report_path,
            "edit_timeline_csv_path": edit_timeline_csv_path,
            "edit_timeline_edl_path": edit_timeline_edl_path,
            "edit_timeline_fcpxml_path": edit_timeline_fcpxml_path,
            "post_handoff_manifest_path": post_handoff_manifest_path,
            "post_handoff_report_path": post_handoff_report_path,
            "post_handoff_csv_path": post_handoff_csv_path,
            "continuity_check_manifest_path": continuity_check_manifest_path,
            "continuity_check_report_path": continuity_check_report_path,
            "continuity_check_csv_path": continuity_check_csv_path,
            "production_check_manifest_path": production_check_manifest_path,
            "production_check_report_path": production_check_report_path,
            "production_check_csv_path": production_check_csv_path,
            "duration_summary_path": duration_summary_path,
            "production_manifest_path": production_manifest_path,
            "production_report_path": production_report_path,
            "asset_usage_csv_path": asset_usage_csv_path,
            "asset_requirements_manifest_path": asset_requirements_manifest_path,
            "asset_requirements_report_path": asset_requirements_report_path,
            "asset_requirements_csv_path": asset_requirements_csv_path,
            "action_matches_manifest_path": action_matches_manifest_path,
            "action_matches_report_path": action_matches_report_path,
            "action_matches_csv_path": action_matches_csv_path,
            "action_matches": action_matches.get("requirements", []),
            "action_match_count": int(action_matches.get("matched_count") or 0),
            "action_match_requirement_count": int(action_matches.get("requirement_count") or 0),
            "action_unmatched_count": int(action_matches.get("unmatched_count") or 0),
            "project_dashboard_path": project_dashboard_path,
            "storyboard_count": len(storyboard_entries),
            "shots": meta.get("shots", []) if isinstance(meta.get("shots"), list) else [],
            "actors": meta.get("actors", []) if isinstance(meta.get("actors"), list) else [],
            "assets": meta.get("assets", []) if isinstance(meta.get("assets"), list) else [],
            "shot_packages": meta.get("shot_packages", []) if isinstance(meta.get("shot_packages"), list) else [],
            "set_packages": meta.get("set_packages", []) if isinstance(meta.get("set_packages"), list) else [],
            "asset_count": len(meta.get("assets", [])) if isinstance(meta.get("assets"), list) else 0,
            "render_templates": meta.get("render_templates", []) if isinstance(meta.get("render_templates"), list) else [],
            "light_templates": meta.get("light_templates", []) if isinstance(meta.get("light_templates"), list) else [],
            "action_clips": meta.get("action_clips", []) if isinstance(meta.get("action_clips"), list) else [],
            "retarget_profiles": meta.get("retarget_profiles", []) if isinstance(meta.get("retarget_profiles"), list) else [],
            "retarget_applications": meta.get("retarget_applications", []) if isinstance(meta.get("retarget_applications"), list) else [],
            "pose_templates": meta.get("pose_templates", []) if isinstance(meta.get("pose_templates"), list) else [],
            "animation_templates": meta.get("animation_templates", []) if isinstance(meta.get("animation_templates"), list) else [],
            "material_templates": meta.get("material_templates", []) if isinstance(meta.get("material_templates"), list) else [],
            "material_applications": meta.get("material_applications", []) if isinstance(meta.get("material_applications"), list) else [],
            "camera_motions": meta.get("camera_motions", []) if isinstance(meta.get("camera_motions"), list) else [],
            "camera_templates": meta.get("camera_templates", []) if isinstance(meta.get("camera_templates"), list) else [],
            "object_templates": meta.get("object_templates", []) if isinstance(meta.get("object_templates"), list) else [],
            "object_motions": meta.get("object_motions", []) if isinstance(meta.get("object_motions"), list) else [],
            "action_applications": meta.get("action_applications", []) if isinstance(meta.get("action_applications"), list) else [],
            "shot_package_count": len(meta.get("shot_packages", [])) if isinstance(meta.get("shot_packages"), list) else 0,
            "set_package_count": len(meta.get("set_packages", [])) if isinstance(meta.get("set_packages"), list) else 0,
            "render_template_count": len(meta.get("render_templates", [])) if isinstance(meta.get("render_templates"), list) else 0,
            "light_template_count": len(meta.get("light_templates", [])) if isinstance(meta.get("light_templates"), list) else 0,
            "action_clip_count": len(meta.get("action_clips", [])) if isinstance(meta.get("action_clips"), list) else 0,
            "retarget_profile_count": len(meta.get("retarget_profiles", [])) if isinstance(meta.get("retarget_profiles"), list) else 0,
            "retarget_application_count": len(meta.get("retarget_applications", [])) if isinstance(meta.get("retarget_applications"), list) else 0,
            "pose_template_count": len(meta.get("pose_templates", [])) if isinstance(meta.get("pose_templates"), list) else 0,
            "animation_template_count": len(meta.get("animation_templates", [])) if isinstance(meta.get("animation_templates"), list) else 0,
            "material_template_count": len(meta.get("material_templates", [])) if isinstance(meta.get("material_templates"), list) else 0,
            "material_application_count": len(meta.get("material_applications", [])) if isinstance(meta.get("material_applications"), list) else 0,
            "camera_motion_count": len(meta.get("camera_motions", [])) if isinstance(meta.get("camera_motions"), list) else 0,
            "camera_template_count": len(meta.get("camera_templates", [])) if isinstance(meta.get("camera_templates"), list) else 0,
            "object_template_count": len(meta.get("object_templates", [])) if isinstance(meta.get("object_templates"), list) else 0,
            "action_record_count": len(meta.get("action_applications", [])) if isinstance(meta.get("action_applications"), list) else 0,
            "object_motion_count": len(meta.get("object_motions", [])) if isinstance(meta.get("object_motions"), list) else 0,
            "actor_count": len(meta.get("actors", [])) if isinstance(meta.get("actors"), list) else 0,
            "summary": summarize_blender_director_metadata(meta),
        }
        plan = meta.get("plan") if isinstance(meta.get("plan"), dict) else {}
        for record in new_records:
            path = str(record.get("path") or "")
            shot_id = str(record.get("shot_id") or "").strip()
            shot_name = str(record.get("shot_name") or "").strip()
            shot_note = str(record.get("shot_note") or "").strip()
            output_label = str(record.get("output_label") or record.get("output_type") or "").strip()
            storyboard_entry = storyboard_by_shot.get(shot_id, {})
            prompt_parts = [
                str(meta.get("project_name") or "").strip(),
                str(plan.get("scene_prompt") or "").strip(),
                str(plan.get("camera_prompt") or "").strip(),
                f"镜头：{shot_name}" if shot_name else "",
                f"输出：{output_label}" if output_label else "",
                f"备注：{shot_note}" if shot_note else "",
            ]
            result = {
                "images": [path],
                "refs": [],
                "prompt": "\n".join(part for part in prompt_parts if part),
                "model": "Blender 导演台",
                "created_at": now_str(),
                "source": "blender_director_project",
                "blender_render": record,
                "blender_project": project_info,
                "blender_storyboard_entry": storyboard_entry,
            }
            self.sync_image_result_to_history(result)
        new_paths = [str(record.get("path") or "") for record in new_records]
        node.data["director_synced_renders"] = sorted(synced.union(new_paths))
        if new_paths:
            node.data["image_path"] = new_paths[-1]
            node.set_thumbnail(new_paths[-1])
        self.notify(f"已同步 {len(new_paths)} 张 Blender 预览图到图片历史。")
        self.mark_changed()

    def run_blender_render_node(self, node):
        blender_path = self._select_blender_executable()
        if not blender_path:
            return
        plan = self.upstream_blender_plan(node)
        plan = self._append_blender_prompt(plan, "render_prompt", self._upstream_texts_for_node(node) + [self._text_from_node_value(node)])
        node.data["blender_plan"] = plan

        blender_cfg = self.config.setdefault("blender", {})
        try:
            width = int(node.data.get("blender_width") or blender_cfg.get("width") or 1280)
            height = int(node.data.get("blender_height") or blender_cfg.get("height") or 720)
        except Exception:
            width, height = 1280, 720
        width = min(4096, max(320, width))
        height = min(4096, max(320, height))

        self.notify("正在渲染 Blender 导演台参考图...")
        worker = BlenderDirectorWorker(blender_path, plan, width, height)
        node_id = node.data["id"]
        self.workers[node_id] = worker
        worker.progress.connect(self.notify)
        worker.result_ready.connect(lambda result, nid=node_id: self.on_blender_director_finished(nid, result))
        worker.failed.connect(lambda err, nid=node_id: self.on_node_failed(nid, err))
        worker.finished.connect(lambda nid=node_id, w=worker: self._cleanup_worker_for_node(nid, w))
        worker.start()

    def on_blender_director_finished(self, node_id, result):
        node = self._node_by_id(node_id)
        images = result.get("images", []) if isinstance(result, dict) else []
        if not images:
            self.notify("Blender 渲染完成，但没有输出参考图。")
            return
        path = images[0]
        if node is None:
            self.sync_image_result_to_history(result)
            self.notify("Blender 渲染节点已不存在，结果已同步到图片历史。")
            return
        node.data["image_path"] = path
        node.data["blender_plan"] = result.get("blender_plan", node.data.get("blender_plan", {}))
        node.data["value"] = result.get("prompt", node.data.get("value", "")) or node.data.get("value", "")
        if node.value_edit is not None:
            node.value_edit.setPlainText(node.data["value"])
        node.set_thumbnail(path)
        self.sync_image_result_to_history(result)
        self.notify("Blender 导演台参考图已生成。")
        self.mark_changed()

    def run_blender_storyboard_node(self, node):
        prompt = self.upstream_text(node)
        if not prompt:
            self.notify("Blender 分镜节点没有镜头描述。")
            return
        blender_path = self._select_blender_executable()
        if not blender_path:
            return

        blender_cfg = self.config.setdefault("blender", {})
        try:
            width = int(node.data.get("blender_width") or blender_cfg.get("width") or 1280)
            height = int(node.data.get("blender_height") or blender_cfg.get("height") or 720)
        except Exception:
            width, height = 1280, 720
        width = min(4096, max(320, width))
        height = min(4096, max(320, height))

        self.notify("正在渲染 Blender 分镜参考图...")
        worker = BlenderStoryboardWorker(blender_path, prompt, width, height)
        node_id = node.data["id"]
        self.workers[node_id] = worker
        worker.progress.connect(self.notify)
        worker.result_ready.connect(lambda result, nid=node_id: self.on_blender_storyboard_finished(nid, result))
        worker.failed.connect(lambda err, nid=node_id: self.on_node_failed(nid, err))
        worker.finished.connect(lambda nid=node_id, w=worker: self._cleanup_worker_for_node(nid, w))
        worker.start()

    def on_blender_storyboard_finished(self, node_id, result):
        node = self._node_by_id(node_id)
        images = result.get("images", []) if isinstance(result, dict) else []
        if not images:
            self.notify("Blender 渲染完成，但没有输出分镜图片。")
            return
        path = images[0]
        if node is None:
            self.sync_image_result_to_history(result)
            self.notify("Blender 分镜节点已不存在，结果已同步到图片历史。")
            return
        node.data["image_path"] = path
        node.data["value"] = result.get("prompt", node.data.get("value", ""))
        if node.value_edit is not None:
            node.value_edit.setPlainText(node.data["value"])
        node.set_thumbnail(path)
        self.sync_image_result_to_history(result)
        self.notify("Blender 分镜参考图已生成。")
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
        add_blender = menu.addAction("添加Blender分镜节点")
        menu.addSeparator()
        add_blender_model = menu.addAction("添加Blender模型节点")
        add_blender_scene = menu.addAction("添加Blender场景节点")
        add_blender_character = menu.addAction("添加Blender人物节点")
        add_blender_camera = menu.addAction("添加Blender镜头节点")
        add_blender_render = menu.addAction("添加Blender渲染节点")
        add_blender_director_project = menu.addAction("添加Blender导演台工程")
        menu.addSeparator()
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
        elif action == add_blender:
            self.add_node("blender_storyboard", event.scenePos())
        elif action == add_blender_model:
            self.add_node("blender_model", event.scenePos())
        elif action == add_blender_scene:
            self.add_node("blender_scene", event.scenePos())
        elif action == add_blender_character:
            self.add_node("blender_character", event.scenePos())
        elif action == add_blender_camera:
            self.add_node("blender_camera", event.scenePos())
        elif action == add_blender_render:
            self.add_node("blender_render", event.scenePos())
        elif action == add_blender_director_project:
            self.add_node("blender_director_project", event.scenePos())
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
