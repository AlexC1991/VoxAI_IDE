
import os
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication.instance() or QApplication(sys.argv)
sys.path.append(os.getcwd())

from ui.chat_panel import ChatPanel
from core.ai_client import AIClient
from core.agent_tools import get_project_root, set_project_root


class TestCommandControl(unittest.TestCase):
    def _panel(self, project_root: str | None = None, auto_approve_writes: bool = False) -> ChatPanel:
        if project_root:
            set_project_root(project_root)
        with patch('ui.chat_panel.QTimer.singleShot', lambda *args, **kwargs: None):
            panel = ChatPanel()
        panel.settings_manager.get_auto_approve_writes = MagicMock(return_value=auto_approve_writes)
        panel.model_combo.clear()
        panel.model_combo.addItem("gpt-4", "[OpenAI] gpt-4")
        panel.model_combo.setCurrentIndex(0)
        return panel

    @contextmanager
    def _blank_project(self):
        old_root = get_project_root()
        with tempfile.TemporaryDirectory() as tmpdir:
            set_project_root(tmpdir)
            try:
                yield tmpdir.replace("\\", "/")
            finally:
                set_project_root(old_root)

    def tearDown(self):
        AIClient.clear_test_provider()

    def _wait_until(self, predicate, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            app.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        app.processEvents()
        return predicate()

    def _wait_until_idle(self, panel: ChatPanel, timeout=8.0):
        return self._wait_until(
            lambda: (
                not panel.is_processing
                and getattr(panel, 'ai_thread_obj', None) is None
                and getattr(panel, 'tool_thread', None) is None
            ),
            timeout=timeout,
        )

    @patch('ui.chat_panel.AIWorker')
    @patch('ui.chat_panel.QThread')
    def test_mode_prompts_match_new_loop_controls(self, MockThread, MockWorker):
        panel = self._panel()

        panel.mode_combo.setCurrentText("Phased")
        panel._start_ai_worker("Inspect this repo for real issues")
        phased_history = MockWorker.call_args.args[0]
        phased_prompt = next(
            msg['content'] for msg in phased_history
            if msg['role'] == 'system' and "MODE 1 (PHASED STRATEGIC ALIGNMENT)" in str(msg['content'])
        )
        guided_prompt = next(
            msg['content'] for msg in phased_history
            if msg['role'] == 'system' and "GUIDED TAKEOFF — STAGE 1" in str(msg['content'])
        )
        tool_coach = next(
            msg['content'] for msg in phased_history
            if msg['role'] == 'system' and "TOOL COACH / REALITY CHECK" in str(msg['content'])
        )
        self.assertIn("STOP after the summary", phased_prompt)
        self.assertIn("wait for the user", phased_prompt)
        self.assertIn("reply 'continue'", guided_prompt)
        self.assertIn("<read_file path=\"file.py\" />", tool_coach)
        self.assertIn("If the latest ACTION_SUMMARY says no successful file changes occurred", tool_coach)
        self.assertIn("a successful execute_command must happen AFTER that edit", tool_coach)
        self.assertIn("fresh read/search/list/structure/codebase-scan step must happen AFTER that edit", tool_coach)

        MockWorker.reset_mock()
        panel.mode_combo.setCurrentText("Phased")
        panel._phased_task_anchor = "Create app.py, observe failure, fix it, and verify the result."
        panel._guided_takeoff_stage = 2
        panel._start_ai_worker("continue. focus the best-supported issue")
        continue_history = MockWorker.call_args.args[0]
        continue_prompt = next(
            msg['content'] for msg in continue_history
            if msg['role'] == 'system' and "PHASED CONTINUE DIRECTIVE" in str(msg['content'])
        )
        guided_continue_prompt = next(
            msg['content'] for msg in continue_history
            if msg['role'] == 'system' and "GUIDED TAKEOFF — STAGE 2" in str(msg['content'])
        )
        anchor_prompt = next(
            msg['content'] for msg in continue_history
            if msg['role'] == 'system' and "CURRENT PHASED TASK ANCHOR" in str(msg['content'])
        )
        self.assertIn("emit the tool call(s) FIRST", continue_prompt)
        self.assertIn("fresh [TOOL_RESULT] from THIS phase", continue_prompt)
        self.assertIn("single highest-confidence issue", guided_continue_prompt)
        self.assertIn("Create app.py, observe failure, fix it, and verify the result.", anchor_prompt)

        MockWorker.reset_mock()
        panel.mode_combo.setCurrentText("Siege")
        panel._start_ai_worker("Test siege")
        siege_history = MockWorker.call_args.args[0]
        siege_prompt = next(
            msg['content'] for msg in siege_history
            if msg['role'] == 'system' and "MODE 2 (SIEGE MODE / FULL AUTO)" in str(msg['content'])
        )
        self.assertIn("AUTONOMY WITH LOOP GUARDS", siege_prompt)
        self.assertIn("Never repeat the exact same tool call", siege_prompt)
        self.assertIn("ACTION_SUMMARY", siege_prompt)

    @patch('ui.chat_panel.AIWorker')
    @patch('ui.chat_panel.QThread')
    def test_image_attachment_persists_across_followup_turns_and_regenerate(self, MockThread, MockWorker):
        panel = self._panel()
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = os.path.join(tmpdir, 'sample.png')
            with open(image_path, 'wb') as f:
                f.write(b'not-a-real-png-but-good-enough-for-base64')

            with patch.object(panel.rag_client, 'ingest_message'):
                panel.add_attachment(image_path)
                panel.input_field.setPlainText('Inspect this image')
                panel.send_message()

            first_history = MockWorker.call_args.args[0]
            first_user = next(m for m in reversed(first_history) if m['role'] == 'user')
            self.assertIsInstance(first_user['content'], list)
            self.assertEqual(first_user['content'][0]['type'], 'text')
            self.assertEqual(first_user['content'][1]['type'], 'image_url')

            MockWorker.reset_mock()
            panel.is_processing = False
            panel._start_ai_worker()
            followup_history = MockWorker.call_args.args[0]
            followup_user = next(m for m in reversed(followup_history) if m['role'] == 'user')
            self.assertIsInstance(followup_user['content'], list)
            self.assertEqual(followup_user['content'][1]['type'], 'image_url')

            MockWorker.reset_mock()
            panel.is_processing = False
            panel._regenerate_last()
            regen_history = MockWorker.call_args.args[0]
            regen_user = next(m for m in reversed(regen_history) if m['role'] == 'user')
            self.assertIsInstance(regen_user['content'], list)
            self.assertEqual(regen_user['content'][1]['type'], 'image_url')

    def test_stopped_partial_response_does_not_restart_tools(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Phased")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "<list_files path=\".\" />"
        panel._stop_requested = True

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'):
            panel.handle_ai_finished()

        mock_tools.assert_not_called()
        self.assertEqual(panel.messages, [])

    def test_handle_tool_finished_uses_system_role_and_honors_stop(self):
        panel = self._panel()
        panel.messages = []
        panel._tool_calls_for_run = ["list_files"]
        panel._tool_action_log = ["Listed -> Done"]
        panel._stop_requested = True

        with patch.object(panel, 'append_message_widget') as mock_append, \
             patch.object(panel, '_start_ai_worker') as mock_restart:
            panel.handle_tool_finished("[Interrupted] Tool execution stopped by user.")

        mock_restart.assert_not_called()
        mock_append.assert_called_once()
        self.assertEqual(panel.messages[-1]["role"], "system")
        self.assertIn("[TOOL_RESULT]", panel.messages[-1]["content"])

    def test_handle_tool_finished_injects_no_change_reality_check_before_summary(self):
        panel = self._panel()
        panel.messages = []
        panel._tool_calls_for_run = ["read_file"]
        panel._tool_action_log = ["Read file -> Done"]

        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- none\n"
            "Other successful actions:\n"
            "- read_file app.py\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]\n"
            "Read file: app.py"
        )

        with patch.object(panel, 'append_message_widget'), \
             patch.object(panel, '_start_ai_worker') as mock_restart:
            panel.handle_tool_finished(output)

        extra_msgs = mock_restart.call_args.kwargs.get('extra_system_messages')
        self.assertIsNotNone(extra_msgs)
        combined = "\n".join(extra_msgs)
        self.assertIn("did NOT produce any successful file changes", combined)

    def test_handle_tool_finished_skips_no_change_warning_when_file_changed(self):
        panel = self._panel()
        panel.messages = []
        panel._tool_calls_for_run = ["write_file"]
        panel._tool_action_log = ["Wrote file -> Done"]

        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- write_file app.py\n"
            "Other successful actions:\n"
            "- none\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]\n"
            "Wrote file: app.py"
        )

        with patch.object(panel, 'append_message_widget'), \
             patch.object(panel, '_start_ai_worker') as mock_restart:
            panel.handle_tool_finished(output)

        extra_msgs = mock_restart.call_args.kwargs.get('extra_system_messages')
        self.assertIsNotNone(extra_msgs)
        combined = "\n".join(extra_msgs)
        self.assertIn("did NOT run any successful validation command", combined)
        self.assertIn("did NOT perform a fresh rescan/inspection AFTER the latest successful edit", combined)

    def test_handle_tool_finished_warns_when_validation_happened_before_latest_edit(self):
        panel = self._panel()
        panel.messages = []
        panel._tool_calls_for_run = ["execute_command", "write_file"]
        panel._tool_action_log = [
            "Executed: pytest -q -> Done",
            "Wrote main.py (modified) -> Done",
        ]

        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- write_file main.py\n"
            "Other successful actions:\n"
            "- execute_command: pytest -q\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]\n"
            "Command Output:\nall good"
        )

        with patch.object(panel, 'append_message_widget'), \
             patch.object(panel, '_start_ai_worker') as mock_restart:
            panel.handle_tool_finished(output)

        extra_msgs = mock_restart.call_args.kwargs.get('extra_system_messages')
        self.assertIsNotNone(extra_msgs)
        combined = "\n".join(extra_msgs)
        self.assertIn("no successful validation AFTER the latest successful edit", combined)
        self.assertIn("did NOT perform a fresh rescan/inspection AFTER the latest successful edit", combined)

    def test_handle_tool_finished_warns_when_rescan_missing_after_edit(self):
        panel = self._panel()
        panel.messages = []
        panel._tool_calls_for_run = ["write_file", "execute_command"]
        panel._tool_action_log = [
            "Wrote main.py (modified) -> Done",
            "Executed: pytest -q -> Done",
        ]

        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- write_file main.py\n"
            "Other successful actions:\n"
            "- execute_command: pytest -q\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]\n"
            "Command Output:\nall good"
        )

        with patch.object(panel, 'append_message_widget'), \
             patch.object(panel, '_start_ai_worker') as mock_restart:
            panel.handle_tool_finished(output)

        extra_msgs = mock_restart.call_args.kwargs.get('extra_system_messages')
        self.assertIsNotNone(extra_msgs)
        combined = "\n".join(extra_msgs)
        self.assertNotIn("no successful validation AFTER the latest successful edit", combined)
        self.assertIn("did NOT perform a fresh rescan/inspection AFTER the latest successful edit", combined)

    def test_handle_tool_finished_skips_post_edit_warnings_when_edit_then_rescan_then_validate(self):
        panel = self._panel()
        panel.messages = []
        panel._tool_calls_for_run = ["write_file", "read_file", "execute_command"]
        panel._tool_action_log = [
            "Wrote main.py (modified) -> Done",
            "Read file: main.py -> Done",
            "Executed: pytest -q -> Done",
        ]

        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- write_file main.py\n"
            "Other successful actions:\n"
            "- execute_command: pytest -q\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]\n"
            "Command Output:\nall good"
        )

        with patch.object(panel, 'append_message_widget'), \
             patch.object(panel, '_start_ai_worker') as mock_restart:
            panel.handle_tool_finished(output)

        self.assertIsNone(mock_restart.call_args.kwargs.get('extra_system_messages'))

    def test_phased_summary_pause_queues_followup_tool_batch(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Phased")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "<list_files path=\".\" />"
        panel._phased_summary_pending = True
        panel._guided_takeoff_stage = 2

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget') as mock_append:
            panel.handle_ai_finished()

        mock_tools.assert_not_called()
        mock_append.assert_called_once()
        self.assertFalse(panel._phased_summary_pending)
        self.assertEqual(panel._pending_phased_tools, [{"cmd": "list_files", "args": {"path": "."}}])

    def test_phased_continue_executes_queued_tool_batch_before_new_ai_turn(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Phased")
        panel._pending_phased_tools = [{"cmd": "list_files", "args": {"path": "tests"}}]
        panel._guided_takeoff_stage = 1

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_ai, \
             patch.object(panel.rag_client, 'ingest_message'):
            panel.send_worker("continue. take the next bounded step")

        mock_tools.assert_called_once_with([{"cmd": "list_files", "args": {"path": "tests"}}])
        mock_ai.assert_not_called()
        self.assertEqual(panel.messages[-1]["content"], "continue. take the next bounded step")
        self.assertEqual(panel._pending_phased_tools, [])
        self.assertEqual(panel._guided_takeoff_stage, 2)

    def test_phase_one_summary_gets_followup_and_advances_guidance(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Phased")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "What was done: inspected the repo. What was found: one likely bug. Assessment: high confidence. Next steps: fix it."
        panel._phased_summary_pending = True
        panel._guided_takeoff_stage = 1
        panel._guided_direct_change_requested = False

        with patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_ai_finished()

        self.assertIn("Follow-up for you", panel.messages[-1]["content"])
        self.assertIn("reply 'continue'", panel.messages[-1]["content"])
        self.assertEqual(panel._guided_takeoff_stage, 2)

    def test_guided_takeoff_trims_large_phase_one_tool_batch(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Phased")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            '<list_files path="." />\n'
            '<search_files query="TODO" file_pattern="*.py" />\n'
            '<read_file path="a.py" />\n'
            '<read_file path="b.py" />\n'
            '<get_file_structure path="c.py" />\n'
            '<search_codebase query="auth" />'
        )
        panel._guided_takeoff_stage = 1
        panel._guided_direct_change_requested = False

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_ai_finished()

        trimmed_tools = mock_tools.call_args.args[0]
        self.assertEqual(len(trimmed_tools), 5)
        self.assertEqual(trimmed_tools[0]["cmd"], "list_files")
        self.assertEqual(panel.messages[0]["role"], "assistant")
        self.assertEqual(panel.messages[1]["role"], "system")
        self.assertIn("Guided takeoff limited this phase", panel.messages[1]["content"])

    def test_guided_takeoff_rewrites_disallowed_phase_one_tool_batch(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Phased")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = '<write_file path="app.py">print(1)</write_file>'
        panel._guided_takeoff_stage = 1
        panel._guided_direct_change_requested = False

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        mock_restart.assert_called_once()
        self.assertIn("too aggressive for guided takeoff", mock_restart.call_args.args[0])

    def test_guided_takeoff_rewrites_phase_one_tool_response_into_pure_summary_request(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Phased")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = '<read_file path="engine/hardware_check.py" />'
        panel._phased_summary_pending = True
        panel._guided_takeoff_stage = 1
        panel._guided_direct_change_requested = False

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        self.assertEqual(panel._guided_phase_summary_retry_count, 1)
        mock_restart.assert_called_once()
        self.assertIn("Do not emit tool calls in this response", mock_restart.call_args.args[0])

    def test_guided_takeoff_phase_one_summary_fallback_after_retry(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Phased")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            '<read_file path="engine/hardware_check.py" />\n'
            'Grounded finding: the hardware path handling looks platform-fragile.'
        )
        panel._phased_summary_pending = True
        panel._guided_takeoff_stage = 1
        panel._guided_direct_change_requested = False
        panel._guided_phase_summary_retry_count = 1

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_ai_finished()

        mock_tools.assert_not_called()
        self.assertIn("Grounded finding", panel.messages[-1]["content"])
        self.assertIn("Follow-up for you", panel.messages[-1]["content"])
        self.assertEqual(panel._guided_takeoff_stage, 2)

    def test_kimi_stage_two_trims_tool_batch_more_aggressively(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.model_combo.clear()
        panel.model_combo.addItem("kimi", "[OpenRouter] moonshotai/kimi-k2")
        panel.model_combo.setCurrentIndex(0)
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            '<read_file path="a.py" />\n'
            '<read_file path="b.py" />\n'
            '<read_file path="c.py" />\n'
            '<search_files query="TODO" file_pattern="*.py" />\n'
            '<get_file_structure path="d.py" />'
        )
        panel._guided_takeoff_stage = 2
        panel._guided_direct_change_requested = False

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_ai_finished()

        trimmed_tools = mock_tools.call_args.args[0]
        self.assertEqual(len(trimmed_tools), 4)

    def test_kimi_decision_gate_rewrites_broad_investigation_after_no_progress(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.model_combo.clear()
        panel.model_combo.addItem("kimi", "[OpenRouter] moonshotai/kimi-k2")
        panel.model_combo.setCurrentIndex(0)
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            '<search_files query="CUDA" file_pattern="*.py" />\n'
            '<read_file path="engine/hardware_check.py" />'
        )
        panel._guided_takeoff_stage = 2
        panel._guided_no_progress_cycles = 2

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        self.assertEqual(panel._guided_decision_retry_count, 1)
        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — COMMIT OR STOP", combined)

    def test_decision_gate_falls_back_to_blocker_summary_after_retry(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.model_combo.clear()
        panel.model_combo.addItem("kimi", "[OpenRouter] moonshotai/kimi-k2")
        panel.model_combo.setCurrentIndex(0)
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            '<search_files query="CUDA" file_pattern="*.py" />\n'
            '<read_file path="engine/hardware_check.py" />'
        )
        panel._guided_takeoff_stage = 2
        panel._guided_no_progress_cycles = 2
        panel._guided_decision_retry_count = 1

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_ai_finished()

        mock_tools.assert_not_called()
        self.assertIn("paused here because the latest evidence still does not show a completed fix cycle", panel.messages[-1]["content"])
        self.assertIn("reply 'continue'", panel.messages[-1]["content"])

    def test_decision_gate_requires_validation_when_edit_already_exists(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = '<read_file path="engine/hardware_check.py" />'
        panel._guided_takeoff_stage = 2
        panel._pending_summary_guard_flags = {"no_post_edit_validation", "no_post_edit_rescan"}

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — FINISH THE CURRENT FIX CYCLE", combined)
        self.assertIn("validation/rescan", combined)

    def test_non_tool_decision_gate_rewrites_analysis_only_stage_two_reply(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "The real issue is in run.bat, but I have not changed any files yet."
        panel._guided_takeoff_stage = 2
        panel._pending_summary_guard_flags = {"no_file_changes", "no_validation"}

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — DO NOT STOP AT ANALYSIS", combined)

    def test_non_tool_decision_gate_requires_validation_after_edit(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I fixed the issue." 
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._pending_summary_guard_flags = {"no_post_edit_validation", "no_post_edit_rescan"}

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — DO NOT END BEFORE VALIDATION", combined)

    def test_malformed_tool_attempt_is_rewritten_before_summary(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            "Let me fix this now:\n\n"
            '<edit_file path="engine/model_manager.py" old_text="import os\n"'
        )
        panel._guided_takeoff_stage = 2

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        self.assertIn("malformed or partial tool syntax", mock_restart.call_args.args[0])

    def test_guided_recovery_escalates_after_repeated_investigation_only_cycles(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._guided_autonomy_unlocked = False
        panel._tool_calls_for_run = ["read_file", "search_files"]
        panel._tool_action_log = [
            "Read file: a.py -> Done",
            "Search files: TODO -> Done",
        ]
        panel._run_tool_action_log = list(panel._tool_action_log)
        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- none\n"
            "Other successful actions:\n"
            "- read a.py\n"
            "- search TODO\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]"
        )

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, 'append_message_widget'):
            panel.handle_tool_finished(output)
            first_msgs = mock_restart.call_args.kwargs.get('extra_system_messages') or []
            panel.handle_tool_finished(output)
            second_msgs = mock_restart.call_args.kwargs.get('extra_system_messages') or []

        self.assertIn("GUIDED RECOVERY — STAY NARROW", "\n".join(first_msgs))
        self.assertIn("GUIDED RECOVERY — STOP RE-INVESTIGATING", "\n".join(second_msgs))

    def test_guided_recovery_focuses_validation_after_successful_edit(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._guided_autonomy_unlocked = False
        panel._tool_calls_for_run = ["write_file"]
        panel._tool_action_log = ["Wrote app.py -> Done"]
        panel._run_tool_action_log = list(panel._tool_action_log)
        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- app.py\n"
            "Other successful actions:\n"
            "- none\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]"
        )

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, 'append_message_widget'):
            panel.handle_tool_finished(output)

        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED RECOVERY — FOCUS THE CURRENT FIX CYCLE", combined)
        self.assertIn("Validate the latest successful edit", combined)

    def test_guided_recovery_marks_noop_edit_targets_and_pushes_move_on(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._guided_autonomy_unlocked = False
        panel._tool_calls_for_run = ["edit_file"]
        panel._tool_specs_for_run = [{"cmd": "edit_file", "args": {"path": "engine/hardware_check.py"}}]
        panel._tool_action_log = ["Edited engine/hardware_check.py -> No changes needed"]
        panel._run_tool_action_log = list(panel._tool_action_log)
        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- none\n"
            "Other successful actions:\n"
            "- none\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]"
        )

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, 'append_message_widget'):
            panel.handle_tool_finished(output)

        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED RECOVERY — THE LAST EDIT WAS A NO-OP", combined)
        self.assertIn("engine/hardware_check.py", combined)
        self.assertEqual(panel._guided_noop_edit_targets, ["engine/hardware_check.py"])

    def test_grounded_fix_cycle_unlocks_guided_autonomy(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._guided_autonomy_unlocked = False
        panel._tool_calls_for_run = ["write_file", "execute_command", "read_file"]
        panel._tool_action_log = [
            "Wrote app.py -> Done",
            "Executed: python app.py -> Done",
            "Read file: app.py -> Done",
        ]
        panel._run_tool_action_log = list(panel._tool_action_log)

        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- app.py\n"
            "Other successful actions:\n"
            "- python app.py\n"
            "- read app.py\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]"
        )

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, 'append_message_widget'):
            panel.handle_tool_finished(output)

        self.assertTrue(panel._guided_autonomy_unlocked)
        self.assertEqual(panel._guided_takeoff_stage, 3)
        self.assertIsNone(mock_restart.call_args.kwargs.get('extra_system_messages'))

    def test_ai_provider_error_does_not_look_like_phase_completion(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Phased")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "[Error: AI Request Failed: 429]"
        panel._phased_summary_pending = True

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget') as mock_append:
            panel.handle_ai_finished()

        mock_tools.assert_not_called()
        mock_append.assert_not_called()
        self.assertFalse(panel._phased_summary_pending)

    def test_blank_final_response_is_replaced_with_retry_message(self):
        panel = self._panel()
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "   "
        panel._empty_ai_retry_count = 1

        with patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages[-1]["role"], "assistant")
        self.assertIn("No response received from the model", panel.messages[-1]["content"])
        panel.current_ai_item.set_text.assert_called()

    def test_blank_final_response_retries_once_before_fallback(self):
        panel = self._panel()
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "   "

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        mock_restart.assert_called_once()
        self.assertEqual(panel.messages, [])
        self.assertEqual(panel._empty_ai_retry_count, 1)

    def test_contradictory_summary_is_blocked_before_reaching_user(self):
        panel = self._panel()
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I fixed app.py, verified the fix, and performed a fresh rescan."
        panel._pending_summary_guard_flags = {"no_file_changes", "no_validation", "no_post_edit_rescan"}
        panel._pending_summary_guard_message = "REALITY CHECK BEFORE YOU RESPOND TO THE USER:\n- no changes"

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        mock_restart.assert_called_once()
        self.assertEqual(panel._summary_guard_retry_count, 1)
        extra_msgs = mock_restart.call_args.kwargs.get('extra_system_messages')
        self.assertEqual(extra_msgs, [panel._pending_summary_guard_message])

    def test_honest_no_change_summary_passes_summary_guard(self):
        panel = self._panel()
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "No files were changed in this phase. No successful validation or fresh rescan happened yet."
        panel._pending_summary_guard_flags = {"no_file_changes", "no_validation", "no_post_edit_rescan"}
        panel._pending_summary_guard_message = "REALITY CHECK BEFORE YOU RESPOND TO THE USER:\n- no changes"

        with patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, '_start_ai_worker') as mock_restart:
            panel.handle_ai_finished()

        mock_restart.assert_not_called()
        self.assertEqual(panel.messages[-1]["role"], "assistant")
        self.assertIn("No files were changed", panel.messages[-1]["content"])
        self.assertEqual(panel._pending_summary_guard_flags, set())

    def test_second_contradictory_summary_falls_back_to_safe_message(self):
        panel = self._panel()
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I fixed app.py and verified it."
        panel._pending_summary_guard_flags = {"no_file_changes", "no_validation"}
        panel._pending_summary_guard_message = "REALITY CHECK BEFORE YOU RESPOND TO THE USER:\n- no changes"
        panel._summary_guard_retry_count = 1

        with patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, '_start_ai_worker') as mock_restart:
            panel.handle_ai_finished()

        mock_restart.assert_not_called()
        self.assertIn("Summary corrected by IDE reality check", panel.messages[-1]["content"])
        self.assertIn("No files were successfully changed", panel.messages[-1]["content"])

    def test_openrouter_error_notification_is_clean_and_specific(self):
        title, message = ChatPanel._notification_for_ai_error(
            "[Error: OpenRouter blocked model 'openai/gpt-oss-20b:free' because your privacy settings do not allow this free-model route.\n"
            "Open https://openrouter.ai/settings/privacy and enable the required privacy/data-sharing setting, then retry.\n"
            "Provider said: No endpoints found matching your data policy (Free model publication)]"
        )

        self.assertEqual(title, "OpenRouter Privacy Setting Needed")
        self.assertIn("settings/privacy", message)
        self.assertNotIn("[Error:", message)

    def test_openrouter_fallback_exhausted_notification_title(self):
        title, message = ChatPanel._notification_for_ai_error(
            "[Error: OpenRouter fallback exhausted 3 model attempt(s) for the current request.\n"
            "Attempts:\n- a: OpenRouter rate limit reached\n- b: OpenRouter rate limit reached]"
        )

        self.assertEqual(title, "OpenRouter Fallback Exhausted")
        self.assertIn("fallback exhausted", message.lower())

    def test_handle_ai_model_selected_refreshes_combo_and_notifies(self):
        panel = self._panel()
        emitted = []
        panel.notification_requested.connect(lambda title, message: emitted.append((title, message)))

        with patch.object(panel.settings_manager, 'set_selected_model') as mock_set_selected, \
             patch.object(panel, 'refresh_models') as mock_refresh:
            panel._handle_ai_model_selected(
                "[OpenRouter] z-ai/glm-4.5-air:free",
                "OpenRouter preflight auto-selected healthier model 'z-ai/glm-4.5-air:free'.",
            )

        mock_set_selected.assert_called_once_with("[OpenRouter] z-ai/glm-4.5-air:free")
        mock_refresh.assert_called_once()
        self.assertEqual(emitted[0][0], "OpenRouter Preflight")

    def test_siege_mode_runs_full_agent_tool_cycle_with_scripted_provider(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.model_combo.clear()
        panel.model_combo.addItem("scripted-agent", "[Test] scripted-agent")
        panel.model_combo.setCurrentIndex(0)
        panel.on_model_changed("scripted-agent")

        AIClient.configure_test_provider([
            "<list_files path=\"tests\" />",
            "I listed the repository and completed the task.",
        ])

        notifications = []
        panel.notification_requested.connect(lambda title, message: notifications.append((title, message)))

        with patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'):
            panel.send_worker("Inspect the repo and finish.")
            completed = self._wait_until(lambda: not panel.is_processing)

        self.assertTrue(completed, "Timed out waiting for scripted agent run to finish")
        self.assertGreaterEqual(len(panel.messages), 4)
        self.assertEqual(panel.messages[0]["role"], "user")
        self.assertEqual(panel.messages[1]["role"], "assistant")
        self.assertIn("<list_files", panel.messages[1]["content"])
        self.assertEqual(panel.messages[2]["role"], "system")
        self.assertIn("[TOOL_RESULT]", panel.messages[2]["content"])
        self.assertEqual(panel.messages[-1]["role"], "assistant")
        self.assertIn("completed the task", panel.messages[-1]["content"])
        self.assertEqual(panel.tool_loop_count, 1)
        self.assertTrue(any(title == "AI Response Complete" for title, _ in notifications))
        transcript = AIClient.get_test_transcript()
        self.assertEqual(len(transcript), 2)
        self.assertIn("[TOOL_RESULT]", transcript[1][-1]["content"])

    def test_siege_mode_end_to_end_blank_project_failure_then_fix(self):
        with self._blank_project() as project_dir:
            self.assertEqual(os.listdir(project_dir), [])
            panel = self._panel(project_root=project_dir)
            panel.mode_combo.setCurrentText("Siege")
            panel.model_combo.clear()
            panel.model_combo.addItem("scripted-agent", "[Test] scripted-agent")
            panel.model_combo.setCurrentIndex(0)
            panel.on_model_changed("scripted-agent")

            app_file = f"{project_dir}/app.py"
            notifications = []
            panel.notification_requested.connect(lambda title, message: notifications.append((title, message)))

            AIClient.configure_test_provider([
                f'<write_file path="{app_file}">\nprint(message)\n</write_file>',
                lambda _messages: f'<execute_command command="python app.py" cwd="{project_dir}" />',
                lambda messages: (
                    f'<read_file path="{app_file}" start_line="1" end_line="40" />\n'
                    f'<write_file path="{app_file}">\nmessage = "hello from siege"\nprint(message)\n</write_file>'
                    if "NameError" in messages[-1]["content"] and "[Exit code: 1]" in messages[-1]["content"]
                    else "I did not receive the expected runtime failure to fix."
                ),
                lambda _messages: f'<execute_command command="python app.py" cwd="{project_dir}" />',
                lambda messages: (
                    "I created a blank project, observed the runtime failure, fixed it, reran it successfully, and the Siege flow completed cleanly."
                    if "hello from siege" in messages[-1]["content"] and "[Exit code:" not in messages[-1]["content"]
                    else "The rerun did not succeed as expected."
                ),
            ])

            try:
                with patch.object(panel, 'save_conversation'), \
                     patch.object(panel.rag_client, 'ingest_message'):
                    panel.send_worker("Create a tiny project from scratch, catch a failure, fix it, and finish.")
                    completed = self._wait_until_idle(panel, timeout=12.0)

                self.assertTrue(completed, "Timed out waiting for the Siege end-to-end run to finish")
                self.assertTrue(os.path.exists(app_file))
                with open(app_file, 'r', encoding='utf-8') as f:
                    self.assertIn('hello from siege', f.read())

                system_messages = [m["content"] for m in panel.messages if m["role"] == "system"]
                self.assertTrue(any("NameError" in m for m in system_messages))
                self.assertTrue(any("hello from siege" in m for m in system_messages))
                self.assertIn("Siege flow completed cleanly", panel.messages[-1]["content"])
                self.assertEqual(panel.tool_loop_count, 4)
                self.assertFalse(any(title == "Approval Needed" for title, _ in notifications))
            finally:
                panel.close()

    def test_siege_mode_reasoning_preamble_before_tools_still_completes(self):
        with self._blank_project() as project_dir:
            panel = self._panel(project_root=project_dir)
            panel.mode_combo.setCurrentText("Siege")
            panel.model_combo.clear()
            panel.model_combo.addItem("scripted-agent", "[Test] scripted-agent")
            panel.model_combo.setCurrentIndex(0)
            panel.on_model_changed("scripted-agent")

            note_file = f"{project_dir}/note.txt"
            reasoning_intro = (
                "I am going to reason step by step before I act.\n"
                "First I will outline the workspace state, then I will choose the smallest useful action,\n"
                "and only after that will I emit a tool call.\n"
                "This kind of verbose reasoning should not prevent the IDE from finding the tool tag.\n"
            )

            AIClient.configure_test_provider([
                reasoning_intro + f'\n<write_file path="{note_file}">\nreasoning-mode works\n</write_file>',
                reasoning_intro + f'\n<execute_command command="type note.txt" cwd="{project_dir}" />',
                "After extended reasoning, I created the file, verified its contents, and completed successfully.",
            ])

            try:
                with patch.object(panel, 'save_conversation'), \
                     patch.object(panel.rag_client, 'ingest_message'):
                    panel.send_worker("Think carefully, then create note.txt and verify it.")
                    completed = self._wait_until_idle(panel, timeout=12.0)

                self.assertTrue(completed)
                self.assertTrue(os.path.exists(note_file))
                with open(note_file, 'r', encoding='utf-8') as f:
                    self.assertEqual(f.read().strip(), 'reasoning-mode works')
                self.assertIn("completed successfully", panel.messages[-1]["content"])
                self.assertEqual(panel.tool_loop_count, 2)
            finally:
                panel.close()

    def test_siege_mode_reasoning_repeat_batch_hits_loop_guard(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.model_combo.clear()
        panel.model_combo.addItem("scripted-agent", "[Test] scripted-agent")
        panel.model_combo.setCurrentIndex(0)
        panel.on_model_changed("scripted-agent")

        repeated_reasoning = (
            "Let me think carefully about the next action.\n"
            "I will re-check the same evidence path while deliberating.\n"
            "The IDE should stop me before this turns into an endless loop.\n"
            "<list_files path=\"tests\" />"
        )
        AIClient.configure_test_provider([
            repeated_reasoning,
            repeated_reasoning,
            repeated_reasoning,
        ])

        notifications = []
        panel.notification_requested.connect(lambda title, message: notifications.append((title, message)))

        try:
            with patch.object(panel, 'save_conversation'), \
                 patch.object(panel.rag_client, 'ingest_message'):
                panel.send_worker("Reason about the repo until you decide on a tool.")
                completed = self._wait_until_idle(panel, timeout=12.0)

            self.assertTrue(completed)
            self.assertTrue(any(title == "Loop Guard Triggered" for title, _ in notifications))
            self.assertTrue(any("same tool batch 3 times" in message for _, message in notifications))
            self.assertEqual(panel.tool_loop_count, 2)
        finally:
            panel.close()

    def test_phased_mode_end_to_end_blank_project_pause_continue_and_fix(self):
        with self._blank_project() as project_dir:
            self.assertEqual(os.listdir(project_dir), [])
            panel = self._panel(project_root=project_dir, auto_approve_writes=False)
            panel.mode_combo.setCurrentText("Phased")
            panel.model_combo.clear()
            panel.model_combo.addItem("scripted-agent", "[Test] scripted-agent")
            panel.model_combo.setCurrentIndex(0)
            panel.on_model_changed("scripted-agent")

            app_file = f"{project_dir}/app.py"
            notifications = []
            panel.notification_requested.connect(lambda title, message: notifications.append((title, message)))

            AIClient.configure_test_provider([
                f'<write_file path="{app_file}">\nprint(message)\n</write_file>',
                lambda messages: (
                    "Phase 1 summary: I created the blank project file with a deliberate mistake. Next phase: run it and inspect the failure."
                    if "File written" in messages[-1]["content"]
                    else "Phase 1 summary failed unexpectedly."
                ),
                lambda _messages: f'<execute_command command="python app.py" cwd="{project_dir}" />',
                lambda messages: (
                    "Phase 2 summary: Running the project produced a NameError. Next phase: inspect and rewrite the file to fix the bug."
                    if "NameError" in messages[-1]["content"] and "[Exit code: 1]" in messages[-1]["content"]
                    else "Phase 2 summary failed unexpectedly."
                ),
                lambda messages: (
                    f'<read_file path="{app_file}" start_line="1" end_line="40" />\n'
                    f'<write_file path="{app_file}">\nmessage = "hello from phased"\nprint(message)\n</write_file>'
                    if any("NameError" in str(m.get("content", "")) for m in messages)
                    else "I lost the failure context before fixing it."
                ),
                lambda messages: (
                    "Phase 3 summary: I inspected the file and replaced the broken code with a valid implementation. Next phase: rerun the project to confirm it works."
                    if "Read file" in messages[-1]["content"] and "Wrote file" in messages[-1]["content"]
                    else "Phase 3 summary failed unexpectedly."
                ),
                lambda _messages: f'<execute_command command="python app.py" cwd="{project_dir}" />',
                lambda messages: (
                    "Phase 4 summary: The rerun printed hello from phased, so the fix is verified and the phased workflow completed correctly."
                    if "hello from phased" in messages[-1]["content"] and "[Exit code:" not in messages[-1]["content"]
                    else "Phase 4 summary failed unexpectedly."
                ),
            ])

            try:
                with patch.object(panel, 'save_conversation'), \
                     patch.object(panel.rag_client, 'ingest_message'), \
                     patch('ui.chat_panel.QMessageBox.question', return_value=QMessageBox.Yes):
                    panel.send_worker("Phase 1: create a tiny blank project with a bug.")
                    self.assertTrue(self._wait_until_idle(panel, timeout=10.0))
                    self.assertIn("Phase 1 summary", panel.messages[-1]["content"])

                    panel.send_worker("continue")
                    self.assertTrue(self._wait_until_idle(panel, timeout=10.0))
                    self.assertIn("Phase 2 summary", panel.messages[-1]["content"])

                    panel.send_worker("continue")
                    self.assertTrue(self._wait_until_idle(panel, timeout=10.0))
                    self.assertIn("Phase 3 summary", panel.messages[-1]["content"])

                    panel.send_worker("continue")
                    completed = self._wait_until_idle(panel, timeout=10.0)

                self.assertTrue(completed, "Timed out waiting for the Phased end-to-end run to finish")
                self.assertTrue(os.path.exists(app_file))
                with open(app_file, 'r', encoding='utf-8') as f:
                    self.assertIn('hello from phased', f.read())

                system_messages = [m["content"] for m in panel.messages if m["role"] == "system"]
                self.assertTrue(any("NameError" in m for m in system_messages))
                self.assertTrue(any("hello from phased" in m for m in system_messages))
                self.assertIn("phased workflow completed correctly", panel.messages[-1]["content"])
                self.assertGreaterEqual(sum(1 for title, _ in notifications if title == "Approval Needed"), 4)
                self.assertGreaterEqual(sum(1 for title, _ in notifications if title == "Phased Mode Complete"), 4)
                self.assertEqual(panel.send_btn.text(), "↑")
            finally:
                panel.close()

if __name__ == '__main__':
    unittest.main()
