import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gpt_desktop.novel_utils as novel_utils


PROJECT_PATH = Path.home() / ".gpt_desktop_app/history/novel_projects/《离婚后，我成了前妻高攀不起的人》框架.json"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "api_test_outputs/离婚后_旧59k上下文截断分析.json"


def split_sections(text):
    text = str(text or "")
    matches = list(re.finditer(r"(?m)^【([^】]+)】\n", text))
    sections = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.end():end].strip()
    return sections


def build_context(project, chapter_index, limit):
    old_limit = novel_utils.NOVEL_AI_CONTEXT_LIMIT
    try:
        novel_utils.NOVEL_AI_CONTEXT_LIMIT = limit
        return novel_utils._build_chapter_ai_context(project, chapter_index, "draft")
    finally:
        novel_utils.NOVEL_AI_CONTEXT_LIMIT = old_limit


def capture_selected_records(project, chapter_index, limit):
    captured = []
    original = novel_utils._prioritize_named_records

    def wrapper(records, context_text, linked_names=None, name_key="name", limit=24, score_func=None, min_score=1):
        selected = original(
            records,
            context_text,
            linked_names=linked_names,
            name_key=name_key,
            limit=limit,
            score_func=score_func,
            min_score=min_score,
        )
        eligible = original(
            records,
            context_text,
            linked_names=linked_names,
            name_key=name_key,
            limit=0,
            score_func=score_func,
            min_score=min_score,
        )
        captured.append({
            "candidate_count": len(records) if isinstance(records, list) else 0,
            "eligible_count": len(eligible),
            "selection_limit": limit,
            "selected_count": len(selected),
            "selected_names": [str(item.get(name_key, "") or "") for item in selected],
        })
        return selected

    novel_utils._prioritize_named_records = wrapper
    try:
        build_context(project, chapter_index, limit)
    finally:
        novel_utils._prioritize_named_records = original
    labels = ("characters", "lore", "foreshadows")
    return {label: row for label, row in zip(labels, captured)}


def source_metrics(project, chapter_index):
    chapters = project.get("chapters", [])
    recent, _names = novel_utils._recent_chapter_context(
        chapters, chapter_index, window=6, project=project
    )
    auto_timeline = novel_utils._build_project_timeline_draft(project)
    auto_summary = novel_utils._build_project_summary_draft(project)

    def joined(*parts):
        return "\n\n".join(
            novel_utils._dedupe_text_lines(part)
            for part in parts
            if str(part or "").strip()
        ) or "暂无"

    values = {
        "时间线": joined(
            project.get("timeline", ""),
            "自动章节顺序线：\n" + auto_timeline if auto_timeline else "",
        ),
        "续写承接点": novel_utils._build_chapter_continuation_text(chapters, chapter_index) or "暂无",
        "后续规划 / 边界": novel_utils._build_future_plan_text(chapters, chapter_index) or "暂无",
        "前文继承摘要": novel_utils._build_previous_inheritance_text(chapters, chapter_index),
        "近几章连续性": recent or "暂无",
        "全局摘要 / 日志": joined(
            project.get("summary", ""),
            "自动章节压缩：\n" + auto_summary if auto_summary else "",
        ),
    }
    return {
        name: {
            "source_chars": len(value),
            "contains_internal_omission": "省略" in value or "已压缩" in value,
        }
        for name, value in values.items()
    }


def main():
    project = json.loads(PROJECT_PATH.read_text(encoding="utf-8"))
    rows = []
    for chapter_index in (14, 24, 33):
        old_context = build_context(project, chapter_index, 59000)
        new_context = build_context(project, chapter_index, 120000)
        selections = capture_selected_records(project, chapter_index, 59000)
        sources = source_metrics(project, chapter_index)
        old_sections = split_sections(old_context)
        new_sections = split_sections(new_context)
        section_rows = []
        for title in dict.fromkeys(list(new_sections) + list(old_sections)):
            old_text = old_sections.get(title, "")
            new_text = new_sections.get(title, "")
            section_rows.append({
                "name": title,
                "old_chars": len(old_text),
                "new_chars": len(new_text),
                "lost_chars": max(0, len(new_text) - len(old_text)),
                "missing_in_old": title not in old_sections,
                "old_preview": old_text[:120],
                "new_preview": new_text[:120],
                "source_chars_before_section_limit": sources.get(title, {}).get("source_chars"),
                "contains_internal_omission": sources.get(title, {}).get("contains_internal_omission", False),
            })
        rows.append({
            "chapter": chapter_index + 1,
            "title": project["chapters"][chapter_index].get("title", ""),
            "chapter_body_chars": len(project["chapters"][chapter_index].get("text", "")),
            "old_total_chars": len(old_context),
            "new_total_chars": len(new_context),
            "old_section_order": list(old_sections),
            "new_section_order": list(new_sections),
            "sections": section_rows,
            "record_selections": selections,
        })
    report = {
        "project": project.get("meta", {}).get("title", ""),
        "chapters": len(project.get("chapters", [])),
        "body_chars": sum(len(item.get("text", "")) for item in project.get("chapters", [])),
        "characters": len(project.get("characters", [])),
        "lore": len(project.get("lore", [])),
        "foreshadows": len(project.get("foreshadow_items", [])),
        "rows": rows,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
