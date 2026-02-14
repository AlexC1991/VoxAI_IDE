
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from PySide6.QtCore import QRegularExpression

class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.highlighting_rules = []

        # Keywords
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("#C586C0")) # Purple-ish
        keyword_format.setFontWeight(QFont.Bold)
        keywords = [
            "def", "class", "if", "else", "elif", "try", "except", "return", 
            "import", "from", "while", "for", "in", "break", "continue", 
            "and", "or", "not", "is", "None", "True", "False", "with", "as",
            "lambda", "pass", "raise", "print"
        ]
        for word in keywords:
            pattern = QRegularExpression(fr"\b{word}\b")
            self.highlighting_rules.append((pattern, keyword_format))

        # Strings (Double quotes)
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("#CE9178")) # Orange-ish
        pattern = QRegularExpression(r"\".*\"")
        self.highlighting_rules.append((pattern, string_format))
        
        # Strings (Single quotes)
        pattern = QRegularExpression(r"'.*'")
        self.highlighting_rules.append((pattern, string_format))

        # Comments
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6A9955")) # Green
        pattern = QRegularExpression(r"#[^\n]*")
        self.highlighting_rules.append((pattern, comment_format))
        
        # Numbers
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#B5CEA8")) # Light Green
        pattern = QRegularExpression(r"\b[0-9]+\b")
        self.highlighting_rules.append((pattern, number_format))
        
        # Decorators
        decorator_format = QTextCharFormat()
        decorator_format.setForeground(QColor("#DCDCAA")) # Yellow-ish
        pattern = QRegularExpression(r"@[^\n]*")
        self.highlighting_rules.append((pattern, decorator_format))
        
        # Function defs
        # pattern = QRegularExpression(r"\bdef\s+([A-Za-z0-9_]+)")
        # We can't do capturing groups easily in this simple loop, 
        # but we can try to highlight "def" separately (done above).
        
    def highlightBlock(self, text):
        for pattern, format in self.highlighting_rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), format)
