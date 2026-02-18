"""Chat display widgets — Claude Code inspired inline terminal style."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QSizePolicy,
    QFrame, QApplication,
)
from PySide6.QtCore import Qt, Signal
import html as html_mod
import re
import logging

log = logging.getLogger(__name__)

_C_BG       = "#1e1e1e"
_C_USER     = "#ff9900"
_C_AI       = "#00f3ff"
_C_SYSTEM   = "#858585"
_C_DIM      = "#6e6e6e"
_C_ACCENT   = "#4ec9b0"
_C_LINK     = "#3794ff"
_C_CODE_BG  = "#2d2d2d"
_C_CODE_FG  = "#d4d4d8"
_C_ERR      = "#f14c4c"

_FONT_MONO  = "Consolas, 'Courier New', 'Fira Code', monospace"
_FONT_SANS  = "'Segoe UI', 'Inter', system-ui, sans-serif"

_ACTION_BTN_CSS = (
    "QPushButton { background: transparent; color: %s; border: none; "
    "font-family: %s; font-size: 10px; padding: 1px 6px; }"
    "QPushButton:hover { color: #00f3ff; text-decoration: underline; }"
)


class MessageItem(QWidget):
    """Flat, inline message widget with action buttons."""
    regenerate_requested = Signal()
    copy_requested = Signal(str)

    def __init__(self, role: str, text: str, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.role = role
        self.original_text = text

        from core.settings import SettingsManager
        self.settings_manager = SettingsManager()
        user_color = self.settings_manager.get_chat_user_color()
        ai_color = self.settings_manager.get_chat_ai_color()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(4)

        role_lower = role.lower()
        if role_lower == "user":
            prefix, role_name, color = "> ", "You", user_color
        elif role_lower in ("ai", "assistant"):
            prefix, role_name, color = "", "VoxAI", ai_color
        elif role_lower == "tool":
            prefix, role_name, color = "", "Tool", _C_ACCENT
        else:
            prefix, role_name, color = "", "System", "#555555"

        self.current_color = color
        is_ai = role_lower in ("ai", "assistant")
        is_system = role_lower == "system"
        is_project_switch = is_system and "switched project to" in text.lower()

        # --- Header row: role label + action buttons ---
        header_row = QWidget()
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        self.role_label = QLabel(f"{prefix}{role_name}")
        self.role_label.setStyleSheet(
            f"color: {color}; font-family: {_FONT_MONO}; font-size: 11px; "
            f"font-weight: bold; background: transparent; padding: 0; margin: 0; "
            f"text-transform: uppercase; letter-spacing: 0.5px;")
        header_layout.addWidget(self.role_label)
        header_layout.addStretch()

        # Copy button for all roles
        copy_btn = QPushButton("Copy")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setStyleSheet(_ACTION_BTN_CSS % (_C_DIM, _FONT_MONO))
        copy_btn.clicked.connect(self._copy_text)
        header_layout.addWidget(copy_btn)

        # Regenerate button only for AI
        if is_ai:
            regen_btn = QPushButton("Regenerate")
            regen_btn.setCursor(Qt.PointingHandCursor)
            regen_btn.setStyleSheet(_ACTION_BTN_CSS % (_C_DIM, _FONT_MONO))
            regen_btn.clicked.connect(self.regenerate_requested.emit)
            header_layout.addWidget(regen_btn)

        # Container with optional AI border
        self.item_container = QFrame()
        self.container_layout = QVBoxLayout(self.item_container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(4)

        if is_ai:
            self.item_container.setStyleSheet(
                f"border-left: 2px solid {_C_AI}; margin-left: 4px; padding-left: 10px;")
        else:
            self.item_container.setStyleSheet(
                "border: none; margin-left: 0; padding-left: 0;")

        if is_project_switch:
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Plain)
            line.setStyleSheet("background-color: #333333; margin: 10px 0;")
            layout.addWidget(line)

        self.container_layout.addWidget(header_row)

        # --- Content ---
        self.content_label = QLabel()
        self.content_label.setWordWrap(True)
        self.content_label.setTextFormat(Qt.RichText)
        self.content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.content_label.setOpenExternalLinks(True)
        self.content_label.setStyleSheet(
            f"color: {color}; font-family: {_FONT_MONO}; font-size: 12px; "
            f"background: transparent; padding: 2px 0 0 0; margin: 0; "
            f"line-height: 1.4;")

        formatted = self._format(text, color)
        self.content_label.setText(formatted)
        self.container_layout.addWidget(self.content_label)

        layout.addWidget(self.item_container)

        # --- Footer (Usage Stats) ---
        self.footer_label = QLabel()
        self.footer_label.setStyleSheet(
            f"color: {_C_DIM}; font-family: {_FONT_MONO}; font-size: 10px; "
            f"background: transparent; padding-top: 4px;")
        self.footer_label.hide()
        self.container_layout.addWidget(self.footer_label)

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("MessageItem { background: transparent; border: none; }")

    def _copy_text(self):
        QApplication.clipboard().setText(self.original_text)
        self.copy_requested.emit(self.original_text)

    def update_appearance(self):
        user_color = self.settings_manager.get_chat_user_color()
        ai_color = self.settings_manager.get_chat_ai_color()
        role_lower = self.role.lower()
        if role_lower == "user":
            color = user_color
        elif role_lower in ("ai", "assistant"):
            color = ai_color
        elif role_lower == "tool":
            color = _C_ACCENT
        else:
            color = "#555555"
        self.current_color = color
        self.role_label.setStyleSheet(
            f"color: {color}; font-family: {_FONT_MONO}; font-size: 11px; "
            f"font-weight: bold; background: transparent; padding: 0; margin: 0; "
            f"text-transform: uppercase; letter-spacing: 0.5px;")
        if role_lower in ("ai", "assistant"):
            self.item_container.setStyleSheet(
                f"border-left: 2px solid {ai_color}; margin-left: 4px; padding-left: 10px;")
        if hasattr(self, 'original_text'):
            self.set_text(self.original_text)

    def set_text(self, text: str):
        self.original_text = text
        self.content_label.setText(self._format(text, self.current_color))

    def set_usage(self, usage: dict):
        if not usage:
            return
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0)
        self.footer_label.setText(
            f"Tokens: {total} (Prompt: {prompt} | Output: {completion})")
        self.footer_label.show()

    def _format(self, text: str, main_color: str) -> str:
        if not text:
            return ""
        parts = re.split(r'(```\w*\n.*?```)', text, flags=re.DOTALL)
        result = ""
        for part in parts:
            if part.startswith("```") and part.endswith("```"):
                result += self._render_code_block(part)
            else:
                result += self._render_text(part, main_color)
        return result

    def _render_code_block(self, block: str) -> str:
        content = block[3:-3]
        if '\n' in content:
            lang, code = content.split('\n', 1)
            lang = lang.strip()
        else:
            lang, code = "", content

        try:
            from pygments import highlight
            from pygments.lexers import get_lexer_by_name, guess_lexer
            from pygments.formatters import HtmlFormatter
            formatter = HtmlFormatter(
                style='monokai', noclasses=True,
                cssstyles=(
                    f"padding: 10px; border-radius: 6px; "
                    f"background-color: {_C_CODE_BG}; color: {_C_CODE_FG}; "
                    f"display: block; white-space: pre-wrap; font-size: 12px; "
                    f"font-family: {_FONT_MONO}; margin: 6px 0;"))
            try:
                lexer = get_lexer_by_name(lang) if lang else guess_lexer(code)
            except Exception:
                from pygments.lexers.special import TextLexer
                lexer = TextLexer()
            return highlight(code, lexer, formatter)
        except ImportError:
            escaped = html_mod.escape(code)
            return (
                f'<pre style="background:{_C_CODE_BG}; color:{_C_CODE_FG}; '
                f'padding:10px; border-radius:6px; font-family:{_FONT_MONO}; '
                f'font-size:12px; margin:6px 0; white-space:pre-wrap;">'
                f'{escaped}</pre>')

    def _render_text(self, text: str, color: str) -> str:
        safe = html_mod.escape(text)
        safe = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', safe)
        safe = re.sub(
            r'`([^`]+)`',
            rf'<code style="background:{_C_CODE_BG}; color:{_C_LINK}; '
            rf'padding:1px 4px; border-radius:3px; font-family:{_FONT_MONO}; '
            rf'font-size:12px;">\1</code>', safe)
        safe = safe.replace('\n', '<br>')
        return (
            f'<span style="color:{color}; font-family:{_FONT_MONO}; '
            f'font-size: 13px;">{safe}</span>')


class ProgressItem(QWidget):
    """Collapsible thought-process + tool step tracker."""
    size_changed = Signal()
    show_detail_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(4)

        self.thought_expander = QPushButton("  Thinking...")
        self.thought_expander.setCheckable(True)
        self.thought_expander.setChecked(False)
        self.thought_expander.setStyleSheet(f"""
            QPushButton {{
                text-align: left; background: transparent;
                color: {_C_DIM}; border: none; padding: 4px 8px;
                font-family: {_FONT_MONO}; font-size: 12px;
            }}
            QPushButton:checked {{ color: {_C_AI}; }}
            QPushButton:hover   {{ color: {_C_AI}; }}
        """)
        self.thought_expander.clicked.connect(self._toggle_thought)
        layout.addWidget(self.thought_expander)

        self.thought_content = QLabel("(Analyzing request...)")
        self.thought_content.setWordWrap(True)
        self.thought_content.setStyleSheet(
            f"color: {_C_DIM}; font-style: italic; font-family: {_FONT_MONO}; "
            f"font-size: 11px; padding: 4px 12px; "
            f"border-left: 2px solid {_C_DIM}; background: transparent;")
        self.thought_content.hide()
        layout.addWidget(self.thought_content)

        self.steps_container = QWidget()
        self.steps_layout = QVBoxLayout(self.steps_container)
        self.steps_layout.setContentsMargins(12, 2, 0, 2)
        self.steps_layout.setSpacing(3)
        layout.addWidget(self.steps_container)

        self.status_label = QLabel("...")
        self.status_label.setStyleSheet(
            f"color: {_C_DIM}; font-family: {_FONT_MONO}; font-size: 11px; "
            f"padding-left: 12px; background: transparent;")
        layout.addWidget(self.status_label)

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("ProgressItem { background: transparent; border: none; }")

    def _toggle_thought(self):
        expanded = self.thought_expander.isChecked()
        arrow = "v" if expanded else ">"
        self.thought_expander.setText(f"  {arrow} Thinking...")
        self.thought_content.setVisible(expanded)
        self.size_changed.emit()

    def set_thought(self, text):
        if text:
            self.thought_content.setText(text)
            self.size_changed.emit()

    def add_step(self, icon, text, detail=None):
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        label = QLabel(f"{icon} {text}")
        label.setStyleSheet(
            f"color: {_C_DIM}; font-family: {_FONT_MONO}; font-size: 11px; "
            f"background: transparent;")
        row_layout.addWidget(label)
        if detail:
            btn = QPushButton("view")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {_C_LINK}; border: none;
                    font-family: {_FONT_MONO}; font-size: 10px;
                    text-decoration: underline; padding: 0;
                }}
                QPushButton:hover {{ color: {_C_USER}; }}
            """)
            btn.clicked.connect(
                lambda: self.show_detail_requested.emit(text, detail))
            row_layout.addWidget(btn)
        row_layout.addStretch()
        self.steps_layout.addWidget(row)
        self.size_changed.emit()

    def update_step_status(self, icon: str, result: str):
        """Update the last step with a completion indicator."""
        count = self.steps_layout.count()
        if count == 0:
            return
        last_row = self.steps_layout.itemAt(count - 1).widget()
        if last_row:
            row_layout = last_row.layout()
            if row_layout and row_layout.count() > 0:
                label = row_layout.itemAt(0).widget()
                if label:
                    current = label.text()
                    label.setText(f"{current} — {result}")

    def finish(self):
        self.status_label.hide()
        self.size_changed.emit()
