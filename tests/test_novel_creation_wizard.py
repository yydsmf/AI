import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import gpt_desktop.novel_creation_wizard as wizard


class NovelCreationWizardPersistenceTests(unittest.TestCase):
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

    def test_creation_scale_requires_three_foreshadows_per_stage(self):
        _size_label, ranges = wizard._creation_scale_requirements(500000)
        self.assertEqual(ranges["characters"], (25, 25))
        self.assertEqual(ranges["lore"], (25, 25))
        self.assertEqual(ranges["foreshadows"], (15, 15))

        assets = self._scale_sized_assets([3, 3, 3, 3, 3])
        self.assertEqual(
            wizard._creation_scale_shortfalls(assets, 500000),
            [],
        )

    def test_creation_scale_rejects_total_enough_but_stage_shortfall(self):
        assets = self._scale_sized_assets([2, 4, 3, 3, 3])
        shortfalls = wizard._creation_scale_shortfalls(assets, 500000)
        self.assertIn("伏笔第1阶段 2/3", shortfalls)
        self.assertNotIn("伏笔 15/15", shortfalls)

    def test_bible_confirmation_uses_stage_foreshadow_minimum(self):
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

        self.assertIn("资料数量未达到按阶段计算的最低要求", error)
        self.assertIn("伏笔第1阶段 2/3", error)

    def test_creation_scale_guidance_uses_positive_foreshadow_prompt(self):
        guidance = wizard._creation_scale_guidance(500000)
        self.assertIn("每个阶段至少生成3条真正有长期回收价值的新增伏笔", guidance)
        self.assertNotIn("每个阶段至少准备5条", guidance)

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


if __name__ == "__main__":
    unittest.main()
