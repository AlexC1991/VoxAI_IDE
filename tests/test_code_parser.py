import unittest

from core.code_parser import CodeParser


class TestCodeParser(unittest.TestCase):
    def test_ignores_inline_and_fenced_tool_examples(self):
        text = (
            "Explain the tool like this: <read_file path=\"demo.py\" />\n\n"
            "```xml\n<delete_file path=\"danger.txt\" />\n```\n\n"
            "<list_files path=\".\" />"
        )

        calls = CodeParser.parse_tool_calls(text)

        self.assertEqual(calls, [{"cmd": "list_files", "args": {"path": "."}}])

    def test_preserves_order_for_block_and_self_closing_tags(self):
        text = (
            "<search_files query=\"TODO\" />\n"
            "<write_file path=\"notes.txt\">alpha\nbeta</write_file>\n"
            "<git_status />"
        )

        calls = CodeParser.parse_tool_calls(text)

        self.assertEqual([call["cmd"] for call in calls], ["search_files", "write_file", "git_status"])
        self.assertEqual(calls[1]["args"]["content"], "alpha\nbeta")

    def test_parses_all_known_tool_tags(self):
        text = (
            '<read_file path="a.py" with_line_numbers="true" />\n'
            '<read_json path="package.json" query="scripts.test" />\n'
            '<read_python_symbols path="a.py" symbols="Demo.run" />\n'
            '<write_file path="a.py">alpha</write_file>\n'
            '<edit_file path="a.py" old_text="alpha" new_text="beta" />\n'
            '<list_files path="." />\n'
            '<find_files pattern="*config*.json" root_dir="." max_results="5" />\n'
            '<find_tests source_path="src/app.py" root_dir="tests" max_results="3" />\n'
            '<move_file src="a.py" dst="b.py" />\n'
            '<copy_file src="b.py" dst="c.py" />\n'
            '<search_files query="beta" root_dir="." file_pattern="*.py" context_lines="2" max_results="7" />\n'
            '<find_symbol symbol="Demo.run" root_dir="." symbol_type="method" />\n'
            '<find_references symbol="Demo" root_dir="." context_lines="1" />\n'
            '<get_imports path="a.py" include_external="false" />\n'
            '<find_importers target="core.agent_tools" root_dir="." />\n'
            '<get_file_structure path="c.py" />\n'
            '<delete_file path="c.py" />\n'
            '<execute_command command="python a.py" cwd="." />\n'
            '<search_memory query="memory" />\n'
            '<search_codebase query="Example class" />\n'
            '<index_codebase path="." />\n'
            '<git_status />\n'
            '<git_diff path="a.py" />\n'
            '<git_log count="5" />\n'
            '<git_commit message="feat: test" />\n'
            '<git_push remote="origin" branch="main" />\n'
            '<git_pull remote="origin" branch="main" />\n'
            '<git_fetch remote="origin" />\n'
            '<web_search query="python unittest" />\n'
            '<fetch_url url="https://example.com" />'
        )

        calls = CodeParser.parse_tool_calls(text)

        self.assertEqual(
            [call["cmd"] for call in calls],
            [
                'read_file', 'read_json', 'read_python_symbols', 'write_file', 'edit_file', 'list_files', 'find_files', 'find_tests', 'move_file', 'copy_file',
                'search_files', 'find_symbol', 'find_references', 'get_imports', 'find_importers', 'get_file_structure', 'delete_file', 'execute_command',
                'search_memory', 'search_codebase', 'index_codebase', 'git_status', 'git_diff',
                'git_log', 'git_commit', 'git_push', 'git_pull', 'git_fetch', 'web_search', 'fetch_url'
            ]
        )
        self.assertEqual(calls[0]["args"]["with_line_numbers"], "true")
        self.assertEqual(calls[1]["args"]["query"], "scripts.test")
        self.assertEqual(calls[2]["args"]["symbols"], "Demo.run")
        self.assertEqual(calls[6]["args"]["pattern"], "*config*.json")
        self.assertEqual(calls[7]["args"]["source_path"], "src/app.py")
        self.assertEqual(calls[10]["args"]["context_lines"], "2")
        self.assertEqual(calls[11]["args"]["symbol_type"], "method")
        self.assertEqual(calls[13]["args"]["include_external"], "false")

    def test_unescapes_xml_entities_in_attributes_and_block_content(self):
        text = (
            '<edit_file path="requirements.txt" old_text="numpy&lt;2" new_text="numpy&lt;2.0 &amp; pinned" />\n'
            '<write_file path="snippet.py">if value &lt; limit:\n    print(&quot;ok&quot;)</write_file>'
        )

        calls = CodeParser.parse_tool_calls(text)

        self.assertEqual(calls[0]["args"]["old_text"], "numpy<2")
        self.assertEqual(calls[0]["args"]["new_text"], "numpy<2.0 & pinned")
        self.assertEqual(calls[1]["args"]["content"], 'if value < limit:\n    print("ok")')

    def test_parses_single_quoted_attributes(self):
        text = (
            "<read_file path='engine/model_manager.py' />\n"
            "<edit_file path='requirements.txt' old_text='numpy<2' new_text='numpy<2.0' />\n"
            '<execute_command command="python -m py_compile engine/model_manager.py" cwd="." />'
        )

        calls = CodeParser.parse_tool_calls(text)

        self.assertEqual(
            calls,
            [
                {"cmd": "read_file", "args": {"path": "engine/model_manager.py"}},
                {
                    "cmd": "edit_file",
                    "args": {
                        "path": "requirements.txt",
                        "old_text": "numpy<2",
                        "new_text": "numpy<2.0",
                    },
                },
                {
                    "cmd": "execute_command",
                    "args": {"command": "python -m py_compile engine/model_manager.py", "cwd": "."},
                },
            ],
        )

    def test_parses_tool_call_wrapper_without_inner_angle_bracket(self):
        text = (
            "I will inspect the likely targets now.\n"
            '<tool_call>read_file path="engine/model_manager.py" />\n'
            '<tool_call>execute_command command="python -m py_compile engine/model_manager.py" cwd="." />'
        )

        calls = CodeParser.parse_tool_calls(text)

        self.assertEqual(
            calls,
            [
                {"cmd": "read_file", "args": {"path": "engine/model_manager.py"}},
                {
                    "cmd": "execute_command",
                    "args": {"command": "python -m py_compile engine/model_manager.py", "cwd": "."},
                },
            ],
        )

    def test_parses_tool_call_wrapper_around_standard_tag(self):
        text = '<tool_call><read_file path="engine/model_manager.py" /></tool_call>'

        calls = CodeParser.parse_tool_calls(text)

        self.assertEqual(calls, [{"cmd": "read_file", "args": {"path": "engine/model_manager.py"}}])

    def test_parses_square_bracket_tool_lines(self):
        text = (
            "[read_file path='requirements.txt']\n"
            '[execute_command command="python -m py_compile app/main_gui.py" cwd="."]\n'
            "[TOOL_RESULT]"
        )

        calls = CodeParser.parse_tool_calls(text)

        self.assertEqual(
            calls,
            [
                {"cmd": "read_file", "args": {"path": "requirements.txt"}},
                {
                    "cmd": "execute_command",
                    "args": {"command": "python -m py_compile app/main_gui.py", "cwd": "."},
                },
            ],
        )

    def test_ignores_inline_tool_call_wrapper_example(self):
        text = (
            'Example only: <tool_call>read_file path="demo.py" />\n'
            '<list_files path="." />'
        )

        calls = CodeParser.parse_tool_calls(text)

        self.assertEqual(calls, [{"cmd": "list_files", "args": {"path": "."}}])


if __name__ == '__main__':
    unittest.main()