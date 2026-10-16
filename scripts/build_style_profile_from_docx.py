import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from docx import Document

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpt_desktop.core import get_provider, load_config, now_str
from gpt_desktop.novel_storage import get_style_profile, upsert_style_profile
from gpt_desktop.novel_utils import (
    STYLE_CARD_CACHE_VERSION,
    STYLE_SHEET_CACHE_VERSION,
    _build_style_baseline_context,
    _build_style_cards_context,
    _build_style_persona_context,
    _build_style_profile_units,
    _build_style_sheet_context,
    _build_style_sheet_merge_context,
    _compose_style_profile,
    _parse_style_cards_result,
)
from gpt_desktop.workers import NovelWritingWorker


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "api_test_outputs"


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def read_docx_text(path):
    paragraphs = [paragraph.text.strip() for paragraph in Document(str(path)).paragraphs]
    return "\n".join(value for value in paragraphs if value).strip()


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
                    f"[{action}] 请求失败，{delay}秒后自动重试 "
                    f"{attempt + 2}/{len(retry_delays) + 1}：{last_error[:160]}",
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


def main():
    parser = argparse.ArgumentParser(description="从Word正文建立永久小说文风档案")
    parser.add_argument("docx", nargs="?")
    parser.add_argument("--profile-id", default="")
    parser.add_argument("--name", default="")
    args = parser.parse_args()

    profile_id = str(args.profile_id or "").strip().lower()
    source_project = ""
    if profile_id:
        existing_profile = get_style_profile(profile_id)
        if not existing_profile:
            raise RuntimeError(f"找不到永久文风档案：{profile_id}")
        style_reference = str(existing_profile.get("style_reference", "") or "").strip()
        profile_name = str(args.name or existing_profile.get("name", "") or "").strip()
        source_project = str(existing_profile.get("source_project", "") or "").strip()
        source_path = Path(source_project).expanduser() if source_project else None
        source_label = source_project or f"永久文风档案 {profile_id}"
    else:
        if not args.docx:
            parser.error("必须提供Word文件，或使用 --profile-id 指定现有永久文风档案。")
        source_path = Path(args.docx).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        style_reference = read_docx_text(source_path)
        profile_name = str(args.name or source_path.stem).strip()
        source_project = str(source_path)
        source_label = str(source_path)
    if len(style_reference) < 1000:
        raise RuntimeError("Word中的有效正文不足1000字，无法建立大样本文风档案。")

    config = load_config()
    novel_config = config.get("novel", {})
    provider = get_provider(config, novel_config.get("provider_id"))
    model = str(novel_config.get("model", "") or "").strip()
    if not provider or not model:
        raise RuntimeError("小说AI厂商或模型未配置。")

    reference_hash = hashlib.sha256(style_reference.encode("utf-8")).hexdigest()
    checkpoint_path = OUTPUT_DIR / f"style_archive_{reference_hash[:12]}_checkpoint.json"
    report_path = OUTPUT_DIR / f"style_archive_{reference_hash[:12]}_report.json"
    checkpoint = {}
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    entry = checkpoint.get("cache_entry", {}) if isinstance(checkpoint, dict) else {}
    if not isinstance(entry, dict) or int(entry.get("version", 0) or 0) < STYLE_SHEET_CACHE_VERSION:
        entry = {
            "version": STYLE_SHEET_CACHE_VERSION,
            "status": "building",
            "profile": "",
            "combined_sheet": "",
            "persona": "",
            "style_cards_version": 0,
            "style_cards": [],
            "units": _build_style_profile_units(style_reference, max_units=10, target_chars=2400),
            "merge_results": [],
        }
    units = entry.get("units", []) if isinstance(entry.get("units"), list) else []
    if not units:
        raise RuntimeError("Word正文无法切分成文风分析单元。")
    calls = checkpoint.get("calls", []) if isinstance(checkpoint.get("calls"), list) else []

    def persist():
        entry["cached_at"] = now_str()
        entry["model"] = model
        atomic_write_json(checkpoint_path, {
            "name": profile_name,
            "source_path": source_label,
            "reference_hash": reference_hash,
            "style_chars": len(style_reference),
            "cache_entry": entry,
            "calls": calls,
            "updated_at": now_str(),
        })

    total = len(units)
    expected = total * 2 + max(0, total - 1) + 2
    print(
        f"开始建立文风档案：{profile_name}\n样本{len(style_reference)}字，"
        f"分为{total}个单元，完整建档共{expected}次调用。",
        flush=True,
    )
    for index, unit in enumerate(units):
        if not str(unit.get("baseline", "") or "").strip():
            unit["baseline"] = run_action(
                provider,
                model,
                "style_baseline",
                _build_style_baseline_context(unit, index + 1, total),
                calls,
                f"{index + 1}/{total}",
            )
            persist()
        if not str(unit.get("sheet", "") or "").strip():
            unit["sheet"] = run_action(
                provider,
                model,
                "style_sheet",
                _build_style_sheet_context(unit, index + 1, total),
                calls,
                f"{index + 1}/{total}",
            )
            persist()

    merge_results = entry.setdefault("merge_results", [])
    if total == 1:
        entry["combined_sheet"] = units[0]["sheet"]
    while len(merge_results) < total - 1:
        next_index = len(merge_results) + 1
        previous = merge_results[-1] if merge_results else units[0]["sheet"]
        merged = run_action(
            provider,
            model,
            "style_sheet_merge",
            _build_style_sheet_merge_context(
                previous,
                units[next_index]["sheet"],
                next_index + 1,
                total,
            ),
            calls,
            f"{next_index}/{total - 1}",
        )
        merge_results.append(merged)
        entry["combined_sheet"] = merged
        persist()
    if merge_results:
        entry["combined_sheet"] = merge_results[-1]

    if not str(entry.get("persona", "") or "").strip():
        entry["persona"] = run_action(
            provider,
            model,
            "style_persona",
            _build_style_persona_context(entry.get("combined_sheet", "")),
            calls,
            "最终人格",
        )
        persist()

    if int(entry.get("style_cards_version", 0) or 0) < STYLE_CARD_CACHE_VERSION:
        raw_cards = str(entry.get("style_cards_raw", "") or "").strip()
        if not raw_cards:
            raw_cards = run_action(
                provider,
                model,
                "style_cards",
                _build_style_cards_context(
                    style_reference,
                    entry.get("combined_sheet", ""),
                    entry.get("persona", ""),
                ),
                calls,
                "功能片段库",
            )
            entry["style_cards_raw"] = raw_cards
            persist()
        style_cards = _parse_style_cards_result(raw_cards, style_reference)
        if len(style_cards) < 6:
            raise RuntimeError(f"功能型原文片段卡有效数量不足：{len(style_cards)}")
        entry["style_cards"] = style_cards
        entry["style_cards_version"] = STYLE_CARD_CACHE_VERSION
        entry.pop("style_cards_raw", None)
        persist()

    entry["profile"] = _compose_style_profile(
        entry.get("combined_sheet", ""),
        entry.get("persona", ""),
    )
    entry["status"] = "complete"
    entry.pop("error", None)
    persist()
    profile_id = upsert_style_profile(
        style_reference,
        entry,
        name=profile_name,
        source_project=source_project,
    )
    if not profile_id:
        raise RuntimeError("文风档案生成完成，但写入永久文风列表失败。")

    report = {
        "name": profile_name,
        "id": profile_id,
        "source_path": source_label,
        "provider": provider.get("name", ""),
        "model": model,
        "style_chars": len(style_reference),
        "units": total,
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
