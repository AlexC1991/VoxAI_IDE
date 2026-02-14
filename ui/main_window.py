import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QSplitter, QHBoxLayout, QPushButton, QComboBox, QLabel, QFrame)
from PySide6.QtCore import Qt, QProcess

from ui.chat_panel import ChatPanel
from ui.editor_panel import EditorPanel
from ui.file_tree_panel import FileTreePanel
from ui.debug_drawer import DebugDrawer
from core.runner import Runner
from core.agent_tools import set_project_root

class CodingAgentIDE(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VoxAI Coding Agent IDE")
        self.resize(1200, 800)

        # Core Settings
        from core.settings import SettingsManager
        self.settings_manager = SettingsManager()
        
        # Project Selection Hook
        # Will be called after panels are initialized to ensure they exist.
        self.project_path = None

        # Core Services
        self.runner = Runner()
        self.runner.output_received.connect(self.on_process_output)
        self.runner.execution_started.connect(self.on_execution_start)
        self.runner.execution_finished.connect(self.on_execution_finish)

        # Central Widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Instantiate Panels First (so Toolbar can connect to them)
        self.chat_panel = ChatPanel()
        self.chat_panel.message_sent.connect(self.handle_chat_message)
        self.chat_panel.code_generated.connect(self.on_code_generated)
        self.chat_panel.file_updated.connect(self.on_file_updated)

        self.editor_panel = EditorPanel()
        self.editor_panel.run_requested.connect(self.run_script)

        self.tree_panel = FileTreePanel(start_path=self.project_path)
        self.tree_panel.file_double_clicked.connect(self.editor_panel.load_file)

        self.debug_drawer = DebugDrawer(self)
        self.debug_drawer.hide()
        self.debug_drawer.setStyleSheet("border-left: 1px solid #3E3E42; background-color: #1E1E1E;")
        self.debug_drawer.send_to_agent.connect(self.handle_debug_output_to_chat)

        # 2. Create Global Toolbar (Now safe to connect)
        self.create_global_toolbar()
        main_layout.addWidget(self.toolbar_widget)
        
        # 3. Setup Main Splitter (Below Toolbar)
        self.main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.main_splitter)

        # Add Chat Panel
        self.main_splitter.addWidget(self.chat_panel)

        # Setup Right Splitter
        self.right_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.addWidget(self.right_splitter)

        # Add Editor and Tree
        self.right_splitter.addWidget(self.editor_panel)
        self.right_splitter.addWidget(self.tree_panel)

        # Initial Sizes

        # Initial Sizes
        # Chat: 300, Right: 900
        self.main_splitter.setSizes([300, 900])
        # Editor: 500, Tree: 250
        self.right_splitter.setSizes([600, 200])

        # Menu Bar (Must be after panels are initialized)
        self.create_menu_bar()

        # Project Selection Hook (Now safe)
        self.select_project_folder()
        
        if not self.project_path:
             self.project_path = os.getcwd()
             self.tree_panel.set_root_path(self.project_path)
             self.settings_manager.set_last_project_path(self.project_path)

        set_project_root(self.project_path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Position Debug Drawer as an overlay on the right
        # Width: 40% of window or fixed? Let's say fixed 450px or 40%
        drawer_width = 450
        toolbar_height = self.toolbar_widget.height() if hasattr(self, 'toolbar_widget') else 50
        
        # x, y, w, h
        self.debug_drawer.setGeometry(
            self.width() - drawer_width,
            toolbar_height + self.menuBar().height(), # Offset by toolbar + menu
            drawer_width,
            self.height() - toolbar_height - self.menuBar().height()
        )
        self.debug_drawer.raise_()

    def on_file_updated(self, file_path):
        """Called when AI writes a file. Open or reload it."""
        print(f"[Main] AI updated file: {file_path}")
        self.editor_panel.load_file(file_path)
        self.tree_panel.refresh() # Ensure tree sees the new/updated file
        # self.debug_drawer.show() # User requested manual open only
        self.debug_drawer.append_output(f"> AI updated: {os.path.basename(file_path)}")

    def on_code_generated(self, language, code):
        # Only use this if NO file was written (fallback for snippets)
        # We might want to just show it in a new "Untitled" tab or ignore if it's duping.
        # For now, let's log it but NOT overwrite the current editor to prevent accidents.
        self.debug_drawer.append_output(f"> AI generated snippet ({language}). Check chat for details.")

    def run_script(self, script_path):
        self.runner.run_script(script_path)

    def on_execution_start(self, script_path):
        self.debug_drawer.show()
        self.debug_drawer.clear_output()
        self.debug_drawer.append_output(f"> Executing: {script_path}\n")

    def on_process_output(self, text, is_error):
        self.debug_drawer.append_output(text, is_error)

    def on_execution_finish(self, exit_code):
        msg = f"\n> Process finished with exit code {exit_code}"
        self.debug_drawer.append_output(msg, is_error=(exit_code != 0))
        
        # Auto-retract on success (Exit Code 0)
        if exit_code == 0:
            # Maybe a small delay would be nice, but for now instant hide as per spec "auto-retracts"
            # Let's give it a slight delay so user sees "Finished"
            from PySide6.QtCore import QTimer
            QTimer.singleShot(2000, self.debug_drawer.hide)
            
    def handle_debug_output_to_chat(self, text):
        """Feeds debug output back to the AI context."""
        # We want to send this as a User message so the AI sees it as input
        # "Here is the output from the last run: ..."
        formatted_msg = f"Here is the output/error from the last run:\n\n{text}"
        self.chat_panel.chat_input.setText(formatted_msg) # Pre-fill input? 
        # Or auto-send? The spec says "Send to Agent" action feeds it back. 
        # Usually implies auto-send or at least put it in the chat.
        # Let's put it in the input box so user can add context? 
        # Or just append to chat history as a "System" message that AI can read?
        # Better: Treat it as a user message "I got this error: ..."
        
        # Let's pre-fill the input box so user can review or just hit enter.
        # self.chat_panel.chat_input.setText(formatted_msg)
        
        # Actually, "Send to Agent" usually implies immediate action.
        # Let's inject it as a message from "System" or "User" that gets processed.
        # But we need to be careful about loops.
        # Let's just add it to the chat history as "Run Output" and let user prompt?
        # The spec says "User: 'Write script' -> AI writes -> User Runs -> Error -> 'Send to Agent' -> AI analyzes"
        # So it should probably trigger a response.
        
        # self.chat_panel.add_message("User", formatted_msg) # send_worker adds it
        self.chat_panel.send_worker(formatted_msg, is_automated=False)

    def select_project_folder(self):
        from PySide6.QtWidgets import QFileDialog
        start_dir = self.settings_manager.get_last_project_path() or os.getcwd()
        folder = QFileDialog.getExistingDirectory(self, "Select Project Root", start_dir)
        if folder:
            self.project_path = folder
            self.settings_manager.set_last_project_path(folder)
            
            # 1. Update File Tree
            self.tree_panel.set_root_path(folder)
            
            # 2. Update System CWD & project root (Access for AI/Runner)
            os.chdir(folder)
            set_project_root(folder)

            # 3. Visual Feedback
            self.setWindowTitle(f"VoxAI Coding Agent IDE - {folder}")
            self.chat_panel.add_message("System", f"Switched project to: {folder}")

    def create_global_toolbar(self):
        # Top-level container
        self.toolbar_widget = QWidget()
        self.toolbar_widget.setStyleSheet("background-color: #2D2D30; border-bottom: 1px solid #3E3E42;")
        self.toolbar_widget.setFixedHeight(50)
        
        layout = QHBoxLayout(self.toolbar_widget)
        layout.setContentsMargins(10, 5, 10, 5)
        
        layout.addStretch() # Left Spacer
        
        # --- AI Controls ---
        self.model_combo = QComboBox()
        self.model_combo.setFixedWidth(200)
        self.refresh_models()
        # ...
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        layout.addWidget(self.model_combo)
        
        # Settings Button
        self.settings_btn = QPushButton("⚙️")
        self.settings_btn.setFixedWidth(30)
        self.settings_btn.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_btn)
        
        # Spacer between AI and Run controls
        layout.addSpacing(10)
        
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("border-left: 1px solid #555;")
        layout.addWidget(line)
        
        layout.addSpacing(10)
        
        # --- Center: Run Controls ---
        
        self.run_btn = QPushButton("▶ Run Script")
        self.run_btn.setStyleSheet("background-color: #4CAF50; color: white; border: none; padding: 6px 12px; border-radius: 4px; font-weight: bold;")
        self.run_btn.clicked.connect(self.editor_panel.request_run)
        layout.addWidget(self.run_btn)
        
        # self.config_btn = QPushButton("⚙ Run Config")
        # layout.addWidget(self.config_btn)
        
        layout.addStretch() # Right Spacer

    def refresh_models(self):
        """Reloads the model list from settings."""
        current = self.model_combo.currentText()
        if not current:
            current = self.settings_manager.get_selected_model()
            
        self.model_combo.clear()
        models = self.settings_manager.get_enabled_models()
        
        for m in models:
            self.model_combo.addItem(m)
            
        # Restore selection
        index = self.model_combo.findText(current)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)
        else:
             # Default to first
             if self.model_combo.count() > 0:
                 self.model_combo.setCurrentIndex(0)

    def on_model_changed(self, text):
        if text:
            self.settings_manager.set_selected_model(text)
            print(f"[Main] Model switched to: {text}")

    def open_settings(self):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        if dlg.exec():
            # Settings saved
            self.refresh_models()

        self.config_btn.setStyleSheet("""
            QPushButton {
                background-color: #3E3E42; 
                color: white; 
                border: 1px solid #555;
                padding: 6px 15px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #505050; }
        """)
        self.config_btn.clicked.connect(self.editor_panel.open_run_config)
        layout.addWidget(self.config_btn)
        
        layout.addStretch() # Right Spacer
        
        # Placeholder to balance layout if needed
        # layout.addWidget(QWidget()) 

    def refresh_models(self):
        models = self.settings_manager.get_custom_models()
        self.model_combo.clear()
        self.model_combo.addItems(models)
        
        current = self.settings_manager.get_selected_model()
        index = self.model_combo.findText(current)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)

    def on_model_changed(self, text):
        if text:
            self.settings_manager.set_selected_model(text)

    def open_settings(self):
        from ui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self)
        if dialog.exec():
            self.refresh_models()

    def create_menu_bar(self):
        menu_bar = self.menuBar()
        
        # --- File Menu ---
        file_menu = menu_bar.addMenu("&File")
        
        new_proj_action = file_menu.addAction("New/Open Project Folder")
        new_proj_action.triggered.connect(self.select_project_folder)
        
        file_menu.addSeparator()
        
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)
        
        # --- Edit Menu ---
        edit_menu = menu_bar.addMenu("&Edit")
        
        # --- Options/System Menu ---
        options_menu = menu_bar.addMenu("&Options")
        
        # Re-using the same slots
        settings_action = options_menu.addAction("Settings")
        settings_action.triggered.connect(self.open_settings)
        
        run_config_action = options_menu.addAction("Run Configuration")
        run_config_action.triggered.connect(self.editor_panel.open_run_config)

    def handle_chat_message(self, text):
        # Log message or perform other main-window side effects if needed
        pass

    def closeEvent(self, event):
        # Clean up Runner
        if self.runner and self.runner.process.state() != QProcess.ProcessState.NotRunning:
            print("[Main] Killing running process before exit...")
            self.runner.process.kill()
            self.runner.process.waitForFinished(1000)
            
        # Clean up Chat Panel threads
        self.chat_panel.close()
        
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CodingAgentIDE()
    window.show()
    sys.exit(app.exec())
