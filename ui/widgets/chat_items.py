from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton, 
                             QListWidget, QListWidgetItem, QFrame, QHBoxLayout)
from PySide6.QtCore import Qt, QSize, Signal

class ProgressItem(QWidget):
    size_changed = Signal()
    show_detail_requested = Signal(str, str) # title, content

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 8, 5, 8) # More vertical padding
        self.layout.setSpacing(6) # More spacing between elements

        # 1. Thought Process (Collapsible)
        self.thought_expander = QPushButton("▶ Thought Process")
        self.thought_expander.setCheckable(True)
        self.thought_expander.setChecked(False) 
        self.thought_expander.setStyleSheet("""
            QPushButton {
                text-align: left;
                background-color: rgba(255, 255, 255, 0.05);
                color: #AAA;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: bold;
                min-height: 20px;
            }
            QPushButton:checked { 
                background-color: rgba(255, 255, 255, 0.1);
                color: #DDD; 
            }
            QPushButton:hover { 
                background-color: rgba(255, 255, 255, 0.1);
                color: #FFF; 
            }
        """)
        self.thought_expander.clicked.connect(self.toggle_thought)
        self.layout.addWidget(self.thought_expander)

        self.thought_content = QLabel("(Analyzing request...)")
        self.thought_content.setWordWrap(True)
        self.thought_content.setStyleSheet("color: #CCC; font-style: italic; padding: 10px; border-left: 2px solid #555; background-color: rgba(0,0,0,0.2); border-radius: 4px;")
        self.thought_content.hide()
        self.layout.addWidget(self.thought_content)

        # 2. Progress Updates (Steps)
        self.steps_container = QWidget()
        self.steps_layout = QVBoxLayout(self.steps_container)
        self.steps_layout.setContentsMargins(15, 5, 5, 5) # Better indentation
        self.steps_layout.setSpacing(6) # Spacing between steps
        self.layout.addWidget(self.steps_container)
        
        # 3. Status / Spinner
        self.status_label = QLabel("Thinking...")
        self.status_label.setStyleSheet("color: #888; font-style: italic; font-size: 11px; margin-left: 5px;")
        self.layout.addWidget(self.status_label)

    def toggle_thought(self):
        if self.thought_expander.isChecked():
            self.thought_expander.setText("▼ Thought Process")
            self.thought_content.show()
        else:
            self.thought_expander.setText("▶ Thought Process")
            self.thought_content.hide()
        
        # Emit signal to let parent resize the QListWidgetItem
        self.size_changed.emit()

    def set_thought(self, text):
        if not text: return
        self.thought_content.setText(text)
        # If already expanded, sizing might change
        if self.thought_expander.isChecked():
            self.size_changed.emit()

    def add_step(self, icon, text, detail=None):
        """Adds a step like '📝 Written main.py'. If detail provided, adds a view button."""
        
        step_widget = QWidget()
        step_layout = QHBoxLayout(step_widget)
        step_layout.setContentsMargins(0, 0, 0, 0)
        step_layout.setSpacing(5)
        
        label = QLabel(f"{icon} {text}")
        label.setStyleSheet("color: #AAA; font-size: 11px;")
        step_layout.addWidget(label)
        
        if detail:
            btn = QPushButton("View Changes")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #4EC9B0;
                    border: 1px solid #4EC9B0;
                    border-radius: 3px;
                    padding: 2px 5px;
                    font-size: 10px;
                }
                QPushButton:hover { background-color: rgba(78, 201, 176, 0.1); }
            """)
            btn.clicked.connect(lambda: self.show_detail_requested.emit(text, detail))
            step_layout.addWidget(btn)
            
        step_layout.addStretch()
        
        self.steps_layout.addWidget(step_widget)
        self.size_changed.emit()
        
    def finish(self):
        """Called when AI is done."""
        self.status_label.hide()
        self.size_changed.emit()
        
class MessageItem(QWidget):
    def __init__(self, role, text, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        
        # Header (Role Label)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        # Icons
        icon_text = ""
        role_text = role
        
        if role.lower() == "user":
            icon_text = "👤"
            role_text = "You"
            color = "#569CD6" # VSCode Blue
            bg_color = "rgba(30, 30, 30, 0.6)" # Darker
            border_color = "#569CD6"
        elif role.lower() in ["ai", "assistant"]:
            icon_text = "🤖"
            role_text = "VoxAI"
            color = "#4EC9B0" # Teal
            bg_color = "rgba(30, 30, 30, 0.6)"
            border_color = "#4EC9B0"
        else: # System
            icon_text = "⚙️" 
            role_text = "System"
            color = "#CE9178" # Orange
            bg_color = "rgba(40, 40, 40, 0.4)"
            border_color = "#CE9178"

        self.role_label = QLabel(f"{icon_text}  {role_text}")
        font = self.role_label.font()
        font.setBold(True)
        font.setPointSize(10)
        self.role_label.setFont(font)
        self.role_label.setStyleSheet(f"color: {color}; background: transparent; border: none;")
            
        header_layout.addWidget(self.role_label)
        header_layout.addStretch()
        self.layout.addLayout(header_layout)
        
        # Content
        self.content_label = QLabel()
        self.content_label.setWordWrap(True)
        self.content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.content_label.setOpenExternalLinks(True)
        
        # Format text with syntax highlighting
        formatted_html = self.format_message(text)
        self.content_label.setText(formatted_html)
        
        # Note: We don't set a unified style sheet for color here because we use HTML for content
        # But we still want the padding and text color backup
        self.content_label.setStyleSheet("padding-top: 5px; color: #E0E0E0;")
        
        # Set background of this widget using a refined style
        self.setStyleSheet(f"""
            MessageItem {{
                background-color: {bg_color}; 
                border-left: 4px solid {border_color};
                border-radius: 8px;
                margin-bottom: 5px;
            }}
            QLabel {{
                background-color: transparent;
                color: #E0E0E0;
            }}
        """)

    def format_message(self, text):
        """Converts markdown code blocks to highlighted HTML."""
        import html
        from pygments import highlight
        from pygments.lexers import get_lexer_by_name, guess_lexer
        from pygments.formatters import HtmlFormatter
        import re

        # Escape HTML characters in the text first? 
        # No, because we want to inject our own HTML.
        # But regular text needs to be escaped.
        # This is a bit complex. Let's do a simple split by code blocks.
        
        parts = re.split(r'(```\w*\n.*?```)', text, flags=re.DOTALL)
        final_html = ""
        
        formatter = HtmlFormatter(style='monokai', noclasses=True, cssstyles='padding: 10px; border-radius: 5px; background-color: #2D2D2D; color: #F8F8F2; display: block; white-space: pre-wrap;')

        for part in parts:
            if part.startswith("```") and part.endswith("```"):
                # extracting language and code
                content = part[3:-3] # remove backticks
                if '\n' in content:
                    lang_tag, code = content.split('\n', 1)
                    lang = lang_tag.strip()
                else:
                    lang = ""
                    code = content
                
                try:
                    if lang:
                        lexer = get_lexer_by_name(lang)
                    else:
                        lexer = guess_lexer(code)
                except:
                    from pygments.lexers.special import TextLexer
                    lexer = TextLexer()
                    
                highlighted = highlight(code, lexer, formatter)
                final_html += highlighted
            else:
                # Regular text
                # We should replace newlines with <br> and maybe basic markdown?
                # For now, just safe escape and newlines.
                safe_text = html.escape(part)
                # safe_text = safe_text.replace('\n', '<br>') # Allow normal wrapping
                # Actually, plain line breaks are better handled by <p> or style="white-space: pre-wrap;"
                # But QLabel rich text engine is limited.
                # Let's use simple <span style="color: #E0E0E0;">
                final_html += f'<span style="color: #E0E0E0; font-family: Segoe UI, sans-serif; font-size: 13px;">{safe_text.replace(chr(10), "<br>")}</span>'
                
        return final_html
