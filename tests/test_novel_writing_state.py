import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit

from gpt_desktop.novel_import import Document as DocxDocument, WD_ALIGN_PARAGRAPH, _write_docx_text
from gpt_desktop.novel_utils import (
    CHAPTER_ANALYSIS_HASH_VERSION,
    _append_text_without_duplicate_overlap,
    _build_search_result_text,
    _chapter_analysis_hash,
    _chapter_analysis_legacy_hash,
    _chapter_list_text,
    _character_list_text,
    _compact_chapter_key_facts_text,
    _compact_chapter_summary_text,
    _infer_linked_character_names,
    _mark_chapters_analyzed,
    _new_chapter,
    _normalize_project,
    _project_meta_text,
    _split_manuscript_into_target_chapters,
)
from gpt_desktop.novel_writing_tab import NovelWritingTab
from gpt_desktop.workers import EdgeTTSWorker


class NovelWritingStateTests(unittest.TestCase):
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

    def test_merge_import_candidates_limits_foreshadow_description_supplements(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
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

    def test_auto_chapter_summary_applies_when_fields_unchanged(self):
        chapter = _new_chapter(0)
        chapter["text"] = "赵明进入王城。"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
            ],
            "chapters": [chapter],
        }
        tab.current_chapter_index = 0
        tab._auto_summary_chapter_id = chapter["id"]
        tab._auto_summary_started_summary = ""
        tab._auto_summary_started_key_facts = ""
        tab._auto_summary_started_linked = ""
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab.chapter_linked = _FakeLineEdit("")
        tab._dirty = False
        tab._loading = False
        tab._pending_manuscript_refresh = False
        tab._refresh_timer = _FakeTimer()
        tab.current_project_path = ""
        tab.project_meta_label = _FakeLabel()
        tab.set_status_tip = lambda _text: None
        tab._mark_chapter_dirty = lambda: None

        tab.on_auto_chapter_summary_ready(
            "summary",
            "本章摘要：赵明进入王城。\n本章需继承的关键事实：赵明拿到旧案钥匙。\n本章关联人物：赵明",
        )

        self.assertEqual(tab.chapter_summary.toPlainText(), "赵明进入王城。")
        self.assertEqual(tab.chapter_key_facts.toPlainText(), "赵明拿到旧案钥匙。")
        self.assertEqual(tab.chapter_linked.text(), "赵明")

    def test_auto_chapter_summary_ignores_generic_role_label_for_existing_character(self):
        chapter = _new_chapter(0)
        chapter["outline"] = "有人进入王城。"
        chapter["text"] = "他在王城找到旧案卷宗。"
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "", "notes": ""},
            ],
            "chapters": [chapter],
        }
        tab.current_chapter_index = 0
        tab._auto_summary_chapter_id = chapter["id"]
        tab._auto_summary_started_summary = ""
        tab._auto_summary_started_key_facts = ""
        tab._auto_summary_started_linked = ""
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab.chapter_linked = _FakeLineEdit("")
        tab._dirty = False
        tab._loading = False
        tab._pending_manuscript_refresh = False
        tab._refresh_timer = _FakeTimer()
        tab.current_project_path = ""
        tab.project_meta_label = _FakeLabel()
        tab.set_status_tip = lambda _text: None
        tab._mark_chapter_dirty = lambda: None

        tab.on_auto_chapter_summary_ready(
            "summary",
            "本章摘要：有人进入王城。\n本章需继承的关键事实：他拿到旧案钥匙。\n本章关联人物：主角",
        )

        self.assertEqual(tab.chapter_linked.text(), "")
        self.assertNotEqual(tab.chapter_linked.text(), "主角")

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

    def test_apply_text_preview_infers_linked_characters_before_auto_summary(self):
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
        tab._maybe_start_auto_chapter_summary = lambda: False
        tab.set_chapter_ai_panel_expanded = lambda _expanded: None
        tab.set_status_tip = lambda _text: None

        tab.apply_chapter_ai_preview("text")

        saved = tab.current_project["chapters"][0]
        self.assertEqual(tab.chapter_linked.text(), "赵明, 迟到主角")
        self.assertEqual(saved["linked_characters"], ["赵明", "迟到主角"])

    def test_apply_text_preview_does_not_start_reverse_auto_outline_or_summary(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("新增正文")
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
        started = []
        tab._maybe_start_auto_chapter_summary = lambda: started.append("summary") or True
        tab._maybe_start_auto_chapter_outline = lambda: started.append("outline") or True

        tab.apply_chapter_ai_preview("text")

        self.assertEqual(tab.chapter_text.toPlainText(), "新增正文")
        self.assertEqual(started, [])

    def test_chapter_ai_sequence_runs_draft_outline_then_summary(self):
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
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)
        tab._start_chapter_ai_worker = lambda action, _context, status_text="", resume_prefix="": (
            statuses.append(status_text) if status_text else None,
            started.append(action),
        )

        tab._start_chapter_ai_sequence()
        self.assertEqual(started, ["draft"])
        self.assertTrue(tab._chapter_ai_sequence_active)

        tab.chapter_ai_preview.setPlainText("AI 正文")
        tab.on_chapter_ai_ready("draft", "AI 正文")
        self.assertEqual(tab.chapter_text.toPlainText(), "AI 正文")
        self.assertEqual(started, ["draft", "outline"])

        tab.chapter_ai_preview.setPlainText("AI 提纲")
        tab.on_chapter_ai_ready("outline", "AI 提纲")
        self.assertEqual(tab.chapter_outline.toPlainText(), "AI 提纲")
        self.assertEqual(started, ["draft", "outline", "summary"])

        tab.chapter_ai_preview.setPlainText("本章摘要：AI 摘要。\n本章需继承的关键事实：AI 事实。")
        tab.on_chapter_ai_ready("summary", "本章摘要：AI 摘要。\n本章需继承的关键事实：AI 事实。")
        self.assertEqual(tab.chapter_summary.toPlainText(), "AI 摘要。")
        self.assertEqual(tab.chapter_key_facts.toPlainText(), "AI 事实。")
        self.assertFalse(tab._chapter_ai_sequence_active)

    def test_resumed_draft_sequence_finishes_with_summary(self):
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
        tab._start_chapter_ai_worker = lambda action, _context, status_text="", resume_prefix="": started.append(action)

        tab.run_chapter_ai_action("draft")
        self.assertEqual(started, ["draft"])
        self.assertTrue(tab._chapter_ai_sequence_active)

        tab.chapter_ai_preview.setPlainText("断线正文续完")
        tab.on_chapter_ai_ready("draft", "断线正文续完")

        self.assertEqual(tab.chapter_text.toPlainText(), "断线正文续完")
        self.assertEqual(started, ["draft", "outline"])

        tab.chapter_ai_preview.setPlainText("续写后的提纲")
        tab.on_chapter_ai_ready("outline", "续写后的提纲")
        self.assertEqual(tab.chapter_outline.toPlainText(), "续写后的提纲")
        self.assertEqual(started, ["draft", "outline", "summary"])

    def test_resumed_outline_sequence_does_not_restart_draft(self):
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

        self.assertEqual(started, ["outline"])
        self.assertTrue(tab._chapter_ai_sequence_active)
        self.assertEqual(button.text, "扩写正文并补提纲和摘要")

        tab.chapter_ai_preview.setPlainText("续写后的提纲")
        tab.on_chapter_ai_ready("outline", "续写后的提纲")

        self.assertEqual(tab.chapter_outline.toPlainText(), "续写后的提纲")
        self.assertEqual(started, ["outline", "summary"])

    def test_resumed_summary_sequence_does_not_restart_draft_or_outline(self):
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

        self.assertEqual(started, ["summary"])
        self.assertTrue(tab._chapter_ai_sequence_active)
        self.assertEqual(button.text, "扩写正文并补提纲和摘要")

        tab.chapter_ai_preview.setPlainText("本章摘要：续写后的摘要。\n本章需继承的关键事实：续写后的事实。")
        tab.on_chapter_ai_ready("summary", "本章摘要：续写后的摘要。\n本章需继承的关键事实：续写后的事实。")

        self.assertEqual(tab.chapter_summary.toPlainText(), "续写后的摘要。")
        self.assertEqual(tab.chapter_key_facts.toPlainText(), "续写后的事实。")
        self.assertEqual(started, ["summary"])
        self.assertFalse(tab._chapter_ai_sequence_active)

    def test_auto_chapter_outline_keeps_manual_outline(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab._auto_outline_chapter_id = chapter["id"]
        tab._auto_outline_started_outline = "旧提纲"
        tab.chapter_outline = _FakePlainTextEdit("我手动改过的提纲")
        tab.chapter_linked = _FakeLineEdit("")
        tab.set_status_tip = lambda _text: None

        tab.on_auto_chapter_outline_ready("outline", "AI 新提纲")

        self.assertEqual(tab.chapter_outline.toPlainText(), "我手动改过的提纲")

    def test_auto_chapter_outline_fills_unchanged_outline(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab._auto_outline_chapter_id = chapter["id"]
        tab._auto_outline_started_outline = ""
        tab.chapter_outline = _FakePlainTextEdit("")
        tab.chapter_linked = _FakeLineEdit("")
        tab._mark_chapter_dirty = lambda: None
        tab.set_status_tip = lambda _text: None

        tab.on_auto_chapter_outline_ready("outline", "AI 新提纲")

        self.assertEqual(tab.chapter_outline.toPlainText(), "AI 新提纲")

    def test_partial_draft_preview_context_continues_without_saving_preview(self):
        chapter = _new_chapter(0)
        chapter["draft_words"] = "5000"
        chapter["text"] = "甲" * 1000
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("乙" * 1000)
        tab._chapter_ai_preview_is_partial = True
        tab._chapter_ai_preview_action = "draft"
        tab._chapter_ai_preview_chapter_id = chapter["id"]
        tab._flush_current_editors = lambda: None

        context = tab._chapter_ai_context_with_preview("draft")

        self.assertIn("当前正文长度：约2002字", context)
        self.assertIn("本次新增正文参考目标：约2998字", context)
        self.assertEqual(tab.current_project["chapters"][0]["text"], "甲" * 1000)

    def test_failed_draft_preview_changes_button_to_continue(self):
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
        self.assertEqual(button.text, "续写正文")

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
        tab._chapter_ai_sequence_pending_action = "draft"
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
        self.assertEqual(button.text, "续写正文")
        self.assertIn("可点续写正文继续", statuses[-1])

    def test_failed_outline_without_preview_still_changes_button_to_continue(self):
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
        self.assertEqual(button.text, "续写提纲")

    def test_failed_sequence_outline_status_names_written_body_and_resume_step(self):
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
        tab._chapter_ai_sequence_active = True
        button = _FakeButton()
        tab._chapter_ai_buttons_by_action = {"draft": button}
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)

        import gpt_desktop.novel_writing_tab as writing_tab
        original_warning = writing_tab.QMessageBox.warning
        try:
            writing_tab.QMessageBox.warning = lambda *_args, **_kwargs: None
            tab.on_chapter_ai_failed("接口错误 500：server down")
        finally:
            writing_tab.QMessageBox.warning = original_warning

        self.assertIn("正文已写入", statuses[-1])
        self.assertIn("补提纲失败", statuses[-1])
        self.assertIn("可继续补提纲", statuses[-1])
        self.assertIn("接口错误 500", statuses[-1])

    def test_failed_sequence_summary_status_names_written_body_and_resume_step(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter], "characters": []}
        tab.current_chapter_index = 0
        tab.chapter_ai_preview = _FakePlainTextEdit("")
        tab.chapter_ai_stream_text = ""
        tab._chapter_ai_running_action = "summary"
        tab._chapter_ai_preview_is_partial = False
        tab._chapter_ai_preview_action = ""
        tab._chapter_ai_preview_chapter_id = ""
        tab._chapter_ai_sequence_active = True
        button = _FakeButton()
        tab._chapter_ai_buttons_by_action = {"draft": button}
        statuses = []
        tab.set_status_tip = lambda text: statuses.append(text)

        import gpt_desktop.novel_writing_tab as writing_tab
        original_warning = writing_tab.QMessageBox.warning
        try:
            writing_tab.QMessageBox.warning = lambda *_args, **_kwargs: None
            tab.on_chapter_ai_failed("接口错误 500：server down")
        finally:
            writing_tab.QMessageBox.warning = original_warning

        self.assertIn("正文已写入", statuses[-1])
        self.assertIn("补摘要/关键事实失败", statuses[-1])
        self.assertIn("可继续补摘要", statuses[-1])
        self.assertIn("接口错误 500", statuses[-1])

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

    def test_save_current_work_can_avoid_project_list_refresh_when_switching_projects(self):
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"meta": {"title": "当前项目"}, "chapters": []}
        tab.current_project_path = "/tmp/current.json"
        tab._dirty = True
        tab._flush_current_editors = lambda: None
        tab._sync_candidate_analysis_state = lambda: None
        tab._sync_import_candidates_to_project = lambda: None
        tab._remember_project_path = lambda _path: None
        tab._save_draft_snapshot = lambda: None
        tab._update_stats_label = lambda: None
        refreshed = []
        tab._notify_project_store_changed = lambda: refreshed.append(True)

        import gpt_desktop.novel_writing_tab as writing_tab
        original_save = writing_tab.save_project_file
        calls = []
        try:
            writing_tab.save_project_file = lambda path, data, preserve_mtime=False: calls.append((path, preserve_mtime))

            tab._save_current_work("打开前保存", refresh_project_list=False, preserve_project_mtime=True)
        finally:
            writing_tab.save_project_file = original_save

        self.assertEqual(calls, [("/tmp/current.json", True)])
        self.assertEqual(refreshed, [])
        self.assertFalse(tab._dirty)

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

    def test_auto_chapter_summary_keeps_manual_summary_but_fills_other_fields(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
            ],
            "chapters": [chapter],
        }
        tab.current_chapter_index = 0
        tab._auto_summary_chapter_id = chapter["id"]
        tab._auto_summary_started_summary = ""
        tab._auto_summary_started_key_facts = ""
        tab._auto_summary_started_linked = ""
        tab.chapter_summary = _FakePlainTextEdit("我手动写的摘要")
        tab.chapter_key_facts = _FakePlainTextEdit("")
        tab.chapter_linked = _FakeLineEdit("")
        tab._mark_chapter_dirty = lambda: None
        tab.set_status_tip = lambda _text: None

        tab.on_auto_chapter_summary_ready(
            "summary",
            "本章摘要：AI 摘要。\n本章需继承的关键事实：AI 事实。\n本章关联人物：赵明",
        )

        self.assertEqual(tab.chapter_summary.toPlainText(), "我手动写的摘要")
        self.assertEqual(tab.chapter_key_facts.toPlainText(), "AI 事实。")
        self.assertEqual(tab.chapter_linked.text(), "赵明")

    def test_auto_chapter_summary_keeps_manual_key_facts_but_fills_summary(self):
        chapter = _new_chapter(0)
        tab = NovelWritingTab.__new__(NovelWritingTab)
        tab.current_project = {"chapters": [chapter]}
        tab.current_chapter_index = 0
        tab._auto_summary_chapter_id = chapter["id"]
        tab._auto_summary_started_summary = ""
        tab._auto_summary_started_key_facts = ""
        tab._auto_summary_started_linked = ""
        tab.chapter_summary = _FakePlainTextEdit("")
        tab.chapter_key_facts = _FakePlainTextEdit("我手动写的关键事实")
        tab.chapter_linked = _FakeLineEdit("")
        tab._mark_chapter_dirty = lambda: None
        tab.set_status_tip = lambda _text: None

        tab.on_auto_chapter_summary_ready(
            "summary",
            "本章摘要：AI 摘要。\n本章需继承的关键事实：AI 事实。",
        )

        self.assertEqual(tab.chapter_summary.toPlainText(), "AI 摘要。")
        self.assertEqual(tab.chapter_key_facts.toPlainText(), "我手动写的关键事实")


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

    def setText(self, text):
        self.text = text

    def setToolTip(self, text):
        self.tooltip = text

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


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
    def __init__(self, path):
        self._path = path

    def data(self, _role):
        return self._path


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
