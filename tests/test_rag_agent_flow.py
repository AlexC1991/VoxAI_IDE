import os
import shutil
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
from core.rag_client import RAGClient
from core.settings import SettingsManager
from ui.chat_panel import ChatPanel


class TestRAGAgentFlow(unittest.TestCase):
    def tearDown(self):
        AIClient.clear_test_provider()
        RAGClient.shutdown_server()

    def _wait_until(self, predicate, timeout=30.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            app.processEvents()
            if predicate():
                return True
            time.sleep(0.02)
        app.processEvents()
        return predicate()

    def _wait_until_idle(self, panel, timeout=30.0):
        return self._wait_until(
            lambda: not panel.is_processing and getattr(panel, 'ai_thread_obj', None) is None and getattr(panel, 'tool_thread', None) is None,
            timeout=timeout,
        )

    def test_offline_test_provider_can_drive_real_rag_end_to_end(self):
        old_root = get_project_root()
        project_dir = tempfile.mkdtemp(prefix='vox_rag_agent_')
        panel = None
        file_marker = 'amber_lattice_file_marker_4242'
        memory_query = 'canary phrase'
        memory_payload = 'velvet badger orbit'
        try:
            set_project_root(project_dir)
            with open(os.path.join(project_dir, 'app.py'), 'w', encoding='utf-8') as f:
                f.write(f'code_beacon = "{file_marker}"\nprint(code_beacon)\n')

            with patch.object(SettingsManager, 'get_rag_enabled', return_value=True), \
                 patch.object(SettingsManager, 'get_rag_top_k', return_value=3), \
                 patch.object(SettingsManager, 'get_rag_min_score', return_value=0.0), \
                 patch.object(SettingsManager, 'get_rag_max_context', return_value=4000), \
                 patch.object(SettingsManager, 'get_rag_max_chunk', return_value=250), \
                 patch('ui.chat_panel.QTimer.singleShot', lambda *args, **kwargs: None):
                panel = ChatPanel()
                panel.mode_combo.setCurrentText('Siege')
                panel.model_combo.clear()
                panel.model_combo.addItem('scripted-agent', '[Test] scripted-agent')
                panel.model_combo.setCurrentIndex(0)
                panel.on_model_changed('scripted-agent')

                self.assertTrue(panel.rag_client.ingest_message('user', f'Remember the {memory_query} for retrieval validation: {memory_payload}.', panel.conversation_id))
                self.assertTrue(panel.rag_client.ingest_message('user', f'Chat also mentions {file_marker} so code search must prioritize files.', panel.conversation_id))

                AIClient.configure_test_provider([
                    '<index_codebase path="." />',
                    lambda messages: (
                        f'<search_codebase query="{file_marker}" />'
                        if 'Successfully indexed codebase' in messages[-1]['content']
                        else 'Indexing did not succeed.'
                    ),
                    lambda messages: (
                        f'<search_memory query="{memory_query}" />'
                        if '--- Result 1 (File)' in messages[-1]['content'] and 'Location: app.py' in messages[-1]['content'] and file_marker in messages[-1]['content']
                        else 'Codebase search did not surface the indexed file first.'
                    ),
                    lambda messages: (
                        'I used the real local RAG pipeline to index the project, surfaced app.py first in code search, recalled the stored memory payload, and completed the offline regression successfully.'
                        if memory_payload in messages[-1]['content'] and 'LONG-TERM MEMORY ARCHIVE' in messages[-1]['content']
                        else 'Memory recall did not surface the stored payload.'
                    ),
                ])

                with patch.object(panel, 'save_conversation'):
                    panel.send_worker('Run an offline retrieval validation of this project.')
                    completed = self._wait_until_idle(panel, timeout=45.0)

            self.assertTrue(completed, 'Timed out waiting for the offline RAG agent flow to finish')
            system_messages = [m['content'] for m in panel.messages if m['role'] == 'system']
            self.assertTrue(any('Successfully indexed codebase' in m for m in system_messages))
            self.assertTrue(any('--- Result 1 (File)' in m and 'Location: app.py' in m and file_marker in m for m in system_messages))
            self.assertTrue(any(memory_payload in m and 'LONG-TERM MEMORY ARCHIVE' in m for m in system_messages))
            self.assertIn('offline regression successfully', panel.messages[-1]['content'])
            self.assertEqual(panel.tool_loop_count, 3)
        finally:
            if panel is not None:
                panel.close()
            set_project_root(old_root)
            RAGClient.shutdown_server()
            time.sleep(0.2)
            shutil.rmtree(project_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()

