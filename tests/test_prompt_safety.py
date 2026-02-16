
import sys
import unittest
from unittest.mock import MagicMock, patch
import os
from PySide6.QtWidgets import QApplication

# Initialize QApplication
app = QApplication.instance() or QApplication(sys.argv)

# Initialize paths
sys.path.append(os.getcwd())

try:
    from ui.chat_panel import ChatPanel
    from core.prompts import SystemPrompts
except Exception as e:
    print(f"IMPORT ERROR: {e}")
    sys.exit(1)

print("Imports successful. Starting tests...")

class TestPromptSafety(unittest.TestCase):
    
    @patch('ui.chat_panel.AIWorker') 
    @patch('ui.chat_panel.QThread')
    def test_local_model_uses_lite_prompt(self, MockThread, MockWorker):
        panel = ChatPanel()
        panel.model_combo = MagicMock()
        panel.mode_combo = MagicMock()
        
        # 1. Test Local Model + Greeting
        panel.model_combo.currentText.return_value = "[Local] mistral.gguf"
        panel.mode_combo.currentText.return_value = "🛑 Phased (Default)"
        
        panel._start_ai_worker("Hey")
        
        # Check args passed to AIWorker
        args, _ = MockWorker.call_args
        history = args[0]
        system_msg = history[0]['content']
        
        # Should be Lite Prompt
        self.assertIn("Do NOT use tools unless explicitly requested", system_msg)
        # Should have Safety Latch
        self.assertIn("THIS IS A GREETING", system_msg)
        
        # 2. Test Local Model + Complex Request
        # Reset Mock
        MockWorker.reset_mock()
        panel._start_ai_worker("Analyze the database schema")
         
        args, _ = MockWorker.call_args
        history = args[0]
        system_msg = history[0]['content']
        
        # Should be Lite Prompt
        self.assertIn("Do NOT use tools unless explicitly requested", system_msg)
        # Should NOT have Safety Latch
        self.assertNotIn("THIS IS A GREETING", system_msg)

    @patch('ui.chat_panel.AIWorker') 
    @patch('ui.chat_panel.QThread')
    def test_remote_model_uses_full_prompt(self, MockThread, MockWorker):
        panel = ChatPanel()
        panel.model_combo = MagicMock()
        panel.mode_combo = MagicMock()
        
        # Test Remote Model
        panel.model_combo.currentText.return_value = "[OpenAI] gpt-4"
        panel.mode_combo.currentText.return_value = "🛑 Phased (Default)"
        
        panel._start_ai_worker("Hey")
        
        args, _ = MockWorker.call_args
        history = args[0]
        system_msg = history[0]['content']
        
        # Should be Full Prompt (check for specific full prompt rules)
        self.assertIn("Tool-First Policy (CRITICAL)", system_msg)
        # Should NOT have Safety Latch
        self.assertNotIn("THIS IS A GREETING", system_msg)

if __name__ == '__main__':
    unittest.main()
