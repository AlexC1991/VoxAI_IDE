import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
sys.path.append(os.getcwd())

from core.agent_tools import get_project_root, set_project_root
from ui.chat_panel import ToolWorker


class TestToolWorkerMatrix(unittest.TestCase):
    def setUp(self):
        self._old_root = get_project_root()
        self._tmp = tempfile.TemporaryDirectory()
        set_project_root(self._tmp.name)

    def tearDown(self):
        set_project_root(self._old_root)
        self._tmp.cleanup()

    def _run_worker(self, calls):
        worker = ToolWorker(calls, auto_approve=True)
        outputs = []
        worker.finished.connect(outputs.append)
        worker.run()
        return outputs[0]

    def test_index_codebase_delegates_to_indexer(self):
        with patch.object(ToolWorker, '_rag_enabled', return_value=True), \
             patch('core.indexer.ProjectIndexer.index_project', return_value=True) as mock_index:
            output = self._run_worker([{'cmd': 'index_codebase', 'args': {'path': '.'}}])

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

        with patch('ui.chat_panel.AgentToolHandler.execute_command', side_effect=lambda cmd, cwd=None: f'ran {cmd}') as mock_exec:
            output = self._run_worker(calls)

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
            ])

        mock_search.assert_called_once_with('python unittest')
        mock_fetch.assert_called_once_with('https://example.com')
        self.assertIn('Web Search Results:\nweb ok', output)
        self.assertIn('Fetched URL:\nfetch ok', output)

    def test_failed_command_is_marked_failed_and_reported_in_action_summary(self):
        worker = ToolWorker([{'cmd': 'execute_command', 'args': {'command': 'python broken.py', 'cwd': '.'}}], auto_approve=True)
        outputs = []
        step_statuses = []
        worker.finished.connect(outputs.append)
        worker.step_finished.connect(lambda title, detail, status: step_statuses.append((title, status)))

        with patch('ui.chat_panel.AgentToolHandler.execute_command', return_value='STDERR:\nboom\n[Exit code: 1]'):
            worker.run()

        self.assertEqual(step_statuses[0][1], 'Failed')
        self.assertIn('[ACTION_SUMMARY]', outputs[0])
        self.assertIn('Failed actions:', outputs[0])
        self.assertIn('execute_command python broken.py', outputs[0])


if __name__ == '__main__':
    unittest.main()

