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
NOVEL_BACKUP_DIR = os.path.join(HISTORY_DIR, "novel_project_backups")
NOVEL_DRAFT_FILE = os.path.join(HISTORY_DIR, "novel_draft.json")
NOVEL_LAST_FILE = os.path.join(HISTORY_DIR, "novel_last.json")
NOVEL_PROJECT_SUMMARY_CACHE_FILE = os.path.join(
    HISTORY_DIR, "novel_project_summary_cache.json"
)
NOVEL_STYLE_LIBRARY_FILE = os.path.join(HISTORY_DIR, "novel_style_profiles.json")
NOVEL_BUILTIN_STYLE_LIBRARY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "resources",
    "novel",
    "default_style_profiles.json",
)
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
NOVEL_MEMORY_DIAGNOSTIC_LOG_FILE = os.path.join(
    NOVEL_DIAGNOSTIC_DIR, "memory_sync_failures.jsonl"
)
NOVEL_MEMORY_DIAGNOSTIC_BACKUP_FILE = os.path.join(
    NOVEL_DIAGNOSTIC_DIR, "memory_sync_failures.jsonl.1"
)
NOVEL_DIAGNOSTIC_MAX_BYTES = 12 * 1024 * 1024
NOVEL_MEMORY_DIAGNOSTIC_MAX_BYTES = 8 * 1024 * 1024
NOVEL_DIAGNOSTIC_MAX_SNAPSHOTS = 60
NOVEL_DIAGNOSTIC_SNAPSHOT_TEXT_LIMIT = 180000
_NOVEL_DIAGNOSTIC_LOCK = threading.Lock()
_NOVEL_DIAGNOSTIC_HOOKS_INSTALLED = False
_STYLE_PROFILE_LIBRARY_CACHE_LOCK = threading.Lock()
_STYLE_PROFILE_LIBRARY_CACHE_SIGNATURE = None
_STYLE_PROFILE_LIBRARY_CACHE = None


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


def append_novel_memory_diagnostic_event(event):
    """Append a compact post-write state failure record, excluding prose/context."""
    if not isinstance(event, dict):
        event = {"event": str(event or "unknown")}
    record = _sanitize_novel_diagnostic_value(event)
    if not isinstance(record, dict):
        record = {"event": "unknown", "detail": record}
    for key in (
        "system_prompt", "user_context", "sent_user_context", "partial_output",
        "validation_payload", "body", "text", "final_text", "output",
    ):
        record.pop(key, None)
    record.setdefault("schema_version", 1)
    record.setdefault("record_type", "novel_memory_failure")
    record.setdefault("recorded_at", now_str())
    record.setdefault("event", "unknown")
    record.setdefault(
        "event_id",
        hashlib.sha256(
            f"memory:{time.time_ns()}:{os.getpid()}:{threading.get_ident()}".encode("utf-8")
        ).hexdigest()[:20],
    )
    record.setdefault("process_id", os.getpid())
    record.setdefault("thread_name", threading.current_thread().name)
    try:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with _NOVEL_DIAGNOSTIC_LOCK:
            os.makedirs(NOVEL_DIAGNOSTIC_DIR, exist_ok=True)
            if (
                os.path.exists(NOVEL_MEMORY_DIAGNOSTIC_LOG_FILE)
                and os.path.getsize(NOVEL_MEMORY_DIAGNOSTIC_LOG_FILE)
                + len(line.encode("utf-8"))
                > NOVEL_MEMORY_DIAGNOSTIC_MAX_BYTES
            ):
                try:
                    if os.path.exists(NOVEL_MEMORY_DIAGNOSTIC_BACKUP_FILE):
                        os.remove(NOVEL_MEMORY_DIAGNOSTIC_BACKUP_FILE)
                    os.replace(
                        NOVEL_MEMORY_DIAGNOSTIC_LOG_FILE,
                        NOVEL_MEMORY_DIAGNOSTIC_BACKUP_FILE,
                    )
                except Exception:
                    pass
            with open(NOVEL_MEMORY_DIAGNOSTIC_LOG_FILE, "a", encoding="utf-8") as handle:
                handle.write(line)
        return NOVEL_MEMORY_DIAGNOSTIC_LOG_FILE
    except Exception:
        return ""


def read_novel_memory_diagnostic_events(limit=200):
    """Read compact post-write state failures from the current and rotated logs."""
    try:
        limit = max(1, min(2000, int(limit or 200)))
    except Exception:
        limit = 200
    lines = []
    for path in (
        NOVEL_MEMORY_DIAGNOSTIC_BACKUP_FILE,
        NOVEL_MEMORY_DIAGNOSTIC_LOG_FILE,
    ):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                lines.extend(handle.readlines())
        except Exception:
            continue
    events = []
    for line in lines[-limit:]:
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


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
    """Keep a request-scoped exchange and update the rolling latest pointer."""
    _safe_request_id, snapshot = _prepare_novel_diagnostic_snapshot(request_id, payload)
    exchange_dir = os.path.join(
        os.path.dirname(NOVEL_DIAGNOSTIC_LATEST_EXCHANGE_FILE),
        "model_exchanges",
    )
    request_path = os.path.join(exchange_dir, f"{_safe_request_id}.json")
    try:
        with _NOVEL_DIAGNOSTIC_LOCK:
            _write_novel_diagnostic_json(request_path, snapshot)
            _write_novel_diagnostic_json(NOVEL_DIAGNOSTIC_LATEST_EXCHANGE_FILE, snapshot)
        return request_path
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
    os.makedirs(NOVEL_BACKUP_DIR, exist_ok=True)


def _save_novel_json_strict(path, data):
    """Keep novel persistence failures observable to the writing pipeline."""
    _atomic_write_json(path, data)


def _normalized_style_profile_record(
    style_reference,
    cache_entry,
    name="",
    source_project="",
    profile_id="",
):
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
    archive_id = str(profile_id or cache_entry.get("archive_id", "") or reference_hash).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", archive_id):
        archive_id = reference_hash
    return {
        # A library archive is not always identical to its raw sample.  This
        # lets a new semantic version coexist with the historical archive.
        "id": archive_id,
        "name": str(name or "").strip() or f"永久文风 {reference_hash[:8]}",
        "reference_hash": reference_hash,
        "style_reference": reference,
        "cache_entry": normalized_entry,
        "source_project": str(source_project or "").strip(),
        "updated_at": str(normalized_entry.get("cached_at", "") or "").strip() or now_str(),
    }


def _style_profile_file_signature(path):
    try:
        stat = os.stat(path)
        return (
            os.path.abspath(path),
            True,
            int(getattr(stat, "st_mtime_ns", stat.st_mtime * 1_000_000_000)),
            int(stat.st_size),
        )
    except Exception:
        return (os.path.abspath(str(path or "")), False, 0, 0)


def _style_profile_library_signature():
    return tuple(
        _style_profile_file_signature(path)
        for path in (NOVEL_BUILTIN_STYLE_LIBRARY_FILE, NOVEL_STYLE_LIBRARY_FILE)
    )


def _invalidate_style_profile_library_cache():
    global _STYLE_PROFILE_LIBRARY_CACHE_SIGNATURE, _STYLE_PROFILE_LIBRARY_CACHE
    with _STYLE_PROFILE_LIBRARY_CACHE_LOCK:
        _STYLE_PROFILE_LIBRARY_CACHE_SIGNATURE = None
        _STYLE_PROFILE_LIBRARY_CACHE = None


def _stored_style_profile_record(item):
    if not isinstance(item, dict):
        return None
    reference = str(item.get("style_reference", "") or "").strip()
    if not reference:
        return None
    reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
    stored_reference_hash = str(item.get("reference_hash", "") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", stored_reference_hash):
        reference_hash = stored_reference_hash
    cache_entry = item.get("cache_entry", {})
    if isinstance(cache_entry, dict):
        normalized_entry = deepcopy(cache_entry)
        profile = str(normalized_entry.get("profile", "") or "").strip()
        status = str(normalized_entry.get("status", "") or "").strip()
    else:
        profile = str(cache_entry or "").strip()
        status = ""
        normalized_entry = {"profile": profile}
    if not profile or (status and status != "complete"):
        return None
    normalized_entry["profile"] = profile
    if status:
        normalized_entry["status"] = status
    archive_id = str(
        item.get("id", "")
        or normalized_entry.get("archive_id", "")
        or reference_hash
    ).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", archive_id):
        archive_id = reference_hash
    cached_at = str(normalized_entry.get("cached_at", "") or "").strip()
    updated_at = str(item.get("updated_at", "") or "").strip() or cached_at or now_str()
    return {
        "id": archive_id,
        "name": str(item.get("name", "") or "").strip() or f"永久文风 {reference_hash[:8]}",
        "reference_hash": reference_hash,
        "style_reference": reference,
        "cache_entry": normalized_entry,
        "source_project": str(item.get("source_project", "") or "").strip(),
        "created_at": str(item.get("created_at", "") or "").strip() or updated_at,
        "updated_at": updated_at,
    }


def _load_style_profile_library_file(path):
    raw = load_json_file(path, {})
    items = raw.get("profiles", []) if isinstance(raw, dict) else []
    profiles = []
    seen = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        record = _stored_style_profile_record(item)
        if not record or record["id"] in seen:
            continue
        seen.add(record["id"])
        profiles.append(record)
    profiles.sort(key=lambda item: (item.get("name", ""), item.get("id", "")))
    return profiles


def load_style_profile_library():
    global _STYLE_PROFILE_LIBRARY_CACHE_SIGNATURE, _STYLE_PROFILE_LIBRARY_CACHE
    signature = _style_profile_library_signature()
    with _STYLE_PROFILE_LIBRARY_CACHE_LOCK:
        if (
            _STYLE_PROFILE_LIBRARY_CACHE_SIGNATURE == signature
            and isinstance(_STYLE_PROFILE_LIBRARY_CACHE, list)
        ):
            return deepcopy(_STYLE_PROFILE_LIBRARY_CACHE)
    profiles = {}
    for path in (NOVEL_BUILTIN_STYLE_LIBRARY_FILE, NOVEL_STYLE_LIBRARY_FILE):
        for record in _load_style_profile_library_file(path):
            profiles[record["id"]] = record
    result = sorted(
        profiles.values(),
        key=lambda item: (item.get("name", ""), item.get("id", "")),
    )
    with _STYLE_PROFILE_LIBRARY_CACHE_LOCK:
        _STYLE_PROFILE_LIBRARY_CACHE_SIGNATURE = signature
        _STYLE_PROFILE_LIBRARY_CACHE = deepcopy(result)
    return deepcopy(result)


def save_style_profile_library(profiles):
    normalized = []
    seen = set()
    for item in profiles if isinstance(profiles, list) else []:
        if not isinstance(item, dict):
            continue
        record = _stored_style_profile_record(item)
        if not record:
            record = _normalized_style_profile_record(
                item.get("style_reference", ""),
                item.get("cache_entry", {}),
                item.get("name", ""),
                item.get("source_project", ""),
                item.get("id", ""),
            )
        if not record or record["id"] in seen:
            continue
        record["created_at"] = str(item.get("created_at", "") or "").strip() or now_str()
        record["updated_at"] = str(item.get("updated_at", "") or "").strip() or now_str()
        seen.add(record["id"])
        normalized.append(record)
    normalized.sort(key=lambda item: (item.get("name", ""), item.get("id", "")))
    _save_novel_json_strict(NOVEL_STYLE_LIBRARY_FILE, {"version": 1, "profiles": normalized})
    _invalidate_style_profile_library_cache()
    return normalized


def get_style_profile(profile_id):
    profile_id = str(profile_id or "").strip().lower()
    if not profile_id:
        return None
    for item in load_style_profile_library():
        if item.get("id") == profile_id:
            return deepcopy(item)
    return None


def upsert_style_profile(
    style_reference,
    cache_entry,
    name="",
    source_project="",
    profile_id="",
):
    record = _normalized_style_profile_record(
        style_reference,
        cache_entry,
        name,
        source_project,
        profile_id,
    )
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
        selected_id = str(data.get("style_profile_id", "") or "").strip().lower()
        selected_record = profiles.get(selected_id, {}) if selected_id else {}
        selected_matches_reference = (
            isinstance(selected_record, dict)
            and selected_record.get("reference_hash") == reference_hash
        )
        record = _stored_style_profile_record({
            "id": selected_id if selected_matches_reference else "",
            "name": title,
            "reference_hash": reference_hash,
            "style_reference": reference,
            "cache_entry": entry,
            "source_project": path,
        })
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
        raw = load_json_file(path, {})
        if isinstance(raw, dict) and raw.get("auto_saved_reason") and not include_empty:
            continue
        data = _normalize_project(raw)
        records.append(
            {
                "mtime": mtime,
                "filename": filename,
                "path": path,
                "data": data,
            }
        )
    return records


def _project_summary_cache_path():
    default_project_dir = os.path.join(HISTORY_DIR, "novel_projects")
    try:
        if os.path.abspath(NOVEL_DIR) != os.path.abspath(default_project_dir):
            return os.path.join(os.path.dirname(os.path.abspath(NOVEL_DIR)), "novel_project_summary_cache.json")
    except Exception:
        pass
    return NOVEL_PROJECT_SUMMARY_CACHE_FILE


def _load_project_summary_cache():
    cache = load_json_file(_project_summary_cache_path(), {})
    if not isinstance(cache, dict) or cache.get("version") != 1:
        return {}
    entries = cache.get("entries", {})
    return entries if isinstance(entries, dict) else {}


def _save_project_summary_cache(entries):
    try:
        _save_novel_json_strict(_project_summary_cache_path(), {
            "version": 1,
            "updated_at": now_str(),
            "entries": entries if isinstance(entries, dict) else {},
        })
    except Exception:
        pass


def _project_summary_signature(path):
    try:
        stat = os.stat(path)
        mtime_ns = int(getattr(stat, "st_mtime_ns", stat.st_mtime * 1_000_000_000))
        size = int(stat.st_size)
        return mtime_ns, size
    except Exception:
        return 0, 0


def _build_project_summary_record(mtime, filename, path, data):
    data = data if isinstance(data, dict) else {}
    meta = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
    chapters = data.get("chapters", []) if isinstance(data.get("chapters"), list) else []
    body_words = 0
    for chap in chapters:
        if not isinstance(chap, dict):
            continue
        body_words += _body_display_len(chap.get("text", ""))
    auto_saved_reason = str(data.get("auto_saved_reason", "") or "").strip()
    return {
        "mtime": mtime,
        "filename": filename,
        "path": path,
        "title": meta.get("title") or os.path.splitext(filename)[0],
        "body_words": body_words,
        "chapters": len(chapters),
        "auto_saved_reason": auto_saved_reason,
    }


def list_project_summaries(include_empty=False):
    records = []
    cache = _load_project_summary_cache()
    next_cache = {}
    cache_changed = False
    for mtime, filename, path in list_project_files(include_empty=include_empty):
        mtime_ns, size = _project_summary_signature(path)
        key = os.path.abspath(path)
        cached = cache.get(key, {}) if isinstance(cache, dict) else {}
        record = None
        if (
            isinstance(cached, dict)
            and cached.get("mtime_ns") == mtime_ns
            and cached.get("size") == size
            and isinstance(cached.get("record"), dict)
        ):
            record = deepcopy(cached["record"])
            record["mtime"] = mtime
            record["filename"] = filename
            record["path"] = path
        else:
            raw = load_json_file(path, {})
            record = _build_project_summary_record(
                mtime,
                filename,
                path,
                raw if isinstance(raw, dict) else {},
            )
            cache_changed = True
        if record.get("auto_saved_reason") and not include_empty:
            next_cache[key] = {
                "mtime_ns": mtime_ns,
                "size": size,
                "record": record,
            }
            continue
        next_cache[key] = {
            "mtime_ns": mtime_ns,
            "size": size,
            "record": record,
        }
        records.append(record)
    if set(next_cache) != set(cache if isinstance(cache, dict) else {}):
        cache_changed = True
    if cache_changed:
        _save_project_summary_cache(next_cache)
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
                project_data = _merge_candidate_analysis_state(project_data, draft_data)
                return project_data, last_path
            return draft_data, last_path
        return draft_data, NOVEL_DRAFT_FILE
    files = list_project_summaries()
    if files:
        path = files[0].get("path", "")
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
    path = unique_project_backup_path(title, reason)
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


def unique_project_backup_path(title, reason="备份"):
    project_name = _safe_name(title) or "未命名小说"
    backup_dir = os.path.join(NOVEL_BACKUP_DIR, project_name)
    os.makedirs(backup_dir, exist_ok=True)
    base = _safe_name(f"{project_name}_{reason}") or f"{project_name}_备份"
    timestamp = safe_project_timestamp()
    path = os.path.join(backup_dir, f"{base}_{timestamp}.json")
    index = 2
    while os.path.exists(path):
        path = os.path.join(backup_dir, f"{base}_{timestamp}_{index}.json")
        index += 1
    return path


def named_project_path(name):
    return os.path.join(NOVEL_DIR, f"{_safe_name(name) or '未命名小说'}.json")
