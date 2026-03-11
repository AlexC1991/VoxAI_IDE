import logging

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from core.summary_guard import SummaryGuard
from ui.widgets.chat_items import MessageItem


log = logging.getLogger(__name__)


def refresh_appearance(self):
    """Reloads settings and updates all chat items."""
    count = self.chat_layout.count()
    for i in range(count):
        item = self.chat_layout.itemAt(i)
        widget = item.widget()
        if widget and hasattr(widget, 'update_appearance'):
            widget.update_appearance()
    self.chat_content.update()


def on_model_changed(self, _display_text):
    full = self._get_full_model_name()
    if full:
        self.settings_manager.set_selected_model(full)
        self._refresh_model_combo_tooltip()
        log.info("Model switched to: %s", full)


def open_settings(self):
    from ui.settings_dialog import SettingsDialog

    parent = self.window()
    dlg = SettingsDialog(parent)
    if dlg.exec():
        self.refresh_models()


def append_message_widget(self, role, text):
    item = MessageItem(role, text)
    item.regenerate_requested.connect(self._regenerate_last)
    self._add_chat_widget(item)
    self._auto_scroll = True
    return item


def _add_chat_widget(self, widget, before_widget=None):
    """Keep chat visually locked in a left-anchored, width-limited focus region."""
    row = QWidget()
    row.setStyleSheet("background: transparent; border: none;")
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(0)
    widget.setMaximumWidth(self.CHAT_MAX_WIDTH)
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    row_layout.addWidget(widget)
    row_layout.addStretch(1)
    widget._chat_row = row

    if before_widget is not None and hasattr(before_widget, "_chat_row"):
        idx = self.chat_layout.indexOf(before_widget._chat_row)
        if idx >= 0:
            self.chat_layout.insertWidget(idx, row)
        else:
            self.chat_layout.addWidget(row)
    else:
        self.chat_layout.addWidget(row)
    self._prune_chat_widgets()


def _prune_chat_widgets(self):
    """Limit rendered widgets to keep long conversations responsive."""
    while self.chat_layout.count() > self.MAX_RENDERED_MESSAGES:
        child = self.chat_layout.takeAt(0)
        widget = child.widget()
        if widget:
            active_row = getattr(self.current_ai_item, "_chat_row", None)
            if active_row is not None and widget is active_row:
                self.chat_layout.insertWidget(0, widget)
                break
            widget.deleteLater()


def _regenerate_last(self):
    """Re-send the last user message to get a fresh AI response."""
    if self.is_processing:
        return
    for message in reversed(self.messages):
        if message["role"] == "user" and not message["content"].startswith("[TOOL_RESULT]"):
            while self.messages and self.messages[-1]["role"] != "user":
                self.messages.pop()
            self.is_processing = True
            self._reset_agent_run_state()
            self._set_stop_button()
            self._start_ai_worker(message["content"], [])
            break


def add_message(self, role, text):
    """Public API for adding messages (compatibility wrapper)."""
    self.append_message_widget(role, text)
    self.messages.append({"role": role, "content": text})


def _compact_tool_result_text_for_ai(text: str, max_items: int = 6, max_excerpt_chars: int = 500, max_excerpt_lines: int = 12) -> str:
    raw_text = str(text or "")
    if "[TOOL_RESULT]" not in raw_text:
        return raw_text

    parsed = SummaryGuard.parse_action_summary(raw_text)
    sections = [
        ("Successful file changes:", parsed.get("file_changes") or []),
        ("Other successful actions:", parsed.get("other_actions") or []),
        ("Failed actions:", parsed.get("failed_actions") or []),
    ]

    lines = ["[TOOL_RESULT] (Automated system output — compact replay)"]
    if any(items for _, items in sections):
        lines.append("[ACTION_SUMMARY]")
        for heading, items in sections:
            lines.append(heading)
            if items:
                for item in items[:max_items]:
                    lines.append(f"- {item}")
                if len(items) > max_items:
                    lines.append(f"- ... [{len(items) - max_items} more omitted]")
            else:
                lines.append("- none")
        lines.append("[/ACTION_SUMMARY]")

    body = raw_text
    if "[/ACTION_SUMMARY]" in body:
        body = body.split("[/ACTION_SUMMARY]", 1)[1]
    body = body.replace("[/TOOL_RESULT]", "").strip()
    if body:
        body_lines = body.splitlines()
        excerpt = "\n".join(body_lines[:max_excerpt_lines]).strip()
        if len(excerpt) > max_excerpt_chars:
            excerpt = excerpt[:max_excerpt_chars].rstrip()
        hidden_lines = max(0, len(body_lines) - max_excerpt_lines)
        hidden_chars = max(0, len(body) - len(excerpt))
        if hidden_lines or hidden_chars:
            excerpt += f"\n...[{hidden_lines} lines / {hidden_chars} chars omitted from older tool replay]..."
        lines.append("Output excerpt:")
        lines.append(excerpt)

    lines.append("[/TOOL_RESULT]")
    return "\n".join(lines)


def _is_tool_result_message(msg) -> bool:
    return msg.get("role") == "system" and "[TOOL_RESULT]" in str(msg.get("content", ""))


def _message_for_ai(msg, compact_tool_result: bool = False):
    content = msg.get("payload_content", msg.get("content", ""))
    if compact_tool_result:
        content = _compact_tool_result_text_for_ai(content)
    return {
        "role": msg.get("role", "user"),
        "content": content,
    }


def _messages_for_ai(cls, messages):
    latest_tool_result_idx = None
    for idx, msg in enumerate(messages):
        if _is_tool_result_message(msg):
            latest_tool_result_idx = idx
    return [
        cls._message_for_ai(m, compact_tool_result=_is_tool_result_message(m) and idx != latest_tool_result_idx)
        for idx, m in enumerate(messages)
    ]


def eventFilter(self, obj, event):
    if obj == self.input_field and event.type() == QEvent.KeyPress:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                return False
            self.send_message()
            return True
        if event.key() == Qt.Key_L and event.modifiers() & Qt.ControlModifier:
            self.clear_context()
            return True
        if event.key() == Qt.Key_Escape and self.is_processing:
            self.handle_stop_button()
            return True
    return QWidget.eventFilter(self, obj, event)


__all__ = [name for name in globals() if name.startswith("_") or name in {"refresh_appearance", "on_model_changed", "open_settings", "append_message_widget", "add_message", "eventFilter"}]