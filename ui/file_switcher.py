"""Quick file switcher (Ctrl+P) — fuzzy search overlay."""

import os
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt, Signal

log = logging.getLogger(__name__)

_SKIP_DIRS = {
    '.git', '__pycache__', 'node_modules', '.venv', 'venv',
    '.vox', 'storage', 'dist', 'build', '.egg-info',
}

_SKIP_EXT = {
    '.gguf', '.pth', '.pt', '.safetensors', '.db', '.bin',
    '.exe', '.dll', '.so', '.dylib',
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.bmp',
    '.mp3', '.mp4', '.wav', '.zip', '.tar', '.gz', '.7z',
}


class FileSwitcher(QDialog):
    """Ctrl+P quick file opener with fuzzy filtering."""

    file_selected = Signal(str)

    def __init__(self, project_root: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Go to File")
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setFixedSize(500, 400)
        self._project_root = project_root
        self._all_files: list[str] = []

        self._build_ui()
        self._index_files()
        self._filter("")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Type to search files…")
        self.input.setStyleSheet(
            "QLineEdit { background: #27272a; color: #e4e4e7; border: none; "
            "padding: 10px 14px; font-family: 'Consolas', monospace; font-size: 14px; "
            "border-bottom: 2px solid #00f3ff; }")
        self.input.textChanged.connect(self._filter)
        layout.addWidget(self.input)

        self.results = QListWidget()
        self.results.setStyleSheet("""
            QListWidget {
                background: #1e1e1e; color: #d4d4d8; border: none;
                font-family: 'Consolas', monospace; font-size: 13px;
            }
            QListWidget::item { padding: 6px 14px; }
            QListWidget::item:hover { background: #27272a; }
            QListWidget::item:selected { background: #264f78; color: #ffffff; }
        """)
        self.results.itemActivated.connect(self._on_select)
        layout.addWidget(self.results)

        self.setStyleSheet("QDialog { background: #1e1e1e; border: 1px solid #00f3ff; border-radius: 8px; }")

    def _index_files(self):
        self._all_files.clear()
        if not self._project_root:
            return
        for dirpath, dirnames, filenames in os.walk(self._project_root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                _, ext = os.path.splitext(fname)
                if ext.lower() in _SKIP_EXT:
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fname), self._project_root)
                self._all_files.append(rel)
        self._all_files.sort()

    def _filter(self, text: str):
        self.results.clear()
        query = text.lower().replace(" ", "")
        for path in self._all_files:
            if self._fuzzy_match(query, path.lower()):
                item = QListWidgetItem(path)
                item.setData(Qt.UserRole, os.path.join(self._project_root, path))
                self.results.addItem(item)
                if self.results.count() >= 50:
                    break
        if self.results.count() > 0:
            self.results.setCurrentRow(0)

    @staticmethod
    def _fuzzy_match(query: str, target: str) -> bool:
        if not query:
            return True
        qi = 0
        for ch in target:
            if ch == query[qi]:
                qi += 1
                if qi == len(query):
                    return True
        return False

    def _on_select(self, item):
        path = item.data(Qt.UserRole)
        if path:
            self.file_selected.emit(path)
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() in (Qt.Key_Down, Qt.Key_Up):
            self.results.keyPressEvent(event)
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            current = self.results.currentItem()
            if current:
                self._on_select(current)
        else:
            super().keyPressEvent(event)
