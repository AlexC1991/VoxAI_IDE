import os
import re

from PySide6.QtCore import QTimer

from core.agent_tools import get_project_root
from core.summary_guard import SummaryGuard
from core.tool_policy import ToolPolicy


def _tool_coach_prompt(self) -> str:
    return ToolPolicy.build_tool_coach_prompt(self.settings_manager)


def _parse_action_summary(tool_output: str) -> dict[str, list[str]]:
    return SummaryGuard.parse_action_summary(tool_output)


def _normalize_summary_path(path_text: str) -> str:
    return SummaryGuard.normalize_path(path_text)


def _extract_file_like_tokens(cls, text: str) -> list[str]:
    return SummaryGuard.extract_file_like_tokens(text)


def _grounded_changed_files_from_summary(cls, tool_output: str) -> list[str]:
    return SummaryGuard.grounded_changed_files_from_summary(tool_output)


def _grounded_changed_file_aliases(cls, file_paths: list[str]) -> set[str]:
    return SummaryGuard.grounded_changed_file_aliases(file_paths)


def _summary_claims_wrong_changed_file(cls, response_text: str, grounded_files: list[str]) -> bool:
    return SummaryGuard.summary_claims_wrong_changed_file(response_text, grounded_files)


def _summary_grounding_message(cls, tool_output: str) -> str | None:
    return SummaryGuard.summary_grounding_message(tool_output)


def _latest_tool_cycle_has_file_changes(cls, tool_output: str) -> bool:
    return SummaryGuard.latest_tool_cycle_has_file_changes(tool_output)


def _parse_tool_action_log(action_log: list[str]) -> list[tuple[str, str]]:
    return SummaryGuard.parse_tool_action_log(action_log)


def _is_successful_edit_step(title: str, status: str) -> bool:
    return SummaryGuard.is_successful_edit_step(title, status)


def _is_successful_validation_step(title: str, status: str) -> bool:
    return SummaryGuard.is_successful_validation_step(title, status)


def _is_failed_validation_step(title: str, status: str) -> bool:
    return SummaryGuard.is_failed_validation_step(title, status)


def _is_successful_rescan_step(title: str, status: str) -> bool:
    return SummaryGuard.is_successful_rescan_step(title, status)


def _failed_validation_commands(self, tool_output: str | None = None) -> list[str]:
    return SummaryGuard.failed_validation_commands(tool_output or "", self._run_tool_action_log or self._tool_action_log)


def _summary_guard_flags(self, tool_output: str) -> set[str]:
    return SummaryGuard.summary_guard_flags(tool_output, self._run_tool_action_log or self._tool_action_log)


def _summary_guard_message(flags: set[str], grounded_files: list[str] | None = None) -> str | None:
    return SummaryGuard.summary_guard_message(flags, grounded_files)


def _pre_summary_reality_check(self, tool_output: str) -> str | None:
    return self._summary_guard_message(
        self._summary_guard_flags(tool_output),
        self._grounded_changed_files_from_summary(tool_output),
    )


def _text_has_affirmative_claim(text: str, patterns: list[str]) -> bool:
    return SummaryGuard.text_has_affirmative_claim(text, patterns)


def _summary_guard_violations(self, response_text: str) -> list[str]:
    flags = set(self._pending_summary_guard_flags or set())
    grounded_files = list(self._pending_summary_grounded_files or [])
    guard_active = bool(flags or grounded_files or self._pending_summary_guard_message)
    if not guard_active:
        return []
    violations = []
    text = str(response_text or "")
    lower = text.lower()
    if self._guided_looks_like_malformed_tool_attempt(text) or bool(re.search(r'<\s*/?tool_call\b', text, re.IGNORECASE)):
        violations.append("tool_protocol")
    if "no response received from the model" in lower:
        violations.append("blank_final")
    if not flags and not grounded_files:
        return violations
    honest_no_file = any(phrase in lower for phrase in (
        "no files were changed",
        "did not change any files",
        "made no code changes",
        "changed nothing",
    ))
    honest_no_validation = any(phrase in lower for phrase in (
        "no successful validation",
        "was not verified",
        "not verified",
        "not validated",
        "did not verify",
        "no tests were run",
    ))
    honest_no_rescan = any(phrase in lower for phrase in (
        "no fresh rescan",
        "did not rescan",
        "didn't rescan",
        "no fresh inspection",
    ))
    if "no_file_changes" in flags and not honest_no_file and self._text_has_affirmative_claim(text, [
        r"\bi (changed|updated|modified|edited|fixed|implemented|wrote|created|deleted|refactored)\b",
        r"\bwe (changed|updated|modified|edited|fixed|implemented|wrote|created|deleted|refactored)\b",
    ]):
        violations.append("file_changes")
    if ({"no_validation", "no_post_edit_validation"} & flags) and not honest_no_validation and self._text_has_affirmative_claim(text, [
        r"\bi (verified|validated|tested|reran|re-ran|confirmed)\b",
        r"\bwe (verified|validated|tested|reran|re-ran|confirmed)\b",
        r"\b(the )?(fix|change|result) is verified\b",
        r"\btests? passed\b",
        r"\bvalidation passed\b",
        r"\breran successfully\b",
    ]):
        violations.append("validation")
    if "no_post_edit_rescan" in flags and not honest_no_rescan and self._text_has_affirmative_claim(text, [
        r"\b(i|we) re-?scann?ed\b",
        r"\bscann?ed the repo again\b",
        r"\bperformed a fresh rescan\b",
        r"\bdid a fresh rescan\b",
    ]):
        violations.append("rescan")
    project_start_missing = self._guided_project_start_missing_requirements()
    project_start_incomplete = bool(project_start_missing["missing_files"] or project_start_missing["missing_commands"])
    if (("no_file_changes" in flags) or bool({"no_validation", "no_post_edit_validation"} & flags)) and self._guided_looks_like_fabricated_progress(text) and not project_start_incomplete:
        violations.append("fabricated_progress")
    allowed_changed_files = list(grounded_files)
    seen_allowed = {self._normalize_summary_path(path).lower() for path in grounded_files if self._normalize_summary_path(path)}
    for change in self._session_change_log or []:
        normalized = self._normalize_summary_path(change.get("file_path") or change.get("display_path"))
        if not normalized or normalized.lower() in seen_allowed:
            continue
        seen_allowed.add(normalized.lower())
        allowed_changed_files.append(normalized)
    if self._summary_claims_wrong_changed_file(text, allowed_changed_files):
        violations.append("wrong_changed_file")
    if SummaryGuard.summary_needs_compact_success_rewrite(text, flags, allowed_changed_files):
        violations.append("overlong_success_summary")
    return violations


def _safe_summary_guard_fallback(self) -> str:
    return SummaryGuard.safe_summary_guard_fallback(
        set(self._pending_summary_guard_flags or set()),
        list(self._pending_summary_grounded_files or []),
    )


def _compact_success_summary_fallback(self) -> str:
    return SummaryGuard.compact_success_summary_fallback(
        set(self._pending_summary_guard_flags or set()),
        list(self._pending_summary_grounded_files or []),
    )


def _post_tool_compact_summary_prompt(self) -> str | None:
    grounded_files = list(self._pending_summary_grounded_files or [])
    if not grounded_files:
        return None
    validation_state = "Mention validation only if it actually succeeded in the latest grounded tool cycle."
    flags = set(self._pending_summary_guard_flags or set())
    if not ({"no_validation", "no_post_edit_validation"} & flags):
        validation_state = "If you answer the user now, mention only that the latest validation command succeeded."
    return (
        "FINAL RESPONSE FORMAT FOR THIS TURN:\n"
        "- If you answer the user now instead of calling more tools, keep it to at most 2 short bullets or 3 very short lines total.\n"
        f"- Mention only these grounded changed files if relevant: {', '.join(grounded_files)}\n"
        f"- {validation_state}\n"
        "- Do not add optional next steps, future ideas, or extra sections unless the user explicitly asked for them."
    )


def _on_scroll_range_changed(self, _min, _max):
    if self._auto_scroll and not self._scroll_pending:
        self._scroll_pending = True
        QTimer.singleShot(0, self._do_deferred_scroll)


def _do_deferred_scroll(self):
    self._scroll_pending = False
    if not self._auto_scroll:
        return
    sb = self.scroll_area.verticalScrollBar()
    self._programmatic_scroll = True
    sb.setValue(sb.maximum())
    self._programmatic_scroll = False


def _on_user_scroll(self, value):
    if self._programmatic_scroll:
        return
    sb = self.scroll_area.verticalScrollBar()
    if sb.maximum() == 0:
        return
    self._auto_scroll = (sb.maximum() - value) < 60


def _scroll_to_bottom(self):
    self._auto_scroll = True
    QTimer.singleShot(0, self._do_deferred_scroll)


def _compact_for_display(text: str, max_chars: int = 1400, max_lines: int = 40) -> str:
    if not text:
        return text
    lines = text.splitlines()
    over_lines = len(lines) > max_lines
    over_chars = len(text) > max_chars
    if not over_lines and not over_chars:
        return text
    kept = lines[:max_lines]
    compact = "\n".join(kept)
    if len(compact) > max_chars:
        compact = compact[:max_chars].rstrip()
    hidden_lines = max(0, len(lines) - len(kept))
    hidden_chars = max(0, len(text) - len(compact))
    compact += f"\n\n...[{hidden_lines} lines / {hidden_chars} chars hidden in chat view]..."
    return compact


def _compact_assistant_display(self, text: str) -> str:
    import re as _re
    if not text:
        return text

    def _repl(match):
        block = match.group(0)
        content = block[3:-3]
        lang = ""
        if "\n" in content:
            lang = content.split("\n", 1)[0].strip()
        body = content.split("\n", 1)[1] if "\n" in content else content
        lines = max(1, body.count("\n") + 1)
        label = lang or "code"
        return f"\n```{label}\n[code block hidden: {lines} lines]\n```"

    compact = _re.sub(r"```[\w-]*\n.*?```", _repl, text, flags=_re.DOTALL)
    return self._compact_for_display(compact, max_chars=1800, max_lines=60)


def _is_siege_mode(self) -> bool:
    return "Siege" in self.mode_combo.currentText()


def _rag_enabled(self) -> bool:
    return self.settings_manager.get_rag_enabled()


def _normalize_tool_arg(value) -> str:
    text = str(value).replace("\r\n", "\n")
    if len(text) > 140:
        text = text[:100] + f"...[{len(text) - 120} chars omitted]..." + text[-20:]
    return text


def _tool_signature(self, tools: list[dict]) -> tuple:
    signature = []
    for call in tools:
        args = tuple(sorted((k, self._normalize_tool_arg(v)) for k, v in (call.get("args") or {}).items()))
        signature.append((call.get("cmd", ""), args))
    return tuple(signature)


def _is_continue_directive(text: str | None) -> bool:
    normalized = str(text or "").strip().lower()
    return normalized in {"continue", "next", "resume", "proceed", "go on"} or any(
        normalized.startswith(prefix)
        for prefix in (
            "continue.", "continue,", "continue ",
            "next.", "next,", "next ",
            "resume.", "resume,", "resume ",
            "proceed.", "proceed,", "proceed ",
            "go on.", "go on,", "go on ",
        )
    )


def _user_explicitly_requested_changes(text: str | None) -> bool:
    lowered = str(text or "").lower()
    return bool(re.search(r"\b(create|fix|implement|write|edit|modify|refactor|rename|delete|remove|add|build|patch|update|change|repair|polish|tweak|improve|enhance|refine)\b", lowered))


def _reset_guided_takeoff(self, task_text: str | None = None):
    self._guided_takeoff_stage = 1
    self._guided_autonomy_unlocked = False
    self._guided_direct_change_requested = self._user_explicitly_requested_changes(task_text)
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
    self._reset_guided_task_board(task_text)


def _advance_guided_takeoff_after_phase_one(self):
    if self._guided_takeoff_stage < 2:
        self._guided_takeoff_stage = 2
    self._refresh_guided_task_board()


def _guided_task_status(status: str | None) -> str:
    normalized = str(status or "").strip().lower()
    return normalized if normalized in {"pending", "current", "complete"} else "pending"


def _latest_non_continue_user_goal(self) -> str:
    for message in reversed(self.messages):
        if message.get("role") != "user":
            continue
        content = str(message.get("content", "")).strip()
        if content and not self._is_continue_directive(content):
            return content[:500]
    return ""


def _guided_goal_has_any(goal_text: str | None, phrases: tuple[str, ...]) -> bool:
    lowered = str(goal_text or "").lower()
    for phrase in phrases:
        pattern = re.escape(str(phrase or "").lower()).replace(r"\ ", r"\s+")
        if pattern and re.search(rf'(?<!\w){pattern}(?!\w)', lowered):
            return True
    return False


def _build_guided_task_board(goal_text: str | None = None) -> list[dict]:
    return [
        {"id": "inspect", "title": "Inspect the task and gather grounded evidence", "status": "pending"},
        {"id": "target_and_edit", "title": "Stay on one concrete target and apply the smallest safe change", "status": "pending"},
        {"id": "validate", "title": "Validate the latest change with the smallest useful command", "status": "pending"},
        {"id": "rescan_and_report", "title": "Do one fresh post-edit rescan and report grounded results", "status": "pending"},
    ]


def _default_guided_task_board(self) -> list[dict]:
    return _build_guided_task_board(self._guided_task_board_goal or self._latest_non_continue_user_goal())


def _sanitize_guided_task_board(self, tasks: list[dict] | None) -> list[dict]:
    normalized_tasks = []
    seen_titles = set()
    current_seen = False
    for idx, task in enumerate(tasks or []):
        if not isinstance(task, dict):
            continue
        title = " ".join(str(task.get("title", "")).split()).strip()
        if not title:
            continue
        lowered_title = title.lower()
        if lowered_title in seen_titles:
            continue
        seen_titles.add(lowered_title)
        status = self._guided_task_status(task.get("status"))
        if status == "current":
            if current_seen:
                status = "pending"
            current_seen = True
        normalized_tasks.append({
            "id": str(task.get("id", "")).strip() or f"task_{idx}",
            "title": title[:220],
            "status": status,
        })
        if len(normalized_tasks) >= 8:
            break
    if not normalized_tasks:
        return []
    if not any(task.get("status") == "current" for task in normalized_tasks) and any(task.get("status") != "complete" for task in normalized_tasks):
        for task in normalized_tasks:
            if task.get("status") != "complete":
                task["status"] = "current"
                break
    return normalized_tasks


def _guided_current_task_title(self) -> str:
    board = list(self._guided_task_board or [])
    current = next((str(task.get("title", "")).strip() for task in board if str(task.get("status", "")).lower() == "current"), "")
    if current:
        return current
    return next((str(task.get("title", "")).strip() for task in board if str(task.get("status", "")).lower() == "pending"), "")


def _extract_guided_task_board_update(self, response_text: str) -> tuple[str, list[dict] | None, str | None]:
    text = str(response_text or "")
    match = re.search(r'<task_board>([\s\S]*?)</task_board>', text, re.IGNORECASE)
    if not match:
        return text.strip(), None, None
    body = str(match.group(1) or "")
    goal_text = None
    tasks = []
    for raw_line in body.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        goal_match = re.match(r'^goal\s*:\s*(.+)$', line, re.IGNORECASE)
        if goal_match:
            goal_text = goal_match.group(1).strip()[:500]
            continue
        task_match = re.match(r'^-\s*\[(complete|current|pending|x|>)\]\s*(.+)$', line, re.IGNORECASE)
        if not task_match:
            continue
        status_token = task_match.group(1).strip().lower()
        status = {"x": "complete", ">": "current"}.get(status_token, status_token)
        tasks.append({"title": task_match.group(2).strip(), "status": status})
    cleaned = (text[:match.start()] + text[match.end():]).strip()
    sanitized = self._sanitize_guided_task_board(tasks)
    return cleaned, (sanitized or None), goal_text


def _clear_guided_current_task_stall(self):
    self._guided_current_task_stall_count = 0
    self._guided_last_current_task = ""


def _note_guided_current_task_stall(self, current_task: str | None = None):
    current = str(current_task or self._guided_current_task_title()).strip()
    if not current:
        self._clear_guided_current_task_stall()
        return
    if current == str(getattr(self, "_guided_last_current_task", "") or ""):
        self._guided_current_task_stall_count = int(getattr(self, "_guided_current_task_stall_count", 0) or 0) + 1
    else:
        self._guided_last_current_task = current
        self._guided_current_task_stall_count = 1


def _apply_guided_task_board_update(self, tasks: list[dict] | None, goal_text: str | None = None) -> bool:
    sanitized = self._sanitize_guided_task_board(tasks)
    if not sanitized:
        return False
    previous_current = self._guided_current_task_title()
    if goal_text and not self._is_continue_directive(goal_text):
        self._guided_task_board_goal = goal_text[:500]
    self._guided_task_board = sanitized
    self._guided_task_board_source = "llm"
    if self._guided_current_task_title() != previous_current:
        self._clear_guided_current_task_stall()
    self._sync_guided_task_board_widget()
    return True


def _guided_audit_phase_active(self) -> bool:
    text = "\n".join(
        part for part in [
            self._guided_task_board_goal,
            self._guided_current_task_title(),
            *[str(task.get("title", "")) for task in (self._guided_task_board or [])],
        ] if str(part or "").strip()
    )
    return _guided_goal_has_any(text, ("audit", "audit.md", "reviewer", "codebase review"))


def _guided_audit_completion_missing_bits(self) -> list[str]:
    if not self._guided_audit_phase_active():
        return []
    missing = []
    latest_files = [self._normalize_summary_path(path) for path in (self._pending_summary_grounded_files or []) if self._normalize_summary_path(path)]
    latest_lower = {path.lower() for path in latest_files}
    audit_exists = (
        "audit.md" in latest_lower
        or any(str(change.get("display_path", "")).strip().lower() == "audit.md" for change in (self._session_change_log or []))
        or os.path.isfile(os.path.join(get_project_root(), "AUDIT.md"))
    )
    if not audit_exists:
        missing.append("write AUDIT.md")
    if not any(path.lower() != "audit.md" for path in latest_files):
        missing.append("apply at least one non-AUDIT safe fix in the latest audit cycle")
    flags = set(self._pending_summary_guard_flags or set())
    if {"no_validation", "no_post_edit_validation"} & flags:
        missing.append("rerun the requested validation commands")
    if "no_post_edit_rescan" in flags:
        missing.append("do one fresh post-fix inspection/rescan")
    return missing


def _guided_audit_completion_ready(self) -> bool:
    return self._guided_audit_phase_active() and not self._guided_audit_completion_missing_bits()


def _guided_task_board_marker(status: str) -> str:
    return {"complete": "[x]", "current": "[>]", "pending": "[ ]"}.get(status, "[ ]")


def _compact_guided_task_board_summary(self) -> str:
    if not self._guided_task_board:
        return "Project Tracker"
    total = len(self._guided_task_board)
    completed = sum(1 for task in self._guided_task_board if str(task.get("status", "")).lower() == "complete")
    current = next((str(task.get("title", "") or "").strip() for task in self._guided_task_board if str(task.get("status", "")).lower() == "current"), "")
    summary = f"Project Tracker · {completed}/{total} complete"
    if current:
        summary += f" · Current: {current[:90]}"
    return summary


def _sync_guided_task_board_widget(self):
    if not hasattr(self, "task_board_card"):
        return
    if not self._guided_task_board:
        self.task_board_card.setVisible(False)
        self.task_board_title_label.setText("Project Tracker")
        self.task_board_goal_label.clear()
        self.task_board_body_label.clear()
        self.task_board_card.setToolTip("")
        self.project_tracker_changed.emit()
        return
    goal = (self._guided_task_board_goal or self._latest_non_continue_user_goal()).strip()
    self.task_board_title_label.setText(self._compact_guided_task_board_summary())
    task_lines = [
        f"{self._guided_task_board_marker(task.get('status', 'pending'))} {str(task.get('status', 'pending')).upper():8} {task.get('title', '')}"
        for task in self._guided_task_board
    ]
    tooltip_lines = ["Tracked in the left Project Tracker panel."]
    if goal:
        tooltip_lines.append(f"Goal: {goal[:220]}")
    tooltip_lines.extend(task_lines)
    self.task_board_goal_label.clear()
    self.task_board_goal_label.setVisible(False)
    self.task_board_body_label.clear()
    self.task_board_body_label.setVisible(False)
    self.task_board_card.setToolTip("\n".join(tooltip_lines))
    self.task_board_card.setVisible(True)
    self.project_tracker_changed.emit()


def _trimmed_diff_preview(diff_text: str, max_lines: int = 18, max_chars: int = 1800) -> str:
    lines = []
    for raw_line in str(diff_text or "").splitlines():
        line = raw_line.rstrip()
        if line.startswith(("@@", "+", "-")):
            lines.append(line)
        elif not lines and line:
            lines.append(line)
        if len(lines) >= max_lines:
            break
    preview = "\n".join(lines) if lines else str(diff_text or "").strip()
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip() + "\n..."
    return preview or "(diff preview unavailable)"


def _bounded_diff_text(diff_text: str, max_chars: int = 12000) -> str:
    text = str(diff_text or "")
    return text[:max_chars].rstrip() + ("\n..." if len(text) > max_chars else "")


def _display_tracker_path(self, file_path: str) -> str:
    normalized = str(file_path or "").replace("\\", "/")
    try:
        root = get_project_root().replace("\\", "/")
        if normalized and root and os.path.isabs(normalized):
            return os.path.relpath(normalized, root).replace("\\", "/")
    except Exception:
        pass
    return normalized or "(unknown file)"


def _record_session_change(self, file_path: str, diff_text: str):
    bounded_diff = self._bounded_diff_text(diff_text)
    entry = {
        "file_path": str(file_path or ""),
        "display_path": self._display_tracker_path(file_path),
        "diff_preview": self._trimmed_diff_preview(bounded_diff),
        "diff_text": bounded_diff,
    }
    if self._session_change_log:
        last = self._session_change_log[-1]
        if last.get("display_path") == entry["display_path"] and last.get("diff_text") == entry["diff_text"]:
            return
    self._session_change_log.append(entry)
    self._session_change_log = self._session_change_log[-30:]
    self.project_tracker_changed.emit()


def project_tracker_state(self) -> dict:
    return {
        "goal": self._guided_task_board_goal or self._latest_non_continue_user_goal(),
        "current_task": self._guided_current_task_title(),
        "source": str(getattr(self, "_guided_task_board_source", "fallback") or "fallback"),
        "stall_count": int(getattr(self, "_guided_current_task_stall_count", 0) or 0),
        "tasks": [dict(task) for task in self._guided_task_board],
        "session_changes": [dict(change) for change in self._session_change_log],
    }


def _reset_guided_task_board(self, goal_text: str | None = None, preserve_existing: bool = False):
    goal = str(goal_text or "").strip()
    if goal and not self._is_continue_directive(goal):
        self._guided_task_board_goal = goal[:500]
    elif not self._guided_task_board_goal:
        self._guided_task_board_goal = self._latest_non_continue_user_goal()
    if not preserve_existing or not self._guided_task_board:
        self._guided_task_board = self._default_guided_task_board()
        self._guided_task_board_source = "fallback"
    self._guided_task_board_updated_this_turn = False
    self._clear_guided_current_task_stall()
    self._refresh_guided_task_board()


def _refresh_guided_task_board(self):
    if not self._guided_task_board:
        if not (self._guided_task_board_goal or self.messages or self._guided_takeoff_active()):
            self._sync_guided_task_board_widget()
            return
        self._guided_task_board = self._default_guided_task_board()
        self._guided_task_board_source = "fallback"
    if str(getattr(self, "_guided_task_board_source", "fallback") or "fallback") == "llm":
        self._guided_task_board = self._sanitize_guided_task_board(self._guided_task_board)
        self._sync_guided_task_board_widget()
        return
    completed_ids = set()
    flags = set(self._pending_summary_guard_flags or set())
    has_initial_evidence = self._guided_takeoff_stage >= 2 or self._guided_phase_one_has_tool_evidence() or self._guided_direct_change_requested
    if has_initial_evidence:
        completed_ids.add("inspect")
    if self._guided_successful_edit_seen:
        completed_ids.add("target_and_edit")
    if self._guided_successful_edit_seen and not ({"no_validation", "no_post_edit_validation"} & flags):
        completed_ids.add("validate")
    if self._guided_autonomy_unlocked:
        completed_ids.add("rescan_and_report")
    current_id = next((task["id"] for task in self._guided_task_board if task.get("id") not in completed_ids), None)
    refreshed = []
    for task in self._guided_task_board:
        task_id = str(task.get("id", "")).strip() or f"task_{len(refreshed)}"
        title = str(task.get("title", "")).strip() or "Untitled task"
        if task_id in completed_ids:
            status = "complete"
        elif task_id == current_id:
            status = "current"
        else:
            status = "pending"
        refreshed.append({"id": task_id, "title": title, "status": status})
    self._guided_task_board = refreshed
    self._sync_guided_task_board_widget()


def _guided_task_board_prompt(self) -> str | None:
    self._refresh_guided_task_board()
    goal = self._guided_task_board_goal or self._latest_non_continue_user_goal()
    current_task = self._guided_current_task_title()
    validation_failure = self._guided_validation_failure_focus()
    lines = [
        "PERSISTENT TASK BOARD — THE MODEL MUST AUTHOR AND UPDATE THIS BOARD:",
        "On every Siege/guided turn, start your response with a hidden <task_board>...</task_board> block that YOU update.",
        "TASK BOARD FORMAT:",
        "<task_board>",
        "GOAL: short restatement of the current overall goal",
        "- [COMPLETE] finished task",
        "- [CURRENT] single actionable task to do now",
        "- [PENDING] later task",
        "</task_board>",
    ]
    if goal:
        lines.append(f"PRIMARY GOAL: {goal[:280]}")
    if current_task:
        lines.append(f"CURRENT TASK: {current_task[:220]}")
    if validation_failure:
        if validation_failure["commands"]:
            lines.append(f"LATEST FAILED VALIDATION COMMAND: {validation_failure['commands'][0][:220]}")
        if validation_failure["targets"]:
            lines.append(f"LIKELY FAILURE FIX TARGET: {validation_failure['targets'][0][:220]}")
    if self._guided_task_board:
        lines.append("LAST SAVED TASK BOARD (update this instead of resetting it):")
        for task in self._guided_task_board:
            lines.append(f"- [{task['status'].upper()}] {task['title']}")
    else:
        lines.append("No saved board exists yet. Create one with 3-6 tasks before anything else.")
    lines.extend([
        "RULES:",
        "- Keep exactly one CURRENT task whenever work remains.",
        "- You own this board: update statuses from the latest grounded evidence instead of rewriting the whole plan every turn.",
        "- Preserve COMPLETE tasks unless the latest TOOL_RESULT proves they reopened.",
        "- Take the next smallest step from the CURRENT task; if blocked, keep the board and explain the blocker.",
        "- If you start drifting, get lost, or reopen planning, return to the CURRENT task immediately instead of inventing a new plan.",
        "- Do NOT ask the user to reply 'continue' while the CURRENT task is still actionable.",
        "- If the latest validation command failed, the CURRENT task must stay on fixing/rerunning that failure until it is green or truly blocked.",
        "- Do NOT move CURRENT to README/docs/instructions/reporting or unrelated polish while validation is still failing.",
        "- After the <task_board> block, either emit tool XML for the next action or give a grounded blocker/user update.",
    ])
    return "\n".join(lines)


def _serialize_agent_state(self) -> dict:
    self._refresh_guided_task_board()
    return {
        "phased_task_anchor": self._phased_task_anchor,
        "pending_phased_tools": [dict(tool) for tool in (self._pending_phased_tools or []) if isinstance(tool, dict)],
        "guided_takeoff_stage": self._guided_takeoff_stage,
        "guided_autonomy_unlocked": self._guided_autonomy_unlocked,
        "guided_direct_change_requested": self._guided_direct_change_requested,
        "guided_phase_anchor": self._guided_phase_anchor,
        "guided_successful_edit_seen": self._guided_successful_edit_seen,
        "guided_no_progress_cycles": self._guided_no_progress_cycles,
        "guided_same_target_probe_count": self._guided_same_target_probe_count,
        "guided_bounded_start_probe_count": self._guided_bounded_start_probe_count,
        "guided_noop_edit_targets": list(self._guided_noop_edit_targets or []),
        "guided_exact_match_retry_targets": list(self._guided_exact_match_retry_targets or []),
        "pending_summary_guard_flags": sorted(self._pending_summary_guard_flags or set()),
        "pending_summary_grounded_files": list(self._pending_summary_grounded_files or []),
        "guided_task_board_goal": self._guided_task_board_goal,
        "guided_task_board": [dict(task) for task in self._guided_task_board],
        "guided_task_board_source": str(getattr(self, "_guided_task_board_source", "fallback") or "fallback"),
        "guided_current_task_stall_count": int(getattr(self, "_guided_current_task_stall_count", 0) or 0),
        "guided_last_current_task": str(getattr(self, "_guided_last_current_task", "") or ""),
        "session_change_log": [dict(change) for change in self._session_change_log],
    }


def _restore_agent_state(self, state: dict | None):
    state = state if isinstance(state, dict) else {}
    self._phased_task_anchor = str(state.get("phased_task_anchor", "") or "")
    self._pending_phased_tools = [dict(tool) for tool in (state.get("pending_phased_tools") or []) if isinstance(tool, dict)]
    self._guided_takeoff_stage = int(state.get("guided_takeoff_stage", 1) or 1)
    self._guided_autonomy_unlocked = bool(state.get("guided_autonomy_unlocked", False))
    self._guided_direct_change_requested = bool(state.get("guided_direct_change_requested", False))
    self._guided_phase_anchor = str(state.get("guided_phase_anchor", "") or "")
    self._guided_successful_edit_seen = bool(state.get("guided_successful_edit_seen", False))
    self._guided_no_progress_cycles = int(state.get("guided_no_progress_cycles", 0) or 0)
    self._guided_same_target_probe_count = int(state.get("guided_same_target_probe_count", 0) or 0)
    self._guided_bounded_start_probe_count = int(state.get("guided_bounded_start_probe_count", 0) or 0)
    self._guided_noop_edit_targets = [str(item) for item in (state.get("guided_noop_edit_targets") or []) if str(item).strip()]
    self._guided_exact_match_retry_targets = [
        self._normalize_summary_path(item)
        for item in (state.get("guided_exact_match_retry_targets") or [])
        if self._normalize_summary_path(item)
    ]
    self._pending_summary_guard_flags = set(state.get("pending_summary_guard_flags") or [])
    self._pending_summary_grounded_files = [
        self._normalize_summary_path(item)
        for item in (state.get("pending_summary_grounded_files") or [])
        if self._normalize_summary_path(item)
    ]
    self._guided_task_board_goal = str(state.get("guided_task_board_goal", "") or "") or self._latest_non_continue_user_goal()
    self._guided_task_board_source = str(state.get("guided_task_board_source", "fallback") or "fallback")
    self._guided_current_task_stall_count = int(state.get("guided_current_task_stall_count", 0) or 0)
    self._guided_last_current_task = str(state.get("guided_last_current_task", "") or "")
    self._guided_task_board_updated_this_turn = False
    saved_board = state.get("guided_task_board") or []
    if isinstance(saved_board, list) and saved_board:
        self._guided_task_board = self._sanitize_guided_task_board([
            {
                "id": str(task.get("id", "")).strip() or f"task_{idx}",
                "title": str(task.get("title", "")).strip() or "Untitled task",
                "status": self._guided_task_status(task.get("status")),
            }
            for idx, task in enumerate(saved_board)
            if isinstance(task, dict)
        ])
    else:
        self._guided_task_board = self._default_guided_task_board() if self._guided_task_board_goal else []
        if self._guided_task_board:
            self._guided_task_board_source = "fallback"
    self._session_change_log = [
        {
            "file_path": str(change.get("file_path", "") or ""),
            "display_path": str(change.get("display_path", "") or self._display_tracker_path(change.get("file_path", ""))),
            "diff_preview": self._trimmed_diff_preview(change.get("diff_preview", "") or change.get("diff_text", "")),
            "diff_text": self._bounded_diff_text(change.get("diff_text", "") or change.get("diff_preview", "")),
        }
        for change in (state.get("session_change_log") or [])
        if isinstance(change, dict)
    ]
    self._refresh_guided_task_board()


def _guided_takeoff_active(self) -> bool:
    return not self._guided_autonomy_unlocked


__all__ = [name for name in globals() if name.startswith("_") or name == "project_tracker_state"]