
import sys
import unittest
from unittest.mock import MagicMock, patch
import os

# Initialize paths
sys.path.append(os.getcwd())

from PySide6.QtWidgets import QApplication
# Initialize QApplication
app = QApplication.instance() or QApplication(sys.argv)

from ui.widgets.chat_items import MessageItem, _C_ACCENT
from ui.chat_panel import ChatPanel

class TestToolVisualization(unittest.TestCase):
    
    def test_message_item_tool_role(self):
        # Test that MessageItem handles "tool" role correctly
        item = MessageItem("tool", "Executing: test_tool")
        
        # Check prefix in role label
        self.assertIn("⚡", item.role_label.text())
        self.assertIn("Tool", item.role_label.text())
        
        # Check styling (font color should be _C_ACCENT)
        # We can't easily check the stylesheet string matching exactly, but we can check if it contains the color
        self.assertIn(_C_ACCENT, item.role_label.styleSheet())

    @patch('ui.chat_panel.ToolWorker')
    @patch('ui.chat_panel.QThread')
    def test_chat_panel_logs_tool(self, MockThread, MockToolWorker):
        panel = ChatPanel()
        
        # Mock append_message_widget to verify usage log
        # Note: panel._start_tool_execution calls append_message_widget
        
        # We need to ensure progress_item doesn't crash
        # It's a real widget, but without a parent layout in test it might be fine, 
        # but chat_layout.addWidget might crash if chat_layout is not set up fully?
        # ChatPanel init creates layout.
        
        with patch.object(panel, 'append_message_widget') as mock_append:
            tools = [("list_files", {"path": "."})]
            panel._start_tool_execution(tools)
            
            # Verify usage log
            # The FIRST call should be the tool log
            # start_tool_execution calls it
            
            # Check args of the call with role "tool"
            # mock_append.call_args_list might have multiple if output also calls it?
            # But we are just starting execution.
            
            found = False
            for call in mock_append.call_args_list:
                args, _ = call
                if args[0] == "tool":
                    self.assertIn("**list_files**", args[1])
                    found = True
                    break
            
            self.assertTrue(found, "Did not find tool log message")

if __name__ == '__main__':
    unittest.main()
