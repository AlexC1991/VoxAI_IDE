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
            '<read_file path="a.py" />\n'
            '<write_file path="a.py">alpha</write_file>\n'
            '<edit_file path="a.py" old_text="alpha" new_text="beta" />\n'
            '<list_files path="." />\n'
            '<move_file src="a.py" dst="b.py" />\n'
            '<copy_file src="b.py" dst="c.py" />\n'
            '<search_files query="beta" root_dir="." file_pattern="*.py" />\n'
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
                'read_file', 'write_file', 'edit_file', 'list_files', 'move_file', 'copy_file',
                'search_files', 'get_file_structure', 'delete_file', 'execute_command',
                'search_memory', 'search_codebase', 'index_codebase', 'git_status', 'git_diff',
                'git_log', 'git_commit', 'git_push', 'git_pull', 'git_fetch', 'web_search', 'fetch_url'
            ]
        )

    def test_unescapes_xml_entities_in_attributes_and_block_content(self):
        text = (
            '<edit_file path="requirements.txt" old_text="numpy&lt;2" new_text="numpy&lt;2.0 &amp; pinned" />\n'
            '<write_file path="snippet.py">if value &lt; limit:\n    print(&quot;ok&quot;)</write_file>'
        )

        calls = CodeParser.parse_tool_calls(text)

        self.assertEqual(calls[0]["args"]["old_text"], "numpy<2")
        self.assertEqual(calls[0]["args"]["new_text"], "numpy<2.0 & pinned")
        self.assertEqual(calls[1]["args"]["content"], 'if value < limit:\n    print("ok")')


if __name__ == '__main__':
    unittest.main()