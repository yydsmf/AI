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
                "start_chapter": 30,
                "end_chapter": 34,
                "chapter_count": 5,
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
        self.assertIn("最后5章收尾窗口", terminal_prompt)
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
        self.assertNotIn("最后5章收尾窗口", ordinary_prompt)
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


if __name__ == "__main__":
    unittest.main()
