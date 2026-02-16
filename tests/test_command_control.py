
import sys
import unittest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication

# Initialize QApplication (needed for QWidgets)
app = QApplication.instance() or QApplication(sys.argv)

import os
sys.path.append(os.getcwd())

from ui.chat_panel import ChatPanel

class TestCommandControl(unittest.TestCase):
    @patch('ui.chat_panel.AIWorker') # Mock the worker
    @patch('ui.chat_panel.QThread')  # Mock the thread
    def test_prompt_injection(self, MockThread, MockWorker):
        panel = ChatPanel()
        
        # Test Mode 1: Phased (Default)
        # Verify the dropdown exists
        self.assertTrue(hasattr(panel, 'mode_combo'))
        
        # Set to Phased
        panel.mode_combo.setCurrentText("🛑 Phased (Default)")
        
        # Trigger send (mocking input)
        panel.input_field.setText("Test Phased")
        panel._start_ai_worker("Test Phased")
        
        # Check args passed to AIWorker
        args, _ = MockWorker.call_args
        history = args[0]
        
        # Find the system message with the mode prompt
        found_mode_prompt = False
        for msg in history:
            if msg['role'] == 'system' and "MODE 1 (PHASED STRATEGIC ALIGNMENT)" in str(msg['content']):
                found_mode_prompt = True
                break
        
        self.assertTrue(found_mode_prompt, "Did not find Phased Mode prompt in history")
        
        # Test Mode 2: Siege
        panel.mode_combo.setCurrentText("🔥 Siege Mode")
        panel._start_ai_worker("Test Siege")
        
        args, _ = MockWorker.call_args
        history = args[0]
        
        found_mode_prompt = False
        for msg in history:
            if msg['role'] == 'system' and "MODE 2 (SIEGE MODE / FULL AUTO)" in str(msg['content']):
                found_mode_prompt = True
                self.assertIn("GO LIMITLESS", str(msg['content']))
                break
        
        self.assertTrue(found_mode_prompt, "Did not find Siege Mode prompt in history")
        print("\nSUCCESS: Both modes inject correct prompts.")

if __name__ == '__main__':
    unittest.main()
