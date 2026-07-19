import os
import re
import uuid
import hashlib
import json
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
        any(k in current for k in ("已埋", "已铺垫", "待回收", "未回收", "待兑现"))
        or status_text in {"open", "active", "buried", "setup"}
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
        "chapter_plan_generation_state": {},
        "import_candidates": {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}},
        "updated_at": now_str(),
    }


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
        for kind in ("conflicts", "tasks"):
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
    "style_profile_cache",
    "chapter_plan_generation_state",
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
            if not profile and not units:
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
                "chapter_function": _as_text(item.get("chapter_function", "")),
                "conflict_intensity": _as_text(item.get("conflict_intensity", "")),
                "setup_ratio": _as_text(item.get("setup_ratio", "")),
                "character_task": _as_text(item.get("character_task", "")),
                "mainline_task": _as_text(item.get("mainline_task", "")),
                "outline": _as_text(item.get("outline", "")),
                "characters": _normalize_name_list(item.get("characters", [])),
                "settings": _normalize_name_list(item.get("settings", [])),
                "ending_hook": _as_text(item.get("ending_hook", "")),
                "forbidden": _as_text(item.get("forbidden", "")),
                "source_event_ids": _normalize_name_list(item.get("source_event_ids", [])),
            }
            if any(str(value or "").strip() for value in chapter.values() if not isinstance(value, list)) or chapter["characters"] or chapter["settings"]:
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
        if version > 0 and status in {"pending", "generating", "failed", "interrupted", "complete"}:
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
            }
            for key in ("started_at", "updated_at", "error"):
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
            char["notes"] = _dedupe_text_lines(char.get("notes", ""))
    lore = data.get("lore", [])
    if isinstance(lore, list):
        base["lore"] = [c for c in lore if isinstance(c, dict)]
        for item in base["lore"]:
            if not str(item.get("id", "") or "").strip():
                item["id"] = uuid.uuid4().hex
            for key in ("id", "name", "type", "description", "story_known"):
                item[key] = _as_text(item.get(key, ""))
            item["description"] = _dedupe_text_lines(item.get("description", ""))
            item["story_known"] = _dedupe_text_lines(item.get("story_known", ""))
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
            item["description"] = _dedupe_text_lines(item.get("description", ""))
            item["revealed"] = _dedupe_text_lines(item.get("revealed", ""))
            item["remaining_secret"] = _dedupe_text_lines(item.get("remaining_secret", ""))
            item["notes"] = _dedupe_text_lines(item.get("notes", ""))
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


def _clip_context_text(value, limit, keep_tail=False, preserve_lines=False):
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
                return _clip_lines_balanced(lines, limit)
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


def _clip_lines_balanced(lines, limit, head=8, tail=10):
    lines = [str(line or "").strip() for line in (lines or []) if str(line or "").strip()]
    limit = int(limit or 0)
    if not lines or limit <= 0:
        return ""
    text = "\n".join(lines)
    if len(text) <= limit:
        return text

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

    while head_index <= tail_index:
        progressed = False
        head_chars = _line_join_length(head_lines)
        tail_chars = _line_join_length(tail_lines)
        prefer_tail = bool(tail_lines) and tail_chars <= head_chars or not head_lines
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

    if not head_lines and not tail_lines:
        return _clip_context_text(text, limit, keep_tail=True)
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
    alias_fields = ("description",) if "description" in item else ("notes",)
    alias_source = "\n".join(str(item.get(key, "") or "") for key in alias_fields)
    alias_labels = (
        "别称", "别名", "又名", "化名", "称呼", "代称", "简称",
        "绰号", "外号", "代号", "真名", "本名", "原名", "曾用名",
        "旧名", "身份名", "马甲", "尊称", "昵称", "通称", "称号",
        "封号", "头衔", "身份称呼",
    )
    alias_pattern = "|".join(re.escape(label) for label in alias_labels)
    for match in re.findall(rf"(?:{alias_pattern})[：:]\s*([^\n。；;]+)", alias_source):
        aliases.extend(_normalize_name_list(match))
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
    sentence_parts = re.split(r"([。！？!?；;：:]\s*)", paragraph)
    for piece in sentence_parts:
        if not piece:
            continue
        candidate = current + piece
        if current and len(candidate) > unit_limit:
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
        while len(unit) > unit_limit:
            refined.append(unit[:unit_limit].strip())
            unit = unit[unit_limit:].strip()
        if unit:
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
                    f"上一章「{title}」结尾原文（重点继承时间、天气、地点、人物位置、情绪和未完成动作）：\n"
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
    dialogue_chars = sum(len(_compact_text(match)) for match in dialogue_matches)
    dialogue_paragraphs = sum(
        1 for paragraph in paragraphs
        if any(mark in paragraph for mark in ("“", "”", "「", "」", "『", "』", '"'))
    )
    paragraph_count = len(paragraphs)
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
        "dialogue_char_pct": dialogue_chars * 100 / total_chars if total_chars else 0.0,
        "dialogue_paragraph_pct": dialogue_paragraphs * 100 / paragraph_count if paragraph_count else 0.0,
    }


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
    if ref_density and not (ref_density * 0.75 <= draft_density <= ref_density * 1.25):
        reasons.append(
            f"段落密度偏差过大：样本每1000字约{ref_density:.1f}段，首次正文约{draft_density:.1f}段"
        )

    ref_median = reference["paragraph_median"]
    draft_median = draft["paragraph_median"]
    if ref_median and not (ref_median * 0.75 <= draft_median <= ref_median * 1.35):
        reasons.append(f"段落长度中位数不符：样本约{ref_median}字，首次正文约{draft_median}字")

    short_gap = draft["short_paragraph_pct"] - reference["short_paragraph_pct"]
    if abs(short_gap) > 10:
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
    if dialogue_gap > 10:
        reasons.append(
            f"对白字数占比不符：样本约{reference['dialogue_char_pct']:.0f}%，"
            f"首次正文约{draft['dialogue_char_pct']:.0f}%"
        )
    return reasons


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


def _style_finalize_acceptance_errors(
    execution_text,
    final_text,
    acceptance,
    style_reference="",
    output_target=0,
):
    body = str(final_text or "").strip()
    beats = _style_execution_beats(execution_text)
    result = acceptance if isinstance(acceptance, dict) else {}
    errors = []
    if beats:
        evidence_items = result.get("beat_evidence", [])
        if not isinstance(evidence_items, list):
            evidence_items = []
        evidence_by_beat = {}
        for item in evidence_items:
            if not isinstance(item, dict):
                continue
            try:
                beat_number = int(item.get("beat", 0) or 0)
            except Exception:
                beat_number = 0
            quote = str(item.get("evidence_quote", "") or "").strip()
            if beat_number and quote and beat_number not in evidence_by_beat:
                evidence_by_beat[beat_number] = quote
        for beat in beats:
            number = beat["beat"]
            quote = evidence_by_beat.get(number, "")
            if not quote:
                errors.append(f"剧情拍点{number}没有终稿证据")
            else:
                quote = _literalize_long_form_evidence_quote(quote, body)
            if quote and (
                len(_compact_text(quote)) < 8
                or not _long_form_evidence_present(quote, body)
            ):
                errors.append(f"剧情拍点{number}的证据不是终稿中8字以上逐字原文")
        if result.get("previous_chapter_repetition_check") is not True:
            errors.append("没有确认已删除非必要的前两章剧情复演")
        if result.get("paragraph_structure_check") is not True:
            errors.append("没有确认终稿段落结构已按样本复核")

    reference = _style_text_structure(style_reference)
    final_structure = _style_text_structure(body)
    if reference["chars"] >= 500 and final_structure["chars"] >= 300:
        ref_density = reference["paragraphs_per_1000"]
        final_density = final_structure["paragraphs_per_1000"]
        if ref_density and not (ref_density * 0.80 <= final_density <= ref_density * 1.20):
            errors.append(
                f"终稿段落密度未贴近样本：样本每1000字{ref_density:.1f}段，终稿{final_density:.1f}段"
            )
        short_gap = final_structure["short_paragraph_pct"] - reference["short_paragraph_pct"]
        if abs(short_gap) > 10:
            paragraph_count = int(final_structure["paragraph_count"] or 0)
            short_count = sum(
                length <= 15 for length in final_structure["paragraph_lengths"]
            )
            allowed_high = min(100.0, reference["short_paragraph_pct"] + 10.0) / 100.0
            merge_count = 0
            while (
                short_gap > 10
                and merge_count < short_count
                and paragraph_count - merge_count > 0
                and (short_count - merge_count) / (paragraph_count - merge_count) > allowed_high
            ):
                merge_count += 1
            merge_hint = (
                f"；至少把{merge_count}个短段并入相邻相关段落"
                if short_gap > 10 and merge_count else ""
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
        if single_short_gap > 12 and reference["single_sentence_short_paragraph_pct"] < 55:
            errors.append(
                "终稿非对白短单句段明显多于样本，普通说明需要合并"
            )
        reference_run = _style_max_short_narrative_run(style_reference)
        final_run = _style_max_short_narrative_run(body)
        if final_run >= 3 and final_run > max(2, reference_run + 1):
            errors.append(
                f"终稿连续非对白短段达到{final_run}段，样本最长约{reference_run}段"
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


def _style_exact_source_excerpt(style_reference, excerpt):
    reference = str(style_reference or "").replace("\r\n", "\n").replace("\r", "\n")
    value = str(excerpt or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not reference or not value:
        return ""
    exact_at = reference.find(value)
    if exact_at >= 0:
        return reference[exact_at:exact_at + len(value)].strip()
    compact_value = _compact_text(value)
    if not compact_value:
        return ""
    compact_chars = []
    source_indexes = []
    for source_index, char in enumerate(reference):
        if char.isspace():
            continue
        compact_chars.append(char)
        source_indexes.append(source_index)
    compact_reference = "".join(compact_chars)
    compact_at = compact_reference.find(compact_value)
    if compact_at < 0:
        return ""
    source_start = source_indexes[compact_at]
    source_end = source_indexes[compact_at + len(compact_value) - 1] + 1
    return reference[source_start:source_end].strip()


def _normalize_style_cards(value, style_reference="", max_cards=12):
    items = value if isinstance(value, list) else []
    cards = []
    seen_excerpts = set()
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
        cards.append({
            "id": f"SC{len(cards) + 1:02d}",
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


def _style_cards_selected_by_plan(cards, style_plan, max_cards=3):
    normalized = _normalize_style_cards(cards)
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
    selected_dimensions = set()
    for card_id in requested:
        card = cards_by_id.get(card_id)
        if not card:
            continue
        dimension = STYLE_CARD_DIMENSIONS.get(card.get("category", ""), "叙述/场景")
        if dimension in selected_dimensions:
            continue
        selected.append(card)
        selected_dimensions.add(dimension)
        if len(selected) >= max(1, int(max_cards or 3)):
            break
    return selected


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
        return 6, 12
    if target <= 2500:
        return 6, 10
    if target <= 5000:
        return 8, 14
    if target <= 10000:
        return 10, 18
    return 12, 24


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
    noun_short_limit = max(2, round(max(2000, target or 2000) / 1000))
    lines = [
        "以下数字来自完整样本，必须原样写进声纹表并作为终稿硬范围，不得自行四舍五入成‘约四成’等宽泛要求：",
        f"- 每1000字非空段落控制在{density * 0.90:.1f}-{density * 1.10:.1f}段；段落长度中位数控制在{max(1, median - 3)}-{median + 3}字。",
        f"- 15字以内短段占比控制在{max(0, short_pct - 4):.0f}%-{min(100, short_pct + 4):.0f}%。",
        f"- 非对白35字以内单句短段占比控制在{max(0, single_short_pct - 5):.0f}%-{min(100, single_short_pct + 5):.0f}%。",
        f"- 对白字数占比控制在{max(0, dialogue_pct - 5):.0f}%-{min(100, dialogue_pct + 5):.0f}%；超出上限时把普通汇报、清单和解释并回叙述，不删除剧情。",
        f"- 普通对象名、操作名、阴性结果不得独立成段；约本章篇幅最多保留{noun_short_limit}个非对白名词独段，只留给真正改变认知的首次命名。",
        "- 交付前逐段扫描：连续3个及以上非对白35字以下段落必须合并到只剩1至2段；章首人物状态、普通转场、操作过程和中间结果不能作为例外。",
        "- 同一人物相邻的两句短对白若每句都不超过15字，必须合成一个对白段，或用承担反应/操作的动作标签连接；只有结巴、打断、裁决和样本明确的命令递进可以分开。",
    ]
    return "\n".join(lines)


def _style_repetition_boundary_text():
    return (
        "文风中的重复必须区分用途：保留关键词强调、对白回环、情绪递进、悬念停顿和结论落点等修辞性重复；"
        "删除没有新增动作、信息、决定、后果或情绪转折的同义复述。"
        "同一事实、规则、因果或证据边界原则上只完整说明一次；前文已经说明后，只有出现新证据、新决定或新后果时才能再次提及，"
        "并应直接写新增部分，不重新讲完整背景。"
        "状态快照、人物卡、设定、伏笔和关键事实是静默连续性约束，不是需要角色用对白或旁白逐条证明已经记住的正文任务。"
        "同一人物连续出现多个同义反应时只保留最有力度且会影响下一步行动的一个；多人反应相同时用一个代表性反应或群体结果承接。"
        "章节开篇不得再次完整演示上一章已经完成的结论、动作或情绪；只从上一章章末未完成状态继续，"
        "除非本章出现新的证据、决定或后果。普通说明不得连续拆成大量只有一句话的短段；"
        "短段只在样本对应的强调、对白、转折或节奏落点上使用。"
        "以上边界高于文风画像中对‘真实重复’或‘解释充分’的宽泛描述，但不得删除样本真实存在的强调节奏和有意回环。"
    )


def _build_style_execution_context(
    original_context,
    profile_text="",
    style_cards=None,
    style_reference="",
    limit=NOVEL_AI_CONTEXT_LIMIT,
):
    original = _append_ai_style_profile_to_context(original_context, profile_text, limit=limit)
    beat_low, beat_high = _style_execution_beat_range(original)
    output_target = _style_output_target_from_context(original)
    if 0 < output_target <= 3000:
        card_high = 1
    elif 0 < output_target <= 7000:
        card_high = 2
    else:
        card_high = 3
    short_noun_limit = max(2, round(max(2000, output_target or 2000) / 1000))
    cards_text = _format_style_cards(style_cards, limit=6500)
    structure_contract = _style_execution_structure_contract(style_reference, original)
    instruction = (
        "【剧情执行稿任务】\n"
        "本次先完成剧情执行，不交付最终正文。必须严格执行当前章节提纲、前文连续性、人物与设定边界和结尾要求。"
        "先把人物任务、主线任务、本章目标、必须发生、冲突转折和结尾钩子中指向同一件事的内容合并，"
        "不要因为它们使用了不同字段名就拆成多个事件。‘必须发生’优先保留，其他字段只补足动机、阻力、结果和边界。"
        f"再把本章整理成{beat_low}-{beat_high}条按发生顺序排列的唯一剧情拍点；"
        "每条必须带来新动作、新信息、新决定、新后果或必要的情绪转折，不能把同一场对话、同一规则或同一反应拆成多条。"
        "拍点写清场景、关键行动、对白真正新增的信息、因果、物件或证据变化以及结尾承接，"
        "清单应足够支持下一次调用无需阅读备用草稿措辞也能从零写作，但不要写成逐句分镜。"
        "在剧情拍点末尾单列‘静默继承边界’，集中记录伤势、能力、责任、证据和连续性限制；"
        "这些边界只约束写作，不算剧情拍点，也不得为了证明遵守边界而改写成重复对白或说明。"
        "执行稿必须单列四类硬约束：权限/责任边界、治疗或能力阈值、证据确定性（未知/推测/已证实）、"
        "章首承接状态。没有正文或既有状态明确授权时，不得把权限写成已获得；"
        "没有正文明确达到的条件时，不得把治疗、能力或判断写成已经完成；"
        "‘疑似、可能、未核实、来源不明’不能在执行稿中静默改成确定事实。"
        "如果当前提纲与既有事实冲突，必须保留既有事实并把冲突写入边界或拍点说明，"
        "只有当前正文明确完成改变时才能更新，不能静默覆盖。"
        + _style_repetition_boundary_text()
        + "在剧情执行清单之后生成《本章声纹执行表》。这不是通用建议，而是第二次终稿调用必须逐项执行的写法合同。"
        "文风合同只控制表达，不得把静默继承边界改写成正文里的合规说明；证据、权限和未知边界只在它们确实改变人物行动或判断时自然出现，"
        "不得为每个判断都补一遍‘目前只能确认、不能说明、仍待核对’。"
        f"如果提供了功能型原文片段卡，按本章实际场景选择0至{card_high}张，只填写真实卡号SCxx；默认只选1张，宁可少选，不得凑数。"
        "片段卡是纠正模型默认腔的原文证据，不是场景覆盖清单；优先选择最能改变本章默认写法的卡，"
        "不能因为本章有专业说明或权威命令就机械选择专业/权威卡。若模型本来就容易把该场景写成标准流程或完整命令，"
        "应优先考虑同样适用、但能补足具体感知、异常显形、口语反应或收束节拍的卡。"
        "每张卡只能绑定一个明确剧情拍点或一段连续小场景，必须写明使用起点、停止位置和只模仿哪种机制，不得作为全章统一模板。"
        "同一功能维度最多选1张；‘专业角色对白’和‘权威角色命令’同属对白维度，必须二选一。"
        "若选择3张，必须分别来自叙述/场景、对白、收束/格式三个维度；没有匹配卡时写‘无’，不得编造卡号，"
        "也不得选择只因题材名词相似、实际写作功能不匹配的片段。"
        "声纹执行表必须包含：一、选定片段卡及作用范围，每张严格写成‘卡号｜作用拍点或场景｜模仿机制｜停止位置’；"
        "二、本章叙述声纹，列3至5个真正适用的惯用词或句式框架及各自唯一落点，并明确至少2处如何把无主语流程说明落回人物当下的观察、犹疑或直白推理；"
        "至少安排2个45至90字的连续思路段，由明确人物把所见反馈、暂时判断和下一步验证连在一起；"
        "不得把这些思路压成‘状态A。状态B。结论C。’式整齐调查摘要，也不得用术语清单代替人物理解。"
        f"三、段落执行，逐字采用上方样本结构硬指标；普通说明怎样合并，约本章篇幅最多保留{short_noun_limit}个非对白名词独段，"
        "非对白单句短段不得连续超过2段。流程段不能连续只写物件、操作和结果，每个主要信息单元应由‘现场反馈—人物理解或反应—下一步动作’自然连接，"
        "但不得虚构无关情绪。"
        "四、角色声纹矩阵，覆盖本章每个实际说话人物；不要复述人物职责、权限或信息边界，只写‘人物｜句式与接话方式｜"
        "称呼/语气词/动作标签｜一条不超过25字的本章口吻样句｜禁止共用句型’。"
        "四名及以上人物说话时，最多两人可以持续使用完整、准确、无停顿的工作句；其余人物必须按人物卡和样本分别采用短问、复述关键词、"
        "半句改口、口语词、被打断、先动作后回答等不同机制，不能只靠医学词与行政词的差别区分。"
        "矩阵末尾单列‘相近角色对照’，选择最容易同腔的两组人物，让每组两人用各自口吻表达同一条本章信息，直接给出四句短样句；"
        "再列2至4个不得由多人共享的标准工作句型。矩阵同时标明哪些相邻短对白应写在同一段内，不能为了展示短问短答把每句话都另起一段。"
        "五、信息揭示与章末收束，必须指定最后一个可见、可听或可执行的具体事件，以及承载它的人物、动作、声音或一句对白；"
        "如果多路报告在章末连续接入，只先写一个打断现场的声音，再用人物接线、窗口增加或操作被迫改变承接其余报告；"
        "禁止显式使用‘第一路、第二路、第三路、第四路’或结构完全相同的逐条播报制造机械升级。"
        "最后1至3段就停在这个具体落点，禁止再追加‘某阶段开始了’‘事情没有结束’‘真正的危机才刚刚开始’等抽象宣告，"
        "也禁止用‘不是失败/但还不够/倒计时开始’式对称三段总结；若提纲要求阶段升级，必须用实际命令、异常或后果呈现。"
        "六、本章禁用项，列出作者人格中不适用于本章的局部手法和模型默认写法。全表控制在1600至2300字，"
        "只提供少量高控制力规则，不写第二份剧情说明书。"
        + "随后生成一份完整备用正文草稿，供终稿调用失败时兜底。备用草稿只展开唯一剧情拍点，静默遵守边界，"
        "不得用重复解释、重复反应、往返确认或同义对白补足篇幅。"
        "严格只输出以下三个分区，不输出其他标题、分析、状态JSON或Markdown代码块：\n"
        f"【剧情执行清单】\n{beat_low}-{beat_high}条唯一剧情拍点，末尾另列静默继承边界\n\n"
        "【本章声纹执行表】\n场景绑定片段卡、叙述声纹、段落执行、逐角色声纹矩阵与相近角色对照、具体章末落点、本章禁用项\n\n"
        "【备用正文草稿】\n完整正文草稿"
    )
    structure_block = f"【完整样本结构硬指标｜声纹表必须逐字采用】\n{structure_contract}" if structure_contract else ""
    cards_block = f"【功能型原文片段库｜只选择写法功能，不复制剧情】\n{cards_text}" if cards_text else ""
    budget = max(
        0,
        int(limit or NOVEL_AI_CONTEXT_LIMIT) - len(instruction) - len(structure_block) - len(cards_block) - 6,
    )
    if len(original) > budget:
        original = _clip_context_text(original, budget, keep_tail=False, preserve_lines=True)
    return "\n\n".join(
        part for part in (original, structure_block, cards_block, instruction) if part
    )[:int(limit or NOVEL_AI_CONTEXT_LIMIT)]


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
    style_plan = sections.get("本章声纹执行表", "")
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
    parts = [
        "只按已经合并去重的唯一剧情拍点验收本章；原始提纲里人物任务、主线任务、本章目标、必须发生和结尾钩子"
        "如果描述同一事件，不构成多次叙述任务。每个拍点必须在终稿中真实发生，不能只在人物想法、预告或章末说明中提及。"
        "静默继承边界只要求事实不冲突，不要求正文复述。"
        "同时对照前两章已完成事件，除明确持续动作和必要承接外，不得复演已经完成的冲突、解释、对话结论或结尾钩子。",
        f"【{current_label}】\n{current_basis}",
    ]
    previous_blocks = []
    for previous_index in range(max(0, chapter_index - 2), chapter_index):
        previous = chapters[previous_index]
        if not isinstance(previous, dict):
            continue
        actual_outline = str(previous.get("actual_outline", "") or "").strip()
        summary = str(previous.get("summary", "") or "").strip()
        body = str(previous.get("text", "") or "").strip()
        completed_events = actual_outline or summary or "暂无"
        previous_blocks.append(
            "第{}章《{}》\n已完成事件：{}\n章末承接：{}".format(
                previous_index + 1,
                str(previous.get("title", "") or "").strip(),
                _clip_context_text(completed_events, 1200, preserve_lines=True) or "暂无",
                _clip_context_text(body, 600, keep_tail=True, preserve_lines=True) or "暂无",
            )
        )
    if previous_blocks:
        parts.append("【前两章已完成内容｜只用于承接与去重】\n" + "\n\n".join(previous_blocks))
    return "\n\n".join(parts)


def _build_chapter_execution_hard_constraints(project, chapter_index):
    """Expose continuity boundaries as a short checklist for the execution pass."""
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
        "以下是剧情执行稿的硬约束清单，只用于防止连续性错误，不是正文任务；未发生变化的内容不要写回正文。",
        "1. 权限/责任边界：资料没有明确授权、交接或职责转移时，不能把‘可查看、可操作、可决定、由谁负责’写成已经获得或已经转移。",
        "2. 治疗/能力阈值：资料明确的条件、次数、范围、伤势和能力上限必须原样保留；未达到条件只能写尝试、推测或受限状态，不能写成完成。",
        "3. 证据确定性：未知、疑似、可能、未核实、来源不明和推断必须保持原确定性；新证据只能更新它明确改变的部分。",
        "4. 章首承接：上一章结尾的时间、天气、地点、人物位置、身体状态、持有物和未完成动作必须先承接，再推进本章拍点。",
        "5. 规划冲突：提纲与已发生事实冲突时不能静默覆盖；优先保留更具体、更晚、更接近正文的事实，只有当前章明确发生改变时才更新。",
        "6. 既有结论去重：前两章已经完成的动作、结论和情绪不能在开篇完整复演，只能引用其结果并写本章新增的动作、信息、决定或后果。",
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
):
    original = _append_ai_style_profile_to_context(original_context, profile_text, limit=limit)
    draft = str(draft_text or "").strip()
    execution = str(execution_text or "").strip()
    chapter_style_plan = str(style_plan or "").strip()
    target = int(output_target or 0) or _style_output_target_from_context(original)
    if 0 < target <= 3000:
        style_card_limit = 1
    elif 0 < target <= 7000:
        style_card_limit = 2
    else:
        style_card_limit = 3
    selected_cards = _style_cards_selected_by_plan(
        style_cards,
        chapter_style_plan,
        max_cards=style_card_limit,
    )
    selected_cards_text = _format_style_cards(selected_cards, limit=4200)
    reasons = [str(reason).strip() for reason in (local_reasons or []) if str(reason or "").strip()]
    reason_text = "\n".join(f"- {reason}" for reason in reasons) or "- 本地结构指标均在允许范围内"
    reference_structure = _style_text_structure(style_reference)
    reference_profile = _build_style_reference_profile(style_reference, target) if style_reference else ""
    delivery_targets = []
    if target:
        delivery_targets.append(f"终稿正文控制在{round(target * 0.85)}-{round(target * 1.15)}字")
    if reference_structure["chars"] >= 500:
        if target:
            expected_paragraphs = reference_structure["paragraphs_per_1000"] * target / 1000
            paragraph_low = max(1, round(expected_paragraphs * 0.85))
            paragraph_high = max(1, round(expected_paragraphs * 1.15))
            delivery_targets.append(
                f"非空段落必须控制在{paragraph_low}-{paragraph_high}段；超过{paragraph_high}段视为不合格，交付前先合并"
            )
            expected_short = expected_paragraphs * reference_structure["short_paragraph_pct"] / 100
            delivery_targets.append(
                f"15字以内短段约{max(0, round(expected_short * 0.80))}-{max(1, round(expected_short * 1.20))}段"
            )
        delivery_targets.extend([
            f"每1000字非空段落必须控制在{reference_structure['paragraphs_per_1000'] * 0.90:.1f}-{reference_structure['paragraphs_per_1000'] * 1.10:.1f}段",
            f"段落长度中位数必须控制在{max(1, reference_structure['paragraph_median'] - 3)}-{reference_structure['paragraph_median'] + 3}字",
            f"15字以内短段占比必须控制在{max(0, reference_structure['short_paragraph_pct'] - 4):.0f}%-{min(100, reference_structure['short_paragraph_pct'] + 4):.0f}%",
            f"非对白35字以内单句短段占比必须控制在{max(0, reference_structure['single_sentence_short_paragraph_pct'] - 5):.0f}%-{min(100, reference_structure['single_sentence_short_paragraph_pct'] + 5):.0f}%",
            f"句子长度中位数必须控制在{max(1, reference_structure['sentence_median'] - 4)}-{reference_structure['sentence_median'] + 4}字",
            f"对白字数占比必须控制在{max(0, reference_structure['dialogue_char_pct'] - 5):.0f}%-{min(100, reference_structure['dialogue_char_pct'] + 5):.0f}%；超出上限时合并普通汇报和流程对白，不删除剧情",
            "连续3个及以上非对白35字以下段落必须合并到只剩1至2段；章首状态、普通转场、操作过程和中间结果不能作为例外",
            "同一人物相邻的两句15字以内短对白必须合成一个对白段，或用真正承担反应/操作的动作标签连接；结巴、打断、裁决和样本明确的命令递进除外",
        ])
        if reference_structure["single_sentence_short_paragraph_pct"] < 55:
            delivery_targets.extend([
                "非对白单句短段不得连续超过2段，短段只用于对白、关键发现、裁决、转折或样本明确的节奏落点",
                "普通说明段每段组织2至4个完整句子；普通名词清单、同类结果和中间结论不得逐项独立成段",
            ])
    delivery_text = "\n".join(f"- {item}" for item in delivery_targets)
    plot_acceptance = _build_style_plot_acceptance_context(
        project,
        int(chapter_index or 0),
        execution_text=execution,
    )
    repetition_boundary = _style_repetition_boundary_text()
    instruction = (
        "【终稿编辑任务】\n"
        "先独立核对首次正文是否完整执行本章剧情、人物设定、前文连续性和结尾要求，再对照正文风格样本检查写法。"
        "直接交付修订后的终稿，不要先输出审校报告。剧情正确的内容必须保留，不得为了文风删除、替换、提前或延后既定事件；"
        "只在确有必要时调整叙述方式、句式、段落组织、对白衔接、信息揭示和收束表达。"
        "如果首次正文已经比任何改写更贴近样本，可以原样保留正文。"
        "程序可能根据样本结构在首次正文和修订稿之间择优，因此所有evidence_quote必须从首次正文逐字复制，"
        "并在终稿正文中保留完全相同的连续短句；不得把证据句改写成只存在于其中一个版本的表达。"
        "必须单独完成一次语言声纹校准：按作者人格中的高频/稳定层级，在适用场景沿用样本反复出现的"
        "句首、连接词、动作修饰词、生理反应短语、解释框架和说话标签，不得为了词汇丰富强行换同义词；"
        "局部或限定场景的词不得硬塞，任何惯用词都不得集中堆砌。"
        "必须单独完成一次对白声纹校准：结合角色卡语言方式，为主角、权威或专业角色、弱势角色、对手和口语角色"
        "分别落实样本对应的对白长短、停顿、省略、称呼、语气词、反问、接话和动作插入方式；不能让所有人物一个腔调。"
        "如果提供【本章声纹执行表】，它是本章最高优先级的写法合同：选定惯用词只能在表中指定的语境落下，"
        "每个实际说话人物必须按角色声纹矩阵和相近角色对照分别执行；不得把不同人物都改成准确、克制、无停顿的标准工作语言。"
        "片段卡原文只以【本章选定功能片段卡】实际列出的卡为准；声纹表中提到但未列出的卡视为未选，不执行。"
        "每张选定卡只控制声纹表指定的一个拍点或连续小场景，到表中停止位置立即退出，不能把其判断方式、专业口吻或段落节拍扩散到全章。"
        "只模仿选定卡的组织机制、用词频率和对白节拍，绝不能复制其人物、设定、事件或连续原句。"
        "静默继承边界只用于防止事实写错，不能逐条显性写进正文；不得给每个判断机械补齐风险边界或写成处置报告。"
        "流程信息不能连续由无主语被动句、物件清单和标准命令承担；每个主要信息单元都要让现场反馈改变人物的理解、身体或下一步操作，"
        "并至少两次用45至90字的连续思路段把整理后的旁白结论落回人物当下的直白思路。角色差异必须体现在句法、停顿、称呼和接话，不得只靠职责术语区分。"
        "章首承接状态合并成一个自然中段，不得把人物站姿、伤势、环境和能力状态连续拆成电影分镜。"
        "同一人物连续说出的15字以内短句必须合成一个对白段，或由真正承担反应/操作的动作标签连接；不能把每句命令、短问和短答都另起一段。"
        "多路消息在章末接入时禁止使用‘第一路、第二路、第三路、第四路’逐项播报；先用一个声音打断，再由人物动作和窗口变化承接后续升级。"
        "章末必须停在声纹表指定的具体动作、声音、异常、后果或一句人物对白上；落点之后禁止追加抽象阶段宣告、对称三段总结或商业预告句。"
        "输出前静默检查字数、段落密度、长短段分布、句长、对白比例、习惯用词、对白声纹以及人物、物品、地点、伤势和结尾状态。"
        "必须按【终稿剧情验收清单】逐项确认唯一剧情拍点已经执行，并删除非必要的前两章剧情复演；"
        "终稿前在内部逐段检查净推进：连续两到四段可以共同完成一个强调或情绪单元，"
        "但如果整组内容没有带来新动作、新信息、新决定、新后果或必要情绪转折，就必须删除或并入前文。"
        + repetition_boundary
        + (f"以下是本次终稿交付门槛，不符合时必须在本次调用内部继续调整后再交付：\n{delivery_text}\n" if delivery_text else "\n")
        +
        "必须严格使用以下六个分区标题，标题不得改名；正文中不要出现分析、评分、修改说明或其他分区标题：\n"
        "【终稿正文】\n可直接写入章节的完整正文\n\n"
        "【终稿验收】\n"
        '{"beat_evidence":[{"beat":1,"evidence_quote":"终稿中直接证明该拍点已经发生的8-60字逐字原文"}],'
        '"previous_chapter_repetition_check":true,"paragraph_structure_check":true}\n\n'
        "beat_evidence必须覆盖剧情执行清单中的每个编号且每个编号只写一次；证据必须直接证明事件已发生，"
        "不能用人物设想、预告、静默边界或未执行的计划充数。两个check只能在逐段完成对应检查后写true。\n\n"
        "【实际提纲】\n用6-10条短剧情拍点概括终稿已经发生的内容，不补写正文外事件\n\n"
        "【本章摘要】\n简短概括终稿核心事件和情绪转折\n\n"
        "【本章需继承的关键事实】\n逐条记录后文必须继承的人物关系、伤势、物品、地点、线索、伏笔和结尾状态\n\n"
        "【长篇记忆更新】\n"
        + _long_form_update_contract_instructions(project or {}, chapter_index)
    )
    if not include_memory:
        source_instruction = (
            "以上次终稿为正文底稿，完整保留已经发生的剧情、因果、人物状态、具体信息和章末落点；"
            "只针对【备用正文的本地检测结果】重新组织段落、合并短段、调整对白衔接和必要句式。"
            "不得从剧情执行清单重新写一版，也不得删掉或替换原有拍点。"
            if rescue_from_candidate else
            "根据剧情执行清单从零写出完整终稿。执行清单只提供剧情事实和顺序，不是可沿用的正文表达；"
            "不得把备用草稿的句子、短段排列、动作分镜或措辞当成底稿，也不要做逐句润色。"
            if execution else
            "先独立核对首次正文是否完整执行本章剧情、人物设定、前文连续性和结尾要求，再对照正文风格样本检查写法。"
        )
        fallback_instruction = (
            "本次必须保留上次终稿的全部有效剧情，只调整未通过的验收项。"
            if rescue_from_candidate else
            "必须重新组织整章，不能退回备用正文草稿。"
            if execution else
            "如果首次正文已经比任何改写更贴近样本，可以原样保留。"
        )
        instruction = (
            "【终稿编辑任务】\n"
            + source_instruction
            + "本次只负责小说正文，不生成提纲、摘要、关键事实或状态资料。"
            "剧情事件、人物、设定、时间顺序、因果关系和结尾承接必须完整保留；"
            "在这些内容不变的前提下，可以彻底重组句式、段落、对白衔接、叙述节奏和信息揭示方式。"
            "不要保留备用草稿或模型默认写法中的碎段、短句强调、分镜动作流或对白比例偏差。"
            + fallback_instruction
            + "必须按作者人格和原文证据校准习惯词、句式框架、说话标签、对白停顿、称呼、语气词和接话方式；"
            "样本会重复使用的词不应被模型默认同义词替换，局部词不能硬塞，不同人物不能写成同一种口气。"
            + "【本章声纹执行表】是本章最高优先级写法合同，必须逐项落实选定惯用词的落点、段落执行、相近角色对照和每个说话人物的声纹矩阵。"
            "片段卡原文只以【本章选定功能片段卡】实际列出的卡为准；表中提到但未列出的卡视为未选。"
            "每张卡只控制表中指定的一个拍点或连续小场景，到停止位置立即退出，不能把同一种专业判断、命令口吻或段落节拍铺满全章；"
            "只模仿组织机制、用词频率和对白节拍，禁止复制其中人物、设定、事件或连续原句。"
            "静默继承边界不得逐条显性改写成正文，不得为每个判断机械补齐风险限定。"
            "流程信息不能连续由无主语被动句、物件清单和标准命令承担；每个主要信息单元都要让现场反馈改变人物的理解、身体或下一步操作，"
            "并至少两次用45至90字的连续思路段把旁白结论落回人物当下的直白思路。角色差异必须体现在句法、停顿、称呼和接话，不能只靠职责术语区分。"
            "章首承接状态合并成一个自然中段，不得拆成电影分镜；多路消息在章末接入时禁止用‘第一路、第二路、第三路、第四路’逐项播报，"
            "先用一个声音打断，再由人物动作和窗口变化承接后续升级。"
            "同一人物连续说出的15字以内短句必须合成一个对白段，或由真正承担反应/操作的动作标签连接，不能每句都另起一段。"
            "章末必须停在声纹表指定的具体动作、声音、异常、后果或一句人物对白上，禁止再追加抽象阶段宣告或对称三段总结。"
            + "输出前静默检查字数、段落密度、长短段分布、句长、对白比例、习惯用词、对白声纹以及人物、物品、地点、伤势和结尾状态。"
            + "必须按【终稿剧情验收清单】逐项确认唯一剧情拍点已经执行，并删除非必要的前两章剧情复演。"
            + "终稿前在内部逐段检查净推进：连续两到四段可以共同完成一个强调或情绪单元，"
            "但如果整组内容没有带来新动作、新信息、新决定、新后果或必要情绪转折，就必须删除或并入前文。"
            + repetition_boundary
            + (
                f"以下是本次终稿交付门槛，不符合时必须在本次调用内部继续调整后再交付：\n{delivery_text}\n"
                if delivery_text else "\n"
            )
            + "严格只输出以下两个分区，不输出提纲、摘要、状态JSON、审校报告、评分、修改说明或Markdown代码块：\n"
            "【终稿正文】\n可直接写入章节的完整正文\n\n"
            "【终稿验收】\n"
            '{"beat_evidence":[{"beat":1,"evidence_quote":"终稿中直接证明该拍点已经发生的8-60字逐字原文"}],'
            '"previous_chapter_repetition_check":true,"paragraph_structure_check":true}\n'
            "beat_evidence必须与剧情执行清单的全部编号一一对应，每项证据都必须是终稿正文中的连续逐字原文，"
            "并直接证明该拍点已经发生，不能用人物想法、预告、静默边界或计划充数。"
            "previous_chapter_repetition_check只能在对照前两章并删除无新增变量的复演后写true；"
            "paragraph_structure_check只能在实际核对段落密度、短段比例和连续短段后写true。"
        )
    candidate_limit = 24000
    source_text = draft if rescue_from_candidate else (execution or draft)
    if len(source_text) > candidate_limit:
        half = (candidate_limit - 20) // 2
        source_text = source_text[:half] + "\n……（中段已截断）……\n" + source_text[-half:]
    leading_blocks = [
        f"【终稿剧情验收清单】\n{plot_acceptance}" if plot_acceptance else "",
        f"【文风重复与推进边界】\n{repetition_boundary}",
        f"【完整样本本地结构目标】\n{reference_profile}" if reference_profile else "",
        f"【备用正文的本地检测结果｜终稿必须纠正】\n{reason_text}" if execution else
        f"【首次正文的本地检测结果】\n{reason_text}",
        f"【上次终稿｜保留剧情，只修验收问题】\n{source_text}" if rescue_from_candidate else
        f"【剧情执行清单｜只继承事实与顺序，必须从零写作】\n{source_text}" if execution else
        f"【首次正文】\n{source_text}",
        f"【本章声纹执行表｜必须逐项落实】\n{chapter_style_plan}" if chapter_style_plan else "",
        f"【本章选定功能片段卡｜只模仿写法，不复制内容】\n{selected_cards_text}" if selected_cards_text else "",
    ]
    trailing_blocks = [instruction]
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
    parsed = bool(body and all(title in sections for title in headings))
    if not body and text and not matches:
        body = text
    return {
        "text": body,
        "outline": sections.get("实际提纲", ""),
        "summary": sections.get("本章摘要", ""),
        "key_facts": sections.get("本章需继承的关键事实", ""),
        "acceptance": _parse_style_finalize_acceptance(
            sections.get("终稿验收", "")
        ),
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
    reference = _style_text_structure(style_reference)
    hard_targets = []
    if target:
        hard_targets.append(f"正文总字数控制在约{round(target * 0.85)}-{round(target * 1.15)}字")
    if target and reference["chars"] >= 500:
        expected_paragraphs = reference["paragraphs_per_1000"] * target / 1000
        paragraph_low = max(1, round(expected_paragraphs * 0.88))
        paragraph_high = max(paragraph_low, round(expected_paragraphs * 1.12))
        expected_long = expected_paragraphs * reference["long_paragraph_pct"] / 100
        long_low = max(1, round(expected_long * 0.70)) if reference["long_paragraph_pct"] >= 5 else 0
        long_high = max(long_low, round(expected_long * 1.30)) if long_low else 0
        hard_targets.extend([
            f"非空段落总数控制在约{paragraph_low}-{paragraph_high}段",
            f"段落长度中位数接近{reference['paragraph_median']}字",
            f"15字以内短段占比接近{reference['short_paragraph_pct']:.0f}%",
            (
                f"80字以上中长段至少约{long_low}-{long_high}段"
                if long_low else
                "按样本比例安排中长段"
            ),
            f"句子长度中位数接近{reference['sentence_median']}字",
            f"对白字数占比接近{reference['dialogue_char_pct']:.0f}%",
        ])
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
        f"检测到的偏差：\n{reason_lines or '- 整体结构与样本偏差明显'}\n"
        + (f"本次硬性验收范围：\n{hard_target_text}\n" if hard_target_text else "")
        +
        "上述硬性范围是通过门槛，输出前必须静默统计；任何一项未达到就先自行重写，不要提交不合格结果。"
        "不得用简单合并换行应付验收；需要同步调整习惯用词、句式框架、说话标签、不同人物的对白声纹、"
        "叙述与对白衔接、背景铺陈和长短段穿插。"
        "样本反复使用且适合当前语境的词应原样沿用，不得用模型默认同义词替换；局部词不得硬塞或集中堆砌。"
        "只输出重写后的完整正文，不输出标题、说明、分析、指标或修改记录。"
    )
    style_marker = "【AI文风画像】" if "【AI文风画像】" in original else "【风格锁定规则】"
    style_start = original.find(style_marker)
    if style_start >= 0:
        base_context = original[:style_start].strip()
        style_context = original[style_start:].strip()
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


def _build_style_reference_profile(style_reference, output_target=0):
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
    result["conflicts"].update(existing["conflict_ids"])
    result["tasks"].update(existing["task_ids"])
    for chapter in project.get("chapters", []) if isinstance(project.get("chapters"), list) else []:
        if not isinstance(chapter, dict):
            continue
        reconciliation = chapter.get("state_reconciliation", {})
        reconciliation = reconciliation if isinstance(reconciliation, dict) else {}
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
    repaired = False
    try:
        data = json.loads(text[start:])
    except Exception:
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
                    "name": "新增时填写稳定姓名",
                    "state": "当前动态状态，不重写永久身份、长期目标、秘密或语言",
                    "changes": ["本章长期变化"],
                    "canon": {"role": "仅新增时填写", "goal": "", "secret": "", "voice": "", "notes": ""},
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


def _long_form_update_contract_instructions(project, chapter_index):
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
    return (
        "只输出以下版本2长篇记忆增量，不得返回完整旧事实清单，也不得改写导入的人物卡、设定定义或伏笔计划。"
        "未出现在增量里的旧资料默认保留；只有fact_updates中的retire/supersede和state_retirements可以让旧状态退出。"
        "这是严格增量，不是全量总结：普通章节只返回本章新增、改变、明确结束或被本章正文直接核对的项目；"
        f"fact_updates最多{LONG_FORM_MAX_FACT_UPDATES}项，long_term_events最多{LONG_FORM_MAX_LONG_TERM_EVENTS}项，"
        f"人物/设定/伏笔更新每类最多{LONG_FORM_MAX_RECORD_UPDATES}项，state_patch各列表最多{LONG_FORM_MAX_STATE_ITEMS}项。"
        "若同一变化可归并为一条，必须合并；不要为了覆盖正文中的每个句子制造状态条目。"
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
        "不得填写本次新增的NCF/NTASK临时key。"
        f"三组复核数组至少必须完整包含：{required_state_review_text}；"
        + (
            f"当前是十章边界，state_lifecycle_review.scope必须为{LONG_FORM_STAGE_REVIEW_SCOPE}；"
            "只回显本章选择、触及、修订或退出的物件、冲突和任务，绝不能回显全量目录。"
            "全部未触及状态由程序原样继承，并按数量和SHA256核验。"
            if stage_boundary else
            "state_lifecycle_review.scope必须为current_chapter；复核本章已选及本章触及的物件、冲突和任务。"
        )
        + "record_updates只记录动态状态和本章变化；canon只允许create时填写，update时必须为空。"
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


def _normalize_long_form_update_payload(project, chapter_index, update):
    payload = deepcopy(update) if isinstance(update, dict) else {}
    payload.pop("_parse_repaired", None)
    if "state_patch" not in payload and isinstance(payload.get("state_snapshot"), dict):
        payload["state_patch"] = deepcopy(payload.get("state_snapshot", {}))
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


def _normalize_long_form_event_storage_refs(project, chapter_index, update):
    """Remove only structurally invalid event refs; never infer missing semantic links."""
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
    return payload


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
    return payload


def _long_form_evidence_present(quote, final_text):
    evidence = _compact_text(quote)
    return len(evidence) >= 4 and evidence in _compact_text(final_text)


_EVIDENCE_IGNORED_DIALOGUE_MARKS = frozenset('“”‘’"\'')
_EVIDENCE_CLAUSE_SPLIT_PATTERN = re.compile(r"[\r\n，。！？；：,!?;:]+")
_EVIDENCE_MIN_UNIQUE_CLAUSE_CHARS = 8


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


def _literalize_long_form_evidence_quote(quote, final_text):
    raw_quote = str(quote or "").strip()
    body = str(final_text or "")
    if _long_form_evidence_present(raw_quote, body):
        return raw_quote
    projected_quote = _evidence_projection(raw_quote)
    projected_body, positions = _evidence_projection(body, with_positions=True)
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
        for kind in ("characters", "lore", "foreshadows", "facts", "conflicts", "tasks", "archives"):
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
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
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
                    if _compact_text(previous) != _compact_text(expected):
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
        unknown_reviewed_objects = sorted(
            value for value in reviewed["object_keys"]
            if _compact_text(value) not in existing_object_keys
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
                if not _resolve_long_form_record_ref(project, kind, ref):
                    errors.append(f"{kind}更新第{index}项引用未知记录：{ref}")
                if isinstance(item.get("canon"), dict) and any(
                    str(value or "").strip() for value in item.get("canon", {}).values()
                ):
                    errors.append(f"{kind}更新第{index}项不得修改永久canon字段")
            else:
                key = str(item.get("key", "") or "").strip()
                if not key or key in temp_record_keys[kind]:
                    errors.append(f"{kind}更新第{index}项新增key缺失或重复")
                temp_record_keys[kind].add(key)
                name = str(item.get("name", "") or "").strip()
                if not name:
                    errors.append(f"{kind}更新第{index}项新增名称为空")
                elif require_evidence:
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
            "foreshadow", "key_object", "relationship", "other",
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
    memory_fields = []

    def add(target, value):
        if value not in target:
            target.append(value)

    for error in validation_errors or []:
        text = str(error or "")
        lowered = text.lower()
        if "实际提纲" in text:
            add(bundle_fields, "outline")
        if "本章摘要" in text:
            add(bundle_fields, "summary")
        if "关键事实" in text:
            add(bundle_fields, "key_facts")
        if "schema_version" in lowered:
            add(memory_fields, "schema_version")
        if "base_revision" in lowered:
            add(memory_fields, "base_revision")
        if "state_patch" in lowered or any(
            marker in text for marker in ("人物状态第", "关系状态第", "物品状态第", "冲突状态第", "任务状态第")
        ):
            add(memory_fields, "state_patch")
        if "state_retirements" in lowered or text.startswith("退出"):
            add(memory_fields, "state_retirements")
        if "state_lifecycle_review" in lowered or "状态生命周期复核" in text:
            add(memory_fields, "state_lifecycle_review")
        if "fact_updates" in lowered:
            add(memory_fields, "fact_updates")
        if "fact_lifecycle_review" in lowered or "事实生命周期复核" in text:
            add(memory_fields, "fact_lifecycle_review")
        if "long_term_events" in lowered:
            add(memory_fields, "long_term_events")
        if "state_reconciliation" in lowered:
            add(memory_fields, "state_reconciliation")
        if "state_delta" in lowered:
            add(memory_fields, "state_delta")
        if "current_chapter_character" in lowered:
            add(memory_fields, "current_chapter_character_refs")
        if "stage_archive" in lowered:
            add(memory_fields, "stage_archive")
        if "record_updates" in lowered or "characters更新" in text or "lore更新" in text:
            add(memory_fields, "record_updates")
        if "foreshadow_updates" in lowered or "伏笔更新" in text:
            add(memory_fields, "foreshadow_updates")
        if "next_chapter_memory" in lowered or text.startswith("下一章"):
            add(memory_fields, "next_chapter_memory")
        if "运行态" in text or "提纲或长期事件" in text:
            add(memory_fields, "record_updates")
            add(memory_fields, "state_reconciliation")

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
    return {"bundle_fields": bundle_fields, "memory_fields": memory_fields}


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


def _parse_memory_repair_result(value):
    text = str(value or "").strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.IGNORECASE | re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    start = text.find("{")
    if start < 0:
        return {
            "parsed": False,
            "repair_mode": "",
            "outline": "",
            "summary": "",
            "key_facts": "",
            "memory_update": {},
            "memory_patch": {},
        }
    try:
        data, _offset = json.JSONDecoder().raw_decode(text[start:])
    except Exception:
        return {
            "parsed": False,
            "repair_mode": "",
            "outline": "",
            "summary": "",
            "key_facts": "",
            "memory_update": {},
            "memory_patch": {},
        }
    if not isinstance(data, dict):
        return {
            "parsed": False,
            "repair_mode": "",
            "outline": "",
            "summary": "",
            "key_facts": "",
            "memory_update": {},
            "memory_patch": {},
        }
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
    patch_replacements = (
        memory_patch.get("replace", memory_patch)
        if isinstance(memory_patch, dict) else {}
    )
    patch_mode = isinstance(memory_patch, dict) and bool(patch_replacements)
    bundle_content_present = any(
        str(data.get(key, "") or "").strip()
        for key in ("outline", "summary", "key_facts")
    )
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
    }


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
    original_bundle = {
        key: {"outline": outline, "summary": summary, "key_facts": key_facts}.get(key, "")
        for key in targets["bundle_fields"]
    }
    manifest = _memory_repair_reference_manifest(project, chapter_index, memory_update)
    compact_memory_update = _compact_memory_repair_update_for_context(
        project,
        chapter_index,
        memory_update,
        manifest=manifest,
    )
    original_memory = {
        key: deepcopy(compact_memory_update.get(key))
        for key in targets["memory_fields"]
        if key in compact_memory_update
    }
    output_example = {
        key: "返回完整修复值"
        for key in targets["bundle_fields"]
    }
    if targets["memory_fields"]:
        output_example["long_form_memory_patch"] = {
            "replace": {
                key: "返回该字段的完整替换值"
                for key in targets["memory_fields"]
            }
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
        "再在long_term_events和state_reconciliation中引用同一个临时key。"
        "fact_updates使用retire或supersede时必须保留被处理的已有AF-ID，逐字复制原scope和previous_fact，"
        "同时填写非空reason和正文逐字证据；supersede还要填写新的NF临时key和同scope新fact，该NF必须同步进入long_term_events.storage.fact_refs和"
        "state_reconciliation.fact_refs。"
        "涉及evidence_quote时必须从最终正文逐字复制连续原文。"
        "严格只输出一个合法JSON对象，不输出Markdown、解释或额外字段。输出结构："
        + json.dumps(output_example, ensure_ascii=False, separators=(",", ":"))
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
    ]
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
    contract = _long_form_update_contract_instructions(project, chapter_index)
    error_text = "\n".join(f"- {str(item)}" for item in validation_errors or []) or "- 原终稿未返回可验证的版本2记忆增量"
    output_requirements = (
        "【输出要求】\n必须输出一个合法JSON对象，顶层结构为"
        '{"outline":"6-10条实际提纲","summary":"本章摘要","key_facts":["事实"],"long_form_memory":{...}}。'
        "每条evidence_quote必须从【最终正文】中原样复制一个连续子串，保留原文全部中文引号、标点和换行；"
        "尤其不得把正文中的“对白”改成不带引号的对白。输出前必须按字面检查该字符串能在最终正文中直接找到；"
        "找不到合格逐字证据时删除对应更新，不得概括、拼接或改写证据。"
        "long_form_memory严格执行以下契约：\n" + contract
    )
    source_sections = [
        ("任务", "只修复本章提纲、摘要、关键事实和长篇记忆增量，不得重写正文，不得新增正文没有发生的事件。", 600, False),
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
    contract = _long_form_update_contract_instructions(project, chapter_index)
    stage_boundary = (chapter_index + 1) % 10 == 0
    task = (
        "只读取已经完成的【最终正文】，独立生成实际提纲、本章摘要、需继承关键事实和版本2长篇记忆增量；"
        "不得重写正文，不得把原规划提纲或下一章资料中的未来事件写成已经发生。\n"
        "输出前必须在内部逐段建立事件核对表，至少检查：人物实际出场、说话、来电和带来的新信息；"
        "伤势、能力、关系、位置、物件和任务变化；新线索、证据、异常、记录缺失/覆盖/删除/清空、"
        "未知来源和责任边界；新设施、规则和跨章关键物；伏笔推进或回收；章节结尾仍在持续的动作与风险。\n"
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
    )
    compact_target = (
        "本章不是十章边界。完整性优先，但只返回本章真正新增、改变、明确结束或被正文直接核对且后文必须继承的最小增量；"
        "不得为了接近上限填满数组。建议fact_updates 3-6项、long_term_events 2-5项、"
        "record_updates的人物与设定各0-3项、伏笔0-2项、state_patch各列表0-5项。"
        "人物仅行动、说话或提供信息时只进入current_chapter_character_refs与state_reconciliation.character_refs；"
        "只有章末持续状态、公开层或关系确有变化才写record_updates或state_patch。"
        "相同语义不得同时拆成多条事实、事件和状态；可以交叉引用，但每个分区只承担自己的存储职责。"
        "stage_archive必须为null。目标JSON总长度不超过18000字；确有彼此独立且后文必须继承的关键变化时可以突破建议数量，但不得省略。"
        if not stage_boundary else
        "本章是十章边界。除完整stage_archive外，其他分区仍只返回本章新增、改变、结束或直接核对的最小增量；"
        "不得回显最近十章或全量状态，未触及资料由程序原样继承。"
    )
    output_requirements = (
        "【输出要求】\n严格输出一个合法JSON对象，顶层结构为"
        '{"outline":"6-10条实际提纲","summary":"本章摘要","key_facts":["事实"],"long_form_memory":{...}}。'
        "outline、summary和key_facts只能概括最终正文已经发生的内容。summary控制在800字以内；"
        "key_facts通常控制在4-16条，每条只保留一个后文必须继承的合并事实，同一事件的背景、判断和结果不得拆成多条。"
        "确有超过16项彼此独立且都会影响后文时必须保留，不得为了数字上限丢失关键连续性。"
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


def _merge_long_form_memory_reconciliation_patch(memory_update, patch):
    """Merge a small boundary correction without replacing the original valid delta."""
    merged = deepcopy(memory_update) if isinstance(memory_update, dict) else {}
    patch = patch if isinstance(patch, dict) else {}
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
        ("最近十章正文、摘要与关键事实", recent_ten_text, 56000, True),
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
            or temp_refs.get(kind, {}).get(str(ref or "").strip(), "")
        )
    for key in ("story_time", "location", "notes"):
        if key in patch and str(patch.get(key, "") or "").strip():
            snapshot[key] = str(patch.get(key, "") or "").strip()

    def merge_items(snapshot_key, incoming_key, key_func, normalizer):
        existing = snapshot.get(snapshot_key, []) if isinstance(snapshot.get(snapshot_key), list) else []
        order = []
        records = {}
        for item in existing:
            if not isinstance(item, dict):
                continue
            item_key = key_func(item)
            if not item_key:
                continue
            if item_key not in records:
                order.append(item_key)
            records[item_key] = deepcopy(item)
        for item in patch.get(incoming_key, []) if isinstance(patch.get(incoming_key), list) else []:
            normalized = normalizer(item)
            if not normalized:
                continue
            item_key = key_func(normalized)
            if not item_key:
                continue
            if item_key not in records:
                order.append(item_key)
            records[item_key] = normalized
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
        return str(item.get("lore_id", "") or item.get("key", "") or _compact_text(item.get("name", ""))).strip()

    merge_items("object_states", "object_states", object_key, normalize_object)
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
    memory = _normalize_long_form_memory(project.get("long_form_memory", {}))
    revision_before = int(memory.get("revision", 0) or 0)
    reference_maps = _long_form_record_reference_maps(project)
    temp_refs = {
        "characters": {}, "lore": {}, "foreshadows": {}, "facts": {},
        "archives": {}, "conflicts": {}, "tasks": {},
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
                record = by_name.get(_compact_text(name).casefold())
                if record is None and name:
                    record = factory(len(records))
                    record["id"] = uuid.uuid4().hex
                    record["name"] = name
                    canon = item.get("canon", item.get("fields", {}))
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
            record["status"] = status
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
            str(value or "").strip()
            for value in state_lifecycle_review.get("reviewed_object_keys", [])
            if str(value or "").strip()
        ] if isinstance(state_lifecycle_review.get("reviewed_object_keys", []), list) else []
        reviewed_conflicts = [
            str(value or "").strip()
            for value in state_lifecycle_review.get("reviewed_conflict_refs", [])
            if str(value or "").strip()
        ] if isinstance(state_lifecycle_review.get("reviewed_conflict_refs", []), list) else []
        reviewed_tasks = [
            str(value or "").strip()
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
                    or temp_refs[kind].get(ref_text, "")
                )
            elif kind == "facts":
                item_id = (
                    ref_text
                    if ref_text in fact_by_id or ref_text in historical_fact_ids
                    else temp_refs["facts"].get(ref_text, "")
                )
            elif kind in {"conflicts", "tasks"}:
                item_id = temp_refs[kind].get(ref_text, ref_text)
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
        item_id = _resolve_long_form_record_ref(project, "characters", ref) or temp_refs["characters"].get(str(ref or ""), "")
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
                item_id = _resolve_long_form_record_ref(project, kind, ref) or temp_refs[kind].get(str(ref or ""), "")
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
            item_id = str(ref or "") if str(ref or "") in valid_fact_ids else temp_refs["facts"].get(str(ref or ""), "")
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
            item_id = str(ref or "") if str(ref or "") in valid_archive_ids else temp_refs["archives"].get(str(ref or ""), "")
            if item_id and item_id not in selection["stage_archive_ids"]:
                selection["stage_archive_ids"].append(item_id)
        current_archive_id = temp_refs["archives"].get("CURRENT_STAGE", "")
        if current_archive_id and current_archive_id not in selection["stage_archive_ids"]:
            selection["stage_archive_ids"].append(current_archive_id)
        active_state_refs = _long_form_existing_state_refs(project, memory)
        object_key_by_compact = active_state_refs["object_key_by_compact"]
        selection["object_keys"] = []
        object_values = next_memory.get("object_keys", [])
        for value in object_values if isinstance(object_values, list) else []:
            canonical = object_key_by_compact.get(_compact_text(value), "")
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
            canonical = object_key_by_compact.get(
                _compact_text(item.get("key", item.get("name", ""))), ""
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
                item_id = temp_refs[temp_kind].get(ref, ref)
                if item_id in active_ids and item_id not in selection[output_key]:
                    selection[output_key].append(item_id)
            for item_id in event_selection_refs[output_key]:
                if item_id in active_ids and item_id not in selection[output_key]:
                    selection[output_key].append(item_id)
            for item in state_patch.get(patch_key, []) if isinstance(state_patch.get(patch_key), list) else []:
                if not isinstance(item, dict):
                    continue
                ref = str(item.get("id", "") or item.get("key", "") or "").strip()
                item_id = temp_refs[temp_kind].get(ref, ref)
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
        runtime_state = _record_runtime_context(project, "characters", char.get("id", ""), 700)
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
            runtime_state = _record_runtime_context(project, "lore", item.get("id", ""), 520)
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
        runtime_state = _record_runtime_context(project, "foreshadows", item.get("id", ""), 520)
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
    has_current_text = bool(_compact_text(chap.get("text", "")))
    reverse_from_body = action in {"outline", "summary"} and has_current_text
    draft_words_label = _draft_words_label(chap.get("draft_words", ""))
    draft_words_target = _draft_words_value(chap.get("draft_words", ""))
    current_body_len = _text_len(chap.get("text", ""))
    draft_words_remaining = _draft_words_remaining(chap.get("draft_words", ""), chap.get("text", ""))
    draft_words_remaining_label = f"{draft_words_remaining}字" if draft_words_remaining else ""
    style_reference = str(project.get("style_reference", "") or "").strip()
    stage_boundary = (chapter_index + 1) % 10 == 0
    draft_task = (
        "请根据当前章节的章节提纲和已有正文草稿续写正文。正文草稿已有内容时，只输出可以直接接在草稿末尾的新正文，"
        "不要重复、概括或改写已有正文；开头要优先承接【续写承接点】里的当前正文结尾原文。"
        "如果章节提纲包含“所属阶段/本章功能/冲突强度/铺垫比例/人物任务/主线任务/结尾钩子”，"
        "必须优先按这些章节规划字段执行；阶段规则只控制节奏、密度和钩子，不得改写本章提纲核心事件。"
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
        "请根据当前章节的章节提纲生成正文草稿。若有上一章结尾，请让开篇自然承接上一章的情绪、场景或悬念。"
        "如果章节提纲包含“所属阶段/本章功能/冲突强度/铺垫比例/人物任务/主线任务/结尾钩子”，"
        "必须优先按这些章节规划字段执行；阶段规则只控制节奏、密度和钩子，不得改写本章提纲核心事件。"
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
                "不要重复、概括或改写已有正文；开头必须自然承接【续写承接点】里的最后状态。"
                if has_current_text else
                "请根据当前章节提纲生成完整正文草稿；若有上一章结尾，开篇必须自然承接其最后状态。"
            )
            + "剧情事件、人物设定、世界规则、关键事实、人物位置、身体状态、持有物品和未完成动作必须按项目资料执行。"
            "如果章节提纲包含所属阶段、本章功能、冲突强度、人物任务、主线任务、本章目标或结尾钩子，"
            "先合并其中指向同一事件的内容，只用去重后的事件约束本章剧情边界和顺序，不得把字段复述次数当成正文强调次数。"
            "旧提纲中的固定伏笔编号不构成硬任务，伏笔只能在符合当前场景和人物动机时自然推进。"
            "【正文风格参考】是唯一写法标准；不得额外套用口语化、网文感、高密度推进、多动作、多对白、少解释、短句、"
            "电影化、分镜化或其他默认写作原则，也不得为了所谓去AI味改变样本的叙述方式。"
            "参考【本章写作长度】安排内容总量，但优先保证本章剧情完整。只输出正文，不输出标题、说明或分析。"
        )
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
            + _long_form_update_contract_instructions(project, chapter_index)
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
    if action == "draft" and str(project.get("style_reference", "") or "").strip():
        draft_task += (
            "本次存在【正文风格参考】时，写法优先级最高：除本章剧情事件、人物设定、世界规则、连续性事实必须按当前项目资料执行外，"
            "叙事口吻、段落长短、换行频率、句式节奏、对白比例、情绪表达方式、信息揭示手法、冲突推进密度、场景细节颗粒度、"
            "悬念落点和章节收束方式，都要尽量贴近【正文风格参考】。"
            "如果通用正文风格、去 AI 味要求、网文感要求或你自己的默认表达习惯与【正文风格参考】冲突，以【正文风格参考】为准。"
        )
        task_map["draft"] = draft_task
    task_text = task_map.get(action, str(action or "").strip() or "请根据当前资料完成本章写作任务。")

    inheritance_rule_lines = [
        "写长篇时请把资料当成连续故事档案。",
        "继承优先级：本章需继承的关键事实 > 当前状态快照/活跃连续性事实 > 前文继承摘要 > 人物卡 > 小说圣经/世界规则 > 设定库。",
        "不得改写已发生事实；如果资料冲突，优先保留更具体、更新、更接近当前章节的记录。",
        "续写时要继承人物公开目标、故事内已知动机、称呼和语言风格，以及伤势、物品、地点、关系和情绪变化。",
        "跨章开头必须继承上一章结尾状态：时间、天气、地点、人物位置、人物手中物品、身体状态和未完成动作不能凭空回退。",
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
                "剧情执行硬约束",
                _build_chapter_execution_hard_constraints(project, chapter_index),
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
            style_target = draft_words_remaining if has_current_text and draft_words_remaining else draft_words_target
            style_target = int(style_target or 0)
            style_profile = _build_style_reference_profile(style_reference, style_target)
            selected_style_reference = (
                style_reference if len(style_reference) <= 8000 else
                _select_style_reference_excerpts(style_reference, chapter_match_text, 6000)
            )
            style_lock_context = (
                "本章进入风格锁定模式。剧情事件、人物设定、世界规则、连续性事实必须按当前项目资料执行；"
                "除此之外，正文写法必须优先模仿【正文风格参考】。\n"
                f"{style_profile}\n"
                + (
                    f"当前文风样本全文约{len(_compact_text(style_reference))}字；上述文风指纹按全文计算，"
                    "【正文风格参考】只放入按段落功能分层选出的代表片段。生成时以全文指纹为总体标准，"
                    "不要把某一个代表片段的局部剧情节奏误当成全部文风。\n"
                    if selected_style_reference != style_reference else ""
                )
                +
                "文风重复与推进边界："
                + _style_repetition_boundary_text()
                + "\n"
                "重点贴近：叙事口吻、段落长短、换行频率、句式节奏、对白比例、描写颗粒度、人物与环境反应的组织方式、"
                "情节或情绪推进密度、信息揭示顺序、情绪表达方式、章节收束方式。\n"
                "进一步观察并模仿统计数字无法覆盖的写法，包括叙述与对白如何衔接、描写落在何种细节、"
                "何时解释背景、何时留白、段落如何起落；不要把任何题材偏好或固定网文模板强加给样本。\n"
                "前文正文只用于继承事实、状态和未完成动作；当它的写法与当前样本不同，以当前样本为准。\n"
                "写完后先静默检查整体段落密度、长短段分布、句式和对白比例是否接近样本，偏差明显时自行重写再输出。\n"
                "如果通用正文风格、去 AI 味要求、网文感要求与样本冲突，一律以样本写法为准。\n"
                "只输出当前小说正文，不输出风格分析、说明或对照。"
            )
            style_reference_context = (
                (
                    f"以下内容从约{len(_compact_text(style_reference))}字完整样本中按对白、动作、说明、情绪和收束分层选取，"
                    "各代表片段彼此独立，不要把它们当作连续剧情。\n"
                    if selected_style_reference != style_reference else
                    "以下样本是本次正文扩写的强制写法参照。"
                )
                + "剧情、人物、设定和连续性事实按当前项目资料执行；"
                "除剧情内容外，正文的叙事口吻、段落长短、换行频率、句式节奏、对白比例、情绪表达方式、信息揭示手法、"
                "冲突推进密度、场景细节颗粒度、悬念落点和章节收束方式，都要尽量贴近这个样本。"
                "不得复用样本里的具体情节、人物关系、句子、比喻或专有名词；不要把样本剧情搬进当前小说。\n\n"
                + selected_style_reference
            )
            style_sections = [
                ("风格锁定规则", style_lock_context, 2200, False),
                ("正文风格参考", style_reference_context, 12000, False),
            ]
    memory_sections = _long_form_memory_sections(project, memory_selection)
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
        knowledge_sections.insert(4, ("后续规划 / 边界", future_plan_text, 5000, True))
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
    raw_context_titles = {"当前章节", "正文风格参考"}
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
