import os
from copy import deepcopy

from .core import HISTORY_DIR, load_json_file, now_str, save_json_file
from .novel_utils import _default_project, _normalize_candidate_analysis_state, _normalize_project, _safe_name


NOVEL_DIR = os.path.join(HISTORY_DIR, "novel_projects")
NOVEL_DRAFT_FILE = os.path.join(HISTORY_DIR, "novel_draft.json")
NOVEL_LAST_FILE = os.path.join(HISTORY_DIR, "novel_last.json")


def ensure_novel_storage():
    os.makedirs(NOVEL_DIR, exist_ok=True)


def safe_project_timestamp():
    return now_str().replace(":", "").replace("-", "").replace(" ", "_")


def list_project_files(include_empty=False):
    if not os.path.exists(NOVEL_DIR):
        return []
    out = []
    for name in os.listdir(NOVEL_DIR):
        if not name.lower().endswith(".json"):
            continue
        path = os.path.join(NOVEL_DIR, name)
        if not include_empty:
            try:
                data = load_json_file(path, {})
                if data.get("auto_saved_reason"):
                    continue
            except Exception:
                pass
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0
        out.append((mtime, name, path))
    out.sort(reverse=True)
    return out


def list_project_records(include_empty=False):
    records = []
    for mtime, filename, path in list_project_files(include_empty=include_empty):
        data = _normalize_project(load_json_file(path, {}))
        records.append(
            {
                "mtime": mtime,
                "filename": filename,
                "path": path,
                "data": data,
            }
        )
    return records


def list_project_summaries(include_empty=False):
    records = []
    for mtime, filename, path in list_project_files(include_empty=include_empty):
        raw = load_json_file(path, {})
        data = raw if isinstance(raw, dict) else {}
        if data.get("auto_saved_reason") and not include_empty:
            continue
        meta = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
        chapters = data.get("chapters", []) if isinstance(data.get("chapters"), list) else []
        body_words = 0
        for chap in chapters:
            if not isinstance(chap, dict):
                continue
            body_words += len(str(chap.get("text", "") or "").strip())
        records.append(
            {
                "mtime": mtime,
                "filename": filename,
                "path": path,
                "title": meta.get("title") or os.path.splitext(filename)[0],
                "body_words": body_words,
                "chapters": len(chapters),
            }
        )
    return records


def _merge_candidate_analysis_state(primary, fallback):
    primary_state = _normalize_candidate_analysis_state(primary.get("analysis_state", {}) if isinstance(primary, dict) else {})
    fallback_state = _normalize_candidate_analysis_state(fallback.get("analysis_state", {}) if isinstance(fallback, dict) else {})
    if not fallback_state:
        return primary
    if primary_state.get("failed_candidate_chunks"):
        return primary

    merged_state = deepcopy(primary_state)
    if fallback_state.get("failed_candidate_chunks"):
        merged_state["failed_candidate_chunks"] = deepcopy(fallback_state["failed_candidate_chunks"])
    if not merged_state.get("pending_candidate_chapter_ids") and fallback_state.get("pending_candidate_chapter_ids"):
        merged_state["pending_candidate_chapter_ids"] = deepcopy(fallback_state["pending_candidate_chapter_ids"])
    if merged_state:
        primary["analysis_state"] = merged_state
    return primary


def load_initial_project_data():
    if os.path.exists(NOVEL_DRAFT_FILE):
        last = load_json_file(NOVEL_LAST_FILE, {}) if os.path.exists(NOVEL_LAST_FILE) else {}
        last_path = str(last.get("path", "") or "").strip() if isinstance(last, dict) else ""
        draft_data = load_json_file(NOVEL_DRAFT_FILE, _default_project())
        if last_path and os.path.exists(last_path):
            project_data = load_json_file(last_path, {})
            if isinstance(project_data, dict):
                draft_data = _merge_candidate_analysis_state(draft_data, project_data)
            return draft_data, last_path
        return draft_data, NOVEL_DRAFT_FILE
    files = list_project_files()
    if files:
        _mtime, _name, path = files[0]
        return load_json_file(path, _default_project()), path
    return _default_project(), ""


def save_draft_project(data):
    save_json_file(NOVEL_DRAFT_FILE, _normalize_project(data))


def save_project_file(path, data, preserve_mtime=False):
    old_times = None
    if preserve_mtime and os.path.exists(path):
        try:
            stat = os.stat(path)
            old_times = (stat.st_atime, stat.st_mtime)
        except Exception:
            old_times = None
    data = _normalize_project(data)
    data["updated_at"] = now_str()
    save_json_file(path, data)
    if old_times is not None:
        try:
            os.utime(path, old_times)
        except Exception:
            pass
    return path


def save_named_project(name, data):
    path = named_project_path(name)
    save_project_file(path, data)
    return path


def auto_preserve_project(data, reason):
    if not project_has_content(data):
        return ""
    data = _normalize_project(data)
    title = data.get("meta", {}).get("title") or "未命名小说"
    path = unique_project_path(f"{title}_{reason}")
    data["auto_saved_reason"] = reason
    save_project_file(path, data)
    return path


def remember_project_path(path):
    if path:
        save_json_file(NOVEL_LAST_FILE, {"path": path})


def clear_last_project_path():
    if os.path.exists(NOVEL_LAST_FILE):
        os.remove(NOVEL_LAST_FILE)


def project_has_content(data):
    if not isinstance(data, dict):
        return False
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    meaningful_meta = any(
        str(meta.get(key, "") or "").strip()
        for key in ("genre", "style", "target_words", "premise")
    )
    meaningful_text = any(
        str(data.get(key, "") or "").strip()
        for key in ("bible", "world_rules", "timeline", "foreshadows", "summary", "draft_note")
    )
    meaningful_lists = bool(
        data.get("characters")
        or data.get("lore")
        or data.get("chapters")
        or data.get("foreshadow_items")
    )
    return bool(meaningful_meta or meaningful_text or meaningful_lists)


def unique_project_path(title):
    base = _safe_name(title) or "未命名小说"
    path = os.path.join(NOVEL_DIR, f"{base}.json")
    if not os.path.exists(path):
        return path
    timestamp = safe_project_timestamp()
    path = os.path.join(NOVEL_DIR, f"{base}_{timestamp}.json")
    index = 2
    while os.path.exists(path):
        path = os.path.join(NOVEL_DIR, f"{base}_{timestamp}_{index}.json")
        index += 1
    return path


def named_project_path(name):
    return os.path.join(NOVEL_DIR, f"{_safe_name(name) or '未命名小说'}.json")
