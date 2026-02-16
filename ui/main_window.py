
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
    QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QColor

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
        
        # Set Icon
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "Emblem.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # -----------------------------------------------------------------------
        # Global Modern Dark Theme (Cursor-like)
        # -----------------------------------------------------------------------
        # -----------------------------------------------------------------------
        # Global Modern Dark Theme (Electric Blue / Neon Orange)
        # -----------------------------------------------------------------------
        self.setStyleSheet("""
            QMainWindow {
                background-color: #18181b;  /* Zinc-950 */
                color: #e4e4e7;             /* Zinc-200 */
            }
            QWidget {
                font-family: 'Segoe UI', 'Inter', sans-serif;
                font-size: 13px;
                color: #e4e4e7;
            }
            
            /* --- Scrollbars (Visible & Polished) --- */
            QScrollBar:vertical {
                border: none;
                background: #18181b;
                width: 12px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #3f3f46;
                min-height: 20px;
                border-radius: 6px;
                margin: 2px;
                border: 1px solid #27272a;
            }
            QScrollBar::handle:vertical:hover { background: #52525b; border-color: #00f3ff; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            
            QScrollBar:horizontal {
                border: none;
                background: #18181b;
                height: 12px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #3f3f46;
                min-width: 20px;
                border-radius: 6px;
                margin: 2px;
                border: 1px solid #27272a;
            }
            QScrollBar::handle:horizontal:hover { background: #52525b; border-color: #00f3ff; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
            
            /* --- Splitters (Highly Visible) --- */
            QSplitter::handle {
                background-color: #3f3f46; /* Zinc-700 */
                height: 6px; /* Much thicker handles */
                width: 6px;
            }
            QSplitter::handle:horizontal {
                width: 6px;
                image: url(:/images/splitter_grip_v.png); /* Optional grip hint if we had one */
            }
            QSplitter::handle:vertical {
                height: 6px;
            }
            QSplitter::handle:hover {
                background-color: #ff9900; /* Neon Orange highlight */
            }
            QSplitter::handle:pressed {
                background-color: #00f3ff; /* Electric Blue active */
            }

            /* --- Tooltips --- */
            QToolTip {
                background-color: #27272a;
                color: #e4e4e7;
                border: 1px solid #00f3ff;
                padding: 4px;
                border-radius: 4px;
            }
            
            /* --- Menus --- */
            QMenuBar {
                background-color: #18181b;
                color: #e4e4e7;
                border-bottom: 1px solid #27272a;
            }
            QMenuBar::item {
                background: transparent;
                padding: 8px 12px;
            }
            QMenuBar::item:selected {
                background-color: #27272a;
                border-bottom: 2px solid #00f3ff;
            }
            QMenu {
                background-color: #18181b;
                border: 1px solid #3f3f46;
                padding: 5px;
            }
            QMenu::item {
                padding: 6px 24px 6px 12px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #27272a; 
                color: #00f3ff; /* Electric Blue Text */
                border: 1px solid #00f3ff;
            }
            QMenu::separator {
                height: 1px;
                background: #3f3f46;
                margin: 4px 0;
            }
            
            /* --- Lists & Trees (Cleaner) --- */
            QTreeView, QListView {
                background-color: #1c1c1f; /* Slightly lighter than main bg */
                border: none;
                outline: none;
            }
            QTreeView::item, QListView::item {
                padding: 6px; /* More breathing room */
                border-radius: 4px;
                margin-bottom: 2px;
            }
            QTreeView::item:hover, QListView::item:hover {
                background-color: #2a2a2d;
            }
            QTreeView::item:selected, QListView::item:selected {
                background-color: #2f2f35;
                color: #00f3ff; /* Neon Blue */
                border-left: 2px solid #00f3ff;
            }
        """)

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
    # ------------------------------------------------------------------
    # Runner hooks
    # ------------------------------------------------------------------
    def select_and_run_script(self):
        """Opens a file dialog to select a script, then runs it."""
        last_dir = self.settings_manager.get_last_project_path() or os.getcwd()
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Script to Run", last_dir, "All Files (*.*);;Python (*.py);;Batch (*.bat);;Shell (*.sh)"
        )
        if path:
            self.run_script(path)

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
        
        # Toolbar items
        self.run_btn = QPushButton("Run Script")
        self.run_btn.setFixedSize(140, 32)
        self.run_btn.setStyleSheet("""
            QPushButton {
                background-color: #18181b; 
                color: #ff9900; 
                border: 1px solid #ff9900; 
                border-radius: 4px; 
                font-weight: 900;
                font-family: 'Consolas', monospace;
                text-transform: uppercase;
                letter-spacing: 1px;
                padding: 0 10px;
            }
            QPushButton:hover { 
                background-color: #27272a; 
                color: #00f3ff;
                border-color: #00f3ff;
            }
        """)
        
        # Adding the Neon Glow (Drop Shadow)
        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(15)
        glow.setOffset(0, 0)
        glow.setColor(QColor("#00f3ff")) # Neon Blue Glow
        self.run_btn.setGraphicsEffect(glow)
        self.run_btn.clicked.connect(self.select_and_run_script)
        layout.addWidget(self.run_btn)
        
        layout.addStretch()


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
        act_exit.setShortcut("Alt+F4")
        act_exit.triggered.connect(self.close)

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

    def closeEvent(self, event):
        """Cleanup on IDE shutdown."""
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------
    def _editor_action(self, action_name: str):
        ed = self._current_editor()
        if ed is None:
            return
        fn = getattr(ed, action_name, None)
        if callable(fn):
            fn()

    def _current_editor(self):
        if hasattr(self.editor_panel, "tabs"):
            return self.editor_panel.tabs.currentWidget()
        return None

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
