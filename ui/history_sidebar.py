"""Conversation history sidebar for browsing, switching, and managing past chats."""

import os
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QLabel, QMessageBox,
)
from PySide6.QtCore import Qt, Signal

log = logging.getLogger(__name__)


class HistorySidebar(QWidget):
    """Lists all saved conversations with switch / delete actions."""

    conversation_selected = Signal(str)   # conv_id
    new_conversation = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.hide()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Header row
        hdr = QHBoxLayout()
        title = QLabel("History")
        title.setStyleSheet(
            "font-weight: bold; color: #00f3ff; font-family: 'Consolas', monospace; "
            "font-size: 13px;")
        hdr.addWidget(title)
        hdr.addStretch()

        new_btn = QPushButton("+ New")
        new_btn.setFixedWidth(60)
        new_btn.setStyleSheet(
            "QPushButton { background: #007fd4; color: white; border: none; "
            "border-radius: 3px; padding: 4px 8px; font-weight: bold; "
            "font-family: 'Consolas', monospace; font-size: 11px; }"
            "QPushButton:hover { background: #0098ff; }")
        new_btn.clicked.connect(self.new_conversation.emit)
        hdr.addWidget(new_btn)
        layout.addLayout(hdr)

        # Conversation list
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background: #1e1e1e; color: #d4d4d8; border: 1px solid #27272a;
                font-family: 'Consolas', monospace; font-size: 12px;
            }
            QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #27272a; }
            QListWidget::item:hover { background: #27272a; }
            QListWidget::item:selected { background: #264f78; color: #ffffff; }
        """)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget, 1)

        # Delete button
        del_btn = QPushButton("Delete Selected")
        del_btn.setStyleSheet(
            "QPushButton { background: #3f3f46; color: #ef4444; border: none; "
            "border-radius: 3px; padding: 4px 8px; "
            "font-family: 'Consolas', monospace; font-size: 11px; }"
            "QPushButton:hover { background: #ef4444; color: white; }")
        del_btn.clicked.connect(self._delete_selected)
        layout.addWidget(del_btn)

    def refresh(self, conversations: list[dict], current_id: str = ""):
        """Populate the list with conversation metadata dicts."""
        self.list_widget.clear()
        for c in conversations:
            title = c.get("title", "Untitled")
            count = c.get("msg_count", 0)
            updated = c.get("updated_at", "")[:16].replace("T", " ")
            display = f"{title}\n{updated}  •  {count} msgs"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, c["id"])
            if c["id"] == current_id:
                item.setSelected(True)
            self.list_widget.addItem(item)

    def toggle(self):
        self.setVisible(not self.isVisible())

    def _on_item_clicked(self, item):
        conv_id = item.data(Qt.UserRole)
        if conv_id:
            self.conversation_selected.emit(conv_id)

    def _delete_selected(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        conv_id = item.data(Qt.UserRole)
        reply = QMessageBox.question(
            self, "Delete Conversation",
            "Delete this conversation permanently?",
            QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._remove_conversation_file(conv_id)
            self.list_widget.takeItem(self.list_widget.row(item))

    def _remove_conversation_file(self, conv_id: str):
        """Try to delete the conversation JSON from the history dir."""
        try:
            from core.agent_tools import get_project_root
            path = os.path.join(get_project_root(), ".vox", "history", f"{conv_id}.json")
            if os.path.exists(path):
                os.remove(path)
                log.info("Deleted conversation %s", conv_id)
        except Exception as e:
            log.error("Failed to delete conversation: %s", e)
