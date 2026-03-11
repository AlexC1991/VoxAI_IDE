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
            panel.settings_manager.get_advanced_agent_tools_enabled = lambda: True
            panel.settings_manager.get_web_search_enabled = lambda: True
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
                    f'<execute_command command="python tool_demo.py" cwd="{project_dir}" />'
                    if 'archive/tool_demo_moved.py' in messages[-1]['content'] and 'tool_demo.py' in messages[-1]['content'] else 'Execution batch failed.'
                ),
                lambda messages: (
                    'I successfully used multiple standard tools together and verified the final output.'
                    if 'final' in messages[-1]['content'] and any('Deleted file' in m.get('content', '') for m in messages if m.get('role') == 'system') else 'Execution batch failed.'
                ),
            ])

            with patch.object(panel, 'save_conversation'), \
                 patch.object(panel.rag_client, 'ingest_message'):
                panel.send_worker('Use the IDE tools to build, inspect, modify, verify, and clean up a tiny project.')
                completed = self._wait_until_idle(panel, timeout=30.0)

            self.assertTrue(completed)
            self.assertIn('multiple standard tools together', panel.messages[-1]['content'])
            self.assertEqual(panel.tool_loop_count, 5)
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
                f'<read_file path="requirements.txt" start_line="1" end_line="20" />\n'
                f'<execute_command command="python -c &quot;print(\'ok\')&quot;" cwd="{project_dir}" />',
                lambda messages: (
                    'Escaped edit succeeded and the file was updated.'
                    if 'numpy<2.0' in messages[-1]['content'] and 'STDOUT:\nok' in messages[-1]['content'] else 'Escaped edit rescan failed.'
                ),
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

    def test_agent_can_use_new_navigation_and_json_tools(self):
        old_root = get_project_root()
        project_dir = tempfile.mkdtemp(prefix='vox_tool_nav_').replace('\\', '/')
        panel = None
        try:
            set_project_root(project_dir)
            os.makedirs(os.path.join(project_dir, 'src'), exist_ok=True)
            with open(os.path.join(project_dir, 'src', 'app.py'), 'w', encoding='utf-8') as f:
                f.write('def helper():\n    return "ok"\n\ntoken = "demo"\nprint(token)\n')
            with open(os.path.join(project_dir, 'package.json'), 'w', encoding='utf-8') as f:
                f.write('{"name": "vox-demo", "scripts": {"test": "pytest -q"}}\n')

            with patch('ui.chat_panel.QTimer.singleShot', lambda *args, **kwargs: None):
                panel = ChatPanel()
            panel.mode_combo.setCurrentText('Siege')
            panel.model_combo.clear()
            panel.model_combo.addItem('scripted-agent', '[Test] scripted-agent')
            panel.model_combo.setCurrentIndex(0)
            panel.on_model_changed('scripted-agent')

            AIClient.configure_test_provider([
                '<find_files pattern="*app.py" root_dir="." />\n<read_json path="package.json" query="scripts.test" />',
                lambda messages: (
                    '<search_files query="token" root_dir="src" file_pattern="*.py" context_lines="1" />\n'
                    '<read_file path="src/app.py" start_line="1" end_line="20" with_line_numbers="true" />'
                    if 'app.py' in messages[-1]['content'] and 'pytest -q' in messages[-1]['content'] else 'Navigation batch failed.'
                ),
                lambda messages: (
                    'I successfully used the new navigation and structured-data tools.'
                    if any('Found Files for' in m.get('content', '') for m in messages if m.get('role') == 'system')
                    and '> 5 | print(token)' in messages[-1]['content']
                    and '1: def helper()' in messages[-1]['content'] else 'Inspection batch failed.'
                ),
            ])

            with patch.object(panel, 'save_conversation'), \
                 patch.object(panel.rag_client, 'ingest_message'):
                panel.send_worker('Inspect the demo project with the IDE tools and summarize what you find.')
                completed = self._wait_until_idle(panel, timeout=25.0)

            self.assertTrue(completed)
            self.assertIn('new navigation and structured-data tools', panel.messages[-1]['content'])
            system_messages = [m['content'] for m in panel.messages if m['role'] == 'system']
            self.assertTrue(any('Found Files for' in m and 'app.py' in m for m in system_messages))
            self.assertTrue(any('JSON content for' in m and 'pytest -q' in m for m in system_messages))
            self.assertTrue(any('1: def helper()' in m for m in system_messages))
            self.assertTrue(any('> 5 | print(token)' in m for m in system_messages))
        finally:
            if panel is not None:
                panel.close()
            set_project_root(old_root)

    def test_agent_can_use_semantic_python_navigation_tools(self):
        old_root = get_project_root()
        project_dir = tempfile.mkdtemp(prefix='vox_tool_semantic_').replace('\\', '/')
        panel = None
        try:
            set_project_root(project_dir)
            os.makedirs(os.path.join(project_dir, 'src'), exist_ok=True)
            with open(os.path.join(project_dir, 'src', 'engine.py'), 'w', encoding='utf-8') as f:
                f.write(
                    'class Worker:\n'
                    '    def run(self):\n'
                    '        return helper()\n\n'
                    'def helper():\n'
                    '    return "ok"\n\n'
                    'result = Worker().run()\n'
                )
            with open(os.path.join(project_dir, 'src', 'use_engine.py'), 'w', encoding='utf-8') as f:
                f.write(
                    'from engine import Worker\n\n'
                    'def main():\n'
                    '    return Worker().run()\n'
                )

            with patch('ui.chat_panel.QTimer.singleShot', lambda *args, **kwargs: None):
                panel = ChatPanel()
            panel.mode_combo.setCurrentText('Siege')
            panel.model_combo.clear()
            panel.model_combo.addItem('scripted-agent', '[Test] scripted-agent')
            panel.model_combo.setCurrentIndex(0)
            panel.on_model_changed('scripted-agent')

            AIClient.configure_test_provider([
                '<find_symbol symbol="Worker.run" root_dir="src" />\n<find_references symbol="Worker" root_dir="src" context_lines="0" />',
                lambda messages: (
                    '<read_python_symbols path="src/engine.py" symbols="Worker.run, helper" />'
                    if 'Worker.run' in messages[-1]['content'] and 'use_engine.py' in messages[-1]['content'] else 'Semantic navigation batch failed.'
                ),
                lambda messages: (
                    'I successfully used the semantic Python navigation tools.'
                    if '=== Method Worker.run' in messages[-1]['content'] and '=== Function helper' in messages[-1]['content'] else 'Semantic symbol read failed.'
                ),
            ])

            with patch.object(panel, 'save_conversation'), \
                 patch.object(panel.rag_client, 'ingest_message'):
                panel.send_worker('Use the semantic Python tools to inspect the Worker flow.')
                completed = self._wait_until_idle(panel, timeout=25.0)

            self.assertTrue(completed)
            self.assertIn('semantic Python navigation tools', panel.messages[-1]['content'])
            system_messages = [m['content'] for m in panel.messages if m['role'] == 'system']
            self.assertTrue(any("Python symbols for 'Worker.run'" in m and 'method Worker.run' in m for m in system_messages))
            self.assertTrue(any("Python references for 'Worker'" in m and 'use_engine.py' in m for m in system_messages))
            self.assertTrue(any("Python symbols from 'src/engine.py'" in m and '=== Method Worker.run' in m for m in system_messages))
        finally:
            if panel is not None:
                panel.close()
            set_project_root(old_root)

    def test_agent_can_use_test_discovery_and_import_graph_tools(self):
        old_root = get_project_root()
        project_dir = tempfile.mkdtemp(prefix='vox_tool_graph_').replace('\\', '/')
        panel = None
        try:
            set_project_root(project_dir)
            os.makedirs(os.path.join(project_dir, 'src'), exist_ok=True)
            os.makedirs(os.path.join(project_dir, 'tests'), exist_ok=True)
            os.makedirs(os.path.join(project_dir, 'core'), exist_ok=True)
            with open(os.path.join(project_dir, 'core', 'helpers.py'), 'w', encoding='utf-8') as f:
                f.write('def helper():\n    return "ok"\n')
            with open(os.path.join(project_dir, 'src', 'engine.py'), 'w', encoding='utf-8') as f:
                f.write(
                    'from core.helpers import helper\n\n'
                    'class Worker:\n'
                    '    def run(self):\n'
                    '        return helper()\n'
                )
            with open(os.path.join(project_dir, 'tests', 'test_engine.py'), 'w', encoding='utf-8') as f:
                f.write(
                    'from src.engine import Worker\n\n'
                    'class TestWorkerFlow:\n'
                    '    def test_run_returns_helper_result(self):\n'
                    '        assert Worker().run() == "ok"\n'
                )
            with open(os.path.join(project_dir, 'consumer.py'), 'w', encoding='utf-8') as f:
                f.write('from src.engine import Worker\n\nvalue = Worker().run()\n')

            with patch('ui.chat_panel.QTimer.singleShot', lambda *args, **kwargs: None):
                panel = ChatPanel()
            panel.mode_combo.setCurrentText('Siege')
            panel.model_combo.clear()
            panel.model_combo.addItem('scripted-agent', '[Test] scripted-agent')
            panel.model_combo.setCurrentIndex(0)
            panel.on_model_changed('scripted-agent')

            AIClient.configure_test_provider([
                '<find_tests source_path="src/engine.py" root_dir="tests" />\n<get_imports path="src/engine.py" include_external="false" />',
                lambda messages: (
                    '<find_importers target="src/engine.py" root_dir="." />\n'
                    '<read_python_symbols path="src/engine.py" symbols="Worker.run" />'
                    if 'tests/test_engine.py' in messages[-1]['content'] and 'core.helpers' in messages[-1]['content'] else 'Discovery batch failed.'
                ),
                lambda messages: (
                    'I successfully used the test discovery and import graph tools.'
                    if 'consumer.py' in messages[-1]['content'] and '=== Method Worker.run' in messages[-1]['content'] else 'Import graph batch failed.'
                ),
            ])

            with patch.object(panel, 'save_conversation'), \
                 patch.object(panel.rag_client, 'ingest_message'):
                panel.send_worker('Find the relevant tests and import relationships for src/engine.py.')
                completed = self._wait_until_idle(panel, timeout=25.0)

            self.assertTrue(completed)
            self.assertIn('test discovery and import graph tools', panel.messages[-1]['content'])
            system_messages = [m['content'] for m in panel.messages if m['role'] == 'system']
            self.assertTrue(any("Tests for 'src/engine.py'" in m and 'tests/test_engine.py' in m for m in system_messages))
            self.assertTrue(any("Imports in 'src/engine.py'" in m and 'core.helpers' in m for m in system_messages))
            self.assertTrue(any("Importers for 'src/engine.py'" in m and 'consumer.py' in m for m in system_messages))
        finally:
            if panel is not None:
                panel.close()
            set_project_root(old_root)


if __name__ == '__main__':
    unittest.main()

