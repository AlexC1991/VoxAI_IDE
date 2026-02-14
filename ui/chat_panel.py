import os
import sys
import re
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, 
    QTextEdit, QPushButton, QFrame, QSizePolicy
)
from PySide6.QtCore import Signal, Qt, QThread, QObject, QTimer, QEvent
from PySide6.QtGui import QTextCursor

from core.settings import SettingsManager
from core.ai_client import AIClient
from core.code_parser import CodeParser
from core.agent_tools import AgentToolHandler
from ui.widgets.chat_items import MessageItem, ProgressItem

log = logging.getLogger(__name__)

# ... (omitted workers) ...

class AIWorker(QObject):
    chunk_received = Signal(str)
    finished = Signal()
    
    def __init__(self, message_history, model):
        super().__init__()
        self.message_history = message_history
        self.model = model
        self.client = AIClient()

    def run(self):
        log.debug("AIWorker running with model: %s", self.model)
        
        # Helper: Inject CWD into system prompt if needed
        import os
        cwd = os.getcwd().replace("\\", "/")
        
        final_messages = []
        for msg in self.message_history:
            if msg.get("role") == "system":
                content = msg["content"]
                if "{cwd_path}" in content:
                    content = content.replace("{cwd_path}", cwd)
                final_messages.append({"role": "system", "content": content})
            else:
                final_messages.append(msg)
        
        full_response = ""
        try:
            stream = self.client.stream_chat(final_messages, self.model)
            for chunk in stream:
                if QThread.currentThread().isInterruptionRequested():
                    log.debug("AIWorker Interrupted!")
                    break
                full_response += chunk
                self.chunk_received.emit(chunk)
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
                    self.step_started.emit("📖", f"Reading {os.path.basename(path)}...")
                    content = AgentToolHandler.read_file(path)
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
                    self.step_finished.emit(f"Got structure of {path}", None, "Done")

            except Exception as e:
                tool_outputs.append(f"System: Error executing {cmd}: {e}")
                self.step_finished.emit(f"Error in {cmd}", str(e), "Failed")
        
        self.finished.emit("\n\n".join(tool_outputs))


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
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # 1. Toolbar (Clear Context)
        toolbar = QWidget()
        toolbar.setStyleSheet("background-color: #1e1e1e; border-bottom: 1px solid #2d2d2d;") # Match main theme
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 4, 8, 4)
        
        self.clear_btn = QPushButton("🧹 Clear Context")
        self.clear_btn.setToolTip("Reset conversation memory")
        self.clear_btn.clicked.connect(self.clear_context)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #52525b;
                border: 1px solid #27272a;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                color: #e4e4e7;
                border-color: #52525b;
            }
        """)
        tb_layout.addWidget(self.clear_btn)
        tb_layout.addStretch()
        self.layout.addWidget(toolbar)

        # 2. Scroll Area for Chat
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea { border: none; background-color: #1e1e1e; }
            QScrollBar:vertical {
                border: none;
                background: #1e1e1e;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #424242;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        self.chat_container = QWidget()
        self.chat_container.setStyleSheet("background-color: #1e1e1e;")
        self.chat_layout = QVBoxLayout(self.chat_container)
        self.chat_layout.setContentsMargins(10, 10, 10, 10)
        self.chat_layout.setSpacing(10)
        self.chat_layout.addStretch() # Pushes messages to bottom initially, or top? 
        # Actually for a chat log, we want them at the top usually, but let's see. 
        # Standard terminal: text starts at top.
        
        self.scroll_area.setWidget(self.chat_container)
        self.layout.addWidget(self.scroll_area, 1)

        # 3. Input Area
        input_container = QWidget()
        input_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        input_container.setStyleSheet("background-color: #1e1e1e; border-top: 1px solid #2d2d2d;")
        input_layout = QHBoxLayout(input_container) # Horizontal
        input_layout.setContentsMargins(8, 8, 8, 8) # Tighter margins
        input_layout.setSpacing(8)
        
        # Text Edit for multi-line input
        self.chat_input = QTextEdit()
        self.chat_input.setPlaceholderText("Type a message...")
        self.chat_input.setFixedHeight(38) # Compact height (approx 1 line + padding)
        self.chat_input.setStyleSheet("""
            QTextEdit {
                background-color: #252526;
                color: #cccccc;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 4px 8px; /* Tighter padding */
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QTextEdit:focus {
                border: 1px solid #007fd4;
            }
        """)
        # Install event filter or handle key press for Enter=Send
        self.chat_input.installEventFilter(self)
        
        # Buttons (Right side)
        btn_layout = QVBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(0)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.setFixedSize(60, 38) # Match input height
        self.send_btn.clicked.connect(self.send_message)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #007fd4;
                color: #ffffff;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #026ec1; }
            QPushButton:disabled { background-color: #3e3e42; color: #6e6e6e; }
        """)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedSize(60, 38) # Match input height
        self.stop_btn.clicked.connect(self.stop_ai_worker)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #ce9178;
                color: #1e1e1e;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #be8168; }
        """)
        self.stop_btn.hide()
        
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.send_btn)
        
        input_layout.addWidget(self.chat_input)
        input_layout.addLayout(btn_layout)
        
        self.layout.addWidget(input_container, 0)

        # Threading state
        self.ai_thread = None
        self.ai_worker = None
        self.tool_thread = None
        
        # Context
        from core.prompts import SystemPrompts
        self.messages = [
            {"role": "system", "content": SystemPrompts.CODING_AGENT}
        ]
        
        # Inject Initial Context
        self.inject_initial_context()

    def eventFilter(self, obj, event):
        if obj == self.chat_input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Return and not (event.modifiers() & Qt.ShiftModifier):
                self.send_message()
                return True
        return super().eventFilter(obj, event)

    def inject_initial_context(self):
        try:
            cwd = os.getcwd()
            files = []
            for root, dirs, filenames in os.walk(cwd):
                if ".git" in dirs: dirs.remove(".git")
                if "__pycache__" in dirs: dirs.remove("__pycache__")
                for f in filenames:
                    rel_path = os.path.relpath(os.path.join(root, f), cwd)
                    files.append(rel_path)
            
            file_list_str = "\n".join(files[:50])
            if len(files) > 50: file_list_str += "\n...(more files)..."
            
            context_msg = f"Current Project Structure ({cwd}):\n{file_list_str}\n\nStart by listing files if you need to double check."
            self.messages.append({"role": "system", "content": context_msg})
        except Exception as e:
            log.error("Error injecting context: %s", e)

    def clear_context(self):
        initial_msgs = self.messages[:2] 
        self.messages = initial_msgs
        
        # Clear UI logic for QLayout is tricky - safe delete widgets
        self.clear_layout(self.chat_layout)
        self.chat_layout.addStretch() # Re-add stretch
        
        self.add_message("System", "🧹 Context cleared. Memory reset.")

    def clear_layout(self, layout):
        if layout is None: return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            else:
                self.clear_layout(item.layout())

    def send_message(self):
        text = self.chat_input.toPlainText().strip()
        if not text: return
        self.send_worker(text)

    def add_message(self, role, content):
        # Remove the stretch at the end temporarily?
        # Standard approach: add widget, then ensure scroll to bottom.
        
        msg_widget = MessageItem(role, content)
        # Add before the stretch item? 
        # Actually with addStretch() at the top, we want to add *after* it if we want bottom alignment?
        # Or if we want top alignment (slack style), we add to top and stretch at bottom.
        
        # Current layout: stretch is at index 0.
        # We want messages to flow from top to bottom.
        # So we should insert at layout.count() - 1 (before stretch) 
        # OR just append if we don't use stretch for bottom-pushing.
        
        # Let's remove stretch logic for simplicity and just stack them top-down.
        # We removed the "addStretch" in clear_context for safety.
        # Let's just use top-stacking. 
        # To make them push up from bottom, we place a stretch at index 0.
        
        # Let's try standard top-down. 
        # If we want them to fill from bottom, we use insertWidget(count-1, widget).
        
        # For now, just append.
        self.chat_layout.addWidget(msg_widget)
        
        # Scroll to bottom
        QTimer.singleShot(10, self.scroll_to_bottom)
        return msg_widget

    def scroll_to_bottom(self):
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def send_worker(self, text, is_automated=False, visible=True):
        if not text: return
        
        if not is_automated:
            self.chat_input.clear()
        
        if visible:
            role = "System" if is_automated else "User"
            self.add_message(role, text)
        
        self.message_sent.emit(text)
        self.messages.append({"role": "user", "content": text})
        
        self.send_btn.setEnabled(False)
        self.start_ai_worker()

    def start_ai_worker(self):
        if self.ai_thread and self.ai_thread.isRunning():
            log.warning("Thread already running, ignoring request.")
            return

        log.info("Starting AI Worker thread...")
        model = self.settings_manager.get_selected_model()
        
        # Context Window Logic (Simple Truncation)
        full_history = self.messages
        if len(full_history) > 22:
            context_window = full_history[:2] + full_history[-20:]
            log.debug("Context truncated. Sending %d messages", len(context_window))
        else:
            context_window = full_history
        
        # Create Progress Item
        self.current_progress_widget = ProgressItem()
        self.chat_layout.addWidget(self.current_progress_widget)
        self.current_ai_widget = None # Will create lazily
        self.current_ai_text = "AI: "
        
        self.scroll_to_bottom()

        self.ai_thread = QThread()
        self.ai_worker = AIWorker(list(context_window), model)
        self.ai_worker.moveToThread(self.ai_thread)
        
        self.ai_thread.started.connect(self.ai_worker.run)
        self.ai_worker.chunk_received.connect(self.on_ai_chunk)
        self.ai_worker.finished.connect(self.on_ai_finished)
        self.ai_worker.finished.connect(self.ai_thread.quit)
        self.ai_worker.finished.connect(self.ai_worker.deleteLater)
        self.ai_thread.finished.connect(self.ai_thread.deleteLater)
        self.ai_thread.finished.connect(self.cleanup_thread)

        self.stop_btn.show()
        self.send_btn.hide()
        self.ai_thread.start()

    def stop_ai_worker(self):
        if self.ai_thread and self.ai_thread.isRunning():
            log.info("Stopping AI worker...")
            self.ai_thread.requestInterruption()
            self.ai_thread.quit()
            self.ai_thread.wait(1000)
            
            if self.ai_thread.isRunning():
                self.ai_thread.terminate() 
            
            self.cleanup_thread()
            if hasattr(self, 'current_progress_widget'):
                self.current_progress_widget.add_step("🛑", "Stopped by user.")
                self.current_progress_widget.finish()
            
            self.on_ai_finished(interrupted=True)

    def cleanup_thread(self):
        if self.ai_thread:
            log.debug("Cleaning up AI Thread ref.")
            self.ai_thread = None

    def clean_display_text(self, text):
        """Removes XML tags from the text for display."""
        import re
        text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL)
        text = re.sub(r'<(list_files|read_file|move_file|copy_file|delete_file|search_files|get_file_structure)[^>]*?/>', '', text, flags=re.DOTALL)
        text = re.sub(r'<write_file[^>]*?>.*?</write_file>', '', text, flags=re.DOTALL)
        
        if '<write_file' in text and '</write_file>' not in text:
             text = re.sub(r'<write_file[^>]*?>.*', ' [Writing File...]', text, flags=re.DOTALL)
             
        return text.strip()

    def on_ai_chunk(self, chunk):
        self.current_ai_text += chunk
        
        # Extract thoughts
        thoughts = re.findall(r'<thought>(.*?)</thought>', self.current_ai_text, re.DOTALL)
        if thoughts:
             combined_thoughts = "\n".join(thoughts)
             self.current_progress_widget.set_thought(combined_thoughts)
             
        display_text = self.clean_display_text(self.current_ai_text)
        
        # Lazy Creation of MessageItem
        if not self.current_ai_widget and display_text.strip():
             self.current_ai_widget = self.add_message("AI", "")
             
        if self.current_ai_widget:
             # Only update text if it changed (optimization?) 
             # For RichText label, setText is moderately expensive.
             # But we need to update.
             # We should probably format it incrementally? No, full re-render for now.
             # MessageItem internal format helper handles syntax highlighting.
             # Accessing internal label directly is naughty but effective.
             formatted = self.current_ai_widget._format(display_text)
             self.current_ai_widget.content_label.setText(formatted)
             self.scroll_to_bottom()

    def on_ai_finished(self, interrupted=False):
        log.debug("AI Worker finished signal received.")
        if hasattr(self, 'current_progress_widget'):
            self.current_progress_widget.finish()
        
        if interrupted:
            self.stop_btn.hide()
            self.send_btn.show()
            self.send_btn.setEnabled(True)
            return

        full_response = self.current_ai_text.replace("AI: ", "", 1)
        self.messages.append({"role": "assistant", "content": full_response})
        log.debug("Raw AI Response length: %d chars", len(full_response))
        
        # Parse Tools
        tool_calls = self._parse_tools(full_response)
        
        if not tool_calls:
            self.stop_btn.hide()
            self.send_btn.show()
            self.send_btn.setEnabled(True)
            
            # Check for code block
            lang, code = CodeParser.extract_code(full_response)
            if code:
                self.code_generated.emit(lang, code)
                
            cleaned_text = self.clean_display_text(full_response)
            if not cleaned_text.strip() and not code:
                self.add_message("AI", "(Thinking complete. No output generated.)")
            return

        # Truncation check
        if full_response.strip() and not tool_calls and not full_response.strip().endswith(('.', '>', '}', ']', ')', '!')):
            # Heuristic check for truncation (not ending with punctuation or closing bracket/tag)
            # Or check length limit? Actually easier is if it ends in standard punctuation.
            # But code blocks end with ``` which is not checked here.
            # Let's check for unfinished tags.
            if full_response.count('<') > full_response.count('>'):
                self.add_message("System", "⚠️ Warning: The AI response appears truncated (missing closing tag). Try asking to continue.")
            elif not full_response.endswith(('.', '?', '!', '>', '```')):
                 # Maybe truncated text?
                 pass

        # Execute Tools
        log.info("Starting ToolWorker with %d calls.", len(tool_calls))
        self.tool_thread = QThread()
        self.tool_worker = ToolWorker(tool_calls)
        self.tool_worker.moveToThread(self.tool_thread)
        
        self.tool_thread.started.connect(self.tool_worker.run)
        
        self.tool_worker.step_started.connect(self.on_tool_step_started)
        self.tool_worker.step_finished.connect(self.on_tool_step_finished)
        self.tool_worker.file_changed.connect(self.file_updated.emit)
        self.tool_worker.finished.connect(self.on_tool_worker_finished)
        
        self.tool_worker.finished.connect(self.tool_thread.quit)
        self.tool_worker.finished.connect(self.tool_worker.deleteLater)
        self.tool_thread.finished.connect(self.tool_thread.deleteLater)
        self.tool_thread.finished.connect(lambda: setattr(self, 'tool_thread', None))

        self.tool_thread.start()

    def _parse_tools(self, text):
        tool_calls = []
        # Lists
        for match in re.finditer(r'<list_files(?: path="(.*?)")?.*?>', text):
            tool_calls.append({'cmd': 'list_files', 'args': {'path': match.group(1) or '.'}})
        # Reads
        for match in re.finditer(r'<read_file path="(.*?)".*?/>', text):
            tool_calls.append({'cmd': 'read_file', 'args': {'path': match.group(1)}})
        # Writes
        for match in re.finditer(r'<write_file[^>]*path="(.*?)"[^>]*>(.*?)</write_file>', text, re.DOTALL):
            tool_calls.append({'cmd': 'write_file', 'args': {'path': match.group(1), 'content': match.group(2)}})
        # Moves
        for match in re.finditer(r'<move_file src="(.*?)" dst="(.*?)"\s*/>', text):
            tool_calls.append({'cmd': 'move_file', 'args': {'src': match.group(1), 'dst': match.group(2)}})
        # Copies
        for match in re.finditer(r'<copy_file src="(.*?)" dst="(.*?)"\s*/>', text):
             tool_calls.append({'cmd': 'copy_file', 'args': {'src': match.group(1), 'dst': match.group(2)}})
        # Deletes
        for match in re.finditer(r'<delete_file path="(.*?)"\s*/>', text):
             tool_calls.append({'cmd': 'delete_file', 'args': {'path': match.group(1)}})
        # Searches
        for match in re.finditer(r'<search_files query="(.*?)"(?: root_dir="(.*?)")?\s*/>', text):
             tool_calls.append({'cmd': 'search_files', 'args': {'query': match.group(1), 'root_dir': match.group(2)}})
        # Structure
        for match in re.finditer(r'<get_file_structure path="(.*?)"\s*/>', text):
             tool_calls.append({'cmd': 'get_file_structure', 'args': {'path': match.group(1)}})
        return tool_calls

    def on_tool_step_started(self, icon, text):
        pass 

    def on_tool_step_finished(self, title, detail, result):
        icon = "✅" if result == "Done" else "⚠️"
        if "Syntax Error" in title: icon = "❌"
        
        if "Read" in title: icon = "📖"
        elif "Wrote" in title: icon = "📝"
        elif "Listed" in title: icon = "📂"
        elif "Moved" in title: icon = "➡️"
        elif "Copied" in title: icon = "📋"
        elif "Deleted" in title: icon = "🗑️"
        elif "Searched" in title: icon = "🔍"
        elif "Structure" in title: icon = "🌳"
        
        self.current_progress_widget.add_step(icon, title, detail=detail)
        self.scroll_to_bottom()

    def on_tool_worker_finished(self, combined_output):
        log.debug("ToolWorker finished.")
        self.stop_btn.hide()
        self.send_btn.show()
        self.send_btn.setEnabled(True)
        
        if combined_output.strip():
             QTimer.singleShot(100, lambda: self.send_worker(combined_output, is_automated=True, visible=False))

    def show_diff_dialog(self, title, content):
        from PySide6.QtWidgets import QDialog, QTextEdit, QVBoxLayout, QPushButton
        d = QDialog(self)
        d.setWindowTitle(f"Detail: {title}")
        d.resize(600, 400)
        layout = QVBoxLayout(d)
        
        text_edit = QTextEdit()
        text_edit.setPlainText(content)
        text_edit.setReadOnly(True)
        font = text_edit.font()
        font.setFamily("Consolas")
        text_edit.setFont(font)
             
        layout.addWidget(text_edit)
        
        btn = QPushButton("Close")
        btn.clicked.connect(d.accept)
        layout.addWidget(btn)
        
        d.exec()

    def closeEvent(self, event):
        log.debug("ChatPanel closing, checking thread...")
        if self.ai_thread and self.ai_thread.isRunning():
            self.ai_thread.quit()
            self.ai_thread.wait()
        super().closeEvent(event)
