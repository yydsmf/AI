import os
import tempfile
import unittest

from gpt_desktop import novel_storage
from gpt_desktop.core import load_json_file, save_json_file


class NovelStorageTests(unittest.TestCase):
    def test_load_initial_project_merges_failed_chunks_from_last_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_draft = novel_storage.NOVEL_DRAFT_FILE
            old_last = novel_storage.NOVEL_LAST_FILE
            try:
                draft_path = os.path.join(tmp, "draft.json")
                last_path = os.path.join(tmp, "last.json")
                project_path = os.path.join(tmp, "project.json")
                novel_storage.NOVEL_DRAFT_FILE = draft_path
                novel_storage.NOVEL_LAST_FILE = last_path

                save_json_file(draft_path, {
                    "meta": {"title": "草稿"},
                    "chapters": [],
                    "analysis_state": {
                        "pending_candidate_chapter_ids": ["chapter-a"],
                    },
                })
                save_json_file(project_path, {
                    "meta": {"title": "项目"},
                    "chapters": [],
                    "analysis_state": {
                        "failed_candidate_chunks": [
                            {
                                "index": 1,
                                "total": 1,
                                "text": "失败块正文",
                                "error": "Response ended prematurely",
                            }
                        ],
                        "pending_candidate_chapter_ids": ["chapter-a"],
                        "candidate_postprocess": {
                            "status": "failed",
                            "error": "timeout",
                        },
                    },
                })
                save_json_file(last_path, {"path": project_path})

                data, path = novel_storage.load_initial_project_data()

                self.assertEqual(path, project_path)
                state = data.get("analysis_state", {})
                self.assertEqual(len(state.get("failed_candidate_chunks", [])), 1)
                self.assertEqual(state["failed_candidate_chunks"][0]["text"], "失败块正文")
                self.assertEqual(state.get("pending_candidate_chapter_ids"), ["chapter-a"])
                self.assertEqual(state.get("candidate_postprocess", {}).get("status"), "failed")
            finally:
                novel_storage.NOVEL_DRAFT_FILE = old_draft
                novel_storage.NOVEL_LAST_FILE = old_last

    def test_save_project_file_normalizes_repeated_long_form_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "project.json")
            repeated_note = "允许赵国图继续陈述，最终决定和亲从长计议。"
            repeated_summary = "皇商账册缺页牵出旧案。"

            novel_storage.save_project_file(path, {
                "meta": {"title": "测试项目"},
                "summary": f"{repeated_summary}\n补充：{repeated_summary}",
                "characters": [
                    {
                        "name": "皇上",
                        "role": "皇帝",
                        "notes": f"{repeated_note}\n补充：{repeated_note}",
                    }
                ],
            })

            saved = load_json_file(path, {})
            self.assertEqual(saved["summary"].count(repeated_summary), 1)
            self.assertEqual(saved["characters"][0]["notes"].count(repeated_note), 1)
            self.assertEqual(saved["meta"]["title"], "测试项目")

    def test_save_project_file_can_preserve_mtime_for_project_switch_autosave(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "project.json")
            save_json_file(path, {"meta": {"title": "旧项目"}, "chapters": []})
            old_mtime = 1000000000
            os.utime(path, (old_mtime, old_mtime))

            novel_storage.save_project_file(
                path,
                {"meta": {"title": "新项目"}, "chapters": [{"title": "第一章", "text": "正文"}]},
                preserve_mtime=True,
            )

            saved = load_json_file(path, {})
            self.assertEqual(saved["meta"]["title"], "新项目")
            self.assertEqual(os.path.getmtime(path), old_mtime)


if __name__ == "__main__":
    unittest.main()
