import os
import sys
import time
import unittest
from tempfile import TemporaryDirectory

from PySide6.QtCore import QCoreApplication

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.runner import Runner


class TestRunner(unittest.TestCase):
    def test_runner_executes_script_and_emits_output(self):
        app = QCoreApplication.instance() or QCoreApplication(sys.argv)
        runner = Runner()
        outputs = []
        finished = []

        with TemporaryDirectory() as tmpdir:
            script_path = os.path.join(tmpdir, "dummy_script.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write("print('Hello from dummy script')\n")
                f.write("import sys; print('Error output', file=sys.stderr)\n")

            runner.output_received.connect(lambda text, is_error: outputs.append((text, is_error)))
            runner.execution_finished.connect(lambda code: finished.append(code))
            runner.run_script(script_path)

            deadline = time.time() + 5.0
            while time.time() < deadline and not finished:
                app.processEvents()
                time.sleep(0.01)

        self.assertTrue(finished, "Runner did not finish within the timeout")
        self.assertEqual(finished[-1], 0)
        self.assertTrue(any("Hello from dummy script" in text and not is_error for text, is_error in outputs))
        self.assertTrue(any("Error output" in text and is_error for text, is_error in outputs))

    def test_runner_uses_script_directory_as_working_directory(self):
        app = QCoreApplication.instance() or QCoreApplication(sys.argv)
        runner = Runner()
        outputs = []
        finished = []

        with TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "nested_project")
            os.makedirs(project_dir, exist_ok=True)
            with open(os.path.join(project_dir, "data.txt"), "w", encoding="utf-8") as f:
                f.write("relative-path-ok\n")
            script_path = os.path.join(project_dir, "uses_relative_file.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write("from pathlib import Path\n")
                f.write("print(Path('data.txt').read_text(encoding='utf-8').strip())\n")

            runner.output_received.connect(lambda text, is_error: outputs.append((text, is_error)))
            runner.execution_finished.connect(lambda code: finished.append(code))
            runner.run_script(script_path)

            deadline = time.time() + 5.0
            while time.time() < deadline and not finished:
                app.processEvents()
                time.sleep(0.01)

        self.assertTrue(finished, "Runner did not finish within the timeout")
        self.assertEqual(finished[-1], 0)
        self.assertTrue(any("relative-path-ok" in text and not is_error for text, is_error in outputs))


if __name__ == "__main__":
    unittest.main()