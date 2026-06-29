import os
import shutil
import uuid
from collections import deque

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap, QFontMetrics
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QMessageBox,
    QPushButton, QScrollArea, QTextEdit, QLineEdit, QVBoxLayout, QWidget,
)

from .core import (
    VIDEO_HISTORY_FILE,
    clean_error_text,
    get_provider,
    get_save_file_name_cn,
    load_input_drafts,
    load_json_file,
    load_video_thumbnail_pixmap,
    make_clickable,
    now_str,
    open_local_file,
    save_config,
    save_input_drafts,
    save_json_file,
)
from .error_ui import show_generation_error
from .model_bar_mixin import SimpleModelBarMixin
from .workers import VideoWorker
from .widgets import ProviderModelBar, ReferenceDropArea, ThumbnailList, WideComboBox, show_image_preview

class VideoPreviewCard(QFrame):
    def __init__(self, item, parent_tab):
        super().__init__(parent_tab)
        self.item = item if isinstance(item, dict) else {}
        self.parent_tab = parent_tab
        self.video_path = self.item.get("video", "")
        self._meta_text = ""
        self._prompt_text = ""

        self.setObjectName("card")
        self.setFixedWidth(230)
        self.setFixedHeight(290)
        self.setStyleSheet("""
            QFrame#card {
                background-color: #1a1b20;
                border: 1px solid #2a2c33;
                border-radius: 8px;
            }
            QFrame#card:hover {
                border-color: #1f6feb;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        meta = QLabel(self._format_meta_text())
        meta.setObjectName("hint")
        meta.setToolTip(self.video_path)
        meta.setFixedHeight(18)
        meta.setWordWrap(False)
        layout.addWidget(meta)

        self.preview = QLabel()
        make_clickable(self.preview, "点击打开视频")
        self.preview.setFixedSize(210, 124)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("""
            QLabel {
                background-color: #23252d;
                border: 1px solid #25272e;
                border-radius: 6px;
                padding: 0;
                color: #aeb4c2;
            }
        """)
        self.preview.mousePressEvent = lambda _event: self.open_video()
        self._render_preview()
        layout.addWidget(self.preview)

        display_prompt = str(self.item.get("prompt", "") or "").replace("\n", " ").strip()
        prompt = QLabel(self._elide_text(display_prompt, 44))
        prompt.setWordWrap(True)
        prompt.setObjectName("hint")
        prompt.setFixedHeight(28)
        prompt.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        prompt.setToolTip(display_prompt)
        layout.addWidget(prompt)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addStretch()
        open_btn = QPushButton("打开视频")
        open_btn.setObjectName("ghost")
        open_btn.setFixedHeight(28)
        make_clickable(open_btn, "用系统默认应用打开视频")
        open_btn.clicked.connect(self.open_video)
        row.addWidget(open_btn)

        download_btn = QPushButton("下载")
        download_btn.setObjectName("ghost")
        download_btn.setFixedHeight(28)
        make_clickable(download_btn, "保存这个视频到指定位置")
        download_btn.clicked.connect(self.download_video)
        row.addWidget(download_btn)

        delete_btn = QPushButton("删除")
        delete_btn.setObjectName("danger")
        delete_btn.setFixedHeight(28)
        make_clickable(delete_btn, "从历史记录和本地缓存中删除这个视频")
        delete_btn.clicked.connect(self.delete_video)
        row.addWidget(delete_btn)
        layout.addLayout(row)

    def _elide_text(self, text, max_len):
        text = str(text or "").strip()
        if len(text) <= max_len:
            return text
        return text[:max_len - 1] + "..."

    def _format_meta_text(self):
        text = f"{self.item.get('time', '')}  {self.item.get('model', '')}  {self.item.get('width', '')}x{self.item.get('height', '')}"
        fm = QFontMetrics(self.font())
        return fm.elidedText(text, Qt.ElideRight, 210)

    def _render_preview(self):
        if not self.video_path or not os.path.exists(self.video_path):
            self.preview.setText("视频文件不存在")
            return

        pix = load_video_thumbnail_pixmap(self.video_path, 210, 140)
        if not pix.isNull():
            scaled = pix.scaled(210, 124, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            canvas = QPixmap(210, 124)
            canvas.fill(QColor("#23252d"))
            painter = QPainter(canvas)
            try:
                x = int((210 - scaled.width()) / 2)
                y = int((124 - scaled.height()) / 2)
                painter.drawPixmap(x, y, scaled)
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setBrush(QColor(0, 0, 0, 130))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(82, 39, 46, 46)
                painter.setPen(QColor(255, 255, 255, 230))
                font = painter.font()
                font.setPointSize(22)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(86, 39, 46, 46, Qt.AlignCenter, "▶")
            finally:
                painter.end()
            self.preview.setPixmap(canvas)
            return

        name = os.path.basename(self.video_path)
        if len(name) > 28:
            name = name[:12] + "..." + name[-10:]
        self.preview.setText(f"▶\n视频预览\n{name}")

    def open_video(self):
        if not self.video_path or not os.path.exists(self.video_path):
            QMessageBox.warning(self, "提示", "视频文件不存在。")
            return
        if not open_local_file(self.video_path):
            QMessageBox.warning(self, "提示", "打开视频失败。")

    def download_video(self):
        if not self.video_path or not os.path.exists(self.video_path):
            QMessageBox.warning(self, "提示", "视频文件不存在。")
            return

        try:
            cfg = self.parent_tab.config.setdefault("video", {})
            start_dir = cfg.get("last_save_dir", "")
            source_name = os.path.basename(self.video_path) or "video.mp4"
            target = get_save_file_name_cn(
                self,
                "保存视频",
                source_name,
                "MP4 视频 (*.mp4);;所有文件 (*)",
                start_dir=start_dir,
            )
            if not target:
                self.parent_tab.bar.set_status("已取消下载")
                return

            ext = os.path.splitext(source_name)[1]
            if ext and not os.path.splitext(target)[1]:
                target += ext

            if os.path.abspath(target) == os.path.abspath(self.video_path):
                self.parent_tab.bar.set_status("视频已在当前位置")
                return

            shutil.copy2(self.video_path, target)
            cfg["last_save_dir"] = os.path.dirname(target)
            save_config(self.parent_tab.config)
            self.parent_tab.bar.set_status(f"已下载视频：{os.path.basename(target)}")
        except Exception as e:
            QMessageBox.warning(self, "下载失败", str(e))

    def delete_video(self):
        try:
            self.parent_tab.delete_video_item(self.item)
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))



class VideoGeneratorTab(SimpleModelBarMixin, QWidget):
    request_settings = Signal()
    MODEL_CONFIG_SECTION = "video"

    FALLBACK_MODELS = ["agnes-video-v2.0"]
    SIZE_OPTIONS = ["1280x720（横屏）", "720x1280（竖屏）", "1024x1024（方形）"]
    SIZE_MAP = {
        "1280x720（横屏）": (1280, 720),
        "720x1280（竖屏）": (720, 1280),
        "1024x1024（方形）": (1024, 1024),
    }
    FRAME_OPTIONS = ["81", "121", "161", "241", "441"]
    FPS_OPTIONS = ["24", "30"]

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.model_worker = None
        self._pending_model_reload = False
        self.history = []
        self.refs = []
        self.pending_tasks = deque()
        self.running_tasks = {}
        self.task_records = {}
        try:
            self.max_concurrent_tasks = max(1, int(self.config.setdefault("video", {}).get("concurrency", 2)))
        except Exception:
            self.max_concurrent_tasks = 2
        self._task_seq = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        title_row = QHBoxLayout()
        title = QLabel("视频生成")
        title.setObjectName("section_title")
        title_row.addWidget(title)
        title_row.addStretch()
        self.video_settings_btn = QPushButton("设置")
        self.video_settings_btn.setObjectName("ghost")
        self.video_settings_btn.setToolTip("API 厂商管理")
        title_row.addWidget(self.video_settings_btn)
        root.addLayout(title_row)

        self.bar = ProviderModelBar()
        root.addWidget(self.bar)
        self.bar.provider_changed.connect(self.on_provider_changed)
        self.bar.model_changed.connect(self.on_model_changed)
        self.bar.refresh_clicked.connect(self.load_models)
        self.bar.settings_clicked.connect(self.request_settings.emit)
        self.video_settings_btn.clicked.connect(self.request_settings.emit)

        param_card = QFrame()
        param_card.setObjectName("card")
        param_layout = QHBoxLayout(param_card)
        param_layout.setContentsMargins(14, 12, 14, 12)
        param_layout.setSpacing(10)

        def add_param(label_text, widget):
            lbl = QLabel(label_text)
            lbl.setObjectName("field_label")
            param_layout.addWidget(lbl)
            param_layout.addWidget(widget)

        self.mode_combo = WideComboBox()
        self.mode_combo.addItems(["文生视频", "图生视频"])
        self.mode_combo.setMinimumWidth(110)
        add_param("模式", self.mode_combo)

        self.size_combo = WideComboBox()
        self.size_combo.addItems(self.SIZE_OPTIONS)
        self.size_combo.setMinimumWidth(160)
        add_param("画幅", self.size_combo)

        self.frames_combo = WideComboBox()
        self.frames_combo.addItems(self.FRAME_OPTIONS)
        self.frames_combo.setMinimumWidth(90)
        add_param("帧数", self.frames_combo)

        self.fps_combo = WideComboBox()
        self.fps_combo.addItems(self.FPS_OPTIONS)
        self.fps_combo.setMinimumWidth(80)
        add_param("FPS", self.fps_combo)

        param_layout.addStretch()
        root.addWidget(param_card)

        body = QHBoxLayout()
        body.setSpacing(14)

        left_card = QFrame()
        left_card.setObjectName("card")
        left = QVBoxLayout(left_card)
        left.setContentsMargins(14, 14, 14, 14)
        left.setSpacing(10)

        prompt_label = QLabel("视频提示词")
        prompt_label.setObjectName("field_label")
        left.addWidget(prompt_label)

        self.prompt_input = QTextEdit()
        self.prompt_input.setAcceptRichText(False)
        self.prompt_input.setMinimumHeight(180)
        self.prompt_input.setPlaceholderText("描述你想生成的视频画面、镜头运动、主体动作和风格。")
        left.addWidget(self.prompt_input)

        self.ref_label = QLabel("参考图（图生视频必填；可填 URL，也可拖入本地图片）")
        self.ref_label.setObjectName("field_label")
        left.addWidget(self.ref_label)

        self.image_url_input = QLineEdit()
        self.image_url_input.setPlaceholderText("可选：参考图 URL。也可以直接拖入本地图片。")
        left.addWidget(self.image_url_input)

        self.ref_area = ReferenceDropArea()
        left.addWidget(self.ref_area)

        ref_row = QHBoxLayout()
        self.ref_list = ThumbnailList(icon_size=64, max_height=92)
        self.clear_refs_btn = QPushButton("清空")
        self.clear_refs_btn.setObjectName("ghost")
        ref_row.addWidget(self.ref_list, 1)
        ref_row.addWidget(self.clear_refs_btn)
        left.addLayout(ref_row)

        btn_row = QHBoxLayout()
        self.generate_btn = QPushButton("生成视频")
        self.generate_btn.setObjectName("primary")
        self.generate_btn.setMinimumHeight(36)
        self.stop_btn = QPushButton("停止全部")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setMinimumHeight(36)
        btn_row.addWidget(self.generate_btn, 1)
        btn_row.addWidget(self.stop_btn, 1)
        left.addLayout(btn_row)

        right_container = QWidget()
        right = QVBoxLayout(right_container)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        task_card = QFrame()
        task_card.setObjectName("card")
        task_layout = QVBoxLayout(task_card)
        task_layout.setContentsMargins(12, 10, 12, 10)
        task_layout.setSpacing(6)
        task_title = QLabel("任务进度")
        task_title.setObjectName("sub_title")
        task_layout.addWidget(task_title)
        self.task_list = QListWidget()
        self.task_list.setMaximumHeight(150)
        task_layout.addWidget(self.task_list)
        right.addWidget(task_card)

        history_card = QFrame()
        history_card.setObjectName("card")
        history_layout = QVBoxLayout(history_card)
        history_layout.setContentsMargins(12, 10, 12, 12)
        history_layout.setSpacing(8)
        history_title = QLabel("视频历史")
        history_title.setObjectName("sub_title")
        history_layout.addWidget(history_title)
        self.video_scroll = QScrollArea()
        self.video_scroll.setWidgetResizable(True)
        self.video_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self.video_history_widget = QWidget()
        self.video_history_widget.setStyleSheet("background:transparent;")
        self.video_history_layout = QGridLayout(self.video_history_widget)
        self.video_history_layout.setContentsMargins(0, 0, 0, 0)
        self.video_history_layout.setSpacing(12)
        self.video_history_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.video_scroll.setWidget(self.video_history_widget)
        history_layout.addWidget(self.video_scroll, 1)
        right.addWidget(history_card, 1)

        body.addWidget(left_card, 4)
        body.addWidget(right_container, 6)
        root.addLayout(body, 1)

        self.generate_btn.clicked.connect(self.generate)
        self.stop_btn.clicked.connect(self.stop_generation)
        self.mode_combo.currentTextChanged.connect(self.save_video_params)
        self.mode_combo.currentTextChanged.connect(self.on_video_mode_changed)
        self.size_combo.currentTextChanged.connect(self.save_video_params)
        self.frames_combo.currentTextChanged.connect(self.save_video_params)
        self.fps_combo.currentTextChanged.connect(self.save_video_params)
        self.prompt_input.textChanged.connect(self.save_video_draft)
        self.image_url_input.textChanged.connect(self.save_video_draft)
        self.ref_area.files_added.connect(self.add_refs)
        self.clear_refs_btn.clicked.connect(self.clear_refs)
        self.ref_list.preview_requested.connect(
            lambda p: show_image_preview(self, p, "视频参考图预览")
        )
        self.ref_list.item_removed.connect(self._on_ref_removed)

        self.restore_video_params()
        self.restore_video_draft()
        self.on_video_mode_changed(self.mode_combo.currentText())
        self.refresh_providers()
        self.load_persistent_history()
        self.bar.set_status("未刷新模型列表")

    def _set_video_config(self, **values):
        self._set_model_config(**{
            key: str(value) if value is not None else None
            for key, value in values.items()
        })

    def _set_combo_text_if_exists(self, combo, value):
        try:
            idx = combo.findText(str(value))
            if idx >= 0:
                combo.setCurrentIndex(idx)
        except Exception:
            pass

    def restore_video_params(self):
        cfg = self.config.setdefault("video", {})
        self._set_combo_text_if_exists(self.mode_combo, cfg.get("mode", "文生视频"))
        width = cfg.get("width", "1280")
        height = cfg.get("height", "720")
        for label, size in self.SIZE_MAP.items():
            if str(size[0]) == str(width) and str(size[1]) == str(height):
                self._set_combo_text_if_exists(self.size_combo, label)
                break
        self._set_combo_text_if_exists(self.frames_combo, cfg.get("num_frames", "81"))
        self._set_combo_text_if_exists(self.fps_combo, cfg.get("frame_rate", "24"))

    def save_video_params(self, *_args):
        try:
            width, height = self.SIZE_MAP.get(self.size_combo.currentText(), (1280, 720))
            self._set_video_config(
                mode=self.mode_combo.currentText(),
                width=width,
                height=height,
                num_frames=self.frames_combo.currentText(),
                frame_rate=self.fps_combo.currentText(),
            )
            save_config(self.config)
        except Exception:
            pass

    def restore_video_draft(self):
        try:
            data = load_input_drafts()
            text = data.get("video_prompt", "")
            image_url = data.get("video_image_url", "")
            refs = data.get("video_refs", [])
            self.prompt_input.blockSignals(True)
            self.prompt_input.setPlainText(text if isinstance(text, str) else "")
            self.prompt_input.blockSignals(False)
            self.image_url_input.blockSignals(True)
            self.image_url_input.setText(image_url if isinstance(image_url, str) else "")
            self.image_url_input.blockSignals(False)
            if isinstance(refs, list):
                self.refs = [p for p in refs if isinstance(p, str) and os.path.exists(p)]
                self.ref_list.set_paths(self.refs)
        except Exception:
            try:
                self.prompt_input.blockSignals(False)
            except Exception:
                pass
            try:
                self.image_url_input.blockSignals(False)
            except Exception:
                pass

    def save_video_draft(self, *_args):
        try:
            data = load_input_drafts()
            data["video_prompt"] = self.prompt_input.toPlainText()
            data["video_image_url"] = self.image_url_input.text().strip()
            data["video_refs"] = list(self.refs)
            save_input_drafts(data)
        except Exception:
            pass

    def on_video_mode_changed(self, mode):
        is_i2v = str(mode) == "图生视频"
        for widget in (
            self.ref_label,
            self.image_url_input,
            self.ref_area,
            self.ref_list,
            self.clear_refs_btn,
        ):
            try:
                widget.setVisible(is_i2v)
            except Exception:
                pass

    def add_refs(self, files):
        changed = False
        for path in files or []:
            if not isinstance(path, str) or not os.path.exists(path):
                continue
            if path in self.refs:
                continue
            self.refs.append(path)
            self.ref_list.add_path(path)
            changed = True
        if changed:
            self.save_video_draft()

    def clear_refs(self):
        self.refs = []
        self.ref_list.clear()
        self.save_video_draft()

    def _on_ref_removed(self, path):
        self.refs = [p for p in self.refs if p != path]
        self.save_video_draft()

    def add_task_log(self, text):
        try:
            self.task_list.addItem(text)
            while self.task_list.count() > 30:
                self.task_list.takeItem(0)
            self.task_list.scrollToBottom()
        except Exception:
            pass

    def load_persistent_history(self):
        data = load_json_file(VIDEO_HISTORY_FILE, [])
        self.history = data if isinstance(data, list) else []
        changed = False
        for item in self.history:
            if isinstance(item, dict) and "task_id" in item:
                item.pop("task_id", None)
                changed = True
        if changed:
            self.save_persistent_history()
        self.refresh_history_list()

    def save_persistent_history(self):
        self.history = self.history[-200:]
        save_json_file(VIDEO_HISTORY_FILE, self.history)

    def refresh_history_list(self):
        while self.video_history_layout.count():
            layout_item = self.video_history_layout.takeAt(0)
            widget = layout_item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        shown = 0
        for item in reversed(self.history[-20:]):
            if not isinstance(item, dict):
                continue
            path = item.get("video", "")
            try:
                valid = isinstance(path, str) and os.path.exists(path) and os.path.getsize(path) > 0
            except Exception:
                valid = False
            if not valid:
                continue
            row, col = divmod(shown, 3)
            self.video_history_layout.addWidget(VideoPreviewCard(item, self), row, col)
            shown += 1

        if shown <= 0:
            empty = QLabel("暂无视频历史")
            empty.setAlignment(Qt.AlignCenter)
            empty.setObjectName("hint")
            self.video_history_layout.addWidget(empty, 0, 0)

    def generate(self):
        prompt = self.prompt_input.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "提示", "请输入视频提示词。")
            return
        mode = self.mode_combo.currentText()
        image_url = self.image_url_input.text().strip()
        image_refs = []
        if mode == "图生视频":
            if image_url:
                image_refs.append(image_url)
            image_refs.extend(self.refs)
            if not image_refs:
                QMessageBox.warning(self, "提示", "图生视频需要填写参考图 URL，或拖入一张本地图片。")
                return
        provider = get_provider(self.config, self.bar.current_provider_id())
        if not provider:
            QMessageBox.warning(self, "提示", "请先在设置中添加并选择厂商。")
            return
        model = self.bar.current_model()
        if not model:
            QMessageBox.warning(self, "提示", "请选择模型，或点击刷新加载列表。")
            return

        width, height = self.SIZE_MAP.get(self.size_combo.currentText(), (1280, 720))
        self._set_video_config(model=model, mode=mode, width=width, height=height)
        self.save_video_params()
        self.save_video_draft()

        self._task_seq += 1
        task_id = uuid.uuid4().hex
        task = {
            "id": task_id,
            "seq": self._task_seq,
            "prompt": prompt,
            "model": model,
            "width": width,
            "height": height,
            "frames": self.frames_combo.currentText(),
            "fps": self.fps_combo.currentText(),
            "image_refs": list(image_refs),
            "base_url": provider.get("base_url", ""),
            "api_key": provider.get("api_key", ""),
            "proxy_url": provider.get("proxy_url", ""),
            "proxy_mode": provider.get("proxy_mode", "仅下载图片" if provider.get("proxy_url") else "不使用代理"),
            "status": "queued",
        }
        self.task_records[task_id] = task
        self.pending_tasks.append(task)
        self.add_task_log(f"[{now_str()}] #{task['seq']} 已加入队列：{prompt[:30]}")
        self._set_video_generation_running()
        self._update_task_status_bar()
        self._start_queued_video_tasks()

    def _start_queued_video_tasks(self):
        while self.pending_tasks and len(self.running_tasks) < self.max_concurrent_tasks:
            task = self.pending_tasks.popleft()
            self._start_video_task(task)
        self._update_task_status_bar()

    def _start_video_task(self, task):
        task_id = task["id"]
        task["status"] = "running"
        worker = VideoWorker(
            task["base_url"],
            task["api_key"],
            task["model"],
            task["prompt"],
            task["width"],
            task["height"],
            task["frames"],
            task["fps"],
            task["image_refs"],
            task["proxy_url"],
            task["proxy_mode"],
        )
        self.running_tasks[task_id] = worker
        worker.progress.connect(lambda text, tid=task_id: self.on_progress(tid, text))
        worker.result_ready.connect(lambda result, tid=task_id: self.on_finished(tid, result))
        worker.failed.connect(lambda err, tid=task_id: self.on_failed(tid, err))
        worker.finished.connect(lambda *_args, tid=task_id, w=worker: self._cleanup_worker(tid, w))
        self.add_task_log(f"[{now_str()}] #{task['seq']} 开始运行")
        worker.start()

    def _task_label(self, task_id):
        task = self.task_records.get(task_id, {})
        return f"#{task.get('seq', '?')}"

    def _update_task_status_bar(self):
        running = len(self.running_tasks)
        queued = len(self.pending_tasks)
        if running or queued:
            self.bar.set_status(f"视频任务：运行中 {running}/{self.max_concurrent_tasks}，排队 {queued}")
        else:
            self.bar.set_status("视频任务已空闲")
            self._set_video_generation_idle()

    def on_progress(self, task_id, text):
        label = self._task_label(task_id)
        self.bar.set_status(f"{label} {text}")
        self.add_task_log(f"[{now_str()}] {label} {text}")

    def on_finished(self, task_id, result):
        task = self.task_records.get(task_id, {})
        task["status"] = "finished"
        self.add_task_log(f"[{result.get('time', now_str())}] {self._task_label(task_id)} 完成：已保存视频")
        self.history.append(result)
        self.save_persistent_history()
        self.refresh_history_list()

    def on_failed(self, task_id, err):
        task = self.task_records.get(task_id, {})
        task["status"] = "failed"
        err = clean_error_text(err)
        if "任务已中止" in err:
            self.add_task_log(f"[{now_str()}] {self._task_label(task_id)} 视频任务已中止")
            return
        show_generation_error(
            self,
            "视频生成失败",
            err,
            status=f"{self._task_label(task_id)} 视频生成失败",
            log_func=self.add_task_log,
        )

    def stop_generation(self):
        if not self.running_tasks and not self.pending_tasks:
            self.bar.set_status("没有正在运行的视频任务")
            return
        queued = len(self.pending_tasks)
        self.pending_tasks.clear()
        for task in self.task_records.values():
            if task.get("status") == "queued":
                task["status"] = "stopped"
        for worker in list(self.running_tasks.values()):
            try:
                if hasattr(worker, "stop"):
                    worker.stop()
                else:
                    worker.requestInterruption()
            except Exception:
                pass
        self.bar.set_status("正在中止全部视频任务...")
        self.add_task_log(f"[{now_str()}] 已请求中止全部视频任务，取消排队 {queued} 个")

    def _set_video_generation_running(self):
        self.generate_btn.setEnabled(True)
        self.generate_btn.setObjectName("primary")
        self.generate_btn.setText("生成视频")
        self.generate_btn.setToolTip("继续添加一个新视频任务")
        self.generate_btn.style().unpolish(self.generate_btn)
        self.generate_btn.style().polish(self.generate_btn)
        self.generate_btn.update()

    def _set_video_generation_idle(self):
        self.generate_btn.setEnabled(True)
        self.generate_btn.setObjectName("primary")
        self.generate_btn.setText("生成视频")
        self.generate_btn.setToolTip("")
        self.generate_btn.style().unpolish(self.generate_btn)
        self.generate_btn.style().polish(self.generate_btn)
        self.generate_btn.update()

    def delete_video_item(self, item):
        if not isinstance(item, dict):
            return

        path = item.get("video", "")
        ret = QMessageBox.warning(
            self,
            "删除视频",
            "确定要删除这个视频吗？\n\n此操作会从历史记录中移除，并删除本地视频文件，不可恢复。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return

        try:
            target = os.path.abspath(path) if isinstance(path, str) else ""
        except Exception:
            target = str(path or "")

        new_history = []
        for record in self.history:
            if not isinstance(record, dict):
                continue
            record_path = record.get("video", "")
            try:
                same = os.path.abspath(record_path) == target
            except Exception:
                same = record_path == path
            if same:
                continue
            new_history.append(record)

        self.history = new_history
        try:
            if isinstance(path, str) and os.path.exists(path) and os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

        self.save_persistent_history()
        self.refresh_history_list()
        self.bar.set_status("已删除视频")
        self.add_task_log(f"[{now_str()}] 已删除视频")

    def _cleanup_worker(self, task_id, worker):
        def cleanup():
            try:
                if self.running_tasks.get(task_id) is worker:
                    self.running_tasks.pop(task_id, None)
                if worker is not None:
                    worker.deleteLater()
            except Exception:
                pass
            self._start_queued_video_tasks()

        QTimer.singleShot(0, cleanup)

# ============================================================
# 图片历史、智能体输入与主窗口
# ============================================================

# ============================================================
# 主窗口
# ============================================================
