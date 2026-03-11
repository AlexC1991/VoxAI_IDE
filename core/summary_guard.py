import os
import re

from core.code_parser import CodeParser


class SummaryGuard:
    @staticmethod
    def response_contains_tool_protocol(response_text: str) -> bool:
        text = str(response_text or "")
        if not text.strip():
            return False
        if CodeParser.parse_tool_calls(text):
            return True
        known_tools = "|".join(sorted(CodeParser.KNOWN_TOOLS, key=len, reverse=True))
        return bool(re.search(rf'<\s*/?(?:tool_call|(?:{known_tools}))\b', text, re.IGNORECASE))

    @classmethod
    def user_ready_final_response(cls, response_text: str) -> bool:
        text = str(response_text or "").strip()
        if not text:
            return False
        lower = text.lower()
        if "no response received from the model" in lower:
            return False
        if cls.response_contains_tool_protocol(text):
            return False
        return True

    @staticmethod
    def pause_after_tool_protocol_fallback(grounded_files: list[str] | None = None) -> str:
        grounded_files = list(grounded_files or [])
        changed = ", ".join(grounded_files) if grounded_files else "no newly grounded file changes"
        return "\n".join([
            "[Paused before executing another tool-only turn]",
            f"- Grounded state: {changed}.",
            "- The IDE paused instead of leaving raw tool XML as the final assistant reply.",
        ])

    @staticmethod
    def summary_needs_compact_success_rewrite(response_text: str, flags: set[str], grounded_files: list[str]) -> bool:
        text = str(response_text or "").strip()
        if not text or not grounded_files:
            return False
        if {"no_file_changes", "no_validation", "no_post_edit_validation", "validation_failed", "post_edit_validation_failed"} & set(flags or set()):
            return False
        lower = text.lower()
        nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
        bullet_lines = sum(1 for line in nonempty_lines if re.match(r'^[-*•]\s+', line))
        verbose_markers = (
            "what i changed",
            "why this should fix your issue",
            "try this",
            "key results",
            "issues encountered",
            "what you should know next",
            "actions taken and results",
            "next steps",
            "the project is ready to run as-is",
            "if you want, the next smallest enhancement",
        )
        return (
            len(text) > 360
            or len(nonempty_lines) > 6
            or bullet_lines > 3
            or any(marker in lower for marker in verbose_markers)
        )

    @staticmethod
    def compact_success_summary_fallback(flags: set[str], grounded_files: list[str] | None = None) -> str:
        grounded_files = list(grounded_files or [])
        changed = ", ".join(grounded_files) if grounded_files else "the grounded files from the latest tool cycle"
        verified = "latest validation command succeeded"
        if "no_validation" in flags or "no_post_edit_validation" in flags:
            verified = "no successful post-edit validation happened yet"
        if "no_post_edit_rescan" in flags:
            verified += "; no fresh post-edit rescan happened yet"
        return "\n".join([
            "[Summary compacted by IDE]",
            f"- Changed: {changed}.",
            f"- Verified: {verified}.",
        ])

    @staticmethod
    def parse_action_summary(tool_output: str) -> dict[str, list[str]]:
        sections = {
            "Successful file changes:": [],
            "Other successful actions:": [],
            "Failed actions:": [],
        }
        current_section = None
        inside_summary = False
        for raw_line in str(tool_output or "").splitlines():
            line = raw_line.strip()
            if line.startswith("[ACTION_SUMMARY]") or line.startswith("ACTION_SUMMARY:"):
                inside_summary = True
                current_section = None
                continue
            if not inside_summary:
                continue
            if line == "[/ACTION_SUMMARY]":
                break
            if line in sections:
                current_section = line
                continue
            if current_section and line.startswith("- "):
                value = line[2:].strip()
                if value and value.lower() != "none":
                    sections[current_section].append(value)
        return {
            "file_changes": sections["Successful file changes:"],
            "successful_actions": sections["Other successful actions:"],
            "failed_actions": sections["Failed actions:"],
        }

    @staticmethod
    def normalize_path(path_text: str) -> str:
        path = str(path_text or "").strip().replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        return path

    @classmethod
    def extract_file_like_tokens(cls, text: str) -> list[str]:
        seen = set()
        tokens = []
        pattern = r'(?:[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+\.[A-Za-z0-9_]+'
        for match in re.finditer(pattern, str(text or "")):
            token = cls.normalize_path(match.group(0).strip("'\"()[]{}.,:;"))
            if not token:
                continue
            lowered = token.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            tokens.append(token)
        return tokens

    @classmethod
    def grounded_changed_files_from_summary(cls, tool_output: str) -> list[str]:
        seen = set()
        grounded = []
        for entry in cls.parse_action_summary(tool_output)["file_changes"]:
            raw = str(entry or "").strip()
            if not raw:
                continue
            if ":" in raw:
                prefix, remainder = raw.split(":", 1)
                if prefix.strip().lower() in {"write_file", "edit_file", "delete_file", "move_file", "copy_file"}:
                    raw = remainder.strip()
            for token in cls.extract_file_like_tokens(raw):
                lowered = token.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                grounded.append(token)
        return grounded

    @classmethod
    def grounded_changed_file_aliases(cls, file_paths: list[str]) -> set[str]:
        aliases = set()
        for item in file_paths or []:
            normalized = cls.normalize_path(item)
            if not normalized:
                continue
            aliases.add(normalized.lower())
            aliases.add(os.path.basename(normalized).lower())
        return aliases

    @staticmethod
    def text_has_affirmative_claim(text: str, patterns: list[str]) -> bool:
        lower = str(text or "").lower()
        negations = ("did not", "didn't", "no ", "not ", "without ", "failed to", "wasn't", "weren't", "cannot", "can't")
        for pattern in patterns:
            for match in re.finditer(pattern, lower):
                prefix = lower[max(0, match.start() - 24):match.start()]
                if any(neg in prefix for neg in negations):
                    continue
                return True
        return False

    @classmethod
    def summary_claims_wrong_changed_file(cls, response_text: str, grounded_files: list[str]) -> bool:
        aliases = cls.grounded_changed_file_aliases(grounded_files)
        if not aliases:
            return False
        change_patterns = [
            r"\b(i|we) (changed|updated|modified|edited|fixed|implemented|wrote|created|deleted|refactored|patched|renamed|moved|copied)\b",
            r"\b(the )?(fix|change|update|patch) (was|is)? ?(applied|made|written)\b",
        ]
        for raw_line in str(response_text or "").splitlines():
            line = raw_line.strip()
            if not line or not cls.text_has_affirmative_claim(line, change_patterns):
                continue
            mentioned = [cls.normalize_path(token).lower() for token in cls.extract_file_like_tokens(line)]
            if mentioned and any(token not in aliases for token in mentioned):
                return True
        return False

    @classmethod
    def summary_grounding_message(cls, tool_output: str) -> str | None:
        grounded_files = cls.grounded_changed_files_from_summary(tool_output)
        if not grounded_files:
            return None
        return (
            "GROUNDED FILE-CHANGE SNAPSHOT:\n"
            f"- Exact files successfully changed in the latest tool cycle: {', '.join(grounded_files)}\n"
            "- If you mention changed/touched files in the next summary, name ONLY these exact grounded file paths."
        )

    @classmethod
    def latest_tool_cycle_has_file_changes(cls, tool_output: str) -> bool:
        return bool(cls.parse_action_summary(tool_output)["file_changes"])

    @staticmethod
    def parse_tool_action_log(action_log: list[str]) -> list[tuple[str, str]]:
        parsed = []
        for item in action_log or []:
            text = str(item or "")
            title, status = text.rsplit(" -> ", 1) if " -> " in text else (text, "")
            parsed.append((title.strip(), status.strip()))
        return parsed

    @staticmethod
    def is_successful_edit_step(title: str, status: str) -> bool:
        return status == "Done" and title.startswith(("Wrote ", "Edited ", "Moved ", "Copied ", "Deleted "))

    @staticmethod
    def is_successful_validation_step(title: str, status: str) -> bool:
        return status == "Done" and title.startswith("Executed:")

    @staticmethod
    def is_failed_validation_step(title: str, status: str) -> bool:
        return status == "Failed" and title.startswith("Executed:")

    @staticmethod
    def is_successful_rescan_step(title: str, status: str) -> bool:
        prefixes = (
            "Listed files in:", "Found files:", "Found tests:", "Found symbol:", "Found references:", "Found importers:",
            "Read file:", "Read JSON:", "Read Python symbols:", "Imports in:", "Searched for ", "Got structure of:",
            "Search:", "Git: git_status", "Git: git_diff",
        )
        return status == "Done" and title.startswith(prefixes)

    @classmethod
    def failed_validation_commands(cls, tool_output: str, action_log: list[str]) -> list[str]:
        commands = []
        seen = set()
        for entry in cls.parse_action_summary(tool_output).get("failed_actions", []):
            raw = str(entry or "").strip()
            if not raw.lower().startswith("execute_command "):
                continue
            command = raw[len("execute_command "):].split(":", 1)[0].strip()
            lowered = command.lower()
            if command and lowered not in seen:
                seen.add(lowered)
                commands.append(command)
        for title, status in cls.parse_tool_action_log(action_log):
            if not cls.is_failed_validation_step(title, status):
                continue
            command = title[len("Executed:"):].strip()
            lowered = command.lower()
            if command and lowered not in seen:
                seen.add(lowered)
                commands.append(command)
        return commands

    @classmethod
    def summary_guard_flags(cls, tool_output: str, action_log: list[str]) -> set[str]:
        flags = set()
        action_entries = cls.parse_tool_action_log(action_log)
        has_any_edit = any(cls.is_successful_edit_step(title, status) for title, status in action_entries)
        if not has_any_edit and not cls.latest_tool_cycle_has_file_changes(tool_output):
            flags.add("no_file_changes")
        has_validation = any(cls.is_successful_validation_step(title, status) for title, status in action_entries)
        has_failed_validation = bool(cls.failed_validation_commands(tool_output, action_log))
        if not has_validation:
            flags.add("no_validation")
        if has_failed_validation:
            flags.add("validation_failed")
        last_edit_idx = max((idx for idx, (title, status) in enumerate(action_entries) if cls.is_successful_edit_step(title, status)), default=-1)
        if last_edit_idx >= 0:
            if has_validation and not any(cls.is_successful_validation_step(title, status) for title, status in action_entries[last_edit_idx + 1:]):
                flags.add("no_post_edit_validation")
            if any(cls.is_failed_validation_step(title, status) for title, status in action_entries[last_edit_idx + 1:]) and not any(cls.is_successful_validation_step(title, status) for title, status in action_entries[last_edit_idx + 1:]):
                flags.add("post_edit_validation_failed")
            if not any(cls.is_successful_rescan_step(title, status) for title, status in action_entries[last_edit_idx + 1:]):
                flags.add("no_post_edit_rescan")
        return flags

    @staticmethod
    def summary_guard_message(flags: set[str], grounded_files: list[str] | None = None) -> str | None:
        notes = []
        if "no_file_changes" in flags:
            notes.append("The latest tool cycle did NOT produce any successful file changes. If this phase was investigative, explicitly say no files were changed. If you intended to change code but nothing changed, explain the blocker instead of claiming success.")
        if "no_validation" in flags:
            notes.append("The latest tool cycle did NOT run any successful validation command. Do NOT claim anything was tested, rerun, or verified in this phase.")
        if "validation_failed" in flags:
            notes.append("The latest validation command failed. Do NOT claim success or move on to unrelated polish/docs work until you either fix the failure and rerun it or explain a real blocker.")
        if "no_post_edit_validation" in flags:
            notes.append("You changed files, but there was no successful validation AFTER the latest successful edit. Do NOT claim the latest edit was verified yet.")
        if "post_edit_validation_failed" in flags:
            notes.append("A validation command failed AFTER the latest successful edit. Keep the CURRENT task on the failing code path instead of drifting to unrelated work.")
        if "no_post_edit_rescan" in flags:
            notes.append("You changed files, but did NOT perform a fresh rescan/inspection AFTER the latest successful edit. Do NOT claim a fresh rescan yet.")
        if grounded_files and notes:
            notes.append("If you mention changed files in the next summary, name ONLY these exact grounded paths from the latest tool cycle: " + ", ".join(grounded_files))
        if not notes:
            return None
        return "REALITY CHECK BEFORE YOU RESPOND TO THE USER:\n" + "\n".join(f"- {note}" for note in notes)

    @staticmethod
    def safe_summary_guard_fallback(flags: set[str], grounded_files: list[str] | None = None) -> str:
        lines = ["[Summary corrected by IDE reality check]"]
        if "no_file_changes" in flags:
            lines.append("- No files were successfully changed in the latest tool cycle.")
        elif grounded_files:
            lines.append("- The latest tool cycle only grounded these changed files: " + ", ".join(grounded_files))
        if "no_validation" in flags or "no_post_edit_validation" in flags:
            lines.append("- The latest successful edit was not validated by a successful command after it happened.")
        if "validation_failed" in flags or "post_edit_validation_failed" in flags:
            lines.append("- The latest validation attempt failed, so the run still needs a fix on the failing code path before it is complete.")
        if "no_post_edit_rescan" in flags:
            lines.append("- No fresh rescan/inspection was performed after the latest successful edit.")
        lines.append("- Please review the latest TOOL_RESULT for the grounded state of the run.")
        return "\n".join(lines)