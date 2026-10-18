import json
import hashlib
import os
import unittest
import tempfile
from datetime import datetime, timezone
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QPlainTextEdit

from gpt_desktop.core import load_json_file, save_json_file
from gpt_desktop.novel_import import Document as DocxDocument, WD_ALIGN_PARAGRAPH, _write_docx_text, _extract_structured_framework_chapter_plan, _extract_framework_planning_parameters
from gpt_desktop.novel_storage import list_project_summaries
from gpt_desktop.novel_utils import (
    CHAPTER_ANALYSIS_HASH_VERSION,
    FRAMEWORK_IMPORT_TYPE,
    STYLE_CARD_CACHE_VERSION,
    STYLE_SHEET_CACHE_VERSION,
    _append_text_without_duplicate_overlap,
    _build_search_result_text,
    _chapter_analysis_diff_ratio,
    _chapter_analysis_hash,
    _chapter_analysis_legacy_hash,
    _chapter_list_text,
    _update_chapter_analysis_status_cache,
    _character_list_text,
    _compact_chapter_key_facts_text,
    _compact_chapter_summary_text,
    _infer_linked_character_names,
    _mark_chapters_analyzed,
    _new_chapter,
    _new_foreshadow,
    _normalize_project,
    _project_without_private_notes,
    _project_list_text,
    _project_meta_text,
    _local_split_chapter_title,
    _split_manuscript_into_target_chapters,
)
from gpt_desktop.novel_writing_tab import (
    ChapterPlanFoundationDialog,
    NovelWritingTab,
    _numbered_export_chapter_title,
)
from gpt_desktop.workers import EdgeTTSWorker, _parse_edge_tts_server_date


class NovelWritingStateTests(unittest.TestCase):
    def test_first_character_can_use_style_favorite_button(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "characters": [{"style_favorite_id": ""}],
        }
        tab.current_character_index = 0
        tab.char_style_favorite_btn = _FakeButton()

        tab._update_character_style_favorite_button()

        self.assertTrue(tab.char_style_favorite_btn.enabled)
        self.assertEqual(tab.char_style_favorite_btn.text, "收藏为主角风格")

    def test_removed_character_style_is_not_recreated_when_card_is_saved(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_character_index = 0
        tab.current_project = {
            "meta": {"title": "测试小说"},
            "characters": [{"style_favorite_id": "removed-style"}],
        }
        for field, value in (
            ("name", "主角"), ("role", "学生"), ("goal", "完成学业"),
            ("secret", "秘密"), ("personality", "谨慎"), ("voice", "自然"),
        ):
            setattr(tab, f"char_{field}", _FakeLineEdit(value))
        tab.char_notes = _FakePlainTextEdit("长期备注")
        tab.char_style_favorite_btn = _FakeButton()
        tab._refresh_character_item = lambda _index: None

        with patch("gpt_desktop.novel_writing_tab.load_character_style_library", return_value=[]), \
            patch("gpt_desktop.novel_writing_tab.upsert_character_style") as upsert:
            tab._update_character_style_favorite_button()
            self.assertEqual(tab.char_style_favorite_btn.text, "收藏为主角风格")
            tab._save_character_at_index(0)

        upsert.assert_not_called()
        char = tab.current_project["characters"][0]
        self.assertEqual(char["style_favorite_id"], "")
        self.assertEqual(char["personality"], "谨慎")
        self.assertEqual(char["voice"], "自然")
        self.assertEqual(char["notes"], "长期备注")

    @staticmethod
    def _imported_framework_fixture():
        lines = [
            "故事核心", "冷秋白从病房醒来，一边寻找老药，一边为来求医的人治病。",
            "一、圣经", "主线矛盾", "他想找回丢失的千年。", "男主三不医原则", "心术不正不医。",
            "四、阶段规划", "全书计划约50万字，100章，每章约5000字。",
        ]
        for stage in range(1, 6):
            lines.extend([
                f"第{stage}阶段：第{stage}次求医", f"章节：第{(stage-1)*20+1}—{stage*20}章",
                "字数：约10万字", "主要剧情",
            ])
            lines.extend(f"{event}. 冷秋白在第{stage}次求医中见到了第{event}位病人。" for event in range(1, 21))
            if stage == 5:
                lines.extend(["结尾场景", "神秘病人睁开眼睛，问他是否还记得那扇门。", "第一部完。"])
        lines.extend(["五、整体节奏", "感情节奏", "81—100章：两人被危机打断。", "六、前十章建议标题"])
        lines.extend(f"第{index}章：病房来客{index}" for index in range(1, 11))
        return "\n".join(lines)

    def _imported_planning_tab(self, text=None):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        text = self._imported_framework_fixture() if text is None else text
        tab.current_project = _normalize_project({
            "meta": {"title": "白衣医圣", "target_words": "50", "genre": "都市神医", "style": "轻松爽文"},
            "imported_framework_source": {"text": text, "source_title": "医圣框架", "source_label": "Word"},
        })
        tab.config = {"novel": {"chapter_plan_average_words": 5000}}
        tab.writing_worker = None
        tab.chapter_plan_worker = None
        provider = {"base_url": "http://example.test", "api_key": "key"}
        tab._current_novel_ai_selection = lambda: (provider, "model", "")
        tab._chapter_plan_provider = provider
        tab._chapter_plan_model = "model"
        tab._chapter_plan_auto_active = True
        tab._chapter_plan_sequence_token = 1
        tab._provider_proxy_mode = lambda _provider: "不使用代理"
        tab._flush_current_editors = lambda: None
        tab._set_chapter_ai_actions_enabled = lambda _enabled: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab._note_project_dirty = lambda: None
        tab._log_novel_diagnostic = lambda *args, **kwargs: None
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_plan_apply_btn = _FakeButton()
        tab._framework_test_status = []
        tab.set_status_tip = tab._framework_test_status.append
        return tab

    @staticmethod
    def _mock_complete_framework_ai_analysis(tab):
        text = tab.current_project["imported_framework_source"]["text"]
        tab.current_project["imported_framework_source"]["sha256"] = hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()
        plan = _extract_structured_framework_chapter_plan(text)
        tab._store_imported_chapter_plan_reference(plan)
        tab.current_project["imported_framework_analysis"] = {
            "source_hash": hashlib.sha256(text.strip().encode("utf-8")).hexdigest(),
            "foundation_mode": "reuse", "missing_fields": [],
            "planning_parameters": _extract_framework_planning_parameters(text),
            "foundation": {"summary": "原文里的完整故事", "core_mainline": "他走进一扇扇旧门。",
                           "ending_promise": "第七门打开后，故事仍未结束。",
                           "narrative_strategy_profile": {"genre_world": "都市", "primary_story_engine": "门后的旧名字让众人重新相认。"},
                           "arcs": [{"name": stage["name"], "source_stage": stage["name"],
                                     "start_chapter": stage["start_chapter"], "end_chapter": stage["end_chapter"],
                                     "end_state": stage.get("summary", "") or stage["events"][-1]["text"]}
                                    for stage in plan["stages"]]},
        }

    def test_imported_detailed_framework_click_skips_master_and_uses_framework_words(self):
        class BatchWorker:
            instances = []
            def __init__(self, *args, **kwargs):
                self.args, self.kwargs = args, kwargs
                self.result_ready, self.failed, self.finished = _FakeSignal(), _FakeSignal(), _FakeSignal()
                self.progress = _FakeSignal()
                self.diagnostics = {}
                BatchWorker.instances.append(self)
            def _analysis_prompt(self):
                return "测试章节提示"
            def start(self):
                self.started = True

        tab = self._imported_planning_tab()
        self._mock_complete_framework_ai_analysis(tab)
        with patch("gpt_desktop.novel_writing_tab.NovelChapterPlanWorker", BatchWorker), \
             patch("gpt_desktop.novel_writing_tab.QInputDialog.getInt") as word_dialog:
            tab.generate_chapter_plan()
        word_dialog.assert_not_called()
        state = tab.current_project["chapter_plan_generation_state"]
        self.assertEqual((state["target_words"], state["average_chapter_words"], state["total_chapter_count"]),
                         (500000, 5000, 100))
        self.assertEqual(tab.config["novel"]["chapter_plan_average_words"], 5000)
        self.assertTrue(state["profile_confirmed"])
        self.assertEqual(state["master_plan"]["source"], "imported_framework")
        self.assertEqual(len(state["master_plan"]["arcs"]), 5)
        self.assertTrue(state["master_plan"]["ending_promise"])
        self.assertEqual(tab._chapter_plan_request_kind, "batch")
        worker = BatchWorker.instances[0]
        self.assertEqual(worker.args[6], 20)
        self.assertEqual(worker.kwargs["total_batches"], 5)
        self.assertTrue(worker.started)
        self.assertIn("已读取原框架", tab._framework_test_status[-1])
        reference = tab.current_project["imported_chapter_plan_reference"]
        self.assertEqual([len(stage["events"]) for stage in reference["stages"]], [20] * 5)
        self.assertEqual(reference["chapters"][0]["title"], "病房来客1")
        self.assertEqual(reference["chapters"][0]["outline"], "")
        self.assertEqual(tab._chapter_plan_event_assignment_error([], [{"index": 25, "source_event_ids": []}])[:4], "阶段S0")

    def test_creation_wizard_foundation_survives_state_rebuild_without_master_call(self):
        class BatchWorker:
            instances = []

            def __init__(self, *args, **kwargs):
                self.args, self.kwargs = args, kwargs
                self.result_ready = _FakeSignal()
                self.failed = _FakeSignal()
                self.finished = _FakeSignal()
                self.progress = _FakeSignal()
                self.diagnostics = {}
                BatchWorker.instances.append(self)

            def _analysis_prompt(self):
                return "章节规划提示"

            def start(self):
                self.started = True

        tab = self._imported_planning_tab("")
        tab.current_project = {
            "meta": {
                "title": "向导项目",
                "genre": "都市逆袭",
                "style": "自然网文",
                "premise": "主角在旧城重新开始。",
            },
            "creation_framework": {
                "source": "creation_wizard",
                "novel_name": "向导项目",
                "premise": {
                    "title": "向导项目",
                    "synopsis": "主角在旧城重新开始。",
                    "main_line": "他要把失去的生活一点点夺回来。",
                },
                "stage_plan": [{
                    "name": "旧城开局",
                    "start_chapter": 1,
                    "end_chapter": 20,
                    "summary": "主角回到旧城，先面对生活和人情上的阻力。",
                    "main_conflict": "旧关系和现实压力逼他作出选择。",
                }],
                "total_words": 40000,
                "average_chapter_words": 2000,
                "chapter_plan_foundation": {
                    "summary": "主角从旧城开局，逐步夺回生活。",
                    "core_mainline": "他要把失去的生活一点点夺回来。",
                    "ending_promise": "旧城的人和事留下新的选择。",
                    "target_words": 40000,
                    "average_chapter_words": 2000,
                    "total_chapter_count": 20,
                    "existing_chapter_count": 0,
                    "narrative_strategy_profile": {
                        "genre_world": "都市逆袭",
                        "primary_story_engine": "现实阻力逼出人物选择。",
                    },
                    "arcs": [{
                        "name": "旧城开局",
                        "start_chapter": 1,
                        "end_chapter": 20,
                        "source_stage": "旧城开局",
                        "dominant_line": "旧关系和现实压力逼他作出选择。",
                        "end_state": "主角站稳脚跟。",
                    }],
                },
            },
            "bible": "小说圣经：主角要夺回失去的生活。",
            "world_rules": "世界规则：现实城市，人物要承担选择的后果。",
            "summary": "主角在旧城重新开始。",
            "timeline": "阶段规划：旧城开局。",
            "characters": [{"name": "主角", "role": "回到旧城的人", "goal": "夺回生活"}],
            "lore": [{"name": "旧城", "type": "地点", "description": "故事反复发生的城市"}],
            "foreshadow_items": [{
                "name": "旧钥匙",
                "type": "物件",
                "status": "未埋",
                "description": "主角手里的旧钥匙会牵出过去。",
            }],
            "chapters": [],
        }
        state = {
            "version": 3,
            "status": "pending",
            "target_words": 40000,
            "average_chapter_words": 2000,
            "total_chapter_count": 20,
            "existing_chapter_count": 0,
            "requested_chapter_count": 20,
            "batch_size": 50,
            "master_plan": {},
            "chapters": [],
            "profile_confirmed": False,
        }

        with patch("gpt_desktop.novel_writing_tab.NovelChapterPlanWorker", BatchWorker):
            tab._start_chapter_plan_worker_for_state(deepcopy(state))

        self.assertEqual(tab._chapter_plan_request_kind, "batch")
        self.assertTrue(BatchWorker.instances[-1].started)
        restored = tab.current_project["chapter_plan_generation_state"]
        self.assertEqual(restored["master_plan"]["source"], "creation_wizard")
        context = tab._chapter_plan_batch_context(restored, 20)
        self.assertIn("旧城开局", context)
        self.assertIn("小说圣经：主角要夺回失去的生活。", context)
        self.assertIn("世界规则：现实城市", context)
        self.assertIn("旧钥匙", context)

    def test_imported_foundation_and_reference_survive_storage_roundtrip(self):
        tab = self._imported_planning_tab()
        self._mock_complete_framework_ai_analysis(tab)
        state = {"target_words": 500000, "average_chapter_words": 5000, "total_chapter_count": 100}
        master = tab._chapter_plan_imported_foundation(state)
        tab.current_project["chapter_plan_foundation"] = master
        tab.current_project["chapter_plan_generation_state"] = {
            **state, "version": 3, "status": "pending", "master_plan": master, "profile_confirmed": True,
            "chapters": [], "existing_chapter_count": 0, "requested_chapter_count": 100,
        }
        restored = _normalize_project(json.loads(json.dumps(tab.current_project, ensure_ascii=False)))
        self.assertEqual(restored["chapter_plan_foundation"]["source"], "imported_framework")
        self.assertEqual(restored["chapter_plan_foundation"]["source_hash"], tab._framework_import_source()["sha256"])
        self.assertEqual(len(restored["imported_chapter_plan_reference"]["stages"]), 5)
        self.assertTrue(restored["chapter_plan_generation_state"]["profile_confirmed"])

    def test_framework_recovery_does_not_rewrite_existing_event_ledger(self):
        tab = self._imported_planning_tab()
        tab.current_project["chapter_plan_generation_state"] = {"chapters": [{"index": 1, "source_event_ids": ["S01-E01"]}]}
        tab._chapter_plan_restore_imported_reference()
        self.assertEqual(tab.current_project["imported_chapter_plan_reference"], {})

    def test_framework_recovery_preserves_existing_structured_reference(self):
        tab = self._imported_planning_tab()
        reference = {"stages": [{"id": "S01", "name": "用户原有阶段"}]}
        tab.current_project["imported_chapter_plan_reference"] = deepcopy(reference)
        tab._chapter_plan_restore_imported_reference()
        self.assertEqual(tab.current_project["imported_chapter_plan_reference"], reference)

    def test_reused_regenerated_foundation_keeps_explicit_source_choice(self):
        tab = self._imported_planning_tab("")
        saved = {"target_words": 500000, "average_chapter_words": 3000,
                 "total_chapter_count": 100, "existing_chapter_count": 0,
                 "profile_confirmed": True, "force_master_regeneration": True,
                 "master_plan": {"summary": "用户重新选择的方向"}}
        state = {**saved, "average_chapter_words": 5000, "master_plan": {}, "profile_confirmed": False}
        state.pop("force_master_regeneration")
        tab._chapter_plan_reuse_foundation(state, saved)
        self.assertTrue(state["force_master_regeneration"])
        self.assertEqual(state["master_plan"]["summary"], "用户重新选择的方向")

    def test_saved_project_chapter_words_win_over_global_default(self):
        tab = self._imported_planning_tab("")
        tab.current_project["chapter_plan_generation_state"] = {"average_chapter_words": 2000}
        self.assertEqual(tab._chapter_plan_default_average_words(), 2000)
        tab.current_project["chapter_plan_generation_state"] = {}
        self.assertEqual(tab._chapter_plan_default_average_words(), 5000)

    def test_average_word_change_keeps_confirmed_foundation_when_ranges_unchanged(self):
        tab = self._imported_planning_tab("")
        old = {"target_words": 500000, "average_chapter_words": 3000, "total_chapter_count": 250,
               "existing_chapter_count": 0, "profile_confirmed": True,
               "master_plan": {"summary": "用户确认的故事简介", "arcs": [{"name": "开局", "start_chapter": 1, "end_chapter": 250}],
                               "narrative_strategy_profile": {"genre_world": "都市"}}}
        new = {**old, "average_chapter_words": 2000, "master_plan": {}, "profile_confirmed": False}
        tab._chapter_plan_reuse_foundation(new, old)
        self.assertTrue(new["profile_confirmed"])
        self.assertEqual(new["master_plan"]["summary"], "用户确认的故事简介")
        self.assertEqual(new["master_plan"]["average_chapter_words"], 2000)
        self.assertEqual(old["average_chapter_words"], 3000)
        for key in ("target_words", "total_chapter_count", "existing_chapter_count"):
            changed = {**new, key: new.get(key, 0) + 1, "master_plan": {}, "profile_confirmed": False}
            tab._chapter_plan_reuse_foundation(changed, old)
            self.assertEqual(changed["master_plan"], {})

    def test_complete_original_outline_stays_available_for_same_call_reuse(self):
        original = "雨夜里，冷秋白被敲门声惊醒。老人捧着药盒求他救命，他发现盒底藏着旧日圣印。神魂仍在医圣境，肉身却只是残躯。"
        tab = self._imported_planning_tab("第一阶段：夜访\n章节：第1—1章\n第1章《敲门的人》" + original)
        tab._chapter_plan_restore_imported_reference()
        explicit = tab.current_project["imported_chapter_plan_reference"]["chapters"][0]
        self.assertEqual(explicit["outline"], original)
        output = tab._chapter_plan_apply_imported_outline({"outline": "模型新提纲", "outline_mode": "use_imported"}, explicit)
        self.assertEqual(output["outline"], original)
        output = tab._chapter_plan_apply_imported_outline({"outline": "模型新提纲", "outline_mode": "generate"}, explicit)
        self.assertEqual(output["outline"], "模型新提纲")

    @staticmethod
    def _number_only_full_framework_fixture():
        lines = [
            "正文规划为五个阶段、100章，约50万字。",
            "故事核心：江夜在觉醒日找回力量，想让街坊继续过安稳日子。",
            "一、圣经", "主线矛盾：江夜不愿再替旧王座发号施令。",
            "结局方向：第七门打开，门后传来江夜自己的声音，故事停在这里。",
        ]
        numerals = ["一", "二", "三", "四", "五"]
        for stage, name in enumerate(numerals, 1):
            lines.extend([
                f"第{name}阶段：城门{stage}（第{(stage-1)*20+1:03d}-{stage*20:03d}章，约十万字）",
                f"江夜在城门{stage}遇到了从前看不起他的邻居。",
                f"第{name}阶段落点：第{stage}扇门里的声音已经认出了他。",
            ])
        lines.extend(["二、主要人物", "姓名：江夜"])
        for stage, name in enumerate(numerals, 1):
            lines.extend([f"《天门开时我无敌》第{name}阶段：城门{stage}", f"第{name}阶段：城门{stage}",
                          "每章约五千字正文容量，以下为可直接扩写的故事提纲。"])
            for index in range((stage-1)*20+1, stage*20+1):
                lines.extend([f"第{index:03d}章", f"第{index}次天门响起时，江夜站在街口。邻居想关门，他把手里的钥匙递给林晚照。门后喊出了他的旧名字，实际仍是无极境。"])
        return "\n".join(lines)

    def test_active_framework_resume_recovers_100_outlines_and_skips_old_master(self):
        class BatchWorker:
            instances = []
            def __init__(self, *args, **kwargs):
                self.args, self.kwargs = args, kwargs
                self.result_ready, self.failed, self.finished, self.progress = (_FakeSignal() for _ in range(4))
                self.diagnostics = {}
                BatchWorker.instances.append(self)
            def _analysis_prompt(self):
                return "章节提示"
            def start(self):
                self.started = True

        tab = self._imported_planning_tab(self._number_only_full_framework_fixture())
        tab.config["novel"]["chapter_plan_average_words"] = 2000
        tab.current_project["imported_chapter_plan_reference"] = {"stages": [{
            "id": f"S{i:02d}", "name": f"城门{i}", "start_chapter": (i-1)*20+1, "end_chapter": i*20,
            "events": [{"id": f"S{i:02d}-E01", "order": 1, "text": "旧的简略节点。"}],
        } for i in range(1, 6)]}
        tab.current_project["chapter_plan_generation_state"] = {
            "version": 1, "status": "failed", "target_words": 500000,
            "average_chapter_words": 5000, "total_chapter_count": 100,
            "existing_chapter_count": 0, "requested_chapter_count": 100,
            "chapters": [], "profile_confirmed": True,
            "master_plan": {"summary": "旧AI走向，不该代替原文。", "arcs": []},
        }
        self._mock_complete_framework_ai_analysis(tab)
        with patch("gpt_desktop.novel_writing_tab.NovelChapterPlanWorker", BatchWorker), \
             patch("gpt_desktop.novel_writing_tab.QInputDialog.getInt", side_effect=AssertionError("原文有字数，不应再弹窗")), \
             patch("gpt_desktop.novel_writing_tab.save_config") as save:
            tab.generate_chapter_plan()
        save.assert_not_called()
        state = tab.current_project["chapter_plan_generation_state"]
        self.assertEqual((state["average_chapter_words"], state["total_chapter_count"]), (5000, 100))
        self.assertEqual(state["master_plan"]["source"], "imported_framework")
        self.assertIn("第七门", state["master_plan"]["ending_promise"])
        self.assertEqual(tab.config["novel"]["chapter_plan_average_words"], 2000)
        self.assertEqual(BatchWorker.instances[0].args[6], 20)
        self.assertEqual(BatchWorker.instances[0].kwargs["total_batches"], 5)
        reference = tab.current_project["imported_chapter_plan_reference"]
        self.assertEqual(len(reference["chapters"]), 100)
        self.assertEqual([len(stage["events"]) for stage in reference["stages"]], [20]*5)
        self.assertEqual(reference["chapters"][0]["title"], "")
        original = reference["chapters"][0]["outline"]
        self.assertIn("实际仍是无极境", original)
        result = tab._chapter_plan_apply_imported_outline(
            {"title": "灰石亮起", "outline": "AI另写的内容", "outline_mode": "use_imported"}, reference["chapters"][0])
        self.assertEqual(result["outline"], original)
        self.assertEqual(result["title"], "灰石亮起")
        restored = _normalize_project(json.loads(json.dumps(tab.current_project, ensure_ascii=False)))
        self.assertEqual(restored["imported_chapter_plan_reference"]["chapters"][0]["outline"], original)
        self.assertIn("第1扇门", restored["imported_chapter_plan_reference"]["stages"][0]["summary"])
        context = tab._chapter_plan_reference_context(1, 20)
        self.assertEqual(len(context["chapters"]), 20)
        self.assertEqual(len(context["stages"]), 1)
        self.assertIn("第1扇门", context["stages"][0]["summary"])
        self.assertTrue(all("summary" not in stage for stage in context["stage_index"]))
        valid = [{"index": index, "source_event_ids": [f"S01-E{index:02d}"]} for index in range(1, 21)]
        self.assertEqual(tab._chapter_plan_event_assignment_error([], valid), "")
        valid[1]["source_event_ids"] = ["S01-E01"]
        self.assertIn("重复", tab._chapter_plan_event_assignment_error([], valid))

    def test_number_only_outline_recovery_never_changes_started_event_ledger(self):
        tab = self._imported_planning_tab(self._number_only_full_framework_fixture())
        reference = {"stages": [{"id": "S01", "name": "用户原阶段"}]}
        tab.current_project["imported_chapter_plan_reference"] = deepcopy(reference)
        tab.current_project["chapter_plan_generation_state"] = {"chapters": [{"index": 1, "source_event_ids": ["S01-E01"]}]}
        tab._chapter_plan_restore_imported_reference()
        self.assertEqual(tab.current_project["imported_chapter_plan_reference"], reference)

    def test_late_chapter_callback_is_discarded_after_project_switch(self):
        chapter = _new_chapter(0)

        class Worker:
            diagnostic_request_id = "request-a"
            diagnostic_project_path = "/tmp/project-a.json"
            diagnostic_chapter_id = chapter["id"]
            diagnostic_task_generation = 1
            action = "memory_finalize"

        worker = Worker()
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab.current_project_path = "/tmp/project-b.json"
        tab.writing_worker = worker
        tab._chapter_ai_task_generation = 2
        tab._chapter_ai_diagnostic_request_id = "request-b"
        events = []
        tab.sender = lambda: worker
        tab._log_novel_diagnostic = lambda event, **details: events.append((event, details))

        self.assertFalse(tab._chapter_ai_callback_is_current())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "chapter_ai_stale_callback_discarded")

    def test_foreground_single_chapter_draft_starts_through_detached_runner(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._is_detached_auto_runner = False
        tab.context_build_worker = None
        tab.writing_worker = None
        tab.chapter_plan_worker = None
        tab._discard_partial_preview_for_auto_rewrite = lambda source="": None
        started = []
        tab._start_detached_single_chapter_ai = lambda: started.append(True)

        tab.run_chapter_ai_action("draft")

        self.assertEqual(started, [True])

    def test_detached_single_runner_reselects_target_chapter_by_id(self):
        chapters = [_new_chapter(0), _new_chapter(1)]
        chapters[0]["id"] = "chapter-one"
        chapters[1]["id"] = "chapter-two"
        project = {"chapters": chapters, "meta": {"title": "测试小说"}}
        created = []

        class FakeRunner:
            def __init__(self, config, parent, background_runner=False):
                self.current_project = {}
                self.current_chapter_index = -1
                self._background_task_kind = ""
                self.reloaded_index = -1
                created.append(self)

            def _load_project_data(self, data, source_path, defer_helpers=False):
                self.current_project = deepcopy(data)

            def _reload_chapter_list(self, index):
                self.reloaded_index = index

            def hide(self):
                pass

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.config = {}
        tab._background_chapter_ai_runners = {}
        tab._update_detached_auto_source_lock = lambda: None

        with patch("gpt_desktop.novel_writing_tab.NovelWritingTab", FakeRunner), patch(
            "gpt_desktop.novel_writing_tab.load_json_file", return_value=project
        ):
            runner, _data = tab._create_detached_chapter_runner(
                "/tmp/project.json",
                "single_chapter",
                chapter_index=0,
                chapter_id="chapter-two",
            )

        self.assertIs(runner, created[0])
        self.assertEqual(runner.current_chapter_index, 1)
        self.assertEqual(runner.reloaded_index, 1)
        self.assertIs(tab._background_chapter_ai_runners[os.path.realpath("/tmp/project.json")], runner)

    def test_staged_memory_commit_does_not_mutate_live_project_before_apply(self):
        chapter = _new_chapter(0)
        chapter["text"] = "旧正文"
        chapter["outline"] = "本章提纲"
        project = {
            "chapters": [chapter],
            "long_form_memory": {"revision": 0},
        }
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = project
        tab.current_chapter_index = 0
        tab._chapter_ai_sequence_started_outline = ""
        class Editor:
            def __init__(self, value):
                self.value = value

            def toPlainText(self):
                return self.value

        tab.chapter_text = Editor("旧正文")
        bundle = {
            "outline": "更新提纲",
            "summary": "本章摘要",
            "key_facts": "关键事实",
            "memory_update": {"test": True},
        }

        evidence = []

        def fake_apply(staged, index, update, final_text=""):
            evidence.append(final_text)
            staged["chapters"][index]["memory_sync_status"] = "complete"
            staged["chapters"][index]["memory_revision"] = 1
            return True

        with patch("gpt_desktop.novel_writing_tab._apply_long_form_memory_update", side_effect=fake_apply):
            staged, changed, text, outline, summary, facts = tab._prepare_staged_memory_commit(
                "新正文", bundle
            )

        self.assertTrue(changed)
        self.assertEqual(text, "旧正文\n\n新正文")
        self.assertEqual(outline, "更新提纲")
        self.assertEqual(summary, "本章摘要")
        self.assertEqual(facts, "关键事实")
        self.assertEqual(project["chapters"][0]["text"], "旧正文")
        self.assertEqual(project["chapters"][0]["memory_sync_status"], "pending")
        self.assertEqual(project["chapters"][0]["memory_revision"], 0)
        self.assertEqual(staged["chapters"][0]["text"], "旧正文\n\n新正文")
        self.assertEqual(evidence, [text])

    def test_background_context_result_requires_same_project_and_chapter(self):
        first = _new_chapter(0)
        second = _new_chapter(1)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [first, second]}
        tab.current_chapter_index = 0
        tab.current_project_path = "/tmp/project-a.json"
        pending = {
            "project_path": os.path.abspath("/tmp/project-a.json"),
            "chapter_id": first["id"],
        }

        self.assertTrue(tab._context_build_target_is_current(pending))
        tab.current_project_path = "/tmp/project-b.json"
        self.assertFalse(tab._context_build_target_is_current(pending))
        tab.current_project_path = "/tmp/project-a.json"
        tab.current_chapter_index = 1
        self.assertFalse(tab._context_build_target_is_current(pending))

    def test_detached_auto_source_lock_only_locks_source_project_editors(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._background_chapter_ai_runners = {
            os.path.realpath("/tmp/source.json"): object(),
        }
        tab.current_project_path = "/tmp/source.json"
        tab.tabs = _FakeButton()
        tab.nav_list = _FakeButton()
        tab.auto_expand_all_btn = _FakeButton()
        tab.project_hint = _FakeLineEdit()

        tab._update_detached_auto_source_lock()

        self.assertTrue(tab.tabs.enabled)
        self.assertTrue(tab.nav_list.enabled)
        self.assertFalse(tab.auto_expand_all_btn.enabled)
        self.assertEqual(tab.auto_expand_all_btn.text, "后台自动扩写中")

        tab.current_project_path = "/tmp/other.json"
        tab._update_detached_auto_source_lock()

        self.assertTrue(tab.tabs.enabled)
        self.assertTrue(tab.nav_list.enabled)
        self.assertTrue(tab.auto_expand_all_btn.enabled)
        self.assertEqual(tab.auto_expand_all_btn.text, "自动扩写全部")

    def test_detached_auto_source_lock_scopes_to_project_workspace(self):
        class FakeReadOnlyWidget:
            def __init__(self):
                self.read_only = False

            def isReadOnly(self):
                return self.read_only

            def setReadOnly(self, value):
                self.read_only = bool(value)

        class FakeEnabledWidget:
            def __init__(self):
                self.enabled = True

            def isEnabled(self):
                return self.enabled

            def setEnabled(self, value):
                self.enabled = bool(value)

        class FakeWorkspace:
            def __init__(self, children):
                self.children = children
                self.find_children_called = False

            def findChildren(self, _widget_type):
                self.find_children_called = True
                return list(self.children)

        editor = FakeReadOnlyWidget()
        action = FakeEnabledWidget()
        stop = FakeEnabledWidget()
        read_aloud = FakeEnabledWidget()
        read_aloud_stop = FakeEnabledWidget()
        read_aloud_scope = FakeEnabledWidget()
        read_aloud_rate = FakeEnabledWidget()
        workspace = FakeWorkspace(
            [editor, action, stop, read_aloud, read_aloud_stop, read_aloud_scope, read_aloud_rate]
        )
        project_panel = FakeWorkspace([FakeEnabledWidget()])

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._detached_auto_readonly_states = []
        tab.project_workspace = workspace
        tab.project_panel = project_panel
        tab.chapter_ai_stop_btn = stop
        tab.read_aloud_btn = read_aloud
        tab.read_aloud_stop_btn = read_aloud_stop
        tab.read_aloud_scope_combo = read_aloud_scope
        tab.read_aloud_rate_combo = read_aloud_rate

        with patch("gpt_desktop.novel_writing_tab.QPlainTextEdit", FakeReadOnlyWidget), \
             patch("gpt_desktop.novel_writing_tab.QTextEdit", FakeReadOnlyWidget), \
             patch("gpt_desktop.novel_writing_tab.QLineEdit", FakeReadOnlyWidget), \
             patch("gpt_desktop.novel_writing_tab.QAbstractButton", FakeEnabledWidget), \
             patch("gpt_desktop.novel_writing_tab.QComboBox", FakeEnabledWidget), \
             patch("gpt_desktop.novel_writing_tab.QAbstractSpinBox", FakeEnabledWidget):
            tab._set_detached_auto_source_read_only(True)

            self.assertTrue(workspace.find_children_called)
            self.assertTrue(editor.read_only)
            self.assertFalse(action.enabled)
            self.assertTrue(stop.enabled)
            self.assertTrue(read_aloud.enabled)
            self.assertTrue(read_aloud_stop.enabled)
            self.assertTrue(read_aloud_scope.enabled)
            self.assertTrue(read_aloud_rate.enabled)
            self.assertTrue(project_panel.children[0].enabled)

            tab._set_detached_auto_source_read_only(False)

        self.assertFalse(editor.read_only)
        self.assertTrue(action.enabled)

    def test_detached_auto_runner_exposes_background_stop_button(self):
        class RunningDetached:
            def _status_has_active_work(self):
                return True

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._is_detached_auto_runner = False
        tab._background_chapter_ai_runners = {
            os.path.realpath("/tmp/source.json"): RunningDetached(),
        }
        tab.current_project_path = "/tmp/source.json"
        tab.chapter_ai_stop_btn = _FakeButton()
        tab.auto_expand_all_btn = _FakeButton()
        tab.project_hint = _FakeLineEdit()

        tab._update_detached_auto_source_lock()

        self.assertTrue(tab.chapter_ai_stop_btn.visible)
        self.assertTrue(tab.chapter_ai_stop_btn.enabled)
        self.assertEqual(tab.chapter_ai_stop_btn.text, "中止后台扩写")

        tab.current_project_path = "/tmp/other.json"
        tab._update_detached_auto_source_lock()
        self.assertFalse(tab.chapter_ai_stop_btn.visible)

    def test_detached_auto_status_mirrors_stream_chars_stage_and_queue_progress(self):
        class RunningDetached:
            _status_message = "正在扩写正文..."
            _status_stage_key = "chapter-12:draft"
            _status_stage_label = "正文直写"
            _status_stage_started_at = 123.0
            _status_stage_started_wall = 456.0
            _status_stage_scope_label = "第12章《新章》"
            _status_stage_active = True
            _status_history = [{"label": "上一阶段"}]
            _status_workflow_active = True
            _status_workflow_kind = "auto_expand"
            _status_workflow_started_at = 100.0
            _status_workflow_started_wall = 400.0
            _status_last_run_elapsed = 0.0
            _status_received_chars = 2929

            def _status_current_chapter_scope(self):
                return "chapter-12", "第12章《新章》"

            def _auto_expand_all_chapter_progress(self):
                return 12, 250

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._is_detached_auto_runner = False
        tab._background_chapter_ai_runners = {
            os.path.realpath("/tmp/source.json"): RunningDetached(),
        }
        tab.current_project_path = "/tmp/source.json"
        refreshed = []
        tab._refresh_status_display = lambda: refreshed.append(True)

        runner = tab._current_background_chapter_runner()
        self.assertTrue(tab._sync_detached_auto_status(runner))
        self.assertEqual(tab._status_received_chars, 2929)
        self.assertEqual(tab._status_stage_label, "正文直写")
        self.assertEqual(tab._detached_auto_status_auto_progress, (12, 250))
        self.assertEqual(tab._detached_auto_status_scope_label, "第12章《新章》")
        self.assertEqual(len(refreshed), 1)

        tab.current_project_path = "/tmp/other.json"
        tab._status_received_chars = 0
        self.assertFalse(tab._sync_detached_auto_status(runner))
        self.assertEqual(tab._status_received_chars, 0)

        tab._detached_auto_status_mirrored = True
        tab._status_message = "正在扩写正文..."
        tab._status_stage_started_wall = 456.0
        tab._status_received_chars = 2929
        tab._refresh_status_display = lambda: None
        tab._clear_detached_auto_status_mirror()
        self.assertEqual(tab._status_message, "")
        self.assertEqual(tab._status_received_chars, 0)
        self.assertEqual(tab._status_stage_started_wall, 0.0)

    def test_project_switch_clears_previous_status_snapshot(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._detached_auto_status_mirrored = True
        tab._detached_auto_status_scope_id = "chapter-1"
        tab._detached_auto_status_scope_label = "第1章《旧项目》"
        tab._detached_auto_status_auto_progress = (1, 250)
        tab._status_message = "正在打开：《路人甲拒绝加戏》.json"
        tab._status_stage_key = "chapter-1:draft"
        tab._status_stage_label = "正文直写"
        tab._status_stage_started_at = 123.0
        tab._status_stage_started_wall = 456.0
        tab._status_stage_scope_label = "第1章《旧项目》"
        tab._status_stage_active = True
        tab._status_workflow_active = True
        tab._status_workflow_kind = "auto_expand"
        tab._status_workflow_started_at = 100.0
        tab._status_workflow_started_wall = 400.0
        tab._status_last_run_elapsed = 12.0
        tab._status_received_chars = 8308
        tab._status_history = [{"label": "旧项目阶段"}]
        refreshed = []
        tab._refresh_status_display = lambda: refreshed.append(True)

        tab._reset_status_for_project_switch()

        self.assertFalse(tab._detached_auto_status_mirrored)
        self.assertEqual(tab._detached_auto_status_scope_id, "")
        self.assertEqual(tab._detached_auto_status_scope_label, "")
        self.assertEqual(tab._detached_auto_status_auto_progress, (0, 0))
        self.assertEqual(tab._status_message, "")
        self.assertEqual(tab._status_stage_key, "")
        self.assertEqual(tab._status_stage_label, "")
        self.assertFalse(tab._status_stage_active)
        self.assertFalse(tab._status_workflow_active)
        self.assertEqual(tab._status_last_run_elapsed, 0.0)
        self.assertEqual(tab._status_received_chars, 0)
        self.assertEqual(tab._status_history, [])
        self.assertEqual(refreshed, [True])

    def test_status_mirror_records_the_runner_project_path(self):
        class RunningDetached:
            current_project_path = "/tmp/source.json"
            _status_message = "正在扩写正文..."
            _status_stage_key = "chapter-1:draft"
            _status_stage_label = "正文直写"
            _status_stage_started_at = 1.0
            _status_stage_started_wall = 2.0
            _status_stage_scope_label = "第1章"
            _status_stage_active = True
            _status_history = []
            _status_workflow_active = True
            _status_workflow_kind = "auto_expand"
            _status_workflow_started_at = 1.0
            _status_workflow_started_wall = 2.0
            _status_last_run_elapsed = 0.0
            _status_received_chars = 10

            def _status_current_chapter_scope(self):
                return "chapter-1", "第1章"

            def _auto_expand_all_chapter_progress(self):
                return 1, 3

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._is_detached_auto_runner = False
        tab._background_chapter_ai_runners = {
            os.path.realpath("/tmp/source.json"): RunningDetached(),
        }
        tab.current_project_path = "/tmp/source.json"
        tab._refresh_status_display = lambda: None

        tab._sync_detached_auto_status(tab._current_background_chapter_runner())

        self.assertEqual(tab._status_project_path, os.path.realpath("/tmp/source.json"))

    def test_detached_auto_failure_uses_status_tip_without_modal_warning(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._is_detached_auto_runner = True
        tab._status_message = "正在扩写正文..."
        statuses = []

        def set_status(text):
            tab._status_message = text
            statuses.append(text)

        tab.set_status_tip = set_status

        with patch("gpt_desktop.novel_writing_tab.QMessageBox.warning") as warning:
            tab._show_chapter_ai_failure("stream_read_error: connection lost")

        warning.assert_not_called()
        self.assertEqual(len(statuses), 1)
        self.assertIn("后台自动扩写已停止", statuses[0])
        self.assertIn("stream_read_error", statuses[0])

    def test_detached_auto_runner_is_created_without_widget_parent(self):
        created = []

        class FakeRunner:
            def __init__(self, config, parent, background_runner=False):
                created.append((config, parent, background_runner))
                self.current_project = {"meta": {"title": "测试小说"}}

            def _load_project_data(self, data, source_path, defer_helpers=False):
                self.current_project = data

            def hide(self):
                pass

            def _start_auto_expand_all_local(self):
                pass

            def _status_has_active_work(self):
                return True

            def deleteLater(self):
                pass

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.config = {"novel": {"model": "test"}}
        tab._background_chapter_ai_runners = {}
        tab._save_current_work = lambda *_args, **_kwargs: "/tmp/source.json"
        tab._update_detached_auto_source_lock = lambda: None
        tab.set_status_tip = lambda _text: None

        project = {"meta": {"title": "测试小说"}, "chapters": []}
        with patch("gpt_desktop.novel_writing_tab.NovelWritingTab", FakeRunner), patch(
            "gpt_desktop.novel_writing_tab.load_json_file", return_value=project
        ):
            tab._launch_detached_auto_expand("/tmp/source.json")

        self.assertEqual(len(created), 1)
        self.assertIsNone(created[0][1])
        self.assertTrue(created[0][2])
        self.assertEqual(
            list(tab._background_chapter_ai_runners),
            [os.path.realpath("/tmp/source.json")],
        )

    def test_multiple_detached_auto_runners_are_isolated_by_project_path(self):
        created = []

        class FakeRunner:
            def __init__(self, config, parent, background_runner=False):
                created.append((config, parent, background_runner))
                self.current_project = {"meta": {"title": "测试小说"}}
                self._background_task_kind = ""

            def _load_project_data(self, data, source_path, defer_helpers=False):
                self.current_project = data

            def hide(self):
                pass

            def _start_auto_expand_all_local(self):
                pass

            def _status_has_active_work(self):
                return True

            def deleteLater(self):
                pass

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.config = {"novel": {"model": "test"}}
        tab._background_chapter_ai_runners = {}
        tab._save_current_work = lambda *_args, **_kwargs: "/tmp/saved.json"
        tab._update_detached_auto_source_lock = lambda: None
        tab.set_status_tip = lambda _text: None

        projects = {
            os.path.realpath("/tmp/source-a.json"): {"meta": {"title": "项目 A"}},
            os.path.realpath("/tmp/source-b.json"): {"meta": {"title": "项目 B"}},
        }

        def load_project(path, _default=None):
            return projects[os.path.realpath(path)]

        with patch("gpt_desktop.novel_writing_tab.NovelWritingTab", FakeRunner), patch(
            "gpt_desktop.novel_writing_tab.load_json_file", side_effect=load_project
        ):
            tab._launch_detached_auto_expand("/tmp/source-a.json")
            tab._launch_detached_auto_expand("/tmp/source-b.json")

        self.assertEqual(len(created), 2)
        self.assertEqual(
            set(tab._background_chapter_ai_runners),
            {os.path.realpath("/tmp/source-a.json"), os.path.realpath("/tmp/source-b.json")},
        )
        self.assertTrue(
            all(
                runner._background_task_kind == "auto_expand"
                for runner in tab._background_chapter_ai_runners.values()
            )
        )

    def test_auto_expand_runner_stays_hidden_when_source_project_is_opened(self):
        class AutoRunner:
            _background_task_kind = "auto_expand"

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._is_detached_auto_runner = False
        tab._background_chapter_ai_runners = {
            os.path.realpath("/tmp/source.json"): AutoRunner(),
        }

        self.assertFalse(tab._attach_background_chapter_runner("/tmp/source.json"))
        self.assertIn(
            os.path.realpath("/tmp/source.json"),
            tab._background_chapter_ai_runners,
        )

    def test_detached_auto_runner_waits_for_writing_worker_cleanup(self):
        class FinishedWorker:
            def isRunning(self):
                return False

        runner = NovelWritingTab.__new__(NovelWritingTab)
        runner._is_detached_auto_runner = True
        runner._auto_expand_all_active = False
        runner._auto_expand_all_waiting_next = False
        runner._chapter_ai_sequence_active = False
        runner._chapter_ai_transient_retry_pending = False
        runner._chapter_plan_auto_active = False
        runner.writing_worker = FinishedWorker()
        runner.writing_retired_workers = []
        runner.chapter_plan_worker = None
        runner.context_build_worker = None
        runner._status_message = "AI 写作失败：stream_read_error"
        runner._save_current_project_snapshot_if_named = lambda: None
        runner_deleted = []
        runner.deleteLater = lambda: runner_deleted.append(True)

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._background_chapter_ai_runners = {
            os.path.realpath("/tmp/source.json"): runner,
        }
        tab.current_project_path = "/tmp/other.json"
        tab._update_detached_auto_source_lock = lambda: None
        tab._notify_project_store_changed = lambda: None
        tab.set_status_tip = lambda _text: None

        tab._poll_background_chapter_ai_runners()

        self.assertIs(tab._background_chapter_ai_runners[os.path.realpath("/tmp/source.json")], runner)
        self.assertEqual(runner_deleted, [])

        runner.writing_worker = None
        tab._poll_background_chapter_ai_runners()

        self.assertNotIn(os.path.realpath("/tmp/source.json"), tab._background_chapter_ai_runners)
        self.assertEqual(runner_deleted, [True])

    def test_status_active_work_includes_retired_writing_workers(self):
        runner = NovelWritingTab.__new__(NovelWritingTab)
        runner._is_detached_auto_runner = True
        runner.writing_worker = None
        runner.writing_retired_workers = [object()]
        runner.chapter_plan_worker = None
        runner.context_build_worker = None

        self.assertTrue(runner._status_has_active_work())

        runner.writing_retired_workers.clear()
        self.assertFalse(runner._status_has_active_work())

    def test_detached_auto_completion_keeps_other_project_open(self):
        class FinishedRunner:
            def __init__(self):
                self._status_message = "后台自动扩写已完成。"
                self.saved = False
                self.deleted = False

            def _status_has_active_work(self):
                return False

            def _save_current_project_snapshot_if_named(self):
                self.saved = True

            def deleteLater(self):
                self.deleted = True

        runner = FinishedRunner()
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._background_chapter_ai_runners = {
            os.path.realpath("/tmp/source.json"): runner,
        }
        tab.current_project_path = "/tmp/other.json"
        tab.current_project = {"meta": {"title": "其他小说"}}
        tab._update_detached_auto_source_lock = lambda: None
        notified = []
        statuses = []
        tab._notify_project_store_changed = lambda: notified.append(True)
        tab.set_status_tip = statuses.append

        tab._poll_background_chapter_ai_runners()

        self.assertTrue(runner.saved)
        self.assertTrue(runner.deleted)
        self.assertEqual(tab.current_project_path, "/tmp/other.json")
        self.assertEqual(tab.current_project["meta"]["title"], "其他小说")
        self.assertNotIn(os.path.realpath("/tmp/source.json"), tab._background_chapter_ai_runners)
        self.assertEqual(notified, [True])
        self.assertEqual(statuses, [])

    def test_500k_project_uses_one_hundred_5000_word_chapters(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "meta": {"title": "五十万字压力测试", "target_words": "50万"},
            "chapters": [],
            "characters": [],
            "lore": [],
            "narrative_strategy_profile": {
                "audience_direction": "女频",
                "primary_story_engine": "关系选择与成长",
            },
        }

        context = tab._chapter_plan_project_context(500000, 5000, 100, 50)

        self.assertEqual(tab._chapter_plan_batch_ranges(100), [(0, 50), (50, 50)])
        self.assertIn('"average_chapter_words": 5000', context)
        self.assertIn('"estimated_total_chapters": 100', context)
        self.assertIn("关系选择与成长", context)

    def test_novel_context_diagnostics_report_section_sizes_without_content(self):
        context = "前缀\n【当前章节】\n章节资料。\n\n【当前状态快照】\n状态资料。"

        metrics = NovelWritingTab._novel_context_section_metrics(context)

        self.assertEqual(metrics["section_count"], 2)
        self.assertEqual(metrics["prefix_chars"], len("前缀\n"))
        self.assertEqual(
            [item["title"] for item in metrics["sections"]],
            ["当前章节", "当前状态快照"],
        )
        self.assertNotIn("章节资料", json.dumps(metrics, ensure_ascii=False))

    def test_auto_expand_stop_reason_codes_are_actionable(self):
        self.assertEqual(
            NovelWritingTab._auto_expand_stop_reason_code(
                "自动扩写已停止：第51章上下文组装失败。"
            ),
            "context_build_failed",
        )
        self.assertEqual(
            NovelWritingTab._auto_expand_stop_reason_code(
                "自动扩写已停止：第51章正文完成，但状态同步失败。"
            ),
            "memory_sync_failed",
        )
        self.assertEqual(
            NovelWritingTab._auto_expand_stop_reason_code("自动扩写完成：共完成 250 章。"),
            "completed",
        )
        self.assertEqual(
            NovelWritingTab._novel_diagnostic_error_category("请先选择厂商。"),
            "configuration",
        )
        self.assertEqual(
            NovelWritingTab._novel_diagnostic_error_category(
                "AI 没有返回有效内容。 finish_reason=stop"
            ),
            "empty_output",
        )
        self.assertEqual(
            NovelWritingTab._novel_diagnostic_error_category(
                "AI 章节状态整理输出异常膨胀（已超过36000字）"
            ),
            "incomplete_output",
        )

    def test_memory_failure_diagnostics_exclude_body_requests(self):
        memory_failure = {
            "event": "memory_validation_failed",
            "level": "warning",
            "pipeline": {"action": "memory_repair"},
            "details": {"validation_errors": ["object_keys引用未知物件"]},
        }
        body_failure = {
            "event": "chapter_ai_request_failed",
            "level": "error",
            "pipeline": {"action": "draft"},
            "details": {"error": "正文请求失败"},
        }

        self.assertTrue(NovelWritingTab._should_log_memory_failure(memory_failure))
        self.assertFalse(NovelWritingTab._should_log_memory_failure(body_failure))

    def test_status_tracker_records_chapter_stage_time_ranges(self):
        chapter = _new_chapter(0)
        chapter["title"] = "祭坛醒来"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab._chapter_ai_running_action = "draft"
        tab._auto_expand_all_active = True
        tab._auto_expand_all_waiting_next = False
        tab._chapter_ai_sequence_active = True
        tab._chapter_ai_transient_retry_pending = False
        tab._chapter_plan_auto_active = False
        tab.writing_worker = None
        tab.chapter_plan_worker = None
        tab._status_stage_key = ""
        tab._status_stage_label = ""
        tab._status_stage_started_at = 0.0
        tab._status_stage_started_wall = 0.0
        tab._status_stage_active = False
        tab._status_history = []
        tab._status_workflow_active = True
        tab._status_workflow_started_at = 90.0
        tab._status_workflow_started_wall = 990.0

        with patch("gpt_desktop.novel_writing_tab.time.monotonic", side_effect=[100.0, 112.0]), patch(
            "gpt_desktop.novel_writing_tab.time.time", side_effect=[1000.0, 1012.0]
        ):
            tab._track_status_message("文风档案已载入，正在直接扩写正文...")
            tab._chapter_ai_running_action = "style_finalize"
            tab._track_status_message("正文已生成，正在专门审校并修订正文终稿...")

        self.assertEqual(tab._status_stage_label, "终稿补救")
        self.assertEqual(len(tab._status_history), 1)
        self.assertEqual(tab._status_history[0]["label"], "正文直写")
        self.assertEqual(tab._status_history[0]["scope"], "第1章《祭坛醒来》")
        self.assertEqual(tab._status_history[0]["elapsed"], 12.0)
        history_text = tab._status_history_text()
        self.assertIn("正文直写", history_text)
        self.assertIn("12秒", history_text)

    def test_status_action_labels_cover_long_form_pipeline(self):
        self.assertEqual(NovelWritingTab._status_action_label("draft"), "正文直写")
        self.assertEqual(NovelWritingTab._status_action_label("style_finalize"), "终稿补救")
        self.assertEqual(NovelWritingTab._status_action_label("memory_finalize"), "状态整理")
        self.assertEqual(NovelWritingTab._status_action_label("memory_reconcile"), "十章边界对账")
        self.assertEqual(NovelWritingTab._status_action_label("memory_repair"), "状态修复")
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._chapter_ai_running_action = ""
        self.assertEqual(
            tab._status_stage_for_message("自动扩写 3/20（已丢弃半成品，重新生成）"),
            ("半成品重写", "partial_rewrite"),
        )

    def test_status_progress_estimate_moves_from_waiting_to_receiving_and_repair(self):
        self.assertEqual(
            NovelWritingTab._status_progress_percent(
                "正在独立整理本章摘要和长期状态...",
                "memory_finalize",
                received_chars=0,
                active=True,
            ),
            10,
        )
        receiving = NovelWritingTab._status_progress_percent(
            "正在独立整理本章摘要和长期状态...",
            "memory_finalize",
            received_chars=1999,
            active=True,
        )
        self.assertGreater(receiving, 10)
        self.assertLessEqual(receiving, 78)
        self.assertGreaterEqual(
            NovelWritingTab._status_progress_percent(
                "状态数据有1项需修复，正在处理（1/2）...",
                "memory_repair",
                received_chars=0,
                active=True,
            ),
            80,
        )
        self.assertEqual(
            NovelWritingTab._status_progress_percent(
                "章节 AI 已完成：摘要、关键事实和长篇状态已自动修复并提交。",
                "memory_repair",
                received_chars=0,
                active=False,
            ),
            100,
        )

    def test_status_display_only_shows_received_chars_when_available(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._status_message = "正在独立整理本章摘要和长期状态..."
        tab._status_stage_key = "chapter-1:memory_finalize"
        tab._status_stage_label = "状态整理"
        tab._status_stage_active = True
        tab._status_stage_started_wall = 0.0
        tab._status_stage_started_at = 0.0
        tab._status_workflow_active = True
        tab._status_workflow_started_at = 0.0
        tab._status_last_run_elapsed = 0.0
        tab._status_received_chars = 0
        tab._status_has_active_work = lambda: True
        tab._status_current_chapter_scope = lambda: ("chapter-1", "第1章")
        tab.status_label = _FakeLabel()
        tab.status_meta_label = _FakeLabel()

        tab._refresh_status_display()

        self.assertNotIn("已接收字符", tab.status_label.text)
        self.assertNotIn("当前进度", tab.status_label.text)
        self.assertNotIn("%", tab.status_label.tooltip)

        tab._status_received_chars = 1999
        tab._refresh_status_display()

        self.assertIn("已接收字符：1999", tab.status_label.text)
        self.assertNotIn("当前进度", tab.status_label.text)
        self.assertNotIn("%", tab.status_label.tooltip)
        self.assertIn("第1章", tab.status_meta_label.text)
        self.assertIn("状态整理", tab.status_meta_label.text)

        for stage, message in (
            ("draft", "正在直接扩写正文..."),
            ("chapter_plan", "正在生成章节规划..."),
            ("memory_repair", "正在修复本章状态..."),
            ("memory_reconcile", "正在十章边界对账..."),
            ("chapter_complete", "章节 AI 已完成。"),
        ):
            with self.subTest(stage=stage):
                tab._status_stage_key = f"chapter-1:{stage}"
                tab._status_message = message
                tab._refresh_status_display()
                self.assertNotIn("%", tab.status_label.text)
                self.assertNotIn("%", tab.status_label.tooltip)

    def test_stopping_worker_does_not_clear_completed_stage_history(self):
        class RunningWorker:
            def isRunning(self):
                return True

        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab.writing_worker = RunningWorker()
        tab.chapter_plan_worker = None
        tab._chapter_ai_running_action = "draft"
        tab._chapter_ai_stop_requested_by_user = False
        tab._auto_expand_all_active = True
        tab._auto_expand_all_waiting_next = False
        tab._chapter_ai_sequence_active = True
        tab._chapter_ai_transient_retry_pending = False
        tab._chapter_plan_auto_active = False
        tab._status_stage_key = ""
        tab._status_stage_label = ""
        tab._status_stage_started_at = 0.0
        tab._status_stage_started_wall = 0.0
        tab._status_stage_active = False
        tab._status_history = []
        tab._status_workflow_active = True
        tab._status_workflow_started_at = 90.0
        tab._status_workflow_started_wall = 990.0

        with patch("gpt_desktop.novel_writing_tab.time.monotonic", side_effect=[100.0, 110.0, 111.0]), patch(
            "gpt_desktop.novel_writing_tab.time.time", side_effect=[1000.0, 1010.0, 1011.0]
        ):
            tab._track_status_message("文风档案已载入，正在直接扩写正文...")
            tab._auto_expand_all_active = False
            tab._chapter_ai_sequence_active = False
            tab._chapter_ai_stop_requested_by_user = True
            tab._track_status_message("自动扩写已中止：已完成 2/20 章。")
            history_size = len(tab._status_history)
            tab._track_status_message("正在中止 AI 辅助生成...")

        self.assertFalse(tab._status_workflow_active)
        self.assertEqual(len(tab._status_history), history_size)
        self.assertTrue(any(item["label"] == "正文直写" for item in tab._status_history))

    @staticmethod
    def _strict_memory_controls(fact_refs=None, long_term_events=None):
        return {
            "state_lifecycle_review": {
                "scope": "current_chapter",
                "reviewed_object_keys": [],
                "reviewed_conflict_refs": [],
                "reviewed_task_refs": [],
                "notes": "已复核",
            },
            "fact_lifecycle_review": {
                "scope": "current_chapter",
                "reviewed_refs": [],
                "notes": "已复核",
            },
            "long_term_events": list(long_term_events or []),
            "state_reconciliation": {
                "checked": True,
                "coverage_checks": {
                    "named_character_actions": True,
                    "state_changes": True,
                    "evidence_and_unknowns": True,
                    "mechanism_claims_match_body": True,
                    "rules_and_boundaries": True,
                    "foreshadow_and_ending": True,
                },
                "fact_refs": list(fact_refs or []),
                "character_refs": [],
                "lore_refs": [],
                "foreshadow_refs": [],
                "relationship_refs": [],
                "object_keys": [],
                "conflict_refs": [],
                "task_refs": [],
                "record_runtime_review": {
                    "reviewed_lore_refs": [],
                    "unchanged_lore_refs": [],
                    "reviewed_foreshadow_refs": [],
                    "unchanged_foreshadow_refs": [],
                },
                "resolved_contradictions": [],
                "notes": "已对账",
            },
        }

    @staticmethod
    def _valid_summary_bundle(summary="AI 摘要。", fact="AI 事实。", base_revision=0):
        return json.dumps({
            "summary": summary,
            "key_facts": [fact],
            "linked_characters": [],
            "long_form_memory": {
                "schema_version": 2,
                "base_revision": base_revision,
                "state_patch": {},
                "state_retirements": {},
                "fact_updates": [],
                "state_delta": {},
                "current_chapter_character_refs": [],
                "stage_archive": None,
                "record_updates": {"characters": [], "lore": []},
                "foreshadow_updates": [],
                "next_chapter_memory": {},
                **NovelWritingStateTests._strict_memory_controls(),
            },
        }, ensure_ascii=False)

    def test_chapter_plan_batch_ranges_cover_250_chapters(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        ranges = tab._chapter_plan_batch_ranges(250)

        self.assertEqual(ranges, [
            (0, 50), (50, 50), (100, 50), (150, 50), (200, 50),
        ])

    def test_chapter_plan_stage_batches_do_not_cross_explicit_framework_stages(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "imported_chapter_plan_reference": {
                "stages": [
                    {"id": f"S{index:02d}", "name": f"阶段{index}", "start_chapter": start, "end_chapter": end}
                    for index, (start, end) in enumerate(
                        ((1, 20), (21, 40), (41, 60), (61, 80)), 1
                    )
                ]
            }
        }
        state = {
            "existing_chapter_count": 0,
            "requested_chapter_count": 80,
            "batch_size": 50,
            "master_plan": {
                "arcs": [
                    {"start_chapter": start, "end_chapter": end}
                    for start, end in ((1, 20), (21, 40), (41, 60), (61, 80))
                ]
            },
            "chapters": [],
        }

        self.assertEqual(
            tab._chapter_plan_stage_batch_ranges(state),
            [(1, 20), (21, 40), (41, 60), (61, 80)],
        )

    def test_chapter_plan_stage_longer_than_batch_size_splits_inside_stage_only(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "imported_chapter_plan_reference": {
                "stages": [
                    {"id": "S01", "name": "长阶段", "start_chapter": 1, "end_chapter": 80},
                    {"id": "S02", "name": "第二阶段", "start_chapter": 81, "end_chapter": 100},
                ]
            }
        }
        state = {
            "existing_chapter_count": 0,
            "requested_chapter_count": 100,
            "batch_size": 50,
            "master_plan": {
                "arcs": [
                    {"start_chapter": 1, "end_chapter": 80},
                    {"start_chapter": 81, "end_chapter": 100},
                ]
            },
            "chapters": [],
        }

        self.assertEqual(
            tab._chapter_plan_stage_batch_ranges(state),
            [(1, 50), (51, 80), (81, 100)],
        )

    def test_chapter_plan_without_explicit_stages_keeps_fixed_batches(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"imported_chapter_plan_reference": {}}
        state = {
            "existing_chapter_count": 0,
            "requested_chapter_count": 120,
            "batch_size": 50,
            "master_plan": {
                "arcs": [
                    {"start_chapter": 1, "end_chapter": 30},
                    {"start_chapter": 31, "end_chapter": 60},
                    {"start_chapter": 61, "end_chapter": 120},
                ]
            },
            "chapters": [],
        }

        self.assertIsNone(tab._chapter_plan_stage_batch_ranges(state))
        self.assertEqual(
            tab._chapter_plan_next_batch_info(state),
            (50, 1, 3, 1, 50),
        )

    def test_chapter_plan_stage_batches_resume_from_existing_chapters(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "imported_chapter_plan_reference": {
                "stages": [
                    {"id": f"S{index:02d}", "name": f"阶段{index}", "start_chapter": start, "end_chapter": end}
                    for index, (start, end) in enumerate(
                        ((1, 20), (21, 40), (41, 60), (61, 80), (81, 100),
                         (101, 120), (121, 140), (141, 160), (161, 180), (181, 200)), 1
                    )
                ]
            }
        }
        state = {
            "existing_chapter_count": 150,
            "requested_chapter_count": 50,
            "batch_size": 50,
            "master_plan": {
                "arcs": [
                    {"start_chapter": 151, "end_chapter": 160},
                    {"start_chapter": 161, "end_chapter": 180},
                    {"start_chapter": 181, "end_chapter": 200},
                ]
            },
            "chapters": [],
        }

        self.assertEqual(
            tab._chapter_plan_next_batch_info(state),
            (10, 1, 3, 151, 160),
        )
        state["chapters"] = [{"index": index} for index in range(151, 161)]
        self.assertEqual(
            tab._chapter_plan_next_batch_info(state),
            (20, 2, 3, 161, 180),
        )
        state["chapters"].extend({"index": index} for index in range(161, 181))
        self.assertEqual(
            tab._chapter_plan_next_batch_info(state),
            (20, 3, 3, 181, 200),
        )

    def test_numbered_export_chapter_title_uses_chinese_order_without_duplicate_prefix(self):
        self.assertEqual(_numbered_export_chapter_title(1, "开局被献祭"), "第一章 开局被献祭")
        self.assertEqual(_numbered_export_chapter_title(12, "第 99 章：旧标题"), "第十二章 旧标题")
        self.assertEqual(_numbered_export_chapter_title(101, "终局之前"), "第一百零一章 终局之前")

    def test_append_text_without_duplicate_overlap_removes_repeated_tail(self):
        existing = "第一段。\n\n第二段。"
        addition = "第二段。\n\n第三段。"

        text = _append_text_without_duplicate_overlap(existing, addition)

        self.assertEqual(text.count("第二段。"), 1)
        self.assertIn("第三段。", text)

    def test_character_list_text_is_single_line(self):
        text = _character_list_text(0, {"name": "赵图图", "role": "国公府世子\n系统宿主"})

        self.assertEqual(text, "赵图图  ·  国公府世子 系统宿主")
        self.assertNotIn("\n", text)

    def test_new_chapter_has_chapter_draft_words_field(self):
        chapter = _new_chapter(0)

        self.assertIn("draft_words", chapter)
        self.assertEqual(chapter["draft_words"], "")
        self.assertFalse(chapter["auto_expand_resume_required"])

    def test_normalize_project_coerces_auto_expand_resume_flag(self):
        project = _normalize_project({
            "chapters": [
                {"title": "第一章", "auto_expand_resume_required": "true"},
                {"title": "第二章", "auto_expand_resume_required": "false"},
            ],
        })

        self.assertTrue(project["chapters"][0]["auto_expand_resume_required"])
        self.assertFalse(project["chapters"][1]["auto_expand_resume_required"])
        self.assertNotIn(
            "auto_expand_resume_required",
            _project_without_private_notes(project)["chapters"][0],
        )

    def test_normalize_project_assigns_stable_foreshadow_codes(self):
        project = _normalize_project({
            "foreshadow_items": [
                {"name": "旧伏笔一", "code": ""},
                {"name": "旧伏笔二", "code": "F0001"},
                {"name": "旧伏笔三", "code": "F0001"},
            ],
        })

        codes = [item["code"] for item in project["foreshadow_items"]]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(codes[1], "F0001")
        self.assertTrue(all(code.startswith("F") for code in codes))

    def test_normalize_project_preserves_chapter_draft_words(self):
        project = _normalize_project({
            "chapters": [
                {"title": "第一章", "draft_words": "3200"},
                {"title": "第二章"},
            ],
        })

        self.assertEqual(project["chapters"][0]["draft_words"], "3200")
        self.assertEqual(project["chapters"][1]["draft_words"], "")

    def test_imported_chapter_plan_reference_is_saved_but_private(self):
        project = _normalize_project({
            "imported_chapter_plan_reference": {
                "summary": "导入章节总览",
                "source_title": "框架文件",
                "chapters": [
                    {
                        "index": 1,
                        "title": "第一章",
                        "outline": "主角得到线索。",
                        "characters": ["赵明"],
                        "source_event_ids": ["S01-E01"],
                    }
                ],
                "source": "local_framework_parser",
                "stages": [{
                    "id": "S01",
                    "name": "开局",
                    "start_chapter": 1,
                    "end_chapter": 3,
                    "events": [{"id": "S01-E01", "order": 1, "text": "主角得到线索。"}],
                }],
            }
        })

        self.assertEqual(project["imported_chapter_plan_reference"]["summary"], "导入章节总览")
        self.assertEqual(project["imported_chapter_plan_reference"]["chapters"][0]["title"], "第一章")
        self.assertEqual(
            project["imported_chapter_plan_reference"]["chapters"][0]["source_event_ids"],
            ["S01-E01"],
        )
        self.assertEqual(
            project["imported_chapter_plan_reference"]["stages"][0]["events"][0]["text"],
            "主角得到线索。",
        )
        self.assertNotIn("imported_chapter_plan_reference", _project_without_private_notes(project))

    def test_imported_chapter_plan_reference_drops_range_and_volume_titles(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        reference = tab._normalize_imported_chapter_plan_reference({
            "summary": "阶段规划",
            "chapters": [
                {"index": 1, "title": "第一章：开局", "outline": "主角醒来。"},
                {"index": 2, "title": "第4—10章：新婚立威", "outline": "阶段剧情。"},
                {"index": 3, "title": "第二卷：首辅夫人搞钱", "outline": "分卷剧情。"},
            ],
        })

        self.assertEqual([item["title"] for item in reference["chapters"]], ["第一章：开局"])

    def test_imported_framework_source_is_saved_with_verified_hash_but_private(self):
        source_text = "第一阶段：开局\n章节：第1—1章\n1. 主角苏醒。"
        project = _normalize_project({
            "imported_framework_source": {
                "source_title": "框架文件",
                "source_label": "Word",
                "source_path": "/tmp/框架.docx",
                "text": source_text,
                "sha256": "错误哈希",
                "imported_at": "2026-07-13 12:00:00",
            }
        })

        stored = project["imported_framework_source"]
        self.assertEqual(stored["text"], source_text)
        self.assertEqual(stored["sha256"], hashlib.sha256(source_text.encode("utf-8")).hexdigest())
        self.assertNotIn("imported_framework_source", _project_without_private_notes(project))

    def test_chapter_plan_generation_state_is_saved_but_private(self):
        project = _normalize_project({
            "chapter_plan_generation_state": {
                "version": 1,
                "status": "failed",
                "chapters": [{"index": 1, "title": "已完成批次"}],
            }
        })

        self.assertEqual(project["chapter_plan_generation_state"]["status"], "failed")
        self.assertNotIn("chapter_plan_generation_state", _project_without_private_notes(project))

    def test_confirmed_chapter_plan_foundation_persists_but_stays_out_of_body_context(self):
        project = _normalize_project({
            "chapter_plan_foundation": {
                "summary": "全书主线",
                "core_mainline": "成长与关系共同推进",
                "ending_promise": "终局兑现身份与关系承诺",
                "global_hard_boundaries": (
                    "不得扩大办案流程；未提供stages.events节点ID，"
                    "因此所有章节source_event_ids使用空数组，不虚构来源节点。"
                ),
                "target_words": 500000,
                "average_chapter_words": 5000,
                "total_chapter_count": 100,
                "existing_chapter_count": 0,
                "narrative_strategy_profile": {"primary_story_engine": "人物选择"},
                "arcs": [
                    {"name": "开局", "start_chapter": 1, "end_chapter": 30},
                    {"name": "发展与收束", "start_chapter": 31, "end_chapter": 100},
                ],
            },
            "narrative_strategy_confirmation": {
                "status": "confirmed",
                "profile_hash": "a" * 64,
                "foundation_hash": "b" * 64,
            },
        })

        foundation = project["chapter_plan_foundation"]
        self.assertEqual(foundation["total_chapter_count"], 100)
        self.assertEqual(foundation["arcs"][-1]["end_chapter"], 100)
        self.assertIn("身份与关系", foundation["ending_promise"])
        self.assertEqual(foundation["global_hard_boundaries"], "不得扩大办案流程。")
        self.assertEqual(
            project["narrative_strategy_confirmation"]["foundation_hash"],
            "b" * 64,
        )
        public_project = _project_without_private_notes(project)
        self.assertNotIn("chapter_plan_foundation", public_project)
        self.assertNotIn("narrative_strategy_confirmation", public_project)

    def test_chapter_list_text_shows_ai_analysis_status_instead_of_draft_words(self):
        chapter = _new_chapter(0)
        chapter["title"] = "章节1"
        chapter["status"] = "已完成"
        chapter["text"] = "正文内容"
        chapter["draft_words"] = "3000"

        text = _chapter_list_text(0, chapter)

        self.assertIn("待AI分析", text)
        self.assertNotIn("扩写约3000字", text)

        _mark_chapters_analyzed([chapter], [chapter["id"]])
        text = _chapter_list_text(0, chapter)

        self.assertIn("已AI分析", text)
        self.assertNotIn("扩写约3000字", text)
        self.assertTrue(chapter["analysis_baseline"])
        self.assertTrue(chapter["analysis_linked_hash"] or "linked_characters" in chapter)

    def test_outline_only_planned_chapter_is_not_pending_ai_analysis(self):
        chapter = _new_chapter(0)
        chapter["title"] = "规划章"
        chapter["outline"] = "AI 章节规划生成的提纲。"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.pending_analysis_chapter_ids = [chapter["id"]]

        text = _chapter_list_text(0, chapter)

        self.assertIn("未写正文", text)
        self.assertNotIn("待AI分析", text)
        self.assertEqual(tab._pending_candidate_analysis_chapter_ids(), [])

    def test_reset_chapter_for_ai_rewrite_clears_analysis_cache(self):
        chapter = _new_chapter(0)
        chapter.update({
            "text": "旧正文",
            "summary": "旧摘要",
            "key_facts": "旧关键事实",
            "memory_selection": {"fact_ids": ["AF-0001"]},
            "fact_lifecycle_review": {"reviewed_refs": ["AF-0001"]},
            "state_lifecycle_review": {"reviewed_object_keys": ["NOBJ001"]},
            "analysis_hash": "old-hash",
            "analysis_hash_version": CHAPTER_ANALYSIS_HASH_VERSION,
            "analysis_analyzed_at": "2026-08-01 00:00:00",
            "analysis_baseline": "旧分析基线",
            "analysis_linked_hash": "old-linked",
            "analysis_status": "current",
            "analysis_status_hash": "old-status",
            "analysis_status_version": "1",
        })

        self.assertTrue(NovelWritingTab._reset_chapter_data_for_ai_rewrite(chapter))

        self.assertEqual(chapter["text"], "")
        self.assertEqual(chapter["summary"], "")
        self.assertEqual(chapter["key_facts"], "")
        self.assertEqual(chapter["memory_selection"], {})
        self.assertEqual(chapter["fact_lifecycle_review"], {})
        self.assertEqual(chapter["state_lifecycle_review"], {})
        self.assertEqual(chapter["analysis_hash"], "")
        self.assertEqual(chapter["analysis_hash_version"], "")
        self.assertEqual(chapter["analysis_analyzed_at"], "")
        self.assertEqual(chapter["analysis_baseline"], "")
        self.assertEqual(chapter["analysis_linked_hash"], "")
        self.assertEqual(chapter["analysis_status"], "unwritten")
        self.assertEqual(chapter["analysis_status_hash"], "")
        self.assertEqual(chapter["analysis_status_version"], "1")

    def test_reset_foreshadow_runtime_state_keeps_writing_plan(self):
        project = {
            "foreshadow_items": [{
                "code": "F0001",
                "name": "旧账册缺页",
                "status": "已回收",
                "setup_chapter": "第3章",
                "payoff_chapter": "第20章",
                "description": "缺页指向幕后交易。",
                "revealed": "已经查到缺页被人取走。",
                "remaining_secret": "取走者的真实目的。",
                "notes": "保留到后期。",
            }],
        }

        self.assertEqual(
            NovelWritingTab._reset_foreshadow_runtime_state_for_ai_rewrite(project),
            1,
        )
        item = project["foreshadow_items"][0]
        self.assertEqual(item["status"], "未埋")
        self.assertEqual(item["revealed"], "")
        self.assertEqual(item["remaining_secret"], "")
        self.assertEqual(item["setup_chapter"], "第3章")
        self.assertEqual(item["payoff_chapter"], "第20章")
        self.assertEqual(item["description"], "缺页指向幕后交易。")
        self.assertEqual(item["notes"], "保留到后期。")

    def test_reset_all_chapters_refreshes_selected_editors_before_save(self):
        chapter = _new_chapter(0)
        chapter["text"] = "已经写入的正文"
        project = {
            "meta": {"title": "测试小说"},
            "chapters": [chapter],
            "foreshadow_items": [
                {"code": "F0001", "name": "第一个伏笔", "status": "已埋"},
                {"code": "F0002", "name": "第二个伏笔", "status": "已埋"},
            ],
            "long_form_memory": {"revision": 4},
        }
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = project
        tab.current_chapter_index = 0
        tab.current_foreshadow_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("预览")
        tab._chapter_clear_has_active_work = lambda: False
        tab._flush_current_editors = lambda: None
        tab._project_title = lambda: "测试小说"
        tab._reload_chapter_list = lambda index: None
        reload_calls = []
        editor_status = ["已埋"]

        def reload_foreshadow(index):
            reload_calls.append(index)
            editor_status[0] = project["foreshadow_items"][index]["status"]

        tab._reload_foreshadow_list = reload_foreshadow
        tab._set_partial_chapter_ai_preview_state = lambda _value: None
        tab._reset_chapter_ai_sequence = lambda: None
        tab._reset_chapter_ai_style_retry = lambda: None
        tab._note_project_dirty = lambda: None
        tab._notify_project_store_changed = lambda: None
        tab.set_status_tip = lambda _text: None

        def save_current_work(*_args, **_kwargs):
            # Model _save_current_work's final editor flush. A stale editor
            # would write the old selected status back into the project.
            project["foreshadow_items"][0]["status"] = editor_status[0]
            return "/tmp/test-novel.json"

        tab._save_current_work = save_current_work

        with patch("gpt_desktop.novel_writing_tab.QMessageBox.question", return_value=QMessageBox.Yes), \
            patch("gpt_desktop.novel_writing_tab.unique_project_backup_path", return_value="/tmp/test-backup.json"), \
            patch("gpt_desktop.novel_writing_tab.save_project_file"):
            tab.reset_all_chapters()

        self.assertEqual(reload_calls, [0])
        self.assertEqual(
            [item["status"] for item in project["foreshadow_items"]],
            ["未埋", "未埋"],
        )

    def test_chapter_list_text_shows_small_change_for_minor_edit(self):
        chapter = _new_chapter(0)
        chapter["title"] = "章节1"
        chapter["status"] = "已完成"
        chapter["text"] = "正文内容很多。" * 80
        _mark_chapters_analyzed([chapter], [chapter["id"]])

        chapter["text"] += "补充几字。"
        text = _chapter_list_text(0, chapter)

        self.assertIn("小改", text)
        self.assertNotIn("待AI分析", text)

    def test_chapter_list_text_uses_cached_analysis_status(self):
        chapter = _new_chapter(0)
        chapter["title"] = "章节1"
        chapter["status"] = "已完成"
        chapter["text"] = "正文内容很多。" * 1000
        _mark_chapters_analyzed([chapter], [chapter["id"]])
        chapter["text"] += "补充几字。"
        text = _chapter_list_text(0, chapter)
        self.assertIn("小改", text)

        with patch("gpt_desktop.novel_utils._chapter_analysis_diff_ratio", side_effect=AssertionError("should use cache")):
            cached_text = _chapter_list_text(0, chapter)

        self.assertIn("小改", cached_text)

    def test_chapter_analysis_status_cache_refreshes_after_text_change(self):
        chapter = _new_chapter(0)
        chapter["title"] = "章节1"
        chapter["text"] = "赵明进入王城。" * 100
        _mark_chapters_analyzed([chapter], [chapter["id"]])
        self.assertIn("已AI分析", _chapter_list_text(0, chapter))

        chapter["text"] = "苏秦离开边城。" * 100
        _update_chapter_analysis_status_cache(chapter)

        self.assertIn("待AI分析", _chapter_list_text(0, chapter))

    def test_chapter_analysis_diff_returns_fast_when_length_delta_exceeds_small_change(self):
        old_text = "旧正文" * 3000
        new_text = old_text + ("新增正文" * 500)

        ratio = _chapter_analysis_diff_ratio(old_text, new_text)

        self.assertGreater(ratio, 0.10)
        self.assertAlmostEqual(ratio, (len(new_text) - len(old_text)) / len(new_text))

    def test_project_meta_text_includes_summary_fact_words(self):
        chapter = _new_chapter(0)
        chapter["text"] = "正文内容"
        chapter["outline"] = "章节提纲"
        chapter["summary"] = "本章摘要"
        chapter["key_facts"] = "关键事实"
        project = {
            "meta": {"target_words": "100"},
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "bible": "小说圣经",
            "world_rules": "世界观",
        }

        text = _project_meta_text(project, "自动草稿")

        self.assertIn("圣经 7", text)
        self.assertIn("正文 4/100", text)
        self.assertIn("大纲 4", text)
        self.assertIn("摘要/事实 9", text)

    def test_visible_body_word_count_ignores_whitespace(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["status"] = "已完成"
        chapter["text"] = "正文 一\n\n正文 二"
        project = {
            "meta": {"title": "测试书", "target_words": "100"},
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
        }

        self.assertIn("正文 6/100", _project_meta_text(project, "测试书"))
        self.assertIn("测试书  ·  6字正文  ·  1章", _project_list_text(project, "测试书"))
        self.assertIn("6字", _chapter_list_text(0, chapter))

    def test_project_summary_records_use_visible_body_word_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "测试书.json"
            path.write_text(
                json.dumps({
                    "meta": {"title": "测试书"},
                    "chapters": [{"title": "第一章", "text": "正文 一\n\n正文 二"}],
                }, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch("gpt_desktop.novel_storage.list_project_files", return_value=[(1, path.name, str(path))]):
                records = list_project_summaries()

        self.assertEqual(records[0]["body_words"], 6)

    def test_search_results_show_chapter_field_matches(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第八章 赴约"
        chapter["outline"] = "雨夜抵达老宅。"
        chapter["text"] = "京城入夜后下了一场短雨。\n\n陈景川望着前方，雨后的长街空旷。"
        chapter["key_facts"] = "陈景川望着前方，雨后的长街空旷，决定赴京郊南仓。"
        project = {"chapters": [chapter]}

        text = _build_search_result_text(project, "雨")

        self.assertIn("[章节 / 提纲] 第八章 赴约", text)
        self.assertIn("[章节 / 正文] 第八章 赴约", text)
        self.assertIn("[章节 / 关键事实] 第八章 赴约", text)
        self.assertIn("雨后的长街空旷", text)
        self.assertIn("共 2 处", text)

    def test_search_results_cover_current_project_all_visible_content(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["draft_words"] = "测试锚点"
        foreshadow = _new_foreshadow(0)
        foreshadow["name"] = "权限会议"
        foreshadow["notes"] = "体检备注含测试锚点"
        project = {
            "meta": {"title": "书名"},
            "draft_note": "草稿备注含测试锚点",
            "style_reference": "后台文风样本含测试锚点",
            "chapters": [chapter],
            "foreshadow_items": [foreshadow],
            "import_candidates": {
                "characters": [{"name": "候选人物", "notes": "候选人物含测试锚点"}],
                "lore": [{"name": "候选设定", "description": "候选设定含测试锚点"}],
                "foreshadows": [{"name": "候选伏笔", "description": "候选伏笔含测试锚点"}],
                "project_materials": {"summary": "候选资料含测试锚点"},
            },
        }

        text = _build_search_result_text(project, "测试锚点")

        self.assertIn("[全局备注] 全局备注", text)
        self.assertIn("[章节 / 扩写字数] 第一章", text)
        self.assertIn("[伏笔 / 备注] 权限会议", text)
        self.assertIn("[候选人物 / 备注] 候选人物", text)
        self.assertIn("[候选设定 / 说明] 候选设定", text)
        self.assertIn("[候选伏笔 / 说明] 候选伏笔", text)
        self.assertNotIn("[候选资料] 摘要 / 日志", text)
        self.assertNotIn("后台文风样本含测试锚点", text)

    def test_save_current_fields_persists_global_note(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._loading = False
        tab.current_chapter_index = -1
        tab.current_project = {
            "meta": {},
            "chapters": [],
            "foreshadow_items": [],
            "timeline": "导入后保留的隐藏时间线",
            "summary": "导入后保留的隐藏全局摘要",
        }
        tab.title_edit = _FakeLineEdit("测试小说")
        tab.genre_edit = _FakeLineEdit("都市")
        tab.style_edit = _FakeLineEdit("爽文")
        tab.pov_combo = _FakeComboBox(["第三人称"], "第三人称")
        tab.target_words_edit = _FakeLineEdit("200000")
        tab.status_combo = _FakeComboBox(["草稿"], "草稿")
        tab.premise_edit = _FakePlainTextEdit("核心设定")
        tab.bible_edit = _FakePlainTextEdit("小说圣经")
        tab.world_rules_edit = _FakePlainTextEdit("世界规则")
        tab.draft_note_edit = _FakePlainTextEdit("只给自己看的长篇提醒")

        tab._save_current_fields()

        self.assertEqual(tab.current_project["draft_note"], "只给自己看的长篇提醒")
        self.assertEqual(tab.current_project["timeline"], "导入后保留的隐藏时间线")
        self.assertEqual(tab.current_project["summary"], "导入后保留的隐藏全局摘要")

    def test_update_stats_label_uses_project_title_not_import_filename(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"meta": {"title": "《什么鬼系统？见谁都是四六开》第一季"}, "chapters": []}
        tab.current_project_path = "/tmp/《什么鬼系统？见谁都是四六开》框架.json"
        tab.project_meta_label = _FakeLabel()

        tab._update_stats_label()

        self.assertIn("第一季", tab.project_meta_label.text)
        self.assertNotIn("框架", tab.project_meta_label.text)
        self.assertIn("框架.json", tab.project_meta_label.tooltip)

    def test_edge_tts_worker_accepts_rate_argument(self):
        worker = EdgeTTSWorker("文本", "/tmp/test.mp3", rate="+20%")

        self.assertEqual(worker.rate, "+20%")

    def test_edge_tts_worker_stop_marks_stop_requested(self):
        worker = EdgeTTSWorker("文本", "/tmp/test.mp3")

        worker.stop()

        self.assertTrue(worker._stop_requested)

    def test_edge_tts_server_date_parser_accepts_english_rfc_date(self):
        parsed = _parse_edge_tts_server_date("Thu, 15 Oct 2026 02:41:15 GMT")

        self.assertIsInstance(parsed, float)
        expected = datetime(2026, 10, 15, 2, 41, 15, tzinfo=timezone.utc).timestamp()
        self.assertEqual(parsed, expected)

    def test_novel_default_read_aloud_rate_exists(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.config = {"novel": {}}

        self.assertEqual(tab._read_aloud_rate_from_config(), "+0%")

    def test_read_aloud_rate_is_generation_only(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.config = {"novel": {"read_aloud_rate": "+20%"}}
        tab.read_aloud_speed_override = None

        self.assertEqual(tab._current_read_aloud_rate(), "+20%")

    def test_set_read_aloud_rate_updates_override(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.config = {"novel": {}}
        tab.read_aloud_player = None

        tab._set_read_aloud_rate("+20%", persist=False)

        self.assertEqual(tab.read_aloud_speed_override, "+20%")

    def test_selected_read_aloud_text_defaults_to_current_chapter(self):
        first = _new_chapter(0)
        first["title"] = "第一章"
        first["text"] = "第一章正文"
        second = _new_chapter(1)
        second["title"] = "第二章"
        second["text"] = "第二章正文"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"meta": {"title": "书名"}, "chapters": [first, second]}
        tab.current_chapter_index = 1
        tab.read_aloud_scope = "current"
        tab._flush_current_editors = lambda: None

        text, error, label = tab._selected_read_aloud_text()

        self.assertEqual(error, "")
        self.assertEqual(label, "第二章")
        self.assertIn("第二章正文", text)
        self.assertNotIn("第一章正文", text)

    def test_selected_read_aloud_text_can_read_all_or_specific_chapter(self):
        first = _new_chapter(0)
        first["title"] = "第一章"
        first["text"] = "第一章正文"
        second = _new_chapter(1)
        second["title"] = "第二章"
        second["text"] = "第二章正文"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"meta": {"title": "书名"}, "chapters": [first, second]}
        tab.current_chapter_index = 0
        tab._flush_current_editors = lambda: None

        tab.read_aloud_scope = "all"
        all_text, error, label = tab._selected_read_aloud_text()
        self.assertEqual(error, "")
        self.assertEqual(label, "书稿")
        self.assertIn("第一章正文", all_text)
        self.assertIn("第二章正文", all_text)

        tab.read_aloud_scope = f"chapter:{second['id']}"
        chapter_text, error, label = tab._selected_read_aloud_text()
        self.assertEqual(error, "")
        self.assertEqual(label, "第二章")
        self.assertIn("第二章正文", chapter_text)
        self.assertNotIn("第一章正文", chapter_text)

    def test_read_aloud_retire_calls_worker_stop(self):
        class FakeWorker:
            def __init__(self):
                self.stopped = False

            def stop(self):
                self.stopped = True

        worker = FakeWorker()
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.read_aloud_worker = worker
        tab.read_aloud_worker_index = 0
        tab.read_aloud_retired_workers = []

        tab._retire_read_aloud_worker()

        self.assertTrue(worker.stopped)
        self.assertIsNone(tab.read_aloud_worker)
        self.assertEqual(tab.read_aloud_worker_index, -1)
        self.assertIn(worker, tab.read_aloud_retired_workers)

    def test_read_aloud_starts_new_segment_while_old_worker_is_retired(self):
        class RetiredWorker:
            output_path = "/tmp/old-read-aloud.mp3"

        class FakeWorker:
            instances = []

            def __init__(self, text, output_path, rate="+0%"):
                self.text = text
                self.output_path = output_path
                self.rate = rate
                self.started = False
                self.progress = _FakeSignal()
                self.result_ready = _FakeSignal()
                self.failed = _FakeSignal()
                self.finished = _FakeSignal()
                FakeWorker.instances.append(self)

            def start(self):
                self.started = True

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.read_aloud_segments = [{"text": "新的朗读内容", "file": "", "ready": False}]
        tab.read_aloud_worker = None
        tab.read_aloud_worker_index = -1
        tab.read_aloud_retired_workers = [RetiredWorker()]
        tab.read_aloud_pending_segment = None
        tab._segment_audio_path = lambda: "/tmp/new-read-aloud.mp3"
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)

        with patch("gpt_desktop.novel_writing_tab.EdgeTTSWorker", FakeWorker):
            tab._ensure_read_aloud_segment(0, autoplay=True, start_position=0)

        self.assertEqual(len(FakeWorker.instances), 1)
        self.assertIs(tab.read_aloud_worker, FakeWorker.instances[0])
        self.assertTrue(FakeWorker.instances[0].started)
        self.assertIsNone(tab.read_aloud_pending_segment)
        self.assertNotIn("等待上一段语音生成线程结束", "\n".join(statuses))

    def test_previous_writing_worker_is_retained_until_finished(self):
        old_worker = object()
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.writing_worker = old_worker
        tab.writing_retired_workers = []

        tab._retain_previous_writing_worker()

        self.assertIsNone(tab.writing_worker)
        self.assertEqual(tab.writing_retired_workers, [old_worker])

    def test_previous_writing_worker_is_not_retained_twice(self):
        old_worker = object()
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.writing_worker = old_worker
        tab.writing_retired_workers = [old_worker]

        tab._retain_previous_writing_worker()

        self.assertIsNone(tab.writing_worker)
        self.assertEqual(tab.writing_retired_workers, [old_worker])

    def test_auto_expand_all_skips_chapters_with_existing_body(self):
        first = _new_chapter(0)
        first["text"] = "已有正文"
        first["summary"] = "已有摘要"
        first["key_facts"] = "已有关键事实"
        second = _new_chapter(1)
        third = _new_chapter(2)
        third["text"] = "也有正文"
        third["summary"] = "也有摘要"
        third["key_facts"] = "也有关键事实"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [first, second, third]}

        self.assertEqual(tab._auto_expand_pending_indexes(), [1])

    def test_auto_expand_progress_uses_absolute_chapter_position_after_restart(self):
        chapters = [_new_chapter(index) for index in range(250)]
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": chapters}
        tab.current_chapter_index = 11
        tab._auto_expand_all_active = True
        tab._auto_expand_all_waiting_next = False
        tab._auto_expand_all_total = 239
        tab._auto_expand_all_completed = 4
        tab._auto_expand_all_current_chapter_id = chapters[11]["id"]
        tab.auto_expand_all_btn = _FakeButton()

        tab._set_auto_expand_all_button_text()

        self.assertEqual(tab._auto_expand_all_chapter_progress(), (12, 250))
        self.assertEqual(tab.auto_expand_all_btn.text, "自动扩写全部 12/250")

    def test_auto_expand_status_uses_same_absolute_progress_as_button(self):
        chapters = [_new_chapter(index) for index in range(250)]
        chapters[11]["title"] = "重新开始后的章节"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": chapters}
        tab.current_chapter_index = 11
        tab._auto_expand_all_active = True
        tab._auto_expand_all_waiting_next = False
        tab._auto_expand_all_total = 239
        tab._auto_expand_all_completed = 4
        tab._auto_expand_all_current_chapter_id = chapters[11]["id"]
        tab._status_message = "正文已生成，正在专门审校并修订正文终稿..."
        tab._status_stage_label = "仿写终稿"
        tab._status_stage_active = False
        tab._status_stage_key = ""
        tab._status_stage_started_wall = 0.0
        tab._status_stage_started_at = 0.0
        tab._status_workflow_active = True
        tab._status_workflow_started_at = 0.0
        tab._status_last_run_elapsed = 0.0
        tab._status_history = []
        tab._status_has_active_work = lambda: True
        tab.status_label = _FakeLabel()
        tab.status_meta_label = _FakeLabel()

        tab._refresh_status_display()

        self.assertIn("自动扩写 12/250", tab.status_meta_label.text)
        self.assertNotIn("4/239", tab.status_meta_label.text)

    def test_auto_expand_stop_before_worker_start_unlocks_actions(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._auto_expand_all_active = True
        tab._auto_expand_all_waiting_next = False
        tab._auto_expand_all_current_chapter_id = "chapter-1"
        tab._chapter_ai_transient_retry_pending = False
        tab.writing_worker = None
        tab.chapter_plan_worker = None
        tab._set_auto_expand_all_button_text = lambda: None
        tab._log_novel_diagnostic = lambda *_args, **_kwargs: None
        tab.set_status_tip = lambda _text: None
        enabled = []
        tab._set_chapter_ai_actions_enabled = enabled.append

        tab._stop_auto_expand_all("自动扩写已停止：上下文组装失败。")

        self.assertEqual(enabled, [True])
        self.assertFalse(tab._auto_expand_all_active)

    def test_auto_expand_restart_discards_partial_draft_instead_of_resuming_it(self):
        chapter = _new_chapter(0)
        chapter["outline"] = "本章完整提纲"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("中止时留下的半句正文")
        tab.chapter_ai_stream_text = "中止时留下的半句正文"
        tab._chapter_ai_preview_is_partial = True
        tab._chapter_ai_preview_action = "draft"
        tab._chapter_ai_preview_chapter_id = chapter["id"]
        tab._chapter_ai_resume_prefix = "中止时留下的半句正文"
        tab._chapter_ai_sequence_active = True
        tab._chapter_ai_sequence_chapter_id = chapter["id"]
        tab._chapter_ai_buttons_by_action = {}
        snapshots = []
        events = []
        tab._save_chapter_ai_failure_snapshot = lambda action, request_id, **kwargs: snapshots.append(
            (action, request_id, kwargs)
        ) or "/tmp/partial-preview.json"
        tab._log_novel_diagnostic = lambda event, **kwargs: events.append((event, kwargs))

        self.assertTrue(tab._discard_partial_preview_for_auto_rewrite())

        self.assertEqual(tab.chapter_ai_preview.toPlainText(), "")
        self.assertEqual(tab.chapter_ai_stream_text, "")
        self.assertEqual(tab._chapter_ai_resume_prefix, "")
        self.assertFalse(tab._chapter_ai_sequence_active)
        self.assertFalse(tab._has_partial_chapter_ai_preview())
        self.assertEqual(chapter["text"], "")
        self.assertEqual(snapshots[0][0], "draft")
        self.assertEqual(events[0][0], "auto_expand_partial_preview_discarded")
        self.assertEqual(events[0][1]["restart_mode"], "rewrite")

    def test_auto_expand_start_marks_partial_preview_for_clean_rewrite(self):
        chapter = _new_chapter(0)
        chapter["outline"] = "本章完整提纲"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab.writing_worker = None
        tab.chapter_plan_worker = None
        tab._auto_expand_all_active = False
        tab._current_novel_ai_selection = lambda: ({"id": "provider"}, "model", "")
        tab._flush_current_editors = lambda: None
        discard_calls = []
        tab._discard_partial_preview_for_auto_rewrite = lambda: discard_calls.append(True) or True
        tab._persist_completed_auto_expand_resume_flags = lambda: True
        tab._auto_expand_pending_indexes = lambda: [0]
        tab._status_begin_workflow = lambda kind="": None
        tab._log_novel_diagnostic = lambda *_args, **_kwargs: None
        tab._set_auto_expand_all_button_text = lambda: None
        action_enabled = []
        tab._set_chapter_ai_actions_enabled = action_enabled.append
        started = []
        tab._start_next_auto_expand_chapter = lambda: started.append(True)

        with patch("gpt_desktop.novel_writing_tab.QTimer.singleShot") as single_shot:
            tab.start_auto_expand_all_chapters()

        self.assertEqual(discard_calls, [True])
        self.assertTrue(tab._auto_expand_all_active)
        self.assertTrue(tab._auto_expand_restart_rewrite_notice)
        self.assertEqual(action_enabled, [False])
        self.assertEqual(started, [])
        self.assertEqual(single_shot.call_count, 1)
        self.assertEqual(single_shot.call_args.args[0], 0)

    def test_auto_expand_all_resumes_existing_body_missing_postwrite_materials(self):
        chapter = _new_chapter(0)
        chapter["text"] = "已经写入的正文"
        chapter["summary"] = ""
        chapter["key_facts"] = ""
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "long_form_memory": {"revision": 0}}

        self.assertEqual(tab._auto_expand_pending_indexes(), [0])

    def test_auto_expand_all_resumes_failed_existing_body(self):
        chapter = _new_chapter(0)
        chapter["text"] = "已经写入的正文"
        chapter["summary"] = "已有摘要"
        chapter["key_facts"] = "已有关键事实"
        chapter["memory_sync_status"] = "failed"
        chapter["memory_sync_error"] = "状态事务未能提交"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "long_form_memory": {"revision": 3}}

        self.assertEqual(tab._auto_expand_pending_indexes(), [0])

    def test_auto_expand_all_resumes_checkpoint_after_body_was_written(self):
        chapter = _new_chapter(0)
        chapter["outline"] = "原规划提纲"
        chapter["text"] = "已经完成审校的正文终稿。"
        chapter["summary"] = "已有摘要"
        chapter["key_facts"] = "已有关键事实"
        chapter["ai_generation_checkpoint"] = {
            "version": 1,
            "stage": "memory_finalize",
            "chapter_id": chapter["id"],
            "final_text": chapter["text"],
            "final_text_sha256": NovelWritingTab._chapter_ai_checkpoint_hash(chapter["text"]),
            "source_text_sha256": NovelWritingTab._chapter_ai_checkpoint_hash(""),
            "outline_sha256": NovelWritingTab._chapter_ai_checkpoint_hash(chapter["outline"]),
            "base_memory_revision": 7,
        }
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "long_form_memory": {"revision": 7}}

        self.assertEqual(tab._auto_expand_pending_indexes(), [0])

    def test_auto_expand_all_skips_fully_committed_chapter_with_stale_resume_flag(self):
        chapter = _new_chapter(0)
        chapter["text"] = "完整正文"
        chapter["summary"] = "完整摘要"
        chapter["key_facts"] = "完整关键事实"
        chapter["memory_sync_status"] = "complete"
        chapter["memory_revision"] = 2
        chapter["memory_update_hash"] = "verified-update-hash"
        chapter["auto_expand_resume_required"] = True
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "long_form_memory": {"revision": 5}}

        self.assertEqual(tab._auto_expand_pending_indexes(), [])

    def test_auto_expand_retries_only_save_for_fully_committed_stale_resume_flag(self):
        chapter = _new_chapter(0)
        chapter["text"] = "完整正文"
        chapter["summary"] = "完整摘要"
        chapter["key_facts"] = "完整关键事实"
        chapter["memory_sync_status"] = "complete"
        chapter["memory_revision"] = 2
        chapter["memory_update_hash"] = "verified-update-hash"
        chapter["auto_expand_resume_required"] = True
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "long_form_memory": {"revision": 5}}
        saved_flags = []
        tab._save_current_work = lambda *_args, **_kwargs: saved_flags.append(
            chapter["auto_expand_resume_required"]
        ) or "/tmp/project.json"
        tab._note_project_dirty = lambda: None

        self.assertTrue(tab._persist_completed_auto_expand_resume_flags())
        self.assertEqual(saved_flags, [False])
        self.assertFalse(chapter["auto_expand_resume_required"])

    def test_auto_expand_save_retry_failure_restores_completed_resume_flag(self):
        chapter = _new_chapter(0)
        chapter["text"] = "完整正文"
        chapter["summary"] = "完整摘要"
        chapter["key_facts"] = "完整关键事实"
        chapter["memory_sync_status"] = "complete"
        chapter["memory_revision"] = 2
        chapter["memory_update_hash"] = "verified-update-hash"
        chapter["auto_expand_resume_required"] = True
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "long_form_memory": {"revision": 5}}
        tab._save_current_work = lambda *_args, **_kwargs: ""
        tab._note_project_dirty = lambda: None
        tab.set_status_tip = lambda text: setattr(tab, "last_status", text)

        self.assertFalse(tab._persist_completed_auto_expand_resume_flags())
        self.assertTrue(chapter["auto_expand_resume_required"])
        self.assertIn("保存失败", tab.last_status)

    def test_model_list_failure_keeps_configured_custom_model_selected(self):
        class FakeModelBar:
            def __init__(self):
                self.models = []
                self.selected = ""
                self.status = ""

            def set_models(self, models, current):
                self.models = list(models)
                self.selected = current

            def set_status(self, text):
                self.status = text

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.config = {
            "novel": {
                "provider_id": "provider-1",
                "model": "gpt-5.6-sol",
                "model_by_provider": {"provider-1": "gpt-5.6-sol"},
            },
            "model_cache": {},
        }
        tab.bar = FakeModelBar()
        tab._is_current_model_request = lambda _provider_id, _request_id: True
        tab.refresh_ai_settings_summary = lambda: None

        with patch("gpt_desktop.model_bar_mixin.save_config"):
            tab.on_models_failed("provider-1", "request-1", "模型列表加载失败")

        self.assertEqual(tab.bar.selected, "gpt-5.6-sol")
        self.assertEqual(tab.bar.models[0], "gpt-5.6-sol")
        self.assertIn("gpt-4o-mini", tab.bar.models)

    def test_novel_loaded_models_drop_model_from_previous_provider(self):
        class FakeModelBar:
            def __init__(self):
                self.models = []
                self.selected = ""
                self.status = ""

            def set_models(self, models, current):
                self.models = list(models)
                self.selected = current

            def set_status(self, text):
                self.status = text

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.config = {
            "novel": {
                "provider_id": "provider-image",
                "model": "gpt-5.6-sol-免费",
            },
            "model_cache": {
                "provider-image": ["gpt-image-2", "gpt-image-2-4k"],
            },
        }
        tab.bar = FakeModelBar()
        tab._is_current_model_request = lambda _provider_id, _request_id: True
        tab.refresh_ai_settings_summary = lambda: None

        with patch("gpt_desktop.model_bar_mixin.save_config"):
            tab.on_models_loaded(
                "provider-image",
                "request-1",
                ["gpt-image-2", "gpt-image-2-4k"],
            )

        self.assertEqual(tab.bar.models, ["gpt-image-2", "gpt-image-2-4k"])
        self.assertEqual(tab.bar.selected, "gpt-image-2")
        self.assertNotIn("gpt-5.6-sol-免费", tab.bar.models)
        self.assertEqual(tab.config["novel"]["model"], "gpt-image-2")

    def test_auto_expand_sequence_keeps_batch_locked_provider_and_model(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab._auto_expand_all_active = True
        tab._chapter_ai_provider = {"id": "locked-provider", "name": "锁定厂商"}
        tab._chapter_ai_model = "gpt-5.6-sol"
        tab._current_novel_ai_selection = lambda: self.fail("自动扩写批次中不应重新读取已漂移的下拉框")
        tab.chapter_outline = _FakePlainTextEdit("章节提纲")
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab._reset_chapter_ai_style_retry = lambda: None
        tab._set_partial_chapter_ai_preview_state = lambda *_args: None
        tab._chapter_ai_context_with_preview = lambda _action: "章节上下文"
        started = []
        tab._start_style_locked_draft = lambda context: started.append(
            (context, tab._chapter_ai_provider["id"], tab._chapter_ai_model)
        )

        tab._start_chapter_ai_sequence()

        self.assertEqual(started, [("章节上下文", "locked-provider", "gpt-5.6-sol")])
        self.assertEqual(chapter["memory_sync_status"], "pending")
        self.assertTrue(chapter["auto_expand_resume_required"])

    def test_auto_expand_sequence_rewrites_existing_body_with_stale_checkpoint(self):
        chapter = _new_chapter(0)
        chapter["outline"] = "本章完整提纲"
        chapter["text"] = "已经写入章节的正文。"
        chapter["summary"] = "半成品摘要"
        chapter["key_facts"] = "半成品事实"
        chapter["ai_generation_checkpoint"] = {
            "version": 1,
            "stage": "memory_finalize",
            "status": "pending",
            "chapter_id": chapter["id"],
            "final_text": chapter["text"],
            "final_text_sha256": NovelWritingTab._chapter_ai_checkpoint_hash(chapter["text"]),
            "source_text_sha256": NovelWritingTab._chapter_ai_checkpoint_hash(chapter["text"]),
            "outline_sha256": NovelWritingTab._chapter_ai_checkpoint_hash(chapter["outline"]),
            "base_memory_revision": 3,
        }
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "long_form_memory": {"schema_version": "2", "revision": 4},
        }
        tab.current_chapter_index = 0
        tab._auto_expand_all_active = True
        tab._chapter_ai_provider = {"id": "locked-provider", "name": "锁定厂商"}
        tab._chapter_ai_model = "gpt-5.6-sol"
        tab.chapter_outline = _FakePlainTextEdit("")
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab._chapter_ai_buttons_by_action = {}
        tab._flush_current_editors = lambda: None
        tab._set_partial_chapter_ai_preview_state = lambda *_args: None
        tab._persist_ai_generation_state = lambda: None
        tab._chapter_ai_context_with_preview = lambda _action: "重写上下文"
        started = []
        tab._start_style_locked_draft = lambda context: started.append(context)
        tab._start_memory_finalize = lambda *_args, **_kwargs: self.fail("半成品不应续跑状态整理")

        tab._start_chapter_ai_sequence()

        self.assertEqual(started, ["重写上下文"])
        self.assertEqual(chapter["text"], "")
        self.assertEqual(chapter["summary"], "")
        self.assertEqual(chapter["key_facts"], "")
        self.assertEqual(chapter["ai_generation_checkpoint"], {})
        self.assertTrue(chapter["auto_expand_resume_required"])
        self.assertEqual(chapter["memory_sync_status"], "pending")

    def test_manual_sequence_preserves_existing_body_for_metadata(self):
        chapter = _new_chapter(0)
        chapter["outline"] = "保留的完整章节提纲"
        chapter["text"] = "未完成正文"
        chapter["summary"] = "未完成摘要"
        chapter["key_facts"] = "未完成关键事实"
        chapter["actual_linked_character_ids"] = ["C1"]
        chapter["state_delta"] = {"characters": [{"id": "C1"}]}
        chapter["long_term_events"] = [{"event": "未提交事件"}]
        chapter["memory_sync_status"] = "failed"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "long_form_memory": {"schema_version": "2", "revision": 0},
        }
        tab.current_chapter_index = 0
        tab._auto_expand_all_active = False
        tab._current_novel_ai_selection = lambda: ({"id": "provider"}, "model", "")
        tab._flush_current_editors = lambda: None
        tab._persist_ai_generation_state = lambda: None
        tab.chapter_outline = _FakePlainTextEdit(chapter["outline"])
        tab.chapter_text = _FakePlainTextEdit(chapter["text"])
        tab.chapter_summary = _FakePlainTextEdit(chapter["summary"])
        tab.chapter_key_facts = _FakePlainTextEdit(chapter["key_facts"])
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab._chapter_ai_buttons_by_action = {}
        started = []
        tab._chapter_ai_context_with_preview = lambda _action: self.fail(
            "已有正文不应重新进入初稿流程"
        )
        tab._start_memory_finalize = lambda text, resumed=False: started.append((text, resumed))

        tab._start_chapter_ai_sequence()

        self.assertEqual(started, [("未完成正文", False)])
        self.assertEqual(chapter["text"], "未完成正文")
        self.assertEqual(chapter["summary"], "未完成摘要")
        self.assertEqual(chapter["key_facts"], "未完成关键事实")
        self.assertEqual(chapter["outline"], "保留的完整章节提纲")
        self.assertEqual(chapter["actual_linked_character_ids"], ["C1"])
        self.assertEqual(chapter["state_delta"], {"characters": [{"id": "C1"}]})
        self.assertEqual(chapter["long_term_events"], [{"event": "未提交事件"}])
        self.assertEqual(chapter["memory_sync_status"], "pending")
        self.assertTrue(chapter["auto_expand_resume_required"])

    def test_manual_sequence_blocks_already_committed_chapter(self):
        chapter = _new_chapter(0)
        chapter.update({
            "text": "完整正文",
            "summary": "完整摘要",
            "key_facts": "完整关键事实",
            "memory_sync_status": "complete",
            "memory_revision": 1,
            "memory_update_hash": "committed-hash",
        })
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "long_form_memory": {"revision": 1},
        }
        tab.current_chapter_index = 0
        tab._auto_expand_all_active = False
        tab._current_novel_ai_selection = lambda: ({"id": "provider"}, "model", "")
        tab.set_status_tip = lambda text: setattr(tab, "_status", text)

        with patch("gpt_desktop.novel_writing_tab.QMessageBox.information") as information:
            tab._start_chapter_ai_sequence()

        information.assert_called_once()
        self.assertIn("不能再次扩写", tab._status)
        self.assertEqual(chapter["text"], "完整正文")
        self.assertFalse(getattr(tab, "_chapter_ai_sequence_active", False))

    def test_auto_sequence_stops_when_committed_chapter_material_was_cleared(self):
        chapter = _new_chapter(0)
        chapter.update({
            "text": "",
            "summary": "原摘要",
            "key_facts": "原关键事实",
            "memory_sync_status": "complete",
            "memory_revision": 1,
            "memory_update_hash": "committed-hash",
        })
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "long_form_memory": {"revision": 1},
        }
        tab.current_chapter_index = 0
        tab._auto_expand_all_active = True
        tab._chapter_ai_provider = {"id": "provider"}
        tab._chapter_ai_model = "model"
        stopped = []
        tab._stop_auto_expand_all = stopped.append

        tab._start_chapter_ai_sequence()

        self.assertEqual(len(stopped), 1)
        self.assertIn("长期状态已提交", stopped[0])
        self.assertFalse(getattr(tab, "_chapter_ai_sequence_active", False))

    def test_existing_body_enters_state_finalization_without_overwrite(self):
        chapter = _new_chapter(0)
        chapter["text"] = "上下文失败前的未完成正文"
        chapter["summary"] = "上下文失败前的摘要"
        chapter["key_facts"] = "上下文失败前的关键事实"
        chapter["memory_sync_status"] = "failed"
        chapter["memory_sync_error"] = "原状态错误"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "long_form_memory": {"revision": 0}}
        tab.current_chapter_index = 0
        tab._auto_expand_all_active = False
        tab._current_novel_ai_selection = lambda: ({"id": "provider"}, "model", "")
        tab.chapter_outline = _FakePlainTextEdit("章节提纲")
        tab.chapter_text = _FakePlainTextEdit(chapter["text"])
        tab.chapter_summary = _FakePlainTextEdit(chapter["summary"])
        tab.chapter_key_facts = _FakePlainTextEdit(chapter["key_facts"])
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab._chapter_ai_buttons_by_action = {}
        tab._chapter_ai_context_with_preview = lambda _action: self.fail(
            "已有正文不应重新构建正文上下文"
        )
        tab._persist_ai_generation_state = lambda: None
        finalized = []
        tab._start_memory_finalize = lambda text, resumed=False: finalized.append((text, resumed))

        tab._start_chapter_ai_sequence()

        self.assertEqual(finalized, [("上下文失败前的未完成正文", False)])
        self.assertEqual(chapter["memory_sync_status"], "pending")
        self.assertEqual(chapter["memory_sync_error"], "")
        self.assertEqual(chapter["text"], "上下文失败前的未完成正文")
        self.assertEqual(tab.chapter_text.toPlainText(), "上下文失败前的未完成正文")
        self.assertEqual(chapter["summary"], "上下文失败前的摘要")
        self.assertEqual(chapter["key_facts"], "上下文失败前的关键事实")
        self.assertTrue(chapter["auto_expand_resume_required"])

    def test_auto_expand_existing_body_can_recover_without_outline(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["text"] = "已有正文，正在等待状态恢复。"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "long_form_memory": {"revision": 0}}
        tab.current_chapter_index = 0
        tab._auto_expand_all_active = True
        tab._auto_expand_all_waiting_next = False
        tab._auto_expand_all_total = 1
        tab._auto_expand_all_completed = 0
        tab._auto_expand_all_current_chapter_id = ""
        tab.chapter_list = _FakeListWidget([])
        tab._row_for_source_index = lambda *_args: 0
        tab.writing_worker = None
        started = []
        def start_sequence():
            tab._chapter_ai_sequence_active = True
            started.append(chapter["id"])
        tab._start_chapter_ai_sequence = start_sequence
        tab.set_status_tip = lambda _text: None

        with patch("gpt_desktop.novel_writing_tab.QTimer.singleShot") as single_shot:
            tab._start_next_auto_expand_chapter()

        self.assertEqual(started, [])
        self.assertEqual(tab._auto_expand_all_current_chapter_id, chapter["id"])
        self.assertEqual(single_shot.call_count, 1)
        self.assertEqual(single_shot.call_args.args[0], 0)

    def test_auto_expand_all_waits_for_worker_cleanup_after_complete_chapter(self):
        chapter = _new_chapter(0)
        chapter["text"] = "完整正文"
        chapter["summary"] = "章节摘要"
        chapter["key_facts"] = "关键事实"
        chapter["memory_sync_status"] = "complete"
        chapter["memory_revision"] = 1
        chapter["memory_update_hash"] = "verified-update-hash"
        chapter["auto_expand_resume_required"] = True
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "long_form_memory": {
                "revision": 1,
                "state_snapshot": {"as_of_chapter_id": chapter["id"]},
            },
        }
        tab.current_chapter_index = 0
        tab._auto_expand_all_active = True
        tab._auto_expand_all_waiting_next = False
        tab._auto_expand_all_total = 1
        tab._auto_expand_all_completed = 0
        tab._auto_expand_all_current_chapter_id = chapter["id"]
        tab.auto_expand_all_btn = _FakeButton()
        tab._current_chapter_id = lambda: chapter["id"]
        tab._save_current_work = lambda *_args, **_kwargs: "/tmp/project.json"
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)

        tab._on_auto_expand_chapter_completed(True)

        self.assertTrue(tab._auto_expand_all_active)
        self.assertTrue(tab._auto_expand_all_waiting_next)
        self.assertEqual(tab._auto_expand_all_completed, 1)
        self.assertEqual(tab.auto_expand_all_btn.text, "自动扩写全部 1/1")
        self.assertIn("第1章已完成（1/1）", statuses[-1])
        self.assertFalse(chapter["auto_expand_resume_required"])

    def test_auto_expand_all_keeps_resume_flag_when_final_save_fails(self):
        chapter = _new_chapter(0)
        chapter["text"] = "完整正文"
        chapter["summary"] = "章节摘要"
        chapter["key_facts"] = "关键事实"
        chapter["memory_sync_status"] = "complete"
        chapter["memory_revision"] = 1
        chapter["memory_update_hash"] = "verified-update-hash"
        chapter["auto_expand_resume_required"] = True
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "long_form_memory": {
                "revision": 1,
                "state_snapshot": {"as_of_chapter_id": chapter["id"]},
            },
        }
        tab.current_chapter_index = 0
        tab._auto_expand_all_active = True
        tab._auto_expand_all_waiting_next = False
        tab._auto_expand_all_total = 1
        tab._auto_expand_all_completed = 0
        tab._auto_expand_all_current_chapter_id = chapter["id"]
        tab.auto_expand_all_btn = _FakeButton()
        tab._current_chapter_id = lambda: chapter["id"]
        tab._save_current_work = lambda *_args, **_kwargs: ""
        tab._note_project_dirty = lambda: None
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)

        tab._on_auto_expand_chapter_completed(True)

        self.assertFalse(tab._auto_expand_all_active)
        self.assertTrue(chapter["auto_expand_resume_required"])
        self.assertIn("保存失败", statuses[-1])

    def test_auto_expand_all_stops_when_postwrite_memory_is_missing(self):
        chapter = _new_chapter(0)
        chapter["text"] = "完整正文"
        chapter["summary"] = "章节摘要"
        chapter["key_facts"] = "关键事实"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab._auto_expand_all_active = True
        tab._auto_expand_all_waiting_next = False
        tab._auto_expand_all_total = 1
        tab._auto_expand_all_completed = 0
        tab._auto_expand_all_current_chapter_id = chapter["id"]
        tab.auto_expand_all_btn = _FakeButton()
        tab._current_chapter_id = lambda: chapter["id"]
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)

        tab._on_auto_expand_chapter_completed(False)

        self.assertFalse(tab._auto_expand_all_active)
        self.assertFalse(tab._auto_expand_all_waiting_next)
        self.assertIn("资料回填不完整", statuses[-1])

    def test_compact_chapter_summary_ignores_sentence_limit(self):
        text = "赵明进入王城，确认旧案卷宗藏在礼部档案房。" * 12 + "他因此决定夜探档案房。"

        compacted = _compact_chapter_summary_text(text, max_chars=120, max_sentences=2)

        self.assertLessEqual(len(compacted), 120)
        self.assertIn("礼部档案房", compacted)

    def test_compact_chapter_summary_keeps_all_text_by_default(self):
        text = "\n".join(f"摘要短句{index}。" for index in range(1, 9))

        compacted = _compact_chapter_summary_text(text)

        self.assertEqual(compacted, text)
        self.assertIn("摘要短句8。", compacted)

    def test_compact_chapter_key_facts_ignores_item_limit(self):
        text = "\n".join(f"{index}. 关键事实{index}会影响后文。" for index in range(1, 10))

        compacted = _compact_chapter_key_facts_text(text, max_items=4)

        self.assertIn("关键事实1", compacted)
        self.assertIn("关键事实9", compacted)

    def test_compact_chapter_key_facts_drops_empty_numbered_tail(self):
        text = "1. 苏不欺确认对方宿主身份；2. 四六开系统已绑定苏不欺；3. 苏不欺学心猿破流血；4。"

        compacted = _compact_chapter_key_facts_text(text)

        self.assertIn("苏不欺确认对方宿主身份", compacted)
        self.assertIn("四六开系统已绑定苏不欺", compacted)
        self.assertIn("苏不欺学心猿破流血", compacted)
        self.assertNotIn("4。", compacted)
        self.assertNotRegex(compacted, r"(?:^|[；;\n])\s*4[.。]\s*$")

    def test_compact_chapter_key_facts_does_not_hard_cut_long_fact_tail(self):
        long_fact = (
            "赵元宝私用下品定身符失效，设定圆脸外门弟子，被陆长明撞见；"
            "苏不欺掌心伤口重新渗血，收下陆长明给的止血散并随身带着；"
            "苏不欺已领败债宫竹牌、灰布袋、两套衣、一枚引路符和三块下品灵石，暂未使用。"
        )

        compacted = _compact_chapter_key_facts_text(long_fact, max_chars=45, max_items=6)

        self.assertIn("赵元宝私用下品定身符失效", compacted)
        self.assertNotIn("苏不欺掌心伤口", compacted)
        self.assertNotRegex(compacted, r"[，,、]\s*。$")

    def test_compact_chapter_key_facts_keeps_all_items_by_default(self):
        text = "\n".join(f"{index}. 关键事实{index}会影响后文。" for index in range(1, 10))

        compacted = _compact_chapter_key_facts_text(text)

        self.assertEqual(len(compacted.splitlines()), 9)
        self.assertIn("关键事实9会影响后文。", compacted)

    def test_compact_chapter_key_facts_does_not_treat_commas_as_item_limit(self):
        text = (
            "苏不欺掌心伤口重新渗血，收下陆长明给的止血散并随身带着；"
            "苏不欺已领取候查竹牌、灰布袋、两套衣、一枚引路符和三块下品灵石，暂未使用。"
        )

        compacted = _compact_chapter_key_facts_text(text)

        self.assertIn("止血散并随身带着", compacted)
        self.assertIn("三块下品灵石，暂未使用。", compacted)
        self.assertNotIn("暂。", compacted)

    def test_compact_chapter_summary_drops_empty_numbered_tail(self):
        compacted = _compact_chapter_summary_text("1. 赵明进入王城。2。")

        self.assertEqual(compacted, "1. 赵明进入王城。")

    def test_plain_text_edit_is_plain_text_widget(self):
        from gpt_desktop.novel_writing_tab import PlainTextEdit

        self.assertTrue(issubclass(PlainTextEdit, QPlainTextEdit))

    def test_text_edit_bottom_scroll_padding_keeps_existing_margins(self):
        class Margins:
            def __init__(self, left=1, top=2, right=3, bottom=4):
                self._values = (left, top, right, bottom)

            def left(self):
                return self._values[0]

            def top(self):
                return self._values[1]

            def right(self):
                return self._values[2]

            def bottom(self):
                return self._values[3]

        class FakeEdit:
            def __init__(self):
                self.applied = None

            def viewportMargins(self):
                return Margins()

            def setViewportMargins(self, left, top, right, bottom):
                self.applied = (left, top, right, bottom)

        tab = NovelWritingTab.__new__(NovelWritingTab)
        edit = FakeEdit()

        returned = tab._set_text_edit_bottom_scroll_padding(edit, 28)

        self.assertIs(returned, edit)
        self.assertEqual(edit.applied, (1, 2, 3, 28))

    def test_indexed_records_sort_foreshadows_by_stable_code(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": []}
        items = [
            {"code": "F0010", "name": "后期伏笔", "status": "已埋", "setup_chapter": "第十章", "payoff_chapter": ""},
            {"code": "F0002", "name": "前期伏笔", "status": "已埋", "setup_chapter": "第二章", "payoff_chapter": ""},
            {"code": "F0008", "name": "只有回收", "status": "已回收", "setup_chapter": "", "payoff_chapter": "第八集"},
            {"code": "F0015", "name": "无章节", "status": "未埋", "setup_chapter": "", "payoff_chapter": ""},
        ]

        ordered = [item["name"] for _index, item in tab._sorted_indexed_records("foreshadows", items)]

        self.assertEqual(ordered, ["前期伏笔", "只有回收", "后期伏笔", "无章节"])

    def test_indexed_records_sort_characters_by_first_appearance(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [
                {"title": "第一章", "text": "赵明进入王城。", "linked_characters": ["赵明"]},
                {"title": "第二章", "summary": "迟到主角出现。", "linked_characters": []},
            ]
        }
        items = [
            {"name": "迟到主角", "role": "", "notes": ""},
            {"name": "赵明", "role": "", "notes": ""},
            {"name": "后期人物", "role": "", "notes": ""},
        ]

        ordered = [item["name"] for _index, item in tab._sorted_indexed_records("characters", items)]

        self.assertEqual(ordered, ["赵明", "迟到主角", "后期人物"])

    def test_indexed_records_keep_source_indexes_after_sort(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": []}
        items = [
            {"code": "F0010", "name": "第十章伏笔", "status": "已埋", "setup_chapter": "第十章"},
            {"code": "F0002", "name": "第二章伏笔", "status": "已埋", "setup_chapter": "第二章"},
        ]

        ordered_indexes = [index for index, _item in tab._sorted_indexed_records("foreshadows", items)]

        self.assertEqual(ordered_indexes, [1, 0])

    def test_pending_candidate_analysis_ids_with_existing_pending_state(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["text"] = "正文"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.pending_analysis_chapter_ids = [chapter["id"]]

        self.assertEqual(tab._pending_candidate_analysis_chapter_ids(), [chapter["id"]])

    def test_pending_candidate_analysis_ids_include_changed_chapters_not_in_saved_pending(self):
        pending_chapter = _new_chapter(0)
        pending_chapter["title"] = "第一章"
        pending_chapter["text"] = "正文一"
        changed_chapter = _new_chapter(1)
        changed_chapter["title"] = "第二章"
        changed_chapter["text"] = "正文二。" * 80
        _mark_chapters_analyzed([changed_chapter], [changed_chapter["id"]])
        changed_chapter["text"] = "第二章被大幅改写。" * 80
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [pending_chapter, changed_chapter]}
        tab.pending_analysis_chapter_ids = [pending_chapter["id"]]

        self.assertEqual(
            tab._pending_candidate_analysis_chapter_ids(),
            [pending_chapter["id"], changed_chapter["id"]],
        )

    def test_pending_candidate_analysis_ids_skip_small_changes(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["text"] = "赵明进入王城。" * 80
        _mark_chapters_analyzed([chapter], [chapter["id"]])
        chapter["text"] += "补充一句。"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.pending_analysis_chapter_ids = []

        self.assertEqual(tab._pending_candidate_analysis_chapter_ids(), [])

    def test_pending_candidate_analysis_ids_skip_same_length_small_changes(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["text"] = "赵明进入王城。" * 80
        _mark_chapters_analyzed([chapter], [chapter["id"]])
        chapter["text"] = chapter["text"].replace("王城", "皇城", 1)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.pending_analysis_chapter_ids = []

        self.assertEqual(tab._pending_candidate_analysis_chapter_ids(), [])

    def test_pending_candidate_analysis_ids_include_same_length_large_changes(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["text"] = "赵明进入王城。" * 80
        _mark_chapters_analyzed([chapter], [chapter["id"]])
        chapter["text"] = "苏秦离开边城。" * 80
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.pending_analysis_chapter_ids = []

        self.assertEqual(tab._pending_candidate_analysis_chapter_ids(), [chapter["id"]])

    def test_pending_candidate_analysis_ids_include_changed_linked_characters_after_new_hash(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["text"] = "赵明进入王城。" * 80
        chapter["linked_characters"] = ["赵明"]
        _mark_chapters_analyzed([chapter], [chapter["id"]])
        self.assertEqual(chapter["analysis_hash_version"], CHAPTER_ANALYSIS_HASH_VERSION)
        chapter["linked_characters"] = ["赵明", "迟到主角"]
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.pending_analysis_chapter_ids = []

        self.assertEqual(tab._pending_candidate_analysis_chapter_ids(), [chapter["id"]])

    def test_ai_candidate_analysis_lets_worker_split_normal_text(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["text"] = "赵明进入王城。" * 1200
        project = {
            "meta": {},
            "draft_note": "私有备注锚点：不能交给 AI。",
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
        }
        captured = {}

        class FakeSignal:
            def connect(self, _callback):
                return None

        class FakeWorker:
            def __init__(
                self,
                _base_url,
                _api_key,
                _model,
                text,
                _proxy_url="",
                _proxy_mode="不使用代理",
                _max_concurrency=3,
                chunks=None,
                dossier="",
            ):
                captured["text"] = text
                captured["chunks"] = chunks
                captured["dossier"] = dossier
                self.progress = FakeSignal()
                self.partial_ready = FakeSignal()
                self.result_ready = FakeSignal()
                self.failed = FakeSignal()
                self.finished = FakeSignal()

            def start(self):
                captured["started"] = True

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.analysis_worker = None
        tab.failed_analysis_chunks = []
        tab.pending_analysis_chapter_ids = []
        tab.current_project = project
        tab.candidate_postprocess_state = {}
        tab._analysis_stop_requested_by_user = False
        tab._current_novel_ai_selection = lambda: (
            {"base_url": "http://example.test", "api_key": "key", "proxy_url": ""},
            "model",
            "",
        )
        tab._flush_current_editors = lambda: None
        tab._has_candidate_postprocess_pending = lambda: False
        tab._pending_candidate_analysis_chapter_ids = lambda: [chapter["id"]]
        tab._sync_candidate_analysis_state = lambda: None
        tab._candidate_analysis_concurrency = lambda: 3
        tab._provider_proxy_mode = lambda _provider: "不使用代理"
        tab._set_candidate_actions_enabled = lambda _enabled: None
        tab.set_status_tip = lambda _text: None

        with patch("gpt_desktop.novel_writing_tab.NovelAnalysisWorker", FakeWorker):
            tab.analyze_import_candidates_with_ai()

        self.assertIsNone(captured["chunks"])
        self.assertIn("第一章\n正文：", captured["text"])
        self.assertIn("赵明进入王城", captured["text"])
        self.assertNotIn("私有备注锚点", captured["text"])
        self.assertNotIn("私有备注锚点", captured["dossier"])
        self.assertTrue(captured["started"])
        self.assertEqual(tab.pending_analysis_chapter_ids, [chapter["id"]])
        self.assertFalse(tab._analysis_merge_with_existing)

    def test_split_manuscript_into_target_chapters_uses_natural_boundaries(self):
        project = {
            "chapters": [
                {
                    "text": ("第一段第一句。第一段第二句。第一段第三句。" * 4) + "\n\n" + ("第二段第一句。第二段第二句。第二段第三句。" * 4)
                },
                {
                    "text": ("第三段第一句。第三段第二句。第三段第三句。" * 4) + "\n\n" + ("第四段第一句。第四段第二句。第四段第三句。" * 4)
                },
            ]
        }

        split = _split_manuscript_into_target_chapters(project, 80)

        self.assertGreaterEqual(len(split), 2)
        self.assertTrue(all(isinstance(item, dict) for item in split))
        self.assertTrue(all(item["text"].strip() for item in split))
        self.assertTrue(all(item["title"].startswith("第 ") for item in split))
        self.assertTrue(all(item["draft_words"] == "80" for item in split))
        self.assertGreater(len(split[0]["text"]), 40)
        self.assertTrue(all(len(item["text"]) >= 70 for item in split))

    def test_split_manuscript_keeps_overlong_sentence_intact(self):
        long_sentence = "这是一个不能被拆开的完整句子" * 80
        source = f"开头完整句。{long_sentence}。后续完整句。"
        split = _split_manuscript_into_target_chapters(
            {"chapters": [{"text": source}]},
            500,
        )

        self.assertGreaterEqual(len(split), 2)
        self.assertTrue(all(not item["text"].startswith("。") for item in split[1:]))
        self.assertTrue(all(not item["text"].endswith("这是一个不能被拆开的完整句子") for item in split[:-1]))
        compact = lambda value: "".join(str(value or "").split())
        self.assertEqual(compact(source), compact("".join(item["text"] for item in split)))

    def test_split_manuscript_uses_clause_boundaries_for_long_comma_paragraphs(self):
        source = "".join(f"第{i}个完整分句，" for i in range(180)) + "最后收束。"
        split = _split_manuscript_into_target_chapters(
            {"chapters": [{"text": source}]},
            500,
        )

        self.assertGreaterEqual(len(split), 2)
        self.assertTrue(all(not item["text"].startswith("，") for item in split[1:]))
        compact = lambda value: "".join(str(value or "").split())
        self.assertEqual(compact(source), compact("".join(item["text"] for item in split)))

    def test_local_split_chapter_title_uses_middle_sentence_without_ai(self):
        text = (
            "开头重复的章节标题。"
            + "甲" * 300
            + "。"
            + "中段出现了适合导出的章节名。"
            + "乙" * 300
            + "结尾重复的章节标题。"
        )
        self.assertEqual(_local_split_chapter_title(text), "中段出现了适合导出的章节名")

    def test_local_split_chapter_title_removes_source_chapter_header_and_keeps_heading(self):
        text = "前文。第 38 章 发怒，‘你知道那段婚姻不是我一个人毁掉的。’后文。"
        self.assertEqual(_local_split_chapter_title(text), "发怒")

        middle_text = "甲" * 220 + "。中段出现了新的章节钩子。"
        self.assertEqual(_local_split_chapter_title(middle_text), "中段出现了新的章节钩子")

        fallback = "乙" * 300
        title = _local_split_chapter_title(fallback)
        self.assertEqual(len(title), 20)

    def test_local_split_chapter_title_never_uses_middle_window_fragment(self):
        complete_title = "完整章节标题绝不能从中间位置被截断"
        prefix = "甲" * 284 + "。"
        middle_start = len(prefix) + 8
        total_chars = 500 + middle_start * 2
        suffix_chars = total_chars - len(prefix) - len(complete_title) - 1
        text = prefix + complete_title + "。" + "乙" * suffix_chars

        self.assertEqual(_local_split_chapter_title(text), complete_title)

    def test_split_docx_export_centers_chapter_headings(self):
        if DocxDocument is None:
            self.skipTest("python-docx unavailable")
        chapters = [
            {"title": "第 1 章", "text": "第一段。\n\n第二段。"},
            {"title": "第 2 章", "text": "第三段。"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "split.docx"
            _write_docx_text(str(path), "书名", chapters, center_chapter_headings=True)
            doc = DocxDocument(str(path))

        headings = [para for para in doc.paragraphs if para.text.strip() in {"书名", "第 1 章", "第 2 章"}]
        self.assertGreaterEqual(len(headings), 2)
        self.assertTrue(all(para.alignment == WD_ALIGN_PARAGRAPH.CENTER for para in headings))

    def test_existing_chapter_export_uses_current_titles_without_ai(self):
        chapter_one = _new_chapter(0)
        chapter_one["title"] = "第一章 原来的名字"
        chapter_one["text"] = "第一章正文。"
        empty_chapter = _new_chapter(1)
        empty_chapter["title"] = "第二章 尚未写作"
        chapter_three = _new_chapter(2)
        chapter_three["title"] = "第三章 仍用现有标题"
        chapter_three["text"] = "第三章正文。"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "meta": {"title": "测试小说"},
            "chapters": [chapter_one, empty_chapter, chapter_three],
        }
        tab._flush_current_editors = lambda: None
        tab._project_title = lambda: "测试小说"
        tab._get_export_path = lambda *_args: "/tmp/current-chapters.docx"
        tab._current_novel_ai_selection = lambda: self.fail("按章节导出不应读取或调用AI")
        exported = []
        tab.set_status_tip = lambda text: exported.append(("status", text))

        import gpt_desktop.novel_writing_tab as writing_tab
        original_write = writing_tab._write_docx_text
        try:
            writing_tab._write_docx_text = lambda path, title, chapters, center_chapter_headings=False: exported.append(
                (path, title, [chapter["title"] for chapter in chapters], center_chapter_headings)
            )
            tab.export_existing_chapters_docx()
        finally:
            writing_tab._write_docx_text = original_write

        self.assertIn(
            (
                "/tmp/current-chapters.docx",
                "测试小说",
                ["第一章 原来的名字", "第三章 仍用现有标题"],
                True,
            ),
            exported,
        )
        self.assertIn("导出 2 章", exported[-1][1])

    def test_chapter_export_mode_routes_existing_chapters_without_ai(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        selected = []
        tab.export_existing_chapters_docx = lambda: selected.append("existing")
        tab.split_current_chapter = lambda: selected.append("split")

        with patch(
            "gpt_desktop.novel_writing_tab.QInputDialog.getItem",
            return_value=("按现有章节导出（不调用AI）", True),
        ):
            tab.choose_chapter_export_mode()

        self.assertEqual(selected, ["existing"])

    def test_split_chapter_titles_ready_exports_with_generated_titles(self):
        chapter_one = _new_chapter(0)
        chapter_one["text"] = "第一章正文。"
        chapter_two = _new_chapter(1)
        chapter_two["text"] = "第二章正文。"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"meta": {"title": "书名"}, "chapters": []}
        tab._pending_split_export = {
            "title": "书名",
            "target_words": 1000,
            "chapters": [chapter_one, chapter_two],
        }
        exported = []
        tab._get_export_path = lambda *_args: "/tmp/split.docx"
        tab._project_title = lambda: "书名"
        tab.set_status_tip = lambda text: exported.append(("status", text))

        import gpt_desktop.novel_writing_tab as writing_tab
        original_write = writing_tab._write_docx_text
        try:
            writing_tab._write_docx_text = lambda path, title, chapters, center_chapter_headings=False: exported.append(
                (path, title, [chap["title"] for chap in chapters], center_chapter_headings)
            )
            tab.on_split_chapter_titles_ready(["会议室里的选择", "沉默的副创始人"])
        finally:
            writing_tab._write_docx_text = original_write

        self.assertIn(("/tmp/split.docx", "书名", ["第 1 章 会议室里的选择", "第 2 章 沉默的副创始人"], True), exported)
        self.assertEqual(tab._pending_split_export, {})

    def test_split_chapter_titles_failure_does_not_export(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"meta": {"title": "书名"}, "chapters": []}
        tab._pending_split_export = {
            "title": "书名",
            "target_words": 1000,
            "chapters": [{"title": "第 1 章", "text": "正文。"}],
        }
        tab._get_export_path = lambda *_args: self.fail("标题失败时不应选择导出路径")
        statuses = []
        warnings = []
        tab.set_status_tip = lambda text: statuses.append(text)

        import gpt_desktop.novel_writing_tab as writing_tab
        original_warning = writing_tab.QMessageBox.warning
        try:
            writing_tab.QMessageBox.warning = lambda _parent, title, text: warnings.append((title, text))
            tab.on_split_chapter_titles_ready([])
        finally:
            writing_tab.QMessageBox.warning = original_warning

        self.assertEqual(tab._pending_split_export, {})
        self.assertTrue(warnings)
        self.assertEqual(warnings[-1][0], "章节标题生成失败")
        self.assertIn("请重试", warnings[-1][1])
        self.assertIn("标题数量不一致", warnings[-1][1])
        self.assertIn("已停止拆分导出", statuses[-1])

    def test_pending_candidate_analysis_keeps_legacy_hash_without_forced_rerun(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["text"] = "赵明进入王城。"
        chapter["linked_characters"] = ["赵明"]
        chapter["analysis_hash"] = _chapter_analysis_legacy_hash(chapter)
        chapter["analysis_hash_version"] = ""
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.pending_analysis_chapter_ids = []

        self.assertEqual(tab._pending_candidate_analysis_chapter_ids(), [])

    def test_save_chapter_marks_legacy_analysis_stale_when_linked_characters_change(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["status"] = "写作中"
        chapter["text"] = "赵明进入王城。"
        chapter["linked_characters"] = ["赵明"]
        chapter["analysis_hash"] = _chapter_analysis_legacy_hash(chapter)
        chapter["analysis_hash_version"] = ""
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab.pending_analysis_chapter_ids = []
        tab.chapter_title = _FakeLineEdit("第一章")
        tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "写作中")
        tab.chapter_linked = _FakeLineEdit("赵明, 迟到主角")
        tab.chapter_draft_words = _FakeLineEdit("3200")
        tab.chapter_outline = _FakePlainTextEdit("")
        tab.chapter_text = _FakePlainTextEdit("赵明进入王城。")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab._refresh_chapter_item = lambda _index: None

        tab._save_chapter_from_editor()

        self.assertEqual(tab.current_project["chapters"][0]["analysis_hash"], "")
        self.assertEqual(tab.current_project["chapters"][0]["draft_words"], "3200")
        self.assertEqual(tab._pending_candidate_analysis_chapter_ids(), [chapter["id"]])

    def test_sync_candidate_analysis_state_prunes_deleted_chapter_ids(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["text"] = "正文"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.pending_analysis_chapter_ids = [chapter["id"], "deleted-chapter"]
        tab.failed_analysis_chunks = [
            {"index": 1, "total": 2, "text": "失败块", "error": "timeout"}
        ]

        tab._sync_candidate_analysis_state()

        self.assertEqual(tab.pending_analysis_chapter_ids, [chapter["id"]])
        self.assertEqual(len(tab.failed_analysis_chunks), 1)
        self.assertEqual(
            tab.current_project["analysis_state"]["pending_candidate_chapter_ids"],
            [chapter["id"]],
        )

    def test_sync_candidate_analysis_state_clears_failures_when_all_pending_chapters_deleted(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": []}
        tab.pending_analysis_chapter_ids = ["deleted-chapter"]
        tab.failed_analysis_chunks = [
            {"index": 1, "total": 1, "text": "旧失败块", "error": "timeout"}
        ]

        tab._sync_candidate_analysis_state()

        self.assertEqual(tab.pending_analysis_chapter_ids, [])
        self.assertEqual(tab.failed_analysis_chunks, [])
        self.assertNotIn("analysis_state", tab.current_project)

    def test_sync_candidate_analysis_state_keeps_candidate_postprocess_state(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.pending_analysis_chapter_ids = [chapter["id"]]
        tab.failed_analysis_chunks = []
        tab.candidate_postprocess_state = {"status": "failed", "error": "timeout"}
        tab.foreshadow_review_observations = {"characters": [], "lore": [], "foreshadows": [{"name": "雨后伏笔", "description": "收尾里提到雨后。"}], "project_materials": {}}
        tab.foreshadow_review_comparison_state = {"status": "pending", "updated_at": "2026-07-02 10:00:00"}
        tab.failed_foreshadow_review_chunks = [{"index": 1, "total": 2, "text": "观察块", "error": "timeout"}]

        tab._sync_candidate_analysis_state()

        state = tab.current_project["analysis_state"]["candidate_postprocess"]
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["error"], "timeout")
        foreshadow_state = tab.current_project["analysis_state"]["foreshadow_review"]
        self.assertEqual(len(foreshadow_state["observations"]["foreshadows"]), 1)
        self.assertEqual(foreshadow_state["comparison"]["status"], "pending")
        self.assertEqual(len(foreshadow_state["failed_observation_chunks"]), 1)

    def test_clear_candidate_analysis_state_clears_foreshadow_postprocess_marker(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "analysis_state": {
                "foreshadow_review": {"comparison": {"status": "pending"}},
            },
        }
        tab.foreshadow_review_postprocess_pending = True

        tab._clear_candidate_analysis_state()

        self.assertFalse(tab.foreshadow_review_postprocess_pending)
        self.assertNotIn("analysis_state", tab.current_project)

    def test_foreshadow_review_observations_sync_to_visible_candidate_drafts(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [], "foreshadow_items": []}
        tab.import_candidates = {
            "characters": [],
            "lore": [],
            "foreshadows": [{"name": "正式候选", "description": "已经完成全局比对。"}],
            "project_materials": {},
        }
        tab.foreshadow_review_observations = {
            "characters": [],
            "lore": [],
            "foreshadows": [
                {
                    "name": "雨后状态",
                    "status": "已埋",
                    "setup_chapter": "第八章",
                    "description": "第八章结尾已经进入雨后。",
                    "_source_label": "章节：第八章",
                }
            ],
            "project_materials": {},
        }

        count = tab._sync_foreshadow_observations_to_import_candidates()

        self.assertEqual(count, 1)
        self.assertEqual(len(tab.import_candidates["foreshadows"]), 2)
        draft = tab.import_candidates["foreshadows"][1]
        self.assertEqual(draft["name"], "雨后状态")
        self.assertEqual(draft["_review_stage"], "observation_draft")
        self.assertEqual(draft["review_action"], "观察待比对")
        self.assertIn("体检建议：观察待比对", draft["description"])
        self.assertIn("逐章伏笔观察草稿", draft["description"])
        self.assertNotIn("_status_explicit", draft)

        tab._drop_foreshadow_observation_draft_candidates()

        self.assertEqual([item["name"] for item in tab.import_candidates["foreshadows"]], ["正式候选"])

    def test_foreshadow_observation_drafts_default_unchecked_and_explained(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        item = {
            "name": "雨后状态",
            "description": "第八章结尾已经进入雨后。\n体检建议：观察待比对",
            "_review_stage": "observation_draft",
        }

        self.assertEqual(tab._default_candidate_check_state("foreshadows", item), Qt.Unchecked)
        detail = tab._candidate_detail_text_with_review("foreshadows", item)
        self.assertIn("逐章伏笔观察草稿", detail)
        self.assertIn("默认不勾选", detail)

    def test_foreshadow_observations_split_by_chapter_for_comparison(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        observations = {
            "foreshadows": [
                {
                    "name": "雨后状态",
                    "description": "第八章结尾已经进入雨后。",
                    "_source_label": "章节：第八章",
                },
                {
                    "name": "总部交锋",
                    "description": "第九章推进总部交锋。",
                    "_source_label": "章节：第九章",
                },
                {
                    "name": "雨后追问",
                    "description": "第八章继续写雨后追问。",
                    "_source_label": "章节：第八章",
                },
            ]
        }

        chunks = tab._split_foreshadow_observation_records(observations)

        self.assertEqual(len(chunks), 2)
        self.assertEqual([chunk["source_label"] for chunk in chunks], ["章节：第八章", "章节：第九章"])
        self.assertTrue(all(chunk["review_flow"] == "foreshadow_review_chapter_compare" for chunk in chunks))
        first_records = json.loads(chunks[0]["text"])
        second_records = json.loads(chunks[1]["text"])
        self.assertEqual([item["name"] for item in first_records], ["雨后状态", "雨后追问"])
        self.assertEqual([item["name"] for item in second_records], ["总部交锋"])

    def test_foreshadow_comparison_retry_ignores_legacy_global_failed_chunks(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        state = {
            "status": "failed",
            "failed_chunks": [
                {"index": 1, "total": 2, "text": "旧全局失败块", "error": "timeout"},
                {
                    "index": 2,
                    "total": 2,
                    "text": "新按章失败块",
                    "review_flow": "foreshadow_review_chapter_compare",
                    "chapter_title": "章节：第八章",
                },
            ],
        }

        chunks = tab._foreshadow_review_comparison_retry_chunks(state)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["text"], "新按章失败块")

    def test_foreshadow_review_partial_publishes_observations_to_candidates(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [], "foreshadow_items": []}
        tab.import_candidates = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
        tab.foreshadow_review_observations = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
        tab.failed_foreshadow_review_chunks = []
        tab.pending_analysis_chapter_ids = []
        tab.failed_analysis_chunks = []
        tab.candidate_postprocess_state = {}
        tab.foreshadow_review_comparison_state = {}
        tab._last_candidate_auto_cleanup_report = {}
        refreshed = []
        persisted = []
        statuses = []
        tab._refresh_candidate_analysis_result_view = lambda: refreshed.append(True)
        tab._persist_candidate_analysis_draft_state = lambda: persisted.append(True)
        tab.set_status_tip = lambda text: statuses.append(text)

        tab.on_foreshadow_review_partial(
            {
                "foreshadows": [
                    {
                        "name": "雨后状态",
                        "status": "已埋",
                        "setup_chapter": "第八章",
                        "description": "第八章结尾已经进入雨后。",
                        "_source_label": "章节：第八章",
                    }
                ],
                "_chunk_total": 2,
                "_chunk_succeeded": 1,
            },
            1,
            2,
        )

        self.assertEqual(len(tab.import_candidates["foreshadows"]), 1)
        self.assertEqual(tab.import_candidates["foreshadows"][0]["_review_stage"], "observation_draft")
        self.assertEqual(tab.current_project["import_candidates"]["foreshadows"][0]["name"], "雨后状态")
        self.assertTrue(refreshed)
        self.assertTrue(persisted)
        self.assertIn("候选区已显示 1 条草稿", statuses[-1])

    def test_foreshadow_postprocess_keeps_unmatched_observation_drafts_until_complete(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [], "foreshadow_items": []}
        tab.import_candidates = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
        tab.foreshadow_review_observations = {
            "characters": [],
            "lore": [],
            "foreshadows": [
                {"name": "雨后状态", "description": "第八章结尾已经进入雨后。"},
                {"name": "旧总部交锋", "description": "总部交锋场域已经变化。"},
            ],
            "project_materials": {},
        }
        tab._sync_foreshadow_observations_to_import_candidates()

        tab._apply_foreshadow_review_postprocess_candidates(
            {
                "foreshadows": [
                    {
                        "name": "雨后状态",
                        "status": "已回收",
                        "description": "全局比对确认雨后状态已回收。",
                        "review_action": "更新状态",
                    }
                ]
            },
            keep_observation_drafts=True,
        )

        items = tab.import_candidates["foreshadows"]
        self.assertEqual(len(items), 2)
        by_name = {item["name"]: item for item in items}
        self.assertFalse(tab._is_foreshadow_observation_draft(by_name["雨后状态"]))
        self.assertTrue(tab._is_foreshadow_observation_draft(by_name["旧总部交锋"]))

        tab._apply_foreshadow_review_postprocess_candidates(
            {
                "foreshadows": [
                    {
                        "name": "雨后状态",
                        "status": "已回收",
                        "description": "全局比对确认雨后状态已回收。",
                        "review_action": "更新状态",
                    }
                ]
            },
            keep_observation_drafts=False,
        )

        self.assertEqual([item["name"] for item in tab.import_candidates["foreshadows"]], ["雨后状态"])

    def test_merge_import_candidates_dedupes_repeated_notes_and_materials(self):
        repeated_note = "允许赵国图继续陈述，最终决定和亲从长计议。"
        repeated_summary = "皇商账册缺页牵出旧案。"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.import_candidates = {
            "characters": [
                {
                    "name": "皇上",
                    "role": "皇帝",
                    "goal": "",
                    "secret": "",
                    "voice": "",
                    "notes": f"{repeated_note}\n补充：{repeated_note}",
                }
            ],
            "lore": [],
            "foreshadows": [],
            "project_materials": {
                "summary": f"{repeated_summary}\n补充：{repeated_summary}",
            },
        }

        merged = tab._merge_import_candidates({
            "characters": [
                {
                    "name": "皇上",
                    "role": "皇帝",
                    "notes": f"{repeated_note}\n早朝准奏设立流民夜市。",
                }
            ],
            "project_materials": {
                "summary": f"{repeated_summary}\n赵明拿到半枚虎符。",
            },
        })

        notes = merged["characters"][0]["notes"]
        self.assertEqual(notes.count(repeated_note), 1)
        self.assertIn("补充：早朝准奏设立流民夜市。", notes)
        summary = merged["project_materials"]["summary"]
        self.assertEqual(summary.count(repeated_summary), 1)
        self.assertIn("补充：赵明拿到半枚虎符。", summary)

    def test_merge_import_candidates_drops_internal_candidate_markers_from_old_cache(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.import_candidates = {
            "characters": [{
                "name": "苏晚晴",
                "notes": "原有备注。\n补充：AI 分析候选",
            }],
            "lore": [],
            "foreshadows": [{
                "name": "关系边界",
                "description": "原有说明。\n补充：AI 分析候选",
            }],
            "project_materials": {},
        }

        merged = tab._merge_import_candidates({
            "characters": [{"name": "苏晚晴"}],
            "foreshadows": [{"name": "关系边界"}],
        })

        serialized = repr(merged)
        self.assertNotIn("AI 分析候选", serialized)
        self.assertEqual(merged["characters"][0]["notes"], "原有备注。")
        self.assertEqual(merged["foreshadows"][0]["description"], "原有说明。")

    def test_core_project_material_candidates_default_unchecked(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        self.assertEqual(tab._default_candidate_material_check_state("bible"), Qt.Unchecked)
        self.assertEqual(tab._default_candidate_material_check_state("world_rules"), Qt.Unchecked)
        self.assertEqual(tab._default_candidate_material_check_state("timeline"), Qt.Checked)
        self.assertEqual(tab._default_candidate_material_check_state("summary"), Qt.Checked)

    def test_candidate_auto_cleanup_keeps_ai_content_without_semantic_filtering(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        chapters = []
        for index in range(8):
            chapter = _new_chapter(index)
            chapter["title"] = f"第{index + 1}章"
            chapter["summary"] = "沈慕白追查慕白资本。"
            chapter["linked_characters"] = ["沈慕白"]
            chapters.append(chapter)
        tab.current_project = {
            "characters": [
                {"name": "沈慕白", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": "核心人物"}
            ],
            "lore": [
                {"name": "慕白资本", "type": "组织", "description": "核心组织"}
            ],
            "foreshadow_items": [
                {"name": "旧钟声", "status": "已埋", "setup_chapter": "第一章", "payoff_chapter": "", "description": "核心伏笔"}
            ],
            "chapters": chapters,
        }
        tab.import_candidates = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
        tab.pending_analysis_chapter_ids = []
        tab._analysis_merge_with_existing = False

        tab._apply_candidate_analysis_result({
            "characters": [
                {"name": "沈慕白", "notes": "本章沈慕白追问泄露范围。"},
                {"name": "沈慕白", "notes": "沈慕白对信息泄露极度敏感，会优先追查责任链。"},
            ],
            "lore": [
                {"name": "慕白资本", "type": "组织", "description": "本章项目资料发往慕白资本邮箱。"},
                {"name": "琉璃塔", "type": "地点", "description": "琉璃塔保存旧案卷宗。"},
            ],
            "foreshadows": [
                {"name": "旧钟声", "status": "未埋", "description": "本章又提到旧钟声。"},
            ],
            "_chunk_total": 1,
            "_chunk_succeeded": 1,
        })

        self.assertEqual(len(tab.import_candidates["characters"]), 1)
        self.assertIn("极度敏感", tab.import_candidates["characters"][0]["notes"])
        self.assertIn("追问泄露范围", tab.import_candidates["characters"][0]["notes"])
        self.assertEqual(len(tab.import_candidates["lore"]), 2)
        self.assertEqual(tab.import_candidates["lore"][0]["name"], "慕白资本")
        self.assertIn("发往慕白资本邮箱", tab.import_candidates["lore"][0]["description"])
        self.assertEqual(tab.import_candidates["lore"][1]["name"], "琉璃塔")
        self.assertEqual(len(tab.import_candidates["foreshadows"]), 1)
        self.assertIn("本章又提到旧钟声", tab.import_candidates["foreshadows"][0]["description"])
        self.assertEqual(tab._last_candidate_auto_cleanup_report["filtered"]["characters"], 0)
        self.assertEqual(tab._last_candidate_auto_cleanup_report["trimmed"]["characters"], 0)
        self.assertEqual(tab._last_candidate_auto_cleanup_report["filtered"]["lore"], 0)
        self.assertEqual(tab._last_candidate_auto_cleanup_report["filtered"]["foreshadows"], 0)
        self.assertEqual(tab._candidate_auto_cleanup_status_text(), "")

    def test_apply_candidate_analysis_result_marks_postprocess_pending_after_success(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"characters": [], "lore": [], "foreshadow_items": [], "chapters": []}
        tab.import_candidates = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
        tab.pending_analysis_chapter_ids = ["chapter-a"]
        tab.failed_analysis_chunks = []
        tab.candidate_postprocess_state = {}
        tab._analysis_merge_with_existing = False

        tab._apply_candidate_analysis_result({
            "characters": [{"name": "赵明", "notes": "长期追查旧案。"}],
            "_chunk_total": 1,
            "_chunk_succeeded": 1,
        })
        tab._set_candidate_postprocess_state("pending")

        self.assertTrue(tab._has_candidate_postprocess_pending())
        self.assertEqual(tab.candidate_postprocess_state["status"], "pending")

    def test_apply_candidate_postprocess_result_replaces_candidates_and_clears_state(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"characters": [], "lore": [], "foreshadow_items": [], "chapters": []}
        tab.import_candidates = {
            "characters": [{"name": "赵明", "notes": "旧候选"}],
            "lore": [],
            "foreshadows": [],
            "project_materials": {},
        }
        tab.candidate_postprocess_state = {"status": "pending"}

        tab._apply_candidate_postprocess_result({
            "characters": [{"name": "赵明", "notes": "合并后的候选"}],
            "lore": [],
            "foreshadows": [],
            "project_materials": {},
        })

        self.assertEqual(tab.import_candidates["characters"][0]["notes"], "合并后的候选")
        self.assertEqual(tab.candidate_postprocess_state, {})

    def test_apply_empty_candidate_postprocess_result_keeps_chunk_candidates(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"characters": [], "lore": [], "foreshadow_items": [], "chapters": []}
        tab.import_candidates = {
            "characters": [{"name": "赵明", "notes": "分块候选"}],
            "lore": [{"name": "旧案密室", "type": "地点", "description": "分块设定"}],
            "foreshadows": [],
            "project_materials": {"timeline": "分块时间线"},
        }
        tab.candidate_postprocess_state = {"status": "pending"}
        tab._last_candidate_auto_cleanup_report = {"filtered": {"characters": 1}}

        replaced = tab._apply_candidate_postprocess_result({"_postprocess_empty": True})

        self.assertFalse(replaced)
        self.assertEqual(tab.import_candidates["characters"][0]["notes"], "分块候选")
        self.assertEqual(tab.import_candidates["lore"][0]["description"], "分块设定")
        self.assertEqual(tab.import_candidates["project_materials"]["timeline"], "分块时间线")
        self.assertEqual(tab.candidate_postprocess_state, {})
        self.assertEqual(tab._last_candidate_auto_cleanup_report, {})

    def test_candidate_detail_explains_review_reason_and_source(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "characters": [
                {"name": "沈慕白", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": "核心人物"}
            ],
            "lore": [],
            "foreshadow_items": [],
            "chapters": [],
        }

        text = tab._candidate_detail_text_with_review(
            "characters",
            {"name": "沈慕白", "notes": "本章沈慕白追问泄露范围。", "_source_label": "第 2/5 块"},
        )

        self.assertIn("默认勾选", text)
        self.assertNotIn("临时剧情推进", text)
        self.assertIn("来源：第 2/5 块", text)

    def test_merge_import_candidates_uses_character_canonical_key(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.import_candidates = {
            "characters": [
                {
                    "name": "皇上赵明",
                    "role": "皇帝",
                    "goal": "",
                    "secret": "",
                    "voice": "",
                    "notes": "旧候选",
                }
            ],
            "lore": [],
            "foreshadows": [],
            "project_materials": {},
        }

        merged = tab._merge_import_candidates({
            "characters": [
                {
                    "name": "赵明",
                    "role": "皇帝",
                    "goal": "稳住朝局",
                    "notes": "新候选",
                }
            ],
        })

        self.assertEqual(len(merged["characters"]), 1)
        self.assertEqual(merged["characters"][0]["name"], "赵明")
        self.assertEqual(merged["characters"][0]["goal"], "稳住朝局")
        self.assertIn("别称：皇上赵明", merged["characters"][0]["notes"])
        self.assertIn("补充：新候选", merged["characters"][0]["notes"])

    def test_merge_import_candidates_uses_aliases_for_lore_and_foreshadows(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {}
        tab.import_candidates = {
            "characters": [],
            "lore": [
                {"name": "琉璃塔", "type": "地点", "description": "别称：白塔\n藏有旧案卷宗。"}
            ],
            "foreshadows": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "",
                    "payoff_chapter": "",
                    "description": "别称：半枚虎符\n牵出兵权。",
                }
            ],
            "project_materials": {},
        }

        merged = tab._merge_import_candidates({
            "lore": [
                {"name": "白塔", "type": "地点", "description": "塔顶有钟。"}
            ],
            "foreshadows": [
                {"name": "半枚虎符", "status": "已埋", "payoff_chapter": "第二十章", "description": "真相揭晓。"}
            ],
        })

        self.assertEqual(len(merged["lore"]), 1)
        self.assertEqual(merged["lore"][0]["name"], "琉璃塔")
        self.assertIn("补充：塔顶有钟。", merged["lore"][0]["description"])
        self.assertEqual(len(merged["foreshadows"]), 1)
        self.assertEqual(merged["foreshadows"][0]["name"], "虎符失踪")
        self.assertEqual(merged["foreshadows"][0]["payoff_chapter"], "第二十章")
        self.assertIn("补充：第二十章：真相揭晓。", merged["foreshadows"][0]["description"])

    def test_merge_import_candidates_adds_chapter_source_to_foreshadow_updates(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [
                {"title": "五行缺五行，系统缺大德"},
            ],
        }
        tab.import_candidates = {
            "characters": [],
            "lore": [],
            "foreshadows": [
                {
                    "name": "系统来源",
                    "status": "已埋",
                    "setup_chapter": "",
                    "payoff_chapter": "",
                    "description": "本季结尾需揭示系统真正来源。",
                }
            ],
            "project_materials": {},
        }

        merged = tab._merge_import_candidates({
            "foreshadows": [
                {
                    "name": "系统来源",
                    "setup_chapter": "五行缺五行，系统缺大德",
                    "description": "四大开系统首次绑定苏不孝时出现异常乱码。",
                }
            ],
        })

        item = merged["foreshadows"][0]
        self.assertEqual(item["setup_chapter"], "第1章：五行缺五行，系统缺大德")
        self.assertIn("补充：第1章：五行缺五行，系统缺大德：埋设章节更新为：第1章：五行缺五行，系统缺大德", item["description"])
        self.assertIn("补充：第1章：五行缺五行，系统缺大德：四大开系统首次绑定苏不孝时出现异常乱码。", item["description"])

    def test_merge_import_candidates_limits_foreshadow_description_supplements(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {}
        tab.import_candidates = {
            "characters": [],
            "lore": [],
            "foreshadows": [
                {
                    "name": "旧钟声",
                    "status": "已埋",
                    "setup_chapter": "第一章",
                    "payoff_chapter": "",
                    "description": "钟声提示旧案未结。\n补充：第一章：钟声在夜里响起。\n补充：第二章：钟声又在王城出现。",
                }
            ],
            "project_materials": {},
        }

        merged = tab._merge_import_candidates({
            "foreshadows": [
                {
                    "name": "旧钟声",
                    "payoff_chapter": "第三章",
                    "description": "赵明确认钟声来自旧案密室。\n章节依据：第三章打开密室。",
                }
            ],
        })

        description = merged["foreshadows"][0]["description"]
        self.assertEqual(description.count("补充："), 2)
        self.assertIn("补充：第一章：钟声在夜里响起。", description)
        self.assertIn("补充：第三章：赵明确认钟声来自旧案密室。；章节依据：第三章打开密室。", description)
        self.assertNotIn("第二章：钟声又在王城出现。", description)

    def test_merge_foreshadow_review_observations_limits_description_supplements(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.foreshadow_review_observations = {
            "characters": [],
            "lore": [],
            "foreshadows": [
                {
                    "name": "旧钟声",
                    "status": "已埋",
                    "description": "钟声提示旧案未结。\n补充：第一章：钟声在夜里响起。\n补充：第二章：钟声又在王城出现。",
                }
            ],
            "project_materials": {},
        }

        merged = tab._merge_foreshadow_review_observations({
            "foreshadows": [
                {
                    "name": "旧钟声",
                    "payoff_chapter": "第三章",
                    "description": "赵明确认钟声来自旧案密室。\n章节依据：第三章打开密室。",
                }
            ],
        })

        description = merged["foreshadows"][0]["description"]
        self.assertEqual(description.count("补充："), 2)
        self.assertIn("补充：第一章：钟声在夜里响起。", description)
        self.assertIn("补充：第三章：赵明确认钟声来自旧案密室。；章节依据：第三章打开密室。", description)
        self.assertNotIn("第二章：钟声又在王城出现。", description)

    def test_merge_import_candidates_uses_foreshadow_review_merge_target(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.import_candidates = {
            "characters": [],
            "lore": [],
            "foreshadows": [
                {
                    "name": "雨后状态",
                    "status": "已埋",
                    "setup_chapter": "第八章",
                    "payoff_chapter": "",
                    "description": "第八章结尾已经进入雨后。",
                }
            ],
            "project_materials": {},
        }

        merged = tab._merge_import_candidates({
            "foreshadows": [
                {
                    "name": "第九章不应再次下雨",
                    "status": "已回收",
                    "payoff_chapter": "第九章",
                    "description": "第九章开头重复写雨水，应按第八章雨后状态修正。",
                    "merge_target": "雨后状态",
                    "review_action": "更新状态",
                }
            ],
        })

        self.assertEqual(len(merged["foreshadows"]), 1)
        self.assertEqual(merged["foreshadows"][0]["name"], "雨后状态")
        self.assertEqual(merged["foreshadows"][0]["status"], "已回收")
        self.assertEqual(merged["foreshadows"][0]["payoff_chapter"], "第九章")
        self.assertIn("重复写雨水", merged["foreshadows"][0]["description"])
        self.assertNotIn("别称：第九章不应再次下雨", merged["foreshadows"][0]["description"])

    def test_merge_import_candidates_does_not_append_after_terminal_foreshadow_review(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.import_candidates = {
            "characters": [],
            "lore": [],
            "foreshadows": [
                {
                    "name": "陈景川与陈远山景辰总部正面交锋",
                    "status": "废弃",
                    "description": "体检建议：移出伏笔\n判断依据：场域已被正文修正。",
                    "_target_code": "F0055",
                    "_status_explicit": True,
                }
            ],
            "project_materials": {},
        }

        merged = tab._merge_import_candidates({
            "foreshadows": [
                {
                    "name": "陈景川与陈远山景辰总部正面交锋",
                    "status": "已回收",
                    "description": "体检建议：更新状态\n命中编号：F0055\n判断依据：后续章节再次提到。",
                    "target_code": "F0055",
                    "_status_explicit": True,
                }
            ],
        })

        self.assertEqual(len(merged["foreshadows"]), 1)
        self.assertEqual(merged["foreshadows"][0]["status"], "废弃")
        self.assertIn("移出伏笔", merged["foreshadows"][0]["description"])
        self.assertNotIn("后续章节再次提到", merged["foreshadows"][0]["description"])

    def test_merge_import_candidates_replaces_terminal_review_with_earlier_chapter(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.import_candidates = {
            "characters": [],
            "lore": [],
            "foreshadows": [
                {
                    "name": "陈景川与陈远山景辰总部正面交锋",
                    "status": "废弃",
                    "description": "第九章后续再次提到该旧线索。\n章节依据：第九章",
                    "_target_code": "F0055",
                    "_status_explicit": True,
                }
            ],
            "project_materials": {},
        }

        merged = tab._merge_import_candidates({
            "foreshadows": [
                {
                    "name": "陈景川与陈远山景辰总部正面交锋",
                    "status": "废弃",
                    "description": "章节 7 首次证明总部交锋场域已被正文修正。",
                    "target_code": "F0055",
                    "review_action": "移出伏笔",
                    "evidence": "章节 7 陈家老宅通知",
                }
            ],
        })

        self.assertEqual(len(merged["foreshadows"]), 1)
        self.assertIn("章节 7", merged["foreshadows"][0]["description"])
        self.assertNotIn("第九章后续", merged["foreshadows"][0]["description"])

    def test_has_manuscript_body_requires_chapter_text(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "meta": {"title": "只有书名"},
            "chapters": [{"title": "第一章", "text": ""}],
        }

        self.assertFalse(tab._has_manuscript_body())

        tab.current_project["chapters"][0]["text"] = "正文"
        self.assertTrue(tab._has_manuscript_body())

    def test_mark_current_chapter_ai_result_uses_final_editor_content(self):
        chapter = _new_chapter(0)
        chapter["text"] = "审稿前正文"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab.chapter_outline = _FakePlainTextEdit("实际提纲")
        tab.chapter_text = _FakePlainTextEdit("第二次审稿后的终稿")
        tab.chapter_summary = _FakePlainTextEdit("终稿摘要")
        tab.chapter_key_facts = _FakePlainTextEdit("终稿事实")
        tab.chapter_linked = _FakeLineEdit("赵明, 苏秦")

        marked = tab._mark_current_chapter_ai_result_analyzed()

        self.assertTrue(marked)
        self.assertEqual(chapter["text"], "第二次审稿后的终稿")
        self.assertEqual(chapter["linked_characters"], ["赵明", "苏秦"])
        self.assertEqual(chapter["analysis_hash"], _chapter_analysis_hash(chapter))
        self.assertEqual(chapter["analysis_status"], "current")

    def test_apply_summary_preview_infers_linked_characters(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["status"] = "写作中"
        chapter["text"] = "赵明进入王城，迟到主角把旧卷交给他。"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
                {"name": "迟到主角", "role": "旧案证人", "goal": "", "secret": "", "voice": "", "notes": ""},
            ],
            "chapters": [chapter],
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit(
            "本章摘要：赵明进入王城。\n本章需继承的关键事实：迟到主角交出旧卷。"
        )
        tab.chapter_title = _FakeLineEdit("第一章")
        tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "写作中")
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_outline = _FakePlainTextEdit("")
        tab.chapter_text = _FakePlainTextEdit(chapter["text"])
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab._dirty = False
        tab._loading = False
        tab._refresh_chapter_item = lambda _index: None
        tab._schedule_refresh = lambda include_manuscript=False: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab.set_status_tip = lambda _text: None

        tab.apply_chapter_ai_preview("summary")

        saved = tab.current_project["chapters"][0]
        self.assertEqual(tab.chapter_linked.text(), "赵明, 迟到主角")
        self.assertEqual(saved["linked_characters"], ["赵明", "迟到主角"])
        self.assertEqual(saved["summary"], "赵明进入王城。")
        self.assertEqual(saved["key_facts"], "迟到主角交出旧卷。")

    def test_apply_summary_preview_ignores_generic_role_label_for_existing_character(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["status"] = "写作中"
        chapter["outline"] = "有人进入王城。"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "", "notes": ""},
            ],
            "chapters": [chapter],
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit(
            "本章摘要：有人进入王城。\n本章需继承的关键事实：他拿到旧案钥匙。\n本章关联人物：主角"
        )
        tab.chapter_title = _FakeLineEdit("第一章")
        tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "写作中")
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_outline = _FakePlainTextEdit(chapter["outline"])
        tab.chapter_text = _FakePlainTextEdit("")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab._dirty = False
        tab._loading = False
        tab._refresh_chapter_item = lambda _index: None
        tab._schedule_refresh = lambda include_manuscript=False: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab.set_status_tip = lambda _text: None

        tab.apply_chapter_ai_preview("summary")

        saved = tab.current_project["chapters"][0]
        self.assertEqual(tab.chapter_linked.text(), "")
        self.assertEqual(saved["linked_characters"], [])

    def test_apply_summary_preview_does_not_put_fact_only_output_into_summary(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["status"] = "写作中"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
            ],
            "chapters": [chapter],
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit(
            "本章需继承的关键事实：赵明拿到旧案钥匙。\n本章关联人物：赵明"
        )
        tab.chapter_title = _FakeLineEdit("第一章")
        tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "写作中")
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_outline = _FakePlainTextEdit("")
        tab.chapter_text = _FakePlainTextEdit("")
        tab.chapter_summary = _FakePlainTextEdit("原摘要")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab._dirty = False
        tab._loading = False
        tab._refresh_chapter_item = lambda _index: None
        tab._schedule_refresh = lambda include_manuscript=False: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab.set_status_tip = lambda _text: None

        tab.apply_chapter_ai_preview("summary")

        saved = tab.current_project["chapters"][0]
        self.assertEqual(saved["summary"], "原摘要")
        self.assertEqual(saved["key_facts"], "赵明拿到旧案钥匙。")
        self.assertEqual(saved["linked_characters"], ["赵明"])

    def test_apply_outline_preview_infers_linked_characters(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["status"] = "大纲"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
                {"name": "迟到主角", "role": "旧案证人", "goal": "", "secret": "", "voice": "", "notes": ""},
            ],
            "chapters": [chapter],
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("主角进入王城，迟到主角交出旧卷。")
        tab.chapter_title = _FakeLineEdit("第一章")
        tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "大纲")
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_outline = _FakePlainTextEdit("")
        tab.chapter_text = _FakePlainTextEdit("")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab._dirty = False
        tab._loading = False
        tab._refresh_chapter_item = lambda _index: None
        tab._schedule_refresh = lambda include_manuscript=False: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab.set_status_tip = lambda _text: None

        tab.apply_chapter_ai_preview("outline")

        saved = tab.current_project["chapters"][0]
        self.assertEqual(saved["outline"], "主角进入王城，迟到主角交出旧卷。")
        self.assertEqual(tab.chapter_linked.text(), "迟到主角")
        self.assertEqual(saved["linked_characters"], ["迟到主角"])

    def test_apply_text_preview_infers_linked_characters(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["status"] = "写作中"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
                {"name": "迟到主角", "role": "旧案证人", "goal": "", "secret": "", "voice": "", "notes": ""},
            ],
            "chapters": [chapter],
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("赵明进入王城，迟到主角把旧卷交给他。")
        tab.chapter_title = _FakeLineEdit("第一章")
        tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "写作中")
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_outline = _FakePlainTextEdit("")
        tab.chapter_text = _FakePlainTextEdit("")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab._dirty = False
        tab._loading = False
        tab._refresh_chapter_item = lambda _index: None
        tab._schedule_refresh = lambda include_manuscript=False: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab.set_status_tip = lambda _text: None

        tab.apply_chapter_ai_preview("text")

        saved = tab.current_project["chapters"][0]
        self.assertEqual(tab.chapter_linked.text(), "赵明, 迟到主角")
        self.assertEqual(saved["linked_characters"], ["赵明", "迟到主角"])

    def test_chapter_ai_sequence_keeps_draft_in_preview_until_memory_finalize(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_title = _FakeLineEdit("第一章")
        tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "大纲")
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_outline = _FakePlainTextEdit("")
        tab.chapter_text = _FakePlainTextEdit("")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab._dirty = False
        tab._loading = False
        tab._refresh_chapter_item = lambda _index: None
        tab._schedule_refresh = lambda include_manuscript=False: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab.set_status_tip = lambda _text: None
        tab._set_chapter_ai_actions_enabled = lambda _enabled: None
        tab._set_partial_draft_preview_state = lambda enabled: setattr(tab, "_partial_state", enabled)
        tab._chapter_ai_resume_prefix = ""
        tab._chapter_ai_stop_requested_by_user = False
        tab._chapter_ai_running_action = ""
        tab._chapter_ai_buttons_by_action = {}
        tab._chapter_ai_provider = {"base_url": "http://example.test", "api_key": "key", "proxy_url": ""}
        tab._chapter_ai_model = "model"
        tab._provider_proxy_mode = lambda _provider: "不使用代理"
        tab._current_novel_ai_selection = lambda: (tab._chapter_ai_provider, tab._chapter_ai_model, "")
        tab._flush_current_editors = lambda: None
        tab._chapter_ai_context = lambda action: f"context:{action}"
        tab._chapter_ai_context_with_preview = lambda action: f"context:{action}"
        started = []
        finalized = []
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)
        tab._start_chapter_ai_worker = lambda action, _context, status_text="", resume_prefix="": (
            statuses.append(status_text) if status_text else None,
            started.append(action),
        )
        tab._start_memory_finalize = lambda text: finalized.append(text)

        tab._start_chapter_ai_sequence()
        self.assertEqual(started, ["draft"])
        self.assertTrue(tab._chapter_ai_sequence_active)

        tab.chapter_ai_preview.setPlainText("AI 正文")
        tab.on_chapter_ai_ready("draft", "AI 正文")
        self.assertEqual(tab.chapter_text.toPlainText(), "")
        self.assertEqual(tab.chapter_ai_preview.toPlainText(), "AI 正文")
        self.assertEqual(started, ["draft"])
        self.assertEqual(finalized, ["AI 正文"])
        self.assertTrue(tab._chapter_ai_sequence_active)

    def test_single_and_auto_expand_draft_share_the_same_commit_gate(self):
        def run_flow(auto_expand):
            chapter = _new_chapter(0)
            tab = NovelWritingTab.__new__(NovelWritingTab)
            tab.current_project = {"chapters": [chapter], "characters": []}
            tab.current_chapter_index = 0
            tab.chapter_ai_preview = _FakePlainTextEdit("")
            tab.chapter_title = _FakeLineEdit("第一章")
            tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "大纲")
            tab.chapter_linked = _FakeLineEdit("")
            tab.chapter_outline = _FakePlainTextEdit("章节提纲")
            tab.chapter_text = _FakePlainTextEdit("")
            tab.chapter_summary = _FakePlainTextEdit("")
            tab.chapter_key_facts = _FakePlainTextEdit("")
            tab._dirty = False
            tab._loading = False
            tab._auto_expand_all_active = auto_expand
            tab._refresh_chapter_item = lambda _index: None
            tab._schedule_refresh = lambda include_manuscript=False: None
            tab.set_chapter_ai_panel_expanded = lambda _expanded: None
            tab.set_status_tip = lambda _text: None
            tab._set_chapter_ai_actions_enabled = lambda _enabled: None
            tab._chapter_ai_resume_prefix = ""
            tab._chapter_ai_stop_requested_by_user = False
            tab._chapter_ai_running_action = ""
            tab._chapter_ai_buttons_by_action = {}
            tab._chapter_ai_provider = {
                "base_url": "http://example.test",
                "api_key": "key",
                "proxy_url": "",
            }
            tab._chapter_ai_model = "model"
            tab._provider_proxy_mode = lambda _provider: "不使用代理"
            tab._current_novel_ai_selection = lambda: (
                tab._chapter_ai_provider,
                tab._chapter_ai_model,
                "",
            )
            tab._flush_current_editors = lambda: None
            tab._chapter_ai_context_with_preview = lambda action: f"context:{action}"
            started = []
            finalized = []
            applied = []
            tab._start_chapter_ai_worker = lambda action, _context, status_text="", resume_prefix="": started.append(action)
            tab._start_memory_finalize = lambda text: finalized.append(text)
            tab.apply_chapter_ai_preview = lambda target: applied.append(target)

            tab._start_chapter_ai_sequence()
            tab.chapter_ai_preview.setPlainText("统一流程正文")
            tab.on_chapter_ai_ready("draft", "统一流程正文")
            return tab, started, finalized, applied

        single_tab, single_started, single_finalized, single_applied = run_flow(False)
        auto_tab, auto_started, auto_finalized, auto_applied = run_flow(True)

        self.assertEqual(single_started, ["draft"])
        self.assertEqual(auto_started, ["draft"])
        self.assertEqual(single_finalized, ["统一流程正文"])
        self.assertEqual(auto_finalized, ["统一流程正文"])
        self.assertEqual(single_applied, [])
        self.assertEqual(auto_applied, [])
        self.assertEqual(single_tab.chapter_text.toPlainText(), "")
        self.assertEqual(auto_tab.chapter_text.toPlainText(), "")
        self.assertEqual(single_tab.chapter_ai_preview.toPlainText(), "统一流程正文")
        self.assertEqual(auto_tab.chapter_ai_preview.toPlainText(), "统一流程正文")

    def test_single_and_auto_expand_commit_atomically_after_memory_postprocessing(self):
        final_text = "赵明确认资料来源仍然未知。"
        for auto_expand in (False, True):
            for stage in ("memory_finalize", "memory_repair", "memory_reconcile"):
                with self.subTest(auto_expand=auto_expand, stage=stage):
                    chapter_index = 9 if stage == "memory_reconcile" else 0
                    chapters = [_new_chapter(index) for index in range(chapter_index + 1)]
                    chapter = chapters[-1]
                    tab = NovelWritingTab.__new__(NovelWritingTab)
                    tab.current_project = {
                        "chapters": chapters, "characters": [], "lore": [],
                        "foreshadow_items": [],
                        "long_form_memory": {"schema_version": "2", "revision": chapter_index},
                    }
                    tab.current_chapter_index = chapter_index
                    tab.chapter_ai_preview = _FakePlainTextEdit("")
                    tab.chapter_ai_stream_text = ""
                    tab.chapter_text = _FakePlainTextEdit("")
                    tab.chapter_outline = _FakePlainTextEdit("原规划提纲")
                    tab.chapter_summary = _FakePlainTextEdit("")
                    tab.chapter_key_facts = _FakePlainTextEdit("")
                    tab.chapter_linked = _FakeLineEdit("")
                    tab._auto_expand_all_active = auto_expand
                    tab._chapter_ai_sequence_active = True
                    tab._chapter_ai_sequence_started_outline = "原规划提纲"
                    tab._ai_project_snapshot = lambda: deepcopy(tab.current_project)
                    tab._set_partial_chapter_ai_preview_state = lambda *_args: None
                    tab._refresh_long_form_record_views = lambda: None
                    tab._mark_chapter_dirty = lambda: None
                    tab._note_project_dirty = lambda: None
                    tab._persist_ai_generation_state = lambda: None
                    tab.set_chapter_ai_panel_expanded = lambda _expanded: None
                    tab.set_status_tip = lambda _text: None
                    started = []
                    completed = []
                    tab._start_chapter_ai_worker = lambda action, *_args, **_kwargs: started.append(action)
                    tab._on_auto_expand_chapter_completed = completed.append

                    tab.on_chapter_ai_ready("draft", final_text)

                    self.assertEqual(started, ["memory_finalize"])
                    self.assertEqual(tab.chapter_text.toPlainText(), "")
                    self.assertEqual(chapter["text"], "")
                    self.assertEqual(tab.chapter_ai_preview.toPlainText(), final_text)
                    memory_update = {
                        "schema_version": 2, "base_revision": chapter_index,
                        "state_patch": {}, "state_retirements": {}, "state_delta": {},
                        "fact_updates": [], "current_chapter_character_refs": [],
                        "stage_archive": None,
                        "record_updates": {"characters": [], "lore": []},
                        "foreshadow_updates": [], "next_chapter_memory": {},
                        **self._strict_memory_controls(),
                    }
                    if stage == "memory_reconcile":
                        memory_update["state_lifecycle_review"]["scope"] = "stage_boundary_delta"
                        memory_update["fact_lifecycle_review"]["scope"] = "stage_boundary_delta"
                        memory_update["stage_archive"] = {
                            "summary": "前十章完成资料核查。", "irreversible_facts": [],
                            "relationship_changes": [], "unresolved_threads": ["资料来源未知"],
                            "next_stage_entry": "继续核实资料来源。",
                        }
                    result = {
                        "logic_audit": {"checked": True, "issues": []},
                        "outline": "赵明核对资料来源。", "summary": final_text,
                        "key_facts": ["资料来源仍然未知。"],
                        "long_form_memory": memory_update,
                    }
                    if stage == "memory_repair":
                        invalid = deepcopy(result)
                        invalid["long_form_memory"]["state_reconciliation"]["checked"] = False
                        tab._handle_memory_finalize_ready(json.dumps(invalid, ensure_ascii=False))
                        self.assertEqual(started, ["memory_finalize", "memory_repair"])
                        self.assertEqual(tab.chapter_text.toPlainText(), "")
                        self.assertEqual(tab.current_project["chapters"][-1]["text"], "")
                        self.assertEqual(tab.current_project["long_form_memory"]["revision"], chapter_index)
                        tab._handle_memory_repair_ready(json.dumps(result, ensure_ascii=False))
                    else:
                        tab._handle_memory_finalize_ready(json.dumps(result, ensure_ascii=False))
                        if stage == "memory_reconcile":
                            self.assertEqual(started, ["memory_finalize", "memory_reconcile"])
                            self.assertEqual(tab.chapter_text.toPlainText(), "")
                            self.assertEqual(tab.current_project["chapters"][-1]["text"], "")
                            self.assertEqual(tab.current_project["long_form_memory"]["revision"], chapter_index)
                            tab._handle_memory_reconciliation_ready('{"corrections": {}}')

                    saved = tab.current_project["chapters"][-1]
                    self.assertEqual(tab.chapter_text.toPlainText(), final_text)
                    self.assertEqual(saved["text"], final_text)
                    self.assertEqual(saved["summary"], final_text)
                    self.assertEqual(saved["key_facts"], "1. 资料来源仍然未知。")
                    self.assertEqual(saved["memory_sync_status"], "complete")
                    self.assertEqual(saved["ai_generation_checkpoint"], {})
                    self.assertEqual(tab.current_project["long_form_memory"]["revision"], chapter_index + 1)
                    self.assertEqual(tab.chapter_ai_preview.toPlainText(), "")
                    self.assertEqual(completed, [True])
                    self.assertNotIn("outline", started)
                    self.assertNotIn("summary", started)

    def test_fragmented_style_draft_triggers_one_automatic_rewrite(self):
        reference = "\n".join(
            (f"样本第{i}段，" + "人物关系与事情缘由在连续叙述里逐步展开。" * 5)
            for i in range(20)
        )
        fragmented = "\n".join(f"短句{i}。" for i in range(180))
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.chapter_ai_preview = _FakePlainTextEdit(fragmented)
        tab.chapter_ai_stream_text = fragmented
        tab._chapter_ai_resume_prefix = ""
        tab._chapter_ai_style_retry_attempted = False
        tab._chapter_ai_style_fallback_text = ""
        tab._chapter_ai_last_context = (
            "【当前章节】\n剧情资料。\n\n【风格锁定规则】\n动态规则。\n\n【正文风格参考】\n" + reference
        )
        tab._ai_project_snapshot = lambda: {"style_reference": reference}
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )

        retried = tab._maybe_retry_draft_for_style("draft", fragmented)

        self.assertTrue(retried)
        self.assertTrue(tab._chapter_ai_style_retry_attempted)
        self.assertEqual(tab._chapter_ai_style_fallback_text, fragmented)
        self.assertEqual(tab.chapter_ai_preview.toPlainText(), "")
        self.assertEqual(started[0][0], "draft")
        self.assertIn("【风格验收未通过：本次必须重写】", started[0][1])
        self.assertIn("正在自动重写一次", started[0][2])
        self.assertFalse(tab._maybe_retry_draft_for_style("draft", fragmented))

    def test_style_workflow_builds_full_sheet_then_runs_direct_draft_and_state_finalize(self):
        reference = "\n".join(
            (f"样本第{i}段，" + "人物关系和前因后果继续展开。" * 5)
            for i in range(12)
        )
        fragmented = "\n".join(f"短句{i}。" for i in range(180))
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "style_reference": reference,
            "style_profile_cache": {},
            "chapters": [_new_chapter(0)],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "long_form_memory": {"schema_version": "2", "revision": 0},
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab._chapter_ai_resume_prefix = ""
        tab._chapter_ai_stop_requested_by_user = False
        tab._chapter_ai_style_profile_cache_hash = ""
        tab._chapter_ai_style_profile_cache_text = ""
        tab._chapter_ai_style_workflow_active = False
        tab._chapter_ai_style_rewrite_count = 0
        tab._chapter_ai_style_finalize_count = 0
        tab._chapter_ai_style_local_reasons = []
        tab._chapter_ai_style_reference_hash = ""
        tab._chapter_ai_style_cache_entry = {}
        tab._chapter_ai_style_build_unit_index = -1
        tab._chapter_ai_style_combined_sheet = ""
        tab._chapter_ai_style_persona = ""
        tab._chapter_ai_style_rules = ""
        tab._ai_project_snapshot = lambda: tab.current_project
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )
        original_context = (
            "【当前章节】\n剧情资料。\n本章扩写字数：3000字\n\n"
            "【风格锁定规则】\n动态规则。\n\n【正文风格参考】\n" + reference
        )

        tab._start_style_locked_draft(original_context)
        self.assertEqual(started[-1][0], "style_baseline")

        tab.on_chapter_ai_ready("style_baseline", "普通基准正文。")
        self.assertEqual(started[-1][0], "style_sheet")
        sheet = "语言与格式：作者用连续长段铺陈。证据：样本原句。[1]"
        tab.on_chapter_ai_ready("style_sheet", sheet)
        self.assertEqual(started[-1][0], "style_persona")
        tab.on_chapter_ai_ready("style_persona", "你使用连续长段铺陈，并保留直接叙述。")
        self.assertEqual(started[-1][0], "style_cards")
        card_excerpt = reference[:400]
        tab.on_chapter_ai_ready("style_cards", json.dumps({"cards": [{
            "category": "推理与解释",
            "title": "连续铺陈",
            "use_when": "人物核对事情缘由",
            "avoid_when": "高速战斗",
            "voice_features": "连续叙述后给出判断",
            "source_excerpt": card_excerpt,
        }]}, ensure_ascii=False))
        self.assertEqual(started[-1][0], "draft")
        self.assertIn("【仿写使用说明】", started[-1][1])
        self.assertIn(reference, started[-1][1])
        self.assertNotIn("【AI文风画像】", started[-1][1])
        self.assertNotIn("【功能型原文片段库", started[-1][1])
        self.assertNotIn("作者人格", started[-1][1])
        reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        cache = tab.current_project["style_profile_cache"][reference_hash]
        self.assertEqual(cache["status"], "complete")
        self.assertEqual(cache["combined_sheet"], sheet)
        self.assertIn("作者人格", cache["profile"])
        self.assertEqual(cache["style_cards_version"], STYLE_CARD_CACHE_VERSION)
        self.assertEqual(len(cache["style_cards"]), 1)

        candidate = "\n".join(
            (f"第{i}段，" + "人物关系和前因后果继续展开。" * 8)
            for i in range(20)
        )
        tab.on_chapter_ai_ready(
            "draft",
            candidate,
        )
        self.assertEqual(started[-1][0], "memory_finalize")
        self.assertIn("【最终正文】", started[-1][1])
        self.assertIn(candidate, started[-1][1])
        self.assertNotIn("【仿写终稿任务】", started[-1][1])
        normal_actions = [item[0] for item in started if item[0] in {
            "style_rules", "draft", "style_finalize", "memory_finalize"
        }]
        self.assertEqual(normal_actions, ["draft", "memory_finalize"])

    def test_style_workflow_reuses_persisted_profile_after_restart(self):
        reference = "样本文风。" * 300
        reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "style_reference": reference,
            "style_profile_cache": {reference_hash: {
                "version": STYLE_SHEET_CACHE_VERSION,
                "status": "complete",
                "profile": "含完整证据档案的持久文风画像",
                "combined_sheet": "不应逐章进入正文上下文的完整证据档案",
                "persona": "应逐章进入正文上下文的作者语言声纹契约",
            }},
        }
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab._chapter_ai_style_profile_cache_hash = ""
        tab._chapter_ai_style_profile_cache_text = ""
        started = []
        tab._ai_project_snapshot = lambda: tab.current_project
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )

        tab._start_style_locked_draft("【当前章节】\n剧情。\n\n【正文风格参考】\n" + reference)

        self.assertEqual([item[0] for item in started], ["draft"])
        self.assertIn("【仿写使用说明】\n", started[0][1])
        self.assertIn(reference, started[0][1])
        self.assertNotIn("【AI文风画像】\n", started[0][1])
        self.assertNotIn("应逐章进入正文上下文的作者语言声纹契约", started[0][1])
        self.assertNotIn("不应逐章进入正文上下文的完整证据档案", started[0][1])

    def test_style_workflow_rebuilds_legacy_profile_cache(self):
        reference = "旧版样本文风。" * 300
        reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "style_reference": reference,
            "style_profile_cache": {reference_hash: {
                "version": STYLE_SHEET_CACHE_VERSION - 1,
                "status": "complete",
                "profile": "旧版泛化文风画像",
            }},
        }
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab._chapter_ai_style_profile_cache_hash = reference_hash
        tab._chapter_ai_style_profile_cache_text = "旧版运行时缓存"
        tab._chapter_ai_style_profile_cache_version = STYLE_SHEET_CACHE_VERSION - 1
        started = []
        tab._ai_project_snapshot = lambda: tab.current_project
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )

        tab._start_style_locked_draft("【当前章节】\n剧情。\n\n【正文风格参考】\n" + reference)

        self.assertEqual(started[0][0], "style_baseline")
        rebuilt = tab.current_project["style_profile_cache"][reference_hash]
        self.assertEqual(rebuilt["version"], STYLE_SHEET_CACHE_VERSION)
        self.assertEqual(rebuilt["status"], "building")
        self.assertNotEqual(rebuilt.get("profile", ""), "旧版泛化文风画像")

    def test_ai_snapshot_uses_selected_global_style_profile(self):
        local_reference = "当前项目自己的样本。"
        global_reference = "从永久档案库选择的样本。"
        profile_id = hashlib.sha256(global_reference.encode("utf-8")).hexdigest()
        global_entry = {
            "version": 2,
            "status": "complete",
            "profile": "全局永久文风画像",
        }
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "style_reference": local_reference,
            "style_profile_id": profile_id,
            "style_profile_cache": {},
        }

        with patch("gpt_desktop.novel_writing_tab.get_style_profile", return_value={
            "id": profile_id,
            "reference_hash": profile_id,
            "style_reference": global_reference,
            "cache_entry": global_entry,
        }):
            snapshot = tab._ai_project_snapshot()

        self.assertEqual(snapshot["style_reference"], global_reference)
        self.assertEqual(snapshot["style_profile_cache"][profile_id]["profile"], "全局永久文风画像")
        self.assertEqual(tab.current_project["style_reference"], local_reference)

    def test_ai_snapshot_does_not_use_legacy_project_style_without_backend_selection(self):
        reference = "当前项目已经完成建档的样本。"
        reference_hash = hashlib.sha256(reference.encode("utf-8")).hexdigest()
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "style_reference": reference,
            "style_profile_id": "",
            "style_profile_cache": {
                reference_hash: {"status": "complete", "profile": "已持久化文风画像"},
            },
        }

        snapshot = tab._ai_project_snapshot()

        self.assertEqual(snapshot["style_reference"], "")
        self.assertEqual(snapshot["style_profile_cache"], {})

    def test_ai_snapshot_can_disable_style_without_erasing_local_sample(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "style_reference": "仍需保留的项目样本。",
            "style_profile_id": "__none__",
            "style_profile_cache": {"unused": {"profile": "不应进入调用"}},
        }

        snapshot = tab._ai_project_snapshot()

        self.assertEqual(snapshot["style_reference"], "")
        self.assertEqual(snapshot["style_profile_cache"], {})
        self.assertEqual(tab.current_project["style_reference"], "仍需保留的项目样本。")

    def test_style_finalize_starts_independent_memory_finalize_before_writing(self):
        reference = "\n".join("样本连续叙述人物关系和事情缘由，并把信息自然放在段落中。" for _ in range(70))
        initial = "\n".join("初稿连续叙述人物关系和事情缘由，并把信息自然放在段落中。" for _ in range(70))
        revised = "\n".join("终稿连续叙述人物关系和事情缘由，并把信息自然放在段落中。" for _ in range(70))
        tab = NovelWritingTab.__new__(NovelWritingTab)
        chapter = _new_chapter(0)
        tab.current_project = {
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "long_form_memory": {"schema_version": "2", "revision": 0},
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab.chapter_text = _FakePlainTextEdit("")
        tab.chapter_outline = _FakePlainTextEdit("原规划提纲")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab._chapter_ai_resume_prefix = ""
        tab._chapter_ai_stop_requested_by_user = False
        tab._chapter_ai_style_workflow_active = True
        tab._chapter_ai_style_reference = reference
        tab._chapter_ai_style_candidate = initial
        tab._chapter_ai_style_output_target = 0
        tab._chapter_ai_style_finalize_count = 1
        tab._chapter_ai_sequence_started_outline = "原规划提纲"
        tab._chapter_ai_memory_pending = {}
        tab._chapter_ai_memory_finalize_attempted = False
        tab.set_status_tip = lambda _text: None
        tab._ai_project_snapshot = lambda: deepcopy(tab.current_project)
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )
        terminal = (
            f"【终稿正文】\n{revised}\n\n"
            "【终稿验收】\n"
            '{"previous_chapter_repetition_check":true,"logic_continuity_check":true}'
        )

        tab.on_chapter_ai_ready("style_finalize", terminal)

        self.assertEqual([item[0] for item in started], ["memory_finalize"])
        self.assertIn("【最终正文】", started[0][1])
        self.assertIn(revised, started[0][1])
        self.assertEqual(tab.chapter_text.toPlainText(), "")
        self.assertEqual(tab.chapter_outline.toPlainText(), "原规划提纲")
        self.assertEqual(tab.chapter_summary.toPlainText(), "")
        self.assertEqual(tab._chapter_ai_memory_pending["final_text"], revised)
        self.assertTrue(tab._chapter_ai_memory_finalize_attempted)
        checkpoint = tab.current_project["chapters"][0]["ai_generation_checkpoint"]
        self.assertEqual(checkpoint["stage"], "memory_finalize")
        self.assertEqual(checkpoint["final_text"], revised)
        self.assertEqual(checkpoint["base_memory_revision"], 0)

    def test_style_finalize_retries_once_when_plot_evidence_is_incomplete(self):
        reference = "\n".join(
            f"样本第{index}段连续说明人物行动和事情结果。"
            for index in range(40)
        )
        body_lines = [
            f"正文第{index}段继续推进人物行动和事情结果。"
            for index in range(38)
        ]
        body_lines[5] = "赵明进入仓库，并在墙后找到了暗格。"
        body_lines[28] = "暗格打开以后，里面只剩下半页账册。"
        revised = "\n".join(body_lines)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        chapter = _new_chapter(0)
        chapter["outline"] = "赵明进入仓库找到暗格，发现半页账册。"
        tab.current_project = {
            "meta": {},
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "long_form_memory": {"schema_version": "2", "revision": 0},
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab._chapter_ai_style_workflow_active = True
        tab._chapter_ai_style_reference = reference
        tab._chapter_ai_style_candidate = revised
        tab._chapter_ai_style_output_target = len(revised)
        tab._chapter_ai_style_finalize_count = 1
        tab._chapter_ai_style_execution = (
            "1. 赵明进入仓库并找到暗格。\n"
            "2. 暗格内只有半页账册。\n"
            "静默继承边界：旧案卷宗仍由赵明保管。"
        )
        tab._chapter_ai_style_original_context = "【当前章节】\n仓库调查。"
        tab._chapter_ai_style_profile = ""
        tab._chapter_ai_style_plan = ""
        tab._chapter_ai_style_cards = []
        tab._chapter_ai_style_pending_reasons = []
        tab._ai_project_snapshot = lambda: deepcopy(tab.current_project)
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )
        terminal = (
            f"【终稿正文】\n{revised}\n\n"
            "【终稿验收】\n"
            '{"beat_evidence":[{"beat":1,"evidence_quote":'
            '"赵明进入仓库，并在墙后找到了暗格"}],'
            '"previous_chapter_repetition_check":true,'
            '"paragraph_structure_check":true}'
        )

        tab.on_chapter_ai_ready("style_finalize", terminal)

        self.assertEqual([item[0] for item in started], ["memory_finalize"])
        self.assertEqual(tab._chapter_ai_style_finalize_count, 1)
        self.assertEqual(tab._chapter_ai_style_pending_reasons, [])

    def test_style_finalize_severe_structure_mismatch_triggers_one_api_rescue(self):
        reference = "\n".join(
            "样本用连续段落说明人物判断、现场变化和下一步行动。" * 3
            for _ in range(35)
        )
        revised_lines = [f"短段{index}。" for index in range(180)]
        revised_lines[40] = "赵明核完账册，确认封签已经断裂。"
        revised = "\n".join(revised_lines)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        chapter = _new_chapter(0)
        chapter["outline"] = "赵明核对账册并确认封签断裂。"
        tab.current_project = {
            "meta": {},
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "long_form_memory": {"schema_version": "2", "revision": 0},
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab.chapter_text = _FakePlainTextEdit("")
        tab.chapter_outline = _FakePlainTextEdit(chapter["outline"])
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab._chapter_ai_style_workflow_active = True
        tab._chapter_ai_style_reference = reference
        tab._chapter_ai_style_candidate = revised
        tab._chapter_ai_style_output_target = len(revised)
        tab._chapter_ai_style_finalize_count = 1
        tab._chapter_ai_style_execution = "1. 赵明核对账册并确认封签断裂。"
        tab._chapter_ai_style_original_context = "【当前章节】\n核对账册。"
        tab._chapter_ai_style_profile = ""
        tab._chapter_ai_style_plan = ""
        tab._chapter_ai_style_cards = []
        tab._chapter_ai_style_pending_reasons = []
        tab._chapter_ai_sequence_started_outline = chapter["outline"]
        tab._chapter_ai_memory_pending = {}
        tab._chapter_ai_memory_finalize_attempted = False
        tab._ai_project_snapshot = lambda: deepcopy(tab.current_project)
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )
        acceptance = json.dumps({
            "beat_evidence": [{
                "beat": 1,
                "evidence_quote": "赵明核完账册，确认封签已经断裂",
            }],
            "previous_chapter_repetition_check": True,
            "logic_continuity_check": True,
            "paragraph_structure_check": True,
        }, ensure_ascii=False)

        tab.on_chapter_ai_ready(
            "style_finalize",
            f"【终稿正文】\n{revised}\n\n【终稿验收】\n{acceptance}",
        )

        self.assertEqual([item[0] for item in started], ["memory_finalize"])
        self.assertEqual(tab._chapter_ai_style_finalize_count, 1)
        self.assertTrue(any(
            "段落" in item or "短段" in item
            for item in tab._chapter_ai_style_pending_reasons
        ))

    def test_style_finalize_structure_rank_does_not_trigger_extra_api_rescue(self):
        reference = "\n".join(
            "样本用连续段落说明人物判断、现场变化和下一步行动。" * 3
            for _ in range(35)
        )
        initial_lines = [
            "初稿用连续段落说明人物判断、现场变化和下一步行动。" * 3
            for _ in range(35)
        ]
        initial_lines[10] = "赵明核完账册，确认封签已经断裂，随后把证据收回手边。" * 3
        initial = "\n".join(initial_lines)
        revised_lines = [f"短段{index}。" for index in range(180)]
        revised_lines[40] = "赵明核完账册，确认封签已经断裂。"
        revised = "\n".join(revised_lines)
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "meta": {},
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "long_form_memory": {"schema_version": "2", "revision": 0},
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab._chapter_ai_style_workflow_active = True
        tab._chapter_ai_style_reference = reference
        tab._chapter_ai_style_candidate = initial
        tab._chapter_ai_style_output_target = len(initial)
        tab._chapter_ai_style_finalize_count = 1
        tab._chapter_ai_style_execution = "1. 赵明核对账册并确认封签断裂。"
        tab._chapter_ai_style_original_context = "【当前章节】\n核对账册。"
        tab._chapter_ai_style_profile = ""
        tab._chapter_ai_style_plan = ""
        tab._chapter_ai_style_cards = []
        tab._chapter_ai_style_pending_reasons = []
        tab._ai_project_snapshot = lambda: deepcopy(tab.current_project)
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )
        acceptance = json.dumps({
            "beat_evidence": [{
                "beat": 1,
                "evidence_quote": "赵明核完账册，确认封签已经断裂",
            }],
            "previous_chapter_repetition_check": True,
            "logic_continuity_check": True,
            "paragraph_structure_check": True,
        }, ensure_ascii=False)

        tab.on_chapter_ai_ready(
            "style_finalize",
            f"【终稿正文】\n{revised}\n\n【终稿验收】\n{acceptance}",
        )

        self.assertEqual([item[0] for item in started], ["memory_finalize"])
        self.assertEqual(tab._chapter_ai_style_finalize_count, 1)

    def test_style_finalize_does_not_retry_for_missing_conditional_voice_scenes(self):
        reference = "样本文风包含人物口语、冲突接话和日常喜剧。" * 80
        revised = (
            "赵明把账册按回桌上。\n\n"
            "“不是，你真当我看不懂这点把戏？”\n\n"
            "对面的人顿时噎住。"
        )
        tab = NovelWritingTab.__new__(NovelWritingTab)
        chapter = _new_chapter(0)
        chapter["outline"] = "赵明拒绝对方索要账册。"
        tab.current_project = {
            "meta": {},
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "long_form_memory": {"schema_version": "2", "revision": 0},
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab._chapter_ai_style_workflow_active = True
        tab._chapter_ai_style_reference = reference
        tab._chapter_ai_style_candidate = revised
        tab._chapter_ai_style_output_target = len(revised)
        tab._chapter_ai_style_finalize_count = 1
        tab._chapter_ai_style_execution = "1. 赵明拒绝对方索要账册。"
        tab._chapter_ai_style_original_context = "【当前章节】\n赵明保护账册。"
        tab._chapter_ai_style_profile = ""
        tab._chapter_ai_style_plan = "【固定人物声纹基线｜每章必执行】人物对白、冲突声纹、日常口语与喜剧。"
        tab._chapter_ai_style_cards = []
        tab._chapter_ai_style_pending_reasons = []
        tab._ai_project_snapshot = lambda: deepcopy(tab.current_project)
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )
        acceptance = json.dumps({
            "beat_evidence": [{
                "beat": 1,
                "evidence_quote": "赵明把账册按回桌上",
            }],
            "previous_chapter_repetition_check": True,
            "logic_continuity_check": True,
            "paragraph_structure_check": True,
            "role_voice_attribution_check": True,
        }, ensure_ascii=False)

        tab.on_chapter_ai_ready(
            "style_finalize",
            f"【终稿正文】\n{revised}\n\n【终稿验收】\n{acceptance}",
        )

        self.assertEqual([item[0] for item in started], ["memory_finalize"])
        self.assertNotIn("人物对白声纹没有终稿证据", started[0][1])
        self.assertNotIn("日常口语与喜剧没有终稿证据", started[0][1])
        self.assertEqual(tab._chapter_ai_style_finalize_count, 1)

    def test_style_finalize_extreme_dialogue_ratio_triggers_one_api_rescue(self):
        reference = "\n".join(
            f"人物观察第{index}处现场变化，并把判断落实为下一步行动。"
            for index in range(70)
        )
        revised_lines = [
            f"“第{index}项已经核完，请继续登记下一项结果。”"
            for index in range(70)
        ]
        revised_lines[10] = "赵明核完账册，确认封签已经断裂。"
        revised = "\n".join(revised_lines)
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "meta": {},
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "long_form_memory": {"schema_version": "2", "revision": 0},
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab._chapter_ai_style_workflow_active = True
        tab._chapter_ai_style_reference = reference
        tab._chapter_ai_style_candidate = revised
        tab._chapter_ai_style_output_target = len(revised)
        tab._chapter_ai_style_finalize_count = 1
        tab._chapter_ai_style_execution = "1. 赵明核对账册并确认封签断裂。"
        tab._chapter_ai_style_original_context = "【当前章节】\n核对账册。"
        tab._chapter_ai_style_profile = ""
        tab._chapter_ai_style_plan = ""
        tab._chapter_ai_style_cards = []
        tab._chapter_ai_style_pending_reasons = []
        tab._ai_project_snapshot = lambda: deepcopy(tab.current_project)
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )
        tab._start_memory_finalize = lambda text: started.append(("memory_finalize", text, ""))
        acceptance = json.dumps({
            "beat_evidence": [{
                "beat": 1,
                "evidence_quote": "赵明核完账册，确认封签已经断裂",
            }],
            "previous_chapter_repetition_check": True,
            "logic_continuity_check": True,
            "paragraph_structure_check": True,
        }, ensure_ascii=False)
        response = f"【终稿正文】\n{revised}\n\n【终稿验收】\n{acceptance}"

        tab.on_chapter_ai_ready("style_finalize", response)

        self.assertEqual([item[0] for item in started], ["memory_finalize"])
        self.assertEqual(tab._chapter_ai_style_finalize_count, 1)

    def test_chapter_sequence_resumes_valid_memory_checkpoint_without_rewriting_body(self):
        chapter = _new_chapter(0)
        chapter["outline"] = "原规划提纲"
        chapter["memory_sync_status"] = "failed"
        final_text = "已经完成审校的正文终稿。"
        chapter["ai_generation_checkpoint"] = {
            "version": 1,
            "stage": "memory_finalize",
            "status": "failed",
            "chapter_id": chapter["id"],
            "final_text": final_text,
            "final_text_sha256": NovelWritingTab._chapter_ai_checkpoint_hash(final_text),
            "source_text_sha256": NovelWritingTab._chapter_ai_checkpoint_hash(""),
            "outline_sha256": NovelWritingTab._chapter_ai_checkpoint_hash(chapter["outline"]),
            "base_memory_revision": 107,
        }
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "long_form_memory": {"schema_version": "2", "revision": 107},
        }
        tab.current_chapter_index = 0
        tab.chapter_outline = _FakePlainTextEdit(chapter["outline"])
        tab.chapter_ai_preview = _FakePlainTextEdit(
            '```json\n{"summary":"不应被当成正文的内部状态"}\n```'
        )
        tab._chapter_ai_buttons_by_action = {}
        tab._auto_expand_all_active = False
        tab._flush_current_editors = lambda: None
        tab._current_novel_ai_selection = lambda: ({"name": "hubway.cc"}, "gpt-5.5", "")
        tab._chapter_ai_context_with_preview = lambda _action: self.fail("不应重新构建正文上下文")
        resumed_calls = []
        def capture_resume(text, resumed=False):
            resumed_calls.append((text, resumed))
        tab._start_memory_finalize = capture_resume

        tab._start_chapter_ai_sequence()

        self.assertEqual(resumed_calls, [(final_text, True)])
        self.assertEqual(tab._chapter_ai_model, "gpt-5.5")
        self.assertEqual(tab.current_project["chapters"][0]["memory_sync_status"], "pending")

    def test_chapter_sequence_resumes_memory_repair_checkpoint_directly(self):
        chapter = _new_chapter(0)
        chapter["outline"] = "原规划提纲"
        chapter["memory_sync_status"] = "failed"
        final_text = "已经完成审校的正文终稿。"
        bundle = {
            "outline": "实际提纲",
            "summary": "本章摘要",
            "key_facts": "关键事实",
            "memory_update": {"state_reconciliation": {"checked": False}},
        }
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "long_form_memory": {"schema_version": "2", "revision": 107},
        }
        tab.current_chapter_index = 0
        tab.current_project_path = "/tmp/repair-resume.json"
        tab.chapter_outline = _FakePlainTextEdit(chapter["outline"])
        tab.chapter_summary = _FakePlainTextEdit(chapter.get("summary", ""))
        tab.chapter_key_facts = _FakePlainTextEdit(chapter.get("key_facts", ""))
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab._chapter_ai_buttons_by_action = {}
        tab._auto_expand_all_active = False
        tab._flush_current_editors = lambda: None
        tab._current_novel_ai_selection = lambda: ({"name": "hubway.cc"}, "gpt-5.5", "")
        tab._note_project_dirty = lambda: None
        tab._set_partial_chapter_ai_preview_state = lambda *_args: None
        tab._chapter_ai_memory_pending = {}
        tab._store_memory_repair_checkpoint(
            "memory_repair",
            final_text,
            bundle,
            validation_errors=["state_reconciliation.checked必须为true"],
            repair_attempt=1,
            status="failed",
        )
        started = []
        tab._start_memory_repair = lambda *args: started.append(args)
        tab._start_memory_finalize = lambda *_args, **_kwargs: self.fail(
            "修复检查点不应重新进入状态整理"
        )

        tab._start_chapter_ai_sequence()

        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][0], final_text)
        self.assertEqual(started[0][1], bundle)
        self.assertEqual(started[0][2], ["state_reconciliation.checked必须为true"])
        self.assertEqual(tab.current_project["chapters"][0]["ai_generation_checkpoint"]["stage"], "memory_repair")

    def test_chapter_sequence_resumes_logic_repair_checkpoint_directly(self):
        chapter = _new_chapter(0)
        chapter["outline"] = "原规划提纲"
        chapter["memory_sync_status"] = "failed"
        final_text = "已经完成审校的正文终稿。"
        bundle = {
            "outline": "实际提纲",
            "summary": "本章摘要",
            "key_facts": "关键事实",
            "memory_update": {},
        }
        issue = {
            "severity": "major",
            "category": "object_state",
            "earlier_quote": "物件已经撤走",
            "later_quote": "人物再次拿起物件",
            "explanation": "前后状态冲突",
        }
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "long_form_memory": {"schema_version": "2", "revision": 107},
        }
        tab.current_chapter_index = 0
        tab.current_project_path = "/tmp/logic-repair-resume.json"
        tab.chapter_outline = _FakePlainTextEdit(chapter["outline"])
        tab.chapter_summary = _FakePlainTextEdit(chapter.get("summary", ""))
        tab.chapter_key_facts = _FakePlainTextEdit(chapter.get("key_facts", ""))
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab._chapter_ai_buttons_by_action = {}
        tab._auto_expand_all_active = False
        tab._flush_current_editors = lambda: None
        tab._current_novel_ai_selection = lambda: ({"name": "hubway.cc"}, "gpt-5.5", "")
        tab._note_project_dirty = lambda: None
        tab._set_partial_chapter_ai_preview_state = lambda *_args: None
        tab._chapter_ai_memory_pending = {}
        tab._store_memory_repair_checkpoint(
            "logic_repair",
            final_text,
            bundle,
            logic_issues=[issue],
            repair_attempt=1,
            status="failed",
        )
        started = []
        tab._start_chapter_logic_repair = lambda *args: started.append(args)
        tab._start_memory_finalize = lambda *_args, **_kwargs: self.fail(
            "逻辑修复检查点不应重新进入状态整理"
        )

        tab._start_chapter_ai_sequence()

        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][0], final_text)
        self.assertEqual(started[0][1], bundle)
        self.assertEqual(started[0][2], [issue])
        self.assertEqual(tab.current_project["chapters"][0]["ai_generation_checkpoint"]["stage"], "logic_repair")

    def test_stale_repair_checkpoint_restarts_state_finalize_for_existing_body(self):
        chapter = _new_chapter(0)
        chapter["outline"] = "原规划提纲"
        chapter["text"] = "当前已经保存的正文。"
        chapter["memory_sync_status"] = "failed"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "long_form_memory": {"schema_version": "2", "revision": 107},
        }
        tab.current_chapter_index = 0
        tab.current_project_path = "/tmp/stale-repair-resume.json"
        tab.chapter_outline = _FakePlainTextEdit(chapter["outline"])
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab._chapter_ai_buttons_by_action = {}
        tab._auto_expand_all_active = False
        tab._flush_current_editors = lambda: None
        tab._current_novel_ai_selection = lambda: ({"name": "hubway.cc"}, "gpt-5.5", "")
        tab._note_project_dirty = lambda: None
        tab._set_partial_chapter_ai_preview_state = lambda *_args: None
        tab._chapter_ai_memory_pending = {}
        tab._store_memory_repair_checkpoint(
            "memory_repair",
            "旧修复终稿。",
            {"summary": "旧摘要", "memory_update": {}},
            validation_errors=["摘要缺失"],
            repair_attempt=1,
            status="failed",
        )
        chapter["outline"] = "用户已经修改的提纲"
        tab.chapter_outline.setPlainText(chapter["outline"])
        resumed_calls = []
        tab._start_memory_finalize = lambda text, resumed=False: resumed_calls.append((text, resumed))

        tab._start_chapter_ai_sequence()

        self.assertEqual(resumed_calls, [(chapter["text"], False)])
        self.assertEqual(tab.current_project["chapters"][0]["ai_generation_checkpoint"], {})

    def test_internal_memory_stream_stays_out_of_body_preview(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._chapter_ai_running_action = "memory_finalize"
        tab._chapter_ai_style_workflow_active = False
        tab._chapter_ai_sequence_active = True
        tab.chapter_ai_stream_text = ""
        tab.chapter_ai_preview = _FakePlainTextEdit("已经确定的正文终稿。")

        tab.on_chapter_ai_chunk('```json\n{"summary":"内部摘要"}')

        self.assertIn("内部摘要", tab.chapter_ai_stream_text)
        self.assertEqual(tab.chapter_ai_preview.toPlainText(), "已经确定的正文终稿。")

    def test_completed_internal_result_is_parsed_without_flashing_in_preview(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.chapter_ai_stream_text = ""
        tab.chapter_ai_preview = _FakePlainTextEdit("已经确定的正文终稿。")
        tab._chapter_ai_resume_prefix = ""
        tab._chapter_ai_stop_requested_by_user = False
        tab._chapter_ai_sequence_active = True
        tab._chapter_ai_style_workflow_active = True
        tab._clear_transient_chapter_ai_retry = lambda _action: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab._chapter_ai_signal_diagnostics = lambda: ("request-1", 0.0, {})
        tab._save_chapter_ai_latest_exchange = lambda *_args, **_kwargs: ""
        tab._log_novel_diagnostic = lambda *_args, **_kwargs: None
        preview_seen_by_parser = []
        tab._handle_memory_finalize_ready = lambda _content: preview_seen_by_parser.append(
            tab.chapter_ai_preview.toPlainText()
        )

        tab.on_chapter_ai_ready(
            "memory_finalize",
            '```json\n{"summary":"内部摘要","key_facts":[]}\n```',
        )

        self.assertEqual(preview_seen_by_parser, ["已经确定的正文终稿。"])

    def test_stale_memory_checkpoint_is_discarded_before_new_draft(self):
        chapter = _new_chapter(0)
        chapter["outline"] = "原规划提纲"
        chapter["memory_sync_status"] = "failed"
        final_text = "旧终稿。"
        chapter["ai_generation_checkpoint"] = {
            "version": 1,
            "stage": "memory_finalize",
            "status": "failed",
            "chapter_id": chapter["id"],
            "final_text": final_text,
            "final_text_sha256": NovelWritingTab._chapter_ai_checkpoint_hash(final_text),
            "source_text_sha256": NovelWritingTab._chapter_ai_checkpoint_hash(""),
            "outline_sha256": NovelWritingTab._chapter_ai_checkpoint_hash(chapter["outline"]),
            "base_memory_revision": 106,
        }
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "long_form_memory": {"schema_version": "2", "revision": 107},
        }
        tab.current_chapter_index = 0
        tab.chapter_outline = _FakePlainTextEdit(chapter["outline"])
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab._chapter_ai_buttons_by_action = {}
        tab._auto_expand_all_active = False
        tab._flush_current_editors = lambda: None
        tab._current_novel_ai_selection = lambda: ({"name": "hubway.cc"}, "gpt-5.5", "")
        tab._chapter_ai_context_with_preview = lambda action: f"context:{action}"
        started = []
        tab._start_style_locked_draft = lambda context: started.append(context)

        tab._start_chapter_ai_sequence()

        self.assertEqual(started, ["context:draft"])
        self.assertEqual(tab.current_project["chapters"][0]["ai_generation_checkpoint"], {})

    def test_memory_finalize_valid_bundle_commits_body_and_state_atomically(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["auto_expand_resume_required"] = True
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "long_form_memory": {"schema_version": "2", "revision": 0},
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab.chapter_text = _FakePlainTextEdit("")
        tab.chapter_outline = _FakePlainTextEdit("原规划提纲")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab.chapter_linked = _FakeLineEdit("")
        tab._chapter_ai_memory_pending = {}
        tab._chapter_ai_memory_repair_attempts = 0
        tab._chapter_ai_style_workflow_active = True
        tab._chapter_ai_sequence_started_outline = "原规划提纲"
        tab._ai_project_snapshot = lambda: deepcopy(tab.current_project)
        tab._set_partial_chapter_ai_preview_state = lambda *_args: None
        tab._set_line_text_without_signals = lambda widget, text: widget.setText(text)
        tab._refresh_long_form_record_views = lambda: None
        tab._mark_chapter_dirty = lambda: None
        tab._note_project_dirty = lambda: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab.set_status_tip = lambda _text: None
        completions = []
        tab._on_auto_expand_chapter_completed = lambda changed: completions.append(changed)
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )
        final_text = "赵明进入王城，亲手取出封存多年的旧案卷宗。"

        tab._start_memory_finalize(final_text)
        self.assertEqual([item[0] for item in started], ["memory_finalize"])
        result = json.dumps({
            "logic_audit": {"checked": True, "issues": []},
            "outline": "1. 赵明进入王城。\n2. 赵明取出旧案卷宗。",
            "summary": "赵明进入王城并取得旧案卷宗。",
            "key_facts": ["赵明已经取得旧案卷宗。"],
            "long_form_memory": {
                "schema_version": 2,
                "base_revision": 0,
                "state_patch": {"location": "王城"},
                "state_retirements": {},
                "fact_updates": [{
                    "operation": "add",
                    "key": "NF1",
                    "scope": "object:old_case_file:ownership",
                    "fact": "赵明已经取得旧案卷宗",
                    "evidence_quote": "赵明进入王城，亲手取出封存多年的旧案卷宗",
                }],
                "state_delta": {},
                "current_chapter_character_refs": [],
                "stage_archive": None,
                "record_updates": {"characters": [], "lore": []},
                "foreshadow_updates": [],
                "next_chapter_memory": {},
                **self._strict_memory_controls(["NF1"], [{
                    "event": "赵明取得旧案卷宗",
                    "category": "key_object",
                    "evidence_quote": "赵明进入王城，亲手取出封存多年的旧案卷宗",
                    "storage": {
                        "fact_refs": ["NF1"], "character_refs": [], "lore_refs": [],
                        "foreshadow_refs": [], "object_keys": [], "conflict_refs": [],
                        "task_refs": [],
                    },
                }]),
            },
        }, ensure_ascii=False)

        tab._handle_memory_finalize_ready(result)

        self.assertEqual(tab.chapter_text.toPlainText(), final_text)
        self.assertEqual(tab.current_project["chapters"][0]["memory_sync_status"], "complete")
        self.assertFalse(tab.current_project["chapters"][0]["auto_expand_resume_required"])
        self.assertEqual(tab.current_project["chapters"][0]["ai_generation_checkpoint"], {})
        self.assertEqual(tab.current_project["long_form_memory"]["revision"], 1)
        self.assertEqual(completions, [True])
        self.assertEqual([item[0] for item in started], ["memory_finalize"])

    def test_memory_finalize_hard_logic_issue_starts_local_repair_before_memory_validation(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        final_text = "两扇屏风被撤下。\n采买管事扑向屏风边缘。"
        tab._chapter_ai_memory_pending = {
            "chapter_id": chapter["id"],
            "final_text": final_text,
            "logic_audit_required": True,
        }
        started = []
        tab._start_chapter_logic_repair = lambda text, bundle, issues: started.append(
            (text, bundle, issues)
        )
        tab._start_memory_repair = lambda *_args, **_kwargs: self.fail(
            "有效逻辑审查不应进入状态格式修复"
        )
        tab._memory_bundle_validation_errors = lambda *_args, **_kwargs: self.fail(
            "发现硬矛盾后不应校验将被丢弃的旧正文状态"
        )
        result = json.dumps({
            "logic_audit": {
                "checked": True,
                "issues": [{
                    "severity": "major",
                    "category": "object_state",
                    "earlier_quote": "两扇屏风被撤下",
                    "later_quote": "采买管事扑向屏风边缘",
                    "explanation": "屏风已经撤走，后文不能继续扑向屏风。",
                }],
            },
            "outline": "1. 屏风被撤下。",
            "summary": "管事试图逃走。",
            "key_facts": ["屏风已经撤下。"],
            "long_form_memory": {"schema_version": 2},
        }, ensure_ascii=False)

        tab._handle_memory_finalize_ready(result)

        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][0], final_text)
        self.assertEqual(started[0][2][0]["category"], "object_state")

    def test_local_logic_repair_restarts_independent_memory_finalize(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        final_text = "两扇屏风被撤下。\n采买管事扑向屏风边缘。"
        issue = {
            "severity": "major",
            "category": "object_state",
            "earlier_quote": "两扇屏风被撤下",
            "later_quote": "采买管事扑向屏风边缘",
            "explanation": "屏风已经撤走，后文不能继续扑向屏风。",
        }
        tab._chapter_ai_memory_pending = {
            "chapter_id": chapter["id"],
            "final_text": final_text,
            "bundle": {},
            "logic_issues": [issue],
        }
        tab._chapter_ai_logic_repair_attempts = 1
        tab.chapter_ai_preview = _FakePlainTextEdit(final_text)
        tab._log_novel_diagnostic = lambda *_args, **_kwargs: None
        failures = []
        tab._fail_memory_sync = lambda message: failures.append(message)
        restarted = []
        tab._start_memory_finalize = lambda text: restarted.append(text)
        response = json.dumps({
            "patches": [{
                "issue_index": 1,
                "original_quote": "采买管事扑向屏风边缘",
                "replacement_text": "采买管事扑向后门",
            }],
        }, ensure_ascii=False)

        tab._handle_chapter_logic_repair_ready(response)

        self.assertEqual(failures, [])
        self.assertEqual(restarted, ["两扇屏风被撤下。\n采买管事扑向后门。"])
        self.assertEqual(tab.chapter_ai_preview.toPlainText(), restarted[0])

    def test_tenth_chapter_valid_memory_starts_optional_semantic_reconciliation(self):
        chapters = [_new_chapter(index) for index in range(10)]
        chapter = chapters[-1]
        chapter["title"] = "第十章"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": chapters,
            "characters": [], "lore": [], "foreshadow_items": [],
            "long_form_memory": {"schema_version": "2", "revision": 9},
        }
        tab.current_chapter_index = 9
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab._chapter_ai_memory_pending = {
            "chapter_id": chapter["id"],
            "final_text": "赵明确认资料来源仍然未知。",
            "bundle": {}, "reconciliation_started": False,
        }
        tab._ai_project_snapshot = lambda: deepcopy(tab.current_project)
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )
        result = json.dumps({
            "logic_audit": {"checked": True, "issues": []},
            "outline": "1. 赵明核对资料。",
            "summary": "赵明确认资料来源仍未知。",
            "key_facts": ["资料来源仍然未知。"],
            "long_form_memory": {
                "schema_version": 2,
                "base_revision": 9,
                "state_patch": {}, "state_retirements": {},
                "state_lifecycle_review": {
                    "scope": "stage_boundary_delta", "reviewed_object_keys": [],
                    "reviewed_conflict_refs": [], "reviewed_task_refs": [], "notes": "已复核",
                },
                "fact_updates": [],
                "fact_lifecycle_review": {
                    "scope": "stage_boundary_delta", "reviewed_refs": [], "notes": "已复核",
                },
                "long_term_events": [],
                "state_reconciliation": {
                    "checked": True,
                    "coverage_checks": {
                        "named_character_actions": True, "state_changes": True,
                        "evidence_and_unknowns": True, "mechanism_claims_match_body": True,
                        "rules_and_boundaries": True,
                        "foreshadow_and_ending": True,
                    },
                    "fact_refs": [], "character_refs": [], "lore_refs": [],
                    "foreshadow_refs": [], "relationship_refs": [], "object_keys": [],
                    "conflict_refs": [], "task_refs": [], "resolved_contradictions": [],
                },
                "state_delta": {}, "current_chapter_character_refs": [],
                "stage_archive": {
                    "summary": "前十章完成资料核查。", "irreversible_facts": [],
                    "relationship_changes": [], "unresolved_threads": ["资料来源未知"],
                    "next_stage_entry": "继续核实资料来源。",
                },
                "record_updates": {"characters": [], "lore": []},
                "foreshadow_updates": [], "next_chapter_memory": {},
            },
        }, ensure_ascii=False)

        tab._handle_memory_finalize_ready(result)

        self.assertEqual([item[0] for item in started], ["memory_reconcile"])
        self.assertIn("只审查第十章边界的状态语义", started[0][1])
        self.assertEqual(chapter["memory_reconciliation_status"], "pending")

    def test_boundary_reconciliation_failure_keeps_package_for_next_resume(self):
        chapter = _new_chapter(9)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "long_form_memory": {"revision": 9},
        }
        tab.current_chapter_index = 0
        tab.current_project_path = "/tmp/project.json"
        tab._current_chapter_id = lambda: chapter["id"]
        tab._current_chapter_ai_task_context = lambda: {}
        tab._persist_ai_generation_state = lambda: None
        tab._note_project_dirty = lambda: None
        tab._log_novel_diagnostic = lambda *_args, **_kwargs: None
        tab._set_partial_chapter_ai_preview_state = lambda *_args, **_kwargs: None
        tab._reset_chapter_ai_sequence = lambda: None
        tab._set_chapter_ai_actions_enabled = lambda *_args, **_kwargs: None
        tab.set_status_tip = lambda *_args, **_kwargs: None
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        bundle = {"summary": "摘要", "memory_update": {"schema_version": 2}}
        tab._chapter_ai_memory_pending = {
            "chapter_id": chapter["id"], "final_text": "终稿正文。", "bundle": bundle,
        }
        applied = []
        tab._apply_style_final_result = lambda text, value, memory_validated=False: applied.append(
            (text, value, memory_validated)
        )

        tab._apply_memory_reconciliation_fallback("接口暂时失败")

        self.assertEqual(chapter["memory_reconciliation_status"], "failed")
        self.assertIn("接口暂时失败", chapter["memory_reconciliation_error"])
        self.assertEqual(applied, [])
        checkpoint = chapter["ai_generation_checkpoint"]
        self.assertEqual(checkpoint["stage"], "memory_reconcile")
        self.assertEqual(checkpoint["bundle"], bundle)
        self.assertEqual(checkpoint["final_text"], "终稿正文。")
        self.assertTrue(chapter["auto_expand_resume_required"])

    def test_saved_reconciliation_checkpoint_is_selected_before_new_draft(self):
        chapter = _new_chapter(9)
        chapter.update({
            "outline": "本章边界提纲",
            "memory_reconciliation_status": "failed",
            "ai_generation_checkpoint": {
                "version": 3,
                "stage": "memory_reconcile",
                "chapter_id": chapter["id"],
                "chapter_index": 0,
                "project_path": "/tmp/project.json",
                "final_text": "已经完成的正文。",
                "final_text_sha256": NovelWritingTab._chapter_ai_checkpoint_hash("已经完成的正文。"),
                "outline_sha256": NovelWritingTab._chapter_ai_checkpoint_hash("本章边界提纲"),
                "base_memory_revision": 9,
                "bundle": {"memory_update": {"schema_version": 2}},
                "transaction_id": "memory-sync-test",
            },
        })
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "long_form_memory": {"revision": 9},
        }
        tab.current_chapter_index = 0
        tab.current_project_path = "/tmp/project.json"

        checkpoint = tab._validated_memory_reconciliation_checkpoint()

        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint["stage"], "memory_reconcile")
        self.assertEqual(tab._auto_expand_pending_indexes(), [0])

    def test_manual_sequence_resumes_saved_reconciliation_without_new_draft(self):
        chapter = _new_chapter(0)
        chapter.update({
            "outline": "边界提纲",
            "memory_reconciliation_status": "failed",
            "ai_generation_checkpoint": {
                "version": 3,
                "stage": "memory_reconcile",
                "chapter_id": chapter["id"],
                "chapter_index": 0,
                "project_path": "/tmp/project.json",
                "final_text": "保留的完整正文。",
                "final_text_sha256": NovelWritingTab._chapter_ai_checkpoint_hash("保留的完整正文。"),
                "outline_sha256": NovelWritingTab._chapter_ai_checkpoint_hash("边界提纲"),
                "base_memory_revision": 9,
                "bundle": {"memory_update": {"schema_version": 2}},
                "transaction_id": "memory-sync-test",
            },
        })
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "long_form_memory": {"revision": 9}}
        tab.current_chapter_index = 0
        tab.current_project_path = "/tmp/project.json"
        tab.chapter_outline = _FakePlainTextEdit("边界提纲")
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab._current_novel_ai_selection = lambda: ({"id": "provider"}, "model", "")
        tab._flush_current_editors = lambda: None
        tab._reset_chapter_ai_sequence = lambda: None
        tab._reset_chapter_ai_style_retry = lambda: None
        tab._set_partial_chapter_ai_preview_state = lambda *_args, **_kwargs: None
        tab._mark_current_chapter_ai_sync_pending = lambda _chapter: None
        resumed_calls = []
        tab._start_memory_reconciliation = lambda text, bundle, resumed=False: resumed_calls.append(
            (text, bundle, resumed)
        )

        tab._start_chapter_ai_sequence()

        self.assertEqual(resumed_calls, [("保留的完整正文。", {"memory_update": {"schema_version": 2}}, True)])

    def test_legacy_committed_reconciliation_resume_keeps_memory_sync_complete(self):
        chapter = _new_chapter(9)
        chapter.update({
            "memory_sync_status": "complete",
            "memory_reconciliation_status": "pending",
        })
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._chapter_ai_memory_pending = {"already_committed": True}
        tab._note_project_dirty = lambda: None
        tab._persist_ai_generation_state = lambda: None

        tab._mark_current_chapter_ai_sync_pending(chapter)

        self.assertEqual(chapter["memory_sync_status"], "complete")
        self.assertTrue(chapter["auto_expand_resume_required"])

    def test_legacy_committed_boundary_checkpoint_marker_is_preserved_on_failure(self):
        chapter = _new_chapter(9)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "long_form_memory": {"revision": 40}}
        tab.current_chapter_index = 0
        tab.current_project_path = "/tmp/project.json"
        tab._current_chapter_id = lambda: chapter["id"]
        tab._current_chapter_ai_task_context = lambda: {}
        tab._persist_ai_generation_state = lambda: None
        tab._note_project_dirty = lambda: None
        tab._log_novel_diagnostic = lambda *_args, **_kwargs: None
        tab._set_partial_chapter_ai_preview_state = lambda *_args, **_kwargs: None
        tab._reset_chapter_ai_sequence = lambda: None
        tab._set_chapter_ai_actions_enabled = lambda *_args, **_kwargs: None
        tab.set_status_tip = lambda *_args, **_kwargs: None
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab._chapter_ai_memory_pending = {
            "chapter_id": chapter["id"],
            "final_text": "终稿正文。",
            "bundle": {"memory_update": {"schema_version": 2}},
            "already_committed": True,
        }

        tab._apply_memory_reconciliation_fallback("接口暂时失败")

        self.assertTrue(chapter["ai_generation_checkpoint"]["already_committed"])

    def test_boundary_reconciliation_api_failure_delegates_to_checkpoint_fallback(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._chapter_ai_running_action = "memory_reconcile"
        tab._chapter_ai_sequence_active = True
        tab._auto_expand_all_active = True
        tab._schedule_transient_chapter_ai_retry = lambda _action, _error: False
        stopped = []
        fallback = []
        tab._stop_auto_expand_all = lambda message: stopped.append(message)
        tab._apply_memory_reconciliation_fallback = lambda message: fallback.append(message)

        tab.on_chapter_ai_failed("接口错误 500：server down")

        self.assertEqual(stopped, [])
        self.assertEqual(len(fallback), 1)
        self.assertIn("已保留原本通过校验的状态包等待下次对账", fallback[0])

    def test_style_finalize_selects_revised_body_when_only_it_matches_memory_evidence(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "long_form_memory": {"schema_version": "2", "revision": 0},
        }
        tab.current_chapter_index = 0
        initial = "赵明站在门口观察四周。" * 80
        revised = initial + ("他继续确认周围情况。" * 120) + "赵明亲手取出旧案卷宗。"
        tab._chapter_ai_style_reference = initial
        tab._chapter_ai_style_output_target = len(initial)
        bundle = {
            "outline": "赵明取出旧案卷宗。",
            "summary": "赵明取得旧案卷宗。",
            "key_facts": "赵明已经取得旧案卷宗。",
            "memory_update": {
                "schema_version": 2,
                "base_revision": 0,
                "state_patch": {},
                "state_retirements": {},
                "fact_updates": [{
                    "operation": "add",
                    "key": "NF1",
                    "scope": "object:old_case_file:ownership",
                    "fact": "赵明已经取得旧案卷宗",
                    "evidence_quote": "赵明亲手取出旧案卷宗",
                }],
                **self._strict_memory_controls(["NF1"], [{
                    "event": "赵明取得旧案卷宗",
                    "category": "key_object",
                    "evidence_quote": "赵明亲手取出旧案卷宗",
                    "storage": {
                        "fact_refs": ["NF1"], "character_refs": [], "lore_refs": [],
                        "foreshadow_refs": [], "object_keys": [], "conflict_refs": [],
                        "task_refs": [],
                    },
                }]),
                "record_updates": {"characters": [], "lore": []},
                "foreshadow_updates": [],
                "current_chapter_character_refs": [],
                "stage_archive": None,
                "next_chapter_memory": {},
            },
        }

        selected = tab._select_style_final_text(initial, revised, bundle)

        self.assertEqual(selected, revised)

    def test_invalid_style_memory_starts_repair_and_commits_once_after_valid_result(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "long_form_memory": {"schema_version": "2", "revision": 0},
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab.chapter_text = _FakePlainTextEdit("")
        tab.chapter_outline = _FakePlainTextEdit("原规划提纲")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab.chapter_linked = _FakeLineEdit("")
        tab._chapter_ai_memory_repair_attempts = 0
        tab._chapter_ai_memory_pending = {}
        tab._chapter_ai_style_workflow_active = True
        tab._chapter_ai_sequence_started_outline = "原规划提纲"
        tab._ai_project_snapshot = lambda: deepcopy(tab.current_project)
        tab._set_partial_chapter_ai_preview_state = lambda *_args: None
        tab._set_line_text_without_signals = lambda widget, text: widget.setText(text)
        tab._refresh_long_form_record_views = lambda: None
        tab._mark_chapter_dirty = lambda: None
        tab._note_project_dirty = lambda: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)
        completions = []
        tab._on_auto_expand_chapter_completed = lambda changed: completions.append(changed)
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )
        final_text = "赵明进入王城，亲手取出封存多年的旧案卷宗。"
        invalid_bundle = {
            "outline": "赵明进入王城并找到旧案卷宗。",
            "summary": "赵明找到旧案卷宗。",
            "key_facts": "赵明已经取得旧案卷宗。",
            "memory_update": {},
        }

        tab._apply_style_final_result(final_text, invalid_bundle)

        self.assertEqual([item[0] for item in started], ["memory_repair"])
        self.assertIn("状态数据有", started[0][2])
        self.assertIn("项需修复", started[0][2])
        self.assertEqual(tab.chapter_text.toPlainText(), "")
        self.assertEqual(tab._chapter_ai_memory_repair_attempts, 1)
        repaired = json.dumps({
            "outline": "赵明进入王城并找到旧案卷宗。",
            "summary": "赵明进入王城，取得封存多年的旧案卷宗。",
            "key_facts": ["赵明已经取得旧案卷宗。"],
            "long_form_memory": {
                "schema_version": 2,
                "base_revision": 0,
                "state_patch": {},
                "state_retirements": {},
                "fact_updates": [],
                "state_delta": {},
                "current_chapter_character_refs": [],
                "stage_archive": None,
                "record_updates": {"characters": [], "lore": []},
                "foreshadow_updates": [],
                "next_chapter_memory": {},
                **self._strict_memory_controls(),
            },
        }, ensure_ascii=False)

        tab._handle_memory_repair_ready(repaired)

        memory = tab.current_project["long_form_memory"]
        updated_chapter = tab.current_project["chapters"][0]
        self.assertEqual(tab.chapter_text.toPlainText(), final_text)
        self.assertEqual(updated_chapter["text"], final_text)
        self.assertEqual(updated_chapter["memory_sync_status"], "complete")
        self.assertEqual(updated_chapter["memory_revision"], 1)
        self.assertTrue(updated_chapter["memory_update_hash"])
        self.assertEqual(memory["revision"], 1)
        self.assertEqual(len(memory["update_journal"]), 1)
        self.assertEqual(completions, [True])
        self.assertEqual(tab.chapter_ai_preview.toPlainText(), "")
        self.assertIn("已自动更新", statuses[-1])

    def test_mechanical_event_ref_cleanup_avoids_memory_repair(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "characters": [{"id": "char-a", "name": "赵明", "role": "主角"}],
            "lore": [],
            "foreshadow_items": [],
            "long_form_memory": {"schema_version": "2", "revision": 0},
        }
        tab.current_chapter_index = 0
        final_text = "赵明清点完药柜，确认三份药材仍由自己保管。"
        bundle = {
            "outline": "赵明清点药柜。",
            "summary": "赵明确认药材库存。",
            "key_facts": "三份药材仍由赵明保管。",
            "memory_update": {
                "schema_version": 2,
                "base_revision": 0,
                "state_patch": {},
                "state_retirements": {},
                "fact_updates": [{
                    "operation": "add",
                    "key": "NF1",
                    "scope": "object:medicine:inventory",
                    "fact": "三份药材仍由赵明保管",
                    "evidence_quote": "确认三份药材仍由自己保管",
                }],
                "fact_lifecycle_review": {
                    "scope": "current_chapter", "reviewed_refs": [], "notes": "已复核",
                },
                "state_lifecycle_review": {
                    "scope": "current_chapter",
                    "reviewed_object_keys": [],
                    "reviewed_conflict_refs": [],
                    "reviewed_task_refs": [],
                    "notes": "已复核",
                },
                "long_term_events": [{
                    "event": "赵明确认药材库存",
                    "category": "key_object",
                    "evidence_quote": "确认三份药材仍由自己保管",
                    "storage": {
                        "fact_refs": ["NF1", "NF1", "AF-9999"],
                        "character_refs": ["C999"],
                        "lore_refs": [], "foreshadow_refs": [], "object_keys": [],
                        "conflict_refs": [], "task_refs": [],
                    },
                }],
                "state_reconciliation": {
                    "checked": True,
                    "coverage_checks": {
                        "named_character_actions": True,
                        "state_changes": True,
                        "evidence_and_unknowns": True,
                        "mechanism_claims_match_body": True,
                        "rules_and_boundaries": True,
                        "foreshadow_and_ending": True,
                    },
                    "fact_refs": ["NF1"],
                    "character_refs": ["C001"],
                    "lore_refs": [], "foreshadow_refs": [], "relationship_refs": [],
                    "object_keys": [], "conflict_refs": [], "task_refs": [],
                    "resolved_contradictions": [], "notes": "已对账",
                },
                "state_delta": {},
                "record_updates": {
                    "characters": [{
                        "operation": "update",
                        "ref": "C001",
                        "state": "完成药柜清点",
                        "changes": ["确认药材库存"],
                        "evidence_quote": "赵明清点完药柜",
                    }],
                    "lore": [],
                },
                "foreshadow_updates": [],
                "current_chapter_character_refs": [],
                "stage_archive": None,
                "next_chapter_memory": {},
            },
        }

        errors = tab._memory_bundle_validation_errors(final_text, bundle)

        self.assertEqual(errors, [])
        storage = bundle["memory_update"]["long_term_events"][0]["storage"]
        self.assertEqual(storage["fact_refs"], ["NF1"])
        self.assertEqual(storage["character_refs"], [])

    def test_memory_repair_patch_preserves_valid_transaction_and_commits(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章"
        chapter["memory_selection"] = {"fact_ids": ["AF-0001"]}
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "long_form_memory": {
                "schema_version": "2",
                "revision": 0,
                "active_facts": [{
                    "id": "AF-0001",
                    "scope": "case:existing",
                    "fact": "旧案仍需调查",
                }],
            },
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab.chapter_text = _FakePlainTextEdit("")
        tab.chapter_outline = _FakePlainTextEdit("原规划提纲")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab.chapter_linked = _FakeLineEdit("")
        tab._chapter_ai_memory_repair_attempts = 0
        tab._chapter_ai_memory_pending = {}
        tab._chapter_ai_style_workflow_active = True
        tab._chapter_ai_sequence_started_outline = "原规划提纲"
        tab._ai_project_snapshot = lambda: deepcopy(tab.current_project)
        tab._set_partial_chapter_ai_preview_state = lambda *_args: None
        tab._set_line_text_without_signals = lambda widget, text: widget.setText(text)
        tab._refresh_long_form_record_views = lambda: None
        tab._mark_chapter_dirty = lambda: None
        tab._note_project_dirty = lambda: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab.set_status_tip = lambda _text: None
        tab._on_auto_expand_chapter_completed = lambda _changed: None
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="": started.append(
            (action, context, status_text)
        )
        final_text = "赵明取得旧案卷宗，决定继续调查。"
        invalid_bundle = {
            "outline": "赵明取得旧案卷宗。",
            "summary": "赵明取得卷宗并继续调查。",
            "key_facts": "赵明已经取得旧案卷宗。",
            "memory_update": {
                "schema_version": 2,
                "base_revision": 0,
                "state_patch": {},
                "state_retirements": {},
                "fact_updates": [{
                    "operation": "add",
                    "key": "NF1",
                    "scope": "object:case_file:ownership",
                    "fact": "赵明已经取得旧案卷宗",
                    "evidence_quote": "赵明取得旧案卷宗",
                }],
                "fact_lifecycle_review": {
                    "scope": "current_chapter",
                    "reviewed_refs": ["NF1"],
                    "notes": "误把新key当成旧ID",
                },
                "state_lifecycle_review": {
                    "scope": "current_chapter",
                    "reviewed_object_keys": [],
                    "reviewed_conflict_refs": [],
                    "reviewed_task_refs": [],
                    "notes": "已复核",
                },
                "long_term_events": [{
                    "event": "赵明取得旧案卷宗",
                    "category": "key_object",
                    "evidence_quote": "赵明取得旧案卷宗",
                    "storage": {
                        "fact_refs": ["NF1"], "character_refs": [], "lore_refs": [],
                        "foreshadow_refs": [], "object_keys": [], "conflict_refs": [],
                        "task_refs": [],
                    },
                }],
                "state_reconciliation": {
                    "checked": True,
                    "coverage_checks": {
                        "named_character_actions": True,
                        "state_changes": True,
                        "evidence_and_unknowns": True,
                        "mechanism_claims_match_body": True,
                        "rules_and_boundaries": True,
                        "foreshadow_and_ending": True,
                    },
                    "fact_refs": ["NF1"],
                    "character_refs": [],
                    "lore_refs": [],
                    "foreshadow_refs": [],
                    "relationship_refs": [],
                    "object_keys": [],
                    "conflict_refs": [],
                    "task_refs": [],
                    "resolved_contradictions": [],
                    "notes": "已对账",
                },
                "state_delta": {},
                "current_chapter_character_refs": [],
                "stage_archive": None,
                "record_updates": {"characters": [], "lore": []},
                "foreshadow_updates": [],
                "next_chapter_memory": {},
            },
        }

        tab._apply_style_final_result(final_text, invalid_bundle)

        self.assertEqual([item[0] for item in started], ["memory_repair"])
        self.assertIn("【状态增量修复补丁】", started[0][1])
        patch_result = json.dumps({
            "long_form_memory_patch": {
                "replace": {
                    "fact_lifecycle_review": {
                        "scope": "current_chapter",
                        "reviewed_refs": ["AF-0001"],
                        "notes": "已复核旧事实",
                    }
                }
            }
        }, ensure_ascii=False)

        tab._handle_memory_repair_ready(patch_result)

        memory = tab.current_project["long_form_memory"]
        updated_chapter = tab.current_project["chapters"][0]
        self.assertEqual(tab.chapter_text.toPlainText(), final_text)
        self.assertEqual(updated_chapter["memory_sync_status"], "complete")
        self.assertEqual(memory["revision"], 1)
        self.assertEqual(len(memory["active_facts"]), 2)
        self.assertEqual(memory["active_facts"][-1]["fact"], "赵明已经取得旧案卷宗")

    def test_memory_repair_stops_auto_expand_after_three_retries(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [chapter],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "long_form_memory": {"schema_version": "2", "revision": 0},
        }
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab.chapter_text = _FakePlainTextEdit("")
        tab.chapter_outline = _FakePlainTextEdit("原规划提纲")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab.chapter_linked = _FakeLineEdit("")
        tab._chapter_ai_memory_repair_attempts = 0
        tab._chapter_ai_memory_pending = {}
        tab._chapter_ai_style_workflow_active = True
        tab._chapter_ai_sequence_started_outline = "原规划提纲"
        tab._auto_expand_all_active = True
        tab._ai_project_snapshot = lambda: deepcopy(tab.current_project)
        tab._set_partial_chapter_ai_preview_state = lambda *_args: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)
        stopped = []
        def stop_auto_expand(message):
            tab._auto_expand_all_active = False
            stopped.append(message)
        tab._stop_auto_expand_all = stop_auto_expand
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status_text="", resume_prefix="", **_kwargs: started.append(
            (action, context, status_text)
        )
        final_text = "赵明进入王城，亲手取出封存多年的旧案卷宗。"
        invalid_bundle = {
            "outline": "赵明进入王城并找到旧案卷宗。",
            "summary": "赵明找到旧案卷宗。",
            "key_facts": "赵明已经取得旧案卷宗。",
            "memory_update": {},
        }

        tab._apply_style_final_result(final_text, invalid_bundle)
        with patch(
            "gpt_desktop.novel_writing_tab.QTimer.singleShot",
            side_effect=lambda _delay, callback: callback(),
        ):
            tab._handle_memory_repair_ready("不是合法JSON")
            tab._handle_memory_repair_ready("仍然不是合法JSON")
            tab._handle_memory_repair_ready("第三次仍然不是合法JSON")
            tab._handle_memory_repair_ready("第四次仍然不是合法JSON")

        self.assertEqual([item[0] for item in started], ["memory_repair"] * 4)
        self.assertEqual(tab._chapter_ai_memory_repair_attempts, 4)
        self.assertFalse(tab._auto_expand_all_active)
        self.assertEqual(len(stopped), 1)
        self.assertIn("状态同步失败", stopped[0])
        self.assertEqual(chapter["memory_sync_status"], "failed")
        self.assertEqual(tab.current_project["long_form_memory"]["revision"], 0)
        self.assertEqual(tab.chapter_text.toPlainText(), "")
        self.assertEqual(tab.chapter_ai_preview.toPlainText(), final_text)
        self.assertIn("未写入章节", statuses[-1])

    def test_chapter_ai_sequence_keeps_existing_planned_outline(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_title = _FakeLineEdit("第一章")
        tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "大纲")
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_outline = _FakePlainTextEdit("规划提纲：本章要完成权限边界会议。")
        tab.chapter_text = _FakePlainTextEdit("")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab._dirty = False
        tab._loading = False
        tab._refresh_chapter_item = lambda _index: None
        tab._schedule_refresh = lambda include_manuscript=False: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab._set_chapter_ai_actions_enabled = lambda _enabled: None
        tab._chapter_ai_resume_prefix = ""
        tab._chapter_ai_stop_requested_by_user = False
        tab._chapter_ai_running_action = ""
        tab._chapter_ai_buttons_by_action = {}
        tab._chapter_ai_provider = {"base_url": "http://example.test", "api_key": "key", "proxy_url": ""}
        tab._chapter_ai_model = "model"
        tab._provider_proxy_mode = lambda _provider: "不使用代理"
        tab._current_novel_ai_selection = lambda: (tab._chapter_ai_provider, tab._chapter_ai_model, "")
        tab._flush_current_editors = lambda: None
        tab._chapter_ai_context_with_preview = lambda action: f"context:{action}"
        started = []
        finalized = []
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)
        tab._start_chapter_ai_worker = lambda action, _context, status_text="", resume_prefix="": (
            statuses.append(status_text) if status_text else None,
            started.append(action),
        )
        tab._start_memory_finalize = lambda text: finalized.append(text)

        tab._start_chapter_ai_sequence()
        tab.chapter_ai_preview.setPlainText("AI 正文")
        tab.on_chapter_ai_ready("draft", "AI 正文")

        self.assertEqual(started, ["draft"])
        self.assertEqual(tab.chapter_outline.toPlainText(), "规划提纲：本章要完成权限边界会议。")
        self.assertEqual(tab.chapter_text.toPlainText(), "")
        self.assertEqual(finalized, ["AI 正文"])

    def test_partial_draft_restart_rewrites_full_chapter_then_finishes_with_summary(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.writing_worker = None
        tab.chapter_ai_preview = _FakePlainTextEdit("断线正文")
        tab.chapter_title = _FakeLineEdit("第一章")
        tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "写作中")
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_outline = _FakePlainTextEdit("章节提纲")
        tab.chapter_text = _FakePlainTextEdit("")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab._dirty = False
        tab._loading = False
        tab._refresh_chapter_item = lambda _index: None
        tab._schedule_refresh = lambda include_manuscript=False: None
        tab._set_text_without_signals = lambda widget, text: widget.setPlainText(text)
        tab._set_line_text_without_signals = lambda widget, text: widget.setText(text)
        tab._infer_current_chapter_linked_names = lambda extra_text="": []
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab.set_status_tip = lambda _text: None
        tab._set_chapter_ai_actions_enabled = lambda _enabled: None
        tab._chapter_ai_preview_is_partial = True
        tab._chapter_ai_preview_action = "draft"
        tab._chapter_ai_preview_chapter_id = chapter["id"]
        tab._chapter_ai_resume_prefix = ""
        tab._chapter_ai_stop_requested_by_user = False
        tab._chapter_ai_running_action = ""
        tab._chapter_ai_buttons_by_action = {}
        tab._chapter_ai_provider = {"base_url": "http://example.test", "api_key": "key", "proxy_url": ""}
        tab._chapter_ai_model = "model"
        tab._provider_proxy_mode = lambda _provider: "不使用代理"
        tab._current_novel_ai_selection = lambda: (tab._chapter_ai_provider, tab._chapter_ai_model, "")
        tab._flush_current_editors = lambda: None
        tab._chapter_ai_context_with_preview = lambda action: f"context:{action}"
        started = []
        finalized = []
        tab._start_chapter_ai_worker = lambda action, _context, status_text="", resume_prefix="": started.append(action)
        tab._start_memory_finalize = lambda text: finalized.append(text)

        tab.run_chapter_ai_action("draft")
        self.assertEqual(started, ["draft"])
        self.assertTrue(tab._chapter_ai_sequence_active)

        tab.chapter_ai_preview.setPlainText("断线正文续完")
        tab.on_chapter_ai_ready("draft", "断线正文续完")

        self.assertEqual(tab.chapter_text.toPlainText(), "")
        self.assertEqual(tab.chapter_ai_preview.toPlainText(), "断线正文续完")
        self.assertEqual(tab.chapter_outline.toPlainText(), "章节提纲")
        self.assertEqual(started, ["draft"])
        self.assertEqual(finalized, ["断线正文续完"])

    def test_partial_outline_restart_returns_to_full_draft(self):
        chapter = _new_chapter(0)
        chapter["text"] = "已完成正文"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.writing_worker = None
        tab.chapter_ai_preview = _FakePlainTextEdit("断线提纲")
        tab.chapter_title = _FakeLineEdit("第一章")
        tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "写作中")
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_outline = _FakePlainTextEdit("")
        tab.chapter_text = _FakePlainTextEdit("已完成正文")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab._dirty = False
        tab._loading = False
        tab._refresh_chapter_item = lambda _index: None
        tab._schedule_refresh = lambda include_manuscript=False: None
        tab._set_text_without_signals = lambda widget, text: widget.setPlainText(text)
        tab._infer_current_chapter_linked_names = lambda extra_text="": []
        tab._merge_chapter_linked_names = lambda _names: None
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab.set_status_tip = lambda _text: None
        tab._set_chapter_ai_actions_enabled = lambda _enabled: None
        tab._chapter_ai_preview_is_partial = True
        tab._chapter_ai_preview_action = "outline"
        tab._chapter_ai_preview_chapter_id = chapter["id"]
        tab._chapter_ai_resume_prefix = ""
        tab._chapter_ai_stop_requested_by_user = False
        tab._chapter_ai_running_action = ""
        button = _FakeButton()
        tab._chapter_ai_buttons_by_action = {"draft": button}
        tab._chapter_ai_provider = {"base_url": "http://example.test", "api_key": "key", "proxy_url": ""}
        tab._chapter_ai_model = "model"
        tab._provider_proxy_mode = lambda _provider: "不使用代理"
        tab._current_novel_ai_selection = lambda: (tab._chapter_ai_provider, tab._chapter_ai_model, "")
        tab._flush_current_editors = lambda: None
        tab._chapter_ai_context_with_preview = lambda action: f"context:{action}"
        started = []
        tab._start_chapter_ai_worker = lambda action, _context, status_text="", resume_prefix="": started.append(action)

        tab.run_chapter_ai_action("draft")

        self.assertEqual(started, ["draft"])
        self.assertTrue(tab._chapter_ai_sequence_active)
        self.assertEqual(button.text, "扩写正文并补提纲和摘要")
        self.assertEqual(tab.chapter_text.toPlainText(), "")
        self.assertFalse(tab._has_partial_chapter_ai_preview())

    def test_partial_summary_restart_returns_to_full_draft(self):
        chapter = _new_chapter(0)
        chapter["text"] = "已完成正文"
        chapter["outline"] = "已完成提纲"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.writing_worker = None
        tab.chapter_ai_preview = _FakePlainTextEdit("断线摘要")
        tab.chapter_title = _FakeLineEdit("第一章")
        tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "写作中")
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_outline = _FakePlainTextEdit("已完成提纲")
        tab.chapter_text = _FakePlainTextEdit("已完成正文")
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab._dirty = False
        tab._loading = False
        tab._refresh_chapter_item = lambda _index: None
        tab._schedule_refresh = lambda include_manuscript=False: None
        tab._set_text_without_signals = lambda widget, text: widget.setPlainText(text)
        tab._set_line_text_without_signals = lambda widget, text: widget.setText(text)
        tab._infer_current_chapter_linked_names = lambda extra_text="": []
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab.set_status_tip = lambda _text: None
        tab._set_chapter_ai_actions_enabled = lambda _enabled: None
        tab._chapter_ai_preview_is_partial = True
        tab._chapter_ai_preview_action = "summary"
        tab._chapter_ai_preview_chapter_id = chapter["id"]
        tab._chapter_ai_resume_prefix = ""
        tab._chapter_ai_stop_requested_by_user = False
        tab._chapter_ai_running_action = ""
        button = _FakeButton()
        tab._chapter_ai_buttons_by_action = {"draft": button}
        tab._chapter_ai_provider = {"base_url": "http://example.test", "api_key": "key", "proxy_url": ""}
        tab._chapter_ai_model = "model"
        tab._provider_proxy_mode = lambda _provider: "不使用代理"
        tab._current_novel_ai_selection = lambda: (tab._chapter_ai_provider, tab._chapter_ai_model, "")
        tab._flush_current_editors = lambda: None
        tab._chapter_ai_context_with_preview = lambda action: f"context:{action}"
        started = []
        tab._start_chapter_ai_worker = lambda action, _context, status_text="", resume_prefix="": started.append(action)

        tab.run_chapter_ai_action("draft")

        self.assertEqual(started, ["draft"])
        self.assertTrue(tab._chapter_ai_sequence_active)
        self.assertEqual(button.text, "扩写正文并补提纲和摘要")
        self.assertEqual(tab.chapter_text.toPlainText(), "")
        self.assertFalse(tab._has_partial_chapter_ai_preview())

    def test_partial_draft_preview_is_excluded_from_rewrite_context(self):
        chapter = _new_chapter(0)
        chapter["draft_words"] = "5000"
        chapter["text"] = "甲" * 1000
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_project["draft_note"] = "私有备注锚点：不能交给 AI。"
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("乙" * 1000)
        tab._chapter_ai_preview_is_partial = True
        tab._chapter_ai_preview_action = "draft"
        tab._chapter_ai_preview_chapter_id = chapter["id"]
        tab._flush_current_editors = lambda: None

        context = tab._chapter_ai_context_with_preview("draft")

        self.assertIn("当前正文长度：约1000字", context)
        self.assertIn("本次新增正文参考目标：约4000字", context)
        self.assertNotIn("乙" * 100, context)
        self.assertNotIn("私有备注锚点", context)
        self.assertEqual(tab.current_project["chapters"][0]["text"], "甲" * 1000)

    def test_failed_draft_preview_keeps_full_rewrite_button(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = "断线前正文"
        tab._chapter_ai_running_action = "draft"
        tab._chapter_ai_preview_is_partial = False
        tab._chapter_ai_preview_action = ""
        tab._chapter_ai_preview_chapter_id = ""
        button = _FakeButton()
        tab._chapter_ai_buttons_by_action = {"draft": button}
        tab.set_status_tip = lambda _text: None

        import gpt_desktop.novel_writing_tab as writing_tab
        original_warning = writing_tab.QMessageBox.warning
        try:
            writing_tab.QMessageBox.warning = lambda *_args, **_kwargs: None
            tab.on_chapter_ai_failed("timeout")
        finally:
            writing_tab.QMessageBox.warning = original_warning

        self.assertEqual(tab.chapter_ai_preview.toPlainText(), "断线前正文")
        self.assertTrue(tab._has_partial_draft_preview())
        self.assertEqual(button.text, "扩写正文并补提纲和摘要")
        self.assertIn("丢弃未完成预览", button.tooltip)

    def test_transient_style_finalize_failure_schedules_retry_without_stopping_sequence(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab._chapter_ai_running_action = "style_finalize"
        tab._chapter_ai_running_context = "同一份终稿审校上下文"
        tab._chapter_ai_running_status_text = "正在执行终稿审校..."
        tab._chapter_ai_running_chapter_id = chapter["id"]
        tab._chapter_ai_transient_retry_counts = {}
        tab._chapter_ai_transient_retry_pending = False
        tab._chapter_ai_transient_retry_token = 0
        tab._chapter_ai_stop_requested_by_user = False
        tab._chapter_ai_style_workflow_active = True
        tab._chapter_ai_sequence_active = True
        tab._auto_expand_all_active = True
        statuses = []
        scheduled = []
        tab.set_status_tip = lambda text: statuses.append(text)

        with patch(
            "gpt_desktop.novel_writing_tab.QTimer.singleShot",
            side_effect=lambda delay, callback: scheduled.append((delay, callback)),
        ):
            tab.on_chapter_ai_failed("Upstream request failed")

        self.assertTrue(tab._chapter_ai_sequence_active)
        self.assertTrue(tab._auto_expand_all_active)
        self.assertTrue(tab._chapter_ai_transient_retry_pending)
        self.assertEqual(scheduled[0][0], 10000)
        self.assertIn("自动重试", statuses[-1])

    def test_transient_style_finalize_retry_reuses_same_action_and_context(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab._chapter_ai_running_context = "不能重建的终稿审校上下文"
        tab._chapter_ai_running_status_text = "正在执行终稿审校..."
        tab._chapter_ai_running_chapter_id = chapter["id"]
        tab._chapter_ai_transient_retry_counts = {}
        tab._chapter_ai_transient_retry_pending = False
        tab._chapter_ai_transient_retry_token = 0
        tab._chapter_ai_stop_requested_by_user = False
        tab._chapter_ai_style_workflow_active = True
        tab.writing_worker = None
        tab.set_status_tip = lambda _text: None
        started = []
        tab._start_chapter_ai_worker = lambda action, context, status="", **kwargs: started.append(
            (action, context, status, kwargs)
        )
        scheduled = []

        with patch(
            "gpt_desktop.novel_writing_tab.QTimer.singleShot",
            side_effect=lambda delay, callback: scheduled.append((delay, callback)),
        ):
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("style_finalize", "timeout"))
            scheduled[0][1]()

        self.assertEqual(started[0][0], "style_finalize")
        self.assertEqual(started[0][1], "不能重建的终稿审校上下文")
        self.assertTrue(started[0][3]["transient_retry"])

    def test_transient_chapter_ai_retry_is_capped_at_three_with_fixed_delays(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab._chapter_ai_running_context = "终稿上下文"
        tab._chapter_ai_running_status_text = ""
        tab._chapter_ai_running_chapter_id = chapter["id"]
        tab._chapter_ai_transient_retry_counts = {}
        tab._chapter_ai_transient_retry_pending = False
        tab._chapter_ai_transient_retry_token = 0
        tab._chapter_ai_stop_requested_by_user = False
        tab.set_status_tip = lambda _text: None

        with patch("gpt_desktop.novel_writing_tab.QTimer.singleShot") as single_shot:
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("style_finalize", "接口错误 503"))
            tab._chapter_ai_transient_retry_pending = False
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("style_finalize", "接口错误 503"))
            tab._chapter_ai_transient_retry_pending = False
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("style_finalize", "接口错误 503"))
            tab._chapter_ai_transient_retry_pending = False
            self.assertFalse(tab._schedule_transient_chapter_ai_retry("style_finalize", "接口错误 503"))

        self.assertEqual(single_shot.call_count, 3)
        self.assertEqual([call.args[0] for call in single_shot.call_args_list], [10000, 20000, 30000])

    def test_transient_memory_repair_uses_same_three_retry_budget(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab._chapter_ai_running_context = "状态增量修复补丁"
        tab._chapter_ai_running_status_text = ""
        tab._chapter_ai_running_chapter_id = chapter["id"]
        tab._chapter_ai_transient_retry_counts = {}
        tab._chapter_ai_transient_retry_pending = False
        tab._chapter_ai_transient_retry_token = 0
        tab._chapter_ai_stop_requested_by_user = False
        tab.set_status_tip = lambda _text: None

        with patch("gpt_desktop.novel_writing_tab.QTimer.singleShot") as single_shot:
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("memory_repair", "remote end closed"))
            tab._chapter_ai_transient_retry_pending = False
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("memory_repair", "remote end closed"))
            tab._chapter_ai_transient_retry_pending = False
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("memory_repair", "remote end closed"))
            tab._chapter_ai_transient_retry_pending = False
            self.assertFalse(tab._schedule_transient_chapter_ai_retry("memory_repair", "remote end closed"))

        self.assertEqual(single_shot.call_count, 3)
        self.assertEqual([call.args[0] for call in single_shot.call_args_list], [10000, 20000, 30000])

    def test_empty_output_uses_same_three_retry_budget_with_clear_status(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab._chapter_ai_running_context = "原样重试的状态修复上下文"
        tab._chapter_ai_running_status_text = "正在修复状态..."
        tab._chapter_ai_running_chapter_id = chapter["id"]
        tab._chapter_ai_transient_retry_counts = {}
        tab._chapter_ai_transient_retry_pending = False
        tab._chapter_ai_transient_retry_token = 0
        tab._chapter_ai_stop_requested_by_user = False
        statuses = []
        tab.set_status_tip = statuses.append
        error = "AI 没有返回有效内容。 finish_reason=stop"

        with patch("gpt_desktop.novel_writing_tab.QTimer.singleShot") as single_shot:
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("style_finalize", error))
            tab._chapter_ai_transient_retry_pending = False
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("style_finalize", error))
            tab._chapter_ai_transient_retry_pending = False
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("style_finalize", error))
            tab._chapter_ai_transient_retry_pending = False
            self.assertFalse(tab._schedule_transient_chapter_ai_retry("style_finalize", error))

        self.assertEqual(single_shot.call_count, 3)
        self.assertEqual([call.args[0] for call in single_shot.call_args_list], [10000, 20000, 30000])
        self.assertIn("当前步骤未通过", statuses[0])
        self.assertIn("（1/3）", statuses[0])

    def test_oversized_memory_output_uses_same_three_retry_budget(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab._chapter_ai_running_context = "原样重试的状态整理上下文"
        tab._chapter_ai_running_status_text = "正在独立整理本章摘要和长期状态..."
        tab._chapter_ai_running_chapter_id = chapter["id"]
        tab._chapter_ai_transient_retry_counts = {}
        tab._chapter_ai_transient_retry_pending = False
        tab._chapter_ai_transient_retry_token = 0
        tab._chapter_ai_stop_requested_by_user = False
        statuses = []
        tab.set_status_tip = statuses.append
        error = "AI 章节状态整理输出异常膨胀（已超过36000字），已中止本次结果。"

        with patch("gpt_desktop.novel_writing_tab.QTimer.singleShot") as single_shot:
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("memory_finalize", error))
            tab._chapter_ai_transient_retry_pending = False
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("memory_finalize", error))
            tab._chapter_ai_transient_retry_pending = False
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("memory_finalize", error))
            tab._chapter_ai_transient_retry_pending = False
            self.assertFalse(tab._schedule_transient_chapter_ai_retry("memory_finalize", error))

        self.assertEqual(single_shot.call_count, 3)
        self.assertEqual([call.args[0] for call in single_shot.call_args_list], [10000, 20000, 30000])
        self.assertIn("当前步骤未通过", statuses[0])
        self.assertIn("（1/3）", statuses[0])
        self.assertTrue(NovelWritingTab._is_transient_chapter_ai_error(error))

    def test_incomplete_style_execution_retries_whole_draft_with_three_budget(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab._chapter_ai_running_context = "完整剧情执行稿上下文"
        tab._chapter_ai_running_status_text = "正在生成剧情执行稿..."
        tab._chapter_ai_running_chapter_id = chapter["id"]
        tab._chapter_ai_transient_retry_counts = {}
        tab._chapter_ai_transient_retry_pending = False
        tab._chapter_ai_transient_retry_token = 0
        tab._chapter_ai_stop_requested_by_user = False
        statuses = []
        tab.set_status_tip = statuses.append
        error = "AI 剧情执行稿结构不完整，已丢弃本次半成品，请重新扩写正文。"

        with patch("gpt_desktop.novel_writing_tab.QTimer.singleShot") as single_shot:
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("draft", error))
            tab._chapter_ai_transient_retry_pending = False
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("draft", error))
            tab._chapter_ai_transient_retry_pending = False
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("draft", error))
            tab._chapter_ai_transient_retry_pending = False
            self.assertFalse(tab._schedule_transient_chapter_ai_retry("draft", error))

        self.assertEqual(single_shot.call_count, 3)
        self.assertEqual([call.args[0] for call in single_shot.call_args_list], [10000, 20000, 30000])
        self.assertIn("当前步骤未通过", statuses[0])

    def test_empty_output_shares_budget_with_network_failures(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab._chapter_ai_running_context = "完整剧情执行稿上下文"
        tab._chapter_ai_running_status_text = "正在生成剧情执行稿..."
        tab._chapter_ai_running_chapter_id = chapter["id"]
        tab._chapter_ai_transient_retry_counts = {}
        tab._chapter_ai_transient_retry_pending = False
        tab._chapter_ai_transient_retry_token = 0
        tab._chapter_ai_stop_requested_by_user = False
        statuses = []
        tab.set_status_tip = statuses.append

        with patch("gpt_desktop.novel_writing_tab.QTimer.singleShot") as single_shot:
            for _ in range(2):
                self.assertTrue(tab._schedule_transient_chapter_ai_retry("draft", "接口错误 503"))
                tab._chapter_ai_transient_retry_pending = False
            empty_error = (
                "AI 没有返回有效内容：厂商返回 HTTP 200 并正常结束，但正文为0字。"
            )
            self.assertTrue(tab._schedule_transient_chapter_ai_retry("draft", empty_error))
            tab._chapter_ai_transient_retry_pending = False
            self.assertFalse(tab._schedule_transient_chapter_ai_retry("draft", empty_error))

        self.assertEqual(single_shot.call_count, 3)
        self.assertIn("当前步骤未通过", statuses[-1])
        self.assertIn("（3/3）", statuses[-1])

    def test_transient_retry_delay_is_fixed(self):
        self.assertEqual(NovelWritingTab._transient_chapter_ai_retry_delay(1), 10)
        self.assertEqual(NovelWritingTab._transient_chapter_ai_retry_delay(2), 20)
        self.assertEqual(NovelWritingTab._transient_chapter_ai_retry_delay(3), 30)

    def test_ssl_eof_connection_failure_is_treated_as_transient(self):
        error = (
            "HTTPSConnectionPool(host='api.example.test', port=443): Max retries exceeded "
            "(Caused by SSLError(SSLEOFError(8, 'EOF occurred in violation of protocol')))"
        )

        self.assertTrue(NovelWritingTab._is_transient_chapter_ai_error(error))

    def test_cloudflare_524_failure_is_treated_as_transient(self):
        error = (
            "接口错误 524：中转服务器超时 524：Cloudflare 已连接到中转站，"
            "但中转站长时间没有返回结果。"
        )

        self.assertTrue(NovelWritingTab._is_transient_chapter_ai_error(error))

    def test_plain_english_upstream_unavailable_is_treated_as_transient(self):
        self.assertTrue(NovelWritingTab._is_transient_chapter_ai_error(
            "Upstream service temporarily unavailable"
        ))

    def test_upstream_response_stream_interruption_is_treated_as_transient(self):
        self.assertTrue(NovelWritingTab._is_transient_chapter_ai_error(
            "Upstream response stream was interrupted"
        ))

    def test_non_transient_chapter_ai_error_is_not_retried(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._chapter_ai_stop_requested_by_user = False

        self.assertFalse(tab._schedule_transient_chapter_ai_retry("style_finalize", "返回格式无法解析"))

    def test_clearing_failed_draft_preview_keeps_full_rewrite_button(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("断线前正文")
        tab._chapter_ai_preview_is_partial = True
        tab._chapter_ai_preview_action = "draft"
        tab._chapter_ai_preview_chapter_id = chapter["id"]
        button = _FakeButton()
        tab._chapter_ai_buttons_by_action = {"draft": button}

        tab._refresh_chapter_ai_action_labels()
        self.assertEqual(button.text, "扩写正文并补提纲和摘要")

        tab.chapter_ai_preview.setPlainText("")
        tab._on_chapter_ai_preview_text_changed()

        self.assertFalse(tab._has_partial_draft_preview())
        self.assertEqual(button.text, "扩写正文并补提纲和摘要")

    def test_failed_draft_without_preview_keeps_expand_button_and_rewrite_status(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab._chapter_ai_running_action = "draft"
        tab._chapter_ai_preview_is_partial = True
        tab._chapter_ai_preview_action = "draft"
        tab._chapter_ai_preview_chapter_id = chapter["id"]
        button = _FakeButton()
        tab._chapter_ai_buttons_by_action = {"draft": button}
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)

        import gpt_desktop.novel_writing_tab as writing_tab
        original_warning = writing_tab.QMessageBox.warning
        try:
            writing_tab.QMessageBox.warning = lambda *_args, **_kwargs: None
            tab.on_chapter_ai_failed("timeout")
        finally:
            writing_tab.QMessageBox.warning = original_warning

        self.assertEqual(tab.chapter_ai_preview.toPlainText(), "")
        self.assertFalse(tab._has_partial_draft_preview())
        self.assertEqual(button.text, "扩写正文并补提纲和摘要")
        self.assertIn("可重新扩写正文", statuses[-1])
        self.assertNotIn("续写正文", statuses[-1])

    def test_incomplete_style_execution_discards_partial_instead_of_offering_continuation(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = "【剧情执行清单】\n未完成的结构"
        tab._chapter_ai_running_action = "draft"
        tab._chapter_ai_preview_is_partial = False
        tab._chapter_ai_preview_action = ""
        tab._chapter_ai_preview_chapter_id = ""
        tab._chapter_ai_style_workflow_active = True
        tab._chapter_ai_style_execution = "旧执行稿"
        tab._chapter_ai_style_plan = "旧声纹表"
        button = _FakeButton()
        tab._chapter_ai_buttons_by_action = {"draft": button}
        statuses = []
        tab.set_status_tip = statuses.append

        import gpt_desktop.novel_writing_tab as writing_tab
        original_warning = writing_tab.QMessageBox.warning
        try:
            writing_tab.QMessageBox.warning = lambda *_args, **_kwargs: None
            tab.on_chapter_ai_failed(
                "AI 剧情执行稿结构不完整，已丢弃本次半成品，请重新扩写正文。"
            )
        finally:
            writing_tab.QMessageBox.warning = original_warning

        self.assertEqual(tab.chapter_ai_preview.toPlainText(), "")
        self.assertEqual(tab.chapter_ai_stream_text, "")
        self.assertFalse(tab._has_partial_draft_preview())
        self.assertFalse(tab._chapter_ai_style_workflow_active)
        self.assertEqual(tab._chapter_ai_style_execution, "")
        self.assertEqual(tab._chapter_ai_style_plan, "")
        self.assertEqual(button.text, "扩写正文并补提纲和摘要")
        self.assertIn("半成品已丢弃", statuses[-1])
        self.assertNotIn("续写正文", statuses[-1])

    def test_failed_sequence_draft_keeps_partial_preview_out_of_chapter_text(self):
        chapter = _new_chapter(0)
        chapter["text"] = "原正文"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_text = _FakePlainTextEdit("原正文")
        tab.chapter_ai_stream_text = "断线半截正文"
        tab._chapter_ai_running_action = "draft"
        tab._chapter_ai_preview_is_partial = False
        tab._chapter_ai_preview_action = ""
        tab._chapter_ai_preview_chapter_id = ""
        tab._chapter_ai_sequence_active = True
        tab._chapter_ai_sequence_chapter_id = chapter["id"]
        tab._chapter_ai_sequence_started_outline = ""
        button = _FakeButton()
        tab._chapter_ai_buttons_by_action = {"draft": button}
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)

        import gpt_desktop.novel_writing_tab as writing_tab
        original_warning = writing_tab.QMessageBox.warning
        try:
            writing_tab.QMessageBox.warning = lambda *_args, **_kwargs: None
            tab.on_chapter_ai_failed("AI 输出未完整结束，已保留当前预览内容，可点续写正文继续。")
        finally:
            writing_tab.QMessageBox.warning = original_warning

        self.assertEqual(tab.chapter_text.toPlainText(), "原正文")
        self.assertEqual(tab.chapter_ai_preview.toPlainText(), "断线半截正文")
        self.assertTrue(tab._has_partial_draft_preview())
        self.assertEqual(button.text, "扩写正文并补提纲和摘要")
        self.assertIn("丢弃半成品并重写整章", statuses[-1])

    def test_failed_outline_without_preview_keeps_full_rewrite_button(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab._chapter_ai_running_action = "outline"
        tab._chapter_ai_preview_is_partial = False
        tab._chapter_ai_preview_action = ""
        tab._chapter_ai_preview_chapter_id = ""
        button = _FakeButton()
        tab._chapter_ai_buttons_by_action = {"draft": button}
        tab.set_status_tip = lambda _text: None

        import gpt_desktop.novel_writing_tab as writing_tab
        original_warning = writing_tab.QMessageBox.warning
        try:
            writing_tab.QMessageBox.warning = lambda *_args, **_kwargs: None
            tab.on_chapter_ai_failed("timeout")
        finally:
            writing_tab.QMessageBox.warning = original_warning

        self.assertEqual(tab.chapter_ai_preview.toPlainText(), "")
        self.assertTrue(tab._has_partial_chapter_ai_preview("outline"))
        self.assertEqual(button.text, "扩写正文并补提纲和摘要")

    def test_save_chapter_auto_updates_default_status(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab.chapter_title = _FakeLineEdit("第一章")
        tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "大纲")
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_outline = _FakePlainTextEdit("章节提纲")
        tab.chapter_text = _FakePlainTextEdit("章节正文")
        tab.chapter_summary = _FakePlainTextEdit("章节摘要")
        tab.chapter_key_facts = _FakePlainTextEdit("关键事实")
        tab._refresh_chapter_item = lambda _index: None

        tab._save_chapter_from_editor()

        self.assertEqual(tab.current_project["chapters"][0]["status"], "已完成")
        self.assertEqual(tab.chapter_status.currentText(), "已完成")

    def test_save_chapter_keeps_manual_rewrite_status(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab.chapter_title = _FakeLineEdit("第一章")
        tab.chapter_status = _FakeComboBox(["大纲", "写作中", "已完成", "待重写"], "待重写")
        tab.chapter_linked = _FakeLineEdit("")
        tab.chapter_outline = _FakePlainTextEdit("章节提纲")
        tab.chapter_text = _FakePlainTextEdit("章节正文")
        tab.chapter_summary = _FakePlainTextEdit("章节摘要")
        tab.chapter_key_facts = _FakePlainTextEdit("关键事实")
        tab._refresh_chapter_item = lambda _index: None

        tab._save_chapter_from_editor()

        self.assertEqual(tab.current_project["chapters"][0]["status"], "待重写")
        self.assertEqual(tab.chapter_status.currentText(), "待重写")

    def test_split_chapter_summary_bundle_parses_linked_characters(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            "本章摘要：赵明进入王城。\n"
            "本章需继承的关键事实：赵明拿到旧案钥匙。\n"
            "本章关联人物：赵明、迟到主角"
        )

        self.assertEqual(summary, "赵明进入王城。")
        self.assertEqual(key_facts, "赵明拿到旧案钥匙。")
        self.assertEqual(linked, ["赵明", "迟到主角"])

    def test_split_chapter_summary_bundle_accepts_bulleted_headings(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            "- 本章摘要：赵明进入王城。\n"
            "1. 本章需继承的关键事实：赵明拿到旧案钥匙。\n"
            "2. 本章关联人物：赵明、迟到主角"
        )

        self.assertEqual(summary, "赵明进入王城。")
        self.assertEqual(key_facts, "赵明拿到旧案钥匙。")
        self.assertEqual(linked, ["赵明", "迟到主角"])

    def test_split_chapter_summary_bundle_accepts_markdown_headings(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            "### 本章摘要\n"
            "赵明进入王城。\n\n"
            "**本章需继承的关键事实**\n"
            "赵明拿到旧案钥匙。\n\n"
            "### 本章关联人物\n"
            "赵明、迟到主角"
        )

        self.assertEqual(summary, "赵明进入王城。")
        self.assertEqual(key_facts, "赵明拿到旧案钥匙。")
        self.assertEqual(linked, ["赵明", "迟到主角"])

    def test_split_chapter_summary_bundle_accepts_json_output(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            '{"本章摘要":"赵明进入王城。","本章需继承的关键事实":["赵明拿到旧案钥匙。","王城暗门开启。"],"本章关联人物":["赵明","迟到主角"]}'
        )

        self.assertEqual(summary, "赵明进入王城。")
        self.assertEqual(key_facts, "赵明拿到旧案钥匙。\n王城暗门开启。")
        self.assertEqual(linked, ["赵明", "迟到主角"])

    def test_split_chapter_summary_bundle_keeps_all_key_facts(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        facts = "\n".join(f"{index}. 关键事实{index}会影响后文。" for index in range(1, 10))

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            "本章摘要：赵明进入王城。\n"
            "本章需继承的关键事实：\n"
            f"{facts}\n"
            "本章关联人物：赵明"
        )

        self.assertEqual(summary, "赵明进入王城。")
        self.assertEqual(len(key_facts.splitlines()), 9)
        self.assertIn("关键事实9会影响后文。", key_facts)
        self.assertEqual(linked, ["赵明"])

    def test_split_chapter_summary_bundle_accepts_fenced_json_output(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            "```json\n"
            '{"summary":"赵明进入王城。","key_facts":"赵明拿到旧案钥匙。","linked_characters":"赵明、迟到主角"}'
            "\n```"
        )

        self.assertEqual(summary, "赵明进入王城。")
        self.assertEqual(key_facts, "赵明拿到旧案钥匙。")
        self.assertEqual(linked, ["赵明", "迟到主角"])

    def test_split_chapter_summary_bundle_accepts_json_object_lists(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            '{"summary":{"text":"赵明进入王城。"},"facts":[{"fact":"赵明拿到旧案钥匙。"},{"内容":"王城暗门开启。"}],"characters":[{"name":"赵明"},{"名称":"迟到主角"}]}'
        )

        self.assertEqual(summary, "赵明进入王城。")
        self.assertEqual(key_facts, "赵明拿到旧案钥匙。\n王城暗门开启。")
        self.assertEqual(linked, ["赵明", "迟到主角"])

    def test_split_chapter_summary_bundle_flattens_categorized_json_key_facts(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            '{"summary":"赵明进入王城。","关键事实":{"人物关系":["赵明信任迟到主角。","沈砚继续隐瞒身份。"],"物品":["虎符交给赵明。"],"伏笔":{"旧钟声":"旧钟声仍未解释。"}},"characters":[{"姓名":"赵明","身份":"主角"},{"姓名":"迟到主角","身份":"旧案证人"}]}'
        )

        self.assertEqual(summary, "赵明进入王城。")
        self.assertEqual(
            key_facts,
            "人物关系：赵明信任迟到主角。\n"
            "人物关系：沈砚继续隐瞒身份。\n"
            "物品：虎符交给赵明。\n"
            "伏笔：旧钟声仍未解释。",
        )
        self.assertNotIn("[", key_facts)
        self.assertEqual(linked, ["赵明", "迟到主角"])

    def test_split_chapter_summary_bundle_accepts_json_character_name_aliases(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            '{"summary":"赵明进入王城。","facts":["赵明拿到旧案钥匙。"],"characters":[{"姓名":"赵明","身份":"主角"},{"名字":"迟到主角","身份":"旧案证人"}]}'
        )

        self.assertEqual(summary, "赵明进入王城。")
        self.assertEqual(key_facts, "赵明拿到旧案钥匙。")
        self.assertEqual(linked, ["赵明", "迟到主角"])

    def test_split_chapter_summary_bundle_cleans_descriptive_character_names(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            "本章摘要：赵明进入王城。\n"
            "本章需继承的关键事实：赵明拿到旧案钥匙。\n"
            "本章关联人物：姓名：赵明（主角）、迟到主角（旧案证人）"
        )

        self.assertEqual(summary, "赵明进入王城。")
        self.assertEqual(key_facts, "赵明拿到旧案钥匙。")
        self.assertEqual(linked, ["赵明", "迟到主角"])

    def test_split_chapter_summary_bundle_splits_slash_linked_characters(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            "本章摘要：赵明进入王城。\n"
            "本章需继承的关键事实：赵明拿到旧案钥匙。\n"
            "本章关联人物：赵明/迟到主角｜沈砚"
        )

        self.assertEqual(summary, "赵明进入王城。")
        self.assertEqual(key_facts, "赵明拿到旧案钥匙。")
        self.assertEqual(linked, ["赵明", "迟到主角", "沈砚"])

    def test_split_chapter_summary_bundle_accepts_short_synonym_headings(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            "内容概述：赵明回到王城。\n"
            "继承事实：赵明拿到旧案钥匙。\n"
            "角色：赵明、迟到主角"
        )

        self.assertEqual(summary, "赵明回到王城。")
        self.assertEqual(key_facts, "赵明拿到旧案钥匙。")
        self.assertEqual(linked, ["赵明", "迟到主角"])

    def test_split_chapter_summary_bundle_accepts_bracketed_numbered_synonyms(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            "一、【内容摘要】赵明回到王城。\n"
            "二、连续性事实：赵明拿到旧案钥匙。\n"
            "三、相关角色：赵明、迟到主角"
        )

        self.assertEqual(summary, "赵明回到王城。")
        self.assertEqual(key_facts, "赵明拿到旧案钥匙。")
        self.assertEqual(linked, ["赵明", "迟到主角"])

    def test_split_chapter_summary_bundle_strips_colon_after_bracketed_heading(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            "【内容摘要】：赵明回到王城。\n"
            "【连续性事实】：赵明拿到旧案钥匙。\n"
            "【相关角色】：赵明、迟到主角"
        )

        self.assertEqual(summary, "赵明回到王城。")
        self.assertEqual(key_facts, "赵明拿到旧案钥匙。")
        self.assertEqual(linked, ["赵明", "迟到主角"])

    def test_split_chapter_summary_bundle_accepts_json_inheritance_and_roles(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        summary, key_facts, linked = tab._split_chapter_summary_bundle(
            '{"摘要":"赵明回到王城。","inheritance":["赵明拿到旧案钥匙。","王城暗门开启。"],"roles":["赵明","迟到主角"]}'
        )

        self.assertEqual(summary, "赵明回到王城。")
        self.assertEqual(key_facts, "赵明拿到旧案钥匙。\n王城暗门开启。")
        self.assertEqual(linked, ["赵明", "迟到主角"])

    def test_open_selected_current_project_does_not_reload_or_clear_editors(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._loading = False
        tab._opening_project = False
        tab.current_project_path = "/tmp/current.json"
        opened = []
        statuses = []
        tab.open_project_file = lambda path: opened.append(path)
        tab.set_status_tip = lambda text: statuses.append(text)

        tab._open_selected_project_item(_FakeListItem("/tmp/current.json"))

        self.assertEqual(opened, [])
        self.assertEqual(statuses, ["已打开：current.json"])

    def test_select_project_list_path_keeps_current_project_highlighted(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.project_list = _FakeListWidget([
            _FakeListItem("/tmp/first.json"),
            _FakeListItem("/tmp/current.json"),
        ])

        tab._select_project_list_path("/tmp/current.json")

        self.assertEqual(tab.project_list.current_row, 1)
        self.assertFalse(tab.project_list.signals_blocked)

    def test_refresh_current_project_list_item_from_memory_updates_current_row(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project_path = "/tmp/current.json"
        tab.current_project = {
            "meta": {"title": "当前项目"},
            "chapters": [
                {"title": "第一章", "text": "旧正文"},
                {"title": "第二章", "text": "新增正文内容"},
            ],
        }
        tab.project_list = _FakeListWidget([
            _FakeListItem("/tmp/first.json", "其他项目  ·  1字正文  ·  1章"),
            _FakeListItem("/tmp/current.json", "当前项目  ·  3字正文  ·  2章"),
        ])

        updated = tab._refresh_current_project_list_item_from_memory()

        self.assertTrue(updated)
        self.assertEqual(
            tab.project_list.item(1).text(),
            _project_list_text(tab.current_project, "current"),
        )
        self.assertEqual(tab.project_list.item(0).text(), "其他项目  ·  1字正文  ·  1章")

    def test_refresh_current_project_list_item_from_memory_skips_draft(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project_path = ""
        tab.current_project = {"meta": {"title": "自动草稿"}, "chapters": [{"text": "正文"}]}
        tab.project_list = _FakeListWidget([
            _FakeListItem("/tmp/current.json", "当前项目  ·  3字正文  ·  1章"),
        ])

        updated = tab._refresh_current_project_list_item_from_memory()

        self.assertFalse(updated)
        self.assertEqual(tab.project_list.item(0).text(), "当前项目  ·  3字正文  ·  1章")

    def test_mark_chapter_dirty_refreshes_current_project_list_row(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._loading = False
        tab._dirty = False
        tab._project_file_dirty = False
        tab._loading = False
        tab._dirty_generation = 0
        tab._last_failed_autosave_generation = -1
        tab._chapter_order_search_cache = "cached"
        tab.current_project_path = "/tmp/current.json"
        tab.current_project = {"meta": {"title": "当前项目"}, "chapters": [{"text": "旧正文"}]}
        tab.project_list = _FakeListWidget([
            _FakeListItem("/tmp/current.json", "当前项目  ·  3字正文  ·  1章"),
        ])
        scheduled = []
        autosave_only = []
        tab._save_chapter_from_editor = lambda: tab.current_project["chapters"][0].update({"text": "这是新的正文内容"})
        tab._schedule_refresh = lambda include_manuscript=False: scheduled.append(include_manuscript)
        tab._schedule_autosave_only = lambda: autosave_only.append(True)

        tab._mark_chapter_dirty()

        self.assertTrue(tab._dirty)
        self.assertTrue(tab._project_file_dirty)
        self.assertIsNone(tab._chapter_order_search_cache)
        self.assertEqual(scheduled, [])
        self.assertEqual(autosave_only, [True])
        self.assertTrue(tab._manuscript_stale)
        self.assertTrue(tab._writing_check_stale)
        self.assertEqual(
            tab.project_list.item(0).text(),
            _project_list_text(tab.current_project, "current"),
        )

    def test_deferred_refresh_after_chapter_edit_only_autosaves(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._loading = False
        tab._refresh_pending_count = 3
        tab._pending_manuscript_refresh = False
        tab._refresh_pending_helpers = False
        refreshed = []
        autosaved = []
        tab.refresh_manuscript = lambda: refreshed.append("manuscript")
        tab.refresh_writing_check = lambda: refreshed.append("check")
        tab.refresh_import_candidate_lists = lambda: refreshed.append("candidates")
        tab._autosave_draft = lambda: autosaved.append(True)

        tab._run_deferred_refresh()

        self.assertEqual(refreshed, [])
        self.assertEqual(autosaved, [True])
        self.assertEqual(tab._refresh_pending_count, 0)

    def test_stale_helper_pages_refresh_only_when_opened(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.page_indexes = {"书稿": 1, "检查": 2}
        tab._manuscript_stale = True
        tab._writing_check_stale = True
        refreshed = []
        tab.refresh_manuscript = lambda: refreshed.append("manuscript")
        tab.refresh_writing_check = lambda: refreshed.append("check")

        tab._refresh_visible_helper_page(0)
        self.assertEqual(refreshed, [])

        tab._refresh_visible_helper_page(1)
        tab._refresh_visible_helper_page(2)

        self.assertEqual(refreshed, ["manuscript", "check"])

    def test_import_script_text_defaults_to_new_project_mode(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        choices = []
        created = []
        appended = []

        def choose(title, _label, options, current_index=0):
            choices.append((title, list(options), current_index))
            if title == "选择导入类型":
                return "小说", True
            return options[current_index], True

        tab._get_combo_choice = choose
        tab._import_script_as_new_project = lambda *args: created.append(args)
        tab._import_script_append = lambda *args: appended.append(args)

        import gpt_desktop.novel_writing_tab as writing_tab
        original_question = writing_tab.QMessageBox.question
        try:
            writing_tab.QMessageBox.question = lambda *_args, **_kwargs: QMessageBox.Yes
            tab._import_script_text("第一章 开始\n正文内容", "/tmp/测试导入.txt", "TXT")
        finally:
            writing_tab.QMessageBox.question = original_question

        mode_choice = next(choice for choice in choices if choice[0] == "选择导入方式")
        self.assertEqual(mode_choice, ("选择导入方式", ["创建为新项目", "追加到当前项目"], 0))
        self.assertEqual(len(created), 1)
        self.assertEqual(appended, [])

    def test_import_script_text_uses_framework_import_type(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        calls = []

        def choose(title, _label, options, current_index=0):
            if title == "选择导入类型":
                self.assertEqual(options[current_index], FRAMEWORK_IMPORT_TYPE)
            return options[current_index], True

        tab._get_combo_choice = choose
        tab._import_framework_text = lambda *args: calls.append(args)
        tab._import_script_as_new_project = lambda *args: self.fail("框架导入不应走正文新项目导入")
        tab._import_script_append = lambda *args: self.fail("框架导入不应走正文追加导入")

        tab._import_script_text("主角：赵明\n主线：旧案复仇", "/tmp/框架.txt", "TXT")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "主角：赵明\n主线：旧案复仇")

    def test_framework_import_always_uses_ai_without_processing_choice(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        choices, started = [], []
        tab._get_combo_choice = lambda title, _label, options, current_index=0: (choices.append(title) or "追加到当前项目", True)
        provider = {"base_url": "http://example.test", "api_key": "key"}
        tab._current_novel_ai_selection = lambda: (provider, "model", "")
        tab._prepare_framework_import_project = lambda *_args: "框架"
        tab._start_framework_import_worker = lambda *args: started.append(args)
        tab._import_framework_text("主线：旧案复仇", "/tmp/框架.txt", "TXT")
        self.assertEqual(choices, ["选择导入方式"])
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][:3], (provider, "model", "主线：旧案复仇"))
        self.assertFalse(hasattr(NovelWritingTab, "_apply_direct_framework_import"))

    def test_framework_import_text_can_choose_ai_classification(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        started = []
        choices = []

        def choose(title, _label, options, current_index=0):
            choices.append(title)
            if title == "选择框架处理方式":
                return "AI 智能分类", True
            if title == "选择导入方式":
                return "创建为新项目", True
            return options[current_index], True

        provider = {"base_url": "http://example.test", "api_key": "key"}
        tab._get_combo_choice = choose
        tab._current_novel_ai_selection = lambda: (provider, "model", "")
        tab._prepare_framework_import_project = lambda text, path, source, mode: "框架"
        tab._apply_direct_framework_import = lambda *args: self.fail("AI 智能分类不应走直接导入")
        tab._start_framework_import_worker = lambda *args: started.append(args)

        tab._import_framework_text("主线：旧案复仇", "/tmp/框架.txt", "TXT")

        self.assertEqual(choices, ["选择导入方式"])
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][0], provider)
        self.assertEqual(started[0][1], "model")
        self.assertEqual(started[0][2], "主线：旧案复仇")
        self.assertEqual(started[0][3], "框架")

    def test_framework_import_clears_interrupted_chapter_plan_preview_and_checkpoint(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapter_plan_generation_state": {
                "status": "interrupted",
                "requested_chapter_count": 200,
                "chapters": [{"index": index} for index in range(1, 151)],
            }
        }
        tab.chapter_ai_preview = _FakePlainTextEdit(
            "正在自动分批生成章节规划\n已完成：150/200章"
        )
        tab.chapter_plan_apply_btn = _FakeButton()
        tab._pending_chapter_plan = {"chapters": [{"title": "旧规划"}]}
        tab.chapter_plan_worker = None
        tab._chapter_plan_sequence_token = 4
        tab._chapter_plan_auto_active = False
        tab._chapter_plan_continue_pending = False
        tab._chapter_ai_stop_requested_by_user = False
        tab._set_chapter_ai_actions_enabled = lambda _enabled: None
        tab._note_project_dirty = lambda: None
        tab._get_combo_choice = lambda title, _label, options, current_index=0: (
            ("追加到当前项目" if title == "选择导入方式" else "AI 智能分类"),
            True,
        )
        provider = {"base_url": "http://example.test", "api_key": "key"}
        tab._current_novel_ai_selection = lambda: (provider, "model", "")
        tab._prepare_framework_import_project = lambda *_args: "新框架"
        started = []
        tab._start_framework_import_worker = lambda *args: started.append(args)

        tab._import_framework_text("新框架正文", "/tmp/new-framework.txt", "TXT")

        self.assertEqual(tab.chapter_ai_preview.toPlainText(), "")
        self.assertNotIn("chapter_plan_generation_state", tab.current_project)
        self.assertEqual(tab._pending_chapter_plan, {})
        self.assertFalse(tab.chapter_plan_apply_btn.visible)
        self.assertEqual(tab._chapter_plan_sequence_token, 5)
        self.assertEqual(len(started), 1)

    def test_late_chapter_plan_callback_is_discarded_after_invalidation(self):
        class Worker:
            _chapter_plan_sequence_token = 3

        worker = Worker()
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.chapter_plan_worker = None
        tab._chapter_plan_sequence_token = 4
        tab._chapter_plan_auto_active = False
        events = []
        tab.sender = lambda: worker
        tab._log_novel_diagnostic = lambda event, **details: events.append((event, details))

        self.assertFalse(tab._chapter_plan_callback_is_current())
        self.assertEqual(events[0][0], "chapter_plan_stale_callback_discarded")

    def test_framework_import_retry_reuses_saved_source_in_current_project(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "meta": {"title": "已创建的框架项目"},
            "imported_framework_source": {
                "text": "主角：赵明\n主线：旧案复仇",
                "sha256": "a" * 64,
                "source_title": "原始框架",
                "source_label": "Word",
            },
        }
        tab.framework_import_worker = None
        provider = {"base_url": "http://example.test", "api_key": "key"}
        tab._current_novel_ai_selection = lambda: (provider, "model", "")
        tab._project_title = lambda: "已创建的框架项目"
        started = []
        tab._start_framework_import_worker = lambda *args: started.append(args)

        tab.retry_framework_import()

        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][0], provider)
        self.assertEqual(started[0][1], "model")
        self.assertEqual(started[0][2], "主角：赵明\n主线：旧案复仇")
        self.assertEqual(started[0][3], "原始框架")
        self.assertEqual(started[0][4], "Word")
        self.assertEqual(started[0][5], "追加到当前项目")

    def test_failed_framework_import_state_survives_reload_and_exposes_retry(self):
        project = _normalize_project({
            "imported_framework_source": {
                "text": "主线：旧案复仇",
                "sha256": hashlib.sha256("主线：旧案复仇".encode("utf-8")).hexdigest(),
            },
            "framework_import_state": {
                "status": "failed",
                "error": "AI 返回内容不是合法 JSON",
                "model": "model",
                "updated_at": "2026-07-31 02:52:36",
            },
        })
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = project
        tab.framework_import_worker = None
        tab.framework_import_retry_btn = _FakeButton()

        tab._refresh_framework_import_retry_action()

        self.assertTrue(tab.framework_import_retry_btn.visible)
        self.assertTrue(tab.framework_import_retry_btn.enabled)
        self.assertEqual(tab.framework_import_retry_btn.text, "重试框架 AI 分类")
        self.assertNotIn("framework_import_state", _project_without_private_notes(project))

    def test_completed_framework_import_hides_retry_action(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "imported_framework_source": {"text": "主线：已分类"},
            "framework_import_state": {"status": "complete"},
        }
        tab.framework_import_worker = None
        tab.framework_import_retry_btn = _FakeButton()

        tab._refresh_framework_import_retry_action()

        self.assertFalse(tab.framework_import_retry_btn.visible)

    def test_legacy_framework_source_does_not_offer_reclassification_after_chapter_planning(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "imported_framework_source": {"text": "主线：旧案复仇"},
            "chapters": [{"title": "开局", "outline": "主角收到旧案卷宗。"}],
        }
        tab.framework_import_worker = None
        tab.framework_import_retry_btn = _FakeButton()

        tab._refresh_framework_import_retry_action()

        self.assertFalse(tab.framework_import_retry_btn.visible)

    def test_legacy_framework_source_without_chapter_progress_offers_reclassification(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "imported_framework_source": {"text": "主线：旧案复仇"},
            "chapters": [],
        }
        tab.framework_import_worker = None
        tab.framework_import_retry_btn = _FakeButton()

        tab._refresh_framework_import_retry_action()

        self.assertTrue(tab.framework_import_retry_btn.visible)
        self.assertEqual(tab.framework_import_retry_btn.text, "重新进行框架 AI 分类")

    def test_explicit_framework_failure_still_offers_retry_after_existing_chapters(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "imported_framework_source": {"text": "新增框架资料"},
            "framework_import_state": {"status": "failed"},
            "chapters": [{"title": "已有章节"}],
        }
        tab.framework_import_worker = None
        tab.framework_import_retry_btn = _FakeButton()

        tab._refresh_framework_import_retry_action()

        self.assertTrue(tab.framework_import_retry_btn.visible)
        self.assertEqual(tab.framework_import_retry_btn.text, "重试框架 AI 分类")

    def test_ai_framework_assessment_invalidates_when_original_changes(self):
        tab = self._imported_planning_tab()
        self._mock_complete_framework_ai_analysis(tab)
        restored = _normalize_project(json.loads(json.dumps(tab.current_project, ensure_ascii=False)))
        self.assertEqual(restored["imported_framework_analysis"]["foundation_mode"], "reuse")
        tab.current_project["imported_framework_source"]["text"] += "\n故事结局修改。"
        self.assertEqual(tab._framework_ai_analysis(), {})
        normalized = _normalize_project(tab.current_project)
        self.assertNotIn("imported_framework_analysis", normalized)

    def test_apply_framework_import_result_writes_directly_to_project_sections(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "meta": {"title": "已有书名", "genre": "都市", "style": "", "pov": "第三人称", "status": "草稿"},
            "chapters": [],
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "bible": "",
            "world_rules": "",
            "timeline": "",
            "summary": "",
            "draft_note": "",
        }
        tab.current_project_path = ""
        tab.import_candidates = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
        tab.pending_analysis_chapter_ids = []
        tab.failed_analysis_chunks = []
        tab.current_character_index = -1
        tab.current_lore_index = -1
        tab.current_foreshadow_index = -1
        tab.current_chapter_index = -1
        tab._dirty = False
        tab._project_file_dirty = False
        tab._loading = False
        tab._dirty_generation = 0
        tab._last_failed_autosave_generation = -1
        tab._framework_import_context = {
            "source_title": "框架文件",
            "source_label": "Word",
            "import_mode": "追加到当前项目",
            "source_text": (
                "第一阶段：遗物苏醒\n"
                "章节：第1—2章\n"
                "1. 陈序收到第一件会复仇的遗物。\n"
                "2. 镜子留下真正凶手的第一条线索。"
            ),
        }
        tab.title_edit = _FakeLineEdit("已有书名")
        tab.genre_edit = _FakeLineEdit("都市")
        tab.style_edit = _FakeLineEdit("")
        tab.pov_combo = _FakeComboBox(["第三人称", "第一人称"], "第三人称")
        tab.target_words_edit = _FakeLineEdit("")
        tab.status_combo = _FakeComboBox(["草稿", "完结"], "草稿")
        tab.premise_edit = _FakePlainTextEdit("")
        tab.bible_edit = _FakePlainTextEdit("")
        tab.world_rules_edit = _FakePlainTextEdit("")
        tab.timeline_edit = _FakePlainTextEdit("")
        tab.summary_edit = _FakePlainTextEdit("")
        tab.draft_note_edit = _FakePlainTextEdit("")
        tab._save_character_from_editor = lambda: None
        tab._save_lore_from_editor = lambda: None
        tab._save_foreshadow_from_editor = lambda: None
        tab._save_chapter_from_editor = lambda: None
        tab._sync_candidate_analysis_state = lambda: None
        tab._sync_import_candidates_to_project = lambda: tab.current_project.pop("import_candidates", None)
        tab._reload_character_list = lambda *args, **kwargs: None
        tab._reload_lore_list = lambda *args, **kwargs: None
        tab._reload_foreshadow_list = lambda *args, **kwargs: None
        tab._reload_chapter_list = lambda *args, **kwargs: None
        tab.refresh_writing_check = lambda: None
        tab.refresh_manuscript = lambda: None
        tab._update_stats_label = lambda: None
        tab._save_after_import = lambda: "已保存。"

        result, meta_changed, plan_added, save_message = tab._apply_framework_import_result({
            "meta": {
                "title": "AI 书名",
                "genre": "悬疑",
                "style": "强节奏",
                "target_words": "200000",
                "premise": "遗物替主角复仇。",
            },
            "project_materials": {
                "bible": "主线是遗物复仇。",
                "world_rules": "遗物只在关键节点触发。",
                "timeline": "第一阶段：死亡真相浮出。",
                "summary": "框架聚焦复仇主线。",
            },
            "characters": [{"name": "陈序", "role": "主角", "goal": "追查真相", "notes": "冷静行动派"}],
            "lore": [{"name": "遗物规则", "type": "规则", "description": "遗物只能留下有限提示。"}],
            "foreshadows": [{"name": "死亡真相", "status": "未埋", "description": "最终揭示真正凶手。"}],
            "chapter_plan": {
                "source": "local_framework_parser",
                "summary": "前三章强钩子。",
                "stages": [
                    {
                        "id": "S01",
                        "name": "AI返回阶段：遗物苏醒",
                        "start_chapter": 1,
                        "end_chapter": 2,
                        "events": [
                            {"id": "S01-E01", "order": 1, "text": "陈序收到第一件会复仇的遗物。"},
                            {"id": "S01-E02", "order": 2, "text": "镜子留下真正凶手的第一条线索。"},
                        ],
                    }
                ],
                "chapters": [
                    {
                        "title": "遗物醒来",
                        "target_words": "3000",
                        "outline": "陈序收到第一件会复仇的遗物。",
                        "characters": ["陈序"],
                        "settings": ["遗物规则"],
                        "ending_hook": "镜子出现新字。",
                    }
                ],
            },
        })

        self.assertEqual(tab.current_project["meta"]["title"], "已有书名")
        self.assertEqual(tab.current_project["meta"]["genre"], "都市")
        self.assertEqual(tab.current_project["meta"]["style"], "强节奏")
        self.assertEqual(tab.current_project["meta"]["target_words"], "20万")
        self.assertEqual(tab.current_project["meta"]["premise"], "遗物替主角复仇。")
        self.assertIn("主线是遗物复仇", tab.current_project["bible"])
        self.assertNotIn("全书阶段规划 / 框架参考", tab.current_project["bible"])
        self.assertNotIn("第一阶段：死亡真相浮出", tab.current_project["bible"])
        self.assertNotIn("框架聚焦复仇主线", tab.current_project["bible"])
        self.assertNotIn("前三章强钩子", tab.current_project["bible"])
        self.assertEqual(tab.current_project["timeline"], "")
        self.assertEqual(tab.current_project["summary"], "")
        self.assertIn("遗物只在关键节点触发", tab.current_project["world_rules"])
        self.assertEqual(tab.current_project["characters"][0]["name"], "陈序")
        self.assertEqual(tab.current_project["lore"][0]["name"], "遗物规则")
        self.assertEqual(tab.current_project["foreshadow_items"][0]["name"], "死亡真相")
        self.assertEqual(tab.current_project["chapters"], [])
        reference = tab.current_project["imported_chapter_plan_reference"]
        self.assertIn("第一阶段：遗物苏醒", reference["summary"])
        self.assertIn("第一阶段：死亡真相浮出", reference["summary"])
        self.assertIn("框架聚焦复仇主线", reference["summary"])
        self.assertIn("前三章强钩子。", reference["summary"])
        self.assertEqual(len(reference["chapters"]), 1)
        self.assertEqual(reference["chapters"][0]["title"], "遗物醒来")
        self.assertIn("陈序收到第一件会复仇的遗物", reference["chapters"][0]["outline"])
        self.assertEqual(len(reference["stages"]), 1)
        self.assertEqual(reference["stages"][0]["name"], "第一阶段：遗物苏醒")
        self.assertEqual(reference["stages"][0]["events"], [])
        self.assertEqual(tab.import_candidates, {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}})
        self.assertNotIn("import_candidates", tab.current_project)
        self.assertGreaterEqual(meta_changed, 3)
        self.assertEqual(plan_added, 1)
        self.assertEqual(save_message, "已保存。")
        self.assertEqual(result["added"]["characters"], 1)

    def test_complete_imported_framework_writes_chapters_and_linked_characters_directly(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": []}

        count = tab._apply_complete_imported_chapter_plan(
            {
                "local_mapping_status": "mapped_by_ai",
                "chapters": [
                    {
                        "index": 1,
                        "title": "雨夜醒来",
                        "outline": "主角在雨夜醒来，发现门外有人等候。",
                        "narrative_stage": "第一阶段：开局",
                        "characters": ["主角", "林晚"],
                    },
                    {
                        "index": 2,
                        "title": "门外来客",
                        "outline": "林晚说明来意，主角决定跟她离开。",
                        "narrative_stage": "第一阶段：开局",
                        "characters": ["主角", "林晚"],
                    },
                ],
            },
            {
                "foundation_mode": "reuse",
                "chapter_outline_mode": "reuse",
                "chapter_outline_count": 2,
                "planning_parameters": {
                    "average_chapter_words": 2800,
                },
            },
        )

        self.assertEqual(count, 2)
        self.assertEqual(len(tab.current_project["chapters"]), 2)
        self.assertEqual(
            tab.current_project["chapters"][0]["linked_characters"],
            ["主角", "林晚"],
        )
        self.assertEqual(
            tab.current_project["chapters"][1]["source_stage"],
            "第一阶段：开局",
        )
        self.assertEqual(
            tab.current_project["chapters"][1]["draft_words"],
            "2800",
        )
        self.assertEqual(
            tab.current_project["chapters"][1]["outline"],
            "林晚说明来意，主角决定跟她离开。",
        )

    def test_imported_chapter_plan_reference_drops_generic_placeholder_title(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)

        reference = tab._normalize_imported_chapter_plan_reference({
            "summary": "开篇样章方向。",
            "chapters": [
                {"index": 1, "title": "章节 1", "outline": "不应作为正式章节。"},
                {"index": 2, "title": "正式开局", "outline": "这是明确章节。"},
            ],
        })

        self.assertEqual(len(reference["chapters"]), 1)
        self.assertEqual(reference["chapters"][0]["title"], "正式开局")

    def test_open_project_file_skips_opening_save_when_current_project_is_clean(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._opening_project = False
        tab.current_project_path = "/tmp/current.json"
        tab._dirty = False
        tab._project_file_dirty = False
        saves = []
        loaded = []
        draft_snapshots = []
        tab._save_current_work = lambda *args, **kwargs: saves.append((args, kwargs))
        tab._load_project_data = lambda data, path, defer_helpers=False: loaded.append((data, path, defer_helpers))
        tab._remember_project_path = lambda _path: None
        tab._save_draft_snapshot = lambda: draft_snapshots.append(True)
        tab._select_project_list_path = lambda _path: None
        tab._update_detached_auto_source_lock = lambda: None
        tab.set_status_tip = lambda _text: None

        import gpt_desktop.novel_writing_tab as writing_tab
        with patch.object(writing_tab, "load_json_file", return_value={"meta": {"title": "新项目"}}):
            tab.open_project_file("/tmp/new.json")

        self.assertEqual(saves, [])
        self.assertEqual(loaded, [({"meta": {"title": "新项目"}}, "/tmp/new.json", True)])
        self.assertEqual(draft_snapshots, [])
        self.assertFalse(tab._opening_project)

    def test_open_project_file_saves_when_project_file_is_dirty_after_draft_autosave(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._opening_project = False
        tab.current_project_path = "/tmp/current.json"
        tab._dirty = False
        tab._project_file_dirty = True
        saves = []
        draft_snapshots = []
        tab._save_current_work = lambda *args, **kwargs: saves.append((args, kwargs))
        tab._load_project_data = lambda data, path, defer_helpers=False: None
        tab._remember_project_path = lambda _path: None
        tab._save_draft_snapshot = lambda: draft_snapshots.append(True)
        tab._select_project_list_path = lambda _path: None
        tab._update_detached_auto_source_lock = lambda: None
        tab.set_status_tip = lambda _text: None

        import gpt_desktop.novel_writing_tab as writing_tab
        with patch.object(writing_tab, "load_json_file", return_value={"meta": {"title": "新项目"}}):
            tab.open_project_file("/tmp/new.json")

        self.assertEqual(len(saves), 1)
        args, kwargs = saves[0]
        self.assertEqual(args[0], "打开前保存")
        self.assertFalse(kwargs["refresh_project_list"])
        self.assertTrue(kwargs["preserve_project_mtime"])
        self.assertFalse(kwargs["update_draft"])
        self.assertEqual(draft_snapshots, [])

    def test_save_current_work_can_avoid_project_list_refresh_when_switching_projects(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"meta": {"title": "当前项目"}, "chapters": []}
        tab.current_project_path = "/tmp/current.json"
        tab._dirty = True
        tab._project_file_dirty = True
        tab._flush_current_editors = lambda: None
        tab._sync_candidate_analysis_state = lambda: None
        tab._sync_import_candidates_to_project = lambda: None
        tab._remember_project_path = lambda _path: None
        draft_snapshots = []
        tab._save_draft_snapshot = lambda: draft_snapshots.append(True)
        tab._update_stats_label = lambda: None
        refreshed = []
        tab._notify_project_store_changed = lambda: refreshed.append(True)

        import gpt_desktop.novel_writing_tab as writing_tab
        original_save = writing_tab.save_project_file
        calls = []
        try:
            writing_tab.save_project_file = lambda path, data, preserve_mtime=False: calls.append((path, preserve_mtime))

            tab._save_current_work(
                "打开前保存",
                refresh_project_list=False,
                preserve_project_mtime=True,
                update_draft=False,
            )
        finally:
            writing_tab.save_project_file = original_save

        self.assertEqual(calls, [("/tmp/current.json", True)])
        self.assertEqual(refreshed, [])
        self.assertEqual(draft_snapshots, [])
        self.assertFalse(tab._dirty)
        self.assertFalse(tab._project_file_dirty)

    def test_save_current_work_does_not_overwrite_project_updated_by_external_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_path = os.path.join(tmp, "project.json")
            backup_path = os.path.join(tmp, "external_update_backup.json")
            save_json_file(project_path, {
                "meta": {"title": "API压力测试"},
                "chapters": [],
            })
            os.utime(project_path, (1000, 1000))

            tab = NovelWritingTab.__new__(NovelWritingTab)
            tab.current_project = {
                "meta": {"title": "API压力测试"},
                "chapters": [],
            }
            tab.current_project_path = project_path
            tab._loaded_project_file_signature = tab._project_file_signature(project_path)
            tab._dirty = True
            tab._project_file_dirty = True
            tab._flush_current_editors = lambda: None
            tab._sync_candidate_analysis_state = lambda: None
            tab._sync_import_candidates_to_project = lambda: None
            tab._save_draft_snapshot = lambda: None
            tab._remember_project_path = lambda _path: None
            tab._notify_project_store_changed = lambda: None
            tab._update_stats_label = lambda: None
            tab.set_status_tip = lambda _text: None
            tab._log_novel_perf = lambda *args, **kwargs: None

            loaded = []
            def load_external(data, path, defer_helpers=False):
                loaded.append((data, path, defer_helpers))
                tab.current_project = data
                tab.current_project_path = path
                tab._record_current_project_file_signature(path)
            tab._load_project_data = load_external

            save_json_file(project_path, {
                "meta": {"title": "API压力测试"},
                "chapters": [{"title": "医圣渡劫", "outline": "完整提纲"}],
            })
            os.utime(project_path, (2000, 2000))

            import gpt_desktop.novel_writing_tab as writing_tab
            with patch.object(writing_tab, "unique_project_backup_path", return_value=backup_path):
                saved_path = tab._save_current_work("退出前保存", refresh_project_list=False)

            disk = load_json_file(project_path, {})
            backup = load_json_file(backup_path, {})
            self.assertEqual(saved_path, project_path)
            self.assertEqual(len(disk.get("chapters", [])), 1)
            self.assertEqual(disk["chapters"][0]["title"], "医圣渡劫")
            self.assertEqual(backup.get("chapters"), [])
            self.assertTrue(backup["meta"]["title"].endswith("_外部更新前备份"))
            self.assertEqual(len(loaded), 1)
            self.assertEqual(tab.current_project["chapters"][0]["title"], "医圣渡劫")
            self.assertFalse(tab._dirty)
            self.assertFalse(tab._project_file_dirty)

    def test_autosave_draft_clears_dirty_flag_after_success(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._loading = False
        tab._dirty = True
        tab._project_file_dirty = True
        tab._draft_saved_once = True
        tab.current_project = {"meta": {"title": "当前项目"}, "chapters": []}
        tab._flush_current_editors = lambda: None
        tab._sync_candidate_analysis_state = lambda: None
        tab._sync_import_candidates_to_project = lambda: None
        saves = []
        tab._save_draft_snapshot = lambda: saves.append(True)

        tab._autosave_draft()

        self.assertEqual(saves, [True])
        self.assertFalse(tab._dirty)
        self.assertTrue(tab._project_file_dirty)
        self.assertIn("updated_at", tab.current_project)

    def test_autosave_draft_does_not_retry_same_failed_generation(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._loading = False
        tab._dirty = True
        tab._project_file_dirty = True
        tab._draft_saved_once = True
        tab._dirty_generation = 4
        tab._last_failed_autosave_generation = -1
        tab._autosave_in_progress = False
        tab.current_project = {"meta": {"title": "当前项目"}, "chapters": []}
        tab._flush_current_editors = lambda: None
        tab._sync_candidate_analysis_state = lambda: None
        tab._sync_import_candidates_to_project = lambda: None
        attempts = []

        def fail_save():
            attempts.append(True)
            raise RuntimeError("save failed")

        tab._save_draft_snapshot = fail_save

        tab._autosave_draft()
        tab._autosave_draft()

        self.assertEqual(len(attempts), 1)
        self.assertTrue(tab._dirty)
        self.assertTrue(tab._project_file_dirty)
        self.assertEqual(tab._last_failed_autosave_generation, 4)

        tab._dirty_generation = 5
        tab._last_failed_autosave_generation = -1
        tab._autosave_draft()

        self.assertEqual(len(attempts), 2)

    def test_persist_candidate_analysis_draft_state_clears_dirty_after_success(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"meta": {"title": "当前项目"}, "chapters": []}
        tab._dirty = False
        tab._project_file_dirty = False
        tab._dirty_generation = 0
        tab._last_failed_autosave_generation = -1
        tab._sync_candidate_analysis_state = lambda: None
        tab._sync_import_candidates_to_project = lambda: None
        saves = []
        tab._save_draft_snapshot = lambda: saves.append(True)

        tab._persist_candidate_analysis_draft_state()

        self.assertEqual(saves, [True])
        self.assertFalse(tab._dirty)
        self.assertTrue(tab._project_file_dirty)
        self.assertEqual(tab._dirty_generation, 1)

    def test_infer_linked_character_names_uses_existing_character_cards(self):
        chapter = _new_chapter(0)
        chapter["text"] = "赵明推开暗门，迟到主角把旧卷递给他。"
        project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
                {"name": "迟到主角", "role": "证人", "goal": "", "secret": "", "voice": "", "notes": "别称：旧案证人"},
                {"name": "没有出场", "role": "路人", "goal": "", "secret": "", "voice": "", "notes": ""},
            ],
            "chapters": [chapter],
        }

        self.assertEqual(_infer_linked_character_names(project, chapter), ["赵明", "迟到主角"])

    def test_infer_linked_character_names_uses_extended_alias_labels(self):
        chapter = _new_chapter(0)
        chapter["text"] = "玄鸦把旧卷递给赵明，提醒他别信王城名册。"
        project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
                {"name": "迟到主角", "role": "旧案证人", "goal": "", "secret": "", "voice": "", "notes": "代号：玄鸦"},
            ],
            "chapters": [chapter],
        }

        self.assertEqual(_infer_linked_character_names(project, chapter), ["赵明", "迟到主角"])

    def test_infer_linked_character_names_uses_title_and_honorific_alias_labels(self):
        chapter = _new_chapter(0)
        chapter["text"] = "少主让阁主先生把旧卷交给赵明。"
        project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
                {
                    "name": "迟到主角",
                    "role": "旧案证人",
                    "goal": "",
                    "secret": "",
                    "voice": "",
                    "notes": "尊称：阁主先生\n头衔：少主",
                },
            ],
            "chapters": [chapter],
        }

        self.assertEqual(_infer_linked_character_names(project, chapter), ["赵明", "迟到主角"])

    def test_infer_linked_character_names_splits_slash_alias_values(self):
        chapter = _new_chapter(0)
        chapter["text"] = "阁主先生把旧卷交给赵明。"
        project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
                {
                    "name": "迟到主角",
                    "role": "旧案证人",
                    "goal": "",
                    "secret": "",
                    "voice": "",
                    "notes": "代号：玄鸦/阁主先生/少主",
                },
            ],
            "chapters": [chapter],
        }

        self.assertEqual(_infer_linked_character_names(project, chapter), ["赵明", "迟到主角"])

    def test_apply_chapter_plan_appends_planned_chapters(self):
        existing = _new_chapter(0)
        existing["title"] = "旧第一章"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [existing],
            "draft_note": "旧全局备注",
            "chapter_plan_generation_state": {"status": "complete"},
        }
        tab.current_project["imported_chapter_plan_reference"] = {
            "summary": "导入简纲参考。",
            "chapters": [{"index": "1", "title": "导入旧章", "outline": "旧简纲。"}],
        }
        tab.current_chapter_index = 0
        tab._pending_chapter_plan = {
            "summary": "第一卷先立住主线，前十章持续高能推进。",
            "chapters": [
                {
                    "title": "风雨入城",
                    "target_words": "3200",
                    "narrative_stage": "强钩子阶段",
                    "source_stage": "第1-10章：城市立足",
                    "dominant_line": "人物冲突",
                    "relationship_task": "建立临时信任",
                    "investigation_scope": "卷宗只带来一个新结果，不展开查案流程",
                    "chapter_function": "开局爆点",
                    "conflict_intensity": "高",
                    "setup_ratio": "低，只允许事件中带出",
                    "character_task": "快速建立陈景川行动风格",
                    "mainline_task": "进入京城主线冲突",
                    "foreshadow_task": "埋下风雨信号",
                    "outline": "本章目标：主角进入京城。",
                    "characters": ["陈景川"],
                    "settings": ["景辰总部"],
                    "foreshadows": ["F0001 风雨信号"],
                    "ending_hook": "旧案卷宗出现。",
                    "forbidden": "不要提前揭晓幕后人。",
                    "source_event_ids": ["S01-E01"],
                }
            ]
        }
        tab.chapter_plan_apply_btn = _FakeButton()
        tab.chapter_ai_preview = _FakePlainTextEdit("规划预览")
        tab.draft_note_edit = _FakePlainTextEdit("旧全局备注")
        selected = []
        scheduled = []
        statuses = []
        tab._flush_current_editors = lambda: None
        tab._reload_chapter_list = lambda index=None: selected.append(index)
        tab._schedule_refresh = lambda include_manuscript=False: scheduled.append(include_manuscript)
        tab.set_status_tip = statuses.append

        with patch("gpt_desktop.novel_writing_tab.QMessageBox.question", return_value=QMessageBox.Yes):
            tab.apply_chapter_plan()

        self.assertEqual(len(tab.current_project["chapters"]), 2)
        self.assertEqual(tab.current_project["chapters"][0]["title"], "旧第一章")
        appended = tab.current_project["chapters"][1]
        self.assertEqual(appended["title"], "风雨入城")
        self.assertEqual(appended["draft_words"], "3200")
        self.assertEqual(appended["linked_characters"], ["陈景川"])
        self.assertEqual(appended["source_event_ids"], ["S01-E01"])
        self.assertEqual(appended["outline"], "主角进入京城。")
        self.assertNotIn("所属阶段：", appended["outline"])
        self.assertNotIn("原框架阶段：", appended["outline"])
        for planning_label in (
            "涉及设定：", "禁止/边界：", "本章主导线：", "关系推进：",
            "调查范围：", "本章功能：", "冲突强度：", "铺垫比例：",
            "人物任务：", "主线任务：", "伏笔任务：", "本章目标：",
            "本章涉及设定：", "本章伏笔动作：", "结尾悬念：",
        ):
            self.assertNotIn(planning_label, appended["outline"])
        self.assertIn("旧全局备注", tab.current_project["draft_note"])
        self.assertIn("阶段规划摘要：", tab.current_project["draft_note"])
        self.assertIn("第一卷先立住主线", tab.current_project["draft_note"])
        self.assertEqual(tab.draft_note_edit.toPlainText(), tab.current_project["draft_note"])
        self.assertIn("imported_chapter_plan_reference", tab.current_project)
        self.assertEqual(
            tab.current_project["imported_chapter_plan_reference"]["summary"],
            "导入简纲参考。",
        )
        self.assertNotIn("chapter_plan_generation_state", tab.current_project)
        self.assertEqual(selected, [1])
        self.assertEqual(scheduled, [True])
        self.assertFalse(tab.chapter_plan_apply_btn.visible)
        self.assertEqual(tab.chapter_ai_preview.toPlainText(), "")
        self.assertTrue(statuses[-1].startswith("已追加 1 章章节规划"))

    def test_chapter_plan_direct_use_keeps_imported_outline_when_model_decides_use_imported(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "imported_chapter_plan_reference": {
                "chapters": [{
                    "index": 1,
                    "title": "灰烬醒来",
                    "outline": "母亲葬礼后的雨夜，林烬在旧宅醒来，听见妹妹咳嗽，带她去早餐店并当众压服闹事者，最后在雨幕外听见整齐脚步声。",
                }],
            },
        }
        model_result = {
            "index": 1,
            "title": "模型改写标题",
            "outline": "模型重新写了一版，不应覆盖用户原文。",
            "outline_mode": "use_imported",
        }

        merged = tab._chapter_plan_apply_imported_outline(
            model_result,
            tab.current_project["imported_chapter_plan_reference"]["chapters"][0],
        )

        self.assertEqual(merged["title"], "灰烬醒来")
        self.assertEqual(
            merged["outline"],
            "母亲葬礼后的雨夜，林烬在旧宅醒来，听见妹妹咳嗽，带她去早餐店并当众压服闹事者，最后在雨幕外听见整齐脚步声。",
        )
        self.assertEqual(merged["outline_source"], "imported_framework")

    def test_chapter_plan_generated_outline_is_kept_when_model_decides_generate(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        source = {"index": 1, "title": "框架标题", "outline": "用户原始细纲。"}
        model_result = {
            "index": 1,
            "title": "模型标题",
            "outline": "模型判断原文不足后生成的约300字提纲。",
            "outline_mode": "generate",
        }

        merged = tab._chapter_plan_apply_imported_outline(model_result, source)

        self.assertEqual(merged["title"], "框架标题")
        self.assertEqual(merged["outline"], "模型判断原文不足后生成的约300字提纲。")
        self.assertNotIn("outline_source", merged)

    def test_chapter_plan_direct_use_requires_nonempty_imported_outline(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        source = {"index": 1, "title": "只有标题", "outline": ""}
        model_result = {
            "index": 1,
            "title": "模型标题",
            "outline": "模型生成的完整章节提纲。",
            "outline_mode": "use_imported",
        }

        merged = tab._chapter_plan_apply_imported_outline(model_result, source)

        self.assertEqual(merged["title"], "只有标题")
        self.assertEqual(merged["outline"], "模型生成的完整章节提纲。")
        self.assertNotIn("outline_source", merged)

    def test_chapter_plan_missing_outline_mode_defaults_to_generated_result(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        source = {"index": 1, "title": "框架标题", "outline": "用户原始细纲。"}
        model_result = {
            "index": 1,
            "title": "模型标题",
            "outline": "模型生成的约300字提纲。",
        }

        merged = tab._chapter_plan_apply_imported_outline(model_result, source)

        self.assertEqual(merged["title"], "框架标题")
        self.assertEqual(merged["outline"], "模型生成的约300字提纲。")
        self.assertNotIn("outline_source", merged)

    def test_chapter_plan_context_uses_remaining_chapter_count(self):
        chapter = _new_chapter(0)
        chapter["title"] = "雨后收束"
        chapter["text"] = "开头内容。" + "正文推进。" * 500 + "雨后，众人离开总部。"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "meta": {"title": "测试小说", "target_words": "20"},
            "bible": "小说圣经",
            "world_rules": "世界规则",
            "timeline": "导入框架时间线锚点",
            "summary": "导入框架全局摘要锚点",
            "draft_note": "私有备注锚点：不能交给 AI。",
            "imported_chapter_plan_reference": {
                "summary": "导入原始章纲总览",
                "chapters": [
                    {
                        "index": "1",
                        "title": "导入第一章",
                        "outline": "主角拿到第一份遗物线索。",
                        "characters": ["陈序"],
                    }
                ],
            },
            "foreshadow_items": [
                {"code": "F0001", "name": "风雨信号", "status": "已埋", "description": "旧固定伏笔。"}
            ],
            "chapters": [chapter],
        }

        total_count, requested_count = tab._chapter_plan_counts(200000, 3000, 1)
        context = tab._chapter_plan_project_context(200000, 3000, total_count, requested_count)

        self.assertEqual(total_count, 67)
        self.assertEqual(requested_count, 66)
        self.assertIn('"existing_chapter_count": 1', context)
        self.assertIn('"requested_new_chapters": 66', context)
        self.assertIn('"planning_contract"', context)
        self.assertIn('"macro_pacing_rules"', context)
        self.assertIn("强钩子阶段", context)
        self.assertIn("主线扩展阶段", context)
        self.assertIn("收束升级阶段", context)
        self.assertIn("用户原始框架具体章段 > 全书分卷/阶段目标 > 通用宏观节奏", context)
        self.assertIn("主副叙事发动机", context)
        self.assertIn("按当前项目已经确认的题材与风格形成阅读感", context)
        self.assertIn("outline负责用当前小说自己的口吻讲述这一章", context)
        self.assertIn("不要像编辑解释本章功能", context)
        self.assertIn("宏观节奏不得覆盖原框架阶段", context)
        self.assertIn("imported_chapter_plan_reference", context)
        self.assertIn("导入原始章纲总览", context)
        self.assertIn("导入框架时间线锚点", context)
        self.assertIn("导入框架全局摘要锚点", context)
        self.assertIn("主角拿到第一份遗物线索", context)
        self.assertIn("伏笔由扩写正文时根据当时的开放伏笔动态调度", context)
        self.assertIn("雨后，众人离开总部。", context)
        self.assertIn("不要重写已有章节", context)
        self.assertIn("下一章必须从触发后的新反应、新结果或新阻力开始", context)
        self.assertIn("后章outline只需写触发后可能出现的新增变量", context)
        self.assertIn("风雨信号", context)
        self.assertIn("旧固定伏笔", context)
        self.assertNotIn("私有备注锚点", context)

    def test_chapter_plan_batch_context_keeps_ledger_and_only_last_five_detailed_outlines(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "meta": {"title": "压力测试", "target_words": "50"},
            "chapters": [],
            "characters": [],
            "lore": [],
        }
        generated = [
            {
                "index": index,
                "title": f"章节{index}",
                "narrative_stage": "主线扩展阶段",
                "chapter_function": f"功能{index}",
                "mainline_task": f"任务{index}",
                "outline": f"唯一详细提纲{index}",
                "ending_hook": f"钩子{index}",
            }
            for index in range(1, 9)
        ]
        state = {
            "target_words": 500000,
            "average_chapter_words": 2000,
            "total_chapter_count": 250,
            "existing_chapter_count": 0,
            "master_plan": {
                "summary": "全书总规划",
                "narrative_strategy_profile": {"planning_grammar": "固定流程模板"},
                "arcs": [{
                    "name": "第一阶段",
                    "start_chapter": 1,
                    "end_chapter": 250,
                    "dominant_line": "人物关系变化",
                    "relationship_goal": "建立信任",
                    "end_state": "双方形成合作",
                    "goal": "逐项完成任务",
                    "main_conflict": "旧任务型冲突",
                    "investigation_scope": "核验证据",
                    "forbidden": "禁止自由发挥",
                }],
            },
            "chapters": generated,
        }

        context = tab._chapter_plan_batch_context(state, 30)

        batch_payload = json.loads(context[context.find("{"):])
        self.assertEqual(
            batch_payload["batch_continuity"]["required_absolute_range"],
            [9, 38],
        )
        self.assertIn('"existing_chapter_count": 8', context)
        self.assertIn('"title": "章节1"', context)
        self.assertNotIn("唯一详细提纲3", context)
        self.assertIn("唯一详细提纲4", context)
        self.assertIn("唯一详细提纲8", context)
        self.assertIn("全书总规划", context)
        self.assertIn("下一批第一章必须从新反应、新结果或新阻力开始", context)
        compact_master = batch_payload["batch_continuity"]["master_plan"]
        self.assertNotIn("narrative_strategy_profile", compact_master)
        compact_arc = compact_master["arcs"][0]
        self.assertEqual(compact_arc["goal"], "逐项完成任务")
        self.assertEqual(compact_arc["main_conflict"], "旧任务型冲突")
        self.assertEqual(compact_arc["investigation_scope"], "核验证据")
        self.assertEqual(compact_arc["forbidden"], "禁止自由发挥")

    def test_chapter_plan_reference_keeps_250_items_and_filters_late_batch_range(self):
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
                        "text": f"FRAME_EVENT_{start + event_index - 1:04d}",
                    }
                    for event_index in range(1, 26)
                ],
            })
        tab.current_project = {
            "meta": {"title": "压力测试", "target_words": "50"},
            "chapters": [],
            "characters": [],
            "lore": [],
            "imported_chapter_plan_reference": {
                "summary": "十阶段完整骨架",
                "chapters": [
                    {
                        "index": index,
                        "title": f"明确标题{index}",
                        "outline": f"明确章节约束{index}",
                    }
                    for index in range(1, 11)
                ],
                "stages": stages,
            },
        }

        full_reference = tab._chapter_plan_reference_context()
        late_reference = tab._chapter_plan_reference_context(211, 240)
        context = tab._chapter_plan_project_context(
            500000,
            2000,
            250,
            30,
            existing_count_override=210,
            reference_start_index=211,
            reference_end_index=240,
        )

        self.assertEqual(len(full_reference["chapters"]), 10)
        self.assertEqual(len(full_reference["stages"]), 10)
        self.assertEqual(len(late_reference["stage_index"]), 10)
        self.assertNotIn("chapters", late_reference)
        self.assertEqual([item["id"] for item in late_reference["stages"]], ["S09", "S10"])
        self.assertEqual(sum(len(item["events"]) for item in late_reference["stages"]), 50)
        self.assertIn("FRAME_EVENT_0201", context)
        self.assertIn("FRAME_EVENT_0211", context)
        self.assertIn("FRAME_EVENT_0240", context)
        self.assertIn("FRAME_EVENT_0250", context)
        self.assertNotIn("FRAME_EVENT_0200", context)

    def test_chapter_plan_reference_does_not_parse_permanent_framework_source(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        dirty = []
        tab._note_project_dirty = lambda: dirty.append(True)
        tab.current_project = {
            "meta": {"title": "轻悬疑甜宠"},
            "chapters": [],
            "imported_chapter_plan_reference": {},
            "imported_framework_source": {
                "source_title": "原始框架",
                "source_label": "Word",
                "text": (
                    "第一卷：关系升温\n"
                    "第1—20章\n"
                    "1—10章：误会与靠近\n"
                    "两人因为误会保持距离。\n"
                    "两人在共同困境中靠近。\n"
                    "11—20章：轻悬疑反转\n"
                    "女主发现账目异常。\n"
                    "她用一次公开反击解决陷害。"
                ),
            },
        }

        context = tab._chapter_plan_reference_context(1, 10)

        self.assertEqual(tab.current_project["imported_chapter_plan_reference"], {})
        self.assertEqual(context, {})
        self.assertEqual(dirty, [])

    def test_chapter_plan_master_reference_rejects_merged_source_stages(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [],
            "imported_chapter_plan_reference": {
                "stages": [
                    {
                        "id": "S01",
                        "name": "第21-30章：感情推进",
                        "start_chapter": 21,
                        "end_chapter": 30,
                        "events": [{"id": "S01-E01", "order": 1, "text": "两人靠近。"}],
                    },
                    {
                        "id": "S02",
                        "name": "第31-40章：反派打脸",
                        "start_chapter": 31,
                        "end_chapter": 40,
                        "events": [{"id": "S02-E01", "order": 1, "text": "反派败退。"}],
                    },
                ],
            },
        }
        correct = {
            "existing_chapter_count": 0,
            "total_chapter_count": 40,
            "arcs": [
                {"start_chapter": 1, "end_chapter": 20},
                {"start_chapter": 21, "end_chapter": 30},
                {"start_chapter": 31, "end_chapter": 40},
            ],
        }
        merged = deepcopy(correct)
        merged["arcs"] = [
            {"start_chapter": 1, "end_chapter": 20},
            {"start_chapter": 21, "end_chapter": 40},
        ]

        self.assertEqual(tab._chapter_plan_master_reference_error(correct), "")
        self.assertIn("不能合并", tab._chapter_plan_master_reference_error(merged))
        self.assertEqual(
            tab._chapter_plan_source_stage_for_index(26)["name"],
            "第21-30章：感情推进",
        )

    def test_chapter_plan_event_assignment_allows_grouping_and_expansion_without_reuse(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "imported_chapter_plan_reference": {
                "stages": [{
                    "id": "S01",
                    "name": "开局",
                    "start_chapter": 1,
                    "end_chapter": 5,
                    "events": [
                        {"id": "S01-E01", "order": 1, "text": "主角苏醒。"},
                        {"id": "S01-E02", "order": 2, "text": "女主登场。"},
                        {"id": "S01-E03", "order": 3, "text": "首次救人。"},
                    ],
                }],
            },
        }
        chapters = [
            {
                "index": 1,
                "source_event_ids": ["S01-E01", "S01-E02"],
                "mainline_task": "主角苏醒。女主登场。",
                "outline": "主角苏醒。女主登场。",
            },
            {"index": 2, "source_event_ids": [], "mainline_task": "扩展冲突", "outline": "扩展冲突。"},
            {"index": 3, "source_event_ids": [], "mainline_task": "推进关系", "outline": "推进关系。"},
            {"index": 4, "source_event_ids": [], "mainline_task": "准备救人", "outline": "准备救人。"},
            {
                "index": 5,
                "source_event_ids": ["S01-E03"],
                "mainline_task": "首次救人。",
                "outline": "首次救人。",
            },
        ]

        self.assertEqual(tab._chapter_plan_event_assignment_error([], chapters), "")

        duplicate = deepcopy(chapters)
        duplicate[1]["source_event_ids"] = ["S01-E01"]
        duplicate[1]["outline"] = "主角苏醒。"
        self.assertIn("重复使用", tab._chapter_plan_event_assignment_error([], duplicate))

        missing = deepcopy(chapters)
        missing[-1]["source_event_ids"] = []
        self.assertIn("仍缺少1个", tab._chapter_plan_event_assignment_error([], missing))

        natural_rewrite = deepcopy(chapters)
        natural_rewrite[0]["mainline_task"] = "醒来后与女主发生第一次正面交锋。"
        natural_rewrite[0]["outline"] = "主角从昏迷中恢复，随即遇见女主。"
        self.assertEqual(tab._chapter_plan_event_assignment_error([], natural_rewrite), "")

    def test_chapter_plan_event_assignment_accepts_stage_event_id_aliases(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        stage = {
            "id": "S01",
            "name": "开局",
            "start_chapter": 1,
            "end_chapter": 3,
            "events": [
                {"id": "S01-E01", "order": 1, "text": "主角苏醒。"},
                {"id": "S01-E02", "order": 2, "text": "女主登场。"},
                {"id": "S01-E03", "order": 3, "text": "首次救人。"},
            ],
        }
        stage_chapters = [
            {"index": 1, "source_event_ids": ["STAGE_01-E01"]},
            {"index": 2, "source_event_ids": ["STAGE_01-E02"]},
            {"index": 3, "source_event_ids": ["STAGE_01-E03"]},
        ]

        tab.current_project = {"imported_chapter_plan_reference": {"stages": [stage]}}
        self.assertEqual(tab._chapter_plan_event_assignment_error([], stage_chapters), "")

        stage_alias_reference = deepcopy(stage)
        stage_alias_reference["events"] = [
            dict(event, id=f"STAGE_{event['id'][1:]}") for event in stage["events"]
        ]
        canonical_chapters = [
            {
                "index": chapter["index"],
                "source_event_ids": [chapter["source_event_ids"][0].replace("STAGE_", "S")],
            }
            for chapter in stage_chapters
        ]
        tab.current_project = {
            "imported_chapter_plan_reference": {"stages": [stage_alias_reference]}
        }
        self.assertEqual(
            tab._chapter_plan_event_assignment_error([], canonical_chapters),
            "",
        )

        compatibility_aliases = [
            "STAGE_1-E1",
            "STAGE_01-E01",
            "STAGE-1-E-1",
            "S1-E1",
            "S01_E01",
        ]
        for alias in compatibility_aliases:
            tab.current_project = {
                "imported_chapter_plan_reference": {"stages": [stage]}
            }
            self.assertEqual(
                tab._chapter_plan_event_assignment_error(
                    [],
                    [{"index": 1, "source_event_ids": [alias]}],
                ),
                "",
                alias,
            )

    def test_opening_event_mapping_does_not_repeat_events_already_grouped_into_first_ten_chapters(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        events = [
            {"id": f"S01-E{index:02d}", "order": index, "text": f"开局剧情节点{index}。"}
            for index in range(1, 26)
        ]
        tab.current_project = {
            "imported_chapter_plan_reference": {
                "stages": [{
                    "id": "S01",
                    "name": "医圣苏醒",
                    "start_chapter": 1,
                    "end_chapter": 25,
                    "events": events,
                }],
            },
        }
        groups = {
            1: [1],
            2: [2, 3, 4],
            3: [5, 6],
            4: [7, 8],
            5: [9, 10],
            6: [11, 12, 13],
            7: [14, 15],
            8: [16, 17],
            9: [18, 19, 20],
            10: [21, 22, 23, 24],
            25: [25],
        }
        chapters = []
        for chapter_index in range(1, 26):
            orders = groups.get(chapter_index, [])
            text = "".join(f"开局剧情节点{order}。" for order in orders) or f"扩展剧情{chapter_index}。"
            chapters.append({
                "index": chapter_index,
                "source_event_ids": [f"S01-E{order:02d}" for order in orders],
                "mainline_task": text,
                "outline": text,
            })

        self.assertEqual(tab._chapter_plan_event_assignment_error([], chapters), "")
        self.assertEqual(chapters[10]["source_event_ids"], [])

        repeated = deepcopy(chapters)
        repeated[10]["source_event_ids"] = ["S01-E11"]
        repeated[10]["outline"] = "开局剧情节点11。"
        self.assertIn("重复使用", tab._chapter_plan_event_assignment_error([], repeated))

    def test_chapter_plan_batches_merge_to_absolute_indexes_and_complete_once(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [],
            "chapter_plan_generation_state": {
                "version": 1,
                "status": "generating",
                "target_words": 70000,
                "average_chapter_words": 2000,
                "total_chapter_count": 35,
                "existing_chapter_count": 0,
                "requested_chapter_count": 35,
                "batch_size": 30,
                "master_plan": {"summary": "总规划", "arcs": []},
                "chapters": [],
            },
        }
        tab._chapter_plan_request_kind = "batch"
        tab._chapter_plan_continue_pending = False
        tab.chapter_plan_worker = object()
        tab._pending_chapter_plan = {}
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_plan_apply_btn = _FakeButton()
        tab.chapter_plan_apply_btn.setVisible(False)
        tab.set_status_tip = lambda _text: None
        tab._set_chapter_ai_actions_enabled = lambda _enabled: None
        tab._note_project_dirty = lambda: None

        first_batch = {
            "chapters": [
                {"index": index, "title": f"章节{index}", "outline": f"提纲{index}"}
                for index in range(1, 31)
            ]
        }
        tab.on_chapter_plan_ready(first_batch)

        state = tab.current_project["chapter_plan_generation_state"]
        self.assertEqual(len(state["chapters"]), 30)
        self.assertEqual(state["chapters"][0]["index"], 1)
        self.assertEqual(state["chapters"][-1]["index"], 30)
        self.assertTrue(tab._chapter_plan_continue_pending)
        self.assertFalse(tab.chapter_plan_apply_btn.visible)

        tab._chapter_plan_continue_pending = False
        second_batch = {
            "chapters": [
                {"index": index, "title": f"尾批{index}", "outline": f"尾批提纲{index}"}
                for index in range(1, 6)
            ]
        }
        tab.on_chapter_plan_ready(second_batch)

        state = tab.current_project["chapter_plan_generation_state"]
        self.assertEqual(state["status"], "complete")
        self.assertEqual(len(state["chapters"]), 35)
        self.assertEqual(state["chapters"][-1]["index"], 35)
        self.assertEqual(len(tab._pending_chapter_plan["chapters"]), 35)
        self.assertTrue(tab.chapter_plan_apply_btn.visible)

    def test_chapter_plan_250_chapter_pressure_simulation_merges_five_batches(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapters": [],
            "chapter_plan_generation_state": {
                "version": 1,
                "status": "generating",
                "target_words": 500000,
                "average_chapter_words": 2000,
                "total_chapter_count": 250,
                "existing_chapter_count": 0,
                "requested_chapter_count": 250,
                "master_plan": {"summary": "250章全书总规划", "arcs": []},
                "chapters": [],
            },
        }
        tab._chapter_plan_request_kind = "batch"
        tab._chapter_plan_continue_pending = False
        tab._pending_chapter_plan = {}
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_plan_apply_btn = _FakeButton()
        tab.chapter_plan_apply_btn.setVisible(False)
        tab.set_status_tip = lambda _text: None
        tab._set_chapter_ai_actions_enabled = lambda _enabled: None
        tab._note_project_dirty = lambda: None

        for batch_index, (_offset, count) in enumerate(tab._chapter_plan_batch_ranges(250), 1):
            tab._chapter_plan_continue_pending = False
            tab.on_chapter_plan_ready({
                "chapters": [
                    {
                        "index": relative_index,
                        "title": f"第{batch_index}批章节{relative_index}",
                        "outline": "本章推进主线并留下下一章承接点。",
                    }
                    for relative_index in range(1, count + 1)
                ]
            })

        state = tab.current_project["chapter_plan_generation_state"]
        self.assertEqual(state["status"], "complete")
        self.assertEqual(len(state["chapters"]), 250)
        self.assertEqual([item["index"] for item in state["chapters"]], list(range(1, 251)))
        self.assertEqual(len(tab._pending_chapter_plan["chapters"]), 250)
        self.assertTrue(tab.chapter_plan_apply_btn.visible)

    def test_stopping_between_chapter_plan_batches_cancels_scheduled_continuation(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "chapter_plan_generation_state": {
                "version": 1,
                "status": "generating",
                "requested_chapter_count": 250,
                "chapters": [{"index": index} for index in range(1, 31)],
            }
        }
        tab.writing_worker = None
        tab.chapter_plan_worker = None
        tab._chapter_plan_auto_active = True
        tab._chapter_plan_continue_pending = True
        tab._chapter_plan_sequence_token = 7
        tab._chapter_ai_transient_retry_pending = False
        tab._set_chapter_ai_actions_enabled = lambda _enabled: None
        tab._note_project_dirty = lambda: None
        statuses = []
        tab.set_status_tip = statuses.append

        tab.stop_chapter_ai_action()

        state = tab.current_project["chapter_plan_generation_state"]
        self.assertFalse(tab._chapter_plan_auto_active)
        self.assertFalse(tab._chapter_plan_continue_pending)
        self.assertEqual(tab._chapter_plan_sequence_token, 8)
        self.assertEqual(state["status"], "interrupted")
        self.assertIn("已保存当前批次进度", statuses[-1])

    def test_chapter_plan_requires_foundation_before_detailed_batch(self):
        class FakePlanWorker:
            instances = []

            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs
                self.progress = _FakeSignal()
                self.result_ready = _FakeSignal()
                self.failed = _FakeSignal()
                self.finished = _FakeSignal()
                self.started = False
                self.diagnostics = {}
                FakePlanWorker.instances.append(self)

            def _analysis_prompt(self):
                return "规划系统提示词"

            def start(self):
                self.started = True

        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "meta": {"title": "压力测试", "target_words": "50"},
            "chapters": [],
            "characters": [],
            "lore": [],
        }
        tab._chapter_plan_provider = {
            "base_url": "http://example.test",
            "api_key": "key",
            "proxy_url": "",
        }
        tab._chapter_plan_model = "model"
        tab._chapter_plan_auto_active = True
        tab._chapter_plan_sequence_token = 1
        tab._provider_proxy_mode = lambda _provider: "不使用代理"
        tab._set_chapter_ai_actions_enabled = lambda _enabled: None
        tab._note_project_dirty = lambda: None
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.set_status_tip = lambda _text: None
        diagnostic_events = []
        tab._log_novel_diagnostic = lambda event, **details: diagnostic_events.append(
            (event, details)
        )
        base_state = {
            "version": 1,
            "status": "pending",
            "target_words": 500000,
            "average_chapter_words": 2000,
            "total_chapter_count": 250,
            "existing_chapter_count": 0,
            "requested_chapter_count": 250,
            "master_plan": {},
            "chapters": [],
        }

        tab._start_chapter_plan_worker_for_state(deepcopy(base_state))

        self.assertEqual(tab._chapter_plan_request_kind, "")
        self.assertFalse(tab._chapter_plan_auto_active)
        self.assertEqual(
            tab.current_project["chapter_plan_generation_state"]["status"],
            "failed",
        )
        self.assertEqual(diagnostic_events, [])

        batch_state = deepcopy(base_state)
        batch_state["master_plan"] = {
            "summary": "全书总规划",
            "arcs": [],
            "narrative_strategy_profile": {"primary_story_engine": "成长与公开结果"},
        }
        batch_state["profile_confirmed"] = True
        batch_state["chapters"] = [
            {"index": index, "title": f"章节{index}", "outline": f"提纲{index}"}
            for index in range(1, 51)
        ]
        tab._chapter_plan_auto_active = True
        with patch("gpt_desktop.novel_writing_tab.NovelChapterPlanWorker", FakePlanWorker):
            tab._start_chapter_plan_worker_for_state(batch_state)

        worker = FakePlanWorker.instances[-1]
        self.assertEqual(tab._chapter_plan_request_kind, "batch")
        self.assertEqual(worker.args[6], 50)
        self.assertEqual(worker.args[8], 50)
        self.assertEqual(worker.kwargs["batch_number"], 2)
        self.assertEqual(worker.kwargs["total_batches"], 5)
        batch_event = diagnostic_events[-1]
        self.assertEqual(batch_event[0], "chapter_plan_request_started")
        self.assertEqual(batch_event[1]["request_kind"], "batch")
        self.assertEqual(batch_event[1]["batch_number"], 2)
        self.assertEqual(batch_event[1]["absolute_start"], 51)
        self.assertEqual(batch_event[1]["absolute_end"], 100)

    def test_short_chapter_plan_without_foundation_stops_without_api_call(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"meta": {}, "chapters": [], "characters": [], "lore": []}
        tab._chapter_plan_provider = {
            "base_url": "http://example.test",
            "api_key": "key",
            "proxy_url": "",
        }
        tab._chapter_plan_model = "model"
        tab._chapter_plan_auto_active = True
        tab._provider_proxy_mode = lambda _provider: "不使用代理"
        tab._set_chapter_ai_actions_enabled = lambda _enabled: None
        tab._persist_chapter_plan_generation_state = lambda state: tab.current_project.__setitem__(
            "chapter_plan_generation_state", deepcopy(state)
        )
        tab._show_chapter_plan_generation_progress = lambda _state, _message="": None
        tab.set_status_tip = lambda _text: None
        state = {
            "version": 3,
            "status": "pending",
            "target_words": 40000,
            "average_chapter_words": 2000,
            "total_chapter_count": 20,
            "existing_chapter_count": 0,
            "requested_chapter_count": 20,
            "master_plan": {},
            "chapters": [],
            "profile_confirmed": False,
        }

        with patch("gpt_desktop.novel_writing_tab.NovelChapterPlanWorker") as batch:
            tab._start_chapter_plan_worker_for_state(state)

        batch.assert_not_called()
        self.assertEqual(tab._chapter_plan_request_kind, "")
        self.assertFalse(tab._chapter_plan_auto_active)
        self.assertEqual(
            tab.current_project["chapter_plan_generation_state"]["status"],
            "failed",
        )

    def test_quick_foundation_review_keeps_hidden_strategy_details(self):
        dialog = ChapterPlanFoundationDialog.__new__(ChapterPlanFoundationDialog)
        dialog._plan = {
            "summary": "原始故事简介",
            "core_mainline": "原始主线",
            "ending_promise": "原始结局",
            "global_hard_boundaries": "不得扩大办案流程。",
            "narrative_strategy_profile": {
                "genre_world": "古言穿越",
                "primary_story_engine": "关系与身份变化",
                "planning_grammar": "人物选择推动后果",
                "satisfaction_currencies": ["身份翻盘", "关系确认"],
                "chapter_variation_pool": ["日常", "冲突", "关系"],
            },
            "arcs": [{"name": "开局", "start_chapter": 1, "end_chapter": 20}],
        }
        dialog._arcs = [{"name": "开局", "start_chapter": 1, "end_chapter": 20}]

        plan = dialog.foundation()

        self.assertEqual(plan["summary"], "原始故事简介")
        self.assertEqual(plan["narrative_strategy_profile"]["planning_grammar"], "人物选择推动后果")
        self.assertEqual(
            plan["narrative_strategy_profile"]["satisfaction_currencies"],
            ["身份翻盘", "关系确认"],
        )
        self.assertEqual(
            plan["narrative_strategy_profile"]["chapter_variation_pool"],
            ["日常", "冲突", "关系"],
        )

    def test_master_confirmation_starts_batch_when_worker_was_cleaned_during_dialog(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        state = {
            "version": 3,
            "status": "generating",
            "target_words": 200000,
            "average_chapter_words": 5000,
            "total_chapter_count": 40,
            "existing_chapter_count": 0,
            "requested_chapter_count": 40,
            "master_plan": {
                "summary": "全书规划",
                "arcs": [{"start_chapter": 1, "end_chapter": 40}],
                "narrative_strategy_profile": {"primary_story_engine": "人物成长"},
            },
            "chapters": [],
            "profile_confirmed": True,
        }
        tab.current_project = {"chapters": [], "chapter_plan_generation_state": deepcopy(state)}
        tab.chapter_plan_worker = None
        tab._chapter_plan_auto_active = True
        tab._chapter_plan_continue_pending = False
        tab._chapter_plan_sequence_token = 7
        tab._log_novel_diagnostic = lambda *_args, **_kwargs: None
        starts = []
        tab._start_chapter_plan_worker_for_state = lambda value: starts.append(deepcopy(value))

        with patch("gpt_desktop.novel_writing_tab.QTimer.singleShot") as single_shot:
            tab._queue_chapter_plan_continuation()

        self.assertFalse(tab._chapter_plan_continue_pending)
        single_shot.assert_called_once()
        delay, callback = single_shot.call_args.args
        self.assertEqual(delay, 100)
        callback()
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["requested_chapter_count"], 40)
        self.assertTrue(starts[0]["profile_confirmed"])

    def test_cancelling_profile_confirmation_pauses_without_generating_chapters(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        state = {
            "version": 3,
            "status": "awaiting_profile_confirmation",
            "target_words": 40000,
            "average_chapter_words": 2000,
            "total_chapter_count": 20,
            "existing_chapter_count": 0,
            "requested_chapter_count": 20,
            "master_plan": {
                "summary": "全书规划",
                "arcs": [{"start_chapter": 1, "end_chapter": 20}],
                "narrative_strategy_profile": {"primary_story_engine": "关系选择"},
            },
            "chapters": [],
            "profile_confirmed": False,
        }
        tab.current_project = {"chapters": [], "chapter_plan_generation_state": deepcopy(state)}
        tab._chapter_plan_auto_active = True
        tab._chapter_plan_continue_pending = False
        tab._edit_chapter_plan_foundation = lambda master_plan, _state: (
            "cancelled", deepcopy(master_plan)
        )
        tab._persist_chapter_plan_generation_state = lambda value: tab.current_project.__setitem__(
            "chapter_plan_generation_state", deepcopy(value)
        )
        tab._show_chapter_plan_generation_progress = lambda _state, _message="": None
        tab.set_status_tip = lambda _text: None

        confirmed = tab._confirm_chapter_plan_strategy_profile(state)

        saved = tab.current_project["chapter_plan_generation_state"]
        self.assertFalse(confirmed)
        self.assertFalse(tab._chapter_plan_auto_active)
        self.assertFalse(tab._chapter_plan_continue_pending)
        self.assertEqual(saved["status"], "awaiting_profile_confirmation")
        self.assertEqual(saved["chapters"], [])
        self.assertEqual(tab.current_project["narrative_strategy_confirmation"]["status"], "pending")

    def test_detailed_batch_cannot_overwrite_confirmed_strategy_profile(self):
        confirmed_profile = {
            "audience_direction": "男频",
            "primary_story_engine": "能力成长与公开结果",
        }
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "narrative_strategy_profile": deepcopy(confirmed_profile),
            "chapters": [],
            "chapter_plan_generation_state": {
                "version": 3,
                "status": "generating",
                "target_words": 2000,
                "average_chapter_words": 2000,
                "total_chapter_count": 1,
                "existing_chapter_count": 0,
                "requested_chapter_count": 1,
                "master_plan": {
                    "summary": "总规划",
                    "narrative_strategy_profile": deepcopy(confirmed_profile),
                },
                "chapters": [],
                "profile_confirmed": True,
            },
        }
        tab._chapter_plan_request_kind = "batch"
        tab._chapter_plan_auto_active = True
        tab._chapter_plan_continue_pending = False
        tab._pending_chapter_plan = {}
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_plan_apply_btn = _FakeButton()
        tab._chapter_plan_event_reference = lambda: ({}, [], {})
        tab._chapter_plan_source_stage_for_index = lambda _index: {}
        tab._chapter_plan_event_assignment_error = lambda _generated, _incoming: ""
        tab._persist_chapter_plan_generation_state = lambda state: tab.current_project.__setitem__(
            "chapter_plan_generation_state", deepcopy(state)
        )
        tab.set_status_tip = lambda _text: None

        tab.on_chapter_plan_ready({
            "narrative_strategy_profile": {
                "audience_direction": "女频",
                "primary_story_engine": "错误覆盖值",
            },
            "chapters": [{"index": 1, "title": "开局", "outline": "主角完成第一次选择。"}],
        })

        self.assertEqual(tab.current_project["narrative_strategy_profile"], confirmed_profile)
        self.assertEqual(
            tab.current_project["chapter_plan_generation_state"]["narrative_strategy_profile"]["primary_story_engine"],
            "能力成长与公开结果",
        )

    def test_foundation_validation_requires_contiguous_full_book_stage_coverage(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab._chapter_plan_master_reference_error = lambda _plan: ""
        plan = {
            "summary": "故事简介",
            "existing_chapter_count": 0,
            "total_chapter_count": 100,
            "narrative_strategy_profile": {"primary_story_engine": "人物成长"},
            "arcs": [
                {"name": "开局", "start_chapter": 1, "end_chapter": 25},
                {"name": "发展", "start_chapter": 26, "end_chapter": 70},
                {"name": "收束", "start_chapter": 71, "end_chapter": 100},
            ],
        }

        self.assertEqual(tab._validate_chapter_plan_foundation(plan), "")
        broken = deepcopy(plan)
        broken["arcs"][1]["start_chapter"] = 27
        self.assertIn("应从第26章开始", tab._validate_chapter_plan_foundation(broken))
        truncated = deepcopy(plan)
        truncated["arcs"][-1]["end_chapter"] = 99
        self.assertIn("覆盖到第100章", tab._validate_chapter_plan_foundation(truncated))

class _FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class _FakePlainTextEdit:
    def __init__(self, text=""):
        self._text = text
        self._blocked = False

    def toPlainText(self):
        return self._text

    def setPlainText(self, text):
        self._text = text

    def clear(self):
        self._text = ""

    def blockSignals(self, blocked):
        self._blocked = bool(blocked)


class _FakeLineEdit:
    def __init__(self, text=""):
        self._text = text
        self._blocked = False

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text

    def blockSignals(self, blocked):
        self._blocked = bool(blocked)


class _FakeButton:
    def __init__(self):
        self.text = ""
        self.tooltip = ""
        self.enabled = True
        self.visible = True

    def setText(self, text):
        self.text = text

    def setToolTip(self, text):
        self.tooltip = text

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setVisible(self, visible):
        self.visible = bool(visible)


class _FakeComboBox:
    def __init__(self, items, current):
        self._items = [(item, item) for item in items]
        self._current = current
        self._blocked = False
        self.enabled = True

    def currentText(self):
        if 0 <= self._current_index() < len(self._items):
            return self._items[self._current_index()][0]
        return self._current

    def currentData(self):
        if 0 <= self._current_index() < len(self._items):
            return self._items[self._current_index()][1]
        return self._current

    def _current_index(self):
        for index, (_text, data) in enumerate(self._items):
            if data == self._current or _text == self._current:
                return index
        return -1

    def addItem(self, text, data=None):
        self._items.append((text, text if data is None else data))

    def clear(self):
        self._items.clear()
        self._current = ""

    def findText(self, text):
        try:
            return [item[0] for item in self._items].index(text)
        except ValueError:
            return -1

    def findData(self, data):
        for index, (_text, item_data) in enumerate(self._items):
            if item_data == data:
                return index
        return -1

    def setCurrentIndex(self, index):
        if 0 <= index < len(self._items):
            self._current = self._items[index][1]

    def blockSignals(self, blocked):
        self._blocked = bool(blocked)

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


class _FakeTimer:
    def start(self):
        pass


class _FakeLabel:
    def __init__(self):
        self.text = ""
        self.tooltip = ""

    def setText(self, text):
        self.text = text

    def setToolTip(self, text):
        self.tooltip = text


class _FakeListItem:
    def __init__(self, path, text=""):
        self._path = path
        self._text = text
        self._tooltip = ""

    def data(self, _role):
        return self._path

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text

    def setToolTip(self, text):
        self._tooltip = text


class _FakeListWidget:
    def __init__(self, items):
        self._items = list(items)
        self.current_row = -1
        self.signals_blocked = False

    def blockSignals(self, blocked):
        self.signals_blocked = bool(blocked)

    def count(self):
        return len(self._items)

    def item(self, row):
        return self._items[row]

    def setCurrentRow(self, row):
        self.current_row = row


if __name__ == "__main__":
    unittest.main()
