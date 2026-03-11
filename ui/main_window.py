import os
import sys
import json
import subprocess
import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter, QHBoxLayout,
    QPushButton, QFileDialog, QMessageBox, QLabel,
    QSystemTrayIcon,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut

from ui.chat_panel import ChatPanel
from ui.editor_panel import EditorPanel
from ui.file_tree_panel import FileTreePanel
from ui.debug_drawer import DebugDrawer
from ui.search_panel import SearchPanel
from ui.history_sidebar import HistorySidebar
from ui.project_tracker_panel import ProjectTrackerPanel
from ui.file_switcher import FileSwitcher
from ui.code_outline import CodeOutline
from core.runner import Runner
from core.ai_client import AIClient
from core.agent_tools import get_executable_root, set_project_root, get_resource_path
from core.settings import SettingsManager
from ui.main_window_status import (
    _apply_openrouter_health_indicator,
    _clear_openrouter_health_refresh_refs,
    _handle_openrouter_health_refresh,
    _openrouter_health_indicator_style,
    _queue_openrouter_health_refresh,
    _refresh_branch,
    _setup_openrouter_health_refresh,
    _setup_status_bar,
    _should_run_openrouter_health_refresh,
    update_token_count,
)
from ui.main_window_support import ABOUT_TEXT, CommandPalette, OpenRouterHealthWorker, _GLOBAL_STYLE, _

log = logging.getLogger(__name__)


class CodingAgentIDE(QMainWindow):
    _setup_status_bar = _setup_status_bar
    _refresh_branch = _refresh_branch
    update_token_count = update_token_count
    _openrouter_health_indicator_style = staticmethod(_openrouter_health_indicator_style)
    _apply_openrouter_health_indicator = _apply_openrouter_health_indicator
    _setup_openrouter_health_refresh = _setup_openrouter_health_refresh
    _should_run_openrouter_health_refresh = _should_run_openrouter_health_refresh
    _queue_openrouter_health_refresh = _queue_openrouter_health_refresh
    _handle_openrouter_health_refresh = _handle_openrouter_health_refresh
    _clear_openrouter_health_refresh_refs = _clear_openrouter_health_refresh_refs

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
        self._tray.setToolTip("VoxAI IDE")
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        # Terminal mode subprocess handle
        self._terminal_proc: subprocess.Popen | None = None

        self.setStyleSheet(_GLOBAL_STYLE)

        from core.settings import SettingsManager
        self.settings_manager = SettingsManager()
        self._openrouter_health_thread = None
        self._openrouter_health_worker = None
        self._openrouter_health_inflight = False
        self._openrouter_health_last_note = ""

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
        self.editor_panel.ai_edit_requested.connect(self._handle_ai_edit_requested)
        self._outline_editor_connected = None

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

        self.project_tracker_panel = ProjectTrackerPanel(self)
        self.project_tracker_panel.change_open_requested.connect(self._open_project_tracker_change)
        self.chat_panel.project_tracker_changed.connect(self._refresh_project_tracker)
        self.chat_panel.conversation_changed.connect(self._refresh_project_tracker)

        # ── Slim icon bar (replaces old toolbar) ──
        self._create_icon_bar()
        main_layout.addWidget(self._icon_bar)

        # ── Splitters (chat-centric layout) ──
        self.main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.main_splitter)

        # Left pane: project tracker + history
        self.left_sidebar_splitter = QSplitter(Qt.Vertical)
        self.left_sidebar_splitter.setChildrenCollapsible(False)
        self.left_sidebar_splitter.addWidget(self.project_tracker_panel)
        self.left_sidebar_splitter.addWidget(self.history_sidebar)
        self.left_sidebar_splitter.setSizes([420, 0])
        self.main_splitter.addWidget(self.left_sidebar_splitter)

        # Centre: chat panel (dominant)
        self.main_splitter.addWidget(self.chat_panel)

        # Right pane: editor + search + tree/outline (collapsible)
        self.right_splitter = QSplitter(Qt.Vertical)
        self.right_splitter.addWidget(self.editor_panel)
        self.right_splitter.addWidget(self.search_panel)

        self.bottom_right = QSplitter(Qt.Horizontal)
        self.bottom_right.addWidget(self.tree_panel)
        self.bottom_right.addWidget(self.code_outline)
        self.bottom_right.setSizes([300, 0])
        self.right_splitter.addWidget(self.bottom_right)
        self.right_splitter.setSizes([500, 0, 200])

        self.main_splitter.addWidget(self.right_splitter)

        # Default sizes: tracker visible, chat dominant, right panels available
        self.main_splitter.setSizes([320, 700, 500])
        self._refresh_project_tracker()
        self._sync_left_sidebar_layout(force_open=True)

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
        QShortcut(QKeySequence("Ctrl+Shift+T"), self).activated.connect(
            self._toggle_project_tracker)
        QShortcut(QKeySequence("Ctrl+H"), self).activated.connect(
            self._toggle_history_sidebar)
        QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(
            self._open_file_switcher)
        QShortcut(QKeySequence("Ctrl+Shift+L"), self).activated.connect(
            self._toggle_code_outline)
        QShortcut(QKeySequence("Ctrl+B"), self).activated.connect(
            self._toggle_file_tree)
        QShortcut(QKeySequence("Ctrl+Shift+E"), self).activated.connect(
            self._toggle_editor)

        # Project selection
        self.select_project_folder()
        if not self.project_path:
            self.project_path = os.getcwd()
            self.tree_panel.set_root_path(self.project_path)
            self.settings_manager.set_last_project_path(self.project_path)
        set_project_root(self.project_path)
        self.search_panel.set_root(self.project_path)
        if hasattr(self, '_title_label') and self.project_path:
            self._title_label.setText(os.path.basename(self.project_path))
        self._setup_openrouter_health_refresh()

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------
    def _refresh_cursor_pos(self):
        editor = self.editor_panel.tabs.currentWidget()
        if editor and hasattr(editor, 'textCursor'):
            cursor = editor.textCursor()
            line = cursor.blockNumber() + 1
            col = cursor.columnNumber() + 1
            self._status_cursor.setText(f"Ln {line}, Col {col}")

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
            ("Settings…  (Ctrl+,)", self.open_settings),
            ("Toggle Files  (Ctrl+B)", self._toggle_file_tree),
            ("Toggle Editor  (Ctrl+Shift+E)", self._toggle_editor),
            ("Toggle Debug Panel  (Ctrl+`)", self._toggle_debug_drawer),
            ("Search in Project  (Ctrl+Shift+F)", self._toggle_search_panel),
            ("Conversation History  (Ctrl+H)", self._toggle_history_sidebar),
            ("Go to File  (Ctrl+P)", self._open_file_switcher),
            ("Code Outline  (Ctrl+Shift+L)", self._toggle_code_outline),
            ("Find & Replace  (Ctrl+F)", self.editor_panel._toggle_find),
            ("New Chat", self.chat_panel.clear_context),
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
        self._ib_search.setChecked(self.search_panel.isVisible())
        if self.search_panel.isVisible():
            self._ensure_right_panel_visible(True)
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
        self._sync_left_sidebar_layout(force_open=self.history_sidebar.isVisible())
        if self.history_sidebar.isVisible():
            self._refresh_history()

    def _refresh_history(self):
        convos = self.chat_panel.list_conversations()
        self.history_sidebar.refresh(convos, self.chat_panel.conversation_id)

    def _toggle_project_tracker(self):
        self.project_tracker_panel.setVisible(not self.project_tracker_panel.isVisible())
        self._sync_left_sidebar_layout(force_open=self.project_tracker_panel.isVisible())

    def _sync_left_sidebar_layout(self, force_open: bool = False):
        tracker_visible = self.project_tracker_panel.isVisible()
        history_visible = self.history_sidebar.isVisible()
        left_visible = tracker_visible or history_visible

        if hasattr(self, '_ib_tracker'):
            self._ib_tracker.setChecked(tracker_visible)
        if hasattr(self, '_ib_history'):
            self._ib_history.setChecked(history_visible)

        self.left_sidebar_splitter.setVisible(left_visible)
        if not left_visible:
            sizes = self.main_splitter.sizes()
            if len(sizes) >= 3 and sizes[0] > 0:
                self.main_splitter.setSizes([0, sizes[1] + sizes[0], sizes[2]])
            return

        if tracker_visible and history_visible:
            self.left_sidebar_splitter.setSizes([420, 220])
        elif tracker_visible:
            self.left_sidebar_splitter.setSizes([1, 0])
        else:
            self.left_sidebar_splitter.setSizes([0, 1])

        sizes = self.main_splitter.sizes()
        if len(sizes) >= 3 and (force_open or sizes[0] < 180):
            total = sum(sizes) or 1520
            left_width = min(max(int(total * 0.22), 280), 360)
            right_width = max(sizes[2], 280)
            chat_width = max(total - left_width - right_width, 320)
            self.main_splitter.setSizes([left_width, chat_width, right_width])

    def _refresh_project_tracker(self):
        self.project_tracker_panel.update_state(self.chat_panel.project_tracker_state())

    def _open_project_tracker_change(self, file_path: str, diff_text: str):
        resolved_path = str(file_path or "")
        if resolved_path and not os.path.isabs(resolved_path):
            resolved_path = os.path.join(self.project_path or os.getcwd(), resolved_path)
        if resolved_path and os.path.exists(resolved_path):
            if not self.editor_panel.reload_open_file(resolved_path, highlight=True):
                self.editor_panel.load_file(resolved_path)
        if diff_text and diff_text.strip():
            self.editor_panel.show_diff(resolved_path or file_path or "Session Change", diff_text, activate=True)
        self._ensure_editor_visible_for_diff()

    # ------------------------------------------------------------------
    # Code outline
    # ------------------------------------------------------------------
    def _toggle_code_outline(self):
        self.code_outline.toggle()
        self._ib_outline.setChecked(self.code_outline.isVisible())
        if self.code_outline.isVisible():
            self._ensure_right_panel_visible(True)
            sizes = self.bottom_right.sizes()
            if sizes[1] < 100:
                self.bottom_right.setSizes([sizes[0], 200])
            self._refresh_outline()

    def _on_editor_tab_changed(self, index):
        editor = self.editor_panel.tabs.widget(index) if index >= 0 else None
        if self._outline_editor_connected and self._outline_editor_connected is not editor:
            try:
                self._outline_editor_connected.textChanged.disconnect(self._refresh_outline)
            except Exception:
                pass
            self._outline_editor_connected = None
        if editor and hasattr(editor, "textChanged"):
            try:
                editor.textChanged.connect(self._refresh_outline)
                self._outline_editor_connected = editor
            except Exception:
                pass
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
    @staticmethod
    def _notification_payload(title: str, message: str):
        compact = " ".join((message or "").split())
        if len(compact) > 220:
            compact = compact[:217] + "..."
        lowered = f"{title} {message}".lower()
        is_error = any(token in lowered for token in ("error", "failed", "rate limit", "privacy setting", "blocked"))
        icon = QSystemTrayIcon.Warning if is_error else QSystemTrayIcon.Information
        timeout_ms = 12000 if is_error else 5000
        return compact, icon, timeout_ms

    def _show_notification(self, title: str, message: str):
        compact, icon, timeout_ms = self._notification_payload(title, message)
        if "openrouter" in f"{title} {message}".lower():
            self._apply_openrouter_health_indicator()
        if self.statusBar():
            self.statusBar().showMessage(f"{title}: {compact}", timeout_ms)
        if not self.isActiveWindow() and self._tray.isSystemTrayAvailable():
            self._tray.showMessage(title, compact, icon, timeout_ms)

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
        model = self.chat_panel._get_full_model_name()
        mode = self.chat_panel.mode_combo.currentText()

        if getattr(sys, "frozen", False):
            cli_target = os.path.join(get_executable_root(), "VoxAI_Terminal.exe")
            if not os.path.exists(cli_target):
                QMessageBox.warning(
                    self,
                    "Terminal Mode",
                    "Bundled terminal executable not found. Expected VoxAI_Terminal.exe next to the main app.",
                )
                return
            args = [
                cli_target,
                "--project", project_root,
                "--conversation", conv_file,
                "--model", model,
                "--mode", mode,
            ]
        else:
            cli_target = get_resource_path(os.path.join("cli", "terminal_mode.py"))
            if not os.path.exists(cli_target):
                QMessageBox.warning(self, "Terminal Mode",
                                    "CLI module not found. Ensure cli/terminal_mode.py exists.")
                return
            args = [
                sys.executable, cli_target,
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
            "IDE minimized to the tray. Double-click the tray icon to return to the GUI.",
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
        # Terminal mode may have changed model/settings; sync combo selection first.
        self.chat_panel.refresh_models()
        # Ensure any stale run-state from before terminal mode is cleared.
        self.chat_panel._reset_send_button()
        # Reload conversation written by the terminal session.
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
        top_offset = (
            (self._icon_bar.height() if hasattr(self, "_icon_bar") else 34)
            + self.menuBar().height())
        self.debug_drawer.setGeometry(
            self.width() - drawer_width, top_offset,
            drawer_width, self.height() - top_offset)
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
        # Preserve baseline when file is already open so change highlights remain visible.
        if not self.editor_panel.reload_open_file(file_path, highlight=True):
            self.editor_panel.load_file(file_path)
        self._ensure_editor_visible_for_diff()
        self.tree_panel.refresh()
        if self.code_outline.isVisible():
            self._refresh_outline()

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
            self.editor_panel.show_diff(*diffs[0], activate=False)
        else:
            self.editor_panel.show_diffs_batch(diffs, activate=False)
        self._ensure_editor_visible_for_diff()
        self._pending_diffs = []

    def _handle_ai_edit_requested(self, file_path: str, selection: str, instruction: str):
        if self.chat_panel.is_processing:
            self._show_notification("AI Busy", "Please wait for the current response to finish.")
            return
        prompt = (
            "You are editing a selected code snippet in the user's file.\n"
            f"File: {file_path}\n"
            f"Instruction: {instruction}\n\n"
            "Use the edit_file tool with old_text matching the selection exactly.\n"
            "Only change text inside the selection. Preserve formatting and indentation.\n\n"
            "[BEGIN_SELECTION]\n"
            f"{selection}\n"
            "[END_SELECTION]"
        )
        self.chat_panel.send_worker(prompt, is_automated=True)

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
            if hasattr(self, '_title_label'):
                self._title_label.setText(os.path.basename(folder))
            self.chat_panel.clear_context()
            self.chat_panel.add_message("system", f"Switched project to: {folder}")

    def select_project_folder_from_menu(self):
        self.select_project_folder()

    # ------------------------------------------------------------------
    # Slim icon bar (replaces old toolbar)
    # ------------------------------------------------------------------
    def _create_icon_bar(self):
        self._icon_bar = QWidget()
        self._icon_bar.setFixedHeight(34)
        self._icon_bar.setStyleSheet(
            "background: #111113; border-bottom: 1px solid #27272a;")
        lay = QHBoxLayout(self._icon_bar)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(2)

        _ib = (
            "QPushButton { background: transparent; color: #71717a; border: none; "
            "border-radius: 4px; padding: 4px 8px; font-size: 14px; }"
            "QPushButton:hover { background: #27272a; color: #e4e4e7; }"
            "QPushButton:checked { color: #00f3ff; background: #1a1a2e; }")

        def _icon_btn(icon: str, tip: str, fn, checkable: bool = False):
            b = QPushButton(icon)
            b.setToolTip(tip)
            b.setFixedSize(30, 28)
            b.setStyleSheet(_ib)
            b.setCheckable(checkable)
            b.clicked.connect(fn)
            return b

        self._ib_files = _icon_btn("📁", "Toggle Files  (Ctrl+B)", self._toggle_file_tree, True)
        self._ib_editor = _icon_btn("📝", "Toggle Editor", self._toggle_editor, True)
        self._ib_search = _icon_btn("🔍", "Search  (Ctrl+Shift+F)", self._toggle_search_panel, True)
        self._ib_tracker = _icon_btn("📋", "Project Tracker  (Ctrl+Shift+T)", self._toggle_project_tracker, True)
        self._ib_outline = _icon_btn("🧭", "Code Outline  (Ctrl+Shift+L)", self._toggle_code_outline, True)
        self._ib_history = _icon_btn("💬", "History  (Ctrl+H)", self._toggle_history_sidebar, True)
        self._ib_terminal = _icon_btn("⌨", "Terminal Mode", self._enter_terminal_mode)
        self._ib_run = _icon_btn("▶", "Run Script", self.select_and_run_script)
        self._ib_settings = _icon_btn("⚙", "Settings  (Ctrl+,)", self.open_settings)

        self._ib_tracker.setChecked(True)

        for b in (self._ib_files, self._ib_editor, self._ib_search, self._ib_tracker,
                  self._ib_outline, self._ib_history):
            lay.addWidget(b)

        lay.addStretch()

        # Centred project title label
        self._title_label = QLabel("VoxAI")
        self._title_label.setStyleSheet(
            "color: #52525b; font-size: 11px; font-family: 'Consolas', monospace;")
        self._title_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._title_label)

        lay.addStretch()

        for b in (self._ib_run, self._ib_terminal, self._ib_settings):
            lay.addWidget(b)

    # Panel visibility toggles used by icon bar
    def _toggle_file_tree(self):
        vis = not self.tree_panel.isVisible()
        self.tree_panel.setVisible(vis)
        self._ib_files.setChecked(vis)
        self._ensure_right_panel_visible(vis)

    def _toggle_editor(self):
        vis = not self.editor_panel.isVisible()
        self.editor_panel.setVisible(vis)
        self._ib_editor.setChecked(vis)
        self._ensure_right_panel_visible(vis)

    def _ensure_right_panel_visible(self, opening: bool):
        """When opening a right-side panel, make sure the splitter gives it space."""
        if opening:
            sizes = self.main_splitter.sizes()
            if sizes[2] < 200:
                total = sum(sizes)
                sizes[2] = int(total * 0.4)
                sizes[1] = total - sizes[0] - sizes[2]
                self.main_splitter.setSizes(sizes)

    def _ensure_editor_visible_for_diff(self):
        """Ensure the editor pane is visible when a diff is generated."""
        if not self.editor_panel.isVisible():
            self.editor_panel.setVisible(True)
            if hasattr(self, "_ib_editor"):
                self._ib_editor.setChecked(True)
        self._ensure_right_panel_visible(True)

        sizes = self.right_splitter.sizes()
        if sizes and sizes[0] < 200:
            total = sum(sizes)
            sizes[0] = int(total * 0.6)
            remaining = total - sizes[0]
            if len(sizes) == 2:
                sizes[1] = remaining
            elif len(sizes) >= 3:
                sizes[1] = int(remaining * 0.4)
                sizes[2] = remaining - sizes[1]
            self.right_splitter.setSizes(sizes)

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
        view_menu.addSeparator()
        view_menu.addAction("Toggle Files", self._toggle_file_tree,
                            QKeySequence("Ctrl+B"))
        view_menu.addAction("Toggle Editor", self._toggle_editor,
                            QKeySequence("Ctrl+Shift+E"))
        view_menu.addAction("Toggle Debug Panel", self._toggle_debug_drawer,
                            QKeySequence("Ctrl+`"))
        view_menu.addAction("Search in Project", self._toggle_search_panel,
                            QKeySequence("Ctrl+Shift+F"))
        view_menu.addAction("Project Tracker", self._toggle_project_tracker,
                            QKeySequence("Ctrl+Shift+T"))
        view_menu.addAction("Conversation History", self._toggle_history_sidebar,
                            QKeySequence("Ctrl+H"))
        view_menu.addSeparator()
        view_menu.addAction("Go to File", self._open_file_switcher,
                            QKeySequence("Ctrl+P"))
        view_menu.addAction("Code Outline", self._toggle_code_outline,
                            QKeySequence("Ctrl+Shift+L"))
        view_menu.addSeparator()
        view_menu.addAction("Terminal Mode", self._enter_terminal_mode)

        options_menu = menu.addMenu("&Options")
        options_menu.addAction("Settings…", self.open_settings,
                               QKeySequence("Ctrl+,"))

        help_menu = menu.addMenu("&Help")
        help_menu.addAction("About", self.show_about)

    def closeEvent(self, event):
        self._shutdown_background_work()
        if hasattr(self, '_tray'):
            self._tray.hide()
        self._kill_terminal()
        super().closeEvent(event)

    def _shutdown_background_work(self):
        chat_panel = getattr(self, 'chat_panel', None)
        if chat_panel is not None:
            shutdown = getattr(chat_panel, '_shutdown_background_threads', None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    log.exception("Failed to shut down chat panel background threads")
        timer = getattr(self, '_openrouter_health_timer', None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                log.exception("Failed to stop OpenRouter health timer")
        thread = getattr(self, '_openrouter_health_thread', None)
        if thread is not None:
            try:
                if thread.isRunning():
                    thread.quit()
                    if not thread.wait(5000):
                        log.warning("Timed out waiting for OpenRouter health thread shutdown")
            except Exception:
                log.exception("Failed to shut down OpenRouter health thread")
        clear_refs = getattr(self, '_clear_openrouter_health_refresh_refs', None)
        if callable(clear_refs):
            try:
                clear_refs()
            except Exception:
                log.exception("Failed to clear OpenRouter health refresh refs")

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
