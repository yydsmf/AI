import json
import unittest

from gpt_desktop.workers import (
    NovelAnalysisWorker,
    NovelCandidatePostprocessWorker,
    NovelChapterTitleWorker,
    NovelForeshadowReviewPostprocessWorker,
    NovelForeshadowReviewWorker,
    NovelWritingWorker,
)


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
        self.assertIn("条数不固定", prompt)
        self.assertIn("重要连续性事实必须保留", prompt)
        self.assertIn("章节结尾的时间、天气、地点、人物位置", prompt)
        self.assertIn("雨停/雨后", prompt)
        self.assertEqual(worker._max_tokens_for_request(), 1200)

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

    def test_draft_prompt_requires_continuity_from_previous_ending_state(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", "context")

        prompt = worker._action_prompt()

        self.assertIn("必须继承承接点里的时间、天气、地点", prompt)
        self.assertIn("雨已停", prompt)
        self.assertIn("不要在下一章开头改成仍在下雨", prompt)

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

    def test_writing_worker_rejects_premature_stream_with_partial_content(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", "context")
        worker._session = _FakeStreamSession([
            'data: {"choices":[{"delta":{"content":"半截正文"}}]}',
        ])
        chunks = []
        errors = []
        results = []
        worker.chunk.connect(chunks.append)
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, content: results.append((action, content)))

        worker.run()

        self.assertEqual(chunks, ["半截正文"])
        self.assertEqual(results, [])
        self.assertTrue(errors)
        self.assertIn("未完整结束", errors[0])

    def test_writing_worker_rejects_length_finish_reason_even_with_done_marker(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", "context")
        worker._session = _FakeStreamSession([
            'data: {"choices":[{"delta":{"content":"半截正文"},"finish_reason":"length"}]}',
            "data: [DONE]",
        ])
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, content: results.append((action, content)))

        worker.run()

        self.assertEqual(results, [])
        self.assertTrue(errors)
        self.assertIn("长度上限", errors[0])
        self.assertIn("续写正文", errors[0])

    def test_writing_worker_accepts_stop_finish_reason_without_done_marker(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", "context")
        worker._session = _FakeStreamSession([
            'data: {"choices":[{"delta":{"content":"完整正文。"},"finish_reason":"stop"}]}',
        ])
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, content: results.append((action, content)))

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(results, [("draft", "完整正文。")])

    def test_draft_worker_rejects_body_that_ends_mid_sentence(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", "context")
        worker._session = _FakeStreamSession([
            'data: {"choices":[{"delta":{"content":"办公室里安静得"},"finish_reason":"stop"}]}',
        ])
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, content: results.append((action, content)))

        worker.run()

        self.assertEqual(results, [])
        self.assertTrue(errors)
        self.assertIn("还没有写完", errors[0])

    def test_outline_worker_allows_compact_unpunctuated_result(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "outline", "context")
        worker._session = _FakeStreamSession([
            'data: {"choices":[{"delta":{"content":"1. 主角进入王城"},"finish_reason":"stop"}]}',
        ])
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, content: results.append((action, content)))

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(results, [("outline", "1. 主角进入王城")])

    def test_chapter_title_worker_normalizes_title_response(self):
        worker = NovelChapterTitleWorker(
            "http://example.test",
            "key",
            "model",
            "书名",
            "都市",
            "轻喜剧",
            [{"title": "第 1 章", "text": "正文一。"}, {"title": "第 2 章", "text": "正文二。"}],
        )

        titles = worker._normalize_titles_response(
            {
                "titles": [
                    {"index": 1, "title": "第 1 章 会议室里的选择"},
                    {"index": 2, "title": "《沉默的副创始人》"},
                ]
            },
            [1, 2],
        )

        self.assertEqual(titles, ["会议室里的选择", "沉默的副创始人"])

    def test_chapter_title_worker_requires_missing_titles_but_allows_quality_variation(self):
        worker = NovelChapterTitleWorker(
            "http://example.test",
            "key",
            "model",
            "书名",
            "",
            "",
            [{"title": "第 1 章", "text": "正文一。"}, {"title": "第 2 章", "text": "正文二。"}],
        )

        with self.assertRaisesRegex(ValueError, "没有为这些章节返回有效标题"):
            worker._normalize_titles_response({"titles": [{"index": 1, "title": "选择"}]}, [1, 2])

        titles = worker._normalize_titles_response(
            {
                "titles": [
                    {"index": 1, "title": "选择"},
                    {"index": 2, "title": "非常非常非常非常非常非常长的标题"},
                ]
            },
            [1, 2],
        )

        self.assertEqual(titles, ["选择", "非常非常非常非常非常非常长的标题"])

        titles = worker._normalize_titles_response(
            {"titles": [{"index": 1, "title": "会议室里的选择"}, {"index": 2, "title": "会议室里的选择"}]},
            [1, 2],
        )

        self.assertEqual(titles, ["会议室里的选择", "会议室里的选择"])

    def test_chapter_title_worker_retries_only_missing_items_in_batch(self):
        worker = NovelChapterTitleWorker(
            "http://example.test",
            "key",
            "model",
            "书名",
            "",
            "",
            [{"title": "第 1 章", "text": "正文一。"}, {"title": "第 2 章", "text": "正文二。"}],
        )
        calls = []

        def fake_request(batch, label, total):
            calls.append(([item["index"] for item in batch], label, total))
            if len(calls) == 1:
                return {1: "会议室里的选择"}
            return {2: "沉默的副创始人"}

        worker._request_title_batch_once = fake_request

        titles = worker._request_title_batch_with_retries(
            [
                {"index": 1, "current_title": "第 1 章", "excerpt": "正文一。"},
                {"index": 2, "current_title": "第 2 章", "excerpt": "正文二。"},
            ],
            1,
            1,
        )

        self.assertEqual(titles, ["会议室里的选择", "沉默的副创始人"])
        self.assertEqual(calls[0][0], [1, 2])
        self.assertEqual(calls[1][0], [2])
        self.assertEqual(calls[1][1], "1.补缺")

    def test_chapter_title_worker_stops_when_missing_retry_still_fails(self):
        worker = NovelChapterTitleWorker(
            "http://example.test",
            "key",
            "model",
            "书名",
            "",
            "",
            [{"title": "第 1 章", "text": "正文一。"}, {"title": "第 2 章", "text": "正文二。"}],
        )

        def fake_request(batch, _label, _total):
            if len(batch) == 2:
                return {1: "会议室里的选择"}
            return {}

        worker._request_title_batch_once = fake_request

        with self.assertRaisesRegex(ValueError, "没有为这些章节返回有效标题"):
            worker._request_title_batch_with_retries(
                [
                    {"index": 1, "current_title": "第 1 章", "excerpt": "正文一。"},
                    {"index": 2, "current_title": "第 2 章", "excerpt": "正文二。"},
                ],
                1,
                1,
            )

    def test_chapter_title_worker_keeps_order_across_batches_with_missing_retry(self):
        worker = NovelChapterTitleWorker(
            "http://example.test",
            "key",
            "model",
            "书名",
            "",
            "",
            [
                {"title": "第 1 章", "text": "正文一。"},
                {"title": "第 2 章", "text": "正文二。"},
                {"title": "第 3 章", "text": "正文三。"},
            ],
        )
        batches = [
            [
                {"index": 1, "current_title": "第 1 章", "excerpt": "正文一。"},
                {"index": 2, "current_title": "第 2 章", "excerpt": "正文二。"},
            ],
            [{"index": 3, "current_title": "第 3 章", "excerpt": "正文三。"}],
        ]
        worker._title_batches = lambda: batches

        def fake_request(batch, _label, _total):
            indexes = [item["index"] for item in batch]
            if indexes == [1, 2]:
                return {1: "会议室里的选择"}
            if indexes == [2]:
                return {2: "沉默的副创始人"}
            return {3: "第三次转身"}

        worker._request_title_batch_once = fake_request
        results = []
        errors = []
        worker.result_ready.connect(results.append)
        worker.failed.connect(errors.append)

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(results, [["会议室里的选择", "沉默的副创始人", "第三次转身"]])

    def test_chapter_title_worker_batches_long_chapters(self):
        worker = NovelChapterTitleWorker(
            "http://example.test",
            "key",
            "model",
            "书名",
            "",
            "",
            [{"title": f"第 {index} 章", "text": "正文。" * 300} for index in range(1, 20)],
        )

        batches = worker._title_batches(max_chars=2200, max_count=5)

        self.assertGreater(len(batches), 1)
        self.assertTrue(all(len(batch) <= 5 for batch in batches))

    def test_chapter_title_worker_falls_back_to_non_stream_when_json_parse_fails(self):
        worker = NovelChapterTitleWorker(
            "http://example.test",
            "key",
            "model",
            "书名",
            "",
            "",
            [{"title": "第 1 章", "text": "正文一。"}],
        )
        calls = []

        def fake_analyze(_prompt, _chunk, label, total, _use_response_format):
            calls.append((label, total, worker._analysis_request_capabilities()))
            if len(calls) == 1:
                raise ValueError("AI 返回的章节标题不是合法 JSON。")
            return {"titles": [{"index": 1, "title": "会议室里的选择"}]}, True

        worker._analyze_chunk_with_retries = fake_analyze

        titles = worker._request_title_batch_with_retries(
            [{"index": 1, "current_title": "第 1 章", "excerpt": "正文一。"}],
            1,
            1,
        )

        self.assertEqual(titles, ["会议室里的选择"])
        self.assertEqual(len(calls), 2)
        self.assertFalse(calls[-1][2][1])

    def test_analysis_prompt_uses_existing_project_dossier_for_dedupe(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")

        prompt = worker._analysis_prompt()

        self.assertIn("已有项目档案", prompt)
        self.assertIn("同名、别称或同一线索不要重复新增", prompt)
        self.assertIn("长期有效的人物变化才写入已有人物 notes", prompt)
        self.assertIn("普通章节行动、临时情绪、一次性互动", prompt)
        self.assertIn("稳定设定变化才写入 lore.description", prompt)
        self.assertIn("本章出现、追问、调查、发送、发现线索、谁去问谁等临时推进", prompt)
        self.assertIn("characters.notes 要求：只写会影响后续多章的人物档案增量", prompt)
        self.assertIn("lore.description 要求：只写后续章节需要继承的稳定设定增量", prompt)
        self.assertIn("没有明确全局增量时，project_materials 对应字段请留空字符串", prompt)
        self.assertIn("timeline 只记录关键转折、时间顺序变化、伏笔推进/回收", prompt)
        self.assertIn("summary 只写对全局剧情有继承价值的简短状态变化", prompt)
        self.assertIn("不要因为固定条数限制丢掉会影响后续章节继承的信息", prompt)
        self.assertIn("设定和伏笔不要原文重复", prompt)
        self.assertIn("lore 写规则本身，foreshadows 改写成待验证/待回收的问题或结果", prompt)
        self.assertIn("名称不要与 lore 完全相同", prompt)
        self.assertIn("foreshadows 要求：只提取会跨章节影响后文的明确线索", prompt)
        self.assertIn("普通悬念、单章情绪钩子、一次性疑问", prompt)
        self.assertIn("不要为了凑数写普通悬念", prompt)
        self.assertIn("不要把已有档案里没有在本片段推进的信息当作新发现重复输出", prompt)

    def test_draft_prompt_distinguishes_relevant_and_open_foreshadows(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", "context")

        prompt = worker._action_prompt()

        self.assertIn("只有【本章相关伏笔】里被本章标题、提纲或正文目标命中的伏笔", prompt)
        self.assertIn("【开放伏笔队列】只用于提醒不要遗忘", prompt)
        self.assertIn("不要提前兑现或解释队列里的伏笔", prompt)

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
        self.assertIn("setup_chapter/payoff_chapter 必须优先填写该真实章节标题", text)
        self.assertIn("不要填写“本片段”“本章”或“第几块”", text)
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

    def test_retryable_chunk_split_is_limited_to_three_parts_once(self):
        worker = NovelAnalysisWorker(
            "http://example.test",
            "key",
            "model",
            "长文本",
            max_concurrency=1,
        )
        worker.retry_attempts = 3
        calls = []
        progress = []
        worker.progress.connect(progress.append)

        def fake_split(_text, max_parts=3):
            self.assertEqual(max_parts, 3)
            return ["子块一" * 700, "子块二" * 700, "子块三" * 700]

        def fake_post(_prompt, chunk, label, _total, _use_response_format):
            calls.append((chunk, label))
            raise RuntimeError("Response ended prematurely")

        worker._split_retry_chunk_once = fake_split
        worker._post_analysis_chunk = fake_post
        worker._post_analysis_chunk_stream = fake_post
        worker._set_analysis_stream_supported(False)

        with self.assertRaises(RuntimeError):
            worker._analyze_chunk_with_retries("prompt", "原始块" * 700, 1, 1, True)

        self.assertEqual([label for _chunk, label in calls], [1, "1.1"])
        self.assertEqual(sum(1 for text in progress if "已自动拆成 3 小块" in text), 1)

    def test_failed_chunk_state_keeps_chapter_metadata_for_retry(self):
        worker = NovelAnalysisWorker(
            "http://example.test",
            "key",
            "model",
            "",
            max_concurrency=1,
            chunks=[
                {
                    "index": 3,
                    "total": 9,
                        "chapter_id": "chapter-3",
                        "chapter_title": "第三章 雨后追问",
                        "review_flow": "foreshadow_review_chapter_compare",
                        "source_label": "章节：第三章 雨后追问",
                        "chunk_key": "章节：第三章 雨后追问#1",
                        "text": "当前章节标题：第三章 雨后追问\n正文：赵明追问虎符线索。",
                    }
                ],
            )
        partials = []

        def fake_analyze(*_args, **_kwargs):
            raise RuntimeError("接口超时")

        worker._analyze_chunk_with_retries = fake_analyze
        worker.partial_ready.connect(lambda data, _done, _total: partials.append(data))

        worker.run()

        self.assertEqual(len(partials), 1)
        failed = partials[0]["_failed_chunks"][0]
        self.assertEqual(failed["index"], 3)
        self.assertEqual(failed["total"], 9)
        self.assertEqual(failed["chapter_id"], "chapter-3")
        self.assertEqual(failed["chapter_title"], "第三章 雨后追问")
        self.assertEqual(failed["review_flow"], "foreshadow_review_chapter_compare")
        self.assertEqual(failed["source_label"], "章节：第三章 雨后追问")
        self.assertEqual(failed["chunk_key"], "章节：第三章 雨后追问#1")

    def test_analysis_chunk_normalizes_foreshadow_chapter_placeholders(self):
        worker = NovelAnalysisWorker(
            "http://example.test",
            "key",
            "model",
            "",
            max_concurrency=1,
            chunks=[
                {
                    "index": 1,
                    "total": 1,
                    "chapter_title": "第十二章 真相揭晓",
                    "text": "赵明揭晓虎符失踪真相。",
                }
            ],
        )
        calls = []
        results = []

        def fake_analyze(_prompt, chunk, label, total, use_response_format):
            calls.append((chunk, label, total, use_response_format))
            return {
                "foreshadows": [
                    {
                        "name": "虎符失踪",
                        "status": "已回收",
                        "setup_chapter": "第 1/1 个文本片段前文",
                        "payoff_chapter": "本片段",
                        "description": "揭晓虎符失踪真相。",
                    }
                ]
            }, use_response_format

        worker._analyze_chunk_with_retries = fake_analyze
        worker.result_ready.connect(results.append)

        worker.run()

        self.assertEqual(len(results), 1)
        item = results[0]["foreshadows"][0]
        self.assertEqual(item["setup_chapter"], "第十二章 真相揭晓")
        self.assertEqual(item["payoff_chapter"], "第十二章 真相揭晓")
        self.assertEqual(item["status"], "已回收")

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

    def test_analysis_merge_keeps_candidate_source_label(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")
        merged = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}

        worker._merge_analysis_result(
            merged,
            {"characters": [{"name": "沈慕白", "notes": "长期关注泄露责任链。"}]},
            source_label="第 2/5 块",
        )
        worker._merge_analysis_result(
            merged,
            {"characters": [{"name": "沈慕白", "notes": "对慕白资本邮箱极度敏感。"}]},
            source_label="第 3/5 块",
        )

        self.assertIn("第 2/5 块", merged["characters"][0]["_source_label"])
        self.assertIn("第 3/5 块", merged["characters"][0]["_source_label"])

    def test_analysis_merge_does_not_overwrite_foreshadow_status_without_explicit_status(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")
        merged = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}

        worker._merge_analysis_result(
            merged,
            {"foreshadows": [{"name": "虎符失踪", "status": "已埋", "description": "半枚虎符首次出现。"}]},
        )
        worker._merge_analysis_result(
            merged,
            {"foreshadows": [{"name": "虎符失踪", "description": "后续牵出兵权交易。"}]},
        )

        self.assertEqual(len(merged["foreshadows"]), 1)
        self.assertEqual(merged["foreshadows"][0]["status"], "已埋")
        self.assertIn("后续牵出兵权交易", merged["foreshadows"][0]["description"])

    def test_analysis_merge_limits_foreshadow_description_supplements(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")
        merged = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}

        worker._merge_analysis_result(
            merged,
            {
                "foreshadows": [
                    {
                        "name": "虎符失踪",
                        "status": "已埋",
                        "description": "半枚虎符首次出现。\n补充：第一章：赵明拿到半枚虎符。",
                    }
                ]
            },
        )
        worker._merge_analysis_result(
            merged,
            {
                "foreshadows": [
                    {
                        "name": "虎符失踪",
                        "payoff_chapter": "第二章",
                        "description": "内库调包痕迹被提到。",
                    }
                ]
            },
        )
        worker._merge_analysis_result(
            merged,
            {
                "foreshadows": [
                    {
                        "name": "虎符失踪",
                        "payoff_chapter": "第三章",
                        "description": "赵明确认虎符被内库调包。\n章节依据：第三章查到调包记录。",
                    }
                ]
            },
        )

        description = merged["foreshadows"][0]["description"]
        self.assertEqual(description.count("补充："), 2)
        self.assertIn("补充：第一章：赵明拿到半枚虎符。", description)
        self.assertIn("补充：第三章：赵明确认虎符被内库调包。；章节依据：第三章查到调包记录。", description)
        self.assertNotIn("第二章：内库调包痕迹被提到。", description)

    def test_analysis_merge_does_not_duplicate_foreshadow_supplement_chapter_source(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")
        merged = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}

        worker._merge_analysis_result(
            merged,
            {
                "foreshadows": [
                    {
                        "name": "旧钟声",
                        "status": "已埋",
                        "description": "钟声提示旧案未结。\n补充：第一章：钟声在夜里响起。",
                    }
                ]
            },
        )
        worker._merge_analysis_result(
            merged,
            {
                "foreshadows": [
                    {
                        "name": "旧钟声",
                        "payoff_chapter": "章节 8",
                        "description": "章节11中，陈景川确认钟声来自旧案密室。",
                    }
                ]
            },
        )

        description = merged["foreshadows"][0]["description"]
        self.assertIn("补充：章节11中，陈景川确认钟声来自旧案密室。", description)
        self.assertNotIn("章节 8：章节11中", description)

    def test_analysis_merge_does_not_downgrade_recovered_foreshadow_status(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")
        merged = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}

        worker._merge_analysis_result(
            merged,
            {"foreshadows": [{"name": "虎符失踪", "status": "已回收", "description": "真相揭晓。"}]},
        )
        worker._merge_analysis_result(
            merged,
            {"foreshadows": [{"name": "虎符失踪", "status": "已埋", "description": "再次提到虎符。"}]},
        )

        self.assertEqual(len(merged["foreshadows"]), 1)
        self.assertEqual(merged["foreshadows"][0]["status"], "已回收")
        self.assertIn("再次提到虎符", merged["foreshadows"][0]["description"])

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

    def test_candidate_postprocess_prompt_requires_dossier_dedupe(self):
        worker = NovelCandidatePostprocessWorker(
            "http://example.test",
            "key",
            "model",
            {"characters": [{"name": "赵明", "notes": "旧案重启。"}]},
            "【已有项目档案】\n- 赵明｜主角",
        )

        prompt = worker._postprocess_prompt()
        user_text = worker._postprocess_user_text()

        self.assertIn("最终合并、去重和对已有项目档案查重", prompt)
        self.assertIn("已有档案里已经稳定存在的信息，不要作为新增候选重复输出", prompt)
        self.assertIn("不确定是否同一对象时分开保留", prompt)
        self.assertIn("伏笔要保守", prompt)
        self.assertIn("分块候选", user_text)
        self.assertIn("赵明", user_text)

    def test_candidate_postprocess_rejects_empty_merged_result(self):
        worker = NovelCandidatePostprocessWorker(
            "http://example.test",
            "key",
            "model",
            {"characters": [{"name": "赵明", "notes": "旧案重启。"}]},
            "【已有项目档案】",
        )
        worker._analyze_chunk_with_retries = lambda *_args, **_kwargs: (
            {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}},
            True,
        )
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(results.append)

        worker.run()

        self.assertEqual(results, [])
        self.assertTrue(errors)
        self.assertIn("没有返回有效候选", errors[0])

    def test_candidate_postprocess_retry_entry_accepts_split_depth_argument(self):
        worker = NovelCandidatePostprocessWorker(
            "http://example.test",
            "key",
            "model",
            {"characters": [{"name": "赵明", "notes": "旧案重启。"}]},
            "【已有项目档案】",
        )
        worker._analysis_request_capabilities = lambda: (False, False)
        worker._post_analysis_chunk = lambda *_args, **_kwargs: {
            "characters": [{"name": "赵明", "notes": "旧案重启。"}],
            "lore": [],
            "foreshadows": [],
            "project_materials": {},
        }

        parsed, _response_format = worker._analyze_chunk_with_retries(
            "prompt",
            "候选合并文本",
            1,
            1,
            True,
        )

        self.assertEqual(parsed["characters"][0]["name"], "赵明")

    def test_foreshadow_review_prompt_is_conservative_and_review_only(self):
        worker = NovelForeshadowReviewWorker(
            "http://example.test",
            "key",
            "model",
            "【现有伏笔列表】\n虎符失踪",
        )

        prompt = worker._analysis_prompt()

        self.assertIn("伏笔观察", prompt)
        self.assertIn("当前章节完整正文", prompt)
        self.assertIn("不要查看、引用或匹配现有伏笔列表", prompt)
        self.assertIn("不要引用摘要、关键事实", prompt)
        self.assertIn("不要凭关键词猜测", prompt)
        self.assertIn("观察待比对", prompt)
        self.assertIn("review_action", prompt)

    def test_foreshadow_review_worker_returns_only_foreshadow_candidates(self):
        worker = NovelForeshadowReviewWorker(
            "http://example.test",
            "key",
            "model",
            "【现有伏笔列表】\n虎符失踪",
            max_concurrency=1,
            chunks=[
                {
                    "index": 1,
                    "total": 1,
                    "chapter_title": "第二章 真相",
                    "text": "当前章节标题：第二章 真相\n正文：虎符失踪真相已经揭晓。",
                }
            ],
        )
        calls = []

        def fake_analyze(prompt, chunk, label, total, use_response_format):
            calls.append((prompt, chunk, label, total, use_response_format))
            return (
                {
                    "characters": [{"name": "赵明", "notes": "不应保留"}],
                    "lore": [{"name": "内库", "description": "不应保留"}],
                    "foreshadows": [
                        {
                            "name": "虎符失踪",
                            "status": "已回收",
                            "payoff_chapter": "本章",
                            "description": "真相已经揭晓。",
                            "review_action": "更新状态",
                            "review_reason": "第二章解释清楚。",
                        }
                    ],
                },
                True,
            )

        worker._analyze_chunk_with_retries = fake_analyze
        results = []
        errors = []
        worker.result_ready.connect(results.append)
        worker.failed.connect(errors.append)

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(calls[0][2:], (1, 1, True))
        request_text = worker._chunk_user_text(calls[0][1], 1, 1)
        self.assertNotIn("【现有伏笔列表】", request_text)
        self.assertIn("【本章完整正文】", request_text)
        self.assertEqual(results[0]["characters"], [])
        self.assertEqual(results[0]["lore"], [])
        self.assertEqual(results[0]["foreshadows"][0]["status"], "已回收")
        self.assertEqual(results[0]["foreshadows"][0]["payoff_chapter"], "第二章 真相")
        self.assertTrue(results[0]["foreshadows"][0].get("_status_explicit"))
        self.assertIn("章节：第二章 真相", results[0]["foreshadows"][0].get("_source_label", ""))
        self.assertIn("体检建议：更新状态", results[0]["foreshadows"][0]["description"])

    def test_foreshadow_review_postprocess_returns_only_foreshadows(self):
        worker = NovelForeshadowReviewPostprocessWorker(
            "http://example.test",
            "key",
            "model",
            {
                "characters": [{"name": "赵明"}],
                "foreshadows": [{"name": "虎符失踪", "status": "已回收", "description": "第二章已经解释虎符去向。"}],
            },
            "【现有伏笔列表】\n虎符失踪",
        )
        calls = []

        def fake_analyze(prompt, chunk, label, total, use_response_format):
            calls.append((prompt, chunk, label, total, use_response_format))
            return (
                {
                    "characters": [{"name": "赵明", "notes": "不应保留"}],
                    "foreshadows": [
                        {
                            "name": "虎符失踪",
                            "status": "已回收",
                            "payoff_chapter": "第二章 真相",
                            "description": "最终确认。",
                        }
                    ],
                },
                True,
            )

        worker._analyze_chunk_with_retries = fake_analyze
        results = []
        errors = []
        worker.result_ready.connect(results.append)
        worker.failed.connect(errors.append)

        worker.run()

        self.assertEqual(errors, [])
        self.assertIn("伏笔连续性总编辑", calls[0][0])
        self.assertIn("对照【现有伏笔列表】", calls[0][0])
        request_text = worker._chunk_user_text(calls[0][1], calls[0][2], calls[0][3])
        self.assertIn("已有项目档案", request_text)
        self.assertIn("本批逐章伏笔观察", request_text)
        self.assertEqual(results[0]["characters"], [])
        self.assertEqual(results[0]["lore"], [])
        self.assertEqual(results[0]["foreshadows"][0]["status"], "已回收")

    def test_foreshadow_review_postprocess_prompt_requires_target_code(self):
        worker = NovelForeshadowReviewPostprocessWorker(
            "http://example.test",
            "key",
            "model",
            {"foreshadows": [{"name": "雨后状态", "description": "第九章重复写雨。"}]},
            "【现有伏笔列表】\n编号：F0007｜名称：雨后状态",
        )

        prompt = worker._analysis_prompt()

        self.assertIn("target_code", prompt)
        self.assertIn("命中编号", prompt)

    def test_foreshadow_review_postprocess_merge_stops_after_terminal_candidate(self):
        worker = NovelForeshadowReviewPostprocessWorker(
            "http://example.test",
            "key",
            "model",
            {"foreshadows": []},
            "【现有伏笔列表】",
        )
        output = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}

        worker._merge_analysis_result(output, {
            "foreshadows": [
                {
                    "name": "陈景川与陈远山景辰总部正面交锋",
                    "status": "废弃",
                    "description": "体检建议：移出伏笔\n判断依据：场域已被正文修正。",
                    "target_code": "F0055",
                    "review_action": "移出伏笔",
                }
            ]
        })
        worker._merge_analysis_result(output, {
            "foreshadows": [
                {
                    "name": "陈景川与陈远山景辰总部正面交锋",
                    "status": "已回收",
                    "description": "体检建议：更新状态\n判断依据：后续章节再次提到。",
                    "target_code": "F0055",
                    "review_action": "更新状态",
                }
            ]
        })

        self.assertEqual(len(output["foreshadows"]), 1)
        self.assertEqual(output["foreshadows"][0]["status"], "废弃")
        self.assertIn("移出伏笔", output["foreshadows"][0]["description"])
        self.assertNotIn("后续章节再次提到", output["foreshadows"][0]["description"])

    def test_foreshadow_review_postprocess_merge_keeps_earliest_terminal_chapter(self):
        worker = NovelForeshadowReviewPostprocessWorker(
            "http://example.test",
            "key",
            "model",
            {"foreshadows": []},
            "【现有伏笔列表】",
        )
        output = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}

        worker._merge_analysis_result(output, {
            "foreshadows": [
                {
                    "name": "陈景川与陈远山景辰总部正面交锋",
                    "status": "废弃",
                    "description": "第九章后续再次提到该旧线索。",
                    "target_code": "F0055",
                    "review_action": "移出伏笔",
                    "evidence": "第九章",
                }
            ]
        })
        worker._merge_analysis_result(output, {
            "foreshadows": [
                {
                    "name": "陈景川与陈远山景辰总部正面交锋",
                    "status": "废弃",
                    "description": "章节 7 首次证明总部交锋场域已被正文修正。",
                    "target_code": "F0055",
                    "review_action": "移出伏笔",
                    "evidence": "章节 7 陈家老宅通知",
                }
            ]
        })

        self.assertEqual(len(output["foreshadows"]), 1)
        self.assertIn("章节 7", output["foreshadows"][0]["description"])
        self.assertNotIn("第九章后续", output["foreshadows"][0]["description"])

    def test_foreshadow_review_postprocess_chunks_many_observations(self):
        candidates = {
            "foreshadows": [
                {
                    "name": f"线索{i}",
                    "description": "这一章留下需要后续比对的完整观察证据。" * 40,
                }
                for i in range(30)
            ]
        }

        chunks = NovelForeshadowReviewPostprocessWorker._build_observation_chunks(
            candidates,
            dossier="【现有伏笔列表】\n" + ("旧伏笔说明。" * 2000),
        )

        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0]["total"], len(chunks))
        for chunk in chunks:
            records = json.loads(chunk["text"])
            self.assertTrue(records)
            self.assertIn("name", records[0])


class _FakeStreamResponse:
    status_code = 200
    encoding = "utf-8"

    def __init__(self, lines):
        self._lines = [line.encode("utf-8") if isinstance(line, str) else line for line in lines]
        self.closed = False

    def iter_lines(self, decode_unicode=False):
        yield from self._lines

    def close(self):
        self.closed = True


class _FakeStreamSession:
    trust_env = False

    def __init__(self, lines):
        self._response = _FakeStreamResponse(lines)
        self.closed = False

    def post(self, *_args, **_kwargs):
        return self._response

    def close(self):
        self.closed = True


if __name__ == "__main__":
    unittest.main()
