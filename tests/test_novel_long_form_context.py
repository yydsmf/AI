import unittest

from gpt_desktop.novel_utils import (
    _build_chapter_ai_context,
    _build_foreshadow_notes_draft,
    _build_project_summary_draft,
    _build_project_timeline_draft,
    _build_writing_check_text,
    _infer_foreshadow_status,
    _new_chapter,
)


class NovelLongFormContextTests(unittest.TestCase):
    def _project_with_current_chapter(self, current):
        return {
            "meta": {
                "title": "长篇测试",
                "genre": "古言",
                "style": "细腻",
                "pov": "第三人称",
                "target_words": "20万",
                "premise": "主角在权谋漩涡中查清旧案。",
            },
            "bible": "核心设定：旧案牵动三代人。",
            "world_rules": "规则：贵族名册不可伪造。",
            "timeline": "第1章旧案重启。",
            "summary": "阶段总结：主角已经进入王城。",
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "chapters": [current],
        }

    def _context_section(self, context, title):
        marker = f"【{title}】\n"
        start = context.find(marker)
        self.assertNotEqual(start, -1, f"missing context section: {title}")
        start += len(marker)
        end = context.find("\n\n【", start)
        return context[start:] if end < 0 else context[start:end]

    def test_outline_context_requests_compact_outline(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入城"
        current["text"] = "赵明在城门外看见旧案告示。"
        project = self._project_with_current_chapter(current)

        context = _build_chapter_ai_context(project, 0, "outline")

        self.assertIn("只输出短提纲", context)
        self.assertIn("6-10 条", context)
        self.assertIn("600-1200 字", context)
        self.assertIn("不要输出正文、对白或长段场景描写", context)
        self.assertIn("正文草稿为唯一事实来源", context)
        self.assertIn("正文没发生", context)

    def test_outline_and_summary_context_do_not_include_future_boundary_when_body_exists(self):
        current = _new_chapter(0)
        current["title"] = "第一章 半枚虎符"
        current["outline"] = "主角拿到半枚虎符，后续第二章才追查来源。"
        current["text"] = "赵明只在门缝里看见半枚虎符。"
        future = _new_chapter(1)
        future["title"] = "第二章 虎符来源"
        future["outline"] = "第二章才揭晓虎符来自旧案内鬼。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, future]

        outline_context = _build_chapter_ai_context(project, 0, "outline")
        summary_context = _build_chapter_ai_context(project, 0, "summary")

        self.assertNotIn("【后续规划 / 边界】", outline_context)
        self.assertNotIn("第二章才揭晓虎符来自旧案内鬼", outline_context)
        self.assertIn("正文没有写到的内容不要写入摘要或关键事实", summary_context)
        self.assertNotIn("【后续规划 / 边界】", summary_context)
        self.assertNotIn("第二章才揭晓虎符来自旧案内鬼", summary_context)

    def test_chapter_context_prioritizes_linked_character_beyond_first_batch(self):
        current = _new_chapter(0)
        current["title"] = "第四十一章 风雪夜谈"
        current["outline"] = "主角向迟到主角追问旧案。"
        current["linked_characters"] = ["迟到主角"]
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {"name": f"路人{i}", "role": "过场人物", "goal": "", "secret": "", "voice": "", "notes": ""}
            for i in range(35)
        ]
        project["characters"].append({
            "name": "迟到主角",
            "role": "旧案关键证人",
            "goal": "保住证据",
            "secret": "知道名册被换过",
            "voice": "说话谨慎",
            "notes": "本章必须出现",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关人物】", context)
        self.assertIn("迟到主角", context)
        self.assertIn("旧案关键证人", context)
        self.assertNotIn("路人0", context)

    def test_chapter_draft_words_controls_draft_prompt_without_using_project_total(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入城"
        current["outline"] = "主角入城调查旧案。"
        current["draft_words"] = "3000"
        project = self._project_with_current_chapter(current)
        project["meta"]["target_words"] = "20万"

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章写作长度】", context)
        self.assertIn("本章扩写字数：3000字", context)
        self.assertIn("本次新增正文参考目标：约3000字", context)
        self.assertIn("软性参考目标", context)
        self.assertIn("不是硬性字数要求", context)
        self.assertIn("优先保证完整小场景、冲突收束、人物反应和正文质量", context)
        self.assertIn("不要为了贴字数牺牲完整场景", context)
        self.assertIn("可以略高或略低于目标", context)
        self.assertNotIn("2970-3150字", context)
        self.assertNotIn("严格长度约束", context)
        self.assertIn("项目总目标字数：20万字", context)
        self.assertIn("不要把项目总字数当作单章输出字数", context)

    def test_blank_chapter_draft_words_does_not_expand_to_project_total(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入城"
        current["outline"] = "主角入城调查旧案。"
        project = self._project_with_current_chapter(current)
        project["meta"]["target_words"] = "1万"

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("本章扩写字数：未填写", context)
        self.assertIn("不要根据项目总目标字数一次性写满", context)
        self.assertIn("项目总目标字数：1万字", context)

    def test_chapter_draft_words_uses_remaining_words_after_existing_body(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入城"
        current["outline"] = "主角入城调查旧案。"
        current["draft_words"] = "5000"
        current["text"] = "甲" * 2000
        project = self._project_with_current_chapter(current)

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("本章扩写字数：5000字", context)
        self.assertIn("当前正文长度：约2000字", context)
        self.assertIn("本次新增正文参考目标：约3000字", context)
        self.assertIn("软性参考目标", context)
        self.assertIn("不是硬性字数要求", context)
        self.assertNotIn("2970-3150字", context)

    def test_chapter_context_ignores_core_role_words_without_exact_character_name(self):
        current = _new_chapter(0)
        current["title"] = "第十二章 入城"
        current["outline"] = "主角入城调查，反派暗中设局。"
        current["linked_characters"] = []
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {"name": f"路人{i}", "role": "过场人物", "goal": "", "secret": "", "voice": "", "notes": ""}
            for i in range(35)
        ]
        project["characters"].extend([
            {
                "name": "赵明",
                "role": "主角",
                "goal": "查清旧案",
                "secret": "不知道父亲曾改过证词",
                "voice": "克制直接",
                "notes": "",
            },
            {
                "name": "沈砚",
                "role": "反派",
                "goal": "阻止旧案翻出真相",
                "secret": "",
                "voice": "温和但带压迫感",
                "notes": "",
            },
        ])

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关人物】", context)
        current_section = self._context_section(context, "当前章节")
        character_section = self._context_section(context, "本章相关人物")
        self.assertIn("关联人物：", current_section)
        self.assertNotIn("关联人物：赵明", current_section)
        self.assertNotIn("赵明", character_section)
        self.assertNotIn("查清旧案", character_section)
        self.assertNotIn("沈砚", character_section)
        self.assertNotIn("阻止旧案翻出真相", character_section)
        self.assertNotIn("路人0", context)

    def test_chapter_context_prioritizes_relevant_lore_and_foreshadow(self):
        current = _new_chapter(0)
        current["title"] = "第四十六章 旧钟再响"
        current["outline"] = "主角进入琉璃塔，听见密室钟声。"
        project = self._project_with_current_chapter(current)
        project["lore"] = [
            {"name": f"普通地点{i}", "type": "地点", "description": "无关地点"}
            for i in range(45)
        ]
        project["lore"].append({
            "name": "琉璃塔",
            "type": "地点",
            "description": "旧案档案被藏在塔顶。",
        })
        project["foreshadow_items"] = [
            {
                "name": f"旧线索{i}",
                "status": "已回收",
                "setup_chapter": "第1章",
                "payoff_chapter": "第2章",
                "description": "已经处理。",
            }
            for i in range(45)
        ]
        project["foreshadow_items"].append({
            "name": "旧钟声",
            "status": "已埋",
            "setup_chapter": "第3章",
            "payoff_chapter": "第四十六章",
            "description": "钟声响起表示密室开启。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关设定】", context)
        self.assertIn("琉璃塔", context)
        self.assertNotIn("普通地点0", context)
        self.assertIn("【本章相关伏笔】", context)
        self.assertIn("旧钟声", context)
        self.assertNotIn("旧线索0", context)

    def test_chapter_context_ignores_generic_stage_terms_without_exact_lore_name(self):
        current = _new_chapter(0)
        current["title"] = "第二十一章 回城"
        current["outline"] = "主角回到主舞台，在朝堂继续调查旧案。"
        project = self._project_with_current_chapter(current)
        project["lore"] = [
            {"name": f"普通地点{i}", "type": "地点", "description": "偏远地点，暂不影响主线。"}
            for i in range(35)
        ]
        project["lore"].append({
            "name": "王城",
            "type": "地点",
            "description": "故事主舞台，朝堂和旧案卷宗都在这里交汇。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关设定】", context)
        lore_section = self._context_section(context, "本章相关设定")
        self.assertNotIn("王城", lore_section)
        self.assertNotIn("故事主舞台", lore_section)
        self.assertNotIn("普通地点0", lore_section)

    def test_chapter_context_dedupes_reference_notes_without_touching_body_repetition(self):
        current = _new_chapter(0)
        current["title"] = "第十章 重复资料"
        current["outline"] = "赵明进入琉璃塔，准备回收虎符失踪。"
        current["text"] = "重复对白。\n重复对白。"
        current["summary"] = "摘要唯一事实。\n补充：摘要唯一事实。"
        current["key_facts"] = "关键唯一事实。\n补充：关键唯一事实。"
        project = self._project_with_current_chapter(current)
        project["bible"] = "圣经唯一事实。\n补充：圣经唯一事实。"
        project["world_rules"] = "规则唯一事实。\n补充：规则唯一事实。"
        project["characters"] = [
            {
                "name": "赵明",
                "role": "主角",
                "goal": "查清旧案",
                "secret": "",
                "voice": "",
                "notes": "人物唯一备注。\n补充：人物唯一备注。",
            }
        ]
        project["lore"] = [
            {
                "name": "琉璃塔",
                "type": "地点",
                "description": "设定唯一说明。\n补充：设定唯一说明。",
            }
        ]
        project["foreshadow_items"] = [
            {
                "name": "虎符失踪",
                "status": "已埋",
                "setup_chapter": "",
                "payoff_chapter": "",
                "description": "伏笔唯一说明。\n补充：伏笔唯一说明。",
            }
        ]

        context = _build_chapter_ai_context(project, 0, "draft")

        for duplicated_line in (
            "圣经唯一事实。",
            "规则唯一事实。",
            "摘要唯一事实。",
            "关键唯一事实。",
            "人物唯一备注。",
            "设定唯一说明。",
            "伏笔唯一说明。",
        ):
            self.assertNotIn(f"补充：{duplicated_line}", context)
        self.assertEqual(context.count("圣经唯一事实。"), 1)
        self.assertEqual(context.count("规则唯一事实。"), 1)
        self.assertEqual(context.count("人物唯一备注。"), 1)
        self.assertEqual(context.count("伏笔唯一说明。"), 1)
        self.assertGreaterEqual(context.count("重复对白。"), 2)

    def test_chapter_context_prioritizes_payoff_keyword_foreshadow(self):
        current = _new_chapter(0)
        current["title"] = "第二十章 虎符真相"
        current["outline"] = "本章回收虎符失踪，揭晓兵权旧案。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": f"背景线索{i}",
                "status": "已埋",
                "setup_chapter": "第1章",
                "payoff_chapter": "",
                "description": "后续处理。",
            }
            for i in range(40)
        ]
        project["foreshadow_items"].append({
            "name": "虎符失踪",
            "status": "已埋",
            "setup_chapter": "第2章",
            "payoff_chapter": "",
            "description": "牵出兵权。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关伏笔】", context)
        self.assertIn("虎符失踪", context)
        self.assertIn("牵出兵权", context)
        self.assertNotIn("背景线索0", context)

    def test_chapter_context_keeps_global_foreshadow_queue_with_matched_item(self):
        current = _new_chapter(0)
        current["title"] = "第二十章 虎符真相"
        current["outline"] = "本章回收虎符失踪，揭晓兵权旧案。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": "虎符失踪",
                "status": "已埋",
                "setup_chapter": "第2章",
                "payoff_chapter": "第二十章",
                "description": "牵出兵权。",
            },
            {
                "name": "密室旧钟",
                "status": "已埋",
                "setup_chapter": "第3章",
                "payoff_chapter": "第二十五章",
                "description": "后续开启地底密室。",
            },
        ]

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关伏笔】", context)
        self.assertIn("虎符失踪", context)
        self.assertIn("开放伏笔队列", context)
        self.assertIn("密室旧钟", context)

    def test_chapter_context_prioritizes_actionable_open_foreshadow_queue(self):
        current = _new_chapter(0)
        current["title"] = "第十章 暂避锋芒"
        current["outline"] = "本章处理人物关系，不直接回收伏笔。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": f"背景待处理{i}",
                "status": "已埋",
                "setup_chapter": "",
                "payoff_chapter": "",
                "description": "普通背景线索，暂不影响主线。",
            }
            for i in range(20)
        ]
        project["foreshadow_items"].append({
            "name": "终局密钥",
            "status": "已埋",
            "setup_chapter": "第九章",
            "payoff_chapter": "第二十五章",
            "description": "关系最终真相，不能遗忘。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("开放伏笔队列", context)
        self.assertIn("终局密钥", context)
        self.assertIn("关系最终真相", context)
        self.assertLess(context.index("终局密钥"), context.index("背景待处理0"))

    def test_chapter_context_prioritizes_due_open_foreshadow_queue(self):
        current = _new_chapter(39)
        current["title"] = "第四十章 风雪夜谈"
        current["outline"] = "本章处理人物关系，不直接回收伏笔。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": f"普通伏笔{i}",
                "status": "已埋",
                "setup_chapter": "第1章",
                "payoff_chapter": "",
                "description": "普通背景线索，暂不影响主线。",
            }
            for i in range(20)
        ]
        project["foreshadow_items"].append({
            "name": "临近回收伏笔",
            "status": "已埋",
            "setup_chapter": "第5章",
            "payoff_chapter": "第四十一章",
            "description": "临近当前章节，应该优先提醒。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("开放伏笔队列", context)
        self.assertIn("不要无计划回收", context)
        self.assertIn("临近回收伏笔", context)
        self.assertLess(context.index("临近回收伏笔"), context.index("普通伏笔0"))

    def test_chapter_context_prioritizes_foreshadow_alias_from_description(self):
        current = _new_chapter(0)
        current["title"] = "第十二章 密室开启"
        current["outline"] = "本章揭晓密室钟声，回收塔顶暗门线索。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": f"背景线索{i}",
                "status": "已埋",
                "setup_chapter": "第1章",
                "payoff_chapter": "",
                "description": "后续处理。",
            }
            for i in range(40)
        ]
        project["foreshadow_items"].append({
            "name": "旧钟声",
            "status": "已埋",
            "setup_chapter": "第3章",
            "payoff_chapter": "",
            "description": "别称：密室钟声。钟声响起表示暗门开启。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关伏笔】", context)
        self.assertIn("旧钟声", context)
        self.assertIn("密室钟声", context)

    def test_chapter_context_prioritizes_foreshadow_extended_alias_labels(self):
        current = _new_chapter(0)
        current["title"] = "第二十章 虎符真相"
        current["outline"] = "本章回收玄铁令，揭晓兵权旧案。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": f"背景线索{i}",
                "status": "已埋",
                "setup_chapter": "第1章",
                "payoff_chapter": "",
                "description": "后续处理。",
            }
            for i in range(40)
        ]
        project["foreshadow_items"].append({
            "name": "虎符失踪",
            "status": "已埋",
            "setup_chapter": "第3章",
            "payoff_chapter": "",
            "description": "代号：玄铁令。真名：半枚虎符。牵出兵权交易。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关伏笔】", context)
        self.assertIn("虎符失踪", context)
        self.assertIn("玄铁令", context)
        self.assertNotIn("背景线索0", context)

    def test_chapter_context_prioritizes_character_honorific_aliases(self):
        current = _new_chapter(0)
        current["title"] = "第四十一章 暗阁旧卷"
        current["outline"] = "少主命阁主先生交出旧案卷宗。"
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {"name": f"路人{i}", "role": "过场人物", "goal": "", "secret": "", "voice": "", "notes": ""}
            for i in range(35)
        ]
        project["characters"].append({
            "name": "迟到主角",
            "role": "旧案证人",
            "goal": "保住旧卷",
            "secret": "知道名册被换过",
            "voice": "谨慎克制",
            "notes": "尊称：阁主先生\n头衔：少主",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关人物】", context)
        self.assertIn("迟到主角", context)
        self.assertIn("保住旧卷", context)
        self.assertNotIn("路人0", context)

    def test_chapter_context_splits_slash_alias_values(self):
        current = _new_chapter(0)
        current["title"] = "第四十一章 暗阁旧卷"
        current["outline"] = "阁主先生交出旧案卷宗。"
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {"name": f"路人{i}", "role": "过场人物", "goal": "", "secret": "", "voice": "", "notes": ""}
            for i in range(35)
        ]
        project["characters"].append({
            "name": "迟到主角",
            "role": "旧案证人",
            "goal": "保住旧卷",
            "secret": "知道名册被换过",
            "voice": "谨慎克制",
            "notes": "代号：玄鸦/阁主先生/少主",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关人物】", context)
        self.assertIn("迟到主角", context)
        self.assertIn("保住旧卷", context)
        self.assertNotIn("路人0", context)

    def test_chapter_context_keeps_old_facts_and_recent_summaries(self):
        chapters = []
        for index in range(60):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"近期摘要 {index + 1}"
            chapter["key_facts"] = f"早期事实 {index + 1}"
            chapters.append(chapter)
        current = _new_chapter(60)
        current["title"] = "章节61"
        current["outline"] = "收束旧案第一阶段。"
        chapters.append(current)
        project = self._project_with_current_chapter(current)
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 60, "draft")

        self.assertLessEqual(len(context), 56000)
        self.assertIn("【前文继承摘要】", context)
        self.assertIn("远期关键事实", context)
        self.assertIn("早期事实 1", context)
        self.assertIn("近期摘要 60", context)

    def test_chapter_context_previous_summary_keeps_mid_story_milestones(self):
        chapters = []
        for index in range(80):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"日常推进 {index + 1}。"
            chapter["key_facts"] = f"阶段事实 {index + 1}。"
            chapters.append(chapter)
        chapters[34]["title"] = "第三十五章 虎符真相"
        chapters[34]["summary"] = "虎符真相揭晓，旧案内鬼露出破绽。"
        chapters[34]["key_facts"] = "虎符失踪伏笔部分回收。"
        current = _new_chapter(80)
        current["title"] = "第八十一章 终局门前"
        current["outline"] = "主角整理旧案证据。"
        chapters.append(current)
        project = self._project_with_current_chapter(current)
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 80, "draft")

        self.assertIn("【前文继承摘要】", context)
        self.assertIn("历史关键转折锚点", context)
        self.assertIn("虎符真相揭晓", context)
        self.assertIn("近期章节（优先继承）", context)
        self.assertIn("第80章 章节80", context)

    def test_chapter_context_inherits_unsummarized_body_excerpt(self):
        previous = _new_chapter(0)
        previous["title"] = "第十章 油纸包"
        previous["text"] = "赵明打开油纸包，发现半枚虎符和旧案缺页藏在一起。"
        current = _new_chapter(1)
        current["title"] = "第十一章 暗流"
        current["outline"] = "主角带着证据入城。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertIn("【前文继承摘要】", context)
        self.assertIn("正文摘录", context)
        self.assertIn("半枚虎符和旧案缺页", context)

    def test_chapter_context_auto_builds_compressed_materials_without_manual_inputs(self):
        first = _new_chapter(0)
        first["title"] = "第一章 旧案"
        first["summary"] = "主角发现旧案卷宗。"
        first["key_facts"] = "卷宗缺少最后一页。"
        first["linked_characters"] = ["赵明"]
        current = _new_chapter(1)
        current["title"] = "第二章 入城"
        current["outline"] = "主角入城调查。"
        project = self._project_with_current_chapter(current)
        project["timeline"] = ""
        project["summary"] = ""
        project["foreshadows"] = ""
        project["chapters"] = [first, current]
        project["foreshadow_items"] = [
            {
                "name": "虎符失踪",
                "status": "已埋",
                "setup_chapter": "第一章",
                "payoff_chapter": "第二十章",
                "description": "后续牵出兵权。",
            }
        ]

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertIn("自动章节顺序线", context)
        self.assertIn("卷宗缺少最后一页", context)
        self.assertIn("自动章节压缩", context)
        self.assertIn("开放伏笔队列", context)
        self.assertIn("虎符失踪", context)

    def test_chapter_context_inherits_recent_chapter_relevance_without_manual_links(self):
        previous = _new_chapter(0)
        previous["title"] = "第五十章 暗门"
        previous["summary"] = "迟到主角带主角进入琉璃塔。"
        previous["key_facts"] = "琉璃塔地底暗门开启，迟到主角暴露旧案证人身份。"
        previous["linked_characters"] = ["迟到主角"]
        current = _new_chapter(1)
        current["title"] = "第五十一章 地底旧卷"
        current["outline"] = "主角在暗门下寻找旧卷。"
        current["linked_characters"] = []
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]
        project["characters"] = [
            {"name": f"路人{i}", "role": "过场人物", "goal": "", "secret": "", "voice": "", "notes": ""}
            for i in range(35)
        ]
        project["characters"].append({
            "name": "迟到主角",
            "role": "旧案证人",
            "goal": "带主角找到旧卷",
            "secret": "曾经藏起证词",
            "voice": "谨慎克制",
            "notes": "",
        })
        project["lore"] = [
            {"name": f"普通地点{i}", "type": "地点", "description": "无关地点"}
            for i in range(35)
        ]
        project["lore"].append({
            "name": "琉璃塔",
            "type": "地点",
            "description": "旧案证据藏匿处。",
        })

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertIn("【近几章连续性】", context)
        self.assertIn("迟到主角", context)
        self.assertIn("旧案证人", context)
        self.assertIn("琉璃塔", context)
        self.assertIn("旧案证据藏匿处", context)

    def test_chapter_context_includes_recent_character_and_lore_state(self):
        previous = _new_chapter(0)
        previous["title"] = "第五十章 暗门"
        previous["summary"] = "赵明和迟到主角进入琉璃塔。"
        previous["key_facts"] = "迟到主角暴露旧案证人身份；琉璃塔地底暗门已开启。"
        previous["linked_characters"] = ["赵明", "迟到主角"]
        current = _new_chapter(1)
        current["title"] = "第五十一章 地底旧卷"
        current["outline"] = "赵明追问迟到主角，并继续探索琉璃塔暗门。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]
        project["characters"] = [
            {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "", "notes": ""},
            {"name": "迟到主角", "role": "旧案证人", "goal": "保住旧卷", "secret": "", "voice": "", "notes": ""},
        ]
        project["lore"] = [
            {"name": "琉璃塔", "type": "地点", "description": "旧案证据藏匿处。"},
        ]

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertIn("最近状态", context)
        self.assertIn("迟到主角暴露旧案证人身份", context)
        self.assertIn("琉璃塔地底暗门已开启", context)

    def test_chapter_context_infers_recent_character_state_without_manual_links(self):
        previous = _new_chapter(0)
        previous["title"] = "第五十章 暗门"
        previous["summary"] = "赵明和迟到主角进入琉璃塔。"
        previous["key_facts"] = "迟到主角暴露旧案证人身份，交出缺页卷宗。"
        previous["linked_characters"] = []
        current = _new_chapter(1)
        current["title"] = "第五十一章 地底旧卷"
        current["outline"] = "主角继续追问旧卷来源。"
        current["linked_characters"] = []
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]
        project["characters"] = [
            {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "", "notes": ""},
            {"name": "迟到主角", "role": "旧案证人", "goal": "保住旧卷", "secret": "", "voice": "", "notes": ""},
        ]

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertIn("关联人物：赵明, 迟到主角", context)
        self.assertIn("最近状态", context)
        self.assertIn("迟到主角暴露旧案证人身份", context)
        self.assertIn("交出缺页卷宗", context)

    def test_chapter_context_infers_current_character_without_manual_links(self):
        current = _new_chapter(0)
        current["title"] = "第二十章 旧卷"
        current["outline"] = "主角追问旧卷来源。"
        current["text"] = "赵明刚把旧卷收起，迟到主角便按住了暗门。"
        current["linked_characters"] = []
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "", "notes": ""},
            {"name": "迟到主角", "role": "旧案证人", "goal": "保住旧卷", "secret": "", "voice": "", "notes": ""},
        ]

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("关联人物：赵明, 迟到主角", context)
        self.assertIn("查清旧案", context)
        self.assertIn("保住旧卷", context)

    def test_chapter_context_includes_current_tail_for_continuation(self):
        current = _new_chapter(0)
        current["title"] = "第六十章 雨夜追问"
        current["outline"] = "主角继续追问旧案。"
        current["text"] = "前文很多。\n\n迟到主角停在檐下，雨水顺着刀鞘往下淌。\n\n他低声说：钥匙不在我这里。"
        project = self._project_with_current_chapter(current)

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【续写承接点】", context)
        self.assertIn("当前正文最后几段", context)
        self.assertIn("钥匙不在我这里", context)
        self.assertIn("优先承接【续写承接点】", context)

    def test_chapter_context_includes_previous_chapter_tail_for_new_chapter(self):
        previous = _new_chapter(0)
        previous["title"] = "第六十章 雨夜追问"
        previous["text"] = "前文很多。\n\n迟到主角把油纸包放到桌上。\n\n纸包里露出半枚虎符。"
        current = _new_chapter(1)
        current["title"] = "第六十一章 半枚虎符"
        current["outline"] = "主角确认虎符来源。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertIn("【续写承接点】", context)
        self.assertIn("上一章「第六十章 雨夜追问」结尾", context)
        self.assertIn("纸包里露出半枚虎符", context)
        self.assertIn("自然承接上一章", context)

    def test_chapter_context_keeps_current_chapter_when_materials_are_huge(self):
        previous = _new_chapter(0)
        previous["title"] = "第六十章 雨夜追问"
        previous["text"] = "上一章厚重正文。" * 1200 + "\n\n纸包里露出半枚虎符。"
        previous["summary"] = "上一章摘要。" * 600
        previous["key_facts"] = "上一章关键事实。" * 600
        current = _new_chapter(1)
        current["title"] = "第六十一章 半枚虎符"
        current["outline"] = (
            "必须保留的当前章提纲。"
            + " ".join(f"角色{i}" for i in range(24))
            + " "
            + " ".join(f"地点{i}" for i in range(28))
            + " "
            + " ".join(f"伏笔{i}" for i in range(30))
        )
        current["text"] = "当前章已有正文。" * 1000 + "\n\n必须保留的当前正文尾巴。"
        project = self._project_with_current_chapter(current)
        project["bible"] = "小说圣经资料。" * 2000
        project["world_rules"] = "世界规则资料。" * 1600
        project["timeline"] = "时间线资料。" * 2000
        project["summary"] = "全局摘要资料。" * 2000
        project["chapters"] = [previous, current]
        project["characters"] = [
            {
                "name": f"角色{i}",
                "role": "重要人物" + "身份资料。" * 40,
                "goal": "人物目标。" * 40,
                "secret": "人物秘密。" * 40,
                "voice": "语言风格。" * 40,
                "notes": "",
            }
            for i in range(24)
        ]
        project["lore"] = [
            {"name": f"地点{i}", "type": "地点", "description": "设定说明。" * 120}
            for i in range(28)
        ]
        project["foreshadow_items"] = [
            {
                "name": f"伏笔{i}",
                "status": "已埋",
                "setup_chapter": "第10章",
                "payoff_chapter": "",
                "description": "伏笔说明。" * 120,
            }
            for i in range(30)
        ]

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertLessEqual(len(context), 56000)
        self.assertIn("【当前章节】", context)
        self.assertIn("必须保留的当前章提纲", context)
        self.assertIn("必须保留的当前正文尾巴", context)
        self.assertIn("【续写承接点】", context)
        self.assertIn("纸包里露出半枚虎符", context)

    def test_chapter_context_allows_larger_timeline_and_summary_windows(self):
        current = _new_chapter(0)
        current["title"] = "第八十章 终局前夜"
        current["outline"] = "主角整理所有线索，准备进入终局法庭。"
        project = self._project_with_current_chapter(current)
        project["timeline"] = "时间线资料。" * 1200
        project["summary"] = "全局摘要资料。" * 1200

        context = _build_chapter_ai_context(project, 0, "draft")
        timeline_section = self._context_section(context, "时间线")
        summary_section = self._context_section(context, "全局摘要 / 日志")

        self.assertGreater(len(timeline_section), 4200)
        self.assertLessEqual(len(timeline_section), 5000)
        self.assertGreater(len(summary_section), 4200)
        self.assertLessEqual(len(summary_section), 5000)

    def test_chapter_context_includes_long_form_progress_rhythm(self):
        chapters = []
        for index in range(40):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["text"] = "正文" * 2000
            chapter["summary"] = f"摘要 {index + 1}"
            chapter["key_facts"] = f"事实 {index + 1}"
            chapters.append(chapter)
        current = _new_chapter(40)
        current["title"] = "章节41"
        current["outline"] = "主角准备回收关键伏笔。"
        chapters.append(current)
        project = self._project_with_current_chapter(current)
        project["meta"]["target_words"] = "20万"
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 40, "draft")

        self.assertIn("【长篇进度 / 节奏】", context)
        self.assertIn("项目总目标规模：20万字", context)
        self.assertIn("自动判断阶段：后段收束", context)
        self.assertIn("集中回收伏笔", context)
        self.assertIn("控制本章推进密度", context)

    def test_chapter_context_includes_future_plan_boundary(self):
        current = _new_chapter(0)
        current["title"] = "第一章 半枚虎符"
        current["outline"] = "主角拿到半枚虎符，但还不能知道来源。"
        chapters = [current]
        for index in range(1, 6):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = f"阶段推进 {index + 1}。"
            chapters.append(chapter)
        chapters[1]["outline"] = "第二章继续追查虎符来源，只做铺垫。"
        chapters[5]["key_facts"] = "第六章揭晓虎符真相，确认旧案内鬼。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【后续规划 / 边界】", context)
        self.assertIn("后续近章规划", context)
        self.assertIn("当前章只能铺垫", context)
        self.assertIn("虎符来源", context)
        self.assertIn("远期回收/转折锚点", context)
        self.assertIn("虎符真相", context)

    def test_chapter_context_future_boundary_keeps_final_milestone(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入局"
        current["outline"] = "主角只拿到第一条线索。"
        chapters = [current]
        for index in range(1, 40):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = f"阶段推进 {index + 1}。"
            if index >= 5:
                chapter["key_facts"] = f"第{index + 1}章回收阶段线索 {index + 1}。"
            chapters.append(chapter)
        chapters[-1]["title"] = "第四十章 终局真相"
        chapters[-1]["key_facts"] = "结局揭晓旧案最终真相，确认真正内鬼。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("远期回收/转折锚点", context)
        self.assertIn("第四十章 终局真相", context)
        self.assertIn("最终真相", context)

    def test_chapter_context_future_boundary_keeps_parentage_milestone(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入局"
        current["outline"] = "主角只拿到第一条线索。"
        chapters = [current]
        for index in range(1, 40):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = f"阶段推进 {index + 1}。"
            chapters.append(chapter)
        chapters[-1]["title"] = "第四十章 身世夜谈"
        chapters[-1]["key_facts"] = "结局揭晓赵明亲生父亲，确认旧案血脉真相。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("远期回收/转折锚点", context)
        self.assertIn("第四十章 身世夜谈", context)
        self.assertIn("亲生父亲", context)

    def test_chapter_context_keeps_balanced_auto_timeline_for_long_projects(self):
        chapters = []
        for index in range(70):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"日常推进 {index + 1}。"
            chapter["key_facts"] = f"阶段事实 {index + 1}。"
            chapters.append(chapter)
        chapters[0]["title"] = "第一章 旧案"
        chapters[0]["summary"] = "赵明发现旧案卷宗。"
        chapters[0]["key_facts"] = "卷宗缺少最后一页。"
        chapters[34]["title"] = "第三十五章 虎符真相"
        chapters[34]["summary"] = "虎符真相揭晓，旧案内鬼露出破绽。"
        chapters[34]["key_facts"] = "虎符失踪伏笔部分回收。"
        current = _new_chapter(70)
        current["title"] = "第七十一章 终局门前"
        current["outline"] = "众人抵达终局法庭。"
        chapters.append(current)
        project = self._project_with_current_chapter(current)
        project["timeline"] = ""
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 70, "draft")

        self.assertIn("自动章节顺序线", context)
        self.assertIn("早期/中段时间线", context)
        self.assertIn("关键转折锚点", context)
        self.assertIn("卷宗缺少最后一页", context)
        self.assertIn("虎符真相揭晓", context)
        self.assertIn("第七十一章 终局门前", context)

    def test_chapter_context_keeps_saved_archive_notes_without_semantic_filtering(self):
        current = _new_chapter(0)
        current["title"] = "第一章 邮件泄露"
        current["outline"] = "沈慕白追查慕白资本的泄露责任链，旧钟声只作为线索出现。"
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {
                "name": "沈慕白",
                "role": "主角",
                "goal": "查清泄露责任链",
                "secret": "",
                "voice": "",
                "notes": "沈慕白对信息泄露极度敏感，会优先追查责任链。\n本章沈慕白追问泄露范围。",
            }
        ]
        project["lore"] = [
            {
                "name": "慕白资本",
                "type": "组织",
                "description": "慕白资本控制多条融资渠道，是沈家资本布局的核心工具。\n本章项目资料发往慕白资本邮箱。",
            }
        ]
        project["foreshadow_items"] = [
            {
                "name": "旧钟声",
                "status": "已埋",
                "setup_chapter": "第一章",
                "payoff_chapter": "第十章",
                "description": "旧钟声代表密室开启，已埋，待在琉璃塔章节回收。\n本章又提到旧钟声。\n主角看到新线索后很震惊。",
            }
        ]

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("沈慕白对信息泄露极度敏感", context)
        self.assertIn("慕白资本控制多条融资渠道", context)
        self.assertIn("旧钟声代表密室开启", context)
        self.assertIn("本章沈慕白追问泄露范围", context)
        self.assertIn("本章项目资料发往慕白资本邮箱", context)
        self.assertIn("本章又提到旧钟声", context)
        self.assertIn("主角看到新线索后很震惊", context)

    def test_long_form_check_reports_context_maintenance_gaps(self):
        chapters = []
        for index in range(20):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["text"] = "正文"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "world_rules": "",
            "timeline": "",
            "summary": "",
            "characters": [],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "foreshadow_items": [],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("阶段摘要暂缺", check_text)
        self.assertIn("系统会自动压缩成全局摘要", check_text)
        self.assertIn("时间线暂缺", check_text)
        self.assertIn("系统会按章节顺序生成草稿", check_text)
        self.assertIn("缺少摘要/关键事实", check_text)
        self.assertIn("应用 AI 正文后会自动补", check_text)
        self.assertIn("没有关联人物", check_text)
        self.assertIn("可用 AI 摘要按本章实际内容补齐，或手动填写", check_text)
        self.assertIn("人物卡为空", check_text)
        self.assertIn("摘要/事实覆盖：0/20", check_text)
        self.assertIn("关联人物覆盖：0/20", check_text)
        self.assertIn("后续规划覆盖：0/19", check_text)
        self.assertIn("后续章节规划较少", check_text)

    def test_long_form_check_groups_completed_chapters_missing_summary_fields(self):
        chapters = []
        for index in range(20):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["status"] = "已完成"
            chapter["text"] = "正文"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("标记已完成但缺少本章摘要", check_text)
        self.assertIn("长篇可优先补关键转折章", check_text)
        self.assertIn("标记已完成但缺少需继承的关键事实", check_text)
        self.assertIn("建议优先补人物关系", check_text)
        self.assertIn("等 20 章", check_text)
        self.assertEqual(check_text.count("标记已完成但缺少本章摘要"), 1)
        self.assertEqual(check_text.count("标记已完成但缺少需继承的关键事实"), 1)

    def test_short_form_check_keeps_precise_completed_chapter_summary_warnings(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章 旧案"
        chapter["status"] = "已完成"
        chapter["text"] = "正文"
        project = {
            "meta": {"target_words": "3万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("第 1 章「第一章 旧案」标记已完成，但缺少本章摘要", check_text)
        self.assertIn("第 1 章「第一章 旧案」标记已完成，但缺少需继承的关键事实", check_text)

    def test_long_form_check_does_not_guess_future_reveal_from_keywords(self):
        current = _new_chapter(0)
        current["title"] = "第一章 半枚虎符"
        current["text"] = "赵明提前知道虎符真相。"
        future = _new_chapter(1)
        future["title"] = "第二章 真相"
        future["outline"] = "第二章揭晓虎符真相。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": [current, future],
        }

        check_text = _build_writing_check_text(project)

        self.assertNotIn("可能提前写到第二章 真相的", check_text)
        self.assertNotIn("提前兑现后续规划", check_text)

    def test_long_form_check_does_not_guess_distant_future_reveal_from_keywords(self):
        chapters = []
        current = _new_chapter(0)
        current["title"] = "第一章 入局"
        current["text"] = "赵明提前说破沈砚真实身份。"
        chapters.append(current)
        for index in range(1, 39):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = f"阶段推进 {index + 1}。"
            chapters.append(chapter)
        future = _new_chapter(39)
        future["title"] = "第四十章 身份真相"
        future["outline"] = "第四十章揭晓沈砚真实身份，确认他是旧案内鬼。"
        chapters.append(future)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"},
                {"name": "沈砚", "role": "反派", "goal": "隐藏旧案身份", "voice": "温和"},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertNotIn("可能提前写到第四十章 身份真相的", check_text)
        self.assertNotIn("提前兑现后续规划", check_text)

    def test_long_form_check_does_not_guess_future_parentage_reveal_from_keywords(self):
        chapters = []
        current = _new_chapter(0)
        current["title"] = "第一章 入局"
        current["text"] = "赵明提前知道沈砚是亲生父亲。"
        chapters.append(current)
        for index in range(1, 39):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = f"阶段推进 {index + 1}。"
            chapters.append(chapter)
        future = _new_chapter(39)
        future["title"] = "第四十章 身世夜谈"
        future["outline"] = "第四十章揭晓沈砚亲生父亲身份，确认旧案血脉真相。"
        chapters.append(future)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"},
                {"name": "沈砚", "role": "反派", "goal": "隐藏旧案身份", "voice": "温和"},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertNotIn("可能提前写到第四十章 身世夜谈的", check_text)
        self.assertNotIn("提前兑现后续规划", check_text)

    def test_long_form_check_does_not_nag_outline_only_future_chapters(self):
        chapters = []
        for index in range(24):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["status"] = "大纲"
            chapter["outline"] = f"第 {index + 1} 章剧情拍点。"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertNotIn("还没有正文", check_text)
        self.assertNotIn("缺少章节提纲", check_text)

    def test_writing_check_keeps_warning_for_active_chapter_without_text(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章 旧案"
        chapter["status"] = "写作中"
        chapter["outline"] = "主角发现旧案。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("标记为写作中/已完成但没有正文", check_text)

    def test_long_form_check_counts_auto_detected_character_links(self):
        chapters = []
        for index in range(20):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["text"] = "赵明在王城调查旧案。"
            chapter["summary"] = "赵明继续调查旧案。"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("关联人物覆盖：20/20", check_text)
        self.assertNotIn("没有关联人物", check_text)

    def test_long_form_check_ignores_core_role_words_without_exact_character_name(self):
        chapters = []
        for index in range(20):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = "主角在王城调查旧案。"
            chapter["summary"] = "主角继续调查旧案。"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "克制", "notes": ""},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("关联人物覆盖：0/20", check_text)
        self.assertIn("没有关联人物", check_text)

    def test_long_form_check_does_not_count_global_core_character_without_chapter_signal(self):
        chapters = []
        for index in range(20):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = "剧情拍点推进。"
            chapter["summary"] = "旧案线继续推进。"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "克制", "notes": ""},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("关联人物覆盖：0/20", check_text)
        self.assertIn("没有关联人物", check_text)

    def test_writing_check_only_requires_details_for_core_or_frequent_characters(self):
        chapters = []
        for index in range(9):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = "赵明继续调查旧案。"
            chapter["text"] = "赵明在王城追查线索。"
            if index == 0:
                chapter["text"] += " 李路人递来茶盏。"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
                {"name": "李路人", "role": "路人", "goal": "", "secret": "", "voice": "", "notes": ""},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("核心/高频人物「赵明」缺少人物目标", check_text)
        self.assertIn("核心/高频人物「赵明」缺少语言风格", check_text)
        self.assertNotIn("人物「李路人」缺少人物目标", check_text)
        self.assertNotIn("人物「李路人」缺少语言风格", check_text)

    def test_writing_check_accepts_linked_character_aliases(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第十章 代号现身"
        chapter["summary"] = "玄鸦交出旧案卷宗，陌生人旁听。"
        chapter["linked_characters"] = ["玄鸦", "陌生人"]
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {
                    "name": "迟到主角",
                    "role": "旧案证人",
                    "goal": "保住证据",
                    "voice": "谨慎",
                    "notes": "代号：玄鸦",
                },
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertNotIn("关联人物「玄鸦」不在人物卡里", check_text)
        self.assertIn("关联人物「陌生人」不在人物卡里", check_text)

    def test_writing_check_accepts_linked_character_honorific_aliases(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第十章 尊称现身"
        chapter["summary"] = "阁主先生交出旧案卷宗。"
        chapter["linked_characters"] = ["阁主先生"]
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {
                    "name": "迟到主角",
                    "role": "旧案证人",
                    "goal": "保住证据",
                    "voice": "谨慎",
                    "notes": "尊称：阁主先生",
                },
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertNotIn("关联人物「阁主先生」不在人物卡里", check_text)

    def test_writing_check_warns_character_alias_duplicates(self):
        chapter = _new_chapter(0)
        chapter["summary"] = "玄鸦交出旧案卷宗。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {
                    "name": "迟到主角",
                    "role": "旧案证人",
                    "goal": "保住证据",
                    "voice": "谨慎",
                    "notes": "代号：玄鸦",
                },
                {"name": "玄鸦", "role": "密探", "goal": "", "voice": ""},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("人物「迟到主角」和「玄鸦」疑似同一人/别称", check_text)

    def test_writing_check_warns_lore_alias_duplicates(self):
        chapter = _new_chapter(0)
        chapter["summary"] = "赵明进入白塔。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [
                {"name": "琉璃塔", "type": "地点", "description": "别称：白塔。旧案证据藏匿处。"},
                {"name": "白塔", "type": "地点", "description": "塔顶藏有旧案卷宗。"},
            ],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("设定「琉璃塔」和「白塔」疑似同一设定/别称", check_text)

    def test_writing_check_warns_foreshadow_alias_duplicates(self):
        chapter = _new_chapter(0)
        chapter["summary"] = "赵明拿到半枚虎符。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第一章",
                    "payoff_chapter": "",
                    "description": "别称：半枚虎符。牵出兵权。",
                },
                {
                    "name": "半枚虎符",
                    "status": "已埋",
                    "setup_chapter": "第一章",
                    "payoff_chapter": "",
                    "description": "后续牵出兵权交易。",
                },
            ],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("伏笔「虎符失踪」和「半枚虎符」疑似同一线索/别称", check_text)

    def test_project_summary_draft_collects_chapter_facts_and_active_foreshadows(self):
        chapters = []
        for index in range(14):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"摘要 {index + 1}"
            chapter["key_facts"] = f"事实 {index + 1}"
            chapter["text"] = "赵明继续在王城调查旧案。"
            chapters.append(chapter)
        project = {
            "meta": {"title": "长篇测试", "premise": "旧案重启。"},
            "chapters": chapters,
            "characters": [
                {
                    "name": "赵明",
                    "role": "主角",
                    "goal": "查清旧案",
                    "secret": "藏着旧伤",
                    "voice": "克制",
                    "notes": "",
                }
            ],
            "lore": [
                {"name": "王城", "type": "地点", "description": "旧案调查的主舞台。"},
            ],
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第2章",
                    "payoff_chapter": "第20章",
                    "description": "",
                }
            ],
        }

        text = _build_project_summary_draft(project)

        self.assertIn("阶段摘要草稿", text)
        self.assertIn("近期章节", text)
        self.assertIn("长期关键事实", text)
        self.assertIn("事实 1", text)
        self.assertIn("事实 14", text)
        self.assertIn("高频人物快照", text)
        self.assertIn("赵明", text)
        self.assertIn("出现 14 章", text)
        self.assertIn("高频设定快照", text)
        self.assertIn("王城", text)
        self.assertIn("旧案调查的主舞台", text)
        self.assertIn("未完成伏笔", text)
        self.assertIn("虎符失踪", text)

    def test_project_summary_draft_ignores_core_role_words_without_exact_character_name(self):
        chapters = []
        for index in range(14):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = "主角继续调查旧案。"
            chapter["key_facts"] = "主角保留缺页卷宗。"
            chapters.append(chapter)
        project = {
            "meta": {"title": "长篇测试", "premise": "旧案重启。"},
            "chapters": chapters,
            "characters": [
                {
                    "name": "赵明",
                    "role": "主角",
                    "goal": "查清旧案",
                    "secret": "",
                    "voice": "克制",
                    "notes": "",
                }
            ],
        }

        text = _build_project_summary_draft(project)

        self.assertNotIn("高频人物快照", text)
        self.assertNotIn("赵明｜出现 14 章", text)

    def test_project_summary_draft_keeps_mid_story_milestones_in_long_projects(self):
        chapters = []
        for index in range(70):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"日常推进 {index + 1}。"
            chapter["key_facts"] = f"阶段事实 {index + 1}。"
            chapters.append(chapter)
        chapters[0]["title"] = "第一章 旧案"
        chapters[0]["summary"] = "赵明发现旧案卷宗。"
        chapters[0]["key_facts"] = "卷宗缺少最后一页。"
        chapters[34]["title"] = "第三十五章 虎符真相"
        chapters[34]["summary"] = "虎符真相揭晓，旧案内鬼露出破绽。"
        chapters[34]["key_facts"] = "虎符失踪伏笔部分回收。"
        chapters[69]["title"] = "第七十章 终局门前"
        chapters[69]["summary"] = "众人抵达终局法庭。"
        project = {
            "meta": {"title": "长篇测试", "premise": "旧案重启。"},
            "chapters": chapters,
        }

        text = _build_project_summary_draft(project)

        self.assertIn("阶段摘要草稿", text)
        self.assertIn("近期章节", text)
        self.assertIn("长期关键事实", text)
        self.assertIn("关键转折锚点", text)
        self.assertIn("卷宗缺少最后一页", text)
        self.assertIn("虎符真相揭晓", text)
        self.assertIn("第七十章 终局门前", text)

    def test_project_summary_draft_uses_body_excerpt_when_summary_missing(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章 油纸包"
        chapter["text"] = "赵明打开油纸包，发现半枚虎符和旧案缺页藏在一起。"
        project = {
            "meta": {"title": "长篇测试", "premise": "旧案重启。"},
            "chapters": [chapter],
        }

        text = _build_project_summary_draft(project)

        self.assertIn("阶段摘要草稿", text)
        self.assertIn("正文摘录", text)
        self.assertIn("半枚虎符和旧案缺页", text)

    def test_project_summary_draft_prioritizes_actionable_late_foreshadow(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章 旧案"
        chapter["summary"] = "主角发现旧案卷宗。"
        project = {
            "meta": {"title": "长篇测试", "premise": "旧案重启。"},
            "chapters": [chapter],
            "foreshadow_items": [
                {
                    "name": f"普通伏笔{i}",
                    "status": "已埋",
                    "setup_chapter": "",
                    "payoff_chapter": "",
                    "description": "普通背景线索，暂不影响主线。",
                }
                for i in range(80)
            ],
        }
        project["foreshadow_items"].append({
            "name": "终局密钥",
            "status": "已埋",
            "setup_chapter": "第十章",
            "payoff_chapter": "第五十章",
            "description": "关系最终真相，必须在后期回收。",
        })

        text = _build_project_summary_draft(project)

        self.assertIn("未完成伏笔", text)
        self.assertIn("终局密钥", text)
        self.assertIn("第五十章", text)
        self.assertLess(text.index("终局密钥"), text.index("普通伏笔0"))

    def test_project_timeline_draft_collects_chapter_order_and_linked_characters(self):
        first = _new_chapter(0)
        first["title"] = "第一章 旧案"
        first["summary"] = "主角发现旧案卷宗。"
        first["key_facts"] = "卷宗缺少最后一页。"
        first["linked_characters"] = ["赵明"]
        second = _new_chapter(1)
        second["title"] = "第二章 入城"
        second["outline"] = "主角入城，遇见线人。"
        project = {"chapters": [first, second]}

        text = _build_project_timeline_draft(project)

        self.assertIn("时间线草稿", text)
        self.assertIn("第一章 旧案", text)
        self.assertIn("卷宗缺少最后一页", text)
        self.assertIn("人物：赵明", text)
        self.assertIn("第二章 入城", text)
        self.assertIn("提纲：主角入城", text)

    def test_project_timeline_draft_uses_body_excerpt_when_summary_missing(self):
        first = _new_chapter(0)
        first["title"] = "第一章 油纸包"
        first["text"] = "赵明打开油纸包，发现半枚虎符和旧案缺页藏在一起。"
        project = {"chapters": [first]}

        text = _build_project_timeline_draft(project)

        self.assertIn("时间线草稿", text)
        self.assertIn("正文摘录", text)
        self.assertIn("半枚虎符和旧案缺页", text)

    def test_project_timeline_draft_uses_auto_detected_characters(self):
        first = _new_chapter(0)
        first["title"] = "第一章 旧案"
        first["summary"] = "赵明发现旧案卷宗。"
        first["text"] = "赵明在王城找到旧案卷宗。"
        project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
            ],
            "lore": [
                {"name": "王城", "type": "地点", "description": "故事主舞台"},
            ],
            "chapters": [first],
        }

        text = _build_project_timeline_draft(project)

        self.assertIn("人物：赵明", text)
        self.assertIn("设定：王城", text)

    def test_project_timeline_draft_ignores_core_role_words_without_exact_character_name(self):
        first = _new_chapter(0)
        first["title"] = "第一章 旧案"
        first["summary"] = "主角发现旧案卷宗。"
        first["key_facts"] = "主角拿到缺页卷宗。"
        project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "", "notes": ""},
            ],
            "chapters": [first],
        }

        text = _build_project_timeline_draft(project)

        self.assertNotIn("人物：赵明", text)

    def test_project_timeline_draft_uses_lore_alias_from_description(self):
        first = _new_chapter(0)
        first["title"] = "第一章 白塔钟声"
        first["summary"] = "赵明进入白塔，发现旧案卷宗。"
        project = {
            "lore": [
                {"name": "琉璃塔", "type": "地点", "description": "别称：白塔。旧案证据藏匿处。"},
            ],
            "chapters": [first],
        }

        text = _build_project_timeline_draft(project)

        self.assertIn("设定：琉璃塔", text)

    def test_project_timeline_draft_ignores_generic_stage_terms_without_exact_lore_name(self):
        first = _new_chapter(0)
        first["title"] = "第一章 回城"
        first["outline"] = "主角回到主舞台，在朝堂继续调查旧案。"
        project = {
            "lore": [
                *[
                    {"name": f"普通设定{i}", "type": "地点", "description": "偏远地点，暂不影响主线。"}
                    for i in range(35)
                ],
                {"name": "王城", "type": "地点", "description": "故事主舞台，朝堂和旧案卷宗都在这里交汇。"},
            ],
            "chapters": [first],
        }

        text = _build_project_timeline_draft(project)

        self.assertNotIn("设定：王城", text)
        self.assertNotIn("普通设定0", text)

    def test_project_summary_draft_ignores_lore_activity_from_generic_stage_terms(self):
        chapters = []
        for index in range(14):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"摘要 {index + 1}"
            chapter["key_facts"] = f"事实 {index + 1}"
            chapter["text"] = "主角回到主舞台，在朝堂继续调查旧案。"
            chapters.append(chapter)
        project = {
            "meta": {"title": "长篇测试", "premise": "旧案重启。"},
            "chapters": chapters,
            "lore": [
                {"name": "王城", "type": "地点", "description": "故事主舞台，朝堂和旧案卷宗都在这里交汇。"},
            ],
        }

        text = _build_project_summary_draft(project)

        self.assertNotIn("高频设定快照", text)
        self.assertNotIn("王城｜地点｜出现 14 章", text)

    def test_project_timeline_draft_compresses_long_projects_with_milestones(self):
        chapters = []
        for index in range(70):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"日常推进 {index + 1}。"
            chapter["key_facts"] = f"阶段事实 {index + 1}。"
            chapters.append(chapter)
        chapters[0]["title"] = "第一章 旧案"
        chapters[0]["summary"] = "赵明发现旧案卷宗。"
        chapters[0]["key_facts"] = "卷宗缺少最后一页。"
        chapters[34]["title"] = "第三十五章 虎符真相"
        chapters[34]["summary"] = "虎符真相揭晓，旧案内鬼露出破绽。"
        chapters[34]["key_facts"] = "虎符失踪伏笔部分回收。"
        chapters[69]["title"] = "第七十章 终局门前"
        chapters[69]["summary"] = "众人抵达终局法庭。"
        project = {"chapters": chapters}

        text = _build_project_timeline_draft(project)

        self.assertIn("近期章节", text)
        self.assertIn("早期/中段时间线", text)
        self.assertIn("关键转折锚点", text)
        self.assertIn("卷宗缺少最后一页", text)
        self.assertIn("虎符真相揭晓", text)
        self.assertIn("第七十章 终局门前", text)
        self.assertIn("已平衡压缩", text)

    def test_foreshadow_notes_draft_groups_structured_items(self):
        project = {
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第2章",
                    "payoff_chapter": "第20章",
                    "description": "读者以为只是偷盗。",
                },
                {
                    "name": "旧钟声",
                    "status": "已回收",
                    "setup_chapter": "第3章",
                    "payoff_chapter": "第12章",
                    "description": "密室开启。",
                },
            ]
        }

        text = _build_foreshadow_notes_draft(project)

        self.assertIn("伏笔汇总草稿", text)
        self.assertIn("已埋：", text)
        self.assertIn("虎符失踪", text)
        self.assertIn("第2章 -> 第20章", text)
        self.assertIn("已回收：", text)
        self.assertIn("旧钟声", text)

    def test_foreshadow_notes_draft_limits_large_resolved_groups(self):
        project = {
            "foreshadow_items": [
                {
                    "name": f"待回收伏笔{i}",
                    "status": "已埋",
                    "setup_chapter": f"第{i + 1}章",
                    "payoff_chapter": "",
                    "description": "后续处理。",
                }
                for i in range(3)
            ] + [
                {
                    "name": f"已回收线索{i}",
                    "status": "已回收",
                    "setup_chapter": f"第{i + 1}章",
                    "payoff_chapter": f"第{i + 2}章",
                    "description": "已经处理。",
                }
                for i in range(20)
            ]
        }

        text = _build_foreshadow_notes_draft(project)

        self.assertIn("待回收伏笔0", text)
        self.assertIn("已回收线索19", text)
        self.assertNotIn("已回收线索0", text)
        self.assertIn("另有 12 条已回收伏笔已省略", text)

    def test_foreshadow_notes_draft_prioritizes_actionable_buried_items(self):
        project = {
            "foreshadow_items": [
                {
                    "name": f"普通已埋伏笔{i}",
                    "status": "已埋",
                    "setup_chapter": "",
                    "payoff_chapter": "",
                    "description": "普通背景线索，暂不影响主线。",
                }
                for i in range(45)
            ]
        }
        project["foreshadow_items"].append({
            "name": "终局密钥",
            "status": "已埋",
            "setup_chapter": "第十章",
            "payoff_chapter": "第五十章",
            "description": "关系最终真相，必须在后期回收。",
        })

        text = _build_foreshadow_notes_draft(project)

        self.assertIn("已埋：", text)
        self.assertIn("终局密钥", text)
        self.assertIn("第十章 -> 第五十章", text)
        self.assertLess(text.index("终局密钥"), text.index("普通已埋伏笔0"))
        self.assertNotIn("普通已埋伏笔44", text)

    def test_infer_foreshadow_status_only_normalizes_explicit_status(self):
        buried = {
            "name": "虎符失踪",
            "setup_chapter": "第二章",
            "description": "第十章待揭晓，尚未解释真相。",
        }
        unburied = {
            "name": "暗门机关",
            "description": "后期未兑现，真相未明。",
        }
        resolved = {
            "name": "旧钟声",
            "description": "密室钟声的真相揭晓，机关已经解开。",
        }
        explicit_buried = {"name": "虎符失踪", "status": "待回收", "description": "第十章待揭晓。"}
        explicit_resolved = {"name": "旧钟声", "status": "已兑现", "description": "密室钟声的真相揭晓。"}

        self.assertEqual(_infer_foreshadow_status(buried), "未埋")
        self.assertEqual(_infer_foreshadow_status(unburied), "未埋")
        self.assertEqual(_infer_foreshadow_status(resolved), "未埋")
        self.assertEqual(_infer_foreshadow_status(explicit_buried), "已埋")
        self.assertEqual(_infer_foreshadow_status(explicit_resolved), "已回收")

    def test_writing_check_does_not_infer_foreshadow_payoff_from_chapter_facts(self):
        chapter = _new_chapter(19)
        chapter["title"] = "第二十章 虎符真相"
        chapter["summary"] = "虎符失踪的真相揭晓。"
        chapter["key_facts"] = "虎符失踪在本章回收，确认牵出兵权。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角"}],
            "lore": [{"name": "虎符", "type": "物品", "description": "兵权信物"}],
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第2章",
                    "payoff_chapter": "",
                    "description": "后续牵出兵权。",
                }
            ],
            "chapters": [chapter],
        }

        text = _build_writing_check_text(project)

        self.assertNotIn("伏笔「虎符失踪」可能已在", text)
        self.assertIn("伏笔「虎符失踪」已埋，但还没有填写回收章节", text)

    def test_writing_check_does_not_treat_unresolved_payoff_wording_as_recovered(self):
        chapter = _new_chapter(9)
        chapter["title"] = "第十章 虎符疑云"
        chapter["summary"] = "虎符失踪仍待揭晓。"
        chapter["key_facts"] = "虎符失踪尚未解释，真相未明。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角"}],
            "lore": [{"name": "虎符", "type": "物品", "description": "兵权信物"}],
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第2章",
                    "payoff_chapter": "",
                    "description": "后续牵出兵权。",
                }
            ],
            "chapters": [chapter],
        }

        text = _build_writing_check_text(project)

        self.assertNotIn("伏笔「虎符失踪」可能已在", text)
        self.assertIn("伏笔「虎符失踪」已埋，但还没有填写回收章节", text)

    def test_writing_check_does_not_infer_foreshadow_payoff_from_unsummarized_body(self):
        chapter = _new_chapter(19)
        chapter["title"] = "第二十章 雨夜"
        chapter["text"] = "赵明终于回收虎符失踪这条线索，揭晓虎符真相，确认牵出兵权。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角"}],
            "lore": [{"name": "虎符", "type": "物品", "description": "兵权信物"}],
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第2章",
                    "payoff_chapter": "",
                    "description": "后续牵出兵权。",
                }
            ],
            "chapters": [chapter],
        }

        text = _build_writing_check_text(project)

        self.assertNotIn("伏笔「虎符失踪」可能已在", text)
        self.assertIn("伏笔「虎符失踪」已埋，但还没有填写回收章节", text)

    def test_writing_check_does_not_infer_foreshadow_setup_from_unsummarized_body(self):
        chapter = _new_chapter(1)
        chapter["title"] = "第二章 雨夜"
        chapter["text"] = "赵明发现虎符失踪，暗中留下半枚虎符作为线索。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角"}],
            "lore": [{"name": "虎符", "type": "物品", "description": "兵权信物"}],
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已回收",
                    "setup_chapter": "",
                    "payoff_chapter": "第二十章",
                    "description": "后续牵出兵权。",
                }
            ],
            "chapters": [chapter],
        }

        text = _build_writing_check_text(project)

        self.assertNotIn("伏笔「虎符失踪」可能已在", text)
        self.assertIn("伏笔「虎符失踪」已回收，但缺少埋设章节记录", text)

    def test_writing_check_does_not_infer_foreshadow_payoff_from_alias(self):
        chapter = _new_chapter(11)
        chapter["title"] = "第十二章 密室开启"
        chapter["summary"] = "密室钟声的真相揭晓。"
        chapter["key_facts"] = "密室钟声在本章回收，确认暗门已经开启。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角"}],
            "lore": [{"name": "琉璃塔", "type": "地点", "description": "旧案证据藏匿处"}],
            "foreshadow_items": [
                {
                    "name": "旧钟声",
                    "status": "已埋",
                    "setup_chapter": "第3章",
                    "payoff_chapter": "",
                    "description": "别称：密室钟声。钟声响起表示暗门开启。",
                }
            ],
            "chapters": [chapter],
        }

        text = _build_writing_check_text(project)

        self.assertNotIn("伏笔「旧钟声」可能已在", text)
        self.assertIn("伏笔「旧钟声」已埋，但还没有填写回收章节", text)


if __name__ == "__main__":
    unittest.main()
