
import sys
import os
from PySide6.QtCore import QSettings

# Setup path
sys.path.append(os.getcwd())

from core.settings import SettingsManager

def test_settings_persistence():
    print("Testing Settings Persistence...")
    mgr = SettingsManager()
    
    # Set values
    print("Setting custom colors...")
    mgr.set_chat_user_color("#123456")
    mgr.set_chat_ai_color("#654321")
    
    # Verify values
    u = mgr.get_chat_user_color()
    a = mgr.get_chat_ai_color()
    
    print(f"User Color: {u}")
    print(f"AI Color:   {a}")
    
    if u == "#123456" and a == "#654321":
        print("SUCCESS: Settings saved and retrieved correctly.")
    else:
        print("FAILURE: Settings mismatch.")
        sys.exit(1)

if __name__ == "__main__":
    test_settings_persistence()
