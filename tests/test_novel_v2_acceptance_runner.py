import tempfile
import unittest

from scripts.novel_v2_300k_acceptance import (
    REQUIRED_MODEL,
    REQUIRED_PROVIDER_NAME,
    GPT55_CHAPTER_TARGET,
    GPT55_TARGET_START_CHAPTER,
    VISIBLE_PROJECT_TITLE,
    build_initial_project,
    initial_state,
    split_body_for_semantic_compression,
)


class NovelV2AcceptanceRunnerTests(unittest.TestCase):
    def test_acceptance_run_is_pinned_to_requested_visible_model(self):
        self.assertEqual(REQUIRED_PROVIDER_NAME, "hubway.cc")
        self.assertEqual(REQUIRED_MODEL, "gpt-5.5")
        self.assertIn("GPT-5.5", VISIBLE_PROJECT_TITLE)
        self.assertEqual(GPT55_TARGET_START_CHAPTER, 30)
        self.assertEqual(GPT55_CHAPTER_TARGET, 4000)

    def test_semantic_compression_split_preserves_all_paragraph_text(self):
        paragraphs = ["甲" * 120, "乙" * 80, "丙" * 140, "丁" * 60]
        source = "\n\n".join(paragraphs)

        segments = split_body_for_semantic_compression(source)

        self.assertEqual(len(segments), 2)
        self.assertEqual("\n\n".join(segments), source)

    def test_initial_project_is_isolated_long_form_stress_story(self):
        project = build_initial_project(300000)

        self.assertEqual(project["meta"]["target_words"], "300000")
        self.assertEqual(project["meta"]["status"], "写作中")
        self.assertGreaterEqual(len(project["characters"]), 8)
        self.assertGreaterEqual(len(project["lore"]), 6)
        self.assertGreaterEqual(len(project["foreshadow_items"]), 10)
        self.assertEqual(len({item["id"] for item in project["foreshadow_items"]}), len(project["foreshadow_items"]))
        self.assertTrue(all(item["status"] == "未埋" for item in project["foreshadow_items"]))
        self.assertEqual(project["chapters"], [])

    def test_initial_state_allows_fifteen_repair_chapters(self):
        state = initial_state(300000, 100)

        self.assertEqual(state["target_words"], 300000)
        self.assertEqual(state["base_chapters"], 100)
        self.assertEqual(state["max_total_chapters"], 115)
        self.assertEqual(state["api_calls"], 0)
        self.assertEqual(state["chapter_metrics"], [])


if __name__ == "__main__":
    unittest.main()
