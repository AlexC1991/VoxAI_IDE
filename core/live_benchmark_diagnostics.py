STAGES = [
    ("S0_PROVIDER_REQUEST", "Provider request", "Run invoked the configured model/provider route."),
    ("S1_VISIBLE_RESPONSE", "Visible response", "At least one visible model response arrived."),
    ("S2_ACTIONABLE_RESPONSE", "Actionable response", "A response was accepted as valid tool XML or grounded text."),
    ("S3_TOOL_EXECUTION", "Tool execution", "At least one tool batch executed successfully."),
    ("S4_CONCRETE_TARGET", "Concrete target", "The run narrowed to a specific file, command, or issue."),
    ("S5_EDIT_ATTEMPT", "Edit attempt", "The model attempted a workspace change."),
    ("S6_POST_EDIT_VALIDATION", "Post-edit validation", "The run validated or rescanned after an edit attempt."),
    ("S7_GROUNDED_COMPLETION", "Grounded completion", "The final answer was grounded in the latest tool evidence."),
]
STAGE_INDEX = {code: idx for idx, (code, _, _) in enumerate(STAGES)}
STAGE_LABELS = {code: label for code, label, _ in STAGES}
STAGE_DESCRIPTIONS = {code: desc for code, _, desc in STAGES}
EDIT_COMMANDS = {"write_file", "edit_file", "move_file", "copy_file", "delete_file"}
VALIDATION_COMMANDS = {
    "read_file",
    "read_json",
    "read_python_symbols",
    "get_file_structure",
    "get_imports",
    "find_symbol",
    "find_references",
    "search_files",
    "execute_command",
    "git_diff",
    "git_status",
}
TARGETED_INSPECTION_COMMANDS = {
    "read_file",
    "read_json",
    "read_python_symbols",
    "get_file_structure",
    "find_symbol",
    "find_references",
    "get_imports",
    "find_importers",
    "find_tests",
}
GENERIC_SEARCH_TERMS = {"todo", "fixme", "bug", "bugs", "issue", "issues", "except", "error", "errors"}


def new_trace(model):
    return {
        "model": model,
        "furthest_stage_code": "S0_PROVIDER_REQUEST",
        "visible_response_count": 0,
        "blank_visible_responses": 0,
        "blank_retry_count": 0,
        "decision_gate_rewrites": 0,
        "summary_guard_rewrites": 0,
        "tool_batches_executed": 0,
        "edit_batches": 0,
        "validation_batches": 0,
        "concrete_target_selected": False,
        "provider_error_message": "",
    }


def mark_stage(trace, stage_code):
    if STAGE_INDEX[stage_code] > STAGE_INDEX[trace["furthest_stage_code"]]:
        trace["furthest_stage_code"] = stage_code


def observe_response(trace, text):
    stripped = (text or "").strip()
    if not stripped:
        trace["blank_visible_responses"] += 1
        return
    trace["visible_response_count"] += 1
    mark_stage(trace, "S1_VISIBLE_RESPONSE")
    if stripped.startswith("[Error:") and not trace["provider_error_message"]:
        trace["provider_error_message"] = stripped


def observe_tool_batch(trace, tools, mode):
    if not tools:
        return
    mark_stage(trace, "S2_ACTIONABLE_RESPONSE")
    trace["tool_batches_executed"] += 1
    mark_stage(trace, "S3_TOOL_EXECUTION")
    names = [tool.get("cmd", "") for tool in tools]
    if mode == "siege" and _targets_specific_issue(tools):
        trace["concrete_target_selected"] = True
        mark_stage(trace, "S4_CONCRETE_TARGET")
    if any(name in EDIT_COMMANDS for name in names):
        trace["edit_batches"] += 1
        mark_stage(trace, "S5_EDIT_ATTEMPT")
    if trace["edit_batches"] and any(name in VALIDATION_COMMANDS for name in names):
        trace["validation_batches"] += 1
        mark_stage(trace, "S6_POST_EDIT_VALIDATION")


def _targets_specific_issue(tools):
    for tool in tools:
        cmd = tool.get("cmd", "")
        args = tool.get("args", {})
        if cmd in EDIT_COMMANDS or cmd in TARGETED_INSPECTION_COMMANDS or cmd in VALIDATION_COMMANDS - {"search_files", "git_status"}:
            return True
        if cmd == "search_files":
            query = str(args.get("query", "")).strip().lower()
            if query and query not in GENERIC_SEARCH_TERMS:
                return True
    return False


def looks_like_tool_protocol(text):
    stripped = (text or "").strip().lower()
    tokens = (
        "<tool_call",
        "<read_file",
        "<read_json",
        "<read_python_symbols",
        "<write_file",
        "<edit_file",
        "<execute_command",
        "<find_tests",
        "<get_imports",
        "<find_importers",
        "<find_symbol",
        "<find_references",
        "[read_file",
        "[write_file",
        "[execute_command",
    )
    return any(token in stripped for token in tokens)


def looks_like_blank_completion(text):
    stripped = (text or "").strip().lower()
    return stripped.startswith("[no response received from the model.")


def classify_provider_failure(text):
    lowered = (text or "").lower()
    if not lowered.startswith("[error:"):
        return ""
    if any(token in lowered for token in ("401", "invalid api key", "incorrect api key", "auth", "unauthorized")):
        return "P1_PROVIDER_AUTH"
    if any(token in lowered for token in (
        "429",
        "503",
        "rate limit",
        "credit",
        "quota",
        "capacity",
        "temporarily unavailable",
        "service unavailable",
        "high demand",
        "busy",
        "overloaded",
    )):
        return "P2_PROVIDER_RATE_LIMIT"
    return "P3_PROVIDER_OTHER"


def finalize_result(trace, *, guided_stage, autonomy_unlocked, no_progress_cycles, changed_files, final, grounded_completion):
    result = dict(trace)
    grounded_completion_reached = _reached_grounded_completion_stage(result, grounded_completion, final)
    if grounded_completion_reached:
        mark_stage(result, "S7_GROUNDED_COMPLETION")
    result.update(
        {
            "guided_stage": guided_stage,
            "guided_autonomy_unlocked": autonomy_unlocked,
            "no_progress_cycles": no_progress_cycles,
            "changed_files": changed_files,
            "final": final,
            "final_excerpt": _clip(final),
            "furthest_stage_label": STAGE_LABELS[result["furthest_stage_code"]],
            "furthest_stage_description": STAGE_DESCRIPTIONS[result["furthest_stage_code"]],
        }
    )
    result["pass"] = bool(changed_files) and bool(autonomy_unlocked)
    result["grounded_completion_reached"] = grounded_completion_reached
    result["failure_code"] = "" if result["pass"] else _primary_failure_code(result, grounded_completion)
    result["failure_note"] = _failure_note(result)
    return result


def _reached_grounded_completion_stage(result, grounded_completion, final):
    if not grounded_completion or looks_like_blank_completion(final):
        return False
    return bool(result.get("edit_batches") or result.get("validation_batches"))


def _primary_failure_code(result, grounded_completion):
    provider = classify_provider_failure(result.get("provider_error_message", ""))
    if provider:
        return provider
    if looks_like_blank_completion(result.get("final", "")):
        return "R2_BLANK_FINAL_RESPONSE"
    if not result.get("visible_response_count"):
        return "R1_BLANK_VISIBLE_RESPONSE"
    if looks_like_tool_protocol(result.get("final", "")):
        return "T1_RAW_TOOL_PROTOCOL_FINAL"
    if result.get("edit_batches") and not result.get("validation_batches"):
        return "V1_NO_VALIDATION_AFTER_EDIT"
    if result.get("validation_batches") and result.get("changed_files") and not result.get("guided_autonomy_unlocked"):
        if grounded_completion:
            return "U1_AUTONOMY_NOT_UNLOCKED_AFTER_VALIDATED_CHANGE"
        return "S2_NO_GROUNDED_FINAL_AFTER_VALIDATED_CHANGE"
    if result.get("edit_batches") and not result.get("changed_files"):
        return "E2_EDIT_ATTEMPT_NO_EFFECTIVE_CHANGE"
    if result.get("guided_stage", 0) < 3 and not result.get("edit_batches"):
        return "G2_STUCK_IN_GUIDED_STAGE"
    if not result.get("concrete_target_selected"):
        return "G1_NO_CONCRETE_TARGET"
    if result.get("tool_batches_executed") and not result.get("edit_batches"):
        return "E1_NO_EDIT_ATTEMPT"
    if grounded_completion and not result.get("grounded_completion_reached"):
        return "S3_GROUNDED_FINAL_WITHOUT_EDIT_CYCLE"
    if result.get("final", "").strip() and not grounded_completion:
        return "S1_UNGROUNDED_FINAL_SUMMARY"
    return "S4_NO_GROUNDED_COMPLETION_AFTER_PROGRESS"


def _failure_note(result):
    if result.get("pass"):
        return "Completed a grounded edit/validation cycle."
    if result.get("provider_error_message"):
        return _clip(result["provider_error_message"])
    if result.get("failure_code") == "R1_BLANK_VISIBLE_RESPONSE":
        return "No visible assistant content arrived after retries."
    if result.get("failure_code") == "R2_BLANK_FINAL_RESPONSE":
        return "The run ended with the benchmark's no-visible-response placeholder instead of a grounded final answer."
    if result.get("failure_code") == "T1_RAW_TOOL_PROTOCOL_FINAL":
        return "Final output still contained raw tool protocol instead of grounded progress."
    if result.get("failure_code") == "G2_STUCK_IN_GUIDED_STAGE":
        return "The run never escaped guided stage into a concrete edit/validation loop."
    if result.get("failure_code") == "V1_NO_VALIDATION_AFTER_EDIT":
        return "An edit was attempted, but no validation batch followed it."
    if result.get("failure_code") == "U1_AUTONOMY_NOT_UNLOCKED_AFTER_VALIDATED_CHANGE":
        return "A changed file was validated, but autonomy unlock criteria still were not met."
    if result.get("failure_code") == "S2_NO_GROUNDED_FINAL_AFTER_VALIDATED_CHANGE":
        return "The run reached validated file changes, but never produced a grounded final answer."
    if result.get("failure_code") == "E2_EDIT_ATTEMPT_NO_EFFECTIVE_CHANGE":
        return "An edit batch ran, but no lasting workspace change was detected afterward."
    if result.get("failure_code") == "S3_GROUNDED_FINAL_WITHOUT_EDIT_CYCLE":
        return "The final answer looked grounded, but the run never completed an edit/validation cycle."
    return _clip(result.get("final", "")) or "No grounded completion was observed."


def format_markdown_matrix(results):
    include_scenario = any(str(result.get("scenario") or "").strip() for result in results or [])
    if include_scenario:
        lines = [
            "| Scenario | Model | Furthest stage | Failure code | Guided | Auto | Changed files | Note |",
            "|---|---|---|---|---:|---|---|---|",
        ]
    else:
        lines = [
            "| Model | Furthest stage | Failure code | Guided | Auto | Changed files | Note |",
            "|---|---|---|---:|---|---|---|",
        ]
    for result in results:
        changed = ", ".join(result.get("changed_files", [])) or "—"
        failure = result.get("failure_code") or "PASS"
        auto = "yes" if result.get("guided_autonomy_unlocked") else "no"
        note = _clip(result.get("failure_note") or result.get("final_excerpt") or "—", limit=100)
        if include_scenario:
            lines.append(
                f"| {result.get('scenario', '—')} | {result.get('model', '—')} | {result.get('furthest_stage_code', '—')} | {failure} | {result.get('guided_stage', '—')} | {auto} | {changed} | {note} |"
            )
        else:
            lines.append(
                f"| {result.get('model', '—')} | {result.get('furthest_stage_code', '—')} | {failure} | {result.get('guided_stage', '—')} | {auto} | {changed} | {note} |"
            )
    return "\n".join(lines)


def _clip(text, limit=140):
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."