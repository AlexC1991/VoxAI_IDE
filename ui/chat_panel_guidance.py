import os
import re

from PySide6.QtCore import QTimer

from core.agent_tools import get_project_root
from core.code_parser import CodeParser


def _guided_task_board_focus_hint(self) -> str:
    current = self._guided_current_task_title()
    if not current:
        return ""
    return (
        f"\nCURRENT TASK FROM THE PERSISTENT TASK BOARD: {current}."
        " If you drift, get lost, or start re-planning, return to this task instead of inventing a new plan or asking the user to reply 'continue'."
    )


def _guided_takeoff_prompt(self, user_text: str | None = None) -> str | None:
    if not self._guided_takeoff_active():
        return None
    if self._is_siege_mode() and self._guided_takeoff_stage <= 1:
        if self._guided_direct_change_requested:
            return (
                "GUIDED TAKEOFF (BOUNDED START):\n"
                "The user explicitly asked for a change, but you are still on a short leash.\n"
                "1. Start with the smallest useful batch, not a repo-wide campaign.\n"
                "2. Prefer one issue and one narrow tool batch at a time.\n"
                "3. After the first grounded batch, give the user a clear checkpoint instead of over-claiming success."
            )
        if self._guided_navigation_request_detected():
            return (
                "GUIDED TAKEOFF (NAVIGATION BOUNDED START):\n"
                "This task explicitly asks for grounded navigation/reporting, so start with one tiny navigation batch.\n"
                "1. Prefer <find_symbol>, <get_imports>, <find_importers>, and <find_tests> before writing any report.\n"
                "2. Do NOT write the report or summary until at least one real navigation batch has grounded it.\n"
                "3. Keep the first batch small and concrete instead of narrating intended tool use."
            )
    if self._guided_takeoff_stage <= 1:
        return (
            "GUIDED TAKEOFF — STAGE 1 (INSPECT, THEN CHECK IN):\n"
            "You are NOT in full autonomy yet.\n"
            "1. Use 3-5 inspection-focused tools in this first phase unless one earlier tool already proves a concrete issue.\n"
            "2. Prefer <find_tests>, <get_imports>, <find_importers>, <find_symbol>, <find_references>, <read_python_symbols>, <find_files>, <list_files>, <search_files>, <read_file>, <read_json>, <get_file_structure>, and <search_codebase>.\n"
            "3. Unless the user explicitly asked for code changes right now, do NOT modify files or run validation in phase 1.\n"
            "4. After the tools, respond directly to the user with this handoff structure: Finding 1 / Evidence / Recommended next step / Follow-up for you. The follow-up may explicitly invite the user to reply 'continue'.\n"
            "5. Do NOT paste raw tool output or large code excerpts into the Phase 1 handoff.\n"
            "6. Do not try to solve the whole task in one leap."
        )
    anchor_text = ""
    if self._guided_phase_anchor:
        anchor_text = f"\nPHASE 1 ANCHOR (use this instead of reopening broad exploration):\n{self._guided_phase_anchor[:700]}"
    return (
        "GUIDED TAKEOFF — STAGE 2 (ONE ISSUE, ONE FIX CYCLE):\n"
        "You still have guard rails.\n"
        "1. Pick the single highest-confidence issue from the latest evidence.\n"
        "2. Make the smallest safe change that addresses it.\n"
        "3. Run minimal validation after the edit and do one fresh post-edit inspection/rescan.\n"
        "4. Then respond to the user with exactly what changed, what validation ran, and the next best step.\n"
        "5. Do not branch into multiple unrelated fixes unless the user explicitly asks.\n"
        "6. If the latest TOOL_RESULT already identified the likely fix target, do NOT spend this turn on another broad investigation sweep.\n"
        "7. In Stage 2, do NOT describe intended tools, pseudo-commands, or example shell steps. Either emit real tool XML for the next batch or give a grounded blocker summary."
        f"{anchor_text}"
    )


def _guided_tool_limit(self) -> int | None:
    if not self._guided_takeoff_active():
        return None
    if self._guided_takeoff_stage <= 1:
        if self._guided_direct_change_requested:
            return 3
        return 5
    limit = 4
    if self._guided_no_progress_cycles >= 1:
        limit = min(limit, 2)
    return limit


def _guided_takeoff_allows_tool(self, cmd: str) -> bool:
    if not self._guided_takeoff_active():
        return True
    if self._guided_takeoff_stage > 1 or self._guided_direct_change_requested:
        return True
    return cmd in {
        "find_tests", "get_imports", "find_importers", "find_symbol", "find_references",
        "read_python_symbols", "find_files", "list_files", "search_files", "read_file",
        "read_json", "get_file_structure", "search_codebase", "search_memory", "git_status", "git_diff",
    }


def _guided_is_narrow_context_tool(call: dict) -> bool:
    cmd = call.get("cmd", "")
    if cmd not in {"read_file", "read_json", "read_python_symbols", "get_imports", "get_file_structure"}:
        return False
    args = call.get("args") or {}
    return bool(str(args.get("path") or "").strip())


def _guided_prefer_fix_batch(self, tools: list[dict], limit: int) -> list[dict] | None:
    if self._guided_takeoff_stage < 2 or limit <= 0:
        return None
    target_index = next(
        (i for i, call in enumerate(tools) if self._guided_is_edit_tool(call.get("cmd", "")) or self._guided_is_validation_tool(call.get("cmd", ""))),
        None,
    )
    if target_index is None or target_index < limit:
        return None
    kept_indexes = [target_index]
    for i in range(target_index + 1, len(tools)):
        if len(kept_indexes) >= limit:
            break
        candidate = tools[i]
        cmd = candidate.get("cmd", "")
        if self._guided_is_validation_tool(cmd) or self._guided_is_narrow_context_tool(candidate):
            kept_indexes.append(i)
    for i in range(target_index - 1, -1, -1):
        if len(kept_indexes) >= limit:
            break
        candidate = tools[i]
        if self._guided_is_narrow_context_tool(candidate):
            kept_indexes.append(i)
    for i in range(target_index - 1, -1, -1):
        if len(kept_indexes) >= limit:
            break
        candidate = tools[i]
        cmd = candidate.get("cmd", "")
        if i in kept_indexes or cmd not in {"find_tests", "find_symbol", "find_references", "find_importers", "find_files", "search_files", "search_codebase", "get_file_structure"}:
            continue
        kept_indexes.append(i)
    if len(kept_indexes) < limit:
        for i in range(target_index):
            if len(kept_indexes) >= limit:
                break
            candidate = tools[i]
            if i in kept_indexes or not self._guided_is_narrow_context_tool(candidate):
                continue
            kept_indexes.append(i)
    kept_indexes.sort()
    return [tools[i] for i in kept_indexes]


def _guided_takeoff_filter_tools(self, tools: list[dict]) -> tuple[list[dict], str | None]:
    if not tools or not self._guided_takeoff_active():
        return tools, None
    filtered = [call for call in tools if self._guided_takeoff_allows_tool(call.get("cmd", ""))]
    if self._guided_navigation_request_detected() and not self._guided_navigation_evidence_seen():
        nav_tools = self._guided_navigation_tool_names()
        if not any(call.get("cmd", "") in nav_tools for call in filtered or tools):
            navigation_probe = self._guided_navigation_probe_tools()
            if navigation_probe:
                return navigation_probe, "[Guided takeoff inserted one grounding navigation batch before any report-writing or summary turn.]"
    if not filtered:
        return [], (
            "GUIDED TAKEOFF HELD BACK THE PREVIOUS TOOL BATCH:\n"
            "Phase 1 is inspection-first for this task. Use at most 5 inspection tools or write the Phase 1 summary with a follow-up for the user."
        )
    note = None
    if self._guided_navigation_request_detected():
        report_target = self._guided_navigation_report_target()
        if report_target:
            kept = [call for call in filtered if not self._guided_is_off_target_navigation_edit(call, report_target)]
            if len(kept) != len(filtered):
                note = (
                    f"[Guided takeoff removed unrelated file edits. For this navigation/report task, only write/edit {report_target}; keep source files read-only unless the user explicitly asks to modify them.]"
                )
            filtered = kept
            if not filtered:
                return [], (
                    "GUIDED TAKEOFF HELD BACK THE PREVIOUS TOOL BATCH:\n"
                    f"This is a navigation/report task. Ground the report with navigation tools first, and only write/edit {report_target}. Do not modify unrelated source files."
                )
    limit = self._guided_tool_limit()
    if limit is not None and len(filtered) > limit:
        kept = self._guided_prefer_fix_batch(filtered, limit) or filtered[:limit]
        held_back = len(filtered) - len(kept)
        if kept != filtered[:limit]:
            return kept, _merge_guided_notes(
                note,
                "[Guided takeoff preserved a smaller fix-oriented batch so the run can commit on the best-supported target instead of drifting through more broad inspection.]",
            )
        return kept, _merge_guided_notes(
            note,
            "[Guided takeoff limited this phase to the first "
            f"{limit} tool(s); {held_back} additional proposed tool(s) were held back so the run stays focused.]",
        )
    return filtered, note


def _assistant_summary_has_followup(self, text: str) -> bool:
    lowered = re.sub(r'[`*_#]+', '', str(text or "").lower())
    followup_cues = (
        "follow-up", "reply continue", "reply 'continue'", 'reply "continue"', "say continue", "would you like me to",
        "do you want me to", "which issue", "which finding", "should i proceed",
        "if you want, i can", "if you'd like, i can", "i can proceed", "ready to continue", "ready to proceed",
    )
    if any(cue in lowered for cue in followup_cues):
        return True
    return bool(
        re.search(r"\breply\b.{0,20}\bcontinue\b", lowered)
        or re.search(r"\b(i can|i am ready to|i'm ready to|i will)\s+(continue|proceed)\b", lowered)
    )


def _ensure_phase_one_followup(self, text: str) -> str:
    if self._guided_takeoff_stage != 1 or self._guided_direct_change_requested:
        return text
    if self._assistant_summary_has_followup(text):
        return text
    suffix = (
        "\n\nFollow-up for you: If you want me to take the recommended next step, reply 'continue', "
        "or tell me which finding you want me to prioritize first."
    )
    return (text or "").rstrip() + suffix


def _guided_takeoff_unlock_ready(self, tool_output: str) -> bool:
    flags = self._summary_guard_flags(tool_output)
    return (
        "no_file_changes" not in flags
        and "no_validation" not in flags
        and "no_post_edit_validation" not in flags
        and "no_post_edit_rescan" not in flags
    )


def _guided_phase_one_needs_pure_summary(self, tools: list[dict]) -> bool:
    return bool(tools and self._guided_takeoff_stage == 1 and not self._guided_direct_change_requested and self._phased_summary_pending and not self._is_siege_mode())


def _guided_phase_one_has_tool_evidence(self) -> bool:
    return any(m.get("role") == "system" and "[TOOL_RESULT]" in str(m.get("content", "")) for m in self.messages) or bool(self._tool_action_log or self._run_tool_action_log)


def _guided_phase_one_has_grounded_handoff(self, text: str) -> bool:
    narrative = str(text or "").strip()
    if not narrative:
        return False
    return bool(re.search(r'\b(finding|issue|problem|bug|risk|evidence|recommended next step|grounded status|recommend)\b', narrative, re.IGNORECASE))


def _guided_phase_one_evidence_is_shallow(self) -> bool:
    latest_batch = list(self._tool_calls_for_run or [])
    return bool(latest_batch) and all(cmd == "list_files" for cmd in latest_batch)


def _guided_phase_one_needs_real_inspection(self, tools: list[dict], response_text: str) -> bool:
    return bool(not tools and self._guided_takeoff_stage == 1 and not self._guided_direct_change_requested and self._phased_summary_pending and not self._is_siege_mode() and not self._guided_phase_one_has_tool_evidence() and not self._guided_phase_one_has_grounded_handoff(response_text))


def _guided_phase_one_needs_grounded_handoff(self, tools: list[dict], response_text: str) -> bool:
    return bool(not tools and self._guided_takeoff_stage == 1 and not self._guided_direct_change_requested and self._phased_summary_pending and not self._is_siege_mode() and self._guided_phase_one_has_tool_evidence() and not self._guided_phase_one_evidence_is_shallow() and not self._guided_phase_one_has_grounded_handoff(response_text))


def _guided_phase_one_needs_more_targeted_inspection(self, tools: list[dict], response_text: str) -> bool:
    return bool(not tools and self._guided_takeoff_stage == 1 and not self._guided_direct_change_requested and self._phased_summary_pending and not self._is_siege_mode() and self._guided_phase_one_has_tool_evidence() and self._guided_phase_one_evidence_is_shallow() and not self._guided_phase_one_has_grounded_handoff(response_text))


def _guided_phase_one_summary_fallback(self, response_text: str) -> str:
    cleaned_lines = []
    tool_line_pattern = re.compile(r'^\s*<([a-z_]+)\b.*?/?>\s*$', re.IGNORECASE)
    for line in str(response_text or "").splitlines():
        if tool_line_pattern.match(line.strip()):
            continue
        cleaned_lines.append(line)
    narrative = "\n".join(cleaned_lines).strip()
    useful = bool(re.search(r'\b(finding|issue|problem|bug|risk|recommend|evidence)\b', narrative, re.IGNORECASE))
    if not useful:
        narrative = (
            "[Guided takeoff paused here because Phase 1 should end with a short user-facing handoff, and the inspection results were not turned into grounded findings yet.]\n\n"
            "Grounded status: the first inspection phase ran, and no files were changed in Phase 1.\n"
            "Recommended next step: continue with one narrow follow-up inspection or one concrete fix for the best-supported issue."
        )
    return self._ensure_phase_one_followup(narrative)


def _guided_update_phase_anchor(self, summary_text: str):
    text = str(summary_text or "").strip()
    if not text:
        self._guided_phase_anchor = ""
        return
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    self._guided_phase_anchor = "\n".join(lines[:6])[:900]


def _guided_is_investigation_tool(cmd: str) -> bool:
    return cmd in {
        "find_tests", "get_imports", "find_importers", "find_symbol", "find_references", "read_python_symbols",
        "find_files", "list_files", "search_files", "read_file", "read_json", "get_file_structure",
        "search_codebase", "search_memory", "git_status", "git_diff",
    }


def _guided_is_edit_tool(cmd: str) -> bool:
    return cmd in {"write_file", "edit_file", "delete_file", "rename_file", "move_file"}


def _guided_navigation_tool_names() -> set[str]:
    return {"find_tests", "get_imports", "find_importers", "find_symbol", "find_references", "read_python_symbols"}


def _guided_is_validation_tool(cmd: str) -> bool:
    return cmd in {"execute_command", "git_status", "git_diff"}


def _guided_extract_target_hints(*texts: str) -> list[str]:
    hints: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(r'([A-Za-z0-9_./\\-]+\.(?:py|bat|txt|md|json|yaml|yml|ini|cfg))', re.IGNORECASE)
    for text in texts:
        for match in pattern.findall(str(text or "")):
            cleaned = match.strip("`'\" ")
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            hints.append(cleaned)
            if len(hints) >= 3:
                return hints
    return hints


def _guided_extract_symbol_hints(*texts: str) -> list[str]:
    hints: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b')
    for text in texts:
        for match in pattern.findall(str(text or "")):
            cleaned = match.strip("`'\" ")
            lowered = cleaned.lower()
            if "/" in cleaned or "\\" in cleaned or lowered.endswith((".py", ".md", ".json", ".yaml", ".yml", ".ini", ".cfg", ".txt", ".bat")):
                continue
            if lowered in seen:
                continue
            seen.add(lowered)
            hints.append(cleaned)
            if len(hints) >= 3:
                return hints
    return hints


def _merge_guided_notes(*notes: str | None) -> str | None:
    parts = [str(note or "").strip() for note in notes if str(note or "").strip()]
    if not parts:
        return None
    return "\n".join(parts)


def _guided_navigation_request_detected(self) -> bool:
    navigation_text = "\n".join(part for part in (self._latest_non_continue_user_goal(), self._guided_task_board_goal, self._guided_phase_anchor) if str(part or "").strip())
    if not navigation_text:
        return False
    return bool(re.search(r'(\buse navigation tools\b|\bfind where\b|\bwhere .* defined\b|\bwhat it imports\b|\bwhat imports it\b|\bwhich tests cover\b|\bfind_tests\b|\bget_imports\b|\bfind_importers\b|\bfind_symbol\b|\bfind_references\b|\bbenchmark_report\.md\b)', navigation_text, re.IGNORECASE))


def _guided_navigation_evidence_seen(self) -> bool:
    nav_tools = self._guided_navigation_tool_names()
    return any(cmd in nav_tools for cmd in list(self._run_tool_calls or []) + list(self._tool_calls_for_run or []))


def _guided_navigation_report_target(self) -> str | None:
    for target in self._guided_extract_target_hints(self._latest_non_continue_user_goal(), self._guided_task_board_goal, self._guided_phase_anchor):
        lowered = str(target or "").lower()
        if lowered.endswith((".md", ".txt")):
            return self._normalize_summary_path(target) or str(target or "").strip()
    return None


def _guided_project_start_request_detected(self) -> bool:
    goal_text = "\n".join(
        part for part in (self._latest_non_continue_user_goal(), self._guided_task_board_goal)
        if str(part or "").strip()
    )
    lowered = goal_text.lower()
    cues = (
        "new project", "from scratch", "folder is empty", "empty folder", "empty workspace",
        "starter", "basic runnable", "tiny project", "small project", "minimum files needed",
        "runnable cli", "readme.md", "this folder is empty", "start a very small",
    )
    return bool(goal_text and any(cue in lowered for cue in cues))


def _guided_project_start_required_files(self) -> list[str]:
    if not self._guided_project_start_request_detected():
        return []
    allowed_exts = (".py", ".md", ".txt", ".json", ".yaml", ".yml", ".ini", ".cfg", ".bat")
    targets = []
    seen = set()
    for target in self._guided_extract_target_hints(self._latest_non_continue_user_goal(), self._guided_task_board_goal):
        normalized = self._normalize_summary_path(target)
        lowered = normalized.lower()
        if not normalized or not lowered.endswith(allowed_exts) or lowered in seen:
            continue
        seen.add(lowered)
        targets.append(normalized)
    return targets[:4]


def _guided_project_start_required_commands(self) -> list[str]:
    if not self._guided_project_start_request_detected():
        return []
    goal_text = "\n".join(
        part for part in (self._latest_non_continue_user_goal(), self._guided_task_board_goal)
        if str(part or "").strip()
    )
    if not re.search(r'\b(run|running|execute|executing|validate|validation|rerun|smoke test)\b', goal_text, re.IGNORECASE):
        return []
    commands = []
    seen = set()
    pattern = re.compile(
        r'(?:run(?:ning)?|rerun(?:ning)?|execute(?:d|ing)?|validate(?:\s+it)?\s+by\s+running)\s+'
        r'((?:python|python3(?:\.[0-9]+)?)\s+[A-Za-z0-9_./\\-]+)',
        re.IGNORECASE,
    )
    for match in pattern.finditer(goal_text):
        command = " ".join(match.group(1).split()).rstrip('.,;:')
        lowered = command.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        commands.append(command)
    return commands[:3]


def _guided_project_start_requested_run_command(self) -> str | None:
    commands = self._guided_project_start_required_commands()
    if not commands:
        return None
    known_files = set()
    for path in list(self._guided_project_start_required_files()) + list(self._guided_recent_validation_targets()):
        normalized = self._normalize_summary_path(path)
        if not normalized:
            continue
        known_files.add(normalized.lower())
        known_files.add(os.path.basename(normalized).lower())
    for command in commands:
        parts = command.split()
        if len(parts) < 2:
            continue
        target = self._normalize_summary_path(parts[1])
        if not target:
            continue
        lowered = target.lower()
        base = os.path.basename(target).lower()
        if not known_files or lowered in known_files or base in known_files:
            return command
    return commands[0]


def _guided_project_start_completed_files(self) -> set[str]:
    aliases = set()
    for change in self._session_change_log or []:
        normalized = self._normalize_summary_path(change.get("file_path") or change.get("display_path"))
        if not normalized:
            continue
        aliases.add(normalized.lower())
        aliases.add(os.path.basename(normalized).lower())
    for candidate in self._pending_summary_grounded_files or []:
        normalized = self._normalize_summary_path(candidate)
        if not normalized:
            continue
        aliases.add(normalized.lower())
        aliases.add(os.path.basename(normalized).lower())
    return aliases


def _guided_project_start_completed_commands(self) -> set[str]:
    commands = set()
    for title, status in self._parse_tool_action_log(self._run_tool_action_log or self._tool_action_log):
        if status != "Done" or not title.startswith("Executed:"):
            continue
        command = " ".join(title.split(":", 1)[1].split()).lower()
        if command:
            commands.add(command)
    return commands


def _guided_project_start_missing_requirements(self) -> dict[str, list[str]]:
    required_files = self._guided_project_start_required_files()
    required_commands = self._guided_project_start_required_commands()
    if not required_files and not required_commands:
        return {"missing_files": [], "missing_commands": []}
    completed_files = self._guided_project_start_completed_files()
    completed_commands = self._guided_project_start_completed_commands()
    missing_files = [
        path for path in required_files
        if path.lower() not in completed_files and os.path.basename(path).lower() not in completed_files
    ]
    missing_commands = []
    for command in required_commands:
        lowered = command.lower()
        if any(done == lowered or done.startswith(lowered) or lowered.startswith(done) for done in completed_commands):
            continue
        missing_commands.append(command)
    return {"missing_files": missing_files, "missing_commands": missing_commands}


def _guided_project_start_requirements_prompt(self, response_text: str | None = None) -> str | None:
    if not self._is_siege_mode() or not self._guided_phase_one_has_tool_evidence():
        return None
    missing = self._guided_project_start_missing_requirements()
    missing_files = missing["missing_files"]
    missing_commands = missing["missing_commands"]
    if not missing_files and not missing_commands:
        return None
    text = str(response_text or "").strip()
    if self._guided_is_grounded_blocker_summary(text) or re.search(r'\b(blocker|cannot|can\'t|unable|need user|need permission|need a decision)\b', text, re.IGNORECASE):
        return None
    requirements = []
    if missing_files:
        requirements.append(f"Missing required file(s): {', '.join(missing_files)}.")
    if missing_commands:
        requirements.append(f"Missing required validation/run command(s): {', '.join(missing_commands)}.")
    finish_hint = ""
    if missing_files and missing_commands:
        finish_hint = "Finish the remaining starter deliverables in one compact batch: create the missing file(s), run the exact requested command, and do at most one small read only if you need a final grounded check."
    elif missing_files:
        finish_hint = "Create the missing named file(s) now instead of reopening investigation."
    elif missing_commands:
        finish_hint = "Run the exact requested command now instead of substituting a different validation step."
    return (
        "GUIDED COMPLETION GATE — EXPLICIT PROJECT-START REQUIREMENTS ARE STILL MISSING:\n"
        "The user explicitly asked for a tiny starter project, and the run does not yet satisfy every named deliverable.\n"
        f"{' '.join(requirements)}\n"
        "Do NOT claim the starter is complete yet.\n"
        "Your next reply must be either valid tool XML only for the smallest batch that finishes the missing requirement(s), or a grounded blocker summary with one follow-up question.\n"
        f"Prefer completing the missing file or requested run command directly instead of reopening broad investigation. {finish_hint}"
    )


def _guided_current_task_requires_action(self) -> bool:
    current = str(self._guided_current_task_title() or "").strip().lower()
    if not current:
        return False
    action_tokens = (
        "fix", "edit", "apply", "add", "create", "write", "implement", "build", "run", "rerun",
        "validate", "test", "execute", "polish", "update", "finish", "complete", "ship",
    )
    passive_prefixes = ("inspect", "read", "review", "gather", "identify", "analyze", "audit evidence", "explore", "scan")
    if current.startswith(passive_prefixes) and not any(token in current for token in action_tokens):
        return False
    return any(token in current for token in action_tokens)


def _guided_validation_failure_focus(self) -> dict | None:
    flags = set(self._pending_summary_guard_flags or set())
    if not ({"validation_failed", "post_edit_validation_failed"} & flags):
        return None
    commands = list(self._failed_validation_commands())
    targets = []
    seen = set()
    for candidate in list(self._guided_recent_validation_targets()) + list(self._guided_concrete_target_context()) + list(self._guided_extract_target_hints(self._guided_phase_anchor)):
        normalized = self._normalize_summary_path(candidate)
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        targets.append(normalized)
    current = str(self._guided_current_task_title() or "").strip()
    lowered_current = current.lower()
    target_aliases = {alias for path in targets for alias in (path.lower(), os.path.basename(path).lower()) if alias}
    mentions_target = any(alias in lowered_current for alias in target_aliases)
    mentions_command = any(command.lower() in lowered_current for command in commands if command)
    failure_tokens = (
        "fix", "repair", "debug", "resolve", "rerun", "re-run", "test", "tests", "pytest", "self-test",
        "validation", "validate", "failing", "failure", "bug", "error", "audit fix", "apply",
    )
    unrelated_tokens = ("readme", "docs", "documentation", "instructions", "controls", "report", "reporting")
    on_failure_path = any(token in lowered_current for token in failure_tokens) or mentions_target or mentions_command
    conflicts = (not current) or (any(token in lowered_current for token in unrelated_tokens) and not on_failure_path) or not on_failure_path
    return {
        "commands": commands[:2],
        "targets": targets[:3],
        "current_task": current,
        "current_conflicts": conflicts,
    }


def _guided_validation_failure_hint_text(self) -> str:
    focus = self._guided_validation_failure_focus()
    if not focus:
        return ""
    pieces = []
    if focus["commands"]:
        pieces.append(f"Failing validation command: {focus['commands'][0]}.")
    if focus["targets"]:
        pieces.append(f"Stay on the failing code path around: {', '.join(focus['targets'][:2])}.")
    if not pieces:
        pieces.append("Stay on the failing validation path until it is fixed, rerun, or truly blocked.")
    return "\n" + " ".join(pieces)


def _guided_is_off_target_navigation_edit(self, call: dict, report_target: str | None) -> bool:
    if not report_target or not self._guided_is_edit_tool(call.get("cmd", "")):
        return False
    path = self._normalize_summary_path((call.get("args") or {}).get("path"))
    if not path:
        return False
    return path.lower() != report_target.lower()


def _guided_navigation_probe_tools(self) -> list[dict]:
    if not self._guided_navigation_request_detected():
        return []
    symbols = self._guided_extract_symbol_hints(self._latest_non_continue_user_goal(), self._guided_task_board_goal, self._guided_phase_anchor, getattr(self, "current_ai_response", ""))
    if symbols:
        primary = symbols[0]
        return [
            {"cmd": "find_symbol", "args": {"symbol": primary, "root_dir": "."}},
            {"cmd": "find_tests", "args": {"query": primary}},
        ]
    py_target = next((target for target in self._guided_extract_target_hints(self._latest_non_continue_user_goal(), self._guided_task_board_goal, self._guided_phase_anchor) if str(target or "").lower().endswith(".py")), None)
    if py_target:
        return [
            {"cmd": "get_imports", "args": {"path": py_target, "include_external": False}},
            {"cmd": "find_tests", "args": {"source_path": py_target}},
        ]
    return []


def _guided_recent_target_hints(self) -> list[str]:
    return self._guided_extract_target_hints("\n".join(self._tool_action_log or []), "\n".join(self._run_tool_action_log or []), self._guided_phase_anchor)


def _guided_current_fix_targets(self) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for candidate in list(self._guided_exact_match_retry_targets or []) + list(self._guided_noop_edit_targets or []) + self._guided_recent_target_hints():
        normalized = self._normalize_summary_path(candidate)
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        targets.append(normalized)
        if len(targets) >= 3:
            break
    return targets


def _guided_concrete_target_context(self) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for candidate in list(self._guided_exact_match_retry_targets or []) + list(self._guided_noop_edit_targets or []):
        normalized = self._normalize_summary_path(candidate)
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        targets.append(normalized)
        if len(targets) >= 3:
            return targets
    for candidate in self._guided_extract_target_hints(self._guided_phase_anchor):
        normalized = self._normalize_summary_path(candidate)
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        targets.append(normalized)
        if len(targets) >= 3:
            return targets
    if self._pending_summary_grounded_files:
        for candidate in self._pending_summary_grounded_files:
            normalized = self._normalize_summary_path(candidate)
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            targets.append(normalized)
            if len(targets) >= 3:
                return targets
    return targets


def _guided_requires_same_target_edit_now(self) -> bool:
    if not self._is_siege_mode() or not self._guided_takeoff_active() or self._guided_takeoff_stage < 2:
        return False
    if self._guided_successful_edit_seen or not self._guided_concrete_target_context():
        return False
    return bool(self._guided_exact_match_retry_targets or self._guided_same_target_probe_count >= 1 or self._guided_no_progress_cycles >= 2)


def _guided_call_matches_targets(self, call: dict, targets: list[str]) -> bool:
    aliases = self._grounded_changed_file_aliases(targets)
    if not aliases:
        return False
    args = call.get("args") or {}
    for key in ("path", "src", "dst"):
        value = self._normalize_summary_path(args.get(key))
        if not value:
            continue
        lowered = value.lower()
        if lowered in aliases or os.path.basename(lowered) in aliases:
            return True
    return False


def _guided_exact_match_retry_hint(self) -> str:
    targets = self._guided_current_fix_targets()
    if not targets:
        return ""
    primary = targets[0]
    return (
        f"\nPreferred next batch shape (max 2 tools) for {primary}: "
        f"first one narrow <read_file path=\"{primary}\" with_line_numbers=\"true\" /> to copy the live text or line numbers, "
        f"then either one easy <edit_file ... /> on that SAME file (exact old_text/new_text, start_line/end_line, or insert_before/insert_after) or one <write_file path=\"{primary}\">...</write_file> rewrite if replacing the small function/file is simpler than another surgical patch."
    )


def _guided_tool_targets(tools: list[dict], edit_only: bool = False) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for call in tools or []:
        cmd = call.get("cmd", "")
        if edit_only and cmd not in {"write_file", "edit_file", "delete_file", "rename_file", "move_file"}:
            continue
        path = str((call.get("args") or {}).get("path") or "").strip()
        if not path:
            continue
        lowered = path.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        targets.append(path)
    return targets


def _guided_validation_hint_text(self) -> str:
    missing = self._guided_project_start_missing_requirements()
    requested_command = self._guided_project_start_requested_run_command()
    validation_targets = self._guided_recent_validation_targets()
    primary_target = validation_targets[0] if validation_targets else ""
    failure_focus = self._guided_validation_failure_focus()
    if failure_focus:
        fix_hint = ""
        if failure_focus["targets"]:
            primary_failure_target = failure_focus["targets"][0]
            fix_hint = f' re-read <read_file path="{primary_failure_target}" /> and make the smallest fix on that same target,'
        rerun_hint = f' then rerun <execute_command command="{failure_focus["commands"][0]}" cwd="." />' if failure_focus["commands"] else " then rerun the failing validation command"
        return f"\nConcrete failure-recovery hint:{fix_hint}{rerun_hint}."
    if requested_command and not missing["missing_files"]:
        read_hint = f' and then <read_file path="{primary_target}" />' if primary_target else ""
        return f"\nConcrete validation hint: run <execute_command command=\"{requested_command}\" cwd=\".\" />{read_hint} for the fresh post-edit check."
    recent_edit_targets = self._guided_tool_targets(self._tool_specs_for_run, edit_only=True)
    recent_py_file = next((path for path in recent_edit_targets if path.lower().endswith('.py')), None)
    if recent_py_file:
        return f"\nConcrete validation hint: run <execute_command command=\"python -m py_compile {recent_py_file}\" cwd=\".\" /> and then <read_file path=\"{recent_py_file}\" /> for the fresh post-edit check."
    recent_text_target = next((path for path in recent_edit_targets if path.lower().endswith(('.txt', '.md', '.json', '.yaml', '.yml', '.ini', '.cfg', '.bat')) or path.lower().endswith('requirements.txt')), None)
    if recent_text_target:
        command = self._text_validation_command(recent_text_target)
        return f"\nConcrete validation hint: run <execute_command command='{command}' cwd=\".\" /> and then <read_file path=\"{recent_text_target}\" /> for the fresh post-edit check."
    hints = self._guided_recent_target_hints()
    py_file = next((path for path in hints if path.lower().endswith('.py')), None)
    if py_file:
        return f"\nConcrete validation hint: run <execute_command command=\"python -m py_compile {py_file}\" cwd=\".\" /> and then <read_file path=\"{py_file}\" /> for the fresh post-edit check."
    text_file = next((path for path in hints if path.lower().endswith(('.txt', '.md', '.json', '.yaml', '.yml', '.ini', '.cfg', '.bat')) or path.lower().endswith('requirements.txt')), None)
    if text_file:
        command = self._text_validation_command(text_file)
        return f"\nConcrete validation hint: run <execute_command command='{command}' cwd=\".\" /> and then <read_file path=\"{text_file}\" /> for the fresh post-edit check."
    if hints:
        return f"\nConcrete validation hint: re-read {hints[0]} and run one small command that checks the expected change is present."
    return ""


def _guided_same_target_probe_tools(self) -> list[dict]:
    if not self._is_siege_mode() or not self._guided_takeoff_active() or self._guided_takeoff_stage < 2:
        return []
    if self._guided_successful_edit_seen or self._guided_same_target_probe_count >= 1:
        return []
    concrete_targets = self._guided_concrete_target_context()
    if not concrete_targets:
        return []
    primary = concrete_targets[0]
    latest_specs = list(self._tool_specs_for_run or [])
    if latest_specs and len(latest_specs) == 1:
        latest_cmd = latest_specs[0].get("cmd", "")
        if latest_cmd in {"read_file", "get_file_structure"} and self._guided_call_matches_targets(latest_specs[0], [primary]):
            return []
    target_path = os.path.join(get_project_root(), primary)
    if os.path.isdir(target_path):
        return [{"cmd": "get_file_structure", "args": {"path": primary}}]
    return [{"cmd": "read_file", "args": {"path": primary}}]


def _launch_guided_same_target_probe_batch(self, note: str) -> bool:
    probe_tools = self._guided_same_target_probe_tools()
    if not probe_tools:
        return False
    self._guided_same_target_probe_count += 1
    if self.current_ai_item:
        self.current_ai_item.set_text(note)
    self.append_message_widget("system", note)
    self.messages.append({"role": "system", "content": note})
    self.save_conversation()
    self._start_tool_execution(probe_tools)
    return True


def _guided_bounded_start_probe_tools(self) -> list[dict]:
    if not self._is_siege_mode() or not self._guided_takeoff_active() or self._guided_takeoff_stage > 1:
        return []
    navigation_start = self._guided_navigation_request_detected()
    if not self._guided_direct_change_requested and not navigation_start:
        return []
    if self._guided_bounded_start_probe_count >= 1 or self._guided_phase_one_has_tool_evidence():
        return []
    if navigation_start:
        navigation_tools = self._guided_navigation_probe_tools()
        if navigation_tools:
            return navigation_tools
    candidates = self._guided_concrete_target_context() or self._guided_extract_target_hints(self.current_ai_response, self._guided_phase_anchor)
    for candidate in candidates:
        target = str(candidate or "").strip()
        if not target:
            continue
        full_path = os.path.join(get_project_root(), target)
        if os.path.isdir(full_path):
            return [{"cmd": "get_file_structure", "args": {"path": target}}]
        if os.path.isfile(full_path):
            return [{"cmd": "read_file", "args": {"path": target}}]
    return [{"cmd": "list_files", "args": {"path": "."}}]


def _launch_guided_bounded_start_probe_batch(self, note: str) -> bool:
    probe_tools = self._guided_bounded_start_probe_tools()
    if not probe_tools:
        return False
    self._guided_bounded_start_probe_count += 1
    if self.current_ai_item:
        self.current_ai_item.set_text(note)
    self.append_message_widget("system", note)
    self.messages.append({"role": "system", "content": note})
    self.save_conversation()
    self._start_tool_execution(probe_tools)
    return True


def _shell_quote_path(path: str) -> str:
    return '"' + str(path or "").replace('"', '\\"') + '"'


def _text_validation_command(path: str) -> str:
    quoted = _shell_quote_path(path)
    if os.name == "nt":
        return f"type {quoted}"
    return f"cat {quoted}"


def _guided_recent_validation_targets(self) -> list[str]:
    targets = []
    seen = set()
    for candidate in list(self._pending_summary_grounded_files or []) + self._guided_tool_targets(self._tool_specs_for_run, edit_only=True):
        cleaned = str(candidate or "").strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        targets.append(cleaned)
    return targets[:3]


def _guided_auto_validation_tools(self) -> list[dict]:
    if not self._is_siege_mode() or not self._guided_successful_edit_seen:
        return []
    pending_flags = set(self._pending_summary_guard_flags or set())
    if {"validation_failed", "post_edit_validation_failed"} & pending_flags:
        return []
    needs_validation = bool({"no_validation", "no_post_edit_validation"} & pending_flags)
    needs_rescan = "no_post_edit_rescan" in pending_flags
    if not needs_validation and not needs_rescan:
        return []
    missing = self._guided_project_start_missing_requirements()
    if missing["missing_files"]:
        return []
    targets = self._guided_recent_validation_targets()
    if not targets:
        return []
    tools = []
    py_targets = [path for path in targets if path.lower().endswith('.py')]
    primary_target = targets[0]
    requested_command = self._guided_project_start_requested_run_command()
    if needs_validation:
        if requested_command:
            tools.append({"cmd": "execute_command", "args": {"command": requested_command, "cwd": "."}})
        elif py_targets:
            quoted = " ".join(self._shell_quote_path(path) for path in py_targets[:3])
            tools.append({"cmd": "execute_command", "args": {"command": f"python -m py_compile {quoted}", "cwd": "."}})
        else:
            tools.append({"cmd": "execute_command", "args": {"command": self._text_validation_command(primary_target), "cwd": "."}})
    if needs_rescan:
        tools.append({"cmd": "read_file", "args": {"path": primary_target}})
    return tools[:2]


def _launch_guided_auto_validation_batch(self, note: str) -> bool:
    auto_validation_tools = self._guided_auto_validation_tools()
    if not auto_validation_tools or self._auto_validation_retry_count >= 1:
        return False
    self._auto_validation_retry_count += 1
    if self.current_ai_item:
        self.current_ai_item.set_text(note)
    self.append_message_widget("system", note)
    self.messages.append({"role": "system", "content": note})
    self.save_conversation()
    self._start_tool_execution(auto_validation_tools)
    return True


def _guided_blank_response_extra_messages(self) -> list[str]:
    extra_messages = []
    guided_recovery = self._guided_recovery_prompt("")
    guided_prompt = self._guided_takeoff_prompt(None) if not guided_recovery else None
    if guided_recovery:
        extra_messages.append(guided_recovery)
    elif guided_prompt:
        extra_messages.append(guided_prompt)
    if self._pending_summary_guard_message:
        extra_messages.append(self._pending_summary_guard_message)
    return extra_messages


def _try_guided_blank_response_recovery(self) -> bool:
    if self._stop_requested:
        return False
    if self._launch_guided_auto_validation_batch("[Blank model response triggered a compact post-edit verification batch before ending the run.]"):
        return True
    if self._is_siege_mode() and self._guided_takeoff_active() and not self._guided_phase_one_has_tool_evidence():
        if self._launch_guided_bounded_start_probe_batch("[Blank model response triggered one minimal probe to ground the run before ending it.]"):
            return True
    if not self._is_siege_mode() or not self._guided_takeoff_active() or self._guided_takeoff_stage < 2:
        return False
    if self._guided_blank_response_retry_count >= 1:
        return False
    self._guided_blank_response_retry_count += 1
    retry_note = "[Model returned a blank response at a critical guided step; requesting a grounded rewrite automatically.]"
    if self.current_ai_item:
        self.current_ai_item.set_text(retry_note)
    self.notification_requested.emit("Blank Model Response", retry_note)
    extra_messages = self._guided_blank_response_extra_messages()
    QTimer.singleShot(
        0,
        lambda: self._start_ai_worker(
            "Your previous response was blank. Do NOT leave this turn empty. Rewrite it as either (A) valid tool XML only for the smallest required fix/validation batch, with no surrounding prose, or (B) a grounded blocker summary with one follow-up question.",
            [],
            extra_system_messages=extra_messages or None,
        ),
    )
    return True


def _blank_response_fallback_message(self) -> str:
    if self._is_siege_mode() and self._guided_takeoff_active() and self._guided_takeoff_stage >= 2:
        return self._guided_blocker_summary_fallback()
    return "[No response received from the model. The request completed without visible content. Please retry.]"


def _guided_decision_gate_prompt(self, tools: list[dict]) -> str | None:
    if not tools or not self._is_siege_mode() or not self._guided_takeoff_active() or self._guided_takeoff_stage < 2:
        return None
    cmds = [call.get("cmd", "") for call in tools]
    has_edit = any(self._guided_is_edit_tool(cmd) for cmd in cmds)
    has_validation = any(self._guided_is_validation_tool(cmd) for cmd in cmds)
    has_rescan = any(self._guided_is_investigation_tool(cmd) for cmd in cmds)
    investigation_only = all(self._guided_is_investigation_tool(cmd) for cmd in cmds)
    broad_investigation = any(cmd in {"find_tests", "find_symbol", "find_references", "find_importers", "find_files", "list_files", "search_files", "search_codebase", "search_memory", "git_status", "git_diff"} for cmd in cmds)
    pending_flags = set(self._pending_summary_guard_flags or set())
    needs_validation = bool({"no_validation", "no_post_edit_validation"} & pending_flags)
    needs_rescan = "no_post_edit_rescan" in pending_flags
    concrete_targets = self._guided_concrete_target_context()
    exact_targets = list(self._guided_exact_match_retry_targets or [])
    if exact_targets and "no_file_changes" in pending_flags and not self._guided_successful_edit_seen:
        allowed_cmds = {"read_file", "edit_file", "write_file"}
        targeted_reads = [call for call in tools if call.get("cmd") == "read_file" and self._guided_call_matches_targets(call, exact_targets)]
        targeted_edits = [call for call in tools if call.get("cmd") == "edit_file" and self._guided_call_matches_targets(call, exact_targets)]
        all_allowed = all(cmd in allowed_cmds for cmd in cmds)
        all_targeted = all(self._guided_call_matches_targets(call, exact_targets) for call in tools if call.get("cmd") in allowed_cmds)
        if len(tools) > 2 or not all_allowed or not all_targeted or broad_investigation or (targeted_edits and not targeted_reads):
            return (
                "GUIDED DECISION GATE — RESOLVE THE FAILED EDIT NOW:\n"
                "The previous edit failed because the requested live target was not matched uniquely. Do NOT switch back to broad investigation yet.\n"
                "On this turn, either emit a same-target recovery batch or stop with a grounded blocker summary.\n"
                f"{self._guided_exact_match_retry_hint()}\n"
                "Do NOT emit list/search/codebase tools in this recovery turn."
            )
    if "no_file_changes" not in pending_flags and ((needs_validation and not has_validation) or (needs_rescan and not has_rescan)):
        hint_text = ""
        hints = self._guided_recent_target_hints()
        if hints:
            hint_text = f"\nTarget hint(s) already named in context: {', '.join(hints)}."
        validation_hint = self._guided_validation_hint_text()
        noop_text = f"\nDo NOT retry the same no-op target(s): {', '.join(self._guided_noop_edit_targets)} unless fresh evidence proves a different exact patch." if self._guided_noop_edit_targets else ""
        missing_steps = []
        if needs_validation and not has_validation:
            missing_steps.append("validation")
        if needs_rescan and not has_rescan:
            missing_steps.append("fresh post-edit rescan")
        missing_text = f"\nThis batch is still missing: {', '.join(missing_steps)}." if missing_steps else ""
        return (
            "GUIDED DECISION GATE — FINISH THE CURRENT FIX CYCLE:\n"
            "The latest TOOL_RESULT shows you already have a successful edit.\n"
            "Your NEXT batch must focus on validation/rescan, not fresh investigation or unrelated edits.\n"
            "Emit at most:\n"
            "- one <execute_command ... /> for validation, and\n"
            "- one narrow read/search/list step for a fresh post-edit check.\n"
            "If validation is impossible, stop and write a grounded blocker summary instead of exploring further."
            f"{missing_text}{hint_text}{validation_hint}{noop_text}"
        )
    noop_text = f"\nAvoid retrying disproven/no-op target(s): {', '.join(self._guided_noop_edit_targets)}." if self._guided_noop_edit_targets else ""
    if concrete_targets and investigation_only and not has_edit and self._guided_requires_same_target_edit_now():
        return (
            "GUIDED DECISION GATE — NO MORE SAME-TARGET INSPECTION:\n"
            "A concrete target is already in context, and this run already spent its allowed same-target reinspection chance without a successful edit.\n"
            "Do NOT emit another read/search-only batch on this target.\n"
            "On this turn do exactly ONE of these:\n"
            "A. Emit the smallest same-target edit batch now, optionally paired with one immediately-adjacent targeted read only if that read directly enables the edit, or\n"
            "B. Stop and write a grounded blocker summary with one follow-up question.\n"
            "Do NOT switch to a different target unless the latest TOOL_RESULT clearly disproves the current one."
            f"\nConcrete target(s): {', '.join(concrete_targets)}.{noop_text}{self._guided_exact_match_retry_hint()}"
        )
    threshold = 1 if concrete_targets else 2
    if self._guided_no_progress_cycles < threshold or has_edit:
        return None
    if not concrete_targets and investigation_only and not broad_investigation and len(tools) <= 1 and cmds[0] in {"read_file", "get_file_structure"}:
        return None
    hint_text = ""
    hints = concrete_targets or self._guided_extract_target_hints(self._guided_phase_anchor)
    if hints:
        hint_text = f"\nTarget hint(s) already named in context: {', '.join(hints)}. Pick ONE of them if possible."
    if concrete_targets:
        return (
            "GUIDED DECISION GATE — STAY ON ONE TARGET:\n"
            "A concrete target is already in context, and the run has already spent a cycle investigating without a successful edit.\n"
            "On this turn do exactly ONE of these:\n"
            "A. Emit the smallest same-target fix batch, optionally preceded by one narrow <read_file ... /> on that exact file, or\n"
            "B. Stop and write a grounded blocker summary with one follow-up question.\n"
            "Do NOT switch back to broad repo-inspection or wander to a different target unless the latest TOOL_RESULT clearly disproves the current target."
            f"{hint_text}{noop_text}{self._guided_exact_match_retry_hint()}"
        )
    return (
        "GUIDED DECISION GATE — COMMIT OR STOP:\n"
        "You have already spent enough cycles investigating without a successful edit.\n"
        "On this turn do exactly ONE of these:\n"
        "A. Emit the smallest concrete fix batch for the single best-supported issue, optionally preceded by one narrow <read_file ... /> on the exact target file, or\n"
        "B. Stop and write a grounded blocker summary with one follow-up question.\n"
        "Do NOT use broad repo-inspection tools such as <find_tests>, <find_symbol>, <find_references>, <find_importers>, <find_files>, <list_files>, <search_files>, or <search_codebase> in this response."
        f"{hint_text}{noop_text}{self._guided_exact_match_retry_hint()}"
    )


def _guided_non_tool_decision_gate_prompt(self, response_text: str) -> str | None:
    if not self._is_siege_mode():
        return None
    text = str(response_text or "").strip()
    if not text:
        return None
    requirements_prompt = self._guided_project_start_requirements_prompt(text)
    if requirements_prompt:
        return requirements_prompt
    if not self._guided_takeoff_active():
        return None
    navigation_start = self._guided_takeoff_stage <= 1 and self._guided_navigation_request_detected()
    bounded_start = self._guided_takeoff_stage <= 1 and (self._guided_direct_change_requested or navigation_start)
    if self._guided_takeoff_stage < 2 and not bounded_start:
        return None
    pending_flags = set(self._pending_summary_guard_flags or set())
    concrete_targets = self._guided_concrete_target_context()
    current_task = self._guided_current_task_title()
    current_task_requires_action = self._guided_current_task_requires_action()
    board_updated = bool(getattr(self, "_guided_task_board_updated_this_turn", False))
    hints = concrete_targets or self._guided_extract_target_hints(text, self._guided_phase_anchor)
    hint_text = f"\nTarget hint(s) already named by you: {', '.join(hints)}. Pick ONE." if hints else ""
    noop_text = f"\nAvoid retrying disproven/no-op target(s): {', '.join(self._guided_noop_edit_targets)}." if self._guided_noop_edit_targets else ""
    validation_failure = self._guided_validation_failure_focus()
    validation_failure_hint = self._guided_validation_failure_hint_text()
    navigation_hint = "\nThis task is a navigation/report request. Before writing the report or summary, emit at least one real navigation batch using <find_symbol>, <get_imports>, <find_importers>, or <find_tests>." if navigation_start else ""
    board_requirement = "\nYour rewrite MUST start with an updated <task_board>...</task_board> block that you author and update yourself." if self._guided_takeoff_stage >= 2 and not board_updated else ""
    if not self._guided_phase_one_has_tool_evidence() and self._guided_looks_like_fabricated_progress(text):
        return (
            "GUIDED DECISION GATE — DO NOT SIMULATE COMPLETED WORK:\n"
            "Your reply described completed creates/runs/fixes/verification without any grounded tool evidence in this run.\n"
            "Do NOT invent file contents, runtime output, traceback text, action logs, or final summaries for work that has not actually happened.\n"
            "Emit valid tool XML only for the smallest real batch now, or write a grounded blocker summary with one follow-up question.\n"
            f"Stay on one issue and keep the batch narrow.{board_requirement}{navigation_hint}{hint_text}{noop_text}"
        )
    if bounded_start:
        if self._guided_is_grounded_blocker_summary(text):
            return None
        if re.search(r'\b(blocker|cannot|can\'t|unable|need user|need permission|need a decision|halted further wandering)\b', text, re.IGNORECASE):
            return None
        if self._guided_looks_like_tool_advice(text):
            return (
                "GUIDED DECISION GATE — TAKE THE FIRST ACTION NOW:\n"
                "Siege bounded start is active, but your reply only described intended tool usage instead of taking the first action.\n"
                "Do NOT describe tools, example commands, or a next-step plan.\n"
                "Emit valid tool XML only for the smallest real batch now, or write a grounded blocker summary with one follow-up question.\n"
                f"Stay on one issue and keep the batch narrow.{board_requirement}{navigation_hint}{hint_text}{noop_text}"
            )
        return (
            "GUIDED DECISION GATE — DO NOT STOP BEFORE THE FIRST TOOL BATCH:\n"
            "Siege bounded start is active because the user asked for a concrete change/report, but this run still has no grounded tool action.\n"
            "Do not end this turn with analysis, plans, or intentions alone.\n"
            "Emit valid tool XML only for the smallest real batch now, or write a grounded blocker summary with one follow-up question.\n"
            f"Stay on one issue and keep the batch narrow.{board_requirement}{navigation_hint}{hint_text}{noop_text}"
        )
    audit_missing = self._guided_audit_completion_missing_bits()
    if audit_missing and not self._guided_is_grounded_blocker_summary(text):
        self._note_guided_current_task_stall(current_task)
        return (
            "GUIDED AUDIT COMPLETION GATE — THE AUDIT PHASE IS NOT DONE YET:\n"
            f"Your own task board is in an audit phase, but the grounded evidence still does not show: {'; '.join(audit_missing)}.\n"
            "Do NOT summarize the audit as complete yet. Update the task board and keep working on the CURRENT audit task.\n"
            f"After the task board, emit the smallest tool batch that closes the missing audit requirement(s), or write a grounded blocker summary if something external prevents that.{board_requirement}"
        )
    if validation_failure and validation_failure["current_conflicts"]:
        self._note_guided_current_task_stall(current_task)
        current_display = validation_failure["current_task"] or "(missing CURRENT task)"
        return (
            "GUIDED VALIDATION FAILURE GATE — KEEP THE CURRENT TASK ON THE FAILING CODE PATH:\n"
            "The latest grounded validation attempt failed, so this phase cannot drift to unrelated work.\n"
            f"Your current task board is inconsistent with that evidence: {current_display}.\n"
            "Rewrite this turn with an updated <task_board> block whose CURRENT task explicitly fixes the failing code path or reruns the failing validation.\n"
            f"After the task board, emit the smallest tool batch that advances that failure-fix path, or write a grounded blocker summary if something external truly blocks it.{board_requirement}{validation_failure_hint}{hint_text}{noop_text}"
        )
    if self._guided_successful_edit_seen:
        requirements_prompt = self._guided_project_start_requirements_prompt(text)
        if requirements_prompt:
            return requirements_prompt
        if {"validation_failed", "post_edit_validation_failed"} & pending_flags:
            return (
                "GUIDED DECISION GATE — VALIDATION FAILED, SO FIX THE FAILING CODE PATH NOW:\n"
                "The latest grounded evidence shows a validation command failed. Do NOT summarize success, move on to unrelated work, or ask the user to continue.\n"
                f"Rewrite this turn with an updated <task_board> block, then either emit valid tool XML only for the smallest fix/rerun batch or write a grounded blocker summary.{board_requirement}{validation_failure_hint}{hint_text}{noop_text}"
            )
        if {"no_validation", "no_post_edit_validation", "no_post_edit_rescan"} & pending_flags:
            validation_hint = self._guided_validation_hint_text()
            return (
                "GUIDED DECISION GATE — DO NOT END BEFORE VALIDATION:\n"
                "You already have a successful edit, but the current evidence still lacks the required validation/rescan.\n"
                "Emit the smallest validation/rescan batch now, or write a grounded blocker summary that explains why validation cannot run."
                f"{board_requirement}{hint_text}{validation_hint}{noop_text}"
            )
        return None
    if self._guided_exact_match_retry_targets:
        return (
            "GUIDED DECISION GATE — RESOLVE THE FAILED EDIT NOW:\n"
            "The previous edit failed because the requested live target was not matched uniquely.\n"
            "Do not stop at analysis and do not jump back to broad investigation.\n"
            f"Either emit the smallest same-target recovery batch now or write a grounded blocker summary with one follow-up question.{board_requirement}{self._guided_exact_match_retry_hint()}"
        )
    if self._guided_is_grounded_blocker_summary(text):
        return None
    if re.search(r'\b(blocker|cannot|can\'t|unable|need user|need permission|need a decision|halted further wandering)\b', text, re.IGNORECASE):
        return None
    if current_task and current_task_requires_action and self._guided_looks_like_inspection_only_summary(text):
        self._note_guided_current_task_stall(current_task)
        return (
            "GUIDED CURRENT TASK GATE — DO NOT END THIS PHASE ON INSPECTION ONLY:\n"
            f"Your own task board still has an actionable CURRENT TASK: {current_task}.\n"
            "This reply reads like inspection findings or a handoff summary, but it did not actually advance that CURRENT task.\n"
            "Do NOT stop at findings, recommendations, or a no-change summary while the CURRENT task still calls for edits or validation.\n"
            f"Rewrite this turn with an updated <task_board> block, then either emit valid tool XML only for the smallest batch that advances the CURRENT task or write a grounded blocker summary.{board_requirement}{hint_text}{noop_text}"
        )
    if current_task and self._assistant_summary_has_followup(text):
        self._note_guided_current_task_stall(current_task)
        if int(getattr(self, "_guided_current_task_stall_count", 0) or 0) >= 2:
            return (
                "GUIDED TASK BOARD EXECUTION GATE — STOP ASKING FOR CONTINUE:\n"
                f"Your own task board still has an actionable CURRENT TASK: {current_task}.\n"
                "Do NOT ask the user to continue, do NOT restate the plan, and do NOT stop at analysis.\n"
                f"Rewrite this turn with an updated <task_board> block, then emit valid tool XML only for the smallest batch that advances the CURRENT task, or write a grounded blocker summary if the task is truly blocked.{board_requirement}"
            )
        return (
            "GUIDED TASK BOARD GATE — ADVANCE THE CURRENT TASK NOW:\n"
            f"Your own task board still marks an actionable CURRENT TASK: {current_task}.\n"
            "Do NOT ask the user to reply 'continue' while that task is still actionable.\n"
            f"Rewrite this turn with an updated <task_board> block, then either emit the smallest next tool batch for the CURRENT task or write a grounded blocker summary.{board_requirement}"
        )
    if concrete_targets and self._guided_requires_same_target_edit_now():
        return (
            "GUIDED DECISION GATE — DO NOT RE-INSPECT THIS TARGET:\n"
            "A concrete target is already in context, and this run already exhausted the allowed same-target reinspection chance without a successful edit.\n"
            "Do NOT answer with more analysis, more inspection plans, or another same-target read/search request.\n"
            f"Emit the smallest same-target edit batch now, or write a grounded blocker summary with one follow-up question.{board_requirement}{hint_text}{noop_text}{self._guided_exact_match_retry_hint()}"
        )
    if concrete_targets:
        return (
            "GUIDED DECISION GATE — DO NOT STOP AT TARGET ANALYSIS:\n"
            "You already have a concrete target in context, but this run still has no successful edit.\n"
            "Emit the smallest same-target edit batch now, optionally preceded by one narrow <read_file ... /> on that file, or write a grounded blocker summary with one follow-up question.\n"
            f"Do not end this turn with more analysis or another search plan.{board_requirement}{hint_text}{noop_text}{self._guided_exact_match_retry_hint()}"
        )
    if "no_file_changes" not in pending_flags and self._guided_looks_like_tool_advice(text):
        return (
            "GUIDED DECISION GATE — TAKE THE FIRST ACTION NOW:\n"
            "Stage 2 has started, but your reply only described intended tool usage instead of taking the action.\n"
            "Do NOT describe tools, example commands, or a next-step plan.\n"
            "Emit valid tool XML only for the smallest real batch now, or write a grounded blocker summary with one follow-up question.\n"
            f"If you already know the likely target file, use at most one narrow <read_file ... /> before the smallest fix.{board_requirement}{hint_text}{noop_text}"
        )
    if "no_file_changes" not in pending_flags:
        return (
            "GUIDED DECISION GATE — DO NOT STOP BEFORE THE FIRST REAL ACTION:\n"
            "Stage 2 has started, but this run still has no successful edit or grounded blocker.\n"
            "Do not end this turn with analysis, plans, or intentions alone.\n"
            "Emit either valid tool XML only for the smallest next batch, or a grounded blocker summary with one follow-up question.\n"
            f"If editing is likely, prefer one narrow read on the exact target file before the smallest fix.{board_requirement}{hint_text}{noop_text}"
        )
    return (
        "GUIDED DECISION GATE — DO NOT STOP AT ANALYSIS:\n"
        "The latest evidence may identify an issue, but this run still has no successful edit.\n"
        "If the issue is fixable, emit the smallest concrete edit batch now, optionally preceded by one narrow <read_file ... /> on the exact target file.\n"
        "If editing is not justified yet, write a grounded blocker summary that explicitly says why and ends with one follow-up question.\n"
        f"Do not end this turn with issue analysis alone.{board_requirement}{hint_text}{noop_text}{self._guided_exact_match_retry_hint()}"
    )


def _recover_fenced_tool_calls(response_text: str) -> list[dict]:
    text = str(response_text or "")
    if not text.strip():
        return []
    recovered = []
    for match in re.finditer(r"```([^\n`]*)\n([\s\S]*?)```", text):
        lang = (match.group(1) or "").strip().lower()
        body = (match.group(2) or "").strip()
        if lang and "xml" not in lang and "tool" not in lang:
            continue
        if not body.startswith("<"):
            continue
        calls = CodeParser.parse_tool_calls(body)
        if calls:
            recovered.extend(calls)
    return recovered


def _guided_looks_like_malformed_tool_attempt(response_text: str) -> bool:
    text = str(response_text or "")
    if not text.strip():
        return False
    if CodeParser.parse_tool_calls(text):
        return False
    if _recover_fenced_tool_calls(text):
        return False
    return bool(re.search(r'<(?:edit_file|write_file|execute_command|read_file|read_json|read_python_symbols|find_tests|get_imports|find_importers|search_files|find_symbol|find_references|find_files|list_files|get_file_structure|search_codebase)\b', text))


def _guided_looks_like_tool_advice(response_text: str) -> bool:
    text = str(response_text or "").strip()
    if not text:
        return False
    lowered = text.lower()
    cue_tokens = (
        "next step:", "example command", "run a tool", "use a tool", "tool to inspect", "tool call",
        "read_file", "read_json", "read_python_symbols", "find_tests", "get_imports", "find_importers",
        "search_files", "find_symbol", "find_references", "find_files", "list_files", "execute_command",
        "get_file_structure",
    )
    if any(token in lowered for token in cue_tokens):
        return True
    if re.search(r'```(?:bash|sh|shell|powershell|pwsh|cmd)\b', text, re.IGNORECASE):
        return True
    return bool(re.search(r"\b(i will|i'll|let me)\s+(inspect|search|read|check|explore|look at|analyze|examine|re-examine|reexamine|verify|re-verify|reverify)\b", text, re.IGNORECASE))


def _guided_looks_like_fabricated_progress(response_text: str) -> bool:
    text = str(response_text or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if _recover_fenced_tool_calls(text) or CodeParser.parse_tool_calls(text):
        return False
    if _guided_is_grounded_blocker_summary(text):
        return False
    if any(token in lowered for token in ("action log", "final summary", "runtime output", "traceback (most recent call last)")):
        return True
    if re.search(r"\b(created|creating|executed|executing|applied|applying|fixed|fixing|verified|validated|reran|re-ran|re-executed|re-executing)\b", text, re.IGNORECASE):
        return True
    return False


def _guided_looks_like_inspection_only_summary(response_text: str) -> bool:
    text = str(response_text or "").strip()
    if not text:
        return False
    if _recover_fenced_tool_calls(text) or CodeParser.parse_tool_calls(text):
        return False
    if _guided_is_grounded_blocker_summary(text):
        return False
    lowered = text.lower()
    if re.search(r"\b(blocker|cannot|can't|unable|need user|need permission|need a decision)\b", lowered, re.IGNORECASE):
        return False
    inspection_cues = (
        "inspection complete", "finding", "evidence", "recommended next step", "assessment:",
        "no files changed", "phase 1 inspection", "what i found", "critical bug", "recommended fix",
        "let me re-examine", "find actual issues", "false findings", "re-verify actual bugs",
    )
    action_cues = (
        "<task_board>", "grounded status:", "write_file", "edit_file", "execute_command", "read_file",
        "i changed", "changed:", "verified:", "validated", "reran", "applied", "fixed",
    )
    return any(cue in lowered for cue in inspection_cues) and not any(cue in lowered for cue in action_cues)


def _guided_is_grounded_blocker_summary(response_text: str) -> bool:
    text = str(response_text or "").strip()
    if not text:
        return False
    if text.startswith("[Guided takeoff paused here"):
        return True
    return bool(re.search(r"\bgrounded status:\b", text, re.IGNORECASE) and re.search(r"\bfollow-up for you:\b", text, re.IGNORECASE))


def _guided_blocker_summary_fallback(self) -> str:
    if self._guided_successful_edit_seen:
        grounded_status = "Grounded status: at least one file was successfully changed, but no successful validation/rescan was proven after that edit."
    else:
        grounded_status = "Grounded status: no files were successfully changed in the latest guided cycle, and no successful validation/rescan was proven after an edit."
    focus_hint = _guided_task_board_focus_hint(self)
    return (
        "[Guided takeoff paused here because the latest evidence still does not show a completed fix cycle.]\n\n"
        f"{grounded_status}{focus_hint}\n\n"
        "Follow-up for you: tell me which blocker or decision to resolve first, and I will stay on the current task board instead of restarting the plan."
    )


def _guided_recovery_prompt(self, tool_output: str) -> str | None:
    if self._guided_takeoff_stage < 2:
        return None
    flags = set(self._pending_summary_guard_flags or self._summary_guard_flags(tool_output))
    latest_batch = list(self._tool_calls_for_run or [])
    investigation_only = bool(latest_batch) and all(self._guided_is_investigation_tool(cmd) for cmd in latest_batch)
    concrete_targets = self._guided_concrete_target_context()
    task_focus_hint = _guided_task_board_focus_hint(self)
    requirements_prompt = self._guided_project_start_requirements_prompt("")
    if requirements_prompt:
        self._guided_no_progress_cycles = 0
        self._guided_noop_edit_targets = []
        self._guided_exact_match_retry_targets = []
        return requirements_prompt
    if {"validation_failed", "post_edit_validation_failed"} & flags:
        self._guided_no_progress_cycles = 0
        self._guided_noop_edit_targets = []
        self._guided_exact_match_retry_targets = []
        failure_hint = self._guided_validation_failure_hint_text()
        return (
            "GUIDED RECOVERY — THE LATEST VALIDATION FAILED:\n"
            "A validation command already ran and failed, so do NOT waste this turn re-running the same phase summary or drifting to unrelated work.\n"
            "Your next reply must be either valid tool XML only for the smallest fix/rerun batch on the failing code path (no surrounding prose) or a grounded blocker summary.\n"
            "1. Stay on the code path implicated by the failing validation.\n"
            "2. Make the smallest safe fix or gather one narrow read that directly enables that fix.\n"
            f"3. Then rerun the failing validation command.{failure_hint}{task_focus_hint}"
        )
    if "no_file_changes" not in flags and ("no_validation" in flags or "no_post_edit_validation" in flags or "no_post_edit_rescan" in flags):
        self._guided_no_progress_cycles = 0
        self._guided_noop_edit_targets = []
        self._guided_exact_match_retry_targets = []
        validation_hint = self._guided_validation_hint_text()
        return (
            "GUIDED RECOVERY — FOCUS THE CURRENT FIX CYCLE:\n"
            "You already have a successful edit in this run. Do NOT branch into new unrelated work.\n"
            "Your next reply must be either valid tool XML only for the smallest validation/rescan batch (no surrounding prose) or a grounded blocker summary.\n"
            "1. Validate the latest successful edit with the smallest useful command.\n"
            "2. Do one fresh post-edit inspection/rescan.\n"
            f"3. Then write a grounded user-facing update.{validation_hint}{task_focus_hint}"
        )
    if not self._guided_takeoff_active():
        return None
    if "no_file_changes" in flags and any(self._guided_is_edit_tool(cmd) for cmd in latest_batch):
        self._guided_no_progress_cycles += 1
        self._guided_noop_edit_targets = self._guided_tool_targets(self._tool_specs_for_run, edit_only=True)
        target_text = f" Target(s): {', '.join(self._guided_noop_edit_targets)}." if self._guided_noop_edit_targets else ""
        exact_match_hint = ""
        if "old_text not found" in str(tool_output or "").lower():
            self._guided_exact_match_retry_targets = list(self._guided_noop_edit_targets or [])
            exact_match_hint = (
                "\nThe last edit failed because the exact block was not found. Stay on that SAME target for one recovery turn instead of broadening the search."
                f"{self._guided_exact_match_retry_hint()}"
            )
        else:
            self._guided_exact_match_retry_targets = []
        return (
            "GUIDED RECOVERY — THE LAST EDIT WAS A NO-OP:\n"
            "The most recent edit batch did not actually change any files, so that fix hypothesis is either already present or incorrectly targeted.\n"
            f"Do NOT retry the same patch without fresh evidence.{target_text}\n"
            "On the next turn, reply with either valid tool XML only for one new concrete target (no surrounding prose) or a grounded blocker summary.\n"
            f"If you need confirmation, use at most one narrow read on the same file before moving on.{exact_match_hint}{task_focus_hint}"
        )
    if "no_file_changes" in flags and investigation_only:
        self._guided_no_progress_cycles += 1
        if concrete_targets:
            target_text = f"\nConcrete target(s) already in context: {', '.join(concrete_targets)}. Stay on ONE of them." if concrete_targets else ""
            if self._guided_requires_same_target_edit_now():
                return (
                    "GUIDED RECOVERY — EDIT OR STOP ON THIS TARGET:\n"
                    "A concrete target is already in context, and the run has already used its same-target reinspection chance without a successful edit.\n"
                    "Your next reply must be either valid tool XML only (no surrounding prose) for the single smallest same-target edit attempt or a grounded blocker summary with one follow-up question.\n"
                    f"Do NOT emit another read/search-only batch on this target.{target_text}{self._guided_exact_match_retry_hint()}{task_focus_hint}"
                )
            if self._guided_no_progress_cycles == 1:
                return (
                    "GUIDED RECOVERY — STAY ON THIS TARGET:\n"
                    "The last batch was still investigation-only, but a concrete target is already in context.\n"
                    "Your next reply must be either valid tool XML only (no surrounding prose) for one tiny same-target fix batch or a grounded blocker summary.\n"
                    "You may use at most one narrow <read_file ... /> on that file before making one small edit.\n"
                    f"Do NOT run another broad repo search or switch to a different target unless the latest TOOL_RESULT disproves the current one.{target_text}{self._guided_exact_match_retry_hint()}{task_focus_hint}"
                )
            return (
                "GUIDED RECOVERY — STOP RE-INVESTIGATING THIS TARGET:\n"
                "You already had a concrete target and still spent multiple cycles without a successful edit.\n"
                "Your next reply must be either valid tool XML only (no surrounding prose) for the single smallest same-target fix attempt or a grounded blocker summary with one follow-up question.\n"
                f"Do NOT start another read/search sweep. Either try the fix now or stop cleanly.{target_text}{self._guided_exact_match_retry_hint()}"
            )
        if self._guided_no_progress_cycles == 1:
            hints = self._guided_current_fix_targets() or self._guided_extract_target_hints(self._guided_phase_anchor)
            hint_text = f"\nTarget hint(s) already named in Phase 1: {', '.join(hints)}. Pick ONE." if hints else ""
            return (
                "GUIDED RECOVERY — PICK A TARGET NOW:\n"
                "The last batch was investigation-only and did not produce a successful edit.\n"
                "Your next reply must be either valid tool XML only (no surrounding prose) for one tiny target-focused batch or a grounded blocker summary.\n"
                "For the next turn, use the strongest Phase 1 finding or the latest TOOL_RESULT to choose ONE target file.\n"
                "You may use at most one narrow <read_file ... /> on that file before either making one small fix or stopping with a grounded blocker summary.\n"
                f"Do NOT run another broad repo search.{hint_text}"
            )
        if self._guided_no_progress_cycles >= 2:
            return (
                "GUIDED RECOVERY — STOP RE-INVESTIGATING:\n"
                "You have already spent multiple cycles without a successful edit.\n"
                "Your next reply must be either valid tool XML only (no surrounding prose) for the single best-supported next step or a grounded blocker summary.\n"
                "On the next turn do ONE of these only:\n"
                "A. Emit the smallest concrete fix batch for the single best-supported issue, or\n"
                "B. Stop and give the user a grounded blocker summary with one follow-up question.\n"
                f"Do NOT start another broad read/search sweep.{self._guided_exact_match_retry_hint()}"
            )
    self._guided_no_progress_cycles = 0
    self._guided_exact_match_retry_targets = []
    return None


def _is_ai_error_response(text: str) -> bool:
    return (text or "").strip().startswith("[Error:")


def _notification_for_ai_error(text: str) -> tuple[str, str]:
    clean = (text or "").strip()
    if clean.startswith("[Error:"):
        clean = clean[len("[Error:"):].strip()
    if clean.endswith("]"):
        clean = clean[:-1].strip()
    title = "AI Provider Error"
    if "OpenRouter fallback exhausted" in clean:
        title = "OpenRouter Fallback Exhausted"
    elif "OpenRouter rate limit reached" in clean:
        title = "OpenRouter Rate Limit"
    elif "OpenRouter blocked model" in clean and "privacy settings" in clean:
        title = "OpenRouter Privacy Setting Needed"
    elif "OpenRouter request failed" in clean:
        title = "OpenRouter Request Failed"
    message = clean.replace("\nProvider said:", "\n\nProvider said:")
    return title, message[:320] + ("..." if len(message) > 320 else "")


__all__ = [name for name in globals() if name.startswith("_")]