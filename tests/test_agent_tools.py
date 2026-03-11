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

    def test_read_file_can_include_line_numbers(self):
        full_path = os.path.join(self._tmp.name, "app.py")
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write("alpha\nbeta\ngamma\n")

        read_result = AgentToolHandler.read_file("app.py", 1, 3, with_line_numbers=True)

        self.assertIn("1: alpha", read_result)
        self.assertIn("2: beta", read_result)
        self.assertIn("3: gamma", read_result)

    def test_edit_file_uses_indentation_aware_fallback_for_unique_block(self):
        full_path = os.path.join(self._tmp.name, "pkg", "worker.py")
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(
                "def run():\n"
                "    if enabled:\n"
                "        return 'old'\n"
            )

        edit_result = AgentToolHandler.edit_file(
            "pkg/worker.py",
            "if enabled:\n    return 'old'\n",
            "if enabled:\n    return 'new'\n",
        )

        self.assertIn("using indentation-aware", edit_result)
        self.assertIn("return 'new'", AgentToolHandler.read_file("pkg/worker.py", 1, 20))

    def test_edit_file_indentation_aware_fallback_refuses_ambiguous_match(self):
        full_path = os.path.join(self._tmp.name, "pkg", "worker.py")
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(
                "def one():\n"
                "    if enabled:\n"
                "        return 'old'\n\n"
                "def two():\n"
                "        if enabled:\n"
                "            return 'old'\n"
            )

        edit_result = AgentToolHandler.edit_file(
            "pkg/worker.py",
            "if enabled:\n    return 'old'\n",
            "if enabled:\n    return 'new'\n",
        )

        self.assertIn("matched 2 locations", edit_result)

    def test_edit_file_supports_line_range_anchor_insert_and_occurrence_modes(self):
        full_path = os.path.join(self._tmp.name, "pkg", "worker.py")
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(
                "class Worker:\n"
                "    def setup(self):\n"
                "        return 'draft'\n"
                "\n"
                "    def finish(self):\n"
                "        return 'draft'\n"
            )

        line_result = AgentToolHandler.edit_file(
            "pkg/worker.py",
            start_line=2,
            end_line=3,
            new_text="    def setup(self):\n        return 'ready'\n",
        )
        occurrence_result = AgentToolHandler.edit_file(
            "pkg/worker.py",
            old_text="draft",
            new_text="done",
            occurrence=1,
        )
        insert_result = AgentToolHandler.edit_file(
            "pkg/worker.py",
            new_text="\n    def run(self):\n        return 'ok'\n",
            insert_after="    def finish(self):\n        return 'done'\n",
        )

        contents = AgentToolHandler.read_file("pkg/worker.py", 1, 20)
        self.assertIn("using line-range", line_result)
        self.assertIn("using exact", occurrence_result)
        self.assertIn("using insert_after", insert_result)
        self.assertIn("return 'ready'", contents)
        self.assertIn("return 'done'", contents)
        self.assertIn("def run(self):", contents)

    def test_edit_file_rejects_invalid_python_syntax_before_writing(self):
        full_path = os.path.join(self._tmp.name, "bad.py")
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write("def run():\n    return 1\n")

        result = AgentToolHandler.edit_file(
            "bad.py",
            start_line=1,
            end_line=2,
            new_text="def run(:\n    return 1\n",
        )

        self.assertIn("invalid syntax", result)
        self.assertIn("def run():", AgentToolHandler.read_file("bad.py", 1, 10))

    def test_execute_command_defaults_to_project_root_for_relative_project(self):
        full_path = os.path.join(self._tmp.name, "app.py")
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write("print('tool cwd ok')\n")

        result = AgentToolHandler.execute_command("python app.py")

        self.assertIn("STDOUT:\ntool cwd ok", result)
        self.assertNotIn("[Permission Denied", result)

    def test_execute_command_honors_relative_cwd_inside_project(self):
        src_dir = os.path.join(self._tmp.name, "src")
        os.makedirs(src_dir, exist_ok=True)
        with open(os.path.join(src_dir, "app.py"), 'w', encoding='utf-8') as f:
            f.write("from pathlib import Path\n")
            f.write("print(Path('data.txt').read_text(encoding='utf-8').strip())\n")
        with open(os.path.join(src_dir, "data.txt"), 'w', encoding='utf-8') as f:
            f.write("nested-cwd-ok\n")

        result = AgentToolHandler.execute_command("python app.py", cwd="src")

        self.assertIn("STDOUT:\nnested-cwd-ok", result)
        self.assertNotIn("[Permission Denied", result)

    def test_list_and_search_files_use_project_root_for_relative_root_dir(self):
        src_dir = os.path.join(self._tmp.name, "src")
        os.makedirs(src_dir, exist_ok=True)
        with open(os.path.join(src_dir, 'main.py'), 'w', encoding='utf-8') as f:
            f.write("def helper():\n    return 'before'\n\nprint('needle')\n")
        with open(os.path.join(src_dir, 'config.json'), 'w', encoding='utf-8') as f:
            f.write('{"scripts": {"test": "pytest -q"}, "enabled": true}\n')

        listed = AgentToolHandler.list_files("src")
        found = AgentToolHandler.find_files("*main.py", root_dir="src")
        searched = AgentToolHandler.search_files("needle", root_dir="src", file_pattern="*.py", context_lines=1)
        json_summary = AgentToolHandler.read_json("src/config.json")
        json_query = AgentToolHandler.read_json("src/config.json", query="scripts.test")

        self.assertIn("main.py", listed)
        self.assertIn("main.py", found)
        self.assertIn("main.py:4", searched)
        self.assertIn("3 |", searched)
        self.assertIn("> 4 | print('needle')", searched)
        self.assertIn("Top-level entries:", json_summary)
        self.assertIn("- scripts: object (1 keys)", json_summary)
        self.assertEqual(json_query, '"pytest -q"')

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

    def test_python_symbol_navigation_tools_find_definitions_references_and_bodies(self):
        pkg_dir = os.path.join(self._tmp.name, "pkg")
        os.makedirs(pkg_dir, exist_ok=True)
        with open(os.path.join(pkg_dir, 'sample.py'), 'w', encoding='utf-8') as f:
            f.write(
                "class Example:\n"
                "    def greet(self):\n"
                "        return helper()\n\n"
                "def helper():\n"
                "    return 'hi'\n\n"
                "result = Example().greet()\n"
            )
        with open(os.path.join(pkg_dir, 'use_sample.py'), 'w', encoding='utf-8') as f:
            f.write(
                "from sample import Example, helper\n\n"
                "def run():\n"
                "    return Example().greet(), helper()\n"
            )

        symbol_hits = AgentToolHandler.find_symbol("Example.greet", root_dir="pkg", symbol_type="method")
        symbol_body = AgentToolHandler.read_python_symbols("pkg/sample.py", "Example.greet, helper")
        references = AgentToolHandler.find_references("Example", root_dir="pkg", context_lines=0)

        self.assertIn("sample.py:2: method Example.greet", symbol_hits)
        self.assertIn("=== Method Example.greet (lines 2-3) ===", symbol_body)
        self.assertIn("2:     def greet(self):", symbol_body)
        self.assertIn("=== Function helper (lines 5-6) ===", symbol_body)
        self.assertIn("use_sample.py:1:", references)
        self.assertIn("sample.py:8:", references)

    def test_find_tests_and_import_tools_surface_relevant_matches(self):
        src_dir = os.path.join(self._tmp.name, "src")
        tests_dir = os.path.join(self._tmp.name, "tests")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(tests_dir, exist_ok=True)
        with open(os.path.join(src_dir, 'engine.py'), 'w', encoding='utf-8') as f:
            f.write(
                "from core.helpers import helper\n"
                "from .local_mod import LocalThing\n"
                "import json\n\n"
                "class Worker:\n"
                "    def run(self):\n"
                "        return helper()\n"
            )
        os.makedirs(os.path.join(self._tmp.name, 'core'), exist_ok=True)
        with open(os.path.join(self._tmp.name, 'core', 'helpers.py'), 'w', encoding='utf-8') as f:
            f.write("def helper():\n    return 'ok'\n")
        with open(os.path.join(tests_dir, 'test_engine.py'), 'w', encoding='utf-8') as f:
            f.write(
                "from src.engine import Worker\n\n"
                "class TestWorkerFlow:\n"
                "    def test_run_returns_helper_result(self):\n"
                "        assert Worker().run() == 'ok'\n"
            )
        with open(os.path.join(self._tmp.name, 'consumer.py'), 'w', encoding='utf-8') as f:
            f.write("from src.engine import Worker\n\nvalue = Worker().run()\n")

        test_matches = AgentToolHandler.find_tests(source_path="src/engine.py")
        imports = AgentToolHandler.get_imports("src/engine.py")
        importers = AgentToolHandler.find_importers("src/engine.py", root_dir=".")

        self.assertIn("tests/test_engine.py", test_matches)
        self.assertIn("TestWorkerFlow.test_run_returns_helper_result", test_matches)
        self.assertIn("1: from core.helpers import helper [internal]", imports)
        self.assertIn("2: from .local_mod import LocalThing [relative]", imports)
        self.assertIn("3: import json [external]", imports)
        self.assertIn("consumer.py:1: from src.engine import Worker [matches src.engine]", importers)


if __name__ == '__main__':
    unittest.main()

