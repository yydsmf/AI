import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
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
NOVEL_CHARACTER_STYLE_LIBRARY_FILE = os.path.join(
    HISTORY_DIR,
    "novel_character_styles.json",
)
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
NOVEL_RAW_OUTPUT_DIR = os.path.join(NOVEL_DIAGNOSTIC_DIR, "raw_outputs")
NOVEL_RAW_OUTPUT_MAX_FILES = 240
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

# Semantic V4 archives take precedence in the main writing interface.
_STYLE_PROFILE_V4_SCHEMA = "semantic_voice_v4"


def _is_v4_style_profile_record(item):
    if not isinstance(item, dict):
        return False
    cache_entry = item.get("cache_entry", {})
    if not isinstance(cache_entry, dict):
        return False
    return (
        str(cache_entry.get("style_archive_schema", "") or "").strip()
        == _STYLE_PROFILE_V4_SCHEMA
        and str(cache_entry.get("version", "") or "").strip() == "4"
        and str(cache_entry.get("semantic_archive_version", "") or "").strip() == "4"
    )


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


def _novel_raw_output_slot_key(request_id, metadata):
    """Return the logical slot whose latest raw response should be kept."""
    metadata = metadata if isinstance(metadata, dict) else {}
    nested = metadata.get("metadata", {})
    nested = nested if isinstance(nested, dict) else {}

    stage = str(
        metadata.get("stage")
        or nested.get("stage")
        or nested.get("creation_step")
        or ""
    ).strip()
    if not stage:
        stage = str(request_id or "raw-output").strip() or "raw-output"

    # The wizard may split one visible step into several API batches.  Those
    # batches are implementation details, so they share one latest-response
    # slot.  Chapter planning keeps event placement separate from the actual
    # outline request because they are two different generation stages.
    for prefix in ("premise:", "bible:", "stage_plan:"):
        if stage.startswith(prefix):
            stage = prefix[:-1]
            break

    project = str(
        metadata.get("project_path")
        or nested.get("project_path")
        or metadata.get("project_title")
        or nested.get("project_title")
        or "current-project"
    ).strip()
    return f"{project}|{stage}"


def _novel_raw_output_slot_id(slot_key):
    digest = hashlib.sha256(str(slot_key or "raw-output").encode("utf-8")).hexdigest()
    return f"slot-{digest[:24]}"


def _novel_raw_output_record_slot(record):
    if not isinstance(record, dict):
        return ""
    saved_slot = str(record.get("slot_key", "") or "").strip()
    if saved_slot:
        return saved_slot
    return _novel_raw_output_slot_key(
        record.get("request_id", ""),
        record,
    )


def _prune_novel_raw_output_slots():
    """Keep only the newest text/metadata pair for each logical stage."""
    try:
        names = os.listdir(NOVEL_RAW_OUTPUT_DIR)
    except OSError:
        return

    records = []
    referenced_text_paths = set()
    for name in names:
        if not name.endswith(".json"):
            continue
        metadata_path = os.path.join(NOVEL_RAW_OUTPUT_DIR, name)
        if not os.path.isfile(metadata_path):
            continue
        try:
            with open(metadata_path, "r", encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        raw_path = str(record.get("raw_output_path", "") or "").strip()
        if raw_path:
            referenced_text_paths.add(os.path.abspath(raw_path))
        try:
            mtime = os.path.getmtime(metadata_path)
        except OSError:
            mtime = 0
        records.append((
            _novel_raw_output_record_slot(record),
            mtime,
            metadata_path,
            raw_path,
        ))

    newest_by_slot = {}
    for slot, mtime, metadata_path, raw_path in records:
        previous = newest_by_slot.get(slot)
        if previous is None or mtime >= previous[0]:
            newest_by_slot[slot] = (mtime, metadata_path, raw_path)

    keep_metadata = {item[1] for item in newest_by_slot.values()}
    keep_text = {
        os.path.abspath(item[2])
        for item in newest_by_slot.values()
        if item[2]
    }
    for _slot, _mtime, metadata_path, raw_path in records:
        if metadata_path in keep_metadata:
            continue
        try:
            os.remove(metadata_path)
        except OSError:
            pass
        if raw_path and os.path.abspath(raw_path) not in keep_text:
            try:
                os.remove(raw_path)
            except OSError:
                pass

    # Old versions could leave text files without a metadata pair.  They are
    # diagnostic leftovers, not project data, and are safe to remove here.
    try:
        for name in os.listdir(NOVEL_RAW_OUTPUT_DIR):
            if not name.endswith(".txt"):
                continue
            path = os.path.abspath(os.path.join(NOVEL_RAW_OUTPUT_DIR, name))
            if path not in keep_text:
                try:
                    os.remove(path)
                except OSError:
                    pass
    except OSError:
        pass


def save_novel_raw_model_output(request_id, attempt_index, raw_text, metadata=None):
    """Persist the latest exact response for one logical generation stage."""
    safe_request_id = re.sub(
        r"[^A-Za-z0-9_.-]+", "_", str(request_id or "raw-output")
    ).strip("._")[:120] or "raw-output"
    try:
        attempt_index = max(1, int(attempt_index or 1))
    except (TypeError, ValueError):
        attempt_index = 1
    text = str(raw_text or "")
    raw_metadata = metadata if isinstance(metadata, dict) else {}
    slot_key = _novel_raw_output_slot_key(request_id, raw_metadata)
    slot_id = _novel_raw_output_slot_id(slot_key)
    stem = f"{slot_id}--latest"
    text_path = os.path.join(NOVEL_RAW_OUTPUT_DIR, f"{stem}.txt")
    metadata_path = os.path.join(NOVEL_RAW_OUTPUT_DIR, f"{stem}.json")
    record = {
        "schema_version": 2,
        "record_type": "novel_raw_model_output",
        "request_id": safe_request_id,
        "attempt_index": attempt_index,
        "slot_key": slot_key,
        "saved_at": now_str(),
        "output_chars": len(text),
        "output_utf8_bytes": len(text.encode("utf-8", errors="replace")),
        "output_sha256": hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
    }
    if isinstance(metadata, dict):
        record.update(_sanitize_novel_diagnostic_value(metadata))
    record["raw_output_path"] = text_path
    try:
        with _NOVEL_DIAGNOSTIC_LOCK:
            os.makedirs(NOVEL_RAW_OUTPUT_DIR, exist_ok=True)
            temp_text_path = f"{text_path}.{os.getpid()}.{threading.get_ident()}.tmp"
            try:
                with open(temp_text_path, "w", encoding="utf-8") as handle:
                    handle.write(text)
                    handle.flush()
                os.replace(temp_text_path, text_path)
            finally:
                if os.path.exists(temp_text_path):
                    os.remove(temp_text_path)
            _write_novel_diagnostic_json(metadata_path, record)
            _prune_novel_raw_output_slots()
        return text_path
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
    loaded_profiles = []
    for path in (NOVEL_BUILTIN_STYLE_LIBRARY_FILE, NOVEL_STYLE_LIBRARY_FILE):
        for record in _load_style_profile_library_file(path):
            loaded_profiles.append(record)

    # A V4 archive supersedes any stale duplicate with the same source sample.
    v4_by_reference = {
        item.get("reference_hash"): item
        for item in loaded_profiles
        if _is_v4_style_profile_record(item) and item.get("reference_hash")
    }
    profiles = {}
    for record in loaded_profiles:
        reference_hash = record.get("reference_hash")
        v4_record = v4_by_reference.get(reference_hash)
        if v4_record and not _is_v4_style_profile_record(record):
            continue
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
        reference_record = next(
            (
                item for item in profiles.values()
                if item.get("reference_hash") == reference_hash
            ),
            {},
        )
        # Keep a shipped V4 archive authoritative instead of downgrading it
        # when a stale duplicate is found during startup.
        if reference_record and _is_v4_style_profile_record(reference_record) and not _is_v4_style_profile_record({"cache_entry": entry}):
            continue
        if reference_record and _is_v4_style_profile_record(reference_record):
            selected_record = reference_record
        selected_matches_reference = (
            isinstance(selected_record, dict)
            and selected_record.get("reference_hash") == reference_hash
        )
        record = _stored_style_profile_record({
            "id": selected_record.get("id", "") if selected_matches_reference else "",
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


def _normalized_character_style_record(item, style_id=""):
    """Keep only reusable protagonist personality and voice fields."""
    item = item if isinstance(item, dict) else {}
    personality = str(item.get("personality", "") or "").strip()
    voice = str(item.get("voice", "") or "").strip()
    if not personality and not voice:
        return None
    record_id = str(style_id or item.get("id", "") or "").strip()
    if not record_id:
        record_id = uuid.uuid4().hex
    return {
        "id": record_id,
        "name": str(item.get("name", "") or "").strip() or "未命名人物风格",
        "personality": personality,
        "voice": voice,
        "source_project": str(item.get("source_project", "") or "").strip(),
        "source_character": str(item.get("source_character", "") or "").strip(),
        "created_at": str(item.get("created_at", "") or "").strip() or now_str(),
        "updated_at": str(item.get("updated_at", "") or "").strip() or now_str(),
    }


def load_character_style_library():
    raw = load_json_file(NOVEL_CHARACTER_STYLE_LIBRARY_FILE, {})
    items = raw.get("styles", []) if isinstance(raw, dict) else []
    styles = []
    seen = set()
    for item in items if isinstance(items, list) else []:
        record = _normalized_character_style_record(item)
        if not record or record["id"] in seen:
            continue
        seen.add(record["id"])
        styles.append(record)
    styles.sort(key=lambda item: (item.get("name", ""), item.get("id", "")))
    return styles


def save_character_style_library(styles):
    normalized = []
    seen = set()
    for item in styles if isinstance(styles, list) else []:
        record = _normalized_character_style_record(item)
        if not record or record["id"] in seen:
            continue
        seen.add(record["id"])
        normalized.append(record)
    normalized.sort(key=lambda item: (item.get("name", ""), item.get("id", "")))
    _save_novel_json_strict(
        NOVEL_CHARACTER_STYLE_LIBRARY_FILE,
        {"version": 1, "styles": normalized},
    )
    return normalized


def upsert_character_style(
    personality,
    voice,
    name="",
    source_project="",
    source_character="",
    style_id="",
):
    record = _normalized_character_style_record({
        "id": style_id,
        "name": name,
        "personality": personality,
        "voice": voice,
        "source_project": source_project,
        "source_character": source_character,
    })
    if not record:
        return ""
    styles = load_character_style_library()
    existing = next((item for item in styles if item.get("id") == record["id"]), None)
    if existing:
        record["created_at"] = existing.get("created_at", "") or record["created_at"]
        styles = [record if item.get("id") == record["id"] else item for item in styles]
    else:
        styles.append(record)
    save_character_style_library(styles)
    return record["id"]


def remove_character_style(style_id):
    style_id = str(style_id or "").strip()
    if not style_id:
        return False
    styles = load_character_style_library()
    remaining = [item for item in styles if item.get("id") != style_id]
    if len(remaining) == len(styles):
        return False
    save_character_style_library(remaining)
    return True


def safe_project_timestamp():
    return now_str().replace(":", "").replace("-", "").replace(" ", "_")


def _project_timestamp_from_mtime(mtime):
    try:
        value = float(mtime or 0)
    except (TypeError, ValueError):
        value = 0.0
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value)) if value else ""


def _project_file_created_at(path, fallback_mtime=0):
    try:
        stat = os.stat(path)
        birthtime = float(getattr(stat, "st_birthtime", 0) or 0)
    except Exception:
        birthtime = 0.0
    return _project_timestamp_from_mtime(birthtime or fallback_mtime)


def _project_created_at_from_disk(path, mtime=0, raw=None):
    if not isinstance(raw, dict):
        raw = load_json_file(path, {})
    if isinstance(raw, dict):
        created_at = str(raw.get("created_at", "") or "").strip()
        if created_at:
            return created_at
    return _project_file_created_at(path, mtime)


def _project_sort_key(created_at, filename=""):
    # All persisted timestamps use the sortable ``YYYY-MM-DD HH:MM:SS`` form.
    # The filename tie-breaker keeps projects deterministic when timestamps
    # were created in the same second or came from legacy files.
    return str(created_at or ""), str(filename or "")


def list_project_files(include_empty=False):
    if not os.path.exists(NOVEL_DIR):
        return []
    cache = _load_project_summary_cache()
    out = []
    for name in os.listdir(NOVEL_DIR):
        if not name.lower().endswith(".json"):
            continue
        path = os.path.join(NOVEL_DIR, name)
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0
        cached = cache.get(os.path.abspath(path), {}) if isinstance(cache, dict) else {}
        cached_record = cached.get("record", {}) if isinstance(cached, dict) else {}
        created_at = (
            str(cached_record.get("created_at", "") or "").strip()
            if isinstance(cached_record, dict) else ""
        ) or _project_file_created_at(path, mtime)
        out.append((mtime, name, path, created_at))
    out.sort(key=lambda item: _project_sort_key(item[3], item[1]), reverse=True)
    return [(mtime, name, path) for mtime, name, path, _created_at in out]


def list_project_records(include_empty=False):
    records = []
    for mtime, filename, path in list_project_files(include_empty=include_empty):
        raw = load_json_file(path, {})
        if isinstance(raw, dict) and raw.get("auto_saved_reason") and not include_empty:
            continue
        data = _normalize_project(raw)
        created_at = str(data.get("created_at", "") or "").strip()
        if not created_at:
            created_at = _project_created_at_from_disk(path, mtime, raw)
        records.append(
            {
                "mtime": mtime,
                "filename": filename,
                "path": path,
                "created_at": created_at,
                "data": data,
            }
        )
    records.sort(
        key=lambda item: _project_sort_key(item.get("created_at"), item.get("filename")),
        reverse=True,
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
    if not isinstance(cache, dict) or cache.get("version") != 3:
        return {}
    entries = cache.get("entries", {})
    return entries if isinstance(entries, dict) else {}


def _save_project_summary_cache(entries):
    try:
        _save_novel_json_strict(_project_summary_cache_path(), {
            "version": 3,
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


def _build_project_summary_record(mtime, filename, path, data, created_at=""):
    data = data if isinstance(data, dict) else {}
    meta = data.get("meta", {}) if isinstance(data.get("meta"), dict) else {}
    chapters = data.get("chapters", []) if isinstance(data.get("chapters"), list) else []
    body_words = 0
    for chap in chapters:
        if not isinstance(chap, dict):
            continue
        body_words += _body_display_len(chap.get("text", ""))
    auto_saved_reason = str(data.get("auto_saved_reason", "") or "").strip()
    created_at = (
        str(data.get("created_at", "") or "").strip()
        or str(created_at or "").strip()
        or _project_file_created_at(path, mtime)
    )
    return {
        "mtime": mtime,
        "filename": filename,
        "path": path,
        "created_at": created_at,
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
            cached_record = cached.get("record", {}) if isinstance(cached, dict) else {}
            record = _build_project_summary_record(
                mtime,
                filename,
                path,
                raw if isinstance(raw, dict) else {},
                created_at=(
                    cached_record.get("created_at", "")
                    if isinstance(cached_record, dict) else ""
                ) or _project_created_at_from_disk(path, mtime, raw),
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
    records.sort(
        key=lambda item: _project_sort_key(item.get("created_at"), item.get("filename")),
        reverse=True,
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
    data = deepcopy(data) if isinstance(data, dict) else {}
    existing_created_at = str(data.get("created_at", "") or "").strip()
    if not existing_created_at and os.path.exists(path):
        existing = load_json_file(path, {})
        if isinstance(existing, dict):
            existing_created_at = str(existing.get("created_at", "") or "").strip()
        if not existing_created_at:
            try:
                existing_created_at = _project_file_created_at(
                    path, os.path.getmtime(path)
                )
            except Exception:
                existing_created_at = ""
    data["created_at"] = (
        str(data.get("created_at", "") or "").strip()
        or existing_created_at
        or now_str()
    )
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
