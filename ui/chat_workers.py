import html
import logging
import os
import threading

from PySide6.QtCore import QObject, QThread, Signal

from core.ai_client import AIClient
from core.agent_tools import AgentToolHandler
from core.rag_client import RAGClient
from core.settings import SettingsManager
from core.tool_policy import ToolPolicy


log = logging.getLogger(__name__)


class AIWorker(QObject):
    chunk_received = Signal(str)
    usage_received = Signal(dict)
    model_selected = Signal(str, str)
    finished = Signal()

    def __init__(self, message_history, model):
        super().__init__()
        self.message_history = message_history
        self.model = model
        self.client = None
        self.settings = SettingsManager()

    _cached_structure: str = ""
    _cached_root: str = ""

    def run(self):
        requested_model = self.model
        self.client = AIClient(selected_full_model=self.model, settings_manager=self.settings)
        log.info("AIWorker starting | requested_model=%s effective_model=%s", requested_model, self.model)

        from core.agent_tools import get_project_root
        project_root = get_project_root()
        cwd = project_root.replace("\\", "/")

        if AIWorker._cached_root != project_root:
            try:
                files = []
                skip = {".git", "__pycache__", "node_modules", ".venv", "venv", "storage", ".vox", "dist", "build"}
                for root, dirs, filenames in os.walk(project_root):
                    dirs[:] = [d for d in dirs if d not in skip]
                    for f in filenames:
                        files.append(os.path.relpath(os.path.join(root, f), project_root))

                stop_idx = min(self.settings.get_max_file_list(), 30)
                file_list_str = "\n".join(files[:stop_idx])
                if len(files) > stop_idx:
                    file_list_str += f"\n...({len(files) - stop_idx} more)"
                AIWorker._cached_structure = f"Project: {cwd} ({len(files)} files)\n{file_list_str}\nUse <list_files /> for full listing."
                AIWorker._cached_root = project_root
            except Exception as e:
                log.error("Structure injection error: %s", e)
                AIWorker._cached_structure = f"Project: {cwd}"

        final_messages = [{"role": "system", "content": AIWorker._cached_structure}]
        for msg in self.message_history:
            if msg.get("role") == "system":
                content = msg["content"]
                if "{cwd_path}" in content:
                    content = content.replace("{cwd_path}", cwd)
                final_messages.append({"role": "system", "content": content})
            else:
                final_messages.append(msg)

        prompt_chars = sum(len(str(m.get("content", ""))) for m in final_messages)
        est_prompt_tokens = prompt_chars // 4
        log.info("AIWorker sending %d messages (~%d est. tokens) to %s", len(final_messages), est_prompt_tokens, self.model)

        api_usage = None
        full_response = ""
        try:
            stream = self.client.stream_chat(final_messages)
            for chunk in stream:
                if QThread.currentThread().isInterruptionRequested():
                    log.info("AIWorker interrupted by user.")
                    break
                if isinstance(chunk, dict):
                    if "usage" in chunk:
                        api_usage = chunk["usage"]
                        self.usage_received.emit(api_usage)
                    continue
                full_response += chunk
                self.chunk_received.emit(chunk)
                QThread.msleep(10)
        except Exception as e:
            log.error("AIWorker stream failed: %s", e)
            self.chunk_received.emit(f"\n[Error: {str(e)}]\n")

        est_completion_tokens = len(full_response) // 4
        if api_usage is None:
            self.usage_received.emit({
                "prompt_tokens": est_prompt_tokens,
                "completion_tokens": est_completion_tokens,
                "total_tokens": est_prompt_tokens + est_completion_tokens,
            })

        log.info(
            "AIWorker done | prompt~%d completion~%d total~%d tokens | response_len=%d chars",
            api_usage.get("prompt_tokens", est_prompt_tokens) if api_usage else est_prompt_tokens,
            api_usage.get("completion_tokens", est_completion_tokens) if api_usage else est_completion_tokens,
            (api_usage.get("total_tokens", 0) if api_usage else est_prompt_tokens + est_completion_tokens),
            len(full_response),
        )
        self.finished.emit()


class ToolWorker(QObject):
    """Executes tool calls in a background thread."""

    step_started = Signal(str, str)
    step_finished = Signal(str, str, str)
    file_changed = Signal(str)
    diff_generated = Signal(str, str)
    confirmation_needed = Signal(str)
    change_proposed = Signal(str, str, str)
    finished = Signal(str)

    DESTRUCTIVE_CMDS = {'delete_file', 'execute_command', 'git_commit', 'git_push', 'git_pull', 'move_file'}
    FILE_WRITE_CMDS = {'write_file', 'edit_file'}

    def __init__(self, tool_calls, auto_approve=False):
        super().__init__()
        self.tool_calls = tool_calls
        self.rag_client = RAGClient()
        self.settings = SettingsManager()
        self.auto_approve = auto_approve
        self._approval_event = threading.Event()
        self._approved = False

    def _rag_enabled(self) -> bool:
        return self.settings.get_rag_enabled()

    def approve(self, yes: bool):
        self._approved = yes
        self._approval_event.set()

    def _request_approval(self, description: str) -> bool:
        if self.auto_approve:
            return True
        self._approval_event.clear()
        self._approved = False
        self.confirmation_needed.emit(description)
        self._approval_event.wait(timeout=120)
        return self._approved

    @staticmethod
    def _command_succeeded(result: str) -> bool:
        text = str(result or "")
        return "[Exit code:" not in text and not text.startswith("[Error")

    @classmethod
    def _tool_succeeded(cls, cmd: str, result: str) -> bool:
        text = str(result or "")
        if cmd in {'execute_command', 'git_status', 'git_diff', 'git_log', 'git_commit', 'git_push', 'git_pull', 'git_fetch'}:
            return cls._command_succeeded(text)
        if cmd in {'write_file', 'edit_file', 'move_file', 'copy_file', 'delete_file'}:
            return "[Success" in text
        if cmd == 'index_codebase':
            return "Successfully indexed codebase" in text
        if cmd in {'web_search', 'fetch_url'}:
            return not text.startswith("[Error")
        return not text.startswith("[Error")

    @staticmethod
    def _build_action_summary(successful_changes, successful_actions, failed_actions) -> str:
        lines = [
            "[ACTION_SUMMARY] (Automated execution summary — use this to ground your next response)",
            "Successful file changes:",
        ]
        lines.extend([f"- {item}" for item in successful_changes] or ["- none"])
        lines.append("Other successful actions:")
        lines.extend([f"- {item}" for item in successful_actions] or ["- none"])
        lines.append("Failed actions:")
        lines.extend([f"- {item}" for item in failed_actions] or ["- none"])
        lines.extend([
            "Rules:",
            "- Only claim a file changed, a fix was applied, or validation passed if it appears in the successful lists above.",
            "- Treat every failed action above as NOT completed, NOT fixed, and NOT validated.",
            "[/ACTION_SUMMARY]",
        ])
        return "\n".join(lines)

    def run(self):
        tool_outputs = []
        successful_changes = []
        successful_actions = []
        failed_actions = []
        for call in self.tool_calls:
            if QThread.currentThread().isInterruptionRequested():
                tool_outputs.append("System: [Interrupted] Tool execution stopped by user.")
                break
            cmd = call['cmd']
            args = call['args']
            enabled, disabled_reason = ToolPolicy.is_tool_enabled(cmd, self.settings)
            if not enabled:
                tool_outputs.append(f"System: [{cmd}] Skipped — {disabled_reason}")
                failed_actions.append(f"{cmd}: {disabled_reason}")
                self.step_finished.emit(f"{cmd} blocked", disabled_reason, "Skipped")
                continue
            if cmd in self.DESTRUCTIVE_CMDS:
                desc_map = {
                    'delete_file': f"Delete: {args.get('path', '?')}",
                    'execute_command': f"Run: {args.get('command', '?')}",
                    'git_commit': f"Git commit: {args.get('message', '?')}",
                    'git_push': f"Git push: {args.get('remote', 'origin')} {args.get('branch', '')}".strip(),
                    'git_pull': f"Git pull: {args.get('remote', 'origin')} {args.get('branch', '')}".strip(),
                    'move_file': f"Move: {args.get('src', '?')} -> {args.get('dst', '?')}",
                }
                if not self._request_approval(desc_map.get(cmd, cmd)):
                    tool_outputs.append(f"System: [{cmd}] Skipped — user declined.")
                    self.step_finished.emit(f"{cmd} declined", None, "Skipped")
                    continue
            try:
                if cmd == 'list_files':
                    path = args.get('path', '.')
                    self.step_started.emit("📂", f"Listing files in {path}...")
                    result = AgentToolHandler.list_files(path)
                    tool_outputs.append(f"Listed files in '{path}':\n{result}")
                    self.step_finished.emit(f"Listed files in: {path}", None, "Done")
                elif cmd == 'read_file':
                    path = args.get('path')
                    try:
                        start = int(args.get('start_line', 1))
                    except (ValueError, TypeError):
                        start = 1
                    try:
                        end = int(args.get('end_line', 300))
                    except (ValueError, TypeError):
                        end = 300
                    with_line_numbers = str(args.get('with_line_numbers', 'false')).lower() == 'true'
                    self.step_started.emit("📖", f"Reading {os.path.basename(path)}...")
                    content = AgentToolHandler.read_file(path, start_line=start, end_line=end, with_line_numbers=with_line_numbers)
                    tool_outputs.append(f"Read file '{path}':\n{content}")
                    self.step_finished.emit(f"Read file: {path}", None, "Done")
                elif cmd == 'read_json':
                    path = args.get('path')
                    query = args.get('query')
                    try:
                        max_chars = int(args.get('max_chars', 4000))
                    except (ValueError, TypeError):
                        max_chars = 4000
                    self.step_started.emit("🧾", f"Inspecting JSON {os.path.basename(path)}...")
                    result = AgentToolHandler.read_json(path, query=query, max_chars=max_chars)
                    tool_outputs.append(f"JSON content for '{path}':\n{result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_actions.append(f"read_json: {path}" + (f" ({query})" if query else ""))
                    else:
                        failed_actions.append(f"read_json {path}: {result}")
                    self.step_finished.emit(f"Read JSON: {path}", None, "Done" if success else "Failed")
                elif cmd == 'read_python_symbols':
                    path = args.get('path')
                    symbols = args.get('symbols')
                    with_line_numbers = str(args.get('with_line_numbers', 'true')).lower() == 'true'
                    try:
                        max_symbols = int(args.get('max_symbols', 5))
                    except (ValueError, TypeError):
                        max_symbols = 5
                    self.step_started.emit("🧠", f"Reading Python symbols from {os.path.basename(path)}...")
                    result = AgentToolHandler.read_python_symbols(path, symbols=symbols, with_line_numbers=with_line_numbers, max_symbols=max_symbols)
                    tool_outputs.append(f"Python symbols from '{path}':\n{result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_actions.append(f"read_python_symbols: {path} ({symbols})")
                    else:
                        failed_actions.append(f"read_python_symbols {path}: {result}")
                    self.step_finished.emit(f"Read Python symbols: {path}", None, "Done" if success else "Failed")
                elif cmd == 'find_tests':
                    query = args.get('query')
                    source_path = args.get('source_path')
                    root = args.get('root_dir', 'tests')
                    try:
                        max_results = int(args.get('max_results', 20))
                    except (ValueError, TypeError):
                        max_results = 20
                    label = source_path or query
                    self.step_started.emit("🧪", f"Finding tests for '{label}'...")
                    result = AgentToolHandler.find_tests(query=query, source_path=source_path, root_dir=root, max_results=max_results)
                    tool_outputs.append(f"Tests for '{label}':\n{result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_actions.append(f"find_tests: {label}")
                    else:
                        failed_actions.append(f"find_tests {label}: {result}")
                    self.step_finished.emit(f"Found tests: {label}", None, "Done" if success else "Failed")
                elif cmd == 'write_file':
                    path = args.get('path')
                    content = args.get('content')
                    self.step_started.emit("📝", f"Writing {os.path.basename(path)}...")
                    syntax_error = AgentToolHandler.validate_syntax(content, path)
                    if syntax_error:
                        tool_outputs.append(f"System: [Syntax Error] in '{path}':\n{syntax_error}")
                        self.step_finished.emit(f"Syntax Error in {os.path.basename(path)}", syntax_error, "Failed")
                        continue
                    diff_text = None
                    diff_str = "modified"
                    full_path = AgentToolHandler.resolve_path(path)
                    if os.path.exists(full_path):
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f:
                                old_content = f.read()
                            diff_text = AgentToolHandler.get_diff(old_content, content, os.path.basename(path))
                        except Exception:
                            diff_text = "[Error generating diff]"
                    else:
                        diff_str = "new"
                        diff_text = f"[New File]\n{content}"
                    if not self.auto_approve and diff_text and "[Error" not in diff_text:
                        self.change_proposed.emit(full_path, diff_text, content)
                        if not self._request_approval(f"Write file: {path} ({diff_str})"):
                            tool_outputs.append(f"System: [{cmd}] Write to '{path}' rejected by user.")
                            self.step_finished.emit(f"Write {os.path.basename(path)} rejected", None, "Skipped")
                            continue
                    result = AgentToolHandler.write_file(path, content)
                    tool_outputs.append(f"System: Wrote file '{path}' ({result})")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_changes.append(path)
                        self.file_changed.emit(full_path)
                    else:
                        failed_actions.append(f"write_file {path}: {result}")
                    if success and diff_text and "[Error" not in diff_text:
                        self.diff_generated.emit(full_path, diff_text)
                    self.step_finished.emit(f"Wrote {os.path.basename(path)} ({diff_str})", diff_text, "Done" if success else "Failed")
                elif cmd == 'move_file':
                    src = args.get('src')
                    dst = args.get('dst')
                    self.step_started.emit("➡️", f"Moving {os.path.basename(src)}...")
                    result = AgentToolHandler.move_file(src, dst)
                    tool_outputs.append(f"System: {result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_changes.append(f"{src} -> {dst}")
                        self.file_changed.emit(AgentToolHandler.resolve_path(dst))
                    else:
                        failed_actions.append(f"move_file {src} -> {dst}: {result}")
                    self.step_finished.emit(f"Moved {src} to {dst}", None, "Done" if success else "Failed")
                elif cmd == 'copy_file':
                    src = args.get('src')
                    dst = args.get('dst')
                    self.step_started.emit("📋", f"Copying {os.path.basename(src)}...")
                    result = AgentToolHandler.copy_file(src, dst)
                    tool_outputs.append(f"System: {result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_changes.append(f"{src} -> {dst}")
                        self.file_changed.emit(AgentToolHandler.resolve_path(dst))
                    else:
                        failed_actions.append(f"copy_file {src} -> {dst}: {result}")
                    self.step_finished.emit(f"Copied {src} to {dst}", None, "Done" if success else "Failed")
                elif cmd == 'delete_file':
                    path = args.get('path')
                    self.step_started.emit("🗑️", f"Deleting {os.path.basename(path)}...")
                    result = AgentToolHandler.delete_file(path)
                    tool_outputs.append(f"System: {result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_changes.append(path)
                        self.file_changed.emit(AgentToolHandler.resolve_path(path))
                    else:
                        failed_actions.append(f"delete_file {path}: {result}")
                    self.step_finished.emit(f"Deleted {path}", None, "Done" if success else "Failed")
                elif cmd == 'search_files':
                    query = args.get('query')
                    root = args.get('root_dir', '.')
                    file_pattern = args.get('file_pattern')
                    case_insensitive = str(args.get('case_insensitive', 'false')).lower() == 'true'
                    try:
                        context_lines = int(args.get('context_lines', 0))
                    except (ValueError, TypeError):
                        context_lines = 0
                    try:
                        max_results = int(args.get('max_results', 100))
                    except (ValueError, TypeError):
                        max_results = 100
                    self.step_started.emit("🔍", f"Searching '{query}'...")
                    result = AgentToolHandler.search_files(query, root, file_pattern=file_pattern, case_insensitive=case_insensitive, context_lines=context_lines, max_results=max_results)
                    tool_outputs.append(f"Search Results for '{query}':\n{result}")
                    self.step_finished.emit(f"Searched for '{query}'", None, "Done")
                elif cmd == 'find_files':
                    pattern = args.get('pattern')
                    root = args.get('root_dir', '.')
                    case_insensitive = str(args.get('case_insensitive', 'false')).lower() == 'true'
                    try:
                        max_results = int(args.get('max_results', 100))
                    except (ValueError, TypeError):
                        max_results = 100
                    self.step_started.emit("🧭", f"Finding files matching '{pattern}'...")
                    result = AgentToolHandler.find_files(pattern, root_dir=root, case_insensitive=case_insensitive, max_results=max_results)
                    tool_outputs.append(f"Found Files for '{pattern}':\n{result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_actions.append(f"find_files: {pattern}")
                    else:
                        failed_actions.append(f"find_files {pattern}: {result}")
                    self.step_finished.emit(f"Found files: {pattern}", None, "Done" if success else "Failed")
                elif cmd == 'find_symbol':
                    symbol = args.get('symbol')
                    root = args.get('root_dir', '.')
                    symbol_type = args.get('symbol_type')
                    file_pattern = args.get('file_pattern', '*.py')
                    try:
                        max_results = int(args.get('max_results', 50))
                    except (ValueError, TypeError):
                        max_results = 50
                    self.step_started.emit("🔎", f"Finding symbol '{symbol}'...")
                    result = AgentToolHandler.find_symbol(symbol, root_dir=root, symbol_type=symbol_type, file_pattern=file_pattern, max_results=max_results)
                    tool_outputs.append(f"Python symbols for '{symbol}':\n{result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_actions.append(f"find_symbol: {symbol}")
                    else:
                        failed_actions.append(f"find_symbol {symbol}: {result}")
                    self.step_finished.emit(f"Found symbol: {symbol}", None, "Done" if success else "Failed")
                elif cmd == 'find_references':
                    symbol = args.get('symbol')
                    root = args.get('root_dir', '.')
                    file_pattern = args.get('file_pattern', '*.py')
                    include_definitions = str(args.get('include_definitions', 'false')).lower() == 'true'
                    try:
                        context_lines = int(args.get('context_lines', 1))
                    except (ValueError, TypeError):
                        context_lines = 1
                    try:
                        max_results = int(args.get('max_results', 50))
                    except (ValueError, TypeError):
                        max_results = 50
                    self.step_started.emit("🧷", f"Finding references to '{symbol}'...")
                    result = AgentToolHandler.find_references(symbol, root_dir=root, file_pattern=file_pattern, context_lines=context_lines, max_results=max_results, include_definitions=include_definitions)
                    tool_outputs.append(f"Python references for '{symbol}':\n{result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_actions.append(f"find_references: {symbol}")
                    else:
                        failed_actions.append(f"find_references {symbol}: {result}")
                    self.step_finished.emit(f"Found references: {symbol}", None, "Done" if success else "Failed")
                elif cmd == 'get_imports':
                    path = args.get('path')
                    include_external = str(args.get('include_external', 'true')).lower() == 'true'
                    self.step_started.emit("🕸️", f"Inspecting imports in {os.path.basename(path)}...")
                    result = AgentToolHandler.get_imports(path, include_external=include_external)
                    tool_outputs.append(f"Imports in '{path}':\n{result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_actions.append(f"get_imports: {path}")
                    else:
                        failed_actions.append(f"get_imports {path}: {result}")
                    self.step_finished.emit(f"Imports in: {path}", None, "Done" if success else "Failed")
                elif cmd == 'find_importers':
                    target = args.get('target')
                    root = args.get('root_dir', '.')
                    file_pattern = args.get('file_pattern', '*.py')
                    try:
                        max_results = int(args.get('max_results', 50))
                    except (ValueError, TypeError):
                        max_results = 50
                    self.step_started.emit("🕵️", f"Finding importers of '{target}'...")
                    result = AgentToolHandler.find_importers(target, root_dir=root, file_pattern=file_pattern, max_results=max_results)
                    tool_outputs.append(f"Importers for '{target}':\n{result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_actions.append(f"find_importers: {target}")
                    else:
                        failed_actions.append(f"find_importers {target}: {result}")
                    self.step_finished.emit(f"Found importers: {target}", None, "Done" if success else "Failed")
                elif cmd == 'get_file_structure':
                    path = args.get('path')
                    self.step_started.emit("🌳", f"Analyzing {os.path.basename(path)}...")
                    result = AgentToolHandler.get_file_structure(path)
                    tool_outputs.append(f"Structure of '{path}':\n{result}")
                    self.step_finished.emit(f"Got structure of: {path}", None, "Done")
                elif cmd == 'execute_command':
                    command = args.get('command')
                    cwd = args.get('cwd') or '.'
                    self.step_started.emit("💻", f"Executing: {command}...")
                    result = AgentToolHandler.execute_command(command, cwd)
                    tool_outputs.append(f"Command Output:\n{result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_actions.append(f"execute_command: {command}")
                    else:
                        failed_actions.append(f"execute_command {command}: {result}")
                    self.step_finished.emit(f"Executed: {command}", result, "Done" if success else "Failed")
                elif cmd == 'search_memory':
                    query = args.get('query')
                    self.step_started.emit("🧠", f"Searching memory for '{query}'...")
                    if not self._rag_enabled():
                        tool_outputs.append("System: RAG memory search is disabled in settings.")
                        self.step_finished.emit("Recall disabled", "Enable RAG in settings to search memory.", "Skipped")
                        continue
                    chunks = self.rag_client.retrieve(query, k=self.settings.get_rag_top_k())
                    if chunks:
                        context = self.rag_client.format_context_block(chunks)
                        tool_outputs.append(f"Memory found for '{query}':\n{context}")
                        self.step_finished.emit(f"Recall: found {len(chunks)} relevant memories", context, "Done")
                    else:
                        tool_outputs.append(f"System: No relevant memories found for '{query}'.")
                        self.step_finished.emit("Recall: No matches in archive", None, "Done")
                elif cmd == 'search_codebase':
                    query = args.get('query')
                    self.step_started.emit("🔎", f"Searching codebase for '{query}'...")
                    if not self._rag_enabled():
                        tool_outputs.append("System: RAG codebase search is disabled in settings.")
                        self.step_finished.emit("Code search disabled", "Enable RAG in settings to search the codebase.", "Skipped")
                        continue
                    top_k = self.settings.get_rag_top_k()
                    candidate_k = min(100, max(top_k * 5, top_k + 20))
                    chunks = self.rag_client.retrieve(query, k=candidate_k)
                    chunks = [c for c in chunks if str(c.doc_id).startswith("file:")][:top_k]
                    preview_limit = self.settings.get_rag_max_chunk()
                    if chunks:
                        output = [f"Codebase Search Results for '{query}':"]
                        for i, c in enumerate(chunks, 1):
                            source_type = "File"
                            location = c.doc_id
                            if "file:" in c.doc_id:
                                parts = c.doc_id.split(":")
                                if len(parts) >= 3:
                                    location = parts[2]
                            output.append(f"\n--- Result {i} ({source_type}) | Score: {c.score:.4f} ---")
                            output.append(f"Location: {location}")
                            if c.start_line > 0:
                                output.append(f"Lines: {c.start_line}-{c.end_line}")
                            content_preview = c.content.strip()
                            if len(content_preview) > preview_limit:
                                content_preview = content_preview[:preview_limit] + "...(truncated)"
                            output.append(f"Content:\n{content_preview}\n")
                        tool_outputs.append("\n".join(output))
                        self.step_finished.emit(f"Search: found {len(chunks)} code results", None, "Done")
                    else:
                        tool_outputs.append(f"System: No relevant code found for '{query}'.")
                        self.step_finished.emit("Search: No matches found", None, "Done")
                elif cmd == 'edit_file':
                    path = args.get('path')
                    old_text = html.unescape(args.get('old_text', ''))
                    new_text = html.unescape(args.get('new_text', args.get('content', '')))
                    start_line = args.get('start_line')
                    end_line = args.get('end_line')
                    occurrence = args.get('occurrence')
                    match_mode = args.get('match_mode', 'smart')
                    replace_all = str(args.get('replace_all', 'false')).lower() == 'true'
                    anchor_before = html.unescape(args.get('anchor_before', ''))
                    anchor_after = html.unescape(args.get('anchor_after', ''))
                    insert_before = html.unescape(args.get('insert_before', ''))
                    insert_after = html.unescape(args.get('insert_after', ''))
                    try:
                        start_line = int(start_line) if start_line not in (None, '') else None
                    except (TypeError, ValueError):
                        pass
                    try:
                        end_line = int(end_line) if end_line not in (None, '') else None
                    except (TypeError, ValueError):
                        pass
                    try:
                        occurrence = int(occurrence) if occurrence not in (None, '') else None
                    except (TypeError, ValueError):
                        pass
                    edit_kwargs = {
                        'start_line': start_line,
                        'end_line': end_line,
                        'match_mode': match_mode,
                        'occurrence': occurrence,
                        'replace_all': replace_all,
                        'anchor_before': anchor_before,
                        'anchor_after': anchor_after,
                        'insert_before': insert_before,
                        'insert_after': insert_after,
                    }
                    self.step_started.emit("✏️", f"Editing {os.path.basename(path)}...")
                    full_path = AgentToolHandler.resolve_path(path)
                    old_content = ""
                    if os.path.exists(full_path):
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f:
                                old_content = f.read()
                        except Exception:
                            pass
                    if not self.auto_approve:
                        preview = AgentToolHandler.preview_edit(path, old_text=old_text, new_text=new_text, **edit_kwargs)
                        diff_text = preview.get('error', '')
                        if not diff_text:
                            diff_text = AgentToolHandler.get_diff(preview.get('old_content', old_content), preview.get('new_content', old_content), os.path.basename(path))
                            if not diff_text:
                                diff_text = f"[Preview: {preview.get('summary', 'edit produced no visible diff')}]"
                        preview_content = preview.get('new_content', old_content)
                        self.change_proposed.emit(full_path, diff_text, preview_content)
                        if not self._request_approval(f"Edit file: {path}"):
                            tool_outputs.append(f"System: [{cmd}] Edit to '{path}' rejected by user.")
                            self.step_finished.emit(f"Edit {os.path.basename(path)} rejected", None, "Skipped")
                            continue
                    result = AgentToolHandler.edit_file(path, old_text=old_text, new_text=new_text, **edit_kwargs)
                    tool_outputs.append(f"System: {result}")
                    if "[Success" in result:
                        successful_changes.append(path)
                        self.file_changed.emit(full_path)
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f:
                                new_content = f.read()
                            diff_text = AgentToolHandler.get_diff(old_content, new_content, os.path.basename(path))
                            if diff_text:
                                self.diff_generated.emit(full_path, diff_text)
                        except Exception:
                            pass
                    else:
                        failed_actions.append(f"edit_file {path}: {result}")
                    self.step_finished.emit(f"Edited {os.path.basename(path)}", None, "Done" if "[Success" in result else "Failed")
                elif cmd == 'index_codebase':
                    path = args.get('path', '.')
                    self.step_started.emit("📚", f"Indexing codebase at {path}...")
                    if not self._rag_enabled():
                        tool_outputs.append("System: RAG indexing is disabled in settings.")
                        self.step_finished.emit("Indexing disabled", "Enable RAG in settings to index the codebase.", "Skipped")
                        continue
                    from core.indexer import ProjectIndexer
                    indexer = ProjectIndexer()
                    success = indexer.index_project(path)
                    if success:
                        tool_outputs.append(f"System: Successfully indexed codebase at '{path}'.")
                        successful_actions.append(f"index_codebase: {path}")
                        self.step_finished.emit(f"Indexed {path}", None, "Done")
                    else:
                        tool_outputs.append(f"System: Failed to index codebase at '{path}'. Check logs.")
                        failed_actions.append(f"index_codebase {path}: Failed to index codebase")
                        self.step_finished.emit("Indexing failed", "Check logs", "Failed")
                elif cmd in ('git_status', 'git_diff', 'git_log', 'git_commit', 'git_push', 'git_pull', 'git_fetch'):
                    remote = args.get('remote', 'origin')
                    branch = args.get('branch', '')
                    git_cmds = {
                        'git_status': 'git status --short',
                        'git_diff': 'git diff' + (f" {args.get('path', '')}" if args.get('path') else ''),
                        'git_log': f"git log --oneline -n {args.get('count', '15')}",
                        'git_commit': f"git add -A && git commit -m \"{args.get('message', 'auto-commit')}\"",
                        'git_push': f"git push {remote} {branch}".strip(),
                        'git_pull': f"git pull {remote} {branch}".strip(),
                        'git_fetch': f"git fetch {remote}".strip(),
                    }
                    git_cmd = git_cmds[cmd]
                    self.step_started.emit("🔀", f"Git: {git_cmd}...")
                    result = AgentToolHandler.execute_command(git_cmd)
                    tool_outputs.append(f"Git Output ({cmd}):\n{result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_actions.append(f"{cmd}: {git_cmd}")
                    else:
                        failed_actions.append(f"{cmd} {git_cmd}: {result}")
                    self.step_finished.emit(f"Git: {cmd}", result, "Done" if success else "Failed")
                elif cmd == 'web_search':
                    query = args.get('query', '')
                    self.step_started.emit("🌐", f"Searching web: {query}...")
                    try:
                        from Vox_IronGate import IronGateClient
                        result = IronGateClient.web_search(query)
                    except ImportError:
                        result = "[Error: IronGate web client not available]"
                    except Exception as e:
                        result = f"[Error: Web search failed — {e}]"
                    tool_outputs.append(f"Web Search Results:\n{result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_actions.append(f"web_search: {query}")
                    else:
                        failed_actions.append(f"web_search {query}: {result}")
                    self.step_finished.emit(f"Web search: {query}", None, "Done" if success else "Failed")
                elif cmd == 'fetch_url':
                    url = args.get('url', '')
                    self.step_started.emit("🔗", f"Fetching {url}...")
                    try:
                        from Vox_IronGate import IronGateClient
                        result = IronGateClient.fetch_url(url)
                    except ImportError:
                        result = "[Error: IronGate web client not available]"
                    except Exception as e:
                        result = f"[Error: Fetch failed — {e}]"
                    tool_outputs.append(f"Fetched URL:\n{result}")
                    success = self._tool_succeeded(cmd, result)
                    if success:
                        successful_actions.append(f"fetch_url: {url}")
                    else:
                        failed_actions.append(f"fetch_url {url}: {result}")
                    self.step_finished.emit(f"Fetched: {url}", None, "Done" if success else "Failed")
            except Exception as e:
                tool_outputs.append(f"[TOOL_ERROR] {cmd} failed: {e}\nAnalyze this error and either fix the inputs and retry, or explain the issue to the user.")
                failed_actions.append(f"{cmd}: {e}")
                self.step_finished.emit(f"Error in {cmd}", str(e), "Failed")
        summary = self._build_action_summary(successful_changes, successful_actions, failed_actions)
        self.finished.emit(summary + "\n\n" + "\n\n".join(tool_outputs))


class IndexingWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(bool)

    def __init__(self, root_path):
        super().__init__()
        self.root_path = root_path
        from core.indexer import ProjectIndexer
        self.indexer = ProjectIndexer()

    def run(self):
        try:
            success = self.indexer.index_project(
                self.root_path,
                progress_callback=self.progress.emit,
                cancel_callback=lambda: QThread.currentThread().isInterruptionRequested(),
            )
            self.finished.emit(success)
        except Exception as e:
            log.error("IndexingWorker failed: %s", e)
            self.finished.emit(False)


__all__ = ["AIWorker", "ToolWorker", "IndexingWorker"]