import os
import tempfile
import hashlib
import re
import json
import time
import traceback
import uuid
from copy import deepcopy

from PySide6.QtCore import QFileSystemWatcher, QObject, QSize, QUrl, Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog as _QtInputDialog,
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

from .core import HISTORY_DIR, clean_error_text, get_provider, load_json_file, log_debug, now_str, save_config, save_json_file
from .model_bar_mixin import SimpleModelBarMixin
from .novel_import import (
    _MANUAL_PROJECT_MATERIAL_KEYS,
    _apply_import_candidates,
    _candidate_analysis_text,
    _candidate_analysis_dossier_text,
    _candidate_detail_text,
    _chapter_source_label_map,
    _extract_import_candidates,
    _extract_structured_framework_chapter_plan,
    _extract_framework_chapter_plan_from_locations,
    _build_local_framework_chapter_plan,
    _extract_framework_planning_parameters,
    _framework_numbered_source,
    _framework_story_section,
    _foreshadow_candidate_identity_keys,
    _foreshadow_candidate_is_terminal_review,
    _foreshadow_candidate_target_code_keys,
    _foreshadow_candidate_target_keys,
    _foreshadow_chapter_field_source_item,
    _foreshadow_chapter_update_text,
    _foreshadow_source_item,
    _foreshadow_terminal_review_description,
    _foreshadow_terminal_review_should_replace,
    _foreshadow_review_context,
    _foreshadow_review_chapter_chunks,
    _foreshadow_review_dossier_text,
    _is_framework_placeholder_chapter_title,
    _is_framework_scope_title,
    _merge_framework_chapter_plans,
    _normalize_ai_candidates,
    _strip_internal_candidate_markers,
    _read_docx_text,
    _read_txt_text,
    _write_docx_text,
)
from .novel_storage import (
    NOVEL_DIR,
    NOVEL_DRAFT_FILE,
    append_novel_diagnostic_event,
    clear_last_project_path,
    ensure_novel_storage,
    get_style_profile,
    list_project_summaries,
    load_character_style_library,
    load_style_profile_library,
    load_initial_project_data,
    named_project_path,
    remember_project_path,
    save_draft_project,
    save_named_project,
    save_novel_diagnostic_latest_exchange,
    save_novel_diagnostic_snapshot,
    append_novel_memory_diagnostic_event,
    save_project_file,
    sync_style_profile_library_from_projects,
    remove_character_style,
    upsert_character_style,
    upsert_style_profile,
    unique_project_backup_path,
    unique_project_path,
)
from .novel_utils import (
    CHAPTER_ANALYSIS_HASH_VERSION,
    IMPORT_TYPE_OPTIONS,
    LORE_TYPE_OPTIONS,
    NOVEL_AI_CONTEXT_LIMIT,
    STYLE_CARD_CACHE_VERSION,
    STYLE_SHEET_CACHE_VERSION,
    _append_text_without_duplicate_overlap,
    _append_ai_style_profile_to_context,
    _apply_long_form_memory_update,
    _build_chapter_ai_context,
    _build_volume_opening_handoff_context,
    _build_chapter_logic_repair_context,
    _build_long_form_memory_finalize_context,
    _build_long_form_memory_reconcile_context,
    _build_long_form_memory_repair_context,
    _build_long_form_selection_index,
    _build_style_finalize_context,
    _build_style_baseline_context,
    _build_style_cards_context,
    _build_style_execution_context,
    _build_style_persona_context,
    _build_style_audit_context,
    _build_style_profile_request_context,
    _build_style_profile_units,
    _build_style_rewrite_context,
    _build_style_sheet_context,
    _build_style_sheet_merge_context,
    _build_manuscript_text,
    _build_search_result_text,
    _build_writing_check_text,
    _auto_classify_default_statuses,
    _body_display_len,
    _character_merge_key,
    _character_list_text,
    _update_chapter_analysis_status_cache,
    _chapter_dedupe_key,
    _chapter_analysis_hash,
    _chapter_list_text,
    _candidate_long_term_review_reasons,
    _compact_chapter_key_facts_text,
    _compact_chapter_summary_text,
    _compose_style_profile,
    _chapter_needs_analysis,
    _chapter_tooltip,
    _dedupe_chapters,
    _dedupe_text_lines,
    _ensure_foreshadow_codes,
    _foreshadow_code_number,
    _import_candidates_has_content,
    _mark_chapters_analyzed,
    _merge_foreshadow_description_without_bloat,
    _merge_text_lines_without_duplicates,
    _merge_foreshadow_status,
    _default_project,
    _default_long_form_memory,
    _foreshadow_list_text,
    _normalize_foreshadow_code,
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
    _clean_chapter_plan_story_boundary,
    _normalize_chapter_plan_foundation,
    _normalize_framework_analysis,
    _canonical_chapter_plan_event_id,
    _canonical_chapter_plan_stage_id,
    _normalize_foreshadow_review_observations,
    _normalize_import_candidates,
    _normalize_name_list,
    _normalize_narrative_strategy_profile,
    _normalize_creative_intent_contract,
    _core_motive_progression_guidance,
    _terminal_window_bounds,
    _procedural_plot_guard_guidance,
    _build_volume_handoff_source,
    _build_volume_handoff_record_catalog,
    _compact_volume_continuity_anchors,
    _compact_volume_handoff_records,
    _inherit_continuation_record_ids,
    _normalize_series_continuation,
    _rebase_long_form_memory_for_volume_continuation,
    _volume_two_framework_template_text,
    _normalize_semantic_style_archive,
    _normalize_project,
    _entity_naming_guidance,
    _strip_static_foreshadow_outline_fields,
    _strip_volume_handoff_outline_metadata,
    _project_without_private_notes,
    _project_list_text,
    _project_ready_for_completion,
    _project_summary_record_text,
    _project_meta_text,
    _project_summary_text,
    _parse_style_audit_result,
    _parse_style_cards_result,
    _parse_style_execution_result,
    _parse_style_finalize_result,
    _parse_chapter_logic_repair_result,
    _parse_memory_reconciliation_result,
    _parse_memory_repair_result,
    _merge_long_form_memory_reconciliation_patch,
    _merge_long_form_memory_repair_full,
    _merge_long_form_memory_repair_patch,
    _apply_chapter_prose_repair_patches,
    _apply_chapter_logic_repair_patches,
    _chapter_logic_audit_blocking_issues,
    _chapter_logic_audit_validation_errors,
    _repair_literal_count_claims,
    _sanitize_prose_internal_references,
    _literalize_long_form_memory_evidence,
    _normalize_long_form_structural_refs,
    _validate_long_form_memory_update,
    _record_alias_keys,
    _safe_name,
    _sanitize_import_candidates_for_long_form,
    _local_split_chapter_title,
    _split_chapters_from_text,
    _split_manuscript_into_target_chapters,
    _style_draft_mismatch_reasons,
    _style_finalize_acceptance_errors,
    _style_finalize_error_is_hard,
    _style_candidate_needs_rescue,
    _style_candidate_rank,
    _style_output_target_from_context,
    _story_conflict_pacing_guidance,
    _target_words,
    FRAMEWORK_IMPORT_TYPE,
)
from .novel_creation_wizard import (
    NovelCreationWorkspaceDialog,
    NovelCreationWizardDialog,
    build_chapter_plan_foundation,
    create_creation_wizard_draft,
    creation_meta_display_values,
    creation_wizard_payload_from_project_draft,
    format_creation_preview,
    format_creation_text,
    migrate_creation_bible_display_text,
    mark_creation_wizard_draft_completed,
    normalize_creation_result,
    story_requires_explicit_power_levels,
)
from .fanqie_upload import (
    FANQIE_LEGACY_ACCOUNT_ID,
    FanqieBatchUploadDialog,
    FanqieBatchUploadWorker,
    build_fanqie_upload_task,
    stop_fanqie_manual_browser_workers,
)
from .widgets import ProviderModelBar, WideComboBox, install_combo_arrow_overlay
from .workers import EdgeTTSWorker, NovelAnalysisWorker, NovelCandidatePostprocessWorker, NovelChapterEventPlacementWorker, NovelChapterPlanWorker, NovelContextBuildWorker, NovelForeshadowReviewPostprocessWorker, NovelForeshadowReviewWorker, NovelFrameworkImportWorker, NovelVolumeFrameworkAlignmentWorker, NovelVolumeFrameworkWorker, NovelVolumeHandoffWorker, NovelVolumeIntentWorker, NovelWritingWorker

NOVEL_PERF_LOG_ENABLED = str(os.environ.get("GPT_NOVEL_PERF_LOG", "") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Every request in the chapter-writing workflow shares one stage-level retry
# budget. The initial request is followed by at most three retries.
_CHAPTER_AI_RETRY_DELAYS = (10, 20, 30)
_CHAPTER_AI_MAX_RETRIES = len(_CHAPTER_AI_RETRY_DELAYS)
_CHAPTER_AI_RETRY_STAGES = frozenset(
    {
        "context_build",
        "draft",
        "style_profile",
        "style_baseline",
        "style_sheet",
        "style_sheet_merge",
        "style_persona",
        "style_cards",
        "style_rules",
        "style_audit",
        "style_rewrite",
        "style_plot_extract",
        "style_finalize",
        "memory_finalize",
        "memory_repair",
        "logic_repair",
        "memory_reconcile",
    }
)


class QInputDialog(_QtInputDialog):
    """保留 Qt 输入对话框 API，并让选项列表显示统一的上下箭头。"""

    @staticmethod
    def getItem(
        parent,
        title,
        label,
        items,
        current=0,
        editable=True,
        flags=Qt.WindowFlags(),
        inputMethodHints=Qt.InputMethodHints(),
    ):
        dialog = _QtInputDialog(parent)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        dialog.setComboBoxItems([str(item) for item in (items or [])])
        dialog.setComboBoxEditable(bool(editable))
        dialog.setInputMethodHints(inputMethodHints)
        if flags:
            dialog.setWindowFlags(flags)

        combo = dialog.findChild(QComboBox)
        if combo is not None:
            if combo.count():
                combo.setCurrentIndex(max(0, min(int(current), combo.count() - 1)))
            install_combo_arrow_overlay(combo)

        accepted = dialog.exec() == QDialog.Accepted
        return dialog.textValue(), accepted

_SORT_MISSING_ORDER = 10 ** 9
_CHAPTER_PLAN_BATCH_SIZE = 50
# Leave room for the chapter-planning system prompt and request envelope.
# The returned context itself remains below the application's 128,000-char
# limit even for large existing projects and imported frameworks.
_CHAPTER_PLAN_CONTEXT_CHAR_BUDGET = NOVEL_AI_CONTEXT_LIMIT - 10000
_CHAPTER_PLAN_BATCH_STATE_VERSION = 3

_CREATIVE_INTENT_FIELDS = (
    ("primary_line", "本卷主线"),
    ("core_motive", "核心动机"),
    ("supporting_lines", "辅助线"),
    ("core_relationships", "核心关系"),
    ("stage_progression", "阶段推进"),
    ("reading_experience", "目标读感"),
    ("supporting_line_usage", "辅助线用法"),
    ("ending_boundaries", "结局边界"),
)

_NARRATIVE_STRATEGY_LIST_FIELDS = (
    ("satisfaction_currencies", "爽感货币"),
    ("emotional_resonance_axes", "情绪共鸣轴"),
    ("chapter_variation_pool", "章节变化池"),
)
_NARRATIVE_STRATEGY_DIALOG_FIELDS = (
    ("audience_direction", "受众方向"),
    ("genre_world", "题材与世界"),
    ("core_reader_promise", "核心读者承诺"),
    ("core_motive", "核心动机"),
    ("primary_story_engine", "主叙事发动机"),
    ("secondary_story_engine", "副叙事发动机"),
    ("planning_grammar", "章节规划语法"),
    ("satisfaction_currencies", "爽感货币"),
    ("emotional_resonance_axes", "情绪共鸣轴"),
    ("pacing_strategy", "节奏策略"),
    ("low_exposition_strategy", "低说明性叙事"),
    ("chapter_variation_pool", "章节变化池"),
    ("story_direction", "故事方向"),
)
_CHAPTER_PLAN_FOUNDATION_FIELDS = (
    ("summary", "故事简介"),
    ("core_motive", "核心动机"),
    ("ending_promise", "结尾承诺"),
    ("global_hard_boundaries", "写作硬边界"),
)
_CHAPTER_PLAN_ARC_FIELDS = (
    ("name", "阶段名称"),
    ("start_chapter", "起始章节"),
    ("end_chapter", "结束章节"),
    ("source_stage", "原框架阶段"),
    ("macro_phase", "宏观节奏位置"),
    ("dominant_line", "主导剧情线"),
    ("supporting_lines", "辅助剧情线"),
    ("relationship_goal", "人物关系目标"),
    ("end_state", "阶段结束状态"),
)
_CHAPTER_PLAN_QUICK_ARC_FIELDS = (
    ("name", "阶段名称"),
    ("start_chapter", "起始章节"),
    ("end_chapter", "结束章节"),
    ("source_stage", "原框架阶段"),
    ("dominant_line", "阶段主线"),
    ("end_state", "阶段后部局面"),
)
_CHAPTER_PLAN_OPTIONAL_TEXT_FIELDS = (
    ("relationship_task", "关系推进"),
    ("investigation_scope", "调查范围"),
    ("chapter_function", "本章功能"),
    ("conflict_intensity", "冲突强度"),
    ("setup_ratio", "铺垫比例"),
    ("character_task", "人物任务"),
    ("mainline_task", "主线任务"),
    ("planning_method", "规划方式"),
    ("start_state", "开始状态"),
    ("must_happen", "必须发生"),
    ("satisfaction_payoff", "爽点兑现"),
    ("emotional_resonance", "情绪共鸣"),
    ("relationship_change", "关系变化"),
    ("exposition_compression", "说明处理"),
    ("variation_pattern", "变化方式"),
    ("foreshadow_task", "伏笔任务"),
    ("story_direction", "故事方向"),
    ("goal", "本章目标"),
    ("main_event", "核心事件"),
    ("conflict", "核心冲突"),
    ("turning_point", "转折"),
    ("emotional_shift", "情绪变化"),
)
_CHAPTER_PLAN_OPTIONAL_LIST_FIELDS = (
    ("dynamic_modules", "动态模块"),
    ("settings", "本章涉及设定"),
    ("foreshadows", "本章伏笔动作"),
    ("required_events", "必须发生"),
)
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


def _chinese_chapter_number(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value or "")
    if number <= 0 or number > 9999:
        return str(number)
    digits = "零一二三四五六七八九"
    units = ("", "十", "百", "千")
    values = [int(char) for char in str(number)]
    result = []
    zero_pending = False
    total = len(values)
    for position, digit in enumerate(values):
        unit_index = total - position - 1
        if digit == 0:
            if result and any(values[position + 1:]):
                zero_pending = True
            continue
        if zero_pending:
            result.append("零")
            zero_pending = False
        if not (digit == 1 and unit_index == 1 and not result):
            result.append(digits[digit])
        result.append(units[unit_index])
    return "".join(result)


def _numbered_export_chapter_title(index, title):
    clean_title = re.sub(
        r"^第\s*[一二两三四五六七八九十百千万零〇\d]+\s*章\s*[：:、.\-—]?\s*",
        "",
        str(title or "").strip(),
    ).strip()
    prefix = f"第{_chinese_chapter_number(index)}章"
    return f"{prefix} {clean_title}" if clean_title else prefix


def _record_text_for_sort(item, fields):
    item = item if isinstance(item, dict) else {}
    return "\n".join(str(item.get(field, "") or "") for field in fields)


def _volume_handoff_display_text(handoff):
    """Render the structured handoff as readable notes instead of raw JSON."""
    handoff = handoff if isinstance(handoff, dict) else {}
    labels = {
        "volume_summary": "上一卷总体收束",
        "ending_state": "卷末状态",
        "character_states": "人物状态",
        "relationship_states": "关系状态",
        "world_state": "上一卷结束时的世界状态",
        "resolved_threads": "已完成主线",
        "open_threads": "未完成主线",
        "continuity_boundaries": "连续性事实",
        "reusable_characters": "可复用人物",
        "reusable_lore": "可复用设定",
        "reusable_foreshadows": "继续追踪的伏笔",
        "resolved_foreshadows": "已回收伏笔",
        "discarded_foreshadows": "已废弃伏笔",
        "inherited_materials": "上一卷基础资料",
        "last_chapter": "上一卷最后一章",
        "story_time": "故事时间",
        "location": "地点",
        "current_situation": "当前处境",
        "last_action": "最后动作",
        "immediate_tension": "即时矛盾",
        "name": "名称",
        "role": "身份",
        "goal": "目标",
        "secret": "隐藏秘密",
        "personality": "性格/特点",
        "voice": "语言风格",
        "notes": "长期备注",
        "state": "当前状态",
        "relationship": "关系",
        "characters": "相关人物",
        "unresolved": "未解决内容",
        "type": "类型",
        "description": "说明",
        "story_known": "已知事实",
        "code": "编号",
        "status": "状态",
        "setup_chapter": "埋设章节",
        "payoff_chapter": "回收章节",
        "revealed": "已揭示内容",
        "remaining_secret": "尚未揭开的秘密",
        "result": "结果",
        "index": "章节序号",
        "title": "章节标题",
        "outline": "章节提纲",
        "key_facts": "关键事实",
        "text": "正文",
        "bible": "上一卷圣经",
        "world_rules": "上一卷世界规则",
        "fact": "事实",
        "category": "类别",
        "source_chapters": "来源章节",
    }

    def label(key):
        return labels.get(str(key), str(key).replace("_", " "))

    def add_value(lines, key, value, indent=""):
        if value in (None, "", [], {}):
            return
        if isinstance(value, dict):
            lines.append(f"{indent}{label(key)}：")
            for child_key, child_value in value.items():
                add_value(lines, child_key, child_value, indent + "  ")
            return
        if isinstance(value, list):
            lines.append(f"{indent}{label(key)}：")
            for child in value:
                if isinstance(child, dict):
                    first = str(child.get("name", "") or child.get("title", "") or "").strip()
                    if first:
                        lines.append(f"{indent}  {first}")
                    for child_key, child_value in child.items():
                        if child_key in {"name", "title"}:
                            continue
                        add_value(lines, child_key, child_value, indent + "    ")
                elif str(child or "").strip():
                    lines.append(f"{indent}  {str(child).strip()}")
            return
        text = str(value).strip()
        if text:
            lines.append(f"{indent}{label(key)}：{text}")

    lines = ["上一卷交接摘要", ""]
    ordered_sections = (
        ("volume_summary", "上一卷收束"),
        ("ending_state", "卷末状态"),
        ("character_states", "人物状态"),
        ("relationship_states", "关系状态"),
        ("world_state", "世界状态"),
        ("resolved_threads", "已完成主线"),
        ("open_threads", "未完成主线"),
        ("continuity_anchors", "跨卷事实锚点"),
        ("continuity_boundaries", "连续性事实"),
        ("reusable_characters", "本卷可复用人物"),
        ("reusable_lore", "本卷可复用设定"),
        ("reusable_foreshadows", "本卷继续追踪的伏笔"),
        ("resolved_foreshadows", "上一卷已回收伏笔"),
        ("discarded_foreshadows", "上一卷已废弃伏笔"),
        ("inherited_materials", "上一卷基础资料"),
        ("last_chapter", "上一卷最后一章"),
    )
    for key, title in ordered_sections:
        value = handoff.get(key)
        if value in (None, "", [], {}):
            continue
        lines.append(f"【{title}】")
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                add_value(lines, child_key, child_value, "")
        elif isinstance(value, list):
            add_value(lines, key, value, "")
        else:
            lines.append(str(value).strip())
        lines.append("")
    return "\n".join(lines).strip()


def _creative_intent_display_text(contract):
    contract = _normalize_creative_intent_contract(contract)
    labels = dict(_CREATIVE_INTENT_FIELDS)
    if contract.get("core_motive"):
        labels["core_motive"] = "核心动机主线"
    lines = []
    for key, _label in _CREATIVE_INTENT_FIELDS:
        value = contract.get(key, []) if key == "supporting_lines" else contract.get(key, "")
        if key == "primary_line" and contract.get("core_motive") == value:
            continue
        if not value:
            continue
        if isinstance(value, list):
            text = "、".join(str(item) for item in value if str(item or "").strip())
        else:
            text = str(value or "").strip()
        if text:
            lines.append(f"{labels[key]}：{text}")
    return "\n\n".join(lines) or "尚未生成创作意图。"


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


class VolumeTwoSetupDialog(QDialog):
    def __init__(self, source_meta, handoff, parent=None, setup=None):
        super().__init__(parent)
        self.setWindowTitle("创建新卷续写")
        self.setMinimumSize(760, 620)
        self.resize(860, 700)
        source_meta = deepcopy(source_meta if isinstance(source_meta, dict) else {})
        self._handoff = deepcopy(handoff if isinstance(handoff, dict) else {})
        setup = setup if isinstance(setup, dict) else {}
        setup_meta = setup.get("meta", {}) if isinstance(setup.get("meta", {}), dict) else {}
        for key in ("genre", "style", "pov", "target_words"):
            if str(setup_meta.get(key, "") or "").strip():
                source_meta[key] = str(setup_meta.get(key, "") or "").strip()

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.title_edit = QLineEdit()
        source_title = str(source_meta.get("title", "") or "").strip() or "未命名小说"
        next_volume_number = int(source_meta.get("_next_volume_number", 2) or 2)
        self.title_edit.setText(
            str(setup_meta.get("title", "") or "").strip()
            or f"{source_title} 第{next_volume_number}卷"
        )
        self.genre_edit = QLineEdit(str(source_meta.get("genre", "") or ""))
        self.style_edit = QLineEdit(str(source_meta.get("style", "") or ""))
        self.target_words_edit = QLineEdit(str(source_meta.get("target_words", "") or ""))
        self.pov_combo = WideComboBox()
        self.pov_combo.addItems(["第一人称", "第三人称", "多视角"])
        pov = str(source_meta.get("pov", "第三人称") or "第三人称")
        index = self.pov_combo.findText(pov)
        self.pov_combo.setCurrentIndex(index if index >= 0 else 1)
        form.addRow("本卷书名", self.title_edit)
        form.addRow("类型", self.genre_edit)
        form.addRow("风格", self.style_edit)
        form.addRow("叙事人称", self.pov_combo)
        form.addRow("目标字数（万字）", self.target_words_edit)
        root.addLayout(form)

        tabs = QTabWidget()
        self.requirements_edit = PlainTextEdit()
        self.requirements_edit.setMinimumHeight(190)
        self.requirements_edit.setPlaceholderText("例如：加强追夫火葬场、爽点密集、情绪拉满、强反转，双方感情不要有大的变化，设计约20万字本卷。")
        self.requirements_edit.setPlainText(str(setup.get("requirements", "") or "").strip())
        tabs.addTab(self.requirements_edit, "本卷要求")
        handoff_edit = PlainTextEdit()
        handoff_edit.setReadOnly(True)
        handoff_edit.setPlainText(_volume_handoff_display_text(self._handoff))
        tabs.addTab(handoff_edit, "上一卷交接摘要")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox()
        confirm_btn = buttons.addButton("分析本卷创作意图", QDialogButtonBox.AcceptRole)
        confirm_btn.setObjectName("primary")
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.RejectRole)
        cancel_btn.setObjectName("ghost")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def request_data(self):
        return {
            "meta": {
                "title": self.title_edit.text().strip(),
                "genre": self.genre_edit.text().strip(),
                "style": self.style_edit.text().strip(),
                "pov": self.pov_combo.currentText().strip() or "第三人称",
                "target_words": self.target_words_edit.text().strip(),
                "status": "草稿",
            },
            "requirements": self.requirements_edit.toPlainText().strip(),
        }

    def accept(self):
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, "创建新卷续写", "请填写本卷书名。")
            return
        super().accept()


class VolumeCreativeIntentDialog(QDialog):
    def __init__(self, contract, parent=None, volume_mode=True):
        super().__init__(parent)
        self.setWindowTitle("确认本卷创作意图" if volume_mode else "调整创作主线")
        self.setMinimumSize(780, 620)
        self.resize(880, 700)
        self._contract = _normalize_creative_intent_contract(contract)
        self._editors = {}
        self._dialog_fields = _CREATIVE_INTENT_FIELDS
        if not volume_mode:
            self._dialog_fields = tuple(
                (key, "核心动机主线" if key == "core_motive" else label)
                for key, label in _CREATIVE_INTENT_FIELDS
                if key != "primary_line"
            )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        intro = QLabel(
            "AI 已把本卷要求整理成一份简短创作意图。这里只确认主线有没有理解错；"
            "交接摘要只负责连续性事实，不会替用户决定本卷写什么。"
            if volume_mode else
            "这里保存的是章节规划必须服从的创作主线。只在主线、辅助线用途或结局边界有偏差时修改。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        root.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(0, 0, 8, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for key, label in self._dialog_fields:
            editor = PlainTextEdit()
            editor.setMinimumHeight(62 if key != "supporting_lines" else 76)
            editor.setMaximumHeight(130)
            if key == "supporting_lines":
                editor.setPlaceholderText("每行一条辅助线；没有可留空")
                editor.setPlainText("\n".join(self._contract.get(key, [])))
            else:
                value = self._contract.get(key, "")
                if key == "core_motive" and not value:
                    value = self._contract.get("primary_line", "")
                editor.setPlainText(str(value or ""))
            self._editors[key] = editor
            form.addRow(label, editor)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox()
        confirm_btn = buttons.addButton(
            "确认并生成本卷框架" if volume_mode else "保存修改",
            QDialogButtonBox.AcceptRole,
        )
        confirm_btn.setObjectName("primary")
        cancel_btn = buttons.addButton("暂不生成", QDialogButtonBox.RejectRole)
        cancel_btn.setObjectName("ghost")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def contract(self):
        result = {}
        for key, _label in self._dialog_fields:
            text = self._editors[key].toPlainText().strip()
            if key == "supporting_lines":
                values = _normalize_name_list(re.split(r"[\n\r、，,；;]+", text))
                if values:
                    result[key] = values
            elif text:
                result[key] = text
        if result.get("core_motive") and not result.get("primary_line"):
            result["primary_line"] = result["core_motive"]
        result["version"] = str(self._contract.get("version", "1") or "1")
        result["source"] = str(self._contract.get("source", "volume_user_requirements") or "volume_user_requirements")
        return _normalize_creative_intent_contract(result)

    def accept(self):
        contract = self.contract()
        if not contract.get("primary_line"):
            QMessageBox.warning(self, "确认创作意图", "请确认本卷主线。")
            return
        self._confirmed_contract = contract
        super().accept()

    def confirmed_contract(self):
        return deepcopy(getattr(self, "_confirmed_contract", self.contract()))


class VolumeTwoFrameworkDialog(QDialog):
    def __init__(self, framework, handoff, parent=None):
        super().__init__(parent)
        self.setWindowTitle("确认本卷框架")
        self.setMinimumSize(920, 680)
        self.resize(1040, 760)
        self._framework = deepcopy(framework if isinstance(framework, dict) else {})
        self._handoff = deepcopy(handoff if isinstance(handoff, dict) else {})
        self._creative_intent_contract = _normalize_creative_intent_contract(
            self._framework.get("creative_intent_contract", {})
        )
        self._confirmed_framework = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        meta = self._framework.get("meta", {})
        meta = meta if isinstance(meta, dict) else {}
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        self.title_edit = QLineEdit(str(meta.get("title", "") or ""))
        self.genre_edit = QLineEdit(str(meta.get("genre", "") or ""))
        self.style_edit = QLineEdit(str(meta.get("style", "") or ""))
        self.target_words_edit = QLineEdit(str(meta.get("target_words", "") or ""))
        self.pov_combo = WideComboBox()
        self.pov_combo.addItems(["第一人称", "第三人称", "多视角"])
        pov = str(meta.get("pov", "第三人称") or "第三人称")
        index = self.pov_combo.findText(pov)
        self.pov_combo.setCurrentIndex(index if index >= 0 else 1)
        self.premise_edit = PlainTextEdit()
        self.premise_edit.setFixedHeight(62)
        self.premise_edit.setPlainText(str(meta.get("premise", "") or ""))
        fields = (
            ("书名", self.title_edit),
            ("类型", self.genre_edit),
            ("风格", self.style_edit),
            ("目标字数（万字）", self.target_words_edit),
            ("叙事人称", self.pov_combo),
        )
        for index, (label, editor) in enumerate(fields):
            column = (index % 3) * 2
            row = index // 3
            form.addWidget(QLabel(label), row, column)
            form.addWidget(editor, row, column + 1)
        form.addWidget(QLabel("故事简介"), 2, 0)
        form.addWidget(self.premise_edit, 2, 1, 1, 5)
        root.addLayout(form)

        materials = self._framework.get("project_materials", {})
        materials = materials if isinstance(materials, dict) else {}
        self.tabs = QTabWidget()
        self.bible_edit = PlainTextEdit()
        self.bible_edit.setPlainText(str(materials.get("bible", "") or ""))
        self.tabs.addTab(self.bible_edit, "小说圣经")
        self.world_rules_edit = PlainTextEdit()
        self.world_rules_edit.setPlainText(str(materials.get("world_rules", "") or ""))
        self.tabs.addTab(self.world_rules_edit, "世界观/规则")
        self.chapter_plan_edit = PlainTextEdit()
        self.chapter_plan_edit.setPlainText(
            json.dumps(self._framework.get("chapter_plan", {}), ensure_ascii=False, indent=2)
        )
        self.tabs.addTab(self.chapter_plan_edit, "章节框架")
        self.characters_edit = PlainTextEdit()
        self.characters_edit.setPlainText(
            json.dumps(self._framework.get("characters", []), ensure_ascii=False, indent=2)
        )
        self.tabs.addTab(self.characters_edit, "人物")
        self.lore_edit = PlainTextEdit()
        self.lore_edit.setPlainText(
            json.dumps(self._framework.get("lore", []), ensure_ascii=False, indent=2)
        )
        self.tabs.addTab(self.lore_edit, "设定")
        self.foreshadows_edit = PlainTextEdit()
        self.foreshadows_edit.setPlainText(
            json.dumps(self._framework.get("foreshadows", []), ensure_ascii=False, indent=2)
        )
        self.tabs.addTab(self.foreshadows_edit, "伏笔")
        handoff_edit = PlainTextEdit()
        handoff_edit.setReadOnly(True)
        handoff_edit.setPlainText(_volume_handoff_display_text(self._handoff))
        self.tabs.addTab(handoff_edit, "上一卷交接")
        intent_edit = PlainTextEdit()
        intent_edit.setReadOnly(True)
        intent_edit.setPlainText(_creative_intent_display_text(self._creative_intent_contract))
        self.tabs.addTab(intent_edit, "本卷创作意图")
        root.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox()
        confirm_btn = buttons.addButton("确认并创建本卷", QDialogButtonBox.AcceptRole)
        confirm_btn.setObjectName("primary")
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.RejectRole)
        cancel_btn.setObjectName("ghost")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _json_editor_value(editor, label, expected_type):
        text = editor.toPlainText().strip()
        if not text:
            return expected_type()
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} 不是合法 JSON：第 {exc.lineno} 行，第 {exc.colno} 列。")
        if not isinstance(value, expected_type):
            expected_name = "对象" if expected_type is dict else "数组"
            raise ValueError(f"{label} 必须是 JSON {expected_name}。")
        return value

    def framework_data(self):
        try:
            chapter_plan = self._json_editor_value(self.chapter_plan_edit, "章节框架", dict)
            characters = self._json_editor_value(self.characters_edit, "人物", list)
            lore = self._json_editor_value(self.lore_edit, "设定", list)
            foreshadows = self._json_editor_value(self.foreshadows_edit, "伏笔", list)
        except ValueError as exc:
            QMessageBox.warning(self, "确认本卷框架", str(exc))
            return None
        source_materials = self._framework.get("project_materials", {})
        source_materials = source_materials if isinstance(source_materials, dict) else {}
        return {
            "meta": {
                "title": self.title_edit.text().strip(),
                "genre": self.genre_edit.text().strip(),
                "style": self.style_edit.text().strip(),
                "pov": self.pov_combo.currentText().strip() or "第三人称",
                "target_words": self.target_words_edit.text().strip(),
                "status": "草稿",
                "premise": self.premise_edit.toPlainText().strip(),
            },
            "project_materials": {
                "bible": self.bible_edit.toPlainText().strip(),
                "world_rules": self.world_rules_edit.toPlainText().strip(),
                "timeline": str(source_materials.get("timeline", "") or "").strip(),
                "summary": str(source_materials.get("summary", "") or "").strip(),
            },
            "characters": characters,
            "lore": lore,
            "foreshadows": foreshadows,
            "chapter_plan": chapter_plan,
            "creative_intent_contract": deepcopy(self._creative_intent_contract),
        }

    def accept(self):
        framework = self.framework_data()
        if framework is None:
            return
        if not str(framework.get("meta", {}).get("title", "") or "").strip():
            QMessageBox.warning(self, "确认本卷框架", "请填写本卷书名。")
            return
        self._confirmed_framework = framework
        super().accept()

    def confirmed_framework(self):
        return deepcopy(self._confirmed_framework or self._framework)


class NarrativeStrategyProfileDialog(QDialog):
    def __init__(self, profile, parent=None, planning_gate=False):
        super().__init__(parent)
        self.setWindowTitle("确认叙事策略画像" if planning_gate else "叙事策略画像")
        self.setMinimumSize(760, 680)
        self._profile = _normalize_narrative_strategy_profile(profile)
        self._editors = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        intro = QLabel(
            "AI 已根据小说框架生成叙事策略画像。请核对并直接修改有出入的内容；"
            "确认后才会开始生成详细章节。"
            if planning_gate else
            "这里保存的是当前项目实际用于章节规划和正文扩写的叙事策略。修改后将影响后续生成。"
        )
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        root.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(0, 0, 8, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        list_keys = {key for key, _label in _NARRATIVE_STRATEGY_LIST_FIELDS}
        for key, label in _NARRATIVE_STRATEGY_DIALOG_FIELDS:
            editor = PlainTextEdit()
            editor.setMinimumHeight(58 if key not in list_keys else 72)
            editor.setMaximumHeight(110 if key not in list_keys else 130)
            if key in list_keys:
                values = _normalize_name_list(self._profile.get(key, []))
                editor.setPlainText("\n".join(values))
                editor.setPlaceholderText("每行一项")
            else:
                editor.setPlainText(str(self._profile.get(key, "") or ""))
            self._editors[key] = editor
            form.addRow(label, editor)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox()
        confirm_text = "确认并生成章节" if planning_gate else "保存修改"
        confirm_btn = buttons.addButton(confirm_text, QDialogButtonBox.AcceptRole)
        confirm_btn.setObjectName("primary")
        cancel_btn = buttons.addButton(
            "暂不生成章节" if planning_gate else "取消",
            QDialogButtonBox.RejectRole,
        )
        cancel_btn.setObjectName("ghost")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def profile(self):
        result = {}
        list_keys = {key for key, _label in _NARRATIVE_STRATEGY_LIST_FIELDS}
        for key, editor in self._editors.items():
            text = editor.toPlainText().strip()
            if key in list_keys:
                values = _normalize_name_list(re.split(r"[\n\r、，,；;]+", text))
                if values:
                    result[key] = values
            elif text:
                result[key] = text
        result["version"] = str(self._profile.get("version", "1") or "1")
        return _normalize_narrative_strategy_profile(result)


class ChapterPlanFoundationDialog(QDialog):
    RegenerateResult = 2

    def __init__(self, master_plan, state, validator=None, parent=None):
        super().__init__(parent)
        self.setObjectName("chapter_plan_foundation_dialog")
        self.setWindowTitle("核对章节规划")
        self.setMinimumSize(840, 600)
        self.resize(960, 680)
        self.setStyleSheet("""
        QDialog#chapter_plan_foundation_dialog {
            background: #17191f;
        }
        QScrollArea#foundation_review_scroll,
        QWidget#foundation_review_content {
            background: transparent;
            border: none;
        }
        QFrame#foundation_header,
        QFrame#foundation_summary,
        QFrame#foundation_stage_detail {
            background: #1c1f26;
            border: 1px solid #2a2e38;
            border-radius: 7px;
        }
        QFrame#foundation_strategy_strip {
            background: #192331;
            border: 1px solid #2a4058;
            border-radius: 6px;
        }
        QLabel#foundation_title {
            color: #f4f6fa;
            font-size: 16px;
            font-weight: 600;
        }
        QLabel#foundation_subtitle,
        QLabel#foundation_section_hint,
        QLabel#foundation_metric_label {
            color: #9aa3b2;
        }
        QLabel#foundation_metric_value {
            color: #e8edf5;
            font-weight: 600;
        }
        QLabel#foundation_section_title,
        QLabel#foundation_item_title {
            color: #c8d0dd;
            font-weight: 600;
        }
        QLabel#foundation_item_value,
        QLabel#foundation_stage_value {
            color: #d7dce5;
            font-size: 13px;
        }
        QPushButton#primary {
            background: #2f7de1;
            color: #ffffff;
            border: 1px solid #438cec;
            border-radius: 5px;
            min-height: 30px;
            padding: 0 14px;
            font-weight: 600;
        }
        QPushButton#primary:hover {
            background: #3b88ea;
        }
        QPushButton#ghost {
            background: #20242c;
            color: #d9dee8;
            border: 1px solid #383e4a;
            border-radius: 5px;
            min-height: 30px;
            padding: 0 12px;
        }
        QPushButton#ghost:hover {
            background: #292f3a;
            border-color: #4d5666;
        }
        QListWidget#foundation_arc_list {
            background: #181b21;
            border: 1px solid #2a2e38;
            border-radius: 6px;
            padding: 4px;
        }
        QListWidget#foundation_arc_list::item {
            padding: 9px 10px;
            margin: 1px 0;
            border-radius: 4px;
        }
        QListWidget#foundation_arc_list::item:selected {
            background: #2a70d6;
            color: #ffffff;
        }
        QListWidget#foundation_arc_list::item:hover:!selected {
            background: #252a34;
        }
        QScrollBar:vertical {
            background: transparent;
            width: 8px;
            margin: 2px 0;
        }
        QScrollBar::handle:vertical {
            background: #3a414e;
            border-radius: 4px;
            min-height: 24px;
        }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0;
        }
        """)
        self._plan = deepcopy(master_plan) if isinstance(master_plan, dict) else {}
        boundary = _clean_chapter_plan_story_boundary(
            self._plan.get("global_hard_boundaries", "")
        )
        if boundary:
            self._plan["global_hard_boundaries"] = boundary
        else:
            self._plan.pop("global_hard_boundaries", None)
        self._state = deepcopy(state) if isinstance(state, dict) else {}
        contract = _normalize_creative_intent_contract(
            self._plan.get("creative_intent_contract", {})
            or self._state.get("creative_intent_contract", {})
        )
        if contract:
            self._plan["creative_intent_contract"] = contract
        self._validator = validator
        self._quick_value_labels = {}
        self._arc_detail_labels = {}
        self._arcs = [
            deepcopy(item) for item in self._plan.get("arcs", []) if isinstance(item, dict)
        ]
        self._current_arc_index = -1
        self._confirmed_plan = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)
        root.addWidget(self._build_header())

        content_scroll = QScrollArea()
        content_scroll.setObjectName("foundation_review_scroll")
        content_scroll.setWidgetResizable(True)
        content_scroll.setFrameShape(QFrame.NoFrame)
        content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("foundation_review_content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 4, 0)
        content_layout.setSpacing(12)
        content_layout.addWidget(self._build_quick_overview())
        content_layout.addWidget(self._build_arc_overview())
        content_layout.addStretch()
        content_scroll.setWidget(content)
        root.addWidget(content_scroll, 1)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        regenerate_btn = QPushButton("重新生成")
        regenerate_btn.setObjectName("ghost")
        regenerate_btn.setToolTip("放弃当前结果，重新生成章节规划基础和阶段安排")
        regenerate_btn.clicked.connect(lambda: self.done(self.RegenerateResult))
        buttons.addWidget(regenerate_btn)
        buttons.addStretch()
        cancel_btn = QPushButton("暂不生成")
        cancel_btn.setObjectName("ghost")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        confirm_btn = QPushButton("确认并生成章节")
        confirm_btn.setObjectName("primary")
        confirm_btn.clicked.connect(self.accept)
        buttons.addWidget(confirm_btn)
        root.addLayout(buttons)

    def _build_header(self):
        header = QFrame()
        header.setObjectName("foundation_header")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title = QLabel("章节规划核对")
        title.setObjectName("foundation_title")
        title_row.addWidget(title)
        title_row.addStretch()
        subtitle = QLabel("确认规划基础无误后，才开始生成详细章节")
        subtitle.setObjectName("foundation_subtitle")
        title_row.addWidget(subtitle)
        layout.addLayout(title_row)

        existing = int(self._state.get("existing_chapter_count", 0) or 0)
        total = int(self._state.get("total_chapter_count", 0) or 0)
        target_words = int(self._state.get("target_words", 0) or 0)
        average_words = int(self._state.get("average_chapter_words", 0) or 0)
        range_start = existing + 1
        metrics = QGridLayout()
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setHorizontalSpacing(18)
        metrics.setVerticalSpacing(2)
        values = (
            ("目标篇幅", f"{target_words}字"),
            ("单章目标", f"{average_words}字"),
            ("全书章节", f"{total}章"),
            ("本次规划", f"第{range_start}-{total}章"),
        )
        for column, (label_text, value_text) in enumerate(values):
            item = QWidget()
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(2)
            label = QLabel(label_text)
            label.setObjectName("foundation_metric_label")
            value = QLabel(value_text)
            value.setObjectName("foundation_metric_value")
            item_layout.addWidget(label)
            item_layout.addWidget(value)
            metrics.addWidget(item, 0, column)
            metrics.setColumnStretch(column, 1)
        layout.addLayout(metrics)
        return header

    @staticmethod
    def _multiline_editor(value="", minimum_height=90):
        editor = PlainTextEdit()
        editor.setPlainText(str(value or ""))
        editor.setMinimumHeight(minimum_height)
        return editor

    @staticmethod
    def _review_text(value, limit=168):
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= limit:
            return text or "未填写"
        return text[:limit].rstrip("，。；;、 ") + "..."

    def _review_value_label(self, value="", limit=112, stage_value=False):
        label = QLabel(self._review_text(value, limit))
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setObjectName("foundation_stage_value" if stage_value else "foundation_item_value")
        return label

    def _summary_item(self, title, value, limit=112):
        item = QWidget()
        layout = QVBoxLayout(item)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("foundation_item_title")
        value_label = self._review_value_label(value, limit)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return item, value_label

    def _build_quick_overview(self):
        page = QFrame()
        page.setObjectName("foundation_summary")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        title = QLabel("章节规划基础")
        title.setObjectName("foundation_section_title")
        heading.addWidget(title)
        hint = QLabel("只确认有没有明显跑偏，不必逐句审核")
        hint.setObjectName("foundation_section_hint")
        heading.addWidget(hint)
        heading.addStretch()
        direction_edit_btn = QPushButton("编辑章节规划基础")
        direction_edit_btn.setObjectName("ghost")
        direction_edit_btn.setToolTip("主线、结局或写作边界有明显偏差时再修改")
        direction_edit_btn.clicked.connect(self._edit_chapter_plan_basics)
        heading.addWidget(direction_edit_btn)
        layout.addLayout(heading)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(11)
        for index, (key, label) in enumerate(_CHAPTER_PLAN_FOUNDATION_FIELDS):
            item, value_label = self._summary_item(label, self._plan.get(key, ""), 106)
            self._quick_value_labels[key] = value_label
            grid.addWidget(item, index // 2, index % 2)
            grid.setColumnStretch(index % 2, 1)
        layout.addLayout(grid)

        intent_box = QFrame()
        intent_box.setObjectName("foundation_strategy_strip")
        intent_layout = QHBoxLayout(intent_box)
        intent_layout.setContentsMargins(10, 8, 10, 8)
        intent_layout.setSpacing(10)
        intent_title = QLabel("确认主线")
        intent_title.setObjectName("foundation_item_title")
        intent_layout.addWidget(intent_title, 0, Qt.AlignTop)
        self._intent_summary_label = QLabel()
        self._intent_summary_label.setWordWrap(True)
        self._intent_summary_label.setObjectName("foundation_item_value")
        intent_layout.addWidget(self._intent_summary_label, 1)
        intent_edit_btn = QPushButton("编辑")
        intent_edit_btn.setObjectName("ghost")
        intent_edit_btn.setToolTip("主线、辅助线用途或结局边界理解错误时修改")
        intent_edit_btn.clicked.connect(self._edit_creative_intent)
        intent_layout.addWidget(intent_edit_btn, 0, Qt.AlignTop)
        layout.addWidget(intent_box)

        profile_box = QFrame()
        profile_box.setObjectName("foundation_strategy_strip")
        profile_layout = QHBoxLayout(profile_box)
        profile_layout.setContentsMargins(10, 8, 10, 8)
        profile_layout.setSpacing(10)
        profile_title = QLabel("题材判断")
        profile_title.setObjectName("foundation_item_title")
        profile_layout.addWidget(profile_title, 0, Qt.AlignTop)
        self._profile_summary_label = QLabel()
        self._profile_summary_label.setWordWrap(True)
        self._profile_summary_label.setObjectName("foundation_item_value")
        profile_layout.addWidget(self._profile_summary_label, 1)
        profile_edit_btn = QPushButton("编辑")
        profile_edit_btn.setObjectName("ghost")
        profile_edit_btn.setToolTip("题材方向、读者期待或写作禁区明显不对时再修改")
        profile_edit_btn.clicked.connect(self._edit_profile_details)
        profile_layout.addWidget(profile_edit_btn, 0, Qt.AlignTop)
        layout.addWidget(profile_box)
        self._refresh_quick_overview()
        self._refresh_intent_summary()
        self._refresh_profile_summary()
        return page

    def _refresh_intent_summary(self):
        label = getattr(self, "_intent_summary_label", None)
        if label is None:
            return
        contract = _normalize_creative_intent_contract(
            self._plan.get("creative_intent_contract", {})
        )
        primary = str(
            contract.get("core_motive", "")
            or contract.get("primary_line", "")
            or ""
        ).strip()
        supporting = "、".join(contract.get("supporting_lines", []))
        text = f"核心动机主线：{primary}" if primary else "尚未形成独立创作意图；请先确认章节规划基础和题材判断。"
        if supporting:
            text += f"  ·  辅助线：{supporting}"
        label.setText(text)

    def _edit_creative_intent(self):
        contract = _normalize_creative_intent_contract(
            self._plan.get("creative_intent_contract", {})
        )
        if not contract:
            profile = _normalize_narrative_strategy_profile(
                self._plan.get("narrative_strategy_profile", {})
            )
            contract = _normalize_creative_intent_contract({
                "primary_line": profile.get("core_motive", "") or profile.get("primary_story_engine", ""),
                "core_motive": profile.get("core_motive", "") or profile.get("primary_story_engine", ""),
                "supporting_lines": [profile.get("secondary_story_engine", "")],
                "reading_experience": profile.get("core_reader_promise", ""),
                "ending_boundaries": profile.get("story_direction", ""),
                "source": "chapter_plan_inference",
            })
        dialog = VolumeCreativeIntentDialog(contract, self, volume_mode=False)
        if dialog.exec() != QDialog.Accepted:
            return
        self._plan["creative_intent_contract"] = dialog.confirmed_contract()
        self._plan["creative_intent_contract"]["source"] = "user_confirmed"
        self._refresh_intent_summary()

    def _refresh_quick_overview(self):
        for key, label in self._quick_value_labels.items():
            label.setText(self._review_text(self._plan.get(key, "")))

    def _edit_chapter_plan_basics(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("调整章节规划基础")
        dialog.setMinimumSize(700, 460)
        root = QVBoxLayout(dialog)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        hint = QLabel("只在章节规划基础有明显偏差时修改。这里的内容会作为后续章节规划的参考。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        editors = {}
        for key, label in _CHAPTER_PLAN_FOUNDATION_FIELDS:
            editor = self._multiline_editor(self._plan.get(key, ""), 58)
            editor.setMaximumHeight(100)
            editors[key] = editor
            form.addRow(label, editor)
        root.addLayout(form, 1)
        buttons = QDialogButtonBox()
        save_btn = buttons.addButton("保存调整", QDialogButtonBox.AcceptRole)
        save_btn.setObjectName("primary")
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.RejectRole)
        cancel_btn.setObjectName("ghost")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        for key, editor in editors.items():
            value = editor.toPlainText().strip()
            if key == "global_hard_boundaries":
                value = _clean_chapter_plan_story_boundary(value)
                if value:
                    self._plan[key] = value
                else:
                    self._plan.pop(key, None)
            else:
                self._plan[key] = value
        self._refresh_quick_overview()

    def _profile_summary_text(self):
        profile = _normalize_narrative_strategy_profile(
            self._plan.get("narrative_strategy_profile", {})
        )
        values = (
            ("题材", profile.get("genre_world", "")),
            ("读者期待", profile.get("core_reader_promise", "")),
            ("故事发动机", profile.get("primary_story_engine", "")),
            ("故事方向", profile.get("story_direction", "")),
        )
        lines = [
            f"{label}：{self._review_text(value, 48)}"
            for label, value in values if str(value or "").strip()
        ]
        return "  ·  ".join(lines) or "AI 未给出额外题材判断；以章节规划基础为准。"

    def _refresh_profile_summary(self):
        label = getattr(self, "_profile_summary_label", None)
        if label is not None:
            label.setText(self._profile_summary_text())

    def _edit_profile_details(self):
        profile = _normalize_narrative_strategy_profile(
            self._plan.get("narrative_strategy_profile", {})
        )
        dialog = NarrativeStrategyProfileDialog(profile, self, planning_gate=False)
        dialog.setWindowTitle("调整题材判断")
        if dialog.exec() != QDialog.Accepted:
            return
        self._plan["narrative_strategy_profile"] = dialog.profile()
        self._refresh_profile_summary()

    def _build_arc_overview(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        label = QLabel("阶段安排")
        label.setObjectName("foundation_section_title")
        heading.addWidget(label)
        hint = QLabel(f"共{len(self._arcs)}个阶段，确认顺序、主线和限制没有错位")
        hint.setObjectName("foundation_section_hint")
        heading.addWidget(hint)
        heading.addStretch()
        arc_edit_btn = QPushButton("编辑当前阶段")
        arc_edit_btn.setObjectName("ghost")
        arc_edit_btn.setToolTip("当前阶段范围、主线或禁区有明显偏差时再修改")
        arc_edit_btn.clicked.connect(self._edit_current_arc_details)
        heading.addWidget(arc_edit_btn)
        root.addLayout(heading)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.arc_list = QListWidget()
        self.arc_list.setObjectName("foundation_arc_list")
        self.arc_list.setMinimumWidth(260)
        self.arc_list.setMaximumWidth(340)
        self.arc_list.setMinimumHeight(180)
        for index, arc in enumerate(self._arcs, 1):
            self.arc_list.addItem(self._arc_label(arc, index))
        layout.addWidget(self.arc_list, 0)

        detail_page = QFrame()
        detail_page.setObjectName("foundation_stage_detail")
        form = QFormLayout(detail_page)
        form.setContentsMargins(14, 11, 14, 11)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(7)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for key, label in (
            ("source_stage", "原框架阶段"),
            ("dominant_line", "阶段主线"),
            ("end_state", "阶段后部局面"),
        ):
            value_label = self._review_value_label("", 118, stage_value=True)
            self._arc_detail_labels[key] = value_label
            form.addRow(label, value_label)
        layout.addWidget(detail_page, 1)
        root.addLayout(layout, 1)
        self.arc_list.currentRowChanged.connect(self._on_arc_selected)
        if self._arcs:
            self.arc_list.setCurrentRow(0)
        return page

    @staticmethod
    def _arc_label(arc, fallback_index):
        arc = arc if isinstance(arc, dict) else {}
        name = str(arc.get("name", "") or f"阶段{fallback_index}").strip()
        start = arc.get("start_chapter", "")
        end = arc.get("end_chapter", "")
        return f"{fallback_index:02d}  第{start}-{end}章 · {name}"

    def _refresh_current_arc_details(self):
        index = self._current_arc_index
        if index < 0 or index >= len(self._arcs):
            return
        arc = self._arcs[index]
        for key, label in self._arc_detail_labels.items():
            label.setText(self._review_text(arc.get(key, ""), 118))

    def _on_arc_selected(self, row):
        self._current_arc_index = int(row)
        if row < 0 or row >= len(self._arcs):
            return
        self._refresh_current_arc_details()

    def _edit_current_arc_details(self):
        index = self._current_arc_index
        if index < 0 or index >= len(self._arcs):
            return
        arc = self._arcs[index]
        dialog = QDialog(self)
        dialog.setWindowTitle(f"调整阶段：{self._arc_label(arc, index + 1)}")
        dialog.setMinimumSize(720, 560)
        root = QVBoxLayout(dialog)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        hint = QLabel("仅在当前阶段存在明显错误时调整。未修改的内部规划资料会继续保留。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        editors = {}
        for key, label in _CHAPTER_PLAN_QUICK_ARC_FIELDS:
            if key in {"name", "start_chapter", "end_chapter"}:
                editor = QLineEdit(str(arc.get(key, "") or ""))
            else:
                editor = self._multiline_editor(arc.get(key, ""), 50)
                editor.setMaximumHeight(90)
            editors[key] = editor
            form.addRow(label, editor)
        root.addLayout(form, 1)
        buttons = QDialogButtonBox()
        save_btn = buttons.addButton("保存调整", QDialogButtonBox.AcceptRole)
        save_btn.setObjectName("primary")
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.RejectRole)
        cancel_btn.setObjectName("ghost")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        for key, editor in editors.items():
            value = editor.text().strip() if isinstance(editor, QLineEdit) else editor.toPlainText().strip()
            if key in {"start_chapter", "end_chapter"}:
                try:
                    arc[key] = int(value)
                except Exception:
                    arc[key] = value
            else:
                arc[key] = value
        item = self.arc_list.item(index)
        if item is not None:
            item.setText(self._arc_label(arc, index + 1))
        self._refresh_current_arc_details()

    def foundation(self):
        plan = deepcopy(self._plan)
        profile = _normalize_narrative_strategy_profile(
            self._plan.get("narrative_strategy_profile", {})
        )
        profile["version"] = str(profile.get("version", "1") or "1")
        plan["narrative_strategy_profile"] = _normalize_narrative_strategy_profile(profile)
        plan["creative_intent_contract"] = _normalize_creative_intent_contract(
            self._plan.get("creative_intent_contract", {})
        )
        plan["arcs"] = deepcopy(self._arcs)
        return plan

    def accept(self):
        plan = self.foundation()
        error = str(self._validator(plan) or "").strip() if callable(self._validator) else ""
        if error:
            QMessageBox.warning(self, "规划基础需要调整", error)
            return
        self._confirmed_plan = plan
        super().accept()

    def confirmed_plan(self):
        return deepcopy(self._confirmed_plan or self.foundation())


class _ChapterTaskSignalRouter(QObject):
    """Keep queued worker signals attached to the same receiver across switches."""

    def __init__(self, worker, owner, result_method, cleanup_method):
        super().__init__(worker if isinstance(worker, QObject) else None)
        self.worker = worker
        self.result_method = result_method
        self.cleanup_method = cleanup_method
        worker._chapter_task_owner_tab = owner

    def dispatch(self, method, *args):
        owner = self.worker._chapter_task_owner_tab
        previous = getattr(owner, "_chapter_task_callback_worker", None)
        owner._chapter_task_callback_worker = self.worker
        try:
            getattr(owner, method)(*args)
        finally:
            owner._chapter_task_callback_worker = previous

    def on_result(self, *args):
        self.dispatch(self.result_method, *args)

    def on_failure(self, *args):
        method = {
            "_on_chapter_context_ready": "_on_chapter_context_failed",
            "on_chapter_ai_ready": "on_chapter_ai_failed",
        }.get(self.result_method, "on_chapter_plan_failed")
        self.dispatch(method, *args)

    def on_finished(self):
        self.dispatch(self.cleanup_method)

    def on_chunk(self, piece):
        self.dispatch("on_chapter_ai_chunk", piece)

    def on_progress(self, text):
        self.dispatch("set_status_tip", text)

    def on_output_chars(self, count):
        self.dispatch("_on_novel_output_chars", count)


class NovelWritingTab(SimpleModelBarMixin, QWidget):
    request_settings = Signal()
    MODEL_CONFIG_SECTION = "novel"
    FALLBACK_MODELS = ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"]
    _MEMORY_POSTPROCESS_ACTIONS = frozenset({
        "memory_finalize",
        "memory_reconcile",
        "memory_repair",
        "logic_repair",
        "memory_sync",
    })
    _MEMORY_FAILURE_EVENTS = frozenset({
        "memory_validation_failed",
        "memory_sync_failed",
        "memory_reconciliation_fallback",
        "chapter_logic_repair_started",
        "chapter_logic_repair_applied",
        "chapter_prose_repair_patch_skipped",
        "chapter_prose_repair_patch_applied",
        "literal_count_claim_normalized",
        "auto_expand_postwrite_validation_failed",
        "auto_expand_chapter_save_failed",
        "auto_expand_resume_state_save_failed",
        "ai_generation_checkpoint_save_failed",
    })

    def __init__(self, config=None, parent=None, background_runner=False):
        super().__init__(parent)
        self.config = config or {}
        self.model_worker = None
        self.analysis_worker = None
        self.writing_worker = None
        self.writing_retired_workers = []
        self.context_build_worker = None
        self._context_build_token = 0
        self._context_build_pending = {}
        self._is_detached_auto_runner = bool(background_runner)
        self._detached_auto_readonly_states = []
        self._background_task_kind = ""
        # Chapter work is owned by a project path, not by whichever project
        # happens to be visible in the single writing tab.  These hidden
        # runners keep in-flight chapter and automatic expansion requests
        # alive while the user opens another project.
        self._background_chapter_ai_runners = {}
        self._fanqie_upload_workers = {}
        self._fanqie_upload_dialog = None
        self._fanqie_upload_locked_path = ""
        self._chapter_task_timer_owner = None
        self.chapter_plan_worker = None
        self._chapter_plan_request_kind = ""
        self._chapter_plan_continue_pending = False
        self._chapter_plan_auto_active = False
        self._chapter_plan_foundation_regenerate_pending = False
        self._chapter_plan_sequence_token = 0
        self._chapter_plan_provider = {}
        self._chapter_plan_model = ""
        self._chapter_plan_diagnostic_request_id = ""
        self._chapter_plan_diagnostic_started_at = 0.0
        self.framework_import_worker = None
        self._framework_import_context = {}
        self.volume_handoff_worker = None
        self.volume_intent_worker = None
        self.volume_framework_worker = None
        self.volume_framework_audit_worker = None
        self._volume_two_pending = {}
        self._volume_two_source_path = ""
        self._volume_two_source_hash = ""
        self._volume_two_model = ""
        self._volume_two_template_hash = ""
        self.chapter_title_worker = None
        self.foreshadow_review_worker = None
        self.failed_foreshadow_review_chunks = []
        self.foreshadow_review_postprocess_pending = False
        self.foreshadow_review_observations = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
        self.foreshadow_review_comparison_state = {}
        self.chapter_ai_stream_text = ""
        self.chapter_ai_action_buttons = []
        self._chapter_ai_buttons_by_action = {}
        self.candidate_action_buttons = []
        self.foreshadow_action_buttons = []
        self._pending_model_reload = False
        self._loading = False
        self._dirty = False
        self._project_file_dirty = False
        self._draft_saved_once = False
        self._dirty_generation = 0
        self._last_failed_autosave_generation = -1
        self._autosave_in_progress = False
        self._chapter_order_search_cache = None
        self._field_refresh_pending = False
        self._opening_project = False
        self._loaded_project_file_signature = ()
        self.current_project_path = ""
        self.current_project = _default_project()
        self.import_candidates = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
        self.last_import_text = ""
        self.pending_analysis_chapter_ids = []
        self.failed_analysis_chunks = []
        self.candidate_postprocess_state = {}
        self._analysis_stop_requested_by_user = False
        self._chapter_ai_stop_requested_by_user = False
        self._chapter_ai_last_memory_repair_signature = ""
        self._chapter_ai_preview_action = ""
        self._chapter_ai_preview_chapter_id = ""
        self._chapter_ai_preview_is_partial = False
        self._chapter_ai_resume_prefix = ""
        self._chapter_ai_running_action = ""
        self._chapter_ai_running_context = ""
        self._chapter_ai_running_status_text = ""
        self._chapter_ai_running_chapter_id = ""
        self._chapter_ai_diagnostic_request_id = ""
        self._chapter_ai_diagnostic_started_at = 0.0
        self._chapter_ai_task_generation = 0
        self._chapter_ai_active_task = {}
        self._chapter_ai_transient_retry_counts = {}
        self._chapter_ai_transient_retry_pending = False
        self._chapter_ai_transient_retry_token = 0
        self._chapter_ai_last_context = ""
        self._chapter_ai_style_retry_attempted = False
        self._chapter_ai_style_fallback_text = ""
        self._chapter_ai_style_workflow_active = False
        self._chapter_ai_style_reference = ""
        self._chapter_ai_style_original_context = ""
        self._chapter_ai_style_profile = ""
        self._chapter_ai_style_profile_cache_hash = ""
        self._chapter_ai_style_profile_cache_text = ""
        self._chapter_ai_style_profile_cache_version = 0
        self._chapter_ai_style_candidate = ""
        self._chapter_ai_style_finalize_count = 0
        self._chapter_ai_style_final_bundle = {}
        self._chapter_ai_style_rewrite_count = 0
        self._chapter_ai_style_local_reasons = []
        self._chapter_ai_style_output_target = 0
        self._chapter_ai_style_plot_ledger = ""
        self._chapter_ai_style_pending_reasons = []
        self._chapter_ai_style_cards = []
        self._chapter_ai_style_semantic_archive = {}
        self._chapter_ai_style_plan = ""
        self._chapter_ai_sequence_active = False
        self._chapter_ai_sequence_chapter_id = ""
        self._chapter_ai_sequence_started_outline = ""
        self._auto_expand_all_active = False
        self._auto_expand_all_waiting_next = False
        self._auto_expand_all_total = 0
        self._auto_expand_all_completed = 0
        self._auto_expand_all_current_chapter_id = ""
        self._auto_expand_restart_rewrite_notice = False
        self._chapter_ai_provider = {}
        self._chapter_ai_model = ""
        self._status_message = ""
        self._status_stage_key = ""
        self._status_stage_label = ""
        self._status_stage_started_at = 0.0
        self._status_stage_started_wall = 0.0
        self._status_stage_scope_label = ""
        self._status_stage_active = False
        self._status_history = []
        self._status_workflow_active = False
        self._status_workflow_kind = ""
        self._status_workflow_started_at = 0.0
        self._status_workflow_started_wall = 0.0
        self._status_last_run_elapsed = 0.0
        self._status_received_chars = 0
        self._status_project_path = ""
        # The foreground tab mirrors status from detached chapter runners so
        # single-chapter and automatic expansion share one display path.
        self._detached_auto_status_scope_id = ""
        self._detached_auto_status_scope_label = ""
        self._detached_auto_status_auto_progress = (0, 0)
        self._detached_auto_status_mirrored = False
        self._novel_diagnostic_counter = 0
        self._novel_diagnostic_session_id = hashlib.sha256(
            f"{time.time_ns()}:{id(self)}".encode("utf-8")
        ).hexdigest()[:16]
        self._novel_diagnostics_enabled = True
        self._pending_chapter_plan = {}
        self._pending_split_export = {}
        self._creation_wizard_workspace = None
        self._creation_wizard_dialogs = {}
        self.current_character_index = -1
        self.current_lore_index = -1
        self.current_foreshadow_index = -1
        self.current_chapter_index = -1
        self._refreshing_helpers = False
        self._pending_manuscript_refresh = False
        self._manuscript_stale = False
        self._writing_check_stale = False
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
        if not self._is_detached_auto_runner:
            sync_style_profile_library_from_projects()
        self._build_ui()
        self._apply_novel_ui_style()
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._refresh_status_display)
        self._status_timer.timeout.connect(self._poll_background_chapter_ai_runners)
        self._status_timer.start()
        if not self._is_detached_auto_runner:
            self._init_project_sync_watcher()
            self.refresh_import_candidate_lists()
            self._load_initial_project()
        self._log_novel_diagnostic("novel_session_started")
        self._autosave_timer = None
        if not self._is_detached_auto_runner:
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
        header_layout = QVBoxLayout(self.project_info_body)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        self.title_edit = QLineEdit()
        self.genre_edit = QLineEdit()
        self.style_edit = QLineEdit()
        self.pov_combo = WideComboBox()
        self.pov_combo.addItems(["第一人称", "第三人称", "多视角"])
        self.target_words_edit = QLineEdit()
        self.status_combo = WideComboBox()
        self.status_combo.addItems(["草稿", "连载中", "已完结", "修订中"])
        self.style_profile_combo = WideComboBox()
        self.style_profile_combo.setToolTip("选择扩写正文时调用的永久文风档案")
        self.premise_edit = PlainTextEdit()
        self.premise_edit.setFixedHeight(42)
        self.premise_edit.setPlaceholderText("用几句话说清主角是谁、现在遇到什么事，以及故事会怎样展开。")

        for w in (self.title_edit, self.genre_edit, self.style_edit, self.target_words_edit):
            w.textChanged.connect(self._mark_dirty)
        self.pov_combo.currentTextChanged.connect(self._mark_dirty)
        self.status_combo.currentTextChanged.connect(self._mark_dirty)
        self.style_profile_combo.currentIndexChanged.connect(self._on_style_profile_selected)
        self.premise_edit.textChanged.connect(self._mark_dirty)

        def configure_field_grid(column_count):
            layout = QGridLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setHorizontalSpacing(10)
            layout.setVerticalSpacing(0)
            for col in range(column_count):
                layout.setColumnStretch(col, 1 if col % 2 else 0)
            return layout

        def add_field(layout, col, label, widget):
            lab = QLabel(label)
            layout.addWidget(lab, 0, col)
            layout.addWidget(widget, 0, col + 1)

        self.project_info_top_layout = configure_field_grid(6)
        add_field(self.project_info_top_layout, 0, "书名", self.title_edit)
        add_field(self.project_info_top_layout, 2, "类型", self.genre_edit)
        add_field(self.project_info_top_layout, 4, "风格", self.style_edit)
        header_layout.addLayout(self.project_info_top_layout)

        self.project_info_controls_layout = configure_field_grid(8)
        add_field(self.project_info_controls_layout, 0, "叙事人称", self.pov_combo)
        add_field(self.project_info_controls_layout, 2, "项目总字数（万字）", self.target_words_edit)
        add_field(self.project_info_controls_layout, 4, "状态", self.status_combo)
        add_field(self.project_info_controls_layout, 6, "写作风格", self.style_profile_combo)
        header_layout.addLayout(self.project_info_controls_layout)

        premise_layout = QGridLayout()
        premise_layout.setContentsMargins(0, 0, 0, 0)
        premise_layout.setHorizontalSpacing(10)
        premise_layout.addWidget(QLabel("故事简介"), 0, 0)
        premise_layout.addWidget(self.premise_edit, 0, 1)
        self.narrative_strategy_btn = self._ghost_button(
            "叙事策略",
            self.show_narrative_strategy_profile,
            "查看或修改当前项目用于章节规划和正文扩写的叙事策略画像",
        )
        premise_layout.addWidget(self.narrative_strategy_btn, 0, 2)
        premise_layout.setColumnStretch(1, 1)
        header_layout.addLayout(premise_layout)
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
        if self._is_detached_auto_runner:
            provider_id = self.bar.current_provider_id()
            cached_models = [
                str(item).strip()
                for item in self.config.get("model_cache", {}).get(provider_id, [])
                if str(item).strip()
            ]
            selected_model = str(
                self.config.get(self.MODEL_CONFIG_SECTION, {}).get("model", "") or ""
            ).strip()
            if selected_model and selected_model not in cached_models:
                cached_models.insert(0, selected_model)
            self.bar.set_models(cached_models, selected_model)
            self.refresh_ai_settings_summary()
        else:
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
            ("伏笔", "伏笔", self._build_foreshadow_tab()),
            ("书稿", "完整书稿", self._build_manuscript_tab()),
            ("检查", "写作检查", self._build_check_tab()),
            ("搜索", "全局搜索", self._build_search_tab()),
            ("候选", "导入候选", self._build_import_candidates_tab()),
            ("备注", "全局备注", self._build_simple_text_tab("draft_note_edit", "全局备注")),
        ]
        for short_name, full_name, page in pages:
            page_index = self.tabs.addWidget(page)
            self.page_indexes[short_name] = page_index
            item = QListWidgetItem(short_name)
            item.setToolTip(full_name)
            item.setData(Qt.UserRole, page_index)
            self.nav_list.addItem(item)
            item.setHidden(short_name == "候选")
        self.nav_list.setCurrentRow(0)
        content_layout.addWidget(self.tabs, 1)
        right_layout.addWidget(content_area, 1)

        # Background expansion locks the currently visible project workspace,
        # while the project-management area remains available for switching
        # projects and starting work elsewhere.
        self.project_workspace = right
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

        self.create_volume_two_btn = self._ghost_button(
            "创建新卷续写",
            self.create_second_volume,
            "从当前已完成项目生成交接摘要和本卷框架，确认后创建独立项目",
        )

        layout.addLayout(self._project_button_grid((
            ("新建", self.new_project, "新建一个小说项目，当前内容会先自动保存"),
            ("创建新卷续写", self.create_second_volume, "", self.create_volume_two_btn),
        ), columns=2))

        layout.addLayout(self._project_button_grid((
            ("删除", self.delete_selected_project, "删除左侧列表中选中的小说项目"),
            ("导入Word/TXT", self.import_word_or_txt_script, "从 Word 或 TXT 文档导入小说、剧本或框架正文"),
        ), columns=2))

        layout.addLayout(self._project_button_grid((
            ("导入项目", self.import_project, "导入小说项目 JSON 文件"),
            ("导出项目", self.export_project, "导出当前小说项目 JSON 文件"),
        ), columns=2))

        self.framework_import_retry_btn = self._ghost_button(
            "重试框架 AI 分类",
            self.retry_framework_import,
            "使用当前项目已经保存的框架原文重新进行 AI 智能分类，不会新建项目",
        )
        self.framework_import_retry_btn.setVisible(False)
        layout.addWidget(self.framework_import_retry_btn)

        self.project_list = QListWidget()
        self.project_list.itemClicked.connect(self._open_selected_project_item)
        layout.addWidget(self.project_list, 1)

        self.project_hint = QLabel("单击列表可打开已保存小说。")
        self.project_hint.setObjectName("hint")
        self.project_hint.setWordWrap(True)
        # The main status line below is the useful live status. The old
        # project hint duplicated background-task state and consumed the
        # narrow panel height, so keep it available for compatibility but do
        # not place it in the visible layout.
        self.project_hint.setVisible(False)

        self.status_label = QLabel("")
        self.status_label.setObjectName("novel_status_current")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(34)
        self.status_label.setMaximumHeight(56)
        layout.addWidget(self.status_label)

        self.status_meta_label = QLabel("")
        self.status_meta_label.setObjectName("novel_status_meta")
        self.status_meta_label.setWordWrap(True)
        self.status_meta_label.setFixedHeight(36)
        layout.addWidget(self.status_meta_label)

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
        QLabel#novel_status_current {
            color: #e7e9ee;
        }
        QLabel#novel_status_meta {
            color: #9ec5ff;
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
        model = self.bar.current_model() or self._current_model()
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

    def on_models_loaded(self, provider_id, request_id, models):
        if not self._is_current_model_request(provider_id, request_id):
            return
        SimpleModelBarMixin.on_models_loaded(self, provider_id, request_id, models)
        self.refresh_ai_settings_summary()

    def on_models_failed(self, provider_id, request_id, err):
        if not self._is_current_model_request(provider_id, request_id):
            return
        SimpleModelBarMixin.on_models_failed(self, provider_id, request_id, err)
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

    def _matching_local_style_profile_id(self):
        reference = str(self.current_project.get("style_reference", "") or "").strip()
        if not reference:
            return ""
        reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        return reference_hash if get_style_profile(reference_hash) else ""

    def _refresh_style_profile_combo(self):
        if not hasattr(self, "style_profile_combo"):
            return
        selected_id = str(self.current_project.get("style_profile_id", "") or "").strip().lower()
        if not selected_id:
            matching_id = self._matching_local_style_profile_id()
            if matching_id:
                selected_id = matching_id
                self.current_project["style_profile_id"] = matching_id
            else:
                selected_id = "__none__"
                self.current_project["style_profile_id"] = selected_id
        profiles = load_style_profile_library()
        self.style_profile_combo.blockSignals(True)
        try:
            self.style_profile_combo.clear()
            self.style_profile_combo.addItem("不使用文风档案", "__none__")
            for item in profiles:
                profile_id = str(item.get("id", "") or "").strip()
                if not profile_id:
                    continue
                name = str(item.get("name", "") or "").strip() or f"永久文风 {profile_id[:8]}"
                sample_chars = len(str(item.get("style_reference", "") or "").replace("\n", "").strip())
                label = f"{name}（样本 {sample_chars} 字）" if sample_chars else name
                self.style_profile_combo.addItem(label, profile_id)
            index = self.style_profile_combo.findData(selected_id)
            if index < 0:
                self.current_project["style_profile_id"] = "__none__"
                index = self.style_profile_combo.findData("__none__")
            self.style_profile_combo.setCurrentIndex(max(0, index))
        finally:
            self.style_profile_combo.blockSignals(False)

    def _on_style_profile_selected(self, _index=-1):
        if self._loading or not hasattr(self, "style_profile_combo"):
            return
        profile_id = str(self.style_profile_combo.currentData() or "").strip().lower()
        if profile_id == self.current_project.get("style_profile_id", ""):
            return
        self.current_project["style_profile_id"] = profile_id
        self._note_project_dirty()
        self._schedule_autosave_only()
        if profile_id == "__none__":
            self.set_status_tip("当前项目扩写正文时不使用文风档案。")
        elif profile_id:
            self.set_status_tip(f"已选择文风档案：{self.style_profile_combo.currentText()}")

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

    def _expand_text_edit(self, widget, min_height=90, bottom_scroll_padding=0):
        widget.setMinimumHeight(min_height)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if bottom_scroll_padding:
            self._set_text_edit_bottom_scroll_padding(widget, bottom_scroll_padding)
        return widget

    def _set_text_edit_bottom_scroll_padding(self, widget, bottom=28):
        try:
            margins = widget.viewportMargins()
            widget.setViewportMargins(
                margins.left(),
                margins.top(),
                margins.right(),
                max(margins.bottom(), int(bottom or 0)),
            )
        except Exception as e:
            log_debug("章节编辑区底部留白设置失败", e)
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

    def _button_grid(self, actions, columns=3, button_store=None):
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for index, action in enumerate(actions):
            text, callback = action[:2]
            tooltip = action[2] if len(action) > 2 else ""
            btn = self._ghost_button(text, callback, tooltip)
            grid.addWidget(btn, index // columns, index % columns)
            if button_store is not None:
                button_store.append(btn)
        return grid

    def _project_button_grid(self, actions, columns=2):
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, action in enumerate(actions):
            text, callback = action[:2]
            tooltip = action[2] if len(action) > 2 else ""
            btn = action[3] if len(action) > 3 and action[3] is not None else self._ghost_button(text, callback, tooltip)
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
        title_edit_text = self.title_edit.text() if hasattr(self, "title_edit") else ""
        return str(meta.get("title") or title_edit_text or "未命名小说").strip() or "未命名小说"

    def _novel_perf_enabled(self):
        return NOVEL_PERF_LOG_ENABLED

    def _novel_perf_summary(self, project=None):
        if not self._novel_perf_enabled():
            return {}
        project = project if isinstance(project, dict) else getattr(self, "current_project", {})
        project = project if isinstance(project, dict) else {}
        chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
        characters = project.get("characters", []) if isinstance(project.get("characters"), list) else []
        lore = project.get("lore", []) if isinstance(project.get("lore"), list) else []
        foreshadows = project.get("foreshadow_items", []) if isinstance(project.get("foreshadow_items"), list) else []
        candidates = project.get("import_candidates", {}) if isinstance(project.get("import_candidates"), dict) else {}
        body_chars = sum(len(str(chap.get("text", "") or "")) for chap in chapters if isinstance(chap, dict))
        candidate_count = 0
        for key in ("characters", "lore", "foreshadows"):
            values = candidates.get(key, []) if isinstance(candidates, dict) else []
            if isinstance(values, list):
                candidate_count += len(values)
        return {
            "chapters": len(chapters),
            "body_chars": body_chars,
            "characters": len(characters),
            "lore": len(lore),
            "foreshadows": len(foreshadows),
            "candidates": candidate_count,
        }

    def _log_novel_perf(self, name, start_time, threshold_ms=80, **details):
        try:
            elapsed = (time.perf_counter() - start_time) * 1000
            if not self._novel_perf_enabled():
                return elapsed
            if elapsed < float(threshold_ms or 0):
                return elapsed
            parts = [f"{elapsed:.1f}ms"]
            for key, value in details.items():
                if value is None or value == "":
                    continue
                parts.append(f"{key}={value}")
            message = f"小说性能｜{name}｜" + "｜".join(parts)
            log_debug(message)
            try:
                os.makedirs(HISTORY_DIR, exist_ok=True)
                perf_log_path = os.path.join(HISTORY_DIR, "novel_perf.log")
                if os.path.exists(perf_log_path) and os.path.getsize(perf_log_path) > 2 * 1024 * 1024:
                    os.replace(perf_log_path, f"{perf_log_path}.1")
                with open(perf_log_path, "a", encoding="utf-8") as f:
                    f.write(f"{now_str()} {message}\n")
            except Exception:
                pass
            return elapsed
        except Exception:
            return 0

    def _next_novel_diagnostic_request_id(self, prefix="request"):
        session_id = str(getattr(self, "_novel_diagnostic_session_id", "") or "").strip()
        if not session_id:
            session_id = hashlib.sha256(
                f"{time.time_ns()}:{id(self)}".encode("utf-8")
            ).hexdigest()[:16]
            self._novel_diagnostic_session_id = session_id
        counter = int(getattr(self, "_novel_diagnostic_counter", 0) or 0) + 1
        self._novel_diagnostic_counter = counter
        return f"{str(prefix or 'request')}-{session_id}-{counter:05d}"

    @staticmethod
    def _novel_context_section_metrics(context):
        text = str(context or "")
        matches = list(re.finditer(r"(?m)^【([^】\r\n]{1,120})】[ \t]*\r?$", text))
        sections = []
        for index, match in enumerate(matches[:120]):
            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            content = text[match.end():next_start].strip()
            sections.append({
                "title": str(match.group(1) or "").strip(),
                "content_chars": len(content),
                "block_chars": max(0, next_start - match.start()),
            })
        return {
            "section_count": len(matches),
            "prefix_chars": matches[0].start() if matches else len(text),
            "sections": sections,
        }

    @staticmethod
    def _novel_exception_details(error):
        formatted = traceback.format_exc(limit=40)
        if formatted.strip() == "NoneType: None":
            formatted = ""
        return {
            "error": clean_error_text(error),
            "error_type": type(error).__name__,
            "traceback": formatted,
        }

    @staticmethod
    def _novel_diagnostic_error_category(error):
        text = clean_error_text(error).lower()
        if any(marker in text for marker in ("选择厂商", "设置 api key", "设置api key", "选择模型")):
            return "configuration"
        if any(marker in text for marker in ("接口错误 401", "接口错误 403", "unauthorized", "forbidden")):
            return "authentication"
        if any(marker in text for marker in ("接口错误 429", "rate limit", "too many requests", "concurrency limit")):
            return "rate_limit"
        if any(marker in text for marker in ("接口错误 500", "接口错误 502", "接口错误 503", "接口错误 504", "接口错误 524", "upstream")):
            return "upstream"
        if any(marker in text for marker in ("timeout", "timed out", "超时")):
            return "timeout"
        if any(marker in text for marker in ("ssl", "connection", "remote end closed", "max retries exceeded")):
            return "network"
        if any(marker in text for marker in (
            "length", "max_tokens", "token_limit", "未完整结束", "没有写完", "输出异常膨胀",
        )):
            return "incomplete_output"
        if "没有返回有效内容" in text:
            return "empty_output"
        if any(marker in text for marker in ("json", "无法解析", "格式", "校验")):
            return "invalid_output"
        if any(marker in text for marker in ("状态事务", "状态同步", "长期状态", "关键事实", "摘要")):
            return "memory_state"
        if any(marker in text for marker in ("保存失败", "持久化失败", "写入失败")):
            return "storage"
        if any(marker in text for marker in ("中止", "cancel", "stop requested")):
            return "cancelled"
        return "unknown"

    @staticmethod
    def _auto_expand_stop_reason_code(message):
        text = str(message or "")
        checks = (
            ("自动扩写完成", "completed"),
            ("已中止", "user_cancelled"),
            ("没有章节提纲", "missing_outline"),
            ("无法定位", "chapter_lookup_failed"),
            ("上下文组装失败", "context_build_failed"),
            ("状态同步失败", "memory_sync_failed"),
            ("资料回填不完整", "postwrite_validation_failed"),
            ("保存失败", "storage_failed"),
            ("生成失败", "api_generation_failed"),
            ("完成章节与当前任务不一致", "chapter_mismatch"),
            ("未能启动", "pipeline_start_failed"),
        )
        for marker, code in checks:
            if marker in text:
                return code
        return "unknown"

    def _chapter_ai_signal_diagnostics(self):
        worker = None
        try:
            candidate = self._chapter_task_signal_worker()
            if candidate is not None and hasattr(candidate, "diagnostics"):
                worker = candidate
        except Exception:
            worker = None
        if worker is None:
            worker = getattr(self, "writing_worker", None)
        diagnostics = getattr(worker, "diagnostics", {}) if worker is not None else {}
        worker_request_id = str(getattr(worker, "diagnostic_request_id", "") or "") if worker is not None else ""
        request_id = worker_request_id or str(getattr(self, "_chapter_ai_diagnostic_request_id", "") or "")
        try:
            worker_started_at = (
                float(getattr(worker, "diagnostic_started_at", 0.0) or 0.0)
                if worker is not None else 0.0
            )
            started_at = worker_started_at or float(
                getattr(self, "_chapter_ai_diagnostic_started_at", 0.0) or 0.0
            )
        except Exception:
            started_at = 0.0
        return request_id, started_at, deepcopy(diagnostics) if isinstance(diagnostics, dict) else {}

    def _chapter_plan_signal_diagnostics(self):
        worker = None
        try:
            candidate = self._chapter_task_signal_worker()
            if candidate is not None and hasattr(candidate, "diagnostics"):
                worker = candidate
        except Exception:
            worker = None
        if worker is None:
            worker = getattr(self, "chapter_plan_worker", None)
        diagnostics = getattr(worker, "diagnostics", {}) if worker is not None else {}
        request_id = str(
            (getattr(worker, "diagnostic_request_id", "") if worker is not None else "")
            or getattr(self, "_chapter_plan_diagnostic_request_id", "")
            or ""
        )
        try:
            started_at = float(
                (getattr(worker, "diagnostic_started_at", 0.0) if worker is not None else 0.0)
                or getattr(self, "_chapter_plan_diagnostic_started_at", 0.0)
                or 0.0
            )
        except Exception:
            started_at = 0.0
        return request_id, started_at, deepcopy(diagnostics) if isinstance(diagnostics, dict) else {}

    def _chapter_ai_signal_worker(self):
        worker = None
        try:
            candidate = self.sender()
            if candidate is not None and hasattr(candidate, "context"):
                worker = candidate
        except Exception:
            worker = None
        return worker or getattr(self, "writing_worker", None)

    def _save_chapter_ai_failure_snapshot(
        self, action, request_id, error="", worker_diagnostics=None, validation_payload=""
    ):
        if not getattr(self, "_novel_diagnostics_enabled", False):
            return ""
        worker = self._chapter_ai_signal_worker()
        context = str(
            getattr(worker, "context", "")
            if worker is not None else getattr(self, "_chapter_ai_running_context", "")
        )
        if not context:
            context = str(getattr(self, "_chapter_ai_running_context", "") or "")
        system_prompt = ""
        if worker is not None and hasattr(worker, "_action_prompt"):
            try:
                system_prompt = str(worker._action_prompt() or "")
            except Exception:
                system_prompt = ""
        partial_output = str(
            getattr(worker, "last_response_text", "")
            if worker is not None else getattr(self, "chapter_ai_stream_text", "")
        )
        if not partial_output:
            partial_output = str(getattr(self, "chapter_ai_stream_text", "") or "")
        request_id = str(request_id or "").strip() or self._next_novel_diagnostic_request_id(
            "chapter-ai-failure"
        )
        project = self.current_project if isinstance(getattr(self, "current_project", None), dict) else {}
        chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
        chapter = (
            chapters[self.current_chapter_index]
            if 0 <= int(getattr(self, "current_chapter_index", -1)) < len(chapters)
            else {}
        )
        provider = getattr(self, "_chapter_ai_provider", {})
        provider = provider if isinstance(provider, dict) else {}
        return save_novel_diagnostic_snapshot(request_id, {
            "request_id": request_id,
            "action": str(action or ""),
            "error": clean_error_text(error) if error else "",
            "project_title": str(project.get("meta", {}).get("title", "") or "")
            if isinstance(project.get("meta"), dict) else "",
            "project_path": str(getattr(self, "current_project_path", "") or ""),
            "chapter_index": int(getattr(self, "current_chapter_index", -1)) + 1,
            "chapter_id": str(chapter.get("id", "") or "") if isinstance(chapter, dict) else "",
            "chapter_title": str(chapter.get("title", "") or "") if isinstance(chapter, dict) else "",
            "provider_id": str(provider.get("id", "") or ""),
            "provider_name": str(provider.get("name", "") or ""),
            "model": str(getattr(self, "_chapter_ai_model", "") or ""),
            "worker_diagnostics": deepcopy(worker_diagnostics)
            if isinstance(worker_diagnostics, dict) else {},
            "context_sections": self._novel_context_section_metrics(context),
            "system_prompt": system_prompt,
            "user_context": context,
            "sent_user_context": context[:NOVEL_AI_CONTEXT_LIMIT]
            if len(context) > NOVEL_AI_CONTEXT_LIMIT else "",
            "partial_output": partial_output,
            "validation_payload": str(validation_payload or ""),
        })

    def _save_chapter_ai_latest_exchange(
        self, action, request_id, output, worker_diagnostics=None
    ):
        if not getattr(self, "_novel_diagnostics_enabled", False):
            return ""
        worker = self._chapter_ai_signal_worker()
        context = str(
            (getattr(worker, "context", "") if worker is not None else "")
            or getattr(self, "_chapter_ai_running_context", "")
            or ""
        )
        system_prompt = ""
        if worker is not None and hasattr(worker, "_action_prompt"):
            try:
                system_prompt = str(worker._action_prompt() or "")
            except Exception:
                system_prompt = ""
        project = self.current_project if isinstance(getattr(self, "current_project", None), dict) else {}
        chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
        chapter = (
            chapters[self.current_chapter_index]
            if 0 <= int(getattr(self, "current_chapter_index", -1)) < len(chapters)
            else {}
        )
        return save_novel_diagnostic_latest_exchange(request_id, {
            "request_id": str(request_id or ""),
            "action": str(action or ""),
            "project_title": str(project.get("meta", {}).get("title", "") or "")
            if isinstance(project.get("meta"), dict) else "",
            "project_path": str(getattr(self, "current_project_path", "") or ""),
            "chapter_index": int(getattr(self, "current_chapter_index", -1)) + 1,
            "chapter_id": str(chapter.get("id", "") or "") if isinstance(chapter, dict) else "",
            "chapter_title": str(chapter.get("title", "") or "") if isinstance(chapter, dict) else "",
            "model": str(getattr(self, "_chapter_ai_model", "") or ""),
            "worker_diagnostics": deepcopy(worker_diagnostics)
            if isinstance(worker_diagnostics, dict) else {},
            "context_sections": self._novel_context_section_metrics(context),
            "system_prompt": system_prompt,
            "user_context": context,
            "sent_user_context": context[:NOVEL_AI_CONTEXT_LIMIT]
            if len(context) > NOVEL_AI_CONTEXT_LIMIT else "",
            "partial_output": str(output or ""),
        })

    def _log_novel_diagnostic(self, event, level="info", **details):
        if not getattr(self, "_novel_diagnostics_enabled", False):
            return ""
        try:
            project = self.current_project if isinstance(getattr(self, "current_project", None), dict) else {}
            chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
            requested_chapter_id = str(
                details.get("chapter_id", "")
                or getattr(self, "_chapter_ai_running_chapter_id", "")
                or ""
            )
            try:
                chapter_index = int(getattr(self, "current_chapter_index", -1))
            except (TypeError, ValueError):
                chapter_index = -1
            if requested_chapter_id:
                for index, item in enumerate(chapters):
                    if isinstance(item, dict) and str(item.get("id", "") or "") == requested_chapter_id:
                        chapter_index = index
                        break
            chapter = (
                chapters[chapter_index]
                if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict)
                else {}
            )
            memory = project.get("long_form_memory", {}) if isinstance(project.get("long_form_memory"), dict) else {}
            snapshot = memory.get("state_snapshot", {}) if isinstance(memory.get("state_snapshot"), dict) else {}
            checkpoint = chapter.get("ai_generation_checkpoint", {}) if isinstance(chapter.get("ai_generation_checkpoint"), dict) else {}
            provider = details.pop("provider", None)
            provider = provider if isinstance(provider, dict) else getattr(self, "_chapter_ai_provider", {})
            provider = provider if isinstance(provider, dict) else {}
            model = str(details.pop("model", "") or getattr(self, "_chapter_ai_model", "") or "")
            action = str(details.get("action", "") or getattr(self, "_chapter_ai_running_action", "") or "")
            request_id = str(
                details.get("request_id", "")
                or getattr(self, "_chapter_ai_diagnostic_request_id", "")
                or ""
            )
            record = {
                "event": str(event or "unknown"),
                "level": str(level or "info"),
                "session_id": str(getattr(self, "_novel_diagnostic_session_id", "") or ""),
                "request_id": request_id,
                "project": {
                    "title": str(project.get("meta", {}).get("title", "") or "")
                    if isinstance(project.get("meta"), dict) else "",
                    "path": str(getattr(self, "current_project_path", "") or ""),
                    "chapter_count": len(chapters),
                },
                "chapter": {
                    "index": chapter_index + 1 if chapter else 0,
                    "id": str(chapter.get("id", "") or requested_chapter_id),
                    "title": str(chapter.get("title", "") or ""),
                    "outline_chars": len(str(chapter.get("outline", "") or "")),
                    "body_chars": len(str(chapter.get("text", "") or "")),
                    "summary_chars": len(str(chapter.get("summary", "") or "")),
                    "key_facts_chars": len(str(chapter.get("key_facts", "") or "")),
                    "memory_sync_status": str(chapter.get("memory_sync_status", "") or ""),
                    "memory_revision": int(chapter.get("memory_revision", 0) or 0),
                    "checkpoint_stage": str(checkpoint.get("stage", "") or ""),
                    "checkpoint_status": str(checkpoint.get("status", "") or ""),
                    "resume_required": bool(chapter.get("auto_expand_resume_required", False)),
                },
                "memory": {
                    "revision": int(memory.get("revision", 0) or 0),
                    "snapshot_chapter_index": int(snapshot.get("as_of_chapter_index", 0) or 0),
                    "snapshot_chapter_id": str(snapshot.get("as_of_chapter_id", "") or ""),
                },
                "pipeline": {
                    "action": action,
                    "sequence_active": bool(getattr(self, "_chapter_ai_sequence_active", False)),
                    "style_workflow_active": bool(getattr(self, "_chapter_ai_style_workflow_active", False)),
                    "auto_expand_active": bool(getattr(self, "_auto_expand_all_active", False)),
                    "auto_expand_completed": int(getattr(self, "_auto_expand_all_completed", 0) or 0),
                    "auto_expand_total": int(getattr(self, "_auto_expand_all_total", 0) or 0),
                },
                "provider": {
                    "id": str(provider.get("id", "") or ""),
                    "name": str(provider.get("name", "") or ""),
                    "model": model,
                },
                "details": details,
            }
            if self._should_log_memory_failure(record):
                append_novel_memory_diagnostic_event(
                    self._compact_memory_failure_record(record)
                )
            return append_novel_diagnostic_event(record)
        except Exception as exc:
            log_debug("小说诊断日志写入失败", exc)
            return ""

    @classmethod
    def _should_log_memory_failure(cls, record):
        if not isinstance(record, dict):
            return False
        event = str(record.get("event", "") or "").strip()
        level = str(record.get("level", "") or "").strip().lower()
        details = record.get("details", {})
        details = details if isinstance(details, dict) else {}
        pipeline = record.get("pipeline", {})
        pipeline = pipeline if isinstance(pipeline, dict) else {}
        action = str(
            details.get("action", "")
            or pipeline.get("action", "")
            or ""
        ).strip()
        if event in cls._MEMORY_FAILURE_EVENTS:
            return True
        if action not in cls._MEMORY_POSTPROCESS_ACTIONS:
            return False
        return level in {"warning", "error", "fatal"} or any(
            marker in event for marker in ("failed", "failure", "retry", "invalid", "parse")
        )

    @staticmethod
    def _compact_memory_failure_record(record):
        details = record.get("details", {}) if isinstance(record, dict) else {}
        details = details if isinstance(details, dict) else {}
        allowed_detail_keys = {
            "error", "error_category", "validation_errors", "issue_categories",
            "issue_count", "validation_attempt", "repair_attempt", "repair_mode",
            "retryable", "retry_scheduled", "retry_attempt", "finalize_attempt",
            "patch_count", "validation_errors", "repair_triggered", "fallback_status",
            "reason", "reason_code", "memory_status", "memory_revision",
            "final_text_chars", "final_text_sha256", "before_chars", "after_chars",
            "before_sha256", "after_sha256", "partial_output_chars",
            "diagnostic_snapshot_path", "prose_patch_applied",
            "transaction_id", "repair_targets", "bundle_summary",
            "state_before", "state_after", "parsed", "output_chars",
            "output_sha256", "validation_error_count", "audit_error_count",
            "bundle_error_count", "checkpoint_summary", "package_status",
            "package_summary", "resume_required",
        }
        compact_details = {
            key: deepcopy(value)
            for key, value in details.items()
            if key in allowed_detail_keys
        }
        worker = details.get("worker_diagnostics", {})
        if isinstance(worker, dict):
            worker_keys = {
                "http_status", "response_chars", "response_utf8_bytes", "elapsed_ms",
                "time_to_headers_ms", "time_to_first_piece_ms", "finish_reason",
                "invalid_sse_json_lines", "ignored_reasoning_chars",
                "response_char_limit_exceeded", "json_response_format_fallback",
                "json_response_format_transport_fallback", "reasoning_effort_requested",
                "max_output_tokens", "request_timeout_seconds", "content_type",
            }
            compact_details["worker_diagnostics"] = {
                key: deepcopy(value) for key, value in worker.items() if key in worker_keys
            }
        project = record.get("project", {}) if isinstance(record, dict) else {}
        chapter = record.get("chapter", {}) if isinstance(record, dict) else {}
        memory = record.get("memory", {}) if isinstance(record, dict) else {}
        pipeline = record.get("pipeline", {}) if isinstance(record, dict) else {}
        provider = record.get("provider", {}) if isinstance(record, dict) else {}
        return {
            "record_type": "novel_memory_failure",
            "event": str(record.get("event", "unknown") or "unknown"),
            "level": str(record.get("level", "info") or "info"),
            "session_id": str(record.get("session_id", "") or ""),
            "request_id": str(record.get("request_id", "") or ""),
            "mode": (
                "auto_expand"
                if isinstance(pipeline, dict) and pipeline.get("auto_expand_active")
                else "single_chapter"
            ),
            "project": {
                "title": str(project.get("title", "") or "") if isinstance(project, dict) else "",
                "path": str(project.get("path", "") or "") if isinstance(project, dict) else "",
            },
            "chapter": {
                "index": int(chapter.get("index", 0) or 0) if isinstance(chapter, dict) else 0,
                "id": str(chapter.get("id", "") or "") if isinstance(chapter, dict) else "",
                "title": str(chapter.get("title", "") or "") if isinstance(chapter, dict) else "",
                "memory_sync_status": str(chapter.get("memory_sync_status", "") or "")
                if isinstance(chapter, dict) else "",
                "memory_revision": int(chapter.get("memory_revision", 0) or 0)
                if isinstance(chapter, dict) else 0,
            },
            "memory": {
                "revision": int(memory.get("revision", 0) or 0) if isinstance(memory, dict) else 0,
                "snapshot_chapter_index": int(memory.get("snapshot_chapter_index", 0) or 0)
                if isinstance(memory, dict) else 0,
                "snapshot_chapter_id": str(memory.get("snapshot_chapter_id", "") or "")
                if isinstance(memory, dict) else "",
            },
            "pipeline": {
                "action": str(pipeline.get("action", "") or "") if isinstance(pipeline, dict) else "",
                "sequence_active": bool(pipeline.get("sequence_active", False))
                if isinstance(pipeline, dict) else False,
                "auto_expand_active": bool(pipeline.get("auto_expand_active", False))
                if isinstance(pipeline, dict) else False,
                "auto_expand_completed": int(pipeline.get("auto_expand_completed", 0) or 0)
                if isinstance(pipeline, dict) else 0,
                "auto_expand_total": int(pipeline.get("auto_expand_total", 0) or 0)
                if isinstance(pipeline, dict) else 0,
            },
            "provider": {
                "id": str(provider.get("id", "") or "") if isinstance(provider, dict) else "",
                "name": str(provider.get("name", "") or "") if isinstance(provider, dict) else "",
                "model": str(provider.get("model", "") or "") if isinstance(provider, dict) else "",
            },
            "details": compact_details,
        }

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
            self._refresh_visible_helper_page(page_index)

    def _refresh_visible_helper_page(self, page_index=None):
        if not hasattr(self, "page_indexes"):
            return
        if page_index is None and hasattr(self, "tabs"):
            page_index = self.tabs.currentIndex()
        if page_index == self.page_indexes.get("书稿"):
            self.ensure_manuscript_fresh()
        elif page_index == self.page_indexes.get("检查"):
            self.ensure_writing_check_fresh()

    def _show_deferred_helper_page_notice(self, page_index=None):
        if not hasattr(self, "page_indexes"):
            return
        if page_index is None and hasattr(self, "tabs"):
            page_index = self.tabs.currentIndex()
        if page_index == self.page_indexes.get("书稿") and getattr(self, "_manuscript_stale", False):
            self._set_text_without_signals(
                self.manuscript_edit,
                "完整书稿已随项目切换标记为待刷新。\n\n点击上方“刷新汇总”后再查看、复制或导出全文。",
            )
        elif page_index == self.page_indexes.get("检查") and getattr(self, "_writing_check_stale", False):
            self._set_text_without_signals(
                self.check_edit,
                "写作检查已随项目切换标记为待刷新。\n\n点击上方“刷新检查”后再查看当前项目问题。",
            )

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
        self.bible_edit.setPlaceholderText("核心设定、读者承诺、主题、核心动机契约、关系底盘、结局方向、禁用设定等。")
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
            "draft_note_edit": "仅自己可见的长篇提醒，不会自动进入 AI 写作上下文。",
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
        self.char_personality = QLineEdit()
        self.char_voice = QLineEdit()
        self.char_style_favorite_btn = QPushButton("收藏为主角风格")
        self.char_style_favorite_btn.setToolTip(
            "只收藏当前人物卡的性格/特点和语言风格，供新建向导选择"
        )
        self.char_style_favorite_btn.clicked.connect(self._toggle_character_style_favorite)
        self.char_name.setPlaceholderText("填写人物姓名，左侧列表会自动更新。")
        self.char_role.setPlaceholderText("例如：国公府世子、女主、反派、师父。")
        self.char_goal.setPlaceholderText("这个人物最想得到什么，或者最想避免什么。")
        self.char_secret.setPlaceholderText("暂时不能让读者或其他角色知道的隐藏信息。")
        self.char_personality.setPlaceholderText("人物性格/特点，比如搞笑、好胜、敏感、嘴硬、优柔寡断。")
        self.char_voice.setPlaceholderText("语言风格分类，比如话多、话少、喜欢开玩笑、无厘头、爱打岔。")
        for w in (self.char_name, self.char_role, self.char_goal, self.char_secret, self.char_personality, self.char_voice):
            self._wide_field(w)
        self.char_notes = PlainTextEdit()
        self._wide_field(self.char_notes)
        self._expand_text_edit(self.char_notes, 110)
        self.char_notes.setPlaceholderText("只写长期关系底色、稳定身份变化和后续必须继承的事实；不要写固定笑点、具体剧情动作、道具或一次性反应。")
        for w in (self.char_name, self.char_role, self.char_goal, self.char_secret, self.char_personality, self.char_voice):
            w.textChanged.connect(self._mark_character_dirty)
        self.char_notes.textChanged.connect(self._mark_character_dirty)
        form.addRow("姓名", self.char_name)
        form.addRow("身份", self.char_role)
        form.addRow("人物目标", self.char_goal)
        form.addRow("隐藏秘密", self.char_secret)
        form.addRow("人物性格/特点", self.char_personality)
        voice_row = QWidget()
        voice_layout = QHBoxLayout(voice_row)
        voice_layout.setContentsMargins(0, 0, 0, 0)
        voice_layout.setSpacing(6)
        voice_layout.addWidget(self.char_voice, 1)
        voice_layout.addWidget(self.char_style_favorite_btn)
        form.addRow("语言风格", voice_row)
        form.addRow("长期备注", self.char_notes)

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
        self.lore_type.addItems(LORE_TYPE_OPTIONS)
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
        left_layout.addLayout(self._button_grid((
            ("新增", self.add_foreshadow),
            ("删除", self.delete_foreshadow),
        ), button_store=self.foreshadow_action_buttons))

        right = QFrame()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        form_box = QFrame()
        form = QFormLayout(form_box)
        self._setup_form(form)
        self.foreshadow_name = QLineEdit()
        self.foreshadow_code = QLineEdit()
        self.foreshadow_status = WideComboBox()
        self.foreshadow_status.addItems(["未埋", "已埋", "已回收", "无需回收", "废弃"])
        self.foreshadow_setup = QLineEdit()
        self.foreshadow_payoff = QLineEdit()
        self.foreshadow_desc = PlainTextEdit()
        self.foreshadow_notes = PlainTextEdit()
        for w in (
            self.foreshadow_code,
            self.foreshadow_name,
            self.foreshadow_status,
            self.foreshadow_setup,
            self.foreshadow_payoff,
            self.foreshadow_desc,
            self.foreshadow_notes,
        ):
            self._wide_field(w)
        self.foreshadow_code.setReadOnly(True)
        self.foreshadow_code.setPlaceholderText("自动编号，如 F0001")
        self.foreshadow_desc.setPlaceholderText("写清这个伏笔是什么、读者看到什么、真正含义是什么。")
        self.foreshadow_notes.setPlaceholderText("体检/合并时的命中编号、建议状态、建议说明，仅供查看，不进上下文。")
        self.foreshadow_name.setPlaceholderText("例如：虎符失踪、世子装傻、旧案真凶。")
        self.foreshadow_setup.setPlaceholderText("例如：第3章")
        self.foreshadow_payoff.setPlaceholderText("例如：第28章")
        self.foreshadow_code.textChanged.connect(self._mark_foreshadow_dirty)
        self.foreshadow_name.textChanged.connect(self._mark_foreshadow_dirty)
        self.foreshadow_status.currentTextChanged.connect(self._mark_foreshadow_dirty)
        self.foreshadow_setup.textChanged.connect(self._mark_foreshadow_dirty)
        self.foreshadow_payoff.textChanged.connect(self._mark_foreshadow_dirty)
        self.foreshadow_desc.textChanged.connect(self._mark_foreshadow_dirty)
        form.addRow("编号", self.foreshadow_code)
        form.addRow("名称", self.foreshadow_name)
        form.addRow("状态", self.foreshadow_status)
        form.addRow("埋设章节", self.foreshadow_setup)
        form.addRow("回收章节", self.foreshadow_payoff)
        form.addRow("说明", self.foreshadow_desc)
        form.addRow("备注", self.foreshadow_notes)
        right_layout.addWidget(form_box, 1)

        return self._two_pane_tab(left, right)

    def _build_chapters_tab(self):
        left, left_layout = self._plain_frame()
        self.chapter_list = QListWidget()
        self.chapter_list.currentRowChanged.connect(self._on_chapter_selected)
        left_layout.addWidget(self.chapter_list, 1)
        chapter_action_grid = QGridLayout()
        chapter_action_grid.setHorizontalSpacing(6)
        chapter_action_grid.setVerticalSpacing(6)
        chapter_action_buttons = (
            (0, 0, self._ghost_button("新增", self.add_chapter)),
            (0, 1, self._ghost_button(
                "AI生成章节规划",
                self.generate_chapter_plan,
                "根据项目信息、圣经、世界观、人物、设定、时间线和伏笔生成章节名与章节提纲；生成后先预览，确认后再写入章节列表。",
            )),
            (1, 0, self._ghost_button("删除", self.delete_chapter)),
            (1, 1, self._ghost_button(
                "重置所有章节",
                self.reset_all_chapters,
                "清除所有章节的正文和状态整理，保留章节标题、提纲、阶段、字数和规划关联人物。",
            )),
            (2, 0, self._ghost_button(
                "按章节导出/拆分导出",
                self.choose_chapter_export_mode,
                "按现有章节和章节名直接导出，或按目标字数重新拆分并本地快速取名",
            )),
            (2, 1, self._ghost_button(
                "番茄批量上传",
                self.open_fanqie_batch_upload,
                "选择本地项目和番茄后台目标作品，可上传草稿、直接发布或定时发布；支持断点续传。",
            )),
        )
        for row, column, btn in chapter_action_buttons:
            chapter_action_grid.addWidget(btn, row, column)
            if btn.text() == "番茄批量上传":
                self.fanqie_upload_btn = btn
            if btn.text() == "AI生成章节规划":
                self.chapter_plan_btn = btn
                self.chapter_ai_action_buttons.append(btn)
        left_layout.addLayout(chapter_action_grid)

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
        self._expand_text_edit(self.chapter_outline, 90, bottom_scroll_padding=32)
        self.chapter_outline.setPlaceholderText("本章处境、推进方向、可能转折与结尾悬念。")
        self.chapter_text = PlainTextEdit()
        self._expand_text_edit(self.chapter_text, 180, bottom_scroll_padding=36)
        self.chapter_text.setPlaceholderText("正文草稿。")
        self.chapter_summary = PlainTextEdit()
        self._expand_text_edit(self.chapter_summary, 80, bottom_scroll_padding=28)
        self.chapter_summary.setPlaceholderText("简短总结本章发生了什么。")
        self.chapter_key_facts = PlainTextEdit()
        self._expand_text_edit(self.chapter_key_facts, 80, bottom_scroll_padding=28)
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
            btn.setToolTip("先扩写完整正文，再根据实际正文补提纲和摘要/关键事实")
            btn.clicked.connect(lambda _checked=False, a=action: self.run_chapter_ai_action(a))
            ai_top.addWidget(btn)
            self.chapter_ai_action_buttons.append(btn)
            self._chapter_ai_buttons_by_action[action] = btn
        self.auto_expand_all_btn = self._ghost_button("自动扩写全部")
        self.auto_expand_all_btn.setToolTip("跳过已有正文，按章节顺序自动完成所有未写章节；遇到失败会停止")
        self.auto_expand_all_btn.clicked.connect(self.start_auto_expand_all_chapters)
        ai_top.addWidget(self.auto_expand_all_btn)
        self.chapter_ai_action_buttons.append(self.auto_expand_all_btn)
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
        self.chapter_ai_preview.textChanged.connect(self._on_chapter_ai_preview_text_changed)
        ai_body_layout.addWidget(self.chapter_ai_preview, 1)
        plan_action_row = QHBoxLayout()
        plan_action_row.addStretch()
        self.chapter_plan_apply_btn = self._ghost_button("应用章节规划", self.apply_chapter_plan)
        self.chapter_plan_apply_btn.setToolTip("把预览中的章节规划追加写入章节列表。")
        self.chapter_plan_apply_btn.setVisible(False)
        plan_action_row.addWidget(self.chapter_plan_apply_btn)
        ai_body_layout.addLayout(plan_action_row)

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
        self.search_input.setPlaceholderText("输入关键词，搜索当前项目的全部内容。")
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
            widget.itemClicked.connect(
                lambda item, w=widget, k=kind: self.show_import_candidate_detail(k, w.row(item))
            )

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
        lst.setSelectionMode(QListWidget.NoSelection)
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

    def _schedule_autosave_only(self):
        if self._loading:
            return
        self._update_stats_label()
        timer = getattr(self, "_refresh_timer", None)
        if timer is not None:
            timer.start()

    def _mark_helper_pages_stale(self, manuscript=True, writing_check=True):
        if manuscript:
            self._manuscript_stale = True
        if writing_check:
            self._writing_check_stale = True

    def ensure_manuscript_fresh(self):
        if getattr(self, "_manuscript_stale", False):
            self.refresh_manuscript()

    def ensure_writing_check_fresh(self):
        if getattr(self, "_writing_check_stale", False):
            self.refresh_writing_check()

    def _note_project_dirty(self):
        self._dirty = True
        self._project_file_dirty = True
        self._chapter_order_search_cache = None
        try:
            self._dirty_generation = int(getattr(self, "_dirty_generation", 0) or 0) + 1
        except Exception:
            self._dirty_generation = 1
        self._last_failed_autosave_generation = -1

    def _has_unsaved_current_work(self):
        return bool(
            getattr(self, "_dirty", False)
            or getattr(self, "_project_file_dirty", False)
        )

    def _project_file_signature(self, path):
        path = str(path or "").strip()
        if not path or not os.path.exists(path):
            return ()
        try:
            stat = os.stat(path)
            mtime_ns = int(getattr(stat, "st_mtime_ns", stat.st_mtime * 1_000_000_000))
            return mtime_ns, int(stat.st_size)
        except Exception:
            return ()

    def _record_current_project_file_signature(self, path=None):
        target = str(path or getattr(self, "current_project_path", "") or "").strip()
        self._loaded_project_file_signature = self._project_file_signature(target)

    def _project_payload_matches(self, first, second):
        try:
            left = _normalize_project(first if isinstance(first, dict) else {})
            right = _normalize_project(second if isinstance(second, dict) else {})
            left.pop("updated_at", None)
            right.pop("updated_at", None)
            return left == right
        except Exception:
            return False

    def _handle_external_project_change_before_save(self, data, reason, refresh_project_list=True):
        path = str(getattr(self, "current_project_path", "") or "").strip()
        if not path or path == NOVEL_DRAFT_FILE:
            return False
        expected = tuple(getattr(self, "_loaded_project_file_signature", ()) or ())
        current = self._project_file_signature(path)
        if not expected or not current or current == expected:
            return False

        disk_data = load_json_file(path, None)
        if isinstance(disk_data, dict) and self._project_payload_matches(data, disk_data):
            self._loaded_project_file_signature = current
            return False

        title = str((data.get("meta", {}) if isinstance(data, dict) else {}).get("title", "") or "").strip()
        project_title = title or "未命名小说"
        backup_title = f"{project_title}_外部更新前备份"
        backup_path = unique_project_backup_path(project_title, "外部更新前备份")
        backup_data = deepcopy(data if isinstance(data, dict) else {})
        backup_meta = backup_data.setdefault("meta", {})
        if not isinstance(backup_meta, dict):
            backup_meta = {}
            backup_data["meta"] = backup_meta
        backup_meta["title"] = backup_title

        try:
            save_project_file(backup_path, backup_data)
        except Exception as e:
            self._log_novel_diagnostic(
                "external_project_conflict_backup_failed",
                level="error",
                reason=str(reason or ""),
                project_path=path,
                backup_path=backup_path,
                error_category="storage",
                **self._novel_exception_details(e),
            )
            log_debug("小说项目外部更新冲突备份失败", e)
            self.set_status_tip("检测到项目已被外部更新，已阻止旧内容覆盖；冲突备份失败。")
            return True

        if isinstance(disk_data, dict):
            self._load_project_data(disk_data, path, defer_helpers=True)
            self._remember_project_path(path)
            status_text = (
                "检测到项目已被外部更新，已加载磁盘新版本；"
                f"旧内存已备份为 {os.path.basename(backup_path)}。"
            )
        else:
            self.current_project_path = NOVEL_DRAFT_FILE
            self.current_project = _normalize_project(backup_data)
            self._loaded_project_file_signature = ()
            clear_last_project_path()
            status_text = (
                "检测到项目文件已变化但无法读取；当前内容已转为自动草稿，"
                f"并备份为 {os.path.basename(backup_path)}。"
            )
        self._save_draft_snapshot()
        self._dirty = False
        self._project_file_dirty = False
        if refresh_project_list:
            self._notify_project_store_changed()
        self.set_status_tip(status_text)
        self._log_novel_perf(
            f"阻止外部更新被覆盖-{reason}",
            time.perf_counter(),
            threshold_ms=0,
            path=os.path.basename(path),
            backup=os.path.basename(backup_path),
        )
        return True

    def _mark_dirty(self):
        if self._loading:
            return
        self._note_project_dirty()
        self._save_current_fields()
        self.refresh_project_summary_label()
        self._refresh_current_project_list_item_from_memory()
        self._schedule_refresh()

    def _mark_character_dirty(self):
        if self._loading:
            return
        self._note_project_dirty()
        self._save_character_from_editor()
        self._schedule_refresh()

    def _mark_lore_dirty(self):
        if self._loading:
            return
        self._note_project_dirty()
        self._save_lore_from_editor()
        self._schedule_refresh()

    def _mark_foreshadow_dirty(self):
        if self._loading:
            return
        self._note_project_dirty()
        self._save_foreshadow_from_editor()
        self._schedule_refresh()

    def _mark_chapter_dirty(self):
        if self._loading:
            return
        self._note_project_dirty()
        self._save_chapter_from_editor()
        self._refresh_current_project_list_item_from_memory()
        self._mark_helper_pages_stale()
        self._schedule_autosave_only()

    def _auto_update_project_status(self, chapter_plan_applied=False):
        """Advance project status only at explicit planning or save milestones."""
        if not isinstance(getattr(self, "current_project", None), dict):
            return False
        meta = self.current_project.setdefault("meta", {})
        current_status = str(meta.get("status", "") or "").strip() or "草稿"
        next_status = ""
        if chapter_plan_applied and current_status == "草稿":
            next_status = "连载中"
        elif current_status in {"草稿", "连载中"} and _project_ready_for_completion(
            self.current_project
        ):
            next_status = "已完结"
        if not next_status or next_status == current_status:
            return False
        meta["status"] = next_status
        if hasattr(self, "status_combo"):
            self._set_combo_text_without_signals(self.status_combo, next_status)
        self._refresh_current_project_list_item_from_memory()
        return True

    def _save_current_work(
        self,
        reason="自动保存",
        refresh_project_list=True,
        preserve_project_mtime=False,
        update_draft=True,
    ):
        if self._current_background_chapter_runner() is not None:
            return self.current_project_path
        if self._current_fanqie_upload_worker() is not None:
            return self.current_project_path
        perf_start = time.perf_counter()
        summary = self._novel_perf_summary()
        try:
            self._flush_current_editors()
            self._auto_update_project_status()
            self._sync_candidate_analysis_state()
            self._sync_import_candidates_to_project()
            data = deepcopy(self.current_project)
            current_path = self.current_project_path
            if current_path and current_path not in ("", NOVEL_DRAFT_FILE):
                if self._handle_external_project_change_before_save(data, reason, refresh_project_list):
                    return current_path
                save_project_file(current_path, data, preserve_mtime=preserve_project_mtime)
                self._record_current_project_file_signature(current_path)
                self._remember_project_path(current_path)
                if update_draft:
                    self._save_draft_snapshot()
                else:
                    self._draft_saved_once = True
                if refresh_project_list:
                    self._notify_project_store_changed()
                self._dirty = False
                self._project_file_dirty = False
                self._update_stats_label()
                self._log_novel_perf(
                    f"保存当前项目-{reason}",
                    perf_start,
                    threshold_ms=120,
                    path=os.path.basename(current_path),
                    chapters=summary.get("chapters"),
                    body=summary.get("body_chars"),
                    refresh_list=refresh_project_list,
                    update_draft=bool(update_draft),
                )
                return current_path
            self._save_draft_snapshot()
            self._dirty = False
            self._project_file_dirty = False
            self._update_stats_label()
            self._log_novel_perf(
                f"保存当前草稿-{reason}",
                perf_start,
                threshold_ms=120,
                chapters=summary.get("chapters"),
                body=summary.get("body_chars"),
            )
            return NOVEL_DRAFT_FILE
        except Exception as e:
            self._log_novel_perf(
                f"保存当前项目失败-{reason}",
                perf_start,
                threshold_ms=0,
                chapters=summary.get("chapters"),
                body=summary.get("body_chars"),
            )
            self._log_novel_diagnostic(
                "project_save_failed",
                level="error",
                save_reason=str(reason or ""),
                project_path=str(getattr(self, "current_project_path", "") or NOVEL_DRAFT_FILE),
                preserve_project_mtime=bool(preserve_project_mtime),
                refresh_project_list=bool(refresh_project_list),
                project_summary=summary,
                error_category="storage",
                **self._novel_exception_details(e),
            )
            log_debug(f"小说项目{reason}失败", e)
            return ""

    def _has_saved_project_path(self):
        path = str(self.current_project_path or "").strip()
        return bool(path and path != NOVEL_DRAFT_FILE)

    def _save_after_import(self):
        try:
            self._flush_current_editors()
            self._auto_update_project_status()
            self._sync_candidate_analysis_state()
            self._sync_import_candidates_to_project()
            if self._has_saved_project_path():
                if self._handle_external_project_change_before_save(
                    deepcopy(self.current_project), "导入后保存", True
                ):
                    return "检测到外部更新，已保留磁盘新版本并备份当前内容。"
                save_project_file(self.current_project_path, self.current_project)
                self._record_current_project_file_signature(self.current_project_path)
                self._remember_project_path(self.current_project_path)
                self._save_draft_snapshot()
                self._notify_project_store_changed()
                self._dirty = False
                self._project_file_dirty = False
                self._update_stats_label()
                return "已保存到原项目。"
            self._save_draft_snapshot()
            self._update_stats_label()
            return "已保存到自动草稿。"
        except Exception as e:
            self._log_novel_diagnostic(
                "project_import_save_failed",
                level="error",
                project_path=str(getattr(self, "current_project_path", "") or NOVEL_DRAFT_FILE),
                error_category="storage",
                **self._novel_exception_details(e),
            )
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
            self.project_hint.setText("当前没有已保存项目；当前内容会自动保存到草稿。" if not records else "单击列表可打开已保存小说。")

    def _refresh_current_project_list_item_from_memory(self):
        if not hasattr(self, "project_list"):
            return False
        current_path = str(self.current_project_path or "").strip()
        if not current_path or current_path == NOVEL_DRAFT_FILE:
            return False
        target = os.path.abspath(current_path)
        fallback_title = os.path.splitext(os.path.basename(current_path))[0]
        text = _project_list_text(self.current_project, fallback_title)
        for row in range(self.project_list.count()):
            item = self.project_list.item(row)
            if item is None:
                continue
            item_path = os.path.abspath(str(item.data(Qt.UserRole) or ""))
            if item_path != target:
                continue
            item.setText(text)
            item.setToolTip(current_path)
            return True
        return False

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

    def _ai_project_snapshot(self):
        volume_opening_handoff = _build_volume_opening_handoff_context(
            self.current_project,
            total_limit=12000,
        )
        project = _project_without_private_notes(self.current_project)
        if volume_opening_handoff:
            project["volume_opening_handoff_context"] = volume_opening_handoff
        project["style_profile_cache"] = deepcopy(self.current_project.get("style_profile_cache", {}))
        profile_id = str(self.current_project.get("style_profile_id", "") or "").strip().lower()
        if not profile_id or profile_id == "__none__":
            project["style_reference"] = ""
            project["style_profile_cache"] = {}
            return project
        if profile_id:
            profile = get_style_profile(profile_id)
            if profile:
                reference = str(profile.get("style_reference", "") or "").strip()
                reference_hash = str(profile.get("reference_hash", "") or profile_id).strip().lower()
                cache_entry = profile.get("cache_entry", {})
                if reference and isinstance(cache_entry, dict):
                    project["style_reference"] = reference
                    project["style_profile_cache"] = {reference_hash: deepcopy(cache_entry)}
        return project

    def get_current_project_snapshot(self):
        return self._current_project_to_data(), self.current_project_path or ""

    def _update_stats_label(self):
        if not hasattr(self, "project_meta_label"):
            return
        path = str(self.current_project_path or "").strip()
        source = self._project_title()
        self.project_meta_label.setToolTip(path or "未保存项目")
        self.project_meta_label.setText(_project_meta_text(self.current_project, source))

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
        if hasattr(self, "style_profile_combo") and self.style_profile_combo.currentIndex() >= 0:
            self.current_project["style_profile_id"] = str(
                self.style_profile_combo.currentData() or ""
            ).strip().lower()
        self.current_project["draft_note"] = self.draft_note_edit.toPlainText()
        chapters, removed = _dedupe_chapters(self.current_project.get("chapters", []))
        if removed:
            self.current_project["chapters"] = chapters
            if self.current_chapter_index >= len(chapters):
                self.current_chapter_index = len(chapters) - 1
        _ensure_foreshadow_codes(self.current_project)

    def _refresh_project_material_editors(self):
        pairs = [
            ("bible", self.bible_edit),
            ("world_rules", self.world_rules_edit),
            ("draft_note", self.draft_note_edit),
        ]
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
        char["personality"] = self.char_personality.text().strip()
        char["voice"] = self.char_voice.text().strip()
        char["notes"] = self.char_notes.toPlainText().strip()
        favorite_id = str(char.get("style_favorite_id", "") or "").strip()
        if favorite_id and not any(
            item.get("id") == favorite_id for item in load_character_style_library()
        ):
            # A style removed from the wizard must not be recreated by autosave.
            char["style_favorite_id"] = ""
            favorite_id = ""
        if favorite_id:
            if char["personality"] and char["voice"]:
                upsert_character_style(
                    char["personality"],
                    char["voice"],
                    name=char["name"],
                    source_project=str(
                        self.current_project.get("meta", {}).get("title", "")
                        if isinstance(self.current_project.get("meta", {}), dict)
                        else ""
                    ).strip(),
                    source_character=char["name"],
                    style_id=favorite_id,
                )
            else:
                remove_character_style(favorite_id)
                char["style_favorite_id"] = ""
        self._refresh_character_item(index)
        if index == self.current_character_index:
            self._update_character_style_favorite_button()

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
        item["code"] = _normalize_foreshadow_code(self.foreshadow_code.text().strip()) or item.get("code", "")
        item["name"] = self.foreshadow_name.text().strip()
        item["status"] = self.foreshadow_status.currentText().strip()
        item["setup_chapter"] = self.foreshadow_setup.text().strip()
        item["payoff_chapter"] = self.foreshadow_payoff.text().strip()
        item["description"] = self.foreshadow_desc.toPlainText().strip()
        item["notes"] = self.foreshadow_notes.toPlainText().strip()
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
        _update_chapter_analysis_status_cache(chap, allow_similarity=False)
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
            ("性格/特点", char.get("personality", "")),
            ("语言", char.get("voice", "")),
            ("长期备注", char.get("notes", "")),
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

    def _chapter_order_search_texts(self):
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        chapters = chapters if isinstance(chapters, list) else []
        cached = getattr(self, "_chapter_order_search_cache", None)
        if cached and cached.get("chapters") is chapters:
            return cached.get("texts", [])
        texts = []
        for index, chap in enumerate(chapters):
            if not isinstance(chap, dict):
                texts.append((index, ""))
                continue
            linked = chap.get("linked_characters", [])
            linked_text = " ".join(str(value or "") for value in (linked if isinstance(linked, list) else [linked]))
            chapter_text = "\n".join(
                str(chap.get(field, "") or "")
                for field in ("title", "outline", "summary", "key_facts", "text")
            )
            texts.append((index, re.sub(r"\s+", "", f"{linked_text}\n{chapter_text}")))
        self._chapter_order_search_cache = {"chapters": chapters, "texts": texts}
        return texts

    def _first_record_appearance_order(self, item, fields):
        item = item if isinstance(item, dict) else {}
        aliases = _record_alias_keys(item, name_key="name")
        name = str(item.get("name", "") or "").strip()
        if name:
            aliases.add(_character_merge_key(item) if "role" in item else re.sub(r"\s+", "", name))
        aliases = {alias for alias in aliases if alias}
        if aliases:
            for index, compact in self._chapter_order_search_texts():
                if any(alias in compact for alias in aliases):
                    return index + 1
        return _story_order_from_text(_record_text_for_sort(item, fields))

    def _indexed_sort_key(self, group_key, source_index, item):
        item = item if isinstance(item, dict) else {}
        if group_key == "characters":
            order = self._first_record_appearance_order(item, ("name", "role", "goal", "secret", "personality", "voice", "notes"))
            name = str(item.get("name", "") or "")
            return (order, str(item.get("name", "") or "").strip() == "", source_index, name)
        if group_key == "lore":
            order = self._first_record_appearance_order(item, ("name", "type", "description"))
            typ = str(item.get("type", "") or "")
            name = str(item.get("name", "") or "")
            return (order, typ, source_index, name)
        if group_key == "foreshadows":
            code_number = _foreshadow_code_number(item.get("code", ""))
            name = str(item.get("name", "") or "")
            return (code_number <= 0, code_number or source_index + 1, source_index, name)
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

    def _refresh_long_form_record_views(self):
        for widget_attr, index_attr, reload_name in (
            ("character_list", "current_character_index", "_reload_character_list"),
            ("lore_list", "current_lore_index", "_reload_lore_list"),
            ("foreshadow_list", "current_foreshadow_index", "_reload_foreshadow_list"),
        ):
            if not hasattr(self, widget_attr):
                continue
            selected_index = getattr(self, index_attr, -1)
            getattr(self, reload_name)(selected_index if selected_index >= 0 else None)

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

    def _update_character_style_favorite_button(self):
        button = getattr(self, "char_style_favorite_btn", None)
        if button is None:
            return
        index = getattr(self, "current_character_index", -1)
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = -1
        characters = self.current_project.get("characters", [])
        if index < 0 or index >= len(characters):
            button.setEnabled(False)
            button.setText("收藏为主角风格")
            return
        favorite_id = str(characters[index].get("style_favorite_id", "") or "").strip()
        if favorite_id and not any(
            item.get("id") == favorite_id for item in load_character_style_library()
        ):
            favorite_id = ""
        button.setEnabled(True)
        button.setText("取消主角风格收藏" if favorite_id else "收藏为主角风格")

    def _toggle_character_style_favorite(self):
        index = getattr(self, "current_character_index", -1)
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = -1
        characters = self.current_project.get("characters", [])
        if index < 0 or index >= len(characters):
            return
        self._save_character_at_index(index)
        char = characters[index]
        favorite_id = str(char.get("style_favorite_id", "") or "").strip()
        if favorite_id:
            remove_character_style(favorite_id)
            char["style_favorite_id"] = ""
            self._update_character_style_favorite_button()
            self._mark_dirty()
            return
        personality = str(char.get("personality", "") or "").strip()
        voice = str(char.get("voice", "") or "").strip()
        if not personality or not voice:
            QMessageBox.information(
                self,
                "收藏人物风格",
                "请先填写完整的“人物性格/特点”和“语言风格”，再收藏为主角风格。",
            )
            return
        project_meta = self.current_project.get("meta", {})
        source_project = project_meta.get("title", "") if isinstance(project_meta, dict) else ""
        favorite_id = upsert_character_style(
            personality,
            voice,
            name=char.get("name", ""),
            source_project=source_project,
            source_character=char.get("name", ""),
        )
        if not favorite_id:
            QMessageBox.warning(self, "收藏人物风格", "保存人物风格失败，请稍后重试。")
            return
        char["style_favorite_id"] = favorite_id
        self._update_character_style_favorite_button()
        self._mark_dirty()

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
                for w in (self.char_name, self.char_role, self.char_goal, self.char_secret, self.char_personality, self.char_voice):
                    w.clear()
                self.char_notes.clear()
                self.current_character_index = -1
                self._update_character_style_favorite_button()
                return
            char = self.current_project["characters"][row]
            self.char_name.setText(char.get("name", ""))
            self.char_role.setText(char.get("role", ""))
            self.char_goal.setText(char.get("goal", ""))
            self.char_secret.setText(char.get("secret", ""))
            self.char_personality.setText(char.get("personality", ""))
            self.char_voice.setText(char.get("voice", ""))
            self.char_notes.setPlainText(char.get("notes", ""))
            self.current_character_index = row
            self._update_character_style_favorite_button()
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
            lore_type = str(lore.get("type", "地点") or "地点").strip() or "地点"
            idx = self.lore_type.findText(lore_type)
            if idx < 0:
                # Preserve a legacy/custom type instead of silently changing
                # the stored record to the first visible option.
                self.lore_type.addItem(lore_type)
                idx = self.lore_type.findText(lore_type)
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
                self.foreshadow_code.clear()
                self.foreshadow_name.clear()
                self.foreshadow_status.setCurrentIndex(0)
                self.foreshadow_setup.clear()
                self.foreshadow_payoff.clear()
                self.foreshadow_desc.clear()
                self.foreshadow_notes.clear()
                self.current_foreshadow_index = -1
                return
            item = self.current_project["foreshadow_items"][row]
            self.foreshadow_code.setText(item.get("code", ""))
            self.foreshadow_name.setText(item.get("name", ""))
            idx = self.foreshadow_status.findText(item.get("status", "未埋"))
            self.foreshadow_status.setCurrentIndex(idx if idx >= 0 else 0)
            self.foreshadow_setup.setText(item.get("setup_chapter", ""))
            self.foreshadow_payoff.setText(item.get("payoff_chapter", ""))
            self.foreshadow_desc.setPlainText(item.get("description", ""))
            self.foreshadow_notes.setPlainText(item.get("notes", ""))
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

    def review_foreshadows_with_ai(self):
        if self.foreshadow_review_worker is not None and self.foreshadow_review_worker.isRunning():
            self.set_status_tip("AI 伏笔体检正在进行，请稍等。")
            return
        if self.analysis_worker is not None and self.analysis_worker.isRunning():
            self.set_status_tip("AI 分析候选正在进行，请稍后再做伏笔体检。")
            return
        self._flush_current_editors()
        items = self.current_project.get("foreshadow_items", [])
        items = items if isinstance(items, list) else []
        if not any(isinstance(item, dict) and str(item.get("name", "") or "").strip() for item in items):
            QMessageBox.information(self, "AI 伏笔体检", "当前没有可体检的结构化伏笔。")
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self.set_ai_settings_expanded(True)
            self.set_status_tip(f"AI 伏笔体检失败：{error}")
            QMessageBox.warning(self, "AI 伏笔体检失败", error)
            return
        if (
            getattr(self, "foreshadow_review_comparison_state", {})
            and str(self.foreshadow_review_comparison_state.get("status", "") or "") in {"pending", "failed"}
            and not (self.failed_foreshadow_review_chunks or [])
            and self.foreshadow_review_observations.get("foreshadows")
        ):
            self._start_foreshadow_review_comparison(provider, model)
            return
        retry_chunk_items = [
            deepcopy(item)
            for item in (getattr(self, "failed_foreshadow_review_chunks", []) or [])
            if isinstance(item, dict) and str(item.get("text", "") or "").strip()
        ]
        if retry_chunk_items:
            review_chunks = retry_chunk_items
        else:
            review_chunks = _foreshadow_review_chapter_chunks(self._ai_project_snapshot())
        if not review_chunks:
            QMessageBox.information(self, "AI 伏笔体检", "没有可用于体检的章节正文。")
            return
        concurrency = self._candidate_analysis_concurrency()
        fresh_start = not retry_chunk_items and not (
            isinstance(self.foreshadow_review_comparison_state, dict)
            and str(self.foreshadow_review_comparison_state.get("status", "") or "") in {"pending", "failed"}
        )
        if fresh_start:
            self.foreshadow_review_observations = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
            self.foreshadow_review_comparison_state = {}
            self.failed_foreshadow_review_chunks = []
            self.foreshadow_review_postprocess_pending = False
        self._set_candidate_actions_enabled(False)
        self._set_foreshadow_actions_enabled(False)
        self.foreshadow_review_worker = NovelForeshadowReviewWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            "",
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
            concurrency,
            chunks=review_chunks,
        )
        self._connect_novel_worker_status(self.foreshadow_review_worker)
        self.foreshadow_review_worker.result_ready.connect(self.on_foreshadow_review_ready)
        self.foreshadow_review_worker.partial_ready.connect(self.on_foreshadow_review_partial)
        self.foreshadow_review_worker.failed.connect(self.on_foreshadow_review_failed)
        self.foreshadow_review_worker.finished.connect(self._cleanup_foreshadow_review_worker)
        if retry_chunk_items:
            self.set_status_tip(f"正在重试 AI 伏笔体检失败章节：共 {len(retry_chunk_items)} 章，并发 {concurrency}...")
        else:
            self.set_status_tip(f"正在按章提取 AI 伏笔观察：共 {len(review_chunks)} 章，并发 {concurrency}...")
        self.foreshadow_review_worker.start()

    def delete_chapter(self):
        self._delete_indexed_item("chapters", self.current_chapter_index, "章节", "title", self._reload_chapter_list)

    def choose_chapter_export_mode(self):
        options = [
            "按现有章节导出（不调用AI）",
            "按字数拆分导出（本地快速取名）",
        ]
        selected, ok = QInputDialog.getItem(
            self,
            "按章节导出/拆分导出",
            "请选择导出方式：",
            options,
            0,
            False,
        )
        if not ok:
            return
        if selected == options[0]:
            self.export_existing_chapters_docx()
        elif selected == options[1]:
            self.split_current_chapter()

    def _fanqie_upload_worker_for_path(self, path):
        target = self._canonical_project_path(path)
        workers = getattr(self, "_fanqie_upload_workers", {})
        if not target or not isinstance(workers, dict):
            return None
        worker = workers.get(target)
        if worker is not None and worker.isRunning():
            return worker
        return None

    def _current_fanqie_upload_worker(self):
        return self._fanqie_upload_worker_for_path(
            getattr(self, "current_project_path", "")
        )

    def open_fanqie_batch_upload(self):
        if getattr(self, "_is_detached_auto_runner", False):
            return
        active_upload = self._current_fanqie_upload_worker()
        if active_upload is not None:
            ret = QMessageBox.question(
                self,
                "中止番茄批量上传",
                "当前项目的番茄批量上传正在运行，是否中止并保存当前断点？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ret == QMessageBox.Yes:
                active_upload.stop()
                active_upload.requestInterruption()
                self.set_status_tip("正在中止番茄批量上传，并保存当前断点...")
            return
        if self._current_background_chapter_runner() is not None:
            QMessageBox.information(
                self,
                "番茄批量上传",
                "当前项目正在后台扩写章节，请等扩写完成后再启动番茄批量上传。",
            )
            return
        self._flush_current_editors()
        if not self._has_saved_project_path():
            if not self.save_current_project():
                return
        current_path = self._canonical_project_path(self.current_project_path)
        if self._fanqie_upload_worker_for_path(current_path) is not None:
            self.set_status_tip("当前项目已经有番茄批量上传任务在运行。")
            return
        dialog = FanqieBatchUploadDialog(
            current_project_path=self.current_project_path,
            parent=self,
        )
        self._fanqie_upload_dialog = dialog
        try:
            if dialog.exec() != QDialog.Accepted:
                return
            config = dialog.config()
        finally:
            self._fanqie_upload_dialog = None
            dialog.deleteLater()
        if not config:
            return
        self._start_fanqie_upload(config)

    def _start_fanqie_upload(self, config):
        config = config if isinstance(config, dict) else {}
        path = self._canonical_project_path(config.get("project_path", ""))
        if not path:
            QMessageBox.warning(self, "番茄批量上传", "没有选择有效的本地小说项目。")
            return
        if self._fanqie_upload_worker_for_path(path) is not None:
            self.set_status_tip("这个项目已经有番茄批量上传任务在运行。")
            return
        if self._active_background_chapter_runner_for_path(path) is not None:
            QMessageBox.information(
                self,
                "番茄批量上传",
                "所选项目正在后台扩写章节，请等扩写完成后再启动番茄批量上传。",
            )
            return
        try:
            project = load_json_file(path, {})
            task = build_fanqie_upload_task(path, config, project=project)
        except Exception as exc:
            QMessageBox.warning(self, "番茄批量上传", clean_error_text(exc))
            return
        worker = FanqieBatchUploadWorker(task, self)
        workers = getattr(self, "_fanqie_upload_workers", {})
        if not isinstance(workers, dict):
            workers = {}
            self._fanqie_upload_workers = workers
        workers[path] = worker
        worker.progress.connect(
            lambda text, project_path=path: self._on_fanqie_upload_progress(project_path, text)
        )
        worker.state_changed.connect(
            lambda state, project_path=path: self._on_fanqie_upload_state_changed(project_path, state)
        )
        worker.chapter_succeeded.connect(
            lambda item, project_path=path: self._on_fanqie_upload_chapter_succeeded(project_path, item)
        )
        worker.completed.connect(
            lambda state, project_path=path: self._on_fanqie_upload_completed(project_path, state)
        )
        worker.failed.connect(
            lambda message, project_path=path: self._on_fanqie_upload_failed(project_path, message)
        )
        worker.finished.connect(
            lambda project_path=path, task_worker=worker: self._cleanup_fanqie_upload_worker(
                project_path, task_worker
            )
        )
        if self._canonical_project_path(self.current_project_path) == path:
            self._fanqie_upload_locked_path = path
            self._set_detached_auto_source_read_only(True)
            if hasattr(self, "fanqie_upload_btn"):
                self.fanqie_upload_btn.setText("中止番茄上传")
        title = str(config.get("platform_work_title", "") or "番茄目标作品").strip()
        mode_label = {
            "draft": "保存草稿",
            "direct_publish": "直接发布",
            "scheduled_publish": "定时发布",
        }.get(str(config.get("mode", "draft") or "draft"), "上传")
        self.set_status_tip(f"已启动番茄批量上传：{title}，后台按顺序{mode_label}。")
        worker.start()

    def _on_fanqie_upload_progress(self, project_path, message):
        if self._canonical_project_path(self.current_project_path) != self._canonical_project_path(project_path):
            return
        self.set_status_tip(f"番茄批量上传：{str(message or '').strip()}")

    def _on_fanqie_upload_state_changed(self, project_path, state):
        if self._canonical_project_path(self.current_project_path) != self._canonical_project_path(project_path):
            return
        if isinstance(state, dict):
            account_id = str(state.get("account_id", "") or "").strip() or FANQIE_LEGACY_ACCOUNT_ID
            states = self.current_project.setdefault("fanqie_upload_accounts", {})
            if not isinstance(states, dict):
                states = {}
                self.current_project["fanqie_upload_accounts"] = states
            states[account_id] = deepcopy(state)
            if account_id == FANQIE_LEGACY_ACCOUNT_ID:
                self.current_project["fanqie_upload"] = deepcopy(state)

    def _on_fanqie_upload_chapter_succeeded(self, project_path, item):
        if self._canonical_project_path(self.current_project_path) != self._canonical_project_path(project_path):
            return
        number = item.get("chapter_number", "") if isinstance(item, dict) else ""
        mode = item.get("mode", "draft") if isinstance(item, dict) else "draft"
        action = {
            "draft": "草稿已保存",
            "direct_publish": "已直接发布",
            "scheduled_publish": "已设置定时发布",
        }.get(mode, "已完成")
        publish_time = item.get("publish_time", "") if isinstance(item, dict) else ""
        suffix = f"（{publish_time}）" if publish_time and mode == "scheduled_publish" else ""
        self.set_status_tip(f"番茄批量上传：第{number}章{action}{suffix}。")

    def _on_fanqie_upload_completed(self, project_path, state):
        status = str(state.get("status", "") or "") if isinstance(state, dict) else ""
        if self._canonical_project_path(self.current_project_path) != self._canonical_project_path(project_path):
            return
        if status == "completed":
            mode = str(state.get("mode", "draft") or "draft") if isinstance(state, dict) else "draft"
            action = {
                "draft": "保存为草稿",
                "direct_publish": "直接发布",
                "scheduled_publish": "设置定时发布",
            }.get(mode, "上传")
            self.set_status_tip(f"番茄批量上传完成，所有选定章节已{action}。")
        elif status == "paused":
            self.set_status_tip("番茄批量上传已暂停：请完成登录后重新启动并继续断点。")
        elif status == "stopped":
            self.set_status_tip("番茄批量上传已中止，已保存当前断点。")
        elif status == "failed" and isinstance(state, dict):
            if state.get("error_kind") == "daily_limit":
                self.set_status_tip(
                    "番茄批量上传已停止：平台返回每日更新字数上限，当前章节未记为成功。"
                )
            elif state.get("error_kind") == "publish_rejected":
                self.set_status_tip(
                    "番茄批量上传已停止：平台拒绝了本章发布，当前章节未记为成功。"
                )

    def _on_fanqie_upload_failed(self, project_path, message):
        if self._canonical_project_path(self.current_project_path) == self._canonical_project_path(project_path):
            state = self.current_project.get("fanqie_upload", {}) if isinstance(self.current_project, dict) else {}
            states = self.current_project.get("fanqie_upload_accounts", {}) if isinstance(self.current_project, dict) else {}
            if isinstance(states, dict) and states:
                state = max(
                    (item for item in states.values() if isinstance(item, dict)),
                    key=lambda item: str(item.get("updated_at", "") or ""),
                    default=state,
                )
            if isinstance(state, dict) and state.get("error_kind") == "daily_limit":
                self.set_status_tip(
                    "番茄批量上传已停止：番茄后台提示每日更新字数上限；"
                    f"当前章节未记为成功。{clean_error_text(message)}"
                )
            elif isinstance(state, dict) and state.get("error_kind") == "publish_rejected":
                self.set_status_tip(
                    "番茄批量上传已停止：平台拒绝了当前章节发布；"
                    f"当前章节未记为成功。{clean_error_text(message)}"
                )
            else:
                self.set_status_tip(f"番茄批量上传失败：{clean_error_text(message)}")

    def _cleanup_fanqie_upload_worker(self, project_path, worker):
        workers = getattr(self, "_fanqie_upload_workers", {})
        target = self._canonical_project_path(project_path)
        if isinstance(workers, dict) and workers.get(target) is worker:
            workers.pop(target, None)
        if self._fanqie_upload_locked_path == target:
            self._set_detached_auto_source_read_only(False)
            self._fanqie_upload_locked_path = ""
            if hasattr(self, "fanqie_upload_btn"):
                self.fanqie_upload_btn.setText("番茄批量上传")
        try:
            worker.deleteLater()
        except RuntimeError:
            pass
        self._notify_project_store_changed()

    def stop_fanqie_upload_workers(self):
        stop_fanqie_manual_browser_workers()
        workers = getattr(self, "_fanqie_upload_workers", {})
        if not isinstance(workers, dict):
            return
        for worker in list(workers.values()):
            try:
                worker.stop()
                worker.requestInterruption()
            except Exception as exc:
                log_debug("退出时停止番茄批量上传失败", exc)

    def export_existing_chapters_docx(self):
        try:
            self._flush_current_editors()
            chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
            export_chapters = []
            for index, chapter in enumerate(chapters, 1):
                if not isinstance(chapter, dict) or not str(chapter.get("text", "") or "").strip():
                    continue
                export_chapter = deepcopy(chapter)
                export_chapter["title"] = _numbered_export_chapter_title(index, chapter.get("title", ""))
                export_chapters.append(export_chapter)
            if not export_chapters:
                QMessageBox.information(self, "导出提示", "当前没有可导出的章节正文。")
                return
            title = self._project_title()
            path = self._get_export_path(
                "按现有章节导出 Word",
                f"{title}_按章节导出",
                "docx",
                "Word 文档 (*.docx)",
            )
            if not path:
                return
            _write_docx_text(path, title, export_chapters, center_chapter_headings=True)
            self.set_status_tip(
                f"已按现有章节和章节名导出 {len(export_chapters)} 章：{os.path.basename(path)}"
            )
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def split_current_chapter(self):
        if self.chapter_title_worker is not None and self.chapter_title_worker.isRunning():
            self.set_status_tip("拆分导出正在处理中，请稍等。")
            return
        self._save_chapter_from_editor()
        chapters = self.current_project.get("chapters", [])
        chapters = chapters if isinstance(chapters, list) else []
        body_chapters = [chap for chap in chapters if isinstance(chap, dict) and str(chap.get("text", "") or "").strip()]
        body_words = sum(_body_display_len(chap.get("text", "")) for chap in body_chapters)
        if body_words <= 0:
            QMessageBox.information(self, "拆分提示", "当前没有可导出的章节正文。")
            return
        average_words = body_words // max(1, len(body_chapters))
        default_words = max(100, min(3000, average_words or 2000))
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
        self._pending_split_export = {
            "title": title,
            "target_words": target_words,
            "chapters": deepcopy(split_chapters),
        }
        titles = [
            _local_split_chapter_title(chapter.get("text", ""))
            for chapter in split_chapters
        ]
        self.set_status_tip(f"正在本地快速生成 {len(split_chapters)} 个拆分章节名...")
        self.on_split_chapter_titles_ready(titles)

    def on_split_chapter_titles_ready(self, titles):
        pending = getattr(self, "_pending_split_export", {}) or {}
        split_chapters = deepcopy(pending.get("chapters", []))
        title = str(pending.get("title", "") or self._project_title()).strip() or "未命名小说"
        target_words = int(pending.get("target_words", 0) or 0)
        titles = [str(item or "").strip() for item in (titles or [])]
        if not split_chapters or len(titles) != len(split_chapters):
            err = f"标题数量不一致：需要 {len(split_chapters)} 个，实际 {len(titles)} 个。"
            self.on_split_chapter_titles_failed(err)
            return
        for index, chap in enumerate(split_chapters, 1):
            chap["title"] = f"第 {index} 章 {titles[index - 1]}"
        path = self._get_export_path("导出拆分 Word", f"{title}_按{target_words}字拆分", "docx", "Word 文档 (*.docx)")
        if not path:
            self._pending_split_export = {}
            self.set_status_tip("已生成拆分章节标题，已取消导出。")
            return
        try:
            _write_docx_text(path, title, split_chapters, center_chapter_headings=True)
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))
            self._pending_split_export = {}
            self.set_status_tip(f"拆分章节标题已生成，但导出失败：{clean_error_text(e)[:80]}")
            return
        self._pending_split_export = {}
        self.set_status_tip(f"已生成章节标题，并按约{target_words}字拆分为 {len(split_chapters)} 章导出 Word：{os.path.basename(path)}")

    def on_split_chapter_titles_failed(self, err):
        err_text = clean_error_text(err)
        self.set_status_tip(f"章节标题生成失败，已停止拆分导出：{err_text[:80]}")
        QMessageBox.warning(
            self,
            "章节标题生成失败",
            f"章节标题生成失败，请重试。\n\n失败原因：{err_text}",
        )
        self._pending_split_export = {}

    def _cleanup_chapter_title_worker(self):
        worker = self.sender()
        def cleanup():
            try:
                if self.chapter_title_worker is worker:
                    self.chapter_title_worker = None
                if worker is not None:
                    worker.deleteLater()
            except Exception as e:
                log_debug("拆分章节标题线程清理失败", e)
        QTimer.singleShot(0, cleanup)

    def _reconcile_creation_wizard_meta(self):
        """补齐向导选择在主程序顶部的可读摘要，不改动结构化原稿。"""
        project = self.current_project if isinstance(self.current_project, dict) else {}
        framework = project.get("creation_framework", {})
        if not isinstance(framework, dict):
            return False
        premise = framework.get("premise", {})
        if not isinstance(premise, dict) or not premise:
            return False
        state = project.get("creation_wizard_state", {})
        source = str(framework.get("source", "") or "").strip()
        state_status = (
            str(state.get("status", "") or "").strip().lower()
            if isinstance(state, dict) else ""
        )
        if source != "creation_wizard" and state_status not in {"complete", "confirmed"}:
            return False
        meta = project.setdefault("meta", {})
        display = creation_meta_display_values(
            premise,
            existing_genre=meta.get("genre", ""),
            existing_style=meta.get("style", ""),
        )
        changed = False
        for key in ("genre", "style"):
            value = str(display.get(key, "") or "").strip()
            if value and value != str(meta.get(key, "") or "").strip():
                meta[key] = value
                changed = True
        bible = framework.get("bible", {})
        core_motive = (
            str(framework.get("core_motive", "") or "").strip()
            or str(bible.get("main_conflict", "") or "").strip()
            if isinstance(bible, dict)
            else str(framework.get("core_motive", "") or "").strip()
        )
        if core_motive:
            migrated_bible = migrate_creation_bible_display_text(
                project.get("bible", ""),
                has_core_motive=True,
            )
            if migrated_bible != str(project.get("bible", "") or ""):
                project["bible"] = migrated_bible
                changed = True
        return changed

    def _schedule_chapter_task_callback(self, delay_ms, callback):
        # Timers follow the project owner when a foreground task moves to a runner.
        owner = getattr(self, "_chapter_task_timer_owner", None)
        if owner is None:
            owner = {"tab": self, "pending": 0}
            self._chapter_task_timer_owner = owner
        owner["pending"] = int(owner.get("pending", 0) or 0) + 1

        def dispatch():
            owner["pending"] -= 1
            callback(owner["tab"])

        QTimer.singleShot(delay_ms, dispatch)

    def _chapter_task_signal_worker(self):
        worker = getattr(self, "_chapter_task_callback_worker", None)
        if worker is not None:
            return worker
        try:
            return self.sender()
        except RuntimeError:
            return None

    def _forward_chapter_task_signal(self, method, *args):
        worker = self._chapter_task_signal_worker()
        target = getattr(worker, "_chapter_task_owner_tab", self)
        if target is self:
            return False
        previous = getattr(target, "_chapter_task_callback_worker", None)
        target._chapter_task_callback_worker = worker
        try:
            getattr(target, method)(*args)
        finally:
            target._chapter_task_callback_worker = previous
        return True

    def _copy_chapter_task_state(self, target):
        """Move chapter workflow state to a hidden runner for one project."""
        if target is None:
            return
        names = (
            name for name in vars(self)
            if (name.startswith("_chapter_ai_") and name != "_chapter_ai_buttons_by_action")
            or name.startswith("_auto_expand_all_")
            or name.startswith("_auto_expand_restart_")
            or name.startswith("_auto_chapter_")
            or name.startswith("_chapter_plan_")
        )
        for name in names:
            try:
                setattr(target, name, deepcopy(getattr(self, name)))
            except Exception:
                setattr(target, name, getattr(self, name))
        target._context_build_token = int(getattr(self, "_context_build_token", 0) or 0)
        target._context_build_pending = deepcopy(
            getattr(self, "_context_build_pending", {}) or {}
        )
        for name in (
            "_status_project_path",
            "_status_message",
            "_status_stage_key",
            "_status_stage_label",
            "_status_stage_started_at",
            "_status_stage_started_wall",
            "_status_stage_scope_label",
            "_status_stage_active",
            "_status_history",
            "_status_workflow_active",
            "_status_workflow_kind",
            "_status_workflow_started_at",
            "_status_workflow_started_wall",
            "_status_last_run_elapsed",
            "_status_received_chars",
        ):
            value = getattr(self, name, None)
            setattr(target, name, deepcopy(value) if name == "_status_history" else value)
        def copy_index(name, default=-1):
            value = getattr(self, name, default)
            try:
                return int(default if value is None else value)
            except (TypeError, ValueError):
                return default

        target.current_chapter_index = copy_index("current_chapter_index")
        target.current_character_index = copy_index("current_character_index")
        target.current_lore_index = copy_index("current_lore_index")
        target.current_foreshadow_index = copy_index("current_foreshadow_index")
        target._draft_saved_once = True

    def _move_chapter_task_workers_to(self, target):
        for name in ("writing_worker", "context_build_worker", "chapter_plan_worker"):
            worker = getattr(self, name, None)
            setattr(target, name, worker)
            if worker is not None:
                worker._chapter_task_owner_tab = target
            setattr(self, name, None)
        target.writing_retired_workers = list(
            getattr(self, "writing_retired_workers", []) or []
        )
        for worker in target.writing_retired_workers:
            worker._chapter_task_owner_tab = target
        self.writing_retired_workers = []
        owner = getattr(self, "_chapter_task_timer_owner", None)
        if owner is not None:
            owner["tab"] = target
            target._chapter_task_timer_owner = owner
            self._chapter_task_timer_owner = None

    def _connect_chapter_task_worker(self, worker, result_method, cleanup_method):
        router = _ChapterTaskSignalRouter(worker, self, result_method, cleanup_method)
        worker._chapter_task_signal_router = router
        worker.result_ready.connect(router.on_result)
        worker.failed.connect(router.on_failure)
        worker.finished.connect(router.on_finished)
        if hasattr(worker, "chunk"):
            worker.chunk.connect(router.on_chunk)
        if hasattr(worker, "progress"):
            worker.progress.connect(router.on_progress)
        output_signal = getattr(worker, "output_chars", None)
        if output_signal is not None:
            output_signal.connect(router.on_output_chars)

    def _detach_foreground_chapter_tasks(self, reason=""):
        """Keep a named project's active chapter task alive across project switches."""
        if getattr(self, "_is_detached_auto_runner", False):
            return False
        source_path = self._canonical_project_path(getattr(self, "current_project_path", ""))
        if not source_path or source_path == self._canonical_project_path(NOVEL_DRAFT_FILE):
            return False
        writing_worker = getattr(self, "writing_worker", None)
        context_worker = getattr(self, "context_build_worker", None)
        chapter_plan_worker = getattr(self, "chapter_plan_worker", None)
        retry_pending = bool(getattr(self, "_chapter_ai_transient_retry_pending", False))
        plan_continuation_pending = bool(getattr(self, "_chapter_plan_continue_pending", False))
        active = bool(
            writing_worker is not None
            or context_worker is not None
            or chapter_plan_worker is not None
            or getattr(self, "writing_retired_workers", [])
            or getattr(self, "_chapter_ai_sequence_active", False)
            or retry_pending
            or getattr(self, "_auto_expand_all_active", False)
            or getattr(self, "_auto_expand_all_waiting_next", False)
            or getattr(self, "_chapter_plan_auto_active", False)
            or plan_continuation_pending
            or (getattr(self, "_chapter_task_timer_owner", None) or {}).get("pending", 0)
        )
        if not active:
            return False
        existing = (getattr(self, "_background_chapter_ai_runners", {}) or {}).get(source_path)
        if existing is not None:
            return False
        try:
            self._flush_current_editors()
            runner = NovelWritingTab(deepcopy(self.config), None, background_runner=True)
            runner._background_task_kind = "chapter_ai"
            runner._save_draft_snapshot = lambda: None
            runner._notify_project_store_changed = lambda: None
            runner._load_project_data(
                deepcopy(self.current_project), source_path, defer_helpers=True
            )
            runner.current_chapter_index = self.current_chapter_index
            runner._reload_chapter_list(self.current_chapter_index)
            self._copy_chapter_task_state(runner)
            # Other record editors must match their selected indexes before a save.
            runner._load_character_to_editor(runner.current_character_index)
            runner._load_lore_to_editor(runner.current_lore_index)
            runner._load_foreshadow_to_editor(runner.current_foreshadow_index)
            runner.chapter_ai_stream_text = self.chapter_ai_stream_text
            runner.chapter_ai_preview.setPlainText(self.chapter_ai_preview.toPlainText())
            runner._pending_chapter_plan = deepcopy(
                getattr(self, "_pending_chapter_plan", {}) or {}
            )
            self._move_chapter_task_workers_to(runner)
            runner.hide()
            runners = getattr(self, "_background_chapter_ai_runners", None)
            if not isinstance(runners, dict):
                runners = {}
                self._background_chapter_ai_runners = runners
            runners[source_path] = runner
            self._context_build_pending = {}
            self._chapter_ai_memory_pending = {}
            self._chapter_ai_sequence_active = False
            self._chapter_ai_transient_retry_pending = False
            self._chapter_ai_transient_retry_token = int(
                getattr(self, "_chapter_ai_transient_retry_token", 0) or 0
            ) + 1
            self._chapter_ai_active_task = {}
            self._chapter_ai_running_action = ""
            self._chapter_plan_continue_pending = False
            self._chapter_plan_sequence_token = int(
                getattr(self, "_chapter_plan_sequence_token", 0) or 0
            ) + 1
            self._auto_expand_all_active = False
            self._auto_expand_all_waiting_next = False
            self._reset_chapter_ai_style_retry()
            self._log_novel_diagnostic(
                "chapter_ai_task_detached_for_project_switch",
                level="info",
                project_path=source_path,
                reason=str(reason or "")[:500],
                chapter_id=str(getattr(writing_worker, "diagnostic_chapter_id", "") or ""),
                request_id=str(getattr(writing_worker, "diagnostic_request_id", "") or ""),
            )
            return True
        except Exception as exc:
            self._log_novel_diagnostic(
                "chapter_ai_task_detach_failed",
                level="error",
                project_path=source_path,
                error_category="lifecycle",
                **self._novel_exception_details(exc),
            )
            return False

    def _background_chapter_runner_for_path(self, path):
        source_path = self._canonical_project_path(path)
        if not source_path:
            return None
        runners = getattr(self, "_background_chapter_ai_runners", {})
        if not isinstance(runners, dict):
            return None
        return runners.get(source_path)

    def _active_background_chapter_runner_for_path(self, path):
        runner = self._background_chapter_runner_for_path(path)
        if runner is None:
            return None
        try:
            return runner if runner._status_has_active_work() else None
        except Exception:
            return runner

    def _attach_background_chapter_runner(self, path):
        """Restore a project's hidden chapter worker into the visible tab."""
        if getattr(self, "_is_detached_auto_runner", False):
            return False
        source_path = self._canonical_project_path(path)
        runner = self._background_chapter_runner_for_path(source_path)
        if runner is None:
            return False
        # Automatic expansion remains a hidden owner of the project.  Loading
        # the project should show its latest snapshot without moving the
        # worker back into the foreground tab.
        if str(getattr(runner, "_background_task_kind", "") or "") == "auto_expand":
            return False
        try:
            # The project data was loaded from the runner immediately before
            # this call. Copy the in-memory snapshot once more so a queued
            # callback that saved just before the switch is not lost.
            self.current_project = deepcopy(runner.current_project)
            self.current_project_path = source_path
            runners = getattr(self, "_background_chapter_ai_runners", {})
            runners.pop(source_path, None)
            self._update_detached_auto_source_lock()
            runner._copy_chapter_task_state(self)
            self._reload_character_list(self.current_character_index)
            self._reload_lore_list(self.current_lore_index)
            self._reload_foreshadow_list(self.current_foreshadow_index)
            self._reload_chapter_list(self.current_chapter_index)
            self._load_character_to_editor(self.current_character_index)
            self._load_lore_to_editor(self.current_lore_index)
            self._load_foreshadow_to_editor(self.current_foreshadow_index)
            self.chapter_ai_stream_text = str(
                getattr(runner, "chapter_ai_stream_text", "") or ""
            )
            self.chapter_ai_preview.setPlainText(
                runner.chapter_ai_preview.toPlainText()
            )
            self._pending_chapter_plan = deepcopy(
                getattr(runner, "_pending_chapter_plan", {}) or {}
            )

            runner._move_chapter_task_workers_to(self)

            # The workers now belong to this tab.  Clearing the runner's
            # references lets the runner's own status poller see that it no
            # longer owns active work and prevents a later cleanup from
            # deleting a worker that has already been reattached.
            self._sync_completed_background_chapter_plan(self._pending_chapter_plan)
            self._set_chapter_ai_actions_enabled(not self._status_has_active_work())
            self._refresh_status_display()
            runner.deleteLater()
            self._log_novel_diagnostic(
                "chapter_ai_task_attached_after_project_switch",
                level="info",
                project_path=source_path,
                chapter_id=self._current_chapter_id(),
                request_id=str(
                    getattr(self, "_chapter_ai_diagnostic_request_id", "") or ""
                ),
            )
            return True
        except Exception as exc:
            self._background_chapter_ai_runners[source_path] = runner
            self._log_novel_diagnostic(
                "chapter_ai_task_attach_failed",
                level="error",
                project_path=source_path,
                error_category="lifecycle",
                **self._novel_exception_details(exc),
            )
            return False

    def _current_background_chapter_runner(self):
        if getattr(self, "_is_detached_auto_runner", False):
            return None
        source_path = self._canonical_project_path(getattr(self, "current_project_path", ""))
        runners = getattr(self, "_background_chapter_ai_runners", {})
        return runners.get(source_path) if isinstance(runners, dict) else None

    def _poll_background_chapter_ai_runners(self):
        runners = getattr(self, "_background_chapter_ai_runners", None)
        if not isinstance(runners, dict) or not runners:
            return
        for source_path, runner in list(runners.items()):
            try:
                visible = self._current_background_chapter_runner() is runner
                if visible:
                    self._sync_detached_auto_status(runner)
                if runner._status_has_active_work():
                    continue
                runner._save_current_project_snapshot_if_named()
                runners.pop(source_path, None)
                if visible:
                    data = deepcopy(runner.current_project)
                    plan = deepcopy(getattr(runner, "_pending_chapter_plan", {}) or {})
                    self._update_detached_auto_source_lock()
                    self._load_project_data(data, source_path, defer_helpers=True)
                    self._sync_completed_background_chapter_plan(plan)
                    self.set_status_tip(str(getattr(runner, "_status_message", "") or "章节任务已结束。"))
                runner.deleteLater()
                self._notify_project_store_changed()
                self._log_novel_diagnostic(
                    "chapter_ai_background_task_finished",
                    level="info",
                    project_path=source_path,
                    status=str(getattr(runner, "_status_message", "") or ""),
                )
            except Exception as exc:
                self._log_novel_diagnostic(
                    "chapter_ai_background_task_poll_failed",
                    level="error",
                    project_path=source_path,
                    error_category="lifecycle",
                    **self._novel_exception_details(exc),
                )

    def _sync_completed_background_chapter_plan(self, plan=None):
        if plan is None:
            project = getattr(self, "current_project", {})
            state = project.get("chapter_plan_generation_state", {}) if isinstance(project, dict) else {}
            plan = self._chapter_plan_from_generation_state(state) if state.get("status") == "complete" else {}
        if not isinstance(plan, dict) or not plan.get("chapters"):
            return
        self._pending_chapter_plan = deepcopy(plan)
        self.chapter_ai_preview.setPlainText(self._format_chapter_plan_preview(plan))
        self.chapter_plan_apply_btn.setVisible(True)
        self.chapter_plan_apply_btn.setEnabled(True)

    def stop_background_chapter_ai_runners(self):
        self.stop_fanqie_upload_workers()
        runners = getattr(self, "_background_chapter_ai_runners", {})
        if not isinstance(runners, dict):
            return
        for runner in list(runners.values()):
            try:
                runner.stop_chapter_ai_action()
                runner._save_current_project_snapshot_if_named()
            except Exception as exc:
                log_debug("退出时停止后台章节任务失败", exc)
        runners.clear()

    def _load_project_data(self, data, path="", defer_helpers=False):
        if getattr(self, "_fanqie_upload_locked_path", ""):
            self._set_detached_auto_source_read_only(False)
            self._fanqie_upload_locked_path = ""
        previous_project_path = self._canonical_project_path(
            getattr(self, "current_project_path", "")
        )
        detached_task = self._detach_foreground_chapter_tasks(
            "加载新项目数据，旧项目章节任务转入后台"
        )
        self._invalidate_chapter_plan_generation(
            "加载项目数据，旧章节规划预览和回调已失效",
            clear_project_state=False,
        )
        if not getattr(self, "_is_detached_auto_runner", False) and not detached_task:
            foreground_worker = getattr(self, "writing_worker", None)
            has_foreground_task = bool(
                foreground_worker is not None
                or getattr(self, "_chapter_ai_memory_pending", {})
                or getattr(self, "_chapter_ai_sequence_active", False)
                or getattr(self, "_chapter_ai_transient_retry_pending", False)
            )
            if has_foreground_task:
                self._invalidate_foreground_chapter_ai_task(
                    "加载新项目数据，旧前台章节任务已失效"
                )
        perf_start = time.perf_counter()
        source_name = os.path.basename(str(path or "")) or "草稿"
        file_size = ""
        if path and os.path.exists(path):
            try:
                file_size = os.path.getsize(path)
            except Exception:
                file_size = ""
        self._loading = True
        try:
            step_start = time.perf_counter()
            self.current_project = _normalize_project(data)
            self._log_novel_perf(
                "加载项目-规范化",
                step_start,
                threshold_ms=80,
                path=source_name,
                file_size=file_size,
            )
            step_start = time.perf_counter()
            status_changes = _auto_classify_default_statuses(self.current_project)
            self._log_novel_perf(
                "加载项目-自动分类",
                step_start,
                threshold_ms=80,
                path=source_name,
            )
            step_start = time.perf_counter()
            framework_reconciled = self._reconcile_imported_framework_source()
            self._log_novel_perf(
                "加载项目-框架结构自愈",
                step_start,
                threshold_ms=80,
                path=source_name,
            )
            creation_meta_reconciled = self._reconcile_creation_wizard_meta()
            self.current_project_path = path
            loaded_project_path = self._canonical_project_path(path)
            if self._fanqie_upload_worker_for_path(loaded_project_path) is not None:
                self._fanqie_upload_locked_path = loaded_project_path
                self._set_detached_auto_source_read_only(True)
                if hasattr(self, "fanqie_upload_btn"):
                    self.fanqie_upload_btn.setText("中止番茄上传")
            if previous_project_path and loaded_project_path and previous_project_path != loaded_project_path:
                self._reset_status_for_project_switch(loaded_project_path)
            elif loaded_project_path and not str(getattr(self, "_status_project_path", "") or "").strip():
                self._status_project_path = loaded_project_path
            self._record_current_project_file_signature(path)
            analysis_state = _normalize_candidate_analysis_state(self.current_project.get("analysis_state", {}))
            self.failed_analysis_chunks = analysis_state.get("failed_candidate_chunks", [])
            self.pending_analysis_chapter_ids = analysis_state.get("pending_candidate_chapter_ids", [])
            self.candidate_postprocess_state = analysis_state.get("candidate_postprocess", {})
            foreshadow_review_state = analysis_state.get("foreshadow_review", {}) if isinstance(analysis_state, dict) else {}
            self.foreshadow_review_observations = foreshadow_review_state.get(
                "observations",
                {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}},
            ) if isinstance(foreshadow_review_state, dict) else {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
            self.failed_foreshadow_review_chunks = foreshadow_review_state.get("failed_observation_chunks", []) if isinstance(foreshadow_review_state, dict) else []
            self.foreshadow_review_comparison_state = foreshadow_review_state.get("comparison", {}) if isinstance(foreshadow_review_state, dict) else {}
            self.foreshadow_review_postprocess_pending = str(self.foreshadow_review_comparison_state.get("status", "") or "") in {"pending", "failed"}
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
            self._refresh_style_profile_combo()
            self.draft_note_edit.setPlainText(self.current_project.get("draft_note", ""))
            step_start = time.perf_counter()
            self._reload_character_list()
            self._reload_lore_list()
            self._reload_foreshadow_list()
            self._reload_chapter_list()
            self._log_novel_perf(
                "加载项目-刷新结构列表",
                step_start,
                threshold_ms=80,
                path=source_name,
                **self._novel_perf_summary(),
            )
            project_status_changed = self._auto_update_project_status()
            self._dirty = (
                any(status_changes.values())
                or bool(framework_reconciled)
                or bool(creation_meta_reconciled)
                or project_status_changed
            )
            self._project_file_dirty = self._dirty
        finally:
            self._loading = False
        self.refresh_project_summary_label()
        self._update_detached_auto_source_lock()
        self._update_stats_label()
        self._refresh_framework_import_retry_action()
        if defer_helpers:
            self._mark_helper_pages_stale()
            self._show_deferred_helper_page_notice()
        else:
            self.refresh_manuscript()
            self.refresh_writing_check()
            self.refresh_import_candidate_lists()
        self._log_novel_perf(
            "加载项目-总计",
            perf_start,
            threshold_ms=0,
            path=source_name,
            defer_helpers=defer_helpers,
            file_size=file_size,
            **self._novel_perf_summary(),
        )

    def refresh_manuscript(self):
        if not hasattr(self, "manuscript_edit") or self._loading or self._refreshing_helpers:
            return
        perf_start = time.perf_counter()
        try:
            self._refreshing_helpers = True
            self._flush_current_editors()
            text = _build_manuscript_text(self.current_project)
            self._set_text_without_signals(self.manuscript_edit, text)
            self._refresh_read_aloud_scope_combo()
            self._manuscript_stale = False
            self._log_novel_perf(
                "刷新完整书稿",
                perf_start,
                threshold_ms=80,
                text_len=len(text),
                **self._novel_perf_summary(),
            )
        except Exception as e:
            self._log_novel_perf("刷新完整书稿失败", perf_start, threshold_ms=0)
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
            self._set_text_without_signals(self.manuscript_edit, text)
            self._manuscript_stale = False
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
        self._set_text_without_signals(self.manuscript_edit, text)
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
        self.read_aloud_worker.progress.connect(self._on_read_aloud_progress)
        self.read_aloud_worker.result_ready.connect(self._on_read_aloud_segment_ready)
        self.read_aloud_worker.failed.connect(self._on_read_aloud_error)
        self.read_aloud_worker.finished.connect(self._cleanup_read_aloud_worker)
        self.set_status_tip(f"正在生成第 {index + 1}/{len(self.read_aloud_segments)} 段语音...")
        self.read_aloud_worker.start()

    def _on_read_aloud_progress(self, message):
        worker = self.sender()
        if worker is not None and self.read_aloud_worker is not worker:
            return
        self.set_status_tip(message)

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
        if self.read_aloud_worker is None and self.read_aloud_pending_segment:
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
            if hasattr(worker, "stop"):
                worker.stop()
            else:
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
        perf_start = time.perf_counter()
        try:
            self._refreshing_helpers = True
            self._flush_current_editors()
            text = _build_writing_check_text(self.current_project)
            self._set_text_without_signals(self.check_edit, text)
            self._writing_check_stale = False
            self._log_novel_perf(
                "刷新写作检查",
                perf_start,
                threshold_ms=80,
                text_len=len(text),
                **self._novel_perf_summary(),
            )
        except Exception as e:
            self._log_novel_perf("刷新写作检查失败", perf_start, threshold_ms=0)
            log_debug("小说写作检查刷新失败", e)
        finally:
            self._refreshing_helpers = False

    def run_global_search(self):
        if not hasattr(self, "search_result_edit"):
            return
        perf_start = time.perf_counter()
        keyword = self.search_input.text().strip()
        self._flush_current_editors()
        self._sync_import_candidates_to_project()
        text = _build_search_result_text(self.current_project, keyword)
        self.search_result_edit.setPlainText(text)
        self._log_novel_perf(
            "全局搜索",
            perf_start,
            threshold_ms=80,
            keyword=keyword,
            result_len=len(text),
            **self._novel_perf_summary(),
        )

    def clear_global_search(self):
        if hasattr(self, "search_input"):
            self.search_input.clear()
        if hasattr(self, "search_result_edit"):
            self.search_result_edit.clear()

    def refresh_import_candidate_lists(self):
        if not hasattr(self, "candidate_character_list"):
            return
        perf_start = time.perf_counter()
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
            observation_draft_count = sum(
                1
                for item in self.import_candidates.get("foreshadows", [])
                if self._is_foreshadow_observation_draft(item)
            )
            failed_count = len(getattr(self, "failed_analysis_chunks", []) or [])
            pending_count = len(getattr(self, "pending_analysis_chapter_ids", []) or [])
            failed_summary = self._failed_candidate_error_summary()
            post_status = self._candidate_postprocess_status()
            post_error = self._candidate_postprocess_error()
            if total:
                material_text = "/".join(material_labels) if material_labels else "0"
                text = f"候选：人物 {counts['characters']} · 设定 {counts['lore']} · 伏笔 {counts['foreshadows']} · 资料草案 {material_text}"
                if observation_draft_count:
                    text += f" · 观察草稿 {observation_draft_count}"
                if failed_count:
                    text += f" · 待重试 {failed_count} 块"
                elif post_status == "pending":
                    text += " · 候选合并待继续"
                elif post_status == "failed":
                    text += " · 候选合并失败，可重试"
                if pending_count:
                    text += f" · 待分析 {pending_count} 章"
                self.candidate_count_label.setText(text)
            elif failed_count:
                self.candidate_count_label.setText(f"暂无候选；还有 {failed_count} 个失败文本块待重试。悬停查看原因。")
            elif pending_count:
                self.candidate_count_label.setText(f"暂无候选；有 {pending_count} 个章节等待 AI 分析。")
            else:
                self.candidate_count_label.setText("暂无候选；可先导入 Word/TXT，或使用 AI 分析候选。")
            tooltip_parts = []
            if failed_summary:
                tooltip_parts.append(failed_summary)
            if post_error:
                tooltip_parts.append(f"候选合并/查重：{post_error}")
            self.candidate_count_label.setToolTip("\n".join(tooltip_parts))
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
                    row_text = name
                    if kind == "foreshadows" and self._is_foreshadow_observation_draft(item):
                        row_text = f"观察草稿｜{name}"
                    row = QListWidgetItem(row_text)
                    row_key = self._candidate_item_check_key(kind, item, source_index)
                    default_state = self._default_candidate_check_state(kind, item)
                    row.setCheckState(previous_checks.get(row_key, default_state))
                    row.setData(Qt.UserRole, source_index)
                    row.setData(Qt.UserRole + 1, row_key)
                    row.setToolTip(self._candidate_detail_text_with_review(kind, item))
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
        self._log_novel_perf(
            "刷新候选区",
            perf_start,
            threshold_ms=80,
            characters=counts.get("characters"),
            lore=counts.get("lore"),
            foreshadows=counts.get("foreshadows"),
            materials=material_hits,
        )

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
        if kind == "foreshadows" and self._is_foreshadow_observation_draft(item):
            source = str(item.get("_source_label", "") or item.get("source_label", "") or fallback or "").strip()
            return f"{kind}:observation:{name}:{source}"
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

    def _candidate_review_reasons(self, kind, item):
        project = self.current_project if isinstance(getattr(self, "current_project", None), dict) else {}
        return _candidate_long_term_review_reasons(project, kind, item)

    def _default_candidate_check_state(self, kind, item):
        if kind == "foreshadows" and self._is_foreshadow_observation_draft(item):
            return Qt.Unchecked
        return Qt.Checked

    def _candidate_detail_text_with_review(self, kind, item):
        detail = _candidate_detail_text(kind, item)
        reasons = self._candidate_review_reasons(kind, item)
        source = ""
        if isinstance(item, dict):
            source = str(item.get("_source_label", "") or item.get("source_label", "") or "").strip()
        header_lines = []
        if kind == "foreshadows" and self._is_foreshadow_observation_draft(item):
            header_lines.append("建议：这是逐章伏笔观察草稿，已默认不勾选；等待按章比对后会生成正式处理建议。")
            header_lines.append("用途：先让你看到每章已提取出的伏笔观察，避免按章比对失败时看不到第一步成果。")
        elif reasons:
            header_lines.append("建议：已默认勾选；导入时只做同名/别名合并和重复行清理。")
            header_lines.append("原因：" + "；".join(reasons))
        else:
            header_lines.append("建议：已默认勾选，可导入。")
        if kind == "foreshadows" and isinstance(item, dict) and item.get("_status_explicit"):
            status = str(item.get("status", "") or "").strip()
            desc = str(item.get("description", "") or "")
            if "体检建议" in desc or "判断依据" in desc or "章节依据" in desc:
                header_lines.append("伏笔体检：这是 AI 对已有伏笔的清理建议；确认后才会更新原伏笔。")
            if status in {"已回收", "无需回收", "废弃"}:
                header_lines.append(f"伏笔复核：AI 判断该伏笔应更新为“{status}”；确认后会按同名/别名合并到已有伏笔。")
            elif status == "已埋":
                header_lines.append("伏笔复核：AI 判断该伏笔本章有推进但尚未回收；确认后会补充到已有伏笔。")
        if source:
            header_lines.append(f"来源：{source}")
        return "\n".join(header_lines + (["", detail] if detail else []))

    def _candidate_material_labels(self, material_result=None):
        labels = (
            ("bible", "圣经"),
            ("world_rules", "世界规则"),
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
        self.candidate_detail_edit.setPlainText(self._candidate_detail_text_with_review(kind, items[source_index]))

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
        for btn in getattr(self, "foreshadow_action_buttons", []):
            btn.setEnabled(bool(enabled))
        if hasattr(self, "candidate_concurrency_combo"):
            self.candidate_concurrency_combo.setEnabled(bool(enabled))
        if hasattr(self, "candidate_analysis_stop_btn"):
            self.candidate_analysis_stop_btn.setVisible(not bool(enabled))
            self.candidate_analysis_stop_btn.setEnabled(not bool(enabled))

    def _set_foreshadow_actions_enabled(self, enabled):
        self._set_candidate_actions_enabled(enabled)

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

    def _prune_foreshadow_review_state_to_existing_chapters(self):
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
            self.failed_foreshadow_review_chunks = []
            self.foreshadow_review_comparison_state = {}
            return
        failed_chunks = []
        for item in getattr(self, "failed_foreshadow_review_chunks", []) or []:
            if not isinstance(item, dict):
                continue
            chapter_id = str(item.get("chapter_id", "") or "").strip()
            if chapter_id and chapter_id not in existing_ids:
                continue
            failed_chunks.append(item)
        self.failed_foreshadow_review_chunks = failed_chunks

    def _split_foreshadow_observation_records(self, observations=None, target_chars=12000):
        observations = observations if isinstance(observations, dict) else getattr(self, "foreshadow_review_observations", {})
        items = observations.get("foreshadows", []) if isinstance(observations, dict) else []

        def source_labels(item):
            labels = []
            raw = str(item.get("_source_label", "") or item.get("source_label", "") or "").strip()
            for line in raw.splitlines():
                line = str(line or "").strip()
                if line and line not in labels:
                    labels.append(line)
            if labels:
                return labels
            for key in ("setup_chapter", "payoff_chapter", "evidence"):
                value = str(item.get(key, "") or "").strip()
                if value:
                    label = value if value.startswith("章节") else f"章节：{value}"
                    return [label]
            return ["未标记章节"]

        grouped = {}
        group_order = {}
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            description = str(item.get("description", "") or "").strip()
            if not name and not description:
                continue
            base_record = {
                "name": name,
                "status": str(item.get("status", "") or "").strip(),
                "setup_chapter": str(item.get("setup_chapter", "") or "").strip(),
                "payoff_chapter": str(item.get("payoff_chapter", "") or "").strip(),
                "description": description,
                "review_action": str(item.get("review_action", "") or "").strip(),
                "merge_target": str(item.get("merge_target", "") or "").strip(),
                "review_reason": str(item.get("review_reason", "") or "").strip(),
                "evidence": str(item.get("evidence", "") or "").strip(),
            }
            for label in source_labels(item):
                record = deepcopy(base_record)
                record["_source_label"] = label
                grouped.setdefault(label, []).append(record)
                group_order.setdefault(label, (len(group_order), _story_order_from_text(label)))
        if not grouped:
            return []
        limit = max(5000, int(target_chars or 24000))
        grouped_items = sorted(
            grouped.items(),
            key=lambda pair: (group_order.get(pair[0], (0, _SORT_MISSING_ORDER))[1], group_order.get(pair[0], (0,))[0]),
        )
        chunks = []
        for label, records in grouped_items:
            current = []
            current_chars = 0
            part_index = 1
            for record in records:
                record_text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                record_chars = len(record_text)
                if current and current_chars + record_chars > limit:
                    chunks.append((label, part_index, current))
                    part_index += 1
                    current = []
                    current_chars = 0
                current.append(record)
                current_chars += record_chars
            if current:
                chunks.append((label, part_index, current))
        total = len(chunks)
        out = []
        for index, (label, part_index, group) in enumerate(chunks, 1):
            title = label if part_index <= 1 else f"{label} 第 {part_index} 批"
            out.append({
                "text": json.dumps(group, ensure_ascii=False, indent=2),
                "index": index,
                "total": total,
                "chapter_title": title,
                "review_flow": "foreshadow_review_chapter_compare",
                "source_label": label,
                "chunk_key": f"{label}#{part_index}",
            })
        return out

    def _foreshadow_review_comparison_retry_chunks(self, state=None):
        state = state if isinstance(state, dict) else getattr(self, "foreshadow_review_comparison_state", {})
        if not isinstance(state, dict):
            return []
        retry_chunks = []
        for item in state.get("failed_chunks", []) if isinstance(state.get("failed_chunks", []), list) else []:
            if not isinstance(item, dict) or not str(item.get("text", "") or "").strip():
                continue
            if str(item.get("review_flow", "") or "").strip() != "foreshadow_review_chapter_compare":
                continue
            retry_chunks.append(deepcopy(item))
        return retry_chunks

    def _sync_candidate_analysis_state(self):
        if not isinstance(self.current_project, dict):
            return
        self._prune_candidate_analysis_state_to_existing_chapters()
        self._prune_foreshadow_review_state_to_existing_chapters()
        postprocess_state = getattr(self, "candidate_postprocess_state", {}) or {}
        foreshadow_state = getattr(self, "foreshadow_review_comparison_state", {}) or {}
        if not isinstance(postprocess_state, dict):
            postprocess_state = {}
        if not isinstance(foreshadow_state, dict):
            foreshadow_state = {}
        state = _normalize_candidate_analysis_state({
            "failed_candidate_chunks": getattr(self, "failed_analysis_chunks", []) or [],
            "pending_candidate_chapter_ids": getattr(self, "pending_analysis_chapter_ids", []) or [],
            "candidate_postprocess": postprocess_state,
            "foreshadow_review": {
                "observations": getattr(self, "foreshadow_review_observations", {}) or {},
                "comparison": foreshadow_state,
                "failed_observation_chunks": getattr(self, "failed_foreshadow_review_chunks", []) or [],
            },
        })
        self.failed_analysis_chunks = state.get("failed_candidate_chunks", [])
        self.pending_analysis_chapter_ids = state.get("pending_candidate_chapter_ids", [])
        self.candidate_postprocess_state = state.get("candidate_postprocess", {})
        foreshadow_review_state = state.get("foreshadow_review", {})
        if isinstance(foreshadow_review_state, dict):
            self.foreshadow_review_observations = foreshadow_review_state.get(
                "observations",
                getattr(self, "foreshadow_review_observations", {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}),
            )
            self.foreshadow_review_comparison_state = foreshadow_review_state.get(
                "comparison",
                getattr(self, "foreshadow_review_comparison_state", {}),
            )
            self.failed_foreshadow_review_chunks = foreshadow_review_state.get(
                "failed_observation_chunks",
                getattr(self, "failed_foreshadow_review_chunks", []),
            )
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
        self.candidate_postprocess_state = {}
        self.foreshadow_review_observations = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
        self.foreshadow_review_comparison_state = {}
        self.failed_foreshadow_review_chunks = []
        self.foreshadow_review_postprocess_pending = False
        if isinstance(self.current_project, dict):
            state = self.current_project.get("analysis_state", {})
            if isinstance(state, dict):
                state.pop("failed_candidate_chunks", None)
                state.pop("pending_candidate_chapter_ids", None)
                state.pop("candidate_postprocess", None)
                state.pop("foreshadow_review", None)
                if not state:
                    self.current_project.pop("analysis_state", None)

    def _persist_candidate_analysis_state(self):
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        self._note_project_dirty()
        try:
            self.current_project["updated_at"] = now_str()
            self._save_draft_snapshot()
            self._save_current_project_snapshot_if_named()
            self._dirty = False
            self._project_file_dirty = False
        except Exception as e:
            log_debug("小说候选分析状态保存失败", e)

    def _merge_import_candidates(self, incoming):
        incoming = _normalize_ai_candidates(incoming)
        merged = deepcopy(self.import_candidates if isinstance(self.import_candidates, dict) else {})
        chapter_labels = _chapter_source_label_map(getattr(self, "current_project", {}))

        def merge_candidate_text(old, new, append=False):
            raw_old = str(old or "").strip()
            old = _strip_internal_candidate_markers(raw_old)
            new = _strip_internal_candidate_markers(new)
            if append:
                cleaned_old = _dedupe_text_lines(old)
                merged_text, did_change = _merge_text_lines_without_duplicates(cleaned_old, new)
                return merged_text, did_change or merged_text != raw_old
            if not new:
                return old, old != raw_old
            if not old:
                return new, new != raw_old
            if new == old or new in old:
                return old, False
            if old in new:
                return new, True
            return old, False

        def merge_source_labels(old, new):
            labels = []
            seen = set()
            for value in (old, new):
                for line in str(value or "").splitlines():
                    line = line.strip()
                    if not line or line in seen:
                        continue
                    seen.add(line)
                    labels.append(line)
            merged_text = "\n".join(labels)
            return merged_text, merged_text != str(old or "").strip()

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
                elif key == "foreshadows":
                    alias_keys = _foreshadow_candidate_identity_keys(item)
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
                target_code_keys = _foreshadow_candidate_target_code_keys(item) if key == "foreshadows" else set()
                target_keys = set() if target_code_keys else (_foreshadow_candidate_target_keys(item) if key == "foreshadows" else set())
                if key == "characters":
                    alias_keys.add(merge_key)
                elif key == "foreshadows":
                    alias_keys = _foreshadow_candidate_identity_keys(item)
                existing = by_name.get(merge_key)
                matched_by_target = False
                matched_by_code = False
                if existing is None:
                    for alias_key in list(target_code_keys) + list(target_keys) + [
                        value for value in alias_keys if value not in target_keys and value not in target_code_keys
                    ]:
                        existing = by_alias.get(alias_key)
                        if existing is not None:
                            matched_by_target = alias_key in target_keys
                            matched_by_code = alias_key in target_code_keys
                            break
                if existing is None:
                    clone = deepcopy(item)
                    if key == "foreshadows" and _foreshadow_candidate_is_terminal_review(clone):
                        clone["description"] = _foreshadow_terminal_review_description(clone.get("description", ""))
                    if key == "foreshadows" and item.get("_status_explicit"):
                        clone["status"] = _infer_foreshadow_status(
                            {"status": clone.get("status", "")},
                            preserve_manual=False,
                        )
                    target.append(clone)
                    by_name[merge_key] = clone
                    for alias_key in alias_keys:
                        if alias_key:
                            by_alias[alias_key] = clone
                    continue
                if key == "foreshadows" and _foreshadow_candidate_is_terminal_review(existing):
                    if _foreshadow_terminal_review_should_replace(existing, item):
                        replacement = deepcopy(item)
                        replacement["description"] = _foreshadow_terminal_review_description(replacement.get("description", ""))
                        existing.clear()
                        existing.update(replacement)
                    continue
                incoming_terminal = key == "foreshadows" and _foreshadow_candidate_is_terminal_review(item)
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
                    if not (key == "foreshadows" and (matched_by_target or matched_by_code)):
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
                    field_source_item = item
                    if key == "foreshadows" and field in {"setup_chapter", "payoff_chapter"}:
                        field_source_item, value = _foreshadow_chapter_field_source_item(
                            item,
                            field,
                            value,
                            chapter_labels,
                        )
                    if field in {"_source_label", "source_label"}:
                        merged_text, did_change = merge_source_labels(existing.get("_source_label", ""), value)
                        if did_change:
                            existing["_source_label"] = merged_text
                        continue
                    if key == "foreshadows" and field == "status":
                        if not item.get("_status_explicit"):
                            continue
                        inferred = _merge_foreshadow_status(existing.get("status", ""), value)
                        if inferred != str(existing.get("status", "") or "").strip():
                            existing["status"] = inferred
                        continue
                    if key == "foreshadows" and field == "_status_explicit":
                        if value:
                            existing["_status_explicit"] = True
                        continue
                    if key == "foreshadows" and field in {"_target_code", "target_code", "merge_target_code", "foreshadow_code", "命中编号", "伏笔编号", "目标编号"}:
                        if value and not existing.get("_target_code"):
                            existing["_target_code"] = _normalize_foreshadow_code(value)
                        continue
                    if incoming_terminal and field == "description":
                        cleaned = _foreshadow_terminal_review_description(value)
                        if cleaned != str(existing.get(field, "") or "").strip():
                            existing[field] = cleaned
                        continue
                    if key == "foreshadows" and field == "description":
                        raw_old = str(existing.get(field, "") or "").strip()
                        source_item = _foreshadow_source_item(item, chapter_labels, value)
                        merged_text, did_change = _merge_foreshadow_description_without_bloat(
                            _strip_internal_candidate_markers(raw_old),
                            _strip_internal_candidate_markers(value),
                            source_item,
                        )
                        did_change = did_change or merged_text != raw_old
                    else:
                        merged_text, did_change = merge_candidate_text(
                            existing.get(field, ""),
                            value,
                            append=field in {"notes", "description"},
                        )
                    if did_change:
                        existing[field] = merged_text
                        if key == "foreshadows" and field in {"setup_chapter", "payoff_chapter"}:
                            update_text = _foreshadow_chapter_update_text(field, merged_text)
                            if update_text:
                                merged_desc, desc_changed = _merge_foreshadow_description_without_bloat(
                                    existing.get("description", ""),
                                    update_text,
                                    field_source_item,
                                )
                                if desc_changed:
                                    existing["description"] = merged_desc
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

    def _merge_foreshadow_review_observations(self, incoming):
        incoming = _normalize_foreshadow_review_observations(incoming)
        merged = deepcopy(self.foreshadow_review_observations if isinstance(self.foreshadow_review_observations, dict) else {})
        if not isinstance(merged, dict):
            merged = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
        chapter_labels = _chapter_source_label_map(getattr(self, "current_project", {}))
        merged.setdefault("foreshadows", [])
        by_name = {
            str(item.get("name", "") or "").strip(): item
            for item in merged.get("foreshadows", [])
            if isinstance(item, dict) and str(item.get("name", "") or "").strip()
        }
        for item in incoming.get("foreshadows", []) if isinstance(incoming, dict) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            if not name:
                continue
            existing = by_name.get(name)
            if existing is None:
                clone = deepcopy(item)
                clone["description"] = _strip_internal_candidate_markers(
                    clone.get("description", "")
                )
                if str(clone.get("description", "") or "").strip():
                    clone["description"], _did_change = _merge_foreshadow_description_without_bloat(
                        "",
                        clone.get("description", ""),
                        clone,
                    )
                merged["foreshadows"].append(clone)
                by_name[name] = clone
                continue
            for field in ("status", "setup_chapter", "payoff_chapter", "description", "review_action", "merge_target", "review_reason", "evidence", "_source_label"):
                raw_new = str(item.get(field, "") or "").strip()
                new = _strip_internal_candidate_markers(raw_new)
                raw_old = str(existing.get(field, "") or "").strip()
                old = _strip_internal_candidate_markers(raw_old)
                if old != raw_old:
                    existing[field] = old
                if not new:
                    continue
                field_source_item = item
                if field in {"setup_chapter", "payoff_chapter"}:
                    field_source_item, new = _foreshadow_chapter_field_source_item(
                        item,
                        field,
                        new,
                        chapter_labels,
                    )
                if field == "description":
                    merged_desc, did_change = _merge_foreshadow_description_without_bloat(
                        old,
                        new,
                        _foreshadow_source_item(item, chapter_labels, new),
                    )
                    if did_change:
                        existing[field] = merged_desc
                    continue
                if not old:
                    existing[field] = new
                    update_text = _foreshadow_chapter_update_text(field, new)
                    if update_text:
                        merged_desc, did_change = _merge_foreshadow_description_without_bloat(
                            existing.get("description", ""),
                            update_text,
                            field_source_item,
                        )
                        if did_change:
                            existing["description"] = merged_desc
                elif new == old or new in old:
                    continue
                elif old in new:
                    existing[field] = new
                    update_text = _foreshadow_chapter_update_text(field, new)
                    if update_text:
                        merged_desc, did_change = _merge_foreshadow_description_without_bloat(
                            existing.get("description", ""),
                            update_text,
                            field_source_item,
                        )
                        if did_change:
                            existing["description"] = merged_desc
                else:
                    existing[field] = f"{old}\n补充：{new}"
        merged["project_materials"] = {"bible": "", "world_rules": "", "timeline": "", "summary": ""}
        return merged

    def _is_foreshadow_observation_draft(self, item):
        item = item if isinstance(item, dict) else {}
        stage = str(item.get("_review_stage", "") or "").strip()
        action = str(item.get("review_action", "") or item.get("体检建议", "") or "").strip()
        description = str(item.get("description", "") or "")
        return (
            stage == "observation_draft"
            or action == "观察待比对"
            or "体检建议：观察待比对" in description
        )

    def _foreshadow_observation_draft_candidates(self, observations=None):
        observations = _normalize_foreshadow_review_observations(
            observations if isinstance(observations, dict) else getattr(self, "foreshadow_review_observations", {})
        )
        drafts = []
        for item in observations.get("foreshadows", []) if isinstance(observations, dict) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            description = str(item.get("description", "") or "").strip()
            if not name or not description:
                continue
            clone = deepcopy(item)
            clone["name"] = name
            clone["description"] = _dedupe_text_lines(
                "\n".join(
                    part
                    for part in (
                        description,
                        "体检建议：观察待比对" if "体检建议：观察待比对" not in description else "",
                        "阶段：逐章伏笔观察草稿，等待按章比对。",
                    )
                    if str(part or "").strip()
                )
            )
            clone["review_action"] = "观察待比对"
            clone["_review_stage"] = "observation_draft"
            clone.pop("_target_code", None)
            clone.pop("_status_explicit", None)
            drafts.append(clone)
        return drafts

    def _sync_foreshadow_observations_to_import_candidates(self):
        candidates = _normalize_import_candidates(getattr(self, "import_candidates", {}))
        foreshadows = [
            item
            for item in candidates.get("foreshadows", [])
            if not self._is_foreshadow_observation_draft(item)
        ]
        foreshadows.extend(self._foreshadow_observation_draft_candidates())
        candidates["foreshadows"] = foreshadows
        self.import_candidates, self._last_candidate_auto_cleanup_report = _sanitize_import_candidates_for_long_form(
            getattr(self, "current_project", {}) if isinstance(getattr(self, "current_project", {}), dict) else {},
            candidates,
        )
        return len(self._foreshadow_observation_draft_candidates())

    def _drop_foreshadow_observation_draft_candidates(self):
        candidates = _normalize_import_candidates(getattr(self, "import_candidates", {}))
        candidates["foreshadows"] = [
            item
            for item in candidates.get("foreshadows", [])
            if not self._is_foreshadow_observation_draft(item)
        ]
        self.import_candidates = candidates

    def _apply_foreshadow_review_postprocess_candidates(self, data, keep_observation_drafts=False):
        observation_drafts = self._foreshadow_observation_draft_candidates() if keep_observation_drafts else []
        self._drop_foreshadow_observation_draft_candidates()
        raw_candidates = self._merge_import_candidates(data)
        self.import_candidates, self._last_candidate_auto_cleanup_report = _sanitize_import_candidates_for_long_form(
            self.current_project,
            raw_candidates,
        )
        if not observation_drafts:
            return
        candidates = _normalize_import_candidates(self.import_candidates)
        existing_names = {
            str(item.get("name", "") or "").strip()
            for item in candidates.get("foreshadows", [])
            if isinstance(item, dict) and not self._is_foreshadow_observation_draft(item)
        }
        for item in observation_drafts:
            name = str(item.get("name", "") or "").strip()
            if name and name not in existing_names:
                candidates.setdefault("foreshadows", []).append(item)
        self.import_candidates, self._last_candidate_auto_cleanup_report = _sanitize_import_candidates_for_long_form(
            self.current_project,
            candidates,
        )

    def _candidate_analysis_chunk_stats(self, data):
        data = data if isinstance(data, dict) else {}
        return (
            int(data.get("_chunk_total", 0) or 0),
            int(data.get("_chunk_succeeded", 0) or 0),
        )

    def _candidate_auto_cleanup_status_text(self):
        report = getattr(self, "_last_candidate_auto_cleanup_report", {}) or {}
        if not isinstance(report, dict):
            return ""
        filtered = report.get("filtered", {})
        trimmed = report.get("trimmed", {})
        filtered_total = sum(int(value or 0) for value in filtered.values()) if isinstance(filtered, dict) else 0
        trimmed_total = sum(int(value or 0) for value in trimmed.values()) if isinstance(trimmed, dict) else 0
        parts = []
        if filtered_total:
            parts.append(f"已忽略 {filtered_total} 条空/无效候选")
        if trimmed_total:
            parts.append(f"已清理 {trimmed_total} 条重复/占位说明")
        return "；" + "，".join(parts) if parts else ""

    def _candidate_postprocess_status(self):
        state = getattr(self, "candidate_postprocess_state", {}) or {}
        if not isinstance(state, dict):
            return ""
        return str(state.get("status", "") or "").strip()

    def _candidate_postprocess_error(self):
        state = getattr(self, "candidate_postprocess_state", {}) or {}
        if not isinstance(state, dict):
            return ""
        return str(state.get("error", "") or "").strip()

    def _has_candidate_postprocess_pending(self):
        return (
            self._candidate_postprocess_status() in {"pending", "failed"}
            and _import_candidates_has_content(getattr(self, "import_candidates", {}))
        )

    def _set_candidate_postprocess_state(self, status="", error=""):
        status = str(status or "").strip()
        if status not in {"pending", "failed"}:
            self.candidate_postprocess_state = {}
            return
        state = {"status": status, "updated_at": now_str()}
        error = str(error or "").strip()
        if error:
            state["error"] = error
        self.candidate_postprocess_state = state

    def _apply_candidate_analysis_result(self, data):
        data = data if isinstance(data, dict) else {}
        state = _normalize_candidate_analysis_state({
            "failed_candidate_chunks": data.get("_failed_chunks", []),
            "pending_candidate_chapter_ids": self.pending_analysis_chapter_ids,
        })
        self.failed_analysis_chunks = state.get("failed_candidate_chunks", [])
        self.pending_analysis_chapter_ids = state.get("pending_candidate_chapter_ids", [])
        if getattr(self, "_analysis_merge_with_existing", False):
            raw_candidates = self._merge_import_candidates(data)
        else:
            raw_candidates = _normalize_ai_candidates(data)
        self.import_candidates, self._last_candidate_auto_cleanup_report = _sanitize_import_candidates_for_long_form(
            self.current_project,
            raw_candidates,
        )
        return self._candidate_analysis_chunk_stats(data)

    def _apply_candidate_postprocess_result(self, data):
        if isinstance(data, dict) and data.get("_postprocess_empty"):
            self._last_candidate_auto_cleanup_report = {}
            self._set_candidate_postprocess_state("")
            return False
        raw_candidates = _normalize_ai_candidates(data)
        self.import_candidates, self._last_candidate_auto_cleanup_report = _sanitize_import_candidates_for_long_form(
            self.current_project,
            raw_candidates,
        )
        self._set_candidate_postprocess_state("")
        return True

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
            if not str(chap.get("text", "") or "").strip():
                continue
            if chapter_id in wanted or _chapter_needs_analysis(chap):
                if _chapter_analysis_hash(chap):
                    pending.append(chapter_id)
                    seen.add(chapter_id)
        return pending

    def _start_candidate_postprocess(self, provider, model):
        self._set_candidate_postprocess_state("pending")
        self._sync_candidate_analysis_state()
        perf_start = time.perf_counter()
        dossier = _candidate_analysis_dossier_text(self._ai_project_snapshot())
        self._log_novel_perf(
            "AI候选合并-构建档案输入",
            perf_start,
            threshold_ms=80,
            dossier_len=len(dossier),
            candidate_items=sum(
                len(self.import_candidates.get(key, []))
                for key in ("characters", "lore", "foreshadows")
                if isinstance(self.import_candidates.get(key, []), list)
            ),
            **self._novel_perf_summary(),
        )
        self.analysis_worker = NovelCandidatePostprocessWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            deepcopy(self.import_candidates),
            dossier,
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
        )
        self._connect_novel_worker_status(self.analysis_worker)
        self.analysis_worker.result_ready.connect(self.on_ai_candidate_postprocess_ready)
        self.analysis_worker.failed.connect(self.on_ai_candidate_postprocess_failed)
        self.analysis_worker.finished.connect(self._cleanup_analysis_worker)
        self._analysis_stop_requested_by_user = False
        self._set_candidate_actions_enabled(False)
        self.set_status_tip("正在进行 AI 候选合并和已有档案查重...")
        self.analysis_worker.start()

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
        if self._has_candidate_postprocess_pending():
            self._start_candidate_postprocess(provider, model)
            return
        retry_chunk_items = [
            deepcopy(item)
            for item in (getattr(self, "failed_analysis_chunks", []) or [])
            if isinstance(item, dict) and str(item.get("text", "") or "").strip()
        ]
        retrying_failed_chunks = bool(retry_chunk_items)
        if retrying_failed_chunks:
            chapter_ids = list(self.pending_analysis_chapter_ids or self._pending_candidate_analysis_chapter_ids())
            text = "\n\n".join(str(item.get("text", "") or "").strip() for item in retry_chunk_items)
            analysis_chunks = retry_chunk_items
        else:
            chapter_ids = self._pending_candidate_analysis_chapter_ids()
            analysis_chunks = None
            perf_start = time.perf_counter()
            text = _candidate_analysis_text(self._ai_project_snapshot(), "", chapter_ids, include_dossier=False)
            self._log_novel_perf(
                "AI分析候选-构建正文输入",
                perf_start,
                threshold_ms=80,
                pending_chapters=len(chapter_ids),
                text_len=len(text),
                **self._novel_perf_summary(),
            )
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
        perf_start = time.perf_counter()
        dossier = _candidate_analysis_dossier_text(self._ai_project_snapshot())
        self._log_novel_perf(
            "AI分析候选-构建档案输入",
            perf_start,
            threshold_ms=80,
            dossier_len=len(dossier),
            **self._novel_perf_summary(),
        )
        self.analysis_worker = NovelAnalysisWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            text,
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
            concurrency,
            chunks=analysis_chunks,
            dossier=dossier,
        )
        self._connect_novel_worker_status(self.analysis_worker)
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

    def _chapter_plan_framework_parameters(self):
        project = self.current_project if isinstance(getattr(self, "current_project", None), dict) else {}
        source = project.get("imported_framework_source", {})
        source = source if isinstance(source, dict) else {}
        analysis = self._framework_ai_analysis()
        parameters = deepcopy(analysis.get("planning_parameters", {}))
        if not analysis:
            parameters = _extract_framework_planning_parameters(source.get("text", ""))
        framework = project.get("creation_framework", {})
        framework = framework if isinstance(framework, dict) else {}
        for key, framework_key in (
            ("target_words", "total_words"),
            ("average_chapter_words", "average_chapter_words"),
        ):
            try:
                value = int(framework.get(framework_key, 0) or 0)
            except (ValueError, TypeError):
                value = 0
            if value > 0:
                parameters.setdefault(key, value)
        foundation = framework.get("chapter_plan_foundation", {})
        if isinstance(foundation, dict):
            try:
                count = int(foundation.get("total_chapter_count", 0) or 0)
            except (ValueError, TypeError):
                count = 0
            if count > 0:
                parameters.setdefault("total_chapter_count", count)
        # When the imported source already contains explicit chapter records,
        # their actual range is authoritative. A prose header may contain an
        # old estimate that conflicts with the detailed chapter list.
        reference = project.get("imported_chapter_plan_reference", {})
        if isinstance(reference, dict):
            chapter_items = reference.get("chapters", [])
            if isinstance(chapter_items, list):
                indices = []
                for item in chapter_items:
                    if not isinstance(item, dict):
                        continue
                    try:
                        index = int(item.get("index", 0) or 0)
                    except (TypeError, ValueError):
                        index = 0
                    if index > 0:
                        indices.append(index)
                if indices:
                    parameters["total_chapter_count"] = max(indices)
            if not indices:
                stage_ends = []
                for stage in reference.get("stages", []) if isinstance(reference.get("stages"), list) else []:
                    try:
                        end_chapter = int(stage.get("end_chapter", 0) or 0)
                    except (TypeError, ValueError):
                        end_chapter = 0
                    if end_chapter > 0:
                        stage_ends.append(end_chapter)
                if stage_ends:
                    parameters["total_chapter_count"] = max(stage_ends)
        foundation = analysis.get("foundation", {}) if isinstance(analysis, dict) else {}
        foundation_arcs = foundation.get("arcs", []) if isinstance(foundation, dict) else []
        arc_ends = []
        for arc in foundation_arcs if isinstance(foundation_arcs, list) else []:
            try:
                end_chapter = int(arc.get("end_chapter", 0) or 0)
            except (TypeError, ValueError):
                end_chapter = 0
            if end_chapter > 0:
                arc_ends.append(end_chapter)
        if arc_ends:
            parameters["total_chapter_count"] = max(arc_ends)
        # A detailed source with explicit ranges is more reliable than a
        # contradictory prose estimate such as "250 chapters". Derive the
        # average only when the source gives enough information to do so.
        if parameters.get("total_chapter_count") and parameters.get("target_words"):
            chapter_count = int(parameters["total_chapter_count"])
            average = int(parameters.get("average_chapter_words", 0) or 0)
            if chapter_count > 0 and average <= 0:
                parameters["average_chapter_words"] = max(
                    1, round(int(parameters["target_words"]) / chapter_count)
                )
        return parameters

    def _chapter_plan_restore_imported_reference(self):
        """Recover old imports locally, without changing a running event ledger."""
        project = self.current_project
        if self._framework_ai_analysis():
            return
        reference = project.get("imported_chapter_plan_reference", {})
        reference = reference if isinstance(reference, dict) else {}
        generation = project.get("chapter_plan_generation_state", {})
        generation = generation if isinstance(generation, dict) else {}
        if generation.get("chapters") or project.get("chapters"):
            return
        source = self._framework_import_source()
        structured = _extract_structured_framework_chapter_plan(source.get("text", ""))
        if reference.get("stages"):
            existing_outlines = {
                str(item.get("index", "")): str(item.get("outline", "") or "").strip()
                for item in reference.get("chapters", []) if isinstance(item, dict)
            }
            recovered_outlines = [
                item for item in structured.get("chapters", [])
                if str(item.get("outline", "") or "").strip()
                and not existing_outlines.get(str(item.get("index", "")))
            ]
            if not recovered_outlines:
                return
        if structured.get("stages") or structured.get("chapters"):
            self._store_imported_chapter_plan_reference(
                _merge_framework_chapter_plans(reference, structured),
                source.get("source_title", ""), source.get("source_label", ""),
            )

    def _framework_ai_analysis(self):
        project = self.current_project if isinstance(self.current_project, dict) else {}
        source = project.get("imported_framework_source", {})
        source = source if isinstance(source, dict) else {}
        if not source.get("text"):
            return {}
        return _normalize_framework_analysis(project.get("imported_framework_analysis", {}), source.get("text", ""))

    def _chapter_plan_imported_foundation(self, state):
        """Follow the saved AI decision; never infer completeness from headings."""
        if int(state.get("existing_chapter_count", 0) or 0):
            return {}
        analysis = self._framework_ai_analysis()
        if analysis.get("foundation_mode") != "reuse":
            return {}
        foundation = deepcopy(analysis.get("foundation", {}))
        if not foundation:
            return {}
        foundation["source"] = "imported_framework"
        foundation["source_hash"] = analysis["source_hash"]
        for key in ("target_words", "average_chapter_words", "total_chapter_count", "existing_chapter_count"):
            foundation[key] = int(state.get(key, 0) or 0)
        # Number/range validity is a program invariant, not a story judgment.
        arcs = foundation.get("arcs", [])
        if arcs:
            expected = 1
            for arc in arcs:
                if arc["start_chapter"] != expected or arc["end_chapter"] < expected:
                    return {}
                expected = arc["end_chapter"] + 1
            if expected - 1 != state.get("total_chapter_count") or self._chapter_plan_master_reference_error(foundation):
                return {}
        elif self.current_project.get("imported_chapter_plan_reference", {}).get("stages"):
            return {}
        return _normalize_chapter_plan_foundation(foundation)

    def _chapter_plan_creation_wizard_foundation(self, state):
        """Reuse the wizard's confirmed stage plan without another planning call."""
        project = self.current_project if isinstance(getattr(self, "current_project", None), dict) else {}
        framework = project.get("creation_framework", {})
        if not isinstance(framework, dict) or framework.get("source") != "creation_wizard":
            return {}
        foundation = framework.get("chapter_plan_foundation", {})
        if not isinstance(foundation, dict) or not foundation:
            try:
                foundation = build_chapter_plan_foundation(framework)
            except Exception as exc:
                log_debug("恢复向导章节规划基础失败", exc)
                return {}
        foundation = _normalize_chapter_plan_foundation(foundation)
        if not foundation.get("arcs") or not foundation.get("narrative_strategy_profile"):
            return {}

        for key in ("target_words", "average_chapter_words", "total_chapter_count"):
            try:
                value = int(state.get(key, 0) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                foundation[key] = value
        try:
            existing_count = max(0, int(state.get("existing_chapter_count", 0) or 0))
        except (TypeError, ValueError):
            existing_count = 0
        foundation["existing_chapter_count"] = existing_count
        foundation["source"] = "creation_wizard"

        try:
            total_chapters = int(foundation.get("total_chapter_count", 0) or 0)
        except (TypeError, ValueError):
            total_chapters = 0
        arcs = foundation.get("arcs", [])
        if total_chapters <= 0 or not isinstance(arcs, list):
            return {}
        expected_start = 1
        for arc in arcs:
            if not isinstance(arc, dict):
                return {}
            try:
                start = int(arc.get("start_chapter", 0) or 0)
                end = int(arc.get("end_chapter", 0) or 0)
            except (TypeError, ValueError):
                return {}
            if start != expected_start or end < start:
                return {}
            expected_start = end + 1
        if expected_start - 1 != total_chapters:
            return {}
        return foundation

    def _chapter_plan_reuse_foundation(self, state, saved_state):
        """Changing only chapter size does not discard the confirmed planning foundation."""
        saved_state = saved_state if isinstance(saved_state, dict) else {}
        if not saved_state.get("master_plan") or not saved_state.get("profile_confirmed"):
            return
        for key in ("target_words", "total_chapter_count", "existing_chapter_count"):
            if int(saved_state.get(key, 0) or 0) != int(state.get(key, 0) or 0):
                return
        master = _normalize_chapter_plan_foundation(saved_state["master_plan"])
        master["average_chapter_words"] = state["average_chapter_words"]
        state["master_plan"] = master
        state["profile_confirmed"] = True
        if saved_state.get("force_master_regeneration"):
            state["force_master_regeneration"] = True
        state["narrative_strategy_profile"] = deepcopy(master.get("narrative_strategy_profile", {}))
        state["foundation_hash"] = self._chapter_plan_foundation_hash(master)
        self.current_project["chapter_plan_foundation"] = deepcopy(master)

    def _chapter_plan_default_average_words(self):
        parameters = self._chapter_plan_framework_parameters()
        project = self.current_project if isinstance(getattr(self, "current_project", None), dict) else {}
        saved_state = project.get("chapter_plan_generation_state", {})
        saved_state = saved_state if isinstance(saved_state, dict) else {}
        foundation = project.get("chapter_plan_foundation", {})
        foundation = foundation if isinstance(foundation, dict) else {}
        try:
            value = int(parameters.get("average_chapter_words")
                        or saved_state.get("average_chapter_words")
                        or foundation.get("average_chapter_words")
                        or self.config.setdefault("novel", {}).get("chapter_plan_average_words", 3000) or 3000)
        except Exception:
            value = 3000
        return max(1000, min(20000, value))

    def _chapter_plan_counts(self, target_words, average_chapter_words, existing_count=0):
        try:
            target_words = int(target_words or 0)
        except Exception:
            target_words = 0
        try:
            average_chapter_words = int(average_chapter_words or 0)
        except Exception:
            average_chapter_words = 0
        target_words = max(1, target_words)
        average_chapter_words = max(1, average_chapter_words)
        total_count = max(1, (target_words + average_chapter_words - 1) // average_chapter_words)
        remaining_count = max(1, total_count - max(0, int(existing_count or 0)))
        return total_count, remaining_count

    def _chapter_plan_clip_text(self, value, limit, keep_tail=False):
        text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text or len(text) <= limit:
            return text
        limit = max(20, int(limit or 20))
        marker = "\n...[已压缩]...\n"
        if limit <= len(marker) + 20:
            return text[-limit:] if keep_tail else text[:limit]
        available = limit - len(marker)
        if keep_tail:
            head = max(10, available // 3)
            tail = max(10, available - head)
            return text[:head].rstrip() + marker + text[-tail:].lstrip()
        return text[:available].rstrip() + marker

    def _chapter_plan_records(
        self,
        items,
        fields,
        max_items,
        field_limit=500,
        keep_tail_fields=None,
        total_limit=None,
        minimal_fields=None,
    ):
        keep_tail_fields = set(keep_tail_fields or [])
        records = []
        for item in (items if isinstance(items, list) else [])[:max_items]:
            if not isinstance(item, dict):
                continue
            record = {}
            for field in fields:
                value = item.get(field, "")
                if isinstance(value, list):
                    record[field] = _normalize_name_list(value)
                else:
                    record[field] = self._chapter_plan_clip_text(value, field_limit, field in keep_tail_fields)
            records.append(record)
        if total_limit is not None:
            limits = {field: field_limit for field in fields}
            for field in keep_tail_fields:
                if field in limits:
                    limits[field] = field_limit
            records = _compact_volume_handoff_records(
                records,
                tuple(fields),
                limits,
                max(1000, int(total_limit or 0)),
                minimal_fields=tuple(minimal_fields or ("name",)),
            )
        return records

    @staticmethod
    def _chapter_plan_foreshadow_chapter(value):
        text = str(value or "").strip()
        if not text:
            return 0
        match = re.search(r"第\s*(\d+)\s*章", text)
        if not match:
            match = re.search(r"(?<!\d)(\d+)(?!\d)", text)
        try:
            return int(match.group(1)) if match else 0
        except (AttributeError, TypeError, ValueError):
            return 0

    def _chapter_plan_scoped_foreshadows(self, items, start_index, end_index):
        """只把当前章节范围内已出现的伏笔送入向导章节规划。

        向导保存的伏笔资料覆盖全书，并且可能带有后续阶段的具体埋设章号。
        如果整份资料直接进入当前批次，模型会把后续章位当成本批任务，导致
        当前阶段被提前写穿。这里仅裁剪请求上下文，不改变项目里的原始伏笔。
        """
        try:
            start_index = int(start_index or 0)
            end_index = int(end_index or 0)
        except (TypeError, ValueError):
            return items if isinstance(items, list) else []
        if start_index <= 0 or end_index < start_index:
            return items if isinstance(items, list) else []

        scoped = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            setup_chapter = self._chapter_plan_foreshadow_chapter(
                item.get("setup_chapter", "")
            )
            if setup_chapter and setup_chapter > end_index:
                continue
            row = deepcopy(item)
            payoff_chapter = self._chapter_plan_foreshadow_chapter(
                row.get("payoff_chapter", "")
            )
            if payoff_chapter and payoff_chapter > end_index:
                row.pop("payoff_chapter", None)
            scoped.append(row)
        return scoped

    def _chapter_plan_compact_reference_context(self, reference, total_limit, master=False):
        """Keep source-framework constraints structured when a plan is large."""
        reference = deepcopy(reference if isinstance(reference, dict) else {})
        total_limit = max(6000, int(total_limit or 0))

        def size():
            return len(json.dumps(reference, ensure_ascii=False, separators=(",", ":")))

        if size() <= total_limit:
            return reference
        reference["usage"] = self._chapter_plan_clip_text(reference.get("usage", ""), 1000)
        reference["summary"] = self._chapter_plan_clip_text(reference.get("summary", ""), 2600, keep_tail=True)
        stage_index = reference.get("stage_index", [])
        reference["stage_index"] = _compact_volume_handoff_records(
            stage_index,
            ("id", "name", "start_chapter", "end_chapter"),
            {"id": 40, "name": 90, "start_chapter": 20, "end_chapter": 20},
            5000,
            minimal_fields=("id", "name", "start_chapter", "end_chapter"),
        )
        chapters = reference.get("chapters", [])
        if isinstance(chapters, list) and chapters:
            if master and reference.get("stages"):
                reference["chapter_index"] = _compact_volume_handoff_records(
                    chapters,
                    ("index", "title", "narrative_stage"),
                    {"index": 20, "title": 80, "narrative_stage": 80},
                    9000,
                    minimal_fields=("index", "title"),
                )
                reference.pop("chapters", None)
            else:
                reference["chapters"] = _compact_volume_handoff_records(
                    chapters,
                    (
                        "index", "title", "target_words", "narrative_stage",
                        "outline", "characters", "ending_hook", "source_event_ids",
                    ),
                    {
                        "index": 20, "title": 80, "target_words": 40, "narrative_stage": 80,
                        "outline": 420, "ending_hook": 100,
                    },
                    max(8000, total_limit // 3),
                    minimal_fields=("index", "title", "outline"),
                )

        stages = reference.get("stages", [])
        stages = stages if isinstance(stages, list) else []
        event_count = sum(
            len(item.get("events", []))
            for item in stages if isinstance(item, dict) and isinstance(item.get("events", []), list)
        )

        def compact_stages(event_limit):
            compacted = []
            for item in stages:
                if not isinstance(item, dict):
                    continue
                row = {
                    "id": self._chapter_plan_clip_text(item.get("id", ""), 40),
                    "name": self._chapter_plan_clip_text(item.get("name", ""), 100),
                    "summary": self._chapter_plan_clip_text(item.get("summary", ""), 1500),
                    "start_chapter": item.get("start_chapter", 0),
                    "end_chapter": item.get("end_chapter", 0),
                }
                events = []
                for event in item.get("events", []) if isinstance(item.get("events", []), list) else []:
                    if not isinstance(event, dict):
                        continue
                    event_id = self._chapter_plan_clip_text(
                        _canonical_chapter_plan_event_id(event.get("id", "")),
                        40,
                    )
                    event_text = self._chapter_plan_clip_text(event.get("text", ""), event_limit)
                    if event_id and event_text:
                        events.append({
                            "id": event_id,
                            "order": event.get("order", 0),
                            "text": event_text,
                        })
                if events:
                    row["events"] = events
                compacted.append(row)
            return compacted

        if stages:
            base_event_limit = max(80, min(280, (max(6000, total_limit // 2) // max(1, event_count)) - 40))
            for scale in (1.0, 0.7, 0.45, 0.25):
                reference["stages"] = compact_stages(max(60, int(base_event_limit * scale)))
                if size() <= total_limit:
                    return reference
            if master:
                # The planning-foundation context only needs stage borders and
                # broad constraints here. Each batch later receives its own
                # fully scoped event range.
                reference.pop("stages", None)
            else:
                reference["stages"] = compact_stages(60)

        if size() > total_limit and isinstance(reference.get("chapters"), list):
            reference["chapters"] = _compact_volume_handoff_records(
                reference.get("chapters", []),
                ("index", "title", "outline", "source_event_ids"),
                {"index": 20, "title": 70, "outline": 100},
                max(4000, total_limit // 4),
                minimal_fields=("index", "title"),
            )
        return reference

    def _chapter_plan_compact_batch_continuity(self, value, total_limit=26000):
        """Keep batch-to-batch continuity useful without letting its ledger bypass the request cap."""
        source = deepcopy(value if isinstance(value, dict) else {})
        total_limit = max(3000, int(total_limit or 0))

        def clipped_list(items, item_limit, list_limit):
            rows = []
            for item in items if isinstance(items, list) else []:
                text = self._chapter_plan_clip_text(item, item_limit)
                if text:
                    rows.append(text)
            if not rows:
                return []
            return _compact_volume_handoff_records(
                [{"text": text} for text in rows],
                ("text",),
                {"text": item_limit},
                max(1000, int(list_limit or 0)),
                minimal_fields=("text",),
            )

        def build(scale):
            result = {}
            absolute_range = source.get("required_absolute_range", [])
            if isinstance(absolute_range, list) and len(absolute_range) >= 2:
                result["required_absolute_range"] = deepcopy(absolute_range[:2])

            locked_schedule = source.get("locked_node_schedule", {})
            if isinstance(locked_schedule, dict):
                nodes = []
                for item in locked_schedule.get("nodes", []):
                    if not isinstance(item, dict):
                        continue
                    try:
                        node_index = int(item.get("n", 0) or 0)
                        node_range = item.get("range", [])
                        start = int(node_range[0])
                        end = int(node_range[1])
                    except (TypeError, ValueError, IndexError):
                        continue
                    if node_index > 0 and start > 0 and end >= start:
                        nodes.append({"n": node_index, "r": [start, end]})
                if nodes:
                    result["locked_node_schedule"] = {
                        "stage_id": str(locked_schedule.get("stage_id", "") or "").strip(),
                        "range": deepcopy(locked_schedule.get("range", [])[:2]),
                        "nodes": nodes,
                    }

            master = source.get("master_plan", {})
            if isinstance(master, dict):
                compact_master = {}
                for key, limit in (
                    ("summary", 2600),
                    ("core_motive", 1400),
                    ("ending_promise", 1200),
                    ("global_hard_boundaries", 1200),
                ):
                    text = self._chapter_plan_clip_text(master.get(key, ""), max(120, int(limit * scale)))
                    if text:
                        compact_master[key] = text
                master_fields = (
                    ("name", "start_chapter", "end_chapter", "source_stage",
                     "dominant_line")
                    if str(master.get("source", "") or "").strip() == "creation_wizard"
                    else (
                        "name", "start_chapter", "end_chapter", "macro_phase", "source_stage",
                        "dominant_line", "relationship_goal", "end_state", "supporting_lines",
                        "goal", "main_conflict", "turning_points", "reader_payoff",
                        "emotional_arc", "pacing_pattern", "exposition_compression",
                        "variation_plan", "investigation_scope", "forbidden",
                    )
                )
                master_limits = (
                    {
                        "name": 80, "start_chapter": 20, "end_chapter": 20,
                        "source_stage": 80, "dominant_line": max(50, int(180 * scale)),
                    }
                    if str(master.get("source", "") or "").strip() == "creation_wizard"
                    else {
                        "name": 80, "start_chapter": 20, "end_chapter": 20, "macro_phase": 60,
                        "source_stage": 80, "dominant_line": max(50, int(180 * scale)),
                        "relationship_goal": max(40, int(140 * scale)), "end_state": max(40, int(140 * scale)),
                        "supporting_lines": max(40, int(120 * scale)),
                        "goal": max(40, int(120 * scale)), "main_conflict": max(40, int(120 * scale)),
                        "turning_points": max(40, int(120 * scale)), "reader_payoff": max(40, int(100 * scale)),
                        "emotional_arc": max(40, int(100 * scale)), "pacing_pattern": max(40, int(100 * scale)),
                        "exposition_compression": max(40, int(100 * scale)), "variation_plan": max(40, int(100 * scale)),
                        "investigation_scope": max(40, int(100 * scale)), "forbidden": max(40, int(100 * scale)),
                    }
                )
                arcs = _compact_volume_handoff_records(
                    master.get("arcs", []),
                    master_fields,
                    master_limits,
                    max(1200, int(total_limit * 0.34)),
                    minimal_fields=("name", "start_chapter", "end_chapter"),
                )
                if arcs:
                    compact_master["arcs"] = arcs
                if compact_master:
                    result["master_plan"] = compact_master

            ledger = _compact_volume_handoff_records(
                source.get("planned_chapter_ledger", []),
                (
                    "index", "title", "characters", "stage_id", "source_event_ids",
                ),
                {
                    "index": 20, "title": 70,
                },
                # Chapter number + title are the cross-batch identity index.
                # Keep a floor for that pair so a later compression tier does
                # not silently turn a 250-chapter ledger into title-only rows.
                max(12000, int(total_limit * 0.31)),
                minimal_fields=("index", "title"),
            )
            if ledger:
                result["planned_chapter_ledger"] = ledger

            tail = _compact_volume_handoff_records(
                source.get("previous_batch_tail", []),
                (
                    "index", "title", "outline", "characters", "stage_id", "source_event_ids",
                ),
                {
                    "index": 20, "title": 80, "outline": max(120, int(650 * scale)),
                },
                max(1200, int(total_limit * 0.24)),
                minimal_fields=("index", "title", "outline"),
            )
            if tail:
                result["previous_batch_tail"] = tail

            rules = clipped_list(source.get("rules", []), max(80, int(360 * scale)), max(1000, int(total_limit * 0.08)))
            if rules:
                result["rules"] = [item.get("text", "") for item in rules if isinstance(item, dict) and item.get("text")]
            return result

        for scale in (1.0, 0.7, 0.45, 0.25):
            result = build(scale)
            if len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= total_limit:
                return result

        # This final tier is only for damaged or unusually verbose saved state.
        # It keeps the current batch range, stage map, compact historical ledger,
        # and immediate handoff rather than slicing a JSON string mid-record.
        result = build(0.16)
        result["planned_chapter_ledger"] = _compact_volume_handoff_records(
            result.get("planned_chapter_ledger", []),
            ("index", "title", "characters", "stage_id", "source_event_ids"),
            {"index": 20, "title": 48},
            max(1000, int(total_limit * 0.30)),
            minimal_fields=("index", "title"),
        )
        result["previous_batch_tail"] = _compact_volume_handoff_records(
            result.get("previous_batch_tail", []),
            ("index", "title", "outline", "characters", "stage_id", "source_event_ids"),
            {"index": 20, "title": 55, "outline": 180},
            max(1000, int(total_limit * 0.25)),
            minimal_fields=("index", "title", "outline"),
        )
        return result

    def _chapter_plan_bounded_context(self, instruction_prefix, payload, context_mode="master"):
        """Return a valid, priority-ordered plan request under the shared cap."""
        payload = deepcopy(payload if isinstance(payload, dict) else {})
        budget = _CHAPTER_PLAN_CONTEXT_CHAR_BUDGET

        def render():
            return str(instruction_prefix or "") + json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ": "),
            )

        batch_mode = context_mode == "batch"
        if batch_mode and isinstance(payload.get("batch_continuity"), dict):
            payload["batch_continuity"] = self._chapter_plan_compact_batch_continuity(
                payload["batch_continuity"],
                46000,
            )

        context = render()
        if len(context) <= budget:
            return context

        materials = payload.get("project_materials", {})
        materials = materials if isinstance(materials, dict) else {}
        material_limit = 2600 if batch_mode else 3200
        for key in ("bible", "world_rules", "timeline", "summary"):
            materials[key] = self._chapter_plan_clip_text(materials.get(key, ""), material_limit, keep_tail=key in {"timeline", "summary"})
        payload["project_materials"] = materials
        if isinstance(payload.get("wizard_framework"), dict):
            payload["wizard_framework"] = self._chapter_plan_compact_creation_framework_context(
                payload["wizard_framework"],
                12000 if batch_mode else 18000,
            )
        payload["characters"] = _compact_volume_handoff_records(
            payload.get("characters", []),
            ("name", "role", "goal", "secret", "personality", "voice", "notes"),
            {"name": 80, "role": 90, "goal": 130, "secret": 130, "personality": 100, "voice": 100, "notes": 120},
            10000 if batch_mode else 14000,
            minimal_fields=("name", "role", "goal"),
        )
        payload["settings"] = _compact_volume_handoff_records(
            payload.get("settings", []),
            ("name", "type", "description"),
            {"name": 90, "type": 40, "description": 160},
            12000 if batch_mode else 16000,
            minimal_fields=("name", "type"),
        )
        payload["foreshadows"] = _compact_volume_handoff_records(
            payload.get("foreshadows", []),
            (
                "name", "type", "status", "setup_chapter", "payoff_chapter",
                "description", "revealed", "remaining_secret",
            ),
            {
                "name": 90, "type": 40, "status": 30,
                "setup_chapter": 40, "payoff_chapter": 40,
                "description": 220, "revealed": 160, "remaining_secret": 160,
            },
            9000 if batch_mode else 12000,
            minimal_fields=("name", "type", "description"),
        )
        if isinstance(payload.get("imported_chapter_plan_reference"), dict):
            payload["imported_chapter_plan_reference"] = self._chapter_plan_compact_reference_context(
                payload["imported_chapter_plan_reference"],
                18000 if batch_mode else 30000,
                master=not batch_mode,
            )
        if batch_mode and isinstance(payload.get("batch_continuity"), dict):
            payload["batch_continuity"] = self._chapter_plan_compact_batch_continuity(
                payload["batch_continuity"],
                32000,
            )
        context = render()
        if len(context) <= budget:
            return context

        existing = payload.get("existing_chapters", [])
        if isinstance(existing, list):
            payload["existing_chapters"] = _compact_volume_handoff_records(
                existing[-6:],
                ("index", "title", "status", "target_words", "outline", "summary", "key_facts", "linked_characters", "body_tail"),
                {"index": 20, "title": 80, "status": 40, "target_words": 30, "outline": 360, "summary": 240, "key_facts": 260, "body_tail": 240},
                9000,
                minimal_fields=("index", "title", "summary"),
            )
        profile = payload.get("narrative_strategy_profile", {})
        profile_text = json.dumps(profile, ensure_ascii=False, indent=2)
        if len(profile_text) > 5000:
            payload["narrative_strategy_profile"] = {
                "compressed_profile": self._chapter_plan_clip_text(profile_text, 5000, keep_tail=True)
            }
        if batch_mode and isinstance(payload.get("batch_continuity"), dict):
            payload["batch_continuity"] = self._chapter_plan_compact_batch_continuity(
                payload["batch_continuity"],
                22000,
            )
        context = render()
        if len(context) <= budget:
            return context

        # The final tier preserves the global planning contract and stage map,
        # then sacrifices old supporting detail before a request can overrun.
        for key in ("bible", "world_rules", "timeline", "summary"):
            payload["project_materials"][key] = self._chapter_plan_clip_text(
                payload["project_materials"].get(key, ""),
                1600,
                keep_tail=key in {"timeline", "summary"},
            )
        if isinstance(payload.get("wizard_framework"), dict):
            payload["wizard_framework"] = self._chapter_plan_compact_creation_framework_context(
                payload["wizard_framework"],
                7000 if batch_mode else 11000,
            )
        payload["characters"] = _compact_volume_handoff_records(
            payload.get("characters", []),
            ("name", "role", "goal"),
            {"name": 70, "role": 70, "goal": 80},
            6000,
            minimal_fields=("name", "role"),
        )
        payload["settings"] = _compact_volume_handoff_records(
            payload.get("settings", []),
            ("name", "type", "description"),
            {"name": 70, "type": 30, "description": 80},
            8000,
            minimal_fields=("name", "type"),
        )
        payload["foreshadows"] = _compact_volume_handoff_records(
            payload.get("foreshadows", []),
            ("name", "type", "status", "description", "revealed", "remaining_secret"),
            {"name": 70, "type": 30, "status": 24, "description": 110, "revealed": 80, "remaining_secret": 80},
            5000 if batch_mode else 7000,
            minimal_fields=("name", "description"),
        )
        if isinstance(payload.get("imported_chapter_plan_reference"), dict):
            payload["imported_chapter_plan_reference"] = self._chapter_plan_compact_reference_context(
                payload["imported_chapter_plan_reference"],
                12000,
                master=not batch_mode,
            )
        if batch_mode and isinstance(payload.get("batch_continuity"), dict):
            payload["batch_continuity"] = self._chapter_plan_compact_batch_continuity(
                payload["batch_continuity"],
                12000,
            )
        context = render()
        if len(context) <= budget:
            return context

        # The request must have a hard upper bound. This emergency envelope is
        # deliberately structured: it retains planning rules and current-batch
        # continuity while reducing supporting archives, instead of truncating
        # serialized JSON in the middle of a record.
        payload["project_materials"] = {
            key: self._chapter_plan_clip_text(
                payload.get("project_materials", {}).get(key, ""),
                800,
                keep_tail=key in {"timeline", "summary"},
            )
            for key in ("bible", "world_rules", "timeline", "summary")
        }
        if isinstance(payload.get("wizard_framework"), dict):
            payload["wizard_framework"] = self._chapter_plan_compact_creation_framework_context(
                payload["wizard_framework"],
                4000,
            )
        payload["characters"] = _compact_volume_handoff_records(
            payload.get("characters", []),
            ("name", "role", "goal"),
            {"name": 60, "role": 60, "goal": 70},
            3000,
            minimal_fields=("name", "role"),
        )
        payload["settings"] = _compact_volume_handoff_records(
            payload.get("settings", []),
            ("name", "type", "description"),
            {"name": 60, "type": 30, "description": 60},
            4000,
            minimal_fields=("name", "type"),
        )
        payload["foreshadows"] = _compact_volume_handoff_records(
            payload.get("foreshadows", []),
            ("name", "type", "description"),
            {"name": 60, "type": 24, "description": 80},
            2600,
            minimal_fields=("name",),
        )
        payload.pop("existing_chapter_index", None)
        if isinstance(payload.get("existing_chapters"), list):
            payload["existing_chapters"] = _compact_volume_handoff_records(
                payload["existing_chapters"][-3:],
                ("index", "title", "summary", "key_facts", "body_tail"),
                {"index": 20, "title": 70, "summary": 180, "key_facts": 180, "body_tail": 160},
                2500,
                minimal_fields=("index", "title", "summary"),
            )
        if isinstance(payload.get("imported_chapter_plan_reference"), dict):
            payload["imported_chapter_plan_reference"] = self._chapter_plan_compact_reference_context(
                payload["imported_chapter_plan_reference"],
                7000,
                master=not batch_mode,
            )
        profile = payload.get("narrative_strategy_profile", {})
        if isinstance(profile, dict):
            profile_text = json.dumps(profile, ensure_ascii=False, indent=2)
            payload["narrative_strategy_profile"] = {
                "compressed_profile": self._chapter_plan_clip_text(profile_text, 2400, keep_tail=True)
            }
        if batch_mode and isinstance(payload.get("batch_continuity"), dict):
            payload["batch_continuity"] = self._chapter_plan_compact_batch_continuity(
                payload["batch_continuity"],
                7000,
            )
        context = render()
        if len(context) <= budget:
            return context

        # Pathological saved projects may still exceed the global envelope.
        # Keep the current range, stage map and immediate handoff, then remove
        # older supporting detail in a deterministic final tier.
        payload["project_materials"] = {
            key: self._chapter_plan_clip_text(
                payload.get("project_materials", {}).get(key, ""),
                400,
                keep_tail=key in {"timeline", "summary"},
            )
            for key in ("bible", "world_rules", "timeline", "summary")
        }
        if isinstance(payload.get("wizard_framework"), dict):
            payload["wizard_framework"] = self._chapter_plan_compact_creation_framework_context(
                payload["wizard_framework"],
                2400,
            )
        payload["characters"] = _compact_volume_handoff_records(
            payload.get("characters", []),
            ("name", "role"),
            {"name": 50, "role": 50},
            1500,
            minimal_fields=("name",),
        )
        payload["settings"] = _compact_volume_handoff_records(
            payload.get("settings", []),
            ("name", "type"),
            {"name": 50, "type": 24},
            2000,
            minimal_fields=("name",),
        )
        payload["foreshadows"] = _compact_volume_handoff_records(
            payload.get("foreshadows", []),
            ("name", "type"),
            {"name": 50, "type": 24},
            1200,
            minimal_fields=("name",),
        )
        payload.pop("existing_chapter_index", None)
        payload.pop("existing_chapters", None)
        if isinstance(payload.get("imported_chapter_plan_reference"), dict):
            payload["imported_chapter_plan_reference"] = self._chapter_plan_compact_reference_context(
                payload["imported_chapter_plan_reference"],
                4000,
                master=not batch_mode,
            )
        if batch_mode and isinstance(payload.get("batch_continuity"), dict):
            payload["batch_continuity"] = self._chapter_plan_compact_batch_continuity(
                payload["batch_continuity"],
                3500,
            )
        return render()

    def _chapter_plan_reference_context(
        self,
        start_index=None,
        end_index=None,
        target_words=0,
        average_chapter_words=0,
        total_chapter_count=0,
    ):
        reference = self.current_project.get("imported_chapter_plan_reference", {}) if isinstance(self.current_project, dict) else {}
        if not isinstance(reference, dict):
            return {}
        semantic_outline_mode = str(
            reference.get("semantic_outline_mode", "") or ""
        ).strip().lower()
        if not semantic_outline_mode:
            # A complete imported framework keeps the original outline in the
            # local project.  The planner only needs chapter identity and the
            # one-shot reuse decision; sending every local outline again is a
            # large duplicate and does not improve that decision.
            framework_analysis = self._framework_ai_analysis()
            if isinstance(framework_analysis, dict):
                outline_mode = str(
                    framework_analysis.get("chapter_outline_mode", "") or ""
                ).strip().lower()
                mapping_status = str(
                    framework_analysis.get("local_mapping_status", "") or ""
                ).strip().lower()
                if outline_mode == "reuse" and mapping_status in {"mapped", "mapped_by_ai"}:
                    semantic_outline_mode = "reuse"
        chapters = []
        items = reference.get("chapters", [])
        items = items if isinstance(items, list) else []
        for fallback_index, item in enumerate(items[:1000], 1):
            if not isinstance(item, dict):
                continue
            try:
                item_index = int(item.get("index", fallback_index) or fallback_index)
            except Exception:
                item_index = fallback_index
            if start_index is not None and item_index < int(start_index):
                continue
            if end_index is not None and item_index > int(end_index):
                continue
            record = {
                "index": self._chapter_plan_clip_text(item_index, 20),
                "title": self._chapter_plan_clip_text(item.get("title", ""), 80),
                "target_words": self._chapter_plan_clip_text(item.get("target_words", ""), 40),
                "narrative_stage": self._chapter_plan_clip_text(item.get("narrative_stage", ""), 80),
                # Do not send imported prose back to AI during semantic reuse.
                # The local source remains available to the application.
                "outline": "" if semantic_outline_mode == "reuse" else self._chapter_plan_clip_text(item.get("outline", ""), 1000),
                "characters": _normalize_name_list(item.get("characters", [])),
                "ending_hook": self._chapter_plan_clip_text(item.get("ending_hook", ""), 240),
                "source_event_ids": [
                    _canonical_chapter_plan_event_id(value)
                    for value in _normalize_name_list(item.get("source_event_ids", []))
                ],
            }
            if any(str(value or "").strip() for value in record.values() if not isinstance(value, list)) or record["characters"]:
                chapters.append(record)
        stages = []
        stage_index = []
        reference_stages = reference.get("stages", []) if isinstance(reference.get("stages", []), list) else []
        for item in reference_stages:
            if not isinstance(item, dict):
                continue
            try:
                stage_start = int(item.get("start_chapter", 0) or 0)
                stage_end = int(item.get("end_chapter", 0) or 0)
            except Exception:
                continue
            if stage_start <= 0 or stage_end < stage_start:
                continue
            stage_index.append({
                "id": str(item.get("id", "") or "").strip().upper(),
                "name": self._chapter_plan_clip_text(item.get("name", ""), 120),
                "start_chapter": stage_start,
                "end_chapter": stage_end,
            })
            if start_index is not None and stage_end < int(start_index):
                continue
            if end_index is not None and stage_start > int(end_index):
                continue
            events = []
            for event in item.get("events", []) if isinstance(item.get("events", []), list) else []:
                if not isinstance(event, dict):
                    continue
                event_id = _canonical_chapter_plan_event_id(event.get("id", ""))
                event_text = self._chapter_plan_clip_text(event.get("text", ""), 600)
                if not event_id or not event_text:
                    continue
                try:
                    event_order = int(event.get("order", len(events) + 1) or len(events) + 1)
                except Exception:
                    event_order = len(events) + 1
                events.append({"id": event_id, "order": event_order, "text": event_text})
            # Chapter outlines are stored once in chapters. Keep stage events
            # only for legacy/non-chapter source material; imported detailed
            # chapters must never be duplicated into the stage ledger.
            if events and str(reference.get("source", "") or "") != "local_framework_parser":
                stages.append({
                    "id": _canonical_chapter_plan_stage_id(item.get("id", "")),
                    "name": self._chapter_plan_clip_text(item.get("name", ""), 120),
                    "summary": self._chapter_plan_clip_text(item.get("summary", ""), 1500),
                    "start_chapter": stage_start,
                    "end_chapter": stage_end,
                    "events": events,
                })
            elif str(reference.get("source", "") or "") == "local_framework_parser":
                stages.append({
                    "id": _canonical_chapter_plan_stage_id(item.get("id", "")),
                    "name": str(item.get("name", "") or f"阶段{stage_index}").strip(),
                    "summary": str(item.get("summary", "") or "").strip(),
                    "start_chapter": stage_start,
                    "end_chapter": stage_end,
                    "events": [],
                })
        summary = self._chapter_plan_clip_text(reference.get("summary", ""), 5000)
        result = {
            "usage": (
                "chapters是用户明确给出的章节级约束，必须按绝对章号继承。"
                "完整导入框架的章节原文已由程序本地保存；模型只返回use_imported或generate，不得重抄原文。"
                "stages.events是可选的阶段剧情节点；完整导入框架通常没有events。"
                "不要生成source_event_ids，不要复制章节原文或阶段节点；节点只提供故事事实和方向，不是动作清单，"
                "outline只需自然落实其语义，不得展开成流程步骤。"
                "stage_index是全书原框架的阶段边界；当前阶段的扩展章先把本阶段的人物、关系和现场后果写完整，"
                "下一阶段从当前阶段留下的新变化自然接续。"
            ),
            "summary": summary,
        }
        location_status = str(reference.get("local_mapping_status", "") or "").strip().lower()
        locations = reference.get("chapter_locations", [])
        if location_status == "pending":
            result["location_status"] = "pending"
            if isinstance(locations, list) and locations:
                result["chapter_locations"] = [
                    {
                        "index": int(item.get("index", 0) or 0),
                        "start_line": str(item.get("start_line", "") or "").strip(),
                        "end_line": str(item.get("end_line", "") or "").strip(),
                        **({"anchor": str(item.get("anchor", "") or "").strip()} if str(item.get("anchor", "") or "").strip() else {}),
                    }
                    for item in locations
                    if isinstance(item, dict) and int(item.get("index", 0) or 0) > 0
                ]
        if (
            not summary
            and not chapters
            and not stages
            and not result.get("chapter_locations")
            and result.get("location_status") != "pending"
        ):
            return {}
        if chapters:
            result["chapters"] = chapters
        if stages:
            result["stages"] = stages
        if stage_index:
            result["stage_index"] = stage_index
        return result

    def _chapter_plan_source_stage_for_index(self, chapter_index):
        project = self.current_project if isinstance(self.current_project, dict) else {}
        reference = project.get("imported_chapter_plan_reference", {})
        reference_stages = reference.get("stages", []) if isinstance(reference, dict) else []
        # 新建向导生成的阶段没有“导入框架”来源，但仍然是章节规划的硬边界。
        if not isinstance(reference_stages, list) or not reference_stages:
            creation_framework = project.get("creation_framework", {})
            reference_stages = (
                creation_framework.get("stage_plan", [])
                if isinstance(creation_framework, dict)
                else []
            )
        try:
            chapter_index = int(chapter_index or 0)
        except Exception:
            return {}
        for item in reference_stages if isinstance(reference_stages, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                start = int(item.get("start_chapter", 0) or 0)
                end = int(item.get("end_chapter", 0) or 0)
            except Exception:
                continue
            if start <= chapter_index <= end:
                return {
                "id": _canonical_chapter_plan_stage_id(item.get("id", "")),
                    "name": str(item.get("name", "") or "").strip(),
                    "start_chapter": start,
                    "end_chapter": end,
                }
        return {}

    def _chapter_plan_event_reference(self):
        reference = self.current_project.get("imported_chapter_plan_reference", {}) if isinstance(self.current_project, dict) else {}
        if not isinstance(reference, dict):
            return {}, [], {}
        catalog = {}
        stages = []
        for item in reference.get("stages", []) if isinstance(reference.get("stages", []), list) else []:
            if not isinstance(item, dict):
                continue
            try:
                stage_start = int(item.get("start_chapter", 0) or 0)
                stage_end = int(item.get("end_chapter", 0) or 0)
            except Exception:
                continue
            stage_id = _canonical_chapter_plan_stage_id(item.get("id", ""))
            events = []
            for event in item.get("events", []) if isinstance(item.get("events", []), list) else []:
                if not isinstance(event, dict):
                    continue
                event_id = _canonical_chapter_plan_event_id(event.get("id", ""))
                event_text = str(event.get("text", "") or "").strip()
                if not event_id or not event_text or event_id in catalog:
                    continue
                try:
                    order = int(event.get("order", len(events) + 1) or len(events) + 1)
                except Exception:
                    order = len(events) + 1
                info = {
                    "id": event_id,
                    "text": event_text,
                    "order": order,
                    "stage_id": stage_id,
                    "start_chapter": stage_start,
                    "end_chapter": stage_end,
                }
                catalog[event_id] = info
                events.append(info)
            if events:
                events.sort(key=lambda event: (event["order"], event["id"]))
                stages.append({
                    "id": stage_id,
                    "start_chapter": stage_start,
                    "end_chapter": stage_end,
                    "event_ids": [event["id"] for event in events],
                })
        explicit = {}
        for fallback_index, item in enumerate(
            reference.get("chapters", []) if isinstance(reference.get("chapters", []), list) else [], 1
        ):
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index", fallback_index) or fallback_index)
            except Exception:
                index = fallback_index
            explicit[index] = item
        return catalog, stages, explicit

    def _chapter_plan_event_assignment_error(self, generated, incoming):
        catalog, stages, _explicit = self._chapter_plan_event_reference()
        if not catalog:
            return ""
        assignments = []
        seen = set()
        for item in list(generated or []) + list(incoming or []):
            if not isinstance(item, dict):
                continue
            try:
                chapter_index = int(item.get("index", 0) or 0)
            except Exception:
                chapter_index = 0
            ids = [
                _canonical_chapter_plan_event_id(value)
                for value in _normalize_name_list(item.get("source_event_ids", []))
            ]
            if len(ids) != len(set(ids)):
                return f"第{chapter_index}章重复填写了同一原始事件ID。"
            for position, event_id in enumerate(ids):
                info = catalog.get(event_id)
                if info is None:
                    return f"第{chapter_index}章引用了未知原始事件ID：{event_id}。"
                if event_id in seen:
                    return f"原始事件{event_id}被多个章节重复使用。"
                if not (info["start_chapter"] <= chapter_index <= info["end_chapter"]):
                    return f"原始事件{event_id}被安排到所属阶段范围之外的第{chapter_index}章。"
                seen.add(event_id)
                assignments.append((info["stage_id"], chapter_index, position, info["order"], event_id))
        for stage in stages:
            ordered = [item for item in assignments if item[0] == stage["id"]]
            ordered.sort(key=lambda item: (item[1], item[2]))
            orders = [item[3] for item in ordered]
            if orders != sorted(orders):
                return f"阶段{stage['id']}的原始事件顺序被打乱。"
        batch_end = max(
            [int(item.get("index", 0) or 0) for item in incoming if isinstance(item, dict)] or [0]
        )
        for stage in stages:
            if stage["end_chapter"] <= batch_end:
                missing = [event_id for event_id in stage["event_ids"] if event_id not in seen]
                if missing:
                    preview = "、".join(missing[:6])
                    suffix = "等" if len(missing) > 6 else ""
                    return f"阶段{stage['id']}结束时仍缺少{len(missing)}个原始事件：{preview}{suffix}。"
        return ""

    def _chapter_plan_master_reference_error(self, master_plan):
        master_plan = master_plan if isinstance(master_plan, dict) else {}
        arcs = master_plan.get("arcs", []) if isinstance(master_plan.get("arcs"), list) else []
        reference = self.current_project.get("imported_chapter_plan_reference", {})
        if not arcs:
            if (master_plan.get("source") == "imported_framework" or master_plan.get("foundation_mode") == "reuse") and not reference.get("stages"):
                return ""
            return "AI没有返回阶段列表。"
        reference = self.current_project.get("imported_chapter_plan_reference", {}) if isinstance(self.current_project, dict) else {}
        stages = reference.get("stages", []) if isinstance(reference, dict) and isinstance(reference.get("stages"), list) else []
        if not stages:
            return ""
        first_new = int(master_plan.get("existing_chapter_count", 0) or 0) + 1
        total = int(master_plan.get("total_chapter_count", 0) or 0)
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            try:
                expected_start = max(first_new, int(stage.get("start_chapter", 0) or 0))
                expected_end = min(total, int(stage.get("end_chapter", 0) or 0))
            except Exception:
                continue
            if expected_start <= 0 or expected_end < expected_start:
                continue
            matched = any(
                isinstance(arc, dict)
                and int(arc.get("start_chapter", 0) or 0) == expected_start
                and int(arc.get("end_chapter", 0) or 0) == expected_end
                for arc in arcs
            )
            if not matched:
                name = str(stage.get("name", "") or "原框架阶段").strip()
                return f"{name}必须保持第{expected_start}-{expected_end}章边界，不能合并、拆分或提前。"
        return ""

    def _chapter_plan_creation_framework_context(self, project):
        """Expose the wizard's confirmed story facts without sending private state."""
        framework = project.get("creation_framework", {}) if isinstance(project, dict) else {}
        if not isinstance(framework, dict) or framework.get("source") != "creation_wizard":
            return {}
        premise = framework.get("premise", {})
        premise = premise if isinstance(premise, dict) else {}
        premise_context = {}
        for key, value in premise.items():
            # The project-level core_motive below is the only planning source
            # of truth.  Do not send the legacy premise aliases beside it and
            # make the model reconcile two copies of the mainline.
            if str(key) in {"main_line", "core_motive"}:
                continue
            if isinstance(value, (str, int, float, bool)):
                text = self._chapter_plan_clip_text(value, 1800)
                if text:
                    premise_context[str(key)] = text
            elif isinstance(value, list):
                values = [
                    self._chapter_plan_clip_text(item, 800)
                    for item in value
                    if str(item or "").strip()
                ]
                if values:
                    premise_context[str(key)] = values[:40]

        def compact_records(items, fields, item_limit=900, total_limit=10000):
            rows = []
            used = 0
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                row = {}
                for key in fields:
                    value = item.get(key, "")
                    if isinstance(value, list):
                        value = [
                            self._chapter_plan_clip_text(entry, 320)
                            for entry in value if str(entry or "").strip()
                        ][:24]
                    elif isinstance(value, dict):
                        value = self._chapter_plan_clip_text(
                            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
                            item_limit,
                        )
                    else:
                        value = self._chapter_plan_clip_text(value, item_limit)
                    if value not in (None, "", [], {}):
                        row[key] = value
                if not row:
                    continue
                row_cost = len(json.dumps(row, ensure_ascii=False))
                if rows and used + row_cost > total_limit:
                    break
                rows.append(row)
                used += row_cost
            return rows

        stage_skeletons = framework.get("stage_skeleton", [])
        stage_skeletons = stage_skeletons if isinstance(stage_skeletons, list) else []
        skeleton_by_id = {}
        for skeleton in stage_skeletons:
            if not isinstance(skeleton, dict):
                continue
            skeleton_id = _canonical_chapter_plan_stage_id(skeleton.get("id", ""))
            if skeleton_id:
                skeleton_by_id[skeleton_id] = skeleton

        stage_fields = (
            "id", "name", "start_chapter", "end_chapter", "summary", "main_conflict",
            "relationship_changes", "world_reveals", "turning_points",
            "end_state", "entry_state", "exit_state", "carry_over", "ordered_events",
        )
        stage_plan = []
        for item in framework.get("stage_plan", []) if isinstance(framework.get("stage_plan"), list) else []:
            if not isinstance(item, dict):
                continue
            row = {}
            stage_id = _canonical_chapter_plan_stage_id(item.get("id", ""))
            skeleton = skeleton_by_id.get(stage_id, {})
            for key in stage_fields:
                value = item.get(key, "")
                if value in (None, "", [], {}) and isinstance(skeleton, dict):
                    value = skeleton.get(key, "")
                if key == "ordered_events":
                    events = []
                    for event_index, event in enumerate(
                        value if isinstance(value, list) else [], 1
                    ):
                        if not isinstance(event, dict):
                            continue
                        event_row = {
                            "n": event_index,
                            "allowed_chapters": event.get("allowed_chapters", []),
                            "references": event.get("references", []),
                            "preconditions": event.get("preconditions", []),
                            "event": self._chapter_plan_clip_text(event.get("event", ""), 900),
                            "result": self._chapter_plan_clip_text(event.get("result", ""), 700),
                            "state_delta": event.get("state_delta", {}),
                        }
                        events.append(event_row)
                    if events:
                        row[key] = events
                    continue
                if isinstance(value, list):
                    values = [
                        self._chapter_plan_clip_text(entry, 700)
                        for entry in value
                        if str(entry or "").strip()
                    ]
                    if values:
                        row[key] = values
                else:
                    text = self._chapter_plan_clip_text(value, 1600)
                    if text:
                        row[key] = text
            if row:
                stage_plan.append(row)

        foundation = framework.get("chapter_plan_foundation", {})
        foundation = foundation if isinstance(foundation, dict) else {}
        bible = framework.get("bible", {})
        bible = bible if isinstance(bible, dict) else {}
        core_motive = self._chapter_plan_clip_text(
            foundation.get("core_motive", "")
            or framework.get("core_motive", "")
            or bible.get("main_conflict", "")
            or premise.get("core_motive", "")
            or premise.get("main_line", ""),
            2200,
        )

        result = {
            "source": "creation_wizard",
            "novel_name": self._chapter_plan_clip_text(framework.get("novel_name", ""), 300),
            "premise": premise_context,
            "core_motive": core_motive,
            "bible": self._chapter_plan_clip_text(
                json.dumps(framework.get("bible", {}), ensure_ascii=False, separators=(",", ":")), 6500
            ),
            "world_rules": self._chapter_plan_clip_text(
                json.dumps(framework.get("world_rules", {}), ensure_ascii=False, separators=(",", ":")), 6500
            ),
            "characters": compact_records(
                framework.get("characters", []),
                ("name", "role", "goal", "secret", "personality", "voice", "notes"),
                item_limit=700,
                total_limit=9000,
            ),
            "lore": compact_records(
                framework.get("lore", []),
                ("name", "type", "description", "story_known"),
                item_limit=750,
                total_limit=11000,
            ),
            "foreshadows": compact_records(
                framework.get("foreshadows", []),
                ("code", "name", "status", "setup_chapter", "payoff_chapter", "description", "revealed", "remaining_secret"),
                item_limit=700,
                total_limit=9000,
            ),
            "book_contract": deepcopy(framework.get("book_contract", {})),
            "chapter_plan_note": self._chapter_plan_clip_text(
                framework.get("chapter_plan_note", ""), 2400
            ),
            "stage_plan": stage_plan,
            "total_words": framework.get("total_words", 0),
            "average_chapter_words": framework.get("average_chapter_words", 0),
        }
        if not (
            result["novel_name"]
            or result["premise"]
            or result["chapter_plan_note"]
            or result["stage_plan"]
        ):
            return {}
        return result

    def _chapter_plan_scope_creation_framework_context(
        self,
        value,
        reference_start_index=None,
        reference_end_index=None,
    ):
        """只给章节规划发送当前阶段的完整事件，其他阶段只保留边界索引。"""
        source = deepcopy(value if isinstance(value, dict) else {})
        stages = source.get("stage_plan", [])
        stages = stages if isinstance(stages, list) else []
        try:
            start_index = int(reference_start_index or 0)
            end_index = int(reference_end_index or 0)
        except (TypeError, ValueError):
            start_index, end_index = 0, 0
        if start_index <= 0 or end_index < start_index:
            return source

        stage_index = []
        scoped_stages = []
        for item in stages:
            if not isinstance(item, dict):
                continue
            try:
                stage_start = int(item.get("start_chapter", 0) or 0)
                stage_end = int(item.get("end_chapter", 0) or 0)
            except (TypeError, ValueError):
                stage_start, stage_end = 0, 0
            stage_id = _canonical_chapter_plan_stage_id(item.get("id", ""))
            stage_index.append({
                "id": stage_id,
                "name": self._chapter_plan_clip_text(item.get("name", ""), 120),
                "start_chapter": stage_start,
                "end_chapter": stage_end,
            })
            if stage_start <= end_index and stage_end >= start_index:
                scoped_stages.append(deepcopy(item))
        source["stage_index"] = stage_index
        source["stage_plan"] = scoped_stages
        return source

    def _chapter_plan_creation_transport_framework(
        self,
        value,
        reference_start_index=None,
        reference_end_index=None,
    ):
        """构造向导章节规划专用的单份阶段事实包。"""
        source = self._chapter_plan_scope_creation_framework_context(
            value,
            reference_start_index,
            reference_end_index,
        )
        if str(source.get("source", "") or "").strip() == "creation_wizard":
            # 最新的人物、设定和伏笔会在请求顶层发送。这里仅保留当前阶段
            # 的故事事实；引用、前置条件和状态差分不是章节请求的执行字段，
            # 再次发送只会让章节规划同时面对两套节点协议。
            for key in (
                "bible", "world_rules", "characters", "lore", "foreshadows",
                "book_contract",
            ):
                source.pop(key, None)
            compact_stages = []
            for stage in source.get("stage_plan", []) if isinstance(source.get("stage_plan"), list) else []:
                if not isinstance(stage, dict):
                    continue
                compact_stage = {}
                for key in (
                    "id", "name", "start_chapter", "end_chapter", "summary",
                    "end_state", "entry_state", "exit_state",
                ):
                    value = stage.get(key, "")
                    if value not in (None, "", [], {}):
                        compact_stage[key] = value
                events = []
                for event_index, event in enumerate(
                    stage.get("ordered_events", [])
                    if isinstance(stage.get("ordered_events"), list) else [],
                    1,
                ):
                    if not isinstance(event, dict):
                        continue
                    event_text = self._chapter_plan_clip_text(event.get("event", ""), 760)
                    result_text = self._chapter_plan_clip_text(event.get("result", ""), 520)
                    if not event_text and not result_text:
                        continue
                    event_row = {
                        "n": event_index,
                        "event": event_text,
                        "result": result_text,
                    }
                    # Keep the event's original chapter window beside its
                    # text. The batch schedule is authoritative, but carrying
                    # this small range here avoids making the model join two
                    # separate structures by event order.
                    allowed = event.get("allowed_chapters", [])
                    if isinstance(allowed, (list, tuple)) and len(allowed) >= 2:
                        try:
                            allowed_start = int(allowed[0])
                            allowed_end = int(allowed[1])
                        except (TypeError, ValueError):
                            allowed_start = allowed_end = 0
                        if allowed_start > 0 and allowed_end >= allowed_start:
                            if reference_start_index is not None:
                                allowed_start = max(
                                    allowed_start, int(reference_start_index or 0)
                                )
                            if reference_end_index is not None:
                                allowed_end = min(
                                    allowed_end, int(reference_end_index or 0)
                                )
                            if allowed_end >= allowed_start:
                                event_row["allowed_chapters"] = [
                                    allowed_start, allowed_end
                                ]
                    events.append(event_row)
                if events:
                    compact_stage["ordered_events"] = events
                if compact_stage:
                    compact_stages.append(compact_stage)
            source["stage_plan"] = compact_stages
            # A batch request only needs the active stage. Future stage
            # boundaries are already known by the application and tend to
            # invite the model to continue past the requested endpoint.
            active_stage_ids = {
                _canonical_chapter_plan_stage_id(stage.get("id", ""))
                for stage in compact_stages
                if isinstance(stage, dict)
            }
            if active_stage_ids and isinstance(source.get("stage_index"), list):
                source["stage_index"] = [
                    item
                    for item in source["stage_index"]
                    if isinstance(item, dict)
                    and _canonical_chapter_plan_stage_id(item.get("id", ""))
                    in active_stage_ids
                ]
            source.pop("total_words", None)
            source.pop("average_chapter_words", None)
            if not str(source.get("chapter_plan_note", "") or "").strip():
                source.pop("chapter_plan_note", None)
        return source

    def _chapter_plan_compact_creation_framework_context(self, value, total_limit):
        source = deepcopy(value if isinstance(value, dict) else {})
        total_limit = max(1200, int(total_limit or 1200))

        def compact_stage(item, field_limit):
            if not isinstance(item, dict):
                return {}
            row = {}
            for key in (
                "name", "start_chapter", "end_chapter", "summary",
                "main_conflict", "relationship_changes", "world_reveals",
                "turning_points", "end_state", "entry_state", "exit_state",
                "ordered_events",
            ):
                value = item.get(key, "")
                if key == "ordered_events":
                    events = []
                    for event_index, event in enumerate(value if isinstance(value, list) else [], 1):
                        if not isinstance(event, dict):
                            continue
                        events.append({
                            "n": event_index,
                            "allowed_chapters": event.get("allowed_chapters", []),
                            "references": event.get("references", []),
                            "event": self._chapter_plan_clip_text(event.get("event", ""), field_limit),
                            "result": self._chapter_plan_clip_text(event.get("result", ""), field_limit),
                            "state_delta": event.get("state_delta", {}),
                        })
                    if events:
                        row[key] = events
                    continue
                if isinstance(value, list):
                    values = [
                        self._chapter_plan_clip_text(entry, field_limit)
                        for entry in value
                        if str(entry or "").strip()
                    ]
                    if values:
                        row[key] = values
                else:
                    text = self._chapter_plan_clip_text(value, field_limit)
                    if text:
                        row[key] = text
            return row

        stages = source.get("stage_plan", [])
        stages = stages if isinstance(stages, list) else []
        stage_limit = max(80, min(1400, total_limit // max(1, len(stages) * 4)))
        source["stage_plan"] = [
            row for row in (compact_stage(item, stage_limit) for item in stages) if row
        ]
        source["chapter_plan_note"] = self._chapter_plan_clip_text(
            source.get("chapter_plan_note", ""),
            max(240, min(2400, total_limit // 8)),
        )
        for key, limit in (
            ("story_synopsis", 2600),
            ("bible", 3200),
            ("world_rules", 3200),
        ):
            source[key] = self._chapter_plan_clip_text(source.get(key, ""), limit)
        if isinstance(source.get("book_contract"), dict):
            source["book_contract"] = {
                key: [self._chapter_plan_clip_text(item, 280) for item in value[:24]]
                for key, value in source["book_contract"].items()
                if isinstance(value, list) and value
            }
        premise = source.get("premise", {})
        if isinstance(premise, dict):
            source["premise"] = {
                key: (
                    [
                        self._chapter_plan_clip_text(item, max(80, stage_limit))
                        for item in value
                        if str(item or "").strip()
                    ][:20]
                    if isinstance(value, list)
                    else self._chapter_plan_clip_text(value, max(120, stage_limit))
                )
                for key, value in premise.items()
                if value not in (None, "", [], {})
            }
        rendered = json.dumps(source, ensure_ascii=False, indent=2)
        if len(rendered) <= total_limit:
            return source

        source["premise"] = {
            key: self._chapter_plan_clip_text(value, 180)
            for key, value in source.get("premise", {}).items()
            if not isinstance(value, list)
        }
        compacted_stages = []
        for row in source.get("stage_plan", []):
            if not isinstance(row, dict):
                continue
            compacted = {
                key: row.get(key, "")
                for key in ("name", "start_chapter", "end_chapter", "summary", "main_conflict", "end_state")
                if row.get(key, "") not in (None, "")
            }
            events = []
            for event_index, event in enumerate(row.get("ordered_events", []), 1):
                if not isinstance(event, dict):
                    continue
                event_text = self._chapter_plan_clip_text(event.get("event", ""), 420)
                result_text = self._chapter_plan_clip_text(event.get("result", ""), 280)
                if not event_text and not result_text:
                    continue
                events.append({
                    "n": event.get("n", event_index),
                    "allowed_chapters": event.get("allowed_chapters", []),
                    "event": event_text,
                    "result": result_text,
                })
            if events:
                compacted["ordered_events"] = events
            if compacted:
                compacted_stages.append(compacted)
        source["stage_plan"] = compacted_stages
        return source

    def _chapter_plan_project_context(
        self,
        target_words,
        average_chapter_words,
        total_chapter_count,
        requested_chapter_count,
        existing_count_override=None,
        reference_start_index=None,
        reference_end_index=None,
        context_mode="master",
        extra_payload=None,
    ):
        creative_intent_contract = _normalize_creative_intent_contract(
            self.current_project.get("creative_intent_contract", {})
            if isinstance(getattr(self, "current_project", None), dict) else {}
        )
        project = self._ai_project_snapshot()
        meta = project.get("meta", {}) if isinstance(project.get("meta", {}), dict) else {}
        chapters = project.get("chapters", [])
        chapters = chapters if isinstance(chapters, list) else []
        existing_chapter_records = []
        for index, chap in enumerate(chapters, 1):
            if not isinstance(chap, dict):
                continue
            existing_chapter_records.append({
                "index": index,
                "title": self._chapter_plan_clip_text(chap.get("title", ""), 80),
                "status": self._chapter_plan_clip_text(chap.get("status", ""), 40),
                "target_words": self._chapter_plan_clip_text(chap.get("draft_words", ""), 40),
                "outline": self._chapter_plan_clip_text(chap.get("outline", ""), 1200),
                "summary": self._chapter_plan_clip_text(chap.get("summary", ""), 900),
                "key_facts": self._chapter_plan_clip_text(chap.get("key_facts", ""), 1200),
                "linked_characters": _normalize_name_list(chap.get("linked_characters", [])),
                "body_tail": self._chapter_plan_clip_text(chap.get("text", ""), 900, keep_tail=True),
            })
        context_existing_count = (
            max(0, int(existing_count_override or 0))
            if existing_count_override is not None else len(chapters)
        )
        batch_mode = context_mode == "batch"
        # Titles are a small cross-batch identity index. Keep the complete list
        # separate from detailed chapter context so compression never removes
        # the information needed to avoid reusing an earlier title.
        used_chapter_titles = []
        used_title_indexes = set()

        def add_used_title(index, title):
            title = str(title or "").strip()
            if not title:
                return
            try:
                index = int(index or 0)
            except (TypeError, ValueError):
                index = 0
            if index <= 0 or index in used_title_indexes:
                return
            used_title_indexes.add(index)
            used_chapter_titles.append({"index": index, "title": title})

        for index, chapter in enumerate(chapters, 1):
            if isinstance(chapter, dict):
                add_used_title(index, chapter.get("title", ""))
        if batch_mode and isinstance(extra_payload, dict):
            continuity = extra_payload.get("batch_continuity", {})
            if isinstance(continuity, dict):
                for item in continuity.get("planned_chapter_ledger", []):
                    if isinstance(item, dict):
                        add_used_title(item.get("index", 0), item.get("title", ""))
        used_chapter_titles.sort(key=lambda item: item["index"])
        try:
            batch_is_final = bool(
                batch_mode
                and reference_end_index is not None
                and int(reference_end_index or 0) >= int(total_chapter_count or 0)
            )
        except (TypeError, ValueError):
            batch_is_final = False
        terminal_bounds = _terminal_window_bounds(total_chapter_count)
        terminal_batch_overlap = None
        if terminal_bounds and reference_start_index is not None and reference_end_index is not None:
            try:
                overlap_start = max(int(reference_start_index), terminal_bounds[0])
                overlap_end = min(int(reference_end_index), terminal_bounds[1])
            except (TypeError, ValueError):
                overlap_start, overlap_end = 0, -1
            if overlap_start <= overlap_end:
                terminal_batch_overlap = (overlap_start, overlap_end)
        batch_creative_intent_contract = deepcopy(creative_intent_contract)
        if batch_mode and not batch_is_final and not terminal_batch_overlap:
            # The concrete ending belongs to the final stage. Sending it to
            # an earlier batch makes a model close the whole novel as soon as
            # the current stage reaches its local climax.
            batch_creative_intent_contract.pop("ending_boundaries", None)
        detailed_existing_count = 10 if batch_mode else 16
        if len(existing_chapter_records) > detailed_existing_count:
            existing_chapters = existing_chapter_records[-detailed_existing_count:]
            existing_chapter_index = _compact_volume_handoff_records(
                existing_chapter_records,
                ("index", "title", "status", "target_words"),
                {"index": 20, "title": 80, "status": 40, "target_words": 30},
                9000 if batch_mode else 14000,
                minimal_fields=("index", "title", "status"),
            )
        else:
            existing_chapters = existing_chapter_records
            existing_chapter_index = []
        materials_limit = 3200 if batch_mode else 5000
        character_total_limit = 10000 if batch_mode else 14000
        setting_total_limit = 12000 if batch_mode else 16000
        foreshadow_total_limit = 10000 if batch_mode else 14000
        wizard_framework = self._chapter_plan_creation_framework_context(project)
        creation_wizard_source = bool(wizard_framework)
        if creation_wizard_source:
            wizard_framework = self._chapter_plan_creation_transport_framework(
                wizard_framework,
                reference_start_index=reference_start_index,
                reference_end_index=reference_end_index,
            )
        wizard_core_motive = str(
            wizard_framework.get("core_motive", "")
            if isinstance(wizard_framework, dict) else ""
        ).strip()
        if wizard_core_motive and not str(batch_creative_intent_contract.get("core_motive", "") or "").strip():
            batch_creative_intent_contract["core_motive"] = wizard_core_motive
        foreshadow_items = project.get("foreshadow_items", [])
        if creation_wizard_source:
            foreshadow_items = self._chapter_plan_scoped_foreshadows(
                foreshadow_items,
                reference_start_index,
                reference_end_index,
            )
        raw_profile = project.get("narrative_strategy_profile", {})
        raw_profile = raw_profile if isinstance(raw_profile, dict) else {}
        planning_profile = {
            key: deepcopy(raw_profile.get(key))
                for key in (
                    "version", "audience_direction", "genre_world", "core_reader_promise", "core_motive",
                    "primary_story_engine", "secondary_story_engine", "story_direction",
                )
            if raw_profile.get(key) not in (None, "", [], {})
        }
        if wizard_core_motive and "core_motive" not in planning_profile:
            planning_profile["core_motive"] = wizard_core_motive
        payload = {
            "task": (
                "生成可以追加到当前项目章节列表的长篇章节规划。"
                "如果已有章节，请从已有章节之后继续规划，保持前文事实、节奏和伏笔连续。"
            ),
            "planning_contract": {
                "priority": "用户已确认创作意图（若有） > 用户原始框架具体章段 > 全书分卷/阶段目标 > 通用宏观节奏",
                "source_stage_rule": (
                    "原框架阶段决定内容方向，必须持续到其绝对结束章号；"
                    "通用前10%/中70%/后20%只控制节奏，不能触发题材切换。"
                ),
                "stage_boundary_rule": "当前阶段的事件、人物、关系和后果在本阶段自然展开，下一阶段承接上一阶段留下的变化继续发展。",
                "material_rule": "项目资料是只读事实底稿，不重新生成，不把背景资料自动变成章节任务。",
                "core_motive_rule": (
                    "核心动机必须作为具体因果主线执行：主角为了完成明确目标主动行动，遇到阻碍并付出代价，"
                    "当前结果再打开下一道具体目标；不能只写主角被动不断遇到新事件。"
                ),
                "line_field_boundary": (
                    "core_motive是唯一主线；primary_line、core_mainline和primary_story_engine只是兼容别名或执行说明，"
                    "阶段main_conflict只写本阶段阻碍核心动机的问题，不得另起总目标。"
                ),
            },
            "entity_naming_guidance": _entity_naming_guidance(project),
            "target": {
                "target_words": int(target_words or 0),
                "average_chapter_words": int(average_chapter_words or 0),
                "estimated_total_chapters": int(total_chapter_count or 0),
                "existing_chapter_count": context_existing_count,
                "requested_new_chapters": int(requested_chapter_count or 0),
                "terminal_window": {
                    "start_chapter": terminal_bounds[0],
                    "end_chapter": terminal_bounds[1],
                    "chapter_count": terminal_bounds[1] - terminal_bounds[0] + 1,
                    "batch_overlap": list(terminal_batch_overlap)
                    if terminal_batch_overlap else [],
                } if terminal_bounds else {},
                "macro_pacing_rules": [
                    {
                        "range": "前10%",
                        "stage": "强钩子阶段",
                        "rule": "尽早让读者看见人物处境、主线承诺与风险；不等于每章使用同一种爆点。",
                    },
                    {
                        "range": "中间70%",
                        "stage": "主线扩展阶段",
                        "rule": "在当前主线内推进人物、关系、对抗与结果；允许不同章节以不同场景和节奏展开。",
                    },
                    {
                        "range": "后20%",
                        "stage": "收束升级阶段",
                        "rule": "减少无关新增，优先让既有主线与人物选择自然汇合；不把每章写成机械回收清单。",
                    },
                ],
            },
            "meta": {
                "title": meta.get("title", ""),
                "genre": meta.get("genre", ""),
                "style": meta.get("style", ""),
                "pov": meta.get("pov", ""),
                "target_words": meta.get("target_words", ""),
                "status": meta.get("status", ""),
                # The wizard framework already carries the selected premise;
                # sending meta.premise as well repeats the public synopsis.
                "premise": (
                    ""
                    if creation_wizard_source
                    else self._chapter_plan_clip_text(meta.get("premise", ""), 3000)
                ),
            },
            "narrative_strategy_profile": planning_profile,
            "creative_intent_contract": batch_creative_intent_contract,
            "wizard_framework": wizard_framework,
            "used_chapter_titles": used_chapter_titles,
            "project_materials": {
                "bible": self._chapter_plan_clip_text(project.get("bible", ""), materials_limit),
                "world_rules": self._chapter_plan_clip_text(project.get("world_rules", ""), max(2600, materials_limit - 400)),
                "timeline": (
                    ""
                    if creation_wizard_source
                    else self._chapter_plan_clip_text(project.get("timeline", ""), materials_limit, keep_tail=True)
                ),
                "summary": self._chapter_plan_clip_text(project.get("summary", ""), materials_limit, keep_tail=True),
            },
            "characters": self._chapter_plan_records(
                project.get("characters", []),
                ("name", "role", "goal", "secret", "personality", "voice", "notes"),
                120,
                700,
                keep_tail_fields={"notes"},
                total_limit=character_total_limit,
                minimal_fields=("name", "role", "goal"),
            ),
            "settings": self._chapter_plan_records(
                project.get("lore", []),
                ("name", "type", "description"),
                160,
                900,
                keep_tail_fields={"description"},
                total_limit=setting_total_limit,
                minimal_fields=("name", "type"),
            ),
            "foreshadows": self._chapter_plan_records(
                foreshadow_items,
                (
                    "name", "type", "status", "setup_chapter", "payoff_chapter",
                    "description", "revealed", "remaining_secret",
                ),
                160,
                800,
                keep_tail_fields={"description", "revealed", "remaining_secret"},
                total_limit=foreshadow_total_limit,
                minimal_fields=("name", "type", "description"),
            ),
            "existing_chapters": existing_chapters,
        }
        opening_handoff = str(project.get("volume_opening_handoff_context", "") or "").strip()
        planning_starts_at_first_chapter = (
            context_existing_count == 0
            and (reference_start_index in (None, 1))
        )
        if opening_handoff and planning_starts_at_first_chapter:
            payload["volume_opening_continuity"] = opening_handoff
        current_continuation = _normalize_series_continuation(
            self.current_project.get("series_continuation", {})
            if isinstance(getattr(self, "current_project", None), dict) else {}
        )
        current_handoff = current_continuation.get("handoff", {})
        current_handoff = current_handoff if isinstance(current_handoff, dict) else {}
        continuity_anchors = _compact_volume_continuity_anchors(
            current_handoff.get("continuity_anchors", []), 3000
        )
        if continuity_anchors:
            payload["cross_volume_continuity"] = {
                "purpose": "上一卷已发生的稳定事实，仅供本卷章节规划校准；不是本章剧情任务或硬规则。",
                "anchors": continuity_anchors,
            }
        if existing_chapter_index:
            payload["existing_chapter_index"] = existing_chapter_index
        # A creation-wizard project already has its own confirmed stage plan.
        # Never let an old imported-framework reference leak into this request:
        # it uses a different chapter/event protocol and can make the model
        # plan the same range twice.
        imported_reference = (
            {}
            if creation_wizard_source
            else self._chapter_plan_reference_context(
                reference_start_index,
                reference_end_index,
                target_words=target_words,
                average_chapter_words=average_chapter_words,
                total_chapter_count=total_chapter_count,
            )
        )
        if imported_reference:
            payload["imported_chapter_plan_reference"] = imported_reference
        analysis = {} if creation_wizard_source else self._framework_ai_analysis()
        if analysis:
            payload["framework_analysis"] = analysis
            if (
                isinstance(imported_reference, dict)
                and str(imported_reference.get("location_status", "") or "").strip().lower()
                == "pending"
            ):
                source = project.get("imported_framework_source", {})
                source_text = source.get("text", "") if isinstance(source, dict) else ""
                if source_text:
                    payload["unresolved_framework_source"] = _framework_numbered_source(source_text)
        elif context_mode == "master":
            source = project.get("imported_framework_source", {})
            if isinstance(source, dict) and source.get("text"):
                payload["original_framework_text"] = source["text"]
        if isinstance(extra_payload, dict) and extra_payload:
            payload.update(deepcopy(extra_payload))
        if terminal_batch_overlap:
            terminal_batch_guidance = (
                "当前批次与全书最后5章收尾窗口有交集：每章仍要留下可承接的具体结果，"
                "但下一章只能继续落实窗口内已经安排的直接后果、行动或关系变化；"
                "不得用新的主要任务、主要敌人、未知信息或等待回答的悬念制造连载钩子。\n"
            )
            terminal_transition_guidance = (
                "跨章边界必须明确：上一章可以停在已经发生的触发或结果，下一章从它造成的新反应、"
                "新结果或关系变化开始；收尾窗口内不得新增必须由后续章节回答的主线任务或悬念。"
                "不得把同一句对白、同一声响、同一动作落点或同一结论同时写进前章结尾和后章开头。\n\n"
            )
            terminal_node_progression_guidance = (
                "当前节点解决或暂时解决后，在收尾窗口内只落实已经安排的直接结果、关系变化或主角处境落点；"
                "不另开下一道主线目标、主要敌人或必须由后续章节回答的任务。不能把章节写成主角不断被动遭遇事情的流水账。\n\n"
            )
        else:
            terminal_batch_guidance = (
                "每章都要留下可承接的具体结果，下一章从新反应、新结果或新阻力继续。\n"
            )
            terminal_transition_guidance = (
                "跨章边界必须明确：上一章可以停在触发点，但下一章必须从触发后的新反应、新结果或新阻力开始；"
                "不得把同一句对白、同一声响、同一动作落点或同一结论同时写进前章结尾钩子和后章开头。"
                "前章ending_hook负责留下已发布的触发，后章outline只需写触发后可能出现的新增变量，不要重复前章落点。\n\n"
            )
            terminal_node_progression_guidance = (
                "当前节点解决或暂时解决后，必须留下下一道可执行的具体目标、资源缺口、关系选择、"
                "认知真相或更高代价。不能把章节写成主角不断被动遭遇事情的流水账。\n\n"
            )
        core_motive_guidance = (
            "【核心动机与收尾窗口】核心动机仍是本项目唯一执行主线；收尾窗口内只把已经安排的目标、阻碍、"
            "代价和关系变化落实为具体结果，不再打开下一道需要后续章节回答的主线目标。\n"
            if terminal_batch_overlap else
            _core_motive_progression_guidance()
        )
        instruction_prefix = (
            "请根据以下 JSON 项目档案生成章节规划。只规划 requested_new_chapters 指定数量的新章节；"
            "不要重写已有章节，不要输出正文。"
            "target.terminal_window只表示最后5章的内容收束范围，不改变requested_new_chapters、当前批次范围、阶段边界或返回对象数量。"
            "必须先按 creative_intent_contract、planning_contract 和 imported_chapter_plan_reference 决定内容方向；"
            "再参考 target.macro_pacing_rules 安排宏观节奏。宏观节奏不得覆盖原框架阶段。\n\n"
            "若存在 imported_chapter_plan_reference，chapters是按绝对章号执行的明确章节约束；"
            "stages.events是阶段有序剧情节点，不得把事件序号直接当作章号。"
            "如果imported_chapter_plan_reference.location_status为pending，"
            "请根据unresolved_framework_source为当前批次补充每章source_location的起止L行号和极短anchor；"
            "只返回位置，不要抄写原文。程序会用原始框架恢复细纲，定位失败不能改判为内容缺失。\n"
            "每章用source_event_ids列出本章承载的节点ID；一章可承载多个连续节点，扩展章可用空数组。"
            "每个节点只能使用一次、必须位于所属阶段章号范围内并保持原顺序；阶段结束前必须全部覆盖。"
            "凡引用节点，outline必须清楚落实其语义，可以自然改写，不要机械逐字粘贴。"
            "当前绝对章号对应的阶段和章节字数由程序根据输入资料确定，不要在返回 JSON 中重复输出source_stage、narrative_stage或target_words。\n\n"
            "若narrative_strategy_profile为空，先从项目资料推导受众方向、题材世界、主副叙事发动机、读者承诺、"
            "情绪方向和节奏原则；按当前项目已经确认的题材与风格形成阅读感，后续规划只能使用这些原则，"
            "不得把它们展开成固定场景轮换表或逐章任务。\n\n"
            "若creative_intent_contract非空，它是用户已确认的最高优先级创作方向：主线和结局边界不得被交接资料、"
            "圣经中的旧剧情权重、原框架辅助线或AI重新推断的narrative_strategy_profile替换；辅助线只能推动主线发生变化。\n\n"
            "core_motive是本项目唯一的具体执行主线：它回答主角最终必须完成什么。primary_line、core_mainline、"
            "primary_story_engine和Bible.main_conflict在新项目中只是同一主线的兼容表达或执行说明；阶段main_conflict只表示"
            "当前阶段阻碍核心动机的具体问题、门槛或代价，不能被当成另一条全书主线。theme只提供价值命题，不承担章节任务。\n\n"
            "如果存在wizard_framework，它与故事简介、小说圣经、世界规则、人物、设定和伏笔共同组成向导已经确认的完整底稿；"
            "故事底盘和十万字阶段规划已经在向导中完成，这里不要再次生成新的总规划，只写当前批次的具体章节。\n\n"
            "注意：结构字段负责守住本章主线、阶段、事件和结尾边界；outline负责用当前小说自己的口吻讲述这一章，"
            "这里只表示事实必须贴合当前题材和人物，不要求生成另一份自然语言版规划；outline同时保留本章给正文扩写使用的具体故事事实。"
            "章节规划可以使用清楚、稳定、便于执行的结构化表达，不需要像发布简介，也不需要单独生成另一份自然语言版规划。"
            "outline直接写本章真正需要给正文继承的具体故事事实；人物、地点、行动、阻力、结果或章末变化按本章需要自然取用，"
            "不要求每章按同一顺序全部出现，也不要为了凑齐项目补写没有发生的内容。不得出现字段名、内部编号、JSON、代码字符、规划过程或工作流程。"
            "used_chapter_titles列出已经使用过的章节标题；新章节标题不得与其中任何标题重复，也不得与本批次其他新章节标题重复。"
            "生成前逐项核对标题，重复时必须改成能对应本章具体事件、人物行动或结果的新标题。\n\n"
            "不要像编辑解释本章功能，不要写‘推动剧情、关系推进、制造悬念、完成任务、阶段作用’等空泛任务词，"
            "不要解释本章意义、主题、节奏、主线、人物弧线或读者效果。"
            + _procedural_plot_guard_guidance()
            + "章节不能写成案卷、办案报告、审查流程或资料处理；不得让抽象说明、流程往来或结论宣告代替人物在现场的行动和冲突。"
            "输入资料里的抽象总结只作为事实参考，要改写成具体人物、地点、动作、阻力、结果和状态变化；"
            "人物认知变化必须落到看见、听见、当场反应、决定和现实后果。不要写‘章末留下悬念’或‘读者会继续追问’，直接写章末发生的具体事情。"
            "每章都要让人物在具体场景中遇到阻力并采取行动；随着章节推进，优先安排人物对抗、关系变化、利益争夺、环境压力、能力试探或突发后果，让读者看到事情正在发生，而不是看到一份事情说明。"
            "不要把正文细拆成必须完成的动作、对白、程序或固定拍点；结构字段只负责守住事实和顺序，正文扩写时再转换为自然的网络小说叙述语言。"
            "本章相关资料若自然出现在返回内容中，保留其原有语义，不要把它们改写成固定动作清单；"
            "伏笔由扩写正文时根据当时的开放伏笔动态调度。\n\n"
            "如果存在cross_volume_continuity，其中的anchors只是上一卷事实参考：用于避免人物关系、生活分工和既有习惯被写反，"
            "不要逐条复述、不要把它们改写成章节任务，也不要在本章规划中强行安排它们。\n\n"
            + terminal_transition_guidance
            + core_motive_guidance
            + "\n"
        )
        if creation_wizard_source:
            # 向导项目使用自己的章节协议。导入项目的通用提示会要求模型
            # 逐章维护事件索引，这与向导工作线程的紧凑输出协议相冲突；
            # 这里直接替换整段请求说明，而不是在末尾继续追加另一套规则。
            instruction_prefix = (
                "请根据以下 JSON 项目档案生成向导已经确认的当前阶段章节规划。"
                "只生成 requested_new_chapters 指定数量的新章节，不重写已有章节，不输出正文。"
                "target.terminal_window只表示最后5章的内容收束范围，不改变requested_new_chapters、当前阶段边界或返回对象数量。"
                "故事简介、小说圣经、世界规则、人物、设定、伏笔和当前阶段资料共同构成只读底稿；"
                "它们提供事实和边界，本次只把当前阶段继续落实到具体章节。\n\n"
                "wizard_framework.stage_plan 只包含当前阶段的阶段事实和有序剧情节点；"
                "batch_continuity.locked_node_schedule 已由程序锁定节点可以落入的章节范围。"
                "按节点的既定顺序安排故事，不改变当前阶段边界，不把下一阶段内容提前写入当前阶段。"
                "节点编号和落点只供你理解，不要把它们写进返回内容，也不要为节点另造章节。"
                "同一节点第一次发生时完成它的核心转折；如果一个节点覆盖数章，后续章节只写由它造成的新反应、新选择、新代价、新关系变化或新阻力，尽量不用固定清单式要求逐章重复节点。\n\n"
                "当前阶段只是全书核心动机链的一段，不是独立短篇。每章都要写清主角为了当前具体目标采取的行动、"
                "阻碍来自谁或什么、主角付出了什么代价、结果怎样改变主线；"
                + terminal_node_progression_guidance
                + "伏笔资料只列当前章节范围内已经出现或即将出现的线索；后续阶段的伏笔等到对应阶段再自然展开。\n\n"
                "本批次必须返回准确数量的章节，列表顺序就是章节顺序；不要返回章节号、阶段号、节点号或其它定位标签。"
                "章节名和 outline 是读者与正文作者会看到的内容：章节名从本章具体发生的事情、人物行动、现场冲突、关系变化或结果中自然命名，且不超过15个汉字；"
                "used_chapter_titles列出已经使用过的章节标题；新章节标题不得与其中任何标题重复，也不得与本批次其他新章节标题重复。"
                "生成前逐项核对标题，重复时必须改成能对应本章具体事件、人物行动或结果的新标题。\n\n"
                "outline 直接写本章真正需要给正文继承的具体故事事实；人物、地点、行动、阻力、结果或章末变化按本章需要自然取用，"
                "不要求每章按同一顺序全部出现，也不要为了凑齐项目补写没有发生的内容。"
                "outline 建议 250—380 字，保持事实密度，但不要写成字段说明、工作流程、编辑分析或另一份规划表。"
                "不要把阶段资料逐条复述成清单；让人物在具体场景里行动、碰撞、改变关系或承担后果。"
                "当前题材和人物关系决定冲突的形状，不能用固定场景轮换或固定拍点替代故事发展。\n\n"
                "创作意图、阶段边界、人物关系和结尾方向已经确认，优先沿用它们；"
                "宏观节奏只作参考，不新增全书总规划，不提前解释后续阶段。"
                + terminal_batch_guidance
                + "entity_naming_guidance 是当前项目的正式称谓和实体关系边界，优先于模型自行压缩出的简称；"
                "涉及人物集合、组织集合和势力集合时，必须保留实体类型，不要把人数简称写成组织名称。\n"
                + _story_conflict_pacing_guidance()
                + core_motive_guidance
                + _procedural_plot_guard_guidance()
                + "状态变化要落到人物正在经历的场景、行动和后果，不把同一句状态连续复制到多章。"
                "章节标题和提纲都使用具体、好读、能看见人物与现场的表达；不写策划术语、抽象形容、办案式说明或编辑式总结。\n"
                + "只输出一个合法 JSON 对象，结构为 {\"c\":[{\"t\":\"章节名\",\"o\":\"本章具体故事提纲\",\"p\":[]}]}；"
                "列表数量必须严格等于本批次要求，p 只列本章自然涉及的主要人物，没有则为空数组。"
            )
        return self._chapter_plan_bounded_context(
            instruction_prefix,
            payload,
            context_mode=context_mode,
        )

    def _format_chapter_plan_preview(self, plan):
        plan = plan if isinstance(plan, dict) else {}
        chapters = plan.get("chapters", [])
        chapters = chapters if isinstance(chapters, list) else []
        lines = [
            "章节规划预览",
            f"目标总字数：约{int(plan.get('target_words', 0) or 0)}字",
            f"单章目标：约{int(plan.get('average_chapter_words', 0) or 0)}字",
            f"本次生成：{len(chapters)}章",
        ]
        summary = str(plan.get("summary", "") or "").strip()
        if summary:
            lines.extend(["", "阶段规划摘要：", summary])
        for fallback_index, item in enumerate(chapters, 1):
            if not isinstance(item, dict):
                continue
            index = item.get("index", fallback_index)
            title = str(item.get("title", "") or f"章节 {index}").strip()
            target_words = str(item.get("target_words", "") or "").strip()
            heading = f"第{index}章 {title}"
            if target_words:
                heading += f"（约{target_words}字）"
            lines.extend(["", heading])
            for label, key in (
                ("所属阶段", "narrative_stage"),
                ("原框架阶段", "source_stage"),
                ("本章主导线", "dominant_line"),
            ):
                value = str(item.get(key, "") or "").strip()
                if value:
                    lines.append(f"{label}：{value}")
            outline = _strip_volume_handoff_outline_metadata(
                _strip_static_foreshadow_outline_fields(item.get("outline", ""))
            )
            if outline:
                lines.append(outline)
            lines.extend(self._chapter_plan_structured_blocks(item))
            lines.extend(self._chapter_plan_optional_blocks(item, outline))
            for label, key in (("相关人物", "characters"),):
                values = _normalize_name_list(item.get(key, []))
                if values:
                    lines.append(f"{label}：" + "、".join(values))
            ending_hook = str(item.get("ending_hook", "") or "").strip()
            if ending_hook:
                lines.append(f"结尾钩子：{ending_hook}")
        return "\n".join(lines).strip()

    @staticmethod
    def _chapter_plan_structured_blocks(item):
        """Render structured planning facts without exposing Python/JSON syntax."""
        item = item if isinstance(item, dict) else {}
        blocks = []

        def text_list(value):
            return [
                str(child or "").strip()
                for child in (value if isinstance(value, list) else [])
                if str(child or "").strip()
            ]

        def state_text(value):
            if not isinstance(value, dict):
                return ""
            parts = []
            location = str(value.get("location", "") or "").strip()
            characters = text_list(value.get("characters", []))
            known_facts = text_list(value.get("known_facts", []))
            if location:
                parts.append(f"地点：{location}")
            if characters:
                parts.append("人物：" + "、".join(characters))
            if known_facts:
                parts.append("已知事实：" + "；".join(known_facts))
            return "；".join(parts)

        start_state = state_text(item.get("start_state", {}))
        if start_state:
            blocks.append(f"开始状态：{start_state}")

        scene_lines = []
        for scene in item.get("scene_chain", []) if isinstance(item.get("scene_chain"), list) else []:
            if not isinstance(scene, dict):
                continue
            parts = []
            location = str(scene.get("location", "") or "").strip()
            characters = text_list(scene.get("characters", []))
            trigger = str(scene.get("trigger", "") or "").strip()
            action = str(scene.get("action", "") or "").strip()
            result = str(scene.get("result", "") or "").strip()
            if location:
                parts.append(f"地点：{location}")
            if characters:
                parts.append("人物：" + "、".join(characters))
            if trigger:
                parts.append(f"触发：{trigger}")
            if action:
                parts.append(f"行动：{action}")
            if result:
                parts.append(f"结果：{result}")
            if parts:
                scene_lines.append(f"{len(scene_lines) + 1}. " + "；".join(parts))
        if scene_lines:
            blocks.append("场景推进：\n" + "\n".join(scene_lines))

        conflict = item.get("conflict", {})
        if isinstance(conflict, dict):
            parts = []
            source = str(conflict.get("source", "") or "").strip()
            pressure = str(conflict.get("pressure", "") or "").strip()
            result = str(conflict.get("result", "") or "").strip()
            if source:
                parts.append(f"冲突来源：{source}")
            if pressure:
                parts.append(f"现实压力：{pressure}")
            if result:
                parts.append(f"冲突结果：{result}")
            if parts:
                blocks.append("冲突：" + "；".join(parts))

        required_facts = text_list(item.get("required_facts", []))
        if required_facts:
            blocks.append("必须保留的事实：" + "；".join(required_facts))
        delta = item.get("continuity_delta", {})
        if isinstance(delta, dict):
            labels = (
                ("time_advance", "时间变化"),
                ("location_changes", "地点变化"),
                ("knowledge_changes", "认知变化"),
                ("relationship_changes", "关系变化"),
                ("object_changes", "物件变化"),
                ("new_open_threads", "新增问题"),
                ("closed_threads", "解决问题"),
            )
            changes = []
            for key, label in labels:
                value = delta.get(key)
                values = text_list(value) if isinstance(value, list) else []
                text = "；".join(values) if values else str(value or "").strip()
                if text:
                    changes.append(f"{label}：{text}")
            if changes:
                blocks.append("状态变化：" + "；".join(changes))

        ending_change = item.get("ending_change", {})
        if isinstance(ending_change, dict):
            change_type = str(ending_change.get("type", "") or "").strip()
            fact = str(ending_change.get("fact", "") or "").strip()
            if change_type or fact:
                text = "；".join(
                    part for part in (f"变化类型：{change_type}" if change_type else "", fact) if part
                )
                blocks.append(f"章末变化：{text}")
        return blocks

    @staticmethod
    def _chapter_plan_optional_blocks(item, existing_text=""):
        item = item if isinstance(item, dict) else {}
        existing_text = str(existing_text or "")
        blocks = []
        for key, label in _CHAPTER_PLAN_OPTIONAL_TEXT_FIELDS:
            raw_value = item.get(key, "")
            if isinstance(raw_value, (dict, list, tuple)):
                continue
            value = str(raw_value or "").strip()
            if value and value not in existing_text:
                blocks.append(f"{label}：{value}")
        for key, label in _CHAPTER_PLAN_OPTIONAL_LIST_FIELDS:
            values = [
                value for value in _normalize_name_list(item.get(key, []))
                if value and value not in existing_text
            ]
            if values:
                blocks.append(f"{label}：" + "、".join(values))
        return blocks

    def _chapter_plan_outline_for_item(self, item):
        item = item if isinstance(item, dict) else {}
        outline = str(item.get("outline", "") or "").strip()
        return _strip_volume_handoff_outline_metadata(
            _strip_static_foreshadow_outline_fields(outline)
        )

    @staticmethod
    def _chapter_plan_apply_imported_outline(chapter, explicit_item):
        """Apply the model's same-call direct-use decision to one chapter."""
        chapter = deepcopy(chapter) if isinstance(chapter, dict) else {}
        explicit_item = explicit_item if isinstance(explicit_item, dict) else {}
        explicit_title = str(explicit_item.get("title", "") or "").strip()
        if explicit_title:
            chapter["title"] = explicit_title
        explicit_outline = str(explicit_item.get("outline", "") or "").strip()
        if not explicit_outline:
            source_location = chapter.get("source_location", {})
            # The caller injects restored source text before this method when
            # chapter planning is handling an unresolved imported mapping.
            source_text = str(chapter.pop("_framework_source_text", "") or "").strip()
            if source_text and isinstance(source_location, dict):
                try:
                    restored = _extract_framework_chapter_plan_from_locations(
                        source_text,
                        [{
                            "index": chapter.get("index", 0),
                            **source_location,
                        }],
                    ).get("chapters", [])
                except Exception:
                    restored = []
                if restored:
                    explicit_outline = str(restored[0].get("outline", "") or "").strip()
                    if not explicit_title:
                        explicit_title = str(restored[0].get("title", "") or "").strip()
        if str(chapter.get("outline_mode", "") or "").strip() == "use_imported":
            if explicit_title:
                chapter["title"] = explicit_title
            if explicit_outline:
                chapter["outline"] = explicit_outline
                chapter["outline_source"] = "imported_framework"
            # The AI selected this exact original chapter. Its source event IDs
            # are already established, so reuse them without inventing a ledger.
            if explicit_item.get("source_event_ids"):
                chapter["source_event_ids"] = deepcopy(explicit_item["source_event_ids"])
        return chapter

    def _chapter_plan_batch_ranges(self, chapter_count, batch_size=_CHAPTER_PLAN_BATCH_SIZE):
        try:
            chapter_count = max(0, int(chapter_count or 0))
            batch_size = max(1, int(batch_size or _CHAPTER_PLAN_BATCH_SIZE))
        except Exception:
            return []
        return [
            (offset, min(batch_size, chapter_count - offset))
            for offset in range(0, chapter_count, batch_size)
        ]

    def _chapter_plan_stage_batch_ranges(self, state):
        """Return absolute chapter ranges that never cross an explicit source stage.

        Stage batching is enabled only when the imported/source framework
        contains valid stages. The saved foundation remains the source of the
        normalized boundaries so resumed jobs follow the same plan.
        """
        state = state if isinstance(state, dict) else {}
        master_plan = state.get("master_plan", {})
        master_plan = master_plan if isinstance(master_plan, dict) else {}
        arcs = master_plan.get("arcs", [])
        arcs = arcs if isinstance(arcs, list) else []
        reference = (
            self.current_project.get("imported_chapter_plan_reference", {})
            if isinstance(getattr(self, "current_project", None), dict)
            else {}
        )
        reference_stages = reference.get("stages", []) if isinstance(reference, dict) else []
        if not isinstance(reference_stages, list) or not reference_stages:
            creation_framework = (
                self.current_project.get("creation_framework", {})
                if isinstance(getattr(self, "current_project", None), dict)
                else {}
            )
            reference_stages = (
                creation_framework.get("stage_plan", [])
                if isinstance(creation_framework, dict)
                else []
            )
        if not isinstance(reference_stages, list) or not reference_stages:
            return None

        try:
            existing_count = max(0, int(state.get("existing_chapter_count", 0) or 0))
            requested = max(0, int(state.get("requested_chapter_count", 0) or 0))
            batch_size = self._chapter_plan_state_batch_size(state)
        except Exception:
            return None
        first_chapter = existing_count + 1
        last_chapter = existing_count + requested
        if first_chapter > last_chapter:
            return []

        normalized = []
        for arc in arcs:
            if not isinstance(arc, dict):
                continue
            try:
                start = int(arc.get("start_chapter", 0) or 0)
                end = int(arc.get("end_chapter", 0) or 0)
            except Exception:
                continue
            if start <= 0 or end < start:
                continue
            start = max(first_chapter, start)
            end = min(last_chapter, end)
            if start <= end:
                normalized.append((start, end))
        normalized.sort()
        if not normalized or normalized[0][0] != first_chapter or normalized[-1][1] != last_chapter:
            return None
        expected = first_chapter
        for start, end in normalized:
            if start != expected:
                return None
            expected = end + 1
        if expected != last_chapter + 1:
            return None

        # Confirm that the master plan did not silently merge/split explicit
        # source stages.  The reference may begin before an existing chapter;
        # clipping it to the requested absolute range is intentional.
        source_ranges = []
        for stage in reference_stages:
            if not isinstance(stage, dict):
                continue
            try:
                start = int(stage.get("start_chapter", 0) or 0)
                end = int(stage.get("end_chapter", 0) or 0)
            except Exception:
                continue
            start = max(first_chapter, start)
            end = min(last_chapter, end)
            if start <= end:
                source_ranges.append((start, end))
        source_ranges.sort()
        if source_ranges:
            if source_ranges[0][0] != first_chapter or source_ranges[-1][1] != last_chapter:
                return None
            expected = first_chapter
            for start, end in source_ranges:
                if start != expected:
                    return None
                expected = end + 1
            if expected != last_chapter + 1:
                return None
            if source_ranges != normalized:
                return None

        ranges = []
        for start, end in normalized:
            cursor = start
            while cursor <= end:
                chunk_end = min(end, cursor + batch_size - 1)
                ranges.append((cursor, chunk_end))
                cursor = chunk_end + 1
        return ranges

    def _chapter_plan_next_batch_info(self, state):
        """Return (batch_count, batch_number, total_batches, abs_start, abs_end)."""
        state = state if isinstance(state, dict) else {}
        generated = state.get("chapters", []) if isinstance(state.get("chapters"), list) else []
        existing_count = int(state.get("existing_chapter_count", 0) or 0)
        requested = int(state.get("requested_chapter_count", 0) or 0)
        next_start = existing_count + len(generated) + 1
        stage_ranges = self._chapter_plan_stage_batch_ranges(state)
        if stage_ranges is not None:
            ranges = stage_ranges
            for batch_number, (start, end) in enumerate(ranges, 1):
                if start <= next_start <= end:
                    return end - next_start + 1, batch_number, len(ranges), next_start, end
            return 0, 0, len(ranges), next_start, next_start - 1

        batch_size = self._chapter_plan_state_batch_size(state)
        remaining = max(0, requested - len(generated))
        batch_count = min(batch_size, remaining)
        ranges = self._chapter_plan_batch_ranges(requested, batch_size)
        batch_number = len(generated) // batch_size + 1 if batch_count else 0
        absolute_end = next_start + batch_count - 1
        return batch_count, batch_number, len(ranges), next_start, absolute_end

    def _sanitize_creation_chapter_event_refs(self, chapters, absolute_start):
        """保留可确认的事件索引，避免辅助字段让整批提纲失败。

        向导阶段事件已经作为完整事实放在章节规划上下文中。模型返回的
        source_event_ids 只是索引，不能因为模型把索引放偏一章就丢弃已经
        生成的 outline；越界、重复或未知索引直接移除，正文事实不变。
        """
        project = self.current_project if isinstance(getattr(self, "current_project", None), dict) else {}
        framework = project.get("creation_framework", {})
        if not isinstance(framework, dict) or framework.get("source") != "creation_wizard":
            return
        stages = framework.get("structured_stages", framework.get("stage_plan", []))
        if not isinstance(stages, list) or not stages:
            return

        event_by_id = {}
        event_aliases = {}
        for stage_index, stage in enumerate(stages, 1):
            if not isinstance(stage, dict):
                continue
            stage_id = _canonical_chapter_plan_stage_id(
                stage.get("id", ""), f"S{stage_index:02d}"
            )
            if not stage_id:
                continue
            for event_index, event in enumerate(
                stage.get("ordered_events", [])
                if isinstance(stage.get("ordered_events"), list)
                else [],
                1,
            ):
                if not isinstance(event, dict):
                    continue
                raw_event_id = _canonical_chapter_plan_event_id(event.get("id", ""))
                event_id = raw_event_id
                if not re.fullmatch(rf"{re.escape(stage_id)}-E\d{{2,4}}", event_id):
                    event_id = f"{stage_id}-E{event_index:02d}"
                event_by_id[event_id] = (stage_id, event)
                event_aliases[event_id] = event_id
                event_aliases[f"{stage_id}-E{event_index:02d}"] = event_id
                if raw_event_id:
                    event_aliases[raw_event_id] = event_id

        seen = set()
        for offset, chapter in enumerate(chapters if isinstance(chapters, list) else []):
            if not isinstance(chapter, dict):
                continue
            try:
                chapter_index = int(absolute_start or 1) + offset
            except (TypeError, ValueError):
                chapter_index = offset + 1
            stage_id = _canonical_chapter_plan_stage_id(chapter.get("stage_id", ""))
            cleaned = []
            for raw_ref in _normalize_name_list(
                chapter.get("source_event_ids", chapter.get("event_refs", []))
            ):
                event_id = event_aliases.get(
                    _canonical_chapter_plan_event_id(raw_ref),
                    _canonical_chapter_plan_event_id(raw_ref),
                )
                info = event_by_id.get(event_id)
                if info is None:
                    continue
                event_stage_id, event = info
                if stage_id and event_stage_id != stage_id:
                    continue
                allowed = event.get("allowed_chapters", [])
                if isinstance(allowed, list) and len(allowed) >= 2:
                    try:
                        if not (int(allowed[0]) <= chapter_index <= int(allowed[1])):
                            continue
                    except (TypeError, ValueError):
                        pass
                if event_id in seen:
                    continue
                seen.add(event_id)
                cleaned.append(event_id)
            chapter["source_event_ids"] = cleaned

    def _validate_creation_chapter_plan_batch(self, chapters, absolute_start):
        """Validate wizard event references before a batch is persisted."""
        project = self.current_project if isinstance(getattr(self, "current_project", None), dict) else {}
        framework = project.get("creation_framework", {})
        if not isinstance(framework, dict) or framework.get("source") != "creation_wizard":
            return ""
        stages = framework.get("structured_stages", framework.get("stage_plan", []))
        if not isinstance(stages, list) or not stages:
            return ""
        stage_by_id = {}
        event_by_id = {}
        event_aliases = {}
        for stage_index, stage in enumerate(stages, 1):
            if not isinstance(stage, dict):
                continue
            stage_id = _canonical_chapter_plan_stage_id(
                stage.get("id", ""), f"S{stage_index:02d}"
            )
            if not stage_id:
                continue
            stage_by_id[stage_id] = stage
            for event_index, event in enumerate(
                stage.get("ordered_events", [])
                if isinstance(stage.get("ordered_events"), list)
                else [],
                1,
            ):
                if not isinstance(event, dict):
                    continue
                raw_event_id = _canonical_chapter_plan_event_id(event.get("id", ""))
                expected_event_id = f"{stage_id}-E{event_index:02d}"
                event_id = raw_event_id
                if not re.fullmatch(
                    rf"{re.escape(stage_id)}-E\d{{2,4}}", event_id
                ):
                    event_id = expected_event_id
                event_by_id[event_id] = (stage_id, event)
                event_aliases[expected_event_id] = event_id
                if raw_event_id:
                    event_aliases[raw_event_id] = event_id
        seen_events = set()
        for offset, chapter in enumerate(chapters if isinstance(chapters, list) else []):
            if not isinstance(chapter, dict):
                continue
            chapter_index = int(absolute_start or 1) + offset
            stage_id = _canonical_chapter_plan_stage_id(
                chapter.get("stage_id", "")
            )
            if stage_id and stage_id in stage_by_id:
                stage = stage_by_id[stage_id]
                try:
                    start = int(stage.get("start_chapter", 0) or 0)
                    end = int(stage.get("end_chapter", 0) or 0)
                except (TypeError, ValueError):
                    start, end = 0, 0
                if start and end and not (start <= chapter_index <= end):
                    return f"第{chapter_index}章引用了不属于当前章节的阶段 {stage_id}。"
            refs = chapter.get("source_event_ids", chapter.get("event_refs", []))
            for raw_ref in _normalize_name_list(refs):
                event_id = event_aliases.get(
                    _canonical_chapter_plan_event_id(raw_ref),
                    _canonical_chapter_plan_event_id(raw_ref),
                )
                if event_id not in event_by_id:
                    return f"第{chapter_index}章引用了不存在的阶段事件 {event_id}。"
                event_stage_id, event = event_by_id[event_id]
                if stage_id and event_stage_id != stage_id:
                    return f"第{chapter_index}章把 {event_id} 放到了错误的阶段。"
                allowed = event.get("allowed_chapters", [])
                if isinstance(allowed, list) and len(allowed) >= 2:
                    try:
                        if not (int(allowed[0]) <= chapter_index <= int(allowed[1])):
                            return f"第{chapter_index}章超出了 {event_id} 允许的章节范围。"
                    except (TypeError, ValueError):
                        pass
                if event_id in seen_events:
                    return f"阶段事件 {event_id} 被重复安排。"
                seen_events.add(event_id)
        return ""

    @staticmethod
    def _chapter_plan_state_batch_size(state):
        state = state if isinstance(state, dict) else {}
        try:
            return max(1, int(state.get("batch_size", _CHAPTER_PLAN_BATCH_SIZE) or _CHAPTER_PLAN_BATCH_SIZE))
        except Exception:
            return _CHAPTER_PLAN_BATCH_SIZE

    def _persist_chapter_plan_generation_state(self, state):
        if not isinstance(getattr(self, "current_project", None), dict):
            return
        stored = deepcopy(state) if isinstance(state, dict) else {}
        stored["updated_at"] = now_str()
        self.current_project["chapter_plan_generation_state"] = stored
        if hasattr(self, "_note_project_dirty"):
            self._note_project_dirty()
        if not hasattr(self, "current_project_path") or not hasattr(self, "_draft_saved_once"):
            return
        try:
            self._save_draft_snapshot()
            self._save_current_project_snapshot_if_named()
        except Exception as e:
            log_debug("章节分批规划进度持久化失败", e)

    def _chapter_plan_state_matches(self, state, target_words, average_words, total_count, existing_count):
        if not isinstance(state, dict):
            return False
        return (
            int(state.get("version", 0) or 0) == _CHAPTER_PLAN_BATCH_STATE_VERSION
            and int(state.get("target_words", 0) or 0) == int(target_words or 0)
            and int(state.get("average_chapter_words", 0) or 0) == int(average_words or 0)
            and int(state.get("total_chapter_count", 0) or 0) == int(total_count or 0)
            and int(state.get("existing_chapter_count", -1) or 0) == int(existing_count or 0)
        )

    @staticmethod
    def _narrative_strategy_profile_hash(profile):
        normalized = _normalize_narrative_strategy_profile(profile)
        normalized.pop("updated_at", None)
        payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest() if normalized else ""

    @staticmethod
    def _creative_intent_contract_from_profile(profile):
        profile = _normalize_narrative_strategy_profile(profile)
        supporting = str(profile.get("secondary_story_engine", "") or "").strip()
        reading_parts = [
            str(profile.get("core_reader_promise", "") or "").strip(),
            str(profile.get("pacing_strategy", "") or "").strip(),
            str(profile.get("low_exposition_strategy", "") or "").strip(),
        ]
        return _normalize_creative_intent_contract({
            "primary_line": profile.get("core_motive", "") or profile.get("primary_story_engine", ""),
            "core_motive": profile.get("core_motive", "") or profile.get("primary_story_engine", ""),
            "supporting_lines": [supporting] if supporting else [],
            "reading_experience": "；".join(part for part in reading_parts if part),
            "ending_boundaries": profile.get("story_direction", ""),
            "source": "chapter_plan_inference",
            "version": "1",
        })

    def _edit_narrative_strategy_profile(self, profile, planning_gate=False):
        dialog = NarrativeStrategyProfileDialog(
            profile,
            self,
            planning_gate=planning_gate,
        )
        if dialog.exec() != QDialog.Accepted:
            return False, _normalize_narrative_strategy_profile(profile)
        return True, dialog.profile()

    @staticmethod
    def _chapter_plan_foundation_hash(master_plan):
        plan = deepcopy(master_plan) if isinstance(master_plan, dict) else {}
        profile = plan.get("narrative_strategy_profile", {})
        if isinstance(profile, dict):
            profile = deepcopy(profile)
            profile.pop("updated_at", None)
            plan["narrative_strategy_profile"] = profile
        payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest() if plan else ""

    def _validate_chapter_plan_foundation(self, plan):
        plan = plan if isinstance(plan, dict) else {}
        if not str(plan.get("summary", "") or "").strip():
            return "故事简介不能为空。"
        profile = _normalize_narrative_strategy_profile(
            plan.get("narrative_strategy_profile", {})
        )
        if not profile:
            return "叙事策略画像不能为空。"
        arcs = plan.get("arcs", []) if isinstance(plan.get("arcs"), list) else []
        if not arcs:
            return "阶段规划不能为空。"
        try:
            expected = int(plan.get("existing_chapter_count", 0) or 0) + 1
            total = int(plan.get("total_chapter_count", 0) or 0)
        except Exception:
            return "全书章节范围无效，请重新生成规划基础。"
        for index, arc in enumerate(arcs, 1):
            if not isinstance(arc, dict):
                return f"阶段{index}格式无效。"
            try:
                start = int(arc.get("start_chapter", 0) or 0)
                end = int(arc.get("end_chapter", 0) or 0)
            except Exception:
                return f"阶段{index}的起止章节必须填写数字。"
            if start != expected:
                return f"阶段{index}应从第{expected}章开始，当前填写为第{start}章。"
            if end < start:
                return f"阶段{index}的结束章节不能早于起始章节。"
            if not str(arc.get("name", "") or "").strip():
                return f"阶段{index}缺少阶段名称。"
            expected = end + 1
        if expected - 1 != total:
            return f"阶段规划必须连续覆盖到第{total}章，当前只覆盖到第{expected - 1}章。"
        reference_error = self._chapter_plan_master_reference_error(plan)
        if reference_error:
            return f"原始框架阶段边界不一致：{reference_error}"
        return ""

    def _edit_chapter_plan_foundation(self, master_plan, state):
        dialog = ChapterPlanFoundationDialog(
            master_plan,
            state,
            validator=self._validate_chapter_plan_foundation,
            parent=self,
        )
        result = dialog.exec()
        if result == ChapterPlanFoundationDialog.RegenerateResult:
            return "regenerate", deepcopy(master_plan)
        if result != QDialog.Accepted:
            return "cancelled", deepcopy(master_plan)
        return "confirmed", dialog.confirmed_plan()

    def _save_narrative_strategy_profile(self, profile, confirmation_status="confirmed"):
        normalized = _normalize_narrative_strategy_profile(profile)
        if not normalized:
            return {}
        normalized["version"] = str(normalized.get("version", "1") or "1")
        normalized["updated_at"] = now_str()
        profile_hash = self._narrative_strategy_profile_hash(normalized)
        self.current_project["narrative_strategy_profile"] = deepcopy(normalized)
        previous = self.current_project.get("narrative_strategy_confirmation", {})
        previous = previous if isinstance(previous, dict) else {}
        confirmation = {
            "status": "confirmed" if confirmation_status == "confirmed" else "pending",
            "profile_hash": profile_hash,
            "generated_at": str(previous.get("generated_at", "") or now_str()),
            "updated_at": now_str(),
        }
        if confirmation["status"] == "confirmed":
            confirmation["confirmed_at"] = now_str()
        self.current_project["narrative_strategy_confirmation"] = confirmation
        return normalized

    def _confirm_chapter_plan_strategy_profile(self, state):
        state = deepcopy(state) if isinstance(state, dict) else {}
        master_plan = state.get("master_plan", {})
        master_plan = deepcopy(master_plan) if isinstance(master_plan, dict) else {}
        profile = master_plan.get("narrative_strategy_profile", {})
        if not isinstance(profile, dict) or not profile:
            profile = state.get("narrative_strategy_profile", {})
        if not isinstance(profile, dict) or not profile:
            profile = self.current_project.get("narrative_strategy_profile", {})
        profile = _normalize_narrative_strategy_profile(profile)
        if not profile:
            self.on_chapter_plan_failed("AI 没有返回可供确认的叙事策略画像。")
            return False

        action, edited_master_plan = self._edit_chapter_plan_foundation(master_plan, state)
        if action == "regenerate":
            self.current_project["narrative_strategy_profile"] = {}
            self.current_project["narrative_strategy_confirmation"] = {}
            self.current_project["chapter_plan_foundation"] = {}
            existing_contract = _normalize_creative_intent_contract(
                self.current_project.get("creative_intent_contract", {})
            )
            if str(existing_contract.get("source", "") or "").strip() != "user_confirmed":
                self.current_project["creative_intent_contract"] = {}
            state["master_plan"] = {}
            state["narrative_strategy_profile"] = {}
            if str(existing_contract.get("source", "") or "").strip() != "user_confirmed":
                state["creative_intent_contract"] = {}
            state["profile_confirmed"] = False
            state["force_master_regeneration"] = True
            state.pop("profile_hash", None)
            state.pop("foundation_hash", None)
            state["status"] = "pending"
            state.pop("error", None)
            self._chapter_plan_foundation_regenerate_pending = True
            self._persist_chapter_plan_generation_state(state)
            self._show_chapter_plan_generation_progress(
                state,
                "已放弃当前规划基础，正在准备重新生成。",
            )
            self.set_status_tip("正在重新整理章节规划基础和叙事策略...")
            return False
        if action != "confirmed":
            pending_profile = self._save_narrative_strategy_profile(profile, "pending")
            master_plan["narrative_strategy_profile"] = deepcopy(pending_profile)
            contract = _normalize_creative_intent_contract(
                master_plan.get("creative_intent_contract", {})
                or state.get("creative_intent_contract", {})
                or self._creative_intent_contract_from_profile(pending_profile)
            )
            if contract:
                master_plan["creative_intent_contract"] = deepcopy(contract)
                state["creative_intent_contract"] = deepcopy(contract)
                self.current_project["creative_intent_contract"] = deepcopy(contract)
            self.current_project["chapter_plan_foundation"] = _normalize_chapter_plan_foundation(
                master_plan
            )
            state["master_plan"] = master_plan
            state["narrative_strategy_profile"] = deepcopy(pending_profile)
            state["profile_confirmed"] = False
            state["profile_hash"] = self._narrative_strategy_profile_hash(pending_profile)
            state["foundation_hash"] = self._chapter_plan_foundation_hash(master_plan)
            state["status"] = "awaiting_profile_confirmation"
            self._chapter_plan_auto_active = False
            self._chapter_plan_continue_pending = False
            self._chapter_plan_foundation_regenerate_pending = False
            self._persist_chapter_plan_generation_state(state)
            self._show_chapter_plan_generation_progress(
                state,
                "章节规划基础尚未确认。再次点击AI生成章节规划即可继续核对，不会重复调用规划基础API。",
            )
            self.set_status_tip("已暂停章节规划：等待确认章节规划基础和叙事策略。")
            return False

        master_plan = deepcopy(edited_master_plan)
        edited_profile = master_plan.get("narrative_strategy_profile", {})
        confirmed_profile = self._save_narrative_strategy_profile(edited_profile, "confirmed")
        master_plan["narrative_strategy_profile"] = deepcopy(confirmed_profile)
        contract = _normalize_creative_intent_contract(
            master_plan.get("creative_intent_contract", {})
            or state.get("creative_intent_contract", {})
            or self._creative_intent_contract_from_profile(confirmed_profile)
        )
        if contract:
            master_plan["creative_intent_contract"] = deepcopy(contract)
            state["creative_intent_contract"] = deepcopy(contract)
            self.current_project["creative_intent_contract"] = deepcopy(contract)
        foundation_hash = self._chapter_plan_foundation_hash(master_plan)
        self.current_project["chapter_plan_foundation"] = _normalize_chapter_plan_foundation(
            master_plan
        )
        state["master_plan"] = master_plan
        state["narrative_strategy_profile"] = deepcopy(confirmed_profile)
        state["profile_confirmed"] = True
        state["profile_hash"] = self._narrative_strategy_profile_hash(confirmed_profile)
        state["foundation_hash"] = foundation_hash
        state["status"] = "generating"
        state.pop("error", None)
        confirmation = self.current_project.get("narrative_strategy_confirmation", {})
        confirmation = deepcopy(confirmation) if isinstance(confirmation, dict) else {}
        confirmation["foundation_hash"] = foundation_hash
        self.current_project["narrative_strategy_confirmation"] = confirmation
        self._chapter_plan_foundation_regenerate_pending = False
        self._persist_chapter_plan_generation_state(state)
        self.set_status_tip("章节规划基础已确认，正在准备详细章节规划。")
        return True

    def show_narrative_strategy_profile(self):
        profile = self.current_project.get("narrative_strategy_profile", {})
        profile = _normalize_narrative_strategy_profile(profile)
        if not profile:
            QMessageBox.information(
                self,
                "叙事策略画像",
                "当前项目尚未生成叙事策略画像。点击“AI生成章节规划”后，AI会先生成画像并请你确认。",
            )
            return
        worker = getattr(self, "chapter_plan_worker", None)
        if worker is not None and worker.isRunning():
            self.set_status_tip("章节规划正在生成，完成当前调用后再修改叙事策略。")
            return
        accepted, edited_profile = self._edit_narrative_strategy_profile(profile, planning_gate=False)
        if not accepted:
            return
        state = deepcopy(self.current_project.get("chapter_plan_generation_state", {}))
        awaiting = str(state.get("status", "") or "") == "awaiting_profile_confirmation"
        saved_profile = self._save_narrative_strategy_profile(
            edited_profile,
            "pending" if awaiting else "confirmed",
        )
        existing_contract = _normalize_creative_intent_contract(
            self.current_project.get("creative_intent_contract", {})
        )
        if not existing_contract or str(existing_contract.get("source", "") or "").strip() in {
            "",
            "chapter_plan_inference",
        }:
            existing_contract = self._creative_intent_contract_from_profile(saved_profile)
            if existing_contract:
                existing_contract["source"] = "chapter_plan_inference"
                self.current_project["creative_intent_contract"] = deepcopy(existing_contract)
        foundation = self.current_project.get("chapter_plan_foundation", {})
        if isinstance(foundation, dict) and foundation:
            foundation = deepcopy(foundation)
            foundation["narrative_strategy_profile"] = deepcopy(saved_profile)
            self.current_project["chapter_plan_foundation"] = _normalize_chapter_plan_foundation(
                foundation
            )
        if isinstance(state, dict) and state:
            master_plan = state.get("master_plan", {})
            master_plan = deepcopy(master_plan) if isinstance(master_plan, dict) else {}
            master_plan["narrative_strategy_profile"] = deepcopy(saved_profile)
            if existing_contract:
                master_plan["creative_intent_contract"] = deepcopy(existing_contract)
            state["master_plan"] = master_plan
            state["narrative_strategy_profile"] = deepcopy(saved_profile)
            if existing_contract:
                state["creative_intent_contract"] = deepcopy(existing_contract)
            state["profile_hash"] = self._narrative_strategy_profile_hash(saved_profile)
            state["profile_confirmed"] = not awaiting
            self._persist_chapter_plan_generation_state(state)
        else:
            self._note_project_dirty()
            self._save_draft_snapshot()
            self._save_current_project_snapshot_if_named()
        self.set_status_tip(
            "叙事策略画像已保存；再次点击AI生成章节规划进行最终确认。"
            if awaiting else
            "叙事策略画像已保存，后续章节规划和正文扩写将使用修改后的内容。"
        )

    def _chapter_plan_master_summary_text(self, master_plan):
        master_plan = master_plan if isinstance(master_plan, dict) else {}
        lines = []
        for label, key in _CHAPTER_PLAN_FOUNDATION_FIELDS:
            value = str(master_plan.get(key, "") or "").strip()
            if value:
                lines.append(f"{label}：{value}")
        for arc in master_plan.get("arcs", []) if isinstance(master_plan.get("arcs"), list) else []:
            if not isinstance(arc, dict):
                continue
            start = int(arc.get("start_chapter", 0) or 0)
            end = int(arc.get("end_chapter", 0) or 0)
            name = str(arc.get("name", "") or "阶段").strip()
            lines.append(f"第{start}-{end}章｜{name}")
            for label, key in (
                ("宏观节奏", "macro_phase"),
                ("原框架阶段", "source_stage"),
                ("主导线", "dominant_line"),
                ("关系目标", "relationship_goal"),
                ("结束状态", "end_state"),
            ):
                value = str(arc.get(key, "") or "").strip()
                if value:
                    lines.append(f"{label}：{value}")
        return "\n".join(line for line in lines if line).strip()

    def _creation_wizard_stage_nodes_for_range(self, batch_start, batch_end):
        """Return only the current wizard stage nodes needed for placement.

        The placement request must not carry the full novel dossier.  The
        wizard already produced ordered nodes with chapter windows, so this
        helper exposes only the current stage's small, actionable slice.
        """
        project = self.current_project if isinstance(self.current_project, dict) else {}
        framework = project.get("creation_framework", {})
        if not isinstance(framework, dict) or framework.get("source") != "creation_wizard":
            return {}
        try:
            batch_start = int(batch_start or 0)
            batch_end = int(batch_end or 0)
        except (TypeError, ValueError):
            return {}
        if batch_start <= 0 or batch_end < batch_start:
            return {}

        def compact_stage_value(value, limit):
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            return self._chapter_plan_clip_text(value, limit)

        stages = framework.get("stage_plan", [])
        if not isinstance(stages, list):
            return {}
        for stage_index, stage in enumerate(stages, 1):
            if not isinstance(stage, dict):
                continue
            try:
                stage_start = int(stage.get("start_chapter", 0) or 0)
                stage_end = int(stage.get("end_chapter", 0) or 0)
            except (TypeError, ValueError):
                continue
            if stage_start > batch_start or stage_end < batch_end:
                continue
            stage_id = _canonical_chapter_plan_stage_id(
                stage.get("id", ""), f"S{stage_index:02d}"
            )
            raw_events = stage.get("ordered_events", [])
            raw_events = raw_events if isinstance(raw_events, list) else []
            nodes = []
            for event_index, event in enumerate(raw_events, 1):
                if not isinstance(event, dict):
                    continue
                allowed = event.get("allowed_chapters", [])
                if not isinstance(allowed, (list, tuple)) or len(allowed) < 2:
                    allowed = [stage_start, stage_end]
                try:
                    allowed_start = int(allowed[0] or stage_start)
                    allowed_end = int(allowed[1] or stage_end)
                except (TypeError, ValueError):
                    allowed_start, allowed_end = stage_start, stage_end
                if allowed_end < batch_start or allowed_start > batch_end:
                    continue
                nodes.append({
                    "n": event_index,
                    "id": _canonical_chapter_plan_event_id(event.get("id", "")),
                    "allowed": [max(batch_start, allowed_start), min(batch_end, allowed_end)],
                    "event": self._chapter_plan_clip_text(event.get("event", ""), 700),
                    "result": self._chapter_plan_clip_text(event.get("result", ""), 500),
                })
            if not nodes:
                return {}
            return {
                "stage_id": stage_id,
                "stage_name": self._chapter_plan_clip_text(stage.get("name", ""), 120),
                "stage_summary": compact_stage_value(stage.get("summary", ""), 900),
                "entry_state": compact_stage_value(stage.get("entry_state", ""), 500),
                "exit_state": compact_stage_value(stage.get("exit_state", ""), 500),
                "batch_start": batch_start,
                "batch_end": batch_end,
                "nodes": nodes,
            }
        return {}

    @staticmethod
    def _chapter_plan_event_schedule_key(batch_start, batch_end):
        return f"{int(batch_start or 0)}-{int(batch_end or 0)}"

    def _chapter_plan_saved_event_schedule(self, state, batch_start, batch_end):
        schedules = state.get("event_schedules", {}) if isinstance(state, dict) else {}
        if not isinstance(schedules, dict):
            return {}
        value = schedules.get(self._chapter_plan_event_schedule_key(batch_start, batch_end), {})
        return deepcopy(value) if isinstance(value, dict) else {}

    def _chapter_plan_locked_node_schedule(self, state, batch_start, batch_end):
        source = self._creation_wizard_stage_nodes_for_range(batch_start, batch_end)
        if not source:
            return {}
        saved = self._chapter_plan_saved_event_schedule(state, batch_start, batch_end)
        placements = saved.get("placements", []) if isinstance(saved, dict) else []
        placement_map = {}
        for item in placements if isinstance(placements, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                placement_map[int(item.get("n", 0) or 0)] = [
                    int(item.get("a", 0) or 0), int(item.get("b", 0) or 0)
                ]
            except (TypeError, ValueError):
                continue
        return {
            "stage_id": source.get("stage_id", ""),
            "range": [int(batch_start), int(batch_end)],
            "nodes": [
                {
                    "n": int(node.get("n", 0) or 0),
                    "range": placement_map.get(
                        int(node.get("n", 0) or 0),
                        list(node.get("allowed", [batch_start, batch_end]))[:2],
                    ),
                }
                for node in source.get("nodes", [])
                if isinstance(node, dict)
            ],
        }

    def _chapter_plan_event_placement_context(self, stage_data):
        """Build a small placement-only request envelope."""
        if not isinstance(stage_data, dict):
            return ""
        premise = {}
        framework = self.current_project.get("creation_framework", {})
        if isinstance(framework, dict):
            raw_premise = framework.get("premise", {})
            if isinstance(raw_premise, dict):
                for key in ("synopsis", "one_sentence", "main_line", "story_synopsis", "summary", "core_mainline"):
                    value = self._chapter_plan_clip_text(raw_premise.get(key, ""), 700)
                    if value:
                        premise[key] = value
        payload = {
            "stage": {
                "id": stage_data.get("stage_id", ""),
                "name": stage_data.get("stage_name", ""),
                "summary": stage_data.get("stage_summary", ""),
                "entry_state": stage_data.get("entry_state", ""),
                "exit_state": stage_data.get("exit_state", ""),
            },
            "batch": [stage_data.get("batch_start", 0), stage_data.get("batch_end", 0)],
            "nodes": [
                {
                    "n": node.get("n", 0),
                    "allowed": node.get("allowed", []),
                    "event": node.get("event", ""),
                    "result": node.get("result", ""),
                }
                for node in stage_data.get("nodes", [])
                if isinstance(node, dict)
            ],
        }
        if premise:
            payload["story_anchor"] = premise
        return (
            "请根据以下当前阶段资料安排剧情节点的章节范围。只处理节点位置，不重新创作故事。\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )

    def _chapter_plan_batch_context(self, state, batch_count):
        generated = state.get("chapters", []) if isinstance(state.get("chapters"), list) else []
        creation_wizard_project = bool(
            isinstance(self.current_project, dict)
            and isinstance(self.current_project.get("creation_framework"), dict)
            and self.current_project.get("creation_framework", {}).get("source") == "creation_wizard"
        )
        existing_count = int(state.get("existing_chapter_count", 0) or 0)
        batch_start = existing_count + len(generated) + 1
        batch_end = batch_start + int(batch_count or 0) - 1
        try:
            total_chapter_count = int(state.get("total_chapter_count", 0) or 0)
        except (TypeError, ValueError):
            total_chapter_count = 0
        terminal_bounds = _terminal_window_bounds(total_chapter_count)
        batch_terminal_overlap = None
        if terminal_bounds:
            overlap_start = max(batch_start, terminal_bounds[0])
            overlap_end = min(batch_end, terminal_bounds[1])
            if overlap_start <= overlap_end:
                batch_terminal_overlap = (overlap_start, overlap_end)
        batch_is_final = bool(total_chapter_count and batch_end >= total_chapter_count)
        ledger = []
        for item in generated:
            if not isinstance(item, dict):
                continue
            row = {
                "index": item.get("index", ""),
                "title": item.get("title", ""),
                "outline": item.get("outline", ""),
                "characters": item.get("characters", []),
                "stage_id": item.get("stage_id", ""),
            }
            if not creation_wizard_project:
                row["source_event_ids"] = [
                    _canonical_chapter_plan_event_id(value)
                    for value in _normalize_name_list(item.get("source_event_ids", []))
                ]
            ledger.append(row)
        previous_tail = []
        for item in generated[-5:]:
            if not isinstance(item, dict):
                continue
            row = {
                key: deepcopy(item.get(key, ""))
                for key in (
                    "index", "title", "outline", "characters", "stage_id",
                )
            }
            if not creation_wizard_project:
                row["source_event_ids"] = [
                    _canonical_chapter_plan_event_id(value)
                    for value in _normalize_name_list(item.get("source_event_ids", []))
                ]
            previous_tail.append(row)
        compact_master_plan = _normalize_chapter_plan_foundation(state.get("master_plan", {}))
        # These are already supplied once at the top level. Keeping only the
        # confirmed planning foundation and stage map prevents duplicated
        # strategy prose from turning into per-chapter checklists.
        compact_master_plan.pop("narrative_strategy_profile", None)
        compact_master_plan.pop("creative_intent_contract", None)
        if compact_master_plan.get("source") == "creation_wizard":
            # The current stage and all stage boundaries are already sent once
            # through wizard_framework.  The batch envelope only needs the
            # confirmed story-level anchors; sending the foundation object
            # again makes the model reconcile two copies of the same plan.
            master_keys = (
                "source", "summary", "core_motive", "ending_promise",
                "global_hard_boundaries",
            )
            try:
                batch_is_final = batch_end >= int(state.get("total_chapter_count", 0) or 0)
            except (TypeError, ValueError):
                batch_is_final = False
            if not batch_is_final:
                master_keys = tuple(key for key in master_keys if key != "ending_promise")
            compact_master_plan = {
                key: deepcopy(compact_master_plan.get(key))
                for key in master_keys
                if compact_master_plan.get(key) not in (None, "", [], {})
            }
        continuity_rules = [
            (
                "本批包含全书最后一章：仍服从已确认的阶段规划，并在已有章节位置内完成核心矛盾、主要关系和主角最终处境的实际结果；"
                "不得另增章节，但也不要把结尾继续写成等待后续章节回答的连载悬念。"
                if batch_is_final else
                "本批必须服从已确认的阶段规划，不得把批次结尾写成全书结局。"
            ),
            "第1章的相对index对应required_absolute_range起点，章节数量必须精确。",
            "承接上一批末章状态，避免重复开局、重复冲突或提前进入后续阶段。",
            "原框架阶段高于宏观节奏；不得在前10%/中70%边界处切换题材。",
            "保持本项目主线；项目资料只作连续性参考，不能把背景资料自动变成章节任务。",
            "used_chapter_titles是已经使用过的章节标题清单；新标题不得与其中任何标题重复，也不得与本批次其他新标题重复。",
            "相邻章节应避免无意义重复，但不要求按固定轮换表更换开局、冲突或结尾；以当前人物处境和主线需要为准。",
            (
                "当前批次与全书最后5章收尾窗口有交集：窗口内只落实已经安排的直接后果、行动、关系变化或主角处境落点；"
                "不得新增主要任务、主要敌人、未知信息或等待回答的悬念。"
                if batch_terminal_overlap else
                "上一批末章结尾已经是已发布触发点，下一批第一章必须从新反应、新结果或新阻力开始，不能复播末句、声音、动作落点或结论。"
            ),
        ]
        if batch_terminal_overlap and batch_start > 1:
            continuity_rules.append(
                "收尾窗口批次的第一章承接上一章已经发生的结果，后续章节继续写窗口内部的直接后果，不另开新的连载主线。"
            )
        continuity = {
            "required_absolute_range": [batch_start, batch_end],
            "master_plan": compact_master_plan,
            "planned_chapter_ledger": ledger,
            "previous_batch_tail": previous_tail,
            "rules": continuity_rules,
        }
        locked_node_schedule = self._chapter_plan_locked_node_schedule(
            state, batch_start, batch_end
        )
        if locked_node_schedule:
            continuity["locked_node_schedule"] = locked_node_schedule
        return self._chapter_plan_project_context(
            state.get("target_words", 0),
            state.get("average_chapter_words", 0),
            state.get("total_chapter_count", 0),
            batch_count,
            existing_count_override=existing_count + len(generated),
            reference_start_index=batch_start,
            reference_end_index=batch_end,
            context_mode="batch",
            extra_payload={"batch_continuity": continuity},
        )

    def _chapter_plan_from_generation_state(self, state):
        return {
            "summary": self._chapter_plan_master_summary_text(state.get("master_plan", {})),
            "target_words": int(state.get("target_words", 0) or 0),
            "average_chapter_words": int(state.get("average_chapter_words", 0) or 0),
            "chapter_count": int(state.get("requested_chapter_count", 0) or 0),
            "total_chapter_count": int(state.get("total_chapter_count", 0) or 0),
            "existing_chapter_count": int(state.get("existing_chapter_count", 0) or 0),
            "chapters": deepcopy(state.get("chapters", [])),
        }

    def _show_chapter_plan_generation_progress(self, state, message=""):
        generated = len(state.get("chapters", [])) if isinstance(state.get("chapters"), list) else 0
        requested = int(state.get("requested_chapter_count", 0) or 0)
        total = int(state.get("total_chapter_count", 0) or 0)
        lines = [
            "正在自动分批生成章节规划",
            f"全书预计：{total}章",
            f"本次需规划：{requested}章",
            f"已完成：{generated}/{requested}章",
        ]
        if state.get("master_plan"):
            if state.get("master_plan", {}).get("source") == "imported_framework":
                lines.append("规划基础：沿用导入框架和原有阶段")
            elif state.get("master_plan", {}).get("source") == "creation_wizard":
                lines.append("规划基础：沿用向导阶段规划")
            elif bool(state.get("profile_confirmed", False)):
                lines.append("规划基础：章节规划基础和叙事策略已确认")
            else:
                lines.append("规划基础：已生成，等待用户确认")
        else:
            lines.append("规划基础：待生成")
        if message:
            lines.extend(["", str(message)])
        self.chapter_ai_preview.setPlainText("\n".join(lines))

    def _stop_chapter_plan_without_foundation(self, state):
        message = (
            "当前项目没有可用的章节规划基础。请先完成新建向导或导入框架，"
            "再点击AI章节规划。"
        )
        state = deepcopy(state) if isinstance(state, dict) else {}
        state["status"] = "failed"
        state["error"] = message
        state.pop("force_master_regeneration", None)
        self._chapter_plan_auto_active = False
        self._chapter_plan_continue_pending = False
        self._chapter_plan_request_kind = ""
        self._persist_chapter_plan_generation_state(state)
        self._show_chapter_plan_generation_progress(state, message)
        self._set_chapter_ai_actions_enabled(True)
        self.set_status_tip(message)

    def _start_chapter_plan_event_placement_worker(self, state, stage_data):
        """Run the small, validated node-placement request for one stage batch."""
        provider = self._chapter_plan_provider
        model = self._chapter_plan_model
        batch_start = int(stage_data.get("batch_start", 0) or 0)
        batch_end = int(stage_data.get("batch_end", 0) or 0)
        context = self._chapter_plan_event_placement_context(stage_data)
        worker = NovelChapterEventPlacementWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            context,
            stage_data.get("nodes", []),
            stage_data.get("stage_id", ""),
            batch_start,
            batch_end,
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
        )
        self._chapter_plan_request_kind = "event_placement"
        state = deepcopy(state) if isinstance(state, dict) else {}
        state["status"] = "placing"
        state.pop("error", None)
        self._persist_chapter_plan_generation_state(state)
        self._show_chapter_plan_generation_progress(
            state,
            f"正在安排第{batch_start}-{batch_end}章的阶段剧情节点...",
        )
        self.chapter_plan_worker = worker
        worker._chapter_plan_sequence_token = int(
            getattr(self, "_chapter_plan_sequence_token", 0) or 0
        )
        worker._chapter_plan_project_path = self._canonical_project_path(
            getattr(self, "current_project_path", "")
        )
        worker.diagnostic_project_path = worker._chapter_plan_project_path
        worker.diagnostic_project_title = str(
            (
                self.current_project.get("meta", {})
                if isinstance(self.current_project.get("meta", {}), dict)
                else {}
            ).get("title", "")
            or ""
        ).strip()
        self._connect_chapter_task_worker(
            worker, "on_chapter_plan_event_placement_ready", "_cleanup_chapter_plan_worker"
        )
        request_id = self._next_novel_diagnostic_request_id("chapter-plan-placement")
        diagnostic_started_at = time.perf_counter()
        self._chapter_plan_diagnostic_request_id = request_id
        self._chapter_plan_diagnostic_started_at = diagnostic_started_at
        worker.diagnostic_request_id = request_id
        worker.diagnostic_started_at = diagnostic_started_at
        worker.capture_raw_model_output = True
        worker.diagnostic_stage = "chapter_plan_event_placement"
        worker.raw_model_output_metadata = {
            "request_kind": "event_placement",
            "stage_id": str(stage_data.get("stage_id", "") or ""),
            "batch_start": batch_start,
            "batch_end": batch_end,
            "node_count": len(stage_data.get("nodes", [])),
        }
        try:
            system_prompt_chars = len(str(worker._analysis_prompt() or ""))
        except Exception:
            system_prompt_chars = 0
        self._log_novel_diagnostic(
            "chapter_plan_request_started",
            action="chapter_plan_event_placement",
            request_id=request_id,
            provider=provider,
            model=model,
            request_kind="event_placement",
            batch_start=batch_start,
            batch_end=batch_end,
            node_count=len(stage_data.get("nodes", [])),
            input_chars=len(str(context or "")),
            input_utf8_bytes=len(str(context or "").encode("utf-8", errors="replace")),
            system_prompt_chars=system_prompt_chars,
        )
        self._chapter_ai_stop_requested_by_user = False
        self._set_chapter_ai_actions_enabled(False)
        self.set_status_tip(f"正在安排第{batch_start}-{batch_end}章的阶段剧情节点...")
        worker.start()

    def _chapter_plan_event_placement_error(self, state, placement, stage_data):
        if not isinstance(placement, dict) or not isinstance(stage_data, dict):
            return "节点安排结果为空。"
        expected_nodes = stage_data.get("nodes", [])
        placements = placement.get("placements", [])
        if not isinstance(expected_nodes, list) or not expected_nodes:
            return "当前阶段没有可安排的剧情节点。"
        if not isinstance(placements, list) or len(placements) != len(expected_nodes):
            return f"节点安排数量不一致：需要{len(expected_nodes)}项，实际{len(placements) if isinstance(placements, list) else 0}项。"
        by_number = {}
        for item in placements:
            if not isinstance(item, dict):
                return "节点安排中存在无效项目。"
            try:
                number = int(item.get("n", 0) or 0)
                start = int(item.get("a", 0) or 0)
                end = int(item.get("b", 0) or 0)
            except (TypeError, ValueError):
                return "节点安排缺少有效的节点序号或章节范围。"
            if number != len(by_number) + 1:
                return "节点序号必须按输入顺序返回。"
            if number in by_number or not (1 <= number <= len(expected_nodes)):
                return "节点序号必须从1连续递增且不能重复。"
            if start < int(stage_data.get("batch_start", 0) or 0) or end > int(stage_data.get("batch_end", 0) or 0) or start > end:
                return f"节点{number}超出了当前批次章节范围。"
            node = expected_nodes[number - 1] if number <= len(expected_nodes) else {}
            allowed = node.get("allowed", []) if isinstance(node, dict) else []
            if isinstance(allowed, list) and len(allowed) >= 2:
                try:
                    if start < int(allowed[0]) or end > int(allowed[1]):
                        return f"节点{number}超出了原定范围第{allowed[0]}-{allowed[1]}章。"
                except (TypeError, ValueError):
                    pass
            by_number[number] = (start, end)
        if set(by_number) != set(range(1, len(expected_nodes) + 1)):
            return "节点安排没有覆盖全部节点。"
        previous_start = int(stage_data.get("batch_start", 0) or 0)
        for number in range(1, len(expected_nodes) + 1):
            start, _end = by_number[number]
            if start < previous_start:
                return "节点安排顺序被打乱。"
            previous_start = start
        return ""

    def on_chapter_plan_event_placement_ready(self, placement):
        if self._forward_chapter_task_signal("on_chapter_plan_event_placement_ready", placement):
            return
        if not self._chapter_plan_callback_is_current():
            return
        stage_data = self._creation_wizard_stage_nodes_for_range(
            placement.get("batch_start", 0) if isinstance(placement, dict) else 0,
            placement.get("batch_end", 0) if isinstance(placement, dict) else 0,
        )
        error = self._chapter_plan_event_placement_error(
            self.current_project.get("chapter_plan_generation_state", {}),
            placement,
            stage_data,
        )
        if error:
            self.on_chapter_plan_failed(f"阶段剧情节点安排校验失败：{error}")
            return
        state = deepcopy(self.current_project.get("chapter_plan_generation_state", {}))
        if not isinstance(state, dict) or not state:
            self.on_chapter_plan_failed("章节规划进度状态丢失，无法保存节点安排。")
            return
        schedules = state.get("event_schedules", {})
        schedules = deepcopy(schedules) if isinstance(schedules, dict) else {}
        key = self._chapter_plan_event_schedule_key(
            placement.get("batch_start", 0), placement.get("batch_end", 0)
        )
        schedules[key] = deepcopy(placement)
        state["event_schedules"] = schedules
        state["status"] = "generating"
        state.pop("error", None)
        self._persist_chapter_plan_generation_state(state)
        self._show_chapter_plan_generation_progress(
            state,
            f"第{placement.get('batch_start', 0)}-{placement.get('batch_end', 0)}章节点已锁定，正在生成章节提纲...",
        )
        self._queue_chapter_plan_continuation()

    def _start_chapter_plan_worker_for_state(self, state):
        if not getattr(self, "_chapter_plan_auto_active", False):
            return
        if not state.get("chapters") and not int(state.get("existing_chapter_count", 0) or 0):
            creation_foundation = self._chapter_plan_creation_wizard_foundation(state)
            if creation_foundation:
                state = deepcopy(state)
                state["master_plan"] = creation_foundation
                state["profile_confirmed"] = True
                state["narrative_strategy_profile"] = deepcopy(
                    creation_foundation.get("narrative_strategy_profile", {})
                )
                state["creative_intent_contract"] = deepcopy(
                    creation_foundation.get("creative_intent_contract", {})
                )
                state["foundation_hash"] = self._chapter_plan_foundation_hash(creation_foundation)
                state.pop("force_master_regeneration", None)
                self.current_project["chapter_plan_foundation"] = deepcopy(creation_foundation)
                if creation_foundation.get("narrative_strategy_profile"):
                    self._save_narrative_strategy_profile(
                        creation_foundation["narrative_strategy_profile"]
                    )
                self._persist_chapter_plan_generation_state(state)
            elif not state.get("force_master_regeneration"):
                self._chapter_plan_restore_imported_reference()
                foundation = self._chapter_plan_imported_foundation(state)
                if foundation:
                    state = deepcopy(state)
                    state["master_plan"] = foundation
                    state["profile_confirmed"] = True
                    state["narrative_strategy_profile"] = deepcopy(foundation.get("narrative_strategy_profile", {}))
                    state["foundation_hash"] = self._chapter_plan_foundation_hash(foundation)
                    self.current_project["chapter_plan_foundation"] = deepcopy(foundation)
                    # The imported author framework is already the user's
                    # confirmed planning foundation.
                    # No extra confirmation/API task is needed for a local projection.
                    if foundation.get("narrative_strategy_profile"):
                        self._save_narrative_strategy_profile(foundation["narrative_strategy_profile"])
                    self._persist_chapter_plan_generation_state(state)
        if state.get("master_plan") and not bool(state.get("profile_confirmed", False)):
            source = str(state.get("master_plan", {}).get("source", "") or "").strip()
            if source in {"creation_wizard", "imported_framework"}:
                state = deepcopy(state)
                state["profile_confirmed"] = True
                state["status"] = "pending"
                self._persist_chapter_plan_generation_state(state)
            else:
                state = deepcopy(state)
                state["master_plan"] = {}
                state["profile_confirmed"] = False
                self.current_project["chapter_plan_foundation"] = {}
                self._stop_chapter_plan_without_foundation(state)
                return
        if not state.get("master_plan"):
            self._stop_chapter_plan_without_foundation(state)
            return
        generated = state.get("chapters", []) if isinstance(state.get("chapters"), list) else []
        requested = int(state.get("requested_chapter_count", 0) or 0)
        remaining = max(0, requested - len(generated))
        if remaining <= 0:
            state["status"] = "complete"
            state.pop("error", None)
            self._persist_chapter_plan_generation_state(state)
            plan = self._chapter_plan_from_generation_state(state)
            self._pending_chapter_plan = plan
            self.chapter_ai_preview.setPlainText(self._format_chapter_plan_preview(plan))
            if hasattr(self, "chapter_plan_apply_btn"):
                self.chapter_plan_apply_btn.setVisible(True)
                self.chapter_plan_apply_btn.setEnabled(True)
            self._set_chapter_ai_actions_enabled(True)
            self._chapter_plan_auto_active = False
            self.set_status_tip(f"章节规划已全部生成：{len(generated)}章。预览确认后可一次应用。")
            return

        provider = self._chapter_plan_provider
        model = self._chapter_plan_model
        batch_number = 0
        total_batches = 0
        absolute_start = 0
        absolute_end = 0
        (
            batch_count,
            batch_number,
            total_batches,
            absolute_start,
            absolute_end,
        ) = self._chapter_plan_next_batch_info(state)
        if batch_count <= 0:
            self.on_chapter_plan_failed("章节规划批次范围计算失败，请重试。")
            return
        stage_data = self._creation_wizard_stage_nodes_for_range(
            absolute_start, absolute_end
        )
        creation_wizard_project = bool(
            isinstance(self.current_project, dict)
            and isinstance(self.current_project.get("creation_framework"), dict)
            and self.current_project.get("creation_framework", {}).get("source")
            == "creation_wizard"
        )
        if stage_data:
            saved_schedule = self._chapter_plan_saved_event_schedule(
                state, absolute_start, absolute_end
            )
            schedule_error = (
                self._chapter_plan_event_placement_error(state, saved_schedule, stage_data)
                if saved_schedule else ""
            )
            if schedule_error:
                state = deepcopy(state)
                schedules = state.get("event_schedules", {})
                schedules = deepcopy(schedules) if isinstance(schedules, dict) else {}
                schedules.pop(
                    self._chapter_plan_event_schedule_key(absolute_start, absolute_end),
                    None,
                )
                state["event_schedules"] = schedules
                self._persist_chapter_plan_generation_state(state)
                saved_schedule = {}
            if not saved_schedule:
                self._start_chapter_plan_event_placement_worker(state, stage_data)
                return
        self._chapter_plan_request_kind = "batch"
        context = self._chapter_plan_batch_context(state, batch_count)
        worker = NovelChapterPlanWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            context,
            state.get("target_words", 0),
            state.get("average_chapter_words", 0),
            batch_count,
            state.get("total_chapter_count", 0),
            int(state.get("existing_chapter_count", 0) or 0) + len(generated),
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
            batch_number=batch_number,
            total_batches=total_batches,
            creation_wizard_mode=creation_wizard_project,
            locked_node_schedule=(
                self._chapter_plan_locked_node_schedule(state, absolute_start, absolute_end)
                if stage_data else {}
            ),
        )
        status = f"正在规划第{absolute_start}-{absolute_end}章，共{state.get('total_chapter_count', 0)}章..."
        if state.get("master_plan", {}).get("source") == "imported_framework":
            status = "已读取原框架，" + status

        state["status"] = "generating"
        state.pop("error", None)
        self._persist_chapter_plan_generation_state(state)
        self._show_chapter_plan_generation_progress(state, status)
        self.chapter_plan_worker = worker
        worker._chapter_plan_sequence_token = int(
            getattr(self, "_chapter_plan_sequence_token", 0) or 0
        )
        worker._chapter_plan_project_path = self._canonical_project_path(
            getattr(self, "current_project_path", "")
        )
        worker.diagnostic_project_path = worker._chapter_plan_project_path
        worker.diagnostic_project_title = str(
            (
                self.current_project.get("meta", {})
                if isinstance(self.current_project.get("meta", {}), dict)
                else {}
            ).get("title", "")
            or ""
        ).strip()
        self._connect_chapter_task_worker(
            worker, "on_chapter_plan_ready", "_cleanup_chapter_plan_worker"
        )
        request_id = self._next_novel_diagnostic_request_id("chapter-plan")
        diagnostic_started_at = time.perf_counter()
        self._chapter_plan_diagnostic_request_id = request_id
        self._chapter_plan_diagnostic_started_at = diagnostic_started_at
        worker.diagnostic_request_id = request_id
        worker.diagnostic_started_at = diagnostic_started_at
        worker.capture_raw_model_output = True
        worker.diagnostic_stage = "chapter_plan"
        worker.raw_model_output_metadata = {
            "request_kind": str(self._chapter_plan_request_kind or "batch"),
            "batch_number": int(batch_number or 0),
            "total_batches": int(total_batches or 0),
            "absolute_start": int(absolute_start or 0),
            "absolute_end": int(absolute_end or 0),
            "batch_count": int(batch_count or 0),
        }
        try:
            system_prompt_chars = len(str(worker._analysis_prompt() or ""))
        except Exception:
            system_prompt_chars = 0
        self._log_novel_diagnostic(
            "chapter_plan_request_started",
            action=f"chapter_plan_{self._chapter_plan_request_kind}",
            request_id=request_id,
            provider=provider,
            model=model,
            request_kind=self._chapter_plan_request_kind,
            target_words=int(state.get("target_words", 0) or 0),
            average_chapter_words=int(state.get("average_chapter_words", 0) or 0),
            total_chapter_count=int(state.get("total_chapter_count", 0) or 0),
            requested_chapter_count=requested,
            generated_before=len(generated),
            batch_number=batch_number,
            total_batches=total_batches,
            absolute_start=absolute_start,
            absolute_end=absolute_end,
            input_chars=len(str(context or "")),
            input_utf8_bytes=len(str(context or "").encode("utf-8", errors="replace")),
            system_prompt_chars=system_prompt_chars,
        )
        self._chapter_ai_stop_requested_by_user = False
        self._set_chapter_ai_actions_enabled(False)
        self.set_status_tip(status)
        worker.start()

    def generate_chapter_plan(self):
        if self.writing_worker is not None and self.writing_worker.isRunning():
            self.set_status_tip("AI 写作助手正在生成，请稍等。")
            return
        chapter_plan_worker = getattr(self, "chapter_plan_worker", None)
        if chapter_plan_worker is not None and chapter_plan_worker.isRunning():
            self.set_status_tip("章节规划正在生成，请稍等。")
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self.set_ai_settings_expanded(True)
            self.set_status_tip(f"章节规划生成失败：{error}")
            return
        self._flush_current_editors()
        meta = self.current_project.get("meta", {}) if isinstance(self.current_project, dict) else {}
        framework_parameters = self._chapter_plan_framework_parameters()
        target_words = framework_parameters.get("target_words", 0) or _target_words(meta)
        if target_words <= 0:
            target_words, ok = QInputDialog.getInt(
                self,
                "AI 生成章节规划",
                "目标总字数：",
                200000,
                10000,
                3000000,
                10000,
            )
            if not ok:
                return
        average_chapter_words = framework_parameters.get("average_chapter_words", 0)
        if not average_chapter_words:
            average_chapter_words, ok = QInputDialog.getInt(
                self,
                "AI 生成章节规划",
                "单章目标字数：",
                self._chapter_plan_default_average_words(),
                1000,
                20000,
                500,
            )
            if not ok:
                return
            self.config.setdefault("novel", {})["chapter_plan_average_words"] = int(average_chapter_words)
            try:
                save_config(self.config)
            except Exception as e:
                log_debug("章节规划单章字数设置保存失败", e)
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        existing_count = len(chapters if isinstance(chapters, list) else [])
        total_chapter_count, requested_chapter_count = self._chapter_plan_counts(
            target_words,
            average_chapter_words,
            existing_count,
        )
        if framework_parameters.get("total_chapter_count"):
            total_chapter_count = framework_parameters["total_chapter_count"]
            requested_chapter_count = max(0, total_chapter_count - existing_count)
        if requested_chapter_count <= 0:
            self.set_status_tip("已有章节已覆盖框架规定的全部章节，不再追加规划。")
            return
        self.set_chapter_ai_panel_expanded(True)
        if hasattr(self, "chapter_plan_apply_btn"):
            self.chapter_plan_apply_btn.setVisible(False)
            self.chapter_plan_apply_btn.setEnabled(False)
        saved_state = self.current_project.get("chapter_plan_generation_state", {})
        if self._chapter_plan_state_matches(
            saved_state, target_words, average_chapter_words, total_chapter_count, existing_count
        ) and len(saved_state.get("chapters", [])) <= requested_chapter_count:
            state = deepcopy(saved_state)
        else:
            state = {
                "version": _CHAPTER_PLAN_BATCH_STATE_VERSION,
                "status": "pending",
                "target_words": target_words,
                "average_chapter_words": average_chapter_words,
                "total_chapter_count": total_chapter_count,
                "existing_chapter_count": existing_count,
                "requested_chapter_count": requested_chapter_count,
                "batch_size": _CHAPTER_PLAN_BATCH_SIZE,
                "master_plan": {},
                "chapters": [],
                "creative_intent_contract": _normalize_creative_intent_contract(
                    self.current_project.get("creative_intent_contract", {})
                ),
                "profile_confirmed": False,
                "started_at": now_str(),
            }
            self._chapter_plan_reuse_foundation(state, saved_state)
        if str(state.get("status", "") or "") == "complete":
            self._chapter_plan_auto_active = False
            self._pending_chapter_plan = self._chapter_plan_from_generation_state(state)
            self.chapter_ai_preview.setPlainText(self._format_chapter_plan_preview(self._pending_chapter_plan))
            if hasattr(self, "chapter_plan_apply_btn"):
                self.chapter_plan_apply_btn.setVisible(True)
                self.chapter_plan_apply_btn.setEnabled(True)
            self.set_status_tip("已恢复完成的章节规划，可直接预览并应用。")
            return
        self._pending_chapter_plan = {}
        self._chapter_plan_provider = provider
        self._chapter_plan_model = model
        self._chapter_plan_continue_pending = False
        self._chapter_plan_auto_active = True
        self._chapter_plan_sequence_token = int(getattr(self, "_chapter_plan_sequence_token", 0) or 0) + 1
        self.chapter_ai_stream_text = ""
        self._persist_chapter_plan_generation_state(state)
        self._start_chapter_plan_worker_for_state(state)

    def on_chapter_plan_ready(self, plan):
        if self._forward_chapter_task_signal("on_chapter_plan_ready", plan):
            return
        if not self._chapter_plan_callback_is_current():
            return
        request_id, started_at, worker_diagnostics = self._chapter_plan_signal_diagnostics()
        elapsed_ms = float(worker_diagnostics.get("elapsed_ms", 0) or 0)
        if not elapsed_ms and started_at:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        self._log_novel_diagnostic(
            "chapter_plan_request_completed",
            action=f"chapter_plan_{str(getattr(self, '_chapter_plan_request_kind', '') or '')}",
            request_id=request_id,
            provider=getattr(self, "_chapter_plan_provider", {}),
            model=str(getattr(self, "_chapter_plan_model", "") or ""),
            request_kind=str(getattr(self, "_chapter_plan_request_kind", "") or ""),
            elapsed_ms=elapsed_ms,
            output_json_chars=len(json.dumps(plan or {}, ensure_ascii=False)),
            worker_diagnostics=worker_diagnostics,
        )
        state = deepcopy(self.current_project.get("chapter_plan_generation_state", {}))
        if not isinstance(state, dict) or not state:
            self.on_chapter_plan_failed("章节规划进度状态丢失。")
            return
        chapters = (plan or {}).get("chapters", []) if isinstance(plan, dict) else []
        if not chapters:
            self.on_chapter_plan_failed("AI 没有返回可用章节规划。")
            return
        confirmed_profile = self.current_project.get("narrative_strategy_profile", {})
        confirmed_profile = _normalize_narrative_strategy_profile(confirmed_profile)
        if confirmed_profile:
            state["narrative_strategy_profile"] = deepcopy(confirmed_profile)
            state["profile_confirmed"] = True
            state["profile_hash"] = self._narrative_strategy_profile_hash(confirmed_profile)
        generated = state.get("chapters", []) if isinstance(state.get("chapters"), list) else []
        expected, _batch_number, _total_batches, _absolute_start, _absolute_end = (
            self._chapter_plan_next_batch_info(state)
        )
        if expected <= 0:
            self.on_chapter_plan_failed("章节规划批次范围计算失败，请重试。")
            return
        if len(chapters) != expected:
            self.on_chapter_plan_failed(f"章节规划数量不一致：需要{expected}章，实际{len(chapters)}章。")
            return
        absolute_start = int(state.get("existing_chapter_count", 0) or 0) + len(generated) + 1
        creation_wizard_batch = bool(
            isinstance(self.current_project, dict)
            and isinstance(self.current_project.get("creation_framework"), dict)
            and self.current_project.get("creation_framework", {}).get("source")
            == "creation_wizard"
        )
        if creation_wizard_batch and not self._creation_wizard_stage_nodes_for_range(
            absolute_start,
            absolute_start + expected - 1,
        ):
            self.on_chapter_plan_failed(
                "向导当前阶段资料与返回批次范围不一致，未保存本批章节。"
            )
            return
        if creation_wizard_batch:
            # A wizard batch has no imported chapter-level source to reuse.
            # Ignore stale imported references that may remain on an older
            # project instead of letting them alter the new outline.
            explicit = {}
        else:
            _catalog, _stages, explicit = self._chapter_plan_event_reference()
        incoming = []
        for offset, item in enumerate(chapters):
            chapter = deepcopy(item)
            chapter["index"] = absolute_start + offset
            source_stage = self._chapter_plan_source_stage_for_index(chapter["index"])
            if source_stage:
                chapter["source_stage"] = source_stage.get("name", "")
                chapter["stage_id"] = source_stage.get("id", "")
            if creation_wizard_batch:
                # The wizard schedule is validated in its own request.  The
                # outline request must not invent a second per-chapter event
                # index; chapter order and stage are assigned locally.
                chapter["source_event_ids"] = []
            else:
                chapter["source_event_ids"] = [
                    _canonical_chapter_plan_event_id(value)
                    for value in _normalize_name_list(chapter.get("source_event_ids", []))
                ]
            explicit_item = explicit.get(chapter["index"], {})
            reference = self.current_project.get("imported_chapter_plan_reference", {})
            reference = reference if isinstance(reference, dict) else {}
            if (
                str(chapter.get("outline_mode", "") or "").strip() == "use_imported"
                and not str(explicit_item.get("outline", "") or "").strip()
                and isinstance(chapter.get("source_location"), dict)
                and str(reference.get("local_mapping_status", "") or "").strip().lower() == "pending"
            ):
                source = self.current_project.get("imported_framework_source", {})
                source_text = source.get("text", "") if isinstance(source, dict) else ""
                if source_text:
                    chapter["_framework_source_text"] = source_text
            # The model makes the completeness decision in the same planning
            # call.  Once it explicitly chooses direct reuse, preserve the
            # imported wording byte-for-byte; otherwise its generated outline
            # remains the planning result.  Missing source text always falls
            # back to generation, even if the model emitted a bad flag.
            chapter = self._chapter_plan_apply_imported_outline(chapter, explicit_item)
            incoming.append(chapter)
        if not creation_wizard_batch:
            structured_error = self._validate_creation_chapter_plan_batch(incoming, absolute_start)
            if structured_error:
                self.on_chapter_plan_failed(f"向导阶段事件校验失败：{structured_error}")
                return
            assignment_error = self._chapter_plan_event_assignment_error(generated, incoming)
            if assignment_error:
                self.on_chapter_plan_failed(f"原始框架事件覆盖校验失败：{assignment_error}")
                return
        generated.extend(incoming)
        state["chapters"] = generated
        state["status"] = "complete" if len(generated) >= int(state.get("requested_chapter_count", 0) or 0) else "generating"
        state.pop("error", None)
        self._persist_chapter_plan_generation_state(state)
        if state["status"] == "complete":
            self._chapter_plan_auto_active = False
            self._pending_chapter_plan = self._chapter_plan_from_generation_state(state)
            self.chapter_ai_preview.setPlainText(self._format_chapter_plan_preview(self._pending_chapter_plan))
            if hasattr(self, "chapter_plan_apply_btn"):
                self.chapter_plan_apply_btn.setVisible(True)
                self.chapter_plan_apply_btn.setEnabled(True)
            self.set_status_tip(f"章节规划已全部生成：{len(generated)}章。预览确认后可一次应用。")
        else:
            self._show_chapter_plan_generation_progress(state, "当前批次已保存，正在准备下一批。")
            self._queue_chapter_plan_continuation()

    def _queue_chapter_plan_continuation(self):
        self._chapter_plan_continue_pending = True
        if getattr(self, "chapter_plan_worker", None) is not None:
            return
        self._chapter_plan_continue_pending = False
        state = deepcopy(self.current_project.get("chapter_plan_generation_state", {}))
        token = int(getattr(self, "_chapter_plan_sequence_token", 0) or 0)
        generated = len(state.get("chapters", [])) if isinstance(state.get("chapters"), list) else 0
        self._log_novel_diagnostic(
            "chapter_plan_continuation_scheduled",
            action="chapter_plan_continue",
            request_kind="batch",
            generated_before=generated,
            requested_chapter_count=int(state.get("requested_chapter_count", 0) or 0),
        )

        def continue_planning():
            if (
                getattr(self, "_chapter_plan_auto_active", False)
                and int(getattr(self, "_chapter_plan_sequence_token", 0) or 0) == token
            ):
                self._start_chapter_plan_worker_for_state(state)

        self._schedule_chapter_task_callback(100, lambda tab: (
            tab._start_chapter_plan_worker_for_state(state)
            if tab._chapter_plan_auto_active
            and int(getattr(tab, "_chapter_plan_sequence_token", 0) or 0) == token
            else None
        ))

    def on_chapter_plan_failed(self, err):
        if self._forward_chapter_task_signal("on_chapter_plan_failed", err):
            return
        if not self._chapter_plan_callback_is_current():
            return
        request_id, started_at, worker_diagnostics = self._chapter_plan_signal_diagnostics()
        elapsed_ms = float(worker_diagnostics.get("elapsed_ms", 0) or 0)
        if not elapsed_ms and started_at:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        if getattr(self, "_chapter_ai_stop_requested_by_user", False):
            self._log_novel_diagnostic(
                "chapter_plan_request_stopped",
                level="warning",
                action=f"chapter_plan_{str(getattr(self, '_chapter_plan_request_kind', '') or '')}",
                request_id=request_id,
                provider=getattr(self, "_chapter_plan_provider", {}),
                model=str(getattr(self, "_chapter_plan_model", "") or ""),
                elapsed_ms=elapsed_ms,
                worker_diagnostics=worker_diagnostics,
            )
            self.set_status_tip("章节规划生成已中止。")
            return
        err_text = clean_error_text(err)
        self._log_novel_diagnostic(
            "chapter_plan_request_failed",
            level="error",
            action=f"chapter_plan_{str(getattr(self, '_chapter_plan_request_kind', '') or '')}",
            request_id=request_id,
            provider=getattr(self, "_chapter_plan_provider", {}),
            model=str(getattr(self, "_chapter_plan_model", "") or ""),
            request_kind=str(getattr(self, "_chapter_plan_request_kind", "") or ""),
            elapsed_ms=elapsed_ms,
            error_category=self._novel_diagnostic_error_category(err_text),
            error=err_text,
            worker_diagnostics=worker_diagnostics,
        )
        self._chapter_plan_auto_active = False
        self._chapter_plan_sequence_token = int(getattr(self, "_chapter_plan_sequence_token", 0) or 0) + 1
        state = deepcopy(self.current_project.get("chapter_plan_generation_state", {}))
        if isinstance(state, dict) and state:
            state["status"] = "failed"
            state["error"] = err_text[:500]
            self._persist_chapter_plan_generation_state(state)
            generated = len(state.get("chapters", [])) if isinstance(state.get("chapters"), list) else 0
            requested = int(state.get("requested_chapter_count", 0) or 0)
            self._show_chapter_plan_generation_progress(
                state,
                f"当前批次失败，已保存{generated}/{requested}章；再次点击AI生成章节规划将从这里继续。",
            )
        if hasattr(self, "chapter_plan_apply_btn"):
            self.chapter_plan_apply_btn.setVisible(False)
            self.chapter_plan_apply_btn.setEnabled(False)
        self.set_status_tip(f"章节规划当前批次失败，进度已保存：{err_text[:100]}")

    def _cleanup_chapter_plan_worker(self):
        if self._forward_chapter_task_signal("_cleanup_chapter_plan_worker"):
            return
        worker = self._chapter_task_signal_worker()

        def cleanup(tab):
            try:
                was_current = tab.chapter_plan_worker is worker
                if was_current:
                    tab.chapter_plan_worker = None
                if worker is not None:
                    worker.deleteLater()
                if was_current:
                    continue_pending = bool(getattr(tab, "_chapter_plan_continue_pending", False))
                    tab._set_chapter_ai_actions_enabled(not continue_pending)
                    if getattr(tab, "_chapter_ai_stop_requested_by_user", False):
                        state = deepcopy(tab.current_project.get("chapter_plan_generation_state", {}))
                        if isinstance(state, dict) and state and state.get("status") != "complete":
                            state["status"] = "interrupted"
                            tab._persist_chapter_plan_generation_state(state)
                        tab.set_status_tip("章节规划生成已中止。")
                    tab._chapter_ai_stop_requested_by_user = False
                    if continue_pending:
                        tab._chapter_plan_continue_pending = False
                        state = deepcopy(tab.current_project.get("chapter_plan_generation_state", {}))
                        token = int(getattr(tab, "_chapter_plan_sequence_token", 0) or 0)
                        tab._schedule_chapter_task_callback(
                            100,
                            lambda owner, s=state, t=token: (
                                owner._start_chapter_plan_worker_for_state(s)
                                if getattr(owner, "_chapter_plan_auto_active", False)
                                and int(getattr(owner, "_chapter_plan_sequence_token", 0) or 0) == t
                                else None
                            ),
                        )
            except Exception as e:
                log_debug("小说章节规划线程清理失败", e)

        self._schedule_chapter_task_callback(0, cleanup)

    def apply_chapter_plan(self):
        plan = deepcopy(getattr(self, "_pending_chapter_plan", {}) or {})
        chapters_plan = plan.get("chapters", []) if isinstance(plan, dict) else []
        chapters_plan = [item for item in chapters_plan if isinstance(item, dict)]
        if not chapters_plan:
            self.set_status_tip("没有可应用的章节规划。")
            return
        self._flush_current_editors()
        chapters = self.current_project.setdefault("chapters", [])
        if not isinstance(chapters, list):
            chapters = []
            self.current_project["chapters"] = chapters
        existing_count = len(chapters)
        if existing_count:
            ret = QMessageBox.question(
                self,
                "应用章节规划",
                f"当前已有 {existing_count} 章。将把这 {len(chapters_plan)} 章追加到章节列表后面，不会覆盖已有章节。继续吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if ret != QMessageBox.Yes:
                self.set_status_tip("已取消应用章节规划。")
                return
        first_new_index = len(chapters)
        for item in chapters_plan:
            chapter = _new_chapter(len(chapters))
            title = str(item.get("title", "") or "").strip()
            if title:
                chapter["title"] = title
            target_words = str(item.get("target_words", "") or "").strip()
            if target_words:
                chapter["draft_words"] = target_words
            chapter["outline"] = self._chapter_plan_outline_for_item(item)
            for key in ("narrative_stage", "source_stage", "dominant_line", "ending_hook"):
                chapter[key] = str(item.get(key, "") or "").strip()
            if not chapter["source_stage"]:
                chapter["source_stage"] = chapter["narrative_stage"]
            chapter["linked_characters"] = _normalize_name_list(item.get("characters", []))
            chapter["source_event_ids"] = [
                _canonical_chapter_plan_event_id(value)
                for value in _normalize_name_list(item.get("source_event_ids", []))
            ]
            chapter["chapter_plan_structured"] = {
                "stage_id": str(item.get("stage_id", "") or "").strip().upper(),
                "start_state": deepcopy(item.get("start_state", {})) if isinstance(item.get("start_state"), dict) else {},
                "scene_chain": deepcopy(item.get("scene_chain", [])) if isinstance(item.get("scene_chain"), list) else [],
                "conflict": deepcopy(item.get("conflict", {})) if isinstance(item.get("conflict"), dict) else {},
                "required_facts": _normalize_name_list(item.get("required_facts", [])),
                "continuity_delta": deepcopy(item.get("continuity_delta", {})) if isinstance(item.get("continuity_delta"), dict) else {},
                "ending_change": deepcopy(item.get("ending_change", {})) if isinstance(item.get("ending_change"), dict) else {},
            }
            chapter["status"] = "大纲"
            chapters.append(chapter)
        plan_summary = str(plan.get("summary", "") or "").strip()
        if plan_summary:
            note_block = f"阶段规划摘要：\n{plan_summary}"
            current_note = str(self.current_project.get("draft_note", "") or "").strip()
            if plan_summary not in current_note:
                self.current_project["draft_note"] = f"{current_note}\n\n{note_block}".strip() if current_note else note_block
                if hasattr(self, "draft_note_edit"):
                    self.draft_note_edit.setPlainText(self.current_project["draft_note"])
        self.current_project.pop("chapter_plan_generation_state", None)
        self._pending_chapter_plan = {}
        if hasattr(self, "chapter_plan_apply_btn"):
            self.chapter_plan_apply_btn.setVisible(False)
            self.chapter_plan_apply_btn.setEnabled(False)
        self.chapter_ai_preview.clear()
        self._auto_update_project_status(chapter_plan_applied=True)
        self._note_project_dirty()
        self._reload_chapter_list(first_new_index)
        self._schedule_refresh(include_manuscript=True)
        self.set_status_tip(f"已追加 {len(chapters_plan)} 章章节规划，可从第一章新规划开始逐章扩写。")

    def _chapter_ai_context(self, action):
        perf_start = time.perf_counter()
        self._flush_current_editors()
        context = _build_chapter_ai_context(self._ai_project_snapshot(), self.current_chapter_index, action)
        self._log_novel_perf(
            "AI写作-构建上下文",
            perf_start,
            threshold_ms=80,
            action=action,
            chapter=self.current_chapter_index + 1,
            context_len=len(context),
            **self._novel_perf_summary(),
        )
        return context

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

    def _discard_partial_preview_for_auto_rewrite(self, source="auto_expand"):
        if not self._has_partial_chapter_ai_preview():
            return False
        # The user (or the automatic queue) is explicitly restarting a
        # half-finished AI result. Carry that intent into the sequence entry
        # so an existing chapter body is rewritten only in this case.
        self._chapter_ai_force_rewrite = True
        action = str(getattr(self, "_chapter_ai_preview_action", "") or "draft")
        preview_text = str(self.chapter_ai_preview.toPlainText() or "").strip()
        request_id = str(getattr(self, "_chapter_ai_diagnostic_request_id", "") or "")
        snapshot_path = ""
        try:
            snapshot_path = self._save_chapter_ai_failure_snapshot(
                action,
                request_id,
                error="扩写重新启动：半成品不参与续写，改为从干净上下文重写",
                validation_payload="半成品仅保存到诊断快照，不写入章节正文。",
            )
        except Exception as exc:
            log_debug("自动扩写半成品诊断快照保存失败", exc)
        source = str(source or "auto_expand").strip()
        self._log_novel_diagnostic(
            "auto_expand_partial_preview_discarded"
            if source == "auto_expand" else "chapter_ai_partial_preview_discarded",
            level="warning",
            action=action,
            chapter_id=self._current_chapter_id(),
            partial_preview_chars=len(preview_text),
            diagnostic_snapshot_path=snapshot_path,
            restart_mode="rewrite",
            restart_source=source,
        )
        self.chapter_ai_preview.clear()
        self.chapter_ai_stream_text = ""
        self._chapter_ai_resume_prefix = ""
        self._set_partial_chapter_ai_preview_state(False)
        self._reset_chapter_ai_sequence()
        return True

    def _on_chapter_ai_preview_text_changed(self):
        self._refresh_chapter_ai_action_labels()

    def _chapter_ai_context_with_preview(self, action):
        perf_start = time.perf_counter()
        self._flush_current_editors()
        context = _build_chapter_ai_context(
            self._ai_project_snapshot(), self.current_chapter_index, action
        )
        self._log_novel_perf(
            "AI写作-构建上下文",
            perf_start,
            threshold_ms=80,
            action=action,
            chapter=self.current_chapter_index + 1,
            context_len=len(context),
            preview=False,
            **self._novel_perf_summary(),
        )
        return context

    def _start_chapter_context_build(
        self,
        action,
        mode,
        project_snapshot=None,
        chapter_index=None,
        chapter_id="",
        rewrite_on_ready=False,
        status_text="正在后台组装本章资料...",
    ):
        """Build the prompt asynchronously and dispatch only if its target is still current."""
        # Lightweight state tests construct the tab without __init__. Keep that
        # path synchronous while the real UI always uses the background worker.
        if not hasattr(self, "context_build_worker"):
            rewrite_backup = None
            if rewrite_on_ready:
                chapters = self.current_project.get("chapters", [])
                chapter = chapters[self.current_chapter_index]
                rewrite_backup = deepcopy(chapter)
                self._reset_current_chapter_for_ai_rewrite(chapter)
            try:
                context = self._chapter_ai_context_with_preview(action)
            except Exception as exc:
                if isinstance(rewrite_backup, dict):
                    chapter.clear()
                    chapter.update(rewrite_backup)
                    for attr_name, field in (
                        ("chapter_text", "text"),
                        ("chapter_summary", "summary"),
                        ("chapter_key_facts", "key_facts"),
                    ):
                        editor = getattr(self, attr_name, None)
                        if editor is not None:
                            editor.setPlainText(str(chapter.get(field, "") or ""))
                context_chapter_id = str(chapter_id or self._current_chapter_id())
                retry_scheduled = self._schedule_transient_chapter_ai_retry(
                    "context_build",
                    str(exc),
                    force_retry=True,
                    retry_context="context_build",
                    retry_chapter_id=context_chapter_id,
                    retry_callback=lambda tab: tab._start_chapter_context_build(
                        action,
                        mode,
                        project_snapshot=None,
                        chapter_index=chapter_index,
                        chapter_id=context_chapter_id,
                        rewrite_on_ready=rewrite_on_ready,
                        status_text=status_text,
                    ),
                )
                self._log_novel_diagnostic(
                    "chapter_ai_context_build_failed",
                    level="error",
                    action=action,
                    chapter_id=chapter_id or self._current_chapter_id(),
                    error_category="context_build",
                    **self._novel_exception_details(exc),
                )
                if retry_scheduled:
                    return False
                if getattr(self, "_auto_expand_all_active", False):
                    self._stop_auto_expand_all(
                        f"自动扩写已停止：第{self.current_chapter_index + 1}章上下文组装失败。"
                    )
                self._reset_chapter_ai_sequence()
                self._show_chapter_ai_failure(str(exc))
                return False
            if mode == "style_draft":
                chapters = self.current_project.get("chapters", [])
                chapter = chapters[self.current_chapter_index]
                self._clear_transient_chapter_ai_retry("context_build")
                self._mark_current_chapter_ai_sync_pending(chapter)
                self._start_style_locked_draft(context)
            else:
                self._clear_transient_chapter_ai_retry("context_build")
                self._start_chapter_ai_worker(action, context, status_text)
            return True

        worker = getattr(self, "context_build_worker", None)
        if worker is not None and worker.isRunning():
            self.set_status_tip("正在组装当前章节资料，请稍等。")
            return False
        index = self.current_chapter_index if chapter_index is None else int(chapter_index)
        target_id = str(chapter_id or self._current_chapter_id())
        snapshot = deepcopy(project_snapshot) if isinstance(project_snapshot, dict) else self._ai_project_snapshot()
        self._context_build_token = int(getattr(self, "_context_build_token", 0) or 0) + 1
        token = str(self._context_build_token)
        self._context_build_pending = {
            "token": token,
            "action": str(action or ""),
            "mode": str(mode or "direct"),
            "chapter_id": target_id,
            "chapter_index": index,
            "project_path": os.path.abspath(str(self.current_project_path or "")),
            "rewrite_on_ready": bool(rewrite_on_ready),
            "status_text": str(status_text or ""),
            "started_at": time.perf_counter(),
        }
        self._set_chapter_ai_actions_enabled(False)
        self.set_chapter_ai_panel_expanded(True)
        self.set_status_tip(status_text or "正在后台组装本章资料...")
        worker = NovelContextBuildWorker(
            token,
            action,
            snapshot,
            index,
            self.current_project_path,
            target_id,
        )
        self.context_build_worker = worker
        self._connect_chapter_task_worker(
            worker, "_on_chapter_context_ready", "_cleanup_chapter_context_worker"
        )
        try:
            worker.start()
        except Exception as exc:
            self.context_build_worker = None
            retry_scheduled = self._schedule_transient_chapter_ai_retry(
                "context_build",
                str(exc),
                force_retry=True,
                retry_context="context_build",
                retry_chapter_id=target_id,
                retry_callback=lambda tab: tab._start_chapter_context_build(
                    action,
                    mode,
                    project_snapshot=None,
                    chapter_index=index,
                    chapter_id=target_id,
                    rewrite_on_ready=rewrite_on_ready,
                    status_text=status_text,
                ),
            )
            if not retry_scheduled:
                raise
            self._log_novel_diagnostic(
                "chapter_context_worker_start_failed",
                level="error",
                action=action,
                chapter_id=target_id,
                error_category="context_build",
                **self._novel_exception_details(exc),
            )
        return True

    def _context_build_target_is_current(self, pending):
        if not isinstance(pending, dict):
            return False
        current_path = os.path.abspath(str(getattr(self, "current_project_path", "") or ""))
        return bool(
            current_path == str(pending.get("project_path", "") or "")
            and self._current_chapter_id() == str(pending.get("chapter_id", "") or "")
        )

    def _on_chapter_context_ready(self, token, action, chapter_id, context):
        if self._forward_chapter_task_signal(
            "_on_chapter_context_ready", token, action, chapter_id, context
        ):
            return
        pending = dict(getattr(self, "_context_build_pending", {}) or {})
        if str(token or "") != str(pending.get("token", "") or ""):
            return
        if not self._context_build_target_is_current(pending):
            self._context_build_pending = {}
            self._reset_chapter_ai_sequence()
            self._set_chapter_ai_actions_enabled(True)
            self.set_status_tip("章节或项目已切换，旧章节资料已丢弃，不会写入当前项目。")
            return
        self._clear_transient_chapter_ai_retry(
            "context_build",
            chapter_id=str(pending.get("chapter_id", "") or ""),
        )
        elapsed_ms = (time.perf_counter() - float(pending.get("started_at", 0.0) or 0.0)) * 1000
        self._log_novel_diagnostic(
            "chapter_context_built_in_background",
            action=action,
            chapter_id=chapter_id,
            context_chars=len(str(context or "")),
            elapsed_ms=round(elapsed_ms, 1),
        )
        self._context_build_pending = {}
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        index = int(pending.get("chapter_index", -1) or 0)
        chapter = chapters[index] if 0 <= index < len(chapters) else None
        if pending.get("rewrite_on_ready") and isinstance(chapter, dict):
            self._reset_current_chapter_for_ai_rewrite(chapter)
        mode = str(pending.get("mode", "direct") or "direct")
        if mode == "style_draft":
            self._mark_current_chapter_ai_sync_pending(chapter)
            self._start_style_locked_draft(context)
            return
        self.chapter_ai_stream_text = ""
        self._set_partial_chapter_ai_preview_state(False)
        self._chapter_ai_resume_prefix = ""
        self.chapter_ai_preview.setPlainText("")
        self._start_chapter_ai_worker(action, context, str(pending.get("status_text", "") or ""))

    def _on_chapter_context_failed(self, token, action, chapter_id, error):
        if self._forward_chapter_task_signal(
            "_on_chapter_context_failed", token, action, chapter_id, error
        ):
            return
        pending = dict(getattr(self, "_context_build_pending", {}) or {})
        if str(token or "") != str(pending.get("token", "") or ""):
            return
        self._context_build_pending = {}
        target_chapter_id = str(
            pending.get("chapter_id", "") or chapter_id or self._current_chapter_id()
        )
        retry_scheduled = self._schedule_transient_chapter_ai_retry(
            "context_build",
            str(error),
            force_retry=True,
            retry_context="context_build",
            retry_chapter_id=target_chapter_id,
            retry_callback=lambda tab: tab._start_chapter_context_build(
                action,
                str(pending.get("mode", "direct") or "direct"),
                project_snapshot=None,
                chapter_index=int(pending.get("chapter_index", -1)),
                chapter_id=target_chapter_id,
                rewrite_on_ready=bool(pending.get("rewrite_on_ready", False)),
                status_text=str(pending.get("status_text", "") or ""),
            ),
        )
        self._log_novel_diagnostic(
            "chapter_ai_context_build_failed",
            level="error",
            action=action,
            chapter_id=chapter_id,
            error_category="context_build",
            **self._novel_exception_details(error),
        )
        if retry_scheduled:
            return
        if getattr(self, "_auto_expand_all_active", False):
            self._stop_auto_expand_all(
                f"自动扩写已停止：第{int(pending.get('chapter_index', 0) or 0) + 1}章上下文组装失败。"
            )
        self._reset_chapter_ai_sequence()
        self._set_chapter_ai_actions_enabled(True)
        self._show_chapter_ai_failure(str(error))

    def _cleanup_chapter_context_worker(self):
        if self._forward_chapter_task_signal("_cleanup_chapter_context_worker"):
            return
        worker = self._chapter_task_signal_worker()
        if self.context_build_worker is worker:
            self.context_build_worker = None
        if worker is not None:
            worker.deleteLater()

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
        if (
            getattr(self, "_chapter_ai_preview_is_partial", False)
            and getattr(self, "_chapter_ai_preview_action", "") == "draft"
            and not str(self.chapter_ai_preview.toPlainText() or "").strip()
        ):
            self._chapter_ai_preview_is_partial = False
            self._chapter_ai_preview_action = ""
            self._chapter_ai_preview_chapter_id = ""
        btn.setText("扩写正文并补提纲和摘要")
        if self._has_partial_chapter_ai_preview():
            btn.setToolTip("重新扩写时会丢弃未完成预览，从章节提纲重写整章")
        else:
            btn.setToolTip("先扩写完整正文，再根据实际正文补提纲和摘要/关键事实")

    def _reset_chapter_ai_sequence(self):
        self._chapter_ai_sequence_active = False
        self._chapter_ai_sequence_chapter_id = ""
        self._chapter_ai_sequence_started_outline = ""

    def _stage_chapter_ai_draft_for_memory_finalize(self, final_text):
        """Keep a complete draft in preview until the state transaction commits."""
        candidate = str(final_text or "").strip()
        if not candidate:
            self._fail_memory_sync("正文终稿为空，无法整理章节状态")
            return False
        candidate, replacements = _sanitize_prose_internal_references(
            self.current_project if isinstance(self.current_project, dict) else {},
            candidate,
            strip_metadata=True,
        )
        if replacements:
            self._log_novel_diagnostic(
                "chapter_prose_internal_reference_sanitized",
                level="warning",
                chapter_id=self._current_chapter_id(),
                replacements=replacements,
                before_chars=len(str(final_text or "")),
                after_chars=len(candidate),
            )
        self._chapter_ai_style_execution = ""
        self._chapter_ai_style_plan = ""
        self._chapter_ai_style_candidate = candidate
        self.chapter_ai_preview.setPlainText(candidate)
        self._clear_transient_chapter_ai_retry("draft")
        self._start_memory_finalize(candidate)
        return True

    def _auto_expand_chapter_has_committed_memory(self, chapter):
        if not isinstance(chapter, dict):
            return False
        if not all(
            str(chapter.get(key, "") or "").strip()
            for key in ("text", "summary", "key_facts")
        ):
            return False
        if str(chapter.get("memory_sync_status", "") or "") != "complete":
            return False
        if str(chapter.get("memory_sync_error", "") or "").strip():
            return False
        return self._chapter_has_committed_memory_marker(chapter)

    def _chapter_has_committed_memory_marker(self, chapter):
        if not isinstance(chapter, dict):
            return False
        try:
            chapter_revision = int(chapter.get("memory_revision", 0) or 0)
        except Exception:
            chapter_revision = 0
        memory = self.current_project.get("long_form_memory", {}) if isinstance(self.current_project, dict) else {}
        try:
            memory_revision = int(memory.get("revision", 0) or 0) if isinstance(memory, dict) else 0
        except Exception:
            memory_revision = 0
        return bool(
            chapter_revision > 0
            and chapter_revision <= memory_revision
            and str(chapter.get("memory_update_hash", "") or "").strip()
        )

    @staticmethod
    def _reset_chapter_data_for_ai_rewrite(chapter):
        if not isinstance(chapter, dict):
            return False
        chapter["text"] = ""
        chapter["summary"] = ""
        chapter["key_facts"] = ""
        chapter["actual_linked_character_ids"] = []
        chapter["memory_selection"] = {}
        chapter["state_delta"] = {}
        chapter["long_term_events"] = []
        chapter["state_reconciliation"] = {}
        chapter["fact_lifecycle_review"] = {}
        chapter["state_lifecycle_review"] = {}
        chapter["memory_sync_status"] = "pending"
        chapter["memory_revision"] = 0
        chapter["memory_update_hash"] = ""
        chapter["memory_sync_error"] = ""
        chapter["memory_boundary_integrity"] = {}
        chapter["memory_reconciliation_status"] = ""
        chapter["memory_reconciliation_error"] = ""
        chapter["ai_generation_checkpoint"] = {}
        chapter["auto_expand_resume_required"] = False
        chapter["analysis_hash"] = ""
        chapter["analysis_hash_version"] = ""
        chapter["analysis_analyzed_at"] = ""
        chapter["analysis_baseline"] = ""
        chapter["analysis_linked_hash"] = ""
        chapter["analysis_status"] = "unwritten"
        chapter["analysis_status_hash"] = ""
        chapter["analysis_status_version"] = "1"
        return True

    @staticmethod
    def _reset_foreshadow_runtime_state_for_ai_rewrite(project):
        """Reset generated foreshadow progress while keeping its writing plan."""
        if not isinstance(project, dict):
            return 0
        items = project.get("foreshadow_items", [])
        if not isinstance(items, list):
            return 0
        reset_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            item["status"] = "未埋"
            item["revealed"] = ""
            item["remaining_secret"] = ""
            reset_count += 1
        return reset_count

    def _reset_current_chapter_for_ai_rewrite(self, chapter):
        if not self._reset_chapter_data_for_ai_rewrite(chapter):
            return False
        for attr_name in ("chapter_text", "chapter_summary", "chapter_key_facts"):
            editor = getattr(self, attr_name, None)
            if editor is None:
                continue
            if hasattr(self, "_set_text_without_signals"):
                self._set_text_without_signals(editor, "")
            else:
                editor.setPlainText("")
        return True

    @staticmethod
    def _chapter_has_generated_output(chapter):
        if not isinstance(chapter, dict):
            return False
        if any(
            str(chapter.get(key, "") or "").strip()
            for key in ("text", "summary", "key_facts")
        ):
            return True
        if str(chapter.get("status", "大纲") or "大纲").strip() in {"写作中", "已完成", "待重写"}:
            return True
        if any(
            chapter.get(key)
            for key in (
                "actual_linked_character_ids",
                "state_delta",
                "long_term_events",
                "state_reconciliation",
                "fact_lifecycle_review",
                "state_lifecycle_review",
                "memory_boundary_integrity",
                "ai_generation_checkpoint",
                "analysis_hash",
                "analysis_baseline",
            )
        ):
            return True
        try:
            if int(chapter.get("memory_revision", 0) or 0) > 0:
                return True
        except (TypeError, ValueError):
            pass
        return bool(
            str(chapter.get("memory_update_hash", "") or "").strip()
            or bool(chapter.get("auto_expand_resume_required", False))
        )

    def _chapter_clear_has_active_work(self):
        if any(
            bool(getattr(self, name, False))
            for name in (
                "_auto_expand_all_active",
                "_auto_expand_all_waiting_next",
                "_chapter_ai_sequence_active",
                "_chapter_ai_transient_retry_pending",
                "_chapter_plan_auto_active",
            )
        ):
            return True
        for name in ("writing_worker", "chapter_plan_worker", "context_build_worker"):
            worker = getattr(self, name, None)
            if worker is None:
                continue
            try:
                if worker.isRunning():
                    return True
            except Exception:
                continue
        detached = self._current_background_chapter_runner()
        if detached is not None and not getattr(self, "_is_detached_auto_runner", False):
            try:
                if detached._status_has_active_work():
                    return True
            except Exception:
                return True
        return False

    def reset_all_chapters(self):
        """Reset all generated chapter results while keeping the chapter plan."""
        if self._chapter_clear_has_active_work():
            self.set_status_tip("当前仍有 AI 任务在运行，完成或中止后才能重置章节。")
            return

        self._flush_current_editors()
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        chapters = chapters if isinstance(chapters, list) else []
        if not chapters:
            self.set_status_tip("当前项目还没有章节。")
            return

        generated_count = sum(
            1
            for chapter in chapters
            if self._chapter_has_generated_output(chapter)
        )
        if not generated_count:
            self.set_status_tip("当前没有需要重置的章节内容。")
            return
        ret = QMessageBox.question(
            self,
            "重置所有章节确认",
            "确定重置所有章节吗？\n\n"
            f"将清除 {generated_count} 个章节的正文、摘要、关键事实、状态整理、"
            "分析缓存、修复检查点和自动扩写恢复标记，并重置长期记忆与伏笔运行状态。\n\n"
            "章节标题、提纲、阶段、扩写字数和规划关联人物会保留，"
            "重置后可以从第1章重新扩写。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return

        project_snapshot = deepcopy(self.current_project)
        backup_path = ""
        try:
            backup_path = unique_project_backup_path(
                self._project_title() or "未命名小说",
                "重置所有章节前备份",
            )
            save_project_file(backup_path, project_snapshot)
        except Exception as exc:
            self._log_novel_diagnostic(
                "chapter_reset_backup_failed",
                level="error",
                chapter_count=len(chapters),
                error_category="storage",
                **self._novel_exception_details(exc),
            )
            self.set_status_tip("重置未执行：重置前备份失败。")
            QMessageBox.warning(self, "重置失败", "重置前备份失败，原章节内容未改变。")
            return

        raw_selected_index = getattr(self, "current_chapter_index", -1)
        selected_index = int(raw_selected_index) if raw_selected_index is not None else -1
        raw_selected_foreshadow_index = getattr(self, "current_foreshadow_index", -1)
        selected_foreshadow_index = (
            int(raw_selected_foreshadow_index)
            if raw_selected_foreshadow_index is not None else -1
        )
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            self._reset_chapter_data_for_ai_rewrite(chapter)
            chapter["status"] = "大纲"
        self._reset_foreshadow_runtime_state_for_ai_rewrite(self.current_project)
        self.current_project["long_form_memory"] = _default_long_form_memory()
        self._clear_candidate_analysis_state()
        self._reload_chapter_list(selected_index)
        # _save_current_work flushes all visible editors before writing. Reload
        # the foreshadow editor after resetting the project data so a stale
        # selected record cannot overwrite its reset runtime status.
        self._reload_foreshadow_list(selected_foreshadow_index)

        self.chapter_ai_preview.clear()
        self.chapter_ai_stream_text = ""
        self._chapter_ai_resume_prefix = ""
        self._set_partial_chapter_ai_preview_state(False)
        self._reset_chapter_ai_sequence()
        self._reset_chapter_ai_style_retry()
        self._note_project_dirty()
        saved_path = self._save_current_work(
            "重置所有章节",
            refresh_project_list=False,
        )
        if not saved_path:
            self.current_project.clear()
            self.current_project.update(project_snapshot)
            self._reload_chapter_list(selected_index)
            self._reload_foreshadow_list(selected_foreshadow_index)
            self.set_status_tip("重置失败：项目保存失败，已恢复原章节内容。")
            QMessageBox.warning(self, "重置失败", "项目保存失败，原章节内容已恢复。")
            return

        self._notify_project_store_changed()
        self.set_status_tip(
            f"已重置所有章节，可以从第1章重新扩写。已自动备份为：{os.path.basename(backup_path)}"
        )

    def clear_current_chapter(self):
        """Compatibility alias for callers of the previous single-chapter action."""
        return self.reset_all_chapters()

    def _mark_current_chapter_ai_sync_pending(self, chapter):
        if not isinstance(chapter, dict):
            return
        chapter["auto_expand_resume_required"] = True
        pending = getattr(self, "_chapter_ai_memory_pending", {})
        if (
            isinstance(pending, dict)
            and pending.get("already_committed")
            and str(chapter.get("memory_sync_status", "") or "") == "complete"
        ):
            # A legacy boundary checkpoint may be created after the state
            # transaction already committed. Keep that marker idempotent
            # while only the semantic reconciliation is resumed.
            chapter["memory_sync_error"] = ""
            if hasattr(self, "_note_project_dirty"):
                self._note_project_dirty()
            self._persist_ai_generation_state()
            return
        chapter["memory_sync_status"] = "pending"
        chapter["memory_sync_error"] = ""
        if hasattr(self, "_note_project_dirty"):
            self._note_project_dirty()
        self._persist_ai_generation_state()

    def _clear_current_chapter_ai_resume_required(self):
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if not (0 <= self.current_chapter_index < len(chapters)):
            return False
        chapter = chapters[self.current_chapter_index]
        if not isinstance(chapter, dict):
            return False
        changed = bool(chapter.get("auto_expand_resume_required", False))
        chapter["auto_expand_resume_required"] = False
        return changed

    def _auto_expand_chapter_needs_work(self, chapter):
        if not isinstance(chapter, dict):
            return False
        if (
            str(chapter.get("memory_reconciliation_status", "") or "") in {"pending", "failed"}
            and isinstance(chapter.get("ai_generation_checkpoint"), dict)
            and str(chapter.get("ai_generation_checkpoint", {}).get("stage", "") or "")
            == "memory_reconcile"
        ):
            return True
        if not str(chapter.get("text", "") or "").strip():
            return True
        if self._auto_expand_chapter_has_committed_memory(chapter):
            return False
        if self._memory_finalize_checkpoint_text(chapter):
            return True
        if bool(chapter.get("auto_expand_resume_required", False)):
            return True
        if (
            str(chapter.get("memory_sync_status", "") or "") == "failed"
            or str(chapter.get("memory_sync_error", "") or "").strip()
        ):
            return True
        return not (
            str(chapter.get("summary", "") or "").strip()
            and str(chapter.get("key_facts", "") or "").strip()
        )

    def _auto_expand_pending_indexes(self):
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        return [
            index
            for index, chapter in enumerate(chapters if isinstance(chapters, list) else [])
            if self._auto_expand_chapter_needs_work(chapter)
        ]

    def _persist_completed_auto_expand_resume_flags(self):
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        chapters = chapters if isinstance(chapters, list) else []
        completed = [
            chapter
            for chapter in chapters
            if (
                isinstance(chapter, dict)
                and bool(chapter.get("auto_expand_resume_required", False))
                and self._auto_expand_chapter_has_committed_memory(chapter)
            )
        ]
        if not completed:
            return True
        for chapter in completed:
            chapter["auto_expand_resume_required"] = False
        if hasattr(self, "_note_project_dirty"):
            self._note_project_dirty()
        saved_path = self._save_current_work(
            "恢复自动扩写完成状态",
            refresh_project_list=False,
        )
        if saved_path:
            return True
        for chapter in completed:
            chapter["auto_expand_resume_required"] = True
        if hasattr(self, "_note_project_dirty"):
            self._note_project_dirty()
        self._persist_ai_generation_state()
        self._log_novel_diagnostic(
            "auto_expand_resume_state_save_failed",
            level="error",
            affected_chapter_ids=[
                str(chapter.get("id", "") or "") for chapter in completed
                if isinstance(chapter, dict)
            ],
            error="已完成章节的续跑状态保存失败",
            error_category="storage",
        )
        self.set_status_tip("自动扩写未启动：已完成章节的续跑状态保存失败。")
        return False

    def _auto_expand_all_chapter_progress(self):
        project = self.current_project if isinstance(getattr(self, "current_project", None), dict) else {}
        chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
        total = len(chapters)
        if not total:
            return 0, 0

        current_id = str(getattr(self, "_auto_expand_all_current_chapter_id", "") or "")
        if current_id:
            for index, chapter in enumerate(chapters):
                if isinstance(chapter, dict) and str(chapter.get("id", "") or "") == current_id:
                    return index + 1, total

        if bool(getattr(self, "_auto_expand_all_active", False)):
            pending = self._auto_expand_pending_indexes()
            if pending:
                return pending[0] + 1, total

        try:
            current_index = int(getattr(self, "current_chapter_index", -1))
        except (TypeError, ValueError):
            current_index = -1
        if 0 <= current_index < total:
            return current_index + 1, total
        return 0, total

    def _set_auto_expand_all_button_text(self):
        if not hasattr(self, "auto_expand_all_btn"):
            return
        if getattr(self, "_auto_expand_all_active", False):
            current, total = self._auto_expand_all_chapter_progress()
            progress = f" {current}/{total}" if current and total else ""
            self.auto_expand_all_btn.setText(f"自动扩写全部{progress}")
        else:
            self.auto_expand_all_btn.setText("自动扩写全部")

    def _stop_auto_expand_all(self, message=""):
        message_text = str(message or "").strip()
        if message_text:
            if "完成" in message_text and not any(
                marker in message_text for marker in ("失败", "不完整", "无法", "停止")
            ):
                level = "info"
            elif "中止" in message_text:
                level = "warning"
            else:
                level = "error"
            self._log_novel_diagnostic(
                "auto_expand_stopped",
                level=level,
                reason=message_text,
                reason_code=self._auto_expand_stop_reason_code(message_text),
            )
        self._auto_expand_all_active = False
        self._auto_expand_all_waiting_next = False
        self._auto_expand_all_current_chapter_id = ""
        self._set_auto_expand_all_button_text()
        if message:
            self.set_status_tip(message)
        worker = getattr(self, "writing_worker", None)
        plan_worker = getattr(self, "chapter_plan_worker", None)
        if (
            not (worker is not None and worker.isRunning())
            and not (plan_worker is not None and plan_worker.isRunning())
            and not getattr(self, "_chapter_ai_transient_retry_pending", False)
        ):
            self._set_chapter_ai_actions_enabled(True)

    def _start_detached_single_chapter_ai(self):
        self._flush_current_editors()
        if not self._has_saved_project_path():
            if not self.save_current_project():
                return
        source_path = self._canonical_project_path(self.current_project_path)
        if not source_path or source_path == self._canonical_project_path(NOVEL_DRAFT_FILE):
            QMessageBox.warning(self, "单章扩写失败", "请先把小说保存为项目，再启动后台单章扩写。")
            return
        runner = self._background_chapter_runner_for_path(source_path)
        if runner is not None:
            title = str((runner.current_project.get("meta", {}) or {}).get("title", "") or "当前项目")
            task_label = (
                "后台自动扩写"
                if str(getattr(runner, "_background_task_kind", "") or "") == "auto_expand"
                else "后台单章扩写"
            )
            self.set_status_tip(f"《{title}》仍在{task_label}，可继续操作其他章节。")
            return
        # Chapter indexes are zero-based. Preserve index 0 instead of treating
        # it as a missing value when the first chapter is selected.
        chapter_index = int(getattr(self, "current_chapter_index", -1))
        chapter_id = self._current_chapter_id()
        if chapter_index < 0 or not chapter_id:
            self.set_status_tip("当前没有可扩写的章节。")
            return
        self._set_chapter_ai_actions_enabled(False)
        self.set_status_tip("正在保存项目并启动后台单章扩写...")
        QTimer.singleShot(
            0,
            lambda p=source_path, i=chapter_index, c=chapter_id: self._launch_detached_single_chapter_ai(
                p, i, c
            ),
        )

    def start_auto_expand_all_chapters(self):
        if not hasattr(self, "_is_detached_auto_runner") or self._is_detached_auto_runner:
            self._start_auto_expand_all_local()
            return
        self._flush_current_editors()
        if not self._has_saved_project_path():
            if not self.save_current_project():
                return
        source_path = self._canonical_project_path(self.current_project_path)
        if not source_path or source_path == self._canonical_project_path(NOVEL_DRAFT_FILE):
            QMessageBox.warning(self, "自动扩写失败", "请先把小说保存为项目，再启动后台自动扩写。")
            return
        runner = self._background_chapter_runner_for_path(source_path)
        if runner is not None:
            title = str((runner.current_project.get("meta", {}) or {}).get("title", "") or "当前项目")
            task_label = (
                "后台自动扩写"
                if str(getattr(runner, "_background_task_kind", "") or "") == "auto_expand"
                else "后台章节任务"
            )
            self.set_status_tip(f"《{title}》仍在{task_label}，可继续操作其他小说。")
            return
        if hasattr(self, "auto_expand_all_btn"):
            self.auto_expand_all_btn.setEnabled(False)
            self.auto_expand_all_btn.setText("正在启动后台扩写...")
        self.set_status_tip("正在保存项目并启动后台自动扩写...")
        QTimer.singleShot(0, lambda p=source_path: self._launch_detached_auto_expand(p))

    def _create_detached_chapter_runner(
        self, source_path, task_kind, chapter_index=None, chapter_id=""
    ):
        source_path = self._canonical_project_path(source_path)
        data = load_json_file(source_path, None)
        if not isinstance(data, dict):
            raise RuntimeError("无法读取要处理的项目。")
        runner = NovelWritingTab(deepcopy(self.config), None, background_runner=True)
        runner._background_task_kind = str(task_kind or "chapter_ai")
        runner._save_draft_snapshot = lambda: None
        runner._notify_project_store_changed = lambda: None
        runner._load_project_data(data, source_path, defer_helpers=True)
        if chapter_index is not None or chapter_id:
            chapters = runner.current_project.get("chapters", [])
            target_index = -1
            if chapter_id:
                chapter_id = str(chapter_id or "")
                target_index = next(
                    (
                        index
                        for index, chapter in enumerate(chapters)
                        if isinstance(chapter, dict)
                        and str(chapter.get("id", "") or "") == chapter_id
                    ),
                    -1,
                )
            if target_index < 0 and chapter_index is not None:
                try:
                    candidate_index = int(chapter_index)
                except (TypeError, ValueError):
                    candidate_index = -1
                if 0 <= candidate_index < len(chapters):
                    target_index = candidate_index
            if target_index < 0:
                raise RuntimeError("目标章节不存在，未启动后台单章扩写。")
            runner.current_chapter_index = target_index
            runner._reload_chapter_list(target_index)
        runner.hide()
        runners = getattr(self, "_background_chapter_ai_runners", None)
        if not isinstance(runners, dict):
            runners = {}
            self._background_chapter_ai_runners = runners
        if source_path in runners:
            raise RuntimeError("当前项目已经有后台章节任务。")
        runners[source_path] = runner
        self._update_detached_auto_source_lock()
        return runner, data

    def _launch_detached_single_chapter_ai(self, source_path, chapter_index, chapter_id):
        runner = None
        source_path = self._canonical_project_path(source_path)
        try:
            saved_path = self._save_current_work(
                "启动后台单章扩写", refresh_project_list=False
            )
            if not saved_path:
                raise RuntimeError("项目保存失败，未启动后台单章扩写。")
            runner, _data = self._create_detached_chapter_runner(
                source_path,
                "single_chapter",
                chapter_index=chapter_index,
                chapter_id=chapter_id,
            )
            runner.run_chapter_ai_action("draft")
            self._update_detached_auto_source_lock()
            self._sync_detached_auto_status(runner)
        except Exception as exc:
            runners = getattr(self, "_background_chapter_ai_runners", {})
            if isinstance(runners, dict) and runner is not None and runners.get(source_path) is runner:
                runners.pop(source_path, None)
            if runner is not None:
                try:
                    runner.deleteLater()
                except Exception:
                    pass
            self._update_detached_auto_source_lock()
            self._set_chapter_ai_actions_enabled(True)
            self._log_novel_diagnostic(
                "detached_single_chapter_start_failed",
                level="error",
                project_path=source_path,
                chapter_id=str(chapter_id or ""),
                **self._novel_exception_details(exc),
            )
            QMessageBox.warning(self, "单章扩写失败", str(exc))

    def _launch_detached_auto_expand(self, source_path):
        runner = None
        source_path = self._canonical_project_path(source_path)
        try:
            saved_path = self._save_current_work("启动后台自动扩写", refresh_project_list=False)
            if not saved_path:
                raise RuntimeError("项目保存失败，未启动后台任务。")
            runner, data = self._create_detached_chapter_runner(
                source_path, "auto_expand"
            )
            runner._start_auto_expand_all_local()
            self._update_detached_auto_source_lock()
            title = str((data.get("meta", {}) or {}).get("title", "") or os.path.basename(source_path))
            runners = getattr(self, "_background_chapter_ai_runners", {})
            active_count = sum(
                1
                for item in runners.values()
                if item is not None and item._status_has_active_work()
            )
            self.set_status_tip(
                f"《{title}》已在后台自动扩写，可继续操作其他小说。"
                f"当前后台任务：{active_count} 个。"
            )
        except Exception as exc:
            runners = getattr(self, "_background_chapter_ai_runners", {})
            if isinstance(runners, dict) and runner is not None and runners.get(source_path) is runner:
                runners.pop(source_path, None)
            if runner is not None:
                try:
                    runner.deleteLater()
                except Exception:
                    pass
            self._update_detached_auto_source_lock()
            if hasattr(self, "auto_expand_all_btn"):
                self.auto_expand_all_btn.setEnabled(True)
                self._set_auto_expand_all_button_text()
            self._log_novel_diagnostic(
                "detached_auto_expand_start_failed",
                level="error",
                project_path=source_path,
                **self._novel_exception_details(exc),
            )
            QMessageBox.warning(self, "自动扩写失败", str(exc))

    def _poll_detached_auto_expand(self):
        """Compatibility wrapper for the unified multi-project poller."""
        self._poll_background_chapter_ai_runners()

    def _show_chapter_ai_failure(self, message):
        error_text = clean_error_text(message)
        if getattr(self, "_is_detached_auto_runner", False):
            current_status = str(getattr(self, "_status_message", "") or "").strip()
            if not current_status or not any(
                marker in current_status for marker in ("失败", "停止", "中止")
            ):
                task_label = (
                    "后台自动扩写"
                    if str(getattr(self, "_background_task_kind", "") or "") != "single_chapter"
                    else "后台单章扩写"
                )
                self.set_status_tip(f"{task_label}已停止：{error_text[:120]}")
            return
        QMessageBox.warning(self, "AI 写作失败", error_text)

    def _detached_auto_status_is_current(self, runner=None):
        if getattr(self, "_is_detached_auto_runner", False):
            return False
        runner = runner if runner is not None else self._current_background_chapter_runner()
        return runner is not None and runner is self._current_background_chapter_runner()

    def _sync_detached_auto_status(self, runner):
        """Mirror detached expansion status into the visible project tab."""
        if not self._detached_auto_status_is_current(runner):
            return False
        self._status_project_path = self._canonical_project_path(
            getattr(runner, "current_project_path", "")
        )
        status_fields = (
            "_status_message",
            "_status_stage_key",
            "_status_stage_label",
            "_status_stage_started_at",
            "_status_stage_started_wall",
            "_status_stage_scope_label",
            "_status_stage_active",
            "_status_history",
            "_status_workflow_active",
            "_status_workflow_kind",
            "_status_workflow_started_at",
            "_status_workflow_started_wall",
            "_status_last_run_elapsed",
            "_status_received_chars",
        )
        for field in status_fields:
            value = getattr(runner, field, None)
            setattr(self, field, deepcopy(value) if field == "_status_history" else value)
        try:
            scope_id, scope_label = runner._status_current_chapter_scope()
        except Exception:
            scope_id, scope_label = "", ""
        self._detached_auto_status_scope_id = str(scope_id or "")
        self._detached_auto_status_scope_label = str(scope_label or "")
        try:
            progress = runner._auto_expand_all_chapter_progress()
        except Exception:
            progress = (0, 0)
        if not isinstance(progress, (tuple, list)) or len(progress) != 2:
            progress = (0, 0)
        self._detached_auto_status_auto_progress = (
            int(progress[0] or 0),
            int(progress[1] or 0),
        )
        self._detached_auto_status_mirrored = True
        self._refresh_status_display()
        return True

    def _clear_detached_auto_status_mirror(self):
        if not bool(getattr(self, "_detached_auto_status_mirrored", False)):
            return
        self._detached_auto_status_mirrored = False
        self._detached_auto_status_scope_id = ""
        self._detached_auto_status_scope_label = ""
        self._detached_auto_status_auto_progress = (0, 0)
        self._status_message = ""
        self._status_stage_key = ""
        self._status_stage_label = ""
        self._status_stage_started_at = 0.0
        self._status_stage_started_wall = 0.0
        self._status_stage_scope_label = ""
        self._status_stage_active = False
        self._status_workflow_active = False
        self._status_workflow_kind = ""
        self._status_workflow_started_at = 0.0
        self._status_workflow_started_wall = 0.0
        self._status_last_run_elapsed = 0.0
        self._status_received_chars = 0
        self._status_history = []
        self._refresh_status_display()

    def _reset_status_for_project_switch(self, project_path=None):
        """Discard status fields that belong to the project just left."""
        target_path = (
            project_path
            if project_path is not None
            else getattr(self, "current_project_path", "")
        )
        self._status_project_path = self._canonical_project_path(target_path)
        self._detached_auto_status_mirrored = False
        self._detached_auto_status_scope_id = ""
        self._detached_auto_status_scope_label = ""
        self._detached_auto_status_auto_progress = (0, 0)
        self._status_message = ""
        self._status_stage_key = ""
        self._status_stage_label = ""
        self._status_stage_started_at = 0.0
        self._status_stage_started_wall = 0.0
        self._status_stage_scope_label = ""
        self._status_stage_active = False
        self._status_workflow_active = False
        self._status_workflow_kind = ""
        self._status_workflow_started_at = 0.0
        self._status_workflow_started_wall = 0.0
        self._status_last_run_elapsed = 0.0
        self._status_received_chars = 0
        self._status_history = []
        self._refresh_status_display()

    def _set_detached_auto_source_read_only(self, locked):
        """Keep the source project viewable while preventing foreground writes."""
        states = getattr(self, "_detached_auto_readonly_states", None)
        if not isinstance(states, list):
            states = []
            self._detached_auto_readonly_states = states
        if locked:
            if states:
                return
            # Do not lock the whole NovelWritingTab: its project-management
            # panel must remain usable while this project's content is busy.
            root = getattr(self, "project_workspace", None)
            if root is None or not hasattr(root, "findChildren"):
                return
            try:
                child_widgets = root.findChildren(QWidget)
            except RuntimeError:
                return
            # Listening is read-only and does not mutate the project. Keep
            # these controls available while the source project is locked.
            read_aloud_controls = {
                widget
                for name in (
                    "read_aloud_btn",
                    "read_aloud_stop_btn",
                    "read_aloud_scope_combo",
                    "read_aloud_rate_combo",
                )
                if (widget := getattr(self, name, None)) is not None
            }
            if getattr(self, "fanqie_upload_btn", None) is not None:
                read_aloud_controls.add(self.fanqie_upload_btn)
            for widget in child_widgets:
                if widget is getattr(self, "chapter_ai_stop_btn", None):
                    continue
                if widget in read_aloud_controls:
                    continue
                if isinstance(widget, (QPlainTextEdit, QTextEdit, QLineEdit)):
                    states.append((widget, "read_only", bool(widget.isReadOnly())))
                    widget.setReadOnly(True)
                elif isinstance(widget, (QAbstractButton, QComboBox, QAbstractSpinBox)):
                    states.append((widget, "enabled", bool(widget.isEnabled())))
                    widget.setEnabled(False)
            return
        for widget, state_type, value in states:
            try:
                if state_type == "read_only":
                    widget.setReadOnly(bool(value))
                else:
                    widget.setEnabled(bool(value))
            except RuntimeError:
                pass
        states.clear()

    def _update_detached_auto_source_lock(self):
        detached_runner = self._current_background_chapter_runner()
        locked = detached_runner is not None
        if not locked:
            self._clear_detached_auto_status_mirror()
        self._set_detached_auto_source_read_only(locked)
        detached_active = False
        if detached_runner is not None and not getattr(self, "_is_detached_auto_runner", False):
            try:
                detached_active = bool(detached_runner._status_has_active_work())
            except Exception:
                detached_active = False
        if hasattr(self, "chapter_ai_stop_btn"):
            if detached_active and locked:
                self.chapter_ai_stop_btn.setText("中止后台扩写")
                self.chapter_ai_stop_btn.setToolTip("中止当前项目正在后台运行的章节任务")
                self.chapter_ai_stop_btn.setVisible(True)
                self.chapter_ai_stop_btn.setEnabled(True)
            else:
                self.chapter_ai_stop_btn.setText("中止")
                self.chapter_ai_stop_btn.setToolTip("中止当前 AI 辅助生成")
                self.chapter_ai_stop_btn.setVisible(False)
        if hasattr(self, "auto_expand_all_btn"):
            self.auto_expand_all_btn.setEnabled(not locked)
            if locked:
                task_kind = str(getattr(detached_runner, "_background_task_kind", "") or "")
                task_label = "后台单章扩写中" if task_kind == "single_chapter" else "后台自动扩写中"
                self.auto_expand_all_btn.setText(task_label)
            else:
                self.auto_expand_all_btn.setText("自动扩写全部")
        if locked and hasattr(self, "project_hint"):
            self.project_hint.setText("当前项目正在后台处理章节，可查看最新已保存内容；任务完成后自动恢复编辑。")
        elif hasattr(self, "project_hint"):
            self.project_hint.setText("单击列表可打开已保存小说。")

    def _start_auto_expand_all_local(self):
        perf_start = time.perf_counter()
        if getattr(self, "_auto_expand_all_active", False):
            self.set_status_tip("正在自动扩写所有未写章节。")
            return
        worker = getattr(self, "writing_worker", None)
        if worker is not None and worker.isRunning():
            self.set_status_tip("当前章节仍在生成，请完成后再启动自动扩写。")
            return
        plan_worker = getattr(self, "chapter_plan_worker", None)
        if plan_worker is not None and plan_worker.isRunning():
            self.set_status_tip("章节规划仍在生成，请完成后再启动自动扩写。")
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self._log_novel_diagnostic(
                "auto_expand_start_failed",
                level="error",
                error=clean_error_text(error),
                error_category=self._novel_diagnostic_error_category(error),
            )
            self.set_ai_settings_expanded(True)
            QMessageBox.warning(self, "自动扩写失败", error)
            return
        step_start = time.perf_counter()
        self._flush_current_editors()
        self._log_novel_perf(
            "自动扩写启动-刷新编辑器",
            step_start,
            threshold_ms=120,
            **self._novel_perf_summary(),
        )
        step_start = time.perf_counter()
        self._auto_expand_restart_rewrite_notice = self._discard_partial_preview_for_auto_rewrite()
        self._log_novel_perf(
            "自动扩写启动-清理半成品预览",
            step_start,
            threshold_ms=120,
            **self._novel_perf_summary(),
        )
        step_start = time.perf_counter()
        if not self._persist_completed_auto_expand_resume_flags():
            return
        self._log_novel_perf(
            "自动扩写启动-保存续跑状态",
            step_start,
            threshold_ms=120,
            **self._novel_perf_summary(),
        )
        step_start = time.perf_counter()
        pending = self._auto_expand_pending_indexes()
        self._log_novel_perf(
            "自动扩写启动-扫描待写章节",
            step_start,
            threshold_ms=120,
            pending_count=len(pending),
            **self._novel_perf_summary(),
        )
        if not pending:
            self._log_novel_diagnostic("auto_expand_no_pending")
            self.set_status_tip("所有章节均已完成，无需自动扩写或恢复。")
            return
        self._chapter_ai_provider = provider
        self._chapter_ai_model = model
        self._auto_expand_all_active = True
        self._auto_expand_all_waiting_next = False
        self._auto_expand_all_total = len(pending)
        self._auto_expand_all_completed = 0
        self._auto_expand_all_current_chapter_id = ""
        self._set_chapter_ai_actions_enabled(False)
        self._status_begin_workflow("auto_expand")
        self._log_novel_diagnostic(
            "auto_expand_started",
            provider=provider,
            model=model,
            pending_count=len(pending),
            pending_chapter_indexes=[index + 1 for index in pending],
        )
        project_total = len(self.current_project.get("chapters", [])) if isinstance(self.current_project, dict) else 0
        if hasattr(self, "auto_expand_all_btn") and pending and project_total:
            self.auto_expand_all_btn.setText(f"自动扩写全部 {pending[0] + 1}/{project_total}")
        else:
            self._set_auto_expand_all_button_text()
        self._log_novel_perf(
            "自动扩写启动-入口总耗时",
            perf_start,
            threshold_ms=120,
            pending_count=len(pending),
            **self._novel_perf_summary(),
        )
        self._schedule_chapter_task_callback(0, lambda tab: tab._start_next_auto_expand_chapter())

    def _start_next_auto_expand_chapter(self):
        if not getattr(self, "_auto_expand_all_active", False):
            return
        self._auto_expand_all_waiting_next = False
        pending = self._auto_expand_pending_indexes()
        if not pending:
            batch_total = int(getattr(self, "_auto_expand_all_total", 0) or 0)
            project_total = len(self.current_project.get("chapters", []))
            self._stop_auto_expand_all(
                f"自动扩写完成：全书 {project_total}/{project_total} 章均已完成，本轮完成 {batch_total} 章。"
            )
            return
        index = pending[0]
        chapters = self.current_project.get("chapters", [])
        chapter = chapters[index]
        title = str(chapter.get("title", "") or f"第{index + 1}章").strip()
        has_body = bool(str(chapter.get("text", "") or "").strip())
        has_checkpoint = bool(self._memory_finalize_checkpoint_text(chapter))
        if not has_checkpoint:
            checkpoint = chapter.get("ai_generation_checkpoint", {})
            has_checkpoint = bool(
                isinstance(checkpoint, dict)
                and str(checkpoint.get("stage", "") or "") in {"memory_repair", "logic_repair"}
                and str(checkpoint.get("final_text", "") or "").strip()
            )
        if not str(chapter.get("outline", "") or "").strip() and not has_body and not has_checkpoint:
            self._stop_auto_expand_all(f"自动扩写已停止：第{index + 1}章《{title}》没有章节提纲。")
            self._set_chapter_ai_actions_enabled(True)
            return
        row = self._row_for_source_index(self.chapter_list, index)
        if row < 0:
            self._stop_auto_expand_all(f"自动扩写已停止：无法定位第{index + 1}章《{title}》。")
            self._set_chapter_ai_actions_enabled(True)
            return
        self.chapter_list.setCurrentRow(row)
        if self._discard_partial_preview_for_auto_rewrite():
            self._auto_expand_restart_rewrite_notice = True
        self._auto_expand_all_current_chapter_id = str(chapter.get("id", "") or "")
        self._set_auto_expand_all_button_text()
        completed = int(getattr(self, "_auto_expand_all_completed", 0) or 0)
        total = int(getattr(self, "_auto_expand_all_total", 0) or 0)
        self._log_novel_diagnostic(
            "auto_expand_chapter_started",
            chapter_id=str(chapter.get("id", "") or ""),
            queue_position=completed + 1,
            queue_total=total,
            recovery_mode=(
                str(chapter.get("ai_generation_checkpoint", {}).get("stage", "") or "")
                if isinstance(chapter.get("ai_generation_checkpoint"), dict)
                and str(chapter.get("ai_generation_checkpoint", {}).get("stage", "") or "")
                in {"memory_finalize", "memory_repair", "logic_repair", "memory_reconcile"}
                else "existing_body" if has_body else "new_draft"
            ),
        )
        rewrite_notice = "（已丢弃半成品，重新生成）" if getattr(
            self, "_auto_expand_restart_rewrite_notice", False
        ) else ""
        self._auto_expand_restart_rewrite_notice = False
        chapter_number, project_total = self._auto_expand_all_chapter_progress()
        self.set_status_tip(
            f"自动扩写 {chapter_number}/{project_total}：第{index + 1}章《{title}》...{rewrite_notice}"
        )
        def start_sequence_after_ui_update(tab):
            if not getattr(tab, "_auto_expand_all_active", False):
                return
            if tab._current_chapter_id() != str(chapter.get("id", "") or ""):
                return
            tab._start_chapter_ai_sequence()
            if (
                getattr(tab, "_auto_expand_all_active", False)
                and not getattr(tab, "_chapter_ai_sequence_active", False)
                and getattr(tab, "writing_worker", None) is None
            ):
                tab._stop_auto_expand_all(f"自动扩写已停止：第{index + 1}章《{title}》未能启动。")
                tab._set_chapter_ai_actions_enabled(True)

        self._schedule_chapter_task_callback(0, start_sequence_after_ui_update)

    def _on_auto_expand_chapter_completed(self, memory_changed):
        if not getattr(self, "_auto_expand_all_active", False):
            return
        chapter_id = self._current_chapter_id()
        if chapter_id != getattr(self, "_auto_expand_all_current_chapter_id", ""):
            self._stop_auto_expand_all("自动扩写已停止：完成章节与当前任务不一致。")
            return
        chapter = self.current_project.get("chapters", [])[self.current_chapter_index]
        boundary_reconciliation_status = str(
            chapter.get("memory_reconciliation_status", "") or ""
        )
        if (
            (self.current_chapter_index + 1) % 10 == 0
            and boundary_reconciliation_status in {"pending", "failed"}
        ):
            self._log_novel_diagnostic(
                "auto_expand_paused_for_memory_reconciliation",
                level="warning",
                chapter_id=str(chapter.get("id", "") or ""),
                reconciliation_status=boundary_reconciliation_status,
                reason="十章边界对账未完成，保留恢复检查点后暂停自动扩写",
            )
            self._stop_auto_expand_all(
                f"自动扩写已暂停：第{self.current_chapter_index + 1}章十章边界对账未完成；"
                "下次启动时将从对账继续。"
            )
            return
        memory = self.current_project.get("long_form_memory", {}) if isinstance(self.current_project, dict) else {}
        snapshot = memory.get("state_snapshot", {}) if isinstance(memory, dict) else {}
        memory_revision = int(memory.get("revision", 0) or 0) if isinstance(memory, dict) else 0
        complete = bool(
            str(chapter.get("text", "") or "").strip()
            and str(chapter.get("summary", "") or "").strip()
            and str(chapter.get("key_facts", "") or "").strip()
            and memory_changed
            and str(chapter.get("memory_sync_status", "") or "") == "complete"
            and int(chapter.get("memory_revision", 0) or 0) == memory_revision
            and str(chapter.get("memory_update_hash", "") or "").strip()
            and str(snapshot.get("as_of_chapter_id", "") or "") == str(chapter.get("id", "") or "")
        )
        if not complete:
            self._log_novel_diagnostic(
                "auto_expand_postwrite_validation_failed",
                level="error",
                chapter_id=str(chapter.get("id", "") or ""),
                memory_changed=bool(memory_changed),
                has_body=bool(str(chapter.get("text", "") or "").strip()),
                has_summary=bool(str(chapter.get("summary", "") or "").strip()),
                has_key_facts=bool(str(chapter.get("key_facts", "") or "").strip()),
                memory_status=str(chapter.get("memory_sync_status", "") or ""),
                chapter_memory_revision=int(chapter.get("memory_revision", 0) or 0),
                global_memory_revision=memory_revision,
                has_memory_update_hash=bool(str(chapter.get("memory_update_hash", "") or "").strip()),
                snapshot_matches=(
                    str(snapshot.get("as_of_chapter_id", "") or "")
                    == str(chapter.get("id", "") or "")
                ),
            )
            self._stop_auto_expand_all(
                f"自动扩写已停止：第{self.current_chapter_index + 1}章资料回填不完整，请检查后继续。"
            )
            return
        chapter["auto_expand_resume_required"] = False
        if hasattr(self, "_note_project_dirty"):
            self._note_project_dirty()
        saved_path = self._save_current_work(
            f"自动扩写第{self.current_chapter_index + 1}章完成",
            refresh_project_list=False,
        )
        if not saved_path:
            chapter["auto_expand_resume_required"] = True
            if hasattr(self, "_note_project_dirty"):
                self._note_project_dirty()
            self._persist_ai_generation_state()
            self._log_novel_diagnostic(
                "auto_expand_chapter_save_failed",
                level="error",
                chapter_id=str(chapter.get("id", "") or ""),
                error="章节内容和长期状态已完成，但项目文件保存失败",
                error_category="storage",
            )
            self._stop_auto_expand_all(
                f"自动扩写已停止：第{self.current_chapter_index + 1}章保存失败。"
            )
            return
        self._auto_expand_all_completed = int(getattr(self, "_auto_expand_all_completed", 0) or 0) + 1
        self._auto_expand_all_waiting_next = True
        self._log_novel_diagnostic(
            "auto_expand_chapter_completed",
            chapter_id=str(chapter.get("id", "") or ""),
            completed_count=self._auto_expand_all_completed,
            queue_total=int(getattr(self, "_auto_expand_all_total", 0) or 0),
        )
        self._set_auto_expand_all_button_text()
        chapter_number, project_total = self._auto_expand_all_chapter_progress()
        self.set_status_tip(
            f"自动扩写进度：第{chapter_number}章已完成（{chapter_number}/{project_total}），正在准备下一章。"
        )

    def _reset_chapter_ai_style_retry(self):
        self._chapter_ai_transient_retry_pending = False
        self._chapter_ai_transient_retry_token = int(
            getattr(self, "_chapter_ai_transient_retry_token", 0) or 0
        ) + 1
        self._chapter_ai_transient_retry_counts = {}
        self._chapter_ai_style_retry_attempted = False
        self._chapter_ai_style_fallback_text = ""
        self._chapter_ai_last_context = ""
        self._chapter_ai_style_workflow_active = False
        self._chapter_ai_style_reference = ""
        self._chapter_ai_style_original_context = ""
        self._chapter_ai_style_profile = ""
        self._chapter_ai_style_candidate = ""
        self._chapter_ai_style_finalize_count = 0
        self._chapter_ai_style_final_bundle = {}
        self._chapter_ai_style_rewrite_count = 0
        self._chapter_ai_style_local_reasons = []
        self._chapter_ai_style_output_target = 0
        self._chapter_ai_style_plot_ledger = ""
        self._chapter_ai_style_pending_reasons = []
        self._chapter_ai_style_cards = []
        self._chapter_ai_style_semantic_archive = {}
        self._chapter_ai_style_plan = ""
        self._chapter_ai_style_reference_hash = ""
        self._chapter_ai_style_cache_entry = {}
        self._chapter_ai_style_build_unit_index = -1
        self._chapter_ai_style_combined_sheet = ""
        self._chapter_ai_style_persona = ""
        self._chapter_ai_style_rules = ""
        self._chapter_ai_style_execution = ""
        self._chapter_ai_memory_finalize_attempted = False
        self._chapter_ai_memory_repair_attempts = 0
        self._chapter_ai_last_memory_repair_signature = ""
        self._chapter_ai_logic_repair_attempts = 0
        self._chapter_ai_memory_pending = {}

    @staticmethod
    def _canonical_project_path(path):
        raw = str(path or "").strip()
        return os.path.abspath(os.path.realpath(raw)) if raw else ""

    def _current_chapter_ai_task_context(self):
        task = getattr(self, "_chapter_ai_active_task", {})
        return deepcopy(task) if isinstance(task, dict) else {}

    def _log_stale_chapter_ai_callback(self, worker, reason):
        worker_path = self._canonical_project_path(
            getattr(worker, "diagnostic_project_path", "") if worker is not None else ""
        )
        worker_chapter_id = str(
            getattr(worker, "diagnostic_chapter_id", "") if worker is not None else ""
        )
        worker_request_id = str(
            getattr(worker, "diagnostic_request_id", "") if worker is not None else ""
        )
        self._log_novel_diagnostic(
            "chapter_ai_stale_callback_discarded",
            level="warning",
            action=str(getattr(worker, "action", "") or ""),
            request_id=worker_request_id,
            callback_project_path=worker_path,
            callback_chapter_id=worker_chapter_id,
            callback_task_generation=int(
                getattr(worker, "diagnostic_task_generation", 0) or 0
            ) if worker is not None else 0,
            current_project_path=self._canonical_project_path(
                getattr(self, "current_project_path", "")
            ),
            current_chapter_id=self._current_chapter_id(),
            current_task_generation=int(
                getattr(self, "_chapter_ai_task_generation", 0) or 0
            ),
            reason=str(reason or "")[:500],
        )

    def _chapter_ai_callback_is_current(self):
        """Reject late worker signals before they can touch the visible project."""
        worker = None
        try:
            candidate = self._chapter_task_signal_worker()
            if candidate is not None and hasattr(candidate, "diagnostic_request_id"):
                worker = candidate
        except Exception:
            worker = None
        if worker is None:
            # Direct method calls in tests and non-Qt integrations do not have a
            # sender. Keep those calls compatible with the pre-worker API.
            return True
        current_worker = getattr(self, "writing_worker", None)
        current_path = self._canonical_project_path(
            getattr(self, "current_project_path", "")
        )
        callback_path = self._canonical_project_path(
            getattr(worker, "diagnostic_project_path", "")
        )
        callback_chapter_id = str(
            getattr(worker, "diagnostic_chapter_id", "") or ""
        )
        callback_generation = int(
            getattr(worker, "diagnostic_task_generation", 0) or 0
        )
        current_generation = int(
            getattr(self, "_chapter_ai_task_generation", 0) or 0
        )
        current_chapter_id = self._current_chapter_id()
        callback_request_id = str(
            getattr(worker, "diagnostic_request_id", "") or ""
        )
        current_request_id = str(
            getattr(self, "_chapter_ai_diagnostic_request_id", "") or ""
        )
        valid = bool(
            worker is current_worker
            and callback_path == current_path
            and callback_chapter_id == current_chapter_id
            and callback_generation == current_generation
            and callback_request_id == current_request_id
        )
        if not valid:
            reasons = []
            if worker is not current_worker:
                reasons.append("worker已不是当前任务")
            if callback_path != current_path:
                reasons.append("项目路径不一致")
            if callback_chapter_id != current_chapter_id:
                reasons.append("章节不一致")
            if callback_generation != current_generation:
                reasons.append("任务代次不一致")
            if callback_request_id != current_request_id:
                reasons.append("请求ID不一致")
            self._log_stale_chapter_ai_callback(worker, "；".join(reasons))
        return valid

    def _invalidate_foreground_chapter_ai_task(self, reason=""):
        """Invalidate foreground callbacks when replacing the open project."""
        self._chapter_ai_task_generation = int(
            getattr(self, "_chapter_ai_task_generation", 0) or 0
        ) + 1
        self._chapter_ai_active_task = {}
        self._chapter_ai_memory_pending = {}
        self._chapter_ai_running_action = ""
        self._chapter_ai_running_context = ""
        self._chapter_ai_running_chapter_id = ""
        self._chapter_ai_diagnostic_request_id = ""
        self._chapter_ai_diagnostic_started_at = 0.0
        self._chapter_ai_transient_retry_pending = False
        self._chapter_ai_transient_retry_token = int(
            getattr(self, "_chapter_ai_transient_retry_token", 0) or 0
        ) + 1
        self._reset_chapter_ai_sequence()
        self._reset_chapter_ai_style_retry()
        workers = []
        current_worker = getattr(self, "writing_worker", None)
        if current_worker is not None:
            workers.append(current_worker)
        workers.extend(
            worker for worker in (getattr(self, "writing_retired_workers", []) or [])
            if worker is not None and worker not in workers
        )
        for worker in workers:
            try:
                if worker.isRunning():
                    if hasattr(worker, "stop"):
                        worker.stop()
                    else:
                        worker.requestInterruption()
            except Exception as exc:
                log_debug("切换项目时中止旧章节任务失败", exc)
        self._chapter_ai_stop_requested_by_user = False
        self._set_chapter_ai_actions_enabled(True)
        self._log_novel_diagnostic(
            "chapter_ai_task_invalidated",
            action="chapter_ai",
            reason=str(reason or "")[:500],
            task_generation=int(self._chapter_ai_task_generation),
        )

    def _invalidate_chapter_plan_generation(self, reason="", clear_project_state=True):
        """Invalidate chapter-plan work and remove stale planning UI state.

        Chapter planning is resumable after a user stop, so its interrupted
        checkpoint is intentionally kept by ``stop_chapter_ai_action``.  That
        checkpoint must be discarded when the project/framework context is
        replaced; otherwise the old progress remains visible and a late worker
        signal can write it back into the new context.
        """
        self._chapter_plan_sequence_token = int(
            getattr(self, "_chapter_plan_sequence_token", 0) or 0
        ) + 1
        self._chapter_plan_auto_active = False
        self._chapter_plan_continue_pending = False
        self._chapter_plan_foundation_regenerate_pending = False
        self._chapter_plan_request_kind = ""
        self._chapter_plan_provider = {}
        self._chapter_plan_model = ""
        self._chapter_plan_diagnostic_request_id = ""
        self._chapter_plan_diagnostic_started_at = 0.0
        self._pending_chapter_plan = {}
        self.chapter_ai_stream_text = ""

        worker = getattr(self, "chapter_plan_worker", None)
        # Detach it immediately.  The finished callback may still arrive after
        # stop(), but its sender will then fail the sequence/current-worker
        # check and cannot mutate the replacement project.
        self.chapter_plan_worker = None
        if worker is not None:
            try:
                if worker.isRunning():
                    if hasattr(worker, "stop"):
                        worker.stop()
                    else:
                        worker.requestInterruption()
            except Exception as exc:
                log_debug("失效旧章节规划线程失败", exc)

        if clear_project_state and isinstance(getattr(self, "current_project", None), dict):
            self.current_project.pop("chapter_plan_generation_state", None)
            if hasattr(self, "_note_project_dirty"):
                self._note_project_dirty()
        if hasattr(self, "chapter_plan_apply_btn"):
            self.chapter_plan_apply_btn.setVisible(False)
            self.chapter_plan_apply_btn.setEnabled(False)
        if hasattr(self, "chapter_ai_preview"):
            self.chapter_ai_preview.clear()
        self._set_chapter_ai_actions_enabled(True)
        self._chapter_ai_stop_requested_by_user = False
        self._log_novel_diagnostic(
            "chapter_plan_generation_invalidated",
            action="chapter_plan",
            reason=str(reason or "")[:500],
            sequence_token=int(self._chapter_plan_sequence_token),
        )

    def _chapter_plan_callback_is_current(self):
        """Reject late chapter-plan worker signals after context replacement."""
        worker = None
        try:
            candidate = self._chapter_task_signal_worker()
            if candidate is not None and hasattr(candidate, "_chapter_plan_sequence_token"):
                worker = candidate
        except Exception:
            worker = None
        if worker is None:
            # Direct calls used by tests and non-Qt integrations remain
            # compatible with the public callback methods.
            return True
        current_worker = getattr(self, "chapter_plan_worker", None)
        callback_token = int(getattr(worker, "_chapter_plan_sequence_token", -1) or -1)
        current_token = int(getattr(self, "_chapter_plan_sequence_token", 0) or 0)
        valid = bool(
            worker is current_worker
            and callback_token == current_token
            and bool(getattr(self, "_chapter_plan_auto_active", False))
        )
        if not valid:
            self._log_novel_diagnostic(
                "chapter_plan_stale_callback_discarded",
                level="warning",
                action="chapter_plan",
                callback_sequence_token=callback_token,
                current_sequence_token=current_token,
                callback_is_current_worker=worker is current_worker,
                chapter_plan_auto_active=bool(
                    getattr(self, "_chapter_plan_auto_active", False)
                ),
            )
        return valid

    def _start_style_locked_draft(self, context):
        project = self._ai_project_snapshot()
        style_reference = str(project.get("style_reference", "") or "").strip()
        if not style_reference:
            self._start_chapter_ai_worker("draft", context, "正在扩写正文...")
            return
        self._chapter_ai_style_workflow_active = True
        self._chapter_ai_style_reference = style_reference
        self._chapter_ai_style_original_context = str(context or "")
        self._chapter_ai_style_output_target = _style_output_target_from_context(context)
        reference_hash = hashlib.sha256(style_reference.encode("utf-8")).hexdigest()
        self._chapter_ai_style_reference_hash = reference_hash
        project_cache = project.get("style_profile_cache", {})
        cached_item = project_cache.get(reference_hash, {}) if isinstance(project_cache, dict) else {}
        try:
            cached_version = int(cached_item.get("version", 0) or 0) if isinstance(cached_item, dict) else 0
        except Exception:
            cached_version = 0
        persisted_text = (
            str(cached_item.get("profile", "") or "").strip()
            if isinstance(cached_item, dict) else str(cached_item or "").strip()
        )
        if persisted_text and cached_version >= STYLE_SHEET_CACHE_VERSION:
            if isinstance(cached_item, dict):
                self._chapter_ai_style_cache_entry = deepcopy(cached_item)
                self._chapter_ai_style_combined_sheet = str(
                    cached_item.get("combined_sheet", "") or persisted_text
                ).strip()
                self._chapter_ai_style_persona = str(cached_item.get("persona", "") or "").strip()
                self._chapter_ai_style_cards = deepcopy(
                    cached_item.get("style_cards", [])
                    if isinstance(cached_item.get("style_cards"), list) else []
                )
                self._chapter_ai_style_semantic_archive = _normalize_semantic_style_archive(
                    cached_item,
                    style_reference,
                )
            self._chapter_ai_style_profile = persisted_text
            self._chapter_ai_style_profile_cache_hash = reference_hash
            self._chapter_ai_style_profile_cache_text = persisted_text
            self._chapter_ai_style_profile_cache_version = cached_version
            self._start_style_profiled_draft()
            return
        cached_hash = str(getattr(self, "_chapter_ai_style_profile_cache_hash", "") or "")
        cached_text = str(getattr(self, "_chapter_ai_style_profile_cache_text", "") or "").strip()
        cached_runtime_version = int(
            getattr(self, "_chapter_ai_style_profile_cache_version", 0) or 0
        )
        if (
            reference_hash == cached_hash
            and cached_text
            and cached_runtime_version >= STYLE_SHEET_CACHE_VERSION
        ):
            self._chapter_ai_style_profile = cached_text
            self._start_style_profiled_draft()
            return
        if isinstance(cached_item, dict) and int(cached_item.get("version", 0) or 0) >= STYLE_SHEET_CACHE_VERSION:
            entry = deepcopy(cached_item)
        else:
            entry = {
                "version": STYLE_SHEET_CACHE_VERSION,
                "status": "building",
                "profile": "",
                "combined_sheet": "",
                "persona": "",
                "style_cards_version": 0,
                "style_cards": [],
                "units": _build_style_profile_units(style_reference, max_units=10, target_chars=2400),
                "merge_results": [],
            }
        if not entry.get("units"):
            profile_context = _build_style_profile_request_context(style_reference)
            self._start_chapter_ai_worker(
                "style_profile",
                profile_context,
                "样本无法分段，正在使用兼容模式建立文风画像...",
            )
            return
        self._chapter_ai_style_cache_entry = entry
        self._persist_style_cache_entry(reference_hash, entry)
        self._continue_style_profile_build()

    def _start_style_profiled_draft(self):
        self._chapter_ai_style_rules = ""
        self._start_style_draft_with_rules()

    def _start_style_draft_with_rules(self):
        if str(self._chapter_ai_style_persona or "").strip():
            profile = _compose_style_profile(
                "",
                self._chapter_ai_style_persona,
                self._chapter_ai_style_rules,
            )
        else:
            profile = _compose_style_profile(
                self._chapter_ai_style_combined_sheet or self._chapter_ai_style_profile,
                "",
                self._chapter_ai_style_rules,
            )
        profile = profile or self._chapter_ai_style_profile
        self._chapter_ai_style_profile = profile
        vocabulary_profile = _compose_style_profile(
            str(getattr(self, "_chapter_ai_style_combined_sheet", "") or ""),
            str(getattr(self, "_chapter_ai_style_persona", "") or ""),
        ) or profile
        context = _build_style_execution_context(
            self._chapter_ai_style_original_context,
            profile,
            style_cards=self._chapter_ai_style_cards,
            style_reference=self._chapter_ai_style_reference,
            project=self._ai_project_snapshot(),
            chapter_index=int(getattr(self, "current_chapter_index", 0) or 0),
            vocabulary_profile_text=vocabulary_profile,
            semantic_archive=getattr(self, "_chapter_ai_style_semantic_archive", {}),
        )
        self.chapter_ai_preview.clear()
        self.chapter_ai_stream_text = ""
        self._start_chapter_ai_worker("draft", context, "文风档案已载入，正在直接扩写正文...")

    def _persist_style_cache_entry(self, reference_hash, entry):
        cache_key = str(reference_hash or "").strip().lower()
        if not cache_key or not isinstance(entry, dict):
            return
        stored = deepcopy(entry)
        stored["cached_at"] = now_str()
        stored["model"] = str(getattr(self, "_chapter_ai_model", "") or "")
        cache = self.current_project.setdefault("style_profile_cache", {})
        if not isinstance(cache, dict):
            cache = {}
            self.current_project["style_profile_cache"] = cache
        cache[cache_key] = stored
        self._chapter_ai_style_cache_entry = deepcopy(stored)
        if hasattr(self, "_note_project_dirty"):
            self._note_project_dirty()
        if not hasattr(self, "current_project_path") or not hasattr(self, "_draft_saved_once"):
            return
        self._archive_completed_style_profile(cache_key, stored)
        try:
            self._save_draft_snapshot()
            self._save_current_project_snapshot_if_named()
        except Exception as e:
            log_debug("小说完整文风档案持久化失败", e)

    def _archive_completed_style_profile(self, reference_hash, cache_entry):
        if not isinstance(cache_entry, dict) or not str(cache_entry.get("profile", "") or "").strip():
            return ""
        status = str(cache_entry.get("status", "") or "").strip()
        if status and status != "complete":
            return ""
        reference = str(getattr(self, "_chapter_ai_style_reference", "") or "").strip()
        if not reference:
            reference = str(self.current_project.get("style_reference", "") or "").strip()
        if not reference or hashlib.sha256(reference.encode("utf-8")).hexdigest() != reference_hash:
            return ""
        title = str(self.current_project.get("meta", {}).get("title", "") or "").strip()
        selected_id = str(
            self.current_project.get("style_profile_id", "") or ""
        ).strip().lower()
        archive_id = str(
            cache_entry.get("archive_id", "") or ""
        ).strip().lower()
        if archive_id == "__none__":
            archive_id = ""
        if not archive_id and selected_id != "__none__":
            archive_id = selected_id
        profile_id = upsert_style_profile(
            reference,
            cache_entry,
            name=title,
            source_project=str(getattr(self, "current_project_path", "") or ""),
            profile_id=archive_id,
        )
        local_reference = str(self.current_project.get("style_reference", "") or "").strip()
        if profile_id and local_reference == reference and selected_id != "__none__":
            self.current_project["style_profile_id"] = profile_id
            self._refresh_style_profile_combo()
        return profile_id

    def _continue_style_profile_build(self):
        entry = self._chapter_ai_style_cache_entry if isinstance(self._chapter_ai_style_cache_entry, dict) else {}
        units = entry.get("units", []) if isinstance(entry.get("units"), list) else []
        total = len(units)
        for index, unit in enumerate(units):
            if not isinstance(unit, dict):
                continue
            self._chapter_ai_style_build_unit_index = index
            if not str(unit.get("baseline", "") or "").strip():
                self._start_chapter_ai_worker(
                    "style_baseline",
                    _build_style_baseline_context(unit, index + 1, total),
                    f"首次文风建档：正在生成普通基准稿 {index + 1}/{total}...",
                )
                return
            if not str(unit.get("sheet", "") or "").strip():
                self._start_chapter_ai_worker(
                    "style_sheet",
                    _build_style_sheet_context(unit, index + 1, total),
                    f"首次文风建档：正在提取证据化写法 {index + 1}/{total}...",
                )
                return

        merge_results = entry.get("merge_results", []) if isinstance(entry.get("merge_results"), list) else []
        if total == 1:
            entry["combined_sheet"] = str(units[0].get("sheet", "") or "").strip()
        elif len(merge_results) < total - 1:
            next_unit_index = len(merge_results) + 1
            previous = (
                str(merge_results[-1] or "").strip()
                if merge_results else str(units[0].get("sheet", "") or "").strip()
            )
            current = str(units[next_unit_index].get("sheet", "") or "").strip()
            self._chapter_ai_style_build_unit_index = next_unit_index
            self._start_chapter_ai_worker(
                "style_sheet_merge",
                _build_style_sheet_merge_context(previous, current, next_unit_index + 1, total),
                f"首次文风建档：正在合并作者写作档案 {next_unit_index}/{total - 1}...",
            )
            return
        else:
            entry["combined_sheet"] = str(merge_results[-1] or "").strip()

        if not str(entry.get("persona", "") or "").strip():
            self._chapter_ai_style_cache_entry = entry
            self._persist_style_cache_entry(self._chapter_ai_style_reference_hash, entry)
            self._start_chapter_ai_worker(
                "style_persona",
                _build_style_persona_context(entry.get("combined_sheet", "")),
                "首次文风建档：正在生成作者人格（最后一步）...",
            )
            return

        if int(entry.get("style_cards_version", 0) or 0) < STYLE_CARD_CACHE_VERSION:
            self._chapter_ai_style_cache_entry = entry
            self._persist_style_cache_entry(self._chapter_ai_style_reference_hash, entry)
            self._start_chapter_ai_worker(
                "style_cards",
                _build_style_cards_context(
                    self._chapter_ai_style_reference,
                    entry.get("combined_sheet", ""),
                    entry.get("persona", ""),
                ),
                "首次文风建档：正在建立功能型原文片段库（最后一步）...",
            )
            return

        entry["profile"] = _compose_style_profile(entry.get("combined_sheet", ""), entry.get("persona", ""))
        entry["status"] = "complete"
        entry.pop("error", None)
        self._persist_style_cache_entry(self._chapter_ai_style_reference_hash, entry)
        self._chapter_ai_style_combined_sheet = str(entry.get("combined_sheet", "") or "").strip()
        self._chapter_ai_style_persona = str(entry.get("persona", "") or "").strip()
        self._chapter_ai_style_cards = deepcopy(
            entry.get("style_cards", []) if isinstance(entry.get("style_cards"), list) else []
        )
        self._chapter_ai_style_profile = str(entry.get("profile", "") or "").strip()
        self._chapter_ai_style_profile_cache_hash = self._chapter_ai_style_reference_hash
        self._chapter_ai_style_profile_cache_text = self._chapter_ai_style_profile
        self._chapter_ai_style_profile_cache_version = STYLE_SHEET_CACHE_VERSION
        self._start_style_profiled_draft()

    def _persist_style_profile(self, reference_hash, profile_text):
        profile = str(profile_text or "").strip()
        if not profile:
            return
        cache = self.current_project.setdefault("style_profile_cache", {})
        if not isinstance(cache, dict):
            cache = {}
            self.current_project["style_profile_cache"] = cache
        cache[reference_hash] = {
            "version": 1,
            "status": "complete",
            "profile": profile,
            "cached_at": now_str(),
            "model": str(getattr(self, "_chapter_ai_model", "") or ""),
        }
        if hasattr(self, "_note_project_dirty"):
            self._note_project_dirty()
        if not hasattr(self, "current_project_path") or not hasattr(self, "_draft_saved_once"):
            return
        self._archive_completed_style_profile(reference_hash, cache[reference_hash])
        try:
            self._save_draft_snapshot()
            self._save_current_project_snapshot_if_named()
        except Exception as e:
            log_debug("小说文风画像持久化失败", e)

    def _start_style_candidate_finalize(
        self, candidate, rescue=False, gate_errors=None, transient_retry=False
    ):
        self._chapter_ai_style_candidate = str(candidate or "").strip()
        self._chapter_ai_style_finalize_count = int(
            getattr(self, "_chapter_ai_style_finalize_count", 0) or 0
        ) + 1
        execution_text = str(getattr(self, "_chapter_ai_style_execution", "") or "").strip()
        self._chapter_ai_style_local_reasons = _style_draft_mismatch_reasons(
            self._chapter_ai_style_reference,
            self._chapter_ai_style_candidate,
            self._chapter_ai_style_output_target,
        )
        for reason in gate_errors or []:
            reason = str(reason or "").strip()
            if reason and reason not in self._chapter_ai_style_local_reasons:
                self._chapter_ai_style_local_reasons.append(reason)
        finalize_context = _build_style_finalize_context(
            self._chapter_ai_style_original_context,
            self._chapter_ai_style_candidate,
            self._chapter_ai_style_profile,
            self._chapter_ai_style_reference,
            local_reasons=self._chapter_ai_style_local_reasons,
            output_target=self._chapter_ai_style_output_target,
            project=self._ai_project_snapshot(),
            chapter_index=int(getattr(self, "current_chapter_index", 0) or 0),
            include_memory=False,
            execution_text=execution_text,
            style_plan=str(getattr(self, "_chapter_ai_style_plan", "") or ""),
            style_cards=getattr(self, "_chapter_ai_style_cards", []),
            rescue_from_candidate=bool(rescue),
            vocabulary_profile_text=(
                _compose_style_profile(
                    str(getattr(self, "_chapter_ai_style_combined_sheet", "") or ""),
                    str(getattr(self, "_chapter_ai_style_persona", "") or ""),
                )
                or str(getattr(self, "_chapter_ai_style_profile", "") or "")
            ),
        )
        self.chapter_ai_preview.setPlainText(self._chapter_ai_style_candidate)
        self.chapter_ai_stream_text = ""
        if rescue:
            self._log_novel_diagnostic(
                "style_finalize_rescue_started",
                level="warning",
                action="style_finalize",
                finalize_attempt=self._chapter_ai_style_finalize_count,
                gate_errors=[
                    str(item or "").strip()
                    for item in self._chapter_ai_style_local_reasons
                    if str(item or "").strip()
                ],
                candidate_chars=len(self._chapter_ai_style_candidate),
            )
        worker_kwargs = {"transient_retry": True} if transient_retry else {}
        self._start_chapter_ai_worker(
            "style_finalize",
            finalize_context,
            "正文存在严重偏差，正在执行一次终稿补救..." if rescue else
            "正文已生成，正在专门审校并修订正文终稿...",
            **worker_kwargs,
        )

    @staticmethod
    def _chapter_ai_checkpoint_hash(value):
        return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()

    @staticmethod
    def _novel_memory_bundle_summary(bundle):
        """Return a content-free structural summary for memory diagnostics."""
        bundle = bundle if isinstance(bundle, dict) else {}
        update = bundle.get("memory_update", {})
        update = update if isinstance(update, dict) else {}
        state_patch = update.get("state_patch", {})
        state_patch = state_patch if isinstance(state_patch, dict) else {}
        record_updates = update.get("record_updates", {})
        record_updates = record_updates if isinstance(record_updates, dict) else {}
        reconciliation = update.get("state_reconciliation", {})
        reconciliation = reconciliation if isinstance(reconciliation, dict) else {}
        next_memory = update.get("next_chapter_memory", {})
        next_memory = next_memory if isinstance(next_memory, dict) else {}

        def count(value):
            return len(value) if isinstance(value, list) else 0

        def count_map(value, keys):
            return {key: count(value.get(key, [])) for key in keys}

        try:
            update_hash = hashlib.sha256(
                json.dumps(update, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
        except Exception:
            update_hash = ""
        return {
            "outline_chars": len(str(bundle.get("outline", "") or "")),
            "summary_chars": len(str(bundle.get("summary", "") or "")),
            "key_facts_chars": len(str(bundle.get("key_facts", "") or "")),
            "logic_audit_present": isinstance(bundle.get("logic_audit"), dict)
            and bool(bundle.get("logic_audit")),
            "repair_patches": count(bundle.get("repair_patches", [])),
            "memory_update_sha256": update_hash,
            "schema_version": update.get("schema_version", ""),
            "base_revision": update.get("base_revision", ""),
            "state_patch_counts": count_map(
                state_patch,
                (
                    "character_states", "relationship_states", "object_states",
                    "active_conflicts", "unresolved_tasks",
                ),
            ),
            "record_update_counts": {
                "characters": count(record_updates.get("characters", [])),
                "lore": count(record_updates.get("lore", [])),
                "foreshadows": count(update.get("foreshadow_updates", [])),
            },
            "fact_updates": count(update.get("fact_updates", [])),
            "long_term_events": count(update.get("long_term_events", [])),
            "reconciliation_counts": count_map(
                reconciliation,
                (
                    "fact_refs", "character_refs", "lore_refs", "foreshadow_refs",
                    "relationship_refs", "object_keys", "conflict_refs", "task_refs",
                ),
            ),
            "next_chapter_counts": count_map(
                next_memory,
                (
                    "fact_refs", "character_refs", "lore_refs", "foreshadow_refs",
                    "object_keys", "conflict_refs", "task_refs",
                ),
            ),
        }

    def _novel_memory_state_summary(self, project=None, chapter_index=None):
        project = project if isinstance(project, dict) else getattr(self, "current_project", {})
        project = project if isinstance(project, dict) else {}
        chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
        try:
            index = int(
                getattr(self, "current_chapter_index", -1)
                if chapter_index is None else chapter_index
            )
        except (TypeError, ValueError):
            index = -1
        chapter = chapters[index] if 0 <= index < len(chapters) and isinstance(chapters[index], dict) else {}
        memory = project.get("long_form_memory", {})
        memory = memory if isinstance(memory, dict) else {}
        snapshot = memory.get("state_snapshot", {})
        snapshot = snapshot if isinstance(snapshot, dict) else {}

        def count(value):
            return len(value) if isinstance(value, list) else 0

        return {
            "chapter_body_chars": len(str(chapter.get("text", "") or "")),
            "chapter_summary_chars": len(str(chapter.get("summary", "") or "")),
            "chapter_key_facts_chars": len(str(chapter.get("key_facts", "") or "")),
            "memory_sync_status": str(chapter.get("memory_sync_status", "") or ""),
            "chapter_memory_revision": int(chapter.get("memory_revision", 0) or 0),
            "chapter_memory_update_hash": str(chapter.get("memory_update_hash", "") or ""),
            "global_memory_revision": int(memory.get("revision", 0) or 0),
            "snapshot_chapter_index": int(snapshot.get("as_of_chapter_index", 0) or 0),
            "snapshot_chapter_id": str(snapshot.get("as_of_chapter_id", "") or ""),
            "snapshot_counts": {
                "active_facts": count(memory.get("active_facts", [])),
                "character_states": count(snapshot.get("character_states", [])),
                "relationship_states": count(snapshot.get("relationship_states", [])),
                "object_states": count(snapshot.get("object_states", [])),
                "active_conflicts": count(snapshot.get("active_conflicts", [])),
                "unresolved_tasks": count(snapshot.get("unresolved_tasks", [])),
                "long_term_events": count(chapter.get("long_term_events", [])),
            },
        }

    @staticmethod
    def _novel_memory_repair_targets(errors):
        targets = []
        for value in errors if isinstance(errors, list) else []:
            text = str(value or "").strip()
            if not text:
                continue
            target = re.split(r"[：:]", text, maxsplit=1)[0].strip()
            if target and target not in targets:
                targets.append(target)
        return targets[:30]

    def _persist_ai_generation_state(self):
        if not hasattr(self, "current_project_path") or not hasattr(self, "_draft_saved_once"):
            return
        try:
            self.current_project["updated_at"] = now_str()
            self._save_draft_snapshot()
            self._save_current_project_snapshot_if_named()
        except Exception as e:
            self._log_novel_diagnostic(
                "ai_generation_checkpoint_save_failed",
                level="error",
                project_path=str(getattr(self, "current_project_path", "") or NOVEL_DRAFT_FILE),
                error_category="storage",
                **self._novel_exception_details(e),
            )
            log_debug("小说AI生成检查点保存失败", e)

    def _store_memory_finalize_checkpoint(self, final_text, status="pending", error=""):
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if not (0 <= self.current_chapter_index < len(chapters)):
            return False
        chapter = chapters[self.current_chapter_index]
        if not isinstance(chapter, dict):
            return False
        text = str(final_text or "").strip()
        if not text:
            return False
        memory = self.current_project.get("long_form_memory", {})
        memory = memory if isinstance(memory, dict) else {}
        previous = chapter.get("ai_generation_checkpoint", {})
        previous = previous if isinstance(previous, dict) else {}
        pending = getattr(self, "_chapter_ai_memory_pending", {})
        pending = pending if isinstance(pending, dict) else {}
        task = self._current_chapter_ai_task_context()
        checkpoint = {
            "version": 2,
            "stage": "memory_finalize",
            "status": str(status or "pending"),
            "project_path": str(
                pending.get("project_path", "")
                or task.get("project_path", "")
                or getattr(self, "current_project_path", "")
                or ""
            ),
            "chapter_id": str(chapter.get("id", "") or ""),
            "chapter_index": int(
                pending.get("chapter_index", self.current_chapter_index)
                or self.current_chapter_index
            ),
            "request_id": str(
                pending.get("request_id", "")
                or task.get("request_id", "")
                or ""
            ),
            "task_generation": int(
                pending.get("task_generation", 0)
                or task.get("task_generation", 0)
                or 0
            ),
            "final_text": text,
            "final_text_sha256": self._chapter_ai_checkpoint_hash(text),
            "source_text_sha256": self._chapter_ai_checkpoint_hash(chapter.get("text", "")),
            "outline_sha256": self._chapter_ai_checkpoint_hash(chapter.get("outline", "")),
            "base_memory_revision": int(memory.get("revision", 0) or 0),
            "provider": str(
                (getattr(self, "_chapter_ai_provider", {}) or {}).get("name", "")
                if isinstance(getattr(self, "_chapter_ai_provider", {}), dict) else ""
            ),
            "model": str(getattr(self, "_chapter_ai_model", "") or ""),
            "transaction_id": str(
                pending.get("transaction_id", "")
                or getattr(self, "_chapter_ai_memory_transaction_id", "")
                or previous.get("transaction_id", "")
                or ""
            ),
            "created_at": str(previous.get("created_at", "") or now_str()),
            "updated_at": now_str(),
        }
        if error:
            checkpoint["error"] = str(error)[:1000]
        chapter["ai_generation_checkpoint"] = checkpoint
        if hasattr(self, "_note_project_dirty"):
            self._note_project_dirty()
        self._persist_ai_generation_state()
        return True

    def _store_memory_reconciliation_checkpoint(self, final_text, bundle, status="failed", error=""):
        """Persist a validated chapter package until its boundary audit succeeds."""
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if not (0 <= self.current_chapter_index < len(chapters)):
            return False
        chapter = chapters[self.current_chapter_index]
        if not isinstance(chapter, dict):
            return False
        text = str(final_text or "").strip()
        if not text or not isinstance(bundle, dict):
            return False
        memory = self.current_project.get("long_form_memory", {})
        memory = memory if isinstance(memory, dict) else {}
        previous = chapter.get("ai_generation_checkpoint", {})
        previous = previous if isinstance(previous, dict) else {}
        pending = getattr(self, "_chapter_ai_memory_pending", {})
        pending = pending if isinstance(pending, dict) else {}
        task = self._current_chapter_ai_task_context()
        checkpoint = {
            "version": 3,
            "stage": "memory_reconcile",
            "status": str(status or "failed"),
            "project_path": str(
                pending.get("project_path", "")
                or task.get("project_path", "")
                or getattr(self, "current_project_path", "")
                or ""
            ),
            "chapter_id": str(chapter.get("id", "") or ""),
            "chapter_index": int(
                pending.get("chapter_index", self.current_chapter_index)
                or self.current_chapter_index
            ),
            "request_id": str(
                pending.get("request_id", "")
                or task.get("request_id", "")
                or ""
            ),
            "task_generation": int(
                pending.get("task_generation", 0)
                or task.get("task_generation", 0)
                or 0
            ),
            "final_text": text,
            "final_text_sha256": self._chapter_ai_checkpoint_hash(text),
            "source_text_sha256": self._chapter_ai_checkpoint_hash(chapter.get("text", "")),
            "outline_sha256": self._chapter_ai_checkpoint_hash(chapter.get("outline", "")),
            "base_memory_revision": int(memory.get("revision", 0) or 0),
            "provider": str(
                (getattr(self, "_chapter_ai_provider", {}) or {}).get("name", "")
                if isinstance(getattr(self, "_chapter_ai_provider", {}), dict) else ""
            ),
            "model": str(getattr(self, "_chapter_ai_model", "") or ""),
            "transaction_id": str(
                pending.get("transaction_id", "")
                or getattr(self, "_chapter_ai_memory_transaction_id", "")
                or previous.get("transaction_id", "")
                or ""
            ),
            "bundle": deepcopy(bundle),
            "created_at": str(previous.get("created_at", "") or now_str()),
            "updated_at": now_str(),
        }
        if error:
            checkpoint["error"] = str(error)[:1000]
        if pending.get("already_committed"):
            # Preserve the legacy committed-state marker when a boundary
            # retry itself fails and has to be resumed again.
            checkpoint["already_committed"] = True
        chapter["ai_generation_checkpoint"] = checkpoint
        chapter["auto_expand_resume_required"] = True
        if hasattr(self, "_note_project_dirty"):
            self._note_project_dirty()
        self._persist_ai_generation_state()
        self._log_novel_diagnostic(
            "memory_reconciliation_checkpoint_saved",
            level="warning",
            action="memory_reconcile",
            transaction_id=str(checkpoint.get("transaction_id", "") or ""),
            status=str(status or "failed"),
            error=clean_error_text(error),
            final_text_chars=len(text),
            bundle_summary=self._novel_memory_bundle_summary(bundle),
            resume_required=True,
        )
        return True

    def _store_memory_repair_checkpoint(
        self,
        stage,
        final_text,
        bundle,
        validation_errors=None,
        logic_issues=None,
        repair_attempt=0,
        status="failed",
        error="",
    ):
        """Persist the exact structured inputs needed to resume a failed repair."""
        stage = str(stage or "").strip()
        if stage not in {"memory_repair", "logic_repair"}:
            return False
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if not (0 <= self.current_chapter_index < len(chapters)):
            return False
        chapter = chapters[self.current_chapter_index]
        if not isinstance(chapter, dict):
            return False
        text = str(final_text or "").strip()
        if not text or not isinstance(bundle, dict):
            return False
        memory = self.current_project.get("long_form_memory", {})
        memory = memory if isinstance(memory, dict) else {}
        previous = chapter.get("ai_generation_checkpoint", {})
        previous = previous if isinstance(previous, dict) else {}
        pending = getattr(self, "_chapter_ai_memory_pending", {})
        pending = pending if isinstance(pending, dict) else {}
        task = self._current_chapter_ai_task_context()
        try:
            attempt = int(repair_attempt or 0)
        except (TypeError, ValueError):
            attempt = 0
        linked_characters = chapter.get("linked_characters", [])
        try:
            linked_characters_hash = self._chapter_ai_checkpoint_hash(
                json.dumps(linked_characters, ensure_ascii=False, sort_keys=True, default=str)
            )
        except Exception:
            linked_characters_hash = self._chapter_ai_checkpoint_hash(linked_characters)
        checkpoint = {
            "version": 4,
            "stage": stage,
            "status": str(status or "failed"),
            "project_path": str(
                pending.get("project_path", "")
                or task.get("project_path", "")
                or getattr(self, "current_project_path", "")
                or ""
            ),
            "chapter_id": str(chapter.get("id", "") or ""),
            "chapter_index": int(
                pending.get("chapter_index", self.current_chapter_index)
                or self.current_chapter_index
            ),
            "request_id": str(
                pending.get("request_id", "")
                or task.get("request_id", "")
                or ""
            ),
            "task_generation": int(
                pending.get("task_generation", 0)
                or task.get("task_generation", 0)
                or 0
            ),
            "final_text": text,
            "final_text_sha256": self._chapter_ai_checkpoint_hash(text),
            "source_text_sha256": self._chapter_ai_checkpoint_hash(chapter.get("text", "")),
            "outline_sha256": self._chapter_ai_checkpoint_hash(chapter.get("outline", "")),
            "summary_sha256": self._chapter_ai_checkpoint_hash(chapter.get("summary", "")),
            "key_facts_sha256": self._chapter_ai_checkpoint_hash(chapter.get("key_facts", "")),
            "linked_characters_sha256": linked_characters_hash,
            "base_memory_revision": int(memory.get("revision", 0) or 0),
            "provider": str(
                (getattr(self, "_chapter_ai_provider", {}) or {}).get("name", "")
                if isinstance(getattr(self, "_chapter_ai_provider", {}), dict) else ""
            ),
            "model": str(getattr(self, "_chapter_ai_model", "") or ""),
            "transaction_id": str(
                pending.get("transaction_id", "")
                or getattr(self, "_chapter_ai_memory_transaction_id", "")
                or previous.get("transaction_id", "")
                or ""
            ),
            "bundle": deepcopy(bundle),
            "validation_errors": [
                str(item) for item in validation_errors or [] if str(item or "").strip()
            ],
            "logic_issues": [
                deepcopy(item) for item in logic_issues or [] if isinstance(item, dict)
            ],
            "logic_audit_required": bool(
                pending.get("logic_audit_required", stage == "logic_repair")
            ),
            "repair_attempt": attempt,
            "created_at": str(
                previous.get("created_at", "")
                if previous.get("stage") == stage else now_str()
            ),
            "updated_at": now_str(),
        }
        if error:
            checkpoint["error"] = str(error)[:1000]
        chapter["ai_generation_checkpoint"] = checkpoint
        chapter["auto_expand_resume_required"] = True
        if hasattr(self, "_note_project_dirty"):
            self._note_project_dirty()
        self._persist_ai_generation_state()
        self._log_novel_diagnostic(
            "memory_repair_checkpoint_saved",
            level="warning",
            action=stage,
            status=str(status or "failed"),
            error=clean_error_text(error),
            repair_attempt=attempt,
            final_text_chars=len(text),
            final_text_sha256=self._chapter_ai_checkpoint_hash(text),
            validation_error_count=len(checkpoint["validation_errors"]),
            logic_issue_count=len(checkpoint["logic_issues"]),
            resume_required=True,
        )
        return True

    def _validated_memory_repair_checkpoint(self):
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if not (0 <= self.current_chapter_index < len(chapters)):
            return None
        chapter = chapters[self.current_chapter_index]
        if not isinstance(chapter, dict):
            return None
        checkpoint = chapter.get("ai_generation_checkpoint", {})
        if not isinstance(checkpoint, dict):
            return None
        stage = str(checkpoint.get("stage", "") or "")
        if stage not in {"memory_repair", "logic_repair"}:
            return None
        text = str(checkpoint.get("final_text", "") or "").strip()
        bundle = checkpoint.get("bundle")
        memory = self.current_project.get("long_form_memory", {})
        memory = memory if isinstance(memory, dict) else {}
        try:
            checkpoint_revision = int(checkpoint.get("base_memory_revision", -1) or 0)
            memory_revision = int(memory.get("revision", 0) or 0)
            raw_checkpoint_index = checkpoint.get("chapter_index", -1)
            checkpoint_index = int(
                raw_checkpoint_index if raw_checkpoint_index is not None else -1
            )
        except (TypeError, ValueError):
            return None
        checkpoint_project_path = self._canonical_project_path(checkpoint.get("project_path", ""))
        current_project_path = self._canonical_project_path(getattr(self, "current_project_path", ""))
        project_matches = (
            not checkpoint_project_path
            or not current_project_path
            or checkpoint_project_path == current_project_path
        )
        linked_characters = chapter.get("linked_characters", [])
        try:
            linked_characters_hash = self._chapter_ai_checkpoint_hash(
                json.dumps(linked_characters, ensure_ascii=False, sort_keys=True, default=str)
            )
        except Exception:
            linked_characters_hash = self._chapter_ai_checkpoint_hash(linked_characters)
        source_hash = str(checkpoint.get("source_text_sha256", "") or "")
        current_text_hash = self._chapter_ai_checkpoint_hash(chapter.get("text", ""))
        final_text_hash = self._chapter_ai_checkpoint_hash(text)
        source_matches = source_hash == current_text_hash or current_text_hash == final_text_hash
        common_valid = bool(
            int(checkpoint.get("version", 0) or 0) == 4
            and str(checkpoint.get("chapter_id", "") or "") == str(chapter.get("id", "") or "")
            and checkpoint_index == int(self.current_chapter_index)
            and project_matches
            and text
            and str(checkpoint.get("final_text_sha256", "") or "") == final_text_hash
            and source_matches
            and str(checkpoint.get("outline_sha256", "") or "")
            == self._chapter_ai_checkpoint_hash(chapter.get("outline", ""))
            and str(checkpoint.get("summary_sha256", "") or "")
            == self._chapter_ai_checkpoint_hash(chapter.get("summary", ""))
            and str(checkpoint.get("key_facts_sha256", "") or "")
            == self._chapter_ai_checkpoint_hash(chapter.get("key_facts", ""))
            and str(checkpoint.get("linked_characters_sha256", "") or "") == linked_characters_hash
            and checkpoint_revision == memory_revision
            and isinstance(bundle, dict)
            and str(chapter.get("memory_sync_status", "") or "") in {"pending", "failed"}
        )
        if stage == "memory_repair":
            valid = common_valid and bool(
                isinstance(checkpoint.get("validation_errors"), list)
                and checkpoint.get("validation_errors")
            )
        else:
            valid = common_valid and bool(
                isinstance(checkpoint.get("logic_issues"), list)
                and checkpoint.get("logic_issues")
                and all(isinstance(item, dict) for item in checkpoint.get("logic_issues", []))
            )
        return deepcopy(checkpoint) if valid else None

    def _validated_memory_reconciliation_checkpoint(self):
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if not (0 <= self.current_chapter_index < len(chapters)):
            return None
        chapter = chapters[self.current_chapter_index]
        if not isinstance(chapter, dict):
            return None
        checkpoint = chapter.get("ai_generation_checkpoint", {})
        if not isinstance(checkpoint, dict) or str(checkpoint.get("stage", "") or "") != "memory_reconcile":
            return None
        text = str(checkpoint.get("final_text", "") or "").strip()
        bundle = checkpoint.get("bundle")
        memory = self.current_project.get("long_form_memory", {})
        memory = memory if isinstance(memory, dict) else {}
        try:
            checkpoint_revision = int(checkpoint.get("base_memory_revision", -1) or 0)
            memory_revision = int(memory.get("revision", 0) or 0)
            raw_checkpoint_index = checkpoint.get("chapter_index", -1)
            checkpoint_index = int(
                raw_checkpoint_index if raw_checkpoint_index is not None else -1
            )
        except (TypeError, ValueError):
            return None
        checkpoint_project_path = self._canonical_project_path(checkpoint.get("project_path", ""))
        current_project_path = self._canonical_project_path(getattr(self, "current_project_path", ""))
        project_matches = (
            not checkpoint_project_path
            or not current_project_path
            or checkpoint_project_path == current_project_path
        )
        valid = bool(
            int(checkpoint.get("version", 0) or 0) == 3
            and str(checkpoint.get("chapter_id", "") or "") == str(chapter.get("id", "") or "")
            and checkpoint_index == int(self.current_chapter_index)
            and project_matches
            and text
            and str(checkpoint.get("final_text_sha256", "") or "")
            == self._chapter_ai_checkpoint_hash(text)
            and str(checkpoint.get("outline_sha256", "") or "")
            == self._chapter_ai_checkpoint_hash(chapter.get("outline", ""))
            and checkpoint_revision == memory_revision
            and isinstance(bundle, dict)
            and isinstance(bundle.get("memory_update"), dict)
            and str(chapter.get("memory_reconciliation_status", "") or "") in {"pending", "failed"}
        )
        return deepcopy(checkpoint) if valid else None

    def _memory_finalize_checkpoint_text(self, chapter):
        if not isinstance(chapter, dict):
            return ""
        checkpoint = chapter.get("ai_generation_checkpoint", {})
        if not isinstance(checkpoint, dict) or not checkpoint:
            return ""
        text = str(checkpoint.get("final_text", "") or "").strip()
        memory = self.current_project.get("long_form_memory", {})
        memory = memory if isinstance(memory, dict) else {}
        current_text_hash = self._chapter_ai_checkpoint_hash(chapter.get("text", ""))
        final_text_hash = self._chapter_ai_checkpoint_hash(text)
        checkpoint_source_hash = str(checkpoint.get("source_text_sha256", "") or "")
        try:
            checkpoint_version = int(checkpoint.get("version", 0) or 0)
        except Exception:
            checkpoint_version = 0
        try:
            checkpoint_revision = int(checkpoint.get("base_memory_revision", -1) or 0)
        except Exception:
            checkpoint_revision = -1
        try:
            memory_revision = int(memory.get("revision", 0) or 0)
        except Exception:
            memory_revision = 0
        checkpoint_project_path = self._canonical_project_path(
            checkpoint.get("project_path", "")
        )
        current_project_path = self._canonical_project_path(
            getattr(self, "current_project_path", "")
        )
        project_matches = (
            checkpoint_version < 2
            or bool(checkpoint_project_path and current_project_path)
            and checkpoint_project_path == current_project_path
        )
        try:
            raw_checkpoint_index = checkpoint.get("chapter_index", -1)
            checkpoint_index = int(
                raw_checkpoint_index
                if raw_checkpoint_index is not None and str(raw_checkpoint_index).strip()
                else -1
            )
        except (TypeError, ValueError):
            checkpoint_index = -1
        try:
            current_chapter_index = int(getattr(self, "current_chapter_index", -1))
        except (TypeError, ValueError):
            current_chapter_index = -1
        chapter_index_matches = (
            checkpoint_version < 2
            or checkpoint_index == current_chapter_index
        )
        source_matches = checkpoint_source_hash == current_text_hash or current_text_hash == final_text_hash
        valid = (
            checkpoint_version in {1, 2}
            and str(checkpoint.get("stage", "") or "") == "memory_finalize"
            and str(checkpoint.get("chapter_id", "") or "") == str(chapter.get("id", "") or "")
            and project_matches
            and chapter_index_matches
            and bool(text)
            and str(checkpoint.get("final_text_sha256", "") or "") == final_text_hash
            and source_matches
            and str(checkpoint.get("outline_sha256", "") or "")
            == self._chapter_ai_checkpoint_hash(chapter.get("outline", ""))
            and checkpoint_revision == memory_revision
            and str(chapter.get("memory_sync_status", "") or "") in {"pending", "failed"}
        )
        if not valid:
            return ""
        return text

    def _validated_memory_finalize_checkpoint(self):
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if not (0 <= self.current_chapter_index < len(chapters)):
            return ""
        return self._memory_finalize_checkpoint_text(chapters[self.current_chapter_index])

    def _clear_memory_finalize_checkpoint(self, persist=False):
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if not (0 <= self.current_chapter_index < len(chapters)):
            return False
        chapter = chapters[self.current_chapter_index]
        if not isinstance(chapter, dict) or not chapter.get("ai_generation_checkpoint"):
            return False
        checkpoint = chapter.get("ai_generation_checkpoint", {})
        if (
            isinstance(checkpoint, dict)
            and str(checkpoint.get("stage", "") or "") == "memory_reconcile"
            and str(chapter.get("memory_reconciliation_status", "") or "") != "complete"
        ):
            return False
        chapter["ai_generation_checkpoint"] = {}
        if hasattr(self, "_note_project_dirty"):
            self._note_project_dirty()
        if persist:
            self._persist_ai_generation_state()
        return True

    def _start_memory_finalize(
        self,
        final_text,
        resumed=False,
        prose_patch_applied=False,
        transient_retry=False,
    ):
        text = str(final_text or "").strip()
        if not text:
            self._fail_memory_sync("正文终稿为空，无法整理章节状态")
            return
        repaired_text, literal_count_issues = _repair_literal_count_claims(text)
        if literal_count_issues and repaired_text != text:
            self._log_novel_diagnostic(
                "literal_count_claim_normalized",
                level="warning",
                chapter_id=self._current_chapter_id(),
                issue_count=len(literal_count_issues),
                issues=[
                    {
                        "claimed": int(item.get("claimed", 0) or 0),
                        "claim_text": str(item.get("claim_text", "") or ""),
                        "replacement_text": str(item.get("replacement_text", "") or ""),
                        "normalization": str(item.get("normalization", "") or ""),
                    }
                    for item in literal_count_issues[:5]
                ],
            )
            text = repaired_text
        text, replacements = _sanitize_prose_internal_references(
            self.current_project if isinstance(self.current_project, dict) else {},
            text,
            strip_metadata=True,
        )
        if replacements:
            self._log_novel_diagnostic(
                "chapter_prose_internal_reference_sanitized",
                level="warning",
                chapter_id=self._current_chapter_id(),
                replacements=replacements,
                before_chars=len(str(final_text or "")),
                after_chars=len(text),
                source="memory_finalize_resume",
            )
        self._chapter_ai_memory_finalize_attempted = True
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        checkpoint = (
            chapters[self.current_chapter_index].get("ai_generation_checkpoint", {})
            if 0 <= self.current_chapter_index < len(chapters)
            and isinstance(chapters[self.current_chapter_index], dict)
            and isinstance(chapters[self.current_chapter_index].get("ai_generation_checkpoint"), dict)
            else {}
        )
        self._chapter_ai_memory_transaction_id = str(
            checkpoint.get("transaction_id", "")
            or self._next_novel_diagnostic_request_id("memory-sync")
        )
        self._chapter_ai_memory_pending = {
            "chapter_id": self._current_chapter_id(),
            "transaction_id": self._chapter_ai_memory_transaction_id,
            "final_text": text,
            "bundle": {},
            "errors": [],
            "logic_audit_required": True,
            "reconciliation_started": False,
            "prose_patch_applied": bool(prose_patch_applied),
        }
        if 0 <= self.current_chapter_index < len(chapters) and isinstance(chapters[self.current_chapter_index], dict):
            chapter = chapters[self.current_chapter_index]
            if (self.current_chapter_index + 1) % 10 == 0:
                chapter["memory_reconciliation_status"] = "pending"
                chapter["memory_reconciliation_error"] = ""
            else:
                chapter["memory_reconciliation_status"] = "skipped"
                chapter["memory_reconciliation_error"] = ""
        self._store_memory_finalize_checkpoint(text)
        context = _build_long_form_memory_finalize_context(
            self._ai_project_snapshot(),
            self.current_chapter_index,
            text,
        )
        if transient_retry:
            context = (
                "【本次是状态整理重试】\n"
                "上一次状态整理结果未能通过解析或完整校验，正文尚未提交长期状态。"
                "本次必须先完整返回outline、summary、key_facts和long_form_memory，再返回三个审校字段；"
                "不能只返回审校字段。请依据下方完整资料重新整理本章状态。\n\n"
                + context
            )
        self.chapter_ai_preview.setPlainText(text)
        self.chapter_ai_stream_text = ""
        status_text = (
            "已应用必要的局部修补，正在重新整理状态并复核本章..."
            if prose_patch_applied else
            f"已识别后台保存的完整正文（{len(text)}字），不重写正文，正在补摘要和长期状态..."
            if resumed else
            "正文已完成，正在整理摘要、关键事实、长期状态并检查本章读感..."
        )
        worker_kwargs = {"transient_retry": True} if transient_retry else {}
        self._start_chapter_ai_worker(
            "memory_finalize",
            context,
            status_text,
            **worker_kwargs,
        )

    def _start_memory_reconciliation(self, final_text, bundle, resumed=False):
        pending = getattr(self, "_chapter_ai_memory_pending", {})
        if not isinstance(pending, dict) or pending.get("chapter_id") != self._current_chapter_id():
            self._fail_memory_sync("章节已切换，无法启动边界状态对账")
            return
        pending["bundle"] = deepcopy(bundle) if isinstance(bundle, dict) else {}
        pending["reconciliation_started"] = True
        self._chapter_ai_memory_pending = pending
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if 0 <= self.current_chapter_index < len(chapters) and isinstance(chapters[self.current_chapter_index], dict):
            chapters[self.current_chapter_index]["memory_reconciliation_status"] = "pending"
            chapters[self.current_chapter_index]["memory_reconciliation_error"] = ""
        context = _build_long_form_memory_reconcile_context(
            self._ai_project_snapshot(),
            self.current_chapter_index,
            final_text,
            (bundle or {}).get("memory_update", {}) if isinstance(bundle, dict) else {},
            summary=(bundle or {}).get("summary", "") if isinstance(bundle, dict) else "",
            key_facts=(bundle or {}).get("key_facts", "") if isinstance(bundle, dict) else "",
        )
        self.chapter_ai_preview.setPlainText(str(final_text or "").strip())
        self.chapter_ai_stream_text = ""
        self._start_chapter_ai_worker(
            "memory_reconcile",
            context,
            (
                "正在恢复上次未完成的十章边界对账，不重写正文和状态整理..."
                if resumed else
                "十章边界状态已通过结构校验，正在执行一次语义对账（只修正状态，不阻断正文）..."
            ),
        )

    def _apply_memory_reconciliation_fallback(self, message, status="failed"):
        pending = getattr(self, "_chapter_ai_memory_pending", {})
        if not isinstance(pending, dict):
            self._fail_memory_sync(message)
            return
        transaction_id = str(pending.get("transaction_id", "") or "")
        state_before = self._novel_memory_state_summary()
        self._log_novel_diagnostic(
            "memory_reconciliation_fallback",
            level="warning",
            action="memory_reconcile",
            transaction_id=transaction_id,
            fallback_status=str(status or "failed"),
            error=clean_error_text(message),
            repair_triggered=False,
            committed=False,
            commit_mode="deferred_until_reconciliation_success",
            resume_required=True,
            state_before=state_before,
            bundle_summary=self._novel_memory_bundle_summary(
                pending.get("bundle", {}) if isinstance(pending.get("bundle"), dict) else {}
            ),
        )
        final_text = str(pending.get("final_text", "") or "").strip()
        bundle = deepcopy(pending.get("bundle", {})) if isinstance(pending.get("bundle"), dict) else {}
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if 0 <= self.current_chapter_index < len(chapters) and isinstance(chapters[self.current_chapter_index], dict):
            chapter = chapters[self.current_chapter_index]
            chapter["memory_reconciliation_status"] = str(status or "failed")
            chapter["memory_reconciliation_error"] = str(message or "")[:1000]
            chapter["memory_sync_status"] = "failed"
            chapter["memory_sync_error"] = str(message or "")[:1000]
        checkpoint_saved = bool(
            final_text
            and bundle
            and self._store_memory_reconciliation_checkpoint(
                final_text,
                bundle,
                status=status,
                error=message,
            )
        )
        self._chapter_ai_memory_pending = {}
        self._chapter_ai_style_workflow_active = False
        self._set_partial_chapter_ai_preview_state(False)
        self._reset_chapter_ai_sequence()
        if final_text:
            self.chapter_ai_preview.setPlainText(final_text)
        if not checkpoint_saved:
            self._fail_memory_sync(message)
            return
        if getattr(self, "_auto_expand_all_active", False):
            self._stop_auto_expand_all(
                f"自动扩写已暂停：第{self.current_chapter_index + 1}章十章边界对账失败；"
                "下次启动时将从对账继续，不会重写正文。"
            )
        self._set_chapter_ai_actions_enabled(True)
        self.set_status_tip(
            "十章边界对账未完成，已保留正文、状态包和恢复检查点；"
            "下次单章扩写或自动扩写启动时将从对账继续。"
        )

    def _handle_memory_reconciliation_ready(self, content):
        pending = getattr(self, "_chapter_ai_memory_pending", {})
        if not isinstance(pending, dict) or pending.get("chapter_id") != self._current_chapter_id():
            self._fail_memory_sync("章节已切换，对账结果未应用")
            return
        transaction_id = str(pending.get("transaction_id", "") or "")
        parsed = _parse_memory_reconciliation_result(content)
        corrections = parsed.get("corrections", {}) if isinstance(parsed, dict) else {}
        corrections = corrections if isinstance(corrections, dict) else {}
        self._log_novel_diagnostic(
            "memory_reconciliation_output_parsed",
            action="memory_reconcile",
            transaction_id=transaction_id,
            parsed=bool(parsed.get("parsed")) if isinstance(parsed, dict) else False,
            output_chars=len(str(content or "")),
            output_sha256=self._chapter_ai_checkpoint_hash(content),
            correction_keys=sorted(str(key) for key in corrections.keys())[:30],
            correction_count=len(corrections),
        )
        if not parsed.get("parsed"):
            if self._schedule_transient_chapter_ai_retry(
                "memory_reconcile",
                "边界语义对账结果无法解析",
                force_retry=True,
            ):
                return
            self._apply_memory_reconciliation_fallback("边界语义对账结果无法解析")
            return
        original_bundle = deepcopy(pending.get("bundle", {})) if isinstance(pending.get("bundle"), dict) else {}
        final_text = str(pending.get("final_text", "") or "").strip()
        merged_update = _merge_long_form_memory_reconciliation_patch(
            original_bundle.get("memory_update", {}) if isinstance(original_bundle, dict) else {},
            parsed.get("corrections", {}),
            project=self.current_project if isinstance(getattr(self, "current_project", None), dict) else None,
        )
        merged_update = _literalize_long_form_memory_evidence(merged_update, final_text)
        if isinstance(getattr(self, "current_project", None), dict):
            merged_update = _normalize_long_form_structural_refs(
                self.current_project,
                self.current_chapter_index,
                merged_update,
            )
        bundle = deepcopy(original_bundle)
        bundle["memory_update"] = merged_update
        errors = self._memory_bundle_validation_errors(final_text, bundle)
        if errors:
            self._log_novel_diagnostic(
                "memory_reconciliation_validation_failed",
                level="warning",
                action="memory_reconcile",
                transaction_id=transaction_id,
                validation_errors=errors,
                repair_targets=self._novel_memory_repair_targets(errors),
                bundle_summary=self._novel_memory_bundle_summary(bundle),
                state_before=self._novel_memory_state_summary(),
            )
            if self._schedule_transient_chapter_ai_retry(
                "memory_reconcile",
                "对账纠错补丁未通过完整校验：" + "；".join(errors),
                force_retry=True,
            ):
                return
            self._apply_memory_reconciliation_fallback(
                "对账纠错补丁未通过完整校验，已保留原状态包等待下次对账：" + "；".join(errors)
            )
            return
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if 0 <= self.current_chapter_index < len(chapters) and isinstance(chapters[self.current_chapter_index], dict):
            chapter = chapters[self.current_chapter_index]
            chapter["memory_reconciliation_status"] = "complete"
            chapter["memory_reconciliation_error"] = ""
        self._clear_transient_chapter_ai_retry("memory_reconcile")
        self._chapter_ai_memory_pending = {}
        self._apply_style_final_result(final_text, bundle, memory_validated=True)

    def _handle_memory_finalize_ready(self, content):
        pending = getattr(self, "_chapter_ai_memory_pending", {})
        if not isinstance(pending, dict) or pending.get("chapter_id") != self._current_chapter_id():
            self._fail_memory_sync("章节已切换，状态整理结果未应用")
            return
        parsed = _parse_memory_repair_result(content)
        memory_update = deepcopy(parsed.get("memory_update", {})) \
            if isinstance(parsed.get("memory_update"), dict) else {}
        if parsed.get("repair_mode") == "patch":
            # A compatible response may contain a complete long_form_memory
            # object without the outer response brace. Keep it in the normal
            # validation path instead of treating the package as empty.
            memory_update = _merge_long_form_memory_repair_patch(
                {}, parsed.get("memory_patch", {})
            )
        bundle = {
            "outline": str(parsed.get("outline", "") or "").strip(),
            "summary": str(parsed.get("summary", "") or "").strip(),
            "key_facts": str(parsed.get("key_facts", "") or "").strip(),
            "memory_update": memory_update,
            "logic_audit": deepcopy(parsed.get("logic_audit", {}))
            if isinstance(parsed.get("logic_audit"), dict) else {},
            "prose_review": deepcopy(parsed.get("prose_review", {}))
            if isinstance(parsed.get("prose_review"), dict) else {},
            "repair_patches": deepcopy(parsed.get("repair_patches", []))
            if isinstance(parsed.get("repair_patches"), list) else [],
        }
        final_text = str(pending.get("final_text", "") or "").strip()
        transaction_id = str(pending.get("transaction_id", "") or "")
        self._log_novel_diagnostic(
            "memory_finalize_output_parsed",
            action="memory_finalize",
            transaction_id=transaction_id,
            parsed=bool(parsed.get("parsed")),
            output_chars=len(str(content or "")),
            output_sha256=self._chapter_ai_checkpoint_hash(content),
            bundle_summary=self._novel_memory_bundle_summary(bundle),
        )
        if not parsed.get("parsed"):
            self._log_novel_diagnostic(
                "memory_finalize_empty_package",
                level="warning",
                action="memory_finalize",
                transaction_id=transaction_id,
                parsed=False,
                package_status="parse_failed",
                output_chars=len(str(content or "")),
                output_sha256=self._chapter_ai_checkpoint_hash(content),
                final_text_chars=len(final_text),
                package_summary=self._novel_memory_bundle_summary(bundle),
                resume_required=True,
            )
            if self._schedule_transient_chapter_ai_retry(
                "memory_finalize",
                "独立状态整理结果无法解析（JSON格式错误）",
                force_retry=True,
                retry_callback=lambda tab: tab._start_memory_finalize(
                    final_text,
                    resumed=True,
                    prose_patch_applied=bool(pending.get("prose_patch_applied")),
                    transient_retry=True,
                ),
            ):
                return
            self._fail_memory_sync("独立状态整理结果无法解析（JSON格式错误）")
            return
        package_summary = self._novel_memory_bundle_summary(bundle)
        package_count_groups = (
            package_summary.get("state_patch_counts", {}),
            package_summary.get("record_update_counts", {}),
            package_summary.get("reconciliation_counts", {}),
            package_summary.get("next_chapter_counts", {}),
        )
        package_has_delta = any(
            int(value or 0) > 0
            for group in package_count_groups
            if isinstance(group, dict)
            for value in group.values()
        ) or int(package_summary.get("fact_updates", 0) or 0) > 0 \
            or int(package_summary.get("long_term_events", 0) or 0) > 0 \
            or bool(bundle.get("memory_update", {}).get("stage_archive")) \
            or bool(bundle.get("memory_update", {}).get("state_delta"))
        package_has_text = any(
            int(package_summary.get(key, 0) or 0) > 0
            for key in ("outline_chars", "summary_chars", "key_facts_chars")
        )
        if not package_has_text and not package_has_delta:
            self._log_novel_diagnostic(
                "memory_finalize_empty_package",
                level="warning",
                action="memory_finalize",
                transaction_id=transaction_id,
                parsed=True,
                package_status="empty",
                output_chars=len(str(content or "")),
                output_sha256=self._chapter_ai_checkpoint_hash(content),
                final_text_chars=len(final_text),
                package_summary=package_summary,
                resume_required=True,
            )
            if self._schedule_transient_chapter_ai_retry(
                "memory_finalize",
                "独立状态整理结果为空，已保留正文并等待下次状态整理",
                force_retry=True,
                retry_callback=lambda tab: tab._start_memory_finalize(
                    final_text,
                    resumed=True,
                    prose_patch_applied=bool(pending.get("prose_patch_applied")),
                    transient_retry=True,
                ),
            ):
                return
            self._fail_memory_sync("独立状态整理结果为空，已保留正文并等待下次状态整理")
            return
        audit_errors = _chapter_logic_audit_validation_errors(
            final_text, bundle.get("logic_audit", {})
        )
        logic_issues = _chapter_logic_audit_blocking_issues(bundle.get("logic_audit", {}))
        # A confirmed prose contradiction must be repaired before validating
        # its derived state bundle: the repair may change the evidence that
        # supports the summary and long-form memory update.
        if logic_issues:
            self._clear_transient_chapter_ai_retry("memory_finalize")
            self._start_chapter_logic_repair(final_text, bundle, logic_issues)
            return
        bundle_errors = self._memory_bundle_validation_errors(final_text, bundle)
        validation_errors = list(dict.fromkeys(audit_errors + bundle_errors))
        if validation_errors:
            self._log_novel_diagnostic(
                "memory_finalize_validation_collected",
                level="warning",
                action="memory_finalize",
                transaction_id=transaction_id,
                validation_error_count=len(validation_errors),
                validation_errors=validation_errors,
                repair_targets=self._novel_memory_repair_targets(validation_errors),
                audit_error_count=len(audit_errors),
                bundle_error_count=len(bundle_errors),
            )
            # Structural validation failures are deterministic for this exact
            # package. Re-running the full finalize prompt only repeats the
            # same omission and burns the transport retry budget; the repair
            # prompt already receives the concrete validation errors.
            self._clear_transient_chapter_ai_retry("memory_finalize")
            self._start_memory_repair(final_text, bundle, validation_errors)
            return
        patches = bundle.get("repair_patches", [])
        if patches and not pending.get("prose_patch_applied"):
            repaired_text, patch_errors = _apply_chapter_prose_repair_patches(final_text, patches)
            if not patch_errors and repaired_text != final_text:
                self._log_novel_diagnostic(
                    "chapter_prose_repair_patch_applied",
                    level="info",
                    chapter_id=self._current_chapter_id(),
                    patch_count=len(patches),
                    prose_review=deepcopy(bundle.get("prose_review", {})),
                    before_chars=len(final_text),
                    after_chars=len(repaired_text),
                )
                self.chapter_ai_preview.setPlainText(repaired_text)
                self._clear_transient_chapter_ai_retry("memory_finalize")
                self._start_memory_finalize(repaired_text, prose_patch_applied=True)
                return
            self._log_novel_diagnostic(
                "chapter_prose_repair_patch_skipped",
                level="warning",
                chapter_id=self._current_chapter_id(),
                patch_count=len(patches),
                validation_errors=patch_errors,
            )
            if patch_errors:
                if self._schedule_transient_chapter_ai_retry(
                    "memory_finalize",
                    "正文修复补丁校验失败：" + "；".join(patch_errors),
                    force_retry=True,
                ):
                    return
                self._fail_memory_sync("正文修复补丁校验失败：" + "；".join(patch_errors))
                return
        if (self.current_chapter_index + 1) % 10 == 0 and not pending.get("reconciliation_started"):
            self._clear_transient_chapter_ai_retry("memory_finalize")
            self._start_memory_reconciliation(final_text, bundle)
            return
        self._clear_transient_chapter_ai_retry("memory_finalize")
        self._chapter_ai_memory_pending = {}
        self.chapter_ai_preview.setPlainText(final_text)
        self._apply_style_final_result(final_text, bundle, memory_validated=True)

    def _memory_bundle_validation_errors(self, final_text, bundle):
        errors = []
        if not isinstance(bundle, dict):
            return ["终稿附带资料无法解析"]
        for key, label in (("outline", "实际提纲"), ("summary", "本章摘要"), ("key_facts", "关键事实")):
            if not str(bundle.get(key, "") or "").strip():
                errors.append(f"{label}为空")
        if not isinstance(getattr(self, "current_project", None), dict):
            return errors
        normalized_update = _literalize_long_form_memory_evidence(
            bundle.get("memory_update", {}), final_text
        )
        normalized_update = _normalize_long_form_structural_refs(
            self.current_project,
            self.current_chapter_index,
            normalized_update,
        )
        # Keep the normalized compact delta in the repair checkpoint as well.
        # A repair call should patch one stable shape instead of rediscovering
        # the omitted deterministic review fields.
        bundle["memory_update"] = normalized_update
        update_errors = _validate_long_form_memory_update(
            self.current_project,
            self.current_chapter_index,
            normalized_update,
            final_text=final_text,
            require_revision=True,
            require_evidence=True,
        )
        errors.extend(update_errors)
        return errors

    def _start_memory_repair(
        self,
        final_text,
        bundle,
        validation_errors=None,
        transient_retry=False,
    ):
        previous_pending = getattr(self, "_chapter_ai_memory_pending", {})
        logic_audit_required = bool(
            previous_pending.get("logic_audit_required", False)
            if isinstance(previous_pending, dict) else False
        )
        attempts = int(getattr(self, "_chapter_ai_memory_repair_attempts", 0) or 0) + 1
        self._chapter_ai_memory_repair_attempts = attempts
        validation_errors = [str(item) for item in validation_errors or []]
        self._log_novel_diagnostic(
            "memory_validation_failed",
            level="warning",
            action="memory_repair",
            validation_attempt=attempts,
            validation_errors=validation_errors,
            final_text_chars=len(str(final_text or "").strip()),
            final_text_sha256=self._chapter_ai_checkpoint_hash(final_text),
        )
        self._chapter_ai_memory_pending = {
            "chapter_id": self._current_chapter_id(),
            "transaction_id": str(
                previous_pending.get("transaction_id", "")
                or getattr(self, "_chapter_ai_memory_transaction_id", "")
                or self._next_novel_diagnostic_request_id("memory-sync")
            ),
            "final_text": str(final_text or "").strip(),
            "bundle": deepcopy(bundle) if isinstance(bundle, dict) else {},
            "errors": validation_errors,
            "logic_audit_required": logic_audit_required,
        }
        self._store_memory_repair_checkpoint(
            "memory_repair",
            final_text,
            self._chapter_ai_memory_pending["bundle"],
            validation_errors=validation_errors,
            repair_attempt=attempts,
            status="pending",
        )
        context = _build_long_form_memory_repair_context(
            self._ai_project_snapshot(),
            self.current_chapter_index,
            final_text,
            outline=(bundle or {}).get("outline", "") if isinstance(bundle, dict) else "",
            summary=(bundle or {}).get("summary", "") if isinstance(bundle, dict) else "",
            key_facts=(bundle or {}).get("key_facts", "") if isinstance(bundle, dict) else "",
            logic_audit=(bundle or {}).get("logic_audit", {}) if isinstance(bundle, dict) else {},
            memory_update=(bundle or {}).get("memory_update", {}) if isinstance(bundle, dict) else {},
            validation_errors=validation_errors,
        )
        self.chapter_ai_preview.setPlainText(str(final_text or "").strip())
        self.chapter_ai_stream_text = ""
        worker_kwargs = {"transient_retry": True} if transient_retry else {}
        self._start_chapter_ai_worker(
            "memory_repair",
            context,
            f"正文终稿已保留，状态数据有{len(validation_errors)}项需修复，"
            f"正在处理（阶段重试预算 {_CHAPTER_AI_MAX_RETRIES} 次）...",
            **worker_kwargs,
        )

    def _start_chapter_logic_repair(
        self, final_text, bundle, logic_issues, transient_retry=False
    ):
        previous_pending = getattr(self, "_chapter_ai_memory_pending", {})
        previous_pending = previous_pending if isinstance(previous_pending, dict) else {}
        attempts = int(getattr(self, "_chapter_ai_logic_repair_attempts", 0) or 0) + 1
        self._chapter_ai_logic_repair_attempts = attempts
        issues = [deepcopy(item) for item in logic_issues if isinstance(item, dict)][:3]
        self._chapter_ai_memory_pending = {
            "chapter_id": self._current_chapter_id(),
            "transaction_id": str(
                previous_pending.get("transaction_id", "")
            ) or self._next_novel_diagnostic_request_id("memory-sync"),
            "final_text": str(final_text or "").strip(),
            "bundle": deepcopy(bundle) if isinstance(bundle, dict) else {},
            "errors": [],
            "logic_audit_required": True,
            "logic_issues": issues,
        }
        if not issues:
            self._fail_memory_sync(
                "终稿逻辑审查仍发现明确矛盾，已停止自动写入，正文保留在恢复检查点中"
            )
            return
        self._store_memory_repair_checkpoint(
            "logic_repair",
            final_text,
            self._chapter_ai_memory_pending["bundle"],
            logic_issues=issues,
            repair_attempt=attempts,
            status="pending",
        )
        self._log_novel_diagnostic(
            "chapter_logic_repair_started",
            level="warning",
            action="logic_repair",
            repair_attempt=attempts,
            issue_count=len(issues),
            issue_categories=[str(item.get("category", "") or "") for item in issues],
            final_text_chars=len(str(final_text or "").strip()),
            final_text_sha256=self._chapter_ai_checkpoint_hash(final_text),
        )
        context = _build_chapter_logic_repair_context(
            self._ai_project_snapshot(),
            self.current_chapter_index,
            final_text,
            issues,
        )
        self.chapter_ai_preview.setPlainText(str(final_text or "").strip())
        self.chapter_ai_stream_text = ""
        worker_kwargs = {"transient_retry": True} if transient_retry else {}
        self._start_chapter_ai_worker(
            "logic_repair",
            context,
            f"终稿审查发现{len(issues)}处有原文证据的逻辑矛盾，"
            f"正在局部修复（阶段重试预算 {_CHAPTER_AI_MAX_RETRIES} 次）...",
            **worker_kwargs,
        )

    def _handle_chapter_logic_repair_ready(self, content):
        pending = getattr(self, "_chapter_ai_memory_pending", {})
        if not isinstance(pending, dict) or pending.get("chapter_id") != self._current_chapter_id():
            self._fail_memory_sync("章节已切换，局部逻辑修复结果未应用")
            return
        final_text = str(pending.get("final_text", "") or "").strip()
        issues = pending.get("logic_issues", [])
        issues = issues if isinstance(issues, list) else []
        parsed = _parse_chapter_logic_repair_result(content)
        repaired_text, errors = _apply_chapter_logic_repair_patches(
            final_text,
            issues,
            parsed.get("patches", []) if parsed.get("parsed") else [],
        )
        if not parsed.get("parsed"):
            errors.insert(0, "局部逻辑修复结果无法解析")
        if errors:
            if self._schedule_transient_chapter_ai_retry(
                "logic_repair",
                "；".join(errors),
                force_retry=True,
                retry_callback=lambda tab: tab._start_chapter_logic_repair(
                    final_text,
                    pending.get("bundle", {}),
                    issues,
                    transient_retry=True,
                ),
            ):
                return
            self._fail_memory_sync("；".join(errors))
            return
        self._log_novel_diagnostic(
            "chapter_logic_repair_applied",
            action="logic_repair",
            repair_attempt=int(getattr(self, "_chapter_ai_logic_repair_attempts", 0) or 0),
            issue_count=len(issues),
            before_sha256=self._chapter_ai_checkpoint_hash(final_text),
            after_sha256=self._chapter_ai_checkpoint_hash(repaired_text),
            before_chars=len(final_text),
            after_chars=len(repaired_text),
        )
        self.chapter_ai_preview.setPlainText(repaired_text)
        self._clear_transient_chapter_ai_retry("logic_repair")
        self._start_memory_finalize(repaired_text)

    def _fail_memory_sync(self, message):
        pending = getattr(self, "_chapter_ai_memory_pending", {})
        pending = pending if isinstance(pending, dict) else {}
        pending_path = self._canonical_project_path(pending.get("project_path", ""))
        current_path = self._canonical_project_path(
            getattr(self, "current_project_path", "")
        )
        pending_chapter_id = str(pending.get("chapter_id", "") or "")
        pending_generation = int(pending.get("task_generation", 0) or 0)
        if pending and (
            (pending_path and pending_path != current_path)
            or (pending_chapter_id and pending_chapter_id != self._current_chapter_id())
            or (
                pending_generation
                and pending_generation
                != int(getattr(self, "_chapter_ai_task_generation", 0) or 0)
            )
        ):
            self._log_novel_diagnostic(
                "chapter_ai_stale_failure_discarded",
                level="warning",
                action="memory_sync",
                request_id=str(pending.get("request_id", "") or ""),
                reason=str(message or "")[:500],
                pending_project_path=pending_path,
                current_project_path=current_path,
                pending_chapter_id=pending_chapter_id,
                current_chapter_id=self._current_chapter_id(),
                pending_task_generation=pending_generation,
                current_task_generation=int(
                    getattr(self, "_chapter_ai_task_generation", 0) or 0
                ),
            )
            return
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if 0 <= self.current_chapter_index < len(chapters) and isinstance(chapters[self.current_chapter_index], dict):
            chapters[self.current_chapter_index]["memory_sync_status"] = "failed"
            chapters[self.current_chapter_index]["memory_sync_error"] = str(message or "")[:1000]
        final_text = str(pending.get("final_text", "") or "").strip()
        transaction_id = str(
            pending.get("transaction_id", "")
            if isinstance(pending, dict) else ""
        )
        failure_action = str(getattr(self, "_chapter_ai_running_action", "") or "")
        repair_stage = ""
        if failure_action == "logic_repair" or pending.get("logic_issues"):
            repair_stage = "logic_repair"
        elif failure_action == "memory_repair":
            repair_stage = "memory_repair"
        if final_text:
            self.chapter_ai_preview.setPlainText(final_text)
            if repair_stage:
                self._store_memory_repair_checkpoint(
                    repair_stage,
                    final_text,
                    pending.get("bundle", {}) if isinstance(pending, dict) else {},
                    validation_errors=pending.get("errors", []) if isinstance(pending, dict) else [],
                    logic_issues=pending.get("logic_issues", []) if isinstance(pending, dict) else [],
                    repair_attempt=(
                        getattr(self, "_chapter_ai_logic_repair_attempts", 0)
                        if repair_stage == "logic_repair" else
                        getattr(self, "_chapter_ai_memory_repair_attempts", 0)
                    ),
                    status="failed",
                    error=str(message or ""),
                )
            else:
                self._store_memory_finalize_checkpoint(
                    final_text,
                    status="failed",
                    error=str(message or ""),
                )
        request_id = str(getattr(self, "_chapter_ai_diagnostic_request_id", "") or "")
        validation_payload = ""
        try:
            validation_payload = json.dumps({
                "message": str(message or ""),
                "pending_errors": pending.get("errors", []) if isinstance(pending, dict) else [],
                "bundle": pending.get("bundle", {}) if isinstance(pending, dict) else {},
            }, ensure_ascii=False, default=str)
        except Exception:
            validation_payload = str(message or "")
        snapshot_path = self._save_chapter_ai_failure_snapshot(
            "memory_sync",
            request_id,
            error=str(message or ""),
            validation_payload=validation_payload,
        )
        self._log_novel_diagnostic(
            "memory_sync_failed",
            level="error",
            action="memory_sync",
            request_id=request_id,
            error=clean_error_text(message),
            error_category="memory_state",
            transaction_id=transaction_id,
            repair_attempts=int(getattr(self, "_chapter_ai_memory_repair_attempts", 0) or 0),
            final_text_chars=len(final_text),
            final_text_sha256=self._chapter_ai_checkpoint_hash(final_text) if final_text else "",
            repair_targets=self._novel_memory_repair_targets(
                pending.get("errors", []) if isinstance(pending, dict) else []
            ),
            bundle_summary=self._novel_memory_bundle_summary(
                pending.get("bundle", {}) if isinstance(pending, dict) else {}
            ),
            state_before=self._novel_memory_state_summary(),
            checkpoint_summary={
                "present": bool(final_text),
                "chars": len(final_text),
                "sha256": self._chapter_ai_checkpoint_hash(final_text) if final_text else "",
                "status": str(
                    chapters[self.current_chapter_index].get("ai_generation_checkpoint", {}).get("status", "")
                    if 0 <= self.current_chapter_index < len(chapters)
                    and isinstance(chapters[self.current_chapter_index], dict)
                    and isinstance(chapters[self.current_chapter_index].get("ai_generation_checkpoint"), dict)
                    else ""
                ),
            },
            diagnostic_snapshot_path=snapshot_path,
        )
        self._chapter_ai_style_workflow_active = False
        self._set_partial_chapter_ai_preview_state(False)
        self._reset_chapter_ai_sequence()
        if getattr(self, "_auto_expand_all_active", False):
            self._stop_auto_expand_all(
                f"自动扩写已停止：第{self.current_chapter_index + 1}章正文完成，但状态同步失败。"
            )
        resume_action_text = {
            "memory_repair": "重新启动时会继续状态修复。",
            "logic_repair": "重新启动时会继续正文逻辑修复。",
        }.get(repair_stage, "重新启动时会继续整理状态。")
        self.set_status_tip(
            "正文终稿未写入章节：状态同步失败，已保留后台恢复检查点；"
            + resume_action_text
            + f"{str(message or '')[:120]}"
        )

    def _handle_memory_repair_ready(self, content):
        pending = getattr(self, "_chapter_ai_memory_pending", {})
        if not isinstance(pending, dict) or pending.get("chapter_id") != self._current_chapter_id():
            self._fail_memory_sync("章节已切换，修复结果未应用")
            return
        parsed = _parse_memory_repair_result(content)
        bundle = deepcopy(pending.get("bundle", {})) if isinstance(pending.get("bundle"), dict) else {}
        final_text = str(pending.get("final_text", "") or "").strip()
        transaction_id = str(pending.get("transaction_id", "") or "")
        self._log_novel_diagnostic(
            "memory_repair_output_parsed",
            action="memory_repair",
            transaction_id=transaction_id,
            parsed=bool(parsed.get("parsed")),
            output_chars=len(str(content or "")),
            output_sha256=self._chapter_ai_checkpoint_hash(content),
            bundle_summary=self._novel_memory_bundle_summary(bundle),
        )
        if not parsed.get("parsed"):
            retry_errors = [
                str(item) for item in pending.get("errors", []) if str(item or "").strip()
            ]
            if "状态修复结果无法解析（JSON格式错误）" not in retry_errors:
                retry_errors.insert(0, "状态修复结果无法解析（JSON格式错误）")
            if self._schedule_transient_chapter_ai_retry(
                "memory_repair",
                "状态修复结果无法解析（JSON格式错误）",
                force_retry=True,
                retry_callback=lambda tab: tab._start_memory_repair(
                    final_text,
                    bundle,
                    retry_errors,
                    transient_retry=True,
                ),
            ):
                return
            self._fail_memory_sync("状态修复结果无法解析（JSON格式错误）")
            return
        for key in ("outline", "summary", "key_facts"):
            value = str(parsed.get(key, "") or "").strip()
            if value:
                bundle[key] = value
        if isinstance(parsed.get("logic_audit"), dict) and parsed.get("logic_audit"):
            bundle["logic_audit"] = deepcopy(parsed.get("logic_audit", {}))
        if parsed.get("repair_mode") == "patch":
            bundle["memory_update"] = _merge_long_form_memory_repair_patch(
                bundle.get("memory_update", {}),
                parsed.get("memory_patch", {}),
            )
        elif parsed.get("parsed") and isinstance(parsed.get("memory_update"), dict):
            bundle["memory_update"] = _merge_long_form_memory_repair_full(
                bundle.get("memory_update", {}),
                parsed.get("memory_update", {}),
                pending.get("errors", []),
            )
        audit_errors = []
        if pending.get("logic_audit_required"):
            audit_errors.extend(_chapter_logic_audit_validation_errors(
                final_text, bundle.get("logic_audit", {})
            ))
        bundle_errors = self._memory_bundle_validation_errors(final_text, bundle)
        validation_errors = list(dict.fromkeys(audit_errors + bundle_errors))
        if validation_errors:
            self._log_novel_diagnostic(
                "memory_repair_validation_collected",
                level="warning",
                action="memory_repair",
                transaction_id=transaction_id,
                validation_error_count=len(validation_errors),
                validation_errors=validation_errors,
                repair_targets=self._novel_memory_repair_targets(validation_errors),
                audit_error_count=len(audit_errors),
                bundle_error_count=len(bundle_errors),
            )
            if self._schedule_transient_chapter_ai_retry(
                "memory_repair",
                "；".join(validation_errors),
                force_retry=True,
                retry_callback=lambda tab: tab._start_memory_repair(
                    final_text,
                    bundle,
                    validation_errors,
                    transient_retry=True,
                ),
            ):
                return
            self._fail_memory_sync("；".join(validation_errors))
            return
        logic_issues = (
            _chapter_logic_audit_blocking_issues(bundle.get("logic_audit", {}))
            if pending.get("logic_audit_required") else []
        )
        if logic_issues:
            self._clear_transient_chapter_ai_retry("memory_repair")
            self._start_chapter_logic_repair(final_text, bundle, logic_issues)
            return
        # A repair response is still a memory-finalize result. At a ten-chapter
        # boundary it must pass the same reconciliation gate as the first
        # response; otherwise a repaired bundle can commit while the boundary
        # remains pending without a resumable checkpoint.
        if (
            (self.current_chapter_index + 1) % 10 == 0
            and not pending.get("reconciliation_started")
        ):
            self._clear_transient_chapter_ai_retry("memory_repair")
            self._start_memory_reconciliation(final_text, bundle)
            return
        self._clear_transient_chapter_ai_retry("memory_repair")
        self._chapter_ai_memory_pending = {}
        self.chapter_ai_preview.setPlainText(final_text)
        self._apply_style_final_result(final_text, bundle, memory_validated=True)

    def _prepare_staged_memory_commit(self, final_text, bundle):
        """Build the complete chapter update without mutating the live project."""
        if not isinstance(getattr(self, "current_project", None), dict):
            return None, False, "", "", "", ""
        raw_chapter_index = getattr(self, "current_chapter_index", -1)
        chapter_index = int(raw_chapter_index if raw_chapter_index is not None else -1)
        chapters = self.current_project.get("chapters", [])
        if not isinstance(chapters, list) or not (0 <= chapter_index < len(chapters)):
            return None, False, "", "", "", ""
        staged_project = deepcopy(self.current_project)
        staged_chapter = staged_project.get("chapters", [])[chapter_index]
        old_text = str(
            self.chapter_text.toPlainText()
            if hasattr(self, "chapter_text") else staged_chapter.get("text", "")
        ).strip()
        final_text = str(final_text or "").strip()
        new_text = _append_text_without_duplicate_overlap(old_text, final_text)
        memory_update = bundle.get("memory_update", {}) if isinstance(bundle, dict) else {}
        memory_changed = _apply_long_form_memory_update(
            staged_project,
            chapter_index,
            memory_update,
            final_text=new_text or old_text,
        )
        if not memory_changed:
            return None, False, "", "", "", ""
        staged_chapter["text"] = new_text
        bundle = bundle if isinstance(bundle, dict) else {}
        outline = str(bundle.get("outline", "") or "").strip()
        summary = str(bundle.get("summary", "") or "").strip()
        key_facts = str(bundle.get("key_facts", "") or "").strip()
        if outline and not str(
            getattr(self, "_chapter_ai_sequence_started_outline", "") or ""
        ).strip():
            staged_chapter["outline"] = outline
        if summary:
            staged_chapter["summary"] = summary
        if key_facts:
            staged_chapter["key_facts"] = key_facts
        return staged_project, True, new_text, outline, summary, key_facts

    def _start_chapter_ai_worker(
        self, action, context, status_text="", resume_prefix="", transient_retry=False
    ):
        self.set_chapter_ai_panel_expanded(True)
        self._status_begin_workflow("chapter_ai")
        chapter_id = self._current_chapter_id()
        raw_chapter_index = getattr(self, "current_chapter_index", -1)
        chapter_index = int(raw_chapter_index if raw_chapter_index is not None else -1)
        project_path = self._canonical_project_path(
            getattr(self, "current_project_path", "")
        )
        request_id = self._next_novel_diagnostic_request_id("chapter-ai")
        self._chapter_ai_task_generation = int(
            getattr(self, "_chapter_ai_task_generation", 0) or 0
        ) + 1
        task_generation = int(self._chapter_ai_task_generation)
        diagnostic_started_at = time.perf_counter()
        self._chapter_ai_diagnostic_request_id = request_id
        self._chapter_ai_diagnostic_started_at = diagnostic_started_at
        chapter = {}
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict):
            chapter = chapters[chapter_index]
        active_task = {
            "project_path": project_path,
            "chapter_id": chapter_id,
            "chapter_index": chapter_index,
            "action": str(action or ""),
            "request_id": request_id,
            "task_generation": task_generation,
            "source_text_sha256": hashlib.sha256(
                str(chapter.get("text", "") or "").encode("utf-8", errors="replace")
            ).hexdigest(),
            "outline_sha256": hashlib.sha256(
                str(chapter.get("outline", "") or "").encode("utf-8", errors="replace")
            ).hexdigest(),
            "base_memory_revision": int(
                (self.current_project.get("long_form_memory", {}) or {}).get(
                    "revision", 0
                ) or 0
            ) if isinstance(self.current_project, dict) and isinstance(
                self.current_project.get("long_form_memory", {}), dict
            ) else 0,
        }
        self._chapter_ai_active_task = active_task
        pending = getattr(self, "_chapter_ai_memory_pending", {})
        if isinstance(pending, dict) and pending:
            pending.update(
                {
                    "project_path": project_path,
                    "chapter_index": chapter_index,
                    "request_id": request_id,
                    "task_generation": task_generation,
                    "source_text_sha256": active_task["source_text_sha256"],
                    "outline_sha256": active_task["outline_sha256"],
                    "base_memory_revision": active_task["base_memory_revision"],
                }
            )
            self._chapter_ai_memory_pending = pending
        if not transient_retry:
            retry_counts = getattr(self, "_chapter_ai_transient_retry_counts", None)
            if isinstance(retry_counts, dict):
                retry_key = f"{chapter_id}:{action}"
                for key in list(retry_counts):
                    if key == retry_key or key.startswith(retry_key + ":"):
                        retry_counts.pop(key, None)
            self._chapter_ai_transient_retry_pending = False
            self._chapter_ai_transient_retry_token = int(
                getattr(self, "_chapter_ai_transient_retry_token", 0) or 0
            ) + 1
        self.chapter_ai_stream_text = str(resume_prefix or "").strip()
        self._chapter_ai_resume_prefix = str(resume_prefix or "").strip() if action == "draft" else ""
        if status_text:
            self.set_status_tip(status_text)
        if action == "draft":
            self._chapter_ai_last_context = str(context or "")
        self._chapter_ai_running_action = action
        self._chapter_ai_running_context = str(context or "")
        self._chapter_ai_running_chapter_id = chapter_id
        self._retain_previous_writing_worker()
        try:
            self.writing_worker = NovelWritingWorker(
                self._chapter_ai_provider.get("base_url", ""),
                self._chapter_ai_provider.get("api_key", ""),
                self._chapter_ai_model,
                action,
                context,
                self._chapter_ai_provider.get("proxy_url", ""),
                self._provider_proxy_mode(self._chapter_ai_provider),
            )
        except Exception as exc:
            error_details = self._novel_exception_details(exc)
            snapshot_path = self._save_chapter_ai_failure_snapshot(
                action,
                request_id,
                error=error_details["error"],
                validation_payload=error_details["traceback"],
            )
            self._log_novel_diagnostic(
                "chapter_ai_worker_create_failed",
                level="error",
                action=action,
                chapter_id=chapter_id,
                request_id=request_id,
                diagnostic_snapshot_path=snapshot_path,
                error_category=self._novel_diagnostic_error_category(exc),
                **error_details,
            )
            retry_scheduled = False
            if (
                getattr(self, "_chapter_ai_sequence_active", False)
                or getattr(self, "_auto_expand_all_active", False)
            ):
                retry_scheduled = self._schedule_transient_chapter_ai_retry(
                    action,
                    error_details["error"],
                    force_retry=True,
                )
            if not retry_scheduled:
                raise
            return
        self.writing_worker.diagnostic_request_id = request_id
        self.writing_worker.diagnostic_started_at = diagnostic_started_at
        self.writing_worker.diagnostic_project_path = project_path
        self.writing_worker.diagnostic_chapter_id = chapter_id
        self.writing_worker.diagnostic_chapter_index = chapter_index
        self.writing_worker.diagnostic_task_generation = task_generation
        self.writing_worker.diagnostic_task_context = deepcopy(active_task)
        if isinstance(getattr(self.writing_worker, "diagnostics", None), dict):
            self.writing_worker.diagnostics.update(
                {
                    "project_path": project_path,
                    "chapter_id": chapter_id,
                    "chapter_index": chapter_index,
                    "task_generation": task_generation,
                }
            )
        self._connect_chapter_task_worker(
            self.writing_worker, "on_chapter_ai_ready", "_cleanup_writing_worker"
        )
        self._chapter_ai_stop_requested_by_user = False
        if not transient_retry or not str(getattr(self, "_chapter_ai_running_status_text", "") or ""):
            self._chapter_ai_running_status_text = str(status_text or "")
        context_text = str(context or "")
        sent_context = context_text[:NOVEL_AI_CONTEXT_LIMIT]
        retry_counts = getattr(self, "_chapter_ai_transient_retry_counts", {})
        retry_attempt = int(retry_counts.get(f"{chapter_id}:{action}", 0) or 0) if isinstance(retry_counts, dict) else 0
        self._log_novel_diagnostic(
            "chapter_ai_request_started",
            action=action,
            chapter_id=chapter_id,
            request_id=request_id,
            project_path=project_path,
            task_generation=task_generation,
            transient_retry=bool(transient_retry),
            retry_attempt=retry_attempt,
            context_chars=len(context_text),
            context_utf8_bytes=len(context_text.encode("utf-8", errors="replace")),
            sent_context_chars=len(sent_context),
            sent_context_utf8_bytes=len(sent_context.encode("utf-8", errors="replace")),
            context_limit=NOVEL_AI_CONTEXT_LIMIT,
            context_truncated=len(context_text) > NOVEL_AI_CONTEXT_LIMIT,
            context_fill_percent=round(
                min(100.0, len(sent_context) * 100.0 / max(1, NOVEL_AI_CONTEXT_LIMIT)), 2
            ),
            context_sha256=hashlib.sha256(
                context_text.encode("utf-8", errors="replace")
            ).hexdigest(),
            sent_context_sha256=hashlib.sha256(
                sent_context.encode("utf-8", errors="replace")
            ).hexdigest(),
            context_sections=self._novel_context_section_metrics(context_text),
            resume_prefix_chars=len(str(resume_prefix or "")),
            max_output_tokens=int(
                getattr(self.writing_worker, "diagnostics", {}).get("max_output_tokens", 0) or 0
            ),
        )
        self._set_chapter_ai_actions_enabled(False)
        try:
            self.writing_worker.start()
        except Exception as exc:
            error_details = self._novel_exception_details(exc)
            snapshot_path = self._save_chapter_ai_failure_snapshot(
                action,
                request_id,
                error=error_details["error"],
                worker_diagnostics=getattr(self.writing_worker, "diagnostics", {}),
                validation_payload=error_details["traceback"],
            )
            self._log_novel_diagnostic(
                "chapter_ai_worker_start_failed",
                level="error",
                action=action,
                chapter_id=chapter_id,
                request_id=request_id,
                diagnostic_snapshot_path=snapshot_path,
                error_category=self._novel_diagnostic_error_category(exc),
                **error_details,
            )
            retry_scheduled = False
            if (
                getattr(self, "_chapter_ai_sequence_active", False)
                or getattr(self, "_auto_expand_all_active", False)
            ):
                retry_scheduled = self._schedule_transient_chapter_ai_retry(
                    action,
                    error_details["error"],
                    force_retry=True,
                )
            if not retry_scheduled:
                raise

    @staticmethod
    def _is_transient_chapter_ai_error(err):
        text = clean_error_text(err).lower()
        transient_markers = (
            "upstream request failed",
            "upstream service temporarily unavailable",
            "service temporarily unavailable",
            "concurrency limit exceeded",
            "rate limit",
            "too many requests",
            "timeout",
            "timed out",
            "connection reset",
            "connection aborted",
            "connection broken",
            "remote end closed",
            "ssl eof",
            "ssleoferror",
            "eof occurred in violation of protocol",
            "max retries exceeded",
            "response ended prematurely",
            "response stream was interrupted",
            "stream was interrupted",
            "未完整结束",
            "正文交付边界不完整",
            "剧情执行稿结构不完整",
            "没有返回有效内容",
            "输出异常膨胀",
            "接口错误 429",
            "接口错误 500",
            "接口错误 502",
            "接口错误 503",
            "接口错误 504",
            "接口错误 524",
        )
        return any(marker in text for marker in transient_markers)

    @staticmethod
    def _transient_chapter_ai_retry_delay(attempt, err=""):
        """Return the shared chapter-workflow retry delay in seconds."""
        del err
        attempt = max(1, int(attempt or 1))
        index = min(attempt, len(_CHAPTER_AI_RETRY_DELAYS)) - 1
        return int(_CHAPTER_AI_RETRY_DELAYS[index])

    def _schedule_transient_chapter_ai_retry(
        self,
        action,
        err,
        *,
        force_retry=False,
        retry_context="",
        retry_chapter_id="",
        retry_callback=None,
    ):
        """Schedule one bounded retry for an automatic chapter workflow stage.

        The same stage budget is used for transport failures and for a response
        that cannot be accepted (empty output, malformed JSON, missing fields,
        or failed validation).  Callers may provide a callback for stages that
        are assembled outside ``NovelWritingWorker`` such as context building
        or a repair response that needs a refreshed prompt.
        """
        if not force_retry and not self._is_transient_chapter_ai_error(err):
            return False
        if getattr(self, "_chapter_ai_stop_requested_by_user", False):
            return False
        action = str(action or "").strip()
        stage = str(retry_context or action or "").strip()
        context = str(
            retry_context if retry_context and retry_context not in _CHAPTER_AI_RETRY_STAGES
            else getattr(self, "_chapter_ai_running_context", "")
        )
        chapter_id = str(
            retry_chapter_id
            or getattr(self, "_chapter_ai_running_chapter_id", "")
            or self._current_chapter_id()
            or ""
        )
        if stage not in _CHAPTER_AI_RETRY_STAGES:
            return False
        if not callable(retry_callback) and (not action or not context or not chapter_id):
            return False
        if callable(retry_callback) and not chapter_id:
            return False
        retry_counts = getattr(self, "_chapter_ai_transient_retry_counts", None)
        if not isinstance(retry_counts, dict):
            retry_counts = {}
            self._chapter_ai_transient_retry_counts = retry_counts
        retry_key = f"{chapter_id}:{stage}"
        attempt = int(retry_counts.get(retry_key, 0) or 0) + 1
        max_retries = _CHAPTER_AI_MAX_RETRIES
        if attempt > max_retries:
            return False
        retry_counts[retry_key] = attempt
        delay_seconds = self._transient_chapter_ai_retry_delay(attempt, err)
        status_text = str(getattr(self, "_chapter_ai_running_status_text", "") or "")
        self._chapter_ai_transient_retry_pending = True
        token = int(getattr(self, "_chapter_ai_transient_retry_token", 0) or 0) + 1
        self._chapter_ai_transient_retry_token = token
        self.set_status_tip(
            f"当前步骤未通过，已丢弃本次结果；{delay_seconds} 秒后自动重试"
            f"（{attempt}/{max_retries}）..."
        )

        def retry(tab):
            if token != int(getattr(tab, "_chapter_ai_transient_retry_token", 0) or 0):
                return
            if not getattr(tab, "_chapter_ai_transient_retry_pending", False):
                return
            if getattr(tab, "_chapter_ai_stop_requested_by_user", False):
                tab._chapter_ai_transient_retry_pending = False
                return
            if tab._current_chapter_id() != chapter_id:
                tab._chapter_ai_transient_retry_pending = False
                for key in list(tab._chapter_ai_transient_retry_counts):
                    if key == retry_key or key.startswith(retry_key + ":"):
                        tab._chapter_ai_transient_retry_counts.pop(key, None)
                tab._reset_chapter_ai_sequence()
                tab.set_status_tip("章节已切换，已取消上一个章节的自动重试。")
                tab._set_chapter_ai_actions_enabled(True)
                return
            if (
                not callable(retry_callback)
                and action.startswith("style_")
                and not getattr(tab, "_chapter_ai_style_workflow_active", False)
            ):
                tab._chapter_ai_transient_retry_pending = False
                return
            worker = getattr(tab, "writing_worker", None)
            if worker is not None and worker.isRunning():
                tab._schedule_chapter_task_callback(500, retry)
                return
            tab._chapter_ai_transient_retry_pending = False
            if callable(retry_callback):
                retry_callback(tab)
            else:
                tab._start_chapter_ai_worker(
                    action,
                    context,
                    f"正在自动重试当前步骤（{attempt}/{max_retries}）..." if not status_text else
                    f"{status_text.rstrip('。.')}，自动重试 {attempt}/{max_retries}...",
                    transient_retry=True,
                )

        self._schedule_chapter_task_callback(delay_seconds * 1000, retry)
        self._log_novel_diagnostic(
            "chapter_ai_retry_scheduled",
            level="warning",
            action=action,
            retry_stage=stage,
            chapter_id=chapter_id,
            request_id=str(getattr(self, "_chapter_ai_diagnostic_request_id", "") or ""),
            retry_attempt=attempt,
            max_retries=max_retries,
            delay_seconds=delay_seconds,
            error=clean_error_text(err),
            error_category=self._novel_diagnostic_error_category(err),
        )
        return True

    def _clear_transient_chapter_ai_retry(self, action, chapter_id="", stage=""):
        chapter_id = str(
            chapter_id or getattr(self, "_chapter_ai_running_chapter_id", "") or ""
        )
        retry_counts = getattr(self, "_chapter_ai_transient_retry_counts", None)
        if isinstance(retry_counts, dict) and chapter_id and action:
            retry_key = f"{chapter_id}:{stage or action}"
            for key in list(retry_counts):
                if key == retry_key:
                    retry_counts.pop(key, None)
        self._chapter_ai_transient_retry_pending = False
        self._chapter_ai_transient_retry_token = int(
            getattr(self, "_chapter_ai_transient_retry_token", 0) or 0
        ) + 1

    def _retain_previous_writing_worker(self):
        worker = getattr(self, "writing_worker", None)
        if worker is None:
            return
        retired = getattr(self, "writing_retired_workers", None)
        if not isinstance(retired, list):
            retired = []
            self.writing_retired_workers = retired
        if worker not in retired:
            retired.append(worker)
        self.writing_worker = None

    def _start_chapter_ai_sequence(self):
        if self.current_chapter_index < 0:
            self._set_chapter_ai_actions_enabled(True)
            self._show_chapter_ai_failure("请先选择一个章节。")
            return
        if (
            getattr(self, "_auto_expand_all_active", False)
            and isinstance(getattr(self, "_chapter_ai_provider", None), dict)
            and getattr(self, "_chapter_ai_provider", None)
            and str(getattr(self, "_chapter_ai_model", "") or "").strip()
        ):
            provider = self._chapter_ai_provider
            model = self._chapter_ai_model
            error = ""
        else:
            provider, model, error = self._current_novel_ai_selection()
        if error:
            self._set_chapter_ai_actions_enabled(True)
            self.set_ai_settings_expanded(True)
            self.set_status_tip(f"AI 写作失败：{error}")
            self._show_chapter_ai_failure(error)
            return
        if hasattr(self, "_loading"):
            self._flush_current_editors()
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        chapter = (
            chapters[self.current_chapter_index]
            if 0 <= self.current_chapter_index < len(chapters)
            and isinstance(chapters[self.current_chapter_index], dict)
            else {}
        )
        force_rewrite = bool(getattr(self, "_chapter_ai_force_rewrite", False))
        self._chapter_ai_force_rewrite = False
        reconciliation_checkpoint = self._validated_memory_reconciliation_checkpoint()
        if reconciliation_checkpoint:
            self._chapter_ai_provider = provider
            self._chapter_ai_model = model
            self._reset_chapter_ai_sequence()
            self._reset_chapter_ai_style_retry()
            self._chapter_ai_sequence_active = True
            self._chapter_ai_sequence_chapter_id = self._current_chapter_id()
            self._chapter_ai_sequence_started_outline = self.chapter_outline.toPlainText().strip()
            self._set_partial_chapter_ai_preview_state(False)
            self._chapter_ai_resume_prefix = ""
            final_text = str(reconciliation_checkpoint.get("final_text", "") or "").strip()
            bundle = deepcopy(reconciliation_checkpoint.get("bundle", {}))
            self._chapter_ai_memory_transaction_id = str(
                reconciliation_checkpoint.get("transaction_id", "")
                or self._next_novel_diagnostic_request_id("memory-sync")
            )
            self._chapter_ai_memory_pending = {
                "chapter_id": self._current_chapter_id(),
                "transaction_id": self._chapter_ai_memory_transaction_id,
                "final_text": final_text,
                "bundle": bundle,
                "errors": [],
                "logic_audit_required": False,
                "reconciliation_started": False,
                "resumed_reconciliation": True,
                "already_committed": bool(
                    reconciliation_checkpoint.get("already_committed", False)
                ),
            }
            self._mark_current_chapter_ai_sync_pending(chapter)
            self._chapter_ai_style_workflow_active = True
            self.chapter_ai_preview.setPlainText(final_text)
            self._start_memory_reconciliation(final_text, bundle, resumed=True)
            return
        repair_checkpoint = self._validated_memory_repair_checkpoint()
        if repair_checkpoint:
            self._chapter_ai_provider = provider
            self._chapter_ai_model = model
            self._reset_chapter_ai_sequence()
            self._reset_chapter_ai_style_retry()
            self._chapter_ai_sequence_active = True
            self._chapter_ai_sequence_chapter_id = self._current_chapter_id()
            self._chapter_ai_sequence_started_outline = self.chapter_outline.toPlainText().strip()
            self._set_partial_chapter_ai_preview_state(False)
            self._chapter_ai_resume_prefix = ""
            self.chapter_ai_stream_text = ""
            final_text = str(repair_checkpoint.get("final_text", "") or "").strip()
            bundle = deepcopy(repair_checkpoint.get("bundle", {}))
            stage = str(repair_checkpoint.get("stage", "") or "")
            self._chapter_ai_memory_transaction_id = str(
                repair_checkpoint.get("transaction_id", "")
                or self._next_novel_diagnostic_request_id("memory-sync")
            )
            self._chapter_ai_memory_pending = {
                "chapter_id": self._current_chapter_id(),
                "transaction_id": self._chapter_ai_memory_transaction_id,
                "final_text": final_text,
                "bundle": bundle,
                "errors": [
                    str(item) for item in repair_checkpoint.get("validation_errors", [])
                    if str(item or "").strip()
                ],
                "logic_audit_required": bool(
                    repair_checkpoint.get("logic_audit_required", stage == "logic_repair")
                ),
                "logic_issues": [
                    deepcopy(item) for item in repair_checkpoint.get("logic_issues", [])
                    if isinstance(item, dict)
                ],
                "resumed_repair": True,
            }
            self._mark_current_chapter_ai_sync_pending(chapter)
            self._chapter_ai_style_workflow_active = True
            self.chapter_ai_preview.setPlainText(final_text)
            try:
                stored_attempt = int(repair_checkpoint.get("repair_attempt", 0) or 0)
            except (TypeError, ValueError):
                stored_attempt = 0
            if stage == "memory_repair":
                # Retry the failed request in the same logical repair slot; do
                # not reset the validation budget or create an automatic loop.
                resume_attempt = stored_attempt if 0 < stored_attempt <= _CHAPTER_AI_MAX_RETRIES else 0
                self._chapter_ai_memory_repair_attempts = max(0, resume_attempt - 1)
                self._start_memory_repair(
                    final_text,
                    bundle,
                    self._chapter_ai_memory_pending["errors"],
                )
            else:
                # Resume the same three-retry stage budget after an explicit
                # user restart; do not silently create a separate allowance.
                resume_attempt = stored_attempt if 0 < stored_attempt <= _CHAPTER_AI_MAX_RETRIES else 0
                self._chapter_ai_logic_repair_attempts = max(0, resume_attempt - 1)
                self._start_chapter_logic_repair(
                    final_text,
                    bundle,
                    self._chapter_ai_memory_pending["logic_issues"],
                )
            return
        has_committed_marker = self._chapter_has_committed_memory_marker(chapter)
        if has_committed_marker:
            if self._auto_expand_chapter_has_committed_memory(chapter):
                message = "本章正文、摘要和长期状态已经完整提交，不能再次扩写，以免破坏后续章节记忆。"
                title = "本章已完成"
            else:
                message = (
                    "本章长期状态已经提交，但正文、摘要或关键事实被清空或改动，"
                    "当前记忆无法安全回滚，已停止扩写以避免破坏后续章节。"
                )
                title = "章节状态不完整"
            if getattr(self, "_auto_expand_all_active", False):
                self._stop_auto_expand_all(
                    f"自动扩写已停止：第{self.current_chapter_index + 1}章长期状态已提交，但章节资料不完整。"
                )
            else:
                self.set_status_tip(message)
                QMessageBox.information(self, title, message)
                self._set_chapter_ai_actions_enabled(True)
            return
        had_memory_checkpoint = bool(chapter.get("ai_generation_checkpoint"))
        checkpoint_stage = (
            str(chapter.get("ai_generation_checkpoint", {}).get("stage", "") or "")
            if isinstance(chapter.get("ai_generation_checkpoint"), dict) else ""
        )
        checkpoint_text = self._validated_memory_finalize_checkpoint()
        existing_body = str(chapter.get("text", "") or "").strip()
        rewrite_on_ready = False
        if had_memory_checkpoint and not checkpoint_text:
            self._clear_memory_finalize_checkpoint(persist=True)
            if checkpoint_stage in {"memory_repair", "logic_repair"}:
                # A stale repair package must not force a prose rewrite. The
                # current body is still usable; rebuild only its state data.
                had_memory_checkpoint = False
        # A validated memory checkpoint contains a complete, style-finalized
        # body. Resume only its state transaction. A body without a checkpoint
        # is user-authored (or already delivered) content and must go straight
        # to metadata and state finalization; only a stale/invalid checkpoint
        # is eligible for a clean rewrite.
        self._chapter_ai_provider = provider
        self._chapter_ai_model = model
        self._reset_chapter_ai_sequence()
        self._reset_chapter_ai_style_retry()
        self._chapter_ai_sequence_active = True
        self._chapter_ai_sequence_chapter_id = self._current_chapter_id()
        self._chapter_ai_sequence_started_outline = self.chapter_outline.toPlainText().strip()
        self._set_partial_chapter_ai_preview_state(False)
        self._chapter_ai_resume_prefix = ""
        self.chapter_ai_preview.setPlainText("")
        if checkpoint_text:
            self._mark_current_chapter_ai_sync_pending(chapter)
            self._chapter_ai_style_workflow_active = True
            self._start_memory_finalize(checkpoint_text, resumed=True)
            return
        if existing_body and not had_memory_checkpoint and not force_rewrite:
            self._mark_current_chapter_ai_sync_pending(chapter)
            self._chapter_ai_style_workflow_active = True
            self._start_memory_finalize(
                existing_body,
                resumed=bool(getattr(self, "_auto_expand_all_active", False)),
            )
            return
        rewrite_on_ready = bool(had_memory_checkpoint or force_rewrite)
        context_snapshot = self._ai_project_snapshot()
        if rewrite_on_ready:
            snapshot_chapters = context_snapshot.get("chapters", [])
            if 0 <= self.current_chapter_index < len(snapshot_chapters):
                self._reset_chapter_data_for_ai_rewrite(snapshot_chapters[self.current_chapter_index])
        self._start_chapter_context_build(
            "draft",
            "style_draft",
            project_snapshot=context_snapshot,
            chapter_index=self.current_chapter_index,
            chapter_id=self._current_chapter_id(),
            rewrite_on_ready=rewrite_on_ready,
            status_text="正在后台组装本章资料...",
        )

    def run_chapter_ai_action(self, action):
        context_worker = getattr(self, "context_build_worker", None)
        if context_worker is not None and context_worker.isRunning():
            self.set_status_tip("正在组装当前章节资料，请稍等。")
            return
        if self.writing_worker is not None and self.writing_worker.isRunning():
            self.set_status_tip("AI 写作助手正在生成，请稍等。")
            return
        chapter_plan_worker = getattr(self, "chapter_plan_worker", None)
        if chapter_plan_worker is not None and chapter_plan_worker.isRunning():
            self.set_status_tip("章节规划正在生成，请稍等。")
            return
        if action == "draft":
            self._discard_partial_preview_for_auto_rewrite(source="single_chapter")
            if hasattr(self, "_is_detached_auto_runner") and not self._is_detached_auto_runner:
                self._start_detached_single_chapter_ai()
                return
            if hasattr(self, "context_build_worker"):
                self._set_chapter_ai_actions_enabled(False)
                self.set_status_tip("正在后台准备本章资料...")
                self._chapter_ai_sequence_active = True
                self._schedule_chapter_task_callback(
                    0, lambda tab: tab._start_chapter_ai_sequence()
                )
                return
            self._start_chapter_ai_sequence()
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self.set_ai_settings_expanded(True)
            self.set_status_tip(f"AI 写作失败：{error}")
            self._show_chapter_ai_failure(error)
            return
        self._chapter_ai_provider = provider
        self._chapter_ai_model = model
        self._start_chapter_context_build(
            action,
            "direct",
            chapter_index=self.current_chapter_index,
            chapter_id=self._current_chapter_id(),
            status_text="正在后台组装本章资料...",
        )

    def stop_chapter_ai_action(self):
        detached = self._current_background_chapter_runner()
        if detached is not None and not getattr(self, "_is_detached_auto_runner", False):
            local_writing = getattr(self, "writing_worker", None)
            local_context = getattr(self, "context_build_worker", None)
            local_plan = getattr(self, "chapter_plan_worker", None)
            local_active = any(
                worker is not None and worker.isRunning()
                for worker in (local_writing, local_context, local_plan)
            )
            if not local_active and detached._status_has_active_work():
                detached.stop_chapter_ai_action()
                self.set_status_tip("正在中止后台自动扩写...")
                return
        if getattr(self, "_auto_expand_all_active", False):
            completed = int(getattr(self, "_auto_expand_all_completed", 0) or 0)
            current, total = self._auto_expand_all_chapter_progress()
            position = f"停在第{current}章（{current}/{total}）" if current and total else "当前章节已停止"
            self._stop_auto_expand_all(f"自动扩写已中止：{position}，本轮已完成 {completed} 章。")
        worker = self.writing_worker
        context_worker = getattr(self, "context_build_worker", None)
        plan_worker = getattr(self, "chapter_plan_worker", None)
        if getattr(self, "_chapter_plan_auto_active", False):
            self._chapter_ai_stop_requested_by_user = True
            self._chapter_plan_auto_active = False
            self._chapter_plan_continue_pending = False
            self._chapter_plan_sequence_token = int(
                getattr(self, "_chapter_plan_sequence_token", 0) or 0
            ) + 1
            state = deepcopy(self.current_project.get("chapter_plan_generation_state", {}))
            if isinstance(state, dict) and state and state.get("status") != "complete":
                state["status"] = "interrupted"
                self._persist_chapter_plan_generation_state(state)
            if plan_worker is None or not plan_worker.isRunning():
                self._chapter_ai_stop_requested_by_user = False
                self._set_chapter_ai_actions_enabled(True)
                self.set_status_tip("章节规划生成已中止，已保存当前批次进度。")
                return
        if getattr(self, "_chapter_ai_transient_retry_pending", False):
            self._chapter_ai_stop_requested_by_user = True
            self._chapter_ai_transient_retry_pending = False
            self._chapter_ai_transient_retry_token = int(
                getattr(self, "_chapter_ai_transient_retry_token", 0) or 0
            ) + 1
            self._reset_chapter_ai_sequence()
            self._set_chapter_ai_actions_enabled(True)
            self.set_status_tip("AI 辅助生成已中止。")
            return
        if (
            (worker is None or not worker.isRunning())
            and (plan_worker is None or not plan_worker.isRunning())
            and (context_worker is None or not context_worker.isRunning())
        ):
            return
        self._chapter_ai_stop_requested_by_user = True
        self.set_status_tip("正在中止 AI 辅助生成...")
        try:
            if worker is not None and worker.isRunning():
                if hasattr(worker, "stop"):
                    worker.stop()
                else:
                    worker.requestInterruption()
            if plan_worker is not None and plan_worker.isRunning():
                if hasattr(plan_worker, "stop"):
                    plan_worker.stop()
                else:
                    plan_worker.requestInterruption()
            if context_worker is not None and context_worker.isRunning():
                self._context_build_token = int(getattr(self, "_context_build_token", 0) or 0) + 1
                self._context_build_pending = {}
                context_worker.requestInterruption()
                self._reset_chapter_ai_sequence()
                self._set_chapter_ai_actions_enabled(True)
        except Exception as e:
            log_debug("小说章节 AI 中止失败", e)

    def _chapter_ai_output_is_user_facing(self, action=None):
        action = str(action or getattr(self, "_chapter_ai_running_action", "") or "")
        if action in {
            "memory_finalize",
            "memory_reconcile",
            "memory_repair",
            "logic_repair",
            "style_profile",
            "style_baseline",
            "style_sheet",
            "style_sheet_merge",
            "style_persona",
            "style_cards",
            "style_rules",
            "style_finalize",
            "style_audit",
            "style_rewrite",
            "style_plot_extract",
        }:
            return False
        if action == "draft" and bool(getattr(self, "_chapter_ai_style_workflow_active", False)):
            return False
        return True

    def on_chapter_ai_chunk(self, piece):
        if self._forward_chapter_task_signal("on_chapter_ai_chunk", piece):
            return
        if not self._chapter_ai_callback_is_current():
            return
        piece = str(piece or "")
        if not piece:
            return
        self.chapter_ai_stream_text += piece
        if not self._chapter_ai_output_is_user_facing():
            return
        self.chapter_ai_preview.moveCursor(QTextCursor.End)
        self.chapter_ai_preview.insertPlainText(piece)
        bar = self.chapter_ai_preview.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _maybe_retry_draft_for_style(self, action, final_text):
        if action != "draft" or getattr(self, "_chapter_ai_style_retry_attempted", False):
            return False
        project = self._ai_project_snapshot()
        style_reference = str(project.get("style_reference", "") or "").strip()
        if not style_reference:
            return False
        original_context = str(getattr(self, "_chapter_ai_last_context", "") or "")
        output_target = _style_output_target_from_context(original_context)
        reasons = _style_draft_mismatch_reasons(style_reference, final_text, output_target)
        if not reasons or not original_context:
            return False
        repair_context = _build_style_rewrite_context(
            original_context,
            final_text,
            reasons,
            style_reference=style_reference,
            output_target=output_target,
        )
        self._chapter_ai_style_retry_attempted = True
        self._chapter_ai_style_fallback_text = str(final_text or "").strip()
        self._chapter_ai_resume_prefix = ""
        self.chapter_ai_stream_text = ""
        self.chapter_ai_preview.clear()
        self._start_chapter_ai_worker(
            "draft",
            repair_context,
            "首次正文与风格样本偏差较大，正在自动重写一次...",
        )
        return True

    def _select_style_final_text(self, initial, revised, bundle, validate_memory=True):
        initial = str(initial or "").strip()
        revised = str(revised or "").strip()
        selected = initial
        if revised and _style_candidate_rank(
            self._chapter_ai_style_reference, revised, self._chapter_ai_style_output_target
        ) <= _style_candidate_rank(
            self._chapter_ai_style_reference, initial, self._chapter_ai_style_output_target
        ):
            selected = revised
        if (
            validate_memory
            and selected == initial
            and revised
            and isinstance(getattr(self, "current_project", None), dict)
        ):
            initial_errors = self._memory_bundle_validation_errors(initial, bundle)
            if initial_errors and not self._memory_bundle_validation_errors(revised, bundle):
                selected = revised
        return selected

    def _apply_style_final_result(self, final_text, bundle, memory_validated=False):
        text = str(final_text or "").strip()
        if not text:
            self._reset_chapter_ai_sequence()
            self.set_status_tip("终稿编辑没有返回可用正文，已保留首次正文预览。")
            return
        if not memory_validated:
            errors = self._memory_bundle_validation_errors(text, bundle)
            if errors:
                self._start_memory_repair(text, bundle, errors)
                return
        pending = getattr(self, "_chapter_ai_memory_pending", {})
        pending = pending if isinstance(pending, dict) else {}
        transaction_id = str(
            pending.get("transaction_id", "")
            or getattr(self, "_chapter_ai_memory_transaction_id", "")
        )
        state_before = self._novel_memory_state_summary()
        self._log_novel_diagnostic(
            "memory_transaction_started",
            action="memory_sync",
            transaction_id=transaction_id,
            bundle_summary=self._novel_memory_bundle_summary(bundle),
            state_before=state_before,
        )
        (
            staged_project,
            memory_changed,
            new_text,
            outline,
            summary,
            key_facts,
        ) = self._prepare_staged_memory_commit(text, bundle)
        if not memory_changed:
            self._log_novel_diagnostic(
                "memory_transaction_failed",
                level="error",
                action="memory_sync",
                transaction_id=transaction_id,
                state_before=state_before,
                state_after=self._novel_memory_state_summary(),
                bundle_summary=self._novel_memory_bundle_summary(bundle),
            )
            self._fail_memory_sync("状态事务未能提交")
            return
        self.current_project = staged_project
        self._log_novel_diagnostic(
            "memory_transaction_committed",
            action="memory_sync",
            transaction_id=transaction_id,
            state_before=state_before,
            state_after=self._novel_memory_state_summary(),
            bundle_summary=self._novel_memory_bundle_summary(bundle),
        )
        self.chapter_text.setPlainText(new_text)
        if outline and not str(getattr(self, "_chapter_ai_sequence_started_outline", "") or "").strip():
            self.chapter_outline.setPlainText(outline)
        if summary:
            self.chapter_summary.setPlainText(summary)
        if key_facts:
            self.chapter_key_facts.setPlainText(key_facts)
        if memory_changed and isinstance(getattr(self, "current_project", None), dict):
            self._refresh_long_form_record_views()
            chapters = self.current_project.get("chapters", [])
            chapter = chapters[self.current_chapter_index] if 0 <= self.current_chapter_index < len(chapters) else {}
            self._set_line_text_without_signals(
                self.chapter_linked,
                ", ".join(_normalize_name_list(chapter.get("linked_characters", []))),
            )
        else:
            inferred_names = self._infer_current_chapter_linked_names(
                extra_text="\n".join([text, outline, summary, key_facts])
            )
            self._merge_chapter_linked_names(inferred_names)
        if memory_changed and hasattr(self, "chapter_status"):
            completed_index = self.chapter_status.findText("已完成")
            if completed_index >= 0:
                self.chapter_status.blockSignals(True)
                try:
                    self.chapter_status.setCurrentIndex(completed_index)
                finally:
                    self.chapter_status.blockSignals(False)
        self._clear_current_chapter_ai_resume_required()
        self._mark_chapter_dirty()
        if memory_changed and isinstance(getattr(self, "current_project", None), dict):
            self._mark_current_chapter_ai_result_analyzed()
        checkpoint_cleared = self._clear_memory_finalize_checkpoint()
        if memory_changed and hasattr(self, "_note_project_dirty"):
            self._note_project_dirty()
        if checkpoint_cleared:
            self._persist_ai_generation_state()
        self.chapter_ai_preview.clear()
        self._set_partial_chapter_ai_preview_state(False)
        self._chapter_ai_resume_prefix = ""
        self._chapter_ai_style_workflow_active = False
        self._reset_chapter_ai_sequence()
        self.set_chapter_ai_panel_expanded(False)
        if outline and summary and key_facts:
            self.set_status_tip("章节 AI 已完成：正文终稿、提纲、摘要和关键事实已自动更新。")
        else:
            self.set_status_tip("正文终稿已写入；终稿附带资料不完整，可单独补提纲或摘要。")
        self._on_auto_expand_chapter_completed(memory_changed)

    def _mark_current_chapter_ai_result_analyzed(self):
        chapters = self.current_project.get("chapters", []) if isinstance(self.current_project, dict) else []
        if not (0 <= self.current_chapter_index < len(chapters)):
            return False
        chapter = chapters[self.current_chapter_index]
        if not isinstance(chapter, dict):
            return False
        for field, attr_name in (
            ("outline", "chapter_outline"),
            ("text", "chapter_text"),
            ("summary", "chapter_summary"),
            ("key_facts", "chapter_key_facts"),
        ):
            editor = getattr(self, attr_name, None)
            if editor is not None:
                chapter[field] = editor.toPlainText().strip()
        linked_editor = getattr(self, "chapter_linked", None)
        if linked_editor is not None:
            chapter["linked_characters"] = _normalize_name_list(linked_editor.text())
        marked = bool(_mark_chapters_analyzed(chapters, [str(chapter.get("id", "") or "")]))
        if marked and hasattr(self, "chapter_list"):
            self._refresh_chapter_item(self.current_chapter_index)
        return marked

    def on_chapter_ai_ready(self, action, content):
        if self._forward_chapter_task_signal("on_chapter_ai_ready", action, content):
            return
        if not self._chapter_ai_callback_is_current():
            return
        self.set_chapter_ai_panel_expanded(True)
        raw_final_text = str(content or "").strip() or self.chapter_ai_stream_text.strip()
        resume_prefix = getattr(self, "_chapter_ai_resume_prefix", "") if action == "draft" else ""
        if resume_prefix and raw_final_text and not raw_final_text.startswith(resume_prefix):
            final_text = _append_text_without_duplicate_overlap(resume_prefix, raw_final_text)
        else:
            final_text = raw_final_text
        request_id, started_at, worker_diagnostics = self._chapter_ai_signal_diagnostics()
        elapsed_ms = worker_diagnostics.get("elapsed_ms", 0) if isinstance(worker_diagnostics, dict) else 0
        if not elapsed_ms and started_at:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
        exchange_path = self._save_chapter_ai_latest_exchange(
            action,
            request_id,
            final_text,
            worker_diagnostics=worker_diagnostics,
        )
        self._log_novel_diagnostic(
            "chapter_ai_request_result",
            level="info",
            action=action,
            request_id=request_id,
            content_chars=len(str(content or "")),
            output_chars=len(final_text),
            output_sha256=hashlib.sha256(
                final_text.encode("utf-8", errors="replace")
            ).hexdigest() if final_text else "",
            elapsed_ms=elapsed_ms,
            diagnostic_exchange_path=exchange_path,
            worker_diagnostics=worker_diagnostics,
        )
        if final_text and self._chapter_ai_output_is_user_facing(action):
            self.chapter_ai_preview.setPlainText(final_text)
        if getattr(self, "_chapter_ai_stop_requested_by_user", False):
            if action in {"memory_finalize", "logic_repair"}:
                pending = getattr(self, "_chapter_ai_memory_pending", {})
                kept_final = str(pending.get("final_text", "") or "").strip() if isinstance(pending, dict) else ""
                if kept_final:
                    self.chapter_ai_preview.setPlainText(kept_final)
                self._reset_chapter_ai_sequence()
                self.set_status_tip(
                    ("正文逻辑修复已中止，终稿已保留在预览和恢复检查点中；"
                     if action == "logic_repair" else
                     "状态整理已中止，正文终稿已保留在预览和恢复检查点中；")
                    + "重新启动自动扩写时会继续整理状态。"
                )
                return
            if final_text and self._chapter_ai_output_is_user_facing(action):
                if action in {"draft", "outline", "summary"}:
                    self._set_partial_chapter_ai_preview_state(True, action)
                self.set_status_tip("AI 辅助生成已中止，已保留当前预览内容。")
            else:
                self.set_status_tip("AI 辅助生成已中止，内部结构化结果未显示。")
            self._reset_chapter_ai_sequence()
            return
        if action == "memory_repair":
            self._handle_memory_repair_ready(final_text)
            return
        if action == "logic_repair":
            self._handle_chapter_logic_repair_ready(final_text)
            return
        if action == "memory_reconcile":
            self._handle_memory_reconciliation_ready(final_text)
            return
        if action == "memory_finalize":
            self._handle_memory_finalize_ready(final_text)
            return
        if action in {"style_baseline", "style_sheet", "style_sheet_merge", "style_persona", "style_cards"} and getattr(
            self, "_chapter_ai_style_workflow_active", False
        ):
            self._clear_transient_chapter_ai_retry(action)
            entry = self._chapter_ai_style_cache_entry if isinstance(self._chapter_ai_style_cache_entry, dict) else {}
            units = entry.get("units", []) if isinstance(entry.get("units"), list) else []
            index = int(getattr(self, "_chapter_ai_style_build_unit_index", -1) or 0)
            if action in {"style_baseline", "style_sheet"} and 0 <= index < len(units):
                units[index]["baseline" if action == "style_baseline" else "sheet"] = final_text
                entry["units"] = units
            elif action == "style_sheet_merge":
                merge_results = entry.get("merge_results", []) if isinstance(entry.get("merge_results"), list) else []
                merge_results.append(final_text)
                entry["merge_results"] = merge_results
                entry["combined_sheet"] = final_text
            elif action == "style_persona":
                entry["persona"] = final_text
            elif action == "style_cards":
                entry["style_cards"] = _parse_style_cards_result(
                    final_text,
                    self._chapter_ai_style_reference,
                )
                entry["style_cards_version"] = STYLE_CARD_CACHE_VERSION
            entry["status"] = "building"
            entry.pop("error", None)
            self._persist_style_cache_entry(self._chapter_ai_style_reference_hash, entry)
            self.chapter_ai_preview.clear()
            self.chapter_ai_stream_text = ""
            self._continue_style_profile_build()
            return
        if action == "style_profile" and getattr(self, "_chapter_ai_style_workflow_active", False):
            self._clear_transient_chapter_ai_retry(action)
            self._chapter_ai_style_profile = final_text
            self._chapter_ai_style_combined_sheet = final_text
            reference_hash = hashlib.sha256(self._chapter_ai_style_reference.encode("utf-8")).hexdigest()
            self._chapter_ai_style_profile_cache_hash = reference_hash
            self._chapter_ai_style_profile_cache_text = final_text
            self._persist_style_profile(reference_hash, final_text)
            self._start_style_profiled_draft()
            return
        if action == "style_rules" and getattr(self, "_chapter_ai_style_workflow_active", False):
            self._clear_transient_chapter_ai_retry(action)
            self._chapter_ai_style_rules = final_text
            self._start_style_draft_with_rules()
            return
        if action == "draft":
            # Both single-chapter expansion and automatic expansion use this
            # same transaction boundary: draft -> memory_finalize -> commit.
            # The body must stay in the preview until the complete package is
            # validated and committed. Treat every chapter draft callback this
            # way so legacy or queued state-marker handoffs cannot fall back to
            # the ordinary preview-apply path.
            self._stage_chapter_ai_draft_for_memory_finalize(final_text)
            return
        if action == "style_finalize" and getattr(self, "_chapter_ai_style_workflow_active", False):
            bundle = _parse_style_finalize_result(final_text)
            initial = str(getattr(self, "_chapter_ai_style_candidate", "") or "").strip()
            revised = str(bundle.get("text", "") or "").strip()
            if not bundle.get("parsed"):
                rescue_candidate = revised or initial
                if self._schedule_transient_chapter_ai_retry(
                    "style_finalize",
                    "终稿审校结果无法解析或缺少验收内容",
                    force_retry=True,
                    retry_callback=lambda tab: tab._start_style_candidate_finalize(
                        rescue_candidate,
                        rescue=True,
                        gate_errors=["终稿审校结果无法解析或缺少验收内容"],
                        transient_retry=True,
                    ),
                ):
                    return
                self.on_chapter_ai_failed("终稿审校结果无法解析或缺少验收内容")
                return
            if not revised and not initial:
                if self._schedule_transient_chapter_ai_retry(
                    "style_finalize",
                    "终稿审校没有返回可用正文",
                    force_retry=True,
                    retry_callback=lambda tab: tab._start_style_candidate_finalize(
                        initial,
                        rescue=True,
                        gate_errors=["终稿审校没有返回可用正文"],
                        transient_retry=True,
                    ),
                ):
                    return
                self.on_chapter_ai_failed("终稿审校没有返回可用正文")
                return
            execution = str(getattr(self, "_chapter_ai_style_execution", "") or "").strip()
            selected = (
                revised or initial
                if execution else
                self._select_style_final_text(initial, revised, bundle, validate_memory=False)
            )
            acceptance_project = self._ai_project_snapshot()
            acceptance_chapter_index = int(getattr(self, "current_chapter_index", 0) or 0)
            selected_errors = _style_finalize_acceptance_errors(
                execution,
                selected,
                bundle.get("acceptance", {}),
                self._chapter_ai_style_reference,
                self._chapter_ai_style_output_target,
                project=acceptance_project,
                chapter_index=acceptance_chapter_index,
                style_plan=str(getattr(self, "_chapter_ai_style_plan", "") or ""),
                profile_text=str(getattr(self, "_chapter_ai_style_profile", "") or ""),
            )
            if selected_errors and revised and selected != revised:
                revised_errors = _style_finalize_acceptance_errors(
                    execution,
                    revised,
                    bundle.get("acceptance", {}),
                    self._chapter_ai_style_reference,
                    self._chapter_ai_style_output_target,
                    project=acceptance_project,
                    chapter_index=acceptance_chapter_index,
                    style_plan=str(getattr(self, "_chapter_ai_style_plan", "") or ""),
                    profile_text=str(getattr(self, "_chapter_ai_style_profile", "") or ""),
                )
                if not revised_errors:
                    selected = revised
                    selected_errors = []
            if (
                selected_errors
                and int(getattr(self, "_chapter_ai_style_finalize_count", 0) or 0) >= 2
                and initial
            ):
                previous_errors = [
                    str(value or "").strip()
                    for value in getattr(self, "_chapter_ai_style_pending_reasons", [])
                    if str(value or "").strip()
                ]
                previous_hard_errors = [
                    value for value in previous_errors
                    if _style_finalize_error_is_hard(value)
                ]
                current_hard_errors = [
                    value for value in selected_errors
                    if _style_finalize_error_is_hard(value)
                ]
                if current_hard_errors and not previous_hard_errors:
                    selected = initial
                    selected_errors = previous_errors
            if selected_errors:
                hard_errors = [
                    value for value in selected_errors
                    if _style_finalize_error_is_hard(value)
                ]
                style_observation_errors = [
                    value for value in selected_errors if value not in hard_errors
                ]
                if style_observation_errors:
                    self._log_novel_diagnostic(
                        "style_structure_drift_observed",
                        level="info",
                        chapter_id=self._current_chapter_id(),
                        observations=style_observation_errors,
                        repair_triggered=False,
                    )
                self._chapter_ai_style_pending_reasons = list(selected_errors)
                if hard_errors:
                    rescue_candidate = revised or initial
                    rescue_gate_errors = list(hard_errors)
                    if self._schedule_transient_chapter_ai_retry(
                        "style_finalize",
                        "终稿验收未通过：" + "；".join(hard_errors[:6]),
                        force_retry=True,
                        retry_callback=lambda tab: tab._start_style_candidate_finalize(
                            rescue_candidate,
                            rescue=True,
                            gate_errors=rescue_gate_errors,
                            transient_retry=True,
                        ),
                    ):
                        return
                    self.on_chapter_ai_failed(
                        "终稿硬验收未通过：" + "；".join(hard_errors[:6])
                    )
                    return
            self._chapter_ai_style_final_bundle = bundle
            self._chapter_ai_style_retry_attempted = True
            self._chapter_ai_style_fallback_text = ""
            self.chapter_ai_preview.setPlainText(selected)
            self._clear_transient_chapter_ai_retry("style_finalize")
            self._start_memory_finalize(selected)
            return
        if self._maybe_retry_draft_for_style(action, final_text):
            return
        if action == "draft":
            self._chapter_ai_style_fallback_text = ""
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
            self._clear_transient_chapter_ai_retry(action)
            self._set_partial_chapter_ai_preview_state(False)
            self._chapter_ai_resume_prefix = ""
            self.apply_chapter_ai_preview(target)
        else:
            self.set_status_tip(f"AI {labels.get(action, '内容')}已生成，可确认后应用。")

    def on_chapter_ai_failed(self, err):
        if self._forward_chapter_task_signal("on_chapter_ai_failed", err):
            return
        if not self._chapter_ai_callback_is_current():
            return
        action = getattr(self, "_chapter_ai_running_action", "")
        sequence_active = bool(getattr(self, "_chapter_ai_sequence_active", False))
        err_text = clean_error_text(err)
        request_id, started_at, worker_diagnostics = self._chapter_ai_signal_diagnostics()
        snapshot_path = self._save_chapter_ai_failure_snapshot(
            action,
            request_id,
            error=err_text,
            worker_diagnostics=worker_diagnostics,
        )
        retry_scheduled = False
        try:
            automatic_stage_retry = bool(
                action in _CHAPTER_AI_RETRY_STAGES
                and (
                    sequence_active
                    or getattr(self, "_auto_expand_all_active", False)
                )
            )
            retry_scheduled = self._schedule_transient_chapter_ai_retry(action, err)
            if not retry_scheduled and automatic_stage_retry:
                retry_scheduled = self._schedule_transient_chapter_ai_retry(
                    action,
                    err,
                    force_retry=True,
                )
        except Exception as exc:
            self._log_novel_diagnostic(
                "chapter_ai_retry_scheduler_failed",
                level="error",
                action=action,
                request_id=request_id,
                error=clean_error_text(exc),
                error_category=self._novel_diagnostic_error_category(exc),
            )
        self._log_novel_diagnostic(
            "chapter_ai_request_failed",
            level="error",
            action=action,
            request_id=request_id,
            error=err_text,
            error_category=self._novel_diagnostic_error_category(err_text),
            retryable=self._is_transient_chapter_ai_error(err_text),
            retry_scheduled=bool(retry_scheduled),
            sequence_active=sequence_active,
            diagnostic_snapshot_path=snapshot_path,
            partial_output_chars=int(
                worker_diagnostics.get("response_chars", 0) or 0
            ) if isinstance(worker_diagnostics, dict) else len(self.chapter_ai_stream_text),
            worker_diagnostics=worker_diagnostics,
            elapsed_ms=(
                worker_diagnostics.get("elapsed_ms", 0)
                if isinstance(worker_diagnostics, dict) else
                round((time.perf_counter() - started_at) * 1000, 1) if started_at else 0
            ),
        )
        if retry_scheduled:
            return
        if getattr(self, "_auto_expand_all_active", False) and action not in {
            "style_profile", "style_rules", "memory_reconcile"
        }:
            self._stop_auto_expand_all(
                f"自动扩写已停止：第{self.current_chapter_index + 1}章生成失败，请检查后继续。"
            )
        if action == "draft" and "剧情执行稿结构不完整" in err_text:
            self._log_novel_diagnostic(
                "style_execution_partial_discarded",
                level="warning",
                action=action,
                request_id=request_id,
                discarded_chars=len(str(self.chapter_ai_stream_text or "")),
            )
            self.chapter_ai_preview.clear()
            self.chapter_ai_stream_text = ""
            self._chapter_ai_resume_prefix = ""
            self._chapter_ai_style_workflow_active = False
            self._chapter_ai_style_fallback_text = ""
            self._chapter_ai_style_execution = ""
            self._chapter_ai_style_plan = ""
            self._set_partial_chapter_ai_preview_state(False)
            self._reset_chapter_ai_sequence()
            self.set_status_tip("剧情执行稿结构不完整，半成品已丢弃；请重新扩写本章。")
            self._show_chapter_ai_failure(err_text)
            return
        if action in {"style_baseline", "style_sheet", "style_sheet_merge", "style_persona", "style_cards"} and getattr(
            self, "_chapter_ai_style_workflow_active", False
        ):
            entry = self._chapter_ai_style_cache_entry if isinstance(self._chapter_ai_style_cache_entry, dict) else {}
            entry["status"] = "failed"
            entry["error"] = clean_error_text(err)[:500]
            self._persist_style_cache_entry(self._chapter_ai_style_reference_hash, entry)
            self._reset_chapter_ai_sequence()
            self.set_status_tip(
                f"首次文风建档已暂停，已保存完成进度；重新扩写时会从当前步骤继续：{clean_error_text(err)[:90]}"
            )
            return
        if action == "style_profile" and getattr(self, "_chapter_ai_style_workflow_active", False):
            self._chapter_ai_style_profile = ""
            self._start_style_profiled_draft()
            return
        if action == "style_rules" and getattr(self, "_chapter_ai_style_workflow_active", False):
            self._chapter_ai_style_rules = ""
            self._start_style_draft_with_rules()
            return
        if action == "memory_reconcile":
            self._apply_memory_reconciliation_fallback(
                "边界语义对账调用失败，已保留原本通过校验的状态包等待下次对账：" + clean_error_text(err)
            )
            return
        if action in {"memory_finalize", "memory_repair", "logic_repair"}:
            self._fail_memory_sync(clean_error_text(err))
            return
        if action in {"style_finalize", "style_audit", "style_rewrite", "style_plot_extract"} and getattr(self, "_chapter_ai_style_workflow_active", False):
            candidate = str(getattr(self, "_chapter_ai_style_candidate", "") or "").strip()
            self.chapter_ai_preview.setPlainText(candidate)
            self._chapter_ai_style_workflow_active = False
            self._set_partial_chapter_ai_preview_state(False)
            self._reset_chapter_ai_sequence()
            self.set_status_tip(
                f"文风流程失败，候选正文仅保留在预览，未写入章节：{clean_error_text(err)[:100]}"
            )
            return
        style_fallback = str(getattr(self, "_chapter_ai_style_fallback_text", "") or "").strip()
        if action == "draft" and style_fallback:
            self.chapter_ai_preview.setPlainText(style_fallback)
            self._chapter_ai_style_fallback_text = ""
            self._set_partial_chapter_ai_preview_state(True, action)
            self._reset_chapter_ai_sequence()
            self.set_status_tip("风格自动重写失败，已保留首次正文预览，可检查后决定是否应用。")
            return
        output_is_user_facing = self._chapter_ai_output_is_user_facing(action)
        kept_preview = self.chapter_ai_stream_text.strip() if output_is_user_facing else ""
        if kept_preview:
            self.chapter_ai_preview.setPlainText(kept_preview)
        if action == "draft" and kept_preview:
            self._set_partial_chapter_ai_preview_state(True, action)
        elif action in {"outline", "summary"} and output_is_user_facing:
            self._set_partial_chapter_ai_preview_state(True, action)
        else:
            self._refresh_chapter_ai_action_labels()
        self._reset_chapter_ai_sequence()
        action_label = {"draft": "正文", "outline": "提纲", "summary": "摘要"}.get(action, "正文")
        kept_hint = "已保留预览，" if kept_preview else ""
        if kept_preview:
            action_text = "预览仅供查看；重新点击扩写会丢弃半成品并重写整章"
        elif action in {"outline", "summary"}:
            action_text = "可重新扩写整章"
        else:
            action_text = "可重新扩写正文" if action == "draft" else f"可重新生成{action_label}"
        status = f"AI 写作失败，{kept_hint}{action_text}：{err_text[:80]}"
        self.set_status_tip(status)
        self._show_chapter_ai_failure(err_text)

    def _cleanup_writing_worker(self):
        if self._forward_chapter_task_signal("_cleanup_writing_worker"):
            return
        worker = self._chapter_task_signal_worker()
        def cleanup(tab):
            try:
                was_current = tab.writing_worker is worker
                if was_current:
                    tab.writing_worker = None
                retired = getattr(tab, "writing_retired_workers", None)
                if isinstance(retired, list) and worker in retired:
                    retired.remove(worker)
                if worker is not None:
                    worker.deleteLater()
                if was_current:
                    retry_pending = bool(getattr(tab, "_chapter_ai_transient_retry_pending", False))
                    tab._set_chapter_ai_actions_enabled(not retry_pending)
                    if not retry_pending:
                        tab._chapter_ai_stop_requested_by_user = False
                        tab._chapter_ai_running_action = ""
                    if (
                        getattr(tab, "_auto_expand_all_active", False)
                        and getattr(tab, "_auto_expand_all_waiting_next", False)
                    ):
                        tab._schedule_chapter_task_callback(
                            100, lambda owner: owner._start_next_auto_expand_chapter()
                        )
            except Exception as e:
                log_debug("小说章节 AI 线程清理失败", e)
        self._schedule_chapter_task_callback(0, cleanup)

    def apply_chapter_ai_preview(self, target):
        text = self.chapter_ai_preview.toPlainText().strip()
        if not text or text == "正在生成，请稍等...":
            self.set_status_tip("没有可应用的 AI 结果。")
            return
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
        elif target == "text":
            old = self.chapter_text.toPlainText().strip()
            self.chapter_text.setPlainText(_append_text_without_duplicate_overlap(old, text))
        if target in {"replace_text", "text"}:
            inferred_names = self._infer_current_chapter_linked_names(
                extra_text=self.chapter_text.toPlainText()
            )
            self._merge_chapter_linked_names(inferred_names)
        self._mark_chapter_dirty()
        self.chapter_ai_preview.clear()
        self._set_partial_chapter_ai_preview_state(False)
        self._chapter_ai_resume_prefix = ""
        self.set_chapter_ai_panel_expanded(False)
        if target in {"replace_text", "text"}:
            self.set_status_tip("正文已应用。")
        else:
            self.set_status_tip("AI 结果已应用到当前章节。")

    def _current_chapter_id(self):
        chapters = self.current_project.get("chapters", [])
        if not isinstance(chapters, list) or self.current_chapter_index < 0 or self.current_chapter_index >= len(chapters):
            return ""
        chap = chapters[self.current_chapter_index]
        return str(chap.get("id", "") or "") if isinstance(chap, dict) else ""


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
        if self.failed_analysis_chunks:
            self._set_candidate_postprocess_state("")
        elif _import_candidates_has_content(self.import_candidates):
            self._set_candidate_postprocess_state("pending")
        else:
            self._set_candidate_postprocess_state("")
        self._persist_candidate_analysis_state()
        self._refresh_candidate_analysis_result_view()
        self._reload_chapter_list(self.current_chapter_index)
        material_hits = self._candidate_material_status_text()
        cleanup_tail = self._candidate_auto_cleanup_status_text()
        if self.failed_analysis_chunks:
            reason = self._failed_candidate_error_summary(limit=1).replace("\n", " ")
            reason_tail = f" 原因：{reason}" if reason else ""
            self.set_status_tip(
                f"AI 分析部分完成：成功 {succeeded}/{total} 块，失败 {len(self.failed_analysis_chunks)} 块；下次点击 AI 分析候选会优先重试失败块{cleanup_tail}。{reason_tail}"
            )
        else:
            if not _import_candidates_has_content(self.import_candidates):
                self.set_status_tip(
                    f"AI 分析完成：没有发现需要加入项目的候选内容{cleanup_tail}"
                )
                return
            self.set_status_tip(
                f"AI 分析完成：人物 {len(self.import_candidates['characters'])}，设定 {len(self.import_candidates['lore'])}，伏笔 {len(self.import_candidates['foreshadows'])}，资料草案 {material_hits}{cleanup_tail}；正在继续合并候选并查重..."
            )
            provider, model, error = self._current_novel_ai_selection()
            if error:
                self._set_candidate_postprocess_state("failed", error)
                self._persist_candidate_analysis_state()
                self.refresh_import_candidate_lists()
                self.set_status_tip(f"块分析已保存；候选合并待继续：{error}")
                return
            self._start_candidate_postprocess(provider, model)

    def on_ai_candidates_partial(self, data, completed, total):
        self._apply_candidate_analysis_result(data)
        self._persist_candidate_analysis_draft_state()
        self._refresh_candidate_analysis_result_view()
        self._reload_chapter_list(self.current_chapter_index)
        material_hits = self._candidate_material_status_text()
        failed_count = len(self.failed_analysis_chunks)
        tail = f"，待重试 {failed_count} 块" if failed_count else ""
        cleanup_tail = self._candidate_auto_cleanup_status_text()
        if failed_count:
            reason = self._failed_candidate_error_summary(limit=1).replace("\n", " ")
            if reason:
                tail += f"，原因：{reason}"
        self.set_status_tip(
            f"AI 分析进度 {completed}/{total}：人物 {len(self.import_candidates['characters'])}，设定 {len(self.import_candidates['lore'])}，伏笔 {len(self.import_candidates['foreshadows'])}，资料草案 {material_hits}{cleanup_tail}{tail}"
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

    def on_ai_candidate_postprocess_ready(self, data):
        replaced_candidates = self._apply_candidate_postprocess_result(data)
        self._persist_candidate_analysis_state()
        self._refresh_candidate_analysis_result_view()
        self._reload_chapter_list(self.current_chapter_index)
        material_hits = self._candidate_material_status_text()
        cleanup_tail = self._candidate_auto_cleanup_status_text()
        if not replaced_candidates:
            self.set_status_tip("AI 候选合并完成：没有新的候选需要加入，已保留分块候选供查看。")
            return
        self.set_status_tip(
            f"AI 候选合并完成：人物 {len(self.import_candidates['characters'])}，设定 {len(self.import_candidates['lore'])}，伏笔 {len(self.import_candidates['foreshadows'])}，资料草案 {material_hits}{cleanup_tail}"
        )

    def on_ai_candidate_postprocess_failed(self, err):
        message = clean_error_text(err)
        self._set_candidate_postprocess_state("failed", message)
        self._persist_candidate_analysis_state()
        self._refresh_candidate_analysis_result_view()
        self.set_status_tip(f"候选已保存；AI 候选合并/查重失败，可再次点击 AI 分析候选继续：{message[:100]}")
        QMessageBox.warning(self, "AI 候选合并失败", f"{message}\n\n块分析结果已保留在候选区，可再次点击“AI 分析候选”重试合并/查重。")

    def on_foreshadow_review_ready(self, data):
        self.foreshadow_review_observations = self._merge_foreshadow_review_observations(data)
        draft_count = self._sync_foreshadow_observations_to_import_candidates()
        self.failed_foreshadow_review_chunks = [
            deepcopy(item)
            for item in data.get("_failed_chunks", [])
            if isinstance(item, dict) and str(item.get("text", "") or "").strip()
        ] if isinstance(data, dict) else []
        self._sync_candidate_analysis_state()
        self._mark_dirty()
        total = int(data.get("_chunk_total", 0) or 0) if isinstance(data, dict) else 0
        succeeded = int(data.get("_chunk_succeeded", 0) or 0) if isinstance(data, dict) else 0
        if self.failed_foreshadow_review_chunks:
            reason = clean_error_text(self.failed_foreshadow_review_chunks[0].get("error", "") or "").replace("\n", " ")
            reason_tail = f" 原因：{reason[:120]}" if reason else ""
            self.foreshadow_review_comparison_state = {}
            self.foreshadow_review_postprocess_pending = False
            self._persist_candidate_analysis_state()
            self._refresh_candidate_analysis_result_view()
            self.set_status_tip(
                f"AI 伏笔观察部分完成：成功 {succeeded}/{total} 章，已显示 {draft_count} 条观察草稿，失败 {len(self.failed_foreshadow_review_chunks)} 章；下次点击会优先重试失败章。{reason_tail}"
            )
            return
        self._persist_candidate_analysis_state()
        self._refresh_candidate_analysis_result_view()
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self.foreshadow_review_comparison_state = {
                "status": "failed",
                "error": error,
                "review_flow": "foreshadow_review_chapter_compare",
                "updated_at": now_str(),
            }
            self.foreshadow_review_postprocess_pending = True
            self._persist_candidate_analysis_state()
            self.set_status_tip(f"逐章伏笔观察已保存；按章比对待继续：{error}")
            return
        self._start_foreshadow_review_comparison(provider, model)

    def on_foreshadow_review_partial(self, data, completed, total):
        self.foreshadow_review_observations = self._merge_foreshadow_review_observations(data)
        draft_count = self._sync_foreshadow_observations_to_import_candidates()
        self.failed_foreshadow_review_chunks = [
            deepcopy(item)
            for item in data.get("_failed_chunks", [])
            if isinstance(item, dict) and str(item.get("text", "") or "").strip()
        ] if isinstance(data, dict) else []
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        self._refresh_candidate_analysis_result_view()
        self._persist_candidate_analysis_draft_state()
        failed_tail = f"，待重试 {len(self.failed_foreshadow_review_chunks)} 章" if self.failed_foreshadow_review_chunks else ""
        self.set_status_tip(
            f"AI 伏笔观察进度 {completed}/{total}：已提取 {len(self.foreshadow_review_observations.get('foreshadows', []))} 条观察，候选区已显示 {draft_count} 条草稿{failed_tail}"
        )

    def _start_foreshadow_review_comparison(self, provider, model):
        observations = self.foreshadow_review_observations if isinstance(self.foreshadow_review_observations, dict) else {}
        state = self.foreshadow_review_comparison_state if isinstance(self.foreshadow_review_comparison_state, dict) else {}
        retry_chunks = self._foreshadow_review_comparison_retry_chunks(state)
        comparison_chunks = retry_chunks or self._split_foreshadow_observation_records(observations)
        if not comparison_chunks:
            self.foreshadow_review_comparison_state = {}
            self.foreshadow_review_postprocess_pending = False
            self.set_status_tip("AI 伏笔观察完成：没有可继续比对的长期线索。")
            return
        self.foreshadow_review_comparison_state = {
            "status": "pending",
            "review_flow": "foreshadow_review_chapter_compare",
            "updated_at": now_str(),
        }
        self.foreshadow_review_postprocess_pending = True
        self.foreshadow_review_worker = NovelForeshadowReviewPostprocessWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            deepcopy(observations),
            _foreshadow_review_dossier_text(self._ai_project_snapshot()),
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
            self._candidate_analysis_concurrency(),
            chunks=comparison_chunks,
        )
        self._connect_novel_worker_status(self.foreshadow_review_worker)
        self.foreshadow_review_worker.result_ready.connect(self.on_foreshadow_review_postprocess_ready)
        self.foreshadow_review_worker.partial_ready.connect(self.on_foreshadow_review_postprocess_partial)
        self.foreshadow_review_worker.failed.connect(self.on_foreshadow_review_postprocess_failed)
        self.foreshadow_review_worker.finished.connect(self._cleanup_foreshadow_review_worker)
        self._set_candidate_actions_enabled(False)
        self._set_foreshadow_actions_enabled(False)
        prefix = "正在重试 AI 伏笔按章比对失败块" if retry_chunks else "正在按章比对伏笔观察"
        self.set_status_tip(f"{prefix}：共 {len(comparison_chunks)} 批，并发 {self._candidate_analysis_concurrency()}...")
        self.foreshadow_review_worker.start()

    def on_foreshadow_review_postprocess_partial(self, data, completed, total):
        failed_chunks = [
            deepcopy(item)
            for item in data.get("_failed_chunks", [])
            if isinstance(item, dict) and str(item.get("text", "") or "").strip()
        ] if isinstance(data, dict) else []
        self._apply_foreshadow_review_postprocess_candidates(data, keep_observation_drafts=True)
        state = {
            "status": "pending",
            "review_flow": "foreshadow_review_chapter_compare",
            "updated_at": now_str(),
        }
        if failed_chunks:
            state["failed_chunks"] = failed_chunks
        self.foreshadow_review_comparison_state = state
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        self._refresh_candidate_analysis_result_view()
        self._persist_candidate_analysis_draft_state()
        failed_tail = f"，待重试 {len(failed_chunks)} 批" if failed_chunks else ""
        self.set_status_tip(
            f"AI 伏笔按章比对进度 {completed}/{total}：已生成 {len(self.import_candidates.get('foreshadows', []))} 条候选{failed_tail}"
        )

    def on_foreshadow_review_postprocess_ready(self, data):
        failed_chunks = [
            deepcopy(item)
            for item in data.get("_failed_chunks", [])
            if isinstance(item, dict) and str(item.get("text", "") or "").strip()
        ] if isinstance(data, dict) else []
        self._apply_foreshadow_review_postprocess_candidates(data, keep_observation_drafts=bool(failed_chunks))
        self.failed_foreshadow_review_chunks = []
        if failed_chunks:
            self.foreshadow_review_comparison_state = {
                "status": "failed",
                "error": str(failed_chunks[0].get("error", "") or ""),
                "failed_chunks": failed_chunks,
                "review_flow": "foreshadow_review_chapter_compare",
                "updated_at": now_str(),
            }
            self.foreshadow_review_postprocess_pending = True
        else:
            self.foreshadow_review_observations = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
            self.foreshadow_review_comparison_state = {}
            self.foreshadow_review_postprocess_pending = False
        self._sync_import_candidates_to_project()
        self._sync_candidate_analysis_state()
        self._clear_candidate_detail_view()
        self._refresh_candidate_analysis_result_view()
        self._mark_dirty()
        self._persist_candidate_analysis_state()
        count = len(self.import_candidates.get("foreshadows", []))
        if failed_chunks:
            reason = clean_error_text(failed_chunks[0].get("error", "") or "").replace("\n", " ")
            reason_tail = f" 原因：{reason[:120]}" if reason else ""
            self.set_status_tip(
                f"AI 伏笔体检部分完成：已生成 {count} 条候选，失败 {len(failed_chunks)} 个按章比对块；下次点击会优先重试失败块。{reason_tail}"
            )
        else:
            self.set_status_tip(f"AI 伏笔体检完成：已生成 {count} 条伏笔处理候选，请在候选区确认后再加入项目。")

    def on_foreshadow_review_postprocess_failed(self, err):
        message = clean_error_text(err)
        self.foreshadow_review_comparison_state = {
            "status": "failed",
            "error": message,
            "review_flow": "foreshadow_review_chapter_compare",
            "updated_at": now_str(),
        }
        self.foreshadow_review_postprocess_pending = True
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        self._mark_dirty()
        self._refresh_candidate_analysis_result_view()
        self._persist_candidate_analysis_state()
        self.set_status_tip(f"伏笔观察已保存；按章比对失败，可再次点击继续：{message[:100]}")
        QMessageBox.warning(self, "AI 伏笔体检失败", f"{message}\n\n逐章伏笔观察已保留，可再次点击“AI 伏笔体检”继续按章比对。")

    def on_foreshadow_review_failed(self, err):
        message = clean_error_text(err)
        self.set_status_tip(f"AI 伏笔体检失败：{message[:100]}")
        QMessageBox.warning(self, "AI 伏笔体检失败", message)

    def _cleanup_foreshadow_review_worker(self):
        worker = self.sender()
        def cleanup():
            try:
                if self.foreshadow_review_worker is worker:
                    self.foreshadow_review_worker = None
                if worker is not None:
                    worker.deleteLater()
                active_foreshadow_worker = self.foreshadow_review_worker is not None
                if self.analysis_worker is None and not active_foreshadow_worker:
                    self._set_candidate_actions_enabled(True)
                    self._set_foreshadow_actions_enabled(True)
            except Exception as e:
                log_debug("小说伏笔体检线程清理失败", e)
        QTimer.singleShot(0, cleanup)

    def _cleanup_analysis_worker(self):
        worker = self.sender()
        def cleanup():
            try:
                if self.analysis_worker is worker:
                    self.analysis_worker = None
                if worker is not None:
                    worker.deleteLater()
                if self.analysis_worker is None:
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
        raw_foreshadow_indexes = self._checked_candidate_indexes(self.candidate_foreshadow_list)
        foreshadow_items = self.import_candidates.get("foreshadows", [])
        skipped_observation_drafts = [
            index
            for index in raw_foreshadow_indexes
            if isinstance(index, int)
            and 0 <= index < len(foreshadow_items)
            and self._is_foreshadow_observation_draft(foreshadow_items[index])
        ]
        checked = {
            "characters": self._checked_candidate_indexes(self.candidate_character_list),
            "lore": self._checked_candidate_indexes(self.candidate_lore_list),
            "foreshadows": [
                index
                for index in raw_foreshadow_indexes
                if index not in skipped_observation_drafts
            ],
            "project_materials": self._checked_candidate_material_keys(),
        }
        if not any(checked.values()) and not self.pending_analysis_chapter_ids:
            if skipped_observation_drafts:
                self.set_status_tip("逐章伏笔观察草稿需等待按章比对后再加入项目。")
                return
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
            self._set_candidate_postprocess_state("")
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        self.refresh_import_candidate_lists()
        self._reload_chapter_list(self.current_chapter_index)
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

    def _recover_creation_wizard_project_from_draft(self, data, path):
        """把完成但尚未落盘为正式项目的向导草稿恢复出来。"""
        if path and os.path.abspath(str(path)) != os.path.abspath(str(NOVEL_DRAFT_FILE)):
            return data, path, False
        payload = creation_wizard_payload_from_project_draft(data)
        if not payload:
            return data, path, False
        framework = payload.get("creation_framework", {})
        premise = framework.get("premise", {}) if isinstance(framework, dict) else {}
        title = _safe_name(
            framework.get("novel_name", "") if isinstance(framework, dict) else ""
        ) or _safe_name(
            premise.get("title", "") if isinstance(premise, dict) else ""
        ) or "未命名小说"

        # 如果正式项目已经存在，直接打开它，避免启动时重复生成同名项目。
        for record in list_project_summaries():
            if _safe_name(record.get("title", "")) != title:
                continue
            existing_path = str(record.get("path", "") or "").strip()
            existing_data = load_json_file(existing_path, {})
            if isinstance(existing_data, dict):
                remember_project_path(existing_path)
                save_draft_project(existing_data)
                return existing_data, existing_path, True

        try:
            recovered_data = self._apply_creation_wizard_payload(
                _default_project(),
                payload,
            )
            project_path = unique_project_path(title)
            save_project_file(project_path, recovered_data)
            remember_project_path(project_path)
            save_draft_project(recovered_data)
            return recovered_data, project_path, True
        except Exception as exc:
            log_debug("恢复新建向导项目失败", exc)
            return data, path, False

    def _load_initial_project(self):
        data, path = load_initial_project_data()
        data, path, recovered = self._recover_creation_wizard_project_from_draft(data, path)
        self._load_project_data(data, path)
        if recovered:
            self.set_status_tip("已从自动草稿恢复新建向导资料，并保存到项目列表。")
        self.refresh_project_list()

    def _autosave_draft(self):
        if self._loading:
            return
        if self._current_fanqie_upload_worker() is not None:
            return
        if not self._dirty and self._draft_saved_once:
            return
        if getattr(self, "_autosave_in_progress", False):
            return
        current_generation = int(getattr(self, "_dirty_generation", 0) or 0)
        if getattr(self, "_last_failed_autosave_generation", -1) == current_generation:
            return
        self._autosave_in_progress = True
        perf_start = time.perf_counter()
        summary = self._novel_perf_summary()
        try:
            self._flush_current_editors()
            self._auto_update_project_status()
            self._sync_candidate_analysis_state()
            self._sync_import_candidates_to_project()
            self.current_project["updated_at"] = now_str()
            self._save_draft_snapshot()
            self._dirty = False
            self._last_failed_autosave_generation = -1
            self._log_novel_perf(
                "自动保存草稿",
                perf_start,
                threshold_ms=120,
                chapters=summary.get("chapters"),
                body=summary.get("body_chars"),
                project_dirty=getattr(self, "_project_file_dirty", False),
            )
        except Exception as e:
            self._last_failed_autosave_generation = current_generation
            self._log_novel_perf(
                "自动保存草稿失败",
                perf_start,
                threshold_ms=0,
                chapters=summary.get("chapters"),
                body=summary.get("body_chars"),
            )
            self._log_novel_diagnostic(
                "project_autosave_failed",
                level="error",
                autosave_generation=int(current_generation or 0),
                project_path=str(getattr(self, "current_project_path", "") or NOVEL_DRAFT_FILE),
                project_summary=summary,
                error_category="storage",
                **self._novel_exception_details(e),
            )
            log_debug("小说草稿自动保存失败", e)
        finally:
            self._autosave_in_progress = False

    def _save_draft_snapshot(self):
        save_draft_project(self.current_project)
        self._draft_saved_once = True

    def _save_current_project_snapshot_if_named(self):
        if self._current_background_chapter_runner() is not None:
            return
        if self._current_fanqie_upload_worker() is not None:
            return
        path = str(self.current_project_path or "").strip()
        if not path or path == NOVEL_DRAFT_FILE:
            return
        self._auto_update_project_status()
        if self._handle_external_project_change_before_save(
            deepcopy(self.current_project), "项目快照保存", False
        ):
            return
        save_project_file(path, self.current_project)
        self._record_current_project_file_signature(path)
        self._remember_project_path(path)
        self._project_file_dirty = False

    def _persist_candidate_analysis_draft_state(self):
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        self._note_project_dirty()
        try:
            self.current_project["updated_at"] = now_str()
            self._save_draft_snapshot()
            self._dirty = False
        except Exception as e:
            self._log_novel_diagnostic(
                "candidate_state_save_failed",
                level="error",
                project_path=str(getattr(self, "current_project_path", "") or NOVEL_DRAFT_FILE),
                error_category="storage",
                **self._novel_exception_details(e),
            )
            log_debug("小说候选分析草稿保存失败", e)

    def _remember_project_path(self, path):
        remember_project_path(path)

    def save_current_project(self):
        if self._current_background_chapter_runner() is not None:
            self.set_status_tip("当前项目正在后台处理章节，任务结束前不允许从界面覆盖保存。")
            return True
        if self._current_fanqie_upload_worker() is not None:
            self.set_status_tip("当前项目正在番茄批量上传，任务结束前不允许从界面覆盖保存。")
            return True
        self._flush_current_editors()
        self._auto_update_project_status()
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        if not self.current_project_path or self.current_project_path == NOVEL_DRAFT_FILE:
            return self.save_project_as_named()
        try:
            if self._handle_external_project_change_before_save(
                deepcopy(self.current_project), "手动保存", True
            ):
                return True
            save_project_file(self.current_project_path, self.current_project)
            self._record_current_project_file_signature(self.current_project_path)
            self._remember_project_path(self.current_project_path)
            self._save_draft_snapshot()
            self._notify_project_store_changed()
            self._dirty = False
            self._project_file_dirty = False
            self._update_stats_label()
            return True
        except Exception as e:
            self._log_novel_diagnostic(
                "manual_project_save_failed",
                level="error",
                project_path=str(getattr(self, "current_project_path", "") or ""),
                error_category="storage",
                **self._novel_exception_details(e),
            )
            QMessageBox.warning(self, "保存失败", str(e))
            return False

    def save_project_as_named(self):
        self._flush_current_editors()
        self._auto_update_project_status()
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
            self._record_current_project_file_signature(path)
            self._update_stats_label()
            self._dirty = False
            self._project_file_dirty = False
            self._notify_project_store_changed()
            self.set_status_tip(f"已保存：{name}")
            return True
        except Exception as e:
            self._log_novel_diagnostic(
                "named_project_save_failed",
                level="error",
                project_path=str(path or ""),
                error_category="storage",
                **self._novel_exception_details(e),
            )
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
        perf_start = time.perf_counter()
        source_name = os.path.basename(path)
        file_size = ""
        if os.path.exists(path):
            try:
                file_size = os.path.getsize(path)
            except Exception:
                file_size = ""
        self._opening_project = True
        try:
            step_start = time.perf_counter()
            runner = self._background_chapter_runner_for_path(path)
            data = (
                deepcopy(runner.current_project)
                if runner is not None else load_json_file(path, None)
            )
            self._log_novel_perf(
                "切换小说-读取文件",
                step_start,
                threshold_ms=80,
                path=source_name,
                file_size=file_size,
            )
            if not isinstance(data, dict):
                QMessageBox.warning(self, "打开失败", "项目文件无效。")
                return
            saved_before_open = self._has_unsaved_current_work()
            if saved_before_open:
                self._save_current_work(
                    "打开前保存",
                    refresh_project_list=False,
                    preserve_project_mtime=True,
                    update_draft=False,
                )
            self._load_project_data(data, path, defer_helpers=True)
            attached = self._attach_background_chapter_runner(path)
            if not attached and self._current_background_chapter_runner() is None:
                self._sync_completed_background_chapter_plan()
            self._remember_project_path(path)
            self._select_project_list_path(path)
            current_runner = self._current_background_chapter_runner()
            if attached or current_runner is not None:
                self._sync_detached_auto_status(current_runner)
            else:
                self._update_detached_auto_source_lock()
                self.set_status_tip(f"已打开：{os.path.basename(path)}")
            self._log_novel_perf(
                "切换小说-总计",
                perf_start,
                threshold_ms=0,
                path=source_name,
                file_size=file_size,
                saved_before_open=saved_before_open,
                **self._novel_perf_summary(),
            )
        finally:
            self._opening_project = False

    def _apply_creation_wizard_payload(self, data, payload):
        """把新建向导确认的框架写入现有项目字段。

        这里只做新项目初始化，不触碰已有项目的导入、章节规划和正文流程。
        结构化原稿保存在 creation_framework，旧页面继续读取已有兼容字段。
        """
        payload = payload if isinstance(payload, dict) else {}
        framework = payload.get("creation_framework", {})
        framework = deepcopy(framework) if isinstance(framework, dict) else {}
        premise = framework.get("premise", {}) if isinstance(framework.get("premise", {}), dict) else {}
        normalized_framework = normalize_creation_result(
            "bible",
            framework,
            allow_power_levels=story_requires_explicit_power_levels(
                premise,
                framework.get("world_rules", {}),
                framework.get("lore", []),
            ),
            total_words=framework.get("total_words", 500000),
            average_chapter_words=framework.get("average_chapter_words", 3000),
        )
        for key in ("bible", "world_rules", "characters", "lore", "foreshadows"):
            framework[key] = deepcopy(normalized_framework.get(key, {} if key in {"bible", "world_rules"} else []))
        # 旧版本把势力、场景和能力体系放在独立字段；标准化后它们已经
        # 进入 lore，项目里不再保留第二套同义数据。
        for key in ("ability_system", "factions", "relationship_map", "key_scenes"):
            framework.pop(key, None)
        bible = framework.get("bible", {})
        world_rules = framework.get("world_rules", {})
        characters = framework.get("characters", []) if isinstance(framework.get("characters", []), list) else []
        lore = framework.get("lore", []) if isinstance(framework.get("lore", []), list) else []
        foreshadows = framework.get("foreshadows", []) if isinstance(framework.get("foreshadows", []), list) else []
        stage_plan = framework.get("stage_plan", []) if isinstance(framework.get("stage_plan", []), list) else []

        meta = data.setdefault("meta", {})
        title = _safe_name(
            framework.get("novel_name", "") or premise.get("title", "")
        ) or "未命名小说"
        display_meta = creation_meta_display_values(premise)
        meta.update({
            "title": title,
            "genre": display_meta["genre"],
            "style": display_meta["style"],
            "pov": "第三人称",
            "target_words": str(framework.get("total_words", 500000) or 500000),
            "status": "草稿",
            "premise": str(premise.get("synopsis", "") or "").strip(),
        })
        data["bible"] = format_creation_text(
            bible,
            "小说圣经",
            {"main_conflict": "核心动机契约（主线矛盾）"},
        )
        data["world_rules"] = format_creation_text(world_rules, "世界规则")
        data["summary"] = str(premise.get("synopsis", "") or "").strip()
        data["timeline"] = format_creation_preview(
            "stage_plan",
            {
                "stage_skeleton": framework.get("stage_skeleton", []),
                "book_contract": framework.get("book_contract", {}),
                "stage_plan": stage_plan,
                "chapter_plan_note": framework.get("chapter_plan_note", ""),
            },
        )
        data["foreshadows"] = format_creation_text(foreshadows, "长期伏笔")

        normalized_characters = []
        for index, item in enumerate(characters):
            if not isinstance(item, dict):
                continue
            record = _new_character(index)
            record["name"] = str(item.get("name", "") or "").strip() or record["name"]
            record["role"] = str(
                item.get("role", "")
                or item.get("identity", "")
                or item.get("身份", "")
                or item.get("人物身份", "")
            ).strip()
            record["goal"] = str(
                item.get("goal", "")
                or item.get("目标", "")
                or item.get("人物目标", "")
            ).strip()
            record["secret"] = str(
                item.get("secret", "")
                or item.get("秘密", "")
                or item.get("隐藏秘密", "")
            ).strip()
            record["personality"] = str(
                item.get("personality", "")
                or item.get("traits", "")
                or item.get("人物性格", "")
                or item.get("人物特点", "")
                or item.get("性格特点", "")
                or item.get("人物性格/特点", "")
            ).strip()
            record["voice"] = str(
                item.get("voice", "")
                or item.get("language_style", "")
                or item.get("语言风格", "")
                or item.get("说话风格", "")
            ).strip()
            notes = str(item.get("notes", "") or "").strip()
            relationship = str(
                item.get("relationship_to_protagonist", "")
                or item.get("relationship", "")
                or item.get("与主角关系", "")
            ).strip()
            long_term = str(
                item.get("long_term_change", "")
                or item.get("character_arc", "")
                or item.get("长期变化", "")
            ).strip()
            fear = str(
                item.get("fear", "")
                or item.get("fears", "")
                or item.get("害怕失去", "")
            ).strip()
            record["notes"] = "\n".join(
                part for part in (
                    notes,
                    f"害怕失去：{fear}" if fear else "",
                    f"与主角关系：{relationship}" if relationship else "",
                    f"长期变化：{long_term}" if long_term else "",
                ) if part
            )
            normalized_characters.append(record)
        data["characters"] = normalized_characters

        normalized_lore = []
        for index, item in enumerate(lore):
            if not isinstance(item, dict):
                continue
            record = _new_lore(index)
            record["name"] = str(item.get("name", "") or "").strip() or record["name"]
            record["type"] = str(item.get("type", "") or "设定").strip()
            record["description"] = str(item.get("description", "") or "").strip()
            record["story_known"] = str(item.get("story_known", "") or "").strip()
            normalized_lore.append(record)
        data["lore"] = normalized_lore

        normalized_foreshadows = []
        for index, item in enumerate(foreshadows):
            if not isinstance(item, dict):
                continue
            record = _new_foreshadow(index)
            record["name"] = str(item.get("name", "") or "").strip() or record["name"]
            # 向导只负责建立伏笔资料，初始生命周期状态始终从“未埋”开始。
            record["status"] = "未埋"
            record["setup_chapter"] = str(
                item.get("setup_chapter", "") or item.get("setup_stage", "")
            ).strip()
            record["payoff_chapter"] = str(
                item.get("payoff_chapter", "") or item.get("payoff_stage", "")
            ).strip()
            description = str(item.get("description", "") or "").strip()
            for extra in (
                str(item.get("relationship_effect", "") or "").strip(),
                str(item.get("notes", "") or "").strip(),
            ):
                if extra and extra not in description:
                    description = "\n".join(
                        part for part in (description, extra) if part
                    ).strip()
            record["description"] = description
            record["revealed"] = str(item.get("revealed", "") or "").strip()
            record["remaining_secret"] = str(item.get("remaining_secret", "") or "").strip()
            # 向导生成的正式内容已经归入说明；备注只保留给用户手动记录。
            record["notes"] = ""
            normalized_foreshadows.append(record)
        data["foreshadow_items"] = normalized_foreshadows

        data["creation_framework"] = framework
        data["creation_wizard_state"] = deepcopy(payload.get("creation_wizard_state", {}))
        foundation = framework.get("chapter_plan_foundation", {})
        if isinstance(foundation, dict):
            foundation = _normalize_chapter_plan_foundation(foundation)
            data["chapter_plan_foundation"] = deepcopy(foundation)
            profile = _normalize_narrative_strategy_profile(
                foundation.get("narrative_strategy_profile", {})
            )
            contract = _normalize_creative_intent_contract(
                foundation.get("creative_intent_contract", {})
            )
            data["narrative_strategy_profile"] = deepcopy(profile)
            data["creative_intent_contract"] = deepcopy(contract)

            # 向导已经完成叙事策略和十万字阶段边界。
            # 这里只预置“待用户点击章节规划”的确认状态，不发起任何章节 API 调用，
            # 这样现有“AI生成章节规划”按钮会直接进入具体章节提纲生成，避免重复生成同一层规划。
            try:
                target_words = max(1, int(foundation.get("target_words", 0) or 0))
                average_words = max(1, int(foundation.get("average_chapter_words", 0) or 0))
                total_chapters = max(1, int(foundation.get("total_chapter_count", 0) or 0))
            except Exception:
                target_words = average_words = total_chapters = 0
            if target_words and average_words and total_chapters and foundation.get("arcs") and profile:
                data["chapter_plan_generation_state"] = {
                    "version": _CHAPTER_PLAN_BATCH_STATE_VERSION,
                    "status": "pending",
                    "target_words": target_words,
                    "average_chapter_words": average_words,
                    "total_chapter_count": total_chapters,
                    "existing_chapter_count": 0,
                    "requested_chapter_count": total_chapters,
                    "batch_size": _CHAPTER_PLAN_BATCH_SIZE,
                    "master_plan": deepcopy(foundation),
                    "chapters": [],
                    "creative_intent_contract": deepcopy(contract),
                    "profile_confirmed": True,
                    "started_at": now_str(),
                }
        return data

    def _ensure_creation_wizard_workspace(self):
        workspace = self._creation_wizard_workspace
        if workspace is None:
            workspace = NovelCreationWorkspaceDialog(
                open_draft_ids=lambda: set(self._creation_wizard_dialogs),
                parent=self,
            )
            workspace.new_draft_requested.connect(self._create_creation_wizard_draft)
            workspace.draft_open_requested.connect(self._open_creation_wizard_draft)
            self._creation_wizard_workspace = workspace
        return workspace

    def _create_creation_wizard_draft(self):
        draft_id = create_creation_wizard_draft()
        workspace = self._ensure_creation_wizard_workspace()
        workspace.refresh()
        workspace.show()
        workspace.raise_()
        workspace.activateWindow()
        self.set_status_tip("已创建创作项目，请在项目管理界面中选中它并打开向导。")

    def _open_creation_wizard_draft(self, draft_id):
        draft_id = str(draft_id or "").strip()
        if not draft_id:
            return
        workspace = self._ensure_creation_wizard_workspace()
        workspace.hide()
        existing = self._creation_wizard_dialogs.get(draft_id)
        if existing is not None:
            existing.showNormal()
            existing.raise_()
            existing.activateWindow()
            return
        dialog = NovelCreationWizardDialog(
            self._current_novel_ai_selection,
            parent=self,
            draft_id=draft_id,
        )
        self._creation_wizard_dialogs[draft_id] = dialog
        dialog.draft_saved.connect(
            lambda _draft_id: self._ensure_creation_wizard_workspace().refresh()
        )
        dialog.finished.connect(
            lambda result, wizard=dialog: self._on_creation_wizard_finished(wizard, result)
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        workspace.refresh()

    def _on_creation_wizard_finished(self, dialog, result):
        draft_id = str(getattr(dialog, "draft_id", "") or "").strip()
        if draft_id:
            self._creation_wizard_dialogs.pop(draft_id, None)
        if result != QDialog.Accepted:
            workspace = self._ensure_creation_wizard_workspace()
            workspace.refresh()
            if not self._creation_wizard_dialogs:
                workspace.show()
                workspace.raise_()
                workspace.activateWindow()
            dialog.deleteLater()
            return
        try:
            self._save_current_work("新建前保存")
            wizard_payload = dialog.result_payload()
            data = self._apply_creation_wizard_payload(_default_project(), wizard_payload)
            project_title = (
                data.get("meta", {}).get("title", "")
                if isinstance(data.get("meta"), dict)
                else ""
            )
            project_path = unique_project_path(project_title or "未命名小说")
            save_project_file(project_path, data)
            self._load_project_data(data, project_path)
            self._remember_project_path(project_path)
            self._save_draft_snapshot()
            self._notify_project_store_changed()
        except Exception as exc:
            log_debug("新建向导项目保存失败", exc)
            QMessageBox.warning(self, "新建项目失败", f"项目保存失败：{exc}\n向导草稿仍然保留，可以稍后继续。")
            workspace = self._ensure_creation_wizard_workspace()
            workspace.refresh()
            workspace.show()
            workspace.raise_()
            workspace.activateWindow()
            dialog.deleteLater()
            return
        archive_error = ""
        try:
            archived_path = mark_creation_wizard_draft_completed(
                draft_id,
                project_path,
                wizard_payload,
            )
            if not archived_path:
                archive_error = "没有找到向导草稿文件"
        except Exception as exc:
            archive_error = str(exc)
        self._ensure_creation_wizard_workspace().refresh()
        dialog.deleteLater()
        self._update_stats_label()
        if archive_error:
            log_debug("新建向导完成记录保存失败", archive_error)
            self.set_status_tip(
                "项目已保存，但向导完成记录保存失败；请检查历史目录。"
            )
        else:
            self.set_status_tip(
                "已完成创作框架向导并保存到项目列表；向导资料已保留。"
                "请到“章节”页面手动点击“AI生成章节规划”。"
            )

    def new_project(self):
        workspace = self._ensure_creation_wizard_workspace()
        workspace.refresh()
        workspace.show()
        workspace.raise_()
        workspace.activateWindow()

    def _set_volume_two_running(self, running):
        button = getattr(self, "create_volume_two_btn", None)
        if button is None:
            return
        button.setEnabled(not running)
        button.setText("正在创建新卷续写..." if running else "创建新卷续写")

    def _volume_two_parent_is_current(self):
        pending = getattr(self, "_volume_two_pending", {}) or {}
        expected_path = os.path.abspath(str(pending.get("source_path", "") or ""))
        current_path = os.path.abspath(str(getattr(self, "current_project_path", "") or ""))
        if not expected_path or expected_path != current_path:
            return False
        expected_hash = str(pending.get("source_hash", "") or "").strip()
        if not expected_hash:
            return True
        try:
            current_source = _build_volume_handoff_source(self.current_project)
            current_hash = hashlib.sha256(
                json.dumps(current_source, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            return current_hash == expected_hash
        except Exception:
            return False

    @staticmethod
    def _volume_two_resume_path(source_path):
        normalized_path = os.path.abspath(str(source_path or "").strip())
        if not normalized_path:
            return ""
        path_key = hashlib.sha256(normalized_path.encode("utf-8", errors="replace")).hexdigest()[:32]
        return os.path.join(
            HISTORY_DIR,
            "novel_volume_resume",
            f"{path_key}.json",
        )

    def _load_volume_two_resume(self, source_path, source_hash):
        path = self._volume_two_resume_path(source_path)
        if not path:
            return {}
        payload = load_json_file(path, {})
        if not isinstance(payload, dict):
            return {}
        expected_path = os.path.abspath(str(source_path or ""))
        saved_path = os.path.abspath(str(payload.get("source_path", "") or ""))
        expected_hash = str(source_hash or "").strip()
        saved_hash = str(payload.get("source_hash", "") or "").strip()
        if expected_path != saved_path or not expected_hash or expected_hash != saved_hash:
            try:
                os.remove(path)
            except Exception:
                pass
            payload = {}
        else:
            return payload

        # Migrate a successful handoff written by the diagnostic version that
        # existed before restart persistence. The request body hash prevents a
        # stale handoff from being reused after the first-volume project changed.
        latest_path = os.path.join(
            HISTORY_DIR,
            "novel_diagnostics",
            "latest_model_exchange.json",
        )
        latest = load_json_file(latest_path, {})
        if not isinstance(latest, dict):
            return {}
        if str(latest.get("stage", "") or "").strip() != "handoff":
            return {}
        if str(latest.get("outcome", "") or "").strip().lower() != "success":
            return {}
        if os.path.abspath(str(latest.get("project_path", "") or "")) != expected_path:
            return {}
        saved_user_context = str(latest.get("user_context", "") or "")
        if not saved_user_context:
            return {}
        try:
            from .workers import NovelVolumeHandoffWorker

            verifier = NovelVolumeHandoffWorker("", "", "", self._current_volume_handoff_source())
            expected_user_context = verifier._chunk_user_text("", 1, 1)
        except Exception:
            return {}
        if hashlib.sha256(saved_user_context.encode("utf-8", errors="replace")).hexdigest() != hashlib.sha256(
            expected_user_context.encode("utf-8", errors="replace")
        ).hexdigest():
            return {}
        try:
            handoff = json.loads(str(latest.get("partial_output", "") or ""))
        except Exception:
            return {}
        if not isinstance(handoff, dict) or not handoff:
            return {}
        migrated = {
            "schema_version": 1,
            "stage": "handoff_ready",
            "source_path": expected_path,
            "source_hash": expected_hash,
            "source_meta": {},
            "handoff": handoff,
            "setup": {},
            "creative_intent_contract": {},
            "framework": {},
            "model": str(latest.get("model", "") or "").strip(),
            "created_at": str(latest.get("saved_at", "") or now_str()),
            "updated_at": now_str(),
        }
        save_json_file(path, migrated)
        return migrated

    def _current_volume_handoff_source(self):
        return _build_volume_handoff_source(deepcopy(self.current_project))

    def _save_volume_two_resume(self, stage):
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        source_path = str(pending.get("source_path", "") or "").strip()
        source_hash = str(pending.get("source_hash", "") or "").strip()
        path = self._volume_two_resume_path(source_path)
        if not path or not source_hash:
            return ""
        existing = load_json_file(path, {})
        existing = existing if isinstance(existing, dict) else {}
        source_meta = pending.get("source_meta", {})
        if not isinstance(source_meta, dict):
            source_snapshot = pending.get("source_snapshot", {})
            source_snapshot = source_snapshot if isinstance(source_snapshot, dict) else {}
            source_meta = source_snapshot.get("meta", {})
        payload = {
            "schema_version": 1,
            "stage": str(stage or "pending"),
            "source_path": os.path.abspath(source_path),
            "source_hash": source_hash,
            "model": str(getattr(self, "_volume_two_model", "") or "").strip(),
            "source_meta": deepcopy(source_meta if isinstance(source_meta, dict) else {}),
            "handoff": deepcopy(pending.get("handoff", {}))
            if isinstance(pending.get("handoff", {}), dict) else {},
            "setup": deepcopy(pending.get("setup", {}))
            if isinstance(pending.get("setup", {}), dict) else {},
            "creative_intent_contract": deepcopy(
                pending.get("creative_intent_contract", {})
            ) if isinstance(pending.get("creative_intent_contract", {}), dict) else {},
            "framework": deepcopy(pending.get("framework", {}))
            if isinstance(pending.get("framework", {}), dict) else {},
            "created_at": str(existing.get("created_at", "") or now_str()),
            "updated_at": now_str(),
        }
        save_json_file(path, payload)
        return path if os.path.exists(path) else ""

    def _remove_volume_two_resume(self, source_path):
        path = self._volume_two_resume_path(source_path)
        if not path:
            return
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except Exception as exc:
            log_debug("清理新卷续写恢复状态失败", exc)

    def _clear_volume_two_pending(self, remove_resume=True):
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        source_path = str(
            pending.get("source_path", "")
            or getattr(self, "_volume_two_source_path", "")
            or ""
        ).strip()
        if remove_resume and source_path:
            self._remove_volume_two_resume(source_path)
        self._volume_two_pending = {}
        self._volume_two_source_path = ""
        self._volume_two_source_hash = ""
        self._volume_two_model = ""
        self._volume_two_template_hash = ""
        self._set_volume_two_running(False)

    def _volume_signal_worker(self, attribute_name):
        worker = None
        try:
            candidate = self.sender()
            if candidate is not None and hasattr(candidate, "diagnostics"):
                worker = candidate
        except Exception:
            worker = None
        if worker is None:
            worker = getattr(self, attribute_name, None)
        return worker

    def _save_volume_diagnostic(
        self, stage, outcome, error="", result=None, worker=None
    ):
        if not getattr(self, "_novel_diagnostics_enabled", False):
            return ""
        worker_attribute = {
            "handoff": "volume_handoff_worker",
            "intent": "volume_intent_worker",
            "framework": "volume_framework_worker",
            "framework_alignment": "volume_framework_audit_worker",
        }.get(str(stage or ""), "volume_framework_worker")
        worker = worker or self._volume_signal_worker(worker_attribute)
        diagnostics = getattr(worker, "diagnostics", {}) if worker is not None else {}
        diagnostics = deepcopy(diagnostics) if isinstance(diagnostics, dict) else {}
        request_id = str(
            getattr(worker, "diagnostic_request_id", "") if worker is not None else ""
        ).strip() or self._next_novel_diagnostic_request_id(f"volume-{stage}")
        provider = getattr(worker, "diagnostic_provider", {}) if worker is not None else {}
        provider = provider if isinstance(provider, dict) else {}
        project_path = str(
            getattr(worker, "diagnostic_project_path", "") if worker is not None else ""
        ).strip() or str(getattr(self, "current_project_path", "") or "")
        project_title = str(
            getattr(worker, "diagnostic_project_title", "") if worker is not None else ""
        ).strip()
        if not project_title:
            project = self.current_project if isinstance(getattr(self, "current_project", None), dict) else {}
            project_title = str(project.get("meta", {}).get("title", "") or "") if isinstance(project.get("meta"), dict) else ""
        system_prompt = str(getattr(worker, "last_system_prompt", "") or "") if worker is not None else ""
        user_context = str(getattr(worker, "last_user_text", "") or "") if worker is not None else ""
        partial_output = str(getattr(worker, "last_partial_output", "") or "") if worker is not None else ""
        if result is not None:
            try:
                partial_output = json.dumps(result, ensure_ascii=False, indent=2)
            except Exception:
                partial_output = str(result or "")
        error_text = clean_error_text(error) if error else str(diagnostics.get("error", "") or "")
        traceback_text = str(diagnostics.get("traceback", "") or "")
        payload = {
            "request_id": request_id,
            "stage": str(stage or ""),
            "outcome": str(outcome or "unknown"),
            "error": error_text,
            "error_type": str(diagnostics.get("error_type", "") or ""),
            "traceback": traceback_text,
            "project_title": project_title,
            "project_path": project_path,
            "provider_id": str(provider.get("id", "") or ""),
            "provider_name": str(provider.get("name", "") or ""),
            "model": str(getattr(worker, "model", "") if worker is not None else ""),
            "worker_diagnostics": diagnostics,
            "http_status": int(
                diagnostics.get("http_status", diagnostics.get("last_http_status", 0)) or 0
            ),
            "response_headers": deepcopy(
                diagnostics.get("response_headers", diagnostics.get("last_response_headers", {}))
            ) if isinstance(
                diagnostics.get("response_headers", diagnostics.get("last_response_headers", {})),
                dict,
            ) else {},
            "attempts": deepcopy(diagnostics.get("attempts", []))
            if isinstance(diagnostics.get("attempts", []), list) else [],
            "reasoning_chars": int(diagnostics.get("reasoning_chars", 0) or 0),
            "content_chars": int(diagnostics.get("content_chars", 0) or 0),
            "context_metrics": {
                "system_prompt_chars": len(system_prompt),
                "user_context_chars": len(user_context),
                "user_context_utf8_bytes": len(user_context.encode("utf-8", errors="replace")),
                "partial_output_chars": len(partial_output),
            },
            "system_prompt": system_prompt,
            "user_context": user_context,
            "sent_user_context": user_context,
            "partial_output": partial_output,
        }
        if str(outcome or "").lower() == "error":
            path = save_novel_diagnostic_snapshot(request_id, payload)
        else:
            path = save_novel_diagnostic_latest_exchange(request_id, payload)
        outcome_key = str(outcome or "unknown").lower()
        event_name = (
            f"volume_{stage}_request_finished" if outcome_key == "success"
            else f"volume_{stage}_request_failed" if outcome_key == "error"
            else f"volume_{stage}_request_{outcome_key}"
        )
        self._log_novel_diagnostic(
            event_name,
            level="error" if str(outcome or "").lower() == "error" else "info",
            action=f"volume_{stage}",
            request_id=request_id,
            model=str(getattr(worker, "model", "") if worker is not None else ""),
            provider=provider,
            stage=str(stage or ""),
            outcome=str(outcome or "unknown"),
            error=error_text,
            worker_diagnostics=diagnostics,
            diagnostic_snapshot=path,
            context_metrics=payload["context_metrics"],
        )
        return path

    def _show_volume_two_setup_dialog(self):
        if not self._volume_two_parent_is_current():
            self._clear_volume_two_pending()
            self.set_status_tip("上一卷已切换或发生变化，无法恢复本卷续写流程。")
            return
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        source_meta = deepcopy(pending.get("source_meta", {}))
        source_continuation = _normalize_series_continuation(
            (pending.get("source_snapshot", {}) if isinstance(pending.get("source_snapshot", {}), dict) else {}).get(
                "series_continuation", {}
            )
        )
        try:
            source_meta["_next_volume_number"] = int(source_continuation.get("volume_number", 1) or 1) + 1
        except Exception:
            source_meta["_next_volume_number"] = 2
        dialog = VolumeTwoSetupDialog(
            source_meta,
            pending.get("handoff", {}),
            self,
            setup=pending.get("setup", {}),
        )
        if dialog.exec() != QDialog.Accepted:
            self._clear_volume_two_pending()
            self.set_status_tip("已取消创建新卷续写；上一卷未发生变化。")
            return
        setup = dialog.request_data()
        pending["setup"] = setup
        pending["creative_intent_contract"] = {}
        pending["framework"] = {}
        self._volume_two_pending = pending
        self._save_volume_two_resume("intent_pending")
        self._start_volume_intent_worker(setup)

    def _show_volume_two_intent_dialog(self, contract):
        if not self._volume_two_parent_is_current():
            self._clear_volume_two_pending()
            self.set_status_tip("上一卷已切换或发生变化，无法恢复本卷创作意图。")
            return
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        dialog = VolumeCreativeIntentDialog(contract, self)
        if dialog.exec() != QDialog.Accepted:
            self._set_volume_two_running(False)
            self._save_volume_two_resume("intent_ready")
            self.set_status_tip("本卷创作意图尚未确认；再次点击“创建新卷续写”可继续。")
            return
        confirmed = dialog.confirmed_contract()
        confirmed["confirmed_at"] = now_str()
        pending["creative_intent_contract"] = _normalize_creative_intent_contract(confirmed)
        pending["framework"] = {}
        self._volume_two_pending = pending
        self._save_volume_two_resume("intent_confirmed")
        self._start_volume_framework_worker(pending.get("setup", {}))

    def _start_volume_intent_worker(self, setup):
        if not self._volume_two_parent_is_current():
            self._clear_volume_two_pending()
            self.set_status_tip("上一卷已切换或发生变化，已停止本卷创作意图分析。")
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self._set_volume_two_running(False)
            self.set_ai_settings_expanded(True)
            QMessageBox.warning(self, "无法理解本卷要求", error)
            return
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        setup = setup if isinstance(setup, dict) else {}
        self._volume_two_model = str(model or "")
        self.volume_intent_worker = NovelVolumeIntentWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            setup.get("meta", {}) if isinstance(setup.get("meta", {}), dict) else {},
            str(setup.get("requirements", "") or ""),
            pending.get("handoff", {}) if isinstance(pending.get("handoff", {}), dict) else {},
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
        )
        self.volume_intent_worker.diagnostic_request_id = self._next_novel_diagnostic_request_id(
            "volume-intent"
        )
        self.volume_intent_worker.diagnostic_stage = "intent"
        self.volume_intent_worker.diagnostic_project_path = str(
            pending.get("source_path", "") or getattr(self, "current_project_path", "") or ""
        )
        self.volume_intent_worker.diagnostic_project_title = str(
            (setup.get("meta", {}) if isinstance(setup.get("meta", {}), dict) else {}).get("title", "") or ""
        ).strip()
        self.volume_intent_worker.diagnostic_provider = {
            "id": str(provider.get("id", "") or ""),
            "name": str(provider.get("name", "") or ""),
        }
        self._save_volume_two_resume("intent_running")
        self._connect_novel_worker_status(self.volume_intent_worker)
        self.volume_intent_worker.result_ready.connect(self.on_volume_intent_ready)
        self.volume_intent_worker.failed.connect(self.on_volume_intent_failed)
        self.volume_intent_worker.finished.connect(self._cleanup_volume_intent_worker)
        self.set_status_tip("正在理解本卷用户要求...")
        self.volume_intent_worker.start()

    def on_volume_intent_ready(self, contract):
        worker = self._volume_signal_worker("volume_intent_worker")
        self._save_volume_diagnostic("intent", "success", result=contract, worker=worker)
        if not self._volume_two_parent_is_current():
            self._clear_volume_two_pending()
            return
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        pending["creative_intent_contract"] = _normalize_creative_intent_contract(contract)
        pending["framework"] = {}
        self._volume_two_pending = pending
        self._save_volume_two_resume("intent_ready")
        self._set_volume_two_running(False)
        self._show_volume_two_intent_dialog(pending["creative_intent_contract"])

    def on_volume_intent_failed(self, error):
        worker = self._volume_signal_worker("volume_intent_worker")
        self._save_volume_diagnostic("intent", "error", error=error, worker=worker)
        message = clean_error_text(error)
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        setup = pending.get("setup", {}) if isinstance(pending.get("setup", {}), dict) else {}
        self._set_volume_two_running(False)
        self._save_volume_two_resume("intent_failed")
        if setup:
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Warning)
            dialog.setWindowTitle("本卷创作意图分析失败")
            dialog.setText(message or "本卷创作意图分析失败。")
            retry_button = dialog.addButton("重试", QMessageBox.AcceptRole)
            dialog.addButton("取消", QMessageBox.RejectRole)
            dialog.exec()
            if dialog.clickedButton() is retry_button:
                self._set_volume_two_running(True)
                self._start_volume_intent_worker(setup)
                return
        self._clear_volume_two_pending()
        self.set_status_tip(f"本卷创作意图分析失败：{message[:100]}")

    def _cleanup_volume_intent_worker(self):
        worker = self.sender()

        def cleanup():
            try:
                if self.volume_intent_worker is worker:
                    self.volume_intent_worker = None
                if worker is not None:
                    worker.deleteLater()
            except Exception as exc:
                log_debug("本卷创作意图线程清理失败", exc)

        QTimer.singleShot(0, cleanup)

    def _show_volume_two_framework_dialog(self, framework):
        if not self._volume_two_parent_is_current():
            self._clear_volume_two_pending()
            self.set_status_tip("上一卷已切换或发生变化，无法恢复本卷框架。")
            return
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        setup = pending.get("setup", {}) if isinstance(pending.get("setup", {}), dict) else {}
        framework = deepcopy(framework if isinstance(framework, dict) else {})
        framework_meta = framework.setdefault("meta", {})
        if not isinstance(framework_meta, dict):
            framework_meta = {}
            framework["meta"] = framework_meta
        setup_meta = setup.get("meta", {}) if isinstance(setup.get("meta", {}), dict) else {}
        for key in ("title", "genre", "style", "pov", "target_words"):
            if not str(framework_meta.get(key, "") or "").strip():
                framework_meta[key] = str(setup_meta.get(key, "") or "").strip()
        framework_meta["status"] = "草稿"
        framework["creative_intent_contract"] = deepcopy(
            pending.get("creative_intent_contract", {})
        )
        pending["framework"] = deepcopy(framework)
        self._volume_two_pending = pending
        self._save_volume_two_resume("framework_ready")
        dialog = VolumeTwoFrameworkDialog(
            framework,
            pending.get("handoff", {}),
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            self._clear_volume_two_pending()
            self.set_status_tip("已取消创建新卷续写；上一卷未发生变化。")
            return
        confirmed = dialog.confirmed_framework()
        self._create_second_volume_project(confirmed)

    def create_second_volume(self):
        handoff_worker = getattr(self, "volume_handoff_worker", None)
        intent_worker = getattr(self, "volume_intent_worker", None)
        framework_worker = getattr(self, "volume_framework_worker", None)
        audit_worker = getattr(self, "volume_framework_audit_worker", None)
        if (
            (handoff_worker is not None and handoff_worker.isRunning())
            or (intent_worker is not None and intent_worker.isRunning())
            or (framework_worker is not None and framework_worker.isRunning())
            or (audit_worker is not None and audit_worker.isRunning())
        ):
            self.set_status_tip("新卷续写流程正在进行，请稍等。")
            return
        if not self._has_saved_project_path():
            QMessageBox.warning(
                self,
                "无法创建新卷续写",
                "请先保存当前项目。这样才能保证上一卷不会被本卷流程覆盖或污染。",
            )
            return
        self._flush_current_editors()
        if not self._save_current_work("生成上一卷交接摘要", refresh_project_list=True):
            QMessageBox.warning(self, "无法创建新卷续写", "当前项目保存失败，已停止新卷续写。")
            return
        source_context = _build_volume_handoff_source(deepcopy(self.current_project))
        source_catalog = _build_volume_handoff_record_catalog(deepcopy(self.current_project))
        source_path = str(self.current_project_path or "").strip()
        source_hash = hashlib.sha256(
            json.dumps(source_context, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        resume = self._load_volume_two_resume(source_path, source_hash)
        resume_handoff = resume.get("handoff", {}) if isinstance(resume.get("handoff", {}), dict) else {}
        if resume_handoff:
            source_meta = resume.get("source_meta", {})
            self._volume_two_pending = {
                "source_path": source_path,
                "source_hash": source_hash,
                "source_snapshot": deepcopy(self.current_project),
                "source_context": source_context,
                "source_meta": deepcopy(source_meta if isinstance(source_meta, dict) else self.current_project.get("meta", {})),
                "handoff": deepcopy(resume_handoff),
                "setup": deepcopy(resume.get("setup", {}))
                if isinstance(resume.get("setup", {}), dict) else {},
                "creative_intent_contract": deepcopy(resume.get("creative_intent_contract", {}))
                if isinstance(resume.get("creative_intent_contract", {}), dict) else {},
                "framework": deepcopy(resume.get("framework", {}))
                if isinstance(resume.get("framework", {}), dict) else {},
            }
            self._volume_two_source_path = source_path
            self._volume_two_source_hash = source_hash
            self._volume_two_model = str(resume.get("model", "") or "").strip()
            self._set_volume_two_running(True)
            framework = self._volume_two_pending.get("framework", {})
            if isinstance(framework, dict) and framework:
                resume_stage = str(resume.get("stage", "") or "").strip()
                if resume_stage == "framework_ready":
                    self.set_status_tip("已恢复完成的本卷框架，未重复调用API。")
                    self._show_volume_two_framework_dialog(framework)
                else:
                    self.set_status_tip("已恢复本卷框架，正在重新执行主线对齐检查。")
                    self._start_volume_framework_audit_worker()
                return
            setup = self._volume_two_pending.get("setup", {})
            intent = self._volume_two_pending.get("creative_intent_contract", {})
            if isinstance(intent, dict) and intent:
                if str(resume.get("stage", "") or "").strip() == "intent_ready":
                    self._set_volume_two_running(False)
                    self._show_volume_two_intent_dialog(intent)
                    return
                self.set_status_tip("已恢复本卷创作意图，正在重试框架生成。")
                self._start_volume_framework_worker(setup)
                return
            if isinstance(setup, dict) and setup:
                self.set_status_tip("已恢复本卷要求，正在重新理解创作意图。")
                self._start_volume_intent_worker(setup)
                return
            self.set_status_tip("已恢复上一卷交接摘要，等待填写本卷要求。")
            self._show_volume_two_setup_dialog()
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self.set_ai_settings_expanded(True)
            QMessageBox.warning(self, "无法创建新卷续写", error)
            return
        self._volume_two_pending = {
            "source_path": source_path,
            "source_hash": source_hash,
            "source_snapshot": deepcopy(self.current_project),
            "source_context": source_context,
            "source_meta": deepcopy(self.current_project.get("meta", {})),
        }
        self._save_volume_two_resume("handoff_pending")
        self._volume_two_source_path = source_path
        self._volume_two_source_hash = source_hash
        self._volume_two_model = str(model or "")
        self._set_volume_two_running(True)
        self.volume_handoff_worker = NovelVolumeHandoffWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            source_context,
            source_catalog,
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
        )
        self.volume_handoff_worker.diagnostic_request_id = self._next_novel_diagnostic_request_id(
            "volume-handoff"
        )
        self.volume_handoff_worker.diagnostic_stage = "handoff"
        self.volume_handoff_worker.diagnostic_project_path = source_path
        self.volume_handoff_worker.diagnostic_project_title = str(
            (self.current_project.get("meta", {}) if isinstance(self.current_project.get("meta", {}), dict) else {}).get("title", "") or ""
        ).strip()
        self.volume_handoff_worker.diagnostic_provider = {
            "id": str(provider.get("id", "") or ""),
            "name": str(provider.get("name", "") or ""),
        }
        self._log_novel_diagnostic(
            "volume_handoff_request_started",
            action="volume_handoff",
            request_id=self.volume_handoff_worker.diagnostic_request_id,
            model=model,
            provider=provider,
            stage="handoff",
            source_chars=len(json.dumps(source_context, ensure_ascii=False)),
            source_utf8_bytes=len(json.dumps(source_context, ensure_ascii=False).encode("utf-8", errors="replace")),
        )
        self._connect_novel_worker_status(self.volume_handoff_worker)
        self.volume_handoff_worker.result_ready.connect(self.on_volume_handoff_ready)
        self.volume_handoff_worker.failed.connect(self.on_volume_handoff_failed)
        self.volume_handoff_worker.finished.connect(self._cleanup_volume_handoff_worker)
        self.set_status_tip("正在生成上一卷交接摘要...")
        self.volume_handoff_worker.start()

    def on_volume_handoff_ready(self, handoff):
        worker = self._volume_signal_worker("volume_handoff_worker")
        self._save_volume_diagnostic("handoff", "success", result=handoff, worker=worker)
        if not self._volume_two_parent_is_current():
            self._clear_volume_two_pending()
            self.set_status_tip("上一卷已切换或发生变化，已丢弃本次本卷交接结果。")
            return
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        handoff = deepcopy(handoff if isinstance(handoff, dict) else {})
        pending["handoff"] = handoff
        pending["framework"] = {}
        self._volume_two_pending = pending
        self._save_volume_two_resume("handoff_ready")
        self._show_volume_two_setup_dialog()

    def on_volume_handoff_failed(self, error):
        worker = self._volume_signal_worker("volume_handoff_worker")
        self._save_volume_diagnostic("handoff", "error", error=error, worker=worker)
        message = clean_error_text(error)
        self._clear_volume_two_pending()
        self.set_status_tip(f"上一卷交接摘要生成失败：{message[:100]}")
        QMessageBox.warning(self, "新卷续写失败", message)

    def _start_volume_framework_worker(self, setup):
        if not self._volume_two_parent_is_current():
            self._clear_volume_two_pending()
            self.set_status_tip("上一卷已切换或发生变化，已停止本卷框架生成。")
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self._clear_volume_two_pending()
            self.set_ai_settings_expanded(True)
            QMessageBox.warning(self, "无法生成本卷框架", error)
            return
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        self._set_volume_two_running(True)
        handoff = pending.get("handoff", {})
        requirements = str((setup or {}).get("requirements", "") or "").strip()
        template_text = _volume_two_framework_template_text()
        self._volume_two_model = str(model or "")
        self._volume_two_template_hash = hashlib.sha256(template_text.encode("utf-8")).hexdigest()
        self.volume_framework_worker = NovelVolumeFrameworkWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            handoff,
            requirements,
            template_text,
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
            setup.get("meta", {}) if isinstance(setup, dict) else {},
            pending.get("creative_intent_contract", {})
            if isinstance(pending.get("creative_intent_contract", {}), dict) else {},
        )
        self.volume_framework_worker.diagnostic_request_id = self._next_novel_diagnostic_request_id(
            "volume-framework"
        )
        self.volume_framework_worker.diagnostic_stage = "framework"
        self.volume_framework_worker.diagnostic_project_path = str(
            pending.get("source_path", "") or getattr(self, "current_project_path", "") or ""
        )
        self.volume_framework_worker.diagnostic_project_title = str(
            (setup.get("meta", {}) if isinstance(setup.get("meta", {}), dict) else {}).get("title", "") or ""
        ).strip()
        self.volume_framework_worker.diagnostic_provider = {
            "id": str(provider.get("id", "") or ""),
            "name": str(provider.get("name", "") or ""),
        }
        self._log_novel_diagnostic(
            "volume_framework_request_started",
            action="volume_framework",
            request_id=self.volume_framework_worker.diagnostic_request_id,
            model=model,
            provider=provider,
            stage="framework",
            handoff_chars=len(json.dumps(handoff, ensure_ascii=False)),
            requirements_chars=len(requirements),
            template_chars=len(template_text),
        )
        self._save_volume_two_resume("framework_running")
        self._connect_novel_worker_status(self.volume_framework_worker)
        self.volume_framework_worker.result_ready.connect(self.on_volume_framework_ready)
        self.volume_framework_worker.failed.connect(self.on_volume_framework_failed)
        self.volume_framework_worker.finished.connect(self._cleanup_volume_framework_worker)
        self.set_status_tip("正在根据交接摘要、用户要求和小说模板生成本卷框架...")
        self.volume_framework_worker.start()

    def on_volume_framework_ready(self, framework):
        worker = self._volume_signal_worker("volume_framework_worker")
        self._save_volume_diagnostic("framework", "success", result=framework, worker=worker)
        if not self._volume_two_parent_is_current():
            self._clear_volume_two_pending()
            return
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        pending["framework"] = deepcopy(framework if isinstance(framework, dict) else {})
        self._volume_two_pending = pending
        self._save_volume_two_resume("framework_audit_pending")
        self._start_volume_framework_audit_worker()

    def _start_volume_framework_audit_worker(self):
        if not self._volume_two_parent_is_current():
            self._clear_volume_two_pending()
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self._set_volume_two_running(False)
            self._show_volume_two_framework_dialog(
                self._volume_two_pending.get("framework", {})
                if isinstance(self._volume_two_pending, dict) else {}
            )
            return
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        self._set_volume_two_running(True)
        setup = pending.get("setup", {}) if isinstance(pending.get("setup", {}), dict) else {}
        framework = pending.get("framework", {}) if isinstance(pending.get("framework", {}), dict) else {}
        self.volume_framework_audit_worker = NovelVolumeFrameworkAlignmentWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            framework,
            pending.get("creative_intent_contract", {})
            if isinstance(pending.get("creative_intent_contract", {}), dict) else {},
            str(setup.get("requirements", "") or ""),
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
        )
        self.volume_framework_audit_worker.diagnostic_request_id = self._next_novel_diagnostic_request_id(
            "volume-framework-alignment"
        )
        self.volume_framework_audit_worker.diagnostic_stage = "framework_alignment"
        self.volume_framework_audit_worker.diagnostic_project_path = str(
            pending.get("source_path", "") or getattr(self, "current_project_path", "") or ""
        )
        self.volume_framework_audit_worker.diagnostic_project_title = str(
            (setup.get("meta", {}) if isinstance(setup.get("meta", {}), dict) else {}).get("title", "") or ""
        ).strip()
        self.volume_framework_audit_worker.diagnostic_provider = {
            "id": str(provider.get("id", "") or ""),
            "name": str(provider.get("name", "") or ""),
        }
        self._save_volume_two_resume("framework_audit_running")
        self._connect_novel_worker_status(self.volume_framework_audit_worker)
        self.volume_framework_audit_worker.result_ready.connect(self.on_volume_framework_audit_ready)
        self.volume_framework_audit_worker.failed.connect(self.on_volume_framework_audit_failed)
        self.volume_framework_audit_worker.finished.connect(self._cleanup_volume_framework_audit_worker)
        self.set_status_tip("正在检查本卷框架是否执行已确认的创作主线...")
        self.volume_framework_audit_worker.start()

    def on_volume_framework_audit_ready(self, alignment):
        worker = self._volume_signal_worker("volume_framework_audit_worker")
        self._save_volume_diagnostic(
            "framework_alignment", "success", result=alignment, worker=worker
        )
        if not self._volume_two_parent_is_current():
            self._clear_volume_two_pending()
            return
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        framework = pending.get("framework", {}) if isinstance(pending.get("framework", {}), dict) else {}
        alignment = alignment if isinstance(alignment, dict) else {}
        patch_meta = alignment.get("meta", {}) if isinstance(alignment.get("meta", {}), dict) else {}
        if str(patch_meta.get("premise", "") or "").strip():
            framework.setdefault("meta", {})["premise"] = str(patch_meta["premise"]).strip()
        patch_plan = alignment.get("chapter_plan", {})
        if isinstance(patch_plan, dict) and patch_plan:
            original_plan = framework.get("chapter_plan", {})
            original_plan = deepcopy(original_plan) if isinstance(original_plan, dict) else {}
            for key in ("summary", "stages"):
                if key not in patch_plan:
                    continue
                if key == "summary" and str(patch_plan.get(key, "") or "").strip():
                    original_plan[key] = str(patch_plan.get(key) or "").strip()
                elif key == "stages" and isinstance(patch_plan.get(key), list) and patch_plan.get(key):
                    original_plan[key] = deepcopy(patch_plan[key])
            original_plan["chapters"] = []
            framework["chapter_plan"] = original_plan
        pending["framework"] = framework
        self._volume_two_pending = pending
        self._save_volume_two_resume("framework_ready")
        self._show_volume_two_framework_dialog(framework)

    def on_volume_framework_audit_failed(self, error):
        worker = self._volume_signal_worker("volume_framework_audit_worker")
        self._save_volume_diagnostic(
            "framework_alignment", "error", error=error, worker=worker
        )
        message = clean_error_text(error)
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        framework = pending.get("framework", {}) if isinstance(pending.get("framework", {}), dict) else {}
        self._save_volume_two_resume("framework_audit_failed")
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("本卷框架对齐检查失败")
        dialog.setText(message or "框架对齐检查失败。")
        dialog.setInformativeText("已保留原始框架。可以重试对齐检查，也可以直接打开框架确认窗口。")
        retry_button = dialog.addButton("重试对齐检查", QMessageBox.AcceptRole)
        use_button = dialog.addButton("直接确认原始框架", QMessageBox.DestructiveRole)
        dialog.addButton("取消", QMessageBox.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is retry_button:
            self._start_volume_framework_audit_worker()
        elif dialog.clickedButton() is use_button:
            self._save_volume_two_resume("framework_ready")
            self._show_volume_two_framework_dialog(framework)
        else:
            self._set_volume_two_running(False)

    def _cleanup_volume_framework_audit_worker(self):
        worker = self.sender()

        def cleanup():
            try:
                if self.volume_framework_audit_worker is worker:
                    self.volume_framework_audit_worker = None
                if worker is not None:
                    worker.deleteLater()
            except Exception as exc:
                log_debug("本卷框架对齐线程清理失败", exc)

        QTimer.singleShot(0, cleanup)

    def on_volume_framework_failed(self, error):
        worker = self._volume_signal_worker("volume_framework_worker")
        self._save_volume_diagnostic("framework", "error", error=error, worker=worker)
        self._save_volume_two_resume("framework_failed")
        message = clean_error_text(error)
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        handoff = pending.get("handoff")
        setup = pending.get("setup")
        can_retry = (
            isinstance(handoff, dict)
            and bool(handoff)
            and isinstance(setup, dict)
            and bool(str((setup.get("meta", {}) if isinstance(setup.get("meta", {}), dict) else {}).get("title", "") or "").strip())
            and self._volume_two_parent_is_current()
        )
        if not can_retry:
            self._clear_volume_two_pending()
            self.set_status_tip(f"本卷框架生成失败：{message[:100]}")
            QMessageBox.warning(self, "新卷续写失败", message)
            return

        # The handoff call is already complete. Keep it in memory so a
        # transient framework failure does not spend the first API call again.
        self._set_volume_two_running(False)
        self.set_status_tip("本卷框架生成失败，上一卷交接摘要已保留。")
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("本卷框架生成失败")
        dialog.setText(message or "本卷框架生成失败。")
        dialog.setInformativeText(
            "上一卷交接摘要和最后一章正文仍在本次流程中。重试只重新调用本卷框架，不会重复生成交接摘要。"
        )
        retry_button = dialog.addButton("重试本卷框架", QMessageBox.AcceptRole)
        dialog.addButton("取消", QMessageBox.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is retry_button:
            QTimer.singleShot(0, self._retry_volume_framework_from_pending)
            return
        self._clear_volume_two_pending()
        self.set_status_tip("已取消创建新卷续写；上一卷未发生变化。")

    def _retry_volume_framework_from_pending(self):
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        if not pending or not self._volume_two_parent_is_current():
            self._clear_volume_two_pending()
            self.set_status_tip("上一卷已切换或发生变化，无法重试本卷框架。")
            return
        handoff = pending.get("handoff")
        setup = pending.get("setup")
        if not isinstance(handoff, dict) or not isinstance(setup, dict):
            self._clear_volume_two_pending()
            self.set_status_tip("本卷交接资料不完整，无法重试。")
            return
        old_worker = getattr(self, "volume_framework_worker", None)
        if old_worker is not None and old_worker.isRunning():
            QTimer.singleShot(80, self._retry_volume_framework_from_pending)
            return
        self._start_volume_framework_worker(setup)

    def _create_second_volume_project(self, framework):
        pending = self._volume_two_pending if isinstance(self._volume_two_pending, dict) else {}
        if not pending or not self._volume_two_parent_is_current():
            self._clear_volume_two_pending()
            self.set_status_tip("上一卷已切换或发生变化，未创建本卷。")
            return
        framework = deepcopy(framework if isinstance(framework, dict) else {})
        setup = pending.get("setup", {}) if isinstance(pending.get("setup", {}), dict) else {}
        source_snapshot = pending.get("source_snapshot", {})
        source_snapshot = source_snapshot if isinstance(source_snapshot, dict) else {}
        source_meta = source_snapshot.get("meta", {}) if isinstance(source_snapshot.get("meta", {}), dict) else {}
        framework_meta = framework.get("meta", {}) if isinstance(framework.get("meta", {}), dict) else {}
        data = _default_project()
        new_meta = data.setdefault("meta", {})
        for key in ("title", "genre", "style", "pov", "target_words", "premise"):
            value = str(framework_meta.get(key, "") or "").strip()
            if not value:
                value = str((setup.get("meta", {}) if isinstance(setup.get("meta", {}), dict) else {}).get(key, "") or "").strip()
            if not value and key in {"genre", "style", "pov"}:
                value = str(source_meta.get(key, "") or "").strip()
            if key == "target_words" and value:
                value = self._framework_target_words_display(value)
            if value:
                new_meta[key] = value
        source_continuation = _normalize_series_continuation(
            source_snapshot.get("series_continuation", {})
        )
        try:
            next_volume_number = int(source_continuation.get("volume_number", 1) or 1) + 1
        except Exception:
            next_volume_number = 2
        new_meta["title"] = _safe_name(new_meta.get("title", "")) or f"未命名小说 第{next_volume_number}卷"
        new_meta["status"] = "草稿"
        # First-volume foundations are copied locally before AI additions are
        # applied. This keeps the sequel continuous even when the framework
        # response contains only second-volume deltas.
        for key in ("bible", "world_rules"):
            data[key] = str(source_snapshot.get(key, "") or "").strip()
        new_data_materials = self._framework_ai_materials_for_project(framework)
        candidates = _normalize_ai_candidates({
            "characters": framework.get("characters", []),
            "lore": framework.get("lore", []),
            "foreshadows": framework.get("foreshadows", []),
            "project_materials": new_data_materials,
        })
        checked = {
            "characters": list(range(len(candidates.get("characters", [])))),
            "lore": list(range(len(candidates.get("lore", [])))),
            "foreshadows": list(range(len(candidates.get("foreshadows", [])))),
            "project_materials": ["bible", "world_rules", "timeline", "summary"],
        }
        _apply_import_candidates(data, candidates, checked)
        _inherit_continuation_record_ids(source_snapshot, data)
        data["long_form_memory"] = _rebase_long_form_memory_for_volume_continuation(source_snapshot)
        series_id = str(source_continuation.get("series_id", "") or "").strip() or uuid.uuid4().hex
        try:
            previous_volume = int(source_continuation.get("volume_number", 1) or 1)
        except Exception:
            previous_volume = 1
        template_text = _volume_two_framework_template_text()
        framework_source_text = json.dumps(framework, ensure_ascii=False, indent=2)
        framework_source_hash = hashlib.sha256(framework_source_text.encode("utf-8")).hexdigest()
        data["series_continuation"] = {
            "schema_version": "1",
            "series_id": series_id,
            "volume_number": previous_volume + 1,
            "parent_project_path": str(pending.get("source_path", "") or ""),
            "parent_project_title": str(source_meta.get("title", "") or "").strip(),
            "parent_snapshot_hash": str(pending.get("source_hash", "") or "").strip(),
            "template_hash": hashlib.sha256(template_text.encode("utf-8")).hexdigest(),
            "created_at": now_str(),
            "user_requirements": str(
                (setup.get("requirements", "") if isinstance(setup, dict) else "") or ""
            ).strip(),
            "creative_intent_contract": deepcopy(
                pending.get("creative_intent_contract", {})
            ),
            "handoff": deepcopy(pending.get("handoff", {})),
        }
        data["creative_intent_contract"] = deepcopy(
            pending.get("creative_intent_contract", {})
        )
        chapter_plan = self._framework_ai_chapter_plan_for_project(framework)
        reference = self._normalize_imported_chapter_plan_reference(
            chapter_plan,
            new_meta.get("title", ""),
            "本卷框架",
        )
        if reference:
            data["imported_chapter_plan_reference"] = reference
        data["imported_framework_source"] = {
            "text": framework_source_text,
            "sha256": framework_source_hash,
            "source_title": str(new_meta.get("title", "") or "").strip(),
            "source_label": "本卷框架（已确认）",
            "source_path": "",
            "imported_at": now_str(),
        }
        data["framework_import_state"] = {
            "status": "complete",
            "source_hash": framework_source_hash,
            "source_title": str(new_meta.get("title", "") or "").strip(),
            "source_label": "本卷框架（已确认）",
            "import_mode": "创建新卷续写",
            "model": str(self._volume_two_model or "").strip(),
            "updated_at": now_str(),
        }
        # The style library is global; copying its identifier keeps the same
        # style available without duplicating the large sample in this project.
        style_profile_id = str(source_snapshot.get("style_profile_id", "") or "").strip().lower()
        if style_profile_id:
            data["style_profile_id"] = style_profile_id
        if str(source_snapshot.get("style_reference", "") or "").strip():
            data["style_reference"] = str(source_snapshot.get("style_reference", "") or "").strip()
        if isinstance(source_snapshot.get("style_profile_cache", {}), dict):
            data["style_profile_cache"] = deepcopy(source_snapshot.get("style_profile_cache", {}))
        data["updated_at"] = now_str()
        data = _normalize_project(data)
        project_path = unique_project_path(new_meta.get("title", f"未命名小说 第{next_volume_number}卷"))
        try:
            save_project_file(project_path, data)
            self._load_project_data(data, project_path)
            self._remember_project_path(project_path)
            self._save_draft_snapshot()
            self._notify_project_store_changed()
            self._clear_volume_two_pending()
            self.set_status_tip(
                f"本卷已创建并导入：{new_meta.get('title', f'未命名小说 第{next_volume_number}卷')}。"
                "章节规划尚未启动，请按原流程点击“AI生成章节规划”。"
            )
        except Exception as exc:
            self._clear_volume_two_pending()
            log_debug("创建新卷续写项目失败", exc)
            QMessageBox.warning(self, "新卷续写失败", str(exc))

    def _cleanup_volume_handoff_worker(self):
        worker = self.sender()

        def cleanup():
            try:
                if self.volume_handoff_worker is worker:
                    self.volume_handoff_worker = None
                if worker is not None:
                    worker.deleteLater()
            except Exception as exc:
                log_debug("新卷交接线程清理失败", exc)

        QTimer.singleShot(0, cleanup)

    def _cleanup_volume_framework_worker(self):
        worker = self.sender()

        def cleanup():
            try:
                if self.volume_framework_worker is worker:
                    self.volume_framework_worker = None
                if worker is not None:
                    worker.deleteLater()
            except Exception as exc:
                log_debug("新卷框架线程清理失败", exc)

        QTimer.singleShot(0, cleanup)

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
        self._project_file_dirty = False
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

    def import_word_or_txt_script(self):
        path = self._get_open_path(
            "导入 Word/TXT",
            "Word/TXT 文档 (*.docx *.txt);;Word 文档 (*.docx);;TXT 文本 (*.txt)",
        )
        if not path:
            return
        suffix = os.path.splitext(path)[1].lower()
        if suffix == ".docx":
            source_label = "Word"
            reader = _read_docx_text
        elif suffix == ".txt":
            source_label = "TXT"
            reader = _read_txt_text
        else:
            QMessageBox.warning(self, "导入失败", "请选择 Word（.docx）或 TXT（.txt）文件。")
            return
        try:
            text = reader(path)
            if not text.strip():
                QMessageBox.warning(self, "导入失败", f"{source_label} 文件没有可读取的正文。")
                return
            self._import_script_text(text, path, source_label)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))

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
            if import_type == FRAMEWORK_IMPORT_TYPE:
                self._import_framework_text(text, path, source_label)
                return
            chapters = _split_chapters_from_text(text, import_type)
            if not chapters:
                QMessageBox.warning(self, "导入失败", "没有拆出可导入的章节。")
                return

            import_mode, ok = self._get_combo_choice("选择导入方式", "请选择导入方式：", ["创建为新项目", "追加到当前项目"], 0)
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

    def _import_framework_text(self, text, path, source_label):
        worker = getattr(self, "framework_import_worker", None)
        if worker is not None and worker.isRunning():
            self.set_status_tip("框架正在 AI 分类，请稍等。")
            return
        import_mode, ok = self._get_combo_choice("选择导入方式", "请选择导入方式：", ["创建为新项目", "追加到当前项目"], 0)
        if not ok:
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self.set_ai_settings_expanded(True)
            self.set_status_tip(f"框架导入失败：{error}")
            QMessageBox.warning(self, "框架导入失败", error)
            return

        # Importing a new framework changes the planning source.  Drop the
        # resumable checkpoint and visible preview before starting classification
        # so an interrupted plan cannot be mistaken for the new framework's
        # progress (including the append-to-current-project path).
        self._invalidate_chapter_plan_generation(
            "导入新框架，旧章节规划进度已失效",
            clear_project_state=import_mode != "创建为新项目",
        )
        title = self._prepare_framework_import_project(text, path, source_label, import_mode)
        self._start_framework_import_worker(provider, model, text, title, source_label, import_mode)

    def _prepare_framework_import_project(self, text, path, source_label, import_mode):
        self.last_import_text = text
        title = os.path.splitext(os.path.basename(path))[0]
        if import_mode == "创建为新项目":
            self._clear_candidate_detail_view()
            self._save_current_work(f"{source_label}框架导入新项目前保存")
            data = _default_project()
            safe_title = _safe_name(title) or "未命名小说"
            data["meta"]["title"] = safe_title
            data["updated_at"] = now_str()
            project_path = unique_project_path(safe_title)
            save_project_file(project_path, data)
            self._load_project_data(data, project_path)
            self._remember_project_path(project_path)
            self._store_imported_framework_source(text, title, source_label, path)
            self._save_draft_snapshot()
            self._save_current_project_snapshot_if_named()
            self._notify_project_store_changed()
            self._dirty = False
            self._project_file_dirty = False
        else:
            if not self._has_saved_project_path():
                self._save_current_work(f"{source_label}框架导入前保存")
            self._flush_current_editors()
            if self._store_imported_framework_source(text, title, source_label, path):
                self._note_project_dirty()
                self._save_draft_snapshot()
                self._save_current_project_snapshot_if_named()
        return title

    def _store_imported_framework_source(self, text, title="", source_label="", source_path=""):
        text = str(text or "").strip()
        if not text or not isinstance(getattr(self, "current_project", None), dict):
            return False
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing = self.current_project.get("imported_framework_source", {})
        if isinstance(existing, dict) and str(existing.get("sha256", "") or "") == source_hash:
            return False
        self.current_project["imported_framework_source"] = {
            "source_title": str(title or "").strip(),
            "source_label": str(source_label or "").strip(),
            "source_path": str(source_path or "").strip(),
            "text": text,
            "sha256": source_hash,
            "imported_at": now_str(),
        }
        return True

    def _framework_bible_reference_block(self, text, title="", source_label=""):
        text = str(text or "").strip()
        if not text:
            return ""
        title = str(title or "").strip() or "未命名框架"
        source_label = str(source_label or "").strip() or "导入"
        return f"导入框架原文（{source_label}：{title}）：\n{text}"

    def _append_framework_reference_to_bible(self, text, title="", source_label=""):
        block = self._framework_bible_reference_block(text, title, source_label)
        if not block:
            return False
        old = str(self.current_project.get("bible", "") or "").strip()
        if block in old:
            return False
        self.current_project["bible"] = f"{old}\n\n{block}".strip() if old else block
        return True

    def _framework_ai_materials_for_project(self, data):
        materials = deepcopy(data.get("project_materials", {})) if isinstance(data, dict) else {}
        materials = materials if isinstance(materials, dict) else {}
        for key in ("timeline", "summary"):
            materials[key] = ""
        return materials

    def _framework_ai_chapter_plan_for_project(self, data):
        data = data if isinstance(data, dict) else {}
        plan = deepcopy(data.get("chapter_plan", {}))
        plan = plan if isinstance(plan, dict) else {}
        materials = data.get("project_materials", {})
        materials = materials if isinstance(materials, dict) else {}
        moved_parts = []
        for key, label in (("timeline", "框架时间线 / 阶段规划"), ("summary", "框架摘要")):
            value = str(materials.get(key, "") or "").strip()
            if value:
                moved_parts.append(f"{label}：\n{value}")
        if moved_parts:
            summary = str(plan.get("summary", "") or "").strip()
            additions = "\n\n".join(moved_parts)
            if additions not in summary:
                plan["summary"] = f"{summary}\n\n{additions}".strip() if summary else additions
        if isinstance(data.get("chapter_locations"), list):
            plan["chapter_locations"] = deepcopy(data.get("chapter_locations"))
        analysis = data.get("framework_analysis", {})
        if isinstance(analysis, dict):
            plan["local_mapping_status"] = str(
                analysis.get("local_mapping_status", "") or ""
            ).strip()
        return plan

    def _refresh_after_framework_import(self):
        self.import_candidates = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
        self.pending_analysis_chapter_ids = []
        self.failed_analysis_chunks = []
        self._set_candidate_postprocess_state("")
        self._sync_candidate_analysis_state()
        self._sync_import_candidates_to_project()
        self._refresh_project_meta_editors()
        self._refresh_project_material_editors()
        self._reload_character_list()
        self._reload_lore_list()
        self._reload_foreshadow_list()
        self._reload_chapter_list()
        self.refresh_writing_check()
        self.refresh_manuscript()
        self._update_stats_label()

    def _start_framework_import_worker(self, provider, model, text, source_title, source_label, import_mode):
        if not provider:
            return
        worker = getattr(self, "framework_import_worker", None)
        if worker is not None and worker.isRunning():
            self.set_status_tip("框架正在 AI 分类，请稍等。")
            return
        context = _candidate_analysis_dossier_text(self._ai_project_snapshot())
        self._framework_import_context = {
            "source_title": str(source_title or "").strip(),
            "source_label": str(source_label or "").strip(),
            "import_mode": str(import_mode or "").strip(),
            "source_text": str(text or ""),
        }
        self.framework_import_worker = NovelFrameworkImportWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            text,
            context,
            provider.get("proxy_url", ""),
            self._provider_proxy_mode(provider),
        )
        self._connect_novel_worker_status(self.framework_import_worker)
        self.framework_import_worker.result_ready.connect(self.on_framework_import_ready)
        self.framework_import_worker.failed.connect(self.on_framework_import_failed)
        self.framework_import_worker.finished.connect(self._cleanup_framework_import_worker)
        self._persist_framework_import_state("running", model=model)
        self.set_status_tip("正在用 AI 分类导入框架...")
        self.framework_import_worker.start()

    def _framework_import_source(self):
        source = self.current_project.get("imported_framework_source", {})
        source = source if isinstance(source, dict) else {}
        return {
            "text": str(source.get("text", "") or "").strip(),
            "sha256": str(source.get("sha256", "") or "").strip().lower(),
            "source_title": str(source.get("source_title", "") or "").strip(),
            "source_label": str(source.get("source_label", "") or "").strip(),
        }

    def _refresh_framework_import_retry_action(self):
        button = getattr(self, "framework_import_retry_btn", None)
        if button is None:
            return
        source = self._framework_import_source()
        if not source.get("text"):
            button.setVisible(False)
            return
        state = self.current_project.get("framework_import_state", {})
        state = state if isinstance(state, dict) else {}
        status = str(state.get("status", "") or "")
        worker = getattr(self, "framework_import_worker", None)
        running = worker is not None and (worker.isRunning() or status == "running")
        if running:
            button.setText("框架 AI 分类中...")
            button.setEnabled(False)
            button.setVisible(True)
            return
        if status == "complete":
            button.setVisible(False)
            return
        if status != "failed" and self._project_has_started_chapter_planning():
            button.setVisible(False)
            return
        button.setText("重试框架 AI 分类" if status == "failed" else "重新进行框架 AI 分类")
        button.setEnabled(True)
        button.setVisible(True)

    def _project_has_started_chapter_planning(self):
        project = self.current_project if isinstance(self.current_project, dict) else {}
        chapters = project.get("chapters", [])
        if isinstance(chapters, list) and chapters:
            return True
        foundation = project.get("chapter_plan_foundation", {})
        if isinstance(foundation, dict) and (
            str(foundation.get("summary", "") or "").strip()
            or bool(foundation.get("arcs"))
            or bool(foundation.get("narrative_strategy_profile"))
        ):
            return True
        generation = project.get("chapter_plan_generation_state", {})
        if not isinstance(generation, dict):
            return False
        generation_status = str(generation.get("status", "") or "").strip()
        return bool(
            generation.get("master_plan")
            or generation.get("chapters")
            or generation_status in {
                "generating",
                "awaiting_profile_confirmation",
                "complete",
            }
        )

    def _persist_framework_import_state(self, status, error="", model=""):
        if not isinstance(getattr(self, "current_project", None), dict):
            return
        source = self._framework_import_source()
        context = getattr(self, "_framework_import_context", {}) or {}
        state = {
            "status": str(status or "failed"),
            "source_hash": source.get("sha256", ""),
            "source_title": str(context.get("source_title", "") or source.get("source_title", "")),
            "source_label": str(context.get("source_label", "") or source.get("source_label", "")),
            "import_mode": str(context.get("import_mode", "") or "追加到当前项目"),
            "model": str(model or ""),
            "updated_at": now_str(),
        }
        error_text = clean_error_text(error) if error else ""
        if error_text:
            state["error"] = error_text[:1000]
        self.current_project["framework_import_state"] = state
        self._note_project_dirty()
        try:
            self._save_draft_snapshot()
            self._save_current_project_snapshot_if_named()
        except Exception as e:
            log_debug("框架 AI 分类状态保存失败", e)
        self._refresh_framework_import_retry_action()

    def retry_framework_import(self):
        worker = getattr(self, "framework_import_worker", None)
        if worker is not None and worker.isRunning():
            self.set_status_tip("框架正在 AI 分类，请稍等。")
            return
        source = self._framework_import_source()
        text = source.get("text", "")
        if not text:
            QMessageBox.warning(self, "无法重试", "当前项目没有保存可重试的框架原文。")
            self._refresh_framework_import_retry_action()
            return
        provider, model, error = self._current_novel_ai_selection()
        if error:
            self.set_ai_settings_expanded(True)
            self.set_status_tip(f"框架 AI 分类重试失败：{error}")
            QMessageBox.warning(self, "框架 AI 分类重试失败", error)
            return
        title = source.get("source_title", "") or self._project_title()
        label = source.get("source_label", "") or "框架"
        self._start_framework_import_worker(
            provider,
            model,
            text,
            title,
            label,
            "追加到当前项目",
        )

    def _set_combo_text_without_signals(self, widget, value):
        if widget is None:
            return
        text = str(value or "").strip()
        if not text:
            return
        widget.blockSignals(True)
        try:
            index = widget.findText(text)
            if index >= 0:
                widget.setCurrentIndex(index)
        finally:
            widget.blockSignals(False)

    def _refresh_project_meta_editors(self):
        meta = self.current_project.get("meta", {}) if isinstance(self.current_project, dict) else {}
        if hasattr(self, "title_edit"):
            self._set_line_text_without_signals(self.title_edit, meta.get("title", ""))
        if hasattr(self, "genre_edit"):
            self._set_line_text_without_signals(self.genre_edit, meta.get("genre", ""))
        if hasattr(self, "style_edit"):
            self._set_line_text_without_signals(self.style_edit, meta.get("style", ""))
        if hasattr(self, "target_words_edit"):
            self._set_line_text_without_signals(self.target_words_edit, meta.get("target_words", ""))
        if hasattr(self, "premise_edit"):
            self._set_text_without_signals(self.premise_edit, meta.get("premise", ""))
        if hasattr(self, "pov_combo"):
            self._set_combo_text_without_signals(self.pov_combo, meta.get("pov", ""))
        if hasattr(self, "status_combo"):
            self._set_combo_text_without_signals(self.status_combo, meta.get("status", ""))

    def _merge_framework_meta(self, meta_updates, source_title="", import_mode=""):
        meta_updates = meta_updates if isinstance(meta_updates, dict) else {}
        meta = self.current_project.setdefault("meta", {})
        new_project = import_mode == "创建为新项目"
        source_title = str(source_title or "").strip()
        changed = 0
        for key in ("title", "genre", "style", "pov", "target_words", "status"):
            value = str(meta_updates.get(key, "") or "").strip()
            if not value:
                continue
            if key == "target_words":
                value = self._framework_target_words_display(value)
            current = str(meta.get(key, "") or "").strip()
            can_replace = (
                new_project
                or not current
                or current in {"未命名小说", "草稿"}
                or (key == "title" and source_title and current == source_title)
            )
            if can_replace and current != value:
                meta[key] = value
                changed += 1
        premise = str(meta_updates.get("premise", "") or "").strip()
        if premise:
            current = str(meta.get("premise", "") or "").strip()
            if not current or new_project:
                if current != premise:
                    meta["premise"] = premise
                    changed += 1
            elif premise not in current:
                merged, did_change = _merge_text_lines_without_duplicates(current, premise)
                if did_change:
                    meta["premise"] = merged
                    changed += 1
        return changed

    def _framework_target_words_display(self, value):
        text = str(value or "").replace(",", "").strip()
        if not text:
            return ""
        try:
            words = _target_words({"target_words": text})
        except Exception:
            words = 0
        if words <= 0:
            return text
        if words % 10000 == 0:
            return f"{words // 10000}万"
        if words >= 10000:
            number = words / 10000
            return f"{number:.2f}".rstrip("0").rstrip(".") + "万"
        return f"{words}字"

    def _reconcile_imported_framework_source(self):
        return False

    def _normalize_imported_chapter_plan_reference(self, plan, source_title="", source_label=""):
        plan = plan if isinstance(plan, dict) else {}
        items = plan.get("chapters", [])
        items = items if isinstance(items, list) else []
        chapters = []
        for fallback_index, item in enumerate(items, 1):
            if not isinstance(item, dict):
                continue
            outline = _strip_volume_handoff_outline_metadata(
                _strip_static_foreshadow_outline_fields(item.get("outline", ""))
            )
            if not outline:
                outline = self._chapter_plan_outline_for_item(item)
            title = str(item.get("title", "") or "").strip()
            if _is_framework_scope_title(title) or _is_framework_placeholder_chapter_title(title):
                continue
            if not title and not outline:
                continue
            chapters.append({
                "index": str(item.get("index", fallback_index) or fallback_index),
                "title": title,
                "target_words": str(item.get("target_words", "") or "").strip(),
                "narrative_stage": str(item.get("narrative_stage", "") or "").strip(),
                "outline": outline,
                "characters": _normalize_name_list(item.get("characters", [])),
                "ending_hook": str(item.get("ending_hook", "") or "").strip(),
                "source_event_ids": [
                    _canonical_chapter_plan_event_id(value)
                    for value in _normalize_name_list(item.get("source_event_ids", []))
                ],
            })
            if isinstance(item.get("source_location"), dict):
                chapters[-1]["source_location"] = {
                    "start_line": str(item["source_location"].get("start_line", "") or "").strip(),
                    "end_line": str(item["source_location"].get("end_line", "") or "").strip(),
                    **({
                        "anchor": str(item["source_location"].get("anchor", "") or "").strip()
                    } if str(item["source_location"].get("anchor", "") or "").strip() else {}),
                }
        stages = []
        for stage_index, item in enumerate(
            plan.get("stages", []) if isinstance(plan.get("stages", []), list) else [], 1
        ):
            if not isinstance(item, dict):
                continue
            try:
                start_chapter = int(item.get("start_chapter", 0) or 0)
                end_chapter = int(item.get("end_chapter", 0) or 0)
            except Exception:
                continue
            if start_chapter <= 0 or end_chapter < start_chapter:
                continue
            stage_id = _canonical_chapter_plan_stage_id(
                item.get("id", ""),
                f"S{stage_index:02d}",
            )
            events = []
            for event_index, event in enumerate(
                item.get("events", []) if isinstance(item.get("events", []), list) else [], 1
            ):
                if not isinstance(event, dict):
                    continue
                event_id = _canonical_chapter_plan_event_id(
                    event.get("id", "") or f"{stage_id}-E{event_index:02d}"
                )
                event_text = str(event.get("text", "") or "").strip()
                if not event_id or not event_text:
                    continue
                try:
                    order = int(event.get("order", event_index) or event_index)
                except Exception:
                    order = event_index
                events.append({"id": event_id, "order": order, "text": event_text})
            if events or str(plan.get("source", "") or "") == "local_framework_parser":
                stages.append({
                    "id": stage_id,
                    "name": str(item.get("name", "") or f"阶段{stage_index}").strip(),
                    "summary": str(item.get("summary", "") or "").strip(),
                    "start_chapter": start_chapter,
                    "end_chapter": end_chapter,
                    "events": [] if str(plan.get("source", "") or "") == "local_framework_parser" else events,
                })
        summary = str(plan.get("summary", "") or "").strip()
        if not summary and not chapters and not stages:
            return {}
        reference = {
            "summary": summary,
            "source": str(plan.get("source", "") or "").strip(),
            "semantic_outline_mode": str(plan.get("semantic_outline_mode", "") or "").strip(),
            "semantic_outline_missing": _normalize_name_list(plan.get("semantic_outline_missing", [])),
            "source_text_preserved": bool(plan.get("source_text_preserved")),
            "local_mapping_status": str(plan.get("local_mapping_status", "") or "").strip(),
            "unresolved_chapters": _normalize_name_list(plan.get("unresolved_chapters", [])),
            "source_title": str(source_title or "").strip(),
            "source_label": str(source_label or "").strip(),
            "imported_at": now_str(),
        }
        if chapters:
            reference["chapters"] = chapters
        locations = plan.get("chapter_locations", [])
        if isinstance(locations, list) and locations:
            normalized_locations = []
            for fallback_index, item in enumerate(locations, 1):
                if not isinstance(item, dict):
                    continue
                try:
                    index = int(item.get("index", fallback_index) or fallback_index)
                except (TypeError, ValueError):
                    index = fallback_index
                if index <= 0:
                    continue
                normalized_locations.append({
                    "index": index,
                    "start_line": str(item.get("start_line", "") or "").strip(),
                    "end_line": str(item.get("end_line", "") or "").strip(),
                    "characters": _normalize_name_list(item.get("characters", [])),
                    **({
                        "anchor": str(item.get("anchor", "") or "").strip()
                    } if str(item.get("anchor", "") or "").strip() else {}),
                })
            if normalized_locations:
                reference["chapter_locations"] = normalized_locations
        if stages:
            reference["stages"] = stages
        return reference

    def _store_imported_chapter_plan_reference(self, plan, source_title="", source_label=""):
        reference = self._normalize_imported_chapter_plan_reference(plan, source_title, source_label)
        if not reference:
            self.current_project.pop("imported_chapter_plan_reference", None)
            return 0
        self.current_project["imported_chapter_plan_reference"] = reference
        return len(reference.get("chapters", []) if isinstance(reference.get("chapters", []), list) else [])

    def _apply_complete_imported_chapter_plan(self, plan, analysis):
        """Write a verified complete imported outline directly as chapters."""
        self._last_framework_direct_import_count = 0
        plan = plan if isinstance(plan, dict) else {}
        analysis = analysis if isinstance(analysis, dict) else {}
        chapters_plan = [
            item for item in plan.get("chapters", [])
            if isinstance(item, dict)
        ]
        outline_mode = str(analysis.get("chapter_outline_mode", "") or "").strip().lower()
        foundation_mode = str(analysis.get("foundation_mode", "") or "").strip().lower()
        mapping_status = str(plan.get("local_mapping_status", "") or "").strip().lower()
        unresolved = _normalize_name_list(plan.get("unresolved_chapters", []))
        expected_count = int(analysis.get("chapter_outline_count", 0) or 0)
        indexes = []
        for item in chapters_plan:
            try:
                indexes.append(int(item.get("index", 0) or 0))
            except (TypeError, ValueError):
                indexes.append(0)
        complete = (
            not self.current_project.get("chapters")
            and foundation_mode == "reuse"
            and outline_mode == "reuse"
            and mapping_status in {"mapped", "mapped_by_ai"}
            and not unresolved
            and bool(chapters_plan)
            and len(indexes) == len(set(indexes))
            and all(index > 0 for index in indexes)
            and indexes == list(range(1, len(indexes) + 1))
            and (not expected_count or expected_count == len(chapters_plan))
            and all(str(item.get("outline", "") or "").strip() for item in chapters_plan)
        )
        if not complete:
            return 0
        chapters = self.current_project.setdefault("chapters", [])
        parameters = analysis.get("planning_parameters", {})
        parameters = parameters if isinstance(parameters, dict) else {}
        try:
            default_target_words = int(parameters.get("average_chapter_words", 0) or 0)
        except (TypeError, ValueError):
            default_target_words = 0
        for item in chapters_plan:
            chapter = _new_chapter(len(chapters))
            title = str(item.get("title", "") or "").strip()
            if title:
                chapter["title"] = title
            target_words = str(item.get("target_words", "") or "").strip()
            if not target_words and default_target_words > 0:
                target_words = str(default_target_words)
            if target_words:
                chapter["draft_words"] = target_words
            chapter["outline"] = self._chapter_plan_outline_for_item(item)
            for key in ("narrative_stage", "source_stage", "dominant_line", "ending_hook"):
                chapter[key] = str(item.get(key, "") or "").strip()
            if not chapter["source_stage"]:
                chapter["source_stage"] = chapter["narrative_stage"]
            chapter["linked_characters"] = _normalize_name_list(item.get("characters", []))
            chapter["source_event_ids"] = [
                _canonical_chapter_plan_event_id(value)
                for value in _normalize_name_list(item.get("source_event_ids", []))
            ]
            chapter["status"] = "大纲"
            chapters.append(chapter)
        self.current_project.pop("chapter_plan_generation_state", None)
        self.current_project.pop("chapter_plan_foundation", None)
        self._last_framework_direct_import_count = len(chapters_plan)
        return len(chapters_plan)

    def _apply_framework_import_result(self, data):
        data = data if isinstance(data, dict) else {}
        self._flush_current_editors()
        context = getattr(self, "_framework_import_context", {}) or {}
        meta_changed = self._merge_framework_meta(
            data.get("meta", {}),
            context.get("source_title", ""),
            context.get("import_mode", ""),
        )
        framework_plan = self._framework_ai_chapter_plan_for_project(data)
        candidates = _normalize_ai_candidates({
            "characters": data.get("characters", []),
            "lore": data.get("lore", []),
            "foreshadows": data.get("foreshadows", []),
            "project_materials": self._framework_ai_materials_for_project(data),
        })
        checked = {
            "characters": list(range(len(candidates.get("characters", [])))),
            "lore": list(range(len(candidates.get("lore", [])))),
            "foreshadows": list(range(len(candidates.get("foreshadows", [])))),
            "project_materials": ["bible", "world_rules", "timeline", "summary"],
        }
        apply_result = _apply_import_candidates(self.current_project, candidates, checked)
        source_text = str(context.get("source_text", "") or "").strip()
        if not source_text:
            source_text = str(
                self.current_project.get("imported_framework_source", {}).get("text", "")
                if isinstance(self.current_project.get("imported_framework_source"), dict) else ""
            ).strip()
        analysis = _normalize_framework_analysis(data.get("framework_analysis", {}), source_text)
        if analysis:
            self.current_project["imported_framework_analysis"] = analysis
            # AI decides semantic completeness; local code restores the
            # original chapter text without asking the model to echo it.
            chapter_locations = framework_plan.get("chapter_locations", [])
            local_plan = _build_local_framework_chapter_plan(
                source_text,
                analysis,
                chapter_locations,
            )
            merged_plan = _merge_framework_chapter_plans(framework_plan, local_plan)
            # Persist the final local mapping result, not the worker's
            # pre-localization placeholder status. Otherwise a successful
            # direct import would still look pending on the next launch.
            analysis["local_mapping_status"] = str(
                merged_plan.get("local_mapping_status", "") or "pending"
            ).strip().lower()
            self.current_project["imported_framework_analysis"] = analysis
        else:
            # Old saved/API payloads can still be read, but do not establish
            # a semantic reuse decision merely because a regex recognized them.
            structured_plan = _build_local_framework_chapter_plan(source_text, {})
            merged_plan = _merge_framework_chapter_plans(framework_plan, structured_plan)
        plan_added = self._store_imported_chapter_plan_reference(
            merged_plan,
            context.get("source_title", ""),
            context.get("source_label", ""),
        )
        self._apply_complete_imported_chapter_plan(merged_plan, analysis)
        self._refresh_after_framework_import()
        self._note_project_dirty()
        save_message = self._save_after_import()
        return apply_result, meta_changed, plan_added, save_message

    def on_framework_import_ready(self, data):
        try:
            result, meta_changed, plan_added, save_message = self._apply_framework_import_result(data)
            direct_import_count = int(
                getattr(self, "_last_framework_direct_import_count", 0) or 0
            )
            previous_state = self.current_project.get("framework_import_state", {})
            previous_state = previous_state if isinstance(previous_state, dict) else {}
            self._persist_framework_import_state(
                "complete",
                model=str(previous_state.get("model", "") or ""),
            )
            added = result.get("added", {}) if isinstance(result, dict) else {}
            merged = result.get("merged", {}) if isinstance(result, dict) else {}
            materials = result.get("materials", {}) if isinstance(result, dict) else {}
            if hasattr(self, "nav_list") and hasattr(self, "page_indexes"):
                self.nav_list.setCurrentRow(self.page_indexes.get("圣经", 0))
            material_count = sum(1 for value in materials.values() if value) if isinstance(materials, dict) else 0
            reference = self.current_project.get("imported_chapter_plan_reference", {})
            stage_event_count = sum(
                len(item.get("events", []))
                for item in reference.get("stages", [])
                if isinstance(item, dict) and isinstance(item.get("events", []), list)
            ) if isinstance(reference, dict) else 0
            analysis = self._framework_ai_analysis()
            mode = str(analysis.get("foundation_mode", "") or "").strip().lower()
            mode_text = {
                "reuse": "AI判断为完整框架，章节细纲直接沿用原文",
                "supplement": "AI判断为部分完整，后续只补缺失章节内容",
                "generate": "AI判断为资料不足，后续才生成缺失规划",
            }.get(mode, "已完成语义分类")
            direct_text = (
                f"已直接写入 {direct_import_count} 章章节规划，可直接开始正文扩写"
                if direct_import_count
                else "仍需进入“章节”补充或确认章节规划"
            )
            self.set_status_tip(
                "框架 AI 分类完成："
                f"项目信息 {meta_changed} 项，"
                f"新增 人物 {added.get('characters', 0)} / 设定 {added.get('lore', 0)} / 伏笔 {added.get('foreshadows', 0)}，"
                f"补充 人物 {merged.get('characters', 0)} / 设定 {merged.get('lore', 0)} / 伏笔 {merged.get('foreshadows', 0)}，"
                f"资料分类 {material_count} 项，明确章节约束 {plan_added} 章，阶段剧情节点 {stage_event_count} 个。"
                f"{mode_text}。{direct_text}。{save_message}"
            )
        except Exception as e:
            self.on_framework_import_failed(str(e))

    def on_framework_import_failed(self, err):
        message = clean_error_text(err)
        previous_state = self.current_project.get("framework_import_state", {})
        previous_state = previous_state if isinstance(previous_state, dict) else {}
        self._persist_framework_import_state(
            "failed",
            error=message,
            model=str(previous_state.get("model", "") or ""),
        )
        self.set_status_tip(f"框架 AI 分类失败：{message[:100]}。项目和框架原文已保存，可直接重试。")
        QMessageBox.warning(
            self,
            "框架 AI 分类失败",
            f"{message}\n\n项目和框架原文已经保存。请点击左侧“重试框架 AI 分类”，无需重新导入文件。",
        )

    def _cleanup_framework_import_worker(self):
        worker = self.sender()

        def cleanup():
            try:
                if self.framework_import_worker is worker:
                    self.framework_import_worker = None
                if worker is not None:
                    worker.deleteLater()
                self._refresh_framework_import_retry_action()
            except Exception as e:
                log_debug("小说框架导入线程清理失败", e)

        QTimer.singleShot(0, cleanup)

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
        self._project_file_dirty = False
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

    @staticmethod
    def _format_status_elapsed(seconds):
        try:
            total = max(0, int(float(seconds or 0)))
        except (TypeError, ValueError):
            total = 0
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}时{minutes:02d}分{secs:02d}秒"
        if minutes:
            return f"{minutes}分{secs:02d}秒"
        return f"{secs}秒"

    @staticmethod
    def _status_action_label(action):
        return {
            "draft": "正文直写",
            "style_profile": "文风画像",
            "style_baseline": "文风基准稿",
            "style_sheet": "作者写法提取",
            "style_sheet_merge": "文风档案合并",
            "style_persona": "作者人格",
            "style_cards": "原文片段库",
            "style_rules": "本章文风规则",
            "style_finalize": "终稿补救",
            "style_audit": "文风审校",
            "style_rewrite": "定向重写",
            "style_plot_extract": "剧情事实整理",
            "memory_finalize": "状态整理",
            "memory_reconcile": "十章边界对账",
            "memory_repair": "状态修复",
            "logic_repair": "逻辑局部修复",
            "outline": "章节提纲",
            "summary": "摘要/关键事实",
            "script_to_novel": "剧本转小说",
            "novel_to_script": "小说转剧本",
            "novel_to_storyboard": "小说转分镜",
            "script_to_storyboard": "剧本转分镜",
        }.get(str(action or "").strip(), "")

    @staticmethod
    def _status_message_is_terminal(text):
        value = str(text or "")
        return any(marker in value for marker in (
            "自动扩写完成",
            "自动扩写已中止",
            "自动扩写已停止",
            "章节 AI 已完成",
            "AI 写作失败",
            "正文终稿未写入章节",
            "状态整理已中止",
            "正文逻辑修复已中止",
            "AI 辅助生成已中止",
            "章节规划生成已中止",
            "章节规划已全部生成",
        ))

    def _status_stage_for_message(self, text):
        value = str(text or "").strip()
        terminal_patterns = (
            ("自动扩写完成", "批次完成", "auto_complete"),
            ("自动扩写已中止", "批次已中止", "auto_aborted"),
            ("自动扩写已停止", "批次已停止", "auto_stopped"),
            ("章节 AI 已完成", "本章完成", "chapter_complete"),
            ("正文终稿未写入章节", "状态同步失败", "memory_failed"),
            ("AI 写作失败", "生成失败", "generation_failed"),
            ("状态整理已中止", "状态整理已中止", "memory_aborted"),
            ("正文逻辑修复已中止", "逻辑修复已中止", "logic_repair_aborted"),
            ("AI 辅助生成已中止", "生成已中止", "generation_aborted"),
            ("章节规划生成已中止", "规划已中止", "plan_aborted"),
            ("章节规划已全部生成", "规划完成", "plan_complete"),
        )
        for marker, label, key in terminal_patterns:
            if marker in value:
                return label, key
        text_patterns = (
            (("秒后自动重试", "正在自动重试", "自动重试当前步骤"), "等待自动重试", "retry"),
            (("正在中止",), "正在中止", "stopping"),
            (("普通基准稿",), "文风基准稿", "style_baseline"),
            (("提取证据化写法", "作者写法"), "作者写法提取", "style_sheet"),
            (("合并作者写作档案",), "文风档案合并", "style_sheet_merge"),
            (("作者人格",), "作者人格", "style_persona"),
            (("功能型原文片段库", "原文片段库"), "原文片段库", "style_cards"),
            (("本章专用文风规则", "本章文风规则"), "本章文风规则", "style_rules"),
            (("正文直写", "文风档案已载入", "正在直接扩写正文"), "正文直写", "draft"),
            (("终稿补救",), "终稿补救", "style_finalize_rescue"),
            (("审校并修订正文终稿", "专门审校并修订正文终稿", "仿写终稿"), "终稿补救", "style_finalize"),
            (("独立审校", "文风审校"), "文风审校", "style_audit"),
            (("定向重写", "自动重写一次"), "定向重写", "style_rewrite"),
            (("剧情事实",), "剧情事实整理", "style_plot_extract"),
            (("边界语义对账", "十章对账"), "十章边界对账", "memory_reconcile"),
            (("状态修复", "修复本章摘要", "正在修复"), "状态修复", "memory_repair"),
            (("逻辑矛盾", "局部修复正文逻辑", "逻辑局部修复"), "逻辑局部修复", "logic_repair"),
            (("状态整理", "长期状态"), "状态整理", "memory_finalize"),
            (("章节提纲", "补提纲"), "章节提纲", "outline"),
            (("摘要/关键事实", "补摘要", "提炼摘要"), "摘要/关键事实", "summary"),
            (("准备下一章",), "准备下一章", "next_chapter"),
            (("已丢弃半成品", "半成品不参与续写"), "半成品重写", "partial_rewrite"),
            (("自动扩写",), "自动扩写队列", "auto_queue"),
            (("章节规划",), "章节规划", "chapter_plan"),
        )
        for markers, label, key in text_patterns:
            if any(marker in value for marker in markers):
                return label, key
        action = str(getattr(self, "_chapter_ai_running_action", "") or "")
        action_label = self._status_action_label(action)
        if action_label:
            return action_label, action or "chapter_ai"
        if "正在" in value:
            return "处理中", "working"
        return "状态更新", "status"

    def _status_current_chapter_scope(self):
        if self._detached_auto_status_is_current():
            scope_id = str(getattr(self, "_detached_auto_status_scope_id", "") or "")
            scope_label = str(getattr(self, "_detached_auto_status_scope_label", "") or "")
            if scope_id or scope_label:
                return scope_id, scope_label
        project = self.current_project if isinstance(getattr(self, "current_project", None), dict) else {}
        chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
        try:
            index = int(getattr(self, "current_chapter_index", -1))
        except (TypeError, ValueError):
            index = -1
        if not (0 <= index < len(chapters)) or not isinstance(chapters[index], dict):
            return "", ""
        chapter = chapters[index]
        chapter_id = str(chapter.get("id", "") or f"index:{index}")
        title = str(chapter.get("title", "") or "").strip()
        if len(title) > 18:
            title = title[:18] + "..."
        label = f"第{index + 1}章"
        if title:
            label += f"《{title}》"
        return chapter_id, label

    def _status_close_current_stage(self, now_mono=None, now_wall=None):
        if not bool(getattr(self, "_status_stage_active", False)):
            return
        now_mono = float(now_mono if now_mono is not None else time.monotonic())
        now_wall = float(now_wall if now_wall is not None else time.time())
        started_at = float(getattr(self, "_status_stage_started_at", 0.0) or now_mono)
        started_wall = float(getattr(self, "_status_stage_started_wall", 0.0) or now_wall)
        history = getattr(self, "_status_history", None)
        if not isinstance(history, list):
            history = []
            self._status_history = history
        history.append({
            "label": str(getattr(self, "_status_stage_label", "") or "处理中"),
            "scope": str(getattr(self, "_status_stage_scope_label", "") or ""),
            "started_wall": started_wall,
            "ended_wall": now_wall,
            "elapsed": max(0.0, now_mono - started_at),
        })
        del history[:-6]
        self._status_stage_active = False

    def _status_begin_workflow(self, kind=""):
        if bool(getattr(self, "_status_workflow_active", False)):
            return
        now_mono = time.monotonic()
        now_wall = time.time()
        self._status_close_current_stage(now_mono, now_wall)
        self._status_workflow_active = True
        self._status_workflow_kind = str(kind or "")
        self._status_workflow_started_at = now_mono
        self._status_workflow_started_wall = now_wall
        self._status_last_run_elapsed = 0.0
        self._status_received_chars = 0
        self._status_history = []
        self._status_stage_key = ""
        self._status_stage_label = ""
        self._status_stage_active = False

    def _status_end_workflow(self, now_mono=None, now_wall=None):
        now_mono = float(now_mono if now_mono is not None else time.monotonic())
        now_wall = float(now_wall if now_wall is not None else time.time())
        self._status_close_current_stage(now_mono, now_wall)
        started_at = float(getattr(self, "_status_workflow_started_at", 0.0) or 0.0)
        if started_at:
            self._status_last_run_elapsed = max(0.0, now_mono - started_at)
        self._status_workflow_active = False

    def _status_has_active_work(self):
        detached = self._current_background_chapter_runner()
        if self._detached_auto_status_is_current(detached):
            try:
                if detached._status_has_active_work():
                    return True
            except Exception:
                pass
        if any(bool(getattr(self, name, False)) for name in (
            "_auto_expand_all_active",
            "_auto_expand_all_waiting_next",
            "_chapter_ai_sequence_active",
            "_chapter_ai_transient_retry_pending",
            "_chapter_plan_auto_active",
            "_chapter_plan_continue_pending",
        )):
            return True
        if (getattr(self, "_chapter_task_timer_owner", None) or {}).get("pending", 0):
            return True
        retired_workers = getattr(self, "writing_retired_workers", None)
        if isinstance(retired_workers, list) and any(
            worker is not None for worker in retired_workers
        ):
            return True
        for name in ("writing_worker", "chapter_plan_worker", "context_build_worker"):
            worker = getattr(self, name, None)
            if worker is not None:
                # Queued result/finished signals must run before runner teardown.
                return True
        return False

    def _track_status_message(self, text):
        value = str(text or "")
        now_mono = time.monotonic()
        now_wall = time.time()
        terminal_message = self._status_message_is_terminal(value)
        has_active_work = self._status_has_active_work()
        if (
            has_active_work
            and not bool(getattr(self, "_status_workflow_active", False))
            and not terminal_message
            and "中止" not in value
            and not bool(getattr(self, "_chapter_ai_stop_requested_by_user", False))
        ):
            self._status_begin_workflow("detected")
            now_mono = time.monotonic()
            now_wall = time.time()
        label, stage_code = self._status_stage_for_message(value)
        scope_id, scope_label = self._status_current_chapter_scope()
        if (
            not has_active_work
            and not bool(getattr(self, "_status_workflow_active", False))
            and not terminal_message
        ):
            self._status_close_current_stage(now_mono, now_wall)
            self._status_stage_key = "global:status"
            self._status_stage_label = "状态更新"
            self._status_stage_scope_label = ""
            self._status_stage_started_at = now_mono
            self._status_stage_started_wall = now_wall
            self._status_stage_active = False
            return
        stage_key = f"{scope_id or 'global'}:{stage_code}"
        if stage_key != str(getattr(self, "_status_stage_key", "") or ""):
            self._status_close_current_stage(now_mono, now_wall)
            self._status_stage_key = stage_key
            self._status_stage_label = label
            self._status_stage_scope_label = scope_label
            self._status_stage_started_at = now_mono
            self._status_stage_started_wall = now_wall
            self._status_stage_active = True
            if not terminal_message:
                self._status_received_chars = 0
        else:
            self._status_stage_label = label
            self._status_stage_scope_label = scope_label
        terminal = terminal_message
        if bool(getattr(self, "_auto_expand_all_active", False)) and not any(
            marker in value for marker in ("自动扩写完成", "自动扩写已中止", "自动扩写已停止")
        ):
            terminal = False
        if terminal:
            self._status_end_workflow(now_mono, now_wall)

    def _status_history_text(self):
        history = getattr(self, "_status_history", [])
        if not isinstance(history, list) or not history:
            return ""
        lines = []
        for entry in history[-2:]:
            if not isinstance(entry, dict):
                continue
            started = time.strftime("%H:%M:%S", time.localtime(float(entry.get("started_wall", 0) or 0)))
            ended = time.strftime("%H:%M:%S", time.localtime(float(entry.get("ended_wall", 0) or 0)))
            scope = str(entry.get("scope", "") or "")
            label = str(entry.get("label", "") or "处理中")
            elapsed = self._format_status_elapsed(entry.get("elapsed", 0))
            stage = f"{scope} · {label}" if scope else label
            lines.append(f"{started}-{ended}  {stage}（{elapsed}）")
        return "最近阶段\n" + "\n".join(lines) if lines else ""

    @staticmethod
    def _status_progress_percent(message, stage_code, received_chars=0, active=False):
        """Return a lightweight workflow estimate without claiming semantic output completeness."""
        text = str(message or "").strip()
        code = str(stage_code or "").strip()
        if NovelWritingTab._status_message_is_terminal(text):
            return 100
        if not active and code in {"", "status", "global:status"}:
            return 0
        if any(marker in text for marker in ("正在解析", "解析和校验", "结果已接收")):
            return 84
        if any(marker in text for marker in ("正在校验", "正在检查", "正在复核")):
            return 92
        if any(marker in text for marker in ("正在提交", "正在写入", "已应用")):
            return 98

        ranges = {
            "memory_finalize": (10, 78, 6000),
            "memory_repair": (80, 90, 5000),
            "logic_repair": (80, 90, 3500),
            "memory_reconcile": (90, 97, 3500),
            "summary": (10, 88, 3000),
            "outline": (10, 88, 1600),
            "draft": (10, 78, 10000),
            "style_finalize": (10, 78, 8000),
            "style_rewrite": (10, 78, 8000),
        }
        start, end, estimated_chars = ranges.get(code, (10, 78, 6000))
        try:
            chars = max(0, int(received_chars or 0))
        except (TypeError, ValueError):
            chars = 0
        if chars <= 0:
            return start
        progress = start + int(chars * (end - start) / max(1, estimated_chars))
        return min(end, max(start + 1, progress))

    def _refresh_status_display(self):
        current_path = self._canonical_project_path(
            getattr(self, "current_project_path", "")
        )
        status_path = self._canonical_project_path(
            getattr(self, "_status_project_path", "")
        )
        if current_path and status_path and current_path != status_path:
            if hasattr(self, "status_label"):
                self.status_label.setText("")
                self.status_label.setToolTip("")
            if hasattr(self, "status_meta_label"):
                self.status_meta_label.setText("")
                self.status_meta_label.setToolTip("")
            return
        has_active_work = self._status_has_active_work()
        if bool(getattr(self, "_status_workflow_active", False)) and not has_active_work:
            self._status_end_workflow()
        elif (
            bool(getattr(self, "_status_stage_active", False))
            and str(getattr(self, "_status_stage_key", "") or "").endswith(":stopping")
            and not has_active_work
        ):
            self._status_close_current_stage()
        message = str(getattr(self, "_status_message", "") or "")
        received_chars = int(getattr(self, "_status_received_chars", 0) or 0)
        suffix_parts = []
        if received_chars > 0:
            suffix_parts.append(f"已接收字符：{received_chars}")
        if suffix_parts:
            suffix = "；" + "；".join(suffix_parts)
            available = max(0, 180 - len(suffix))
            if len(message) > available:
                message = message[:max(0, available - 3)] + "..."
            display_message = message + suffix
        else:
            display_message = message if len(message) <= 180 else message[:177] + "..."
        if hasattr(self, "status_label"):
            self.status_label.setText(display_message)
            self.status_label.setToolTip(display_message)

        progress_parts = []
        detached_auto_active = self._detached_auto_status_is_current()
        auto_active = bool(getattr(self, "_auto_expand_all_active", False)) or detached_auto_active
        if auto_active or message.startswith("自动扩写"):
            if detached_auto_active:
                current, total = getattr(self, "_detached_auto_status_auto_progress", (0, 0))
            else:
                current, total = self._auto_expand_all_chapter_progress()
            if message.startswith("自动扩写完成") and total:
                current = total
            if current and total:
                progress_parts.append(f"自动扩写 {current}/{total}")
        _, chapter_scope = self._status_current_chapter_scope()
        stage_label = str(getattr(self, "_status_stage_label", "") or "")
        if chapter_scope and stage_label not in {"状态更新", "批次完成", "批次已中止", "批次已停止"}:
            progress_parts.append(chapter_scope)
        if stage_label:
            progress_parts.append(stage_label)

        timing_parts = []
        stage_started_wall = float(getattr(self, "_status_stage_started_wall", 0.0) or 0.0)
        stage_started_at = float(getattr(self, "_status_stage_started_at", 0.0) or 0.0)
        now_mono = time.monotonic()
        if stage_started_wall:
            timing_parts.append(time.strftime("%H:%M:%S 开始", time.localtime(stage_started_wall)))
        if bool(getattr(self, "_status_stage_active", False)) and stage_started_at:
            timing_parts.append("本阶段 " + self._format_status_elapsed(now_mono - stage_started_at))
        workflow_started_at = float(getattr(self, "_status_workflow_started_at", 0.0) or 0.0)
        if bool(getattr(self, "_status_workflow_active", False)) and workflow_started_at:
            timing_parts.append("本轮 " + self._format_status_elapsed(now_mono - workflow_started_at))
        elif float(getattr(self, "_status_last_run_elapsed", 0.0) or 0.0) > 0:
            timing_parts.append("本轮共 " + self._format_status_elapsed(self._status_last_run_elapsed))
        meta_text = " · ".join(progress_parts)
        if timing_parts:
            meta_text += ("\n" if meta_text else "") + " · ".join(timing_parts)
        if hasattr(self, "status_meta_label"):
            self.status_meta_label.setText(meta_text)
            self.status_meta_label.setToolTip(meta_text)

    def _on_novel_output_chars(self, count):
        if self._forward_chapter_task_signal("_on_novel_output_chars", count):
            return
        try:
            count = max(0, int(count or 0))
        except (TypeError, ValueError):
            return
        self._status_received_chars = count
        self._refresh_status_display()

    def _connect_novel_worker_status(self, worker):
        if worker is None:
            return
        worker.progress.connect(self.set_status_tip)
        output_signal = getattr(worker, "output_chars", None)
        if output_signal is not None:
            output_signal.connect(self._on_novel_output_chars)

    def set_status_tip(self, text):
        if self._forward_chapter_task_signal("set_status_tip", text):
            return
        current_path = self._canonical_project_path(
            getattr(self, "current_project_path", "")
        )
        status_path = self._canonical_project_path(
            getattr(self, "_status_project_path", "")
        )
        if current_path and status_path and current_path != status_path:
            return
        self._status_project_path = current_path or status_path
        text = str(text or "")
        self.setToolTip("")
        self._status_message = text
        self._track_status_message(text)
        self._refresh_status_display()
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
