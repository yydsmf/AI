import os
import re
import uuid
import hashlib

from .core import now_str

CHAPTER_ANALYSIS_HASH_VERSION = "2"
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
    valid_statuses = {"未埋", "已埋", "已回收", "废弃"}
    if preserve_manual and current in {"已埋", "已回收", "废弃"}:
        return current
    setup = str(item.get("setup_chapter", "") or "").strip()
    payoff = str(item.get("payoff_chapter", "") or "").strip()
    current_for_keywords = "" if "/" in current or "或" in current else current
    text = " ".join(
        str(item.get(key, "") or "")
        for key in ("name", "setup_chapter", "payoff_chapter", "description")
    )
    text = f"{current_for_keywords} {text}"
    if any(k in text for k in ("废弃", "作废", "弃用", "不再使用")):
        return "废弃"
    recovery_negative = _has_foreshadow_recovery_negative(text)
    setup_negative = any(k in text for k in ("未埋", "尚未埋", "没有埋", "待埋", "还未埋", "尚未出现"))
    if payoff or (not recovery_negative and any(k in text for k in ("已回收", "回收完成", "兑现", "揭晓", "揭示", "解开", "真相大白"))):
        return "已回收"
    if setup or (not setup_negative and any(k in text for k in ("已埋", "埋设", "埋下", "铺垫", "伏笔已经", "线索出现"))):
        return "已埋"
    return current if current in valid_statuses else "未埋"


def _chapter_label(index, chap):
    chap = chap if isinstance(chap, dict) else {}
    title = str(chap.get("title", "") or "").strip()
    if title:
        return f"第 {index} 章「{title}」"
    return f"第 {index} 章"


def _foreshadow_chapter_progress(project, item):
    project = project if isinstance(project, dict) else {}
    item = item if isinstance(item, dict) else {}
    name = str(item.get("name", "") or "").strip()
    if not name:
        return {}
    aliases = _record_aliases(item, name_key="name")
    chapters = project.get("chapters", [])
    chapters = chapters if isinstance(chapters, list) else []
    setup_hits = []
    payoff_hits = []
    setup_keywords = ("埋下", "埋设", "铺垫", "线索出现", "首次出现", "留下", "发现", "露出")
    payoff_keywords = ("回收", "揭晓", "揭示", "兑现", "解开", "真相大白", "确认", "解释")
    for index, chap in enumerate(chapters, 1):
        if not isinstance(chap, dict):
            continue
        text = "\n".join(str(chap.get(key, "") or "") for key in ("title", "summary", "key_facts"))
        if not any(_name_in_text(alias, text) for alias in aliases):
            body_excerpt = _clip_context_text(_dedupe_text_lines(chap.get("text", "")), 1200, keep_tail=True)
            if body_excerpt:
                text = "\n".join([text, body_excerpt])
        if not any(_name_in_text(alias, text) for alias in aliases):
            continue
        label = _chapter_label(index, chap)
        if not _has_foreshadow_recovery_negative(text) and any(keyword in text for keyword in payoff_keywords):
            payoff_hits.append(label)
        elif any(keyword in text for keyword in setup_keywords):
            setup_hits.append(label)
    return {"setup": setup_hits, "payoff": payoff_hits}


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
    for item in project.get("foreshadow_items", []) if isinstance(project.get("foreshadow_items", []), list) else []:
        if not isinstance(item, dict):
            continue
        status = _infer_foreshadow_status(item)
        if status != str(item.get("status", "") or "").strip():
            item["status"] = status
            changed["foreshadows"] += 1
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
_NON_PERSON_EXACT_NAMES = {
    "系统", "任务", "奖励", "惩罚", "商城", "面板", "积分", "主线", "支线", "剧情", "剧情线",
    "剧情点", "设定", "规则", "机制", "金手指", "万人厌系统", "攻略系统", "反派系统",
}
_NON_PERSON_KEYWORDS = (
    "系统", "任务", "奖励", "惩罚", "商城", "积分", "面板", "规则", "机制", "主线", "支线",
    "剧情线", "剧情点", "世界观", "金手指",
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
    paren_match = re.match(r"^([\u4e00-\u9fff]{2,4})[（(]([^（）()]{1,12})[）)]$", raw)
    if paren_match and _looks_like_chinese_person_name(paren_match.group(1)):
        return paren_match.group(1), paren_match.group(2).strip()
    title_pattern = "|".join(re.escape(title) for title in sorted(_CHARACTER_TITLE_WORDS, key=len, reverse=True))
    surname_chars = re.escape(_COMMON_CHINESE_SURNAMES)
    match = re.match(rf"^(.{{0,10}}?(?:{title_pattern}))([{surname_chars}][\u4e00-\u9fff]{{1,3}})$", raw)
    if match and _looks_like_chinese_person_name(match.group(2)):
        return match.group(2), match.group(1).strip()
    for surname in _COMMON_COMPOUND_SURNAMES:
        match = re.match(rf"^(.{{0,10}}?(?:{title_pattern}))({re.escape(surname)}[\u4e00-\u9fff]{{1,2}})$", raw)
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


def _character_lore_type(name):
    compact = _compact_text(name)
    if any(key in compact for key in ("系统", "任务", "奖励", "惩罚", "商城", "积分", "面板", "规则", "机制", "金手指")):
        return "规则"
    if any(key in compact for key in ("主线", "支线", "剧情线", "剧情点")):
        return "事件"
    return "术语"


def _is_non_person_character_candidate(item):
    item = item if isinstance(item, dict) else {"name": item}
    name = _clean_entity_name(item.get("name", ""))
    compact = _compact_text(name)
    if not compact:
        return False
    if compact in _NON_PERSON_EXACT_NAMES:
        return True
    if "系统" in compact:
        return True
    if any(key in compact for key in _NON_PERSON_KEYWORDS):
        role_text = _compact_text(item.get("role", ""))
        notes_text = _compact_text(item.get("notes", ""))
        person_signals = ("人物", "角色", "少女", "少年", "男子", "女子", "公主", "皇子", "公子", "姑娘")
        return not any(signal in role_text or signal in notes_text for signal in person_signals)
    return False


def _character_candidate_as_lore(item, default_description="AI 分析候选"):
    item = item if isinstance(item, dict) else {"name": item}
    name = _clean_entity_name(item.get("name", ""))
    if not name:
        return None
    detail_parts = []
    for label, field in (("身份", "role"), ("目标", "goal"), ("秘密", "secret"), ("语言", "voice"), ("备注", "notes")):
        value = str(item.get(field, "") or "").strip()
        if value and value not in {"AI 分析候选", "文档导入候选"}:
            detail_parts.append(f"{label}：{value}")
    description = "；".join(detail_parts) or default_description
    return {"name": name, "type": _character_lore_type(name), "description": description}


def _prepare_character_candidate(item, default_notes="AI 分析候选"):
    if not isinstance(item, dict):
        return None, None
    name = _clean_entity_name(item.get("name", ""))
    if not name:
        return None, None
    if _is_non_person_character_candidate(item):
        return None, _character_candidate_as_lore(item, default_description=default_notes)
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
        "draft_note": "",
        "import_candidates": {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}},
        "updated_at": now_str(),
    }


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
        "analysis_hash": "",
        "analysis_hash_version": "",
        "analysis_analyzed_at": "",
    }


def _new_lore(index):
    return {
        "id": uuid.uuid4().hex,
        "name": f"设定 {index + 1}",
        "type": "地点",
        "description": "",
    }


def _new_foreshadow(index):
    return {
        "id": uuid.uuid4().hex,
        "name": f"伏笔 {index + 1}",
        "status": "未埋",
        "setup_chapter": "",
        "payoff_chapter": "",
        "description": "",
    }


def _normalize_candidate_analysis_state(data):
    data = data if isinstance(data, dict) else {}
    state = {}
    failed_chunks = []
    for fallback_index, item in enumerate(data.get("failed_candidate_chunks", []), 1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "") or "").strip()
        if not text:
            continue
        failed_chunks.append({
            "index": item.get("index", fallback_index),
            "total": item.get("total", 0),
            "text": text,
            "error": str(item.get("error", "") or ""),
        })
    failed_chunks.sort(key=lambda item: _analysis_chunk_sort_key(item.get("index", 0)))
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
    for key in ("bible", "world_rules", "timeline", "foreshadows", "summary", "draft_note"):
        value = data.get(key, "")
        base[key] = value if isinstance(value, str) else str(value or "")
    for key in ("bible", "world_rules", "timeline", "foreshadows", "summary"):
        base[key] = _dedupe_text_lines(base.get(key, ""))
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
            for key in ("id", "name", "type", "description"):
                item[key] = _as_text(item.get(key, ""))
            item["description"] = _dedupe_text_lines(item.get("description", ""))
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
                    "adaptation_mode",
                    "adaptation_optimization",
                    "adaptation_source_hash",
                    "adapted_at",
                ):
                    chap[key] = _as_text(chap.get(key, ""))
                chap["linked_characters"] = _normalize_name_list(chap.get("linked_characters", []))
    foreshadow_items = data.get("foreshadow_items", [])
    if isinstance(foreshadow_items, list):
        base["foreshadow_items"] = [c for c in foreshadow_items if isinstance(c, dict)]
        for item in base["foreshadow_items"]:
            if not str(item.get("id", "") or "").strip():
                item["id"] = uuid.uuid4().hex
            for key in ("id", "name", "status", "setup_chapter", "payoff_chapter", "description"):
                item[key] = _as_text(item.get(key, ""))
            item["description"] = _dedupe_text_lines(item.get("description", ""))
    candidates = data.get("import_candidates", {})
    if isinstance(candidates, dict):
        normalized_candidates = _normalize_import_candidates(candidates)
        if _import_candidates_has_content(normalized_candidates):
            base["import_candidates"] = normalized_candidates
    analysis_state = _normalize_candidate_analysis_state(data.get("analysis_state", {}))
    if analysis_state:
        base["analysis_state"] = analysis_state
    base["updated_at"] = str(data.get("updated_at") or now_str())
    return base


def _normalize_import_candidates(data):
    data = data if isinstance(data, dict) else {}
    out = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
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
                    out["characters"].append(char_item)
                elif lore_item:
                    lore_item["description"] = _dedupe_text_lines(lore_item.get("description", ""))
                    out["lore"].append(lore_item)
            else:
                if key in {"lore", "foreshadows"}:
                    clone["description"] = _dedupe_text_lines(clone.get("description", ""))
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


def _text_len(value):
    return len(str(value or "").strip())


def _clip_context_text(value, limit, keep_tail=False):
    text = str(value or "").strip()
    limit = int(limit or 0)
    if limit <= 0 or len(text) <= limit:
        return text
    marker = "\n……（内容过长，已裁剪）……\n"
    if keep_tail and limit > len(marker) + 200:
        head_len = max(120, limit // 3)
        tail_len = max(120, limit - head_len - len(marker))
        return text[:head_len].rstrip() + marker + text[-tail_len:].lstrip()
    return text[: max(0, limit - len(marker))].rstrip() + marker.strip()


def _compact_chapter_summary_text(value, max_chars=220, max_sentences=3):
    text = _dedupe_text_lines(value)
    max_chars = max(1, int(max_chars or 1))
    max_sentences = max(1, int(max_sentences or 1))
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
            if len(selected) >= max_sentences:
                break
            next_total = total + len(part)
            if selected and next_total > max_chars:
                break
            selected.append(part)
            total = next_total
        compacted = "".join(selected).strip()
        if compacted:
            return compacted[:max_chars].rstrip()
    return text[:max_chars].rstrip()


def _compact_chapter_key_facts_text(value, max_chars=360, max_items=6):
    text = _dedupe_text_lines(value)
    max_chars = max(1, int(max_chars or 1))
    max_items = max(1, int(max_items or 1))
    if not text:
        return ""
    raw_items = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]\s+|[（(]?\d+[）).、]\s*)", "", line).strip()
        if not line or line in {"无", "没有", "暂无", "无新增"}:
            continue
        sentence_parts = [
            part.strip()
            for part in re.findall(r".+?(?:……|[。！？!?…]+|$)", line)
            if part.strip()
        ]
        raw_items.extend(sentence_parts or [line])

    items = []
    seen = set()
    for item in raw_items:
        item = item.strip()
        if not item:
            continue
        if len(item) > 90:
            item = item[:90].rstrip("，,；;、 ") + "。"
        key = re.sub(r"\s+", "", item)
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
        if len(items) >= max_items:
            break
    compacted = "\n".join(items).strip()
    if len(compacted) <= max_chars:
        return compacted
    kept = []
    total = 0
    for item in items:
        item_len = len(item) + (1 if kept else 0)
        if kept and total + item_len > max_chars:
            break
        kept.append(item)
        total += item_len
    return "\n".join(kept).strip() or compacted[:max_chars].rstrip()


def _clip_lines_balanced(lines, limit, head=8, tail=10):
    lines = [str(line or "").strip() for line in (lines or []) if str(line or "").strip()]
    limit = int(limit or 0)
    if not lines or limit <= 0:
        return ""
    text = "\n".join(lines)
    if len(text) <= limit:
        return text
    if len(lines) <= max(2, int(head or 0) + int(tail or 0)):
        return _clip_context_text(text, limit, keep_tail=True)

    head_count = max(1, int(head or 1))
    tail_count = max(1, int(tail or 1))
    marker = f"……（中间 {max(0, len(lines) - head_count - tail_count)} 条已压缩省略）……"
    out = lines[:head_count] + [marker] + lines[-tail_count:]
    text = "\n".join(out)
    if len(text) <= limit:
        return text
    head_budget = max(1, min(head_count, max(1, head_count // 2)))
    tail_budget = max(1, min(tail_count, max(1, tail_count // 2)))
    marker = f"……（中间 {max(0, len(lines) - head_budget - tail_budget)} 条已压缩省略）……"
    text = "\n".join(lines[:head_budget] + [marker] + lines[-tail_budget:])
    return _clip_context_text(text, limit, keep_tail=True)


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


def _tail_paragraphs(value, limit=1800, paragraphs=4):
    text = str(value or "").strip()
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    if parts:
        text = "\n\n".join(parts[-max(1, int(paragraphs or 1)):])
    return _clip_context_text(text, limit, keep_tail=True)


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
    alias_source = "\n".join(str(item.get(key, "") or "") for key in ("notes", "description"))
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
    return [item for _score, _index, item in ranked[: max(0, int(limit or 0))]]


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
        if not isinstance(char, dict) or _is_non_person_character_candidate(char):
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
        if any(_name_in_text(alias, context_text) for alias in aliases) or _text_matches_any_keyword(context_text, _lore_context_keywords(item)):
            matched.append((index, name))
    return _normalize_name_list([name for _index, name in matched])


_LORE_CONTEXT_GROUPS = (
    ("地点", ("王城", "王都", "都城", "京城", "宫城", "朝堂", "主舞台", "入城", "回城", "城中", "现场")),
    ("组织", ("势力", "门派", "宗门", "朝廷", "官府", "书院", "商会", "军队")),
    ("物品", ("信物", "遗物", "钥匙", "令牌", "虎符", "卷宗", "账册", "证据")),
    ("规则", ("法则", "制度", "禁令", "机制", "契约", "能力", "系统")),
    ("事件", ("旧案", "案件", "阴谋", "计划", "仪式", "战争", "审判")),
)


def _lore_context_keywords(item):
    item = item if isinstance(item, dict) else {}
    name_text = _compact_text(item.get("name", ""))
    type_text = _compact_text(item.get("type", ""))
    desc_text = _compact_text(item.get("description", ""))
    keywords = set()
    for text in (name_text, type_text, desc_text):
        if not text:
            continue
        for group_label, group_keywords in _LORE_CONTEXT_GROUPS:
            if any(keyword in text for keyword in group_keywords):
                keywords.add(group_label)
                keywords.update(group_keywords)
    if "主舞台" in name_text or "主舞台" in desc_text:
        keywords.update(("主舞台", "回到城中", "入城", "回城", "王都", "都城", "京城", "朝堂", "城中"))
    return {keyword for keyword in keywords if keyword}


def _text_matches_any_keyword(text, keywords):
    text = str(text or "")
    return any(keyword and keyword in text for keyword in keywords)


def _lore_context_score(item, context_text):
    item = item if isinstance(item, dict) else {}
    context = _compact_text(context_text)
    if not context:
        return 0
    lore_text = _compact_text(" ".join(str(item.get(key, "") or "") for key in ("name", "type", "description")))
    lore_keywords = _lore_context_keywords(item)
    if not lore_text and not lore_keywords:
        return 0
    score = 0
    if _text_matches_any_keyword(context, lore_keywords):
        score += 120
    for type_label, keywords in _LORE_CONTEXT_GROUPS:
        item_hits = sum(1 for keyword in keywords if keyword in lore_text)
        context_hits = sum(1 for keyword in keywords if keyword in context)
        if item_hits and context_hits:
            score += 160 + min(260, (item_hits + context_hits) * 60)
    if "主舞台" in lore_text and _text_matches_any_keyword(context, ("主舞台", "回到城中", "入城", "回城", "王都", "都城", "京城", "朝堂")):
        score += 180
    if score and str(item.get("description", "") or "").strip():
        score += 30
    return score


_CORE_CHARACTER_DETAIL_KEYWORDS = (
    "主角", "男主", "女主", "主人公", "主线", "核心", "主要", "关键", "重要", "反派",
    "宿敌", "敌手", "boss", "最终", "搭档", "同伴", "队友", "爱人", "恋人", "伴侣",
)
_MINOR_CHARACTER_DETAIL_KEYWORDS = (
    "路人", "过场", "群众", "龙套", "杂兵", "店小二", "侍女", "丫鬟", "仆人", "随从",
    "士兵", "护卫", "侍卫",
)
_CORE_CHARACTER_CONTEXT_GROUPS = (
    ("主角", "男主", "女主", "主人公"),
    ("反派", "宿敌", "敌手", "boss", "最终"),
    ("搭档", "同伴", "队友"),
    ("爱人", "恋人", "伴侣"),
    (
        "关键配角", "重要配角", "主要配角", "核心配角", "关键人物",
        "重要人物", "主要人物", "核心人物", "主线人物", "主线角色",
    ),
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


def _core_character_context_score(char, context_text, include_global=False):
    char = char if isinstance(char, dict) else {}
    if _is_non_person_character_candidate(char):
        return 0
    char_text = _compact_text(" ".join(str(char.get(key, "") or "") for key in (
        "name", "role", "goal", "secret", "voice", "notes", "description",
    ))).lower()
    if not char_text:
        return 0
    has_strong_core_signal = any(
        keyword in char_text
        for keyword in ("主角", "男主", "女主", "主人公", "反派", "宿敌", "敌手", "boss", "最终")
    )
    if (
        any(keyword in char_text for keyword in _MINOR_CHARACTER_DETAIL_KEYWORDS)
        and not has_strong_core_signal
    ):
        return 0

    context = _compact_text(context_text).lower()
    score = 0
    for group in _CORE_CHARACTER_CONTEXT_GROUPS:
        if not any(keyword in char_text for keyword in group):
            continue
        if context and any(keyword in context for keyword in group):
            score += 420
        elif include_global and group[0] in ("主角", "反派"):
            score += 180
        elif include_global:
            score += 90
    if score and any(str(char.get(key, "") or "").strip() for key in ("goal", "secret", "voice", "notes")):
        score += 30
    return score


def _infer_core_character_names(project, chapter, extra_text="", limit=6, include_global=False):
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
    ranked = _prioritize_named_records(
        project.get("characters", []),
        context_text,
        limit=limit,
        score_func=lambda item: _core_character_context_score(
            item,
            context_text,
            include_global=include_global,
        ),
        min_score=120,
    )
    return _normalize_name_list([_clean_entity_name(char.get("name", "")) for char in ranked])


def _character_activity_stats(project):
    project = project if isinstance(project, dict) else {}
    characters = project.get("characters", [])
    characters = characters if isinstance(characters, list) else []
    records = []
    for index, char in enumerate(characters):
        if not isinstance(char, dict) or _is_non_person_character_candidate(char):
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
        core_linked_keys = {
            _compact_text(name)
            for name in _infer_core_character_names(project, chap, text)
            if str(name or "").strip()
        }
        label = _chapter_label(chapter_index, chap)
        for _index, name, aliases in records:
            alias_keys = {_compact_text(alias) for alias in aliases}
            if (
                (alias_keys & linked_keys)
                or (alias_keys & core_linked_keys)
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
            if any(_name_in_text(alias, text) for alias in aliases) or _text_matches_any_keyword(text, _lore_context_keywords(item)):
                stats[name]["chapters"] += 1
                stats[name]["last_chapter"] = label
    return stats


def _character_detail_threshold(total_chapters):
    if total_chapters <= 0:
        return 3
    return max(3, min(8, total_chapters // 8 or 3))


def _should_check_character_details(char, activity_count=0, total_chapters=0):
    char = char if isinstance(char, dict) else {}
    if _is_non_person_character_candidate(char):
        return False
    text = " ".join(str(char.get(key, "") or "") for key in ("name", "role", "notes")).lower()
    if any(keyword in text for keyword in _CORE_CHARACTER_DETAIL_KEYWORDS):
        return True
    threshold = _character_detail_threshold(total_chapters)
    if any(keyword in text for keyword in _MINOR_CHARACTER_DETAIL_KEYWORDS) and activity_count < threshold + 2:
        return False
    return activity_count >= threshold


def _active_character_summary_lines(project, limit=12):
    project = project if isinstance(project, dict) else {}
    characters = project.get("characters", [])
    characters = characters if isinstance(characters, list) else []
    activity = _character_activity_stats(project)
    ranked = []
    for index, char in enumerate(characters):
        if not isinstance(char, dict) or _is_non_person_character_candidate(char):
            continue
        name = _clean_entity_name(char.get("name", ""))
        count = int(activity.get(name, {}).get("chapters", 0) or 0)
        if name and count > 0:
            ranked.append((-count, index, name, char, activity.get(name, {})))
    ranked.sort()
    lines = []
    for _score, _index, name, char, stat in ranked[: max(0, int(limit or 0))]:
        detail_parts = []
        for label, field, clip_limit in (
            ("身份", "role", 80),
            ("目标", "goal", 120),
            ("秘密", "secret", 100),
            ("语言", "voice", 100),
        ):
            value = _clip_context_text(_dedupe_text_lines(char.get(field, "")), clip_limit)
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
    for _score, _index, name, item, stat in ranked[: max(0, int(limit or 0))]:
        typ = str(item.get("type", "") or "其他").strip()
        desc = _clip_context_text(_dedupe_text_lines(item.get("description", "")), 160)
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
    body_words = sum(_text_len(chap.get("text", "")) for chap in chapters if isinstance(chap, dict))
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
        f"当前正文：{stats['body_words']}字，约 {progress * 100:.1f}%",
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


_FUTURE_REVEAL_SUFFIXES = (
    "真相", "真凶", "身份", "死讯", "背叛", "和解", "失踪", "虎符", "密室", "遗物", "回收", "揭晓", "反转",
    "身世", "血脉", "亲缘", "生父", "生母", "亲生父亲", "亲生母亲", "内鬼", "叛徒", "卧底",
    "幕后黑手", "黑手", "凶手", "死因", "死亡", "牺牲", "复活", "叛变", "倒戈", "结局", "归宿",
)


def _future_reveal_markers(text):
    text = str(text or "")
    markers = []
    suffix_pattern = "|".join(re.escape(suffix) for suffix in sorted(_FUTURE_REVEAL_SUFFIXES, key=len, reverse=True))
    for marker in re.findall(
        rf"[\u4e00-\u9fffA-Za-z0-9]{{2,24}}(?:{suffix_pattern})",
        text,
    ):
        marker_text = _compact_text(marker)
        marker_variants = [marker_text]
        marker_core = re.sub(r"^第[一二三四五六七八九十百千万零〇\d]+[章节回卷部集场]?", "", marker_text)
        marker_core = re.sub(
            r"^(?:揭晓|确认|发现|知道|得知|查明|解释|公开|暴露|回收|兑现|写到|点出)+",
            "",
            marker_core,
        )
        if marker_core and marker_core != marker_text:
            marker_variants.append(marker_core)
        for base in tuple(marker_variants):
            for suffix in _FUTURE_REVEAL_SUFFIXES:
                if base.endswith(suffix) and len(base) > len(suffix) + 2:
                    stem = base[:-len(suffix)]
                    if stem:
                        marker_variants.append(stem)
                    marker_variants.append(base[-(len(suffix) + 4):])
        markers.extend(value for value in _normalize_name_list(marker_variants) if len(value) >= 4)
    return _normalize_name_list(markers)


def _future_reveal_match_texts(text):
    compact = _compact_text(text)
    if not compact:
        return []
    values = [compact]
    without_copula = re.sub(r"[是为乃即]", "", compact)
    if without_copula and without_copula != compact:
        values.append(without_copula)
    return values


def _future_boundary_candidates(chapters, current_index, near_window=4, milestone_limit=12):
    chapters = chapters if isinstance(chapters, list) else []
    current_index = int(current_index or 0)
    seen = set()
    candidates = []
    near_end = min(len(chapters), current_index + max(1, int(near_window or 1)))
    for future_index, future in enumerate(chapters[current_index:near_end], current_index + 1):
        if isinstance(future, dict):
            candidates.append((future_index, future))
            seen.add(future_index)
    milestone_items = []
    for future_index, future in enumerate(chapters[near_end:], near_end + 1):
        if not isinstance(future, dict):
            continue
        future_text = "\n".join(
            str(future.get(key, "") or "")
            for key in ("title", "outline", "summary", "key_facts")
        )
        if not _compact_text(future_text):
            continue
        if _is_timeline_milestone(future, future_text):
            milestone_items.append((future_index, future))
    for future_index, future in milestone_items[-max(0, int(milestone_limit or 0)):]:
        if future_index not in seen:
            candidates.append((future_index, future))
            seen.add(future_index)
    return candidates


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
        if _is_non_person_character_candidate(char):
            issues.append(f"人物「{name}」更像规则/术语，建议移到设定库。")
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
        progress = _foreshadow_chapter_progress(project, item)
        if status == "已埋" and not str(item.get("payoff_chapter", "") or "").strip():
            payoff_hits = progress.get("payoff", []) if isinstance(progress, dict) else []
            if payoff_hits:
                sample = "、".join(payoff_hits[:3])
                tail = f"等 {len(payoff_hits)} 章" if len(payoff_hits) > 3 else ""
                issues.append(f"伏笔「{name}」可能已在{sample}{tail}回收；建议确认状态或补上回收章节。")
            else:
                issues.append(f"伏笔「{name}」已埋，但还没有填写回收章节。")
        if status == "已回收" and not str(item.get("setup_chapter", "") or "").strip():
            setup_hits = progress.get("setup", []) if isinstance(progress, dict) else []
            if setup_hits:
                sample = "、".join(setup_hits[:3])
                tail = f"等 {len(setup_hits)} 章" if len(setup_hits) > 3 else ""
                issues.append(f"伏笔「{name}」可能已在{sample}{tail}埋设；建议补上埋设章节。")
            else:
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
        or bool(_infer_core_character_names(project, chap))
    )
    future_plan_ready = 0
    if long_form_mode:
        if not target_words:
            issues.append("建议填写目标字数；长篇项目可按 20万字 这类格式记录。")
        if (
            not str(project.get("summary", "") or "").strip()
            and continuity_total
            and summary_ready < max(1, continuity_total // 3)
        ):
            issues.append("阶段摘要暂缺；优先让章节摘要/关键事实覆盖主要章节，系统会自动压缩成全局摘要。")
        if (
            not str(project.get("timeline", "") or "").strip()
            and continuity_total
            and summary_ready < max(1, continuity_total // 3)
        ):
            issues.append("时间线暂缺；系统会按章节顺序生成草稿，等关键章节摘要齐了再手动修真实时间即可。")
        inheritance_gaps = []
        unlinked_chapters = []
        future_plan_ready = 0
        possible_boundary_leaks = []
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
                _infer_linked_character_names(project, chap) + _infer_core_character_names(project, chap)
            )
            if (
                (has_body or has_outline)
                and (not isinstance(linked, list) or not any(str(x or "").strip() for x in linked))
                and not auto_linked
            ):
                unlinked_chapters.append(f"第 {index} 章「{title}」")
            body_text = str(chap.get("text", "") or "")
            if not body_text or index >= len(chapters):
                continue
            body_match_texts = _future_reveal_match_texts(body_text)
            for future_index, future in _future_boundary_candidates(chapters, index, near_window=4):
                if not isinstance(future, dict):
                    continue
                future_title = str(future.get("title", "") or f"章节 {future_index}").strip()
                future_text = "\n".join(
                    str(future.get(key, "") or "")
                    for key in ("outline", "summary", "key_facts")
                )
                if not _compact_text(future_text):
                    continue
                for marker in _future_reveal_markers(future_text):
                    matched_marker = marker if marker and any(marker in body_text for body_text in body_match_texts) else ""
                    if matched_marker:
                        possible_boundary_leaks.append(f"第 {index} 章「{title}」可能提前写到{future_title}的「{matched_marker}」")
                        break
                if possible_boundary_leaks and possible_boundary_leaks[-1].startswith(f"第 {index} 章"):
                    break
        if inheritance_gaps:
            sample = "、".join(inheritance_gaps[:5])
            tail = f"等 {len(inheritance_gaps)} 章" if len(inheritance_gaps) > 5 else ""
            issues.append(f"{sample}{tail} 缺少摘要/关键事实；应用 AI 正文后会自动补，历史章节可按需补齐。")
        if len(unlinked_chapters) >= max(4, stats["chapters"] // 3):
            sample = "、".join(unlinked_chapters[:5])
            tail = f"等 {len(unlinked_chapters)} 章" if len(unlinked_chapters) > 5 else ""
            issues.append(f"{sample}{tail} 没有关联人物；应用 AI 提纲/正文/摘要时会自动识别已有角色并回填。")
        if future_plan_ready < max(2, stats["chapters"] // 6) and stats["chapters"] >= 12:
            issues.append("后续章节规划较少；章节 AI 会尽量靠前文续写，但补几章粗提纲能明显降低越界和重复。")
        if possible_boundary_leaks:
            sample = "、".join(possible_boundary_leaks[:3])
            tail = f"等 {len(possible_boundary_leaks)} 处" if len(possible_boundary_leaks) > 3 else ""
            issues.append(f"{sample}{tail}；建议确认当前章是否提前兑现后续规划。")
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
IMPORT_TYPE_OPTIONS = ["小说", "短剧 / 分集剧本", "电影 / 长剧剧本", "自由文本"]
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


def _project_search_sources(project):
    project = project if isinstance(project, dict) else {}
    sources = []
    meta = project.get("meta", {}) if isinstance(project.get("meta"), dict) else {}
    sources.append(("项目", "基础信息", "\n".join([
        str(meta.get("title", "")),
        str(meta.get("genre", "")),
        str(meta.get("style", "")),
        str(meta.get("premise", "")),
    ])))
    for label, key in (
        ("小说圣经", "bible"),
        ("世界观 / 规则", "world_rules"),
        ("时间线", "timeline"),
        ("伏笔备注", "foreshadows"),
        ("摘要 / 日志", "summary"),
    ):
        sources.append((label, label, project.get(key, "")))

    for index, char in enumerate(project.get("characters", []) if isinstance(project.get("characters"), list) else [], 1):
        if not isinstance(char, dict):
            continue
        name = char.get("name") or f"人物 {index}"
        text = "\n".join(str(char.get(k, "")) for k in ("name", "role", "goal", "secret", "voice", "notes"))
        sources.append(("人物卡", name, text))

    for index, lore in enumerate(project.get("lore", []) if isinstance(project.get("lore"), list) else [], 1):
        if not isinstance(lore, dict):
            continue
        name = lore.get("name") or f"设定 {index}"
        text = "\n".join(str(lore.get(k, "")) for k in ("name", "type", "description"))
        sources.append(("设定库", name, text))

    for index, item in enumerate(project.get("foreshadow_items", []) if isinstance(project.get("foreshadow_items"), list) else [], 1):
        if not isinstance(item, dict):
            continue
        name = item.get("name") or f"伏笔 {index}"
        text = "\n".join(str(item.get(k, "")) for k in ("name", "status", "setup_chapter", "payoff_chapter", "description"))
        sources.append(("伏笔", name, text))

    for index, chap in enumerate(project.get("chapters", []) if isinstance(project.get("chapters"), list) else [], 1):
        if not isinstance(chap, dict):
            continue
        name = chap.get("title") or f"章节 {index}"
        linked = chap.get("linked_characters", [])
        if isinstance(linked, list):
            linked_text = "、".join(str(x) for x in linked if str(x).strip())
        else:
            linked_text = ""
        text = "\n".join(
            str(chap.get(k, ""))
            for k in ("title", "status", "outline", "text", "summary", "key_facts")
        )
        if linked_text:
            text = f"{text}\n关联人物：{linked_text}"
        sources.append(("章节", name, text))
    return sources


def _search_excerpt(text, keyword, radius=42):
    text = str(text or "").replace("\r", "").replace("\n", " ").strip()
    if not text:
        return ""
    lower = text.lower()
    key = str(keyword or "").lower()
    pos = lower.find(key)
    if pos < 0:
        return text[: radius * 2].strip()
    start = max(0, pos - radius)
    end = min(len(text), pos + len(str(keyword or "")) + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


def _build_search_result_text(project, keyword):
    keyword = str(keyword or "").strip()
    if not keyword:
        return "请输入关键词。"
    results = []
    for group, title, text in _project_search_sources(project):
        text = str(text or "")
        if keyword.lower() not in text.lower():
            continue
        results.append((group, title, _search_excerpt(text, keyword)))
    if not results:
        return f"没有找到：{keyword}"
    group_counts = {}
    for group, _title, _excerpt in results:
        group_counts[group] = group_counts.get(group, 0) + 1
    count_text = " ｜ ".join(f"{group} {count}" for group, count in group_counts.items())
    lines = [f"找到 {len(results)} 条结果：{keyword}", count_text, ""]
    for index, (group, title, excerpt) in enumerate(results, 1):
        lines.append(f"{index}. [{group}] {title}")
        if excerpt:
            lines.append(f"   {excerpt}")
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


def _chapter_analysis_hash(chap):
    text = _chapter_analysis_hash_text(chap, include_linked=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest() if text.strip() else ""


def _chapter_analysis_legacy_hash(chap):
    text = _chapter_analysis_hash_text(chap, include_linked=False)
    return hashlib.sha1(text.encode("utf-8")).hexdigest() if text.strip() else ""


def _chapter_needs_analysis(chap):
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
    return True


def _chapter_analysis_is_current(chap):
    current = _chapter_analysis_hash(chap)
    if not current:
        return False
    chap = chap if isinstance(chap, dict) else {}
    return (
        current == str(chap.get("analysis_hash", "") or "").strip()
        and str(chap.get("analysis_hash_version", "") or "").strip() == CHAPTER_ANALYSIS_HASH_VERSION
    )


def _mark_chapters_analyzed(chapters, chapter_ids):
    ids = {str(x) for x in (chapter_ids or []) if str(x)}
    count = 0
    for chap in chapters if isinstance(chapters, list) else []:
        if not isinstance(chap, dict):
            continue
        if str(chap.get("id", "") or "") not in ids:
            continue
        current = _chapter_analysis_hash(chap)
        if not current:
            continue
        chap["analysis_hash"] = current
        chap["analysis_hash_version"] = CHAPTER_ANALYSIS_HASH_VERSION
        chap["analysis_analyzed_at"] = now_str()
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
    words = _text_len(chap.get("text", ""))
    draft_words = _draft_words_label(chap.get("draft_words", ""))
    unit = UNIT_TYPE_LABELS.get(str(chap.get("unit_type", "chapter") or "chapter"), "章")
    parts = [f"{index + 1}. {unit}｜{title}", status, f"{words}字"]
    if draft_words:
        parts.append(f"扩写约{draft_words}")
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
    status = str(item.get("status", "") or "").strip()
    setup = str(item.get("setup_chapter", "") or "").strip()
    payoff = str(item.get("payoff_chapter", "") or "").strip()
    tail = " -> ".join(x for x in (setup, payoff) if x)
    return "  ·  ".join(str(x) for x in (name, status, tail) if str(x).strip())


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
    summary = _clip_context_text(_dedupe_text_lines(chap.get("summary", "")), summary_limit)
    key_facts = _clip_context_text(_dedupe_text_lines(chap.get("key_facts", "")), facts_limit)
    parts = []
    if summary:
        parts.append("摘要：" + summary)
    if key_facts:
        parts.append("关键事实：" + key_facts)
    if not parts and include_outline_fallback:
        outline = _clip_context_text(_dedupe_text_lines(chap.get("outline", "")), 260)
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


def _build_previous_inheritance_text(chapters, chapter_index):
    recent_start = max(0, chapter_index - 12)
    recent_lines = []
    for index, chap in enumerate(chapters[recent_start:chapter_index], recent_start + 1):
        if not isinstance(chap, dict):
            continue
        line = _chapter_reference_line(index, chap, include_outline_fallback=True, text_fallback_limit=420)
        if line:
            recent_lines.append(line)

    older_lines = []
    older_milestone_lines = []
    for index, chap in enumerate(chapters[:recent_start], 1):
        if not isinstance(chap, dict):
            continue
        line = _chapter_reference_line(index, chap, summary_limit=120, facts_limit=260, text_fallback_limit=240)
        if line:
            older_lines.append(line)
            if _is_timeline_milestone(chap, line):
                older_milestone_lines.append(line)

    parts = []
    if recent_lines:
        parts.append("近期章节（优先继承）：\n" + "\n".join(recent_lines))
    if older_lines:
        older_text = _clip_lines_balanced(older_lines, 6500, head=10, tail=12)
        parts.append("远期关键事实（已压缩，保留开端与近中段）：\n" + older_text)
    if older_milestone_lines:
        milestone_text = _clip_lines_balanced(older_milestone_lines[-16:], 2600, head=6, tail=8)
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
    if len(events) <= 32:
        return [line for _index, line, _is_milestone in events]

    recent_events = events[-12:]
    older_events = events[:-12]
    milestone_events = [
        (index, line, is_milestone)
        for index, line, is_milestone in older_events
        if is_milestone
    ]
    milestone_events = milestone_events[-16:]

    lines = ["近期章节："]
    lines.extend(line for _index, line, _is_milestone in recent_events)
    if older_events:
        lines.extend([
            "",
            "早期/中段时间线（已平衡压缩）：",
            _clip_lines_balanced(
                [line for _index, line, _is_milestone in older_events],
                max(2400, total_limit // 2),
                head=8,
                tail=10,
            ),
        ])
    if milestone_events:
        lines.extend([
            "",
            "关键转折锚点：",
            _clip_lines_balanced(
                [line for _index, line, _is_milestone in milestone_events],
                max(1800, total_limit // 3),
                head=6,
                tail=8,
            ),
        ])
    return lines


def _summary_section_lines(events, total_limit=8200):
    events = events if isinstance(events, list) else []
    if not events:
        return []
    if len(events) <= 32:
        recent_count = min(12, len(events))
        older_lines = [line for _index, line, _is_milestone in events[:-recent_count]]
        recent_lines = [line for _index, line, _is_milestone in events[-recent_count:]]
        lines = ["近期章节：", *recent_lines]
        if older_lines:
            lines.extend(["", "长期关键事实：", _clip_lines_balanced(older_lines, 7000, head=10, tail=12)])
        return lines

    recent_events = events[-12:]
    older_events = events[:-12]
    milestone_events = [
        (index, line, is_milestone)
        for index, line, is_milestone in older_events
        if is_milestone
    ][-16:]
    lines = ["近期章节："]
    lines.extend(line for _index, line, _is_milestone in recent_events)
    if older_events:
        lines.extend([
            "",
            "长期关键事实（已平衡压缩）：",
            _clip_lines_balanced(
                [line for _index, line, _is_milestone in older_events],
                max(3000, total_limit // 2),
                head=8,
                tail=10,
            ),
        ])
    if milestone_events:
        lines.extend([
            "",
            "关键转折锚点：",
            _clip_lines_balanced(
                [line for _index, line, _is_milestone in milestone_events],
                max(2200, total_limit // 3),
                head=6,
                tail=8,
            ),
        ])
    return lines


def _build_project_summary_draft(project):
    project = project if isinstance(project, dict) else {}
    meta = project.get("meta", {}) if isinstance(project.get("meta"), dict) else {}
    chapters = project.get("chapters", [])
    chapters = chapters if isinstance(chapters, list) else []
    events = []
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

    active_character_lines = _active_character_summary_lines(project, limit=12)
    if active_character_lines:
        lines.extend([
            "",
            "高频人物快照：",
            *_clip_context_text("\n".join(active_character_lines), 3000).splitlines(),
        ])
    active_lore_lines = _active_lore_summary_lines(project, limit=12)
    if active_lore_lines:
        lines.extend([
            "",
            "高频设定快照：",
            *_clip_context_text("\n".join(active_lore_lines), 3000).splitlines(),
        ])

    active_foreshadows = [
        line
        for _item, line in _rank_open_foreshadow_lines(
            project.get("foreshadow_items", []),
            limit=60,
            route_style="fields",
            skip_placeholders=False,
            include_desc=False,
        )
    ]
    if active_foreshadows:
        lines.extend(["", "未完成伏笔：", *_clip_context_text("\n".join(active_foreshadows), 3000).splitlines()])
    return "\n".join(str(line) for line in lines).strip()


def _build_project_timeline_draft(project):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", [])
    chapters = chapters if isinstance(chapters, list) else []
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
            include_outline_fallback=True,
            text_fallback_limit=240,
        )
        if line:
            linked = chap.get("linked_characters", [])
            auto_linked = _infer_linked_character_names(project, chap)
            auto_core_linked = _infer_core_character_names(project, chap)
            linked_names = _normalize_name_list(
                (linked if isinstance(linked, list) else []) + auto_linked + auto_core_linked
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
    items = project.get("foreshadow_items", [])
    items = items if isinstance(items, list) else []
    grouped = {"未埋": [], "已埋": [], "已回收": [], "废弃": [], "其他": []}
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "").strip() or f"伏笔 {index}"
        status = str(item.get("status", "") or "").strip() or "其他"
        group = status if status in grouped else "其他"
        setup = str(item.get("setup_chapter", "") or "").strip()
        payoff = str(item.get("payoff_chapter", "") or "").strip()
        desc = _clip_context_text(_dedupe_text_lines(item.get("description", "")), 180)
        route = " -> ".join(x for x in (setup, payoff) if x) or "未填写章节"
        tail = f"｜{desc}" if desc else ""
        line = f"- {name}｜{route}{tail}"
        if group in {"未埋", "已埋"}:
            score, tie_index = _open_foreshadow_queue_score(item, index)
            grouped[group].append((-score, tie_index, line))
        elif group in {"已回收", "废弃"}:
            grouped[group].append((0, -index, line))
        else:
            grouped[group].append((0, index, line))
    if not any(grouped.values()):
        return ""

    limits = {"未埋": 20, "已埋": 40, "已回收": 8, "废弃": 3, "其他": 8}
    lines = ["伏笔汇总草稿"]
    for status in ("未埋", "已埋", "已回收", "废弃", "其他"):
        group_items = grouped[status]
        if not group_items:
            continue
        group_items.sort()
        group_lines = [line for _score, _tie_index, line in group_items]
        limit = limits.get(status, 8)
        selected = group_lines[:limit]
        omitted = len(group_lines) - len(selected)
        lines.extend(["", status + "：", *selected])
        if omitted > 0:
            lines.append(f"- ……另有 {omitted} 条{status}伏笔已省略")
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
    desc = _dedupe_text_lines(item.get("description", ""))
    compact_desc = _compact_text(desc).strip("。.!！?？；;，,、")
    if compact_desc:
        score += 240 + min(220, len(compact_desc) // 2)
    if compact_desc in {"AI分析候选", "文档导入候选", "后续处理", "待后续处理", "待回收"}:
        score -= 900
    return score, index


def _open_foreshadow_line(item, index, route_style="route", desc_limit=160, include_desc=True):
    item = item if isinstance(item, dict) else {}
    name = str(item.get("name", "") or "").strip() or f"伏笔 {index}"
    status = str(item.get("status", "") or "").strip()
    setup = str(item.get("setup_chapter", "") or "").strip()
    payoff = str(item.get("payoff_chapter", "") or "").strip()
    desc = _dedupe_text_lines(item.get("description", ""))
    desc_text = _clip_context_text(desc, desc_limit) if include_desc else ""
    if route_style == "fields":
        return f"- {name}｜{status}｜埋设：{setup}｜回收：{payoff}" + (f"｜{desc_text}" if desc_text else "")
    route = " -> ".join(x for x in (setup, payoff) if x) or "未填写章节"
    tail = f"｜{desc_text}" if desc_text else ""
    return f"- {name}｜{status}｜{route}{tail}"


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
        desc = _dedupe_text_lines(item.get("description", ""))
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
    selected = candidates[: max(1, int(limit or 1))]
    return [(item, line) for _score, _tie_index, item, line in selected]


def _build_open_foreshadow_queue(project, selected_items=None, limit=12, current_order=None):
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
        current_order=current_order,
    )
    selected = candidates[: max(1, int(limit or 1))]
    lines = [line for _score, _tie_index, _item, line in selected]
    if not lines:
        return ""
    omitted = max(0, len(candidates) - len(lines))
    if omitted > 0:
        lines.append(f"- ……另有 {omitted} 条开放伏笔未列出")
    return "开放伏笔队列（未被本章命中，仅提醒，避免遗忘；不要无计划回收）：\n" + "\n".join(lines)


def _recent_chapter_context(chapters, chapter_index, window=6, project=None):
    chapters = chapters if isinstance(chapters, list) else []
    project = project if isinstance(project, dict) else {}
    start = max(0, int(chapter_index or 0) - int(window or 0))
    parts = []
    linked = []
    for index, item in enumerate(chapters[start:chapter_index], start + 1):
        if not isinstance(item, dict):
            continue
        line = _chapter_reference_line(
            index,
            item,
            summary_limit=260,
            facts_limit=420,
            include_outline_fallback=True,
            text_fallback_limit=320,
        )
        if line:
            parts.append(line)
        names = item.get("linked_characters", [])
        if isinstance(names, list):
            linked.extend(str(name) for name in names if str(name).strip())
        if project:
            linked.extend(_infer_linked_character_names(project, item))
            linked.extend(_infer_core_character_names(project, item))
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
            linked = chap.get("linked_characters", [])
            linked_keys = {
                _compact_text(item)
                for item in (linked if isinstance(linked, list) else _normalize_name_list(linked))
                if str(item or "").strip()
            }
            text = "\n".join(
                str(chap.get(field, "") or "")
                for field in ("title", "outline", "summary", "key_facts", "text")
            )
            if not ((alias_keys & linked_keys) or any(_name_in_text(alias, text) for alias in aliases)):
                continue
            line = _chapter_reference_line(
                index + 1,
                chap,
                summary_limit=140,
                facts_limit=220,
                include_outline_fallback=True,
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
    if 0 <= chapter_index - 1 < len(chapters):
        prev = chapters[chapter_index - 1]
        if isinstance(prev, dict):
            prev_tail = _tail_paragraphs(prev.get("text", ""), limit=1600, paragraphs=3)
            if prev_tail:
                title = str(prev.get("title", "") or f"章节 {chapter_index}").strip()
                parts.append(f"上一章「{title}」结尾：\n{prev_tail}")
    if 0 <= chapter_index < len(chapters):
        current = chapters[chapter_index]
        if isinstance(current, dict):
            current_tail = _tail_paragraphs(current.get("text", ""), limit=2000, paragraphs=4)
            if current_tail:
                parts.append("当前正文最后几段（续写应从这里自然接上，不要重复）：\n" + current_tail)
    return "\n\n".join(parts)


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


def _build_chapter_ai_context(project, chapter_index, action):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", [])
    if chapter_index < 0 or chapter_index >= len(chapters):
        raise ValueError("请先选择一个章节。")
    meta = project.get("meta", {})
    chap = chapters[chapter_index]
    linked_characters = chap.get("linked_characters", [])
    if not isinstance(linked_characters, list):
        linked_characters = []
    recent_context_text, recent_linked_characters = _recent_chapter_context(chapters, chapter_index, window=6, project=project)
    chapter_match_text = "\n".join([
        str(chap.get("title", "") or ""),
        str(chap.get("outline", "") or ""),
        str(chap.get("text", "") or ""),
        str(chap.get("summary", "") or ""),
        str(chap.get("key_facts", "") or ""),
        recent_context_text,
        " ".join(str(name) for name in linked_characters),
        " ".join(str(name) for name in recent_linked_characters),
    ])
    inferred_current_characters = _infer_linked_character_names(project, chap, chapter_match_text)
    inferred_core_characters = _infer_core_character_names(
        project,
        chap,
        chapter_match_text,
        include_global=True,
    )
    inherited_linked_characters = _normalize_name_list(
        list(linked_characters) + inferred_current_characters + inferred_core_characters + recent_linked_characters
    )

    def clean_context_text(value, limit, keep_tail=False, dedupe=True):
        text = _dedupe_text_lines(value) if dedupe else str(value or "").strip()
        return _clip_context_text(text, limit, keep_tail=keep_tail)

    selected_characters = _prioritize_named_records(
        project.get("characters", []),
        chapter_match_text,
        linked_names=inherited_linked_characters,
        limit=24,
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
            ("秘密", "secret", 160),
            ("语言", "voice", 180),
            ("备注", "notes", 220),
        ]
        detail = "｜".join(
            f"{label}：{clean_context_text(char.get(field, ''), limit)}"
            for label, field, limit in fields
            if str(char.get(field, "") or "").strip()
        )
        recent_state = character_recent_map.get(_compact_text(name), "")
        if recent_state:
            recent_state = "最近状态：" + clean_context_text(recent_state, 520)
            detail = f"{detail}｜{recent_state}" if detail else recent_state
        character_lines.append(f"- {name}｜{detail}" if detail else f"- {name}")

    selected_lore = _prioritize_named_records(
        project.get("lore", []),
        chapter_match_text,
        name_key="name",
        limit=28,
        score_func=lambda item: _lore_context_score(item, chapter_match_text),
    )
    lore_recent_map = _record_recent_context_map(project, selected_lore, chapter_index, name_key="name")
    lore_lines = []
    for item in selected_lore:
        name = str(item.get("name", "") or "").strip()
        if name:
            recent_state = lore_recent_map.get(_compact_text(name), "")
            recent_tail = f"｜最近状态：{clean_context_text(recent_state, 420)}" if recent_state else ""
            lore_lines.append(f"- {name}｜{item.get('type','其他')}｜{clean_context_text(item.get('description',''), 300)}{recent_tail}")

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
        if status == "已回收":
            score -= 20
        return score

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
        foreshadow_lines.append(
            f"- {name}｜{item.get('status','')}｜埋设：{item.get('setup_chapter','')}｜回收：{item.get('payoff_chapter','')}｜{clean_context_text(item.get('description',''), 300)}"
        )
    previous_summary = _build_previous_inheritance_text(chapters, chapter_index)
    continuation_text = _build_chapter_continuation_text(chapters, chapter_index)
    future_plan_text = _build_future_plan_text(chapters, chapter_index)
    has_current_text = bool(_compact_text(chap.get("text", "")))
    reverse_from_body = action in {"outline", "summary"} and has_current_text
    draft_words_label = _draft_words_label(chap.get("draft_words", ""))
    draft_words_target = _draft_words_value(chap.get("draft_words", ""))
    current_body_len = _text_len(chap.get("text", ""))
    draft_words_remaining = _draft_words_remaining(chap.get("draft_words", ""), chap.get("text", ""))
    draft_words_remaining_label = f"{draft_words_remaining}字" if draft_words_remaining else ""
    draft_task = (
        "请根据当前章节的章节提纲和已有正文草稿续写正文。正文草稿已有内容时，只输出可以直接接在草稿末尾的新正文，"
        "不要重复、概括或改写已有正文；开头要优先承接【续写承接点】里的当前正文最后几段。"
        "优先参考本章需继承的关键事实，其次参考本章摘要、前文摘要、人物目标、语言风格和世界规则。"
        "参考【本章写作长度】安排详略，但不要为了贴字数牺牲完整场景、冲突收束和正文质量；只输出正文内容。"
        if has_current_text else
        "请根据当前章节的章节提纲生成正文草稿。若有上一章结尾，请让开篇自然承接上一章的情绪、场景或悬念。"
        "优先参考本章需继承的关键事实，其次参考本章摘要、前文摘要、人物目标、语言风格和世界规则。"
        "参考【本章写作长度】安排详略，但不要为了贴字数牺牲完整场景、冲突收束和正文质量；只输出正文内容。"
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
            "包括人物关系、线索、伏笔、伤势、物品、地点变化和情绪关系变化。不要评价，不要写创作建议。"
            "请严格按以下格式输出三段内容：\n"
            "本章摘要：...\n"
            "本章需继承的关键事实：...\n"
            "本章关联人物：人物A、人物B（只列本章实际出现或被直接推动的人物；优先使用人物卡里的具体姓名，不要只写主角/反派/配角；没有则写无）\n"
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
        "继承优先级：本章需继承的关键事实 > 时间线 > 前文继承摘要 > 人物卡 > 小说圣经/世界规则 > 设定库。",
        "不得改写已发生事实；如果资料冲突，优先保留更具体、更新、更接近当前章节的记录。",
        "续写时要继承人物目标、秘密、称呼、语言风格，以及伤势、物品、地点、关系和情绪变化。",
        "伏笔只在合适章节推进；已回收伏笔不要重复当新线索。缺资料时保持克制，不要补出会影响后文的新设定。",
    ]
    if reverse_from_body:
        inheritance_rule_lines.append("本次是正文后的资料回填：提纲、摘要和关键事实都只能记录正文草稿中已经发生的内容，不要补写后续规划。")
    else:
        inheritance_rule_lines.append("后续规划只用于控制边界：当前章可以铺垫下一章，但不要提前兑现后续章节明确安排的真相、转折或结局。")
    inheritance_rules = "\n".join(inheritance_rule_lines)

    current_text_limit = 30000 if action in {"outline", "summary"} else 15000
    draft_words_line = draft_words_label if draft_words_label else "未填写"
    current_lines = [
        f"章节标题：{chap.get('title', '')}",
        f"章节状态：{chap.get('status', '')}",
        f"本章扩写字数：{draft_words_line}",
        f"关联人物：{', '.join(inherited_linked_characters)}",
    ]
    if reverse_from_body:
        current_lines.append("章节提纲：已省略；本次必须仅根据正文草稿反向整理，避免旧提纲或后续规划影响结果。")
    else:
        current_lines.append(f"章节提纲：{clean_context_text(chap.get('outline', ''), 6000)}")
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
            "这是软性参考目标，不是硬性字数要求；优先保证完整小场景、冲突收束、人物反应和正文质量。\n"
            "本章扩写字数代表本章正文希望补到的大约总量；如果正文草稿已有内容，只输出剩余部分。\n"
            "可以略高或略低于目标，避免为贴字数删掉关键结尾、跳过必要铺垫或强行拉长解释；"
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

    if reverse_from_body:
        timeline_context = "暂无"
        summary_context = "暂无"
    else:
        auto_timeline = _build_project_timeline_draft(project)
        timeline_context = context_parts(
            project.get("timeline", ""),
            "自动章节顺序线：\n" + auto_timeline if auto_timeline else "",
        )
        auto_summary = _build_project_summary_draft(project)
        summary_context = context_parts(
            project.get("summary", ""),
            "自动章节压缩：\n" + auto_summary if auto_summary else "",
        )
    current_story_order = _story_order_from_text(chap.get("title", ""))
    if current_story_order == _STORY_ORDER_MISSING:
        current_story_order = chapter_index + 1
    open_foreshadows = _build_open_foreshadow_queue(
        project,
        selected_foreshadows,
        current_order=current_story_order,
    )
    foreshadow_context = context_parts(
        "\n".join(foreshadow_lines),
        project.get("foreshadows", ""),
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
    common_sections = [
        ("项目核心信息", core_project_info, 1200, False),
        ("长篇进度 / 节奏", long_form_progress, 1200, False),
        ("长篇继承规则", inheritance_rules, 1500, False),
        ("本次任务", task_text, 2200, False),
        ("项目基础", "\n".join([
            f"项目总目标字数：{_target_words_label(meta.get('target_words', ''))}",
        ]), 500, False),
    ]
    if action == "draft":
        common_sections.insert(3, ("本章写作长度", chapter_length_section, 500, False))
    if reverse_from_body:
        knowledge_sections = [
            ("小说圣经", _dedupe_text_lines(project.get("bible", "")) or "暂无", 2400, True),
            ("世界观 / 规则", _dedupe_text_lines(project.get("world_rules", "")) or "暂无", 1800, True),
            ("前文继承摘要", previous_summary, 5000, True),
            ("近几章连续性", recent_context_section, 2600, True),
            ("本章相关人物", "\n".join(character_lines) or "暂无", 4200, False),
            ("本章相关设定", "\n".join(lore_lines) or "暂无", 2800, False),
        ]
    else:
        knowledge_sections = [
            ("小说圣经", _dedupe_text_lines(project.get("bible", "")) or "暂无", 3600, True),
            ("世界观 / 规则", _dedupe_text_lines(project.get("world_rules", "")) or "暂无", 2800, True),
            ("时间线", timeline_context, 5000, True),
            ("续写承接点", continuation_text or "暂无", 3600, True),
            ("前文继承摘要", previous_summary, 9000, True),
            ("近几章连续性", recent_context_section, 3600, True),
            ("本章相关人物", "\n".join(character_lines) or "暂无", 6000, False),
            ("本章相关设定", "\n".join(lore_lines) or "暂无", 4200, False),
            ("本章相关伏笔", foreshadow_context, 5000, True),
            ("全局摘要 / 日志", summary_context, 5000, True),
        ]
    if action == "draft":
        knowledge_sections.insert(4, ("后续规划 / 边界", future_plan_text, 3600, True))
    current_section_item = (
        "当前章节",
        current_section,
        34000 if action == "summary" else 18000,
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
    max_context_chars = 56000
    out = []
    used = 0
    for title, content, limit, keep_tail in sections:
        remaining = max_context_chars - used
        if remaining <= 1200:
            break
        section_content = content if title == "当前章节" else _dedupe_text_lines(content)
        clipped = _clip_context_text(section_content, min(limit, remaining - 64), keep_tail=keep_tail) or "暂无"
        block = f"【{title}】\n{clipped}"
        out.append(block)
        used += len(block) + 2
    return "\n\n".join(out)
