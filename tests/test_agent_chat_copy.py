import unittest

from gpt_desktop.agent_chat_copy import AgentChatCopyMixin


class AgentChatCopyTests(unittest.TestCase):
    def clean(self, text):
        return AgentChatCopyMixin._clean_chat_selection_text(None, text)

    def test_keeps_list_line_breaks(self):
        text = "\n更色气\n更冷艳\n更甜美\n特定颜色\n特定姿势（躺姿、跪姿、背面等）\n"
        self.assertEqual(
            self.clean(text),
            "更色气\n更冷艳\n更甜美\n特定颜色\n特定姿势（躺姿、跪姿、背面等）",
        )

    def test_trims_outer_blank_lines(self):
        self.assertEqual(self.clean("\n\n第一行\n第二行\n\n"), "第一行\n第二行")

    def test_collapses_repeated_blank_lines(self):
        self.assertEqual(self.clean("第一段\n\n\n第二段"), "第一段\n\n第二段")

    def test_converts_qtext_selection_separators(self):
        self.assertEqual(self.clean("第一行\u2029第二行\u2028第三行"), "第一行\n第二行\n第三行")


if __name__ == "__main__":
    unittest.main()
