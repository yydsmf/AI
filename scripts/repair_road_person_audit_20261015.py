#!/usr/bin/env python3
"""Repair only confirmed data leaks found in the road-person project audit."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


PROJECT = Path("/Users/wanglibo/.gpt_desktop_app/history/novel_projects/《路人甲拒绝加戏》.json")

INTERNAL_MARKERS = {
    "seeded",
    "advanced",
    "progressed",
    "reinforced",
    "未埋",
    "已埋",
    "推进",
    "已推进",
    "本章首次埋设",
}


def clean_foreshadow_lines(value: object) -> str:
    cleaned = []
    for raw in str(value or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in INTERNAL_MARKERS:
            continue
        if line == "”":
            continue
        if line.startswith("”；"):
            line = line[2:].lstrip()
        if line:
            cleaned.append(line)
    return "\n".join(cleaned)


def meaningful_runtime_change(development: object) -> str:
    if not isinstance(development, dict):
        return ""
    changes = development.get("changes", [])
    if not isinstance(changes, list):
        changes = [changes]
    values = [str(item or "").strip() for item in changes if str(item or "").strip()]
    values = [item for item in values if item not in INTERNAL_MARKERS]
    if values:
        return "；".join(values)
    evidence = str(development.get("evidence", "") or "").strip()
    return f"本章正文证据：{evidence}" if evidence else ""


def main() -> None:
    with PROJECT.open("r", encoding="utf-8") as handle:
        project = json.load(handle)

    chapters = project.get("chapters", [])
    expected_replacements = {
        52: ("离开L014后", "离开影像社器材室后"),
        127: ("C017的主表", "客户数据主表"),
    }
    changed = []
    for chapter_number, (old, new) in expected_replacements.items():
        chapter = chapters[chapter_number - 1]
        text = str(chapter.get("text", "") or "")
        old_count = text.count(old)
        new_count = text.count(new)
        if old_count == 1 and new_count == 0:
            chapter["text"] = text.replace(old, new)
            changed.append((chapter_number, old, new, old_count))
        elif old_count == 0 and new_count == 1:
            # The repair was already applied; keep the script idempotent.
            continue
        else:
            raise RuntimeError(
                f"第{chapter_number}章替换状态异常：{old!r}={old_count}，{new!r}={new_count}"
            )

    l012_count = 0
    for chapter_number in range(41, 159):
        chapter = chapters[chapter_number - 1]
        text = str(chapter.get("text", "") or "")
        count = text.count("L012")
        if count:
            chapter["text"] = text.replace("L012", "合租屋")
            l012_count += count
            changed.append((chapter_number, "L012", "合租屋", count))
    if l012_count not in {0, 22}:
        raise RuntimeError(f"41-158章正文替换状态异常：L012剩余{l012_count}处，预期为0或22")

    # Remove standalone lifecycle markers from current user-facing foreshadow text.
    # Historical development entries remain intact so the old run can still be audited.
    items = project.get("foreshadow_items", [])
    by_id = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for field in ("description", "revealed", "remaining_secret", "notes"):
            if field in item:
                item[field] = clean_foreshadow_lines(item.get(field, ""))
        if item.get("id"):
            by_id[str(item["id"])] = item

    runtime = project.get("long_form_memory", {}).get("record_runtime", {}).get("foreshadows", {})
    for item_id, entry in runtime.items():
        if not isinstance(entry, dict):
            continue
        if "revealed" in entry:
            entry["revealed"] = clean_foreshadow_lines(entry.get("revealed", ""))

        item = by_id.get(str(item_id), {})
        status = str(item.get("status", "") or "").strip()
        state = str(entry.get("state", "") or "").strip()
        if status == "未埋" or state not in INTERNAL_MARKERS:
            continue

        replacement = ""
        developments = entry.get("developments", [])
        if isinstance(developments, list):
            for development in reversed(developments):
                candidate = meaningful_runtime_change(development)
                if candidate:
                    replacement = candidate
                    break
        if not replacement:
            revealed = clean_foreshadow_lines(item.get("revealed", ""))
            replacement = revealed.splitlines()[0] if revealed else ""
        if replacement:
            entry["state"] = replacement

    # Correct two obvious stale state snapshots while retaining their historical
    # "未埋" observations in developments.
    runtime_by_code = {
        next((str(item.get("id", "")) for item in items if item.get("code") == code), ""): entry
        for code, entry in (("F0009", None), ("F0023", None))
    }
    # The generic cleanup above already resolves these, but keep an explicit guard
    # so a future data shape change cannot silently reintroduce the stale state.
    for code in ("F0009", "F0023"):
        item = next((row for row in items if row.get("code") == code), None)
        if not isinstance(item, dict):
            raise RuntimeError(f"缺少{code}")
        entry = runtime.get(str(item.get("id", "")), {})
        if str(entry.get("state", "") or "").strip() in {"未埋", "已埋", "推进", "seeded"}:
            raise RuntimeError(f"{code}运行态仍是生命周期标记")

    project["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    temp = PROJECT.with_suffix(PROJECT.suffix + ".audit-repair.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(project, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temp.replace(PROJECT)

    print(json.dumps({
        "project": str(PROJECT),
        "text_replacements": changed,
        "l012_count": l012_count,
        "foreshadow_items": len(items),
        "runtime_foreshadows": len(runtime),
        "revision": project.get("long_form_memory", {}).get("revision"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
