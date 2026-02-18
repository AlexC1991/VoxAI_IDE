
import re
import logging

log = logging.getLogger(__name__)

class CodeParser:
    KNOWN_TOOLS = {
        'read_file', 'write_file', 'edit_file', 'list_files', 'move_file',
        'copy_file', 'search_files', 'get_file_structure', 'delete_file',
        'execute_command', 'search_memory', 'search_codebase', 'index_codebase',
        'git_status', 'git_diff', 'git_log', 'git_commit',
        'git_push', 'git_pull', 'git_fetch',
        'web_search', 'fetch_url',
    }

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
        
        # Regex for attributes: key="value"
        attr_pattern = re.compile(r'(\w+)="([^"]*)"')

        # 1. Find Block Tags: <tool ...>content</tool>
        block_pattern = re.compile(r'<(\w+)([^>]*)>(.*?)</\1>', re.DOTALL)
        
        # We iterate over matches
        for match in block_pattern.finditer(text):
            tool_name = match.group(1)
            attr_str = match.group(2)
            content = match.group(3).strip() 
            
            # Parse attributes
            args = dict(attr_pattern.findall(attr_str))
            
            if content:
                args['content'] = content
            
            calls.append({'cmd': tool_name, 'args': args})

        # 2. Find Self-Closing Tags: <tool ... />
        text_without_blocks = block_pattern.sub('', text)
        
        self_closing_pattern = re.compile(r'<(\w+)([^>]*?)\s*/>')
        
        for match in self_closing_pattern.finditer(text_without_blocks):
            tool_name = match.group(1)
            attr_str = match.group(2)
            
            args = dict(attr_pattern.findall(attr_str))
            calls.append({'cmd': tool_name, 'args': args})

        # Filter to only recognised tool commands
        calls = [c for c in calls if c['cmd'] in CodeParser.KNOWN_TOOLS]

        return calls
