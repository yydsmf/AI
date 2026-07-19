import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from gpt_desktop import novel_storage, novel_v2_storage
from gpt_desktop.novel_v2_context import (
    _assemble_sections,
    build_v2_completion_context,
    build_v2_planning_context,
    build_v2_pov_audit_context,
    build_v2_task_context,
)
from gpt_desktop.novel_v2_utils import (
    _default_project,
    _new_chapter,
    _new_foreshadow,
    _normalize_project,
    _normalize_v2_pov_choice,
    _resolve_v2_chapter_id,
    _v2_pov_value_for_save,
)
from gpt_desktop.novel_v2_workers import (
    NovelV2RollingPlanWorker,
    NovelV2StructuredWorker,
    NovelV2WritingWorker,
    validate_v2_audit_result,
    validate_v2_pov_audit_result,
)
from gpt_desktop.novel_writing_v2_tab import NovelWritingV2Tab


class NovelV2FoundationTests(unittest.TestCase):
    def test_context_assembly_reserves_late_required_constraints(self):
        package = _assemble_sections(
            [
                {"name": "开头硬约束", "text": "必须保留A", "required": True},
                {"name": "可裁剪资料", "text": "资料" * 10000, "required": False},
                {"name": "末尾硬约束", "text": "必须保留B", "required": True},
            ],
            8000,
        )

        self.assertIn("必须保留A", package["text"])
        self.assertIn("必须保留B", package["text"])
        self.assertLessEqual(package["total_chars"], package["limit_chars"])
        self.assertTrue(
            next(item for item in package["manifest"] if item["name"] == "可裁剪资料")["truncated"]
        )

    def test_v2_pov_combo_preserves_imported_viewpoint_detail(self):
        detail = "第三人称限知，以林川为主要视角，单场景不跳视角"

        self.assertEqual(_normalize_v2_pov_choice(detail), "第三人称")
        self.assertEqual(_v2_pov_value_for_save(detail, "第三人称"), detail)
        self.assertEqual(_v2_pov_value_for_save(detail, "第一人称"), "第一人称")
        self.assertEqual(_normalize_v2_pov_choice("未知"), "第三人称")

    def test_v2_pov_audit_uses_full_body_and_requires_evidence(self):
        project = _default_project()
        project["meta"]["pov"] = "第三人称限知"
        chapter = _new_chapter(0)
        chapter["text"] = "林川推开门。" + ("他检查了证据。" * 500)
        project["chapters"] = [chapter]

        package = build_v2_pov_audit_context(project, 0)

        self.assertIn(project["meta"]["pov"], package["text"])
        self.assertIn(chapter["text"], package["text"])
        self.assertEqual(
            validate_v2_pov_audit_result(
                {
                    "decision": "pass",
                    "expected_pov": "第三人称限知",
                    "observed_narration": "third",
                    "evidence": ["林川推开门", "他检查了证据"],
                    "repair_instruction": "",
                }
            ),
            "pass",
        )
        with self.assertRaisesRegex(ValueError, "缺少正文证据"):
            validate_v2_pov_audit_result(
                {
                    "decision": "pass",
                    "expected_pov": "第三人称限知",
                    "observed_narration": "third",
                    "evidence": [],
                }
            )

    def test_v2_audit_requires_all_quality_checks_before_pass(self):
        checks = {
            key: {"status": "pass", "evidence": "证据"}
            for key in (
                "pov_and_viewpoint",
                "causality",
                "character_consistency",
                "continuity",
                "prose_and_dialogue",
                "ending_drive",
            )
        }
        self.assertEqual(validate_v2_audit_result({"decision": "pass", "checks": checks}), "pass")
        checks["pov_and_viewpoint"] = {"status": "fail", "evidence": "第一人称叙述"}
        with self.assertRaisesRegex(ValueError, "结论与失败检查矛盾"):
            validate_v2_audit_result({"decision": "pass", "checks": checks})
        with self.assertRaisesRegex(ValueError, "未完成必填检查"):
            validate_v2_audit_result({"decision": "pass", "checks": {}})

    def test_v2_writing_prompts_and_token_budgets_keep_length_bounded(self):
        outline_worker = NovelV2WritingWorker("", "", "model", "execution_outline", "context")
        draft_worker = NovelV2WritingWorker(
            "",
            "",
            "model",
            "draft",
            "【当前章节】\n本章扩写字数：1200字",
        )

        self.assertEqual(outline_worker._max_tokens_for_request(), 1600)
        self.assertEqual(draft_worker._max_tokens_for_request(), 1440)
        length_worker = NovelV2WritingWorker("", "", "model", "length_repair", draft_worker.context)
        self.assertEqual(length_worker._max_tokens_for_request(), 1440)
        self.assertIn("篇幅编辑", NovelV2WritingWorker.prompt_for_action("length_repair"))
        self.assertIn("900至1400字", NovelV2WritingWorker.prompt_for_action("outline_repair"))
        self.assertIn("pov_and_viewpoint", NovelV2WritingWorker.prompt_for_action("audit"))
        self.assertIn("第三人称正文不得把叙述写成第一人称", NovelV2WritingWorker.prompt_for_action("draft"))
        self.assertIn("绝对不得超过1500字", NovelV2WritingWorker.prompt_for_action("execution_outline"))
        self.assertIn("不得超过目标的120%", NovelV2WritingWorker.prompt_for_action("draft"))
        self.assertTrue(NovelWritingV2Tab._v2_is_retryable_transport_error("接口错误 503：Service temporarily unavailable"))
        self.assertTrue(NovelWritingV2Tab._v2_is_retryable_transport_error("Read timed out"))
        self.assertTrue(NovelWritingV2Tab._v2_is_retryable_transport_error("Response ended prematurely"))
        self.assertTrue(NovelWritingV2Tab._v2_is_retryable_transport_error("Incomplete chunked read"))
        self.assertFalse(NovelWritingV2Tab._v2_is_retryable_transport_error("AI 正文似乎还没有写完"))

        project = _default_project()
        chapter = _new_chapter(0)
        chapter["draft_words"] = "1200"
        project["chapters"] = [chapter]
        draft_context = build_v2_task_context(project, 0, "draft")["text"]
        self.assertTrue(draft_context.endswith("也不得以场景完整为理由超过上限。"))
        self.assertIn("允许范围：1080至1440字", draft_context)
        self.assertEqual(NovelWritingV2Tab._v2_draft_target_bounds("1,200字"), (1200, 1080, 1440))

        outline_context = build_v2_task_context(project, 0, "execution_outline")["text"]
        self.assertTrue(outline_context.endswith("不增加备选方案或复述项目资料。"))

    def test_v2_storage_and_model_config_are_isolated(self):
        self.assertNotEqual(novel_storage.NOVEL_DIR, novel_v2_storage.NOVEL_DIR)
        self.assertNotEqual(novel_storage.NOVEL_DRAFT_FILE, novel_v2_storage.NOVEL_DRAFT_FILE)
        self.assertNotEqual(novel_storage.NOVEL_LAST_FILE, novel_v2_storage.NOVEL_LAST_FILE)
        self.assertEqual(NovelWritingV2Tab.MODEL_CONFIG_SECTION, "novel_v2")
        self.assertEqual(NovelWritingV2Tab._v2_draft_segment_count_for_target("6500"), 1)
        self.assertEqual(NovelWritingV2Tab._v2_draft_segment_count_for_target("6,501字"), 2)
        self.assertEqual(NovelWritingV2Tab._v2_draft_segment_count_for_target("10000"), 2)
        self.assertEqual(NovelWritingV2Tab._v2_draft_segment_count_for_target("15000"), 3)
        self.assertEqual(
            NovelWritingV2Tab._v2_resume_segment_state(
                {"stage": "stopped_draft", "segment_count": 3, "completed_segments": 1}
            ),
            (3, 1, 2),
        )

    def test_v2_pipeline_queues_transport_retry_without_pausing(self):
        tab = NovelWritingV2Tab.__new__(NovelWritingV2Tab)
        tab._chapter_ai_running_action = "draft"
        tab._v2_completion_audit_active = False
        tab._v2_pipeline_active = True
        tab._v2_pipeline_retry_counts = {}
        tab._v2_pending_transport_retry_action = ""
        tab.chapter_ai_preview = Mock()
        tab.chapter_ai_stream_text = "半截流式内容"
        tab.set_status_tip = Mock()
        tab._fail_v2_pipeline = Mock()

        with patch("gpt_desktop.novel_writing_v2_tab.QTimer.singleShot") as single_shot:
            tab.on_chapter_ai_failed("接口错误 503：Service temporarily unavailable")

        self.assertTrue(tab._v2_pipeline_active)
        self.assertEqual(tab._v2_pipeline_retry_counts, {"draft": 1})
        self.assertEqual(tab._v2_pending_transport_retry_action, "draft")
        self.assertEqual(tab.chapter_ai_stream_text, "")
        tab.chapter_ai_preview.clear.assert_called_once_with()
        tab._fail_v2_pipeline.assert_not_called()
        single_shot.assert_called_once()
        self.assertIsNone(
            NovelWritingV2Tab._v2_resume_segment_state(
                {"stage": "audit", "segment_count": 3, "completed_segments": 1}
            )
        )

    def test_v2_storage_round_trip_uses_only_v2_paths(self):
        old_values = (
            novel_v2_storage.NOVEL_DIR,
            novel_v2_storage.NOVEL_DRAFT_FILE,
            novel_v2_storage.NOVEL_LAST_FILE,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            novel_v2_storage.NOVEL_DIR = os.path.join(temp_dir, "v2_projects")
            novel_v2_storage.NOVEL_DRAFT_FILE = os.path.join(temp_dir, "v2_draft.json")
            novel_v2_storage.NOVEL_LAST_FILE = os.path.join(temp_dir, "v2_last.json")
            try:
                novel_v2_storage.ensure_novel_storage()
                project = _default_project()
                project["meta"]["title"] = "隔离项目"
                path = novel_v2_storage.save_named_project("隔离项目", project)
                novel_v2_storage.save_draft_project(project)
                novel_v2_storage.remember_project_path(path)

                loaded, loaded_path = novel_v2_storage.load_initial_project_data()

                self.assertTrue(path.startswith(novel_v2_storage.NOVEL_DIR))
                self.assertEqual(loaded_path, path)
                self.assertEqual(loaded["meta"]["title"], "隔离项目")
                self.assertTrue(os.path.exists(novel_v2_storage.NOVEL_DRAFT_FILE))
            finally:
                (
                    novel_v2_storage.NOVEL_DIR,
                    novel_v2_storage.NOVEL_DRAFT_FILE,
                    novel_v2_storage.NOVEL_LAST_FILE,
                ) = old_values

    def test_normalize_preserves_v2_long_form_chapter_and_foreshadow_fields(self):
        project = _default_project()
        chapter = _new_chapter(0)
        chapter.update(
            {
                "chapter_task": "本章任务",
                "execution_outline": "执行提纲",
                "actual_outline": "实写提纲",
                "linked_character_ids": ["C1"],
                "linked_lore_ids": ["L1"],
                "planned_foreshadow_ids": ["F-ID"],
                "quality_review": {"decision": "pass"},
                "state_delta": {"plot_tasks": ["推进主线"]},
            }
        )
        project["chapters"] = [chapter]
        foreshadow = _new_foreshadow(0)
        foreshadow.update(
            {
                "setup_chapter_id": chapter["id"],
                "priority": "高",
                "canonical_summary": "标准伏笔描述",
                "evidence": [{"chapter_id": chapter["id"], "operation": "setup"}],
            }
        )
        project["foreshadow_items"] = [foreshadow]
        project["long_form"]["state_snapshot"]["as_of_chapter_id"] = chapter["id"]

        normalized = _normalize_project(project)

        normalized_chapter = normalized["chapters"][0]
        self.assertEqual(normalized_chapter["chapter_task"], "本章任务")
        self.assertEqual(normalized_chapter["execution_outline"], "执行提纲")
        self.assertEqual(normalized_chapter["actual_outline"], "实写提纲")
        self.assertEqual(normalized_chapter["quality_review"]["decision"], "pass")
        self.assertEqual(normalized["foreshadow_items"][0]["setup_chapter_id"], chapter["id"])
        self.assertEqual(normalized["foreshadow_items"][0]["evidence"][0]["operation"], "setup")
        self.assertEqual(normalized["long_form"]["state_snapshot"]["as_of_chapter_id"], chapter["id"])

    def test_audit_context_keeps_full_current_body_and_uses_recent_memory(self):
        project = _default_project()
        previous = _new_chapter(0)
        previous.update(
            {
                "title": "前章",
                "text": "不应整章进入上下文" * 1000 + "上一章结尾标记",
                "actual_outline": "前章真实发生的情节",
                "summary": "前章摘要",
                "key_facts": "人物已抵达车站",
            }
        )
        current = _new_chapter(1)
        current.update(
            {
                "title": "当前章",
                "chapter_task": "完成交易并发生反转",
                "text": "当前正文唯一标记。" * 800,
            }
        )
        project["chapters"] = [previous, current]

        package = build_v2_task_context(project, 1, "audit")

        self.assertIn(current["text"], package["text"])
        self.assertIn("前章真实发生的情节", package["text"])
        self.assertIn("上一章结尾标记", package["text"])
        self.assertNotIn(previous["text"], package["text"])
        self.assertLessEqual(package["total_chars"], package["limit_chars"])

    def test_execution_outline_context_keeps_late_constraints_and_foreshadow_debt(self):
        project = _default_project()
        chapters = []
        for index in range(11):
            chapter = _new_chapter(index)
            chapter["actual_outline"] = f"第{index + 1}章真实提纲" + ("推进事实。" * 300)
            chapter["key_facts"] = f"第{index + 1}章关键事实" + ("状态变化。" * 300)
            chapters.append(chapter)
        project["chapters"] = chapters
        foreshadow = _new_foreshadow(0)
        foreshadow.update({"id": "must-keep-debt", "name": "必须保留的伏笔", "status": "已埋"})
        project["foreshadow_items"] = [foreshadow]

        package = build_v2_task_context(project, 10, "execution_outline")

        self.assertIn("must-keep-debt", package["text"])
        self.assertIn("执行提纲以800至1200字为目标", package["text"])
        self.assertLessEqual(package["total_chars"], package["limit_chars"])

    def test_audit_context_never_silently_truncates_required_current_body(self):
        project = _default_project()
        chapter = _new_chapter(0)
        chapter["text"] = "正文" * 30000
        project["chapters"] = [chapter]

        with self.assertRaisesRegex(ValueError, "不能静默截断"):
            build_v2_task_context(project, 0, "audit", total_limit=12000)

    def test_postwrite_context_contains_full_body_and_all_open_foreshadow_ids(self):
        project = _default_project()
        chapter = _new_chapter(0)
        chapter["text"] = "完整正文标记。" * 700
        project["chapters"] = [chapter]
        project["foreshadow_items"] = []
        for index in range(50):
            item = _new_foreshadow(index)
            item["id"] = f"open-id-{index}"
            item["name"] = f"开放伏笔{index}"
            item["status"] = "已埋"
            project["foreshadow_items"].append(item)

        package = build_v2_task_context(project, 0, "postwrite")

        self.assertIn(chapter["text"], package["text"])
        self.assertIn("open-id-0", package["text"])
        self.assertIn("open-id-49", package["text"])

    def test_planning_context_uses_memory_not_full_chapter_history(self):
        project = _default_project()
        chapter = _new_chapter(0)
        chapter.update(
            {
                "text": "历史正文头部唯一标记" + "中间内容" * 2000 + "历史正文结尾唯一标记",
                "actual_outline": "实际完成了关键谈判",
                "summary": "谈判完成",
                "key_facts": "合同已签署",
            }
        )
        project["chapters"] = [chapter]

        package = build_v2_planning_context(project, 1)

        self.assertIn("实际完成了关键谈判", package["text"])
        self.assertIn("历史正文结尾唯一标记", package["text"])
        self.assertNotIn("历史正文头部唯一标记", package["text"])

    def test_planning_context_keeps_imported_full_book_direction(self):
        project = _default_project()
        project["chapters"] = [_new_chapter(0)]
        project["imported_chapter_plan_reference"] = {
            "summary": "全书最终走向唯一标记",
            "chapters": [
                {"index": index, "title": f"粗纲{index}", "outline": f"第{index}阶段方向"}
                for index in range(1, 31)
            ],
        }

        package = build_v2_planning_context(project, 0)

        self.assertIn("全书最终走向唯一标记", package["text"])
        self.assertIn("第30阶段方向", package["text"])

    def test_rolling_plan_normalization_keeps_stable_record_ids(self):
        worker = NovelV2RollingPlanWorker(
            "https://example.invalid",
            "key",
            "model",
            "context",
            300000,
            5000,
            3,
            60,
            10,
            detailed_chapter_count=2,
        )
        data = {
            "summary": "窗口规划",
            "book_plan": {"ending_direction": "主角主动选择公开真相"},
            "checkpoint": {"progress": "主线已推进"},
            "chapters": [
                {
                    "index": index,
                    "title": f"标题{index}",
                    "target_words": "5000",
                    "chapter_task": f"任务{index}",
                    "outline": f"提纲{index}",
                    "character_ids": [f"C{index}"],
                    "lore_ids": [f"L{index}"],
                    "foreshadow_actions": [{"id": f"F{index}", "action": "reinforce", "reason": "自然推进"}],
                }
                for index in range(1, 4)
            ],
        }

        plan = worker._normalize_plan(data)

        self.assertEqual([item["detail_level"] for item in plan["chapters"]], ["detailed", "detailed", "direction"])
        self.assertEqual(plan["chapters"][0]["character_ids"], ["C1"])
        self.assertEqual(plan["chapters"][0]["lore_ids"], ["L1"])
        self.assertEqual(plan["chapters"][0]["foreshadows"], ["F1"])
        self.assertEqual(plan["checkpoint"]["progress"], "主线已推进")
        self.assertEqual(plan["book_plan"]["ending_direction"], "主角主动选择公开真相")

    def test_structured_worker_returns_normalized_json_bundle(self):
        worker = NovelV2StructuredWorker(
            "https://example.invalid",
            "key",
            "model",
            "audit",
            "context",
        )
        worker._analysis_request_capabilities = lambda: (True, True)
        worker._analyze_chunk_with_retries = lambda *args: (
            {"decision": "pass", "issues": []},
            True,
        )
        results = []
        worker.result_ready.connect(lambda action, content: results.append((action, content)))

        worker.run()

        self.assertEqual(results[0][0], "audit")
        self.assertEqual(json.loads(results[0][1])["decision"], "pass")

    def test_legacy_chapter_references_are_migrated_to_stable_ids(self):
        chapters = [_new_chapter(index) for index in range(3)]
        chapters[0]["title"] = "雨夜重逢"
        chapters[1]["title"] = "旧案来客"
        chapters[2]["title"] = "证词反转"

        self.assertEqual(_resolve_v2_chapter_id(chapters, "章节 1"), chapters[0]["id"])
        self.assertEqual(_resolve_v2_chapter_id(chapters, "第2章"), chapters[1]["id"])
        self.assertEqual(_resolve_v2_chapter_id(chapters, "证词反转"), chapters[2]["id"])
        self.assertEqual(_resolve_v2_chapter_id(chapters, "本片段"), "")

        project = _default_project()
        project["chapters"] = chapters
        foreshadow = _new_foreshadow(0)
        foreshadow["setup_chapter"] = "章节 1"
        foreshadow["payoff_chapter"] = "证词反转"
        project["foreshadow_items"] = [foreshadow]
        normalized = _normalize_project(project)
        self.assertEqual(normalized["foreshadow_items"][0]["setup_chapter_id"], chapters[0]["id"])
        self.assertEqual(normalized["foreshadow_items"][0]["payoff_chapter_id"], chapters[2]["id"])

    def test_replanning_uses_both_chapter_and_written_length_thresholds(self):
        tab = NovelWritingV2Tab.__new__(NovelWritingV2Tab)
        project = _default_project()
        chapters = []
        for index in range(10):
            chapter = _new_chapter(index)
            chapter["text"] = "正文" * 2000
            chapters.append(chapter)
        project["chapters"] = chapters
        project["long_form"]["rolling_plan"] = {
            "status": "active",
            "source_chapter_count": 5,
            "chapter_tasks": [
                {"chapter_index": index, "chapter_id": f"future-{index}"}
                for index in range(6, 16)
            ],
        }
        tab.current_project = project

        self.assertTrue(tab._v2_auto_replan_due())
        self.assertEqual(tab._v2_checkpoint_kind(10), "full")

        project["long_form"]["checkpoints"] = [{"kind": "full", "chapter_count": 10}]
        self.assertEqual(tab._v2_checkpoint_kind(10), "light")

    def test_completion_context_contains_all_chapter_memories_and_open_debt_ids(self):
        project = _default_project()
        chapters = []
        for index in range(100):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节标题{index + 1}"
            chapter["actual_outline"] = f"第{index + 1}章实写事件"
            chapter["key_facts"] = f"第{index + 1}章关键事实"
            chapters.append(chapter)
        project["chapters"] = chapters
        project["bible"] = "小说圣经约束。" * 400
        project["world_rules"] = "世界规则约束。" * 300
        project["characters"] = []
        for index in range(120):
            project["characters"].append(
                {
                    "id": f"character-id-{index}",
                    "name": f"人物{index}",
                    "role": "参与主线推进的重要人物",
                    "goal": "完成个人选择并推动最终冲突",
                    "secret": "",
                    "voice": "",
                    "notes": "",
                }
            )
        project["foreshadow_items"] = []
        for index in range(120):
            foreshadow = _new_foreshadow(index)
            foreshadow["id"] = f"stable-debt-{index}"
            foreshadow["name"] = f"尚未兑现的承诺{index}"
            foreshadow["status"] = "已埋"
            project["foreshadow_items"].append(foreshadow)

        package = build_v2_completion_context(project)

        self.assertIn("第1章实写事件", package["text"])
        self.assertIn("第100章实写事件", package["text"])
        self.assertIn("stable-debt-0", package["text"])
        self.assertIn("stable-debt-119", package["text"])
        self.assertIn("character-id-0", package["text"])
        self.assertIn("character-id-119", package["text"])
        self.assertLessEqual(package["total_chars"], package["limit_chars"])

    def test_only_high_confidence_foreshadow_duplicates_are_auto_consolidated(self):
        tab = NovelWritingV2Tab.__new__(NovelWritingV2Tab)
        project = _default_project()
        canonical = _new_foreshadow(0)
        canonical.update({"id": "canonical", "name": "失踪账本", "status": "已埋", "description": "账本下落不明"})
        duplicate = _new_foreshadow(1)
        duplicate.update({"id": "duplicate", "name": "账册线索", "status": "已埋", "description": "同一本账本的去向"})
        uncertain = _new_foreshadow(2)
        uncertain.update({"id": "uncertain", "name": "另一份账册", "status": "已埋"})
        chapter = _new_chapter(0)
        chapter["planned_foreshadow_ids"] = ["duplicate", "uncertain"]
        project["chapters"] = [chapter]
        project["foreshadow_items"] = [canonical, duplicate, uncertain]
        tab.current_project = project

        replacements = tab._apply_v2_plan_foreshadow_maintenance(
            {
                "merge_groups": [
                    {
                        "canonical_id": "canonical",
                        "duplicate_ids": ["duplicate"],
                        "canonical_summary": "失踪账本的最终去向",
                        "confidence": "high",
                        "reason": "同一物件",
                    },
                    {
                        "canonical_id": "canonical",
                        "duplicate_ids": ["uncertain"],
                        "confidence": "medium",
                    },
                ]
            }
        )

        self.assertEqual(replacements, {"duplicate": "canonical"})
        self.assertEqual(duplicate["status"], "废弃")
        self.assertEqual(duplicate["merged_into_id"], "canonical")
        self.assertEqual(uncertain["status"], "已埋")
        self.assertEqual(chapter["planned_foreshadow_ids"], ["canonical", "uncertain"])

    def test_postwrite_updates_create_durable_records_and_keep_foreshadow_evidence_idempotent(self):
        tab = NovelWritingV2Tab.__new__(NovelWritingV2Tab)
        project = _default_project()
        chapter = _new_chapter(0)
        project["chapters"] = [chapter]
        foreshadow = _new_foreshadow(0)
        foreshadow.update({"id": "debt-1", "name": "旧案证词", "status": "已埋"})
        project["foreshadow_items"] = [foreshadow]
        tab.current_project = project

        tab._v2_apply_record_updates(
            {
                "characters": [
                    {
                        "operation": "create",
                        "name": "林律师",
                        "fields": {"role": "长期法律顾问", "goal": "查清旧案"},
                        "evidence": "正文中正式接受长期委托",
                    }
                ],
                "lore": [
                    {
                        "operation": "create",
                        "name": "青色锁链",
                        "fields": {"type": "物品", "description": "跨章束缚主角"},
                        "evidence": "连续多章没有解除",
                    }
                ],
            },
            chapter["id"],
        )
        tab._v2_apply_record_updates(
            {
                "characters": [{"operation": "create", "name": "林律师", "fields": {"goal": "保护证人"}}],
                "lore": [{"operation": "create", "name": "青色锁链", "fields": {"description": "仍未解除"}}],
            },
            chapter["id"],
        )
        update = {
            "id": "debt-1",
            "operation": "payoff",
            "status": "已回收",
            "canonical_summary": "证词真伪已经查清",
            "evidence": "证人当庭承认伪造证词",
        }
        tab._v2_apply_foreshadow_updates([update], chapter)
        tab._v2_apply_foreshadow_updates([update], chapter)
        created = {
            "operation": "create",
            "name": "F0002｜父母死亡真相",
            "status": "已埋",
            "evidence": "主角承诺日后查清父母死因",
        }
        tab._v2_apply_foreshadow_updates([created], chapter)
        tab._v2_apply_foreshadow_updates([created], chapter)

        self.assertEqual(len(project["characters"]), 1)
        self.assertEqual(project["characters"][0]["name"], "林律师")
        self.assertEqual(project["characters"][0]["goal"], "保护证人")
        self.assertEqual(len(project["lore"]), 1)
        self.assertEqual(project["lore"][0]["name"], "青色锁链")
        self.assertEqual(project["characters"][0]["evidence"][0]["chapter_id"], chapter["id"])
        self.assertEqual(foreshadow["status"], "已回收")
        self.assertEqual(foreshadow["payoff_chapter_id"], chapter["id"])
        self.assertEqual(len(foreshadow["evidence"]), 1)
        self.assertEqual(len(project["foreshadow_items"]), 2)
        self.assertEqual(project["foreshadow_items"][1]["name"], "父母死亡真相")

        postwrite_prompt = NovelV2WritingWorker.prompt_for_action("postwrite")
        self.assertIn("未解真相不能只放unresolved_tasks", postwrite_prompt)
        self.assertIn("跨章关键物件不能只放状态", postwrite_prompt)
        self.assertIn("持续角色不能只放character_states", postwrite_prompt)

    def test_300k_scale_contexts_stay_bounded_and_keep_current_chapter_complete(self):
        project = _default_project()
        project["meta"]["target_words"] = "300000"
        project["bible"] = "核心合同。" * 500
        project["world_rules"] = "硬规则。" * 500
        project["chapters"] = []
        for index in range(100):
            chapter = _new_chapter(index)
            chapter["title"] = f"第{index + 1}章"
            chapter["chapter_task"] = f"推进第{index + 1}章核心冲突"
            chapter["execution_outline"] = "场景一冲突；场景二转折；场景三收束。"
            chapter["text"] = f"当前章节正文起点{index}。" + ("文" * 2980) + f"。当前章节正文终点{index}。"
            chapter["actual_outline"] = f"第{index + 1}章完成一次不可逆推进"
            chapter["summary"] = f"第{index + 1}章摘要"
            chapter["key_facts"] = f"第{index + 1}章末状态已确认"
            project["chapters"].append(chapter)
        project["foreshadow_items"] = []
        for index in range(100):
            item = _new_foreshadow(index)
            item.update(
                {
                    "id": f"scale-debt-{index}",
                    "name": f"规模伏笔{index}",
                    "status": "已埋",
                    "canonical_summary": f"需要在后续确认的叙事承诺{index}",
                }
            )
            project["foreshadow_items"].append(item)
        project["characters"] = [
            {
                "id": f"scale-character-{index}",
                "name": f"规模人物{index}",
                "role": "主要人物",
                "goal": "完成个人弧线",
                "secret": "",
                "voice": "",
                "notes": "",
            }
            for index in range(50)
        ]
        current_body = project["chapters"][99]["text"]

        planning = build_v2_planning_context(project, 100, checkpoint=True)
        audit = build_v2_task_context(project, 99, "audit")
        postwrite = build_v2_task_context(project, 99, "postwrite")
        completion = build_v2_completion_context(project)

        for package in (planning, audit, postwrite, completion):
            self.assertLessEqual(package["total_chars"], package["limit_chars"])
        self.assertIn(current_body, audit["text"])
        self.assertIn(current_body, postwrite["text"])
        self.assertIn("scale-debt-99", postwrite["text"])
        self.assertIn("第100章完成一次不可逆推进", completion["text"])


if __name__ == "__main__":
    unittest.main()
