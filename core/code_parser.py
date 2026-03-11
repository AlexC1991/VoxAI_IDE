
import html
import logging
import re

log = logging.getLogger(__name__)

class CodeParser:
    KNOWN_TOOLS = {
        'read_file', 'read_json', 'read_python_symbols', 'write_file', 'edit_file', 'list_files', 'find_files', 'find_tests', 'move_file',
        'copy_file', 'search_files', 'find_symbol', 'find_references', 'get_imports', 'find_importers', 'get_file_structure', 'delete_file',
        'execute_command', 'search_memory', 'search_codebase', 'index_codebase',
        'git_status', 'git_diff', 'git_log', 'git_commit',
        'git_push', 'git_pull', 'git_fetch',
        'web_search', 'fetch_url',
    }

    @staticmethod
    def _strip_non_executable_regions(text: str) -> str:
        cleaned = re.sub(r'```[\s\S]*?```', '', text, flags=re.DOTALL)
        cleaned = re.sub(r'<thought>[\s\S]*?</thought>', '', cleaned, flags=re.DOTALL)
        return cleaned

    @staticmethod
    def _normalize_tool_syntax(text: str) -> str:
        if not text:
            return text
        known_tools = "|".join(sorted(CodeParser.KNOWN_TOOLS, key=len, reverse=True))
        normalized = text
        normalized = re.sub(r'(?mi)^[ \t]*</?tool_call>[ \t]*$', '', normalized)
        normalized = re.sub(
            rf'(?mi)^([ \t]*)<tool_call>\s*(?=<(?:{known_tools})\b)',
            r'\1',
            normalized,
        )
        normalized = re.sub(
            rf'(?mi)^([ \t]*)<tool_call>\s*(?=(?:{known_tools})\b)',
            r'\1<',
            normalized,
        )
        normalized = re.sub(r'(?mi)\s*</tool_call>[ \t]*$', '', normalized)
        normalized = re.sub(
            rf'(?mi)^([ \t]*)\[({known_tools})(\b[^\]]*)\][ \t]*$',
            r'\1<\2\3 />',
            normalized,
        )
        return normalized

    @staticmethod
    def extract_code(text):
        """
        Extracts the first code block found in the text.
        Returns (language, code) or (None, None) if no block found.
        """
        pattern = r"```(\w*)\n([\s\S]*?)```"
        match = re.search(pattern, text)
        
        if match:
            language = match.group(1).strip()
            code = match.group(2)
            return language, code
        
        return None, None

    @staticmethod
    def parse_tool_calls(text):
        """
        Parses text for XML-like tool calls.
        Supports:
          1. <tool_name arg1="val" arg2="val" /> (Self-closing)
          2. <tool_name arg1="val">content</tool_name> (Block)
        
        Returns a list of dicts: {'cmd': 'tool_name', 'args': {...}}
        """
        calls = []

        if not text:
            return calls

        cleaned = CodeParser._strip_non_executable_regions(text)
        cleaned = CodeParser._normalize_tool_syntax(cleaned)

        # Regex for attributes: key="value" or key='value'
        attr_pattern = re.compile(r"(\w+)=(?:\"([^\"]*)\"|'([^']*)')")

        # Tools must start at the beginning of a line (ignoring indentation).
        # This prevents inline examples like `use <read_file ... />` from firing.
        block_pattern = re.compile(r'(?ms)^[ \t]*<(\w+)([^>]*)>(.*?)</\1>[ \t]*$')
        self_closing_pattern = re.compile(r'(?m)^[ \t]*<(\w+)([^>]*?)\s*/>[ \t]*$')

        matches = []
        for match in block_pattern.finditer(cleaned):
            matches.append((match.start(), match.end(), 'block', match))

        masked = cleaned
        for start, end, _, _ in sorted(matches, reverse=True):
            masked = masked[:start] + (' ' * (end - start)) + masked[end:]

        for match in self_closing_pattern.finditer(masked):
            matches.append((match.start(), match.end(), 'self', match))

        for _, _, kind, match in sorted(matches, key=lambda item: item[0]):
            tool_name = match.group(1)
            if tool_name not in CodeParser.KNOWN_TOOLS:
                continue

            attr_str = match.group(2)
            args = {}
            for attr_match in attr_pattern.finditer(attr_str):
                key = attr_match.group(1)
                value = attr_match.group(2)
                if value is None:
                    value = attr_match.group(3) or ""
                args[key] = html.unescape(value)

            if kind == 'block':
                content = html.unescape(match.group(3).strip())
                if content:
                    args['content'] = content

            calls.append({'cmd': tool_name, 'args': args})

        return calls
