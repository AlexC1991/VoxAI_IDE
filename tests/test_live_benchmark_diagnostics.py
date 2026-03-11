import unittest

from core.live_benchmark_diagnostics import finalize_result, format_markdown_matrix, new_trace, observe_response, observe_tool_batch


class TestLiveBenchmarkDiagnostics(unittest.TestCase):
    def test_classifies_provider_auth_failure(self):
        trace = new_trace("openrouter/openai/gpt-4o-mini")
        observe_response(trace, "[Error: 401 invalid api key]")

        result = finalize_result(
            trace,
            guided_stage=0,
            autonomy_unlocked=False,
            no_progress_cycles=0,
            changed_files=[],
            final="",
            grounded_completion=False,
        )

        self.assertEqual(result["failure_code"], "P1_PROVIDER_AUTH")
        self.assertEqual(result["furthest_stage_code"], "S1_VISIBLE_RESPONSE")

    def test_classifies_provider_busy_failure_from_503_message(self):
        trace = new_trace("[Google Gemini] gemini-pro-latest")
        observe_response(
            trace,
            "[Error: Google Gemini request temporarily unavailable for model 'gemini-pro-latest' (503). Provider said: The model is overloaded due to high demand. Please try again later.]",
        )

        result = finalize_result(
            trace,
            guided_stage=0,
            autonomy_unlocked=False,
            no_progress_cycles=0,
            changed_files=[],
            final="",
            grounded_completion=False,
        )

        self.assertEqual(result["failure_code"], "P2_PROVIDER_RATE_LIMIT")
        self.assertIn("temporarily unavailable", result["failure_note"])

    def test_classifies_blank_visible_response(self):
        trace = new_trace("openrouter/google/gemini-2.5-flash")

        result = finalize_result(
            trace,
            guided_stage=0,
            autonomy_unlocked=False,
            no_progress_cycles=0,
            changed_files=[],
            final="",
            grounded_completion=False,
        )

        self.assertEqual(result["failure_code"], "R1_BLANK_VISIBLE_RESPONSE")

    def test_classifies_guided_stall_without_edit(self):
        trace = new_trace("openrouter/openai/gpt-4o-mini")
        observe_response(trace, "I'll inspect likely project issues next.")

        result = finalize_result(
            trace,
            guided_stage=2,
            autonomy_unlocked=False,
            no_progress_cycles=0,
            changed_files=[],
            final="I'll inspect the repo for TODOs and likely issues.",
            grounded_completion=False,
        )

        self.assertEqual(result["failure_code"], "G2_STUCK_IN_GUIDED_STAGE")

    def test_classifies_raw_tool_protocol_final(self):
        trace = new_trace("openrouter/z-ai/glm-5")
        observe_response(trace, '<tool_call><read_file path="requirements.txt" /></tool_call>')

        result = finalize_result(
            trace,
            guided_stage=2,
            autonomy_unlocked=False,
            no_progress_cycles=0,
            changed_files=[],
            final='<tool_call><read_file path="requirements.txt" /></tool_call>',
            grounded_completion=False,
        )

        self.assertEqual(result["failure_code"], "T1_RAW_TOOL_PROTOCOL_FINAL")

    def test_classifies_blank_final_response(self):
        trace = new_trace("openrouter/google/gemini-2.5-flash")
        observe_response(trace, "I inspected the workspace.")

        result = finalize_result(
            trace,
            guided_stage=2,
            autonomy_unlocked=False,
            no_progress_cycles=0,
            changed_files=["requirements.base.txt"],
            final="[No response received from the model. The request completed without visible content. Please retry.]",
            grounded_completion=True,
        )

        self.assertEqual(result["failure_code"], "R2_BLANK_FINAL_RESPONSE")
        self.assertEqual(result["furthest_stage_code"], "S1_VISIBLE_RESPONSE")

    def test_classifies_validated_change_without_autonomy_unlock(self):
        trace = new_trace("openrouter/moonshotai/kimi-k2")
        observe_response(trace, "I found a specific issue.")
        observe_tool_batch(trace, [{"cmd": "edit_file", "args": {"path": "requirements.txt"}}], "siege")
        observe_tool_batch(trace, [{"cmd": "execute_command", "args": {"command": "python -m py_compile foo.py"}}], "siege")

        result = finalize_result(
            trace,
            guided_stage=2,
            autonomy_unlocked=False,
            no_progress_cycles=0,
            changed_files=["requirements.txt"],
            final="I updated requirements.txt and confirmed the validation command passed.",
            grounded_completion=True,
        )

        self.assertEqual(result["failure_code"], "U1_AUTONOMY_NOT_UNLOCKED_AFTER_VALIDATED_CHANGE")
        self.assertEqual(result["furthest_stage_code"], "S7_GROUNDED_COMPLETION")

    def test_classifies_validated_change_without_grounded_final(self):
        trace = new_trace("openrouter/x-ai/grok-code-fast-1")
        observe_response(trace, "I found a specific issue.")
        observe_tool_batch(trace, [{"cmd": "edit_file", "args": {"path": "ImageGen/image_generator.py"}}], "siege")
        observe_tool_batch(trace, [{"cmd": "execute_command", "args": {"command": "python -m py_compile ImageGen/image_generator.py"}}], "siege")

        result = finalize_result(
            trace,
            guided_stage=2,
            autonomy_unlocked=False,
            no_progress_cycles=0,
            changed_files=["ImageGen/image_generator.py"],
            final="Need one more check before I can confirm the fix.",
            grounded_completion=False,
        )

        self.assertEqual(result["failure_code"], "S2_NO_GROUNDED_FINAL_AFTER_VALIDATED_CHANGE")
        self.assertEqual(result["furthest_stage_code"], "S6_POST_EDIT_VALIDATION")

    def test_grounded_text_without_edit_cycle_does_not_reach_stage_seven(self):
        trace = new_trace("openrouter/openai/gpt-4o-mini")
        observe_response(trace, "I inspected likely files and here is a grounded summary.")

        result = finalize_result(
            trace,
            guided_stage=2,
            autonomy_unlocked=False,
            no_progress_cycles=0,
            changed_files=[],
            final="Based on the latest inspection, the likely issue is in app/main_gui.py.",
            grounded_completion=True,
        )

        self.assertFalse(result["grounded_completion_reached"])
        self.assertEqual(result["furthest_stage_code"], "S1_VISIBLE_RESPONSE")
        self.assertEqual(result["failure_code"], "G2_STUCK_IN_GUIDED_STAGE")

    def test_semantic_and_import_inspection_tools_count_as_targeted_progress_and_validation(self):
        trace = new_trace("openrouter/openai/gpt-4o-mini")
        observe_response(trace, "I found a concrete target and will inspect the affected symbol.")
        observe_tool_batch(trace, [{"cmd": "find_symbol", "args": {"symbol": "Worker.run"}}], "siege")
        observe_tool_batch(trace, [{"cmd": "edit_file", "args": {"path": "src/engine.py"}}], "siege")
        observe_tool_batch(trace, [{"cmd": "get_imports", "args": {"path": "src/engine.py"}}], "siege")

        result = finalize_result(
            trace,
            guided_stage=3,
            autonomy_unlocked=True,
            no_progress_cycles=0,
            changed_files=["src/engine.py"],
            final="Updated src/engine.py and rescanned its imports.",
            grounded_completion=True,
        )

        self.assertTrue(result["concrete_target_selected"])
        self.assertEqual(result["furthest_stage_code"], "S7_GROUNDED_COMPLETION")
        self.assertEqual(result["failure_code"], "")

    def test_formats_markdown_matrix(self):
        trace = new_trace("openrouter/x-ai/grok-code-fast-1")
        observe_response(trace, "I found a specific issue.")
        observe_tool_batch(trace, [{"cmd": "read_file", "args": {"path": "app/main_gui.py"}}], "siege")
        observe_tool_batch(trace, [{"cmd": "edit_file", "args": {"path": "app/main_gui.py"}}], "siege")
        observe_tool_batch(trace, [{"cmd": "execute_command", "args": {"command": "python -m py_compile app/main_gui.py"}}], "siege")
        result = finalize_result(
            trace,
            guided_stage=3,
            autonomy_unlocked=True,
            no_progress_cycles=0,
            changed_files=["app/main_gui.py"],
            final="Updated app/main_gui.py and verified it with py_compile.",
            grounded_completion=True,
        )

        table = format_markdown_matrix([result])

        self.assertIn("| openrouter/x-ai/grok-code-fast-1 | S7_GROUNDED_COMPLETION | PASS | 3 | yes | app/main_gui.py |", table)

    def test_formats_markdown_matrix_with_scenarios(self):
        table = format_markdown_matrix([
            {
                "scenario": "navigation_report",
                "model": "openrouter/x-ai/grok-code-fast-1",
                "furthest_stage_code": "S7_GROUNDED_COMPLETION",
                "failure_code": "",
                "guided_stage": 3,
                "guided_autonomy_unlocked": True,
                "changed_files": ["benchmark_report.md"],
                "failure_note": "",
                "final_excerpt": "Wrote the report after navigating definitions, importers, and tests.",
            }
        ])

        self.assertIn("| Scenario | Model | Furthest stage | Failure code | Guided | Auto | Changed files | Note |", table)
        self.assertIn("| navigation_report | openrouter/x-ai/grok-code-fast-1 | S7_GROUNDED_COMPLETION | PASS | 3 | yes | benchmark_report.md |", table)


if __name__ == "__main__":
    unittest.main()