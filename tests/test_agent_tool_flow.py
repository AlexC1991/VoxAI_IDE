import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
sys.path.append(os.getcwd())

from core.ai_client import AIClient
from core.agent_tools import get_project_root, set_project_root
from ui.chat_panel import ChatPanel


class TestAgentToolFlow(unittest.TestCase):
    def tearDown(self):
        AIClient.clear_test_provider()

    def _wait_until(self, predicate, timeout=20.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            app.processEvents()
            if predicate():
                return True
            time.sleep(0.02)
        app.processEvents()
        return predicate()

    def _wait_until_idle(self, panel, timeout=20.0):
        return self._wait_until(
            lambda: not panel.is_processing and getattr(panel, 'ai_thread_obj', None) is None and getattr(panel, 'tool_thread', None) is None,
            timeout=timeout,
        )

    def test_agent_can_use_many_standard_tools_together(self):
        old_root = get_project_root()
        project_dir = tempfile.mkdtemp(prefix='vox_tool_flow_').replace('\\', '/')
        panel = None
        try:
            set_project_root(project_dir)
            with patch('ui.chat_panel.QTimer.singleShot', lambda *args, **kwargs: None):
                panel = ChatPanel()
            panel.mode_combo.setCurrentText('Siege')
            panel.model_combo.clear()
            panel.model_combo.addItem('scripted-agent', '[Test] scripted-agent')
            panel.model_combo.setCurrentIndex(0)
            panel.on_model_changed('scripted-agent')

            AIClient.configure_test_provider([
                '<write_file path="tool_demo.py">\nclass Demo:\n    def value(self):\n        return "draft"\n\nif __name__ == "__main__":\n    print(Demo().value())\n</write_file>\n<list_files path="." />',
                lambda messages: (
                    '<read_file path="tool_demo.py" start_line="1" end_line="40" />\n'
                    '<get_file_structure path="tool_demo.py" />\n'
                    '<search_files query="draft" root_dir="." file_pattern="*.py" />'
                    if 'tool_demo.py' in messages[-1]['content'] else 'Initial tool batch failed.'
                ),
                lambda messages: (
                    f'<edit_file path="tool_demo.py" old_text="draft" new_text="final" />\n'
                    '<copy_file src="tool_demo.py" dst="copy/tool_demo.py" />\n'
                    '<move_file src="copy/tool_demo.py" dst="archive/tool_demo_moved.py" />\n'
                    f'<execute_command command="python tool_demo.py" cwd="{project_dir}" />\n'
                    '<delete_file path="archive/tool_demo_moved.py" />'
                    if 'Class: Demo' in messages[-1]['content'] and 'draft' in messages[-1]['content'] else 'Inspection batch failed.'
                ),
                lambda messages: (
                    'I successfully used multiple standard tools together and verified the final output.'
                    if 'final' in messages[-1]['content'] and 'Deleted file' in messages[-1]['content'] else 'Execution batch failed.'
                ),
            ])

            with patch.object(panel, 'save_conversation'), \
                 patch.object(panel.rag_client, 'ingest_message'):
                panel.send_worker('Use the IDE tools to build, inspect, modify, verify, and clean up a tiny project.')
                completed = self._wait_until_idle(panel, timeout=30.0)

            self.assertTrue(completed)
            self.assertIn('multiple standard tools together', panel.messages[-1]['content'])
            self.assertEqual(panel.tool_loop_count, 3)
            with open(os.path.join(project_dir, 'tool_demo.py'), 'r', encoding='utf-8') as f:
                self.assertIn('final', f.read())
            self.assertFalse(os.path.exists(os.path.join(project_dir, 'archive', 'tool_demo_moved.py')))
            system_messages = [m['content'] for m in panel.messages if m['role'] == 'system']
            self.assertTrue(any('Class: Demo' in m for m in system_messages))
            self.assertTrue(any('STDOUT:\nfinal' in m for m in system_messages))
        finally:
            if panel is not None:
                panel.close()
            set_project_root(old_root)

    def test_agent_can_edit_using_xml_escaped_tool_args(self):
        old_root = get_project_root()
        project_dir = tempfile.mkdtemp(prefix='vox_tool_escape_').replace('\\', '/')
        panel = None
        try:
            set_project_root(project_dir)
            with open(os.path.join(project_dir, 'requirements.txt'), 'w', encoding='utf-8') as f:
                f.write('numpy<2\n')
            with patch('ui.chat_panel.QTimer.singleShot', lambda *args, **kwargs: None):
                panel = ChatPanel()
            panel.mode_combo.setCurrentText('Siege')
            panel.model_combo.clear()
            panel.model_combo.addItem('scripted-agent', '[Test] scripted-agent')
            panel.model_combo.setCurrentIndex(0)
            panel.on_model_changed('scripted-agent')

            AIClient.configure_test_provider([
                '<edit_file path="requirements.txt" old_text="numpy&lt;2" new_text="numpy&lt;2.0" />',
                'Escaped edit succeeded and the file was updated.'
            ])

            with patch.object(panel, 'save_conversation'), \
                 patch.object(panel.rag_client, 'ingest_message'):
                panel.send_worker('Update the numpy pin safely.')
                completed = self._wait_until_idle(panel, timeout=20.0)

            self.assertTrue(completed)
            self.assertIn('Escaped edit succeeded', panel.messages[-1]['content'])
            with open(os.path.join(project_dir, 'requirements.txt'), 'r', encoding='utf-8') as f:
                self.assertEqual(f.read(), 'numpy<2.0\n')
        finally:
            if panel is not None:
                panel.close()
            set_project_root(old_root)


if __name__ == '__main__':
    unittest.main()

