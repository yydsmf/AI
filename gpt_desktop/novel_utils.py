import os
import re
import uuid
import hashlib
import json
import math
from copy import deepcopy
from collections import Counter
from difflib import SequenceMatcher

from .core import now_str

CHAPTER_ANALYSIS_HASH_VERSION = "2"
CHAPTER_ANALYSIS_STATUS_VERSION = "1"
CHAPTER_ANALYSIS_SMALL_CHANGE_RATIO = 0.10
CHAPTER_ANALYSIS_STATUS_CURRENT = "current"
CHAPTER_ANALYSIS_STATUS_SMALL_CHANGE = "small_change"
CHAPTER_ANALYSIS_STATUS_PENDING = "pending"
CHAPTER_ANALYSIS_STATUS_UNWRITTEN = "unwritten"
CHAPTER_ANALYSIS_QUICK_SIMILARITY_LOCAL_RATIO_LIMIT = 0.50
NOVEL_AI_CONTEXT_LIMIT = 120000
# Continuation data is kept separate from ordinary writing state so a new
# volume can inherit continuity without importing the previous manuscript.
VOLUME_CONTINUATION_SCHEMA_VERSION = "1"
VOLUME_TWO_FRAMEWORK_TEMPLATE = (
    "小说模板\n"
    "项目信息：\n"
    "1、书名\n"
    "类型\n"
    "风格\n"
    "故事核心：一至二句话说明。\n\n"
    "一、圣经：\n"
    "小说圣经：核心设定、故事节奏、主题、主线矛盾、结局方向等。\n"
    "世界观/规则：世界运行规则、势力结构、能力限制、时代背景、地点规则等。\n"
    "章节规划：整个小说的故事主线，从开始到结束。不要圆满结局，方便续写\n"
    "二、主要人物（每阶段至少5人）：\n"
    "姓名\n"
    "身份\n"
    "人物目标\n"
    "隐藏秘密\n"
    "语言风格\n"
    "备注\n"
    "设定：\n"
    "名称\n"
    "类型：地点、势力、物品、规则、术语、事件、其它\n"
    "说明"
)
# Volume handoff is a planning request, not a manuscript request. Keep a
# reserve for prompts and the model response instead of filling the whole
# application context window with raw project records.
VOLUME_HANDOFF_SOURCE_CHAR_BUDGET = 105000
VOLUME_FRAMEWORK_HANDOFF_CHAR_BUDGET = 90000
VOLUME_HANDOFF_LAST_CHAPTER_CHAR_LIMIT = 24000
# A volume handoff is sent as a system prompt plus a structured user payload.
# Keep a fixed reserve so either request remains below the application's
# 120,000-character context ceiling even when its prompt changes slightly.
VOLUME_CONTINUATION_REQUEST_CHAR_BUDGET = NOVEL_AI_CONTEXT_LIMIT - 8000
VOLUME_HANDOFF_RECENT_CHAPTER_COUNT = 8
# The compact index normally stays close to 15k, but quality-critical reference
# coverage may grow beyond that. The overall 120k context builder remains the
# final safety boundary.
LONG_FORM_SELECTION_INDEX_LIMIT = 48000
LONG_FORM_STATE_DIRECTORY_LIMIT = 18000
LONG_FORM_MEMORY_FINALIZE_INDEX_LIMIT = 24000
LONG_FORM_MEMORY_IDENTITY_INDEX_LIMIT = 6000
LONG_FORM_CONTEXT_SAFETY_MARGIN = 2048
LONG_FORM_CONTEXT_HARD_RESERVE = 20000
LONG_FORM_CONTEXT_SOFT_LIMIT = NOVEL_AI_CONTEXT_LIMIT - LONG_FORM_CONTEXT_HARD_RESERVE
LONG_FORM_STAGE_REVIEW_SCOPE = "stage_boundary_delta"
LONG_FORM_RECONCILIATION_CONTEXT_LIMIT = 90000
LONG_FORM_MAX_FACT_UPDATES = 12
LONG_FORM_MAX_LONG_TERM_EVENTS = 8
LONG_FORM_MAX_RECORD_UPDATES = 6
LONG_FORM_MAX_STATE_ITEMS = 10
LONG_FORM_MAX_FACT_CONTINUITY_DETAILS = 6
LONG_FORM_FACT_CONTINUITY_DETAIL_LIMIT = 1200
# The model may return the semantic state delta once and let the client expand
# deterministic review/index fields. Existing version-2 payloads remain valid.
LONG_FORM_COMPACT_DELTA_VERSION = 1
STYLE_FINALIZE_SOURCE_CONTEXT_LIMIT = 60000
CHAPTER_ANALYSIS_STATUS_LABELS = {
    CHAPTER_ANALYSIS_STATUS_CURRENT: "已AI分析",
    CHAPTER_ANALYSIS_STATUS_SMALL_CHANGE: "小改",
    CHAPTER_ANALYSIS_STATUS_PENDING: "待AI分析",
    CHAPTER_ANALYSIS_STATUS_UNWRITTEN: "未写正文",
}
_STORY_ORDER_MISSING = 10 ** 9
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


def _safe_name(name):
    name = str(name or "").strip()
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name.strip(" .")


def _as_text(value):
    return value if isinstance(value, str) else str(value or "")


def _compact_text(value):
    return re.sub(r"\s+", "", str(value or ""))


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
        return _STORY_ORDER_MISSING
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
    return min(hits) if hits else _STORY_ORDER_MISSING


def _infer_chapter_status(chap, preserve_manual=True):
    chap = chap if isinstance(chap, dict) else {}
    current = str(chap.get("status", "") or "").strip()
    if preserve_manual and current and current not in {"大纲"}:
        return current
    text_chars = len(_compact_text(chap.get("text", "")))
    outline_chars = len(_compact_text(chap.get("outline", "")))
    summary_chars = len(_compact_text(chap.get("summary", "")))
    fact_chars = len(_compact_text(chap.get("key_facts", "")))
    if text_chars and (summary_chars or fact_chars):
        return "已完成"
    if text_chars:
        return "写作中"
    if outline_chars:
        return "大纲"
    return current or "大纲"


_FORESHADOW_RECOVERY_NEGATIVE_TERMS = (
    "未回收", "尚未回收", "没有回收", "待回收", "还未回收",
    "未兑现", "尚未兑现", "没有兑现", "待兑现", "还未兑现",
    "未揭晓", "尚未揭晓", "没有揭晓", "待揭晓", "还未揭晓",
    "未揭示", "尚未揭示", "没有揭示", "待揭示", "还未揭示",
    "未解开", "尚未解开", "没有解开", "待解开", "还未解开",
    "未解释", "尚未解释", "没有解释", "待解释", "还未解释",
    "真相未明", "真相未大白", "真相尚未大白", "尚未真相大白",
)


def _has_foreshadow_recovery_negative(text):
    return any(k in str(text or "") for k in _FORESHADOW_RECOVERY_NEGATIVE_TERMS)


def _infer_foreshadow_status(item, preserve_manual=True):
    item = item if isinstance(item, dict) else {}
    current = str(item.get("status", "") or "").strip()
    valid_statuses = {"未埋", "已埋", "已回收", "无需回收", "废弃"}
    if current in valid_statuses:
        return current

    # Keep this conservative: only normalize the explicit status field.
    # Narrative text such as "揭晓/确认/解释" is too easy to misread and
    # should stay as AI/user-reviewed content, not become an automatic status.
    status_text = current.lower()
    if any(k in current for k in ("无需回收", "不必回收", "不用回收", "无须回收", "不需要回收", "无需继续回收", "无需追踪")):
        return "无需回收"
    if any(k in current for k in ("废弃", "作废", "弃用", "不再使用")):
        return "废弃"
    if (
        any(k in current for k in ("已回收", "回收完成", "已兑现", "兑现完成"))
        or status_text in {"resolved", "done", "closed", "paid_off", "payoff"}
    ):
        return "已回收"
    if (
        any(k in current for k in ("已埋", "已埋设", "埋设", "已铺垫", "待回收", "未回收", "待兑现"))
        or status_text in {
            "open", "active", "buried", "setup", "seeded", "advanced",
            "progressed", "reinforced",
        }
    ):
        return "已埋"
    if any(k in current for k in ("未埋", "未出现", "待埋")) or status_text in {"new", "planned", "unburied"}:
        return "未埋"
    return "未埋"


_FORESHADOW_STATUS_RANK = {"": 0, "未埋": 1, "已埋": 2, "无需回收": 3, "已回收": 4, "废弃": 5}


def _merge_foreshadow_status(existing, incoming):
    old = _infer_foreshadow_status({"status": existing}, preserve_manual=False) if str(existing or "").strip() else ""
    new = _infer_foreshadow_status({"status": incoming}, preserve_manual=False) if str(incoming or "").strip() else ""
    if not new:
        return old
    if not old:
        return new
    return new if _FORESHADOW_STATUS_RANK.get(new, 0) >= _FORESHADOW_STATUS_RANK.get(old, 0) else old


def _normalize_foreshadow_code(value):
    text = str(value or "").strip().upper()
    if not text:
        return ""
    text = re.sub(r"\s+", "", text)
    match = re.search(r"F0*(\d{1,7})", text)
    if not match and re.fullmatch(r"\d{1,7}", text):
        match = re.match(r"0*(\d{1,7})", text)
    if not match:
        return ""
    try:
        number = int(match.group(1))
    except Exception:
        return ""
    if number <= 0:
        return ""
    return f"F{number:04d}"


def _clean_foreshadow_name(value):
    text = str(value or "").strip()
    cleaned = re.sub(
        r"^F0*\d{1,7}\s*(?:[|｜:：·.、_\-—]+\s*)+",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or text


def _normalize_foreshadow_chapter_ref(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"\d{1,4}", text):
        try:
            number = int(text)
        except Exception:
            return text
        if number > 0:
            return f"第{number}章"
    return text


def _foreshadow_code_number(value):
    code = _normalize_foreshadow_code(value)
    if not code:
        return 0
    try:
        return int(code[1:])
    except Exception:
        return 0


def _ensure_foreshadow_codes(project):
    project = project if isinstance(project, dict) else {}
    items = project.get("foreshadow_items", [])
    if not isinstance(items, list):
        return project
    used = set()
    max_number = 0
    missing = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cleaned_name = _clean_foreshadow_name(item.get("name", ""))
        if cleaned_name and cleaned_name != str(item.get("name", "") or "").strip():
            item["name"] = cleaned_name
        raw_code = (
            item.get("code", "")
            or item.get("foreshadow_code", "")
            or item.get("编号", "")
            or item.get("伏笔编号", "")
        )
        code = _normalize_foreshadow_code(raw_code)
        number = _foreshadow_code_number(code)
        if not code or code in used:
            missing.append(item)
            item["code"] = ""
            continue
        item["code"] = code
        used.add(code)
        max_number = max(max_number, number)
    for item in missing:
        while True:
            max_number += 1
            code = f"F{max_number:04d}"
            if code not in used:
                break
        item["code"] = code
        used.add(code)
    return project


def _chapter_label(index, chap):
    chap = chap if isinstance(chap, dict) else {}
    title = str(chap.get("title", "") or "").strip()
    if title:
        return f"第 {index} 章「{title}」"
    return f"第 {index} 章"


def _auto_classify_default_statuses(project, chapter_ids=None):
    project = project if isinstance(project, dict) else {}
    chapter_id_set = {str(x) for x in (chapter_ids or []) if str(x)} if chapter_ids is not None else None
    changed = {"chapters": 0, "foreshadows": 0}
    for chap in project.get("chapters", []) if isinstance(project.get("chapters", []), list) else []:
        if not isinstance(chap, dict):
            continue
        if chapter_id_set is not None and str(chap.get("id", "") or "") not in chapter_id_set:
            continue
        status = _infer_chapter_status(chap)
        if status != str(chap.get("status", "") or "").strip():
            chap["status"] = status
            changed["chapters"] += 1
    return changed


def _normalize_name_list(value):
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[,，、;；/／|｜\n]+", str(value or ""))
    out = []
    seen = set()
    for item in raw_items:
        text = str(item or "").strip()
        text = re.sub(r"^(?:姓名|名字|名称|人物|角色|关联人物|出场人物|涉及人物)[：:]\s*", "", text).strip()
        if re.search(r"[（(][^（）()]{1,16}[）)]$", text):
            without_tail = re.sub(r"[（(][^（）()]{1,16}[）)]$", "", text).strip()
            if without_tail:
                text = without_tail
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


_COMMON_CHINESE_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费"
    "廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和"
    "穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋庞熊纪舒屈项祝董梁杜阮"
    "蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田胡凌霍虞万支"
    "柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚程邢裴陆荣"
    "翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓"
    "蓬全郗班仰秋仲伊宫宁仇栾暴甘斜厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟"
    "薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴郁胥能苍双闻莘党翟谭贡劳"
    "逄姬申扶堵冉宰郦雍郤璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎"
    "充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙"
    "东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须"
    "丰巢关蒯相查后荆红游竺权逯盖益桓公"
)
_COMMON_COMPOUND_SURNAMES = (
    "欧阳", "太史", "端木", "上官", "司马", "东方", "独孤", "南宫", "万俟", "闻人",
    "夏侯", "诸葛", "尉迟", "公羊", "赫连", "澹台", "皇甫", "宗政", "濮阳", "公冶",
    "太叔", "申屠", "公孙", "慕容", "仲孙", "钟离", "长孙", "宇文", "司徒", "鲜于",
    "司空", "闾丘", "子车", "亓官", "司寇", "巫马", "公西", "颛孙", "壤驷", "公良",
    "漆雕", "乐正", "宰父", "谷梁", "拓跋", "夹谷", "轩辕", "令狐", "段干", "百里",
    "呼延", "东郭", "南门", "羊舌", "微生", "公户", "公玉", "公仪", "梁丘", "公仲",
    "公上", "公门", "公山", "公坚", "左丘", "公伯", "西门", "公祖", "第五", "公乘",
    "贯丘", "公皙", "南荣", "东里", "东宫", "仲长", "子书", "子桑", "即墨", "达奚",
    "褚师",
)
_CHARACTER_TITLE_WORDS = (
    "太皇太后", "皇太后", "摄政王", "长公主", "大将军", "二公主", "三公主", "四公主",
    "五公主", "六公主", "七公主", "八公主", "九公主", "公主", "皇子", "太子", "王爷",
    "王妃", "郡主", "县主", "皇后", "太后", "皇上", "皇帝", "陛下", "殿下", "娘娘",
    "贵妃", "妃子", "公子", "姑娘", "小姐", "少爷", "将军", "丞相", "国师", "太傅",
    "侍卫", "掌柜", "师父", "师傅", "师尊", "宗主", "阁主", "门主", "帮主", "神医",
    "先生", "夫人", "大人", "世子", "侯爷", "王", "帝", "妃", "嫔",
)
_CHARACTER_TITLE_PATTERN = "|".join(
    re.escape(title) for title in sorted(_CHARACTER_TITLE_WORDS, key=len, reverse=True)
)
_COMMON_CHINESE_SURNAME_CHARS = re.escape(_COMMON_CHINESE_SURNAMES)
_CHARACTER_PAREN_ROLE_RE = re.compile(r"^([\u4e00-\u9fff]{2,4})[（(]([^（）()]{1,12})[）)]$")
_CHARACTER_TITLE_SINGLE_SURNAME_RE = re.compile(
    rf"^(.{{0,10}}?(?:{_CHARACTER_TITLE_PATTERN}))"
    rf"([{_COMMON_CHINESE_SURNAME_CHARS}][\u4e00-\u9fff]{{1,3}})$"
)
_CHARACTER_TITLE_COMPOUND_SURNAME_RE_LIST = tuple(
    re.compile(rf"^(.{{0,10}}?(?:{_CHARACTER_TITLE_PATTERN}))({re.escape(surname)}[\u4e00-\u9fff]{{1,2}})$")
    for surname in _COMMON_COMPOUND_SURNAMES
)


def _clean_entity_name(name):
    return str(name or "").strip().strip("「」『』《》<>[]【】（）()：:，,。；;、 \t\r\n")


def _looks_like_chinese_person_name(name):
    name = _clean_entity_name(name)
    if not re.fullmatch(r"[\u4e00-\u9fff]{2,4}", name):
        return False
    return name.startswith(_COMMON_COMPOUND_SURNAMES) or name[0] in _COMMON_CHINESE_SURNAMES


def _canonical_character_name_and_role(name):
    raw = _clean_entity_name(name)
    if not raw:
        return "", ""
    paren_match = _CHARACTER_PAREN_ROLE_RE.match(raw)
    if paren_match and _looks_like_chinese_person_name(paren_match.group(1)):
        return paren_match.group(1), paren_match.group(2).strip()
    match = _CHARACTER_TITLE_SINGLE_SURNAME_RE.match(raw)
    if match and _looks_like_chinese_person_name(match.group(2)):
        return match.group(2), match.group(1).strip()
    for pattern in _CHARACTER_TITLE_COMPOUND_SURNAME_RE_LIST:
        match = pattern.match(raw)
        if match and _looks_like_chinese_person_name(match.group(2)):
            return match.group(2), match.group(1).strip()
    return raw, ""


def _character_merge_key(item_or_name):
    if isinstance(item_or_name, dict):
        name = item_or_name.get("name", "")
    else:
        name = item_or_name
    canonical, _role_hint = _canonical_character_name_and_role(name)
    return _compact_text(canonical)


def _prepare_character_candidate(item, default_notes="AI 分析候选"):
    if not isinstance(item, dict):
        return None, None
    name = _clean_entity_name(item.get("name", ""))
    if not name:
        return None, None
    canonical_name, role_hint = _canonical_character_name_and_role(name)
    role = str(item.get("role", "") or "").strip()
    if role_hint and role_hint not in role:
        role = f"{role_hint}；{role}" if role else role_hint
    notes = str(item.get("notes", "") or default_notes).strip()
    if canonical_name != name and name not in notes:
        notes = f"{notes}\n别称：{name}" if notes else f"别称：{name}"
    return {
        "name": canonical_name,
        "role": role,
        "goal": str(item.get("goal", "") or ""),
        "secret": str(item.get("secret", "") or ""),
        "voice": str(item.get("voice", "") or ""),
        "notes": notes or default_notes,
    }, None


def _canonicalize_character_record(item):
    if not isinstance(item, dict):
        return "", ""
    old_name = _clean_entity_name(item.get("name", ""))
    canonical_name, role_hint = _canonical_character_name_and_role(old_name)
    if not old_name or canonical_name == old_name:
        return old_name, old_name
    item["name"] = canonical_name
    role = str(item.get("role", "") or "").strip()
    if role_hint and role_hint not in role:
        item["role"] = f"{role_hint}；{role}" if role else role_hint
    notes = str(item.get("notes", "") or "").strip()
    if old_name not in notes:
        item["notes"] = f"{notes}\n别称：{old_name}" if notes else f"别称：{old_name}"
    return old_name, canonical_name


_INTERNAL_CANDIDATE_MARKER_RE = re.compile(
    r"^(?:(?:补充|新增|补充说明)\s*[：:]\s*)?"
    r"(?:A\s*I\s*分析\s*候选|文档导入候选)"
    r"(?:\s*[：:]\s*)?",
    flags=re.IGNORECASE,
)


def _strip_internal_candidate_markers(value):
    """Remove internal candidate labels while preserving real record text."""
    kept = []
    for raw in str(value or "").splitlines():
        line = str(raw or "").strip()
        if not line:
            continue
        for _ in range(2):
            if _compact_text(line).lower() in {"ai分析候选", "文档导入候选"}:
                line = ""
                break
            cleaned = _INTERNAL_CANDIDATE_MARKER_RE.sub("", line, count=1).strip()
            if cleaned == line:
                break
            line = cleaned
        if line:
            kept.append(line)
    return _dedupe_text_lines("\n".join(kept))


def _clean_continuation_record_markers(item, text_fields):
    if not isinstance(item, dict):
        return deepcopy(item)
    cleaned = deepcopy(item)
    for field in text_fields:
        if field in cleaned:
            cleaned[field] = _strip_internal_candidate_markers(cleaned.get(field, ""))
    return cleaned


def _normalize_volume_continuity_anchors(value, limit=16):
    """Normalize temporary cross-volume facts used only by planning calls."""
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for raw in value:
        if isinstance(raw, str):
            raw = {"fact": raw}
        if not isinstance(raw, dict):
            continue
        category = _strip_internal_candidate_markers(
            raw.get("category", raw.get("type", ""))
        )
        fact = _strip_internal_candidate_markers(
            raw.get("fact", raw.get("statement", raw.get("description", "")))
        )
        if not fact:
            continue
        key = _compact_text(fact).lower()
        if not key or key in seen:
            continue
        source_chapters = raw.get("source_chapters", raw.get("sources", []))
        if isinstance(source_chapters, str):
            source_chapters = [
                item.strip()
                for item in re.split(r"[、,，;；\s]+", source_chapters)
                if item.strip()
            ]
        elif not isinstance(source_chapters, list):
            source_chapters = []
        source_chapters = [
            _clip_complete_text(item, 80)
            for item in source_chapters
            if str(item or "").strip()
        ][:8]
        item = {"fact": _clip_complete_text(fact, 260)}
        if category:
            item["category"] = _clip_complete_text(category, 60)
        if source_chapters:
            item["source_chapters"] = source_chapters
        result.append(item)
        seen.add(key)
        if len(result) >= max(1, int(limit or 16)):
            break
    return result


def _compact_volume_continuity_anchors(value, total_limit=3000):
    anchors = _normalize_volume_continuity_anchors(value)
    return _compact_volume_handoff_records(
        anchors,
        ("category", "fact", "source_chapters"),
        {"category": 60, "fact": 260, "source_chapters": 180},
        total_limit,
        minimal_fields=("fact",),
    )


def _normalize_series_continuation(value):
    """Normalize volume-continuation metadata without exposing it to body prompts."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in (
        "schema_version",
        "series_id",
        "volume_number",
        "parent_project_path",
        "parent_project_title",
        "parent_snapshot_hash",
        "template_hash",
        "created_at",
        "user_requirements",
    ):
        raw = value.get(key, "")
        if key == "volume_number":
            try:
                number = max(1, int(raw or 1))
            except Exception:
                number = 1
            result[key] = number
            continue
        text = str(raw or "").strip()
        if text:
            result[key] = text

    handoff = value.get("handoff", {})
    if isinstance(handoff, dict):
        normalized_handoff = {}
        try:
            selection_version = int(handoff.get("foreshadow_selection_version", 0) or 0)
        except Exception:
            selection_version = 0
        if selection_version > 0:
            normalized_handoff["foreshadow_selection_version"] = selection_version
        for key in (
            "volume_summary",
            "world_state",
        ):
            text = str(handoff.get(key, "") or "").strip()
            if text:
                normalized_handoff[key] = text
        for key in ("ending_state", "last_chapter"):
            item = handoff.get(key, {})
            if isinstance(item, dict):
                normalized_handoff[key] = deepcopy(item)
        inherited_materials = handoff.get("inherited_materials", {})
        if isinstance(inherited_materials, dict):
            materials = {}
            for key in ("bible", "world_rules"):
                text = str(inherited_materials.get(key, "") or "").strip()
                if text:
                    materials[key] = text
            if materials:
                normalized_handoff["inherited_materials"] = materials
        continuity_anchors = _normalize_volume_continuity_anchors(
            handoff.get("continuity_anchors", [])
        )
        if continuity_anchors:
            normalized_handoff["continuity_anchors"] = continuity_anchors
        record_text_fields = {
            "reusable_characters": ("notes",),
            "reusable_lore": ("description", "story_known"),
            "reusable_foreshadows": ("description", "revealed", "remaining_secret", "notes"),
            "deferred_foreshadows": ("description", "revealed", "remaining_secret", "notes"),
            "resolved_foreshadows": ("description", "revealed", "remaining_secret", "notes", "result"),
            "discarded_foreshadows": ("description", "revealed", "remaining_secret", "notes", "result"),
        }
        for key in (
            "character_states",
            "relationship_states",
            "resolved_threads",
            "open_threads",
            "reusable_characters",
            "reusable_lore",
            "reusable_foreshadows",
            "deferred_foreshadows",
            "resolved_foreshadows",
            "discarded_foreshadows",
            "continuity_boundaries",
        ):
            items = handoff.get(key, [])
            if not isinstance(items, list):
                continue
            normalized_items = []
            for item in items:
                if isinstance(item, dict):
                    cleaned = _clean_continuation_record_markers(
                        item,
                        record_text_fields.get(key, ()),
                    )
                elif isinstance(item, str):
                    cleaned = _strip_internal_candidate_markers(item)
                else:
                    continue
                if str(cleaned or "").strip():
                    normalized_items.append(cleaned)
            if key in handoff or normalized_items:
                normalized_handoff[key] = normalized_items

        terminal_keys = {
            _volume_handoff_record_key(item)
            for group_key in ("resolved_foreshadows", "discarded_foreshadows")
            for item in normalized_handoff.get(group_key, [])
            if isinstance(item, dict) and _volume_handoff_record_key(item)
        }
        normalized_handoff["deferred_foreshadows"] = [
            item
            for item in normalized_handoff.get("deferred_foreshadows", [])
            if not isinstance(item, dict)
            or (
                _infer_foreshadow_status(item, preserve_manual=False)
                not in {"已回收", "无需回收", "废弃"}
                and _volume_handoff_record_key(item) not in terminal_keys
            )
        ]
        if normalized_handoff:
            result["handoff"] = normalized_handoff
    contract = _normalize_creative_intent_contract(value.get("creative_intent_contract", {}))
    if contract:
        result["creative_intent_contract"] = contract
    return result


def _normalize_creative_intent_contract(value):
    """Normalize the user-confirmed story priority used by planning only."""
    if not isinstance(value, dict):
        return {}

    aliases = {
        "primary_line": ("primary_line", "main_line", "core_line", "主线", "核心主线"),
        "core_relationships": (
            "core_relationships", "relationship_progression", "核心关系", "关系推进",
        ),
        "stage_progression": ("stage_progression", "progression", "阶段推进", "阶段变化"),
        "reading_experience": (
            "reading_experience", "reader_experience", "读感", "读者体验",
        ),
        "supporting_line_usage": (
            "supporting_line_usage", "supporting_usage", "辅助线用法", "支线用法",
        ),
        "ending_boundaries": (
            "ending_boundaries", "ending_boundary", "结局边界", "结尾边界",
        ),
    }

    result = {}
    for target, source_keys in aliases.items():
        for source_key in source_keys:
            text = str(value.get(source_key, "") or "").strip()
            if text:
                result[target] = text
                break

    supporting_value = None
    for key in ("supporting_lines", "secondary_lines", "辅助线", "支线"):
        if key in value:
            supporting_value = value.get(key)
            break
    supporting_lines = _normalize_name_list(supporting_value)
    if supporting_lines:
        result["supporting_lines"] = supporting_lines[:16]

    version = str(value.get("version", value.get("schema_version", "")) or "").strip()
    if version:
        result["version"] = version
    source = str(value.get("source", "") or "").strip()
    if source:
        result["source"] = source
    for key in ("generated_at", "confirmed_at", "updated_at"):
        text = str(value.get(key, "") or "").strip()
        if text:
            result[key] = text
    return result


def _volume_two_framework_template_text():
    return VOLUME_TWO_FRAMEWORK_TEMPLATE


def _default_project():
    return {
        "meta": {
            "title": "未命名小说",
            "genre": "",
            "style": "",
            "pov": "第三人称",
            "target_words": "",
            "status": "草稿",
            "premise": "",
        },
        "bible": "",
        "world_rules": "",
        "characters": [],
        "lore": [],
        "chapters": [],
        "foreshadow_items": [],
        "timeline": "",
        "foreshadows": "",
        "summary": "",
        "style_reference": "",
        "style_profile_id": "",
        "style_profile_cache": {},
        "draft_note": "",
        "long_form_memory": _default_long_form_memory(),
        "imported_chapter_plan_reference": {},
        "imported_framework_source": {},
        "framework_import_state": {},
        "chapter_plan_generation_state": {},
        "chapter_plan_foundation": {},
        "narrative_strategy_profile": {},
        "creative_intent_contract": {},
        "series_continuation": {},
        "narrative_strategy_confirmation": {},
        "import_candidates": {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}},
        "updated_at": now_str(),
    }


def _normalize_narrative_strategy_profile(value):
    if not isinstance(value, dict):
        return {}
    text_fields = (
        "audience_direction",
        "genre_world",
        "core_reader_promise",
        "primary_story_engine",
        "secondary_story_engine",
        "planning_grammar",
        "pacing_strategy",
        "low_exposition_strategy",
        "forbidden_drift",
    )
    list_fields = (
        "satisfaction_currencies",
        "emotional_resonance_axes",
        "chapter_variation_pool",
    )
    result = {
        key: str(value.get(key, "") or "").strip()
        for key in text_fields
        if str(value.get(key, "") or "").strip()
    }
    for key in list_fields:
        items = _normalize_name_list(value.get(key, []))
        if items:
            result[key] = items[:24]
    version = str(value.get("version", "") or "").strip()
    if version:
        result["version"] = version
    updated_at = str(value.get("updated_at", "") or "").strip()
    if updated_at:
        result["updated_at"] = updated_at
    return result


def _clean_chapter_plan_story_boundary(value):
    text = str(value or "").strip()
    if not text:
        return ""
    technical_markers = (
        "stages.events",
        "source_event_ids",
        "节点id",
        "json字段",
        "不虚构来源节点",
    )
    parts = re.split(r"(?<=[。！？!?；;])\s*", text)
    kept = [
        part.strip()
        for part in parts
        if part.strip() and not any(marker in part.lower() for marker in technical_markers)
    ]
    cleaned = "".join(kept).strip().rstrip("；; ")
    if cleaned and cleaned[-1] not in "。！？!?":
        cleaned += "。"
    return cleaned


def _normalize_chapter_plan_foundation(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in (
        "summary", "core_mainline", "ending_promise", "global_hard_boundaries",
    ):
        field_value = str(value.get(key, "") or "").strip()
        if key == "global_hard_boundaries":
            field_value = _clean_chapter_plan_story_boundary(field_value)
        if field_value:
            result[key] = field_value
    for key in (
        "target_words", "average_chapter_words", "total_chapter_count", "existing_chapter_count",
    ):
        try:
            result[key] = max(0, int(value.get(key, 0) or 0))
        except Exception:
            result[key] = 0
    profile = _normalize_narrative_strategy_profile(value.get("narrative_strategy_profile", {}))
    if profile:
        result["narrative_strategy_profile"] = profile
    contract = _normalize_creative_intent_contract(value.get("creative_intent_contract", {}))
    if contract:
        result["creative_intent_contract"] = contract
    arc_fields = (
        "name", "macro_phase", "source_stage", "dominant_line", "supporting_lines",
        "relationship_goal", "end_state", "goal", "main_conflict", "turning_points",
        "reader_payoff", "emotional_arc", "pacing_pattern", "exposition_compression",
        "variation_plan", "investigation_scope", "forbidden",
    )
    arcs = []
    for item in value.get("arcs", []) if isinstance(value.get("arcs"), list) else []:
        if not isinstance(item, dict):
            continue
        try:
            start = int(item.get("start_chapter", 0) or 0)
            end = int(item.get("end_chapter", 0) or 0)
        except Exception:
            continue
        if start <= 0 or end < start:
            continue
        arc = {"start_chapter": start, "end_chapter": end}
        for key in arc_fields:
            field_value = str(item.get(key, "") or "").strip()
            if field_value:
                arc[key] = field_value
        arcs.append(arc)
    if arcs:
        result["arcs"] = arcs
    return result


def _default_long_form_memory():
    return {
        "schema_version": "2",
        "revision": 0,
        "state_snapshot": {
            "as_of_chapter_id": "",
            "as_of_chapter_index": 0,
            "story_time": "",
            "location": "",
            "character_states": [],
            "relationship_states": [],
            "object_states": [],
            "active_conflicts": [],
            "unresolved_tasks": [],
            "notes": "",
            "updated_at": "",
        },
        "active_facts": [],
        "fact_history": [],
        "stage_archives": [],
        "record_runtime": {
            "characters": {},
            "lore": {},
            "foreshadows": {},
        },
        "issued_state_ids": {
            "objects": [],
            "conflicts": [],
            "tasks": [],
        },
        "update_journal": [],
        "updated_at": "",
    }


def _normalize_long_form_memory(value):
    base = _default_long_form_memory()
    if not isinstance(value, dict):
        return base
    snapshot = value.get("state_snapshot", {})
    if isinstance(snapshot, dict):
        for key in base["state_snapshot"]:
            if key in snapshot:
                base["state_snapshot"][key] = deepcopy(snapshot[key])
    active_facts = value.get("active_facts", [])
    if isinstance(active_facts, list):
        base["active_facts"] = [deepcopy(item) for item in active_facts if isinstance(item, (dict, str))]
    fact_history = value.get("fact_history", [])
    if isinstance(fact_history, list):
        base["fact_history"] = [deepcopy(item) for item in fact_history if isinstance(item, dict)]
    archives = value.get("stage_archives", [])
    if isinstance(archives, list):
        base["stage_archives"] = [deepcopy(item) for item in archives if isinstance(item, dict)]
    runtime = value.get("record_runtime", {})
    if isinstance(runtime, dict):
        for kind in ("characters", "lore", "foreshadows"):
            items = runtime.get(kind, {})
            if isinstance(items, dict):
                base["record_runtime"][kind] = {
                    str(item_id): deepcopy(item)
                    for item_id, item in items.items()
                    if str(item_id).strip() and isinstance(item, dict)
                }
    issued_state_ids = value.get("issued_state_ids", {})
    if isinstance(issued_state_ids, dict):
        for kind in ("objects", "conflicts", "tasks"):
            values = issued_state_ids.get(kind, [])
            if isinstance(values, list):
                base["issued_state_ids"][kind] = sorted({
                    str(item or "").strip()
                    for item in values
                    if str(item or "").strip()
                })
    journal = value.get("update_journal", [])
    if isinstance(journal, list):
        base["update_journal"] = [deepcopy(item) for item in journal if isinstance(item, dict)][-500:]
    try:
        base["revision"] = max(0, int(value.get("revision", 0) or 0))
    except Exception:
        base["revision"] = 0
    base["updated_at"] = str(value.get("updated_at", "") or "")
    return base


def _fact_with_continuity_context(item, detail_limit=500):
    if not isinstance(item, dict):
        return ""
    fact = str(item.get("fact", "") or "").strip()
    details = item.get("continuity_details", [])
    details = details if isinstance(details, list) else []
    detail_texts = []
    seen = {_compact_text(fact)} if fact else set()
    for detail in details:
        text = str(
            detail.get("fact", "") if isinstance(detail, dict) else detail
            or ""
        ).strip()
        compact = _compact_text(text)
        if not compact or compact in seen:
            continue
        seen.add(compact)
        detail_texts.append(text)
    if not detail_texts:
        return fact
    retained = _clip_context_text(
        "；".join(detail_texts),
        max(0, int(detail_limit or 0)),
        preserve_lines=True,
    )
    if not retained:
        return fact
    return (
        f"{fact}｜同主题既有证据细节（仅用于继承；与当前状态冲突时以当前事实为准）："
        f"{retained}"
    )


def _fact_with_memory_history_context(item, memory, detail_limit=500):
    if not isinstance(item, dict):
        return ""
    item_id = str(item.get("id", "") or "").strip()
    enriched = deepcopy(item)
    details = (
        deepcopy(enriched.get("continuity_details", []))
        if isinstance(enriched.get("continuity_details"), list) else []
    )
    if item_id and isinstance(memory, dict):
        for historical in reversed(memory.get("fact_history", [])):
            if not isinstance(historical, dict):
                continue
            if str(historical.get("id", "") or "").strip() != item_id:
                continue
            fact = str(historical.get("fact", "") or "").strip()
            if not fact:
                continue
            details.append({
                "fact": fact,
                "source_chapter_index": int(
                    historical.get(
                        "evidence_chapter_index",
                        historical.get("source_chapter_index", 0),
                    ) or 0
                ),
                "evidence": str(
                    historical.get("evidence", historical.get("history_evidence", ""))
                    or ""
                ).strip(),
            })
            if len(details) >= LONG_FORM_MAX_FACT_CONTINUITY_DETAILS:
                break
    enriched["continuity_details"] = details
    return _fact_with_continuity_context(enriched, detail_limit=detail_limit)


_PRIVATE_PROJECT_NOTE_KEYS = {
    "draft_note",
    "imported_chapter_plan_reference",
    "imported_framework_source",
    "framework_import_state",
    "style_profile_cache",
    "chapter_plan_generation_state",
    "chapter_plan_foundation",
    "narrative_strategy_confirmation",
    "creative_intent_contract",
    "series_continuation",
    "auto_expand_resume_required",
}


def _project_without_private_notes(project):
    if not isinstance(project, dict):
        return {}

    def scrub(value):
        if isinstance(value, dict):
            return {
                key: scrub(child)
                for key, child in value.items()
                if str(key) not in _PRIVATE_PROJECT_NOTE_KEYS
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(project)


def _new_character(index):
    return {
        "id": uuid.uuid4().hex,
        "name": f"人物 {index + 1}",
        "role": "",
        "goal": "",
        "secret": "",
        "voice": "",
        "notes": "",
    }


def _character_role_from_string_canon(value):
    """Extract only an opening identity phrase from a string-form character canon."""
    text = str(value or "").strip()
    if not text:
        return ""
    opening = re.split(r"[。！？!?；;\n]", text, maxsplit=1)[0].strip(" ，,：:")
    if not opening or opening.startswith(("本章", "本次", "当前", "此章", "此次")):
        return ""
    return opening[:120].strip(" ，,：:")


def _apply_character_string_canon(record, canon):
    """Keep string canon text and fill only an otherwise empty identity field."""
    if not isinstance(record, dict) or not isinstance(canon, str):
        return {}
    text = canon.strip()
    if not text:
        return {}

    changed = {}
    notes = str(record.get("notes", "") or "").strip()
    if not notes:
        record["notes"] = text
        changed["notes"] = text
    elif text not in notes:
        record["notes"] = f"{notes}；{text}"
        changed["notes"] = record["notes"]

    role = _character_role_from_string_canon(text)
    if role and not str(record.get("role", "") or "").strip():
        record["role"] = role
        changed["role"] = role
    return changed


_TEMPORARY_CHARACTER_NAME_MARKERS = (
    "姓名未明", "姓名不详", "姓名未知", "名字未明", "名字不详", "名字未知",
    "身份未明", "身份不详", "身份未知", "未命名", "无名", "匿名", "待定",
)
_GENERIC_CHARACTER_NAME_LABELS = {
    "内门弟子", "外门弟子", "内门天才", "外门天才", "陌生人", "神秘人",
    "黑衣人", "灰衣人", "白衣人", "来客", "路人", "弟子", "长老",
}


def _is_temporary_character_name(value):
    """Return whether a character label explicitly says its name is unresolved."""
    text = _clean_entity_name(value)
    compact = _compact_text(text)
    return bool(
        compact
        and (
            any(marker in compact for marker in _TEMPORARY_CHARACTER_NAME_MARKERS)
            or compact in {_compact_text(label) for label in _GENERIC_CHARACTER_NAME_LABELS}
        )
    )


def _merge_character_identity_text(current, incoming):
    """Keep established text while absorbing a newer or more specific description."""
    current = str(current or "").strip()
    incoming = str(incoming or "").strip()
    if not incoming:
        return current
    if not current:
        return incoming
    current_compact = _compact_text(current).casefold()
    incoming_compact = _compact_text(incoming).casefold()
    if not current_compact or current_compact == incoming_compact:
        return current
    if current_compact in incoming_compact:
        return incoming
    if incoming_compact in current_compact:
        return current
    return f"{current}；{incoming}"


def _merge_character_identity_fields(record, incoming_fields):
    """Merge explicit identity details while retaining older information."""
    if not isinstance(record, dict) or not isinstance(incoming_fields, dict):
        return {}

    changed = {}
    for field in ("role", "goal", "secret", "voice"):
        incoming = str(incoming_fields.get(field, "") or "").strip()
        current = str(record.get(field, "") or "").strip()
        merged = _merge_character_identity_text(current, incoming)
        if merged != current:
            record[field] = merged
            changed[field] = merged

    incoming_notes = str(incoming_fields.get("notes", "") or "").strip()
    current_notes = str(record.get("notes", "") or "").strip()
    merged_notes = _merge_character_identity_text(current_notes, incoming_notes)
    if merged_notes != current_notes:
        record["notes"] = merged_notes
        changed["notes"] = merged_notes
    return changed


def _character_identity_fields_from_item(item):
    """Read character identity fields from current and legacy response shapes."""
    if not isinstance(item, dict):
        return {}

    aliases = {
        "role": ("role", "identity", "character_role", "身份", "角色定位", "人物身份", "定位"),
        "goal": ("goal", "target", "motive", "motivation", "objective", "目标", "人物目标", "动机", "诉求"),
        "secret": ("secret", "hidden_secret", "private_secret", "秘密", "隐藏秘密", "隐情"),
        "voice": ("voice", "language_style", "speaking_style", "tone", "语言风格", "说话风格", "口吻", "语气"),
        "notes": ("notes", "说明", "备注", "人物关系", "关系变化"),
    }
    sources = []
    for key in ("identity_patch", "canon", "fields"):
        value = item.get(key)
        if isinstance(value, dict):
            sources.append(value)
    sources.append(item)

    placeholder_markers = (
        "仅新增时填写",
        "正文明确的身份",
        "正文明确的目标",
        "正文明确且值得保留的隐情",
        "正文中足够明显的语言/口吻特征",
        "无证据留空",
        "证据不足留空",
    )

    def usable(value):
        value = str(value or "").strip()
        if not value or any(marker in value for marker in placeholder_markers):
            return ""
        return value

    result = {}
    for field, field_aliases in aliases.items():
        for source in sources:
            for key in field_aliases:
                value = usable(source.get(key, ""))
                if value:
                    result[field] = value
                    break
            if field in result:
                break
    return result


def _promote_character_identity(record, incoming_name, incoming_fields=None):
    """Rename a temporary character and merge explicit identity details, keeping its ID."""
    if not isinstance(record, dict):
        return {}
    old_name = str(record.get("name", "") or "").strip()
    new_name = _clean_entity_name(incoming_name)
    if (
        not old_name
        or not new_name
        or _compact_text(old_name).casefold() == _compact_text(new_name).casefold()
        or not _is_temporary_character_name(old_name)
        or _is_temporary_character_name(new_name)
    ):
        return {}

    changed = {"name": new_name}
    record["name"] = new_name
    notes = str(record.get("notes", "") or "").strip()
    old_label = f"旧名：{old_name}"
    if old_label not in notes:
        record["notes"] = f"{notes}\n{old_label}".strip()
        changed["notes"] = record["notes"]
    changed.update(_merge_character_identity_fields(record, incoming_fields))
    return changed


def _new_chapter(index):
    return {
        "id": uuid.uuid4().hex,
        "title": f"章节 {index + 1}",
        "unit_type": "chapter",
        "status": "大纲",
        "outline": "",
        "draft_words": "",
        "text": "",
        "summary": "",
        "key_facts": "",
        "linked_characters": [],
        "source_event_ids": [],
        "actual_linked_character_ids": [],
        "state_delta": {},
        "long_term_events": [],
        "state_reconciliation": {},
        "memory_selection": {},
        "memory_sync_status": "pending",
        "memory_revision": 0,
        "memory_update_hash": "",
        "memory_sync_error": "",
        "memory_boundary_integrity": {},
        "memory_reconciliation_status": "",
        "memory_reconciliation_error": "",
        "ai_generation_checkpoint": {},
        "auto_expand_resume_required": False,
        "analysis_hash": "",
        "analysis_hash_version": "",
        "analysis_analyzed_at": "",
        "analysis_baseline": "",
        "analysis_linked_hash": "",
        "analysis_status": CHAPTER_ANALYSIS_STATUS_UNWRITTEN,
        "analysis_status_hash": "",
        "analysis_status_version": CHAPTER_ANALYSIS_STATUS_VERSION,
    }


def _new_lore(index):
    return {
        "id": uuid.uuid4().hex,
        "name": f"设定 {index + 1}",
        "type": "地点",
        "description": "",
        "story_known": "",
    }


def _new_foreshadow(index):
    return {
        "id": uuid.uuid4().hex,
        "code": f"F{index + 1:04d}",
        "name": f"伏笔 {index + 1}",
        "status": "未埋",
        "setup_chapter": "",
        "payoff_chapter": "",
        "description": "",
        "revealed": "",
        "remaining_secret": "",
        "notes": "",
    }


def _normalize_analysis_chunk_state(items):
    failed_chunks = []
    for fallback_index, item in enumerate(items if isinstance(items, list) else [], 1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "") or "").strip()
        if not text:
            continue
        chunk = {
            "index": item.get("index", fallback_index),
            "total": item.get("total", 0),
            "text": text,
            "error": str(item.get("error", "") or ""),
        }
        chapter_id = str(item.get("chapter_id", "") or "").strip()
        chapter_title = str(item.get("chapter_title", "") or "").strip()
        if chapter_id:
            chunk["chapter_id"] = chapter_id
        if chapter_title:
            chunk["chapter_title"] = chapter_title
        for field in ("review_flow", "source_label", "chunk_key"):
            value = str(item.get(field, "") or "").strip()
            if value:
                chunk[field] = value
        failed_chunks.append(chunk)
    failed_chunks.sort(key=lambda item: _analysis_chunk_sort_key(item.get("index", 0)))
    return failed_chunks


def _normalize_foreshadow_review_observations(data):
    data = data if isinstance(data, dict) else {}
    out = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
    items = data.get("foreshadows", [])
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip()
        if not name:
            continue
        record = {
            "name": name,
            "status": str(item.get("status", "") or "").strip(),
            "setup_chapter": str(item.get("setup_chapter", "") or "").strip(),
            "payoff_chapter": str(item.get("payoff_chapter", "") or "").strip(),
            "description": str(item.get("description", "") or "").strip(),
        }
        source_label = str(item.get("_source_label", "") or item.get("source_label", "") or "").strip()
        if source_label:
            record["_source_label"] = source_label
        if item.get("_status_explicit"):
            record["_status_explicit"] = True
        out["foreshadows"].append(record)
    return out


def _normalize_foreshadow_review_state(data):
    data = data if isinstance(data, dict) else {}
    state = {}
    observations = _normalize_foreshadow_review_observations(data.get("observations", {}))
    if observations.get("foreshadows"):
        state["observations"] = observations

    failed_observation_chunks = _normalize_analysis_chunk_state(data.get("failed_observation_chunks", []))
    if failed_observation_chunks:
        state["failed_observation_chunks"] = failed_observation_chunks

    comparison = data.get("comparison", {})
    if isinstance(comparison, dict):
        status = str(comparison.get("status", "") or "").strip()
        failed_comparison_chunks = _normalize_analysis_chunk_state(comparison.get("failed_chunks", []))
        if status in {"pending", "failed"} or failed_comparison_chunks:
            item = {"status": status if status in {"pending", "failed"} else "failed"}
            error = str(comparison.get("error", "") or "").strip()
            if error:
                item["error"] = error
            updated_at = str(comparison.get("updated_at", "") or "").strip()
            if updated_at:
                item["updated_at"] = updated_at
            review_flow = str(comparison.get("review_flow", "") or "").strip()
            if review_flow:
                item["review_flow"] = review_flow
            if failed_comparison_chunks:
                item["failed_chunks"] = failed_comparison_chunks
            state["comparison"] = item
    return state


def _normalize_candidate_analysis_state(data):
    data = data if isinstance(data, dict) else {}
    state = {}
    failed_chunks = _normalize_analysis_chunk_state(data.get("failed_candidate_chunks", []))
    pending_ids = []
    seen_pending_ids = set()
    for item in data.get("pending_candidate_chapter_ids", []):
        chapter_id = str(item).strip()
        if not chapter_id or chapter_id in seen_pending_ids:
            continue
        seen_pending_ids.add(chapter_id)
        pending_ids.append(chapter_id)
    if failed_chunks:
        state["failed_candidate_chunks"] = failed_chunks
    if pending_ids:
        state["pending_candidate_chapter_ids"] = pending_ids
    postprocess = data.get("candidate_postprocess", {})
    if isinstance(postprocess, dict):
        status = str(postprocess.get("status", "") or "").strip()
        if status in {"pending", "failed"}:
            item = {"status": status}
            error = str(postprocess.get("error", "") or "").strip()
            if error:
                item["error"] = error
            updated_at = str(postprocess.get("updated_at", "") or "").strip()
            if updated_at:
                item["updated_at"] = updated_at
            state["candidate_postprocess"] = item
    foreshadow_review = _normalize_foreshadow_review_state(data.get("foreshadow_review", {}))
    if foreshadow_review:
        state["foreshadow_review"] = foreshadow_review
    return state


def _analysis_chunk_sort_key(value):
    parts = str(value or "").split(".")
    key = []
    for part in parts:
        try:
            key.append((0, int(part)))
        except Exception:
            key.append((1, part))
    return key


def _normalize_project(data):
    base = _default_project()
    if not isinstance(data, dict):
        return base
    meta = data.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    base["meta"].update({k: str(meta.get(k, base["meta"].get(k, ""))) for k in base["meta"]})
    for key in ("bible", "world_rules", "timeline", "foreshadows", "summary", "style_reference", "draft_note"):
        value = data.get(key, "")
        base[key] = value if isinstance(value, str) else str(value or "")
    style_profile_id = str(data.get("style_profile_id", "") or "").strip().lower()
    if style_profile_id == "__none__" or re.fullmatch(r"[0-9a-f]{64}", style_profile_id):
        base["style_profile_id"] = style_profile_id
    for key in ("bible", "world_rules", "timeline", "foreshadows", "summary"):
        base[key] = _dedupe_text_lines(base.get(key, ""))
    base["long_form_memory"] = _normalize_long_form_memory(data.get("long_form_memory", {}))
    # Some projects created by the newer writer keep continuity under
    # ``long_form``.  Keep that value in the in-memory normalized project so
    # the legacy writer can read either shape without changing disk format.
    if isinstance(data.get("long_form"), dict):
        base["long_form"] = deepcopy(data.get("long_form"))
    base["series_continuation"] = _normalize_series_continuation(
        data.get("series_continuation", {})
    )
    base["narrative_strategy_profile"] = _normalize_narrative_strategy_profile(
        data.get("narrative_strategy_profile", {})
    )
    base["creative_intent_contract"] = _normalize_creative_intent_contract(
        data.get("creative_intent_contract", {})
    )
    base["chapter_plan_foundation"] = _normalize_chapter_plan_foundation(
        data.get("chapter_plan_foundation", {})
    )
    strategy_confirmation = data.get("narrative_strategy_confirmation", {})
    if isinstance(strategy_confirmation, dict):
        confirmation_status = str(strategy_confirmation.get("status", "") or "").strip()
        profile_hash = str(strategy_confirmation.get("profile_hash", "") or "").strip().lower()
        foundation_hash = str(strategy_confirmation.get("foundation_hash", "") or "").strip().lower()
        normalized_confirmation = {}
        if confirmation_status in {"pending", "confirmed"}:
            normalized_confirmation["status"] = confirmation_status
        if re.fullmatch(r"[0-9a-f]{64}", profile_hash):
            normalized_confirmation["profile_hash"] = profile_hash
        if re.fullmatch(r"[0-9a-f]{64}", foundation_hash):
            normalized_confirmation["foundation_hash"] = foundation_hash
        for key in ("generated_at", "confirmed_at", "updated_at"):
            field_value = str(strategy_confirmation.get(key, "") or "").strip()
            if field_value:
                normalized_confirmation[key] = field_value
        base["narrative_strategy_confirmation"] = normalized_confirmation
    style_profile_cache = data.get("style_profile_cache", {})
    if isinstance(style_profile_cache, dict):
        normalized_cache = {}
        for reference_hash, item in style_profile_cache.items():
            cache_key = str(reference_hash or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", cache_key):
                continue
            if isinstance(item, dict):
                profile = str(item.get("profile", "") or "").strip()
                cached_at = str(item.get("cached_at", "") or "").strip()
                model = str(item.get("model", "") or "").strip()
            else:
                profile = str(item or "").strip()
                cached_at = ""
                model = ""
            units = []
            if isinstance(item, dict):
                for fallback_index, unit in enumerate(item.get("units", []) if isinstance(item.get("units"), list) else [], 1):
                    if not isinstance(unit, dict):
                        continue
                    source = str(unit.get("source", "") or "").strip()
                    if not source:
                        continue
                    try:
                        unit_id = max(1, int(unit.get("id", fallback_index) or fallback_index))
                    except Exception:
                        unit_id = fallback_index
                    try:
                        source_index = max(1, int(unit.get("source_index", unit_id) or unit_id))
                    except Exception:
                        source_index = unit_id
                    try:
                        source_total = max(1, int(unit.get("source_total", 1) or 1))
                    except Exception:
                        source_total = 1
                    normalized_unit = {
                        "id": unit_id,
                        "source_index": source_index,
                        "source_total": source_total,
                        "source": source,
                        "baseline": str(unit.get("baseline", "") or "").strip(),
                        "sheet": str(unit.get("sheet", "") or "").strip(),
                    }
                    units.append(normalized_unit)
            semantic_archive = {}
            if isinstance(item, dict):
                semantic_archive = _normalize_semantic_style_archive(
                    item,
                    base.get("style_reference", ""),
                )
            if not profile and not units and not semantic_archive:
                continue
            normalized_item = {"profile": profile}
            if isinstance(item, dict):
                try:
                    version = int(item.get("version", 1) or 1)
                except Exception:
                    version = 1
                normalized_item["version"] = max(1, version)
                status = str(item.get("status", "") or "").strip()
                if status:
                    normalized_item["status"] = status
                combined_sheet = str(item.get("combined_sheet", "") or "").strip()
                persona = str(item.get("persona", "") or "").strip()
                if combined_sheet:
                    normalized_item["combined_sheet"] = combined_sheet
                if persona:
                    normalized_item["persona"] = persona
                try:
                    style_cards_version = max(0, int(item.get("style_cards_version", 0) or 0))
                except Exception:
                    style_cards_version = 0
                style_cards = _normalize_style_cards(
                    item.get("style_cards", []),
                    base.get("style_reference", ""),
                )
                if style_cards_version:
                    normalized_item["style_cards_version"] = style_cards_version
                if style_cards:
                    normalized_item["style_cards"] = style_cards
                archive_id = str(item.get("archive_id", "") or "").strip().lower()
                if re.fullmatch(r"[0-9a-f]{64}", archive_id):
                    normalized_item["archive_id"] = archive_id
                if semantic_archive:
                    normalized_item["style_archive_schema"] = STYLE_SEMANTIC_ARCHIVE_SCHEMA
                    normalized_item["semantic_archive_version"] = int(
                        semantic_archive.get("version", STYLE_SEMANTIC_ARCHIVE_VERSION) or STYLE_SEMANTIC_ARCHIVE_VERSION
                    )
                    normalized_item["runtime_voice_pack"] = str(
                        semantic_archive.get("runtime_voice_pack", "") or ""
                    ).strip()
                    normalized_item["native_vocabulary_cards"] = deepcopy(
                        semantic_archive.get("native_vocabulary_cards", [])
                    )
                    normalized_item["voice_cards"] = deepcopy(
                        semantic_archive.get("voice_cards", [])
                    )
                    normalized_item["technique_cards"] = deepcopy(
                        semantic_archive.get("technique_cards", [])
                    )
                if units:
                    normalized_item["units"] = units
                merge_results = [
                    str(value or "").strip()
                    for value in (item.get("merge_results", []) if isinstance(item.get("merge_results"), list) else [])
                    if str(value or "").strip()
                ]
                if merge_results:
                    normalized_item["merge_results"] = merge_results
                error = str(item.get("error", "") or "").strip()
                if error:
                    normalized_item["error"] = error
            normalized_cache[cache_key] = normalized_item
            if cached_at:
                normalized_cache[cache_key]["cached_at"] = cached_at
            if model:
                normalized_cache[cache_key]["model"] = model
        base["style_profile_cache"] = normalized_cache
    plan_reference = data.get("imported_chapter_plan_reference", {})
    if isinstance(plan_reference, dict):
        normalized_reference = {}
        for key in ("summary", "source_title", "source_label", "imported_at"):
            value = str(plan_reference.get(key, "") or "").strip()
            if value:
                normalized_reference[key] = value
        chapters = []
        for item in plan_reference.get("chapters", []) if isinstance(plan_reference.get("chapters", []), list) else []:
            if not isinstance(item, dict):
                continue
            chapter = {
                "index": _as_text(item.get("index", "")),
                "title": _as_text(item.get("title", "")),
                "target_words": _as_text(item.get("target_words", "")),
                "narrative_stage": _as_text(item.get("narrative_stage", "")),
                "outline": _as_text(item.get("outline", "")),
                "characters": _normalize_name_list(item.get("characters", [])),
                "ending_hook": _as_text(item.get("ending_hook", "")),
                "source_event_ids": _normalize_name_list(item.get("source_event_ids", [])),
            }
            if any(str(value or "").strip() for value in chapter.values() if not isinstance(value, list)) or chapter["characters"]:
                chapters.append(chapter)
        if chapters:
            normalized_reference["chapters"] = chapters
        stages = []
        for stage_index, item in enumerate(
            plan_reference.get("stages", []) if isinstance(plan_reference.get("stages", []), list) else [], 1
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
            stage_id = str(item.get("id", "") or f"S{stage_index:02d}").strip().upper()
            if not re.fullmatch(r"S\d{2,4}", stage_id):
                stage_id = f"S{stage_index:02d}"
            events = []
            seen_event_ids = set()
            for event_index, event in enumerate(
                item.get("events", []) if isinstance(item.get("events", []), list) else [], 1
            ):
                if not isinstance(event, dict):
                    continue
                try:
                    order = max(1, int(event.get("order", event_index) or event_index))
                except Exception:
                    order = event_index
                event_id = str(event.get("id", "") or f"{stage_id}-E{order:02d}").strip().upper()
                if not re.fullmatch(r"S\d{2,4}-E\d{2,4}", event_id):
                    event_id = f"{stage_id}-E{order:02d}"
                text = _as_text(event.get("text", "")).strip()
                if not text or event_id in seen_event_ids:
                    continue
                seen_event_ids.add(event_id)
                events.append({"id": event_id, "order": order, "text": text})
            events.sort(key=lambda event: (event["order"], event["id"]))
            if not events:
                continue
            stages.append({
                "id": stage_id,
                "name": _as_text(item.get("name", "")).strip() or f"阶段{stage_index}",
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
                "events": events,
            })
        stages.sort(key=lambda stage: (stage["start_chapter"], stage["end_chapter"], stage["id"]))
        if stages:
            normalized_reference["stages"] = stages
        if normalized_reference.get("summary") or normalized_reference.get("chapters") or normalized_reference.get("stages"):
            base["imported_chapter_plan_reference"] = normalized_reference
    framework_source = data.get("imported_framework_source", {})
    if isinstance(framework_source, dict):
        source_text = str(framework_source.get("text", "") or "").strip()
        if source_text:
            source_hash = str(framework_source.get("sha256", "") or "").strip().lower()
            calculated_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            normalized_source = {
                "text": source_text,
                "sha256": source_hash if source_hash == calculated_hash else calculated_hash,
            }
            for key in ("source_title", "source_label", "source_path", "imported_at"):
                value = str(framework_source.get(key, "") or "").strip()
                if value:
                    normalized_source[key] = value
            base["imported_framework_source"] = normalized_source
    framework_import_state = data.get("framework_import_state", {})
    if isinstance(framework_import_state, dict):
        import_status = str(framework_import_state.get("status", "") or "").strip()
        if import_status in {"running", "failed", "complete"}:
            normalized_import_state = {"status": import_status}
            for key in (
                "error", "source_hash", "source_title", "source_label", "import_mode",
                "model", "updated_at",
            ):
                field_value = str(framework_import_state.get(key, "") or "").strip()
                if field_value:
                    normalized_import_state[key] = field_value
            base["framework_import_state"] = normalized_import_state
    generation_state = data.get("chapter_plan_generation_state", {})
    if isinstance(generation_state, dict) and generation_state:
        try:
            version = int(generation_state.get("version", 0) or 0)
        except Exception:
            version = 0
        status = str(generation_state.get("status", "") or "").strip()
        chapters = [
            deepcopy(item)
            for item in generation_state.get("chapters", [])
            if isinstance(item, dict)
        ] if isinstance(generation_state.get("chapters"), list) else []
        master_plan = deepcopy(generation_state.get("master_plan", {}))
        if not isinstance(master_plan, dict):
            master_plan = {}
        if version > 0 and status in {
            "pending", "awaiting_profile_confirmation", "generating", "failed", "interrupted", "complete"
        }:
            def state_int(key, default=0):
                try:
                    return int(generation_state.get(key, default) or default)
                except Exception:
                    return int(default)

            normalized_state = {
                "version": version,
                "status": status,
                "target_words": state_int("target_words"),
                "average_chapter_words": state_int("average_chapter_words"),
                "total_chapter_count": state_int("total_chapter_count"),
                "existing_chapter_count": state_int("existing_chapter_count"),
                "requested_chapter_count": state_int("requested_chapter_count"),
                "batch_size": state_int("batch_size", 30),
                "master_plan": master_plan,
                "chapters": chapters,
                "creative_intent_contract": _normalize_creative_intent_contract(
                    generation_state.get("creative_intent_contract", {})
                ),
                "profile_confirmed": bool(generation_state.get("profile_confirmed", False)),
            }
            for key in ("started_at", "updated_at", "error", "profile_hash", "foundation_hash"):
                value = str(generation_state.get(key, "") or "").strip()
                if value:
                    normalized_state[key] = value
            base["chapter_plan_generation_state"] = normalized_state
    chars = data.get("characters", [])
    if isinstance(chars, list):
        base["characters"] = [c for c in chars if isinstance(c, dict)]
        for char in base["characters"]:
            if not str(char.get("id", "") or "").strip():
                char["id"] = uuid.uuid4().hex
            for key in ("id", "name", "role", "goal", "secret", "voice", "notes"):
                char[key] = _as_text(char.get(key, ""))
            char["notes"] = _strip_internal_candidate_markers(char.get("notes", ""))
    lore = data.get("lore", [])
    if isinstance(lore, list):
        base["lore"] = [c for c in lore if isinstance(c, dict)]
        for item in base["lore"]:
            if not str(item.get("id", "") or "").strip():
                item["id"] = uuid.uuid4().hex
            for key in ("id", "name", "type", "description", "story_known"):
                item[key] = _as_text(item.get(key, ""))
            item["description"] = _strip_internal_candidate_markers(item.get("description", ""))
            item["story_known"] = _strip_internal_candidate_markers(item.get("story_known", ""))
    chaps = data.get("chapters", [])
    if isinstance(chaps, list):
        base["chapters"] = [c for c in chaps if isinstance(c, dict)]
        base["chapters"], _removed = _dedupe_chapters(base["chapters"])
        for chap in base["chapters"]:
            if isinstance(chap, dict):
                if not str(chap.get("id", "") or "").strip():
                    chap["id"] = uuid.uuid4().hex
                for key in (
                    "id",
                    "title",
                    "unit_type",
                    "status",
                    "outline",
                    "draft_words",
                    "text",
                    "summary",
                    "key_facts",
                    "analysis_hash",
                    "analysis_hash_version",
                    "analysis_analyzed_at",
                    "analysis_baseline",
                    "analysis_linked_hash",
                    "analysis_status",
                    "analysis_status_hash",
                    "analysis_status_version",
                    "adaptation_mode",
                    "adaptation_optimization",
                    "adaptation_source_hash",
                    "adapted_at",
                ):
                    chap[key] = _as_text(chap.get(key, ""))
                chap["linked_characters"] = _normalize_name_list(chap.get("linked_characters", []))
                chap["source_event_ids"] = _normalize_name_list(chap.get("source_event_ids", []))
                chap["actual_linked_character_ids"] = _normalize_name_list(chap.get("actual_linked_character_ids", []))
                chap["state_delta"] = deepcopy(chap.get("state_delta", {})) if isinstance(chap.get("state_delta"), dict) else {}
                chap["long_term_events"] = [
                    deepcopy(item)
                    for item in chap.get("long_term_events", [])
                    if isinstance(item, dict)
                ] if isinstance(chap.get("long_term_events"), list) else []
                chap["state_reconciliation"] = (
                    deepcopy(chap.get("state_reconciliation", {}))
                    if isinstance(chap.get("state_reconciliation"), dict) else {}
                )
                chap["memory_selection"] = deepcopy(chap.get("memory_selection", {})) if isinstance(chap.get("memory_selection"), dict) else {}
                memory_sync_status = str(chap.get("memory_sync_status", "") or "").strip()
                if memory_sync_status not in {"pending", "complete", "failed"}:
                    memory_sync_status = "complete" if _chapter_analysis_is_current(chap) else "pending"
                chap["memory_sync_status"] = memory_sync_status
                try:
                    chap["memory_revision"] = max(0, int(chap.get("memory_revision", 0) or 0))
                except Exception:
                    chap["memory_revision"] = 0
                chap["memory_update_hash"] = _as_text(chap.get("memory_update_hash", ""))
                chap["memory_sync_error"] = _as_text(chap.get("memory_sync_error", ""))
                chap["memory_boundary_integrity"] = (
                    deepcopy(chap.get("memory_boundary_integrity", {}))
                    if isinstance(chap.get("memory_boundary_integrity"), dict) else {}
                )
                memory_reconciliation_status = str(
                    chap.get("memory_reconciliation_status", "") or ""
                ).strip()
                if memory_reconciliation_status not in {"", "pending", "complete", "failed", "skipped"}:
                    memory_reconciliation_status = ""
                chap["memory_reconciliation_status"] = memory_reconciliation_status
                chap["memory_reconciliation_error"] = _as_text(
                    chap.get("memory_reconciliation_error", "")
                )
                chap["ai_generation_checkpoint"] = (
                    deepcopy(chap.get("ai_generation_checkpoint", {}))
                    if isinstance(chap.get("ai_generation_checkpoint"), dict) else {}
                )
                auto_expand_resume_required = chap.get("auto_expand_resume_required", False)
                if isinstance(auto_expand_resume_required, str):
                    auto_expand_resume_required = auto_expand_resume_required.strip().lower() in {
                        "1", "true", "yes", "on",
                    }
                chap["auto_expand_resume_required"] = bool(auto_expand_resume_required)
                if _chapter_analysis_is_current(chap):
                    chap["analysis_baseline"] = chap.get("analysis_baseline", "") or _chapter_analysis_content_text(chap)
                    chap["analysis_linked_hash"] = chap.get("analysis_linked_hash", "") or _chapter_analysis_linked_hash(chap)
    foreshadow_items = data.get("foreshadow_items", [])
    if isinstance(foreshadow_items, list):
        base["foreshadow_items"] = [c for c in foreshadow_items if isinstance(c, dict)]
        _ensure_foreshadow_codes(base)
        for item in base["foreshadow_items"]:
            if not str(item.get("id", "") or "").strip():
                item["id"] = uuid.uuid4().hex
            for key in (
                "id", "code", "name", "status", "setup_chapter", "payoff_chapter",
                "description", "revealed", "remaining_secret", "notes",
            ):
                item[key] = _as_text(item.get(key, ""))
            item["setup_chapter"] = _normalize_foreshadow_chapter_ref(item.get("setup_chapter", ""))
            item["payoff_chapter"] = _normalize_foreshadow_chapter_ref(item.get("payoff_chapter", ""))
            item["description"] = _strip_internal_candidate_markers(item.get("description", ""))
            item["revealed"] = _strip_internal_candidate_markers(item.get("revealed", ""))
            item["remaining_secret"] = _strip_internal_candidate_markers(item.get("remaining_secret", ""))
            item["notes"] = _strip_internal_candidate_markers(item.get("notes", ""))
    candidates = data.get("import_candidates", {})
    if isinstance(candidates, dict):
        normalized_candidates = _normalize_import_candidates(candidates)
        if _import_candidates_has_content(normalized_candidates):
            base["import_candidates"] = normalized_candidates
    analysis_state = _normalize_candidate_analysis_state(data.get("analysis_state", {}))
    if analysis_state:
        base["analysis_state"] = analysis_state
    snapshot = base.get("long_form_memory", {}).get("state_snapshot", {})
    auto_updated_chapter_id = str(snapshot.get("as_of_chapter_id", "") or "").strip() if isinstance(snapshot, dict) else ""
    if auto_updated_chapter_id:
        for chapter in base.get("chapters", []):
            if not isinstance(chapter, dict) or str(chapter.get("id", "") or "").strip() != auto_updated_chapter_id:
                continue
            if (
                str(chapter.get("text", "") or "").strip()
                and str(chapter.get("summary", "") or "").strip()
                and str(chapter.get("key_facts", "") or "").strip()
            ):
                chapter["status"] = "已完成"
                if not _chapter_analysis_is_current(chapter):
                    _mark_chapters_analyzed(base["chapters"], [auto_updated_chapter_id])
            break
    base["updated_at"] = str(data.get("updated_at") or now_str())
    return base


def _volume_handoff_record(item, fields, field_limit=520):
    item = item if isinstance(item, dict) else {}
    result = {}
    for key in fields:
        value = item.get(key, "")
        if isinstance(value, list):
            values = [
                deepcopy(child)
                for child in value
                if isinstance(child, (dict, str)) and str(child or "").strip()
            ]
            if values:
                result[key] = values
            continue
        text = _clip_context_text(value, field_limit, preserve_lines=True).strip()
        if text:
            result[key] = text
    return result


def _volume_handoff_json_chars(value):
    return len(json.dumps(value, ensure_ascii=False, indent=2))


def _compact_volume_handoff_records(
    items,
    fields,
    field_limits,
    total_limit,
    minimal_fields=None,
):
    """Bound a record list by characters while preserving entity names."""
    items = items if isinstance(items, list) else []
    fields = tuple(fields or ())
    field_limits = field_limits if isinstance(field_limits, dict) else {}
    minimal_fields = tuple(minimal_fields or ("name",))

    def render(scale, only_minimal=False, selected_fields_override=None):
        rendered = []
        for item in items:
            if not isinstance(item, dict):
                continue
            row = {}
            selected_fields = (
                tuple(selected_fields_override)
                if selected_fields_override is not None
                else minimal_fields if only_minimal else fields
            )
            for key in selected_fields:
                if key not in item:
                    continue
                value = item.get(key, "")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    row[key] = value
                    continue
                if isinstance(value, list):
                    values = [
                        deepcopy(child)
                        for child in value
                        if isinstance(child, (dict, str)) and str(child or "").strip()
                    ]
                    if values:
                        row[key] = values
                    continue
                limit = int(field_limits.get(key, 120) or 120)
                if only_minimal:
                    limit = min(limit, 80)
                else:
                    limit = max(24, int(limit * scale))
                text = _clip_complete_text(value, limit, keep_tail=False)
                if text:
                    row[key] = text
            if row:
                rendered.append(row)
        return rendered

    total_limit = max(1000, int(total_limit or 0))
    for scale in (1.0, 0.75, 0.5, 0.35, 0.2):
        result = render(scale)
        if _volume_handoff_json_chars(result) <= total_limit:
            return result

    result = render(1.0, only_minimal=True)
    if _volume_handoff_json_chars(result) <= total_limit:
        return result

    # When descriptions alone exceed the group budget, keep every stable
    # identity before falling back to a sampled list. Most project records use
    # ``name``, while planning ledgers need the paired ``index``/``title``
    # identity. Trying the pair first prevents an oversized ledger from
    # retaining titles while losing the absolute chapter numbers.
    identity_groups = (
        ("index", "title"),
        ("code", "name"),
        ("id", "name"),
        ("name",),
        ("title",),
        ("code",),
        ("id",),
    )
    for group in identity_groups:
        if not all(
            any(
                isinstance(item, dict)
                and candidate in item
                and (
                    isinstance(item.get(candidate), (int, float))
                    or bool(str(item.get(candidate, "") or "").strip())
                )
                for item in items
            )
            for candidate in group
        ):
            continue
        paired = render(1.0, only_minimal=True, selected_fields_override=group)
        if _volume_handoff_json_chars(paired) <= total_limit:
            return paired

    # A still oversized group may not fit a stable pair. Keep one stable
    # identity field as the last structured fallback rather than dropping the
    # entire record list.
    identity_field = ""
    for candidate in ("name", "title", "code", "id", *minimal_fields, *fields):
        if any(
            isinstance(item, dict)
            and candidate in item
            and (
                isinstance(item.get(candidate), (int, float))
                or bool(str(item.get(candidate, "") or "").strip())
            )
            for item in items
        ):
            identity_field = candidate
            break
    if not identity_field:
        return []
    result = render(1.0, only_minimal=True, selected_fields_override=(identity_field,))
    if _volume_handoff_json_chars(result) <= total_limit:
        return result

    # Names and ordering are more useful than dropping the whole group. This
    # final fallback keeps a balanced head/tail sample and states the omission.
    if not result:
        return []
    head = max(1, len(result) // 3)
    tail = max(1, len(result) // 3)
    while head + tail >= len(result) and (head > 1 or tail > 1):
        if head >= tail and head > 1:
            head -= 1
        elif tail > 1:
            tail -= 1
        else:
            break
    omitted = max(0, len(result) - head - tail)
    selected = result[:head] + [{
        "note": f"中间 {omitted} 条记录已按字符预算省略，名称未参与正文写作。"
    }] + result[-tail:]
    while _volume_handoff_json_chars(selected) > total_limit and len(selected) > 3:
        marker_index = next(
            (index for index, item in enumerate(selected) if isinstance(item, dict) and "note" in item),
            -1,
        )
        if marker_index > 1:
            selected.pop(marker_index - 1)
        elif 0 <= marker_index < len(selected) - 2:
            selected.pop(marker_index + 1)
        else:
            break
    return selected


def _compact_volume_handoff_text_list(items, total_limit, item_limit=320):
    items = items if isinstance(items, list) else []
    total_limit = max(300, int(total_limit or 0))

    def render(scale):
        rows = []
        limit = max(24, int(item_limit * scale))
        for item in items:
            if isinstance(item, dict):
                text = json.dumps(item, ensure_ascii=False, indent=0)
            else:
                text = str(item or "").strip()
            text = _clip_complete_text(text, limit, keep_tail=False)
            if text:
                rows.append(text)
        return rows

    for scale in (1.0, 0.75, 0.5, 0.35, 0.2):
        rows = render(scale)
        if _volume_handoff_json_chars(rows) <= total_limit:
            return rows
    rows = render(0.2)
    while _volume_handoff_json_chars(rows) > total_limit and len(rows) > 2:
        rows.pop(len(rows) // 2)
    return rows


def _compact_volume_handoff_current_state(value, total_limit=4500):
    """Compress live continuation state by semantic groups, never as one raw blob."""
    value = value if isinstance(value, dict) else {}
    total_limit = max(1200, int(total_limit or 0))
    snapshot = value.get("state_snapshot", {})
    snapshot = snapshot if isinstance(snapshot, dict) else {}

    def build(snapshot_limit, facts_limit, history_limit, archives_limit):
        compact_snapshot = {}
        for key in ("as_of_chapter_id", "as_of_chapter_index", "story_time", "location", "notes", "updated_at"):
            raw = snapshot.get(key, "")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                compact_snapshot[key] = raw
            else:
                text = _clip_context_text(raw, 360, keep_tail=True, preserve_lines=True)
                if text:
                    compact_snapshot[key] = text
        state_list_limits = {
            "character_states": 900,
            "relationship_states": 900,
            "object_states": 600,
            "active_conflicts": 900,
            "unresolved_tasks": 900,
        }
        for key, group_limit in state_list_limits.items():
            rows = _compact_volume_handoff_text_list(
                snapshot.get(key, []),
                max(180, int(group_limit * snapshot_limit / 4500)),
                260,
            )
            if rows:
                compact_snapshot[key] = rows

        result = {"state_snapshot": compact_snapshot}
        for key, limit in (("active_facts", facts_limit), ("fact_history", history_limit)):
            rows = _compact_volume_handoff_text_list(value.get(key, []), limit, 300)
            if rows:
                result[key] = rows
        archives = _compact_volume_handoff_records(
            value.get("stage_archives", []),
            (
                "id", "start_chapter_index", "end_chapter_index", "summary",
                "irreversible_facts", "relationship_changes", "unresolved_threads", "next_stage_entry",
            ),
            {
                "id": 40, "start_chapter_index": 24, "end_chapter_index": 24,
                "summary": 240, "irreversible_facts": 220, "relationship_changes": 200,
                "unresolved_threads": 220, "next_stage_entry": 200,
            },
            archives_limit,
            minimal_fields=("id", "start_chapter_index", "end_chapter_index", "summary"),
        )
        if archives:
            result["stage_archives"] = archives
        return result

    for scale in (1.0, 0.7, 0.45, 0.25):
        result = build(
            int(4500 * scale),
            max(300, int(1600 * scale)),
            max(160, int(500 * scale)),
            max(300, int(900 * scale)),
        )
        if _volume_handoff_json_chars(result) <= total_limit:
            return result
    return build(900, 300, 160, 300)


def _volume_handoff_record_key(item):
    item = item if isinstance(item, dict) else {}
    code = _compact_text(item.get("code", ""))
    name = _compact_text(item.get("name", ""))
    return f"code:{code}" if code else f"name:{name}" if name else ""


def _dedupe_volume_handoff_terminal_records(*groups):
    """Merge terminal indexes without reopening or repeating a line."""
    result = []
    positions = {}
    for group in groups:
        if not isinstance(group, list):
            continue
        for raw in group:
            if not isinstance(raw, dict):
                continue
            item = deepcopy(raw)
            key = _volume_handoff_record_key(item)
            if not key:
                continue
            position = positions.get(key)
            if position is None:
                positions[key] = len(result)
                result.append(item)
                continue
            existing = result[position]
            for field in ("code", "name", "status", "payoff_chapter", "description", "result"):
                old = str(existing.get(field, "") or "").strip()
                new = str(item.get(field, "") or "").strip()
                if not old and new:
                    existing[field] = new
                elif new and len(new) > len(old) and old not in new:
                    existing[field] = new
    return result


def _compact_volume_handoff_source_for_request(source, total_limit=VOLUME_HANDOFF_SOURCE_CHAR_BUDGET):
    """Apply a deterministic final envelope to the first continuation request."""
    source = deepcopy(source if isinstance(source, dict) else {})
    total_limit = max(12000, int(total_limit or VOLUME_HANDOFF_SOURCE_CHAR_BUDGET))

    def size():
        return _volume_handoff_json_chars(source)

    def compact_state(limit):
        value = source.get("current_state", {})
        if _volume_handoff_json_chars(value) <= limit:
            return
        source["current_state"] = _compact_volume_handoff_current_state(value, limit)

    def compact_records(
        characters_limit,
        lore_limit,
        active_limit,
        resolved_limit,
        discarded_limit,
        chapter_outline_limit,
        field_scale=1.0,
    ):
        records = source.get("records", {})
        records = records if isinstance(records, dict) else {}
        source["records"] = records
        records["characters"] = _compact_volume_handoff_records(
            records.get("characters", []),
            ("name", "role", "goal", "secret", "voice", "notes"),
            {
                "name": int(80 * field_scale), "role": int(80 * field_scale),
                "goal": int(100 * field_scale), "secret": int(100 * field_scale),
                "voice": int(80 * field_scale), "notes": int(120 * field_scale),
            },
            characters_limit,
            minimal_fields=("name", "role", "goal"),
        )
        records["lore"] = _compact_volume_handoff_records(
            records.get("lore", []),
            ("name", "type", "description", "story_known"),
            {
                "name": int(70 * field_scale), "type": max(16, int(24 * field_scale)),
                "description": int(80 * field_scale), "story_known": int(60 * field_scale),
            },
            lore_limit,
            minimal_fields=("name", "type"),
        )
        records["foreshadows"] = _compact_volume_handoff_records(
            records.get("foreshadows", []),
            (
                "code", "name", "status", "setup_chapter", "payoff_chapter",
                "description", "revealed", "remaining_secret", "notes",
            ),
            {
                "code": 28, "name": 70, "status": 20, "setup_chapter": 36,
                "payoff_chapter": 36, "description": 100, "revealed": 80,
                "remaining_secret": 100, "notes": 70,
            },
            active_limit,
            minimal_fields=("code", "name", "status", "remaining_secret"),
        )
        records["resolved_foreshadows"] = _compact_volume_handoff_records(
            records.get("resolved_foreshadows", []),
            ("code", "name", "status", "payoff_chapter", "description", "result"),
            {"code": 28, "name": 70, "status": 20, "payoff_chapter": 36, "description": 60, "result": 80},
            resolved_limit,
            minimal_fields=("code", "name", "status", "payoff_chapter", "result"),
        )
        records["discarded_foreshadows"] = _compact_volume_handoff_records(
            records.get("discarded_foreshadows", []),
            ("code", "name", "status"),
            {"code": 28, "name": 70, "status": 20},
            discarded_limit,
            minimal_fields=("code", "name", "status"),
        )
        source["chapter_outlines"] = _compact_volume_handoff_records(
            source.get("chapter_outlines", []),
            ("index", "title", "outline"),
            {
                "index": 20, "title": 90, "outline": max(120, int(1800 * field_scale)),
            },
            chapter_outline_limit,
            minimal_fields=("index", "title"),
        )
        for chapter_key in ("first_chapter", "last_chapter"):
            chapter = source.get(chapter_key, {})
            if not isinstance(chapter, dict):
                continue
            for key in ("title", "outline"):
                chapter[key] = _clip_context_text(
                    chapter.get(key, ""),
                    max(120, int(900 * field_scale)),
                    keep_tail=True,
                    preserve_lines=True,
                )
            chapter["text"] = _clip_context_text(
                chapter.get("text", ""),
                max(12000, int(24000 * field_scale)),
                keep_tail=True,
                preserve_lines=True,
                preserve_boundaries=True,
            )
            source[chapter_key] = chapter

    if size() <= total_limit:
        return source

    # First remove detail from historical material. The final chapter and
    # active records remain the highest-value continuity evidence.
    source["timeline"] = _clip_context_text(source.get("timeline", ""), 4000, keep_tail=True, preserve_lines=True)
    source["summary"] = _clip_context_text(source.get("summary", ""), 4000, keep_tail=True, preserve_lines=True)
    compact_state(4200)
    compact_records(7000, 20000, 9000, 4500, 900, 9000, 1.0)
    if size() <= total_limit:
        return source

    # A damaged or unusually dense project gets a second, still structured
    # reduction. Never turn the whole payload into an arbitrary sliced string.
    source["source_project"] = {
        key: _clip_context_text(value, 500 if key == "premise" else 120, preserve_lines=True)
        for key, value in (source.get("source_project", {}) or {}).items()
        if str(value or "").strip()
    }
    source["bible"] = _clip_context_text(source.get("bible", ""), 3200, keep_tail=True, preserve_lines=True)
    source["world_rules"] = _clip_context_text(source.get("world_rules", ""), 3200, keep_tail=True, preserve_lines=True)
    source["timeline"] = _clip_context_text(source.get("timeline", ""), 2800, keep_tail=True, preserve_lines=True)
    source["summary"] = _clip_context_text(source.get("summary", ""), 2800, keep_tail=True, preserve_lines=True)
    compact_state(2600)
    compact_records(4500, 20000, 7000, 3200, 650, 5200, 0.7)
    if size() <= total_limit:
        return source

    # Last fallback keeps the continuity anchor usable while making the cap
    # mathematically reachable for pathological record libraries.
    source["bible"] = _clip_context_text(source.get("bible", ""), 2200, keep_tail=True, preserve_lines=True)
    source["world_rules"] = _clip_context_text(source.get("world_rules", ""), 2200, keep_tail=True, preserve_lines=True)
    source["timeline"] = _clip_context_text(source.get("timeline", ""), 1800, keep_tail=True, preserve_lines=True)
    source["summary"] = _clip_context_text(source.get("summary", ""), 1800, keep_tail=True, preserve_lines=True)
    compact_state(1500)
    compact_records(3200, 20000, 5600, 2400, 500, 3200, 0.45)
    if isinstance(source.get("last_chapter"), dict):
        source["last_chapter"]["text"] = _clip_context_text(
            source["last_chapter"].get("text", ""),
            16000,
            keep_tail=True,
            preserve_lines=True,
        )
    if isinstance(source.get("first_chapter"), dict):
        source["first_chapter"]["text"] = _clip_context_text(
            source["first_chapter"].get("text", ""),
            14000,
            keep_tail=True,
            preserve_lines=True,
        )
    return source


def _compact_volume_handoff_for_framework(handoff, total_limit=VOLUME_FRAMEWORK_HANDOFF_CHAR_BUDGET):
    """Create the second-call view without changing the persisted handoff."""
    handoff = deepcopy(handoff if isinstance(handoff, dict) else {})
    # Deferred first-volume foreshadows remain an archive only. They are not
    # sent to the second-volume framework call and therefore cannot be
    # mistaken for active sequel tasks.
    handoff.pop("deferred_foreshadows", None)
    continuity_anchors = _compact_volume_continuity_anchors(
        handoff.get("continuity_anchors", []), 3000
    )
    if continuity_anchors:
        handoff["continuity_anchors"] = continuity_anchors
    else:
        handoff.pop("continuity_anchors", None)
    handoff["volume_summary"] = _clip_complete_text(handoff.get("volume_summary", ""), 5000)
    handoff["world_state"] = _clip_complete_text(handoff.get("world_state", ""), 5000)
    handoff["open_threads"] = _compact_volume_handoff_text_list(
        handoff.get("open_threads", []), 5000, 420
    )
    handoff["resolved_threads"] = _compact_volume_handoff_text_list(
        handoff.get("resolved_threads", []), 3500, 300
    )
    if "continuity_boundaries" in handoff:
        handoff["continuity_boundaries"] = _compact_volume_handoff_text_list(
            handoff.get("continuity_boundaries", []), 4500, 360
        )
    handoff["character_states"] = _compact_volume_handoff_text_list(
        handoff.get("character_states", []), 5000, 360
    )
    handoff["relationship_states"] = _compact_volume_handoff_text_list(
        handoff.get("relationship_states", []), 4000, 360
    )
    handoff["reusable_characters"] = _compact_volume_handoff_records(
        handoff.get("reusable_characters", []),
        ("name", "role", "goal", "secret", "voice", "notes"),
        {"name": 80, "role": 80, "goal": 100, "secret": 100, "voice": 80, "notes": 120},
        9000,
        minimal_fields=("name", "role", "goal"),
    )
    handoff["reusable_lore"] = _compact_volume_handoff_records(
        handoff.get("reusable_lore", []),
        ("name", "type", "description", "story_known"),
        {"name": 70, "type": 24, "description": 80, "story_known": 60},
        20000,
        minimal_fields=("name", "type"),
    )
    handoff["reusable_foreshadows"] = _compact_volume_handoff_records(
        handoff.get("reusable_foreshadows", []),
        (
            "code", "name", "status", "setup_chapter", "payoff_chapter",
            "description", "revealed", "remaining_secret", "notes",
        ),
        {
            "code": 28, "name": 70, "status": 20, "setup_chapter": 36,
            "payoff_chapter": 36, "description": 100, "revealed": 80,
            "remaining_secret": 100, "notes": 70,
        },
        12000,
        minimal_fields=("code", "name", "status", "remaining_secret"),
    )
    handoff["resolved_foreshadows"] = _compact_volume_handoff_records(
        handoff.get("resolved_foreshadows", []),
        ("code", "name", "status", "payoff_chapter", "description", "result"),
        {"code": 28, "name": 70, "status": 20, "payoff_chapter": 36, "description": 60, "result": 80},
        5000,
        minimal_fields=("code", "name", "status", "payoff_chapter", "result"),
    )
    handoff["discarded_foreshadows"] = _compact_volume_handoff_records(
        handoff.get("discarded_foreshadows", []),
        ("code", "name", "status"),
        {"code": 28, "name": 70, "status": 20},
        1200,
        minimal_fields=("code", "name", "status"),
    )
    inherited = handoff.get("inherited_materials", {})
    inherited = inherited if isinstance(inherited, dict) else {}
    handoff["inherited_materials"] = {
        "bible": _clip_context_text(inherited.get("bible", ""), 6000, keep_tail=True, preserve_lines=True),
        "world_rules": _clip_context_text(inherited.get("world_rules", ""), 6000, keep_tail=True, preserve_lines=True),
    }
    last_chapter = handoff.get("last_chapter", {})
    if isinstance(last_chapter, dict):
        last_chapter["text"] = _clip_context_text(
            last_chapter.get("text", ""),
            VOLUME_HANDOFF_LAST_CHAPTER_CHAR_LIMIT,
            keep_tail=True,
            preserve_lines=True,
            preserve_boundaries=True,
        )
        handoff["last_chapter"] = last_chapter

    # The group budgets above normally leave ample room. If a model returns
    # unusually verbose state fields, trim those fields once more before the
    # request is serialized.
    if _volume_handoff_json_chars(handoff) > int(total_limit or VOLUME_FRAMEWORK_HANDOFF_CHAR_BUDGET):
        handoff["volume_summary"] = _clip_complete_text(handoff.get("volume_summary", ""), 3000)
        handoff["world_state"] = _clip_complete_text(handoff.get("world_state", ""), 3000)
        handoff["open_threads"] = _compact_volume_handoff_text_list(handoff.get("open_threads", []), 3000, 260)
        if "continuity_boundaries" in handoff:
            handoff["continuity_boundaries"] = _compact_volume_handoff_text_list(
                handoff.get("continuity_boundaries", []), 3000, 260
            )
        handoff["reusable_characters"] = _compact_volume_handoff_records(
            handoff.get("reusable_characters", []),
            ("name", "role", "goal", "secret", "voice", "notes"),
            {"name": 70, "role": 60, "goal": 70, "secret": 70, "voice": 60, "notes": 80},
            6000,
            minimal_fields=("name", "role"),
        )
        handoff["reusable_lore"] = _compact_volume_handoff_records(
            handoff.get("reusable_lore", []),
            ("name", "type", "description", "story_known"),
            {"name": 60, "type": 20, "description": 50, "story_known": 40},
            12000,
            minimal_fields=("name", "type"),
        )
        handoff["reusable_foreshadows"] = _compact_volume_handoff_records(
            handoff.get("reusable_foreshadows", []),
            ("code", "name", "status", "remaining_secret", "description"),
            {"code": 24, "name": 60, "status": 18, "remaining_secret": 70, "description": 60},
            9000,
            minimal_fields=("code", "name", "status"),
        )
        handoff["resolved_foreshadows"] = _compact_volume_handoff_records(
            handoff.get("resolved_foreshadows", []),
            ("code", "name", "status", "payoff_chapter", "result"),
            {"code": 24, "name": 60, "status": 18, "payoff_chapter": 30, "result": 60},
            3000,
            minimal_fields=("code", "name", "status", "result"),
        )
        handoff["discarded_foreshadows"] = _compact_volume_handoff_records(
            handoff.get("discarded_foreshadows", []),
            ("code", "name", "status"),
            {"code": 24, "name": 60, "status": 18},
            800,
            minimal_fields=("code", "name", "status"),
        )
        handoff["continuity_anchors"] = _compact_volume_continuity_anchors(
            handoff.get("continuity_anchors", []), 1800
        )
        handoff["inherited_materials"] = {
            "bible": _clip_context_text(inherited.get("bible", ""), 4000, keep_tail=True, preserve_lines=True),
            "world_rules": _clip_context_text(inherited.get("world_rules", ""), 4000, keep_tail=True, preserve_lines=True),
        }
        if isinstance(last_chapter, dict):
            for key in ("outline", "summary", "key_facts"):
                last_chapter[key] = _clip_context_text(
                    last_chapter.get(key, ""), 700, keep_tail=True, preserve_lines=True
                )
            handoff["last_chapter"] = last_chapter
    # Keep the ending anchor well-formed even when a model returns verbose
    # free-form state fields that were not part of the normal source package.
    ending_state = handoff.get("ending_state", {})
    if isinstance(ending_state, dict):
        handoff["ending_state"] = {
            key: _clip_context_text(value, 900, keep_tail=True, preserve_lines=True)
            for key, value in ending_state.items()
            if str(value or "").strip()
        }
    return _enforce_volume_framework_handoff_limit(handoff, total_limit)


def _enforce_volume_framework_handoff_limit(handoff, total_limit):
    """Guarantee the second continuation call keeps structured priorities."""
    handoff = deepcopy(handoff if isinstance(handoff, dict) else {})
    total_limit = max(12000, int(total_limit or VOLUME_FRAMEWORK_HANDOFF_CHAR_BUDGET))
    if _volume_handoff_json_chars(handoff) <= total_limit:
        return handoff

    handoff["volume_summary"] = _clip_context_text(handoff.get("volume_summary", ""), 1800, keep_tail=True, preserve_lines=True)
    handoff["world_state"] = _clip_context_text(handoff.get("world_state", ""), 1800, keep_tail=True, preserve_lines=True)
    handoff["open_threads"] = _compact_volume_handoff_text_list(handoff.get("open_threads", []), 2400, 180)
    handoff["resolved_threads"] = _compact_volume_handoff_text_list(handoff.get("resolved_threads", []), 1400, 140)
    if "continuity_boundaries" in handoff:
        handoff["continuity_boundaries"] = _compact_volume_handoff_text_list(
            handoff.get("continuity_boundaries", []), 2200, 180
        )
    handoff["character_states"] = _compact_volume_handoff_text_list(handoff.get("character_states", []), 2400, 180)
    handoff["relationship_states"] = _compact_volume_handoff_text_list(handoff.get("relationship_states", []), 1600, 160)
    handoff["reusable_characters"] = _compact_volume_handoff_records(
        handoff.get("reusable_characters", []),
        ("name", "role", "goal", "secret", "voice", "notes"),
        {"name": 60, "role": 50, "goal": 60, "secret": 60, "voice": 50, "notes": 70},
        4000,
        minimal_fields=("name", "role"),
    )
    handoff["reusable_lore"] = _compact_volume_handoff_records(
        handoff.get("reusable_lore", []),
        ("name", "type", "description", "story_known"),
        {"name": 50, "type": 20, "description": 45, "story_known": 35},
        8000,
        minimal_fields=("name", "type"),
    )
    handoff["reusable_foreshadows"] = _compact_volume_handoff_records(
        handoff.get("reusable_foreshadows", []),
        ("code", "name", "status", "remaining_secret", "description"),
        {"code": 24, "name": 55, "status": 18, "remaining_secret": 55, "description": 45},
        6000,
        minimal_fields=("code", "name", "status"),
    )
    handoff["resolved_foreshadows"] = _compact_volume_handoff_records(
        handoff.get("resolved_foreshadows", []),
        ("code", "name", "status", "payoff_chapter", "result", "description"),
        {"code": 24, "name": 55, "status": 18, "payoff_chapter": 28, "result": 50, "description": 40},
        2000,
        minimal_fields=("code", "name", "status", "payoff_chapter", "result"),
    )
    handoff["discarded_foreshadows"] = _compact_volume_handoff_records(
        handoff.get("discarded_foreshadows", []),
        ("code", "name", "status"),
        {"code": 24, "name": 55, "status": 18},
        500,
        minimal_fields=("code", "name", "status"),
    )
    handoff["continuity_anchors"] = _compact_volume_continuity_anchors(
        handoff.get("continuity_anchors", []), 1200
    )
    inherited = handoff.get("inherited_materials", {})
    inherited = inherited if isinstance(inherited, dict) else {}
    handoff["inherited_materials"] = {
        "bible": _clip_context_text(inherited.get("bible", ""), 3000, keep_tail=True, preserve_lines=True),
        "world_rules": _clip_context_text(inherited.get("world_rules", ""), 3000, keep_tail=True, preserve_lines=True),
    }
    ending_state = handoff.get("ending_state", {})
    ending_state = ending_state if isinstance(ending_state, dict) else {}
    handoff["ending_state"] = {
        key: _clip_context_text(value, 500, keep_tail=True, preserve_lines=True)
        for key, value in ending_state.items()
        if str(value or "").strip()
    }
    last_chapter = handoff.get("last_chapter", {})
    if isinstance(last_chapter, dict):
        for key in ("title", "outline", "summary", "key_facts"):
            last_chapter[key] = _clip_context_text(last_chapter.get(key, ""), 500, keep_tail=True, preserve_lines=True)
        last_chapter["text"] = _clip_context_text(
            last_chapter.get("text", ""),
            16000,
            keep_tail=True,
            preserve_lines=True,
            preserve_boundaries=True,
        )
        handoff["last_chapter"] = last_chapter
    return handoff


def _build_volume_opening_handoff_context(project, total_limit=12000):
    """Build a compact first-volume ending anchor for a sequel's opening."""
    project = project if isinstance(project, dict) else {}
    continuation = _normalize_series_continuation(project.get("series_continuation", {}))
    try:
        volume_number = int(continuation.get("volume_number", 1) or 1)
    except Exception:
        volume_number = 1
    handoff = continuation.get("handoff", {})
    handoff = handoff if isinstance(handoff, dict) else {}
    if volume_number < 2 or not handoff:
        return ""

    total_limit = max(3000, int(total_limit or 12000))
    ending_state = handoff.get("ending_state", {})
    ending_state = ending_state if isinstance(ending_state, dict) else {}
    compact_ending_state = {
        str(key): _clip_context_text(value, 700, keep_tail=True, preserve_lines=True)
        for key, value in ending_state.items()
        if str(value or "").strip()
    }
    last_chapter = handoff.get("last_chapter", {})
    last_chapter = last_chapter if isinstance(last_chapter, dict) else {}
    fixed_parts = [
        "用途：以下内容是上一卷已经发生的连续性证据，只用于确定本卷开场的初始状态；不是要求复述上一卷，也不是新的剧情任务。",
    ]
    volume_summary = _clip_context_text(
        handoff.get("volume_summary", ""), 2600, keep_tail=True, preserve_lines=True
    )
    if volume_summary:
        fixed_parts.append("上一卷交接摘要：\n" + volume_summary)
    if compact_ending_state:
        fixed_parts.append(
            "上一卷卷末即时状态：\n"
            + json.dumps(compact_ending_state, ensure_ascii=False, indent=2)
        )
    for label, key, limit in (
        ("上一卷最后一章标题", "title", 180),
        ("上一卷最后一章摘要", "summary", 1800),
        ("上一卷最后一章关键事实", "key_facts", 2400),
    ):
        value = _clip_context_text(
            last_chapter.get(key, ""), limit, keep_tail=True, preserve_lines=True
        )
        if value:
            fixed_parts.append(f"{label}：\n{value}")

    fixed_text = "\n\n".join(fixed_parts)
    if len(fixed_text) > total_limit:
        return _clip_context_text(
            fixed_text,
            total_limit,
            keep_tail=True,
            preserve_lines=True,
            preserve_boundaries=True,
        )

    body = str(last_chapter.get("text", "") or "").strip()
    body_heading = "上一卷最后一章已发布正文（只继承卷末状态，本卷不要复述）：\n"
    remaining = total_limit - len(fixed_text) - len(body_heading) - 2
    if body and remaining >= 600:
        body = _clip_context_text(
            body,
            min(8000, remaining),
            keep_tail=True,
            preserve_lines=True,
            preserve_boundaries=True,
        )
        return f"{fixed_text}\n\n{body_heading}{body}"[:total_limit]
    return fixed_text


def _build_volume_handoff_source(project):
    """Build a bounded, continuity-focused source package for a new volume."""
    project = project if isinstance(project, dict) else {}
    meta = project.get("meta", {}) if isinstance(project.get("meta"), dict) else {}
    chapters = project.get("chapters", [])
    chapters = chapters if isinstance(chapters, list) else []
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
    snapshot = deepcopy(memory.get("state_snapshot", {}))
    if not isinstance(snapshot, dict):
        snapshot = {}

    written_chapters = [
        (index, chapter)
        for index, chapter in enumerate(chapters, 1)
        if isinstance(chapter, dict) and str(chapter.get("text", "") or "").strip()
    ]
    def build_written_chapter_record(index, chapter):
        record = {
            "index": index,
            "title": _clip_complete_text(chapter.get("title", ""), 120),
            "outline": _strip_volume_handoff_outline_metadata(chapter.get("outline", "")),
        }
        record = {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }
        if record.get("outline"):
            record["outline"] = _clip_complete_text(record["outline"], 1800)
        return record

    chapter_outlines = [
        record
        for index, chapter in written_chapters
        for record in [build_written_chapter_record(index, chapter)]
        if record.get("outline")
    ]

    def build_full_chapter_record(index, chapter):
        record = _volume_handoff_record(
            chapter,
            ("title", "outline"),
            field_limit=1600,
        )
        record["outline"] = _strip_volume_handoff_outline_metadata(record.get("outline", ""))
        record["index"] = index
        record["text"] = _clip_context_text(
            str(chapter.get("text", "") or "").strip(),
            VOLUME_HANDOFF_LAST_CHAPTER_CHAR_LIMIT,
            keep_tail=True,
            preserve_lines=True,
            preserve_boundaries=True,
        )
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }

    first_chapter = {}
    last_chapter = {}
    if written_chapters:
        first_index, first_source = written_chapters[0]
        last_index, last_source = written_chapters[-1]
        first_chapter = build_full_chapter_record(first_index, first_source)
        last_chapter = build_full_chapter_record(last_index, last_source)


    stage_archive_records = []
    for archive in memory.get("stage_archives", [])[-8:]:
        if not isinstance(archive, dict):
            continue
        stage_archive_records.append(_volume_handoff_record(
            archive,
            (
                "id",
                "start_chapter_index",
                "end_chapter_index",
                "summary",
                "irreversible_facts",
                "relationship_changes",
                "unresolved_threads",
                "next_stage_entry",
            ),
            field_limit=900,
        ))
    compact_archives = _compact_volume_handoff_records(
        stage_archive_records,
        (
            "id", "start_chapter_index", "end_chapter_index", "summary",
            "irreversible_facts", "relationship_changes", "unresolved_threads", "next_stage_entry",
        ),
        {
            "id": 40, "summary": 260, "irreversible_facts": 240,
            "relationship_changes": 220, "unresolved_threads": 220, "next_stage_entry": 220,
        },
        3500,
        minimal_fields=("id", "start_chapter_index", "end_chapter_index", "summary"),
    )

    character_records = [
        _volume_handoff_record(item, ("name", "role", "goal", "secret", "voice", "notes"), field_limit=180)
        for item in project.get("characters", []) if isinstance(item, dict) and str(item.get("name", "") or "").strip()
    ]
    lore_records = [
        _volume_handoff_record(item, ("name", "type", "description", "story_known"), field_limit=180)
        for item in project.get("lore", []) if isinstance(item, dict) and str(item.get("name", "") or "").strip()
    ]
    raw_foreshadows = project.get("foreshadow_items", [])
    raw_foreshadows = raw_foreshadows if isinstance(raw_foreshadows, list) else []
    active_foreshadows = []
    resolved_foreshadows = []
    discarded_foreshadows = []
    foreshadow_fields = (
        "code", "name", "status", "setup_chapter", "payoff_chapter",
        "description", "revealed", "remaining_secret", "notes",
    )
    for item in raw_foreshadows:
        if not isinstance(item, dict) or not str(item.get("name", "") or "").strip():
            continue
        record = _volume_handoff_record(item, foreshadow_fields, field_limit=220)
        status = _infer_foreshadow_status(record, preserve_manual=False) or str(record.get("status", "") or "").strip()
        record["status"] = status
        if status == "已回收":
            resolved_foreshadows.append(record)
        elif status in {"废弃", "无需回收"}:
            discarded_foreshadows.append(record)
        else:
            active_foreshadows.append(record)

    # A new volume keeps terminal-line indexes in private continuation
    # metadata. Bring those concise indexes forward for a possible third or
    # later volume, but never place them back into the active foreshadow pool.
    previous_continuation = _normalize_series_continuation(
        project.get("series_continuation", {})
    )
    previous_handoff = previous_continuation.get("handoff", {})
    previous_handoff = previous_handoff if isinstance(previous_handoff, dict) else {}
    active_terminal_keys = {
        _volume_handoff_record_key(item)
        for item in active_foreshadows
        if _volume_handoff_record_key(item)
    }
    inherited_resolved = [
        item for item in previous_handoff.get("resolved_foreshadows", [])
        if isinstance(item, dict)
        and _volume_handoff_record_key(item)
        and _volume_handoff_record_key(item) not in active_terminal_keys
    ]
    inherited_discarded = [
        item for item in previous_handoff.get("discarded_foreshadows", [])
        if isinstance(item, dict)
        and _volume_handoff_record_key(item)
        and _volume_handoff_record_key(item) not in active_terminal_keys
    ]
    resolved_foreshadows = _dedupe_volume_handoff_terminal_records(
        resolved_foreshadows,
        inherited_resolved,
    )
    discarded_foreshadows = _dedupe_volume_handoff_terminal_records(
        discarded_foreshadows,
        inherited_discarded,
    )

    records = {
        "characters": _compact_volume_handoff_records(
            character_records,
            ("name", "role", "goal", "secret", "voice", "notes"),
            {"name": 80, "role": 80, "goal": 100, "secret": 100, "voice": 80, "notes": 120},
            8000,
            minimal_fields=("name", "role", "goal"),
        ),
        "lore": _compact_volume_handoff_records(
            lore_records,
            ("name", "type", "description", "story_known"),
            {"name": 70, "type": 24, "description": 80, "story_known": 60},
            20000,
            minimal_fields=("name", "type"),
        ),
        # Only unresolved foreshadows stay in the active continuation pool.
        "foreshadows": _compact_volume_handoff_records(
            active_foreshadows,
            foreshadow_fields,
            {
                "code": 28, "name": 70, "status": 20, "setup_chapter": 36,
                "payoff_chapter": 36, "description": 100, "revealed": 80,
                "remaining_secret": 100, "notes": 70,
            },
            12000,
            minimal_fields=("code", "name", "status", "remaining_secret"),
        ),
        # Resolved lines are history: keep a one-line index so they are not
        # reopened in volume 2, but do not spend full-context detail on them.
        "resolved_foreshadows": _compact_volume_handoff_records(
            resolved_foreshadows,
            ("code", "name", "status", "payoff_chapter", "description", "result"),
            {"code": 28, "name": 70, "status": 20, "payoff_chapter": 36, "description": 60, "result": 80},
            5000,
            minimal_fields=("code", "name", "status", "payoff_chapter", "result"),
        ),
        "discarded_foreshadows": _compact_volume_handoff_records(
            discarded_foreshadows,
            ("code", "name", "status"),
            {"code": 28, "name": 70, "status": 20},
            1200,
            minimal_fields=("code", "name", "status"),
        ),
    }

    current_state = {
        "state_snapshot": snapshot,
        "active_facts": deepcopy(memory.get("active_facts", [])[-100:]),
        "fact_history": deepcopy(memory.get("fact_history", [])[-50:]),
        "stage_archives": compact_archives,
    }
    if _volume_handoff_json_chars(current_state) > 4500:
        current_state = {
            "compressed_state": _clip_context_text(
                json.dumps(current_state, ensure_ascii=False, indent=2),
                4300,
                keep_tail=True,
                preserve_lines=True,
            )
        }

    source = {
        "source_project": {
            "title": str(meta.get("title", "") or "").strip(),
            "genre": str(meta.get("genre", "") or "").strip(),
            "style": str(meta.get("style", "") or "").strip(),
            "pov": str(meta.get("pov", "") or "").strip(),
            "premise": _clip_context_text(meta.get("premise", ""), 1600, preserve_lines=True),
            "target_words": str(meta.get("target_words", "") or "").strip(),
        },
        "bible": _clip_context_text(project.get("bible", ""), 5000, keep_tail=True, preserve_lines=True),
        "world_rules": _clip_context_text(project.get("world_rules", ""), 5000, keep_tail=True, preserve_lines=True),
        "timeline": _clip_context_text(project.get("timeline", ""), 6000, keep_tail=True, preserve_lines=True),
        "summary": _clip_context_text(project.get("summary", ""), 6000, keep_tail=True, preserve_lines=True),
        "current_state": current_state,
        "records": records,
        "chapter_outlines": _compact_volume_handoff_records(
            chapter_outlines,
            ("index", "title", "outline"),
            {"index": 20, "title": 100, "outline": 1800},
            24000,
            minimal_fields=("index", "title"),
        ),
        "first_chapter": first_chapter,
        "last_chapter": last_chapter,
    }
    return _compact_volume_handoff_source_for_request(
        source,
        VOLUME_HANDOFF_SOURCE_CHAR_BUDGET,
    )


def _build_volume_handoff_record_catalog(project):
    """Keep full local record details for enriching the model-selected handoff."""
    project = project if isinstance(project, dict) else {}
    characters = [
        _volume_handoff_record(
            item,
            ("id", "name", "role", "goal", "secret", "voice", "notes"),
            field_limit=1800,
        )
        for item in project.get("characters", [])
        if isinstance(item, dict) and str(item.get("name", "") or "").strip()
    ]
    lore = [
        _volume_handoff_record(
            item,
            ("id", "name", "type", "description", "story_known"),
            field_limit=1800,
        )
        for item in project.get("lore", [])
        if isinstance(item, dict) and str(item.get("name", "") or "").strip()
    ]
    foreshadows = []
    for item in project.get("foreshadow_items", []) if isinstance(project.get("foreshadow_items"), list) else []:
        if not isinstance(item, dict) or not str(item.get("name", "") or "").strip():
            continue
        record = _volume_handoff_record(
            item,
            (
                "id", "code", "name", "status", "setup_chapter", "payoff_chapter",
                "description", "revealed", "remaining_secret", "notes",
            ),
            field_limit=1800,
        )
        record["status"] = _infer_foreshadow_status(record, preserve_manual=False)
        foreshadows.append(record)
    return {
        "characters": characters,
        "lore": lore,
        "foreshadows": foreshadows,
    }


def _rebase_long_form_memory_for_volume_continuation(project):
    """Carry the current story state into chapter 1 without stale chapter pointers."""
    source = project if isinstance(project, dict) else {}
    memory = _normalize_long_form_memory(source.get("long_form_memory", {}))
    rebased = deepcopy(memory)
    snapshot = rebased.get("state_snapshot", {})
    snapshot = deepcopy(snapshot) if isinstance(snapshot, dict) else {}
    snapshot["as_of_chapter_id"] = ""
    snapshot["as_of_chapter_index"] = 0
    snapshot["updated_at"] = now_str()
    rebased["schema_version"] = "2"
    rebased["revision"] = 0
    rebased["state_snapshot"] = snapshot
    # Historical archives and runtime IDs belong to volume 1. The active
    # facts/state snapshot are the continuity bridge; new chapters will issue
    # fresh volume-2 revisions and record references.
    rebased["fact_history"] = []
    rebased["stage_archives"] = []
    rebased["record_runtime"] = {"characters": {}, "lore": {}, "foreshadows": {}}
    rebased["update_journal"] = []
    rebased["updated_at"] = now_str()
    return rebased


def _inherit_continuation_record_ids(source_project, target_project):
    """Keep stable IDs for inherited records so the carried state remains linked."""
    source_project = source_project if isinstance(source_project, dict) else {}
    target_project = target_project if isinstance(target_project, dict) else {}
    for key in ("characters", "lore", "foreshadow_items"):
        source_items = source_project.get(key, [])
        target_items = target_project.get(key, [])
        source_items = source_items if isinstance(source_items, list) else []
        target_items = target_items if isinstance(target_items, list) else []
        source_ids = {
            _compact_text(item.get("name", "")): str(item.get("id", "") or "").strip()
            for item in source_items
            if isinstance(item, dict)
            and _compact_text(item.get("name", ""))
            and str(item.get("id", "") or "").strip()
        }
        for item in target_items:
            if not isinstance(item, dict):
                continue
            record_id = source_ids.get(_compact_text(item.get("name", "")))
            if record_id:
                item["id"] = record_id
    return target_project


def _normalize_import_candidates(data):
    data = data if isinstance(data, dict) else {}
    out = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}

    def preserve_candidate_metadata(target, source):
        if not isinstance(target, dict) or not isinstance(source, dict):
            return target
        source_label = str(source.get("_source_label", "") or source.get("source_label", "") or "").strip()
        if source_label:
            target["_source_label"] = source_label
        return target

    for key in ("characters", "lore", "foreshadows"):
        items = data.get(key, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            if not name:
                continue
            clone = dict(item)
            clone["name"] = name
            if key == "characters":
                char_item, lore_item = _prepare_character_candidate(clone, default_notes=str(clone.get("notes", "") or "AI 分析候选"))
                if char_item:
                    char_item["notes"] = _dedupe_text_lines(char_item.get("notes", ""))
                    preserve_candidate_metadata(char_item, clone)
                    out["characters"].append(char_item)
                elif lore_item:
                    lore_item["description"] = _dedupe_text_lines(lore_item.get("description", ""))
                    preserve_candidate_metadata(lore_item, clone)
                    out["lore"].append(lore_item)
            else:
                if key in {"lore", "foreshadows"}:
                    clone["description"] = _dedupe_text_lines(clone.get("description", ""))
                if key == "foreshadows":
                    clone["setup_chapter"] = _normalize_foreshadow_chapter_ref(clone.get("setup_chapter", ""))
                    clone["payoff_chapter"] = _normalize_foreshadow_chapter_ref(clone.get("payoff_chapter", ""))
                preserve_candidate_metadata(clone, item)
                out[key].append(clone)
    materials = data.get("project_materials", {})
    if isinstance(materials, dict):
        out["project_materials"] = {
            key: str(materials.get(key, "") or "").strip()
            for key in ("bible", "world_rules", "timeline", "summary")
        }
    return out


def _import_candidates_has_content(candidates):
    if not isinstance(candidates, dict):
        return False
    if any(candidates.get(key) for key in ("characters", "lore", "foreshadows")):
        return True
    materials = candidates.get("project_materials", {})
    return isinstance(materials, dict) and any(str(value or "").strip() for value in materials.values())


def _dedupe_text_line_key(value):
    text = str(value or "").strip()
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"^(?:补充|新增|补充说明)[：:]\s*", "", text).strip()
    return _compact_text(text)


def _dedupe_text_lines(value):
    lines = str(value or "").splitlines()
    out = []
    seen = set()
    for raw in lines:
        line = raw.strip()
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue
        key = _dedupe_text_line_key(line)
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out).strip()


_LONG_TERM_CONTEXT_PLACEHOLDERS = {
    "AI 分析候选", "文档导入候选", "后续处理", "待后续处理", "待补充", "待定", "待回收",
}


def _long_term_context_core(value):
    text = str(value or "").strip()
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"^(?:补充|新增|补充说明)[：:]\s*", "", text).strip()
    return text.strip(" \t\r\n-•")


def _stable_long_term_context_text(value):
    lines = []
    for raw in str(value or "").splitlines():
        text = _long_term_context_core(raw)
        if not text or _compact_text(text) in {_compact_text(item) for item in _LONG_TERM_CONTEXT_PLACEHOLDERS}:
            continue
        lines.append(str(raw or "").strip())
    return _dedupe_text_lines("\n".join(lines))


def _stable_character_notes_context(value):
    return _stable_long_term_context_text(value)


def _stable_lore_description_context(value):
    return _stable_long_term_context_text(value)


def _stable_foreshadow_description_context(value):
    return _stable_long_term_context_text(value)


def _merge_text_lines_without_duplicates(existing, incoming, prefix="补充："):
    old = _dedupe_text_lines(existing)
    new = _dedupe_text_lines(incoming)
    if not new:
        return old, False
    old_keys = {
        _dedupe_text_line_key(line)
        for line in old.splitlines()
        if str(line or "").strip()
    }
    additions = []
    for line in new.splitlines():
        line = line.strip()
        if not line:
            continue
        key = _dedupe_text_line_key(line)
        if key in old_keys:
            continue
        old_keys.add(key)
        additions.append(line)
    if not old:
        return "\n".join(additions).strip(), bool(additions)
    changed = old != str(existing or "").strip()
    if additions:
        changed = True
        additions_text = "\n".join(
            line if str(line).startswith(prefix) else f"{prefix}{line}"
            for line in additions
        )
        old = f"{old}\n{additions_text}".strip()
    return old, changed


def _is_supplement_line(value):
    return bool(re.match(r"^\s*(?:补充|新增|补充说明)[：:]", str(value or "").strip()))


def _foreshadow_supplement_core(value):
    return _long_term_context_core(value)


def _foreshadow_supplement_source_label(item):
    item = item if isinstance(item, dict) else {}
    for key in (
        "_resolved_chapter_label",
        "resolved_chapter_label",
        "chapter_source_label",
        "payoff_chapter",
        "回收章节",
        "兑现章节",
        "揭晓章节",
        "setup_chapter",
        "埋设章节",
        "铺垫章节",
        "出现章节",
        "chapter_title",
        "_source_label",
        "source_label",
    ):
        raw = str(item.get(key, "") or "").strip()
        if not raw:
            continue
        for value in raw.splitlines():
            value = str(value or "").strip()
            if not value:
                continue
            for _i in range(4):
                cleaned = re.sub(r"^(?:伏笔按章比对|章节|当前章节标题|来源)[：:]\s*", "", value).strip()
                if cleaned == value:
                    break
                value = cleaned
            if not value:
                continue
            if re.search(r"第\s*\d+\s*/\s*\d+\s*块", value):
                continue
            if "章" in value or value.startswith("章节"):
                return value
    return ""


def _foreshadow_supplement_has_source(value):
    text = _foreshadow_supplement_core(value)
    return bool(re.match(r"^(?:第\s*[一二两三四五六七八九十百千万零〇\d]+\s*章|章节\s*[一二两三四五六七八九十百千万零〇\d]+|章\s*[一二两三四五六七八九十百千万零〇\d]+)", text))


def _format_foreshadow_supplement(value, source_item=None):
    core = _foreshadow_supplement_core(value)
    if not core:
        return ""
    source = _foreshadow_supplement_source_label(source_item)
    if source and not _foreshadow_supplement_has_source(core):
        core = f"{source}：{core}"
    return f"补充：{core}"


def _limit_foreshadow_description_supplements(value, max_supplements=2):
    lines = [
        str(line or "").strip()
        for line in _dedupe_text_lines(value).splitlines()
        if str(line or "").strip()
    ]
    if not lines:
        return ""
    body_lines = []
    supplement_lines = []
    for line in lines:
        if _is_supplement_line(line):
            supplement_lines.append(line)
        else:
            body_lines.append(line)
    if len(supplement_lines) > max_supplements:
        supplement_lines = [supplement_lines[0], supplement_lines[-1]]
    return "\n".join(body_lines + supplement_lines).strip()


def _merge_foreshadow_description_without_bloat(existing, incoming, source_item=None):
    old = _limit_foreshadow_description_supplements(existing)
    new = _dedupe_text_lines(incoming)
    if not new:
        return old, old != str(existing or "").strip()
    if not old or old in {"AI 分析候选", "文档导入候选"}:
        merged = _limit_foreshadow_description_supplements(new)
        return merged, merged != str(existing or "").strip()
    old_keys = {
        _dedupe_text_line_key(_foreshadow_supplement_core(line))
        for line in old.splitlines()
        if str(line or "").strip()
    }
    addition_parts = []
    for line in new.splitlines():
        core = _foreshadow_supplement_core(line)
        if not core:
            continue
        key = _dedupe_text_line_key(core)
        if key in old_keys:
            continue
        old_keys.add(key)
        addition_parts.append(core)
    if not addition_parts:
        return old, old != str(existing or "").strip()
    addition = _format_foreshadow_supplement("；".join(addition_parts), source_item)
    if not addition:
        return old, old != str(existing or "").strip()
    merged = _limit_foreshadow_description_supplements(f"{old}\n{addition}")
    return merged, merged != str(existing or "").strip()


def _text_len(value):
    return len(str(value or "").strip())


def _body_display_len(value):
    return len(re.sub(r"\s+", "", str(value or "")))


def _line_join_length(lines):
    return len("\n".join(str(line or "") for line in lines))


def _clip_lines_head(lines, limit):
    lines = [str(line or "").strip() for line in (lines or []) if str(line or "").strip()]
    limit = int(limit or 0)
    if not lines or limit <= 0:
        return ""
    text = "\n".join(lines)
    if len(text) <= limit:
        return text
    kept = []
    for index, line in enumerate(lines):
        omitted = len(lines) - index
        marker = f"……（后续 {omitted} 条已压缩省略）……"
        candidate = "\n".join(kept + [line, marker]).strip() if kept else "\n".join([line, marker]).strip()
        if len(candidate) <= limit:
            kept.append(line)
            continue
        if kept:
            omitted = len(lines) - len(kept)
            marker = f"……（后续 {omitted} 条已压缩省略）……"
            candidate = "\n".join(kept + [marker]).strip()
            if len(candidate) <= limit:
                return candidate
            return "\n".join(kept).strip()
        return _clip_complete_text(line, limit, keep_tail=True)
    return "\n".join(kept).strip()


def _tail_lines_by_limit(lines, limit):
    lines = [str(line or "").strip() for line in (lines or []) if str(line or "").strip()]
    limit = int(limit or 0)
    if not lines or limit <= 0:
        return []
    if _line_join_length(lines) <= limit:
        return lines
    selected = []
    total = 0
    for line in reversed(lines):
        line_len = len(line) + (1 if selected else 0)
        if selected and total + line_len > limit:
            break
        if not selected and line_len > limit:
            selected.append(_clip_complete_text(line, limit, keep_tail=True))
            break
        selected.append(line)
        total += line_len
    return list(reversed(selected))


def _select_lines_by_char_budget(lines, limit, omitted_label="条"):
    lines = [str(line or "").strip() for line in (lines or []) if str(line or "").strip()]
    limit = int(limit or 0)
    if not lines:
        return []
    if limit <= 0 or _line_join_length(lines) <= limit:
        return lines
    selected = []
    for index, line in enumerate(lines):
        omitted = len(lines) - index
        marker = f"- ……另有 {omitted} {omitted_label}已省略"
        candidate = "\n".join(selected + [line, marker]).strip()
        if len(candidate) <= limit:
            selected.append(line)
            continue
        break
    omitted = len(lines) - len(selected)
    if omitted > 0:
        marker = f"- ……另有 {omitted} {omitted_label}已省略"
        if selected and len("\n".join(selected + [marker]).strip()) <= limit:
            selected.append(marker)
        elif not selected:
            selected.append(_clip_complete_text(lines[0], limit, keep_tail=True))
    return selected


def _semantic_text_units(value):
    text = _clean_empty_numbered_list_items(_dedupe_text_lines(value))
    if not text:
        return []
    units = []
    for raw in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]\s+|[（(]?\d+[）).、]\s*)", "", raw).strip()
        if not line or line in {"无", "没有", "暂无", "无新增"}:
            continue
        parts = [
            part.strip()
            for part in re.findall(r".+?(?:……|[。！？!?；;]+|$)", line)
            if part.strip()
        ]
        units.extend(parts or [line])
    out = []
    seen = set()
    for unit in units:
        key = _compact_text(unit)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(unit)
    return out


def _join_semantic_units(units, separator=None):
    units = [str(unit or "").strip() for unit in (units or []) if str(unit or "").strip()]
    if not units:
        return ""
    if separator is not None:
        return str(separator).join(units).strip()
    out = ""
    for unit in units:
        if not out:
            out = unit
            continue
        if out[-1:] in "。！？!?；;…\n" or unit[:1] in "，,。！？!?；;…":
            out += unit
        else:
            out += "；" + unit
    return out.strip()


def _fit_complete_units(value, limit, keep_tail=False, separator=None):
    units = _semantic_text_units(value)
    limit = int(limit or 0)
    if not units:
        return ""
    text = _join_semantic_units(units, separator=separator)
    if limit <= 0 or len(text) <= limit:
        return text
    ordered = list(reversed(units)) if keep_tail else list(units)
    selected = []
    for unit in ordered:
        candidate_units = selected + [unit]
        candidate = _join_semantic_units(candidate_units, separator=separator)
        if selected and len(candidate) > limit:
            break
        if not selected and len(unit) > limit:
            marker = "……（单条事实过长，已裁剪）……"
            if keep_tail and limit > len(marker) + 80:
                return marker + unit[-(limit - len(marker)):].lstrip()
            return unit[: max(0, limit - len(marker))].rstrip() + marker
        selected.append(unit)
    if keep_tail:
        selected.reverse()
    return _join_semantic_units(selected, separator=separator)


def _clip_complete_text(value, limit, keep_tail=False, separator=None):
    text = _dedupe_text_lines(value)
    limit = int(limit or 0)
    if not text or limit <= 0 or len(text) <= limit:
        return text
    fitted = _fit_complete_units(text, limit, keep_tail=keep_tail, separator=separator)
    if fitted:
        return fitted
    marker = "……（内容过长，已裁剪）……"
    if keep_tail and limit > len(marker) + 80:
        return marker + text[-(limit - len(marker)):].lstrip()
    return text[: max(0, limit - len(marker))].rstrip() + marker


def _clip_context_text(value, limit, keep_tail=False, preserve_lines=False, preserve_boundaries=False):
    text = str(value or "").strip()
    limit = int(limit or 0)
    if limit <= 0 or len(text) <= limit:
        return text
    if preserve_lines:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) <= 1:
            lines = [
                part.strip()
                for part in re.findall(r".+?(?:……|[。！？!?；;…]+|$)", text)
                if part.strip()
            ]
        if len(lines) > 1:
            if keep_tail:
                return _clip_lines_balanced(lines, limit, preserve_boundaries=preserve_boundaries)
            return _clip_lines_head(lines, limit)
    marker = "\n……（内容过长，已裁剪）……\n"
    if keep_tail and limit > len(marker) + 200:
        head_len = max(120, limit // 3)
        tail_len = max(120, limit - head_len - len(marker))
        return text[:head_len].rstrip() + marker + text[-tail_len:].lstrip()
    return text[: max(0, limit - len(marker))].rstrip() + marker.strip()


def _compact_chapter_summary_text(value, max_chars=0, max_sentences=0):
    text = _clean_empty_numbered_list_items(_dedupe_text_lines(value))
    max_chars = int(max_chars or 0)
    if not text:
        return ""
    if max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text
    parts = [
        part.strip()
        for part in re.findall(r".+?(?:……|[。！？!?…]+|$)", text.replace("\n", " "))
        if part.strip()
    ]
    if parts:
        selected = []
        total = 0
        for part in parts:
            next_total = total + len(part)
            if max_chars > 0 and selected and next_total > max_chars:
                break
            if max_chars > 0 and not selected and len(part) > max_chars:
                break
            selected.append(part)
            total = next_total
        compacted = "".join(selected).strip()
        if compacted:
            return compacted
    if max_chars > 0:
        return _clip_context_text(text, max_chars, keep_tail=True)
    return text


def _clean_empty_numbered_list_items(value):
    cleaned_lines = []
    for raw in str(value or "").splitlines():
        line = str(raw or "").strip()
        if not line:
            continue
        previous = None
        while previous != line:
            previous = line
            line = re.sub(r"(?:^|(?<=[。！？!?；;，,\s]))[（(]?\d{1,3}[）).、。]\s*$", "", line).strip()
            line = re.sub(r"(?:^|(?<=[。！？!?；;，,\s]))[一二三四五六七八九十]{1,4}[、.。]\s*$", "", line).strip()
        if not line or re.fullmatch(r"(?:[-*•]+|[（(]?\d{1,3}[）).、。]?|[一二三四五六七八九十]{1,4}[、.。]?)", line):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def _compact_chapter_key_facts_text(value, max_chars=0, max_items=0):
    text = _clean_empty_numbered_list_items(_dedupe_text_lines(value))
    max_chars = int(max_chars or 0)
    if not text:
        return ""
    raw_items = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]\s+|[（(]?\d+[）).、]\s*)", "", line).strip()
        if not line or line in {"无", "没有", "暂无", "无新增"}:
            continue
        sentence_parts = []
        for part in re.findall(r".+?(?:……|[。！？!?…]+|$)", line):
            part = part.strip()
            if not part:
                continue
            segments = [seg.strip() for seg in re.split(r"(?<=[；;])", part) if seg.strip()]
            sentence_parts.extend(segments or [part])
        raw_items.extend(sentence_parts or [line])

    items = []
    seen = set()
    for item in raw_items:
        item = item.strip()
        if not item:
            continue
        key = re.sub(r"\s+", "", item)
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    compacted = "\n".join(items).strip()
    if max_chars <= 0 or len(compacted) <= max_chars:
        return compacted
    kept = []
    total = 0
    for item in items:
        item_len = len(item) + (1 if kept else 0)
        if kept and total + item_len > max_chars:
            break
        kept.append(item)
        total += item_len
    return "\n".join(kept).strip()


def _clip_lines_balanced(lines, limit, head=8, tail=10, preserve_boundaries=False):
    lines = [str(line or "").strip() for line in (lines or []) if str(line or "").strip()]
    limit = int(limit or 0)
    if not lines or limit <= 0:
        return ""
    text = "\n".join(lines)
    if len(text) <= limit:
        return text

    if preserve_boundaries:
        # Lock both boundaries before spending any budget on the middle. The
        # volume-ending chapter uses this mode because its opening situation
        # and final action are both continuity-critical.
        if len(lines) == 1:
            return _clip_context_text(text, limit, keep_tail=True)
        head_lines = [lines[0]]
        tail_lines = [lines[-1]]
        head_index = 1
        tail_index = len(lines) - 2
    else:
        head_lines = []
        tail_lines = []
        head_index = 0
        tail_index = len(lines) - 1

    def build_text(extra_head=None, extra_tail=None):
        head_part = head_lines + ([extra_head] if extra_head else [])
        tail_part = ([extra_tail] if extra_tail else []) + tail_lines
        omitted = max(0, len(lines) - len(head_part) - len(tail_part))
        marker = f"……（中间 {omitted} 条已按字符预算压缩省略）……"
        return "\n".join(head_part + [marker] + tail_part).strip()

    def can_add_head():
        if head_index > tail_index:
            return False
        return len(build_text(extra_head=lines[head_index])) <= limit

    def can_add_tail():
        if head_index > tail_index:
            return False
        return len(build_text(extra_tail=lines[tail_index])) <= limit

    # The normal case has enough room for both exact boundary lines.  Keep a
    # compact boundary fallback for pathological single-line payloads so the
    # function still honours the hard limit without dropping the ending.
    if len(build_text()) > limit:
        marker = f"……（中间 {max(0, len(lines) - 2)} 条已按字符预算压缩省略）……"
        boundary_budget = max(2, limit - len(marker) - 2)
        first_budget = max(1, boundary_budget // 2)
        last_budget = max(1, boundary_budget - first_budget)
        head_lines = [lines[0][:first_budget]]
        tail_lines = [lines[-1][-last_budget:]]
        # The marker length depends on the number of omitted lines. Trim
        # boundary fragments against the actual rendered result, never by
        # slicing the completed string, so the ending fragment stays at the
        # end of the returned context.
        while len(build_text()) > limit and (len(head_lines[0]) > 1 or len(tail_lines[0]) > 1):
            overflow = len(build_text()) - limit
            if len(head_lines[0]) >= len(tail_lines[0]) and len(head_lines[0]) > 1:
                head_lines[0] = head_lines[0][:-max(1, (overflow + 1) // 2)]
            elif len(tail_lines[0]) > 1:
                tail_lines[0] = tail_lines[0][max(1, overflow):]
            else:
                break
        rendered = build_text()
        if len(rendered) <= limit:
            return rendered
        # A limit smaller than the marker itself cannot represent both
        # boundaries and the omission notice. Preserve the final boundary,
        # which is the higher-value continuity anchor in this emergency case.
        return tail_lines[0][-limit:]

    while head_index <= tail_index:
        progressed = False
        head_chars = _line_join_length(head_lines)
        tail_chars = _line_join_length(tail_lines)
        if preserve_boundaries:
            prefer_tail = bool(tail_lines) and tail_chars <= head_chars
        else:
            # Historical-summary compression intentionally favors the recent
            # tail until it has an anchor, so old milestones do not consume
            # the small draft-context budget.
            prefer_tail = not head_lines or tail_chars <= head_chars
        attempts = ("tail", "head") if prefer_tail else ("head", "tail")
        for side in attempts:
            if side == "head" and can_add_head():
                head_lines.append(lines[head_index])
                head_index += 1
                progressed = True
                break
            if side == "tail" and can_add_tail():
                tail_lines.insert(0, lines[tail_index])
                tail_index -= 1
                progressed = True
                break
        if not progressed:
            break

    return build_text()


def _drop_first_nonempty_lines(text, count):
    lines = str(text or "").splitlines()
    if count <= 0:
        return "\n".join(lines).strip()
    skipped = 0
    start_index = 0
    for index, line in enumerate(lines):
        if line.strip():
            skipped += 1
        if skipped >= count:
            start_index = index + 1
            break
    if skipped < count:
        return ""
    return "\n".join(lines[start_index:]).strip()


def _append_text_without_duplicate_overlap(existing, addition):
    existing = str(existing or "").strip()
    addition = str(addition or "").strip()
    if not existing:
        return addition
    if not addition:
        return existing
    if addition.startswith(existing):
        return addition
    if existing.endswith(addition):
        return existing

    max_raw_overlap = min(len(existing), len(addition), 2000)
    for size in range(max_raw_overlap, 19, -1):
        if existing[-size:] == addition[:size]:
            addition = addition[size:].lstrip()
            return (existing + "\n\n" + addition).strip() if addition else existing

    old_lines = [line.strip() for line in existing.splitlines() if line.strip()]
    new_lines = [line.strip() for line in addition.splitlines() if line.strip()]
    max_line_overlap = min(len(old_lines), len(new_lines), 8)
    for count in range(max_line_overlap, 0, -1):
        if [_compact_text(line) for line in old_lines[-count:]] == [
            _compact_text(line) for line in new_lines[:count]
        ]:
            addition = _drop_first_nonempty_lines(addition, count)
            return (existing + "\n\n" + addition).strip() if addition else existing
    return (existing + "\n\n" + addition).strip()


def _tail_text_window(value, limit=1800):
    text = str(value or "").strip()
    if not text:
        return ""
    limit = int(limit or 0)
    if limit <= 0 or len(text) <= limit:
        return text
    marker = "……（前文已省略，以下为结尾原文）……\n"
    if limit <= len(marker) + 80:
        return text[-limit:].lstrip()
    return marker + text[-(limit - len(marker)):].lstrip()


def _name_in_text(name, text):
    name = _clean_entity_name(name)
    if not name:
        return False
    text = str(text or "")
    if re.search(r"[A-Za-z]", name):
        return name.lower() in text.lower()
    return name in text


def _record_aliases(item, name_key="name"):
    item = item if isinstance(item, dict) else {}
    aliases = []
    name = _clean_entity_name(item.get(name_key, ""))
    if name:
        aliases.append(name)
        aliases.extend(_normalize_name_list(name))
    alias_source = "\n".join(
        str(item.get(key, "") or "")
        for key in ("description", "story_known", "notes")
        if key in item
    )
    alias_labels = (
        "别称", "别名", "又名", "化名", "称呼", "代称", "简称",
        "绰号", "外号", "代号", "真名", "本名", "原名", "曾用名",
        "旧名", "身份名", "马甲", "尊称", "昵称", "通称", "称号",
        "封号", "头衔", "身份称呼",
    )
    alias_pattern = "|".join(re.escape(label) for label in alias_labels)
    for match in re.findall(rf"(?:{alias_pattern})[：:]\s*([^\n。；;]+)", alias_source):
        aliases.extend(_normalize_name_list(match))
    for match in re.findall(
        r"(?:也称|称作|称为|通称|叫做)[：:\s]*[“\"「『]?([^”\"」』；;。\n]{1,24})",
        alias_source,
    ):
        aliases.extend(_normalize_name_list(match))
    for prefix in ("老", "当年", "年轻", "灰衣", "灰袍"):
        if name.startswith(prefix) and len(name) > len(prefix) + 1:
            aliases.append(name[len(prefix):])
    out = []
    seen = set()
    for alias in aliases:
        alias = _clean_entity_name(alias)
        key = _compact_text(alias)
        if not alias or key in seen:
            continue
        seen.add(key)
        out.append(alias)
    return out


def _record_alias_keys(item, name_key="name"):
    return {
        _compact_text(alias)
        for alias in _record_aliases(item, name_key=name_key)
        if _compact_text(alias)
    }


def _prioritize_named_records(records, context_text, linked_names=None, name_key="name", limit=24, score_func=None, min_score=1):
    records = records if isinstance(records, list) else []
    linked_keys = {_compact_text(name) for name in _normalize_name_list(linked_names or [])}
    ranked = []
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            continue
        aliases = _record_aliases(item, name_key=name_key)
        if not aliases:
            continue
        alias_keys = {_compact_text(alias) for alias in aliases}
        score = 0
        if alias_keys & linked_keys:
            score += 1000
        if any(_name_in_text(alias, context_text) for alias in aliases):
            score += 600
        if score_func is not None:
            try:
                score += int(score_func(item) or 0)
            except Exception:
                pass
        if score < int(min_score or 0):
            continue
        ranked.append((-score, index, item))
    ranked.sort()
    if limit is None or int(limit or 0) <= 0:
        return [item for _score, _index, item in ranked]
    return [item for _score, _index, item in ranked[: int(limit or 0)]]


def _infer_linked_character_names(project, chapter, extra_text=""):
    project = project if isinstance(project, dict) else {}
    chapter = chapter if isinstance(chapter, dict) else {}
    context_text = "\n".join(
        str(value or "")
        for value in (
            chapter.get("title", ""),
            chapter.get("outline", ""),
            chapter.get("text", ""),
            chapter.get("summary", ""),
            chapter.get("key_facts", ""),
            extra_text,
        )
    )
    if not _compact_text(context_text):
        return []

    matched = []
    for index, char in enumerate(project.get("characters", []) if isinstance(project.get("characters", []), list) else []):
        if not isinstance(char, dict):
            continue
        name = _clean_entity_name(char.get("name", ""))
        if not name:
            continue
        aliases = _record_aliases(char)
        if any(_name_in_text(alias, context_text) for alias in aliases):
            matched.append((index, name))
    return _normalize_name_list([name for _index, name in matched])


def _infer_lore_names(project, chapter, extra_text=""):
    project = project if isinstance(project, dict) else {}
    chapter = chapter if isinstance(chapter, dict) else {}
    context_text = "\n".join(
        str(value or "")
        for value in (
            chapter.get("title", ""),
            chapter.get("outline", ""),
            chapter.get("text", ""),
            chapter.get("summary", ""),
            chapter.get("key_facts", ""),
            extra_text,
        )
    )
    if not _compact_text(context_text):
        return []

    matched = []
    for index, item in enumerate(project.get("lore", []) if isinstance(project.get("lore", []), list) else []):
        if not isinstance(item, dict):
            continue
        name = _clean_entity_name(item.get("name", ""))
        if not name:
            continue
        aliases = _record_aliases(item, name_key="name")
        if any(_name_in_text(alias, context_text) for alias in aliases):
            matched.append((index, name))
    return _normalize_name_list([name for _index, name in matched])


_CORE_CHARACTER_DETAIL_KEYWORDS = (
    "主角", "男主", "女主", "主人公", "主线", "核心", "主要", "关键", "重要", "反派",
    "宿敌", "敌手", "boss", "最终", "搭档", "同伴", "队友", "爱人", "恋人", "伴侣",
)
_MINOR_CHARACTER_DETAIL_KEYWORDS = (
    "路人", "过场", "群众", "龙套", "杂兵", "店小二", "侍女", "丫鬟", "仆人", "随从",
    "士兵", "护卫", "侍卫",
)
_GENERIC_CHARACTER_ROLE_LABELS = {
    "主角", "男主", "男主角", "女主", "女主角", "主人公", "男主人公", "女主人公",
    "反派", "大反派", "主要反派", "最终反派", "boss", "最终boss",
    "搭档", "同伴", "队友", "爱人", "恋人", "伴侣",
    "关键配角", "重要配角", "主要配角", "核心配角",
    "关键人物", "重要人物", "主要人物", "核心人物", "主线人物", "主线角色",
}


def _is_generic_character_role_label(value):
    return _compact_text(value).lower() in _GENERIC_CHARACTER_ROLE_LABELS


def _character_activity_stats(project):
    project = project if isinstance(project, dict) else {}
    characters = project.get("characters", [])
    characters = characters if isinstance(characters, list) else []
    records = []
    for index, char in enumerate(characters):
        if not isinstance(char, dict):
            continue
        name = _clean_entity_name(char.get("name", ""))
        aliases = _record_aliases(char)
        if name and aliases:
            records.append((index, name, aliases))
    stats = {name: {"chapters": 0, "last_chapter": ""} for _index, name, _aliases in records}
    chapters = project.get("chapters", [])
    chapters = chapters if isinstance(chapters, list) else []
    for chapter_index, chap in enumerate(chapters, 1):
        if not isinstance(chap, dict):
            continue
        linked = chap.get("linked_characters", [])
        linked_keys = {
            _compact_text(name)
            for name in (linked if isinstance(linked, list) else _normalize_name_list(linked))
            if str(name or "").strip()
        }
        text = "\n".join(
            str(chap.get(key, "") or "")
            for key in ("title", "outline", "text", "summary", "key_facts")
        )
        label = _chapter_label(chapter_index, chap)
        for _index, name, aliases in records:
            alias_keys = {_compact_text(alias) for alias in aliases}
            if (
                (alias_keys & linked_keys)
                or any(_name_in_text(alias, text) for alias in aliases)
            ):
                stats[name]["chapters"] += 1
                stats[name]["last_chapter"] = label
    return stats


def _lore_activity_stats(project):
    project = project if isinstance(project, dict) else {}
    lore_items = project.get("lore", [])
    lore_items = lore_items if isinstance(lore_items, list) else []
    records = []
    for index, item in enumerate(lore_items):
        if not isinstance(item, dict):
            continue
        name = _clean_entity_name(item.get("name", ""))
        aliases = _record_aliases(item, name_key="name")
        if name and aliases:
            records.append((index, name, aliases))
    stats = {name: {"chapters": 0, "last_chapter": ""} for _index, name, _aliases in records}
    chapters = project.get("chapters", [])
    chapters = chapters if isinstance(chapters, list) else []
    for chapter_index, chap in enumerate(chapters, 1):
        if not isinstance(chap, dict):
            continue
        text = "\n".join(
            str(chap.get(key, "") or "")
            for key in ("title", "outline", "text", "summary", "key_facts")
        )
        label = _chapter_label(chapter_index, chap)
        for _index, name, aliases in records:
            item = lore_items[_index]
            if any(_name_in_text(alias, text) for alias in aliases):
                stats[name]["chapters"] += 1
                stats[name]["last_chapter"] = label
    return stats


def _character_detail_threshold(total_chapters):
    if total_chapters <= 0:
        return 3
    return max(3, min(8, total_chapters // 8 or 3))


def _should_check_character_details(char, activity_count=0, total_chapters=0):
    char = char if isinstance(char, dict) else {}
    text = " ".join(str(char.get(key, "") or "") for key in ("name", "role", "notes")).lower()
    if any(keyword in text for keyword in _CORE_CHARACTER_DETAIL_KEYWORDS):
        return True
    threshold = _character_detail_threshold(total_chapters)
    if any(keyword in text for keyword in _MINOR_CHARACTER_DETAIL_KEYWORDS) and activity_count < threshold + 2:
        return False
    return activity_count >= threshold


def _candidate_long_term_review_reasons(project, kind, item):
    return []


def _sanitize_candidate_for_long_form(project, kind, item):
    item = dict(item) if isinstance(item, dict) else {}
    if not str(item.get("name", "") or "").strip():
        return None, False
    changed = False

    if kind == "characters":
        notes = _dedupe_text_lines(item.get("notes", ""))
        stable_notes = _stable_character_notes_context(notes)
        if notes != stable_notes:
            item["notes"] = stable_notes
            changed = True
        return item, changed

    if kind == "lore":
        desc = _dedupe_text_lines(item.get("description", ""))
        stable_desc = _stable_lore_description_context(desc)
        if desc != stable_desc:
            item["description"] = stable_desc
            changed = True
        return item, changed

    if kind == "foreshadows":
        desc = _dedupe_text_lines(item.get("description", ""))
        stable_desc = _stable_foreshadow_description_context(desc)
        if desc != stable_desc:
            item["description"] = stable_desc
            changed = True
        return item, changed

    return item, False


def _sanitize_import_candidates_for_long_form(project, candidates):
    candidates = candidates if isinstance(candidates, dict) else {}
    out = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
    report = {
        "filtered": {"characters": 0, "lore": 0, "foreshadows": 0},
        "trimmed": {"characters": 0, "lore": 0, "foreshadows": 0},
    }
    for kind in ("characters", "lore", "foreshadows"):
        for item in candidates.get(kind, []) if isinstance(candidates.get(kind, []), list) else []:
            cleaned, changed = _sanitize_candidate_for_long_form(project, kind, item)
            if cleaned is None:
                report["filtered"][kind] += 1
                continue
            if changed:
                report["trimmed"][kind] += 1
            out[kind].append(cleaned)
    materials = candidates.get("project_materials", {})
    if isinstance(materials, dict):
        out["project_materials"] = {
            key: str(materials.get(key, "") or "").strip()
            for key in ("bible", "world_rules", "timeline", "summary")
        }
    return out, report


def _active_character_summary_lines(project, limit=12):
    project = project if isinstance(project, dict) else {}
    characters = project.get("characters", [])
    characters = characters if isinstance(characters, list) else []
    activity = _character_activity_stats(project)
    ranked = []
    for index, char in enumerate(characters):
        if not isinstance(char, dict):
            continue
        name = _clean_entity_name(char.get("name", ""))
        count = int(activity.get(name, {}).get("chapters", 0) or 0)
        if name and count > 0:
            ranked.append((-count, index, name, char, activity.get(name, {})))
    ranked.sort()
    lines = []
    selected = ranked if limit is None or int(limit or 0) <= 0 else ranked[: int(limit or 0)]
    for _score, _index, name, char, stat in selected:
        detail_parts = []
        for label, field, clip_limit in (
            ("身份", "role", 80),
            ("目标", "goal", 120),
            ("秘密", "secret", 100),
            ("语言", "voice", 100),
        ):
            value = _clip_complete_text(char.get(field, ""), clip_limit)
            if value:
                detail_parts.append(f"{label}：{value}")
        last_chapter = str(stat.get("last_chapter", "") or "").strip()
        progress = f"出现 {stat.get('chapters', 0)} 章"
        if last_chapter:
            progress += f"｜最近：{last_chapter}"
        tail = "｜" + "｜".join(detail_parts) if detail_parts else ""
        lines.append(f"- {name}｜{progress}{tail}")
    return lines


def _active_lore_summary_lines(project, limit=12):
    project = project if isinstance(project, dict) else {}
    lore_items = project.get("lore", [])
    lore_items = lore_items if isinstance(lore_items, list) else []
    activity = _lore_activity_stats(project)
    ranked = []
    for index, item in enumerate(lore_items):
        if not isinstance(item, dict):
            continue
        name = _clean_entity_name(item.get("name", ""))
        count = int(activity.get(name, {}).get("chapters", 0) or 0)
        if name and count > 0:
            ranked.append((-count, index, name, item, activity.get(name, {})))
    ranked.sort()
    lines = []
    selected = ranked if limit is None or int(limit or 0) <= 0 else ranked[: int(limit or 0)]
    for _score, _index, name, item, stat in selected:
        typ = str(item.get("type", "") or "其他").strip()
        desc = _clip_complete_text(_stable_lore_description_context(item.get("description", "")), 160)
        last_chapter = str(stat.get("last_chapter", "") or "").strip()
        progress = f"出现 {stat.get('chapters', 0)} 章"
        if last_chapter:
            progress += f"｜最近：{last_chapter}"
        tail = f"｜{desc}" if desc else ""
        lines.append(f"- {name}｜{typ}｜{progress}{tail}")
    return lines


def _project_stats(data):
    data = data if isinstance(data, dict) else {}
    chapters = data.get("chapters") if isinstance(data.get("chapters"), list) else []
    characters = data.get("characters") if isinstance(data.get("characters"), list) else []
    lore = data.get("lore") if isinstance(data.get("lore"), list) else []
    foreshadow_items = data.get("foreshadow_items") if isinstance(data.get("foreshadow_items"), list) else []
    body_words = sum(_body_display_len(chap.get("text", "")) for chap in chapters if isinstance(chap, dict))
    outline_words = sum(_text_len(chap.get("outline", "")) for chap in chapters if isinstance(chap, dict))
    summary_facts_words = sum(
        _text_len("\n".join([str(chap.get("summary", "") or ""), str(chap.get("key_facts", "") or "")]))
        for chap in chapters
        if isinstance(chap, dict)
    )
    bible_section_words = sum(_text_len(data.get(key, "")) for key in ("bible", "world_rules"))
    bible_words = sum(_text_len(data.get(key, "")) for key in ("bible", "world_rules", "timeline", "foreshadows", "summary"))
    return {
        "body_words": body_words,
        "outline_words": outline_words,
        "summary_facts_words": summary_facts_words,
        "bible_section_words": bible_section_words,
        "bible_words": bible_words,
        "chapters": len(chapters),
        "characters": len(characters),
        "lore": len(lore),
        "foreshadows": len(foreshadow_items),
        "total_words": body_words + outline_words + summary_facts_words + bible_words,
    }


def _long_form_progress_text(project, chapter_index):
    project = project if isinstance(project, dict) else {}
    meta = project.get("meta", {}) if isinstance(project.get("meta"), dict) else {}
    stats = _project_stats(project)
    target = _target_words(meta) or 200000
    progress = min(1.5, stats["body_words"] / max(1, target))
    chapters = project.get("chapters", [])
    chapter_count = len(chapters) if isinstance(chapters, list) else 0
    chapter_pos = (chapter_index + 1) / max(1, chapter_count)
    stage_ratio = max(progress, chapter_pos * 0.75)
    if stage_ratio < 0.18:
        stage = "开篇建立"
        advice = "建立主角目标、核心矛盾和主要关系；埋钩子但不要过早解释全部真相。"
    elif stage_ratio < 0.45:
        stage = "前中段推进"
        advice = "推进主线调查/行动，持续制造选择压力；让人物关系和阶段目标发生可继承变化。"
    elif stage_ratio < 0.72:
        stage = "中段深化"
        advice = "兑现部分线索并制造更高代价；避免原地反复，重点写转折、代价、关系变化。"
    elif stage_ratio < 0.9:
        stage = "后段收束"
        advice = "减少新增大型设定，集中回收伏笔、压紧冲突，把人物推向最终选择。"
    else:
        stage = "结局收束"
        advice = "优先解决核心矛盾和情感归宿，回收关键伏笔；不要再开启需要长篇展开的新主线。"
    target_label = _target_words_label(meta.get("target_words", "")) or f"{target}字"
    return "\n".join([
        f"项目总目标规模：{target_label}",
        f"当前进度字数：{stats['body_words']} / {target} 字，约 {progress * 100:.1f}%",
        f"当前章节：第 {chapter_index + 1}/{max(1, chapter_count)} 章",
        f"自动判断阶段：{stage}",
        f"节奏建议：控制本章推进密度，{advice}",
    ])


def _project_list_text(data, fallback_title="未命名小说"):
    data = data if isinstance(data, dict) else {}
    meta = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
    title = meta.get("title") or fallback_title or "未命名小说"
    stats = _project_stats(data)
    return f"{title}  ·  {stats['body_words']}字正文  ·  {stats['chapters']}章"


def _project_summary_record_text(record):
    record = record if isinstance(record, dict) else {}
    title = str(record.get("title", "") or record.get("filename", "") or "未命名小说").strip()
    if title.lower().endswith(".json"):
        title = os.path.splitext(title)[0]
    body_words = int(record.get("body_words", 0) or 0)
    chapters = int(record.get("chapters", 0) or 0)
    return f"{title}  ·  {body_words}字正文  ·  {chapters}章"


def _project_summary_text(project, fallback=None):
    project = project if isinstance(project, dict) else {}
    fallback = fallback if isinstance(fallback, dict) else {}
    meta = project.get("meta", {}) if isinstance(project.get("meta"), dict) else {}
    title = str(meta.get("title", "") or fallback.get("title", "") or "未命名小说").strip()
    genre = str(meta.get("genre", "") or fallback.get("genre", "") or "").strip()
    target = _target_words_label(meta.get("target_words", "") or fallback.get("target_words", ""))
    status = str(meta.get("status", "") or fallback.get("status", "") or "").strip()
    parts = [title]
    if genre:
        parts.append(genre)
    if target:
        parts.append(target)
    if status:
        parts.append(status)
    return " · ".join(parts)


def _project_meta_text(project, source):
    stats = _project_stats(project)
    target = _target_words((project or {}).get("meta", {}) if isinstance(project, dict) else {})
    progress = f"{stats['body_words']}/{target}" if target else str(stats["body_words"])
    source = str(source or "自动草稿").strip() or "自动草稿"
    return (
        f"{source} ｜圣经 {stats['bible_section_words']} ｜正文 {progress} ｜大纲 {stats['outline_words']} ｜摘要/事实 {stats['summary_facts_words']} ｜章节 {stats['chapters']} "
        f"｜人物 {stats['characters']} ｜设定 {stats['lore']} ｜伏笔 {stats['foreshadows']}"
    )


def _duplicate_values(values):
    seen = set()
    dup = []
    for value in values:
        value = str(value or "").strip()
        if not value:
            continue
        if value in seen and value not in dup:
            dup.append(value)
        seen.add(value)
    return dup


def _alias_duplicate_pairs(records, label_prefix, name_key="name"):
    records = records if isinstance(records, list) else []
    aliases = {}
    pairs = []
    seen_pairs = set()
    for index, item in enumerate(records, 1):
        if not isinstance(item, dict):
            continue
        name = str(item.get(name_key, "") or "").strip() or f"{label_prefix} {index}"
        keys = _record_alias_keys(item, name_key=name_key)
        if not keys:
            compact = _compact_text(name)
            keys = {compact} if compact else set()
        for key in keys:
            previous = aliases.get(key)
            if previous and previous != name:
                pair_key = tuple(sorted((previous, name)))
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    pairs.append((previous, name))
            else:
                aliases[key] = name
    return pairs


def _build_writing_check_text(project):
    project = project if isinstance(project, dict) else {}
    issues = []

    meta = project.get("meta", {}) if isinstance(project.get("meta"), dict) else {}
    if not str(meta.get("premise", "") or "").strip():
        issues.append("故事核心还没填写。")
    if not str(project.get("bible", "") or "").strip():
        issues.append("小说圣经还没填写，长篇后期容易跑偏。")
    target_raw = str(meta.get("target_words", "") or "").strip()
    target_words = _target_words(meta)
    if target_raw and not target_words:
        issues.append("目标字数格式无法识别；可填写 10、10万、10万字或 100000字。")

    chapters = project.get("chapters", [])
    chapters = chapters if isinstance(chapters, list) else []
    characters = project.get("characters", [])
    characters = characters if isinstance(characters, list) else []
    if not characters:
        issues.append("人物卡为空；长篇建议至少记录主角、关键配角和主要反派。")
    character_activity = _character_activity_stats(project)
    character_names = {
        str(char.get("name", "") or "").strip()
        for char in characters
        if isinstance(char, dict) and str(char.get("name", "") or "").strip()
    }
    character_name_keys = set()
    for char in characters:
        if not isinstance(char, dict):
            continue
        character_name_keys.update(_record_alias_keys(char, name_key="name"))
        name_key = _compact_text(char.get("name", ""))
        if name_key:
            character_name_keys.add(name_key)
    for index, char in enumerate(characters, 1):
        if not isinstance(char, dict):
            continue
        name = str(char.get("name", "") or "").strip() or f"人物 {index}"
        activity_count = int(character_activity.get(name, {}).get("chapters", 0) or 0)
        if _should_check_character_details(char, activity_count, len(chapters)):
            if not str(char.get("goal", "") or "").strip():
                issues.append(f"核心/高频人物「{name}」缺少人物目标。")
            if not str(char.get("voice", "") or "").strip():
                issues.append(f"核心/高频人物「{name}」缺少语言风格。")
    for name in _duplicate_values(char.get("name", "") for char in characters if isinstance(char, dict)):
        issues.append(f"人物「{name}」重复，请确认是否需要合并。")
    for previous, name in _alias_duplicate_pairs(characters, "人物", name_key="name"):
        if previous != name:
            issues.append(f"人物「{previous}」和「{name}」疑似同一人/别称，请确认是否需要合并。")
    canonical_characters = {}
    for char in characters:
        if not isinstance(char, dict):
            continue
        name = str(char.get("name", "") or "").strip()
        key = _character_merge_key(char)
        if not name or not key:
            continue
        previous = canonical_characters.get(key)
        if previous and previous != name:
            issues.append(f"人物「{previous}」和「{name}」疑似同一人，请确认是否需要合并。")
        else:
            canonical_characters[key] = name

    stats = _project_stats(project)
    long_form_mode = target_words >= 150000 or stats["body_words"] >= 50000 or stats["chapters"] >= 20
    empty_planned_chapters = []
    missing_outline_with_body = []
    writing_without_text = []
    completed_missing_summary = []
    completed_missing_key_facts = []
    for index, chap in enumerate(chapters, 1):
        if not isinstance(chap, dict):
            continue
        title = str(chap.get("title", "") or "").strip() or f"章节 {index}"
        outline = str(chap.get("outline", "") or "").strip()
        body = str(chap.get("text", "") or "").strip()
        status = str(chap.get("status", "") or "").strip()
        if not outline and not body:
            if long_form_mode:
                empty_planned_chapters.append(f"第 {index} 章「{title}」")
            else:
                issues.append(f"第 {index} 章「{title}」缺少章节提纲。")
                issues.append(f"第 {index} 章「{title}」还没有正文。")
        elif not outline and body:
            if long_form_mode:
                missing_outline_with_body.append(f"第 {index} 章「{title}」")
            else:
                issues.append(f"第 {index} 章「{title}」缺少章节提纲。")
        if not body and status in {"写作中", "已完成"}:
            writing_without_text.append(f"第 {index} 章「{title}」")
        if chap.get("status") == "已完成" and not str(chap.get("summary", "") or "").strip():
            if long_form_mode:
                completed_missing_summary.append(f"第 {index} 章「{title}」")
            else:
                issues.append(f"第 {index} 章「{title}」标记已完成，但缺少本章摘要。")
        if chap.get("status") == "已完成" and not str(chap.get("key_facts", "") or "").strip():
            if long_form_mode:
                completed_missing_key_facts.append(f"第 {index} 章「{title}」")
            else:
                issues.append(f"第 {index} 章「{title}」标记已完成，但缺少需继承的关键事实。")
        linked = chap.get("linked_characters", [])
        if isinstance(linked, list):
            for name in linked:
                name = str(name or "").strip()
                if name and name not in character_names and _compact_text(name) not in character_name_keys:
                    issues.append(f"第 {index} 章「{title}」关联人物「{name}」不在人物卡里。")
    if empty_planned_chapters:
        sample = "、".join(empty_planned_chapters[:5])
        tail = f"等 {len(empty_planned_chapters)} 章" if len(empty_planned_chapters) > 5 else ""
        issues.append(f"{sample}{tail} 还是空章节；长篇可保留占位，写到前让 AI 生成提纲即可。")
    if len(missing_outline_with_body) >= max(4, stats["chapters"] // 3):
        sample = "、".join(missing_outline_with_body[:5])
        tail = f"等 {len(missing_outline_with_body)} 章" if len(missing_outline_with_body) > 5 else ""
        issues.append(f"{sample}{tail} 有正文但缺少提纲；如需后续 AI 改写，可按需补提纲，不必逐章手动维护。")
    if writing_without_text:
        sample = "、".join(writing_without_text[:5])
        tail = f"等 {len(writing_without_text)} 章" if len(writing_without_text) > 5 else ""
        issues.append(f"{sample}{tail} 标记为写作中/已完成但没有正文。")
    if completed_missing_summary:
        sample = "、".join(completed_missing_summary[:5])
        tail = f"等 {len(completed_missing_summary)} 章" if len(completed_missing_summary) > 5 else ""
        issues.append(f"{sample}{tail} 标记已完成但缺少本章摘要；长篇可优先补关键转折章，其余章节由正文摘录兜底继承。")
    if completed_missing_key_facts:
        sample = "、".join(completed_missing_key_facts[:5])
        tail = f"等 {len(completed_missing_key_facts)} 章" if len(completed_missing_key_facts) > 5 else ""
        issues.append(f"{sample}{tail} 标记已完成但缺少需继承的关键事实；建议优先补人物关系、物品、伤势、伏笔推进等会影响后文的事实。")
    for title in _duplicate_values(chap.get("title", "") for chap in chapters if isinstance(chap, dict)):
        issues.append(f"章节标题「{title}」重复，请确认是否为误导入。")

    foreshadow_items = project.get("foreshadow_items", [])
    foreshadow_items = foreshadow_items if isinstance(foreshadow_items, list) else []
    if str(project.get("foreshadows", "") or "").strip() == "" and not foreshadow_items:
        issues.append("伏笔页为空；如果是长篇，建议记录伏笔和回收章节。")
    for index, item in enumerate(foreshadow_items, 1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip() or f"伏笔 {index}"
        status = str(item.get("status", "") or "").strip()
        if status == "已埋" and not str(item.get("payoff_chapter", "") or "").strip():
            issues.append(f"伏笔「{name}」已埋，但还没有填写回收章节。")
        if status == "已回收" and not str(item.get("setup_chapter", "") or "").strip():
            issues.append(f"伏笔「{name}」已回收，但缺少埋设章节记录。")

    lore = project.get("lore", [])
    lore = lore if isinstance(lore, list) else []
    if not lore:
        issues.append("设定库为空；长篇建议把地点、势力、物品、规则单独记录。")
    else:
        for name in _duplicate_values(item.get("name", "") for item in lore if isinstance(item, dict)):
            issues.append(f"设定「{name}」重复，请确认是否需要合并。")
        for previous, name in _alias_duplicate_pairs(lore, "设定", name_key="name"):
            if previous != name:
                issues.append(f"设定「{previous}」和「{name}」疑似同一设定/别称，请确认是否需要合并。")
    for name in _duplicate_values(item.get("name", "") for item in foreshadow_items if isinstance(item, dict)):
        issues.append(f"伏笔「{name}」重复，请确认是否需要合并。")
    for previous, name in _alias_duplicate_pairs(foreshadow_items, "伏笔", name_key="name"):
        if previous != name:
            issues.append(f"伏笔「{previous}」和「{name}」疑似同一线索/别称，请确认是否需要合并。")

    continuity_chapters = [
        chap for chap in chapters
        if isinstance(chap, dict)
        and (
            str(chap.get("text", "") or "").strip()
            or str(chap.get("outline", "") or "").strip()
            or str(chap.get("summary", "") or "").strip()
            or str(chap.get("key_facts", "") or "").strip()
        )
    ]
    continuity_total = len(continuity_chapters)
    summary_ready = sum(
        1 for chap in continuity_chapters
        if str(chap.get("summary", "") or "").strip()
        or str(chap.get("key_facts", "") or "").strip()
    )
    linked_ready = sum(
        1 for chap in continuity_chapters
        if (
            isinstance(chap.get("linked_characters", []), list)
            and any(str(x or "").strip() for x in chap.get("linked_characters", []))
        )
        or bool(_infer_linked_character_names(project, chap))
    )
    future_plan_ready = 0
    if long_form_mode:
        if not target_words:
            issues.append("建议填写目标字数；长篇项目可按 20万字 这类格式记录。")
        inheritance_gaps = []
        unlinked_chapters = []
        future_plan_ready = 0
        for index, chap in enumerate(chapters, 1):
            if not isinstance(chap, dict):
                continue
            title = str(chap.get("title", "") or "").strip() or f"章节 {index}"
            has_body = bool(str(chap.get("text", "") or "").strip())
            has_outline = bool(str(chap.get("outline", "") or "").strip())
            plan_text = "\n".join(
                str(chap.get(key, "") or "")
                for key in ("outline", "summary", "key_facts")
            )
            if index > 1 and _compact_text(plan_text):
                future_plan_ready += 1
            if has_body and not (
                str(chap.get("summary", "") or "").strip()
                or str(chap.get("key_facts", "") or "").strip()
            ):
                inheritance_gaps.append(f"第 {index} 章「{title}」")
            linked = chap.get("linked_characters", [])
            auto_linked = _normalize_name_list(
                _infer_linked_character_names(project, chap)
            )
            if (
                (has_body or has_outline)
                and (not isinstance(linked, list) or not any(str(x or "").strip() for x in linked))
                and not auto_linked
            ):
                unlinked_chapters.append(f"第 {index} 章「{title}」")
        if inheritance_gaps:
            sample = "、".join(inheritance_gaps[:5])
            tail = f"等 {len(inheritance_gaps)} 章" if len(inheritance_gaps) > 5 else ""
            issues.append(f"{sample}{tail} 缺少摘要/关键事实；应用 AI 正文后会自动补，历史章节可按需补齐。")
        if len(unlinked_chapters) >= max(4, stats["chapters"] // 3):
            sample = "、".join(unlinked_chapters[:5])
            tail = f"等 {len(unlinked_chapters)} 章" if len(unlinked_chapters) > 5 else ""
            issues.append(f"{sample}{tail} 没有关联人物；可用 AI 摘要按本章实际内容补齐，或手动填写。")
        if future_plan_ready < max(2, stats["chapters"] // 6) and stats["chapters"] >= 12:
            issues.append("后续章节规划较少；章节 AI 会尽量靠前文续写，但补几章粗提纲能明显降低越界和重复。")
        unresolved = [
            str(item.get("name", "") or f"伏笔 {index}").strip()
            for index, item in enumerate(foreshadow_items, 1)
            if isinstance(item, dict) and str(item.get("status", "") or "").strip() == "已埋"
        ]
        if len(unresolved) >= 8:
            issues.append(f"已有 {len(unresolved)} 个伏笔处于已埋状态；建议检查回收计划，避免长篇后期线索堆积。")
    if target_words and stats["body_words"] > target_words:
        issues.append(f"正文已超过目标字数 {target_words}，建议检查目标或拆分规划。")
    lines = [
        "基础统计",
        f"- 正文字数：{stats['body_words']}",
        f"- 章节数量：{stats['chapters']}",
        f"- 人物数量：{stats['characters']}",
        f"- 设定数量：{stats['lore']}",
        f"- 伏笔数量：{stats['foreshadows']}",
        f"- 摘要/事实覆盖：{summary_ready}/{continuity_total}",
        f"- 关联人物覆盖：{linked_ready}/{continuity_total}",
        f"- 后续规划覆盖：{future_plan_ready}/{max(0, stats['chapters'] - 1)}",
        "",
        "问题清单",
    ]
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- 暂未发现基础结构问题。")
    return "\n".join(lines)


def _target_words(meta):
    raw = str((meta or {}).get("target_words", "") or "").strip()
    if not raw:
        return 0
    has_wan = "万" in raw
    has_words = "字" in raw
    try:
        value = float(raw.replace("万", "").replace("字", "").replace(",", ""))
    except Exception:
        return 0
    if value <= 0:
        return 0
    if has_wan:
        return int(value * 10000)
    if has_words or value >= 1000:
        return int(value)
    return int(value * 10000)


def _target_words_label(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "万" in raw:
        return raw if raw.endswith("字") else f"{raw}字"
    if raw.endswith("字"):
        return raw
    try:
        number = float(raw.replace(",", ""))
    except Exception:
        return f"{raw}万字"
    if number >= 1000:
        return f"{raw}字"
    return f"{raw}万字"


def _draft_words_label(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = _draft_words_value(raw)
    if parsed:
        return f"{parsed}字"
    try:
        number = float(raw.replace(",", ""))
    except Exception:
        return raw
    if number <= 0:
        return ""
    if number.is_integer():
        raw = str(int(number))
    return f"{raw}字"


def _draft_words_value(value):
    raw = str(value or "").strip()
    if not raw:
        return 0
    text = (
        raw.replace(",", "")
        .replace("，", "")
        .replace("约", "")
        .replace("大约", "")
        .replace("左右", "")
        .replace("字", "")
        .strip()
    )
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return 0
    try:
        number = float(match.group(0))
    except Exception:
        return 0
    if number <= 0:
        return 0
    if "万" in text:
        number *= 10000
    elif "千" in text or re.search(r"\bk\b", text, flags=re.IGNORECASE):
        number *= 1000
    return int(number)


def _draft_words_remaining(value, current_text=""):
    target = _draft_words_value(value)
    if not target:
        return 0
    current_len = _text_len(current_text)
    if current_len <= 0:
        return target
    if current_len >= int(target * 0.99):
        return 0
    return max(0, target - current_len)


CHAPTER_TITLE_RE = re.compile(
    r"^\s*(?:[#＃]+\s*)?(第\s*[一二三四五六七八九十百千万零〇\d]+\s*[章节回卷部].*|Chapter\s+\d+.*|\d+[\.、]\s*\S.{0,40})\s*$",
    re.IGNORECASE,
)
EPISODE_TITLE_RE = re.compile(
    r"^\s*(?:[#＃]+\s*)?(?:(?:\d+|[一二三四五六七八九十百千万零〇]+)\s*[\.、]\s*)?((?:第\s*[一二三四五六七八九十百千万零〇\d]+\s*集|[一二三四五六七八九十百千万零〇]+\s*集|EP(?:ISODE)?\.?\s*\d+|Episode\s+\d+|E\d{1,3})(?:\s*[:：\-—、.·]\s*.*|.*)?)\s*$",
    re.IGNORECASE,
)
SCENE_TITLE_RE = re.compile(
    r"^\s*(?:[#＃]+\s*)?((?:第\s*[一二三四五六七八九十百千万零〇\d]+\s*场|场景\s*[一二三四五六七八九十百千万零〇\d]+|Scene\s+\d+|S\d{1,3}|INT\.|EXT\.|内景|外景)(?:\s*[:：\-—、.·]\s*.*|.*)?)\s*$",
    re.IGNORECASE,
)
FRAMEWORK_IMPORT_TYPE = "小说框架 / 大纲"
IMPORT_TYPE_OPTIONS = [FRAMEWORK_IMPORT_TYPE, "小说", "短剧 / 分集剧本", "电影 / 长剧剧本", "自由文本"]
UNIT_TYPE_LABELS = {
    "chapter": "章",
    "episode": "集",
    "scene": "场",
    "text": "正文",
}


def _build_manuscript_text(project):
    project = project if isinstance(project, dict) else {}
    meta = project.get("meta", {}) if isinstance(project.get("meta"), dict) else {}
    parts = [str(meta.get("title") or "未命名小说").strip(), ""]
    chapters = project.get("chapters", [])
    for index, chap in enumerate(chapters if isinstance(chapters, list) else [], 1):
        if not isinstance(chap, dict):
            continue
        title = chap.get("title") or f"第 {index} 章"
        text = str(chap.get("text", "") or "").strip()
        if not text:
            continue
        parts.append(str(title).strip())
        parts.append("")
        parts.append(text)
        parts.append("")
    return "\n".join(parts).strip()


_PROJECT_SEARCH_FIELD_LABELS = {
    "title": "书名",
    "genre": "类型",
    "style": "风格",
    "pov": "视角",
    "target_words": "目标字数",
    "status": "状态",
    "premise": "核心设定",
    "bible": "小说圣经",
    "world_rules": "世界观 / 规则",
    "timeline": "时间线",
    "foreshadows": "伏笔汇总",
    "summary": "摘要 / 日志",
    "style_reference": "正文风格参考",
    "draft_note": "全局备注",
    "name": "名称",
    "role": "身份",
    "goal": "目标",
    "secret": "秘密",
    "voice": "语言",
    "notes": "备注",
    "type": "类型",
    "description": "说明",
    "code": "编号",
    "setup_chapter": "埋设章节",
    "payoff_chapter": "回收章节",
    "unit_type": "章节类型",
    "outline": "提纲",
    "text": "正文",
    "key_facts": "关键事实",
    "draft_words": "扩写字数",
    "linked_characters": "关联人物",
    "source_label": "来源",
    "_source_label": "来源",
}

_PROJECT_SEARCH_SKIP_KEYS = {
    "id",
    "updated_at",
    "analysis_state",
    "analysis_hash",
    "analysis_hash_version",
    "analysis_analyzed_at",
    "analysis_baseline",
    "analysis_linked_hash",
    "analysis_status",
    "analysis_status_hash",
    "analysis_status_version",
    "adaptation_source_hash",
    "adapted_at",
    "imported_chapter_plan_reference",
    "imported_framework_source",
    "chapter_plan_generation_state",
    "creative_intent_contract",
    "series_continuation",
}


def _project_search_field_label(key, field_labels=None):
    key = str(key or "").strip()
    if not key:
        return "内容"
    if isinstance(field_labels, dict) and key in field_labels:
        return field_labels[key]
    return _PROJECT_SEARCH_FIELD_LABELS.get(key, key.lstrip("_") or key)


def _iter_project_search_texts(value, path="", field_labels=None):
    if isinstance(value, dict):
        for key, child in value.items():
            key = str(key or "").strip()
            if not key or key in _PROJECT_SEARCH_SKIP_KEYS or key.startswith("__"):
                continue
            label = _project_search_field_label(key, field_labels=field_labels)
            child_path = f"{path} / {label}" if path else label
            yield from _iter_project_search_texts(child, child_path, field_labels=field_labels)
        return
    if isinstance(value, list):
        scalar_values = [
            str(item).strip()
            for item in value
            if not isinstance(item, (dict, list)) and str(item or "").strip()
        ]
        if scalar_values:
            yield path or "内容", "、".join(scalar_values)
        for index, item in enumerate(value, 1):
            if isinstance(item, (dict, list)):
                child_path = f"{path} / {index}" if path else str(index)
                yield from _iter_project_search_texts(item, child_path, field_labels=field_labels)
        return
    text = str(value or "").strip()
    if text:
        yield path or "内容", text


def _append_project_search_sources(sources, group_prefix, title, record, field_labels=None):
    for path, text in _iter_project_search_texts(record, field_labels=field_labels):
        leaf = str(path or "内容").split(" / ")[-1] or "内容"
        sources.append((f"{group_prefix} / {leaf}", title, text))


def _project_search_sources(project):
    project = project if isinstance(project, dict) else {}
    sources = []
    meta = project.get("meta", {}) if isinstance(project.get("meta"), dict) else {}
    _append_project_search_sources(sources, "项目", "基础信息", meta, field_labels={"title": "书名"})

    for key in ("bible", "world_rules", "foreshadows", "draft_note"):
        text = str(project.get(key, "") or "").strip()
        if text:
            label = _project_search_field_label(key)
            sources.append((label, label, text))

    for index, char in enumerate(project.get("characters", []) if isinstance(project.get("characters"), list) else [], 1):
        if not isinstance(char, dict):
            continue
        name = str(char.get("name") or f"人物 {index}").strip()
        _append_project_search_sources(sources, "人物卡", name, char, field_labels={"name": "姓名"})

    for index, lore in enumerate(project.get("lore", []) if isinstance(project.get("lore"), list) else [], 1):
        if not isinstance(lore, dict):
            continue
        name = str(lore.get("name") or f"设定 {index}").strip()
        _append_project_search_sources(sources, "设定库", name, lore)

    for index, item in enumerate(project.get("foreshadow_items", []) if isinstance(project.get("foreshadow_items"), list) else [], 1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or f"伏笔 {index}").strip()
        _append_project_search_sources(sources, "伏笔", name, item)

    for index, chap in enumerate(project.get("chapters", []) if isinstance(project.get("chapters"), list) else [], 1):
        if not isinstance(chap, dict):
            continue
        name = str(chap.get("title") or f"章节 {index}").strip()
        _append_project_search_sources(sources, "章节", name, chap, field_labels={"title": "标题", "summary": "摘要"})

    candidates = project.get("import_candidates", {})
    if isinstance(candidates, dict):
        candidate_groups = (
            ("characters", "候选人物", "候选人物"),
            ("lore", "候选设定", "候选设定"),
            ("foreshadows", "候选伏笔", "候选伏笔"),
        )
        for key, group_prefix, fallback_title in candidate_groups:
            items = candidates.get(key, [])
            for index, item in enumerate(items if isinstance(items, list) else [], 1):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("name") or f"{fallback_title} {index}").strip()
                _append_project_search_sources(sources, group_prefix, title, item)
        materials = candidates.get("project_materials", {})
        if isinstance(materials, dict):
            for key, value in materials.items():
                if key not in {"bible", "world_rules"}:
                    continue
                text = str(value or "").strip()
                if text:
                    label = _project_search_field_label(key)
                    sources.append(("候选资料", label, text))

    handled = {
        "meta",
        "bible",
        "world_rules",
        "timeline",
        "foreshadows",
        "summary",
        "style_reference",
        "draft_note",
        "characters",
        "lore",
        "foreshadow_items",
        "chapters",
        "import_candidates",
    }
    for key, value in project.items():
        if key in handled or key in _PROJECT_SEARCH_SKIP_KEYS or str(key).startswith("__"):
            continue
        label = _project_search_field_label(key)
        for path, text in _iter_project_search_texts(value, label):
            leaf = str(path or label).split(" / ")[-1] or label
            sources.append((f"项目 / {leaf}", label, text))
    return sources


def _search_excerpt_at_position(text, keyword, pos, radius=42):
    text = str(text or "").replace("\r", "").replace("\n", " ").strip()
    if not text:
        return ""
    pos = max(0, min(int(pos or 0), len(text)))
    start = max(0, pos - radius)
    end = min(len(text), pos + len(str(keyword or "")) + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


def _search_keyword_positions(text, keyword):
    text = str(text or "")
    key = str(keyword or "")
    if not text or not key:
        return []
    lower = text.lower()
    key_lower = key.lower()
    positions = []
    start = 0
    while True:
        pos = lower.find(key_lower, start)
        if pos < 0:
            break
        positions.append(pos)
        start = pos + max(1, len(key_lower))
    return positions


def _select_search_positions(positions, max_excerpts=3):
    positions = list(positions or [])
    max_excerpts = max(1, int(max_excerpts or 1))
    if len(positions) <= max_excerpts:
        return positions
    if max_excerpts == 1:
        return [positions[0]]
    if max_excerpts == 2:
        return [positions[0], positions[-1]]
    selected = [positions[0], positions[len(positions) // 2], positions[-1]]
    for pos in positions:
        if len(selected) >= max_excerpts:
            break
        if pos not in selected:
            selected.append(pos)
    return sorted(set(selected))


def _search_excerpts(text, keyword, radius=42, max_excerpts=3):
    clean = str(text or "").replace("\r", "").replace("\n", " ").strip()
    if not clean:
        return [], 0
    positions = _search_keyword_positions(clean, keyword)
    if not positions:
        return [clean[: radius * 2].strip()], 0
    excerpts = []
    seen = set()
    for pos in _select_search_positions(positions, max_excerpts=max_excerpts):
        excerpt = _search_excerpt_at_position(clean, keyword, pos, radius=radius)
        key = _compact_text(excerpt)
        if not key or key in seen:
            continue
        seen.add(key)
        excerpts.append(excerpt)
    return excerpts, len(positions)


def _search_excerpt(text, keyword, radius=42):
    excerpts, _count = _search_excerpts(text, keyword, radius=radius, max_excerpts=1)
    return excerpts[0] if excerpts else ""


def _build_search_result_text(project, keyword):
    keyword = str(keyword or "").strip()
    if not keyword:
        return "请输入关键词。"
    results = []
    for group, title, text in _project_search_sources(project):
        text = str(text or "")
        if keyword.lower() not in text.lower():
            continue
        excerpts, match_count = _search_excerpts(text, keyword)
        results.append((group, title, excerpts, match_count))
    if not results:
        return f"没有找到：{keyword}"
    group_counts = {}
    for group, _title, _excerpts, _match_count in results:
        group_counts[group] = group_counts.get(group, 0) + 1
    count_text = " ｜ ".join(f"{group} {count}" for group, count in group_counts.items())
    lines = [f"找到 {len(results)} 条结果：{keyword}", count_text, ""]
    for index, (group, title, excerpts, match_count) in enumerate(results, 1):
        suffix = f"（共 {match_count} 处）" if match_count > 1 else ""
        lines.append(f"{index}. [{group}] {title}{suffix}")
        for excerpt in excerpts:
            if excerpt:
                prefix = "   - " if len(excerpts) > 1 else "   "
                lines.append(f"{prefix}{excerpt}")
        lines.append("")
    return "\n".join(lines).strip()


def _chapter_title_regex(import_type):
    if import_type == "短剧 / 分集剧本":
        return EPISODE_TITLE_RE, "episode", "第 {n} 集"
    if import_type == "电影 / 长剧剧本":
        return SCENE_TITLE_RE, "scene", "第 {n} 场"
    if import_type == "自由文本":
        return None, "text", "导入正文"
    return CHAPTER_TITLE_RE, "chapter", "章节 {n}"


def _split_chapters_from_text(text, import_type="小说"):
    title_re, unit_type, fallback_title = _chapter_title_regex(import_type)
    if title_re is None:
        body = str(text or "").strip()
        chap = {
            "id": uuid.uuid4().hex,
            "title": fallback_title,
            "unit_type": unit_type,
            "status": "",
            "outline": "",
            "text": body,
            "summary": "",
            "key_facts": "",
            "linked_characters": [],
            "analysis_hash": "",
            "analysis_hash_version": "",
            "analysis_analyzed_at": "",
            "analysis_baseline": "",
            "analysis_linked_hash": "",
            "analysis_status": CHAPTER_ANALYSIS_STATUS_UNWRITTEN,
            "analysis_status_hash": "",
            "analysis_status_version": CHAPTER_ANALYSIS_STATUS_VERSION,
        }
        chap["status"] = _infer_chapter_status(chap, preserve_manual=False)
        return [chap] if body else []

    lines = [line.strip() for line in str(text or "").splitlines()]
    chapters = []
    current_title = ""
    current_lines = []

    def flush():
        nonlocal current_title, current_lines
        body = "\n".join(current_lines).strip()
        if current_title or body:
            chap = {
                "id": uuid.uuid4().hex,
                "title": current_title or fallback_title.format(n=len(chapters) + 1),
                "unit_type": unit_type,
                "status": "",
                "outline": "",
                "text": body,
                "summary": "",
                "key_facts": "",
                "linked_characters": [],
                "analysis_hash": "",
                "analysis_hash_version": "",
                "analysis_analyzed_at": "",
                "analysis_baseline": "",
                "analysis_linked_hash": "",
                "analysis_status": CHAPTER_ANALYSIS_STATUS_UNWRITTEN,
                "analysis_status_hash": "",
                "analysis_status_version": CHAPTER_ANALYSIS_STATUS_VERSION,
            }
            chap["status"] = _infer_chapter_status(chap, preserve_manual=False)
            chapters.append(chap)
        current_title = ""
        current_lines = []

    for line in lines:
        if not line:
            continue
        title_match = title_re.match(line)
        if title_match:
            if current_title:
                flush()
            current_title = title_match.group(1).strip() if title_match.groups() else line
            continue
        current_lines.append(line)
    flush()
    if not chapters and str(text or "").strip():
        chap = {
            "id": uuid.uuid4().hex,
            "title": "导入正文",
            "unit_type": "text",
            "status": "",
            "outline": "",
            "text": str(text).strip(),
            "summary": "",
            "key_facts": "",
            "linked_characters": [],
            "analysis_hash": "",
            "analysis_hash_version": "",
            "analysis_analyzed_at": "",
            "analysis_baseline": "",
            "analysis_linked_hash": "",
            "analysis_status": CHAPTER_ANALYSIS_STATUS_UNWRITTEN,
            "analysis_status_hash": "",
            "analysis_status_version": CHAPTER_ANALYSIS_STATUS_VERSION,
        }
        chap["status"] = _infer_chapter_status(chap, preserve_manual=False)
        chapters.append(chap)
    return chapters


def _split_export_text_into_chunks(text, max_chars):
    text = str(text or "").strip()
    max_chars = max(1, int(max_chars or 1))
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current = ""
    pieces = re.split(r"([。！？!?；;：:]\s*)", text)
    for piece in pieces:
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
        chunk = chunk.strip()
        if not chunk:
            continue
        while len(chunk) > max_chars:
            final.append(chunk[:max_chars].strip())
            chunk = chunk[max_chars:].strip()
        if chunk:
            final.append(chunk)
    return final or [text]


def _split_paragraph_to_units(paragraph, unit_limit):
    paragraph = str(paragraph or "").strip()
    unit_limit = max(1, int(unit_limit or 1))
    if not paragraph:
        return []
    if len(paragraph) <= unit_limit:
        return [paragraph]
    units = []
    current = ""
    sentence_parts = re.split(r"([。！？!?；;：:，,]\s*)", paragraph)
    for piece in sentence_parts:
        if not piece:
            continue
        candidate = current + piece
        if current and len(candidate) > unit_limit:
            # Keep sentence/clause punctuation with the text before it.  If
            # it were carried into the next unit, an exported chapter could
            # start with a dangling "。"/"！" even without content loss.
            if re.fullmatch(r"[。！？!?；;：:，,]\s*", piece):
                units.append(candidate.strip())
                current = ""
            else:
                units.append(current.strip())
                current = piece
        else:
            current = candidate
    if current.strip():
        units.append(current.strip())
    refined = []
    for unit in units:
        unit = unit.strip()
        if not unit:
            continue
        # Keep an overlong sentence/semantic unit intact.  The limit is only
        # a grouping hint; slicing here makes the next exported chapter start
        # in the middle of a sentence and moves its punctuation to the next
        # chapter.
        refined.append(unit)
    return refined or [paragraph]


def _split_manuscript_into_target_chapters(project, target_words):
    project = project if isinstance(project, dict) else {}
    target_words = _draft_words_value(target_words)
    if target_words <= 0:
        return []
    chapters = project.get("chapters", [])
    chapters = chapters if isinstance(chapters, list) else []
    if not chapters:
        return []

    target_low = max(1, int(target_words * 0.9))
    target_high = max(target_low, int(target_words * 1.1))
    unit_limit = max(120, int(target_words * 0.2))
    output = []
    current_units = []
    current_chars = 0

    def flush():
        nonlocal current_units, current_chars
        body = "\n\n".join(current_units).strip()
        if body:
            output.append({
                "id": uuid.uuid4().hex,
                "title": f"第 {len(output) + 1} 章",
                "unit_type": "chapter",
                "status": "写作中",
                "outline": "",
                "draft_words": str(target_words),
                "text": body,
                "summary": "",
                "key_facts": "",
                "linked_characters": [],
                "analysis_hash": "",
                "analysis_hash_version": "",
                "analysis_analyzed_at": "",
                "analysis_baseline": "",
                "analysis_linked_hash": "",
                "analysis_status": CHAPTER_ANALYSIS_STATUS_UNWRITTEN,
                "analysis_status_hash": "",
                "analysis_status_version": CHAPTER_ANALYSIS_STATUS_VERSION,
            })
        current_units = []
        current_chars = 0

    def append_unit(unit):
        nonlocal current_units, current_chars
        unit = str(unit or "").strip()
        if not unit:
            return
        unit_chars = _text_len(unit)
        if not current_units:
            current_units = [unit]
            current_chars = unit_chars
            return
        proposed = current_chars + unit_chars
        if proposed <= target_high:
            current_units.append(unit)
            current_chars = proposed
            return
        if current_chars < target_low:
            current_units.append(unit)
            current_chars = proposed
            return
        flush()
        current_units = [unit]
        current_chars = unit_chars

    for chap in chapters:
        if not isinstance(chap, dict):
            continue
        body = str(chap.get("text", "") or "").strip()
        if not body:
            continue
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", body) if part.strip()]
        if not paragraphs:
            paragraphs = [body]
        for paragraph in paragraphs:
            for unit in _split_paragraph_to_units(paragraph, unit_limit):
                append_unit(unit)

    if current_units:
        flush()
    if len(output) >= 2:
        last_len = _text_len(output[-1].get("text", ""))
        prev_len = _text_len(output[-2].get("text", ""))
        if last_len < target_low and prev_len + last_len <= target_high:
            output[-2]["text"] = f"{output[-2].get('text', '').rstrip()}\n\n{output[-1].get('text', '').lstrip()}".strip()
            output.pop()
    return output


def _local_split_chapter_title(text, middle_chars=500, min_chars=5, max_chars=20):
    """Use a short sentence from the middle of the text as a fast export-only title."""
    text = str(text or "").strip()
    if not text:
        return ""
    try:
        middle_chars = max(1, int(middle_chars or 500))
        min_chars = max(1, int(min_chars or 5))
        max_chars = max(min_chars, int(max_chars or 20))
    except (TypeError, ValueError):
        middle_chars, min_chars, max_chars = 500, 5, 20

    trim_chars = "#\\\"'“”‘’《》【】「」『』（）()[]，,。；;：:、!?！？"

    source_chapter_re = re.compile(
        r"^\s*第\s*[一二两三四五六七八九十百千万零〇\d]+\s*章\s*[：:、.。\-—]?\s*"
    )

    def clean(value):
        source_header = bool(source_chapter_re.match(str(value or "")))
        value = source_chapter_re.sub("", str(value or ""), count=1)
        value = re.sub(r"\s+", "", str(value or "")).strip(trim_chars)
        if "：" in value:
            prefix, remainder = value.split("：", 1)
            if 1 <= len(prefix) <= 12:
                value = remainder
        elif ":" in value:
            prefix, remainder = value.split(":", 1)
            if 1 <= len(prefix) <= 12:
                value = remainder
        value = value.strip(trim_chars)
        if source_header:
            # A source manuscript often has: "第38章 发怒，‘……’".
            # Keep the original short heading instead of treating the
            # following dialogue as one long title.
            heading = re.split(r"[，,：:；;。！？!?]", value, maxsplit=1)[0]
            heading = heading.strip(trim_chars)
            if 2 <= len(heading) <= max_chars:
                return heading
        return value

    window_chars = min(len(text), middle_chars)
    middle_start = max(0, (len(text) - window_chars) // 2)
    middle_text = text[middle_start:middle_start + window_chars]
    candidates = []
    source_headings = []
    for sentence in re.split(r"[。！？!?；;\n]+", middle_text):
        if source_chapter_re.match(sentence):
            heading = clean(sentence)
            if 2 <= len(heading) <= max_chars:
                source_headings.append(heading)
        sentence = clean(sentence)
        if sentence:
            candidates.append(sentence)

    for candidate in candidates:
        if min_chars <= len(candidate) <= max_chars:
            return candidate
        if len(candidate) > max_chars:
            for fragment in re.split(r"[，,：:；;、\"“”‘’「」『』]+", candidate):
                fragment = clean(fragment)
                if min_chars <= len(fragment) <= max_chars:
                    return fragment
    if source_headings:
        return source_headings[0]
    if candidates:
        return clean(candidates[0][:max_chars])
    return clean(middle_text[:max_chars])


def _chapter_analysis_hash_text(chap, include_linked=True):
    chap = chap if isinstance(chap, dict) else {}
    parts = [
        str(chap.get(key, "") or "").strip()
        for key in ("title", "outline", "text", "summary", "key_facts")
    ]
    if include_linked:
        linked = _normalize_name_list(chap.get("linked_characters", []))
        if linked:
            parts.append("关联人物：" + "、".join(linked))
    return "\n".join(parts)


def _chapter_has_analysis_body(chap):
    return bool(str((chap if isinstance(chap, dict) else {}).get("text", "") or "").strip())


def _chapter_has_occurred_content(chap):
    chap = chap if isinstance(chap, dict) else {}
    return any(str(chap.get(key, "") or "").strip() for key in ("text", "summary", "key_facts"))


def _chapter_analysis_hash(chap):
    text = _chapter_analysis_hash_text(chap, include_linked=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest() if text.strip() else ""


def _chapter_analysis_legacy_hash(chap):
    text = _chapter_analysis_hash_text(chap, include_linked=False)
    return hashlib.sha1(text.encode("utf-8")).hexdigest() if text.strip() else ""


def _chapter_analysis_content_text(chap):
    return _chapter_analysis_hash_text(chap, include_linked=False).strip()


def _chapter_analysis_linked_hash(chap):
    linked = "、".join(_normalize_name_list((chap if isinstance(chap, dict) else {}).get("linked_characters", [])))
    return hashlib.sha1(linked.encode("utf-8")).hexdigest() if linked else ""


def _chapter_analysis_has_saved_current_version(chap):
    chap = chap if isinstance(chap, dict) else {}
    return (
        bool(str(chap.get("analysis_hash", "") or "").strip())
        and str(chap.get("analysis_hash_version", "") or "").strip() == CHAPTER_ANALYSIS_HASH_VERSION
    )


def _chapter_analysis_status_cache_hash(chap):
    chap = chap if isinstance(chap, dict) else {}
    current = _chapter_analysis_hash(chap)
    if not current:
        return ""
    saved = str(chap.get("analysis_hash", "") or "").strip()
    saved_version = str(chap.get("analysis_hash_version", "") or "").strip()
    baseline = str(chap.get("analysis_baseline", "") or "").strip()
    baseline_hash = hashlib.sha1(baseline.encode("utf-8")).hexdigest() if baseline else ""
    saved_linked = str(chap.get("analysis_linked_hash", "") or "").strip()
    linked = _chapter_analysis_linked_hash(chap)
    return hashlib.sha1(
        f"{current}\n{saved}\n{saved_version}\n{baseline_hash}\n{saved_linked}\n{linked}".encode("utf-8")
    ).hexdigest()


def _chapter_analysis_diff_ratio(old_text, new_text, allow_similarity=True):
    old_text = str(old_text or "").strip()
    new_text = str(new_text or "").strip()
    if old_text == new_text:
        return 0.0
    length_delta_ratio = abs(len(new_text) - len(old_text)) / max(len(old_text), len(new_text), 1)
    if length_delta_ratio > CHAPTER_ANALYSIS_SMALL_CHANGE_RATIO:
        return length_delta_ratio
    prefix = 0
    shortest = min(len(old_text), len(new_text))
    while prefix < shortest and old_text[prefix] == new_text[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < shortest - prefix
        and old_text[len(old_text) - 1 - suffix] == new_text[len(new_text) - 1 - suffix]
    ):
        suffix += 1
    changed_old = len(old_text) - prefix - suffix
    changed_new = len(new_text) - prefix - suffix
    local_ratio = max(changed_old, changed_new) / max(len(old_text), len(new_text), 1)
    if local_ratio <= CHAPTER_ANALYSIS_SMALL_CHANGE_RATIO:
        return max(length_delta_ratio, local_ratio)
    if (
        allow_similarity
        and local_ratio <= CHAPTER_ANALYSIS_QUICK_SIMILARITY_LOCAL_RATIO_LIMIT
    ):
        similarity = SequenceMatcher(None, old_text, new_text, autojunk=True).quick_ratio()
        return max(length_delta_ratio, 1.0 - similarity)
    return max(length_delta_ratio, local_ratio)


def _chapter_analysis_small_change_ratio(chap, allow_similarity=True):
    chap = chap if isinstance(chap, dict) else {}
    baseline = str(chap.get("analysis_baseline", "") or "").strip()
    if not baseline:
        return None
    current_text = _chapter_analysis_content_text(chap)
    if not current_text:
        return None
    return _chapter_analysis_diff_ratio(baseline, current_text, allow_similarity=allow_similarity)


def _chapter_analysis_is_small_change(chap, allow_similarity=True):
    chap = chap if isinstance(chap, dict) else {}
    if not _chapter_has_analysis_body(chap):
        return False
    current = _chapter_analysis_hash(chap)
    if not current or not _chapter_analysis_has_saved_current_version(chap):
        return False
    if current == str(chap.get("analysis_hash", "") or "").strip():
        return False
    saved_linked_hash = str(chap.get("analysis_linked_hash", "") or "").strip()
    if "analysis_linked_hash" in chap and saved_linked_hash != _chapter_analysis_linked_hash(chap):
        return False
    ratio = _chapter_analysis_small_change_ratio(chap, allow_similarity=allow_similarity)
    return ratio is not None and ratio <= CHAPTER_ANALYSIS_SMALL_CHANGE_RATIO


def _chapter_needs_analysis(chap, allow_similarity=True):
    if not _chapter_has_analysis_body(chap):
        return False
    current = _chapter_analysis_hash(chap)
    if not current:
        return False
    chap = chap if isinstance(chap, dict) else {}
    saved = str(chap.get("analysis_hash", "") or "").strip()
    if current == saved:
        return False
    if (
        str(chap.get("analysis_hash_version", "") or "").strip() != CHAPTER_ANALYSIS_HASH_VERSION
        and saved
        and saved == _chapter_analysis_legacy_hash(chap)
    ):
        return False
    if _chapter_analysis_is_small_change(chap, allow_similarity=allow_similarity):
        return False
    return True


def _chapter_analysis_is_current(chap):
    if not _chapter_has_analysis_body(chap):
        return False
    current = _chapter_analysis_hash(chap)
    if not current:
        return False
    chap = chap if isinstance(chap, dict) else {}
    return (
        current == str(chap.get("analysis_hash", "") or "").strip()
        and str(chap.get("analysis_hash_version", "") or "").strip() == CHAPTER_ANALYSIS_HASH_VERSION
    )


def _compute_chapter_analysis_status(chap, allow_similarity=True):
    if not _chapter_has_analysis_body(chap):
        return CHAPTER_ANALYSIS_STATUS_UNWRITTEN
    current = _chapter_analysis_hash(chap)
    if not current:
        return CHAPTER_ANALYSIS_STATUS_UNWRITTEN
    chap = chap if isinstance(chap, dict) else {}
    saved = str(chap.get("analysis_hash", "") or "").strip()
    saved_version = str(chap.get("analysis_hash_version", "") or "").strip()
    if current == saved:
        return CHAPTER_ANALYSIS_STATUS_CURRENT
    if saved_version != CHAPTER_ANALYSIS_HASH_VERSION and saved and saved == _chapter_analysis_legacy_hash(chap):
        return CHAPTER_ANALYSIS_STATUS_CURRENT
    if not _chapter_analysis_has_saved_current_version(chap):
        return CHAPTER_ANALYSIS_STATUS_PENDING
    saved_linked_hash = str(chap.get("analysis_linked_hash", "") or "").strip()
    if "analysis_linked_hash" in chap and saved_linked_hash != _chapter_analysis_linked_hash(chap):
        return CHAPTER_ANALYSIS_STATUS_PENDING
    ratio = _chapter_analysis_small_change_ratio(chap, allow_similarity=allow_similarity)
    if ratio is not None and ratio <= CHAPTER_ANALYSIS_SMALL_CHANGE_RATIO:
        return CHAPTER_ANALYSIS_STATUS_SMALL_CHANGE
    return CHAPTER_ANALYSIS_STATUS_PENDING


def _update_chapter_analysis_status_cache(chap, allow_similarity=True):
    if not isinstance(chap, dict):
        return CHAPTER_ANALYSIS_STATUS_UNWRITTEN
    status = _compute_chapter_analysis_status(chap, allow_similarity=allow_similarity)
    chap["analysis_status"] = status
    chap["analysis_status_hash"] = _chapter_analysis_status_cache_hash(chap)
    chap["analysis_status_version"] = CHAPTER_ANALYSIS_STATUS_VERSION
    return status


def _chapter_analysis_status(chap):
    if not isinstance(chap, dict):
        return CHAPTER_ANALYSIS_STATUS_UNWRITTEN
    cache_hash = _chapter_analysis_status_cache_hash(chap)
    status = str(chap.get("analysis_status", "") or "").strip()
    if (
        status in CHAPTER_ANALYSIS_STATUS_LABELS
        and str(chap.get("analysis_status_version", "") or "").strip() == CHAPTER_ANALYSIS_STATUS_VERSION
        and str(chap.get("analysis_status_hash", "") or "").strip() == cache_hash
    ):
        return status
    return _update_chapter_analysis_status_cache(chap)


def _mark_chapters_analyzed(chapters, chapter_ids):
    ids = {str(x) for x in (chapter_ids or []) if str(x)}
    count = 0
    for chap in chapters if isinstance(chapters, list) else []:
        if not isinstance(chap, dict):
            continue
        if str(chap.get("id", "") or "") not in ids:
            continue
        if not _chapter_has_analysis_body(chap):
            continue
        current = _chapter_analysis_hash(chap)
        if not current:
            continue
        chap["analysis_hash"] = current
        chap["analysis_hash_version"] = CHAPTER_ANALYSIS_HASH_VERSION
        chap["analysis_analyzed_at"] = now_str()
        chap["analysis_baseline"] = _chapter_analysis_content_text(chap)
        chap["analysis_linked_hash"] = _chapter_analysis_linked_hash(chap)
        _update_chapter_analysis_status_cache(chap)
        count += 1
    return count


def _chapter_dedupe_key(chap):
    if not isinstance(chap, dict):
        return None
    title = str(chap.get("title", "") or "").strip()
    outline = str(chap.get("outline", "") or "").strip()
    text = str(chap.get("text", "") or "").strip()
    summary = str(chap.get("summary", "") or "").strip()
    if not title or not (outline or text or summary):
        return None

    def compact(value):
        return re.sub(r"\s+", "", str(value or ""))

    return (
        compact(title),
        compact(outline),
        compact(text),
        compact(summary),
    )


def _dedupe_chapters(chapters):
    seen = set()
    out = []
    removed = 0
    for chap in chapters if isinstance(chapters, list) else []:
        key = _chapter_dedupe_key(chap)
        if key and key in seen:
            removed += 1
            continue
        if key:
            seen.add(key)
        out.append(chap)
    return out, removed


def _chapter_list_text(index, chap):
    chap = chap if isinstance(chap, dict) else {}
    title = chap.get("title") or f"章节 {index + 1}"
    status = chap.get("status") or "大纲"
    words = _body_display_len(chap.get("text", ""))
    unit = UNIT_TYPE_LABELS.get(str(chap.get("unit_type", "chapter") or "chapter"), "章")
    analysis_status = CHAPTER_ANALYSIS_STATUS_LABELS.get(_chapter_analysis_status(chap), "未写正文")
    parts = [f"{index + 1}. {unit}｜{title}", status, f"{words}字", analysis_status]
    return "  ·  ".join(parts)


def _character_list_text(index, char):
    char = char if isinstance(char, dict) else {}
    name = char.get("name") or f"人物 {index + 1}"
    role = str(char.get("role", "") or "").strip().replace("\r", " ").replace("\n", " ")
    return f"{name}  ·  {role}" if role else str(name)


def _lore_list_text(index, lore):
    lore = lore if isinstance(lore, dict) else {}
    name = lore.get("name") or f"设定 {index + 1}"
    typ = str(lore.get("type", "") or "").strip()
    return f"{name}  ·  {typ}" if typ else str(name)


def _foreshadow_list_text(index, item):
    item = item if isinstance(item, dict) else {}
    name = item.get("name") or f"伏笔 {index + 1}"
    code = _normalize_foreshadow_code(item.get("code", "")) or f"F{index + 1:04d}"
    status = str(item.get("status", "") or "").strip()
    setup = str(item.get("setup_chapter", "") or "").strip()
    payoff = str(item.get("payoff_chapter", "") or "").strip()
    tail = " -> ".join(x for x in (setup, payoff) if x)
    return "  ·  ".join(str(x) for x in (code, name, status, tail) if str(x).strip())


def _chapter_tooltip(chap):
    chap = chap if isinstance(chap, dict) else {}
    parts = []
    outline = str(chap.get("outline", "") or "").strip()
    summary = str(chap.get("summary", "") or "").strip()
    key_facts = str(chap.get("key_facts", "") or "").strip()
    draft_words = _draft_words_label(chap.get("draft_words", ""))
    linked = chap.get("linked_characters", [])
    if draft_words:
        parts.append("本章扩写字数：" + draft_words)
    if isinstance(linked, list) and linked:
        parts.append("关联人物：" + "、".join(str(x) for x in linked if str(x).strip()))
    if outline:
        parts.append("提纲：" + outline[:160])
    if summary:
        parts.append("摘要：" + summary[:160])
    if key_facts:
        parts.append("关键事实：" + key_facts[:160])
    return "\n\n".join(parts)


_STATIC_FORESHADOW_OUTLINE_LABELS = (
    "伏笔任务",
    "伏笔动作",
    "本章伏笔动作",
    "相关伏笔",
    "本章相关伏笔",
)


def _strip_static_foreshadow_outline_fields(value):
    text = str(value or "").strip()
    if not text:
        return ""
    lines = []
    skip_list = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        compact = re.sub(r"\s+", "", stripped)
        is_static_label = any(
            compact.startswith(f"{label}：") or compact.startswith(f"{label}:")
            for label in _STATIC_FORESHADOW_OUTLINE_LABELS
        )
        if is_static_label:
            tail = re.split(r"[:：]", stripped, maxsplit=1)[1] if re.search(r"[:：]", stripped) else ""
            skip_list = not tail.strip()
            continue
        if skip_list:
            if not stripped:
                skip_list = False
                continue
            if stripped.startswith(("-", "•", "*", "·")) or re.match(r"^\d+[.)、．]\s*", stripped):
                continue
            skip_list = False
        lines.append(raw_line)
    return "\n".join(lines).strip()


_VOLUME_HANDOFF_OUTLINE_DROP_LABELS = (
    "所属阶段",
    "原框架阶段",
    "阶段",
    "本章功能",
    "冲突强度",
    "铺垫比例",
    "人物任务",
    "主线任务",
    "本章主导线",
    "主导线",
    "本章涉及设定",
    "相关设定",
    "设定",
    "本章目标",
    "当章目标",
    "本章任务",
    "核心事件",
    "关键事件",
    "剧情节点",
    "故事节点",
    "事件节点",
    "主要事件",
    "发展方向",
    "情绪目标",
    "关系推进",
    "人物关系",
    "结尾悬念",
    "结尾钩子",
    "悬念",
    "禁止/边界",
    "禁止",
    "边界",
)


def _strip_volume_handoff_outline_metadata(value):
    """Keep chapter-story prose while dropping planning-only outline labels."""
    text = str(value or "").strip()
    if not text:
        return ""
    lines = []
    skip_list = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if not skip_list:
                lines.append("")
            continue
        compact = re.sub(r"\s+", "", stripped)
        label = next(
            (
                candidate
                for candidate in _VOLUME_HANDOFF_OUTLINE_DROP_LABELS
                if compact.startswith(candidate + "：")
                or compact.startswith(candidate + ":")
                or compact == candidate
            ),
            "",
        )
        if label:
            separator_match = re.search(r"[:：]", stripped)
            tail = stripped[separator_match.end():].strip() if separator_match else ""
            # A label carrying a short story sentence can still contribute that
            # sentence; a list-valued planning field is discarded as a whole.
            if tail and label not in {
                "所属阶段", "原框架阶段", "阶段", "冲突强度", "铺垫比例",
                "本章功能", "本章主导线", "主导线", "本章涉及设定", "相关设定",
                "设定", "结尾悬念", "结尾钩子", "悬念", "禁止/边界", "禁止", "边界",
            }:
                lines.append(tail)
                skip_list = False
            else:
                skip_list = not tail
            continue
        if skip_list:
            if stripped.startswith(("-", "•", "*", "·")) or re.match(r"^\d+[.)、．]\s*", stripped):
                continue
            skip_list = False
        lines.append(raw_line)
    return _dedupe_text_lines("\n".join(lines)).strip()


def _chapter_reference_line(
    index,
    chap,
    summary_limit=360,
    facts_limit=520,
    include_outline_fallback=False,
    text_fallback_limit=0,
):
    chap = chap if isinstance(chap, dict) else {}
    title = str(chap.get("title", "") or "").strip() or f"章节 {index}"
    summary = _clip_complete_text(chap.get("summary", ""), summary_limit)
    key_facts = _clip_complete_text(chap.get("key_facts", ""), facts_limit)
    parts = []
    if summary:
        parts.append("摘要：" + summary)
    if key_facts:
        parts.append("关键事实：" + key_facts)
    if not parts and include_outline_fallback:
        outline = _clip_complete_text(_strip_static_foreshadow_outline_fields(chap.get("outline", "")), 260)
        if outline:
            parts.append("提纲：" + outline)
    if not (summary or key_facts) and text_fallback_limit:
        body_excerpt = _clip_context_text(
            _dedupe_text_lines(chap.get("text", "")),
            text_fallback_limit,
            keep_tail=True,
        )
        if body_excerpt:
            parts.append("正文摘录：" + body_excerpt)
    if not parts:
        return ""
    return f"第{index}章 {title}｜" + "；".join(parts)


def _build_previous_inheritance_text(chapters, chapter_index, compact_for_draft=False):
    previous_lines = []
    milestone_lines = []
    for index, chap in enumerate(chapters[:chapter_index], 1):
        if not isinstance(chap, dict):
            continue
        line = _chapter_reference_line(index, chap, summary_limit=220, facts_limit=420, text_fallback_limit=260)
        if line:
            previous_lines.append(line)
            if _is_timeline_milestone(chap, line):
                milestone_lines.append(line)

    if compact_for_draft:
        recent_lines = _tail_lines_by_limit(previous_lines, 4200)
        parts = []
        if recent_lines:
            parts.append("近期章节（优先继承）：\n" + "\n".join(recent_lines))
        recent_keys = set(recent_lines)
        older_milestones = [
            line for line in milestone_lines if line not in recent_keys
        ]
        used = len("\n\n".join(parts))
        remaining = max(0, 5000 - used - len("\n\n历史关键转折锚点：\n"))
        if older_milestones and remaining >= 240:
            parts.append(
                "历史关键转折锚点：\n"
                + _clip_lines_balanced(older_milestones, remaining)
            )
        return "\n\n".join(parts) or "暂无"

    recent_lines = _tail_lines_by_limit(previous_lines, 5200)
    recent_keys = set(recent_lines)
    older_lines = [line for line in previous_lines if line not in recent_keys]
    older_milestone_lines = [line for line in milestone_lines if line not in recent_keys]

    parts = []
    if recent_lines:
        parts.append("近期章节（优先继承）：\n" + "\n".join(recent_lines))
    if older_lines:
        older_text = _clip_lines_balanced(older_lines, 6500)
        parts.append("远期关键事实（已压缩，保留开端与近中段）：\n" + older_text)
    if older_milestone_lines:
        milestone_text = _clip_lines_balanced(older_milestone_lines, 2600)
        parts.append("历史关键转折锚点：\n" + milestone_text)
    return "\n\n".join(parts) or "暂无"


_TIMELINE_MILESTONE_KEYWORDS = (
    "真相", "揭晓", "揭示", "回收", "兑现", "反转", "决战", "结局", "死亡", "背叛", "和解",
    "失踪", "身份", "秘密", "遗物", "虎符", "密室", "旧案", "证据", "卷宗", "内鬼",
    "身世", "血脉", "亲缘", "生父", "生母", "亲生父亲", "亲生母亲", "叛徒", "卧底",
    "幕后黑手", "黑手", "凶手", "死因", "牺牲", "复活", "叛变", "倒戈", "归宿",
)


def _is_timeline_milestone(chap, line):
    chap = chap if isinstance(chap, dict) else {}
    text = "\n".join(
        str(chap.get(key, "") or "")
        for key in ("title", "outline", "summary", "key_facts")
    )
    text += "\n" + str(line or "")
    return any(keyword in text for keyword in _TIMELINE_MILESTONE_KEYWORDS)


def _timeline_section_lines(events, total_limit=9000):
    events = events if isinstance(events, list) else []
    if not events:
        return []
    event_lines = [line for _index, line, _is_milestone in events]
    if _line_join_length(event_lines) <= total_limit:
        return [line for _index, line, _is_milestone in events]

    recent_lines = _tail_lines_by_limit(event_lines, max(3200, total_limit // 3))
    recent_keys = set(recent_lines)
    older_events = [
        (index, line, is_milestone)
        for index, line, is_milestone in events
        if line not in recent_keys
    ]
    milestone_events = [
        (index, line, is_milestone)
        for index, line, is_milestone in older_events
        if is_milestone
    ]

    lines = ["近期章节："]
    lines.extend(recent_lines)
    if older_events:
        lines.extend([
            "",
            "早期/中段时间线（已平衡压缩）：",
            _clip_lines_balanced(
                [line for _index, line, _is_milestone in older_events],
                max(2400, total_limit // 2),
            ),
        ])
    if milestone_events:
        lines.extend([
            "",
            "关键转折锚点：",
            _clip_lines_balanced(
                [line for _index, line, _is_milestone in milestone_events],
                max(1800, total_limit // 3),
            ),
        ])
    return lines


def _summary_section_lines(events, total_limit=8200):
    events = events if isinstance(events, list) else []
    if not events:
        return []
    event_lines = [line for _index, line, _is_milestone in events]
    if _line_join_length(event_lines) <= total_limit:
        return ["近期章节：", *event_lines]

    recent_lines = _tail_lines_by_limit(event_lines, max(3000, total_limit // 3))
    recent_keys = set(recent_lines)
    older_events = [
        (index, line, is_milestone)
        for index, line, is_milestone in events
        if line not in recent_keys
    ]
    milestone_events = [
        (index, line, is_milestone)
        for index, line, is_milestone in older_events
        if is_milestone
    ]
    lines = ["近期章节："]
    lines.extend(recent_lines)
    if older_events:
        lines.extend([
            "",
            "长期关键事实（已平衡压缩）：",
            _clip_lines_balanced(
                [line for _index, line, _is_milestone in older_events],
                max(3000, total_limit // 2),
            ),
        ])
    if milestone_events:
        lines.extend([
            "",
            "关键转折锚点：",
            _clip_lines_balanced(
                [line for _index, line, _is_milestone in milestone_events],
                max(2200, total_limit // 3),
            ),
        ])
    return lines


def _build_project_summary_draft(project, through_index=None):
    project = project if isinstance(project, dict) else {}
    _ensure_foreshadow_codes(project)
    meta = project.get("meta", {}) if isinstance(project.get("meta"), dict) else {}
    chapters = project.get("chapters", [])
    chapters = chapters if isinstance(chapters, list) else []
    events = []
    if through_index is not None:
        chapters = chapters[:max(0, min(int(through_index or 0), len(chapters)))]
    for index, chap in enumerate(chapters, 1):
        if not isinstance(chap, dict):
            continue
        line = _chapter_reference_line(index, chap, summary_limit=220, facts_limit=360, text_fallback_limit=280)
        if line:
            events.append((index, line, _is_timeline_milestone(chap, line)))
    if not events:
        return ""

    lines = [
        "阶段摘要草稿",
        f"书名：{meta.get('title', '') or '未命名小说'}",
    ]
    premise = _clip_context_text(meta.get("premise", ""), 800)
    if premise:
        lines.append(f"故事核心：{premise}")
    lines.extend(["", *_summary_section_lines(events)])

    active_character_lines = _active_character_summary_lines(project, limit=0)
    if active_character_lines:
        lines.extend([
            "",
            "高频人物快照：",
            *_select_lines_by_char_budget(active_character_lines, 3000, omitted_label="人物"),
        ])
    active_lore_lines = _active_lore_summary_lines(project, limit=0)
    if active_lore_lines:
        lines.extend([
            "",
            "高频设定快照：",
            *_select_lines_by_char_budget(active_lore_lines, 3000, omitted_label="设定"),
        ])

    active_foreshadows = [
        line
        for _item, line in _rank_open_foreshadow_lines(
            project.get("foreshadow_items", []),
            limit=0,
            route_style="fields",
            skip_placeholders=False,
            include_desc=False,
        )
    ]
    if active_foreshadows:
        lines.extend(["", "未完成伏笔：", *_select_lines_by_char_budget(active_foreshadows, 3000, omitted_label="伏笔")])
    return "\n".join(str(line) for line in lines).strip()


def _build_project_timeline_draft(project, through_index=None):
    project = project if isinstance(project, dict) else {}
    _ensure_foreshadow_codes(project)
    chapters = project.get("chapters", [])
    chapters = chapters if isinstance(chapters, list) else []
    if through_index is not None:
        chapters = chapters[:max(0, min(int(through_index or 0), len(chapters)))]
    lines = ["时间线草稿", "按章节顺序整理，后续可改成故事内真实时间。"]
    events = []
    for index, chap in enumerate(chapters, 1):
        if not isinstance(chap, dict):
            continue
        line = _chapter_reference_line(
            index,
            chap,
            summary_limit=180,
            facts_limit=260,
            include_outline_fallback=False,
            text_fallback_limit=240,
        )
        if line:
            linked = chap.get("linked_characters", [])
            auto_linked = _infer_linked_character_names(project, chap)
            linked_names = _normalize_name_list(
                (linked if isinstance(linked, list) else []) + auto_linked
            )
            linked_text = "、".join(str(x) for x in linked_names if str(x).strip())
            lore_names = _infer_lore_names(project, chap)
            lore_text = "、".join(str(x) for x in lore_names if str(x).strip())
            tail_parts = []
            if linked_text:
                tail_parts.append(f"人物：{linked_text}")
            if lore_text:
                tail_parts.append(f"设定：{lore_text}")
            event_line = f"{line}｜{'｜'.join(tail_parts)}" if tail_parts else line
            events.append((index, event_line, _is_timeline_milestone(chap, event_line)))
    if not events:
        return ""
    lines.extend(["", *_timeline_section_lines(events)])
    return "\n".join(lines).strip()


def _build_foreshadow_notes_draft(project):
    project = project if isinstance(project, dict) else {}
    _ensure_foreshadow_codes(project)
    items = project.get("foreshadow_items", [])
    items = items if isinstance(items, list) else []
    grouped = {"未埋": [], "已埋": [], "已回收": [], "无需回收": [], "废弃": [], "其他": []}
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip() or f"伏笔 {index}"
        code = _normalize_foreshadow_code(item.get("code", ""))
        head = f"{code}｜{name}" if code else name
        status = str(item.get("status", "") or "").strip() or "其他"
        group = status if status in grouped else "其他"
        setup = str(item.get("setup_chapter", "") or "").strip()
        payoff = str(item.get("payoff_chapter", "") or "").strip()
        desc = _clip_complete_text(_stable_foreshadow_description_context(item.get("description", "")), 180)
        route = " -> ".join(x for x in (setup, payoff) if x) or "未填写章节"
        tail = f"｜{desc}" if desc else ""
        line = f"- {head}｜{route}{tail}"
        if group in {"未埋", "已埋"}:
            score, tie_index = _open_foreshadow_queue_score(item, index)
            grouped[group].append((-score, tie_index, line))
        elif group in {"已回收", "无需回收", "废弃"}:
            grouped[group].append((0, -index, line))
        else:
            grouped[group].append((0, index, line))
    if not any(grouped.values()):
        return ""

    budgets = {"未埋": 2600, "已埋": 4200, "已回收": 1800, "无需回收": 700, "废弃": 800, "其他": 1400}
    lines = ["伏笔汇总草稿"]
    for status in ("未埋", "已埋", "已回收", "无需回收", "废弃", "其他"):
        group_items = grouped[status]
        if not group_items:
            continue
        group_items.sort()
        group_lines = [line for _score, _tie_index, line in group_items]
        selected = _select_lines_by_char_budget(group_lines, budgets.get(status, 1200), omitted_label=f"{status}伏笔")
        lines.extend(["", status + "：", *selected])
    return "\n".join(lines).strip()


def _open_foreshadow_queue_score(item, index, current_order=None):
    item = item if isinstance(item, dict) else {}
    status = str(item.get("status", "") or "").strip()
    score = 0
    if status == "已埋":
        score += 2400
    elif status == "未埋":
        score += 1800
    setup = str(item.get("setup_chapter", "") or "").strip()
    payoff = str(item.get("payoff_chapter", "") or "").strip()
    if payoff:
        score += 1200
    if setup:
        score += 500
    current_order = current_order if isinstance(current_order, int) and current_order != _STORY_ORDER_MISSING else None
    setup_order = _story_order_from_text(setup)
    payoff_order = _story_order_from_text(payoff)
    if current_order is not None and payoff_order != _STORY_ORDER_MISSING:
        distance = payoff_order - current_order
        if distance <= 0:
            score += 2600
        elif distance <= 2:
            score += 2200
        elif distance <= 6:
            score += 1500
        elif distance <= 12:
            score += 800
        else:
            score += 240
    if current_order is not None and setup_order != _STORY_ORDER_MISSING:
        if status == "未埋" and setup_order > current_order + 2:
            score -= 900
        elif setup_order <= current_order:
            score += 260
    desc = _stable_foreshadow_description_context(item.get("description", ""))
    compact_desc = _compact_text(desc).strip("。.!！?？；;，,、")
    if compact_desc:
        score += 240 + min(220, len(compact_desc) // 2)
    if compact_desc in {"AI分析候选", "文档导入候选", "后续处理", "待后续处理", "待回收"}:
        score -= 900
    return score, index


def _open_foreshadow_line(item, index, route_style="route", desc_limit=160, include_desc=True):
    item = item if isinstance(item, dict) else {}
    name = str(item.get("name", "") or "").strip() or f"伏笔 {index}"
    code = _normalize_foreshadow_code(item.get("code", ""))
    head = f"{code}｜{name}" if code else name
    status = str(item.get("status", "") or "").strip()
    setup = str(item.get("setup_chapter", "") or "").strip()
    payoff = str(item.get("payoff_chapter", "") or "").strip()
    desc = _stable_foreshadow_description_context(item.get("description", ""))
    desc_text = _clip_complete_text(desc, desc_limit) if include_desc else ""
    if route_style == "fields":
        return f"- {head}｜{status}｜埋设：{setup}｜回收：{payoff}" + (f"｜{desc_text}" if desc_text else "")
    route = " -> ".join(x for x in (setup, payoff) if x) or "未填写章节"
    tail = f"｜{desc_text}" if desc_text else ""
    return f"- {head}｜{status}｜{route}{tail}"


def _rank_open_foreshadow_candidates(
    items,
    selected_keys=None,
    route_style="route",
    skip_placeholders=True,
    include_desc=True,
    current_order=None,
):
    items = items if isinstance(items, list) else []
    selected_keys = selected_keys if isinstance(selected_keys, set) else set()
    candidates = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "") or "").strip()
        if status not in {"未埋", "已埋"}:
            continue
        name = str(item.get("name", "") or "").strip() or f"伏笔 {index}"
        alias_keys = _record_alias_keys(item, name_key="name") or {_compact_text(name)}
        if selected_keys and (alias_keys & selected_keys):
            continue
        desc = _stable_foreshadow_description_context(item.get("description", ""))
        compact_desc = _compact_text(desc).strip("。.!！?？；;，,、")
        if (
            skip_placeholders
            and not str(item.get("payoff_chapter", "") or "").strip()
            and compact_desc in {"后续处理", "待后续处理", "待回收"}
        ):
            continue
        score, tie_index = _open_foreshadow_queue_score(item, index, current_order=current_order)
        line = _open_foreshadow_line(item, index, route_style=route_style, include_desc=include_desc)
        candidates.append((-score, tie_index, item, line))
    candidates.sort()
    return candidates


def _rank_open_foreshadow_lines(
    items,
    selected_keys=None,
    limit=12,
    route_style="route",
    skip_placeholders=True,
    include_desc=True,
    current_order=None,
):
    candidates = _rank_open_foreshadow_candidates(
        items,
        selected_keys=selected_keys,
        route_style=route_style,
        skip_placeholders=skip_placeholders,
        include_desc=include_desc,
        current_order=current_order,
    )
    selected = candidates if limit is None or int(limit or 0) <= 0 else candidates[: max(1, int(limit or 1))]
    return [(item, line) for _score, _tie_index, item, line in selected]


def _build_open_foreshadow_queue(
    project, selected_items=None, limit=0, current_order=None, include_desc=True
):
    project = project if isinstance(project, dict) else {}
    selected_keys = set()
    for item in selected_items if isinstance(selected_items, list) else []:
        if isinstance(item, dict):
            selected_keys.update(_record_alias_keys(item, name_key="name"))
            selected_keys.add(_compact_text(item.get("name", "")))
    items = project.get("foreshadow_items", [])
    items = items if isinstance(items, list) else []
    candidates = _rank_open_foreshadow_candidates(
        items,
        selected_keys=selected_keys,
        include_desc=include_desc,
        current_order=current_order,
    )
    raw_lines = [line for _score, _tie_index, _item, line in candidates]
    budget = int(limit or 0)
    lines = _select_lines_by_char_budget(raw_lines, budget if budget > 0 else 2400, omitted_label="开放伏笔")
    if not lines:
        return ""
    guide = (
        "动态伏笔调度参考（开放伏笔队列；不是硬任务）：\n"
        "请结合当前章节提纲、已发生事实、后续近章边界和人物动机，自行判断每条伏笔本章应“推进 / 回收 / 暂不处理”。\n"
        "只有与本章核心事件自然相连时才推进或回收；不要为了凑回收率强行解释、提前揭底或改写本章主线。"
    )
    return guide + "\n" + "\n".join(lines)


def _recent_chapter_context(chapters, chapter_index, window=6, project=None):
    chapters = chapters if isinstance(chapters, list) else []
    project = project if isinstance(project, dict) else {}
    start = max(0, int(chapter_index or 0) - int(window or 0))
    parts = []
    linked = []
    for index, item in enumerate(chapters[start:chapter_index], start + 1):
        if not isinstance(item, dict):
            continue
        if not _chapter_has_occurred_content(item):
            continue
        line = _chapter_reference_line(
            index,
            item,
            summary_limit=260,
            facts_limit=420,
            include_outline_fallback=False,
            text_fallback_limit=320,
        )
        if line:
            parts.append(line)
        names = item.get("linked_characters", [])
        if isinstance(names, list):
            linked.extend(str(name) for name in names if str(name).strip())
        if project:
            linked.extend(_infer_linked_character_names(project, item))
    return "\n".join(parts), _normalize_name_list(linked)


def _record_recent_context_map(project, records, before_index, name_key="name", limit_per_record=2):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", [])
    chapters = chapters if isinstance(chapters, list) else []
    records = records if isinstance(records, list) else []
    before_index = max(0, min(int(before_index or 0), len(chapters)))
    out = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        name = _clean_entity_name(record.get(name_key, ""))
        key = _compact_text(name)
        aliases = _record_aliases(record, name_key=name_key)
        if not key or not aliases:
            continue
        alias_keys = {_compact_text(alias) for alias in aliases if _compact_text(alias)}
        lines = []
        for index in range(before_index - 1, -1, -1):
            chap = chapters[index]
            if not isinstance(chap, dict):
                continue
            if not _chapter_has_occurred_content(chap):
                continue
            linked = chap.get("linked_characters", [])
            linked_keys = {
                _compact_text(item)
                for item in (linked if isinstance(linked, list) else _normalize_name_list(linked))
                if str(item or "").strip()
            }
            text = "\n".join(
                str(chap.get(field, "") or "")
                for field in ("title", "summary", "key_facts", "text")
            )
            if not ((alias_keys & linked_keys) or any(_name_in_text(alias, text) for alias in aliases)):
                continue
            line = _chapter_reference_line(
                index + 1,
                chap,
                summary_limit=140,
                facts_limit=220,
                include_outline_fallback=False,
                text_fallback_limit=180,
            )
            if line:
                lines.append(line)
            else:
                title = str(chap.get("title", "") or f"章节 {index + 1}").strip()
                lines.append(f"第{index + 1}章 {title}｜出现/被提及")
            if len(lines) >= max(1, int(limit_per_record or 1)):
                break
        if lines:
            out[key] = "；".join(reversed(lines))
    return out


def _build_future_plan_text(chapters, chapter_index, window=4):
    chapters = chapters if isinstance(chapters, list) else []
    start = max(0, int(chapter_index or 0) + 1)
    end = min(len(chapters), start + max(1, int(window or 1)))
    planned_lines = []
    for index, item in enumerate(chapters[start:end], start + 1):
        if not isinstance(item, dict):
            continue
        line = _chapter_reference_line(
            index,
            item,
            summary_limit=220,
            facts_limit=320,
            include_outline_fallback=True,
        )
        if line:
            planned_lines.append(line)

    milestone_lines = []
    for index, item in enumerate(chapters[end:], end + 1):
        if not isinstance(item, dict):
            continue
        text = "\n".join(
            str(item.get(key, "") or "")
            for key in ("title", "outline", "summary", "key_facts")
        )
        if not _compact_text(text):
            continue
        if _is_timeline_milestone(item, text):
            line = _chapter_reference_line(
                index,
                item,
                summary_limit=160,
                facts_limit=220,
                include_outline_fallback=True,
            )
            if line:
                milestone_lines.append(line)

    parts = []
    if planned_lines:
        parts.append("后续近章规划（当前章只能铺垫，不要提前写完）：\n" + "\n".join(planned_lines))
    if milestone_lines:
        parts.append("远期回收/转折锚点（只用于避免越界）：\n" + _clip_lines_balanced(milestone_lines, 2600, head=4, tail=4))
    return "\n\n".join(parts) or "暂无"


def _chapter_previous_text(project, chapter_index):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    try:
        index = int(chapter_index or 0)
    except Exception:
        return ""
    if index <= 0 or index >= len(chapters):
        return ""
    previous = chapters[index - 1]
    if not isinstance(previous, dict):
        return ""
    return str(previous.get("text", "") or "").strip()


def _chapter_previous_opening_boundary_text(project, chapter_index):
    previous_text = _chapter_previous_text(project, chapter_index)
    if not previous_text:
        return ""
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    try:
        index = int(chapter_index or 0)
    except Exception:
        return ""
    if index < 0 or index >= len(chapters) or not isinstance(chapters[index], dict):
        return ""
    if _compact_text(chapters[index].get("text", "")):
        return ""
    return previous_text


def _build_chapter_continuation_text(chapters, chapter_index):
    chapters = chapters if isinstance(chapters, list) else []
    parts = []
    has_current_text = False
    if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict):
        has_current_text = bool(_compact_text(chapters[chapter_index].get("text", "")))
    if 0 <= chapter_index - 1 < len(chapters):
        prev = chapters[chapter_index - 1]
        if isinstance(prev, dict):
            prev_limit = 1800 if has_current_text else 4200
            prev_tail = _tail_text_window(prev.get("text", ""), limit=prev_limit)
            if prev_tail:
                title = str(prev.get("title", "") or f"章节 {chapter_index}").strip()
                parts.append(
                    f"上一章「{title}」结尾原文（已发布正文；只继承时间、天气、地点、人物位置、情绪和未完成动作，禁止原样或同义重写）：\n"
                    "以下文字已经在上一章展示给读者。本章开头必须越过这段已完成文字：上一章以对白结束时，从听者的新反应或新回答开始；"
                    "以上一章以动作结束时，从动作造成的新结果或新阻力开始；以上一章以声音结束时，从声源揭示或人物听见后的新反应开始。\n"
                    + prev_tail
                )
    if 0 <= chapter_index < len(chapters):
        current = chapters[chapter_index]
        if isinstance(current, dict):
            current_tail = _tail_text_window(current.get("text", ""), limit=3400)
            if current_tail:
                parts.append("当前正文结尾原文（续写应从这里自然接上，不要重复）：\n" + current_tail)
    return "\n\n".join(parts)


def _build_next_chapter_anchor_text(chapters, chapter_index, limit=500):
    chapters = chapters if isinstance(chapters, list) else []
    if not (0 <= chapter_index < len(chapters)):
        return ""
    current = chapters[chapter_index]
    if not isinstance(current, dict) or _compact_text(current.get("text", "")):
        return ""
    next_index = chapter_index + 1
    if not (0 <= next_index < len(chapters)):
        return ""
    next_chapter = chapters[next_index]
    if not isinstance(next_chapter, dict):
        return ""
    next_head = _clip_complete_text(next_chapter.get("text", ""), int(limit or 500))
    if not next_head:
        return ""
    title = str(next_chapter.get("title", "") or f"章节 {next_index + 1}").strip()
    return (
        f"下一章「{title}」开头原文（只用于当前章结尾对齐，不要复述、改写或提前写完下一章）：\n"
        + next_head
    )


def _chapter_reference_score(value, chapter_index, chapter_title):
    text = _compact_text(value)
    if not text:
        return 0
    title = _compact_text(chapter_title)
    markers = []
    has_explicit_title_marker = False
    if title:
        markers.append((title, 420))
        title_prefix = re.match(r"^(第[一二三四五六七八九十百千万零〇\d]+[章节回卷部集场])", title)
        if title_prefix:
            markers.append((title_prefix.group(1), 380))
            has_explicit_title_marker = True
    if not has_explicit_title_marker:
        number = chapter_index + 1
        markers.extend(
            (marker, 360)
            for marker in (
                f"第{number}章",
                f"{number}章",
                f"章节{number}",
                f"第{number}节",
                f"{number}节",
            )
        )
    for marker, score in markers:
        if marker and marker in text:
            return score
    return 0


_CONTINUITY_KEYWORDS = (
    "老杂役", "杂役", "密室", "铜盘", "石台", "乱葬岗", "守山木屋",
    "封脉针", "止血散", "灰衣执事", "中品骨",
)


def _continuity_memory(project):
    """Read either long-form memory shape without migrating project data."""
    project = project if isinstance(project, dict) else {}
    legacy = project.get("long_form_memory")
    primary = project.get("long_form")
    if isinstance(primary, dict) and isinstance(legacy, dict):
        merged = deepcopy(legacy)
        for key, value in primary.items():
            if value not in (None, "", [], {}):
                merged[key] = deepcopy(value)
        return merged
    if isinstance(primary, dict):
        return deepcopy(primary)
    if isinstance(legacy, dict):
        return deepcopy(legacy)
    return {}


def _build_targeted_continuity_context(project, chapter_index, chapter_match_text):
    """Expose a few confirmed, scene-relevant facts to the legacy writer."""
    memory = _continuity_memory(project)
    if not memory:
        return ""
    query = _compact_text(chapter_match_text)
    triggers = [term for term in _CONTINUITY_KEYWORDS if term in query]
    if not triggers:
        return ""
    try:
        current_chapter = max(0, int(chapter_index or 0))
    except Exception:
        current_chapter = 0

    lines = []
    facts = memory.get("active_facts", [])
    for item in facts if isinstance(facts, list) else []:
        if not isinstance(item, dict):
            continue
        base_fact = str(item.get("fact", "") or "").strip()
        if "老杂役" in base_fact and "铜盘" in base_fact and any(
            word in base_fact for word in ("目睹", "亲眼", "现场")
        ):
            continue
        try:
            base_source = int(item.get("source_chapter_index", 0) or 0)
        except Exception:
            base_source = 0
        try:
            base_evidence = int(item.get("evidence_chapter_index", 0) or 0)
        except Exception:
            base_evidence = 0
        # Source chapter indexes are one-based while chapter_index is zero-based;
        # later review/evidence updates must not leak into the current draft.
        candidates = [
            (base_source, base_fact)
        ] if (
            base_fact and base_source <= current_chapter
            and (not base_evidence or base_evidence <= current_chapter)
        ) else []
        for detail in item.get("continuity_details", []) if isinstance(item.get("continuity_details"), list) else []:
            if not isinstance(detail, dict):
                continue
            fact = str(detail.get("fact", "") or "").strip()
            try:
                source = int(detail.get("source_chapter_index", 0) or 0)
            except Exception:
                source = 0
            if fact and source <= current_chapter:
                candidates.append((source, fact))
        if not candidates:
            continue
        source, fact = max(candidates, key=lambda value: (value[0], len(value[1])))
        # A fact may have been revised later with a sentence about the chapter
        # currently being drafted (or a later chapter).  Do not let that
        # retrospective sentence leak into the draft as if it were prior
        # evidence.
        future_numbers = []
        for raw in re.findall(
            r"第\s*([一二两三四五六七八九十百千万零〇\d]+)\s*章", fact
        ):
            number = _chinese_numeral_to_int(raw)
            if number is not None:
                future_numbers.append(number)
        if any(value >= current_chapter + 1 for value in future_numbers):
            continue
        haystack = _compact_text("\n".join(str(item.get(key, "") or "") for key in ("fact", "evidence")))
        if not any(term in haystack for term in triggers):
            continue
        # A rescue worker must not be given an invented viewpoint over the
        # separate bone-removal scene.
        if "老杂役" in fact and "铜盘" in fact and any(word in fact for word in ("目睹", "亲眼", "现场")):
            continue
        lines.append((source, fact))
    # Keep the block deliberately small and deterministic.
    unique = []
    seen = set()
    for source, fact in sorted(lines, key=lambda value: (value[0], len(value[1])), reverse=True):
        key = _compact_text(fact)
        if key and key not in seen:
            seen.add(key)
            unique.append((source, fact))
        if len(unique) >= 8:
            break

    snapshot = memory.get("state_snapshot", {})
    if isinstance(snapshot, dict):
        try:
            snapshot_index = int(snapshot.get("as_of_chapter_index", 0) or 0)
        except Exception:
            snapshot_index = 0
        if snapshot_index <= current_chapter:
            for group in ("character_states", "object_states"):
                for item in snapshot.get(group, []) if isinstance(snapshot.get(group), list) else []:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "") or "").strip()
                    state = str(item.get("state", "") or "").strip()
                    if name and state and any(term in _compact_text(name + state) for term in triggers):
                        unique.append((0, f"当前状态（{name}）：{_clip_complete_text(state, 420)}"))
    if not unique:
        return ""
    rendered = []
    for source, fact in unique[:10]:
        source_label = f"第{source}章已确认" if source else "已确认"
        rendered.append(
            f"- {source_label}：{_clip_complete_text(fact, 620, keep_tail=False)}"
        )
    return (
        "以下是与本章场景相关的已确认连续性依据，用于保持时间顺序、人物视角和物件状态。\n"
        "章节提纲只是创作计划；如与已确认正文事实冲突，保留本章剧情目标，并按已确认依据调整细节。\n"
        + "\n".join(rendered)
    )


def _chapter_memory_view(project, chapter_index):
    """Return a read-only memory view with facts/state not yet known removed."""
    view = deepcopy(project if isinstance(project, dict) else {})
    memory = _continuity_memory(view)
    if not memory:
        return view
    try:
        current = max(0, int(chapter_index or 0))
    except Exception:
        current = 0
    facts = []
    for item in memory.get("active_facts", []) if isinstance(memory.get("active_facts"), list) else []:
        if not isinstance(item, dict):
            continue
        try:
            source = int(item.get("source_chapter_index", 0) or 0)
        except Exception:
            source = 0
        try:
            evidence = int(item.get("evidence_chapter_index", 0) or 0)
        except Exception:
            evidence = 0
        if source > current or (evidence and evidence > current):
            continue
        copied = deepcopy(item)
        if "老杂役" in str(copied.get("fact", "") or "") and "铜盘" in str(copied.get("fact", "") or "") and any(
            word in str(copied.get("fact", "") or "") for word in ("目睹", "亲眼", "现场")
        ):
            continue
        details = []
        for detail in copied.get("continuity_details", []) if isinstance(copied.get("continuity_details"), list) else []:
            if not isinstance(detail, dict):
                continue
            try:
                detail_source = int(detail.get("source_chapter_index", 0) or 0)
            except Exception:
                detail_source = 0
            if detail_source <= current:
                details.append(detail)
        if details:
            copied["continuity_details"] = details
        facts.append(copied)
    memory["active_facts"] = facts
    snapshot = memory.get("state_snapshot")
    if isinstance(snapshot, dict):
        try:
            snapshot_index = int(snapshot.get("as_of_chapter_index", 0) or 0)
        except Exception:
            snapshot_index = 0
        if snapshot_index > current:
            memory["state_snapshot"] = {}
    archives = []
    for archive in memory.get("stage_archives", []) if isinstance(memory.get("stage_archives"), list) else []:
        if not isinstance(archive, dict):
            continue
        try:
            end_index = int(archive.get("end_chapter_index", 0) or 0)
        except Exception:
            end_index = 0
        if not end_index or end_index <= current:
            archives.append(archive)
    memory["stage_archives"] = archives
    runtime = memory.get("record_runtime")
    if isinstance(runtime, dict):
        for records in runtime.values():
            if not isinstance(records, dict):
                continue
            for key, entry in list(records.items()):
                if not isinstance(entry, dict):
                    continue
                developments = entry.get("developments")
                if not isinstance(developments, list):
                    continue
                kept = []
                latest_index = 0
                for development in developments:
                    if not isinstance(development, dict):
                        continue
                    try:
                        development_index = int(development.get("chapter_index", 0) or 0)
                    except Exception:
                        development_index = 0
                    if development_index <= current:
                        kept.append(development)
                    latest_index = max(latest_index, development_index)
                entry["developments"] = kept
                if latest_index > current:
                    entry["state"] = ""
    # _long_form_memory_sections consumes the legacy key; provide the merged
    # view there without writing it back to the project.
    view["long_form_memory"] = memory
    return view


def _style_percentile(values, ratio):
    ordered = sorted(int(value) for value in values if int(value) >= 0)
    if not ordered:
        return 0
    index = round((len(ordered) - 1) * max(0.0, min(1.0, float(ratio))))
    return ordered[index]


def _style_text_structure(value):
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = [line.strip() for line in text.split("\n") if line.strip()]
    compact = _compact_text(text)
    total_chars = len(compact)
    paragraph_lengths = [len(_compact_text(paragraph)) for paragraph in paragraphs]
    sentence_parts = [part for part in re.split(r"[。！？!?；;…]+", compact) if part]
    sentence_lengths = [len(part) for part in sentence_parts] or ([total_chars] if total_chars else [])
    single_sentence_short_count = 0
    for paragraph, length in zip(paragraphs, paragraph_lengths):
        sentence_count = len([part for part in re.split(r"[。！？!?；;…]+", _compact_text(paragraph)) if part])
        if (
            length <= 35
            and sentence_count <= 1
            and not any(mark in paragraph for mark in ("“", "”", "「", "」", "『", "』", '"'))
        ):
            single_sentence_short_count += 1
    dialogue_matches = re.findall(
        r"“[^”]*”|「[^」]*」|『[^』]*』|\"[^\"\n]*\"",
        text,
    )
    dialogue_turn_lengths = [
        len(_compact_text(match).strip("“”「」『』\""))
        for match in dialogue_matches
    ]
    dialogue_chars = sum(len(_compact_text(match)) for match in dialogue_matches)
    dialogue_paragraphs = sum(
        1 for paragraph in paragraphs
        if any(mark in paragraph for mark in ("“", "”", "「", "」", "『", "』", '"'))
    )
    paragraph_count = len(paragraphs)
    short_dialogue_run = 0
    max_short_dialogue_run = 0
    for paragraph in paragraphs:
        match = re.fullmatch(
            r"\s*(?:“([^”]*)”|「([^」]*)」|『([^』]*)』|\"([^\"\n]*)\")\s*",
            paragraph,
        )
        inner = next((group for group in match.groups() if group is not None), "") if match else ""
        if match and len(_compact_text(inner)) <= 15:
            short_dialogue_run += 1
            max_short_dialogue_run = max(max_short_dialogue_run, short_dialogue_run)
        else:
            short_dialogue_run = 0
    dialogue_turn_count = len(dialogue_turn_lengths)
    short_dialogue_turn_count = sum(length <= 15 for length in dialogue_turn_lengths)
    return {
        "text": text,
        "paragraphs": paragraphs,
        "chars": total_chars,
        "paragraph_count": paragraph_count,
        "paragraph_lengths": paragraph_lengths,
        "paragraphs_per_1000": paragraph_count * 1000 / total_chars if total_chars else 0.0,
        "paragraph_median": _style_percentile(paragraph_lengths, 0.5),
        "short_paragraph_pct": (
            sum(length <= 15 for length in paragraph_lengths) * 100 / paragraph_count
            if paragraph_count else 0.0
        ),
        "single_sentence_short_paragraph_pct": (
            single_sentence_short_count * 100 / paragraph_count
            if paragraph_count else 0.0
        ),
        "long_paragraph_pct": (
            sum(length >= 80 for length in paragraph_lengths) * 100 / paragraph_count
            if paragraph_count else 0.0
        ),
        "sentence_lengths": sentence_lengths,
        "sentence_median": _style_percentile(sentence_lengths, 0.5),
        "dialogue_chars": dialogue_chars,
        "dialogue_char_pct": dialogue_chars * 100 / total_chars if total_chars else 0.0,
        "dialogue_paragraph_pct": dialogue_paragraphs * 100 / paragraph_count if paragraph_count else 0.0,
        "dialogue_turn_count": dialogue_turn_count,
        "dialogue_turn_lengths": dialogue_turn_lengths,
        "dialogue_turn_median": _style_percentile(dialogue_turn_lengths, 0.5),
        "dialogue_turns_per_1000": dialogue_turn_count * 1000 / total_chars if total_chars else 0.0,
        "short_dialogue_turn_count": short_dialogue_turn_count,
        "short_dialogue_turns_per_1000": (
            short_dialogue_turn_count * 1000 / total_chars if total_chars else 0.0
        ),
        "max_short_dialogue_run": max_short_dialogue_run,
    }


def _style_centered_structure_bands(reference, target_chars=0):
    structure = reference if isinstance(reference, dict) else _style_text_structure(reference)
    target = max(0, int(target_chars or 0))
    expected_paragraphs = structure["paragraphs_per_1000"] * target / 1000 if target else 0.0
    expected_dialogue_turns = structure["dialogue_turns_per_1000"] * target / 1000 if target else 0.0
    expected_short_dialogue_turns = (
        structure["short_dialogue_turns_per_1000"] * target / 1000 if target else 0.0
    )
    return {
        "paragraph_low": max(1, round(expected_paragraphs * 0.85)) if expected_paragraphs else 0,
        "paragraph_high": max(1, round(expected_paragraphs * 1.15)) if expected_paragraphs else 0,
        "density_low": structure["paragraphs_per_1000"] * 0.85,
        "density_high": structure["paragraphs_per_1000"] * 1.15,
        "short_pct_low": max(0.0, structure["short_paragraph_pct"] - 8.0),
        "short_pct_high": min(100.0, structure["short_paragraph_pct"] + 8.0),
        "dialogue_pct_low": max(0.0, structure["dialogue_char_pct"] - 8.0),
        "dialogue_pct_high": min(100.0, structure["dialogue_char_pct"] + 8.0),
        "dialogue_turn_low": max(0, round(expected_dialogue_turns * 0.80)),
        "dialogue_turn_high": max(1, round(expected_dialogue_turns * 1.20)) if expected_dialogue_turns else 0,
        "dialogue_turn_rate_high": max(
            structure["dialogue_turns_per_1000"] + 4.0,
            structure["dialogue_turns_per_1000"] * 1.20,
        ),
        "short_dialogue_turn_low": max(0, round(expected_short_dialogue_turns * 0.80)),
        "short_dialogue_turn_high": (
            max(1, round(expected_short_dialogue_turns * 1.25))
            if expected_short_dialogue_turns else 0
        ),
        "short_dialogue_turn_rate_high": max(
            structure["short_dialogue_turns_per_1000"] + 3.0,
            structure["short_dialogue_turns_per_1000"] * 1.25,
        ),
    }


def _style_fragmentation_drift_flags(reference, candidate):
    ref = reference if isinstance(reference, dict) else _style_text_structure(reference)
    current = candidate if isinstance(candidate, dict) else _style_text_structure(candidate)
    if ref["chars"] < 500 or current["chars"] < 300:
        return []
    bands = _style_centered_structure_bands(ref, current["chars"])
    flags = []
    if current["paragraphs_per_1000"] > bands["density_high"]:
        flags.append("段落密度偏高")
    if current["short_paragraph_pct"] > bands["short_pct_high"]:
        flags.append("短段比例偏高")
    if (
        ref["single_sentence_short_paragraph_pct"] < 55
        and current["single_sentence_short_paragraph_pct"]
        - ref["single_sentence_short_paragraph_pct"] > 18
    ):
        flags.append("非对白单句短段偏高")
    if current["dialogue_char_pct"] > bands["dialogue_pct_high"]:
        flags.append("对白字数占比偏高")
    if current["dialogue_turns_per_1000"] > bands["dialogue_turn_rate_high"]:
        flags.append("对白轮数偏多")
    if current["short_dialogue_turns_per_1000"] > bands["short_dialogue_turn_rate_high"]:
        flags.append("短对白轮数偏多")
    return flags


def _style_boundary_paragraphs(value, from_start=False, limit=3):
    paragraphs = _style_text_structure(value)["paragraphs"]
    try:
        count = max(1, int(limit or 3))
    except Exception:
        count = 3
    return paragraphs[:count] if from_start else paragraphs[-count:]


def _style_boundary_repetition_match(previous_text, current_text):
    previous_paragraphs = _style_boundary_paragraphs(previous_text, limit=3)
    current_paragraphs = _style_boundary_paragraphs(current_text, from_start=True, limit=3)
    for previous in previous_paragraphs:
        previous_compact = _compact_text(previous)
        if not previous_compact:
            continue
        for current in current_paragraphs:
            current_compact = _compact_text(current)
            if not current_compact:
                continue
            if previous_compact == current_compact:
                return {"previous": previous, "current": current}
            shorter, longer = sorted((previous_compact, current_compact), key=len)
            if shorter not in longer or not re.search(r"[\w\u4e00-\u9fff]", shorter):
                continue
            if len(shorter) >= 4 or (
                len(shorter) >= 3
                and (longer.startswith(shorter) or longer.endswith(shorter))
            ):
                return {"previous": previous, "current": current}
    return {}


def _style_output_target_from_context(context):
    text = str(context or "")
    match = re.search(r"本次新增正文(?:参考)?目标：\s*约?\s*(\d{1,7})\s*字", text)
    if not match:
        match = re.search(r"本章扩写字数：\s*(\d{2,7})\s*字", text)
    try:
        return max(0, int(match.group(1))) if match else 0
    except Exception:
        return 0


def _style_draft_mismatch_reasons(style_reference, draft_text, output_target=0):
    reference = _style_text_structure(style_reference)
    draft = _style_text_structure(draft_text)
    if reference["chars"] < 500 or draft["chars"] < 300:
        return []

    reasons = []
    target = int(output_target or 0)
    if target and not (target * 0.80 <= draft["chars"] <= target * 1.20):
        reasons.append(f"正文总字数不符：目标约{target}字，首次正文约{draft['chars']}字")
    ref_density = reference["paragraphs_per_1000"]
    draft_density = draft["paragraphs_per_1000"]
    if ref_density and not (ref_density * 0.80 <= draft_density <= ref_density * 1.20):
        reasons.append(
            f"段落密度偏差过大：样本每1000字约{ref_density:.1f}段，首次正文约{draft_density:.1f}段"
        )

    ref_median = reference["paragraph_median"]
    draft_median = draft["paragraph_median"]
    if ref_median and not (ref_median * 0.75 <= draft_median <= ref_median * 1.35):
        reasons.append(f"段落长度中位数不符：样本约{ref_median}字，首次正文约{draft_median}字")

    short_gap = draft["short_paragraph_pct"] - reference["short_paragraph_pct"]
    if abs(short_gap) > 8:
        reasons.append(
            f"短段比例不符：样本15字以内段落约占{reference['short_paragraph_pct']:.0f}%，"
            f"首次正文约占{draft['short_paragraph_pct']:.0f}%"
        )

    single_sentence_gap = (
        draft["single_sentence_short_paragraph_pct"]
        - reference["single_sentence_short_paragraph_pct"]
    )
    if single_sentence_gap > 15 and reference["single_sentence_short_paragraph_pct"] < 55:
        reasons.append(
            f"短单句段过多：样本约{reference['single_sentence_short_paragraph_pct']:.0f}%，"
            f"首次正文约{draft['single_sentence_short_paragraph_pct']:.0f}%；普通说明不能连续拆段"
        )

    ref_long = reference["long_paragraph_pct"]
    draft_long = draft["long_paragraph_pct"]
    if ref_long >= 5 and draft_long < max(2.0, ref_long * 0.65):
        reasons.append(
            f"中长段不足：样本80字以上段落约占{ref_long:.0f}%，首次正文仅约占{draft_long:.0f}%"
        )

    ref_sentence = reference["sentence_median"]
    draft_sentence = draft["sentence_median"]
    if ref_sentence and not (ref_sentence * 0.75 <= draft_sentence <= ref_sentence * 1.35):
        reasons.append(f"句子长度中位数不符：样本约{ref_sentence}字，首次正文约{draft_sentence}字")

    dialogue_gap = abs(draft["dialogue_char_pct"] - reference["dialogue_char_pct"])
    if dialogue_gap > 8:
        reasons.append(
            f"对白字数占比不符：样本约{reference['dialogue_char_pct']:.0f}%，"
            f"首次正文约{draft['dialogue_char_pct']:.0f}%"
        )
    bands = _style_centered_structure_bands(reference, draft["chars"])
    if draft["dialogue_turns_per_1000"] > bands["dialogue_turn_rate_high"]:
        reasons.append(
            f"对白轮数偏多：样本每1000字约{reference['dialogue_turns_per_1000']:.1f}轮，"
            f"首次正文约{draft['dialogue_turns_per_1000']:.1f}轮"
        )
    if draft["short_dialogue_turns_per_1000"] > bands["short_dialogue_turn_rate_high"]:
        reasons.append(
            f"短对白轮数偏多：样本每1000字约{reference['short_dialogue_turns_per_1000']:.1f}轮，"
            f"首次正文约{draft['short_dialogue_turns_per_1000']:.1f}轮"
        )
    fragmentation_flags = _style_fragmentation_drift_flags(reference, draft)
    if len(fragmentation_flags) >= 2:
        reasons.append(
            "结构多项同时向短碎方向漂移：" + "、".join(fragmentation_flags)
        )
    return reasons


def _style_finalize_preflight_targets(style_reference, candidate_text, output_target=0):
    reference = _style_text_structure(style_reference)
    candidate = _style_text_structure(candidate_text)
    if reference["chars"] < 500 or candidate["chars"] < 300:
        return ""
    lines = []
    target = int(output_target or 0)
    if target:
        low = round(target * 0.85)
        high = round(target * 1.15)
        if not (low <= candidate["chars"] <= high):
            direction = "压缩" if candidate["chars"] > high else "补足"
            lines.append(
                f"候选正文约{candidate['chars']}字，本次须在不改变剧情的前提下{direction}到{low}-{high}字。"
            )

    bands = _style_centered_structure_bands(reference, target or candidate["chars"])
    fragmentation_flags = _style_fragmentation_drift_flags(reference, candidate)
    if len(fragmentation_flags) >= 2:
        lines.append(
            "候选同时出现" + "、".join(fragmentation_flags)
            + "；本次必须整体减少无效换行和功能性短问短答，不能只修其中一项。"
        )

    density = reference["paragraphs_per_1000"]
    if target and density:
        paragraph_low = bands["paragraph_low"]
        paragraph_high = max(paragraph_low, bands["paragraph_high"])
        paragraph_count = int(candidate["paragraph_count"] or 0)
        if paragraph_count > paragraph_high:
            lines.append(
                f"候选有{paragraph_count}个非空段，本次至少合并{paragraph_count - paragraph_high}个普通段，"
                f"交付时保持{paragraph_low}-{paragraph_high}段。"
            )

    short_gap = candidate["short_paragraph_pct"] - reference["short_paragraph_pct"]
    if short_gap > 8:
        paragraph_count = int(candidate["paragraph_count"] or 0)
        short_count = sum(length <= 15 for length in candidate["paragraph_lengths"])
        allowed_high = bands["short_pct_high"] / 100.0
        merge_count = 0
        while (
            merge_count < short_count
            and paragraph_count - merge_count > 0
            and (short_count - merge_count) / (paragraph_count - merge_count) > allowed_high
        ):
            merge_count += 1
        if merge_count:
            lines.append(
                f"候选15字以内短段占{candidate['short_paragraph_pct']:.0f}%，样本约"
                f"{reference['short_paragraph_pct']:.0f}%；至少将{merge_count}个普通短段并入相邻相关段落。"
            )

    median_low = max(1, reference["paragraph_median"] - 8)
    median_high = reference["paragraph_median"] + 8
    if not (median_low <= candidate["paragraph_median"] <= median_high):
        lines.append(
            f"候选段落中位数约{candidate['paragraph_median']}字，本次须调整到{median_low}-{median_high}字。"
        )
    single_short_gap = (
        candidate["single_sentence_short_paragraph_pct"]
        - reference["single_sentence_short_paragraph_pct"]
    )
    if single_short_gap > 18 and reference["single_sentence_short_paragraph_pct"] < 55:
        lines.append(
            f"候选非对白单句短段占{candidate['single_sentence_short_paragraph_pct']:.0f}%，"
            f"样本约{reference['single_sentence_short_paragraph_pct']:.0f}%；普通说明连续短段必须先合并再交付。"
        )
    dialogue_overage = candidate["dialogue_char_pct"] - reference["dialogue_char_pct"]
    if dialogue_overage > 8:
        dialogue_high_pct = bands["dialogue_pct_high"]
        dialogue_high_chars = max(0, math.floor(candidate["chars"] * dialogue_high_pct / 100))
        dialogue_rewrite_chars = max(
            0,
            int(candidate.get("dialogue_chars", 0) or 0) - dialogue_high_chars,
        )
        lines.append(
            f"候选对白字数占{candidate['dialogue_char_pct']:.0f}%，样本约"
            f"{reference['dialogue_char_pct']:.0f}%；本次至少将{dialogue_rewrite_chars}字普通对白"
            f"改写为人物化叙述，交付时对白总字数不得超过约{dialogue_high_chars}字。"
            "保留人物声纹和冲突小场景，优先改写普通核验、汇报、流程命令和重复问答；"
            "不能只删引号、缩短对白或用新增对白补回。"
        )
    if (
        bands["dialogue_turn_high"]
        and candidate["dialogue_turn_count"] > bands["dialogue_turn_high"]
    ):
        lines.append(
            f"候选有{candidate['dialogue_turn_count']}轮对白，按样本和本章篇幅约应保持"
            f"{bands['dialogue_turn_low']}-{bands['dialogue_turn_high']}轮；优先删除或改写只负责确认、"
            "交接、复问和重复结论的台词，不得删减冲突、关系变化和关键信息。"
        )
    if (
        bands["short_dialogue_turn_high"]
        and candidate["short_dialogue_turn_count"] > bands["short_dialogue_turn_high"]
    ):
        lines.append(
            f"候选15字以内短对白有{candidate['short_dialogue_turn_count']}轮，样本中心区间约为"
            f"{bands['short_dialogue_turn_low']}-{bands['short_dialogue_turn_high']}轮；"
            "将无新增信息的‘可以、好、明白、结果、能否’式功能台词并入动作或相邻完整表达。"
        )
    return "\n".join(f"- {line}" for line in lines)


def _style_finalize_priority_edit_text(style_reference, candidate_text, output_target=0):
    preflight = _style_finalize_preflight_targets(
        style_reference,
        candidate_text,
        output_target,
    )
    if not preflight:
        return ""
    return (
        "只修正下面这些已经严重偏离样本的结构问题；剧情完整、人物自然反应和场景适配高于数字，不得为了命中指标新增对白、笑点、动作或拆段。\n"
        + preflight
        + "\n人物语言声纹只约束已经需要开口的人物。不要为了展示口吻新增台词；普通核验、汇报、程序命令和重复追问优先并回人物化叙述。"
    )


def _style_execution_beats(value):
    text = str(value or "").strip()
    if not text:
        return []
    text = re.split(
        r"(?im)^\s*【?静默继承边界】?\s*[:：]?\s*$",
        text,
        maxsplit=1,
    )[0]
    matches = list(re.finditer(r"(?m)^\s*(\d{1,2})\s*[.、）)]\s*", text))
    beats = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        beat_text = text[match.end():end].strip()
        if beat_text:
            beats.append({"beat": int(match.group(1)), "text": beat_text})
    return beats


def _parse_style_finalize_acceptance(value):
    text = str(value or "").strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.IGNORECASE | re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    start = text.find("{")
    if start < 0:
        return {}
    try:
        data, _offset = json.JSONDecoder().raw_decode(text[start:])
    except Exception:
        return {}
    return deepcopy(data) if isinstance(data, dict) else {}


def _style_max_short_narrative_run(value):
    structure = _style_text_structure(value)
    longest = 0
    current = 0
    for paragraph in structure["paragraphs"]:
        compact = _compact_text(paragraph)
        sentence_count = len([
            part for part in re.split(r"[。！？!?；;…]+", compact) if part
        ])
        is_dialogue = any(
            mark in paragraph for mark in ("“", "”", "「", "」", "『", "』", '"')
        )
        if len(compact) <= 35 and sentence_count <= 1 and not is_dialogue:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _style_voice_evidence_dialogue_spans(value):
    return [
        _compact_text(match)
        for match in re.findall(
            r"“[^”]*”|「[^」]*」|『[^』]*』|\"[^\"\n]*\"",
            str(value or ""),
        )
        if _compact_text(match)
    ]


def _style_voice_evidence_has_reaction(value):
    remainder = re.sub(
        r"“[^”]*”|「[^」]*」|『[^』]*』|\"[^\"\n]*\"",
        "",
        str(value or ""),
    )
    return len("".join(re.findall(r"[\u3400-\u9fff]", remainder))) >= 4


def _style_voice_evidence_literal_scene(value, final_text, min_dialogue_spans=2, max_chars=360):
    raw = str(value or "").strip()
    body = str(final_text or "")
    dialogue_spans = _style_voice_evidence_dialogue_spans(raw)
    try:
        minimum = max(1, int(min_dialogue_spans or 1))
    except Exception:
        minimum = 2
    if len(set(dialogue_spans)) < minimum or not body:
        return ""

    projected_body, positions = _evidence_projection(body, with_positions=True)
    if not projected_body or not positions:
        return ""
    matches = []
    search_from = 0
    for span in dialogue_spans:
        projected_span = _evidence_projection(span)
        if len(projected_span) < 2:
            continue
        start = projected_body.find(projected_span, search_from)
        if start < 0:
            continue
        end = start + len(projected_span) - 1
        if end >= len(positions):
            continue
        matches.append((start, end))
        search_from = end + 1
        if len(matches) >= minimum:
            break
    if len(matches) < minimum:
        return ""

    body_start = positions[matches[0][0]]
    body_end = positions[matches[-1][1]] + 1
    if body_start > 0 and body[body_start - 1] in "“「『\"":
        body_start -= 1
    if body_end < len(body) and body[body_end] in "”」』\"":
        body_end += 1
    scene = body[body_start:body_end].strip()
    if (
        len(_compact_text(scene)) > max(80, int(max_chars or 360))
        or len(set(_style_voice_evidence_dialogue_spans(scene))) < minimum
        or not _long_form_evidence_present(scene, body)
    ):
        return ""
    return scene


def _style_finalize_acceptance_flag_failed(value):
    """Return True only when the model explicitly reports a failed check."""
    if value is False:
        return True
    if isinstance(value, dict):
        for key in ("passed", "ok", "compatible", "valid"):
            if value.get(key) is False:
                return True
    return False


_LITERAL_COUNT_CHINESE_DIGITS = {
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


def _literal_count_number_to_int(value):
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{1,3}", text):
        return int(text)
    if text in _LITERAL_COUNT_CHINESE_DIGITS:
        return _LITERAL_COUNT_CHINESE_DIGITS[text]
    if text == "十":
        return 10
    if text.startswith("十") and len(text) == 2 and text[1] in _LITERAL_COUNT_CHINESE_DIGITS:
        return 10 + _LITERAL_COUNT_CHINESE_DIGITS[text[1]]
    if text.endswith("十") and len(text) == 2 and text[0] in _LITERAL_COUNT_CHINESE_DIGITS:
        return _LITERAL_COUNT_CHINESE_DIGITS[text[0]] * 10
    if (
        len(text) == 3
        and text[1] == "十"
        and text[0] in _LITERAL_COUNT_CHINESE_DIGITS
        and text[2] in _LITERAL_COUNT_CHINESE_DIGITS
    ):
        return _LITERAL_COUNT_CHINESE_DIGITS[text[0]] * 10 + _LITERAL_COUNT_CHINESE_DIGITS[text[2]]
    return None


def _literal_count_claim_issues(final_text):
    """Normalize deictic literal-count claims without guessing their referent."""
    body = str(final_text or "")
    if not body.strip():
        return []
    pattern = re.compile(
        r"(?P<deictic>[这那])(?P<num>\d{1,2}|[零〇一二两三四五六七八九十]{1,3})个字"
    )
    issues = []
    for match in pattern.finditer(body):
        claimed = _literal_count_number_to_int(match.group("num"))
        # "这一个字" remains natural and unambiguous. Any larger claimed
        # count is intentionally generalized instead of trying to infer which
        # earlier text it refers to.
        if claimed is None or claimed < 2:
            continue
        replacement = f"{match.group('deictic')}几个字"
        issues.append({
            "claimed": claimed,
            "claim_text": match.group(0),
            "num_text": match.group("num"),
            "replacement_text": replacement,
            "start": match.start(),
            "end": match.end(),
            "normalization": "deictic_literal_count",
        })
    return issues


def _repair_literal_count_claims(final_text):
    body = str(final_text or "").strip()
    issues = _literal_count_claim_issues(body)
    if not issues:
        return body, []
    repaired = body
    for item in sorted(issues, key=lambda value: int(value.get("start", 0)), reverse=True):
        repaired = (
            repaired[:item["start"]]
            + item["replacement_text"]
            + repaired[item["end"]:]
        )
    return repaired.strip(), issues


def _style_finalize_error_is_hard(value):
    """Classify only continuity and prose-quality failures as rewrite blockers."""
    text = str(value or "").strip()
    if not text:
        return False
    return bool(
        "前两章剧情复演" in text
        or "终稿逻辑连续性" in text
        or "文风仿写明确失败" in text
        or text.startswith("章首承接重复上一章")
        or text.startswith("跨章期限")
        or "办案式流程明显扩张" in text
        or "机械感明显" in text
    )


def _style_finalize_acceptance_errors(
    execution_text,
    final_text,
    acceptance,
    style_reference="",
    output_target=0,
    project=None,
    chapter_index=0,
    style_plan="",
    profile_text="",
):
    body = str(final_text or "").strip()
    beats = _style_execution_beats(execution_text)
    result = acceptance if isinstance(acceptance, dict) else {}
    errors = []
    target = max(0, int(output_target or 0))
    body_chars = len(_compact_text(body))
    if target and body_chars >= 300 and not (
        target * 0.75 <= body_chars <= target * 1.30
    ):
        direction = "压缩" if body_chars > target else "补足"
        errors.append(
            f"终稿正文长度明显偏离目标：目标约{target}字，终稿约{body_chars}字；"
            f"须在不删剧情拍点的前提下{direction}到约{round(target * 0.85)}-"
            f"{round(target * 1.15)}字"
        )
    if beats:
        # 剧情拍点只作为正文组织参考，不再要求模型为每个拍点提交逐字证据。
        # 短对白、短动作和自然合并的剧情表达不应因为证据长度触发整章重写。
        if _style_finalize_acceptance_flag_failed(
            result.get("previous_chapter_repetition_check")
        ):
            errors.append("前两章剧情复演：终稿仍重复上一章已发布内容")
        if _style_finalize_acceptance_flag_failed(
            result.get("logic_continuity_check")
        ):
            errors.append(
                "终稿逻辑连续性明确失败：时间顺序、因果、代词指向或人物状态存在冲突"
            )
        if _style_finalize_acceptance_flag_failed(
            result.get("role_voice_attribution_check")
        ):
            errors.append("正文文风仿写明确失败：角色声纹或标志句归属错误")
    previous_boundary = _chapter_previous_opening_boundary_text(project, chapter_index)
    if previous_boundary:
        opening = result.get("opening_continuation", {})
        opening = opening if isinstance(opening, dict) else {}
        first_new_sentence = str(opening.get("first_new_sentence", "") or "").strip()
        new_action_or_result = str(opening.get("new_action_or_result", "") or "").strip()
        opening_text = "\n".join(_style_boundary_paragraphs(body, from_start=True, limit=3))
        if first_new_sentence:
            first_new_sentence = _literalize_long_form_evidence_quote(
                first_new_sentence,
                opening_text,
            )
            if (
                len(_compact_text(first_new_sentence)) < 4
                or not _long_form_evidence_present(first_new_sentence, opening_text)
            ):
                errors.append("章首承接首个新句不是终稿前三段中的4字以上逐字原文")
        if new_action_or_result and len(_compact_text(new_action_or_result)) < 4:
            errors.append("章首新增变量没有说明新反应、新结果、新阻力或新信息")
        repetition = _style_boundary_repetition_match(previous_boundary, body)
        if repetition:
            repeated = _compact_text(repetition.get("current", ""))[:60]
            errors.append(f"章首承接重复上一章已发布结尾：{repeated}")
        timeline_check = result.get("timeline_commitment_check", {})
        timeline_check = timeline_check if isinstance(timeline_check, dict) else {}
        prior_commitment = str(
            timeline_check.get("prior_deadline_or_promise", "") or ""
        ).strip()
        current_schedule = str(
            timeline_check.get("current_schedule", "") or ""
        ).strip()
        if _style_finalize_acceptance_flag_failed(timeline_check.get("compatible")):
            errors.append("跨章期限、承诺与当前时间安排仍不兼容")

    # These are hard prose-quality checks even when the execution parser did
    # not recover a beat list from a malformed model response.
    if _style_finalize_acceptance_flag_failed(
        result.get("procedural_expansion_check")
    ):
        errors.append("正文办案式流程明显扩张：非主线核验、交接或记录过程挤占了剧情")
    if _style_finalize_acceptance_flag_failed(
        result.get("mechanical_prose_check")
    ):
        errors.append("正文机械感明显：同构动作、重复解释或功能性问答形成流程化播报")
    reference = _style_text_structure(style_reference)
    final_structure = _style_text_structure(body)
    if reference["chars"] >= 500 and final_structure["chars"] >= 300:
        bands = _style_centered_structure_bands(reference, final_structure["chars"])
        fragmentation_flags = _style_fragmentation_drift_flags(
            reference,
            final_structure,
        )
        if len(fragmentation_flags) >= 2:
            errors.append(
                "终稿结构同时向短碎方向漂移："
                + "、".join(fragmentation_flags)
                + "；必须整体减少无效换行和功能性短问短答"
            )
        ref_density = reference["paragraphs_per_1000"]
        final_density = final_structure["paragraphs_per_1000"]
        if ref_density and not (ref_density * 0.75 <= final_density <= ref_density * 1.25):
            errors.append(
                f"终稿段落密度未贴近样本：样本每1000字{ref_density:.1f}段，终稿{final_density:.1f}段"
            )
        short_gap = final_structure["short_paragraph_pct"] - reference["short_paragraph_pct"]
        if short_gap > 12 or short_gap < -18:
            paragraph_count = int(final_structure["paragraph_count"] or 0)
            short_count = sum(
                length <= 15 for length in final_structure["paragraph_lengths"]
            )
            allowed_high = min(100.0, reference["short_paragraph_pct"] + 12.0) / 100.0
            merge_count = 0
            while (
                short_gap > 12
                and merge_count < short_count
                and paragraph_count - merge_count > 0
                and (short_count - merge_count) / (paragraph_count - merge_count) > allowed_high
            ):
                merge_count += 1
            merge_hint = (
                f"；至少把{merge_count}个短段并入相邻相关段落"
                if short_gap > 12 and merge_count else ""
            )
            errors.append(
                f"终稿短段比例未贴近样本：样本{reference['short_paragraph_pct']:.0f}%，"
                f"终稿共{paragraph_count}段、其中15字以内{short_count}段，"
                f"占{final_structure['short_paragraph_pct']:.0f}%{merge_hint}"
            )
        single_short_gap = (
            final_structure["single_sentence_short_paragraph_pct"]
            - reference["single_sentence_short_paragraph_pct"]
        )
        if single_short_gap > 18 and reference["single_sentence_short_paragraph_pct"] < 55:
            errors.append(
                "终稿非对白短单句段明显多于样本，普通说明需要合并"
            )
        reference_run = _style_max_short_narrative_run(style_reference)
        final_run = _style_max_short_narrative_run(body)
        if final_run >= 3 and final_run > max(2, reference_run + 1):
            errors.append(
                f"终稿连续非对白短段达到{final_run}段，样本最长约{reference_run}段"
            )
        if (
            final_structure["dialogue_char_pct"]
            > reference["dialogue_char_pct"] + 12.0
        ):
            errors.append(
                f"终稿对白字数占比明显高于样本：样本{reference['dialogue_char_pct']:.0f}%，"
                f"终稿{final_structure['dialogue_char_pct']:.0f}%；保留声纹小场景，"
                "把普通核验、汇报、命令和重复问答合并回人物化叙述"
            )
        if final_structure["dialogue_turns_per_1000"] > max(
            reference["dialogue_turns_per_1000"] + 4.0,
            reference["dialogue_turns_per_1000"] * 1.30,
        ):
            errors.append(
                f"终稿对白轮数明显高于样本：样本每1000字约"
                f"{reference['dialogue_turns_per_1000']:.1f}轮，终稿约"
                f"{final_structure['dialogue_turns_per_1000']:.1f}轮；"
                "删除或改写只承担确认、交接、复问和重复结论的台词"
            )
        if final_structure["short_dialogue_turns_per_1000"] > max(
            reference["short_dialogue_turns_per_1000"] + 3.0,
            reference["short_dialogue_turns_per_1000"] * 1.35,
        ):
            errors.append(
                f"终稿短对白轮数明显高于样本：样本每1000字约"
                f"{reference['short_dialogue_turns_per_1000']:.1f}轮，终稿约"
                f"{final_structure['short_dialogue_turns_per_1000']:.1f}轮；"
                "把无新增信息的极短问答并入动作或相邻完整表达"
            )
        # The local structural measurements are authoritative for this check.
        # A model can omit the boolean after completing a valid edit; do not
        # spend another full-body call solely to repair that self-report.
    if target and profile_text and style_reference and body:
        reference_compact = _compact_text(style_reference)
        body_compact = _compact_text(body)
        reference_chars = max(1, len(reference_compact))
        density_drift = []
        for phrase in _style_profile_extracted_phrases(
            profile_text,
            style_reference,
        )[:120]:
            sample_count = reference_compact.count(phrase)
            if sample_count <= 0:
                continue
            expected = sample_count * target / reference_chars
            soft_upper = min(
                sample_count,
                max(1, int(math.ceil(expected + 0.5))),
            )
            actual_count = body_compact.count(phrase)
            if actual_count > soft_upper + 1:
                density_drift.append(
                    (actual_count - soft_upper, actual_count, phrase, soft_upper)
                )
        if density_drift:
            density_drift.sort(key=lambda item: (-item[0], -item[1], item[2]))
            details = "、".join(
                f"{phrase}{actual_count}次/软上沿{soft_upper}次"
                for _, actual_count, phrase, soft_upper in density_drift[:12]
            )
            errors.append(
                "终稿原生词密度明显高于样本："
                + details
                + "；保留语义必要处，其余改用自然句式或省去重复动作标签，不改剧情"
            )
    return errors


def _style_paragraph_kind(paragraph):
    text = str(paragraph or "").strip()
    compact = _compact_text(text)
    if any(mark in text for mark in ("“", "”", "「", "」", "『", "』", '"')):
        return "对白"
    if len(compact) >= 80 or sum(text.count(term) for term in (
        "因为", "所以", "其实", "原来", "意味着", "也就是说", "对于", "按照", "规则", "身份", "当年",
    )) >= 2:
        return "说明"
    if re.search(r"冲|扑|抓|抬|转身|回头|走|跑|退|砸|斩|杀|打|踢|伸手|落下|站起|坐下", text):
        return "动作"
    if re.search(r"心中|心里|害怕|恐惧|愤怒|悲|痛|紧张|担心|绝望|希望|后悔|不甘|眼泪|哭|笑", text):
        return "情绪"
    if len(compact) <= 15:
        return "强调短段"
    return "叙述"


def _style_reference_blocks(style_reference, target_chars=900):
    paragraphs = _style_text_structure(style_reference)["paragraphs"]
    blocks = []
    current = []
    current_chars = 0
    target = max(400, int(target_chars or 900))
    for paragraph in paragraphs:
        length = len(_compact_text(paragraph))
        if current and current_chars >= target:
            blocks.append("\n\n".join(current))
            current = []
            current_chars = 0
        current.append(paragraph)
        current_chars += length
    if current:
        blocks.append("\n\n".join(current))
    return blocks


def _select_style_reference_excerpts(style_reference, query_text="", limit=6000):
    reference = str(style_reference or "").strip()
    max_chars = max(1000, int(limit or 6000))
    if len(reference) <= max_chars:
        return reference
    blocks = _style_reference_blocks(reference, 850)
    if not blocks:
        return reference[:max_chars]

    def block_features(block):
        structure = _style_text_structure(block)
        compact = structure["text"]
        paragraphs = structure["paragraphs"]
        kinds = [_style_paragraph_kind(paragraph) for paragraph in paragraphs]
        return {
            "dialogue": structure["dialogue_paragraph_pct"],
            "long": structure["long_paragraph_pct"],
            "action": sum(kind == "动作" for kind in kinds) * 100 / max(1, len(kinds)),
            "emotion": sum(kind == "情绪" for kind in kinds) * 100 / max(1, len(kinds)),
            "exposition": sum(kind == "说明" for kind in kinds) * 100 / max(1, len(kinds)),
            "chars": len(_compact_text(compact)),
        }

    features = [block_features(block) for block in blocks]
    query = str(query_text or "")
    requested = []
    if re.search(r"对白|质问|争执|谈判|询问|开口|说道|回答", query):
        requested.append("dialogue")
    if re.search(r"冲突|战斗|追杀|逃|闯|救|杀|打|攻击|反杀", query):
        requested.append("action")
    if re.search(r"规则|设定|身份|身世|真相|解释|契约|神|债|制度", query):
        requested.append("exposition")
    if re.search(r"情绪|关系|回忆|悲|怒|怕|爱|绝望|希望|牵挂", query):
        requested.append("emotion")

    selected = {0, len(blocks) - 1}
    priority = [0]
    if len(blocks) > 1:
        priority.append(len(blocks) - 1)
    criteria = requested + ["long", "dialogue", "exposition", "action", "emotion"]
    for criterion in criteria:
        candidates = [index for index in range(len(blocks)) if index not in selected]
        if not candidates:
            break
        chosen_index = max(candidates, key=lambda index: features[index].get(criterion, 0))
        selected.add(chosen_index)
        priority.append(chosen_index)

    average_dialogue = sum(item["dialogue"] for item in features) / len(features)
    average_long = sum(item["long"] for item in features) / len(features)
    remaining = [index for index in range(len(blocks)) if index not in selected]
    if remaining:
        chosen_index = min(
            remaining,
            key=lambda index: abs(features[index]["dialogue"] - average_dialogue)
            + abs(features[index]["long"] - average_long),
        )
        selected.add(chosen_index)
        priority.append(chosen_index)

    accepted = []
    used = 0
    for index in priority:
        label = f"【代表片段｜原样本位置{index + 1}/{len(blocks)}】\n"
        block = blocks[index].strip()
        addition = len(label) + len(block) + 2
        if accepted and used + addition > max_chars:
            continue
        if not accepted and addition > max_chars:
            block = _clip_context_text(block, max(1, max_chars - len(label)), keep_tail=False, preserve_lines=True)
            addition = len(label) + len(block)
        accepted.append((index, block))
        used += addition
    chosen = [
        f"【代表片段{number}｜原样本位置{index + 1}/{len(blocks)}】\n{block}"
        for number, (index, block) in enumerate(sorted(accepted), 1)
    ]
    return "\n\n".join(chosen)[:max_chars]


def _build_style_profile_request_context(style_reference):
    reference = str(style_reference or "").strip()
    numeric_profile = _build_style_reference_profile(reference, 0)
    reference_for_ai = (
        reference if len(reference) <= 50000
        else _select_style_reference_excerpts(reference, limit=45000)
    )
    return (
        "【基于完整样本的本地文风指纹】\n"
        f"{numeric_profile}\n\n"
        "【待分析正文样本】\n"
        f"{reference_for_ai}\n\n"
        "【任务】\n"
        "只分析写法，不分析或复述剧情。输出一个JSON对象，字段必须包括："
        "narrative_voice、roughness_and_polish、paragraph_rhythm、sentence_patterns、dialogue_integration、"
        "lexical_habits、sentence_rhetoric、paragraph_function_sequence、exposition_method、emotion_source、"
        "scene_progression、information_order、emphasis_habits、ending_method、"
        "must_preserve、must_avoid。每个字段用具体可执行的中文描述，说明作者怎样写，而不是评价写得好不好。"
        "忽略网页复制、OCR或文档提取造成的异常空格、异形字符、词语断行、孤立引号和明显标点错误，"
        "这些不是需要模仿的文风；但作者真实存在的直白、重复、解释性叙述和句法不够精炼仍应识别。"
        "must_preserve和must_avoid必须是字符串数组。只输出JSON，不要Markdown代码块。"
    )


STYLE_SHEET_CACHE_VERSION = 3
STYLE_CARD_CACHE_VERSION = 1
STYLE_SEMANTIC_ARCHIVE_VERSION = 4
STYLE_SEMANTIC_ARCHIVE_SCHEMA = "semantic_voice_v4"
STYLE_SEMANTIC_VOCABULARY_LIMIT = 120
STYLE_CARD_CATEGORIES = (
    "推理与解释",
    "专业角色对白",
    "权威角色命令",
    "弱势与恐惧对白",
    "异常逐步显形",
    "群体反应",
    "日常口语与喜剧",
    "章节收束",
)
STYLE_CARD_DIMENSIONS = {
    "推理与解释": "叙述/场景",
    "异常逐步显形": "叙述/场景",
    "群体反应": "叙述/场景",
    "专业角色对白": "对白",
    "权威角色命令": "对白",
    "弱势与恐惧对白": "对白",
    "日常口语与喜剧": "对白",
    "章节收束": "收束/格式",
}
STYLE_NARRATIVE_MODES = (
    "冲突推进",
    "情绪关系",
    "动作危机",
    "喜剧反差",
    "信息揭示",
    "调查推理",
)
STYLE_PROCEDURAL_CARD_CATEGORIES = {"推理与解释", "专业角色对白"}

STYLE_CONFLICT_VOICE_TERMS = (
    "冲突", "争执", "互呛", "拆台", "施压", "反制", "反击", "对峙",
    "质问", "打断", "争夺", "压制", "误会", "翻盘", "拒绝", "否认",
)


def _style_exact_source_excerpt(style_reference, excerpt):
    reference = str(style_reference or "").replace("\r\n", "\n").replace("\r", "\n")
    value = str(excerpt or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not reference or not value:
        return ""
    candidates = [value]
    # Models regularly add a pair of quotation marks around a sampled narration
    # sentence.  Try the literal excerpt first, then only remove that outer
    # wrapper.  The returned evidence still always comes from the raw sample.
    quote_pairs = (("“", "”"), ("‘", "’"), ('"', '"'), ("'", "'"))
    for opener, closer in quote_pairs:
        if len(value) > 2 and value.startswith(opener) and value.endswith(closer):
            unwrapped = value[len(opener):-len(closer)].strip()
            if unwrapped:
                candidates.append(unwrapped)
    compact_chars = []
    source_indexes = []
    for source_index, char in enumerate(reference):
        if char.isspace():
            continue
        compact_chars.append(char)
        source_indexes.append(source_index)
    compact_reference = "".join(compact_chars)
    for candidate in candidates:
        exact_at = reference.find(candidate)
        if exact_at >= 0:
            return reference[exact_at:exact_at + len(candidate)].strip()
        compact_value = _compact_text(candidate)
        if not compact_value:
            continue
        compact_at = compact_reference.find(compact_value)
        if compact_at < 0:
            continue
        source_start = source_indexes[compact_at]
        source_end = source_indexes[compact_at + len(compact_value) - 1] + 1
        return reference[source_start:source_end].strip()
    return ""


def _normalize_style_cards(value, style_reference="", max_cards=12):
    items = value if isinstance(value, list) else []
    cards = []
    seen_excerpts = set()
    used_ids = set()
    limit = max(1, min(20, int(max_cards or 12)))
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_excerpt = str(item.get("source_excerpt", item.get("excerpt", "")) or "").strip()
        excerpt = (
            _style_exact_source_excerpt(style_reference, raw_excerpt)
            if str(style_reference or "").strip() else raw_excerpt
        )
        compact_excerpt = _compact_text(excerpt)
        if len(compact_excerpt) < 120 or compact_excerpt in seen_excerpts:
            continue
        category = str(item.get("category", "") or "").strip()
        if category not in STYLE_CARD_CATEGORIES:
            category = next(
                (candidate for candidate in STYLE_CARD_CATEGORIES if candidate in category),
                "",
            )
        if not category:
            continue
        seen_excerpts.add(compact_excerpt)
        card_id = str(item.get("id", "") or "").strip().upper()
        if not re.fullmatch(r"SC\d{2}", card_id) or card_id in used_ids:
            next_number = 1
            while f"SC{next_number:02d}" in used_ids:
                next_number += 1
            card_id = f"SC{next_number:02d}"
        used_ids.add(card_id)
        cards.append({
            "id": card_id,
            "category": category,
            "title": str(item.get("title", "") or category).strip()[:80] or category,
            "use_when": str(item.get("use_when", "") or "").strip()[:500],
            "avoid_when": str(item.get("avoid_when", "") or "").strip()[:500],
            "voice_features": str(item.get("voice_features", "") or "").strip()[:800],
            "source_excerpt": excerpt,
        })
        if len(cards) >= limit:
            break
    return cards


def _parse_style_cards_result(value, style_reference):
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match and match.group(0) != text:
        candidates.append(match.group(0))
    data = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            data = parsed
            break
    if not isinstance(data, dict):
        return []
    return _normalize_style_cards(data.get("cards", []), style_reference)


def _style_json_data(value):
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    for pattern in (r"\{.*\}", r"\[.*\]"):
        match = re.search(pattern, text, flags=re.DOTALL)
        if match and match.group(0) != text:
            candidates.append(match.group(0))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, (dict, list)):
            return data
    return {}


def _style_json_object(value):
    data = _style_json_data(value)
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"cards": data}
    return {}


def _style_card_items_from_json(value, *keys):
    data = _style_json_data(value)
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in keys or ("cards",):
        items = data.get(key)
        if isinstance(items, list):
            return items
    return []


def _style_card_field(item, *keys):
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return ""


def _style_native_vocabulary_seed_terms(profile_text, style_reference, limit=84):
    """Return the archive's established original vocabulary in stable order."""
    try:
        count = max(1, int(limit or 84))
    except Exception:
        count = 84
    return _style_profile_extracted_phrases(profile_text, style_reference)[:count]


def _normalize_native_vocabulary_cards(
    value,
    style_reference="",
    required_terms=None,
    max_cards=STYLE_SEMANTIC_VOCABULARY_LIMIT,
):
    reference = str(style_reference or "").strip()
    expected = []
    seen_expected = set()
    for term in required_terms if isinstance(required_terms, (list, tuple)) else []:
        normalized = _compact_text(term)
        if normalized and normalized not in seen_expected:
            expected.append(normalized)
            seen_expected.add(normalized)
    allowed = set(expected)
    cards = []
    seen = set()
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        term = _compact_text(item.get("term", item.get("word", "")))
        if not term or term in seen or (allowed and term not in allowed):
            continue
        if len(term) > 16 or not re.search(r"[\u3400-\u9fff]", term):
            continue
        source_value = str(
            item.get("source_evidence", item.get("source_excerpt", item.get("evidence", "")))
            or ""
        ).strip()
        source_evidence = _style_exact_source_excerpt(reference, source_value) if reference else source_value
        if reference and (not source_evidence or term not in _compact_text(source_evidence)):
            continue
        card = {
            "term": term,
            "meaning": str(item.get("meaning", "") or "").strip()[:180],
            "emotional_temperature": str(item.get("emotional_temperature", "") or "").strip()[:100],
            "speaker_or_viewpoint": str(item.get("speaker_or_viewpoint", item.get("ownership", "")) or "").strip()[:160],
            "use_when": str(item.get("use_when", "") or "").strip()[:220],
            "sentence_position": str(item.get("sentence_position", "") or "").strip()[:130],
            "natural_collocations": str(item.get("natural_collocations", "") or "").strip()[:200],
            "avoid_when": str(item.get("avoid_when", "") or "").strip()[:220],
            "source_evidence": source_evidence[:500],
        }
        if not all(card[key] for key in (
            "meaning", "emotional_temperature", "speaker_or_viewpoint", "use_when",
            "sentence_position", "natural_collocations", "avoid_when", "source_evidence",
        )):
            continue
        cards.append(card)
        seen.add(term)
        if len(cards) >= max(1, int(max_cards or STYLE_SEMANTIC_VOCABULARY_LIMIT)):
            break
    if expected:
        order = {term: index for index, term in enumerate(expected)}
        cards.sort(key=lambda item: order.get(item["term"], len(order)))
    return cards


def _parse_native_vocabulary_cards_result(value, style_reference, required_terms=None):
    data = _style_json_object(value)
    return _normalize_native_vocabulary_cards(
        data.get("cards", []),
        style_reference,
        required_terms=required_terms,
    )


def _normalize_style_voice_cards(value, style_reference="", max_cards=12):
    reference = str(style_reference or "").strip()
    cards = []
    seen = set()
    for index, item in enumerate(value if isinstance(value, list) else [], 1):
        if not isinstance(item, dict):
            continue
        card_id = str(item.get("id", "") or "").strip().upper()
        if not re.fullmatch(r"VC\d{2}", card_id) or card_id in seen:
            card_id = f"VC{index:02d}"
            while card_id in seen:
                index += 1
                card_id = f"VC{index:02d}"
        source_value = str(_style_card_field(
            item,
            "source_evidence", "source_excerpt", "evidence", "source",
            "原文证据", "原文片段", "证据", "样本证据",
        ) or "").strip()
        source_evidence = _style_exact_source_excerpt(reference, source_value) if reference else source_value
        card = {
            "id": card_id,
            "title": str(_style_card_field(item, "title", "name", "标题", "声纹标题") or "").strip()[:80],
            "owner": str(_style_card_field(item, "owner", "speaker", "viewpoint", "归属", "人物", "视角") or "").strip()[:160],
            "voice_features": str(_style_card_field(
                item, "voice_features", "features", "voice", "语言特征", "声纹", "口吻特征"
            ) or "").strip()[:600],
            "use_when": str(_style_card_field(item, "use_when", "use", "适用", "适用场景", "什么时候用") or "").strip()[:240],
            "avoid_when": str(_style_card_field(item, "avoid_when", "avoid", "边界", "不用在", "避免") or "").strip()[:240],
            "source_evidence": source_evidence[:500],
        }
        if not all(card[key] for key in (
            "title", "owner", "voice_features", "use_when", "avoid_when", "source_evidence",
        )):
            continue
        cards.append(card)
        seen.add(card_id)
        if len(cards) >= max(1, int(max_cards or 12)):
            break
    return cards


def _parse_style_voice_cards_result(value, style_reference):
    return _normalize_style_voice_cards(
        _style_card_items_from_json(value, "cards", "voice_cards", "声纹卡", "人物与叙述声纹卡"),
        style_reference,
    )


def _normalize_style_technique_cards(value, style_reference="", max_cards=12):
    reference = str(style_reference or "").strip()
    cards = []
    seen = set()
    for index, item in enumerate(value if isinstance(value, list) else [], 1):
        if not isinstance(item, dict):
            continue
        card_id = str(item.get("id", "") or "").strip().upper()
        if not re.fullmatch(r"TC\d{2}", card_id) or card_id in seen:
            card_id = f"TC{index:02d}"
            while card_id in seen:
                index += 1
                card_id = f"TC{index:02d}"
        source_value = str(_style_card_field(
            item,
            "source_evidence", "source_excerpt", "evidence", "source",
            "原文证据", "原文片段", "证据", "样本证据",
        ) or "").strip()
        source_evidence = _style_exact_source_excerpt(reference, source_value) if reference else source_value
        card = {
            "id": card_id,
            "title": str(_style_card_field(item, "title", "name", "标题", "技法标题") or "").strip()[:80],
            "trigger": str(_style_card_field(item, "trigger", "use_when", "适用", "触发条件", "何时使用") or "").strip()[:260],
            "use_method": str(_style_card_field(item, "use_method", "method", "写法", "使用方法", "技法") or "").strip()[:600],
            "avoid_when": str(_style_card_field(item, "avoid_when", "avoid", "边界", "不用在", "避免") or "").strip()[:280],
            "source_evidence": source_evidence[:500],
        }
        if not all(card[key] for key in (
            "title", "trigger", "use_method", "avoid_when", "source_evidence",
        )):
            continue
        cards.append(card)
        seen.add(card_id)
        if len(cards) >= max(1, int(max_cards or 12)):
            break
    return cards


def _parse_style_technique_cards_result(value, style_reference):
    return _normalize_style_technique_cards(
        _style_card_items_from_json(value, "cards", "technique_cards", "技法卡", "条件性叙事技法卡"),
        style_reference,
    )


def _normalize_semantic_style_archive(cache_entry, style_reference=""):
    entry = cache_entry if isinstance(cache_entry, dict) else {}
    schema = str(entry.get("style_archive_schema", "") or "").strip()
    try:
        if schema == STYLE_SEMANTIC_ARCHIVE_SCHEMA:
            version = int(entry.get("semantic_archive_version", 0) or 0)
        else:
            # Runtime callers may pass the already-normalized semantic archive
            # returned by this helper.  Accept that shape instead of clearing
            # the V4 vocabulary and voice cards on a second normalization pass.
            version = int(entry.get("version", 0) or 0)
    except Exception:
        version = 0
    if schema and schema != STYLE_SEMANTIC_ARCHIVE_SCHEMA:
        return {}
    if version < STYLE_SEMANTIC_ARCHIVE_VERSION:
        return {}
    vocabulary = _normalize_native_vocabulary_cards(
        entry.get("native_vocabulary_cards", []), style_reference
    )
    voices = _normalize_style_voice_cards(entry.get("voice_cards", []), style_reference)
    techniques = _normalize_style_technique_cards(entry.get("technique_cards", []), style_reference)
    runtime_pack = str(entry.get("runtime_voice_pack", "") or "").strip()
    if not vocabulary or not voices or not techniques or not runtime_pack:
        return {}
    return {
        "version": version,
        "native_vocabulary_cards": vocabulary,
        "voice_cards": voices,
        "technique_cards": techniques,
        "runtime_voice_pack": runtime_pack,
    }


def _format_native_vocabulary_cards(cards, limit=18000):
    rows = []
    for card in _normalize_native_vocabulary_cards(cards):
        rows.append(
            f"【{card['term']}】真义：{card['meaning']}；情绪温度：{card['emotional_temperature']}；"
            f"说话/视角：{card['speaker_or_viewpoint']}；适用：{card['use_when']}；"
            f"句位：{card['sentence_position']}；自然搭配：{card['natural_collocations']}；"
            f"不用在：{card['avoid_when']}。"
        )
    if not rows:
        return ""
    text = (
        f"以下{len(rows)}项都是作者原样本中实际存在的语言材料，全部保留在本章上下文。"
        "它们不是每章逐个打卡的词表：当当前人物、情绪和句位吻合时，优先用这里的原生表达替代模型默认的书面话或套路话；"
        "不吻合就不硬塞。必须按每项的说话归属、情绪温度和不用边界使用，不能把所有词都安给同一个人。\n"
        + "\n".join(rows)
    )
    return text[:max(0, int(limit or 18000))]


def _format_style_voice_cards(cards, limit=6000):
    rows = []
    for card in _normalize_style_voice_cards(cards):
        rows.append(
            f"【{card['id']}｜{card['title']}】归属：{card['owner']}；声纹：{card['voice_features']}；"
            f"适用：{card['use_when']}；边界：{card['avoid_when']}。"
        )
    if not rows:
        return ""
    return (
        "人物声纹是每章常驻的语言层，只在对应人物开口、心理或贴近其视角的叙述出现时落实；"
        "不为了展示声纹而新增对白、吵架或笑点。"
        "卡内样本人物名、称呼和关系只用于理解功能口吻，写当前小说时必须映射成当前人物，"
        "严禁把样本姓名、关系和事件带入正文。\n" + "\n".join(rows)
    )[:max(0, int(limit or 6000))]


def _format_style_technique_cards(cards, limit=6500):
    rows = []
    for card in _normalize_style_technique_cards(cards):
        rows.append(
            f"【{card['id']}｜{card['title']}】仅当：{card['trigger']}。写法：{card['use_method']}。"
            f"不用于：{card['avoid_when']}。"
        )
    if not rows:
        return ""
    return (
        "以下只是条件性叙事技法，默认不启用。它们不能决定章节发生什么，也不能把普通矛盾改成公开辩论、"
        "连续拆台、围观合唱或流程核验；只有当前提纲本来就有相同场景且触发条件成立时才可局部借用。\n"
        + "\n".join(rows)
    )[:max(0, int(limit or 6500))]


def _build_style_semantic_vocabulary_context(style_reference, terms, limit=NOVEL_AI_CONTEXT_LIMIT):
    reference = str(style_reference or "").strip()
    terms = [str(term or "").strip() for term in terms if str(term or "").strip()]
    instruction = (
        "【任务】\n"
        "只针对下面列出的作者原生词语或习惯短语建立《词语义卡》，不得新增、删除、合并或替换词条。"
        "每个词条恰好一张卡，meaning必须写作者实际怎么用而不是字典释义；emotional_temperature写情绪温度；"
        "speaker_or_viewpoint写适合哪类人物说、内心独白还是贴近角色的旁白；use_when写自然适用场景；"
        "sentence_position写常落在句首、句中、动作后、对白落点等什么位置；natural_collocations写与动作、语气、"
        "称呼或前后句的自然搭配；avoid_when写会显得不合人物、不合情绪或误读意思的边界。"
        "source_evidence必须从完整原文逐字连续截取一段真实上下文，且必须包含该词，不得拼接、改写或补字。"
        "允许现代口语、粗口、饭圈词和网络词，它们不是污染；不要把所有词解释成搞笑或冲突用语。"
        "只输出合法JSON：{\"cards\":[{\"term\":\"\",\"meaning\":\"\",\"emotional_temperature\":\"\","
        "\"speaker_or_viewpoint\":\"\",\"use_when\":\"\",\"sentence_position\":\"\","
        "\"natural_collocations\":\"\",\"avoid_when\":\"\",\"source_evidence\":\"\"}]}。"
    )
    return "\n\n".join(part for part in (
        "【必须覆盖的词条】\n" + "、".join(terms),
        "【作者完整原文】\n" + reference,
        instruction,
    ) if part)[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]


def _build_style_voice_cards_context(style_reference, limit=NOVEL_AI_CONTEXT_LIMIT):
    instruction = (
        "【任务】\n"
        "从作者完整原文建立6至10张《角色与叙述声纹卡》。只提炼语言层：主视角旁白、主角说话、"
        "不同功能配角的说话方式、冲突中的接话节奏、日常口语和情绪表达。"
        "不得把连续拆台、围观合唱、反转、流程推进等剧情组织方法写成常驻声纹；也不得把任一声纹写成每章必须有笑点或对话。"
        "每卡必须给出owner、voice_features、use_when、avoid_when和逐字连续的source_evidence。"
        "只输出合法JSON：{\"cards\":[{\"id\":\"VC01\",\"title\":\"\",\"owner\":\"\","
        "\"voice_features\":\"\",\"use_when\":\"\",\"avoid_when\":\"\",\"source_evidence\":\"\"}]}。"
    )
    return "\n\n".join(("【作者完整原文】\n" + str(style_reference or "").strip(), instruction))[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]


def _build_style_technique_cards_context(style_reference, limit=NOVEL_AI_CONTEXT_LIMIT):
    instruction = (
        "【任务】\n"
        "从作者完整原文建立5至10张《条件性叙事技法卡》。这类卡只能记录在特定场景才可局部使用的组织办法，"
        "例如公开反应链、字面拆台、身份揭晓、喜剧反差、平台弹幕、危机急停等。"
        "每张必须把trigger写得具体，把avoid_when写得严格：普通情绪冲突、私人谈话、关系拉扯、日常推进默认不调用。"
        "技法卡绝不能成为章节模板，不能要求反复证明同一件事，不能把矛盾写成质问—否认—解释—再反驳的辩论流程。"
        "每卡给出逐字连续source_evidence。只输出合法JSON：{\"cards\":[{\"id\":\"TC01\",\"title\":\"\","
        "\"trigger\":\"\",\"use_method\":\"\",\"avoid_when\":\"\",\"source_evidence\":\"\"}]}。"
    )
    return "\n\n".join(("【作者完整原文】\n" + str(style_reference or "").strip(), instruction))[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]


def _build_style_runtime_voice_pack_context(voice_cards, technique_cards, limit=NOVEL_AI_CONTEXT_LIMIT):
    voices = _format_style_voice_cards(voice_cards, limit=9000)
    techniques = _format_style_technique_cards(technique_cards, limit=9000)
    instruction = (
        "【任务】\n"
        "根据声纹卡和条件技法卡，写一份1200至2200字的《V4运行时文风总则》。"
        "只写正文扩写时始终要遵守的语言原则、人物口吻区分、口语与叙述的关系、段落节奏边界，以及条件技法的默认关闭原则。"
        "不要复述任何原文剧情、人物名、专有物件或逐字证据；不要列出词表；不要把公开围观、连续拆台、反转或喜剧当成每章要求；"
        "明确普通冲突优先写人物目标、选择、关系变化和直接后果，避免证明链、办案流程和来回讲道理。直接输出运行时总则正文。"
    )
    return "\n\n".join(part for part in ("【角色与叙述声纹卡】\n" + voices if voices else "", "【条件性技法卡】\n" + techniques if techniques else "", instruction) if part)[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]


def _build_style_cards_context(style_reference, combined_sheet="", persona="", limit=NOVEL_AI_CONTEXT_LIMIT):
    reference = str(style_reference or "").strip()
    sheet = str(combined_sheet or "").strip()
    persona_text = str(persona or "").strip()
    categories = "、".join(STYLE_CARD_CATEGORIES)
    instruction = (
        "【任务】\n"
        "从作者原文中建立8至12张可跨小说复用的《功能型原文片段卡》。"
        f"分类只能使用：{categories}。八类都应覆盖；确无可靠片段时才允许少一类。"
        "每张卡的source_excerpt必须从【作者完整原文】中逐字连续截取，保留原段落和标点，"
        "不得改写、拼接、补字、纠错或省略；正文有效长度控制在220至700个中文字符。"
        "片段应完整展示一种写法怎样落地，不能只截一句金句，也不能依赖原文专有设定才能理解写法。"
        "use_when写适用场景，avoid_when写不适用边界，voice_features只写片段中可直接观察到的"
        "段落组织、惯用词、句式、对白停顿、说话标签、角色区分或收束方式。"
        "只输出合法JSON对象，不要Markdown或说明。结构："
        '{"cards":[{"category":"","title":"","use_when":"","avoid_when":"",'
        '"voice_features":"","source_excerpt":""}]}。'
    )
    parts = [
        f"【证据化作者写作档案】\n{sheet}" if sheet else "",
        f"【作者人格与语言声纹】\n{persona_text}" if persona_text else "",
        f"【作者完整原文】\n{reference}",
        instruction,
    ]
    return "\n\n".join(part for part in parts if part)[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]


def _format_style_cards(cards, limit=6500):
    normalized = _normalize_style_cards(cards)
    parts = []
    for card in normalized:
        parts.append(
            f"【{card['id']}｜{card['category']}｜{card['title']}】\n"
            f"功能维度：{STYLE_CARD_DIMENSIONS.get(card['category'], '叙述/场景')}\n"
            f"适用：{card.get('use_when', '')}\n"
            f"边界：{card.get('avoid_when', '')}\n"
            f"声纹观察：{card.get('voice_features', '')}\n"
            f"原文片段：\n{card.get('source_excerpt', '')}"
        )
    return "\n\n".join(parts)[:max(0, int(limit or 6500))]


def _style_mandatory_voice_cards(cards):
    # Original excerpts are conditional evidence, not per-chapter quotas.
    return []


def _style_cards_selected_by_plan(cards, style_plan, max_cards=3):
    normalized = _normalize_style_cards(cards)
    narrative_mode = _style_narrative_mode_from_plan(style_plan)
    requested = []
    for card_id in re.findall(
        r"(?<![A-Za-z0-9])SC\d{2}(?![A-Za-z0-9])",
        str(style_plan or ""),
        flags=re.IGNORECASE,
    ):
        card_id = card_id.upper()
        if card_id not in requested:
            requested.append(card_id)
    cards_by_id = {str(card.get("id", "") or "").upper(): card for card in normalized}
    selected = []
    selected_ids = {str(card.get("id", "") or "").upper() for card in selected}
    selected_dimensions = {
        dimension
        for dimension in (
            STYLE_CARD_DIMENSIONS.get(card.get("category", ""), "叙述/场景")
            for card in selected
        )
        if dimension == "对白"
    }
    selection_limit = max(1, int(max_cards or 1))
    for card_id in requested:
        card = cards_by_id.get(card_id)
        if not card or card_id in selected_ids:
            continue
        category = str(card.get("category", "") or "").strip()
        if category in STYLE_PROCEDURAL_CARD_CATEGORIES and narrative_mode != "调查推理":
            continue
        if (
            narrative_mode
            and category == "权威角色命令"
            and narrative_mode not in {"冲突推进", "动作危机", "调查推理"}
        ):
            continue
        if category == "群体反应" and narrative_mode not in {"冲突推进", "喜剧反差"}:
            continue
        if category == "日常口语与喜剧" and narrative_mode not in {"情绪关系", "喜剧反差"}:
            continue
        dimension = STYLE_CARD_DIMENSIONS.get(card.get("category", ""), "叙述/场景")
        if dimension in selected_dimensions:
            continue
        selected.append(card)
        selected_ids.add(card_id)
        selected_dimensions.add(dimension)
        if len(selected) >= selection_limit:
            break
    return selected


def _select_style_execution_cards(cards, chapter_context, max_cards=3):
    """Choose a few source-evidence cards for direct prose generation.

    This intentionally uses only broad scene cues. The cards are writing
    evidence, not a plot-routing system, so the selector must not turn every
    chapter into a procedural checklist.
    """
    normalized = _normalize_style_cards(cards)
    if not normalized:
        return []
    text = _compact_text(chapter_context).lower()
    investigation_terms = (
        "调查", "查证", "取证", "证据", "案件", "审问", "验尸", "化验",
        "鉴定", "线索", "嫌疑", "排查", "推理",
    )
    is_investigation = any(term in text for term in investigation_terms)
    available = [
        card for card in normalized
        if is_investigation or str(card.get("category", "") or "")
        not in STYLE_PROCEDURAL_CARD_CATEGORIES
    ]
    if not available:
        available = list(normalized)

    selected = []
    selected_ids = set()

    def choose(category):
        for card in available:
            card_id = str(card.get("id", "") or "").upper()
            if card_id in selected_ids:
                continue
            if str(card.get("category", "") or "") != category:
                continue
            selected.append(card)
            selected_ids.add(card_id)
            return True
        return False

    # Natural oral rhythm and individual dialogue are always useful evidence;
    # this does not require a joke or extra dialogue in the new chapter.
    choose("日常口语与喜剧")

    if any(term in text for term in ("害怕", "发抖", "哭", "求", "慌", "脸白", "惊恐")):
        choose("弱势与恐惧对白")
    elif any(term in text for term in ("命令", "警告", "冷声", "沉声", "吩咐", "不许", "滚")):
        choose("权威角色命令")
    else:
        choose("权威角色命令") or choose("弱势与恐惧对白")

    if any(term in text for term in ("不对", "异常", "忽然", "变了", "露出", "发现", "反常")):
        choose("异常逐步显形")
    elif any(term in text for term in ("众人", "所有人", "围观", "宾客", "人群", "大家")):
        choose("群体反应")
    elif is_investigation:
        choose("推理与解释")
    else:
        choose("章节收束")

    for card in available:
        if len(selected) >= max(1, int(max_cards or 1)):
            break
        card_id = str(card.get("id", "") or "").upper()
        if card_id in selected_ids:
            continue
        selected.append(card)
        selected_ids.add(card_id)
    return selected[:max(1, int(max_cards or 1))]


def _style_narrative_mode_from_plan(style_plan):
    text = str(style_plan or "")
    match = re.search(
        r"(?:主叙事模式|本章主模式)\s*[:：｜|]\s*(冲突推进|情绪关系|动作危机|喜剧反差|信息揭示|调查推理)",
        text,
    )
    return match.group(1) if match else ""


def _style_narrative_mode_contract(output_target=0, narrative_mode=""):
    try:
        target = max(1000, int(output_target or 2000))
    except Exception:
        target = 2000
    normal_budget = min(400, max(120, round(target * 0.08)))
    investigation_budget = min(700, max(220, round(target * 0.16)))
    mode = narrative_mode if narrative_mode in STYLE_NARRATIVE_MODES else ""
    mode_text = (
        f"本章已确定主叙事模式为“{mode}”，终稿不得被题材名词带偏到其他模式。"
        if mode else
        "先从冲突推进、情绪关系、动作危机、喜剧反差、信息揭示、调查推理中只选一个主叙事模式。"
        "判断依据是本章主要靠什么让读者继续看，不是场景中出现了医院、公司、警察、证据或专业人物。"
    )
    return (
        "【叙事动力与解释预算】\n"
        + mode_text
        + "剧情吸引力优先级为：人物反应与冲突、新结果、悬念、必要解释、流程完整性。"
        "先写人物作出决定、遭遇阻力或看到结果，再补读者此刻非知道不可的最短原因；"
        "读者从动作、结果和上下文已经能推断的内容必须留白，不能由旁白和角色换一种说法再讲一遍。"
        f"非调查推理模式全章用于机制、因果和流程说明的文字总量以{normal_budget}字为上限，"
        "集中判断最多一段、每次不超过两句；不要求写满额度。"
        f"调查推理模式的说明总量也以{investigation_budget}字为上限，最多两段集中推理；"
        "只保留会改变人物下一步行动或结论的验证，不追求现实流程完整。"
        "任何模式都不得为显得严谨而自行增加提纲没有要求的封签编号、分样、审批、交接、见证、记录固定、责任划分或多轮复核。"
        "专业步骤若不影响本章转折、后续伏笔或人物选择，合并为一句结果；同一判断只能由最合适的人完整说一次。"
    )


def _build_style_profile_units(style_reference, max_units=10, target_chars=2400):
    reference = str(style_reference or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not reference:
        return []
    paragraphs = _style_text_structure(reference)["paragraphs"]
    if not paragraphs:
        return []
    target = max(1800, int(target_chars or 3600))
    blocks = []
    current = []
    current_chars = 0
    for paragraph in paragraphs:
        length = len(_compact_text(paragraph))
        if current and current_chars >= target:
            blocks.append("\n\n".join(current))
            current = []
            current_chars = 0
        current.append(paragraph)
        current_chars += length
    if current:
        blocks.append("\n\n".join(current))

    limit = max(1, min(10, int(max_units or 10)))
    if len(blocks) <= limit:
        selected_indices = list(range(len(blocks)))
    else:
        selected_indices = []
        for index in range(limit):
            source_index = round(index * (len(blocks) - 1) / max(1, limit - 1))
            if source_index not in selected_indices:
                selected_indices.append(source_index)
    return [
        {
            "id": index + 1,
            "source_index": source_index + 1,
            "source_total": len(blocks),
            "source": blocks[source_index].strip(),
            "baseline": "",
            "sheet": "",
        }
        for index, source_index in enumerate(selected_indices)
        if blocks[source_index].strip()
    ]


def _build_style_baseline_context(unit, unit_index=0, unit_total=0):
    item = unit if isinstance(unit, dict) else {}
    source = str(item.get("source", "") or "").strip()
    number = int(unit_index or item.get("id", 0) or 1)
    total = int(unit_total or 1)
    return (
        f"【样本单元】\n第{number}/{total}个\n\n"
        f"【作者原文】\n{source}\n\n"
        "【任务】\n"
        "在人物、事件、信息、先后顺序、叙事人称和大致篇幅不变的前提下，把上文改写成没有鲜明个人特征的普通中文小说写法。"
        "这是一篇用于对照分析的基准稿，不要追求模仿原作者，不要保留原文独特句式、段落节奏、修辞、重复用词和对白组织。"
        "不得新增、删减或改换剧情，不得总结，不得输出标题、说明或分析，只输出完整基准正文。"
    )[:NOVEL_AI_CONTEXT_LIMIT]


def _build_style_sheet_context(unit, unit_index=0, unit_total=0):
    item = unit if isinstance(unit, dict) else {}
    source = str(item.get("source", "") or "").strip()
    baseline = str(item.get("baseline", "") or "").strip()
    number = int(unit_index or item.get("id", 0) or 1)
    total = int(unit_total or 1)
    return (
        f"【样本单元】\n第{number}/{total}个，证据编号[{number}]\n\n"
        f"【作者原文】\n{source}\n\n"
        f"【普通作者基准稿】\n{baseline}\n\n"
        "【任务】\n"
        "对比两篇内容相同的正文，只提取作者原文区别于普通基准稿的稳定写作行为。"
        "按以下六类输出《单元作者写作档案》：剧情组织、创意与处理手法、人物与场景展开、"
        "叙述用词与句法声纹、对白声纹、格式节奏与收束。"
        "每条必须依次写明：可跨剧情复用的具体行为、适用场景、本单元出现层级（高频/多次/偶发）、"
        "作者原文中的逐字证据和不适用边界；证据末尾标注当前编号。"
        "叙述用词与句法声纹必须识别真实反复出现的句首、连接词、判断词、动作修饰词、生理反应短语、"
        "感官与颜色词、解释框架、强调框架、说话标签和拟声词，不得只写‘语言简洁’等空泛评价。"
        "对白声纹必须识别对白长短、停顿、结巴、省略、重复称呼、语气词、反问、接话方式、"
        "对白前后插入动作的方式，以及主角、权威者、弱势者、对手、专业解释者、喜剧角色等功能角色的可迁移说话模式。"
        "重点比较原文和基准稿：哪些词作者会反复原样使用而不换同义词，哪些句式和说话方式是原文独有。"
        "排除人物名、专有设定名、当前情节名词、只出现一次的偶然措辞，以及异常空格、异形字符、断词和错误标点。"
        "不要提出通用优秀写作建议，不要美化作者真实存在的直白、重复、长段或慢铺陈。"
        "同一结论不要跨分类重复；没有可靠证据的项目跳过。每类最多保留4条，优先保留跨剧情可复用、"
        "最能区别普通基准稿的行为；词组清单和句式框架可以集中写在同一条内，不得因限长省略。"
        "全文控制在3800至4800个中文字符，直接输出结构化档案，不输出分析过程。"
    )[:NOVEL_AI_CONTEXT_LIMIT]


def _build_style_sheet_merge_context(previous_sheet, current_sheet, current_index=0, unit_total=0):
    previous = str(previous_sheet or "").strip()
    current = str(current_sheet or "").strip()
    return (
        f"【合并进度】\n正在合并第{int(current_index or 2)}/{int(unit_total or 2)}个样本单元。\n\n"
        f"【此前合并档案】\n{previous}\n\n"
        f"【当前单元档案】\n{current}\n\n"
        "【任务】\n"
        "生成新的《合并作者写作档案》。保持六类：剧情组织、创意与处理手法、人物与场景展开、"
        "叙述用词与句法声纹、对白声纹、格式节奏与收束。"
        "近乎相同的结论才能合并；侧重点、适用场景或角色功能不同的结论必须分别保留。"
        "同一行为在多个单元出现时，合并其证据编号并标记稳定度：4个及以上单元为高频，2-3个单元为稳定，1个单元为局部。"
        "每条保留行为、适用场景、稳定度、最多三段最直接的逐字证据和不适用边界。"
        "叙述用词与句法声纹必须保留可直接执行的词组清单及句式框架；对白声纹必须保留全局口语习惯和不同功能角色的说话模式。"
        "每类最多6条，优先保留跨单元反复出现、最能区别普通写法、对仿写最有控制力的行为。"
        "删除矛盾、空泛、仅与题材或人物有关、只靠单个专有名词成立或无法由证据支持的结论。"
        "不得为了篇幅删除此前档案中仍然独特且有证据的习惯词、句式或对白声纹。"
        "词组清单、句式框架和角色对白机制可以集中写在对应条目内。全文控制在4800至6000个中文字符，"
        "直接输出完整的新档案，不输出分析过程、合并说明或Markdown代码块。"
    )[:NOVEL_AI_CONTEXT_LIMIT]


def _build_style_persona_context(combined_sheet):
    sheet = str(combined_sheet or "").strip()
    return (
        f"【最终作者写作档案】\n{sheet}\n\n"
        "【任务】\n"
        "把档案转成供小说模型长期扮演的《作者人格与语言声纹契约》。使用第二人称，必须依次包含六个标题："
        "【剧情组织人格】【人物与场景人格】【叙述习惯词与句法声纹】【对白总体声纹】"
        "【功能角色说话方式】【格式节奏与使用边界】。"
        "叙述声纹必须保留高频、稳定、局部三个层级的惯用词组和句式框架，并写清各自在什么场景使用、"
        "什么情况下不能使用；不得把所有词堆进每一章。"
        "对白声纹必须写清对白长度、停顿、省略、结巴、称呼、语气词、反问、接话、说话标签及对白与动作的衔接方式。"
        "功能角色至少覆盖主角、权威或专业角色、弱势或恐惧角色、对手、喜剧或口语角色；这些是说话机制，不得带入原文人物和剧情。"
        "只描述这位作者实际怎样写，保留其不工整、直白、重复、解释性叙述、长短段和慢快节奏等真实倾向。"
        "不要提到档案、证据、样本、基准稿或分析过程，不要加入通用商业网文规则，不要写具体人物、设定和剧情。"
        "控制在2200至3200个中文字符，直接输出人格与声纹契约正文。"
    )[:NOVEL_AI_CONTEXT_LIMIT]


def _build_style_rules_context(original_context, combined_sheet, persona, style_reference, limit=NOVEL_AI_CONTEXT_LIMIT):
    original = str(original_context or "").strip()
    sheet = str(combined_sheet or "").strip()
    persona_text = str(persona or "").strip()
    reference = str(style_reference or "").strip()
    excerpts = _select_style_reference_excerpts(reference, original, 8000) if reference else ""
    instruction = (
        "【任务】\n"
        "根据当前章节的剧情资料，从作者写作档案中选择真正适用于本章的写法，生成《本章文风执行规则》。"
        "规则必须覆盖剧情组织、场景推进、人物反应、信息揭示、叙述习惯词、句式框架、"
        "对白总体声纹、当前人物各自的说话方式、格式节奏和章节收束；每条都要能让正文模型直接执行。"
        "必须列出本章适用的高频/稳定惯用词和句式，以及本章不适用、不得硬塞的词；"
        "必须把角色卡中的语言方式与作者的功能角色声纹结合，不能让所有人物说成同一种口气。"
        "不要改变、增删或重新安排当前章节既定剧情，不要把参考片段的角色、设定、物件或原句带入新正文。"
        "必须明确本章应沿用的原文手法和应抑制的模型默认写法，但不要输出剧情提纲。"
        "控制在1600至3000个中文字符，只输出规则正文。"
    )
    fixed = [
        f"【作者写作档案】\n{sheet}" if sheet else "",
        f"【作者人格】\n{persona_text}" if persona_text else "",
        f"【与本章写作功能接近的原文证据】\n{excerpts}" if excerpts else "",
        instruction,
    ]
    fixed_length = sum(len(part) + 2 for part in fixed if part)
    original_budget = max(0, int(limit or NOVEL_AI_CONTEXT_LIMIT) - fixed_length)
    if len(original) > original_budget:
        original = _clip_context_text(original, original_budget, keep_tail=False, preserve_lines=True)
    return "\n\n".join(part for part in [f"【当前章节资料】\n{original}"] + fixed if part)[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]


def _compose_style_profile(combined_sheet, persona, chapter_rules=""):
    parts = []
    sheet = str(combined_sheet or "").strip()
    persona_text = str(persona or "").strip()
    rules = str(chapter_rules or "").strip()
    if persona_text:
        parts.append("【作者人格】\n" + persona_text)
    if sheet:
        parts.append("【证据化作者写作档案】\n" + sheet)
    if rules:
        parts.append("【本章文风执行规则】\n" + rules)
    return "\n\n".join(parts)


_STYLE_LAYOUT_METRIC_LABELS = (
    "段落节奏",
    "长短段分布",
    "段落功能分布",
    "常见段落衔接",
    "段落节奏骨架",
    "完整样本结构软参考",
    "完整样本本地结构目标",
    "输出前结构防漂移检查",
)

_STYLE_LAYOUT_METRIC_MARKERS = (
    "每1000字",
    "每千字",
    "非空段",
    "15字以内",
    "35字以内",
    "80字以上",
    "短对白",
    "对白轮数",
    "段落密度",
    "短段比例",
    "短段占比",
    "短句数",
    "段落长度中位数",
    "句子长度中位数",
    "中心区间",
    "强调短段约",
)


def _remove_style_layout_metrics(value):
    """Delete paragraph/layout metrics while preserving voice and vocabulary."""
    text = str(value or "").strip()
    if not text:
        return ""
    kept = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            kept.append(raw_line)
            continue
        if any(label in line for label in _STYLE_LAYOUT_METRIC_LABELS):
            continue
        if any(marker in line for marker in _STYLE_LAYOUT_METRIC_MARKERS):
            continue
        if (
            ("段落" in line or "短段" in line or "短句" in line)
            and re.search(r"\d|%|％|约|占比|中位数|中心区间", line)
        ):
            continue
        kept.append(raw_line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()

def _style_generation_issue_text(reasons):
    lines = []
    for reason in reasons or []:
        text = str(reason or "").strip()
        if not text:
            continue
        if any(key in text for key in ("段落密度", "短段比例", "中长段", "短对白", "对白轮数", "对白比例", "对白字数占比")):
            if "对白" in text:
                text = "对白与叙述衔接读感漂移：无必要台词或功能性问答偏多，需要减少重复确认。"
            elif "中长段" in text:
                text = "叙述承载不足：必要信息被过度碎片化，需要自然合并成完整表达。"
            else:
                text = "自然排版读感向短碎方向漂移：无效碎片、功能性问答或同义复述偏多。"
        lines.append("- " + text)
    return "\n".join(lines) or "- 本地读感检测无硬性问题"


def _style_runtime_profile(profile_text, style_reference="", include_structure=True):
    """Keep language identity always-on while making plot methods conditional."""
    text = str(profile_text or "").strip()
    if not text:
        return ""
    text = re.sub(
        r"(?ms)^【剧情组织人格】\s*.*?(?=^【[^\n】]+】\s*$|\Z)",
        "",
        text,
    ).strip()
    # Archive prose often uses broad frequency labels without measuring the
    # whole sample. Keep the described technique and vocabulary, but remove
    # wording that the writing model can misread as a per-chapter quota.
    for source, replacement in (
        ("你大量把", "你只在需要重音时把"),
        ("你大量使用", "你会按场景使用"),
        ("你高频让", "你会在场景需要时让"),
        ("你高频使用", "你会按场景使用"),
        ("你高频用", "你会按场景用"),
        ("高频使用", "可使用"),
        ("规则和解释高频", "规则和解释中可"),
        ("对白总体偏短、偏口语", "对白允许短句和口语"),
        ("对白整体偏短、偏口语", "对白允许短句和口语"),
    ):
        text = text.replace(source, replacement)
    if not include_structure:
        text = _remove_style_layout_metrics(text)
    reference_structure = _style_text_structure(style_reference)
    distribution = ""
    if include_structure and reference_structure["chars"] >= 500:
        distribution = (
            f"当前完整样本实际分布：每1000字约"
            f"{reference_structure['paragraphs_per_1000']:.1f}个非空段，"
            f"15字以内短段约占{reference_structure['short_paragraph_pct']:.0f}%，"
            f"对白字数约占{reference_structure['dialogue_char_pct']:.0f}%，"
            f"每1000字约{reference_structure['dialogue_turns_per_1000']:.1f}轮对白。"
        )
    if include_structure:
        boundary = (
            "【运行时文风边界｜高于档案中的宽泛习惯】\n"
            + distribution
            + "档案中的‘大量、高频、常用、经常、偏短、偏多’只说明这种写法出现时的形态或相对辨识度，"
            "不能决定它在单章出现多少；频率、段落结构和对白总量一律以完整样本实际分布为准。"
            "每章常驻的只有作者惯用词、句法松紧、动作与反应词、说话标签、对白长短与停顿、称呼语气和人物接话方式。"
            "推理链、反复验证、群体同步反应、误读布局、喜剧反差、危机升级、专业排除和等待揭露都属于条件性剧情手法，"
            "只有当前提纲确实需要且符合片段卡适用边界时才能调用；不得为了证明文风相似而增加对应场面。"
            "档案中‘你习惯、常用、会用、高频’等表述不构成每章配额。日常口语指人物自然的词序、称呼、语气词和停顿，"
            "不等于每章必须讲笑话；严肃、危险或情绪落点允许全章没有喜剧。"
            "剧情准确、人物自然反应和当前场景适配高于任何单项写法手法。"
        )
    else:
        boundary = (
            "【运行时文风边界｜段落排版指标已删除】\n"
            "正文生成阶段只接收作者惯用词、句法松紧、动作与反应词、说话标签、称呼语气、人物接话方式和场景适配边界。"
            "档案中的‘大量、高频、常用、经常、偏短、偏多’只说明这种写法出现时的形态或相对辨识度，"
            "不能决定它在单章出现多少，也不能把全章写成统一节拍。"
            "推理链、反复验证、群体同步反应、误读布局、喜剧反差、危机升级、专业排除和等待揭露都属于条件性剧情手法，"
            "只有当前提纲确实需要且符合片段卡适用边界时才能调用；不得为了证明文风相似而增加对应场面。"
            "日常口语指人物自然的词序、称呼、语气词和停顿，不等于每章必须讲笑话；严肃、危险或情绪落点允许全章没有喜剧。"
            "剧情准确、人物自然反应和当前场景适配高于任何单项写法手法。"
        )
    return "\n\n".join(part for part in (boundary, text) if part)


def _append_ai_style_profile_to_context(context, profile_text, limit=NOVEL_AI_CONTEXT_LIMIT):
    original = str(context or "").strip()
    profile = str(profile_text or "").strip()
    if not profile:
        return original[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]
    profile_block = f"【AI文风画像】\n{profile}"
    marker = "【风格锁定规则】"
    position = original.find(marker)
    if position >= 0:
        head = original[:position].rstrip()
        tail = original[position:].lstrip()
        available = int(limit or NOVEL_AI_CONTEXT_LIMIT) - len(profile_block) - len(tail) - 4
        if available <= 0:
            head = ""
        elif len(head) > available:
            head = _clip_context_text(head, available, keep_tail=False, preserve_lines=True)
        return "\n\n".join(part for part in (head, profile_block, tail) if part)[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]
    available = max(0, int(limit or NOVEL_AI_CONTEXT_LIMIT) - len(profile_block) - 2)
    return "\n\n".join(part for part in (original[:available], profile_block) if part)[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]


def _style_execution_beat_range(context):
    target = _style_output_target_from_context(context)
    if target <= 0:
        return 5, 9
    if target <= 2500:
        return 4, 7
    if target <= 5000:
        return 6, 10
    if target <= 10000:
        return 8, 14
    return 10, 18


def _style_execution_structure_contract(style_reference, context):
    structure = _style_text_structure(style_reference)
    if structure["chars"] < 500:
        return ""
    density = float(structure["paragraphs_per_1000"] or 0)
    short_pct = float(structure["short_paragraph_pct"] or 0)
    single_short_pct = float(structure["single_sentence_short_paragraph_pct"] or 0)
    dialogue_pct = float(structure["dialogue_char_pct"] or 0)
    median = max(1, int(structure["paragraph_median"] or 1))
    target = _style_output_target_from_context(context)
    bands = _style_centered_structure_bands(structure, target)
    noun_short_limit = max(2, round(max(2000, target or 2000) / 1000))
    lines = [
        "以下数字来自完整样本，是防止多项同时向短碎方向漂移的中心区间，不是逐项配额；低于下限时不得补对白、笑点、动作或拆段：",
        f"- 每1000字非空段落中心区间为{bands['density_low']:.1f}-{bands['density_high']:.1f}段；段落长度中位数可参考{max(1, median - 8)}-{median + 8}字。",
        f"- 15字以内短段占比中心区间为{bands['short_pct_low']:.0f}%-{bands['short_pct_high']:.0f}%。",
        f"- 非对白35字以内单句短段占比可参考{max(0, single_short_pct - 15):.0f}%-{min(100, single_short_pct + 15):.0f}%。",
        f"- 对白字数占比中心区间为{bands['dialogue_pct_low']:.0f}%-{bands['dialogue_pct_high']:.0f}%；人物没必要开口时直接用叙述，不为比例制造问答。",
        (
            f"- 按本章篇幅，对白约{bands['dialogue_turn_low']}-{bands['dialogue_turn_high']}轮，"
            f"其中15字以内短对白约{bands['short_dialogue_turn_low']}-{bands['short_dialogue_turn_high']}轮；"
            "下限只供观察，绝不能为了数量增加台词。"
            if target and bands["dialogue_turn_high"] else
            "- 对白轮数和短对白轮数按完整样本密度控制；不为数量增加台词。"
        ),
        f"- 普通对象名、操作名、阴性结果不得独立成段；约本章篇幅最多保留{noun_short_limit}个非对白名词独段，只留给真正改变认知的首次命名。",
        "- 连续3个及以上普通非对白短段应合并；真正的转折、对白、打断和样本式强调不为统计强行合并。",
        "- 同一人物相邻的两句短对白若每句都不超过15字，必须合成一个对白段，或用承担反应/操作的动作标签连接；只有结巴、打断、裁决和样本明确的命令递进可以分开。",
        "- 段落密度、短段、对白占比、对白轮数、短对白轮数中有两项以上同时超过中心区间时，必须整体减少无效换行和功能性问答。",
    ]
    return "\n".join(lines)


def _style_repetition_boundary_text():
    return (
        "文风中的重复必须区分用途：保留关键词强调、对白回环、情绪递进、悬念停顿和结论落点等修辞性重复；"
        "删除没有新增动作、信息、决定、后果或情绪转折的同义复述。"
        "同一事实、规则、因果或证据边界原则上只完整说明一次；前文已经说明后，只有出现新证据、新决定或新后果时才能再次提及，"
        "并应直接写新增部分，不重新讲完整背景。"
        "每个核心结论必须指定一个信息所有者和一次完整揭示：由最合适的人物、行动结果或旁白其中之一承担，其他人物只能给出"
        "会推动下一步的质疑、反应、决定或后果，不能换一种说法复述；人物已经说清后，旁白不得再补‘真正危险在于’、"
        "‘这意味着’、‘不是A而是B’之类总结，旁白已经交代后也不得安排角色复述给读者。"
        "依赖检测、调查、拆封、来电或人物揭晓才能确认的答案，在结果出现前只能写可观察异常和立即行动，不能提前把完整因果说完，"
        "再让结果或专业人物重复认证。专业结论出现时，把发现与必要后果合并为一次自然表达，下一段立即进入人物决定、冲突或新结果。"
        "采购、核验、经手、审批、保管、运输等路径若不是本章核心冲突，必须压成一段人物化叙述或一句结果；"
        "不得用连续短问短答把流程逐项盘完，也不得在叙述列举后再让人物逐项复问。"
        "章节提纲只提供当前剧情方向，不是专业信息补全任务；提纲只概括为部分资金、相关主体、一次确认或一轮回应时，"
        "不得为了显得专业而自行补出多组精确金额、持股比例、文件名、时间戳、合同数量、界面字段或完整机构流程。"
        "只有会直接改变人物选择、关系、代价或章末结果的一项代表性细节可以具体落地，其余直接写结果。"
        "目标篇幅仍有余量时，优先展开人物取舍、关系后果、情绪共鸣和场景中的具体生活痕迹，不能追加查账、举证、核验或处置步骤补字数。"
        "状态快照、人物卡、设定、伏笔和关键事实是静默连续性约束，不是需要角色用对白或旁白逐条证明已经记住的正文任务。"
        "同一人物连续出现多个同义反应时只保留最有力度且会影响下一步行动的一个；多人反应相同时用一个代表性反应或群体结果承接。"
        "上一章结尾原文是已经向读者发布的边界，不是本章可以复用的起笔素材；章节开篇不得原样或同义重写上一章的末句、"
        "对白、声音、动作落点、结论或情绪。上一章以对白结束时，从听者的新反应或新回答开始；以动作结束时，从动作造成的"
        "新结果或新阻力开始；以声音结束时，从声源揭示或人物听见后的新反应开始。只从上一章章末未完成状态继续，"
        "并让第一段出现新动作、新信息、新决定、新后果或必要情绪转折。普通说明不得连续拆成大量只有一句话的短段；"
        "短段只在样本对应的强调、对白、转折或节奏落点上使用。"
        "跨越半日以上、跨城或跨线路以后，同一人物再次出场时，必须用一句简洁的时间、地点或行程过渡交代其位置变化；"
        "不能让人物从上一场景直接无说明地出现在另一座城或另一条线路。"
        "以上边界高于文风画像中对‘真实重复’或‘解释充分’的宽泛描述，但不得删除样本真实存在的强调节奏和有意回环。"
    )


def _style_cjk_ngrams(value, min_length=3, max_length=8):
    text = _compact_text(value)
    result = set()
    low = max(2, int(min_length or 3))
    high = max(low, int(max_length or 8))
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        if len(run) < low:
            continue
        for size in range(low, min(high, len(run)) + 1):
            for start in range(0, len(run) - size + 1):
                result.add(run[start:start + size])
    return result


def _style_profile_extracted_phrases(profile_text, style_reference):
    profile = str(profile_text or "")
    reference_compact = _compact_text(style_reference)
    evidence_marker = "【证据化作者写作档案】"
    if evidence_marker in profile:
        persona = profile.split(evidence_marker, 1)[0].strip()
        if len(_compact_text(persona)) >= 80:
            profile = persona
    voice_marker = "【叙述习惯词与句法声纹】"
    if voice_marker in profile:
        profile = profile.split(voice_marker, 1)[1]
    meta_phrases = {
        "人物", "对象", "动作", "状态", "判断", "变化", "反应", "场景",
        "信息", "身份", "地点", "目标", "任务", "完成", "猜出", "成为",
        "我们", "就在", "之际",
    }
    phrases = []
    seen = set()
    for raw in re.findall(r'[“「『"]([^”」』"\n]{1,240})[”」』"]', profile):
        list_like = bool(re.search(r"[／/、，,；;＋+…]", raw))
        if list_like:
            candidates = []
            for part in re.split(r"[／/、，,；;]", raw):
                part = re.split(r"[＋+]", part, maxsplit=1)[0]
                candidates.extend(re.findall(r"[\u3400-\u9fff]+", part))
        else:
            candidates = [_compact_text(raw).strip("。！？!?：:；;，,、…—- ")]
        for phrase in candidates:
            phrase = _compact_text(phrase)
            if (
                2 <= len(phrase) <= 8
                and re.fullmatch(r"[\u3400-\u9fff]+", phrase)
                and phrase in reference_compact
                and phrase not in meta_phrases
                and phrase not in seen
            ):
                seen.add(phrase)
                phrases.append(phrase)
    return phrases


def _style_native_vocabulary_text(
    profile_text,
    style_reference,
    limit=120,
    output_target=0,
):
    phrases = _style_profile_extracted_phrases(profile_text, style_reference)
    phrases = phrases[:max(1, int(limit or 120))]
    if not phrases:
        return ""
    reference = _compact_text(style_reference)
    reference_chars = max(1, len(reference))
    target_chars = max(0, int(output_target or 0))
    tiers = {"high": [], "medium": [], "low": []}
    for phrase in phrases:
        count = reference.count(phrase)
        rate_per_10000 = count * 10000 / reference_chars
        item = f"{phrase}×{count}"
        if target_chars:
            expected = count * target_chars / reference_chars
            soft_upper = min(count, max(1, int(math.ceil(expected + 0.5))))
            item += f"（约{target_chars}字单章通常0-{soft_upper}次）"
        if count >= 2 and rate_per_10000 >= 3:
            tiers["high"].append(item)
        elif count >= 2 and rate_per_10000 >= 1:
            tiers["medium"].append(item)
        else:
            tiers["low"].append(item)
    rows = []
    for label, key in (
        ("高复现原词", "high"),
        ("中复现原词", "medium"),
        ("低频场景词", "low"),
    ):
        items = tiers[key]
        if not items:
            continue
        rows.append(label + "：" + "、".join(items))
    return (
        f"以下{len(phrases)}项均由约{reference_chars}字当前文风样本实际提取，词后×N是它在完整样本中的实际出现次数。"
        "次数只用于还原相对密度，不是每章配额；不能因为档案把一组词概括为高频，就把组内每个词都当成高频。"
        "高复现原词可在语义适用时稳定沿用，中复现原词按场景选择，低频场景词只在语义、人物和情绪真正吻合时使用，"
        "不能把低频词变成每章固定口头禅、转折标签或人物反应。任何一项的正文密度都不得明显高于完整样本。"
        "这些词都是可主动使用的作者原生口语、习惯词和惯用短语。"
        "正文遇到语义相同或接近的模型默认表达时，优先保留这些原词，不为追求词汇变化改成更工整、书面或常见的AI措辞。"
        "现代口语和网络词不因故事时代背景自动书面化；可用于具有现代认知人物的对白、心理和贴近其视角的叙述。"
        "每章按人物、语义和情绪自然选用，不设最低数量、不轮换打卡，也不为使用某个词新增对白、笑点或剧情。"
        + (
            "括号内是按本章目标篇幅换算的软密度上沿，不是禁词或硬配额；真正必要的修辞回环允许自然多一次，"
            "但不得让同一个低频词、动作标签或判断短语在一章内反复承担相同功能。"
            if target_chars else ""
        )
        + "含样本人物名或专有称呼的短语只能借用句式结构，必须替换为当前小说人物，严禁带入样本人物和事件。\n"
        + "\n".join(rows)
    )


def _style_recent_vocabulary_usage_text(
    project,
    chapter_index,
    profile_text,
    style_reference,
    window=3,
    limit=12,
):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", [])
    chapters = chapters if isinstance(chapters, list) else []
    try:
        current_index = max(0, int(chapter_index or 0))
    except Exception:
        current_index = 0
    phrases = _style_profile_extracted_phrases(profile_text, style_reference)
    if not phrases or current_index <= 0:
        return ""

    recent = []
    for index in range(min(current_index, len(chapters)) - 1, -1, -1):
        chapter = chapters[index] if isinstance(chapters[index], dict) else {}
        body = str(chapter.get("text", "") or "").strip()
        if not body:
            continue
        recent.append((index, _compact_text(body)))
        if len(recent) >= max(1, int(window or 3)):
            break
    recent.reverse()
    if not recent:
        return ""

    reference = _compact_text(style_reference)
    reference_chars = max(1, len(reference))
    recent_chars = max(1, sum(len(body) for _, body in recent))
    rows = []
    for phrase in phrases:
        sample_count = reference.count(phrase)
        chapter_counts = [body.count(phrase) for _, body in recent]
        recent_count = sum(chapter_counts)
        if sample_count <= 0 or recent_count <= 0:
            continue
        density_ratio = recent_count * reference_chars / (sample_count * recent_chars)
        detail = "、".join(
            f"第{index + 1}章{count}次"
            for (index, _), count in zip(recent, chapter_counts)
            if count
        )
        rows.append((
            density_ratio,
            recent_count,
            phrase,
            f"{phrase}：完整样本{sample_count}次/{reference_chars}字；"
            f"最近{len(recent)}章{recent_count}次/{recent_chars}字（{detail}），"
            f"单位字数密度约为样本的{density_ratio:.1f}倍",
        ))
    if not rows:
        return ""
    rows.sort(key=lambda item: (-item[0], -item[1], item[2]))
    selected = rows[:max(1, int(limit or 12))]
    start = recent[0][0] + 1
    end = recent[-1][0] + 1
    return (
        f"以下是已完成第{start}-{end}章对作者原生用词的实际使用统计，只用于校准近期累计密度。"
        "它不是禁词表，不设置单词使用上限、连续章节限制、冷却、轮换或最低使用数量。"
        "任何词在人物、语义和情绪最贴切时仍可自然使用；若某词近期密度明显高于完整样本，"
        "只在存在同样自然的作者原词或普通表达时优先减少重复，不能机械替换，也不能为降密度改坏人物口吻。"
        "未列出的词只是最近这些章节没有出现，不代表必须补用。\n"
        + "\n".join(item[3] for item in selected)
    )


def _mandatory_style_voice_contract(style_cards=None):
    return (
        "【常驻人物语言声纹｜每章静默执行】\n"
        "常驻的是实际说话人物各自的对白长短、停顿、省略、称呼、语气词、接话方式和动作标签，不是固定剧情场面。"
        "人物开口时必须保持彼此可区分，不得统一写成准确、克制、完整的标准工作句；人物没有必要开口时，不得为了展示声纹新增对白。"
        "日常口语指符合身份的自然词序、称呼、语气和不完整句，不等于必须出现笑话、误读或俏皮话。"
        "质疑、拒绝、反驳、群体反应和喜剧反差只有当前提纲本来存在相应冲突且场景适用时才写，不设次数、不要求两轮接话，也不单独制造反应来验收。"
        "功能型原文片段卡全部按适用与禁用边界选择；没有真正匹配的卡时不选。"
    )


def _ensure_mandatory_style_voice_plan(style_plan):
    plan = str(style_plan or "").strip()
    if not plan or "常驻人物语言声纹" in plan:
        return plan
    return plan + "\n\n" + _mandatory_style_voice_contract()


def _build_legacy_style_execution_context(
    original_context,
    profile_text="",
    style_cards=None,
    style_reference="",
    project=None,
    chapter_index=0,
    limit=NOVEL_AI_CONTEXT_LIMIT,
    vocabulary_profile_text="",
):
    original = _append_ai_style_profile_to_context(
        original_context,
        _style_runtime_profile(profile_text, style_reference, include_structure=False),
        limit=limit,
    )
    beat_low, beat_high = _style_execution_beat_range(original)
    output_target = _style_output_target_from_context(original)
    optional_card_high = 1
    mandatory_voice_contract = _mandatory_style_voice_contract(style_cards)
    narrative_mode_contract = _style_narrative_mode_contract(output_target)
    short_noun_limit = max(2, round(max(2000, output_target or 2000) / 1000))
    cards_text = _format_style_cards(style_cards, limit=6500)
    structure_contract = _style_execution_structure_contract(style_reference, original)
    native_vocabulary = _style_native_vocabulary_text(
        vocabulary_profile_text or profile_text,
        style_reference,
        output_target=output_target,
    )
    recent_vocabulary = _style_recent_vocabulary_usage_text(
        project,
        chapter_index,
        vocabulary_profile_text or profile_text,
        style_reference,
    )
    instruction = (
        "【剧情执行稿任务】\n"
        "本次先完成剧情执行，不交付最终正文。必须严格执行当前章节提纲、前文连续性、人物与设定边界和结尾要求。"
        "先把人物任务、主线任务、本章目标、必须发生、冲突转折和结尾钩子中指向同一件事的内容合并，"
        "不要因为它们使用了不同字段名就拆成多个事件。‘必须发生’优先保留，其他字段只补足动机、阻力、结果和边界。"
        "‘必须发生’及本章目标中用顿号、‘和’、‘并’、‘后’串联的每个观察、动作、发现和结果都属于硬情节成分；"
        "可以合并到同一个拍点，但不得因合并同义任务而漏掉其中任何一项，也不得用最终结论代替前置观察或触发动作。"
        f"再把本章整理成{beat_low}-{beat_high}条按发生顺序排列的唯一剧情拍点；"
        "每条必须带来新动作、新信息、新决定、新后果或必要的情绪转折，不能把同一场对话、同一规则或同一反应拆成多条。"
        "拍点代表一次场景转折，不代表一条线索、一个核验步骤或一轮问答；同一场景里的触发、阻力、人物回应、"
        "必要验证和结果必须尽量合并在同一拍点内。证据链中的多个观察可以作为同一转折的内部细节，"
        "不得为了逐项验收把它们拆成教程式步骤。"
        "如上下文存在上一章已发布结尾，拍点1必须以‘章首新增变量：’开头，明确写出本章第一个新反应、新结果、新阻力或新信息；"
        "上一章的末句、触发声、动作落点或同义复述不能算本章拍点。没有上一章已发布正文时，按正常拍点格式执行。"
        "拍点写清场景、关键行动、对白真正新增的信息、关键变化以及结尾承接，"
        "清单应足够支持下一次调用无需阅读备用草稿措辞也能从零写作，但不要写成逐句分镜。"
        "连续性资料只作为事实参考，不得为了证明严谨而改写成对白、说明或新增核验流程。"
        "已有资料没有确认的内容继续保持未确认，能力、伤势、关系和持有状态没有在本章改变时保持原状；"
        "不能因为需要制造冲突或解释就把推测写成结论。"
            "如果当前提纲与既有事实冲突，必须保留既有事实；只有当前正文明确完成改变时才能更新，不能静默覆盖。"
        "整理拍点前必须静默核对提纲内部逻辑：同一人物不能同时处于已故、昏迷、清醒拒绝或异地出场等互斥状态；"
        "时间词、年份、先后顺序和因果必须能连成唯一过程；代词若可能指向两个人，拍点中直接使用姓名。"
        "还必须单独对照前文已经成立的期限、倒计时、预约、承诺和本章计划：凡出现‘N日内、N日后、截至、开门、交付、"
        "售完、再谈’等时间约束，必须确认本章安排为履约保留了真实可执行的时间；例如前文要求N日内完成，本章不能到N日后才开始执行。"
        "两者冲突时以已发布正文中的承诺为准，对当前提纲的时间安排做最小调整，不能把冲突原样写进正文。"
        "提纲自身出现互斥描述时，以已发布正文、当前状态和更具体的已确认事实为准；"
        "不得为了兼顾两种说法把互斥结果同时写进正文，冲突留给后续逻辑验收与局部修复处理。"
        + _style_repetition_boundary_text()
        + "在剧情执行清单之后生成《本章声纹执行表》。这不是通用建议，而是第二次终稿调用必须逐项执行的写法合同。"
        + narrative_mode_contract
        + mandatory_voice_contract
        + (
            "《本章声纹执行表》的主导语言节奏项还要从【作者原生用词池】中挑出本章语义真正适用的词，"
            "供备用正文和终稿优先替换模型默认同义表达；必须服从词池标注的完整样本实际次数和复现层级，"
            "低频场景词不能选作每章固定反应或转折标签；只列自然可用项，不规定出现次数。"
            if native_vocabulary else ""
        )
        + "文风合同只控制表达，不得把连续性资料改写成正文里的合规说明；证据、权限和未知状态只在它们确实改变人物行动或判断时自然出现，"
        "不得为每个判断都补一遍‘目前只能确认、不能说明、仍待核对’。"
        "声纹表开头必须严格写‘主叙事模式：六种模式之一’，再用一句话说明本章靠什么吸引读者。"
        f"如果提供了功能型原文片段卡，只能按本章实际场景选择0至{optional_card_high}张，只填写真实卡号SCxx。"
        "选择前必须同时核对卡片的适用和禁用边界；任何禁用条件命中时都不得选择，即使卡片语言很像样本。"
        "片段卡是条件性写法证据，不是每章覆盖清单；没有真正匹配的卡时写‘无’，不能为了证明文风而凑卡。"
        "每张卡只能绑定一个明确剧情拍点或一段连续小场景，必须写明使用起点、停止位置和只模仿哪种机制，不得作为全章统一模板。"
        "‘推理与解释’和‘专业角色对白’只有在主叙事模式明确为‘调查推理’，且推理本身就是本章核心推进时才能选择；"
        "医院、公司、警察、检测、合同或专业人物只是场景道具，不构成选择理由。‘权威角色命令’只有命令本身就是冲突或危机拍点时才能选择。"
        "‘群体反应’只适用于公开冲突或喜剧误读；‘日常口语与喜剧’只有场景本来允许轻松错位时才能选择，严肃举证、救命决定和情绪重击中不得强塞。"
        "声纹执行表只包含五项：一、选定片段卡及作用范围，严格写成‘卡号｜作用拍点或场景｜模仿机制｜停止位置’，无则写‘无’；"
        "二、主导语言节奏，只选1至2种真正适用的句法、动作反应或说话标签，说明适用场景；它们不是待覆盖词表，"
        "不得为了证明执行而各用一次，也不得指定必须出现的唯一位置；"
        "非调查推理模式不得预设连续思路段，确实需要判断时最多安排一段且不超过两句；"
        "调查推理模式最多安排两段集中判断，结论必须立刻改变动作、选择或风险。"
        f"三、段落节奏，把上方样本结构数字作为防止严重漂移的软参考；普通说明怎样合并，约本章篇幅最多保留{short_noun_limit}个非对白名词独段，"
        "非对白单句短段不得连续超过2段。专业过程只保留会改变剧情结果的一步，其他步骤合并成结果句；"
        "不能把每条信息都扩写成‘观察—理解—操作’的固定三段式，也不得为了命中比例新增对白、短段或笑点。"
        "四、本章核心声纹人物只列1至2人，写‘人物｜句长与停顿｜称呼/语气｜接话方式｜应避免的标准工作句’；"
        "其他人物静默继承人物卡，不逐人列满、不生成示例台词、不要求每个出场人物开口；"
        "五、章末具体落点与本章最需要避免的一种模型腔。必须指定最后一个可见、可听或可执行的具体事件；"
        "如果多路报告在章末连续接入，只先写一个打断现场的声音，再用人物接线、窗口增加或操作被迫改变承接其余报告；"
        "禁止显式使用‘第一路、第二路、第三路、第四路’或结构完全相同的逐条播报制造机械升级。"
        "最后1至3段就停在这个具体落点，禁止再追加‘某阶段开始了’‘事情没有结束’‘真正的危机才刚刚开始’等抽象宣告，"
        "也禁止用‘不是失败/但还不够/倒计时开始’式对称三段总结；若提纲要求阶段升级，必须用实际命令、异常或后果呈现。"
        "全表控制在300至600字，只保留会真正改变本章读感的少量规则，不写第二份剧情说明书。"
        + "随后生成一份完整备用正文草稿，供终稿调用失败时兜底。备用草稿只展开唯一剧情拍点，静默遵守边界，"
        "不得用重复解释、重复反应、往返确认或同义对白补足篇幅。备用正文必须先按【本章写作长度】控制在目标的85%-115%，"
        "并在交付前只检查是否严重偏离完整样本的段落与对白形态；不能为了命中数字新增短段、对白、冲突或喜剧。"
        "严格只输出以下三个分区，不输出其他标题、分析、状态JSON或Markdown代码块：\n"
        f"【剧情执行清单】\n{beat_low}-{beat_high}条唯一剧情拍点\n\n"
        "【本章声纹执行表】\n主叙事模式、0至1张条件性片段卡、1至2种主导语言节奏、段落中心区间、1至2名核心声纹人物、具体章末落点\n\n"
        "【备用正文草稿】\n完整正文草稿"
    )
    # The planning stage now carries pacing, payoff and emotional architecture.
    # Keep the prose stage focused on story facts and author voice instead of
    # re-planning the chapter through a large set of numeric style contracts.
    instruction = (
        "【剧情执行稿任务】\n"
        "本次先整理剧情执行稿并生成备用正文，不交付最终稿。合并提纲里指向同一事件的字段，按自然场景转折列出唯一剧情拍点；"
        "每个拍点必须产生新动作、新信息、新决定、新后果或必要情绪变化，但不要把观察、验证、问答和结论拆成教程步骤。"
        "项目中的连续性事实只用于防止写错，不是额外剧情拍点；"
        "即使同一事实在不同资料中重复出现，也只在剧情真正需要时自然落实一次。"
        "当前状态快照、下一章记忆选择和未决任务只用于防止连续性错误，不是本章待办清单；"
        "只有当前章节提纲明确安排执行时才能把其中事项写成剧情，否则保持未决，不得占用剧情拍点、对白或正文篇幅。"
        "提纲只概括为部分资金、相关主体、一次确认或一轮回应时，不得为了显得专业而自行补出多组精确金额、"
        "持股比例、文件名、时间戳、合同数量、界面字段或完整机构流程。只有直接改变人物选择、关系、代价或章末结果的一项代表性细节可以具体落地。"
        "篇幅仍有余量时优先展开人物取舍、关系后果、情绪共鸣和生活痕迹，不追加查账、举证、核验或处置步骤补字数。"
        "章首从上一章触发后的新反应、新结果或新阻力开始，不复播上一章末句；章末落在具体动作、对白、信息或后果，不追加抽象总结。"
        "随后给出简短的本章声纹执行表：只写1至2名核心人物的口吻、样本中本章自然适用的习惯用词/口语、叙述与对白衔接方式、章末落点。"
        "人物对白、冲突声纹、日常口语与喜剧习惯常驻执行；不要求凑词频，不设置段落、短句或对白数量配额，不选择主叙事模式，不强制套片段卡。"
        "作者画像中‘大量、经常、偏短、偏多’等定性描述只表示相对倾向，不能被放大成整章统一节拍；"
        "完整样本的自然读感优先；如果正文出现无效碎片、功能性问答堆叠或统一节拍，必须主动合并。"
        "同一事实的证明边界只完整交代一次；后续角色或专业人员只给新增结果、决定或阻力，不能换一种说法再次解释。"
        "本章主线不是调查推理时，关于‘能证明什么/不能证明什么’、隐私规则或查询范围最多完整出现一处；机构人物只承担一个改变结果的动作，不能形成流程辩论。"
        "备用正文必须完整执行剧情拍点，正文写法以作者样本为最高标准；避免重复解释、同义对白、流程复述和替人物讲道理。"
        "严格只输出以下三个分区，不输出其他标题、分析、状态JSON或Markdown代码块：\n"
        "【剧情执行清单】\n按发生顺序列出自然数量的唯一剧情拍点\n\n"
        "【本章声纹执行表】\n核心人物口吻、自然适用的原生词与说话方式、叙述衔接和具体章末落点\n\n"
        "【备用正文草稿】\n完整正文草稿"
    )
    structure_block = f"【完整样本结构软参考｜只防严重漂移】\n{structure_contract}" if structure_contract else ""
    vocabulary_block = f"【作者原生用词池｜优先替换AI默认措辞】\n{native_vocabulary}" if native_vocabulary else ""
    recent_vocabulary_block = (
        f"【最近章节原生用词密度｜只作软校准】\n{recent_vocabulary}"
        if recent_vocabulary else ""
    )
    cards_block = f"【功能型原文片段库｜只选择写法功能，不复制剧情】\n{cards_text}" if cards_text else ""
    # The base chapter context already carries the sample-derived style
    # fingerprint. Repeating its numeric structure bands and the entire card
    # library here made the prose stage behave like a checklist again.
    budget = max(
        0,
        int(limit or NOVEL_AI_CONTEXT_LIMIT) - len(instruction)
        - len(vocabulary_block) - len(recent_vocabulary_block) - 10,
    )
    if len(original) > budget:
        original = _clip_context_text(original, budget, keep_tail=False, preserve_lines=True)
    return "\n\n".join(
        part for part in (
            original,
            vocabulary_block,
            recent_vocabulary_block,
            instruction,
        ) if part
    )[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]


def _natural_expression_guidance():
    """Keep prose grounded in the scene instead of abstract verdicts."""
    return (
        "人物、外貌、情绪、关系、物件或场面，不要用生硬或抽象的判断语句直接下结论。"
        "需要让读者感到好看、难过、尴尬、紧张或某件东西显眼时，"
        "优先从当前场景写出可见、可听、可感的线索：动作、停顿、目光、语气、感官、选择、他人看见或听见后的"
        "心理和行为变化，以及这些变化带来的后果。"
        "不要写“他很难过”，可以让他用袖子擦眼睛、话停在半句或避开某个名字；不要写“她很漂亮”，可以写旁人看见她时"
        "视线、判断和动作如何改变。"
        "描写要服从当前人物、关系和现场，不把这些例子当固定动作模板。幽默、吐槽、夸张和比喻可以自由使用；"
        "根据当前人物、关系和现场自由选择描写落点。"
        "例如‘他意识到危险’，可以写成‘眼神停了一下，身体向后撤，右手扣紧桌沿’，再让这个动作带出对白、选择或结果。"
        "先依据当前项目的定位形成故事阅读感：题材类型与读者定位（如男频、女频、搞笑、悬疑等）、叙事人称、故事卖点和节奏，"
        "决定本章呈现什么样的冲突、情绪和推进方式。再依据样本文风进行仿写：以文风档案中的习惯用词、口语、句式松紧、"
        "对白接法、叙述节奏和情绪落点为仿写目标，尽量复刻它的写法，让当前故事以相近的作者表达方式呈现；"
        "项目资料负责故事定位、人物事实和剧情方向，样本文风负责表达层的落笔方式。示例动作只作参考，具体落点交给人物和现场。"
    )


def _build_full_style_imitation_guidance(style_reference):
    """Describe how to imitate a complete sample without turning it into a rule sheet."""
    reference = str(style_reference or "").strip()
    if not reference:
        return ""
    sample_chars = len(_compact_text(reference))
    return (
        f"这份样本保留了约{sample_chars}字完整原文。当前项目资料是本章故事事实：已经确定的人名、时间、地点、关系、"
        "物件、编号、人物状态和已发生事件，随着当前章节继续延展。\n"
        "把完整样本当作同一位作者正在写另一部作品的连续正文来阅读。顺着全文感受旁白怎样落句，人物怎样接话，"
        "动作和心理怎样互相接住，口语怎样嵌进人物当下的情绪，场景细节怎样带出人物的选择，以及一个场景怎样自然转入下一个场景。\n"
        "写当前章节时，让样本中的人物功能映射成当前小说的人物，让样本中的场景和事件映射成当前小说的场景和事件。"
        "以全文反复出现的语言习惯和每一处细微变化为依据，吸收其中的常用说法、句法松紧、叙述视角、对白间隙、"
        "情绪递进、信息露出、反应落点和章节收束。\n"
        "留意同一种情绪在样本中会随着人物关系和现场温度改变落点：有时落在一句接话，有时落在一个动作、一个物件，"
        "有时由带着停顿的旁白慢慢显出。把这种自然变化带进当前正文，让每一章保留作者的熟悉感，也保留当前人物独有的反应与节奏。\n"
        "轻松、尴尬、紧张、难过、关系拉扯和情节推进都可以从完整样本里寻找相应的写法，让当前人物按照自己的身份、"
        "关系与处境自然说话、行动和感受。样本的特色词、口头习惯、停顿方式和叙述温度随着人物和场景自然出现，"
        "形成一篇属于当前故事、同时读起来像同一位作者写出的正文。\n"
        + _natural_expression_guidance()
    )


def _build_style_execution_context(
    original_context,
    profile_text="",
    style_cards=None,
    style_reference="",
    project=None,
    chapter_index=0,
    limit=NOVEL_AI_CONTEXT_LIMIT,
    vocabulary_profile_text="",
    semantic_archive=None,
):
    """Build the prose prompt from the full sample instead of a runtime rule pack."""
    effective_limit = int(limit or NOVEL_AI_CONTEXT_LIMIT)
    original = str(original_context or "").strip()
    reference = str(style_reference or "").strip()
    if reference:
        style_markers = (
            "【AI文风画像】",
            "【风格锁定规则】",
            "【仿写使用说明】",
            "【正文风格参考】",
            "【本章选中的原文片段卡",
            "【作者原生用词池",
            "【最近章节原生用词密度",
            "【V4 人物与叙述声纹",
            "【V4 条件性叙事技法",
        )
        # The draft task mentions these section names in prose. Only remove a
        # real, line-leading context section, otherwise that prose can cut off
        # the current chapter, facts, and rules before they reach the model.
        marker_positions = [
            match.start()
            for marker in style_markers
            for match in re.finditer(rf"(?m)^{re.escape(marker)}", original)
        ]
        if marker_positions:
            original = original[:min(marker_positions)].rstrip()
        original = "\n\n".join(part for part in (
            original,
            "【仿写使用说明】\n" + _build_full_style_imitation_guidance(reference),
            "【正文风格参考】\n" + reference,
        ) if part)
    instruction = (
        "【小说正文直写】\n"
        "根据当前章节资料和前面的完整原样本，写出本章可直接进入小说的正文。"
        "项目资料中已经确定的人名、时间、地点、关系、物件、编号、人物状态和已发生事件保持原样延续。"
        "正文从当前章节的状态自然展开。"
        f"输出必须严格使用{NOVEL_PROSE_START_MARKER}和{NOVEL_PROSE_END_MARKER}包住正文；"
        "包络外不输出任何说明，包络内不写‘我会’‘接下来’‘本章将’等规划、分析或执行稿内容，"
        "只写可以直接进入小说的正文。"
    )
    budget = max(0, effective_limit - len(instruction) - 2)
    if len(original) > budget:
        original = _clip_context_text(original, budget, keep_tail=False, preserve_lines=True)
    return "\n\n".join(part for part in (original, instruction) if part)[:effective_limit]


def _parse_style_execution_result(value):
    text = str(value or "").strip()
    matches = list(re.finditer(
        r"【(剧情执行清单|本章声纹执行表|备用正文草稿)】[ \t]*(?=\r?\n|$)",
        text,
    ))
    required_order = ("剧情执行清单", "本章声纹执行表", "备用正文草稿")
    complete_sets = []
    for index in range(max(0, len(matches) - 2)):
        group = matches[index:index + 3]
        if tuple(match.group(1) for match in group) != required_order:
            continue
        group_end = matches[index + 3].start() if index + 3 < len(matches) else len(text)
        candidate = {
            "剧情执行清单": text[group[0].end():group[1].start()].strip(),
            "本章声纹执行表": text[group[1].end():group[2].start()].strip(),
            "备用正文草稿": text[group[2].end():group_end].strip(),
        }
        if candidate["剧情执行清单"] and candidate["备用正文草稿"]:
            complete_sets.append(candidate)
    if complete_sets:
        sections = complete_sets[-1]
    else:
        sections = {}
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            sections[match.group(1)] = text[match.end():end].strip()
    execution = sections.get("剧情执行清单", "")
    style_plan = _ensure_mandatory_style_voice_plan(
        sections.get("本章声纹执行表", "")
    )
    draft = sections.get("备用正文草稿", "")
    if not draft and text and not matches:
        draft = text
    if not execution:
        execution = draft
    return {
        "execution": execution,
        "style_plan": style_plan,
        "draft": draft,
        "parsed": bool(
            sections.get("剧情执行清单")
            and sections.get("备用正文草稿")
        ),
        "style_plan_parsed": bool(style_plan),
        "complete_set_count": len(complete_sets),
    }


NOVEL_PROSE_START_MARKER = "<NOVEL_PROSE_START>"
NOVEL_PROSE_END_MARKER = "<NOVEL_PROSE_END>"


def _extract_prose_delivery_result(value, require_marker=False):
    """Return only the body allowed to enter the writing pipeline."""
    raw = str(value or "").strip()
    if not raw:
        return {
            "ok": False,
            "text": "",
            "source": "empty",
            "execution": "",
            "style_plan": "",
            "error": "AI 正文交付边界不完整：返回为空。",
        }

    has_structured_sections = bool(re.search(
        r"【(?:剧情执行清单|本章声纹执行表|备用正文草稿)】",
        raw,
    ))
    if has_structured_sections:
        parsed = _parse_style_execution_result(raw)
        draft = str(parsed.get("draft", "") or "").strip()
        if parsed.get("parsed") and parsed.get("style_plan_parsed") and draft:
            return {
                "ok": True,
                "text": draft,
                "source": "structured_backup_draft",
                "execution": str(parsed.get("execution", "") or "").strip(),
                "style_plan": str(parsed.get("style_plan", "") or "").strip(),
                "error": "",
            }
        return {
            "ok": False,
            "text": "",
            "source": "structured_incomplete",
            "execution": "",
            "style_plan": "",
            "error": "AI 剧情执行稿结构不完整，正文交付边界没有提供完整备用正文。",
        }

    if require_marker:
        start_index = raw.find(NOVEL_PROSE_START_MARKER)
        end_index = (
            raw.find(
                NOVEL_PROSE_END_MARKER,
                start_index + len(NOVEL_PROSE_START_MARKER),
            )
            if start_index >= 0 else -1
        )
        if start_index < 0 or end_index < 0:
            return {
                "ok": False,
                "text": "",
                "source": "direct_boundary_missing",
                "execution": "",
                "style_plan": "",
                "error": "AI 正文交付边界不完整：直写正文必须只放在正文包络内。",
            }
        prose = raw[
            start_index + len(NOVEL_PROSE_START_MARKER):end_index
        ].strip()
        if not prose:
            return {
                "ok": False,
                "text": "",
                "source": "direct_boundary_empty",
                "execution": "",
                "style_plan": "",
                "error": "AI 正文交付边界不完整：正文包络内为空。",
            }
        return {
            "ok": True,
            "text": prose,
            "source": "direct_prose_boundary",
            "execution": "",
            "style_plan": "",
            "error": "",
        }

    return {
        "ok": True,
        "text": raw,
        "source": "plain_compatibility",
        "execution": "",
        "style_plan": "",
        "error": "",
    }


def _build_style_audit_context(style_reference, draft_text, profile_text="", local_reasons=None, limit=NOVEL_AI_CONTEXT_LIMIT):
    reference = str(style_reference or "").strip()
    audit_reference = (
        reference if len(reference) <= 16000
        else _select_style_reference_excerpts(reference, draft_text, 12000)
    )
    draft = str(draft_text or "").strip()
    profile = str(profile_text or "").strip()
    reasons = [str(reason).strip() for reason in (local_reasons or []) if str(reason or "").strip()]
    local_block = "\n".join(f"- {reason}" for reason in reasons) or "- 本地结构指标均在允许范围内"
    instruction = (
        "【审校任务】\n"
        "独立比较样本与候选正文的写法。忽略两者剧情、人物和题材不同，不因候选剧情完整或好看而加分。"
        "逐项检查：叙事口吻、语言粗糙/工整程度、习惯词及其使用场景、常用句首和句式框架、"
        "动作与生理反应词、说话标签、对白长度与停顿、称呼与语气词、不同功能角色的说话方式、"
        "段落起落、对白与叙述结合方式、背景插入方式、"
        "情绪来源、场景推进逻辑、信息揭示顺序、强调句习惯和章节收束。"
        "必须判断候选是否为了词汇丰富而替换了样本会重复使用的词，或让所有人物使用了同一种模型口吻。"
        "如果只是合并换行但句子组织仍不同，必须判定不通过。"
        "忽略样本因网页复制、OCR或文档提取产生的异常空格、异形字符、断词和明显标点错误。"
        "审校只能要求改变表达方式，绝不能要求删除、提前、延后或更换候选正文必须完成的剧情事件和结尾事件；"
        "章节收束只比较语气、段落组织和落点表达，不比较两篇故事具体停在哪个事件。"
        "输出JSON对象：pass（布尔值）、score（0-100整数）、summary（字符串）、issues（数组）。"
        "issues中的每项必须包含dimension、evidence、instruction；evidence要引用两边的写法差异，"
        "instruction必须是下一次重写可直接执行的要求。issues最多列5项真正影响整体读感的阻断差异，"
        "不要为了覆盖全部分析维度而罗列轻微差异；正常标点、语法规范和剧情题材差异不构成问题。"
        "score达到80且不存在明显文风差异时pass才可为true。"
        "只输出JSON，不要Markdown代码块。"
    )
    parts = [
        f"【AI文风画像】\n{profile}" if profile else "",
        f"【本地结构验收】\n{local_block}",
        (
            f"【正文风格样本】\n{audit_reference}"
            if audit_reference == reference else
            f"【正文风格样本｜从约{len(_compact_text(reference))}字完整样本分层选取】\n{audit_reference}"
        ),
        f"【候选正文】\n{draft}",
        instruction,
    ]
    text = "\n\n".join(part for part in parts if part)
    return text[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]


def _parse_style_audit_result(value):
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match and match.group(0) != text:
        candidates.append(match.group(0))
    data = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            data = parsed
            break
    if not isinstance(data, dict):
        return {
            "pass": False,
            "score": 0,
            "summary": "文风审校结果无法解析。",
            "issues": [{
                "dimension": "审校格式",
                "evidence": text[:500],
                "instruction": "重新按样本文风完整重写，并严格控制结构指标。",
            }],
        }
    try:
        score = max(0, min(100, int(float(data.get("score", 0) or 0))))
    except Exception:
        score = 0
    issues = []
    for item in data.get("issues", []) if isinstance(data.get("issues"), list) else []:
        if isinstance(item, dict):
            dimension = str(item.get("dimension", "文风") or "文风").strip()
            evidence = str(item.get("evidence", "") or "").strip()
            instruction = str(item.get("instruction", "") or "").strip()
        else:
            dimension = "文风"
            evidence = str(item or "").strip()
            instruction = evidence
        if evidence or instruction:
            issues.append({"dimension": dimension, "evidence": evidence, "instruction": instruction})
    passed = bool(data.get("pass")) and score >= 80 and not issues
    return {
        "pass": passed,
        "score": score,
        "summary": str(data.get("summary", "") or "").strip(),
        "issues": issues,
    }


def _build_style_plot_acceptance_context(project, chapter_index, execution_text=""):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    if chapter_index < 0 or chapter_index >= len(chapters):
        return ""
    chapter = chapters[chapter_index] if isinstance(chapters[chapter_index], dict) else {}
    execution = str(execution_text or "").strip()
    current_outline = _strip_static_foreshadow_outline_fields(chapter.get("outline", ""))
    current_basis = execution or current_outline or "暂无明确规划"
    current_label = "本章唯一剧情执行清单" if execution else "本章规划验收原文"
    previous_boundary = _chapter_previous_opening_boundary_text(project, chapter_index)
    parts = [
        "只按已经合并去重的唯一剧情拍点验收本章；原始提纲里人物任务、主线任务、本章目标、必须发生和结尾钩子"
        "如果描述同一事件，不构成多次叙述任务。每个拍点必须在终稿中真实发生，不能只在人物想法、预告或章末说明中提及。"
        "现有连续性事实只用于验收事实是否冲突，不要求正文复述。"
        "同时对照前两章已完成事件，除明确持续动作和必要承接外，不得复演已经完成的冲突、解释、对话结论或结尾钩子。",
        f"【{current_label}】\n{current_basis}",
    ]
    if previous_boundary:
        parts.append(
            "【章首承接硬验收】\n"
            "上一章结尾已经向读者发布，终稿不能再次写出或同义重写其中的末句、对白、声音、动作落点、结论或情绪。"
            "本章必须从新反应、新结果、新阻力或新信息起笔；终稿验收必须提供章首前三段中的首个新句逐字证据，"
            "并用一句话说明这个章首新增变量。合法起笔分别是：对白后的新反应/回答、动作后的新结果/阻力、声音后的声源/新反应。\n"
            + "上一章已发布结尾的最后三段：\n"
            + "\n".join(_style_boundary_paragraphs(previous_boundary, limit=3))
        )
    previous_blocks = []
    for previous_index in range(max(0, chapter_index - 2), chapter_index):
        previous = chapters[previous_index]
        if not isinstance(previous, dict):
            continue
        actual_outline = str(previous.get("actual_outline", "") or "").strip()
        summary = str(previous.get("summary", "") or "").strip()
        body = str(previous.get("text", "") or "").strip()
        completed_events = actual_outline or summary or "暂无"
        boundary_label = (
            "章末承接（已发布事实，用于去重）"
            if previous_index == chapter_index - 1 and body
            else "章末承接（只用于承接与去重）"
        )
        boundary_text = (
            "\n".join(_style_boundary_paragraphs(body, limit=3))
            if body else "暂无"
        )
        previous_blocks.append(
            "第{}章《{}》\n已完成事件：{}\n{}：{}".format(
                previous_index + 1,
                str(previous.get("title", "") or "").strip(),
                _clip_context_text(completed_events, 1200, preserve_lines=True) or "暂无",
                boundary_label,
                boundary_text,
            )
        )
    if previous_blocks:
        parts.append("【前两章已完成内容｜只用于承接与去重】\n" + "\n\n".join(previous_blocks))
    return "\n\n".join(parts)


def _context_section_blocks(value):
    """Return heading-delimited context blocks without changing their content."""
    text = str(value or "").strip()
    if not text:
        return []
    matches = list(re.finditer(r"(?m)^【([^】\r\n]+)】\s*$", text))
    if not matches:
        return []
    blocks = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = str(match.group(1) or "").strip()
        body = text[match.end():end].strip()
        if title and body:
            blocks.append((title, f"【{title}】\n{body}"))
    return blocks


def _compact_style_finalize_source_context(
    original_context,
    style_reference="",
    limit=STYLE_FINALIZE_SOURCE_CONTEXT_LIMIT,
):
    """Build a continuity-safe packet for body-only finalization.

    The first draft already receives the complete project packet. The
    finalizer needs the same identity and selected continuity facts, but does
    not need every copy of the global catalog and planning instructions again.
    """
    original = str(original_context or "").strip()
    blocks = _context_section_blocks(original)
    if not blocks:
        if len(original) <= int(limit or STYLE_FINALIZE_SOURCE_CONTEXT_LIMIT):
            return original
        return _clip_context_text(
            original,
            int(limit or STYLE_FINALIZE_SOURCE_CONTEXT_LIMIT),
            keep_tail=True,
            preserve_lines=True,
        )
    by_title = {}
    for title, block in blocks:
        by_title.setdefault(title, []).append(block)

    selected = []
    selected_titles = set()

    def add_title(title, budget):
        values = by_title.get(title, [])
        if not values:
            return
        remaining_budget = max(0, int(budget or 0))
        for block in values:
            if remaining_budget <= 0:
                break
            body = block.split("\n", 1)[1] if "\n" in block else block
            clipped = _clip_context_text(
                body,
                min(remaining_budget, max(80, int(budget or 0))),
                preserve_lines=True,
            )
            if clipped:
                selected.append(f"【{title}】\n{clipped}")
                selected_titles.add(title)
                remaining_budget -= len(clipped)

    core_budgets = (
        ("项目核心信息", 500),
        ("长篇进度 / 节奏", 400),
        ("长篇继承规则", 700),
        ("剧情连续性参考", 2200),
        ("剧情执行硬约束", 2200),
        ("本章写作长度", 500),
        ("本次任务", 700),
        ("当前章节", 4500),
        ("小说圣经", 1500),
        ("世界观 / 规则", 1500),
        ("当前状态快照", 4500),
        ("全局紧凑状态目录", 2500),
        ("后续规划参考", 1600),
        ("后章衔接点", 700),
        ("活跃连续性事实", 5000),
        ("近期阶段档案", 2200),
        ("续写承接点", 2200),
        ("前文继承摘要", 2500),
        ("近几章连续性", 2500),
        ("本章相关人物", 3500),
        ("本章相关设定", 2200),
        ("本章相关伏笔", 1200),
        ("本章唯一剧情执行清单", 3500),
    )
    for title, budget in core_budgets:
        add_title(title, budget)

    style_prefixes = (
        "AI文风画像",
        "作者人格",
        "剧情组织人格",
        "人物与场景人格",
        "叙述习惯词与句法声纹",
        "对白总体声纹",
        "功能角色说话方式",
        "格式节奏与使用边界",
        "风格锁定规则",
        "正文风格参考",
        "代表片段",
        "观众期待值",
    )
    core_compacted = "\n\n".join(selected)
    style_budget = max(
        0,
        min(9000, int(limit or STYLE_FINALIZE_SOURCE_CONTEXT_LIMIT) - len(core_compacted) - 800),
    )
    style_used = 0
    for title, block in blocks:
        if title in selected_titles or not any(title.startswith(prefix) for prefix in style_prefixes):
            continue
        remaining = style_budget - style_used
        if remaining <= 120:
            break
        body = block.split("\n", 1)[1] if "\n" in block else block
        clipped = _clip_context_text(body, remaining, preserve_lines=True)
        if clipped:
            selected.append(f"【{title}】\n{clipped}")
            selected_titles.add(title)
            style_used += len(clipped)

    has_reference = any(
        title.startswith("正文风格参考") or title.startswith("代表片段")
        for title in selected_titles
    )
    if not has_reference and style_reference:
        remaining = max(0, style_budget - style_used)
        excerpt = _select_style_reference_excerpts(
            style_reference,
            original,
            min(6000, remaining),
        ) if remaining > 120 else ""
        if excerpt:
            selected.append(f"【正文风格参考｜终稿分层选段】\n{excerpt}")

    compacted = "\n\n".join(selected)
    if not compacted:
        return original
    hard_limit = int(limit or STYLE_FINALIZE_SOURCE_CONTEXT_LIMIT)
    if len(compacted) <= hard_limit:
        return compacted
    return _clip_context_text(compacted, hard_limit, keep_tail=True, preserve_lines=True)


def _build_chapter_execution_hard_constraints(project, chapter_index):
    """Expose selected continuity facts without turning them into a boundary checklist."""
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter = (
        chapters[chapter_index]
        if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict)
        else {}
    )
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
    selected = chapter.get("memory_selection", {}) if isinstance(chapter, dict) else {}
    selected = selected if isinstance(selected, dict) else {}
    constraint_selection = deepcopy(selected)
    constraint_selection["_restrict_state"] = True
    try:
        snapshot = json.loads(
            _long_form_memory_sections(project, constraint_selection)["当前状态快照"]
        )
    except Exception:
        snapshot = {}
    lines = [
        "以下资料只用于核对连续性事实，不是正文需要逐条展示的任务。",
        "只参考本章提纲真正触及的事实；未触及的职责、规则、物件和旧结论保持原状，不要写进执行清单。",
        "资料未确认的内容继续保持未确认，人物没有获得的新能力、授权或物品不能凭空获得；伤势和关系没有变化时保持原状。",
        "这些事实不得被扩写成新增的核对、封存、编号、审批、交接、见证、记录固定或责任说明；现实流程完整不等于剧情完整。",
        "上一章结尾的时间、地点、人物位置、身体状态、持有物和未完成动作必须自然承接，但不能复播已经发布的末句、动作或结论。",
        "提纲与已发生事实冲突时保留更具体、更新、更接近正文的记录；前两章已经完成的解释和冲突只继承结果，不重新演一遍。",
    ]
    selected_facts = set(str(value or "").strip() for value in selected.get("fact_ids", []) if str(value or "").strip())
    fact_lines = []
    for item in memory.get("active_facts", []) if selected_facts else []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "") or "").strip()
        if selected_facts and item_id not in selected_facts:
            continue
        fact = _fact_with_memory_history_context(item, memory, detail_limit=420)
        if fact:
            fact_lines.append(f"- {item_id}｜{fact}")
    if fact_lines:
        lines.append("已选长期事实（只能按原确定性继承）：\n" + "\n".join(fact_lines[:12]))
    for label, key, formatter in (
        ("当前人物状态", "character_states", lambda item: f"{item.get('name', '')}：{item.get('state', '')}"),
        ("当前关系状态", "relationship_states", lambda item: f"{'、'.join(_normalize_name_list(item.get('characters', [])))}：{item.get('state', '')}"),
        ("当前物件状态", "object_states", lambda item: f"{item.get('key', item.get('name', ''))}：{item.get('state', '')}"),
        ("当前冲突", "active_conflicts", lambda item: f"{item.get('id', '')}：{item.get('conflict', '')}"),
        ("当前未决任务", "unresolved_tasks", lambda item: f"{item.get('id', '')}：{item.get('task', '')}"),
    ):
        values = snapshot.get(key, [])
        rows = []
        for item in values if isinstance(values, list) else []:
            if not isinstance(item, dict):
                continue
            row = _compact_text(formatter(item))
            if row:
                rows.append("- " + row)
        if rows:
            lines.append(label + "（如无本章明确变化，保持不变）：\n" + "\n".join(rows[:10]))
    return _clip_context_text("\n".join(lines), 4200, preserve_lines=True)


def _build_style_finalize_context(
    original_context,
    draft_text,
    profile_text="",
    style_reference="",
    local_reasons=None,
    output_target=0,
    limit=NOVEL_AI_CONTEXT_LIMIT,
    memory_selection_index="",
    project=None,
    chapter_index=0,
    include_memory=True,
    execution_text="",
    style_plan="",
    style_cards=None,
    rescue_from_candidate=False,
    vocabulary_profile_text="",
):
    original = _append_ai_style_profile_to_context(
        original_context,
        _style_runtime_profile(profile_text, style_reference, include_structure=False),
        limit=limit,
    )
    if not include_memory:
        original = _compact_style_finalize_source_context(
            original,
            style_reference=style_reference,
        )
    draft = str(draft_text or "").strip()
    execution = str(execution_text or "").strip()
    chapter_style_plan = str(style_plan or "").strip()
    voice_identity_required = bool(execution and _compact_text(style_reference))
    if voice_identity_required:
        chapter_style_plan = _ensure_mandatory_style_voice_plan(chapter_style_plan)
    chapter_style_plan = _remove_style_layout_metrics(chapter_style_plan)
    mandatory_voice_contract = (
        _mandatory_style_voice_contract(style_cards)
        if voice_identity_required else ""
    )
    target = int(output_target or 0) or _style_output_target_from_context(original)
    narrative_mode = _style_narrative_mode_from_plan(chapter_style_plan)
    narrative_mode_contract = _style_narrative_mode_contract(target, narrative_mode)
    style_card_limit = 1
    selected_cards = _style_cards_selected_by_plan(
        style_cards,
        chapter_style_plan,
        max_cards=style_card_limit,
    )
    selected_cards_text = _format_style_cards(selected_cards, limit=5600)
    native_vocabulary = _style_native_vocabulary_text(
        vocabulary_profile_text or profile_text,
        style_reference,
        output_target=target,
    )
    recent_vocabulary = _style_recent_vocabulary_usage_text(
        project,
        chapter_index,
        vocabulary_profile_text or profile_text,
        style_reference,
    )
    reasons = [str(reason).strip() for reason in (local_reasons or []) if str(reason or "").strip()]
    reason_text = _style_generation_issue_text(reasons)
    previous_boundary = _chapter_previous_opening_boundary_text(project, chapter_index)
    opening_acceptance_text = (
        "存在上一章已发布结尾时，终稿必须从新反应、新结果、新阻力或新信息起笔；"
        "上一章的末句、对白、声音、动作落点、结论和情绪不能原样或同义重写。"
        "合法起笔是对白后的新反应/回答、动作后的新结果/阻力、声音后的声源/新反应。"
        "验收JSON中的opening_continuation如有填写，证据必须来自章首前三段；字段缺失不等于正文失败，"
        "但实际复演上一章结尾仍然是硬错误。"
        if previous_boundary else
        "本章没有需要验收的上一章章首边界；不要伪造opening_continuation字段。"
    )
    acceptance_schema = (
        "{"
        + (
            '"opening_continuation":{"first_new_sentence":"章首前三段中的首个新句逐字原文",'
            '"new_action_or_result":"该句带来的新反应、新结果、新阻力或新信息"},'
            '"timeline_commitment_check":{"prior_deadline_or_promise":"前文期限或承诺的简短原意；确无则写无",'
            '"current_schedule":"终稿采用的当前时间安排；确无则写无","compatible":true},'
            if previous_boundary else ""
        )
        + '"previous_chapter_repetition_check":true,"logic_continuity_check":true,'
        '"procedural_expansion_check":true,"mechanical_prose_check":true,'
        '"role_voice_attribution_check":true}'
    )
    preflight_text = _style_finalize_preflight_targets(
        style_reference,
        draft,
        target,
    )
    priority_edit_text = _style_finalize_priority_edit_text(
        style_reference,
        draft,
        target,
    )
    reference_structure = _style_text_structure(style_reference)
    draft_structure = _style_text_structure(draft)
    draft_structure_errors = _style_finalize_acceptance_errors(
        "",
        draft,
        {},
        style_reference,
        target,
    )
    draft_length_usable = bool(
        draft_structure["chars"] >= 300
        and (
            not target
            or target * 0.85 <= draft_structure["chars"] <= target * 1.15
        )
    )
    edit_candidate_in_place = bool(
        execution
        and draft
        and not rescue_from_candidate
        and draft_length_usable
        and not draft_structure_errors
    )
    # A from-execution rewrite does not receive the rejected backup body. Do
    # not ask the model to merge a specific number of paragraphs or dialogue
    # turns from text that is intentionally absent from the request.
    candidate_metrics_relevant = bool(
        rescue_from_candidate or edit_candidate_in_place or not execution
    )
    if not candidate_metrics_relevant:
        reasons = []
        reason_text = ""
        preflight_text = ""
        priority_edit_text = ""
    in_place_structure_contract = (
        "底稿结构已经通过；终稿不得为了留下修改痕迹拆段、补对白或改坏自然节奏。"
        "只允许保留原有自然排版，或合并确有重复的相邻表达。"
        if edit_candidate_in_place else ""
    )
    reference_profile = (
        _build_style_reference_profile(style_reference, target, include_structure=False)
        if style_reference else ""
    )
    delivery_targets = []
    if target:
        delivery_targets.append(f"终稿正文控制在{round(target * 0.85)}-{round(target * 1.15)}字")
    delivery_targets.extend([
        "自然排版只跟随样本文本读感，不执行固定换行、短句、对白或结构统计目标",
        "办案式流程和机械感是硬约束：非主线的查证、审批、封存、交接、记录、责任确认不得扩成流程播报；连续同构动作、重复解释和段尾总结必须压缩",
        "能不用“几个字/几个词/几个音节”就不用；真要写字数，标点符号、引号和空格都不计入字数",
    ])
    delivery_text = "\n".join(f"- {item}" for item in delivery_targets)
    delivery_audit_text = ""
    plot_acceptance = _build_style_plot_acceptance_context(
        project,
        int(chapter_index or 0),
        execution_text=execution,
    )
    repetition_boundary = _style_repetition_boundary_text()
    instruction = (
        "【终稿编辑任务】\n"
        + (
            f"【本章首要编辑动作】\n{priority_edit_text}\n"
            if priority_edit_text else ""
        )
        + "先独立核对首次正文是否完整执行本章剧情、人物设定、前文连续性和结尾要求，再对照正文风格样本检查写法。"
        "直接交付修订后的终稿，不要先输出审校报告。剧情正确的内容必须保留，不得为了文风删除、替换、提前或延后既定事件；"
        "只在确有必要时调整叙述方式、句式、段落组织、对白衔接、信息揭示和收束表达。"
        "如果首次正文已经比任何改写更贴近样本，可以原样保留正文。"
        "程序可能根据样本结构在首次正文和修订稿之间择优，因此所有evidence_quote必须从首次正文逐字复制，"
        "并在终稿正文中保留完全相同的连续短句；不得把证据句改写成只存在于其中一个版本的表达。"
        "必须单独完成一次语言声纹校准：按作者人格中的高频/稳定层级，在适用场景沿用样本反复出现的"
        "句首、连接词、动作修饰词、生理反应短语、解释框架和说话标签，不得为了词汇丰富强行换同义词；"
        "作者人格的宽泛‘高频’概括必须让位于【作者原生用词池】标注的完整样本实际次数；"
        "局部或限定场景的词不得硬塞，低频词不能变成每章口头禅，任何惯用词都不得集中堆砌或明显超过样本密度。"
        "必须单独完成一次对白声纹校准：只重点校准声纹表列出的1至2名核心人物，结合角色卡落实其对白长短、"
        "停顿、省略、称呼、语气词、接话和动作插入方式；其他人物只在剧情必须开口时自然继承人物卡，不能为了区分口吻轮流发言。"
        + narrative_mode_contract
        + mandatory_voice_contract
        + "如果提供【本章声纹执行表】，它只校准同一剧情的语言，不得新增剧情任务；剧情完整、人物自然反应和片段卡适用边界优先。"
        "核心声纹人物必须保持可区分；其他实际说话人物只需符合身份，没有必要开口的人物不为展示声纹新增台词。"
        "片段卡原文只以【本章选定功能片段卡】实际列出的卡为准；声纹表中提到但未列出的卡视为未选，不执行。"
        "每张选定卡只控制声纹表指定的一个拍点或连续小场景，到表中停止位置立即退出，不能把其判断方式、专业口吻或段落节拍扩散到全章。"
        "只模仿选定卡的组织机制、用词频率和对白节拍，绝不能复制其人物、设定、事件或连续原句。"
        "连续性事实只用于后续验收和修复，不能逐条显性写进正文；不得给每个判断机械补齐风险说明或写成处置报告。"
        "专业信息先写它造成的决定、冲突或结果，再补读者非知道不可的最短原因；"
        "不得自行补齐提纲没有要求的现实处置流程，也不得把同一判断拆给多人重复确认。"
        "角色差异必须体现在句法、停顿、称呼和接话，不能只靠职责术语区分。"
        "必须逐段完成逻辑连续性核对：时间词、年份和先后顺序不能互相打架；原因必须先于结果；"
        "代词必须只有一个明确指向，同时出现两个可能对象时直接写姓名；人物的生死、清醒、伤势、位置、权限和物件持有状态"
        "必须与已发布正文及当前状态一致。提纲内部存在互斥描述时，以已确认事实为准，正文只保留一种成立状态。"
        "必须把前两章已经成立的期限、倒计时、预约和承诺与终稿当前时间安排并列核对；若当前计划会占满期限、倒置先后或让承诺无法履行，"
        "先按已发布正文最小调整当前时间，再在timeline_commitment_check中写出前文约束、终稿安排并确认兼容，不能直接填true。"
        "章首承接状态合并成一个自然中段，不得把人物站姿、伤势、环境和能力状态连续拆成电影分镜。"
        "同一人物连续说出的短促命令、短问和短答必须自然衔接，或由真正承担反应/操作的动作标签连接；不能每句都另起一段。"
        "多路消息在章末接入时禁止使用‘第一路、第二路、第三路、第四路’逐项播报；先用一个声音打断，再由人物动作和窗口变化承接后续升级。"
        "章末必须停在声纹表指定的具体动作、声音、异常、后果或一句人物对白上；落点之后禁止追加抽象阶段宣告、对称三段总结或商业预告句。"
        "输出前静默检查字数、自然排版读感、句式、对白衔接、习惯用词、对白声纹以及人物、物品、地点、伤势和结尾状态。"
        "必须按【终稿剧情验收清单】逐项确认唯一剧情拍点已经执行，并删除非必要的前两章剧情复演；"
        "终稿前在内部逐段检查净推进：连续两到四段可以共同完成一个强调或情绪单元，"
        "但如果整组内容没有带来新动作、新信息、新决定、新后果或必要情绪转折，就必须删除或并入前文。"
        + repetition_boundary
        + opening_acceptance_text
        + (f"以下只用于防止机械漂移，不得为了命中数字制造内容：\n{delivery_text}\n" if delivery_text else "\n")
        +
        "必须严格使用以下六个分区标题，标题不得改名；正文中不要出现分析、评分、修改说明或其他分区标题：\n"
        "【终稿正文】\n可直接写入章节的完整正文\n\n"
        "【终稿验收】\n"
        + acceptance_schema + "\n\n"
        + "剧情执行清单只用于组织本章正文，不要求为每个拍点提交逐字证据；不得因为自然合并表达而重写已经成立的剧情。"
        "所有check只能在逐段完成对应检查后写true；"
        "role_voice_attribution_check还必须确认示例句和标志短语没有串给错误人物。"
        + "人物声纹只检查实际说话人物是否彼此可区分，不要求新增冲突、喜剧、两轮接话或逐字声纹证据。\n\n"
        "【实际提纲】\n用6-10条短剧情拍点概括终稿已经发生的内容，不补写正文外事件\n\n"
        "【本章摘要】\n简短概括终稿核心事件和情绪转折\n\n"
        "【本章需继承的关键事实】\n逐条记录后文必须继承的人物关系、伤势、物品、地点、线索、伏笔和结尾状态\n\n"
        "【长篇记忆更新】\n"
        + _long_form_update_contract_instructions(project or {}, chapter_index)
    )
    if not include_memory:
        source_instruction = (
            "以上次终稿为正文底稿，完整保留已经发生的剧情、因果、人物状态、具体信息和章末落点；"
            "只针对【备用正文的本地检测结果】调整语言组织、合并无效碎片、校准对白衔接和必要句式。"
            "不得从剧情执行清单重新写一版，也不得删掉或替换原有拍点。"
            if rescue_from_candidate else
            "备用正文的篇幅与整体读感已经通过本地验收，以它为正文底稿，完整保留已经发生的剧情、因果、"
            "人物状态、具体信息、自然段落和章末落点；只做确有必要的语言声纹、人物口吻、信息揭示和"
            "句式校准。不得从零重写，也不得为了显得修改充分而增加对白、拆段或替换原本自然的表达。"
            + in_place_structure_contract
            if edit_candidate_in_place else
            "根据剧情执行清单从零写出完整终稿。执行清单只提供剧情事实和顺序，不是可沿用的正文表达；"
            "不得把备用草稿的句子、碎片排列、动作分镜或措辞当成底稿，也不要做逐句润色。"
            "清单只是场景转折索引，不是一条拍点对应一次换行、一句对白或一次结论总结的模板；"
            "同一场景内的相邻拍点必须连成自然的冲突单元，写完场景后再从正文中选择验收证据，"
            "不能围绕验收字段反向拼装正文。"
            if execution else
            "先独立核对首次正文是否完整执行本章剧情、人物设定、前文连续性和结尾要求，再对照正文风格样本检查写法。"
        )
        fallback_instruction = (
            "本次必须保留上次终稿的全部有效剧情，只调整未通过的验收项。"
            if rescue_from_candidate else
            "如果任何改写会损伤剧情、自然度或现有读感，允许原样保留已经合格的正文；禁止为留下修改痕迹而改写。"
            if edit_candidate_in_place else
            "必须重新组织整章，不能退回备用正文草稿。"
            if execution else
            "如果首次正文已经比任何改写更贴近样本，可以原样保留。"
        )
        instruction = (
            "【终稿编辑任务】\n"
            + (
                f"【本章首要编辑动作】\n{priority_edit_text}\n"
                if priority_edit_text else ""
            )
            + source_instruction
            + "本次只负责小说正文，不生成提纲、摘要、关键事实或状态资料。"
            "剧情事件、人物、设定、时间顺序、因果关系和结尾承接必须完整保留；"
            "在这些内容不变的前提下，可以彻底重组句式、自然排版、对白衔接、叙述节奏和信息揭示方式。"
            "不要保留备用草稿或模型默认写法中的碎片化排版、机械强调、分镜动作流或对白堆砌。"
            + fallback_instruction
            + "必须按作者人格和原文证据校准习惯词、句式框架、说话标签、对白停顿、称呼、语气词和接话方式；"
            "样本会重复使用的词不应被模型默认同义词替换，但主导语言节奏不是待覆盖词表；局部词不能硬塞，"
            "不得把多个习惯词平均撒在整章，不同人物不能写成同一种口气。"
            + (
                "逐句检查【作者原生用词池】：凡是正文正在使用模型常见词，而词池中存在语义和人物口吻都匹配的作者原词，"
                "优先改用作者原词；现代口语可自然进入现代认知人物的对白、心理和贴近其视角的叙述。"
                "以词池中的完整样本实际次数和复现层级校准密度；低频场景词不能写成每章口头禅、转折标签或固定人物反应。"
                "不要求覆盖全部词，也不得为了命中词库破坏语义或新增情节。"
                if native_vocabulary else ""
            )
            + narrative_mode_contract
            + mandatory_voice_contract
            + "【本章声纹执行表】只校准同一剧情的语言；剧情完整、人物自然反应和片段卡适用边界优先，不能把表内项目改写成新增场面。"
            + "只重点校准声纹表列出的1至2名核心人物；其他人物只在剧情必须开口时自然继承人物卡，"
            "没有必要开口的人物不为展示声纹新增台词，也不为了区分口吻轮流发言。"
            "片段卡原文只以【本章选定功能片段卡】实际列出的卡为准；表中提到但未列出的卡视为未选。"
            "每张卡只控制表中指定的一个拍点或连续小场景，到停止位置立即退出，不能把同一种专业判断、命令口吻或段落节拍铺满全章；"
            "只模仿组织机制、用词频率和对白节拍，禁止复制其中人物、设定、事件或连续原句。"
            "连续性事实不得逐条显性改写成正文；事实冲突由逻辑验收和局部修复处理，不得为每个判断机械补齐风险限定。"
            "专业信息先写它造成的决定、冲突或结果，再补读者非知道不可的最短原因；"
            "不得自行补齐提纲没有要求的现实处置流程，也不得把同一判断拆给多人重复确认。"
            "角色差异必须体现在句法、停顿、称呼和接话，不能只靠职责术语区分。"
            "必须逐段核对时间顺序、因果、代词指向和人物生死/清醒/位置/持有状态；"
            "提纲内部出现互斥描述时，以已发布正文、当前状态和更具体的已确认事实为准，正文只保留一种成立状态。"
            "章首承接状态合并成一个自然中段，不得拆成电影分镜；多路消息在章末接入时禁止用‘第一路、第二路、第三路、第四路’逐项播报，"
            "先用一个声音打断，再由人物动作和窗口变化承接后续升级。"
            "同一人物连续说出的短促命令、短问和短答必须自然衔接，或由真正承担反应/操作的动作标签连接，不能每句都另起一段。"
            "章末必须停在声纹表指定的具体动作、声音、异常、后果或一句人物对白上，禁止再追加抽象阶段宣告或对称三段总结。"
            + "输出前静默检查人物、物品、地点、伤势、时间、因果、结尾状态、对白声纹、办案式流程扩张和机械化表达。"
            + "段落排版指标已删除；自然排版、句式、对白衔接和习惯用词只用于贴近读感，不能据此新增、拆分或删改剧情。"
            "只有普通说明、同义确认、重复边界说明和无新增信息的功能性问答形成明显机械播报时，才自然合并。"
            "同一证据或判断的‘能证明什么、不能证明什么’只完整说明一次；后续核验只写新增结果及其造成的选择或后果。"
            + "必须按【终稿剧情验收清单】逐项确认唯一剧情拍点已经执行，并删除非必要的前两章剧情复演。"
            + "终稿前在内部逐段检查净推进：相邻几段可以共同完成一个强调或情绪单元，"
            "但如果整组内容没有带来新动作、新信息、新决定、新后果或必要情绪转折，就必须删除或并入前文。"
            + repetition_boundary
            + opening_acceptance_text
            + (
                f"以下只用于防止机械漂移，不得为了命中数字制造内容：\n{delivery_text}\n"
                if delivery_text else "\n"
            )
            + delivery_audit_text
            + "严格只输出以下两个分区，不输出提纲、摘要、状态JSON、审校报告、评分、修改说明或Markdown代码块：\n"
            "【终稿正文】\n可直接写入章节的完整正文\n\n"
            "【终稿验收】\n"
            + acceptance_schema + "\n"
            + "剧情执行清单只用于组织本章正文，不要求逐项提交逐字证据；正文应保留自然的事件合并，不要为了满足验收格式补写解释。"
            + "人物声纹只检查实际说话人物是否彼此可区分，不要求新增冲突、喜剧、两轮接话或逐字声纹证据。"
            + "previous_chapter_repetition_check只能在对照前两章并删除无新增变量的复演后写true；"
            "logic_continuity_check只能在逐段核对时间顺序、因果、代词唯一指向，以及人物生死、清醒、位置、权限和物件持有状态后写true；"
            "timeline_commitment_check必须先摘出前文已成立的期限或承诺和终稿当前安排；确实都没有时两项写‘无’，"
            "只要存在期限冲突、倒计时被占满或履约时间不足，就必须先修正文，不能把compatible写成true；"
            "提纲内部存在互斥描述时，还必须确认终稿只保留与已确认事实一致的一种状态。"
            "procedural_expansion_check只能在确认没有把非主线调查、核验、审批、封存、交接和记录扩成流程播报后写true；"
            "mechanical_prose_check只能在确认没有同构动作、重复解释、功能性问答和段尾总结形成机械化播报后写true；"
            "这两项是硬约束，明确为false时必须修正文；字段缺失不等于失败。"
            "paragraph_structure_check如模型自行提供，只作诊断，不是重写条件；"
            "role_voice_attribution_check只能在逐句核对说话人、示例句归属和当前问答逻辑后写true。"
        )
    if include_memory:
        instruction = (
            "【终稿编辑任务】\n"
            "依据剧情执行清单和备用正文交付完整终稿。硬性保留本章必须发生、因果顺序、人物状态、物件归属、时间地点和章末承接；"
            "发现硬矛盾时做最小修复，不新增提纲外流程、解释或事件。"
            "正文写法以作者样本和本章声纹表为最高标准：常驻执行人物对白、冲突声纹、日常口语和自然适用的作者原生词，"
            "用它们替换模型惯用表达，但不凑词频、不把低频词写成口头禅。"
            "项目叙事策略只决定本章兑现与情绪方向，不得显性讲解；优先写选择、动作、关系回应和后果，压缩程序过程、专业说明、重复确认和段尾总结。"
            "当前状态快照、下一章记忆选择和未决任务只约束连续性，不是本章待办；当前提纲未明确安排的事项必须保持未决，"
            "不得扩成拍点、对白、核验或处置流程。"
            "自然排版与句式跟随样本读感变化，不执行固定换行、固定短句、固定对白数量或六种主叙事模式。"
            "章首从上一章触发后的新变量开始，章末停在具体动作、对白、信息或后果。"
            "严格输出六个分区：\n"
            "【终稿正文】\n完整正文\n\n"
            "【终稿验收】\n" + acceptance_schema + "\n\n"
            "【实际提纲】\n6-10条概括终稿已发生内容\n\n"
            "【本章摘要】\n简短概括核心事件与情绪变化\n\n"
            "【本章需继承的关键事实】\n只写后文必须继承的变化\n\n"
            "【长篇记忆更新】\n" + _long_form_update_contract_instructions(project or {}, chapter_index)
        )
    else:
        severe_rescue_rewrite = bool(
            rescue_from_candidate
            and any(
                reason.startswith("终稿正文长度明显偏离目标")
                or reason.startswith("终稿结构同时向短碎方向漂移")
                for reason in reasons
            )
        )
        vocabulary_density_rescue = bool(
            rescue_from_candidate
            and any(
                reason.startswith("终稿原生词密度明显高于样本")
                for reason in reasons
            )
        )
        if rescue_from_candidate:
            if severe_rescue_rewrite:
                task_heading = "【终稿整章压缩补救】"
                task_rule = (
                    "上一版终稿的剧情拍点、因果、人物状态和章末钩子必须全部保留，但原来的无效换行、"
                    "重复问答、同义解释和模型化动作标签不是必须保留内容。当前长度和自然读感已经明显漂移，"
                    "必须在本次交付中完成整章压缩重组：合并无效碎片与功能性问答，删除不产生新变量的复述，"
                    "减少无必要台词；不能只做少量同义改写后原样交付，也不能新增解释、流程或事件。"
                )
            else:
                task_heading = "【终稿局部补救】"
                task_rule = (
                    "以上一版终稿为底稿，只修【已确认硬验收问题】列出的硬逻辑、剧情遗漏、明显重复或严重语言漂移。"
                    "未被问题点涉及的剧情、因果、人物状态、自然段落和作者化表达全部保留；不重新规划，不新增解释、流程或事件。"
                )
        elif edit_candidate_in_place:
            task_heading = "【合格底稿轻量校准】"
            task_rule = (
                "当前备用正文的剧情与整体读感已经可用，以它为底稿；允许原样保留合格内容，只校准确有必要的人物口吻、"
                "作者习惯措辞、重复解释和硬逻辑。不得为了留下修改痕迹而拆段、补对白、重排剧情或从零重写。"
            )
        elif execution:
            task_heading = "【仿写终稿任务】"
            task_rule = (
                "根据【剧情执行清单】从零写出完整终稿。清单只规定已经确定的剧情事实、顺序和边界，不是正文措辞或段落模板；"
                "把相邻拍点组织成自然场景，完整落实必须发生与结束变化，不复播上一章结尾，不遗漏前置动作，也不新增提纲外流程。"
            )
        else:
            task_heading = "【首次正文轻量审校】"
            task_rule = (
                "以【首次正文】为底稿，只修硬逻辑、剧情遗漏、明显重复和严重语言漂移；不为段落排版指标重排整章。"
            )
        instruction = (
            task_heading + "\n" + task_rule
            + (
                "【原生词密度补救】必须按已确认问题中的具体次数逐项降低，并在交付前重新统计【作者原生用词池】的全部词。"
                "每项最多保留到该词软上沿再自然多一次；不能把删掉的超密词换成另一个原生词、同义动作标签或判断词，"
                "也不能通过拆句让同一表达重复出现。语义不需要标签时直接省去，必要处保留，不改变剧情。"
                if vocabulary_density_rescue else ""
            )
            + "正文写法以作者样本、人物口吻、习惯词和自然口语为最高标准；优先用选择、动作、关系回应和后果推进，"
            "压缩程序过程、专业说明、同义确认、机械总结和替人物讲道理。"
            "当前状态快照、下一章记忆选择和未决任务只约束连续性，不是本章待办；当前提纲未明确安排的事项必须保持未决，"
            "不得扩成拍点、对白、核验或处置流程。"
            "本章主线不是调查推理时，关于‘能证明什么/不能证明什么’、隐私规则或查询范围最多完整出现一处；"
            "机构人物只承担一个改变结果的动作，不能形成流程辩论。"
            + delivery_audit_text
            + "本次只负责小说正文，不生成或修改长期记忆资料。"
            "严格只输出【终稿正文】和【终稿验收】两个分区；验收JSON为："
            + acceptance_schema
        )
    candidate_limit = 24000
    source_text = draft if (rescue_from_candidate or edit_candidate_in_place) else (execution or draft)
    if len(source_text) > candidate_limit:
        half = (candidate_limit - 20) // 2
        source_text = source_text[:half] + "\n……（中段已截断）……\n" + source_text[-half:]
    leading_blocks = [
        f"【终稿剧情验收清单】\n{plot_acceptance}" if plot_acceptance else "",
        f"【文风重复与推进边界】\n{repetition_boundary}",
        f"【作者原生用词池｜优先替换AI默认措辞】\n{native_vocabulary}" if native_vocabulary else "",
        f"【最近章节原生用词密度｜只作软校准】\n{recent_vocabulary}" if recent_vocabulary else "",
        f"【完整样本文风语言参考｜段落排版指标已删除】\n{reference_profile}" if reference_profile else "",
        f"【已确认硬验收问题｜只修这些问题】\n{reason_text}" if rescue_from_candidate and reason_text else "",
        f"【上次终稿｜保留剧情，只修验收问题】\n{source_text}" if rescue_from_candidate else
        f"【结构已通过的备用正文底稿｜保留剧情与自然段落，只做必要校准】\n{source_text}" if edit_candidate_in_place else
        f"【剧情执行清单｜只继承事实与顺序，必须从零写作】\n{source_text}" if execution else
        f"【首次正文】\n{source_text}",
        f"【本章声纹执行表｜必须逐项落实】\n{chapter_style_plan}" if chapter_style_plan else "",
        f"【本章选定功能片段卡｜只模仿写法，不复制内容】\n{selected_cards_text}" if selected_cards_text else "",
    ]
    trailing_blocks = [
        instruction,
        "【自然表达边界】\n" + _natural_expression_guidance(),
    ]
    index_text = str(memory_selection_index or "").strip() if include_memory else ""
    if index_text:
        base_fixed_length = sum(
            len(block) + 2
            for block in leading_blocks + trailing_blocks
            if block
        )
        index_prefix = "【AI资料更新与下一章选择索引】\n"
        available_index_budget = (
            int(limit or NOVEL_AI_CONTEXT_LIMIT)
            - len(original)
            - base_fixed_length
            - len(index_prefix)
            - 128
        )
        if 4000 <= available_index_budget < len(index_text):
            if isinstance(project, dict):
                index_text = _build_long_form_selection_index(
                    project,
                    chapter_index,
                    limit=available_index_budget,
                )
            else:
                index_text = _clip_context_text(
                    index_text,
                    available_index_budget,
                    preserve_lines=True,
                )
    index_block = f"【AI资料更新与下一章选择索引】\n{index_text}" if index_text else ""
    blocks = leading_blocks + ([index_block] if index_block else []) + trailing_blocks
    fixed_length = sum(len(block) + 2 for block in blocks if block)
    original_budget = max(0, int(limit or NOVEL_AI_CONTEXT_LIMIT) - fixed_length)
    if len(original) > original_budget:
        original = _clip_context_text(original, original_budget, keep_tail=False, preserve_lines=True)
    return "\n\n".join(part for part in [original] + blocks if part)[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]


def _parse_style_finalize_result(value):
    text = str(value or "").strip()
    headings = (
        "终稿正文",
        "实际提纲",
        "本章摘要",
        "本章需继承的关键事实",
    )
    matches = list(re.finditer(
        r"(?m)^【(终稿正文|终稿验收|实际提纲|本章摘要|本章需继承的关键事实|长篇记忆更新)】\s*$",
        text,
    ))
    sections = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.end():end].strip()
    body = sections.get("终稿正文", "")
    acceptance = _parse_style_finalize_acceptance(
        sections.get("终稿验收", "")
    )
    # The independent memory-finalize call owns the outline, summary, facts,
    # and state transaction. A body plus a parseable acceptance block is
    # therefore a usable style result even when the vendor omits those extra
    # sections from this response.
    parsed = bool(body and acceptance)
    if not body and text and not matches:
        body = text
    return {
        "text": body,
        "outline": sections.get("实际提纲", ""),
        "summary": sections.get("本章摘要", ""),
        "key_facts": sections.get("本章需继承的关键事实", ""),
        "acceptance": acceptance,
        "memory_update": _parse_long_form_memory_update(
            "【长篇记忆更新】\n" + sections.get("长篇记忆更新", "")
            if sections.get("长篇记忆更新", "") else ""
        ),
        "parsed": parsed,
    }


def _style_candidate_rank(style_reference, candidate, output_target=0):
    reference = _style_text_structure(style_reference)
    structure = _style_text_structure(candidate)
    target = int(output_target or 0)
    invalid_penalty = 100.0 if structure["chars"] < 300 else 0.0
    if target and not (target * 0.70 <= structure["chars"] <= target * 1.35):
        invalid_penalty += 20.0

    def relative_gap(actual, expected, floor=1.0):
        return abs(float(actual) - float(expected)) / max(float(floor), abs(float(expected)))

    distance = 0.0
    if target:
        distance += relative_gap(structure["chars"], target) * 1.5
    if reference["chars"] >= 500 and structure["chars"] >= 300:
        distance += relative_gap(structure["paragraphs_per_1000"], reference["paragraphs_per_1000"]) * 3.0
        distance += relative_gap(structure["paragraph_median"], reference["paragraph_median"]) * 2.0
        distance += abs(structure["short_paragraph_pct"] - reference["short_paragraph_pct"]) / 100 * 2.0
        distance += abs(
            structure["single_sentence_short_paragraph_pct"]
            - reference["single_sentence_short_paragraph_pct"]
        ) / 100 * 2.5
        distance += abs(structure["long_paragraph_pct"] - reference["long_paragraph_pct"]) / 100 * 1.5
        distance += relative_gap(structure["sentence_median"], reference["sentence_median"]) * 2.0
        distance += abs(structure["dialogue_char_pct"] - reference["dialogue_char_pct"]) / 100 * 1.5
        distance += abs(structure["dialogue_paragraph_pct"] - reference["dialogue_paragraph_pct"]) / 100
        distance += relative_gap(
            structure["dialogue_turns_per_1000"],
            reference["dialogue_turns_per_1000"],
        ) * 1.5
        distance += relative_gap(
            structure["short_dialogue_turns_per_1000"],
            reference["short_dialogue_turns_per_1000"],
        ) * 1.5
    return (round(invalid_penalty + distance, 6),)


def _style_candidate_needs_rescue(style_reference, candidate, output_target=0):
    structure = _style_text_structure(candidate)
    target = int(output_target or 0)
    if structure["chars"] < 300:
        return True
    if target and not (target * 0.55 <= structure["chars"] <= target * 1.65):
        return True
    return False


def _build_style_rewrite_context(
    original_context,
    draft_text,
    reasons,
    limit=NOVEL_AI_CONTEXT_LIMIT,
    style_reference="",
    output_target=0,
    plot_ledger="",
):
    original = str(original_context or "").strip()
    candidate = str(draft_text or "").strip()
    reason_lines = "\n".join(f"- {reason}" for reason in reasons if str(reason or "").strip())
    target = int(output_target or 0) or _style_output_target_from_context(original)
    hard_targets = []
    if target:
        hard_targets.append(f"正文总字数控制在约{round(target * 0.85)}-{round(target * 1.15)}字")
    hard_target_text = "\n".join(f"- {item}" for item in hard_targets)
    ledger = str(plot_ledger or "").strip()
    instruction = (
        "【风格验收未通过：本次必须重写】\n"
        "首次正文的剧情事件、人物关系、设定事实和先后顺序均须保留，不得新增、删减或改换剧情；"
        "只重写叙述方式、句式和段落组织，使其贴近【正文风格参考】。\n"
        + (
            "必须依据剧情事实清单和原项目资料从头重新组织正文，不得沿用首次正文的句子、段落、强调方式和动作镜头。\n"
            if ledger else ""
        )
        +
        f"检测到的偏差：\n{reason_lines or '- 整体读感与样本偏差明显'}\n"
        + (f"本次硬性验收范围：\n{hard_target_text}\n" if hard_target_text else "")
        +
        "上述硬性范围是通过门槛；任何一项未达到就先自行重写，不要提交不合格结果。"
        "不得用简单合并换行应付验收；需要同步调整习惯用词、句式框架、说话标签、不同人物的对白声纹、"
        "叙述与对白衔接、背景铺陈和自然排版读感。"
        "样本反复使用且适合当前语境的词应原样沿用，不得用模型默认同义词替换；局部词不得硬塞或集中堆砌。"
        "只输出重写后的完整正文，不输出标题、说明、分析、指标或修改记录。"
    )
    style_marker = "【AI文风画像】" if "【AI文风画像】" in original else "【风格锁定规则】"
    style_start = original.find(style_marker)
    if style_start >= 0:
        base_context = original[:style_start].strip()
        style_context = _remove_style_layout_metrics(original[style_start:].strip())
    else:
        base_context = original
        style_context = ""

    candidate_limit = 24000
    if len(candidate) > candidate_limit:
        half = (candidate_limit - 20) // 2
        candidate = candidate[:half] + "\n……（中段已截断）……\n" + candidate[-half:]
    candidate_block = (
        "【首次正文剧情事实清单，不含需要继承的文风】\n" + ledger
        if ledger else
        "【首次正文，仅作为保留剧情的重写底稿】\n" + candidate
    )
    fixed_parts = [part for part in (style_context, candidate_block, instruction) if part]
    fixed_length = sum(len(part) + 2 for part in fixed_parts)
    base_budget = max(0, int(limit or NOVEL_AI_CONTEXT_LIMIT) - fixed_length)
    if base_budget <= 0:
        base_context = ""
    elif len(base_context) > base_budget:
        base_context = _clip_context_text(base_context, base_budget, keep_tail=False, preserve_lines=True)
    parts = [part for part in (base_context, style_context, candidate_block, instruction) if part]
    return "\n\n".join(parts)[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]


def _build_style_reference_profile(style_reference, output_target=0, include_structure=True):
    structure = _style_text_structure(style_reference)
    text = structure["text"]
    paragraphs = structure["paragraphs"]
    compact = _compact_text(text)
    total_chars = structure["chars"]
    if not total_chars or not paragraphs:
        return "样本为空，不生成结构画像。"

    paragraph_lengths = structure["paragraph_lengths"]
    sentence_lengths = structure["sentence_lengths"]
    short_paragraphs = sum(length <= 15 for length in paragraph_lengths)
    long_paragraphs = sum(length >= 80 for length in paragraph_lengths)
    paragraph_kinds = [_style_paragraph_kind(paragraph) for paragraph in paragraphs]
    kind_counts = Counter(paragraph_kinds)
    transitions = Counter(zip(paragraph_kinds, paragraph_kinds[1:]))
    connector_terms = (
        "因为", "所以", "但", "不过", "而", "如今", "其实", "原来", "同时", "与此同时",
        "不仅", "虽然", "如果", "只要", "对于", "根本", "已经", "自然", "肯定", "当然",
    )
    connector_counts = [(term, compact.count(term)) for term in connector_terms if compact.count(term)]
    connector_counts.sort(key=lambda item: (-item[1], connector_terms.index(item[0])))
    lexical_groups = (
        ("句首/推理框架", (
            "看到", "听到", "就在这时", "下一刻", "与此同时", "不知为何", "不知过了多久",
            "像是想到了什么", "这说明", "这意味着", "真正", "原来如此", "直到此刻",
        )),
        ("动作修饰词", (
            "突然", "猛地", "骤然", "缓缓", "下意识", "径直", "死死", "用力", "逐渐",
            "立刻", "迅速", "微微", "轻轻", "缓慢", "不由得",
        )),
        ("生理/神态反应", (
            "瞳孔骤然收缩", "瞳孔收缩", "脸色煞白", "咽了口唾沫", "头皮发麻", "后颈发凉",
            "浑身一颤", "愣在原地", "深吸一口气", "眉头紧锁", "倒吸一口凉气", "嘴角一抽",
            "眼角一抽", "喉结滚动", "脸色苍白",
        )),
        ("说话标签", (
            "开口", "说道", "问道", "回答", "喊道", "喃喃", "低声", "沉声", "冷声",
            "淡淡", "沙哑", "轻声", "缓缓开口", "下意识地喊道",
        )),
    )

    def ranked_terms(terms, source_text, minimum=2, limit=10):
        values = [(term, source_text.count(term)) for term in terms if source_text.count(term) >= minimum]
        if not values:
            values = [(term, source_text.count(term)) for term in terms if source_text.count(term)]
        values.sort(key=lambda item: (-item[1], terms.index(item[0])))
        return values[:limit]

    dialogue_matches = re.findall(
        r"“([^”]*)”|「([^」]*)」|『([^』]*)』|\"([^\"\n]*)\"",
        text,
    )
    dialogue_lines = [next((part for part in match if part), "").strip() for match in dialogue_matches]
    dialogue_lines = [line for line in dialogue_lines if line]
    dialogue_compact = _compact_text("\n".join(dialogue_lines))
    dialogue_lengths = [len(_compact_text(line)) for line in dialogue_lines]
    dialogue_particles = (
        "啊", "吧", "呢", "吗", "呀", "哦", "嗯", "喂", "嘿", "呵", "啧", "妈的", "卧槽",
        "怎么", "为什么", "凭什么", "不对", "等等", "算了",
    )
    dialogue_particle_counts = ranked_terms(dialogue_particles, dialogue_compact, minimum=2, limit=10)

    if not include_structure:
        language_lines = [
            f"样本文风语言画像（段落排版指标已删除，只保留用词、口吻、动作反应和说话习惯）：样本约{total_chars}字。",
        ]
        if total_chars < 500:
            language_lines.append("样本不足500字，只以样本原文的口吻、句式和表达习惯为准。")
            return "\n".join(language_lines)
        if connector_counts:
            language_lines.append(
                "高频连接/判断词："
                + "、".join(term for term, _ in connector_counts[:12])
                + "。保留作者真实的重复用词倾向，不要为了词汇变化强行换同义词。"
            )
        for label, terms in lexical_groups:
            ranked = ranked_terms(terms, compact)
            if ranked:
                language_lines.append(
                    f"{label}："
                    + "、".join(term for term, _ in ranked)
                    + "。只在样本对应的语境使用，不集中堆词。"
                )
        language_lines.append(
            "对白高频口语/接话词："
            + (
                "、".join(term for term, _ in dialogue_particle_counts)
                if dialogue_particle_counts else "未发现稳定高频项"
            )
            + "。角色按身份和情绪选择其中一部分，不能让所有人物共享全部口头习惯。"
        )
        language_lines.append("段落排版指标已从正文生成资料中删除；格式只按样本文本的自然读感跟随。")
        return "\n".join(language_lines)

    lines = [
        f"样本结构画像（根据当前样本实时计算，不是固定文风模板）：样本约{total_chars}字，共{len(paragraphs)}个非空段落。",
    ]
    if total_chars < 500:
        lines.append(
            "样本不足500字，结构比例容易失真，不设置段落或对白硬指标；直接以样本原文的口吻、句式和排版为准。"
        )
        return "\n".join(lines)

    paragraphs_per_1000 = len(paragraphs) * 1000 / total_chars
    target = int(output_target or 0)
    if target > 0:
        expected = paragraphs_per_1000 * target / 1000
        lower = max(1, round(expected * 0.85))
        upper = max(lower, round(expected * 1.15))
        target_rule = f"本次预计输出约{target}字时，段落总数参考范围约{lower}-{upper}段"
    else:
        target_rule = f"输出时参考每1000字约{paragraphs_per_1000:.1f}段"
    lines.extend([
        (
            f"段落节奏：样本每1000字约{paragraphs_per_1000:.1f}段；{target_rule}。"
            f"段落长度中位数约{_style_percentile(paragraph_lengths, 0.5)}字，"
            f"中间一半主要落在{_style_percentile(paragraph_lengths, 0.25)}-"
            f"{_style_percentile(paragraph_lengths, 0.75)}字。"
        ),
        (
            f"长短段分布：15字以内段落约占{short_paragraphs * 100 / len(paragraphs):.0f}%，"
            f"80字以上段落约占{long_paragraphs * 100 / len(paragraphs):.0f}%。"
            "按这个比例和穿插方式模仿，不要擅自统一成长段或碎短段。"
        ),
        (
            f"句式节奏：句子长度中位数约{_style_percentile(sentence_lengths, 0.5)}字，"
            f"中间一半主要落在{_style_percentile(sentence_lengths, 0.25)}-"
            f"{_style_percentile(sentence_lengths, 0.75)}字。"
        ),
        (
            f"对白分布：引号内文字约占样本{min(100, structure['dialogue_char_pct']):.0f}%，"
            f"含对白段落约占{structure['dialogue_paragraph_pct']:.0f}%。"
            "只模仿对白密度、长短和插入叙述的方式，不复用对白内容。"
        ),
        (
            f"标点语气：每1000字约有{(compact.count('！') + compact.count('!')) * 1000 / total_chars:.1f}个感叹号、"
            f"{(compact.count('？') + compact.count('?')) * 1000 / total_chars:.1f}个问号、"
            f"{(compact.count('，') + compact.count(',')) * 1000 / total_chars:.1f}个逗号、"
            f"{(compact.count('；') + compact.count(';')) * 1000 / total_chars:.1f}个分号。"
        ),
        (
            "段落功能分布："
            + "、".join(
                f"{kind}约{kind_counts.get(kind, 0) * 100 / len(paragraphs):.0f}%"
                for kind in ("对白", "说明", "动作", "情绪", "强调短段", "叙述")
            )
            + "。这是按完整样本计算的组织倾向，不应被单个代表片段覆盖。"
        ),
        (
            "常见段落衔接："
            + "、".join(
                f"{left}->{right}（{count}次）"
                for (left, right), count in transitions.most_common(6)
            )
            + "。生成时贴近这种功能段落的交替方式，不要连续堆同一种段落。"
        ),
        (
            "高频连接/判断词："
            + "、".join(
                f"{term}（每千字{count * 1000 / total_chars:.1f}次）"
                for term, count in connector_counts[:12]
            )
            + "。保留作者真实的重复用词倾向，不要为了词汇变化强行换同义词。"
        ),
        *(
            f"{label}："
            + "、".join(
                f"{term}（每千字{count * 1000 / total_chars:.1f}次）"
                for term, count in ranked_terms(terms, compact)
            )
            + "。只在样本对应的语境使用，保持接近样本的频率，不要集中堆词。"
            for label, terms in lexical_groups
            if ranked_terms(terms, compact)
        ),
        (
            "对白句长与停顿："
            + (
                f"共识别{len(dialogue_lines)}句对白，单句中位数约{_style_percentile(dialogue_lengths, 0.5)}字，"
                f"中间一半主要落在{_style_percentile(dialogue_lengths, 0.25)}-"
                f"{_style_percentile(dialogue_lengths, 0.75)}字；"
                f"含省略停顿的对白约占{sum(('…' in line or '...' in line) for line in dialogue_lines) * 100 / len(dialogue_lines):.0f}%，"
                f"疑问对白约占{sum(('？' in line or '?' in line) for line in dialogue_lines) * 100 / len(dialogue_lines):.0f}%，"
                f"感叹对白约占{sum(('！' in line or '!' in line) for line in dialogue_lines) * 100 / len(dialogue_lines):.0f}%。"
                if dialogue_lines else
                "样本未识别到稳定对白，不设置对白声纹硬指标。"
            )
        ),
        (
            "对白高频口语/接话词："
            + (
                "、".join(
                    f"{term}（每百句约{count * 100 / max(1, len(dialogue_lines)):.1f}次）"
                    for term, count in dialogue_particle_counts
                )
                if dialogue_particle_counts else "未发现稳定高频项"
            )
            + "。角色可按身份和情绪选择其中一部分，不能让所有人物共享全部口头习惯。"
        ),
        "这些数字用于校准整体分布，允许自然波动；不得为了凑指标破坏语义、剧情和正常段落。",
    ])
    if target > 0:
        desired_count = max(1, round(paragraphs_per_1000 * target / 1000))
        selected = []
        for index in range(desired_count):
            if desired_count <= 1 or len(paragraph_lengths) <= 1:
                source_index = 0
            else:
                source_index = round(index * (len(paragraph_lengths) - 1) / (desired_count - 1))
            length = paragraph_lengths[source_index]
            selected.append("短" if length <= 15 else "长" if length >= 80 else "中")
        rows = [
            " ".join(selected[index:index + 15])
            for index in range(0, len(selected), 15)
        ]
        lines.append(
            f"段落节奏骨架：按样本原有长短段顺序缩放到约{desired_count}段；"
            "短=15字以内，中=16-79字，长=80字以上。按顺序近似落实，不要写完后机械合并换行。\n"
            + "\n".join(rows)
        )
    return "\n".join(lines)


def _render_complete_compact_directory(heading, sections, limit):
    """Fit a reference directory by shortening descriptions, never by dropping refs."""
    try:
        budget = max(0, int(limit or 0))
    except Exception:
        budget = 0
    normalized_sections = []
    for label, rows in sections:
        normalized_rows = []
        for ref, description in rows:
            ref_text = str(ref or "").strip()
            if not ref_text:
                continue
            normalized_rows.append((ref_text, str(description or "").strip()))
        normalized_sections.append((str(label or "").strip(), normalized_rows))

    def render(description_limit):
        lines = [str(heading or "").strip()]
        for label, rows in normalized_sections:
            lines.append(f"{label}：")
            for ref, description in rows:
                clipped = ""
                if description and description_limit > 0:
                    if len(description) <= description_limit:
                        clipped = description
                    elif description_limit == 1:
                        clipped = description[:1]
                    else:
                        clipped = description[:description_limit - 1].rstrip() + "…"
                lines.append(f"{ref}={clipped}" if clipped else ref)
        return "\n".join(line for line in lines if line)

    for description_limit in (160, 120, 96, 72, 56, 40, 28, 20, 12, 0):
        text = render(description_limit)
        if not budget or len(text) <= budget:
            return text

    # Extremely large projects still retain every reference. Packing removes
    # per-item newlines only after all descriptions have already been removed.
    packed_lines = [str(heading or "").strip()]
    for label, rows in normalized_sections:
        refs = [ref for ref, _description in rows]
        packed_lines.append(
            f"{label}：" + json.dumps(refs, ensure_ascii=False, separators=(",", ":"))
        )
    return "\n".join(line for line in packed_lines if line)


def _long_form_state_directory_sections(project, memory=None):
    project = project if isinstance(project, dict) else {}
    memory = memory if isinstance(memory, dict) else _normalize_long_form_memory(
        project.get("long_form_memory", {})
    )
    snapshot = memory.get("state_snapshot", {})
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    reference_maps = _long_form_record_reference_maps(project)
    character_aliases = reference_maps.get("characters", {}).get("id_to_alias", {})
    character_names = {
        str(item.get("id", "") or "").strip(): str(item.get("name", "") or "").strip()
        for item in project.get("characters", []) if isinstance(item, dict)
    }

    character_rows = []
    for item in snapshot.get("character_states", []) if isinstance(snapshot.get("character_states"), list) else []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("character_id", "") or "").strip()
        ref = character_aliases.get(item_id, item_id)
        description = "｜".join(part for part in (
            str(item.get("name", "") or character_names.get(item_id, "")).strip(),
            str(item.get("state", "") or "").strip(),
        ) if part)
        if ref:
            character_rows.append((ref, description))

    relationship_rows = []
    for item in snapshot.get("relationship_states", []) if isinstance(snapshot.get("relationship_states"), list) else []:
        if not isinstance(item, dict):
            continue
        ids = sorted({
            str(value or "").strip()
            for value in item.get("characters", [])
            if str(value or "").strip()
        })
        refs = sorted(character_aliases.get(item_id, item_id) for item_id in ids)
        ref = "|".join(refs)
        names = "、".join(character_names.get(item_id, "") for item_id in ids if character_names.get(item_id, ""))
        description = "｜".join(part for part in (
            names,
            str(item.get("state", "") or "").strip(),
        ) if part)
        if ref:
            relationship_rows.append((ref, description))

    object_rows = []
    for item in snapshot.get("object_states", []) if isinstance(snapshot.get("object_states"), list) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", item.get("name", "")) or "").strip()
        description = "｜".join(part for part in (
            str(item.get("name", "") or "").strip(),
            str(item.get("state", "") or "").strip(),
        ) if part)
        if key:
            object_rows.append((key, description))

    conflict_rows = []
    for item in snapshot.get("active_conflicts", []) if isinstance(snapshot.get("active_conflicts"), list) else []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "") or "").strip()
        if item_id:
            conflict_rows.append((item_id, str(item.get("conflict", "") or "").strip()))

    task_rows = []
    for item in snapshot.get("unresolved_tasks", []) if isinstance(snapshot.get("unresolved_tasks"), list) else []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "") or "").strip()
        if item_id:
            task_rows.append((item_id, str(item.get("task", "") or "").strip()))

    return [
        ("人物状态", character_rows),
        ("关系状态", relationship_rows),
        ("物件状态", object_rows),
        ("活跃冲突", conflict_rows),
        ("未决任务", task_rows),
    ]


def _build_long_form_state_directory(project, limit=LONG_FORM_STATE_DIRECTORY_LIMIT):
    project = project if isinstance(project, dict) else {}
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
    sections = _long_form_state_directory_sections(project, memory)
    counts = [len(rows) for _label, rows in sections]
    heading = (
        "全局紧凑状态目录："
        f"人物状态{counts[0]}项，关系状态{counts[1]}项，物件状态{counts[2]}项，"
        f"活跃冲突{counts[3]}项，未决任务{counts[4]}项。"
    )
    return _render_complete_compact_directory(heading, sections, limit)


def _long_form_existing_state_refs(project, memory=None):
    project = project if isinstance(project, dict) else {}
    memory = memory if isinstance(memory, dict) else _normalize_long_form_memory(
        project.get("long_form_memory", {})
    )
    snapshot = memory.get("state_snapshot", {})
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    object_key_by_compact = {}
    for item in snapshot.get("object_states", []) if isinstance(snapshot.get("object_states"), list) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", item.get("name", "")) or "").strip()
        compact = _compact_text(key)
        if compact and compact not in object_key_by_compact:
            object_key_by_compact[compact] = key
    return {
        "object_key_by_compact": object_key_by_compact,
        "conflict_ids": {
            str(item.get("id", "") or "").strip()
            for item in snapshot.get("active_conflicts", [])
            if isinstance(item, dict) and str(item.get("id", "") or "").strip()
        },
        "task_ids": {
            str(item.get("id", "") or "").strip()
            for item in snapshot.get("unresolved_tasks", [])
            if isinstance(item, dict) and str(item.get("id", "") or "").strip()
        },
    }


def _long_form_issued_state_ids(project, memory=None):
    project = project if isinstance(project, dict) else {}
    memory = memory if isinstance(memory, dict) else _normalize_long_form_memory(
        project.get("long_form_memory", {})
    )
    issued = memory.get("issued_state_ids", {})
    issued = issued if isinstance(issued, dict) else {}
    result = {
        "objects": {
            str(value or "").strip()
            for value in issued.get("objects", [])
            if str(value or "").strip()
        },
        "conflicts": {
            str(value or "").strip()
            for value in issued.get("conflicts", [])
            if str(value or "").strip()
        },
        "tasks": {
            str(value or "").strip()
            for value in issued.get("tasks", [])
            if str(value or "").strip()
        },
    }
    existing = _long_form_existing_state_refs(project, memory)
    result["objects"].update(existing["object_key_by_compact"].values())
    result["conflicts"].update(existing["conflict_ids"])
    result["tasks"].update(existing["task_ids"])
    for chapter in project.get("chapters", []) if isinstance(project.get("chapters"), list) else []:
        if not isinstance(chapter, dict):
            continue
        reconciliation = chapter.get("state_reconciliation", {})
        reconciliation = reconciliation if isinstance(reconciliation, dict) else {}
        result["objects"].update(
            str(value or "").strip()
            for value in reconciliation.get("object_keys", [])
            if str(value or "").strip()
        )
        result["conflicts"].update(
            str(value or "").strip()
            for value in reconciliation.get("conflict_ids", [])
            if str(value or "").strip()
        )
        result["tasks"].update(
            str(value or "").strip()
            for value in reconciliation.get("task_ids", [])
            if str(value or "").strip()
        )
        lifecycle = chapter.get("state_lifecycle_review", {})
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        result["objects"].update(
            str(value or "").strip()
            for value in lifecycle.get("reviewed_object_keys", [])
            if str(value or "").strip()
        )
        result["conflicts"].update(
            str(value or "").strip()
            for value in lifecycle.get("reviewed_conflict_ids", [])
            if str(value or "").strip()
        )
        result["tasks"].update(
            str(value or "").strip()
            for value in lifecycle.get("reviewed_task_ids", [])
            if str(value or "").strip()
        )
        for event in chapter.get("long_term_events", []) if isinstance(chapter.get("long_term_events"), list) else []:
            storage = event.get("storage", {}) if isinstance(event, dict) else {}
            storage = storage if isinstance(storage, dict) else {}
            result["objects"].update(
                str(value or "").strip()
                for value in storage.get("object_keys", [])
                if str(value or "").strip()
            )
            result["conflicts"].update(
                str(value or "").strip()
                for value in storage.get("conflict_ids", [])
                if str(value or "").strip()
            )
            result["tasks"].update(
                str(value or "").strip()
                for value in storage.get("task_ids", [])
                if str(value or "").strip()
            )
        selection = chapter.get("memory_selection", {})
        selection = selection if isinstance(selection, dict) else {}
        result["objects"].update(
            str(value or "").strip()
            for value in selection.get("object_keys", [])
            if str(value or "").strip()
        )
    return result


def _long_form_catalog_from_entries(entries):
    section_keys = (
        "facts", "characters", "relationships", "objects", "conflicts", "tasks",
    )
    normalized_entries = {}
    for key in section_keys:
        values = entries.get(key, {}) if isinstance(entries, dict) else {}
        values = values if isinstance(values, dict) else {}
        normalized_entries[key] = {
            str(item_id): deepcopy(values[item_id])
            for item_id in sorted(values, key=lambda value: str(value))
            if str(item_id).strip()
        }
    sections = {
        key: list(normalized_entries[key])
        for key in section_keys
    }
    canonical = json.dumps(
        normalized_entries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "hash_version": 2,
        "sections": sections,
        "entries": normalized_entries,
        "counts": {key: len(values) for key, values in sections.items()},
        "hashes": {
            key: hashlib.sha256(
                json.dumps(
                    normalized_entries[key],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            for key in section_keys
        },
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _long_form_active_catalog(project, memory=None):
    project = project if isinstance(project, dict) else {}
    memory = memory if isinstance(memory, dict) else _normalize_long_form_memory(
        project.get("long_form_memory", {})
    )
    snapshot = memory.get("state_snapshot", {})
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    entries = {
        "facts": {},
        "characters": {},
        "relationships": {},
        "objects": {},
        "conflicts": {},
        "tasks": {},
    }
    for item in memory.get("active_facts", []):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "") or "").strip()
        if item_id:
            entries["facts"][item_id] = {
                key: deepcopy(item.get(key))
                for key in (
                    "id", "scope", "fact", "status", "source_chapter_id",
                    "source_chapter_index", "evidence", "evidence_chapter_id",
                    "evidence_chapter_index", "supersedes_fact_id",
                    "continuity_details",
                )
                if key in item
            }
    for item in snapshot.get("character_states", []):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("character_id", "") or "").strip()
        if item_id:
            entries["characters"][item_id] = {
                key: deepcopy(item.get(key))
                for key in ("character_id", "name", "state", "source_chapter_id", "source_chapter_index")
                if key in item
            }
    for item in snapshot.get("relationship_states", []):
        if not isinstance(item, dict):
            continue
        refs = sorted({
            str(value or "").strip()
            for value in item.get("characters", [])
            if str(value or "").strip()
        })
        if len(refs) >= 2:
            item_id = "|".join(refs)
            entries["relationships"][item_id] = {
                "characters": refs,
                **{
                    key: deepcopy(item.get(key))
                    for key in ("state", "source_chapter_id", "source_chapter_index")
                    if key in item
                },
            }
    for item in snapshot.get("object_states", []):
        if not isinstance(item, dict):
            continue
        item_id = _compact_text(item.get("key", item.get("name", "")))
        if item_id:
            entries["objects"][item_id] = {
                key: deepcopy(item.get(key))
                for key in (
                    "key", "name", "state", "lore_id", "source_chapter_id",
                    "source_chapter_index",
                )
                if key in item
            }
    for section, snapshot_key, text_key in (
        ("conflicts", "active_conflicts", "conflict"),
        ("tasks", "unresolved_tasks", "task"),
    ):
        for item in snapshot.get(snapshot_key, []):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", "") or "").strip()
            if item_id:
                entries[section][item_id] = {
                    key: deepcopy(item.get(key))
                    for key in (
                        "id", text_key, "source_chapter_id", "source_chapter_index",
                    )
                    if key in item
                }
    return _long_form_catalog_from_entries(entries)


def _long_form_catalog_summary(catalog):
    catalog = catalog if isinstance(catalog, dict) else {}
    return {
        "hash_version": int(catalog.get("hash_version", 1) or 1),
        "counts": deepcopy(catalog.get("counts", {})),
        "hashes": deepcopy(catalog.get("hashes", {})),
        "sha256": str(catalog.get("sha256", "") or ""),
    }


def _long_form_boundary_integrity(project, chapter_index, before_memory, after_memory, payload):
    before = _long_form_active_catalog(project, before_memory)
    after = _long_form_active_catalog(project, after_memory)
    payload = payload if isinstance(payload, dict) else {}
    removals = {key: set() for key in before["sections"]}
    for item in payload.get("fact_updates", []) if isinstance(payload.get("fact_updates"), list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("operation", "") or "").strip().lower() in {"retire", "supersede"}:
            item_id = str(item.get("id", "") or "").strip()
            if item_id:
                removals["facts"].add(item_id)
    retirements = payload.get("state_retirements", {})
    retirements = retirements if isinstance(retirements, dict) else {}
    for ref in retirements.get("character_refs", []) if isinstance(retirements.get("character_refs"), list) else []:
        item_id = _resolve_long_form_record_ref(project, "characters", ref)
        if item_id:
            removals["characters"].add(item_id)
    for value in retirements.get("relationship_refs", []) if isinstance(retirements.get("relationship_refs"), list) else []:
        refs = value if isinstance(value, list) else str(value or "").split("|")
        ids = sorted({
            _resolve_long_form_record_ref(project, "characters", ref)
            for ref in refs
            if _resolve_long_form_record_ref(project, "characters", ref)
        })
        if len(ids) >= 2:
            removals["relationships"].add("|".join(ids))
    removals["objects"].update(
        _compact_text(value)
        for value in retirements.get("object_keys", [])
        if _compact_text(value)
    )
    removals["conflicts"].update(
        str(value or "").strip()
        for value in retirements.get("conflict_ids", [])
        if str(value or "").strip()
    )
    removals["tasks"].update(
        str(value or "").strip()
        for value in retirements.get("task_ids", [])
        if str(value or "").strip()
    )
    expected_sections = {
        key: sorted(set(values) - removals[key])
        for key, values in before["sections"].items()
    }
    missing = {
        key: sorted(set(values) - set(after["sections"].get(key, [])))
        for key, values in expected_sections.items()
    }
    missing = {key: values for key, values in missing.items() if values}
    expected_catalog = _long_form_catalog_from_entries({
        key: {
            item_id: deepcopy(before.get("entries", {}).get(key, {}).get(item_id, {}))
            for item_id in values
        }
        for key, values in expected_sections.items()
    })
    return {
        "version": 2,
        "mode": "deterministic_delta_inheritance",
        "chapter_index": int(chapter_index) + 1,
        "verified": not missing,
        "before": _long_form_catalog_summary(before),
        "expected_inherited": _long_form_catalog_summary(expected_catalog),
        "after": _long_form_catalog_summary(after),
        "explicit_removal_counts": {
            key: len(values) for key, values in removals.items()
        },
        "missing_inherited_refs": missing,
    }


def _long_form_memory_sections(project, selection=None):
    memory = _normalize_long_form_memory(
        (project if isinstance(project, dict) else {}).get("long_form_memory", {})
    )
    selection = selection if isinstance(selection, dict) else {}
    fact_ids = {str(item or "").strip() for item in selection.get("fact_ids", []) if str(item or "").strip()}
    archive_ids = {str(item or "").strip() for item in selection.get("stage_archive_ids", []) if str(item or "").strip()}
    active_facts = [item for item in memory.get("active_facts", []) if isinstance(item, (dict, str))]
    if fact_ids or selection.get("_restrict_facts"):
        active_facts = [
            item for item in active_facts
            if isinstance(item, dict) and str(item.get("id", "") or "").strip() in fact_ids
        ]
    archives = [item for item in memory.get("stage_archives", []) if isinstance(item, dict)]
    if archive_ids or selection.get("_restrict_archives"):
        archives = [item for item in archives if str(item.get("id", "") or "").strip() in archive_ids]
    else:
        archives = archives[-4:]
    if selection.get("_compact_archives"):
        archives = [
            {
                key: deepcopy(item.get(key))
                for key in (
                    "id",
                    "start_chapter_index",
                    "end_chapter_index",
                    "summary",
                    "irreversible_facts",
                    "relationship_changes",
                    "unresolved_threads",
                    "next_stage_entry",
                )
                if item.get(key) not in (None, "", [], {})
            }
            for item in archives
        ]
    snapshot = deepcopy(memory.get("state_snapshot", {}))
    if not isinstance(snapshot, dict):
        snapshot = {}
    if selection.get("_restrict_state"):
        character_ids = {
            str(value or "").strip() for value in selection.get("character_ids", [])
            if str(value or "").strip()
        }
        lore_ids = {
            str(value or "").strip() for value in selection.get("lore_ids", [])
            if str(value or "").strip()
        }
        object_keys = {
            _compact_text(value) for value in selection.get("object_keys", [])
            if _compact_text(value)
        }
        conflict_ids = {
            str(value or "").strip() for value in selection.get("conflict_ids", [])
            if str(value or "").strip()
        }
        task_ids = {
            str(value or "").strip() for value in selection.get("task_ids", [])
            if str(value or "").strip()
        }
        snapshot["character_states"] = [
            item for item in snapshot.get("character_states", [])
            if isinstance(item, dict)
            and str(item.get("character_id", "") or "").strip() in character_ids
        ]
        relationship_states = []
        for item in snapshot.get("relationship_states", []):
            if not isinstance(item, dict):
                continue
            relation_ids = {
                str(value or "").strip()
                for value in item.get("characters", [])
                if str(value or "").strip()
            }
            if selection.get("_relationships_within_selection"):
                selected = bool(relation_ids) and relation_ids.issubset(character_ids)
            else:
                selected = bool(character_ids.intersection(relation_ids))
            if selected:
                relationship_states.append(item)
        snapshot["relationship_states"] = relationship_states
        snapshot["object_states"] = [
            item for item in snapshot.get("object_states", [])
            if isinstance(item, dict)
            and (
                str(item.get("lore_id", "") or "").strip() in lore_ids
                or _compact_text(item.get("key", item.get("name", ""))) in object_keys
            )
        ]
        snapshot["active_conflicts"] = [
            item for item in snapshot.get("active_conflicts", [])
            if isinstance(item, dict)
            and str(item.get("id", "") or "").strip() in conflict_ids
        ]
        snapshot["unresolved_tasks"] = [
            item for item in snapshot.get("unresolved_tasks", [])
            if isinstance(item, dict)
            and str(item.get("id", "") or "").strip() in task_ids
        ]
    if selection.get("_compact_state"):
        reference_maps = _long_form_record_reference_maps(project)
        character_aliases = reference_maps.get("characters", {}).get("id_to_alias", {})
        lore_aliases = reference_maps.get("lore", {}).get("id_to_alias", {})
        snapshot = {
            "as_of_chapter_index": snapshot.get("as_of_chapter_index", 0),
            "story_time": str(snapshot.get("story_time", "") or "").strip(),
            "location": str(snapshot.get("location", "") or "").strip(),
            "character_states": [
                {
                    "ref": character_aliases.get(
                        str(item.get("character_id", "") or "").strip(),
                        str(item.get("character_id", "") or "").strip(),
                    ),
                    "name": str(item.get("name", "") or "").strip(),
                    "state": str(item.get("state", "") or "").strip(),
                }
                for item in snapshot.get("character_states", [])
                if isinstance(item, dict)
            ],
            "relationship_states": [
                {
                    "refs": sorted(
                        character_aliases.get(str(value or "").strip(), str(value or "").strip())
                        for value in item.get("characters", [])
                        if str(value or "").strip()
                    ),
                    "state": str(item.get("state", "") or "").strip(),
                }
                for item in snapshot.get("relationship_states", [])
                if isinstance(item, dict)
            ],
            "object_states": [
                {
                    "key": str(item.get("key", item.get("name", "")) or "").strip(),
                    "name": str(item.get("name", "") or "").strip(),
                    "lore_ref": lore_aliases.get(
                        str(item.get("lore_id", "") or "").strip(),
                        str(item.get("lore_id", "") or "").strip(),
                    ),
                    "state": str(item.get("state", "") or "").strip(),
                }
                for item in snapshot.get("object_states", [])
                if isinstance(item, dict)
            ],
            "active_conflicts": [
                {
                    "id": str(item.get("id", "") or "").strip(),
                    "conflict": str(item.get("conflict", "") or "").strip(),
                }
                for item in snapshot.get("active_conflicts", [])
                if isinstance(item, dict)
            ],
            "unresolved_tasks": [
                {
                    "id": str(item.get("id", "") or "").strip(),
                    "task": str(item.get("task", "") or "").strip(),
                }
                for item in snapshot.get("unresolved_tasks", [])
                if isinstance(item, dict)
            ],
            "notes": str(snapshot.get("notes", "") or "").strip(),
        }
    if selection.get("_compact_facts"):
        active_facts_text = "\n".join(
            f"- {str(item.get('id', '') or '').strip()}｜"
            f"{str(item.get('scope', '') or '').strip()}｜"
            f"{_fact_with_memory_history_context(item, memory, detail_limit=520)}"
            for item in active_facts if isinstance(item, dict)
        ) or "[]"
    else:
        active_facts_text = json.dumps(active_facts, ensure_ascii=False, separators=(",", ":"))
    return {
        "当前状态快照": json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
        "全局紧凑状态目录": _build_long_form_state_directory(project),
        "活跃连续性事实": active_facts_text,
        "近期阶段档案": json.dumps(archives, ensure_ascii=False, separators=(",", ":")),
    }


def _long_form_character_identity_gaps_text(project, chapter_index):
    """Build a small, chapter-scoped checklist for empty character identity fields."""
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter = (
        chapters[chapter_index]
        if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict)
        else {}
    )
    records = project.get("characters", []) if isinstance(project.get("characters"), list) else []
    records_by_id = {
        str(item.get("id", "") or "").strip(): item
        for item in records
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    records_by_name = {
        _compact_text(item.get("name", "")).casefold(): item
        for item in records
        if isinstance(item, dict) and str(item.get("name", "") or "").strip()
    }
    reference_maps = _long_form_record_reference_maps(project).get("characters", {})
    alias_to_id = reference_maps.get("alias_to_id", {})
    selected_ids = []

    def append_id(value):
        raw = str(value or "").strip()
        if not raw:
            return
        resolved = alias_to_id.get(raw, raw)
        if resolved not in records_by_id:
            resolved = records_by_name.get(_compact_text(raw).casefold(), {}).get("id", "")
        if resolved and resolved in records_by_id and resolved not in selected_ids:
            selected_ids.append(resolved)

    for value in chapter.get("actual_linked_character_ids", []) if isinstance(
        chapter.get("actual_linked_character_ids"), list
    ) else []:
        append_id(value)
    selection = chapter.get("memory_selection", {})
    selection = selection if isinstance(selection, dict) else {}
    for value in selection.get("character_ids", []) if isinstance(
        selection.get("character_ids"), list
    ) else []:
        append_id(value)
    for value in chapter.get("linked_characters", []) if isinstance(
        chapter.get("linked_characters"), list
    ) else []:
        append_id(value)

    gaps = []
    id_to_alias = reference_maps.get("id_to_alias", {})
    for item_id in selected_ids:
        record = records_by_id.get(item_id, {})
        missing = [
            field for field in ("goal", "secret", "voice")
            if not str(record.get(field, "") or "").strip()
        ]
        if not missing:
            continue
        name = str(record.get("name", "") or "").strip() or item_id
        alias = id_to_alias.get(item_id, "")
        label = f"{alias}/{name}" if alias else name
        gaps.append(f"{label}：{','.join(missing)}")
    if not gaps:
        return ""
    return (
        "\n【本章空缺人物字段定向检查】"
        "以下是根据本章已关联人物生成的定向清单；最终正文中若人物实际行动、说话或提供关键信息，"
        "必须逐项检查所列空字段并在有证据时使用identity_patch补齐："
        + "；".join(gaps)
        + "。只补正文直接支持的内容；没有直接证据的字段保持空，不要为了填满而猜测。"
    )


def _long_form_record_reference_maps(project):
    project = project if isinstance(project, dict) else {}
    result = {}
    for kind, project_key, prefix in (
        ("characters", "characters", "C"),
        ("lore", "lore", "L"),
        ("foreshadows", "foreshadow_items", "F"),
    ):
        alias_to_id = {}
        id_to_alias = {}
        id_to_record = {}
        code_to_id = {}
        ambiguous_codes = set()
        records = project.get(project_key, []) if isinstance(project.get(project_key), list) else []
        for index, item in enumerate(records, 1):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", "") or "").strip()
            if not item_id:
                continue
            alias = f"{prefix}{index:03d}"
            alias_to_id[alias] = item_id
            id_to_alias[item_id] = alias
            id_to_record[item_id] = item
            if kind == "foreshadows":
                code = _normalize_foreshadow_code(item.get("code", ""))
                existing = code_to_id.get(code, "") if code else ""
                if existing and existing != item_id:
                    ambiguous_codes.add(code)
                elif code:
                    code_to_id[code] = item_id
        for code in ambiguous_codes:
            code_to_id.pop(code, None)
        result[kind] = {
            "alias_to_id": alias_to_id,
            "id_to_alias": id_to_alias,
            "id_to_record": id_to_record,
            "code_to_id": code_to_id,
        }
    return result


def _resolve_long_form_record_ref(project, kind, value):
    ref = str(value or "").strip()
    if not ref:
        return ""
    maps = _long_form_record_reference_maps(project).get(kind, {})
    alias_id = maps.get("alias_to_id", {}).get(ref, "")
    code_id = ""
    if kind == "foreshadows":
        code_id = maps.get("code_to_id", {}).get(
            _normalize_foreshadow_code(ref), ""
        )
    if alias_id and code_id and alias_id != code_id:
        return ""
    if alias_id or code_id:
        return alias_id or code_id
    if ref in maps.get("id_to_record", {}):
        return ref
    return ""


def _repair_invalid_long_form_record_refs_by_name(project, update):
    """Replace invented opaque refs only when an exact record name is unique."""
    project = project if isinstance(project, dict) else {}
    payload = deepcopy(update) if isinstance(update, dict) else {}
    reference_maps = _long_form_record_reference_maps(project)
    project_keys = {
        "characters": "characters",
        "lore": "lore",
        "foreshadows": "foreshadow_items",
    }
    unique_names = {}
    for kind, project_key in project_keys.items():
        by_name = {}
        for item in project.get(project_key, []) if isinstance(project.get(project_key), list) else []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", "") or "").strip()
            name = str(item.get("name", "") or "").strip()
            key = _compact_text(
                _clean_foreshadow_name(name) if kind == "foreshadows" else name
            ).casefold()
            if item_id and key:
                by_name.setdefault(key, set()).add(item_id)
        unique_names[kind] = {
            key: next(iter(ids)) for key, ids in by_name.items() if len(ids) == 1
        }

    candidates = {}

    def remember(kind, ref, name):
        ref = str(ref or "").strip()
        name = str(name or "").strip()
        if not ref or not name or _resolve_long_form_record_ref(project, kind, ref):
            return
        name_key = _compact_text(
            _clean_foreshadow_name(name) if kind == "foreshadows" else name
        ).casefold()
        item_id = unique_names.get(kind, {}).get(name_key, "")
        alias = reference_maps.get(kind, {}).get("id_to_alias", {}).get(item_id, "")
        if alias:
            candidates.setdefault(ref, set()).add(alias)

    state_patch = payload.get("state_patch", {})
    state_patch = state_patch if isinstance(state_patch, dict) else {}
    for item in state_patch.get("character_states", []) if isinstance(state_patch.get("character_states"), list) else []:
        if isinstance(item, dict):
            remember(
                "characters",
                item.get("ref", item.get("character_id", "")),
                item.get("name", item.get("character_name", "")),
            )

    record_updates = payload.get("record_updates", {})
    record_updates = record_updates if isinstance(record_updates, dict) else {}
    for kind in ("characters", "lore"):
        for item in record_updates.get(kind, []) if isinstance(record_updates.get(kind), list) else []:
            if not isinstance(item, dict):
                continue
            remember(
                kind,
                item.get("ref", item.get("id", "")),
                item.get("name", item.get("character_name", item.get("lore_name", ""))),
            )
    for item in payload.get("foreshadow_updates", []) if isinstance(payload.get("foreshadow_updates"), list) else []:
        if isinstance(item, dict):
            remember(
                "foreshadows",
                item.get("ref", item.get("id", "")),
                item.get("name", item.get("foreshadow_name", "")),
            )

    replacements = {
        ref: next(iter(aliases))
        for ref, aliases in candidates.items()
        if len(aliases) == 1
    }
    if not replacements:
        return payload

    def replace_refs(value):
        if isinstance(value, dict):
            return {key: replace_refs(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace_refs(item) for item in value]
        if isinstance(value, str):
            return replacements.get(value, value)
        return value

    return replace_refs(payload)


def _chapter_outline_named_lore_refs(project, chapter_index):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    if chapter_index < 0 or chapter_index >= len(chapters):
        return set()
    chapter = chapters[chapter_index] if isinstance(chapters[chapter_index], dict) else {}
    outline = str(chapter.get("outline", "") or "").strip()
    if not outline:
        return set()
    result = set()
    for item in project.get("lore", []) if isinstance(project.get("lore"), list) else []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "") or "").strip()
        if not item_id:
            continue
        aliases = _record_aliases(item, name_key="name")
        if any(
            len(_compact_text(alias)) >= 2 and _name_in_text(alias, outline)
            for alias in aliases
        ):
            result.add(item_id)
    return result


def _record_runtime_context(project, kind, item_id, limit=700):
    memory = _normalize_long_form_memory(
        (project if isinstance(project, dict) else {}).get("long_form_memory", {})
    )
    entry = memory.get("record_runtime", {}).get(kind, {}).get(str(item_id or ""), {})
    if not isinstance(entry, dict):
        return ""
    parts = []
    state = str(entry.get("state", "") or "").strip()
    if state:
        parts.append("当前动态：" + state)
    developments = entry.get("developments", [])
    if isinstance(developments, list):
        for item in developments[-3:]:
            if not isinstance(item, dict):
                continue
            changes = item.get("changes", [])
            if isinstance(changes, list):
                change_text = "；".join(str(value or "").strip() for value in changes if str(value or "").strip())
            else:
                change_text = str(changes or "").strip()
            if change_text:
                parts.append(f"第{item.get('chapter_index', '')}章变化：{change_text}")
    return _clip_complete_text("｜".join(parts), limit)


def _record_story_layer_context(project, kind, item_id):
    memory = _normalize_long_form_memory(
        (project if isinstance(project, dict) else {}).get("long_form_memory", {})
    )
    entry = memory.get("record_runtime", {}).get(kind, {}).get(str(item_id or ""), {})
    if not isinstance(entry, dict):
        return {}
    return {
        "story_known": str(entry.get("story_known", "") or "").strip(),
        "revealed": str(entry.get("revealed", "") or "").strip(),
        "remaining_secret": str(entry.get("remaining_secret", "") or "").strip(),
    }


def _build_long_form_record_identity_index(
    project,
    limit=LONG_FORM_MEMORY_IDENTITY_INDEX_LIMIT,
):
    """Keep stable C/L/F reference-to-name mappings when the full catalog is packed."""
    project = project if isinstance(project, dict) else {}
    try:
        index_limit = max(1200, int(limit or LONG_FORM_MEMORY_IDENTITY_INDEX_LIMIT))
    except Exception:
        index_limit = LONG_FORM_MEMORY_IDENTITY_INDEX_LIMIT
    reference_maps = _long_form_record_reference_maps(project)
    sections = []
    for kind, source_key, label in (
        ("characters", "characters", "人物"),
        ("lore", "lore", "设定"),
        ("foreshadows", "foreshadow_items", "伏笔"),
    ):
        rows = []
        source = project.get(source_key, [])
        for item in source if isinstance(source, list) else []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", "") or "").strip()
            alias = reference_maps.get(kind, {}).get("id_to_alias", {}).get(item_id, "")
            if not alias:
                continue
            if kind == "characters":
                description = str(item.get("name", "") or "").strip()
            elif kind == "lore":
                description = "｜".join(part for part in (
                    str(item.get("name", "") or "").strip(),
                    str(item.get("type", "") or "").strip(),
                ) if part)
            else:
                description = "｜".join(part for part in (
                    _normalize_foreshadow_code(item.get("code", "")),
                    str(item.get("name", "") or "").strip(),
                    str(item.get("status", "") or "").strip(),
                ) if part)
            rows.append((alias, description))
        sections.append((label, rows))
    heading = "全量稳定名称映射：即使下方动态目录压缩，也必须用这里的C/L/F短引用匹配已有档案。"
    return _render_complete_compact_directory(heading, sections, index_limit)


def _build_long_form_selection_index(project, chapter_index, selection=None, limit=None):
    project = project if isinstance(project, dict) else {}
    try:
        index_limit = int(limit) if limit is not None else LONG_FORM_SELECTION_INDEX_LIMIT
    except Exception:
        index_limit = LONG_FORM_SELECTION_INDEX_LIMIT
    index_limit = max(4000, min(LONG_FORM_SELECTION_INDEX_LIMIT, index_limit))
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter = chapters[chapter_index] if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict) else {}
    next_index = chapter_index + 1
    next_chapter = chapters[next_index] if 0 <= next_index < len(chapters) and isinstance(chapters[next_index], dict) else {}
    reference_maps = _long_form_record_reference_maps(project)
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
    if not isinstance(selection, dict):
        chapter_selection = chapter.get("memory_selection", {})
        selection = chapter_selection if isinstance(chapter_selection, dict) else {}
    restrict_records = bool(selection.get("_restrict_records"))
    finalize_compact_index = bool(selection.get("_finalize_compact_index"))
    selected_record_id_lists = {
        "characters": _normalize_name_list(selection.get("character_ids", [])),
        "lore": _normalize_name_list(selection.get("lore_ids", [])),
        "foreshadows": _normalize_name_list(selection.get("foreshadow_ids", [])),
    }
    selected_record_ids = {
        "characters": {
            str(value or "").strip() for value in selection.get("character_ids", [])
            if str(value or "").strip()
        },
        "lore": {
            str(value or "").strip() for value in selection.get("lore_ids", [])
            if str(value or "").strip()
        },
        "foreshadows": {
            str(value or "").strip() for value in selection.get("foreshadow_ids", [])
            if str(value or "").strip()
        },
    }
    selected_fact_id_list = _normalize_name_list(selection.get("fact_ids", []))
    selected_fact_ids = set(selected_fact_id_list)
    selected_archive_id_list = _normalize_name_list(selection.get("stage_archive_ids", []))
    selected_archive_ids = set(selected_archive_id_list)
    header_lines = [f"当前长篇记忆修订号：{memory.get('revision', 0)}"]
    if not finalize_compact_index:
        header_lines.extend([
            f"下一章序号：{next_index + 1 if next_chapter else '无'}",
            f"下一章标题：{str(next_chapter.get('title', '') or '')}",
            "下一章提纲：" + _clip_complete_text(
                _strip_static_foreshadow_outline_fields(next_chapter.get("outline", "")),
                1800,
            ),
            "下一章初始规划关联人物（仅弱参考，可能因初始人物库不完整而不准确）："
            + "、".join(_normalize_name_list(next_chapter.get("linked_characters", []))),
        ])

    detail_lines = ["当前章已选择记录详情："]
    selected_records_found = False
    for kind, label in (("characters", "人物"), ("lore", "设定"), ("foreshadows", "伏笔")):
        for item_id in selected_record_id_lists[kind]:
            item = reference_maps[kind]["id_to_record"].get(item_id)
            if not isinstance(item, dict):
                continue
            selected_records_found = True
            alias = reference_maps[kind]["id_to_alias"].get(item_id, "")
            if kind == "characters":
                stable = "｜".join(part for part in (
                    str(item.get("name", "") or "").strip(),
                    _clip_complete_text(item.get("role", ""), 180),
                    _record_runtime_context(project, kind, item_id, 360),
                ) if part)
            elif kind == "lore":
                story_layer = _record_story_layer_context(project, kind, item_id)
                stable = "｜".join(part for part in (
                    str(item.get("name", "") or "").strip(),
                    str(item.get("type", "") or "").strip(),
                    "已公开：" + _clip_complete_text(
                        item.get("story_known", "") or story_layer.get("story_known", ""), 320
                    ) if str(item.get("story_known", "") or story_layer.get("story_known", "")).strip() else "",
                    _record_runtime_context(project, kind, item_id, 300),
                ) if part)
            else:
                story_layer = _record_story_layer_context(project, kind, item_id)
                revealed = str(item.get("revealed", "") or story_layer.get("revealed", "") or "").strip()
                remaining = str(item.get("remaining_secret", "") or story_layer.get("remaining_secret", "") or "").strip()
                stable = "｜".join(part for part in (
                    _normalize_foreshadow_code(item.get("code", "")),
                    str(item.get("name", "") or "").strip(),
                    str(item.get("status", "") or "").strip(),
                    "已揭示：" + _clip_complete_text(revealed, 280) if revealed else "",
                    "未揭示：" + _clip_complete_text(remaining, 280) if remaining else "",
                    _record_runtime_context(project, kind, item_id, 260),
                ) if part)
            detail_lines.append(f"- {label} {alias}｜{stable}")

    fact_by_id = {
        str(item.get("id", "") or "").strip(): item
        for item in memory.get("active_facts", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    for item_id in selected_fact_id_list:
        item = fact_by_id.get(item_id)
        if not isinstance(item, dict):
            continue
        selected_records_found = True
        if selection.get("_compact_index_facts"):
            detail_lines.append(f"- 事实 {item_id}")
        else:
            detail_lines.append(
                f"- 事实 {item_id}｜{_clip_complete_text(item.get('scope', ''), 120)}｜"
                f"{_clip_complete_text(item.get('fact', ''), 320)}"
            )
    archive_by_id = {
        str(item.get("id", "") or "").strip(): item
        for item in memory.get("stage_archives", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    for item_id in selected_archive_id_list:
        item = archive_by_id.get(item_id)
        if not isinstance(item, dict):
            continue
        selected_records_found = True
        detail_lines.append(
            f"- 阶段 {item_id}｜第{item.get('start_chapter_index', '')}-"
            f"{item.get('end_chapter_index', '')}章｜{_clip_complete_text(item.get('summary', ''), 420)}"
        )
    if not selected_records_found:
        detail_lines.append("- 暂无；请依据本章正文和下方目录建立增量。")

    character_directory_rows = []
    for item in project.get("characters", []) if isinstance(project.get("characters"), list) else []:
        if isinstance(item, dict):
            item_id = str(item.get("id", "") or "").strip()
            if restrict_records and item_id not in selected_record_ids["characters"]:
                continue
            character_directory_rows.append((
                reference_maps["characters"]["id_to_alias"].get(item_id, ""),
                str(item.get("name", "") or "").strip(),
            ))
    lore_directory_rows = []
    for item in project.get("lore", []) if isinstance(project.get("lore"), list) else []:
        if isinstance(item, dict):
            item_id = str(item.get("id", "") or "").strip()
            if restrict_records and item_id not in selected_record_ids["lore"]:
                continue
            lore_directory_rows.append((
                reference_maps["lore"]["id_to_alias"].get(item_id, ""),
                f"{str(item.get('name', '') or '').strip()}({str(item.get('type', '') or '').strip()})",
            ))
    foreshadow_directory_rows = []
    for item in project.get("foreshadow_items", []) if isinstance(project.get("foreshadow_items"), list) else []:
        if isinstance(item, dict):
            item_id = str(item.get("id", "") or "").strip()
            if restrict_records and item_id not in selected_record_ids["foreshadows"]:
                continue
            foreshadow_directory_rows.append((
                reference_maps["foreshadows"]["id_to_alias"].get(item_id, ""),
                f"{_normalize_foreshadow_code(item.get('code', ''))}|{str(item.get('name', '') or '').strip()}"
                f"({str(item.get('status', '') or '').strip()})",
            ))
    fact_directory_rows = []
    for item in memory.get("active_facts", []):
        if isinstance(item, dict):
            if selection.get("_restrict_facts") and str(item.get("id", "") or "").strip() not in selected_fact_ids:
                continue
            fact_directory_rows.append((
                str(item.get("id", "") or "").strip(),
                "｜".join(part for part in (
                    str(item.get("scope", "") or "").strip(),
                    str(item.get("fact", "") or "").strip(),
                ) if part),
            ))
    archive_directory_rows = []
    for item in memory.get("stage_archives", []):
        if isinstance(item, dict):
            if selection.get("_restrict_archives") and str(item.get("id", "") or "").strip() not in selected_archive_ids:
                continue
            archive_directory_rows.append((
                str(item.get("id", "") or "").strip(),
                f"第{item.get('start_chapter_index', '')}-{item.get('end_chapter_index', '')}章",
            ))

    header_text = _clip_lines_balanced(header_lines, 2800, head=5, tail=0)
    detail_text = _clip_lines_balanced(detail_lines, 9000, head=12, tail=12)
    fixed = "\n\n".join(part for part in (header_text, detail_text) if part)
    directory_sections = [
        ("人物", character_directory_rows),
        ("设定", lore_directory_rows),
        ("伏笔", foreshadow_directory_rows),
        ("活跃事实", fact_directory_rows),
        ("阶段档案", archive_directory_rows),
    ]
    directory_memory = memory
    if selection.get("_restrict_state_directory"):
        directory_selection = deepcopy(selection)
        directory_selection["_compact_state"] = False
        try:
            selected_snapshot = json.loads(
                _long_form_memory_sections(project, directory_selection)["当前状态快照"]
            )
        except Exception:
            selected_snapshot = {}
        directory_memory = deepcopy(memory)
        directory_memory["state_snapshot"] = (
            selected_snapshot if isinstance(selected_snapshot, dict) else {}
        )
    state_directory_sections = _long_form_state_directory_sections(project, directory_memory)
    state_counts = [len(rows) for _label, rows in state_directory_sections]
    state_directory_heading = (
        "全局紧凑状态目录："
        f"人物状态{state_counts[0]}项，关系状态{state_counts[1]}项，"
        f"物件状态{state_counts[2]}项，活跃冲突{state_counts[3]}项，"
        f"未决任务{state_counts[4]}项。"
    )
    if finalize_compact_index:
        state_directory_text = _render_complete_compact_directory(
            state_directory_heading,
            state_directory_sections,
            min(LONG_FORM_STATE_DIRECTORY_LIMIT, max(4000, index_limit - len(fixed) - 2)),
        )
        return "\n\n".join(part for part in (fixed, state_directory_text) if part)
    directory_heading = (
        "全量紧凑引用目录："
        f"人物{len(character_directory_rows)}项，"
        f"设定{len(lore_directory_rows)}项，"
        f"伏笔{len(foreshadow_directory_rows)}项，"
        f"活跃事实{len(fact_directory_rows)}项，"
        f"阶段档案{len(archive_directory_rows)}项，"
        f"人物状态{state_counts[0]}项，关系状态{state_counts[1]}项，"
        f"物件状态{state_counts[2]}项，活跃冲突{state_counts[3]}项，未决任务{state_counts[4]}项。"
    )
    directory_budget = max(
        0,
        index_limit - len(fixed) - 2,
    )
    minimum_record_directory = _render_complete_compact_directory(
        directory_heading, directory_sections, 1
    )
    minimum_state_directory = _render_complete_compact_directory(
        state_directory_heading, state_directory_sections, 1
    )
    if len(minimum_record_directory) + len(minimum_state_directory) + 2 > directory_budget:
        directory_text = _render_complete_compact_directory(
            directory_heading,
            directory_sections + state_directory_sections,
            directory_budget,
        )
    else:
        available_state_budget = max(
            len(minimum_state_directory),
            directory_budget - len(minimum_record_directory) - 2,
        )
        state_directory_text = _render_complete_compact_directory(
            state_directory_heading,
            state_directory_sections,
            min(LONG_FORM_STATE_DIRECTORY_LIMIT, available_state_budget),
        )
        record_directory_budget = max(
            len(minimum_record_directory),
            directory_budget - len(state_directory_text) - 2,
        )
        record_directory_text = _render_complete_compact_directory(
            directory_heading,
            directory_sections,
            record_directory_budget,
        )
        directory_text = record_directory_text + "\n\n" + state_directory_text
    return "\n\n".join(part for part in (fixed, directory_text) if part)


def _parse_long_form_memory_update(value):
    text = str(value or "").strip()
    if not text:
        return {}
    section_match = re.search(r"(?ms)^【长篇记忆更新】\s*(.*?)(?=^【|\Z)", text)
    if section_match:
        text = section_match.group(1).strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.IGNORECASE | re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    start = text.find("{")
    if start < 0:
        return {}
    data, repaired = _load_json_with_single_missing_quote_repair(text[start:])
    if data is None:
        try:
            data, offset = json.JSONDecoder().raw_decode(text[start:])
            trailing = text[start + offset:].strip()
            if trailing and set(trailing) - {"}"}:
                return {}
            repaired = bool(trailing)
        except Exception:
            return {}
    if not isinstance(data, dict):
        return {}
    update = data.get("long_form_memory", data.get("长篇记忆更新", {}))
    if not isinstance(update, dict):
        return {}
    update = deepcopy(update)
    for key in (
        "state_patch",
        "state_snapshot",
        "state_retirements",
        "state_lifecycle_review",
        "fact_updates",
        "fact_lifecycle_review",
        "active_facts",
        "state_delta",
        "long_term_events",
        "state_reconciliation",
        "current_chapter_character_refs",
        "current_chapter_character_ids",
        "stage_archive",
        "record_updates",
        "foreshadow_updates",
        "next_chapter_memory",
        "schema_version",
        "base_revision",
        "compact_delta_version",
        "output_mode",
        "verification",
    ):
        if key not in update and key in data:
            update[key] = deepcopy(data[key])
    if repaired:
        update["_parse_repaired"] = True
    return update


def _long_form_update_contract_example(project, chapter_index):
    memory = _normalize_long_form_memory(
        (project if isinstance(project, dict) else {}).get("long_form_memory", {})
    )
    stage_boundary = (int(chapter_index) + 1) % 10 == 0
    return {
        "schema_version": 2,
        "base_revision": memory.get("revision", 0),
        "state_patch": {
            "story_time": "本章结束时间",
            "location": "本章结束地点与人物位置",
            "character_states": [{"ref": "C001", "name": "人物名", "state": "本章结束状态"}],
            "relationship_states": [{"refs": ["C001", "C002"], "state": "最新关系状态"}],
            "object_states": [{"key": "稳定物品键", "name": "物品名", "state": "最新位置或归属"}],
            "active_conflicts": [{
                "id": "更新已有冲突时填CF-ID；新增时留空",
                "key": "新增冲突临时键NCF1",
                "previous_conflict": "更新已有冲突时逐字复制旧冲突",
                "conflict": "仍在持续的冲突",
            }],
            "unresolved_tasks": [{
                "id": "更新已有任务时填TASK-ID；新增时留空",
                "key": "新增任务临时键NTASK1",
                "previous_task": "更新已有任务时逐字复制旧任务",
                "task": "仍未完成的任务",
            }],
            "notes": "下一章必须继承的结束状态",
        },
        "state_retirements": {
            "character_refs": [],
            "relationship_refs": [],
            "object_keys": [],
            "conflict_ids": [],
            "task_ids": [],
        },
        "state_lifecycle_review": {
            "scope": LONG_FORM_STAGE_REVIEW_SCOPE if stage_boundary else "current_chapter",
            "reviewed_object_keys": [],
            "reviewed_conflict_refs": [],
            "reviewed_task_refs": [],
            "notes": "已复核继续有效、已完成、已失效和应退出的物件、冲突与任务",
        },
        "fact_updates": [
            {
                "operation": "add|keep|update|retire|supersede",
                "key": "新增或取代后新事实的临时键NF1",
                "id": "keep/update/retire/supersede时填已有AF-ID",
                "scope": "稳定事实主题，例如character:C001:medical_status",
                "previous_fact": "retire/supersede时逐字复制被退出的旧事实",
                "fact": "add/update/supersede后的长期有效事实",
                "reason": "retire/supersede时说明退出或取代原因",
                "evidence_quote": "最终正文中的逐字短句",
            }
        ],
        "fact_lifecycle_review": {
            "scope": LONG_FORM_STAGE_REVIEW_SCOPE if stage_boundary else "current_chapter",
            "reviewed_refs": [],
            "notes": "已复核继续有效、已兑现、已失效和被取代事实",
        },
        "long_term_events": [
            {
                "event": "本章会影响后文的承诺、证据、能力边界、任务、伏笔或关键物",
                "category": "commitment|evidence|ability_boundary|task|foreshadow|key_object|relationship|other",
                "evidence_quote": "最终正文中的逐字短句",
                "storage": {
                    "fact_refs": ["NF1"],
                    "character_refs": [],
                    "lore_refs": [],
                    "foreshadow_refs": [],
                    "object_keys": [],
                    "conflict_refs": [],
                    "task_refs": [],
                },
            }
        ],
        "state_reconciliation": {
            "checked": True,
            "coverage_checks": {
                "named_character_actions": True,
                "state_changes": True,
                "evidence_and_unknowns": True,
                "mechanism_claims_match_body": True,
                "rules_and_boundaries": True,
                "foreshadow_and_ending": True,
            },
            "fact_refs": [],
            "character_refs": [],
            "lore_refs": [],
            "foreshadow_refs": [],
            "relationship_refs": [],
            "object_keys": [],
            "conflict_refs": [],
            "task_refs": [],
            "record_runtime_review": {
                "reviewed_lore_refs": [],
                "unchanged_lore_refs": [],
                "reviewed_foreshadow_refs": [],
                "unchanged_foreshadow_refs": [],
            },
            "resolved_contradictions": [],
            "notes": "已对照最终正文统一检查各状态分区",
        },
        "state_delta": {"characters": [], "relationships": [], "objects": [], "conflicts": [], "tasks": []},
        "current_chapter_character_refs": ["C001"],
        "stage_archive": (
            {
                "summary": "最近十章阶段成果",
                "irreversible_facts": [],
                "relationship_changes": [],
                "unresolved_threads": [],
                "next_stage_entry": "下一阶段承接点",
            }
            if stage_boundary else None
        ),
        "record_updates": {
            "characters": [
                {
                    "operation": "update|create",
                    "ref": "更新填C引用；新增留空",
                    "key": "新增临时键NC1",
                    "name": "新增时填写稳定姓名；临时人物升级时填写正文明确的新姓名",
                    "state": "当前动态状态，不重写永久身份、长期目标、秘密或语言",
                    "changes": ["本章长期变化"],
                    "canon": {
                        "role": "正文明确的身份",
                        "goal": "正文明确的目标；无证据留空",
                        "secret": "正文明确且值得保留的隐情；无证据留空",
                        "voice": "正文中足够明显的语言/口吻特征；证据不足留空",
                        "notes": "正文明确的关系、经历或其他长期信息",
                    },
                    "evidence_quote": "最终正文中的逐字短句",
                }
            ],
            "lore": [
                {
                    "operation": "update|create",
                    "ref": "更新填L引用；新增留空",
                    "key": "新增临时键NL1",
                    "name": "新增时填写稳定名称",
                    "state": "本章确立的动态状态",
                    "story_known": "正文已公开确立、后续可直接使用的设定内容",
                    "changes": ["本章长期变化"],
                    "canon": {"type": "仅新增时填写", "description": "仅新增时填写通用定义"},
                    "evidence_quote": "最终正文中的逐字短句",
                }
            ],
        },
        "foreshadow_updates": [
            {
                "operation": "update|create",
                "ref": "更新填F引用；新增留空",
                "key": "新增临时键NT1",
                "name": "新增时填写稳定名称",
                "status": "未埋|已埋|已回收|无需回收|废弃",
                "state": "本章推进或回收情况",
                "setup_chapter": "实际埋设章；程序可按当前章补齐",
                "payoff_chapter": "实际回收章；程序可按当前章补齐",
                "revealed": "截至本章正文已明确揭示的内容",
                "remaining_secret": "截至本章仍未揭示的边界，可为空",
                "canon": {"description": "仅新增时填写完整计划", "setup_chapter": "", "payoff_chapter": ""},
                "evidence_quote": "最终正文中的逐字短句",
            }
        ],
        "next_chapter_memory": {
            "character_refs": [],
            "lore_refs": [],
            "foreshadow_refs": [],
            "fact_refs": [],
            "stage_archive_refs": ["CURRENT_STAGE"] if stage_boundary else [],
            "object_keys": [],
            "conflict_refs": [],
            "task_refs": [],
            "reason": "选择依据",
        },
    }


def _long_form_compact_update_contract_instructions(project, chapter_index):
    project = project if isinstance(project, dict) else {}
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter = (
        chapters[chapter_index]
        if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict)
        else {}
    )
    selection = chapter.get("memory_selection", {})
    selection = selection if isinstance(selection, dict) else {}
    existing_fact_ids = {
        str(item.get("id", "") or "").strip()
        for item in memory.get("active_facts", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    required_fact_refs = sorted({
        str(value or "").strip()
        for value in selection.get("fact_ids", [])
        if str(value or "").strip() in existing_fact_ids
    })
    existing_state_refs = _long_form_existing_state_refs(project, memory)
    required_objects = []
    for value in selection.get("object_keys", []) if isinstance(selection.get("object_keys"), list) else []:
        canonical = existing_state_refs["object_key_by_compact"].get(_compact_text(value), "")
        if canonical and canonical not in required_objects:
            required_objects.append(canonical)
    required_conflicts = sorted({
        str(value or "").strip()
        for value in selection.get("conflict_ids", [])
        if str(value or "").strip() in existing_state_refs["conflict_ids"]
    })
    required_tasks = sorted({
        str(value or "").strip()
        for value in selection.get("task_ids", [])
        if str(value or "").strip() in existing_state_refs["task_ids"]
    })
    outlined_lore_ids = _chapter_outline_named_lore_refs(project, chapter_index)
    lore_aliases = _long_form_record_reference_maps(project).get("lore", {}).get(
        "id_to_alias", {}
    )
    outlined_lore_refs = sorted(
        lore_aliases.get(item_id, item_id) for item_id in outlined_lore_ids
    )
    stage_boundary = (chapter_index + 1) % 10 == 0
    catalog_summary = json.dumps(
        _long_form_catalog_summary(_long_form_active_catalog(project, memory)),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    example = {
        "schema_version": 2,
        "base_revision": int(memory.get("revision", 0) or 0),
        "compact_delta_version": LONG_FORM_COMPACT_DELTA_VERSION,
        "state_patch": {
            "story_time": "",
            "location": "",
            "character_states": [],
            "relationship_states": [],
            "object_states": [],
            "active_conflicts": [],
            "unresolved_tasks": [],
            "notes": "",
        },
        "state_retirements": {
            "character_refs": [],
            "relationship_refs": [],
            "object_keys": [],
            "conflict_ids": [],
            "task_ids": [],
        },
        "fact_updates": [],
        "record_updates": {"characters": [], "lore": []},
        "foreshadow_updates": [],
        "long_term_events": [],
        "current_chapter_character_refs": [],
        "stage_archive": ({
            "summary": "最近十章阶段成果",
            "irreversible_facts": [],
            "relationship_changes": [],
            "unresolved_threads": [],
            "next_stage_entry": "下一阶段承接点",
        } if stage_boundary else None),
        "next_chapter_memory": {
            "character_refs": [],
            "lore_refs": [],
            "foreshadow_refs": [],
            "fact_refs": [],
            "stage_archive_refs": ["CURRENT_STAGE"] if stage_boundary else [],
            "object_keys": [],
            "conflict_refs": [],
            "task_refs": [],
            "reason": "",
        },
        "verification": {
            "checked": True,
            "coverage_checks": {
                "named_character_actions": True,
                "state_changes": True,
                "evidence_and_unknowns": True,
                "mechanism_claims_match_body": True,
                "rules_and_boundaries": True,
                "foreshadow_and_ending": True,
            },
            "runtime_unchanged": {
                "lore_refs": [],
                "foreshadow_refs": [],
            },
            "resolved_contradictions": [],
            "notes": "",
        },
    }
    required_state_text = json.dumps({
        "object_keys": required_objects,
        "conflict_refs": required_conflicts,
        "task_refs": required_tasks,
    }, ensure_ascii=False, separators=(",", ":"))
    identity_gap_text = _long_form_character_identity_gaps_text(project, chapter_index)
    return (
        "只输出版本2长篇记忆增量的紧凑语义格式。这是严格增量，不是全量总结。"
        "AI仍负责判断发生了什么、哪些旧状态改变或退出、证据是什么、"
        "哪些资料传给下一章；程序只根据这些显式决定补齐重复的生命周期数组、核对引用和存储索引。"
        "不得输出fact_lifecycle_review、state_lifecycle_review、state_reconciliation或完整旧状态，它们由程序机械生成。"
        "程序生成的fact_lifecycle_review.scope和state_lifecycle_review.scope必须为"
        f"{LONG_FORM_STAGE_REVIEW_SCOPE if stage_boundary else 'current_chapter'}。"
        "未出现在增量里的旧资料默认保留并原样继承；只有fact_updates的retire/supersede和state_retirements可以退出旧状态。"
        "十章边界全部未触及状态由程序原样继承，并按数量和SHA256核验。"
        f"fact_updates最多{LONG_FORM_MAX_FACT_UPDATES}项，long_term_events最多{LONG_FORM_MAX_LONG_TERM_EVENTS}项，"
        f"人物、设定、伏笔更新每类最多{LONG_FORM_MAX_RECORD_UPDATES}项，state_patch各数组最多{LONG_FORM_MAX_STATE_ITEMS}项。"
        "相同语义必须合并，不得在多个同类条目中重复表达。普通章节建议fact_updates 1-4项、long_term_events 1-3项，"
        "但完整性高于建议数量。JSON应使用紧凑格式，不缩进、不输出空白说明；普通章节目标总长度不超过7000字。"
        "核对、封存、编号、取样、审批、交接、见证、记录固定和责任说明等一次性操作，默认不构成跨章记忆。"
        "只有后文必须使用同一批次、准确持有人、访问权限、未完成任务或该操作本身就是伏笔时才单独保存；"
        "否则把过程合并进它造成的最终结果，不得逐步拆成事实、事件、物件和任务。"
        "fact_updates的operation只能是add/keep/update/retire/supersede。add和supersede使用NF临时key；"
        "update/retire/supersede必须填写已有AF-ID、原scope，retire/supersede还要逐字填写previous_fact和reason。"
        "scope改变、主体改变或资料类型改变时必须add，不能借用旧事实ID。"
        "不能因为新增了一条更宽泛的概括而退役精确旧事实；仍有效的精确旧事实必须继续保留。"
        "本章选择索引中未发生变化的已有事实由程序自动保留并生成复核索引，不得为它们输出keep；"
        "fact_updates只提交正文明确新增、更新、退出或取代的事实。"
        "record_updates只写人物或设定的动态变化。新人物create使用NC/NL临时key并填写稳定名称和canon；人物canon的role、goal、secret、voice、notes逐项只填写最终正文能够支持的内容，不能为了填满字段猜测。人物字段必须独立判断：直接对白足够辨识时必须提取voice；明确争夺资源/机缘、控制或进入地点、保护/排除/追杀/阻止对象、职责或利益诉求时必须提取goal；只有正文明确揭示的隐情才提取secret。不能因为secret无证据而连带留空goal或voice。"
        "已有人物若正文补出了此前空缺的身份、目标、秘密或语言风格，使用identity_patch逐项补齐；程序保留已有内容，并只追加正文有证据的新补充，不覆盖或替换旧资料。已有姓名未明或临时称谓人物正式命名时，继续沿用原人物ref并用name升级同一ID。"
        "如果正文把已有的姓名未明或临时称谓人物正式命名，必须沿用原人物ref并用update填写name为正式姓名，"
        "不得新建第二张人物卡；只有正文没有对应旧人物时才create。"
        "不得改写导入的人物卡、设定定义或伏笔计划。新增记录不要生成真实ID，真实ID由程序分配。"
        "foreshadow_updates只写本章实际埋设、推进、回收或废弃的伏笔；create使用NT临时key。"
        "state_patch只写本章结束时新增或变化的时间、地点、人物、关系、物件、冲突和任务；"
        "更新已有冲突或任务必须填写真实ID及previous_conflict/previous_task，新增使用NCF/NTASK临时key。"
        "所有非keep事实更新、人物/设定/伏笔更新以及state_patch变化都必须附最终正文中的8-60字连续逐字evidence_quote。"
        "每个会影响后文的事件还必须进入long_term_events一次，并用storage明确指向fact_refs、character_refs、lore_refs、"
        "foreshadow_refs、object_keys、conflict_refs或task_refs中的真实落点；同一证据涉及多个落点时合并为一个事件。"
        "所有event及动态更新只能依据最终正文已经公开或明确发生的内容。疑似、可能、比喻、感官相似、来源不明和人物猜测"
        "不得改成确定机制；原数量、范围、伤势程度、权限和未知边界必须保留。"
        "不得只因提纲或项目资料出现该名称，就声称正文已经使用、确认或公开它。"
        + identity_gap_text
        + _LONG_TERM_RECORD_CLASSIFICATION_RULES
        + "current_chapter_character_refs必须列出本章实际行动、说话、来电或提供关键信息的已有/本次新增命名人物。"
        "verification.checked及六项coverage_checks只能在逐段核对正文后写true。"
        "verification.runtime_unchanged必须列出本章提纲或long_term_events触及、但正文没有改变运行态的设定和伏笔；"
        "已经进入record_updates或foreshadow_updates的引用不要再列为unchanged。"
        f"本章必须复核的已有事实为{json.dumps(required_fact_refs, ensure_ascii=False, separators=(',', ':'))}；"
        f"必须复核的已有物件/冲突/任务为{required_state_text}；"
        f"原提纲直接点名、必须给出更新或runtime_unchanged结论的设定ID为{json.dumps(outlined_lore_refs, ensure_ascii=False, separators=(',', ':'))}。"
        "next_chapter_memory只选择下一章真正需要的引用和状态键；本章新增且会影响下一章的资料必须选入。"
        "next_chapter_memory可直接使用本次新增的NC/NL/NT/NF临时key，真实ID仍由程序统一分配。"
        + (
            "本章是十章边界，stage_archive必须完整总结最近十章，并在需要承接时选择CURRENT_STAGE。"
            if stage_boundary else
            "本章不是十章边界，stage_archive必须为null。"
        )
        + f"当前全量集合只供程序核验，不得复制到输出：{catalog_summary}。"
        + "base_revision必须原样填写当前修订号。以下对象必须作为顶层long_form_memory字段的值，不得把这些字段散落到顶层："
        + json.dumps(example, ensure_ascii=False, separators=(",", ":"))
    )


def _long_form_update_contract_instructions(project, chapter_index, compact=False):
    if compact:
        return _long_form_compact_update_contract_instructions(project, chapter_index)
    project = project if isinstance(project, dict) else {}
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
    stage_boundary = (int(chapter_index) + 1) % 10 == 0
    existing_fact_ids = {
        str(item.get("id", "") or "").strip()
        for item in memory.get("active_facts", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter = (
        chapters[chapter_index]
        if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict)
        else {}
    )
    selection = chapter.get("memory_selection", {})
    selection = selection if isinstance(selection, dict) else {}
    required_review_refs = sorted({
        str(value or "").strip()
        for value in selection.get("fact_ids", [])
        if str(value or "").strip() in existing_fact_ids
    })
    required_review_text = json.dumps(required_review_refs, ensure_ascii=False, separators=(",", ":"))
    outlined_lore_ids = _chapter_outline_named_lore_refs(project, chapter_index)
    lore_aliases = _long_form_record_reference_maps(project).get("lore", {}).get(
        "id_to_alias", {}
    )
    outlined_lore_refs = sorted(
        lore_aliases.get(item_id, item_id) for item_id in outlined_lore_ids
    )
    outlined_lore_text = json.dumps(
        outlined_lore_refs, ensure_ascii=False, separators=(",", ":")
    )
    existing_state_refs = _long_form_existing_state_refs(project, memory)
    selected_object_keys = []
    for value in selection.get("object_keys", []) if isinstance(selection.get("object_keys"), list) else []:
        canonical = existing_state_refs["object_key_by_compact"].get(_compact_text(value), "")
        if canonical and canonical not in selected_object_keys:
            selected_object_keys.append(canonical)
    selected_conflict_values = selection.get("conflict_ids", [])
    selected_conflict_values = selected_conflict_values if isinstance(selected_conflict_values, list) else []
    selected_conflict_ids = sorted({
        str(value or "").strip()
        for value in selected_conflict_values
        if str(value or "").strip() in existing_state_refs["conflict_ids"]
    })
    selected_task_values = selection.get("task_ids", [])
    selected_task_values = selected_task_values if isinstance(selected_task_values, list) else []
    selected_task_ids = sorted({
        str(value or "").strip()
        for value in selected_task_values
        if str(value or "").strip() in existing_state_refs["task_ids"]
    })
    required_state_review = {
        "object_keys": sorted(selected_object_keys),
        "conflict_refs": selected_conflict_ids,
        "task_refs": selected_task_ids,
    }
    required_state_review_text = json.dumps(
        required_state_review, ensure_ascii=False, separators=(",", ":")
    )
    example_payload = _long_form_update_contract_example(project, chapter_index)
    example_payload["fact_lifecycle_review"]["reviewed_refs"] = required_review_refs
    example_payload["state_lifecycle_review"]["reviewed_object_keys"] = required_state_review["object_keys"]
    example_payload["state_lifecycle_review"]["reviewed_conflict_refs"] = required_state_review["conflict_refs"]
    example_payload["state_lifecycle_review"]["reviewed_task_refs"] = required_state_review["task_refs"]
    example_payload["state_reconciliation"]["lore_refs"] = outlined_lore_refs
    example_payload["state_reconciliation"]["record_runtime_review"][
        "reviewed_lore_refs"
    ] = outlined_lore_refs
    example = json.dumps(example_payload, ensure_ascii=False, separators=(",", ":"))
    catalog_summary = json.dumps(
        _long_form_catalog_summary(_long_form_active_catalog(project, memory)),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    identity_gap_text = _long_form_character_identity_gaps_text(project, chapter_index)
    return (
        "只输出以下版本2长篇记忆增量，不得返回完整旧事实清单，也不得改写导入的人物卡、设定定义或伏笔计划。"
        "未出现在增量里的旧资料默认保留；只有fact_updates中的retire/supersede和state_retirements可以让旧状态退出。"
        "这是严格增量，不是全量总结：普通章节只返回本章新增、改变、明确结束或被本章正文直接核对的项目；"
        f"fact_updates最多{LONG_FORM_MAX_FACT_UPDATES}项，long_term_events最多{LONG_FORM_MAX_LONG_TERM_EVENTS}项，"
        f"人物/设定/伏笔更新每类最多{LONG_FORM_MAX_RECORD_UPDATES}项，state_patch各列表最多{LONG_FORM_MAX_STATE_ITEMS}项。"
        "若同一变化可归并为一条，必须合并；不要为了覆盖正文中的每个句子制造状态条目。"
        "核对、封存、编号、取样、审批、交接、见证、记录固定和责任说明等一次性操作默认不跨章保存；"
        "只有后文必须使用同一批次、持有人、权限、未完成任务或伏笔时才单独记录，否则只保留其最终剧情结果。"
        "人物、设定和伏笔更新必须使用【AI资料更新与下一章选择索引】中的C/L/F短引用；新增记录不要生成ID，只填写临时key，真实ID由程序分配。"
        "新增、修改或退出事实必须使用已有AF-ID或新增临时key；source_chapter_id由程序填写。"
        "事实operation只能是add/keep/update/retire/supersede：keep表示复核后继续有效；"
        "update和supersede都只允许在与旧事实完全相同的scope内使用：update表示同主题推进，supersede表示同主题的新版本明确取代旧版本。"
        "主体、资料类型或scope变了必须add新事实；旧事实按其自身是否仍有效单独keep或retire，绝不能挂成跨主题替代链。"
        "不得把治疗条件更新或替代成药材库存、把诊疗交接更新或替代成协议调查等不同主题。"
        "retire只允许在最终正文直接证明旧事实所描述的精确状态已经结束或失效时使用；"
        "retire和supersede必须原样填写旧事实的scope和previous_fact，且只能处理本章选择索引已提供的AF-ID；"
        "如果证据仍写着该伤势、限制、任务、关系或风险继续存在，就必须keep或同scope更新，绝不能因为新增了一条更宽泛的概括而退役精确旧事实。"
        "部分恢复只更新已经改变的部分，不得把仍存在的部位、程度、数量、诊断细节或不确定性一起删除。"
        "必须填写fact_lifecycle_review；reviewed_refs只能填写已经存在的AF-ID，绝不能填写本次新增的NF临时key。"
        f"本章reviewed_refs至少必须包含这些已有事实ID：{required_review_text}；"
        "fact_updates中keep/update/retire/supersede触及的其他已有AF-ID也必须加入。"
        + (
            f"当前是十章边界，fact_lifecycle_review.scope必须为{LONG_FORM_STAGE_REVIEW_SCOPE}；"
            "只回显本章选择、触及、修订或退出的AF-ID，绝不能回显全部活跃事实。"
            "全部未触及事实由程序原样继承，并按数量和SHA256核验。"
            if stage_boundary else
            "fact_lifecycle_review.scope必须为current_chapter，只复核当前章相关事实。"
        )
        + "必须填写state_lifecycle_review；其中只能引用全局紧凑状态目录里本次调用前已经存在的物件键、CF-ID和TASK-ID，"
        "引用字段严格分区：lore_refs只能填写人物设定库中的设定编号或设定别名；"
        "object_keys只能填写状态快照或本次state_patch中真实存在的具体物件键；"
        "设定ID、伏笔ID、事实ID和设定名称即使指向某个物品，也不得放入object_keys；没有真实物件状态时object_keys必须为空。"
        "不得填写本次新增的NCF/NTASK临时key。"
        f"三组复核数组至少必须完整包含：{required_state_review_text}；"
        + (
            f"当前是十章边界，state_lifecycle_review.scope必须为{LONG_FORM_STAGE_REVIEW_SCOPE}；"
            "只回显本章选择、触及、修订或退出的物件、冲突和任务，绝不能回显全量目录。"
            "全部未触及状态由程序原样继承，并按数量和SHA256核验。"
            if stage_boundary else
            "state_lifecycle_review.scope必须为current_chapter；复核本章已选及本章触及的物件、冲突和任务。"
        )
        + "record_updates只记录动态状态和本章变化；新人物使用canon逐项填写正文有证据的身份、目标、秘密、语言风格和备注，不能猜测。人物字段必须独立判断：直接对白足够辨识时必须提取voice；明确争夺资源/机缘、控制或进入地点、保护/排除/追杀/阻止对象、职责或利益诉求时必须提取goal；只有正文明确揭示的隐情才提取secret。不能因为secret无证据而连带留空goal或voice。已有角色只在正文补出原卡空缺信息时使用identity_patch逐项补齐，程序保留已有内容并追加明确的新补充，不覆盖或替换旧资料。已有临时人物正式命名时也使用原ref和identity_patch完成同一ID升级。"
        "已有临时人物在正文中获得正式姓名时，必须用原ref加name完成同一ID升级；不能把正式姓名另建为新人物。"
        "所有fact_updates、record_updates和foreshadow_updates必须附带最终正文中连续逐字出现的8-60字evidence_quote。"
        "keep不改写事实，可不填evidence_quote；其余事实操作必须有逐字证据。"
        "state_patch只写本章新增或变化的状态，未变化项省略；已结束冲突、任务或对象必须放入state_retirements。"
        "story_time、location和notes只保留本章结束时真正需要下一章继承的最短状态；state_delta只记录归类后的少量变化，不复制正文流水账。"
        "更新已有CF-ID或TASK-ID时必须分别逐字填写previous_conflict或previous_task，确认仍是同一冲突或任务；"
        "新语义必须新建临时key，绝不能借用旧ID。"
        "新增冲突或任务绝不能猜测新的CF-ID/TASK-ID：id必须留空，并分别填写NCF1/NTASK1形式的临时key；"
        "同一临时key必须进入long_term_events、state_reconciliation和next_chapter_memory中需要引用的位置，真实ID由程序分配。"
        "必须输出state_reconciliation.checked=true，对照最终正文统一检查事实、人物、关系、物件、冲突、任务和伏笔分区；"
        "state_reconciliation.coverage_checks中的六项必须全部为true，分别确认命名人物行动、状态变化、"
        "证据与未知边界、机制名词与正文一致、规则与责任边界、伏笔与章末持续状态均已逐段核对。"
        "mechanism_claims_match_body只能在逐项确认后写true：摘要、事实、事件、状态和运行态中的机制名词、因果、能力来源或共鸣关系，"
        "必须由最终正文明确说出；正文里的比喻、感官相似、人物猜测、疑似、来源不明或尚待验证，"
        "不得在状态中改写成确定机制。正文没有机制名时保留可观察现象并明确来源未知。"
        "所有本次触及的引用都必须进入对应检查数组，发现矛盾必须在同一增量中更新或退出旧状态。"
        f"当前提纲直接点名的设定引用为{outlined_lore_text}；这些设定必须全部进入state_reconciliation.lore_refs和"
        "record_runtime_review.reviewed_lore_refs。逐项对照最终正文：正文确实推进其公开层、路线、权限、位置或状态时更新record_updates.lore，"
        "正文没有推进时才放入unchanged_lore_refs；提纲点名本身不能当作正文证据。"
        "最终正文中实际行动、说话、来电或提供关键信息的已有命名人物，必须同时进入"
        "current_chapter_character_refs和state_reconciliation.character_refs；有持续变化时还必须进入record_updates.characters。"
        "必须逐段检查新线索、证据异常、记录缺失/覆盖/删除/清空、未知来源和责任边界；"
        "凡是会影响后续调查或判断的内容，都必须进入long_term_events并落到至少一个真实长期存储位置。"
        "state_reconciliation.relationship_refs中的每一项必须使用竖线连接并按引用排序，"
        "例如C001|C002；不得使用C001+C002、逗号或自然语言。"
        "本次新增NF临时key可以进入state_reconciliation.fact_refs、long_term_events和next_chapter_memory，"
        "但不能进入fact_lifecycle_review.reviewed_refs。"
        "必须先建立long_term_events：只逐项列出本章真正会影响后文的承诺、证据、能力边界、未决任务、伏笔、关系变化和跨章关键物；"
        "每项必须附正文逐字证据，并在storage中指向至少一个真实存储落点，不得只写在摘要里。"
        "long_term_events.storage里出现的每个lore_ref和foreshadow_ref，都必须进入"
        "state_reconciliation.record_runtime_review对应的reviewed数组逐项复核。"
        "若该事件改变了设定公开层、当前状态、研究/使用权限、持有位置、损毁程度、伏笔推进或回收状态，"
        "必须同步进入record_updates.lore或foreshadow_updates；确实没有任何动态变化时，才可放入对应unchanged数组。"
        "reviewed引用必须且只能在本次运行态更新和unchanged数组二者之一中得到结论，不能只写reviewed后跳过判断。"
        "每条非keep事实更新、设定运行态更新、伏笔更新以及新增/变化/退出的物件、冲突和任务，"
        "都必须被至少一条long_term_events.storage引用；同一事件可同时引用多个更新，不要重复制造同义事件。"
        "所有状态、事实和运行态更新只能依据最终正文已经公开或明确发生的内容；"
        "不得把章节提纲、永久人物秘密、伏笔计划或下一章资料中的未来信息写成当前已发生事实。"
        "正文没有明确出现某个功法、针法、组织、物品或规则名称时，不得只因提纲或项目资料出现该名称，就在摘要、事实或对应lore运行态中声称本章已经使用、确认或公开了它。"
        "更新已有事实时必须保留原文中的数量、程度、范围和不确定性限定，不得擅自放宽或坐实。"
        "lore.story_known和foreshadow.revealed只能写正文已公开内容；新增设定必须填写story_known，"
        "remaining_secret只写仍未揭示的边界，不得把未来答案搬进revealed。"
        "伏笔标为已埋时必须同步setup_chapter、revealed和remaining_secret；"
        "标为已回收时必须同步payoff_chapter、revealed和remaining_secret。"
        "同一人物或永久设定实体才允许update旧卡；新一轮直播、新文件、新样品、新证据批次或新物件必须create新卡，"
        "使用能区分批次的名称和临时key，绝不能覆盖旧批次当前状态。"
        + identity_gap_text
        + _LONG_TERM_RECORD_CLASSIFICATION_RULES
        + "同一状态包内create的人物NC临时key可用于state_patch人物/关系状态、current_chapter_character_refs和下一章选择；"
        "create的设定NL临时key可用于state_patch物品状态的lore_ref和下一章选择，程序会统一分配真实ID。"
        + "next_chapter_memory除选择已有C/L/F/AF引用外，也可直接使用本次新增的NC/NL/NT/NF临时key；"
        "还必须用object_keys、conflict_refs、task_refs选择下一章需要展开的物件、冲突和任务；"
        "已有状态使用目录中的稳定键或真实ID，本次新增冲突/任务可使用NCF/NTASK临时key。"
        "本章新增或更新且可能影响下一章的资料必须选入。"
        + (
            "本章是十章边界，stage_archive必须完整总结最近十章；如下一章需要承接本档案，"
            "next_chapter_memory.stage_archive_refs填写CURRENT_STAGE。"
            if stage_boundary else
            "本章不是十章边界，stage_archive必须为null。"
        )
        + f"当前全量集合只供程序核验，不得复制到输出：{catalog_summary}。"
        + "base_revision必须原样填写索引中的当前长篇记忆修订号。严格输出一个合法JSON对象："
        + example
    )


def _expand_compact_long_form_memory_update(project, chapter_index, update):
    """Expand a semantic compact delta into the existing version-2 shape.

    The model still supplies every semantic decision and evidence quote. The
    fields synthesized here are deterministic mirrors used by validation,
    storage, and the next-chapter selector.
    """
    payload = deepcopy(update) if isinstance(update, dict) else {}
    marker = payload.get("compact_delta_version")
    if marker != LONG_FORM_COMPACT_DELTA_VERSION and payload.get("output_mode") != "compact_delta_v1":
        return payload

    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter = (
        chapters[chapter_index]
        if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict)
        else {}
    )
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
    selection = chapter.get("memory_selection", {}) if isinstance(chapter, dict) else {}
    selection = selection if isinstance(selection, dict) else {}
    existing_state_refs = _long_form_existing_state_refs(project, memory)
    stage_scope = (
        LONG_FORM_STAGE_REVIEW_SCOPE
        if (chapter_index + 1) % 10 == 0
        else "current_chapter"
    )

    def unique(values):
        result = []
        for value in values if isinstance(values, list) else []:
            if isinstance(value, (dict, list)):
                continue
            text = str(value or "").strip()
            if text and text not in result:
                result.append(text)
        return result

    def append_ref(target, value):
        if isinstance(value, (dict, list)):
            return
        text = str(value or "").strip()
        if text and text not in target:
            target.append(text)

    state_patch = payload.get("state_patch", {})
    state_patch = deepcopy(state_patch) if isinstance(state_patch, dict) else {}
    retirements = payload.get("state_retirements", {})
    retirements = deepcopy(retirements) if isinstance(retirements, dict) else {}
    for key in (
        "character_refs", "relationship_refs", "object_keys", "conflict_ids", "task_ids"
    ):
        retirements.setdefault(key, [])
    payload["state_patch"] = state_patch
    payload["state_retirements"] = retirements

    record_updates = payload.get("record_updates", {})
    record_updates = deepcopy(record_updates) if isinstance(record_updates, dict) else {}
    record_updates.setdefault("characters", [])
    record_updates.setdefault("lore", [])
    payload["record_updates"] = record_updates
    payload["foreshadow_updates"] = deepcopy(
        payload.get("foreshadow_updates", [])
        if isinstance(payload.get("foreshadow_updates", []), list)
        else []
    )

    fact_updates = payload.get("fact_updates", [])
    fact_updates = deepcopy(fact_updates) if isinstance(fact_updates, list) else []
    payload["fact_updates"] = fact_updates

    reviewed_fact_refs = unique(selection.get("fact_ids", []))
    touched_fact_refs = []
    reconciliation = {
        "checked": False,
        "coverage_checks": {},
        "fact_refs": [],
        "character_refs": [],
        "lore_refs": [],
        "foreshadow_refs": [],
        "relationship_refs": [],
        "object_keys": [],
        "conflict_refs": [],
        "task_refs": [],
        "record_runtime_review": {},
        "resolved_contradictions": [],
        "notes": "",
    }
    event_refs = {
        "fact_refs": [],
        "character_refs": [],
        "lore_refs": [],
        "foreshadow_refs": [],
        "object_keys": [],
        "conflict_refs": [],
        "task_refs": [],
    }

    for item in fact_updates:
        if not isinstance(item, dict):
            continue
        operation = str(item.get("operation", "") or "").strip().lower()
        ref = item.get("key", "") if operation in {"add", "supersede"} else item.get("id", "")
        append_ref(reconciliation["fact_refs"], ref)
        if operation != "keep" and str(ref or "").strip():
            append_ref(touched_fact_refs, ref)
        if operation not in {"add", "supersede"}:
            append_ref(reviewed_fact_refs, item.get("id", ""))

    def collect_record(kind, output_key):
        for item in record_updates.get(kind, []) if isinstance(record_updates.get(kind), list) else []:
            if not isinstance(item, dict):
                continue
            operation = str(item.get("operation", "") or "").strip().lower()
            ref = item.get("key", "") if operation == "create" else item.get("ref", item.get("id", ""))
            append_ref(reconciliation[output_key], ref)

    collect_record("characters", "character_refs")
    collect_record("lore", "lore_refs")
    for item in payload["foreshadow_updates"]:
        if not isinstance(item, dict):
            continue
        operation = str(item.get("operation", "") or "").strip().lower()
        ref = item.get("key", "") if operation == "create" else item.get("ref", item.get("id", ""))
        append_ref(reconciliation["foreshadow_refs"], ref)

    for item in state_patch.get("character_states", []) if isinstance(state_patch.get("character_states"), list) else []:
        if isinstance(item, dict):
            append_ref(reconciliation["character_refs"], item.get("ref", item.get("character_id", "")))
    for value in retirements.get("character_refs", []):
        append_ref(reconciliation["character_refs"], value)
    for item in state_patch.get("relationship_states", []) if isinstance(state_patch.get("relationship_states"), list) else []:
        if not isinstance(item, dict):
            continue
        refs = item.get("refs", item.get("characters", []))
        refs = refs if isinstance(refs, list) else str(refs or "").split("|")
        refs = sorted(str(ref or "").strip() for ref in refs if str(ref or "").strip())
        if len(refs) >= 2:
            append_ref(reconciliation["relationship_refs"], "|".join(refs))
    for value in retirements.get("relationship_refs", []):
        refs = value if isinstance(value, list) else str(value or "").split("|")
        refs = sorted(str(ref or "").strip() for ref in refs if str(ref or "").strip())
        if len(refs) >= 2:
            append_ref(reconciliation["relationship_refs"], "|".join(refs))
    for item in state_patch.get("object_states", []) if isinstance(state_patch.get("object_states"), list) else []:
        if not isinstance(item, dict):
            continue
        append_ref(reconciliation["lore_refs"], item.get("lore_ref", item.get("lore_id", "")))
        append_ref(reconciliation["object_keys"], item.get("key", item.get("name", "")))
    for value in retirements.get("object_keys", []):
        append_ref(reconciliation["object_keys"], value)
    for source_key, retirement_key, output_key in (
        ("active_conflicts", "conflict_ids", "conflict_refs"),
        ("unresolved_tasks", "task_ids", "task_refs"),
    ):
        for item in state_patch.get(source_key, []) if isinstance(state_patch.get(source_key), list) else []:
            if isinstance(item, dict):
                append_ref(reconciliation[output_key], item.get("id", "") or item.get("key", ""))
        for value in retirements.get(retirement_key, []):
            append_ref(reconciliation[output_key], value)

    events = payload.get("long_term_events", [])
    events = deepcopy(events) if isinstance(events, list) else []
    for event in events:
        if not isinstance(event, dict):
            continue
        storage = event.get("storage", {})
        if not isinstance(storage, dict):
            continue
        for key in event_refs:
            values = storage.get(key, [])
            for value in values if isinstance(values, list) else []:
                append_ref(event_refs[key], value)
                append_ref(reconciliation[key], value)

    # A lore named in the current outline is a required runtime review even if
    # the chapter did not change it.
    for ref in _chapter_outline_named_lore_refs(project, chapter_index):
        append_ref(reconciliation["lore_refs"], ref)
    for ref in payload.get("current_chapter_character_refs", []):
        append_ref(reconciliation["character_refs"], ref)

    verification = payload.get("verification", {})
    verification = verification if isinstance(verification, dict) else {}
    reconciliation["checked"] = verification.get("checked") is True
    coverage_checks = verification.get("coverage_checks", {})
    reconciliation["coverage_checks"] = (
        deepcopy(coverage_checks) if isinstance(coverage_checks, dict) else {}
    )
    reconciliation["resolved_contradictions"] = unique(
        verification.get("resolved_contradictions", [])
    )
    reconciliation["notes"] = str(verification.get("notes", "") or "").strip()
    unchanged = verification.get("runtime_unchanged", {})
    unchanged = unchanged if isinstance(unchanged, dict) else {}
    unchanged_lore = unique(
        verification.get("unchanged_lore_refs", unchanged.get("lore_refs", []))
    )
    unchanged_foreshadows = unique(
        verification.get("unchanged_foreshadow_refs", unchanged.get("foreshadow_refs", []))
    )
    changed_lore = set()
    for item in record_updates.get("lore", []) if isinstance(record_updates.get("lore"), list) else []:
        if isinstance(item, dict):
            operation = str(item.get("operation", "") or "").strip().lower()
            ref = item.get("key", "") if operation == "create" else item.get("ref", item.get("id", ""))
            resolved = _resolve_long_form_record_ref(project, "lore", ref) or str(ref or "").strip()
            if resolved:
                changed_lore.add(resolved)
    changed_foreshadows = set()
    for item in payload["foreshadow_updates"]:
        if isinstance(item, dict):
            operation = str(item.get("operation", "") or "").strip().lower()
            ref = item.get("key", "") if operation == "create" else item.get("ref", item.get("id", ""))
            resolved = _resolve_long_form_record_ref(project, "foreshadows", ref) or str(ref or "").strip()
            if resolved:
                changed_foreshadows.add(resolved)
    required_lore = set(reconciliation["lore_refs"])
    required_foreshadows = set(reconciliation["foreshadow_refs"])

    def canonical_runtime_ref(kind, value):
        text = str(value or "").strip()
        return _resolve_long_form_record_ref(project, kind, text) or text

    required_lore_canonical = {
        canonical_runtime_ref("lore", value) for value in required_lore
    }
    required_foreshadows_canonical = {
        canonical_runtime_ref("foreshadows", value) for value in required_foreshadows
    }

    def unchanged_runtime_refs(kind, required, required_canonical, changed, explicit):
        result = []
        seen = set()
        for value in explicit:
            canonical = canonical_runtime_ref(kind, value)
            if canonical in required_canonical and canonical not in changed and canonical not in seen:
                result.append(value)
                seen.add(canonical)
        # Every required reference is already marked as reviewed. If the
        # compact delta contains no update for it, omission means unchanged;
        # this is a structural mirror rather than a new semantic decision.
        for value in sorted(required):
            canonical = canonical_runtime_ref(kind, value)
            if canonical and canonical not in changed and canonical not in seen:
                result.append(value)
                seen.add(canonical)
        return result

    reconciliation["record_runtime_review"] = {
        "reviewed_lore_refs": sorted(required_lore),
        "unchanged_lore_refs": unchanged_runtime_refs(
            "lore",
            required_lore,
            required_lore_canonical,
            changed_lore,
            unchanged_lore,
        ),
        "reviewed_foreshadow_refs": sorted(required_foreshadows),
        "unchanged_foreshadow_refs": unchanged_runtime_refs(
            "foreshadows",
            required_foreshadows,
            required_foreshadows_canonical,
            changed_foreshadows,
            unchanged_foreshadows,
        ),
    }

    # The lifecycle arrays are pure mirrors of the selected set plus explicit
    # changes. Whether a selected item changed is still decided by the model's
    # fact/state updates; omission means it remains unchanged.
    existing_fact_ids = {
        str(item.get("id", "") or "").strip()
        for item in memory.get("active_facts", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    reviewed_fact_refs = [value for value in reviewed_fact_refs if value in existing_fact_ids]
    for value in touched_fact_refs:
        if value in existing_fact_ids:
            append_ref(reviewed_fact_refs, value)
    payload["fact_lifecycle_review"] = {
        "scope": stage_scope,
        "reviewed_refs": reviewed_fact_refs,
        "notes": "由本章选择和显式事实更新生成结构复核索引",
    }

    def canonical_object(value):
        return existing_state_refs["object_key_by_compact"].get(_compact_text(value), "")

    reviewed_objects = []
    for value in selection.get("object_keys", []):
        canonical = canonical_object(value)
        if canonical:
            append_ref(reviewed_objects, canonical)
    snapshot = memory.get("state_snapshot", {})
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    existing_object_key_by_lore = {
        str(item.get("lore_id", "") or "").strip(): str(
            item.get("key", item.get("name", "")) or ""
        ).strip()
        for item in snapshot.get("object_states", [])
        if isinstance(item, dict)
        and str(item.get("lore_id", "") or "").strip()
        and str(item.get("key", item.get("name", "")) or "").strip()
    }
    for item in state_patch.get("object_states", []) if isinstance(state_patch.get("object_states"), list) else []:
        if not isinstance(item, dict):
            continue
        lore_id = _resolve_long_form_record_ref(
            project,
            "lore",
            item.get("lore_ref", item.get("lore_id", "")),
        )
        if lore_id in existing_object_key_by_lore:
            append_ref(reviewed_objects, existing_object_key_by_lore[lore_id])
    for value in reconciliation["object_keys"]:
        canonical = canonical_object(value)
        if canonical:
            append_ref(reviewed_objects, canonical)
    reviewed_conflicts = [
        value for value in unique(selection.get("conflict_ids", []))
        if value in existing_state_refs["conflict_ids"]
    ]
    reviewed_tasks = [
        value for value in unique(selection.get("task_ids", []))
        if value in existing_state_refs["task_ids"]
    ]
    for value in reconciliation["conflict_refs"]:
        if value in existing_state_refs["conflict_ids"]:
            append_ref(reviewed_conflicts, value)
    for value in reconciliation["task_refs"]:
        if value in existing_state_refs["task_ids"]:
            append_ref(reviewed_tasks, value)
    payload["state_lifecycle_review"] = {
        "scope": stage_scope,
        "reviewed_object_keys": reviewed_objects,
        "reviewed_conflict_refs": reviewed_conflicts,
        "reviewed_task_refs": reviewed_tasks,
        "notes": "由本章选择和显式状态更新生成结构复核索引",
    }
    payload["state_reconciliation"] = reconciliation
    payload.pop("verification", None)
    payload.pop("compact_delta_version", None)
    payload.pop("output_mode", None)
    return payload


def _normalize_long_form_state_aliases(update):
    """Normalize common model synonyms before validation and memory commit."""
    payload = deepcopy(update) if isinstance(update, dict) else {}

    def first_value(item, keys):
        for key in keys:
            value = item.get(key, "")
            if isinstance(value, (list, dict)):
                if value:
                    return value
                continue
            if str(value or "").strip():
                return value
        return ""

    def ref_list(value):
        values = value if isinstance(value, list) else [value]
        result = []
        for raw in values:
            for item in re.split(r"[|、,，;；\n]+", str(raw or "")):
                item = item.strip()
                if item and item not in result:
                    result.append(item)
        return result

    had_state_patch = "state_patch" in payload
    state_patch = payload.get("state_patch", {})
    if isinstance(state_patch, dict):
        state_patch = deepcopy(state_patch)
        # Repair responses sometimes place these two state collections at the
        # top level. They are structurally equivalent, but only the canonical
        # state_patch location may be committed.
        if not isinstance(state_patch.get("active_conflicts"), list):
            conflicts = payload.get("conflicts")
            if isinstance(conflicts, list):
                state_patch["active_conflicts"] = deepcopy(conflicts)
        if not isinstance(state_patch.get("unresolved_tasks"), list):
            tasks = payload.get("tasks")
            if isinstance(tasks, list):
                state_patch["unresolved_tasks"] = deepcopy(tasks)
        for item in state_patch.get("character_states", []) if isinstance(state_patch.get("character_states"), list) else []:
            if not isinstance(item, dict):
                continue
            if not str(item.get("ref", "") or "").strip():
                item["ref"] = first_value(
                    item,
                    (
                        "character_ref", "character_id", "character", "stable_ref",
                        "stable_id", "ref_id", "temp_key", "key",
                    ),
                )
            if not str(item.get("state", "") or "").strip():
                item["state"] = first_value(
                    item,
                    ("status", "dynamic", "runtime", "runtime_update", "change", "description"),
                )
            if not str(item.get("evidence_quote", "") or "").strip():
                item["evidence_quote"] = first_value(item, ("evidence", "quote"))
        for item in state_patch.get("relationship_states", []) if isinstance(state_patch.get("relationship_states"), list) else []:
            if not isinstance(item, dict):
                continue
            refs = first_value(
                item,
                ("character_refs", "character_ids", "refs", "characters", "participants"),
            )
            if not refs:
                relationship_ref = first_value(
                    item,
                    (
                        "relationship_ref", "relationship_id", "relationship_key",
                        "stable_ref", "stable_id", "temp_key", "key", "ref",
                    ),
                )
                refs = re.findall(r"(?<![A-Za-z0-9])C\d{3}(?!\d)", str(relationship_ref or ""))
            item["refs"] = ref_list(refs)
            if not str(item.get("state", "") or "").strip():
                item["state"] = first_value(
                    item,
                    ("status", "dynamic", "runtime", "runtime_update", "change", "description"),
                )
            if not str(item.get("evidence_quote", "") or "").strip():
                item["evidence_quote"] = first_value(item, ("evidence", "quote"))
        for item in state_patch.get("object_states", []) if isinstance(state_patch.get("object_states"), list) else []:
            if not isinstance(item, dict):
                continue
            if not str(item.get("key", "") or "").strip():
                item["key"] = first_value(
                    item,
                    ("object_key", "object_id", "stable_ref", "temp_key", "id", "name"),
                )
            if not str(item.get("lore_ref", "") or "").strip():
                item["lore_ref"] = first_value(
                    item,
                    ("lore_ref", "lore_id", "setting_ref", "setting_id"),
                )
            if not str(item.get("state", "") or "").strip():
                item["state"] = first_value(
                    item,
                    ("status", "dynamic", "runtime", "runtime_update", "change", "description"),
                )
            if not str(item.get("evidence_quote", "") or "").strip():
                item["evidence_quote"] = first_value(item, ("evidence", "quote"))
        for item in state_patch.get("active_conflicts", []) if isinstance(state_patch.get("active_conflicts"), list) else []:
            if not isinstance(item, dict):
                continue
            conflict_ref = first_value(
                item,
                (
                    "conflict_id", "conflict_ref", "conflict_key", "ref", "stable_ref",
                    "stable_id", "temp_key", "key", "id",
                ),
            )
            create_state = (
                str(item.get("type", item.get("operation", "")) or "").strip().lower() == "create"
                or str(conflict_ref or "").strip().upper().startswith("NCF")
            )
            if create_state:
                if not str(item.get("key", "") or "").strip():
                    item["key"] = conflict_ref
                item["id"] = ""
            elif not str(item.get("id", "") or "").strip():
                item["id"] = conflict_ref
            if not str(item.get("conflict", "") or "").strip():
                item["conflict"] = first_value(
                    item,
                    ("status", "state", "change", "description", "title", "name"),
                )
            if not str(item.get("evidence_quote", "") or "").strip():
                item["evidence_quote"] = first_value(item, ("evidence", "quote"))
        for item in state_patch.get("unresolved_tasks", []) if isinstance(state_patch.get("unresolved_tasks"), list) else []:
            if not isinstance(item, dict):
                continue
            task_ref = first_value(
                item,
                (
                    "task_id", "task_ref", "task_key", "ref", "stable_ref", "stable_id",
                    "temp_key", "key", "id",
                ),
            )
            create_state = (
                str(item.get("type", item.get("operation", "")) or "").strip().lower() == "create"
                or str(task_ref or "").strip().upper().startswith("NTASK")
            )
            if create_state:
                if not str(item.get("key", "") or "").strip():
                    item["key"] = task_ref
                item["id"] = ""
            elif not str(item.get("id", "") or "").strip():
                item["id"] = task_ref
            if not str(item.get("task", "") or "").strip():
                item["task"] = first_value(
                    item,
                    ("status", "state", "change", "description", "title", "name"),
                )
            if not str(item.get("evidence_quote", "") or "").strip():
                item["evidence_quote"] = first_value(item, ("evidence", "quote"))
        if had_state_patch or state_patch:
            payload["state_patch"] = state_patch

    # Models may treat an unchanged runtime reference as the review outcome
    # without copying it into the reviewed list.  These arrays are a semantic
    # pair: unchanged is a reviewed result, so make that equivalence explicit
    # before validation and storage.
    reconciliation = payload.get("state_reconciliation", {})
    if isinstance(reconciliation, dict):
        reconciliation = deepcopy(reconciliation)
        runtime_review = reconciliation.get("record_runtime_review", {})
        if isinstance(runtime_review, dict):
            runtime_review = deepcopy(runtime_review)
            runtime_conclusions = runtime_review.get("runtime_conclusions", [])
            if isinstance(runtime_conclusions, list):
                known_lore_refs = {
                    str(value or "").strip()
                    for value in ref_list(reconciliation.get("lore_refs", []))
                    if str(value or "").strip()
                }
                known_foreshadow_refs = {
                    str(value or "").strip()
                    for value in ref_list(reconciliation.get("foreshadow_refs", []))
                    if str(value or "").strip()
                }
                reviewed_by_kind = {
                    "lore": runtime_review.get("reviewed_lore_refs", []),
                    "foreshadows": runtime_review.get("reviewed_foreshadow_refs", []),
                }
                unchanged_by_kind = {
                    "lore": runtime_review.get("unchanged_lore_refs", []),
                    "foreshadows": runtime_review.get("unchanged_foreshadow_refs", []),
                }
                for kind in reviewed_by_kind:
                    if not isinstance(reviewed_by_kind[kind], list):
                        reviewed_by_kind[kind] = []
                    if not isinstance(unchanged_by_kind[kind], list):
                        unchanged_by_kind[kind] = []

                def append_runtime_ref(target, value):
                    value = str(value or "").strip()
                    if value and value not in target:
                        target.append(value)

                for item in runtime_conclusions:
                    if isinstance(item, dict):
                        ref = first_value(
                            item,
                            (
                                "ref", "record_ref", "lore_ref", "foreshadow_ref",
                                "id", "key",
                            ),
                        )
                        conclusion = str(
                            first_value(item, ("conclusion", "result", "status", "state"))
                            or ""
                        ).strip().lower()
                        kind_hint = str(
                            first_value(item, ("kind", "type", "record_type", "category"))
                            or ""
                        ).strip().lower()
                        if any(
                            str(item.get(key, "") or "").strip()
                            for key in ("foreshadow_ref", "foreshadow_id", "foreshadow")
                        ) or any(marker in kind_hint for marker in ("foreshadow", "伏笔")):
                            kind = "foreshadows"
                        elif any(marker in kind_hint for marker in ("lore", "setting", "设定")):
                            kind = "lore"
                        else:
                            kind = ""
                    else:
                        ref = item
                        conclusion = ""
                        kind = ""
                    refs = ref_list(ref)
                    for value in refs:
                        if not kind:
                            if value in known_foreshadow_refs or value.startswith("F"):
                                kind = "foreshadows"
                            elif value in known_lore_refs or value.startswith("L"):
                                kind = "lore"
                            elif value in {
                                str(item or "").strip()
                                for item in reviewed_by_kind["foreshadows"]
                                if str(item or "").strip()
                            }:
                                kind = "foreshadows"
                            elif value in {
                                str(item or "").strip()
                                for item in reviewed_by_kind["lore"]
                                if str(item or "").strip()
                            }:
                                kind = "lore"
                        if not kind:
                            continue
                        append_runtime_ref(reviewed_by_kind[kind], value)
                        if (
                            "unchanged" in conclusion
                            or "未变化" in conclusion
                            or "未改变" in conclusion
                            or "不变" in conclusion
                            or "same" == conclusion
                        ):
                            append_runtime_ref(unchanged_by_kind[kind], value)
                runtime_review["reviewed_lore_refs"] = reviewed_by_kind["lore"]
                runtime_review["reviewed_foreshadow_refs"] = reviewed_by_kind["foreshadows"]
                runtime_review["unchanged_lore_refs"] = unchanged_by_kind["lore"]
                runtime_review["unchanged_foreshadow_refs"] = unchanged_by_kind["foreshadows"]
            for reviewed_key, unchanged_key in (
                ("reviewed_lore_refs", "unchanged_lore_refs"),
                ("reviewed_foreshadow_refs", "unchanged_foreshadow_refs"),
            ):
                reviewed = runtime_review.get(reviewed_key, [])
                reviewed = reviewed if isinstance(reviewed, list) else []
                seen = {
                    str(value or "").strip()
                    for value in reviewed
                    if str(value or "").strip()
                }
                unchanged = runtime_review.get(unchanged_key, [])
                for value in unchanged if isinstance(unchanged, list) else []:
                    value = str(value or "").strip()
                    if value and value not in seen:
                        reviewed.append(value)
                        seen.add(value)
                runtime_review[reviewed_key] = reviewed
            reconciliation["record_runtime_review"] = runtime_review
        payload["state_reconciliation"] = reconciliation

    retirements = payload.get("state_retirements", {})
    if isinstance(retirements, dict):
        retirements = deepcopy(retirements)
        for target, aliases in (
            ("character_refs", ("character_ids", "characters")),
            ("relationship_refs", ("relationship_ids", "relationships")),
            ("object_keys", ("object_refs", "object_ids", "objects")),
            ("conflict_ids", ("conflict_refs", "conflicts")),
            ("task_ids", ("task_refs", "tasks")),
        ):
            if not retirements.get(target):
                value = first_value(retirements, aliases)
                if value:
                    retirements[target] = ref_list(value)
        payload["state_retirements"] = retirements

    record_updates = payload.get("record_updates", {})
    if isinstance(record_updates, dict):
        record_updates = deepcopy(record_updates)
        if not isinstance(record_updates.get("characters"), list):
            aliases = first_value(record_updates, ("character_updates", "character_states"))
            if isinstance(aliases, list):
                record_updates["characters"] = aliases
        if not isinstance(record_updates.get("lore"), list):
            aliases = first_value(record_updates, ("lore_updates", "setting_updates"))
            if isinstance(aliases, list):
                record_updates["lore"] = aliases
        for kind in ("characters", "lore"):
            raw_items = record_updates.get(kind)
            if isinstance(raw_items, list):
                record_updates[kind] = [
                    item for item in raw_items
                    if not (
                        isinstance(item, dict)
                        and str(item.get("operation", "") or "").strip().lower()
                        in {"unchanged", "no_change", "keep", "retain"}
                    )
                ]
            for item in record_updates.get(kind, []) if isinstance(record_updates.get(kind), list) else []:
                if not isinstance(item, dict):
                    continue
                operation = str(item.get("operation", "") or "").strip().lower()
                if operation in {"add", "new", "insert"}:
                    operation = "create"
                    item["operation"] = operation
                elif operation in {"modify", "change", "patch"}:
                    operation = "update"
                    item["operation"] = operation
                if kind == "characters":
                    identity_fields = _character_identity_fields_from_item(item)
                    if operation == "create":
                        if identity_fields:
                            canon = item.get("canon")
                            canon = deepcopy(canon) if isinstance(canon, dict) else {}
                            for field, value in identity_fields.items():
                                if not str(canon.get(field, "") or "").strip():
                                    canon[field] = value
                            item["canon"] = canon
                    elif identity_fields:
                        # Older responses put identity fields at the top level or
                        # under canon/fields. Normalize them into the explicit
                        # supplement channel so update validation stays strict.
                        item["identity_patch"] = identity_fields
                        item["canon"] = {}
                if not str(item.get("ref", "") or "").strip() and operation != "create":
                    kind_specific_ref = (
                        "character_id" if kind == "characters" else "lore_id"
                    )
                    item["ref"] = first_value(
                        item,
                        (
                            "record_ref", "character_ref", "lore_ref", kind_specific_ref, "stable_ref",
                            "stable_id", "ref_id", "temp_key", "id", "key",
                        ),
                    )
                if kind == "characters" and operation != "create" and not str(item.get("name", "") or "").strip():
                    item["name"] = first_value(
                        item,
                        (
                            "new_name", "canonical_name", "display_name", "character_name",
                            "stable_name", "record_name", "real_name",
                        ),
                    )
                if operation == "create" and not str(item.get("key", "") or "").strip():
                    item["key"] = first_value(
                        item,
                        (
                            "record_key", "stable_ref", "stable_id", "temp_key", "id",
                            "record_ref", "character_ref", "lore_ref", "ref",
                        ),
                    )
                if operation == "create" and not str(item.get("name", "") or "").strip():
                    item["name"] = first_value(
                        item,
                        (
                            "record_name", "character_name", "lore_name", "stable_name",
                            "title", "label",
                        ),
                    )
                dynamic = first_value(item, (
                    "state", "dynamic", "runtime", "runtime_update", "current_dynamic",
                    "change",
                    "latest_state", "new_state", "current_state", "state_update",
                    "new_status", "status_update", "update", "content", "status",
                    "description",
                ))
                if not dynamic:
                    changes = item.get("changes", [])
                    if isinstance(changes, str):
                        dynamic = changes
                    elif isinstance(changes, list):
                        dynamic = "；".join(
                            str(value or "").strip()
                            for value in changes
                            if str(value or "").strip()
                        )
                if not str(item.get("state", "") or "").strip():
                    item["state"] = dynamic
                if not item.get("changes") and dynamic:
                    item["changes"] = [str(dynamic)]
                if not str(item.get("evidence_quote", "") or "").strip():
                    item["evidence_quote"] = first_value(item, ("evidence", "quote"))
        payload["record_updates"] = record_updates

    fact_updates = payload.get("fact_updates", [])
    if "fact_updates" in payload and isinstance(fact_updates, list):
        fact_updates = deepcopy(fact_updates)
        for item in fact_updates:
            if not isinstance(item, dict):
                continue
            operation = str(item.get("operation", "") or "").strip().lower()
            if operation in {"create", "new", "insert"}:
                operation = "add"
                item["operation"] = operation
            elif operation in {"modify", "change", "patch"}:
                operation = "update"
                item["operation"] = operation
            elif operation in {"remove", "delete"}:
                operation = "retire"
                item["operation"] = operation
            elif operation == "replace":
                operation = "supersede"
                item["operation"] = operation
            if operation == "supersede":
                if not str(item.get("id", "") or "").strip():
                    item["id"] = first_value(
                        item,
                        (
                            "fact_ref", "fact_id", "stable_ref", "stable_id", "ref_id", "ref",
                            "supersedes", "supersedes_fact_id", "replaces", "replaced_fact_id",
                        ),
                    )
                # A supersede has two different references: id points to the
                # old AF record, while key is the new temporary NF record.
                # Some model responses echo the old id into key and put the
                # real new key in new_fact_key.
                new_fact_key = first_value(
                    item,
                    (
                        "new_fact_key", "new_key", "fact_key", "temp_key",
                    ),
                )
                if new_fact_key:
                    item["key"] = new_fact_key
                elif not str(item.get("key", "") or "").strip():
                    item["key"] = first_value(item, ("stable_ref",))
            elif operation == "add":
                if not str(item.get("key", "") or "").strip():
                    item["key"] = first_value(
                        item,
                        (
                            "fact_ref", "fact_id", "fact_key", "stable_ref", "stable_id", "temp_key",
                            "temp_id", "ref",
                        ),
                    )
            elif operation in {"keep", "update", "retire"}:
                if not str(item.get("id", "") or "").strip():
                    item["id"] = first_value(
                        item,
                        (
                            "fact_ref", "fact_id", "stable_ref", "stable_id", "ref_id",
                            "temp_key", "ref", "key",
                        ),
                    )
            if not str(item.get("fact", "") or "").strip():
                item["fact"] = first_value(
                    item,
                    (
                        "state", "content", "description", "current_fact",
                        "new_fact", "update", "value",
                    ),
                )
            if not str(item.get("evidence_quote", "") or "").strip():
                item["evidence_quote"] = first_value(item, ("evidence", "quote"))
        payload["fact_updates"] = fact_updates

    foreshadow_updates = payload.get("foreshadow_updates", [])
    if isinstance(foreshadow_updates, list):
        foreshadow_updates = [
            item for item in foreshadow_updates
            if not (
                isinstance(item, dict)
                and str(item.get("operation", "") or "").strip().lower()
                in {"unchanged", "no_change", "keep", "retain"}
            )
        ]
        payload["foreshadow_updates"] = foreshadow_updates
    for item in foreshadow_updates if isinstance(foreshadow_updates, list) else []:
        if not isinstance(item, dict):
            continue
        operation = str(item.get("operation", "") or "").strip().lower()
        if operation in {"add", "new", "insert"}:
            operation = "create"
            item["operation"] = operation
        elif operation in {"modify", "change", "patch", "advance"}:
            operation = "update"
            item["operation"] = operation
        if not str(item.get("ref", "") or "").strip() and str(
            operation or ""
        ).strip().lower() != "create":
            item["ref"] = first_value(
                item,
                (
                    "record_ref", "foreshadow_ref", "foreshadow_id", "stable_ref", "stable_id",
                    "ref_id", "temp_key", "id", "key", "foreshadow_key",
                ),
            )
        if operation == "create" and not str(
            item.get("key", "") or ""
        ).strip():
            item["key"] = first_value(
                item,
                (
                    "foreshadow_key", "record_ref", "foreshadow_ref", "stable_ref", "stable_id",
                    "temp_key", "id", "ref",
                ),
            )
        if not str(item.get("name", "") or "").strip():
            item["name"] = first_value(
                item,
                ("title", "stable_name", "foreshadow_name", "label"),
            )
        if not str(item.get("description", "") or "").strip():
            item["description"] = first_value(
                item,
                (
                    "content", "foreshadow", "progress", "dynamic", "current_dynamic",
                    "update", "detail", "text",
                ),
            )
        if not str(item.get("remaining_secret", "") or "").strip():
            remaining_secret = first_value(
                item,
                ("unrevealed", "unresolved", "remaining", "remaining_unknown"),
            )
            if remaining_secret:
                item["remaining_secret"] = remaining_secret
        dynamic = first_value(
            item,
            (
                "state", "dynamic", "runtime", "runtime_update", "current_dynamic",
                "change",
                "progress", "content", "description", "status",
            ),
        )
        if not str(item.get("state", "") or "").strip():
            item["state"] = dynamic
        raw_status = str(item.get("status", "") or "").strip()
        normalized_status = _infer_foreshadow_status({"status": raw_status}, preserve_manual=False)
        state_status = _infer_foreshadow_status(
            {"status": item.get("state", "")},
            preserve_manual=False,
        )
        if raw_status == "未埋" and state_status == "已埋":
            normalized_status = "已埋"
        if normalized_status:
            item["status"] = normalized_status
        # Both aliases and the canonical status may omit these two required
        # boundaries. Reuse the model's own progress text; a truly empty
        # update still fails validation instead of inventing a reveal.
        if normalized_status in {"已埋", "已回收"}:
            description = str(item.get("description", "") or "").strip()
            progress = str(
                item.get("progress", item.get("update", "")) or ""
            ).strip()
            source = (
                progress or description or str(dynamic or "").strip()
                or str(first_value(item, ("evidence_quote", "evidence", "quote")) or "").strip()
            )
            if source and not str(item.get("revealed", "") or "").strip():
                item["revealed"] = source
            if (
                normalized_status == "已埋"
                and source
                and not str(item.get("remaining_secret", "") or "").strip()
            ):
                item["remaining_secret"] = (
                    description
                    if description and description != source
                    else "该线索的具体来源、含义和后续真相仍未揭示。"
                )
            elif normalized_status == "已回收" and "remaining_secret" not in item:
                item["remaining_secret"] = ""
        if not str(item.get("evidence_quote", "") or "").strip():
            item["evidence_quote"] = first_value(item, ("evidence", "quote"))

    events = payload.get("long_term_events", [])
    events = deepcopy(events if isinstance(events, list) else [])
    for item in events:
        if not isinstance(item, dict):
            continue
        if not str(item.get("event", "") or "").strip():
            item["event"] = first_value(
                item,
                ("summary", "content", "description", "title"),
            )
        category = str(
            item.get("category", "")
            or first_value(item, ("event_category", "type", "kind", "event_type"))
            or "other"
        ).strip().lower()
        category_aliases = {
            "承诺": "commitment",
            "证据": "evidence",
            "能力边界": "ability_boundary",
            "任务": "task",
            "伏笔": "foreshadow",
            "关键物件": "key_object",
            "物件": "key_object",
            "关系": "relationship",
            "事实": "fact",
            "剧情": "plot",
            "情节": "plot",
            "其他": "other",
        }
        category = category_aliases.get(category, category)
        if category not in {
            "commitment", "evidence", "ability_boundary", "task", "foreshadow",
            "key_object", "relationship", "other", "fact", "plot",
        }:
            category = "other"
        item["category"] = category
        if not str(item.get("evidence_quote", "") or "").strip():
            item["evidence_quote"] = first_value(item, ("evidence", "quote"))
    payload["long_term_events"] = events

    def normalize_evidence_fields(items):
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            for key in ("evidence_quote", "evidence", "quote"):
                value = item.get(key)
                if isinstance(value, str) and "\\n" in value:
                    item[key] = value.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")

    normalize_evidence_fields(payload.get("fact_updates", []))
    normalize_evidence_fields(payload.get("foreshadow_updates", []))
    normalize_evidence_fields(payload.get("long_term_events", []))
    record_updates = payload.get("record_updates", {})
    if isinstance(record_updates, dict):
        normalize_evidence_fields(record_updates.get("characters", []))
        normalize_evidence_fields(record_updates.get("lore", []))
    state_patch = payload.get("state_patch", {})
    if isinstance(state_patch, dict):
        for key in ("character_states", "relationship_states", "object_states", "active_conflicts", "unresolved_tasks"):
            normalize_evidence_fields(state_patch.get(key, []))
    return payload


def _load_json_with_trailing_delimiter_repair(value):
    """Parse JSON when the only loss is an unambiguous trailing delimiter."""
    text = str(value or "").strip()
    if not text:
        return None, False
    stack = []
    in_string = False
    escaped = False
    pairs = {"}": "{", "]": "["}
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            stack.append(char)
        elif char in "]}":
            if not stack or stack[-1] != pairs[char]:
                return None, False
            stack.pop()
    if in_string or escaped or not stack:
        return None, False
    repaired = text + "".join(
        "]" if char == "[" else "}" for char in reversed(stack)
    )
    try:
        data = json.loads(repaired)
    except Exception:
        return None, False
    return (data, True) if isinstance(data, dict) else (None, False)


def _load_json_with_single_missing_quote_repair(value):
    """Parse JSON and repair unambiguous missing string-closing quotes."""
    text = str(value or "").strip()
    try:
        return json.loads(text), False
    except Exception:
        pass

    # Some compatible APIs omit the ASCII closing quote of evidence_quote
    # while preserving the following object delimiter. One response can contain
    # several such omissions, so repair this exact structural shape in one pass.
    evidence_quote_pattern = re.compile(
        r'("evidence_quote"\s*:\s*")((?:\\.|[^"\\])*?)(?=}(?:,|\]))'
    )
    targeted = evidence_quote_pattern.sub(lambda match: match.group(0) + '"', text)
    if targeted != text:
        try:
            data = json.loads(targeted)
            if isinstance(data, dict):
                return data, True
        except Exception:
            pass
    else:
        targeted = text

    candidates = []
    in_string = False
    escaped = False
    closing_marks = {"”", "’", "」", "』", "》"}
    for index, char in enumerate(targeted):
        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = False
                continue
            if (
                char in "}]"
                and index > 0
                and targeted[index - 1] in closing_marks
            ):
                candidates.append(targeted[:index] + '"' + targeted[index:])
        elif char == '"':
            in_string = True

    repaired = []
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, dict):
            repaired.append(data)
            if len(repaired) > 1:
                return None, False
    return (repaired[0], True) if len(repaired) == 1 else (None, False)


def _stable_long_form_fact_scope(fact):
    """Create a collision-resistant technical scope when a model omits one."""
    compact = _compact_text(fact)
    if not compact:
        return ""
    digest = hashlib.sha256(compact.encode("utf-8")).hexdigest()[:16]
    return f"auto_fact:{digest}"


def _backfill_long_form_fact_scopes(memory):
    """Give legacy facts a stable scope without guessing their narrative topic."""
    if not isinstance(memory, dict):
        return memory
    facts = memory.get("active_facts", [])
    if not isinstance(facts, list):
        return memory
    for item in facts:
        if not isinstance(item, dict) or str(item.get("scope", "") or "").strip():
            continue
        item["scope"] = _stable_long_form_fact_scope(item.get("fact", ""))
    return memory


def _normalize_long_form_fact_update_scopes(project, payload):
    """Fill omitted update scopes from an existing fact or stable fact text."""
    if not isinstance(payload, dict):
        return payload
    memory = _backfill_long_form_fact_scopes(
        _normalize_long_form_memory(
            (project if isinstance(project, dict) else {}).get("long_form_memory", {})
        )
    )
    by_id = {
        str(item.get("id", "") or "").strip(): item
        for item in memory.get("active_facts", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    by_fact = {
        _compact_text(item.get("fact", "")): item
        for item in memory.get("active_facts", [])
        if isinstance(item, dict) and _compact_text(item.get("fact", ""))
    }
    updates = payload.get("fact_updates", [])
    if not isinstance(updates, list):
        return payload
    for item in updates:
        if not isinstance(item, dict):
            continue
        operation = str(item.get("operation", "") or "").strip().lower()
        if operation not in {"add", "update", "retire", "supersede"}:
            continue
        if str(item.get("scope", "") or "").strip():
            continue
        existing = by_id.get(str(item.get("id", "") or "").strip())
        if existing is None:
            existing = by_fact.get(_compact_text(item.get("fact", "")))
        scope = str(existing.get("scope", "") or "").strip() if existing else ""
        if not scope:
            scope = _stable_long_form_fact_scope(item.get("fact", ""))
        if scope:
            item["scope"] = scope
    return payload


def _normalize_long_form_ephemeral_actor_refs(project, payload):
    """Keep untracked one-scene actors out of the chapter reference indexes.

    This intentionally has a narrow scope.  It only removes a raw actor name
    when that name appears *solely* in the convenience indexes which describe
    who appeared in this chapter.  Once a response tries to persist a state,
    relationship, retirement, or event link for the actor, strict validation
    still rejects it and asks the model to create a formal character record.
    """
    if not isinstance(payload, dict):
        return payload

    record_updates = payload.get("record_updates", {})
    record_updates = record_updates if isinstance(record_updates, dict) else {}
    created_by_name = {}
    created_keys = set()
    for item in record_updates.get("characters", []) if isinstance(record_updates.get("characters"), list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("operation", "") or "").strip().lower() != "create":
            continue
        key = str(item.get("key", "") or "").strip()
        name = _compact_text(item.get("name", "")).casefold()
        if key:
            created_keys.add(key)
            if name:
                created_by_name[name] = key

    def normalize_character_ref(value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        # Preserve established alias forms such as C001.  Other normalizers
        # deliberately use those aliases throughout the compact state packet.
        if _resolve_long_form_record_ref(project, "characters", raw):
            return raw
        if raw in created_keys:
            return raw
        return created_by_name.get(_compact_text(raw).casefold(), "")

    def all_persistent_character_refs():
        result = set()

        def add(values):
            for value in values if isinstance(values, list) else []:
                raw = str(value or "").strip()
                if raw:
                    result.add(raw)

        state_patch = payload.get("state_patch", {})
        if isinstance(state_patch, dict):
            for item in state_patch.get("character_states", []) if isinstance(state_patch.get("character_states"), list) else []:
                if isinstance(item, dict):
                    add([item.get("ref", item.get("character_id", ""))])
            for item in state_patch.get("relationship_states", []) if isinstance(state_patch.get("relationship_states"), list) else []:
                if isinstance(item, dict):
                    add(item.get("refs", item.get("characters", [])))
        state_retirements = payload.get("state_retirements", {})
        if isinstance(state_retirements, dict):
            add(state_retirements.get("character_refs", []))
        next_memory = payload.get("next_chapter_memory", {})
        if isinstance(next_memory, dict):
            add(next_memory.get("character_refs", []))
        for event in payload.get("long_term_events", []) if isinstance(payload.get("long_term_events"), list) else []:
            storage = event.get("storage", {}) if isinstance(event, dict) else {}
            if isinstance(storage, dict):
                add(storage.get("character_refs", []))
        for item in record_updates.get("characters", []) if isinstance(record_updates.get("characters"), list) else []:
            if isinstance(item, dict) and str(item.get("operation", "") or "").strip().lower() == "update":
                add([item.get("ref", item.get("id", ""))])
        return result

    persistent_refs = all_persistent_character_refs()

    def filter_index(values):
        if not isinstance(values, list):
            return values
        result = []
        for value in values:
            raw = str(value or "").strip()
            normalized = normalize_character_ref(raw)
            # An untracked actor is not a long-form character merely because a
            # hotel scene gave them a job title and one line of dialogue.
            if not normalized and raw not in persistent_refs:
                continue
            output = normalized or raw
            if output and output not in result:
                result.append(output)
        return result

    # A newly created lore record must never expose information the final
    # prose did not establish.  The literal evidence quote is the narrowest
    # safe fallback when compatible models omit story_known.
    for item in record_updates.get("lore", []) if isinstance(record_updates.get("lore"), list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("operation", "") or "").strip().lower() != "create":
            continue
        if str(item.get("story_known", "") or "").strip():
            continue
        evidence = str(
            item.get("evidence_quote", item.get("evidence", item.get("quote", ""))) or ""
        ).strip()
        if evidence:
            item["story_known"] = evidence

    current_refs = payload.get("current_chapter_character_refs")
    if isinstance(current_refs, list):
        payload["current_chapter_character_refs"] = filter_index(current_refs)

    reconciliation = payload.get("state_reconciliation")
    if isinstance(reconciliation, dict) and isinstance(reconciliation.get("character_refs"), list):
        reconciliation["character_refs"] = filter_index(reconciliation["character_refs"])
    return payload


def _normalize_long_form_update_payload(project, chapter_index, update):
    payload = deepcopy(update) if isinstance(update, dict) else {}
    payload.pop("_parse_repaired", None)
    if (
        payload.get("compact_delta_version") == LONG_FORM_COMPACT_DELTA_VERSION
        or payload.get("output_mode") == "compact_delta_v1"
    ):
        payload = _normalize_long_form_state_aliases(payload)
        payload = _expand_compact_long_form_memory_update(project, chapter_index, payload)
    else:
        if "state_patch" not in payload and isinstance(payload.get("state_snapshot"), dict):
            payload["state_patch"] = deepcopy(payload.get("state_snapshot", {}))
        payload = _normalize_long_form_state_aliases(payload)
    payload = _drop_empty_long_form_state_items(project, payload)
    payload = _repair_invalid_long_form_record_refs_by_name(project, payload)
    payload = _normalize_long_form_ephemeral_actor_refs(project, payload)
    payload = _normalize_long_form_fact_update_scopes(project, payload)
    payload.setdefault("state_patch", {})
    payload.setdefault("state_retirements", {})
    payload.setdefault("state_lifecycle_review", {})
    if "current_chapter_character_refs" not in payload:
        payload["current_chapter_character_refs"] = deepcopy(
            payload.get("current_chapter_character_ids", [])
        )
    if "fact_updates" not in payload:
        existing_ids = {
            str(item.get("id", "") or "").strip()
            for item in _normalize_long_form_memory(
                (project if isinstance(project, dict) else {}).get("long_form_memory", {})
            ).get("active_facts", [])
            if isinstance(item, dict)
        }
        fact_updates = []
        for index, item in enumerate(payload.get("active_facts", []) if isinstance(payload.get("active_facts"), list) else [], 1):
            if isinstance(item, str):
                fact_text = item.strip()
                if fact_text:
                    fact_updates.append({"operation": "add", "key": f"LEGACY-NF{index}", "fact": fact_text})
                continue
            if not isinstance(item, dict):
                continue
            fact_text = str(item.get("fact", "") or "").strip()
            item_id = str(item.get("id", "") or "").strip()
            if not fact_text:
                continue
            if item_id in existing_ids:
                fact_updates.append({"operation": "update", "id": item_id, "fact": fact_text})
            else:
                fact_updates.append({"operation": "add", "key": f"LEGACY-NF{index}", "fact": fact_text})
        payload["fact_updates"] = fact_updates
    payload.setdefault("record_updates", {})
    payload.setdefault("foreshadow_updates", [])
    payload.setdefault("fact_lifecycle_review", {})
    payload.setdefault("long_term_events", [])
    payload.setdefault("state_reconciliation", {})
    payload.setdefault("next_chapter_memory", {})
    return payload


def _drop_empty_long_form_state_items(project, payload):
    """Drop empty conflict/task rows without inventing a state decision.

    An empty row has no semantic update to persist. When it carries a new
    temporary key, remove only references that were generated for that same
    row; unrelated unknown references must remain visible to validation.
    """
    if not isinstance(payload, dict):
        return payload
    state_patch = payload.get("state_patch")
    if not isinstance(state_patch, dict):
        return payload

    dropped = {"conflicts": set(), "tasks": set()}
    for state_key, text_key, kind in (
        ("active_conflicts", "conflict", "conflicts"),
        ("unresolved_tasks", "task", "tasks"),
    ):
        values = state_patch.get(state_key)
        if not isinstance(values, list):
            continue
        kept = []
        for item in values:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            if str(item.get(text_key, "") or "").strip():
                kept.append(item)
                continue
            ref = str(item.get("id", "") or item.get("key", "") or "").strip()
            if ref:
                dropped[kind].add(ref.casefold())
        state_patch[state_key] = kept

    if not any(dropped.values()):
        return payload

    existing_state_refs = _long_form_existing_state_refs(
        project,
        _normalize_long_form_memory(
            project.get("long_form_memory", {})
            if isinstance(project, dict) else {}
        ),
    )
    existing_ids_by_kind = {
        "conflicts": {
            str(value or "").strip().casefold()
            for value in existing_state_refs.get("conflict_ids", set())
            if str(value or "").strip()
        },
        "tasks": {
            str(value or "").strip().casefold()
            for value in existing_state_refs.get("task_ids", set())
            if str(value or "").strip()
        },
    }
    new_refs = {
        kind: {
            value.casefold()
            for value in refs
            if value.casefold() not in existing_ids_by_kind.get(kind, set())
        }
        for kind, refs in dropped.items()
    }

    def remove_refs(values, kind):
        if not isinstance(values, list):
            return values
        blocked = new_refs.get(kind, set())
        return [
            value for value in values
            if str(value or "").strip().casefold() not in blocked
        ]

    reconciliation = payload.get("state_reconciliation")
    if isinstance(reconciliation, dict):
        reconciliation["conflict_refs"] = remove_refs(
            reconciliation.get("conflict_refs", []), "conflicts"
        )
        reconciliation["task_refs"] = remove_refs(
            reconciliation.get("task_refs", []), "tasks"
        )
    next_memory = payload.get("next_chapter_memory")
    if isinstance(next_memory, dict):
        for key in ("conflict_refs", "conflict_ids"):
            next_memory[key] = remove_refs(next_memory.get(key, []), "conflicts")
        for key in ("task_refs", "task_ids"):
            next_memory[key] = remove_refs(next_memory.get(key, []), "tasks")
    lifecycle = payload.get("state_lifecycle_review")
    if isinstance(lifecycle, dict):
        lifecycle["reviewed_conflict_refs"] = remove_refs(
            lifecycle.get("reviewed_conflict_refs", []), "conflicts"
        )
        lifecycle["reviewed_task_refs"] = remove_refs(
            lifecycle.get("reviewed_task_refs", []), "tasks"
        )
    for event in payload.get("long_term_events", []) if isinstance(payload.get("long_term_events"), list) else []:
        if not isinstance(event, dict) or not isinstance(event.get("storage"), dict):
            continue
        storage = event["storage"]
        storage["conflict_refs"] = remove_refs(
            storage.get("conflict_refs", []), "conflicts"
        )
        storage["task_refs"] = remove_refs(
            storage.get("task_refs", []), "tasks"
        )
    return payload


def _normalize_long_form_event_storage_refs(project, chapter_index, update):
    """Normalize event refs and restore only links proven by shared literal evidence."""
    project = project if isinstance(project, dict) else {}
    payload = _normalize_long_form_update_payload(project, chapter_index, update)
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))

    temp_record_keys = {"characters": set(), "lore": set(), "foreshadows": set()}
    record_updates = payload.get("record_updates", {})
    if isinstance(record_updates, dict):
        for kind in ("characters", "lore"):
            items = record_updates.get(kind, [])
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("operation", "") or "").strip().lower() == "create":
                    key = str(item.get("key", "") or "").strip()
                    if key:
                        temp_record_keys[kind].add(key)
    for item in payload.get("foreshadow_updates", []) if isinstance(payload.get("foreshadow_updates"), list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("operation", "") or "").strip().lower() == "create":
            key = str(item.get("key", "") or "").strip()
            if key:
                temp_record_keys["foreshadows"].add(key)

    valid_fact_refs = {
        str(item.get("id", "") or "").strip()
        for item in memory.get("active_facts", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    valid_fact_refs.update(
        str(item.get("key", "") or "").strip()
        for item in payload.get("fact_updates", []) if isinstance(item, dict)
        and str(item.get("operation", "") or "").strip().lower() in {"add", "supersede"}
        and str(item.get("key", "") or "").strip()
    )

    snapshot = memory.get("state_snapshot", {})
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    state_patch = payload.get("state_patch", {})
    state_patch = state_patch if isinstance(state_patch, dict) else {}
    canonical_object_keys = {}
    object_key_by_lore_id = {}
    ambiguous_object_lore_ids = set()
    for source in (snapshot.get("object_states", []), state_patch.get("object_states", [])):
        for item in source if isinstance(source, list) else []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", item.get("name", "")) or "").strip()
            compact = _compact_text(key)
            if compact and compact not in canonical_object_keys:
                canonical_object_keys[compact] = key

    valid_conflict_refs = {
        str(item.get("id", "") or "").strip()
        for item in snapshot.get("active_conflicts", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    valid_task_refs = {
        str(item.get("id", "") or "").strip()
        for item in snapshot.get("unresolved_tasks", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    for source_key, valid_refs in (
        ("active_conflicts", valid_conflict_refs),
        ("unresolved_tasks", valid_task_refs),
    ):
        for item in state_patch.get(source_key, []) if isinstance(state_patch.get(source_key), list) else []:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("id", "") or item.get("key", "") or "").strip()
            if ref:
                valid_refs.add(ref)

    def normalize_ref(storage_key, raw_ref):
        ref = str(raw_ref or "").strip()
        if not ref:
            return "", ""
        kind_by_key = {
            "character_refs": "characters",
            "lore_refs": "lore",
            "foreshadow_refs": "foreshadows",
        }
        if storage_key in kind_by_key:
            kind = kind_by_key[storage_key]
            item_id = _resolve_long_form_record_ref(project, kind, ref)
            if item_id:
                return item_id, ref
            if ref in temp_record_keys[kind]:
                return f"temp:{kind}:{ref}", ref
            return "", ""
        if storage_key == "fact_refs":
            return (ref, ref) if ref in valid_fact_refs else ("", "")
        if storage_key == "object_keys":
            compact = _compact_text(ref)
            canonical = canonical_object_keys.get(compact, "")
            return (f"object:{compact}", canonical) if canonical else ("", "")
        valid_refs = valid_conflict_refs if storage_key == "conflict_refs" else valid_task_refs
        return (ref, ref) if ref in valid_refs else ("", "")

    events = payload.get("long_term_events", [])
    if not isinstance(events, list):
        return payload
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("storage"), dict):
            continue
        storage = event["storage"]
        for storage_key in (
            "fact_refs", "character_refs", "lore_refs", "foreshadow_refs",
            "object_keys", "conflict_refs", "task_refs",
        ):
            values = storage.get(storage_key, [])
            if not isinstance(values, list):
                continue
            normalized = []
            seen = set()
            for value in values:
                identity, output = normalize_ref(storage_key, value)
                if not identity or identity in seen:
                    continue
                seen.add(identity)
                normalized.append(output)
            storage[storage_key] = normalized

    def item_evidence(item):
        return _compact_text(
            item.get("evidence_quote", item.get("evidence", item.get("quote", "")))
        ) if isinstance(item, dict) else ""

    link_requests = []

    def request_link(storage_key, raw_ref, item):
        if isinstance(item, dict):
            link_requests.append((storage_key, raw_ref, item))

    for item in payload.get("fact_updates", []) if isinstance(payload.get("fact_updates"), list) else []:
        if not isinstance(item, dict):
            continue
        operation = str(item.get("operation", "") or "").strip().lower()
        if operation in {"", "keep"}:
            continue
        ref = item.get("key", "") if operation in {"add", "supersede"} else item.get("id", "")
        request_link("fact_refs", ref, item)
    record_updates = payload.get("record_updates", {})
    record_updates = record_updates if isinstance(record_updates, dict) else {}
    for item in record_updates.get("lore", []) if isinstance(record_updates.get("lore"), list) else []:
        if not isinstance(item, dict):
            continue
        operation = str(item.get("operation", "") or "").strip().lower()
        ref = item.get("key", "") if operation == "create" else item.get("ref", item.get("id", ""))
        request_link("lore_refs", ref, item)
    for item in payload.get("foreshadow_updates", []) if isinstance(payload.get("foreshadow_updates"), list) else []:
        if not isinstance(item, dict):
            continue
        operation = str(item.get("operation", "") or "").strip().lower()
        ref = item.get("key", "") if operation == "create" else item.get("ref", item.get("id", ""))
        request_link("foreshadow_refs", ref, item)
    for item in state_patch.get("object_states", []) if isinstance(state_patch.get("object_states"), list) else []:
        if isinstance(item, dict):
            request_link("object_keys", item.get("key", item.get("name", "")), item)
    for source_key, storage_key in (
        ("active_conflicts", "conflict_refs"),
        ("unresolved_tasks", "task_refs"),
    ):
        for item in state_patch.get(source_key, []) if isinstance(state_patch.get(source_key), list) else []:
            if isinstance(item, dict):
                request_link(storage_key, item.get("id", "") or item.get("key", ""), item)

    evidence_anchors = {}
    for storage_key, raw_ref, item in link_requests:
        identity, _output = normalize_ref(storage_key, raw_ref)
        evidence = item_evidence(item)
        if not identity or len(evidence) < _EVIDENCE_MIN_LITERAL_CHARS:
            continue
        anchors = evidence_anchors.setdefault(evidence, [])
        anchor = (storage_key, identity)
        if anchor not in anchors:
            anchors.append(anchor)

    def event_has_ref(event, storage_key, identity):
        storage = event.get("storage", {}) if isinstance(event, dict) else {}
        if not isinstance(storage, dict):
            return False
        values = storage.get(storage_key, [])
        if not isinstance(values, list):
            return False
        return any(normalize_ref(storage_key, value)[0] == identity for value in values)

    def link_by_literal_evidence(storage_key, raw_ref, item):
        if not isinstance(item, dict):
            return
        identity, output = normalize_ref(storage_key, raw_ref)
        evidence = item_evidence(item)
        if not identity or len(evidence) < _EVIDENCE_MIN_LITERAL_CHARS:
            return
        match_indexes = []
        for index, event in enumerate(events):
            if not isinstance(event, dict) or not isinstance(event.get("storage"), dict):
                continue
            event_evidence = item_evidence(event)
            if len(event_evidence) < _EVIDENCE_MIN_LITERAL_CHARS:
                continue
            if evidence == event_evidence or evidence in event_evidence or event_evidence in evidence:
                match_indexes.append(index)
        if len(match_indexes) != 1:
            anchored_indexes = set()
            for anchor_key, anchor_identity in evidence_anchors.get(evidence, []):
                if anchor_key == storage_key and anchor_identity == identity:
                    continue
                for index, event in enumerate(events):
                    if event_has_ref(event, anchor_key, anchor_identity):
                        anchored_indexes.add(index)
            if len(anchored_indexes) == 1:
                match_indexes = list(anchored_indexes)
        if len(match_indexes) != 1:
            return
        storage = events[match_indexes[0]]["storage"]
        values = storage.get(storage_key)
        if not isinstance(values, list):
            values = []
            storage[storage_key] = values
        existing_identities = {
            normalize_ref(storage_key, value)[0]
            for value in values
        }
        if identity not in existing_identities:
            values.append(output)

    for storage_key, raw_ref, item in link_requests:
        link_by_literal_evidence(storage_key, raw_ref, item)
    return payload


def _long_form_object_record_namespace(project, item):
    """Return a record namespace when an object key is not a proven object key."""
    if not isinstance(item, dict):
        return ""
    raw_key = str(item.get("key", item.get("name", "")) or "").strip()
    if not raw_key:
        return ""
    for kind in ("characters", "lore", "foreshadows"):
        record_id = _resolve_long_form_record_ref(project, kind, raw_key)
        if not record_id:
            continue
        if kind == "lore":
            lore_ref = item.get("lore_ref", item.get("lore_id", ""))
            bound_lore_id = _resolve_long_form_record_ref(project, "lore", lore_ref)
            if bound_lore_id and bound_lore_id == record_id:
                return ""
        return kind
    return ""


def _normalize_long_form_structural_refs(project, chapter_index, update):
    payload = _normalize_long_form_event_storage_refs(project, chapter_index, update)
    reconciliation = payload.get("state_reconciliation", {})
    if not isinstance(reconciliation, dict):
        return payload

    def ensure_list(key):
        values = reconciliation.get(key)
        if values is None:
            reconciliation[key] = []
            return reconciliation[key]
        return values if isinstance(values, list) else None

    def append_unique(key, value):
        values = ensure_list(key)
        value = str(value or "").strip()
        if values is not None and value and value not in values:
            values.append(value)

    fact_updates = payload.get("fact_updates", [])
    for item in fact_updates if isinstance(fact_updates, list) else []:
        if not isinstance(item, dict):
            continue
        operation = str(item.get("operation", "") or "").strip().lower()
        ref = item.get("key", "") if operation in {"add", "supersede"} else item.get("id", "")
        append_unique("fact_refs", ref)

    record_updates = payload.get("record_updates", {})
    record_updates = record_updates if isinstance(record_updates, dict) else {}
    for kind, output_key in (("characters", "character_refs"), ("lore", "lore_refs")):
        items = record_updates.get(kind, [])
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            operation = str(item.get("operation", "") or "").strip().lower()
            ref = item.get("key", "") if operation == "create" else item.get("ref", item.get("id", ""))
            append_unique(output_key, ref)
    foreshadow_updates = payload.get("foreshadow_updates", [])
    for item in foreshadow_updates if isinstance(foreshadow_updates, list) else []:
        if not isinstance(item, dict):
            continue
        operation = str(item.get("operation", "") or "").strip().lower()
        ref = item.get("key", "") if operation == "create" else item.get("ref", item.get("id", ""))
        append_unique("foreshadow_refs", ref)

    state_patch = payload.get("state_patch", {})
    state_patch = state_patch if isinstance(state_patch, dict) else {}
    retirements = payload.get("state_retirements", {})
    retirements = retirements if isinstance(retirements, dict) else {}
    for item in state_patch.get("character_states", []) if isinstance(state_patch.get("character_states"), list) else []:
        if isinstance(item, dict):
            append_unique("character_refs", item.get("ref", item.get("character_id", "")))
    for ref in retirements.get("character_refs", []) if isinstance(retirements.get("character_refs"), list) else []:
        append_unique("character_refs", ref)

    for item in state_patch.get("object_states", []) if isinstance(state_patch.get("object_states"), list) else []:
        if not isinstance(item, dict):
            continue
        append_unique("lore_refs", item.get("lore_ref", item.get("lore_id", "")))
        append_unique("object_keys", item.get("key", item.get("name", "")))
    for value in retirements.get("object_keys", []) if isinstance(retirements.get("object_keys"), list) else []:
        append_unique("object_keys", value)

    def relationship_ref(value):
        refs = value if isinstance(value, list) else str(value or "").split("|")
        refs = sorted(str(ref or "").strip() for ref in refs if str(ref or "").strip())
        return "|".join(refs) if len(refs) >= 2 else ""

    for item in state_patch.get("relationship_states", []) if isinstance(state_patch.get("relationship_states"), list) else []:
        if isinstance(item, dict):
            append_unique("relationship_refs", relationship_ref(item.get("refs", item.get("characters", []))))
    for value in retirements.get("relationship_refs", []) if isinstance(retirements.get("relationship_refs"), list) else []:
        append_unique("relationship_refs", relationship_ref(value))

    for source_key, retirement_key, output_key in (
        ("active_conflicts", "conflict_ids", "conflict_refs"),
        ("unresolved_tasks", "task_ids", "task_refs"),
    ):
        for item in state_patch.get(source_key, []) if isinstance(state_patch.get(source_key), list) else []:
            if isinstance(item, dict):
                append_unique(output_key, item.get("id", "") or item.get("key", ""))
        for value in retirements.get(retirement_key, []) if isinstance(retirements.get(retirement_key), list) else []:
            append_unique(output_key, value)

    # Keep reference namespaces separate. Models occasionally copy a lore alias
    # such as L011 into object_keys because the lore record describes a physical
    # item. Only remove values that are proven record references; unknown values
    # remain visible to validation instead of being silently discarded.
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
    snapshot = memory.get("state_snapshot", {}) if isinstance(memory, dict) else {}
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    state_patch = payload.get("state_patch", {})
    state_patch = state_patch if isinstance(state_patch, dict) else {}
    canonical_object_keys = {}
    object_key_by_lore_id = {}
    ambiguous_object_lore_ids = set()
    for source in (
        snapshot.get("object_states", []),
        state_patch.get("object_states", []),
    ):
        for item in source if isinstance(source, list) else []:
            if not isinstance(item, dict):
                continue
            raw_key = str(item.get("key", item.get("name", "")) or "").strip()
            compact_key = _compact_text(raw_key)
            if compact_key and compact_key not in canonical_object_keys:
                canonical_object_keys[compact_key] = raw_key
            lore_ref = str(item.get("lore_id", item.get("lore_ref", "")) or "").strip()
            lore_id = _resolve_long_form_record_ref(project, "lore", lore_ref)
            if lore_id and raw_key:
                if lore_id in object_key_by_lore_id and object_key_by_lore_id[lore_id] != raw_key:
                    ambiguous_object_lore_ids.add(lore_id)
                else:
                    object_key_by_lore_id[lore_id] = raw_key

    def record_namespace(raw_value):
        raw_value = str(raw_value or "").strip()
        if not raw_value:
            return ""
        if _resolve_long_form_record_ref(project, "lore", raw_value):
            return "lore"
        if _resolve_long_form_record_ref(project, "foreshadows", raw_value):
            return "foreshadows"
        return ""

    def existing_object_for_record(raw_value, namespace):
        if namespace != "lore":
            return ""
        lore_id = _resolve_long_form_record_ref(project, "lore", raw_value)
        if not lore_id or lore_id in ambiguous_object_lore_ids:
            return ""
        return object_key_by_lore_id.get(lore_id, "")

    def append_owner_reference(owner, key, value):
        values = owner.get(key)
        if not isinstance(values, list):
            values = []
            owner[key] = values
        value = str(value or "").strip()
        if value and value not in values:
            values.append(value)

    def normalize_object_references(owner, key, preserve_record_namespace=False):
        values = owner.get(key)
        if not isinstance(values, list):
            return
        normalized = []
        for value in values:
            raw_value = str(value or "").strip()
            if not raw_value:
                continue
            namespace = record_namespace(raw_value)
            if namespace:
                output = existing_object_for_record(raw_value, namespace)
                if output:
                    if output not in normalized:
                        normalized.append(output)
                    continue
                # A same-named object already exists but has no unambiguous
                # lore binding. Keep the raw key so strict validation reports
                # the namespace collision instead of guessing its identity.
                if canonical_object_keys.get(_compact_text(raw_value), ""):
                    output = raw_value
                    if output not in normalized:
                        normalized.append(output)
                    continue
                target_key = (
                    "lore_refs" if namespace == "lore" else "foreshadow_refs"
                )
                append_unique(
                    target_key,
                    raw_value,
                )
                if preserve_record_namespace:
                    append_owner_reference(owner, target_key, raw_value)
                continue
            output = canonical_object_keys.get(_compact_text(raw_value), "") or raw_value
            if output not in normalized:
                normalized.append(output)
        owner[key] = normalized

    normalize_object_references(
        reconciliation,
        "object_keys",
        preserve_record_namespace=True,
    )
    lifecycle_review = payload.get("state_lifecycle_review", {})
    if isinstance(lifecycle_review, dict):
        normalize_object_references(lifecycle_review, "reviewed_object_keys")
    next_memory = payload.get("next_chapter_memory", {})
    if isinstance(next_memory, dict):
        normalize_object_references(
            next_memory,
            "object_keys",
            preserve_record_namespace=True,
        )
    normalize_object_references(retirements, "object_keys")
    return payload


def _long_form_evidence_present(quote, final_text):
    evidence = _compact_text(quote)
    return len(evidence) >= 4 and evidence in _compact_text(final_text)


_EVIDENCE_IGNORED_DIALOGUE_MARKS = frozenset('“”‘’"\'')
_EVIDENCE_CLAUSE_SPLIT_PATTERN = re.compile(r"[\r\n，。！？；：,!?;:]+")
_EVIDENCE_MIN_UNIQUE_CLAUSE_CHARS = 8
_EVIDENCE_MIN_LITERAL_CHARS = 8
_EVIDENCE_MAX_LITERAL_CHARS = 60


def _evidence_projection(value, with_positions=False):
    chars = []
    positions = []
    for index, char in enumerate(str(value or "")):
        if char.isspace() or char in _EVIDENCE_IGNORED_DIALOGUE_MARKS:
            continue
        chars.append(char)
        if with_positions:
            positions.append(index)
    return ("".join(chars), positions) if with_positions else "".join(chars)


def _expand_unique_short_long_form_evidence(quote, final_text):
    """Expand a unique short literal to nearby body text without inventing words."""
    raw_quote = str(quote or "").strip()
    body = str(final_text or "")
    projected_quote = _evidence_projection(raw_quote)
    projected_body, positions = _evidence_projection(body, with_positions=True)
    if not projected_quote or not positions:
        return raw_quote
    exact_line_matches = list(
        re.finditer(r"(?m)^[ \t]*" + re.escape(raw_quote) + r"[ \t]*$", body)
    )
    if len(exact_line_matches) == 1:
        line_match = exact_line_matches[0]
        body_start = line_match.start() + len(line_match.group()) - len(line_match.group().lstrip())
        body_end = body_start + len(raw_quote)
    else:
        start = projected_body.find(projected_quote)
        if start < 0 or projected_body.find(projected_quote, start + 1) >= 0:
            return raw_quote
        body_start = positions[start]
        body_end = positions[start + len(projected_quote) - 1] + 1
    boundaries = set("。！？!?；;\n")

    left = body_start
    while left > 0 and body[left - 1] not in boundaries:
        left -= 1
    right = body_end
    while right < len(body) and body[right] not in boundaries:
        right += 1
    if right < len(body):
        right += 1

    def candidate_text(start_index, end_index):
        return body[start_index:end_index].strip()

    candidate = candidate_text(left, right)
    while (
        len(_compact_text(candidate)) < _EVIDENCE_MIN_LITERAL_CHARS
        and right < len(body)
    ):
        next_boundary = right
        while next_boundary < len(body) and body[next_boundary] not in boundaries:
            next_boundary += 1
        if next_boundary < len(body):
            next_boundary += 1
        else:
            next_boundary = len(body)
        if next_boundary <= right:
            break
        right = next_boundary
        candidate = candidate_text(left, right)

    if len(_compact_text(candidate)) >= _EVIDENCE_MIN_LITERAL_CHARS:
        if len(_compact_text(candidate)) <= _EVIDENCE_MAX_LITERAL_CHARS:
            return candidate
        # Keep a literal local window when the containing sentence is unusually long.
        window_left = max(0, body_start - _EVIDENCE_MAX_LITERAL_CHARS // 2)
        window_right = min(len(body), window_left + _EVIDENCE_MAX_LITERAL_CHARS)
        window = candidate_text(window_left, window_right)
        if _long_form_evidence_present(window, body):
            return window
    return raw_quote


def _literalize_long_form_evidence_quote(quote, final_text):
    raw_quote = str(quote or "").strip()
    body = str(final_text or "")
    if _long_form_evidence_present(raw_quote, body):
        return raw_quote
    projected_quote = _evidence_projection(raw_quote)
    projected_body, positions = _evidence_projection(body, with_positions=True)
    if len(projected_quote) < 4:
        expanded = _expand_unique_short_long_form_evidence(raw_quote, body)
        if expanded != raw_quote:
            return expanded
    if len(projected_quote) < 4 or not positions:
        return raw_quote
    start = projected_body.find(projected_quote)
    if start >= 0 and projected_body.find(projected_quote, start + 1) < 0:
        end = start + len(projected_quote) - 1
        if end < len(positions):
            literal = body[positions[start]:positions[end] + 1].strip()
            if _long_form_evidence_present(literal, body):
                return literal

    # A model may alter only a subject or connector while copying the rest of
    # an evidence sentence. Keep validation literal by salvaging only a long,
    # unique clause that already exists verbatim in the final body.
    candidates = []
    for clause in _EVIDENCE_CLAUSE_SPLIT_PATTERN.split(raw_quote):
        projected_clause = _evidence_projection(clause)
        if len(projected_clause) >= _EVIDENCE_MIN_UNIQUE_CLAUSE_CHARS:
            candidates.append(projected_clause)
    for projected_clause in sorted(set(candidates), key=len, reverse=True):
        clause_start = projected_body.find(projected_clause)
        if clause_start < 0 or projected_body.find(projected_clause, clause_start + 1) >= 0:
            continue
        clause_end = clause_start + len(projected_clause) - 1
        if clause_end >= len(positions):
            continue
        literal = body[positions[clause_start]:positions[clause_end] + 1].strip()
        if _long_form_evidence_present(literal, body):
            return literal

    # A model may concatenate two non-adjacent dialogue fragments in one
    # evidence field. If no 8-character clause survives, expand a unique
    # 4-7 character literal fragment to its containing body sentence.
    short_candidates = []
    for clause in _EVIDENCE_CLAUSE_SPLIT_PATTERN.split(raw_quote):
        projected_clause = _evidence_projection(clause)
        if 4 <= len(projected_clause) < _EVIDENCE_MIN_UNIQUE_CLAUSE_CHARS:
            short_candidates.append(clause.strip())
    for clause in sorted(set(short_candidates), key=lambda value: len(_evidence_projection(value)), reverse=True):
        expanded = _expand_unique_short_long_form_evidence(clause, body)
        if (
            expanded != clause
            and len(_compact_text(expanded)) >= _EVIDENCE_MIN_LITERAL_CHARS
            and _long_form_evidence_present(expanded, body)
        ):
            return expanded
    return raw_quote


def _literalize_long_form_memory_evidence(update, final_text):
    payload = deepcopy(update) if isinstance(update, dict) else {}

    def literalize_items(items):
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            source_key = "evidence_quote" if "evidence_quote" in item else "evidence"
            quote = item.get(source_key, "")
            if str(quote or "").strip():
                item["evidence_quote"] = _literalize_long_form_evidence_quote(
                    quote, final_text
                )

    literalize_items(payload.get("fact_updates", []))
    record_updates = payload.get("record_updates", {})
    if isinstance(record_updates, dict):
        literalize_items(record_updates.get("characters", []))
        literalize_items(record_updates.get("lore", []))
    literalize_items(payload.get("foreshadow_updates", []))
    literalize_items(payload.get("long_term_events", []))
    return payload


_LONG_FORM_TEMP_SCOPE_REF_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(N(?:C|L|T|F)\d+)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


def _long_form_scope_temp_refs(value):
    return {
        match.upper()
        for match in _LONG_FORM_TEMP_SCOPE_REF_PATTERN.findall(str(value or ""))
    }


def _resolve_long_form_scope_temp_refs(project, value, temp_refs):
    text = str(value or "").strip()
    if not text:
        return text
    maps = _long_form_record_reference_maps(project)
    replacements = {}
    for kind in ("characters", "lore", "foreshadows"):
        for key, item_id in temp_refs.get(kind, {}).items() if isinstance(temp_refs.get(kind), dict) else []:
            alias = maps.get(kind, {}).get("id_to_alias", {}).get(str(item_id or "").strip(), "")
            if alias:
                replacements[str(key or "").strip().upper()] = alias

    def replace(match):
        return replacements.get(match.group(1).upper(), match.group(1))

    resolved = _LONG_FORM_TEMP_SCOPE_REF_PATTERN.sub(replace, text)
    if _long_form_scope_temp_refs(resolved):
        raise ValueError("事实scope仍含未映射临时引用")
    return resolved


def _resolve_long_form_stored_temp_refs(value, temp_refs):
    """Resolve temporary refs in chapter audit payloads after real IDs are allocated."""
    temp_refs = temp_refs if isinstance(temp_refs, dict) else {}
    kind_maps = {
        str(kind): {
            str(key or "").strip().casefold(): str(item_id or "").strip()
            for key, item_id in values.items()
            if str(key or "").strip() and str(item_id or "").strip()
        }
        for kind, values in temp_refs.items()
        if isinstance(values, dict)
    }
    field_kinds = {
        "character_id": "characters", "character_ref": "characters", "character_ids": "characters", "character_refs": "characters",
        "lore_id": "lore", "lore_ref": "lore", "lore_ids": "lore", "lore_refs": "lore",
        "foreshadow_id": "foreshadows", "foreshadow_ref": "foreshadows", "foreshadow_ids": "foreshadows", "foreshadow_refs": "foreshadows",
        "fact_id": "facts", "fact_ref": "facts", "fact_ids": "facts", "fact_refs": "facts",
        "object_key": "objects", "object_keys": "objects",
        "conflict_id": "conflicts", "conflict_ref": "conflicts", "conflict_ids": "conflicts", "conflict_refs": "conflicts",
        "task_id": "tasks", "task_ref": "tasks", "task_ids": "tasks", "task_refs": "tasks",
    }

    def resolve_one(raw, kind):
        text = str(raw or "").strip()
        if not text:
            return raw
        return kind_maps.get(kind, {}).get(text.casefold(), text)

    def resolve_any(raw):
        text = str(raw or "").strip()
        if not text:
            return raw
        for kind in ("characters", "lore", "foreshadows", "facts", "objects", "conflicts", "tasks", "archives"):
            resolved = kind_maps.get(kind, {}).get(text.casefold())
            if resolved:
                return resolved
        return raw

    def walk(current, key_hint=""):
        if isinstance(current, dict):
            result = {}
            for key, child in current.items():
                key_text = str(key or "")
                kind = field_kinds.get(key_text.casefold())
                hint = str(key_hint or "").casefold()
                hinted_kind = ""
                for marker, candidate_kind in (
                    ("conflict", "conflicts"), ("冲突", "conflicts"),
                    ("task", "tasks"), ("任务", "tasks"),
                    ("character", "characters"), ("人物", "characters"),
                    ("lore", "lore"), ("设定", "lore"),
                    ("foreshadow", "foreshadows"), ("伏笔", "foreshadows"),
                    ("fact", "facts"), ("事实", "facts"),
                    ("object", "objects"), ("物件", "objects"), ("物品", "objects"),
                ):
                    if marker in hint:
                        hinted_kind = candidate_kind
                        break
                if kind:
                    if isinstance(child, list):
                        result[key] = [
                            [resolve_any(item) for item in value] if isinstance(value, list)
                            else resolve_one(value, kind)
                            for value in child
                        ]
                    else:
                        result[key] = resolve_one(child, kind)
                elif key_text.casefold() in {"refs", "relationship_refs", "relationship_ids"} and isinstance(child, list):
                    result[key] = [
                        [resolve_any(item) for item in value] if isinstance(value, list)
                        else resolve_any(value)
                        for value in child
                    ]
                elif key_text.casefold() in {"id", "ref", "key"} and hinted_kind:
                    result[key] = resolve_one(child, hinted_kind)
                else:
                    next_hint = ".".join(part for part in (str(key_hint or ""), key_text) if part)
                    result[key] = walk(child, next_hint)
            return result
        if isinstance(current, list):
            return [walk(item, key_hint) for item in current]
        return current

    return walk(value)


def _resolve_long_form_temp_ref(temp_refs, kind, value, default=""):
    """Resolve a transaction-local key without changing unknown references."""
    text = str(value or "").strip()
    mapping = temp_refs.get(kind, {}) if isinstance(temp_refs, dict) else {}
    if not text or not isinstance(mapping, dict):
        return default
    if text in mapping:
        return mapping[text]
    folded = text.casefold()
    for key, item_id in mapping.items():
        if str(key or "").strip().casefold() == folded:
            return item_id
    return default


def _validate_long_form_memory_update(
    project,
    chapter_index,
    update,
    final_text="",
    require_revision=False,
    require_evidence=False,
):
    errors = []
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    if chapter_index < 0 or chapter_index >= len(chapters):
        return ["当前章节不存在"]
    if not isinstance(update, dict) or not update:
        return ["长篇记忆更新为空"]
    payload = _normalize_long_form_update_payload(project, chapter_index, update)
    memory = _backfill_long_form_fact_scopes(
        _normalize_long_form_memory(project.get("long_form_memory", {}))
    )
    if require_revision:
        try:
            schema_version = int(payload.get("schema_version", 0) or 0)
        except Exception:
            schema_version = 0
        if schema_version != 2:
            errors.append("schema_version必须为2")
        try:
            base_revision = int(payload.get("base_revision", -1))
        except Exception:
            base_revision = -1
        if base_revision != int(memory.get("revision", 0) or 0):
            errors.append(
                f"base_revision不匹配：应为{memory.get('revision', 0)}，实际为{payload.get('base_revision', '')}"
            )
    state_patch = payload.get("state_patch")
    if not isinstance(state_patch, dict):
        errors.append("state_patch必须为对象")
        state_patch = {}
    state_retirements = payload.get("state_retirements")
    if not isinstance(state_retirements, dict):
        errors.append("state_retirements必须为对象")
        state_retirements = {}
    existing_state_refs = _long_form_existing_state_refs(project, memory)
    chapter_selection = chapters[chapter_index].get("memory_selection", {})
    chapter_selection = chapter_selection if isinstance(chapter_selection, dict) else {}
    selected_fact_ids = {
        str(value or "").strip()
        for value in chapter_selection.get("fact_ids", [])
        if str(value or "").strip()
    }
    selected_object_compacts = {
        _compact_text(value)
        for value in chapter_selection.get("object_keys", [])
        if _compact_text(value)
    }
    selected_conflict_ids = {
        str(value or "").strip()
        for value in chapter_selection.get("conflict_ids", [])
        if str(value or "").strip()
    }
    selected_task_ids = {
        str(value or "").strip()
        for value in chapter_selection.get("task_ids", [])
        if str(value or "").strip()
    }
    selection_has_refs = any(
        isinstance(chapter_selection.get(key), list)
        and any(str(value or "").strip() for value in chapter_selection.get(key, []))
        for key in (
            "fact_ids", "character_ids", "lore_ids", "foreshadow_ids",
            "object_keys", "conflict_ids", "task_ids",
        )
    )
    previous_chapter = chapters[chapter_index - 1] if chapter_index > 0 else {}
    missing_committed_handoff = (
        not selection_has_refs
        and isinstance(previous_chapter, dict)
        and str(previous_chapter.get("memory_sync_status", "") or "") == "complete"
        and int(previous_chapter.get("memory_revision", 0) or 0) > 0
    )
    if missing_committed_handoff:
        # An absent handoff makes the context builder send the full active
        # memory packet. Mirror that actual visibility for retirement checks;
        # otherwise a fully evidenced completion is rejected merely because
        # an imported or externally committed predecessor missed its index.
        selected_fact_ids = {
            str(item.get("id", "") or "").strip()
            for item in memory.get("active_facts", [])
            if isinstance(item, dict) and str(item.get("id", "") or "").strip()
        }
        selected_object_compacts = set(existing_state_refs["object_key_by_compact"])
        selected_conflict_ids = set(existing_state_refs["conflict_ids"])
        selected_task_ids = set(existing_state_refs["task_ids"])

    proposed_record_keys = {"characters": set(), "lore": set(), "foreshadows": set()}
    proposed_state_keys = {"conflicts": set(), "tasks": set()}
    proposed_record_updates = payload.get("record_updates", {})
    if isinstance(proposed_record_updates, dict):
        for kind in ("characters", "lore"):
            for item in proposed_record_updates.get(kind, []) if isinstance(proposed_record_updates.get(kind), list) else []:
                if isinstance(item, dict) and str(item.get("operation", "") or "").strip().lower() == "create":
                    key = str(item.get("key", "") or "").strip()
                    if key:
                        proposed_record_keys[kind].add(key)
    for item in payload.get("foreshadow_updates", []) if isinstance(payload.get("foreshadow_updates"), list) else []:
        if isinstance(item, dict) and str(item.get("operation", "") or "").strip().lower() == "create":
            key = str(item.get("key", "") or "").strip()
            if key:
                proposed_record_keys["foreshadows"].add(key)

    def resolves_existing_or_proposed(kind, ref):
        return bool(
            _resolve_long_form_record_ref(project, kind, ref)
            or str(ref or "").strip() in proposed_record_keys[kind]
        )

    if require_revision:
        snapshot = memory.get("state_snapshot", {}) if isinstance(memory.get("state_snapshot"), dict) else {}

        for key in (
            "character_states", "relationship_states", "object_states",
            "active_conflicts", "unresolved_tasks",
        ):
            if key in state_patch and not isinstance(state_patch.get(key), list):
                errors.append(f"state_patch.{key}必须为数组")

        for index, item in enumerate(
            state_patch.get("character_states", [])
            if isinstance(state_patch.get("character_states"), list) else [],
            1,
        ):
            if not isinstance(item, dict):
                errors.append(f"人物状态第{index}项不是对象")
                continue
            ref = item.get("ref", item.get("character_id", ""))
            if not resolves_existing_or_proposed("characters", ref):
                errors.append(f"人物状态第{index}项引用未知人物：{ref}")
            if not str(item.get("state", "") or "").strip():
                errors.append(f"人物状态第{index}项状态为空")

        for index, item in enumerate(
            state_patch.get("relationship_states", [])
            if isinstance(state_patch.get("relationship_states"), list) else [],
            1,
        ):
            if not isinstance(item, dict):
                errors.append(f"关系状态第{index}项不是对象")
                continue
            refs = item.get("refs", item.get("characters", []))
            refs = refs if isinstance(refs, list) else []
            if len(refs) < 2 or any(
                not resolves_existing_or_proposed("characters", ref) for ref in refs
            ):
                errors.append(f"关系状态第{index}项人物引用无效")
            if not str(item.get("state", "") or "").strip():
                errors.append(f"关系状态第{index}项状态为空")

        for index, item in enumerate(
            state_patch.get("object_states", [])
            if isinstance(state_patch.get("object_states"), list) else [],
            1,
        ):
            if not isinstance(item, dict):
                errors.append(f"物品状态第{index}项不是对象")
                continue
            lore_ref = item.get("lore_ref", item.get("lore_id", ""))
            if str(lore_ref or "").strip() and not resolves_existing_or_proposed("lore", lore_ref):
                errors.append(f"物品状态第{index}项引用未知设定：{lore_ref}")
            if not str(item.get("key", item.get("name", "")) or "").strip():
                errors.append(f"物品状态第{index}项稳定键或名称为空")
            if not str(item.get("state", "") or "").strip():
                errors.append(f"物品状态第{index}项状态为空")

        existing_conflicts = {
            str(item.get("id", "") or "").strip(): item
            for item in snapshot.get("active_conflicts", [])
            if isinstance(item, dict) and str(item.get("id", "") or "").strip()
        }
        existing_tasks = {
            str(item.get("id", "") or "").strip(): item
            for item in snapshot.get("unresolved_tasks", [])
            if isinstance(item, dict) and str(item.get("id", "") or "").strip()
        }
        existing_conflict_ids = set(existing_conflicts)
        existing_task_ids = set(existing_tasks)
        for patch_key, text_key, previous_key, known_records, label in (
            ("active_conflicts", "conflict", "previous_conflict", existing_conflicts, "冲突"),
            ("unresolved_tasks", "task", "previous_task", existing_tasks, "任务"),
        ):
            for index, item in enumerate(
                state_patch.get(patch_key, []) if isinstance(state_patch.get(patch_key), list) else [],
                1,
            ):
                if not isinstance(item, dict):
                    errors.append(f"{label}状态第{index}项不是对象")
                    continue
                item_id = str(item.get("id", "") or "").strip()
                if item_id and item_id not in known_records:
                    errors.append(f"{label}状态第{index}项引用未知ID：{item_id}")
                elif item_id and require_evidence:
                    previous = str(item.get(previous_key, "") or "").strip()
                    expected = str(
                        known_records[item_id].get(text_key, "") or ""
                    ).strip()
                    previous_compact = _compact_text(previous)
                    expected_compact = _compact_text(expected)
                    truncated_prefix = previous_compact.rstrip(".…")
                    previous_matches = previous_compact == expected_compact
                    if (
                        not previous_matches
                        and len(truncated_prefix) >= 80
                        and previous_compact != truncated_prefix
                        and expected_compact.startswith(truncated_prefix)
                    ):
                        previous_matches = True
                    if not previous_matches:
                        errors.append(
                            f"{label}状态第{index}项{previous_key}与旧状态不匹配"
                        )
                if not item_id:
                    key = str(item.get("key", "") or "").strip()
                    state_kind = "conflicts" if patch_key == "active_conflicts" else "tasks"
                    if require_evidence and (not key or key in proposed_state_keys[state_kind]):
                        errors.append(f"{label}状态第{index}项新增key缺失或重复")
                    if key:
                        proposed_state_keys[state_kind].add(key)
                if not str(item.get(text_key, "") or "").strip():
                    errors.append(f"{label}状态第{index}项内容为空")

        retirement_keys = (
            "character_refs", "relationship_refs", "object_keys", "conflict_ids", "task_ids",
        )
        for key in retirement_keys:
            if key in state_retirements and not isinstance(state_retirements.get(key), list):
                errors.append(f"state_retirements.{key}必须为数组")

        active_character_ids = {
            str(item.get("character_id", "") or "").strip()
            for item in snapshot.get("character_states", [])
            if isinstance(item, dict) and str(item.get("character_id", "") or "").strip()
        }
        for ref in state_retirements.get("character_refs", []) if isinstance(state_retirements.get("character_refs"), list) else []:
            item_id = _resolve_long_form_record_ref(project, "characters", ref)
            if not item_id or item_id not in active_character_ids:
                errors.append(f"退出人物状态引用不存在或已退出：{ref}")

        active_relationship_keys = {
            "|".join(sorted(
                str(value or "").strip()
                for value in item.get("characters", []) if str(value or "").strip()
            ))
            for item in snapshot.get("relationship_states", []) if isinstance(item, dict)
        }
        for value in state_retirements.get("relationship_refs", []) if isinstance(state_retirements.get("relationship_refs"), list) else []:
            refs = value if isinstance(value, list) else str(value or "").split("|")
            ids = [_resolve_long_form_record_ref(project, "characters", ref) for ref in refs]
            key = "|".join(sorted(item_id for item_id in ids if item_id))
            if len(ids) < 2 or any(not item_id for item_id in ids) or key not in active_relationship_keys:
                errors.append(f"退出关系状态引用不存在或已退出：{value}")

        active_object_keys = {
            _compact_text(item.get("key", item.get("name", "")))
            for item in snapshot.get("object_states", [])
            if isinstance(item, dict) and _compact_text(item.get("key", item.get("name", "")))
        }
        for value in state_retirements.get("object_keys", []) if isinstance(state_retirements.get("object_keys"), list) else []:
            if _compact_text(value) not in active_object_keys:
                errors.append(f"退出物品状态键不存在或已退出：{value}")
            elif require_evidence and _compact_text(value) not in selected_object_compacts:
                errors.append(f"退出物品状态未进入本章选择：{value}")
        for value in state_retirements.get("conflict_ids", []) if isinstance(state_retirements.get("conflict_ids"), list) else []:
            if str(value or "").strip() not in existing_conflict_ids:
                errors.append(f"退出冲突ID不存在或已退出：{value}")
            elif require_evidence and str(value or "").strip() not in selected_conflict_ids:
                errors.append(f"退出冲突未进入本章选择：{value}")
        for value in state_retirements.get("task_ids", []) if isinstance(state_retirements.get("task_ids"), list) else []:
            if str(value or "").strip() not in existing_task_ids:
                errors.append(f"退出任务ID不存在或已退出：{value}")
            elif require_evidence and str(value or "").strip() not in selected_task_ids:
                errors.append(f"退出任务未进入本章选择：{value}")

    state_lifecycle_review = payload.get("state_lifecycle_review", {})
    if require_evidence and not isinstance(state_lifecycle_review, dict):
        errors.append("state_lifecycle_review必须为对象")
        state_lifecycle_review = {}
    if require_evidence:
        stage_boundary = (chapter_index + 1) % 10 == 0
        expected_scope = LONG_FORM_STAGE_REVIEW_SCOPE if stage_boundary else "current_chapter"
        if str(state_lifecycle_review.get("scope", "") or "").strip() != expected_scope:
            errors.append(f"state_lifecycle_review.scope必须为{expected_scope}")

        review_fields = (
            ("reviewed_object_keys", "物件", "object_keys"),
            ("reviewed_conflict_refs", "冲突", "conflict_refs"),
            ("reviewed_task_refs", "任务", "task_refs"),
        )
        reviewed = {}
        for field, label, output_key in review_fields:
            values = state_lifecycle_review.get(field, [])
            if not isinstance(values, list):
                errors.append(f"state_lifecycle_review.{field}必须为数组")
                values = []
            reviewed[output_key] = {
                str(value or "").strip() for value in values if str(value or "").strip()
            }

        existing_object_keys = existing_state_refs["object_key_by_compact"]
        reviewable_object_keys = dict(existing_object_keys)
        # The lifecycle review may mention an object introduced in the same
        # state patch. Add only genuine object keys here; lore/character
        # record ids remain invalid object references.
        for item in state_patch.get("object_states", []) if isinstance(state_patch.get("object_states"), list) else []:
            if not isinstance(item, dict):
                continue
            raw_key = str(item.get("key", item.get("name", "")) or "").strip()
            compact_key = _compact_text(raw_key)
            if compact_key and not _long_form_object_record_namespace(project, item):
                reviewable_object_keys.setdefault(compact_key, raw_key)
        unknown_reviewed_objects = sorted(
            value for value in reviewed["object_keys"]
            if _compact_text(value) not in reviewable_object_keys
        )
        if unknown_reviewed_objects:
            errors.append("状态生命周期复核引用未知物件：" + "、".join(unknown_reviewed_objects[:8]))
        unknown_reviewed_conflicts = sorted(
            reviewed["conflict_refs"] - existing_state_refs["conflict_ids"]
        )
        if unknown_reviewed_conflicts:
            errors.append("状态生命周期复核引用未知冲突：" + "、".join(unknown_reviewed_conflicts[:8]))
        unknown_reviewed_tasks = sorted(
            reviewed["task_refs"] - existing_state_refs["task_ids"]
        )
        if unknown_reviewed_tasks:
            errors.append("状态生命周期复核引用未知任务：" + "、".join(unknown_reviewed_tasks[:8]))

        selected_object_values = chapter_selection.get("object_keys", [])
        selected_object_values = selected_object_values if isinstance(selected_object_values, list) else []
        selected_conflict_values = chapter_selection.get("conflict_ids", [])
        selected_conflict_values = selected_conflict_values if isinstance(selected_conflict_values, list) else []
        selected_task_values = chapter_selection.get("task_ids", [])
        selected_task_values = selected_task_values if isinstance(selected_task_values, list) else []
        required_state_review = {
            "object_keys": {
                existing_object_keys[_compact_text(value)]
                for value in selected_object_values
                if _compact_text(value) in existing_object_keys
            },
            "conflict_refs": {
                str(value or "").strip()
                for value in selected_conflict_values
                if str(value or "").strip() in existing_state_refs["conflict_ids"]
            },
            "task_refs": {
                str(value or "").strip()
                for value in selected_task_values
                if str(value or "").strip() in existing_state_refs["task_ids"]
            },
        }

        snapshot_for_state_review = memory.get("state_snapshot", {})
        snapshot_for_state_review = snapshot_for_state_review if isinstance(snapshot_for_state_review, dict) else {}
        existing_object_key_by_lore = {
            str(item.get("lore_id", "") or "").strip(): str(
                item.get("key", item.get("name", "")) or ""
            ).strip()
            for item in snapshot_for_state_review.get("object_states", [])
            if isinstance(item, dict)
            and str(item.get("lore_id", "") or "").strip()
            and str(item.get("key", item.get("name", "")) or "").strip()
        }
        for item in state_patch.get("object_states", []) if isinstance(state_patch.get("object_states"), list) else []:
            if not isinstance(item, dict):
                continue
            compact = _compact_text(item.get("key", item.get("name", "")))
            if compact in existing_object_keys:
                required_state_review["object_keys"].add(existing_object_keys[compact])
                continue
            lore_id = _resolve_long_form_record_ref(
                project, "lore", item.get("lore_ref", item.get("lore_id", ""))
            )
            if lore_id in existing_object_key_by_lore:
                required_state_review["object_keys"].add(existing_object_key_by_lore[lore_id])
        required_state_review["object_keys"].update(
            existing_object_keys[_compact_text(value)]
            for value in state_retirements.get("object_keys", [])
            if _compact_text(value) in existing_object_keys
        )
        required_state_review["conflict_refs"].update(
            str(item.get("id", "") or "").strip()
            for item in state_patch.get("active_conflicts", [])
            if isinstance(item, dict)
            and str(item.get("id", "") or "").strip() in existing_state_refs["conflict_ids"]
        )
        required_state_review["conflict_refs"].update(
            str(value or "").strip()
            for value in state_retirements.get("conflict_ids", [])
            if str(value or "").strip() in existing_state_refs["conflict_ids"]
        )
        required_state_review["task_refs"].update(
            str(item.get("id", "") or "").strip()
            for item in state_patch.get("unresolved_tasks", [])
            if isinstance(item, dict)
            and str(item.get("id", "") or "").strip() in existing_state_refs["task_ids"]
        )
        required_state_review["task_refs"].update(
            str(value or "").strip()
            for value in state_retirements.get("task_ids", [])
            if str(value or "").strip() in existing_state_refs["task_ids"]
        )

        reviewed_object_compacts = {_compact_text(value) for value in reviewed["object_keys"]}
        missing_objects = sorted(
            value for value in required_state_review["object_keys"]
            if _compact_text(value) not in reviewed_object_compacts
        )
        if missing_objects:
            errors.append("状态生命周期复核遗漏物件：" + "、".join(missing_objects[:12]))
        missing_conflicts = sorted(
            required_state_review["conflict_refs"] - reviewed["conflict_refs"]
        )
        if missing_conflicts:
            errors.append("状态生命周期复核遗漏冲突：" + "、".join(missing_conflicts[:12]))
        missing_tasks = sorted(required_state_review["task_refs"] - reviewed["task_refs"])
        if missing_tasks:
            errors.append("状态生命周期复核遗漏任务：" + "、".join(missing_tasks[:12]))

    fact_updates = payload.get("fact_updates", [])
    if not isinstance(fact_updates, list):
        errors.append("fact_updates必须为数组")
        fact_updates = []
    existing_fact_records = {
        str(item.get("id", "") or "").strip(): item
        for item in memory.get("active_facts", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    existing_fact_ids = set(existing_fact_records)
    temp_fact_keys = set()
    touched_existing_fact_ids = set()
    for index, item in enumerate(fact_updates, 1):
        if not isinstance(item, dict):
            errors.append(f"fact_updates第{index}项不是对象")
            continue
        operation = str(item.get("operation", "") or "").strip().lower()
        if operation not in {"add", "keep", "update", "retire", "supersede"}:
            errors.append(f"fact_updates第{index}项operation无效")
            continue
        item_id = str(item.get("id", "") or "").strip()
        scope = str(item.get("scope", "") or "").strip()
        if operation in {"add", "supersede"}:
            key = str(item.get("key", "") or "").strip()
            if not key or key in temp_fact_keys:
                errors.append(f"fact_updates第{index}项新增key缺失或重复")
            temp_fact_keys.add(key)
            if not str(item.get("fact", "") or "").strip():
                errors.append(f"fact_updates第{index}项新增事实为空")
            if require_evidence and not scope:
                errors.append(f"fact_updates第{index}项scope为空")
        if require_evidence and scope:
            allowed_temp_scope_refs = {
                str(value or "").strip().upper()
                for values in proposed_record_keys.values()
                for value in values
                if str(value or "").strip()
            }
            unresolved_temp_scope_refs = (
                _long_form_scope_temp_refs(scope) - allowed_temp_scope_refs
            )
            if unresolved_temp_scope_refs:
                errors.append(
                    f"fact_updates第{index}项scope含未映射临时引用："
                    + "、".join(sorted(unresolved_temp_scope_refs))
                )
        if operation != "add":
            if item_id not in existing_fact_ids:
                errors.append(f"fact_updates第{index}项引用未知事实ID：{item_id}")
            else:
                touched_existing_fact_ids.add(item_id)
        if operation == "update":
            if not str(item.get("fact", "") or "").strip():
                errors.append(f"fact_updates第{index}项更新事实为空")
            if require_evidence and not scope:
                errors.append(f"fact_updates第{index}项scope为空")
        if operation in {"update", "retire", "supersede"} and item_id in existing_fact_ids:
            existing_scope = str(
                existing_fact_records.get(item_id, {}).get("scope", "") or ""
            ).strip()
            if _compact_text(existing_scope).casefold() != _compact_text(scope).casefold():
                errors.append(
                    f"fact_updates第{index}项{operation}的scope与旧事实不匹配；"
                    "update/retire/supersede只能用于同一scope，scope变更必须新增事实"
                )
        if operation in {"retire", "supersede"} and item_id in existing_fact_ids:
            if require_evidence and item_id not in selected_fact_ids:
                errors.append(f"fact_updates第{index}项退出事实未进入本章选择：{item_id}")
            previous_fact = str(item.get("previous_fact", "") or "").strip()
            expected_fact = str(
                existing_fact_records.get(item_id, {}).get("fact", "") or ""
            ).strip()
            if require_evidence and _compact_text(previous_fact) != _compact_text(expected_fact):
                errors.append(f"fact_updates第{index}项previous_fact与旧事实不匹配")
        if operation in {"retire", "supersede"} and not str(item.get("reason", "") or "").strip():
            errors.append(f"fact_updates第{index}项退出原因为空")
        if require_evidence and operation != "keep" and not _long_form_evidence_present(
            item.get("evidence_quote", item.get("evidence", "")), final_text
        ):
            errors.append(f"fact_updates第{index}项缺少正文逐字证据")

    lifecycle_review = payload.get("fact_lifecycle_review", {})
    if require_evidence and not isinstance(lifecycle_review, dict):
        errors.append("fact_lifecycle_review必须为对象")
        lifecycle_review = {}
    if require_evidence:
        expected_scope = LONG_FORM_STAGE_REVIEW_SCOPE if (chapter_index + 1) % 10 == 0 else "current_chapter"
        if str(lifecycle_review.get("scope", "") or "").strip() != expected_scope:
            errors.append(f"fact_lifecycle_review.scope必须为{expected_scope}")
        reviewed_refs = lifecycle_review.get("reviewed_refs", [])
        if not isinstance(reviewed_refs, list):
            errors.append("fact_lifecycle_review.reviewed_refs必须为数组")
            reviewed_refs = []
        reviewed_ids = {str(value or "").strip() for value in reviewed_refs if str(value or "").strip()}
        unknown_reviewed = sorted(reviewed_ids - existing_fact_ids)
        if unknown_reviewed:
            errors.append("事实生命周期复核引用未知ID：" + "、".join(unknown_reviewed[:8]))
        required_selected_fact_ids = {
            str(value or "").strip()
            for value in chapter_selection.get("fact_ids", [])
            if str(value or "").strip() in existing_fact_ids
        }
        required_review_ids = set(required_selected_fact_ids)
        required_review_ids.update(touched_existing_fact_ids)
        missing_reviewed = sorted(required_review_ids - reviewed_ids)
        if missing_reviewed:
            errors.append("事实生命周期复核遗漏：" + "、".join(missing_reviewed[:12]))

    reference_maps = _long_form_record_reference_maps(project)
    temp_record_keys = {"characters": set(), "lore": set(), "foreshadows": set()}
    temp_record_names = {"characters": set(), "lore": set(), "foreshadows": set()}

    def validate_record_updates(kind, items):
        if not isinstance(items, list):
            errors.append(f"{kind}更新必须为数组")
            return
        for index, item in enumerate(items, 1):
            if not isinstance(item, dict):
                errors.append(f"{kind}更新第{index}项不是对象")
                continue
            operation = str(item.get("operation", "") or "").strip().lower()
            if operation not in {"create", "update"}:
                errors.append(f"{kind}更新第{index}项operation无效")
                continue
            if operation == "update":
                ref = str(item.get("ref", item.get("id", "")) or "").strip()
                resolved_ref = _resolve_long_form_record_ref(project, kind, ref)
                if not resolved_ref:
                    errors.append(f"{kind}更新第{index}项引用未知记录：{ref}")
                incoming_name = str(item.get("name", "") or "").strip()
                is_identity_promotion = False
                if kind == "characters" and incoming_name and resolved_ref:
                    record = reference_maps[kind]["id_to_record"].get(resolved_ref, {})
                    current_name = str(record.get("name", "") or "").strip()
                    is_identity_promotion = bool(
                        _compact_text(current_name).casefold()
                        != _compact_text(incoming_name).casefold()
                        and _is_temporary_character_name(current_name)
                        and not _is_temporary_character_name(incoming_name)
                    )
                    if (
                        _compact_text(current_name).casefold()
                        != _compact_text(incoming_name).casefold()
                        and (
                            not _is_temporary_character_name(current_name)
                            or _is_temporary_character_name(incoming_name)
                        )
                    ):
                        errors.append(
                            f"characters更新第{index}项只能把临时人物升级为正式姓名："
                            f"{current_name} -> {incoming_name}"
                        )
                changes = item.get("changes", [])
                has_changes = (
                    bool(str(changes or "").strip())
                    if not isinstance(changes, list)
                    else any(str(value or "").strip() for value in changes)
                )
                has_identity_patch = bool(
                    kind == "characters"
                    and isinstance(item.get("identity_patch"), dict)
                    and any(
                        str(value or "").strip()
                        for value in item.get("identity_patch", {}).values()
                    )
                )
                if (
                    require_evidence
                    and not str(item.get("state", "") or "").strip()
                    and not has_changes
                    and not incoming_name
                    and not has_identity_patch
                ):
                    errors.append(f"{kind}更新第{index}项运行态变化为空")
                if isinstance(item.get("canon"), dict) and any(
                    str(value or "").strip() for value in item.get("canon", {}).values()
                ) and not is_identity_promotion:
                    errors.append(f"{kind}更新第{index}项不得修改永久canon字段")
            else:
                name = str(item.get("name", "") or "").strip()
                promotion_ref = str(item.get("ref", item.get("id", "")) or "").strip()
                promotion_id = _resolve_long_form_record_ref(project, kind, promotion_ref)
                promotion_record = reference_maps[kind]["id_to_record"].get(promotion_id)
                is_promotion = bool(
                    kind == "characters"
                    and promotion_record is not None
                    and promotion_id
                )
                if is_promotion:
                    current_name = str(promotion_record.get("name", "") or "").strip()
                    if (
                        not name
                        or not _is_temporary_character_name(current_name)
                        or _is_temporary_character_name(name)
                    ):
                        errors.append(
                            f"characters更新第{index}项create带旧ref时必须是临时人物到正式姓名升级"
                        )
                    key = str(item.get("key", "") or "").strip()
                    if key:
                        if key in temp_record_keys[kind]:
                            errors.append(f"{kind}更新第{index}项新增key重复")
                        temp_record_keys[kind].add(key)
                else:
                    key = str(item.get("key", "") or "").strip()
                    if not key or key in temp_record_keys[kind]:
                        errors.append(f"{kind}更新第{index}项新增key缺失或重复")
                    temp_record_keys[kind].add(key)
                    if not name:
                        errors.append(f"{kind}更新第{index}项新增名称为空")
                if name and require_evidence and not is_promotion:
                    compact_name = _compact_text(
                        _clean_foreshadow_name(name) if kind == "foreshadows" else name
                    ).casefold()
                    existing_names = {
                        _compact_text(
                            _clean_foreshadow_name(record.get("name", ""))
                            if kind == "foreshadows" else record.get("name", "")
                        ).casefold()
                        for record in reference_maps[kind]["id_to_record"].values()
                        if isinstance(record, dict)
                    }
                    if compact_name in existing_names or compact_name in temp_record_names[kind]:
                        errors.append(
                            f"{kind}更新第{index}项新增名称与已有记录或本次新增重名；"
                            "同一实体应update，新证据批次必须使用可区分的新名称"
                        )
                    temp_record_names[kind].add(compact_name)
            if kind == "foreshadows" and require_evidence:
                status = str(item.get("status", "") or "").strip()
                if status in {"已埋", "已回收"}:
                    if not str(item.get("revealed", "") or "").strip():
                        errors.append(f"伏笔更新第{index}项{status}但revealed为空")
                    if "remaining_secret" not in item:
                        errors.append(f"伏笔更新第{index}项{status}但缺少remaining_secret")
            if (
                kind == "lore"
                and require_evidence
                and operation == "create"
                and not str(item.get("story_known", "") or "").strip()
            ):
                errors.append(f"lore更新第{index}项新增设定缺少story_known")
            if require_evidence and not _long_form_evidence_present(
                item.get("evidence_quote", item.get("evidence", "")), final_text
            ):
                errors.append(f"{kind}更新第{index}项缺少正文逐字证据")

    record_updates = payload.get("record_updates", {})
    if not isinstance(record_updates, dict):
        errors.append("record_updates必须为对象")
        record_updates = {}
    validate_record_updates("characters", record_updates.get("characters", []))
    validate_record_updates("lore", record_updates.get("lore", []))
    validate_record_updates("foreshadows", payload.get("foreshadow_updates", []))

    current_refs = payload.get("current_chapter_character_refs", [])
    if not isinstance(current_refs, list):
        errors.append("current_chapter_character_refs必须为数组")
    else:
        for ref in current_refs:
            if not _resolve_long_form_record_ref(project, "characters", ref) and str(ref or "") not in temp_record_keys["characters"]:
                errors.append(f"本章人物引用无效：{ref}")

    snapshot_for_review = memory.get("state_snapshot", {})
    snapshot_for_review = snapshot_for_review if isinstance(snapshot_for_review, dict) else {}
    valid_object_keys = {
        _compact_text(item.get("key", item.get("name", "")))
        for item in snapshot_for_review.get("object_states", [])
        if isinstance(item, dict) and _compact_text(item.get("key", item.get("name", "")))
    }
    valid_object_keys.update(
        _compact_text(item.get("key", item.get("name", "")))
        for item in state_patch.get("object_states", [])
        if isinstance(item, dict) and _compact_text(item.get("key", item.get("name", "")))
    )
    invalid_object_namespace_keys = set()
    for source in (
        snapshot_for_review.get("object_states", []),
        state_patch.get("object_states", []),
    ):
        for item in source if isinstance(source, list) else []:
            if not isinstance(item, dict):
                continue
            compact_key = _compact_text(item.get("key", item.get("name", "")))
            if compact_key and _long_form_object_record_namespace(project, item):
                invalid_object_namespace_keys.add(compact_key)
    valid_object_keys.difference_update(invalid_object_namespace_keys)
    for index, item in enumerate(
        state_patch.get("object_states", [])
        if isinstance(state_patch.get("object_states"), list) else [],
        1,
    ):
        namespace = _long_form_object_record_namespace(project, item)
        if namespace:
            raw_key = str(item.get("key", item.get("name", "")) or "").strip()
            errors.append(
                f"物品状态第{index}项不能直接使用{namespace}记录编号作为物件键：{raw_key}"
            )
    valid_conflict_refs = {
        str(item.get("id", "") or "").strip()
        for item in snapshot_for_review.get("active_conflicts", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    } | proposed_state_keys["conflicts"]
    valid_task_refs = {
        str(item.get("id", "") or "").strip()
        for item in snapshot_for_review.get("unresolved_tasks", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    } | proposed_state_keys["tasks"]

    def valid_record_ref(kind, ref):
        return bool(
            _resolve_long_form_record_ref(project, kind, ref)
            or str(ref or "").strip() in temp_record_keys[kind]
        )

    def validate_storage(storage, label):
        if not isinstance(storage, dict):
            errors.append(f"{label}.storage必须为对象")
            return False
        any_target = False
        for key in (
            "fact_refs", "character_refs", "lore_refs", "foreshadow_refs",
            "object_keys", "conflict_refs", "task_refs",
        ):
            values = storage.get(key, [])
            if not isinstance(values, list):
                errors.append(f"{label}.storage.{key}必须为数组")
                continue
            any_target = any_target or any(str(value or "").strip() for value in values)
            for value in values:
                ref = str(value or "").strip()
                if not ref:
                    continue
                if key == "fact_refs" and ref not in existing_fact_ids | temp_fact_keys:
                    errors.append(f"{label}引用未知事实：{ref}")
                elif key == "character_refs" and not valid_record_ref("characters", ref):
                    errors.append(f"{label}引用未知人物：{ref}")
                elif key == "lore_refs" and not valid_record_ref("lore", ref):
                    errors.append(f"{label}引用未知设定：{ref}")
                elif key == "foreshadow_refs" and not valid_record_ref("foreshadows", ref):
                    errors.append(f"{label}引用未知伏笔：{ref}")
                elif key == "object_keys" and _compact_text(ref) not in valid_object_keys:
                    errors.append(f"{label}引用未知物件状态：{ref}")
                elif key == "conflict_refs" and ref not in valid_conflict_refs:
                    errors.append(f"{label}引用未知冲突：{ref}")
                elif key == "task_refs" and ref not in valid_task_refs:
                    errors.append(f"{label}引用未知任务：{ref}")
        if not any_target:
            errors.append(f"{label}没有任何长期存储落点")
        return any_target

    long_term_events = payload.get("long_term_events", [])
    event_runtime_refs = {"lore": set(), "foreshadows": set()}
    event_storage_refs = {
        "fact_refs": set(),
        "character_refs": set(),
        "lore_refs": set(),
        "foreshadow_refs": set(),
        "object_keys": set(),
        "conflict_refs": set(),
        "task_refs": set(),
    }
    if require_evidence:
        if not isinstance(long_term_events, list):
            errors.append("long_term_events必须为数组")
            long_term_events = []
        allowed_event_categories = {
            "commitment", "evidence", "ability_boundary", "task",
            "foreshadow", "key_object", "relationship", "other", "fact", "plot",
        }
        for index, item in enumerate(long_term_events, 1):
            label = f"long_term_events第{index}项"
            if not isinstance(item, dict):
                errors.append(f"{label}不是对象")
                continue
            if not str(item.get("event", "") or "").strip():
                errors.append(f"{label}事件为空")
            category = str(item.get("category", "") or "").strip()
            if category not in allowed_event_categories:
                errors.append(f"{label}category无效")
            if not _long_form_evidence_present(
                item.get("evidence_quote", item.get("evidence", "")), final_text
            ):
                errors.append(f"{label}缺少正文逐字证据")
            storage = item.get("storage", {})
            validate_storage(storage, label)
            if isinstance(storage, dict):
                for source_key, kind in (
                    ("fact_refs", "facts"),
                    ("character_refs", "characters"),
                    ("lore_refs", "lore"),
                    ("foreshadow_refs", "foreshadows"),
                    ("object_keys", "objects"),
                    ("conflict_refs", "conflicts"),
                    ("task_refs", "tasks"),
                ):
                    for value in storage.get(source_key, []) if isinstance(storage.get(source_key), list) else []:
                        ref = str(value or "").strip()
                        if not ref:
                            continue
                        if kind in {"characters", "lore", "foreshadows"}:
                            ref = _resolve_long_form_record_ref(project, kind, ref) or ref
                        elif kind == "objects":
                            ref = _compact_text(ref)
                        event_storage_refs[source_key].add(ref)
                for source_key, kind in (
                    ("lore_refs", "lore"),
                    ("foreshadow_refs", "foreshadows"),
                ):
                    for value in storage.get(source_key, []) if isinstance(storage.get(source_key), list) else []:
                        ref = str(value or "").strip()
                        if ref:
                            event_runtime_refs[kind].add(
                                _resolve_long_form_record_ref(project, kind, ref) or ref
                            )

    reconciliation = payload.get("state_reconciliation", {})
    if require_evidence:
        if not isinstance(reconciliation, dict):
            errors.append("state_reconciliation必须为对象")
            reconciliation = {}
        if reconciliation.get("checked") is not True:
            errors.append("state_reconciliation.checked必须为true")
        coverage_checks = reconciliation.get("coverage_checks", {})
        required_coverage_checks = (
            "named_character_actions",
            "state_changes",
            "evidence_and_unknowns",
            "mechanism_claims_match_body",
            "rules_and_boundaries",
            "foreshadow_and_ending",
        )
        if not isinstance(coverage_checks, dict):
            errors.append("state_reconciliation.coverage_checks必须为对象")
            coverage_checks = {}
        missing_coverage_checks = [
            key for key in required_coverage_checks
            if coverage_checks.get(key) is not True
        ]
        if missing_coverage_checks:
            errors.append(
                "state_reconciliation.coverage_checks未完成："
                + "、".join(missing_coverage_checks)
            )

        checked_sets = {}
        for key in (
            "fact_refs", "character_refs", "lore_refs", "foreshadow_refs",
            "object_keys", "conflict_refs", "task_refs",
        ):
            if key not in reconciliation:
                errors.append(f"state_reconciliation缺少{key}")
            values = reconciliation.get(key, [])
            if not isinstance(values, list):
                errors.append(f"state_reconciliation.{key}必须为数组")
                values = []
            checked_sets[key] = {str(value or "").strip() for value in values if str(value or "").strip()}
        unknown_checked_facts = checked_sets["fact_refs"] - (existing_fact_ids | temp_fact_keys)
        if unknown_checked_facts:
            errors.append("state_reconciliation.fact_refs引用未知事实：" + "、".join(sorted(unknown_checked_facts)[:8]))
        for key, kind in (
            ("character_refs", "characters"),
            ("lore_refs", "lore"),
            ("foreshadow_refs", "foreshadows"),
        ):
            unknown = sorted(ref for ref in checked_sets[key] if not valid_record_ref(kind, ref))
            if unknown:
                errors.append(f"state_reconciliation.{key}引用未知记录：" + "、".join(unknown[:8]))
        unknown_objects = sorted(
            ref for ref in checked_sets["object_keys"] if _compact_text(ref) not in valid_object_keys
        )
        if unknown_objects:
            errors.append("state_reconciliation.object_keys引用未知物件：" + "、".join(unknown_objects[:8]))
        unknown_conflicts = checked_sets["conflict_refs"] - valid_conflict_refs
        if unknown_conflicts:
            errors.append("state_reconciliation.conflict_refs引用未知冲突：" + "、".join(sorted(unknown_conflicts)[:8]))
        unknown_tasks = checked_sets["task_refs"] - valid_task_refs
        if unknown_tasks:
            errors.append("state_reconciliation.task_refs引用未知任务：" + "、".join(sorted(unknown_tasks)[:8]))
        relationship_values = reconciliation.get("relationship_refs", [])
        if "relationship_refs" not in reconciliation:
            errors.append("state_reconciliation缺少relationship_refs")
        if not isinstance(relationship_values, list):
            errors.append("state_reconciliation.relationship_refs必须为数组")
            relationship_values = []
        checked_relationships = set()
        for value in relationship_values:
            refs = value if isinstance(value, list) else str(value or "").split("|")
            refs = [str(ref or "").strip() for ref in refs if str(ref or "").strip()]
            if len(refs) < 2 or any(not valid_record_ref("characters", ref) for ref in refs):
                errors.append(f"state_reconciliation关系引用无效：{value}")
                continue
            checked_relationships.add("|".join(sorted(refs)))
        if not isinstance(reconciliation.get("resolved_contradictions", []), list):
            errors.append("state_reconciliation.resolved_contradictions必须为数组")

        required_fact_refs = {
            str(item.get("key" if str(item.get("operation", "") or "").lower() in {"add", "supersede"} else "id", "") or "").strip()
            for item in fact_updates if isinstance(item, dict)
        } - {""}
        required_character_refs = set()
        required_lore_refs = set()
        required_foreshadow_refs = set()
        for item in record_updates.get("characters", []) if isinstance(record_updates.get("characters"), list) else []:
            if isinstance(item, dict):
                operation = str(item.get("operation", "") or "").lower()
                required_character_refs.add(str(
                    item.get("key", "") if operation == "create"
                    else item.get("ref", item.get("id", ""))
                    or ""
                ).strip())
        for item in record_updates.get("lore", []) if isinstance(record_updates.get("lore"), list) else []:
            if isinstance(item, dict):
                operation = str(item.get("operation", "") or "").lower()
                required_lore_refs.add(str(
                    item.get("key", "") if operation == "create"
                    else item.get("ref", item.get("id", ""))
                    or ""
                ).strip())
        for item in payload.get("foreshadow_updates", []) if isinstance(payload.get("foreshadow_updates"), list) else []:
            if isinstance(item, dict):
                operation = str(item.get("operation", "") or "").lower()
                required_foreshadow_refs.add(str(
                    item.get("key", "") if operation == "create"
                    else item.get("ref", item.get("id", ""))
                    or ""
                ).strip())
        changed_runtime_refs = {
            "lore": {
                _resolve_long_form_record_ref(project, "lore", ref) or ref
                for ref in required_lore_refs
                if ref
            },
            "foreshadows": {
                _resolve_long_form_record_ref(project, "foreshadows", ref) or ref
                for ref in required_foreshadow_refs
                if ref
            },
        }
        outlined_lore_refs = _chapter_outline_named_lore_refs(
            project, chapter_index
        )
        required_runtime_refs = {
            "lore": event_runtime_refs["lore"] | outlined_lore_refs,
            "foreshadows": set(event_runtime_refs["foreshadows"]),
        }
        runtime_review = reconciliation.get("record_runtime_review", {})
        if any(required_runtime_refs.values()) and not isinstance(runtime_review, dict):
            errors.append("state_reconciliation.record_runtime_review必须为对象")
            runtime_review = {}
        elif not isinstance(runtime_review, dict):
            runtime_review = {}
        for kind, label in (("lore", "设定"), ("foreshadows", "伏笔")):
            reviewed_key = (
                "reviewed_lore_refs" if kind == "lore"
                else "reviewed_foreshadow_refs"
            )
            unchanged_key = (
                "unchanged_lore_refs" if kind == "lore"
                else "unchanged_foreshadow_refs"
            )
            reviewed_values = runtime_review.get(reviewed_key, [])
            unchanged_values = runtime_review.get(unchanged_key, [])
            if required_runtime_refs[kind] and not isinstance(reviewed_values, list):
                errors.append(f"record_runtime_review.{reviewed_key}必须为数组")
                reviewed_values = []
            if required_runtime_refs[kind] and not isinstance(unchanged_values, list):
                errors.append(f"record_runtime_review.{unchanged_key}必须为数组")
                unchanged_values = []
            reviewed = {
                _resolve_long_form_record_ref(project, kind, value) or str(value or "").strip()
                for value in reviewed_values if str(value or "").strip()
            } if isinstance(reviewed_values, list) else set()
            unchanged = {
                _resolve_long_form_record_ref(project, kind, value) or str(value or "").strip()
                for value in unchanged_values if str(value or "").strip()
            } if isinstance(unchanged_values, list) else set()
            missing_review = sorted(required_runtime_refs[kind] - reviewed)
            if missing_review:
                errors.append(
                    f"本章提纲或长期事件{label}运行态未复核："
                    + "、".join(missing_review[:8])
                )
            invalid_unchanged = sorted(unchanged - reviewed)
            if invalid_unchanged:
                errors.append(f"{label}运行态unchanged未进入reviewed：" + "、".join(invalid_unchanged[:8]))
            missing_outcome = sorted(
                reviewed - changed_runtime_refs[kind] - unchanged
            )
            if missing_outcome:
                errors.append(
                    f"{label}运行态复核没有更新或unchanged结论："
                    + "、".join(missing_outcome[:8])
                )
            for value in reviewed:
                if not valid_record_ref(kind, value):
                    errors.append(f"{label}运行态复核引用未知记录：{value}")
            checked_key = "lore_refs" if kind == "lore" else "foreshadow_refs"
            missing_checked = sorted(required_runtime_refs[kind] - {
                _resolve_long_form_record_ref(project, kind, value) or value
                for value in checked_sets.get(checked_key, set())
            })
            if missing_checked:
                errors.append(
                    f"state_reconciliation.{checked_key}遗漏提纲或长期事件引用："
                    + "、".join(missing_checked[:8])
                )
        required_character_refs.update(
            str(item.get("ref", item.get("character_id", "")) or "").strip()
            for item in state_patch.get("character_states", [])
            if isinstance(item, dict)
        )
        required_lore_refs.update(
            str(item.get("lore_ref", item.get("lore_id", "")) or "").strip()
            for item in state_patch.get("object_states", [])
            if isinstance(item, dict) and str(item.get("lore_ref", item.get("lore_id", "")) or "").strip()
        )
        required_relationships = {
            "|".join(sorted(str(ref or "").strip() for ref in item.get("refs", item.get("characters", [])) if str(ref or "").strip()))
            for item in state_patch.get("relationship_states", [])
            if isinstance(item, dict)
        }
        required_relationships.update(
            "|".join(sorted(
                str(ref or "").strip()
                for ref in (value if isinstance(value, list) else str(value or "").split("|"))
                if str(ref or "").strip()
            ))
            for value in state_retirements.get("relationship_refs", [])
            if value
        )
        required_relationships.discard("")
        required_object_keys = {
            str(item.get("key", item.get("name", "")) or "").strip()
            for item in state_patch.get("object_states", []) if isinstance(item, dict)
        }
        required_object_keys.update(
            str(value or "").strip()
            for value in state_retirements.get("object_keys", [])
            if str(value or "").strip()
        )
        required_conflict_refs = {
            str(item.get("id", "") or item.get("key", "") or "").strip()
            for item in state_patch.get("active_conflicts", []) if isinstance(item, dict)
        }
        required_conflict_refs.update(
            str(value or "").strip()
            for value in state_retirements.get("conflict_ids", [])
            if str(value or "").strip()
        )
        required_task_refs = {
            str(item.get("id", "") or item.get("key", "") or "").strip()
            for item in state_patch.get("unresolved_tasks", []) if isinstance(item, dict)
        }
        required_task_refs.update(
            str(value or "").strip()
            for value in state_retirements.get("task_ids", [])
            if str(value or "").strip()
        )
        required_character_refs.update(
            str(value or "").strip()
            for value in state_retirements.get("character_refs", [])
            if str(value or "").strip()
        )
        required_foreshadow_refs.discard("")
        required_character_refs.discard("")
        required_lore_refs.discard("")
        required_object_keys.discard("")
        required_conflict_refs.discard("")
        required_task_refs.discard("")
        required_event_refs = {
            "fact_refs": {
                str(item.get(
                    "key"
                    if str(item.get("operation", "") or "").strip().lower()
                    in {"add", "supersede"}
                    else "id",
                    "",
                ) or "").strip()
                for item in fact_updates
                if isinstance(item, dict)
                and str(item.get("operation", "") or "").strip().lower()
                not in {"", "keep"}
            },
            "lore_refs": set(changed_runtime_refs["lore"]),
            "foreshadow_refs": set(changed_runtime_refs["foreshadows"]),
            "object_keys": {
                _compact_text(value) for value in required_object_keys
                if _compact_text(value)
            },
            "conflict_refs": set(required_conflict_refs),
            "task_refs": set(required_task_refs),
        }
        for key, required in required_event_refs.items():
            required.discard("")
            missing = sorted(required - event_storage_refs.get(key, set()))
            if missing:
                errors.append(
                    f"long_term_events.storage.{key}遗漏本章长期更新："
                    + "、".join(missing[:10])
                )
        for key, required in (
            ("fact_refs", required_fact_refs),
            ("character_refs", required_character_refs),
            ("lore_refs", required_lore_refs),
            ("foreshadow_refs", required_foreshadow_refs),
            ("object_keys", required_object_keys),
            ("conflict_refs", required_conflict_refs),
            ("task_refs", required_task_refs),
        ):
            missing = sorted(required - checked_sets.get(key, set()))
            if missing:
                errors.append(f"state_reconciliation.{key}遗漏：" + "、".join(missing[:10]))
        missing_relationships = sorted(required_relationships - checked_relationships)
        if missing_relationships:
            errors.append("state_reconciliation.relationship_refs遗漏：" + "、".join(missing_relationships[:8]))

    stage_boundary = (chapter_index + 1) % 10 == 0
    archive = payload.get("stage_archive")
    if stage_boundary and not isinstance(archive, dict):
        errors.append("十章边界必须生成stage_archive")
    elif stage_boundary:
        if not str(archive.get("summary", "") or "").strip():
            errors.append("十章边界stage_archive.summary为空")
        if not str(archive.get("next_stage_entry", "") or "").strip():
            errors.append("十章边界stage_archive.next_stage_entry为空")
        for key in ("irreversible_facts", "relationship_changes", "unresolved_threads"):
            if not isinstance(archive.get(key), list):
                errors.append(f"十章边界stage_archive.{key}必须为数组")
    if not stage_boundary and archive not in (None, {}, ""):
        errors.append("非十章边界stage_archive必须为null")

    next_memory = payload.get("next_chapter_memory", {})
    if chapter_index + 1 < len(chapters):
        if not isinstance(next_memory, dict):
            errors.append("next_chapter_memory必须为对象")
        else:
            for key, kind in (
                ("character_refs", "characters"),
                ("lore_refs", "lore"),
                ("foreshadow_refs", "foreshadows"),
            ):
                values = next_memory.get(key, next_memory.get(key.replace("_refs", "_ids"), []))
                if not isinstance(values, list):
                    errors.append(f"next_chapter_memory.{key}必须为数组")
                    continue
                for ref in values:
                    if not _resolve_long_form_record_ref(project, kind, ref) and str(ref or "") not in temp_record_keys[kind]:
                        errors.append(f"下一章{kind}引用无效：{ref}")
            fact_refs = next_memory.get("fact_refs", next_memory.get("fact_ids", []))
            if not isinstance(fact_refs, list):
                errors.append("next_chapter_memory.fact_refs必须为数组")
            else:
                for ref in fact_refs:
                    if str(ref or "") not in existing_fact_ids | temp_fact_keys:
                        errors.append(f"下一章事实引用无效：{ref}")
            retired_object_compacts = {
                _compact_text(value)
                for value in state_retirements.get("object_keys", [])
                if str(value or "").strip()
            }
            retired_conflict_ids = {
                str(value or "").strip()
                for value in state_retirements.get("conflict_ids", [])
                if str(value or "").strip()
            }
            retired_task_ids = {
                str(value or "").strip()
                for value in state_retirements.get("task_ids", [])
                if str(value or "").strip()
            }
            next_state_fields = (
                (
                    "object_keys", "object_keys",
                    valid_object_keys - retired_object_compacts,
                    lambda value: _compact_text(value),
                    "物件",
                ),
                (
                    "conflict_refs", "conflict_ids",
                    valid_conflict_refs - retired_conflict_ids,
                    lambda value: str(value or "").strip(),
                    "冲突",
                ),
                (
                    "task_refs", "task_ids",
                    valid_task_refs - retired_task_ids,
                    lambda value: str(value or "").strip(),
                    "任务",
                ),
            )
            for input_key, legacy_key, valid_refs, normalize_ref, label in next_state_fields:
                values = next_memory.get(input_key, next_memory.get(legacy_key, []))
                if not isinstance(values, list):
                    errors.append(f"next_chapter_memory.{input_key}必须为数组")
                    continue
                for ref in values:
                    if normalize_ref(ref) not in valid_refs:
                        errors.append(f"下一章{label}引用无效：{ref}")
            archive_refs = next_memory.get(
                "stage_archive_refs", next_memory.get("stage_archive_ids", [])
            )
            if not isinstance(archive_refs, list):
                errors.append("next_chapter_memory.stage_archive_refs必须为数组")
            else:
                existing_archive_ids = {
                    str(item.get("id", "") or "").strip()
                    for item in memory.get("stage_archives", [])
                    if isinstance(item, dict) and str(item.get("id", "") or "").strip()
                }
                for ref in archive_refs:
                    ref_text = str(ref or "").strip()
                    if ref_text == "CURRENT_STAGE" and stage_boundary and isinstance(archive, dict):
                        continue
                    if ref_text not in existing_archive_ids:
                        errors.append(f"下一章阶段档案引用无效：{ref}")
    return errors


_LONG_FORM_MEMORY_PATCH_FIELDS = (
    "schema_version",
    "base_revision",
    "state_patch",
    "state_retirements",
    "state_lifecycle_review",
    "fact_updates",
    "fact_lifecycle_review",
    "long_term_events",
    "state_reconciliation",
    "state_delta",
    "current_chapter_character_refs",
    "stage_archive",
    "record_updates",
    "foreshadow_updates",
    "next_chapter_memory",
)


def _memory_repair_patch_targets(validation_errors):
    bundle_fields = []
    direct_memory_fields = []

    def add(target, value):
        if value not in target:
            target.append(value)

    for error in validation_errors or []:
        text = str(error or "")
        lowered = text.lower()
        if "logic_audit" in lowered or "逻辑审查" in text:
            add(bundle_fields, "logic_audit")
        if "实际提纲" in text:
            add(bundle_fields, "outline")
        if "本章摘要" in text:
            add(bundle_fields, "summary")
        if "关键事实" in text:
            add(bundle_fields, "key_facts")
        if "schema_version" in lowered:
            add(direct_memory_fields, "schema_version")
        if "base_revision" in lowered:
            add(direct_memory_fields, "base_revision")
        if "state_patch" in lowered or any(
            marker in text for marker in ("人物状态第", "关系状态第", "物品状态第", "冲突状态第", "任务状态第")
        ):
            add(direct_memory_fields, "state_patch")
        if "state_retirements" in lowered or text.startswith("退出"):
            add(direct_memory_fields, "state_retirements")
        if "state_lifecycle_review" in lowered or "状态生命周期复核" in text:
            add(direct_memory_fields, "state_lifecycle_review")
        if "fact_updates" in lowered:
            add(direct_memory_fields, "fact_updates")
        if "fact_lifecycle_review" in lowered or "事实生命周期复核" in text:
            add(direct_memory_fields, "fact_lifecycle_review")
        if "long_term_events" in lowered:
            add(direct_memory_fields, "long_term_events")
        if "state_reconciliation" in lowered:
            add(direct_memory_fields, "state_reconciliation")
        if "state_delta" in lowered:
            add(direct_memory_fields, "state_delta")
        if "current_chapter_character" in lowered:
            add(direct_memory_fields, "current_chapter_character_refs")
        if "stage_archive" in lowered:
            add(direct_memory_fields, "stage_archive")
        if "record_updates" in lowered or "characters更新" in text or "lore更新" in text:
            add(direct_memory_fields, "record_updates")
        if (
            "foreshadow_updates" in lowered
            or "foreshadows更新" in lowered
            or "伏笔更新" in text
        ):
            add(direct_memory_fields, "foreshadow_updates")
        if "next_chapter_memory" in lowered or text.startswith("下一章"):
            add(direct_memory_fields, "next_chapter_memory")
        if "运行态" in text or "提纲或长期事件" in text:
            add(direct_memory_fields, "record_updates")
            add(direct_memory_fields, "state_reconciliation")

    memory_fields = list(direct_memory_fields)

    dependency_fields = {
        "fact_updates": (
            "fact_lifecycle_review", "long_term_events", "state_reconciliation",
        ),
        "record_updates": ("long_term_events", "state_reconciliation"),
        "foreshadow_updates": ("long_term_events", "state_reconciliation"),
        "state_patch": ("state_lifecycle_review", "long_term_events", "state_reconciliation"),
        "state_retirements": ("state_lifecycle_review", "state_reconciliation"),
    }
    for field in tuple(memory_fields):
        for dependency in dependency_fields.get(field, ()):
            add(memory_fields, dependency)
    return {
        "bundle_fields": bundle_fields,
        "direct_memory_fields": direct_memory_fields,
        "memory_fields": memory_fields,
    }


def _merge_long_form_memory_repair_patch(memory_update, patch):
    merged = deepcopy(memory_update) if isinstance(memory_update, dict) else {}
    patch = patch if isinstance(patch, dict) else {}
    replacements = patch.get("replace", patch)
    if not isinstance(replacements, dict):
        return merged
    allowed = set(_LONG_FORM_MEMORY_PATCH_FIELDS)
    for key, value in replacements.items():
        if key in allowed:
            merged[key] = deepcopy(value)
    return merged


def _merge_long_form_memory_repair_full(memory_update, repaired_update, validation_errors):
    repaired_update = repaired_update if isinstance(repaired_update, dict) else {}
    targets = _memory_repair_patch_targets(validation_errors)
    direct_fields = targets.get("direct_memory_fields", [])
    if not direct_fields:
        return deepcopy(repaired_update)
    replacements = {
        key: deepcopy(repaired_update[key])
        for key in direct_fields
        if key in repaired_update
    }
    return _merge_long_form_memory_repair_patch(
        memory_update,
        {"replace": replacements},
    )


def _parse_memory_repair_result(value):
    def empty_result():
        return {
            "parsed": False,
            "repair_mode": "",
            "outline": "",
            "summary": "",
            "key_facts": "",
            "memory_update": {},
            "memory_patch": {},
            "logic_audit": {},
            "prose_review": {"checked": True, "issues": []},
            "repair_patches": [],
        }

    def is_placeholder(value):
        if not isinstance(value, str):
            return False
        text = value.strip()
        return (
            text in {"...", "…", "待填写"}
            or "返回该字段的完整替换值" in text
            or "返回完整修复值" in text
        )

    def candidate_score(data):
        if not isinstance(data, dict):
            return -1
        direct_memory_keys = {
            key for key in _LONG_FORM_MEMORY_PATCH_FIELDS
            if key in data
        }
        if not any(
            key in data
            for key in (
                "long_form_memory_patch", "memory_patch", "long_form_memory",
                "outline", "summary", "key_facts", "logic_audit", "replace",
            )
        ) and not direct_memory_keys:
            return -1
        score = 1
        patch = data.get("long_form_memory_patch", data.get("memory_patch", {}))
        if not patch and isinstance(data.get("replace"), dict):
            patch = {"replace": data["replace"]}
        if not patch and direct_memory_keys:
            patch = {
                "replace": {
                    key: data[key]
                    for key in direct_memory_keys
                }
            }
        if isinstance(patch, dict):
            replacements = patch.get("replace", patch)
            if isinstance(replacements, dict) and replacements:
                if any(is_placeholder(item) for item in replacements.values()):
                    return -1
                score += 20
                score += 100
                if all(isinstance(item, (dict, list)) for item in replacements.values()):
                    score += 10
        memory_update = data.get("long_form_memory", {})
        if isinstance(memory_update, dict) and memory_update:
            score += 80
        if any(str(data.get(key, "") or "").strip() for key in ("outline", "summary", "key_facts")):
            score += 20
        if isinstance(data.get("logic_audit"), dict) and data.get("logic_audit"):
            score += 20
        bundle_values = [
            data.get(key)
            for key in ("outline", "summary", "key_facts")
            if key in data
        ]
        if bundle_values and all(
            isinstance(item, str) and is_placeholder(item)
            for item in bundle_values
        ):
            return -1
        return score

    text = str(value or "").strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.IGNORECASE | re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    start = text.find("{")
    if start < 0:
        return empty_result()

    data = None
    try:
        data = json.loads(text[start:])
    except Exception:
        pass

    if not isinstance(data, dict):
        data, _locally_repaired = _load_json_with_trailing_delimiter_repair(text[start:])
    if not isinstance(data, dict):
        decoder = json.JSONDecoder()
        candidates = []
        cursor = start
        while cursor < len(text):
            root_start = text.find("{", cursor)
            if root_start < 0:
                break
            try:
                candidate, offset = decoder.raw_decode(text, root_start)
            except Exception:
                cursor = root_start + 1
                continue
            if isinstance(candidate, dict) and candidate not in candidates:
                candidates.append(candidate)
            cursor = max(root_start + 1, offset)
        if candidates:
            scored = [(candidate_score(item), item) for item in candidates]
            best_score, data = max(scored, key=lambda item: item[0])
            if best_score < 0:
                data = None

    if not isinstance(data, dict):
        data, _locally_repaired = _load_json_with_single_missing_quote_repair(text[start:])
    if not isinstance(data, dict):
        return empty_result()

    if candidate_score(data) < 0:
        return empty_result()
    if (
        isinstance(data.get("replace"), dict)
        and "long_form_memory_patch" not in data
        and "memory_patch" not in data
    ):
        data = {
            "long_form_memory_patch": {
                "replace": deepcopy(data["replace"]),
            }
        }
    elif (
        "long_form_memory_patch" not in data
        and "memory_patch" not in data
    ):
        direct_memory = {
            key: deepcopy(data[key])
            for key in _LONG_FORM_MEMORY_PATCH_FIELDS
            if key in data
        }
        if direct_memory:
            data = {
                key: deepcopy(data[key])
                for key in ("outline", "summary", "key_facts", "logic_audit")
                if key in data
            }
            data["long_form_memory_patch"] = {"replace": direct_memory}
    key_facts = data.get("key_facts", "")
    if isinstance(key_facts, list):
        key_facts = "\n".join(
            f"{index}. {str(item or '').strip()}"
            for index, item in enumerate(key_facts, 1) if str(item or "").strip()
        )
    outline = data.get("outline", "")
    if isinstance(outline, list):
        outline = "\n".join(
            f"{index}. {str(item or '').strip()}"
            for index, item in enumerate(outline, 1) if str(item or "").strip()
        )
    memory_update = data.get("long_form_memory", {})
    memory_patch = data.get("long_form_memory_patch", data.get("memory_patch", {}))
    logic_audit = data.get("logic_audit", {})
    prose_review = data.get("prose_review", {"checked": True, "issues": []})
    repair_patches = data.get("repair_patches", [])
    patch_replacements = (
        memory_patch.get("replace", memory_patch)
        if isinstance(memory_patch, dict) else {}
    )
    memory_patch_mode = isinstance(memory_patch, dict) and bool(patch_replacements)
    bundle_patch_mode = "long_form_memory" not in data and any(
        key in data for key in ("outline", "summary", "key_facts", "logic_audit")
    )
    patch_mode = memory_patch_mode or bundle_patch_mode
    bundle_content_present = any(
        str(data.get(key, "") or "").strip()
        for key in ("outline", "summary", "key_facts")
    ) or (isinstance(logic_audit, dict) and bool(logic_audit))
    return {
        "parsed": (
            patch_mode or bundle_content_present
            or (isinstance(memory_update, dict) and bool(memory_update))
        ),
        "repair_mode": "patch" if patch_mode else "full",
        "outline": str(outline or "").strip(),
        "summary": str(data.get("summary", "") or "").strip(),
        "key_facts": str(key_facts or "").strip(),
        "memory_update": deepcopy(memory_update) if isinstance(memory_update, dict) else {},
        "memory_patch": deepcopy(memory_patch) if isinstance(memory_patch, dict) else {},
        "logic_audit": deepcopy(logic_audit) if isinstance(logic_audit, dict) else {},
        "prose_review": deepcopy(prose_review) if isinstance(prose_review, dict) else {"checked": True, "issues": []},
        "repair_patches": deepcopy(repair_patches) if isinstance(repair_patches, list) else [],
    }


_CHAPTER_LOGIC_AUDIT_CATEGORIES = {
    "chronology",
    "causality",
    "character_state",
    "character_location",
    "object_state",
    "object_ownership",
    "spatial_state",
    "pronoun_reference",
    "knowledge_permission",
}


def _chapter_logic_audit_validation_errors(final_text, audit):
    """Validate quoted hard contradictions without judging story semantics locally."""
    body = str(final_text or "").strip()
    if not isinstance(audit, dict):
        return ["logic_audit必须为对象"]
    errors = []
    if audit.get("checked") is not True:
        errors.append("logic_audit.checked必须为true")
    issues = audit.get("issues", [])
    if not isinstance(issues, list):
        return errors + ["logic_audit.issues必须为数组"]
    if len(issues) > 3:
        errors.append("logic_audit.issues最多只能包含3项明确硬矛盾")
    for index, item in enumerate(issues[:3], 1):
        if not isinstance(item, dict):
            errors.append(f"logic_audit第{index}项必须为对象")
            continue
        severity = str(item.get("severity", "") or "").strip().lower()
        category = str(item.get("category", "") or "").strip().lower()
        earlier_quote = str(item.get("earlier_quote", "") or "").strip()
        later_quote = str(item.get("later_quote", "") or "").strip()
        explanation = str(item.get("explanation", "") or "").strip()
        if severity not in {"critical", "major"}:
            errors.append(f"logic_audit第{index}项severity必须为critical或major")
        if category not in _CHAPTER_LOGIC_AUDIT_CATEGORIES:
            errors.append(f"logic_audit第{index}项category无效")
        if len(_compact_text(earlier_quote)) < 4 or earlier_quote not in body:
            errors.append(f"logic_audit第{index}项earlier_quote不是正文中4字以上逐字原文")
        if len(_compact_text(later_quote)) < 4 or later_quote not in body:
            errors.append(f"logic_audit第{index}项later_quote不是正文中4字以上逐字原文")
        if len(_compact_text(explanation)) < 6:
            errors.append(f"logic_audit第{index}项缺少明确矛盾说明")
        if earlier_quote in body and later_quote in body:
            earlier_pos = body.find(earlier_quote)
            later_start = earlier_pos + (1 if earlier_quote == later_quote else 0)
            later_pos = body.find(later_quote, max(0, later_start))
            if earlier_pos < 0 or later_pos < earlier_pos:
                errors.append(f"logic_audit第{index}项前后证据顺序无效")
    return errors


def _chapter_logic_audit_blocking_issues(audit):
    if not isinstance(audit, dict) or audit.get("checked") is not True:
        return []
    return [
        deepcopy(item)
        for item in audit.get("issues", [])
        if isinstance(item, dict)
        and str(item.get("severity", "") or "").strip().lower() in {"critical", "major"}
    ][:3]


def _apply_chapter_prose_repair_patches(final_text, patches):
    """Apply only safe, model-authored local prose replacements.

    The model decides whether a passage is repetitive or mechanical. Local code
    only ensures that a suggested patch points to one small, unambiguous span of
    the current chapter before it is applied.
    """
    body = str(final_text or "").strip()
    patches = patches if isinstance(patches, list) else []
    if not patches:
        return body, []
    errors = []
    if len(patches) > 3:
        return body, ["正文局部修补最多只能包含3项"]
    replacements = []
    for index, patch in enumerate(patches, 1):
        if not isinstance(patch, dict):
            errors.append(f"正文局部修补第{index}项必须为对象")
            continue
        before = str(patch.get("before", "") or "").strip()
        after = str(patch.get("after", "") or "").strip()
        reason = str(patch.get("reason", "") or "").strip()
        if len(_compact_text(before)) < 8:
            errors.append(f"正文局部修补第{index}项before过短")
            continue
        if len(before) > 900:
            errors.append(f"正文局部修补第{index}项替换范围过大")
            continue
        if body.count(before) != 1:
            errors.append(f"正文局部修补第{index}项before必须在正文中逐字且唯一出现")
            continue
        if not after or after == before:
            errors.append(f"正文局部修补第{index}项没有有效替换内容")
            continue
        if len(after) > max(1600, len(before) * 3):
            errors.append(f"正文局部修补第{index}项替换范围过大")
            continue
        if len(_compact_text(reason)) < 4:
            errors.append(f"正文局部修补第{index}项缺少修补原因")
            continue
        if any(marker in before or marker in after for marker in ("```", "【审", "【修", "{\"", "\"patch")):
            errors.append(f"正文局部修补第{index}项混入了分析或结构化内容")
            continue
        start = body.find(before)
        replacements.append((start, start + len(before), after, index))
    ordered = sorted(replacements)
    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            errors.append(f"正文局部修补第{previous[3]}和第{current[3]}项范围重叠")
    if errors:
        return body, errors
    repaired = body
    for start, end, after, _index in sorted(replacements, reverse=True):
        repaired = repaired[:start] + after + repaired[end:]
    repaired = repaired.strip()
    if repaired == body:
        return body, ["正文局部修补没有产生变化"]
    return repaired, []


def _parse_chapter_logic_repair_result(value):
    text = str(value or "").strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.IGNORECASE | re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    start = text.find("{")
    if start < 0:
        return {"parsed": False, "patches": []}
    try:
        data, _offset = json.JSONDecoder().raw_decode(text[start:])
    except Exception:
        return {"parsed": False, "patches": []}
    if not isinstance(data, dict) or not isinstance(data.get("patches"), list):
        return {"parsed": False, "patches": []}
    return {"parsed": True, "patches": deepcopy(data.get("patches", []))}


def _apply_chapter_logic_repair_patches(final_text, issues, patches):
    """Apply model-authored exact replacements; local code makes no semantic decision."""
    body = str(final_text or "").strip()
    issues = issues if isinstance(issues, list) else []
    patches = patches if isinstance(patches, list) else []
    errors = []
    expected_indexes = set(range(1, len(issues) + 1))
    by_index = {}
    for position, patch in enumerate(patches, 1):
        if not isinstance(patch, dict):
            errors.append(f"局部修复第{position}项必须为对象")
            continue
        try:
            issue_index = int(patch.get("issue_index", 0) or 0)
        except Exception:
            issue_index = 0
        if issue_index not in expected_indexes or issue_index in by_index:
            errors.append(f"局部修复第{position}项issue_index无效或重复")
            continue
        by_index[issue_index] = patch
    missing = sorted(expected_indexes - set(by_index))
    if missing:
        errors.append("局部修复缺少问题编号：" + "、".join(str(value) for value in missing))

    replacements = []
    for issue_index in sorted(by_index):
        patch = by_index[issue_index]
        issue = issues[issue_index - 1] if issue_index <= len(issues) else {}
        original_quote = str(patch.get("original_quote", "") or "").strip()
        replacement_text = str(patch.get("replacement_text", "") or "").strip()
        if len(_compact_text(original_quote)) < 4:
            errors.append(f"局部修复问题{issue_index}的original_quote过短")
            continue
        if body.count(original_quote) != 1:
            errors.append(f"局部修复问题{issue_index}的original_quote必须在正文中逐字且唯一出现")
            continue
        earlier_quote = str(issue.get("earlier_quote", "") or "").strip()
        later_quote = str(issue.get("later_quote", "") or "").strip()
        if not any(
            evidence and (evidence in original_quote or original_quote in evidence)
            for evidence in (earlier_quote, later_quote)
        ):
            errors.append(f"局部修复问题{issue_index}没有覆盖审查证据")
            continue
        if replacement_text == original_quote:
            errors.append(f"局部修复问题{issue_index}没有实际修改")
            continue
        if len(replacement_text) > max(1200, len(original_quote) * 3):
            errors.append(f"局部修复问题{issue_index}替换内容过长，不符合最小修改")
            continue
        if any(marker in replacement_text for marker in ("```", "【逻辑", "【修复", "修改说明")):
            errors.append(f"局部修复问题{issue_index}混入了分析或格式说明")
            continue
        start = body.find(original_quote)
        replacements.append((start, start + len(original_quote), replacement_text, issue_index))

    ordered = sorted(replacements)
    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            errors.append(f"局部修复问题{previous[3]}和{current[3]}的替换范围重叠")
    if errors:
        return body, errors
    repaired = body
    for start, end, replacement_text, _issue_index in sorted(replacements, reverse=True):
        repaired = repaired[:start] + replacement_text + repaired[end:]
    if repaired == body:
        return body, ["局部修复没有改变正文"]
    return repaired.strip(), []


def _build_memory_repair_selection(
    project, chapter_index, memory_update=None, validation_errors=None
):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter = chapters[chapter_index] if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict) else {}
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
    selection = {
        "character_ids": [],
        "lore_ids": [],
        "foreshadow_ids": [],
        "fact_ids": [],
        "stage_archive_ids": [],
        "object_keys": [],
        "conflict_ids": [],
        "task_ids": [],
        "_restrict_records": True,
        "_restrict_facts": True,
        "_restrict_archives": True,
        "_restrict_state": True,
        "_compact_facts": True,
        "_compact_index_facts": True,
    }

    def append_unique(key, value):
        value = str(value or "").strip()
        if value and value not in selection[key]:
            selection[key].append(value)

    def add_record_ref(kind, ref):
        item_id = _resolve_long_form_record_ref(project, kind, ref)
        output_key = {
            "characters": "character_ids",
            "lore": "lore_ids",
            "foreshadows": "foreshadow_ids",
        }[kind]
        append_unique(output_key, item_id)

    current_selection = chapter.get("memory_selection", {})
    current_selection = current_selection if isinstance(current_selection, dict) else {}
    for key in (
        "character_ids", "lore_ids", "foreshadow_ids", "fact_ids", "stage_archive_ids",
        "object_keys", "conflict_ids", "task_ids",
    ):
        for value in current_selection.get(key, []) if isinstance(current_selection.get(key), list) else []:
            append_unique(key, value)
    for value in chapter.get("actual_linked_character_ids", []) if isinstance(chapter.get("actual_linked_character_ids"), list) else []:
        append_unique("character_ids", value)
    linked_names = set(_normalize_name_list(chapter.get("linked_characters", [])))
    for item in project.get("characters", []) if isinstance(project.get("characters"), list) else []:
        if isinstance(item, dict) and str(item.get("name", "") or "").strip() in linked_names:
            append_unique("character_ids", item.get("id", ""))

    payload = _normalize_long_form_update_payload(project, chapter_index, memory_update or {})
    stage_boundary = (chapter_index + 1) % 10 == 0
    state_patch = payload.get("state_patch", {}) if isinstance(payload.get("state_patch"), dict) else {}
    retirements = payload.get("state_retirements", {}) if isinstance(payload.get("state_retirements"), dict) else {}
    for item in state_patch.get("character_states", []) if isinstance(state_patch.get("character_states"), list) else []:
        if isinstance(item, dict):
            add_record_ref("characters", item.get("ref", item.get("character_id", "")))
    for item in state_patch.get("relationship_states", []) if isinstance(state_patch.get("relationship_states"), list) else []:
        if isinstance(item, dict):
            for ref in item.get("refs", item.get("characters", [])) if isinstance(item.get("refs", item.get("characters", [])), list) else []:
                add_record_ref("characters", ref)
    for item in state_patch.get("object_states", []) if isinstance(state_patch.get("object_states"), list) else []:
        if isinstance(item, dict):
            add_record_ref("lore", item.get("lore_ref", item.get("lore_id", "")))
            append_unique("object_keys", item.get("key", item.get("name", "")))
    for item in state_patch.get("active_conflicts", []) if isinstance(state_patch.get("active_conflicts"), list) else []:
        if isinstance(item, dict):
            append_unique("conflict_ids", item.get("id", item.get("key", "")))
    for item in state_patch.get("unresolved_tasks", []) if isinstance(state_patch.get("unresolved_tasks"), list) else []:
        if isinstance(item, dict):
            append_unique("task_ids", item.get("id", item.get("key", "")))
    for ref in retirements.get("character_refs", []) if isinstance(retirements.get("character_refs"), list) else []:
        add_record_ref("characters", ref)
    for value in retirements.get("relationship_refs", []) if isinstance(retirements.get("relationship_refs"), list) else []:
        refs = value if isinstance(value, list) else str(value or "").split("|")
        for ref in refs:
            add_record_ref("characters", ref)
    for value in retirements.get("object_keys", []) if isinstance(retirements.get("object_keys"), list) else []:
        append_unique("object_keys", value)
    for value in retirements.get("conflict_ids", []) if isinstance(retirements.get("conflict_ids"), list) else []:
        append_unique("conflict_ids", value)
    for value in retirements.get("task_ids", []) if isinstance(retirements.get("task_ids"), list) else []:
        append_unique("task_ids", value)

    record_updates = payload.get("record_updates", {}) if isinstance(payload.get("record_updates"), dict) else {}
    for kind in ("characters", "lore"):
        for item in record_updates.get(kind, []) if isinstance(record_updates.get(kind), list) else []:
            if isinstance(item, dict):
                add_record_ref(kind, item.get("ref", item.get("id", "")))
    for item in payload.get("foreshadow_updates", []) if isinstance(payload.get("foreshadow_updates"), list) else []:
        if isinstance(item, dict):
            add_record_ref("foreshadows", item.get("ref", item.get("id", "")))
    for item in payload.get("fact_updates", []) if isinstance(payload.get("fact_updates"), list) else []:
        if isinstance(item, dict):
            append_unique("fact_ids", item.get("id", ""))
    lifecycle_review = payload.get("fact_lifecycle_review", {})
    if isinstance(lifecycle_review, dict) and not stage_boundary:
        for ref in lifecycle_review.get("reviewed_refs", []) if isinstance(lifecycle_review.get("reviewed_refs"), list) else []:
            append_unique("fact_ids", ref)
    state_lifecycle_review = payload.get("state_lifecycle_review", {})
    if isinstance(state_lifecycle_review, dict) and not stage_boundary:
        for source_key, output_key in (
            ("reviewed_object_keys", "object_keys"),
            ("reviewed_conflict_refs", "conflict_ids"),
            ("reviewed_task_refs", "task_ids"),
        ):
            for ref in state_lifecycle_review.get(source_key, []) if isinstance(state_lifecycle_review.get(source_key), list) else []:
                append_unique(output_key, ref)

    next_memory = payload.get("next_chapter_memory", {}) if isinstance(payload.get("next_chapter_memory"), dict) else {}
    for key, kind in (
        ("character_refs", "characters"),
        ("lore_refs", "lore"),
        ("foreshadow_refs", "foreshadows"),
    ):
        for ref in next_memory.get(key, []) if isinstance(next_memory.get(key), list) else []:
            add_record_ref(kind, ref)
    for ref in next_memory.get("fact_refs", []) if isinstance(next_memory.get("fact_refs"), list) else []:
        append_unique("fact_ids", ref)
    for ref in next_memory.get("stage_archive_refs", []) if isinstance(next_memory.get("stage_archive_refs"), list) else []:
        if str(ref or "").strip() != "CURRENT_STAGE":
            append_unique("stage_archive_ids", ref)
    for ref in next_memory.get("object_keys", []) if isinstance(next_memory.get("object_keys"), list) else []:
        append_unique("object_keys", ref)
    for ref in next_memory.get("conflict_refs", next_memory.get("conflict_ids", [])) if isinstance(next_memory.get("conflict_refs", next_memory.get("conflict_ids", [])), list) else []:
        append_unique("conflict_ids", ref)
    for ref in next_memory.get("task_refs", next_memory.get("task_ids", [])) if isinstance(next_memory.get("task_refs", next_memory.get("task_ids", [])), list) else []:
        append_unique("task_ids", ref)

    for event in payload.get("long_term_events", []) if isinstance(payload.get("long_term_events"), list) else []:
        if not isinstance(event, dict) or not isinstance(event.get("storage"), dict):
            continue
        storage = event["storage"]
        for key, kind in (
            ("character_refs", "characters"),
            ("lore_refs", "lore"),
            ("foreshadow_refs", "foreshadows"),
        ):
            for ref in storage.get(key, []) if isinstance(storage.get(key), list) else []:
                add_record_ref(kind, ref)
        for ref in storage.get("fact_refs", []) if isinstance(storage.get("fact_refs"), list) else []:
            append_unique("fact_ids", ref)
        for ref in storage.get("object_keys", []) if isinstance(storage.get("object_keys"), list) else []:
            append_unique("object_keys", ref)
        for ref in storage.get("conflict_refs", []) if isinstance(storage.get("conflict_refs"), list) else []:
            append_unique("conflict_ids", ref)
        for ref in storage.get("task_refs", []) if isinstance(storage.get("task_refs"), list) else []:
            append_unique("task_ids", ref)

    reconciliation = payload.get("state_reconciliation", {})
    if isinstance(reconciliation, dict):
        for key, kind in (
            ("character_refs", "characters"),
            ("lore_refs", "lore"),
            ("foreshadow_refs", "foreshadows"),
        ):
            for ref in reconciliation.get(key, []) if isinstance(reconciliation.get(key), list) else []:
                add_record_ref(kind, ref)
        for value in reconciliation.get("relationship_refs", []) if isinstance(reconciliation.get("relationship_refs"), list) else []:
            refs = value if isinstance(value, list) else str(value or "").split("|")
            for ref in refs:
                add_record_ref("characters", ref)
        for ref in reconciliation.get("fact_refs", []) if isinstance(reconciliation.get("fact_refs"), list) else []:
            append_unique("fact_ids", ref)
        for ref in reconciliation.get("object_keys", []) if isinstance(reconciliation.get("object_keys"), list) else []:
            append_unique("object_keys", ref)
        for ref in reconciliation.get("conflict_refs", []) if isinstance(reconciliation.get("conflict_refs"), list) else []:
            append_unique("conflict_ids", ref)
        for ref in reconciliation.get("task_refs", []) if isinstance(reconciliation.get("task_refs"), list) else []:
            append_unique("task_ids", ref)

    error_text = "\n".join(str(item or "") for item in validation_errors or [])
    for item_id in re.findall(r"AF-\d+", error_text, flags=re.IGNORECASE):
        append_unique("fact_ids", item_id.upper())
    for item_id in re.findall(r"CF-\d+", error_text, flags=re.IGNORECASE):
        append_unique("conflict_ids", item_id.upper())
    for item_id in re.findall(r"TASK-\d+", error_text, flags=re.IGNORECASE):
        append_unique("task_ids", item_id.upper())
    for kind, pattern in (("characters", r"\bC\d{3}\b"), ("lore", r"\bL\d{3}\b"), ("foreshadows", r"\bF\d{3}\b")):
        for ref in re.findall(pattern, error_text, flags=re.IGNORECASE):
            add_record_ref(kind, ref.upper())

    snapshot = memory.get("state_snapshot", {})
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    selected_character_ids = set(selection["character_ids"])
    for item in snapshot.get("relationship_states", []) if isinstance(snapshot.get("relationship_states"), list) else []:
        if not isinstance(item, dict):
            continue
        relationship_ids = {
            str(value or "").strip() for value in item.get("characters", [])
            if str(value or "").strip()
        }
        if selected_character_ids.intersection(relationship_ids):
            for item_id in relationship_ids:
                append_unique("character_ids", item_id)

    active_facts = [item for item in memory.get("active_facts", []) if isinstance(item, dict)]
    if not stage_boundary:
        recent_floor = max(1, chapter_index - 4)
        for item in active_facts:
            latest_index = max(
                int(item.get("updated_chapter_index", 0) or 0),
                int(item.get("evidence_chapter_index", 0) or 0),
                int(item.get("source_chapter_index", 0) or 0),
            )
            if latest_index >= recent_floor:
                append_unique("fact_ids", item.get("id", ""))
        for item in active_facts[-24:]:
            append_unique("fact_ids", item.get("id", ""))
    for item in memory.get("stage_archives", [])[-2:]:
        if isinstance(item, dict):
            append_unique("stage_archive_ids", item.get("id", ""))
    return selection


def _canonical_relationship_ref(value):
    if isinstance(value, list):
        refs = [str(item or "").strip() for item in value if str(item or "").strip()]
    else:
        refs = [
            item.strip()
            for item in re.split(r"[|+]", str(value or ""))
            if item.strip()
        ]
    return "|".join(sorted(dict.fromkeys(refs))) if len(set(refs)) >= 2 else ""


def _memory_repair_reference_manifest(project, chapter_index, memory_update):
    project = project if isinstance(project, dict) else {}
    payload = _normalize_long_form_update_payload(project, chapter_index, memory_update)
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter = (
        chapters[chapter_index]
        if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict)
        else {}
    )
    existing_fact_records = {
        str(item.get("id", "") or "").strip(): item
        for item in memory.get("active_facts", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    fact_updates = payload.get("fact_updates", [])
    fact_updates = fact_updates if isinstance(fact_updates, list) else []
    temp_fact_keys = sorted({
        str(item.get("key", "") or "").strip()
        for item in fact_updates
        if isinstance(item, dict)
        and str(item.get("operation", "") or "").strip().lower() in {"add", "supersede"}
        and str(item.get("key", "") or "").strip()
    })
    touched_existing_fact_ids = {
        str(item.get("id", "") or "").strip()
        for item in fact_updates
        if isinstance(item, dict)
        and str(item.get("operation", "") or "").strip().lower() != "add"
        and str(item.get("id", "") or "").strip() in existing_fact_records
    }
    chapter_selection = chapter.get("memory_selection", {})
    chapter_selection = chapter_selection if isinstance(chapter_selection, dict) else {}
    selected_fact_ids = {
        str(value or "").strip()
        for value in chapter_selection.get("fact_ids", [])
        if str(value or "").strip() in existing_fact_records
    }
    required_review_refs = selected_fact_ids | touched_existing_fact_ids
    review_fact_records = [
        {
            "id": item_id,
            "scope": str(existing_fact_records[item_id].get("scope", "") or ""),
            "fact": str(existing_fact_records[item_id].get("fact", "") or ""),
        }
        for item_id in sorted(required_review_refs)
    ]

    state_patch = payload.get("state_patch", {})
    state_patch = state_patch if isinstance(state_patch, dict) else {}
    retirements = payload.get("state_retirements", {})
    retirements = retirements if isinstance(retirements, dict) else {}
    record_updates = payload.get("record_updates", {})
    record_updates = record_updates if isinstance(record_updates, dict) else {}
    existing_state_refs = _long_form_existing_state_refs(project, memory)
    existing_object_keys = existing_state_refs["object_key_by_compact"]
    selected_object_values = chapter_selection.get("object_keys", [])
    selected_object_values = selected_object_values if isinstance(selected_object_values, list) else []
    selected_conflict_values = chapter_selection.get("conflict_ids", [])
    selected_conflict_values = selected_conflict_values if isinstance(selected_conflict_values, list) else []
    selected_task_values = chapter_selection.get("task_ids", [])
    selected_task_values = selected_task_values if isinstance(selected_task_values, list) else []
    required_state_review = {
        "object_keys": {
            existing_object_keys[_compact_text(value)]
            for value in selected_object_values
            if _compact_text(value) in existing_object_keys
        },
        "conflict_refs": {
            str(value or "").strip()
            for value in selected_conflict_values
            if str(value or "").strip() in existing_state_refs["conflict_ids"]
        },
        "task_refs": {
            str(value or "").strip()
            for value in selected_task_values
            if str(value or "").strip() in existing_state_refs["task_ids"]
        },
    }
    required_state_review["object_keys"].update(
        existing_object_keys[_compact_text(value)]
        for value in retirements.get("object_keys", [])
        if _compact_text(value) in existing_object_keys
    )
    required_state_review["conflict_refs"].update(
        str(value or "").strip()
        for value in retirements.get("conflict_ids", [])
        if str(value or "").strip() in existing_state_refs["conflict_ids"]
    )
    required_state_review["task_refs"].update(
        str(value or "").strip()
        for value in retirements.get("task_ids", [])
        if str(value or "").strip() in existing_state_refs["task_ids"]
    )
    for item in state_patch.get("object_states", []) if isinstance(state_patch.get("object_states"), list) else []:
        compact = _compact_text(item.get("key", item.get("name", ""))) if isinstance(item, dict) else ""
        if compact in existing_object_keys:
            required_state_review["object_keys"].add(existing_object_keys[compact])
    required_state_review["conflict_refs"].update(
        str(item.get("id", "") or "").strip()
        for item in state_patch.get("active_conflicts", [])
        if isinstance(item, dict)
        and str(item.get("id", "") or "").strip() in existing_state_refs["conflict_ids"]
    )
    required_state_review["task_refs"].update(
        str(item.get("id", "") or "").strip()
        for item in state_patch.get("unresolved_tasks", [])
        if isinstance(item, dict)
        and str(item.get("id", "") or "").strip() in existing_state_refs["task_ids"]
    )

    required = {
        "fact_refs": {
            str(item.get(
                "key" if str(item.get("operation", "") or "").strip().lower() in {"add", "supersede"} else "id",
                "",
            ) or "").strip()
            for item in fact_updates if isinstance(item, dict)
        },
        "character_refs": set(),
        "lore_refs": set(),
        "foreshadow_refs": set(),
        "relationship_refs": set(),
        "object_keys": set(),
        "conflict_refs": set(),
        "task_refs": set(),
    }

    def updated_record_ref(item):
        operation = str(item.get("operation", "") or "").strip().lower()
        return str(
            item.get("key", "") if operation == "create"
            else item.get("ref", item.get("id", ""))
            or ""
        ).strip()

    outlined_lore_ids = _chapter_outline_named_lore_refs(project, chapter_index)
    lore_aliases = _long_form_record_reference_maps(project).get("lore", {}).get(
        "id_to_alias", {}
    )
    outlined_lore_refs = {
        lore_aliases.get(item_id, item_id) for item_id in outlined_lore_ids
    }
    required["lore_refs"].update(outlined_lore_refs)

    for item in record_updates.get("characters", []) if isinstance(record_updates.get("characters"), list) else []:
        if isinstance(item, dict):
            required["character_refs"].add(updated_record_ref(item))
    for item in record_updates.get("lore", []) if isinstance(record_updates.get("lore"), list) else []:
        if isinstance(item, dict):
            required["lore_refs"].add(updated_record_ref(item))
    for item in payload.get("foreshadow_updates", []) if isinstance(payload.get("foreshadow_updates"), list) else []:
        if isinstance(item, dict):
            required["foreshadow_refs"].add(updated_record_ref(item))
    required["character_refs"].update(
        str(item.get("ref", item.get("character_id", "")) or "").strip()
        for item in state_patch.get("character_states", [])
        if isinstance(item, dict)
    )
    required["character_refs"].update(
        str(value or "").strip()
        for value in retirements.get("character_refs", [])
        if str(value or "").strip()
    )
    required["lore_refs"].update(
        str(item.get("lore_ref", item.get("lore_id", "")) or "").strip()
        for item in state_patch.get("object_states", [])
        if isinstance(item, dict)
        and str(item.get("lore_ref", item.get("lore_id", "")) or "").strip()
    )
    required["relationship_refs"].update(
        _canonical_relationship_ref(item.get("refs", item.get("characters", [])))
        for item in state_patch.get("relationship_states", [])
        if isinstance(item, dict)
    )
    required["relationship_refs"].update(
        _canonical_relationship_ref(value)
        for value in retirements.get("relationship_refs", [])
        if value
    )
    required["object_keys"].update(
        str(item.get("key", item.get("name", "")) or "").strip()
        for item in state_patch.get("object_states", []) if isinstance(item, dict)
    )
    required["object_keys"].update(
        str(value or "").strip()
        for value in retirements.get("object_keys", [])
        if str(value or "").strip()
    )
    required["conflict_refs"].update(
        str(item.get("id", "") or item.get("key", "") or "").strip()
        for item in state_patch.get("active_conflicts", []) if isinstance(item, dict)
    )
    required["conflict_refs"].update(
        str(value or "").strip()
        for value in retirements.get("conflict_ids", [])
        if str(value or "").strip()
    )
    required["task_refs"].update(
        str(item.get("id", "") or item.get("key", "") or "").strip()
        for item in state_patch.get("unresolved_tasks", []) if isinstance(item, dict)
    )
    required["task_refs"].update(
        str(value or "").strip()
        for value in retirements.get("task_ids", [])
        if str(value or "").strip()
    )
    for values in required.values():
        values.discard("")

    snapshot = memory.get("state_snapshot", {})
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    conflict_records = {
        str(item.get("id", "") or "").strip(): {
            "id": str(item.get("id", "") or "").strip(),
            "conflict": str(item.get("conflict", "") or "").strip(),
        }
        for item in snapshot.get("active_conflicts", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    task_records = {
        str(item.get("id", "") or "").strip(): {
            "id": str(item.get("id", "") or "").strip(),
            "task": str(item.get("task", "") or "").strip(),
        }
        for item in snapshot.get("unresolved_tasks", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }

    return {
        "fact_lifecycle_review": {
            "scope": LONG_FORM_STAGE_REVIEW_SCOPE if (chapter_index + 1) % 10 == 0 else "current_chapter",
            "required_existing_refs": sorted(required_review_refs),
            "new_fact_keys_forbidden_here": temp_fact_keys,
            "required_fact_records": review_fact_records,
        },
        "state_lifecycle_review": {
            "scope": LONG_FORM_STAGE_REVIEW_SCOPE if (chapter_index + 1) % 10 == 0 else "current_chapter",
            "required_object_keys": sorted(required_state_review["object_keys"]),
            "required_conflict_refs": sorted(required_state_review["conflict_refs"]),
            "required_task_refs": sorted(required_state_review["task_refs"]),
            "required_conflict_records": [
                conflict_records[item_id]
                for item_id in sorted(required_state_review["conflict_refs"])
                if item_id in conflict_records
            ],
            "required_task_records": [
                task_records[item_id]
                for item_id in sorted(required_state_review["task_refs"])
                if item_id in task_records
            ],
            "new_NCF_NTASK_keys_forbidden_here": True,
        },
        "state_reconciliation_required_refs": {
            key: sorted(values) for key, values in required.items()
        },
        "record_runtime_review": {
            "required_outline_lore_refs": sorted(outlined_lore_refs),
        },
        "temporary_refs": {
            "fact_refs": temp_fact_keys,
            "character_refs": sorted({
                updated_record_ref(item)
                for item in record_updates.get("characters", [])
                if isinstance(item, dict)
                and str(item.get("operation", "") or "").strip().lower() == "create"
            }),
            "lore_refs": sorted({
                updated_record_ref(item)
                for item in record_updates.get("lore", [])
                if isinstance(item, dict)
                and str(item.get("operation", "") or "").strip().lower() == "create"
            }),
            "foreshadow_refs": sorted({
                updated_record_ref(item)
                for item in payload.get("foreshadow_updates", [])
                if isinstance(item, dict)
                and str(item.get("operation", "") or "").strip().lower() == "create"
            }),
        },
        "boundary_catalog_integrity": _long_form_catalog_summary(
            _long_form_active_catalog(project, memory)
        ),
        "relationship_ref_format": "使用竖线并按引用排序，例如C001|C002；不得使用加号",
    }


def _compact_memory_repair_update_for_context(
    project,
    chapter_index,
    memory_update,
    manifest=None,
):
    payload = deepcopy(memory_update) if isinstance(memory_update, dict) else {}
    if (chapter_index + 1) % 10 != 0:
        return payload
    manifest = manifest if isinstance(manifest, dict) else _memory_repair_reference_manifest(
        project, chapter_index, payload
    )
    fact_rules = manifest.get("fact_lifecycle_review", {})
    fact_rules = fact_rules if isinstance(fact_rules, dict) else {}
    fact_review = payload.get("fact_lifecycle_review", {})
    if isinstance(fact_review, dict):
        allowed = set(fact_rules.get("required_existing_refs", []))
        fact_review["reviewed_refs"] = [
            str(value or "").strip()
            for value in fact_review.get("reviewed_refs", [])
            if str(value or "").strip() in allowed
        ] if isinstance(fact_review.get("reviewed_refs"), list) else []
    state_rules = manifest.get("state_lifecycle_review", {})
    state_rules = state_rules if isinstance(state_rules, dict) else {}
    state_review = payload.get("state_lifecycle_review", {})
    if isinstance(state_review, dict):
        for field, required_field, normalizer in (
            ("reviewed_object_keys", "required_object_keys", _compact_text),
            ("reviewed_conflict_refs", "required_conflict_refs", lambda value: str(value or "").strip()),
            ("reviewed_task_refs", "required_task_refs", lambda value: str(value or "").strip()),
        ):
            required_values = state_rules.get(required_field, [])
            required = {
                normalizer(value) for value in required_values if normalizer(value)
            }
            values = state_review.get(field, [])
            state_review[field] = [
                str(value or "").strip()
                for value in values
                if normalizer(value) in required
            ] if isinstance(values, list) else []
    return payload


def _assemble_bounded_long_form_context(
    source_sections,
    output_requirements,
    limit=LONG_FORM_CONTEXT_SOFT_LIMIT,
):
    hard_limit = max(1000, min(int(limit or 0), NOVEL_AI_CONTEXT_LIMIT))
    requirements = str(output_requirements or "").strip()
    if len(requirements) > hard_limit // 2:
        requirements = _clip_context_text(
            requirements,
            hard_limit // 2,
            preserve_lines=True,
        )
    source_budget = max(0, hard_limit - len(requirements) - 2)
    blocks = []
    used = 0
    for title, content, section_limit, keep_tail in source_sections:
        title = str(title or "").strip()
        if not title:
            continue
        separator_length = 2 if blocks else 0
        remaining = source_budget - used - separator_length
        prefix = f"【{title}】\n"
        if remaining <= len(prefix):
            break
        content_budget = min(max(0, int(section_limit or 0)), remaining - len(prefix))
        clipped = _clip_context_text(
            content,
            content_budget,
            keep_tail=bool(keep_tail),
            preserve_lines=True,
        ) or "暂无"
        block = prefix + clipped
        if len(block) > remaining:
            block = prefix + _clip_context_text(
                clipped,
                max(0, remaining - len(prefix)),
                keep_tail=bool(keep_tail),
                preserve_lines=True,
            )
        if len(block) > remaining:
            break
        blocks.append(block)
        used += separator_length + len(block)
    parts = blocks + ([requirements] if requirements else [])
    context = "\n\n".join(part for part in parts if part)
    if len(context) > hard_limit:
        raise ValueError("长篇上下文组装超过软上限")
    return context


def _build_long_form_memory_patch_context(
    project,
    chapter_index,
    final_text,
    outline,
    summary,
    key_facts,
    logic_audit,
    memory_update,
    validation_errors,
):
    targets = _memory_repair_patch_targets(validation_errors)
    if not isinstance(memory_update, dict) or not memory_update:
        return ""
    if not targets["bundle_fields"] and not targets["memory_fields"]:
        return ""
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter = chapters[chapter_index] if 0 <= chapter_index < len(chapters) else {}
    next_chapter = chapters[chapter_index + 1] if chapter_index + 1 < len(chapters) else {}
    bundle_values = {
        "outline": outline,
        "summary": summary,
        "key_facts": key_facts,
        "logic_audit": deepcopy(logic_audit) if isinstance(logic_audit, dict) else {},
    }
    original_bundle = {
        key: deepcopy(bundle_values.get(key, ""))
        for key in targets["bundle_fields"]
    }
    manifest = (
        _memory_repair_reference_manifest(project, chapter_index, memory_update)
        if targets["memory_fields"] else {}
    )
    compact_memory_update = (
        _compact_memory_repair_update_for_context(
            project,
            chapter_index,
            memory_update,
            manifest=manifest,
        )
        if targets["memory_fields"] else {}
    )
    original_memory = {
        key: deepcopy(compact_memory_update.get(key))
        for key in targets["memory_fields"]
        if key in compact_memory_update
    }
    requirements = (
        "【状态增量修复补丁】\n"
        "只修复列出的错误字段，不得重写正文，不得重写或复述整份长篇记忆。"
        f"正文外字段只允许修复：{json.dumps(targets['bundle_fields'], ensure_ascii=False)}。"
        f"长篇记忆只允许完整替换这些顶层字段：{json.dumps(targets['memory_fields'], ensure_ascii=False)}。"
        "replace中的每个值必须是该顶层字段的完整新值，不是局部子字段；未列出的原字段由程序原样保留。"
        "不得通过清空数组、删除长期事件或删除状态更新来逃避校验；必须依据错误清单和机械引用清单补齐。"
        "fact_lifecycle_review.reviewed_refs只能使用已有AF-ID，NF临时key只能用于其他允许临时引用的分区。"
        "state_lifecycle_review三组reviewed数组只能使用调用前已有的物件键、CF-ID和TASK-ID，"
        "不得把本次新增的NCF/NTASK临时key写入生命周期复核。"
        "state_reconciliation.relationship_refs必须使用C001|C002格式并按引用排序。"
        "新增冲突或任务不得猜测CF-ID/TASK-ID；id留空并分别填写NCF1/NTASK1临时key，"
        "必须放入state_patch.active_conflicts或state_patch.unresolved_tasks，再在long_term_events和state_reconciliation中引用同一个临时key；"
        "禁止把conflicts或tasks放在long_form_memory顶层。"
        "record_updates只允许create/update；本章没有动态变化的已有人物或设定不要写入record_updates，"
        "若正文明确给已有姓名未明或临时称谓人物补出正式姓名，必须使用原人物引用和name更新卡片名称，保留原ID、运行态和旧称；"
        "只在state_reconciliation.record_runtime_review中列为unchanged。"
        "修复时必须原样保留原结果中已有的NF/NL/NCF/NTASK/NT临时key，不得为了修复字段而重命名、另造同义临时key。"
        "fact_updates使用retire或supersede时必须保留被处理的已有AF-ID，逐字复制原scope和previous_fact，"
        "同时填写非空reason和正文逐字证据；supersede还要填写新的NF临时key和同scope新fact，该NF必须同步进入long_term_events.storage.fact_refs和"
        "state_reconciliation.fact_refs。"
        "涉及evidence_quote时必须从最终正文逐字复制连续原文。"
        "长篇记忆修复结果的固定结构是：顶层使用long_form_memory_patch对象，其下使用replace对象；"
        "每个需要修复的长篇记忆顶层字段只能作为replace的键出现，不能把state_reconciliation、next_chapter_memory或其他长篇字段直接放在顶层。"
        "机械引用清单是引用分类的唯一依据：只有清单中的required_object_keys才能进入object_keys；"
        "lore_refs只能填写设定记录的编号或别名，object_keys只能填写物件状态目录中的真实键；"
        "设定ID、伏笔ID或设定名称对应的记录即使名称像物件，也只能进入对应的lore_refs或foreshadow_refs，不能进入object_keys。"
        "严格只输出一个合法JSON对象，不输出Markdown、代码块、解释、占位符或额外字段；"
        "每个需要修复的字段直接填写真实、完整、可校验的对象或数组，不要先输出示例对象，"
        "也不要输出commentary或连续输出多个JSON对象。"
    )
    sections = [
        ("任务", "修复已完成终稿所附状态事务中的指定字段，修复后程序会重新执行完整校验。", 800, False),
        (
            "原结果问题",
            "\n".join(f"- {str(item)}" for item in validation_errors or [])
            or "- 状态事务未通过校验",
            8000,
            False,
        ),
        (
            "当前章节",
            "第{}章《{}》\n原规划提纲：{}".format(
                chapter_index + 1,
                chapter.get("title", "") if isinstance(chapter, dict) else "",
                chapter.get("outline", "") if isinstance(chapter, dict) else "",
            ),
            7000,
            False,
        ),
        ("最终正文", final_text, 34000, True),
        (
            "待修复的原正文字段",
            json.dumps(original_bundle, ensure_ascii=False, separators=(",", ":")),
            6000,
            False,
        ),
    ]
    if targets["memory_fields"]:
        sections.extend([
            (
                "待修复的原状态字段",
                json.dumps(original_memory, ensure_ascii=False, separators=(",", ":")),
                20000,
                False,
            ),
            (
                "机械引用清单",
                json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
                18000,
                False,
            ),
        ])
    if "next_chapter_memory" in targets["memory_fields"]:
        sections.append((
            "下一章边界",
            "标题：{}\n提纲：{}".format(
                next_chapter.get("title", "") if isinstance(next_chapter, dict) else "",
                next_chapter.get("outline", "") if isinstance(next_chapter, dict) else "",
            ),
            6000,
            False,
        ))
    return _assemble_bounded_long_form_context(sections, requirements)


def _build_long_form_memory_repair_context(
    project,
    chapter_index,
    final_text,
    outline="",
    summary="",
    key_facts="",
    logic_audit=None,
    memory_update=None,
    validation_errors=None,
):
    project = project if isinstance(project, dict) else {}
    patch_context = _build_long_form_memory_patch_context(
        project,
        chapter_index,
        final_text,
        outline,
        summary,
        key_facts,
        logic_audit,
        memory_update,
        validation_errors,
    )
    if patch_context:
        return patch_context
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter = chapters[chapter_index] if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict) else {}
    next_chapter = chapters[chapter_index + 1] if chapter_index + 1 < len(chapters) and isinstance(chapters[chapter_index + 1], dict) else {}
    repair_selection = _build_memory_repair_selection(
        project,
        chapter_index,
        memory_update=memory_update,
        validation_errors=validation_errors,
    )
    repair_manifest = _memory_repair_reference_manifest(
        project, chapter_index, memory_update or {}
    )
    compact_memory_update = _compact_memory_repair_update_for_context(
        project,
        chapter_index,
        memory_update or {},
        manifest=repair_manifest,
    )
    memory_sections = _long_form_memory_sections(project, repair_selection)
    contract = _long_form_update_contract_instructions(project, chapter_index, compact=True)
    error_text = "\n".join(f"- {str(item)}" for item in validation_errors or []) or "- 原终稿未返回可验证的版本2记忆增量"
    output_requirements = (
        "【输出要求】\n必须输出一个合法JSON对象，顶层结构为"
        '{"logic_audit":{"checked":true,"issues":[]},"outline":"6-10条实际提纲",'
        '"summary":"本章摘要","key_facts":["事实"],"long_form_memory":{...}}。'
        "logic_audit必须独立逐段检查最终正文内部的时间因果、人物生死/清醒/位置、物件存在/移动/开合/持有人、"
        "进出场、知识权限和代词指向；只报告有前后正文逐字证据的critical或major硬矛盾，最多3项。"
        "每项结构为severity、category、earlier_quote、later_quote、explanation；没有明确矛盾时issues为空。"
        "category只能使用chronology、causality、character_state、character_location、object_state、object_ownership、"
        "spatial_state、pronoun_reference或knowledge_permission。"
        "不能把文风、剧情选择、人物判断失误或现实流程不完整当成逻辑矛盾。"
        "每条evidence_quote必须从【最终正文】中原样复制一个连续子串，保留原文全部中文引号、标点和换行；"
        "尤其不得把正文中的“对白”改成不带引号的对白。输出前必须按字面检查该字符串能在最终正文中直接找到；"
        "找不到合格逐字证据时删除对应更新，不得概括、拼接或改写证据。"
        "long_form_memory严格执行以下契约：\n" + contract
    )
    source_sections = [
        ("任务", "只修复本章逻辑审查、提纲、摘要、关键事实和长篇记忆增量，不得重写正文，不得新增正文没有发生的事件。", 700, False),
        ("原结果问题", error_text, 6000, False),
        (
            "当前章节",
            f"第{chapter_index + 1}章《{chapter.get('title', '')}》\n"
            f"原规划提纲：{chapter.get('outline', '')}",
            7000,
            False,
        ),
        ("最终正文", final_text, 32000, True),
        (
            "原长篇记忆增量",
            json.dumps(compact_memory_update, ensure_ascii=False, separators=(",", ":")),
            16000,
            False,
        ),
        ("当前状态快照", memory_sections["当前状态快照"], 18000, False),
        (
            "AI资料更新与下一章选择索引",
            _build_long_form_selection_index(project, chapter_index, repair_selection),
            30000,
            False,
        ),
        ("当前活跃事实", memory_sections["活跃连续性事实"], 40000, False),
        (
            "下一章边界",
            f"标题：{next_chapter.get('title', '')}\n提纲：{next_chapter.get('outline', '')}",
            5500,
            False,
        ),
        ("已有实际提纲", outline, 5000, False),
        ("已有摘要", summary, 3000, False),
        ("已有关键事实", key_facts, 6000, False),
        ("近期阶段档案", memory_sections["近期阶段档案"], 12000, True),
    ]
    return _assemble_bounded_long_form_context(source_sections, output_requirements)


def _build_chapter_logic_repair_context(project, chapter_index, final_text, issues):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter = (
        chapters[chapter_index]
        if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict)
        else {}
    )
    selected_issues = [
        deepcopy(item) for item in issues if isinstance(item, dict)
    ][:3]
    requirements = (
        "【输出要求】\n只修复审查已经用前后逐字证据确认的硬矛盾，不重新审稿，不扩写、删减或重组其他段落。"
        "每个问题只选择能解除矛盾的最小连续原文范围；优先替换后出现的冲突动作或状态，保留既定剧情结果、人物口吻、"
        "段落节奏和附近措辞。不得补充解释、流程、总结、伏笔或新事件，也不得把修复写成角色讲道理。"
        "original_quote必须从最终正文逐字复制且在全文中只出现一次，并且覆盖该问题的earlier_quote或later_quote；"
        "replacement_text只填写可直接放回原位置的小说正文，可以为空表示删除一段明确多余的冲突文字。"
        "严格输出一个合法JSON对象，不输出Markdown、分析或完整正文。输出结构："
        '{"patches":[{"issue_index":1,"original_quote":"正文中唯一出现的连续原文",'
        '"replacement_text":"最小修复后的正文"}]}。'
        "patches必须与问题编号一一对应，不得新增审查没有列出的问题。"
    )
    sections = [
        (
            "任务",
            f"对第{chapter_index + 1}章《{chapter.get('title', '')}》执行一次证据限定的局部逻辑修复。",
            800,
            False,
        ),
        (
            "已确认硬矛盾",
            json.dumps(selected_issues, ensure_ascii=False, separators=(",", ":")),
            5000,
            False,
        ),
        ("最终正文", final_text, 34000, True),
    ]
    return _assemble_bounded_long_form_context(sections, requirements)


def _build_long_form_memory_finalize_context(project, chapter_index, final_text):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter = (
        chapters[chapter_index]
        if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict)
        else {}
    )
    next_chapter = (
        chapters[chapter_index + 1]
        if chapter_index + 1 < len(chapters) and isinstance(chapters[chapter_index + 1], dict)
        else {}
    )
    current_selection = chapter.get("memory_selection", {})
    current_selection = current_selection if isinstance(current_selection, dict) else {}
    has_scoped_selection = any(
        current_selection.get(key)
        for key in (
            "character_ids", "lore_ids", "foreshadow_ids", "fact_ids",
            "stage_archive_ids", "object_keys", "conflict_ids", "task_ids",
        )
    )
    finalize_selection = deepcopy(current_selection)
    if has_scoped_selection:
        finalize_selection.update({
            "_restrict_records": True,
            "_restrict_facts": True,
            "_restrict_archives": True,
            "_restrict_state": True,
            "_restrict_state_directory": True,
            "_compact_facts": True,
            "_compact_index_facts": True,
            "_compact_state": True,
            "_compact_archives": True,
            "_finalize_compact_index": True,
            "_relationships_within_selection": True,
        })
    selected_memory = _long_form_memory_sections(project, finalize_selection)
    contract = _long_form_update_contract_instructions(project, chapter_index, compact=True)
    stage_boundary = (chapter_index + 1) % 10 == 0
    task = (
        "只读取已经完成的【最终正文】，独立生成实际提纲、本章摘要、需继承关键事实和版本2长篇记忆增量；"
        "不得重写正文，不得把原规划提纲或下一章资料中的未来事件写成已经发生。\n"
        "生成状态资料前，先独立审查最终正文内部是否存在有前后逐字原文直接证明的硬矛盾。"
        "重点检查同一人物的生死、清醒、伤势和位置，物件的存在、撤走、开合、损毁、移动和持有人，"
        "人物进出场、时间先后、原因结果、明确知识或权限以及代词唯一指向。"
        "只有前文已经建立一个确定状态、后文又在没有任何过渡的情况下使用互斥状态，才列为问题；"
        "不得把人物判断失误、行为不够聪明、现实流程不完整、表达可优化、可能存在但没有证据的风险或单纯文风问题列为矛盾。"
        "最多列3项critical或major问题，每项必须分别逐字引用较早和较晚的正文证据；没有明确硬矛盾时issues必须为空。\n"
        "输出前在内部逐段检查人物实际出场和带来的新信息，以及伤势、能力、关系、位置、关键物、未决任务、"
        "伏笔和章末持续风险是否真的发生变化。只记录后续章节若不知道就会写错的结果，不记录正文的办理过程。\n"
        "会影响后文判断的线索、异常以及记录缺失/覆盖/删除/清空必须保留其结果和未决状态，"
        "但不要保存发现它们时的逐步核验流程。\n"
        "核对、封存、编号、取样、审批、交接、见证、记录固定和责任说明等一次性步骤，除非后文必须继续使用同一批次、"
        "持有人、权限、未完成任务或伏笔，否则只能并入最终结果，不能分别进入关键事实、事件、物件和任务。\n"
        "正文明确出现且会影响后文的每一项，都必须进入摘要或关键事实，并至少落入active fact、人物/设定运行态、"
        "伏笔、对象、冲突、任务或阶段档案中的一个真实存储位置；不能只出现在long_term_events清单里。\n"
        "正文中实际行动、说话、来电或提供关键信息的已有命名人物，必须进入current_chapter_character_refs和"
        "state_reconciliation.character_refs；有持续变化时还必须更新人物运行态。\n"
        "必须把正文中的可观察现象与机制结论分开：比喻、相似感、震动、光影、声音、人物猜测和来源未知，"
        "不能被摘要或状态整理命名为正文没有确认的共鸣、能力、因果或来源；无法确认时保留现象并写明未知。\n"
        "建立long_term_events后逐项复核其storage中的设定和伏笔引用：事件改变了公开层、权限、位置、损毁程度、"
        "推进或回收状态就同步更新运行态；未改变则明确列入record_runtime_review的unchanged数组。\n"
        "更新已有事实时必须对照索引中的原scope和精确内容，保留仍然有效的数量、程度、范围、部位、对象和不确定性；"
        "不得用更短的宽泛概括覆盖精确旧事实。全局紧凑状态目录中的每条引用都是真实存在的当前状态；"
        "普通章和十章边界都只提交本章选择、触及、新增、修订或退出的状态。十章边界的其他全部状态由程序原样继承并核验哈希。"
        "章首已经存在且章末没有变化的伤势、能力、关系、位置、规则和限制，即使正文再次表现，也不得重复进入fact_updates、"
        "record_updates、state_patch或long_term_events；只把实际出场人物放入current_chapter_character_refs，并在必要的"
        "unchanged复核项中确认。角色只完成一次检测、汇报、送达或普通执行动作，也不构成人物运行态更新。"
    )
    compact_target = (
        "本章不是十章边界。完整性优先，但只返回本章真正新增、改变、明确结束或被正文直接核对且后文必须继承的最小增量；"
        "不得为了接近上限填满数组。建议fact_updates 1-4项、long_term_events 1-3项、"
        "record_updates的人物与设定各0-3项、伏笔0-2项、state_patch各列表0-5项。"
        "人物仅行动、说话或提供信息时只进入current_chapter_character_refs与state_reconciliation.character_refs；"
        "只有章末持续状态、公开层或关系确有变化才写record_updates或state_patch。"
        "相同语义不得同时拆成多条事实、事件和状态；可以交叉引用，但每个分区只承担自己的存储职责。"
        "stage_archive必须为null。目标JSON总长度不超过8000字；确有彼此独立且后文必须继承的关键变化时可以突破建议数量，但不得省略。"
        if not stage_boundary else
        "本章是十章边界。除完整stage_archive外，其他分区仍只返回本章新增、改变、结束或直接核对的最小增量；"
        "不得回显最近十章或全量状态，未触及资料由程序原样继承。建议fact_updates 1-4项、long_term_events 1-3项、"
        "record_updates的人物与设定各0-3项、伏笔0-2项；章首已有且本章未改变的状态不得重复更新。"
    )
    output_requirements = (
        "【输出要求】\n严格输出一个合法JSON对象，顶层结构为"
        '{"logic_audit":{"checked":true,"issues":[{"severity":"critical|major",'
        '"category":"chronology|causality|character_state|character_location|object_state|object_ownership|spatial_state|pronoun_reference|knowledge_permission",'
        '"earlier_quote":"较早的正文逐字原文","later_quote":"较晚的正文逐字原文","explanation":"两种状态为何不能同时成立"}]},'
        '"prose_review":{"checked":true,"issues":["仅记录可逐字定位的读感问题"]},'
        '"repair_patches":[{"before":"正文中唯一出现的原句片段","after":"局部替换文本","reason":"重复说明|流程赘述|机械短碎|局部语言冲突"}],'
        '"outline":"6-10条实际提纲","summary":"本章摘要","key_facts":["事实"],"long_form_memory":{...}}。'
        "logic_audit只审查最终正文内部已经发生的直接矛盾，不评价文风和剧情选择；checked必须为true。"
        "prose_review只记录有明确原文位置的重复说明、无结果流程赘述、机械短碎或局部语言冲突；"
        "正常留白、剧情选择、文风偏好和现实流程不完整都不是问题。repair_patches通常为空；"
        "只有确实需要修补且before在最终正文中逐字唯一出现时才返回，最多3项。"
        "每项只能做一处局部替换，不能改剧情事实、人物决定、时间线、关系结果、伏笔或章末结果，"
        "更不能重写整段或整章。"
        "outline、summary和key_facts只能概括最终正文已经发生的内容。summary控制在500字以内；"
        "key_facts通常控制在3-8条，每条只保留一个后文必须继承的合并事实，同一事件的背景、过程、判断和结果不得拆成多条。"
        "确有超过8项彼此独立且都会影响后文时必须保留，不得为了数字上限丢失关键连续性。"
        "每条evidence_quote必须从最终正文逐字复制连续的8-60字原文，保留原标点和引号；"
        "找不到逐字证据时不得生成对应动态更新。"
        + compact_target
        + "long_form_memory严格执行以下契约：\n"
        + contract
    )
    selection_index = "\n\n".join(part for part in (
        _build_long_form_record_identity_index(project),
        _build_long_form_selection_index(
            project,
            chapter_index,
            selection=finalize_selection,
            limit=LONG_FORM_MEMORY_FINALIZE_INDEX_LIMIT,
        ),
    ) if part)
    source_sections = [
        ("任务", task, 3600, False),
        (
            "当前章节",
            f"第{chapter_index + 1}章《{chapter.get('title', '')}》\n"
            f"原规划提纲（只用于核对执行，不是事实来源）："
            f"{_strip_static_foreshadow_outline_fields(chapter.get('outline', ''))}",
            7000,
            False,
        ),
        ("最终正文", final_text, 34000, True),
        (
            "AI资料更新与下一章选择索引",
            selection_index,
            LONG_FORM_MEMORY_FINALIZE_INDEX_LIMIT + LONG_FORM_MEMORY_IDENTITY_INDEX_LIMIT,
            False,
        ),
        ("本章已选活跃事实详情", selected_memory["活跃连续性事实"], 24000, False),
        (
            "下一章边界（只用于选择需继承资料）",
            f"标题：{next_chapter.get('title', '')}\n"
            f"提纲：{_strip_static_foreshadow_outline_fields(next_chapter.get('outline', ''))}\n"
            "初始规划关联人物（仅弱参考）："
            + "、".join(_normalize_name_list(next_chapter.get("linked_characters", []))),
            6000,
            False,
        ),
        ("近期阶段档案", selected_memory["近期阶段档案"], 12000, True),
    ]
    return _assemble_bounded_long_form_context(source_sections, output_requirements)


def _parse_memory_reconciliation_result(value):
    text = str(value or "").strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.IGNORECASE | re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    start = text.find("{")
    if start < 0:
        return {"parsed": False, "corrections": {}}
    try:
        data, _offset = json.JSONDecoder().raw_decode(text[start:])
    except Exception:
        return {"parsed": False, "corrections": {}}
    if not isinstance(data, dict):
        return {"parsed": False, "corrections": {}}
    corrections = data.get(
        "corrections",
        data.get("state_corrections", data.get("long_form_memory_patch", data.get("memory_patch", {}))),
    )
    if isinstance(corrections, dict) and "replace" in corrections and isinstance(corrections.get("replace"), dict):
        corrections = corrections.get("replace", {})
    if not isinstance(corrections, dict):
        corrections = {}
    return {"parsed": True, "corrections": deepcopy(corrections)}


def _normalize_long_form_reconciliation_patch(project, patch):
    """Normalize the narrow correction contract before merging it.

    Reconciliation is forbidden from creating records. That makes a missing
    operation deterministic when an existing reference resolves and the row
    contains an actual correction. Unknown references remain untouched so the
    normal validator can reject them instead of guessing.
    """
    payload = deepcopy(patch) if isinstance(patch, dict) else {}
    nested = payload.get("replace")
    target = deepcopy(nested) if isinstance(nested, dict) else payload

    def first_value(item, keys):
        for key in keys:
            value = item.get(key, "")
            if isinstance(value, (list, dict)):
                if value:
                    return value
                continue
            if str(value or "").strip():
                return value
        return ""

    def normalize_operation(value):
        operation = str(value or "").strip().lower()
        if operation in {"modify", "change", "patch", "advance", "reinforce", "partial_payoff", "payoff", "discard"}:
            return "update"
        if operation in {"add", "new", "insert"}:
            return "create"
        return operation

    def normalize_items(kind, items):
        if not isinstance(items, list):
            return items
        aliases = {
            "characters": ("ref", "character_ref", "character_id", "record_ref", "id", "key"),
            "lore": ("ref", "lore_ref", "lore_id", "record_ref", "id", "key"),
            "foreshadows": (
                "ref", "foreshadow_ref", "foreshadow_id", "record_ref", "id", "key",
            ),
        }[kind]
        result = []
        for raw in items:
            if not isinstance(raw, dict):
                result.append(raw)
                continue
            item = deepcopy(raw)
            ref = str(first_value(item, aliases) or "").strip()
            resolved = _resolve_long_form_record_ref(project, kind, ref) if ref else ""
            if resolved:
                item["ref"] = resolved
            operation = normalize_operation(item.get("operation", ""))
            if not operation and resolved:
                has_correction = any(
                    str(item.get(key, "") or "").strip()
                    for key in (
                        "update", "dynamic", "runtime", "runtime_update", "state",
                        "change", "progress", "description", "previous", "previous_fact",
                        "previous_conflict", "previous_task", "evidence_quote", "evidence",
                    )
                )
                if has_correction:
                    operation = "update"
            if operation:
                item["operation"] = operation
            if operation == "update" and not str(item.get("state", "") or "").strip():
                update_text = first_value(
                    item,
                    ("dynamic", "runtime_update", "runtime", "change", "progress", "update", "description"),
                )
                if update_text:
                    item["state"] = update_text
            result.append(item)
        return result

    record_updates = target.get("record_updates")
    if isinstance(record_updates, dict):
        record_updates = deepcopy(record_updates)
        record_updates["characters"] = normalize_items(
            "characters", record_updates.get("characters", [])
        )
        record_updates["lore"] = normalize_items(
            "lore", record_updates.get("lore", [])
        )
        target["record_updates"] = record_updates
    target["foreshadow_updates"] = normalize_items(
        "foreshadows", target.get("foreshadow_updates", [])
    )

    if isinstance(nested, dict):
        payload["replace"] = target
        return payload
    return target


def _merge_long_form_memory_reconciliation_patch(memory_update, patch, project=None):
    """Merge a small boundary correction without replacing the original valid delta."""
    merged = deepcopy(memory_update) if isinstance(memory_update, dict) else {}
    patch = _normalize_long_form_reconciliation_patch(project, patch) if isinstance(project, dict) else (
        deepcopy(patch) if isinstance(patch, dict) else {}
    )
    corrections = patch.get("replace", patch) if isinstance(patch.get("replace"), dict) else patch
    if not isinstance(corrections, dict):
        return merged

    def merge_list(path, incoming, key_func):
        if not isinstance(incoming, list):
            return
        target = merged
        for part in path[:-1]:
            current = target.get(part)
            if not isinstance(current, dict):
                current = {}
                target[part] = current
            target = current
        key = path[-1]
        existing = target.get(key, [])
        existing = existing if isinstance(existing, list) else []
        for item in incoming:
            if not isinstance(item, dict):
                continue
            identity = key_func(item)
            if identity:
                replaced = False
                for index, old in enumerate(existing):
                    if isinstance(old, dict) and key_func(old) == identity:
                        existing[index] = deepcopy(item)
                        replaced = True
                        break
                if replaced:
                    continue
            existing.append(deepcopy(item))
        target[key] = existing

    merge_list(("fact_updates",), corrections.get("fact_updates", []), lambda item: str(
        item.get("id", "") or item.get("key", "") or ""
    ).strip())
    merge_list(("foreshadow_updates",), corrections.get("foreshadow_updates", []), lambda item: str(
        item.get("ref", "") or item.get("id", "") or item.get("key", "") or item.get("name", "")
    ).strip())
    for kind in ("characters", "lore"):
        merge_list(
            ("record_updates", kind),
            (corrections.get("record_updates", {}) or {}).get(kind, [])
            if isinstance(corrections.get("record_updates", {}), dict) else [],
            lambda item: str(item.get("ref", "") or item.get("id", "") or item.get("key", "") or item.get("name", "")).strip(),
        )

    state_patch = corrections.get("state_patch", {})
    if isinstance(state_patch, dict):
        current_state = merged.setdefault("state_patch", {})
        if not isinstance(current_state, dict):
            current_state = {}
            merged["state_patch"] = current_state
        for key in ("story_time", "location", "notes"):
            if str(state_patch.get(key, "") or "").strip():
                current_state[key] = str(state_patch.get(key, "") or "").strip()
        list_keys = {
            "character_states": lambda item: str(item.get("ref", "") or item.get("character_id", "")).strip(),
            "relationship_states": lambda item: "|".join(sorted(
                str(ref or "").strip()
                for ref in item.get("refs", item.get("characters", []))
                if str(ref or "").strip()
            )),
            "object_states": lambda item: _compact_text(item.get("key", item.get("name", ""))),
            "active_conflicts": lambda item: str(item.get("id", "") or item.get("key", "")).strip(),
            "unresolved_tasks": lambda item: str(item.get("id", "") or item.get("key", "")).strip(),
        }
        for key, key_func in list_keys.items():
            merge_target = current_state.get(key, [])
            merge_target = merge_target if isinstance(merge_target, list) else []
            for item in state_patch.get(key, []) if isinstance(state_patch.get(key), list) else []:
                if not isinstance(item, dict):
                    continue
                identity = key_func(item)
                replaced = False
                if identity:
                    for index, old in enumerate(merge_target):
                        if isinstance(old, dict) and key_func(old) == identity:
                            merge_target[index] = deepcopy(item)
                            replaced = True
                            break
                if not replaced:
                    merge_target.append(deepcopy(item))
            current_state[key] = merge_target

    retirements = corrections.get("state_retirements", {})
    if isinstance(retirements, dict):
        current_retirements = merged.setdefault("state_retirements", {})
        if not isinstance(current_retirements, dict):
            current_retirements = {}
            merged["state_retirements"] = current_retirements
        for key in ("character_refs", "relationship_refs", "object_keys", "conflict_ids", "task_ids"):
            values = current_retirements.get(key, [])
            values = values if isinstance(values, list) else []
            for value in retirements.get(key, []) if isinstance(retirements.get(key), list) else []:
                if key == "relationship_refs" and isinstance(value, list):
                    value = "|".join(sorted(str(ref or "").strip() for ref in value if str(ref or "").strip()))
                else:
                    value = str(value or "").strip()
                if value and value not in values:
                    values.append(value)
            current_retirements[key] = values

    reconciliation = merged.setdefault("state_reconciliation", {})
    if not isinstance(reconciliation, dict):
        reconciliation = {}
        merged["state_reconciliation"] = reconciliation
    for key in (
        "fact_refs", "character_refs", "lore_refs", "foreshadow_refs", "relationship_refs",
        "object_keys", "conflict_refs", "task_refs",
    ):
        values = reconciliation.get(key, [])
        values = values if isinstance(values, list) else []
        incoming = corrections.get("state_reconciliation", {})
        incoming = incoming.get(key, []) if isinstance(incoming, dict) else []
        for value in incoming if isinstance(incoming, list) else []:
            value = str(value or "").strip()
            if value and value not in values:
                values.append(value)
        reconciliation[key] = values

    def append_refs(target_key, items, ref_key):
        values = reconciliation.setdefault(target_key, [])
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            value = str(item.get(ref_key, "") or "").strip()
            if value and value not in values:
                values.append(value)

    append_refs("fact_refs", merged.get("fact_updates", []), "id")
    for item in merged.get("fact_updates", []):
        if isinstance(item, dict) and str(item.get("operation", "") or "").strip().lower() in {"add", "supersede"}:
            value = str(item.get("key", "") or "").strip()
            if value and value not in reconciliation["fact_refs"]:
                reconciliation["fact_refs"].append(value)
    state_patch = merged.get("state_patch", {})
    if isinstance(state_patch, dict):
        for item in state_patch.get("character_states", []) if isinstance(state_patch.get("character_states"), list) else []:
            if isinstance(item, dict):
                value = str(item.get("ref", "") or item.get("character_id", "") or "").strip()
                if value and value not in reconciliation["character_refs"]:
                    reconciliation["character_refs"].append(value)
        for item in state_patch.get("relationship_states", []) if isinstance(state_patch.get("relationship_states"), list) else []:
            if isinstance(item, dict):
                refs = item.get("refs", item.get("characters", []))
                refs = refs if isinstance(refs, list) else []
                value = "|".join(sorted(str(ref or "").strip() for ref in refs if str(ref or "").strip()))
                if value and value not in reconciliation["relationship_refs"]:
                    reconciliation["relationship_refs"].append(value)
        for item in state_patch.get("object_states", []) if isinstance(state_patch.get("object_states"), list) else []:
            if isinstance(item, dict):
                value = str(item.get("key", "") or item.get("name", "") or "").strip()
                if value and value not in reconciliation["object_keys"]:
                    reconciliation["object_keys"].append(value)
                lore_ref = str(item.get("lore_ref", "") or item.get("lore_id", "") or "").strip()
                if lore_ref and lore_ref not in reconciliation["lore_refs"]:
                    reconciliation["lore_refs"].append(lore_ref)
        append_refs("conflict_refs", state_patch.get("active_conflicts", []), "id")
        append_refs("task_refs", state_patch.get("unresolved_tasks", []), "id")
        for item in state_patch.get("active_conflicts", []) if isinstance(state_patch.get("active_conflicts"), list) else []:
            if isinstance(item, dict) and not str(item.get("id", "") or "").strip():
                value = str(item.get("key", "") or "").strip()
                if value and value not in reconciliation["conflict_refs"]:
                    reconciliation["conflict_refs"].append(value)
        for item in state_patch.get("unresolved_tasks", []) if isinstance(state_patch.get("unresolved_tasks"), list) else []:
            if isinstance(item, dict) and not str(item.get("id", "") or "").strip():
                value = str(item.get("key", "") or "").strip()
                if value and value not in reconciliation["task_refs"]:
                    reconciliation["task_refs"].append(value)
    merged_retirements = merged.get("state_retirements", {})
    if isinstance(merged_retirements, dict):
        for source_key, target_key in (
            ("character_refs", "character_refs"),
            ("relationship_refs", "relationship_refs"),
            ("object_keys", "object_keys"),
            ("conflict_ids", "conflict_refs"),
            ("task_ids", "task_refs"),
        ):
            for value in merged_retirements.get(source_key, []) if isinstance(merged_retirements.get(source_key), list) else []:
                if source_key == "relationship_refs" and isinstance(value, list):
                    value = "|".join(sorted(str(ref or "").strip() for ref in value if str(ref or "").strip()))
                else:
                    value = str(value or "").strip()
                if value and value not in reconciliation[target_key]:
                    reconciliation[target_key].append(value)
    record_updates = corrections.get("record_updates", {})
    if isinstance(record_updates, dict):
        for kind, target_key in (("characters", "character_refs"), ("lore", "lore_refs")):
            for item in record_updates.get(kind, []) if isinstance(record_updates.get(kind), list) else []:
                if not isinstance(item, dict):
                    continue
                value = str(
                    item.get("ref", "") or item.get("id", "")
                    or item.get("key", "") or ""
                ).strip()
                if value and value not in reconciliation[target_key]:
                    reconciliation[target_key].append(value)
    for item in corrections.get("foreshadow_updates", []) if isinstance(corrections.get("foreshadow_updates"), list) else []:
        if not isinstance(item, dict):
            continue
        value = str(item.get("ref", "") or item.get("id", "") or item.get("key", "") or "").strip()
        if value and value not in reconciliation["foreshadow_refs"]:
            reconciliation["foreshadow_refs"].append(value)

    lifecycle = merged.setdefault("fact_lifecycle_review", {})
    if not isinstance(lifecycle, dict):
        lifecycle = {}
        merged["fact_lifecycle_review"] = lifecycle
    reviewed = lifecycle.setdefault("reviewed_refs", [])
    if not isinstance(reviewed, list):
        reviewed = []
        lifecycle["reviewed_refs"] = reviewed
    for item in merged.get("fact_updates", []):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "") or "").strip()
        if item_id and item_id not in reviewed and item_id.startswith("AF-"):
            reviewed.append(item_id)
    state_review = merged.setdefault("state_lifecycle_review", {})
    if not isinstance(state_review, dict):
        state_review = {}
        merged["state_lifecycle_review"] = state_review
    for key in ("reviewed_object_keys", "reviewed_conflict_refs", "reviewed_task_refs"):
        if not isinstance(state_review.get(key), list):
            state_review[key] = []
    incoming_state_review = corrections.get("state_lifecycle_review", {})
    if isinstance(incoming_state_review, dict):
        for key in ("reviewed_object_keys", "reviewed_conflict_refs", "reviewed_task_refs"):
            for value in incoming_state_review.get(key, []) if isinstance(incoming_state_review.get(key), list) else []:
                value = str(value or "").strip()
                if value and value not in state_review[key]:
                    state_review[key].append(value)
    for value in reconciliation.get("conflict_refs", []):
        if str(value or "").startswith("CF-") and value not in state_review["reviewed_conflict_refs"]:
            state_review["reviewed_conflict_refs"].append(value)
    for value in reconciliation.get("task_refs", []):
        if str(value or "").startswith("TASK-") and value not in state_review["reviewed_task_refs"]:
            state_review["reviewed_task_refs"].append(value)
    return merged


def _build_long_form_memory_reconcile_context(
    project,
    chapter_index,
    final_text,
    memory_update,
    summary="",
    key_facts="",
):
    """Build a small boundary-only audit context; the result is an optional correction patch."""
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter = chapters[chapter_index] if 0 <= chapter_index < len(chapters) and isinstance(chapters[chapter_index], dict) else {}
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
    selection = chapter.get("memory_selection", {}) if isinstance(chapter, dict) else {}
    selection = selection if isinstance(selection, dict) else {}
    memory_sections = _long_form_memory_sections(project, selection)
    proposed = _normalize_long_form_update_payload(project, chapter_index, memory_update or {})
    recent_blocks = []
    for index in range(max(0, chapter_index - 9), chapter_index + 1):
        item = chapters[index] if 0 <= index < len(chapters) and isinstance(chapters[index], dict) else {}
        body = "见【最终正文】" if index == chapter_index else str(item.get("text", "") or "").strip()
        if len(body) > 5000:
            body = (
                _clip_context_text(body, 2450, preserve_lines=True)
                + "\n……（本章正文中段省略）……\n"
                + _clip_context_text(body, 2450, keep_tail=True, preserve_lines=True)
            )
        recent_blocks.append(
            "第{}章《{}》\n摘要：{}\n关键事实：{}\n正文：{}".format(
                index + 1,
                str(item.get("title", "") or "").strip(),
                _clip_context_text(
                    summary if index == chapter_index and str(summary or "").strip() else item.get("summary", ""),
                    700,
                    preserve_lines=True,
                ) or "暂无",
                _clip_context_text(
                    key_facts if index == chapter_index and str(key_facts or "").strip() else item.get("key_facts", ""),
                    1100,
                    preserve_lines=True,
                ) or "暂无",
                body or "暂无",
            )
        )
    recent_ten_text = "\n\n".join(recent_blocks)
    output_requirements = (
        "【输出要求】严格只输出一个合法JSON对象："
        '{"base_revision":当前修订号,"corrections":{"fact_updates":[],"state_patch":{},'
        '"state_retirements":{},"state_lifecycle_review":{"reviewed_object_keys":[],"reviewed_conflict_refs":[],"reviewed_task_refs":[]},'
        '"record_updates":{"characters":[],"lore":[]},'
        '"foreshadow_updates":[],"state_reconciliation":{}}}。'
        "只返回能由最终正文逐字证实、且能修正原增量语义的最小纠错项；没有错误就返回空数组和空对象。"
        "不要返回完整状态，不要重写未出错的更新，不要新建人物/设定/伏笔，不要凭空增加事实。"
        "证据来源有严格分区：evidence_quote只能从【最终正文】逐字连续复制；"
        "【最近十章正文、摘要与关键事实】只用于比较前后状态，禁止从其中复制任何证据，"
        "即使该句确实出现在前文，也不能作为本章纠错证据。输出前必须确认每条evidence_quote都能在最终正文中直接找到。"
        "对已有设定或伏笔的修正必须使用record_updates.lore或foreshadow_updates；每项必须填写operation:\"update\"、"
        "ref和evidence_quote，ref使用状态引用索引中的C/L/F短引用（例如L005、F003），不要使用lore_id、foreshadow_id或自然语言名称。"
        "对账阶段禁止operation:\"create\"；没有可靠的已有引用就不要输出该项。动态文字统一放在state字段，"
        "不要只使用update、dynamic或progress作为字段名。"
        "fact_updates沿用原契约字段：update/retire/supersede必须填写已有AF-ID、原scope、原previous_fact、"
        "修正后的fact或退出reason以及最终正文连续证据。"
        "修正已有CF/TASK时必须填写真实id，并分别原样填写previous_conflict或previous_task；退出则写入state_retirements。"
        "任何新增冲突或任务都应留给原状态整理，本次对账不得生成NCF/NTASK临时key。"
        "更新不能把未完成改成完成，也不能把疑似、未知或未授权改成确定、已知或已授权。"
        "正文只写比喻、感官相似或来源未知时，纠错结果必须删除状态增量自行补出的机制名词、因果、共鸣或能力来源，"
        "改回可观察现象和原确定性；不能因为项目设定中存在某机制就认定本章已经证实。"
        "同时核对long_term_events.storage引用的设定和伏笔是否已经在record_updates/foreshadow_updates同步动态变化；"
        "若确有变化而原增量漏写，必须在本次最小纠错补丁中补齐。"
    )
    source_sections = [
        ("任务", "只审查第十章边界的状态语义，不审正文文风，不改正文。", 900, False),
        ("最终正文", final_text, 36000, True),
        ("原本已通过校验的状态增量", json.dumps(proposed, ensure_ascii=False, separators=(",", ":")), 22000, False),
        ("调用前状态快照", memory_sections["当前状态快照"], 18000, False),
        (
            "状态引用索引",
            "\n\n".join(part for part in (
                _build_long_form_record_identity_index(project, limit=5000),
                _build_long_form_selection_index(project, chapter_index, limit=18000),
            ) if part),
            24000,
            False,
        ),
        ("最近十章正文、摘要与关键事实（仅供比对，禁止作为证据）", recent_ten_text, 56000, True),
        ("已选活跃事实", memory_sections["活跃连续性事实"], 12000, False),
        (
            "章节边界",
            f"第{chapter_index + 1}章《{chapter.get('title', '')}》\n当前修订号：{memory.get('revision', 0)}",
            1800,
            False,
        ),
    ]
    return _assemble_bounded_long_form_context(
        source_sections,
        output_requirements,
        limit=LONG_FORM_RECONCILIATION_CONTEXT_LIMIT,
    )


_LONG_TERM_RECORD_CLASSIFICATION_RULES = (
    "必须逐项检查最终正文中新出现或发生长期变化的内容，不能只写进state_snapshot、active_facts、"
    "unresolved_tasks或state_delta而漏掉对应长期档案。"
    "人物卡：只为有明确姓名或稳定称谓、后续会再次出场或持续影响关系/主线的具体人物create；"
    "一次性路人、无名群体和只完成单章功能的人物不要建卡。"
    "设定卡：正文首次确立且后续仍会约束剧情的规则、能力体系、势力、地点、长期持有物或跨章关键物件，"
    "现有设定没有对应记录时必须create；只出现一次并当章消耗的道具、场景装饰和气氛细节不要建卡。"
    "伏笔：正文新提出并明确承诺后续解释、揭晓、验证或回收的身份、真相、秘密、异常、因果链、"
    "关键物件去向或未来危险，现有伏笔没有对应记录时必须create；推进或兑现已有伏笔必须使用准确ID更新。"
    "未解真相不能只放unresolved_tasks，跨章关键物件不能只放object_states，持续角色不能只放character_states。"
    "同一内容可以同时保留当前状态和更新长期档案；分类不互斥。"
)


def _next_prefixed_id(items, prefix):
    highest = 0
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$", re.IGNORECASE)
    for item in items if isinstance(items, list) else []:
        item_id = str(item.get("id", "") or "").strip() if isinstance(item, dict) else ""
        match = pattern.match(item_id)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}-{highest + 1:04d}"


def _long_form_object_name_is_placeholder(name, key=""):
    compact_name = _compact_text(name)
    compact_key = _compact_text(key)
    return (
        not compact_name
        or compact_name.casefold() == compact_key.casefold()
        or bool(
            re.fullmatch(
                r"NOBJ(?:-[A-Z0-9]+)*\d+",
                compact_name,
                re.IGNORECASE,
            )
        )
    )


def _long_form_object_name_matches_state(name, state):
    compact_name = _compact_text(name)
    compact_state = _compact_text(state)
    if not compact_name or not compact_state:
        return False
    if compact_name.casefold() in compact_state.casefold():
        return True
    for width in (4, 3):
        if len(compact_name) < width:
            continue
        if any(
            compact_name[index:index + width].casefold() in compact_state.casefold()
            for index in range(len(compact_name) - width + 1)
        ):
            return True
    generic_pairs = {
        "物件", "当前", "已经", "仍在", "相关", "记录", "状态",
        "文书", "订单", "契约", "货单", "资料", "证物", "证据",
    }
    return any(
        marker not in generic_pairs
        and marker.casefold() in compact_state.casefold()
        for marker in (
            compact_name[index:index + 2]
            for index in range(max(0, len(compact_name) - 1))
        )
    )


def _long_form_same_object_entity(existing, incoming):
    existing = existing if isinstance(existing, dict) else {}
    incoming = incoming if isinstance(incoming, dict) else {}
    old_lore = str(existing.get("lore_id", "") or "").strip()
    new_lore = str(incoming.get("lore_id", "") or "").strip()
    if old_lore and new_lore:
        return old_lore == new_lore

    old_key = str(existing.get("key", "") or "").strip()
    new_key = str(incoming.get("key", "") or "").strip()
    old_name = _compact_text(existing.get("name", ""))
    new_name = _compact_text(incoming.get("name", ""))

    old_placeholder = _long_form_object_name_is_placeholder(old_name, old_key)
    new_placeholder = _long_form_object_name_is_placeholder(new_name, new_key)
    if old_placeholder and not new_placeholder:
        return _long_form_object_name_matches_state(
            new_name, existing.get("state", "")
        )
    if new_placeholder and not old_placeholder:
        return _long_form_object_name_matches_state(
            old_name, incoming.get("state", "")
        )
    if old_placeholder and new_placeholder:
        old_state = _compact_text(existing.get("state", ""))
        new_state = _compact_text(incoming.get("state", ""))
        if not old_state or not new_state:
            return old_key.casefold() == new_key.casefold()
        shorter, longer = sorted((old_state, new_state), key=len)
        if len(shorter) >= 8 and shorter.casefold() in longer.casefold():
            return True
        return SequenceMatcher(None, old_state, new_state).ratio() >= 0.42
    if old_name.casefold() == new_name.casefold():
        return True
    shorter, longer = sorted((old_name, new_name), key=len)
    return len(shorter) >= 4 and shorter.casefold() in longer.casefold()


def _next_long_form_object_key(issued_keys, preferred_key=""):
    values = {
        str(value or "").strip()
        for value in issued_keys or []
        if str(value or "").strip()
    }
    preferred = str(preferred_key or "").strip()
    match = re.match(r"^(.*?)(\d+)$", preferred)
    if match:
        root = match.group(1)
        width = len(match.group(2))
    else:
        root = "NOBJ-NF"
        width = 1
    pattern = re.compile(rf"^{re.escape(root)}(\d+)$", re.IGNORECASE)
    highest = 0
    for value in values:
        current = pattern.match(value)
        if current:
            highest = max(highest, int(current.group(1)))
            width = max(width, len(current.group(1)))
    return root + str(highest + 1).zfill(width)


def _append_record_runtime(memory, kind, item_id, chapter, chapter_index, state="", changes=None, evidence=""):
    runtime = memory.setdefault("record_runtime", {}).setdefault(kind, {})
    entry = runtime.setdefault(str(item_id), {"state": "", "developments": []})
    state_text = str(state or "").strip()
    if state_text:
        entry["state"] = state_text
    change_items = changes if isinstance(changes, list) else [changes] if changes else []
    change_items = [str(item or "").strip() for item in change_items if str(item or "").strip()]
    if change_items or str(evidence or "").strip():
        development = {
            "chapter_id": str(chapter.get("id", "") or ""),
            "chapter_index": chapter_index + 1,
            "changes": change_items,
            "evidence": str(evidence or "").strip(),
            "updated_at": now_str(),
        }
        developments = entry.setdefault("developments", [])
        if not developments or developments[-1] != development:
            developments.append(development)
        entry["developments"] = developments[-50:]
    entry["updated_at"] = now_str()


def _merge_long_form_state_patch(
    project, memory, chapter, chapter_index, patch, retirements, temp_refs=None
):
    snapshot = deepcopy(memory.get("state_snapshot", {}))
    patch = patch if isinstance(patch, dict) else {}
    retirements = retirements if isinstance(retirements, dict) else {}
    temp_refs = temp_refs if isinstance(temp_refs, dict) else {}
    issued_state_ids = _long_form_issued_state_ids(project, memory)

    def resolve_record(kind, ref):
        return (
            _resolve_long_form_record_ref(project, kind, ref)
            or _resolve_long_form_temp_ref(temp_refs, kind, ref)
        )
    for key in ("story_time", "location", "notes"):
        if key in patch and str(patch.get(key, "") or "").strip():
            snapshot[key] = str(patch.get(key, "") or "").strip()

    def merge_items(snapshot_key, incoming_key, key_func, normalizer):
        existing = snapshot.get(snapshot_key, []) if isinstance(snapshot.get(snapshot_key), list) else []
        order = []
        records = {}

        def store(item_key, item):
            value = deepcopy(item)
            if snapshot_key == "object_states" and item_key in records:
                previous = records[item_key]
                for field in ("lore_id", "key", "name"):
                    if (
                        not str(value.get(field, "") or "").strip()
                        and str(previous.get(field, "") or "").strip()
                    ):
                        value[field] = previous[field]
            records[item_key] = value

        for item in existing:
            if not isinstance(item, dict):
                continue
            item_key = key_func(item)
            if not item_key:
                continue
            if item_key not in records:
                order.append(item_key)
            store(item_key, item)
        for item in patch.get(incoming_key, []) if isinstance(patch.get(incoming_key), list) else []:
            normalized = normalizer(item)
            if not normalized:
                continue
            item_key = key_func(normalized)
            if not item_key:
                continue
            if item_key not in records:
                order.append(item_key)
            store(item_key, normalized)
        snapshot[snapshot_key] = [records[item_key] for item_key in order if item_key in records]

    character_names = {
        str(item.get("id", "") or "").strip(): str(item.get("name", "") or "").strip()
        for item in project.get("characters", []) if isinstance(item, dict)
    }

    def normalize_character(item):
        if not isinstance(item, dict):
            return None
        item_id = resolve_record(
            "characters", item.get("ref", item.get("character_id", ""))
        )
        name = str(item.get("name", "") or character_names.get(item_id, "")).strip()
        state = str(item.get("state", "") or "").strip()
        return {"character_id": item_id, "name": name, "state": state} if item_id and state else None

    def character_key(item):
        return str(item.get("character_id", "") or "").strip()

    merge_items("character_states", "character_states", character_key, normalize_character)
    retired_character_ids = {
        resolve_record("characters", ref)
        for ref in retirements.get("character_refs", []) if str(ref or "").strip()
    }
    snapshot["character_states"] = [
        item for item in snapshot.get("character_states", [])
        if str(item.get("character_id", "") or "") not in retired_character_ids
    ]

    def normalize_relationship(item):
        if not isinstance(item, dict):
            return None
        refs = item.get("refs", item.get("characters", []))
        ids = []
        for ref in refs if isinstance(refs, list) else []:
            item_id = resolve_record("characters", ref)
            if item_id and item_id not in ids:
                ids.append(item_id)
        state = str(item.get("state", "") or "").strip()
        return {"characters": ids, "state": state} if len(ids) >= 2 and state else None

    def relationship_key(item):
        ids = [str(value or "").strip() for value in item.get("characters", []) if str(value or "").strip()]
        return "|".join(sorted(ids)) if len(ids) >= 2 else ""

    merge_items("relationship_states", "relationship_states", relationship_key, normalize_relationship)
    retired_relationship_keys = set()
    for value in retirements.get("relationship_refs", []) if isinstance(retirements.get("relationship_refs"), list) else []:
        refs = value if isinstance(value, list) else str(value or "").split("|")
        ids = [resolve_record("characters", ref) for ref in refs]
        ids = [item_id for item_id in ids if item_id]
        if len(ids) >= 2:
            retired_relationship_keys.add("|".join(sorted(ids)))
    snapshot["relationship_states"] = [
        item for item in snapshot.get("relationship_states", [])
        if relationship_key(item) not in retired_relationship_keys
    ]

    def normalize_object(item):
        if not isinstance(item, dict):
            return None
        lore_id = resolve_record(
            "lore", item.get("lore_ref", item.get("lore_id", ""))
        )
        name = str(item.get("name", "") or item.get("key", "")).strip()
        state = str(item.get("state", "") or "").strip()
        result = {"lore_id": lore_id, "name": name, "state": state}
        if str(item.get("key", "") or "").strip():
            result["key"] = str(item.get("key", "") or "").strip()
        return result if (lore_id or name) and state else None

    def object_key(item):
        return str(item.get("key", "") or item.get("lore_id", "") or _compact_text(item.get("name", ""))).strip()

    existing_objects = snapshot.get("object_states", [])
    existing_objects = existing_objects if isinstance(existing_objects, list) else []
    object_order = []
    object_records = {}

    def store_object(item_key, item):
        value = deepcopy(item)
        if item_key in object_records:
            previous = object_records[item_key]
            for field in ("lore_id", "key", "name"):
                if (
                    not str(value.get(field, "") or "").strip()
                    and str(previous.get(field, "") or "").strip()
                ):
                    value[field] = previous[field]
            if (
                _long_form_object_name_is_placeholder(
                    value.get("name", ""), value.get("key", item_key)
                )
                and not _long_form_object_name_is_placeholder(
                    previous.get("name", ""), previous.get("key", item_key)
                )
            ):
                value["name"] = previous["name"]
        object_records[item_key] = value

    for item in existing_objects:
        if not isinstance(item, dict):
            continue
        item_key = object_key(item)
        if not item_key:
            continue
        if item_key not in object_records:
            object_order.append(item_key)
        store_object(item_key, item)
    issued_state_ids["objects"].update(object_records)

    incoming_objects = patch.get("object_states", [])
    incoming_objects = incoming_objects if isinstance(incoming_objects, list) else []
    for item in incoming_objects:
        normalized = normalize_object(item)
        if not normalized:
            continue
        requested_key = object_key(normalized)
        if not requested_key:
            continue
        assigned_key = requested_key
        existing = object_records.get(requested_key)
        if (
            existing is not None
            and not _long_form_same_object_entity(existing, normalized)
        ) or (
            existing is None
            and requested_key in issued_state_ids["objects"]
        ):
            assigned_key = _next_long_form_object_key(
                issued_state_ids["objects"],
                requested_key,
            )
            normalized["key"] = assigned_key
            if _long_form_object_name_is_placeholder(
                normalized.get("name", ""), requested_key
            ):
                normalized["name"] = assigned_key
            temp_refs.setdefault("objects", {})[requested_key] = assigned_key
        if assigned_key not in object_records:
            object_order.append(assigned_key)
        store_object(assigned_key, normalized)
        issued_state_ids["objects"].add(assigned_key)
    snapshot["object_states"] = [
        object_records[item_key]
        for item_key in object_order
        if item_key in object_records
    ]
    retired_object_keys = {_compact_text(value) for value in retirements.get("object_keys", []) if str(value or "").strip()}
    snapshot["object_states"] = [
        item for item in snapshot.get("object_states", [])
        if _compact_text(item.get("key", item.get("name", ""))) not in retired_object_keys
    ]

    for snapshot_key, incoming_key, id_prefix, text_key, retirement_key in (
        ("active_conflicts", "active_conflicts", "CF", "conflict", "conflict_ids"),
        ("unresolved_tasks", "unresolved_tasks", "TASK", "task", "task_ids"),
    ):
        issued_kind = "conflicts" if snapshot_key == "active_conflicts" else "tasks"
        existing = snapshot.get(snapshot_key, []) if isinstance(snapshot.get(snapshot_key), list) else []
        records = {str(item.get("id", "") or "").strip(): deepcopy(item) for item in existing if isinstance(item, dict) and str(item.get("id", "") or "").strip()}
        order = [str(item.get("id", "") or "").strip() for item in existing if isinstance(item, dict) and str(item.get("id", "") or "").strip()]
        issued_state_ids[issued_kind].update(records)
        for item in patch.get(incoming_key, []) if isinstance(patch.get(incoming_key), list) else []:
            if not isinstance(item, dict):
                continue
            text = str(item.get(text_key, "") or "").strip()
            if not text:
                continue
            item_id = str(item.get("id", "") or "").strip()
            if item_id not in records:
                item_id = _next_prefixed_id(
                    [{"id": value} for value in issued_state_ids[issued_kind]],
                    id_prefix,
                )
                issued_state_ids[issued_kind].add(item_id)
                order.append(item_id)
                temp_key = str(item.get("key", "") or "").strip()
                temp_kind = "conflicts" if snapshot_key == "active_conflicts" else "tasks"
                if temp_key:
                    temp_refs.setdefault(temp_kind, {})[temp_key] = item_id
            records[item_id] = {"id": item_id, text_key: text}
        retired_ids = {str(value or "").strip() for value in retirements.get(retirement_key, []) if str(value or "").strip()}
        snapshot[snapshot_key] = [records[item_id] for item_id in order if item_id in records and item_id not in retired_ids]

    memory["issued_state_ids"] = {
        kind: sorted(values)
        for kind, values in issued_state_ids.items()
    }

    snapshot["as_of_chapter_id"] = str(chapter.get("id", "") or "")
    snapshot["as_of_chapter_index"] = chapter_index + 1
    snapshot["updated_at"] = now_str()
    memory["state_snapshot"] = snapshot


def _append_fact_history_version(
    memory,
    record,
    chapter,
    chapter_index,
    status,
    reason="",
    evidence="",
    replacement_fact_id="",
):
    if not isinstance(record, dict):
        return
    archived = deepcopy(record)
    archived["status"] = str(status or "").strip() or "revised"
    archived["history_chapter_id"] = str(chapter.get("id", "") or "")
    archived["history_chapter_index"] = chapter_index + 1
    archived["history_reason"] = str(reason or "").strip()
    archived["history_evidence"] = str(evidence or "").strip()
    if archived["status"] == "retired":
        archived["retired_chapter_id"] = archived["history_chapter_id"]
        archived["retired_chapter_index"] = archived["history_chapter_index"]
        archived["retire_reason"] = archived["history_reason"]
        archived["retire_evidence"] = archived["history_evidence"]
    elif archived["status"] == "superseded":
        archived["superseded_chapter_id"] = archived["history_chapter_id"]
        archived["superseded_chapter_index"] = archived["history_chapter_index"]
        archived["supersede_reason"] = archived["history_reason"]
        archived["supersede_evidence"] = archived["history_evidence"]
    elif archived["status"] == "revised":
        archived["revised_chapter_id"] = archived["history_chapter_id"]
        archived["revised_chapter_index"] = archived["history_chapter_index"]
    if replacement_fact_id:
        archived["replacement_fact_id"] = str(replacement_fact_id)
    archived["archived_at"] = now_str()
    memory.setdefault("fact_history", []).append(archived)


def _retained_fact_continuity_details(record, incoming_fact):
    record = record if isinstance(record, dict) else {}
    incoming_compact = _compact_text(incoming_fact)
    candidates = [{
        "fact": str(record.get("fact", "") or "").strip(),
        "source_chapter_index": int(
            record.get("evidence_chapter_index", record.get("source_chapter_index", 0))
            or 0
        ),
        "evidence": str(record.get("evidence", "") or "").strip(),
    }]
    candidates.extend(
        deepcopy(record.get("continuity_details", []))
        if isinstance(record.get("continuity_details"), list) else []
    )
    result = []
    seen = set()
    used = 0
    for candidate in candidates:
        if isinstance(candidate, dict):
            fact = str(candidate.get("fact", "") or "").strip()
            source_index = int(candidate.get("source_chapter_index", 0) or 0)
            evidence = str(candidate.get("evidence", "") or "").strip()
        else:
            fact = str(candidate or "").strip()
            source_index = 0
            evidence = ""
        compact = _compact_text(fact)
        if (
            not compact
            or compact in seen
            or (incoming_compact and compact in incoming_compact)
        ):
            continue
        remaining = LONG_FORM_FACT_CONTINUITY_DETAIL_LIMIT - used
        if remaining <= 0:
            break
        fact = _clip_context_text(fact, min(500, remaining), preserve_lines=True)
        if not fact:
            continue
        normalized = {"fact": fact}
        if source_index:
            normalized["source_chapter_index"] = source_index
        if evidence:
            normalized["evidence"] = _clip_context_text(
                evidence, min(160, max(0, remaining - len(fact))), preserve_lines=True
            )
        result.append(normalized)
        seen.add(compact)
        used += len(fact) + len(str(normalized.get("evidence", "") or ""))
        if len(result) >= LONG_FORM_MAX_FACT_CONTINUITY_DETAILS:
            break
    return result


def _merge_cumulative_story_text(existing, incoming):
    old = _dedupe_text_lines(existing)
    new = _dedupe_text_lines(incoming)
    if not new:
        return old
    if not old:
        return new
    if new in old:
        return old
    if old in new:
        return new
    return _dedupe_text_lines(_append_text_without_duplicate_overlap(old, new))


def _apply_long_form_memory_update_unchecked(project, chapter_index, payload, update_hash):
    chapters = project["chapters"]
    chapter = chapters[chapter_index]
    memory = _backfill_long_form_fact_scopes(
        _normalize_long_form_memory(project.get("long_form_memory", {}))
    )
    revision_before = int(memory.get("revision", 0) or 0)
    reference_maps = _long_form_record_reference_maps(project)
    temp_refs = {
        "characters": {}, "lore": {}, "foreshadows": {}, "facts": {},
        "archives": {}, "objects": {}, "conflicts": {}, "tasks": {},
    }
    touched_refs = {"characters": [], "lore": [], "foreshadows": []}
    touched_fact_ids = []

    record_updates = payload.get("record_updates", {}) if isinstance(payload.get("record_updates"), dict) else {}
    for kind, project_key, factory, canon_fields in (
        ("characters", "characters", _new_character, ("role", "goal", "secret", "voice", "notes")),
        ("lore", "lore", _new_lore, ("type", "description")),
    ):
        records = project.setdefault(project_key, [])
        by_name = {
            _compact_text(item.get("name", "")).casefold(): item
            for item in records if isinstance(item, dict) and str(item.get("name", "") or "").strip()
        }
        for item in record_updates.get(kind, []) if isinstance(record_updates.get(kind), list) else []:
            if not isinstance(item, dict):
                continue
            operation = str(item.get("operation", "") or "").strip().lower()
            if operation == "update":
                item_id = _resolve_long_form_record_ref(project, kind, item.get("ref", item.get("id", "")))
                record = reference_maps[kind]["id_to_record"].get(item_id)
            else:
                name = str(item.get("name", "") or "").strip()
                item_id = _resolve_long_form_record_ref(
                    project, kind, item.get("ref", item.get("id", ""))
                )
                record = reference_maps[kind]["id_to_record"].get(item_id)
                if record is None:
                    record = by_name.get(_compact_text(name).casefold())
                if record is None and name:
                    record = factory(len(records))
                    record["id"] = uuid.uuid4().hex
                    record["name"] = name
                    canon = (
                        _character_identity_fields_from_item(item)
                        if kind == "characters"
                        else item.get("canon", item.get("fields", {}))
                    )
                    if isinstance(canon, dict):
                        for field in canon_fields:
                            value = str(canon.get(field, "") or "").strip()
                            if value:
                                record[field] = value
                    records.append(record)
                    by_name[_compact_text(name).casefold()] = record
                item_id = str(record.get("id", "") or "").strip() if isinstance(record, dict) else ""
                key = str(item.get("key", "") or "").strip()
                if key and item_id:
                    temp_refs[kind][key] = item_id
            if not isinstance(record, dict) or not item_id:
                continue
            if kind == "characters":
                identity_fields = _character_identity_fields_from_item(item)
                if operation == "update":
                    _promote_character_identity(record, item.get("name"), identity_fields)
                    _merge_character_identity_fields(record, identity_fields)
                else:
                    _promote_character_identity(record, item.get("name"), identity_fields)
                    _merge_character_identity_fields(record, identity_fields)
                raw_identity = item.get("identity_patch")
                if not isinstance(raw_identity, (dict, str)):
                    raw_identity = item.get("canon", item.get("fields", {}))
                _apply_character_string_canon(record, raw_identity)
            if item_id not in touched_refs[kind]:
                touched_refs[kind].append(item_id)
            state = str(item.get("state", "") or "").strip()
            changes = item.get("changes", [])
            if not state and isinstance(item.get("fields"), dict):
                state = str(item.get("fields", {}).get("notes", "") or "").strip()
                changes = [
                    f"{field}：{str(value or '').strip()}"
                    for field, value in item.get("fields", {}).items()
                    if str(value or "").strip()
                ]
            _append_record_runtime(
                memory, kind, item_id, chapter, chapter_index, state, changes,
                item.get("evidence_quote", item.get("evidence", "")),
            )
            if kind == "lore":
                story_known = str(item.get("story_known", "") or "").strip()
                runtime_entry = memory["record_runtime"]["lore"][item_id]
                existing_story_known = _merge_cumulative_story_text(
                    record.get("story_known", ""), runtime_entry.get("story_known", "")
                )
                merged_story_known = _merge_cumulative_story_text(
                    existing_story_known, story_known
                )
                if merged_story_known:
                    record["story_known"] = merged_story_known
                    runtime_entry["story_known"] = merged_story_known

    foreshadow_records = project.setdefault("foreshadow_items", [])
    foreshadow_by_name = {
        _compact_text(_clean_foreshadow_name(item.get("name", ""))).casefold(): item
        for item in foreshadow_records if isinstance(item, dict) and _clean_foreshadow_name(item.get("name", ""))
    }
    for item in payload.get("foreshadow_updates", []) if isinstance(payload.get("foreshadow_updates"), list) else []:
        if not isinstance(item, dict):
            continue
        operation = str(item.get("operation", "") or "").strip().lower()
        if operation == "update":
            item_id = _resolve_long_form_record_ref(project, "foreshadows", item.get("ref", item.get("id", "")))
            record = reference_maps["foreshadows"]["id_to_record"].get(item_id)
        else:
            name = _clean_foreshadow_name(item.get("name", ""))
            record = foreshadow_by_name.get(_compact_text(name).casefold())
            if record is None and name:
                record = _new_foreshadow(len(foreshadow_records))
                record["id"] = uuid.uuid4().hex
                record["name"] = name
                canon = item.get("canon", {})
                if isinstance(canon, dict):
                    for field in ("description", "setup_chapter", "payoff_chapter"):
                        value = str(canon.get(field, "") or "").strip()
                        if value:
                            record[field] = value
                foreshadow_records.append(record)
                foreshadow_by_name[_compact_text(name).casefold()] = record
            item_id = str(record.get("id", "") or "").strip() if isinstance(record, dict) else ""
            key = str(item.get("key", "") or "").strip()
            if key and item_id:
                temp_refs["foreshadows"][key] = item_id
        if not isinstance(record, dict) or not item_id:
            continue
        if item_id not in touched_refs["foreshadows"]:
            touched_refs["foreshadows"].append(item_id)
        status = str(item.get("status", "") or "").strip()
        if status in {"未埋", "已埋", "已回收", "无需回收", "废弃"}:
            # A later response may describe an already-planted clue as
            # "未埋" again. Keep the lifecycle monotonic unless the model
            # explicitly advances or retires it.
            record["status"] = _merge_foreshadow_status(record.get("status", ""), status)
        chapter_label = _chapter_label(chapter_index + 1, chapter)
        setup_chapter = _normalize_foreshadow_chapter_ref(item.get("setup_chapter", ""))
        payoff_chapter = _normalize_foreshadow_chapter_ref(item.get("payoff_chapter", ""))
        if setup_chapter and not str(record.get("setup_chapter", "") or "").strip():
            record["setup_chapter"] = setup_chapter
        elif status == "已埋" and not str(record.get("setup_chapter", "") or "").strip():
            record["setup_chapter"] = chapter_label
        if payoff_chapter:
            record["payoff_chapter"] = payoff_chapter
        elif status == "已回收":
            record["payoff_chapter"] = chapter_label
        previous_runtime = memory.get("record_runtime", {}).get("foreshadows", {}).get(item_id, {})
        previous_runtime = previous_runtime if isinstance(previous_runtime, dict) else {}
        revealed = str(item.get("revealed", "") or "").strip()
        existing_revealed = _merge_cumulative_story_text(
            record.get("revealed", ""), previous_runtime.get("revealed", "")
        )
        merged_revealed = _merge_cumulative_story_text(existing_revealed, revealed)
        if merged_revealed:
            record["revealed"] = merged_revealed
        if "remaining_secret" in item:
            incoming_secret = str(item.get("remaining_secret", "") or "").strip()
            if status in {"已回收", "无需回收", "废弃"}:
                record["remaining_secret"] = _dedupe_text_lines(incoming_secret)
            else:
                existing_secret = _merge_cumulative_story_text(
                    record.get("remaining_secret", ""), previous_runtime.get("remaining_secret", "")
                )
                record["remaining_secret"] = _merge_cumulative_story_text(
                    existing_secret, incoming_secret
                )
        else:
            existing_secret = _merge_cumulative_story_text(
                record.get("remaining_secret", ""), previous_runtime.get("remaining_secret", "")
            )
            if existing_secret:
                record["remaining_secret"] = existing_secret
        state = str(item.get("state", item.get("description", "")) or "").strip()
        _append_record_runtime(
            memory, "foreshadows", item_id, chapter, chapter_index, state,
            [state] if state else [], item.get("evidence_quote", item.get("evidence", "")),
        )
        runtime_entry = memory["record_runtime"]["foreshadows"][item_id]
        if str(record.get("revealed", "") or "").strip():
            runtime_entry["revealed"] = str(record.get("revealed", "") or "").strip()
        if "remaining_secret" in record:
            runtime_entry["remaining_secret"] = str(record.get("remaining_secret", "") or "").strip()
    _ensure_foreshadow_codes(project)

    active_facts = [deepcopy(item) for item in memory.get("active_facts", []) if isinstance(item, dict)]
    fact_by_id = {str(item.get("id", "") or "").strip(): item for item in active_facts if str(item.get("id", "") or "").strip()}
    fact_order = [str(item.get("id", "") or "").strip() for item in active_facts if str(item.get("id", "") or "").strip()]
    lifecycle_review = payload.get("fact_lifecycle_review", {})
    reviewed_refs = lifecycle_review.get("reviewed_refs", []) if isinstance(lifecycle_review, dict) else []
    for item_id in reviewed_refs if isinstance(reviewed_refs, list) else []:
        record = fact_by_id.get(str(item_id or "").strip())
        if record is not None:
            record["last_reviewed_chapter_id"] = str(chapter.get("id", "") or "")
            record["last_reviewed_chapter_index"] = chapter_index + 1
            record["last_reviewed_at"] = now_str()

    def create_fact_record(item, item_id, supersedes_fact_id=""):
        scope = _resolve_long_form_scope_temp_refs(
            project,
            item.get("scope", ""),
            temp_refs,
        )
        record = {
            "id": item_id,
            "scope": scope,
            "fact": str(item.get("fact", "") or "").strip(),
            "status": "active",
            "source_chapter_id": str(chapter.get("id", "") or ""),
            "source_chapter_index": chapter_index + 1,
            "evidence": str(item.get("evidence_quote", item.get("evidence", "")) or "").strip(),
            "evidence_chapter_id": str(chapter.get("id", "") or ""),
            "evidence_chapter_index": chapter_index + 1,
            "last_reviewed_chapter_id": str(chapter.get("id", "") or ""),
            "last_reviewed_chapter_index": chapter_index + 1,
            "last_reviewed_at": now_str(),
            "updated_at": now_str(),
        }
        if supersedes_fact_id:
            record["supersedes_fact_id"] = supersedes_fact_id
        return record

    for item in payload.get("fact_updates", []) if isinstance(payload.get("fact_updates"), list) else []:
        if not isinstance(item, dict):
            continue
        operation = str(item.get("operation", "") or "").strip().lower()
        if operation == "add":
            fact_text = str(item.get("fact", "") or "").strip()
            scope = str(item.get("scope", "") or "").strip()
            duplicate = next((
                record for record in fact_by_id.values()
                if _compact_text(record.get("fact", "")) == _compact_text(fact_text)
                and (
                    not scope
                    or not str(record.get("scope", "") or "").strip()
                    or _compact_text(record.get("scope", "")).casefold() == _compact_text(scope).casefold()
                )
            ), None)
            if duplicate is not None:
                item_id = str(duplicate.get("id", "") or "")
                if scope and not str(duplicate.get("scope", "") or "").strip():
                    duplicate["scope"] = scope
                duplicate["last_reviewed_chapter_id"] = str(chapter.get("id", "") or "")
                duplicate["last_reviewed_chapter_index"] = chapter_index + 1
                duplicate["last_reviewed_at"] = now_str()
            else:
                item_id = _next_prefixed_id(
                    list(fact_by_id.values()) + [
                        record for record in memory.get("fact_history", []) if isinstance(record, dict)
                    ],
                    "AF",
                )
                record = create_fact_record(item, item_id)
                fact_by_id[item_id] = record
                fact_order.append(item_id)
            key = str(item.get("key", "") or "").strip()
            if key:
                temp_refs["facts"][key] = item_id
            if item_id not in touched_fact_ids:
                touched_fact_ids.append(item_id)
        elif operation == "keep":
            item_id = str(item.get("id", "") or "").strip()
            record = fact_by_id.get(item_id)
            if record is not None:
                record["last_reviewed_chapter_id"] = str(chapter.get("id", "") or "")
                record["last_reviewed_chapter_index"] = chapter_index + 1
                record["last_reviewed_at"] = now_str()
        elif operation == "update":
            item_id = str(item.get("id", "") or "").strip()
            record = fact_by_id.get(item_id)
            if record is not None:
                evidence = str(item.get("evidence_quote", item.get("evidence", "")) or "").strip()
                incoming_fact = str(item.get("fact", "") or "").strip()
                continuity_details = _retained_fact_continuity_details(
                    record, incoming_fact
                )
                _append_fact_history_version(
                    memory, record, chapter, chapter_index, "revised",
                    reason="same_scope_update", evidence=evidence,
                )
                record["fact"] = incoming_fact
                if continuity_details:
                    record["continuity_details"] = continuity_details
                else:
                    record.pop("continuity_details", None)
                scope = str(item.get("scope", "") or "").strip()
                if scope:
                    record["scope"] = _resolve_long_form_scope_temp_refs(
                        project, scope, temp_refs
                    )
                record["status"] = "active"
                record["updated_chapter_id"] = str(chapter.get("id", "") or "")
                record["updated_chapter_index"] = chapter_index + 1
                record["evidence"] = evidence
                record["evidence_chapter_id"] = str(chapter.get("id", "") or "")
                record["evidence_chapter_index"] = chapter_index + 1
                record["last_reviewed_chapter_id"] = str(chapter.get("id", "") or "")
                record["last_reviewed_chapter_index"] = chapter_index + 1
                record["last_reviewed_at"] = now_str()
                record["updated_at"] = now_str()
                if item_id not in touched_fact_ids:
                    touched_fact_ids.append(item_id)
        elif operation == "retire":
            item_id = str(item.get("id", "") or "").strip()
            record = fact_by_id.pop(item_id, None)
            if record is not None:
                _append_fact_history_version(
                    memory, record, chapter, chapter_index, "retired",
                    reason=item.get("reason", ""),
                    evidence=item.get("evidence_quote", item.get("evidence", "")),
                )
        elif operation == "supersede":
            old_id = str(item.get("id", "") or "").strip()
            old_record = fact_by_id.pop(old_id, None)
            if old_record is None:
                continue
            new_id = _next_prefixed_id(
                list(fact_by_id.values()) + [
                    record for record in memory.get("fact_history", []) if isinstance(record, dict)
                ] + [old_record],
                "AF",
            )
            evidence = str(item.get("evidence_quote", item.get("evidence", "")) or "").strip()
            _append_fact_history_version(
                memory, old_record, chapter, chapter_index, "superseded",
                reason=item.get("reason", ""), evidence=evidence,
                replacement_fact_id=new_id,
            )
            fact_by_id[new_id] = create_fact_record(item, new_id, supersedes_fact_id=old_id)
            insert_at = fact_order.index(old_id) if old_id in fact_order else len(fact_order)
            if old_id in fact_order:
                fact_order.remove(old_id)
            fact_order.insert(insert_at, new_id)
            key = str(item.get("key", "") or "").strip()
            if key:
                temp_refs["facts"][key] = new_id
            if new_id not in touched_fact_ids:
                touched_fact_ids.append(new_id)
    memory["active_facts"] = [fact_by_id[item_id] for item_id in fact_order if item_id in fact_by_id]
    memory["fact_history"] = [
        item for item in memory.get("fact_history", []) if isinstance(item, dict)
    ]

    _merge_long_form_state_patch(
        project, memory, chapter, chapter_index,
        payload.get("state_patch", {}), payload.get("state_retirements", {}),
        temp_refs=temp_refs,
    )
    state_lifecycle_review = payload.get("state_lifecycle_review", {})
    if isinstance(state_lifecycle_review, dict):
        reviewed_objects = [
            _resolve_long_form_temp_ref(
                temp_refs, "objects", value, str(value or "").strip()
            )
            for value in state_lifecycle_review.get("reviewed_object_keys", [])
            if str(value or "").strip()
        ] if isinstance(state_lifecycle_review.get("reviewed_object_keys", []), list) else []
        reviewed_conflicts = [
            _resolve_long_form_temp_ref(
                temp_refs, "conflicts", value, str(value or "").strip()
            )
            for value in state_lifecycle_review.get("reviewed_conflict_refs", [])
            if str(value or "").strip()
        ] if isinstance(state_lifecycle_review.get("reviewed_conflict_refs", []), list) else []
        reviewed_tasks = [
            _resolve_long_form_temp_ref(
                temp_refs, "tasks", value, str(value or "").strip()
            )
            for value in state_lifecycle_review.get("reviewed_task_refs", [])
            if str(value or "").strip()
        ] if isinstance(state_lifecycle_review.get("reviewed_task_refs", []), list) else []
        chapter["state_lifecycle_review"] = {
            "scope": str(state_lifecycle_review.get("scope", "") or "").strip(),
            "reviewed_object_keys": reviewed_objects,
            "reviewed_conflict_ids": reviewed_conflicts,
            "reviewed_task_ids": reviewed_tasks,
            "notes": str(state_lifecycle_review.get("notes", "") or "").strip(),
        }
        snapshot_after_review = memory.get("state_snapshot", {})
        snapshot_after_review = snapshot_after_review if isinstance(snapshot_after_review, dict) else {}
        reviewed_object_compacts = {_compact_text(value) for value in reviewed_objects}
        reviewed_conflict_ids = set(reviewed_conflicts)
        reviewed_task_ids = set(reviewed_tasks)
        for snapshot_key, is_reviewed in (
            (
                "object_states",
                lambda item: _compact_text(item.get("key", item.get("name", ""))) in reviewed_object_compacts,
            ),
            (
                "active_conflicts",
                lambda item: str(item.get("id", "") or "").strip() in reviewed_conflict_ids,
            ),
            (
                "unresolved_tasks",
                lambda item: str(item.get("id", "") or "").strip() in reviewed_task_ids,
            ),
        ):
            for item in snapshot_after_review.get(snapshot_key, []) if isinstance(snapshot_after_review.get(snapshot_key), list) else []:
                if isinstance(item, dict) and is_reviewed(item):
                    item["last_reviewed_chapter_id"] = str(chapter.get("id", "") or "")
                    item["last_reviewed_chapter_index"] = chapter_index + 1
                    item["last_reviewed_at"] = now_str()

    historical_fact_ids = {
        str(item.get("id", "") or "").strip()
        for item in memory.get("fact_history", [])
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }

    def resolve_event_refs(kind, values):
        resolved = []
        for ref in values if isinstance(values, list) else []:
            ref_text = str(ref or "").strip()
            if not ref_text:
                continue
            if kind in {"characters", "lore", "foreshadows"}:
                item_id = (
                    _resolve_long_form_record_ref(project, kind, ref_text)
                    or _resolve_long_form_temp_ref(temp_refs, kind, ref_text)
                )
            elif kind == "facts":
                item_id = (
                    ref_text
                    if ref_text in fact_by_id or ref_text in historical_fact_ids
                    else _resolve_long_form_temp_ref(temp_refs, "facts", ref_text)
                )
            elif kind in {"objects", "conflicts", "tasks"}:
                item_id = _resolve_long_form_temp_ref(temp_refs, kind, ref_text, ref_text)
            else:
                item_id = ref_text
            if item_id and item_id not in resolved:
                resolved.append(item_id)
        return resolved

    resolved_events = []
    for item in payload.get("long_term_events", []) if isinstance(payload.get("long_term_events"), list) else []:
        if not isinstance(item, dict):
            continue
        storage = item.get("storage", {}) if isinstance(item.get("storage"), dict) else {}
        resolved_events.append({
            "event": str(item.get("event", "") or "").strip(),
            "category": str(item.get("category", "") or "").strip(),
            "evidence": str(item.get("evidence_quote", item.get("evidence", "")) or "").strip(),
            "storage": {
                "fact_ids": resolve_event_refs("facts", storage.get("fact_refs", [])),
                "character_ids": resolve_event_refs("characters", storage.get("character_refs", [])),
                "lore_ids": resolve_event_refs("lore", storage.get("lore_refs", [])),
                "foreshadow_ids": resolve_event_refs("foreshadows", storage.get("foreshadow_refs", [])),
                "object_keys": resolve_event_refs("objects", storage.get("object_keys", [])),
                "conflict_ids": resolve_event_refs("conflicts", storage.get("conflict_refs", [])),
                "task_ids": resolve_event_refs("tasks", storage.get("task_refs", [])),
            },
        })
    chapter["long_term_events"] = _resolve_long_form_stored_temp_refs(resolved_events, temp_refs)
    event_selection_refs = {
        "character_ids": [],
        "lore_ids": [],
        "foreshadow_ids": [],
        "fact_ids": [],
        "object_keys": [],
        "conflict_ids": [],
        "task_ids": [],
    }
    for event in chapter["long_term_events"]:
        storage = event.get("storage", {}) if isinstance(event, dict) else {}
        storage = storage if isinstance(storage, dict) else {}
        for key in event_selection_refs:
            for value in storage.get(key, []) if isinstance(storage.get(key), list) else []:
                ref = str(value or "").strip()
                if ref and ref not in event_selection_refs[key]:
                    event_selection_refs[key].append(ref)

    reconciliation = payload.get("state_reconciliation", {})
    if isinstance(reconciliation, dict):
        resolved_reconciliation = deepcopy(reconciliation)
        for source_key, output_key, kind in (
            ("fact_refs", "fact_ids", "facts"),
            ("character_refs", "character_ids", "characters"),
            ("lore_refs", "lore_ids", "lore"),
            ("foreshadow_refs", "foreshadow_ids", "foreshadows"),
            ("object_keys", "object_keys", "objects"),
            ("conflict_refs", "conflict_ids", "conflicts"),
            ("task_refs", "task_ids", "tasks"),
        ):
            resolved_reconciliation[output_key] = resolve_event_refs(
                kind, reconciliation.get(source_key, [])
            )
            if output_key != source_key:
                resolved_reconciliation.pop(source_key, None)
        relationship_ids = []
        for value in reconciliation.get("relationship_refs", []) if isinstance(reconciliation.get("relationship_refs"), list) else []:
            refs = value if isinstance(value, list) else str(value or "").split("|")
            ids = resolve_event_refs("characters", refs)
            if len(ids) >= 2:
                relationship_ids.append(ids)
        resolved_reconciliation["relationship_ids"] = relationship_ids
        resolved_reconciliation.pop("relationship_refs", None)
        chapter["state_reconciliation"] = _resolve_long_form_stored_temp_refs(
            resolved_reconciliation, temp_refs
        )
    if isinstance(payload.get("state_delta"), dict):
        chapter["state_delta"] = _resolve_long_form_stored_temp_refs(
            deepcopy(payload.get("state_delta", {})), temp_refs
        )

    current_refs = payload.get("current_chapter_character_refs", [])
    current_ids = []
    for ref in current_refs if isinstance(current_refs, list) else []:
        item_id = _resolve_long_form_record_ref(project, "characters", ref) or _resolve_long_form_temp_ref(temp_refs, "characters", ref)
        if item_id and item_id not in current_ids:
            current_ids.append(item_id)
    character_names = {
        str(item.get("id", "") or "").strip(): str(item.get("name", "") or "").strip()
        for item in project.get("characters", []) if isinstance(item, dict)
    }
    chapter["actual_linked_character_ids"] = current_ids
    chapter["linked_characters"] = _normalize_name_list([character_names.get(item_id, "") for item_id in current_ids])

    archive = payload.get("stage_archive")
    if isinstance(archive, dict) and archive:
        archives = memory.setdefault("stage_archives", [])
        existing = next((item for item in archives if isinstance(item, dict) and int(item.get("end_chapter_index", 0) or 0) == chapter_index + 1), None)
        if existing is None:
            normalized_archive = {
                "id": _next_prefixed_id(archives, "SA"),
                "start_chapter_index": max(1, chapter_index - 8),
                "end_chapter_id": str(chapter.get("id", "") or ""),
                "end_chapter_index": chapter_index + 1,
                "summary": str(archive.get("summary", "") or "").strip(),
                "irreversible_facts": deepcopy(archive.get("irreversible_facts", [])) if isinstance(archive.get("irreversible_facts"), list) else [],
                "relationship_changes": deepcopy(archive.get("relationship_changes", [])) if isinstance(archive.get("relationship_changes"), list) else [],
                "unresolved_threads": deepcopy(archive.get("unresolved_threads", [])) if isinstance(archive.get("unresolved_threads"), list) else [],
                "next_stage_entry": str(archive.get("next_stage_entry", "") or "").strip(),
                "updated_at": now_str(),
            }
            archives.append(normalized_archive)
            temp_refs["archives"]["CURRENT_STAGE"] = normalized_archive["id"]
        else:
            temp_refs["archives"]["CURRENT_STAGE"] = str(existing.get("id", "") or "")

    next_index = chapter_index + 1
    next_memory = payload.get("next_chapter_memory", {})
    if next_index < len(chapters) and isinstance(next_memory, dict):
        selection = {}
        for output_key, input_key, kind in (
            ("character_ids", "character_refs", "characters"),
            ("lore_ids", "lore_refs", "lore"),
            ("foreshadow_ids", "foreshadow_refs", "foreshadows"),
        ):
            legacy_key = input_key.replace("_refs", "_ids")
            values = next_memory.get(input_key, next_memory.get(legacy_key, []))
            ids = []
            for ref in values if isinstance(values, list) else []:
                item_id = _resolve_long_form_record_ref(project, kind, ref) or _resolve_long_form_temp_ref(temp_refs, kind, ref)
                if item_id and item_id not in ids:
                    ids.append(item_id)
            for item_id in touched_refs[kind]:
                if item_id and item_id not in ids:
                    ids.append(item_id)
            for item_id in event_selection_refs[output_key]:
                if item_id and item_id not in ids:
                    ids.append(item_id)
            selection[output_key] = ids
        fact_values = next_memory.get("fact_refs", next_memory.get("fact_ids", []))
        valid_fact_ids = {str(item.get("id", "") or "") for item in memory.get("active_facts", []) if isinstance(item, dict)}
        selection["fact_ids"] = []
        for ref in fact_values if isinstance(fact_values, list) else []:
            item_id = str(ref or "") if str(ref or "") in valid_fact_ids else _resolve_long_form_temp_ref(temp_refs, "facts", ref)
            if item_id and item_id not in selection["fact_ids"]:
                selection["fact_ids"].append(item_id)
        for item_id in touched_fact_ids:
            if item_id in valid_fact_ids and item_id not in selection["fact_ids"]:
                selection["fact_ids"].append(item_id)
        for item_id in event_selection_refs["fact_ids"]:
            if item_id in valid_fact_ids and item_id not in selection["fact_ids"]:
                selection["fact_ids"].append(item_id)
        archive_values = next_memory.get("stage_archive_refs", next_memory.get("stage_archive_ids", []))
        valid_archive_ids = {str(item.get("id", "") or "") for item in memory.get("stage_archives", []) if isinstance(item, dict)}
        selection["stage_archive_ids"] = []
        for ref in archive_values if isinstance(archive_values, list) else []:
            item_id = str(ref or "") if str(ref or "") in valid_archive_ids else _resolve_long_form_temp_ref(temp_refs, "archives", ref)
            if item_id and item_id not in selection["stage_archive_ids"]:
                selection["stage_archive_ids"].append(item_id)
        current_archive_id = _resolve_long_form_temp_ref(temp_refs, "archives", "CURRENT_STAGE")
        if current_archive_id and current_archive_id not in selection["stage_archive_ids"]:
            selection["stage_archive_ids"].append(current_archive_id)
        active_state_refs = _long_form_existing_state_refs(project, memory)
        object_key_by_compact = active_state_refs["object_key_by_compact"]
        selection["object_keys"] = []
        object_values = next_memory.get("object_keys", [])
        for value in object_values if isinstance(object_values, list) else []:
            resolved_value = _resolve_long_form_temp_ref(
                temp_refs, "objects", value, str(value or "").strip()
            )
            canonical = object_key_by_compact.get(_compact_text(resolved_value), "")
            if canonical and canonical not in selection["object_keys"]:
                selection["object_keys"].append(canonical)
        for value in event_selection_refs["object_keys"]:
            canonical = object_key_by_compact.get(_compact_text(value), "")
            if canonical and canonical not in selection["object_keys"]:
                selection["object_keys"].append(canonical)
        state_patch = payload.get("state_patch", {})
        state_patch = state_patch if isinstance(state_patch, dict) else {}
        for item in state_patch.get("object_states", []) if isinstance(state_patch.get("object_states"), list) else []:
            if not isinstance(item, dict):
                continue
            requested_key = str(item.get("key", item.get("name", "")) or "").strip()
            resolved_key = _resolve_long_form_temp_ref(
                temp_refs, "objects", requested_key, requested_key
            )
            canonical = object_key_by_compact.get(
                _compact_text(resolved_key), ""
            )
            if canonical and canonical not in selection["object_keys"]:
                selection["object_keys"].append(canonical)

        for output_key, input_key, legacy_key, temp_kind, active_ids, patch_key in (
            (
                "conflict_ids", "conflict_refs", "conflict_ids", "conflicts",
                active_state_refs["conflict_ids"], "active_conflicts",
            ),
            (
                "task_ids", "task_refs", "task_ids", "tasks",
                active_state_refs["task_ids"], "unresolved_tasks",
            ),
        ):
            selection[output_key] = []
            values = next_memory.get(input_key, next_memory.get(legacy_key, []))
            for value in values if isinstance(values, list) else []:
                ref = str(value or "").strip()
                item_id = _resolve_long_form_temp_ref(temp_refs, temp_kind, ref, ref)
                if item_id in active_ids and item_id not in selection[output_key]:
                    selection[output_key].append(item_id)
            for item_id in event_selection_refs[output_key]:
                if item_id in active_ids and item_id not in selection[output_key]:
                    selection[output_key].append(item_id)
            for item in state_patch.get(patch_key, []) if isinstance(state_patch.get(patch_key), list) else []:
                if not isinstance(item, dict):
                    continue
                ref = str(item.get("id", "") or item.get("key", "") or "").strip()
                item_id = _resolve_long_form_temp_ref(temp_refs, temp_kind, ref, ref)
                if item_id in active_ids and item_id not in selection[output_key]:
                    selection[output_key].append(item_id)
        selection["_restrict_state"] = True
        selection["source_chapter_id"] = str(chapter.get("id", "") or "")
        selection["reason"] = str(next_memory.get("reason", "") or "").strip()
        selection["updated_at"] = now_str()
        chapters[next_index]["memory_selection"] = selection

    revision_after = revision_before + 1
    memory["schema_version"] = "2"
    memory["revision"] = revision_after
    memory["updated_at"] = now_str()
    memory.setdefault("update_journal", []).append({
        "chapter_id": str(chapter.get("id", "") or ""),
        "chapter_index": chapter_index + 1,
        "revision_before": revision_before,
        "revision_after": revision_after,
        "update_hash": update_hash,
        "applied_at": now_str(),
    })
    memory["update_journal"] = memory["update_journal"][-500:]
    project["long_form_memory"] = memory
    chapter["memory_sync_status"] = "complete"
    chapter["memory_revision"] = revision_after
    chapter["memory_update_hash"] = update_hash
    chapter["memory_sync_error"] = ""
    return True


def _apply_long_form_memory_update(project, chapter_index, update):
    if not isinstance(project, dict) or not isinstance(update, dict) or not update:
        return False
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    if chapter_index < 0 or chapter_index >= len(chapters) or not isinstance(chapters[chapter_index], dict):
        return False
    payload = _normalize_long_form_structural_refs(project, chapter_index, update)
    update_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    chapter = chapters[chapter_index]
    if (
        str(chapter.get("memory_sync_status", "") or "") == "complete"
        and str(chapter.get("memory_update_hash", "") or "") == update_hash
    ):
        return True
    require_revision = "base_revision" in payload
    errors = _validate_long_form_memory_update(
        project,
        chapter_index,
        payload,
        require_revision=require_revision,
        require_evidence=False,
    )
    if errors:
        chapter["memory_sync_status"] = "failed"
        chapter["memory_sync_error"] = "；".join(errors)[:1000]
        return False
    working = deepcopy(project)
    stage_boundary = (chapter_index + 1) % 10 == 0
    before_memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
    try:
        _apply_long_form_memory_update_unchecked(working, chapter_index, payload, update_hash)
        if stage_boundary:
            after_memory = _normalize_long_form_memory(
                working.get("long_form_memory", {})
            )
            integrity = _long_form_boundary_integrity(
                working,
                chapter_index,
                before_memory,
                after_memory,
                payload,
            )
            if not integrity.get("verified"):
                raise ValueError("十章边界未触及状态继承核验失败")
            working_chapter = working["chapters"][chapter_index]
            integrity["verified_at"] = now_str()
            working_chapter["memory_boundary_integrity"] = integrity
            for archive in reversed(after_memory.get("stage_archives", [])):
                if not isinstance(archive, dict):
                    continue
                if int(archive.get("end_chapter_index", 0) or 0) == chapter_index + 1:
                    archive["catalog_integrity"] = deepcopy(integrity)
                    break
            working["long_form_memory"] = after_memory
    except Exception as exc:
        chapter["memory_sync_status"] = "failed"
        chapter["memory_sync_error"] = (
            "十章边界未触及状态继承核验失败"
            if "继承核验失败" in str(exc) else
            "长篇记忆事务应用失败"
        )
        return False
    project.clear()
    project.update(working)
    return True


def _build_chapter_ai_context(project, chapter_index, action):
    project = _project_without_private_notes(project)
    _ensure_foreshadow_codes(project)
    chapters = project.get("chapters", [])
    if chapter_index < 0 or chapter_index >= len(chapters):
        raise ValueError("请先选择一个章节。")
    meta = project.get("meta", {})
    chap = chapters[chapter_index]
    raw_chapter_outline = str(chap.get("outline", "") or "")
    chapter_outline_for_context = (
        _strip_static_foreshadow_outline_fields(raw_chapter_outline)
        if action == "draft" else raw_chapter_outline
    )
    linked_characters = chap.get("linked_characters", [])
    if not isinstance(linked_characters, list):
        linked_characters = []
    planned_linked_characters = _normalize_name_list(linked_characters)
    memory_selection = chap.get("memory_selection", {}) if isinstance(chap.get("memory_selection"), dict) else {}
    selected_character_id_list = _normalize_name_list(memory_selection.get("character_ids", []))
    selected_character_ids = set(selected_character_id_list)
    character_names_by_id = {
        str(item.get("id", "") or "").strip(): str(item.get("name", "") or "").strip()
        for item in project.get("characters", []) if isinstance(item, dict)
    }
    ai_selected_character_names = _normalize_name_list(
        [character_names_by_id.get(item_id, "") for item_id in selected_character_id_list]
    )
    linked_names_for_context = ai_selected_character_names if selected_character_ids else planned_linked_characters
    recent_context_text, recent_linked_characters = _recent_chapter_context(chapters, chapter_index, window=6, project=project)
    chapter_match_text = "\n".join([
        str(chap.get("title", "") or ""),
        chapter_outline_for_context,
        str(chap.get("text", "") or ""),
        str(chap.get("summary", "") or ""),
        str(chap.get("key_facts", "") or ""),
        recent_context_text,
        " ".join(str(name) for name in linked_names_for_context),
        " ".join(str(name) for name in recent_linked_characters),
    ])
    inferred_current_characters = (
        [] if selected_character_ids else _infer_linked_character_names(project, chap, chapter_match_text)
    )
    inherited_linked_characters = (
        ai_selected_character_names
        if selected_character_ids else
        _normalize_name_list(list(planned_linked_characters) + inferred_current_characters + recent_linked_characters)
    )
    selected_lore_ids = {
        str(value or "").strip() for value in memory_selection.get("lore_ids", []) if str(value or "").strip()
    }
    selected_foreshadow_ids = {
        str(value or "").strip() for value in memory_selection.get("foreshadow_ids", []) if str(value or "").strip()
    }

    def clean_context_text(value, limit, keep_tail=False, dedupe=True):
        text = _dedupe_text_lines(value) if dedupe else str(value or "").strip()
        return _clip_complete_text(text, limit, keep_tail=keep_tail)

    story_layer_actions = {
        "draft", "outline", "summary", "script_to_novel", "novel_to_script",
        "novel_to_storyboard", "script_to_storyboard",
    }
    expose_author_secrets = action not in story_layer_actions
    current_outline_match_text = "\n".join([
        str(chap.get("title", "") or ""),
        chapter_outline_for_context,
    ])
    runtime_project = _chapter_memory_view(project, chapter_index)

    if selected_character_ids:
        selected_characters = [
            item for item in project.get("characters", [])
            if isinstance(item, dict) and str(item.get("id", "") or "").strip() in selected_character_ids
        ]
    else:
        selected_characters = _prioritize_named_records(
            project.get("characters", []),
            chapter_match_text,
            linked_names=inherited_linked_characters,
            limit=36,
        )
    # Older chapter links may contain a title/alias (for example “当年杂役”)
    # instead of the canonical record ID.  Add only records that match the
    # chapter text or an explicitly linked alias.
    selected_character_ids_found = {
        str(item.get("id", "") or "").strip()
        for item in selected_characters if isinstance(item, dict)
    }
    linked_keys = {_compact_text(name) for name in inherited_linked_characters}
    for item in project.get("characters", []) if isinstance(project.get("characters"), list) else []:
        if not isinstance(item, dict):
            continue
        aliases = _record_aliases(item)
        matched = any(
            _name_in_text(alias, chapter_match_text)
            or any(
                _compact_text(alias) in linked_name or linked_name in _compact_text(alias)
                for linked_name in linked_keys if len(linked_name) >= 2 and len(_compact_text(alias)) >= 2
            )
            for alias in aliases
        )
        item_id = str(item.get("id", "") or "").strip()
        if matched and item_id and item_id not in selected_character_ids_found:
            selected_characters.append(item)
            selected_character_ids_found.add(item_id)
    selected_characters = selected_characters[:36]
    character_recent_map = _record_recent_context_map(project, selected_characters, chapter_index)
    character_lines = []
    for char in selected_characters:
        name = str(char.get("name", "") or "").strip()
        if not name:
            continue
        fields = [
            ("身份", "role", 120),
            ("目标", "goal", 180),
            ("语言", "voice", 180),
            ("备注", "notes", 220),
        ]
        if expose_author_secrets:
            fields.insert(2, ("秘密", "secret", 160))
        detail_parts = []
        for label, field, limit in fields:
            value = char.get(field, "")
            if field == "notes":
                value = _stable_character_notes_context(value)
            value = clean_context_text(value, limit)
            if value:
                detail_parts.append(f"{label}：{value}")
        detail = "｜".join(detail_parts)
        recent_state = character_recent_map.get(_compact_text(name), "")
        if recent_state:
            recent_state = "最近状态：" + clean_context_text(recent_state, 520)
            detail = f"{detail}｜{recent_state}" if detail else recent_state
        runtime_state = _record_runtime_context(runtime_project, "characters", char.get("id", ""), 700)
        if runtime_state:
            detail = f"{detail}｜{runtime_state}" if detail else runtime_state
        character_lines.append(f"- {name}｜{detail}" if detail else f"- {name}")

    if selected_lore_ids:
        selected_lore = [
            item for item in project.get("lore", [])
            if isinstance(item, dict) and str(item.get("id", "") or "").strip() in selected_lore_ids
        ]
    else:
        selected_lore = _prioritize_named_records(
            project.get("lore", []),
            chapter_match_text,
            name_key="name",
            limit=45,
        )
    # Imported settings often keep their evidence in story_known.  Pull in a
    # matching setting by name or concrete scene keyword without loading the
    # entire setting catalogue.
    selected_lore_ids_found = {
        str(item.get("id", "") or "").strip()
        for item in selected_lore if isinstance(item, dict)
    }
    for item in project.get("lore", []) if isinstance(project.get("lore"), list) else []:
        if not isinstance(item, dict):
            continue
        source_text = "\n".join(
            str(item.get(key, "") or "") for key in ("name", "description", "story_known")
        )
        aliases = _record_aliases(item, name_key="name")
        matched = any(_name_in_text(alias, chapter_match_text) for alias in aliases)
        matched = matched or any(
            term in chapter_match_text and term in source_text
            for term in _CONTINUITY_KEYWORDS
        )
        item_id = str(item.get("id", "") or "").strip()
        if matched and item_id and item_id not in selected_lore_ids_found:
            selected_lore.insert(0, item)
            selected_lore_ids_found.add(item_id)
    selected_lore = selected_lore[:45]
    lore_recent_map = _record_recent_context_map(project, selected_lore, chapter_index, name_key="name")
    lore_lines = []
    for item in selected_lore:
        name = str(item.get("name", "") or "").strip()
        if name:
            recent_state = lore_recent_map.get(_compact_text(name), "")
            recent_tail = f"｜最近状态：{clean_context_text(recent_state, 420)}" if recent_state else ""
            story_layer = _record_story_layer_context(project, "lore", item.get("id", ""))
            story_known = str(
                item.get("story_known", "") or story_layer.get("story_known", "") or ""
            ).strip()
            desc_source = item.get("description", "") if expose_author_secrets else story_known
            desc = clean_context_text(_stable_lore_description_context(desc_source), 300)
            desc_tail = f"｜{desc}" if desc else ""
            runtime_state = _record_runtime_context(runtime_project, "lore", item.get("id", ""), 520)
            runtime_tail = f"｜{runtime_state}" if runtime_state else ""
            lore_lines.append(f"- {name}｜{item.get('type','其他')}{desc_tail}{recent_tail}{runtime_tail}")

    def foreshadow_score(item):
        status = str(item.get("status", "") or "").strip()
        score = 0
        score += _chapter_reference_score(item.get("setup_chapter", ""), chapter_index, chap.get("title", ""))
        score += _chapter_reference_score(item.get("payoff_chapter", ""), chapter_index, chap.get("title", ""))
        aliases = _record_aliases(item, name_key="name")
        if aliases and any(_name_in_text(alias, chapter_match_text) for alias in aliases):
            if any(keyword in chapter_match_text for keyword in ("回收", "揭晓", "揭示", "兑现", "解开", "真相大白")):
                score += 260
            elif any(keyword in chapter_match_text for keyword in ("埋下", "埋设", "铺垫", "线索出现", "发现")):
                score += 140
        if status in {"未埋", "已埋"}:
            score += 80
        if status in {"已回收", "无需回收", "废弃"}:
            score -= 20
        return score

    if selected_foreshadow_ids:
        selected_foreshadows = [
            item for item in project.get("foreshadow_items", [])
            if isinstance(item, dict) and str(item.get("id", "") or "").strip() in selected_foreshadow_ids
        ]
    else:
        selected_foreshadows = _prioritize_named_records(
            project.get("foreshadow_items", []),
            chapter_match_text,
            name_key="name",
            limit=30,
            score_func=foreshadow_score,
            min_score=100,
        )
    foreshadow_lines = []
    for item in selected_foreshadows:
        name = str(item.get("name", "") or "").strip()
        if not name:
            continue
        code = _normalize_foreshadow_code(item.get("code", ""))
        head = f"{code}｜{name}" if code else name
        aliases = _record_aliases(item, name_key="name")
        mentioned_now = any(_name_in_text(alias, current_outline_match_text) for alias in aliases)
        payoff_due = bool(_chapter_reference_score(
            item.get("payoff_chapter", ""), chapter_index, chap.get("title", "")
        ))
        payoff_words = ("回收", "揭晓", "揭示", "兑现", "解开", "真相大白")
        allow_author_plan = bool(
            expose_author_secrets
            or payoff_due
            or (
                mentioned_now
                and any(word in current_outline_match_text for word in payoff_words)
            )
        )
        story_layer = _record_story_layer_context(project, "foreshadows", item.get("id", ""))
        revealed = str(item.get("revealed", "") or story_layer.get("revealed", "") or "").strip()
        remaining_secret = str(
            item.get("remaining_secret", "") or story_layer.get("remaining_secret", "") or ""
        ).strip()
        desc_source = item.get("description", "") if allow_author_plan else revealed
        desc = clean_context_text(_stable_foreshadow_description_context(desc_source), 300)
        desc_tail = f"｜{desc}" if desc else ""
        remaining_tail = (
            f"｜仍未揭示边界：{clean_context_text(remaining_secret, 180)}"
            if expose_author_secrets and remaining_secret else ""
        )
        runtime_state = _record_runtime_context(runtime_project, "foreshadows", item.get("id", ""), 520)
        runtime_tail = f"｜{runtime_state}" if runtime_state else ""
        foreshadow_lines.append(
            f"- {head}｜{item.get('status','')}｜埋设：{item.get('setup_chapter','')}｜回收：{item.get('payoff_chapter','')}"
            f"{desc_tail}{remaining_tail}{runtime_tail}"
        )
    previous_summary = _build_previous_inheritance_text(
        chapters,
        chapter_index,
        compact_for_draft=action == "draft",
    )
    continuation_text = _build_chapter_continuation_text(chapters, chapter_index)
    next_chapter_anchor_text = _build_next_chapter_anchor_text(chapters, chapter_index)
    future_plan_text = _build_future_plan_text(chapters, chapter_index)
    volume_opening_handoff = str(
        project.get("volume_opening_handoff_context", "") or ""
    ).strip()
    has_current_text = bool(_compact_text(chap.get("text", "")))
    reverse_from_body = action in {"outline", "summary"} and has_current_text
    draft_words_label = _draft_words_label(chap.get("draft_words", ""))
    draft_words_target = _draft_words_value(chap.get("draft_words", ""))
    current_body_len = _text_len(chap.get("text", ""))
    draft_words_remaining = _draft_words_remaining(chap.get("draft_words", ""), chap.get("text", ""))
    draft_words_remaining_label = f"{draft_words_remaining}字" if draft_words_remaining else ""
    style_reference = str(project.get("style_reference", "") or "").strip()
    stage_boundary = (chapter_index + 1) % 10 == 0
    no_text_count_rule = (
        "能不用“几个字/几个词/几个音节”就不用；真要写字数，标点符号、引号和空格都不计入字数。"
    )
    draft_task = (
        "请根据当前章节的章节提纲和已有正文草稿续写正文。正文草稿已有内容时，只输出可以直接接在草稿末尾的新正文，"
        "不要重复、概括或改写已有正文；开头要优先承接【续写承接点】里的当前正文结尾原文，"
        "当前草稿结尾已经写出的句子、动作和结论也不能再次原样或同义重写。"
        "章节提纲中的核心方向、已发生事实和承接点优先；历史规划元数据只作参考，不要逐项执行、解释或扩展成任务清单。"
        "旧提纲中若残留固定伏笔编号、伏笔任务或伏笔动作，只作历史文本参考，不能当作本章硬任务；"
        "伏笔推进与回收以动态伏笔调度参考和正文自然性为准。"
        "必须继承承接点里的时间、天气、地点、人物位置、情绪和未完成动作；如果上一章写明雨已停或场景已变化，"
        "不要在下一章开头改成仍在下雨或回到旧场景，除非本章提纲明确发生了新的天气/场景变化。"
        "优先参考本章需继承的关键事实，其次参考本章摘要、前文摘要、人物目标、语言风格和世界规则。"
        "正文风格：口语化、自然、有网文阅读感，不要太工整、太书面、太像范文。"
        "句子长短混用，允许短句、停顿、反问和不完全对称的表达。"
        "少用排比、四字词堆叠、抽象情绪词和模板化反应。"
        "人物情绪优先通过对白、具体动作和选择体现。保持剧情高密度推进，但不要写成流水账。"
        "去 AI 味要求：少写段尾总结、抽象情绪判断和万能反应动作；"
        "不要频繁使用“沉默、皱眉、冷意、压迫感、空气安静、所有人愣住、下一秒”等模板化表达。"
        "对白要有真人说话的不完整感，可以短句、停顿、反问、打断。"
        "场景描写优先用具体物件、动作和细节承载情绪，不要总用氛围词概括。"
        "人物心理不要解释过满，能让读者从动作和对白看懂的，就不要再总结一遍。"
        "少用解释型旁白，不要频繁替人物总结动机、立场和成长。"
        "少写金句式、总结式、标语式句子，不要刻意拔高主题；章节结尾优先用具体动作、对白、信息变化或悬念收住。"
        "段落结构要有变化，不要连续使用“动作描写 + 心理解释 + 氛围总结”的固定结构。"
        "对白不要每句都完整、漂亮、逻辑闭合；不同人物说话要有信息差、情绪偏差和表达习惯，可以含糊、逃避、反问或只说半句。"
        "场景细节要克制：只在能强化冲突、人物状态或信息变化时，少量加入具体物件、声音、动作痕迹和环境反馈。"
        "不要写无意义生活噪声，不要让细节拖慢剧情。"
        "写每一场时优先让人物在具体环境里做事、被打断、受阻、临时反应，不要只用旁白解释情绪和局势。"
        "参考【本章写作长度】安排详略，但不要为了贴字数牺牲完整场景、冲突收束和正文质量；只输出正文内容。"
        if has_current_text else
        "请根据当前章节的章节提纲生成正文草稿。若有上一章结尾，开篇必须自然承接上一章的状态，"
        "但上一章结尾原文已经发布，不能原样或同义重写末句、对白、声音、动作落点、结论或情绪；"
        "必须从对白后的新反应/回答、动作后的新结果/阻力、声音后的声源/新反应中选择一种起笔，"
        "并让第一段出现新动作、新信息、新决定、新后果或必要情绪转折。"
        "章节提纲中的核心方向、已发生事实和承接点优先；历史规划元数据只作参考，不要逐项执行、解释或扩展成任务清单。"
        "旧提纲中若残留固定伏笔编号、伏笔任务或伏笔动作，只作历史文本参考，不能当作本章硬任务；"
        "伏笔推进与回收以动态伏笔调度参考和正文自然性为准。"
        "必须继承上一章结尾的时间、天气、地点、人物位置、情绪和未完成动作；如果上一章写明雨已停或场景已变化，"
        "不要在本章开头改成仍在下雨或回到旧场景，除非本章提纲明确发生了新的天气/场景变化。"
        "如果有【后章衔接点】，本章结尾必须自然接到下一章开头的时间、地点、人物状态、动作和悬念；"
        "后章衔接点只用于对齐当前章结尾，不要复述、改写或提前写完下一章正文。"
        "优先参考本章需继承的关键事实，其次参考本章摘要、前文摘要、人物目标、语言风格和世界规则。"
        "正文风格：口语化、自然、有网文阅读感，不要太工整、太书面、太像范文。"
        "句子长短混用，允许短句、停顿、反问和不完全对称的表达。"
        "少用排比、四字词堆叠、抽象情绪词和模板化反应。"
        "人物情绪优先通过对白、具体动作和选择体现。保持剧情高密度推进，但不要写成流水账。"
        "去 AI 味要求：少写段尾总结、抽象情绪判断和万能反应动作；"
        "不要频繁使用“沉默、皱眉、冷意、压迫感、空气安静、所有人愣住、下一秒”等模板化表达。"
        "对白要有真人说话的不完整感，可以短句、停顿、反问、打断。"
        "场景描写优先用具体物件、动作和细节承载情绪，不要总用氛围词概括。"
        "人物心理不要解释过满，能让读者从动作和对白看懂的，就不要再总结一遍。"
        "少用解释型旁白，不要频繁替人物总结动机、立场和成长。"
        "少写金句式、总结式、标语式句子，不要刻意拔高主题；章节结尾优先用具体动作、对白、信息变化或悬念收住。"
        "段落结构要有变化，不要连续使用“动作描写 + 心理解释 + 氛围总结”的固定结构。"
        "对白不要每句都完整、漂亮、逻辑闭合；不同人物说话要有信息差、情绪偏差和表达习惯，可以含糊、逃避、反问或只说半句。"
        "场景细节要克制：只在能强化冲突、人物状态或信息变化时，少量加入具体物件、声音、动作痕迹和环境反馈。"
        "不要写无意义生活噪声，不要让细节拖慢剧情。"
        "写每一场时优先让人物在具体环境里做事、被打断、受阻、临时反应，不要只用旁白解释情绪和局势。"
        "参考【本章写作长度】安排详略，但不要为了贴字数牺牲完整场景、冲突收束和正文质量；只输出正文内容。"
    )
    if style_reference:
        draft_task = (
            (
                "请根据当前章节提纲和已有正文草稿续写正文。已有正文时，只输出可以直接接在草稿末尾的新正文，"
                "开头承接【续写承接点】里的最后状态。"
                if has_current_text else
                "请根据当前章节提纲生成完整正文草稿；若有上一章结尾，开篇承接其最后状态，并从当前状态自然发展出新的反应、结果、阻力、选择或信息。"
            )
            + "当前项目资料决定故事事实。提纲、已发布正文、状态快照和连续性资料里已经明确写出的专名、日期、时刻、地点、房间号、"
            "物件编号、金额、关系称谓、人物位置、身体状态、持有物品、已发生事件和未完成动作，都是本章需要延续的事实。"
            "以【仿写使用说明】和【正文风格参考】中的完整原样本作为写法来源，让当前人物和当前事件自然长出相同作者的叙述、对白和情绪组织。"
            "参考【本章写作长度】安排内容总量，输出可直接进入小说的正文。"
        )
    draft_task += no_text_count_rule
    task_map = {
        "outline": (
            "请为当前章节生成章节提纲。当前章节已有正文草稿时，必须以正文草稿为唯一事实来源，"
            "反向提炼已经写出来的剧情拍点；不要根据原提纲、后续规划或世界设定补写正文没发生的收尾、反转或伏笔兑现。"
            "正文草稿为空时，才参考项目基础、小说圣经、世界观、人物卡、设定库和前文摘要来生成预写提纲。"
            "只输出短提纲，不要输出正文、对白或长段场景描写。"
            "控制在 6-10 条以内，每条 1-2 句，总长度尽量控制在 600-1200 字。"
        ),
        "draft": draft_task,
        "summary": (
            "请根据当前章节正文草稿提炼本章摘要与本章需继承的关键事实；章节提纲只作辅助，正文没有写到的内容不要写入摘要或关键事实。"
            "摘要用于简短记录发生了什么；关键事实只记录后续必须继承的事实，"
            "包括人物关系、线索、伏笔、伤势、物品、地点变化、情绪关系变化，以及章节结尾的时间、天气、地点、人物位置和未完成动作。"
            "如果正文收尾写明雨停、雨后、天亮、转场、离开、抵达、昏迷、受伤、持有/交出物品等状态，必须写入关键事实。"
            "不要评价，不要写创作建议。"
            "本章需继承的关键事实要写成连续性备忘录，不写剧情复述；同一件事的背景、判断、结果尽量合并成一条完整事实。"
            "删掉过程描写、氛围描述、重复解释和无后续影响的临时动作；不设固定条数，不因为压缩或固定条数删掉会影响后文连续性的变化。"
            "目标是事实完整、表达短。"
            "同时以【当前状态快照】为上一章结束状态，只返回本章新增、变化或明确退出的状态增量。"
            "必须只输出一个合法JSON对象，不要Markdown或额外说明，顶层结构为："
            '{"summary":"本章摘要","key_facts":["后续必须继承的事实"],'
            '"linked_characters":["实际出现或被直接推动的具体人物名"],"long_form_memory":{...}}。'
            "long_form_memory严格执行以下版本2契约："
            + _long_form_update_contract_instructions(project, chapter_index, compact=True)
        ),
        "script_to_novel": (
            "请把当前章节/分集里的剧本内容改编成小说正文。"
            "保留原剧情顺序、人物关系、关键对白和情绪推进；把场景说明、动作说明、对白转化为自然的小说叙事。"
            "不要写分镜号、角色名冒号式对白、镜头术语或创作建议；只输出可直接放入正文的小说内容。"
        ),
        "novel_to_script": (
            "请把当前章节的小说正文改编成剧本。"
            "按场景拆分，包含场景标题、人物、动作说明和对白；保留核心剧情、冲突、人物关系和关键信息。"
            "对白要适合拍摄和表演；不要输出小说叙述腔，不要写创作建议。"
        ),
        "novel_to_storyboard": (
            "请把当前章节的小说正文改编成分镜脚本。"
            "按镜号输出，每个镜头包含：镜号、景别、画面内容、人物动作、镜头运动、对白/旁白、音效/音乐、时长建议。"
            "保留剧情逻辑和关键情绪，不要省略重要转折；不要写创作建议。"
        ),
        "script_to_storyboard": (
            "请把当前章节/分集里的剧本内容改编成分镜脚本。"
            "按镜号输出，每个镜头包含：镜号、景别、画面内容、人物动作、镜头运动、对白/旁白、音效/音乐、时长建议。"
            "严格继承原剧本的场景、对白、动作和节奏；不要写创作建议。"
        ),
    }
    task_text = task_map.get(action, str(action or "").strip() or "请根据当前资料完成本章写作任务。")

    inheritance_rule_lines = [
        "写长篇时请把资料当成连续故事档案。",
        "继承优先级：本章需继承的关键事实 > 当前状态快照/活跃连续性事实 > 前文继承摘要 > 人物卡 > 小说圣经/世界规则 > 设定库。",
        "章节提纲是创作计划，不等同于已经发生的事实；如与已确认正文事实冲突，保留本章剧情目标，并按已确认时间顺序、人物视角和物件状态自然调整细节。",
        "不得改写已发生事实；如果资料冲突，优先保留更具体、更新、更接近当前章节的记录。",
        "续写时要继承人物公开目标、故事内已知动机、称呼和语言风格，以及伤势、物品、地点、关系和情绪变化。",
        "跨章开头必须继承上一章结尾状态：时间、天气、地点、人物位置、人物手中物品、身体状态和未完成动作不能凭空回退。",
        "上一章结尾原文已经发布，不能把末句、对白、声音、动作落点、结论或情绪再次原样或同义写出；"
        "下一章必须从新反应、新结果、新阻力或新信息开始，不能让同一触发句同时作为上一章结尾和下一章开头。",
        "状态快照、活跃事实、人物卡、设定和伏笔用于静默保证连续性；未在本章发生变化的旧信息不是正文任务，"
        "不得为了证明记住资料而让旁白或人物重新解释。只有新证据、新决定、新后果或当前行动确实依赖时才简短引用。",
        "伏笔只在合适章节推进；已回收/无需回收/废弃伏笔不要重复当新线索。缺资料时保持克制，不要补出会影响后文的新设定。",
        "人物秘密、伏笔完整答案和未解锁的设定属于作者层；正文只能使用本上下文已显示的故事内已知内容和当章允许推进的边界。",
    ]
    if reverse_from_body:
        inheritance_rule_lines.append("本次是正文后的资料回填：提纲、摘要和关键事实都只能记录正文草稿中已经发生的内容，不要补写后续规划。")
    else:
        inheritance_rule_lines.append(
            "后续章节提纲和人物名单来自初始框架规划，只是可调整的方向与边界，不是已发生事实或强制出场名单；"
            "当前章可以自然铺垫下一章，但不要提前兑现后续章节安排的真相、转折或结局。"
        )
    inheritance_rules = "\n".join(inheritance_rule_lines)

    current_text_limit = 30000 if action in {"outline", "summary"} else 18000
    draft_words_line = draft_words_label if draft_words_label else "未填写"
    current_lines = [
        f"章节标题：{chap.get('title', '')}",
        f"章节状态：{chap.get('status', '')}",
        f"本章扩写字数：{draft_words_line}",
        f"本章有效关联人物：{', '.join(inherited_linked_characters)}",
    ]
    if selected_character_ids and planned_linked_characters:
        current_lines.append(
            "初始章节规划人物（仅弱参考，不要求全部出场，也不得覆盖AI按实写状态生成的本章人物清单）："
            + ", ".join(planned_linked_characters)
        )
    if reverse_from_body:
        current_lines.append("章节提纲：已省略；本次必须仅根据正文草稿反向整理，避免旧提纲或后续规划影响结果。")
    else:
        current_lines.append(f"章节提纲：{clean_context_text(chapter_outline_for_context, 6000)}")
        current_lines.append(
            "明确事实锁定：章节提纲、已有正文、状态快照与连续性资料中已明确写出的专名、日期、时刻、地点、"
            "房间号、物件编号、金额、关系称谓和条件，正文涉及到时必须逐字继承；未明确具体值的内容才可自然补足。"
        )
    current_lines.append(f"正文草稿：{_clip_context_text(chap.get('text', ''), current_text_limit, keep_tail=True)}")
    if reverse_from_body:
        current_lines.extend([
            "本章摘要：已省略；本次必须仅根据正文草稿重新提炼。",
            "本章需继承的关键事实：已省略；本次必须仅根据正文草稿重新提炼。",
        ])
    else:
        current_lines.extend([
            f"本章摘要：{clean_context_text(chap.get('summary', ''), 5000)}",
            f"本章需继承的关键事实：{clean_context_text(chap.get('key_facts', ''), 7000)}",
        ])
    current_section = "\n".join(current_lines)
    if draft_words_label:
        remaining_line = (
            f"本次新增正文参考目标：约{draft_words_remaining_label}，用于控制详略和推进密度。"
            if draft_words_remaining else
            "当前正文长度已接近或达到本章扩写字数；如仍需生成，优先补足自然收束或必要承接，不要硬凑字数。"
        )
        chapter_length_section = (
            f"本章扩写字数：{draft_words_label}\n"
            f"当前正文长度：约{current_body_len}字\n"
            f"{remaining_line}\n"
            "这是正文长度控制目标；通常把有效正文保持在目标的85%-115%，连续超出会破坏整书总字数和节奏。\n"
            "本章扩写字数代表本章正文希望补到的大约总量；如果正文草稿已有内容，只输出剩余部分。\n"
            "完整收束确有必要时可以略微超出，但不得用重复解释、重复反应或同义对白扩充篇幅；"
            "也不得为贴字数删掉关键结尾、跳过必要铺垫；"
            "项目总目标字数只用于整本小说规模规划，不要把项目总字数当作单章输出字数。"
        )
    else:
        chapter_length_section = (
            "本章扩写字数：未填写\n"
            "未填写时按章节提纲、已有正文和当前剧情节奏自然扩写，"
            "但仍然只写当前章节需要的正文，不要根据项目总目标字数一次性写满。"
        )
    recent_context_section = recent_context_text or "暂无"

    def context_parts(*parts):
        return "\n\n".join(_dedupe_text_lines(part) for part in parts if str(part or "").strip()) or "暂无"

    current_story_order = _story_order_from_text(chap.get("title", ""))
    if current_story_order == _STORY_ORDER_MISSING:
        current_story_order = chapter_index + 1
    open_foreshadows = "" if selected_foreshadow_ids else _build_open_foreshadow_queue(
        project,
        selected_foreshadows,
        limit=4500,
        current_order=current_story_order,
        include_desc=action not in story_layer_actions,
    )
    foreshadow_context = context_parts(
        "\n".join(foreshadow_lines),
        open_foreshadows,
    )
    long_form_progress = _long_form_progress_text(project, chapter_index)
    core_project_info = "\n".join([
        f"书名：{meta.get('title', '')}",
        f"类型：{meta.get('genre', '')}",
        f"风格：{meta.get('style', '')}",
        f"叙事人称：{meta.get('pov', '')}",
        f"故事核心：{clean_context_text(meta.get('premise', ''), 2200)}",
    ])
    style_sections = []
    common_sections = [
        ("项目核心信息", core_project_info, 1200, False),
        ("长篇进度 / 节奏", long_form_progress, 1200, False),
        ("长篇继承规则", inheritance_rules, 1500, False),
        ("本次任务", task_text, 6000 if action == "summary" else 2200, False),
        ("项目基础", "\n".join([
            f"项目总目标字数：{_target_words_label(meta.get('target_words', ''))}",
        ]), 500, False),
    ]
    if action == "draft":
        common_sections.insert(
            3,
            (
                "剧情连续性参考",
                _build_chapter_execution_hard_constraints(
                    runtime_project, chapter_index
                ),
                4200,
                False,
            ),
        )
        common_sections.append((
            "终稿长篇记忆回填要求",
            (
                "本区只供后续终稿整理步骤使用，正文草稿阶段不要输出资料。"
                "终稿必须依据最终正文更新完整状态快照、活跃连续性事实和本章状态变化；不得把计划当作已发生事实。"
                + (
                    "当前是固定十章阶段边界，必须同时生成最近十章的阶段档案。"
                    if stage_boundary else
                    "当前不是阶段边界，阶段档案返回null。"
                )
            ),
            800,
            False,
        ))
    if action == "draft":
        common_sections.insert(3, ("本章写作长度", chapter_length_section, 500, False))
        if style_reference:
            style_sections.extend([
                ("仿写使用说明", _build_full_style_imitation_guidance(style_reference), 1200, False),
                ("正文风格参考", style_reference, len(style_reference) + 64, False),
            ])
        # Keep this after the raw sample so direct drafting receives it even
        # when the style-finalize pass is intentionally skipped.
        style_sections.append((
            "正文自然表达边界",
            _natural_expression_guidance(),
            900,
            False,
        ))
    memory_view = runtime_project
    memory_sections = _long_form_memory_sections(memory_view, memory_selection)
    continuity_context = _build_targeted_continuity_context(
        project, chapter_index, chapter_match_text
    )
    if reverse_from_body:
        knowledge_sections = [
            ("小说圣经", _dedupe_text_lines(project.get("bible", "")) or "暂无", 2400, True),
            ("世界观 / 规则", _dedupe_text_lines(project.get("world_rules", "")) or "暂无", 1800, True),
            ("当前状态快照", memory_sections["当前状态快照"], 10000, True),
            ("全局紧凑状态目录", memory_sections["全局紧凑状态目录"], LONG_FORM_STATE_DIRECTORY_LIMIT, False),
            ("活跃连续性事实", memory_sections["活跃连续性事实"], 10000, True),
            ("近期阶段档案", memory_sections["近期阶段档案"], 12000, True),
            ("前文继承摘要", previous_summary, 5000, True),
            ("近几章连续性", recent_context_section, 2600, True),
            ("历史连续性依据", continuity_context, 2600, False),
            ("本章相关人物", "\n".join(character_lines) or "暂无", 4200, False),
            ("本章相关设定", "\n".join(lore_lines) or "暂无", 2800, False),
        ]
    else:
        knowledge_sections = [
            ("小说圣经", _dedupe_text_lines(project.get("bible", "")) or "暂无", 5000, True),
            ("世界观 / 规则", _dedupe_text_lines(project.get("world_rules", "")) or "暂无", 4000, True),
            ("当前状态快照", memory_sections["当前状态快照"], 10000, True),
            ("全局紧凑状态目录", memory_sections["全局紧凑状态目录"], LONG_FORM_STATE_DIRECTORY_LIMIT, False),
            ("活跃连续性事实", memory_sections["活跃连续性事实"], 10000, True),
            ("近期阶段档案", memory_sections["近期阶段档案"], 12000, True),
            ("续写承接点", continuation_text or "暂无", 6000, True),
            ("前文继承摘要", previous_summary, 5000 if action == "draft" else 15000, True),
            ("近几章连续性", recent_context_section, 5000, True),
            ("历史连续性依据", continuity_context, 2600, False),
            ("本章相关人物", "\n".join(character_lines) or "暂无", 10000, False),
            ("本章相关设定", "\n".join(lore_lines) or "暂无", 8000, False),
            ("本章相关伏笔", foreshadow_context, 7000, True),
        ]
    if action == "summary":
        knowledge_sections.insert(
            3,
            (
                "AI资料更新与下一章选择索引",
                _build_long_form_selection_index(project, chapter_index),
                40000,
                False,
            ),
        )
    if action == "draft":
        if chapter_index == 0 and volume_opening_handoff:
            knowledge_sections.insert(
                4,
                ("上一卷卷末承接事实", volume_opening_handoff, 12000, True),
            )
        knowledge_sections.insert(4, ("后续规划参考", future_plan_text, 5000, True))
        if next_chapter_anchor_text:
            knowledge_sections.insert(5, ("后章衔接点", next_chapter_anchor_text, 900, False))
    current_section_item = (
        "当前章节",
        current_section,
        34000 if action == "summary" else 24000,
        True,
    )
    current_first_actions = {
        "outline",
        "draft",
        "summary",
        "script_to_novel",
        "novel_to_script",
        "novel_to_storyboard",
        "script_to_storyboard",
    }
    if action in current_first_actions:
        sections = common_sections + [current_section_item] + knowledge_sections
    else:
        sections = common_sections + knowledge_sections + [current_section_item]
    if style_sections:
        sections = sections + style_sections
    max_context_chars = NOVEL_AI_CONTEXT_LIMIT
    out = []
    used = 0
    seen_context_lines = set()
    # This short trailing guide intentionally repeats the corresponding part
    # of the imitation note so it remains visible after the raw sample.
    raw_context_titles = {"当前章节", "正文风格参考", "正文自然表达边界"}
    style_titles = {title for title, _content, _limit, _keep_tail in style_sections}
    style_reserve = sum(
        min(len(content), limit) + len(title) + 8
        for title, content, limit, _keep_tail in style_sections
    )
    for title, content, limit, keep_tail in sections:
        is_style_section = title in style_titles
        remaining = max_context_chars - used - (0 if is_style_section else style_reserve)
        if remaining <= 1200:
            if is_style_section:
                break
            continue
        section_content = content if title in raw_context_titles else _dedupe_text_lines(content)
        if title not in raw_context_titles:
            unique_lines = []
            for line in str(section_content or "").splitlines():
                key = _compact_text(line)
                if len(key) >= 30 and key in seen_context_lines:
                    continue
                unique_lines.append(line)
                if len(key) >= 30:
                    seen_context_lines.add(key)
            section_content = "\n".join(unique_lines).strip()
        preserve_lines = title not in raw_context_titles
        clipped = _clip_context_text(
            section_content,
            min(limit, remaining - 64),
            keep_tail=keep_tail,
            preserve_lines=preserve_lines,
        ) or "暂无"
        block = f"【{title}】\n{clipped}"
        out.append(block)
        used += len(block) + 2
    return "\n\n".join(out)
