"""Build a semantic V4 archive from an existing permanent style profile.

The archive keeps original vocabulary, language voice and conditional narrative
techniques separate.  Each vocabulary card is checked against the source text
before it is persisted, so a partial model response can be retried in isolation.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpt_desktop.core import get_provider, load_config, now_str
from gpt_desktop.novel_storage import get_style_profile, upsert_style_profile
from gpt_desktop.novel_utils import (
    STYLE_SEMANTIC_ARCHIVE_SCHEMA,
    STYLE_SEMANTIC_ARCHIVE_VERSION,
    _build_style_runtime_voice_pack_context,
    _build_style_semantic_vocabulary_context,
    _build_style_technique_cards_context,
    _build_style_voice_cards_context,
    _normalize_native_vocabulary_cards,
    _normalize_semantic_style_archive,
    _parse_native_vocabulary_cards_result,
    _parse_style_technique_cards_result,
    _parse_style_voice_cards_result,
    _style_native_vocabulary_seed_terms,
)
from gpt_desktop.workers import NovelWritingWorker


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "api_test_outputs"
DEFAULT_SOURCE_PROFILE_ID = "a9e729167b46ea213f929c9165a98067c596579063344a90ce905fdd040a4bf3"
DEFAULT_PROFILE_NAME = "女频、穿越现代言情、沙雕搞笑 V4"


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def run_action(provider, model, action, context, calls, label):
    last_error = ""
    retry_delays = (12, 30, 60, 120)
    for attempt in range(len(retry_delays) + 1):
        result = {}
        worker = NovelWritingWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            action,
            context,
            provider.get("proxy_url", ""),
            provider.get("proxy_mode", "提交和下载" if provider.get("proxy_url") else "不使用代理"),
        )
        worker.progress.connect(lambda message: print(f"[{action}] {message}", flush=True))
        worker.result_ready.connect(
            lambda returned_action, content: result.update(action=returned_action, content=content)
        )
        worker.failed.connect(lambda error: result.update(error=error))
        started = time.perf_counter()
        worker.run()
        elapsed = round(time.perf_counter() - started, 2)
        if result.get("error"):
            last_error = str(result["error"])
            if attempt < len(retry_delays):
                delay = retry_delays[attempt]
                print(
                    f"[{action}] 请求失败，{delay}秒后重试 "
                    f"{attempt + 2}/{len(retry_delays) + 1}：{last_error[:180]}",
                    flush=True,
                )
                time.sleep(delay)
                continue
            raise RuntimeError(f"{action}: {last_error}")
        content = str(result.get("content", "") or "").strip()
        if content:
            calls.append({
                "action": action,
                "label": label,
                "seconds": elapsed,
                "chars": len(content),
            })
            print(
                f"[{len(calls)}] {action} {label} 完成，{elapsed:.2f}秒，{len(content)}字",
                flush=True,
            )
            return content
        last_error = "empty response"
    raise RuntimeError(f"{action}: {last_error}")


def chunked(values, size):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def vocabulary_batch_is_complete(cards, terms):
    normalized = _normalize_native_vocabulary_cards(cards, required_terms=terms)
    return [item.get("term", "") for item in normalized] == list(terms)


def main():
    parser = argparse.ArgumentParser(description="升级永久小说文风档案至语义声纹 V4")
    parser.add_argument("--source-profile-id", default=DEFAULT_SOURCE_PROFILE_ID)
    parser.add_argument("--name", default=DEFAULT_PROFILE_NAME)
    parser.add_argument("--batch-size", type=int, default=14)
    parser.add_argument("--provider-id", default="")
    parser.add_argument("--model", default="")
    args = parser.parse_args()

    source_profile_id = str(args.source_profile_id or "").strip().lower()
    source_profile = get_style_profile(source_profile_id)
    if not source_profile:
        raise RuntimeError(f"找不到原始永久文风档案：{source_profile_id}")
    old_entry = source_profile.get("cache_entry", {})
    style_reference = str(source_profile.get("style_reference", "") or "").strip()
    profile_text = str(old_entry.get("profile", "") or "").strip()
    if len(style_reference) < 1000 or not profile_text:
        raise RuntimeError("原始文风档案缺少可用样本或文风画像。")

    batch_size = max(8, min(21, int(args.batch_size or 14)))
    terms = _style_native_vocabulary_seed_terms(profile_text, style_reference, limit=84)
    if len(terms) != 84:
        raise RuntimeError(f"原始档案可提取的固定候选词不足84项，当前仅{len(terms)}项。")
    reference_hash = hashlib.sha256(style_reference.encode("utf-8")).hexdigest()
    archive_id = hashlib.sha256(
        f"{reference_hash}:{STYLE_SEMANTIC_ARCHIVE_SCHEMA}".encode("utf-8")
    ).hexdigest()

    config = load_config()
    novel_config = config.get("novel", {})
    provider_id = str(args.provider_id or novel_config.get("provider_id") or "").strip()
    provider = get_provider(config, provider_id)
    model = str(args.model or novel_config.get("model", "") or "").strip()
    if not provider or not model:
        raise RuntimeError("小说AI厂商或模型未配置。")

    checkpoint_path = OUTPUT_DIR / f"style_archive_v4_{archive_id[:12]}_checkpoint.json"
    report_path = OUTPUT_DIR / f"style_archive_v4_{archive_id[:12]}_report.json"
    checkpoint = {}
    if checkpoint_path.exists():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except Exception:
            checkpoint = {}
    entry = checkpoint.get("cache_entry", {}) if isinstance(checkpoint, dict) else {}
    if not isinstance(entry, dict) or str(entry.get("archive_id", "") or "") != archive_id:
        entry = {}
    if not entry:
        entry = {
            "version": STYLE_SEMANTIC_ARCHIVE_VERSION,
            "status": "building",
            "archive_id": archive_id,
            "style_archive_schema": STYLE_SEMANTIC_ARCHIVE_SCHEMA,
            "semantic_archive_version": STYLE_SEMANTIC_ARCHIVE_VERSION,
            "profile": "",
            "runtime_voice_pack": "",
            "native_vocabulary_batches": [
                {"terms": list(batch), "cards": []}
                for batch in chunked(terms, batch_size)
            ],
            "native_vocabulary_cards": [],
            "voice_cards": [],
            "technique_cards": [],
        }
    calls = checkpoint.get("calls", []) if isinstance(checkpoint, dict) else []
    if not isinstance(calls, list):
        calls = []

    def persist():
        entry["cached_at"] = now_str()
        entry["model"] = model
        atomic_write_json(checkpoint_path, {
            "name": str(args.name or DEFAULT_PROFILE_NAME).strip(),
            "source_profile_id": source_profile_id,
            "source_profile_name": str(source_profile.get("name", "") or "").strip(),
            "reference_hash": reference_hash,
            "archive_id": archive_id,
            "style_chars": len(style_reference),
            "cache_entry": entry,
            "calls": calls,
            "updated_at": now_str(),
        })

    batches = entry.get("native_vocabulary_batches", [])
    expected_batches = list(chunked(terms, batch_size))
    if not isinstance(batches, list) or [item.get("terms", []) for item in batches if isinstance(item, dict)] != expected_batches:
        entry["native_vocabulary_batches"] = [
            {"terms": list(batch), "cards": []}
            for batch in expected_batches
        ]
        batches = entry["native_vocabulary_batches"]
        persist()

    print(
        f"开始升级文风档案：{source_profile.get('name', '')} -> {args.name}\n"
        f"样本 {len(style_reference)} 字，固定原生词 84 项，分 {len(batches)} 批。"
        f"使用：{provider.get('name', '')} / {model}",
        flush=True,
    )

    for index, batch in enumerate(batches, 1):
        batch_terms = [str(term or "").strip() for term in batch.get("terms", []) if str(term or "").strip()]
        cards = _normalize_native_vocabulary_cards(
            batch.get("cards", []),
            style_reference,
            required_terms=batch_terms,
        )
        if vocabulary_batch_is_complete(cards, batch_terms):
            batch["cards"] = cards
            continue
        for semantic_attempt in range(1, 4):
            raw = run_action(
                provider,
                model,
                "style_semantic_vocabulary",
                _build_style_semantic_vocabulary_context(style_reference, batch_terms),
                calls,
                f"词语义卡 {index}/{len(batches)}，第{semantic_attempt}次",
            )
            parsed = _parse_native_vocabulary_cards_result(
                raw,
                style_reference,
                required_terms=batch_terms,
            )
            if vocabulary_batch_is_complete(parsed, batch_terms):
                batch["cards"] = parsed
                batch.pop("last_invalid_response", None)
                persist()
                break
            present = {item.get("term", "") for item in parsed}
            missing = [term for term in batch_terms if term not in present]
            batch["last_invalid_response"] = raw
            batch["last_missing_terms"] = missing
            persist()
            print(
                f"[style_semantic_vocabulary] 第{index}批有词卡无效或缺失：{'、'.join(missing)}",
                flush=True,
            )
        else:
            raise RuntimeError(f"第{index}批词语义卡连续三次未能完整通过原文证据校验。")

    all_cards = []
    for batch in batches:
        all_cards.extend(batch.get("cards", []) if isinstance(batch, dict) else [])
    all_cards = _normalize_native_vocabulary_cards(
        all_cards,
        style_reference,
        required_terms=terms,
    )
    if not vocabulary_batch_is_complete(all_cards, terms):
        raise RuntimeError("词语义卡汇总后未覆盖完整84项固定候选词。")
    entry["native_vocabulary_cards"] = all_cards
    persist()

    if not entry.get("voice_cards"):
        for voice_attempt in range(1, 4):
            raw = run_action(
                provider,
                model,
                "style_voice_cards",
                _build_style_voice_cards_context(style_reference),
                calls,
                f"人物与叙述声纹，第{voice_attempt}次",
            )
            cards = _parse_style_voice_cards_result(raw, style_reference)
            # A style sample can genuinely contain only a narrator voice plus a
            # small number of distinct dialogue voices.  Do not invent extra
            # speaker types merely to satisfy a fixed cardinality: fabricated
            # cards become always-on templates at writing time.  Three evidenced
            # cards still cover narration, primary dialogue and a contrasting
            # response pattern, while preserving the semantic archive contract.
            if len(cards) >= 3:
                entry["voice_cards"] = cards
                entry.pop("last_invalid_voice_cards_response", None)
                persist()
                break
            entry["last_invalid_voice_cards_response"] = raw
            entry["last_invalid_voice_cards_count"] = len(cards)
            persist()
            print(
                f"[style_voice_cards] 声纹卡有效数量不足：{len(cards)}，准备重试 {voice_attempt + 1}/3",
                flush=True,
            )
        else:
            raise RuntimeError(
                f"人物与叙述声纹卡连续三次有效数量不足："
                f"{entry.get('last_invalid_voice_cards_count', 0)}"
            )

    if not entry.get("technique_cards"):
        for technique_attempt in range(1, 4):
            raw = run_action(
                provider,
                model,
                "style_technique_cards",
                _build_style_technique_cards_context(style_reference),
                calls,
                f"条件性叙事技法，第{technique_attempt}次",
            )
            cards = _parse_style_technique_cards_result(raw, style_reference)
            if len(cards) >= 5:
                entry["technique_cards"] = cards
                entry.pop("last_invalid_technique_cards_response", None)
                persist()
                break
            entry["last_invalid_technique_cards_response"] = raw
            entry["last_invalid_technique_cards_count"] = len(cards)
            persist()
            print(
                f"[style_technique_cards] 技法卡有效数量不足：{len(cards)}，准备重试 {technique_attempt + 1}/3",
                flush=True,
            )
        else:
            raise RuntimeError(
                f"条件性叙事技法卡连续三次有效数量不足："
                f"{entry.get('last_invalid_technique_cards_count', 0)}"
            )

    if not str(entry.get("runtime_voice_pack", "") or "").strip():
        entry["runtime_voice_pack"] = run_action(
            provider,
            model,
            "style_runtime_voice_pack",
            _build_style_runtime_voice_pack_context(
                entry.get("voice_cards", []),
                entry.get("technique_cards", []),
            ),
            calls,
            "V4运行时总则",
        )
        persist()

    entry["profile"] = str(entry.get("runtime_voice_pack", "") or "").strip()
    entry["status"] = "complete"
    entry.pop("error", None)
    semantic_archive = _normalize_semantic_style_archive(entry, style_reference)
    if not semantic_archive:
        raise RuntimeError("V4文风档案结构校验失败，未写入永久文风列表。")
    persist()

    profile_id = upsert_style_profile(
        style_reference,
        entry,
        name=str(args.name or DEFAULT_PROFILE_NAME).strip(),
        source_project=str(source_profile.get("source_project", "") or ""),
        profile_id=archive_id,
    )
    if profile_id != archive_id:
        raise RuntimeError("V4文风档案生成成功，但未能以独立档案ID写入永久列表。")

    report = {
        "name": str(args.name or DEFAULT_PROFILE_NAME).strip(),
        "id": profile_id,
        "source_profile_id": source_profile_id,
        "provider": provider.get("name", ""),
        "model": model,
        "style_chars": len(style_reference),
        "vocabulary_cards": len(all_cards),
        "voice_cards": len(entry.get("voice_cards", [])),
        "technique_cards": len(entry.get("technique_cards", [])),
        "runtime_voice_pack_chars": len(entry.get("runtime_voice_pack", "")),
        "calls": calls,
        "total_calls": len(calls),
        "total_seconds": round(sum(float(item.get("seconds", 0) or 0) for item in calls), 2),
        "finished_at": now_str(),
    }
    atomic_write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
