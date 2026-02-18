import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Mock core.settings to avoid PySide6 dependency issues during test if needed
sys.modules["core.settings"] = MagicMock()

# Now import AIClient
# We need to make sure the import works even if we mocked settings
# The file core/ai_client.py does "from core.settings import SettingsManager"
# Our mock should handle that.

# Adjust path to find core
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ai_client import AIClient

class TestFetchModels(unittest.TestCase):
    
    @patch('core.ai_client.requests.get')
    def test_fetch_openai_models(self, mock_get):
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "gpt-4"},
                {"id": "gpt-3.5-turbo"}
            ]
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        # Test
        models = AIClient.fetch_models("openai", "fake-key")
        
        # Verify
        self.assertIn("gpt-4", models)
        self.assertIn("gpt-3.5-turbo", models)
        # Check URL construction using replacement logic
        # OpenAI base: https://api.openai.com/v1/chat/completions -> https://api.openai.com/v1/models
        # Note: requests.get doesn't require Content-Type for GET
        mock_get.assert_called_with(
            "https://api.openai.com/v1/models", 
            headers={'Authorization': 'Bearer fake-key'}, 
            timeout=10
        )

    @patch('core.ai_client.requests.get')
    def test_fetch_openrouter_models(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "anthropic/claude-3"},
                {"id": "openai/gpt-4o"}
            ]
        }
        mock_get.return_value = mock_response
        
        models = AIClient.fetch_models("openrouter", "fake-key")
        
        self.assertIn("anthropic/claude-3", models)
        # Check URL: https://openrouter.ai/api/v1/chat/completions -> https://openrouter.ai/api/v1/models
        mock_get.assert_called_with(
            "https://openrouter.ai/api/v1/models",
            headers={'Authorization': 'Bearer fake-key'}, # Note: header name is actually Authorization for OpenRouter in config
            timeout=10
        )

    @patch('core.ai_client.requests.get')
    def test_fetch_local_ollama_models(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3:latest"},
                {"name": "mistral:latest"}
            ]
        }
        mock_get.return_value = mock_response
        
        models = AIClient.fetch_models("local", None, "http://localhost:11434")
        
        self.assertIn("llama3:latest", models)
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], "http://localhost:11434/api/tags")
        self.assertEqual(kwargs['timeout'], 10)

    @patch('core.ai_client.requests.get')
    def test_fetch_local_v1_models(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "local-model-v1"}
            ]
        }
        mock_get.return_value = mock_response
        
        # Local url with v1
        # pass None/empty string for api_key, and url as 3rd arg
        models = AIClient.fetch_models("local", "", "http://localhost:1234/v1")
        
        self.assertIn("local-model-v1", models)
        # Check URL: http://localhost:1234/v1 -> http://localhost:1234/v1/models
        # This path uses the 'else' block so it sends headers={}
        mock_get.assert_called_with(
            "http://localhost:1234/v1/models",
            headers={},
            timeout=10
        )

    @patch('core.ai_client.requests.get')
    def test_fetch_models_http_error(self, mock_get):
        """Models fetch gracefully returns [] on HTTP errors."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("403 Forbidden")
        mock_get.return_value = mock_response

        models = AIClient.fetch_models("openai", "bad-key")
        self.assertEqual(models, [])

    @patch('core.ai_client.requests.get')
    def test_fetch_models_timeout(self, mock_get):
        """Models fetch gracefully returns [] on timeout."""
        import requests as req
        mock_get.side_effect = req.exceptions.Timeout("Connection timed out")

        models = AIClient.fetch_models("openai", "fake-key")
        self.assertEqual(models, [])

    @patch('core.ai_client.requests.get')
    def test_fetch_models_unknown_format(self, mock_get):
        """Unknown JSON shape returns [] without crashing."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"unexpected": "payload"}
        mock_get.return_value = mock_response

        models = AIClient.fetch_models("openai", "fake-key")
        self.assertEqual(models, [])

    def test_fetch_models_unknown_provider(self):
        """Unknown provider returns [] immediately."""
        models = AIClient.fetch_models("nonexistent_provider", "key")
        self.assertEqual(models, [])

    def test_fetch_models_local_file_returns_empty(self):
        """local_file provider has no base_url and should return [] safely."""
        models = AIClient.fetch_models("local_file", "key")
        self.assertEqual(models, [])


if __name__ == '__main__':
    unittest.main()
