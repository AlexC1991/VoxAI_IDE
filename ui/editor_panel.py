from PySide6.QtWidgets import (QWidget, QVBoxLayout, QTabWidget, QPlainTextEdit, 
                             QLabel, QTabBar, QPushButton, QHBoxLayout, QTextEdit)
from PySide6.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat, QColor, QTextFormat, QPainter
from PySide6.QtCore import Qt, QRegularExpression, Signal, QRect, QSize
import os

class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []

        # Keywords
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#569CD6")) # Visual Studio Blue
        keyword_format.setFontWeight(QFont.Bold)
        keywords = [
            "def", "class", "if", "else", "elif", "while", "for", "return", "import",
            "from", "as", "try", "except", "finally", "with", "pass", "lambda", "global",
            "nonlocal", "in", "is", "not", "and", "or", "break", "continue", "yield"
        ]
        for word in keywords:
            pattern = QRegularExpression(f"\\b{word}\\b")
            self.highlighting_rules.append((pattern, keyword_format))

        # Strings
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#CE9178")) # Visual Studio Orange/Red
        self.highlighting_rules.append((QRegularExpression("\".*\""), string_format))
        self.highlighting_rules.append((QRegularExpression("'.*'"), string_format))

        # Comments
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6A9955")) # Visual Studio Green
        self.highlighting_rules.append((QRegularExpression("#[^\n]*"), comment_format))

    def highlightBlock(self, text):
        for pattern, format in self.highlighting_rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), format)

class GenericHighlighter(QSyntaxHighlighter):
    """Simple highlighter for JS, TS, C++, Java, Rust, Go."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []

        # Keywords (Broad set for many languages)
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#569CD6")) 
        keyword_format.setFontWeight(QFont.Bold)
        keywords = [
            "function", "const", "let", "var", "if", "else", "for", "while", "return", 
            "import", "export", "class", "interface", "public", "private", "protected",
            "static", "void", "null", "true", "false", "new", "this", "super",
            "package", "include", "using", "namespace", "struct", "enum", "type",
            "func", "defer", "go", "match", "impl", "trait", "fn", "let", "mut"
        ]
        for word in keywords:
            pattern = QRegularExpression(f"\\b{word}\\b")
            self.highlighting_rules.append((pattern, keyword_format))

        # Strings
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#CE9178"))
        self.highlighting_rules.append((QRegularExpression("\".*\""), string_format))
        self.highlighting_rules.append((QRegularExpression("'.*'"), string_format))
        self.highlighting_rules.append((QRegularExpression("`.*`"), string_format))

        # Comments (Single line //)
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6A9955"))
        self.highlighting_rules.append((QRegularExpression("//[^\n]*"), comment_format))

    def highlightBlock(self, text):
        for pattern, format in self.highlighting_rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), format)

# --- Line Number Area & Code Editor ---
class LineNumberArea(QWidget):
    def __init__(self, editor):
        # ... existing ...
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.lineNumberAreaPaintEvent(event)

class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        
        self.update_line_number_area_width(0)
        self.highlight_current_line()
        
        # Styling
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1E1E1E;
                color: #D4D4D4;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 13px;
                border: none;
            }
        """)
        self.highlighter = None # Set later based on file type
        self.file_path = None # Store associated file path

    def line_number_area_width(self):
        digits = 1
        max_value = max(1, self.blockCount())
        while max_value >= 10:
            max_value /= 10
            digits += 1
        space = 3 + self.fontMetrics().horizontalAdvance('9') * digits
        return space

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#2D2D30"))
        
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(QColor("#858585"))
                width = self.line_number_area.width()
                height = self.fontMetrics().height()
                painter.drawText(0, top, width, height, Qt.AlignRight, number)
            
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self):
        extra_selections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            line_color = QColor("#2D2D30") # Slightly lighter than BG
            selection.format.setBackground(line_color)
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)
        self.setExtraSelections(extra_selections)


class EditorPanel(QWidget):
    run_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Toolbar Removed (Moved to Main Window)

        # Tab Widget

        # Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        # Tab Styling
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #3E3E42; top: -1px; }
            QTabBar::tab {
                background: #2D2D30;
                color: #999;
                padding: 5px 10px;
                border: 1px solid #1E1E1E;
            }
            QTabBar::tab:selected {
                background: #1E1E1E;
                color: #DDD;
                border-bottom: 2px solid #007ACC;
            }
        """)
        self.layout.addWidget(self.tabs)
        
        # Init with one untitled tab
        # self.new_file("untitled.py", "") <--- Removed per user request

    def new_file(self, title="untitled.py", content=""):
        editor = CodeEditor()
        
        # Determine Syntax Highlighting
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
        # Check if already open
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if getattr(widget, 'file_path', None) == path:
                 # Reload content from disk
                 try:
                     with open(path, 'r', encoding='utf-8') as f:
                         content = f.read()
                     widget.setPlainText(content)
                     self.tabs.setCurrentIndex(i)
                     print(f"[Editor] Reloaded {path}")
                 except Exception as e:
                     print(f"[Editor] Error reloading {path}: {e}")
                 return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"Error opening file: {e}")
            return

        # reuse blank untitled tab if it's the only one and empty?
        # For now, just add new tab.
        editor = self.new_file(title=os.path.basename(path), content=content)
        editor.file_path = path

    def close_tab(self, index):
        self.tabs.removeTab(index)
        # Removed logic that forces new untitled file if count == 0

    def request_run(self):
        # Save current if needed
        current_editor = self.tabs.currentWidget()
        if current_editor and getattr(current_editor, 'file_path', None):
             # Save logic
             try:
                with open(current_editor.file_path, 'w', encoding='utf-8') as f:
                    f.write(current_editor.toPlainText())
                print(f"[DEBUG] Saved {current_editor.file_path}")
             except Exception as e:
                print(f"[ERROR] Saving file: {e}")

        from core.settings import SettingsManager
        settings = SettingsManager()
        entry_point = settings.get_entry_point_script()
        
        # If entry point is set and exists, run it
        if entry_point and os.path.exists(entry_point):
            self.run_requested.emit(entry_point)
        # Else if current file is saved, run it
        elif current_editor and getattr(current_editor, 'file_path', None):
             self.run_requested.emit(current_editor.file_path)
        else:
             print("No file to run.")

    def open_run_config(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from core.settings import SettingsManager
        
        settings = SettingsManager()
        
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Entry Point Script", "", "All Files (*.*)")
        if file_path:
            settings.set_entry_point_script(file_path)
            QMessageBox.information(self, "Run Configuration", f"Entry point set to:\n{file_path}")
