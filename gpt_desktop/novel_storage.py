import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback
from copy import deepcopy

from .core import HISTORY_DIR, _atomic_write_json, load_json_file, now_str
from .novel_utils import (
    _body_display_len,
    _default_project,
    _normalize_candidate_analysis_state,
    _normalize_project,
    _safe_name,
)


NOVEL_DIR = os.path.join(HISTORY_DIR, "novel_projects")
NOVEL_DRAFT_FILE = os.path.join(HISTORY_DIR, "novel_draft.json")
NOVEL_LAST_FILE = os.path.join(HISTORY_DIR, "novel_last.json")
NOVEL_STYLE_LIBRARY_FILE = os.path.join(HISTORY_DIR, "novel_style_profiles.json")
NOVEL_DIAGNOSTIC_DIR = os.path.join(HISTORY_DIR, "novel_diagnostics")
NOVEL_DIAGNOSTIC_LOG_FILE = os.path.join(NOVEL_DIAGNOSTIC_DIR, "events.jsonl")
NOVEL_DIAGNOSTIC_BACKUP_FILE = os.path.join(NOVEL_DIAGNOSTIC_DIR, "events.jsonl.1")
NOVEL_DIAGNOSTIC_LATEST_ERROR_FILE = os.path.join(NOVEL_DIAGNOSTIC_DIR, "latest_error.json")
NOVEL_DIAGNOSTIC_SNAPSHOT_DIR = os.path.join(NOVEL_DIAGNOSTIC_DIR, "failure_snapshots")
NOVEL_DIAGNOSTIC_LATEST_SNAPSHOT_FILE = os.path.join(
    NOVEL_DIAGNOSTIC_DIR, "latest_failure_snapshot.json"
)
NOVEL_DIAGNOSTIC_LATEST_EXCHANGE_FILE = os.path.join(
    NOVEL_DIAGNOSTIC_DIR, "latest_model_exchange.json"
)
NOVEL_DIAGNOSTIC_MAX_BYTES = 12 * 1024 * 1024
NOVEL_DIAGNOSTIC_MAX_SNAPSHOTS = 60
NOVEL_DIAGNOSTIC_SNAPSHOT_TEXT_LIMIT = 180000
_NOVEL_DIAGNOSTIC_LOCK = threading.Lock()
_NOVEL_DIAGNOSTIC_HOOKS_INSTALLED = False


def _redact_novel_diagnostic_text(value, limit=4000, strip=True):
    text = str(value or "")
    text = re.sub(
        r"(?i)(api[-_ ]?key|authorization|bearer|access[-_ ]?token|password|secret)(\s*[:=]\s*)(?:bearer\s+)?[^,;\s]+",
        r"\1\2[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)\b(bearer)\s+[^,;\s]+",
        r"\1 [REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)([?&](?:api[-_ ]?key|access[-_ ]?token|token|password|secret)=)[^&\s]+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@",
        r"\1[REDACTED]@",
        text,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED_KEY]", text)
    if strip:
        text = text.strip()
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _sanitize_novel_diagnostic_value(value, depth=0):
    if depth > 6:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_novel_diagnostic_text(value)
    if isinstance(value, dict):
        result = {}
        for raw_key, raw_value in list(value.items())[:120]:
            key = str(raw_key or "")
            lowered = key.lower().replace("-", "_")
            if any(
                marker in lowered
                for marker in ("api_key", "authorization", "password", "access_token", "proxy_url")
            ):
                continue
            result[key] = _sanitize_novel_diagnostic_value(raw_value, depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_novel_diagnostic_value(item, depth + 1) for item in list(value)[:120]]
    return _redact_novel_diagnostic_text(value)


def _write_novel_diagnostic_json(path, data):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    temp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
        os.replace(temp_path, path)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass


def append_novel_diagnostic_event(event):
    """Append one bounded, secret-redacted diagnostic event for novel writing."""
    if not isinstance(event, dict):
        event = {"event": str(event or "unknown")}
    record = _sanitize_novel_diagnostic_value(event)
    if not isinstance(record, dict):
        record = {"event": "unknown", "detail": record}
    record.setdefault("schema_version", 1)
    record.setdefault("recorded_at", now_str())
    record.setdefault("event", "unknown")
    record.setdefault(
        "event_id",
        hashlib.sha256(
            f"{time.time_ns()}:{os.getpid()}:{threading.get_ident()}".encode("utf-8")
        ).hexdigest()[:20],
    )
    record.setdefault("process_id", os.getpid())
    record.setdefault("thread_name", threading.current_thread().name)
    try:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with _NOVEL_DIAGNOSTIC_LOCK:
            os.makedirs(NOVEL_DIAGNOSTIC_DIR, exist_ok=True)
            if (
                os.path.exists(NOVEL_DIAGNOSTIC_LOG_FILE)
                and os.path.getsize(NOVEL_DIAGNOSTIC_LOG_FILE) + len(line.encode("utf-8"))
                > NOVEL_DIAGNOSTIC_MAX_BYTES
            ):
                try:
                    if os.path.exists(NOVEL_DIAGNOSTIC_BACKUP_FILE):
                        os.remove(NOVEL_DIAGNOSTIC_BACKUP_FILE)
                    os.replace(NOVEL_DIAGNOSTIC_LOG_FILE, NOVEL_DIAGNOSTIC_BACKUP_FILE)
                except Exception:
                    pass
            with open(NOVEL_DIAGNOSTIC_LOG_FILE, "a", encoding="utf-8") as handle:
                handle.write(line)
            if str(record.get("level", "") or "").lower() in {"error", "fatal"}:
                _write_novel_diagnostic_json(NOVEL_DIAGNOSTIC_LATEST_ERROR_FILE, record)
        return NOVEL_DIAGNOSTIC_LOG_FILE
    except Exception:
        return ""


def read_novel_diagnostic_events(limit=200):
    try:
        limit = max(1, min(2000, int(limit or 200)))
    except Exception:
        limit = 200
    lines = []
    for path in (NOVEL_DIAGNOSTIC_BACKUP_FILE, NOVEL_DIAGNOSTIC_LOG_FILE):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                lines.extend(handle.readlines())
        except Exception:
            continue
    lines = lines[-limit:]
    events = []
    for line in lines:
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def read_latest_novel_diagnostic_error():
    value = load_json_file(NOVEL_DIAGNOSTIC_LATEST_ERROR_FILE, {})
    return value if isinstance(value, dict) else {}


def _prepare_novel_diagnostic_snapshot(request_id, payload):
    safe_request_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(request_id or "failure")).strip("._")
    safe_request_id = safe_request_id[:120] or "failure"
    raw_payload = payload if isinstance(payload, dict) else {"detail": payload}
    content_keys = {
        "system_prompt",
        "user_context",
        "sent_user_context",
        "partial_output",
        "validation_payload",
    }
    compact_payload = {
        key: value for key, value in raw_payload.items() if str(key) not in content_keys
    }
    snapshot = _sanitize_novel_diagnostic_value(compact_payload)
    snapshot = snapshot if isinstance(snapshot, dict) else {"detail": snapshot}
    for key in content_keys:
        if key not in raw_payload:
            continue
        snapshot[key] = _redact_novel_diagnostic_text(
            raw_payload.get(key, ""),
            limit=NOVEL_DIAGNOSTIC_SNAPSHOT_TEXT_LIMIT,
            strip=False,
        )
    snapshot["schema_version"] = 1
    snapshot["request_id"] = safe_request_id
    snapshot.setdefault("saved_at", now_str())
    snapshot.setdefault("process_id", os.getpid())
    return safe_request_id, snapshot


def save_novel_diagnostic_snapshot(request_id, payload):
    """Persist one bounded failure snapshot without credentials."""
    safe_request_id, snapshot = _prepare_novel_diagnostic_snapshot(request_id, payload)
    path = os.path.join(NOVEL_DIAGNOSTIC_SNAPSHOT_DIR, f"{safe_request_id}.json")
    try:
        with _NOVEL_DIAGNOSTIC_LOCK:
            _write_novel_diagnostic_json(path, snapshot)
            _write_novel_diagnostic_json(NOVEL_DIAGNOSTIC_LATEST_SNAPSHOT_FILE, snapshot)
            candidates = []
            for name in os.listdir(NOVEL_DIAGNOSTIC_SNAPSHOT_DIR):
                candidate = os.path.join(NOVEL_DIAGNOSTIC_SNAPSHOT_DIR, name)
                if name.endswith(".json") and os.path.isfile(candidate):
                    try:
                        candidates.append((os.path.getmtime(candidate), candidate))
                    except Exception:
                        continue
            candidates.sort()
            for _mtime, stale_path in candidates[:-NOVEL_DIAGNOSTIC_MAX_SNAPSHOTS]:
                try:
                    os.remove(stale_path)
                except Exception:
                    pass
        return path
    except Exception:
        return ""


def save_novel_diagnostic_latest_exchange(request_id, payload):
    """Keep only the latest completed model exchange for post-processing crash diagnosis."""
    _safe_request_id, snapshot = _prepare_novel_diagnostic_snapshot(request_id, payload)
    try:
        with _NOVEL_DIAGNOSTIC_LOCK:
            _write_novel_diagnostic_json(NOVEL_DIAGNOSTIC_LATEST_EXCHANGE_FILE, snapshot)
        return NOVEL_DIAGNOSTIC_LATEST_EXCHANGE_FILE
    except Exception:
        return ""


def _record_uncaught_novel_exception(exc_type, exc_value, exc_traceback, origin="main"):
    try:
        formatted = "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback)
        )
    except Exception:
        formatted = str(exc_value or exc_type or "")
    return append_novel_diagnostic_event({
        "event": "uncaught_exception",
        "level": "fatal",
        "origin": str(origin or "main"),
        "error_type": getattr(exc_type, "__name__", str(exc_type or "")),
        "error": str(exc_value or ""),
        "traceback": formatted,
        "latest_model_exchange": (
            NOVEL_DIAGNOSTIC_LATEST_EXCHANGE_FILE
            if os.path.exists(NOVEL_DIAGNOSTIC_LATEST_EXCHANGE_FILE) else ""
        ),
        "latest_failure_snapshot": (
            NOVEL_DIAGNOSTIC_LATEST_SNAPSHOT_FILE
            if os.path.exists(NOVEL_DIAGNOSTIC_LATEST_SNAPSHOT_FILE) else ""
        ),
    })


def install_novel_diagnostic_exception_hooks():
    """Capture uncaught Python and background-thread failures without swallowing them."""
    global _NOVEL_DIAGNOSTIC_HOOKS_INSTALLED
    if _NOVEL_DIAGNOSTIC_HOOKS_INSTALLED:
        return
    _NOVEL_DIAGNOSTIC_HOOKS_INSTALLED = True
    original_sys_hook = sys.excepthook

    def sys_hook(exc_type, exc_value, exc_traceback):
        _record_uncaught_novel_exception(exc_type, exc_value, exc_traceback, "main")
        if original_sys_hook:
            original_sys_hook(exc_type, exc_value, exc_traceback)

    sys.excepthook = sys_hook
    original_thread_hook = getattr(threading, "excepthook", None)
    if original_thread_hook is not None:
        def thread_hook(args):
            _record_uncaught_novel_exception(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
                f"thread:{getattr(args.thread, 'name', '')}",
            )
            original_thread_hook(args)

        threading.excepthook = thread_hook


def ensure_novel_storage():
    os.makedirs(NOVEL_DIR, exist_ok=True)


def _save_novel_json_strict(path, data):
    """Keep novel persistence failures observable to the writing pipeline."""
    _atomic_write_json(path, data)


def _normalized_style_profile_record(style_reference, cache_entry, name="", source_project=""):
    reference = str(style_reference or "").strip()
    if not reference or not isinstance(cache_entry, dict):
        return None
    reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
    normalized_project = _normalize_project({
        "style_reference": reference,
        "style_profile_cache": {reference_hash: cache_entry},
    })
    normalized_entry = normalized_project.get("style_profile_cache", {}).get(reference_hash, {})
    profile = str(normalized_entry.get("profile", "") or "").strip()
    status = str(normalized_entry.get("status", "") or "").strip()
    if not profile or (status and status != "complete"):
        return None
    return {
        "id": reference_hash,
        "name": str(name or "").strip() or f"永久文风 {reference_hash[:8]}",
        "reference_hash": reference_hash,
        "style_reference": reference,
        "cache_entry": normalized_entry,
        "source_project": str(source_project or "").strip(),
        "updated_at": str(normalized_entry.get("cached_at", "") or "").strip() or now_str(),
    }


def load_style_profile_library():
    raw = load_json_file(NOVEL_STYLE_LIBRARY_FILE, {})
    items = raw.get("profiles", []) if isinstance(raw, dict) else []
    profiles = []
    seen = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        record = _normalized_style_profile_record(
            item.get("style_reference", ""),
            item.get("cache_entry", {}),
            item.get("name", ""),
            item.get("source_project", ""),
        )
        if not record or record["id"] in seen:
            continue
        record["created_at"] = str(item.get("created_at", "") or "").strip() or record["updated_at"]
        stored_updated_at = str(item.get("updated_at", "") or "").strip()
        if stored_updated_at:
            record["updated_at"] = stored_updated_at
        seen.add(record["id"])
        profiles.append(record)
    profiles.sort(key=lambda item: (item.get("name", ""), item.get("id", "")))
    return profiles


def save_style_profile_library(profiles):
    normalized = []
    seen = set()
    for item in profiles if isinstance(profiles, list) else []:
        if not isinstance(item, dict):
            continue
        record = _normalized_style_profile_record(
            item.get("style_reference", ""),
            item.get("cache_entry", {}),
            item.get("name", ""),
            item.get("source_project", ""),
        )
        if not record or record["id"] in seen:
            continue
        record["created_at"] = str(item.get("created_at", "") or "").strip() or now_str()
        record["updated_at"] = str(item.get("updated_at", "") or "").strip() or now_str()
        seen.add(record["id"])
        normalized.append(record)
    normalized.sort(key=lambda item: (item.get("name", ""), item.get("id", "")))
    _save_novel_json_strict(NOVEL_STYLE_LIBRARY_FILE, {"version": 1, "profiles": normalized})
    return normalized


def get_style_profile(profile_id):
    profile_id = str(profile_id or "").strip().lower()
    if not profile_id:
        return None
    for item in load_style_profile_library():
        if item.get("id") == profile_id:
            return deepcopy(item)
    return None


def upsert_style_profile(style_reference, cache_entry, name="", source_project=""):
    record = _normalized_style_profile_record(style_reference, cache_entry, name, source_project)
    if not record:
        return ""
    profiles = load_style_profile_library()
    existing = next((item for item in profiles if item.get("id") == record["id"]), None)
    if existing:
        record["created_at"] = existing.get("created_at", "") or now_str()
        if existing.get("name") and not name:
            record["name"] = existing["name"]
        profiles = [record if item.get("id") == record["id"] else item for item in profiles]
    else:
        record["created_at"] = now_str()
        profiles.append(record)
    record["updated_at"] = now_str()
    save_style_profile_library(profiles)
    return record["id"]


def sync_style_profile_library_from_projects():
    before = load_style_profile_library()
    profiles = {item.get("id"): item for item in before if item.get("id")}
    paths = [path for _mtime, _name, path in list_project_files(include_empty=True)]
    if os.path.exists(NOVEL_DRAFT_FILE):
        paths.append(NOVEL_DRAFT_FILE)
    for path in paths:
        data = load_json_file(path, {})
        if not isinstance(data, dict):
            continue
        reference = str(data.get("style_reference", "") or "").strip()
        if not reference:
            continue
        reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        cache = data.get("style_profile_cache", {})
        entry = cache.get(reference_hash, {}) if isinstance(cache, dict) else {}
        title = str(data.get("meta", {}).get("title", "") or "").strip() if isinstance(data.get("meta"), dict) else ""
        record = _normalized_style_profile_record(reference, entry, title, path)
        if not record:
            continue
        old = profiles.get(record["id"])
        if old:
            record["created_at"] = old.get("created_at", "") or record["updated_at"]
            record["name"] = old.get("name", "") or record["name"]
        else:
            record["created_at"] = record["updated_at"]
        profiles[record["id"]] = record
    merged = list(profiles.values())
    if merged != before or (merged and not os.path.exists(NOVEL_STYLE_LIBRARY_FILE)):
        return save_style_profile_library(merged)
    return before


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
            body_words += _body_display_len(chap.get("text", ""))
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
    if not merged_state.get("candidate_postprocess") and fallback_state.get("candidate_postprocess"):
        merged_state["candidate_postprocess"] = deepcopy(fallback_state["candidate_postprocess"])
    if merged_state:
        primary["analysis_state"] = merged_state
    return primary


def _file_mtime_ns(path):
    try:
        stat = os.stat(path)
        return int(getattr(stat, "st_mtime_ns", stat.st_mtime * 1_000_000_000))
    except Exception:
        return 0


def load_initial_project_data():
    if os.path.exists(NOVEL_DRAFT_FILE):
        last = load_json_file(NOVEL_LAST_FILE, {}) if os.path.exists(NOVEL_LAST_FILE) else {}
        last_path = str(last.get("path", "") or "").strip() if isinstance(last, dict) else ""
        draft_data = load_json_file(NOVEL_DRAFT_FILE, _default_project())
        if last_path and os.path.exists(last_path):
            project_data = load_json_file(last_path, {})
            if isinstance(project_data, dict):
                if _file_mtime_ns(last_path) > _file_mtime_ns(NOVEL_DRAFT_FILE):
                    project_data = _merge_candidate_analysis_state(project_data, draft_data)
                    return project_data, last_path
                draft_data = _merge_candidate_analysis_state(draft_data, project_data)
            return draft_data, last_path
        return draft_data, NOVEL_DRAFT_FILE
    files = list_project_files()
    if files:
        _mtime, _name, path = files[0]
        return load_json_file(path, _default_project()), path
    return _default_project(), ""


def save_draft_project(data):
    _save_novel_json_strict(NOVEL_DRAFT_FILE, _normalize_project(data))


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
    _save_novel_json_strict(path, data)
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
        _save_novel_json_strict(NOVEL_LAST_FILE, {"path": path})


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
