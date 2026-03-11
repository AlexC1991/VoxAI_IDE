import re


def _chat_panel_module():
    from ui import chat_panel as chat_panel_module

    return chat_panel_module


def handle_ai_finished(self):
    chat_panel = _chat_panel_module()

    self._ai_update_timer.stop()
    self._ai_text_dirty = False
    self._guided_task_board_updated_this_turn = False
    if self.current_ai_item:
        self.current_ai_item.set_text(self._compact_assistant_display(self.current_ai_response))

    chat_panel.log.debug("handle_ai_finished: response_len=%d chars", len(self.current_ai_response))

    thought_blocks = re.findall(r'<thought>(.*?)</thought>', self.current_ai_response, re.DOTALL)
    display_response = re.sub(r'<thought>.*?</thought>\s*', '', self.current_ai_response, flags=re.DOTALL).strip()

    if thought_blocks and self.current_ai_item:
        thought_text = "\n---\n".join(t.strip() for t in thought_blocks)
        thought_item = chat_panel.ProgressItem()
        thought_item.set_thought(thought_text)
        self._add_chat_widget(thought_item, before_widget=self.current_ai_item)
        thought_item.finish()

    display_response, task_board_update, task_board_goal = self._extract_guided_task_board_update(display_response)
    if task_board_update:
        self._guided_task_board_updated_this_turn = self._apply_guided_task_board_update(task_board_update, task_board_goal)

    if display_response != self.current_ai_response:
        self.current_ai_response = display_response
    if self._stop_requested:
        chat_panel.log.info("AI generation stopped; skipping history append and tool parsing.")
        self._phased_summary_pending = False
        self._pending_phased_tools = []
        if self.current_ai_item and not self.current_ai_response.strip():
            self.current_ai_item.set_text("[Stopped]")
        self._reset_send_button()
        self.notification_requested.emit(
            "Generation Stopped",
            "Stopped before any additional tool execution could continue.",
        )
        return
    if not self.current_ai_response.strip():
        if (
            not self._stop_requested
            and self._is_siege_mode()
            and self._guided_takeoff_active()
            and not self._guided_phase_one_has_tool_evidence()
        ):
            probe_note = "[Blank model response triggered one minimal probe before asking the model to continue.]"
            if self._launch_guided_bounded_start_probe_batch(probe_note):
                self.notification_requested.emit("Empty Model Response", probe_note)
                return
        if not self._stop_requested and self._empty_ai_retry_count < 1:
            self._empty_ai_retry_count += 1
            retry_note = "[Model returned an empty response; retrying once automatically.]"
            if self.current_ai_item:
                self.current_ai_item.set_text(retry_note)
            self.notification_requested.emit("Empty Model Response", retry_note)
            chat_panel.QTimer.singleShot(
                0,
                lambda: self._start_ai_worker(
                    "The previous model response was empty. Continue from the latest context and provide the required next step or final summary. Do not repeat completed work unless the latest TOOL_RESULT proves it is still unresolved.",
                    [],
                ),
            )
            return
        if self._try_guided_blank_response_recovery():
            return
        self.current_ai_response = self._blank_response_fallback_message()
        display_response = self.current_ai_response
    else:
        self._empty_ai_retry_count = 0
        self._guided_blank_response_retry_count = 0
    if self.current_ai_item:
        self.current_ai_item.set_text(self._compact_assistant_display(display_response))
    self.refresh_models()

    if self._is_ai_error_response(self.current_ai_response):
        self._phased_summary_pending = False
        self._pending_phased_tools = []
        self._pending_summary_guard_flags = set()
        self._pending_summary_guard_message = None
        self._pending_summary_grounded_files = []
        self._summary_guard_retry_count = 0
        self.messages.append({"role": "assistant", "content": self.current_ai_response})
        self.save_conversation()
        self._reset_send_button()
        title, message = self._notification_for_ai_error(self.current_ai_response)
        self.notification_requested.emit(title, message)
        return

    is_siege = self._is_siege_mode()
    tools = chat_panel.CodeParser.parse_tool_calls(self.current_ai_response)
    if not tools:
        tools = self._recover_fenced_tool_calls(self.current_ai_response)
    if tools:
        self._clear_guided_current_task_stall()
    disabled_tool_note = chat_panel.ToolPolicy.summarize_disabled_tools([tool.get('cmd', '') for tool in tools], self.settings_manager)
    if tools and disabled_tool_note and all(not chat_panel.ToolPolicy.is_tool_enabled(tool.get('cmd', ''), self.settings_manager)[0] for tool in tools):
        if self.current_ai_item:
            self.current_ai_item.set_text("[Tool safety gate rejected the proposed batch because it only used disabled advanced tools.]")
        chat_panel.QTimer.singleShot(
            0,
            lambda: self._start_ai_worker(
                "Your previous tool batch only used disabled advanced tools. Rewrite it using the stable enabled tools for this run.",
                [],
                extra_system_messages=[disabled_tool_note],
            ),
        )
        return
    if self._guided_phase_one_needs_real_inspection(tools, self.current_ai_response):
        if self._guided_phase_intent_retry_count < 1:
            self._guided_phase_intent_retry_count += 1
            rewrite_note = "[Guided takeoff needs Phase 1 to actually inspect the codebase before it can hand off findings.]"
            if self.current_ai_item:
                self.current_ai_item.set_text(rewrite_note)
            chat_panel.QTimer.singleShot(
                0,
                lambda: self._start_ai_worker(
                    "Your previous Phase 1 response only described a plan. Rewrite it as a bounded Phase 1 inspection batch using 3-5 valid inspection-focused tool calls only. Do not summarize yet, and do not just say you will inspect.",
                    [],
                ),
            )
            return
        self.current_ai_response = self._guided_phase_one_summary_fallback("")
        display_response = self.current_ai_response
        if self.current_ai_item:
            self.current_ai_item.set_text(self._compact_assistant_display(display_response))
    elif self._guided_phase_one_needs_more_targeted_inspection(tools, self.current_ai_response):
        if self._guided_phase_intent_retry_count < 1:
            self._guided_phase_intent_retry_count += 1
            rewrite_note = "[Guided takeoff needs one more targeted Phase 1 inspection before it can summarize findings.]"
            if self.current_ai_item:
                self.current_ai_item.set_text(rewrite_note)
            chat_panel.QTimer.singleShot(
                0,
                lambda: self._start_ai_worker(
                    "Phase 1 evidence is still too shallow. Rewrite this turn as 1-3 valid inspection-focused tool calls that target a specific likely issue or file. Do not use <list_files> again, and do not summarize yet.",
                    [],
                ),
            )
            return
        self.current_ai_response = self._guided_phase_one_summary_fallback(self.current_ai_response)
        display_response = self.current_ai_response
        if self.current_ai_item:
            self.current_ai_item.set_text(self._compact_assistant_display(display_response))
    elif self._guided_phase_one_needs_grounded_handoff(tools, self.current_ai_response):
        if self._guided_phase_intent_retry_count < 1:
            self._guided_phase_intent_retry_count += 1
            rewrite_note = "[Guided takeoff needs a grounded Phase 1 handoff based on the inspection evidence already gathered.]"
            if self.current_ai_item:
                self.current_ai_item.set_text(rewrite_note)
            chat_panel.QTimer.singleShot(
                0,
                lambda: self._start_ai_worker(
                    "Do not emit tool calls in this response. Rewrite it as a grounded user-facing Phase 1 handoff using: Finding 1 / Evidence / Recommended next step / Follow-up for you.",
                    [],
                ),
            )
            return
        self.current_ai_response = self._guided_phase_one_summary_fallback(self.current_ai_response)
        display_response = self.current_ai_response
        if self.current_ai_item:
            self.current_ai_item.set_text(self._compact_assistant_display(display_response))
    if self._guided_phase_one_needs_pure_summary(tools):
        if self._guided_phase_summary_retry_count < 1:
            self._guided_phase_summary_retry_count += 1
            rewrite_note = "[Guided takeoff needs a clean Phase 1 summary before any more tools run.]"
            if self.current_ai_item:
                self.current_ai_item.set_text(rewrite_note)
            chat_panel.QTimer.singleShot(
                0,
                lambda: self._start_ai_worker(
                    "Do not emit tool calls in this response. Write a pure user-facing Phase 1 summary using this exact structure: Finding 1 / Evidence / Recommended next step / Follow-up for you. Do not paste raw tool output or long code excerpts.",
                    [],
                ),
            )
            return
        self.current_ai_response = self._guided_phase_one_summary_fallback(self.current_ai_response)
        display_response = self.current_ai_response
        tools = []
        if self.current_ai_item:
            self.current_ai_item.set_text(self._compact_assistant_display(display_response))
    if not tools:
        if self._guided_looks_like_malformed_tool_attempt(self.current_ai_response):
            if self._guided_decision_retry_count < 1:
                self._guided_decision_retry_count += 1
                if self.current_ai_item:
                    self.current_ai_item.set_text("[Guided takeoff is asking for a clean rewrite of malformed tool syntax.]")
                chat_panel.QTimer.singleShot(
                    0,
                    lambda: self._start_ai_worker(
                        "Your previous response mixed narrative with malformed or partial tool syntax. Rewrite it now as either valid tool XML only or a pure grounded blocker summary. Do not include partial tags or narrative around tool calls.",
                        [],
                    ),
                )
                return
            self.current_ai_response = self._guided_blocker_summary_fallback()
        violations = self._summary_guard_violations(self.current_ai_response)
        if violations:
            if self._summary_guard_retry_count < 1:
                self._summary_guard_retry_count += 1
                compact_only = set(violations) == {"overlong_success_summary"}
                retry_note = "[Summary paused by the IDE reality check; requesting a grounded rewrite.]"
                if compact_only:
                    retry_note = "[Summary paused by the IDE compactness check; requesting a shorter grounded rewrite.]"
                if self.current_ai_item:
                    self.current_ai_item.set_text(retry_note)
                blocker_prompt = (
                    "Your previous summary contradicted the latest tool evidence. Rewrite the summary so it only claims what the latest TOOL_RESULT proves. "
                    "If no files were changed, say that explicitly. If no successful validation or fresh rescan happened after the latest edit, say that explicitly. "
                    "If files were changed, name only the exact grounded file paths from the latest tool cycle. "
                    "Do not output raw or malformed tool XML/protocol in the final answer, and do not return a blank-response placeholder. "
                    "Do not emit tool calls unless you truly need more evidence."
                )
                if compact_only:
                    blocker_prompt = (
                        "Your previous final answer was truthful but too long. Rewrite it now as a compact grounded success summary: "
                        "maximum 2 short bullets or 3 very short lines total. Mention only the exact grounded changed files and whether the latest validation command succeeded. "
                        "Do not add extra recommendations, future ideas, or section headers. Do not emit tool calls."
                    )
                chat_panel.QTimer.singleShot(
                    0,
                    lambda: self._start_ai_worker(
                        blocker_prompt,
                        [],
                        extra_system_messages=[self._pending_summary_guard_message] if self._pending_summary_guard_message else None,
                    ),
                )
                return
            if set(violations) == {"overlong_success_summary"}:
                self.current_ai_response = self._compact_success_summary_fallback()
            else:
                self.current_ai_response = self._safe_summary_guard_fallback()
            display_response = self.current_ai_response
            if self.current_ai_item:
                self.current_ai_item.set_text(self._compact_assistant_display(display_response))
        self._guided_phase_summary_retry_count = 0
        self._guided_phase_intent_retry_count = 0
        self.current_ai_response = self._ensure_phase_one_followup(self.current_ai_response)
        if self._launch_guided_auto_validation_batch(
            "[Auto-recovery launched a compact post-edit verification batch based on the grounded changed file(s) before accepting the final summary.]"
        ):
            return
        non_tool_gate = self._guided_non_tool_decision_gate_prompt(self.current_ai_response)
        if non_tool_gate:
            if self._launch_guided_same_target_probe_batch(
                "[Guided takeoff launched one narrow same-target read before requiring either a fix or blocker.]"
            ):
                return
            current_task_gate = any(
                marker in non_tool_gate
                for marker in (
                    "GUIDED CURRENT TASK GATE",
                    "GUIDED TASK BOARD GATE — ADVANCE THE CURRENT TASK NOW",
                    "GUIDED TASK BOARD EXECUTION GATE — STOP ASKING FOR CONTINUE",
                )
            )
            max_decision_retries = 2 if current_task_gate else 1
            if self._guided_decision_retry_count < max_decision_retries:
                self._guided_decision_retry_count += 1
                if self.current_ai_item:
                    self.current_ai_item.set_text("[Guided takeoff is requesting either the next action or a clear blocker summary.]")
                rewrite_instruction = (
                    "Your previous response stopped at analysis. Rewrite this turn as either (A) valid tool XML only for the next minimal fix/validation batch, with no surrounding prose, or (B) a grounded blocker summary with one follow-up question."
                )
                if current_task_gate and self._guided_decision_retry_count >= 2:
                    rewrite_instruction = (
                        "Your previous response still did not advance your own CURRENT task. Rewrite this turn starting with an updated <task_board> block, then output either (A) valid tool XML only for the smallest batch that advances the CURRENT task, with no surrounding prose, or (B) a grounded blocker summary with one follow-up question. Do not repeat inspection findings or ask the user to continue."
                    )
                chat_panel.QTimer.singleShot(
                    0,
                    lambda: self._start_ai_worker(
                        rewrite_instruction,
                        [],
                        extra_system_messages=[non_tool_gate],
                    ),
                )
                return
            if self._launch_guided_bounded_start_probe_batch(
                "[Guided takeoff grounded the run with one minimal probe after repeated Stage 1 narration.]"
            ):
                return
            self.current_ai_response = self._guided_blocker_summary_fallback()
        display_response = self.current_ai_response
        if self.current_ai_item:
            self.current_ai_item.set_text(self._compact_assistant_display(display_response))
    else:
        tools, guided_note = self._guided_takeoff_filter_tools(tools)
        if guided_note and not tools:
            if self.current_ai_item:
                self.current_ai_item.set_text("[Guided takeoff asked for a smaller Phase 1 step before any tools ran.]")
            chat_panel.QTimer.singleShot(
                0,
                lambda: self._start_ai_worker(
                    "Your previous tool batch was too aggressive for guided takeoff. Use a smaller allowed tool batch or write the required user-facing summary.",
                    [],
                    extra_system_messages=[guided_note],
                ),
            )
            return
        decision_gate = self._guided_decision_gate_prompt(tools)
        if decision_gate:
            if self._launch_guided_same_target_probe_batch(
                "[Guided takeoff replaced the drifting batch with one narrow same-target read before requiring either a fix or blocker.]"
            ):
                return
            if self._guided_decision_retry_count < 1:
                self._guided_decision_retry_count += 1
                if self.current_ai_item:
                    self.current_ai_item.set_text("[Guided takeoff is asking for a commit-or-stop rewrite for this turn.]")
                chat_panel.QTimer.singleShot(
                    0,
                    lambda: self._start_ai_worker(
                        "Your previous tool batch did not satisfy the current guided decision gate. Rewrite this turn as either (A) valid tool XML only for the smallest allowed fix/validation batch, with no surrounding prose, or (B) a grounded blocker summary. Do not keep broadly investigating.",
                        [],
                        extra_system_messages=[decision_gate],
                    ),
                )
                return
            self.current_ai_response = self._guided_blocker_summary_fallback()
            display_response = self.current_ai_response
            tools = []
            if self.current_ai_item:
                self.current_ai_item.set_text(self._compact_assistant_display(display_response))

    self.messages.append({"role": "assistant", "content": self.current_ai_response})
    self.save_conversation()

    if self._rag_enabled():
        try:
            self.rag_client.ingest_message("assistant", self.current_ai_response, self.conversation_id)
        except Exception as e:
            chat_panel.log.error(f"Failed to ingest AI response: {e}")

    if tools:
        self._guided_decision_retry_count = 0
        self._guided_phase_intent_retry_count = 0
        if 'guided_note' in locals() and guided_note:
            self.append_message_widget("system", guided_note)
            self.messages.append({"role": "system", "content": guided_note})
        max_loops = 12 if is_siege else 1
        loop_count = getattr(self, 'tool_loop_count', 0)

        if not is_siege and self._phased_summary_pending:
            self._phased_summary_pending = False
            self._pending_phased_tools = list(tools)
            self.save_conversation()
            self._pause_agent(
                "Phased Mode Pause",
                "[Phased mode paused after the summary. The next tool batch is queued. Send a new message like 'continue' when you want the IDE to run it.]",
            )
            return

        if loop_count >= max_loops:
            chat_panel.log.info("Tool loop limit reached (%d). Pausing for user input.", max_loops)
            self._pause_agent(
                "Agent Loop Guard",
                f"[Loop guard paused the agent after {max_loops} tool cycle(s). Send a new message when you want it to continue.]",
            )
            return
        self._start_tool_execution(tools)
        return

    if not is_siege and self._phased_summary_pending:
        self._phased_summary_pending = False
        self._pending_phased_tools = []
        self._guided_update_phase_anchor(self.current_ai_response)
        self._advance_guided_takeoff_after_phase_one()
        self.save_conversation()
        self._pause_agent(
            "Phased Mode Complete",
            "[Phased mode summary is ready. Review the findings, then send a new message like 'continue' when you want the next phase.]",
        )
        return
    self._guided_decision_retry_count = 0
    self._guided_phase_intent_retry_count = 0
    self._pending_summary_guard_flags = set()
    self._pending_summary_guard_message = None
    self._pending_summary_grounded_files = []
    self._summary_guard_retry_count = 0
    self._phased_summary_pending = False
    self._pending_phased_tools = []
    self._reset_send_button()
    self.notification_requested.emit(
        "AI Response Complete",
        self.current_ai_response[:120] + ("..." if len(self.current_ai_response) > 120 else ""),
    )


def handle_tool_finished(self, output):
    chat_panel = _chat_panel_module()

    if self.progress_item:
        self.progress_item.finish()
    self.tool_loop_count = getattr(self, 'tool_loop_count', 0) + 1
    chat_panel.log.debug("handle_tool_finished: loop_count=%d output_len=%d", self.tool_loop_count, len(output))

    max_tool_output = 8000
    if len(output) > max_tool_output:
        half = max_tool_output // 2
        output = output[:half] + f"\n\n... [{len(output) - max_tool_output} chars truncated] ...\n\n" + output[-half:]
    tool_msg = "[TOOL_RESULT] (Automated system output — not user input)\n" f"{output}\n" "[/TOOL_RESULT]"
    tools_used = ", ".join(self._tool_calls_for_run) if self._tool_calls_for_run else "none"
    actions = "\n".join(f"- {a}" for a in self._tool_action_log) if self._tool_action_log else "- (no actions logged)"
    display_output = self._compact_for_display(output, max_chars=700, max_lines=10)
    display_tool_msg = (
        "[TOOL_RESULT] (Automated system output — compact view)\n"
        f"Tools used: {tools_used}\n"
        "Actions taken:\n"
        f"{actions}\n\n"
        "Output excerpt:\n"
        f"{display_output}\n"
        "[/TOOL_RESULT]"
    )

    self.append_message_widget("system", display_tool_msg)
    self.messages.append({"role": "system", "content": tool_msg})

    if self._stop_requested or "[Interrupted]" in output:
        self._phased_summary_pending = False
        self._pending_phased_tools = []
        self._pending_summary_guard_flags = set()
        self._pending_summary_guard_message = None
        self._pending_summary_grounded_files = []
        self._summary_guard_retry_count = 0
        self._reset_send_button()
        self.notification_requested.emit(
            "Tool Execution Stopped",
            "Tool execution was interrupted. The agent will not continue automatically.",
        )
        return

    self._phased_summary_pending = not self._is_siege_mode()
    self._pending_summary_guard_flags = self._summary_guard_flags(output)
    self._pending_summary_grounded_files = self._grounded_changed_files_from_summary(output)
    self._guided_successful_edit_seen = "no_file_changes" not in self._pending_summary_guard_flags
    self._guided_decision_retry_count = 0
    self._guided_phase_intent_retry_count = 0
    if self._launch_guided_auto_validation_batch(
        "[Auto-recovery launched a compact post-edit verification batch immediately after a successful edit because validation/rescan evidence was still missing.]"
    ):
        return
    if self._guided_takeoff_unlock_ready(output):
        self._guided_autonomy_unlocked = True
        self._guided_takeoff_stage = 3
        self._guided_no_progress_cycles = 0
    self._refresh_guided_task_board()
    reality_check = self._summary_guard_message(
        self._pending_summary_guard_flags,
        self._pending_summary_grounded_files,
    )
    grounded_snapshot = self._summary_grounding_message(output)
    guided_prompt = self._guided_takeoff_prompt(None)
    guided_recovery = self._guided_recovery_prompt(output)
    latest_batch = list(self._tool_calls_for_run or [])
    if (
        "no_file_changes" in self._pending_summary_guard_flags
        and latest_batch
        and all(self._guided_is_investigation_tool(cmd) for cmd in latest_batch)
        and self._launch_guided_same_target_probe_batch(
            "[Auto-recovery launched one narrow same-target read on the current best-supported target before requiring either a fix or blocker.]"
        )
    ):
        return
    self._pending_summary_guard_message = reality_check or grounded_snapshot
    self._summary_guard_retry_count = 0
    extra_messages = []
    if guided_recovery:
        extra_messages.append(guided_recovery)
    elif guided_prompt:
        extra_messages.append(guided_prompt)
    if reality_check:
        extra_messages.append(reality_check)
    elif grounded_snapshot:
        extra_messages.append(grounded_snapshot)
    compact_summary_prompt = self._post_tool_compact_summary_prompt()
    if compact_summary_prompt:
        extra_messages.append(compact_summary_prompt)
    self._start_ai_worker(extra_system_messages=extra_messages or None)


__all__ = ["handle_ai_finished", "handle_tool_finished"]