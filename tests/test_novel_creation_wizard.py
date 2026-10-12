import os
import tempfile
import unittest
from unittest.mock import patch

import gpt_desktop.novel_creation_wizard as wizard


class NovelCreationWizardPersistenceTests(unittest.TestCase):
    def test_completed_wizard_record_keeps_inspiration_and_all_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            draft_dir = os.path.join(tmp, "drafts")
            os.makedirs(draft_dir, exist_ok=True)
            draft_index = os.path.join(draft_dir, "index.json")
            legacy_file = os.path.join(tmp, "legacy.json")
            draft_id = "123-test"
            payload = {
                "schema_version": 3,
                "draft_id": draft_id,
                "created_at": "2026-10-12 10:00:00",
                "created_at_ns": 123,
                "updated_at": "2026-10-12 10:10:00",
                "project_name_hint": "测试小说",
                "current_step_index": 2,
                "inspiration": "主角刚毕业，误入一场不属于自己的故事。",
                "choice_values": {"genre": "都市日常"},
                "target_words": 500000,
                "average_words": 3000,
                "premise_candidates": [{"title": "测试小说", "synopsis": "简介"}],
                "premise_selected_index": 0,
                "step_results": {
                    "premise": {"candidates": [{"title": "测试小说"}]},
                    "bible": {"bible": {"core_setting": "底盘"}},
                    "stage_plan": {"stage_plan": [{"name": "第一阶段"}]},
                },
            }
            with patch.object(wizard, "CREATION_WIZARD_DRAFT_DIR", draft_dir), \
                patch.object(wizard, "CREATION_WIZARD_DRAFT_INDEX_FILE", draft_index), \
                patch.object(wizard, "CREATION_WIZARD_DRAFT_FILE", legacy_file):
                wizard.save_creation_wizard_draft(payload)
                project_path = os.path.join(tmp, "projects", "测试小说.json")
                archive_path = wizard.mark_creation_wizard_draft_completed(
                    draft_id,
                    project_path,
                    {"creation_framework": {"novel_name": "测试小说"}},
                )

                self.assertTrue(archive_path)
                saved = wizard.load_creation_wizard_draft(draft_id)
                self.assertEqual(saved["inspiration"], payload["inspiration"])
                self.assertEqual(set(saved["step_results"]), {"premise", "bible", "stage_plan"})
                self.assertEqual(saved["completion_status"], "completed")
                self.assertEqual(saved["imported_project_path"], os.path.abspath(project_path))

                records = wizard.list_creation_wizard_drafts()
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["status_label"], "已完成")
                self.assertEqual(records[0]["completion_status"], "completed")

    def test_inspiration_fact_guidance_is_shared_by_wizard_prompts(self):
        self.assertIn("作者灵感中明确写出的事实", wizard.COMMON_CREATION_RULES)
        for step in ("premise", "bible"):
            self.assertIn("作者灵感中明确写出的事实", wizard.STEP_PROMPTS[step])


if __name__ == "__main__":
    unittest.main()
