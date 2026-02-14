import sys
import traceback
from ui.main_window import CodingAgentIDE
from PySide6.QtWidgets import QApplication, QMessageBox

from ui.crash_reporter import show_crash_dialog


def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    print("Uncaught exception:", file=sys.stderr)
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
    
    # Show GUI dialog
    try:
        show_crash_dialog(exc_type, exc_value, exc_traceback)
    except Exception as e:
        print(f"Failed to show crash dialog: {e}", file=sys.stderr)

sys.excepthook = handle_exception

def main():
    print("Initializing Application...")
    app = QApplication(sys.argv)
    
    # Optional: Set global stylesheet or theme here
    print("Creating Main Window...")
    window = CodingAgentIDE()
    window.show()
    print("Starting Main Loop...")
    sys.exit(app.exec())

if __name__ == "__main__":
    main()