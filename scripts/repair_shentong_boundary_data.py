from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpt_desktop.novel_utils import (
    _long_form_boundary_integrity,
    _mark_chapters_analyzed,
    _normalize_long_form_memory,
    _normalize_long_form_structural_refs,
    _validate_long_form_memory_update,
    now_str,
)


PROJECT_PATH = Path(
    "/Users/wanglibo/.gpt_desktop_app/history/novel_projects/"
    "《神通骨被挖，我却获得了无上神通》框架.json"
)


def _as_list(value):
    return value if isinstance(value, list) else []


def _build_reconciliation_bundle(project):
    chapters = project["chapters"]
    chapter = chapters[39]
    next_selection = chapters[40].get("memory_selection", {})
    memory = project["long_form_memory"]
    archive = next(
        (
            item
            for item in _as_list(memory.get("stage_archives"))
            if isinstance(item, dict) and int(item.get("end_chapter_index", 0) or 0) == 40
        ),
        {},
    )

    events = []
    for source in _as_list(chapter.get("long_term_events")):
        storage = source.get("storage", {}) if isinstance(source, dict) else {}
        storage = storage if isinstance(storage, dict) else {}
        events.append(
            {
                "event": str(source.get("event", "") or "").strip(),
                "category": str(source.get("category", "") or "").strip(),
                "evidence_quote": str(
                    source.get("evidence", source.get("evidence_quote", "")) or ""
                ).strip(),
                "storage": {
                    "fact_refs": copy.deepcopy(_as_list(storage.get("fact_ids"))),
                    "character_refs": copy.deepcopy(_as_list(storage.get("character_ids"))),
                    "lore_refs": copy.deepcopy(_as_list(storage.get("lore_ids"))),
                    "foreshadow_refs": copy.deepcopy(_as_list(storage.get("foreshadow_ids"))),
                    "object_keys": copy.deepcopy(_as_list(storage.get("object_keys"))),
                    "conflict_refs": copy.deepcopy(_as_list(storage.get("conflict_ids"))),
                    "task_refs": [
                        value
                        for value in _as_list(storage.get("task_ids"))
                        if str(value or "").strip() != "TASK-0024"
                    ],
                },
            }
        )

    reconciliation = copy.deepcopy(chapter.get("state_reconciliation", {}))
    reconciliation["fact_refs"] = copy.deepcopy(_as_list(reconciliation.get("fact_ids")))
    reconciliation["character_refs"] = copy.deepcopy(_as_list(reconciliation.get("character_ids")))
    reconciliation["lore_refs"] = copy.deepcopy(_as_list(reconciliation.get("lore_ids")))
    reconciliation["foreshadow_refs"] = copy.deepcopy(_as_list(reconciliation.get("foreshadow_ids")))
    reconciliation["relationship_refs"] = copy.deepcopy(_as_list(reconciliation.get("relationship_ids")))
    reconciliation["conflict_refs"] = copy.deepcopy(_as_list(reconciliation.get("conflict_ids")))
    reconciliation["task_refs"] = [
        value
        for value in _as_list(reconciliation.get("task_ids"))
        if str(value or "").strip() != "TASK-0024"
    ]
    reconciliation.pop("fact_ids", None)
    reconciliation.pop("character_ids", None)
    reconciliation.pop("lore_ids", None)
    reconciliation.pop("foreshadow_ids", None)
    reconciliation.pop("relationship_ids", None)
    reconciliation.pop("conflict_ids", None)
    reconciliation.pop("task_ids", None)

    active_fact_ids = {
        str(item.get("id", "") or "").strip()
        for item in _as_list(memory.get("active_facts"))
        if isinstance(item, dict) and str(item.get("id", "") or "").strip()
    }
    reconciliation["fact_refs"] = [
        value
        for value in reconciliation["fact_refs"]
        if str(value or "").strip() in active_fact_ids
    ]
    event_lore_refs = {
        str(value or "").strip()
        for event in events
        for value in _as_list(event.get("storage", {}).get("lore_refs"))
        if str(value or "").strip()
    }
    event_foreshadow_refs = {
        str(value or "").strip()
        for event in events
        for value in _as_list(event.get("storage", {}).get("foreshadow_refs"))
        if str(value or "").strip()
    }
    for key, values in (
        ("lore_refs", event_lore_refs),
        ("foreshadow_refs", event_foreshadow_refs),
    ):
        current = reconciliation.get(key, [])
        for value in sorted(values):
            if value not in current:
                current.append(value)
        reconciliation[key] = current
    runtime_review = reconciliation.setdefault("record_runtime_review", {})
    if not isinstance(runtime_review, dict):
        runtime_review = {}
        reconciliation["record_runtime_review"] = runtime_review
    for kind, event_refs in (
        ("lore", event_lore_refs),
        ("foreshadows", event_foreshadow_refs),
    ):
        reviewed_key = "reviewed_lore_refs" if kind == "lore" else "reviewed_foreshadow_refs"
        unchanged_key = "unchanged_lore_refs" if kind == "lore" else "unchanged_foreshadow_refs"
        reviewed = _as_list(runtime_review.get(reviewed_key))
        for value in sorted(event_refs):
            if value not in reviewed:
                reviewed.append(value)
        runtime_review[reviewed_key] = reviewed
        unchanged = _as_list(runtime_review.get(unchanged_key))
        for value in reviewed:
            if value not in unchanged:
                unchanged.append(value)
        runtime_review[unchanged_key] = unchanged

    lifecycle = copy.deepcopy(chapter.get("state_lifecycle_review", {}))
    lifecycle["scope"] = "stage_boundary_delta"
    lifecycle["reviewed_object_keys"] = ["OBJ-002"]
    lifecycle["reviewed_conflict_refs"] = ["CF-0011"]
    lifecycle["reviewed_task_refs"] = ["TASK-0027"]
    lifecycle.pop("reviewed_conflict_ids", None)
    lifecycle.pop("reviewed_task_ids", None)

    next_memory = {
        "character_refs": copy.deepcopy(_as_list(next_selection.get("character_ids"))),
        "lore_refs": copy.deepcopy(_as_list(next_selection.get("lore_ids"))),
        "foreshadow_refs": copy.deepcopy(_as_list(next_selection.get("foreshadow_ids"))),
        "fact_refs": copy.deepcopy(_as_list(next_selection.get("fact_ids"))),
        "stage_archive_refs": copy.deepcopy(_as_list(next_selection.get("stage_archive_ids"))),
        "object_keys": copy.deepcopy(_as_list(next_selection.get("object_keys"))),
        "conflict_refs": copy.deepcopy(_as_list(next_selection.get("conflict_ids"))),
        "task_refs": copy.deepcopy(_as_list(next_selection.get("task_ids"))),
        "reason": str(next_selection.get("reason", "") or "").strip(),
    }

    return {
        "outline": str(chapter.get("outline", "") or "").strip(),
        "summary": str(chapter.get("summary", "") or "").strip(),
        "key_facts": str(chapter.get("key_facts", "") or "").strip(),
        "memory_update": {
            "schema_version": 2,
            "base_revision": int(memory.get("revision", 0) or 0),
            "state_patch": {},
            "state_retirements": {
                "character_refs": [],
                "relationship_refs": [],
                "object_keys": [],
                "conflict_ids": [],
                "task_ids": [],
            },
            "state_lifecycle_review": lifecycle,
            "fact_updates": [],
            "fact_lifecycle_review": {
                "scope": "stage_boundary_delta",
                "reviewed_refs": [
                    value
                    for value in _as_list(chapter.get("memory_selection", {}).get("fact_ids"))
                    if str(value or "").strip() in active_fact_ids
                ],
                "notes": "已复核本章承接的事实，未新增或改写事实。",
            },
            "long_term_events": events,
            "current_chapter_character_refs": copy.deepcopy(
                _as_list(chapter.get("actual_linked_character_ids"))
            ),
            "stage_archive": {
                key: copy.deepcopy(archive.get(key))
                for key in (
                    "summary",
                    "irreversible_facts",
                    "relationship_changes",
                    "unresolved_threads",
                    "next_stage_entry",
                )
            },
            "record_updates": {"characters": [], "lore": []},
            "foreshadow_updates": [],
            "state_reconciliation": reconciliation,
            "next_chapter_memory": next_memory,
        },
    }


def prepare(project):
    chapters = project.get("chapters")
    if not isinstance(chapters, list) or len(chapters) < 41:
        raise RuntimeError("目标项目章节不足41章，拒绝修改")
    chapter36 = chapters[35]
    old_phrase = "左边七人，宽路四人，右边的人更多。"
    new_phrase = "左边七人，宽路五人，右边的人更多。"
    if str(chapter36.get("text", "") or "").count(old_phrase) != 1:
        raise RuntimeError("第36章人数矛盾原文未保持预期的唯一命中")
    if str(chapter36.get("text", "") or "").count(new_phrase):
        raise RuntimeError("第36章已经存在修复后的人数表述，拒绝重复修改")
    chapter36["text"] = chapter36["text"].replace(old_phrase, new_phrase, 1)

    chapter40 = chapters[39]
    memory = project.get("long_form_memory")
    if not isinstance(memory, dict):
        raise RuntimeError("长篇记忆缺失，拒绝修改")
    snapshot = memory.get("state_snapshot")
    if not isinstance(snapshot, dict):
        raise RuntimeError("状态快照缺失，拒绝修改")
    before_memory = _normalize_long_form_memory(copy.deepcopy(memory))
    removed_object_keys = {
        "L049",
        "L050",
        "L051",
        "NOBJ-0033-01",
        "OBJ-001",
    }
    object_states = _as_list(snapshot.get("object_states"))
    present = {
        str(item.get("key", "") or "").strip()
        for item in object_states
        if isinstance(item, dict)
    }
    if not removed_object_keys.issubset(present):
        raise RuntimeError("第40章物件快照缺少预期的旧重复键，拒绝清理")
    if "OBJ-002" not in present:
        raise RuntimeError("第40章完整玉佩OBJ-002不存在，拒绝清理")
    snapshot["object_states"] = [
        item
        for item in object_states
        if not (
            isinstance(item, dict)
            and str(item.get("key", "") or "").strip() in removed_object_keys
        )
    ]

    reconciliation = chapter40.get("state_reconciliation", {})
    if not isinstance(reconciliation, dict):
        raise RuntimeError("第40章状态对账记录缺失，拒绝修改")
    reconciliation["task_ids"] = [
        value
        for value in _as_list(reconciliation.get("task_ids"))
        if str(value or "").strip() != "TASK-0024"
    ]
    if "TASK-0027" not in reconciliation["task_ids"]:
        reconciliation["task_ids"].append("TASK-0027")
    lifecycle = chapter40.get("state_lifecycle_review")
    if not isinstance(lifecycle, dict):
        raise RuntimeError("第40章状态生命周期复核记录缺失，拒绝修改")
    lifecycle["reviewed_task_ids"] = [
        value
        for value in _as_list(lifecycle.get("reviewed_task_ids"))
        if str(value or "").strip() != "TASK-0024"
    ]
    if "TASK-0027" not in lifecycle["reviewed_task_ids"]:
        lifecycle["reviewed_task_ids"].append("TASK-0027")
    for event in _as_list(chapter40.get("long_term_events")):
        if not isinstance(event, dict):
            continue
        storage = event.get("storage")
        if not isinstance(storage, dict):
            continue
        storage["task_ids"] = [
            value
            for value in _as_list(storage.get("task_ids"))
            if str(value or "").strip() != "TASK-0024"
        ]

    # The existing chapter-40 selection was generated for the pre-boundary
    # state and still pointed at the old half-pendant/task.  Keep the
    # historical chapter records intact, but make this chapter's active
    # selection agree with the already-written boundary result so a resumed
    # audit cannot reintroduce retired references.
    next_selection = chapters[40].get("memory_selection", {})
    if not isinstance(next_selection, dict):
        raise RuntimeError("第41章承接选择缺失，拒绝恢复第40章边界")
    chapter40["memory_selection"] = copy.deepcopy(next_selection)

    after_memory = _normalize_long_form_memory(copy.deepcopy(memory))
    integrity = _long_form_boundary_integrity(
        project,
        39,
        before_memory,
        after_memory,
        {"state_retirements": {"object_keys": sorted(removed_object_keys)}},
    )
    integrity["verified_at"] = now_str()
    chapter40["memory_boundary_integrity"] = integrity

    if chapter40.get("memory_reconciliation_status") != "pending":
        chapter40["memory_reconciliation_status"] = "pending"
    chapter40["memory_reconciliation_error"] = ""
    chapter40["auto_expand_resume_required"] = True

    bundle = _build_reconciliation_bundle(project)
    memory_update = _normalize_long_form_structural_refs(
        project, 39, bundle["memory_update"]
    )
    errors = _validate_long_form_memory_update(
        project,
        39,
        memory_update,
        final_text=chapter40.get("text", ""),
        require_revision=True,
        require_evidence=True,
    )
    if errors:
        raise RuntimeError("恢复用状态包校验失败：" + "；".join(errors[:20]))
    bundle["memory_update"] = memory_update
    bundle_hash = hashlib.sha256(
        json.dumps(
            memory_update,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    chapter40["memory_update_hash"] = bundle_hash
    chapter40["memory_sync_status"] = "complete"
    chapter40["memory_sync_error"] = ""
    chapter40["memory_revision"] = int(memory.get("revision", 0) or 0)
    chapter40["ai_generation_checkpoint"] = {
        "version": 3,
        "stage": "memory_reconcile",
        "status": "pending",
        "project_path": str(PROJECT_PATH),
        "chapter_id": str(chapter40.get("id", "") or ""),
        "chapter_index": 39,
        "request_id": "boundary-repair-ch40",
        "task_generation": 0,
        "mode": "style",
        "final_text": str(chapter40.get("text", "") or "").strip(),
        "final_text_sha256": hashlib.sha256(
            str(chapter40.get("text", "") or "").strip().encode("utf-8")
        ).hexdigest(),
        "source_text_sha256": hashlib.sha256(
            str(chapter40.get("text", "") or "").strip().encode("utf-8")
        ).hexdigest(),
        "outline_sha256": hashlib.sha256(
            str(chapter40.get("outline", "") or "").encode("utf-8")
        ).hexdigest(),
        "base_memory_revision": int(memory.get("revision", 0) or 0),
        "provider": "",
        "model": "",
        "transaction_id": "boundary-repair-ch40",
        "bundle": bundle,
        "already_committed": True,
        "created_at": now_str(),
        "updated_at": now_str(),
    }

    if _mark_chapters_analyzed(chapters, [str(chapter36.get("id", "") or "")]) != 1:
        raise RuntimeError("第36章分析哈希未能同步")
    project["updated_at"] = now_str()
    memory["updated_at"] = now_str()
    return {
        "removed_object_keys": sorted(removed_object_keys),
        "chapter36_text_fix": new_phrase,
        "chapter40_checkpoint": chapter40["ai_generation_checkpoint"]["stage"],
        "chapter40_memory_revision": chapter40["memory_revision"],
        "chapter40_boundary_verified": bool(integrity.get("verified")),
        "chapter40_bundle_hash": bundle_hash,
    }


def main():
    if not PROJECT_PATH.exists():
        raise SystemExit(f"目标项目不存在：{PROJECT_PATH}")
    project = json.loads(PROJECT_PATH.read_text(encoding="utf-8"))
    result = prepare(project)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if "--write" not in __import__("sys").argv:
        print("DRY RUN: 未写入目标项目。")
        return
    PROJECT_PATH.write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("WRITTEN:", PROJECT_PATH)


if __name__ == "__main__":
    main()
