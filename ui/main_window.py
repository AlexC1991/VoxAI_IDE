import os
import sys
import json
import subprocess
import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter, QHBoxLayout,
    QPushButton, QFileDialog, QMessageBox,
    QGraphicsDropShadowEffect, QSystemTrayIcon, QStatusBar,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QDialog,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QColor, QKeySequence, QShortcut

from ui.chat_panel import ChatPanel
from ui.editor_panel import EditorPanel
from ui.file_tree_panel import FileTreePanel
from ui.debug_drawer import DebugDrawer
from ui.search_panel import SearchPanel
from ui.history_sidebar import HistorySidebar
from ui.file_switcher import FileSwitcher
from ui.code_outline import CodeOutline
from core.runner import Runner
from core.agent_tools import set_project_root, get_resource_path

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Command Palette
# ---------------------------------------------------------------------------
class CommandPalette(QDialog):
    """Ctrl+Shift+P quick-action launcher."""

    def __init__(self, commands: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Command Palette")
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setFixedSize(500, 340)
        self.setStyleSheet(
            "QDialog { background: #1e1e1e; border: 1px solid #00f3ff; "
            "border-radius: 8px; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command…")
        self._input.setStyleSheet(
            "background: #27272a; color: #e4e4e7; border: 1px solid #3f3f46; "
            "border-radius: 4px; padding: 8px; font-size: 13px; "
            "font-family: 'Consolas', monospace;")
        self._input.textChanged.connect(self._filter)
        lay.addWidget(self._input)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background: #18181b; border: none; color: #e4e4e7; "
            "font-family: 'Consolas', monospace; font-size: 12px; }"
            "QListWidget::item { padding: 8px; border-radius: 4px; }"
            "QListWidget::item:selected { background: #27272a; color: #00f3ff; }"
            "QListWidget::item:hover { background: #232326; }")
        self._list.itemActivated.connect(self._run)
        lay.addWidget(self._list)

        self._commands = commands
        for name, _ in commands:
            self._list.addItem(name)

        self._input.setFocus()

    def _filter(self, text):
        text_lower = text.lower()
        self._list.clear()
        for name, _ in self._commands:
            if text_lower in name.lower():
                self._list.addItem(name)

    def _run(self, item: QListWidgetItem):
        text = item.text()
        for name, fn in self._commands:
            if name == text:
                self.accept()
                fn()
                return


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------
class CodingAgentIDE(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VoxAI Coding Agent IDE")
        self.resize(1200, 800)

        icon_path = get_resource_path(os.path.join("resources", "Emblem.png"))
        app_icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        # System tray
        self._tray = QSystemTrayIcon(app_icon, self)
        self._tray.setToolTip("VoxAI Coding Agent IDE")
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        # Terminal mode subprocess handle
        self._terminal_proc: subprocess.Popen | None = None

        self.setStyleSheet(_GLOBAL_STYLE)

        from core.settings import SettingsManager
        self.settings_manager = SettingsManager()

        self.project_path = None
        self.runner = Runner()
        self.runner.output_received.connect(self.on_process_output)
        self.runner.execution_started.connect(self.on_execution_start)
        self.runner.execution_finished.connect(self.on_execution_finish)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Panels
        self.chat_panel = ChatPanel()
        self.chat_panel.message_sent.connect(self.handle_chat_message)
        self.chat_panel.code_generated.connect(self.on_code_generated)
        self.chat_panel.file_updated.connect(self.on_file_updated)
        self.chat_panel.diff_ready.connect(self.on_diff_generated)
        self.chat_panel.notification_requested.connect(self._show_notification)
        self.chat_panel.token_usage_updated.connect(self.update_token_count)

        self.editor_panel = EditorPanel()
        self.editor_panel.run_requested.connect(self.run_script)
        self.editor_panel.tabs.currentChanged.connect(self._on_editor_tab_changed)

        # Give the chat panel access to the active editor context
        self.chat_panel._editor_context_getter = self.editor_panel.get_active_context

        self.tree_panel = FileTreePanel(start_path=self.project_path)
        self.tree_panel.file_double_clicked.connect(self.editor_panel.load_file)
        self.tree_panel.file_created.connect(self.editor_panel.load_file)
        self.tree_panel.file_deleted.connect(lambda p: self.tree_panel.refresh())
        self.tree_panel.file_renamed.connect(
            lambda old, new: (self.tree_panel.refresh(),
                              self.editor_panel.load_file(new)))
        self.tree_panel.git_diff_requested.connect(self._show_git_diff)

        self.debug_drawer = DebugDrawer(self)
        self.debug_drawer.hide()
        self.debug_drawer.setStyleSheet(
            "border-left: 1px solid #3E3E42; background-color: #1E1E1E;")
        self.debug_drawer.send_to_agent.connect(self.handle_debug_output_to_chat)

        # Project-wide search
        self.search_panel = SearchPanel(self)
        self.search_panel.file_requested.connect(self._open_search_result)

        # Code outline sidebar
        self.code_outline = CodeOutline(self)
        self.code_outline.line_requested.connect(self._goto_line)

        # Conversation history sidebar
        self.history_sidebar = HistorySidebar(self)
        self.history_sidebar.conversation_selected.connect(
            self.chat_panel.switch_conversation)
        self.history_sidebar.new_conversation.connect(
            self.chat_panel.clear_context)
        self.chat_panel.conversation_changed.connect(self._refresh_history)

        # Toolbar
        self.create_global_toolbar()
        main_layout.addWidget(self.toolbar_widget)

        # Splitters
        self.main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.main_splitter)

        # Left pane: history sidebar + chat
        self.left_splitter = QSplitter(Qt.Horizontal)
        self.left_splitter.addWidget(self.history_sidebar)
        self.left_splitter.addWidget(self.chat_panel)
        self.left_splitter.setSizes([0, 300])
        self.main_splitter.addWidget(self.left_splitter)

        self.right_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.addWidget(self.right_splitter)
        self.right_splitter.addWidget(self.editor_panel)
        self.right_splitter.addWidget(self.search_panel)

        # Bottom right: file tree + code outline side by side
        self.bottom_right = QSplitter(Qt.Horizontal)
        self.bottom_right.addWidget(self.tree_panel)
        self.bottom_right.addWidget(self.code_outline)
        self.bottom_right.setSizes([300, 0])
        self.right_splitter.addWidget(self.bottom_right)

        self.main_splitter.setSizes([300, 900])
        self.right_splitter.setSizes([500, 0, 200])

        # Status bar
        self._setup_status_bar()

        # Menu
        self.create_menu_bar()

        # Keyboard shortcuts
        QShortcut(QKeySequence("Ctrl+Shift+P"), self).activated.connect(
            self._open_command_palette)
        QShortcut(QKeySequence("Ctrl+`"), self).activated.connect(
            self._toggle_debug_drawer)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self).activated.connect(
            self._toggle_search_panel)
        QShortcut(QKeySequence("Ctrl+H"), self).activated.connect(
            self._toggle_history_sidebar)
        QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(
            self._open_file_switcher)
        QShortcut(QKeySequence("Ctrl+Shift+L"), self).activated.connect(
            self._toggle_code_outline)

        # Project selection
        self.select_project_folder()
        if not self.project_path:
            self.project_path = os.getcwd()
            self.tree_panel.set_root_path(self.project_path)
            self.settings_manager.set_last_project_path(self.project_path)
        set_project_root(self.project_path)
        self.search_panel.set_root(self.project_path)

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------
    def _setup_status_bar(self):
        sb = QStatusBar()
        sb.setStyleSheet(
            "QStatusBar { background: #18181b; color: #a1a1aa; "
            "border-top: 1px solid #27272a; font-family: 'Consolas', monospace; "
            "font-size: 11px; }"
            "QStatusBar::item { border: none; }")
        self.setStatusBar(sb)

        self._status_branch = QLabel("branch: —")
        self._status_branch.setStyleSheet("color: #a1a1aa; padding: 0 12px;")
        sb.addWidget(self._status_branch)

        self._status_cursor = QLabel("Ln 1, Col 1")
        self._status_cursor.setStyleSheet("color: #a1a1aa; padding: 0 12px;")
        sb.addPermanentWidget(self._status_cursor)

        self._status_encoding = QLabel("UTF-8")
        self._status_encoding.setStyleSheet("color: #a1a1aa; padding: 0 12px;")
        sb.addPermanentWidget(self._status_encoding)

        # Token usage context bar
        from PySide6.QtWidgets import QProgressBar
        self._token_bar = QProgressBar()
        self._token_bar.setFixedWidth(120)
        self._token_bar.setFixedHeight(14)
        self._token_bar.setRange(0, 100)
        self._token_bar.setValue(0)
        self._token_bar.setFormat("")
        self._token_bar.setStyleSheet(
            "QProgressBar { background: #27272a; border: 1px solid #3f3f46; border-radius: 3px; }"
            "QProgressBar::chunk { background: #00f3ff; border-radius: 2px; }")
        sb.addPermanentWidget(self._token_bar)

        self._status_tokens = QLabel("0 / 24K tok")
        self._status_tokens.setStyleSheet("color: #00f3ff; padding: 0 8px; font-size: 11px;")
        sb.addPermanentWidget(self._status_tokens)

        # Periodic git branch refresh
        self._branch_timer = QTimer(self)
        self._branch_timer.timeout.connect(self._refresh_branch)
        self._branch_timer.start(5000)

        # Cursor position tracking
        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._refresh_cursor_pos)
        self._cursor_timer.start(200)

    def _refresh_branch(self):
        if not self.project_path:
            return
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.project_path, capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                self._status_branch.setText(f"branch: {r.stdout.strip()}")
        except Exception:
            pass

    def _refresh_cursor_pos(self):
        editor = self.editor_panel.tabs.currentWidget()
        if editor and hasattr(editor, 'textCursor'):
            cursor = editor.textCursor()
            line = cursor.blockNumber() + 1
            col = cursor.columnNumber() + 1
            self._status_cursor.setText(f"Ln {line}, Col {col}")

    def update_token_count(self, count: int):
        max_tok = self.settings_manager.get_max_history_tokens()
        pct = min(100, int(count / max(max_tok, 1) * 100))
        self._token_bar.setValue(pct)

        if pct < 50:
            color = "#00f3ff"
        elif pct < 80:
            color = "#e5c07b"
        else:
            color = "#ef4444"
        self._token_bar.setStyleSheet(
            f"QProgressBar {{ background: #27272a; border: 1px solid #3f3f46; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 2px; }}")

        if count >= 1000:
            disp = f"{count/1000:.1f}K"
        else:
            disp = str(count)
        max_disp = f"{max_tok/1000:.0f}K"
        self._status_tokens.setText(f"{disp} / {max_disp} tok")
        self._status_tokens.setStyleSheet(f"color: {color}; padding: 0 8px; font-size: 11px;")

    # ------------------------------------------------------------------
    # Command Palette
    # ------------------------------------------------------------------
    def _open_command_palette(self):
        commands = [
            ("Open Project…", self.select_project_folder_from_menu),
            ("Open File…", self.open_file_dialog),
            ("Save File", self.save_current_file),
            ("Save File As…", self.save_current_file_as),
            ("Run Script…", self.select_and_run_script),
            ("Settings…", self.open_settings),
            ("Toggle Debug Panel", self._toggle_debug_drawer),
            ("Search in Project  (Ctrl+Shift+F)", self._toggle_search_panel),
            ("Conversation History  (Ctrl+H)", self._toggle_history_sidebar),
            ("Go to File  (Ctrl+P)", self._open_file_switcher),
            ("Code Outline  (Ctrl+Shift+L)", self._toggle_code_outline),
            ("Find & Replace", self.editor_panel._toggle_find),
            ("Clear Chat Context", self.chat_panel.clear_context),
            ("Export Conversation…", self._export_conversation),
            ("Terminal Mode", self._enter_terminal_mode),
            ("About", self.show_about),
        ]
        palette = CommandPalette(commands, self)
        palette.move(
            self.x() + (self.width() - palette.width()) // 2,
            self.y() + 80)
        palette.exec()

    def _toggle_debug_drawer(self):
        self.debug_drawer.setVisible(not self.debug_drawer.isVisible())

    # ------------------------------------------------------------------
    # Project-wide search
    # ------------------------------------------------------------------
    def _toggle_search_panel(self):
        self.search_panel.toggle()
        if self.search_panel.isVisible():
            sizes = self.right_splitter.sizes()
            if sizes[1] < 120:
                sizes[1] = 250
                sizes[0] = max(sizes[0] - 250, 200)
                self.right_splitter.setSizes(sizes)

    def _open_search_result(self, path: str, line: int):
        self.editor_panel.load_file(path)
        editor = self.editor_panel.tabs.currentWidget()
        if editor and hasattr(editor, 'textCursor'):
            from PySide6.QtGui import QTextCursor
            block = editor.document().findBlockByLineNumber(line - 1)
            cursor = editor.textCursor()
            cursor.setPosition(block.position())
            editor.setTextCursor(cursor)
            editor.centerCursor()

    # ------------------------------------------------------------------
    # Conversation history sidebar
    # ------------------------------------------------------------------
    def _toggle_history_sidebar(self):
        self.history_sidebar.toggle()
        if self.history_sidebar.isVisible():
            sizes = self.left_splitter.sizes()
            if sizes[0] < 120:
                self.left_splitter.setSizes([200, max(sizes[1], 200)])
            self._refresh_history()

    def _refresh_history(self):
        convos = self.chat_panel.list_conversations()
        self.history_sidebar.refresh(convos, self.chat_panel.conversation_id)

    # ------------------------------------------------------------------
    # Code outline
    # ------------------------------------------------------------------
    def _toggle_code_outline(self):
        self.code_outline.toggle()
        if self.code_outline.isVisible():
            sizes = self.bottom_right.sizes()
            if sizes[1] < 100:
                self.bottom_right.setSizes([sizes[0], 200])
            self._refresh_outline()

    def _on_editor_tab_changed(self, index):
        if self.code_outline.isVisible():
            self._refresh_outline()

    def _refresh_outline(self):
        editor = self.editor_panel.tabs.currentWidget()
        if editor and hasattr(editor, 'file_path') and hasattr(editor, 'toPlainText'):
            self.code_outline.update_outline(
                getattr(editor, 'file_path', '') or '',
                editor.toPlainText())

    def _goto_line(self, line: int):
        editor = self.editor_panel.tabs.currentWidget()
        if editor and hasattr(editor, 'textCursor'):
            from PySide6.QtGui import QTextCursor
            block = editor.document().findBlockByLineNumber(line - 1)
            cursor = editor.textCursor()
            cursor.setPosition(block.position())
            editor.setTextCursor(cursor)
            editor.centerCursor()

    # ------------------------------------------------------------------
    # Quick file switcher (Ctrl+P)
    # ------------------------------------------------------------------
    def _open_file_switcher(self):
        dlg = FileSwitcher(self.project_path or os.getcwd(), self)
        dlg.file_selected.connect(self.editor_panel.load_file)
        # Center on parent
        geo = self.geometry()
        dlg.move(geo.center().x() - dlg.width() // 2,
                 geo.top() + 80)
        dlg.show()
        dlg.input.setFocus()

    # ------------------------------------------------------------------
    # Interactive git diff viewer
    # ------------------------------------------------------------------
    def _show_git_diff(self, file_path: str):
        """Run git diff on a file and display the result in an editor tab."""
        root = self.project_path or os.getcwd()
        try:
            # Try staged + unstaged combined view
            result = subprocess.run(
                ["git", "diff", "HEAD", "--", file_path],
                cwd=root, capture_output=True, text=True, timeout=5)
            diff_text = result.stdout.strip()
            if not diff_text:
                # Might be untracked — show full file as addition
                result = subprocess.run(
                    ["git", "diff", "--no-index", os.devnull, file_path],
                    cwd=root, capture_output=True, text=True, timeout=5)
                diff_text = result.stdout.strip()
            if not diff_text:
                diff_text = "(No differences found)"
            self.editor_panel.show_diff(file_path, diff_text)
        except Exception as e:
            log.error("Git diff failed for %s: %s", file_path, e)

    # ------------------------------------------------------------------
    # Desktop notifications
    # ------------------------------------------------------------------
    def _show_notification(self, title: str, message: str):
        if self.isActiveWindow():
            return
        if self._tray.isSystemTrayAvailable():
            self._tray.showMessage(title, message,
                                   QSystemTrayIcon.Information, 5000)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._kill_terminal()
            self.showNormal()
            self.activateWindow()
            self.raise_()

    # ------------------------------------------------------------------
    # Terminal Mode
    # ------------------------------------------------------------------
    def _enter_terminal_mode(self):
        """Hide GUI, save context, launch CLI terminal in a real console."""
        self.chat_panel.save_conversation()

        conv_file = self.chat_panel._conversation_file()
        project_root = self.project_path or os.getcwd()
        model = self.chat_panel.model_combo.currentText()
        mode = self.chat_panel.mode_combo.currentText()

        cli_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "cli", "terminal_mode.py")

        if not os.path.exists(cli_script):
            QMessageBox.warning(self, "Terminal Mode",
                                "CLI module not found. Ensure cli/terminal_mode.py exists.")
            return

        args = [
            sys.executable, cli_script,
            "--project", project_root,
            "--conversation", conv_file,
            "--model", model,
            "--mode", mode,
        ]

        # subprocess.Popen with CREATE_NEW_CONSOLE gives the child its own
        # interactive cmd window with real stdin/stdout — QProcess can't do this.
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_CONSOLE
        try:
            self._terminal_proc = subprocess.Popen(args, creationflags=flags)
        except Exception as e:
            QMessageBox.critical(self, "Terminal Mode",
                                 f"Failed to launch terminal:\n{e}")
            return

        self.hide()
        self._tray.showMessage(
            "VoxAI Terminal Mode",
            "IDE minimized to tray. Double-click icon to return to GUI.",
            QSystemTrayIcon.Information, 3000)

        # Poll for process exit so we can restore the GUI
        self._terminal_poll = QTimer(self)
        self._terminal_poll.timeout.connect(self._poll_terminal)
        self._terminal_poll.start(500)

    def _poll_terminal(self):
        if self._terminal_proc is None:
            self._terminal_poll.stop()
            return
        rc = self._terminal_proc.poll()
        if rc is not None:
            self._terminal_poll.stop()
            self._terminal_proc = None
            self._on_terminal_exited()

    def _kill_terminal(self):
        if self._terminal_proc is not None:
            try:
                self._terminal_proc.terminate()
                self._terminal_proc.wait(timeout=3)
            except Exception:
                try:
                    self._terminal_proc.kill()
                except Exception:
                    pass
            self._terminal_proc = None
            if hasattr(self, '_terminal_poll'):
                self._terminal_poll.stop()

    def _on_terminal_exited(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()
        # Reload conversation written by the terminal session.
        # Clear first to avoid duplicating messages already in the UI.
        self.chat_panel.clear_context()
        self.chat_panel.load_conversation()
        log.info("Terminal mode exited — GUI restored")

    # ------------------------------------------------------------------
    # Export conversation
    # ------------------------------------------------------------------
    def _export_conversation(self):
        if not self.chat_panel.messages:
            QMessageBox.information(self, "Export", "No conversation to export.")
            return

        path, filt = QFileDialog.getSaveFileName(
            self, "Export Conversation",
            os.path.join(self.project_path or "", "conversation_export"),
            "Markdown (*.md);;JSON (*.json)")
        if not path:
            return

        try:
            if path.endswith('.json'):
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(self.chat_panel.messages, f,
                              ensure_ascii=False, indent=2)
            else:
                lines = []
                for m in self.chat_panel.messages:
                    role = m.get("role", "unknown").upper()
                    content = m.get("content", "")
                    lines.append(f"## {role}\n\n{content}\n\n---\n")
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(lines))
            self.statusBar().showMessage(f"Exported to {path}", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    # ------------------------------------------------------------------
    # Window layout
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        drawer_width = 450
        toolbar_height = (
            self.toolbar_widget.height() if hasattr(self, "toolbar_widget") else 50)
        self.debug_drawer.setGeometry(
            self.width() - drawer_width,
            toolbar_height + self.menuBar().height(),
            drawer_width,
            self.height() - toolbar_height - self.menuBar().height())
        self.debug_drawer.raise_()

    # ------------------------------------------------------------------
    # Runner hooks
    # ------------------------------------------------------------------
    def select_and_run_script(self):
        last_dir = self.settings_manager.get_last_project_path() or os.getcwd()
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Script to Run", last_dir,
            "All Files (*.*);;Python (*.py);;Batch (*.bat);;Shell (*.sh)")
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
            QTimer.singleShot(2000, self.debug_drawer.hide)

    def handle_debug_output_to_chat(self, text):
        self.chat_panel.send_worker(
            f"Here is the output/error from the last run:\n\n{text}",
            is_automated=False)

    # ------------------------------------------------------------------
    # AI callbacks
    # ------------------------------------------------------------------
    def on_file_updated(self, file_path):
        self.editor_panel.load_file(file_path)
        self.tree_panel.refresh()

    def on_diff_generated(self, file_path, diff_text):
        if not hasattr(self, '_pending_diffs'):
            self._pending_diffs = []
        self._pending_diffs.append((file_path, diff_text))
        self.debug_drawer.append_output(
            f"> AI updated: {os.path.basename(file_path)}")
        if not hasattr(self, '_diff_timer'):
            self._diff_timer = QTimer(self)
            self._diff_timer.setSingleShot(True)
            self._diff_timer.timeout.connect(self._flush_pending_diffs)
        self._diff_timer.start(200)

    def _flush_pending_diffs(self):
        diffs = getattr(self, '_pending_diffs', [])
        if not diffs:
            return
        if len(diffs) == 1:
            self.editor_panel.show_diff(*diffs[0])
        else:
            self.editor_panel.show_diffs_batch(diffs)
        self._pending_diffs = []

    def on_code_generated(self, language, code):
        self.debug_drawer.append_output(
            f"> AI generated snippet ({language}). Check chat for details.")

    # ------------------------------------------------------------------
    # Project selection
    # ------------------------------------------------------------------
    def select_project_folder(self):
        start_dir = self.settings_manager.get_last_project_path() or os.getcwd()
        folder = QFileDialog.getExistingDirectory(
            self, "Select Project Root", start_dir)
        if folder:
            self.project_path = folder
            self.settings_manager.set_last_project_path(folder)
            self.tree_panel.set_root_path(folder)
            os.chdir(folder)
            set_project_root(folder)
            self.search_panel.set_root(folder)
            self.setWindowTitle(f"VoxAI Coding Agent IDE — {folder}")
            self.chat_panel.clear_context()
            self.chat_panel.add_message("system", f"Switched project to: {folder}")

    def select_project_folder_from_menu(self):
        self.select_project_folder()

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------
    def create_global_toolbar(self):
        self.toolbar_widget = QWidget()
        self.toolbar_widget.setStyleSheet(
            "background-color: #2D2D30; border-bottom: 1px solid #3E3E42;")
        self.toolbar_widget.setFixedHeight(50)
        layout = QHBoxLayout(self.toolbar_widget)
        layout.setContentsMargins(10, 5, 10, 5)

        layout.addStretch()

        btn_css = (
            "QPushButton { background-color: #18181b; color: %s; "
            "border: 1px solid %s; border-radius: 4px; font-weight: 900; "
            "font-family: 'Consolas', monospace; text-transform: uppercase; "
            "letter-spacing: 1px; padding: 0 10px; }"
            "QPushButton:hover { background-color: #27272a; color: #00f3ff; "
            "border-color: #00f3ff; }")

        self.run_btn = QPushButton("Run Script")
        self.run_btn.setFixedSize(140, 32)
        self.run_btn.setStyleSheet(btn_css % ("#ff9900", "#ff9900"))
        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(15)
        glow.setOffset(0, 0)
        glow.setColor(QColor("#00f3ff"))
        self.run_btn.setGraphicsEffect(glow)
        self.run_btn.clicked.connect(self.select_and_run_script)
        layout.addWidget(self.run_btn)

        self.terminal_btn = QPushButton("Terminal")
        self.terminal_btn.setFixedSize(120, 32)
        self.terminal_btn.setStyleSheet(btn_css % ("#00f3ff", "#00f3ff"))
        self.terminal_btn.setToolTip("Switch to Terminal Mode (minimize to tray)")
        self.terminal_btn.clicked.connect(self._enter_terminal_mode)
        layout.addWidget(self.terminal_btn)

        layout.addStretch()

    def open_settings(self):
        from ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        if dlg.exec():
            if hasattr(self, 'chat_panel'):
                self.chat_panel.refresh_models()
                self.chat_panel.refresh_appearance()

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------
    def create_menu_bar(self):
        menu = self.menuBar()
        menu.setNativeMenuBar(False)

        file_menu = menu.addMenu("&File")
        file_menu.addAction("Open Project…", self.select_project_folder_from_menu,
                            QKeySequence("Ctrl+Shift+O"))
        file_menu.addAction("Open File…", self.open_file_dialog,
                            QKeySequence("Ctrl+O"))
        file_menu.addSeparator()
        file_menu.addAction("Save", self.save_current_file, QKeySequence("Ctrl+S"))
        file_menu.addAction("Save As…", self.save_current_file_as,
                            QKeySequence("Ctrl+Shift+S"))
        file_menu.addSeparator()
        file_menu.addAction("Export Conversation…", self._export_conversation)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close, QKeySequence("Alt+F4"))

        edit_menu = menu.addMenu("&Edit")
        edit_menu.addAction("Undo", lambda: self._editor_action("undo"),
                            QKeySequence("Ctrl+Z"))
        edit_menu.addAction("Redo", lambda: self._editor_action("redo"),
                            QKeySequence("Ctrl+Y"))
        edit_menu.addSeparator()
        edit_menu.addAction("Cut", lambda: self._editor_action("cut"),
                            QKeySequence("Ctrl+X"))
        edit_menu.addAction("Copy", lambda: self._editor_action("copy"),
                            QKeySequence("Ctrl+C"))
        edit_menu.addAction("Paste", lambda: self._editor_action("paste"),
                            QKeySequence("Ctrl+V"))
        edit_menu.addSeparator()
        edit_menu.addAction("Select All", lambda: self._editor_action("selectAll"),
                            QKeySequence("Ctrl+A"))
        edit_menu.addAction("Find & Replace", self.editor_panel._toggle_find,
                            QKeySequence("Ctrl+F"))

        view_menu = menu.addMenu("&View")
        view_menu.addAction("Command Palette", self._open_command_palette,
                            QKeySequence("Ctrl+Shift+P"))
        view_menu.addAction("Toggle Debug Panel", self._toggle_debug_drawer,
                            QKeySequence("Ctrl+`"))
        view_menu.addAction("Search in Project", self._toggle_search_panel,
                            QKeySequence("Ctrl+Shift+F"))
        view_menu.addAction("Conversation History", self._toggle_history_sidebar,
                            QKeySequence("Ctrl+H"))
        view_menu.addAction("Go to File", self._open_file_switcher,
                            QKeySequence("Ctrl+P"))
        view_menu.addAction("Code Outline", self._toggle_code_outline,
                            QKeySequence("Ctrl+Shift+L"))
        view_menu.addAction("Terminal Mode", self._enter_terminal_mode)

        options_menu = menu.addMenu("&Options")
        options_menu.addAction("Settings…", self.open_settings,
                               QKeySequence("Ctrl+,"))

        help_menu = menu.addMenu("&Help")
        help_menu.addAction("About", self.show_about)

    def closeEvent(self, event):
        if hasattr(self, '_tray'):
            self._tray.hide()
        self._kill_terminal()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------
    def _editor_action(self, action_name: str):
        ed = self._current_editor()
        if ed:
            fn = getattr(ed, action_name, None)
            if callable(fn):
                fn()

    def _current_editor(self):
        if hasattr(self.editor_panel, "tabs"):
            return self.editor_panel.tabs.currentWidget()
        return None

    def open_file_dialog(self):
        start_dir = self.project_path or os.getcwd()
        path, _ = QFileDialog.getOpenFileName(
            self, "Open File", start_dir, "All Files (*.*)")
        if path:
            self.editor_panel.load_file(path)

    def save_current_file(self):
        ed = self._current_editor()
        if not ed:
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
            QMessageBox.critical(self, "Save Failed", str(e))

    def save_current_file_as(self):
        ed = self._current_editor()
        if not ed:
            return
        start_dir = self.project_path or os.getcwd()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save File As", start_dir, "All Files (*.*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(ed.toPlainText())
            ed.file_path = path
            idx = self.editor_panel.tabs.currentIndex()
            if idx >= 0:
                self.editor_panel.tabs.setTabText(idx, os.path.basename(path))
            self.tree_panel.refresh()
            self.statusBar().showMessage(f"Saved: {path}", 2500)
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", str(e))

    def show_about(self):
        QMessageBox.about(self, "About VoxAI Coding Agent IDE", _(ABOUT_TEXT))

    def handle_chat_message(self, message: str):
        pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ABOUT_TEXT = (
    "<h3>VoxAI Coding Agent IDE</h3>"
    "<p><b>Version:</b> 2.0 Agentic</p><hr>"
    "<h4>Local Models (GGUF)</h4>"
    "<p>Place <code>.gguf</code> files in <code>/models/llm/</code> and "
    "they appear in Model Selection automatically.</p>"
    "<h4>Providers</h4>"
    "<p>OpenAI, Anthropic, Google, OpenRouter, DeepSeek, and more.</p>"
    "<h4>Terminal Mode</h4>"
    "<p>Press <b>Terminal</b> in the toolbar to switch to a Claude Code "
    "style CLI. The IDE minimizes to tray.</p><hr>"
    "<p><i>Built for the Vibe-Coder.</i></p>"
)

_ = lambda x: x  # no-op translation stub

_GLOBAL_STYLE = """
    QMainWindow { background-color: #18181b; color: #e4e4e7; }
    QWidget {
        font-family: 'Segoe UI', 'Inter', sans-serif;
        font-size: 13px; color: #e4e4e7;
    }
    QScrollBar:vertical {
        border: none; background: #18181b; width: 12px; margin: 0;
    }
    QScrollBar::handle:vertical {
        background: #3f3f46; min-height: 20px; border-radius: 6px;
        margin: 2px; border: 1px solid #27272a;
    }
    QScrollBar::handle:vertical:hover { background: #52525b; border-color: #00f3ff; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar:horizontal {
        border: none; background: #18181b; height: 12px; margin: 0;
    }
    QScrollBar::handle:horizontal {
        background: #3f3f46; min-width: 20px; border-radius: 6px;
        margin: 2px; border: 1px solid #27272a;
    }
    QScrollBar::handle:horizontal:hover { background: #52525b; border-color: #00f3ff; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    QSplitter::handle { background-color: #3f3f46; height: 6px; width: 6px; }
    QSplitter::handle:horizontal { width: 6px; }
    QSplitter::handle:vertical { height: 6px; }
    QSplitter::handle:hover { background-color: #ff9900; }
    QSplitter::handle:pressed { background-color: #00f3ff; }
    QToolTip {
        background-color: #27272a; color: #e4e4e7;
        border: 1px solid #00f3ff; padding: 4px; border-radius: 4px;
    }
    QMenuBar { background-color: #18181b; color: #e4e4e7; border-bottom: 1px solid #27272a; }
    QMenuBar::item { background: transparent; padding: 8px 12px; }
    QMenuBar::item:selected { background-color: #27272a; border-bottom: 2px solid #00f3ff; }
    QMenu { background-color: #18181b; border: 1px solid #3f3f46; padding: 5px; }
    QMenu::item { padding: 6px 24px 6px 12px; border-radius: 4px; }
    QMenu::item:selected { background-color: #27272a; color: #00f3ff; border: 1px solid #00f3ff; }
    QMenu::separator { height: 1px; background: #3f3f46; margin: 4px 0; }
    QTreeView, QListView { background-color: #1c1c1f; border: none; outline: none; }
    QTreeView::item, QListView::item { padding: 6px; border-radius: 4px; margin-bottom: 2px; }
    QTreeView::item:hover, QListView::item:hover { background-color: #2a2a2d; }
    QTreeView::item:selected, QListView::item:selected {
        background-color: #2f2f35; color: #00f3ff; border-left: 2px solid #00f3ff;
    }
"""
