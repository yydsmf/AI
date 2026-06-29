import gc
import hashlib
import json
import os
import shutil
import uuid

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .core import (
    IMAGE_DIR,
    IMAGE_HISTORY_FILE,
    IMAGE_TASK_LOG_FILE,
    REFERENCE_DRAFT_DIR,
    REFERENCE_SNAPSHOT_DIR,
    clean_error_text,
    get_provider,
    load_input_drafts,
    load_json_file,
    make_clickable,
    now_str,
    save_config,
    save_input_drafts,
    save_json_file,
)
from .error_ui import show_generation_error
from .image_history_store import (
    append_image_result,
    clear_history as clear_image_history_store,
    count_images as count_image_history_store,
    init_image_history_store,
    iter_image_items as iter_image_history_items,
    migrate_json_history_once,
    remove_image as remove_image_history_item,
)
from .model_bar_mixin import SimpleModelBarMixin
from .workers import ImageWorker, ThumbnailWorker
from .widgets import (
    ImageCard,
    ProviderModelBar,
    ReferenceDropArea,
    ThumbnailList,
    WideComboBox,
    show_image_preview,
)

class ImageGeneratorTab(SimpleModelBarMixin, QWidget):
    request_settings = Signal()
    MODEL_CONFIG_SECTION = "image"

    SIZE_OPTIONS = [
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
    QUALITY_OPTIONS = ["自动", "低", "中", "高"]
    COUNT_OPTIONS = ["1", "2", "3"]
    UPLOAD_OPTIMIZATION_OPTIONS = ["高质量", "标准", "关闭"]
    FALLBACK_MODELS = ["gpt-image-1", "dall-e-3", "dall-e-2"]
    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    MAX_TASK_LOG_ITEMS = 300
    TASK_LOG_RENDER_ITEMS = 30
    MAX_IMAGE_HISTORY_ITEMS = 300
    GALLERY_PAGE_SIZE = 30

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.refs = []
        self.history = []
        self._restoring_image_draft = False
        self._last_image_mode = ""
        self.worker = None
        self.model_worker = None
        self._pending_model_reload = False
        self.thumbnail_worker = None
        self._thumbnail_pending_paths = set()
        self._gallery_cards = []
        self._gallery_render_limit = self.GALLERY_PAGE_SIZE
        self._gallery_load_more_btn = None
        self._gallery_rebuild_token = 0
        self._gallery_total_count = 0
        self._task_log_save_timer = QTimer(self)
        self._task_log_save_timer.setSingleShot(True)
        self._task_log_save_timer.timeout.connect(self.save_persistent_task_log)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        title_row = QHBoxLayout()
        title = QLabel("GPT 图片生成器")
        title.setObjectName("section_title")
        title_row.addWidget(title)
        title_row.addStretch()

        self.image_settings_btn = QPushButton("设置")
        self.image_settings_btn.setObjectName("ghost")
        self.image_settings_btn.setToolTip("API 厂商管理")
        title_row.addWidget(self.image_settings_btn)

        root.addLayout(title_row)

        # 厂商/模型条
        self.bar = ProviderModelBar()
        root.addWidget(self.bar)
        self.bar.provider_changed.connect(self.on_provider_changed)
        self.bar.model_changed.connect(self.on_model_changed)
        self.bar.refresh_clicked.connect(self.load_models)
        self.bar.settings_clicked.connect(self.request_settings.emit)
        self.image_settings_btn.clicked.connect(self.request_settings.emit)

        # 参数卡
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
        self.mode_combo.addItems(["文生图", "图生图"])
        self.mode_combo.setMinimumWidth(110)
        add_param("模式", self.mode_combo)

        self.size_combo = WideComboBox()
        self.size_combo.addItems(self.SIZE_OPTIONS)
        self.size_combo.setMinimumWidth(170)
        add_param("尺寸", self.size_combo)

        self.count_combo = WideComboBox()
        self.count_combo.addItems(self.COUNT_OPTIONS)
        self.count_combo.setMinimumWidth(80)
        add_param("数量", self.count_combo)

        self.quality_combo = WideComboBox()
        self.quality_combo.addItems(self.QUALITY_OPTIONS)
        self.quality_combo.setMinimumWidth(100)
        add_param("质量", self.quality_combo)

        self.upload_optimization_combo = WideComboBox()
        self.upload_optimization_combo.addItems(self.UPLOAD_OPTIMIZATION_OPTIONS)
        self.upload_optimization_combo.setMinimumWidth(110)
        self.upload_optimization_combo.setToolTip("仅影响图生图参考图上传副本，不修改本地原图")
        add_param("参考图优化", self.upload_optimization_combo)

        # 恢复上次关闭/上次使用时的图片生成参数
        self.restore_image_params()

        param_layout.addStretch()
        root.addWidget(param_card)

        # 主体
        body = QHBoxLayout()
        body.setSpacing(14)

        # 左侧
        left_card = QFrame()
        left_card.setObjectName("card")
        left = QVBoxLayout(left_card)
        left.setContentsMargins(14, 14, 14, 14)
        left.setSpacing(10)

        lbl_prompt = QLabel("提示词")
        lbl_prompt.setObjectName("field_label")
        left.addWidget(lbl_prompt)

        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText("用文字描述你想要的画面，可以加入风格、构图、镜头等细节。")
        self.prompt_input.setMinimumHeight(120)
        self.prompt_input.setAcceptRichText(False)
        self.prompt_input.installEventFilter(self)
        left.addWidget(self.prompt_input)

        lbl_ref = QLabel("参考图（图生图模式必填，双击缩略图预览原图）")
        lbl_ref.setObjectName("field_label")
        left.addWidget(lbl_ref)

        self.ref_area = ReferenceDropArea()
        left.addWidget(self.ref_area)

        ref_row = QHBoxLayout()
        self.ref_list = ThumbnailList(icon_size=64, max_height=92)
        self.clear_refs_btn = QPushButton("清空")
        self.clear_refs_btn.setObjectName("ghost")
        ref_row.addWidget(self.ref_list, 1)
        ref_row.addWidget(self.clear_refs_btn)
        left.addLayout(ref_row)

        action_row = QHBoxLayout()
        self.generate_btn = QPushButton("生成")
        self.generate_btn.setObjectName("primary")
        self.generate_btn.setMinimumHeight(36)
        self.clear_history_btn = QPushButton("清空历史")
        self.clear_history_btn.setObjectName("ghost")
        action_row.addWidget(self.generate_btn, 1)
        action_row.addWidget(self.clear_history_btn)
        left.addLayout(action_row)

        # 右侧
        right_container = QWidget()
        right = QVBoxLayout(right_container)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        task_card = QFrame()
        task_card.setObjectName("card")
        task_layout = QVBoxLayout(task_card)
        task_layout.setContentsMargins(12, 10, 12, 10)
        task_layout.setSpacing(6)
        lbl_task = QLabel("任务进度")
        lbl_task.setObjectName("sub_title")
        task_layout.addWidget(lbl_task)
        self.task_list = QListWidget()
        self.task_list.setMaximumHeight(120)
        task_layout.addWidget(self.task_list)
        right.addWidget(task_card)

        gallery_card = QFrame()
        gallery_card.setObjectName("card")
        gallery_layout_outer = QVBoxLayout(gallery_card)
        gallery_layout_outer.setContentsMargins(12, 10, 12, 12)
        gallery_layout_outer.setSpacing(8)
        lbl_gallery = QLabel("图片预览")
        lbl_gallery.setObjectName("sub_title")
        gallery_layout_outer.addWidget(lbl_gallery)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self.gallery_scroll = scroll
        self.gallery_widget = QWidget()
        self.gallery_widget.setStyleSheet("background:transparent;")
        self.gallery_layout = QGridLayout(self.gallery_widget)
        self.gallery_layout.setSpacing(12)
        self.gallery_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(self.gallery_widget)
        gallery_layout_outer.addWidget(scroll, 1)
        right.addWidget(gallery_card, 1)

        body.addWidget(left_card, 4)
        body.addWidget(right_container, 6)
        root.addLayout(body, 1)

        # 信号
        self.generate_btn.clicked.connect(self.on_generate_clicked)
        self.clear_history_btn.clicked.connect(self.clear_persistent_history)

        # 图片生成参数变化后立即保存，重启程序后自动恢复
        self.mode_combo.currentTextChanged.connect(self.save_image_params)
        self.size_combo.currentTextChanged.connect(self.save_image_params)
        self.count_combo.currentTextChanged.connect(self.save_image_params)
        self.quality_combo.currentTextChanged.connect(self.save_image_params)
        self.upload_optimization_combo.currentTextChanged.connect(self.save_image_params)

        self.ref_area.files_added.connect(self.add_refs)
        self.clear_refs_btn.clicked.connect(self.clear_refs)
        self.ref_list.preview_requested.connect(
            lambda p: show_image_preview(self, p, "参考图预览")
        )
        self.ref_list.item_removed.connect(self._on_ref_removed)

        # 恢复文生图/图生图提示词草稿，以及参考图预览框草稿
        self.restore_image_input_draft()
        self._last_image_mode = self.mode_combo.currentText()
        self.prompt_input.textChanged.connect(self.save_image_input_draft)
        self.mode_combo.currentTextChanged.connect(self.on_image_mode_changed)

        paste_action = QAction("粘贴图片", self)
        paste_action.setShortcut("Ctrl+V")
        paste_action.triggered.connect(self.paste_image_from_clipboard)
        self.addAction(paste_action)

        self.refresh_providers()
        QTimer.singleShot(0, self.load_persistent_history)
        QTimer.singleShot(0, self.load_persistent_task_log)
        self.bar.set_status("未刷新模型列表")


    def eventFilter(self, obj, event):
        """
        图片生成页 Ctrl+V / Command+V 粘贴处理。

        规则：
        - 剪贴板是图片文件路径：优先添加原始图片文件；
        - 剪贴板是截图/纯图片数据：保存为临时参考图；
        - 剪贴板是普通文本：放行，让输入框正常粘贴文本。
        """
        try:
            if obj is self.prompt_input and event.type() == event.Type.KeyPress:
                key = event.key()
                modifiers = event.modifiers()

                if key == Qt.Key_V and (modifiers & Qt.ControlModifier or modifiers & Qt.MetaModifier):
                    cb = QGuiApplication.clipboard()
                    mime = cb.mimeData()

                    # 1. 优先处理文件 URL，避免 macOS 把 Finder 复制的图片当成预览图。
                    image_paths = self._image_paths_from_mime(mime)
                    if image_paths:
                        self.add_refs(image_paths)
                        return True

                    # 2. 没有 URL 时，才处理真正的图片数据，例如截图。
                    if mime.hasImage():
                        self.paste_image_from_clipboard()
                        return True

                    # 3. 普通文本不拦截。
                    return False
        except Exception:
            pass

        return super().eventFilter(obj, event)

    def _image_paths_from_mime(self, mime):
        if not mime or not mime.hasUrls():
            return []
        paths = []
        for url in mime.urls():
            path = url.toLocalFile()
            if path and path.lower().endswith(self.IMAGE_EXTS):
                paths.append(path)
        return paths


    def _set_combo_text_if_exists(self, combo, value):
        """
        安全设置下拉框选中项。
        如果旧配置里的值已经不存在，就保持当前默认项。
        """
        try:
            if not value:
                return
            idx = combo.findText(str(value))
            if idx >= 0:
                combo.setCurrentIndex(idx)
        except Exception:
            pass

    def restore_image_params(self):
        """
        从配置文件恢复图片生成参数：
        模式 / 尺寸 / 数量 / 质量。
        """
        try:
            img_cfg = self.config.setdefault("image", {})

            self._set_combo_text_if_exists(
                self.mode_combo,
                img_cfg.get("mode", "文生图")
            )
            self._set_combo_text_if_exists(
                self.size_combo,
                img_cfg.get("size", "自动")
            )
            self._set_combo_text_if_exists(
                self.count_combo,
                img_cfg.get("count", "1")
            )
            self._set_combo_text_if_exists(
                self.quality_combo,
                img_cfg.get("quality", "自动")
            )
            self._set_combo_text_if_exists(
                self.upload_optimization_combo,
                img_cfg.get("upload_optimization", "高质量")
            )
        except Exception:
            pass

    def _set_image_config(self, **values):
        self._set_model_config(**values)

    def save_image_params(self, *args):
        """
        保存图片生成参数。
        currentTextChanged 会传入文本参数，所以这里用 *args 兼容。
        """
        try:
            self._set_image_config(
                mode=self.mode_combo.currentText(),
                size=self.size_combo.currentText(),
                count=self.count_combo.currentText(),
                quality=self.quality_combo.currentText(),
                upload_optimization=self.upload_optimization_combo.currentText(),
            )
            save_config(self.config)
        except Exception:
            pass

    def _reference_copy_path(self, src, directory, prefix):
        try:
            p = os.path.abspath(str(src))
            st = os.stat(p)
            ext = os.path.splitext(p)[1].lower()
            if ext not in self.IMAGE_EXTS:
                ext = ".png"
            raw = json.dumps(
                {
                    "path": p,
                    "size": int(st.st_size),
                    "mtime_ns": int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1000000000))),
                    "prefix": prefix,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            name = f"{prefix}_{hashlib.sha256(raw.encode('utf-8', errors='ignore')).hexdigest()}{ext}"
            return os.path.join(directory, name)
        except Exception:
            ext = os.path.splitext(str(src))[1].lower()
            if ext not in self.IMAGE_EXTS:
                ext = ".png"
            return os.path.join(directory, f"{prefix}_{uuid.uuid4().hex}{ext}")

    def _copy_reference_file(self, src, directory, prefix, keep_existing_in_directory=True):
        try:
            if not src or not os.path.exists(src):
                return ""

            os.makedirs(directory, exist_ok=True)
            src_abs = os.path.abspath(src)
            dir_abs = os.path.abspath(directory)

            if keep_existing_in_directory and os.path.dirname(src_abs) == dir_abs:
                return src

            dst = self._reference_copy_path(src, directory, prefix)
            if os.path.abspath(src) != os.path.abspath(dst) and not os.path.exists(dst):
                shutil.copy2(src, dst)
            return dst
        except Exception:
            return src if isinstance(src, str) and os.path.exists(src) else ""

    def _copy_reference_to_draft(self, src, index):
        """
        把参考图复制到草稿目录。
        这样即使用户原来的图片移动或删除，程序重开后也能恢复预览。
        """
        return self._copy_reference_file(src, REFERENCE_DRAFT_DIR, "draft", keep_existing_in_directory=True)

    def _snapshot_reference_paths(self, refs):
        snapshots = []
        seen = set()
        for src in refs or []:
            copied = self._copy_reference_file(
                src,
                REFERENCE_SNAPSHOT_DIR,
                "snapshot",
                keep_existing_in_directory=True,
            )
            if not copied or not os.path.exists(copied):
                continue
            try:
                key = os.path.abspath(copied)
            except Exception:
                key = copied
            if key in seen:
                continue
            seen.add(key)
            snapshots.append(copied)
        return snapshots

    def _get_saved_prompt_for_mode(self, mode):
        """
        读取某个模式下的提示词草稿。
        mode 通常是：文生图 / 图生图。
        """
        try:
            data = load_input_drafts()
            prompts = data.get("image_prompts", {})
            if not isinstance(prompts, dict):
                prompts = {}

            text = prompts.get(mode, "")

            # 兼容历史草稿只保存 image_prompt 的情况。
            if not text and mode == self.mode_combo.currentText():
                old_text = data.get("image_prompt", "")
                if isinstance(old_text, str):
                    text = old_text

            return text if isinstance(text, str) else ""
        except Exception:
            return ""

    def _restore_prompt_for_mode(self, mode):
        """
        根据当前模式恢复对应提示词，不影响参考图。
        """
        try:
            text = self._get_saved_prompt_for_mode(mode)
            self._restoring_image_draft = True
            self.prompt_input.blockSignals(True)
            self.prompt_input.setPlainText(text)
            self.prompt_input.blockSignals(False)
        except Exception:
            try:
                self.prompt_input.blockSignals(False)
            except Exception:
                pass
        finally:
            self._restoring_image_draft = False

    def restore_image_input_draft(self):
        """
        恢复图片生成页草稿：
        1. 文生图/图生图各自的提示词；
        2. 参考图预览框。
        """
        try:
            self._restoring_image_draft = True
            data = load_input_drafts()

            # 恢复当前模式的提示词
            current_mode = self.mode_combo.currentText()
            prompt = self._get_saved_prompt_for_mode(current_mode)
            self.prompt_input.blockSignals(True)
            self.prompt_input.setPlainText(prompt)
            self.prompt_input.blockSignals(False)

            # 恢复参考图预览框
            refs = data.get("image_refs", [])
            if not isinstance(refs, list):
                refs = []

            self.refs = []
            self.ref_list.set_paths([])

            for path in refs:
                if isinstance(path, str) and os.path.exists(path):
                    self._append_ref_path(path)

        except Exception:
            try:
                self.prompt_input.blockSignals(False)
            except Exception:
                pass
        finally:
            self._restoring_image_draft = False

    def save_image_input_draft(self, *args, mode_override=None):
        """
        保存图片生成页草稿：
        1. 文生图/图生图分别保存各自提示词；
        2. 保存参考图预览框里的图片。
        """
        try:
            if self._restoring_image_draft:
                return

            data = load_input_drafts()

            mode = mode_override or self.mode_combo.currentText()
            prompts = data.get("image_prompts", {})
            if not isinstance(prompts, dict):
                prompts = {}

            prompts[mode] = self.prompt_input.toPlainText()
            data["image_prompts"] = prompts

            # 保留兼容字段，供历史草稿格式读取。
            data["image_prompt"] = self.prompt_input.toPlainText()

            copied_refs = []
            for i, src in enumerate(self.refs):
                copied = self._copy_reference_to_draft(src, i)
                if copied and os.path.exists(copied):
                    copied_refs.append(copied)

            data["image_refs"] = copied_refs
            save_input_drafts(data)
        except Exception:
            pass

    def on_image_mode_changed(self, new_mode):
        """
        文生图 / 图生图切换时：
        1. 先保存旧模式输入框内容；
        2. 再恢复新模式输入框内容。
        """
        try:
            if self._restoring_image_draft:
                return

            old_mode = self._last_image_mode or new_mode

            # 保存旧模式提示词
            self.save_image_input_draft(mode_override=old_mode)

            # 恢复新模式提示词
            self._restore_prompt_for_mode(new_mode)

            self._last_image_mode = new_mode
        except Exception:
            self._last_image_mode = new_mode

    # ---- 历史 ----

    def _set_image_generation_running(self):
        self.generate_btn.setEnabled(True)
        self.generate_btn.setObjectName("danger")
        self.generate_btn.setText("中止")
        self.generate_btn.setToolTip("中止当前图片生成任务")
        self.generate_btn.style().unpolish(self.generate_btn)
        self.generate_btn.style().polish(self.generate_btn)
        self.generate_btn.update()
        self.bar.set_status("任务运行中...")

    def _set_image_generation_idle(self, status):
        self.generate_btn.setEnabled(True)
        self.generate_btn.setObjectName("primary")
        self.generate_btn.setText("生成")
        self.generate_btn.setToolTip("")
        self.generate_btn.style().unpolish(self.generate_btn)
        self.generate_btn.style().polish(self.generate_btn)
        self.generate_btn.update()
        self.bar.set_status(status)

    def on_generate_clicked(self):
        if self.worker and self.worker.isRunning():
            self.stop_generation()
            return
        self.generate()

    def stop_generation(self):
        worker = self.worker
        if worker is None:
            return
        try:
            if hasattr(worker, "stop"):
                worker.stop()
            else:
                worker.requestInterruption()
        except Exception:
            pass
        self._set_image_generation_idle("正在中止任务...")
        self.add_task_log(f"[{now_str()}] 已请求中止当前图片任务")

    def add_task_log(self, text):
        """
        添加一条任务进度，并持久化保存。
        每次打开程序后会恢复这些内容，并自动滚动到最新一条。
        """
        try:
            self.task_list.addItem(text)
            while self.task_list.count() > self.TASK_LOG_RENDER_ITEMS:
                self.task_list.takeItem(0)
            self.task_list.scrollToBottom()
            self._task_log_save_timer.start(250)
        except Exception:
            pass

    def _task_log_items(self):
        logs = []
        count = self.task_list.count()
        start = max(0, count - self.MAX_TASK_LOG_ITEMS)
        for i in range(start, count):
            item = self.task_list.item(i)
            if item:
                logs.append(item.text())
        return logs

    def load_persistent_task_log(self):
        """加载右侧“任务进度”历史记录。"""
        try:
            data = load_json_file(IMAGE_TASK_LOG_FILE, [])
            if not isinstance(data, list):
                data = []

            self.task_list.clear()

            # 历史文件保留较多记录，界面只渲染最近少量记录，避免 QListWidget 首次绘制卡住。
            for item in data[-self.TASK_LOG_RENDER_ITEMS:]:
                if isinstance(item, str) and item.strip():
                    text = item.strip()
                    if len(text) > 180:
                        text = text[:180] + "..."
                    self.task_list.addItem(text)

            self.task_list.scrollToBottom()
            QTimer.singleShot(200, self.task_list.scrollToBottom)
        except Exception:
            pass

    def save_persistent_task_log(self):
        """保存右侧“任务进度”历史记录。"""
        try:
            save_json_file(IMAGE_TASK_LOG_FILE, self._task_log_items())
        except Exception:
            pass

    def clear_persistent_task_log(self):
        """清空任务进度历史。"""
        try:
            self.task_list.clear()
            save_json_file(IMAGE_TASK_LOG_FILE, [])
        except Exception:
            pass

    def _normalize_history_result(self, result):
        if not isinstance(result, dict):
            return None

        images = result.get("images", [])
        if not isinstance(images, list):
            images = []

        valid = [p for p in images if self._is_valid_image_file(p)]
        if not valid:
            return None

        result["images"] = valid
        result.setdefault("prompt", "")
        refs = result.get("refs", [])
        if not isinstance(refs, list):
            refs = []
        result["refs"] = [p for p in refs if isinstance(p, str) and os.path.exists(p)]
        return result

    def _is_valid_image_file(self, path):
        try:
            return isinstance(path, str) and os.path.exists(path) and os.path.getsize(path) > 0
        except Exception:
            return False

    def load_persistent_history(self):
        try:
            self.gallery_widget.setVisible(False)
        except Exception:
            pass

        try:
            init_image_history_store()
            migrate_json_history_once()
        except Exception:
            pass

        self.history = []
        self._gallery_total_count = self._count_gallery_images()
        self.rebuild_gallery(deferred=True)

    def save_persistent_history(self):
        for result in list(self.history):
            try:
                append_image_result(result)
            except Exception:
                pass
        self.history = []
        self._gallery_total_count = self._count_gallery_images()

    def clear_persistent_history(self):
        self.history = []
        self._gallery_total_count = 0
        clear_image_history_store()
        save_json_file(IMAGE_HISTORY_FILE, [])
        self.clear_persistent_task_log()
        self.clear_gallery()
        self.add_task_log(f"[{now_str()}] 历史记录已清空")

    # ---- 参考图 ----

    def _append_ref_path(self, path):
        if not isinstance(path, str) or not os.path.exists(path):
            return False
        try:
            target = os.path.abspath(path)
            for existing in self.refs:
                try:
                    if os.path.abspath(existing) == target:
                        return False
                except Exception:
                    if existing == path:
                        return False
        except Exception:
            if path in self.refs:
                return False
        self.refs.append(path)
        self.ref_list.add_path(path)
        return True

    def add_refs(self, files):
        changed = False
        for f in files:
            if self._append_ref_path(f):
                changed = True
        if changed:
            self.save_image_input_draft()

    def replace_refs(self, files):
        refs = []
        seen = set()
        for path in files or []:
            if not isinstance(path, str) or not os.path.exists(path):
                continue
            try:
                key = os.path.abspath(path)
            except Exception:
                key = path
            if key in seen:
                continue
            seen.add(key)
            refs.append(path)

        self.refs = refs
        self.ref_list.set_paths(self.refs)
        self.save_image_input_draft()

    def clear_refs(self):
        self.refs = []
        self.ref_list.set_paths([])
        self.save_image_input_draft()

    def _on_ref_removed(self, path):
        if path in self.refs:
            self.refs.remove(path)
            self.ref_list.set_paths(self.refs)
            self.save_image_input_draft()

    def paste_image_from_clipboard(self):
        """
        图片生成页粘贴图片。

        重要：
        macOS/Finder 复制图片文件时，剪贴板里通常同时包含：
        1. 原始文件 URL；
        2. 图片预览数据。

        必须优先使用 URL，否则会把预览图另存为 clipboard_xxx.png，
        导致路径不是用户复制的原文件。
        """
        cb = QGuiApplication.clipboard()
        mime = cb.mimeData()

        # 1. 优先处理从 Finder / 文件管理器复制的原始文件路径。
        paths = self._image_paths_from_mime(mime)
        if paths:
            self.add_refs(paths)
            return

        # 2. 如果没有文件 URL，才处理真正的剪贴板图片，例如截图。
        if mime.hasImage():
            image = cb.image()
            path = os.path.join(IMAGE_DIR, f"clipboard_{uuid.uuid4().hex}.png")
            image.save(path)
            self.add_refs([path])

    def _validate_image_generation_request(self):
        prompt = self.prompt_input.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "提示", "请输入提示词。")
            return None

        provider = get_provider(self.config, self.bar.current_provider_id())
        if not provider:
            QMessageBox.warning(self, "提示", "请先在设置中添加并选择厂商。")
            return None

        model = self.bar.current_model()
        if not model:
            QMessageBox.warning(self, "提示", "请选择模型，或点击刷新加载列表。")
            return None

        mode = self.mode_combo.currentText()
        if mode == "图生图" and not self.refs:
            QMessageBox.warning(self, "提示", "图生图模式需要至少上传一张参考图。")
            return None

        return prompt, provider, model, mode

    def generate(self):
        request = self._validate_image_generation_request()
        if request is None:
            return
        prompt, provider, model, mode = request

        self._set_image_config(model=model)
        self.save_image_params()

        self._set_image_generation_running()
        self.add_task_log(f"[{now_str()}] 开始任务：{prompt[:30]}")
        refs = self.refs[:] if mode == "图生图" else []
        task_refs = self._snapshot_reference_paths(refs) if refs else []
        if mode == "图生图" and not task_refs:
            self._set_image_generation_idle("参考图不可用")
            self.add_task_log(f"[{now_str()}] 失败：参考图文件不存在或无法读取")
            QMessageBox.warning(self, "提示", "参考图文件不存在或无法读取，请重新添加参考图。")
            return

        self.worker = ImageWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            self.size_combo.currentText(),
            self.quality_combo.currentText(),
            self.count_combo.currentText(),
            prompt, task_refs,
            provider.get("proxy_url", ""),
            self.upload_optimization_combo.currentText(),
            provider.get("proxy_mode", "仅下载图片" if provider.get("proxy_url") else "不使用代理"),
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.result_ready.connect(self.on_image_finished)
        self.worker.failed.connect(self.on_image_failed)
        self.worker.finished.connect(self._cleanup_image_worker)
        self.worker.start()

    def on_progress(self, text):
        self.bar.set_status(text)
        self.add_task_log(f"[{now_str()}] {text}")

    def on_image_finished(self, result):
        try:
            self._set_image_generation_idle("生成完成")
            self.add_task_log(f"[{result['time']}] 完成：{len(result['images'])} 张图片")
            self.history.append(result)
            self._gallery_total_count += sum(
                1 for path in result.get("images", [])
                if isinstance(path, str) and os.path.exists(path)
            )
            QTimer.singleShot(0, self.save_persistent_history)
            QTimer.singleShot(0, lambda self=self, r=result: self.add_images_to_gallery(r))
            QTimer.singleShot(500, gc.collect)
        except Exception:
            pass

    def on_image_failed(self, err):
        err = clean_error_text(err)
        if "任务已中止" in err:
            self._set_image_generation_idle("任务已中止")
            self.add_task_log(f"[{now_str()}] 任务已中止")
            QTimer.singleShot(500, gc.collect)
            return
        self._set_image_generation_idle("生成失败")
        show_generation_error(self, "生成失败", err, status="生成失败", log_func=self.add_task_log)
        QTimer.singleShot(500, gc.collect)

    def _cleanup_image_worker(self, *_args):
        worker = self.sender()

        def cleanup():
            try:
                if self.worker is worker:
                    self.worker = None
                if worker is not None:
                    worker.deleteLater()
            except Exception:
                pass
            QTimer.singleShot(500, gc.collect)

        QTimer.singleShot(0, cleanup)

    def _delete_widget(self, widget):
        if widget is None:
            return
        try:
            widget.setParent(None)
            widget.deleteLater()
        except Exception:
            pass

    def _queue_thumbnail_generation(self, paths):
        try:
            for path in paths or []:
                if isinstance(path, str) and os.path.exists(path):
                    self._thumbnail_pending_paths.add(path)
            self._start_thumbnail_worker_if_idle()
        except Exception:
            pass

    def _start_thumbnail_worker_if_idle(self):
        try:
            if self.thumbnail_worker is not None and self.thumbnail_worker.isRunning():
                return

            paths = list(self._thumbnail_pending_paths)
            if not paths:
                return

            self._thumbnail_pending_paths.clear()
            worker = ThumbnailWorker(paths, 210, 210)
            self.thumbnail_worker = worker
            worker.thumbnail_ready.connect(self._on_thumbnail_ready)
            worker.finished.connect(self._on_thumbnail_worker_finished)
            worker.start()
        except Exception:
            pass

    def _on_thumbnail_ready(self, image_path, cache_path):
        try:
            for card in list(self._gallery_cards):
                if isinstance(card, ImageCard) and self._same_image_path(card.image_path, image_path):
                    card.set_thumbnail_from_cache(cache_path)
        except Exception:
            pass

    def _on_thumbnail_worker_finished(self):
        worker = self.sender()

        def cleanup():
            try:
                if self.thumbnail_worker is worker:
                    self.thumbnail_worker = None
                if worker is not None:
                    worker.deleteLater()
            except Exception:
                pass
            self._start_thumbnail_worker_if_idle()

        QTimer.singleShot(0, cleanup)

    def _take_gallery_widgets(self):
        widgets = []
        while self.gallery_layout.count():
            item = self.gallery_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widgets.append(widget)
        return widgets

    def clear_gallery(self):
        try:
            self._gallery_rebuild_token += 1
            for widget in list(self._gallery_cards):
                self._delete_widget(widget)

            self._gallery_cards = []

            for widget in self._take_gallery_widgets():
                self._delete_widget(widget)
        except Exception:
            pass

    def _build_gallery_cards_for_result(self, result):
        cards = []

        try:
            if not isinstance(result, dict):
                return cards

            prompt = result.get("prompt", "")
            refs = result.get("refs", [])
            images = result.get("images", [])

            for img_path in images:
                if not self._is_valid_image_file(img_path):
                    continue
                cards.append(ImageCard(img_path, prompt, refs, self.use_as_ref, self.reedit))
        except Exception:
            pass

        return cards

    def _queue_gallery_card_thumbnails(self, cards):
        paths = []
        for card in cards or []:
            if isinstance(card, ImageCard):
                paths.append(card.image_path)
        self._queue_thumbnail_generation(paths)

    def _gallery_render_limit_value(self):
        try:
            return max(0, int(self._gallery_render_limit or self.GALLERY_PAGE_SIZE))
        except Exception:
            return self.GALLERY_PAGE_SIZE

    def _iter_gallery_items(self, limit=None, skip_paths=None):
        target = self.GALLERY_PAGE_SIZE if limit is None else int(limit)
        displayed = skip_paths or set()
        offset = len(displayed)
        emitted = 0
        while emitted < target:
            batch_size = max(self.GALLERY_PAGE_SIZE, target - emitted)
            batch = list(iter_image_history_items(batch_size, offset, displayed))
            if not batch:
                return
            offset += batch_size
            for img_path, prompt, refs in batch:
                yield img_path, prompt, refs
                emitted += 1
                if emitted >= target:
                    return

    def _gallery_items_for_current_limit(self):
        return list(self._iter_gallery_items(self._gallery_render_limit_value()))

    def _gallery_displayed_paths(self):
        paths = set()
        for card in self._gallery_cards:
            try:
                paths.add(os.path.abspath(card.image_path))
            except Exception:
                pass
        return paths

    def _count_gallery_images(self):
        return count_image_history_store()

    def _build_gallery_cards_for_items(self, items):
        cards = []
        for img_path, prompt, refs in items or []:
            cards.append(ImageCard(img_path, prompt, refs, self.use_as_ref, self.reedit))
        return cards

    def _reflow_gallery_cards(self):
        try:
            cards = list(self._gallery_cards)
            card_ids = {id(card) for card in cards}

            try:
                self.gallery_widget.setUpdatesEnabled(False)
            except Exception:
                pass

            try:
                for widget in self._take_gallery_widgets():
                    if id(widget) not in card_ids:
                        self._delete_widget(widget)
            except Exception:
                pass

            self._gallery_load_more_btn = None

            cols = 3
            for idx, card in enumerate(cards):
                row, col = divmod(idx, cols)
                self.gallery_layout.addWidget(card, row, col)

            self._add_gallery_load_more_notice(len(cards), self._gallery_total_count)

        finally:
            try:
                self.gallery_widget.setUpdatesEnabled(True)
                self.gallery_widget.update()
            except Exception:
                pass

    def _add_gallery_load_more_notice(self, shown_count, total_count):
        hidden_count = max(0, int(total_count) - int(shown_count))
        if hidden_count <= 0:
            self._gallery_load_more_btn = None
            return

        btn = QPushButton(f"已隐藏更早的 {hidden_count} 张图片，点击加载更多 {self.GALLERY_PAGE_SIZE} 张")
        btn.setObjectName("ghost")
        make_clickable(btn, "历史和图片文件仍保留，只是为了降低内存没有一次性渲染。")
        btn.clicked.connect(self.load_more_gallery_images)
        self._gallery_load_more_btn = btn

        cols = 3
        row = (max(0, shown_count) + cols - 1) // cols
        self.gallery_layout.addWidget(btn, row, 0, 1, cols)

    def load_more_gallery_images(self):
        old_value = 0
        try:
            old_value = self.gallery_scroll.verticalScrollBar().value()
        except Exception:
            old_value = 0

        items = list(self._iter_gallery_items(self.GALLERY_PAGE_SIZE, self._gallery_displayed_paths()))
        new_cards = self._build_gallery_cards_for_items(items)

        if new_cards:
            self._gallery_cards.extend(new_cards)
            self._queue_gallery_card_thumbnails(new_cards)
            self._gallery_render_limit = len(self._gallery_cards)
            self._reflow_gallery_cards()
            for ms in (0, 40, 120):
                QTimer.singleShot(ms, lambda v=old_value: self.gallery_scroll.verticalScrollBar().setValue(v))

        try:
            self.bar.set_status(f"已加载更多图片，当前显示 {len(self._gallery_cards)} 张")
        except Exception:
            pass

    def rebuild_gallery(self, deferred=False):
        """
        仅在历史加载时做一次全量构建。
        之后新增图片走增量插入。
        """
        try:
            self._gallery_rebuild_token += 1
            self._gallery_cards = []
            for widget in self._take_gallery_widgets():
                self._delete_widget(widget)

            if deferred:
                items = self._gallery_items_for_current_limit()
                cols = 3

                try:
                    self.gallery_widget.setUpdatesEnabled(False)
                except Exception:
                    pass

                try:
                    for img_path, prompt, refs in items:
                        card = ImageCard(img_path, prompt, refs, self.use_as_ref, self.reedit)
                        self._gallery_cards.append(card)
                        idx = len(self._gallery_cards) - 1
                        row, col = divmod(idx, cols)
                        self.gallery_layout.addWidget(card, row, col)

                    self._add_gallery_load_more_notice(len(self._gallery_cards), self._gallery_total_count)
                finally:
                    try:
                        self.gallery_widget.setUpdatesEnabled(True)
                        self.gallery_widget.setVisible(True)
                        self.gallery_widget.update()
                    except Exception:
                        pass

                self._queue_gallery_card_thumbnails(self._gallery_cards)
                return

            new_cards = self._build_gallery_cards_for_items(self._gallery_items_for_current_limit())
            self._gallery_cards.extend(new_cards)
            self._queue_gallery_card_thumbnails(new_cards)

            self._reflow_gallery_cards()
            try:
                self.gallery_widget.setVisible(True)
            except Exception:
                pass
        except Exception:
            try:
                self.gallery_widget.setVisible(True)
            except Exception:
                pass

    def add_images_to_gallery(self, result):
        """
        新生成结果只插入新卡片，不重新创建旧卡片。
        """
        try:
            new_cards = self._build_gallery_cards_for_result(result)
            if not new_cards:
                return

            self._queue_gallery_card_thumbnails(new_cards)
            limit = max(
                self.GALLERY_PAGE_SIZE,
                int(self._gallery_render_limit or self.GALLERY_PAGE_SIZE),
            )
            visible_cards = new_cards + list(self._gallery_cards)
            overflow_cards = visible_cards[limit:]
            self._gallery_cards = visible_cards[:limit]

            for card in overflow_cards:
                self._delete_widget(card)

            self._reflow_gallery_cards()
        except Exception:
            pass

    def _same_image_path(self, left, right):
        try:
            return os.path.abspath(left) == os.path.abspath(right)
        except Exception:
            return left == right

    def _reflow_gallery_without_image(self, image_path):
        """
        只移除当前图片卡片，并对已有卡片重新排版。
        不重新创建 ImageCard，不重新加载缩略图。
        """
        removed = False

        try:
            keep_cards = []

            for card in list(self._gallery_cards):
                if isinstance(card, ImageCard) and self._same_image_path(card.image_path, image_path):
                    removed = True
                    self._delete_widget(card)
                else:
                    keep_cards.append(card)

            self._gallery_cards = keep_cards
            self._reflow_gallery_cards()

        except Exception:
            try:
                self.rebuild_gallery()
            except Exception:
                pass

        return removed

    def _finish_deleted_image_disk_work(self, image_path, removed_from_ui, removed_from_history):
        try:
            self.save_persistent_history()
        except Exception as e:
            try:
                print("保存图片历史失败:", e)
            except Exception:
                pass

        try:
            if os.path.exists(image_path) and os.path.isfile(image_path):
                os.remove(image_path)
        except Exception as e:
            try:
                print("删除图片文件失败:", e)
            except Exception:
                pass

        try:
            self.add_task_log(f"[{now_str()}] 已删除图片：{os.path.basename(image_path)}")
        except Exception:
            pass

        if not removed_from_ui and removed_from_history:
            try:
                self.rebuild_gallery()
            except Exception:
                pass

    def delete_generated_image(self, image_path):
        """
        删除单张历史图片：先更新界面，再延后保存历史和删除本地文件。
        """
        try:
            if not image_path:
                return

            ret = QMessageBox.warning(
                self,
                "删除这张图片",
                "确定要删除这张图片吗？\n\n此操作会从历史记录中移除，并删除本地缓存文件，不可恢复。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if ret != QMessageBox.Yes:
                return

            remove_image_history_item(image_path)
            removed_from_history = True
            self._gallery_total_count = max(0, self._gallery_total_count - 1)

            try:
                removed_from_ui = self._reflow_gallery_without_image(image_path)
            except Exception:
                removed_from_ui = False

            try:
                self.bar.set_status("已删除这张图片")
            except Exception:
                pass

            QTimer.singleShot(
                30,
                lambda: self._finish_deleted_image_disk_work(
                    image_path,
                    removed_from_ui,
                    removed_from_history,
                )
            )

        except Exception as e:
            try:
                QMessageBox.warning(self, "删除失败", str(e))
            except Exception:
                pass

    def use_as_ref(self, path):
        self.mode_combo.setCurrentText("图生图")
        self.add_refs([path])

    def reedit(self, prompt, refs):
        self.prompt_input.setPlainText(prompt)
        self.mode_combo.setCurrentText("图生图" if refs else "文生图")
        if refs:
            self.add_refs(list(refs or []))


# ============================================================
# 智能体会话列表对话框
# ============================================================
