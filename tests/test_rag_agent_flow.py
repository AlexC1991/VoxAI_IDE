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
from core.rag_client import RAGClient, RetrievedChunk
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

    def test_send_worker_keeps_rag_ingest_path_alive_when_advanced_tools_are_enabled(self):
        old_root = get_project_root()
        project_dir = tempfile.mkdtemp(prefix='vox_rag_agent_')
        panel = None
        try:
            set_project_root(project_dir)
            with patch.object(SettingsManager, 'get_rag_enabled', return_value=True), \
                 patch.object(SettingsManager, 'get_advanced_agent_tools_enabled', return_value=True), \
                 patch('ui.chat_panel.QTimer.singleShot', lambda *args, **kwargs: None):
                panel = ChatPanel()
            panel.settings_manager.get_rag_enabled = lambda: True
            panel.settings_manager.get_advanced_agent_tools_enabled = lambda: True
            panel.mode_combo.setCurrentText('Siege')
            panel.model_combo.clear()
            panel.model_combo.addItem('scripted-agent', '[Test] scripted-agent')
            panel.model_combo.setCurrentIndex(0)
            panel.on_model_changed('scripted-agent')

            with patch.object(panel.rag_client, 'ingest_message', return_value=True) as mock_ingest, \
                 patch.object(panel, '_start_ai_worker') as mock_start, \
                 patch.object(panel, 'save_conversation'):
                panel.send_worker('Run an offline retrieval validation of this project.')

            mock_ingest.assert_called_once_with(
                'user',
                'Run an offline retrieval validation of this project.',
                panel.conversation_id,
            )
            mock_start.assert_called_once_with('Run an offline retrieval validation of this project.', [])
        finally:
            if panel is not None:
                panel.close()
            set_project_root(old_root)
            RAGClient.shutdown_server()
            time.sleep(0.2)
            shutil.rmtree(project_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()

