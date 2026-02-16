import os
import sys

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from core.agent_tools import get_resource_path

def test_resources():
    resources = [
        "resources/Chat_Background_Image.png",
        "resources/Emblem.png",
        "resources/close_tab.png"
    ]
    
    all_ok = True
    for res in resources:
        path = get_resource_path(res)
        exists = os.path.exists(path)
        print(f"Resource: {res}")
        print(f"  Path: {path}")
        print(f"  Exists: {exists}")
        if not exists:
            all_ok = False
            
    if all_ok:
        print("\n[SUCCESS] All critical resources found via get_resource_path.")
    else:
        print("\n[FAILURE] Some resources were not found.")
        sys.exit(1)

if __name__ == "__main__":
    test_resources()
