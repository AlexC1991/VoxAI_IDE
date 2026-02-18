import os
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QPlainTextEdit,
    QLabel, QPushButton, QTextEdit, QLineEdit, QCheckBox,
)
from PySide6.QtGui import (
    QFont, QSyntaxHighlighter, QTextCharFormat, QColor, QTextFormat,
    QPainter, QTextCursor, QKeySequence, QShortcut,
)
from PySide6.QtCore import (
    Qt, QRegularExpression, Signal, QRect, QSize, QFileSystemWatcher, QTimer,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Syntax Highlighters
# ---------------------------------------------------------------------------
class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []

        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor("#569CD6"))
        kw_fmt.setFontWeight(QFont.Bold)
        for word in [
            "def", "class", "if", "else", "elif", "while", "for", "return",
            "import", "from", "as", "try", "except", "finally", "with", "pass",
            "lambda", "global", "nonlocal", "in", "is", "not", "and", "or",
            "break", "continue", "yield", "async", "await", "raise", "del",
            "True", "False", "None",
        ]:
            self.highlighting_rules.append(
                (QRegularExpression(rf"\b{word}\b"), kw_fmt))

        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor("#CE9178"))
        self.highlighting_rules.append((QRegularExpression(r'"[^"]*"'), str_fmt))
        self.highlighting_rules.append((QRegularExpression(r"'[^']*'"), str_fmt))

        cmt_fmt = QTextCharFormat()
        cmt_fmt.setForeground(QColor("#6A9955"))
        self.highlighting_rules.append((QRegularExpression(r"#[^\n]*"), cmt_fmt))

        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor("#B5CEA8"))
        self.highlighting_rules.append(
            (QRegularExpression(r"\b\d+(\.\d+)?\b"), num_fmt))

        dec_fmt = QTextCharFormat()
        dec_fmt.setForeground(QColor("#DCDCAA"))
        self.highlighting_rules.append(
            (QRegularExpression(r"@\w+"), dec_fmt))

        func_fmt = QTextCharFormat()
        func_fmt.setForeground(QColor("#DCDCAA"))
        self.highlighting_rules.append(
            (QRegularExpression(r"\bdef\s+(\w+)"), func_fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self.highlighting_rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


class GenericHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []

        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor("#569CD6"))
        kw_fmt.setFontWeight(QFont.Bold)
        for word in [
            "function", "const", "let", "var", "if", "else", "for", "while",
            "return", "import", "export", "class", "interface", "public",
            "private", "protected", "static", "void", "null", "true", "false",
            "new", "this", "super", "package", "include", "using", "namespace",
            "struct", "enum", "type", "func", "defer", "go", "match", "impl",
            "trait", "fn", "mut", "async", "await", "yield",
        ]:
            self.highlighting_rules.append(
                (QRegularExpression(rf"\b{word}\b"), kw_fmt))

        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor("#CE9178"))
        self.highlighting_rules.append((QRegularExpression(r'"[^"]*"'), str_fmt))
        self.highlighting_rules.append((QRegularExpression(r"'[^']*'"), str_fmt))
        self.highlighting_rules.append((QRegularExpression(r"`[^`]*`"), str_fmt))

        cmt_fmt = QTextCharFormat()
        cmt_fmt.setForeground(QColor("#6A9955"))
        self.highlighting_rules.append((QRegularExpression(r"//[^\n]*"), cmt_fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self.highlighting_rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


# ---------------------------------------------------------------------------
# Line Number Area
# ---------------------------------------------------------------------------
class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.lineNumberAreaPaintEvent(event)

    def mouseDoubleClickEvent(self, event):
        y = event.position().y() if hasattr(event, 'position') else event.y()
        block = self.editor.firstVisibleBlock()
        top = self.editor.blockBoundingGeometry(block).translated(
            self.editor.contentOffset()).top()
        while block.isValid():
            btop = self.editor.blockBoundingGeometry(block).translated(
                self.editor.contentOffset()).top()
            bbot = btop + self.editor.blockBoundingRect(block).height()
            if btop <= y <= bbot:
                self.editor.toggle_fold(block)
                return
            block = block.next()
        super().mouseDoubleClickEvent(event)


# ---------------------------------------------------------------------------
# Code Editor with bracket matching
# ---------------------------------------------------------------------------
_BRACKET_PAIRS = {'{': '}', '(': ')', '[': ']'}
_BRACKET_CLOSE = {v: k for k, v in _BRACKET_PAIRS.items()}


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)

        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self._on_cursor_moved)

        self.update_line_number_area_width(0)
        self._on_cursor_moved()

        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1E1E1E; color: #D4D4D4;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 13px; border: none; padding: 5px;
            }
        """)
        self.highlighter = None
        self.file_path = None

    # --- Line numbers ---
    def line_number_area_width(self):
        digits = 1
        mx = max(1, self.blockCount())
        while mx >= 10:
            mx //= 10
            digits += 1
        return 3 + self.fontMetrics().horizontalAdvance('9') * digits

    def update_line_number_area_width(self, _=0):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(
                0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(cr.left(), cr.top(),
                  self.line_number_area_width(), cr.height()))

    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#2D2D30"))
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = int(self.blockBoundingGeometry(block)
                  .translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#858585"))
                painter.drawText(0, top, self.line_number_area.width(),
                                 self.fontMetrics().height(),
                                 Qt.AlignRight, str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            num += 1

    # --- Cursor movement: current-line + bracket matching ---
    def _on_cursor_moved(self):
        extra = []
        # Current line highlight
        if not self.isReadOnly():
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(QColor("#2D2D30"))
            sel.format.setProperty(QTextFormat.FullWidthSelection, True)
            sel.cursor = self.textCursor()
            sel.cursor.clearSelection()
            extra.append(sel)
        # Bracket matching
        extra.extend(self._bracket_selections())
        self.setExtraSelections(extra)

    def _bracket_selections(self) -> list:
        sels = []
        cursor = self.textCursor()
        doc = self.document()
        pos = cursor.position()
        if pos <= 0 and doc.characterCount() == 0:
            return sels

        def char_at(p):
            c = QTextCursor(doc)
            c.setPosition(p)
            c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor)
            return c.selectedText()

        ch = char_at(pos) if pos < doc.characterCount() else ''
        match_pos = -1
        if ch in _BRACKET_PAIRS:
            match_pos = self._find_matching_bracket(pos, ch, _BRACKET_PAIRS[ch], forward=True)
        elif ch in _BRACKET_CLOSE:
            match_pos = self._find_matching_bracket(pos, ch, _BRACKET_CLOSE[ch], forward=False)
        else:
            if pos > 0:
                ch = char_at(pos - 1)
                if ch in _BRACKET_PAIRS:
                    match_pos = self._find_matching_bracket(pos - 1, ch, _BRACKET_PAIRS[ch], forward=True)
                    pos = pos - 1
                elif ch in _BRACKET_CLOSE:
                    match_pos = self._find_matching_bracket(pos - 1, ch, _BRACKET_CLOSE[ch], forward=False)
                    pos = pos - 1

        if match_pos >= 0:
            fmt = QTextCharFormat()
            fmt.setBackground(QColor("#3a3a3a"))
            fmt.setForeground(QColor("#ffd700"))
            for p in (pos, match_pos):
                sel = QTextEdit.ExtraSelection()
                sel.format = fmt
                sel.cursor = QTextCursor(doc)
                sel.cursor.setPosition(p)
                sel.cursor.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor)
                sels.append(sel)
        return sels

    def _find_matching_bracket(self, start, open_ch, close_ch, forward=True):
        doc = self.document()
        depth = 0
        pos = start
        length = doc.characterCount()
        while 0 <= pos < length:
            c = QTextCursor(doc)
            c.setPosition(pos)
            c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor)
            ch = c.selectedText()
            if ch == open_ch:
                depth += 1 if forward else -1
            elif ch == close_ch:
                depth += -1 if forward else 1
            if depth == 0:
                return pos
            pos += 1 if forward else -1
        return -1

    # --- Code folding toggle via gutter double-click ---
    def toggle_fold(self, block):
        """Toggle visibility of blocks inside a function/class starting at `block`."""
        text = block.text().rstrip()
        if not (text.endswith(':') or text.endswith('{')):
            return
        indent = len(text) - len(text.lstrip())
        nxt = block.next()
        changed = False
        while nxt.isValid():
            nxt_text = nxt.text()
            if nxt_text.strip() == '':
                nxt = nxt.next()
                continue
            nxt_indent = len(nxt_text) - len(nxt_text.lstrip())
            if nxt_indent <= indent:
                break
            nxt.setVisible(not nxt.isVisible())
            changed = True
            nxt = nxt.next()
        if changed:
            self.viewport().update()
            self.document().markContentsDirty(
                block.position(), self.document().characterCount() - block.position())


# ---------------------------------------------------------------------------
# Find & Replace Bar
# ---------------------------------------------------------------------------
class FindReplaceBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "background: #27272a; border-top: 1px solid #3f3f46; padding: 4px;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)

        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find…")
        self.find_input.setStyleSheet(
            "background: #18181b; color: #e4e4e7; border: 1px solid #3f3f46; "
            "border-radius: 3px; padding: 3px 6px; font-size: 12px; "
            "font-family: 'Consolas', monospace;")
        self.find_input.setFixedWidth(200)
        self.find_input.returnPressed.connect(lambda: self._do_find(forward=True))
        lay.addWidget(self.find_input)

        self.replace_input = QLineEdit()
        self.replace_input.setPlaceholderText("Replace…")
        self.replace_input.setStyleSheet(self.find_input.styleSheet())
        self.replace_input.setFixedWidth(200)
        lay.addWidget(self.replace_input)

        self.case_cb = QCheckBox("Aa")
        self.case_cb.setToolTip("Case sensitive")
        self.case_cb.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        lay.addWidget(self.case_cb)

        btn_css = (
            "QPushButton { background: #3f3f46; color: #e4e4e7; border: none; "
            "border-radius: 3px; padding: 3px 10px; font-size: 11px; "
            "font-family: 'Consolas', monospace; }"
            "QPushButton:hover { background: #52525b; color: #00f3ff; }")

        for label, slot in [
            ("Prev", lambda: self._do_find(forward=False)),
            ("Next", lambda: self._do_find(forward=True)),
            ("Replace", self._do_replace),
            ("All", self._do_replace_all),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(btn_css)
            btn.clicked.connect(slot)
            lay.addWidget(btn)

        self.match_label = QLabel("")
        self.match_label.setStyleSheet(
            "color: #a1a1aa; font-size: 11px; font-family: 'Consolas', monospace;")
        lay.addWidget(self.match_label)

        lay.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #a1a1aa; border: none; "
            "font-size: 14px; } QPushButton:hover { color: #ef4444; }")
        close_btn.clicked.connect(self.hide)
        lay.addWidget(close_btn)

        self._editor: CodeEditor | None = None
        self.hide()

    def attach(self, editor: CodeEditor | None):
        self._editor = editor

    def activate(self):
        editor = self._editor
        if editor:
            sel = editor.textCursor().selectedText()
            if sel:
                self.find_input.setText(sel)
        self.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def _flags(self, forward=True):
        from PySide6.QtGui import QTextDocument
        flags = QTextDocument.FindFlags()
        if self.case_cb.isChecked():
            flags |= QTextDocument.FindCaseSensitively
        if not forward:
            flags |= QTextDocument.FindBackward
        return flags

    def _do_find(self, forward=True):
        editor = self._editor
        if not editor:
            return
        text = self.find_input.text()
        if not text:
            return
        flags = self._flags(forward=forward)
        found = editor.find(text, flags)
        if not found:
            cursor = editor.textCursor()
            cursor.movePosition(
                QTextCursor.Start if forward else QTextCursor.End)
            editor.setTextCursor(cursor)
            found = editor.find(text, flags)
        self.match_label.setText("" if found else "No matches")

    def _do_replace(self):
        editor = self._editor
        if not editor or not self.find_input.text():
            return
        cursor = editor.textCursor()
        if cursor.hasSelection():
            selected = cursor.selectedText()
            target = self.find_input.text()
            match = (selected == target) if self.case_cb.isChecked() else (selected.lower() == target.lower())
            if match:
                cursor.insertText(self.replace_input.text())
        self._do_find(forward=True)

    def _do_replace_all(self):
        editor = self._editor
        if not editor or not self.find_input.text():
            return
        content = editor.toPlainText()
        find = self.find_input.text()
        repl = self.replace_input.text()
        if self.case_cb.isChecked():
            count = content.count(find)
            content = content.replace(find, repl)
        else:
            import re as _re
            count = len(_re.findall(_re.escape(find), content, _re.IGNORECASE))
            content = _re.sub(_re.escape(find), repl, content, flags=_re.IGNORECASE)
        editor.setPlainText(content)
        self.match_label.setText(f"Replaced {count}")


# ---------------------------------------------------------------------------
# Editor Panel
# ---------------------------------------------------------------------------
class EditorPanel(QWidget):
    run_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border-top: 1px solid #27272a; background: #18181b;
                position: absolute; top: -1px;
            }
            QTabBar::tab {
                background: #18181b; color: #a1a1aa;
                padding: 6px 12px; min-width: 60px; max-width: 180px;
                border-bottom: none; border-top: 2px solid transparent;
                margin-right: -1px; font-family: 'Segoe UI', sans-serif;
                font-size: 11px; font-weight: 500;
            }
            QTabBar::tab:selected {
                background: #27272a; color: #00f3ff;
                border-top: 2px solid #ff9900; font-weight: 600;
            }
            QTabBar::tab:hover:!selected {
                background: #232326; color: #e4e4e7;
                border-top: 2px solid #3f3f46;
            }
            QTabBar::close-button {
                image: url(resources/close_tab.png);
                subcontrol-position: right; padding: 2px; margin-right: 4px;
            }
            QTabBar::close-button:hover {
                background: #ef4444; border-radius: 3px;
            }
        """)
        self._layout.addWidget(self.tabs)

        # Find & Replace bar
        self.find_bar = FindReplaceBar()
        self._layout.addWidget(self.find_bar)

        # Keyboard shortcut: Ctrl+F
        self._find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._find_shortcut.activated.connect(self._toggle_find)

        # File watcher for external changes
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_external_change)
        self._pending_reloads: set[str] = set()
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(300)
        self._reload_timer.timeout.connect(self._process_reloads)

    # --- Find & Replace ---
    def _toggle_find(self):
        editor = self.tabs.currentWidget()
        if isinstance(editor, CodeEditor):
            self.find_bar.attach(editor)
            if self.find_bar.isVisible():
                self.find_bar.hide()
            else:
                self.find_bar.activate()

    def _on_tab_changed(self, index):
        editor = self.tabs.widget(index)
        if isinstance(editor, CodeEditor):
            self.find_bar.attach(editor)

    # --- File watcher ---
    def _watch(self, path: str):
        if path and os.path.isfile(path):
            watched = self._watcher.files()
            if path not in watched:
                self._watcher.addPath(path)

    def _on_external_change(self, path: str):
        self._pending_reloads.add(path)
        self._reload_timer.start()
        if os.path.isfile(path):
            self._watcher.addPath(path)

    def _process_reloads(self):
        paths = list(self._pending_reloads)
        self._pending_reloads.clear()
        for path in paths:
            for i in range(self.tabs.count()):
                w = self.tabs.widget(i)
                if getattr(w, 'file_path', None) == path:
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            new_content = f.read()
                        if new_content != w.toPlainText():
                            cursor_pos = w.textCursor().position()
                            w.setPlainText(new_content)
                            c = w.textCursor()
                            c.setPosition(min(cursor_pos, len(new_content)))
                            w.setTextCursor(c)
                            log.info("Auto-reloaded %s", path)
                    except Exception as e:
                        log.debug("Reload failed for %s: %s", path, e)

    # --- Tab management ---
    def new_file(self, title="untitled.py", content=""):
        editor = CodeEditor()
        _, ext = os.path.splitext(title)
        if ext == '.py':
            editor.highlighter = PythonHighlighter(editor.document())
        else:
            editor.highlighter = GenericHighlighter(editor.document())
        editor.setPlainText(content)
        editor.file_path = None
        self.tabs.addTab(editor, title)
        self.tabs.setCurrentWidget(editor)
        return editor

    def load_file(self, path):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if getattr(w, 'file_path', None) == path:
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        w.setPlainText(f.read())
                    self.tabs.setCurrentIndex(i)
                except Exception as e:
                    log.error("Reload %s: %s", path, e)
                return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            log.error("Open %s: %s", path, e)
            return

        editor = self.new_file(title=os.path.basename(path), content=content)
        editor.file_path = path
        self._watch(path)

    def close_tab(self, index):
        w = self.tabs.widget(index)
        path = getattr(w, 'file_path', None)
        if path:
            try:
                self._watcher.removePath(path)
            except Exception:
                pass
        self.tabs.removeTab(index)

    def request_run(self):
        current = self.tabs.currentWidget()
        if current and getattr(current, 'file_path', None):
            try:
                with open(current.file_path, 'w', encoding='utf-8') as f:
                    f.write(current.toPlainText())
            except Exception as e:
                log.error("Save before run: %s", e)

        from core.settings import SettingsManager
        settings = SettingsManager()
        entry = settings.get_entry_point_script()
        if entry and os.path.exists(entry):
            self.run_requested.emit(entry)
        elif current and getattr(current, 'file_path', None):
            self.run_requested.emit(current.file_path)

    def get_active_context(self) -> dict | None:
        """Return the currently focused file's path, cursor position, and nearby lines."""
        editor = self.tabs.currentWidget()
        if not isinstance(editor, CodeEditor):
            return None
        path = getattr(editor, 'file_path', None)
        if not path:
            return None

        cursor = editor.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1

        # Grab a window of code around the cursor (±15 lines)
        text = editor.toPlainText()
        lines = text.splitlines()
        start = max(0, line - 16)
        end = min(len(lines), line + 15)
        snippet_lines = []
        for i in range(start, end):
            marker = " >> " if i == line - 1 else "    "
            snippet_lines.append(f"{i+1:4d}{marker}{lines[i]}")
        snippet = "\n".join(snippet_lines)

        return {
            "file": path,
            "line": line,
            "col": col,
            "total_lines": len(lines),
            "snippet": snippet,
        }

    # --- Diff viewing ---
    def show_diff(self, file_path: str, diff_text: str):
        if not diff_text or not diff_text.strip():
            return
        tab_title = f"DIFF: {os.path.basename(file_path)}"
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == tab_title:
                editor = self.tabs.widget(i)
                editor.setPlainText(diff_text)
                self._apply_diff_highlights(editor, diff_text)
                self.tabs.setCurrentIndex(i)
                return

        editor = CodeEditor()
        editor.setReadOnly(True)
        editor.file_path = None
        editor.setPlainText(diff_text)
        self._apply_diff_highlights(editor, diff_text)
        idx = self.tabs.addTab(editor, tab_title)
        self.tabs.setCurrentIndex(idx)
        self.tabs.tabBar().setTabTextColor(idx, QColor("#ff9900"))

    def show_diffs_batch(self, diffs: list):
        last_idx = -1
        for file_path, diff_text in diffs:
            if not diff_text or not diff_text.strip():
                continue
            tab_title = f"DIFF: {os.path.basename(file_path)}"
            reused = False
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == tab_title:
                    editor = self.tabs.widget(i)
                    editor.setPlainText(diff_text)
                    self._apply_diff_highlights(editor, diff_text)
                    last_idx = i
                    reused = True
                    break
            if not reused:
                editor = CodeEditor()
                editor.setReadOnly(True)
                editor.file_path = None
                editor.setPlainText(diff_text)
                self._apply_diff_highlights(editor, diff_text)
                last_idx = self.tabs.addTab(editor, tab_title)
                self.tabs.tabBar().setTabTextColor(last_idx, QColor("#ff9900"))
        if last_idx >= 0:
            self.tabs.setCurrentIndex(last_idx)

    def _apply_diff_highlights(self, editor, diff_text: str):
        extra = []
        block = editor.document().begin()
        while block.isValid():
            text = block.text()
            sel = QTextEdit.ExtraSelection()
            sel.format.setProperty(QTextFormat.FullWidthSelection, True)
            sel.cursor = editor.textCursor()
            sel.cursor.setPosition(block.position())
            if text.startswith("+") and not text.startswith("+++"):
                sel.format.setBackground(QColor(0, 80, 0, 80))
                sel.format.setForeground(QColor("#4ec9b0"))
                extra.append(sel)
            elif text.startswith("-") and not text.startswith("---"):
                sel.format.setBackground(QColor(120, 0, 0, 80))
                sel.format.setForeground(QColor("#f14c4c"))
                extra.append(sel)
            elif text.startswith("@@"):
                sel.format.setBackground(QColor(0, 60, 120, 60))
                sel.format.setForeground(QColor("#569CD6"))
                extra.append(sel)
            block = block.next()
        editor.setExtraSelections(extra)

    def open_run_config(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from core.settings import SettingsManager
        settings = SettingsManager()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Entry Point Script", "", "All Files (*.*)")
        if file_path:
            settings.set_entry_point_script(file_path)
            QMessageBox.information(
                self, "Run Configuration",
                f"Entry point set to:\n{file_path}")
