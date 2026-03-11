import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
sys.path.append(os.getcwd())

from core.agent_tools import get_project_root, set_project_root
from ui.chat_workers import ToolWorker


class TestToolWorkerMatrix(unittest.TestCase):
    def setUp(self):
        self._old_root = get_project_root()
        self._tmp = tempfile.TemporaryDirectory()
        set_project_root(self._tmp.name)

    def tearDown(self):
        set_project_root(self._old_root)
        self._tmp.cleanup()

    def _run_worker(self, calls, *, advanced=False, web=False, rag=True):
        worker = ToolWorker(calls, auto_approve=True)
        worker.settings.get_advanced_agent_tools_enabled = MagicMock(return_value=advanced)
        worker.settings.get_web_search_enabled = MagicMock(return_value=web)
        worker.settings.get_rag_enabled = MagicMock(return_value=rag)
        outputs = []
        worker.finished.connect(outputs.append)
        worker.run()
        return outputs[0]

    def test_index_codebase_delegates_to_indexer(self):
        with patch.object(ToolWorker, '_rag_enabled', return_value=True), \
             patch('core.indexer.ProjectIndexer.index_project', return_value=True) as mock_index:
            output = self._run_worker([{'cmd': 'index_codebase', 'args': {'path': '.'}}], advanced=True, rag=True)

        self.assertTrue(mock_index.called)
        self.assertEqual(mock_index.call_args.args[-1], '.')
        self.assertIn("Successfully indexed codebase at '.'", output)

    def test_git_tools_delegate_expected_commands(self):
        calls = [
            {'cmd': 'git_status', 'args': {}},
            {'cmd': 'git_diff', 'args': {'path': 'tool_demo.py'}},
            {'cmd': 'git_log', 'args': {'count': '3'}},
            {'cmd': 'git_commit', 'args': {'message': 'feat: demo'}},
            {'cmd': 'git_fetch', 'args': {'remote': 'origin'}},
            {'cmd': 'git_pull', 'args': {'remote': 'origin', 'branch': 'main'}},
            {'cmd': 'git_push', 'args': {'remote': 'origin', 'branch': 'main'}},
        ]

        with patch('ui.chat_workers.AgentToolHandler.execute_command', side_effect=lambda cmd, cwd=None: f'ran {cmd}') as mock_exec:
            output = self._run_worker(calls, advanced=True)

        self.assertEqual(
            [call.args[0] for call in mock_exec.call_args_list],
            [
                'git status --short', 'git diff tool_demo.py', 'git log --oneline -n 3',
                'git add -A && git commit -m "feat: demo"', 'git fetch origin',
                'git pull origin main', 'git push origin main'
            ]
        )
        self.assertIn('Git Output (git_push):\nran git push origin main', output)

    def test_web_tools_delegate_to_irongate(self):
        with patch('Vox_IronGate.IronGateClient.web_search', return_value='web ok') as mock_search, \
             patch('Vox_IronGate.IronGateClient.fetch_url', return_value='fetch ok') as mock_fetch:
            output = self._run_worker([
                {'cmd': 'web_search', 'args': {'query': 'python unittest'}},
                {'cmd': 'fetch_url', 'args': {'url': 'https://example.com'}},
            ], advanced=True, web=True)

        mock_search.assert_called_once_with('python unittest')
        mock_fetch.assert_called_once_with('https://example.com')
        self.assertIn('Web Search Results:\nweb ok', output)
        self.assertIn('Fetched URL:\nfetch ok', output)

    def test_file_navigation_and_json_tools_delegate_expected_arguments(self):
        with patch('ui.chat_workers.AgentToolHandler.read_file', return_value='1: alpha') as mock_read, \
             patch('ui.chat_workers.AgentToolHandler.read_json', return_value='"pytest -q"') as mock_json, \
             patch('ui.chat_workers.AgentToolHandler.find_files', return_value='src/app.py') as mock_find, \
             patch('ui.chat_workers.AgentToolHandler.search_files', return_value='src/app.py:2:\n> 2 | print(token)') as mock_search:
            output = self._run_worker([
                {'cmd': 'read_file', 'args': {'path': 'src/app.py', 'start_line': '1', 'end_line': '3', 'with_line_numbers': 'true'}},
                {'cmd': 'read_json', 'args': {'path': 'package.json', 'query': 'scripts.test', 'max_chars': '800'}},
                {'cmd': 'find_files', 'args': {'pattern': '*app.py', 'root_dir': '.', 'case_insensitive': 'true', 'max_results': '5'}},
                {'cmd': 'search_files', 'args': {'query': 'token', 'root_dir': '.', 'file_pattern': '*.py', 'case_insensitive': 'true', 'context_lines': '2', 'max_results': '7'}},
            ])

        mock_read.assert_called_once_with('src/app.py', start_line=1, end_line=3, with_line_numbers=True)
        mock_json.assert_called_once_with('package.json', query='scripts.test', max_chars=800)
        mock_find.assert_called_once_with('*app.py', root_dir='.', case_insensitive=True, max_results=5)
        mock_search.assert_called_once_with('token', '.', file_pattern='*.py', case_insensitive=True, context_lines=2, max_results=7)
        self.assertIn("Read file 'src/app.py':\n1: alpha", output)
        self.assertIn("JSON content for 'package.json':\n\"pytest -q\"", output)
        self.assertIn("Found Files for '*app.py':\nsrc/app.py", output)
        self.assertIn("Search Results for 'token':\nsrc/app.py:2", output)

    def test_python_symbol_tools_delegate_expected_arguments(self):
        with patch('ui.chat_workers.AgentToolHandler.find_symbol', return_value='src/app.py:3: method Demo.run') as mock_find_symbol, \
             patch('ui.chat_workers.AgentToolHandler.find_references', return_value='src/app.py:8:\n> 8 | Demo().run()') as mock_find_refs, \
             patch('ui.chat_workers.AgentToolHandler.read_python_symbols', return_value='=== Method Demo.run (lines 3-4) ===\n3:     def run(self):') as mock_read_symbols:
            output = self._run_worker([
                {'cmd': 'find_symbol', 'args': {'symbol': 'Demo.run', 'root_dir': 'src', 'symbol_type': 'method', 'file_pattern': '*.py', 'max_results': '4'}},
                {'cmd': 'find_references', 'args': {'symbol': 'Demo', 'root_dir': 'src', 'file_pattern': '*.py', 'context_lines': '1', 'max_results': '6', 'include_definitions': 'true'}},
                {'cmd': 'read_python_symbols', 'args': {'path': 'src/app.py', 'symbols': 'Demo.run', 'with_line_numbers': 'true', 'max_symbols': '2'}},
            ])

        mock_find_symbol.assert_called_once_with('Demo.run', root_dir='src', symbol_type='method', file_pattern='*.py', max_results=4)
        mock_find_refs.assert_called_once_with('Demo', root_dir='src', file_pattern='*.py', context_lines=1, max_results=6, include_definitions=True)
        mock_read_symbols.assert_called_once_with('src/app.py', symbols='Demo.run', with_line_numbers=True, max_symbols=2)
        self.assertIn("Python symbols for 'Demo.run':\nsrc/app.py:3: method Demo.run", output)
        self.assertIn("Python references for 'Demo':\nsrc/app.py:8", output)
        self.assertIn("Python symbols from 'src/app.py':\n=== Method Demo.run", output)

    def test_test_discovery_and_import_tools_delegate_expected_arguments(self):
        with patch('ui.chat_workers.AgentToolHandler.find_tests', return_value='tests/test_demo.py:5: TestDemo.test_run [matches: demo]') as mock_find_tests, \
             patch('ui.chat_workers.AgentToolHandler.get_imports', return_value='1: from core.agent_tools import AgentToolHandler [internal]') as mock_get_imports, \
             patch('ui.chat_workers.AgentToolHandler.find_importers', return_value='ui/chat_panel.py:20: from core.agent_tools import AgentToolHandler [matches core.agent_tools]') as mock_find_importers:
            output = self._run_worker([
                {'cmd': 'find_tests', 'args': {'source_path': 'src/demo.py', 'root_dir': 'tests', 'max_results': '4'}},
                {'cmd': 'get_imports', 'args': {'path': 'ui/chat_panel.py', 'include_external': 'false'}},
                {'cmd': 'find_importers', 'args': {'target': 'core.agent_tools', 'root_dir': '.', 'file_pattern': '*.py', 'max_results': '8'}},
            ])

        mock_find_tests.assert_called_once_with(query=None, source_path='src/demo.py', root_dir='tests', max_results=4)
        mock_get_imports.assert_called_once_with('ui/chat_panel.py', include_external=False)
        mock_find_importers.assert_called_once_with('core.agent_tools', root_dir='.', file_pattern='*.py', max_results=8)
        self.assertIn("Tests for 'src/demo.py':\ntests/test_demo.py:5", output)
        self.assertIn("Imports in 'ui/chat_panel.py':\n1: from core.agent_tools import AgentToolHandler [internal]", output)
        self.assertIn("Importers for 'core.agent_tools':\nui/chat_panel.py:20", output)

    def test_advanced_tool_batch_is_blocked_by_default(self):
        with patch('ui.chat_workers.AgentToolHandler.execute_command') as mock_exec:
            output = self._run_worker([
                {'cmd': 'git_status', 'args': {}},
                {'cmd': 'web_search', 'args': {'query': 'python unittest'}},
            ])

        mock_exec.assert_not_called()
        self.assertIn('Advanced agent tools are disabled', output)
        self.assertIn('Web tools are disabled until Advanced Agent Tools is enabled', output)

    def test_failed_command_is_marked_failed_and_reported_in_action_summary(self):
        worker = ToolWorker([{'cmd': 'execute_command', 'args': {'command': 'python broken.py', 'cwd': '.'}}], auto_approve=True)
        outputs = []
        step_statuses = []
        worker.finished.connect(outputs.append)
        worker.step_finished.connect(lambda title, detail, status: step_statuses.append((title, status)))

        with patch('ui.chat_workers.AgentToolHandler.execute_command', return_value='STDERR:\nboom\n[Exit code: 1]'):
            worker.run()

        self.assertEqual(step_statuses[0][1], 'Failed')
        self.assertIn('[ACTION_SUMMARY]', outputs[0])
        self.assertIn('Failed actions:', outputs[0])
        self.assertIn('execute_command python broken.py', outputs[0])


if __name__ == '__main__':
    unittest.main()

