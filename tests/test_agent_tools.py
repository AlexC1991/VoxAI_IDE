import os
import sys
import tempfile
import unittest

sys.path.append(os.getcwd())

from core.agent_tools import AgentToolHandler, get_project_root, set_project_root


class TestAgentTools(unittest.TestCase):
    def setUp(self):
        self._old_root = get_project_root()
        self._tmp = tempfile.TemporaryDirectory()
        set_project_root(self._tmp.name)

    def tearDown(self):
        set_project_root(self._old_root)
        self._tmp.cleanup()

    def test_write_file_uses_project_root_for_relative_paths(self):
        result = AgentToolHandler.write_file("app.py", "print('ok')\n")

        self.assertIn("[Success: File written", result)
        full_path = os.path.join(self._tmp.name, "app.py")
        self.assertTrue(os.path.exists(full_path))

    def test_edit_file_and_read_file_use_project_root_for_relative_paths(self):
        full_path = os.path.join(self._tmp.name, "app.py")
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write("print('broken')\n")

        edit_result = AgentToolHandler.edit_file("app.py", "print('broken')", "print('fixed')")
        read_result = AgentToolHandler.read_file("app.py", 1, 20)

        self.assertIn("[Success: Edited", edit_result)
        self.assertIn("print('fixed')", read_result)

    def test_execute_command_defaults_to_project_root_for_relative_project(self):
        full_path = os.path.join(self._tmp.name, "app.py")
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write("print('tool cwd ok')\n")

        result = AgentToolHandler.execute_command("python app.py")

        self.assertIn("STDOUT:\ntool cwd ok", result)
        self.assertNotIn("[Permission Denied", result)

    def test_list_and_search_files_use_project_root_for_relative_root_dir(self):
        src_dir = os.path.join(self._tmp.name, "src")
        os.makedirs(src_dir, exist_ok=True)
        with open(os.path.join(src_dir, 'main.py'), 'w', encoding='utf-8') as f:
            f.write("print('needle')\n")

        listed = AgentToolHandler.list_files("src")
        searched = AgentToolHandler.search_files("needle", root_dir="src", file_pattern="*.py")

        self.assertIn("main.py", listed)
        self.assertIn("main.py:1", searched)

    def test_structure_copy_move_and_delete_use_project_root(self):
        src_dir = os.path.join(self._tmp.name, "pkg")
        os.makedirs(src_dir, exist_ok=True)
        with open(os.path.join(src_dir, 'sample.py'), 'w', encoding='utf-8') as f:
            f.write("class Example:\n    def greet(self):\n        return 'hi'\n")

        structure = AgentToolHandler.get_file_structure("pkg/sample.py")
        copied = AgentToolHandler.copy_file("pkg/sample.py", "copy/sample.py")
        moved = AgentToolHandler.move_file("copy/sample.py", "archive/renamed.py")
        deleted = AgentToolHandler.delete_file("archive/renamed.py")

        self.assertIn("Class: Example", structure)
        self.assertIn("Method: greet", structure)
        self.assertIn("[Success: Copied", copied)
        self.assertIn("[Success: Moved", moved)
        self.assertIn("[Success: Deleted file", deleted)
        self.assertTrue(os.path.exists(os.path.join(self._tmp.name, "pkg", "sample.py")))
        self.assertFalse(os.path.exists(os.path.join(self._tmp.name, "archive", "renamed.py")))


if __name__ == '__main__':
    unittest.main()

