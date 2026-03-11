import os
import subprocess
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.append(os.getcwd())

from core.ai_client import AIClient
from scripts.basic_project_start_benchmark import DEFAULT_OUTPUT_DIR, evaluate_run_outcome, last_user_ready_assistant_message, resolve_output_path, run_once, sanitize_model_slug


class TestBasicProjectStartBenchmark(unittest.TestCase):
    def tearDown(self):
        AIClient.clear_test_provider()

    def test_sanitize_model_slug_normalizes_provider_and_model(self):
        slug = sanitize_model_slug("[OpenRouter] google/gemini-3.1-pro-preview")

        self.assertEqual(slug, "openrouter_google_gemini_3_1_pro_preview")

    def test_resolve_output_path_defaults_to_benchmark_artifacts_dir(self):
        path = resolve_output_path(None, "[OpenAI] gpt-5.4")

        self.assertEqual(path, DEFAULT_OUTPUT_DIR / "basic_project_start_openai_gpt_5_4.json")

    def test_resolve_output_path_preserves_explicit_output(self):
        path = resolve_output_path("tmp/custom-output.json", "[OpenAI] gpt-5.4")

        self.assertEqual(path, Path("tmp/custom-output.json"))

    def test_script_help_runs_without_needing_manual_pythonpath(self):
        completed = subprocess.run(
            [sys.executable, "scripts/basic_project_start_benchmark.py", "--help"],
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertIn("--repetitions", completed.stdout)

    def test_script_sets_windows_font_fallback_for_headless_runs(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; import scripts.basic_project_start_benchmark as m; print(bool(os.environ.get('QT_QPA_FONTDIR')))",
            ],
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            timeout=30,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertIn("True", completed.stdout)

    def test_run_once_supports_scripted_test_provider_for_tiny_starter_flow(self):
        AIClient.configure_test_provider([
            '<write_file path="app.py">\nprint("Hello from benchmark")\n</write_file>\n'
            '<write_file path="README.md">\n# Tiny Starter\n\nRun `python app.py`.\n</write_file>\n'
            '<execute_command command="python app.py" cwd="." />\n'
            '<read_file path="README.md" start_line="1" end_line="20" />',
            'I created app.py and README.md, ran python app.py successfully, and verified the tiny starter.',
        ])

        result = run_once("[Test] scripted-agent")

        self.assertTrue(result["completed"])
        self.assertTrue(result["full_requested_success"])
        self.assertIn("app.py", result["files_created"])
        self.assertIn("README.md", result["files_created"])
        self.assertFalse(any(path.startswith(".vox/") for path in result["files_created"]))
        self.assertEqual(result["run_check"]["return_code"], 0)
        self.assertTrue(result["final_message_user_ready"])
        self.assertIsNone(result["quality_issue"])

    def test_last_user_ready_assistant_message_skips_raw_tool_protocol(self):
        messages = [
            {"role": "assistant", "content": "- Changed: app.py, README.md.\n- Verified: latest validation command succeeded."},
            {"role": "assistant", "content": '<read_file path="app.py" />'},
        ]

        final = last_user_ready_assistant_message(messages)

        self.assertIn("Changed:", final)

    def test_evaluate_run_outcome_marks_raw_tool_protocol_final_message_as_not_full_success(self):
        outcome = evaluate_run_outcome(
            True,
            ["app.py", "README.md"],
            {"return_code": 0, "stdout": "hello", "stderr": ""},
            [
                {"role": "assistant", "content": "- Changed: app.py, README.md.\n- Verified: latest validation command succeeded."},
                {"role": "assistant", "content": '<read_file path="app.py" />'},
            ],
        )

        self.assertFalse(outcome["full_requested_success"])
        self.assertFalse(outcome["final_message_user_ready"])
        self.assertEqual(outcome["quality_issue"], "non_user_ready_final_message")


if __name__ == "__main__":
    unittest.main()