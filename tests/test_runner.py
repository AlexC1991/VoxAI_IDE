import sys
import os
from PySide6.QtCore import QCoreApplication, QTimer
# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.runner import Runner

def test_runner():
    app = QCoreApplication(sys.argv)
    
    runner = Runner()
    
    # Create a dummy script
    with open("dummy_script.py", "w") as f:
        f.write("import time\n")
        f.write("print('Hello from dummy script')\n")
        f.write("import sys; print('Error output', file=sys.stderr)\n")
    
    def on_output(text, is_error):
        prefix = "[STDERR]" if is_error else "[STDOUT]"
        print(f"{prefix} {text}")

    def on_finished(code):
        print(f"Finished with code: {code}")
        app.quit()

    runner.output_received.connect(on_output)
    runner.execution_finished.connect(on_finished)
    
    print("Starting runner...")
    runner.run_script(os.path.abspath("dummy_script.py"))
    
    # Timeout
    QTimer.singleShot(5000, app.quit)
    
    sys.exit(app.exec())

if __name__ == "__main__":
    test_runner()
