"""Project-wide search panel (Ctrl+Shift+F) with clickable results."""

import os
import re
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QCheckBox,
    QPushButton, QTreeWidget, QTreeWidgetItem, QLabel,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut

log = logging.getLogger(__name__)

_IGNORE_DIRS = {
    '.git', '__pycache__', 'node_modules', '.venv', 'venv',
    '.vox', 'storage', 'dist', 'build', '.egg-info',
}

_BINARY_EXT = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.bmp',
    '.mp3', '.mp4', '.wav', '.ogg', '.avi', '.mov',
    '.zip', '.tar', '.gz', '.7z', '.rar',
    '.exe', '.dll', '.so', '.dylib', '.bin',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx',
    '.gguf', '.pth', '.pt', '.safetensors', '.db',
}


class SearchPanel(QWidget):
    """Grep-style project search with clickable results."""

    file_requested = Signal(str, int)  # (file_path, line_number)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_root = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header
        hdr = QLabel("Search Project")
        hdr.setStyleSheet(
            "font-weight: bold; color: #00f3ff; font-family: 'Consolas', monospace; "
            "font-size: 12px;")
        layout.addWidget(hdr)

        # Search input row
        input_row = QHBoxLayout()
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Search across project…")
        self.query_input.setStyleSheet(
            "QLineEdit { background: #27272a; color: #e4e4e7; "
            "border: 1px solid #3f3f46; border-radius: 4px; padding: 6px; "
            "font-family: 'Consolas', monospace; font-size: 12px; }"
            "QLineEdit:focus { border-color: #00f3ff; }")
        self.query_input.returnPressed.connect(self._do_search)
        input_row.addWidget(self.query_input)

        self.search_btn = QPushButton("Search")
        self.search_btn.setFixedWidth(70)
        self.search_btn.setStyleSheet(
            "QPushButton { background: #007fd4; color: white; border: none; "
            "border-radius: 4px; padding: 6px; font-weight: bold; "
            "font-family: 'Consolas', monospace; font-size: 11px; }"
            "QPushButton:hover { background: #0098ff; }")
        self.search_btn.clicked.connect(self._do_search)
        input_row.addWidget(self.search_btn)
        layout.addLayout(input_row)

        # Options row
        opts_row = QHBoxLayout()
        self.case_cb = QCheckBox("Aa")
        self.case_cb.setToolTip("Case sensitive")
        self.case_cb.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        opts_row.addWidget(self.case_cb)

        self.regex_cb = QCheckBox(".*")
        self.regex_cb.setToolTip("Use regex")
        self.regex_cb.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        opts_row.addWidget(self.regex_cb)

        self.file_filter = QLineEdit()
        self.file_filter.setPlaceholderText("File filter (e.g. *.py)")
        self.file_filter.setFixedWidth(140)
        self.file_filter.setStyleSheet(
            "QLineEdit { background: #27272a; color: #a1a1aa; "
            "border: 1px solid #3f3f46; border-radius: 3px; padding: 3px; "
            "font-family: 'Consolas', monospace; font-size: 11px; }")
        opts_row.addWidget(self.file_filter)

        opts_row.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            "color: #6e6e6e; font-family: 'Consolas', monospace; font-size: 11px;")
        opts_row.addWidget(self.status_label)
        layout.addLayout(opts_row)

        # Results tree
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet("""
            QTreeWidget {
                background: #1e1e1e; color: #d4d4d8; border: 1px solid #27272a;
                font-family: 'Consolas', monospace; font-size: 12px;
            }
            QTreeWidget::item { padding: 2px 0; }
            QTreeWidget::item:hover { background: #27272a; }
            QTreeWidget::item:selected { background: #264f78; color: #ffffff; }
        """)
        self.tree.itemDoubleClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree, 1)

        self.hide()

    def set_root(self, path: str):
        self.project_root = path

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.query_input.setFocus()
            self.query_input.selectAll()

    def _do_search(self):
        query = self.query_input.text()
        if not query or not self.project_root:
            return

        self.tree.clear()
        self.status_label.setText("Searching…")

        case_sensitive = self.case_cb.isChecked()
        use_regex = self.regex_cb.isChecked()
        file_glob = self.file_filter.text().strip()

        try:
            if use_regex:
                flags = 0 if case_sensitive else re.IGNORECASE
                pattern = re.compile(query, flags)
            else:
                if case_sensitive:
                    pattern = re.compile(re.escape(query))
                else:
                    pattern = re.compile(re.escape(query), re.IGNORECASE)
        except re.error as e:
            self.status_label.setText(f"Regex error: {e}")
            return

        from fnmatch import fnmatch
        total_matches = 0
        total_files = 0

        for dirpath, dirnames, filenames in os.walk(self.project_root):
            dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS]

            for fname in filenames:
                _, ext = os.path.splitext(fname)
                if ext.lower() in _BINARY_EXT:
                    continue
                if file_glob and not fnmatch(fname, file_glob):
                    continue

                full_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(full_path, self.project_root)

                try:
                    with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                        lines = f.readlines()
                except Exception:
                    continue

                file_matches = []
                for i, line in enumerate(lines, 1):
                    if pattern.search(line):
                        file_matches.append((i, line.rstrip()))
                        if len(file_matches) >= 50:
                            break

                if file_matches:
                    total_files += 1
                    total_matches += len(file_matches)

                    file_item = QTreeWidgetItem(self.tree)
                    file_item.setText(0, f"{rel_path}  ({len(file_matches)} matches)")
                    file_item.setData(0, Qt.UserRole, full_path)
                    file_item.setData(0, Qt.UserRole + 1, 0)
                    file_item.setExpanded(True)

                    for line_num, line_text in file_matches:
                        preview = line_text[:200]
                        child = QTreeWidgetItem(file_item)
                        child.setText(0, f"  {line_num}: {preview}")
                        child.setData(0, Qt.UserRole, full_path)
                        child.setData(0, Qt.UserRole + 1, line_num)

                if total_matches >= 500:
                    break
            if total_matches >= 500:
                break

        truncated = " (capped)" if total_matches >= 500 else ""
        self.status_label.setText(
            f"{total_matches} matches in {total_files} files{truncated}")

    def _on_item_clicked(self, item, column):
        path = item.data(0, Qt.UserRole)
        line = item.data(0, Qt.UserRole + 1)
        if path:
            self.file_requested.emit(path, line or 1)
