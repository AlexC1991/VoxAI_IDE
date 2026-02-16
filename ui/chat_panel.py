
# -*- coding: utf-8 -*-
import os
import sys
import re
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, 
    QTextEdit, QPushButton, QFrame, QSizePolicy, QLabel, QMessageBox,
    QComboBox
)
from PySide6.QtCore import Signal, Qt, QThread, QObject, QTimer, QEvent
from PySide6.QtGui import QTextCursor, QFont, QPixmap, QPainter, QColor

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
    usage_received = Signal(dict) # New signal for usage stats
    rag_step_started = Signal(str, str) # icon, text
    rag_step_finished = Signal(str, str, str) # title, detail, result
    finished = Signal()
    
    def __init__(self, message_history, model):
        super().__init__()
        self.message_history = message_history
        self.model = model
        self.client = AIClient()
        self.settings = SettingsManager()
        self.rag = RAGClient()

    def run(self):
        log.debug("AIWorker running with model: %s", self.model)
        
        # 1. RAG Retrieval logic
        rag_context = ""
        if self.settings.get_rag_enabled():
            # Find last user message for query
            query_text = ""
            for msg in reversed(self.message_history):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        # Handle multimodal content - extract text parts
                        query_text = " ".join([c["text"] for c in content if c["type"] == "text"])
                    else:
                        query_text = str(content)
                    break
            
            if query_text.strip():
                log.debug(f"RAG Retrieval for query: {query_text[:50]}...")
                try:
                    chunks = self.rag.retrieve(query_text, k=self.settings.get_rag_top_k())
                    if chunks:
                        rag_context = self.rag.format_context_block(
                            chunks, 
                            max_chars=self.settings.get_rag_max_context(),
                            max_chunk_chars=self.settings.get_rag_max_chunk()
                        )
                        log.info(f"RAG: Retrieved {len(chunks)} chunks.")
                        self.rag_step_finished.emit(f"RAG Retrieved {len(chunks)} chunks", None, "Done")
                    else:
                         log.debug("RAG: No relevant chunks found.")
                except Exception as e:
                    log.error(f"RAG Retrieval failed: {e}")

        # Helper: Inject CWD into system prompt if needed
        from core.agent_tools import get_project_root
        project_root = get_project_root()
        cwd = project_root.replace("\\", "/")
        
        # Dynamic File List for context
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
            if len(files) > stop_idx: file_list_str += f"\n...({len(files)-stop_idx} more files)..."
            structure_msg = f"Current Project Structure at {cwd}:\n{file_list_str}\n\nAlways use <list_files /> for full project details."
        except Exception as e:
            log.error("Structure injection error: %s", e)
            structure_msg = f"Working in: {cwd}"

        final_messages = []
        # 2. Inject Dynamic Project Context
        final_messages.append({"role": "system", "content": f"CRITICAL CONTEXT: {structure_msg}"})
        
        for msg in self.message_history:
            if msg.get("role") == "system":
                content = msg["content"]
                if "{cwd_path}" in content:
                    content = content.replace("{cwd_path}", cwd)
                final_messages.append({"role": "system", "content": content})
            else:
                final_messages.append(msg)
        
        # Inject RAG context as a system message if found
        if rag_context:
            final_messages.insert(1, {"role": "system", "content": rag_context})

        full_response = ""
        try:
            stream = self.client.stream_chat(final_messages)
            for chunk in stream:
                if QThread.currentThread().isInterruptionRequested():
                    log.debug("AIWorker Interrupted!")
                    break
                
                # Handle usage dict if yielded by client
                if isinstance(chunk, dict):
                    if "usage" in chunk:
                        self.usage_received.emit(chunk["usage"])
                    continue
                
                full_response += chunk
                
                # Typing effect: trickle characters out
                for char in chunk:
                    if QThread.currentThread().isInterruptionRequested():
                        break
                    self.chunk_received.emit(char)
                    QThread.msleep(15) # 15ms delay per char for a smooth feel
        except Exception as e:
            log.error("AIWorker run failed: %s", e)
            self.chunk_received.emit(f"\n[Error: {str(e)}]\n")
        
        log.debug("AIWorker finished run.")
        self.finished.emit()


class ToolWorker(QObject):
    """Executes tool calls in a background thread."""
    step_started = Signal(str, str) # icon, text
    step_finished = Signal(str, str, str) # title, detail (if any), result_summary
    file_changed = Signal(str)
    finished = Signal(str) # combined output text

    def __init__(self, tool_calls):
        super().__init__()
        self.tool_calls = tool_calls
        self.rag_client = RAGClient()

    def run(self):
        tool_outputs = []
        
        for call in self.tool_calls:
            if QThread.currentThread().isInterruptionRequested():
                tool_outputs.append("System: [Interrupted] Tool execution stopped by user.")
                break

            cmd = call['cmd']
            args = call['args']
            
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

                    # Diff generation for safety check (optional, but good for logs)
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

                    result = AgentToolHandler.write_file(path, content)
                    tool_outputs.append(f"System: Wrote file '{path}' ({result})")
                    self.file_changed.emit(full_path)
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

            except Exception as e:
                tool_outputs.append(f"System: Error executing {cmd}: {e}")
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
        self.input_field.setPlaceholderText("Type a message... (Enter to send, Shift+Enter for new line)")
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
        
        # Threads
        self.ai_thread = None
        self.ai_worker = None
        self.tool_thread = None
        self.tool_worker = None

        # Load system prompt
        from core.prompts import SystemPrompts
        self.system_prompt = SystemPrompts.CODING_AGENT

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

    def eventFilter(self, obj, event):
        if obj == self.input_field and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Return and (event.modifiers() & Qt.ControlModifier):
                self.send_message()
                return True
        return super().eventFilter(obj, event)

    def append_message_widget(self, role, text):
        item = MessageItem(role, text)
        self.chat_layout.addWidget(item)
        
        # Auto-scroll
        QTimer.singleShot(100, self._scroll_to_bottom)
        return item

    def add_message(self, role, text):
        """Public API for adding messages (compatibility wrapper)."""
        self.append_message_widget(role, text)
        self.messages.append({"role": role, "content": text})

    def _scroll_to_bottom(self):
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_context(self):
        # Clear UI
        while self.chat_layout.count():
            child = self.chat_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        # Reset state
        self.messages = []
        
        # Generate new conversation ID
        import uuid
        self.conversation_id = str(uuid.uuid4())[:8]
        log.info(f"Context cleared. New Conversation ID: {self.conversation_id}")
        
        self.append_message_widget("system", "Context cleared. Starting new conversation.")

    def send_message(self):
        if self.is_processing:
            self.handle_stop_button()
            return

        text = self.input_field.toPlainText().strip()
        if not text:
            return
            
        self.is_processing = True
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
        # If attachments exist, show them in UI too?
        # For now we just show text. Attachments are context.
        disp_text = text
        if self.attachments:
            att_names = [os.path.basename(p) for p in self.attachments]
            disp_text += f"\n\n[Attached: {', '.join(att_names)}]"
            
        self.append_message_widget("user", disp_text)
        self.messages.append({"role": "user", "content": disp_text}) # Log text version
        
        # 2. Ingest into Long-term memory
        try:
           self.rag_client.ingest_message("user", disp_text, self.conversation_id)
        except:
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
                 base_prompt += "\nUSER SAID: '{user_text}'. THIS IS A GREETING. DO NOT USE TOOLS. JUST SAY HELLO."
        else:
            base_prompt = self.system_prompt # Default full prompt

        history_to_send = [{"role": "system", "content": base_prompt}]

        # Inject Mode-Specific Prompt
        # SKIP complicated mode prompts for Local/Small models to prevent confusion
        current_mode = self.mode_combo.currentText()
        if not is_local:
            if "Siege Mode" in current_mode:
                siege_prompt = """
COMMAND & CONTROL: MODE 2 (SIEGE MODE / FULL AUTO)
AUTHORIZATION GRANTED: "GO LIMITLESS"
1. Bypass phase-gates.
2. Iterate, debug, patch, and execute continuously until the objective is met.
3. If tools fail, analyze specific errors, patch the code, and retry immediately.
4. DO NOT STOP until the task is complete.
"""
                history_to_send.append({"role": "system", "content": siege_prompt})
            else:
                phased_prompt = """
COMMAND & CONTROL: MODE 1 (PHASED STRATEGIC ALIGNMENT)
1. Draft: Analyze the request. Plan phases.
2. Authorize: Stop and wait for approval before executing a new phase.
3. Execute: Perform the phase.
CRITICAL: AFTER completing a phase or if you need to plan, STOP generating tool calls. Return text only.
"""
                history_to_send.append({"role": "system", "content": phased_prompt})
        
        limit = self.settings_manager.get_max_history_messages()
        recent_msgs = self.messages[-limit:] if len(self.messages) > limit else self.messages
        
        if user_text:
            # We filter the LAST message if it's already in history (from send_message/send_worker)
            # and reconstruct it with attachments.
            if recent_msgs and recent_msgs[-1]["role"] in ("user", "system") and recent_msgs[-1]["content"] == user_text:
                history_subset = recent_msgs[:-1]
            else:
                history_subset = recent_msgs
            
            history_to_send.extend(history_subset)
            
            # Construct Current Message
            content_payload = []
            content_payload.append({"type": "text", "text": user_text})
            
            import base64
            for path in attachments:
                if not os.path.exists(path): continue
                ext = os.path.splitext(path)[1].lower()
                if ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
                    try:
                        with open(path, "rb") as image_file:
                            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                            mime = "image/jpeg"
                            if ext == '.png': mime = "image/png"
                            elif ext == '.gif': mime = "image/gif"
                            elif ext == '.webp': mime = "image/webp"
                            content_payload.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded_string}"}})
                    except Exception as e:
                        log.error(f"Failed to load image {path}: {e}")
                else:
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            file_content = f.read()
                            content_payload.append({"type": "text", "text": f"\n\n--- Attached File: {os.path.basename(path)} ---\n{file_content}\n--- End File ---\n"})
                    except: pass
            
            history_to_send.append({"role": "user", "content": content_payload})
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
        
        self.ai_thread_obj.start()

    def send_worker(self, text: str, is_automated: bool = False):
        if self.is_processing: return
        self.is_processing = True
        role = "system" if is_automated else "user"
        self.append_message_widget(role, text)
        self.messages.append({"role": role, "content": text})
        try: self.rag_client.ingest_message(role, text, self.conversation_id)
        except: pass
        self.send_btn.setText("Stop")
        self.send_btn.setStyleSheet("background: #ff9900; color: #18181b; border: none; border-radius: 4px; font-weight: bold; padding: 8px 16px; font-family: 'Consolas', monospace;")
        self._start_ai_worker(text, [])


    def handle_ai_chunk(self, chunk):
        self.current_ai_response += chunk
        # Update UI
        # MessageItem takes full text, so we update it
        # We access the internal label directly or via a method?
        # MessageItem has set_text? No, constructor calls internal setup.
        # Use the new set_text method for clean updates
        self.current_ai_item.set_text(self.current_ai_response)
        
        # Auto-scroll
        self._scroll_to_bottom()

    def handle_ai_usage(self, usage):
        # Update usage stats on the message item
        if self.current_ai_item:
            self.current_ai_item.set_usage(usage)

    def handle_stop_button(self):
        """Interrupts the AI worker and resets the button."""
        if hasattr(self, 'ai_thread_obj') and self.ai_thread_obj and self.ai_thread_obj.isRunning():
            log.info("Stopping AI generation...")
            self.ai_thread_obj.requestInterruption()
            # The finished signal will trigger _reset_send_button
        else:
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
                    return False # Allow new line
                else:
                    self.send_message()
                    return True # Consume event
        return super().eventFilter(obj, event)

    def handle_ai_finished(self):
        # 1. Add to history
        self.messages.append({"role": "assistant", "content": self.current_ai_response})
        
        # 2. Ingest AI response into memory
        try:
            self.rag_client.ingest_message("assistant", self.current_ai_response, self.conversation_id)
        except Exception as e:
            log.error(f"Failed to ingest AI response: {e}")
            
        # 3. Check for Tools
        tools = CodeParser.parse_tool_calls(self.current_ai_response)
        if tools:
            self._start_tool_execution(tools)
        else:
            self.is_processing = False
            self.send_btn.setEnabled(True)

    def _start_tool_execution(self, tools):
        # 1. Log visualization
        for tool_name, args in tools:
            # Format description
            desc = f"**{tool_name}**"
            if args:
                # Simple truncation for cleaner UI
                arg_str = str(args)
                if len(arg_str) > 80:
                    arg_str = arg_str[:80] + "..."
                desc += f" `({arg_str})`"
            
            self.append_message_widget("tool", desc)

        # Add a progress item
        self.progress_item = ProgressItem()
        self.chat_layout.addWidget(self.progress_item)
        self.progress_item.set_thought("Executing tools...")
        self._scroll_to_bottom()
        
        self.tool_thread = QThread()
        self.tool_worker = ToolWorker(tools)
        self.tool_worker.moveToThread(self.tool_thread)
        
        self.tool_thread.started.connect(self.tool_worker.run)
        self.tool_worker.step_started.connect(self.progress_item.add_step)
        self.tool_worker.step_finished.connect(self._handle_tool_step_finished)
        self.tool_worker.file_changed.connect(self.file_updated.emit) # Signal file update to main window
        self.tool_worker.finished.connect(self.handle_tool_finished)
        self.tool_worker.finished.connect(self.tool_thread.quit)
        self.tool_worker.finished.connect(self.tool_worker.deleteLater)
        self.tool_thread.finished.connect(self.tool_thread.deleteLater)
        
        self.tool_thread.start()

    def _handle_tool_step_finished(self, title, detail, result):
        # Update progress item step?
        # ProgressItem.add_step adds a line.
        # We might want to update the last line status?
        # The signals from ToolWorker are: step_started (adds line), step_finished (updates it?)
        # My ToolWorker emits `step_finished(title, detail, result)`.
        # ProgressItem doesn't have an update method for the last step easily unless we track it.
        # But `add_step` just adds a label.
        # Let's just log it or maybe add a "Done" checkmark?
        # The current implementation of ToolWorker calls `step_finished` which implies the step is done.
        # But `ProgressItem.add_step` was called at `step_started`.
        # If we want to show completion, we might need to modify ProgressItem or just assume success if no error is shown.
        # The ToolWorker emits `step_finished` with result text.
        # We can add a "Result" line or updated detail.
        pass

    def handle_tool_finished(self, output):
        self.progress_item.finish()
        
        # Add Tool Output to history as "System" (or "User" simulating system response?)
        # OpenAI expects tool outputs as "tool" role usually, but here we use a generic XML protocol.
        # We'll represent it as a "user" message with the tool output, or "system".
        # If we use "system", the AI treats it as directive.
        # If we use "user", the AI treats it as feedback.
        # "System" is probably safer for "Command Output".
        
        tool_msg = f"Tool Output:\n{output}"
        
        # We don't necessarily show the full tool output in the chat UI if it's huge, 
        # but for now we append it as a message so the user sees it.
        # Maybe collapsed?
        # MessageItem doesn't support collapsing yet.
        # We'll just add it.
        
        self.append_message_widget("system", tool_msg)
        self.messages.append({"role": "system", "content": tool_msg})
        
        # 4. Loop back to AI (Feed tool output back to model)
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
