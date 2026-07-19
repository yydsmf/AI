import os
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from gpt_desktop import novel_storage
from gpt_desktop.core import load_json_file, save_json_file


class NovelStorageTests(unittest.TestCase):
    def test_novel_diagnostic_event_is_redacted_and_latest_error_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_values = {
                name: getattr(novel_storage, name)
                for name in (
                    "NOVEL_DIAGNOSTIC_DIR",
                    "NOVEL_DIAGNOSTIC_LOG_FILE",
                    "NOVEL_DIAGNOSTIC_BACKUP_FILE",
                    "NOVEL_DIAGNOSTIC_LATEST_ERROR_FILE",
                )
            }
            try:
                novel_storage.NOVEL_DIAGNOSTIC_DIR = tmp
                novel_storage.NOVEL_DIAGNOSTIC_LOG_FILE = os.path.join(tmp, "events.jsonl")
                novel_storage.NOVEL_DIAGNOSTIC_BACKUP_FILE = os.path.join(tmp, "events.jsonl.1")
                novel_storage.NOVEL_DIAGNOSTIC_LATEST_ERROR_FILE = os.path.join(tmp, "latest.json")

                path = novel_storage.append_novel_diagnostic_event({
                    "event": "request_failed",
                    "level": "error",
                    "api_key": "sk-secret-key",
                    "error": (
                        "Authorization: Bearer sk-secret-key; "
                        "proxy=https://user:password@example.test; retry-after=3"
                    ),
                    "proxy_url": "https://user:password@example.test",
                })

                self.assertEqual(path, novel_storage.NOVEL_DIAGNOSTIC_LOG_FILE)
                with open(path, "r", encoding="utf-8") as handle:
                    raw = handle.read()
                self.assertNotIn("sk-secret-key", raw)
                self.assertNotIn("user:password", raw)
                event = novel_storage.read_latest_novel_diagnostic_error()
                self.assertEqual(event["event"], "request_failed")
                self.assertTrue(event["event_id"])
                self.assertNotIn("api_key", event)
            finally:
                for name, value in old_values.items():
                    setattr(novel_storage, name, value)

    def test_novel_diagnostic_failure_snapshot_keeps_context_and_redacts_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_values = {
                name: getattr(novel_storage, name)
                for name in (
                    "NOVEL_DIAGNOSTIC_DIR",
                    "NOVEL_DIAGNOSTIC_SNAPSHOT_DIR",
                    "NOVEL_DIAGNOSTIC_LATEST_SNAPSHOT_FILE",
                )
            }
            try:
                novel_storage.NOVEL_DIAGNOSTIC_DIR = tmp
                novel_storage.NOVEL_DIAGNOSTIC_SNAPSHOT_DIR = os.path.join(tmp, "snapshots")
                novel_storage.NOVEL_DIAGNOSTIC_LATEST_SNAPSHOT_FILE = os.path.join(tmp, "latest.json")
                context = "【当前章节】\n" + ("连续性资料。" * 900)
                path = novel_storage.save_novel_diagnostic_snapshot("chapter-ai-test/1", {
                    "error": "接口错误",
                    "user_context": context,
                    "partial_output": "半截正文。",
                    "authorization": "Bearer sk-secret-key",
                    "worker_diagnostics": {"context_chars": len(context)},
                })

                self.assertTrue(path.endswith("chapter-ai-test_1.json"))
                with open(path, "r", encoding="utf-8") as handle:
                    snapshot = json.load(handle)
                self.assertEqual(snapshot["user_context"], context)
                self.assertEqual(snapshot["partial_output"], "半截正文。")
                self.assertNotIn("sk-secret-key", json.dumps(snapshot, ensure_ascii=False))
                self.assertTrue(os.path.exists(novel_storage.NOVEL_DIAGNOSTIC_LATEST_SNAPSHOT_FILE))
            finally:
                for name, value in old_values.items():
                    setattr(novel_storage, name, value)

    def test_novel_diagnostic_reader_includes_rotated_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_values = {
                name: getattr(novel_storage, name)
                for name in (
                    "NOVEL_DIAGNOSTIC_LOG_FILE",
                    "NOVEL_DIAGNOSTIC_BACKUP_FILE",
                )
            }
            try:
                current = os.path.join(tmp, "events.jsonl")
                backup = os.path.join(tmp, "events.jsonl.1")
                novel_storage.NOVEL_DIAGNOSTIC_LOG_FILE = current
                novel_storage.NOVEL_DIAGNOSTIC_BACKUP_FILE = backup
                with open(backup, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps({"event": "old"}, ensure_ascii=False) + "\n")
                with open(current, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps({"event": "new"}, ensure_ascii=False) + "\n")

                events = novel_storage.read_novel_diagnostic_events(limit=2)

                self.assertEqual([item["event"] for item in events], ["old", "new"])
            finally:
                for name, value in old_values.items():
                    setattr(novel_storage, name, value)

    def test_project_save_propagates_atomic_write_failure(self):
        with patch.object(novel_storage, "_atomic_write_json", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                novel_storage.save_project_file("/tmp/novel-project.json", {"meta": {}})

    def test_latest_model_exchange_is_overwritten_as_a_single_rolling_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path = novel_storage.NOVEL_DIAGNOSTIC_LATEST_EXCHANGE_FILE
            try:
                novel_storage.NOVEL_DIAGNOSTIC_LATEST_EXCHANGE_FILE = os.path.join(tmp, "exchange.json")
                path = novel_storage.save_novel_diagnostic_latest_exchange(
                    "request-1", {"user_context": "第一份", "partial_output": "结果一"}
                )
                novel_storage.save_novel_diagnostic_latest_exchange(
                    "request-2", {"user_context": "第二份", "partial_output": "结果二"}
                )

                with open(path, "r", encoding="utf-8") as handle:
                    latest = json.load(handle)
                self.assertEqual(latest["request_id"], "request-2")
                self.assertEqual(latest["partial_output"], "结果二")
            finally:
                novel_storage.NOVEL_DIAGNOSTIC_LATEST_EXCHANGE_FILE = old_path

    def test_uncaught_exception_recorder_keeps_python_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_values = {
                name: getattr(novel_storage, name)
                for name in (
                    "NOVEL_DIAGNOSTIC_DIR",
                    "NOVEL_DIAGNOSTIC_LOG_FILE",
                    "NOVEL_DIAGNOSTIC_LATEST_ERROR_FILE",
                )
            }
            try:
                novel_storage.NOVEL_DIAGNOSTIC_DIR = tmp
                novel_storage.NOVEL_DIAGNOSTIC_LOG_FILE = os.path.join(tmp, "events.jsonl")
                novel_storage.NOVEL_DIAGNOSTIC_LATEST_ERROR_FILE = os.path.join(tmp, "latest.json")
                try:
                    raise RuntimeError("模拟未捕获异常")
                except RuntimeError as exc:
                    import sys
                    novel_storage._record_uncaught_novel_exception(
                        type(exc), exc, sys.exc_info()[2], "test-thread"
                    )

                event = novel_storage.read_latest_novel_diagnostic_error()
                self.assertEqual(event["event"], "uncaught_exception")
                self.assertIn("模拟未捕获异常", event["traceback"])
                self.assertEqual(event["origin"], "test-thread")
            finally:
                for name, value in old_values.items():
                    setattr(novel_storage, name, value)

    def test_global_style_profile_library_deduplicates_by_reference_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_library = novel_storage.NOVEL_STYLE_LIBRARY_FILE
            old_builtin_library = novel_storage.NOVEL_BUILTIN_STYLE_LIBRARY_FILE
            try:
                novel_storage.NOVEL_STYLE_LIBRARY_FILE = os.path.join(tmp, "style_profiles.json")
                novel_storage.NOVEL_BUILTIN_STYLE_LIBRARY_FILE = os.path.join(
                    tmp, "missing_builtin_styles.json"
                )
                reference = "可跨小说复用的正文样本。" * 20
                entry = {
                    "version": 2,
                    "status": "complete",
                    "profile": "完整作者档案",
                    "combined_sheet": "证据化写法",
                    "persona": "作者人格",
                    "style_cards_version": 1,
                    "style_cards": [{
                        "id": "SC01",
                        "category": "推理与解释",
                        "title": "核对",
                        "use_when": "人物核对证据",
                        "avoid_when": "高速战斗",
                        "voice_features": "这说明；随后验证",
                        "source_excerpt": reference,
                    }],
                }

                first_id = novel_storage.upsert_style_profile(reference, entry, name="文风甲")
                second_id = novel_storage.upsert_style_profile(reference, entry, name="文风乙")
                profiles = novel_storage.load_style_profile_library()

                self.assertEqual(first_id, second_id)
                self.assertEqual(len(profiles), 1)
                self.assertEqual(profiles[0]["name"], "文风乙")
                self.assertEqual(profiles[0]["cache_entry"]["persona"], "作者人格")
                self.assertEqual(profiles[0]["cache_entry"]["style_cards_version"], 1)
                self.assertEqual(len(profiles[0]["cache_entry"]["style_cards"]), 1)
            finally:
                novel_storage.NOVEL_STYLE_LIBRARY_FILE = old_library
                novel_storage.NOVEL_BUILTIN_STYLE_LIBRARY_FILE = old_builtin_library

    def test_builtin_style_profiles_are_available_without_user_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_library = novel_storage.NOVEL_STYLE_LIBRARY_FILE
            try:
                novel_storage.NOVEL_STYLE_LIBRARY_FILE = os.path.join(tmp, "style_profiles.json")
                profiles = novel_storage.load_style_profile_library()
                by_name = {item.get("name"): item for item in profiles}

                self.assertIn("男频、穿越、都市高武", by_name)
                self.assertIn("女频、穿越现代言情、沙雕搞笑", by_name)
                for item in by_name.values():
                    if item.get("name") not in {
                        "男频、穿越、都市高武",
                        "女频、穿越现代言情、沙雕搞笑",
                    }:
                        continue
                    self.assertGreater(len(item.get("style_reference", "")), 20000)
                    self.assertEqual(item.get("cache_entry", {}).get("status"), "complete")
            finally:
                novel_storage.NOVEL_STYLE_LIBRARY_FILE = old_library

    def test_sync_style_profile_library_collects_completed_project_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_dir = novel_storage.NOVEL_DIR
            old_draft = novel_storage.NOVEL_DRAFT_FILE
            old_library = novel_storage.NOVEL_STYLE_LIBRARY_FILE
            old_builtin_library = novel_storage.NOVEL_BUILTIN_STYLE_LIBRARY_FILE
            try:
                novel_storage.NOVEL_DIR = os.path.join(tmp, "projects")
                novel_storage.NOVEL_DRAFT_FILE = os.path.join(tmp, "draft.json")
                novel_storage.NOVEL_STYLE_LIBRARY_FILE = os.path.join(tmp, "style_profiles.json")
                novel_storage.NOVEL_BUILTIN_STYLE_LIBRARY_FILE = os.path.join(
                    tmp, "missing_builtin_styles.json"
                )
                os.makedirs(novel_storage.NOVEL_DIR)
                reference = "现有项目中的永久文风样本。" * 20
                reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
                save_json_file(os.path.join(novel_storage.NOVEL_DIR, "项目甲.json"), {
                    "meta": {"title": "项目甲文风"},
                    "style_reference": reference,
                    "style_profile_cache": {
                        reference_hash: {"status": "complete", "profile": "永久文风画像"},
                    },
                })

                profiles = novel_storage.sync_style_profile_library_from_projects()

                self.assertEqual(len(profiles), 1)
                self.assertEqual(profiles[0]["id"], reference_hash)
                self.assertEqual(profiles[0]["name"], "项目甲文风")
            finally:
                novel_storage.NOVEL_DIR = old_dir
                novel_storage.NOVEL_DRAFT_FILE = old_draft
                novel_storage.NOVEL_STYLE_LIBRARY_FILE = old_library
                novel_storage.NOVEL_BUILTIN_STYLE_LIBRARY_FILE = old_builtin_library

    def test_save_project_preserves_style_profile_cache_by_reference_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "project.json")
            reference = "正文风格样本"
            reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
            novel_storage.save_project_file(path, {
                "meta": {"title": "文风缓存测试"},
                "style_reference": reference,
                "style_profile_cache": {
                    reference_hash: {
                        "profile": "永久文风画像",
                        "cached_at": "2026-07-12 03:00:00",
                        "model": "test-model",
                    },
                    "invalid": {"profile": "应删除"},
                },
            })

            saved = load_json_file(path, {})
            self.assertEqual(saved["style_profile_cache"][reference_hash]["profile"], "永久文风画像")
            self.assertNotIn("invalid", saved["style_profile_cache"])

    def test_save_project_preserves_incomplete_full_style_sheet_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "project.json")
            reference_hash = hashlib.sha256("大样本".encode("utf-8")).hexdigest()
            novel_storage.save_project_file(path, {
                "meta": {"title": "断点文风测试"},
                "style_reference": "大样本",
                "style_profile_cache": {
                    reference_hash: {
                        "version": 2,
                        "status": "building",
                        "profile": "",
                        "units": [{
                            "id": 1,
                            "source_index": 1,
                            "source_total": 2,
                            "source": "作者原文一",
                            "baseline": "普通基准稿一",
                            "sheet": "",
                        }],
                        "merge_results": [],
                    },
                },
            })

            saved = load_json_file(path, {})
            checkpoint = saved["style_profile_cache"][reference_hash]
            self.assertEqual(checkpoint["version"], 2)
            self.assertEqual(checkpoint["status"], "building")
            self.assertEqual(checkpoint["units"][0]["baseline"], "普通基准稿一")

    def test_load_initial_project_merges_failed_chunks_from_last_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_draft = novel_storage.NOVEL_DRAFT_FILE
            old_last = novel_storage.NOVEL_LAST_FILE
            try:
                draft_path = os.path.join(tmp, "draft.json")
                last_path = os.path.join(tmp, "last.json")
                project_path = os.path.join(tmp, "project.json")
                novel_storage.NOVEL_DRAFT_FILE = draft_path
                novel_storage.NOVEL_LAST_FILE = last_path

                save_json_file(draft_path, {
                    "meta": {"title": "草稿"},
                    "chapters": [],
                    "analysis_state": {
                        "pending_candidate_chapter_ids": ["chapter-a"],
                    },
                })
                save_json_file(project_path, {
                    "meta": {"title": "项目"},
                    "chapters": [],
                    "analysis_state": {
                        "failed_candidate_chunks": [
                            {
                                "index": 1,
                                "total": 1,
                                "text": "失败块正文",
                                "error": "Response ended prematurely",
                            }
                        ],
                        "pending_candidate_chapter_ids": ["chapter-a"],
                        "candidate_postprocess": {
                            "status": "failed",
                            "error": "timeout",
                        },
                    },
                })
                save_json_file(last_path, {"path": project_path})

                data, path = novel_storage.load_initial_project_data()

                self.assertEqual(path, project_path)
                state = data.get("analysis_state", {})
                self.assertEqual(len(state.get("failed_candidate_chunks", [])), 1)
                self.assertEqual(state["failed_candidate_chunks"][0]["text"], "失败块正文")
                self.assertEqual(state.get("pending_candidate_chapter_ids"), ["chapter-a"])
                self.assertEqual(state.get("candidate_postprocess", {}).get("status"), "failed")
            finally:
                novel_storage.NOVEL_DRAFT_FILE = old_draft
                novel_storage.NOVEL_LAST_FILE = old_last

    def test_load_initial_project_prefers_newer_named_project_over_stale_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_draft = novel_storage.NOVEL_DRAFT_FILE
            old_last = novel_storage.NOVEL_LAST_FILE
            try:
                draft_path = os.path.join(tmp, "draft.json")
                last_path = os.path.join(tmp, "last.json")
                project_path = os.path.join(tmp, "project.json")
                novel_storage.NOVEL_DRAFT_FILE = draft_path
                novel_storage.NOVEL_LAST_FILE = last_path

                save_json_file(draft_path, {
                    "meta": {"title": "旧自动草稿"},
                    "chapters": [],
                    "analysis_state": {
                        "pending_candidate_chapter_ids": ["chapter-a"],
                    },
                })
                save_json_file(project_path, {
                    "meta": {"title": "API更新后的正式项目"},
                    "chapters": [{"title": "第一章", "outline": "完整提纲"}],
                })
                save_json_file(last_path, {"path": project_path})
                os.utime(draft_path, (1000, 1000))
                os.utime(project_path, (2000, 2000))

                data, path = novel_storage.load_initial_project_data()

                self.assertEqual(path, project_path)
                self.assertEqual(data["meta"]["title"], "API更新后的正式项目")
                self.assertEqual(len(data["chapters"]), 1)
                self.assertEqual(
                    data.get("analysis_state", {}).get("pending_candidate_chapter_ids"),
                    ["chapter-a"],
                )
            finally:
                novel_storage.NOVEL_DRAFT_FILE = old_draft
                novel_storage.NOVEL_LAST_FILE = old_last

    def test_save_project_file_normalizes_repeated_long_form_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "project.json")
            repeated_note = "允许赵国图继续陈述，最终决定和亲从长计议。"
            repeated_summary = "皇商账册缺页牵出旧案。"

            novel_storage.save_project_file(path, {
                "meta": {"title": "测试项目"},
                "summary": f"{repeated_summary}\n补充：{repeated_summary}",
                "characters": [
                    {
                        "name": "皇上",
                        "role": "皇帝",
                        "notes": f"{repeated_note}\n补充：{repeated_note}",
                    }
                ],
            })

            saved = load_json_file(path, {})
            self.assertEqual(saved["summary"].count(repeated_summary), 1)
            self.assertEqual(saved["characters"][0]["notes"].count(repeated_note), 1)
            self.assertEqual(saved["meta"]["title"], "测试项目")

    def test_save_project_file_can_preserve_mtime_for_project_switch_autosave(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "project.json")
            save_json_file(path, {"meta": {"title": "旧项目"}, "chapters": []})
            old_mtime = 1000000000
            os.utime(path, (old_mtime, old_mtime))

            novel_storage.save_project_file(
                path,
                {"meta": {"title": "新项目"}, "chapters": [{"title": "第一章", "text": "正文"}]},
                preserve_mtime=True,
            )

            saved = load_json_file(path, {})
            self.assertEqual(saved["meta"]["title"], "新项目")
            self.assertEqual(os.path.getmtime(path), old_mtime)


if __name__ == "__main__":
    unittest.main()
