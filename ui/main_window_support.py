import logging

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from core.ai_client import AIClient


log = logging.getLogger(__name__)


class CommandPalette(QDialog):
    """Ctrl+Shift+P quick-action launcher."""

    def __init__(self, commands: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Command Palette")
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setFixedSize(500, 340)
        self.setStyleSheet(
            "QDialog { background: #1e1e1e; border: 1px solid #00f3ff; "
            "border-radius: 8px; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command…")
        self._input.setStyleSheet(
            "background: #27272a; color: #e4e4e7; border: 1px solid #3f3f46; "
            "border-radius: 4px; padding: 8px; font-size: 13px; "
            "font-family: 'Consolas', monospace;"
        )
        self._input.textChanged.connect(self._filter)
        lay.addWidget(self._input)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background: #18181b; border: none; color: #e4e4e7; "
            "font-family: 'Consolas', monospace; font-size: 12px; }"
            "QListWidget::item { padding: 8px; border-radius: 4px; }"
            "QListWidget::item:selected { background: #27272a; color: #00f3ff; }"
            "QListWidget::item:hover { background: #232326; }"
        )
        self._list.itemActivated.connect(self._run)
        lay.addWidget(self._list)

        self._commands = commands
        for name, _ in commands:
            self._list.addItem(name)
        self._input.setFocus()

    def _filter(self, text):
        text_lower = text.lower()
        self._list.clear()
        for name, _ in self._commands:
            if text_lower in name.lower():
                self._list.addItem(name)

    def _run(self, item: QListWidgetItem):
        text = item.text()
        for name, fn in self._commands:
            if name == text:
                self.accept()
                fn()
                return


class OpenRouterHealthWorker(QObject):
    finished = Signal(dict)

    def run(self):
        try:
            summary = AIClient.refresh_openrouter_health()
        except Exception as e:
            log.error("OpenRouter background health refresh failed: %s", e)
            summary = {"error": str(e), "skipped_reason": "exception"}
        self.finished.emit(summary)


ABOUT_TEXT = (
    "<h3>VoxAI Coding Agent IDE</h3>"
    "<p><b>Version:</b> 2.0 Agentic</p><hr>"
    "<h4>Local Models (GGUF)</h4>"
    "<p>Place <code>.gguf</code> files in <code>/models/llm/</code> and "
    "they appear in Model Selection automatically.</p>"
    "<h4>Providers</h4>"
    "<p>OpenAI, Anthropic, Google, OpenRouter, DeepSeek, and more.</p>"
    "<h4>Terminal Mode</h4>"
    "<p>Click the <b>⌨</b> icon in the top bar (or use the command palette) "
    "to switch to a Claude Code-style CLI. The IDE minimizes to tray.</p><hr>"
    "<p><i>Built for the Vibe-Coder.</i></p>"
)

_ = lambda x: x

_GLOBAL_STYLE = """
    QMainWindow { background-color: #111113; color: #e4e4e7; }
    QWidget { font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; color: #e4e4e7; }
    QScrollBar:vertical { border: none; background: transparent; width: 8px; margin: 0; }
    QScrollBar::handle:vertical { background: #3f3f46; min-height: 24px; border-radius: 4px; }
    QScrollBar::handle:vertical:hover { background: #52525b; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar:horizontal { border: none; background: transparent; height: 8px; margin: 0; }
    QScrollBar::handle:horizontal { background: #3f3f46; min-width: 24px; border-radius: 4px; }
    QScrollBar::handle:horizontal:hover { background: #52525b; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    QSplitter::handle { background: #27272a; }
    QSplitter::handle:horizontal { width: 2px; }
    QSplitter::handle:vertical { height: 2px; }
    QSplitter::handle:hover { background: #3f3f46; }
    QSplitter::handle:pressed { background: #00f3ff; }
    QToolTip { background: #1e1e21; color: #e4e4e7; border: 1px solid #3f3f46; padding: 5px 8px; border-radius: 6px; font-size: 12px; }
    QMenuBar { background: #111113; color: #a1a1aa; border-bottom: 1px solid #1e1e21; font-size: 12px; }
    QMenuBar::item { background: transparent; padding: 6px 10px; border-radius: 4px; }
    QMenuBar::item:selected { background: #1e1e21; color: #e4e4e7; }
    QMenu { background: #1e1e21; border: 1px solid #27272a; border-radius: 8px; padding: 4px; }
    QMenu::item { padding: 6px 28px 6px 12px; border-radius: 4px; color: #a1a1aa; }
    QMenu::item:selected { background: #27272a; color: #e4e4e7; }
    QMenu::separator { height: 1px; background: #27272a; margin: 4px 8px; }
    QTreeView, QListView { background: #141416; border: none; outline: none; }
    QTreeView::item, QListView::item { padding: 5px 8px; border-radius: 4px; }
    QTreeView::item:hover, QListView::item:hover { background: #1e1e21; }
    QTreeView::item:selected, QListView::item:selected { background: #1a1a2e; color: #00f3ff; }
    QTabWidget::pane { border: none; background: #141416; }
    QTabBar::tab { background: #1e1e21; color: #71717a; border: none; padding: 6px 14px; border-radius: 6px 6px 0 0; margin-right: 2px; }
    QTabBar::tab:selected { background: #141416; color: #e4e4e7; }
    QTabBar::tab:hover { color: #a1a1aa; }
"""