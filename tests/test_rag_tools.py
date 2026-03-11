import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
sys.path.append(os.getcwd())

from core.rag_client import RetrievedChunk
from ui.chat_panel import ChatPanel, ToolWorker


class TestRAGTools(unittest.TestCase):
    def test_search_memory_skips_when_rag_disabled(self):
        worker = ToolWorker([{'cmd': 'search_memory', 'args': {'query': 'auth'}}], auto_approve=True)
        outputs = []
        worker.finished.connect(outputs.append)
        worker.settings.get_advanced_agent_tools_enabled = MagicMock(return_value=True)

        with patch.object(worker.settings, 'get_rag_enabled', return_value=False), \
             patch.object(worker.rag_client, 'retrieve') as mock_retrieve:
            worker.run()

        mock_retrieve.assert_not_called()
        self.assertIn('RAG memory search is disabled', outputs[0])

    def test_search_codebase_prioritizes_file_hits_and_respects_limits(self):
        worker = ToolWorker([{'cmd': 'search_codebase', 'args': {'query': 'needle'}}], auto_approve=True)
        outputs = []
        worker.finished.connect(outputs.append)
        worker.settings.get_advanced_agent_tools_enabled = MagicMock(return_value=True)
        chunks = [
            RetrievedChunk(1, 'chat:conv:msg1', 'chat memory about needle', 0.99),
            RetrievedChunk(2, 'file:ns:src/app.py:10-12', 'file one needle ' * 8, 0.70, 10, 12),
            RetrievedChunk(3, 'file:ns:src/lib.py:3-4', 'file two needle ' * 8, 0.60, 3, 4),
        ]

        with patch.object(worker.settings, 'get_rag_enabled', return_value=True), \
             patch.object(worker.settings, 'get_rag_top_k', return_value=2), \
             patch.object(worker.settings, 'get_rag_max_chunk', return_value=24), \
             patch.object(worker.rag_client, 'retrieve', return_value=chunks) as mock_retrieve:
            worker.run()

        mock_retrieve.assert_called_once_with('needle', k=22)
        self.assertIn('--- Result 1 (File)', outputs[0])
        self.assertIn('Location: src/app.py', outputs[0])
        self.assertNotIn('Chat Memory', outputs[0])
        self.assertIn('...(truncated)', outputs[0])

    def test_search_codebase_does_not_fallback_to_chat_memory(self):
        worker = ToolWorker([{'cmd': 'search_codebase', 'args': {'query': 'needle'}}], auto_approve=True)
        outputs = []
        worker.finished.connect(outputs.append)
        worker.settings.get_advanced_agent_tools_enabled = MagicMock(return_value=True)
        chunks = [RetrievedChunk(1, 'chat:conv:msg1', 'chat memory only', 0.99)]

        with patch.object(worker.settings, 'get_rag_enabled', return_value=True), \
             patch.object(worker.settings, 'get_rag_top_k', return_value=3), \
             patch.object(worker.settings, 'get_rag_max_chunk', return_value=80), \
             patch.object(worker.rag_client, 'retrieve', return_value=chunks):
            worker.run()

        self.assertIn("No relevant code found for 'needle'", outputs[0])
        self.assertNotIn('Chat Memory', outputs[0])

    def test_chatpanel_send_worker_skips_rag_ingest_when_disabled(self):
        with patch('ui.chat_panel.QTimer.singleShot', lambda *args, **kwargs: None):
            panel = ChatPanel()
        panel.settings_manager.get_rag_enabled = MagicMock(return_value=False)

        try:
            with patch.object(panel, '_start_ai_worker') as mock_start, \
                 patch.object(panel.rag_client, 'ingest_message') as mock_ingest:
                panel.send_worker('hello retrieval system')

            mock_start.assert_called_once_with('hello retrieval system', [])
            mock_ingest.assert_not_called()
        finally:
            panel.close()


if __name__ == '__main__':
    unittest.main()

