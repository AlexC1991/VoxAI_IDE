
# -*- coding: utf-8 -*-
import os
import sys
import re
import logging
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, 
    QTextEdit, QPushButton, QFrame, QLabel, QMessageBox,
    QComboBox
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

    def run(self):
        log.info("AIWorker starting | model=%s", self.model)

        from core.agent_tools import get_project_root
        project_root = get_project_root()
        cwd = project_root.replace("\\", "/")

        try:
            files = []
            for root, dirs, filenames in os.walk(project_root):
                if ".git" in dirs: dirs.remove(".git")
                if "__pycache__" in dirs: dirs.remove("__pycache__")
                if "node_modules" in dirs: dirs.remove("node_modules")
                for f in filenames:
                    rel_path = os.path.relpath(os.path.join(root, f), project_root)
                    files.append(rel_path)

            stop_idx = self.settings.get_max_file_list()
            file_list_str = "\n".join(files[:stop_idx])
            if len(files) > stop_idx:
                file_list_str += f"\n...({len(files)-stop_idx} more files)..."
            structure_msg = f"Current Project Structure at {cwd}:\n{file_list_str}\n\nAlways use <list_files /> for full project details."
        except Exception as e:
            log.error("Structure injection error: %s", e)
            structure_msg = f"Working in: {cwd}"

        final_messages = []
        final_messages.append({"role": "system", "content": f"CRITICAL CONTEXT: {structure_msg}"})

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
        
        # 1. Toolbar (Clear Context)
        self.top_bar = QFrame()
        self.top_bar.setStyleSheet("background: #18181b; border-bottom: 1px solid #27272a;")
        self.top_bar_layout = QHBoxLayout(self.top_bar)
        self.top_bar_layout.setContentsMargins(10, 5, 10, 5)
        
        self.clear_btn = QPushButton("Clear Context")
        self.clear_btn.clicked.connect(self.clear_context)
        # Fix: ensure stop logic is wired
        self.ai_thread = None 
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background: #27272a; color: #a1a1aa; border: 1px solid #3f3f46; 
                padding: 4px 12px; border-radius: 4px; font-size: 11px;
                font-family: 'Consolas', monospace;
            }
            QPushButton:hover { 
                background: #3f3f46; 
                color: #ff9900; /* Neon Orange hover */
                border-color: #ff9900;
            }
        """)
        self.top_bar_layout.addWidget(self.clear_btn)
        
        self.top_bar_layout.addStretch()
        
        # Model Selector
        self.model_combo = QComboBox()
        self.model_combo.setFixedWidth(200)
        self.model_combo.setStyleSheet("""
            QComboBox {
                background: #27272a; color: #00f3ff; border: 1px solid #3f3f46; 
                padding: 4px 12px; border-radius: 4px;
                font-family: 'Consolas', monospace; font-size: 11px;
            }
            QComboBox:hover { border-color: #00f3ff; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #18181b;
                color: #e4e4e7;
                selection-background-color: #27272a;
                selection-color: #00f3ff;
                border: 1px solid #3f3f46;
                outline: none;
            }
            QComboBox::down-arrow { image: none; border: none; } 
        """)
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        self.top_bar_layout.addWidget(self.model_combo)

        # Mode Selector (Command & Control)
        self.mode_combo = QComboBox()
        self.mode_combo.setFixedWidth(180)
        self.mode_combo.setStyleSheet("""
            QComboBox {
                background: #27272a; color: #ff9900; border: 1px solid #3f3f46; 
                padding: 4px 12px; border-radius: 4px;
                font-family: 'Consolas', monospace; font-size: 11px; font-weight: bold;
            }
            QComboBox:hover { border-color: #ff9900; }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #18181b;
                color: #e4e4e7;
                selection-background-color: #27272a;
                selection-color: #ff9900;
                border: 1px solid #3f3f46;
                outline: none;
            }
        """)
        self.mode_combo.addItems(["🛑 Phased (Default)", "🔥 Siege Mode"])
        self.top_bar_layout.addWidget(self.mode_combo)

        # self.settings_btn = QPushButton("⚙️") ...
        
        self.layout.addWidget(self.top_bar)
        
        # Refresh models init
        self.refresh_models()

        # 2. Chat Area (Scroll) - THE LAYERED STACK
        # Layer 1 & 2: Container with Background
        bg_path = get_resource_path(os.path.join("resources", "Chat_Background_Image.png"))
        self.chat_container = WatermarkContainer(logo_path=bg_path)
        
        # Layer 3: The Scroll Area (Transparent)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAttribute(Qt.WA_TranslucentBackground)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        self.scroll_area.viewport().setStyleSheet("background: transparent; border: none;")
        
        # Content Widget (Transparent)
        self.chat_content = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_content)
        self.chat_layout.setAlignment(Qt.AlignTop) 
        self.chat_layout.setContentsMargins(10, 10, 10, 10)
        self.chat_layout.setSpacing(10)
        self.chat_content.setStyleSheet("background: transparent; border: none;")
        self.chat_content.setAttribute(Qt.WA_TranslucentBackground)
        
        self.scroll_area.setWidget(self.chat_content)

        # Reliable auto-scroll: fires AFTER the layout recalculates sizes
        self.scroll_area.verticalScrollBar().rangeChanged.connect(
            self._on_scroll_range_changed)
        self.scroll_area.verticalScrollBar().valueChanged.connect(
            self._on_user_scroll)
        
        # Add ScrollArea to the Background Container
        self.chat_container.layout.addWidget(self.scroll_area)
        
        # Add the entire wrapped container to main layout
        self.layout.addWidget(self.chat_container, 1)
        
        # 3. Input Area
        self.input_wrapper = QWidget()
        self.input_wrapper.setStyleSheet("background: #18181b; border-top: 1px solid #27272a;")
        self.input_wrapper_layout = QVBoxLayout(self.input_wrapper)
        self.input_wrapper_layout.setContentsMargins(10, 10, 10, 10)
        self.input_wrapper_layout.setSpacing(0)
        
        # Attachment Preview Area
        self.attachment_area = QFrame()
        self.attachment_area.setVisible(False)
        self.attachment_area.setStyleSheet("background: #18181b; border: none; padding-bottom: 5px;")
        self.attachment_layout = QHBoxLayout(self.attachment_area)
        self.attachment_layout.setAlignment(Qt.AlignLeft)
        self.attachment_layout.setContentsMargins(0, 0, 0, 0)
        self.input_wrapper_layout.addWidget(self.attachment_area)

        self.input_container = QFrame()
        self.input_container.setStyleSheet("""
            QFrame {
                background: #27272a; border: 1px solid #3f3f46; border-radius: 6px;
            }
        """)
        self.input_layout = QHBoxLayout(self.input_container)
        self.input_layout.setContentsMargins(5, 5, 5, 5)
        
        # Attachment Button
        self.attach_btn = QPushButton("📎")
        self.attach_btn.setFixedWidth(30)
        self.attach_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #a1a1aa; border: none; font-size: 16px; }
            QPushButton:hover { color: #e4e4e7; }
        """)
        self.attach_btn.clicked.connect(self.select_attachment)
        self.input_layout.addWidget(self.attach_btn)

        self.input_field = QTextEdit()
        self.input_field.setPlaceholderText("Type a message... (@file to attach context, Enter to send)")
        self.input_field.setStyleSheet("""
            QTextEdit {
                background: #18181b; color: #e4e4e7; border: 1px solid #3f3f46; 
                border-radius: 6px; padding: 10px; font-size: 13px;
                font-family: 'Consolas', monospace;
            }
            QTextEdit:focus { border-color: #ff9900; }
        """)
        self.input_field.setFixedHeight(50)
        self.input_layout.addWidget(self.input_field)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.send_message)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: #00f3ff; 
                color: #18181b;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 8px 16px;
                font-family: 'Consolas', monospace;
            }
            QPushButton:hover { background: #33f7ff; }
            QPushButton:pressed { background: #00c2cc; }
            QPushButton:disabled { background: #3f3f46; color: #71717a; }
        """)
        self.input_layout.addWidget(self.send_btn)
        
        self.input_wrapper_layout.addWidget(self.input_container)
        self.layout.addWidget(self.input_wrapper)
        
        # Re-install event filter on logic init
        self.input_field.installEventFilter(self)
        
        # State
        self.attachments = [] # List of paths

        # State
        self.messages = [] # List of {"role":Str, "content":Str}
        self.is_processing = False
        self._auto_scroll = True
        
        # Threads
        self.ai_thread = None
        self.ai_worker = None
        self.tool_thread = None
        self.tool_worker = None

        # Load system prompt
        from core.prompts import SystemPrompts
        self.system_prompt = SystemPrompts.CODING_AGENT

        # Restore previous conversation if available
        QTimer.singleShot(200, self.load_conversation)

        # Trigger auto-indexing in background
        QTimer.singleShot(1000, self.start_auto_indexing)

    def refresh_models(self):
        current = (self.model_combo.currentText().strip() if self.model_combo.count() else "")
        if not current:
            current = (self.settings_manager.get_selected_model() or "").strip()

        models = self.settings_manager.get_enabled_models() or []
        models = [m for m in models if isinstance(m, str) and m.strip()]

        if not models:
            models = ["[OpenRouter] openrouter/auto"]

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in models:
            self.model_combo.addItem(m)
        self.model_combo.blockSignals(False)

        idx = self.model_combo.findText(current)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        else:
            if self.model_combo.count() > 0:
                self.model_combo.setCurrentIndex(0)
                self.settings_manager.set_selected_model(self.model_combo.currentText())

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

    def on_model_changed(self, text):
        if text and text.strip():
            self.settings_manager.set_selected_model(text.strip())
            log.info(f"Model switched to: {text.strip()}")

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
        self.chat_layout.addWidget(item)
        self._auto_scroll = True
        return item

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
                self.send_btn.setText("Stop")
                self.send_btn.setStyleSheet(
                    "background: #ff9900; color: #18181b; border: none; "
                    "border-radius: 4px; font-weight: bold; padding: 8px 16px; "
                    "font-family: 'Consolas', monospace;")
                self._start_ai_worker(m["content"], [])
                break

    def add_message(self, role, text):
        """Public API for adding messages (compatibility wrapper)."""
        self.append_message_widget(role, text)
        self.messages.append({"role": role, "content": text})

    def _on_scroll_range_changed(self, _min, _max):
        """Fires after layout recalculates. Scroll to bottom if user hasn't scrolled away."""
        if self._auto_scroll:
            self.scroll_area.verticalScrollBar().setValue(_max)

    def _on_user_scroll(self, value):
        """Track whether the user manually scrolled away from the bottom."""
        sb = self.scroll_area.verticalScrollBar()
        if sb.maximum() == 0:
            return
        # If user is within 60px of bottom, keep auto-scroll on
        self._auto_scroll = (sb.maximum() - value) < 60

    def _scroll_to_bottom(self):
        self._auto_scroll = True
        sb = self.scroll_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _conversation_file(self) -> str:
        """Path to the auto-save file for the current project."""
        from core.agent_tools import get_project_root
        vox_dir = os.path.join(get_project_root(), ".vox")
        os.makedirs(vox_dir, exist_ok=True)
        return os.path.join(vox_dir, "conversation.json")

    def save_conversation(self):
        """Persists the current messages to disk."""
        if not self.messages:
            return
        if not self.settings_manager.get_auto_save_conversation():
            return
        try:
            import json
            data = {
                "conversation_id": self.conversation_id,
                "messages": self.messages,
            }
            with open(self._conversation_file(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            log.debug("Conversation saved (%d messages)", len(self.messages))
        except Exception as e:
            log.error("Failed to save conversation: %s", e)

    def load_conversation(self):
        """Restores messages from disk and replays them into the UI."""
        path = self._conversation_file()
        if not os.path.exists(path):
            return
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            msgs = data.get("messages", [])
            if not msgs:
                return
            self.conversation_id = data.get("conversation_id", self.conversation_id)
            self.messages = msgs
            for m in msgs:
                self.append_message_widget(m["role"], m.get("content", ""))
            log.info("Restored %d messages from previous session", len(msgs))
        except Exception as e:
            log.error("Failed to load conversation: %s", e)

    def clear_context(self):
        while self.chat_layout.count():
            child = self.chat_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self.messages = []

        import uuid
        self.conversation_id = str(uuid.uuid4())[:8]
        log.info(f"Context cleared. New Conversation ID: {self.conversation_id}")

        # Remove saved conversation file
        try:
            path = self._conversation_file()
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

        self.append_message_widget("system", "Context cleared. Starting new conversation.")

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
        
        # Update button to STOP state (Neon Orange)
        self.send_btn.setText("Stop")
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: #ff9900; 
                color: #18181b;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 8px 16px;
                font-family: 'Consolas', monospace;
            }
            QPushButton:hover { background: #ffaa33; }
        """)
        
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
        is_local = "Local" in self.model_combo.currentText()
        
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
            if "Siege Mode" in current_mode:
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
                    "4. STOP: After the summary, STOP and wait for user to authorize the next phase.\n\n"
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
                    "CRITICAL: After your summary, return TEXT ONLY. Do NOT emit more tool calls."
                )
                history_to_send.append({"role": "system", "content": phased_prompt})
        
        # Token-aware history truncation: keep as many recent messages as
        # fit within ~75% of the typical context window, leaving room for
        # system prompts, attachments, and the AI's response.
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
            recent_msgs = recent_msgs[cutoff:]
        
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
                        with open(att_path, "r", encoding="utf-8", errors="replace") as f:
                            file_content = f.read()
                        text_body += f"\n\n--- Attached File: {os.path.basename(att_path)} ---\n{file_content}\n--- End File ---"
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
        self.ai_worker_obj = AIWorker(history_to_send, self.model_combo.currentText())
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
        self.send_btn.setText("Stop")
        self.send_btn.setStyleSheet("background: #ff9900; color: #18181b; border: none; border-radius: 4px; font-weight: bold; padding: 8px 16px; font-family: 'Consolas', monospace;")
        self._start_ai_worker(text, [])


    def handle_ai_chunk(self, chunk):
        self.current_ai_response += chunk
        self.current_ai_item.set_text(self.current_ai_response)

    def handle_ai_usage(self, usage):
        if self.current_ai_item:
            self.current_ai_item.set_usage(usage)
        total = usage.get("total_tokens", 0) if usage else 0
        if total:
            self.token_usage_updated.emit(total)

    def handle_stop_button(self):
        """Interrupts AI and tool workers and resets the button."""
        stopped = False
        if hasattr(self, 'ai_thread_obj') and self.ai_thread_obj and self.ai_thread_obj.isRunning():
            log.info("Stopping AI generation...")
            self.ai_thread_obj.requestInterruption()
            stopped = True
        if hasattr(self, 'tool_thread') and self.tool_thread and self.tool_thread.isRunning():
            log.info("Stopping tool execution...")
            self.tool_thread.requestInterruption()
            stopped = True
        if not stopped:
            self._reset_send_button()

    def _reset_send_button(self):
        """Resets the button to the Send state (Neon Blue)."""
        self.is_processing = False
        self.send_btn.setText("Send")
        self.send_btn.setEnabled(True)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: #00f3ff; 
                color: #18181b;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 8px 16px;
                font-family: 'Consolas', monospace;
            }
            QPushButton:hover { background: #33f7ff; }
            QPushButton:pressed { background: #00c2cc; }
            QPushButton:disabled { background: #3f3f46; color: #71717a; }
        """)
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
        log.debug("handle_ai_finished: response_len=%d chars", len(self.current_ai_response))

        # Extract <thought> blocks and display them in a collapsible panel,
        # then strip them from the visible response.
        import re as _re
        thought_blocks = _re.findall(r'<thought>(.*?)</thought>', self.current_ai_response, _re.DOTALL)
        display_response = _re.sub(r'<thought>.*?</thought>\s*', '', self.current_ai_response, flags=_re.DOTALL).strip()

        if thought_blocks:
            thought_text = "\n---\n".join(t.strip() for t in thought_blocks)
            thought_item = ProgressItem()
            thought_item.set_thought(thought_text)
            idx = self.chat_layout.indexOf(self.current_ai_item)
            if idx >= 0:
                self.chat_layout.insertWidget(idx, thought_item)
            else:
                self.chat_layout.addWidget(thought_item)
            thought_item.finish()

        if display_response != self.current_ai_response:
            self.current_ai_response = display_response
            self.current_ai_item.set_text(display_response)

        self.messages.append({"role": "assistant", "content": self.current_ai_response})
        self.save_conversation()

        try:
            self.rag_client.ingest_message("assistant", self.current_ai_response, self.conversation_id)
        except Exception as e:
            log.error(f"Failed to ingest AI response: {e}")

        tools = CodeParser.parse_tool_calls(self.current_ai_response)
        if tools:
            current_mode = self.mode_combo.currentText()
            is_siege = "Siege Mode" in current_mode
            max_loops = 25 if is_siege else 3
            loop_count = getattr(self, 'tool_loop_count', 0)

            if loop_count >= max_loops:
                log.info("Tool loop limit reached (%d). Pausing for user input.", max_loops)
                self.append_message_widget(
                    "system",
                    f"[Phase gate: {max_loops} tool cycles completed. Send a message to continue.]"
                )
                self._reset_send_button()
                self.notification_requested.emit(
                    "Phase Gate Reached",
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
        summary = ", ".join(tool_names)
        if len(summary) > 80:
            summary = f"{len(tools)} tools"

        self.progress_item = ProgressItem()
        self.chat_layout.addWidget(self.progress_item)
        self.progress_item.set_thought(f"Running: {summary}")
        self._auto_scroll = True
        
        is_siege = "Siege Mode" in self.mode_combo.currentText()
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
        self.progress_item.finish()
        self.tool_loop_count = getattr(self, 'tool_loop_count', 0) + 1
        log.debug("handle_tool_finished: loop_count=%d output_len=%d",
                  self.tool_loop_count, len(output))

        tool_msg = (
            "[TOOL_RESULT] (Automated system output — not user input)\n"
            f"{output}\n"
            "[/TOOL_RESULT]"
        )

        self.append_message_widget("system", tool_msg)
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
