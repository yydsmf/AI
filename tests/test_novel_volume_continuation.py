import json
import os
import tempfile
import unittest
from unittest.mock import patch

from gpt_desktop.app import MainWindow
from gpt_desktop.novel_utils import (
    NOVEL_AI_CONTEXT_LIMIT,
    _build_chapter_ai_context,
    _build_volume_opening_handoff_context,
    _build_volume_handoff_record_catalog,
    _build_volume_handoff_source,
    _default_project,
    _inherit_continuation_record_ids,
    _normalize_project,
    _normalize_creative_intent_contract,
    _project_without_private_notes,
    _rebase_long_form_memory_for_volume_continuation,
    VOLUME_FRAMEWORK_HANDOFF_CHAR_BUDGET,
    VOLUME_HANDOFF_SOURCE_CHAR_BUDGET,
    _volume_two_framework_template_text,
)
from gpt_desktop.novel_writing_tab import (
    NovelWritingTab,
    _CHAPTER_PLAN_CONTEXT_CHAR_BUDGET,
    _volume_handoff_display_text,
)
from gpt_desktop.workers import (
    NovelChapterPlanWorker,
    NovelVolumeFrameworkWorker,
    NovelVolumeFrameworkAlignmentWorker,
    NovelVolumeHandoffWorker,
    NovelVolumeIntentWorker,
)


class NovelVolumeContinuationTests(unittest.TestCase):
    def test_creative_intent_contract_is_compact_and_normalized(self):
        contract = _normalize_creative_intent_contract({
            "主线": "感情线推进",
            "辅助线": "男二、女二，商业线",
            "核心关系": "双方阶段推进但不完全复合",
            "读感": "情绪拉满、爽点密集",
        })

        self.assertEqual(contract["primary_line"], "感情线推进")
        self.assertEqual(contract["supporting_lines"], ["男二", "女二", "商业线"])
        self.assertEqual(contract["core_relationships"], "双方阶段推进但不完全复合")
        self.assertNotIn("narrative_strategy_profile", contract)

    def test_intent_worker_keeps_user_priority_over_handoff(self):
        worker = NovelVolumeIntentWorker(
            "", "", "gpt-5.6-sol",
            {"title": "第二卷", "target_words": "50万"},
            "本卷主要以感情线为主，加强追夫火葬场。",
            {"volume_summary": "第一卷有商业审查线。"},
        )

        self.assertIn("用户明确写出的主线优先级最高", worker._analysis_prompt())
        contract = worker._normalize_intent({
            "primary_line": "感情线与关系推进",
            "supporting_lines": ["男二女二", "商业线"],
        })
        self.assertEqual(contract["primary_line"], "感情线与关系推进")
        self.assertEqual(contract["source"], "volume_user_requirements")

    def test_intent_worker_does_not_request_boundary_but_preserves_model_value(self):
        worker = NovelVolumeIntentWorker(
            "", "", "gpt-5.6-sol",
            {"title": "第二卷", "target_words": "50万"},
            "本卷以感情线为主。",
            {},
        )

        self.assertNotIn("ending_boundaries", worker._analysis_prompt())
        contract = worker._normalize_intent({
            "primary_line": "感情线推进",
            "ending_boundaries": "双方暂不完全复合",
        })
        self.assertEqual(contract["ending_boundaries"], "双方暂不完全复合")

    def test_handoff_worker_does_not_request_boundary_but_preserves_model_value(self):
        worker = NovelVolumeHandoffWorker(
            "", "", "gpt-5.6-sol",
            {"records": {}, "last_chapter": {}},
            source_catalog={},
        )

        self.assertNotIn("continuity_boundaries", worker._analysis_prompt())
        handoff = worker._normalize_handoff({
            "volume_summary": "第一卷结束。",
            "continuity_boundaries": ["旧案卷宗仍由赵明保管。"],
        })
        self.assertEqual(
            handoff["continuity_boundaries"],
            ["旧案卷宗仍由赵明保管。"],
        )

    def test_framework_and_alignment_prompts_receive_confirmed_intent(self):
        contract = {
            "primary_line": "感情线推进与追夫火葬场",
            "supporting_lines": ["男二女二制造情绪压力"],
            "ending_boundaries": "不完全复合，不写圆满结局",
        }
        framework_worker = NovelVolumeFrameworkWorker(
            "", "", "gpt-5.6-sol", {}, "用户要求", "模板",
            setup_meta={"target_words": "50万"},
            creative_intent_contract=contract,
        )
        request = framework_worker._framework_user_text()
        self.assertIn("creative_intent_contract", request)
        self.assertIn("追夫火葬场", request)
        self.assertIn("优先级高于交接资料", framework_worker._analysis_prompt())

        alignment_worker = NovelVolumeFrameworkAlignmentWorker(
            "", "", "gpt-5.6-sol",
            {"meta": {"premise": "旧主线"}, "chapter_plan": {"stages": []}},
            contract,
            "感情线为主",
        )
        self.assertIn("primary_line必须是真正的本卷主导线", alignment_worker._analysis_prompt())
        alignment = alignment_worker._normalize_alignment({
            "meta": {"premise": "关系主线的新状态"},
            "chapter_plan": {"summary": "关系推进", "stages": [], "chapters": []},
        })
        self.assertEqual(alignment["meta"]["premise"], "关系主线的新状态")
        self.assertEqual(alignment["chapter_plan"]["summary"], "关系推进")

    def test_creative_intent_is_persisted_but_not_in_public_body_snapshot(self):
        project = _normalize_project({
            "creative_intent_contract": {
                "primary_line": "感情线推进",
                "supporting_lines": ["男二女二"],
            },
        })

        self.assertEqual(project["creative_intent_contract"]["primary_line"], "感情线推进")
        public_project = _project_without_private_notes(project)
        self.assertNotIn("creative_intent_contract", public_project)

    def test_resume_keeps_confirmed_creative_intent(self):
        source_path = "/tmp/第一卷项目-意图.json"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._volume_two_pending = {
            "source_path": source_path,
            "source_hash": "source-hash-intent",
            "source_meta": {"title": "第一卷"},
            "handoff": {"volume_summary": "第一卷收束"},
            "setup": {"requirements": "感情线为主"},
            "creative_intent_contract": {"primary_line": "感情线推进"},
            "framework": {},
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "gpt_desktop.novel_writing_tab.HISTORY_DIR", temp_dir
        ):
            resume_path = tab._save_volume_two_resume("intent_ready")
            restarted = NovelWritingTab.__new__(NovelWritingTab)
            resumed = restarted._load_volume_two_resume(source_path, "source-hash-intent")
            self.assertEqual(resumed["stage"], "intent_ready")
            self.assertEqual(
                resumed["creative_intent_contract"]["primary_line"], "感情线推进"
            )

    def test_handoff_prompt_prefers_index_selection_over_repeated_record_text(self):
        worker = NovelVolumeHandoffWorker(
            "",
            "",
            "gpt-5.6-sol",
            {"records": {"characters": [], "lore": [], "foreshadows": []}},
        )

        prompt = worker._analysis_prompt()

        self.assertIn("输出以去重为先", prompt)
        self.assertIn("只负责从本地档案中选择需要沿用的名称/编号", prompt)
        self.assertIn("程序会按名称/编号从上一卷本地档案补回完整资料", prompt)
        self.assertIn("活动伏笔不是本卷必须回收清单", prompt)
        self.assertIn("deferred_foreshadows", prompt)
        self.assertIn("输出是交接索引，不是完整复述稿", prompt)

    def test_framework_prompt_receives_target_words_and_five_wan_stage_guidance(self):
        worker = NovelVolumeFrameworkWorker(
            "",
            "",
            "gpt-5.6-sol",
            {"reusable_characters": [], "reusable_lore": [], "reusable_foreshadows": []},
            "加强情绪线，保持第一卷人物关系底盘。",
            _volume_two_framework_template_text(),
            setup_meta={"title": "第二卷", "target_words": "50"},
        )

        prompt = worker._analysis_prompt()
        user_text = worker._framework_user_text()

        self.assertIn("约50万字", prompt)
        self.assertIn("每阶段约5万字", prompt)
        self.assertIn("约10个阶段", prompt)
        self.assertIn("chapters必须返回空数组", prompt)
        self.assertIn("只写本卷新增或变更的世界规则", prompt)
        self.assertIn("上一卷圣经和世界规则由程序本地继承", prompt)
        self.assertIn("reusable_foreshadows才是本卷默认可用的旧伏笔", prompt)
        self.assertIn("本卷基本信息", user_text)
        self.assertIn('"target_words": "50"', user_text)
        self.assertNotIn("禁用设定", user_text)
        self.assertNotIn("硬边界", user_text)

    def test_volume_framework_normalization_drops_empty_candidate_markers(self):
        worker = NovelVolumeFrameworkWorker(
            "",
            "",
            "gpt-5.6-sol",
            {
                "reusable_characters": [{
                    "name": "陈景川",
                    "notes": "第一卷结尾状态。",
                }],
                "reusable_lore": [],
                "reusable_foreshadows": [{
                    "name": "关系边界",
                    "code": "F0001",
                    "description": "双方尚未完成选择。",
                }],
            },
            "感情线为主",
            _volume_two_framework_template_text(),
        )

        result = worker._normalize_framework_result({
            "characters": [{
                "name": "陈景川",
                "notes": "AI 分析候选",
            }, {
                "name": "苏晚晴",
            }],
            "lore": [],
            "foreshadows": [{
                "name": "关系边界",
                "code": "F0001",
                "description": "AI 分析候选",
                "review_reason": "双方仍未完成选择。",
            }],
            "project_materials": {},
            "chapter_plan": {"chapters": []},
        })

        serialized = repr(result)
        self.assertNotIn("AI 分析候选", serialized)
        self.assertIn("双方仍未完成选择", serialized)

    def test_shutdown_waits_for_running_volume_worker(self):
        class FakeWorker:
            def __init__(self):
                self.calls = []
                self.running = True

            def stop(self):
                self.calls.append("stop")

            def requestInterruption(self):
                self.calls.append("interrupt")

            def quit(self):
                self.calls.append("quit")

            def isRunning(self):
                self.calls.append("is_running")
                return self.running

            def wait(self, timeout):
                self.calls.append(("wait", timeout))
                self.running = False
                return True

        worker = FakeWorker()
        MainWindow._stop_worker(object(), worker)

        self.assertEqual(worker.calls[:3], ["stop", "interrupt", "quit"])
        self.assertIn(("wait", 5000), worker.calls)

    def test_volume_resume_state_survives_restart_and_rejects_changed_source(self):
        source_path = "/tmp/第一卷项目.json"
        source_hash = "source-hash-1"
        first_tab = NovelWritingTab.__new__(NovelWritingTab)
        first_tab._volume_two_pending = {
            "source_path": source_path,
            "source_hash": source_hash,
            "source_meta": {"title": "第一卷"},
            "handoff": {"volume_summary": "第一卷已收束。"},
            "setup": {"requirements": "第二卷加强情绪线。"},
            "framework": {"meta": {"title": "第二卷"}},
        }

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "gpt_desktop.novel_writing_tab.HISTORY_DIR", temp_dir
        ):
            resume_path = first_tab._save_volume_two_resume("framework_ready")
            self.assertTrue(resume_path)
            self.assertTrue(os.path.exists(resume_path))

            restarted_tab = NovelWritingTab.__new__(NovelWritingTab)
            resumed = restarted_tab._load_volume_two_resume(source_path, source_hash)
            self.assertEqual(resumed["stage"], "framework_ready")
            self.assertEqual(resumed["handoff"]["volume_summary"], "第一卷已收束。")
            self.assertEqual(resumed["framework"]["meta"]["title"], "第二卷")

            self.assertEqual(
                restarted_tab._load_volume_two_resume(source_path, "changed-source"),
                {},
            )
            self.assertFalse(os.path.exists(resume_path))

    def test_volume_resume_migrates_legacy_successful_handoff_exchange(self):
        project = self._source_project()
        source_path = "/tmp/legacy-first-volume.json"
        source = _build_volume_handoff_source(project)
        source_hash = "legacy-source-hash"
        verifier = NovelVolumeHandoffWorker("", "", "", source)
        handoff = {"volume_summary": "旧诊断中已生成的交接摘要。"}
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = project

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "gpt_desktop.novel_writing_tab.HISTORY_DIR", temp_dir
        ):
            latest_path = os.path.join(
                temp_dir, "novel_diagnostics", "latest_model_exchange.json"
            )
            os.makedirs(os.path.dirname(latest_path), exist_ok=True)
            with open(latest_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "stage": "handoff",
                        "outcome": "success",
                        "project_path": source_path,
                        "model": "gpt-5.6-sol",
                        "user_context": verifier._chunk_user_text("", 1, 1),
                        "partial_output": json.dumps(handoff, ensure_ascii=False),
                    },
                    handle,
                    ensure_ascii=False,
                )

            # The hash is intentionally only used as the current source token
            # here; the request-body hash verifies that the project content is
            # the same before the legacy exchange is migrated.
            migrated = tab._load_volume_two_resume(source_path, source_hash)
            self.assertEqual(migrated["stage"], "handoff_ready")
            self.assertEqual(migrated["handoff"]["volume_summary"], handoff["volume_summary"])

    def test_handoff_display_is_readable_text_not_raw_json(self):
        display = _volume_handoff_display_text({
            "volume_summary": "第一卷结束时录音尚未播放。",
            "ending_state": {"location": "酒店休息室", "last_action": "拿到录音。"},
            "reusable_characters": [{"name": "沈知夏", "role": "女主", "voice": "口语化吐槽"}],
            "reusable_foreshadows": [{"name": "匿名录音", "status": "已埋", "remaining_secret": "第三人身份"}],
        })

        self.assertIn("上一卷交接摘要", display)
        self.assertIn("沈知夏", display)
        self.assertIn("匿名录音", display)
        self.assertNotIn('"volume_summary"', display)
        self.assertNotIn('"reusable_characters"', display)
        self.assertNotIn("{", display)
        self.assertNotIn("}", display)

    def _source_project(self):
        project = _default_project()
        project["meta"].update({
            "title": "第一卷",
            "genre": "现代言情",
            "style": "情绪爽文",
            "target_words": "20万",
        })
        project["bible"] = "核心设定：两人仍未解除误会。"
        project["world_rules"] = "顾家继承权须经董事会确认。"
        project["characters"] = [{
            "id": "char-a",
            "name": "沈知夏",
            "role": "女主",
            "goal": "拿回主动权",
            "secret": "知道合同漏洞",
            "voice": "口语化吐槽",
            "notes": "与顾承泽关系尚未缓和。",
        }]
        project["lore"] = [{
            "id": "lore-a",
            "name": "顾家董事会",
            "type": "势力",
            "description": "决定继承权归属。",
            "story_known": "",
        }]
        project["foreshadow_items"] = [{
            "id": "f-a",
            "code": "F0001",
            "name": "匿名录音",
            "status": "已埋",
            "setup_chapter": "第18章",
            "payoff_chapter": "",
            "description": "录音来源未明。",
            "revealed": "",
            "remaining_secret": "录音中的第三人身份。",
            "notes": "",
        }]
        project["chapters"] = [
            {
                "id": "old",
                "title": "旧章节",
                "text": "旧正文不应作为完整正文复制。",
                "summary": "旧章节摘要。",
                "key_facts": "旧事实。",
            },
            {
                "id": "last",
                "title": "第一卷终章",
                "text": "终章正文：沈知夏拿到录音，却没有立即播放。",
                "outline": "本章主导线：关系线\n沈知夏取得录音，暂不播放。\n结尾悬念：录音来源未明。",
                "summary": "沈知夏取得录音，顾承泽仍在门外。",
                "key_facts": "录音未播放。",
            },
            {"id": "future", "title": "未写章节", "text": "", "outline": "未写。"},
        ]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 24,
            "state_snapshot": {
                "as_of_chapter_id": "last",
                "as_of_chapter_index": 20,
                "story_time": "订婚宴当晚",
                "location": "酒店休息室",
                "character_states": [{"character_id": "char-a", "state": "掌握录音"}],
                "relationship_states": [],
                "object_states": [],
                "active_conflicts": [{"id": "C1", "text": "录音真相"}],
                "unresolved_tasks": [{"id": "T1", "text": "确认第三人身份"}],
                "notes": "",
                "updated_at": "2026-08-06 10:00:00",
            },
            "active_facts": [{"id": "fact-1", "fact": "录音尚未播放。"}],
            "fact_history": [{"id": "history-1", "fact": "旧历史"}],
            "stage_archives": [{"id": "stage-1", "summary": "第一卷阶段"}],
            "record_runtime": {"characters": {"char-a": {}}, "lore": {}, "foreshadows": {}},
            "issued_state_ids": {"objects": [], "conflicts": ["C1"], "tasks": ["T1"]},
            "update_journal": [{"chapter": 20}],
        }
        return project

    def test_handoff_source_keeps_last_written_chapter_as_anchor(self):
        source = _build_volume_handoff_source(self._source_project())

        self.assertEqual(source["last_chapter"]["title"], "第一卷终章")
        self.assertEqual(source["last_chapter"]["text"], "终章正文：沈知夏拿到录音，却没有立即播放。")
        self.assertNotIn("recent_chapters", source)
        self.assertEqual(
            [item["index"] for item in source["chapter_outlines"]],
            [2],
        )
        self.assertEqual(
            source["chapter_outlines"][0]["outline"],
            "沈知夏取得录音，暂不播放。",
        )
        self.assertNotIn("关系线", source["chapter_outlines"][0]["outline"])
        self.assertNotIn("录音来源未明", source["chapter_outlines"][0]["outline"])
        self.assertEqual(source["records"]["foreshadows"][0]["name"], "匿名录音")

    def test_handoff_budget_filters_terminal_foreshadows_without_losing_their_index(self):
        project = self._source_project()
        project["foreshadow_items"].extend([
            {
                "id": "f-done",
                "code": "F0002",
                "name": "已回收线索",
                "status": "已回收",
                "payoff_chapter": "第20章",
                "description": "已经揭示结果。",
            },
            {
                "id": "f-drop",
                "code": "F0003",
                "name": "废弃线索",
                "status": "废弃",
                "description": "不再使用。",
            },
        ])
        source = _build_volume_handoff_source(project)
        active_names = {item.get("name") for item in source["records"]["foreshadows"]}
        resolved_names = {item.get("name") for item in source["records"]["resolved_foreshadows"]}
        discarded_names = {item.get("name") for item in source["records"]["discarded_foreshadows"]}

        self.assertNotIn("已回收线索", active_names)
        self.assertIn("已回收线索", resolved_names)
        self.assertNotIn("废弃线索", active_names)
        self.assertIn("废弃线索", discarded_names)
        self.assertLessEqual(
            len(json.dumps(source, ensure_ascii=False, indent=2)),
            VOLUME_HANDOFF_SOURCE_CHAR_BUDGET,
        )

        handoff_worker = NovelVolumeHandoffWorker("", "", "", source)
        self.assertLessEqual(
            len(handoff_worker._chunk_user_text("", 1, 1)) + len(handoff_worker._analysis_prompt()),
            NOVEL_AI_CONTEXT_LIMIT,
        )
        handoff = handoff_worker._normalize_handoff({})
        self.assertNotIn("已回收线索", {item.get("name") for item in handoff["reusable_foreshadows"]})
        self.assertIn("已回收线索", {item.get("name") for item in handoff["resolved_foreshadows"]})
        framework_worker = NovelVolumeFrameworkWorker(
            "", "", "", handoff, "继续未完成主线", _volume_two_framework_template_text()
        )
        self.assertLessEqual(
            len(framework_worker._framework_user_text()),
            VOLUME_FRAMEWORK_HANDOFF_CHAR_BUDGET + 9000,
        )
        self.assertLessEqual(
            len(framework_worker._framework_user_text()) + len(framework_worker._analysis_prompt()),
            NOVEL_AI_CONTEXT_LIMIT,
        )

    def test_handoff_and_framework_prompt_stay_bounded_for_large_project_data(self):
        project = self._source_project()
        project["bible"] = "核心设定。" * 5000
        project["world_rules"] = "世界规则。" * 5000
        project["timeline"] = "阶段事件。" * 6000
        project["summary"] = "全局摘要。" * 6000
        project["chapters"] = [{
            "id": "last",
            "title": "超长终章",
            "text": "终章正文。" * 9000,
            "summary": "终章摘要。" * 1000,
            "key_facts": "终章事实。" * 1000,
        }]
        project["characters"] = [{
            "id": f"char-{index}",
            "name": f"人物{index}",
            "role": "长期角色",
            "goal": "达成长期目标。" * 80,
            "secret": "保留秘密。" * 80,
            "voice": "固定口吻。" * 50,
            "notes": "长期关系和状态。" * 80,
        } for index in range(120)]
        project["lore"] = [{
            "id": f"lore-{index}",
            "name": f"设定{index}",
            "type": "规则",
            "description": "设定说明。" * 160,
            "story_known": "已知事实。" * 80,
        } for index in range(420)]
        project["foreshadow_items"] = [{
            "id": f"f-{index}",
            "code": f"F{index:04d}",
            "name": f"伏笔{index}",
            "status": "已埋" if index % 2 else "已回收",
            "setup_chapter": "第1章",
            "payoff_chapter": "第99章" if index % 2 == 0 else "",
            "description": "伏笔说明。" * 160,
            "remaining_secret": "尚未揭开的秘密。" * 80,
        } for index in range(260)]

        source = _build_volume_handoff_source(project)
        self.assertLessEqual(
            len(json.dumps(source, ensure_ascii=False, indent=2)),
            VOLUME_HANDOFF_SOURCE_CHAR_BUDGET,
        )
        self.assertLessEqual(len(source["last_chapter"]["text"]), 24000)
        self.assertEqual(len(source["records"]["characters"]), 120)
        self.assertEqual(len(source["records"]["lore"]), 420)

        handoff_worker = NovelVolumeHandoffWorker("", "", "", source)
        self.assertLessEqual(
            len(handoff_worker._chunk_user_text("", 1, 1)) + len(handoff_worker._analysis_prompt()),
            NOVEL_AI_CONTEXT_LIMIT,
        )
        handoff = handoff_worker._normalize_handoff({})
        framework_worker = NovelVolumeFrameworkWorker(
            "", "", "", handoff, "第二卷要求。" * 5000, _volume_two_framework_template_text()
        )
        self.assertLessEqual(
            len(framework_worker._framework_user_text()),
            VOLUME_FRAMEWORK_HANDOFF_CHAR_BUDGET + 9000,
        )
        self.assertLessEqual(
            len(framework_worker._framework_user_text()) + len(framework_worker._analysis_prompt()),
            NOVEL_AI_CONTEXT_LIMIT,
        )

    def test_rebased_memory_keeps_current_state_but_resets_volume_runtime(self):
        rebased = _rebase_long_form_memory_for_volume_continuation(self._source_project())

        self.assertEqual(rebased["revision"], 0)
        self.assertEqual(rebased["state_snapshot"]["as_of_chapter_id"], "")
        self.assertEqual(rebased["state_snapshot"]["as_of_chapter_index"], 0)
        self.assertEqual(rebased["state_snapshot"]["story_time"], "订婚宴当晚")
        self.assertEqual(rebased["active_facts"][0]["fact"], "录音尚未播放。")
        self.assertEqual(rebased["fact_history"], [])
        self.assertEqual(rebased["stage_archives"], [])
        self.assertEqual(rebased["record_runtime"], {"characters": {}, "lore": {}, "foreshadows": {}})

    def test_inherited_records_keep_source_ids_for_rebased_state(self):
        source = self._source_project()
        target = _default_project()
        target["characters"] = [{"id": "new-char", "name": "沈知夏"}]
        target["lore"] = [{"id": "new-lore", "name": "顾家董事会"}]
        target["foreshadow_items"] = [{"id": "new-foreshadow", "name": "匿名录音"}]

        _inherit_continuation_record_ids(source, target)

        self.assertEqual(target["characters"][0]["id"], "char-a")
        self.assertEqual(target["lore"][0]["id"], "lore-a")
        self.assertEqual(target["foreshadow_items"][0]["id"], "f-a")

    def test_continuation_metadata_is_persistent_but_not_sent_to_body_context(self):
        normalized = _normalize_project({
            "series_continuation": {
                "schema_version": "1",
                "series_id": "series-a",
                "volume_number": 2,
                "parent_project_title": "第一卷",
                "handoff": {
                    "volume_summary": "交接摘要",
                    "resolved_foreshadows": [{"name": "已回收线索", "status": "已回收"}],
                },
            },
        })

        self.assertEqual(normalized["series_continuation"]["volume_number"], 2)
        self.assertEqual(normalized["series_continuation"]["handoff"]["volume_summary"], "交接摘要")
        self.assertEqual(
            normalized["series_continuation"]["handoff"]["resolved_foreshadows"][0]["name"],
            "已回收线索",
        )

    def test_cross_volume_anchors_are_only_sent_to_framework_and_chapter_planning(self):
        project = self._source_project()
        project["meta"]["title"] = "本卷项目"
        project["chapters"][0]["outline"] = "第一章正文方向。"
        project["series_continuation"] = {
            "volume_number": 2,
            "handoff": {
                "continuity_anchors": [{
                    "category": "生活分工",
                    "fact": "沈知夏长期负责对外事务，顾承泽长期负责家中日常安排。",
                    "source_chapters": ["第8章", "第19章"],
                }],
            },
        }

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = project
        plan_context = tab._chapter_plan_project_context(
            500000, 5000, 100, 100,
            existing_count_override=0,
            reference_start_index=1,
            reference_end_index=100,
        )
        self.assertIn("cross_volume_continuity", plan_context)
        self.assertIn("沈知夏长期负责对外事务", plan_context)

        normalized = _normalize_project(project)
        snapshot = _project_without_private_notes(normalized)
        body_context = _build_chapter_ai_context(snapshot, 0, "draft")
        summary_context = _build_chapter_ai_context(snapshot, 0, "summary")
        repair_context = _build_chapter_ai_context(snapshot, 0, "repair")
        for context in (body_context, summary_context, repair_context):
            self.assertNotIn("cross_volume_continuity", context)
            self.assertNotIn("沈知夏长期负责对外事务", context)

        framework_worker = NovelVolumeFrameworkWorker(
            "", "", "", {
                "continuity_anchors": project["series_continuation"]["handoff"]["continuity_anchors"],
                "reusable_characters": [],
                "reusable_lore": [],
                "reusable_foreshadows": [],
            },
            "本卷以关系线为主",
            _volume_two_framework_template_text(),
        )
        framework_request = framework_worker._framework_user_text()
        self.assertIn("沈知夏长期负责对外事务", framework_request)

        intent_worker = NovelVolumeIntentWorker(
            "", "", "", {"title": "本卷项目"}, "本卷以关系线为主", {
                "continuity_anchors": project["series_continuation"]["handoff"]["continuity_anchors"],
            },
        )
        self.assertNotIn("沈知夏长期负责对外事务", intent_worker._chunk_user_text("", 1, 1))
        self.assertNotIn("series_continuation", _project_without_private_notes(normalized))

    def test_volume_opening_handoff_reaches_first_plan_and_body_without_raw_private_data(self):
        project = _normalize_project({
            "meta": {"title": "第二卷", "target_words": "50"},
            "series_continuation": {
                "volume_number": 2,
                "handoff": {
                    "volume_summary": "第一卷关系停在共同准备公开评审。",
                    "ending_state": {
                        "story_time": "周五夜间",
                        "last_action": "陈景川把归还的黑色旧钢笔放进文件夹。",
                    },
                    "last_chapter": {
                        "title": "第一卷终章",
                        "summary": "双方暂时保持合作边界。",
                        "key_facts": "苏晚晴收藏公开评审页面。",
                        "text": "苏晚晴让团队准备申报。陈景川把黑色旧钢笔放进文件夹。",
                    },
                },
            },
            "chapters": [{
                "title": "第二卷第一章",
                "status": "大纲",
                "outline": "从卷末状态继续推进双方关系。",
                "draft_words": "5000",
            }],
        })
        opening = _build_volume_opening_handoff_context(project)
        self.assertIn("周五夜间", opening)
        self.assertIn("黑色旧钢笔", opening)

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = project
        snapshot = tab._ai_project_snapshot()
        self.assertNotIn("series_continuation", snapshot)
        self.assertIn("volume_opening_handoff_context", snapshot)

        plan_context = tab._chapter_plan_project_context(
            500000, 5000, 100, 100,
            existing_count_override=0,
            reference_start_index=1,
            reference_end_index=100,
        )
        self.assertIn("volume_opening_continuity", plan_context)
        self.assertIn("黑色旧钢笔", plan_context)

        body_context = _build_chapter_ai_context(snapshot, 0, "draft")
        self.assertIn("上一卷卷末承接事实", body_context)
        self.assertIn("周五夜间", body_context)
        self.assertIn("黑色旧钢笔", body_context)

    def test_project_normalization_cleans_internal_markers_and_terminal_deferred_overlap(self):
        normalized = _normalize_project({
            "characters": [{"name": "苏晚晴", "notes": "补充：AI 分析候选\n关系状态有效。"}],
            "lore": [{"name": "公开评审", "description": "AI 分析候选\n正常规则。"}],
            "foreshadow_items": [{
                "name": "关系选择",
                "description": "AI 分析候选\n判断依据：双方仍未选择。",
            }],
            "series_continuation": {
                "volume_number": 2,
                "handoff": {
                    "reusable_characters": [{"name": "苏晚晴", "notes": "AI 分析候选\n卷末状态。"}],
                    "deferred_foreshadows": [{"code": "F0001", "name": "旧线", "status": "已回收"}],
                    "resolved_foreshadows": [{"code": "F0001", "name": "旧线", "status": "已回收"}],
                },
            },
        })

        self.assertNotIn("AI 分析候选", repr(normalized))
        self.assertIn("判断依据：双方仍未选择。", normalized["foreshadow_items"][0]["description"])
        handoff = normalized["series_continuation"]["handoff"]
        self.assertEqual(handoff["deferred_foreshadows"], [])
        self.assertEqual(handoff["resolved_foreshadows"][0]["name"], "旧线")

    def test_handoff_and_framework_workers_preserve_continuity_records_without_api(self):
        source_project = self._source_project()
        source = _build_volume_handoff_source(source_project)
        catalog = _build_volume_handoff_record_catalog(source_project)
        handoff_worker = NovelVolumeHandoffWorker("", "", "", source, catalog)
        incomplete_handoff = handoff_worker._normalize_handoff({
            "foreshadow_selection_version": 2,
            "reusable_characters": [],
            "reusable_lore": [],
            "reusable_foreshadows": [{"name": "匿名录音"}],
        })
        self.assertEqual(incomplete_handoff["reusable_characters"][0]["name"], "沈知夏")
        self.assertEqual(incomplete_handoff["reusable_lore"], [])
        self.assertEqual(incomplete_handoff["reusable_foreshadows"][0]["name"], "匿名录音")
        handoff = handoff_worker._normalize_handoff({
            "volume_summary": "第一卷结束时录音尚未播放。",
            "open_threads": ["确认录音中的第三人"],
            "reusable_characters": source["records"]["characters"],
            "reusable_lore": source["records"]["lore"],
            "reusable_foreshadows": source["records"]["foreshadows"],
        })
        framework_worker = NovelVolumeFrameworkWorker(
            "", "", "", handoff, "第二卷加强反转", _volume_two_framework_template_text()
        )
        framework = framework_worker._normalize_framework_result({
            "meta": {"title": "第一卷 第2卷"},
            "project_materials": {"bible": "续作圣经", "world_rules": "原规则继续有效"},
            "characters": [],
            "lore": [],
            "foreshadows": [{"name": "匿名录音"}],
            "chapter_plan": {
                "summary": "第二卷主线",
                "stages": [],
                "chapters": [{"title": "不应提前生成", "outline": "不应保留"}],
            },
        })

        self.assertEqual(handoff["last_chapter"]["text"], source["last_chapter"]["text"])
        framework_request = framework_worker._framework_user_text()
        self.assertIn(source["last_chapter"]["text"], framework_request)
        self.assertIn("上一卷交接资料（含卷末最后一章正文）", framework_request)
        self.assertEqual(framework["chapter_plan"]["chapters"], [])
        self.assertEqual(framework["characters"][0]["name"], "沈知夏")
        self.assertEqual(framework["foreshadows"][0]["name"], "匿名录音")
        self.assertEqual(framework["foreshadows"][0]["code"], "F0001")

    def test_handoff_keeps_explicit_core_family_and_friend_anchors_when_model_omits_them(self):
        project = self._source_project()
        project["characters"] = [
            {"name": "沈知夏", "role": "女主", "goal": "查清真相"},
            {"name": "顾沉", "role": "男主", "goal": "保护底线"},
            {"name": "沈母", "role": "主角的母亲", "goal": "维护家庭"},
            {"name": "谢弥", "role": "长期朋友、闺蜜", "goal": "支持朋友"},
            {"name": "陆衡", "role": "顾沉心腹", "goal": "稳定公司"},
            {"name": "秦越", "role": "核心盟友", "goal": "共同守住底线"},
            {"name": "周临", "role": "重要旧关系人物", "goal": "保持旧约"},
            {"name": "临时接待员", "role": "会场工作人员", "goal": "完成一次接待"},
        ]
        source = _build_volume_handoff_source(project)
        catalog = _build_volume_handoff_record_catalog(project)
        worker = NovelVolumeHandoffWorker("", "", "", source, catalog)

        handoff = worker._normalize_handoff({
            "reusable_characters": [{"name": "沈知夏"}],
        })
        names = [item["name"] for item in handoff["reusable_characters"]]

        self.assertEqual(
            names,
            ["顾沉", "沈母", "谢弥", "陆衡", "秦越", "周临", "沈知夏"],
        )
        self.assertNotIn("临时接待员", names)

    def test_framework_does_not_promote_unselected_handoff_foreshadows(self):
        worker = NovelVolumeFrameworkWorker(
            "", "", "", {
                "reusable_characters": [],
                "reusable_lore": [],
                "reusable_foreshadows": [{
                    "code": "F0001",
                    "name": "第一卷旧案",
                    "status": "已埋",
                    "description": "上一卷尚可追溯，但第二卷主线没有选中。",
                }],
            },
            "第二卷以感情线为主",
            _volume_two_framework_template_text(),
        )

        framework = worker._normalize_framework_result({
            "characters": [],
            "lore": [],
            "foreshadows": [],
            "project_materials": {},
            "chapter_plan": {"chapters": []},
        })

        self.assertEqual(framework["foreshadows"], [])

    def test_handoff_enriches_selected_records_and_keeps_all_geography(self):
        project = self._source_project()
        project["characters"].append({
            "id": "char-b",
            "name": "一次性宾客",
            "role": "路人",
            "goal": "离场",
            "secret": "无",
            "voice": "无",
            "notes": "第一卷已经离场。",
        })
        project["lore"].append({
            "id": "lore-b",
            "name": "旧宴会厅",
            "type": "地点",
            "description": "第一卷一次性场景。",
        })
        source = _build_volume_handoff_source(project)
        worker = NovelVolumeHandoffWorker(
            "", "", "", source, _build_volume_handoff_record_catalog(project)
        )

        handoff = worker._normalize_handoff({
            "reusable_characters": [{"name": "沈知夏", "goal": "确认录音真相"}],
            "reusable_lore": [{"name": "顾家董事会"}],
            "reusable_foreshadows": [{"name": "匿名录音"}],
        })

        self.assertEqual([item["name"] for item in handoff["reusable_characters"]], ["沈知夏"])
        self.assertEqual(handoff["reusable_characters"][0]["secret"], "知道合同漏洞")
        self.assertEqual(handoff["reusable_characters"][0]["voice"], "口语化吐槽")
        self.assertEqual(handoff["reusable_characters"][0]["goal"], "确认录音真相")
        lore_by_name = {item["name"]: item for item in handoff["reusable_lore"]}
        self.assertEqual(set(lore_by_name), {"顾家董事会", "旧宴会厅"})
        self.assertEqual(lore_by_name["顾家董事会"]["description"], "决定继承权归属。")
        self.assertNotIn("一次性宾客", {item["name"] for item in handoff["reusable_characters"]})
        self.assertEqual(lore_by_name["旧宴会厅"]["type"], "地点")
        self.assertEqual([item["name"] for item in handoff["reusable_foreshadows"]], ["匿名录音"])
        self.assertEqual(handoff["reusable_foreshadows"][0]["code"], "F0001")

    def test_deferred_foreshadows_stay_out_of_second_volume_framework(self):
        project = self._source_project()
        project["foreshadow_items"].append({
            "id": "f-b",
            "code": "F0002",
            "name": "第一卷旧线",
            "status": "已埋",
            "description": "第一卷阶段性疑问，第二卷不要求继续。",
        })
        source = _build_volume_handoff_source(project)
        worker = NovelVolumeHandoffWorker(
            "", "", "", source, _build_volume_handoff_record_catalog(project)
        )
        handoff = worker._normalize_handoff({
            "foreshadow_selection_version": 2,
            "reusable_foreshadows": [{"code": "F0001", "name": "匿名录音"}],
            "deferred_foreshadows": [{"code": "F0002", "name": "第一卷旧线"}],
        })

        self.assertEqual([item["name"] for item in handoff["reusable_foreshadows"]], ["匿名录音"])
        self.assertEqual([item["name"] for item in handoff["deferred_foreshadows"]], ["第一卷旧线"])

        framework_worker = NovelVolumeFrameworkWorker(
            "", "", "", handoff, "继续主线", _volume_two_framework_template_text()
        )
        request = framework_worker._framework_user_text()
        self.assertNotIn("第一卷旧线", request)
        framework = framework_worker._normalize_framework_result({
            "foreshadows": [
                {"code": "F0002", "name": "第一卷旧线", "status": "已埋"},
                {"code": "F0001", "name": "匿名录音", "status": "已埋"},
                {"code": "F0003", "name": "第二卷新线", "status": "已埋"},
            ],
            "chapter_plan": {"chapters": []},
        })
        self.assertEqual(
            [item["name"] for item in framework["foreshadows"]],
            ["匿名录音", "第二卷新线"],
        )

    def test_framework_combines_inherited_and_second_volume_materials(self):
        handoff = {
            "inherited_materials": {
                "bible": "第一卷具体剧情圣经。",
                "world_rules": "第一卷阶段性办案流程。",
            },
            "reusable_characters": [],
            "reusable_lore": [],
            "reusable_foreshadows": [],
        }
        worker = NovelVolumeFrameworkWorker(
            "", "", "", handoff, "第二卷转向关系主线", _volume_two_framework_template_text()
        )

        framework = worker._normalize_framework_result({
            "project_materials": {
                "bible": "第二卷关系主线圣经。",
                "world_rules": "第二卷仍有效的基础规则。",
            }
        })

        self.assertIn("第一卷具体剧情圣经。", framework["project_materials"]["bible"])
        self.assertIn("第二卷关系主线圣经。", framework["project_materials"]["bible"])
        self.assertIn("第一卷阶段性办案流程。", framework["project_materials"]["world_rules"])
        self.assertIn("第二卷仍有效的基础规则。", framework["project_materials"]["world_rules"])

    def test_oversized_last_chapter_keeps_ending_anchor(self):
        project = self._source_project()
        project["chapters"] = [{
            "id": "last",
            "title": "超长终章",
            "text": "开头场景。\n" + ("中段发展。\n" * 6000) + "卷末最后动作：沈知夏按下播放键。",
            "summary": "卷末准备播放录音。",
            "key_facts": "播放键已经按下。",
        }]

        source = _build_volume_handoff_source(project)

        self.assertLessEqual(len(source["last_chapter"]["text"]), 24000)
        self.assertIn("开头场景", source["last_chapter"]["text"])
        self.assertIn("卷末最后动作：沈知夏按下播放键", source["last_chapter"]["text"])

    def test_250_chapter_planning_batch_includes_continuity_inside_hard_context_cap(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        stages = []
        for stage_index in range(1, 11):
            start = (stage_index - 1) * 25 + 1
            stages.append({
                "id": f"S{stage_index:02d}",
                "name": f"阶段{stage_index}",
                "start_chapter": start,
                "end_chapter": start + 24,
                "events": [
                    {
                        "id": f"S{stage_index:02d}-E{event_index:02d}",
                        "order": event_index,
                        "text": f"规划事件{stage_index}-{event_index}。" * 80,
                    }
                    for event_index in range(1, 26)
                ],
            })
        tab.current_project = {
            "meta": {
                "title": "250章压力测试",
                "genre": "女频现代言情",
                "target_words": "50万",
            },
            "bible": "圣经事实。" * 3000,
            "world_rules": "世界规则。" * 3000,
            "timeline": "时间线事件。" * 4000,
            "summary": "全局摘要。" * 4000,
            "characters": [
                {"name": f"人物{index}", "role": "长期角色", "goal": "长期目标。" * 20}
                for index in range(120)
            ],
            "lore": [
                {"name": f"设定{index}", "type": "规则", "description": "设定说明。" * 60}
                for index in range(420)
            ],
            "chapters": [],
            "imported_chapter_plan_reference": {
                "summary": "原始框架总览。" * 500,
                "chapters": [
                    {"index": index, "title": f"原始标题{index}", "outline": "明确章节方向。" * 30}
                    for index in range(1, 251)
                ],
                "stages": stages,
            },
        }
        generated = [
            {
                "index": index,
                "title": f"已规划章节{index}",
                "narrative_stage": "主线扩展阶段",
                "source_stage": f"阶段{((index - 1) // 25) + 1}",
                "dominant_line": "主线推进。" * 5,
                "outline": "上一批详细提纲。" * 30,
                "characters": [f"人物{index % 20}"],
                "settings": [f"设定{index % 20}"],
                "ending_hook": "新的局面。" * 10,
                "forbidden": "不要提前揭晓。" * 5,
                "source_event_ids": [f"S{((index - 1) // 25) + 1:02d}-E{((index - 1) % 25) + 1:02d}"],
            }
            for index in range(1, 211)
        ]
        state = {
            "target_words": 500000,
            "average_chapter_words": 2000,
            "total_chapter_count": 250,
            "existing_chapter_count": 0,
            "master_plan": {
                "summary": "全书总规划。" * 300,
                "arcs": [
                    {
                        "name": f"阶段{index}",
                        "start_chapter": (index - 1) * 25 + 1,
                        "end_chapter": index * 25,
                        "dominant_line": "阶段主导线。" * 20,
                        "goal": "阶段目标。" * 20,
                    }
                    for index in range(1, 11)
                ],
            },
            "chapters": generated,
        }

        master_context = tab._chapter_plan_project_context(
            500000,
            2000,
            250,
            250,
            reference_start_index=1,
            reference_end_index=250,
            context_mode="master",
        )
        batch_context = tab._chapter_plan_batch_context(state, 30)
        batch_worker = NovelChapterPlanWorker(
            "", "", "", batch_context, 500000, 2000, 30, 250, 0, batch_number=8, total_batches=9
        )

        self.assertLessEqual(len(master_context), _CHAPTER_PLAN_CONTEXT_CHAR_BUDGET)
        self.assertLessEqual(len(batch_context), _CHAPTER_PLAN_CONTEXT_CHAR_BUDGET)
        self.assertLessEqual(
            len(batch_context) + len(batch_worker._analysis_prompt()),
            NOVEL_AI_CONTEXT_LIMIT,
        )
        batch_payload = json.loads(batch_context[batch_context.find("{"):])
        self.assertEqual(
            batch_payload["batch_continuity"]["required_absolute_range"],
            [211, 240],
        )
        self.assertIn('"previous_batch_tail"', batch_context)
        self.assertIn('"planned_chapter_ledger"', batch_context)
        self.assertIn("阶段9", batch_context)
        ledger = batch_payload["batch_continuity"]["planned_chapter_ledger"]
        self.assertEqual(len(ledger), 210)
        self.assertEqual(ledger[0]["index"], 1)
        self.assertEqual(ledger[-1]["index"], 210)
        self.assertEqual(ledger[0]["title"], "已规划章节1")
        self.assertEqual(ledger[-1]["title"], "已规划章节210")


if __name__ == "__main__":
    unittest.main()
