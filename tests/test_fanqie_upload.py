import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gpt_desktop.fanqie_upload import (
    FanqieBatchUploadWorker,
    build_fanqie_upload_task,
    normalize_fanqie_upload_state,
    validate_chapter_upload_range,
)
from gpt_desktop.novel_storage import load_json_file, save_project_file
from gpt_desktop.novel_utils import _normalize_project


class FanqieUploadTests(unittest.TestCase):
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

    def test_normalize_state_restricts_mode_to_draft(self):
        state = normalize_fanqie_upload_state({"mode": "publish", "status": "unknown"})
        self.assertEqual(state["mode"], "draft")
        self.assertEqual(state["status"], "idle")

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


if __name__ == "__main__":
    unittest.main()
