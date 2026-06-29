import os
from copy import deepcopy

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QTextEdit,
)

from .core import clean_error_text, get_provider, load_json_file, log_debug, now_str, save_config
from .model_bar_mixin import SimpleModelBarMixin
from .novel_storage import NOVEL_DIR, ensure_novel_storage, list_project_records, named_project_path, save_project_file
from .novel_utils import (
    _chapter_analysis_hash,
    _default_project,
    _new_chapter,
    _normalize_name_list,
    _normalize_project,
    _safe_name,
)
from .widgets import ProviderModelBar, WideComboBox
from .workers import NovelWritingWorker


class PlainTextEdit(QTextEdit):
    def insertFromMimeData(self, source):
        if source is not None and source.hasText():
            self.insertPlainText(source.text())
            return
        super().insertFromMimeData(source)


class NovelAdaptationTab(SimpleModelBarMixin, QWidget):
    request_settings = Signal()
    open_project_requested = Signal(str)
    MODEL_CONFIG_SECTION = "novel"
    FALLBACK_MODELS = ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"]

    def __init__(self, config=None, current_project_provider=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self.model_worker = None
        self.adaptation_worker = None
        self.adaptation_stream_text = ""
        self.adaptation_queue = []
        self.adaptation_current_index = -1
        self._adaptation_stop_requested_by_user = False
        self.adaptation_source_project = None
        self.adaptation_source_path = ""
        self.adaptation_target_project = None
        self.adaptation_target_path = ""
        self.adaptation_continue_next = False
        self.adaptation_auto_target_title = ""
        self.adaptation_target_title_user_edited = False
        self._pending_model_reload = False
        self._current_project_provider = current_project_provider or (lambda: (_default_project(), ""))

        ensure_novel_storage()
        self._build_ui()
        self._init_source_project_watcher()
        self.refresh_adaptation_projects()
        QTimer.singleShot(0, self.load_models)

    def _init_source_project_watcher(self):
        self._project_sync_timer = QTimer(self)
        self._project_sync_timer.setSingleShot(True)
        self._project_sync_timer.setInterval(250)
        self._project_sync_timer.timeout.connect(self.refresh_adaptation_projects)
        self._project_dir_watcher = QFileSystemWatcher(self)
        if os.path.isdir(NOVEL_DIR):
            self._project_dir_watcher.addPath(NOVEL_DIR)
        self._project_dir_watcher.directoryChanged.connect(self._on_project_dir_changed)

    def _on_project_dir_changed(self, _path=""):
        if os.path.isdir(NOVEL_DIR) and NOVEL_DIR not in self._project_dir_watcher.directories():
            self._project_dir_watcher.addPath(NOVEL_DIR)
        self._schedule_project_sync()

    def _schedule_project_sync(self):
        if hasattr(self, "_project_sync_timer"):
            self._project_sync_timer.start()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        header = QFrame()
        header.setObjectName("novel_tool_strip")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(8)

        title = QLabel("项目改编")
        title.setObjectName("section_title")
        header_layout.addWidget(title)

        self.status_label = QLabel("选择源项目和模式后开始改编。")
        self.status_label.setObjectName("hint")
        self.status_label.setWordWrap(True)
        header_layout.addWidget(self.status_label, 1)
        root.addWidget(header)

        self.bar = ProviderModelBar()
        self.bar.settings_btn.setVisible(True)
        self.bar.settings_btn.setToolTip("管理 AI 厂商")
        self.bar.provider_changed.connect(self.on_provider_changed)
        self.bar.model_changed.connect(self.on_model_changed)
        self.bar.refresh_clicked.connect(self.load_models)
        self.bar.settings_clicked.connect(self.request_settings.emit)
        root.addWidget(self.bar)
        self.refresh_providers()

        controls = QFrame()
        controls.setObjectName("novel_tool_strip")
        controls_layout = QGridLayout(controls)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setHorizontalSpacing(8)
        controls_layout.setVerticalSpacing(6)

        self.adaptation_source_combo = WideComboBox()
        self.adaptation_mode_combo = WideComboBox()
        for label, action in (
            ("剧本转小说", "script_to_novel"),
            ("小说转剧本", "novel_to_script"),
            ("小说转分镜", "novel_to_storyboard"),
            ("剧本转分镜", "script_to_storyboard"),
        ):
            self.adaptation_mode_combo.addItem(label, action)
        self.adaptation_range_combo = WideComboBox()
        self.adaptation_range_combo.addItems(["选中章节", "全部未改编", "全部章节"])
        self.adaptation_optimization_combo = WideComboBox()
        for label, key in (
            ("忠实整理", "faithful"),
            ("适度优化", "balanced"),
            ("大胆重写", "rewrite"),
        ):
            self.adaptation_optimization_combo.addItem(label, key)
        saved_optimization = str(self.config.setdefault("novel", {}).get("adaptation_optimization", "balanced") or "balanced")
        saved_optimization_index = self.adaptation_optimization_combo.findData(saved_optimization)
        self.adaptation_optimization_combo.setCurrentIndex(saved_optimization_index if saved_optimization_index >= 0 else 1)

        self.adaptation_target_title = QLineEdit()
        self.adaptation_target_title.textEdited.connect(self.on_adaptation_target_title_edited)
        self.adaptation_source_combo.currentIndexChanged.connect(self.on_adaptation_source_changed)
        self.adaptation_mode_combo.currentIndexChanged.connect(self.on_adaptation_mode_changed)
        self.adaptation_range_combo.currentIndexChanged.connect(self.on_adaptation_range_changed)
        self.adaptation_optimization_combo.currentIndexChanged.connect(self.on_adaptation_optimization_changed)

        controls_layout.addWidget(QLabel("源项目"), 0, 0)
        controls_layout.addWidget(self.adaptation_source_combo, 0, 1)
        controls_layout.addWidget(QLabel("改编模式"), 0, 2)
        controls_layout.addWidget(self.adaptation_mode_combo, 0, 3)
        controls_layout.addWidget(QLabel("改编范围"), 0, 4)
        controls_layout.addWidget(self.adaptation_range_combo, 0, 5)
        controls_layout.addWidget(QLabel("目标项目"), 1, 0)
        controls_layout.addWidget(self.adaptation_target_title, 1, 1, 1, 3)
        controls_layout.addWidget(QLabel("优化程度"), 1, 4)
        controls_layout.addWidget(self.adaptation_optimization_combo, 1, 5)
        for col in (1, 3, 5):
            controls_layout.setColumnStretch(col, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        start_btn = QPushButton("开始改编")
        start_btn.setObjectName("primary")
        start_btn.clicked.connect(self.start_adaptation)
        stop_btn = QPushButton("中止")
        stop_btn.setObjectName("danger")
        stop_btn.clicked.connect(self.stop_adaptation)
        self.adaptation_start_btn = start_btn
        self.adaptation_stop_btn = stop_btn
        stop_btn.setVisible(False)
        stop_btn.setEnabled(False)
        for btn in (start_btn, stop_btn):
            btn.setMinimumWidth(86)
            action_row.addWidget(btn)
        controls_layout.addLayout(action_row, 0, 6, 2, 1)
        root.addWidget(controls)

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)

        left = QFrame()
        left.setObjectName("novel_column_card")
        left.setMinimumWidth(280)
        left.setMaximumWidth(360)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)
        left_title = QLabel("章节 / 分集")
        left_title.setObjectName("field_label")
        left_layout.addWidget(left_title)
        self.adaptation_chapter_list = QListWidget()
        self.adaptation_chapter_list.currentRowChanged.connect(self.on_adaptation_chapter_selected)
        left_layout.addWidget(self.adaptation_chapter_list, 1)
        body.addWidget(left)

        right = QFrame()
        right.setObjectName("novel_column_card")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(6)
        preview_title = QLabel("预览")
        preview_title.setObjectName("field_label")
        right_layout.addWidget(preview_title)

        preview_splitter = QSplitter(Qt.Vertical)
        preview_splitter.setChildrenCollapsible(False)

        original_box = QFrame()
        original_layout = QVBoxLayout(original_box)
        original_layout.setContentsMargins(0, 0, 0, 0)
        original_layout.addWidget(QLabel("源内容"))
        self.adaptation_original_preview = PlainTextEdit()
        self.adaptation_original_preview.setReadOnly(True)
        original_layout.addWidget(self.adaptation_original_preview, 1)

        result_box = QFrame()
        result_layout = QVBoxLayout(result_box)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_head = QHBoxLayout()
        result_head.setContentsMargins(0, 0, 0, 0)
        result_head.addWidget(QLabel("改编结果"))
        result_head.addStretch()
        result_head.addWidget(self._ghost_button("复制结果", self.copy_adaptation_result))
        result_head.addWidget(self._ghost_button("打开目标项目", self.open_adaptation_target_project))
        result_layout.addLayout(result_head)
        self.adaptation_result_preview = PlainTextEdit()
        self.adaptation_result_preview.setReadOnly(True)
        result_layout.addWidget(self.adaptation_result_preview, 1)

        preview_splitter.addWidget(original_box)
        preview_splitter.addWidget(result_box)
        preview_splitter.setSizes([1, 1])
        right_layout.addWidget(preview_splitter, 1)
        body.addWidget(right)
        body.setSizes([320, 820])
        root.addWidget(body, 1)

    def _ghost_button(self, text, callback=None, tooltip=""):
        btn = QPushButton(text)
        btn.setObjectName("ghost")
        if tooltip:
            btn.setToolTip(tooltip)
        if callback:
            btn.clicked.connect(callback)
        return btn

    def _set_text_without_signals(self, widget, text):
        widget.blockSignals(True)
        try:
            widget.setPlainText(text)
        finally:
            widget.blockSignals(False)

    def set_status_tip(self, text):
        text = str(text or "")
        if hasattr(self, "status_label"):
            self.status_label.setText(text)
            self.status_label.setToolTip(text)
        self.setToolTip(text)

    def _current_novel_ai_selection(self):
        provider = get_provider(self.config, self.bar.current_provider_id())
        model = self.bar.current_model() or self.config.get("novel", {}).get("model", "")
        if not provider:
            return None, "", "请先选择厂商。"
        if not model:
            return None, "", "请选择模型。"
        return provider, model, ""

    def _provider_proxy_mode(self, provider):
        if not provider:
            return "不使用代理"
        return provider.get("proxy_mode", "提交和下载" if provider.get("proxy_url") else "不使用代理")

    def _current_project_snapshot(self):
        try:
            project, path = self._current_project_provider()
        except Exception as e:
            log_debug("读取当前小说项目失败", e)
            return _default_project(), ""
        project = _normalize_project(deepcopy(project))
        return project, str(path or "")

    def refresh_adaptation_projects(self):
        if not hasattr(self, "adaptation_source_combo"):
            return
        current_data = self.adaptation_source_combo.currentData()
        self.adaptation_source_combo.blockSignals(True)
        try:
            self.adaptation_source_combo.clear()
            self.adaptation_source_combo.addItem("当前项目", "__current__")
            for record in list_project_records():
                path = record.get("path", "")
                data = record.get("data", {})
                title = self._adaptation_project_title(data, path)
                self.adaptation_source_combo.addItem(title, path)
            if current_data:
                idx = self.adaptation_source_combo.findData(current_data)
                if idx >= 0:
                    self.adaptation_source_combo.setCurrentIndex(idx)
        finally:
            self.adaptation_source_combo.blockSignals(False)
        self.refresh_adaptation_chapter_list()

    def _adaptation_project_title(self, project, source_path=""):
        source_path = str(source_path or "").strip()
        if source_path and source_path != "__current__":
            name = os.path.splitext(os.path.basename(source_path))[0]
            if name:
                return name
        meta = project.get("meta", {}) if isinstance(project, dict) else {}
        return str(meta.get("title") or "未命名小说").strip() or "未命名小说"

    def _load_adaptation_source_project(self):
        data = self.adaptation_source_combo.currentData() if hasattr(self, "adaptation_source_combo") else "__current__"
        if data == "__current__" or not data:
            return self._current_project_snapshot()
        project = load_json_file(data, None)
        if not isinstance(project, dict):
            raise ValueError("源项目文件无效。")
        return _normalize_project(project), data

    def on_adaptation_source_changed(self):
        try:
            self.adaptation_target_title_user_edited = False
            source_project, source_path = self._load_adaptation_source_project()
            action = self.adaptation_mode_combo.currentData() or "script_to_novel"
            title = self._adaptation_target_title_for(source_project, action, source_path)
            self.adaptation_target_title.setText(title)
            self.adaptation_auto_target_title = title
        except Exception:
            pass
        self.refresh_adaptation_chapter_list()

    def on_adaptation_mode_changed(self):
        try:
            self.adaptation_target_title_user_edited = False
            source_project, source_path = self._load_adaptation_source_project()
            action = self.adaptation_mode_combo.currentData() or "script_to_novel"
            title = self._adaptation_target_title_for(source_project, action, source_path)
            self.adaptation_target_title.setText(title)
            self.adaptation_auto_target_title = title
        except Exception:
            pass
        self.refresh_adaptation_chapter_list()

    def on_adaptation_target_title_edited(self):
        self.adaptation_target_title_user_edited = True

    def on_adaptation_range_changed(self):
        self.adaptation_target_title_user_edited = False
        self.update_adaptation_target_title()

    def on_adaptation_optimization_changed(self):
        level = self._adaptation_optimization_level()
        self.config.setdefault("novel", {})["adaptation_optimization"] = level
        try:
            save_config(self.config)
        except Exception as e:
            log_debug("小说改编优化程度保存失败", e)
        self.refresh_adaptation_chapter_list()

    def _adaptation_optimization_level(self):
        if not hasattr(self, "adaptation_optimization_combo"):
            return "balanced"
        value = self.adaptation_optimization_combo.currentData()
        value = str(value or "balanced")
        return value if value in {"faithful", "balanced", "rewrite"} else "balanced"

    def _adaptation_optimization_label(self):
        if not hasattr(self, "adaptation_optimization_combo"):
            return "适度优化"
        return self.adaptation_optimization_combo.currentText() or "适度优化"

    def _adaptation_optimization_instruction(self):
        level = self._adaptation_optimization_level()
        if level == "faithful":
            return (
                "优化程度：忠实整理。尽量保留原剧情顺序、信息密度、关键对白、人物动机和情绪走向；"
                "主要做格式转换、语句顺畅化和必要衔接，不主动新增情节，不大幅改写人物行为。"
            )
        if level == "rewrite":
            return (
                "优化程度：大胆重写。在不破坏核心事实、人物关系和关键结局的前提下，可以重组段落、强化冲突、"
                "补足场景细节、调整对白节奏、增强情绪推进和可读性；允许较大幅度改写表达与局部呈现。"
            )
        return (
            "优化程度：适度优化。保留原剧情骨架、关键事件和人物关系；可以优化叙事顺序、语言质感、对白节奏、"
            "场景描写和情绪铺垫，但不要新增会改变后续连续性的重大情节。"
        )

    def update_adaptation_target_title(self):
        if not hasattr(self, "adaptation_target_title"):
            return
        try:
            source_project, source_path = self._load_adaptation_source_project()
            action = self.adaptation_mode_combo.currentData() or "script_to_novel"
            title = self._adaptation_target_title_for(source_project, action, source_path)
            current = self.adaptation_target_title.text().strip()
            if not current or not self.adaptation_target_title_user_edited or current == self.adaptation_auto_target_title:
                self.adaptation_target_title.setText(title)
                self.adaptation_auto_target_title = title
        except Exception:
            pass

    def _adaptation_target_title_for(self, source_project, action, source_path=""):
        base = self._adaptation_source_title(source_project, source_path)
        suffix = {
            "script_to_novel": "小说版",
            "novel_to_script": "剧本版",
            "novel_to_storyboard": "分镜版",
            "script_to_storyboard": "分镜版",
        }.get(str(action or ""), "改编版")
        if base.endswith(f" - {suffix}"):
            return base
        return f"{base} - {suffix}"

    def _adaptation_source_title(self, project, source_path=""):
        mode = self.adaptation_range_combo.currentText() if hasattr(self, "adaptation_range_combo") else ""
        if mode == "选中章节" and hasattr(self, "adaptation_chapter_list"):
            row = self.adaptation_chapter_list.currentRow()
            chapters = project.get("chapters", []) if isinstance(project, dict) else []
            if isinstance(chapters, list) and 0 <= row < len(chapters):
                chap = chapters[row] if isinstance(chapters[row], dict) else {}
                title = str(chap.get("title", "") or "").strip()
                if title:
                    return title
        return self._adaptation_project_title(project, source_path)

    def _adaptation_source_hash(self, chap):
        return _chapter_analysis_hash(chap)

    def copy_adaptation_result(self):
        text = self.adaptation_result_preview.toPlainText().strip() if hasattr(self, "adaptation_result_preview") else ""
        if not text:
            self.set_status_tip("当前没有可复制的改编结果。")
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self.set_status_tip("改编结果已复制。")

    def open_adaptation_target_project(self):
        path = str(getattr(self, "adaptation_target_path", "") or "").strip()
        if not path or not os.path.exists(path):
            target = getattr(self, "adaptation_target_project", None)
            if isinstance(target, dict):
                chapters = target.get("chapters", []) if isinstance(target.get("chapters", []), list) else []
                has_adapted_text = any(
                    isinstance(chap, dict) and str(chap.get("text", "") or "").strip()
                    for chap in chapters
                )
                if not has_adapted_text:
                    self.set_status_tip("目标项目还没有改编正文，请先开始改编。")
                    return
                action = self.adaptation_mode_combo.currentData() if hasattr(self, "adaptation_mode_combo") else "script_to_novel"
                title = target.get("meta", {}).get("title", "") if isinstance(target.get("meta", {}), dict) else ""
                path = named_project_path(_safe_name(title) or self._adaptation_target_title_for(target, action))
                try:
                    save_project_file(path, target)
                except Exception as e:
                    QMessageBox.warning(self, "打开失败", f"目标项目保存失败：{e}")
                    return
            else:
                self.set_status_tip("当前还没有生成目标项目。")
                return
        self.open_project_requested.emit(path)
        self.set_status_tip(f"已请求打开改编目标项目：{os.path.basename(path)}")

    def _ensure_adaptation_target_project(self, source_project, action):
        title = self.adaptation_target_title.text().strip() if hasattr(self, "adaptation_target_title") else ""
        title = _safe_name(title or self._adaptation_target_title_for(source_project, action, self.adaptation_source_path)) or "改编项目"
        path = named_project_path(title)
        if os.path.exists(path):
            target = _normalize_project(load_json_file(path, _default_project()))
        else:
            target = _default_project()
            target["meta"] = deepcopy(source_project.get("meta", {}))
            target["meta"]["title"] = title
            for key in ("bible", "world_rules", "timeline", "foreshadows", "summary"):
                target[key] = source_project.get(key, "")
            target["characters"] = deepcopy(source_project.get("characters", []))
            target["lore"] = deepcopy(source_project.get("lore", []))
            target["foreshadow_items"] = deepcopy(source_project.get("foreshadow_items", []))

        source_chapters = source_project.get("chapters", []) if isinstance(source_project.get("chapters", []), list) else []
        target_chapters = target.setdefault("chapters", [])
        while len(target_chapters) < len(source_chapters):
            target_chapters.append(_new_chapter(len(target_chapters)))
        for index, source_chap in enumerate(source_chapters):
            if not isinstance(source_chap, dict):
                continue
            target_chap = target_chapters[index]
            if not isinstance(target_chap, dict):
                target_chap = {}
                target_chapters[index] = target_chap
            target_chap.setdefault("id", source_chap.get("id", ""))
            target_chap["title"] = source_chap.get("title", target_chap.get("title", f"章节 {index + 1}"))
            target_chap["unit_type"] = source_chap.get("unit_type", target_chap.get("unit_type", "chapter"))
            if not str(target_chap.get("outline", "") or "").strip():
                target_chap["outline"] = source_chap.get("outline", "")
            if not str(target_chap.get("summary", "") or "").strip():
                target_chap["summary"] = source_chap.get("summary", "")
            if not str(target_chap.get("key_facts", "") or "").strip():
                target_chap["key_facts"] = source_chap.get("key_facts", "")
            if not _normalize_name_list(target_chap.get("linked_characters", [])):
                target_chap["linked_characters"] = deepcopy(_normalize_name_list(source_chap.get("linked_characters", [])))
        target["chapters"] = target_chapters[:len(source_chapters)]
        target["meta"]["title"] = title
        return _normalize_project(target), path

    def refresh_adaptation_chapter_list(self):
        if not hasattr(self, "adaptation_chapter_list"):
            return
        try:
            source_project, source_path = self._load_adaptation_source_project()
        except Exception as e:
            self.set_status_tip(str(e))
            return
        action = self.adaptation_mode_combo.currentData() if hasattr(self, "adaptation_mode_combo") else "script_to_novel"
        target_title = self._adaptation_target_title_for(source_project, action, source_path)
        current_target_title = self.adaptation_target_title.text().strip() if hasattr(self, "adaptation_target_title") else ""
        if hasattr(self, "adaptation_target_title") and (
            not current_target_title
            or current_target_title == self.adaptation_auto_target_title
        ):
            self.adaptation_target_title.setText(target_title)
            self.adaptation_auto_target_title = target_title
        target, _path = self._ensure_adaptation_target_project(source_project, action)
        self.adaptation_source_project = source_project
        self.adaptation_source_path = source_path
        self.adaptation_target_project = target
        self.adaptation_chapter_list.blockSignals(True)
        try:
            self.adaptation_chapter_list.clear()
            source_chapters = source_project.get("chapters", [])
            target_chapters = target.get("chapters", [])
            for index, source_chap in enumerate(source_chapters if isinstance(source_chapters, list) else []):
                if not isinstance(source_chap, dict):
                    continue
                target_chap = target_chapters[index] if index < len(target_chapters) and isinstance(target_chapters[index], dict) else {}
                source_hash = self._adaptation_source_hash(source_chap)
                done = bool(str(target_chap.get("text", "") or "").strip())
                optimization_stale = str(target_chap.get("adaptation_optimization", "") or "") != self._adaptation_optimization_level()
                stale = done and (
                    str(target_chap.get("adaptation_source_hash", "") or "") != source_hash
                    or optimization_stale
                )
                status = "需更新" if stale else "已改编" if done else "未改编"
                item = QListWidgetItem(f"{index + 1}. {source_chap.get('title', '')}  ·  {status}")
                item.setData(Qt.UserRole, index)
                self.adaptation_chapter_list.addItem(item)
        finally:
            self.adaptation_chapter_list.blockSignals(False)
        if not self.adaptation_chapter_list.count():
            self.adaptation_original_preview.clear()
            self.adaptation_result_preview.clear()
            self.set_status_tip("当前源项目没有可改编章节。")
            return
        if self.adaptation_chapter_list.count() and self.adaptation_chapter_list.currentRow() < 0:
            self.adaptation_chapter_list.setCurrentRow(0)
        self.on_adaptation_chapter_selected(self.adaptation_chapter_list.currentRow())

    def on_adaptation_chapter_selected(self, row):
        if row < 0 or not self.adaptation_source_project:
            return
        chapters = self.adaptation_source_project.get("chapters", [])
        target_chapters = (self.adaptation_target_project or {}).get("chapters", [])
        if row >= len(chapters):
            return
        source_chap = chapters[row]
        target_chap = target_chapters[row] if row < len(target_chapters) and isinstance(target_chapters[row], dict) else {}
        original = "\n\n".join(
            x for x in (
                str(source_chap.get("title", "") or "").strip(),
                str(source_chap.get("outline", "") or "").strip(),
                str(source_chap.get("text", "") or "").strip(),
            )
            if x
        )
        self.adaptation_original_preview.setPlainText(original)
        self.adaptation_result_preview.setPlainText(str(target_chap.get("text", "") or ""))
        self.update_adaptation_target_title()

    def _adaptation_context(self, source_project, chapter_index, action):
        chapters = source_project.get("chapters", [])
        if chapter_index < 0 or chapter_index >= len(chapters):
            raise ValueError("请选择要改编的章节。")
        chap = chapters[chapter_index]
        meta = source_project.get("meta", {}) if isinstance(source_project.get("meta", {}), dict) else {}
        mode_name = {
            "script_to_novel": "剧本转小说",
            "novel_to_script": "小说转剧本",
            "novel_to_storyboard": "小说转分镜",
            "script_to_storyboard": "剧本转分镜",
        }.get(action, action)
        return "\n\n".join([
            "【项目基础】",
            f"书名：{meta.get('title', '')}",
            f"类型：{meta.get('genre', '')}",
            f"风格：{meta.get('style', '')}",
            f"故事核心：{meta.get('premise', '')}",
            f"小说圣经：{source_project.get('bible', '')}",
            f"世界观/规则：{source_project.get('world_rules', '')}",
            "",
            "【本次改编任务】",
            f"改编模式：{mode_name}",
            f"优化程度：{self._adaptation_optimization_label()}",
            self._adaptation_optimization_instruction(),
            "只输出改编后的正文/剧本/分镜内容，不要解释，不要写创作建议。",
            "",
            "【源章节】",
            f"标题：{chap.get('title', '')}",
            f"提纲：{chap.get('outline', '')}",
            f"正文/原稿：{chap.get('text', '')}",
            f"摘要：{chap.get('summary', '')}",
            f"关键事实：{chap.get('key_facts', '')}",
        ])

    def _adaptation_indexes_for_range(self):
        source_project = self.adaptation_source_project or {}
        target_project = self.adaptation_target_project or {}
        source_chapters = source_project.get("chapters", []) if isinstance(source_project.get("chapters", []), list) else []
        target_chapters = target_project.get("chapters", []) if isinstance(target_project.get("chapters", []), list) else []
        mode = self.adaptation_range_combo.currentText() if hasattr(self, "adaptation_range_combo") else "选中章节"
        if mode == "选中章节":
            row = self.adaptation_chapter_list.currentRow()
            return [row] if 0 <= row < len(source_chapters) else []
        out = []
        for index, source_chap in enumerate(source_chapters):
            target_chap = target_chapters[index] if index < len(target_chapters) and isinstance(target_chapters[index], dict) else {}
            if mode == "全部章节":
                out.append(index)
                continue
            source_hash = self._adaptation_source_hash(source_chap)
            done = bool(str(target_chap.get("text", "") or "").strip())
            optimization_stale = str(target_chap.get("adaptation_optimization", "") or "") != self._adaptation_optimization_level()
            stale = done and (
                str(target_chap.get("adaptation_source_hash", "") or "") != source_hash
                or optimization_stale
            )
            if not done or stale:
                out.append(index)
        return out

    def start_adaptation(self):
        if self.adaptation_worker is not None and self.adaptation_worker.isRunning():
            self.set_status_tip("项目改编正在进行，请稍等。")
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            QMessageBox.warning(self, "改编失败", error)
            return
        try:
            source_project, source_path = self._load_adaptation_source_project()
            action = self.adaptation_mode_combo.currentData() or "script_to_novel"
            self.adaptation_source_path = source_path
            target_project, target_path = self._ensure_adaptation_target_project(source_project, action)
            self.adaptation_source_project = source_project
            self.adaptation_target_project = target_project
            self.adaptation_target_path = target_path
            self.adaptation_queue = self._adaptation_indexes_for_range()
            if not self.adaptation_queue:
                QMessageBox.information(self, "项目改编", "没有需要改编的章节。")
                return
            self.adaptation_current_index = -1
            self._adaptation_stop_requested_by_user = False
            self._set_adaptation_actions_enabled(False)
            self._start_next_adaptation_item(provider, model, action)
        except Exception as e:
            QMessageBox.warning(self, "改编失败", str(e))

    def _start_next_adaptation_item(self, provider, model, action):
        if not self.adaptation_queue:
            save_project_file(self.adaptation_target_path, self.adaptation_target_project)
            self._set_adaptation_actions_enabled(True)
            self.set_status_tip(f"项目改编完成：已保存为 {os.path.basename(self.adaptation_target_path)}，可打开目标项目继续编辑。")
            return
        index = self.adaptation_queue.pop(0)
        self.adaptation_current_index = index
        context = self._adaptation_context(self.adaptation_source_project, index, action)
        self.adaptation_stream_text = ""
        self.adaptation_result_preview.clear()
        if 0 <= index < self.adaptation_chapter_list.count():
            self.adaptation_chapter_list.setCurrentRow(index)
        self.adaptation_worker = NovelWritingWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            action,
            context,
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
        )
        self.adaptation_worker.progress.connect(self.set_status_tip)
        self.adaptation_worker.chunk.connect(self.on_adaptation_chunk)
        self.adaptation_worker.result_ready.connect(self.on_adaptation_ready)
        self.adaptation_worker.failed.connect(self.on_adaptation_failed)
        self.adaptation_worker.finished.connect(self._cleanup_adaptation_worker)
        self._adaptation_provider = provider
        self._adaptation_model = model
        self._adaptation_action = action
        self.set_status_tip(f"正在改编第 {index + 1} 个章节...")
        self.adaptation_worker.start()

    def on_adaptation_chunk(self, piece):
        piece = str(piece or "")
        if not piece:
            return
        self.adaptation_stream_text += piece
        self.adaptation_result_preview.moveCursor(QTextCursor.End)
        self.adaptation_result_preview.insertPlainText(piece)
        bar = self.adaptation_result_preview.verticalScrollBar()
        bar.setValue(bar.maximum())

    def on_adaptation_ready(self, action, content):
        text = str(content or "").strip() or self.adaptation_stream_text.strip()
        index = self.adaptation_current_index
        if getattr(self, "_adaptation_stop_requested_by_user", False):
            self.adaptation_continue_next = False
            self.refresh_adaptation_chapter_list()
            if text:
                self.adaptation_result_preview.setPlainText(text)
            self.set_status_tip("项目改编已中止，当前预览未写入目标项目。")
            return
        if text and self.adaptation_target_project and index >= 0:
            target_chapters = self.adaptation_target_project.setdefault("chapters", [])
            source_chapters = self.adaptation_source_project.get("chapters", [])
            if index < len(target_chapters) and index < len(source_chapters):
                target_chap = target_chapters[index]
                source_chap = source_chapters[index]
                if not isinstance(target_chap, dict):
                    target_chap = {}
                    target_chapters[index] = target_chap
                target_chap["text"] = text
                target_chap["adaptation_mode"] = action
                target_chap["adaptation_optimization"] = self._adaptation_optimization_level()
                target_chap["adaptation_source_hash"] = self._adaptation_source_hash(source_chap)
                target_chap["adapted_at"] = now_str()
                self.adaptation_result_preview.setPlainText(text)
                save_project_file(self.adaptation_target_path, self.adaptation_target_project)
                self._schedule_project_sync()
        self.refresh_adaptation_chapter_list()
        provider = getattr(self, "_adaptation_provider", None)
        model = getattr(self, "_adaptation_model", "")
        next_action = getattr(self, "_adaptation_action", action)
        if provider:
            self._adaptation_provider = provider
            self._adaptation_model = model
            self._adaptation_action = next_action
            self.adaptation_continue_next = True

    def on_adaptation_failed(self, err):
        self._set_adaptation_actions_enabled(True)
        self.set_status_tip(f"项目改编失败：{clean_error_text(err)[:100]}")
        QMessageBox.warning(self, "项目改编失败", clean_error_text(err))

    def _cleanup_adaptation_worker(self):
        worker = self.sender()

        def cleanup():
            try:
                if self.adaptation_worker is worker:
                    self.adaptation_worker = None
                if worker is not None:
                    worker.deleteLater()
                if getattr(self, "_adaptation_stop_requested_by_user", False):
                    self._adaptation_stop_requested_by_user = False
                    self.adaptation_continue_next = False
                    self._set_adaptation_actions_enabled(True)
                    return
                if self.adaptation_continue_next:
                    self.adaptation_continue_next = False
                    provider = getattr(self, "_adaptation_provider", None)
                    model = getattr(self, "_adaptation_model", "")
                    action = getattr(self, "_adaptation_action", "script_to_novel")
                    if provider:
                        self._start_next_adaptation_item(provider, model, action)
            except Exception as e:
                log_debug("项目改编线程清理失败", e)

        QTimer.singleShot(0, cleanup)

    def stop_adaptation(self):
        worker = self.adaptation_worker
        self.adaptation_queue = []
        self.adaptation_continue_next = False
        self._adaptation_stop_requested_by_user = True
        if worker is not None:
            try:
                worker.stop()
            except Exception as e:
                log_debug("项目改编中止失败", e)
        self._set_adaptation_actions_enabled(True)
        self.set_status_tip("已请求中止项目改编。")

    def _set_adaptation_actions_enabled(self, enabled):
        if hasattr(self, "adaptation_start_btn"):
            self.adaptation_start_btn.setEnabled(bool(enabled))
        if hasattr(self, "adaptation_stop_btn"):
            self.adaptation_stop_btn.setVisible(not bool(enabled))
            self.adaptation_stop_btn.setEnabled(not bool(enabled))
