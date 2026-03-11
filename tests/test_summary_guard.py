import unittest

from core.summary_guard import SummaryGuard


class TestSummaryGuard(unittest.TestCase):
    def test_grounded_changed_files_extracts_exact_paths(self):
        tool_output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- edit_file: engine/logging_utils.py\n"
            "- core\\old_name.py -> core\\new_name.py\n"
            "Other successful actions:\n"
            "- execute_command: python -m py_compile engine/logging_utils.py\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]"
        )

        self.assertEqual(
            SummaryGuard.grounded_changed_files_from_summary(tool_output),
            ["engine/logging_utils.py", "core/old_name.py", "core/new_name.py"],
        )

    def test_summary_guard_flags_require_post_edit_validation_and_rescan(self):
        tool_output = (
            "ACTION_SUMMARY:\n"
            "Successful file changes:\n"
            "- edit_file: ui/chat_panel.py\n"
            "Other successful actions:\n"
            "- none\n"
            "Failed actions:\n"
            "- none\n"
        )
        action_log = [
            "Edited ui/chat_panel.py -> Done",
        ]

        self.assertEqual(
            SummaryGuard.summary_guard_flags(tool_output, action_log),
            {"no_validation", "no_post_edit_rescan"},
        )

    def test_safe_summary_guard_fallback_reports_grounded_state(self):
        text = SummaryGuard.safe_summary_guard_fallback(
            {"no_post_edit_validation", "no_post_edit_rescan"},
            ["ui/chat_panel.py"],
        )

        self.assertIn("ui/chat_panel.py", text)
        self.assertIn("not validated", text)
        self.assertIn("No fresh rescan", text)


if __name__ == '__main__':
    unittest.main()