import json

from .novel_v2_utils import (
    _body_display_len,
    _clip_complete_text,
    _compact_chapter_key_facts_text,
    _compact_chapter_summary_text,
    _dedupe_text_lines,
    _normalize_foreshadow_code,
    _normalize_name_list,
    _stable_character_notes_context,
    _stable_foreshadow_description_context,
    _stable_lore_description_context,
)


TASK_CONTEXT_CHAR_LIMITS = {
    "rolling_plan": 44000,
    "checkpoint": 44000,
    "execution_outline": 36000,
    "draft": 40000,
    "audit": 42000,
    "postwrite": 42000,
    "completion_audit": 50000,
}

TASK_CONTEXT_LABELS = {
    "rolling_plan": "滚动规划",
    "checkpoint": "阶段复盘",
    "execution_outline": "当前章执行提纲",
    "draft": "正文扩写",
    "audit": "正文质量审校",
    "postwrite": "写后资料与状态更新",
    "completion_audit": "全书完结审计",
}

_OPEN_FORESHADOW_STATUSES = {"未埋", "已埋"}
_FORESHADOW_PRIORITY_RANK = {"必须处理": 0, "高": 1, "重要": 1, "常规": 2, "低": 3, "休眠": 4}


def _text(value):
    return str(value or "").strip()


def _chapter_id(chapter):
    return _text(chapter.get("id", "")) if isinstance(chapter, dict) else ""


def _json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _clip(value, limit, keep_tail=False):
    return _clip_complete_text(_dedupe_text_lines(value), int(limit or 0), keep_tail=keep_tail)


def _section(name, text, required=False):
    text = _text(text)
    if not text:
        return None
    return {"name": name, "text": text, "required": bool(required)}


def _assemble_sections(sections, total_limit):
    sections = [item for item in sections if item and _text(item.get("text", ""))]
    total_limit = max(8000, int(total_limit or 0))
    rendered = []
    manifest = []
    used = 0
    omitted = []
    for index, item in enumerate(sections):
        name = _text(item.get("name", "")) or "资料"
        text = _text(item.get("text", ""))
        prefix = f"【{name}】\n"
        separator = "\n\n" if rendered else ""
        required_after = sum(
            len(f"【{_text(later.get('name', '')) or '资料'}】\n")
            + len(_text(later.get("text", "")))
            + 2
            for later in sections[index + 1 :]
            if later.get("required")
        )
        available = total_limit - used - len(prefix) - len(separator) - required_after
        original_chars = len(text)
        if item.get("required") and original_chars > available:
            raise ValueError(
                f"{name}约{original_chars}字，超过当前任务剩余上下文预算{max(0, available)}字，不能静默截断。"
            )
        if not item.get("required") and available <= 80:
            omitted.append(name)
            continue
        if original_chars > available:
            text = _clip(text, available, keep_tail=True)
        block = prefix + text
        rendered.append(block)
        block_chars = len(separator) + len(block)
        used += block_chars
        manifest.append(
            {
                "name": name,
                "source_chars": original_chars,
                "included_chars": len(text),
                "truncated": len(text) < original_chars,
                "required": bool(item.get("required")),
            }
        )
    return {
        "text": "\n\n".join(rendered).strip(),
        "manifest": manifest,
        "omitted_sections": omitted,
        "total_chars": used,
        "limit_chars": total_limit,
    }


def _core_contract(project):
    meta = project.get("meta", {}) if isinstance(project.get("meta"), dict) else {}
    lines = [
        f"书名：{_text(meta.get('title'))}",
        f"类型：{_text(meta.get('genre'))}",
        f"文风：{_text(meta.get('style'))}",
        f"叙事人称：{_text(meta.get('pov'))}",
        f"目标字数：{_text(meta.get('target_words'))}",
        f"故事核心：{_clip(meta.get('premise'), 1800)}",
        "小说圣经：\n" + (_clip(project.get("bible"), 3800) or "暂无"),
        "世界硬规则：\n" + (_clip(project.get("world_rules"), 3200) or "暂无"),
    ]
    return "\n".join(lines).strip()


def _state_snapshot(project):
    long_form = project.get("long_form", {}) if isinstance(project.get("long_form"), dict) else {}
    snapshot = long_form.get("state_snapshot", {}) if isinstance(long_form.get("state_snapshot"), dict) else {}
    if not snapshot or not any(value for key, value in snapshot.items() if key not in {"updated_at"}):
        return "暂无正式状态快照；必须以近期实写提纲、摘要和关键事实为准，不得自行补全。"
    return _clip(_json_text(snapshot), 8000, keep_tail=True)


def _book_plan(project):
    long_form = project.get("long_form", {}) if isinstance(project.get("long_form"), dict) else {}
    plan = long_form.get("book_plan", {}) if isinstance(long_form.get("book_plan"), dict) else {}
    if not plan or plan.get("status") == "empty":
        return "尚未建立全书阶段图；首次滚动规划需要同时生成。"
    return _clip(_json_text(plan), 7000, keep_tail=True)


def _imported_plan_reference(project):
    reference = project.get("imported_chapter_plan_reference", {}) if isinstance(project, dict) else {}
    if not isinstance(reference, dict):
        return ""
    chapters = reference.get("chapters", []) if isinstance(reference.get("chapters"), list) else []
    per_chapter_budget = max(100, min(360, 14000 // max(1, len(chapters))))
    lines = []
    for fallback_index, item in enumerate(chapters, 1):
        if not isinstance(item, dict):
            continue
        index = _text(item.get("index")) or str(fallback_index)
        title = _text(item.get("title"))
        direction = _text(item.get("outline")) or _text(item.get("mainline_task")) or _text(item.get("chapter_function"))
        lines.append(f"{index}｜{title}｜{_clip(direction, per_chapter_budget)}")
    summary = _clip(reference.get("summary", ""), 3500)
    parts = []
    if summary:
        parts.append("导入规划总述：" + summary)
    if lines:
        parts.append("导入章节方向：\n" + "\n".join(lines))
    return "\n\n".join(parts)


def _chapter_memory(chapter, index):
    title = _text(chapter.get("title")) or f"章节 {index}"
    actual_outline = _clip(chapter.get("actual_outline"), 900)
    summary = _compact_chapter_summary_text(chapter.get("summary", ""), max_chars=500)
    facts = _compact_chapter_key_facts_text(chapter.get("key_facts", ""), max_chars=900)
    lines = [f"第{index}章｜{title}｜章节ID：{_chapter_id(chapter)}"]
    if actual_outline:
        lines.append("实写提纲：" + actual_outline)
    elif summary:
        lines.append("摘要：" + summary)
    elif _text(chapter.get("outline")):
        lines.append("计划提纲（正文事实未确认）：" + _clip(chapter.get("outline"), 500))
    if facts:
        lines.append("关键事实：" + facts)
    return "\n".join(lines)


def _recent_memories(project, chapter_index, window=10):
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    end = max(0, min(int(chapter_index or 0), len(chapters)))
    start = max(0, end - max(1, int(window or 10)))
    return "\n\n".join(_chapter_memory(chapters[index], index + 1) for index in range(start, end)) or "暂无前文章节。"


def _previous_tail(project, chapter_index, limit=2600):
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    previous_index = int(chapter_index or 0) - 1
    if previous_index < 0 or previous_index >= len(chapters):
        return "暂无。"
    text = _text(chapters[previous_index].get("text", ""))
    if not text:
        return "暂无。"
    if len(text) <= limit:
        return text
    return "……（仅保留上一章结尾原文）……\n" + text[-limit:].lstrip()


def _chapter_task(chapter):
    task = _text(chapter.get("chapter_task")) or _text(chapter.get("outline"))
    return _clip(task, 6000) or "尚未填写章节任务。"


def _selected_character_records(project, chapter, planning=False):
    records = project.get("characters", []) if isinstance(project.get("characters"), list) else []
    linked_ids = set(_normalize_name_list(chapter.get("linked_character_ids", [])))
    linked_names = set(_normalize_name_list(chapter.get("linked_characters", [])))
    selected = []
    for item in records:
        if not isinstance(item, dict):
            continue
        item_id = _text(item.get("id"))
        name = _text(item.get("name"))
        if planning or item_id in linked_ids or name in linked_names:
            selected.append(item)
    if not selected and not planning:
        selected = [item for item in records[:12] if isinstance(item, dict)]
    limit = 80 if planning else 24
    lines = []
    for item in selected[:limit]:
        details = []
        for label, key, max_chars in (
            ("身份", "role", 120),
            ("目标", "goal", 180),
            ("秘密", "secret", 160),
            ("语言", "voice", 140),
            ("当前标准记录", "notes", 260),
        ):
            value = item.get(key, "")
            if key == "notes":
                value = _stable_character_notes_context(value)
            value = _clip(value, max_chars)
            if value:
                details.append(f"{label}：{value}")
        lines.append(f"- {_text(item.get('name'))}｜ID:{_text(item.get('id'))}｜" + "｜".join(details))
    return "\n".join(lines) or "暂无相关人物记录。"


def _selected_lore_records(project, chapter, planning=False):
    records = project.get("lore", []) if isinstance(project.get("lore"), list) else []
    linked_ids = set(_normalize_name_list(chapter.get("linked_lore_ids", [])))
    selected = [item for item in records if isinstance(item, dict) and (planning or _text(item.get("id")) in linked_ids)]
    if not selected and not planning:
        selected = [item for item in records[:16] if isinstance(item, dict)]
    limit = 100 if planning else 28
    lines = []
    for item in selected[:limit]:
        description = _clip(_stable_lore_description_context(item.get("description", "")), 320)
        lines.append(
            f"- {_text(item.get('name'))}｜ID:{_text(item.get('id'))}｜类型:{_text(item.get('type'))}｜{description}"
        )
    return "\n".join(lines) or "暂无相关设定记录。"


def _foreshadow_sort_key(item):
    priority = _text(item.get("priority")) or "常规"
    return (
        _FORESHADOW_PRIORITY_RANK.get(priority, 2),
        0 if _text(item.get("status")) == "已埋" else 1,
        _text(item.get("code")),
        _text(item.get("id")),
    )


def _selected_foreshadows(project, chapter, planning=False):
    items = project.get("foreshadow_items", []) if isinstance(project.get("foreshadow_items"), list) else []
    planned_ids = set(_normalize_name_list(chapter.get("planned_foreshadow_ids", [])))
    open_items = [item for item in items if isinstance(item, dict) and _text(item.get("status")) in _OPEN_FORESHADOW_STATUSES]
    open_items.sort(key=_foreshadow_sort_key)
    if planning:
        selected = open_items[:80]
    else:
        planned = [item for item in open_items if _text(item.get("id")) in planned_ids]
        fallback = [item for item in open_items if _text(item.get("id")) not in planned_ids]
        selected = (planned + fallback)[:12]
    lines = []
    for item in selected:
        code = _normalize_foreshadow_code(item.get("code", ""))
        summary = _text(item.get("canonical_summary")) or _stable_foreshadow_description_context(item.get("description", ""))
        lines.append(
            "- "
            + "｜".join(
                [
                    f"{code}:{_text(item.get('name'))}" if code else _text(item.get("name")),
                    f"ID:{_text(item.get('id'))}",
                    f"状态:{_text(item.get('status'))}",
                    f"优先级:{_text(item.get('priority')) or '常规'}",
                    f"处理阶段:{_text(item.get('horizon')) or '未指定'}",
                    _clip(summary, 260),
                ]
            )
        )
    return "\n".join(lines) or "暂无开放伏笔。"


def _rolling_plan(project):
    long_form = project.get("long_form", {}) if isinstance(project.get("long_form"), dict) else {}
    plan = long_form.get("rolling_plan", {}) if isinstance(long_form.get("rolling_plan"), dict) else {}
    if not plan or plan.get("status") == "empty":
        return "尚未生成滚动规划。"
    return _clip(_json_text(plan), 10000, keep_tail=True)


def _closure_state(project):
    long_form = project.get("long_form", {}) if isinstance(project.get("long_form"), dict) else {}
    closure = long_form.get("closure", {}) if isinstance(long_form.get("closure"), dict) else {}
    return _clip(_json_text(closure), 5000, keep_tail=True) if closure else "当前为正常推进模式。"


def _current_chapter_section(chapter, chapter_index, include_body=False, context_task=""):
    task_limit = 1800 if context_task == "postwrite" else (4000 if context_task == "audit" else 6000)
    lines = [
        f"章节序号：{chapter_index + 1}",
        f"章节ID：{_chapter_id(chapter)}",
        f"标题：{_text(chapter.get('title'))}",
        f"本章扩写字数：{_text(chapter.get('draft_words'))}",
        "章节任务：\n" + _clip(_chapter_task(chapter), task_limit),
    ]
    execution_outline = _text(chapter.get("execution_outline"))
    if execution_outline and context_task != "postwrite":
        execution_limit = 4000 if context_task == "audit" else 8000
        lines.append("执行提纲：\n" + _clip(execution_outline, execution_limit))
    if include_body:
        body = _text(chapter.get("text"))
        lines.append(f"最终正文（约{_body_display_len(body)}字）：\n{body}")
    return "\n".join(lines)


def _foreshadow_id_index(project):
    items = project.get("foreshadow_items", []) if isinstance(project.get("foreshadow_items"), list) else []
    items = [
        item for item in items
        if isinstance(item, dict) and _text(item.get("status")) in _OPEN_FORESHADOW_STATUSES
    ]
    items.sort(key=_foreshadow_sort_key)
    lines = []
    for item in items:
        summary = _text(item.get("canonical_summary")) or _stable_foreshadow_description_context(item.get("description", ""))
        lines.append(
            f"ID:{_text(item.get('id'))}｜{_normalize_foreshadow_code(item.get('code', ''))}｜"
            f"{_text(item.get('name'))}｜{_text(item.get('status'))}｜{_clip(summary, 120)}"
        )
    return "\n".join(lines) or "暂无开放伏笔。"


def build_v2_task_context(project, chapter_index, task, total_limit=None):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    if not chapters:
        raise ValueError("项目还没有章节。")
    chapter_index = int(chapter_index or 0)
    if chapter_index < 0 or chapter_index >= len(chapters):
        raise ValueError("当前章节不存在。")
    task = _text(task)
    if task not in TASK_CONTEXT_CHAR_LIMITS:
        raise ValueError(f"不支持的新版小说任务：{task}")
    chapter = chapters[chapter_index]
    planning = task in {"rolling_plan", "checkpoint"}
    include_body = task in {"audit", "postwrite"} or (task == "draft" and bool(_text(chapter.get("text"))))
    body = _text(chapter.get("text")) if include_body else ""
    draft_length_constraint = ""
    if task == "draft":
        digits = "".join(character for character in _text(chapter.get("draft_words")) if character.isdigit())
        if digits:
            target_words = int(digits)
            lower_words = max(1, int(target_words * 0.9))
            upper_words = max(lower_words, int(target_words * 1.2))
            draft_length_constraint = (
                f"本次正文目标：{target_words}字；允许范围：{lower_words}至{upper_words}字。"
                "这是硬性篇幅预算，必须在上限前完成本章任务；接近上限时压缩次要描写、重复反应和过渡，"
                "不要增加非必要场景，也不得以场景完整为理由超过上限。"
            )
    execution_outline_constraint = ""
    if task == "execution_outline":
        execution_outline_constraint = (
            "执行提纲以800至1200字为目标，绝对不得超过1500字。"
            "只保留能直接指导正文的场景因果和人物行动，不增加备选方案或复述项目资料。"
        )
    sections = [
        _section("任务说明", f"当前任务：{TASK_CONTEXT_LABELS[task]}。只完成这一项任务，不要同时代替其他步骤。", True),
        _section("小说核心合同", _core_contract(project), True),
        _section(
            "当前章节",
            _current_chapter_section(chapter, chapter_index, include_body=include_body, context_task=task),
            True,
        ),
        _section("全部开放伏笔ID索引", _foreshadow_id_index(project), True) if task == "postwrite" else None,
        _section("当前状态快照", _state_snapshot(project)),
        _section("全书阶段图", _book_plan(project)),
        _section("现有滚动规划", _rolling_plan(project)),
        _section("收尾模式", _closure_state(project)),
        _section("近期实写记忆", _clip(_recent_memories(project, chapter_index, window=10), 8000, keep_tail=True)),
        _section("上一章结尾原文", _previous_tail(project, chapter_index)),
        _section("相关人物标准记录", _selected_character_records(project, chapter, planning=planning)),
        _section("相关设定标准记录", _selected_lore_records(project, chapter, planning=planning)),
        _section("开放伏笔债务", _selected_foreshadows(project, chapter, planning=planning)),
        _section("执行提纲篇幅硬约束", execution_outline_constraint, True) if execution_outline_constraint else None,
        _section("本次正文篇幅硬约束", draft_length_constraint, True) if draft_length_constraint else None,
    ]
    package = _assemble_sections(sections, total_limit or TASK_CONTEXT_CHAR_LIMITS[task])
    package["task"] = task
    package["chapter_id"] = _chapter_id(chapter)
    package["chapter_index"] = chapter_index
    return package


def build_v2_pov_audit_context(project, chapter_index, total_limit=24000):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter_index = int(chapter_index or 0)
    if chapter_index < 0 or chapter_index >= len(chapters):
        raise ValueError("当前章节不存在。")
    chapter = chapters[chapter_index]
    body = _text(chapter.get("text")) if isinstance(chapter, dict) else ""
    if not body:
        raise ValueError("当前章节没有可审校的正文。")
    meta = project.get("meta", {}) if isinstance(project.get("meta"), dict) else {}
    expected = (
        f"项目指定叙事人称：{_text(meta.get('pov')) or '未指定'}\n"
        f"项目指定文风：{_clip(meta.get('style'), 1000) or '未指定'}\n"
        "检查对象只包括非对白叙述；角色对白、引文、邮件、录音和文内材料中的第一人称不改变正文叙事人称。"
    )
    sections = [
        _section("任务说明", "当前任务：叙事人称与视角边界专项审校。只判断这一项，不评价情节优劣。", True),
        _section("预期叙事合同", expected, True),
        _section(
            "当前章节",
            f"章节序号：{chapter_index + 1}\n章节ID：{_chapter_id(chapter)}\n标题：{_text(chapter.get('title'))}",
            True,
        ),
        _section("完整正文", body, True),
    ]
    package = _assemble_sections(sections, total_limit)
    package["task"] = "pov_audit"
    package["chapter_id"] = _chapter_id(chapter)
    package["chapter_index"] = chapter_index
    return package


def build_v2_planning_context(project, start_index, total_limit=None, checkpoint=False):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    start_index = max(0, min(int(start_index or 0), len(chapters)))
    reference_chapter = chapters[start_index] if start_index < len(chapters) else {}
    planning_label = "阶段复盘并刷新滚动规划" if checkpoint else "刷新滚动规划"
    start_title = _text(reference_chapter.get("title")) if reference_chapter else "新章节"
    start_id = _chapter_id(reference_chapter) if reference_chapter else "尚未创建"
    start_section = (
        f"规划起始序号：{start_index + 1}\n"
        f"现有目标章节：{start_title}\n"
        f"现有目标章节ID：{start_id}\n"
        "已经写出正文的章节不可改写；尚未写正文的旧提纲只作为可调整方向，不是已经发生的事实。"
    )
    sections = [
        _section("任务说明", f"当前任务：{planning_label}。只规划未来窗口，不输出正文。", True),
        _section("小说核心合同", _core_contract(project), True),
        _section("规划起点", start_section, True),
        _section("当前状态快照", _clip(_state_snapshot(project), 3500, keep_tail=True)),
        _section("全书阶段图", _clip(_book_plan(project), 3500, keep_tail=True)),
        _section("用户导入的全书粗纲", _clip(_imported_plan_reference(project), 5000, keep_tail=True)),
        _section("收尾模式", _clip(_closure_state(project), 1500, keep_tail=True)),
        _section("近期实写记忆", _clip(_recent_memories(project, start_index, window=10), 6000, keep_tail=True)),
        _section("上一章结尾原文", _previous_tail(project, start_index)),
        _section("开放伏笔债务", _clip(_foreshadow_id_index(project), 6000, keep_tail=False)),
        _section("人物标准记录", _clip(_selected_character_records(project, reference_chapter, planning=True), 6000)),
        _section("现有滚动规划", _clip(_rolling_plan(project), 3000, keep_tail=True)),
        _section("设定标准记录", _clip(_selected_lore_records(project, reference_chapter, planning=True), 3000)),
    ]
    package = _assemble_sections(sections, total_limit or TASK_CONTEXT_CHAR_LIMITS["rolling_plan"])
    package["task"] = "checkpoint" if checkpoint else "rolling_plan"
    package["start_index"] = start_index
    return package


def build_v2_completion_context(project, total_limit=None):
    project = project if isinstance(project, dict) else {}
    chapters = project.get("chapters", []) if isinstance(project.get("chapters"), list) else []
    chapter_count = max(1, len(chapters))
    per_chapter_budget = max(100, min(280, 12000 // chapter_count))
    chapter_lines = []
    for index, chapter in enumerate(chapters, 1):
        if not isinstance(chapter, dict):
            continue
        actual = _text(chapter.get("actual_outline")) or _text(chapter.get("summary"))
        facts = _text(chapter.get("key_facts"))
        memory_limit = max(60, int(per_chapter_budget * 0.64))
        facts_limit = max(30, per_chapter_budget - memory_limit)
        memory = _clip(actual, memory_limit)
        facts = _clip(facts, facts_limit)
        line = f"第{index}章｜{_text(chapter.get('title'))}｜ID:{_chapter_id(chapter)}｜{memory}"
        if facts:
            line += "｜事实:" + facts
        chapter_lines.append(line)
    open_items = [
        item
        for item in project.get("foreshadow_items", [])
        if isinstance(item, dict) and _text(item.get("status")) in _OPEN_FORESHADOW_STATUSES
    ]
    open_items.sort(key=_foreshadow_sort_key)
    foreshadow_lines = []
    foreshadow_summary_limit = max(20, min(60, 6000 // max(1, len(open_items))))
    for item in open_items:
        code = _normalize_foreshadow_code(item.get("code", ""))
        summary = _text(item.get("canonical_summary")) or _stable_foreshadow_description_context(item.get("description", ""))
        foreshadow_lines.append(
            f"{code}｜ID:{_text(item.get('id'))}｜{_text(item.get('name'))}｜状态:{_text(item.get('status'))}｜"
            f"{_clip(summary, foreshadow_summary_limit)}"
        )
    character_lines = []
    characters = project.get("characters", []) if isinstance(project.get("characters"), list) else []
    character_field_limit = max(20, min(60, 6000 // max(2, len(characters) * 2)))
    for item in characters:
        if not isinstance(item, dict):
            continue
        character_lines.append(
            f"ID:{_text(item.get('id'))}｜{_text(item.get('name'))}｜"
            f"身份:{_clip(item.get('role'), character_field_limit)}｜"
            f"目标:{_clip(item.get('goal'), character_field_limit)}"
        )
    sections = [
        _section("任务说明", "当前任务：全书完结审计。只能根据已完成正文和项目事实判断，不得把计划当作事实。", True),
        _section("小说核心合同", _core_contract(project), True),
        _section("全书阶段图", _book_plan(project)),
        _section("全书实写记忆", "\n".join(chapter_lines) or "暂无已写章节。", True),
        _section("开放伏笔债务", "\n".join(foreshadow_lines) or "暂无开放伏笔。", True),
        _section("人物弧线ID索引", "\n".join(character_lines) or "暂无人物记录。", True),
        _section("当前状态快照", _state_snapshot(project)),
        _section("收尾模式", _closure_state(project)),
    ]
    package = _assemble_sections(sections, total_limit or TASK_CONTEXT_CHAR_LIMITS["completion_audit"])
    package["task"] = "completion_audit"
    package["chapter_count"] = len(chapters)
    return package
