import sys
import traceback
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QTextEdit, QPushButton, QApplication
from PySide6.QtCore import Qt

class CrashReporter(QDialog):
    def __init__(self, exc_type, exc_value, exc_traceback):
        super().__init__()
        self.setWindowTitle("VoxAI IDE - Crash Report")
        self.resize(600, 400)
        
        layout = QVBoxLayout(self)
        
        # Header
        header = QLabel("⚠️ The application encountered an unexpected error and needs to close.")
        header.setStyleSheet("font-weight: bold; color: #f44336; font-size: 14px; background-color: transparent;")
        header.setWordWrap(True)
        layout.addWidget(header)
        
        # Error Details
        layout.addWidget(QLabel("Error Details:"))
        
        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setStyleSheet("font-family: Consolas; font-size: 12px; background-color: #f0f0f0; color: black;")
        
        # Format traceback
        error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        self.text_area.setText(error_msg)
        layout.addWidget(self.text_area)
        
        # Buttons
        close_btn = QPushButton("Close Application")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
        # Log to file automatically
        try:
            with open("crash.log", "w") as f:
                f.write(error_msg)
        except Exception:
            pass

def show_crash_dialog(exc_type, exc_value, exc_traceback):
    # Ensure we have an application instance
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    dialog = CrashReporter(exc_type, exc_value, exc_traceback)
    dialog.exec()
