import unittest

from gpt_desktop.novel_import import (
    _apply_import_candidates,
    _candidate_analysis_dossier_text,
    _candidate_analysis_text,
    _normalize_ai_candidates,
)
from gpt_desktop.novel_utils import _new_chapter, _normalize_project


class NovelImportCandidateTests(unittest.TestCase):
    def test_candidate_analysis_text_includes_linked_characters(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章 旧案"
        chapter["outline"] = "赵明进入王城。"
        chapter["linked_characters"] = ["赵明", "迟到主角"]
        chapter["summary"] = "两人开始调查旧案。"
        project = {"chapters": [chapter]}

        text = _candidate_analysis_text(project, "", [chapter["id"]])

        self.assertIn("关联人物", text)
        self.assertIn("赵明、迟到主角", text)

    def test_candidate_analysis_text_includes_existing_project_dossier(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第二章 入城"
        chapter["text"] = "赵明继续追查虎符失踪。"
        project = {
            "meta": {"title": "长篇测试", "premise": "旧案重启。"},
            "bible": "核心设定：旧案牵动三代人。",
            "timeline": "第一章旧案重启。",
            "summary": "赵明已经拿到缺页卷宗。",
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "克制"},
            ],
            "lore": [
                {"name": "王城", "type": "地点", "description": "故事主舞台。"},
            ],
            "foreshadow_items": [
                {"name": "虎符失踪", "status": "已埋", "setup_chapter": "第一章", "payoff_chapter": ""},
            ],
            "chapters": [chapter],
        }

        text = _candidate_analysis_text(project, "", [chapter["id"]])

        self.assertIn("【已有项目档案】", text)
        self.assertIn("已有主要人物", text)
        self.assertIn("赵明", text)
        self.assertIn("已有设定库", text)
        self.assertIn("王城", text)
        self.assertIn("已有伏笔", text)
        self.assertIn("虎符失踪", text)
        self.assertIn("第二章 入城", text)

        body_only = _candidate_analysis_text(project, "", [chapter["id"]], include_dossier=False)
        dossier = _candidate_analysis_dossier_text(project)

        self.assertNotIn("【已有项目档案】", body_only)
        self.assertIn("第二章 入城", body_only)
        self.assertIn("【已有项目档案】", dossier)
        self.assertIn("虎符失踪", dossier)

    def test_candidate_analysis_dossier_prioritizes_active_late_character(self):
        characters = [
            {"name": f"路人角色{i:02d}", "role": "", "goal": "", "secret": "", "voice": "", "notes": ""}
            for i in range(45)
        ]
        characters.append({
            "name": "迟到主角",
            "role": "主角",
            "goal": "查明终局真相",
            "secret": "",
            "voice": "克制",
            "notes": "",
        })
        chapters = []
        for i in range(3):
            chapter = _new_chapter(i)
            chapter["title"] = f"第{i + 1}章"
            chapter["linked_characters"] = ["迟到主角"]
            chapter["summary"] = "迟到主角推进主线。"
            chapters.append(chapter)
        project = {"characters": characters, "chapters": chapters}

        dossier = _candidate_analysis_dossier_text(project)

        self.assertIn("迟到主角", dossier)
        self.assertIn("查明终局真相", dossier)
        self.assertNotIn("路人角色44", dossier)

    def test_candidate_analysis_dossier_prioritizes_active_late_lore(self):
        lore = [
            {"name": f"旧设定{i:02d}", "type": "其他", "description": ""}
            for i in range(45)
        ]
        lore.append({
            "name": "终局法庭",
            "type": "地点",
            "description": "审判主线秘密的核心地点。",
        })
        chapters = []
        for i in range(3):
            chapter = _new_chapter(i)
            chapter["title"] = f"第{i + 1}章"
            chapter["summary"] = "众人在终局法庭发现新证据。"
            chapters.append(chapter)
        project = {"lore": lore, "chapters": chapters}

        dossier = _candidate_analysis_dossier_text(project)

        self.assertIn("终局法庭", dossier)
        self.assertIn("审判主线秘密", dossier)
        self.assertNotIn("旧设定44", dossier)

    def test_candidate_analysis_dossier_recalls_lore_from_generic_stage_terms(self):
        chapters = []
        for i in range(3):
            chapter = _new_chapter(i)
            chapter["title"] = f"第{i + 1}章"
            chapter["outline"] = "主角回到主舞台，在朝堂继续调查旧案。"
            chapters.append(chapter)
        project = {
            "lore": [
                {"name": f"普通设定{i:02d}", "type": "地点", "description": "偏远地点，暂不影响主线。"}
                for i in range(45)
            ] + [
                {"name": "王城", "type": "地点", "description": "故事主舞台，朝堂和旧案卷宗都在这里交汇。"},
            ],
            "chapters": chapters,
        }

        dossier = _candidate_analysis_dossier_text(project)

        self.assertIn("王城", dossier)
        self.assertIn("故事主舞台", dossier)
        self.assertNotIn("普通设定44", dossier)

    def test_candidate_analysis_dossier_prioritizes_open_late_foreshadow(self):
        foreshadows = [
            {
                "name": f"旧线索{i:02d}",
                "status": "已回收",
                "setup_chapter": "第一章",
                "payoff_chapter": f"第{i + 2}章",
                "description": "已处理。",
            }
            for i in range(61)
        ]
        foreshadows.append({
            "name": "终局密钥",
            "status": "已埋",
            "setup_chapter": "第六十章",
            "payoff_chapter": "",
            "description": "仍待回收，关系最终真相。",
        })
        project = {"foreshadow_items": foreshadows}

        dossier = _candidate_analysis_dossier_text(project)

        self.assertIn("终局密钥", dossier)
        self.assertIn("仍待回收", dossier)
        self.assertNotIn("旧线索00", dossier)

    def test_normalize_ai_candidates_merges_duplicate_items_in_same_result(self):
        data = {
            "characters": [
                {
                    "name": "皇上赵明",
                    "role": "皇帝",
                    "goal": "",
                    "notes": "旧候选",
                },
                {
                    "name": "赵明",
                    "role": "皇帝",
                    "goal": "稳住朝局",
                    "notes": "新候选",
                },
            ],
            "lore": [
                {"name": "琉璃塔", "type": "地点", "description": "别称：白塔\n藏有旧案卷宗。"},
                {"name": "白塔", "type": "地点", "description": "塔顶有钟。"},
            ],
            "foreshadows": [
                {"name": "虎符失踪", "status": "已埋", "description": "别称：半枚虎符\n牵出兵权。"},
                {"name": "半枚虎符", "status": "已埋", "payoff_chapter": "第二十章", "description": "真相揭晓。"},
            ],
            "project_materials": {
                "summary": "皇商账册缺页牵出旧案。\n补充：皇商账册缺页牵出旧案。",
            },
        }

        normalized = _normalize_ai_candidates(data)

        self.assertEqual(len(normalized["characters"]), 1)
        self.assertEqual(normalized["characters"][0]["name"], "赵明")
        self.assertEqual(normalized["characters"][0]["goal"], "稳住朝局")
        self.assertIn("别称：皇上赵明", normalized["characters"][0]["notes"])
        self.assertIn("补充：新候选", normalized["characters"][0]["notes"])
        self.assertEqual(len(normalized["lore"]), 1)
        self.assertEqual(normalized["lore"][0]["description"].count("藏有旧案卷宗。"), 1)
        self.assertIn("别称：白塔", normalized["lore"][0]["description"])
        self.assertIn("补充：塔顶有钟。", normalized["lore"][0]["description"])
        self.assertEqual(len(normalized["foreshadows"]), 1)
        self.assertEqual(normalized["foreshadows"][0]["payoff_chapter"], "第二十章")
        self.assertIn("别称：半枚虎符", normalized["foreshadows"][0]["description"])
        self.assertIn("补充：真相揭晓。", normalized["foreshadows"][0]["description"])
        self.assertEqual(normalized["project_materials"]["summary"].count("皇商账册缺页牵出旧案。"), 1)

    def test_normalize_ai_candidates_accepts_chinese_field_aliases(self):
        data = {
            "characters": [
                {
                    "姓名": "赵明",
                    "身份": "主角",
                    "人物目标": "查清旧案",
                    "隐藏秘密": "不知道父亲曾改过证词",
                    "语言风格": "克制",
                    "备注": "与迟到主角结盟。",
                }
            ],
            "lore": [
                {"名称": "王城", "类别": "地点", "说明": "旧案调查的主舞台。"},
            ],
            "foreshadows": [
                {
                    "伏笔名": "虎符失踪",
                    "状态": "已埋",
                    "埋设章节": "第一章",
                    "回收章节": "第二十章",
                    "说明": "牵出兵权交易。",
                }
            ],
            "project_materials": {
                "小说圣经": "旧案牵动三代人。",
                "世界观": "王城贵族名册不可伪造。",
                "时间线": "第一章旧案重启。",
                "阶段摘要": "赵明拿到缺页卷宗。",
            },
        }

        normalized = _normalize_ai_candidates(data)

        self.assertEqual(normalized["characters"][0]["name"], "赵明")
        self.assertEqual(normalized["characters"][0]["role"], "主角")
        self.assertEqual(normalized["characters"][0]["goal"], "查清旧案")
        self.assertIn("迟到主角结盟", normalized["characters"][0]["notes"])
        self.assertEqual(normalized["lore"][0]["name"], "王城")
        self.assertEqual(normalized["lore"][0]["type"], "地点")
        self.assertIn("旧案调查的主舞台", normalized["lore"][0]["description"])
        self.assertEqual(normalized["foreshadows"][0]["name"], "虎符失踪")
        self.assertEqual(normalized["foreshadows"][0]["setup_chapter"], "第一章")
        self.assertEqual(normalized["foreshadows"][0]["payoff_chapter"], "第二十章")
        self.assertIn("旧案牵动三代人", normalized["project_materials"]["bible"])
        self.assertIn("贵族名册", normalized["project_materials"]["world_rules"])
        self.assertIn("第一章旧案重启", normalized["project_materials"]["timeline"])
        self.assertIn("缺页卷宗", normalized["project_materials"]["summary"])

    def test_normalize_ai_candidates_accepts_chinese_top_level_groups(self):
        data = {
            "人物": [
                {"姓名": "赵明", "身份": "主角", "人物目标": "查清旧案"},
            ],
            "设定": [
                {"名称": "王城", "类别": "地点", "说明": "旧案调查的主舞台。"},
            ],
            "伏笔": [
                {
                    "伏笔名": "虎符失踪",
                    "状态": "已埋",
                    "埋设章节": "第一章",
                    "回收章节": "第二十章",
                    "说明": "牵出兵权交易。",
                }
            ],
            "项目资料": {
                "小说圣经": "旧案牵动三代人。",
                "世界观": "王城贵族名册不可伪造。",
                "时间线": "第一章旧案重启。",
                "阶段摘要": "赵明拿到缺页卷宗。",
            },
        }

        normalized = _normalize_ai_candidates(data)

        self.assertEqual(normalized["characters"][0]["name"], "赵明")
        self.assertEqual(normalized["characters"][0]["goal"], "查清旧案")
        self.assertEqual(normalized["lore"][0]["name"], "王城")
        self.assertEqual(normalized["foreshadows"][0]["name"], "虎符失踪")
        self.assertIn("旧案牵动三代人", normalized["project_materials"]["bible"])
        self.assertIn("缺页卷宗", normalized["project_materials"]["summary"])

    def test_normalize_ai_candidates_accepts_top_level_material_fields(self):
        data = {
            "characters": [],
            "小说圣经": "旧案牵动三代人。",
            "世界观规则": "王城贵族名册不可伪造。",
            "剧情时间线": "第一章旧案重启。",
            "故事摘要": "赵明拿到缺页卷宗。",
        }

        normalized = _normalize_ai_candidates(data)

        self.assertIn("旧案牵动三代人", normalized["project_materials"]["bible"])
        self.assertIn("贵族名册", normalized["project_materials"]["world_rules"])
        self.assertIn("第一章旧案重启", normalized["project_materials"]["timeline"])
        self.assertIn("缺页卷宗", normalized["project_materials"]["summary"])

    def test_normalize_ai_candidates_accepts_material_list_items(self):
        data = {
            "项目资料": [
                {"类型": "小说圣经", "内容": "旧案牵动三代人。"},
                {"类型": "世界观规则", "内容": "王城贵族名册不可伪造。"},
                {"名称": "剧情时间线", "说明": "第一章旧案重启。"},
                {"标题": "阶段摘要", "正文": "赵明拿到缺页卷宗。"},
            ],
        }

        normalized = _normalize_ai_candidates(data)

        self.assertIn("旧案牵动三代人", normalized["project_materials"]["bible"])
        self.assertIn("贵族名册", normalized["project_materials"]["world_rules"])
        self.assertIn("第一章旧案重启", normalized["project_materials"]["timeline"])
        self.assertIn("缺页卷宗", normalized["project_materials"]["summary"])

    def test_apply_import_candidates_merges_project_materials_and_clears_selected_values(self):
        project = {"bible": "已有圣经"}
        candidates = {
            "characters": [],
            "lore": [],
            "foreshadows": [],
            "project_materials": {
                "bible": "主线矛盾升级。",
                "world_rules": "",
                "timeline": "第1章旧案重启。",
                "summary": "",
            },
        }

        result = _apply_import_candidates(
            project,
            candidates,
            {"project_materials": ["bible", "timeline"]},
        )

        self.assertTrue(result["materials"]["bible"])
        self.assertTrue(result["materials"]["timeline"])
        self.assertIn("已有圣经", project["bible"])
        self.assertIn("主线矛盾升级", project["bible"])
        self.assertEqual(project["timeline"], "第1章旧案重启。")
        self.assertEqual(candidates["project_materials"]["bible"], "")
        self.assertEqual(candidates["project_materials"]["timeline"], "")

    def test_apply_import_candidates_dedupes_project_material_lines(self):
        repeated = "皇商账册缺页牵出旧案。"
        project = {
            "summary": f"{repeated}\n补充：{repeated}",
            "timeline": "第1章旧案重启。",
        }
        candidates = {
            "characters": [],
            "lore": [],
            "foreshadows": [],
            "project_materials": {
                "summary": f"{repeated}\n赵明拿到半枚虎符。",
                "timeline": "第1章旧案重启。\n第2章入城调查。",
            },
        }

        _apply_import_candidates(
            project,
            candidates,
            {"project_materials": ["summary", "timeline"]},
        )

        self.assertEqual(project["summary"].count(repeated), 1)
        self.assertIn("补充：赵明拿到半枚虎符。", project["summary"])
        self.assertEqual(project["timeline"].count("第1章旧案重启。"), 1)
        self.assertIn("补充：第2章入城调查。", project["timeline"])

    def test_apply_import_candidates_dedupes_repeated_character_notes(self):
        repeated = "允许赵国图继续陈述，最终决定和亲从长计议。"
        existing_only = "被赵国图称为临时奶来的李顺儿子；认可赵国图做得比预想更好。"
        new_line = "早朝准奏设立流民夜市。"
        project = {
            "characters": [
                {
                    "name": "皇上",
                    "role": "皇帝",
                    "goal": "",
                    "secret": "",
                    "voice": "",
                    "notes": f"{repeated}\n补充：{repeated}\n补充：{existing_only}",
                }
            ]
        }
        candidates = {
            "characters": [
                {
                    "name": "皇上",
                    "role": "",
                    "goal": "",
                    "secret": "",
                    "voice": "",
                    "notes": f"{repeated}\n{existing_only}\n{new_line}",
                }
            ],
            "lore": [],
            "foreshadows": [],
            "project_materials": {},
        }

        _apply_import_candidates(project, candidates, {"characters": [0]})

        notes = project["characters"][0]["notes"]
        self.assertEqual(notes.count(repeated), 1)
        self.assertEqual(notes.count(existing_only), 1)
        self.assertIn(f"补充：{new_line}", notes)

    def test_apply_import_candidates_merges_slash_alias_character_names(self):
        project = {
            "characters": [
                {
                    "name": "赵父",
                    "role": "赵图图之父，赵国公",
                    "goal": "",
                    "secret": "",
                    "voice": "",
                    "notes": "早期人物卡。",
                }
            ]
        }
        candidates = {
            "characters": [
                {
                    "name": "赵父 / 赵国公",
                    "role": "赵图图之父；赵国公",
                    "goal": "管教赵图图",
                    "secret": "",
                    "voice": "冷峻毒舌",
                    "notes": "后续补充。",
                }
            ],
            "lore": [],
            "foreshadows": [],
            "project_materials": {},
        }

        result = _apply_import_candidates(project, candidates, {"characters": [0]})

        self.assertEqual(len(project["characters"]), 1)
        self.assertEqual(project["characters"][0]["name"], "赵父")
        self.assertEqual(result["merged"]["characters"], 1)
        self.assertEqual(project["characters"][0]["goal"], "管教赵图图")
        self.assertIn("别称：赵父 / 赵国公", project["characters"][0]["notes"])
        self.assertIn("补充：后续补充。", project["characters"][0]["notes"])

    def test_normalize_project_dedupes_existing_character_notes(self):
        repeated = "允许赵国图继续陈述，最终决定和亲从长计议。"
        project = _normalize_project({
            "characters": [
                {
                    "name": "皇上",
                    "role": "皇帝",
                    "notes": f"{repeated}\n补充：{repeated}",
                }
            ]
        })

        self.assertEqual(project["characters"][0]["notes"].count(repeated), 1)

    def test_normalize_project_dedupes_existing_project_materials(self):
        repeated = "皇商账册缺页牵出旧案。"
        project = _normalize_project({
            "summary": f"{repeated}\n补充：{repeated}",
            "timeline": "第1章旧案重启。\n补充：第1章旧案重启。",
            "draft_note": "重复句。\n重复句。",
        })

        self.assertEqual(project["summary"].count(repeated), 1)
        self.assertEqual(project["timeline"].count("第1章旧案重启。"), 1)
        self.assertEqual(project["draft_note"].count("重复句。"), 2)

    def test_apply_import_candidates_dedupes_lore_and_foreshadow_descriptions(self):
        lore_line = "夜市只许低调经营一段时间。"
        foreshadow_line = "账册缺页后续牵出皇商。"
        project = {
            "lore": [
                {"name": "流民夜市", "type": "地点", "description": f"{lore_line}\n补充：{lore_line}"}
            ],
            "foreshadow_items": [
                {
                    "name": "账册缺页",
                    "status": "已埋",
                    "setup_chapter": "",
                    "payoff_chapter": "",
                    "description": f"{foreshadow_line}\n补充：{foreshadow_line}",
                }
            ],
        }
        candidates = {
            "characters": [],
            "lore": [
                {"name": "流民夜市", "type": "地点", "description": f"{lore_line}\n夜市由书院暗中担保。"}
            ],
            "foreshadows": [
                {"name": "账册缺页", "status": "已埋", "description": f"{foreshadow_line}\n牵出兵权交易。"}
            ],
            "project_materials": {},
        }

        _apply_import_candidates(project, candidates, {"lore": [0], "foreshadows": [0]})

        self.assertEqual(project["lore"][0]["description"].count(lore_line), 1)
        self.assertIn("补充：夜市由书院暗中担保。", project["lore"][0]["description"])
        self.assertEqual(project["foreshadow_items"][0]["description"].count(foreshadow_line), 1)
        self.assertIn("补充：牵出兵权交易。", project["foreshadow_items"][0]["description"])

    def test_apply_import_candidates_merges_lore_and_foreshadow_by_alias(self):
        project = {
            "lore": [
                {"name": "琉璃塔", "type": "地点", "description": "别称：白塔\n藏有旧案卷宗。"}
            ],
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "",
                    "payoff_chapter": "",
                    "description": "别称：半枚虎符\n牵出兵权。",
                }
            ],
        }
        candidates = {
            "characters": [],
            "lore": [
                {"name": "白塔", "type": "地点", "description": "塔顶有钟。"}
            ],
            "foreshadows": [
                {"name": "半枚虎符", "status": "已埋", "payoff_chapter": "第二十章", "description": "真相揭晓。"}
            ],
            "project_materials": {},
        }

        _apply_import_candidates(project, candidates, {"lore": [0], "foreshadows": [0]})

        self.assertEqual(len(project["lore"]), 1)
        self.assertEqual(project["lore"][0]["name"], "琉璃塔")
        self.assertIn("补充：塔顶有钟。", project["lore"][0]["description"])
        self.assertEqual(len(project["foreshadow_items"]), 1)
        self.assertEqual(project["foreshadow_items"][0]["name"], "虎符失踪")
        self.assertEqual(project["foreshadow_items"][0]["payoff_chapter"], "第二十章")
        self.assertIn("补充：真相揭晓。", project["foreshadow_items"][0]["description"])


if __name__ == "__main__":
    unittest.main()
