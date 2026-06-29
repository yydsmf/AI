import unittest

from gpt_desktop.agent_chat_renderer import AgentChatRenderer


class AgentChatRendererTests(unittest.TestCase):
    def test_streaming_message_can_include_outer_margin_for_incremental_insert(self):
        html = AgentChatRenderer.streaming_message_html("正在思考...", outer_margin=True)
        self.assertIn("margin:12px 14px 20px 14px", html)
        self.assertIn("智能体：", html)

    def test_normal_streaming_message_keeps_plain_wrapper(self):
        html = AgentChatRenderer.streaming_message_html("正在思考...")
        self.assertNotIn("margin:12px 14px 20px 14px", html)
        self.assertIn("智能体：", html)

    def test_context_cleared_message_is_centered_notice(self):
        renderer = AgentChatRenderer([
            {
                "role": "assistant",
                "content": "【上下文已清除】",
                "_local_status": "context_cleared",
            }
        ])
        html = renderer.message_to_html(renderer.messages[0], 0)
        self.assertIn("text-align:center", html)
        self.assertIn("上下文已清除", html)
        self.assertNotIn("meta-error", html)


if __name__ == "__main__":
    unittest.main()
