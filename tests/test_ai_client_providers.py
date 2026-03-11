
import sys
import os
import unittest
from unittest.mock import MagicMock, mock_open, patch
import requests

# Add project root to path
sys.path.append("a:/Github/VoxAI_IDE")

from core.ai_client import AIClient
from core.settings import SettingsManager

class TestAIClient(unittest.TestCase):
    def setUp(self):
        # Mock SettingsManager to return specific models/keys
        self.settings_mock = MagicMock()
        self.settings_mock.get_api_key.return_value = "dummy_key"
        self.settings_mock.get_show_unstable_models.return_value = False
        self.settings_mock.get_local_llm_url.return_value = "http://localhost:11434/v1"
        self.settings_mock.get_enabled_models.return_value = list(SettingsManager.DEFAULT_OPENROUTER_MODELS)
        self.selected_model = None
        self.health_state = {}

        def get_selected_model():
            if self.selected_model is not None:
                return self.selected_model
            return self.settings_mock.get_selected_model.return_value

        def set_selected_model(model):
            self.selected_model = model

        def get_openrouter_health_state():
            return dict(self.health_state)

        def set_openrouter_health_state(state):
            self.health_state.clear()
            self.health_state.update(state)

        self.settings_mock.get_selected_model.side_effect = get_selected_model
        self.settings_mock.set_selected_model.side_effect = set_selected_model
        self.settings_mock.get_openrouter_health_state.side_effect = get_openrouter_health_state
        self.settings_mock.set_openrouter_health_state.side_effect = set_openrouter_health_state
        
        # Patch SettingsManager in ai_client module
        self.patcher = patch('core.ai_client.SettingsManager', return_value=self.settings_mock)
        self.patcher.start()

    def tearDown(self):
        AIClient.clear_test_provider()
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

    def test_google_transient_503_retries_and_recovers(self):
        self.settings_mock.get_selected_model.return_value = "[Google Gemini] gemini-pro"
        client = AIClient()

        first_response = MagicMock()
        first_response.status_code = 503
        first_response.text = '{"error": {"message": "The model is overloaded due to high demand. Please try again later."}}'
        first_error = requests.exceptions.HTTPError("503 Server Error: Service Unavailable")
        first_error.response = first_response
        first_response.raise_for_status.side_effect = first_error

        second_response = MagicMock()
        second_response.raise_for_status.return_value = None
        second_response.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"content":"Recovered reply"}}]}',
            b'data: [DONE]',
        ]

        first_ctx = MagicMock()
        first_ctx.__enter__.return_value = first_response
        first_ctx.__exit__.return_value = False
        second_ctx = MagicMock()
        second_ctx.__enter__.return_value = second_response
        second_ctx.__exit__.return_value = False

        with patch('core.ai_client.requests.post', side_effect=[first_ctx, second_ctx]) as mock_post, \
             patch('core.ai_client.time.sleep') as mock_sleep:
            chunks = list(client.stream_chat([{"role": "user", "content": "Say hello"}]))

        self.assertEqual("".join(chunks), "Recovered reply")
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once_with(1.0)

    def test_quarantined_model_routes_are_blocked_by_availability_checks(self):
        info = AIClient.get_model_availability("[Google Gemini] gemini-pro-latest", self.settings_mock)
        self.assertEqual(info["status"], "quarantined")
        self.assertFalse(info["send_allowed"])
        self.assertFalse(info["visible_by_default"])

    def test_prepare_model_for_request_switches_away_from_quarantined_route(self):
        self.settings_mock.get_enabled_models.return_value = [
            "[Google Gemini] gemini-pro-latest",
            SettingsManager.DEFAULT_BENCHMARK_MODEL,
        ]

        plan = AIClient.prepare_model_for_request("[Google Gemini] gemini-pro-latest", self.settings_mock, run_probe=False)

        self.assertEqual(plan["effective_model"], SettingsManager.DEFAULT_BENCHMARK_MODEL)
        self.assertIsNone(plan["blocked_reason"])
        self.assertIn("Switched", plan["note"])
        self.settings_mock.set_selected_model.assert_called_with(SettingsManager.DEFAULT_BENCHMARK_MODEL)

    def test_missing_api_key_models_are_hidden_by_default(self):
        self.settings_mock.get_api_key.side_effect = lambda provider: "" if provider == "anthropic" else "dummy_key"

        info = AIClient.get_model_picker_entry("[Anthropic] claude-3", self.settings_mock)

        self.assertEqual(info["status"], "missing_api_key")
        self.assertFalse(info["show_in_picker"])
        self.assertIn("🔑", info["label"])

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

    def test_scripted_test_provider_streams_deterministic_output(self):
        self.settings_mock.get_selected_model.return_value = "[Test] scripted-agent"
        AIClient.configure_test_provider([
            ["<list_files path=\".\" />", "\nDone"],
        ])

        client = AIClient()
        chunks = list(client.stream_chat([{"role": "user", "content": "inspect project"}]))

        self.assertEqual(client.provider, "test")
        self.assertEqual("".join(chunks), "<list_files path=\".\" />\nDone")
        transcript = AIClient.get_test_transcript()
        self.assertEqual(transcript[0][-1]["content"], "inspect project")

    def test_test_provider_loads_script_steps_from_file(self):
        self.settings_mock.get_selected_model.return_value = "[Test] scripted-agent"
        self.settings_mock.get_test_provider_script_abspath.return_value = "A:/fake/.vox/test_provider_script.json"
        client = AIClient()

        with patch('core.ai_client.os.path.exists', return_value=True), \
             patch('builtins.open', mock_open(read_data='["step one", "step two"]')):
            first = "".join(client.stream_chat([{"role": "user", "content": "one"}]))
            second = "".join(client.stream_chat([{"role": "user", "content": "two"}]))

        self.assertEqual(first, "step one")
        self.assertEqual(second, "step two")

    def test_auto_select_openrouter_uses_recent_healthy_model(self):
        self.settings_mock.get_selected_model.return_value = "[OpenRouter] qwen/qwen3-coder:free"
        self.health_state.update({
            "z-ai/glm-4.5-air:free": {
                "status": "healthy",
                "last_success_at": 9999999999,
                "score": 8,
            }
        })

        selected, note = AIClient.auto_select_openrouter_model(self.settings_mock, run_probe=False)

        self.assertEqual(selected, "[OpenRouter] z-ai/glm-4.5-air:free")
        self.assertIn("healthier model", note)
        self.settings_mock.set_selected_model.assert_called_with("[OpenRouter] z-ai/glm-4.5-air:free")

    def test_auto_select_openrouter_probes_until_success(self):
        self.settings_mock.get_selected_model.return_value = "[OpenRouter] qwen/qwen3-coder:free"

        with patch.object(AIClient, '_probe_openrouter_model', side_effect=[
            (False, "rate limited"),
            (True, ""),
        ]) as mock_probe:
            selected, note = AIClient.auto_select_openrouter_model(self.settings_mock, run_probe=True)

        self.assertEqual(selected, "[OpenRouter] z-ai/glm-4.5-air:free")
        self.assertIn("auto-selected healthier model", note)
        self.assertEqual(mock_probe.call_count, 2)
        self.settings_mock.set_selected_model.assert_called_with("[OpenRouter] z-ai/glm-4.5-air:free")

    def test_background_refresh_requires_openrouter_key_and_models(self):
        self.settings_mock.get_api_key.return_value = ""
        self.assertFalse(AIClient.should_background_refresh(self.settings_mock))

        self.settings_mock.get_api_key.return_value = "dummy_key"
        self.settings_mock.get_enabled_models.return_value = ["[OpenAI] gpt-4"]
        self.assertFalse(AIClient.should_background_refresh(self.settings_mock))

        self.settings_mock.get_enabled_models.return_value = list(SettingsManager.DEFAULT_OPENROUTER_MODELS)
        self.assertTrue(AIClient.should_background_refresh(self.settings_mock))

    def test_background_refresh_updates_health_cache_and_recommendation(self):
        self.settings_mock.get_selected_model.return_value = "[OpenRouter] qwen/qwen3-coder:free"

        def fake_probe(self_client, model_id):
            if model_id == "qwen/qwen3-coder:free":
                self_client._record_openrouter_health(
                    model_id,
                    success=False,
                    status_label="rate_limited",
                    message="OpenRouter rate limit reached",
                    source="probe",
                )
                return False, "OpenRouter rate limit reached"

            self_client._record_openrouter_health(model_id, success=True, source="probe")
            return True, ""

        with patch.object(AIClient, '_probe_openrouter_model', autospec=True, side_effect=fake_probe) as mock_probe:
            summary = AIClient.refresh_openrouter_health(self.settings_mock, max_probes=2)

        self.assertEqual(mock_probe.call_count, 2)
        self.assertEqual(summary["recommended_model"], "z-ai/glm-4.5-air:free")
        self.assertIn("qwen/qwen3-coder:free", summary["probed_models"])
        self.assertEqual(self.health_state["z-ai/glm-4.5-air:free"]["status"], "healthy")
        self.assertEqual(self.health_state["qwen/qwen3-coder:free"]["status"], "rate_limited")

    def test_get_openrouter_health_indicator_summarizes_best_model(self):
        self.settings_mock.get_selected_model.return_value = "[OpenRouter] qwen/qwen3-coder:free"
        self.health_state.update({
            "z-ai/glm-4.5-air:free": {
                "status": "healthy",
                "last_success_at": 9999999999,
                "score": 6,
            }
        })

        indicator = AIClient.get_openrouter_health_indicator(self.settings_mock)

        self.assertTrue(indicator["configured"])
        self.assertEqual(indicator["status"], "healthy")
        self.assertEqual(indicator["recommended_model"], "z-ai/glm-4.5-air:free")
        self.assertIn("OpenRouter ready", indicator["message"])

    @patch('core.ai_client.requests.post')
    def test_openrouter_rate_limit_error_is_actionable(self, mock_post):
        self.settings_mock.get_selected_model.return_value = "[OpenRouter] z-ai/glm-4.5-air:free"
        client = AIClient()

        response = MagicMock()
        response.status_code = 429
        response.json.return_value = {"error": {"message": "Rate limit exceeded for free tier"}}
        response.text = '{"error":{"message":"Rate limit exceeded for free tier"}}'
        http_error = requests.exceptions.HTTPError("429 Client Error", response=response)
        response.raise_for_status.side_effect = http_error

        context_response = MagicMock()
        context_response.__enter__.return_value = response
        context_response.__exit__.return_value = False
        mock_post.return_value = context_response

        with patch.object(client, '_openrouter_candidate_models', return_value=[client.model]):
            chunks = list(client.stream_chat([{"role": "user", "content": "hi"}]))
        joined = "".join(chunks)

        self.assertIn("OpenRouter rate limit reached", joined)
        self.assertIn("try another free model", joined)
        self.assertIn("Rate limit exceeded for free tier", joined)

    @patch('core.ai_client.requests.post')
    def test_openrouter_privacy_policy_error_is_actionable(self, mock_post):
        self.settings_mock.get_selected_model.return_value = "[OpenRouter] openai/gpt-oss-20b:free"
        client = AIClient()

        response = MagicMock()
        response.status_code = 404
        response.json.return_value = {
            "error": {"message": "No endpoints found matching your data policy (Free model publication)"}
        }
        response.text = '{"error":{"message":"No endpoints found matching your data policy (Free model publication)"}}'
        http_error = requests.exceptions.HTTPError("404 Client Error", response=response)
        response.raise_for_status.side_effect = http_error

        context_response = MagicMock()
        context_response.__enter__.return_value = response
        context_response.__exit__.return_value = False
        mock_post.return_value = context_response

        with patch.object(client, '_openrouter_candidate_models', return_value=[client.model]):
            chunks = list(client.stream_chat([{"role": "user", "content": "hi"}]))
        joined = "".join(chunks)

        self.assertIn("privacy settings", joined)
        self.assertIn("settings/privacy", joined)
        self.assertIn("data policy", joined)

    @patch('core.ai_client.requests.post')
    def test_openrouter_falls_back_to_next_free_model(self, mock_post):
        self.settings_mock.get_selected_model.return_value = "[OpenRouter] qwen/qwen3-coder:free"
        client = AIClient()

        first = MagicMock()
        first.status_code = 429
        first.json.return_value = {"error": {"message": "Rate limit exceeded for free tier"}}
        first.text = '{"error":{"message":"Rate limit exceeded for free tier"}}'
        first.raise_for_status.side_effect = requests.exceptions.HTTPError("429 Client Error", response=first)

        second = MagicMock()
        second.raise_for_status.return_value = None
        second.iter_lines.return_value = [
            b'data: {"choices":[{"delta":{"content":"Recovered reply"}}]}',
            b'data: [DONE]'
        ]

        ctx1 = MagicMock()
        ctx1.__enter__.return_value = first
        ctx1.__exit__.return_value = False
        ctx2 = MagicMock()
        ctx2.__enter__.return_value = second
        ctx2.__exit__.return_value = False
        mock_post.side_effect = [ctx1, ctx2]

        with patch.object(client, '_openrouter_candidate_models', return_value=[
            'qwen/qwen3-coder:free',
            'z-ai/glm-4.5-air:free',
        ]):
            chunks = list(client.stream_chat([{"role": "user", "content": "hi"}]))

        joined = "".join(chunks)
        self.assertIn("OpenRouter fallback", joined)
        self.assertIn("z-ai/glm-4.5-air:free", joined)
        self.assertIn("Recovered reply", joined)
        self.assertEqual(mock_post.call_count, 2)
        self.settings_mock.set_selected_model.assert_called_with("[OpenRouter] z-ai/glm-4.5-air:free")

    @patch('core.ai_client.requests.post')
    def test_openrouter_reports_all_failed_fallback_attempts(self, mock_post):
        self.settings_mock.get_selected_model.return_value = "[OpenRouter] qwen/qwen3-coder:free"
        client = AIClient()

        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.json.return_value = {"error": {"message": "Rate limit exceeded for free tier"}}
        rate_limited.text = '{"error":{"message":"Rate limit exceeded for free tier"}}'
        rate_limited.raise_for_status.side_effect = requests.exceptions.HTTPError("429 Client Error", response=rate_limited)

        blocked = MagicMock()
        blocked.status_code = 404
        blocked.json.return_value = {
            "error": {"message": "No endpoints found matching your data policy (Free model publication)"}
        }
        blocked.text = '{"error":{"message":"No endpoints found matching your data policy (Free model publication)"}}'
        blocked.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Client Error", response=blocked)

        ctx1 = MagicMock()
        ctx1.__enter__.return_value = rate_limited
        ctx1.__exit__.return_value = False
        ctx2 = MagicMock()
        ctx2.__enter__.return_value = blocked
        ctx2.__exit__.return_value = False
        mock_post.side_effect = [ctx1, ctx2]

        with patch.object(client, '_openrouter_candidate_models', return_value=[
            'qwen/qwen3-coder:free',
            'openai/gpt-oss-20b:free',
        ]):
            chunks = list(client.stream_chat([{"role": "user", "content": "hi"}]))

        joined = "".join(chunks)
        self.assertIn("OpenRouter fallback exhausted 2 model attempt", joined)
        self.assertIn("qwen/qwen3-coder:free", joined)
        self.assertIn("openai/gpt-oss-20b:free", joined)

if __name__ == '__main__':
    unittest.main()
