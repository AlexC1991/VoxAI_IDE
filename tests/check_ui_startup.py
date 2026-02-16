import sys
import os

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

print(f"Checking imports from project root: {PROJECT_ROOT}")

try:
    print("Importing ui.chat_panel...")
    from ui.chat_panel import ChatPanel
    print("SUCCESS: ChatPanel imported.")
except Exception as e:
    print(f"FAILURE: ChatPanel import failed: {e}")
    sys.exit(1)

try:
    print("Importing ui.main_window...")
    from ui.main_window import CodingAgentIDE
    print("SUCCESS: MainWindow imported.")
except Exception as e:
    print(f"FAILURE: MainWindow import failed: {e}")
    sys.exit(1)

print("--- UI Startup Check Passed ---")
