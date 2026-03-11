
import os
import sys
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
sys.path.append(os.getcwd())

from ui.chat_panel import ChatPanel


class TestPromptSafety(unittest.TestCase):
    def _panel_for_model(self, full_model_name: str) -> ChatPanel:
        panel = ChatPanel()
        panel.model_combo.clear()
        panel.model_combo.addItem(full_model_name, full_model_name)
        panel.model_combo.setCurrentIndex(0)
        panel.mode_combo.setCurrentText("Phased")
        return panel

    @patch('ui.chat_panel.AIWorker')
    @patch('ui.chat_panel.QThread')
    def test_local_model_uses_lite_prompt_and_greeting_latch(self, MockThread, MockWorker):
        panel = self._panel_for_model("[Local] mistral.gguf")

        panel._start_ai_worker("Hey")
        history = MockWorker.call_args.args[0]
        system_msg = history[0]['content']

        self.assertIn("Do NOT use tools unless explicitly requested", system_msg)
        self.assertIn("THIS IS A GREETING", system_msg)
        self.assertIn("do not output executable XML tags", system_msg)

        MockWorker.reset_mock()
        panel._start_ai_worker("Analyze the database schema")
        history = MockWorker.call_args.args[0]
        system_msg = history[0]['content']

        self.assertIn("Do NOT use tools unless explicitly requested", system_msg)
        self.assertNotIn("THIS IS A GREETING", system_msg)

    @patch('ui.chat_panel.AIWorker')
    @patch('ui.chat_panel.QThread')
    def test_remote_model_uses_full_prompt_with_tool_safety_rules(self, MockThread, MockWorker):
        panel = self._panel_for_model("[OpenAI] gpt-4")

        panel._start_ai_worker("Hey")
        history = MockWorker.call_args.args[0]
        base_prompt = history[0]['content']

        self.assertIn("Tool-First: Use native local tools", base_prompt)
        self.assertIn("Tool Safety: Emit XML tool tags ONLY when you intend real execution", base_prompt)
        self.assertIn("Never put long multi-line snippets inside <edit_file", base_prompt)
        self.assertIn("Only run/read further when the user explicitly asked for validation/inspection", base_prompt)
        self.assertIn("GROUNDED, CONCISE summary", base_prompt)
        self.assertIn("at most 2 short bullets or 3 very short lines total", base_prompt)
        self.assertIn("Include next-step advice only if the user asked for it", base_prompt)
        self.assertNotIn("After writing a file, STOP", base_prompt)
        self.assertNotIn("THIS IS A GREETING", base_prompt)

if __name__ == '__main__':
    unittest.main()
