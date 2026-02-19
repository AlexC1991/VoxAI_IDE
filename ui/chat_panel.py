
# -*- coding: utf-8 -*-
import os
import re
import json
import logging
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, 
    QTextEdit, QPushButton, QFrame, QLabel, QMessageBox,
    QComboBox, QSizePolicy
)
from PySide6.QtCore import Signal, Qt, QThread, QObject, QTimer, QEvent
from PySide6.QtGui import QPixmap, QPainter, QColor

from core.settings import SettingsManager
from core.ai_client import AIClient
from core.rag_client import RAGClient
from core.code_parser import CodeParser
from core.agent_tools import AgentToolHandler, get_resource_path
from core.prompts import SystemPrompts
from ui.widgets.chat_items import MessageItem, ProgressItem

log = logging.getLogger(__name__)


class WatermarkContainer(QWidget):
    """Layer 1 & 2: Base Gray + Background Image."""
    def __init__(self, parent=None, logo_path=None):
        super().__init__(parent)
        self.logo = None
        if logo_path:
            logo_path = os.path.realpath(logo_path)
            if os.path.exists(logo_path):
                self.logo = QPixmap(logo_path)
                if self.logo.isNull():
                    log.error(f"WatermarkContainer: Failed to load logo from {logo_path}")
                else:
                    log.info(f"WatermarkContainer: Loaded logo {self.logo.width()}x{self.logo.height()}")
            else:
                log.warning(f"WatermarkContainer: Logo path does not exist: {logo_path}")
        
        # This widget will hold the ScrollArea
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
            
    def paintEvent(self, event):
        painter = QPainter(self)
        # LAYER 1: Base Gray
        painter.fillRect(self.rect(), QColor("#18181b"))
        
        # LAYER 2: Background Image
        if self.logo and not self.logo.isNull():
            vw, vh = self.width(), self.height()
            if vw > 0 and vh > 0:
                # Stretch logo to cover the entire chat section as requested
                scaled_logo = self.logo.scaled(
                    self.size(), 
                    Qt.IgnoreAspectRatio, 
                    Qt.SmoothTransformation
                )
                
                if not scaled_logo.isNull():
                    painter.setOpacity(1.0) 
                    painter.drawPixmap(0, 0, scaled_logo)

# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

class AIWorker(QObject):
    chunk_received = Signal(str)
    usage_received = Signal(dict)
    finished = Signal()
    
    def __init__(self, message_history, model):
        super().__init__()
        self.message_history = message_history
        self.model = model
        self.client = AIClient()
        self.settings = SettingsManager()

    # Class-level project structure cache
    _cached_structure: str = ""
    _cached_root: str = ""

    def run(self):
        log.info("AIWorker starting | model=%s", self.model)

        from core.agent_tools import get_project_root
        project_root = get_project_root()
        cwd = project_root.replace("\\", "/")

        # Use cached structure if same project root
        if AIWorker._cached_root != project_root:
            try:
                files = []
                skip = {".git", "__pycache__", "node_modules", ".venv",
                        "venv", "storage", ".vox", "dist", "build"}
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

        final_messages = []
        final_messages.append({"role": "system", "content": AIWorker._cached_structure})

        for msg in self.message_history:
            if msg.get("role") == "system":
                content = msg["content"]
                if "{cwd_path}" in content:
                    content = content.replace("{cwd_path}", cwd)
                final_messages.append({"role": "system", "content": content})
            else:
                final_messages.append(msg)

        # Token estimation for monitoring
        prompt_chars = sum(
            len(str(m.get("content", ""))) for m in final_messages
        )
        est_prompt_tokens = prompt_chars // 4
        log.info("AIWorker sending %d messages (~%d est. tokens) to %s",
                 len(final_messages), est_prompt_tokens, self.model)

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

        # Always emit token estimate so the UI footer is populated
        est_completion_tokens = len(full_response) // 4
        if api_usage is None:
            usage = {
                "prompt_tokens": est_prompt_tokens,
                "completion_tokens": est_completion_tokens,
                "total_tokens": est_prompt_tokens + est_completion_tokens,
            }
            self.usage_received.emit(usage)

        log.info("AIWorker done | prompt~%d completion~%d total~%d tokens | response_len=%d chars",
                 api_usage.get("prompt_tokens", est_prompt_tokens) if api_usage else est_prompt_tokens,
                 api_usage.get("completion_tokens", est_completion_tokens) if api_usage else est_completion_tokens,
                 (api_usage.get("total_tokens", 0) if api_usage
                  else est_prompt_tokens + est_completion_tokens),
                 len(full_response))
        self.finished.emit()


class ToolWorker(QObject):
    """Executes tool calls in a background thread."""
    step_started = Signal(str, str) # icon, text
    step_finished = Signal(str, str, str) # title, detail (if any), result_summary
    file_changed = Signal(str)
    diff_generated = Signal(str, str) # file_path, unified diff text
    confirmation_needed = Signal(str) # description of action needing approval
    change_proposed = Signal(str, str, str) # path, diff_text, new_content — for accept/reject
    finished = Signal(str) # combined output text

    DESTRUCTIVE_CMDS = {'delete_file', 'execute_command', 'git_commit', 'git_push'}
    FILE_WRITE_CMDS = {'write_file', 'edit_file'}

    def __init__(self, tool_calls, auto_approve=False):
        super().__init__()
        self.tool_calls = tool_calls
        self.rag_client = RAGClient()
        self.auto_approve = auto_approve
        self._approval_event = threading.Event()
        self._approved = False

    def approve(self, yes: bool):
        """Called from UI thread after user responds to confirmation dialog."""
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

    def run(self):
        tool_outputs = []
        
        for call in self.tool_calls:
            if QThread.currentThread().isInterruptionRequested():
                tool_outputs.append("System: [Interrupted] Tool execution stopped by user.")
                break

            cmd = call['cmd']
            args = call['args']

            if cmd in self.DESTRUCTIVE_CMDS:
                desc_map = {
                    'delete_file': f"Delete: {args.get('path', '?')}",
                    'execute_command': f"Run: {args.get('command', '?')}",
                    'git_commit': f"Git commit: {args.get('message', '?')}",
                    'git_push': f"Git push: {args.get('remote', 'origin')} {args.get('branch', '')}".strip(),
                }
                if not self._request_approval(desc_map.get(cmd, cmd)):
                    tool_outputs.append(f"System: [{cmd}] Skipped — user declined.")
                    self.step_finished.emit(f"{cmd} declined", None, "Skipped")
                    continue

            try:
                # Map commands to handler methods
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
                    
                    self.step_started.emit("📖", f"Reading {os.path.basename(path)}...")
                    content = AgentToolHandler.read_file(path, start_line=start, end_line=end)
                    tool_outputs.append(f"Read file '{path}':\n{content}")
                    self.step_finished.emit(f"Read file: {path}", None, "Done")
                    
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
                    full_path = os.path.abspath(path)
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

                    # Apply/reject: show diff and ask for approval in non-Siege mode
                    if not self.auto_approve and diff_text and "[Error" not in diff_text:
                        self.change_proposed.emit(full_path, diff_text, content)
                        if not self._request_approval(f"Write file: {path} ({diff_str})"):
                            tool_outputs.append(f"System: [{cmd}] Write to '{path}' rejected by user.")
                            self.step_finished.emit(f"Write {os.path.basename(path)} rejected", None, "Skipped")
                            continue

                    result = AgentToolHandler.write_file(path, content)
                    tool_outputs.append(f"System: Wrote file '{path}' ({result})")
                    self.file_changed.emit(full_path)
                    if diff_text and "[Error" not in diff_text:
                        self.diff_generated.emit(full_path, diff_text)
                    self.step_finished.emit(f"Wrote {os.path.basename(path)} ({diff_str})", diff_text, "Done")

                elif cmd == 'move_file':
                    src = args.get('src')
                    dst = args.get('dst')
                    self.step_started.emit("➡️", f"Moving {os.path.basename(src)}...")
                    result = AgentToolHandler.move_file(src, dst)
                    tool_outputs.append(f"System: {result}")
                    self.file_changed.emit(os.path.abspath(dst))
                    self.step_finished.emit(f"Moved {src} to {dst}", None, "Done")

                elif cmd == 'copy_file':
                    src = args.get('src')
                    dst = args.get('dst')
                    self.step_started.emit("📋", f"Copying {os.path.basename(src)}...")
                    result = AgentToolHandler.copy_file(src, dst)
                    tool_outputs.append(f"System: {result}")
                    self.file_changed.emit(os.path.abspath(dst))
                    self.step_finished.emit(f"Copied {src} to {dst}", None, "Done")

                elif cmd == 'delete_file':
                    path = args.get('path')
                    self.step_started.emit("🗑️", f"Deleting {os.path.basename(path)}...")
                    result = AgentToolHandler.delete_file(path)
                    tool_outputs.append(f"System: {result}")
                    self.file_changed.emit(os.path.abspath(path))
                    self.step_finished.emit(f"Deleted {path}", None, "Done")

                elif cmd == 'search_files':
                    query = args.get('query')
                    root = args.get('root_dir', '.')
                    self.step_started.emit("🔍", f"Searching '{query}'...")
                    result = AgentToolHandler.search_files(query, root)
                    tool_outputs.append(f"Search Results for '{query}':\n{result}")
                    self.step_finished.emit(f"Searched for '{query}'", None, "Done")

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
                    self.step_finished.emit(f"Executed: {command}", result, "Done")

                elif cmd == 'search_memory':
                    query = args.get('query')
                    self.step_started.emit("🧠", f"Searching memory for '{query}'...")
                    # Use RAG to recall memories
                    chunks = self.rag_client.retrieve(query)
                    
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
                    # Use RAG to recall memories/code
                    chunks = self.rag_client.retrieve(query, k=5)
                    
                    if chunks:
                        output = []
                        output.append(f"Codebase Search Results for '{query}':")
                        for i, c in enumerate(chunks, 1):
                            source_type = "File" if "file:" in c.doc_id else "Chat Memory"
                            location = c.doc_id
                            if "file:" in c.doc_id:
                                parts = c.doc_id.split(":")
                                if len(parts) >= 3:
                                    location = parts[2] # filepath
                            
                            output.append(f"\n--- Result {i} ({source_type}) | Score: {c.score:.4f} ---")
                            output.append(f"Location: {location}")
                            if c.start_line > 0:
                                output.append(f"Lines: {c.start_line}-{c.end_line}")
                            content_preview = c.content.strip()
                            if len(content_preview) > 500:
                                content_preview = content_preview[:500] + "...(truncated)"
                            output.append(f"Content:\n{content_preview}\n")
                        
                        tool_outputs.append("\n".join(output))
                        self.step_finished.emit(f"Search: found {len(chunks)} relevant results", None, "Done")
                    else:
                        tool_outputs.append(f"System: No relevant code/memory found for '{query}'.")
                        self.step_finished.emit("Search: No matches found", None, "Done")

                elif cmd == 'edit_file':
                    path = args.get('path')
                    old_text = args.get('old_text', args.get('content', ''))
                    new_text = args.get('new_text', '')
                    self.step_started.emit("✏️", f"Editing {os.path.basename(path)}...")

                    full_path = os.path.abspath(path)
                    old_content = ""
                    if os.path.exists(full_path):
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f:
                                old_content = f.read()
                        except Exception:
                            pass

                    # Preview diff for accept/reject in non-Siege mode
                    if not self.auto_approve and old_content and old_text in old_content:
                        preview_content = old_content.replace(old_text, new_text, 1)
                        diff_text = AgentToolHandler.get_diff(
                            old_content, preview_content, os.path.basename(path))
                        if diff_text:
                            self.change_proposed.emit(full_path, diff_text, preview_content)
                            if not self._request_approval(f"Edit file: {path}"):
                                tool_outputs.append(f"System: [{cmd}] Edit to '{path}' rejected by user.")
                                self.step_finished.emit(f"Edit {os.path.basename(path)} rejected", None, "Skipped")
                                continue

                    result = AgentToolHandler.edit_file(path, old_text, new_text)
                    tool_outputs.append(f"System: {result}")

                    if "[Success" in result:
                        self.file_changed.emit(full_path)
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f:
                                new_content = f.read()
                            diff_text = AgentToolHandler.get_diff(
                                old_content, new_content, os.path.basename(path))
                            if diff_text:
                                self.diff_generated.emit(full_path, diff_text)
                        except Exception:
                            pass
                    self.step_finished.emit(f"Edited {os.path.basename(path)}", None, "Done")

                elif cmd == 'index_codebase':
                    path = args.get('path', '.')
                    self.step_started.emit("📚", f"Indexing codebase at {path}...")
                    
                    from core.indexer import ProjectIndexer
                    indexer = ProjectIndexer()
                    success = indexer.index_project(path)
                    
                    if success:
                        tool_outputs.append(f"System: Successfully indexed codebase at '{path}'.")
                        self.step_finished.emit(f"Indexed {path}", None, "Done")
                    else:
                        tool_outputs.append(f"System: Failed to index codebase at '{path}'. Check logs.")
                        self.step_finished.emit(f"Indexing failed", "Check logs", "Failed")

                elif cmd in ('git_status', 'git_diff', 'git_log', 'git_commit',
                             'git_push', 'git_pull', 'git_fetch'):
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
                    self.step_finished.emit(f"Git: {cmd}", result, "Done")

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
                    self.step_finished.emit(f"Web search: {query}", None, "Done")

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
                    self.step_finished.emit(f"Fetched: {url}", None, "Done")

            except Exception as e:
                tool_outputs.append(
                    f"[TOOL_ERROR] {cmd} failed: {e}\n"
                    f"Analyze this error and either fix the inputs and retry, "
                    f"or explain the issue to the user."
                )
                self.step_finished.emit(f"Error in {cmd}", str(e), "Failed")
        
        self.finished.emit("\n\n".join(tool_outputs))


class IndexingWorker(QObject):
    progress = Signal(int, int, str) # current, total, filename
    finished = Signal(bool)

    def __init__(self, root_path):
        super().__init__()
        self.root_path = root_path
        from core.indexer import ProjectIndexer
        self.indexer = ProjectIndexer()

    def run(self):
        try:
            success = self.indexer.index_project(self.root_path, progress_callback=self.progress.emit)
            self.finished.emit(success)
        except Exception as e:
            log.error("IndexingWorker failed: %s", e)
            self.finished.emit(False)


# ---------------------------------------------------------------------------
# Main Chat Panel
# ---------------------------------------------------------------------------
class ChatPanel(QWidget):
    message_sent = Signal(str)
    code_generated = Signal(str, str) # language, code
    file_updated = Signal(str) # absolute path
    diff_ready = Signal(str, str) # file_path, unified diff text
    notification_requested = Signal(str, str) # title, message
    token_usage_updated = Signal(int) # total tokens for status bar
    conversation_changed = Signal()  # emitted when conversations are saved/switched
    MAX_RENDERED_MESSAGES = 140
    CHAT_MAX_WIDTH = 1080

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
        self.current_ai_item = None
        self.progress_item = None
        self._tool_calls_for_run = []
        self._tool_action_log = []

        # Load system prompt
        from core.prompts import SystemPrompts
        self.system_prompt = SystemPrompts.CODING_AGENT

        # Restore previous conversation if available
        QTimer.singleShot(200, self.load_conversation)

        # Trigger auto-indexing in background
        QTimer.singleShot(1000, self.start_auto_indexing)

    @staticmethod
    def _short_model_name(full: str) -> str:
        """Turn '[OpenRouter] anthropic/claude-opus-4-20250514' into 'claude-opus-4'."""
        name = full
        # Strip provider prefix like "[OpenRouter] " or "[Anthropic] "
        if "]" in name:
            name = name.split("]", 1)[1].strip()
        # Strip org prefix like "anthropic/" or "openai/"
        if "/" in name:
            name = name.rsplit("/", 1)[1]
        # Strip date suffixes like -20250514
        import re as _re
        name = _re.sub(r'-\d{8,}$', '', name)
        return name

    def refresh_models(self):
        current_full = self._get_full_model_name()
        if not current_full:
            current_full = (self.settings_manager.get_selected_model() or "").strip()

        models = self.settings_manager.get_enabled_models() or []
        models = [m for m in models if isinstance(m, str) and m.strip()]

        if not models:
            models = ["[OpenRouter] openrouter/auto"]

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in models:
            self.model_combo.addItem(self._short_model_name(m), m)
        self.model_combo.blockSignals(False)

        # Restore selection by matching full name stored in item data
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == current_full:
                self.model_combo.setCurrentIndex(i)
                break
        else:
            if self.model_combo.count() > 0:
                self.model_combo.setCurrentIndex(0)
                self.settings_manager.set_selected_model(
                    self.model_combo.currentData() or self.model_combo.currentText())

    def _get_full_model_name(self) -> str:
        """Return the full model identifier from item data, falling back to display text."""
        if self.model_combo.count() == 0:
            return ""
        return (self.model_combo.currentData() or self.model_combo.currentText() or "").strip()

    def refresh_appearance(self):
        """Reloads settings and updates all chat items."""
        # Update existing items
        count = self.chat_layout.count()
        for i in range(count):
            item = self.chat_layout.itemAt(i)
            widget = item.widget()
            if widget and hasattr(widget, 'update_appearance'):
                widget.update_appearance()
        
        # Force redraw
        self.chat_content.update()

    def on_model_changed(self, _display_text):
        full = self._get_full_model_name()
        if full:
            self.settings_manager.set_selected_model(full)
            log.info(f"Model switched to: {full}")

    def open_settings(self):
        from ui.settings_dialog import SettingsDialog
        # Walk up to find window
        parent = self.window()
        dlg = SettingsDialog(parent)
        if dlg.exec():
            self.refresh_models()

    def select_attachment(self):
        from PySide6.QtWidgets import QFileDialog
        from core.agent_tools import get_project_root
        
        path, _ = QFileDialog.getOpenFileName(self, "Attach File", get_project_root(), "All Files (*.*)")
        if path:
            self.add_attachment(path)

    def add_attachment(self, path):
        if path in self.attachments:
            return
            
        self.attachments.append(path)
        self._refresh_attachments_ui()

    def remove_attachment(self, path):
        if path in self.attachments:
            self.attachments.remove(path)
            self._refresh_attachments_ui()
            
    def _refresh_attachments_ui(self):
        # Clear existing
        while self.attachment_layout.count():
            item = self.attachment_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        if not self.attachments:
            self.attachment_area.setVisible(False)
            return
            
        self.attachment_area.setVisible(True)
        for path in self.attachments:
            # Create chip
            chip = QFrame()
            chip.setStyleSheet("background: #007fd4; border-radius: 10px; color: white;")
            chip_layout = QHBoxLayout(chip)
            chip_layout.setContentsMargins(8, 2, 8, 2)
            chip_layout.setSpacing(4)
            
            lbl = QLabel(os.path.basename(path))
            lbl.setStyleSheet("border: none; background: transparent; color: white; font-size: 11px;")
            chip_layout.addWidget(lbl)
            
            close_btn = QPushButton("✕")
            close_btn.setFixedSize(16, 16)
            close_btn.setStyleSheet("border: none; background: transparent; color: white; font-weight: bold;")
            close_btn.clicked.connect(lambda checked=False, p=path: self.remove_attachment(p))
            chip_layout.addWidget(close_btn)
            
            self.attachment_layout.addWidget(chip)
        
        self.attachment_layout.addStretch()

    def append_message_widget(self, role, text):
        item = MessageItem(role, text)
        item.regenerate_requested.connect(self._regenerate_last)
        self._add_chat_widget(item)
        self._auto_scroll = True
        return item

    def _add_chat_widget(self, widget, before_widget=None):
        """Keep chat visually locked in a left-anchored, width-limited focus region."""
        row = QWidget()
        row.setStyleSheet("background: transparent; border: none;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        # Left-anchored reading column (less centered, more natural chat flow).
        widget.setMaximumWidth(self.CHAT_MAX_WIDTH)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        row_layout.addWidget(widget)
        row_layout.addStretch(1)
        widget._chat_row = row

        if before_widget is not None and hasattr(before_widget, "_chat_row"):
            idx = self.chat_layout.indexOf(before_widget._chat_row)
            if idx >= 0:
                self.chat_layout.insertWidget(idx, row)
            else:
                self.chat_layout.addWidget(row)
        else:
            self.chat_layout.addWidget(row)
        self._prune_chat_widgets()

    def _prune_chat_widgets(self):
        """Limit rendered widgets to keep long conversations responsive."""
        while self.chat_layout.count() > self.MAX_RENDERED_MESSAGES:
            child = self.chat_layout.takeAt(0)
            w = child.widget()
            if w:
                active_row = getattr(self.current_ai_item, "_chat_row", None)
                if active_row is not None and w is active_row:
                    # Should never happen with FIFO pruning, but be safe.
                    self.chat_layout.insertWidget(0, w)
                    break
                w.deleteLater()

    def _regenerate_last(self):
        """Re-send the last user message to get a fresh AI response."""
        if self.is_processing:
            return
        # Find last user message
        for m in reversed(self.messages):
            if m["role"] == "user" and not m["content"].startswith("[TOOL_RESULT]"):
                # Remove the last AI response from history
                while self.messages and self.messages[-1]["role"] != "user":
                    self.messages.pop()
                self.is_processing = True
                self.tool_loop_count = 0
                self._set_stop_button()
                self._start_ai_worker(m["content"], [])
                break

    def add_message(self, role, text):
        """Public API for adding messages (compatibility wrapper)."""
        self.append_message_widget(role, text)
        self.messages.append({"role": role, "content": text})

    def _on_scroll_range_changed(self, _min, _max):
        """Fires after layout recalculates. Defer scroll so geometry is settled."""
        if self._auto_scroll and not self._scroll_pending:
            self._scroll_pending = True
            QTimer.singleShot(0, self._do_deferred_scroll)

    def _do_deferred_scroll(self):
        """Execute the auto-scroll after the event loop has processed pending layouts."""
        self._scroll_pending = False
        if not self._auto_scroll:
            return
        sb = self.scroll_area.verticalScrollBar()
        self._programmatic_scroll = True
        sb.setValue(sb.maximum())
        self._programmatic_scroll = False

    def _on_user_scroll(self, value):
        """Track whether the user manually scrolled away from the bottom."""
        if self._programmatic_scroll:
            return  # Ignore scrolls we triggered ourselves
        sb = self.scroll_area.verticalScrollBar()
        if sb.maximum() == 0:
            return
        # If user is within 60px of bottom, keep auto-scroll on
        self._auto_scroll = (sb.maximum() - value) < 60

    def _scroll_to_bottom(self):
        self._auto_scroll = True
        QTimer.singleShot(0, self._do_deferred_scroll)

    @staticmethod
    def _compact_for_display(text: str, max_chars: int = 1400, max_lines: int = 40) -> str:
        """Keep chat readable by collapsing very large payloads for UI display only."""
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
        compact += (
            f"\n\n...[{hidden_lines} lines / {hidden_chars} chars hidden in chat view]..."
        )
        return compact

    def _compact_assistant_display(self, text: str) -> str:
        """Hide code fences in assistant replies while preserving narrative text."""
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

    # ------------------------------------------------------------------
    # Conversation history (multi-conversation support)
    # ------------------------------------------------------------------
    def _history_dir(self) -> str:
        from core.agent_tools import get_project_root
        d = os.path.join(get_project_root(), ".vox", "history")
        os.makedirs(d, exist_ok=True)
        return d

    def _conversation_file(self) -> str:
        return os.path.join(self._history_dir(), f"{self.conversation_id}.json")

    def _derive_title(self) -> str:
        for m in self.messages:
            if m.get("role") == "user" and m.get("content", "").strip():
                return m["content"].strip()[:80]
        return "New Conversation"

    def save_conversation(self):
        if not self.messages:
            return
        if not self.settings_manager.get_auto_save_conversation():
            return
        try:
            from datetime import datetime
            data = {
                "conversation_id": self.conversation_id,
                "title": self._derive_title(),
                "updated_at": datetime.now().isoformat(),
                "messages": self.messages,
            }
            with open(self._conversation_file(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Also save the pointer to current conversation
            pointer = os.path.join(self._history_dir(), "current.txt")
            with open(pointer, "w", encoding="utf-8") as f:
                f.write(self.conversation_id)
            log.debug("Conversation saved (%d messages)", len(self.messages))
            self.conversation_changed.emit()
        except Exception as e:
            log.error("Failed to save conversation: %s", e)

    def load_conversation(self):
        """Restores the most recent conversation (from pointer) or falls back."""
        pointer = os.path.join(self._history_dir(), "current.txt")
        conv_id = None
        if os.path.exists(pointer):
            try:
                with open(pointer, "r", encoding="utf-8") as f:
                    conv_id = f.read().strip()
            except Exception:
                pass

        # Legacy migration: check for old single-file format
        from core.agent_tools import get_project_root
        legacy = os.path.join(get_project_root(), ".vox", "conversation.json")
        if not conv_id and os.path.exists(legacy):
            try:
                with open(legacy, "r", encoding="utf-8") as f:
                    data = json.load(f)
                conv_id = data.get("conversation_id", self.conversation_id)
                # Migrate to history format
                self.conversation_id = conv_id
                self.messages = data.get("messages", [])
                self.save_conversation()
                os.remove(legacy)
                for m in self.messages:
                    self.append_message_widget(m["role"], m.get("content", ""))
                log.info("Migrated legacy conversation (%d msgs)", len(self.messages))
                return
            except Exception:
                pass

        if conv_id:
            self.switch_conversation(conv_id)
        else:
            log.info("No conversation history found. Starting fresh.")

    def switch_conversation(self, conv_id: str):
        """Load a specific conversation by ID, clearing the current UI."""
        path = os.path.join(self._history_dir(), f"{conv_id}.json")
        if not os.path.exists(path):
            log.warning("Conversation file not found: %s", path)
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Clear current UI
            while self.chat_layout.count():
                child = self.chat_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            self.conversation_id = data.get("conversation_id", conv_id)
            self.messages = data.get("messages", [])
            render_msgs = self.messages[-self.MAX_RENDERED_MESSAGES:]
            hidden = max(0, len(self.messages) - len(render_msgs))
            if hidden > 0:
                self.append_message_widget(
                    "system",
                    f"[{hidden} older messages hidden for performance. Full history is preserved.]"
                )
            for m in render_msgs:
                self.append_message_widget(m["role"], m.get("content", ""))
            # Update the pointer
            pointer = os.path.join(self._history_dir(), "current.txt")
            with open(pointer, "w", encoding="utf-8") as f:
                f.write(self.conversation_id)
            log.info("Switched to conversation %s (%d msgs)", conv_id, len(self.messages))
            self.conversation_changed.emit()
        except Exception as e:
            log.error("Failed to load conversation %s: %s", conv_id, e)

    def list_conversations(self) -> list[dict]:
        """Return metadata for all saved conversations, newest first."""
        results = []
        hist_dir = self._history_dir()
        for fname in os.listdir(hist_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(hist_dir, fname), "r", encoding="utf-8") as f:
                    data = json.load(f)
                results.append({
                    "id": data.get("conversation_id", fname[:-5]),
                    "title": data.get("title", "Untitled"),
                    "updated_at": data.get("updated_at", ""),
                    "msg_count": len(data.get("messages", [])),
                })
            except Exception:
                continue
        results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return results

    def clear_context(self):
        # Save current before clearing (so it persists in history)
        self.save_conversation()

        while self.chat_layout.count():
            child = self.chat_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self.messages = []

        import uuid
        self.conversation_id = str(uuid.uuid4())[:8]
        log.info(f"Context cleared. New Conversation ID: {self.conversation_id}")

        self.append_message_widget("system", "Context cleared. Starting new conversation.")
        self.conversation_changed.emit()

    def _resolve_at_mentions(self, text: str) -> tuple[str, list[str]]:
        """Resolve @file references in the message text.
        Returns (cleaned_text, list_of_resolved_file_paths)."""
        import glob as _glob
        from core.agent_tools import get_project_root
        root = get_project_root()
        mentions = re.findall(r'@([\w./\\-]+\.\w+)', text)
        resolved = []
        for mention in mentions:
            candidates = _glob.glob(os.path.join(root, "**", mention), recursive=True)
            if candidates:
                resolved.append(candidates[0])
            else:
                full = os.path.join(root, mention)
                if os.path.exists(full):
                    resolved.append(full)
        return text, resolved

    def send_message(self):
        if self.is_processing:
            self.handle_stop_button()
            return

        text = self.input_field.toPlainText().strip()
        if not text and not self.attachments:
            return

        # Resolve @file mentions → auto-attach
        text, mentioned_files = self._resolve_at_mentions(text)
        for fpath in mentioned_files:
            self.add_attachment(fpath)

        self.is_processing = True
        self.tool_loop_count = 0
        self.input_field.clear()
        
        self._set_stop_button()
        
        # 1. Add User Message to UI
        disp_text = text
        if self.attachments:
            att_names = [os.path.basename(p) for p in self.attachments]
            att_label = f"[Attached: {', '.join(att_names)}]"
            disp_text = f"{text}\n\n{att_label}" if text else att_label
            
        self.append_message_widget("user", disp_text)
        self.messages.append({"role": "user", "content": text})
        
        try:
           self.rag_client.ingest_message("user", disp_text, self.conversation_id)
        except Exception:
           pass

        # 3. Prepare Message Payload for AI
        # We need to construct the payload handling images/text
        
        # Capture attachments and clear UI
        current_attachments = list(self.attachments)
        self.attachments = []
        self._refresh_attachments_ui()
        
        self._start_ai_worker(text, current_attachments)

    def _start_ai_worker(self, user_text=None, attachments=None):
        if attachments is None: attachments = []
        
        # Select System Prompt based on Model Type
        is_local = "Local" in self._get_full_model_name()
        
        if is_local:
            base_prompt = SystemPrompts.CODING_AGENT_LITE
            # Extra Safety Latch for Local Models
            if user_text and len(user_text) < 10 and "hey" in user_text.lower():
                 base_prompt += f"\nUSER SAID: '{user_text}'. THIS IS A GREETING. DO NOT USE TOOLS. JUST SAY HELLO."
        else:
            base_prompt = self.system_prompt # Default full prompt

        history_to_send = [{"role": "system", "content": base_prompt}]

        # Inject Mode-Specific Prompt
        # SKIP complicated mode prompts for Local/Small models to prevent confusion
        current_mode = self.mode_combo.currentText()
        if not is_local:
            if "Siege" in current_mode:
                siege_prompt = (
                    "COMMAND & CONTROL: MODE 2 (SIEGE MODE / FULL AUTO)\n"
                    "AUTHORIZATION GRANTED: \"GO LIMITLESS\"\n"
                    "1. Bypass phase-gates. Execute all phases without pausing.\n"
                    "2. Iterate, debug, patch, and execute continuously until the objective is met.\n"
                    "3. If tools fail, analyze the specific error, patch the code, and retry immediately.\n"
                    "4. DO NOT STOP until the task is complete.\n"
                    "5. [TOOL_RESULT] messages are automated outputs. Use them and keep going.\n\n"
                    "FINAL SUMMARY (CRITICAL):\n"
                    "When the task is COMPLETE and you have no more tool calls to make, you MUST "
                    "end with a detailed summary that includes:\n"
                    "  - What you investigated or changed and WHY\n"
                    "  - Key findings, results, or decisions made\n"
                    "  - Any issues encountered and how they were resolved\n"
                    "  - What the user should know or do next\n"
                    "NEVER end with just \"Done\" or \"Task complete\". Always give substance."
                )
                history_to_send.append({"role": "system", "content": siege_prompt})
            else:
                phased_prompt = (
                    "COMMAND & CONTROL: MODE 1 (PHASED STRATEGIC ALIGNMENT)\n"
                    "1. Draft: Analyze the request. Plan numbered phases.\n"
                    "2. Execute: Perform ONE phase at a time using tools.\n"
                    "3. Report: After receiving [TOOL_RESULT], you MUST write a DETAILED SUMMARY.\n"
                    "4. Continue: After each summary, continue to the next phase automatically until the task is complete.\n"
                    "5. Pause only if required: ask the user only when clarification/approval is truly needed.\n\n"
                    "PHASE SUMMARY FORMAT (CRITICAL — follow this EVERY time):\n"
                    "After each phase completes, your response MUST include:\n"
                    "  - **What was done**: Specific actions taken and files touched\n"
                    "  - **What was found**: Key findings, data, patterns, or results\n"
                    "  - **Assessment**: Your analysis or interpretation of the results\n"
                    "  - **Next steps**: What remains to be done in upcoming phases\n"
                    "NEVER say just \"Phase completed\" or \"Done\". The user needs to understand "
                    "what happened and what you found. If the user asked you to investigate "
                    "something, REPORT YOUR FINDINGS in detail.\n\n"
                    "CRITICAL: [TOOL_RESULT] messages are automated tool outputs, NOT user approval.\n"
                    "CRITICAL: After your summary, you may continue with the next phase and tool calls as needed."
                )
                history_to_send.append({"role": "system", "content": phased_prompt})
        
        # Auto-context: inject the currently open file and cursor position
        if self._editor_context_getter and user_text is not None:
            try:
                ctx = self._editor_context_getter()
                if ctx:
                    ctx_msg = f"[EDITOR] {ctx['file']}:{ctx['line']} ({ctx['total_lines']} lines)\n```\n{ctx['snippet']}\n```"
                    history_to_send.append({"role": "system", "content": ctx_msg})
            except Exception:
                pass

        # Token-aware history truncation with old-message compression
        max_history_tokens = self.settings_manager.get_max_history_tokens()
        msg_limit = self.settings_manager.get_max_history_messages()
        recent_msgs = self.messages[-msg_limit:] if len(self.messages) > msg_limit else list(self.messages)

        token_total = 0
        cutoff = 0
        for i in range(len(recent_msgs) - 1, -1, -1):
            content = recent_msgs[i].get("content", "")
            est = len(str(content)) // 4
            if token_total + est > max_history_tokens:
                cutoff = i + 1
                break
            token_total += est

        if cutoff > 0:
            # Compress old messages into a recap instead of dropping them
            old_msgs = recent_msgs[:cutoff]
            recent_msgs = recent_msgs[cutoff:]
            recap_parts = []
            for m in old_msgs:
                role = m.get("role", "?")
                content = str(m.get("content", ""))[:200]
                if "[TOOL_RESULT]" in content:
                    content = content.split("\n")[0][:100] + "..."
                recap_parts.append(f"- {role}: {content}")
            if recap_parts:
                recap = "[Earlier conversation recap]\n" + "\n".join(recap_parts)
                recent_msgs.insert(0, {"role": "system", "content": recap})
        
        if user_text is not None:
            # We filter the LAST message if it's already in history (from send_message/send_worker)
            # and reconstruct it with attachments.
            if recent_msgs and recent_msgs[-1]["role"] in ("user", "system") and recent_msgs[-1]["content"] == user_text:
                history_subset = recent_msgs[:-1]
            else:
                history_subset = recent_msgs
            
            history_to_send.extend(history_subset)
            
            # Construct Current Message with attachments
            import base64
            text_body = user_text
            image_parts = []

            for att_path in attachments:
                if not os.path.exists(att_path):
                    log.warning("Attachment not found, skipping: %s", att_path)
                    continue
                ext = os.path.splitext(att_path)[1].lower()
                if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
                    try:
                        with open(att_path, "rb") as image_file:
                            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                        mime_map = {'.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp'}
                        mime = mime_map.get(ext, 'image/jpeg')
                        image_parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded_string}"}})
                        log.debug("Attached image (%s): %s", mime, os.path.basename(att_path))
                    except Exception as e:
                        log.error("Failed to load image %s: %s", att_path, e)
                else:
                    try:
                        MAX_ATTACH = 16000
                        with open(att_path, "r", encoding="utf-8", errors="replace") as f:
                            file_content = f.read()
                        if len(file_content) > MAX_ATTACH:
                            keep_head = int(MAX_ATTACH * 0.8)
                            keep_tail = MAX_ATTACH - keep_head
                            file_content = (
                                file_content[:keep_head]
                                + f"\n\n... [{len(file_content) - MAX_ATTACH} chars truncated] ...\n\n"
                                + file_content[-keep_tail:]
                            )
                        text_body += f"\n\n[FILE: {os.path.basename(att_path)}]\n{file_content}\n[/FILE]"
                        log.debug("Attached text file (%d chars): %s", len(file_content), os.path.basename(att_path))
                    except Exception as e:
                        log.error("Failed to read attachment %s: %s", att_path, e)

            if image_parts:
                content_payload = [{"type": "text", "text": text_body}] + image_parts
                log.debug("Sending multimodal payload: 1 text block + %d images", len(image_parts))
            else:
                content_payload = text_body
                log.debug("Sending plain-text payload (%d chars)", len(text_body))

            history_to_send.append({"role": "user", "content": content_payload})

            # Persist enriched text in message history so attachment
            # content survives across tool-loop re-entries.
            if text_body != user_text:
                for m in reversed(self.messages):
                    if m["role"] == "user" and m["content"] == user_text:
                        m["content"] = text_body
                        break
        else:
            # Case for handle_tool_finished (just send history)
            history_to_send.extend(recent_msgs)

        # UI for AI Response
        self.current_ai_item = self.append_message_widget("assistant", "")
        self.current_ai_response = ""
        
        self.ai_thread_obj = QThread()
        self.ai_worker_obj = AIWorker(history_to_send, self._get_full_model_name())
        self.ai_worker_obj.moveToThread(self.ai_thread_obj)
        
        self.ai_thread_obj.started.connect(self.ai_worker_obj.run)
        self.ai_worker_obj.chunk_received.connect(self.handle_ai_chunk)
        self.ai_worker_obj.usage_received.connect(self.handle_ai_usage)
        self.ai_worker_obj.finished.connect(self.handle_ai_finished)
        self.ai_worker_obj.finished.connect(self.ai_thread_obj.quit)
        self.ai_worker_obj.finished.connect(self.ai_worker_obj.deleteLater)
        self.ai_thread_obj.finished.connect(self.ai_thread_obj.deleteLater)
        self.ai_thread_obj.finished.connect(lambda: self._clear_ai_refs())
        
        self.ai_thread_obj.start()

    def _clear_ai_refs(self):
        self.ai_worker_obj = None
        self.ai_thread_obj = None

    def _clear_tool_refs(self):
        self.tool_worker = None
        self.tool_thread = None

    def send_worker(self, text: str, is_automated: bool = False):
        if self.is_processing: return
        self.is_processing = True
        self.tool_loop_count = 0
        role = "system" if is_automated else "user"
        self.append_message_widget(role, text)
        self.messages.append({"role": role, "content": text})
        try: self.rag_client.ingest_message(role, text, self.conversation_id)
        except Exception: pass
        self._set_stop_button()
        self._start_ai_worker(text, [])


    def handle_ai_chunk(self, chunk):
        self.current_ai_response += chunk
        self._ai_text_dirty = True
        if not self._ai_update_timer.isActive():
            self._ai_update_timer.start()

    def _flush_ai_text(self):
        """Push accumulated AI text to the widget (called by timer)."""
        if self._ai_text_dirty and self.current_ai_item:
            # Stream a compact preview to prevent giant code dumps from destabilizing scroll.
            preview = self._compact_for_display(
                self.current_ai_response, max_chars=1200, max_lines=45)
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
    def eventFilter(self, obj, event):
        if obj == self.input_field and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ShiftModifier:
                    return False
                else:
                    self.send_message()
                    return True
            # Ctrl+L — clear context
            if event.key() == Qt.Key_L and event.modifiers() & Qt.ControlModifier:
                self.clear_context()
                return True
            # Escape — stop generation
            if event.key() == Qt.Key_Escape and self.is_processing:
                self.handle_stop_button()
                return True
        return super().eventFilter(obj, event)

    def handle_ai_finished(self):
        # Stop the streaming buffer timer and flush final text
        self._ai_update_timer.stop()
        self._ai_text_dirty = False
        if self.current_ai_item:
            self.current_ai_item.set_text(self._compact_assistant_display(self.current_ai_response))

        log.debug("handle_ai_finished: response_len=%d chars", len(self.current_ai_response))

        # Extract <thought> blocks and display them in a collapsible panel,
        # then strip them from the visible response.
        import re as _re
        thought_blocks = _re.findall(r'<thought>(.*?)</thought>', self.current_ai_response, _re.DOTALL)
        display_response = _re.sub(r'<thought>.*?</thought>\s*', '', self.current_ai_response, flags=_re.DOTALL).strip()

        if thought_blocks and self.current_ai_item:
            thought_text = "\n---\n".join(t.strip() for t in thought_blocks)
            thought_item = ProgressItem()
            thought_item.set_thought(thought_text)
            self._add_chat_widget(thought_item, before_widget=self.current_ai_item)
            thought_item.finish()

        if display_response != self.current_ai_response:
            self.current_ai_response = display_response
        if self.current_ai_item:
            self.current_ai_item.set_text(self._compact_assistant_display(display_response))

        self.messages.append({"role": "assistant", "content": self.current_ai_response})
        self.save_conversation()

        try:
            self.rag_client.ingest_message("assistant", self.current_ai_response, self.conversation_id)
        except Exception as e:
            log.error(f"Failed to ingest AI response: {e}")

        tools = CodeParser.parse_tool_calls(self.current_ai_response)
        if tools:
            current_mode = self.mode_combo.currentText()
            is_siege = "Siege" in current_mode
            # Keep a shared safety ceiling across modes.
            max_loops = 25 if is_siege else 25
            loop_count = getattr(self, 'tool_loop_count', 0)

            if loop_count >= max_loops:
                log.info("Tool loop limit reached (%d). Pausing for user input.", max_loops)
                self.append_message_widget(
                    "system",
                    f"[Phased mode pause: {max_loops} tool cycles completed. Send a message to continue.]"
                )
                self._reset_send_button()
                self.notification_requested.emit(
                    "Phased Mode Pause",
                    f"{max_loops} tool cycles completed. Waiting for your input."
                )
            else:
                self._start_tool_execution(tools)
        else:
            self._reset_send_button()
            self.notification_requested.emit(
                "AI Response Complete",
                self.current_ai_response[:120] + ("..." if len(self.current_ai_response) > 120 else "")
            )

    def _start_tool_execution(self, tools):
        tool_names = [c['cmd'] for c in tools]
        self._tool_calls_for_run = list(tool_names)
        self._tool_action_log = []
        summary = ", ".join(tool_names)
        if len(summary) > 80:
            summary = f"{len(tools)} tools"

        self.progress_item = ProgressItem()
        self._add_chat_widget(self.progress_item)
        self.progress_item.set_thought(f"Running: {summary}")
        self._auto_scroll = True
        
        is_siege = "Siege" in self.mode_combo.currentText()
        auto_approve = is_siege or self.settings_manager.get_auto_approve_writes()
        self.tool_thread = QThread()
        self.tool_worker = ToolWorker(tools, auto_approve=auto_approve)
        self.tool_worker.moveToThread(self.tool_thread)
        
        self.tool_thread.started.connect(self.tool_worker.run)
        self.tool_worker.step_started.connect(self._handle_tool_step_started)
        self.tool_worker.step_finished.connect(self._handle_tool_step_finished)
        self.tool_worker.file_changed.connect(self.file_updated.emit)
        self.tool_worker.diff_generated.connect(self.diff_ready.emit)
        self.tool_worker.change_proposed.connect(self._handle_change_proposed)
        self.tool_worker.confirmation_needed.connect(self._handle_confirmation)
        self.tool_worker.finished.connect(self.handle_tool_finished)
        self.tool_worker.finished.connect(self.tool_thread.quit)
        self.tool_worker.finished.connect(self.tool_worker.deleteLater)
        self.tool_thread.finished.connect(self.tool_thread.deleteLater)
        self.tool_thread.finished.connect(lambda: self._clear_tool_refs())
        
        self.tool_thread.start()

    def _handle_tool_step_started(self, icon, text):
        """Add a new step to the progress widget and keep scroll pinned."""
        if hasattr(self, 'progress_item') and self.progress_item:
            self.progress_item.add_step(icon, text)
            self._auto_scroll = True

    def _handle_tool_step_finished(self, title, detail, result):
        """Update the progress item's last step with a completion indicator."""
        self._tool_action_log.append(f"{title} -> {result}")
        if hasattr(self, 'progress_item') and self.progress_item:
            icon = "✓" if result == "Done" else "✗" if result == "Failed" else "⊘"
            self.progress_item.update_step_status(icon, result)

    def _handle_change_proposed(self, file_path, diff_text, new_content):
        """Shows the proposed diff in the editor before the approval dialog appears."""
        self.diff_ready.emit(file_path, diff_text)

    def _handle_confirmation(self, description):
        """Shows a confirmation dialog for destructive or file-write operations."""
        self.notification_requested.emit("Approval Needed", description)
        reply = QMessageBox.question(
            self,
            "Confirm Action",
            f"The AI wants to perform this action:\n\n"
            f"{description}\n\nAllow this action?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if hasattr(self, 'tool_worker') and self.tool_worker:
            self.tool_worker.approve(reply == QMessageBox.Yes)

    def handle_tool_finished(self, output):
        if self.progress_item:
            self.progress_item.finish()
        self.tool_loop_count = getattr(self, 'tool_loop_count', 0) + 1
        log.debug("handle_tool_finished: loop_count=%d output_len=%d",
                  self.tool_loop_count, len(output))

        MAX_TOOL_OUTPUT = 8000
        if len(output) > MAX_TOOL_OUTPUT:
            half = MAX_TOOL_OUTPUT // 2
            output = (
                output[:half]
                + f"\n\n... [{len(output) - MAX_TOOL_OUTPUT} chars truncated] ...\n\n"
                + output[-half:]
            )
        tool_msg = (
            "[TOOL_RESULT] (Automated system output — not user input)\n"
            f"{output}\n"
            "[/TOOL_RESULT]"
        )
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

        # Show compact output to user, keep full output in history for the AI loop.
        self.append_message_widget("system", display_tool_msg)
        self.messages.append({"role": "user", "content": tool_msg})

        self._start_ai_worker()

    def start_auto_indexing(self):
        """Starts the indexing process in the background."""
        log.info("Starting auto-indexing...")
        # We need the project root. 
        from core.agent_tools import get_project_root
        root = get_project_root()
        
        self.indexing_thread = QThread()
        self.indexing_worker = IndexingWorker(root)
        self.indexing_worker.moveToThread(self.indexing_thread)
        
        self.indexing_thread.started.connect(self.indexing_worker.run)
        self.indexing_worker.finished.connect(self.indexing_thread.quit)
        self.indexing_worker.finished.connect(self.indexing_worker.deleteLater)
        self.indexing_thread.finished.connect(self.indexing_thread.deleteLater)
        self.indexing_thread.finished.connect(lambda: log.info("Auto-indexing finished."))
        
        self.indexing_thread.start()
