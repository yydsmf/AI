import json
import hashlib
import threading
import unittest
from unittest.mock import patch

import gpt_desktop.workers as workers_module
from gpt_desktop.core import reasoning_effort_for_model

from gpt_desktop.workers import (
    NovelAnalysisWorker,
    NovelCandidatePostprocessWorker,
    NovelChapterPlanMasterWorker,
    NovelChapterPlanWorker,
    NovelChapterTitleWorker,
    NovelFrameworkImportWorker,
    NovelForeshadowReviewPostprocessWorker,
    NovelForeshadowReviewWorker,
    NovelVolumeHandoffWorker,
    NovelVolumeFrameworkWorker,
    NovelWritingWorker,
)


class NovelAnalysisWorkerTests(unittest.TestCase):
    def test_framework_and_chapter_planning_reasoning_is_fixed_at_high(self):
        for action in ("框架分类", "全书阶段规划", "章节规划"):
            with self.subTest(action=action):
                self.assertEqual(
                    reasoning_effort_for_model(
                        "gpt-5.6-sol", "https://api.dxmcs.xin", action
                    ),
                    "high",
                )

    def test_volume_handoff_run_finalizes_success_diagnostics(self):
        worker = NovelVolumeHandoffWorker(
            "http://example.test",
            "key",
            "gpt-5.6-sol",
            {
                "summary": "第一卷已结束。",
                "records": {"characters": [], "lore": [], "foreshadows": []},
                "last_chapter": {"title": "第一卷终章", "text": "终章正文。"},
            },
        )
        results = []
        errors = []
        worker._analyze_chunk_with_retries = lambda *_args, **_kwargs: (
            {"volume_summary": "交接完成"},
            True,
        )
        worker.result_ready.connect(results.append)
        worker.failed.connect(errors.append)

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(worker.diagnostics["outcome"], "success")
        self.assertTrue(worker.diagnostics["started_at"])
        self.assertTrue(worker.diagnostics["finished_at"])

    def test_volume_framework_run_finalizes_error_diagnostics(self):
        worker = NovelVolumeFrameworkWorker(
            "http://example.test",
            "key",
            "gpt-5.6-sol",
            {"volume_summary": "交接资料"},
            "第二卷要求",
            "小说模板",
        )
        errors = []
        worker._analyze_chunk_with_retries = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("upstream timeout")
        )
        worker.failed.connect(errors.append)

        worker.run()

        self.assertEqual(len(errors), 1)
        self.assertEqual(worker.diagnostics["outcome"], "error")
        self.assertEqual(worker.diagnostics["error_type"], "RuntimeError")
        self.assertIn("upstream timeout", worker.diagnostics["error"])
        self.assertTrue(worker.diagnostics["traceback"])

    def test_upstream_gateway_failures_are_retryable_for_volume_framework(self):
        worker = NovelVolumeFrameworkWorker(
            "http://example.test",
            "key",
            "model",
            {},
            "继续第一卷主线",
            "小说模板",
        )

        for message in (
            "Upstream request failed",
            "upstream service temporarily unavailable",
            "接口错误 502：Upstream request failed",
        ):
            with self.subTest(message=message):
                self.assertTrue(worker._is_retryable_analysis_error(RuntimeError(message)))

    def test_chapter_plan_worker_normalizes_structured_plan(self):
        worker = NovelChapterPlanWorker("http://example.test", "key", "model", "context", 200000, 3000, 2, 20)

        plan = worker._normalize_plan({
            "summary": "第一卷先立主线。",
            "narrative_strategy_profile": {"primary_story_engine": "不应被批次覆盖"},
            "chapters": [
                {
                    "index": 2,
                    "title": "第2章：风雨入城",
                    "target_words": "3200字",
                    "source_stage": "第1-10章：城市立足",
                    "dominant_line": "人物冲突",
                    "relationship_task": "建立临时信任",
                    "investigation_scope": "只保留卷宗带来的一个新结果",
                    "dynamic_modules": ["关系试探", "身份错位", "公开结果"],
                    "outline": "本章目标：主角进入京城。",
                    "characters": "陈景川、林晚",
                    "settings": ["景辰总部"],
                    "foreshadows": "F0001 风雨信号",
                    "ending_hook": "旧案卷宗出现。",
                    "forbidden": "不要提前揭晓幕后人。",
                    "source_event_ids": ["s01-e03", "S01-E04"],
                },
                {
                    "index": 1,
                    "title": "第一章 初到",
                    "goal": "建立主角处境",
                    "required_events": ["收到通知"],
                },
            ],
        })

        self.assertEqual(plan["chapter_count"], 2)
        self.assertEqual(plan["total_chapter_count"], 20)
        self.assertEqual(plan["existing_chapter_count"], 0)
        self.assertEqual([chapter["index"] for chapter in plan["chapters"]], [1, 2])
        self.assertEqual(plan["chapters"][0]["title"], "初到")
        self.assertEqual(plan["chapters"][0]["narrative_stage"], "强钩子阶段")
        self.assertIn("建立主角处境", plan["chapters"][0]["outline"])
        self.assertEqual(plan["chapters"][1]["title"], "风雨入城")
        self.assertEqual(plan["chapters"][1]["target_words"], "3200")
        self.assertEqual(plan["chapters"][1]["source_stage"], "第1-10章：城市立足")
        self.assertEqual(plan["chapters"][1]["dominant_line"], "人物冲突")
        self.assertEqual(plan["chapters"][1]["characters"], ["陈景川", "林晚"])
        self.assertEqual(plan["chapters"][1]["source_event_ids"], ["S01-E03", "S01-E04"])
        self.assertEqual(plan["chapters"][1]["relationship_task"], "建立临时信任")
        self.assertEqual(
            plan["chapters"][1]["investigation_scope"],
            "只保留卷宗带来的一个新结果",
        )
        self.assertEqual(
            plan["chapters"][1]["dynamic_modules"],
            ["关系试探", "身份错位", "公开结果"],
        )
        self.assertEqual(plan["chapters"][1]["settings"], ["景辰总部"])
        self.assertEqual(plan["chapters"][1]["forbidden"], "不要提前揭晓幕后人。")
        self.assertNotIn("summary", plan)
        self.assertNotIn("narrative_strategy_profile", plan)

    def test_chapter_plan_worker_rejects_range_or_volume_as_single_chapter_title(self):
        worker = NovelChapterPlanWorker(
            "http://example.test", "key", "model", "context", 500000, 2000, 1, 250
        )

        for title in ("第4—10章：新婚立威", "第二卷：首辅夫人搞钱"):
            with self.subTest(title=title), self.assertRaisesRegex(ValueError, "范围或分卷标题"):
                worker._normalize_plan({
                    "chapters": [{"index": 1, "title": title, "outline": "推进主线。"}],
                })

    def test_chapter_plan_prompt_requires_json_and_chapter_count(self):
        worker = NovelChapterPlanWorker("http://example.test", "key", "model", "context", 200000, 3000, 67, 67)

        prompt = worker._analysis_prompt()

        self.assertIn("必须只输出一个合法 JSON 对象", prompt)
        self.assertIn("必须输出接下来的 67 章", prompt)
        self.assertIn("不要擅自推翻小说圣经和世界规则", prompt)
        self.assertIn("outline是提纲里的故事正文", prompt)
        self.assertIn("像这本小说的作者在讲述下一章", prompt)
        self.assertIn("不超过300个字符（含标点、不计空白）", prompt)
        self.assertIn("不要复述字段含义", prompt)
        self.assertIn("不必按处境、阻力、选择、后果的固定次序", prompt)
        self.assertIn("narrative_strategy_profile", prompt)
        self.assertIn("用户已确认的只读规划基础", prompt)
        self.assertIn("不得重新生成、改写、总结或返回", prompt)
        self.assertNotIn('JSON 结构：{"summary"', prompt)
        self.assertNotIn('"narrative_strategy_profile":{}', prompt)
        self.assertIn("符合当前题材的阅读期待", prompt)
        self.assertIn("长期状态推进", prompt)
        self.assertIn("不能让同一句状态原样跨多个章节", prompt)
        self.assertIn("恢复或解决必须有资料中已有或剧情自然建立的时间、资源、事件依据", prompt)
        self.assertIn("不写固定伏笔任务", prompt)
        self.assertIn("伏笔由后续扩写正文和正文分析根据实际内容动态处理", prompt)
        self.assertIn("前 10%", prompt)
        self.assertIn("中间 70%", prompt)
        self.assertIn("后 20%", prompt)
        self.assertIn("不能决定本章写什么题材内容", prompt)
        self.assertIn("项目资料是连续性事实参考，不是本章待办清单", prompt)
        self.assertIn("提纲正文应讲述人物真正会经历的故事", prompt)
        self.assertIn("narrative_stage", prompt)
        self.assertIn("source_stage", prompt)
        self.assertIn("dominant_line", prompt)
        self.assertIn("提纲仍给正文留下场景、对白和节奏空间", prompt)
        self.assertIn("不安排任何固定的工作步骤或说明流程", prompt)
        self.assertIn("有题材气质的叙述", prompt)
        self.assertNotIn('"planning_method"', prompt)
        self.assertNotIn('"dynamic_modules"', prompt)
        self.assertNotIn('"satisfaction_payoff"', prompt)
        self.assertNotIn('"emotional_resonance"', prompt)
        self.assertNotIn('"exposition_compression"', prompt)
        self.assertIn("source_event_ids", prompt)
        self.assertIn("不得把事件序号当作章号", prompt)
        self.assertIn("每个节点只能使用一次", prompt)
        self.assertNotIn('"foreshadow_task"', prompt)
        self.assertNotIn('"foreshadows"', prompt)
        self.assertNotIn('"settings"', prompt)
        self.assertNotIn('"forbidden"', prompt)
        self.assertNotIn('"chapter_function"', prompt)
        self.assertNotIn('"character_task"', prompt)
        self.assertNotIn('"mainline_task"', prompt)

    def test_chapter_plan_master_requires_contiguous_full_book_coverage(self):
        worker = NovelChapterPlanMasterWorker(
            "http://example.test", "key", "model", "context", 500000, 2000, 250
        )
        self.assertTrue(worker._retry_stream_transport_before_nonstream)

        plan = worker._normalize_master_plan({
            "summary": "全书主线持续推进到终局。",
            "core_mainline": "主角通过能力成长改变家族命运。",
            "ending_promise": "主角完成身份跃迁并兑现关系承诺。",
            "global_hard_boundaries": "不得把成长主线改成办案主线。",
            "arcs": [
                {
                    "name": f"阶段{index + 1}",
                    "start_chapter": index * 25 + 1,
                    "end_chapter": (index + 1) * 25,
                    "macro_phase": "主线扩展阶段",
                    "source_stage": f"原框架阶段{index + 1}",
                    "dominant_line": "人物成长",
                    "supporting_lines": "轻悬疑",
                    "relationship_goal": "关系向前变化",
                    "goal": "推进主线",
                    "end_state": "进入下一阶段",
                    "investigation_scope": "流程只保留改变结果的一步",
                    "main_conflict": "旧任务型冲突",
                    "turning_points": "固定转折",
                    "reader_payoff": "固定兑现",
                }
                for index in range(10)
            ],
        })

        self.assertEqual(len(plan["arcs"]), 10)
        self.assertEqual(plan["arcs"][0]["start_chapter"], 1)
        self.assertEqual(plan["arcs"][-1]["end_chapter"], 250)
        self.assertEqual(plan["arcs"][0]["source_stage"], "原框架阶段1")
        self.assertEqual(plan["arcs"][0]["dominant_line"], "人物成长")
        self.assertEqual(
            plan["arcs"][0]["investigation_scope"],
            "流程只保留改变结果的一步",
        )
        self.assertEqual(plan["arcs"][0]["goal"], "推进主线")
        self.assertEqual(plan["arcs"][0]["main_conflict"], "旧任务型冲突")
        self.assertEqual(plan["arcs"][0]["turning_points"], "固定转折")
        self.assertEqual(plan["arcs"][0]["reader_payoff"], "固定兑现")
        self.assertEqual(plan["arcs"][0]["supporting_lines"], "轻悬疑")
        self.assertIn("家族命运", plan["core_mainline"])
        self.assertIn("身份跃迁", plan["ending_promise"])
        self.assertIn("办案主线", plan["global_hard_boundaries"])

        with self.assertRaisesRegex(ValueError, "不连续"):
            worker._normalize_master_plan({
                "arcs": [
                    {"name": "阶段1", "start_chapter": 1, "end_chapter": 25},
                    {"name": "阶段2", "start_chapter": 27, "end_chapter": 250},
                ]
            })

        chapter_label_plan = worker._normalize_master_plan({
            "arcs": [
                {
                    "name": f"阶段{index + 1}",
                    "start_chapter": f"第{index * 25 + 1}章",
                    "end_chapter": f"第{(index + 1) * 25}章",
                }
                for index in range(10)
            ],
        })
        self.assertEqual(chapter_label_plan["arcs"][0]["start_chapter"], 1)
        self.assertEqual(chapter_label_plan["arcs"][-1]["end_chapter"], 250)

        wrapped_plan = worker._normalize_master_plan({
            "master_plan": {
                "summary": "包装后的全书规划",
                "strategy_profile": {"primary_story_engine": "人物成长"},
                "stages": [
                    {
                        "阶段名称": f"阶段{index + 1}",
                        "开始章节": f"第{index * 25 + 1}章",
                        "结束章节": f"第{(index + 1) * 25}章",
                    }
                    for index in range(10)
                ],
            },
        })
        self.assertEqual(wrapped_plan["summary"], "包装后的全书规划")
        self.assertEqual(wrapped_plan["arcs"][0]["name"], "阶段1")
        self.assertEqual(
            wrapped_plan["narrative_strategy_profile"]["primary_story_engine"],
            "人物成长",
        )

    def test_chapter_plan_master_prompt_starts_after_existing_chapters(self):
        worker = NovelChapterPlanMasterWorker(
            "http://example.test",
            "key",
            "model",
            "context",
            500000,
            2000,
            250,
            existing_chapter_count=34,
        )

        prompt = worker._analysis_prompt()

        self.assertIn("第一个阶段必须从第35章开始", prompt)
        self.assertIn('"start_chapter":35', prompt)
        self.assertIn("阶段边界和阶段顺序", prompt)
        self.assertIn("stages.events", prompt)
        self.assertIn("用户原始框架的具体章段", prompt)
        self.assertIn("如果原框架明确分卷或分阶段", prompt)
        self.assertIn("narrative_strategy_profile", prompt)
        self.assertIn('"core_mainline":""', prompt)
        self.assertIn('"ending_promise":""', prompt)
        self.assertNotIn('"global_hard_boundaries"', prompt)
        self.assertNotIn('"forbidden_drift"', prompt)
        self.assertIn("不能借空白转入下一阶段", prompt)
        self.assertIn("arcs必须一次性返回完整阶段数组", prompt)
        self.assertIn("严禁只返回第一个阶段", prompt)
        self.assertIn("实际JSON必须展开全部阶段", prompt)
        self.assertIn("不能让同一句状态原样跨多个章节", prompt)
        self.assertIn("恢复或解决必须有资料中已有或剧情自然建立的时间、资源、事件依据", prompt)

    def test_chapter_plan_master_repairs_incomplete_ranges_from_previous_result(self):
        context = (
            "请根据项目规划。\n\n"
            + json.dumps({
                "target": {"estimated_total_chapters": 40},
                "meta": {"title": "谎言回收店"},
                "project_materials": {"bible": "全书五卷。", "world_rules": "谎言可以成物。"},
                "imported_chapter_plan_reference": {"summary": "第一卷到第五卷各约四万字。"},
            }, ensure_ascii=False)
        )
        worker = NovelChapterPlanMasterWorker(
            "http://example.test", "key", "model", context, 200000, 5000, 40
        )
        incomplete = {
            "summary": "完整全书走向",
            "narrative_strategy_profile": {"primary_story_engine": "女性成长"},
            "arcs": [{"name": "第一卷", "start_chapter": 1, "end_chapter": 25}],
        }
        repaired = {
            "summary": "完整全书走向",
            "narrative_strategy_profile": {"primary_story_engine": "女性成长"},
            "arcs": [
                {"name": "第一卷", "start_chapter": 1, "end_chapter": 20},
                {"name": "后续卷", "start_chapter": 21, "end_chapter": 40},
            ],
        }
        calls = []
        progress = []
        results = []
        errors = []

        def fake_analyze(prompt, chunk, label, total, use_response_format):
            calls.append((prompt, chunk, label, total, use_response_format))
            return (incomplete if len(calls) == 1 else repaired), use_response_format

        worker._analyze_chunk_with_retries = fake_analyze
        worker.progress.connect(progress.append)
        worker.result_ready.connect(results.append)
        worker.failed.connect(errors.append)

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["arcs"][-1]["end_chapter"], 40)
        self.assertEqual(len(calls), 2)
        self.assertIn("结构补正编辑", calls[1][0])
        self.assertIn('"previous_plan"', calls[1][1])
        self.assertIn("第一卷到第五卷", calls[1][1])
        self.assertTrue(any("1-25" in text and "只覆盖到第25章" in text for text in progress))
        self.assertFalse(any("重做总规划" in text for text in progress))
        self.assertEqual(worker.diagnostics["structure_repair_count"], 1)
        self.assertEqual(worker.diagnostics["structure_regeneration_count"], 0)
        self.assertEqual(worker.diagnostics["outcome"], "success")
        self.assertGreaterEqual(worker.diagnostics["elapsed_ms"], 0)

    def test_chapter_plan_batch_records_structure_regeneration(self):
        worker = NovelChapterPlanWorker(
            "http://example.test", "key", "gpt-5.6-sol", "context", 200000, 5000, 1, 40
        )
        calls = []
        results = []
        errors = []

        def fake_analyze(*_args):
            calls.append(1)
            if len(calls) == 1:
                return {"chapters": []}, True
            return {
                "chapters": [
                    {"index": 1, "title": "第一章 开局", "outline": "主角被迫入局。"}
                ]
            }, True

        worker._analyze_chunk_with_retries = fake_analyze
        worker.result_ready.connect(results.append)
        worker.failed.connect(errors.append)

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(worker.diagnostics["requested_model"], "gpt-5.6-sol")
        self.assertEqual(worker.diagnostics["structure_regeneration_count"], 1)
        self.assertEqual(worker.diagnostics["structure_repair_count"], 0)
        self.assertEqual(worker.diagnostics["outcome"], "success")

    def test_chapter_plan_stage_uses_existing_chapters_when_appending(self):
        worker = NovelChapterPlanWorker(
            "http://example.test",
            "key",
            "model",
            "context",
            300000,
            3000,
            1,
            total_chapter_count=100,
            existing_chapter_count=85,
        )
        self.assertTrue(worker._retry_stream_transport_before_nonstream)

        plan = worker._normalize_plan({
            "chapters": [
                {
                    "index": 1,
                    "title": "终局前夜",
                    "outline": "主角进入最终对抗前夜。",
                    "chapter_function": "终局压力升级",
                    "conflict_intensity": "极高",
                }
            ],
        })

        self.assertEqual(plan["total_chapter_count"], 100)
        self.assertEqual(plan["existing_chapter_count"], 85)
        self.assertEqual(plan["chapters"][0]["narrative_stage"], "收束升级阶段")
        self.assertEqual(plan["chapters"][0]["chapter_function"], "终局压力升级")
        self.assertEqual(plan["chapters"][0]["conflict_intensity"], "极高")

    def test_chapter_plan_retry_does_not_split_context(self):
        context = "项目资料" * 1000
        worker = NovelChapterPlanWorker("http://example.test", "key", "model", context, 200000, 3000, 1)
        worker.retry_attempts = 2
        calls = []
        progress = []
        worker.progress.connect(progress.append)

        def fail_split(_text, max_parts=3):
            raise AssertionError("章节规划不应该自动拆小块重试")

        def fake_stream(_prompt, chunk, label, total, use_response_format):
            calls.append(("stream", chunk, label, total, use_response_format))
            if len(calls) == 1:
                raise RuntimeError("Response ended prematurely")
            return {
                "summary": "第一卷开局。",
                "chapters": [
                    {
                        "index": 1,
                        "title": "风起京城",
                        "outline": "本章目标：建立主角处境。",
                    }
                ],
            }

        worker._split_retry_chunk_once = fail_split
        worker._post_analysis_chunk_stream = fake_stream

        parsed, _response_format = worker._analyze_chunk_with_retries("prompt", context, 1, 1, True)

        self.assertEqual(len(calls), 2)
        self.assertEqual([call[0] for call in calls], ["stream", "stream"])
        self.assertEqual([call[1] for call in calls], [context, context])
        self.assertEqual([call[2] for call in calls], [1, 1])
        self.assertEqual(parsed["chapters"][0]["title"], "风起京城")
        self.assertFalse(any("自动拆成" in text for text in progress))

    def test_chapter_plan_json_retry_stays_streaming(self):
        worker = NovelChapterPlanWorker("http://example.test", "key", "model", "context", 200000, 3000, 1)
        worker.retry_attempts = 2
        worker._analysis_retry_wait_seconds = lambda *_args: 0
        calls = []

        def fake_stream(*_args, **_kwargs):
            calls.append("stream")
            if len(calls) == 1:
                raise ValueError("AI 返回内容不是合法 JSON。解析位置：第 1 行，第 20 列。")
            return {
                "chapters": [{
                    "index": 1,
                    "title": "风起京城",
                    "outline": "主角进入新的处境。",
                }],
            }

        def unexpected_nonstream(*_args, **_kwargs):
            raise AssertionError("章节规划的流式重试不应降级为普通请求")

        worker._post_analysis_chunk_stream = fake_stream
        worker._post_analysis_chunk = unexpected_nonstream

        parsed, _response_format = worker._analyze_chunk_with_retries(
            "prompt", "context", 1, 1, True
        )

        self.assertEqual(calls, ["stream", "stream"])
        self.assertEqual(parsed["chapters"][0]["title"], "风起京城")

    def test_chapter_plan_does_not_fallback_to_nonstream_when_stream_is_unsupported(self):
        worker = NovelChapterPlanWorker("http://example.test", "key", "model", "context", 200000, 3000, 1)

        def fake_stream(*_args, **_kwargs):
            raise RuntimeError("stream is not supported")

        def unexpected_nonstream(*_args, **_kwargs):
            raise AssertionError("章节规划不应切换到长时间普通请求")

        worker._post_analysis_chunk_stream = fake_stream
        worker._post_analysis_chunk = unexpected_nonstream

        with self.assertRaisesRegex(RuntimeError, "不支持流式输出"):
            worker._analyze_chunk_resilient("prompt", "context", 1, 1, True)

    def test_rate_limit_error_retries_after_ten_seconds(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "正文")
        worker.retry_attempts = 2
        calls = []
        progress = []
        worker.progress.connect(progress.append)

        def fake_resilient(prompt, chunk, label, total, use_response_format, split_depth=0):
            calls.append((prompt, chunk, label, total, use_response_format, split_depth))
            if len(calls) == 1:
                raise RuntimeError("Concurrency limit exceeded for user, please retry later")
            return {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}, use_response_format

        worker._analyze_chunk_resilient = fake_resilient
        with patch.object(workers_module.time, "time", side_effect=[0, 11]), patch.object(workers_module.time, "sleep"):
            parsed, _response_format = worker._analyze_chunk_with_retries("prompt", "正文", 1, 1, True)

        self.assertEqual(len(calls), 2)
        self.assertEqual(parsed["characters"], [])
        self.assertTrue(any("接口并发限制" in text and "10 秒后自动重试 2/2" in text for text in progress))
        self.assertEqual(worker.diagnostics["retry_count"], 1)

    def test_analysis_stream_diagnostics_capture_response_model_and_sizes(self):
        worker = NovelAnalysisWorker(
            "http://example.test", "key", "gpt-5.6-sol", "项目资料"
        )
        payload = {
            "model": "gpt-5.6-sol",
            "choices": [{
                "delta": {"content": json.dumps({
                    "characters": [],
                    "lore": [],
                    "foreshadows": [],
                    "project_materials": {},
                }, ensure_ascii=False)},
                "finish_reason": "stop",
            }],
        }
        session = _FakeStreamSession([
            f"data: {json.dumps(payload, ensure_ascii=False)}",
            "data: [DONE]",
        ])
        session._response.headers = {
            "x-request-id": "request-123",
            "x-upstream-model": "gpt-5.6-sol",
        }
        worker._new_session = lambda: session

        parsed = worker._post_analysis_chunk_stream(
            "系统提示词", "本次规划上下文", 1, 1, True
        )

        self.assertEqual(parsed["characters"], [])
        self.assertEqual(worker.diagnostics["api_call_count"], 1)
        self.assertEqual(worker.diagnostics["response_models"], ["gpt-5.6-sol"])
        attempt = worker.diagnostics["attempts"][0]
        self.assertEqual(attempt["requested_model"], "gpt-5.6-sol")
        self.assertEqual(attempt["response_model"], "gpt-5.6-sol")
        self.assertEqual(attempt["system_prompt_chars"], len("系统提示词"))
        self.assertGreater(attempt["user_text_chars"], len("本次规划上下文"))
        self.assertGreater(attempt["response_chars"], 0)
        self.assertEqual(attempt["finish_reason"], "stop")
        self.assertEqual(attempt["response_headers"]["x-request-id"], "request-123")
        self.assertGreaterEqual(attempt["time_to_headers_ms"], 0)
        self.assertGreaterEqual(attempt["time_to_first_piece_ms"], 0)
        self.assertEqual(attempt["content_chars"], attempt["response_chars"])
        self.assertEqual(attempt["reasoning_chars"], 0)
        self.assertTrue(attempt["received_done"])
        self.assertGreaterEqual(attempt["max_idle_gap_ms"], 0)
        self.assertEqual(worker.diagnostics["content_chars"], attempt["content_chars"])
        self.assertEqual(attempt["outcome"], "success")

    def test_rate_limit_error_does_not_split_large_chunk(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "正文")
        worker._set_analysis_stream_supported(False)
        large_chunk = "正文" * 1000

        def fail_post(*_args, **_kwargs):
            raise RuntimeError("Concurrency limit exceeded for user, please retry later")

        def fail_split(*_args, **_kwargs):
            raise AssertionError("并发限制不应该拆小块重试")

        worker._post_analysis_chunk = fail_post
        worker._split_retry_chunk_once = fail_split

        with self.assertRaisesRegex(RuntimeError, "Concurrency limit exceeded"):
            worker._analyze_chunk_resilient("prompt", large_chunk, 1, 1, True)

    def test_summary_prompt_requires_linked_characters_section(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "summary", "context")

        prompt = worker._action_prompt()

        self.assertIn("本章摘要", prompt)
        self.assertIn("本章需继承的关键事实", prompt)
        self.assertIn("本章关联人物", prompt)
        self.assertIn("具体姓名", prompt)
        self.assertIn("不要只写主角/反派/配角", prompt)
        self.assertIn("成熟的商业小说作者兼责任编辑", prompt)
        self.assertIn("连续性备忘录", prompt)
        self.assertIn("不写剧情复述", prompt)
        self.assertIn("不设固定条数", prompt)
        self.assertIn("事实完整、表达短", prompt)
        self.assertIn("重要连续性事实必须保留", prompt)
        self.assertIn("章节结尾的时间、天气、地点、人物位置", prompt)
        self.assertIn("雨停/雨后", prompt)
        self.assertEqual(worker._max_tokens_for_request(), 6000)

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

    def test_memory_repair_patch_uses_smaller_output_budget(self):
        full_worker = NovelWritingWorker(
            "http://example.test", "key", "model", "memory_repair", "完整修复上下文"
        )
        patch_worker = NovelWritingWorker(
            "http://example.test",
            "key",
            "model",
            "memory_repair",
            "【状态增量修复补丁】\n只替换错误字段。",
        )

        self.assertEqual(full_worker._max_tokens_for_request(), 8000)
        self.assertEqual(patch_worker._max_tokens_for_request(), 6000)

    def test_fiction_prompts_include_body_specific_quality_requirements(self):
        for action in ("draft", "script_to_novel"):
            with self.subTest(action=action):
                worker = NovelWritingWorker("http://example.test", "key", "model", action, "context")

                prompt = worker._action_prompt()

                self.assertIn("让人物的欲望、阻力、选择和后果自然形成推进", prompt)
                self.assertIn("不设细节数量配额", prompt)
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

    def test_draft_prompt_with_style_reference_uses_minimal_full_sample_guidance(self):
        worker = NovelWritingWorker(
            "http://example.test",
            "key",
            "model",
            "draft",
            "【当前章节】\n剧情资料。\n\n【正文风格参考】\n样本正文。",
        )

        prompt = worker._action_prompt()

        self.assertIn("当前项目资料决定故事事实", prompt)
        self.assertIn("完整原样本提供本次仿写的写法来源", prompt)
        self.assertIn("已经确定的人名、时间、地点、关系、物件、编号、人物状态和已发生事件", prompt)
        self.assertNotIn("唯一写法标准", prompt)
        self.assertNotIn("【风格锁定规则】", prompt)
        self.assertNotIn("不要自行追求多动作、多对白", prompt)
        self.assertNotIn("作者原生用词池", prompt)
        self.assertNotIn("中段必须出现一次意料之外", prompt)
        self.assertNotIn("至少写出 3 处具体可见细节", prompt)
        self.assertNotIn("多用动作和对话推进", prompt)

    def test_style_execution_draft_uses_specialized_three_part_contract(self):
        worker = NovelWritingWorker(
            "http://example.test",
            "key",
            "model",
            "draft",
            "本章扩写字数：3000字\n【剧情执行稿任务】\n输出清单和备用正文。",
        )

        prompt = worker._action_prompt()

        self.assertIn("剧情与声纹执行编辑", prompt)
        self.assertIn("无需阅读备用草稿措辞也能从零写作", prompt)
        self.assertIn("唯一剧情拍点", prompt)
        self.assertNotIn("静默继承边界", prompt)
        self.assertIn("后续正文验收与修复阶段", prompt)
        self.assertIn("不得把同一场对话", prompt)
        self.assertIn("本章声纹执行表", prompt)
        self.assertIn("三个分区标题", prompt)
        self.assertEqual(worker._max_tokens_for_request(), 11000)

    def test_style_profile_audit_and_rewrite_prompts_are_specialized(self):
        profile_worker = NovelWritingWorker("http://example.test", "key", "model", "style_profile", "样本")
        finalize_worker = NovelWritingWorker(
            "http://example.test", "key", "model", "style_finalize", "本章扩写字数：3000字"
        )
        audit_worker = NovelWritingWorker("http://example.test", "key", "model", "style_audit", "样本和候选")
        rewrite_worker = NovelWritingWorker(
            "http://example.test",
            "key",
            "model",
            "style_rewrite",
            "【正文风格参考】\n样本\n\n【风格验收未通过：本次必须重写】\n要求",
        )
        plot_worker = NovelWritingWorker("http://example.test", "key", "model", "style_plot_extract", "候选")
        baseline_worker = NovelWritingWorker("http://example.test", "key", "model", "style_baseline", "作者原文")
        sheet_worker = NovelWritingWorker("http://example.test", "key", "model", "style_sheet", "作者原文和基准稿")
        merge_worker = NovelWritingWorker("http://example.test", "key", "model", "style_sheet_merge", "两个档案")
        persona_worker = NovelWritingWorker("http://example.test", "key", "model", "style_persona", "最终档案")
        cards_worker = NovelWritingWorker("http://example.test", "key", "model", "style_cards", "作者完整原文")
        rules_worker = NovelWritingWorker("http://example.test", "key", "model", "style_rules", "本章资料")
        memory_finalize_worker = NovelWritingWorker(
            "http://example.test", "key", "model", "memory_finalize", "最终正文和长期资料"
        )

        profile_prompt = profile_worker._action_prompt()
        finalize_prompt = finalize_worker._action_prompt()
        audit_prompt = audit_worker._action_prompt()
        rewrite_prompt = rewrite_worker._action_prompt()
        plot_prompt = plot_worker._action_prompt()

        self.assertIn("不能自动美化成标准商业文风", profile_prompt)
        self.assertIn("修辞性重复", profile_prompt)
        self.assertIn("跨段或跨章反复解释", profile_prompt)
        self.assertIn("同一信息只有出现新证据", finalize_prompt)
        self.assertIn("同时校验剧情执行、连续性和样本文风", finalize_prompt)
        self.assertIn("用户上下文指定的输出分区", finalize_prompt)
        self.assertIn("独立小说文风审校员", audit_prompt)
        self.assertIn("最多列5项真正影响整体读感的阻断差异", audit_prompt)
        self.assertIn("评分达到80才允许通过", audit_prompt)
        self.assertIn("完整原样本提供本次仿写的写法来源", rewrite_prompt)
        self.assertIn("不带任何原文文风的剧情事实清单", plot_prompt)
        self.assertIn("普通中文小说写法", baseline_worker._action_prompt())
        self.assertIn("逐字证据", sheet_worker._action_prompt())
        self.assertIn("只合并真正等价", merge_worker._action_prompt())
        self.assertIn("第二人称", persona_worker._action_prompt())
        self.assertIn("逐字连续截取片段", cards_worker._action_prompt())
        self.assertEqual(cards_worker._max_tokens_for_request(), 7000)
        self.assertIn("当前章节资料", rules_worker._action_prompt())
        self.assertIn("连续性总编辑", memory_finalize_worker._action_prompt())
        self.assertIn("记录缺失或覆盖", memory_finalize_worker._action_prompt())
        self.assertIn("只能填写在fact_updates各项的key字段", memory_finalize_worker._action_prompt())
        self.assertIn("至少被一个long_term_events.storage.fact_refs引用", memory_finalize_worker._action_prompt())
        self.assertEqual(profile_worker._max_tokens_for_request(), 2800)
        self.assertEqual(finalize_worker._max_tokens_for_request(), 8500)
        self.assertEqual(memory_finalize_worker._max_tokens_for_request(), 9000)
        reconcile_worker = NovelWritingWorker(
            "http://example.test", "key", "model", "memory_reconcile", "十章边界资料"
        )
        self.assertEqual(reconcile_worker._max_tokens_for_request(), 4500)
        self.assertIn("最小纠错补丁", reconcile_worker._action_prompt())
        self.assertIn("未授权写成已授权", reconcile_worker._action_prompt())
        self.assertEqual(audit_worker._max_tokens_for_request(), 2200)
        self.assertEqual(plot_worker._max_tokens_for_request(), 1800)
        self.assertEqual(baseline_worker._max_tokens_for_request(), 12000)
        self.assertEqual(sheet_worker._max_tokens_for_request(), 6000)
        self.assertEqual(merge_worker._max_tokens_for_request(), 6000)
        self.assertEqual(persona_worker._max_tokens_for_request(), 3200)
        self.assertEqual(rules_worker._max_tokens_for_request(), 4200)

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

    def test_writing_worker_diagnostics_capture_failed_request_and_partial_output(self):
        context = "【当前章节】\n" + ("连续性资料。" * 80)
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", context)
        worker._session = _FakeStreamSession([
            'data: {"choices":[{"delta":{"content":"半截正文"}}]}',
        ])

        worker.run()

        diagnostics = worker.diagnostics
        self.assertEqual(diagnostics["outcome"], "error")
        self.assertEqual(diagnostics["error_type"], "Exception")
        self.assertEqual(diagnostics["response_chars"], len("半截正文"))
        self.assertEqual(worker.last_response_text, "半截正文")
        self.assertEqual(
            diagnostics["sent_context_sha256"],
            hashlib.sha256(context.encode("utf-8")).hexdigest(),
        )
        self.assertTrue(diagnostics["traceback"])
        self.assertGreater(diagnostics["sse_lines"], 0)

    def test_writing_worker_diagnostics_mark_empty_user_stop(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "outline", "context")
        worker._session = _FakeStreamSession([])
        worker._stop_requested = True
        results = []
        worker.result_ready.connect(lambda action, content: results.append((action, content)))

        worker.run()

        self.assertEqual(results, [("outline", "")])
        self.assertEqual(worker.diagnostics["outcome"], "stopped")
        self.assertIn("finished_at", worker.diagnostics)

    def test_writing_worker_stop_does_not_wait_for_response_headers(self):
        class BlockingSession:
            trust_env = False

            def __init__(self):
                self.started = threading.Event()
                self.release = threading.Event()
                self.completed = threading.Event()
                self.closed = False

            def post(self, *_args, **_kwargs):
                self.started.set()
                try:
                    self.release.wait(5)
                    raise RuntimeError("request released after cancellation")
                finally:
                    self.completed.set()

            def close(self):
                self.closed = True

        session = BlockingSession()
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", "context")
        worker._session = session
        results = []
        errors = []
        worker.result_ready.connect(lambda action, content: results.append((action, content)))
        worker.failed.connect(errors.append)
        runner = threading.Thread(target=worker.run, daemon=True)
        runner.start()
        self.assertTrue(session.started.wait(1))

        worker.stop()
        runner.join(1)

        try:
            self.assertFalse(runner.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(worker.diagnostics["cancelled_before_headers"])
            self.assertEqual(worker.diagnostics["outcome"], "stopped")
        finally:
            session.release.set()
            session.completed.wait(1)

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

    def test_writing_worker_does_not_leak_reasoning_content_into_result(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", "context")
        worker._session = _FakeStreamSession([
            'data: {"choices":[{"delta":{"reasoning_content":"内部规划，不应进入正文"}}]}',
            'data: {"choices":[{"delta":{"content":"正式正文。"},"finish_reason":"stop"}]}',
        ])
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, content: results.append((action, content)))

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(results, [("draft", "正式正文。")])
        self.assertEqual(worker.diagnostics["ignored_reasoning_chars"], 11)

    def test_writing_worker_sends_up_to_shared_novel_context_limit(self):
        context = "长篇上下文" * 30000
        worker = NovelWritingWorker("http://example.test", "key", "model", "outline", context)
        session = _FakeStreamSession([
            'data: {"choices":[{"delta":{"content":"1. 提纲"},"finish_reason":"stop"}]}',
        ])
        worker._session = session

        worker.run()

        sent = session.last_payload["messages"][1]["content"]
        self.assertEqual(len(sent), workers_module.NOVEL_AI_CONTEXT_LIMIT)
        self.assertEqual(sent, context[:workers_module.NOVEL_AI_CONTEXT_LIMIT])

    def test_memory_worker_requests_structured_json_response_format(self):
        worker = NovelWritingWorker(
            "http://example.test", "key", "model", "memory_finalize", "context"
        )
        session = _FakeStreamSession([
            'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}',
        ])
        worker._session = session
        results = []
        worker.result_ready.connect(lambda action, content: results.append((action, content)))

        worker.run()

        self.assertEqual(results, [("memory_finalize", "{}")])
        self.assertEqual(session.last_payload["response_format"], {"type": "json_object"})
        self.assertEqual(session.last_payload["reasoning_effort"], "low")
        self.assertTrue(worker.diagnostics["json_response_format_requested"])
        self.assertEqual(worker.diagnostics["reasoning_effort_requested"], "low")
        self.assertIn("不能漏掉字符串末尾", worker._action_prompt())

    def test_writing_worker_uses_task_tiered_reasoning_effort_by_provider(self):
        cases = (
            ("https://api.dxmcs.xin", "gpt-5.6-luna", "high"),
            ("https://api.dxmcs.xin", "gpt-5.6-sol", "high"),
            ("https://api.dxmcs.xin", "gpt-5.6-terra", "high"),
            ("https://api.dxmcs.xin", "gpt-5.5", "high"),
            ("https://hubway.cc", "gpt-5.5", "high"),
        )
        for base_url, model, expected in cases:
            with self.subTest(base_url=base_url, model=model):
                worker = NovelWritingWorker(base_url, "key", model, "outline", "context")
                session = _FakeStreamSession([
                    'data: {"choices":[{"delta":{"content":"1. 提纲"},"finish_reason":"stop"}]}',
                ])
                worker._session = session

                worker.run()

                self.assertEqual(session.last_payload["reasoning_effort"], expected)

    def test_writing_worker_keeps_maximum_reasoning_for_prose_and_style_imitation(self):
        cases = (
            ("draft", "max"),
            ("style_finalize", "max"),
            ("style_rewrite", "max"),
        )
        for action, expected in cases:
            with self.subTest(action=action):
                worker = NovelWritingWorker(
                    "https://api.dxmcs.xin", "key", "gpt-5.6-sol", action, "context"
                )
                session = _FakeStreamSession([
                    'data: {"choices":[{"delta":{"content":"正文完成。"},"finish_reason":"stop"}]}',
                ])
                worker._session = session

                worker.run()

                self.assertEqual(session.last_payload["reasoning_effort"], expected)

    def test_writing_worker_lowers_state_tasks_to_high(self):
        worker = NovelWritingWorker(
            "https://api.dxmcs.xin", "key", "gpt-5.6-sol", "memory_finalize", "context"
        )
        session = _FakeStreamSession([
            'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}',
        ])
        worker._session = session

        worker.run()

        self.assertEqual(session.last_payload["reasoning_effort"], "high")

    def test_memory_worker_aborts_abnormally_oversized_stream(self):
        worker = NovelWritingWorker(
            "http://example.test", "key", "model", "memory_finalize", "context"
        )
        piece = "状态" * 10000
        lines = [
            "data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}, ensure_ascii=False),
            "data: " + json.dumps({"choices": [{"delta": {"content": piece}}]}, ensure_ascii=False),
        ]
        worker._session = _FakeStreamSession(lines)
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, content: results.append((action, content)))

        worker.run()

        self.assertEqual(results, [])
        self.assertTrue(errors)
        self.assertIn("输出异常膨胀", errors[0])
        self.assertEqual(worker.diagnostics["response_char_limit"], 36000)
        self.assertTrue(worker.diagnostics["response_char_limit_exceeded"])
        self.assertEqual(worker.diagnostics["response_chars"], 40000)

    def test_memory_worker_ignores_trailing_whitespace_after_complete_json(self):
        worker = NovelWritingWorker(
            "http://example.test", "key", "model", "memory_finalize", "context"
        )
        content = json.dumps({"summary": "状态整理完成"}, ensure_ascii=False)
        lines = [
            "data: " + json.dumps({"choices": [{"delta": {"content": content}}]}, ensure_ascii=False),
            "data: " + json.dumps({"choices": [{"delta": {"content": " " * 40000}}]}, ensure_ascii=False),
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        ]
        worker._session = _FakeStreamSession(lines)
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, value: results.append((action, value)))

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(results, [("memory_finalize", content)])
        self.assertFalse(worker.diagnostics["response_char_limit_exceeded"])
        self.assertEqual(worker.diagnostics["ignored_trailing_whitespace_chars"], 40000)

    def test_memory_worker_only_falls_back_for_response_format_compatibility_errors(self):
        self.assertTrue(NovelWritingWorker._json_response_format_not_supported(
            400, "response_format json_object is unsupported"
        ))
        self.assertFalse(NovelWritingWorker._json_response_format_not_supported(
            500, "response_format json_object is unsupported"
        ))
        self.assertFalse(NovelWritingWorker._json_response_format_not_supported(
            400, "invalid api key"
        ))

    def test_memory_worker_retries_without_response_format_after_preheader_disconnect(self):
        endpoint = "http://transport-fallback.test"
        worker = NovelWritingWorker(
            endpoint, "key", "model", "memory_finalize", "context"
        )

        class DisconnectThenStreamSession(_FakeStreamSession):
            def __init__(self, lines):
                super().__init__(lines)
                self.payloads = []

            def post(self, *_args, **kwargs):
                self.payloads.append(dict(kwargs.get("json") or {}))
                if len(self.payloads) == 1:
                    raise workers_module.requests.exceptions.ConnectionError(
                        "Remote end closed connection without response"
                    )
                return self._response

        session = DisconnectThenStreamSession([
            'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}',
        ])
        worker._session = session
        results = []
        worker.result_ready.connect(lambda action, content: results.append((action, content)))

        try:
            worker.run()
            cached_worker = NovelWritingWorker(
                endpoint, "key", "model", "memory_finalize", "context"
            )
            cached_session = _FakeStreamSession([
                'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}',
            ])
            cached_worker._session = cached_session
            cached_worker.run()
        finally:
            with NovelWritingWorker._json_transport_fallback_lock:
                NovelWritingWorker._json_transport_fallback_endpoints.discard(
                    (endpoint, "model")
                )

        self.assertEqual(results, [("memory_finalize", "{}")])
        self.assertIn("response_format", session.payloads[0])
        self.assertNotIn("response_format", session.payloads[1])
        self.assertTrue(worker.diagnostics["json_response_format_transport_fallback"])
        self.assertNotIn("response_format", cached_session.last_payload)
        self.assertTrue(cached_worker.diagnostics["json_response_format_cached_fallback"])

    def test_writing_worker_reports_http_200_empty_body_as_provider_result(self):
        worker = NovelWritingWorker(
            "http://example.test", "key", "model", "draft", "context"
        )
        worker._session = _FakeStreamSession([
            'data: {"choices":[{"delta":{"content":"","role":"assistant"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ])
        errors = []
        worker.failed.connect(errors.append)

        worker.run()

        self.assertTrue(errors)
        self.assertIn("厂商返回 HTTP 200", errors[0])
        self.assertIn("正文为0字", errors[0])

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

    def test_draft_worker_accepts_em_dash_cliffhanger(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", "context")
        content = "黑暗中传来规律的声音。\n\n滴——\n\n滴——"
        worker._session = _FakeStreamSession([
            "data: " + json.dumps({
                "choices": [{
                    "delta": {"content": content},
                    "finish_reason": "stop",
                }]
            }, ensure_ascii=False),
            "data: [DONE]",
        ])
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, value: results.append((action, value)))

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(results, [("draft", content)])

    def test_structured_draft_worker_validates_extracted_backup_draft(self):
        context = "【剧情执行稿任务】\n严格输出三个分区。"
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", context)
        content = (
            "【剧情执行清单】\n1. 主角渡劫。\n\n"
            "【本章声纹执行表】\n结尾停在监护声。\n\n"
            "【备用正文草稿】\n黑暗中响起声音。\n\n滴——"
        )
        worker._session = _FakeStreamSession([
            "data: " + json.dumps({
                "choices": [{
                    "delta": {"content": content},
                    "finish_reason": "stop",
                }]
            }, ensure_ascii=False),
            "data: [DONE]",
        ])
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, value: results.append((action, value)))

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(results, [("draft", "黑暗中响起声音。\n\n滴——")])
        self.assertEqual(worker.diagnostics["prose_delivery_source"], "structured_backup_draft")
        self.assertTrue(worker.diagnostics["prose_metadata_stripped"])

    def test_style_draft_worker_delivers_only_wrapped_prose(self):
        context = "【小说正文直写】\n【正文风格参考】\n样本"
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", context)
        content = (
            "<NOVEL_PROSE_START>\n"
            "收银台的扫描声停了下来。\n\n她抬头看向门口。"
            "\n<NOVEL_PROSE_END>"
        )
        worker._session = _FakeStreamSession([
            "data: " + json.dumps({
                "choices": [{
                    "delta": {"content": content},
                    "finish_reason": "stop",
                }]
            }, ensure_ascii=False),
            "data: [DONE]",
        ])
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, value: results.append((action, value)))

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(
            results,
            [("draft", "收银台的扫描声停了下来。\n\n她抬头看向门口。")],
        )
        self.assertEqual(worker.diagnostics["prose_delivery_source"], "direct_prose_boundary")

    def test_style_draft_worker_drops_preamble_and_postamble_without_retry(self):
        context = "【小说正文直写】\n【正文风格参考】\n样本"
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", context)
        content = (
            "我会先处理这一章的冲突，然后开始正文。\n"
            "<NOVEL_PROSE_START>\n"
            "她把门推开，先听见屋里有人笑。\n"
            "<NOVEL_PROSE_END>\n"
            "以上是正文，请继续检查风格。"
        )
        worker._session = _FakeStreamSession([
            "data: " + json.dumps({
                "choices": [{
                    "delta": {"content": content},
                    "finish_reason": "stop",
                }]
            }, ensure_ascii=False),
            "data: [DONE]",
        ])
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, value: results.append((action, value)))

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(
            results,
            [("draft", "她把门推开，先听见屋里有人笑。")],
        )
        self.assertTrue(worker.diagnostics["prose_metadata_stripped"])

    def test_style_draft_worker_rejects_planning_preamble_as_body(self):
        context = "【小说正文直写】\n【正文风格参考】\n样本"
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", context)
        content = "我会从收银台后的新反应切入。收银台的扫描声停了下来。"
        worker._session = _FakeStreamSession([
            "data: " + json.dumps({
                "choices": [{
                    "delta": {"content": content},
                    "finish_reason": "stop",
                }]
            }, ensure_ascii=False),
            "data: [DONE]",
        ])
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, value: results.append((action, value)))

        worker.run()

        self.assertEqual(results, [])
        self.assertTrue(errors)
        self.assertIn("正文交付边界不完整", errors[0])

    def test_structured_draft_worker_rejects_incomplete_sections(self):
        context = "【剧情执行稿任务】\n严格输出三个分区。"
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", context)
        content = "【剧情执行清单】\n1. 主角渡劫。\n\n【备用正文草稿】\n正文完成。"
        worker._session = _FakeStreamSession([
            "data: " + json.dumps({
                "choices": [{
                    "delta": {"content": content},
                    "finish_reason": "stop",
                }]
            }, ensure_ascii=False),
            "data: [DONE]",
        ])
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, value: results.append((action, value)))

        worker.run()

        self.assertEqual(results, [])
        self.assertTrue(errors)
        self.assertIn("剧情执行稿结构不完整", errors[0])

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

    def test_chapter_title_prompt_avoids_overstyled_templates(self):
        worker = NovelChapterTitleWorker(
            "http://example.test",
            "key",
            "model",
            "书名",
            "都市",
            "轻喜剧",
            [{"title": "第 1 章", "text": "正文一。"}],
        )

        prompt = worker._title_prompt()

        self.assertIn("最有辨识度的事件、冲突、选择、转折或线索", prompt)
        self.assertIn("允许在标题中间使用一个中文逗号", prompt)
        self.assertIn("不要刻意押韵、对仗", prompt)
        self.assertIn("直白准确", prompt)
        self.assertIn("相邻章节不要使用同一语法模板", prompt)
        self.assertIn("previous_titles", prompt)

    def test_chapter_title_keeps_sentence_comma_inside_title(self):
        worker = NovelChapterTitleWorker(
            "http://example.test",
            "key",
            "model",
            "书名",
            "玄幻",
            "轻松",
            [{"title": "第 1 章", "text": "正文一。"}],
        )

        titles = worker._normalize_titles_response(
            {"titles": [{"index": 1, "title": "他要进山，先过这一关"}]},
            [1],
        )

        self.assertEqual(titles, ["他要进山，先过这一关"])

    def test_chapter_title_batch_omits_style_hints_and_includes_previous_titles(self):
        worker = NovelChapterTitleWorker(
            "http://example.test",
            "key",
            "model",
            "书名",
            "都市",
            "轻喜剧",
            [{"title": "第 1 章", "text": "正文一。"}, {"title": "第 2 章", "text": "正文二。"}],
        )
        worker._title_context_previous_titles = ["会议室里的选择", "沉默的副创始人"]

        batches = worker._title_batches(max_chars=5000, max_count=10)
        text = worker._user_text_for_batch(batches[0])

        self.assertNotIn("style_hint", text)
        self.assertNotIn("事件型", text)
        self.assertNotIn("冲突型", text)
        self.assertIn("previous_titles", text)
        self.assertIn("会议室里的选择", text)
        self.assertIn("不要套固定标题模板", text)
        self.assertIn("押韵、对仗", text)

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
        self.assertIn("主角或高频人物的 notes 更要克制", prompt)
        self.assertIn("只有确实改变长期人物档案的新状态才输出", prompt)
        self.assertIn("也不要转写到本章需继承事实", prompt)
        self.assertIn("人物提取不要只保留主角", prompt)
        self.assertIn("本章实际出场并直接推动剧情的人物", prompt)
        self.assertIn("造成主角资源、去向、身份判断或后续事实变化的人物", prompt)
        self.assertIn("characters.name 必须是具体姓名、可复用称谓或可稳定追踪的单个人物身份", prompt)
        self.assertIn("黑衣人", prompt)
        self.assertIn("苏家管事", prompt)
        self.assertIn("复数无名群体排除规则高于主要行动人物保留规则", prompt)
        self.assertIn("王六的两名同伙", prompt)
        self.assertIn("无名群体/复数路人", prompt)
        self.assertIn("即使他们推动了本章剧情，也只把他们造成的剧情影响放入 timeline、summary 或 foreshadows.description", prompt)
        self.assertIn("只围观/传话/完成一次普通动作且不影响后续的人物可以不提取", prompt)
        self.assertIn("普通章节行动、临时情绪、一次性互动", prompt)
        self.assertIn("已有主角/高频人物", prompt)
        self.assertIn("已有备注的同义复述", prompt)
        self.assertIn("章节事实只由正文后的摘要/事实流程负责", prompt)
        self.assertIn("稳定设定变化才写入 lore.description", prompt)
        self.assertIn("本章出现、追问、调查、发送、发现线索、谁去问谁等临时推进", prompt)
        self.assertIn("characters 要求：在满足具体人物或可复用单人称谓的前提下", prompt)
        self.assertIn("不要输出无名群体/复数路人", prompt)
        self.assertIn("删除人物候选时不能丢失剧情作用", prompt)
        self.assertIn("不要把完整章节流水账塞进 notes", prompt)
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
        self.assertIn("target_code/命中编号", prompt)
        self.assertIn("无需回收", prompt)
        self.assertIn("review_reason", prompt)
        self.assertIn("evidence", prompt)
        self.assertIn("人物身份字段必须逐项独立判断", prompt)
        self.assertIn("直接对白时，voice 必须提炼", prompt)
        self.assertIn("goal 必须写成当前正文可证实的行动目标", prompt)
        self.assertIn("secret 只有正文直接揭示", prompt)

    def test_candidate_postprocess_prompt_keeps_major_chapter_characters(self):
        worker = NovelCandidatePostprocessWorker("http://example.test", "key", "model", {"characters": [{"name": "王六"}]}, "dossier")

        prompt = worker._postprocess_prompt()

        self.assertIn("不要把本章主要行动人物、冲突人物、造成长期结果的人物当作普通流水账删掉", prompt)
        self.assertIn("和主角发生冲突/追杀/审问/交易/救援/试探的人", prompt)
        self.assertIn("影响主角资源/去向/身份判断/后续事实的人", prompt)
        self.assertIn("黑衣人", prompt)
        self.assertIn("复数无名群体排除规则高于主要行动人物保留规则", prompt)
        self.assertIn("王六的两名同伙", prompt)
        self.assertIn("无名群体/复数路人", prompt)
        self.assertIn("最终输出前逐条检查 characters.name", prompt)
        self.assertIn("删除人物候选时不能丢失剧情作用", prompt)
        self.assertIn("删除只围观、传话、无姓名、无独立行动、无后续影响的路人", prompt)
        self.assertIn("人物字段必须逐项复核后再合并", prompt)
        self.assertIn("有稳定直接对白的候选必须保留 voice", prompt)
        self.assertIn("有明确争夺对象、行动方向、职责或利益诉求的候选必须保留 goal", prompt)
        self.assertIn("不能因为 secret 不明确而清空同一人物已有的 goal 或 voice", prompt)

    def test_draft_prompt_distinguishes_relevant_and_open_foreshadows(self):
        worker = NovelWritingWorker("http://example.test", "key", "model", "draft", "context")

        prompt = worker._action_prompt()

        self.assertIn("参考【本章相关伏笔】里的已命中伏笔和动态伏笔调度参考", prompt)
        self.assertIn("开放伏笔队列不是硬任务", prompt)
        self.assertIn("不要为了回收而破坏本章提纲", prompt)

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
        self.assertIn("状态更新，不是新增重复资料", prompt)
        self.assertIn("不同 target_code/命中编号 的终态更新必须分别保留", prompt)
        self.assertIn("没有 target_code/命中编号 的新增伏笔仍按普通候选规则去重", prompt)
        self.assertIn("target_code", prompt)
        self.assertIn("分块候选", user_text)
        self.assertIn("赵明", user_text)

    def test_framework_import_prompt_and_normalization(self):
        worker = NovelFrameworkImportWorker(
            "http://example.test",
            "key",
            "model",
            "主角：赵明\n第一章：旧案重启",
            "已有项目档案",
        )

        prompt = worker._analysis_prompt()
        user_text = worker._framework_user_text()
        normalized = worker._normalize_framework_result({
            "meta": {"title": "旧案录", "genre": "悬疑", "target_words": "约50000字", "premise": "旧案牵动三代人"},
            "project_materials": {"bible": "主线复仇", "world_rules": "卷宗不可外传"},
            "characters": [{"name": "赵明", "role": "主角", "notes": "追查旧案"}],
            "lore": [{"name": "旧案卷宗", "type": "物品", "description": "缺页卷宗"}],
            "foreshadows": [{"name": "缺页真相", "status": "未埋", "description": "卷宗缺页待揭示"}],
            "chapter_plan": {
                "summary": "前三章建立旧案。",
                "stages": [
                    {
                        "name": "开篇旧案",
                        "start_chapter": 1,
                        "end_chapter": 3,
                        "events": ["赵明收到缺页卷宗。"],
                    }
                ],
                "chapters": [
                    {
                        "index": 1,
                        "title": "第一章 旧案重启",
                        "outline": "赵明收到缺页卷宗。",
                        "characters": "赵明",
                        "settings": ["旧案卷宗"],
                    }
                ],
            },
        })

        self.assertIn("只根据【导入框架原文】明确写出的内容分类", prompt)
        self.assertIn("不要把整段框架原文原样塞进", prompt)
        self.assertIn("核心设定、读者承诺、长期主题、主线矛盾", prompt)
        self.assertNotIn('"hard_boundaries"', prompt)
        self.assertIn("详细结局事件不得写入小说圣经", prompt)
        self.assertIn("timeline 和 summary 默认留空", prompt)
        self.assertIn('"stages"', prompt)
        self.assertIn("不要凭空生成完整章节规划", prompt)
        self.assertIn("绝对不能作为某一章", prompt)
        self.assertIn("导入框架原文", user_text)
        self.assertEqual(normalized["meta"]["title"], "旧案录")
        self.assertEqual(normalized["meta"]["target_words"], "5")
        self.assertEqual(normalized["project_materials"]["bible"], "主线复仇")
        self.assertEqual(normalized["characters"][0]["name"], "赵明")
        self.assertEqual(normalized["lore"][0]["name"], "旧案卷宗")
        self.assertEqual(normalized["foreshadows"][0]["name"], "缺页真相")
        self.assertEqual(normalized["chapter_plan"]["chapters"][0]["title"], "旧案重启")
        self.assertIn("赵明收到缺页卷宗", normalized["chapter_plan"]["chapters"][0]["outline"])
        self.assertEqual(normalized["chapter_plan"]["stages"][0]["name"], "开篇旧案")
        self.assertEqual(
            normalized["chapter_plan"]["stages"][0]["events"][0]["text"],
            "赵明收到缺页卷宗。",
        )

    def test_framework_import_drops_untitled_chapter_references(self):
        worker = NovelFrameworkImportWorker(
            "http://example.test",
            "key",
            "model",
            "开篇样章方向",
        )

        normalized = worker._normalize_framework_result({
            "chapter_plan": {
                "chapters": [
                    {"index": 1, "title": "", "outline": "开篇样章方向。"},
                    {"index": 2, "title": "第二章", "outline": "没有正式标题。"},
                ],
            },
        })

        self.assertEqual(normalized["chapter_plan"]["chapters"], [])

    def test_framework_import_formats_all_present_bible_sections(self):
        worker = NovelFrameworkImportWorker(
            "http://example.test",
            "key",
            "model",
            "核心设定、读者承诺和结局方向。",
        )

        normalized = worker._normalize_framework_result({
            "project_materials": {
                "bible_sections": {
                    "core_setting": "女主能把谎言变成实物线索。",
                    "reader_promise": "每次谎言都会带来反击机会。",
                    "theme": "真相需要付出代价。",
                    "main_conflict": "女主对抗利用情感牟利的系统。",
                    "relationship_foundation": "男女主从互相怀疑到并肩，但不保证圆满。",
                    "ending_direction": "胜利有代价，关系留下遗憾。",
                    "hard_boundaries": "不写渣男洗白，不写能力无代价。",
                },
                "world_rules": "能力不能预知未来。",
                "timeline": "框架阶段不应写入项目时间线。",
                "summary": "框架走向不应写入项目摘要。",
            },
        })

        bible = normalized["project_materials"]["bible"]
        for label in (
            "核心设定",
            "核心爽点 / 读者承诺",
            "长期主题",
            "主线矛盾",
            "长期关系底盘",
            "结局方向",
            "禁用设定 / 硬边界",
        ):
            self.assertIn(label, bible)
        self.assertIn("女主能把谎言变成实物线索", bible)
        self.assertIn("不写能力无代价", bible)
        self.assertEqual(normalized["project_materials"]["world_rules"], "能力不能预知未来。")

    def test_framework_import_drops_generic_placeholder_chapter_title(self):
        worker = NovelFrameworkImportWorker(
            "http://example.test",
            "key",
            "model",
            "开篇样章方向",
        )

        normalized = worker._normalize_framework_result({
            "chapter_plan": {
                "chapters": [
                    {"index": 1, "title": "章节 1", "outline": "这只是开篇样章。"},
                    {"index": 2, "title": "第二章：正式标题", "outline": "有明确标题。"},
                ],
            },
        })

        self.assertEqual(len(normalized["chapter_plan"]["chapters"]), 1)
        self.assertEqual(normalized["chapter_plan"]["chapters"][0]["title"], "正式标题")

    def test_framework_import_filters_range_and_volume_items_from_chapters(self):
        worker = NovelFrameworkImportWorker(
            "http://example.test",
            "key",
            "model",
            "第一章：开局\n4—10章：立威\n第二卷：扩张",
        )

        normalized = worker._normalize_framework_result({
            "chapter_plan": {
                "chapters": [
                    {"index": 1, "title": "第一章：开局", "outline": "主角醒来。"},
                    {"index": 2, "title": "4—10章：立威", "outline": "阶段剧情。"},
                    {"index": 3, "title": "第二卷：扩张", "outline": "分卷剧情。"},
                ],
            },
        })

        self.assertEqual(len(normalized["chapter_plan"]["chapters"]), 1)
        self.assertEqual(normalized["chapter_plan"]["chapters"][0]["title"], "开局")

    def test_framework_import_retries_premature_transport_with_stream(self):
        worker = NovelFrameworkImportWorker(
            "http://example.test",
            "key",
            "model",
            "主角：赵明",
        )
        worker.retry_attempts = 2
        stream_calls = []
        normal_calls = []

        def fake_stream(*_args, **_kwargs):
            stream_calls.append(1)
            if len(stream_calls) == 1:
                raise RuntimeError("Response ended prematurely")
            return {"meta": {"title": "旧案录"}, "characters": [], "lore": [], "foreshadows": []}

        def fake_normal(*_args, **_kwargs):
            normal_calls.append(1)
            raise AssertionError("框架长请求不应在流式传输中断后降级为普通请求")

        worker._post_analysis_chunk_stream = fake_stream
        worker._post_analysis_chunk = fake_normal

        parsed, _response_format = worker._analyze_chunk_with_retries(
            worker._analysis_prompt(),
            worker._framework_user_text(),
            1,
            1,
            True,
        )

        self.assertEqual(parsed["meta"]["title"], "旧案录")
        self.assertEqual(len(stream_calls), 2)
        self.assertEqual(normal_calls, [])

    def test_framework_import_retry_progress_does_not_describe_full_framework_as_chunk(self):
        worker = NovelFrameworkImportWorker(
            "http://example.test",
            "key",
            "model",
            "主角：赵明",
        )

        transport_text = worker._analysis_retry_progress_text(
            RuntimeError("Response ended prematurely"), 1, 1, 4, 3, 3
        )
        rate_limit_text = worker._analysis_retry_progress_text(
            RuntimeError("Concurrency limit exceeded"), 1, 1, 10, 2, 3
        )

        self.assertEqual(transport_text, "框架 AI 分类暂时失败，4 秒后自动重试 3/3...")
        self.assertEqual(rate_limit_text, "框架 AI 分类遇到接口并发限制，10 秒后自动重试 2/3...")
        self.assertNotIn("块", transport_text + rate_limit_text)
        self.assertIn(
            "第 2/5 块暂时失败",
            NovelAnalysisWorker(
                "http://example.test", "key", "model", "正文"
            )._analysis_retry_progress_text(
                RuntimeError("Response ended prematurely"), 2, 5, 4, 2, 3
            ),
        )

    def test_framework_import_normalizes_project_target_words_to_wan_unit(self):
        worker = NovelFrameworkImportWorker(
            "http://example.test",
            "key",
            "model",
            "目标字数：20万",
        )

        cases = {
            "约5万字": "5",
            "50000字": "5",
            "200000字": "20",
            "12.5万": "12.5",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                normalized = worker._normalize_framework_result({"meta": {"target_words": raw}})
                self.assertEqual(normalized["meta"]["target_words"], expected)

    def test_analysis_stream_json_error_falls_back_to_non_stream_request(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")
        calls = []

        def fake_stream(*_args, **_kwargs):
            calls.append("stream")
            raise ValueError("AI 返回内容不是合法 JSON。解析位置：第 1 行，第 20 列。")

        def fake_post(*_args, **_kwargs):
            calls.append("post")
            return {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}

        worker._post_analysis_chunk_stream = fake_stream
        worker._post_analysis_chunk = fake_post

        parsed, response_format = worker._analyze_chunk_resilient("prompt", "正文", 1, 1, True)

        self.assertEqual(calls, ["stream", "post"])
        self.assertEqual(parsed["foreshadows"], [])
        self.assertTrue(response_format)
        self.assertFalse(worker._analysis_request_capabilities()[1])

    def test_json_parser_repairs_deterministic_syntax_only(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")

        parsed = worker._parse_json_result(
            '```json\n{"summary":"阶段完成", "arcs":[{"name":"阶段一",}],}\n```'
        )

        self.assertEqual(parsed["summary"], "阶段完成")
        self.assertEqual(parsed["arcs"][0]["name"], "阶段一")
        self.assertEqual(worker.diagnostics["json_syntax_repair_count"], 1)
        self.assertEqual(worker.diagnostics["json_syntax_repair_types"], ["trailing_comma"])

    def test_json_parser_repairs_unescaped_quote_and_control_character(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")

        parsed = worker._parse_json_result(
            '{"summary":"他说"先等等"然后转身。\n她没有回答。","arcs":[]}'
        )

        self.assertEqual(parsed["summary"], "他说\"先等等\"然后转身。\n她没有回答。")
        self.assertEqual(
            worker.diagnostics["json_syntax_repair_types"],
            ["unescaped_quote", "control_character"],
        )

    def test_json_parser_can_close_only_completed_containers(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")

        parsed = worker._parse_json_result(
            '{"summary":"阶段完成","arcs":[{"name":"阶段一"}]'
        )

        self.assertEqual(parsed["arcs"][0]["name"], "阶段一")
        self.assertEqual(worker.diagnostics["json_syntax_repair_types"], ["missing_closer"])

    def test_json_parser_does_not_guess_an_incomplete_value(self):
        worker = NovelAnalysisWorker("http://example.test", "key", "model", "context")

        with self.assertRaisesRegex(ValueError, "不是合法 JSON"):
            worker._parse_json_result('{"summary":"阶段完成","arcs":[')

        self.assertEqual(worker.diagnostics["json_syntax_repair_count"], 0)
        self.assertIn("第 1 行", worker.diagnostics["last_json_parse_error"])

    def test_candidate_postprocess_stream_json_error_falls_back_to_non_stream_request(self):
        worker = NovelCandidatePostprocessWorker(
            "http://example.test",
            "key",
            "model",
            {"foreshadows": [{"name": "虎符失踪", "status": "已回收"}]},
            "【已有项目档案】",
        )
        calls = []

        def fake_stream(*_args, **_kwargs):
            calls.append("stream")
            raise ValueError("AI 返回内容不是合法 JSON。解析位置：第 1 行，第 20 列。")

        def fake_post(*_args, **_kwargs):
            calls.append("post")
            return {"characters": [], "lore": [], "foreshadows": [{"name": "虎符失踪", "status": "已回收"}], "project_materials": {}}

        worker._post_analysis_chunk_stream = fake_stream
        worker._post_analysis_chunk = fake_post

        parsed, response_format = worker._analyze_chunk_resilient("prompt", "候选", 1, 1, True)

        self.assertEqual(calls, ["stream", "post"])
        self.assertEqual(parsed["foreshadows"][0]["status"], "已回收")
        self.assertTrue(response_format)
        self.assertFalse(worker._analysis_request_capabilities()[1])

    def test_candidate_postprocess_accepts_empty_merged_result(self):
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

        self.assertEqual(errors, [])
        self.assertTrue(results)
        self.assertTrue(results[0].get("_postprocess_empty"))
        self.assertEqual(results[0]["characters"], [])

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
        self.assertIn("无需回收", prompt)

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
        self.last_payload = None

    def post(self, *_args, **_kwargs):
        self.last_payload = _kwargs.get("json")
        return self._response

    def close(self):
        self.closed = True


if __name__ == "__main__":
    unittest.main()
