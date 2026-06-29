import os
import tempfile
import hashlib
import re
import json
from copy import deepcopy

from PySide6.QtCore import QFileSystemWatcher, QSize, QUrl, Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QPlainTextEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from .core import clean_error_text, get_provider, load_json_file, log_debug, now_str, save_config, save_json_file
from .model_bar_mixin import SimpleModelBarMixin
from .novel_import import (
    _MANUAL_PROJECT_MATERIAL_KEYS,
    _apply_import_candidates,
    _candidate_analysis_text,
    _candidate_analysis_dossier_text,
    _candidate_detail_text,
    _extract_import_candidates,
    _normalize_ai_candidates,
    _read_docx_text,
    _read_txt_text,
    _write_docx_text,
)
from .novel_storage import (
    NOVEL_DIR,
    NOVEL_DRAFT_FILE,
    clear_last_project_path,
    ensure_novel_storage,
    list_project_summaries,
    load_initial_project_data,
    named_project_path,
    remember_project_path,
    save_draft_project,
    save_named_project,
    save_project_file,
    unique_project_path,
)
from .novel_utils import (
    CHAPTER_ANALYSIS_HASH_VERSION,
    IMPORT_TYPE_OPTIONS,
    _append_text_without_duplicate_overlap,
    _build_chapter_ai_context,
    _build_manuscript_text,
    _build_search_result_text,
    _build_writing_check_text,
    _auto_classify_default_statuses,
    _character_merge_key,
    _character_list_text,
    _chapter_dedupe_key,
    _chapter_analysis_hash,
    _chapter_list_text,
    _compact_chapter_key_facts_text,
    _compact_chapter_summary_text,
    _chapter_needs_analysis,
    _chapter_tooltip,
    _dedupe_chapters,
    _dedupe_text_lines,
    _import_candidates_has_content,
    _mark_chapters_analyzed,
    _merge_text_lines_without_duplicates,
    _default_project,
    _foreshadow_list_text,
    _infer_core_character_names,
    _infer_linked_character_names,
    _is_generic_character_role_label,
    _infer_chapter_status,
    _infer_foreshadow_status,
    _lore_list_text,
    _new_character,
    _new_chapter,
    _new_foreshadow,
    _new_lore,
    _normalize_candidate_analysis_state,
    _normalize_import_candidates,
    _normalize_name_list,
    _normalize_project,
    _project_summary_record_text,
    _project_meta_text,
    _project_summary_text,
    _record_alias_keys,
    _safe_name,
    _split_chapters_from_text,
    _split_manuscript_into_target_chapters,
)
from .widgets import ProviderModelBar, WideComboBox
from .workers import EdgeTTSWorker, NovelAnalysisWorker, NovelWritingWorker

_SORT_MISSING_ORDER = 10 ** 9
_CHINESE_NUMERAL_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_NUMERAL_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def _chinese_numeral_to_int(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    total = 0
    section = 0
    number = 0
    used = False
    for ch in text:
        if ch in _CHINESE_NUMERAL_DIGITS:
            number = _CHINESE_NUMERAL_DIGITS[ch]
            used = True
        elif ch in _CHINESE_NUMERAL_UNITS:
            unit = _CHINESE_NUMERAL_UNITS[ch]
            used = True
            if unit == 10000:
                section = (section + (number or 0)) * unit
                total += section
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
        else:
            return None
    return total + section + number if used else None


def _story_order_from_text(value):
    text = str(value or "")
    if not text.strip():
        return _SORT_MISSING_ORDER
    patterns = (
        r"第\s*([一二两三四五六七八九十百千万零〇\d]+)\s*[章节回卷部集场]",
        r"\b(?:EP(?:ISODE)?\.?|E)\s*0*(\d{1,4})\b",
        r"\bChapter\s+0*(\d{1,4})\b",
        r"(^|[^\d])0*(\d{1,4})\s*[章节回卷部集场]",
    )
    hits = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            raw = match.group(match.lastindex or 1)
            number = _chinese_numeral_to_int(raw)
            if number is not None:
                hits.append(number)
    return min(hits) if hits else _SORT_MISSING_ORDER


def _record_text_for_sort(item, fields):
    item = item if isinstance(item, dict) else {}
    return "\n".join(str(item.get(field, "") or "") for field in fields)


class PlainTextEdit(QPlainTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setUndoRedoEnabled(True)

    def insertFromMimeData(self, source):
        if source is not None and source.hasText():
            self.insertPlainText(source.text())
            return
        super().insertFromMimeData(source)


class NovelWritingTab(SimpleModelBarMixin, QWidget):
    request_settings = Signal()
    MODEL_CONFIG_SECTION = "novel"
    FALLBACK_MODELS = ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"]

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self.model_worker = None
        self.analysis_worker = None
        self.writing_worker = None
        self.auto_summary_worker = None
        self.auto_outline_worker = None
        self.chapter_ai_stream_text = ""
        self.chapter_ai_action_buttons = []
        self._chapter_ai_buttons_by_action = {}
        self.candidate_action_buttons = []
        self._pending_model_reload = False
        self._loading = False
        self._dirty = False
        self._draft_saved_once = False
        self._field_refresh_pending = False
        self._opening_project = False
        self.current_project_path = ""
        self.current_project = _default_project()
        self.import_candidates = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
        self.last_import_text = ""
        self.pending_analysis_chapter_ids = []
        self.failed_analysis_chunks = []
        self._analysis_stop_requested_by_user = False
        self._chapter_ai_stop_requested_by_user = False
        self._chapter_ai_preview_action = ""
        self._chapter_ai_preview_chapter_id = ""
        self._chapter_ai_preview_is_partial = False
        self._chapter_ai_resume_prefix = ""
        self._chapter_ai_running_action = ""
        self._chapter_ai_sequence_active = False
        self._chapter_ai_sequence_chapter_id = ""
        self._chapter_ai_sequence_pending_action = ""
        self._chapter_ai_sequence_started_outline = ""
        self._chapter_ai_provider = {}
        self._chapter_ai_model = ""
        self.current_character_index = -1
        self.current_lore_index = -1
        self.current_foreshadow_index = -1
        self.current_chapter_index = -1
        self._refreshing_helpers = False
        self._pending_manuscript_refresh = False
        self.read_aloud_worker = None
        self.read_aloud_retired_workers = []
        self.read_aloud_pending_segment = None
        self.read_aloud_player = None
        self.read_aloud_audio_output = None
        self.read_aloud_speed_override = None
        self.read_aloud_scope = "current"
        self.read_aloud_finish_message = "书稿朗读完成。"
        self.read_aloud_text = ""
        self.read_aloud_file = ""
        self.read_aloud_text_hash = ""
        self.read_aloud_segments = []
        self.read_aloud_segment_index = 0
        self.read_aloud_worker_index = -1
        self.read_aloud_resume_position = 0
        self.read_aloud_elapsed_seconds = 0
        self._refresh_pending_helpers = False
        self._refresh_pending_count = 0
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(900)
        self._refresh_timer.timeout.connect(self._run_deferred_refresh)
        ensure_novel_storage()
        self._build_ui()
        self._apply_novel_ui_style()
        self._init_project_sync_watcher()
        self.refresh_import_candidate_lists()
        self._load_initial_project()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(3000)
        self._autosave_timer.timeout.connect(self._autosave_draft)
        self._autosave_timer.start()
        self.read_aloud_timer = QTimer(self)
        self.read_aloud_timer.setInterval(1000)
        self.read_aloud_timer.timeout.connect(self._update_read_aloud_scroll)

    def _init_project_sync_watcher(self):
        self._project_sync_timer = QTimer(self)
        self._project_sync_timer.setSingleShot(True)
        self._project_sync_timer.setInterval(250)
        self._project_sync_timer.timeout.connect(self._sync_project_views)
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

    def _sync_project_views(self):
        try:
            self.refresh_project_list()
        except Exception as e:
            log_debug("小说项目列表自动同步失败", e)

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        self.project_panel = self._build_project_panel()
        root.addWidget(self.project_panel, 0)

        right = QFrame()
        right.setObjectName("novel_workspace")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(6)

        header = QFrame()
        header.setObjectName("novel_header")
        header_layout_outer = QVBoxLayout(header)
        header_layout_outer.setContentsMargins(10, 8, 10, 8)
        header_layout_outer.setSpacing(6)

        header_summary_row = QHBoxLayout()
        header_summary_row.setSpacing(8)
        summary_text_layout = QVBoxLayout()
        summary_text_layout.setContentsMargins(0, 0, 0, 0)
        summary_text_layout.setSpacing(2)
        self.project_summary_label = QLabel("未命名小说")
        self.project_summary_label.setObjectName("sub_title")
        summary_text_layout.addWidget(self.project_summary_label)
        self.project_meta_label = QLabel("自动草稿 ｜字数 0 ｜章节 0 ｜人物 0")
        self.project_meta_label.setObjectName("hint")
        self.project_meta_label.setFixedHeight(16)
        summary_text_layout.addWidget(self.project_meta_label)
        header_summary_row.addLayout(summary_text_layout, 1)
        self.project_info_toggle_btn = QPushButton("项目信息")
        self.project_info_toggle_btn.setObjectName("ghost")
        self.project_info_toggle_btn.clicked.connect(self.toggle_project_info_panel)
        header_summary_row.addWidget(self.project_info_toggle_btn)
        header_layout_outer.addLayout(header_summary_row)

        self.project_info_body = QFrame()
        header_layout = QGridLayout(self.project_info_body)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setHorizontalSpacing(10)
        header_layout.setVerticalSpacing(6)

        self.title_edit = QLineEdit()
        self.genre_edit = QLineEdit()
        self.style_edit = QLineEdit()
        self.pov_combo = WideComboBox()
        self.pov_combo.addItems(["第一人称", "第三人称", "多视角"])
        self.target_words_edit = QLineEdit()
        self.status_combo = WideComboBox()
        self.status_combo.addItems(["草稿", "连载中", "已完结", "修订中"])
        self.premise_edit = PlainTextEdit()
        self.premise_edit.setFixedHeight(42)
        self.premise_edit.setPlaceholderText("一句话说明主角、目标、冲突和故事承诺。")

        for w in (self.title_edit, self.genre_edit, self.style_edit, self.target_words_edit):
            w.textChanged.connect(self._mark_dirty)
        self.pov_combo.currentTextChanged.connect(self._mark_dirty)
        self.status_combo.currentTextChanged.connect(self._mark_dirty)
        self.premise_edit.textChanged.connect(self._mark_dirty)

        for col in range(6):
            header_layout.setColumnStretch(col, 1 if col % 2 else 0)

        def add_field(row, col, label, widget):
            lab = QLabel(label)
            header_layout.addWidget(lab, row, col)
            header_layout.addWidget(widget, row, col + 1)

        add_field(0, 0, "书名", self.title_edit)
        add_field(0, 2, "类型", self.genre_edit)
        add_field(0, 4, "风格", self.style_edit)
        add_field(1, 0, "叙事人称", self.pov_combo)
        add_field(1, 2, "项目总字数（万字）", self.target_words_edit)
        add_field(1, 4, "状态", self.status_combo)
        header_layout.addWidget(QLabel("故事核心"), 2, 0)
        header_layout.addWidget(self.premise_edit, 2, 1, 1, 5)
        header_layout_outer.addWidget(self.project_info_body)

        right_layout.addWidget(header)

        self.ai_settings_box = QFrame()
        self.ai_settings_box.setObjectName("novel_tool_strip")
        ai_settings_layout = QVBoxLayout(self.ai_settings_box)
        ai_settings_layout.setContentsMargins(8, 6, 8, 6)
        ai_settings_layout.setSpacing(6)

        self.ai_settings_header = QFrame()
        ai_settings_header = QHBoxLayout(self.ai_settings_header)
        ai_settings_header.setContentsMargins(0, 0, 0, 0)
        self.ai_settings_summary = QLabel("AI：未选择")
        self.ai_settings_summary.setObjectName("hint")
        ai_settings_header.addWidget(self.ai_settings_summary, 1)
        self.ai_settings_toggle_btn = QPushButton("AI 设置")
        self.ai_settings_toggle_btn.setObjectName("ghost")
        self.ai_settings_toggle_btn.setToolTip("展开小说写作使用的 AI 厂商和模型")
        self.ai_settings_toggle_btn.clicked.connect(self.toggle_ai_settings_panel)
        ai_settings_header.addWidget(self.ai_settings_toggle_btn)
        ai_settings_layout.addWidget(self.ai_settings_header)

        self.ai_settings_body = QFrame()
        ai_settings_body_layout = QHBoxLayout(self.ai_settings_body)
        ai_settings_body_layout.setContentsMargins(0, 0, 0, 0)
        ai_settings_body_layout.setSpacing(8)
        self.bar = ProviderModelBar()
        ai_settings_body_layout.addWidget(self.bar, 1)
        self.ai_settings_collapse_btn = QPushButton("收起")
        self.ai_settings_collapse_btn.setObjectName("ghost")
        self.ai_settings_collapse_btn.setToolTip("收起 AI 设置栏")
        self.ai_settings_collapse_btn.clicked.connect(lambda: self.set_ai_settings_expanded(False))
        ai_settings_body_layout.addWidget(self.ai_settings_collapse_btn)
        ai_settings_layout.addWidget(self.ai_settings_body)
        right_layout.addWidget(self.ai_settings_box)
        self.bar.provider_changed.connect(self.on_provider_changed)
        self.bar.model_changed.connect(self.on_model_changed)
        self.bar.refresh_clicked.connect(self.load_models)
        self.bar.settings_clicked.connect(self.request_settings.emit)
        self.bar.settings_btn.setVisible(True)
        self.refresh_providers()
        self.refresh_ai_settings_summary()
        QTimer.singleShot(0, self.load_models)
        self.set_ai_settings_expanded(False)
        self.set_project_info_expanded(False)

        content_area = QFrame()
        content_layout = QHBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("novel_nav")
        self.nav_list.setFixedWidth(104)
        self.nav_list.setSpacing(2)
        self.nav_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        content_layout.addWidget(self.nav_list, 0)

        self.tabs = QStackedWidget()
        self.page_indexes = {}
        pages = [
            ("圣经", "小说圣经", self._build_bible_tab()),
            ("人物", "人物卡", self._build_characters_tab()),
            ("设定", "设定库", self._build_lore_tab()),
            ("章节", "章节", self._build_chapters_tab()),
            ("时间线", "时间线", self._build_simple_text_tab("timeline_edit", "时间线")),
            ("伏笔", "伏笔", self._build_foreshadow_tab()),
            ("摘要", "摘要 / 日志", self._build_simple_text_tab("summary_edit", "摘要 / 日志")),
            ("书稿", "完整书稿", self._build_manuscript_tab()),
            ("检查", "写作检查", self._build_check_tab()),
            ("搜索", "全局搜索", self._build_search_tab()),
            ("候选", "导入候选", self._build_import_candidates_tab()),
        ]
        for short_name, full_name, page in pages:
            page_index = self.tabs.addWidget(page)
            self.page_indexes[short_name] = page_index
            item = QListWidgetItem(short_name)
            item.setToolTip(full_name)
            item.setData(Qt.UserRole, page_index)
            self.nav_list.addItem(item)
        self.nav_list.setCurrentRow(0)
        content_layout.addWidget(self.tabs, 1)
        right_layout.addWidget(content_area, 1)

        root.addWidget(right, 1)
        self.set_project_panel_expanded(True)

    def _build_project_panel(self):
        box = QFrame()
        box.setObjectName("novel_project_panel")
        box.setMinimumWidth(280)
        box.setMaximumWidth(330)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("小说项目")
        title.setObjectName("sub_title")
        title_row.addWidget(title)
        layout.addLayout(title_row)

        layout.addLayout(self._project_button_grid((
            ("新建", self.new_project, "新建一个小说项目，当前内容会先自动保存"),
            ("保存项目", self.save_current_project, "保存当前小说项目"),
        ), columns=2))

        layout.addLayout(self._project_button_grid((
            ("删除", self.delete_selected_project, "删除左侧列表中选中的小说项目"),
            ("清空草稿", self.clear_current_draft, "清空当前自动草稿和编辑区，不删除已保存项目"),
        ), columns=2))

        layout.addLayout(self._project_button_grid((
            ("导入 Word", self.import_word_script, "从 Word 文档导入小说或剧本正文"),
            ("导入 TXT", self.import_txt_script, "从 TXT 文本导入小说或剧本正文"),
            ("导入项目", self.import_project, "导入小说项目 JSON 文件"),
            ("导出项目", self.export_project, "导出当前小说项目 JSON 文件"),
        ), columns=2))

        self.project_list = QListWidget()
        self.project_list.itemClicked.connect(self._open_selected_project_item)
        layout.addWidget(self.project_list, 1)

        self.project_hint = QLabel("单击列表可打开已保存小说。")
        self.project_hint.setObjectName("hint")
        self.project_hint.setWordWrap(True)
        layout.addWidget(self.project_hint)

        self.status_label = QLabel("")
        self.status_label.setObjectName("hint")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        return box

    def set_project_panel_expanded(self, expanded):
        if not hasattr(self, "project_panel"):
            return
        self.project_panel.setVisible(True)

    def toggle_project_panel(self):
        self.set_project_panel_expanded(True)

    def _apply_novel_ui_style(self):
        self.setStyleSheet("""
        QFrame#novel_workspace {
            background-color: transparent;
            border: none;
        }
        QFrame#novel_project_panel,
        QFrame#novel_header,
        QFrame#novel_tool_strip,
        QFrame#novel_detail_panel,
        QFrame#novel_column_card {
            background-color: #181a20;
            border: 1px solid #242730;
            border-radius: 8px;
        }
        QFrame#novel_tool_strip {
            background-color: #17191f;
        }
        QListWidget#novel_nav {
            background-color: transparent;
            border: none;
            padding: 2px;
        }
        QListWidget#novel_nav::item {
            padding: 8px 9px;
            margin: 1px 0;
            border-radius: 6px;
        }
        QListWidget#novel_nav::item:selected {
            background-color: #263246;
            color: #ffffff;
        }
        QListWidget#novel_nav::item:hover {
            background-color: #222734;
        }
        """)

    def set_ai_settings_expanded(self, expanded):
        if not hasattr(self, "ai_settings_body"):
            return
        expanded = bool(expanded)
        self.ai_settings_body.setVisible(expanded)
        if hasattr(self, "ai_settings_header"):
            self.ai_settings_header.setVisible(not expanded)
        if hasattr(self, "ai_settings_toggle_btn"):
            self.ai_settings_toggle_btn.setText("AI 设置")

    def toggle_ai_settings_panel(self):
        if hasattr(self, "ai_settings_body"):
            self.set_ai_settings_expanded(not self.ai_settings_body.isVisible())

    def refresh_ai_settings_summary(self):
        if not hasattr(self, "ai_settings_summary"):
            return
        provider_id = self.bar.current_provider_id() if hasattr(self, "bar") else ""
        model = self.bar.current_model() if hasattr(self, "bar") else ""
        provider = get_provider(self.config, provider_id)
        provider_name = provider.get("name", "") if provider else ""
        if provider_name and model:
            text = f"AI：{provider_name} · {model}"
        elif provider_name:
            text = f"AI：{provider_name} · 未选择模型"
        else:
            text = "AI：未选择"
        self.ai_settings_summary.setText(text)

    def _read_aloud_rate_options(self):
        return [
            ("0.8x", "-20%"),
            ("0.9x", "-10%"),
            ("1.0x", "+0%"),
            ("1.1x", "+10%"),
            ("1.2x", "+20%"),
            ("1.3x", "+30%"),
            ("1.5x", "+50%"),
        ]

    def _read_aloud_rate_from_config(self):
        rate = str(self.config.setdefault("novel", {}).get("read_aloud_rate", "+0%") or "+0%").strip()
        valid = {value for _label, value in self._read_aloud_rate_options()}
        return rate if rate in valid else "+0%"

    def _set_read_aloud_rate(self, rate, persist=True):
        rate = str(rate or "+0%").strip()
        valid = {value for _label, value in self._read_aloud_rate_options()}
        if rate not in valid:
            rate = "+0%"
        self.read_aloud_speed_override = rate
        if hasattr(self, "read_aloud_rate_combo"):
            idx = self.read_aloud_rate_combo.findData(rate)
            if idx >= 0:
                self.read_aloud_rate_combo.blockSignals(True)
                try:
                    self.read_aloud_rate_combo.setCurrentIndex(idx)
                finally:
                    self.read_aloud_rate_combo.blockSignals(False)
        if persist:
            self.config.setdefault("novel", {})["read_aloud_rate"] = rate
            try:
                save_config(self.config)
            except Exception as e:
                log_debug("小说朗读语速保存失败", e)
        if getattr(self, "read_aloud_player", None) is not None:
            try:
                rate_map = {value: float(label.rstrip("x")) for label, value in self._read_aloud_rate_options()}
                self.read_aloud_player.setPlaybackRate(rate_map.get(rate, 1.0))
            except Exception:
                pass

    def _on_read_aloud_rate_changed(self, _text):
        if hasattr(self, "read_aloud_rate_combo"):
            rate = str(self.read_aloud_rate_combo.currentData() or "+0%").strip()
            self._set_read_aloud_rate(rate, persist=True)
            self.set_status_tip(f"朗读语速已设为 {self.read_aloud_rate_combo.currentText()}。")

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

    def on_provider_changed(self, pid):
        SimpleModelBarMixin.on_provider_changed(self, pid)
        self.refresh_ai_settings_summary()

    def on_model_changed(self, model):
        SimpleModelBarMixin.on_model_changed(self, model)
        self.refresh_ai_settings_summary()

    def on_models_loaded(self, models):
        SimpleModelBarMixin.on_models_loaded(self, models)
        self.refresh_ai_settings_summary()

    def on_models_failed(self, err):
        SimpleModelBarMixin.on_models_failed(self, err)
        self.refresh_ai_settings_summary()

    def _scroll_page(self, widget):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setWidget(widget)
        return area

    def _setup_form(self, form):
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setFormAlignment(Qt.AlignTop)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def set_project_info_expanded(self, expanded):
        if not hasattr(self, "project_info_body"):
            return
        expanded = bool(expanded)
        self.project_info_body.setVisible(expanded)
        if hasattr(self, "project_info_toggle_btn"):
            self.project_info_toggle_btn.setText("收起信息" if expanded else "项目信息")

    def toggle_project_info_panel(self):
        if hasattr(self, "project_info_body"):
            self.set_project_info_expanded(not self.project_info_body.isVisible())

    def refresh_project_summary_label(self):
        if not hasattr(self, "project_summary_label"):
            return
        self.project_summary_label.setText(_project_summary_text(self.current_project, {
            "title": self.title_edit.text(),
            "genre": self.genre_edit.text(),
            "target_words": self.target_words_edit.text(),
            "status": self.status_combo.currentText(),
        }))

    def _wide_field(self, widget, min_width=360):
        widget.setMinimumWidth(min_width)
        widget.setSizePolicy(QSizePolicy.Expanding, widget.sizePolicy().verticalPolicy())
        return widget

    def _expand_text_edit(self, widget, min_height=90):
        widget.setMinimumHeight(min_height)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return widget

    def _ghost_button(self, text, callback=None, tooltip=""):
        btn = QPushButton(text)
        btn.setObjectName("ghost")
        if tooltip:
            btn.setToolTip(tooltip)
        if callback:
            btn.clicked.connect(callback)
        return btn

    def _button_row(self, actions):
        row = QHBoxLayout()
        for action in actions:
            text, callback = action[:2]
            tooltip = action[2] if len(action) > 2 else ""
            row.addWidget(self._ghost_button(text, callback, tooltip))
        return row

    def _button_grid(self, actions, columns=3):
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for index, action in enumerate(actions):
            text, callback = action[:2]
            tooltip = action[2] if len(action) > 2 else ""
            grid.addWidget(self._ghost_button(text, callback, tooltip), index // columns, index % columns)
        return grid

    def _project_button_grid(self, actions, columns=2):
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, action in enumerate(actions):
            text, callback = action[:2]
            tooltip = action[2] if len(action) > 2 else ""
            btn = self._ghost_button(text, callback, tooltip)
            btn.setMinimumWidth(96)
            grid.addWidget(btn, index // columns, index % columns)
        return grid

    def _action_button_grid(self, actions, columns=3, button_store=None):
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for index, action in enumerate(actions):
            text, callback = action[:2]
            primary = bool(action[2]) if len(action) > 2 else False
            btn = self._action_button(text, callback, primary)
            grid.addWidget(btn, index // columns, index % columns)
            if button_store is not None:
                button_store.append(btn)
        return grid

    def _action_button(self, text, callback, primary=False):
        btn = QPushButton(text)
        btn.setObjectName("primary" if primary else "ghost")
        btn.clicked.connect(callback)
        return btn

    def _plain_frame(self):
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        return frame, layout

    def _set_text_without_signals(self, widget, text):
        widget.blockSignals(True)
        try:
            widget.setPlainText(text)
        finally:
            widget.blockSignals(False)

    def _set_line_text_without_signals(self, widget, text):
        widget.blockSignals(True)
        try:
            widget.setText(text)
        finally:
            widget.blockSignals(False)

    def _project_title(self):
        meta = self.current_project.get("meta", {}) if isinstance(self.current_project, dict) else {}
        return str(meta.get("title") or self.title_edit.text() or "未命名小说").strip() or "未命名小说"

    def _get_export_path(self, dialog_title, suggested_name, default_ext, file_filter):
        safe_title = _safe_name(suggested_name) or "novel"
        default_name = f"{safe_title}.{default_ext.lstrip('.')}"
        path, _ = QFileDialog.getSaveFileName(self, dialog_title, default_name, file_filter)
        if not path:
            return ""
        ext = "." + default_ext.lstrip(".")
        if not os.path.splitext(path)[1]:
            path += ext
        return path

    def _get_open_path(self, dialog_title, file_filter):
        path, _ = QFileDialog.getOpenFileName(self, dialog_title, "", file_filter)
        return path or ""

    def _get_combo_choice(self, title, label, options, current_index=0):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        lab = QLabel(label)
        lab.setWordWrap(True)
        layout.addWidget(lab)
        combo = WideComboBox()
        combo.addItems([str(x) for x in options])
        if options:
            combo.setCurrentIndex(max(0, min(int(current_index or 0), len(options) - 1)))
        layout.addWidget(combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return "", False
        return combo.currentText(), True

    def _on_nav_changed(self, row):
        if not hasattr(self, "tabs") or row < 0:
            return
        item = self.nav_list.item(row) if hasattr(self, "nav_list") else None
        page_index = item.data(Qt.UserRole) if item is not None else row
        if isinstance(page_index, int):
            self.tabs.setCurrentIndex(page_index)

    def _nav_row_for_page_index(self, page_index):
        if not hasattr(self, "nav_list"):
            return -1
        for row in range(self.nav_list.count()):
            item = self.nav_list.item(row)
            if item is not None and item.data(Qt.UserRole) == page_index:
                return row
        return -1

    def _two_pane_tab(self, left, right, sizes=(260, 760)):
        box = QFrame()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes(list(sizes))
        layout.addWidget(splitter, 1)
        return box

    def _build_bible_tab(self):
        box = QFrame()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        bible_box = QFrame()
        bible_layout = QVBoxLayout(bible_box)
        bible_layout.setContentsMargins(0, 0, 0, 6)
        bible_layout.setSpacing(6)
        self.bible_edit = PlainTextEdit()
        self.bible_edit.setMinimumHeight(120)
        self.bible_edit.setPlaceholderText("核心设定、主题、主线矛盾、结局方向、禁用设定等。")
        self.bible_edit.textChanged.connect(self._mark_dirty)
        bible_layout.addWidget(QLabel("小说圣经"))
        bible_layout.addWidget(self.bible_edit, 1)

        world_box = QFrame()
        world_layout = QVBoxLayout(world_box)
        world_layout.setContentsMargins(0, 6, 0, 0)
        world_layout.setSpacing(6)
        self.world_rules_edit = PlainTextEdit()
        self.world_rules_edit.setMinimumHeight(120)
        self.world_rules_edit.setPlaceholderText("世界运行规则、势力结构、能力限制、时代背景、地点规则等。")
        self.world_rules_edit.textChanged.connect(self._mark_dirty)
        world_layout.addWidget(QLabel("世界观 / 规则"))
        world_layout.addWidget(self.world_rules_edit, 1)

        splitter.addWidget(bible_box)
        splitter.addWidget(world_box)
        splitter.setSizes([1, 1])
        layout.addWidget(splitter, 1)
        return box

    def _build_simple_text_tab(self, attr_name, title):
        box = QFrame()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel(title))
        header.addStretch()
        layout.addLayout(header)
        edit = PlainTextEdit()
        placeholder = {
            "timeline_edit": "按时间顺序记录关键事件，避免长篇写作前后矛盾。",
            "foreshadows_edit": "记录埋下的伏笔、触发条件、回收章节和当前状态。",
            "summary_edit": "记录阶段总结、已发生事实、后续调整日志。",
        }.get(attr_name, "")
        edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(self._mark_dirty)
        setattr(self, attr_name, edit)
        layout.addWidget(edit, 1)
        return box

    def _build_characters_tab(self):
        left, left_layout = self._plain_frame()
        self.character_list = QListWidget()
        self.character_list.currentRowChanged.connect(self._on_character_selected)
        left_layout.addWidget(self.character_list, 1)
        left_layout.addLayout(self._button_row((("新增", self.add_character), ("删除", self.delete_character))))

        right = QFrame()
        form = QFormLayout(right)
        self._setup_form(form)
        self.char_name = QLineEdit()
        self.char_role = QLineEdit()
        self.char_goal = QLineEdit()
        self.char_secret = QLineEdit()
        self.char_voice = QLineEdit()
        self.char_name.setPlaceholderText("填写人物姓名，左侧列表会自动更新。")
        self.char_role.setPlaceholderText("例如：国公府世子、女主、反派、师父。")
        self.char_goal.setPlaceholderText("这个人物最想得到什么，或者最想避免什么。")
        self.char_secret.setPlaceholderText("暂时不能让读者或其他角色知道的隐藏信息。")
        self.char_voice.setPlaceholderText("说话习惯，比如毒舌、文雅、话少、爱打岔。")
        for w in (self.char_name, self.char_role, self.char_goal, self.char_secret, self.char_voice):
            self._wide_field(w)
        self.char_notes = PlainTextEdit()
        self._wide_field(self.char_notes)
        self._expand_text_edit(self.char_notes, 110)
        self.char_notes.setPlaceholderText("人物弧光、关系、外貌、习惯、禁忌、出场线索等。")
        for w in (self.char_name, self.char_role, self.char_goal, self.char_secret, self.char_voice):
            w.textChanged.connect(self._mark_character_dirty)
        self.char_notes.textChanged.connect(self._mark_character_dirty)
        form.addRow("姓名", self.char_name)
        form.addRow("身份", self.char_role)
        form.addRow("人物目标", self.char_goal)
        form.addRow("隐藏秘密", self.char_secret)
        form.addRow("语言风格", self.char_voice)
        form.addRow("备注", self.char_notes)

        return self._two_pane_tab(left, right)

    def _build_lore_tab(self):
        left, left_layout = self._plain_frame()
        self.lore_list = QListWidget()
        self.lore_list.currentRowChanged.connect(self._on_lore_selected)
        left_layout.addWidget(self.lore_list, 1)
        left_layout.addLayout(self._button_row((("新增", self.add_lore), ("删除", self.delete_lore))))

        right = QFrame()
        form = QFormLayout(right)
        self._setup_form(form)
        self.lore_name = QLineEdit()
        self.lore_type = WideComboBox()
        self.lore_type.addItems(["地点", "势力", "物品", "规则", "术语", "事件", "其他"])
        self.lore_desc = PlainTextEdit()
        self._wide_field(self.lore_name)
        self._wide_field(self.lore_type)
        self._wide_field(self.lore_desc)
        self.lore_desc.setPlaceholderText("记录这个设定的来源、规则、限制、关联人物和后续用途。")
        self.lore_name.setPlaceholderText("例如：国公府、青云宗、虎符、灵根规则。")
        self.lore_name.textChanged.connect(self._mark_lore_dirty)
        self.lore_type.currentTextChanged.connect(self._mark_lore_dirty)
        self.lore_desc.textChanged.connect(self._mark_lore_dirty)
        form.addRow("名称", self.lore_name)
        form.addRow("类型", self.lore_type)
        form.addRow("说明", self.lore_desc)

        return self._two_pane_tab(left, right)

    def _build_foreshadow_tab(self):
        left, left_layout = self._plain_frame()
        self.foreshadow_list = QListWidget()
        self.foreshadow_list.currentRowChanged.connect(self._on_foreshadow_selected)
        left_layout.addWidget(self.foreshadow_list, 1)
        left_layout.addLayout(self._button_row((("新增", self.add_foreshadow), ("删除", self.delete_foreshadow))))

        right = QFrame()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        form_box = QFrame()
        form = QFormLayout(form_box)
        self._setup_form(form)
        self.foreshadow_name = QLineEdit()
        self.foreshadow_status = WideComboBox()
        self.foreshadow_status.addItems(["未埋", "已埋", "已回收", "废弃"])
        self.foreshadow_setup = QLineEdit()
        self.foreshadow_payoff = QLineEdit()
        self.foreshadow_desc = PlainTextEdit()
        for w in (
            self.foreshadow_name,
            self.foreshadow_status,
            self.foreshadow_setup,
            self.foreshadow_payoff,
            self.foreshadow_desc,
        ):
            self._wide_field(w)
        self.foreshadow_desc.setPlaceholderText("写清这个伏笔是什么、读者看到什么、真正含义是什么。")
        self.foreshadow_name.setPlaceholderText("例如：虎符失踪、世子装傻、旧案真凶。")
        self.foreshadow_setup.setPlaceholderText("例如：第3章")
        self.foreshadow_payoff.setPlaceholderText("例如：第28章")
        self.foreshadow_name.textChanged.connect(self._mark_foreshadow_dirty)
        self.foreshadow_status.currentTextChanged.connect(self._mark_foreshadow_dirty)
        self.foreshadow_setup.textChanged.connect(self._mark_foreshadow_dirty)
        self.foreshadow_payoff.textChanged.connect(self._mark_foreshadow_dirty)
        self.foreshadow_desc.textChanged.connect(self._mark_foreshadow_dirty)
        form.addRow("名称", self.foreshadow_name)
        form.addRow("状态", self.foreshadow_status)
        form.addRow("埋设章节", self.foreshadow_setup)
        form.addRow("回收章节", self.foreshadow_payoff)
        form.addRow("说明", self.foreshadow_desc)
        right_layout.addWidget(form_box, 2)

        note_label = QLabel("伏笔备注")
        note_label.setObjectName("field_label")
        right_layout.addWidget(note_label)
        self.foreshadows_edit = PlainTextEdit()
        self.foreshadows_edit.setPlaceholderText("保留自由备注；结构化伏笔建议填到上面的列表里。")
        self.foreshadows_edit.textChanged.connect(self._mark_dirty)
        right_layout.addWidget(self.foreshadows_edit, 1)

        return self._two_pane_tab(left, right)

    def _build_chapters_tab(self):
        left, left_layout = self._plain_frame()
        self.chapter_list = QListWidget()
        self.chapter_list.currentRowChanged.connect(self._on_chapter_selected)
        left_layout.addWidget(self.chapter_list, 1)
        left_layout.addLayout(self._button_grid((
            ("新增", self.add_chapter),
            ("上移", self.move_chapter_up),
            ("下移", self.move_chapter_down),
            ("删除", self.delete_chapter),
            ("拆分导出", self.split_current_chapter, "按整本小说正文重切为约定字数的章节并导出 Word"),
        ), columns=3))

        right = QFrame()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        form_box = QFrame()
        form = QFormLayout(form_box)
        self._setup_form(form)
        self.chapter_title = QLineEdit()
        self.chapter_status = WideComboBox()
        self.chapter_status.addItems(["大纲", "写作中", "已完成", "待重写"])
        self.chapter_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.chapter_draft_words = QLineEdit()
        self.chapter_draft_words.setPlaceholderText("例如：1500、3000、5000字；只影响扩写正文。")
        self.chapter_draft_words.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.chapter_linked = QLineEdit()
        linked_box = QFrame()
        linked_layout = QHBoxLayout(linked_box)
        linked_layout.setContentsMargins(0, 0, 0, 0)
        linked_layout.setSpacing(8)
        linked_layout.addWidget(self.chapter_linked, 1)
        linked_pick_btn = self._ghost_button("填入人物", self.pick_linked_character)
        linked_layout.addWidget(linked_pick_btn)

        self.chapter_outline = PlainTextEdit()
        self._expand_text_edit(self.chapter_outline, 90)
        self.chapter_outline.setPlaceholderText("本章目标、冲突、转折、结尾钩子。")
        self.chapter_text = PlainTextEdit()
        self._expand_text_edit(self.chapter_text, 180)
        self.chapter_text.setPlaceholderText("正文草稿。")
        self.chapter_summary = PlainTextEdit()
        self._expand_text_edit(self.chapter_summary, 80)
        self.chapter_summary.setPlaceholderText("简短总结本章发生了什么。")
        self.chapter_key_facts = PlainTextEdit()
        self._expand_text_edit(self.chapter_key_facts, 80)
        self.chapter_key_facts.setPlaceholderText("只记录后续必须继承的关键事实。")
        for w in (
            self.chapter_title,
            self.chapter_outline,
            self.chapter_text,
            self.chapter_summary,
            self.chapter_key_facts,
            self.chapter_linked,
        ):
            self._wide_field(w)
        self.chapter_status.setMinimumWidth(84)
        self.chapter_status.setMaximumWidth(160)
        self.chapter_draft_words.setMinimumWidth(220)
        self.chapter_draft_words.setMaximumWidth(360)

        self.chapter_title.textChanged.connect(self._mark_chapter_dirty)
        self.chapter_status.currentTextChanged.connect(self._mark_chapter_dirty)
        self.chapter_draft_words.textChanged.connect(self._mark_chapter_dirty)
        self.chapter_outline.textChanged.connect(self._mark_chapter_dirty)
        self.chapter_text.textChanged.connect(self._mark_chapter_dirty)
        self.chapter_summary.textChanged.connect(self._mark_chapter_dirty)
        self.chapter_key_facts.textChanged.connect(self._mark_chapter_dirty)
        self.chapter_linked.textChanged.connect(self._mark_chapter_dirty)

        form.addRow("章节标题", self.chapter_title)
        status_row = QFrame()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        self.chapter_status.setMinimumWidth(76)
        self.chapter_status.setMaximumWidth(112)
        status_layout.addWidget(self.chapter_status, 0)
        draft_label = QLabel("扩写字数（字）")
        draft_label.setObjectName("field_label")
        status_layout.addWidget(draft_label)
        self.chapter_draft_words.setMinimumWidth(120)
        self.chapter_draft_words.setMaximumWidth(180)
        status_layout.addWidget(self.chapter_draft_words, 0)
        status_layout.addStretch(1)
        form.addRow("状态", status_row)
        form.addRow("关联人物", linked_box)
        right_layout.addWidget(form_box, 0)

        self.chapter_content_tabs = QTabWidget()
        self.chapter_content_tabs.addTab(self.chapter_outline, "章节提纲")
        self.chapter_content_tabs.addTab(self.chapter_text, "正文")
        summary_box = QFrame()
        summary_layout = QVBoxLayout(summary_box)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(8)
        summary_label = QLabel("本章摘要")
        summary_label.setObjectName("field_label")
        summary_layout.addWidget(summary_label)
        summary_layout.addWidget(self.chapter_summary, 1)
        key_label = QLabel("本章需继承的关键事实")
        key_label.setObjectName("field_label")
        summary_layout.addWidget(key_label)
        summary_layout.addWidget(self.chapter_key_facts, 1)
        self.chapter_content_tabs.addTab(summary_box, "摘要/事实")
        right_layout.addWidget(self.chapter_content_tabs, 1)

        ai_box = QFrame()
        ai_box.setObjectName("novel_tool_strip")
        ai_layout = QVBoxLayout(ai_box)
        ai_layout.setContentsMargins(8, 8, 8, 8)
        ai_layout.setSpacing(6)

        ai_top = QHBoxLayout()
        ai_title = QLabel("AI 辅助")
        ai_title.setObjectName("field_label")
        ai_top.addWidget(ai_title)
        ai_top.addStretch()
        for text, action in (
            ("扩写正文并补提纲和摘要", "draft"),
        ):
            btn = self._ghost_button(text)
            btn.setToolTip("先扩写正文，再根据实际正文补提纲和摘要/关键事实")
            btn.clicked.connect(lambda _checked=False, a=action: self.run_chapter_ai_action(a))
            ai_top.addWidget(btn)
            self.chapter_ai_action_buttons.append(btn)
            self._chapter_ai_buttons_by_action[action] = btn
        self.chapter_ai_stop_btn = QPushButton("中止")
        self.chapter_ai_stop_btn.setObjectName("danger")
        self.chapter_ai_stop_btn.setToolTip("中止当前 AI 辅助生成")
        self.chapter_ai_stop_btn.setVisible(False)
        self.chapter_ai_stop_btn.clicked.connect(self.stop_chapter_ai_action)
        ai_top.addWidget(self.chapter_ai_stop_btn)
        ai_layout.addLayout(ai_top)

        self.chapter_ai_body = QFrame()
        ai_body_layout = QVBoxLayout(self.chapter_ai_body)
        ai_body_layout.setContentsMargins(0, 0, 0, 0)
        ai_body_layout.setSpacing(8)

        self.chapter_ai_preview = PlainTextEdit()
        self.chapter_ai_preview.setMinimumHeight(145)
        self.chapter_ai_preview.setPlaceholderText("AI 结果会显示在这里，生成完成后自动应用到当前章节。")
        ai_body_layout.addWidget(self.chapter_ai_preview, 1)

        ai_layout.addWidget(self.chapter_ai_body, 1)
        self.set_chapter_ai_panel_expanded(True)
        right_layout.addWidget(ai_box, 0)

        return self._two_pane_tab(left, right)

    def _build_manuscript_tab(self):
        box = QFrame()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        row = QHBoxLayout()
        title = QLabel("完整书稿")
        title.setObjectName("field_label")
        row.addWidget(title)
        row.addStretch()
        self.read_aloud_rate_combo = WideComboBox()
        for label, value in self._read_aloud_rate_options():
            self.read_aloud_rate_combo.addItem(label, value)
        self.read_aloud_rate_combo.setToolTip("控制 Edge TTS 朗读语速。")
        self.read_aloud_rate_combo.setFixedWidth(92)
        self.read_aloud_rate_combo.currentTextChanged.connect(self._on_read_aloud_rate_changed)
        self._set_read_aloud_rate(self._read_aloud_rate_from_config(), persist=False)
        row.addWidget(QLabel("语速"))
        row.addWidget(self.read_aloud_rate_combo)
        self.read_aloud_scope_combo = WideComboBox()
        self.read_aloud_scope_combo.setToolTip("选择朗读完整书稿或指定章节。")
        self.read_aloud_scope_combo.setMinimumWidth(190)
        self.read_aloud_scope_combo.currentIndexChanged.connect(self._on_read_aloud_scope_changed)
        row.addWidget(QLabel("朗读范围"))
        row.addWidget(self.read_aloud_scope_combo)
        self._refresh_read_aloud_scope_combo()
        for text, target in (
            ("刷新汇总", self.refresh_manuscript),
            ("朗读", self.start_read_aloud),
            ("停止朗读", self.stop_read_aloud),
            ("复制全文", self.copy_manuscript),
            ("导出 TXT", self.export_manuscript_txt),
            ("导出 Word", self.export_manuscript_docx),
        ):
            btn = self._ghost_button(text, target)
            if text == "停止朗读":
                self.read_aloud_stop_btn = btn
                btn.setObjectName("danger")
                btn.setVisible(False)
            elif text == "朗读":
                self.read_aloud_btn = btn
            row.addWidget(btn)
        layout.addLayout(row)

        self.manuscript_edit = PlainTextEdit()
        self.manuscript_edit.setReadOnly(True)
        self.manuscript_edit.setPlaceholderText("章节正文会在这里按顺序汇总。")
        layout.addWidget(self.manuscript_edit, 1)
        return box

    def _build_check_tab(self):
        box = QFrame()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        row = QHBoxLayout()
        title = QLabel("写作检查")
        title.setObjectName("field_label")
        row.addWidget(title)
        row.addStretch()
        row.addWidget(self._ghost_button("刷新检查", self.refresh_writing_check))
        layout.addLayout(row)

        self.check_edit = PlainTextEdit()
        self.check_edit.setReadOnly(True)
        self.check_edit.setPlaceholderText("这里会显示当前项目的基础问题检查。")
        layout.addWidget(self.check_edit, 1)
        return box

    def _build_search_tab(self):
        box = QFrame()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入关键词，搜索人物、设定、章节、伏笔和小说资料。")
        self.search_input.returnPressed.connect(self.run_global_search)
        row.addWidget(self.search_input, 1)

        row.addWidget(self._ghost_button("搜索", self.run_global_search))
        row.addWidget(self._ghost_button("清空", self.clear_global_search))
        layout.addLayout(row)

        self.search_result_edit = PlainTextEdit()
        self.search_result_edit.setReadOnly(True)
        self.search_result_edit.setPlaceholderText("搜索结果会显示在这里。")
        layout.addWidget(self.search_result_edit, 1)
        return box

    def _build_import_candidates_tab(self):
        box = QFrame()
        self.import_candidates_tab = box
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        hint = QLabel("文档导入后，AI 会整理人物、设定、伏笔和项目资料草案；确认后再加入项目。")
        hint.setObjectName("hint")
        layout.addWidget(hint)
        self.candidate_count_label = QLabel("暂无候选")
        self.candidate_count_label.setObjectName("hint")
        layout.addWidget(self.candidate_count_label)

        lists = QSplitter(Qt.Horizontal)
        lists.setChildrenCollapsible(False)
        self.candidate_character_list = self._build_candidate_column(lists, "候选人物")
        self.candidate_lore_list = self._build_candidate_column(lists, "候选设定")
        self.candidate_foreshadow_list = self._build_candidate_column(lists, "候选伏笔")
        self.candidate_material_list = self._build_candidate_column(lists, "候选资料")
        lists.setSizes([1, 1, 1, 1])
        layout.addWidget(lists, 1)
        for widget, kind in (
            (self.candidate_character_list, "characters"),
            (self.candidate_lore_list, "lore"),
            (self.candidate_foreshadow_list, "foreshadows"),
            (self.candidate_material_list, "project_materials"),
        ):
            widget.currentRowChanged.connect(lambda row, k=kind: self.show_import_candidate_detail(k, row))

        self.candidate_detail_box = QFrame()
        self.candidate_detail_box.setObjectName("novel_detail_panel")
        detail_layout = QVBoxLayout(self.candidate_detail_box)
        detail_layout.setContentsMargins(10, 8, 10, 8)
        detail_head = QHBoxLayout()
        detail_title = QLabel("候选详情")
        detail_title.setObjectName("field_label")
        detail_head.addWidget(detail_title)
        detail_head.addStretch()
        detail_close = self._ghost_button("收起详情", lambda: self.candidate_detail_box.setVisible(False))
        detail_head.addWidget(detail_close)
        detail_layout.addLayout(detail_head)
        self.candidate_detail_edit = PlainTextEdit()
        self.candidate_detail_edit.setReadOnly(True)
        self.candidate_detail_edit.setMinimumHeight(110)
        self.candidate_detail_edit.setMaximumHeight(170)
        self.candidate_detail_edit.setPlaceholderText("点击候选项可查看详情。")
        detail_layout.addWidget(self.candidate_detail_edit)
        layout.addWidget(self.candidate_detail_box)
        self.candidate_detail_box.setVisible(False)

        self.candidate_concurrency_combo = WideComboBox()
        self.candidate_concurrency_combo.addItems(["1", "2", "3", "4", "5", "6"])
        self.candidate_concurrency_combo.setToolTip("同时分析的文本块数量。接口不稳定时可调低，速度优先时可调高。")
        self.candidate_concurrency_combo.setFixedWidth(84)
        concurrency = self._candidate_analysis_concurrency()
        idx = self.candidate_concurrency_combo.findText(str(concurrency))
        self.candidate_concurrency_combo.setCurrentIndex(idx if idx >= 0 else 2)
        self.candidate_concurrency_combo.currentTextChanged.connect(self._on_candidate_concurrency_changed)

        action_grid = QGridLayout()
        action_grid.setHorizontalSpacing(6)
        action_grid.setVerticalSpacing(6)
        for col in range(3):
            action_grid.setColumnStretch(col, 1)
        for index, action in enumerate((
            ("全选", lambda: self.set_all_import_candidates_checked(True)),
            ("全不选", lambda: self.set_all_import_candidates_checked(False)),
            ("AI 分析候选", self.analyze_import_candidates_with_ai),
            ("确认加入项目", self.apply_import_candidates, True),
            ("清空候选", self.clear_import_candidates),
        )):
            text, callback = action[:2]
            primary = bool(action[2]) if len(action) > 2 else False
            btn = self._action_button(text, callback, primary)
            btn.setSizePolicy(QSizePolicy.Expanding, btn.sizePolicy().verticalPolicy())
            action_grid.addWidget(btn, index // 3, index % 3)
            self.candidate_action_buttons.append(btn)

        concurrency_box = QFrame()
        concurrency_layout = QHBoxLayout(concurrency_box)
        concurrency_layout.setContentsMargins(0, 0, 0, 0)
        concurrency_layout.setSpacing(6)
        concurrency_layout.addStretch()
        concurrency_layout.addWidget(QLabel("分析并发"))
        concurrency_layout.addWidget(self.candidate_concurrency_combo)
        concurrency_layout.addStretch()
        action_grid.addWidget(concurrency_box, 1, 2)
        layout.addLayout(action_grid)
        self.candidate_analysis_stop_btn = QPushButton("中止分析")
        self.candidate_analysis_stop_btn.setObjectName("danger")
        self.candidate_analysis_stop_btn.setVisible(False)
        self.candidate_analysis_stop_btn.clicked.connect(self.stop_import_candidate_analysis)
        layout.addWidget(self.candidate_analysis_stop_btn)
        return box

    def _candidate_analysis_concurrency(self):
        try:
            value = int(self.config.setdefault("novel", {}).get("candidate_analysis_concurrency", 3))
        except Exception:
            value = 3
        return max(1, min(6, value))

    def _on_candidate_concurrency_changed(self, text):
        value = self._candidate_analysis_concurrency_from_text(text)
        self.config.setdefault("novel", {})["candidate_analysis_concurrency"] = value
        try:
            save_config(self.config)
        except Exception as e:
            log_debug("小说候选分析并发设置保存失败", e)
        self.set_status_tip(f"AI 分析候选并发已设为 {value}。")

    def _candidate_analysis_concurrency_from_text(self, text):
        try:
            return max(1, min(6, int(str(text or "").strip() or 3)))
        except Exception:
            return 3

    def _build_candidate_column(self, parent, title):
        frame = QFrame()
        frame.setObjectName("novel_column_card")
        frame.setToolTip("导入文档或 AI 分析后，候选内容会先放在这里，勾选后再确认加入项目。")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        label = QLabel(title)
        label.setObjectName("field_label")
        layout.addWidget(label)
        lst = QListWidget()
        lst.setSelectionMode(QListWidget.MultiSelection)
        lst.setMinimumHeight(180)
        lst.setToolTip("勾选要加入项目的候选项；点击一项可在下方查看详情。")
        layout.addWidget(lst, 1)
        parent.addWidget(frame)
        return lst

    def _schedule_refresh(self, include_manuscript=False):
        if self._loading:
            return
        self._pending_manuscript_refresh = self._pending_manuscript_refresh or include_manuscript
        self._refresh_pending_helpers = True
        self._refresh_pending_count += 1
        self._update_stats_label()
        self._refresh_timer.start()

    def _run_deferred_refresh(self):
        if self._loading:
            return
        self._refresh_pending_count = 0
        if self._pending_manuscript_refresh:
            self.refresh_manuscript()
        self._pending_manuscript_refresh = False
        if self._refresh_pending_helpers:
            self.refresh_writing_check()
            self.refresh_import_candidate_lists()
        self._refresh_pending_helpers = False
        self._autosave_draft()

    def _mark_dirty(self):
        if self._loading:
            return
        self._dirty = True
        self._save_current_fields()
        self.refresh_project_summary_label()
        self._schedule_refresh()

    def _mark_character_dirty(self):
        if self._loading:
            return
        self._dirty = True
        self._save_character_from_editor()
        self._schedule_refresh()

    def _mark_lore_dirty(self):
        if self._loading:
            return
        self._dirty = True
        self._save_lore_from_editor()
        self._schedule_refresh()

    def _mark_foreshadow_dirty(self):
        if self._loading:
            return
        self._dirty = True
        self._save_foreshadow_from_editor()
        self._schedule_refresh()

    def _mark_chapter_dirty(self):
        if self._loading:
            return
        self._dirty = True
        self._save_chapter_from_editor()
        self._schedule_refresh(include_manuscript=True)

    def _save_current_work(self, reason="自动保存", refresh_project_list=True, preserve_project_mtime=False):
        try:
            self._flush_current_editors()
            self._sync_candidate_analysis_state()
            self._sync_import_candidates_to_project()
            data = deepcopy(self.current_project)
            current_path = self.current_project_path
            if current_path and current_path not in ("", NOVEL_DRAFT_FILE):
                save_project_file(current_path, data, preserve_mtime=preserve_project_mtime)
                self._remember_project_path(current_path)
                self._save_draft_snapshot()
                if refresh_project_list:
                    self._notify_project_store_changed()
                self._dirty = False
                self._update_stats_label()
                return current_path
            self._save_draft_snapshot()
            self._dirty = False
            self._update_stats_label()
            return NOVEL_DRAFT_FILE
        except Exception as e:
            log_debug(f"小说项目{reason}失败", e)
            return ""

    def _has_saved_project_path(self):
        path = str(self.current_project_path or "").strip()
        return bool(path and path != NOVEL_DRAFT_FILE)

    def _save_after_import(self):
        try:
            self._flush_current_editors()
            self._sync_candidate_analysis_state()
            self._sync_import_candidates_to_project()
            if self._has_saved_project_path():
                save_project_file(self.current_project_path, self.current_project)
                self._remember_project_path(self.current_project_path)
                self._save_draft_snapshot()
                self._notify_project_store_changed()
                self._dirty = False
                self._update_stats_label()
                return "已保存到原项目。"
            self._save_draft_snapshot()
            self._update_stats_label()
            return "已保存到自动草稿。"
        except Exception as e:
            log_debug("小说导入后保存失败", e)
            return "导入完成，但自动保存失败。"

    def _update_project_list(self):
        current_path = os.path.abspath(str(self.current_project_path or ""))
        self.project_list.clear()
        records = list_project_summaries()
        selected_row = -1
        for record in records:
            filename = record["filename"]
            path = record["path"]
            item = QListWidgetItem(_project_summary_record_text(record))
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            self.project_list.addItem(item)
            if current_path and os.path.abspath(path) == current_path:
                selected_row = self.project_list.count() - 1
        if selected_row >= 0:
            self.project_list.blockSignals(True)
            try:
                self.project_list.setCurrentRow(selected_row)
            finally:
                self.project_list.blockSignals(False)
        if hasattr(self, "project_hint"):
            self.project_hint.setText("当前没有已保存项目；点击“保存项目”可保存当前草稿。" if not records else "单击列表可打开已保存小说。")

    def _select_project_list_path(self, path):
        if not hasattr(self, "project_list"):
            return
        target = os.path.abspath(str(path or ""))
        if not target:
            return
        self.project_list.blockSignals(True)
        try:
            for row in range(self.project_list.count()):
                item = self.project_list.item(row)
                item_path = os.path.abspath(str(item.data(Qt.UserRole) or ""))
                if item_path == target:
                    self.project_list.setCurrentRow(row)
                    return
        finally:
            self.project_list.blockSignals(False)

    def _current_project_to_data(self):
        self._flush_current_editors()
        self._sync_import_candidates_to_project()
        data = deepcopy(self.current_project)
        data["updated_at"] = now_str()
        return data

    def get_current_project_snapshot(self):
        return self._current_project_to_data(), self.current_project_path or ""

    def _update_stats_label(self):
        if not hasattr(self, "project_meta_label"):
            return
        path = str(self.current_project_path or "").strip()
        if not path or path == NOVEL_DRAFT_FILE:
            source = "自动草稿"
        else:
            source = os.path.splitext(os.path.basename(path))[0]
        self.project_meta_label.setText(_project_meta_text(self.current_project, source))
        self.project_meta_label.setToolTip(path or "未保存项目")

    def _save_current_fields(self):
        if self._loading:
            return
        meta = self.current_project.setdefault("meta", {})
        meta["title"] = self.title_edit.text().strip() or "未命名小说"
        meta["genre"] = self.genre_edit.text().strip()
        meta["style"] = self.style_edit.text().strip()
        meta["pov"] = self.pov_combo.currentText().strip()
        meta["target_words"] = self.target_words_edit.text().strip()
        meta["status"] = self.status_combo.currentText().strip()
        meta["premise"] = self.premise_edit.toPlainText().strip()
        self.current_project["bible"] = self.bible_edit.toPlainText()
        self.current_project["world_rules"] = self.world_rules_edit.toPlainText()
        self.current_project["timeline"] = self.timeline_edit.toPlainText()
        self.current_project["foreshadows"] = self.foreshadows_edit.toPlainText()
        self.current_project["summary"] = self.summary_edit.toPlainText()
        chapters, removed = _dedupe_chapters(self.current_project.get("chapters", []))
        if removed:
            self.current_project["chapters"] = chapters
            if self.current_chapter_index >= len(chapters):
                self.current_chapter_index = len(chapters) - 1

    def _refresh_project_material_editors(self):
        pairs = (
            ("bible", self.bible_edit),
            ("world_rules", self.world_rules_edit),
            ("timeline", self.timeline_edit),
            ("summary", self.summary_edit),
        )
        for key, widget in pairs:
            self._set_text_without_signals(widget, self.current_project.get(key, ""))

    def _flush_current_editors(self):
        if self._loading:
            return
        self._save_current_fields()
        self._save_character_from_editor()
        self._save_lore_from_editor()
        self._save_foreshadow_from_editor()
        self._save_chapter_from_editor()

    def _save_character_from_editor(self):
        self._save_character_at_index(self.current_character_index)

    def _save_character_at_index(self, index):
        if index < 0:
            return
        chars = self.current_project.setdefault("characters", [])
        if index >= len(chars):
            return
        char = chars[index]
        char["name"] = self.char_name.text().strip()
        char["role"] = self.char_role.text().strip()
        char["goal"] = self.char_goal.text().strip()
        char["secret"] = self.char_secret.text().strip()
        char["voice"] = self.char_voice.text().strip()
        char["notes"] = self.char_notes.toPlainText().strip()
        self._refresh_character_item(index)

    def _save_lore_from_editor(self):
        self._save_lore_at_index(self.current_lore_index)

    def _save_lore_at_index(self, index):
        if index < 0:
            return
        lore = self.current_project.setdefault("lore", [])
        if index >= len(lore):
            return
        item = lore[index]
        item["name"] = self.lore_name.text().strip()
        item["type"] = self.lore_type.currentText().strip()
        item["description"] = self.lore_desc.toPlainText().strip()
        self._refresh_lore_item(index)

    def _save_foreshadow_from_editor(self):
        self._save_foreshadow_at_index(self.current_foreshadow_index)

    def _save_foreshadow_at_index(self, index):
        if index < 0:
            return
        items = self.current_project.setdefault("foreshadow_items", [])
        if index >= len(items):
            return
        item = items[index]
        item["name"] = self.foreshadow_name.text().strip()
        item["status"] = self.foreshadow_status.currentText().strip()
        item["setup_chapter"] = self.foreshadow_setup.text().strip()
        item["payoff_chapter"] = self.foreshadow_payoff.text().strip()
        item["description"] = self.foreshadow_desc.toPlainText().strip()
        self._refresh_foreshadow_item(index)

    def _save_chapter_from_editor(self):
        self._save_chapter_at_index(self.current_chapter_index)

    def _save_chapter_at_index(self, index):
        if index < 0:
            return
        chaps = self.current_project.setdefault("chapters", [])
        if index >= len(chaps):
            return
        chap = chaps[index]
        old_linked = _normalize_name_list(chap.get("linked_characters", []))
        chap["title"] = self.chapter_title.text().strip()
        chap["status"] = self.chapter_status.currentText().strip()
        new_linked = _normalize_name_list(self.chapter_linked.text())
        chap["linked_characters"] = new_linked
        if (
            old_linked != new_linked
            and str(chap.get("analysis_hash_version", "") or "").strip() != CHAPTER_ANALYSIS_HASH_VERSION
        ):
            chap["analysis_hash"] = ""
        chap["outline"] = self.chapter_outline.toPlainText().strip()
        if hasattr(self, "chapter_draft_words"):
            chap["draft_words"] = self.chapter_draft_words.text().strip()
        else:
            chap.setdefault("draft_words", "")
        chap["text"] = self.chapter_text.toPlainText().strip()
        chap["summary"] = self.chapter_summary.toPlainText().strip()
        chap["key_facts"] = self.chapter_key_facts.toPlainText().strip()
        inferred_status = _infer_chapter_status(chap)
        if inferred_status != chap["status"]:
            chap["status"] = inferred_status
            idx = self.chapter_status.findText(inferred_status) if hasattr(self, "chapter_status") else -1
            if idx >= 0:
                self.chapter_status.blockSignals(True)
                try:
                    self.chapter_status.setCurrentIndex(idx)
                finally:
                    self.chapter_status.blockSignals(False)
        self._refresh_chapter_item(index)

    def _refresh_character_item(self, index):
        row = self._row_for_source_index(self.character_list, index) if hasattr(self, "character_list") else -1
        if row >= 0:
            item = self.character_list.item(row)
            char = self.current_project["characters"][index]
            item.setText(_character_list_text(index, char))
            item.setToolTip(self._character_tooltip(char))
            item.setSizeHint(QSize(0, 30))

    def _refresh_chapter_item(self, index):
        if 0 <= index < self.chapter_list.count():
            item = self.chapter_list.item(index)
            chap = self.current_project["chapters"][index]
            item.setText(_chapter_list_text(index, chap))
            item.setToolTip(_chapter_tooltip(chap))

    def _refresh_lore_item(self, index):
        row = self._row_for_source_index(self.lore_list, index) if hasattr(self, "lore_list") else -1
        if row >= 0:
            item = self.lore_list.item(row)
            lore = self.current_project["lore"][index]
            item.setText(_lore_list_text(index, lore))

    def _refresh_foreshadow_item(self, index):
        row = self._row_for_source_index(self.foreshadow_list, index) if hasattr(self, "foreshadow_list") else -1
        if row >= 0:
            item = self.foreshadow_list.item(row)
            data = self.current_project["foreshadow_items"][index]
            item.setText(_foreshadow_list_text(index, data))

    def _character_tooltip(self, char):
        if not isinstance(char, dict):
            return ""
        fields = (
            ("姓名", char.get("name", "")),
            ("身份", char.get("role", "")),
            ("目标", char.get("goal", "")),
            ("秘密", char.get("secret", "")),
            ("语言", char.get("voice", "")),
            ("备注", char.get("notes", "")),
        )
        return "\n".join(f"{label}：{str(value).strip()}" for label, value in fields if str(value or "").strip())

    def _row_for_source_index(self, widget, source_index):
        if widget is None:
            return -1
        for row in range(widget.count()):
            item = widget.item(row)
            if item is not None and item.data(Qt.UserRole) == source_index:
                return row
        return -1

    def _source_index_for_row(self, widget, row):
        if widget is None or row is None or row < 0 or row >= widget.count():
            return -1
        source_index = widget.item(row).data(Qt.UserRole)
        return source_index if isinstance(source_index, int) else row

    def _first_record_appearance_order(self, item, fields):
        item = item if isinstance(item, dict) else {}
        aliases = _record_alias_keys(item, name_key="name")
        name = str(item.get("name", "") or "").strip()
        if name:
            aliases.add(_character_merge_key(item) if "role" in item else re.sub(r"\s+", "", name))
        aliases = {alias for alias in aliases if alias}
        if aliases:
            chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
            chapters = chapters if isinstance(chapters, list) else []
            for index, chap in enumerate(chapters):
                if not isinstance(chap, dict):
                    continue
                linked = chap.get("linked_characters", [])
                linked_text = " ".join(str(value or "") for value in (linked if isinstance(linked, list) else [linked]))
                chapter_text = "\n".join(
                    str(chap.get(field, "") or "")
                    for field in ("title", "outline", "summary", "key_facts", "text")
                )
                compact = re.sub(r"\s+", "", f"{linked_text}\n{chapter_text}")
                if any(alias in compact for alias in aliases):
                    return index + 1
        return _story_order_from_text(_record_text_for_sort(item, fields))

    def _indexed_sort_key(self, group_key, source_index, item):
        item = item if isinstance(item, dict) else {}
        if group_key == "characters":
            order = self._first_record_appearance_order(item, ("name", "role", "goal", "secret", "voice", "notes"))
            name = str(item.get("name", "") or "")
            return (order, str(item.get("name", "") or "").strip() == "", source_index, name)
        if group_key == "lore":
            order = self._first_record_appearance_order(item, ("name", "type", "description"))
            typ = str(item.get("type", "") or "")
            name = str(item.get("name", "") or "")
            return (order, typ, source_index, name)
        if group_key == "foreshadows":
            setup = _story_order_from_text(item.get("setup_chapter", ""))
            payoff = _story_order_from_text(item.get("payoff_chapter", ""))
            if setup == _SORT_MISSING_ORDER:
                setup = _story_order_from_text(_record_text_for_sort(item, ("name", "description")))
            primary = setup if setup != _SORT_MISSING_ORDER else payoff
            status_rank = {"未埋": 0, "已埋": 1, "已回收": 2, "废弃": 3}.get(str(item.get("status", "") or ""), 4)
            name = str(item.get("name", "") or "")
            return (primary, payoff, status_rank, source_index, name)
        return (source_index,)

    def _sorted_indexed_records(self, group_key, items):
        items = items if isinstance(items, list) else []
        records = [(i, item) for i, item in enumerate(items)]
        if group_key == "chapters":
            return records
        return sorted(records, key=lambda pair: self._indexed_sort_key(group_key, pair[0], pair[1]))

    def _reload_indexed_list(self, widget, items, text_func, load_func, current_index, selected_index=None, tooltip_func=None, item_height=None, group_key=""):
        count = 0
        widget.blockSignals(True)
        try:
            widget.clear()
            records = self._sorted_indexed_records(group_key, items)
            for i, data in records:
                item = QListWidgetItem(text_func(i, data))
                item.setData(Qt.UserRole, i)
                if tooltip_func:
                    item.setToolTip(tooltip_func(data))
                if item_height:
                    item.setSizeHint(QSize(0, int(item_height)))
                widget.addItem(item)
            count = widget.count()
            if count:
                if selected_index is None:
                    selected_index = current_index if 0 <= current_index < len(items) else None
                selected_row = self._row_for_source_index(widget, selected_index) if selected_index is not None else -1
                if selected_row < 0:
                    selected_row = 0
                widget.setCurrentRow(selected_row)
            else:
                selected_index = -1
                widget.setCurrentRow(-1)
        finally:
            widget.blockSignals(False)
        if count:
            source_index = self._source_index_for_row(widget, widget.currentRow())
            load_func(source_index)
        else:
            load_func(None)

    def _reload_character_list(self, selected_index=None):
        self._reload_indexed_list(
            self.character_list,
            self.current_project.get("characters", []),
            _character_list_text,
            self._load_character_to_editor,
            self.current_character_index,
            selected_index,
            self._character_tooltip,
            30,
            "characters",
        )

    def _reload_chapter_list(self, selected_index=None):
        self._reload_indexed_list(
            self.chapter_list,
            self.current_project.get("chapters", []),
            _chapter_list_text,
            self._load_chapter_to_editor,
            self.current_chapter_index,
            selected_index,
            _chapter_tooltip,
            group_key="chapters",
        )
        self._refresh_read_aloud_scope_combo()

    def _reload_lore_list(self, selected_index=None):
        self._reload_indexed_list(
            self.lore_list,
            self.current_project.get("lore", []),
            _lore_list_text,
            self._load_lore_to_editor,
            self.current_lore_index,
            selected_index,
            group_key="lore",
        )

    def _reload_foreshadow_list(self, selected_index=None):
        self._reload_indexed_list(
            self.foreshadow_list,
            self.current_project.get("foreshadow_items", []),
            _foreshadow_list_text,
            self._load_foreshadow_to_editor,
            self.current_foreshadow_index,
            selected_index,
            group_key="foreshadows",
        )

    def _switch_indexed_editor(self, row, current_attr, save_func, load_func):
        if self._loading:
            return
        widget_attr = {
            "current_character_index": "character_list",
            "current_chapter_index": "chapter_list",
            "current_lore_index": "lore_list",
            "current_foreshadow_index": "foreshadow_list",
        }.get(current_attr)
        widget = getattr(self, widget_attr, None) if widget_attr else None
        source_index = self._source_index_for_row(widget, row) if widget is not None else row
        old_index = getattr(self, current_attr, -1)
        if old_index != source_index:
            save_func(old_index)
        setattr(self, current_attr, source_index)
        load_func(source_index)

    def _on_character_selected(self, row):
        self._switch_indexed_editor(row, "current_character_index", self._save_character_at_index, self._load_character_to_editor)

    def _on_chapter_selected(self, row):
        self._switch_indexed_editor(row, "current_chapter_index", self._save_chapter_at_index, self._load_chapter_to_editor)

    def _on_lore_selected(self, row):
        self._switch_indexed_editor(row, "current_lore_index", self._save_lore_at_index, self._load_lore_to_editor)

    def _on_foreshadow_selected(self, row):
        self._switch_indexed_editor(row, "current_foreshadow_index", self._save_foreshadow_at_index, self._load_foreshadow_to_editor)

    def _load_character_to_editor(self, row):
        was_loading = self._loading
        self._loading = True
        try:
            if row is None or row < 0 or row >= len(self.current_project.get("characters", [])):
                for w in (self.char_name, self.char_role, self.char_goal, self.char_secret, self.char_voice):
                    w.clear()
                self.char_notes.clear()
                self.current_character_index = -1
                return
            char = self.current_project["characters"][row]
            self.char_name.setText(char.get("name", ""))
            self.char_role.setText(char.get("role", ""))
            self.char_goal.setText(char.get("goal", ""))
            self.char_secret.setText(char.get("secret", ""))
            self.char_voice.setText(char.get("voice", ""))
            self.char_notes.setPlainText(char.get("notes", ""))
            self.current_character_index = row
        finally:
            self._loading = was_loading

    def _load_chapter_to_editor(self, row):
        was_loading = self._loading
        self._loading = True
        try:
            if row is None or row < 0 or row >= len(self.current_project.get("chapters", [])):
                self.chapter_title.clear()
                if hasattr(self, "chapter_draft_words"):
                    self.chapter_draft_words.clear()
                self.chapter_outline.clear()
                self.chapter_text.clear()
                self.chapter_summary.clear()
                self.chapter_key_facts.clear()
                self.chapter_linked.clear()
                self.chapter_status.setCurrentIndex(0)
                self.current_chapter_index = -1
                return
            chap = self.current_project["chapters"][row]
            self.chapter_title.setText(chap.get("title", ""))
            idx = self.chapter_status.findText(chap.get("status", "大纲"))
            self.chapter_status.setCurrentIndex(idx if idx >= 0 else 0)
            if hasattr(self, "chapter_draft_words"):
                self.chapter_draft_words.setText(chap.get("draft_words", ""))
            self.chapter_outline.setPlainText(chap.get("outline", ""))
            self.chapter_text.setPlainText(chap.get("text", ""))
            self.chapter_summary.setPlainText(chap.get("summary", ""))
            self.chapter_key_facts.setPlainText(chap.get("key_facts", ""))
            linked = _normalize_name_list(chap.get("linked_characters", []))
            self.chapter_linked.setText(", ".join(linked))
            self.current_chapter_index = row
            self._refresh_read_aloud_scope_combo()
            if not self._has_partial_chapter_ai_preview():
                self._set_partial_chapter_ai_preview_state(False)
        finally:
            self._loading = was_loading

    def _load_lore_to_editor(self, row):
        was_loading = self._loading
        self._loading = True
        try:
            if row is None or row < 0 or row >= len(self.current_project.get("lore", [])):
                self.lore_name.clear()
                self.lore_type.setCurrentIndex(0)
                self.lore_desc.clear()
                self.current_lore_index = -1
                return
            lore = self.current_project["lore"][row]
            self.lore_name.setText(lore.get("name", ""))
            idx = self.lore_type.findText(lore.get("type", "地点"))
            self.lore_type.setCurrentIndex(idx if idx >= 0 else 0)
            self.lore_desc.setPlainText(lore.get("description", ""))
            self.current_lore_index = row
        finally:
            self._loading = was_loading

    def _load_foreshadow_to_editor(self, row):
        was_loading = self._loading
        self._loading = True
        try:
            if row is None or row < 0 or row >= len(self.current_project.get("foreshadow_items", [])):
                self.foreshadow_name.clear()
                self.foreshadow_status.setCurrentIndex(0)
                self.foreshadow_setup.clear()
                self.foreshadow_payoff.clear()
                self.foreshadow_desc.clear()
                self.current_foreshadow_index = -1
                return
            item = self.current_project["foreshadow_items"][row]
            self.foreshadow_name.setText(item.get("name", ""))
            idx = self.foreshadow_status.findText(item.get("status", "未埋"))
            self.foreshadow_status.setCurrentIndex(idx if idx >= 0 else 0)
            self.foreshadow_setup.setText(item.get("setup_chapter", ""))
            self.foreshadow_payoff.setText(item.get("payoff_chapter", ""))
            self.foreshadow_desc.setPlainText(item.get("description", ""))
            self.current_foreshadow_index = row
        finally:
            self._loading = was_loading

    def _add_indexed_item(self, project_key, new_item_func, save_func, reload_func):
        save_func()
        items = self.current_project.setdefault(project_key, [])
        new_index = len(items)
        items.append(new_item_func(new_index))
        reload_func(new_index)
        self._mark_dirty()

    def _delete_indexed_item(self, project_key, current_index, label, name_key, reload_func):
        if current_index < 0:
            return
        items = self.current_project.setdefault(project_key, [])
        if current_index >= len(items):
            return
        deleted_index = current_index
        name = items[deleted_index].get(name_key, f"{label} {deleted_index + 1}")
        if not self._confirm_delete_item(label, name):
            return
        del items[deleted_index]
        reload_func(min(deleted_index, len(items) - 1))
        self._mark_dirty()

    def add_character(self):
        self._add_indexed_item("characters", _new_character, self._save_character_from_editor, self._reload_character_list)

    def delete_character(self):
        self._delete_indexed_item("characters", self.current_character_index, "人物", "name", self._reload_character_list)

    def add_chapter(self):
        self._add_indexed_item("chapters", _new_chapter, self._save_chapter_from_editor, self._reload_chapter_list)

    def pick_linked_character(self):
        names = [
            str(char.get("name", "") or "").strip()
            for char in self.current_project.get("characters", [])
            if isinstance(char, dict) and str(char.get("name", "") or "").strip()
        ]
        if not names:
            QMessageBox.information(self, "关联人物", "人物卡里还没有可选择的人物。")
            return
        name, ok = self._get_combo_choice("选择关联人物", "人物：", names, 0)
        if not ok or not name:
            return
        current = _normalize_name_list(self.chapter_linked.text())
        if name not in current:
            current.append(name)
        self.chapter_linked.setText(", ".join(current))
        self._mark_chapter_dirty()

    def _confirm_delete_item(self, label, name):
        name = str(name or "").strip() or label
        ret = QMessageBox.question(
            self,
            "删除确认",
            f"确定删除{label}「{name}」吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return ret == QMessageBox.Yes

    def add_lore(self):
        self._add_indexed_item("lore", _new_lore, self._save_lore_from_editor, self._reload_lore_list)

    def delete_lore(self):
        self._delete_indexed_item("lore", self.current_lore_index, "设定", "name", self._reload_lore_list)

    def add_foreshadow(self):
        self._add_indexed_item("foreshadow_items", _new_foreshadow, self._save_foreshadow_from_editor, self._reload_foreshadow_list)

    def delete_foreshadow(self):
        self._delete_indexed_item("foreshadow_items", self.current_foreshadow_index, "伏笔", "name", self._reload_foreshadow_list)

    def delete_chapter(self):
        self._delete_indexed_item("chapters", self.current_chapter_index, "章节", "title", self._reload_chapter_list)

    def split_current_chapter(self):
        self._save_chapter_from_editor()
        chapters = self.current_project.get("chapters", [])
        chapters = chapters if isinstance(chapters, list) else []
        body_chapters = [chap for chap in chapters if isinstance(chap, dict) and str(chap.get("text", "") or "").strip()]
        body_words = sum(len(str(chap.get("text", "") or "").strip()) for chap in body_chapters)
        if body_words <= 0:
            QMessageBox.information(self, "拆分提示", "当前没有可导出的章节正文。")
            return
        average_words = body_words // max(1, len(body_chapters))
        default_words = max(100, min(5000, average_words or 2000))
        target_words, ok = QInputDialog.getInt(
            self,
            "按字数拆分并导出",
            f"当前小说正文总字数：{body_words} 字\n请输入单章目标字数（按自然边界拆分，允许少量浮动）：",
            value=default_words,
            minValue=100,
            maxValue=max(1000, body_words * 2),
            step=100,
        )
        if not ok or target_words <= 0:
            return
        split_chapters = _split_manuscript_into_target_chapters(self.current_project, target_words)
        if not split_chapters:
            QMessageBox.information(self, "拆分提示", "没有可导出的正文内容。")
            return
        title = self._project_title()
        path = self._get_export_path("导出拆分 Word", f"{title}_按{target_words}字拆分", "docx", "Word 文档 (*.docx)")
        if not path:
            return
        _write_docx_text(path, title, split_chapters, center_chapter_headings=True)
        self.set_status_tip(f"已按约{target_words}字拆分为 {len(split_chapters)} 章并导出 Word：{os.path.basename(path)}")

    def _move_chapter(self, offset):
        index = self.current_chapter_index
        chaps = self.current_project.setdefault("chapters", [])
        new_index = index + offset
        if index < 0 or new_index < 0 or index >= len(chaps) or new_index >= len(chaps):
            return
        self._save_chapter_from_editor()
        chaps[index], chaps[new_index] = chaps[new_index], chaps[index]
        self._reload_chapter_list(new_index)
        self._mark_dirty()

    def move_chapter_up(self):
        self._move_chapter(-1)

    def move_chapter_down(self):
        self._move_chapter(1)

    def _load_project_data(self, data, path="", defer_helpers=False):
        self._loading = True
        try:
            self.current_project = _normalize_project(data)
            status_changes = _auto_classify_default_statuses(self.current_project)
            self.current_project_path = path
            analysis_state = _normalize_candidate_analysis_state(self.current_project.get("analysis_state", {}))
            self.failed_analysis_chunks = analysis_state.get("failed_candidate_chunks", [])
            self.pending_analysis_chapter_ids = analysis_state.get("pending_candidate_chapter_ids", [])
            self.import_candidates = _normalize_import_candidates(self.current_project.get("import_candidates", {}))
            meta = self.current_project["meta"]
            self.title_edit.setText(meta.get("title", ""))
            self.genre_edit.setText(meta.get("genre", ""))
            self.style_edit.setText(meta.get("style", ""))
            idx = self.pov_combo.findText(meta.get("pov", "第三人称"))
            self.pov_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.target_words_edit.setText(meta.get("target_words", ""))
            idx = self.status_combo.findText(meta.get("status", "草稿"))
            self.status_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.premise_edit.setPlainText(meta.get("premise", ""))
            self.bible_edit.setPlainText(self.current_project.get("bible", ""))
            self.world_rules_edit.setPlainText(self.current_project.get("world_rules", ""))
            self.timeline_edit.setPlainText(self.current_project.get("timeline", ""))
            self.foreshadows_edit.setPlainText(self.current_project.get("foreshadows", ""))
            self.summary_edit.setPlainText(self.current_project.get("summary", ""))
            self._reload_character_list()
            self._reload_lore_list()
            self._reload_foreshadow_list()
            self._reload_chapter_list()
            self._dirty = any(status_changes.values())
        finally:
            self._loading = False
        self.refresh_project_summary_label()
        self._update_stats_label()
        if defer_helpers:
            self._pending_manuscript_refresh = True
            self._refresh_timer.start()
        else:
            self.refresh_manuscript()
            self.refresh_writing_check()
            self.refresh_import_candidate_lists()

    def refresh_manuscript(self):
        if not hasattr(self, "manuscript_edit") or self._loading or self._refreshing_helpers:
            return
        try:
            self._refreshing_helpers = True
            self._flush_current_editors()
            text = _build_manuscript_text(self.current_project)
            self._set_text_without_signals(self.manuscript_edit, text)
            self._refresh_read_aloud_scope_combo()
        except Exception as e:
            log_debug("小说书稿刷新失败", e)
        finally:
            self._refreshing_helpers = False

    def _has_manuscript_body(self):
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        chapters = chapters if isinstance(chapters, list) else []
        return any(
            isinstance(chap, dict) and str(chap.get("text", "") or "").strip()
            for chap in chapters
        )

    def copy_manuscript(self):
        try:
            self._flush_current_editors()
            if not self._has_manuscript_body():
                QMessageBox.information(self, "复制提示", "当前没有可复制的章节正文。")
                return
            text = _build_manuscript_text(self.current_project)
            self.manuscript_edit.setPlainText(text)
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            self.set_status_tip("完整书稿已复制。")
        except Exception as e:
            QMessageBox.warning(self, "复制失败", str(e))

    def _read_aloud_chapter_label(self, index, chap):
        chap = chap if isinstance(chap, dict) else {}
        title = str(chap.get("title", "") or f"章节 {index + 1}").strip()
        words = len(str(chap.get("text", "") or "").strip())
        return f"{index + 1}. {title}（{words}字）"

    def _refresh_read_aloud_scope_combo(self):
        combo = getattr(self, "read_aloud_scope_combo", None)
        if combo is None:
            return
        previous = str(combo.currentData() or getattr(self, "read_aloud_scope", "") or "current")
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        chapters = chapters if isinstance(chapters, list) else []
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem("当前章节", "current")
            combo.addItem("全部书稿", "all")
            for index, chap in enumerate(chapters):
                if not isinstance(chap, dict):
                    continue
                chapter_id = str(chap.get("id", "") or "").strip()
                data = f"chapter:{chapter_id}" if chapter_id else f"chapter_index:{index}"
                combo.addItem(self._read_aloud_chapter_label(index, chap), data)
            selected = combo.findData(previous)
            if selected < 0:
                selected = combo.findData("current")
            combo.setCurrentIndex(selected if selected >= 0 else 0)
            self.read_aloud_scope = str(combo.currentData() or "current")
        finally:
            combo.blockSignals(False)

    def _on_read_aloud_scope_changed(self, _index):
        combo = getattr(self, "read_aloud_scope_combo", None)
        self.read_aloud_scope = str(combo.currentData() if combo is not None else "current") or "current"

    def _chapter_index_for_read_aloud_scope(self, scope):
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        chapters = chapters if isinstance(chapters, list) else []
        scope = str(scope or "current")
        if scope == "current":
            return self.current_chapter_index if 0 <= self.current_chapter_index < len(chapters) else -1
        if scope.startswith("chapter_index:"):
            try:
                index = int(scope.split(":", 1)[1])
            except Exception:
                return -1
            return index if 0 <= index < len(chapters) else -1
        if scope.startswith("chapter:"):
            chapter_id = scope.split(":", 1)[1]
            for index, chap in enumerate(chapters):
                if isinstance(chap, dict) and str(chap.get("id", "") or "") == chapter_id:
                    return index
        return -1

    def _selected_read_aloud_text(self):
        self._flush_current_editors()
        self._refresh_read_aloud_scope_combo()
        scope = str(getattr(self, "read_aloud_scope", "") or "current")
        if scope == "all":
            if not self._has_manuscript_body():
                return "", "当前没有可朗读的书稿正文。", "书稿"
            return _build_manuscript_text(self.current_project), "", "书稿"
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        chapters = chapters if isinstance(chapters, list) else []
        index = self._chapter_index_for_read_aloud_scope(scope)
        if index < 0 or index >= len(chapters):
            return "", "请先选择要朗读的章节。", "章节"
        chap = chapters[index] if isinstance(chapters[index], dict) else {}
        body = str(chap.get("text", "") or "").strip()
        if not body:
            return "", "所选章节没有可朗读正文。", "章节"
        title = str(chap.get("title", "") or f"章节 {index + 1}").strip()
        text = f"{title}\n\n{body}".strip() if title else body
        return text, "", title or f"章节 {index + 1}"

    def start_read_aloud(self):
        text, error, label = self._selected_read_aloud_text()
        if error:
            QMessageBox.information(self, "朗读提示", error)
            return
        self.manuscript_edit.setPlainText(text)
        text_hash = self._read_aloud_hash(text)
        if self._can_resume_read_aloud(text_hash):
            self._set_read_aloud_running(True)
            self._ensure_read_aloud_segment(self.read_aloud_segment_index, autoplay=True, start_position=self.read_aloud_resume_position)
            return

        self.stop_read_aloud(silent=True, keep_resume=False)
        segments = self._split_read_aloud_segments(text)
        if not segments:
            QMessageBox.information(self, "朗读提示", "当前没有可朗读的书稿正文。")
            return

        self.read_aloud_text = text
        self.read_aloud_text_hash = text_hash
        self.read_aloud_segments = segments
        self.read_aloud_segment_index = 0
        self.read_aloud_resume_position = 0
        self.read_aloud_elapsed_seconds = 0
        self.read_aloud_speed_override = self._read_aloud_rate_from_config()
        self.read_aloud_finish_message = "书稿朗读完成。" if str(getattr(self, "read_aloud_scope", "") or "") == "all" else "章节朗读完成。"
        self._set_read_aloud_running(True)
        self._ensure_read_aloud_segment(0, autoplay=True, start_position=0)

    def stop_read_aloud(self, silent=False, keep_resume=True):
        self.read_aloud_pending_segment = None
        self._retire_read_aloud_worker()
        if self.read_aloud_player is not None:
            if keep_resume:
                self.read_aloud_resume_position = max(0, int(self.read_aloud_player.position()))
                self._sync_read_aloud_current_file()
            self.read_aloud_player.stop()
        elif not keep_resume:
            self.read_aloud_resume_position = 0
        self.read_aloud_timer.stop()
        self._set_read_aloud_running(False)
        if not keep_resume:
            self._cleanup_read_aloud_files(skip_running=True)
            self.read_aloud_speed_override = None
        if not silent:
            self.set_status_tip("已停止朗读。")

    def _read_aloud_hash(self, text):
        return hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()

    def _can_resume_read_aloud(self, text_hash):
        if not (
            text_hash
            and text_hash == self.read_aloud_text_hash
            and self.read_aloud_segments
            and 0 <= self.read_aloud_segment_index < len(self.read_aloud_segments)
            and self.read_aloud_resume_position > 0
        ):
            return False
        segment = self.read_aloud_segments[self.read_aloud_segment_index]
        return bool(
            segment.get("file")
            and os.path.exists(segment.get("file"))
            and segment.get("ready")
        )

    def _current_read_aloud_rate(self):
        rate = str(self.read_aloud_speed_override or self._read_aloud_rate_from_config() or "+0%").strip()
        valid = {value for _label, value in self._read_aloud_rate_options()}
        return rate if rate in valid else "+0%"

    def _set_read_aloud_running(self, running):
        if hasattr(self, "read_aloud_btn"):
            self.read_aloud_btn.setVisible(not running)
            self.read_aloud_btn.setEnabled(not running)
        if hasattr(self, "read_aloud_stop_btn"):
            self.read_aloud_stop_btn.setVisible(running)
            self.read_aloud_stop_btn.setEnabled(running)
        if hasattr(self, "read_aloud_scope_combo"):
            self.read_aloud_scope_combo.setEnabled(not running)

    def _split_read_aloud_segments(self, text, target_chars=850, max_chars=1200):
        source = str(text or "")
        if not source.strip():
            return []
        parts = []
        for match in re.finditer(r"\S(?:.*?\S)?(?:\n{2,}|$)", source, re.S):
            block = match.group(0)
            clean = block.strip()
            if clean:
                parts.append((clean, match.start() + block.find(clean)))
        if not parts:
            parts = [(source.strip(), source.find(source.strip()))]

        segments = []
        buf = ""
        start = None

        def push_buffer():
            nonlocal buf, start
            if buf.strip():
                segments.append({"text": buf.strip(), "start": start or 0, "end": (start or 0) + len(buf.strip()), "file": "", "ready": False})
            buf = ""
            start = None

        for part, offset in parts:
            chunks = self._split_read_aloud_long_text(part, max_chars)
            running_offset = offset
            for chunk in chunks:
                if not chunk:
                    continue
                chunk_offset = source.find(chunk, running_offset)
                if chunk_offset < 0:
                    chunk_offset = running_offset
                running_offset = chunk_offset + len(chunk)
                if start is None:
                    start = chunk_offset
                candidate = f"{buf}\n\n{chunk}" if buf else chunk
                if buf and len(candidate) > target_chars:
                    push_buffer()
                    start = chunk_offset
                    buf = chunk
                else:
                    buf = candidate
                if len(buf) >= max_chars:
                    push_buffer()
        push_buffer()
        return segments

    def _split_read_aloud_long_text(self, text, max_chars):
        text = str(text or "").strip()
        if len(text) <= max_chars:
            return [text] if text else []
        chunks = []
        current = ""
        for piece in re.split(r"([。！？；!?;]\s*)", text):
            if not piece:
                continue
            candidate = current + piece
            if current and len(candidate) > max_chars:
                chunks.append(current.strip())
                current = piece
            else:
                current = candidate
        if current.strip():
            chunks.append(current.strip())
        final = []
        for chunk in chunks:
            while len(chunk) > max_chars:
                final.append(chunk[:max_chars].strip())
                chunk = chunk[max_chars:].strip()
            if chunk:
                final.append(chunk)
        return final

    def _segment_audio_path(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".mp3", delete=False) as f:
            return f.name

    def _ensure_read_aloud_segment(self, index, autoplay=False, start_position=0):
        if index < 0 or index >= len(self.read_aloud_segments):
            return
        segment = self.read_aloud_segments[index]
        if segment.get("ready") and segment.get("file") and os.path.exists(segment.get("file")):
            if autoplay:
                self._play_read_aloud_segment(index, start_position)
            return
        if self.read_aloud_worker is not None:
            if self.read_aloud_worker_index == index:
                segment["autoplay"] = bool(autoplay)
                segment["start_position"] = int(start_position or 0)
            else:
                self.read_aloud_pending_segment = (index, bool(autoplay), int(start_position or 0))
            return
        if self.read_aloud_retired_workers:
            self.read_aloud_pending_segment = (index, bool(autoplay), int(start_position or 0))
            self.set_status_tip("正在等待上一段语音生成线程结束...")
            return
        try:
            path = self._segment_audio_path()
        except Exception as e:
            QMessageBox.warning(self, "朗读失败", f"无法创建朗读临时文件：{e}")
            self.stop_read_aloud(silent=True, keep_resume=False)
            return
        segment["file"] = path
        segment["ready"] = False
        segment["autoplay"] = bool(autoplay)
        segment["start_position"] = int(start_position or 0)
        self.read_aloud_worker_index = index
        self.read_aloud_worker = EdgeTTSWorker(segment.get("text", ""), path, rate="+0%")
        self.read_aloud_worker.progress.connect(self.set_status_tip)
        self.read_aloud_worker.result_ready.connect(self._on_read_aloud_segment_ready)
        self.read_aloud_worker.failed.connect(self._on_read_aloud_error)
        self.read_aloud_worker.finished.connect(self._cleanup_read_aloud_worker)
        self.set_status_tip(f"正在生成第 {index + 1}/{len(self.read_aloud_segments)} 段语音...")
        self.read_aloud_worker.start()

    def _on_read_aloud_segment_ready(self, path):
        worker = self.sender()
        if worker is not None and self.read_aloud_worker is not worker:
            self._remove_read_aloud_file(path)
            return
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "朗读失败", "Edge TTS 没有生成可播放音频。")
            self.stop_read_aloud(silent=True)
            return
        index = self.read_aloud_worker_index
        if index < 0 or index >= len(self.read_aloud_segments):
            self._remove_read_aloud_file(path)
            return
        segment = self.read_aloud_segments[index]
        segment["file"] = path
        segment["ready"] = True
        autoplay = bool(segment.pop("autoplay", False))
        start_position = int(segment.pop("start_position", 0) or 0)
        if autoplay and index == self.read_aloud_segment_index:
            self._play_read_aloud_segment(index, start_position)
        else:
            self.set_status_tip(f"第 {index + 1}/{len(self.read_aloud_segments)} 段语音已准备好。")

    def _play_read_aloud_segment(self, index, start_position=0):
        if index < 0 or index >= len(self.read_aloud_segments):
            self._finish_read_aloud(getattr(self, "read_aloud_finish_message", "书稿朗读完成。"))
            return
        segment = self.read_aloud_segments[index]
        path = segment.get("file", "")
        if not path or not os.path.exists(path):
            self.read_aloud_segment_index = index
            self._ensure_read_aloud_segment(index, autoplay=True, start_position=start_position)
            return
        if self.read_aloud_player is not None:
            try:
                self.read_aloud_player.stop()
            except Exception:
                pass
        audio_output = QAudioOutput(self)
        audio_output.setVolume(1.0)
        player = QMediaPlayer(self)
        player.setAudioOutput(audio_output)
        player.setSource(QUrl.fromLocalFile(path))
        try:
            rate_map = {value: float(label.rstrip("x")) for label, value in self._read_aloud_rate_options()}
            player.setPlaybackRate(rate_map.get(self._current_read_aloud_rate(), 1.0))
        except Exception:
            pass
        player.mediaStatusChanged.connect(self._on_read_aloud_media_status_changed)
        player.errorOccurred.connect(self._on_read_aloud_player_error)
        self.read_aloud_audio_output = audio_output
        self.read_aloud_player = player
        self.read_aloud_file = path
        self.read_aloud_segment_index = index
        self.read_aloud_elapsed_seconds = max(0, int(start_position or 0)) // 1000
        self.read_aloud_timer.start()
        self._scroll_read_aloud_to_segment(index, start_position)
        player.play()
        if start_position:
            player.setPosition(int(start_position))
            self.set_status_tip("正在从上次位置继续朗读。")
        else:
            self.set_status_tip(f"正在朗读第 {index + 1}/{len(self.read_aloud_segments)} 段。")
        self._prefetch_next_read_aloud_segment()

    def _prefetch_next_read_aloud_segment(self):
        next_index = self.read_aloud_segment_index + 1
        if next_index < len(self.read_aloud_segments):
            self._ensure_read_aloud_segment(next_index, autoplay=False)

    def _sync_read_aloud_current_file(self):
        if 0 <= self.read_aloud_segment_index < len(self.read_aloud_segments):
            self.read_aloud_file = self.read_aloud_segments[self.read_aloud_segment_index].get("file", "")

    def _on_read_aloud_media_status_changed(self, status):
        if status == QMediaPlayer.EndOfMedia:
            next_index = self.read_aloud_segment_index + 1
            self.read_aloud_resume_position = 0
            if next_index >= len(self.read_aloud_segments):
                self._finish_read_aloud(getattr(self, "read_aloud_finish_message", "书稿朗读完成。"))
                return
            self.read_aloud_segment_index = next_index
            segment = self.read_aloud_segments[next_index]
            if segment.get("ready") and segment.get("file") and os.path.exists(segment.get("file")):
                self._play_read_aloud_segment(next_index, 0)
            else:
                self.set_status_tip(f"正在生成第 {next_index + 1}/{len(self.read_aloud_segments)} 段语音...")
                self._ensure_read_aloud_segment(next_index, autoplay=True, start_position=0)

    def _on_read_aloud_player_error(self, error, error_string=""):
        log_debug("小说 Edge TTS 播放失败", f"{error}: {error_string}")
        self._finish_read_aloud("朗读播放失败。")
        QMessageBox.warning(self, "朗读失败", error_string or "Edge TTS 音频播放失败。")

    def _finish_read_aloud(self, message):
        self._retire_read_aloud_worker()
        if self.read_aloud_player is not None:
            self.read_aloud_player.stop()
        self.read_aloud_player = None
        self.read_aloud_audio_output = None
        self.read_aloud_resume_position = 0
        self.read_aloud_segment_index = 0
        self.read_aloud_timer.stop()
        self._set_read_aloud_running(False)
        self._cleanup_read_aloud_files(skip_running=True)
        self.set_status_tip(message)

    def _on_read_aloud_error(self, error):
        worker = self.sender()
        if worker is not None and self.read_aloud_worker is not worker:
            return
        log_debug("小说 Edge TTS 朗读失败", error)
        self.stop_read_aloud(silent=True)
        QMessageBox.warning(self, "朗读失败", str(error))

    def _cleanup_read_aloud_worker(self):
        worker = self.sender()
        if self.read_aloud_worker is worker:
            self.read_aloud_worker = None
            self.read_aloud_worker_index = -1
        if worker in self.read_aloud_retired_workers:
            self.read_aloud_retired_workers.remove(worker)
        try:
            if worker is not None:
                worker.deleteLater()
        except Exception:
            pass
        if self.read_aloud_worker is None and not self.read_aloud_retired_workers and self.read_aloud_pending_segment:
            index, autoplay, start_position = self.read_aloud_pending_segment
            self.read_aloud_pending_segment = None
            QTimer.singleShot(0, lambda: self._ensure_read_aloud_segment(index, autoplay=autoplay, start_position=start_position))

    def _cleanup_read_aloud_file(self):
        path = self.read_aloud_file
        self.read_aloud_file = ""
        self._remove_read_aloud_file(path)

    def _remove_read_aloud_file(self, path):
        if not path:
            return
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            log_debug("小说书稿朗读临时文件清理失败", e)

    def _cleanup_read_aloud_files(self, skip_running=False):
        files = [seg.get("file", "") for seg in self.read_aloud_segments if isinstance(seg, dict)]
        if self.read_aloud_file:
            files.append(self.read_aloud_file)
        running_files = set()
        if skip_running:
            workers = list(getattr(self, "read_aloud_retired_workers", []))
            if self.read_aloud_worker is not None:
                workers.append(self.read_aloud_worker)
            running_files = {getattr(worker, "output_path", "") for worker in workers if worker is not None}
        for path in set(files):
            if path and path in running_files:
                continue
            self._remove_read_aloud_file(path)
        for seg in self.read_aloud_segments:
            if isinstance(seg, dict):
                if skip_running and seg.get("file") in running_files:
                    continue
                seg["file"] = ""
                seg["ready"] = False
        self.read_aloud_file = ""

    def _retire_read_aloud_worker(self):
        worker = self.read_aloud_worker
        self.read_aloud_worker = None
        self.read_aloud_worker_index = -1
        if worker is None:
            return
        if worker not in self.read_aloud_retired_workers:
            self.read_aloud_retired_workers.append(worker)
        try:
            worker.requestInterruption()
        except Exception as e:
            log_debug("小说 Edge TTS 中止失败", e)

    def _update_read_aloud_scroll(self):
        if not self.read_aloud_text or not self.read_aloud_segments or not hasattr(self, "manuscript_edit"):
            return
        index = self.read_aloud_segment_index
        if index < 0 or index >= len(self.read_aloud_segments):
            return
        segment = self.read_aloud_segments[index]
        duration = 0
        position = 0
        if self.read_aloud_player is not None:
            duration = max(0, int(self.read_aloud_player.duration()))
            position = max(0, int(self.read_aloud_player.position()))
        ratio_in_segment = min(1.0, position / duration) if duration > 0 else 0.0
        char_pos = int(segment.get("start", 0) + len(segment.get("text", "")) * ratio_in_segment)
        ratio = min(1.0, max(0.0, char_pos / max(1, len(self.read_aloud_text))))
        bar = self.manuscript_edit.verticalScrollBar()
        bar.setValue(int(bar.maximum() * ratio))

    def _scroll_read_aloud_to_segment(self, index, start_position=0):
        if not self.read_aloud_text or index < 0 or index >= len(self.read_aloud_segments):
            return
        segment = self.read_aloud_segments[index]
        ratio = min(1.0, max(0.0, float(segment.get("start", 0)) / max(1, len(self.read_aloud_text))))
        if start_position and self.read_aloud_player is not None and self.read_aloud_player.duration() > 0:
            ratio_in_segment = min(1.0, int(start_position) / max(1, self.read_aloud_player.duration()))
            char_pos = int(segment.get("start", 0) + len(segment.get("text", "")) * ratio_in_segment)
            ratio = min(1.0, max(0.0, char_pos / max(1, len(self.read_aloud_text))))
        bar = self.manuscript_edit.verticalScrollBar()
        bar.setValue(int(bar.maximum() * ratio))

    def export_manuscript_txt(self):
        try:
            self._flush_current_editors()
            if not self._has_manuscript_body():
                QMessageBox.information(self, "导出提示", "当前没有可导出的章节正文。")
                return
            text = _build_manuscript_text(self.current_project)
            path = self._get_export_path("导出完整书稿", self._project_title(), "txt", "文本文件 (*.txt)")
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.set_status_tip(f"已导出完整书稿：{os.path.basename(path)}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def export_manuscript_docx(self):
        try:
            self._flush_current_editors()
            chapters = self.current_project.get("chapters", [])
            has_text = any(isinstance(chap, dict) and str(chap.get("text", "") or "").strip() for chap in chapters)
            if not has_text:
                QMessageBox.information(self, "导出提示", "当前没有可导出的章节正文。")
                return
            title = self._project_title()
            path = self._get_export_path("导出 Word 书稿", title, "docx", "Word 文档 (*.docx)")
            if not path:
                return
            _write_docx_text(path, title, chapters)
            self.set_status_tip(f"已导出 Word 书稿：{os.path.basename(path)}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def refresh_writing_check(self):
        if not hasattr(self, "check_edit") or self._loading or self._refreshing_helpers:
            return
        try:
            self._refreshing_helpers = True
            self._flush_current_editors()
            self._set_text_without_signals(self.check_edit, _build_writing_check_text(self.current_project))
        except Exception as e:
            log_debug("小说写作检查刷新失败", e)
        finally:
            self._refreshing_helpers = False

    def run_global_search(self):
        if not hasattr(self, "search_result_edit"):
            return
        keyword = self.search_input.text().strip()
        self._flush_current_editors()
        self.search_result_edit.setPlainText(_build_search_result_text(self.current_project, keyword))

    def clear_global_search(self):
        if hasattr(self, "search_input"):
            self.search_input.clear()
        if hasattr(self, "search_result_edit"):
            self.search_result_edit.clear()

    def refresh_import_candidate_lists(self):
        if not hasattr(self, "candidate_character_list"):
            return
        previous_checks = self._candidate_check_state_snapshot()
        counts = {
            "characters": len(self.import_candidates.get("characters", [])),
            "lore": len(self.import_candidates.get("lore", [])),
            "foreshadows": len(self.import_candidates.get("foreshadows", [])),
        }
        material_labels = self._candidate_material_labels()
        material_hits = len(material_labels)
        if hasattr(self, "candidate_count_label"):
            total = sum(counts.values()) + material_hits
            failed_count = len(getattr(self, "failed_analysis_chunks", []) or [])
            pending_count = len(getattr(self, "pending_analysis_chapter_ids", []) or [])
            failed_summary = self._failed_candidate_error_summary()
            if total:
                material_text = "/".join(material_labels) if material_labels else "0"
                text = f"候选：人物 {counts['characters']} · 设定 {counts['lore']} · 伏笔 {counts['foreshadows']} · 资料草案 {material_text}"
                if failed_count:
                    text += f" · 待重试 {failed_count} 块"
                if pending_count:
                    text += f" · 待分析 {pending_count} 章"
                self.candidate_count_label.setText(text)
            elif failed_count:
                self.candidate_count_label.setText(f"暂无候选；还有 {failed_count} 个失败文本块待重试。悬停查看原因。")
            elif pending_count:
                self.candidate_count_label.setText(f"暂无候选；有 {pending_count} 个章节等待 AI 分析。")
            else:
                self.candidate_count_label.setText("暂无候选；可先导入 Word/TXT，或使用 AI 分析候选。")
            self.candidate_count_label.setToolTip(failed_summary)
        lists = (
            (self.candidate_character_list, self.import_candidates.get("characters", []), "characters"),
            (self.candidate_lore_list, self.import_candidates.get("lore", []), "lore"),
            (self.candidate_foreshadow_list, self.import_candidates.get("foreshadows", []), "foreshadows"),
        )
        for widget, items, kind in lists:
            widget.blockSignals(True)
            try:
                widget.clear()
                for source_index, item in self._sorted_indexed_records(kind, items):
                    name = str(item.get("name", "") if isinstance(item, dict) else item).strip()
                    if not name:
                        continue
                    row = QListWidgetItem(name)
                    row_key = self._candidate_item_check_key(kind, item, source_index)
                    row.setCheckState(previous_checks.get(row_key, Qt.Checked))
                    row.setData(Qt.UserRole, source_index)
                    row.setData(Qt.UserRole + 1, row_key)
                    row.setToolTip(_candidate_detail_text(kind, item))
                    widget.addItem(row)
            finally:
                widget.blockSignals(False)
        if hasattr(self, "candidate_material_list"):
            self.candidate_material_list.blockSignals(True)
            try:
                self.candidate_material_list.clear()
                for key, label, value in self._candidate_material_items():
                    row = QListWidgetItem(label)
                    row_key = self._candidate_item_check_key("project_materials", {"name": key}, key)
                    default_state = self._default_candidate_material_check_state(key)
                    row.setCheckState(previous_checks.get(row_key, default_state))
                    row.setData(Qt.UserRole, key)
                    row.setData(Qt.UserRole + 1, row_key)
                    row.setToolTip(value)
                    self.candidate_material_list.addItem(row)
            finally:
                self.candidate_material_list.blockSignals(False)

    def _clear_candidate_detail_view(self):
        if hasattr(self, "candidate_detail_edit"):
            self.candidate_detail_edit.clear()
        if hasattr(self, "candidate_detail_box"):
            self.candidate_detail_box.setVisible(False)

    def _candidate_item_check_key(self, kind, item, fallback):
        if kind == "project_materials":
            return f"{kind}:{fallback}"
        item = item if isinstance(item, dict) else {}
        name = str(item.get("name", "") or fallback or "").strip()
        return f"{kind}:{name}"

    def _candidate_check_state_snapshot(self):
        snapshot = {}
        if not hasattr(self, "candidate_character_list"):
            return snapshot
        for kind, widget in (
            ("characters", self.candidate_character_list),
            ("lore", self.candidate_lore_list),
            ("foreshadows", self.candidate_foreshadow_list),
        ):
            items = self.import_candidates.get(kind, [])
            for i in range(widget.count()):
                row = widget.item(i)
                if row is None:
                    continue
                row_key = row.data(Qt.UserRole + 1)
                if not row_key:
                    source_index = row.data(Qt.UserRole)
                    item = items[source_index] if isinstance(source_index, int) and 0 <= source_index < len(items) else {"name": row.text()}
                    row_key = self._candidate_item_check_key(kind, item, source_index if isinstance(source_index, int) else i)
                snapshot[str(row_key)] = row.checkState()
        if hasattr(self, "candidate_material_list"):
            for i in range(self.candidate_material_list.count()):
                row = self.candidate_material_list.item(i)
                if row is None:
                    continue
                key = str(row.data(Qt.UserRole) or "").strip()
                if key:
                    row_key = row.data(Qt.UserRole + 1) or self._candidate_item_check_key("project_materials", {"name": key}, key)
                    snapshot[str(row_key)] = row.checkState()
        return snapshot

    def _candidate_material_items(self):
        labels = (
            ("bible", "圣经"),
            ("world_rules", "世界规则"),
            ("timeline", "时间线"),
            ("summary", "摘要"),
        )
        materials = self.import_candidates.get("project_materials", {})
        if not isinstance(materials, dict):
            return []
        return [
            (key, label, str(materials.get(key, "") or "").strip())
            for key, label in labels
            if str(materials.get(key, "") or "").strip()
        ]

    def _default_candidate_material_check_state(self, key):
        return Qt.Unchecked if key in _MANUAL_PROJECT_MATERIAL_KEYS else Qt.Checked

    def _candidate_material_labels(self, material_result=None):
        labels = (
            ("bible", "圣经"),
            ("world_rules", "世界规则"),
            ("timeline", "时间线"),
            ("summary", "摘要"),
        )
        if material_result is None:
            return [label for _key, label, _value in self._candidate_material_items()]
        if not isinstance(material_result, dict):
            return []
        return [label for key, label in labels if material_result.get(key)]

    def _candidate_material_status_text(self, material_result=None):
        labels = self._candidate_material_labels(material_result)
        return "/".join(labels) if labels else "0"

    def _failed_candidate_error_summary(self, limit=6):
        failed = getattr(self, "failed_analysis_chunks", []) or []
        lines = []
        for item in failed[:limit]:
            if not isinstance(item, dict):
                continue
            index = item.get("index", "?")
            total = item.get("total", "?")
            error = clean_error_text(item.get("error", "") or "未知错误").replace("\n", " ").strip()
            if len(error) > 260:
                error = error[:260] + "..."
            lines.append(f"第 {index}/{total} 块：{error}")
        if len(failed) > limit:
            lines.append(f"另有 {len(failed) - limit} 块失败。")
        return "\n".join(lines)

    def show_import_candidate_detail(self, kind, row):
        if row < 0 or not hasattr(self, "candidate_detail_edit"):
            return
        if kind == "project_materials":
            items = self._candidate_material_items()
            if row >= len(items):
                return
            _key, label, value = items[row]
            if hasattr(self, "candidate_detail_box"):
                self.candidate_detail_box.setVisible(True)
            self.candidate_detail_edit.setPlainText(f"{label}\n\n{value}")
            return
        items = self.import_candidates.get(kind, [])
        widget_map = {
            "characters": self.candidate_character_list,
            "lore": self.candidate_lore_list,
            "foreshadows": self.candidate_foreshadow_list,
        }
        widget = widget_map.get(kind)
        source_index = row
        if widget is not None and row < widget.count():
            source_index = widget.item(row).data(Qt.UserRole)
            if not isinstance(source_index, int):
                source_index = row
        if source_index >= len(items) or not isinstance(items[source_index], dict):
            return
        if hasattr(self, "candidate_detail_box"):
            self.candidate_detail_box.setVisible(True)
        self.candidate_detail_edit.setPlainText(_candidate_detail_text(kind, items[source_index]))

    def clear_import_candidates(self):
        self.import_candidates = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
        self._clear_candidate_detail_view()
        self._clear_candidate_analysis_state()
        self._persist_candidate_analysis_state()
        self.refresh_import_candidate_lists()
        self.set_status_tip("已清空导入候选。")

    def _checked_candidate_indexes(self, widget):
        indexes = []
        for i in range(widget.count()):
            item = widget.item(i)
            if item.checkState() == Qt.Checked:
                source_index = item.data(Qt.UserRole)
                indexes.append(source_index if isinstance(source_index, int) else i)
        return indexes

    def _checked_candidate_material_keys(self):
        keys = []
        if not hasattr(self, "candidate_material_list"):
            return keys
        for i in range(self.candidate_material_list.count()):
            item = self.candidate_material_list.item(i)
            if item.checkState() != Qt.Checked:
                continue
            key = str(item.data(Qt.UserRole) or "").strip()
            if key:
                keys.append(key)
        return keys

    def set_all_import_candidates_checked(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        for widget in (
            self.candidate_character_list,
            self.candidate_lore_list,
            self.candidate_foreshadow_list,
            self.candidate_material_list,
        ):
            for i in range(widget.count()):
                widget.item(i).setCheckState(state)

    def _set_candidate_actions_enabled(self, enabled):
        for btn in getattr(self, "candidate_action_buttons", []):
            btn.setEnabled(bool(enabled))
        if hasattr(self, "candidate_concurrency_combo"):
            self.candidate_concurrency_combo.setEnabled(bool(enabled))
        if hasattr(self, "candidate_analysis_stop_btn"):
            self.candidate_analysis_stop_btn.setVisible(not bool(enabled))
            self.candidate_analysis_stop_btn.setEnabled(not bool(enabled))

    def _prune_candidate_analysis_state_to_existing_chapters(self):
        if not isinstance(self.current_project, dict):
            return
        chapters = self.current_project.get("chapters", [])
        chapters = chapters if isinstance(chapters, list) else []
        existing_ids = {
            str(chap.get("id", "") or "")
            for chap in chapters
            if isinstance(chap, dict) and str(chap.get("id", "") or "")
        }
        if not existing_ids:
            self.pending_analysis_chapter_ids = []
            self.failed_analysis_chunks = []
            return
        old_pending = [str(x) for x in getattr(self, "pending_analysis_chapter_ids", []) or [] if str(x)]
        new_pending = [chapter_id for chapter_id in old_pending if chapter_id in existing_ids]
        if old_pending and not new_pending:
            self.failed_analysis_chunks = []
        self.pending_analysis_chapter_ids = new_pending

    def _sync_candidate_analysis_state(self):
        if not isinstance(self.current_project, dict):
            return
        self._prune_candidate_analysis_state_to_existing_chapters()
        state = _normalize_candidate_analysis_state({
            "failed_candidate_chunks": getattr(self, "failed_analysis_chunks", []) or [],
            "pending_candidate_chapter_ids": getattr(self, "pending_analysis_chapter_ids", []) or [],
        })
        self.failed_analysis_chunks = state.get("failed_candidate_chunks", [])
        self.pending_analysis_chapter_ids = state.get("pending_candidate_chapter_ids", [])
        if not state:
            self.current_project.pop("analysis_state", None)
            return
        self.current_project["analysis_state"] = deepcopy(state)

    def _sync_import_candidates_to_project(self):
        if not isinstance(self.current_project, dict):
            return
        candidates = _normalize_import_candidates(self.import_candidates)
        self.import_candidates = candidates
        if _import_candidates_has_content(candidates):
            self.current_project["import_candidates"] = deepcopy(candidates)
        else:
            self.current_project.pop("import_candidates", None)

    def _clear_candidate_analysis_state(self):
        self.failed_analysis_chunks = []
        self.pending_analysis_chapter_ids = []
        if isinstance(self.current_project, dict):
            state = self.current_project.get("analysis_state", {})
            if isinstance(state, dict):
                state.pop("failed_candidate_chunks", None)
                state.pop("pending_candidate_chapter_ids", None)
                if not state:
                    self.current_project.pop("analysis_state", None)

    def _persist_candidate_analysis_state(self):
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        self._dirty = True
        try:
            self.current_project["updated_at"] = now_str()
            self._save_draft_snapshot()
            self._save_current_project_snapshot_if_named()
        except Exception as e:
            log_debug("小说候选分析状态保存失败", e)

    def _merge_import_candidates(self, incoming):
        incoming = _normalize_ai_candidates(incoming)
        merged = deepcopy(self.import_candidates if isinstance(self.import_candidates, dict) else {})

        def merge_candidate_text(old, new, append=False):
            old = str(old or "").strip()
            new = str(new or "").strip()
            if append:
                cleaned_old = _dedupe_text_lines(old)
                merged_text, did_change = _merge_text_lines_without_duplicates(cleaned_old, new)
                return merged_text, did_change or merged_text != old
            if not new:
                return old, False
            if not old:
                return new, True
            if new == old or new in old:
                return old, False
            if old in new:
                return new, True
            return old, False

        for key in ("characters", "lore", "foreshadows"):
            target = merged.setdefault(key, [])
            if not isinstance(target, list):
                target = []
                merged[key] = target
            by_name = {
                (_character_merge_key(item) if key == "characters" else str(item.get("name", "") or "").strip()): item
                for item in target
                if isinstance(item, dict) and str(item.get("name", "") or "").strip()
            }
            by_alias = {}
            for item in target:
                if not isinstance(item, dict):
                    continue
                alias_keys = _record_alias_keys(item, name_key="name")
                if key == "characters":
                    alias_keys.add(_character_merge_key(item))
                for alias_key in alias_keys:
                    if alias_key:
                        by_alias[alias_key] = item
            for item in incoming.get(key, []):
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "") or "").strip()
                if not name:
                    continue
                merge_key = _character_merge_key(item) if key == "characters" else name
                alias_keys = _record_alias_keys(item, name_key="name")
                if key == "characters":
                    alias_keys.add(merge_key)
                existing = by_name.get(merge_key)
                if existing is None:
                    for alias_key in alias_keys:
                        existing = by_alias.get(alias_key)
                        if existing is not None:
                            break
                if existing is None:
                    clone = deepcopy(item)
                    if key == "foreshadows":
                        clone["status"] = _infer_foreshadow_status(clone, preserve_manual=False)
                    target.append(clone)
                    by_name[merge_key] = clone
                    for alias_key in alias_keys:
                        if alias_key:
                            by_alias[alias_key] = clone
                    continue
                if key == "characters" and name != str(existing.get("name", "") or "").strip():
                    existing_name = str(existing.get("name", "") or "").strip()
                    if existing_name:
                        merged_notes, did_change = merge_candidate_text(
                            existing.get("notes", ""),
                            f"别称：{existing_name}",
                            append=True,
                        )
                        if did_change:
                            existing["notes"] = merged_notes
                    if name == merge_key:
                        existing["name"] = name
                    else:
                        merged_notes, did_change = merge_candidate_text(
                            existing.get("notes", ""),
                            f"别称：{name}",
                            append=True,
                        )
                        if did_change:
                            existing["notes"] = merged_notes
                elif key in {"lore", "foreshadows"} and name != str(existing.get("name", "") or "").strip():
                    merged_desc, did_change = merge_candidate_text(
                        existing.get("description", ""),
                        f"别称：{name}",
                        append=True,
                    )
                    if did_change:
                        existing["description"] = merged_desc
                for field, value in item.items():
                    if field == "name":
                        continue
                    if key == "foreshadows" and field == "status":
                        status_probe = deepcopy(existing)
                        status_probe["status"] = value
                        for extra_field in ("setup_chapter", "payoff_chapter", "description"):
                            if str(item.get(extra_field, "") or "").strip():
                                status_probe[extra_field] = item.get(extra_field, "")
                        inferred = _infer_foreshadow_status(status_probe, preserve_manual=False)
                        if inferred != str(existing.get("status", "") or "").strip():
                            existing["status"] = inferred
                        continue
                    merged_text, did_change = merge_candidate_text(
                        existing.get(field, ""),
                        value,
                        append=field in {"notes", "description"},
                    )
                    if did_change:
                        existing[field] = merged_text
        target_materials = merged.setdefault("project_materials", {})
        if not isinstance(target_materials, dict):
            target_materials = {}
            merged["project_materials"] = target_materials
        for key, value in incoming.get("project_materials", {}).items():
            merged_text, did_change = merge_candidate_text(
                target_materials.get(key, ""),
                value,
                append=True,
            )
            if did_change:
                target_materials[key] = merged_text
        return merged

    def _candidate_analysis_chunk_stats(self, data):
        data = data if isinstance(data, dict) else {}
        return (
            int(data.get("_chunk_total", 0) or 0),
            int(data.get("_chunk_succeeded", 0) or 0),
        )

    def _apply_candidate_analysis_result(self, data):
        data = data if isinstance(data, dict) else {}
        state = _normalize_candidate_analysis_state({
            "failed_candidate_chunks": data.get("_failed_chunks", []),
            "pending_candidate_chapter_ids": self.pending_analysis_chapter_ids,
        })
        self.failed_analysis_chunks = state.get("failed_candidate_chunks", [])
        self.pending_analysis_chapter_ids = state.get("pending_candidate_chapter_ids", [])
        if getattr(self, "_analysis_merge_with_existing", False):
            self.import_candidates = self._merge_import_candidates(data)
        else:
            self.import_candidates = _normalize_ai_candidates(data)
        return self._candidate_analysis_chunk_stats(data)

    def _refresh_candidate_analysis_result_view(self):
        self.refresh_import_candidate_lists()
        self.tabs.setCurrentWidget(self.import_candidates_tab)

    def _set_chapter_ai_actions_enabled(self, enabled):
        for btn in getattr(self, "chapter_ai_action_buttons", []):
            btn.setEnabled(bool(enabled))
        if hasattr(self, "chapter_ai_stop_btn"):
            self.chapter_ai_stop_btn.setVisible(not bool(enabled))
            self.chapter_ai_stop_btn.setEnabled(not bool(enabled))

    def _pending_candidate_analysis_chapter_ids(self):
        chapters = self.current_project.get("chapters", [])
        chapters = chapters if isinstance(chapters, list) else []
        pending = []
        seen = set()
        wanted = {str(x) for x in self.pending_analysis_chapter_ids if str(x)}
        for chap in chapters:
            if not isinstance(chap, dict):
                continue
            chapter_id = str(chap.get("id", "") or "")
            if not chapter_id or chapter_id in seen:
                continue
            if chapter_id in wanted or _chapter_needs_analysis(chap):
                if _chapter_analysis_hash(chap):
                    pending.append(chapter_id)
                    seen.add(chapter_id)
        return pending

    def analyze_import_candidates_with_ai(self):
        if self.analysis_worker is not None and self.analysis_worker.isRunning():
            self.set_status_tip("AI 正在分析候选，请稍等。")
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self.set_ai_settings_expanded(True)
            self.set_status_tip(f"AI 分析失败：{error}")
            QMessageBox.warning(self, "AI 分析失败", error)
            return
        self._flush_current_editors()
        retry_chunk_items = [
            deepcopy(item)
            for item in (getattr(self, "failed_analysis_chunks", []) or [])
            if isinstance(item, dict) and str(item.get("text", "") or "").strip()
        ]
        retrying_failed_chunks = bool(retry_chunk_items)
        if retrying_failed_chunks:
            chapter_ids = list(self.pending_analysis_chapter_ids or self._pending_candidate_analysis_chapter_ids())
            text = "\n\n".join(str(item.get("text", "") or "").strip() for item in retry_chunk_items)
        else:
            chapter_ids = self._pending_candidate_analysis_chapter_ids()
            text = _candidate_analysis_text(self.current_project, "", chapter_ids, include_dossier=False)
        if not text:
            if getattr(self, "failed_analysis_chunks", None):
                message = "有失败块记录，但没有可重试的文本内容。请重新导入或重新分析相关章节。"
                self.set_status_tip(message)
                QMessageBox.information(self, "AI 分析候选", message)
                self._clear_candidate_analysis_state()
                self._persist_candidate_analysis_state()
                self.refresh_import_candidate_lists()
                self.set_status_tip(message)
            else:
                message = "没有新的或改动过的章节需要分析。"
                self.set_status_tip(message)
                QMessageBox.information(self, "AI 分析候选", message)
            return
        self.pending_analysis_chapter_ids = chapter_ids
        if retrying_failed_chunks:
            self._analysis_merge_with_existing = True
        else:
            self._analysis_merge_with_existing = False
        self._sync_candidate_analysis_state()
        concurrency = self._candidate_analysis_concurrency()
        self.analysis_worker = NovelAnalysisWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            text,
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
            concurrency,
            chunks=retry_chunk_items if retrying_failed_chunks else None,
            dossier=_candidate_analysis_dossier_text(self.current_project),
        )
        self.analysis_worker.progress.connect(self.set_status_tip)
        self.analysis_worker.partial_ready.connect(self.on_ai_candidates_partial)
        self.analysis_worker.result_ready.connect(self.on_ai_candidates_ready)
        self.analysis_worker.failed.connect(self.on_ai_candidates_failed)
        self.analysis_worker.finished.connect(self._cleanup_analysis_worker)
        self._analysis_stop_requested_by_user = False
        self._set_candidate_actions_enabled(False)
        if retrying_failed_chunks:
            self.set_status_tip(f"正在重试 AI 分析失败块：共 {len(retry_chunk_items)} 块，并发 {concurrency}...")
        else:
            self.set_status_tip(f"正在启动 AI 分析候选：本次分析 {len(chapter_ids)} 个待更新章节，并发 {concurrency}...")
        self.analysis_worker.start()

    def stop_import_candidate_analysis(self):
        worker = self.analysis_worker
        if worker is None:
            return
        self._analysis_stop_requested_by_user = True
        self.set_status_tip("正在中止 AI 分析候选...")
        try:
            if hasattr(worker, "stop"):
                worker.stop()
            else:
                worker.requestInterruption()
        except Exception as e:
            log_debug("小说候选 AI 中止失败", e)

    def set_chapter_ai_panel_expanded(self, expanded):
        if not hasattr(self, "chapter_ai_body"):
            return
        self.chapter_ai_body.setVisible(True)

    def toggle_chapter_ai_panel(self):
        if not hasattr(self, "chapter_ai_body"):
            return
        self.set_chapter_ai_panel_expanded(True)

    def _chapter_ai_context(self, action):
        self._flush_current_editors()
        return _build_chapter_ai_context(self.current_project, self.current_chapter_index, action)

    def _has_partial_chapter_ai_preview(self, action=None):
        preview_action = getattr(self, "_chapter_ai_preview_action", "")
        if action is not None and preview_action != action:
            return False
        if not (
            getattr(self, "_chapter_ai_preview_is_partial", False)
            and preview_action in {"draft", "outline", "summary"}
            and getattr(self, "_chapter_ai_preview_chapter_id", "") == self._current_chapter_id()
        ):
            return False
        if preview_action in {"outline", "summary"}:
            return True
        return bool(str(self.chapter_ai_preview.toPlainText() or "").strip())

    def _has_partial_draft_preview(self):
        return self._has_partial_chapter_ai_preview("draft")

    def _chapter_ai_context_with_preview(self, action):
        self._flush_current_editors()
        if action != "draft" or not self._has_partial_draft_preview():
            return _build_chapter_ai_context(self.current_project, self.current_chapter_index, action)
        project = deepcopy(self.current_project)
        chapters = project.get("chapters", [])
        if not isinstance(chapters, list) or self.current_chapter_index < 0 or self.current_chapter_index >= len(chapters):
            return _build_chapter_ai_context(self.current_project, self.current_chapter_index, action)
        chap = chapters[self.current_chapter_index]
        if isinstance(chap, dict):
            preview_text = self.chapter_ai_preview.toPlainText().strip()
            chap["text"] = _append_text_without_duplicate_overlap(chap.get("text", ""), preview_text)
        return _build_chapter_ai_context(project, self.current_chapter_index, action)

    def _set_partial_chapter_ai_preview_state(self, enabled, action="draft"):
        self._chapter_ai_preview_is_partial = bool(enabled)
        if enabled:
            if action not in {"draft", "outline", "summary"}:
                action = "draft"
            self._chapter_ai_preview_action = action
            self._chapter_ai_preview_chapter_id = self._current_chapter_id()
        else:
            self._chapter_ai_preview_action = ""
            self._chapter_ai_preview_chapter_id = ""
        self._refresh_chapter_ai_action_labels()

    def _set_partial_draft_preview_state(self, enabled):
        self._set_partial_chapter_ai_preview_state(enabled, "draft")

    def _refresh_chapter_ai_action_labels(self):
        btn = getattr(self, "_chapter_ai_buttons_by_action", {}).get("draft")
        if btn is None:
            return
        partial_action = getattr(self, "_chapter_ai_preview_action", "") if self._has_partial_chapter_ai_preview() else ""
        partial_labels = {
            "draft": ("续写正文", "从当前保留的正文预览继续生成，完成后自动应用并补提纲和摘要/关键事实"),
            "outline": ("续写提纲", "重新生成本章提纲，完成后继续提炼摘要/关键事实"),
            "summary": ("续写摘要", "重新提炼本章摘要/关键事实，完成后结束本次流程"),
        }
        if partial_action in partial_labels:
            text, tooltip = partial_labels[partial_action]
            btn.setText(text)
            btn.setToolTip(tooltip)
            return
        btn.setText("扩写正文并补提纲和摘要")
        btn.setToolTip("先扩写正文，再根据实际正文补提纲和摘要/关键事实")

    def _reset_chapter_ai_sequence(self):
        self._chapter_ai_sequence_active = False
        self._chapter_ai_sequence_chapter_id = ""
        self._chapter_ai_sequence_pending_action = ""
        self._chapter_ai_sequence_started_outline = ""

    def _start_chapter_ai_worker(self, action, context, status_text="", resume_prefix=""):
        self.set_chapter_ai_panel_expanded(True)
        self.chapter_ai_stream_text = str(resume_prefix or "").strip()
        self._chapter_ai_resume_prefix = str(resume_prefix or "").strip() if action == "draft" else ""
        if status_text:
            self.set_status_tip(status_text)
        self.writing_worker = NovelWritingWorker(
            self._chapter_ai_provider.get("base_url", ""),
            self._chapter_ai_provider.get("api_key", ""),
            self._chapter_ai_model,
            action,
            context,
            self._chapter_ai_provider.get("proxy_url", ""),
            self._provider_proxy_mode(self._chapter_ai_provider),
        )
        self.writing_worker.progress.connect(self.set_status_tip)
        self.writing_worker.chunk.connect(self.on_chapter_ai_chunk)
        self.writing_worker.result_ready.connect(self.on_chapter_ai_ready)
        self.writing_worker.failed.connect(self.on_chapter_ai_failed)
        self.writing_worker.finished.connect(self._cleanup_writing_worker)
        self._chapter_ai_stop_requested_by_user = False
        self._chapter_ai_running_action = action
        self._set_chapter_ai_actions_enabled(False)
        self.writing_worker.start()

    def _start_chapter_ai_sequence(self):
        if self.current_chapter_index < 0:
            QMessageBox.warning(self, "AI 写作失败", "请先选择一个章节。")
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self.set_ai_settings_expanded(True)
            self.set_status_tip(f"AI 写作失败：{error}")
            QMessageBox.warning(self, "AI 写作失败", error)
            return
        self._chapter_ai_provider = provider
        self._chapter_ai_model = model
        self._reset_chapter_ai_sequence()
        self._chapter_ai_sequence_active = True
        self._chapter_ai_sequence_chapter_id = self._current_chapter_id()
        self._chapter_ai_sequence_started_outline = self.chapter_outline.toPlainText().strip()
        self._set_partial_chapter_ai_preview_state(False)
        self._chapter_ai_resume_prefix = ""
        self.chapter_ai_preview.setPlainText("")
        try:
            context = self._chapter_ai_context_with_preview("draft")
        except Exception as e:
            self._reset_chapter_ai_sequence()
            QMessageBox.warning(self, "AI 写作失败", str(e))
            return
        self._start_chapter_ai_worker("draft", context, "正在扩写正文...")

    def _continue_chapter_ai_sequence(self, next_action):
        if not getattr(self, "_chapter_ai_sequence_active", False):
            return False
        if self._current_chapter_id() != getattr(self, "_chapter_ai_sequence_chapter_id", ""):
            self._reset_chapter_ai_sequence()
            return False
        try:
            context = self._chapter_ai_context_with_preview(next_action)
        except Exception as e:
            self._reset_chapter_ai_sequence()
            QMessageBox.warning(self, "AI 写作失败", str(e))
            return False
        if next_action == "outline":
            self._auto_outline_chapter_id = self._current_chapter_id()
            self._auto_outline_started_outline = self.chapter_outline.toPlainText().strip()
        if next_action == "summary":
            self._auto_summary_chapter_id = self._current_chapter_id()
            self._auto_summary_started_summary = self.chapter_summary.toPlainText().strip()
            self._auto_summary_started_key_facts = self.chapter_key_facts.toPlainText().strip()
            self._auto_summary_started_linked = self.chapter_linked.text().strip()
        status_map = {
            "outline": "正文已应用，正在根据实际正文补章节提纲...",
            "summary": "正文已应用，正在提炼本章摘要/关键事实...",
        }
        self._chapter_ai_sequence_pending_action = next_action
        self._start_chapter_ai_worker(next_action, context, status_map.get(next_action, "正在继续 AI 写作..."))
        return True

    def run_chapter_ai_action(self, action):
        if self.writing_worker is not None and self.writing_worker.isRunning():
            self.set_status_tip("AI 写作助手正在生成，请稍等。")
            return
        partial_action = ""
        if action == "draft" and self._has_partial_chapter_ai_preview():
            partial_action = getattr(self, "_chapter_ai_preview_action", "")
        resume_partial = partial_action == "draft"
        resume_sequence_action = partial_action if partial_action in {"outline", "summary"} else ""
        if action == "draft" and not resume_partial and not resume_sequence_action:
            self._start_chapter_ai_sequence()
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self.set_ai_settings_expanded(True)
            self.set_status_tip(f"AI 写作失败：{error}")
            QMessageBox.warning(self, "AI 写作失败", error)
            return
        self._chapter_ai_provider = provider
        self._chapter_ai_model = model
        if resume_sequence_action:
            started_outline = self.chapter_outline.toPlainText().strip()
            self._reset_chapter_ai_sequence()
            self._chapter_ai_sequence_active = True
            self._chapter_ai_sequence_chapter_id = self._current_chapter_id()
            self._chapter_ai_sequence_started_outline = started_outline
            self._chapter_ai_resume_prefix = ""
            self.chapter_ai_stream_text = ""
            self.chapter_ai_preview.clear()
            self._set_partial_chapter_ai_preview_state(False)
            if not self._continue_chapter_ai_sequence(resume_sequence_action):
                self._reset_chapter_ai_sequence()
            return
        if resume_partial:
            self._reset_chapter_ai_sequence()
            self._chapter_ai_sequence_active = True
            self._chapter_ai_sequence_chapter_id = self._current_chapter_id()
            self._chapter_ai_sequence_pending_action = "draft"
        try:
            context = self._chapter_ai_context_with_preview(action)
        except Exception as e:
            if resume_partial:
                self._reset_chapter_ai_sequence()
            QMessageBox.warning(self, "AI 写作失败", str(e))
            return
        self.set_chapter_ai_panel_expanded(True)
        self.chapter_ai_stream_text = self.chapter_ai_preview.toPlainText().strip() if resume_partial else ""
        if not resume_partial:
            self._set_partial_chapter_ai_preview_state(False)
            self._chapter_ai_resume_prefix = ""
            self.chapter_ai_preview.setPlainText("")
        else:
            self._chapter_ai_resume_prefix = self.chapter_ai_preview.toPlainText().strip()
            self.set_status_tip("正在从上次中断位置续写正文...")
        if not resume_partial:
            self.set_status_tip("正在启动 AI 写作助手...")
        self._start_chapter_ai_worker(action, context, resume_prefix=self._chapter_ai_resume_prefix)

    def stop_chapter_ai_action(self):
        worker = self.writing_worker
        if worker is None:
            return
        self._chapter_ai_stop_requested_by_user = True
        self.set_status_tip("正在中止 AI 辅助生成...")
        try:
            if hasattr(worker, "stop"):
                worker.stop()
            else:
                worker.requestInterruption()
        except Exception as e:
            log_debug("小说章节 AI 中止失败", e)

    def on_chapter_ai_chunk(self, piece):
        piece = str(piece or "")
        if not piece:
            return
        self.chapter_ai_stream_text += piece
        self.chapter_ai_preview.moveCursor(QTextCursor.End)
        self.chapter_ai_preview.insertPlainText(piece)
        bar = self.chapter_ai_preview.verticalScrollBar()
        bar.setValue(bar.maximum())

    def on_chapter_ai_ready(self, action, content):
        self.set_chapter_ai_panel_expanded(True)
        raw_final_text = str(content or "").strip() or self.chapter_ai_stream_text.strip()
        resume_prefix = getattr(self, "_chapter_ai_resume_prefix", "") if action == "draft" else ""
        if resume_prefix and raw_final_text and not raw_final_text.startswith(resume_prefix):
            final_text = _append_text_without_duplicate_overlap(resume_prefix, raw_final_text)
        else:
            final_text = raw_final_text
        if final_text:
            self.chapter_ai_preview.setPlainText(final_text)
        if getattr(self, "_chapter_ai_stop_requested_by_user", False):
            if final_text:
                if action in {"draft", "outline", "summary"}:
                    self._set_partial_chapter_ai_preview_state(True, action)
                self.set_status_tip("AI 辅助生成已中止，已保留当前预览内容。")
            else:
                self.set_status_tip("AI 辅助生成已中止。")
            self._reset_chapter_ai_sequence()
            return
        labels = {
            "outline": "提纲",
            "draft": "正文",
            "summary": "摘要/关键事实",
            "script_to_novel": "剧本转小说",
            "novel_to_script": "小说转剧本",
            "novel_to_storyboard": "小说转分镜",
            "script_to_storyboard": "剧本转分镜",
        }
        target_map = {
            "outline": "outline",
            "draft": "text",
            "summary": "summary",
        }
        target = target_map.get(action)
        if target:
            self._set_partial_chapter_ai_preview_state(False)
            self._chapter_ai_resume_prefix = ""
            if getattr(self, "_chapter_ai_sequence_active", False):
                if self._current_chapter_id() != getattr(self, "_chapter_ai_sequence_chapter_id", ""):
                    self._reset_chapter_ai_sequence()
                    self.set_status_tip("章节已切换，已停止本次顺序写作流程。")
                    return
                if action == "outline":
                    self.on_auto_chapter_outline_ready("outline", final_text)
                    self.chapter_ai_preview.clear()
                    self._continue_chapter_ai_sequence("summary")
                    return
                if action == "draft":
                    self.chapter_ai_preview.setPlainText(final_text)
                    self.apply_chapter_ai_preview("text")
                    self._continue_chapter_ai_sequence("outline")
                    return
                if action == "summary":
                    self.on_auto_chapter_summary_ready("summary", final_text)
                    self.chapter_ai_preview.clear()
                    self._reset_chapter_ai_sequence()
                    self.set_chapter_ai_panel_expanded(False)
                    self.set_status_tip("章节 AI 已完成：正文、提纲、摘要/关键事实已按顺序更新。")
                    return
            self.apply_chapter_ai_preview(target)
        else:
            self.set_status_tip(f"AI {labels.get(action, '内容')}已生成，可确认后应用。")

    def on_chapter_ai_failed(self, err):
        action = getattr(self, "_chapter_ai_running_action", "")
        sequence_active = bool(getattr(self, "_chapter_ai_sequence_active", False))
        kept_preview = self.chapter_ai_stream_text.strip()
        if kept_preview:
            self.chapter_ai_preview.setPlainText(kept_preview)
        if action == "draft" and kept_preview:
            self._set_partial_chapter_ai_preview_state(True, action)
        elif action in {"outline", "summary"}:
            self._set_partial_chapter_ai_preview_state(True, action)
        self._reset_chapter_ai_sequence()
        action_label = {"draft": "正文", "outline": "提纲", "summary": "摘要"}.get(action, "正文")
        err_text = clean_error_text(err)
        if sequence_active and action == "outline":
            status = f"正文已写入，补提纲失败，可继续补提纲：{err_text[:80]}"
        elif sequence_active and action == "summary":
            status = f"正文已写入，补摘要/关键事实失败，可继续补摘要：{err_text[:80]}"
        else:
            kept_hint = "已保留预览，" if kept_preview else ""
            status = f"AI 写作失败，{kept_hint}可点续写{action_label}继续：{err_text[:80]}"
        self.set_status_tip(status)
        QMessageBox.warning(self, "AI 写作失败", err_text)

    def _cleanup_writing_worker(self):
        worker = self.sender()
        def cleanup():
            try:
                was_current = self.writing_worker is worker
                if was_current:
                    self.writing_worker = None
                if worker is not None:
                    worker.deleteLater()
                if was_current:
                    self._set_chapter_ai_actions_enabled(True)
                    self._chapter_ai_stop_requested_by_user = False
                    self._chapter_ai_running_action = ""
            except Exception as e:
                log_debug("小说章节 AI 线程清理失败", e)
        QTimer.singleShot(0, cleanup)

    def apply_chapter_ai_preview(self, target):
        text = self.chapter_ai_preview.toPlainText().strip()
        if not text or text == "正在生成，请稍等...":
            self.set_status_tip("没有可应用的 AI 结果。")
            return
        should_auto_summary = False
        if target == "outline":
            self.chapter_outline.setPlainText(text)
            inferred_names = self._infer_current_chapter_linked_names(extra_text=text)
            self._merge_chapter_linked_names(inferred_names)
        elif target == "summary":
            summary_text, key_facts_text, linked_names = self._split_chapter_summary_bundle(text)
            if summary_text:
                self.chapter_summary.setPlainText(summary_text)
            elif not key_facts_text and not linked_names:
                self.chapter_summary.setPlainText(text)
            if key_facts_text:
                self.chapter_key_facts.setPlainText(key_facts_text)
            inferred_names = self._infer_current_chapter_linked_names(
                extra_text="\n".join([summary_text, key_facts_text, "、".join(linked_names)])
            )
            self._merge_chapter_linked_names(_normalize_name_list(linked_names + inferred_names))
        elif target == "replace_text":
            self.chapter_text.setPlainText(text)
            should_auto_summary = True
        elif target == "text":
            old = self.chapter_text.toPlainText().strip()
            self.chapter_text.setPlainText(_append_text_without_duplicate_overlap(old, text))
            should_auto_summary = True
        if should_auto_summary:
            inferred_names = self._infer_current_chapter_linked_names(
                extra_text=self.chapter_text.toPlainText()
            )
            self._merge_chapter_linked_names(inferred_names)
        self._mark_chapter_dirty()
        self.chapter_ai_preview.clear()
        self._set_partial_chapter_ai_preview_state(False)
        self._chapter_ai_resume_prefix = ""
        self.set_chapter_ai_panel_expanded(False)
        if should_auto_summary:
            self.set_status_tip("正文已应用。")
        else:
            self.set_status_tip("AI 结果已应用到当前章节。")

    def _maybe_start_auto_chapter_outline(self):
        if self.current_chapter_index < 0:
            return False
        if getattr(self, "auto_outline_worker", None) is not None and self.auto_outline_worker.isRunning():
            return False
        if not str(self.chapter_text.toPlainText() or "").strip():
            return False
        if not hasattr(self, "config") or not hasattr(self, "bar"):
            return False
        provider, model, error = self._current_novel_ai_selection()
        if error:
            return False
        try:
            context = self._chapter_ai_context("outline")
        except Exception as e:
            log_debug("小说章节自动提纲上下文生成失败", e)
            return False
        self._auto_outline_chapter_id = self._current_chapter_id()
        self._auto_outline_started_outline = self.chapter_outline.toPlainText().strip()
        worker = NovelWritingWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            "outline",
            context,
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
        )
        self.auto_outline_worker = worker
        worker.result_ready.connect(self.on_auto_chapter_outline_ready)
        worker.failed.connect(self.on_auto_chapter_outline_failed)
        worker.finished.connect(self._cleanup_auto_outline_worker)
        worker.start()
        return True

    def _maybe_start_auto_chapter_summary(self):
        if self.current_chapter_index < 0:
            return False
        if self.auto_summary_worker is not None and self.auto_summary_worker.isRunning():
            return False
        if not str(self.chapter_text.toPlainText() or "").strip():
            return False
        provider, model, error = self._current_novel_ai_selection()
        if error:
            return False
        try:
            context = self._chapter_ai_context("summary")
        except Exception as e:
            log_debug("小说章节自动摘要上下文生成失败", e)
            return False
        self._auto_summary_chapter_id = self._current_chapter_id()
        self._auto_summary_started_summary = self.chapter_summary.toPlainText().strip()
        self._auto_summary_started_key_facts = self.chapter_key_facts.toPlainText().strip()
        self._auto_summary_started_linked = self.chapter_linked.text().strip()
        worker = NovelWritingWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            "summary",
            context,
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
        )
        self.auto_summary_worker = worker
        worker.result_ready.connect(self.on_auto_chapter_summary_ready)
        worker.failed.connect(self.on_auto_chapter_summary_failed)
        worker.finished.connect(self._cleanup_auto_summary_worker)
        self.set_status_tip("正文已应用，正在自动提炼本章摘要/关键事实...")
        worker.start()
        return True

    def _current_chapter_id(self):
        chapters = self.current_project.get("chapters", [])
        if not isinstance(chapters, list) or self.current_chapter_index < 0 or self.current_chapter_index >= len(chapters):
            return ""
        chap = chapters[self.current_chapter_index]
        return str(chap.get("id", "") or "") if isinstance(chap, dict) else ""

    def on_auto_chapter_summary_ready(self, action, content):
        if action != "summary":
            return
        if self._current_chapter_id() != getattr(self, "_auto_summary_chapter_id", ""):
            return
        current_summary = self.chapter_summary.toPlainText().strip()
        current_key_facts = self.chapter_key_facts.toPlainText().strip()
        current_linked = self.chapter_linked.text().strip()
        summary_text, key_facts_text, linked_names = self._split_chapter_summary_bundle(content)
        if not summary_text and not key_facts_text and not linked_names:
            return
        summary_unchanged = current_summary == getattr(self, "_auto_summary_started_summary", "")
        key_facts_unchanged = current_key_facts == getattr(self, "_auto_summary_started_key_facts", "")
        linked_unchanged = current_linked == getattr(self, "_auto_summary_started_linked", "")
        changed = False
        if summary_text and summary_unchanged:
            self._set_text_without_signals(self.chapter_summary, summary_text)
            changed = True
        if key_facts_text and key_facts_unchanged:
            self._set_text_without_signals(self.chapter_key_facts, key_facts_text)
            changed = True
        if linked_unchanged:
            inferred_names = self._infer_current_chapter_linked_names(
                extra_text="\n".join([summary_text, key_facts_text, "、".join(linked_names)])
            )
            merged_names = _normalize_name_list(
                [
                    name
                    for name in (_normalize_name_list(current_linked) + linked_names + inferred_names)
                    if not _is_generic_character_role_label(name)
                ]
            )
            if merged_names:
                self._set_line_text_without_signals(self.chapter_linked, ", ".join(merged_names))
                changed = True
        if not changed:
            return
        self._mark_chapter_dirty()
        skipped = []
        if summary_text and not summary_unchanged:
            skipped.append("摘要")
        if key_facts_text and not key_facts_unchanged:
            skipped.append("关键事实")
        if linked_names and not linked_unchanged:
            skipped.append("关联人物")
        if skipped:
            self.set_status_tip(f"已自动补齐未手动修改的摘要资料；已保留你手动修改的{'、'.join(skipped)}。")
        else:
            self.set_status_tip("已自动提炼本章摘要/关键事实，并更新本章关联人物。")

    def on_auto_chapter_summary_failed(self, err):
        log_debug("小说章节自动摘要失败", clean_error_text(err))

    def _cleanup_auto_summary_worker(self):
        worker = self.sender()
        def cleanup():
            try:
                if self.auto_summary_worker is worker:
                    self.auto_summary_worker = None
                if worker is not None:
                    worker.deleteLater()
            except Exception as e:
                log_debug("小说章节自动摘要线程清理失败", e)
        QTimer.singleShot(0, cleanup)

    def on_auto_chapter_outline_ready(self, action, content):
        if action != "outline":
            return
        if self._current_chapter_id() != getattr(self, "_auto_outline_chapter_id", ""):
            return
        outline_text = str(content or "").strip()
        if not outline_text:
            return
        current_outline = self.chapter_outline.toPlainText().strip()
        outline_unchanged = current_outline == getattr(self, "_auto_outline_started_outline", "")
        if not outline_unchanged:
            self.set_status_tip("已保留你手动修改的章节提纲。")
            return
        self._set_text_without_signals(self.chapter_outline, outline_text)
        inferred_names = self._infer_current_chapter_linked_names(extra_text=outline_text)
        self._merge_chapter_linked_names(inferred_names)
        self._mark_chapter_dirty()
        self.set_status_tip("已自动补齐章节提纲。")

    def on_auto_chapter_outline_failed(self, err):
        log_debug("小说章节自动提纲失败", clean_error_text(err))

    def _cleanup_auto_outline_worker(self):
        worker = self.sender()
        def cleanup():
            try:
                if self.auto_outline_worker is worker:
                    self.auto_outline_worker = None
                if worker is not None:
                    worker.deleteLater()
            except Exception as e:
                log_debug("小说章节自动提纲线程清理失败", e)
        QTimer.singleShot(0, cleanup)

    def _split_chapter_summary_bundle(self, text):
        text = str(text or "").strip()
        if not text:
            return "", "", []

        def has_value(value):
            if isinstance(value, list):
                return any(has_value(item) for item in value)
            if isinstance(value, dict):
                return any(has_value(item) for item in value.values())
            return bool(str(value or "").strip())

        def labeled_text(label, text):
            lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
            if not lines:
                return ""
            out = []
            label_text = str(label or "").strip()
            for line in lines:
                if len(label_text) >= 2 and line.startswith(label_text):
                    out.append(line)
                else:
                    out.append(f"{label_text}：{line}")
            return "\n".join(out)

        def value_text(value, direct_keys=None, preserve_labels=False):
            direct_keys = tuple(direct_keys or ())
            if isinstance(value, list):
                parts = []
                for item in value:
                    item_text = value_text(item, direct_keys=direct_keys, preserve_labels=preserve_labels)
                    if item_text:
                        parts.append(item_text)
                return "\n".join(parts).strip()
            if isinstance(value, dict):
                for key in direct_keys:
                    if key in value and has_value(value.get(key)):
                        return value_text(
                            value.get(key),
                            direct_keys=direct_keys,
                            preserve_labels=preserve_labels,
                        )
                parts = []
                for key, val in value.items():
                    if not has_value(val):
                        continue
                    item_text = value_text(val, direct_keys=direct_keys, preserve_labels=preserve_labels)
                    if not item_text:
                        continue
                    if preserve_labels:
                        parts.append(labeled_text(key, item_text))
                    else:
                        parts.append(item_text)
                return "\n".join(parts).strip()
            return str(value or "").strip()

        def first_value(data, keys):
            for key in keys:
                if key in data and str(data.get(key, "") or "").strip():
                    return data.get(key)
            return ""

        json_text = text
        fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", json_text, re.IGNORECASE | re.DOTALL)
        if fence_match:
            json_text = fence_match.group(1).strip()
        start = json_text.find("{")
        end = json_text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(json_text[start:end + 1])
            except Exception:
                data = None
            if isinstance(data, dict):
                summary_keys = ("summary", "摘要", "text", "内容", "value")
                fact_keys = ("fact", "事实", "text", "内容", "value")
                character_keys = ("name", "姓名", "名字", "名称", "人物", "角色", "character", "value")
                summary_text = value_text(
                    first_value(data, ("本章摘要", "摘要", "summary", "chapter_summary")),
                    direct_keys=summary_keys,
                )
                key_facts_text = value_text(first_value(data, (
                    "本章需继承的关键事实",
                    "需继承的关键事实",
                    "继承的关键事实",
                    "继承事实",
                    "本章关键事实",
                    "关键事实",
                    "本章事件",
                    "key_facts",
                    "keyFacts",
                    "facts",
                    "inheritance",
                )), direct_keys=fact_keys, preserve_labels=True)
                linked_value = first_value(data, (
                    "本章关联人物",
                    "关联人物",
                    "涉及人物",
                    "出场人物",
                    "人物",
                    "角色",
                    "本章角色",
                    "linked_characters",
                    "linkedCharacters",
                    "characters",
                    "roles",
                ))
                linked_text = value_text(linked_value, direct_keys=character_keys)
                linked_names = [
                    name
                    for name in _normalize_name_list(linked_text)
                    if name and name not in {"无", "没有", "暂无", "无新增"}
                ]
                summary_text = _compact_chapter_summary_text(summary_text)
                key_facts_text = _compact_chapter_key_facts_text(key_facts_text)
                if summary_text or key_facts_text or linked_names:
                    return summary_text, key_facts_text, linked_names

        lines = text.splitlines()
        summary_lines = []
        key_facts_lines = []
        linked_lines = []
        current = "summary"

        def parse_heading(line):
            line = line.strip()
            line = re.sub(
                r"^\s*(?:#{1,6}\s*|[-*•]\s+|[（(]?\d+[）).、]\s*|[一二三四五六七八九十]+[、.]\s*)",
                "",
                line,
            )
            line = re.sub(r"^(?:\*\*|__)", "", line)
            line = re.sub(r"(?:\*\*|__)$", "", line).strip()
            bracket_match = re.match(r"^[\[【]([^\]】]+)[\]】]\s*(.*)$", line)
            if bracket_match:
                rest = re.sub(r"^[：:]\s*", "", bracket_match.group(2).strip())
                line = f"{bracket_match.group(1).strip()}：{rest}" if rest else bracket_match.group(1).strip()
            line = line.strip("[]【】")
            patterns = (
                (r"^(?:本章)?摘要(?:[：:]\s*(.*))?$", "summary"),
                (r"^(?:本章)?(?:事件|剧情|内容概述|内容摘要|情节概述|剧情概述)(?:[：:]\s*(.*))?$", "summary"),
                (r"^(?:本章)?需继承的关键事实(?:[：:]\s*(.*))?$", "key_facts"),
                (r"^(?:本章)?继承的关键事实(?:[：:]\s*(.*))?$", "key_facts"),
                (r"^(?:本章)?继承事实(?:[：:]\s*(.*))?$", "key_facts"),
                (r"^(?:本章)?关键事实(?:[：:]\s*(.*))?$", "key_facts"),
                (r"^(?:本章)?后续需继承(?:[：:]\s*(.*))?$", "key_facts"),
                (r"^(?:本章)?(?:后续影响|连续性事实|延续事实|需延续信息|必须继承|留给后文)(?:[：:]\s*(.*))?$", "key_facts"),
                (r"^(?:本章)?关联人物(?:[：:]\s*(.*))?$", "linked_characters"),
                (r"^(?:本章)?涉及人物(?:[：:]\s*(.*))?$", "linked_characters"),
                (r"^(?:本章)?出场人物(?:[：:]\s*(.*))?$", "linked_characters"),
                (r"^(?:本章)?相关(?:人物|角色)(?:[：:]\s*(.*))?$", "linked_characters"),
                (r"^(?:本章)?人物(?:[：:]\s*(.*))?$", "linked_characters"),
                (r"^(?:本章)?角色(?:[：:]\s*(.*))?$", "linked_characters"),
            )
            for pattern, section in patterns:
                match = re.match(pattern, line)
                if match:
                    return section, (match.group(1) or "").strip()
            return None, None

        for line in lines:
            section, remainder = parse_heading(line)
            if section:
                current = section
                if remainder:
                    if remainder in {"无", "没有", "暂无", "无新增"}:
                        continue
                    if current == "summary":
                        summary_lines.append(remainder)
                    elif current == "linked_characters":
                        linked_lines.append(remainder)
                    else:
                        key_facts_lines.append(remainder)
                continue
            if current == "linked_characters":
                linked_lines.append(line)
            elif current == "key_facts":
                if line.strip() not in {"无", "没有", "暂无", "无新增"}:
                    key_facts_lines.append(line)
            else:
                if line.strip() not in {"无", "没有", "暂无", "无新增"}:
                    summary_lines.append(line)

        summary_text = _compact_chapter_summary_text("\n".join(summary_lines).strip())
        key_facts_text = _compact_chapter_key_facts_text("\n".join(key_facts_lines).strip())
        linked_names = [
            name
            for name in _normalize_name_list("\n".join(linked_lines))
            if name and name not in {"无", "没有", "暂无", "无新增"}
        ]
        if not key_facts_text and "关键事实" not in text and "需继承" not in text:
            return summary_text, "", linked_names
        return summary_text, key_facts_text, linked_names

    def _infer_current_chapter_linked_names(self, extra_text=""):
        chapters = self.current_project.get("chapters", [])
        if not isinstance(chapters, list) or self.current_chapter_index < 0 or self.current_chapter_index >= len(chapters):
            return []
        chapter = chapters[self.current_chapter_index]
        if not isinstance(chapter, dict):
            return []
        return _normalize_name_list(
            _infer_linked_character_names(self.current_project, chapter, extra_text)
            + _infer_core_character_names(self.current_project, chapter, extra_text)
        )

    def _merge_chapter_linked_names(self, names):
        merged = _normalize_name_list(
            [
                name
                for name in (_normalize_name_list(self.chapter_linked.text()) + _normalize_name_list(names))
                if not _is_generic_character_role_label(name)
            ]
        )
        if merged:
            self.chapter_linked.setText(", ".join(merged))

    def on_ai_candidates_ready(self, data):
        total, succeeded = self._apply_candidate_analysis_result(data)
        self._persist_candidate_analysis_state()
        self._refresh_candidate_analysis_result_view()
        material_hits = self._candidate_material_status_text()
        if self.failed_analysis_chunks:
            reason = self._failed_candidate_error_summary(limit=1).replace("\n", " ")
            reason_tail = f" 原因：{reason}" if reason else ""
            self.set_status_tip(
                f"AI 分析部分完成：成功 {succeeded}/{total} 块，失败 {len(self.failed_analysis_chunks)} 块；下次点击 AI 分析候选会优先重试失败块。{reason_tail}"
            )
        else:
            self.set_status_tip(
                f"AI 分析完成：人物 {len(self.import_candidates['characters'])}，设定 {len(self.import_candidates['lore'])}，伏笔 {len(self.import_candidates['foreshadows'])}，资料草案 {material_hits}"
            )

    def on_ai_candidates_partial(self, data, completed, total):
        self._apply_candidate_analysis_result(data)
        self._persist_candidate_analysis_draft_state()
        self._refresh_candidate_analysis_result_view()
        material_hits = self._candidate_material_status_text()
        failed_count = len(self.failed_analysis_chunks)
        tail = f"，待重试 {failed_count} 块" if failed_count else ""
        if failed_count:
            reason = self._failed_candidate_error_summary(limit=1).replace("\n", " ")
            if reason:
                tail += f"，原因：{reason}"
        self.set_status_tip(
            f"AI 分析进度 {completed}/{total}：人物 {len(self.import_candidates['characters'])}，设定 {len(self.import_candidates['lore'])}，伏笔 {len(self.import_candidates['foreshadows'])}，资料草案 {material_hits}{tail}"
        )

    def on_ai_candidates_failed(self, err):
        existing_total = sum(len(self.import_candidates.get(key, [])) for key in ("characters", "lore", "foreshadows"))
        materials = self.import_candidates.get("project_materials", {})
        material_total = sum(1 for value in materials.values() if str(value or "").strip()) if isinstance(materials, dict) else 0
        if existing_total or material_total:
            self._persist_candidate_analysis_state()
        tail = "；已完成的候选已保留" if existing_total or material_total else ""
        self.set_status_tip(f"AI 分析失败：{clean_error_text(err)[:100]}{tail}")
        QMessageBox.warning(self, "AI 分析失败", clean_error_text(err))

    def _cleanup_analysis_worker(self):
        worker = self.sender()
        def cleanup():
            try:
                if self.analysis_worker is worker:
                    self.analysis_worker = None
                if worker is not None:
                    worker.deleteLater()
                self._set_candidate_actions_enabled(True)
                if getattr(self, "_analysis_stop_requested_by_user", False):
                    self._analysis_stop_requested_by_user = False
                    self._persist_candidate_analysis_state()
                    self.refresh_import_candidate_lists()
                    self.set_status_tip("AI 分析候选已中止，已保留当前候选和待重试状态。")
            except Exception as e:
                log_debug("小说候选分析线程清理失败", e)
        QTimer.singleShot(0, cleanup)

    def apply_import_candidates(self):
        self._clear_candidate_detail_view()
        checked = {
            "characters": self._checked_candidate_indexes(self.candidate_character_list),
            "lore": self._checked_candidate_indexes(self.candidate_lore_list),
            "foreshadows": self._checked_candidate_indexes(self.candidate_foreshadow_list),
            "project_materials": self._checked_candidate_material_keys(),
        }
        if not any(checked.values()) and not self.pending_analysis_chapter_ids:
            self.set_status_tip("请先勾选要加入项目的候选内容。")
            return
        result = _apply_import_candidates(self.current_project, self.import_candidates, checked)
        added = result.get("added", result) if isinstance(result, dict) else {}
        merged = result.get("merged", {}) if isinstance(result, dict) else {}
        materials = result.get("materials", {}) if isinstance(result, dict) else {}
        removed_candidates = int(result.get("removed_candidates", 0) or 0) if isinstance(result, dict) else 0
        if any(materials.values()):
            self._refresh_project_material_editors()
        has_failed_chunks = bool(getattr(self, "failed_analysis_chunks", []) or [])
        status_changes = _auto_classify_default_statuses(
            self.current_project,
            self.pending_analysis_chapter_ids or [],
        )
        if has_failed_chunks:
            analyzed_count = 0
        else:
            analyzed_count = _mark_chapters_analyzed(
                self.current_project.get("chapters", []),
                self.pending_analysis_chapter_ids,
            )
            self.pending_analysis_chapter_ids = []
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        self.refresh_import_candidate_lists()
        if (
            not any(added.values())
            and not any(merged.values())
            and not any(materials.values())
            and not analyzed_count
            and not any(status_changes.values())
            and not removed_candidates
        ):
            self.set_status_tip("没有新增或补充内容：已勾选的候选可能为空，或信息没有变化。")
            return
        self._reload_character_list()
        self._reload_lore_list()
        self._reload_foreshadow_list()
        self.refresh_writing_check()
        self.refresh_manuscript()
        self._update_stats_label()
        self._mark_dirty()
        self._save_current_work("候选入库后保存")
        failed_tail = f"；仍有 {len(self.failed_analysis_chunks)} 个失败块待重试，暂不标记章节已完整分析" if has_failed_chunks else ""
        material_text = self._candidate_material_status_text(materials)
        status_tail = (
            f"；自动分类 章节 {status_changes.get('chapters', 0)} / 伏笔 {status_changes.get('foreshadows', 0)}"
            if any(status_changes.values())
            else ""
        )
        self.set_status_tip(
            f"已处理候选：新增 人物 {added.get('characters', 0)} / 设定 {added.get('lore', 0)} / 伏笔 {added.get('foreshadows', 0)}；"
            f"补充 人物 {merged.get('characters', 0)} / 设定 {merged.get('lore', 0)} / 伏笔 {merged.get('foreshadows', 0)}；"
            f"资料草案 {material_text}；已清理候选 {removed_candidates}；已标记分析 {analyzed_count} 章{status_tail}{failed_tail}"
        )

    def _load_initial_project(self):
        data, path = load_initial_project_data()
        self._load_project_data(data, path)
        self.refresh_project_list()

    def _autosave_draft(self):
        if self._loading:
            return
        if not self._dirty and self._draft_saved_once:
            return
        try:
            self._flush_current_editors()
            self._sync_candidate_analysis_state()
            self._sync_import_candidates_to_project()
            self.current_project["updated_at"] = now_str()
            self._save_draft_snapshot()
        except Exception as e:
            log_debug("小说草稿自动保存失败", e)

    def _save_draft_snapshot(self):
        save_draft_project(self.current_project)
        self._draft_saved_once = True

    def _save_current_project_snapshot_if_named(self):
        path = str(self.current_project_path or "").strip()
        if not path or path == NOVEL_DRAFT_FILE:
            return
        save_project_file(path, self.current_project)
        self._remember_project_path(path)

    def _persist_candidate_analysis_draft_state(self):
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        self._dirty = True
        try:
            self.current_project["updated_at"] = now_str()
            self._save_draft_snapshot()
        except Exception as e:
            log_debug("小说候选分析草稿保存失败", e)

    def _remember_project_path(self, path):
        remember_project_path(path)

    def save_current_project(self):
        self._flush_current_editors()
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        if not self.current_project_path or self.current_project_path == NOVEL_DRAFT_FILE:
            return self.save_project_as_named()
        try:
            save_project_file(self.current_project_path, self.current_project)
            self._remember_project_path(self.current_project_path)
            self._save_draft_snapshot()
            self._notify_project_store_changed()
            self._dirty = False
            self._update_stats_label()
            return True
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return False

    def save_project_as_named(self):
        self._flush_current_editors()
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        title = self.title_edit.text().strip() or "未命名小说"
        name, ok = QInputDialog.getText(self, "保存小说项目", "名称：", text=title)
        if not ok:
            return False
        name = _safe_name(name)
        if not name:
            QMessageBox.warning(self, "保存失败", "名称不能为空。")
            return False
        path = named_project_path(name)
        if os.path.exists(path):
            ret = QMessageBox.question(self, "覆盖确认", f"已存在 {name}.json，是否覆盖？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return False
        try:
            self.current_project["meta"]["title"] = name
            save_named_project(name, self.current_project)
            self._remember_project_path(path)
            self._save_draft_snapshot()
            self.current_project_path = path
            self._update_stats_label()
            self._dirty = False
            self._notify_project_store_changed()
            self.set_status_tip(f"已保存：{name}")
            return True
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return False

    def refresh_project_list(self):
        self._update_project_list()

    def _notify_project_store_changed(self):
        try:
            self.refresh_project_list()
        except Exception as e:
            log_debug("小说项目列表同步失败", e)

    def open_named_project_panel(self):
        item = self.project_list.currentItem()
        if item is not None:
            self._open_selected_project_item(item)
        else:
            self.set_status_tip("请先在列表里选择一个小说项目。")

    def _open_selected_project_item(self, item):
        if self._loading or self._opening_project:
            return
        path = item.data(Qt.UserRole) if item is not None else ""
        if not path:
            return
        if os.path.abspath(str(path)) == os.path.abspath(str(self.current_project_path or "")):
            self.set_status_tip(f"已打开：{os.path.basename(path)}")
            return
        self.open_project_file(path)

    def open_project_file(self, path):
        if self._opening_project:
            return
        path = str(path or "").strip()
        if not path:
            return
        if os.path.abspath(path) == os.path.abspath(str(self.current_project_path or "")):
            self.set_status_tip(f"已打开：{os.path.basename(path)}")
            return
        self._opening_project = True
        try:
            data = load_json_file(path, None)
            if not isinstance(data, dict):
                QMessageBox.warning(self, "打开失败", "项目文件无效。")
                return
            self.set_status_tip(f"正在打开：{os.path.basename(path)}")
            self._save_current_work("打开前保存", refresh_project_list=False, preserve_project_mtime=True)
            self._load_project_data(data, path, defer_helpers=True)
            self._remember_project_path(path)
            self._save_draft_snapshot()
            self._select_project_list_path(path)
            self.set_status_tip(f"已打开：{os.path.basename(path)}")
        finally:
            self._opening_project = False

    def new_project(self):
        name, ok = QInputDialog.getText(self, "新建小说项目", "名称：", text="未命名小说")
        if not ok:
            return
        name = _safe_name(name) or "未命名小说"
        self._save_current_work("新建前保存")
        data = _default_project()
        data["meta"]["title"] = name
        self._load_project_data(data, "")
        self._save_draft_snapshot()
        try:
            clear_last_project_path()
        except Exception as e:
            log_debug("小说最近项目记录清理失败", e)
        self._update_stats_label()
        self.set_status_tip("已新建为自动草稿；点击“保存项目”可加入项目列表。")

    def clear_current_draft(self):
        ret = QMessageBox.question(
            self,
            "清空草稿",
            "确定清空当前小说草稿和编辑区内容吗？\n\n这不会删除左侧已经保存的项目文件。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        self._reset_to_empty_draft()
        self._dirty = False
        self.set_status_tip("已清空当前草稿。")

    def _reset_to_empty_draft(self, title="未命名小说"):
        data = _default_project()
        data["meta"]["title"] = title or "未命名小说"
        self._load_project_data(data, NOVEL_DRAFT_FILE)
        self._save_draft_snapshot()
        try:
            clear_last_project_path()
        except Exception as e:
            log_debug("小说最近项目记录清理失败", e)
        self._notify_project_store_changed()

    def delete_selected_project(self):
        item = self.project_list.currentItem()
        path = item.data(Qt.UserRole) if item is not None else ""
        if not path:
            return
        is_current_project = os.path.abspath(path) == os.path.abspath(self.current_project_path or "")
        ret = QMessageBox.question(
            self,
            "删除确认",
            f"确定删除 {os.path.basename(path)} 吗？"
            + ("\n\n当前正在编辑这个项目，删除后会同时清空当前界面和自动草稿。" if is_current_project else ""),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return
        try:
            os.remove(path)
            if is_current_project:
                self._reset_to_empty_draft()
                self.set_status_tip("已删除当前小说项目，并清空当前草稿。")
            else:
                self._notify_project_store_changed()
                self.set_status_tip("已删除小说项目。")
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))

    def export_project(self):
        self._flush_current_editors()
        path = self._get_export_path("导出小说项目", self._project_title(), "json", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            save_json_file(path, self.current_project)
            self.set_status_tip("小说项目已导出。")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def import_project(self):
        path = self._get_open_path("导入小说项目", "JSON 文件 (*.json)")
        if not path:
            return
        data = load_json_file(path, None)
        if not isinstance(data, dict):
            QMessageBox.warning(self, "导入失败", "JSON 不是有效项目。")
            return
        self._save_current_work("导入前保存")
        self._load_project_data(data, "")
        self._save_draft_snapshot()
        self._notify_project_store_changed()
        self.set_status_tip("小说项目已导入。")

    def import_word_script(self):
        path = self._get_open_path("导入 Word 剧本", "Word 文档 (*.docx)")
        if not path:
            return
        try:
            text = _read_docx_text(path)
            if not text.strip():
                QMessageBox.warning(self, "导入失败", "Word 文档没有可读取的正文。")
                return
            self._import_script_text(text, path, "Word")
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))

    def import_txt_script(self):
        path = self._get_open_path("导入 TXT 剧本", "文本文件 (*.txt)")
        if not path:
            return
        try:
            text = _read_txt_text(path)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))
            return
        if not text.strip():
            QMessageBox.warning(self, "导入失败", "TXT 文件没有可读取的正文。")
            return
        self._import_script_text(text, path, "TXT")

    def _import_script_text(self, text, path, source_label):
        try:
            import_type, ok = self._get_combo_choice("选择导入类型", "请选择这份文档的内容类型：", IMPORT_TYPE_OPTIONS, 0)
            if not ok:
                return
            chapters = _split_chapters_from_text(text, import_type)
            if not chapters:
                QMessageBox.warning(self, "导入失败", "没有拆出可导入的章节。")
                return

            import_mode, ok = self._get_combo_choice("选择导入方式", "请选择导入方式：", ["追加到当前项目", "创建为新项目"], 0)
            if not ok:
                return

            ret = QMessageBox.question(
                self,
                "导入确认",
                (
                    f"导入类型：{import_type}\n"
                    f"已从 {source_label} 识别出 {len(chapters)} 个内容单元。\n"
                    f"导入方式：{import_mode}\n"
                    "是否继续？"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if ret != QMessageBox.Yes:
                return

            self.last_import_text = text
            title = os.path.splitext(os.path.basename(path))[0]
            if import_mode == "创建为新项目":
                self._import_script_as_new_project(text, chapters, title, source_label, import_type)
            else:
                self._import_script_append(text, chapters, title, source_label, import_type)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))

    def _import_script_append(self, text, chapters, title, source_label, import_type):
        self._clear_candidate_detail_view()
        if not self._has_saved_project_path():
            self._save_current_work(f"{source_label}导入前保存")
        self._flush_current_editors()
        project_chapters = self.current_project.setdefault("chapters", [])
        existing_keys = {
            key
            for key in (_chapter_dedupe_key(chap) for chap in project_chapters)
            if key
        }
        unique_chapters = []
        skipped = 0
        for chap in chapters:
            key = _chapter_dedupe_key(chap)
            if key and key in existing_keys:
                skipped += 1
                continue
            if key:
                existing_keys.add(key)
            unique_chapters.append(chap)
        if not unique_chapters:
            QMessageBox.information(self, "导入提示", "这些章节已经在当前项目里，没有重复追加。")
            self.import_candidates = _extract_import_candidates(text)
            self._sync_import_candidates_to_project()
            self._save_after_import()
            self.refresh_import_candidate_lists()
            self.tabs.setCurrentWidget(self.import_candidates_tab)
            self.set_status_tip(f"{source_label} 内容已分析候选，章节未重复追加。")
            return

        project_chapters.extend(unique_chapters)
        if self.title_edit.text().strip() in ("", "未命名小说"):
            self.title_edit.setText(title)
            self.current_project.setdefault("meta", {})["title"] = title

        self.import_candidates = _extract_import_candidates(text)
        self.pending_analysis_chapter_ids = [str(chap.get("id", "") or "") for chap in unique_chapters if isinstance(chap, dict)]
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        self._reload_chapter_list(len(self.current_project.get("chapters", [])) - len(unique_chapters))
        self.refresh_import_candidate_lists()
        self.tabs.setCurrentWidget(self.import_candidates_tab)
        self._mark_dirty()
        save_message = self._save_after_import()
        self._set_import_done_status(source_label, import_type, len(unique_chapters), skipped, save_message)

    def _import_script_as_new_project(self, text, chapters, title, source_label, import_type):
        self._clear_candidate_detail_view()
        self._save_current_work(f"{source_label}导入新项目前保存")
        data = _default_project()
        safe_title = _safe_name(title) or "未命名小说"
        data["meta"]["title"] = safe_title
        data["chapters"] = chapters
        data["updated_at"] = now_str()
        project_path = unique_project_path(safe_title)
        save_project_file(project_path, data)
        self._load_project_data(data, project_path)
        self._remember_project_path(project_path)
        self._save_draft_snapshot()
        self.import_candidates = _extract_import_candidates(text)
        self.pending_analysis_chapter_ids = [str(chap.get("id", "") or "") for chap in chapters if isinstance(chap, dict)]
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        save_project_file(project_path, self.current_project)
        self._save_draft_snapshot()
        self.refresh_import_candidate_lists()
        self.tabs.setCurrentWidget(self.import_candidates_tab)
        self._notify_project_store_changed()
        self._dirty = False
        self._update_stats_label()
        self._set_import_done_status(source_label, import_type, len(chapters), 0, "已创建并保存为新项目。")

    def _set_import_done_status(self, source_label, import_type, added_count, skipped, save_message):
        candidate_counts = {
            "characters": len(self.import_candidates.get("characters", [])),
            "lore": len(self.import_candidates.get("lore", [])),
            "foreshadows": len(self.import_candidates.get("foreshadows", [])),
        }
        self.set_status_tip(
            f"{source_label} 导入完成：类型 {import_type}，新增 {added_count}，跳过重复 {skipped}，"
            f"候选人物 {candidate_counts['characters']}，候选设定 {candidate_counts['lore']}，候选伏笔 {candidate_counts['foreshadows']}。{save_message}"
        )

    def set_status_tip(self, text):
        text = str(text or "")
        self.setToolTip(text)
        if hasattr(self, "status_label"):
            self.status_label.setText(text)
        try:
            candidate_page_visible = (
                hasattr(self, "tabs")
                and hasattr(self, "import_candidates_tab")
                and self.tabs.currentWidget() is self.import_candidates_tab
            )
            if candidate_page_visible and hasattr(self, "candidate_count_label"):
                self.candidate_count_label.setText(text)
                self.candidate_count_label.setToolTip(text)
        except Exception as e:
            log_debug("小说候选状态提示同步失败", e)
