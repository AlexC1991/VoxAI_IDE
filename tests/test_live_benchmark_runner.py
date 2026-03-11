import os
import sys
import time
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.append(os.getcwd())

from core.ai_client import AIClient
from core.live_benchmark_runner import DEFAULT_BENCHMARK_OUTPUT_DIR, default_scenarios, enabled_models, resolve_output_artifact_path, run_siege_benchmark, write_blank_project_fixture, write_navigation_fixture
from core.settings import SettingsManager


class TestLiveBenchmarkRunner(unittest.TestCase):
    def tearDown(self):
        AIClient.clear_test_provider()

    def test_default_scenarios_include_navigation_report(self):
        scenarios = default_scenarios()

        self.assertIn("blank_project_repair", scenarios)
        self.assertIn("navigation_report", scenarios)
        self.assertTrue(scenarios["navigation_report"].require_navigation)
        self.assertEqual(scenarios["navigation_report"].expected_changed_file, "benchmark_report.md")

    def test_write_navigation_fixture_creates_expected_files(self):
        with TemporaryDirectory() as tmpdir:
            write_navigation_fixture(tmpdir)

            self.assertTrue(os.path.exists(os.path.join(tmpdir, "src", "engine.py")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "core", "helpers.py")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "tests", "test_engine.py")))
            with open(os.path.join(tmpdir, "consumer.py"), "r", encoding="utf-8") as f:
                self.assertIn("Worker().run()", f.read())

    def test_write_blank_project_fixture_creates_buggy_app(self):
        with TemporaryDirectory() as tmpdir:
            write_blank_project_fixture(tmpdir)

            with open(os.path.join(tmpdir, "app.py"), "r", encoding="utf-8") as f:
                source = f.read()

            self.assertIn("message = greeting", source)
            self.assertIn("print(message)", source)

    def test_run_siege_benchmark_supports_scripted_test_provider(self):
        AIClient.configure_test_provider([
            '<execute_command command="python app.py" cwd="." />',
            '<edit_file path="app.py" start_line="1" end_line="2">message = "hello from maintained benchmark"\nprint(message)\n</edit_file>',
            '<execute_command command="python app.py" cwd="." />',
            '<read_file path="app.py" start_line="1" end_line="20" />',
            'I observed the runtime failure in app.py, fixed it, reran it successfully, and reread the final file.',
        ])

        results = run_siege_benchmark(["[Test] scripted-agent"], scenario_names=["blank_project_repair"], timeout_seconds=12.0)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["scenario"], "blank_project_repair")
        self.assertIn("app.py", results[0]["changed_files"])
        self.assertFalse(results[0]["timed_out"])

    def test_run_siege_benchmark_supplies_default_navigation_script_for_test_provider(self):
        results = run_siege_benchmark(["[Test] scripted-agent"], scenario_names=["navigation_report"], timeout_seconds=12.0)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["scenario"], "navigation_report")
        self.assertEqual(results[0]["failure_code"], "")
        self.assertIn("benchmark_report.md", results[0]["changed_files"])
        self.assertTrue(results[0]["navigation_used"])

    def test_enabled_models_skips_openrouter_models_under_active_cooldown(self):
        future = time.time() + 300
        with patch.object(SettingsManager, 'get_enabled_models', return_value=[
            '[OpenRouter] anthropic/claude-opus-4.6',
            '[OpenRouter] x-ai/grok-code-fast-1',
            '[Google Gemini] gemini-pro-latest',
        ]), patch.object(SettingsManager, 'get_openrouter_health_state', return_value={
            'anthropic/claude-opus-4.6': {
                'status': 'request_failed',
                'cooldown_until': future,
                'score': -4,
            },
        }):
            models = enabled_models()

        self.assertCountEqual(models, [
            '[OpenRouter] x-ai/grok-code-fast-1',
            '[Google Gemini] gemini-pro-latest',
        ])

    def test_live_benchmark_default_output_paths_use_artifacts_directory(self):
        json_path = resolve_output_artifact_path(None, "siege_benchmark_results.json")
        markdown_path = resolve_output_artifact_path(None, "siege_benchmark_results.md")

        self.assertEqual(json_path, os.path.join(DEFAULT_BENCHMARK_OUTPUT_DIR, "siege_benchmark_results.json"))
        self.assertEqual(markdown_path, os.path.join(DEFAULT_BENCHMARK_OUTPUT_DIR, "siege_benchmark_results.md"))


if __name__ == "__main__":
    unittest.main()