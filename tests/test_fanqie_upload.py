import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gpt_desktop.fanqie_upload import (
    _FanqieBrowserSession,
    _extract_id_from_url,
    _interpret_publish_response,
    FanqieBatchUploadWorker,
    FanqieDailyLimitError,
    FanqieLoginRequired,
    FanqieUploadError,
    FanqieBatchUploadDialog,
    build_fanqie_schedule_entries,
    build_fanqie_upload_task,
    normalize_fanqie_upload_state,
    validate_chapter_upload_range,
)
from gpt_desktop.novel_storage import load_json_file, save_project_file
from gpt_desktop.novel_utils import _normalize_project


class FanqieUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _project(self):
        return {
            "meta": {"title": "测试小说"},
            "chapters": [
                {"id": "chapter-1", "title": "第一章", "text": "正文" * 80},
                {"id": "chapter-2", "title": "第二章", "text": "正文" * 80},
                {"id": "chapter-3", "title": "第三章", "text": "正文" * 80},
            ],
        }

    def test_validation_reports_empty_title_and_body(self):
        project = self._project()
        project["chapters"][1]["title"] = ""
        project["chapters"][2]["text"] = ""
        result = validate_chapter_upload_range(project, 1, 3)
        self.assertEqual(result["count"], 3)
        self.assertIn("第2章缺少章节标题。", result["errors"])
        self.assertIn("第3章没有正文，不能上传。", result["errors"])

    def test_build_task_keeps_project_and_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "测试小说.json")
            project = self._project()
            save_project_file(path, project)
            task = build_fanqie_upload_task(
                path,
                {
                    "platform_work_id": "book-1",
                    "platform_work_title": "番茄作品",
                    "platform_work_url": "https://example.test/work/book-1",
                    "start_chapter": 2,
                    "end_chapter": 3,
                },
                project=project,
            )
            self.assertEqual(task["project_path"], os.path.realpath(path))
            self.assertEqual(task["start_chapter"], 2)
            self.assertEqual(task["end_chapter"], 3)
            self.assertEqual(task["mode"], "draft")

    def test_build_task_creates_stable_schedule_for_scheduled_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "测试小说.json")
            project = self._project()
            save_project_file(path, project)
            task = build_fanqie_upload_task(
                path,
                {
                    "platform_work_id": "book-1",
                    "platform_work_title": "番茄作品",
                    "start_chapter": 2,
                    "end_chapter": 3,
                    "mode": "scheduled_publish",
                    "work_type": "serial",
                    "schedule_start_date": "2026-10-21",
                    "schedule_start_time": "10:00",
                    "schedule_interval_minutes": 30,
                    "schedule_chapters_per_day": 2,
                },
                project=project,
            )
            self.assertEqual(task["mode"], "scheduled_publish")
            self.assertEqual(task["work_type"], "serial")
            self.assertTrue(task["publish_use_ai"])
            self.assertNotIn("schedule_interval_minutes", task)
            self.assertNotIn("schedule_chapters_per_day", task)
            self.assertEqual(task["schedule_entries"][0]["chapter_number"], 2)
            self.assertEqual(task["schedule_entries"][0]["publish_time"], "10:00")
            self.assertEqual(task["schedule_entries"][1]["publish_date"], "2026-10-21")
            self.assertEqual(task["schedule_entries"][1]["publish_time"], "10:00")

    def test_build_task_can_disable_ai_for_publishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "测试小说.json")
            project = self._project()
            save_project_file(path, project)
            task = build_fanqie_upload_task(
                path,
                {
                    "platform_work_id": "book-1",
                    "start_chapter": 1,
                    "end_chapter": 1,
                    "mode": "direct_publish",
                    "publish_use_ai": False,
                },
                project=project,
            )
            self.assertEqual(task["mode"], "direct_publish")
            self.assertFalse(task["publish_use_ai"])

    def test_dialog_locks_current_project_and_serializes_radio_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "测试小说.json")
            project = self._project()
            save_project_file(path, project)
            dialog = FanqieBatchUploadDialog(current_project_path=path)
            try:
                self.assertEqual(dialog._selected_project_path(), os.path.realpath(path))
                self.assertTrue(dialog.project_name_edit.isReadOnly())
                self.assertEqual(dialog._radio_value(dialog.mode_buttons, "draft"), "draft")
                self.assertEqual(dialog._radio_value(dialog.work_type_buttons, "unknown"), "unknown")
                self.assertFalse(dialog.publish_ai_buttons["yes"].isEnabled())
                dialog.mode_buttons["direct_publish"].setChecked(True)
                dialog._on_mode_changed()
                dialog.publish_ai_buttons["no"].setChecked(True)
                self.assertTrue(dialog.publish_ai_buttons["no"].isEnabled())
                self.assertEqual(dialog._radio_value(dialog.publish_ai_buttons, "yes"), "no")
            finally:
                dialog.close()

    def test_dialog_restores_last_upload_parameters_for_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "测试小说.json")
            project = self._project()
            project["fanqie_upload"] = {
                "platform_work_id": "book-2",
                "platform_work_title": "目标作品",
                "platform_work_url": "https://example.test/book-2",
                "mode": "scheduled_publish",
                "work_type": "completed",
                "publish_use_ai": False,
                "schedule_start_date": "2026-11-03",
                "schedule_start_time": "21:15",
                "start_chapter": 2,
                "end_chapter": 3,
                "headless": False,
                "resume": False,
                "status": "failed",
                "updated_at": "2026-10-20 12:00:00",
            }
            save_project_file(path, project)
            dialog = FanqieBatchUploadDialog(current_project_path=path)
            try:
                self.assertEqual(dialog._radio_value(dialog.mode_buttons, "draft"), "scheduled_publish")
                self.assertEqual(dialog._radio_value(dialog.work_type_buttons, "unknown"), "completed")
                self.assertEqual(dialog._radio_value(dialog.publish_ai_buttons, "yes"), "no")
                self.assertEqual(dialog.schedule_date_edit.date().toString("yyyy-MM-dd"), "2026-11-03")
                self.assertEqual(dialog.schedule_time_edit.time().toString("HH:mm"), "21:15")
                self.assertEqual(dialog.start_spin.value(), 2)
                self.assertEqual(dialog.end_spin.value(), 3)
                self.assertFalse(dialog.headless_check.isChecked())
                self.assertFalse(dialog.resume_check.isChecked())
                dialog._on_works_ready([{
                    "id": "book-2",
                    "title": "目标作品",
                    "url": "https://example.test/book-2",
                    "work_type": "serial",
                }])
                self.assertEqual(
                    dialog._radio_value(dialog.work_type_buttons, "unknown"),
                    "completed",
                )
            finally:
                dialog.close()

    def test_dialog_fields_match_width_after_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "测试小说.json")
            save_project_file(path, self._project())
            dialog = FanqieBatchUploadDialog(current_project_path=path)
            try:
                dialog.show()
                self._app.processEvents()
                self.assertEqual(dialog.project_name_edit.width(), dialog.work_combo.width())
            finally:
                dialog.close()

    def test_normalize_project_preserves_upload_checkpoint(self):
        project = _normalize_project({
            "meta": {"title": "测试小说"},
            "fanqie_upload": {
                "platform_work_id": "book-1",
                "status": "running",
                "completed_chapter_ids": ["chapter-1", "chapter-1"],
            },
        })
        self.assertEqual(project["fanqie_upload"]["platform_work_id"], "book-1")
        self.assertEqual(project["fanqie_upload"]["completed_chapter_ids"], ["chapter-1"])
        self.assertEqual(project["fanqie_upload"]["status"], "running")

    def test_normalize_state_keeps_publish_modes(self):
        state = normalize_fanqie_upload_state({"mode": "publish", "status": "unknown"})
        self.assertEqual(state["mode"], "direct_publish")
        self.assertEqual(state["status"], "idle")

    def test_editor_actions_prefer_top_right_controls(self):
        class FakeButton:
            def __init__(self):
                self.clicks = 0

            def is_visible(self):
                return True

            def click(self, **_kwargs):
                self.clicks += 1

        class FakeLocator:
            def __init__(self, items):
                self.items = items

            def count(self):
                return len(self.items)

            def nth(self, index):
                return self.items[index]

        class FakePage:
            def __init__(self):
                self.save = FakeButton()
                self.next = FakeButton()

            def locator(self, selector):
                if selector == "button.auto-editor-save-btn":
                    return FakeLocator([self.save])
                if selector == "button.auto-editor-next":
                    return FakeLocator([self.next])
                return FakeLocator([])

            def get_by_text(self, _name, exact=False):
                return FakeLocator([])

        browser = object.__new__(_FanqieBrowserSession)
        browser.page = FakePage()
        self.assertTrue(browser._click_save_draft_button())
        self.assertTrue(browser._click_next_editor_button())
        self.assertEqual(browser.page.save.clicks, 1)
        self.assertEqual(browser.page.next.clicks, 1)

    def test_draft_save_does_not_fall_back_to_next_step(self):
        browser = object.__new__(_FanqieBrowserSession)
        browser.page = object()
        browser._wait_for_metadata_stable = lambda *_args, **_kwargs: True
        browser._wait_for_editor_action = lambda *_args, **_kwargs: True
        browser._click_save_draft_button = lambda: False
        browser._click_text = lambda *_args, **_kwargs: self.fail(
            "草稿保存失败时不应尝试点击下一步"
        )
        with self.assertRaisesRegex(FanqieUploadError, "存草稿"):
            browser._save_draft_with_metadata_retry(
                "第九章",
                "9",
                (),
                (),
                text="正文",
                max_attempts=1,
            )

    def test_publish_flow_submits_typo_warning_and_uses_basic_detection(self):
        class FakePage:
            def wait_for_timeout(self, _milliseconds):
                return None

        browser = object.__new__(_FanqieBrowserSession)
        browser.page = FakePage()
        feedback = iter([
            "发布提示\n检测到你还有错别字未修改，是否确定提交？\n取消\n提交",
            "请选择内容检测方式\n仅基础检测\n全面检测",
            "",
        ])
        clicks = []
        settings_checks = iter([False, False, True])
        browser._click_next_editor_button = lambda: True
        browser._read_transient_publish_feedback = lambda: next(feedback, "")
        browser._publish_settings_visible = lambda: next(settings_checks, True)
        browser._click_text = lambda names, exact=False: clicks.append(tuple(names)) or True
        browser._configure_publish_settings = lambda *args, **kwargs: None
        browser._wait_for_publish_result = lambda *args, **kwargs: True
        browser._page_text = lambda: ""
        browser._publish_chapter(
            "第七十章",
            "正文",
            "direct_publish",
            None,
            True,
            lambda _text: None,
        )
        self.assertEqual(clicks, [("提交",), ("仅基础检测",)])

    def test_publish_settings_use_selected_ai_option(self):
        browser = object.__new__(_FanqieBrowserSession)
        selected = []
        browser._set_publish_ai_option = lambda use_ai=False: selected.append(use_ai) or True
        browser._set_schedule_toggle = lambda _enabled: True
        browser._click_text = lambda *_args, **_kwargs: True
        browser._configure_publish_settings("direct_publish", None, use_ai=False)
        self.assertEqual(selected, [False])

    def test_schedule_entries_use_tomato_date_and_time_for_each_chapter(self):
        entries = build_fanqie_schedule_entries(
            "2026-10-21",
            "10:30",
            45,
            2,
            [
                {"chapter_id": "chapter-1", "chapter_number": 1},
                {"chapter_id": "chapter-2", "chapter_number": 2},
                {"chapter_id": "chapter-3", "chapter_number": 3},
            ],
        )
        self.assertEqual(entries[0]["publish_date"], "2026-10-21")
        self.assertEqual(entries[0]["publish_time"], "10:30")
        self.assertEqual(entries[1]["publish_time"], "10:30")
        self.assertEqual(entries[1]["publish_date"], "2026-10-21")
        self.assertEqual(entries[2]["publish_date"], "2026-10-21")
        self.assertEqual(entries[2]["publish_time"], "10:30")

    def test_publish_response_business_code_overrides_http_success(self):
        self.assertEqual(
            _interpret_publish_response('{"code": 0, "message": "success"}'),
            (True, "success", False),
        )
        success, message, daily = _interpret_publish_response(
            '{"code": -1001, "message": "超出每日更新字数上限"}'
        )
        self.assertFalse(success)
        self.assertIn("每日", message)
        self.assertTrue(daily)

    def test_worker_stops_and_records_daily_limit_without_completing_chapter(self):
        class FakeBrowser:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def upload_chapter(self, *_args, **_kwargs):
                raise FanqieDailyLimitError("超出每日更新字数上限")

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "测试小说.json")
            save_project_file(path, self._project())
            worker = FanqieBatchUploadWorker({
                "project_path": path,
                "platform_work_id": "book-1",
                "platform_work_title": "番茄作品",
                "start_chapter": 1,
                "end_chapter": 2,
                "headless": True,
                "resume": False,
                "mode": "direct_publish",
                "work_type": "serial",
            })
            with patch("gpt_desktop.fanqie_upload._FanqieBrowserSession", return_value=FakeBrowser()):
                worker.run()
            state = load_json_file(path, {}).get("fanqie_upload", {})
            self.assertEqual(state.get("status"), "failed")
            self.assertEqual(state.get("error_kind"), "daily_limit")
            self.assertEqual(state.get("daily_limit_scope"), "serial")
            self.assertEqual(state.get("completed_chapter_ids"), [])

    def test_worker_resets_checkpoint_when_target_work_changes(self):
        worker = FanqieBatchUploadWorker({
            "project_path": "/tmp/test.json",
            "platform_work_id": "book-2",
            "platform_work_url": "https://example.test/work/book-2",
            "platform_work_title": "新作品",
            "start_chapter": 1,
            "end_chapter": 3,
        })
        state = worker._initial_state({
            "fanqie_upload": {
                "platform_work_id": "book-1",
                "platform_work_url": "https://example.test/work/book-1",
                "completed_chapter_ids": ["chapter-1"],
                "last_successful_chapter_id": "chapter-1",
                "last_successful_chapter_number": 1,
            }
        })
        self.assertEqual(state["completed_chapter_ids"], [])
        self.assertEqual(state["last_successful_chapter_number"], 0)
        self.assertEqual(state["platform_work_id"], "book-2")

    def test_extract_id_does_not_treat_writer_navigation_route_as_work(self):
        self.assertEqual(
            _extract_id_from_url("https://fanqienovel.com/writer/zone/"),
            "",
        )
        self.assertEqual(
            _extract_id_from_url("https://fanqienovel.com/writer/copyright/"),
            "",
        )
        self.assertEqual(
            _extract_id_from_url(
                "https://fanqienovel.com/main/writer/123456789012345/publish/"
            ),
            "123456789012345",
        )
        self.assertEqual(
            _extract_id_from_url(
                "https://fanqienovel.com/writer/zone/?id=not-a-book"
            ),
            "",
        )
        self.assertEqual(
            _extract_id_from_url(
                "https://fanqienovel.com/main/writer/chapter-manage/1234567890&章节标题?type=1"
            ),
            "1234567890",
        )

    def test_extract_works_ignores_writer_navigation_items(self):
        class FakePage:
            url = "https://fanqienovel.com/main/writer"

            def evaluate(self, _script):
                return [
                    {
                        "text": "作家专区",
                        "href": "https://fanqienovel.com/writer/zone/",
                        "id": "zone",
                        "book_id": "",
                        "title": "作家专区",
                    },
                    {
                        "text": "全家都想蹭我的豪门",
                        "href": "https://fanqienovel.com/main/writer/123456789012345/publish/",
                        "id": "",
                        "book_id": "",
                        "title": "",
                    },
                    {
                        "text": "带有作品数据属性的作品",
                        "href": "",
                        "id": "",
                        "book_id": "book-123456",
                        "title": "",
                    },
                    {
                        "text": "普通数据属性的真实作品",
                        "href": "",
                        "id": "987654321",
                        "book_id": "",
                        "title": "",
                    },
                    {
                        "text": "营业执照",
                        "href": "https://fanqienovel.com/writer/license/?id=987654322",
                        "id": "987654322",
                        "book_id": "",
                        "title": "营业执照",
                    },
                ]

        browser = object.__new__(_FanqieBrowserSession)
        browser.page = FakePage()
        works = browser._extract_works()
        self.assertEqual(
            [(item["id"], item["title"]) for item in works],
            [
                ("123456789012345", "全家都想蹭我的豪门"),
                ("book-123456", "带有作品数据属性的作品"),
                ("987654321", "普通数据属性的真实作品"),
            ],
        )

    def test_extract_works_from_author_book_list_payload(self):
        browser = object.__new__(_FanqieBrowserSession)
        works = browser._extract_works_from_payloads([
            {
                "code": 0,
                "data": {
                    "total_count": 2,
                    "book_list": [
                        {"book_id": "book-001", "book_name": "第一本小说"},
                        {"book_id": "book-002", "book_name": "第二本小说"},
                    ],
                },
            },
            {
                "code": 0,
                "data": {
                    "book_list": [
                        {"book_id": "book-001", "book_name": "第一本小说"},
                    ],
                },
            },
        ])
        self.assertEqual(
            [(item["id"], item["title"]) for item in works],
            [("book-001", "第一本小说"), ("book-002", "第二本小说")],
        )
        self.assertTrue(works[0]["url"].endswith("/main/writer/book-001/publish/"))

    def test_list_works_hidden_mode_requests_login_without_waiting_or_showing_ui(self):
        class FakeLocator:
            def inner_text(self, timeout=None):
                return "请先登录"

        class FakePage:
            url = "https://fanqienovel.com/writer/zone/"

            def goto(self, url, wait_until=None, timeout=None):
                self.url = url

            def wait_for_timeout(self, _milliseconds):
                return None

            def locator(self, _selector):
                return FakeLocator()

            def get_by_text(self, _name, exact=False):
                class EmptyLocator:
                    def count(self):
                        return 0

                return EmptyLocator()

        browser = object.__new__(_FanqieBrowserSession)
        browser.headless = True
        browser.page = FakePage()
        with self.assertRaises(FanqieLoginRequired):
            browser.list_works(
                should_stop=lambda: False,
                interactive_login=False,
                login_wait_seconds=15,
            )

    def test_upload_chapter_fills_and_verifies_absolute_chapter_number(self):
        class FakeField:
            def __init__(self, class_name="", placeholder="", on_fill=None):
                self.value = ""
                self.class_name = class_name
                self.placeholder = placeholder
                self.on_fill = on_fill

            def is_visible(self):
                return True

            def click(self, timeout=None):
                return None

            def press(self, key, timeout=None):
                return None

            def fill(self, value, timeout=None):
                self.value = str(value)
                if self.on_fill:
                    self.on_fill()

            def input_value(self, timeout=None):
                return self.value

            def get_attribute(self, name):
                return {
                    "class": self.class_name,
                    "placeholder": self.placeholder,
                }.get(name, "")

        class FakeLocator:
            def __init__(self, items):
                self.items = items

            def count(self):
                return len(self.items)

            def nth(self, index):
                return self.items[index]

        class FakePage:
            def __init__(self):
                self.serial = FakeField("serial-input byte-input", "")
                self.title = FakeField("", "请输入标题")
                self.editor = FakeField(
                    on_fill=lambda: setattr(self.serial, "value", "")
                    or setattr(self.title, "value", "")
                )
                self.keyboard = type(
                    "FakeKeyboard",
                    (),
                    {"type": lambda _self, value, delay=0: (
                        setattr(self.editor, "value", str(value)) or self.editor.on_fill()
                    )},
                )()

            def locator(self, selector):
                if "serial-input" in selector:
                    return FakeLocator([self.serial])
                if "请输入标题" in selector:
                    return FakeLocator([self.title])
                if "serial-editor .ProseMirror" in selector:
                    return FakeLocator([self.editor])
                return FakeLocator([])

        browser = object.__new__(_FanqieBrowserSession)
        browser.page = FakePage()
        browser._goto = lambda _url: None
        browser._click_text = lambda _names, exact=False: True
        browser._page_text = lambda: "正文字数\n160\n保存成功"
        browser.upload_chapter(
            {"id": "book-1", "url": "https://example.test/book-1"},
            {"title": "礼物不必学规矩", "text": "正文" * 80},
            chapter_number=9,
        )
        self.assertEqual(browser.page.serial.value, "9")
        self.assertEqual(browser.page.title.value, "礼物不必学规矩")
        self.assertEqual(browser.page.editor.value, "正文" * 80)

    def test_upload_chapter_stops_when_chapter_number_control_is_missing(self):
        class FakeField:
            def __init__(self, placeholder=""):
                self.value = ""
                self.placeholder = placeholder

            def is_visible(self):
                return True

            def click(self, timeout=None):
                return None

            def press(self, key, timeout=None):
                return None

            def fill(self, value, timeout=None):
                self.value = str(value)

            def input_value(self, timeout=None):
                return self.value

            def get_attribute(self, name):
                return self.placeholder if name == "placeholder" else ""

        class FakeLocator:
            def __init__(self, items):
                self.items = items

            def count(self):
                return len(self.items)

            def nth(self, index):
                return self.items[index]

        class FakePage:
            def __init__(self):
                self.title = FakeField("请输入标题")
                self.editor = FakeField()
                self.keyboard = type(
                    "FakeKeyboard",
                    (),
                    {"type": lambda _self, value, delay=0: setattr(self.editor, "value", str(value))},
                )()

            def locator(self, selector):
                if "请输入标题" in selector:
                    return FakeLocator([self.title])
                if "ProseMirror" in selector:
                    return FakeLocator([self.editor])
                return FakeLocator([])

        browser = object.__new__(_FanqieBrowserSession)
        browser.page = FakePage()
        browser._goto = lambda _url: None
        browser._click_text = lambda _names, exact=False: True
        browser._page_text = lambda: "正文字数\n160"
        with self.assertRaisesRegex(FanqieUploadError, "没有找到章节号输入框"):
            browser.upload_chapter(
                {"id": "book-1", "url": "https://example.test/book-1"},
                {"title": "第九章", "text": "正文" * 80},
                chapter_number=9,
            )

    def test_editor_ready_uses_internal_editor_text_when_visible_count_lags(self):
        class FakePage:
            def evaluate(self, _script):
                return "正文" * 80

            def wait_for_timeout(self, _timeout):
                return None

            def locator(self, _selector):
                class Body:
                    def inner_text(self, timeout=None):
                        return "正文字数\n0"

                return Body()

        browser = object.__new__(_FanqieBrowserSession)
        browser.page = FakePage()
        self.assertTrue(browser._wait_for_editor_ready("正文" * 80, timeout_ms=100))

    def test_read_transient_publish_feedback_reads_modal_text(self):
        class FakePage:
            def __init__(self):
                self.script = ""

            def evaluate(self, script):
                self.script = script
                return ["请选择内容检测方式\n仅基础检测\n全面检测"]

        browser = object.__new__(_FanqieBrowserSession)
        browser.page = FakePage()
        feedback = browser._read_transient_publish_feedback()
        self.assertIn("请选择内容检测方式", feedback)
        self.assertIn("仅基础检测", feedback)
        self.assertIn("const selectors = [", browser.page.script)
        self.assertIn(".join(',')", browser.page.script)

    def test_publish_feedback_classifies_prior_scheduled_chapter_warning(self):
        browser = object.__new__(_FanqieBrowserSession)
        kind, message = browser._classify_publish_feedback(
            "作品有定时待发布章节「第71章 花店撑不过下个月」，"
            "建议本章定时发布，否则在前面定时章节发布前本章不进审。"
        )
        self.assertEqual(kind, "confirm_required")
        self.assertIn("再次确认", message)

    def test_publish_result_reconfirms_when_prior_schedule_warning_is_shown(self):
        class FakePage:
            url = "https://example.test/main/writer/book/publish/draft"

            def wait_for_timeout(self, _milliseconds):
                return None

        browser = object.__new__(_FanqieBrowserSession)
        browser.page = FakePage()
        feedbacks = [
            "发布设置\n作品有定时待发布章节「第71章」，建议本章定时发布，否则在前面定时章节发布前本章不进审。",
            "发布成功",
        ]
        clicks = []
        browser._read_transient_publish_feedback = lambda: feedbacks.pop(0) if feedbacks else ""
        browser._publish_settings_visible = lambda: True
        browser._click_text = lambda names, exact=False: clicks.append((names, exact)) or True
        browser._page_text = lambda: "发布成功"
        self.assertTrue(browser._wait_for_publish_result({}, "direct_publish", timeout_ms=1000))
        self.assertEqual(len(clicks), 1)

    def test_wait_for_save_completion_waits_for_cloud_state(self):
        class FakePage:
            def __init__(self):
                self.index = 0

            def wait_for_timeout(self, _milliseconds):
                self.index += 1

        states = ["保存中", "保存中", "已保存到云端"]
        browser = object.__new__(_FanqieBrowserSession)
        browser.page = FakePage()
        browser._page_text = lambda: states[min(browser.page.index, len(states) - 1)]
        self.assertTrue(browser._wait_for_save_completion(timeout_ms=2000, settle_ms=200))
        self.assertGreaterEqual(browser.page.index, 2)

    def test_worker_passes_absolute_chapter_numbers_to_browser(self):
        class FakeBrowser:
            calls = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def upload_chapter(self, work, chapter, chapter_number=None, progress=None, **_kwargs):
                self.calls.append(chapter_number)
                return True

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "测试小说.json")
            save_project_file(path, self._project())
            browser = FakeBrowser()
            worker = FanqieBatchUploadWorker({
                "project_path": path,
                "platform_work_id": "book-1",
                "platform_work_title": "番茄作品",
                "platform_work_url": "https://example.test/book-1",
                "start_chapter": 2,
                "end_chapter": 3,
                "headless": True,
                "resume": False,
                "mode": "direct_publish",
            })
            with patch("gpt_desktop.fanqie_upload._FanqieBrowserSession", return_value=browser):
                worker.run()
            self.assertEqual(browser.calls, [2, 3])


if __name__ == "__main__":
    unittest.main()
