
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append("a:/Github/VoxAI_IDE")

from core.ai_client import AIClient
from core.settings import SettingsManager

class TestAIClient(unittest.TestCase):
    def setUp(self):
        # Mock SettingsManager to return specific models/keys
        self.settings_mock = MagicMock()
        self.settings_mock.get_api_key.return_value = "dummy_key"
        self.settings_mock.get_local_llm_url.return_value = "http://localhost:11434/v1"
        
        # Patch SettingsManager in ai_client module
        self.patcher = patch('core.ai_client.SettingsManager', return_value=self.settings_mock)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_openai_config(self):
        self.settings_mock.get_selected_model.return_value = "[OpenAI] gpt-4"
        client = AIClient()
        self.assertEqual(client.provider, "openai")
        self.assertEqual(client.model, "gpt-4")
        self.assertEqual(client._get_url(), "https://api.openai.com/v1/chat/completions")

    def test_anthropic_config(self):
        self.settings_mock.get_selected_model.return_value = "[Anthropic] claude-3"
        client = AIClient()
        self.assertEqual(client.provider, "anthropic")
        self.assertEqual(client.model, "claude-3")
        self.assertEqual(client._get_url(), "https://api.anthropic.com/v1/messages")

    def test_deepseek_config(self):
        self.settings_mock.get_selected_model.return_value = "[DeepSeek] deepseek-chat"
        client = AIClient()
        self.assertEqual(client.provider, "deepseek")
        self.assertEqual(client.model, "deepseek-chat")
        self.assertEqual(client._get_url(), "https://api.deepseek.com/chat/completions")
    
    def test_google_config(self):
        self.settings_mock.get_selected_model.return_value = "[Google Gemini] gemini-pro"
        client = AIClient()
        self.assertEqual(client.provider, "google")
        self.assertEqual(client.model, "gemini-pro")
        self.assertEqual(client._get_url(), "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")

    def test_openrouter_ui_format(self):
        # This mirrors the user's screenshot case
        self.settings_mock.get_selected_model.return_value = "[OpenRouter] google/gemini-2.0-flash-001"
        client = AIClient()
        self.assertEqual(client.provider, "openrouter")
        # Ensure the prefix is stripped but the internal slash remains
        self.assertEqual(client.model, "google/gemini-2.0-flash-001")
        self.assertEqual(client._get_url(), "https://openrouter.ai/api/v1/chat/completions")

    def test_local_config(self):
        self.settings_mock.get_selected_model.return_value = "[Local LLM (Ollama)] llama3"
        client = AIClient()
        self.assertEqual(client.provider, "local")
        self.assertEqual(client.model, "llama3")
        self.assertEqual(client._get_url(), "http://localhost:11434/v1/chat/completions")

    def test_raw_fallback(self):
        # Backward compatibility check
        self.settings_mock.get_selected_model.return_value = "mistral/mistral-large"
        client = AIClient()
        self.assertEqual(client.provider, "mistral")
        self.assertEqual(client.model, "mistral-large")

if __name__ == '__main__':
    unittest.main()
