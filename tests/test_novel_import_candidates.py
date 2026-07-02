import unittest

from gpt_desktop.novel_import import (
    _apply_import_candidates,
    _candidate_analysis_dossier_text,
    _candidate_analysis_text,
    _foreshadow_review_chapter_chunks,
    _foreshadow_review_context,
    _foreshadow_review_dossier_text,
    _normalize_ai_candidates,
)
from gpt_desktop.novel_utils import _new_chapter, _normalize_project
from gpt_desktop.novel_utils import _sanitize_import_candidates_for_long_form


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

    def test_foreshadow_review_uses_existing_items_and_full_chapter_body(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第二章 真相"
        chapter["text"] = "赵明在内库发现调包记录，虎符失踪已经解释清楚。"
        chapter["summary"] = "赵明查明虎符失踪真相。"
        chapter["key_facts"] = "虎符失踪已经由内库调包解释清楚。"
        project = {
            "meta": {"title": "长篇测试"},
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第一章 旧案",
                    "payoff_chapter": "",
                    "description": "半枚虎符首次出现。",
                }
            ],
            "chapters": [chapter],
        }

        dossier = _foreshadow_review_dossier_text(project)
        chunks = _foreshadow_review_chapter_chunks(project)
        context = _foreshadow_review_context(project)

        self.assertIn("【现有伏笔列表】", dossier)
        self.assertIn("虎符失踪", dossier)
        self.assertEqual(len(chunks), 1)
        self.assertIn("当前章节标题：第二章 真相", chunks[0]["text"])
        self.assertNotIn("【现有伏笔列表】", chunks[0]["text"])
        self.assertIn("赵明在内库发现调包记录", chunks[0]["text"])
        self.assertNotIn("摘要：", chunks[0]["text"])
        self.assertNotIn("关键事实：", chunks[0]["text"])
        self.assertIn("【章节正文】", context)
        self.assertIn("赵明在内库发现调包记录", context)

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

    def test_candidate_analysis_dossier_keeps_lore_description_without_semantic_filtering(self):
        project = {
            "lore": [
                {
                    "name": "慕白资本",
                    "type": "势力",
                    "description": (
                        "慕白资本控制多条融资渠道，是沈家在资本布局中的核心工具，"
                        "本章中苏明宇将项目资料发往慕白资本邮箱，沈慕白追问泄露范围。"
                    ),
                }
            ]
        }

        dossier = _candidate_analysis_dossier_text(project)

        self.assertIn("慕白资本控制多条融资渠道", dossier)
        self.assertIn("发往慕白资本邮箱", dossier)
        self.assertIn("追问泄露范围", dossier)

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

    def test_normalize_ai_candidates_keeps_lore_description_without_semantic_filtering(self):
        data = {
            "lore": [
                {
                    "name": "慕白资本",
                    "type": "势力",
                    "description": (
                        "慕白资本控制多条融资渠道，是沈家在资本布局中的核心工具，"
                        "本章中苏明宇将项目资料发往慕白资本邮箱，沈慕白在危机爆发后追问泄露范围。"
                    ),
                }
            ],
        }

        normalized = _normalize_ai_candidates(data)

        description = normalized["lore"][0]["description"]
        self.assertIn("慕白资本控制多条融资渠道", description)
        self.assertIn("发往慕白资本邮箱", description)
        self.assertIn("追问泄露范围", description)

    def test_long_form_candidate_cleanup_keeps_ai_content_without_semantic_filtering(self):
        project = {
            "characters": [
                {"name": "沈慕白", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""}
            ],
            "lore": [
                {"name": "慕白资本", "type": "组织", "description": "核心组织"}
            ],
            "foreshadow_items": [
                {"name": "旧钟声", "status": "已埋", "setup_chapter": "第一章", "payoff_chapter": "", "description": ""}
            ],
            "chapters": [],
        }
        candidates = {
            "characters": [
                {
                    "name": "沈慕白",
                    "notes": "沈慕白对信息泄露极度敏感，会优先追查责任链。\n本章沈慕白追问泄露范围。",
                }
            ],
            "lore": [
                {
                    "name": "慕白资本",
                    "type": "组织",
                    "description": "慕白资本控制多条融资渠道，是沈家资本布局的核心工具。\n本章项目资料发往慕白资本邮箱。",
                }
            ],
            "foreshadows": [
                {
                    "name": "旧钟声",
                    "status": "未埋",
                    "description": "旧钟声代表密室开启，已埋，待在琉璃塔章节回收。\n本章又提到旧钟声。",
                }
            ],
            "project_materials": {},
        }

        cleaned, report = _sanitize_import_candidates_for_long_form(project, candidates)

        self.assertEqual(len(cleaned["characters"]), 1)
        self.assertIn("极度敏感", cleaned["characters"][0]["notes"])
        self.assertIn("追问泄露范围", cleaned["characters"][0]["notes"])
        self.assertEqual(len(cleaned["lore"]), 1)
        self.assertIn("控制多条融资渠道", cleaned["lore"][0]["description"])
        self.assertIn("发往慕白资本邮箱", cleaned["lore"][0]["description"])
        self.assertEqual(len(cleaned["foreshadows"]), 1)
        self.assertIn("代表密室开启", cleaned["foreshadows"][0]["description"])
        self.assertIn("本章又提到", cleaned["foreshadows"][0]["description"])
        self.assertEqual(report["trimmed"]["characters"], 0)
        self.assertEqual(report["trimmed"]["lore"], 0)
        self.assertEqual(report["trimmed"]["foreshadows"], 0)

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

    def test_apply_import_candidates_does_not_auto_merge_core_project_materials(self):
        project = {"bible": "已有圣经。", "world_rules": "已有规则。"}
        candidates = {
            "characters": [],
            "lore": [],
            "foreshadows": [],
            "project_materials": {
                "bible": "新主线矛盾。",
                "world_rules": "新世界规则。",
                "timeline": "第1章旧案重启。",
                "summary": "赵明拿到缺页卷宗。",
            },
        }

        result = _apply_import_candidates(project, candidates, {})

        self.assertNotIn("新主线矛盾", project["bible"])
        self.assertNotIn("新世界规则", project["world_rules"])
        self.assertIn("第1章旧案重启", project["timeline"])
        self.assertIn("缺页卷宗", project["summary"])
        self.assertFalse(result["materials"]["bible"])
        self.assertFalse(result["materials"]["world_rules"])
        self.assertTrue(result["materials"]["timeline"])
        self.assertTrue(result["materials"]["summary"])
        self.assertEqual(candidates["project_materials"]["bible"], "新主线矛盾。")
        self.assertEqual(candidates["project_materials"]["world_rules"], "新世界规则。")
        self.assertEqual(candidates["project_materials"]["timeline"], "")
        self.assertEqual(candidates["project_materials"]["summary"], "")

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

    def test_apply_import_candidates_keeps_lore_description_without_semantic_filtering(self):
        project = {
            "lore": [
                {
                    "name": "慕白资本",
                    "type": "势力",
                    "description": "表面体面，实际掌控多条资本渠道。",
                }
            ]
        }
        candidates = {
            "characters": [],
            "lore": [
                {
                    "name": "慕白资本",
                    "type": "势力",
                    "description": (
                        "慕白资本控制多条融资渠道，是沈家在资本布局中的核心工具，"
                        "本章中苏明宇将项目资料发往慕白资本邮箱，沈慕白追问泄露范围。"
                    ),
                }
            ],
            "foreshadows": [],
            "project_materials": {},
        }

        _apply_import_candidates(project, candidates, {"lore": [0]})

        description = project["lore"][0]["description"]
        self.assertIn("补充：慕白资本控制多条融资渠道", description)
        self.assertIn("发往慕白资本邮箱", description)
        self.assertIn("追问泄露范围", description)

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

    def test_apply_import_candidates_limits_foreshadow_description_supplements(self):
        project = {
            "foreshadow_items": [
                {
                    "name": "旧钟声",
                    "status": "已埋",
                    "setup_chapter": "第一章",
                    "payoff_chapter": "",
                    "description": "钟声提示旧案未结。\n补充：第一章：钟声在夜里响起。\n补充：第二章：钟声又在王城出现。",
                }
            ],
        }
        candidates = {
            "characters": [],
            "lore": [],
            "foreshadows": [
                {
                    "name": "旧钟声",
                    "payoff_chapter": "第三章",
                    "description": "赵明确认钟声来自旧案密室。\n章节依据：第三章打开密室。",
                }
            ],
            "project_materials": {},
        }

        _apply_import_candidates(project, candidates, {"foreshadows": [0]})

        description = project["foreshadow_items"][0]["description"]
        self.assertEqual(description.count("补充："), 2)
        self.assertIn("补充：第一章：钟声在夜里响起。", description)
        self.assertIn("补充：第三章：赵明确认钟声来自旧案密室。；章节依据：第三章打开密室。", description)
        self.assertNotIn("第二章：钟声又在王城出现。", description)

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
        self.assertIn("补充：第二十章：真相揭晓。", project["foreshadow_items"][0]["description"])

    def test_apply_import_candidates_keeps_existing_foreshadow_status_without_explicit_candidate_status(self):
        project = {
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第二章",
                    "payoff_chapter": "",
                    "description": "半枚虎符首次出现。",
                }
            ]
        }
        candidates = _normalize_ai_candidates({
            "foreshadows": [
                {
                    "name": "虎符失踪",
                    "description": "后续牵出兵权交易。",
                }
            ]
        })

        _apply_import_candidates(project, candidates, {"foreshadows": [0]})

        self.assertEqual(project["foreshadow_items"][0]["status"], "已埋")
        self.assertIn("后续牵出兵权交易", project["foreshadow_items"][0]["description"])

    def test_apply_import_candidates_updates_explicit_foreshadow_recovery(self):
        project = {
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第二章",
                    "payoff_chapter": "",
                    "description": "半枚虎符首次出现。",
                }
            ]
        }
        candidates = _normalize_ai_candidates({
            "foreshadows": [
                {
                    "name": "虎符失踪",
                    "status": "已回收",
                    "payoff_chapter": "第十二章 真相",
                    "description": "本章揭晓虎符失踪真相，确认牵出兵权交易。",
                }
            ]
        })

        _apply_import_candidates(project, candidates, {"foreshadows": [0]})

        self.assertEqual(project["foreshadow_items"][0]["status"], "已回收")
        self.assertEqual(project["foreshadow_items"][0]["payoff_chapter"], "第十二章 真相")
        self.assertIn("揭晓虎符失踪真相", project["foreshadow_items"][0]["description"])

    def test_apply_import_candidates_updates_foreshadow_by_review_merge_target(self):
        project = {
            "foreshadow_items": [
                {
                    "code": "F0007",
                    "name": "雨后状态",
                    "status": "已埋",
                    "setup_chapter": "第八章",
                    "payoff_chapter": "",
                    "description": "第八章结尾已经进入雨后。",
                }
            ]
        }
        candidates = _normalize_ai_candidates({
            "foreshadows": [
                {
                    "name": "第九章不应再次下雨",
                    "status": "已回收",
                    "payoff_chapter": "第九章",
                    "description": "第九章开头重复写雨水，应按第八章雨后状态修正。",
                    "merge_target": "雨后状态",
                    "review_action": "更新状态",
                    "review_reason": "命中旧伏笔的天气连续性。",
                }
            ]
        })

        result = _apply_import_candidates(project, candidates, {"foreshadows": [0]})

        self.assertEqual(len(project["foreshadow_items"]), 1)
        self.assertEqual(project["foreshadow_items"][0]["name"], "雨后状态")
        self.assertEqual(project["foreshadow_items"][0]["status"], "已回收")
        self.assertEqual(project["foreshadow_items"][0]["payoff_chapter"], "")
        self.assertEqual(project["foreshadow_items"][0]["description"], "第八章结尾已经进入雨后。")
        self.assertNotIn("重复写雨水", project["foreshadow_items"][0]["description"])
        self.assertNotIn("别称：第九章不应再次下雨", project["foreshadow_items"][0]["description"])
        self.assertEqual(result["added"]["foreshadows"], 0)
        self.assertEqual(result["merged"]["foreshadows"], 1)
        self.assertEqual(result["removed_candidates"], 1)
        self.assertIn("命中编号：F0007", project["foreshadow_items"][0]["notes"])
        self.assertIn("原伏笔标题：雨后状态", project["foreshadow_items"][0]["notes"])
        self.assertIn("建议状态：已回收", project["foreshadow_items"][0]["notes"])
        self.assertIn("建议说明：第九章开头重复写雨水", project["foreshadow_items"][0]["notes"])

    def test_apply_import_candidates_keeps_unmatched_review_target_as_candidate(self):
        project = {
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第二章",
                    "payoff_chapter": "",
                    "description": "半枚虎符首次出现。",
                }
            ]
        }
        candidates = _normalize_ai_candidates({
            "foreshadows": [
                {
                    "name": "陌生线索",
                    "status": "已回收",
                    "description": "AI 认为应更新旧伏笔，但目标名当前不存在。",
                    "merge_target": "不存在的旧伏笔",
                    "review_action": "更新状态",
                }
            ]
        })

        result = _apply_import_candidates(project, candidates, {"foreshadows": [0]})

        self.assertEqual(len(project["foreshadow_items"]), 1)
        self.assertEqual(project["foreshadow_items"][0]["name"], "虎符失踪")
        self.assertEqual(len(candidates["foreshadows"]), 1)
        self.assertEqual(result["added"]["foreshadows"], 0)
        self.assertEqual(result["merged"]["foreshadows"], 0)
        self.assertEqual(result["removed_candidates"], 0)
        self.assertEqual(result["skipped"]["foreshadows"], 1)

    def test_apply_import_candidates_updates_foreshadow_by_target_code(self):
        project = {
            "foreshadow_items": [
                {
                    "code": "F0007",
                    "name": "雨后状态",
                    "status": "已埋",
                    "setup_chapter": "第八章",
                    "payoff_chapter": "",
                    "description": "第八章结尾已经进入雨后。",
                }
            ]
        }
        candidates = _normalize_ai_candidates({
            "foreshadows": [
                {
                    "name": "第九章不应再次下雨",
                    "status": "已回收",
                    "payoff_chapter": "第九章",
                    "description": "第九章开头重复写雨水，应按编号命中旧伏笔修正。",
                    "target_code": "F0007",
                    "review_action": "更新状态",
                }
            ]
        })

        _apply_import_candidates(project, candidates, {"foreshadows": [0]})

        self.assertEqual(project["foreshadow_items"][0]["status"], "已回收")
        self.assertEqual(project["foreshadow_items"][0]["payoff_chapter"], "")
        self.assertEqual(project["foreshadow_items"][0]["description"], "第八章结尾已经进入雨后。")
        self.assertIn("命中编号：F0007", project["foreshadow_items"][0]["notes"])
        self.assertIn("原伏笔标题：雨后状态", project["foreshadow_items"][0]["notes"])

    def test_apply_import_candidates_keeps_terminal_review_note_to_first_batch(self):
        project = {
            "foreshadow_items": [
                {
                    "code": "F0055",
                    "name": "陈景川与陈远山景辰总部正面交锋",
                    "status": "已埋",
                    "setup_chapter": "章节 4",
                    "payoff_chapter": "",
                    "description": "预设二人在景辰总部正面交锋。",
                }
            ]
        }
        candidates = _normalize_ai_candidates({
            "foreshadows": [
                {
                    "name": "陈景川与陈远山景辰总部正面交锋",
                    "status": "废弃",
                    "description": (
                        "原伏笔预设交锋场域为景辰京城总部，但正文实际推进为陈家老宅家族会议。\n"
                        "体检建议：移出伏笔\n"
                        "合并目标：陈家老宅权限边界会议\n"
                        "判断依据：旧伏笔与 F0065 明显重复且场域已被正文修正。\n"
                        "章节依据：章节 7 与章节 8。\n"
                        "补充：体检建议：更新状态\n"
                        "补充：命中编号：F0065\n"
                        "补充：判断依据：章节 8 中另一个规范伏笔已经回收。"
                    ),
                    "target_code": "F0055",
                    "review_action": "移出伏笔",
                    "merge_target": "陈家老宅权限边界会议",
                }
            ]
        })

        _apply_import_candidates(project, candidates, {"foreshadows": [0]})

        notes = project["foreshadow_items"][0]["notes"]
        self.assertEqual(project["foreshadow_items"][0]["status"], "废弃")
        self.assertIn("命中编号：F0055", notes)
        self.assertIn("建议状态：废弃", notes)
        self.assertIn("体检建议：移出伏笔", notes)
        self.assertIn("合并目标：陈家老宅权限边界会议", notes)
        self.assertNotIn("命中编号：F0065", notes)
        self.assertNotIn("另一个规范伏笔已经回收", notes)

    def test_foreshadow_move_out_review_action_defaults_to_discard_status(self):
        project = {
            "foreshadow_items": [
                {
                    "code": "F0021",
                    "name": "旧总部交锋",
                    "status": "已埋",
                    "setup_chapter": "章节 3",
                    "payoff_chapter": "",
                    "description": "原计划在总部发生正面交锋。",
                }
            ]
        }
        candidates = _normalize_ai_candidates({
            "foreshadows": [
                {
                    "name": "旧总部交锋",
                    "description": "正文已经改为陈家老宅会议，不再作为长期伏笔保留。",
                    "target_code": "F0021",
                    "review_action": "移出伏笔",
                }
            ]
        })

        item = candidates["foreshadows"][0]
        self.assertEqual(item["status"], "废弃")
        self.assertTrue(item.get("_status_explicit"))

        _apply_import_candidates(project, candidates, {"foreshadows": [0]})

        target = project["foreshadow_items"][0]
        self.assertEqual(target["status"], "废弃")
        self.assertEqual(target["description"], "原计划在总部发生正面交锋。")
        self.assertIn("命中编号：F0021", target["notes"])
        self.assertIn("建议状态：废弃", target["notes"])
        self.assertIn("体检建议：移出伏笔", target["notes"])

    def test_apply_import_candidates_skips_closed_foreshadow_review_target(self):
        for closed_status in ("已回收", "废弃"):
            with self.subTest(closed_status=closed_status):
                project = {
                    "foreshadow_items": [
                        {
                            "code": "F0007",
                            "name": "雨后状态",
                            "status": closed_status,
                            "setup_chapter": "第八章",
                            "payoff_chapter": "第九章",
                            "description": "第八章结尾已经进入雨后。",
                        }
                    ]
                }
                candidates = _normalize_ai_candidates({
                    "foreshadows": [
                        {
                            "name": "第十章又写雨水",
                            "status": "已回收",
                            "description": "第十章再次命中旧伏笔，但该伏笔已经关闭。",
                            "target_code": "F0007",
                            "review_action": "更新状态",
                        }
                    ]
                })

                result = _apply_import_candidates(project, candidates, {"foreshadows": [0]})

                item = project["foreshadow_items"][0]
                self.assertEqual(item["status"], closed_status)
                self.assertEqual(item["description"], "第八章结尾已经进入雨后。")
                self.assertNotIn("notes", item)
                self.assertEqual(len(candidates["foreshadows"]), 0)
                self.assertEqual(result["merged"]["foreshadows"], 0)
                self.assertEqual(result["removed_candidates"], 1)

    def test_foreshadow_review_dossier_uses_stable_codes(self):
        project = {
            "foreshadow_items": [
                {"code": "F0007", "name": "雨后状态", "status": "已埋", "description": "雨后。"}
            ]
        }
        dossier = _foreshadow_review_dossier_text(project)

        self.assertIn("编号：F0007", dossier)
        self.assertIn("名称：雨后状态", dossier)
        self.assertNotIn("1.", dossier)

    def test_apply_import_candidates_does_not_downgrade_recovered_foreshadow(self):
        project = {
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已回收",
                    "setup_chapter": "第二章",
                    "payoff_chapter": "第十二章",
                    "description": "真相已经揭晓。",
                }
            ]
        }
        candidates = _normalize_ai_candidates({
            "foreshadows": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "description": "再次提到虎符。",
                }
            ]
        })

        _apply_import_candidates(project, candidates, {"foreshadows": [0]})

        self.assertEqual(project["foreshadow_items"][0]["status"], "已回收")
        self.assertIn("再次提到虎符", project["foreshadow_items"][0]["description"])

    def test_ai_foreshadow_candidate_without_status_stays_unjudged_until_new_import(self):
        candidates = _normalize_ai_candidates({
            "foreshadows": [
                {
                    "name": "半枚虎符",
                    "description": "后续牵出兵权交易。",
                }
            ]
        })

        self.assertEqual(candidates["foreshadows"][0]["status"], "")
        self.assertFalse(candidates["foreshadows"][0].get("_status_explicit"))

        project = {"foreshadow_items": []}
        _apply_import_candidates(project, candidates, {"foreshadows": [0]})

        self.assertEqual(project["foreshadow_items"][0]["status"], "未埋")
        self.assertIn("后续牵出兵权交易", project["foreshadow_items"][0]["description"])

    def test_foreshadow_review_metadata_is_kept_in_candidate_description(self):
        candidates = _normalize_ai_candidates({
            "foreshadows": [
                {
                    "name": "虎符失踪",
                    "status": "已回收",
                    "payoff_chapter": "第二章 真相",
                    "description": "真相已经揭晓。",
                    "review_action": "更新状态",
                    "review_reason": "正文已解释虎符失踪原因。",
                    "evidence": "第二章 真相",
                }
            ]
        })

        item = candidates["foreshadows"][0]

        self.assertEqual(item["status"], "已回收")
        self.assertTrue(item.get("_status_explicit"))
        self.assertIn("体检建议：更新状态", item["description"])
        self.assertIn("判断依据：正文已解释虎符失踪原因。", item["description"])
        self.assertIn("章节依据：第二章 真相", item["description"])

    def test_foreshadow_review_target_code_prevents_cross_target_candidate_merge(self):
        candidates = _normalize_ai_candidates({
            "foreshadows": [
                {
                    "name": "陈景川与陈远山景辰总部正面交锋",
                    "status": "废弃",
                    "description": "总部交锋场域已被正文修正。",
                    "target_code": "F0055",
                    "merge_target": "陈家老宅权限边界会议",
                    "review_action": "移出伏笔",
                },
                {
                    "name": "陈家老宅权限边界会议",
                    "status": "已回收",
                    "description": "家族会议已正式发生。",
                    "target_code": "F0065",
                    "review_action": "更新状态",
                },
            ]
        })

        self.assertEqual(len(candidates["foreshadows"]), 2)
        by_code = {item.get("_target_code"): item for item in candidates["foreshadows"]}
        self.assertIn("F0055", by_code)
        self.assertIn("F0065", by_code)
        self.assertNotIn("家族会议已正式发生", by_code["F0055"]["description"])

    def test_foreshadow_review_keeps_earliest_terminal_chapter(self):
        candidates = _normalize_ai_candidates({
            "foreshadows": [
                {
                    "name": "陈景川与陈远山景辰总部正面交锋",
                    "status": "废弃",
                    "description": "第九章后续再次提到该旧线索。",
                    "target_code": "F0055",
                    "review_action": "移出伏笔",
                    "evidence": "第九章",
                },
                {
                    "name": "陈景川与陈远山景辰总部正面交锋",
                    "status": "废弃",
                    "description": "章节 7 首次证明总部交锋场域已被正文修正。",
                    "target_code": "F0055",
                    "review_action": "移出伏笔",
                    "evidence": "章节 7 陈家老宅通知",
                },
            ]
        })

        self.assertEqual(len(candidates["foreshadows"]), 1)
        item = candidates["foreshadows"][0]
        self.assertIn("章节 7", item["description"])
        self.assertNotIn("第九章后续", item["description"])


if __name__ == "__main__":
    unittest.main()
