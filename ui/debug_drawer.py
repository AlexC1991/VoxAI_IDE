from PySide6.QtWidgets import (QWidget, QVBoxLayout, QTextEdit, QLabel, 
                             QPushButton, QHBoxLayout)
from PySide6.QtCore import Qt, QSize, Signal

class DebugDrawer(QWidget):
    send_to_agent = Signal(str) # Emits full text content

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Header / Drag Handle area
        self.header = QWidget()
        self.header.setStyleSheet("background-color: #333; color: white;")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(10, 5, 10, 5)
        
        title = QLabel("Terminal / Output")
        title.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Send to Agent Button
        self.send_agent_btn = QPushButton("Send to Agent")
        self.send_agent_btn.setStyleSheet("""
            QPushButton {
                background-color: #007ACC;
                color: white;
                border: none;
                padding: 3px 8px;
                border-radius: 3px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #0098FF; }
        """)
        self.send_agent_btn.clicked.connect(self.on_send_to_agent)
        header_layout.addWidget(self.send_agent_btn)
        
        self.close_btn = QPushButton("x")
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.clicked.connect(self.hide)
        self.close_btn.setStyleSheet("background-color: transparent; color: white; border: none; font-weight: bold;")
        header_layout.addWidget(self.close_btn)
        
        self.layout.addWidget(self.header)
        
        # Terminal Output Area
        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setStyleSheet("""
            background-color: #1e1e1e; 
            color: #d4d4d4; 
            font-family: Consolas, 'Courier New', monospace;
            border: none;
        """)
        self.layout.addWidget(self.output_area)
        
        # Initial State
        self.hide()
        # self.setMinimumWidth(300) # Handled by MainWindow resize

    def append_output(self, text, is_error=False):
        color = "#f44336" if is_error else "#d4d4d4"
        self.output_area.append(f'<span style="color:{color};">{text}</span>')
        self.output_area.verticalScrollBar().setValue(
            self.output_area.verticalScrollBar().maximum()
        )

    def clear_output(self):
        self.output_area.clear()

    def on_send_to_agent(self):
        # Get all text
        text = self.output_area.toPlainText()
        if text.strip():
            self.send_to_agent.emit(text)
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Header / Drag Handle area
        self.header = QWidget()
        self.header.setStyleSheet("background-color: #333; color: white;")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(10, 5, 10, 5)
        
        title = QLabel("Terminal / Output")
        title.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # Send to Agent Button
        self.send_agent_btn = QPushButton("Send to Agent")
        self.send_agent_btn.setStyleSheet("""
            QPushButton {
                background-color: #007ACC;
                color: white;
                border: none;
                padding: 3px 8px;
                border-radius: 3px;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #0098FF; }
        """)
        self.send_agent_btn.clicked.connect(self.on_send_to_agent)
        header_layout.addWidget(self.send_agent_btn)
        
        self.close_btn = QPushButton("x")
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.clicked.connect(self.hide)
        self.close_btn.setStyleSheet("background-color: transparent; color: white; border: none; font-weight: bold;")
        header_layout.addWidget(self.close_btn)
        
        self.layout.addWidget(self.header)
        
        # Terminal Output Area
        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setStyleSheet("""
            background-color: #1e1e1e; 
            color: #d4d4d4; 
            font-family: Consolas, 'Courier New', monospace;
            border: none;
        """)
        self.layout.addWidget(self.output_area)
        
        # Initial State
        self.hide()
        # self.setMinimumWidth(300) # Handled by MainWindow resize

    def append_output(self, text, is_error=False):
        color = "#f44336" if is_error else "#d4d4d4"
        self.output_area.append(f'<span style="color:{color};">{text}</span>')
        self.output_area.verticalScrollBar().setValue(
            self.output_area.verticalScrollBar().maximum()
        )

    def clear_output(self):
        self.output_area.clear()

    def on_send_to_agent(self):
        # Get all text
        text = self.output_area.toPlainText()
        if text.strip():
            self.send_to_agent.emit(text)
