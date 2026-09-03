import unittest

from gpt_desktop.novel_utils import _build_chapter_ai_context, _normalize_project


class LegacyContinuityContextTests(unittest.TestCase):
    def test_clean_chapter_46_keeps_rescue_chain_and_viewpoint_boundary(self):
        project = _normalize_project(
            {
                "meta": {"title": "测试", "target_words": "5000"},
                "characters": [
                    {
                        "id": "char-old-helper",
                        "name": "老杂役",
                        "role": "后山杂役",
                        "notes": "章节中也称“杂役”；第2-3章发现林辰未死后救治。",
                    }
                ],
                "lore": [
                    {
                        "id": "lore-room",
                        "name": "长老院地下密室",
                        "type": "地点",
                        "description": "",
                        "story_known": "密室石台旁有铜盘。",
                    }
                ],
                "chapters": [
                    {
                        "id": "chapter-1",
                        "title": "觉骨",
                        "outline": "开篇",
                        "text": "开篇正文",
                        "summary": "",
                        "key_facts": "",
                        "linked_characters": [],
                    },
                    {
                        "id": "chapter-2",
                        "title": "一夕剔骨",
                        "outline": "林辰在密室被挖骨，随后交给老杂役。",
                        "text": "密室正文",
                        "summary": "",
                        "key_facts": "",
                        "linked_characters": ["老杂役"],
                    },
                    {
                        "id": "chapter-3",
                        "title": "众口成罪",
                        "outline": "老杂役将林辰转入木屋救治。",
                        "text": "木屋正文",
                        "summary": "",
                        "key_facts": "",
                        "linked_characters": ["杂役"],
                    },
                    {
                        "id": "chapter-46",
                        "title": "血债昭然",
                        "outline": "林辰在祖祠追问挖骨和乱葬岗灭口，老杂役出面作证。",
                        "text": "",
                        "summary": "",
                        "key_facts": "",
                        "linked_characters": ["当年杂役"],
                        "linked_character_ids": [],
                        "linked_lore_ids": [],
                        "memory_selection": {
                            "fact_ids": ["AF-rescue", "AF-bone", "AF-wrong-view"],
                            "_restrict_facts": True,
                        },
                    },
                ],
                "long_form_memory": {
                    "state_snapshot": {
                        "as_of_chapter_index": 2,
                        "character_states": [],
                        "object_states": [
                            {
                                "name": "C003.original_bone",
                                "state": "林浩原有的暗青色中品骨已剔出，最后在密室石台旁铜盘。",
                            }
                        ],
                    },
                    "active_facts": [
                        {
                            "id": "AF-rescue",
                            "source_chapter_index": 2,
                            "fact": "两名灰衣执事把林辰交给老杂役送往乱葬岗；老杂役发现他仍活着，改道废弃守山木屋救治。",
                        },
                        {
                            "id": "AF-bone",
                            "source_chapter_index": 3,
                            "fact": "林浩原有的暗青色中品骨已剔出并留在密室铜盘。",
                        },
                        {
                            "id": "AF-wrong-view",
                            "source_chapter_index": 2,
                            "fact": "老杂役目睹剔骨现场，亲眼见到铜盘中的骨。",
                        },
                    ],
                },
            }
        )
        original_snapshot_index = project["long_form_memory"]["state_snapshot"]["as_of_chapter_index"]
        context = _build_chapter_ai_context(project, 3, "draft")
        self.assertIn("【历史连续性依据】", context)
        self.assertIn("老杂役", context)
        self.assertIn("长老院地下密室", context)
        self.assertIn("铜盘", context)
        self.assertIn("第2章已确认", context)
        self.assertIn("第3章已确认", context)
        self.assertNotIn("老杂役目睹", context)
        self.assertNotIn("老杂役亲眼见到剔骨", context)
        self.assertEqual(
            project["long_form_memory"]["state_snapshot"]["as_of_chapter_index"],
            original_snapshot_index,
        )


if __name__ == "__main__":
    unittest.main()
