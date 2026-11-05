import os
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import gpt_desktop.novel_creation_wizard as wizard
from gpt_desktop.novel_utils import _normalize_mainline_pressure_curve


class NovelCreationWizardPersistenceTests(unittest.TestCase):
    def test_length_choices_are_grouped_into_short_and_long_options(self):
        self.assertEqual(
            wizard.CREATION_CHOICE_GROUPS["length"],
            {
                "短篇": ("1万字", "3万字", "5万字", "10万字"),
                "长篇": ("15万字", "30万字", "50万字", "100万字+"),
            },
        )

        dialog = wizard.NovelCreationWizardDialog.__new__(
            wizard.NovelCreationWizardDialog
        )
        dialog.choice_values = {}
        dialog._save_draft = lambda: None
        values = {}
        dialog.target_words_spin = SimpleNamespace(
            setValue=lambda value: values.__setitem__("target_words", value),
        )
        for label, expected in (
            ("1万字", 10000),
            ("3万字", 30000),
            ("5万字", 50000),
            ("10万字", 100000),
            ("15万字", 150000),
            ("30万字", 300000),
            ("50万字", 500000),
            ("100万字+", 1000000),
        ):
            dialog.choice_values["length"] = label
            dialog._on_choice_changed("length")
            self.assertEqual(values["target_words"], expected)

    @staticmethod
    def _choice_dialog():
        dialog = wizard.NovelCreationWizardDialog.__new__(
            wizard.NovelCreationWizardDialog
        )
        dialog.choice_values = {}
        dialog.choice_display_values = {}
        dialog.choice_summary_buttons = {}
        dialog.choice_arrow_buttons = {}
        dialog.premise_candidates = []
        dialog._save_draft = lambda: None
        return dialog

    def test_gender_choice_groups_keep_the_requested_order_and_separation(self):
        self.assertEqual(
            wizard.CREATION_CHOICE_GROUPS["audience"]["读者方向"],
            ("男频", "女频"),
        )
        male = wizard.CREATION_GENDER_CHOICE_GROUPS["男频"]
        female = wizard.CREATION_GENDER_CHOICE_GROUPS["女频"]
        self.assertEqual(
            male["genre"]["主分类"][:4],
            ("西方奇幻", "东方仙侠", "科幻末世", "男频衍生"),
        )
        self.assertEqual(
            male["genre"]["主分类"][-4:],
            ("动漫衍生", "游戏体育", "传统玄幻", "都市修真"),
        )
        self.assertEqual(
            female["genre"]["主分类"][:4],
            ("女频悬疑", "古风世情", "科幻末世", "女频衍生"),
        )
        self.assertEqual(female["genre"]["主分类"][-3:], ("年代", "种田", "快穿"))
        self.assertEqual(male["theme"]["主题"][0], "衍生")
        self.assertEqual(female["theme"]["主题"][0], "古言权谋")
        self.assertEqual(male["role"]["角色"][0], "多女主")
        self.assertEqual(female["role"]["角色"][0], "位尊权重")
        self.assertEqual(male["plot"]["情节"][0], "都市江湖")
        self.assertEqual(female["plot"]["情节"][0], "男二上位")

    def test_choice_groups_switch_with_reader_direction(self):
        dialog = self._choice_dialog()
        dialog.choice_values["audience"] = "男频"
        self.assertEqual(
            dialog._choice_groups("genre")["主分类"][0],
            "西方奇幻",
        )
        self.assertEqual(
            dialog._choice_groups("role")["角色"][0],
            "多女主",
        )

        dialog.choice_values["audience"] = "女频"
        self.assertEqual(
            dialog._choice_groups("genre")["主分类"][0],
            "女频悬疑",
        )
        self.assertEqual(
            dialog._choice_groups("plot")["情节"][0],
            "男二上位",
        )
        self.assertNotIn("男频衍生", dialog._choice_options("genre"))
        self.assertNotIn("多女主", dialog._choice_options("role"))

    def test_switching_reader_direction_drops_invalid_selected_categories(self):
        dialog = self._choice_dialog()
        dialog.choice_values.update({
            "audience": "男频",
            "genre": "都市脑洞",
            "theme": "衍生、开局",
            "role": "多女主、天才",
            "plot": "废土、末世",
        })
        dialog.choice_values["audience"] = "女频"
        dialog._on_choice_changed("audience")

        self.assertNotIn("genre", dialog.choice_values)
        self.assertEqual(dialog.choice_values["theme"], "衍生")
        self.assertEqual(dialog.choice_values["role"], "天才")
        self.assertEqual(dialog.choice_values["plot"], "末世")

    def test_theme_role_and_plot_are_limited_to_two_choices(self):
        dialog = self._choice_dialog()
        for key in ("theme", "role", "plot"):
            dialog._set_choice(key, "甲、乙、丙")
            self.assertEqual(dialog.choice_values[key], "甲、乙")
            self.assertEqual(dialog.choice_display_values[key], "甲、乙")

    def test_role_and_plot_are_passed_to_ai_and_saved_in_selected_premise(self):
        dialog = self._choice_dialog()
        dialog.choice_values.update({
            "audience": "女频",
            "genre": "古言脑洞",
            "theme": "古代、悬疑",
            "role": "公主、腹黑",
            "plot": "追夫、破镜重圆",
            "style": "细腻情感",
            "protagonist_route": "身份反转",
        })
        dialog.inspiration_edit = SimpleNamespace(text=lambda: "故事灵感")
        dialog.project_name_hint = ""
        dialog.premise_candidates = []
        dialog.target_words_spin = SimpleNamespace(value=lambda: 500000)
        dialog.average_words_spin = SimpleNamespace(value=lambda: 3000)
        dialog._selected_custom_protagonist_style = lambda: {}

        with patch.object(wizard, "_creation_name_references", return_value={}):
            context = dialog._context_for_step("premise")
        self.assertEqual(context["author_input"]["role"], "公主、腹黑")
        self.assertEqual(context["author_input"]["plot"], "追夫、破镜重圆")

        dialog.current_step_index = 0
        dialog.premise_candidates = [{"title": "标题", "synopsis": "简介"}]
        dialog.premise_selected_index = 0
        dialog.step_results = {}
        dialog._read_current_step()
        selected = dialog.step_results["premise"]["selected"]
        self.assertEqual(selected["audience"], "女频")
        self.assertEqual(selected["role"], "公主、腹黑")
        self.assertEqual(selected["plot"], "追夫、破镜重圆")

    @staticmethod
    def _scale_sized_assets(stage_counts):
        characters = [{"name": f"人物{i}"} for i in range(25)]
        lore = [{"name": f"设定{i}"} for i in range(25)]
        foreshadows = []
        for stage_number, count in enumerate(stage_counts, 1):
            for item_number in range(count):
                foreshadows.append({
                    "code": f"F{stage_number}{item_number}",
                    "name": f"伏笔{stage_number}-{item_number}",
                    "setup_stage": f"第{stage_number}阶段",
                    "payoff_stage": f"第{stage_number}阶段",
                })
        return {
            "characters": characters,
            "lore": lore,
            "foreshadows": foreshadows,
        }

    def test_creation_scale_does_not_hard_require_foreshadows_per_stage(self):
        _size_label, ranges = wizard._creation_scale_requirements(500000)
        self.assertEqual(ranges["characters"], (25, 25))
        self.assertEqual(ranges["lore"], (25, 25))
        self.assertEqual(ranges["foreshadows"], (0, 0))

        assets = self._scale_sized_assets([1, 0, 2, 0, 1])
        self.assertEqual(
            wizard._creation_scale_shortfalls(assets, 500000),
            [],
        )

    def test_creation_scale_ignores_foreshadow_count_shortfall(self):
        assets = self._scale_sized_assets([2, 4, 3, 3, 3])
        shortfalls = wizard._creation_scale_shortfalls(assets, 500000)
        self.assertEqual(shortfalls, [])

    def test_bible_confirmation_does_not_use_stage_foreshadow_minimum(self):
        dialog = wizard.NovelCreationWizardDialog.__new__(
            wizard.NovelCreationWizardDialog
        )
        dialog.target_words_spin = SimpleNamespace(value=lambda: 500000)
        dialog._normalize_step_result = lambda step, payload: payload
        result = {
            "bible": {"core": "核心冲突"},
            "world_rules": {"rules": ["规则"]},
            **self._scale_sized_assets([2, 4, 3, 3, 3]),
        }

        error = dialog._bible_validation_error(result)

        self.assertEqual(error, "")

    def test_creation_scale_guidance_uses_positive_foreshadow_prompt(self):
        guidance = wizard._creation_scale_guidance(500000)
        self.assertIn("伏笔数量只是建议参考，不是硬性配额", guidance)
        self.assertIn("质量优先、数量不够时不硬凑", guidance)
        self.assertNotIn("每个阶段至少准备5条", guidance)

    def test_foreshadow_distribution_guidance_prioritizes_quality(self):
        guidance = wizard._creation_foreshadow_distribution_guidance(300000)
        self.assertIn("不要求每个阶段必须有固定数量", guidance)
        self.assertIn("质量优先，数量不足不补造宽泛线索", guidance)
        self.assertIn("大多数应是普通可回收闭环", guidance)

    def test_foreshadow_closure_guidance_requires_single_question_and_result(self):
        guidance = wizard.CREATION_FORESHADOW_CLOSURE_GUIDANCE
        self.assertIn("一个核心问题、一个核心承诺和一个可观察的回收结果", guidance)
        self.assertIn("写不出这四点，就不要生成伏笔", guidance)
        self.assertIn("真正贯穿全书核心矛盾", guidance)

    def test_bible_assets_recovers_rows_mixed_under_compact_c_key(self):
        result = wizard.normalize_creation_result(
            "bible",
            {
                "c": [
                    {
                        "n": "人物甲",
                        "r": "主角",
                        "g": "目标",
                        "s": "秘密",
                        "p": "性格",
                        "v": "口吻",
                        "q": "长期变化",
                    },
                    {
                        "n": "设定甲",
                        "t": "规则",
                        "d": "具体内容",
                        "k": "人物已知",
                    },
                    {
                        "i": "f1",
                        "n": "伏笔甲",
                        "a": "第1阶段",
                        "b": "第2阶段",
                        "d": "线索",
                        "r": "揭示结果",
                        "u": "未揭开",
                    },
                ],
            },
            foreshadow_stage_count=5,
        )

        self.assertEqual([item["name"] for item in result["characters"]], ["人物甲"])
        self.assertEqual([item["name"] for item in result["lore"]], ["设定甲"])
        self.assertEqual([item["code"] for item in result["foreshadows"]], ["F0001"])
        self.assertEqual(result["foreshadows"][0]["setup_stage"], "第1阶段")

    def test_bible_assets_recovers_positional_foreshadow_rows_mixed_under_c_key(self):
        result = wizard.normalize_creation_result(
            "bible",
            {
                "c": [
                    ["人物甲", "主角", "目标", "秘密", "性格", "口吻", "备注"],
                    ["设定甲", "规则", "具体内容", "人物已知"],
                    ["F1", "伏笔甲", "第1阶段", "第2阶段", "线索", "揭示结果", "未揭开"],
                ],
            },
            foreshadow_stage_count=5,
        )

        self.assertEqual(len(result["characters"]), 1)
        self.assertEqual(len(result["lore"]), 1)
        self.assertEqual(result["foreshadows"][0]["code"], "F0001")

    def test_stage_directions_normalize_and_keep_scene_character_result_fields(self):
        result = wizard.normalize_creation_result(
            "bible",
            {
                "stage_directions": [
                    {
                        "i": "R01",
                        "n": "废材开局",
                        "w": [0, 100000],
                        "s": "主角在宗族擂台觉醒并完成逆袭。",
                        "l": "家族大厅与宗族擂台",
                        "c": "退婚者和族内天才",
                        "x": "主角拿回修炼资格",
                        "q": "必须进入更大的修炼场",
                    },
                ],
            },
            total_words=100000,
            creation_batch="stage_directions",
        )

        direction = result["stage_directions"][0]
        self.assertEqual(direction["id"], "R01")
        self.assertEqual(direction["start_word"], 0)
        self.assertEqual(direction["end_word"], 100000)
        self.assertEqual(direction["scene_change"], "家族大厅与宗族擂台")
        self.assertEqual(direction["character_change"], "退婚者和族内天才")
        self.assertEqual(direction["result"], "主角拿回修炼资格")

    def test_stage_direction_batch_waits_for_confirmation_before_bible(self):
        dialog = wizard.NovelCreationWizardDialog.__new__(
            wizard.NovelCreationWizardDialog
        )
        dialog.step_results = {}
        self.assertEqual(dialog._next_generation_batch("bible")[0], "stage_directions")
        dialog.step_results["bible"] = {
            "stage_directions": [{"summary": "阶段方向"}],
            "_generation_state": {
                "status": "partial",
                "completed_batches": ["stage_directions"],
                "stage_directions_confirmed": False,
            },
        }
        self.assertEqual(dialog._next_generation_batch("bible")[0], "")
        dialog.step_results["bible"]["_generation_state"]["stage_directions_confirmed"] = True
        self.assertEqual(dialog._next_generation_batch("bible")[0], "bible_core")

    def test_confirmed_stage_directions_start_stage_batches_directly(self):
        dialog = wizard.NovelCreationWizardDialog.__new__(
            wizard.NovelCreationWizardDialog
        )
        dialog.target_words_spin = SimpleNamespace(value=lambda: 200000)
        dialog.average_words_spin = SimpleNamespace(value=lambda: 3000)
        dialog.step_results = {
            "bible": {
                "_generation_state": {
                    "completed_batches": ["stage_directions"],
                    "stage_directions_confirmed": True,
                },
                "stage_directions": [
                    {
                        "name": "家族逆袭",
                        "summary": "主角在家族擂台觉醒并完成逆袭。",
                        "scene_change": "家族大厅与宗族擂台",
                        "character_change": "退婚者成为直接对手",
                        "result": "主角拿回修炼资格",
                    },
                    {
                        "name": "都城入宗",
                        "summary": "主角进入都城宗门，在外门大比中站稳脚跟。",
                        "scene_change": "都城与宗门外门",
                        "character_change": "宗门师兄和权贵长公子进入主线",
                        "result": "主角进入内门",
                    },
                ],
            },
            "stage_plan": {},
        }
        self.assertTrue(dialog._has_stage_directions())
        self.assertEqual(
            dialog._next_generation_batch("stage_plan"),
            ("stage_plan_stage", 0),
        )

    def test_stage_direction_prompt_requires_new_scene_and_character_changes(self):
        worker = wizard.NovelCreationWorker(
            "http://example.test",
            "key",
            "model",
            "bible",
            {
                "author_input": {"total_words": 200000, "average_chapter_words": 3000},
                "selected_premise": {"genre": "传统玄幻"},
            },
            batch_kind="stage_directions",
        )
        prompt = worker._analysis_prompt()
        self.assertIn("阶段方向", prompt)
        self.assertIn("场景和人物变化", prompt)
        self.assertIn("不能只是继续在同一家庭、公司、工厂、宗门", prompt)
        self.assertIn("完结前高潮方向", prompt)
        self.assertIn("最后3章属于高潮结果兑现与收束的一部分", prompt)
        self.assertIn('"stage_directions"', prompt)

    def test_generation_batch_labels_are_specific_to_the_current_batch(self):
        self.assertEqual(
            wizard._creation_batch_display_name("stage_directions"),
            "阶段方向",
        )
        self.assertEqual(
            wizard._creation_batch_action_text("stage_directions"),
            "AI 生成阶段方向",
        )
        self.assertEqual(
            wizard._creation_batch_action_text("bible_assets"),
            "AI 生成人物、设定、伏笔",
        )
        self.assertEqual(
            wizard._creation_batch_action_text("stage_plan_stage", 1, 5),
            "AI 生成第2阶段（共5个阶段）",
        )
        self.assertEqual(
            wizard._creation_batch_action_text("stage_endpoint_repair", 0, 5),
            "AI 补齐第1阶段伏笔定位",
        )

    def test_stage_direction_worker_progress_does_not_fall_back_to_bible_assets(self):
        worker = wizard.NovelCreationWorker(
            "http://example.test",
            "key",
            "model",
            "bible",
            {"author_input": {"total_words": 200000}},
            batch_kind="stage_directions",
        )
        self.assertEqual(worker._analysis_progress_label(), "全书阶段方向")
        self.assertEqual(worker._generation_progress_text(200000), "正在生成：全书阶段方向")

    def test_direct_stage_pressure_row_is_preserved_as_pressure_curve(self):
        curve = _normalize_mainline_pressure_curve({
            "scope": "从厂区扩大到跨城区路线",
            "step": "必须同时承受守厂与外出风险",
            "opponents": ["掠夺者", "车队利益方"],
            "cost": "放弃一批关键配件救人",
            "exit_change": "补给路线与车队绑定",
        })
        self.assertEqual(len(curve.get("stage_ladder", [])), 1)
        row = curve["stage_ladder"][0]
        self.assertEqual(row["stage_id"], "S01")
        self.assertEqual(row["direct_opponents"], "掠夺者；车队利益方")
        self.assertEqual(row["exit_change"], "补给路线与车队绑定")

    def test_stage_pressure_row_uses_the_surrounding_stage_id(self):
        result = wizard.normalize_creation_result(
            "stage_plan",
            {
                "s": {
                    "i": "S03",
                    "n": "电站阶段",
                    "r": [69, 100],
                    "b": {},
                    "e": [{
                        "i": "E01",
                        "r": [69, 69],
                        "h": "人物在电站入口发生冲突并作出选择。",
                        "o": "设备取得代价落地。",
                        "d": "供能范围改变。",
                    }],
                    "x": {},
                    "y": [],
                    "u": {
                        "scope": "冲突扩大到电站",
                        "step": "压力提高",
                        "opponents": "控制者",
                        "cost": "交出独占权",
                        "exit_change": "区域供能建立",
                    },
                },
            },
            total_words=300000,
            average_chapter_words=3000,
            pad_stage_plan=False,
        )
        self.assertEqual(
            result["stage_plan"][0]["mainline_pressure"]["stage_id"],
            "S03",
        )

    def test_normalization_can_use_the_active_batch_instead_of_recomputing_next_batch(self):
        dialog = wizard.NovelCreationWizardDialog.__new__(
            wizard.NovelCreationWizardDialog
        )
        dialog.target_words_spin = SimpleNamespace(value=lambda: 200000)
        dialog.average_words_spin = SimpleNamespace(value=lambda: 3000)
        dialog.premise_candidates = []
        dialog.choice_values = {}
        dialog.step_results = {
            "bible": {
                "_generation_state": {
                    "status": "partial",
                    "completed_batches": ["stage_directions"],
                    "stage_directions_confirmed": False,
                },
            },
        }
        result = dialog._normalize_step_result(
            "bible",
            {"stage_directions": [{"summary": "当前请求的方向"}]},
            creation_batch="stage_directions",
        )
        self.assertEqual(result["stage_directions"][0]["summary"], "当前请求的方向")

    def test_stage_plan_requires_complete_stage_directions(self):
        dialog = wizard.NovelCreationWizardDialog.__new__(
            wizard.NovelCreationWizardDialog
        )
        dialog.target_words_spin = SimpleNamespace(value=lambda: 200000)
        dialog.average_words_spin = SimpleNamespace(value=lambda: 3000)
        dialog.step_results = {
            "bible": {
                "_generation_state": {
                    "completed_batches": [],
                    "stage_directions_confirmed": False,
                },
                "stage_directions": [{"summary": "仅有第一阶段"}],
            },
            "stage_plan": {
                "stage_plan": [],
            },
        }
        self.assertEqual(
            dialog._next_generation_batch("stage_plan"),
            ("", -1),
        )

    def test_recovered_stage_directions_survive_bible_core_normalization(self):
        dialog = wizard.NovelCreationWizardDialog.__new__(
            wizard.NovelCreationWizardDialog
        )
        dialog.target_words_spin = SimpleNamespace(value=lambda: 200000)
        dialog.average_words_spin = SimpleNamespace(value=lambda: 3000)
        dialog._allow_power_levels = lambda: False
        result = dialog._normalize_step_result(
            "bible",
            {
                "stage_directions": [
                    {"summary": "第一阶段方向"},
                    {"summary": "第二阶段方向"},
                ],
                "bible": {"main_conflict": "主线冲突"},
                "world_rules": {},
            },
            creation_batch="bible_core",
        )
        self.assertEqual(
            [item["summary"] for item in result["stage_directions"]],
            ["第一阶段方向", "第二阶段方向"],
        )
        self.assertEqual(result["bible"]["main_conflict"], "主线冲突")

    def test_restoring_full_bible_payload_does_not_misclassify_it_as_directions_only(self):
        dialog = wizard.NovelCreationWizardDialog.__new__(
            wizard.NovelCreationWizardDialog
        )
        dialog.target_words_spin = SimpleNamespace(value=lambda: 200000)
        dialog.average_words_spin = SimpleNamespace(value=lambda: 3000)
        dialog._allow_power_levels = lambda: False
        dialog.step_results = {}
        result = dialog._normalize_step_result(
            "bible",
            {
                "_generation_state": {
                    "status": "complete",
                    "completed_batches": ["stage_directions", "bible_core", "bible_assets"],
                    "stage_directions_confirmed": True,
                },
                "stage_directions": [
                    {"summary": "第一阶段方向"},
                    {"summary": "第二阶段方向"},
                ],
                "bible": {"main_conflict": "主线冲突"},
                "world_rules": {"rules": ["长期规则"], "costs_and_limits": ["代价"]},
                "characters": [{"name": "主角"}],
                "lore": [{"name": "地点", "description": "故事地点"}],
                "foreshadows": [{"code": "F0001", "name": "线索"}],
            },
        )
        self.assertEqual(len(result["stage_directions"]), 2)
        self.assertEqual(result["bible"]["main_conflict"], "主线冲突")
        self.assertEqual(result["world_rules"]["rules"], ["长期规则"])
        self.assertEqual(result["characters"][0]["name"], "主角")
        self.assertTrue(result["_generation_state"]["stage_directions_confirmed"])

    def test_stage_plan_context_receives_all_directions_and_current_direction(self):
        dialog = wizard.NovelCreationWizardDialog.__new__(
            wizard.NovelCreationWizardDialog
        )
        directions = [
            {"id": "R01", "summary": "进入山门，赢下外门争斗"},
            {"id": "R02", "summary": "下山追查灵脉异变"},
        ]
        dialog.inspiration_edit = SimpleNamespace(text=lambda: "作者灵感")
        dialog.project_name_hint = "测试书名"
        dialog.choice_values = {}
        dialog.target_words_spin = SimpleNamespace(value=lambda: 200000)
        dialog.average_words_spin = SimpleNamespace(value=lambda: 3000)
        dialog._selected_custom_protagonist_style = lambda: {}
        dialog._current_premise = lambda: {"title": "测试书名", "synopsis": "简介"}
        dialog.step_results = {
            "bible": {
                "stage_directions": directions,
                "foreshadows": [],
            },
            "stage_plan": {},
        }

        context = dialog._context_for_step("stage_plan")

        self.assertEqual(context["confirmed"]["stage_directions"], directions)
        self.assertEqual(context["current_stage"]["stage_direction"], directions[0])

    def test_character_style_choice_only_exposes_personality_and_voice(self):
        entry = {
            "id": "style-1",
            "name": "贺知微",
            "source_project": "路人甲",
            "source_character": "贺知微",
            "personality": "先观察再行动",
            "voice": "说话自然，少用总结句",
            "secret": "不应传递",
        }
        with patch.object(wizard, "load_character_style_library", return_value=[entry]):
            self.assertEqual(
                wizard._character_style_choice_groups(),
                {
                    "已收藏人物卡风格": (
                        wizard.CHARACTER_STYLE_NONE_OPTION,
                        "贺知微（路人甲）\n性格/特点：先观察再行动\n语言风格：说话自然，少用总结句",
                    )
                },
            )
            dialog = wizard.NovelCreationWizardDialog.__new__(
                wizard.NovelCreationWizardDialog
            )
            dialog.choice_values = {"protagonist_style": "style-1"}
            dialog.choice_display_values = {}
            self.assertEqual(
                dialog._choice_options("protagonist_style"),
                [
                    wizard.CHARACTER_STYLE_NONE_OPTION,
                    "贺知微（路人甲）\n性格/特点：先观察再行动\n语言风格：说话自然，少用总结句"
                ],
            )
            self.assertEqual(
                dialog._selected_choice_display("protagonist_style"),
                "贺知微（路人甲）",
            )
            self.assertEqual(
                dialog._selected_custom_protagonist_style(),
                {"personality": "先观察再行动", "voice": "说话自然，少用总结句"},
            )
            self.assertNotIn("secret", dialog._selected_custom_protagonist_style())

    def test_completed_wizard_record_keeps_inspiration_and_all_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            draft_dir = os.path.join(tmp, "drafts")
            os.makedirs(draft_dir, exist_ok=True)
            draft_index = os.path.join(draft_dir, "index.json")
            legacy_file = os.path.join(tmp, "legacy.json")
            draft_id = "123-test"
            payload = {
                "schema_version": 3,
                "draft_id": draft_id,
                "created_at": "2026-10-12 10:00:00",
                "created_at_ns": 123,
                "updated_at": "2026-10-12 10:10:00",
                "project_name_hint": "测试小说",
                "current_step_index": 2,
                "inspiration": "主角刚毕业，误入一场不属于自己的故事。",
                "choice_values": {"genre": "都市日常"},
                "target_words": 500000,
                "average_words": 3000,
                "premise_candidates": [{"title": "测试小说", "synopsis": "简介"}],
                "premise_selected_index": 0,
                "step_results": {
                    "premise": {"candidates": [{"title": "测试小说"}]},
                    "bible": {"bible": {"core_setting": "底盘"}},
                    "stage_plan": {"stage_plan": [{"name": "第一阶段"}]},
                },
            }
            with patch.object(wizard, "CREATION_WIZARD_DRAFT_DIR", draft_dir), \
                patch.object(wizard, "CREATION_WIZARD_DRAFT_INDEX_FILE", draft_index), \
                patch.object(wizard, "CREATION_WIZARD_DRAFT_FILE", legacy_file):
                wizard.save_creation_wizard_draft(payload)
                project_path = os.path.join(tmp, "projects", "测试小说.json")
                archive_path = wizard.mark_creation_wizard_draft_completed(
                    draft_id,
                    project_path,
                    {"creation_framework": {"novel_name": "测试小说"}},
                )

                self.assertTrue(archive_path)
                saved = wizard.load_creation_wizard_draft(draft_id)
                self.assertEqual(saved["inspiration"], payload["inspiration"])
                self.assertEqual(set(saved["step_results"]), {"premise", "bible", "stage_plan"})
                self.assertEqual(saved["completion_status"], "completed")
                self.assertEqual(saved["imported_project_path"], os.path.abspath(project_path))

                records = wizard.list_creation_wizard_drafts()
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["status_label"], "已完成")
                self.assertEqual(records[0]["completion_status"], "completed")

    def test_inspiration_fact_guidance_is_shared_by_wizard_prompts(self):
        self.assertIn("作者灵感中明确写出的事实", wizard.COMMON_CREATION_RULES)
        for step in ("premise", "bible"):
            self.assertIn("作者灵感中明确写出的事实", wizard.STEP_PROMPTS[step])

    def test_core_motive_guidance_is_shared_and_carried_into_foundation(self):
        guidance = wizard.CREATION_CORE_MOTIVE_GUIDANCE
        for phrase in ("核心动机", "具体目标", "失败代价", "反差", "阶段目标"):
            self.assertIn(phrase, guidance)
        self.assertTrue(
            "机会窗口" in guidance or "时间限制" in guidance
        )
        self.assertIn("核心动机契约", wizard.STEP_PROMPTS["bible"])
        self.assertIn("主题字段只提炼", wizard.STEP_PROMPTS["bible"])
        self.assertTrue(
            "具体任务、金额、期限" in wizard.STEP_PROMPTS["bible"]
            or "不重复具体任务、金额、期限" in wizard.STEP_PROMPTS["bible"]
        )
        self.assertTrue(
            "下一阶段目标" in wizard.STEP_PROMPTS["stage_plan"]
            or "下一道更具体的" in wizard.STEP_PROMPTS["stage_plan"]
        )

        foundation = wizard.build_chapter_plan_foundation({
            "premise": {
                "synopsis": "主角必须在期限前救回妻子。",
                "main_line": "距离手术还有一个月，他必须凑够五万元。",
                "relationship_engine": "夫妻关系从互相怀疑走向重新信任。",
            },
            "bible": {"main_conflict": "资金、时间和旧债同时逼近。"},
            "stage_plan": [{
                "name": "凑齐手术费",
                "summary": "主角寻找第一笔资金并面对阻碍。",
                "main_conflict": "旧债主截断了他的收入来源。",
                "end_state": "拿到部分手术费，但必须夺回被扣押的货物。",
            }],
            "total_words": 100000,
            "average_chapter_words": 3000,
        })
        self.assertEqual(
            foundation["core_motive"],
            "资金、时间和旧债同时逼近。",
        )
        self.assertEqual(
            foundation["narrative_strategy_profile"]["core_motive"],
            foundation["core_motive"],
        )
        self.assertEqual(
            foundation["terminal_window"],
            {
                "start_chapter": 32,
                "end_chapter": 34,
                "chapter_count": 3,
                "source": "creation_wizard",
            },
        )

        fallback = wizard.build_chapter_plan_foundation({
            "premise": {"main_line": "第一步的具体主线。"},
            "bible": {},
            "stage_plan": [],
            "total_words": 100000,
            "average_chapter_words": 3000,
        })
        self.assertEqual(fallback["core_motive"], "第一步的具体主线。")
        self.assertEqual(
            foundation["creative_intent_contract"]["core_motive"],
            foundation["core_motive"],
        )

    def test_terminal_contract_projects_final_stage_results_and_roles(self):
        foundation = wizard.build_chapter_plan_foundation({
            "premise": {
                "ending_direction": "主角完成救援并让小镇恢复日常秩序。",
                "relationship_engine": "搭档从互相猜疑变成共同守护。",
            },
            "bible": {"main_conflict": "主角必须在灾潮到来前守住小镇。"},
            "stage_plan": [{
                "id": "S01",
                "name": "终局",
                "start_chapter": 1,
                "end_chapter": 4,
                "end_state": "小镇恢复供水，主角交出指挥权。",
                "relationship_changes": ["搭档愿意共同留下"],
                "exit_state": {
                    "c": ["主角不再独自承担守护责任"],
                    "k": ["供水系统稳定运行"],
                },
                "ordered_events": [{
                    "id": "S01-E01",
                    "allowed_chapters": [4, 4],
                    "result": "供水系统完成修复并连续运行。",
                }],
                "closure_plan": {
                    "closure_mode": "mirror_scene",
                    "closure_horizon": "一年后",
                    "final_image": "主角和搭档回到第一次取水的水井旁。",
                    "opening_echo": "开头两人在断水的水井前争执。",
                    "title_closure_intent": "标题体现供水已经稳定和关系已经改变。",
                    "climax_event_id": "S01-E03",
                    "climax_chapter_range": [3, 3],
                    "climax_event": "主角在堤坝决口前选择留下抢修。",
                    "climax_result": "供水系统恢复，核心冲突当场落地。",
                    "post_climax_landing": "搭档接过维护责任，主角不再独自指挥。",
                    "time_jump_allowed": True,
                },
            }],
            "total_words": 10000,
            "average_chapter_words": 3000,
        })

        contract = foundation["terminal_contract"]
        self.assertIn("供水系统完成修复并连续运行。", contract["required_results"])
        self.assertIn("搭档愿意共同留下", contract["relationship_results"])
        self.assertNotIn("chapter_roles", contract)
        self.assertEqual(contract["closure_mode"], "mirror_scene")
        self.assertEqual(contract["closure_horizon"], "一年后")
        self.assertTrue(contract["time_jump_allowed"])
        self.assertEqual(contract["climax_event_id"], "S01-E03")
        self.assertEqual(contract["climax_chapter_range"], [3, 3])
        self.assertIn("供水系统恢复", contract["climax_result"])
        self.assertEqual(
            contract["final_image"],
            "主角和搭档回到第一次取水的水井旁。",
        )
        terminal_stage = foundation["structured_stages"][-1]
        terminal_event = terminal_stage["ordered_events"][-1]
        self.assertNotIn("terminal_role", terminal_event)
        self.assertEqual(terminal_stage["terminal_contract"]["version"], "1")
        self.assertEqual(terminal_stage["closure_plan"]["closure_mode"], "mirror_scene")

        premise_first = wizard.build_chapter_plan_foundation({
            "premise": {
                "core_motive": "第一步已经具体化的核心动机。",
                "main_line": "旧字段里的候选主线。",
            },
            "bible": {},
            "stage_plan": [],
            "total_words": 100000,
            "average_chapter_words": 3000,
        })
        self.assertEqual(
            premise_first["core_motive"],
            "第一步已经具体化的核心动机。",
        )

    def test_bible_display_exposes_core_motive_label(self):
        bible = {
            "core_setting": "工厂会在灾变中成为堡垒。",
            "main_conflict": "主角必须在设施失效前完成改造。",
        }
        text = wizard.format_creation_text(
            bible,
            "小说圣经",
            {"main_conflict": "核心动机契约（主线矛盾）"},
        )
        self.assertIn("核心动机契约（主线矛盾）：主角必须在设施失效前完成改造。", text)
        self.assertNotIn("\n主线矛盾：", text)

    def test_legacy_bible_label_is_migrated_without_changing_content(self):
        text = "小说圣经\n主线矛盾：主角必须在设施失效前完成改造。"
        migrated = wizard.migrate_creation_bible_display_text(text, True)
        self.assertEqual(
            migrated,
            "小说圣经\n核心动机契约（主线矛盾）：主角必须在设施失效前完成改造。",
        )

    def test_ending_direction_requires_book_closure_before_open_ended_aftertaste(self):
        guidance = wizard.CREATION_ENDING_DIRECTION_GUIDANCE
        self.assertIn("本部结局的方向性契约", guidance)
        self.assertIn("本部已经得到的结果", guidance)
        self.assertIn("不影响本部闭环", guidance)
        self.assertIn("不得把新敌人、新任务、新规则", guidance)
        self.assertIn("结尾方向（本部结果与余波）", wizard.STEP_PROMPTS["premise"])
        self.assertNotIn("开放式结尾方向", wizard.STEP_PROMPTS["premise"])
        self.assertIn("结尾方向字段必须写成“本部结果与余波”", wizard.STEP_PROMPTS["bible"])

        foundation = wizard.build_chapter_plan_foundation({
            "premise": {"ending_direction": "本部主线完成，但关系留下余味。"},
            "bible": {},
            "stage_plan": [],
            "total_words": 100000,
            "average_chapter_words": 3000,
        })
        profile = foundation["narrative_strategy_profile"]
        self.assertIn("本部明确结果", profile["story_direction"])
        self.assertNotIn("结尾留下有余波的问题", profile["story_direction"])

    def test_stage_plan_terminal_window_does_not_open_next_stage_task(self):
        base_context = {
            "author_input": {
                "total_words": 500000,
                "average_chapter_words": 3000,
                "genre": "玄幻",
            },
            "selected_premise": {"genre": "玄幻"},
            "current_stage": {
                "number": 5,
                "total_stages": 5,
                "start_chapter": 135,
                "end_chapter": 167,
                "target_words": 100000,
            },
        }
        terminal_worker = wizard.NovelCreationWorker(
            "http://example.test",
            "key",
            "model",
            "stage_plan",
            base_context,
            batch_kind="stage_plan_stage",
            stage_index=4,
        )
        terminal_prompt = terminal_worker._analysis_prompt()
        self.assertIn("最后3章收尾窗口", terminal_prompt)
        self.assertIn("本阶段后部只沿着已经发生的冲突", terminal_prompt)
        self.assertNotIn(
            "本阶段解决或暂时解决当前目标后，要在 x/y 或事件结果中留下下一阶段可执行的具体目标",
            terminal_prompt,
        )

        ordinary_context = dict(base_context)
        ordinary_context["current_stage"] = {
            "number": 4,
            "total_stages": 5,
            "start_chapter": 101,
            "end_chapter": 134,
            "target_words": 100000,
        }
        ordinary_worker = wizard.NovelCreationWorker(
            "http://example.test",
            "key",
            "model",
            "stage_plan",
            ordinary_context,
            batch_kind="stage_plan_stage",
            stage_index=3,
        )
        ordinary_prompt = ordinary_worker._analysis_prompt()
        self.assertNotIn("最后3章收尾窗口", ordinary_prompt)
        self.assertIn(
            "本阶段解决或暂时解决当前目标后，要在 x/y 或事件结果中留下下一阶段可执行的具体目标",
            ordinary_prompt,
        )

    def test_character_profile_guidance_blocks_adversarial_voice_labels(self):
        guidance = wizard.CREATION_CHARACTER_PROFILE_GUIDANCE
        self.assertIn("语言风格可以保留“话多”等正常表达特征", guidance)
        self.assertIn("不得生成“话少、寡言、惜字如金、解释型、反问多", guidance)
        self.assertIn("质问式、审问式、对抗式、命令式", guidance)
        self.assertIn("不能作为人物卡的语言风格结论", guidance)
        self.assertIn("限制“话少”是为了避免正文模型把它误读成短句", guidance)

    def test_character_name_prefix_is_moved_to_role_without_rewriting_role(self):
        cases = (
            ("陶大姑陶秀兰", "陶秀兰", "陶大姑"),
            ("陶二叔陶建平", "陶建平", "陶二叔"),
            ("闻母沈曼如", "沈曼如", "闻母"),
            ("闻父闻承岳", "闻承岳", "闻父"),
            ("陶小姨陶秀梅", "陶秀梅", "陶小姨"),
            ("陶家长辈陶秀兰", "陶秀兰", "陶家长辈"),
            ("陶知意大姑陶秀兰", "陶秀兰", "陶知意大姑"),
        )
        for raw_name, expected_name, expected_prefix in cases:
            original_role = "完整身份说明，包含关系、故事位置和长期作用"
            record = wizard._normalize_character_record({
                "name": raw_name,
                "role": original_role,
                "goal": "目标",
                "secret": "秘密",
                "personality": "性格",
                "voice": "话多",
                "notes": "备注",
            })
            self.assertEqual(record["name"], expected_name)
            self.assertTrue(record["role"].startswith(expected_prefix + "，"))
            self.assertIn(original_role, record["role"])
            self.assertEqual(record["goal"], "目标")
            self.assertEqual(record["secret"], "秘密")

    def test_standalone_title_or_formal_name_is_not_changed(self):
        for name in ("陶大姑", "陶秀兰", "梁律师"):
            record = wizard._normalize_character_record({"name": name, "role": "身份"})
            self.assertEqual(record["name"], name)
            self.assertEqual(record["role"], "身份")

    def test_character_name_split_rule_is_in_bible_prompt(self):
        self.assertIn("姓名字段只填写人物的正式姓名", wizard.STEP_PROMPTS["bible"])
        self.assertIn("陶大姑陶秀兰", wizard.STEP_PROMPTS["bible"])

    def test_bible_prompt_preserves_names_from_selected_story(self):
        prompt = wizard.STEP_PROMPTS["bible"]
        self.assertIn("已经选定的这个故事简介及其中明确写出的姓名为准", prompt)
        self.assertIn("必须原样沿用这些既定姓名", prompt)
        self.assertIn("不得因为命名参考而过滤、替换、改写或遗漏", prompt)
        self.assertIn("命名参考只用于为新增人物起名", prompt)
        self.assertNotIn("五个方向", prompt)

    def test_recent_name_guidance_uses_one_all_people_reference(self):
        for step in ("premise", "bible"):
            prompt = wizard.STEP_PROMPTS[step]
            self.assertIn("n.recent_character_names", prompt)
            self.assertIn("同音或近音", prompt)
            self.assertIn("只换一个字", prompt)
            self.assertIn("读音节奏", prompt)
        self.assertNotIn("主角姓名不能重复", wizard.STEP_PROMPTS["premise"])
        self.assertNotIn("软性避重", wizard.STEP_PROMPTS["premise"])

    def test_character_name_collection_keeps_every_character(self):
        records = [
            {"name": "林澈", "role": "主角"},
            {"name": "程绛", "role": "重要配角"},
            {"name": "齐越", "role": "维修学徒"},
            {"name": "林澈", "role": "重复资料"},
        ]
        self.assertEqual(
            wizard._creation_character_names(records),
            ["林澈", "程绛", "齐越"],
        )

    def test_project_name_scan_includes_all_character_cards(self):
        payload = {
            "characters": [{"name": "林澈"}, {"name": "程绛"}],
            "creation_framework": {
                "characters": [{"name": "程绛"}, {"name": "齐越"}],
            },
        }
        self.assertEqual(
            wizard._creation_project_character_names(payload),
            ["林澈", "程绛", "齐越"],
        )

    def test_name_reference_returns_100_most_recent_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = os.path.join(temp_dir, "name_history.json")
            records = [
                {"name": f"人物{i:03d}", "created_at_ns": i + 1}
                for i in range(120)
            ]
            with open(history_path, "w", encoding="utf-8") as file:
                json.dump({
                    "schema_version": wizard.CREATION_WIZARD_NAME_PROJECT_SCAN_VERSION,
                    "project_scan_complete": True,
                    "records": records,
                }, file, ensure_ascii=False)
            with patch.object(wizard, "CREATION_WIZARD_NAME_HISTORY_FILE", history_path):
                references = wizard._creation_name_references()
        self.assertEqual(wizard.CREATION_WIZARD_NAME_REFERENCE_LIMIT, 100)
        self.assertEqual(len(references["recent_character_names"]), 100)
        self.assertEqual(references["recent_character_names"][0], "人物119")
        self.assertEqual(references["recent_character_names"][-1], "人物020")

    def test_legacy_project_scan_backfills_all_names_by_project_recency(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_dir = os.path.join(temp_dir, "history")
            project_dir = os.path.join(history_dir, "novel_projects")
            draft_dir = os.path.join(history_dir, "novel_creation_wizard_drafts")
            os.makedirs(project_dir)
            os.makedirs(draft_dir)
            history_path = os.path.join(history_dir, "name_history.json")
            with open(history_path, "w", encoding="utf-8") as file:
                json.dump({
                    "schema_version": 1,
                    "project_scan_complete": True,
                    "records": [{"name": "旧姓名", "created_at_ns": 1}],
                }, file, ensure_ascii=False)
            older_path = os.path.join(project_dir, "older.json")
            newer_path = os.path.join(project_dir, "newer.json")
            for path, names in (
                (older_path, ["旧项目甲", "旧项目乙"]),
                (newer_path, ["新项目甲", "新项目乙", "新项目丙"]),
            ):
                with open(path, "w", encoding="utf-8") as file:
                    json.dump({"characters": [{"name": name} for name in names]}, file)
            os.utime(older_path, ns=(1_000_000_000, 1_000_000_000))
            os.utime(newer_path, ns=(2_000_000_000, 2_000_000_000))
            with (
                patch.object(wizard, "HISTORY_DIR", history_dir),
                patch.object(wizard, "CREATION_WIZARD_DRAFT_DIR", draft_dir),
                patch.object(wizard, "CREATION_WIZARD_NAME_HISTORY_FILE", history_path),
            ):
                references = wizard._creation_name_references()
                with open(history_path, "r", encoding="utf-8") as file:
                    saved_history = json.load(file)
        names = references["recent_character_names"]
        self.assertTrue(set(("新项目甲", "新项目乙", "新项目丙", "旧项目甲", "旧项目乙", "旧姓名")) <= set(names))
        self.assertLess(max(names.index("新项目甲"), names.index("新项目乙")), names.index("旧项目甲"))
        self.assertEqual(
            saved_history["schema_version"],
            wizard.CREATION_WIZARD_NAME_PROJECT_SCAN_VERSION,
        )

    def test_step_two_uses_the_shared_reference_without_a_separate_name_group(self):
        dialog = wizard.NovelCreationWizardDialog.__new__(wizard.NovelCreationWizardDialog)
        dialog.inspiration_edit = SimpleNamespace(text=lambda: "作者灵感")
        dialog.project_name_hint = ""
        dialog.choice_values = {}
        dialog.target_words_spin = SimpleNamespace(value=lambda: 300000)
        dialog.average_words_spin = SimpleNamespace(value=lambda: 3000)
        dialog._selected_custom_protagonist_style = lambda: {}
        dialog.premise_candidates = [
            {"protagonist": "林澈"},
            {"protagonist": "沈闻"},
            {"protagonist": "周予"},
        ]
        dialog.premise_selected_index = 1
        dialog._current_premise = lambda: {"protagonist": "沈闻", "title": "已选故事"}
        dialog.step_results = {"bible": {"characters": [{"name": "程绛"}, {"name": "齐越"}]}}
        dialog._next_generation_batch = lambda _step: ("bible_core", -1)
        with patch.object(
            wizard,
            "_creation_name_references",
            side_effect=lambda *args: {"received_args": args},
        ):
            context = dialog._context_for_step("bible")
        self.assertEqual(context["naming_reference"]["received_args"], ())
        self.assertEqual(context["selected_premise"]["title"], "已选故事")
        self.assertNotIn("五个方向", wizard.STEP_PROMPTS["bible"])
        self.assertNotIn("主角姓名不能重复", wizard.STEP_PROMPTS["bible"])

    def test_step_one_adds_existing_candidate_names_to_the_same_reference(self):
        dialog = wizard.NovelCreationWizardDialog.__new__(wizard.NovelCreationWizardDialog)
        dialog.inspiration_edit = SimpleNamespace(text=lambda: "作者灵感")
        dialog.project_name_hint = ""
        dialog.choice_values = {}
        dialog.target_words_spin = SimpleNamespace(value=lambda: 300000)
        dialog.average_words_spin = SimpleNamespace(value=lambda: 3000)
        dialog._selected_custom_protagonist_style = lambda: {}
        dialog.premise_candidates = [
            {"protagonist": "林澈"},
            {"protagonist": "沈闻"},
        ]
        with patch.object(
            wizard,
            "_creation_name_references",
            side_effect=lambda names: {"received_names": names},
        ):
            context = dialog._context_for_step("premise")
        self.assertEqual(
            context["naming_reference"]["received_names"],
            ["林澈", "沈闻"],
        )
        self.assertEqual(set(context["naming_reference"]), {"received_names"})


if __name__ == "__main__":
    unittest.main()
