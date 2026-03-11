from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget


class ProjectTrackerPanel(QWidget):
    """Left-rail tracker showing task progress and session changes."""

    change_open_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)
        self._changes = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.title_label = QLabel("Project Tracker")
        self.title_label.setStyleSheet("color: #00f3ff; font-weight: bold; font-family: 'Consolas', monospace; font-size: 13px;")
        layout.addWidget(self.title_label)

        self.overview_label = QLabel("No active tracked work yet.")
        self.overview_label.setWordWrap(True)
        self.overview_label.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        layout.addWidget(self.overview_label)

        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)

        self.task_frame = QFrame()
        self.task_frame.setStyleSheet("QFrame { background: #141416; border: 1px solid #27272a; border-radius: 8px; }")
        task_layout = QVBoxLayout(self.task_frame)
        task_layout.setContentsMargins(10, 10, 10, 10)
        task_layout.setSpacing(6)

        task_header = QHBoxLayout()
        self.task_title_label = QLabel("Task Board")
        self.task_title_label.setStyleSheet("color: #e4e4e7; font-weight: bold; font-size: 12px;")
        task_header.addWidget(self.task_title_label)
        task_header.addStretch()
        self.task_stats_label = QLabel("0 complete")
        self.task_stats_label.setStyleSheet("color: #67e8f9; font-size: 11px; font-weight: bold;")
        task_header.addWidget(self.task_stats_label)
        task_layout.addLayout(task_header)

        self.task_goal_label = QLabel("No active goal yet.")
        self.task_goal_label.setWordWrap(True)
        self.task_goal_label.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        task_layout.addWidget(self.task_goal_label)

        self.task_current_label = QLabel("Current focus: —")
        self.task_current_label.setWordWrap(True)
        self.task_current_label.setStyleSheet("color: #f4f4f5; font-size: 11px; font-weight: bold;")
        task_layout.addWidget(self.task_current_label)

        self.task_list = QListWidget()
        self.task_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; color: #e4e4e7; font-family: 'Consolas', monospace; font-size: 11px; }"
            "QListWidget::item { padding: 6px 4px; border-radius: 4px; }"
            "QListWidget::item:selected { background: #1a1a2e; color: #00f3ff; }"
        )
        self.task_list.setFocusPolicy(Qt.NoFocus)
        task_layout.addWidget(self.task_list, 1)

        self.change_frame = QFrame()
        self.change_frame.setStyleSheet("QFrame { background: #141416; border: 1px solid #27272a; border-radius: 8px; }")
        change_layout = QVBoxLayout(self.change_frame)
        change_layout.setContentsMargins(10, 10, 10, 10)
        change_layout.setSpacing(6)

        change_header = QHBoxLayout()
        self.change_title_label = QLabel("Session Changes")
        self.change_title_label.setStyleSheet("color: #e4e4e7; font-weight: bold; font-size: 12px;")
        change_header.addWidget(self.change_title_label)
        change_header.addStretch()
        self.change_count_label = QLabel("0 entries")
        self.change_count_label.setStyleSheet("color: #67e8f9; font-size: 11px; font-weight: bold;")
        change_header.addWidget(self.change_count_label)
        change_layout.addLayout(change_header)

        self.change_summary_label = QLabel("No captured changes yet.")
        self.change_summary_label.setWordWrap(True)
        self.change_summary_label.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        change_layout.addWidget(self.change_summary_label)

        self.change_list = QListWidget()
        self.change_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; color: #e4e4e7; font-family: 'Consolas', monospace; font-size: 11px; }"
            "QListWidget::item { padding: 6px 4px; border-radius: 4px; }"
            "QListWidget::item:selected { background: #1a1a2e; color: #00f3ff; }"
        )
        self.change_list.itemSelectionChanged.connect(self._update_change_preview)
        self.change_list.itemClicked.connect(self._emit_selected_change)
        self.change_list.itemActivated.connect(self._emit_selected_change)
        change_layout.addWidget(self.change_list, 1)

        self.change_preview = QPlainTextEdit()
        self.change_preview.setReadOnly(True)
        self.change_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.change_preview.setStyleSheet(
            "QPlainTextEdit { background: transparent; border: none; color: #d4d4d8; font-family: 'Consolas', 'Courier New', monospace; font-size: 11px; }"
        )
        change_layout.addWidget(self.change_preview, 1)

        self.splitter.addWidget(self.task_frame)
        self.splitter.addWidget(self.change_frame)
        self.splitter.setSizes([280, 320])

    def update_state(self, state: dict | None):
        state = state if isinstance(state, dict) else {}
        goal = str(state.get("goal", "") or "").strip()
        tasks = [task for task in (state.get("tasks") or []) if isinstance(task, dict)]
        changes = [change for change in (state.get("session_changes") or []) if isinstance(change, dict)]

        complete = sum(1 for task in tasks if str(task.get("status", "")).lower() == "complete")
        current = next((str(task.get("title", "") or "").strip() for task in tasks if str(task.get("status", "")).lower() == "current"), "")
        pending = sum(1 for task in tasks if str(task.get("status", "")).lower() == "pending")
        files_changed = {str(change.get("display_path", "") or "") for change in changes if str(change.get("display_path", "") or "").strip()}
        self.overview_label.setText(
            f"Progress: {complete}/{len(tasks) or 0} complete • {pending} pending • {len(files_changed)} changed file(s)."
            if (tasks or changes) else "No active tracked work yet."
        )

        self.task_goal_label.setText(f"Goal: {goal}" if goal else "No active goal yet.")
        self.task_current_label.setText(f"Current focus: {current}" if current else "Current focus: No active current task.")
        self.task_stats_label.setText(f"{complete}/{len(tasks) or 0} complete")
        self.task_list.clear()
        if tasks:
            for task in tasks:
                status = str(task.get("status", "pending") or "pending").upper()
                title = str(task.get("title", "") or "Untitled task")
                marker = {"COMPLETE": "[x]", "CURRENT": "[>]", "PENDING": "[ ]"}.get(status, "[ ]")
                item = QListWidgetItem(f"{marker} {status:8} {title}")
                if status == "COMPLETE":
                    item.setForeground(QColor("#86efac"))
                elif status == "CURRENT":
                    item.setForeground(QColor("#67e8f9"))
                    item.setBackground(QColor("#1f2937"))
                self.task_list.addItem(item)
        else:
            self.task_list.addItem(QListWidgetItem("[ ] PENDING  No active task board yet."))

        self._changes = list(reversed(changes[-20:]))
        self.change_count_label.setText(f"{len(self._changes)} entr{'y' if len(self._changes) == 1 else 'ies'}")
        self.change_list.clear()
        if self._changes:
            latest = str(self._changes[0].get("display_path", "") or "most recent file")
            self.change_summary_label.setText(
                f"{len(changes)} captured change(s) across {len(files_changed)} file(s). Click an entry to open its file + diff. Latest: {latest}."
            )
            for change in self._changes:
                display_path = str(change.get("display_path", "") or "(unknown file)")
                item = QListWidgetItem(f"{display_path}  {self._change_delta_summary(change)}")
                item.setData(Qt.UserRole, change)
                self.change_list.addItem(item)
            if self.change_list.count() > 0:
                self.change_list.setCurrentRow(0)
                self._update_change_preview()
        else:
            self.change_summary_label.setText("No captured changes yet.")
            self.change_preview.setPlainText("No applied file diffs have been captured for this conversation yet.")

    def _selected_change(self) -> dict | None:
        item = self.change_list.currentItem()
        data = item.data(Qt.UserRole) if item else None
        return data if isinstance(data, dict) else None

    def _update_change_preview(self):
        change = self._selected_change()
        if not change:
            if not self._changes:
                self.change_preview.setPlainText("No applied file diffs have been captured for this conversation yet.")
            return
        preview = str(change.get("diff_text", "") or change.get("diff_preview", "") or "(diff preview unavailable)").strip()
        self.change_preview.setPlainText(preview)

    def _emit_selected_change(self, item=None):
        change = item.data(Qt.UserRole) if item is not None else self._selected_change()
        if isinstance(change, dict):
            self.change_open_requested.emit(
                str(change.get("file_path", "") or ""),
                str(change.get("diff_text", "") or change.get("diff_preview", "") or ""),
            )

    @staticmethod
    def _change_delta_summary(change: dict) -> str:
        diff_text = str(change.get("diff_text", "") or change.get("diff_preview", "") or "")
        added = sum(1 for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---"))
        if added or removed:
            return f"(+{added}/-{removed})"
        return "(preview)"