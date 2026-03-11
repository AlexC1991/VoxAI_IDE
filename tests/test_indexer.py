import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.append(os.getcwd())

from core.indexer import ProjectIndexer
from ui.chat_workers import IndexingWorker


class TestIndexer(unittest.TestCase):
    def test_index_project_honors_cancel_callback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "alpha.py"), "w", encoding="utf-8") as f:
                f.write("print('hello')\n")

            fake_rag = MagicMock()
            cancel_states = iter([False, False, True])

            with patch('core.indexer.RAGClient', return_value=fake_rag):
                indexer = ProjectIndexer()
                result = indexer.index_project(tmpdir, cancel_callback=lambda: next(cancel_states, True))

        self.assertFalse(result)
        fake_rag.ingest_document.assert_not_called()

    def test_indexing_worker_passes_interruptible_cancel_callback(self):
        fake_indexer = MagicMock()
        fake_indexer.index_project.return_value = True

        with patch('core.indexer.ProjectIndexer', return_value=fake_indexer):
            worker = IndexingWorker('.')

        with patch('ui.chat_workers.QThread.currentThread', return_value=SimpleNamespace(isInterruptionRequested=lambda: True)):
            worker.run()
            kwargs = fake_indexer.index_project.call_args.kwargs
            self.assertIn('cancel_callback', kwargs)
            self.assertTrue(callable(kwargs['cancel_callback']))
            self.assertTrue(kwargs['cancel_callback']())


if __name__ == '__main__':
    unittest.main()