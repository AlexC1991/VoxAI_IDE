
import sys
import traceback
from ui.main_window import CodingAgentIDE
from PySide6.QtWidgets import QApplication, QMessageBox

from ui.crash_reporter import show_crash_dialog

# Ensure stdout/stderr handle UTF-8 (important for emojis on Windows)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')


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

import logging

# Configure Logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("debug.log", mode='w', encoding='utf-8')
    ]
)

log = logging.getLogger(__name__)

def main():
    log.info("Initializing Application...")
    app = QApplication(sys.argv)
    
    # Optional: Set global stylesheet or theme here
    log.info("Creating Main Window...")
    window = CodingAgentIDE()
    window.show()
    log.info("Starting Main Loop...")
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
