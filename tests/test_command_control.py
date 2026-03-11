
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

from ui.chat_panel import ChatPanel, ToolWorker
from core.settings import SettingsManager
from core.ai_client import AIClient
from core.agent_tools import get_project_root, set_project_root


class TestCommandControl(unittest.TestCase):
    def _panel(self, project_root: str | None = None, auto_approve_writes: bool = False) -> ChatPanel:
        if project_root:
            set_project_root(project_root)
        with patch('ui.chat_panel.QTimer.singleShot', lambda *args, **kwargs: None):
            panel = ChatPanel()
        panel.settings_manager.get_auto_approve_writes = MagicMock(return_value=auto_approve_writes)
        panel.settings_manager.get_advanced_agent_tools_enabled = MagicMock(return_value=False)
        panel.settings_manager.get_web_search_enabled = MagicMock(return_value=False)
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

    def test_messages_for_ai_compacts_older_tool_results_but_keeps_latest_full(self):
        panel = self._panel()
        older_tool = (
            "[TOOL_RESULT] (Automated system output — not user input)\n"
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- write_file: README.md\n"
            "Other successful actions:\n"
            "- list_files .\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]\n"
            "Listed files in '.':\nREADME.md\napp.py\n[/TOOL_RESULT]"
        )
        latest_tool = (
            "[TOOL_RESULT] (Automated system output — not user input)\n"
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- write_file: app.py\n"
            "Other successful actions:\n"
            "- execute_command: python app.py\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]\n"
            "Command Output:\nHello from VoxAI!\n[/TOOL_RESULT]"
        )

        converted = panel._messages_for_ai([
            {"role": "system", "content": older_tool},
            {"role": "assistant", "content": "I created the README first."},
            {"role": "system", "content": latest_tool},
        ])

        self.assertIn("compact replay", converted[0]["content"])
        self.assertIn("write_file: README.md", converted[0]["content"])
        self.assertIn("Output excerpt:", converted[0]["content"])
        self.assertEqual(converted[2]["content"], latest_tool)

    def test_messages_for_ai_leaves_single_tool_result_uncompacted(self):
        panel = self._panel()
        only_tool = "[TOOL_RESULT]\n[ACTION_SUMMARY]\nSuccessful file changes:\n- app.py\n[/ACTION_SUMMARY]\nEdited app.py\n[/TOOL_RESULT]"

        converted = panel._messages_for_ai([
            {"role": "system", "content": only_tool},
        ])

        self.assertEqual(converted[0]["content"], only_tool)

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
        tool_surface = next(
            msg['content'] for msg in phased_history
            if msg['role'] == 'system' and "TOOL SURFACE:" in str(msg['content'])
        )
        self.assertIn("STOP after the summary", phased_prompt)
        self.assertIn("wait for the user", phased_prompt)
        self.assertIn("reply 'continue'", guided_prompt)
        self.assertIn("<find_tests />", tool_coach)
        self.assertIn("<get_imports />", tool_coach)
        self.assertIn("<find_importers />", tool_coach)
        self.assertIn("start_line=\"10\" end_line=\"14\"", tool_coach)
        self.assertIn("insert_after=\"class Demo:", tool_coach)
        self.assertIn("Advanced tools are OFF for this run", tool_coach)
        self.assertIn("Stable core only", tool_surface)
        self.assertIn("<find_tests>", guided_prompt)
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
    def test_persistent_task_board_is_injected_into_ai_history(self, MockThread, MockWorker):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._reset_guided_takeoff("Fix the parser drift without restarting the plan.")
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._pending_summary_guard_flags = {"no_post_edit_validation", "no_post_edit_rescan"}
        panel._refresh_guided_task_board()

        panel._start_ai_worker("continue")
        history = MockWorker.call_args.args[0]
        task_prompt = next(
            msg['content'] for msg in history
            if msg['role'] == 'system' and "PERSISTENT TASK BOARD" in str(msg['content'])
        )

        self.assertIn("MODEL MUST AUTHOR AND UPDATE THIS BOARD", task_prompt)
        self.assertIn("<task_board>", task_prompt)
        self.assertIn("[COMPLETE] Inspect the task and gather grounded evidence", task_prompt)
        self.assertIn("[COMPLETE] Stay on one concrete target and apply the smallest safe change", task_prompt)
        self.assertIn("[CURRENT] Validate the latest change with the smallest useful command", task_prompt)
        self.assertIn("[PENDING] Do one fresh post-edit rescan and report grounded results", task_prompt)

    @patch('ui.chat_panel.AIWorker')
    @patch('ui.chat_panel.QThread')
    def test_persistent_task_board_is_reinjected_on_followup_turns_without_user_text(self, MockThread, MockWorker):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._reset_guided_takeoff("Build the project, then validate and report grounded results.")
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._pending_summary_guard_flags = {"no_post_edit_validation", "no_post_edit_rescan"}
        panel._refresh_guided_task_board()

        panel._start_ai_worker(extra_system_messages=["[TOOL_RESULT]\nEdited app.py"])
        history = MockWorker.call_args.args[0]
        task_prompt = next(
            msg['content'] for msg in history
            if msg['role'] == 'system' and "PERSISTENT TASK BOARD" in str(msg['content'])
        )

        self.assertIn("CURRENT TASK: Validate the latest change with the smallest useful command", task_prompt)
        self.assertIn("If you start drifting, get lost, or reopen planning, return to the CURRENT task immediately", task_prompt)
        self.assertIn("Do NOT ask the user to reply 'continue' while the CURRENT task is still actionable", task_prompt)

    def test_guided_blocker_summary_fallback_references_current_task_board_task(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._reset_guided_takeoff("Build the project, then validate and report grounded results.")
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._pending_summary_guard_flags = {"no_post_edit_validation", "no_post_edit_rescan"}
        panel._refresh_guided_task_board()

        summary = panel._guided_blocker_summary_fallback()

        self.assertIn("CURRENT TASK FROM THE PERSISTENT TASK BOARD", summary)
        self.assertIn("Validate the latest change with the smallest useful command", summary)
        self.assertIn("tell me which blocker or decision to resolve first", summary)

    def test_handle_ai_finished_strips_llm_task_board_and_updates_tracker(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel.current_ai_response = (
            "<task_board>\n"
            "GOAL: Build and polish the pong project\n"
            "- [COMPLETE] Inspect the current game files\n"
            "- [CURRENT] Add countdown and polish the HUD\n"
            "- [PENDING] Rerun pytest and self-test\n"
            "</task_board>\n"
            "- Changed: main.py.\n- Verified: latest validation command succeeded."
        )

        with patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_ai_finished()

        self.assertEqual(panel._guided_task_board_source, "llm")
        self.assertEqual(panel._guided_current_task_title(), "Add countdown and polish the HUD")
        self.assertNotIn("<task_board>", panel.current_ai_response)
        self.assertIn("Changed: main.py", panel.current_ai_response)

    def test_decision_gate_requires_llm_task_board_update_on_non_tool_response(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._reset_guided_takeoff("Fix the parser drift without restarting the plan.")
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = False
        panel._guided_task_board_updated_this_turn = False

        prompt = panel._guided_non_tool_decision_gate_prompt("I will validate the latest change next.")

        self.assertIn("DO NOT STOP BEFORE THE FIRST REAL ACTION", prompt)
        self.assertIn("<task_board>", prompt)

    def test_polish_prompt_counts_as_direct_change_request(self):
        panel = self._panel()

        self.assertTrue(panel._user_explicitly_requested_changes("Now polish the game with countdown, HUD, and win/reset details."))

        panel._reset_guided_takeoff("Now polish the game with countdown, HUD, and win/reset details.")

        self.assertTrue(panel._guided_direct_change_requested)

    def test_summary_guard_flags_mark_failed_validation_after_edit(self):
        panel = self._panel()
        panel._run_tool_action_log = [
            "Edited engine/game_logic.py -> Done",
            "Executed: python -m pytest -q -> Failed",
        ]
        flags = panel._summary_guard_flags(
            "ACTION_SUMMARY:\n"
            "Successful file changes:\n"
            "- edit_file: engine/game_logic.py\n"
            "Other successful actions:\n"
            "- none\n"
            "Failed actions:\n"
            "- execute_command python -m pytest -q: exit code 1\n",
        )

        self.assertIn("validation_failed", flags)
        self.assertIn("post_edit_validation_failed", flags)

    def test_task_board_prompt_warns_when_validation_is_failing(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._reset_guided_takeoff("Fix the gameplay bug and keep validation green.")
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._pending_summary_guard_flags = {"validation_failed", "post_edit_validation_failed"}
        panel._tool_action_log = [
            "Edited engine/game_logic.py -> Done",
            "Executed: python -m pytest -q -> Failed",
        ]
        panel._run_tool_action_log = list(panel._tool_action_log)
        panel._tool_specs_for_run = [{"cmd": "edit_file", "args": {"path": "engine/game_logic.py"}}]

        prompt = panel._guided_task_board_prompt()

        self.assertIn("LATEST FAILED VALIDATION COMMAND: python -m pytest -q", prompt)
        self.assertIn("CURRENT task must stay on fixing/rerunning that failure", prompt)
        self.assertIn("Do NOT move CURRENT to README/docs", prompt)

    def test_decision_gate_blocks_continue_when_current_task_is_actionable(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._guided_task_board = [
            {"id": "inspect", "title": "Inspect the current game files", "status": "complete"},
            {"id": "polish", "title": "Add countdown and polish the HUD", "status": "current"},
            {"id": "validate", "title": "Rerun pytest and self-test", "status": "pending"},
        ]
        panel._guided_task_board_source = "llm"
        panel._guided_task_board_updated_this_turn = True

        prompt = panel._guided_non_tool_decision_gate_prompt("Reply 'continue' and I'll add the countdown next.")

        self.assertIn("ADVANCE THE CURRENT TASK NOW", prompt)
        self.assertIn("Add countdown and polish the HUD", prompt)

        softer_prompt = panel._guided_non_tool_decision_gate_prompt("If you want, I can proceed with the countdown polish next.")

        self.assertIn("STOP ASKING FOR CONTINUE", softer_prompt)
        self.assertIn("Add countdown and polish the HUD", softer_prompt)

        markdown_prompt = panel._guided_non_tool_decision_gate_prompt("Follow-up for you: Reply **continue** to proceed with the countdown feature.")

        self.assertIn("STOP ASKING FOR CONTINUE", markdown_prompt)
        self.assertIn("Add countdown and polish the HUD", markdown_prompt)

    def test_decision_gate_blocks_inspection_only_summary_when_current_task_requires_action(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._guided_task_board = [
            {"id": "inspect", "title": "Inspect the current game files", "status": "complete"},
            {"id": "polish", "title": "Fix bugs and add countdown, speedup, HUD state to game_logic.py", "status": "current"},
            {"id": "validate", "title": "Rerun pytest and self-test", "status": "pending"},
        ]
        panel._guided_task_board_source = "llm"
        panel._guided_task_board_updated_this_turn = True

        prompt = panel._guided_non_tool_decision_gate_prompt(
            "Phase 1 Inspection Complete — No files changed.\n\n"
            "Finding 1: Ball.reset uses math.random().\n"
            "Evidence: game_logic.py line 27 uses math.random().\n"
            "Recommended next step: fix the bug and add countdown state."
        )

        self.assertIn("DO NOT END THIS PHASE ON INSPECTION ONLY", prompt)
        self.assertIn("Fix bugs and add countdown, speedup, HUD state to game_logic.py", prompt)

    def test_decision_gate_blocks_current_task_drift_when_validation_failed(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._pending_summary_guard_flags = {"validation_failed", "post_edit_validation_failed"}
        panel._tool_action_log = [
            "Edited game_logic.py -> Done",
            "Executed: python -m pytest -q -> Failed",
        ]
        panel._run_tool_action_log = list(panel._tool_action_log)
        panel._tool_specs_for_run = [{"cmd": "edit_file", "args": {"path": "game_logic.py"}}]
        panel._guided_task_board = [
            {"id": "fix", "title": "Fix countdown and paddle collision bugs in game_logic.py", "status": "complete"},
            {"id": "docs", "title": "Improve README controls and instructions", "status": "current"},
            {"id": "validate", "title": "Rerun pytest and self-test", "status": "pending"},
        ]
        panel._guided_task_board_source = "llm"
        panel._guided_task_board_updated_this_turn = True

        prompt = panel._guided_non_tool_decision_gate_prompt(
            "I updated the README controls section and can continue polishing the instructions next."
        )

        self.assertIn("GUIDED VALIDATION FAILURE GATE", prompt)
        self.assertIn("Improve README controls and instructions", prompt)
        self.assertIn("python -m pytest -q", prompt)

    def test_decision_gate_blocks_audit_reexamine_handoff_when_current_task_requires_fix(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._guided_task_board = [
            {"id": "inspect", "title": "Read all project files for thorough audit", "status": "complete"},
            {"id": "audit", "title": "Apply top 2 safe fixes (must re-verify actual bugs first)", "status": "current"},
            {"id": "validate", "title": "Validate with pytest and self-test", "status": "pending"},
        ]
        panel._guided_task_board_source = "llm"
        panel._guided_task_board_updated_this_turn = True

        prompt = panel._guided_non_tool_decision_gate_prompt(
            "The AUDIT.md contained false findings - the Score.add_point() code in the actual file is complete. "
            "Let me re-examine the real code and find actual issues:"
        )

        self.assertIn("AUDIT PHASE IS NOT DONE YET", prompt)
        self.assertIn("apply at least one non-AUDIT safe fix", prompt)

    def test_audit_completion_gate_requires_audit_artifact_and_fix(self):
        with self._blank_project() as tmpdir:
            panel = self._panel(project_root=tmpdir)
            panel.mode_combo.setCurrentText("Siege")
            panel._guided_takeoff_stage = 2
            panel._guided_successful_edit_seen = True
            panel._guided_task_board_goal = "Audit this codebase, write AUDIT.md, and apply the top 2 safe fixes."
            panel._guided_task_board = [
                {"id": "inspect", "title": "Inspect the project and gather audit evidence", "status": "complete"},
                {"id": "audit", "title": "Write the audit findings and apply the top safe fixes", "status": "current"},
                {"id": "validate", "title": "Rerun pytest and self-test", "status": "pending"},
            ]
            panel._guided_task_board_source = "llm"
            panel._guided_task_board_updated_this_turn = True
            panel._pending_summary_guard_flags = set()
            panel._pending_summary_grounded_files = []

            prompt = panel._guided_non_tool_decision_gate_prompt("Audit complete. Everything is done.")

        self.assertIn("AUDIT PHASE IS NOT DONE YET", prompt)
        self.assertIn("write AUDIT.md", prompt)

    def test_continue_preserves_task_board_statuses(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._reset_guided_takeoff("Tighten the recovery loop and keep progress.")
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._pending_summary_guard_flags = {"no_post_edit_validation", "no_post_edit_rescan"}
        panel._refresh_guided_task_board()
        before = [dict(task) for task in panel._guided_task_board]

        with patch.object(panel, '_start_ai_worker') as mock_start, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'):
            panel.send_worker("continue")

        mock_start.assert_called_once()
        after = panel._guided_task_board
        self.assertEqual(before, after)
        self.assertEqual(panel._guided_task_board_goal, "Tighten the recovery loop and keep progress.")

    def test_task_board_widget_reflects_guided_statuses(self):
        panel = self._panel()
        self.assertTrue(panel.task_board_card.isHidden())

        panel.mode_combo.setCurrentText("Siege")
        panel._reset_guided_takeoff("Tighten the recovery loop and keep progress.")
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._pending_summary_guard_flags = {"no_post_edit_validation", "no_post_edit_rescan"}
        panel._refresh_guided_task_board()

        self.assertFalse(panel.task_board_card.isHidden())
        self.assertIn("Project Tracker · 2/4 complete", panel.task_board_title_label.text())
        self.assertIn("Current: Validate the latest change with the smallest useful command", panel.task_board_title_label.text())
        self.assertFalse(panel.task_board_goal_label.isVisible())
        self.assertFalse(panel.task_board_body_label.isVisible())
        tooltip = panel.task_board_card.toolTip()
        self.assertIn("Goal: Tighten the recovery loop and keep progress.", tooltip)
        self.assertIn("[x] COMPLETE Inspect the task and gather grounded evidence", tooltip)
        self.assertIn("[>] CURRENT  Validate the latest change with the smallest useful command", tooltip)

    def test_refresh_models_highlights_recommended_benchmark_model(self):
        panel = self._panel()
        panel.model_combo.clear()
        with patch.object(panel.settings_manager, 'get_enabled_models', return_value=[
            SettingsManager.DEFAULT_BENCHMARK_MODEL,
            "[OpenRouter] qwen/qwen3-coder:free",
        ]), patch.object(panel.settings_manager, 'get_selected_model', return_value=SettingsManager.DEFAULT_BENCHMARK_MODEL):
            panel.refresh_models()

        self.assertEqual(panel.model_combo.itemData(0), SettingsManager.DEFAULT_BENCHMARK_MODEL)
        self.assertEqual(panel.model_combo.itemText(0), "grok-code-fast-1 ★")
        self.assertIn("Recommended benchmark model selected: grok-code-fast-1", panel.model_combo.toolTip())

    def test_task_board_state_persists_across_save_and_switch(self):
        with self._blank_project() as tmpdir:
            panel = self._panel(project_root=tmpdir)
            panel.settings_manager.get_auto_save_conversation = MagicMock(return_value=True)
            panel.messages = [{"role": "user", "content": "Fix parser drift and do not restart the plan."}]
            panel._reset_guided_takeoff("Fix parser drift and do not restart the plan.")
            panel._guided_takeoff_stage = 2
            panel._guided_successful_edit_seen = True
            panel._pending_summary_guard_flags = {"no_post_edit_validation", "no_post_edit_rescan"}
            panel._refresh_guided_task_board()
            panel.save_conversation()
            conv_id = panel.conversation_id

            restored = self._panel(project_root=tmpdir)
            restored.settings_manager.get_auto_save_conversation = MagicMock(return_value=True)
            restored.switch_conversation(conv_id)

            self.assertEqual(restored._guided_task_board_goal, panel._guided_task_board_goal)
            self.assertEqual(restored._guided_task_board, panel._guided_task_board)
            self.assertFalse(restored.task_board_card.isHidden())
            self.assertEqual(restored.task_board_title_label.text(), panel.task_board_title_label.text())
            self.assertEqual(restored.task_board_card.toolTip(), panel.task_board_card.toolTip())

    def test_phased_queued_batch_persists_across_save_and_switch(self):
        with self._blank_project() as tmpdir:
            panel = self._panel(project_root=tmpdir)
            panel.settings_manager.get_auto_save_conversation = MagicMock(return_value=True)
            panel.mode_combo.setCurrentText("Phased")
            panel.messages = [{"role": "user", "content": "Inspect one bounded phase, then wait."}]
            panel.current_ai_item = MagicMock()
            panel.current_ai_response = '<list_files path="tests" />'
            panel._phased_summary_pending = True
            panel._guided_takeoff_stage = 2

            with patch.object(panel.rag_client, 'ingest_message'):
                panel.handle_ai_finished()
            conv_id = panel.conversation_id

            restored = self._panel(project_root=tmpdir)
            restored.settings_manager.get_auto_save_conversation = MagicMock(return_value=True)
            restored.mode_combo.setCurrentText("Phased")
            restored.switch_conversation(conv_id)

            self.assertEqual(restored._pending_phased_tools, [{"cmd": "list_files", "args": {"path": "tests"}}])

            with patch.object(restored, '_start_tool_execution') as mock_tools, \
                 patch.object(restored, '_start_ai_worker') as mock_ai, \
                 patch.object(restored.rag_client, 'ingest_message'):
                restored.send_worker("continue")

            mock_tools.assert_called_once_with([{"cmd": "list_files", "args": {"path": "tests"}}])
            mock_ai.assert_not_called()

    def test_phased_summary_state_persists_across_save_and_switch(self):
        with self._blank_project() as tmpdir:
            panel = self._panel(project_root=tmpdir)
            panel.settings_manager.get_auto_save_conversation = MagicMock(return_value=True)
            panel.mode_combo.setCurrentText("Phased")
            panel.messages = [{"role": "user", "content": "Inspect, summarize, then wait for approval."}]
            panel.current_ai_item = MagicMock()
            panel.current_ai_response = (
                "Finding 1: app.py is the likely fix target.\n"
                "Evidence: the bounded inspection isolated the failure to that file.\n"
                "Recommended next step: edit app.py and rerun the project.\n"
                "Follow-up for you: reply 'continue' to edit app.py."
            )
            panel._phased_summary_pending = True
            panel._guided_takeoff_stage = 1

            with patch.object(panel.rag_client, 'ingest_message'):
                panel.handle_ai_finished()
            conv_id = panel.conversation_id

            restored = self._panel(project_root=tmpdir)
            restored.settings_manager.get_auto_save_conversation = MagicMock(return_value=True)
            restored.mode_combo.setCurrentText("Phased")
            restored.switch_conversation(conv_id)

            self.assertEqual(restored._guided_takeoff_stage, 2)
            self.assertIn("reply 'continue'", restored._guided_phase_anchor)
            self.assertEqual(restored._pending_phased_tools, [])

    def test_project_tracker_state_persists_session_changes(self):
        with self._blank_project() as tmpdir:
            panel = self._panel(project_root=tmpdir)
            panel.settings_manager.get_auto_save_conversation = MagicMock(return_value=True)
            file_path = os.path.join(tmpdir, "ui", "chat_panel.py")
            panel.messages = [{"role": "user", "content": "Track diffs for this conversation."}]
            panel._reset_guided_takeoff("Track diffs for this conversation.")
            panel._guided_takeoff_stage = 2
            panel._refresh_guided_task_board()
            panel._record_session_change(file_path, "@@\n- old line\n+ new line")
            panel.save_conversation()
            conv_id = panel.conversation_id

            restored = self._panel(project_root=tmpdir)
            restored.settings_manager.get_auto_save_conversation = MagicMock(return_value=True)
            restored.switch_conversation(conv_id)
            state = restored.project_tracker_state()

            self.assertEqual(state["goal"], "Track diffs for this conversation.")
            self.assertEqual(len(state["session_changes"]), 1)
            self.assertEqual(state["session_changes"][0]["display_path"], "ui/chat_panel.py")
            self.assertIn("+ new line", state["session_changes"][0]["diff_preview"])
            self.assertIn("+ new line", state["session_changes"][0]["diff_text"])


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

    def test_stopped_blank_response_does_not_turn_into_blank_fallback(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Phased")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = ""
        panel._stop_requested = True

        notifications = []
        panel.notification_requested.connect(lambda title, message: notifications.append((title, message)))

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'):
            panel.handle_ai_finished()

        mock_restart.assert_not_called()
        mock_tools.assert_not_called()
        self.assertEqual(panel.current_ai_response, "")
        self.assertEqual(panel.messages, [])
        self.assertIn(("Generation Stopped", "Stopped before any additional tool execution could continue."), notifications)
        self.assertTrue(any(args and args[0] == "[Stopped]" for args, _kwargs in panel.current_ai_item.set_text.call_args_list))

    def test_close_event_drains_background_threads(self):
        panel = self._panel()
        ai_thread = MagicMock()
        ai_thread.isRunning.return_value = True
        tool_thread = MagicMock()
        tool_thread.isRunning.return_value = True
        indexing_thread = MagicMock()
        indexing_thread.isRunning.return_value = True
        tool_worker = MagicMock()
        panel.ai_thread_obj = ai_thread
        panel.tool_thread = tool_thread
        panel.indexing_thread = indexing_thread
        panel.tool_worker = tool_worker

        panel.close()

        tool_worker.approve.assert_called_once_with(False)
        for thread in (ai_thread, tool_thread, indexing_thread):
            thread.requestInterruption.assert_called_once_with()
            thread.quit.assert_called_once_with()
            thread.wait.assert_called_once_with(5000)
        self.assertIsNone(panel.ai_thread_obj)
        self.assertIsNone(panel.tool_thread)
        self.assertIsNone(panel.indexing_thread)
        self.assertTrue(panel._shutting_down)

    def test_start_auto_indexing_skips_when_panel_is_shutting_down(self):
        panel = self._panel()
        panel._shutting_down = True

        with patch.object(panel, '_rag_enabled', return_value=True):
            panel.start_auto_indexing()

        self.assertIsNone(panel.indexing_thread)
        self.assertIsNone(panel.indexing_worker)

    def test_stale_thread_cleanup_does_not_clear_newer_refs(self):
        panel = self._panel()
        old_ai_thread = object()
        old_ai_worker = object()
        new_ai_thread = object()
        new_ai_worker = object()
        panel.ai_thread_obj = new_ai_thread
        panel.ai_worker_obj = new_ai_worker

        panel._clear_ai_refs(old_ai_thread, old_ai_worker)
        self.assertIs(panel.ai_thread_obj, new_ai_thread)
        self.assertIs(panel.ai_worker_obj, new_ai_worker)

        panel._clear_ai_refs(new_ai_thread, new_ai_worker)
        self.assertIsNone(panel.ai_thread_obj)
        self.assertIsNone(panel.ai_worker_obj)

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

        extra_msgs = mock_restart.call_args.kwargs.get('extra_system_messages')
        self.assertGreaterEqual(len(extra_msgs), 1)
        self.assertIn("Exact files successfully changed in the latest tool cycle: main.py", "\n".join(extra_msgs))

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
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
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
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        self.assertEqual(panel._guided_phase_summary_retry_count, 1)
        mock_restart.assert_called_once()
        self.assertIn("Do not emit tool calls in this response", mock_restart.call_args.args[0])

    def test_guided_takeoff_rewrites_phase_one_plan_without_tools_into_real_inspection(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Phased")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I will inspect the codebase systematically and then report back with findings."
        panel._phased_summary_pending = True
        panel._guided_takeoff_stage = 1
        panel._guided_direct_change_requested = False

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        self.assertEqual(panel._guided_phase_intent_retry_count, 1)
        mock_restart.assert_called_once()
        self.assertIn("only described a plan", mock_restart.call_args.args[0])

    def test_guided_takeoff_rewrites_phase_one_no_tool_reply_into_grounded_handoff_after_evidence(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Phased")
        panel.messages = [{"role": "system", "content": "[TOOL_RESULT]\nRead file: ok"}]
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I explored the repo and have a next step in mind."
        panel._phased_summary_pending = True
        panel._guided_takeoff_stage = 1
        panel._guided_direct_change_requested = False

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel._guided_phase_intent_retry_count, 1)
        mock_restart.assert_called_once()
        self.assertIn("grounded user-facing Phase 1 handoff", mock_restart.call_args.args[0])

    def test_guided_takeoff_rewrites_shallow_phase_one_evidence_into_targeted_inspection(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Phased")
        panel.messages = [{"role": "system", "content": "[TOOL_RESULT]\nListed files in '.':\napp.py"}]
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I have enough context to continue from here."
        panel._phased_summary_pending = True
        panel._guided_takeoff_stage = 1
        panel._guided_direct_change_requested = False
        panel._tool_calls_for_run = ["list_files"]

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel._guided_phase_intent_retry_count, 1)
        mock_restart.assert_called_once()
        self.assertIn("Do not use <list_files> again", mock_restart.call_args.args[0])

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

    def test_stage_two_trims_tool_batch_more_aggressively_for_all_models(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
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

    def test_stage_two_prefers_fix_oriented_batch_when_edit_is_later(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            '<search_files query="sk-" file_pattern="*.py" />\n'
            '<read_file path="ImageGen/image_worker.py" />\n'
            '<search_codebase query="OpenAI(api_key" />\n'
            '<edit_file path="ImageGen/image_worker.py" old_text="a" new_text="b" />'
        )
        panel._guided_takeoff_stage = 2
        panel._guided_no_progress_cycles = 1

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_ai_finished()

        trimmed_tools = mock_tools.call_args.args[0]
        self.assertEqual([tool["cmd"] for tool in trimmed_tools], ["read_file", "edit_file"])
        self.assertIn("fix-oriented batch", panel.messages[1]["content"])

    def test_decision_gate_does_not_demand_validation_when_latest_cycle_had_no_edit(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._pending_summary_guard_flags = {"no_file_changes", "no_validation"}

        gate = panel._guided_decision_gate_prompt([
            {"cmd": "search_files", "args": {"query": "sk-", "file_pattern": "*.py"}},
            {"cmd": "edit_file", "args": {"path": "ImageGen/image_worker.py"}},
        ])

        self.assertIsNone(gate)

    def test_decision_gate_rewrites_broad_investigation_after_no_progress(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            '<search_files query="CUDA" file_pattern="*.py" />\n'
            '<read_file path="engine/hardware_check.py" />'
        )
        panel._guided_takeoff_stage = 2
        panel._guided_no_progress_cycles = 2

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        self.assertEqual(panel._guided_decision_retry_count, 1)
        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — COMMIT OR STOP", combined)

    def test_decision_gate_commits_sooner_when_concrete_target_exists(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = '<read_file path="engine/hardware_check.py" />'
        panel._guided_takeoff_stage = 2
        panel._guided_no_progress_cycles = 1
        panel._guided_phase_anchor = "Finding 1 points to engine/hardware_check.py as the best-supported target."

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — STAY ON ONE TARGET", combined)
        self.assertIn("engine/hardware_check.py", combined)

    def test_decision_gate_blocks_reinspection_after_same_target_probe_used(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = '<read_file path="engine/hardware_check.py" />'
        panel._guided_takeoff_stage = 2
        panel._guided_no_progress_cycles = 1
        panel._guided_same_target_probe_count = 1
        panel._guided_phase_anchor = "Finding 1 points to engine/hardware_check.py as the best-supported target."

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — NO MORE SAME-TARGET INSPECTION", combined)
        self.assertIn("engine/hardware_check.py", combined)

    def test_decision_gate_falls_back_to_blocker_summary_after_retry(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
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
        self.assertIn("tell me which blocker or decision to resolve first", panel.messages[-1]["content"])

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

    def test_decision_gate_requires_rescan_when_edit_already_exists(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = '<execute_command command="python -m py_compile engine/hardware_check.py" cwd="." />'
        panel._guided_takeoff_stage = 2
        panel._pending_summary_guard_flags = {"no_post_edit_rescan"}

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — FINISH THE CURRENT FIX CYCLE", combined)
        self.assertIn("fresh post-edit rescan", combined)

    def test_non_tool_decision_gate_rewrites_analysis_only_stage_two_reply(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "The real issue is in run.bat, but I need to inspect more before taking action."
        panel._guided_takeoff_stage = 2

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — DO NOT STOP BEFORE THE FIRST REAL ACTION", combined)

    def test_non_tool_decision_gate_rewrites_stage_one_bounded_start_narration(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            "I will create app.py, intentionally trigger a runtime failure, and then fix it after I inspect the result."
        )
        panel._guided_takeoff_stage = 1
        panel._guided_direct_change_requested = True

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — DO NOT STOP BEFORE THE FIRST TOOL BATCH", combined)
        self.assertIn("user asked for a concrete change/report", combined)

    def test_non_tool_decision_gate_blocks_fabricated_action_log_before_grounded_work(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            "**ACTION LOG:**\n"
            "1. Creating initial application (`app.py`)\n"
            "2. Executing `python app.py` and observing the traceback\n"
            "3. Applying the fix and verifying the result\n\n"
            "**FINAL SUMMARY:** The application is now fully functional."
        )
        panel._guided_takeoff_stage = 1
        panel._guided_direct_change_requested = True

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — DO NOT SIMULATE COMPLETED WORK", combined)
        self.assertIn("Do NOT invent file contents", combined)

    def test_stage_one_bounded_start_second_narration_launches_minimal_probe(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I will create a tiny app and then run it once I inspect the workspace."
        panel._guided_takeoff_stage = 1
        panel._guided_direct_change_requested = True
        panel._guided_decision_retry_count = 1

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, 'append_message_widget'), \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'):
            panel.handle_ai_finished()

        mock_tools.assert_called_once_with([{'cmd': 'list_files', 'args': {'path': '.'}}])
        self.assertEqual(panel._guided_bounded_start_probe_count, 1)
        self.assertEqual(panel.messages[-1]['role'], 'system')
        self.assertIn('minimal probe', panel.messages[-1]['content'])

    def test_stage_one_navigation_second_narration_launches_navigation_probe(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.messages = [{
            "role": "user",
            "content": "Use navigation tools to find where Worker.run is defined, what it imports, what imports it, and which tests cover it. Write a concise findings report to benchmark_report.md.",
        }]
        panel.current_ai_response = "I will inspect the repo and then write the report."
        panel._guided_takeoff_stage = 1
        panel._guided_decision_retry_count = 1

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, 'append_message_widget'), \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'):
            panel.handle_ai_finished()

        mock_tools.assert_called_once_with([
            {'cmd': 'find_symbol', 'args': {'symbol': 'Worker.run', 'root_dir': '.'}},
            {'cmd': 'find_tests', 'args': {'query': 'Worker.run'}},
        ])
        self.assertEqual(panel._guided_bounded_start_probe_count, 1)

    def test_navigation_report_batch_inserts_navigation_probe_before_report_write(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = [{
            "role": "user",
            "content": "Use navigation tools to find where Worker.run is defined, what it imports, what imports it, and which tests cover it. Write a concise findings report to benchmark_report.md.",
        }]

        filtered, note = panel._guided_takeoff_filter_tools([
            {"cmd": "write_file", "args": {"path": "benchmark_report.md", "content": "draft"}},
        ])

        self.assertEqual(filtered, [
            {'cmd': 'find_symbol', 'args': {'symbol': 'Worker.run', 'root_dir': '.'}},
            {'cmd': 'find_tests', 'args': {'query': 'Worker.run'}},
        ])
        self.assertIn('grounding navigation batch', note)

    def test_navigation_report_filter_blocks_unrelated_file_edits(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = [{
            "role": "user",
            "content": "Use navigation tools to find where Worker.run is defined, what it imports, what imports it, and which tests cover it. Write a concise findings report to benchmark_report.md.",
        }]
        panel._guided_takeoff_stage = 2
        panel._run_tool_calls = ["find_symbol", "find_tests"]

        filtered, note = panel._guided_takeoff_filter_tools([
            {"cmd": "edit_file", "args": {"path": "core/helpers.py", "old_text": "return 'ok'", "new_text": "return 'still ok'"}},
        ])

        self.assertEqual(filtered, [])
        self.assertIn('only write/edit benchmark_report.md', note)

    def test_non_tool_decision_gate_demands_same_target_edit_when_target_known(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "The best-supported issue is in engine/hardware_check.py, but I have not changed anything yet."
        panel._guided_takeoff_stage = 2
        panel._guided_phase_anchor = "Finding 1 points to engine/hardware_check.py as the best-supported target."

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — DO NOT STOP AT TARGET ANALYSIS", combined)
        self.assertIn("engine/hardware_check.py", combined)

    def test_non_tool_decision_gate_blocks_reinspection_after_probe_used(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I should inspect engine/hardware_check.py one more time before editing."
        panel._guided_takeoff_stage = 2
        panel._guided_same_target_probe_count = 1
        panel._guided_phase_anchor = "Finding 1 points to engine/hardware_check.py as the best-supported target."

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — DO NOT RE-INSPECT THIS TARGET", combined)
        self.assertIn("engine/hardware_check.py", combined)

    def test_non_tool_decision_gate_rewrites_pseudo_tool_advice_before_first_batch(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "**Next Step:** Run a tool to inspect `crash.log`. Example command: ```bash\ncat crash.log\n```"
        panel._guided_takeoff_stage = 2

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — TAKE THE FIRST ACTION NOW", combined)
        self.assertIn("Do NOT describe tools, example commands", combined)

    def test_non_tool_decision_gate_allows_grounded_blocker_before_first_batch(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2

        gate = panel._guided_non_tool_decision_gate_prompt(
            "I cannot safely continue because I need user permission before touching deployment configuration."
        )

        self.assertIsNone(gate)

    def test_non_tool_decision_gate_requires_validation_after_edit(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = [{"role": "system", "content": "[TOOL_RESULT] Edited engine/hardware_check.py"}]
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I still need to validate the latest change before I can confirm it." 
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._pending_summary_guard_flags = {"no_post_edit_validation", "no_post_edit_rescan"}

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — DO NOT END BEFORE VALIDATION", combined)

    def test_non_tool_decision_gate_requires_validation_after_edit_even_when_none_ran(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I updated engine/model_manager.py to fix it."
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._pending_summary_guard_flags = {"no_validation", "no_post_edit_rescan"}

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — DO NOT END BEFORE VALIDATION", combined)
        self.assertIn("validation/rescan", combined)

    def test_non_tool_decision_gate_requires_explicit_project_start_deliverables(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = [{
            "role": "user",
            "content": (
                "This folder is empty. Start a very small new Python project here. "
                "Create only the minimum files needed for a basic runnable CLI starter: "
                "app.py that prints a short greeting, plus a short README.md with run instructions. "
                "Then validate it by running python app.py. Keep the project tiny and grounded."
            ),
        }]
        panel._guided_task_board_goal = panel.messages[0]["content"]
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._session_change_log = [{
            "file_path": "app.py",
            "display_path": "app.py",
            "diff_preview": "+ print('hello')",
            "diff_text": "@@\n+print('hello')",
        }]
        panel._run_tool_action_log = [
            "Wrote app.py -> Done",
            "Executed: python -m py_compile app.py -> Done",
            "Read file: app.py -> Done",
        ]

        gate = panel._guided_non_tool_decision_gate_prompt("I created app.py and finished the starter.")

        self.assertIsNotNone(gate)
        self.assertIn("GUIDED COMPLETION GATE", gate)
        self.assertIn("README.md", gate)
        self.assertIn("python app.py", gate)

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

    def test_tool_call_wrapper_executes_tools_instead_of_malformed_rewrite(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            "I will inspect the likely target now.\n"
            '<tool_call>read_file path="engine/model_manager.py" />\n'
            '<tool_call>execute_command command="python -m py_compile engine/model_manager.py" cwd="." />'
        )
        panel._guided_takeoff_stage = 2

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_ai_finished()

        mock_restart.assert_not_called()
        mock_tools.assert_called_once()
        parsed_tools = mock_tools.call_args.args[0]
        self.assertEqual([tool["cmd"] for tool in parsed_tools], ["read_file", "execute_command"])

    def test_fenced_xml_tool_block_executes_tools_instead_of_malformed_rewrite(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            "I will inspect the likely target now.\n\n"
            "```xml\n"
            '<read_file path="engine/model_manager.py" />\n'
            '<execute_command command="python -m py_compile engine/model_manager.py" cwd="." />\n'
            "```"
        )
        panel._guided_takeoff_stage = 2

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_ai_finished()

        mock_restart.assert_not_called()
        mock_tools.assert_called_once()
        parsed_tools = mock_tools.call_args.args[0]
        self.assertEqual([tool["cmd"] for tool in parsed_tools], ["read_file", "execute_command"])

    def test_tool_code_fenced_tool_block_executes_tools_instead_of_malformed_rewrite(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            "Continuing with the next step.\n\n"
            "```tool_code\n"
            '<read_file path="requirements.txt" />\n'
            "```"
        )
        panel._guided_takeoff_stage = 2

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_ai_finished()

        mock_restart.assert_not_called()
        mock_tools.assert_called_once()
        parsed_tools = mock_tools.call_args.args[0]
        self.assertEqual([tool["cmd"] for tool in parsed_tools], ["read_file"])

    def test_single_quoted_fenced_tool_block_executes_tools(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            "Continuing with a focused edit.\n\n"
            "```xml\n"
            "<edit_file path='requirements.txt' old_text='numpy<2' new_text='numpy<2.0' />\n"
            "```"
        )
        panel._guided_takeoff_stage = 2

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_ai_finished()

        mock_restart.assert_not_called()
        mock_tools.assert_called_once()
        parsed_tools = mock_tools.call_args.args[0]
        self.assertEqual([tool["cmd"] for tool in parsed_tools], ["edit_file"])
        self.assertEqual(parsed_tools[0]["args"]["path"], "requirements.txt")

    def test_square_bracket_tool_lines_execute_tools(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            "I'll verify the import issue directly.\n\n"
            "[execute_command command=\"python -m py_compile app/main_gui.py\" cwd=\".\"]\n"
            "[read_file path='requirements.txt']"
        )
        panel._guided_takeoff_stage = 2

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_ai_finished()

        mock_restart.assert_not_called()
        mock_tools.assert_called_once()
        parsed_tools = mock_tools.call_args.args[0]
        self.assertEqual([tool["cmd"] for tool in parsed_tools], ["execute_command", "read_file"])

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
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_tool_finished(output)
            first_msgs = mock_restart.call_args.kwargs.get('extra_system_messages') or []
            panel.handle_tool_finished(output)
            second_msgs = mock_restart.call_args.kwargs.get('extra_system_messages') or []

        self.assertIn("GUIDED RECOVERY — PICK A TARGET NOW", "\n".join(first_msgs))
        self.assertIn("valid tool XML only", "\n".join(first_msgs))
        self.assertIn("GUIDED RECOVERY — STOP RE-INVESTIGATING", "\n".join(second_msgs))
        self.assertIn("valid tool XML only", "\n".join(second_msgs))

    def test_guided_recovery_forces_same_target_fix_once_target_exists(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._guided_autonomy_unlocked = False
        panel._guided_phase_anchor = "Finding 1 points to engine/hardware_check.py as the best-supported target."
        panel._tool_calls_for_run = ["read_file"]
        panel._tool_action_log = ["Read file: engine/hardware_check.py -> Done"]
        panel._run_tool_action_log = list(panel._tool_action_log)
        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- none\n"
            "Other successful actions:\n"
            "- read engine/hardware_check.py\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]"
        )

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_tool_finished(output)
            first_msgs = mock_restart.call_args.kwargs.get('extra_system_messages') or []
            panel.handle_tool_finished(output)
            second_msgs = mock_restart.call_args.kwargs.get('extra_system_messages') or []

        self.assertIn("GUIDED RECOVERY — STAY ON THIS TARGET", "\n".join(first_msgs))
        self.assertIn("engine/hardware_check.py", "\n".join(first_msgs))
        self.assertIn("GUIDED RECOVERY — EDIT OR STOP ON THIS TARGET", "\n".join(second_msgs))
        self.assertIn("single smallest same-target edit attempt", "\n".join(second_msgs))

    def test_guided_recovery_blocks_reinspection_after_same_target_probe_used(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._guided_autonomy_unlocked = False
        panel._guided_same_target_probe_count = 1
        panel._guided_phase_anchor = "Finding 1 points to engine/hardware_check.py as the best-supported target."
        panel._tool_calls_for_run = ["read_file"]
        panel._tool_action_log = ["Read file: engine/hardware_check.py -> Done"]
        panel._run_tool_action_log = list(panel._tool_action_log)
        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- none\n"
            "Other successful actions:\n"
            "- read engine/hardware_check.py\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]"
        )

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch.object(panel, 'append_message_widget'):
            panel.handle_tool_finished(output)
            msgs = mock_restart.call_args.kwargs.get('extra_system_messages') or []

        combined = "\n".join(msgs)
        self.assertIn("GUIDED RECOVERY — EDIT OR STOP ON THIS TARGET", combined)
        self.assertIn("Do NOT emit another read/search-only batch", combined)

    def test_handle_tool_finished_launches_same_target_probe_after_targeted_stall(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel._guided_takeoff_stage = 2
        panel._guided_phase_anchor = "Finding 1 points to engine/hardware_check.py as the best-supported target."
        panel._tool_calls_for_run = ["search_files"]
        panel._tool_specs_for_run = [{"cmd": "search_files", "args": {"query": "hardware"}}]
        panel._tool_action_log = ["Search files: hardware -> Done"]
        panel._run_tool_action_log = list(panel._tool_action_log)
        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- none\n"
            "Other successful actions:\n"
            "- search hardware\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]"
        )

        with patch.object(panel, 'append_message_widget') as mock_append, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_ai:
            panel.handle_tool_finished(output)

        mock_ai.assert_not_called()
        mock_tools.assert_called_once_with([
            {"cmd": "read_file", "args": {"path": "engine/hardware_check.py"}},
        ])
        self.assertEqual(panel._guided_same_target_probe_count, 1)
        self.assertEqual(panel.messages[-1]["role"], "system")
        self.assertIn("same-target read", panel.messages[-1]["content"])
        self.assertEqual(mock_append.call_count, 2)

    def test_analysis_only_target_known_launches_same_target_probe_before_rewrite(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "The best-supported issue is in engine/hardware_check.py, but I want to inspect more before editing."
        panel._guided_takeoff_stage = 2
        panel._guided_phase_anchor = "Finding 1 points to engine/hardware_check.py as the best-supported target."

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_ai, \
             patch.object(panel, 'save_conversation'):
            panel.handle_ai_finished()

        mock_ai.assert_not_called()
        mock_tools.assert_called_once_with([
            {"cmd": "read_file", "args": {"path": "engine/hardware_check.py"}},
        ])
        self.assertEqual(panel._guided_same_target_probe_count, 1)

    def test_drifting_tool_batch_is_replaced_with_same_target_probe_before_rewrite(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = '<search_files query="hardware" />'
        panel._guided_takeoff_stage = 2
        panel._guided_no_progress_cycles = 1
        panel._guided_phase_anchor = "Finding 1 points to engine/hardware_check.py as the best-supported target."

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_ai, \
             patch.object(panel, 'save_conversation'):
            panel.handle_ai_finished()

        mock_ai.assert_not_called()
        mock_tools.assert_called_once_with([
            {"cmd": "read_file", "args": {"path": "engine/hardware_check.py"}},
        ])
        self.assertEqual(panel._guided_same_target_probe_count, 1)

    def test_guided_recovery_focuses_validation_after_successful_edit(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._guided_autonomy_unlocked = False
        panel._auto_validation_retry_count = 1
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
        self.assertIn("valid tool XML only", combined)
        self.assertIn("Validate the latest successful edit", combined)

    def test_guided_recovery_requires_missing_project_start_deliverables_after_partial_success(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = [{
            "role": "user",
            "content": (
                "This folder is empty. Start a very small new Python project here. "
                "Create only the minimum files needed for a basic runnable CLI starter: "
                "app.py that prints a short greeting, plus a short README.md with run instructions. "
                "Then validate it by running python app.py. Keep the project tiny and grounded."
            ),
        }]
        panel._guided_task_board_goal = panel.messages[0]["content"]
        panel._guided_takeoff_stage = 2
        panel._guided_autonomy_unlocked = False
        panel._guided_successful_edit_seen = True
        panel._tool_calls_for_run = ["execute_command", "read_file"]
        panel._session_change_log = [{
            "file_path": "app.py",
            "display_path": "app.py",
            "diff_preview": "+ print('hello')",
            "diff_text": "@@\n+print('hello')",
        }]
        panel._run_tool_action_log = [
            "Wrote app.py -> Done",
            "Executed: python -m py_compile app.py -> Done",
            "Read file: app.py -> Done",
        ]
        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- app.py\n"
            "Other successful actions:\n"
            "- python -m py_compile app.py\n"
            "- read app.py\n"
            "Failed actions:\n"
            "- none\n"
            "[/ACTION_SUMMARY]"
        )

        prompt = panel._guided_recovery_prompt(output)

        self.assertIsNotNone(prompt)
        self.assertIn("GUIDED COMPLETION GATE", prompt)
        self.assertIn("README.md", prompt)
        self.assertIn("python app.py", prompt)

    def test_successful_edit_without_validation_does_not_unlock_guided_autonomy(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._guided_autonomy_unlocked = False
        panel._auto_validation_retry_count = 1
        panel._tool_calls_for_run = ["write_file"]
        panel._tool_specs_for_run = [{"cmd": "write_file", "args": {"path": "app.py"}}]
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

        self.assertFalse(panel._guided_autonomy_unlocked)
        self.assertEqual(panel._guided_takeoff_stage, 2)
        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED RECOVERY — FOCUS THE CURRENT FIX CYCLE", combined)
        self.assertIn("The latest tool cycle did NOT run any successful validation command", combined)

    def test_validation_hint_prefers_recently_changed_file_over_phase_anchor(self):
        panel = self._panel()
        panel._guided_phase_anchor = "Finding 1 references hardware_config.json as a likely target."
        panel._tool_action_log = ["Wrote requirements.txt -> Done"]
        panel._run_tool_action_log = list(panel._tool_action_log)

        hint = panel._guided_validation_hint_text()

        self.assertIn(ChatPanel._text_validation_command("requirements.txt"), hint)
        self.assertIn("read_file path=\"requirements.txt\"", hint)

    def test_validation_hint_prefers_actual_recent_edit_target_before_other_hints(self):
        panel = self._panel()
        panel._guided_phase_anchor = "Finding 1 references app.py as a possible entry point."
        panel._tool_specs_for_run = [{"cmd": "write_file", "args": {"path": "run_zluda.bat"}}]
        panel._tool_action_log = ["Wrote run_zluda.bat -> Done"]
        panel._run_tool_action_log = list(panel._tool_action_log)

        hint = panel._guided_validation_hint_text()

        self.assertIn(ChatPanel._text_validation_command("run_zluda.bat"), hint)
        self.assertIn('read_file path="run_zluda.bat"', hint)

    def test_validation_hint_prefers_exact_project_start_run_command(self):
        panel = self._panel()
        panel.messages = [{
            "role": "user",
            "content": (
                "This folder is empty. Start a very small new Python project here. "
                "Create only the minimum files needed for a basic runnable CLI starter: "
                "app.py that prints a short greeting, plus a short README.md with run instructions. "
                "Then validate it by running python app.py. Keep the project tiny and grounded."
            ),
        }]
        panel._guided_task_board_goal = panel.messages[0]["content"]
        panel._session_change_log = [{
            "file_path": "app.py",
            "display_path": "app.py",
            "diff_preview": "+ print('hello')",
            "diff_text": "@@\n+print('hello')",
        }, {
            "file_path": "README.md",
            "display_path": "README.md",
            "diff_preview": "+ Run python app.py",
            "diff_text": "@@\n+Run python app.py",
        }]
        panel._tool_specs_for_run = [{"cmd": "write_file", "args": {"path": "README.md"}}]
        panel._tool_action_log = ["Wrote README.md -> Done"]
        panel._run_tool_action_log = list(panel._tool_action_log)

        hint = panel._guided_validation_hint_text()

        self.assertIn('execute_command command="python app.py"', hint)
        self.assertNotIn('python -m py_compile', hint)

    def test_handle_tool_finished_skips_auto_validation_when_project_start_missing_files(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel.messages = [{
            "role": "user",
            "content": (
                "This folder is empty. Start a very small new Python project here. "
                "Create only the minimum files needed for a basic runnable CLI starter: "
                "app.py that prints a short greeting, plus a short README.md with run instructions. "
                "Then validate it by running python app.py. Keep the project tiny and grounded."
            ),
        }]
        panel._guided_task_board_goal = panel.messages[0]["content"]
        panel.current_ai_item = MagicMock()
        panel._tool_calls_for_run = ["write_file"]
        panel._tool_specs_for_run = [{"cmd": "write_file", "args": {"path": "app.py"}}]
        panel._tool_action_log = ["Wrote app.py -> Done"]
        panel._run_tool_action_log = list(panel._tool_action_log)
        tool_output = (
            "ACTION_SUMMARY:\n"
            "Successful file changes:\n"
            "- write_file: app.py\n"
            "Other successful actions:\n"
            "- none\n"
            "Failed actions:\n"
            "- none\n"
        )

        with patch.object(panel, 'append_message_widget') as mock_append, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_ai:
            panel.handle_tool_finished(tool_output)

        mock_tools.assert_not_called()
        mock_ai.assert_called_once()
        combined = "\n".join(mock_ai.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED COMPLETION GATE", combined)
        self.assertIn("README.md", combined)
        self.assertIn("python app.py", combined)
        self.assertGreaterEqual(mock_append.call_count, 1)

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

    def test_guided_recovery_after_exact_match_failure_stays_on_same_target(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._guided_takeoff_stage = 2
        panel._guided_autonomy_unlocked = False
        panel._tool_calls_for_run = ["edit_file"]
        panel._tool_specs_for_run = [{"cmd": "edit_file", "args": {"path": "engine/hardware_check.py"}}]
        panel._tool_action_log = ["Edited engine/hardware_check.py -> Failed"]
        panel._run_tool_action_log = list(panel._tool_action_log)
        output = (
            "[ACTION_SUMMARY]\n"
            "Successful file changes:\n"
            "- none\n"
            "Other successful actions:\n"
            "- none\n"
            "Failed actions:\n"
            "- edit_file engine/hardware_check.py: [Error: old_text not found in engine/hardware_check.py. Make sure the text matches exactly (including whitespace).]\n"
            "[/ACTION_SUMMARY]"
        )

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, 'append_message_widget'):
            panel.handle_tool_finished(output)

        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED RECOVERY — THE LAST EDIT WAS A NO-OP", combined)
        self.assertIn("exact block was not found", combined)
        self.assertIn('write_file path="engine/hardware_check.py"', combined)
        self.assertEqual(panel._guided_exact_match_retry_targets, ["engine/hardware_check.py"])

    def test_exact_match_failure_blocks_broad_search_and_demands_same_target_recovery(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = '<search_files query="hardware" root_dir="." file_pattern="*.py" />'
        panel._guided_takeoff_stage = 2
        panel._guided_exact_match_retry_targets = ["engine/hardware_check.py"]
        panel._pending_summary_guard_flags = {"no_file_changes"}

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        combined = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED DECISION GATE — RESOLVE THE FAILED EDIT NOW", combined)
        self.assertIn("engine/hardware_check.py", combined)
        self.assertIn('write_file path="engine/hardware_check.py"', combined)

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
        extra_msgs = mock_restart.call_args.kwargs.get('extra_system_messages')
        self.assertGreaterEqual(len(extra_msgs), 1)
        self.assertIn("Exact files successfully changed in the latest tool cycle: app.py", "\n".join(extra_msgs))

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

    def test_blank_final_response_after_retry_requests_guided_rewrite(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "   "
        panel._empty_ai_retry_count = 1
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = False
        panel._pending_summary_guard_flags = {"no_file_changes"}
        panel._pending_summary_guard_message = "REALITY CHECK BEFORE YOU RESPOND TO THE USER:\n- no changes"

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        mock_restart.assert_called_once()
        self.assertEqual(panel.messages, [])
        self.assertEqual(panel._guided_blank_response_retry_count, 1)
        self.assertIn("Do NOT leave this turn empty", mock_restart.call_args.args[0])

    def test_blank_final_response_in_stage_one_launches_minimal_probe(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = [{"role": "user", "content": "Fix the startup issue."}]
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "   "
        panel._empty_ai_retry_count = 1
        panel._guided_takeoff_stage = 1
        panel._guided_direct_change_requested = True

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, 'append_message_widget'), \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, '_start_ai_worker') as mock_restart:
            panel.handle_ai_finished()

        mock_restart.assert_not_called()
        mock_tools.assert_called_once_with([{'cmd': 'list_files', 'args': {'path': '.'}}])
        self.assertEqual(panel._guided_bounded_start_probe_count, 1)

    def test_first_blank_response_in_stage_one_immediately_launches_minimal_probe(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = [{"role": "user", "content": "Fix the startup issue."}]
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "   "
        panel._guided_takeoff_stage = 1
        panel._guided_direct_change_requested = True

        with patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, 'append_message_widget'), \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, '_start_ai_worker') as mock_restart:
            panel.handle_ai_finished()

        mock_restart.assert_not_called()
        mock_tools.assert_called_once_with([{'cmd': 'list_files', 'args': {'path': '.'}}])
        self.assertEqual(panel._guided_bounded_start_probe_count, 1)

    def test_second_guided_blank_final_falls_back_to_grounded_blocker(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "   "
        panel._empty_ai_retry_count = 1
        panel._guided_blank_response_retry_count = 1
        panel._guided_takeoff_stage = 2

        with patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, '_start_ai_worker') as mock_restart:
            panel.handle_ai_finished()

        mock_restart.assert_not_called()
        self.assertEqual(panel.messages[-1]["role"], "assistant")
        self.assertIn("Guided takeoff paused here", panel.messages[-1]["content"])

    def test_summary_guard_rewrites_raw_tool_protocol_in_final_answer(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = [{"role": "system", "content": "[TOOL_RESULT]\nEdited app.py"}]
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = 'Done. <tool_call cmd="read_file" path="app.py">'
        panel._guided_takeoff_stage = 3
        panel._guided_successful_edit_seen = True
        panel._pending_summary_grounded_files = ["app.py"]
        panel._pending_summary_guard_message = "REALITY CHECK BEFORE YOU RESPOND TO THE USER:\n- grounded file: app.py"

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        mock_restart.assert_called_once()
        self.assertEqual(panel.messages, [{"role": "system", "content": "[TOOL_RESULT]\nEdited app.py"}])
        self.assertEqual(panel._summary_guard_retry_count, 1)
        self.assertIn("Do not output raw or malformed tool XML/protocol", mock_restart.call_args.args[0])

    def test_summary_guard_rewrites_blank_placeholder_final_answer(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = [{"role": "system", "content": "[TOOL_RESULT]\nEdited app.py"}]
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "[No response received from the model. The request completed without visible content. Please retry.]"
        panel._guided_takeoff_stage = 3
        panel._guided_successful_edit_seen = True
        panel._pending_summary_grounded_files = ["app.py"]
        panel._pending_summary_guard_message = "REALITY CHECK BEFORE YOU RESPOND TO THE USER:\n- grounded file: app.py"

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        mock_restart.assert_called_once()
        self.assertEqual(panel.messages, [{"role": "system", "content": "[TOOL_RESULT]\nEdited app.py"}])
        self.assertEqual(panel._summary_guard_retry_count, 1)
        self.assertIn("blank-response placeholder", mock_restart.call_args.args[0])

    def test_pause_agent_rewrites_trailing_tool_protocol_assistant_message(self):
        panel = self._panel()
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = '<read_file path="app.py" />'
        panel.messages = [{"role": "assistant", "content": '<read_file path="app.py" />'}]
        panel._pending_summary_grounded_files = ["app.py"]

        with patch.object(panel, 'append_message_widget') as mock_append:
            panel._pause_agent("Agent Loop Guard", "[Loop guard paused the agent after 12 tool cycle(s). Send a new message when you want it to continue.]")

        self.assertIn("Paused before executing another tool-only turn", panel.messages[-1]["content"])
        self.assertIn("app.py", panel.messages[-1]["content"])
        panel.current_ai_item.set_text.assert_called()
        mock_append.assert_called_once()

    def test_summary_guard_rewrites_overlong_success_summary_into_compact_grounded_reply(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = [{"role": "system", "content": "[TOOL_RESULT]\nEdited app.py and README.md"}]
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            "What I changed and why:\n"
            "- Created app.py as the smallest possible runnable CLI starter.\n"
            "- Created README.md with run instructions.\n\n"
            "Key results:\n"
            "- Validation succeeded by running python app.py.\n"
            "- Output matched expectations.\n\n"
            "What you should know next:\n"
            "- The project is ready to run as-is.\n"
            "- If you want, the next smallest enhancement would be adding a main() wrapper."
        )
        panel._guided_takeoff_stage = 3
        panel._guided_successful_edit_seen = True
        panel._pending_summary_guard_flags = set()
        panel._pending_summary_grounded_files = ["app.py", "README.md"]
        panel._pending_summary_guard_message = "GROUNDED FILE-CHANGE SNAPSHOT:\n- Exact files successfully changed in the latest tool cycle: app.py, README.md"

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        mock_restart.assert_called_once()
        self.assertEqual(panel.messages, [{"role": "system", "content": "[TOOL_RESULT]\nEdited app.py and README.md"}])
        self.assertEqual(panel._summary_guard_retry_count, 1)
        self.assertIn("too long", mock_restart.call_args.args[0])
        self.assertIn("maximum 2 short bullets or 3 very short lines total", mock_restart.call_args.args[0])

    def test_handle_tool_finished_adds_compact_summary_format_guidance(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel._tool_calls_for_run = ["write_file", "execute_command", "read_file"]
        panel._tool_action_log = [
            "Wrote app.py -> Done",
            "Executed: python app.py -> Done",
            "Read file: app.py -> Done",
        ]
        panel._run_tool_action_log = list(panel._tool_action_log)
        output = (
            "ACTION_SUMMARY:\n"
            "Successful file changes:\n"
            "- write_file: app.py\n"
            "Other successful actions:\n"
            "- execute_command: python app.py\n"
            "- read_file: app.py\n"
            "Failed actions:\n"
            "- none\n"
        )

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel, 'append_message_widget'):
            panel.handle_tool_finished(output)

        extra_msgs = mock_restart.call_args.kwargs.get('extra_system_messages') or []
        combined = "\n".join(extra_msgs)
        self.assertIn("FINAL RESPONSE FORMAT FOR THIS TURN", combined)
        self.assertIn("at most 2 short bullets or 3 very short lines total", combined)
        self.assertIn("app.py", combined)

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

    def test_summary_guard_rewrites_fabricated_action_log_without_grounded_changes(self):
        panel = self._panel()
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            "**ACTION LOG:**\n"
            "1. Creating initial application (`app.py`)\n"
            "2. Executing `python app.py`\n"
            "3. Applying the fix and verifying the result\n\n"
            "**FINAL SUMMARY:** The application is now fully functional."
        )
        panel._pending_summary_guard_flags = {"no_file_changes", "no_validation", "no_post_edit_rescan"}
        panel._pending_summary_guard_message = "REALITY CHECK BEFORE YOU RESPOND TO THE USER:\n- no changes"

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        mock_restart.assert_called_once()
        self.assertEqual(panel._summary_guard_retry_count, 1)
        self.assertEqual(mock_restart.call_args.kwargs.get('extra_system_messages'), [panel._pending_summary_guard_message])

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

    def test_grounded_changed_files_extract_exact_paths_from_action_summary(self):
        tool_output = (
            "ACTION_SUMMARY:\n"
            "Successful file changes:\n"
            "- edit_file: engine/logging_utils.py\n"
            "- core\\old_name.py -> core\\new_name.py\n"
            "Other successful actions:\n"
            "- execute_command: python -m py_compile engine/logging_utils.py\n"
            "Failed actions:\n"
            "- none\n"
        )

        self.assertEqual(
            ChatPanel._grounded_changed_files_from_summary(tool_output),
            ["engine/logging_utils.py", "core/old_name.py", "core/new_name.py"],
        )

    def test_wrong_changed_file_summary_is_blocked_before_reaching_user(self):
        panel = self._panel()
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I updated requirements.txt and verified the change."
        panel._pending_summary_guard_message = "REALITY CHECK BEFORE YOU RESPOND TO THE USER:\n- use only grounded file paths"
        panel._pending_summary_grounded_files = ["engine/logging_utils.py"]

        with patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        self.assertEqual(panel.messages, [])
        mock_restart.assert_called_once()
        self.assertEqual(panel._summary_guard_retry_count, 1)
        extra_msgs = mock_restart.call_args.kwargs.get('extra_system_messages')
        self.assertEqual(extra_msgs, [panel._pending_summary_guard_message])

    def test_summary_guard_allows_file_grounded_earlier_in_same_run(self):
        panel = self._panel()
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I updated app.py earlier in the run, then added README.md."
        panel._pending_summary_guard_message = "REALITY CHECK BEFORE YOU RESPOND TO THE USER:\n- use only grounded file paths"
        panel._pending_summary_grounded_files = ["README.md"]
        panel._session_change_log = [{
            "file_path": "app.py",
            "display_path": "app.py",
            "diff_preview": "+ print('hello')",
            "diff_text": "@@\n+print('hello')",
        }]

        with patch.object(panel, 'save_conversation'), \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch.object(panel, '_start_ai_worker') as mock_restart:
            panel.handle_ai_finished()

        mock_restart.assert_not_called()
        self.assertEqual(panel.messages[-1]["role"], "assistant")
        self.assertIn("app.py", panel.messages[-1]["content"])

    def test_premature_post_edit_summary_triggers_auto_validation_batch(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I updated engine/logging_utils.py and the fix should be complete."
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._pending_summary_guard_flags = {"no_post_edit_validation", "no_post_edit_rescan"}
        panel._pending_summary_grounded_files = ["engine/logging_utils.py"]
        panel._tool_specs_for_run = [{"cmd": "edit_file", "args": {"path": "engine/logging_utils.py"}}]

        with patch.object(panel, 'append_message_widget') as mock_append, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel, '_start_tool_execution') as mock_tools:
            panel.handle_ai_finished()

        mock_tools.assert_called_once_with([
            {"cmd": "execute_command", "args": {"command": 'python -m py_compile "engine/logging_utils.py"', "cwd": "."}},
            {"cmd": "read_file", "args": {"path": "engine/logging_utils.py"}},
        ])
        mock_append.assert_called_once()
        self.assertEqual(panel.messages[-1]["role"], "system")
        self.assertIn("Auto-recovery launched a compact post-edit verification batch", panel.messages[-1]["content"])
        self.assertEqual(panel._auto_validation_retry_count, 1)

    def test_handle_tool_finished_immediately_runs_auto_validation_after_edit(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel._tool_calls_for_run = ["edit_file"]
        panel._tool_specs_for_run = [{"cmd": "edit_file", "args": {"path": "engine/logging_utils.py"}}]
        panel._tool_action_log = ["Edited engine/logging_utils.py -> Done"]
        panel._run_tool_action_log = list(panel._tool_action_log)
        tool_output = (
            "ACTION_SUMMARY:\n"
            "Successful file changes:\n"
            "- edit_file: engine/logging_utils.py\n"
            "Other successful actions:\n"
            "- none\n"
            "Failed actions:\n"
            "- none\n"
        )

        with patch.object(panel, 'append_message_widget') as mock_append, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_ai:
            panel.handle_tool_finished(tool_output)

        mock_ai.assert_not_called()
        mock_tools.assert_called_once_with([
            {"cmd": "execute_command", "args": {"command": 'python -m py_compile "engine/logging_utils.py"', "cwd": "."}},
            {"cmd": "read_file", "args": {"path": "engine/logging_utils.py"}},
        ])
        self.assertEqual(panel._pending_summary_grounded_files, ["engine/logging_utils.py"])
        self.assertEqual(panel._auto_validation_retry_count, 1)
        self.assertEqual(mock_append.call_count, 2)

    def test_handle_tool_finished_does_not_auto_rerun_failed_validation(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._tool_calls_for_run = ["edit_file", "execute_command"]
        panel._tool_specs_for_run = [{"cmd": "edit_file", "args": {"path": "engine/game_logic.py"}}]
        panel._tool_action_log = [
            "Edited engine/game_logic.py -> Done",
            "Executed: python -m pytest -q -> Failed",
        ]
        panel._run_tool_action_log = list(panel._tool_action_log)
        tool_output = (
            "ACTION_SUMMARY:\n"
            "Successful file changes:\n"
            "- edit_file: engine/game_logic.py\n"
            "Other successful actions:\n"
            "- none\n"
            "Failed actions:\n"
            "- execute_command python -m pytest -q: exit code 1\n"
        )

        with patch.object(panel, 'append_message_widget') as mock_append, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_ai:
            panel.handle_tool_finished(tool_output)

        mock_tools.assert_not_called()
        mock_ai.assert_called_once()
        extra = "\n".join(mock_ai.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED RECOVERY — THE LATEST VALIDATION FAILED", extra)
        self.assertIn("python -m pytest -q", extra)
        self.assertIn("engine/game_logic.py", extra)
        self.assertEqual(panel._auto_validation_retry_count, 0)
        self.assertGreaterEqual(mock_append.call_count, 1)

    def test_handle_tool_finished_uses_requested_project_start_run_command_for_auto_validation(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = [{
            "role": "user",
            "content": (
                "This folder is empty. Start a very small new Python project here. "
                "Create only the minimum files needed for a basic runnable CLI starter: "
                "app.py that prints a short greeting, plus a short README.md with run instructions. "
                "Then validate it by running python app.py. Keep the project tiny and grounded."
            ),
        }]
        panel._guided_task_board_goal = panel.messages[0]["content"]
        panel.current_ai_item = MagicMock()
        panel._tool_calls_for_run = ["write_file", "write_file"]
        panel._tool_specs_for_run = [{"cmd": "write_file", "args": {"path": "README.md"}}]
        panel._tool_action_log = ["Wrote app.py -> Done", "Wrote README.md -> Done"]
        panel._run_tool_action_log = list(panel._tool_action_log)
        tool_output = (
            "ACTION_SUMMARY:\n"
            "Successful file changes:\n"
            "- write_file: app.py\n"
            "- write_file: README.md\n"
            "Other successful actions:\n"
            "- none\n"
            "Failed actions:\n"
            "- none\n"
        )

        with patch.object(panel, 'append_message_widget') as mock_append, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_ai:
            panel.handle_tool_finished(tool_output)

        mock_ai.assert_not_called()
        mock_tools.assert_called_once_with([
            {"cmd": "execute_command", "args": {"command": "python app.py", "cwd": "."}},
            {"cmd": "read_file", "args": {"path": "app.py"}},
        ])
        self.assertEqual(panel._auto_validation_retry_count, 1)
        self.assertGreaterEqual(mock_append.call_count, 2)

    def test_project_start_premature_summary_goes_straight_to_completion_gate(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = [{
            "role": "user",
            "content": (
                "This folder is empty. Start a very small new Python project here. "
                "Create only the minimum files needed for a basic runnable CLI starter: "
                "app.py that prints a short greeting, plus a short README.md with run instructions. "
                "Then validate it by running python app.py. Keep the project tiny and grounded."
            ),
        }]
        panel._guided_task_board_goal = panel.messages[0]["content"]
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = "I created app.py and the starter is finished."
        panel._guided_takeoff_stage = 2
        panel._guided_successful_edit_seen = True
        panel._pending_summary_guard_flags = {"no_post_edit_validation", "no_post_edit_rescan"}
        panel._pending_summary_grounded_files = ["app.py"]
        panel._tool_specs_for_run = [{"cmd": "write_file", "args": {"path": "app.py"}}]
        panel._tool_action_log = ["Wrote app.py -> Done"]
        panel._run_tool_action_log = list(panel._tool_action_log)

        with patch.object(panel, 'append_message_widget'), \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_ai, \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        mock_tools.assert_not_called()
        mock_ai.assert_called_once()
        extra = "\n".join(mock_ai.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("GUIDED COMPLETION GATE", extra)
        self.assertIn("README.md", extra)
        self.assertIn("python app.py", extra)

    def test_handle_ai_finished_allows_second_retry_for_current_task_gate(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            "Phase 1 Inspection Complete — No files changed.\n\n"
            "Finding 1: Ball.reset uses math.random().\n"
            "Evidence: game_logic.py line 27 uses math.random().\n"
            "Recommended next step: fix the bug and add countdown state."
        )
        panel._guided_takeoff_stage = 2
        panel._guided_decision_retry_count = 1
        panel._guided_task_board = [
            {"id": "inspect", "title": "Inspect the current game files", "status": "complete"},
            {"id": "polish", "title": "Fix bugs and add countdown, speedup, HUD state to game_logic.py", "status": "current"},
            {"id": "validate", "title": "Rerun pytest and self-test", "status": "pending"},
        ]
        panel._guided_task_board_source = "llm"

        with patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
             patch.object(panel, '_start_ai_worker') as mock_restart, \
             patch.object(panel.rag_client, 'ingest_message'), \
             patch('ui.chat_panel.QTimer.singleShot', side_effect=lambda _ms, fn: fn()):
            panel.handle_ai_finished()

        mock_restart.assert_called_once()
        self.assertEqual(panel._guided_decision_retry_count, 2)
        self.assertIn("did not advance your own CURRENT task", mock_restart.call_args.args[0])
        extra = "\n".join(mock_restart.call_args.kwargs.get('extra_system_messages') or [])
        self.assertIn("DO NOT END THIS PHASE ON INSPECTION ONLY", extra)

    def test_handle_tool_finished_uses_shell_safe_text_auto_validation_after_report_edit(self):
        panel = self._panel()
        panel.mode_combo.setCurrentText("Siege")
        panel.messages = []
        panel.current_ai_item = MagicMock()
        panel._tool_calls_for_run = ["write_file"]
        panel._tool_specs_for_run = [{"cmd": "write_file", "args": {"path": "benchmark_report.md"}}]
        panel._tool_action_log = ["Wrote benchmark_report.md -> Done"]
        panel._run_tool_action_log = list(panel._tool_action_log)
        tool_output = (
            "ACTION_SUMMARY:\n"
            "Successful file changes:\n"
            "- write_file: benchmark_report.md\n"
            "Other successful actions:\n"
            "- none\n"
            "Failed actions:\n"
            "- none\n"
        )

        with patch.object(panel, 'append_message_widget') as mock_append, \
             patch.object(panel, 'save_conversation'), \
             patch.object(panel, '_start_tool_execution') as mock_tools, \
             patch.object(panel, '_start_ai_worker') as mock_ai:
            panel.handle_tool_finished(tool_output)

        mock_ai.assert_not_called()
        mock_tools.assert_called_once_with([
            {"cmd": "execute_command", "args": {"command": ChatPanel._text_validation_command("benchmark_report.md"), "cwd": "."}},
            {"cmd": "read_file", "args": {"path": "benchmark_report.md"}},
        ])
        self.assertEqual(panel._pending_summary_grounded_files, ["benchmark_report.md"])
        self.assertEqual(panel._auto_validation_retry_count, 1)
        self.assertEqual(mock_append.call_count, 2)

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

    def test_ai_error_response_is_saved_to_messages_and_notified(self):
        panel = self._panel()
        panel.current_ai_item = MagicMock()
        panel.current_ai_response = (
            "[Error: Google Gemini request temporarily unavailable for model 'gemini-pro-latest' (503).\n"
            "Provider said: The model is overloaded due to high demand. Please try again later.]"
        )
        notifications = []
        panel.notification_requested.connect(lambda title, message: notifications.append((title, message)))

        with patch.object(panel, 'save_conversation') as mock_save, \
             patch.object(panel.rag_client, 'ingest_message') as mock_ingest:
            panel.handle_ai_finished()

        self.assertEqual(panel.messages[-1]['role'], 'assistant')
        self.assertIn('temporarily unavailable', panel.messages[-1]['content'])
        mock_save.assert_called_once()
        mock_ingest.assert_not_called()
        self.assertEqual(notifications[0][0], 'AI Provider Error')
        self.assertIn('high demand', notifications[0][1])

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

    def test_prepare_selected_model_for_send_switches_quarantined_route_before_run(self):
        panel = self._panel()
        panel.model_combo.clear()
        panel.model_combo.addItem("gemini-pro-latest", "[Google Gemini] gemini-pro-latest")
        panel.model_combo.setCurrentIndex(0)
        panel.settings_manager.get_selected_model = MagicMock(return_value="[Google Gemini] gemini-pro-latest")
        panel.settings_manager.get_enabled_models = MagicMock(return_value=[
            "[Google Gemini] gemini-pro-latest",
            SettingsManager.DEFAULT_BENCHMARK_MODEL,
        ])
        panel.settings_manager.get_api_key = MagicMock(return_value="dummy_key")
        panel.settings_manager.get_show_unstable_models = MagicMock(return_value=False)

        emitted = []
        panel.notification_requested.connect(lambda title, message: emitted.append((title, message)))

        ready, blocked_reason = panel._prepare_selected_model_for_send(run_probe=False)

        self.assertTrue(ready)
        self.assertEqual(blocked_reason, "")
        self.assertEqual(panel._get_full_model_name(), SettingsManager.DEFAULT_BENCHMARK_MODEL)
        self.assertTrue(any(title == "Model Safety Gate" and "Switched" in message for title, message in emitted))
        panel.close()

    def test_move_file_requires_confirmation(self):
        worker = ToolWorker([
            {"cmd": "move_file", "args": {"src": "old.py", "dst": "new.py"}},
        ], auto_approve=False)
        worker.settings.get_advanced_agent_tools_enabled = MagicMock(return_value=True)

        with patch.object(ToolWorker, '_request_approval', return_value=False) as mock_approval, \
             patch('ui.chat_panel.AgentToolHandler.move_file') as mock_move:
            worker.run()

        mock_approval.assert_called_once()
        mock_move.assert_not_called()

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
                lambda _messages: f'<read_file path="{app_file}" start_line="1" end_line="40" />',
                lambda messages: (
                    "I created a blank project, observed the runtime failure, fixed it, reran it successfully, and the Siege flow completed cleanly."
                    if any("hello from siege" in str(m.get("content", "")) for m in messages if m.get("role") == "system")
                    else "The rerun did not succeed as expected."
                ),
            ])

            try:
                with patch.object(panel, 'save_conversation'), \
                     patch.object(panel.rag_client, 'ingest_message'), \
                     patch.object(panel, '_launch_guided_auto_validation_batch', return_value=False):
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
                self.assertEqual(panel.tool_loop_count, 5)
                self.assertFalse(any(title == "Approval Needed" for title, _ in notifications))
            finally:
                panel.close()

    def test_siege_mode_project_start_does_not_stop_before_missing_readme_and_run(self):
        with self._blank_project() as project_dir:
            panel = self._panel(project_root=project_dir)
            panel.mode_combo.setCurrentText("Siege")
            panel.model_combo.clear()
            panel.model_combo.addItem("scripted-agent", "[Test] scripted-agent")
            panel.model_combo.setCurrentIndex(0)
            panel.on_model_changed("scripted-agent")

            app_file = f"{project_dir}/app.py"
            readme_file = f"{project_dir}/README.md"
            AIClient.configure_test_provider([
                '<write_file path="app.py">\nprint("Hello from starter")\n</write_file>',
                'I created app.py and the starter is finished.',
                lambda messages: (
                    '<write_file path="README.md">\n# Tiny Starter\n\nRun `python app.py`.\n</write_file>\n'
                    f'<execute_command command="python app.py" cwd="{project_dir}" />\n'
                    '<read_file path="README.md" />'
                    if any(
                        'GUIDED COMPLETION GATE — EXPLICIT PROJECT-START REQUIREMENTS ARE STILL MISSING' in str(msg.get('content', ''))
                        for msg in messages if msg.get('role') == 'system'
                    ) else 'Controller failed to demand the remaining project-start requirements.'
                ),
                'I created app.py and README.md, ran python app.py successfully, and completed the tiny starter.',
            ])

            try:
                with patch.object(panel, 'save_conversation'), \
                     patch.object(panel.rag_client, 'ingest_message'):
                    panel.send_worker(
                        'This folder is empty. Start a very small new Python project here. '
                        'Create only the minimum files needed for a basic runnable CLI starter: '
                        'app.py that prints a short greeting, plus a short README.md with run instructions. '
                        'Then validate it by running python app.py. Keep the project tiny and grounded.'
                    )
                    completed = self._wait_until_idle(panel, timeout=20.0)

                self.assertTrue(completed)
                self.assertTrue(os.path.exists(app_file))
                self.assertTrue(os.path.exists(readme_file))
                with open(app_file, 'r', encoding='utf-8') as f:
                    self.assertIn('Hello from starter', f.read())
                with open(readme_file, 'r', encoding='utf-8') as f:
                    self.assertIn('python app.py', f.read())
                assistant_messages = [m['content'] for m in panel.messages if m['role'] == 'assistant']
                system_messages = [m['content'] for m in panel.messages if m['role'] == 'system']
                self.assertTrue(any('<write_file path="README.md">' in m for m in assistant_messages))
                self.assertTrue(any('Hello from starter' in m for m in system_messages))
                self.assertGreaterEqual(len(assistant_messages), 2)
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
                f'<read_file path="{note_file}" />',
                "After extended reasoning, I created the file, verified its contents, and completed successfully.",
            ])

            try:
                with patch.object(panel, 'save_conversation'), \
                     patch.object(panel.rag_client, 'ingest_message'), \
                     patch.object(panel, '_launch_guided_auto_validation_batch', return_value=False):
                    panel.send_worker("Think carefully, then create note.txt and verify it.")
                    completed = self._wait_until_idle(panel, timeout=12.0)

                self.assertTrue(completed)
                self.assertTrue(os.path.exists(note_file))
                with open(note_file, 'r', encoding='utf-8') as f:
                    self.assertEqual(f.read().strip(), 'reasoning-mode works')
                self.assertIn("completed successfully", panel.messages[-1]["content"])
                self.assertEqual(panel.tool_loop_count, 3)
            finally:
                panel.close()

    def test_siege_mode_stage_one_narration_only_is_rewritten_into_real_first_batch(self):
        with self._blank_project() as project_dir:
            panel = self._panel(project_root=project_dir)
            panel.mode_combo.setCurrentText("Siege")
            panel.model_combo.clear()
            panel.model_combo.addItem("scripted-agent", "[Test] scripted-agent")
            panel.model_combo.setCurrentIndex(0)
            panel.on_model_changed("scripted-agent")

            app_file = f"{project_dir}/app.py"
            AIClient.configure_test_provider([
                "I will create app.py, trigger a runtime failure, and then fix it after I observe the error.",
                lambda messages: (
                    f'<write_file path="{app_file}">\nprint(1 / 0)\n</write_file>\n'
                    f'<execute_command command="python app.py" cwd="{project_dir}" />'
                    if any(
                        msg.get('role') == 'system'
                        and 'GUIDED DECISION GATE — DO NOT STOP BEFORE THE FIRST TOOL BATCH' in str(msg.get('content', ''))
                        for msg in messages
                    ) else 'Controller failed to demand a real first batch.'
                ),
                lambda messages: (
                    f'<edit_file path="{app_file}" old_text="print(1 / 0)" new_text="print(1 / 2)" />\n'
                    f'<execute_command command="python app.py" cwd="{project_dir}" />\n'
                    f'<read_file path="{app_file}" />'
                    if any('ZeroDivisionError' in str(msg.get('content', '')) for msg in messages if msg.get('role') == 'system') else 'Fix batch was not requested after the failing run.'
                ),
                'I created app.py, observed the failure, fixed it, and verified the result successfully.',
            ])

            try:
                with patch.object(panel, 'save_conversation'), \
                     patch.object(panel.rag_client, 'ingest_message'):
                    panel.send_worker('Create a tiny Python app, make it fail once, fix it, and verify it.')
                    completed = self._wait_until_idle(panel, timeout=20.0)

                self.assertTrue(completed)
                with open(app_file, 'r', encoding='utf-8') as f:
                    self.assertEqual(f.read().strip(), 'print(1 / 2)')
                self.assertIn('verified the result successfully', panel.messages[-1]['content'])
                self.assertGreaterEqual(panel.tool_loop_count, 2)
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
                     patch.object(panel, '_launch_guided_same_target_probe_batch', return_value=False), \
                     patch('ui.chat_panel.QMessageBox.question', return_value=QMessageBox.Yes):
                    panel.send_worker("Phase 1: create a tiny blank project with a bug.")
                    self.assertTrue(self._wait_until_idle(panel, timeout=15.0))
                    self.assertTrue(os.path.exists(app_file))
                    self.assertEqual(panel._pending_phased_tools, [{"cmd": "execute_command", "args": {"command": "python app.py", "cwd": project_dir}}])
                    self.assertFalse(any("<execute_command" in m["content"] for m in panel.messages if m["role"] == "assistant"))

                    panel.send_worker("continue")
                    self.assertTrue(self._wait_until_idle(panel, timeout=15.0))
                    self.assertTrue(any("Phase 2 summary" in m["content"] for m in panel.messages if m["role"] == "assistant"))

                    panel.send_worker("continue")
                    self.assertTrue(self._wait_until_idle(panel, timeout=15.0))
                    self.assertTrue(any("Phase 3 summary" in m["content"] for m in panel.messages if m["role"] == "assistant"))

                    panel.send_worker("continue")
                    completed = self._wait_until_idle(panel, timeout=15.0)

                self.assertTrue(completed, "Timed out waiting for the Phased end-to-end run to finish")
                self.assertTrue(os.path.exists(app_file))
                with open(app_file, 'r', encoding='utf-8') as f:
                    self.assertIn('hello from phased', f.read())

                system_messages = [m["content"] for m in panel.messages if m["role"] == "system"]
                self.assertTrue(any("NameError" in m for m in system_messages))
                self.assertTrue(any("hello from phased" in m for m in system_messages))
                self.assertGreaterEqual(sum(1 for title, _ in notifications if title == "Approval Needed"), 4)
                self.assertGreaterEqual(sum(1 for title, _ in notifications if title == "Phased Mode Complete"), 2)
                self.assertEqual(panel.send_btn.text(), "↑")
            finally:
                panel.close()

if __name__ == '__main__':
    unittest.main()
