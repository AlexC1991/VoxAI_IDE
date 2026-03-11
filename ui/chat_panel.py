
# -*- coding: utf-8 -*-
import os
import re
import json
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, 
    QTextEdit, QPushButton, QFrame, QLabel, QMessageBox,
    QComboBox, QSizePolicy
)
from PySide6.QtCore import Signal, Qt, QThread, QTimer, QEvent

from core.settings import SettingsManager
from core.rag_client import RAGClient
from core.code_parser import CodeParser
from core.agent_tools import AgentToolHandler, get_project_root, get_resource_path
from core.prompts import SystemPrompts
from core.summary_guard import SummaryGuard
from core.tool_policy import ToolPolicy
from ui.chat_background import WatermarkContainer
from ui import chat_panel_dispatch as panel_dispatch
from ui import chat_panel_guidance as panel_guidance
from ui import chat_panel_handlers as panel_handlers
from ui import chat_panel_io as panel_io
from ui import chat_panel_ui as panel_ui
from ui.chat_workers import AIWorker, ToolWorker
from ui import chat_panel_models as panel_models
from ui import chat_panel_runtime as panel_runtime
from ui import chat_panel_state as panel_state
from ui.widgets.chat_items import MessageItem, ProgressItem

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main Chat Panel
# ---------------------------------------------------------------------------
class ChatPanel(QWidget):
    message_sent = Signal(str)
    code_generated = Signal(str, str) # language, code
    file_updated = Signal(str) # absolute path
    diff_ready = Signal(str, str) # file_path, unified diff text
    project_tracker_changed = Signal()
    notification_requested = Signal(str, str) # title, message
    token_usage_updated = Signal(int) # total tokens for status bar
    conversation_changed = Signal()  # emitted when conversations are saved/switched
    MAX_RENDERED_MESSAGES = 140
    CHAT_MAX_WIDTH = 1080

    _short_model_name = staticmethod(panel_models._short_model_name)
    _recommended_benchmark_model = staticmethod(panel_models._recommended_benchmark_model)
    _display_model_name = panel_models._display_model_name
    _refresh_model_combo_tooltip = panel_models._refresh_model_combo_tooltip
    refresh_models = panel_models.refresh_models
    _prepare_selected_model_for_send = panel_models._prepare_selected_model_for_send
    _get_full_model_name = panel_models._get_full_model_name
    _handle_ai_model_selected = panel_models._handle_ai_model_selected
    _resolve_at_mentions = panel_dispatch._resolve_at_mentions
    send_message = panel_dispatch.send_message
    _start_ai_worker = panel_dispatch._start_ai_worker
    send_worker = panel_dispatch.send_worker
    _guided_takeoff_prompt = panel_guidance._guided_takeoff_prompt
    _guided_tool_limit = panel_guidance._guided_tool_limit
    _guided_takeoff_allows_tool = panel_guidance._guided_takeoff_allows_tool
    _guided_is_narrow_context_tool = staticmethod(panel_guidance._guided_is_narrow_context_tool)
    _guided_prefer_fix_batch = panel_guidance._guided_prefer_fix_batch
    _guided_takeoff_filter_tools = panel_guidance._guided_takeoff_filter_tools
    _assistant_summary_has_followup = panel_guidance._assistant_summary_has_followup
    _ensure_phase_one_followup = panel_guidance._ensure_phase_one_followup
    _guided_takeoff_unlock_ready = panel_guidance._guided_takeoff_unlock_ready
    _guided_phase_one_needs_pure_summary = panel_guidance._guided_phase_one_needs_pure_summary
    _guided_phase_one_has_tool_evidence = panel_guidance._guided_phase_one_has_tool_evidence
    _guided_phase_one_has_grounded_handoff = panel_guidance._guided_phase_one_has_grounded_handoff
    _guided_phase_one_evidence_is_shallow = panel_guidance._guided_phase_one_evidence_is_shallow
    _guided_phase_one_needs_real_inspection = panel_guidance._guided_phase_one_needs_real_inspection
    _guided_phase_one_needs_grounded_handoff = panel_guidance._guided_phase_one_needs_grounded_handoff
    _guided_phase_one_needs_more_targeted_inspection = panel_guidance._guided_phase_one_needs_more_targeted_inspection
    _guided_phase_one_summary_fallback = panel_guidance._guided_phase_one_summary_fallback
    _guided_update_phase_anchor = panel_guidance._guided_update_phase_anchor
    _guided_is_investigation_tool = staticmethod(panel_guidance._guided_is_investigation_tool)
    _guided_is_edit_tool = staticmethod(panel_guidance._guided_is_edit_tool)
    _guided_navigation_tool_names = staticmethod(panel_guidance._guided_navigation_tool_names)
    _guided_is_validation_tool = staticmethod(panel_guidance._guided_is_validation_tool)
    _guided_extract_target_hints = staticmethod(panel_guidance._guided_extract_target_hints)
    _guided_extract_symbol_hints = staticmethod(panel_guidance._guided_extract_symbol_hints)
    _merge_guided_notes = staticmethod(panel_guidance._merge_guided_notes)
    _guided_navigation_request_detected = panel_guidance._guided_navigation_request_detected
    _guided_navigation_evidence_seen = panel_guidance._guided_navigation_evidence_seen
    _guided_navigation_report_target = panel_guidance._guided_navigation_report_target
    _guided_project_start_request_detected = panel_guidance._guided_project_start_request_detected
    _guided_project_start_required_files = panel_guidance._guided_project_start_required_files
    _guided_project_start_required_commands = panel_guidance._guided_project_start_required_commands
    _guided_project_start_requested_run_command = panel_guidance._guided_project_start_requested_run_command
    _guided_project_start_completed_files = panel_guidance._guided_project_start_completed_files
    _guided_project_start_completed_commands = panel_guidance._guided_project_start_completed_commands
    _guided_project_start_missing_requirements = panel_guidance._guided_project_start_missing_requirements
    _guided_project_start_requirements_prompt = panel_guidance._guided_project_start_requirements_prompt
    _guided_current_task_requires_action = panel_guidance._guided_current_task_requires_action
    _guided_validation_failure_focus = panel_guidance._guided_validation_failure_focus
    _guided_validation_failure_hint_text = panel_guidance._guided_validation_failure_hint_text
    _guided_is_off_target_navigation_edit = panel_guidance._guided_is_off_target_navigation_edit
    _guided_navigation_probe_tools = panel_guidance._guided_navigation_probe_tools
    _guided_recent_target_hints = panel_guidance._guided_recent_target_hints
    _guided_current_fix_targets = panel_guidance._guided_current_fix_targets
    _guided_concrete_target_context = panel_guidance._guided_concrete_target_context
    _guided_requires_same_target_edit_now = panel_guidance._guided_requires_same_target_edit_now
    _guided_call_matches_targets = panel_guidance._guided_call_matches_targets
    _guided_exact_match_retry_hint = panel_guidance._guided_exact_match_retry_hint
    _guided_tool_targets = staticmethod(panel_guidance._guided_tool_targets)
    _guided_validation_hint_text = panel_guidance._guided_validation_hint_text
    _guided_same_target_probe_tools = panel_guidance._guided_same_target_probe_tools
    _launch_guided_same_target_probe_batch = panel_guidance._launch_guided_same_target_probe_batch
    _guided_bounded_start_probe_tools = panel_guidance._guided_bounded_start_probe_tools
    _launch_guided_bounded_start_probe_batch = panel_guidance._launch_guided_bounded_start_probe_batch
    _shell_quote_path = staticmethod(panel_guidance._shell_quote_path)
    _text_validation_command = staticmethod(panel_guidance._text_validation_command)
    _guided_recent_validation_targets = panel_guidance._guided_recent_validation_targets
    _guided_auto_validation_tools = panel_guidance._guided_auto_validation_tools
    _launch_guided_auto_validation_batch = panel_guidance._launch_guided_auto_validation_batch
    _guided_blank_response_extra_messages = panel_guidance._guided_blank_response_extra_messages
    _try_guided_blank_response_recovery = panel_guidance._try_guided_blank_response_recovery
    _blank_response_fallback_message = panel_guidance._blank_response_fallback_message
    _guided_decision_gate_prompt = panel_guidance._guided_decision_gate_prompt
    _guided_non_tool_decision_gate_prompt = panel_guidance._guided_non_tool_decision_gate_prompt
    _recover_fenced_tool_calls = staticmethod(panel_guidance._recover_fenced_tool_calls)
    _guided_looks_like_malformed_tool_attempt = staticmethod(panel_guidance._guided_looks_like_malformed_tool_attempt)
    _guided_looks_like_tool_advice = staticmethod(panel_guidance._guided_looks_like_tool_advice)
    _guided_looks_like_fabricated_progress = staticmethod(panel_guidance._guided_looks_like_fabricated_progress)
    _guided_looks_like_inspection_only_summary = staticmethod(panel_guidance._guided_looks_like_inspection_only_summary)
    _guided_is_grounded_blocker_summary = staticmethod(panel_guidance._guided_is_grounded_blocker_summary)
    _guided_blocker_summary_fallback = panel_guidance._guided_blocker_summary_fallback
    _guided_recovery_prompt = panel_guidance._guided_recovery_prompt
    _is_ai_error_response = staticmethod(panel_guidance._is_ai_error_response)
    _notification_for_ai_error = staticmethod(panel_guidance._notification_for_ai_error)
    refresh_appearance = panel_ui.refresh_appearance
    on_model_changed = panel_ui.on_model_changed
    open_settings = panel_ui.open_settings
    append_message_widget = panel_ui.append_message_widget
    _add_chat_widget = panel_ui._add_chat_widget
    _prune_chat_widgets = panel_ui._prune_chat_widgets
    _regenerate_last = panel_ui._regenerate_last
    add_message = panel_ui.add_message
    _message_for_ai = staticmethod(panel_ui._message_for_ai)
    _messages_for_ai = classmethod(panel_ui._messages_for_ai)
    eventFilter = panel_ui.eventFilter
    handle_ai_finished = panel_handlers.handle_ai_finished
    handle_tool_finished = panel_handlers.handle_tool_finished
    _tool_coach_prompt = panel_state._tool_coach_prompt
    _parse_action_summary = staticmethod(panel_state._parse_action_summary)
    _normalize_summary_path = staticmethod(panel_state._normalize_summary_path)
    _extract_file_like_tokens = classmethod(panel_state._extract_file_like_tokens)
    _grounded_changed_files_from_summary = classmethod(panel_state._grounded_changed_files_from_summary)
    _grounded_changed_file_aliases = classmethod(panel_state._grounded_changed_file_aliases)
    _summary_claims_wrong_changed_file = classmethod(panel_state._summary_claims_wrong_changed_file)
    _summary_grounding_message = classmethod(panel_state._summary_grounding_message)
    _latest_tool_cycle_has_file_changes = classmethod(panel_state._latest_tool_cycle_has_file_changes)
    _parse_tool_action_log = staticmethod(panel_state._parse_tool_action_log)
    _is_successful_edit_step = staticmethod(panel_state._is_successful_edit_step)
    _is_successful_validation_step = staticmethod(panel_state._is_successful_validation_step)
    _is_failed_validation_step = staticmethod(panel_state._is_failed_validation_step)
    _is_successful_rescan_step = staticmethod(panel_state._is_successful_rescan_step)
    _failed_validation_commands = panel_state._failed_validation_commands
    _summary_guard_flags = panel_state._summary_guard_flags
    _summary_guard_message = staticmethod(panel_state._summary_guard_message)
    _pre_summary_reality_check = panel_state._pre_summary_reality_check
    _text_has_affirmative_claim = staticmethod(panel_state._text_has_affirmative_claim)
    _summary_guard_violations = panel_state._summary_guard_violations
    _safe_summary_guard_fallback = panel_state._safe_summary_guard_fallback
    _compact_success_summary_fallback = panel_state._compact_success_summary_fallback
    _post_tool_compact_summary_prompt = panel_state._post_tool_compact_summary_prompt
    _on_scroll_range_changed = panel_state._on_scroll_range_changed
    _do_deferred_scroll = panel_state._do_deferred_scroll
    _on_user_scroll = panel_state._on_user_scroll
    _scroll_to_bottom = panel_state._scroll_to_bottom
    _compact_for_display = staticmethod(panel_state._compact_for_display)
    _compact_assistant_display = panel_state._compact_assistant_display
    _is_siege_mode = panel_state._is_siege_mode
    _rag_enabled = panel_state._rag_enabled
    _normalize_tool_arg = staticmethod(panel_state._normalize_tool_arg)
    _tool_signature = panel_state._tool_signature
    _is_continue_directive = staticmethod(panel_state._is_continue_directive)
    _user_explicitly_requested_changes = staticmethod(panel_state._user_explicitly_requested_changes)
    _reset_guided_takeoff = panel_state._reset_guided_takeoff
    _advance_guided_takeoff_after_phase_one = panel_state._advance_guided_takeoff_after_phase_one
    _guided_task_status = staticmethod(panel_state._guided_task_status)
    _latest_non_continue_user_goal = panel_state._latest_non_continue_user_goal
    _default_guided_task_board = panel_state._default_guided_task_board
    _sanitize_guided_task_board = panel_state._sanitize_guided_task_board
    _guided_current_task_title = panel_state._guided_current_task_title
    _extract_guided_task_board_update = panel_state._extract_guided_task_board_update
    _clear_guided_current_task_stall = panel_state._clear_guided_current_task_stall
    _note_guided_current_task_stall = panel_state._note_guided_current_task_stall
    _apply_guided_task_board_update = panel_state._apply_guided_task_board_update
    _guided_audit_phase_active = panel_state._guided_audit_phase_active
    _guided_audit_completion_missing_bits = panel_state._guided_audit_completion_missing_bits
    _guided_audit_completion_ready = panel_state._guided_audit_completion_ready
    _guided_task_board_marker = staticmethod(panel_state._guided_task_board_marker)
    _compact_guided_task_board_summary = panel_state._compact_guided_task_board_summary
    _sync_guided_task_board_widget = panel_state._sync_guided_task_board_widget
    _trimmed_diff_preview = staticmethod(panel_state._trimmed_diff_preview)
    _bounded_diff_text = staticmethod(panel_state._bounded_diff_text)
    _display_tracker_path = panel_state._display_tracker_path
    _record_session_change = panel_state._record_session_change
    project_tracker_state = panel_state.project_tracker_state
    _reset_guided_task_board = panel_state._reset_guided_task_board
    _refresh_guided_task_board = panel_state._refresh_guided_task_board
    _guided_task_board_prompt = panel_state._guided_task_board_prompt
    _serialize_agent_state = panel_state._serialize_agent_state
    _restore_agent_state = panel_state._restore_agent_state
    _guided_takeoff_active = panel_state._guided_takeoff_active
    select_attachment = panel_io.select_attachment
    add_attachment = panel_io.add_attachment
    remove_attachment = panel_io.remove_attachment
    _refresh_attachments_ui = panel_io._refresh_attachments_ui
    _history_dir = panel_io._history_dir
    _conversation_file = panel_io._conversation_file
    _derive_title = panel_io._derive_title
    save_conversation = panel_io.save_conversation
    load_conversation = panel_io.load_conversation
    switch_conversation = panel_io.switch_conversation
    list_conversations = panel_io.list_conversations
    clear_context = panel_io.clear_context
    _reset_agent_run_state = panel_runtime._reset_agent_run_state
    _pause_agent = panel_runtime._pause_agent
    _track_background_thread = panel_runtime._track_background_thread
    _forget_background_thread = panel_runtime._forget_background_thread
    _clear_ai_refs = panel_runtime._clear_ai_refs
    _clear_tool_refs = panel_runtime._clear_tool_refs
    _clear_indexing_refs = panel_runtime._clear_indexing_refs
    _shutdown_thread = panel_runtime._shutdown_thread
    _shutdown_background_threads = panel_runtime._shutdown_background_threads
    handle_ai_chunk = panel_runtime.handle_ai_chunk
    _flush_ai_text = panel_runtime._flush_ai_text
    handle_ai_usage = panel_runtime.handle_ai_usage
    handle_stop_button = panel_runtime.handle_stop_button
    _set_stop_button = panel_runtime._set_stop_button
    _reset_send_button = panel_runtime._reset_send_button
    _start_tool_execution = panel_runtime._start_tool_execution
    _handle_tool_step_started = panel_runtime._handle_tool_step_started
    _handle_tool_step_finished = panel_runtime._handle_tool_step_finished
    _handle_change_proposed = panel_runtime._handle_change_proposed
    _handle_diff_generated = panel_runtime._handle_diff_generated
    _handle_confirmation = panel_runtime._handle_confirmation
    start_auto_indexing = panel_runtime.start_auto_indexing

    def __init__(self, parent=None):
        super().__init__(parent)
        log.info("ChatPanel initializing...")
        self.settings_manager = SettingsManager()
        
        # Long-term Memory: Conversation Tracking
        import uuid
        self.conversation_id = str(uuid.uuid4())[:8]
        self.rag_client = RAGClient()
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # ── Chat Area ──
        bg_path = get_resource_path(os.path.join("resources", "Chat_Background_Image.png"))
        self.chat_container = WatermarkContainer(logo_path=bg_path)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setAttribute(Qt.WA_TranslucentBackground)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        self.scroll_area.viewport().setStyleSheet("background: transparent; border: none;")

        self.chat_content = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_content)
        self.chat_layout.setAlignment(Qt.AlignTop)
        self.chat_layout.setContentsMargins(16, 12, 16, 12)
        self.chat_layout.setSpacing(10)
        self.chat_content.setStyleSheet("background: transparent; border: none;")
        self.chat_content.setAttribute(Qt.WA_TranslucentBackground)

        self.scroll_area.setWidget(self.chat_content)
        self.scroll_area.verticalScrollBar().rangeChanged.connect(
            self._on_scroll_range_changed)
        self.scroll_area.verticalScrollBar().valueChanged.connect(
            self._on_user_scroll)

        self.chat_container.layout.addWidget(self.scroll_area)
        self.layout.addWidget(self.chat_container, 1)

        # ── Input Area (compact bottom bar) ──
        self.input_wrapper = QWidget()
        self.input_wrapper.setStyleSheet("background: #111113; border-top: 1px solid #1e1e21;")
        self.input_wrapper_layout = QVBoxLayout(self.input_wrapper)
        self.input_wrapper_layout.setContentsMargins(10, 4, 10, 6)
        self.input_wrapper_layout.setSpacing(3)

        self.task_board_card = QFrame()
        self.task_board_card.setVisible(False)
        self.task_board_card.setStyleSheet(
            "QFrame { background: #121216; border: 1px solid #25252b; border-radius: 8px; }"
        )
        task_board_layout = QVBoxLayout(self.task_board_card)
        task_board_layout.setContentsMargins(10, 6, 10, 6)
        task_board_layout.setSpacing(2)

        self.task_board_title_label = QLabel("Project Tracker")
        self.task_board_title_label.setStyleSheet(
            "color: #f4f4f5; font-size: 10px; font-weight: bold; letter-spacing: 0.2px;"
        )
        task_board_layout.addWidget(self.task_board_title_label)

        self.task_board_goal_label = QLabel()
        self.task_board_goal_label.setWordWrap(True)
        self.task_board_goal_label.setStyleSheet("color: #a1a1aa; font-size: 10px;")
        self.task_board_goal_label.setVisible(False)
        task_board_layout.addWidget(self.task_board_goal_label)

        self.task_board_body_label = QLabel()
        self.task_board_body_label.setWordWrap(True)
        self.task_board_body_label.setTextFormat(Qt.PlainText)
        self.task_board_body_label.setStyleSheet(
            "color: #e4e4e7; font-size: 11px; font-family: 'Consolas', 'Courier New', monospace;"
        )
        self.task_board_body_label.setVisible(False)
        task_board_layout.addWidget(self.task_board_body_label)

        self.input_wrapper_layout.addWidget(self.task_board_card)

        # Attachment preview row
        self.attachment_area = QFrame()
        self.attachment_area.setVisible(False)
        self.attachment_area.setStyleSheet("background: transparent; border: none;")
        self.attachment_layout = QHBoxLayout(self.attachment_area)
        self.attachment_layout.setAlignment(Qt.AlignLeft)
        self.attachment_layout.setContentsMargins(0, 0, 0, 0)
        self.input_wrapper_layout.addWidget(self.attachment_area)

        # Main input frame (rounded card)
        self.input_container = QFrame()
        self.input_container.setStyleSheet(
            "QFrame { background: #1a1a1d; border: 1px solid #27272a; border-radius: 10px; }")
        input_outer = QVBoxLayout(self.input_container)
        input_outer.setContentsMargins(0, 0, 0, 0)
        input_outer.setSpacing(0)

        # Text input (compact)
        self.input_field = QTextEdit()
        self.input_field.setPlaceholderText("Message VoxAI...  (@file for context)")
        self.input_field.setStyleSheet(
            "QTextEdit { background: transparent; color: #e4e4e7; border: none; "
            "padding: 8px 12px 2px 12px; font-size: 13px; "
            "font-family: 'Consolas', 'Courier New', monospace; }"
        )
        self.input_field.setMinimumHeight(28)
        self.input_field.setMaximumHeight(100)
        input_outer.addWidget(self.input_field)

        # Bottom row inside the card: pills + buttons
        pill_row = QHBoxLayout()
        pill_row.setContentsMargins(6, 0, 6, 5)
        pill_row.setSpacing(4)

        # Attach button
        self.attach_btn = QPushButton("+")
        self.attach_btn.setToolTip("Attach file")
        self.attach_btn.setFixedSize(22, 22)
        self.attach_btn.setStyleSheet(
            "QPushButton { background: #27272a; color: #71717a; border: 1px solid #3f3f46; "
            "border-radius: 11px; font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { color: #00f3ff; border-color: #00f3ff; }")
        self.attach_btn.clicked.connect(self.select_attachment)
        pill_row.addWidget(self.attach_btn)

        # Mode pill
        self.mode_combo = QComboBox()
        self.mode_combo.setFixedHeight(22)
        self.mode_combo.addItems(["Phased", "Siege"])
        self.mode_combo.setStyleSheet(
            "QComboBox { background: #27272a; color: #ff9900; border: 1px solid #3f3f46; "
            "border-radius: 8px; padding: 1px 8px; font-size: 10px; "
            "font-family: 'Consolas', monospace; font-weight: bold; }"
            "QComboBox:hover { border-color: #ff9900; }"
            "QComboBox::drop-down { border: none; width: 0px; }"
            "QComboBox QAbstractItemView { background: #18181b; color: #e4e4e7; "
            "selection-background-color: #27272a; selection-color: #ff9900; "
            "border: 1px solid #3f3f46; }")
        pill_row.addWidget(self.mode_combo)

        # Model pill
        self.model_combo = QComboBox()
        self.model_combo.setFixedHeight(22)
        self.model_combo.setMaximumWidth(180)
        self.model_combo.setStyleSheet(
            "QComboBox { background: #27272a; color: #00f3ff; border: 1px solid #3f3f46; "
            "border-radius: 8px; padding: 1px 8px; font-size: 10px; "
            "font-family: 'Consolas', monospace; }"
            "QComboBox:hover { border-color: #00f3ff; }"
            "QComboBox::drop-down { border: none; width: 0px; }"
            "QComboBox QAbstractItemView { background: #18181b; color: #e4e4e7; "
            "selection-background-color: #27272a; selection-color: #00f3ff; "
            "border: 1px solid #3f3f46; }")
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        pill_row.addWidget(self.model_combo)

        pill_row.addStretch()

        # Send / Stop button
        self.send_btn = QPushButton("↑")
        self.send_btn.setToolTip("Send message (Enter)")
        self.send_btn.setFixedSize(28, 22)
        self.send_btn.clicked.connect(self.send_message)
        self.send_btn.setStyleSheet(
            "QPushButton { background: #00f3ff; color: #111113; border: none; "
            "border-radius: 11px; font-weight: bold; font-size: 14px; }"
            "QPushButton:hover { background: #33f7ff; }"
            "QPushButton:pressed { background: #00c2cc; }"
            "QPushButton:disabled { background: #3f3f46; color: #71717a; }")
        pill_row.addWidget(self.send_btn)

        input_outer.addLayout(pill_row)
        self.input_wrapper_layout.addWidget(self.input_container)
        self.layout.addWidget(self.input_wrapper)

        self.refresh_models()
        
        # Re-install event filter on logic init
        self.input_field.installEventFilter(self)
        
        # State
        self.attachments = [] # List of paths

        # State
        self.messages = [] # List of {"role":Str, "content":Str}
        self.is_processing = False
        self._auto_scroll = True
        self._programmatic_scroll = False
        self._scroll_pending = False
        self._editor_context_getter = None  # set by main_window

        # Streaming text buffer — batch updates to reduce layout thrashing
        self._ai_text_dirty = False
        self._ai_update_timer = QTimer()
        self._ai_update_timer.setInterval(50)  # Refresh UI every 50ms max
        self._ai_update_timer.timeout.connect(self._flush_ai_text)
        
        # Threads (use the same names throughout lifecycle)
        self.ai_thread_obj = None
        self.ai_worker_obj = None
        self.tool_thread = None
        self.tool_worker = None
        self.indexing_thread = None
        self.indexing_worker = None
        self._live_background_threads = []
        self.current_ai_item = None
        self.progress_item = None
        self._tool_calls_for_run = []
        self._run_tool_calls = []
        self._tool_action_log = []
        self._run_tool_action_log = []
        self.tool_loop_count = 0
        self._stop_requested = False
        self._phased_summary_pending = False
        self._pending_phased_tools = []
        self._phased_task_anchor = ""
        self._last_tool_signature = None
        self._repeat_tool_batches = 0
        self._empty_ai_retry_count = 0
        self._guided_blank_response_retry_count = 0
        self._pending_summary_guard_flags = set()
        self._pending_summary_guard_message = None
        self._pending_summary_grounded_files = []
        self._summary_guard_retry_count = 0
        self._auto_validation_retry_count = 0
        self._guided_takeoff_stage = 1
        self._guided_autonomy_unlocked = False
        self._guided_direct_change_requested = False
        self._guided_phase_summary_retry_count = 0
        self._guided_phase_intent_retry_count = 0
        self._guided_no_progress_cycles = 0
        self._guided_same_target_probe_count = 0
        self._guided_bounded_start_probe_count = 0
        self._guided_decision_retry_count = 0
        self._guided_phase_anchor = ""
        self._guided_successful_edit_seen = False
        self._guided_noop_edit_targets = []
        self._guided_exact_match_retry_targets = []
        self._guided_task_board_goal = ""
        self._guided_task_board = []
        self._guided_task_board_source = "fallback"
        self._guided_task_board_updated_this_turn = False
        self._guided_current_task_stall_count = 0
        self._guided_last_current_task = ""
        self._session_change_log = []
        self._tool_specs_for_run = []
        self._shutting_down = False

        # Load system prompt
        from core.prompts import SystemPrompts
        self.system_prompt = SystemPrompts.CODING_AGENT

        # Restore previous conversation if available
        QTimer.singleShot(200, self.load_conversation)

        # Trigger auto-indexing in background
        QTimer.singleShot(1000, self.start_auto_indexing)

    def closeEvent(self, event):
        self._shutdown_background_threads()
        super().closeEvent(event)
