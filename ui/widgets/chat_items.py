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

# ── Palette ──
_BG         = "#111113"
_C_USER     = "#e4e4e7"
_C_AI       = "#d4d4d8"
_C_SYSTEM   = "#52525b"
_C_TOOL     = "#4ec9b0"
_C_DIM      = "#52525b"
_C_ACCENT   = "#00f3ff"
_C_ORANGE   = "#ff9900"
_C_LINK     = "#3794ff"
_C_CODE_BG  = "#1a1a1d"
_C_CODE_FG  = "#d4d4d8"
_C_ERR      = "#f14c4c"
_C_GREEN    = "#4ec9b0"

_FONT_MONO  = "Consolas, 'Courier New', 'Fira Code', monospace"
_FONT_SANS  = "'Segoe UI', 'Inter', system-ui, sans-serif"

_ROLE_CSS = (
    "color: %s; font-family: {m}; font-size: 11px; font-weight: 600; "
    "background: transparent; padding: 0; margin: 0; letter-spacing: 0.3px;"
).replace("{m}", _FONT_MONO)

_SMALL_BTN = (
    "QPushButton { background: transparent; color: #3f3f46; border: none; "
    "font-family: %s; font-size: 10px; padding: 0 4px; }"
    "QPushButton:hover { color: #a1a1aa; }"
) % _FONT_MONO


class MessageItem(QWidget):
    """Flat, terminal-style message widget."""
    regenerate_requested = Signal()
    copy_requested = Signal(str)

    def __init__(self, role: str, text: str, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.role = role
        self.original_text = text

        from core.settings import SettingsManager
        self.settings_manager = SettingsManager()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(2)

        role_lower = role.lower()
        is_ai = role_lower in ("ai", "assistant")
        is_user = role_lower == "user"
        is_tool = role_lower == "tool"
        is_system = role_lower == "system"
        is_tool_result = is_system and text.startswith("[TOOL_RESULT]")

        # Determine colors
        if is_user:
            label_color = _C_ORANGE
            text_color = _C_USER
            role_name = "You"
        elif is_ai:
            label_color = _C_ACCENT
            text_color = _C_AI
            role_name = "VoxAI"
        elif is_tool:
            label_color = _C_GREEN
            text_color = _C_TOOL
            role_name = "Tool"
        else:
            label_color = _C_DIM
            text_color = _C_SYSTEM
            role_name = "System"

        self.current_color = text_color

        # ── Tool results: collapsible ──
        if is_tool_result:
            self._build_tool_result(layout, text)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setStyleSheet("MessageItem { background: transparent; }")
            return

        # ── Header row ──
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 0)
        hdr.setSpacing(4)

        self.role_label = QLabel(role_name)
        self.role_label.setStyleSheet(_ROLE_CSS % label_color)
        hdr.addWidget(self.role_label)
        hdr.addStretch()

        copy_btn = QPushButton("copy")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setStyleSheet(_SMALL_BTN)
        copy_btn.clicked.connect(self._copy_text)
        hdr.addWidget(copy_btn)

        if is_ai:
            regen_btn = QPushButton("retry")
            regen_btn.setCursor(Qt.PointingHandCursor)
            regen_btn.setStyleSheet(_SMALL_BTN)
            regen_btn.clicked.connect(self.regenerate_requested.emit)
            hdr.addWidget(regen_btn)

        layout.addLayout(hdr)

        # ── Content ──
        self.content_label = QLabel()
        self.content_label.setWordWrap(True)
        self.content_label.setTextFormat(Qt.RichText)
        self.content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.content_label.setOpenExternalLinks(True)

        if is_ai:
            self.content_label.setStyleSheet(
                f"color: {text_color}; font-family: {_FONT_MONO}; font-size: 13px; "
                f"background: transparent; padding: 2px 0 0 10px; margin: 0; "
                f"line-height: 1.45; border-left: 2px solid #1e1e21;")
        elif is_user:
            self.content_label.setStyleSheet(
                f"color: {text_color}; font-family: {_FONT_MONO}; font-size: 13px; "
                f"background: transparent; padding: 2px 0 0 0; margin: 0; "
                f"line-height: 1.4;")
        else:
            self.content_label.setStyleSheet(
                f"color: {text_color}; font-family: {_FONT_MONO}; font-size: 11px; "
                f"background: transparent; padding: 1px 0; margin: 0; "
                f"line-height: 1.3;")

        self.content_label.setText(self._format(text, text_color))
        layout.addWidget(self.content_label)

        # ── Footer (token usage) ──
        self.footer_label = QLabel()
        self.footer_label.setStyleSheet(
            f"color: #3f3f46; font-family: {_FONT_MONO}; font-size: 10px; "
            f"background: transparent; padding: 2px 0 0 10px;")
        self.footer_label.hide()
        layout.addWidget(self.footer_label)

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("MessageItem { background: transparent; }")

    def _build_tool_result(self, parent_layout, text: str):
        """Render [TOOL_RESULT] blocks as a collapsible section."""
        clean = text
        if clean.startswith("[TOOL_RESULT]"):
            clean = clean[len("[TOOL_RESULT]"):].strip()
        if clean.endswith("[/TOOL_RESULT]"):
            clean = clean[:-len("[/TOOL_RESULT]")].strip()
        # Strip the automated notice
        clean = clean.replace("(Automated system output — not user input)", "").strip()

        preview = clean[:120].replace("\n", " ")
        if len(clean) > 120:
            preview += "..."

        self._tool_btn = QPushButton(f"  ▸ Tool Result  —  {preview}")
        self._tool_btn.setCheckable(True)
        self._tool_btn.setChecked(False)
        self._tool_btn.setStyleSheet(f"""
            QPushButton {{
                text-align: left; background: transparent;
                color: {_C_DIM}; border: none; padding: 3px 0;
                font-family: {_FONT_MONO}; font-size: 11px;
            }}
            QPushButton:checked {{ color: {_C_GREEN}; }}
            QPushButton:hover {{ color: {_C_GREEN}; }}
        """)

        self._tool_detail = QLabel()
        self._tool_detail.setWordWrap(True)
        self._tool_detail.setTextFormat(Qt.RichText)
        self._tool_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        escaped = html_mod.escape(clean)
        self._tool_detail.setText(
            f'<pre style="color:{_C_DIM}; font-family:{_FONT_MONO}; font-size:11px; '
            f'background:{_C_CODE_BG}; padding:8px; border-radius:4px; '
            f'white-space:pre-wrap; margin:2px 0 0 12px;">{escaped}</pre>')
        self._tool_detail.hide()

        self._tool_btn.clicked.connect(self._toggle_tool_detail)
        parent_layout.addWidget(self._tool_btn)
        parent_layout.addWidget(self._tool_detail)

    def _toggle_tool_detail(self):
        expanded = self._tool_btn.isChecked()
        self._tool_detail.setVisible(expanded)
        txt = self._tool_btn.text()
        if expanded:
            self._tool_btn.setText(txt.replace("▸", "▾", 1))
        else:
            self._tool_btn.setText(txt.replace("▾", "▸", 1))

    def _copy_text(self):
        QApplication.clipboard().setText(self.original_text)
        self.copy_requested.emit(self.original_text)

    def update_appearance(self):
        user_color = self.settings_manager.get_chat_user_color()
        ai_color = self.settings_manager.get_chat_ai_color()
        role_lower = self.role.lower()
        if role_lower == "user":
            color = user_color or _C_USER
        elif role_lower in ("ai", "assistant"):
            color = ai_color or _C_AI
        elif role_lower == "tool":
            color = _C_GREEN
        else:
            color = _C_SYSTEM
        self.current_color = color
        if hasattr(self, 'original_text'):
            self.set_text(self.original_text)

    def set_text(self, text: str):
        self.original_text = text
        if hasattr(self, 'content_label'):
            self.content_label.setText(self._format(text, self.current_color))

    def set_usage(self, usage: dict):
        if not usage:
            return
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0)
        self.footer_label.setText(
            f"tokens: {total}  (in: {prompt} · out: {completion})")
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

        lang_badge = ""
        if lang:
            lang_badge = (
                f'<span style="color:{_C_DIM}; font-size:10px; '
                f'font-family:{_FONT_MONO};">{lang}</span><br>')

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
                    f"font-family: {_FONT_MONO}; margin: 4px 0;"))
            try:
                lexer = get_lexer_by_name(lang) if lang else guess_lexer(code)
            except Exception:
                from pygments.lexers.special import TextLexer
                lexer = TextLexer()
            return lang_badge + highlight(code, lexer, formatter)
        except ImportError:
            escaped = html_mod.escape(code)
            return (
                lang_badge +
                f'<pre style="background:{_C_CODE_BG}; color:{_C_CODE_FG}; '
                f'padding:10px; border-radius:6px; font-family:{_FONT_MONO}; '
                f'font-size:12px; margin:4px 0; white-space:pre-wrap;">'
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
    """Collapsible tool execution tracker — shows thinking + live tool steps."""
    size_changed = Signal()
    show_detail_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(2)

        # Thinking toggle
        self.thought_expander = QPushButton("  ▸ Thinking...")
        self.thought_expander.setCheckable(True)
        self.thought_expander.setChecked(False)
        self.thought_expander.setStyleSheet(f"""
            QPushButton {{
                text-align: left; background: transparent;
                color: {_C_DIM}; border: none; padding: 2px 0;
                font-family: {_FONT_MONO}; font-size: 11px;
            }}
            QPushButton:checked {{ color: {_C_ACCENT}; }}
            QPushButton:hover   {{ color: {_C_ACCENT}; }}
        """)
        self.thought_expander.clicked.connect(self._toggle_thought)
        layout.addWidget(self.thought_expander)

        self.thought_content = QLabel("")
        self.thought_content.setWordWrap(True)
        self.thought_content.setStyleSheet(
            f"color: {_C_DIM}; font-style: italic; font-family: {_FONT_MONO}; "
            f"font-size: 11px; padding: 2px 0 2px 14px; "
            f"border-left: 2px solid #1e1e21; background: transparent;")
        self.thought_content.hide()
        layout.addWidget(self.thought_content)

        # Tool steps
        self.steps_container = QWidget()
        self.steps_layout = QVBoxLayout(self.steps_container)
        self.steps_layout.setContentsMargins(10, 0, 0, 0)
        self.steps_layout.setSpacing(1)
        layout.addWidget(self.steps_container)

        # Status line
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            f"color: #3f3f46; font-family: {_FONT_MONO}; font-size: 10px; "
            f"padding-left: 10px; background: transparent;")
        layout.addWidget(self.status_label)

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("ProgressItem { background: transparent; }")

    def _toggle_thought(self):
        expanded = self.thought_expander.isChecked()
        arrow = "▾" if expanded else "▸"
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
        row_layout.setSpacing(4)
        label = QLabel(f"{icon} {text}")
        label.setStyleSheet(
            f"color: {_C_DIM}; font-family: {_FONT_MONO}; font-size: 11px; "
            f"background: transparent;")
        row_layout.addWidget(label)
        if detail:
            btn = QPushButton("view")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {_C_LINK}; border: none; "
                f"font-family: {_FONT_MONO}; font-size: 10px; padding: 0; }}"
                f"QPushButton:hover {{ color: {_C_ORANGE}; }}")
            btn.clicked.connect(
                lambda: self.show_detail_requested.emit(text, detail))
            row_layout.addWidget(btn)
        row_layout.addStretch()
        self.steps_layout.addWidget(row)
        self.size_changed.emit()

    def update_step_status(self, icon: str, result: str):
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
                    color = _C_GREEN if icon == "✓" else _C_ERR if icon == "✗" else _C_DIM
                    label.setText(f"{current} — {result}")
                    label.setStyleSheet(
                        f"color: {color}; font-family: {_FONT_MONO}; "
                        f"font-size: 11px; background: transparent;")

    def finish(self):
        self.status_label.hide()
        self.size_changed.emit()
