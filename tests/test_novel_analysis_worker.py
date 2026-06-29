import unittest

from gpt_desktop.workers import NovelAnalysisWorker, NovelWritingWorker


class NovelAnalysisWorkerTests(unittest.TestCase):
    def test_summary_prompt_requires_linked_characters_section(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "summary", "context")

        prompt = worker._action_prompt()

        self.assertIn("本章摘要", prompt)
        self.assertIn("本章需继承的关键事实", prompt)
        self.assertIn("本章关联人物", prompt)
        self.assertIn("具体姓名", prompt)
        self.assertIn("不要只写主角/反派/配角", prompt)
        self.assertIn("成熟的商业小说作者兼责任编辑", prompt)
        self.assertIn("1-3 句", prompt)
        self.assertIn("3-6 条短句", prompt)
        self.assertEqual(worker._max_tokens_for_request(), 700)

    def test_writing_prompts_include_editorial_quality_standard(self):
        for action in (
            "outline",
            "draft",
            "summary",
            "script_to_novel",
            "novel_to_script",
            "novel_to_storyboard",
            "script_to_storyboard",
        ):
            with self.subTest(action=action):
                worker = NovelWritingWorker("http://example.test", "key", "model", action, "context")

                prompt = worker._action_prompt()

                self.assertIn("成熟的商业小说作者兼责任编辑", prompt)
                self.assertIn("人物、设定、时间线、伏笔、空间关系和因果链", prompt)

    def test_fiction_prompts_include_body_specific_quality_requirements(self):
        for action in ("draft", "script_to_novel"):
            with self.subTest(action=action):
                worker = NovelWritingWorker("http://example.test", "key", "model", action, "context")

                prompt = worker._action_prompt()

                self.assertIn("中段必须出现一次意料之外但符合逻辑的小变化", prompt)
                self.assertIn("至少写出 3 处具体可见细节", prompt)
                self.assertIn("结尾要来自冲突本身", prompt)
                self.assertIn("不要为了贴字数截断", prompt)

        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", "context")
        prompt = worker._action_prompt()
        self.assertIn("质量优先的参考目标", prompt)
        self.assertIn("不是硬性字数要求", prompt)

    def test_outline_prompt_is_kept_compact(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "outline", "context")

        prompt = worker._action_prompt()

        self.assertIn("短提纲", prompt)
        self.assertIn("6-10", prompt)
        self.assertIn("600-1200 字", prompt)
        self.assertIn("不要写正文、对白或长段场景描写", prompt)
        self.assertIn("只概括正文已经写出来的内容", prompt)
        self.assertIn("正文没有发生", prompt)
        self.assertEqual(worker._max_tokens_for_request(), 1200)

    def test_draft_worker_extracts_chapter_word_target(self):
        worker = NovelWritingWorker(
            "http://example.test",
            "key",
            "model",
            "draft",
            "【本章写作长度】\n本章扩写字数：5000字\n本次新增正文参考目标：约3000字，用于控制详略和推进密度。",
        )

        self.assertEqual(worker._draft_word_target(), 3000)
        self.assertEqual(worker._max_tokens_for_request(), 0)

    def test_draft_worker_keeps_chapter_word_target_as_soft_guidance(self):
        worker = NovelWritingWorker(
            "http://example.test",
            "key",
            "model",
            "draft",
            "【本章写作长度】\n本章扩写字数：2200字\n本次新增正文参考目标：约2200字，用于控制详略和推进密度。",
        )

        self.assertEqual(worker._draft_word_target(), 2200)
        self.assertEqual(worker._max_tokens_for_request(), 0)

    def test_draft_worker_does_not_use_local_stream_truncation(self):
        worker = NovelWritingWorker(
            "http://example.test",
            "key",
            "model",
            "draft",
            "【本章写作长度】\n本次新增正文参考目标：约1000字，用于控制详略和推进密度。",
        )

        self.assertFalse(hasattr(worker, "_draft_stream_stop_index"))
        self.assertFalse(hasattr(worker, "_draft_max_output_chars"))
        self.assertEqual(worker._max_tokens_for_request(), 0)

    def test_analysis_prompt_uses_existing_project_dossier_for_dedupe(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")

        prompt = worker._analysis_prompt()

        self.assertIn("已有项目档案", prompt)
        self.assertIn("同名、别称或同一线索不要重复新增", prompt)
        self.assertIn("已有人物 notes", prompt)
        self.assertIn("不要把已有档案里没有在本片段推进的信息当作新发现重复输出", prompt)

    def test_analysis_chunk_user_text_injects_dossier_outside_fragment(self):
        worker = NovelAnalysisWorker(
            "http://example.test",
            "key",
            "model",
            "正文片段",
            dossier="【已有项目档案】\n赵明｜主角",
        )

        text = worker._chunk_user_text("正文片段", 2, 5)

        self.assertIn("第 2/5 个文本片段", text)
        self.assertIn("【已有项目档案】", text)
        self.assertIn("赵明｜主角", text)
        self.assertIn("【本片段】\n正文片段", text)
        self.assertLess(text.index("【已有项目档案】"), text.index("【本片段】"))

    def test_failed_chunk_retry_keeps_original_chunk_label(self):
        worker = NovelAnalysisWorker(
            "http://example.test",
            "key",
            "model",
            "这段完整文本不应该被重新切块",
            max_concurrency=1,
            chunks=[
                {
                    "index": 7,
                    "total": 12,
                    "text": "只重试这一块",
                    "error": "Response ended prematurely",
                }
            ],
        )
        calls = []
        results = []

        def fake_analyze(_prompt, chunk, label, total, use_response_format):
            calls.append((chunk, label, total, use_response_format))
            return {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}, use_response_format

        worker._analyze_chunk_with_retries = fake_analyze
        worker.result_ready.connect(lambda data: results.append(data))

        worker.run()

        self.assertEqual(calls, [("只重试这一块", 7, 12, True)])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get("_chunk_total"), 1)
        self.assertEqual(results[0].get("_chunk_succeeded"), 1)
        self.assertEqual(results[0].get("_failed_chunks"), [])

    def test_analysis_merge_accepts_chinese_top_level_groups(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")
        merged = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}

        worker._merge_analysis_result(merged, {
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
        })

        self.assertEqual(merged["characters"][0]["name"], "赵明")
        self.assertEqual(merged["characters"][0]["goal"], "查清旧案")
        self.assertEqual(merged["lore"][0]["name"], "王城")
        self.assertEqual(merged["foreshadows"][0]["name"], "虎符失踪")
        self.assertEqual(merged["foreshadows"][0]["payoff_chapter"], "第二十章")
        self.assertIn("旧案牵动三代人", merged["project_materials"]["bible"])
        self.assertIn("第一章旧案重启", merged["project_materials"]["timeline"])

    def test_analysis_merge_accepts_material_list_and_top_level_materials(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")
        merged = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}

        worker._merge_analysis_result(merged, {
            "项目资料": [
                {"类型": "小说圣经", "内容": "旧案牵动三代人。"},
                {"类型": "世界观规则", "内容": "王城贵族名册不可伪造。"},
            ],
            "剧情时间线": "第一章旧案重启。",
            "故事摘要": "赵明拿到缺页卷宗。",
        })

        self.assertIn("旧案牵动三代人", merged["project_materials"]["bible"])
        self.assertIn("贵族名册", merged["project_materials"]["world_rules"])
        self.assertIn("第一章旧案重启", merged["project_materials"]["timeline"])
        self.assertIn("缺页卷宗", merged["project_materials"]["summary"])


if __name__ == "__main__":
    unittest.main()
