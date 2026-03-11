import logging

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox

from core.agent_tools import get_project_root
from core.summary_guard import SummaryGuard
from ui.chat_workers import IndexingWorker, ToolWorker
from ui.widgets.chat_items import ProgressItem


log = logging.getLogger(__name__)


def _reset_agent_run_state(self):
    self._tool_action_log = []
    self._run_tool_calls = []
    self._run_tool_action_log = []
    self.tool_loop_count = 0
    self._stop_requested = False
    self._phased_summary_pending = False
    self._pending_phased_tools = []
    self._last_tool_signature = None
    self._repeat_tool_batches = 0
    self._empty_ai_retry_count = 0
    self._guided_blank_response_retry_count = 0
    self._pending_summary_guard_flags = set()
    self._pending_summary_guard_message = None
    self._pending_summary_grounded_files = []
    self._summary_guard_retry_count = 0
    self._auto_validation_retry_count = 0
    self._guided_phase_summary_retry_count = 0
    self._guided_phase_intent_retry_count = 0
    self._guided_no_progress_cycles = 0
    self._guided_same_target_probe_count = 0
    self._guided_bounded_start_probe_count = 0
    self._guided_decision_retry_count = 0
    self._guided_successful_edit_seen = False
    self._guided_noop_edit_targets = []
    self._guided_exact_match_retry_targets = []
    self._tool_specs_for_run = []
    self._refresh_guided_task_board()


def _pause_agent(self, title: str, message: str):
    if self.messages and self.messages[-1].get("role") == "assistant":
        last_content = str(self.messages[-1].get("content", ""))
        if SummaryGuard.response_contains_tool_protocol(last_content):
            replacement = SummaryGuard.pause_after_tool_protocol_fallback(
                list(getattr(self, "_pending_summary_grounded_files", []) or [])
            )
            self.messages[-1]["content"] = replacement
            self.current_ai_response = replacement
            if self.current_ai_item:
                self.current_ai_item.set_text(self._compact_assistant_display(replacement))
    self.append_message_widget("system", message)
    self._reset_send_button()
    self.notification_requested.emit(title, message)


def _track_background_thread(self, thread):
    if thread is None or thread in self._live_background_threads:
        return
    self._live_background_threads.append(thread)
    thread.finished.connect(lambda t=thread: self._forget_background_thread(t))


def _forget_background_thread(self, thread):
    self._live_background_threads = [t for t in self._live_background_threads if t is not thread]


def _clear_ai_refs(self, thread=None, worker=None):
    if worker is None or self.ai_worker_obj is worker:
        self.ai_worker_obj = None
    if thread is None or self.ai_thread_obj is thread:
        self.ai_thread_obj = None


def _clear_tool_refs(self, thread=None, worker=None):
    if worker is None or self.tool_worker is worker:
        self.tool_worker = None
    if thread is None or self.tool_thread is thread:
        self.tool_thread = None


def _clear_indexing_refs(self, thread=None, worker=None):
    if worker is None or self.indexing_worker is worker:
        self.indexing_worker = None
    if thread is None or self.indexing_thread is thread:
        self.indexing_thread = None


def _shutdown_thread(self, thread, *, interrupt=False, wait_ms=5000):
    if thread is None:
        return
    try:
        running = thread.isRunning()
    except Exception:
        return
    if not running:
        return
    if interrupt:
        try:
            thread.requestInterruption()
        except Exception:
            pass
    try:
        thread.quit()
    except Exception:
        pass
    try:
        if not thread.wait(wait_ms):
            log.warning("Timed out waiting for thread shutdown: %r", thread)
    except Exception:
        pass


def _shutdown_background_threads(self):
    self._shutting_down = True
    if self.tool_worker is not None:
        try:
            self.tool_worker.approve(False)
        except Exception:
            pass
    threads = []
    for thread in self._live_background_threads + [self.ai_thread_obj, self.tool_thread, self.indexing_thread]:
        if thread is not None and thread not in threads:
            threads.append(thread)
    for thread in threads:
        self._shutdown_thread(thread, interrupt=True)
    self._clear_ai_refs()
    self._clear_tool_refs()
    self._clear_indexing_refs()
    self._live_background_threads = []


def handle_ai_chunk(self, chunk):
    self.current_ai_response += chunk
    self._ai_text_dirty = True
    if not self._ai_update_timer.isActive():
        self._ai_update_timer.start()


def _flush_ai_text(self):
    """Push accumulated AI text to the widget (called by timer)."""
    if self._ai_text_dirty and self.current_ai_item:
        preview = self._compact_for_display(self.current_ai_response, max_chars=1200, max_lines=45)
        self.current_ai_item.set_text(preview)
        self._ai_text_dirty = False
        if self._auto_scroll:
            self._scroll_to_bottom()


def handle_ai_usage(self, usage):
    if self.current_ai_item:
        self.current_ai_item.set_usage(usage)
    total = usage.get("total_tokens", 0) if usage else 0
    if total:
        self.token_usage_updated.emit(total)


def handle_stop_button(self):
    """Interrupts AI and tool workers and resets the button."""
    stopped = False
    self._stop_requested = True
    if self.tool_worker:
        try:
            self.tool_worker.approve(False)
        except Exception:
            pass
    if self.ai_thread_obj and self.ai_thread_obj.isRunning():
        log.info("Stopping AI generation...")
        self.ai_thread_obj.requestInterruption()
        stopped = True
    if self.tool_thread and self.tool_thread.isRunning():
        log.info("Stopping tool execution...")
        self.tool_thread.requestInterruption()
        stopped = True
    if not stopped:
        self._reset_send_button()


def _set_stop_button(self):
    """Switch to the Stop state (orange square)."""
    self.send_btn.setText("■")
    self.send_btn.setStyleSheet(
        "QPushButton { background: #ff9900; color: #111113; border: none; "
        "border-radius: 11px; font-weight: bold; font-size: 12px; }"
        "QPushButton:hover { background: #ffaa33; }")


def _reset_send_button(self):
    """Resets the button to the Send state."""
    self.is_processing = False
    self.send_btn.setText("↑")
    self.send_btn.setEnabled(True)
    self.send_btn.setStyleSheet(
        "QPushButton { background: #00f3ff; color: #111113; border: none; "
        "border-radius: 11px; font-weight: bold; font-size: 14px; }"
        "QPushButton:hover { background: #33f7ff; }"
        "QPushButton:pressed { background: #00c2cc; }"
        "QPushButton:disabled { background: #3f3f46; color: #71717a; }")


def _start_tool_execution(self, tools):
    is_siege = self._is_siege_mode()
    signature = self._tool_signature(tools)
    if signature == self._last_tool_signature:
        self._repeat_tool_batches += 1
    else:
        self._last_tool_signature = signature
        self._repeat_tool_batches = 1

    repeat_limit = 3 if is_siege else 2
    if self._repeat_tool_batches >= repeat_limit:
        self._phased_summary_pending = False
        self._pause_agent(
            "Loop Guard Triggered",
            f"[Loop guard paused the agent because it proposed the same tool batch {self._repeat_tool_batches} times in a row. Give it a new instruction, or send 'continue' if you want to override that pause.]"
        )
        return

    tool_names = [c['cmd'] for c in tools]
    self._tool_calls_for_run = list(tool_names)
    self._run_tool_calls.extend(tool_names)
    self._tool_specs_for_run = [dict(call) for call in tools]
    self._tool_action_log = []
    summary = ", ".join(tool_names)
    if len(summary) > 80:
        summary = f"{len(tools)} tools"

    self.progress_item = ProgressItem()
    self._add_chat_widget(self.progress_item)
    self.progress_item.set_thought(f"Running: {summary}")
    self._auto_scroll = True

    auto_approve = is_siege or self.settings_manager.get_auto_approve_writes()
    self.tool_thread = QThread()
    self.tool_worker = ToolWorker(tools, auto_approve=auto_approve)
    self.tool_worker.moveToThread(self.tool_thread)
    tool_thread = self.tool_thread
    tool_worker = self.tool_worker
    self._track_background_thread(tool_thread)

    tool_thread.started.connect(tool_worker.run)
    tool_worker.step_started.connect(self._handle_tool_step_started)
    tool_worker.step_finished.connect(self._handle_tool_step_finished)
    tool_worker.file_changed.connect(self.file_updated.emit)
    tool_worker.diff_generated.connect(self._handle_diff_generated)
    tool_worker.change_proposed.connect(self._handle_change_proposed)
    tool_worker.confirmation_needed.connect(self._handle_confirmation)
    tool_worker.finished.connect(self.handle_tool_finished)
    tool_worker.finished.connect(tool_thread.quit)
    tool_worker.finished.connect(tool_worker.deleteLater)
    tool_thread.finished.connect(tool_thread.deleteLater)
    tool_thread.finished.connect(lambda t=tool_thread, w=tool_worker: self._clear_tool_refs(t, w))

    tool_thread.start()


def _handle_tool_step_started(self, icon, text):
    """Add a new step to the progress widget and keep scroll pinned."""
    if hasattr(self, 'progress_item') and self.progress_item:
        self.progress_item.add_step(icon, text)
        self._auto_scroll = True


def _handle_tool_step_finished(self, title, detail, result):
    """Update the progress item's last step with a completion indicator."""
    self._tool_action_log.append(f"{title} -> {result}")
    self._run_tool_action_log.append(f"{title} -> {result}")
    if hasattr(self, 'progress_item') and self.progress_item:
        icon = "✓" if result == "Done" else "✗" if result == "Failed" else "⊘"
        self.progress_item.update_step_status(icon, result)


def _handle_change_proposed(self, file_path, diff_text, new_content):
    """Shows the proposed diff in the editor before the approval dialog appears."""
    self.diff_ready.emit(file_path, diff_text)


def _handle_diff_generated(self, file_path, diff_text):
    self._record_session_change(file_path, diff_text)
    self.diff_ready.emit(file_path, diff_text)


def _handle_confirmation(self, description):
    """Shows a confirmation dialog for destructive or file-write operations."""
    self.notification_requested.emit("Approval Needed", description)
    reply = QMessageBox.question(
        self,
        "Confirm Action",
        f"The AI wants to perform this action:\n\n{description}\n\nAllow this action?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if hasattr(self, 'tool_worker') and self.tool_worker:
        self.tool_worker.approve(reply == QMessageBox.Yes)


def start_auto_indexing(self):
    """Starts the indexing process in the background."""
    if getattr(self, '_shutting_down', False):
        log.info("Auto-indexing skipped because ChatPanel is shutting down.")
        return
    if not self._rag_enabled():
        log.info("Auto-indexing skipped because RAG is disabled.")
        return
    log.info("Starting auto-indexing...")
    root = get_project_root()

    self.indexing_thread = QThread()
    self.indexing_worker = IndexingWorker(root)
    self.indexing_worker.moveToThread(self.indexing_thread)
    indexing_thread = self.indexing_thread
    indexing_worker = self.indexing_worker
    self._track_background_thread(indexing_thread)

    indexing_thread.started.connect(indexing_worker.run)
    indexing_worker.finished.connect(indexing_thread.quit)
    indexing_worker.finished.connect(indexing_worker.deleteLater)
    indexing_thread.finished.connect(indexing_thread.deleteLater)
    indexing_thread.finished.connect(lambda t=indexing_thread, w=indexing_worker: self._clear_indexing_refs(t, w))
    indexing_thread.finished.connect(lambda: log.info("Auto-indexing finished."))

    indexing_thread.start()


__all__ = [name for name in globals() if name.startswith("_") or name in {"handle_ai_chunk", "handle_ai_usage", "handle_stop_button", "start_auto_indexing"}]