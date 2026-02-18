"""Code outline sidebar — shows classes/functions/methods for the active file."""

import ast
import re
import os
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QLabel,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

log = logging.getLogger(__name__)


class CodeOutline(QWidget):
    """Parses AST (Python) or regex (other langs) to show a symbol tree."""

    line_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.hide()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        hdr = QLabel("Outline")
        hdr.setStyleSheet(
            "font-weight: bold; color: #00f3ff; font-family: 'Consolas', monospace; "
            "font-size: 12px;")
        layout.addWidget(hdr)

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

    def update_outline(self, file_path: str, text: str):
        """Rebuild the outline tree for the given file content."""
        self.tree.clear()
        if not file_path or not text:
            return

        _, ext = os.path.splitext(file_path)
        ext = ext.lower()

        if ext == '.py':
            self._parse_python(text)
        elif ext in ('.js', '.ts', '.jsx', '.tsx'):
            self._parse_js_ts(text)
        elif ext in ('.c', '.cpp', '.h', '.hpp', '.java', '.go', '.rs'):
            self._parse_c_style(text)
        else:
            self._parse_generic(text)

        self.tree.expandAll()

    def _add_item(self, parent, icon: str, name: str, line: int):
        item = QTreeWidgetItem(parent if parent else self.tree)
        item.setText(0, f"{icon} {name}")
        item.setData(0, Qt.UserRole, line)
        return item

    def _parse_python(self, text: str):
        """Use Python AST for accurate parsing."""
        try:
            tree = ast.parse(text)
        except SyntaxError:
            self._parse_generic(text)
            return

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                cls_item = self._add_item(None, "C", node.name, node.lineno)
                cls_item.setForeground(0, QColor("#e5c07b"))
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.FunctionDef):
                        m = self._add_item(cls_item, "M", child.name, child.lineno)
                        m.setForeground(0, QColor("#61afef"))
            elif isinstance(node, ast.FunctionDef):
                f = self._add_item(None, "F", node.name, node.lineno)
                f.setForeground(0, QColor("#98c379"))

    def _parse_js_ts(self, text: str):
        """Regex-based parsing for JS/TS files."""
        patterns = [
            (r'^\s*(?:export\s+)?class\s+(\w+)', "C", "#e5c07b"),
            (r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)', "F", "#98c379"),
            (r'^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(', "F", "#98c379"),
            (r'^\s*(\w+)\s*\([^)]*\)\s*\{', "M", "#61afef"),
        ]
        for i, line in enumerate(text.splitlines(), 1):
            for pattern, icon, color in patterns:
                m = re.match(pattern, line)
                if m:
                    item = self._add_item(None, icon, m.group(1), i)
                    item.setForeground(0, QColor(color))
                    break

    def _parse_c_style(self, text: str):
        """Regex-based parsing for C/C++/Java/Go/Rust."""
        patterns = [
            (r'^\s*(?:pub\s+)?(?:struct|class|enum|interface|type)\s+(\w+)', "C", "#e5c07b"),
            (r'^\s*(?:pub\s+)?(?:fn|func|void|int|string|bool|auto)\s+(\w+)\s*\(', "F", "#98c379"),
        ]
        for i, line in enumerate(text.splitlines(), 1):
            for pattern, icon, color in patterns:
                m = re.match(pattern, line)
                if m:
                    item = self._add_item(None, icon, m.group(1), i)
                    item.setForeground(0, QColor(color))
                    break

    def _parse_generic(self, text: str):
        """Fallback: look for common function/class patterns."""
        patterns = [
            (r'^\s*(?:class|struct|enum|interface)\s+(\w+)', "C", "#e5c07b"),
            (r'^\s*(?:def|function|fn|func|sub)\s+(\w+)', "F", "#98c379"),
        ]
        for i, line in enumerate(text.splitlines(), 1):
            for pattern, icon, color in patterns:
                m = re.match(pattern, line)
                if m:
                    item = self._add_item(None, icon, m.group(1), i)
                    item.setForeground(0, QColor(color))
                    break

    def toggle(self):
        self.setVisible(not self.isVisible())

    def _on_item_clicked(self, item, column):
        line = item.data(0, Qt.UserRole)
        if line:
            self.line_requested.emit(line)
