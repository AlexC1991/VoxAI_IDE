from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget, 
                             QLineEdit, QPushButton, QLabel, QListWidgetItem, QComboBox)
from PySide6.QtCore import Signal, Qt, QThread, QObject
from ui.settings_dialog import SettingsDialog
from core.settings import SettingsManager
from core.settings import SettingsManager
from core.ai_client import AIClient
from core.code_parser import CodeParser
from core.agent_tools import AgentToolHandler
from ui.widgets.chat_items import MessageItem
import re
import os
import sys


class AIWorker(QObject):
    chunk_received = Signal(str)
    finished = Signal()
    tool_requested = Signal(str, str) # tool_name, result
    
    def __init__(self, message_history, model):
        super().__init__()
        self.message_history = message_history
        self.model = model
        self.client = AIClient()

    def run(self):
        print(f"[DEBUG] AIWorker running with model: {self.model}")
        
        # Inject CWD into system prompt if it's the first message or if we want to ensure it's there.
        # Ideally, we format the System Prompt in the message history before sending.
        # But prompts.py is static. Let's do a quick replace if it's in the messages.
        
        import os
        cwd = os.getcwd().replace("\\", "/")
        
        # Deep copy messages to avoid mutating the UI state permanently with formatting?
        # Or just update the system message.
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
                    print("[DEBUG] AIWorker Interrupted!")
                    break
                full_response += chunk
                self.chunk_received.emit(chunk)
                
                # Experimental: Stop if tool tag detected?
                # "/>" is weak, "</write_file>" is strong.
                # Let's rely on prompt first.
            
            # Post-processing for Tools (Simple Regex for now, synchronous)
            # In a real agent loop, this would happen iteratively.
            # Here we just check if the LAST response had a tool call and execute it?
            # Or we let the ChatPanel handle the logic. 
            # Better to just finish and let ChatPanel parse.
            
        except Exception as e:
            print(f"[ERROR] AIWorker run failed: {e}")
            self.chunk_received.emit(f"\n[Error: {str(e)}]\n")
        
        print("[DEBUG] AIWorker finished run.")
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
        from core.agent_tools import AgentToolHandler
        import os
        
        tool_outputs = []
        
        for call in self.tool_calls:
            if QThread.currentThread().isInterruptionRequested():
                tool_outputs.append("System: [Interrupted] Tool execution stopped by user.")
                break

            cmd = call['cmd']
            args = call['args']
            
            try:
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
                    
                    # Syntax Check
                    syntax_error = AgentToolHandler.validate_syntax(content, path)
                    if syntax_error:
                        tool_outputs.append(f"System: [Syntax Error] in '{path}':\n{syntax_error}")
                        self.step_finished.emit(f"Syntax Error in {os.path.basename(path)}", syntax_error, "Failed")
                        continue

                    # Diff
                    diff_text = None
                    diff_str = "modified"
                    full_path = os.path.abspath(path)
                    if os.path.exists(full_path):
                        try:
                            with open(full_path, 'r', encoding='utf-8') as f:
                                old_content = f.read()
                            diff_text = AgentToolHandler.get_diff(old_content, content, os.path.basename(path))
                        except:
                            diff_text = "[Error diff]"
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
                    self.step_started.emit("🌳", f" analyzing {os.path.basename(path)}...")
                    result = AgentToolHandler.get_file_structure(path)
                    tool_outputs.append(f"Structure of '{path}':\n{result}")
                    self.step_finished.emit(f"Got structure of {path}", None, "Done")

            except Exception as e:
                tool_outputs.append(f"System: Error executing {cmd}: {e}")
                self.step_finished.emit(f"Error in {cmd}", str(e), "Failed")
        
        self.finished.emit("\n\n".join(tool_outputs))

class ChatPanel(QWidget):
    message_sent = Signal(str)
    code_generated = Signal(str, str) # language, code
    file_updated = Signal(str) # absolute path


    def __init__(self, parent=None):
        super().__init__(parent)
        print("[DEBUG] ChatPanel initializing...")
        self.settings_manager = SettingsManager()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Header Removed (Moved to Main Window)
        
        # Chat History
        
        # Toolbar
        toolbar = QWidget()
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(5, 5, 5, 5)
        
        self.clear_btn = QPushButton("🧹 Clear Context")
        self.clear_btn.setToolTip("Reset conversation memory to save tokens")
        self.clear_btn.clicked.connect(self.clear_context)
        self.clear_btn.setStyleSheet("padding: 3px;")
        tb_layout.addWidget(self.clear_btn)
        tb_layout.addStretch()
        
        self.layout.addWidget(toolbar)
        
        # Chat History
        self.chat_history = QListWidget()
        self.chat_history.setAlternatingRowColors(True)
        self.chat_history.setWordWrap(True)
        self.layout.addWidget(self.chat_history)
        
        # Input Area
        input_container = QWidget()
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(0, 5, 0, 5)
        
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Describe what you want to build...")
        self.chat_input.returnPressed.connect(self.send_message)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self.send_message)
        
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_ai_worker)
        self.stop_btn.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        self.stop_btn.hide() # Hidden by default
        
        input_layout.addWidget(self.chat_input)
        input_layout.addWidget(self.send_btn)
        input_layout.addWidget(self.stop_btn)
        
        self.layout.addWidget(input_container)
        
        # Threading state
        self.ai_thread = None
        self.ai_worker = None
        
        # Internal message memory for context
        from core.prompts import SystemPrompts
        self.messages = [
            {"role": "system", "content": SystemPrompts.CODING_AGENT}
        ]
        
        # INJECT INITIAL CONTEXT
        # The AI needs to know what files exist immediately.
        import os
        try:
            cwd = os.getcwd()
            files = []
            for root, dirs, filenames in os.walk(cwd):
                if ".git" in dirs: dirs.remove(".git")
                if "__pycache__" in dirs: dirs.remove("__pycache__")
                for f in filenames:
                    rel_path = os.path.relpath(os.path.join(root, f), cwd)
                    files.append(rel_path)
            
            file_list_str = "\n".join(files[:50]) # Limit to 50 for now
            if len(files) > 50: file_list_str += "\n...(more files)..."
            
            context_msg = f"Current Project Structure ({cwd}):\n{file_list_str}\n\nStart by listing files if you need to double check."
            self.messages.append({"role": "system", "content": context_msg})
        except Exception as e:
            print(f"Error injecting context: {e}")

    def clear_context(self):
        """Resets the conversation history to save tokens."""
        # Keep only System Prompt and Initial Context
        initial_msgs = self.messages[:2] 
        self.messages = initial_msgs
        
        self.chat_history.clear()
        self.add_message("System", "🧹 Context cleared. Memory reset.")
        
        # Re-display the initial context signal?
        # Maybe just leave it blank.

    # Methods moved to MainWindow to control Global Toolbar

    def send_message(self):
        text = self.chat_input.text().strip()
        self.send_worker(text)

    def add_message(self, role, content):
        # Create Custom Widget
        
        item = QListWidgetItem()
        # Estimate size? MessageItem will handle layout.
        # We need to set item size hint after creating widget.
        
        msg_widget = MessageItem(role, content)
        item.setSizeHint(msg_widget.sizeHint())
        
        self.chat_history.addItem(item)
        self.chat_history.setItemWidget(item, msg_widget)
        self.chat_history.scrollToBottom()

    def trigger_fix(self, error_message):
        """Called when a script fails. Sends the error to the AI."""
        context = f"The script failed with the following error. Please analyze it and provide the fixed code.\n\nError Output:\n{error_message}"
        
        # Simulate user sending this message
        self.send_worker(context, is_automated=True)

    def send_worker(self, text, is_automated=False, visible=True):
        if not text:
            return
            
        # UI Update
        if not is_automated:
            self.chat_input.clear()
        
        if visible:
            role = "System" if is_automated else "User"
            self.add_message(role, text)
        
        self.message_sent.emit(text)
        
        # State Update
        self.messages.append({"role": "user", "content": text})
        
        # Disable input while processing
        self.send_btn.setEnabled(False)
        
        # Start Worker
        self.start_ai_worker()

    def start_ai_worker(self):
        # Clean up old thread if it exists but is finished
        if self.ai_thread is not None:
            if self.ai_thread.isRunning():
                print("[DEBUG] Thread already running, ignoring request.")
                return
            else:
                # Needed to ensure valid state before overwriting
                self.ai_thread.wait()
                self.ai_thread = None

        print("[DEBUG] Starting AI Worker thread...")
        model = self.settings_manager.get_selected_model()
        
        # SLIDING WINDOW / TOKEN SAVING
        full_history = self.messages
        if len(full_history) > 22: # 2 + 20
            context_window = full_history[:2] + full_history[-20:]
            print(f"[DEBUG] Context truncated. Sending {len(context_window)} messages")
        else:
            context_window = full_history
        
        # Create Progress Item
        from ui.widgets.chat_items import ProgressItem
        item = QListWidgetItem()
        self.current_progress_widget = ProgressItem()
        item.setSizeHint(self.current_progress_widget.sizeHint()) # Initial hint
        self.chat_history.addItem(item)
        self.chat_history.setItemWidget(item, self.current_progress_widget)
        self.current_progress_item = item # Keep ref to resize later
        
        # Connect resize signal
        # Connect resize signal
        self.current_progress_widget.size_changed.connect(lambda: item.setSizeHint(self.current_progress_widget.sizeHint()))
        self.current_progress_widget.show_detail_requested.connect(self.show_diff_dialog)
        
        from ui.widgets.chat_items import MessageItem
        
        # Prepare AI Bubble (Empty for now, will fill if text exists)
        self.current_ai_item = QListWidgetItem()
        self.current_ai_widget = MessageItem("AI", "")
        self.current_ai_item.setSizeHint(self.current_ai_widget.sizeHint())
        
        self.chat_history.addItem(self.current_ai_item)
        self.chat_history.setItemWidget(self.current_ai_item, self.current_ai_widget)
        self.chat_history.scrollToBottom()
        self.current_ai_text = "AI: "
        
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

        self.ai_thread.finished.connect(self.cleanup_thread)

        self.stop_btn.show()
        self.send_btn.hide()
        self.ai_thread.start()

    def stop_ai_worker(self):
        """Manually stops the AI generation."""
        if self.ai_thread and self.ai_thread.isRunning():
            print("[ChatPanel] Stopping AI worker...")
            self.ai_thread.requestInterruption()
            self.ai_thread.quit()
            self.ai_thread.wait(1000) # Wait up to 1s
            
            # Force cleanup if still running?
            if self.ai_thread.isRunning():
                self.ai_thread.terminate() # Hard kill if needed (dangerous but effective for stop button)
            
            self.cleanup_thread()
            if hasattr(self, 'current_progress_widget'):
                self.current_progress_widget.add_step("🛑", "Stopped by user.")
                self.current_progress_widget.finish()
            
            # Reset UI
            self.on_ai_finished(interrupted=True)

    def cleanup_thread(self):
        # Safely clear the reference so start_ai_worker doesn't try to reuse a dead object
        if self.ai_thread:
            print("[DEBUG] Cleaning up AI Thread ref.")
            self.ai_thread = None

    def clean_display_text(self, text):
        """Removes XML tags from the text for display."""
        import re
        # 1. Remove thoughts (handled separately in UI)
        text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL)
        
        # 2. Remove specific tool tags
        # Self-closing tags: <tool ... />
        text = re.sub(r'<(list_files|read_file|move_file|copy_file|delete_file|search_files|get_file_structure)[^>]*?/>', '', text, flags=re.DOTALL)
        
        # Block tags: <write_file ...> ... </write_file>
        # We want to hide the content AND the tags.
        # During streaming, we might have an open tag but no closing tag yet.
        # We should hide from <write_file...> to </write_file> OR to the end of string if still open.
        
        # Match complete blocks first
        text = re.sub(r'<write_file[^>]*?>.*?</write_file>', '', text, flags=re.DOTALL)
        
        # Match partial blocks (open tag to end of string)
        # Only do this if we are seemingly inside a block.
        # Check if there is an unclosed <write_file tag
        # Count open vs closed?
        # Simple heuristic: if <write_file exists but no </write_file> after it.
        
        # Use a non-greedy match for the start, then consume rest
        # But be careful not to hide "I am writing <write_file" (intro text)
        # The regex `<write_file[^>]*?>.*` matches from the tag start.
        
        if '<write_file' in text and '</write_file>' not in text:
             text = re.sub(r'<write_file[^>]*?>.*', ' [Writing File...]', text, flags=re.DOTALL)
        elif '<write_file' in text:
             # Case where there might be multiple blocks, some closed, last one open.
             # This is complex regex.
             # Let's simple split by <write_file and check.
             pass
             
        return text.strip()

    def on_ai_chunk(self, chunk):
        self.current_ai_text += chunk
        
        # Extract thoughts
        import re
        thoughts = re.findall(r'<thought>(.*?)</thought>', self.current_ai_text, re.DOTALL)
        if thoughts:
             combined_thoughts = "\n".join(thoughts)
             self.current_progress_widget.set_thought(combined_thoughts)
             
        # Clean text for display
        display_text = self.clean_display_text(self.current_ai_text)
        
        # Update the Custom MessageItem Widget
        if hasattr(self, 'current_ai_widget'):
             self.current_ai_widget.content_label.setText(display_text)
             # Only resize if text changed meaningfully? 
             # self.current_ai_item.setSizeHint(self.current_ai_widget.sizeHint()) 
             # SizeHint update might be expensive on every chunk, but needed for wrapping.
             self.current_ai_item.setSizeHint(self.current_ai_widget.sizeHint())
        else:
             self.current_ai_item.setText(display_text)
        
        self.chat_history.scrollToBottom()
        
        # Resize progress item as content grows (thoughts)
        self.current_progress_item.setSizeHint(self.current_progress_widget.sizeHint())

    def on_ai_finished(self, interrupted=False):
        print("[DEBUG] AI Worker finished signal received.")
        self.current_progress_widget.finish()
        
        if interrupted:
            self.stop_btn.hide()
            self.send_btn.show()
            self.send_btn.setEnabled(True)
            return
            
        # Save full AI response (WITH thoughts) to history context
        full_response = self.current_ai_text.replace("AI: ", "", 1)
        self.messages.append({"role": "assistant", "content": full_response})
        
        # --- PARSE TOOLS ---
        tool_calls = []
        import re
        
        # 1. List Files
        for match in re.finditer(r'<list_files(?: path="(.*?)")?.*?>', full_response):
            tool_calls.append({'cmd': 'list_files', 'args': {'path': match.group(1) or '.'}})

        # 2. Read Files
        for match in re.finditer(r'<read_file path="(.*?)".*?/>', full_response):
            tool_calls.append({'cmd': 'read_file', 'args': {'path': match.group(1)}})

        # 3. Write Files
        for match in re.finditer(r'<write_file path="(.*?)"\s*>(.*?)</write_file>', full_response, re.DOTALL):
            tool_calls.append({'cmd': 'write_file', 'args': {'path': match.group(1), 'content': match.group(2)}})

        # 4. Move Files
        for match in re.finditer(r'<move_file src="(.*?)" dst="(.*?)"\s*/>', full_response):
            tool_calls.append({'cmd': 'move_file', 'args': {'src': match.group(1), 'dst': match.group(2)}})

        # 5. Copy Files
        for match in re.finditer(r'<copy_file src="(.*?)" dst="(.*?)"\s*/>', full_response):
             tool_calls.append({'cmd': 'copy_file', 'args': {'src': match.group(1), 'dst': match.group(2)}})

        # 6. Delete Files
        for match in re.finditer(r'<delete_file path="(.*?)"\s*/>', full_response):
             tool_calls.append({'cmd': 'delete_file', 'args': {'path': match.group(1)}})

        # 7. Search Files
        for match in re.finditer(r'<search_files query="(.*?)"(?: root_dir="(.*?)")?\s*/>', full_response):
             tool_calls.append({'cmd': 'search_files', 'args': {'query': match.group(1), 'root_dir': match.group(2)}})

        # 8. Get File Structure
        for match in re.finditer(r'<get_file_structure path="(.*?)"\s*/>', full_response):
             tool_calls.append({'cmd': 'get_file_structure', 'args': {'path': match.group(1)}})

        if not tool_calls:
            # No tools, just finish
            self.stop_btn.hide()
            self.send_btn.show()
            self.send_btn.setEnabled(True)
            
            # Check for code block to emit
            lang, code = CodeParser.extract_code(full_response)
            if code:
                self.code_generated.emit(lang, code)
                
            # Fallback for empty text (if just thoughts were generated)
            cleaned_text = self.clean_display_text(full_response)
            if not cleaned_text.strip() and not code:
                # If we have thoughts but no text, maybe the AI is just thinking?
                # But if it finished, we should say something.
                self.add_message("AI", "(Thinking complete. No output generated.)")
            return

        # --- EXECUTE TOOLS ASYNC ---
        print(f"[DEBUG] Starting ToolWorker with {len(tool_calls)} calls.")
        self.tool_thread = QThread()
        self.tool_worker = ToolWorker(tool_calls)
        self.tool_worker.moveToThread(self.tool_thread)
        
        self.tool_thread.started.connect(self.tool_worker.run)
        
        # Connect Signals
        self.tool_worker.step_started.connect(self.on_tool_step_started)
        self.tool_worker.step_finished.connect(self.on_tool_step_finished)
        self.tool_worker.file_changed.connect(self.file_updated.emit)
        self.tool_worker.finished.connect(self.on_tool_worker_finished)
        
        # Cleanup
        self.tool_worker.finished.connect(self.tool_thread.quit)
        self.tool_worker.finished.connect(self.tool_worker.deleteLater)
        self.tool_thread.finished.connect(self.tool_thread.deleteLater)
        self.tool_thread.finished.connect(lambda: setattr(self, 'tool_thread', None))

        self.tool_thread.start()

    def on_tool_step_started(self, icon, text):
        # Optional: could show a spinner or log
        pass 

    def on_tool_step_finished(self, title, detail, result):
        # Map result to icon
        icon = "✅" if result == "Done" else "⚠️"
        if "Syntax Error" in title: icon = "❌"
        
        # Use specific icons based on title keywords
        if "Read" in title: icon = "📖"
        elif "Wrote" in title: icon = "📝"
        elif "Listed" in title: icon = "📂"
        elif "Moved" in title: icon = "➡️"
        elif "Copied" in title: icon = "📋"
        elif "Deleted" in title: icon = "🗑️"
        elif "Searched" in title: icon = "🔍"
        elif "Structure" in title: icon = "🌳"
        
        self.current_progress_widget.add_step(icon, title, detail=detail)

    def on_tool_worker_finished(self, combined_output):
        print("[DEBUG] ToolWorker finished.")
        
        self.stop_btn.hide()
        self.send_btn.show()
        self.send_btn.setEnabled(True)
        
        if combined_output.strip():
            # Send results back to AI
             from PySide6.QtCore import QTimer
             # Send as automated BUT invisible
             QTimer.singleShot(100, lambda: self.send_worker(combined_output, is_automated=True, visible=False))

    def show_diff_dialog(self, title, content):
        """Shows a dialog with the diff/detail."""
        from PySide6.QtWidgets import QDialog, QTextEdit, QVBoxLayout, QPushButton
        d = QDialog(self)
        d.setWindowTitle(f"Detail: {title}")
        d.resize(600, 400)
        layout = QVBoxLayout(d)
        
        text_edit = QTextEdit()
        text_edit.setPlainText(content)
        text_edit.setReadOnly(True)
        # Simple coloring for diffs
        if "diff" in content or "@@" in content:
             # We could use the MessageItem highlighter logic here too?
             # For now, just set a font
             font = text_edit.font()
             font.setFamily("Consolas")
             text_edit.setFont(font)
             
        layout.addWidget(text_edit)
        
        btn = QPushButton("Close")
        btn.clicked.connect(d.accept)
        layout.addWidget(btn)
        
        d.exec()

    def closeEvent(self, event):
        print("[DEBUG] ChatPanel closing, checking thread...")
        if self.ai_thread and self.ai_thread.isRunning():
            self.ai_thread.quit()
            self.ai_thread.wait()
        super().closeEvent(event)
