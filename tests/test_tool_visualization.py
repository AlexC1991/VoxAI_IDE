
import sys
import unittest
from unittest.mock import MagicMock, patch
import os

# Initialize paths
sys.path.append(os.getcwd())

from PySide6.QtWidgets import QApplication
# Initialize QApplication
app = QApplication.instance() or QApplication(sys.argv)

from ui.widgets.chat_items import MessageItem
from ui.chat_panel import ChatPanel

class TestToolVisualization(unittest.TestCase):
    
    def test_message_item_tool_role(self):
        # Test that MessageItem handles "tool" role correctly
        item = MessageItem("tool", "Executing: test_tool")
        
        # Check role label
        self.assertEqual("Tool", item.role_label.text())
        
        # Tool labels use the current tool accent color
        self.assertIn("#4ec9b0", item.role_label.styleSheet())

    @patch('ui.chat_panel.ToolWorker')
    @patch('ui.chat_panel.QThread')
    def test_chat_panel_logs_tool(self, MockThread, MockToolWorker):
        panel = ChatPanel()

        try:
            with patch.object(panel, '_add_chat_widget') as mock_add:
                tools = [{"cmd": "list_files", "args": {"path": "."}}]
                panel._start_tool_execution(tools)

                mock_add.assert_called_once_with(panel.progress_item)
                self.assertIn("Running: list_files", panel.progress_item.thought_content.text())
        finally:
            panel.close()

if __name__ == '__main__':
    unittest.main()
