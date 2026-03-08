import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(os.getcwd())

from core.rag_client import RAGClient, RetrievedChunk


class TestRAGClient(unittest.TestCase):
    def test_disabled_rag_short_circuits_retrieve_and_ingest(self):
        client = RAGClient()

        with patch.object(client.settings, 'get_rag_enabled', return_value=False), \
             patch.object(client.ai, 'embed_texts') as mock_embed:
            self.assertEqual(client.retrieve('find auth flow'), [])
            self.assertFalse(client.ingest_message('user', 'hello world', 'conv1'))
            self.assertFalse(client.ingest_document('app.py', 'print(1)', 1, 1))

        mock_embed.assert_not_called()

    def test_retrieve_uses_settings_top_k_and_min_score(self):
        client = RAGClient()
        response = {
            'chunks': [
                {'similarity': 0.40, 'chunk': {'id': 1, 'doc_id': 'file:ns:low.py:1-2', 'content': 'low'}},
                {'similarity': 0.91, 'chunk': {'id': 2, 'doc_id': 'file:ns:best.py:3-4', 'content': 'best'}},
                {'similarity': 0.72, 'chunk': {'id': 3, 'doc_id': 'chat:conv:msg1', 'content': 'mid'}},
            ]
        }

        with patch.object(client.settings, 'get_rag_enabled', return_value=True), \
             patch.object(client.settings, 'get_rag_top_k', return_value=2), \
             patch.object(client.settings, 'get_rag_min_score', return_value=0.5), \
             patch.object(client.ai, 'embed_texts', return_value=[[0.1, 0.2, 0.3]]), \
             patch.object(client, '_http_post', return_value=response), \
             patch.object(client, '_run_cli', return_value=None):
            chunks = client.retrieve('best match please')

        self.assertEqual([c.doc_id for c in chunks], ['file:ns:best.py:3-4', 'chat:conv:msg1'])
        self.assertTrue(all(c.score >= 0.5 for c in chunks))

    def test_format_context_block_uses_settings_limits(self):
        client = RAGClient()
        chunks = [
            RetrievedChunk(1, 'file:ns:alpha.py:1-2', 'A' * 60, 0.9),
            RetrievedChunk(2, 'file:ns:beta.py:3-4', 'B' * 60, 0.8),
        ]

        with patch.object(client.settings, 'get_rag_max_context', return_value=260), \
             patch.object(client.settings, 'get_rag_max_chunk', return_value=18):
            block = client.format_context_block(chunks)

        self.assertIn('...(truncated)', block)
        self.assertIn('alpha.py', block)
        self.assertNotIn('beta.py', block)
        self.assertIn('[END OF MEMORY ARCHIVE]', block)


if __name__ == '__main__':
    unittest.main()

