import json
import logging
import os

from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton

from core.agent_tools import get_project_root


log = logging.getLogger(__name__)


def select_attachment(self):
    path, _ = QFileDialog.getOpenFileName(self, "Attach File", get_project_root(), "All Files (*.*)")
    if path:
        self.add_attachment(path)


def add_attachment(self, path):
    if path in self.attachments:
        return
    self.attachments.append(path)
    self._refresh_attachments_ui()


def remove_attachment(self, path):
    if path in self.attachments:
        self.attachments.remove(path)
        self._refresh_attachments_ui()


def _refresh_attachments_ui(self):
    while self.attachment_layout.count():
        item = self.attachment_layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
    if not self.attachments:
        self.attachment_area.setVisible(False)
        return
    self.attachment_area.setVisible(True)
    for path in self.attachments:
        chip = QFrame()
        chip.setStyleSheet("background: #007fd4; border-radius: 10px; color: white;")
        chip_layout = QHBoxLayout(chip)
        chip_layout.setContentsMargins(8, 2, 8, 2)
        chip_layout.setSpacing(4)
        lbl = QLabel(os.path.basename(path))
        lbl.setStyleSheet("border: none; background: transparent; color: white; font-size: 11px;")
        chip_layout.addWidget(lbl)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setStyleSheet("border: none; background: transparent; color: white; font-weight: bold;")
        close_btn.clicked.connect(lambda checked=False, p=path: self.remove_attachment(p))
        chip_layout.addWidget(close_btn)
        self.attachment_layout.addWidget(chip)
    self.attachment_layout.addStretch()


def _history_dir(self) -> str:
    d = os.path.join(get_project_root(), ".vox", "history")
    os.makedirs(d, exist_ok=True)
    return d


def _conversation_file(self) -> str:
    return os.path.join(self._history_dir(), f"{self.conversation_id}.json")


def _derive_title(self) -> str:
    for message in self.messages:
        if message.get("role") == "user" and message.get("content", "").strip():
            return message["content"].strip()[:80]
    return "New Conversation"


def save_conversation(self):
    if not self.messages:
        return
    if not self.settings_manager.get_auto_save_conversation():
        return
    try:
        from datetime import datetime

        data = {
            "conversation_id": self.conversation_id,
            "title": self._derive_title(),
            "updated_at": datetime.now().isoformat(),
            "messages": self.messages,
            "agent_state": self._serialize_agent_state(),
        }
        with open(self._conversation_file(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        pointer = os.path.join(self._history_dir(), "current.txt")
        with open(pointer, "w", encoding="utf-8") as f:
            f.write(self.conversation_id)
        log.debug("Conversation saved (%d messages)", len(self.messages))
        self.conversation_changed.emit()
    except Exception as e:
        log.error("Failed to save conversation: %s", e)


def load_conversation(self):
    pointer = os.path.join(self._history_dir(), "current.txt")
    conv_id = None
    if os.path.exists(pointer):
        try:
            with open(pointer, "r", encoding="utf-8") as f:
                conv_id = f.read().strip()
        except Exception:
            pass

    legacy = os.path.join(get_project_root(), ".vox", "conversation.json")
    if not conv_id and os.path.exists(legacy):
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                data = json.load(f)
            conv_id = data.get("conversation_id", self.conversation_id)
            self.conversation_id = conv_id
            self.messages = data.get("messages", [])
            self._restore_agent_state(data.get("agent_state"))
            self.save_conversation()
            os.remove(legacy)
            for message in self.messages:
                self.append_message_widget(message["role"], message.get("content", ""))
            log.info("Migrated legacy conversation (%d msgs)", len(self.messages))
            return
        except Exception:
            pass

    if conv_id:
        self.switch_conversation(conv_id)
    else:
        log.info("No conversation history found. Starting fresh.")


def switch_conversation(self, conv_id: str):
    path = os.path.join(self._history_dir(), f"{conv_id}.json")
    if not os.path.exists(path):
        log.warning("Conversation file not found: %s", path)
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        while self.chat_layout.count():
            child = self.chat_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.conversation_id = data.get("conversation_id", conv_id)
        self._restore_agent_state(data.get("agent_state"))
        self.messages = data.get("messages", [])
        render_msgs = self.messages[-self.MAX_RENDERED_MESSAGES:]
        hidden = max(0, len(self.messages) - len(render_msgs))
        if hidden > 0:
            self.append_message_widget("system", f"[{hidden} older messages hidden for performance. Full history is preserved.]")
        for message in render_msgs:
            self.append_message_widget(message["role"], message.get("content", ""))
        pointer = os.path.join(self._history_dir(), "current.txt")
        with open(pointer, "w", encoding="utf-8") as f:
            f.write(self.conversation_id)
        log.info("Switched to conversation %s (%d msgs)", conv_id, len(self.messages))
        self.conversation_changed.emit()
    except Exception as e:
        log.error("Failed to load conversation %s: %s", conv_id, e)


def list_conversations(self) -> list[dict]:
    results = []
    hist_dir = self._history_dir()
    for fname in os.listdir(hist_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(hist_dir, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
            results.append({
                "id": data.get("conversation_id", fname[:-5]),
                "title": data.get("title", "Untitled"),
                "updated_at": data.get("updated_at", ""),
                "msg_count": len(data.get("messages", [])),
            })
        except Exception:
            continue
    results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return results


def clear_context(self):
    self.save_conversation()
    while self.chat_layout.count():
        child = self.chat_layout.takeAt(0)
        if child.widget():
            child.widget().deleteLater()
    self.messages = []
    self._reset_agent_run_state()
    self._reset_guided_takeoff(None)
    self._session_change_log = []
    import uuid
    self.conversation_id = str(uuid.uuid4())[:8]
    log.info("Context cleared. New Conversation ID: %s", self.conversation_id)
    self.project_tracker_changed.emit()
    self.append_message_widget("system", "Context cleared. Starting new conversation.")
    self.conversation_changed.emit()


__all__ = [
    "select_attachment",
    "add_attachment",
    "remove_attachment",
    "_refresh_attachments_ui",
    "_history_dir",
    "_conversation_file",
    "_derive_title",
    "save_conversation",
    "load_conversation",
    "switch_conversation",
    "list_conversations",
    "clear_context",
]