"""Chat display widgets — Claude Code inspired inline terminal style."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QSizePolicy,
)
from PySide6.QtCore import Qt, QSize, Signal
import html as html_mod
import re
import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colours (VS Code Dark Theme)
# ---------------------------------------------------------------------------
_C_BG        = "#1e1e1e"   # VS Code Main Background
_C_USER      = "#d4d4d8"   # Light Gray (Zinc-300)
_C_AI        = "#cccccc"   # Standard Gray
_C_SYSTEM    = "#858585"   # Dimmed Gray
_C_DIM       = "#6e6e6e"   # Darker Gray
_C_ACCENT    = "#4ec9b0"   # Teal-ish
_C_LINK      = "#3794ff"   # Blue
_C_CODE_BG   = "#2d2d2d"   # Slightly lighter block background
_C_CODE_FG   = "#d4d4d8"
_C_ERR       = "#f14c4c"   # Red

_FONT_MONO   = "Consolas, 'Courier New', 'Fira Code', monospace"
_FONT_SANS   = "'Segoe UI', 'Inter', system-ui, sans-serif"

# ---------------------------------------------------------------------------
# MessageItem — a single chat message (user / AI / system)
# ---------------------------------------------------------------------------
class MessageItem(QWidget):
    """Flat, inline message widget.  No bubbles — just role label + content."""

    def __init__(self, role: str, text: str, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(2)

        # --- Role header ---
        role_lower = role.lower()
        if role_lower == "user":
            prefix = "> "
            role_name = "You"
            color = _C_USER
        elif role_lower in ("ai", "assistant"):
            prefix = ""
            role_name = "VoxAI"
            color = _C_AI
        else:
            prefix = ""
            role_name = "System"
            color = _C_SYSTEM

        self.role_label = QLabel(f"{prefix}{role_name}")
        self.role_label.setStyleSheet(
            f"color: {color}; font-family: {_FONT_MONO}; font-size: 12px; "
            f"font-weight: bold; background: transparent; padding: 0; margin: 0;"
        )
        layout.addWidget(self.role_label)

        # --- Content ---
        self.content_label = QLabel()
        self.content_label.setWordWrap(True)
        self.content_label.setTextFormat(Qt.RichText)
        self.content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.content_label.setOpenExternalLinks(True)
        self.content_label.setStyleSheet(
            f"color: {_C_AI}; font-family: {_FONT_MONO}; font-size: 13px; "
            f"background: transparent; padding: 2px 0 0 0; margin: 0; "
            f"line-height: 1.5;"
        )

        formatted = self._format(text)
        self.content_label.setText(formatted)
        layout.addWidget(self.content_label)

        # Widget-level style (flat, no border)
        self.setStyleSheet(f"MessageItem {{ background: transparent; }}")

    # ---- Formatting helpers ----
    def _format(self, text: str) -> str:
        """Convert markdown-ish text to simple HTML (code blocks highlighted)."""
        if not text:
            return ""

        parts = re.split(r'(```\w*\n.*?```)', text, flags=re.DOTALL)
        result = ""

        for part in parts:
            if part.startswith("```") and part.endswith("```"):
                result += self._render_code_block(part)
            else:
                result += self._render_text(part)
        return result

    def _render_code_block(self, block: str) -> str:
        """Render a fenced code block with pygments if available."""
        content = block[3:-3]
        if '\n' in content:
            lang, code = content.split('\n', 1)
            lang = lang.strip()
        else:
            lang = ""
            code = content

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
                    f"font-family: {_FONT_MONO}; margin: 6px 0;"
                ),
            )
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
                f'{escaped}</pre>'
            )

    def _render_text(self, text: str) -> str:
        safe = html_mod.escape(text)
        # Bold
        safe = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', safe)
        # Inline code
        safe = re.sub(r'`([^`]+)`',
                       rf'<code style="background:{_C_CODE_BG}; color:{_C_LINK}; '
                       rf'padding:1px 4px; border-radius:3px; font-family:{_FONT_MONO}; '
                       rf'font-size:12px;">\1</code>', safe)
        # Newlines
        safe = safe.replace('\n', '<br>')
        return (
            f'<span style="color:{_C_AI}; font-family:{_FONT_MONO}; '
            f'font-size:13px;">{safe}</span>'
        )


# ---------------------------------------------------------------------------
# ProgressItem — shows thinking / tool steps
# ---------------------------------------------------------------------------
class ProgressItem(QWidget):
    """Collapsible thought-process + tool step tracker."""

    size_changed = Signal()
    show_detail_requested = Signal(str, str)  # title, content

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(4)

        # Thought expander
        self.thought_expander = QPushButton("  Thinking...")
        self.thought_expander.setCheckable(True)
        self.thought_expander.setChecked(False)
        self.thought_expander.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                background: transparent;
                color: {_C_DIM};
                border: none;
                padding: 4px 8px;
                font-family: {_FONT_MONO};
                font-size: 12px;
            }}
            QPushButton:checked {{ color: {_C_AI}; }}
            QPushButton:hover   {{ color: {_C_AI}; }}
        """)
        self.thought_expander.clicked.connect(self._toggle_thought)
        layout.addWidget(self.thought_expander)

        # Thought content (hidden by default)
        self.thought_content = QLabel("(Analyzing request...)")
        self.thought_content.setWordWrap(True)
        self.thought_content.setStyleSheet(
            f"color: {_C_DIM}; font-style: italic; font-family: {_FONT_MONO}; "
            f"font-size: 11px; padding: 4px 12px; "
            f"border-left: 2px solid {_C_DIM}; background: transparent;"
        )
        self.thought_content.hide()
        layout.addWidget(self.thought_content)

        # Steps container
        self.steps_container = QWidget()
        self.steps_layout = QVBoxLayout(self.steps_container)
        self.steps_layout.setContentsMargins(12, 2, 0, 2)
        self.steps_layout.setSpacing(3)
        layout.addWidget(self.steps_container)

        # Status
        self.status_label = QLabel("...")
        self.status_label.setStyleSheet(
            f"color: {_C_DIM}; font-family: {_FONT_MONO}; font-size: 11px; "
            f"padding-left: 12px; background: transparent;"
        )
        layout.addWidget(self.status_label)

        self.setStyleSheet("ProgressItem { background: transparent; }")

    def _toggle_thought(self):
        expanded = self.thought_expander.isChecked()
        arrow = "v" if expanded else ">"
        self.thought_expander.setText(f"  {arrow} Thinking...")
        self.thought_content.setVisible(expanded)
        self.size_changed.emit()

    def set_thought(self, text):
        if not text:
            return
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
            f"background: transparent;"
        )
        row_layout.addWidget(label)

        if detail:
            btn = QPushButton("view")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {_C_LINK};
                    border: none;
                    font-family: {_FONT_MONO};
                    font-size: 10px;
                    text-decoration: underline;
                    padding: 0;
                }}
                QPushButton:hover {{ color: {_C_USER}; }}
            """)
            btn.clicked.connect(lambda: self.show_detail_requested.emit(text, detail))
            row_layout.addWidget(btn)

        row_layout.addStretch()
        self.steps_layout.addWidget(row)
        self.size_changed.emit()

    def finish(self):
        self.status_label.hide()
        self.size_changed.emit()
