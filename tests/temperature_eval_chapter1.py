#!/usr/bin/env python3
"""Run a controlled chapter-one temperature comparison against the configured provider.

The script deliberately reads the clean framework backup but never writes it. Each
request uses the same context, system prompt, model, reasoning level and token
budget; only temperature changes.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from gpt_desktop.novel_utils import (
    _build_chapter_ai_context,
    _build_style_execution_context,
    _compose_style_profile,
    _normalize_semantic_style_archive,
)
from gpt_desktop.workers import NovelWritingWorker


CLEAN_PROJECT = WORKSPACE / ".codex_backups" / "realm_setting_fix_20260831" / "project.before.json"
CONFIG_PATH = Path.home() / ".gpt_desktop_app" / "config.json"
STYLE_LIBRARY = WORKSPACE / "gpt_desktop" / "resources" / "novel" / "default_style_profiles.json"
STYLE_HISTORY = Path.home() / ".gpt_desktop_app" / "history" / "novel_style_profiles.json"
OUTPUT_ROOT = WORKSPACE / "temperature_tests"
TEMPERATURES = (0.55, 0.8, 1.0, 1.2, 1.5, 1.8)
PROVIDER_NAME = "api.tcvps.cn-gpt"
MODEL = "gpt-5.6-terra"
STYLE_NAME = "男频、穿越、都市高武 V4"
MAX_ATTEMPTS = 5
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 524}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def load_provider() -> tuple[str, str, str]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for provider in config.get("providers", []):
        if provider.get("name") == PROVIDER_NAME:
            key = str(provider.get("api_key", "") or "").strip()
            base_url = str(provider.get("base_url", "") or "").rstrip("/")
            if not key or not base_url:
                raise RuntimeError(f"Provider {PROVIDER_NAME!r} is missing credentials or URL")
            return str(provider.get("id", "")), base_url, key
    raise RuntimeError(f"Provider not found: {PROVIDER_NAME}")


def load_male_style_archive() -> dict[str, Any]:
    defaults = json.loads(STYLE_LIBRARY.read_text(encoding="utf-8"))
    default = next(
        (item for item in defaults.get("profiles", []) if item.get("name") == "男频、穿越、都市高武"),
        None,
    )
    history = json.loads(STYLE_HISTORY.read_text(encoding="utf-8"))
    archive = next(
        (item for item in history.get("profiles", []) if item.get("name") == STYLE_NAME),
        None,
    )
    if not isinstance(default, dict) or not isinstance(archive, dict):
        raise RuntimeError(f"Style archive not found: {STYLE_NAME}")
    reference = str(default.get("style_reference", "") or "").strip()
    cache_entry = archive.get("cache_entry", {})
    if not reference or not isinstance(cache_entry, dict):
        raise RuntimeError("Male style archive is incomplete")
    return {
        "id": str(archive.get("id", "") or "").strip().lower(),
        "name": STYLE_NAME,
        "reference": reference,
        "reference_hash": str(default.get("reference_hash", "") or "").strip().lower(),
        "cache_entry": cache_entry,
    }


def build_test_project(style_archive: dict[str, Any]) -> dict[str, Any]:
    project = json.loads(CLEAN_PROJECT.read_text(encoding="utf-8"))
    imported = project.get("imported_chapter_plan_reference", {})
    source_chapters = imported.get("chapters", []) if isinstance(imported, dict) else []
    source = source_chapters[0] if source_chapters else {}
    # Keep the source framework outline and make the already-defined first
    # target visible to the prose context through the chapter's linked cards.
    chapter = {
        "id": "temperature-test-chapter-1",
        "index": 0,
        "title": str(source.get("title") or "穿越觉醒！超级无敌背刺系统"),
        "draft_words": str(source.get("target_words") or "5000"),
        "outline": str(source.get("outline") or (
            "林砚穿越青玄宗成外门弟子，绑定背刺系统，系统选中绑定废灵根苏轻棠作为背刺执行者，"
            "成功背刺苏轻棠涨修为，当即锁定首个目标。"
        )),
        "linked_characters": ["林砚", "苏轻棠", "楚峰"],
        "status": "大纲",
        "text": "",
        "summary": "",
        "key_facts": "",
        "memory_selection": {},
    }
    project["chapters"] = [chapter]
    # Make this a clean, first-chapter run even if a future backup gains
    # transient runtime fields.
    # This mirrors NovelWritingTab._ai_project_snapshot after selecting the
    # built-in male V4 profile: the project itself stays clean, while the AI
    # snapshot receives the library sample and its cached archive entry.
    project["style_profile_id"] = style_archive["id"]
    project["style_reference"] = style_archive["reference"]
    project["style_profile_cache"] = {
        style_archive["reference_hash"]: style_archive["cache_entry"]
    }
    return project


def build_prompt(
    project: dict[str, Any], style_archive: dict[str, Any]
) -> tuple[str, str, int]:
    raw_context = _build_chapter_ai_context(project, 0, "draft")
    cache_entry = style_archive["cache_entry"]
    persisted_profile = str(cache_entry.get("profile", "") or "").strip()
    combined_sheet = str(cache_entry.get("combined_sheet", "") or persisted_profile).strip()
    persona = str(cache_entry.get("persona", "") or "").strip()
    profile = _compose_style_profile(combined_sheet, persona) or persisted_profile
    semantic_archive = _normalize_semantic_style_archive(
        cache_entry, style_archive["reference"]
    )
    vocabulary_profile = _compose_style_profile(combined_sheet, persona) or profile
    # This is the same style-locked draft assembly used by the writing tab.
    # The helper decides which archive material is eligible for the draft;
    # do not paste a second, hand-written style prompt on top of it.
    context = _build_style_execution_context(
        raw_context,
        profile_text=profile,
        style_cards=cache_entry.get("style_cards", []),
        style_reference=style_archive["reference"],
        project=project,
        chapter_index=0,
        vocabulary_profile_text=vocabulary_profile,
        semantic_archive=semantic_archive,
    )
    worker = NovelWritingWorker("https://api.tcvps.cn", "redacted", MODEL, "draft", context)
    try:
        system_prompt = worker._action_prompt()
        max_tokens = worker._max_tokens_for_request() or 15000
    finally:
        worker._close_network_handles()
    return system_prompt, context, max_tokens


def extract_stream_text(response: requests.Response) -> tuple[str, str, bool]:
    chunks: list[str] = []
    finish_reason = ""
    done = False
    # Keep bytes until JSON decoding so the gateway's UTF-8 content is not
    # guessed from an absent Content-Type charset.
    for raw_line in response.iter_lines(decode_unicode=False):
        if raw_line is None:
            continue
        line = bytes(raw_line).strip()
        if not line or not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if data == b"[DONE]":
            done = True
            continue
        try:
            item = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = item.get("choices") or []
        if not choices:
            continue
        choice = choices[0] if isinstance(choices[0], dict) else {}
        finish_reason = str(choice.get("finish_reason") or finish_reason)
        delta = choice.get("delta") or {}
        content = delta.get("content") if isinstance(delta, dict) else None
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    return "".join(chunks), finish_reason, done


def extract_non_stream_text(response: requests.Response) -> tuple[str, str, bool]:
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        return "", "", False
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    content = message.get("content", "")
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    return str(content or ""), str(choice.get("finish_reason") or ""), True


def clean_body(text: str) -> str:
    text = str(text or "").strip()
    # Some compatible gateways omit a charset on SSE. Requests can then
    # expose UTF-8 bytes as Latin-1 characters; repair that representation
    # before storing or counting the prose.
    if not any("\u3400" <= char <= "\u9fff" for char in text):
        try:
            repaired = text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            repaired = text
        if any("\u3400" <= char <= "\u9fff" for char in repaired):
            text = repaired
    # The app's style workflow uses these markers, but the no-style draft path
    # generally does not. Remove them only when a provider returns them anyway.
    text = re.sub(r"^```(?:text|markdown)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"^【正文开始】\s*", "", text)
    text = re.sub(r"\s*【正文结束】$", "", text)
    text = re.sub(r"^<NOVEL_PROSE_START>\s*", "", text)
    text = re.sub(r"\s*<NOVEL_PROSE_END>$", "", text)
    return text.strip()


def request_one(
    temperature: float,
    *,
    base_url: str,
    api_key: str,
    system_prompt: str,
    context: str,
    max_tokens: int,
) -> dict[str, Any]:
    endpoint = f"{base_url}/v1/chat/completions"
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ],
        "temperature": temperature,
        "stream": True,
        "max_tokens": max_tokens,
        "reasoning_effort": "max",
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    attempts: list[dict[str, Any]] = []
    started = time.perf_counter()
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempt_started = time.perf_counter()
        response = None
        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                stream=True,
                timeout=(20, 300),
            )
            status = int(response.status_code)
            if status >= 400:
                error_preview = response.text[:1000]
                retryable = status in RETRYABLE_STATUS
                attempts.append({
                    "attempt": attempt,
                    "status": status,
                    "elapsed_seconds": round(time.perf_counter() - attempt_started, 3),
                    "retryable": retryable,
                    "error": error_preview,
                })
                last_error = f"HTTP {status}: {error_preview}"
                if not retryable or attempt >= MAX_ATTEMPTS:
                    break
            else:
                if response.headers.get("content-type", "").lower().startswith("application/json"):
                    text, finish_reason, done = extract_non_stream_text(response)
                else:
                    text, finish_reason, done = extract_stream_text(response)
                body = clean_body(text)
                attempts.append({
                    "attempt": attempt,
                    "status": status,
                    "elapsed_seconds": round(time.perf_counter() - attempt_started, 3),
                    "chars": len(body),
                    "finish_reason": finish_reason,
                    "done": done,
                    "empty": not bool(body),
                })
                # A gateway can close an SSE response after emitting a
                # partial body without sending either [DONE] or a finish
                # reason. Treat that as an upstream truncation and retry it
                # instead of accepting a cut-off chapter as a valid sample.
                complete = bool(done or finish_reason)
                if body and complete:
                    return {
                        "temperature": temperature,
                        "ok": True,
                        "attempts": attempts,
                        "retry_count": attempt - 1,
                        "elapsed_seconds": round(time.perf_counter() - started, 3),
                        "status": status,
                        "finish_reason": finish_reason,
                        "done": done,
                        "body": body,
                        "body_chars": len(body),
                        "body_sha256": sha256_text(body),
                    }
                last_error = "incomplete stream" if body else "empty response"
                if attempt >= MAX_ATTEMPTS:
                    break
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            attempts.append({
                "attempt": attempt,
                "status": None,
                "elapsed_seconds": round(time.perf_counter() - attempt_started, 3),
                "retryable": True,
                "error": last_error[:1000],
            })
            if attempt >= MAX_ATTEMPTS:
                break
        finally:
            if response is not None:
                response.close()
        time.sleep(min(30, 2 ** (attempt - 1)))
    return {
        "temperature": temperature,
        "ok": False,
        "attempts": attempts,
        "retry_count": max(0, len(attempts) - 1),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "error": last_error,
    }


def main() -> None:
    provider_id, base_url, api_key = load_provider()
    style_archive = load_male_style_archive()
    project = build_test_project(style_archive)
    system_prompt, context, max_tokens = build_prompt(project, style_archive)
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_ROOT / f"chapter1_{run_stamp}"
    output_dir.mkdir(parents=True, exist_ok=False)

    manifest = {
        "created_at": utc_now(),
        "provider_id": provider_id,
        "provider_name": PROVIDER_NAME,
        "base_url": base_url,
        "model": MODEL,
        "style_archive_name": style_archive["name"],
        "style_archive_id": style_archive["id"],
        "style_reference_chars": len(style_archive["reference"]),
        "style_reference_sha256": sha256_text(style_archive["reference"]),
        "style_archive_cache_version": style_archive["cache_entry"].get("version"),
        "style_archive_schema": style_archive["cache_entry"].get("style_archive_schema", ""),
        "style_archive_semantic_version": style_archive["cache_entry"].get("semantic_archive_version", 0),
        "style_archive_component_chars": {
            "runtime_voice_pack": len(str(style_archive["cache_entry"].get("runtime_voice_pack", "") or "")),
            "native_vocabulary_cards": len(style_archive["cache_entry"].get("native_vocabulary_cards", []) or []),
            "voice_cards": len(style_archive["cache_entry"].get("voice_cards", []) or []),
            "technique_cards": len(style_archive["cache_entry"].get("technique_cards", []) or []),
        },
        "temperatures": list(TEMPERATURES),
        "reasoning_effort": "max",
        "max_tokens": max_tokens,
        "retry_policy": {
            "max_attempts": MAX_ATTEMPTS,
            "retryable_status": sorted(RETRYABLE_STATUS),
            "empty_response_retry": True,
        },
        "source_project": str(CLEAN_PROJECT),
        "chapter_title": project["chapters"][0]["title"],
        "chapter_outline": project["chapters"][0]["outline"],
        "linked_characters": project["chapters"][0]["linked_characters"],
        "system_prompt_chars": len(system_prompt),
        "system_prompt_sha256": sha256_text(system_prompt),
        "context_chars": len(context),
        "context_sha256": sha256_text(context),
        "api_key_saved": False,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "system_prompt.txt").write_text(system_prompt, encoding="utf-8")
    (output_dir / "context.txt").write_text(context, encoding="utf-8")

    print(f"TEST_DIR={output_dir}", flush=True)
    print(f"CONTEXT_CHARS={len(context)} SYSTEM_CHARS={len(system_prompt)} MAX_TOKENS={max_tokens}", flush=True)
    print("STARTING=0.55,0.8,1.0,1.2,1.5,1.8", flush=True)
    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(TEMPERATURES)) as pool:
        future_map = {
            pool.submit(
                request_one,
                temperature,
                base_url=base_url,
                api_key=api_key,
                system_prompt=system_prompt,
                context=context,
                max_tokens=max_tokens,
            ): temperature
            for temperature in TEMPERATURES
        }
        for future in concurrent.futures.as_completed(future_map):
            temperature = future_map[future]
            result = future.result()
            results[f"{temperature:.2f}"] = {k: v for k, v in result.items() if k != "body"}
            if result.get("ok"):
                (output_dir / f"temperature_{temperature:.2f}.txt").write_text(
                    result["body"], encoding="utf-8"
                )
                print(
                    f"DONE temperature={temperature:.2f} chars={result['body_chars']} "
                    f"attempts={len(result['attempts'])} seconds={result['elapsed_seconds']}",
                    flush=True,
                )
            else:
                print(
                    f"FAIL temperature={temperature:.2f} attempts={len(result['attempts'])} "
                    f"error={result.get('error', '')[:240]}",
                    flush=True,
                )

    summary = {
        "completed_at": utc_now(),
        "results": dict(sorted(results.items(), key=lambda item: float(item[0]))),
    }
    (output_dir / "results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"RESULTS={output_dir / 'results.json'}", flush=True)


if __name__ == "__main__":
    main()
