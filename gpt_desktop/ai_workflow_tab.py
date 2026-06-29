from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics

from .core import HISTORY_DIR, load_json_file, save_json_file
from .native_workflow import WorkflowScene, WorkflowView

WORKFLOW_STATE_FILE = os.path.join(HISTORY_DIR, "ai_workflow_state.json")
WORKFLOW_SAVED_JSON_FILE = os.path.join(HISTORY_DIR, "ai_workflow_saved.json")
WORKFLOW_SAVED_JSON_DIR = os.path.join(HISTORY_DIR, "saved_workflows")


class AIWorkflowTab(QWidget):
    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self._loading_saved_workflow = False
        self._fit_once_done = False
        os.makedirs(WORKFLOW_SAVED_JSON_DIR, exist_ok=True)
        self._build_ui()
        self.load_saved_workflow()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(2000)
        self.autosave_timer.timeout.connect(self._save_workflow_state)
        self.autosave_timer.start()
        self.deferred_save_timer = QTimer(self)
        self.deferred_save_timer.setSingleShot(True)
        self.deferred_save_timer.setInterval(500)
        self.deferred_save_timer.timeout.connect(self._save_workflow_state)
        QTimer.singleShot(0, self.fit_workflow_to_view)
        QTimer.singleShot(250, self.fit_workflow_to_view)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        toolbar = QFrame()
        toolbar.setObjectName("card")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)

        title = QLabel("AI工作流")
        title.setObjectName("section_title")
        row.addWidget(title)

        self.status_label = QLabel("原生画布已就绪。")
        self.status_label.setObjectName("muted")
        row.addWidget(self.status_label, 1)

        save_btn = QPushButton("保存 JSON")
        save_btn.setObjectName("ghost")
        save_btn.clicked.connect(self.save_json_to_preset_file)
        row.addWidget(save_btn)

        open_saved_btn = QPushButton("打开 JSON")
        open_saved_btn.setObjectName("ghost")
        open_saved_btn.clicked.connect(self.open_preset_json_file)
        row.addWidget(open_saved_btn)

        export_btn = QPushButton("导出文件")
        export_btn.setObjectName("ghost")
        export_btn.clicked.connect(self.export_json_file)
        row.addWidget(export_btn)

        import_btn = QPushButton("导入 JSON")
        import_btn.setObjectName("ghost")
        import_btn.clicked.connect(self.import_json_from_box)
        row.addWidget(import_btn)

        clear_btn = QPushButton("清空")
        clear_btn.setObjectName("ghost")
        clear_btn.clicked.connect(self.clear_workflow)
        row.addWidget(clear_btn)

        fit_btn = QPushButton("适配画布")
        fit_btn.setObjectName("ghost")
        fit_btn.clicked.connect(self.fit_workflow_to_view)
        row.addWidget(fit_btn)

        toggle_palette_btn = QPushButton("节点栏")
        toggle_palette_btn.setObjectName("ghost")
        toggle_palette_btn.clicked.connect(self.toggle_palette)
        row.addWidget(toggle_palette_btn)

        root.addWidget(toolbar)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(True)

        self.palette = self._build_palette()
        self.splitter.addWidget(self.palette)

        self._saved_workflow_text = self._read_saved_workflow_text()
        self.scene = WorkflowScene(
            config=self.config,
            status_callback=self.set_status,
            load_defaults=not bool(self._saved_workflow_text),
        )
        self.scene.changed_callback = self.schedule_save
        self.view = WorkflowView(self.scene)
        self.splitter.addWidget(self.view)

        self.saved_panel = self._build_saved_json_panel()
        self.splitter.addWidget(self.saved_panel)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([0, 1080, 0])
        self.palette.hide()
        self.saved_panel.hide()

        root.addWidget(self.splitter, 1)

    def fit_workflow_to_view(self):
        try:
            self.view.fit_nodes()
            self._fit_once_done = True
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.fit_workflow_to_view)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._fit_once_done:
            QTimer.singleShot(0, self.fit_workflow_to_view)

    def _build_palette(self):
        box = QFrame()
        box.setObjectName("card")
        box.setMinimumWidth(130)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("节点列表")
        title.setObjectName("sub_title")
        layout.addWidget(title)

        hint = QLabel("点击添加节点；画布空白处右键也可添加。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        input_btn = QPushButton("提示词输入节点")
        input_btn.setObjectName("ghost")
        input_btn.clicked.connect(lambda: self.add_node("prompt_input"))

        upload_btn = QPushButton("上传图片节点")
        upload_btn.setObjectName("ghost")
        upload_btn.clicked.connect(lambda: self.add_node("upload_image"))

        output_btn = QPushButton("文生图节点")
        output_btn.setObjectName("ghost")
        output_btn.clicked.connect(lambda: self.add_node("text_to_image"))

        image_btn = QPushButton("图生图节点")
        image_btn.setObjectName("ghost")
        image_btn.clicked.connect(lambda: self.add_node("image_to_image"))

        video_btn = QPushButton("图生视频节点")
        video_btn.setObjectName("ghost")
        video_btn.clicked.connect(lambda: self.add_node("image_to_video"))

        prompt_opt_btn = QPushButton("提示词优化节点")
        prompt_opt_btn.setObjectName("ghost")
        prompt_opt_btn.clicked.connect(lambda: self.add_node("prompt_optimize"))
        layout.addWidget(input_btn)
        layout.addWidget(upload_btn)
        layout.addWidget(output_btn)
        layout.addWidget(image_btn)
        layout.addWidget(video_btn)
        layout.addWidget(prompt_opt_btn)

        usage = QLabel("空白处左键拖动画布；滚轮缩放；节点可直接输入；点右侧圆点开始连线；右键可删除节点或连线。")
        usage.setObjectName("hint")
        usage.setWordWrap(True)
        layout.addWidget(usage)
        layout.addStretch()
        return box

    def _build_saved_json_panel(self):
        box = QFrame()
        box.setObjectName("card")
        box.setMinimumWidth(220)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("已保存 JSON")
        title.setObjectName("sub_title")
        layout.addWidget(title)

        hint = QLabel("选择列表项后点击打开；双击也可以打开。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.saved_json_list = QListWidget()
        self.saved_json_list.itemDoubleClicked.connect(self.load_saved_json_item)
        layout.addWidget(self.saved_json_list, 1)

        row = QHBoxLayout()
        open_btn = QPushButton("打开")
        open_btn.setObjectName("ghost")
        open_btn.clicked.connect(self.load_selected_saved_json)
        row.addWidget(open_btn)
        refresh_btn = QPushButton("刷新")
        refresh_btn.setObjectName("ghost")
        refresh_btn.clicked.connect(self.refresh_saved_json_list)
        row.addWidget(refresh_btn)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("ghost")
        close_btn.clicked.connect(self.hide_saved_json_panel)
        row.addWidget(close_btn)
        layout.addLayout(row)
        return box

    def set_status(self, text):
        text = str(text or "")
        self.status_label.setToolTip(text)
        try:
            fm = QFontMetrics(self.status_label.font())
            width = max(220, self.status_label.width() or 420)
            self.status_label.setText(fm.elidedText(text, Qt.ElideRight, width))
        except Exception:
            self.status_label.setText(text[:160] + "..." if len(text) > 160 else text)

    def add_node(self, node_type):
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self.scene.add_node(node_type, center)

    def save_workflow_now(self):
        self._save_workflow_state()
        self.set_status("工作流已保存。")

    def save_json_to_preset_file(self):
        text = self.scene.to_json_text()
        default_name = self._default_workflow_name()
        name, ok = QInputDialog.getText(self, "保存工作流 JSON", "名称：", text=default_name)
        if not ok:
            self.set_status("已取消保存 JSON。")
            return
        name = self._safe_workflow_name(name)
        if not name:
            self.set_status("名称不能为空。")
            return
        path = os.path.join(WORKFLOW_SAVED_JSON_DIR, f"{name}.json")
        if os.path.exists(path):
            reply = QMessageBox.question(
                self,
                "覆盖确认",
                f"已存在“{name}.json”，是否覆盖？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self.set_status("已取消保存 JSON。")
                return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            with open(WORKFLOW_SAVED_JSON_FILE, "w", encoding="utf-8") as f:
                f.write(text)
            self._save_workflow_state()
            self.refresh_saved_json_list()
            self.set_status(f"JSON 已保存：{name}.json")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def open_preset_json_file(self):
        self.saved_panel.show()
        self.refresh_saved_json_list()
        self._set_splitter_sizes(saved=280)
        self.set_status("请选择右侧列表里的 JSON。")

    def refresh_saved_json_list(self):
        if not hasattr(self, "saved_json_list"):
            return
        self.saved_json_list.clear()
        os.makedirs(WORKFLOW_SAVED_JSON_DIR, exist_ok=True)
        files = []
        for name in os.listdir(WORKFLOW_SAVED_JSON_DIR):
            if name.lower().endswith(".json"):
                path = os.path.join(WORKFLOW_SAVED_JSON_DIR, name)
                try:
                    mtime = os.path.getmtime(path)
                except Exception:
                    mtime = 0
                files.append((mtime, name, path))
        files.sort(reverse=True)
        if not files:
            item = QListWidgetItem("还没有保存过 JSON")
            item.setData(Qt.UserRole, "")
            self.saved_json_list.addItem(item)
            return
        for _mtime, name, path in files:
            item = QListWidgetItem(os.path.splitext(name)[0])
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            self.saved_json_list.addItem(item)

    def load_saved_json_item(self, item):
        path = item.data(Qt.UserRole) if item is not None else ""
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if not text:
                self.set_status("选择的 JSON 文件为空。")
                return
            self.scene.load_json_text(text)
            self._save_workflow_state()
            self.fit_workflow_to_view()
            self.set_status(f"已打开 JSON：{os.path.basename(path)}")
        except Exception as e:
            QMessageBox.warning(self, "打开失败", str(e))

    def load_selected_saved_json(self):
        self.load_saved_json_item(self.saved_json_list.currentItem())

    def hide_saved_json_panel(self):
        self.saved_panel.hide()
        self._set_splitter_sizes()

    def _default_workflow_name(self):
        try:
            from datetime import datetime
            return f"工作流_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        except Exception:
            return "工作流"

    def _safe_workflow_name(self, name):
        name = str(name or "").strip()
        for ch in '<>:"/\\|?*':
            name = name.replace(ch, "_")
        return name.strip(" .")

    def export_json_file(self):
        text = self.scene.to_json_text()
        path, _ = QFileDialog.getSaveFileName(self, "导出工作流 JSON", "ai_workflow.json", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.set_status("工作流文件已导出。")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def import_json_from_box(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入工作流 JSON", "", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            QMessageBox.warning(self, "读取失败", str(e))
            return

        try:
            self.scene.load_json_text(text)
            self._save_workflow_state()
            self.fit_workflow_to_view()
            self.set_status(f"已导入 JSON：{os.path.basename(path)}")
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))

    def clear_workflow(self):
        self.scene.clear_workflow()
        self._save_workflow_state()

    def toggle_palette(self):
        self.palette.setVisible(not self.palette.isVisible())
        self._set_splitter_sizes()

    def _set_splitter_sizes(self, saved=None):
        total = max(900, sum(self.splitter.sizes()) or self.width())
        left = 160 if self.palette.isVisible() else 0
        saved_width = saved if saved is not None else (280 if self.saved_panel.isVisible() else 0)
        center = max(420, total - left - saved_width)
        self.splitter.setSizes([left, center, saved_width])

    def _read_saved_workflow_text(self):
        data = load_json_file(WORKFLOW_STATE_FILE, {})
        if not isinstance(data, dict):
            return ""
        text = data.get("workflow_json", "")
        return text.strip() if isinstance(text, str) else ""

    def load_saved_workflow(self):
        text = getattr(self, "_saved_workflow_text", "")
        if not text:
            self.scene.add_default_nodes()
            QTimer.singleShot(0, self.fit_workflow_to_view)
            return
        try:
            self._loading_saved_workflow = True
            self.scene.load_json_text(text)
            self._loading_saved_workflow = False
            self.set_status("已恢复上次工作流。")
            QTimer.singleShot(0, self.fit_workflow_to_view)
        except Exception:
            self._loading_saved_workflow = False
            self.scene.add_default_nodes()
            QTimer.singleShot(0, self.fit_workflow_to_view)

    def schedule_save(self):
        if self._loading_saved_workflow:
            return
        try:
            self.deferred_save_timer.start()
        except Exception:
            pass

    def _save_workflow_state(self):
        save_json_file(WORKFLOW_STATE_FILE, {"workflow_json": self.scene.to_json_text()})

    def closeEvent(self, event):
        try:
            self._save_workflow_state()
        except Exception:
            pass
        super().closeEvent(event)
