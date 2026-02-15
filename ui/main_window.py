
import os
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QSplitter,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QFrame,
    QFileDialog,
    QMessageBox,
)
from PySide6.QtCore import Qt

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

        # Panels
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
        self.debug_drawer.setStyleSheet(
            "border-left: 1px solid #3E3E42; background-color: #1E1E1E;"
        )
        self.debug_drawer.send_to_agent.connect(self.handle_debug_output_to_chat)

        # Toolbar
        self.create_global_toolbar()
        main_layout.addWidget(self.toolbar_widget)

        # Main Splitter (Below Toolbar)
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
        self.main_splitter.setSizes([300, 900])
        self.right_splitter.setSizes([600, 200])

        # Menu Bar
        self.create_menu_bar()

        # Project selection
        self.select_project_folder()
        if not self.project_path:
            self.project_path = os.getcwd()
            self.tree_panel.set_root_path(self.project_path)
            self.settings_manager.set_last_project_path(self.project_path)

        set_project_root(self.project_path)

        # Make sure model combo has something selected/displayed
        self.refresh_models()

    # ------------------------------------------------------------------
    # Window/layout
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        drawer_width = 450
        toolbar_height = (
            self.toolbar_widget.height() if hasattr(self, "toolbar_widget") else 50
        )

        self.debug_drawer.setGeometry(
            self.width() - drawer_width,
            toolbar_height + self.menuBar().height(),
            drawer_width,
            self.height() - toolbar_height - self.menuBar().height(),
        )
        self.debug_drawer.raise_()

    # ------------------------------------------------------------------
    # Runner hooks
    # ------------------------------------------------------------------
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

        if exit_code == 0:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(2000, self.debug_drawer.hide)

    def handle_debug_output_to_chat(self, text):
        formatted_msg = f"Here is the output/error from the last run:\n\n{text}"
        self.chat_panel.send_worker(formatted_msg, is_automated=False)

    # ------------------------------------------------------------------
    # AI callbacks
    # ------------------------------------------------------------------
    def on_file_updated(self, file_path):
        print(f"[Main] AI updated file: {file_path}")
        self.editor_panel.load_file(file_path)
        self.tree_panel.refresh()
        self.debug_drawer.append_output(f"> AI updated: {os.path.basename(file_path)}")

    def on_code_generated(self, language, code):
        self.debug_drawer.append_output(
            f"> AI generated snippet ({language}). Check chat for details."
        )

    # ------------------------------------------------------------------
    # Project selection
    # ------------------------------------------------------------------
    def select_project_folder(self):
        start_dir = self.settings_manager.get_last_project_path() or os.getcwd()
        folder = QFileDialog.getExistingDirectory(self, "Select Project Root", start_dir)
        if folder:
            self.project_path = folder
            self.settings_manager.set_last_project_path(folder)

            self.tree_panel.set_root_path(folder)
            os.chdir(folder)
            set_project_root(folder)

            self.setWindowTitle(f"VoxAI Coding Agent IDE - {folder}")
            self.chat_panel.clear_context()
            self.chat_panel.add_message("System", f"Switched project to: {folder}")

    def select_project_folder_from_menu(self):
        self.select_project_folder()

    # ------------------------------------------------------------------
    # Toolbar / model selection
    # ------------------------------------------------------------------
    def create_global_toolbar(self):
        self.toolbar_widget = QWidget()
        self.toolbar_widget.setStyleSheet(
            "background-color: #2D2D30; border-bottom: 1px solid #3E3E42;"
        )
        self.toolbar_widget.setFixedHeight(50)

        layout = QHBoxLayout(self.toolbar_widget)
        layout.setContentsMargins(10, 5, 10, 5)

        layout.addStretch()

        # Model combo
        self.model_combo = QComboBox()
        self.model_combo.setFixedWidth(260)
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        layout.addWidget(self.model_combo)

        # Settings button
        self.settings_btn = QPushButton("⚙️")
        self.settings_btn.setFixedWidth(34)
        self.settings_btn.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_btn)

        layout.addSpacing(10)

        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("border-left: 1px solid #555;")
        layout.addWidget(line)

        layout.addSpacing(10)

        self.run_btn = QPushButton("▶ Run Script")
        self.run_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; border: none; padding: 6px 12px; "
            "border-radius: 4px; font-weight: bold;"
        )
        self.run_btn.clicked.connect(self.editor_panel.request_run)
        layout.addWidget(self.run_btn)

        layout.addStretch()

    def refresh_models(self):
        """Reloads the model list from settings, ensuring there's at least one selectable model."""
        current = (
            self.model_combo.currentText().strip() if self.model_combo.count() else ""
        )
        if not current:
            current = (self.settings_manager.get_selected_model() or "").strip()

        models = self.settings_manager.get_enabled_models() or []
        models = [m for m in models if isinstance(m, str) and m.strip()]

        # If user hasn't selected any models yet, provide a safe default so the app "works".
        if not models:
            models = ["[OpenRouter] openrouter/auto"]

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in models:
            self.model_combo.addItem(m)
        self.model_combo.blockSignals(False)

        # Restore selection
        idx = self.model_combo.findText(current)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        else:
            # Default to first model and persist it as selected
            if self.model_combo.count() > 0:
                self.model_combo.setCurrentIndex(0)
                self.settings_manager.set_selected_model(self.model_combo.currentText())

    def on_model_changed(self, text):
        if text and text.strip():
            self.settings_manager.set_selected_model(text.strip())
            print(f"[Main] Model switched to: {text.strip()}")

    def open_settings(self):
        from ui.settings_dialog import SettingsDialog

        dlg = SettingsDialog(self)
        if dlg.exec():
            self.refresh_models()

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------
    def create_menu_bar(self):
        menu = self.menuBar()
        menu.setNativeMenuBar(False)

        # File
        file_menu = menu.addMenu("&File")

        act_open_project = file_menu.addAction("Open Project…")
        act_open_project.setShortcut("Ctrl+Shift+O")
        act_open_project.triggered.connect(self.select_project_folder_from_menu)

        act_open_file = file_menu.addAction("Open File…")
        act_open_file.setShortcut("Ctrl+O")
        act_open_file.triggered.connect(self.open_file_dialog)

        file_menu.addSeparator()

        act_save = file_menu.addAction("Save")
        act_save.setShortcut("Ctrl+S")
        act_save.triggered.connect(self.save_current_file)

        act_save_as = file_menu.addAction("Save As…")
        act_save_as.setShortcut("Ctrl+Shift+S")
        act_save_as.triggered.connect(self.save_current_file_as)

        file_menu.addSeparator()

        act_exit = file_menu.addAction("Exit")
        act_exit.setShortcut("Alt+F4")
        act_exit.triggered.connect(self.close)

    def closeEvent(self, event):
        """Cleanup on IDE shutdown."""
        super().closeEvent(event)

        # Edit
        edit_menu = menu.addMenu("&Edit")

        act_undo = edit_menu.addAction("Undo")
        act_undo.setShortcut("Ctrl+Z")
        act_undo.triggered.connect(lambda: self._editor_action("undo"))

        act_redo = edit_menu.addAction("Redo")
        act_redo.setShortcut("Ctrl+Y")
        act_redo.triggered.connect(lambda: self._editor_action("redo"))

        edit_menu.addSeparator()

        act_cut = edit_menu.addAction("Cut")
        act_cut.setShortcut("Ctrl+X")
        act_cut.triggered.connect(lambda: self._editor_action("cut"))

        act_copy = edit_menu.addAction("Copy")
        act_copy.setShortcut("Ctrl+C")
        act_copy.triggered.connect(lambda: self._editor_action("copy"))

        act_paste = edit_menu.addAction("Paste")
        act_paste.setShortcut("Ctrl+V")
        act_paste.triggered.connect(lambda: self._editor_action("paste"))

        edit_menu.addSeparator()

        act_select_all = edit_menu.addAction("Select All")
        act_select_all.setShortcut("Ctrl+A")
        act_select_all.triggered.connect(lambda: self._editor_action("selectAll"))

        # Options
        options_menu = menu.addMenu("&Options")

        act_settings = options_menu.addAction("Settings…")
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self.open_settings)

        # Help
        help_menu = menu.addMenu("&Help")
        act_about = help_menu.addAction("About")
        act_about.triggered.connect(self.show_about)

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------
    def _current_editor(self):
        return getattr(self.editor_panel.tabs, "currentWidget", lambda: None)()

    def _editor_action(self, action_name: str):
        ed = self._current_editor()
        if ed is None:
            return
        fn = getattr(ed, action_name, None)
        if callable(fn):
            fn()

    def open_file_dialog(self):
        start_dir = self.project_path or os.getcwd()
        file_path, _ = QFileDialog.getOpenFileName(self, "Open File", start_dir, "All Files (*.*)")
        if file_path:
            self.editor_panel.load_file(file_path)

    def save_current_file(self):
        ed = self._current_editor()
        if ed is None:
            return

        path = getattr(ed, "file_path", None)
        if not path:
            self.save_current_file_as()
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(ed.toPlainText())
            self.statusBar().showMessage(f"Saved: {path}", 2500)
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Could not save file:\n{e}")

    def save_current_file_as(self):
        ed = self._current_editor()
        if ed is None:
            return

        start_dir = self.project_path or os.getcwd()
        file_path, _ = QFileDialog.getSaveFileName(self, "Save File As", start_dir, "All Files (*.*)")
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(ed.toPlainText())
            ed.file_path = file_path
            # Update tab title
            idx = self.editor_panel.tabs.currentIndex()
            if idx >= 0:
                self.editor_panel.tabs.setTabText(idx, os.path.basename(file_path))
            self.tree_panel.refresh()
            self.statusBar().showMessage(f"Saved: {file_path}", 2500)
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Could not save file:\n{e}")

    def show_about(self):
        QMessageBox.information(
            self,
            "About VoxAI Coding Agent IDE",
            "VoxAI Coding Agent IDE\n\nLocal-first autonomous coding agent with native subprocess execution.",
        )

    # ------------------------------------------------------------------
    # Chat hook placeholders
    # ------------------------------------------------------------------
    def handle_chat_message(self, message: str):
        """
        ChatPanel already triggers AI via its own send flow; this is kept as a hook
        for legacy wiring.
        """
        pass
