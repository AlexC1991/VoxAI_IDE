
import sys
import unittest
from unittest.mock import MagicMock, patch, mock_open
import os

# Initialize paths
sys.path.append(os.getcwd())

from core.settings import SettingsManager
from core.ai_client import AIClient

class TestLocalLLM(unittest.TestCase):
    
    @patch("os.listdir")
    @patch("os.path.exists")
    def test_settings_detect_local_models(self, mock_exists, mock_listdir):
        # Setup mock FS
        mock_exists.return_value = True
        mock_listdir.return_value = ["my-local-model.gguf", "readme.txt"]
        
        settings = SettingsManager()
        
        # Patch QSettings inside the instance or just mock `get_enabled_models` behavior partly
        # Easier: just verify get_local_models works
        local_models = settings.get_local_models()
        self.assertIn("my-local-model.gguf", local_models)
        self.assertNotIn("readme.txt", local_models)

    @patch("core.ai_client.SettingsManager")
    @patch("os.path.exists")
    def test_ai_client_local_inference(self, mock_exists, MockSettings):
        # Setup mock exists
        mock_exists.return_value = True

        # Setup Settings to return our local model
        mock_settings_instance = MockSettings.return_value
        mock_settings_instance.get_selected_model.return_value = "[Local] test-model.gguf"
        mock_settings_instance.get_api_key.return_value = ""
        
        # Mock llama-cpp-python
        with patch.dict(sys.modules, {"llama_cpp": MagicMock()}):
            import llama_cpp
            mock_llama_instance = MagicMock()
            llama_cpp.Llama.return_value = mock_llama_instance
            
            # Mock stream response
            mock_chunk = {
                "choices": [{
                    "delta": {"content": "Hello world"}
                }]
            }
            mock_llama_instance.create_chat_completion.return_value = iter([mock_chunk])
            
            # Initialize Client
            client = AIClient()
            self.assertEqual(client.provider, "local_file")
            self.assertEqual(client.model, "test-model.gguf")
            
            # Run inference
            messages = [{"role": "user", "content": "Hi"}]
            response_generator = client.stream_chat(messages)
            response = list(response_generator)
            
            self.assertEqual(response, ["Hello world"])
            
            # Verify Llama was initialized with correct path
            # We strictly check if it was called, but constructing the absolute path in test is tricky due to __file__
            # Just ensure it was called
            llama_cpp.Llama.assert_called_once()
            _, kwargs = llama_cpp.Llama.call_args
            self.assertTrue(kwargs['model_path'].endswith("test-model.gguf"), "Model path should end with test-model.gguf")

if __name__ == '__main__':
    unittest.main()
