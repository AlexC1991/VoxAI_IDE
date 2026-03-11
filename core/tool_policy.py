class ToolPolicy:
    CORE_TOOLS = {
        'read_file', 'read_json', 'read_python_symbols', 'write_file', 'edit_file', 'list_files', 'find_files',
        'find_tests', 'search_files', 'find_symbol', 'find_references', 'get_imports', 'find_importers',
        'get_file_structure', 'execute_command',
    }
    ADVANCED_TOOLS = {
        'move_file', 'copy_file', 'delete_file',
        'search_memory', 'search_codebase', 'index_codebase',
        'git_status', 'git_diff', 'git_log', 'git_commit', 'git_push', 'git_pull', 'git_fetch',
        'web_search', 'fetch_url',
    }
    WEB_TOOLS = {'web_search', 'fetch_url'}
    RAG_TOOLS = {'search_memory', 'search_codebase', 'index_codebase'}

    @staticmethod
    def advanced_tools_enabled(settings_manager) -> bool:
        getter = getattr(settings_manager, 'get_advanced_agent_tools_enabled', None)
        if not callable(getter):
            return False
        try:
            return bool(getter())
        except Exception:
            return False

    @staticmethod
    def web_tools_enabled(settings_manager) -> bool:
        getter = getattr(settings_manager, 'get_web_search_enabled', None)
        if not callable(getter):
            return False
        try:
            return bool(getter())
        except Exception:
            return False

    @classmethod
    def is_tool_enabled(cls, tool_name: str, settings_manager) -> tuple[bool, str]:
        tool_name = str(tool_name or '').strip()
        if tool_name in cls.WEB_TOOLS:
            if not cls.advanced_tools_enabled(settings_manager):
                return False, 'Web tools are disabled until Advanced Agent Tools is enabled in settings.'
            if not cls.web_tools_enabled(settings_manager):
                return False, 'Web tools are disabled in settings for this run.'
        elif tool_name in cls.ADVANCED_TOOLS and not cls.advanced_tools_enabled(settings_manager):
            return False, 'Advanced agent tools are disabled for this run. Stick to the stable local code/edit/test toolset.'
        return True, ''

    @classmethod
    def summarize_disabled_tools(cls, tool_names, settings_manager) -> str | None:
        blocked = []
        for name in tool_names:
            allowed, _ = cls.is_tool_enabled(name, settings_manager)
            if not allowed:
                blocked.append(name)
        if not blocked:
            return None
        unique = ', '.join(sorted(set(blocked)))
        if cls.advanced_tools_enabled(settings_manager):
            return f"The previous tool batch relied on disabled tools ({unique}). Rewrite it using only enabled tools."
        return (
            f"The previous tool batch relied on advanced/unsafe tools ({unique}) that are disabled by default. "
            "Rewrite it using the stable core tools only."
        )

    @classmethod
    def build_tool_coach_prompt(cls, settings_manager) -> str:
        advanced = cls.advanced_tools_enabled(settings_manager)
        lines = [
            'TOOL COACH / REALITY CHECK:',
            '- Prefer the stable core tools first: <find_tests />, <get_imports />, <find_importers />, <find_symbol />, <find_references />, <read_python_symbols />, <find_files />, <list_files />, <search_files />, <read_file />, <read_json />, <edit_file />, <write_file />, and <execute_command />.',
            '- Change code with tools. Use <edit_file path="file.py" old_text="draft" new_text="final" /> for exact replacements, <edit_file path="file.py" start_line="10" end_line="14">new block</edit_file> for line-range edits, or <edit_file path="file.py" insert_after="class Demo:\n">    def run(self):\n        return 1\n</edit_file> for anchored inserts. Use <write_file path="file.py">full content</write_file> only for large rewrites.',
            '- Verify with tools, e.g. <execute_command command="pytest -q" cwd="." />.',
            '- If the latest ACTION_SUMMARY says no successful file changes occurred, explicitly say no files were changed.',
            '- Do not claim a fix, file change, or successful validation unless the latest TOOL_RESULT proves it.',
            '- If you claim the latest edit was verified, a successful execute_command must happen AFTER that edit.',
            '- If you claim a fresh rescan after editing, a fresh read/search/list/structure/codebase-scan step must happen AFTER that edit.',
            '- If an edit failed, read/search the file again before retrying.',
            '- After an edit_file failure, prefer one narrow <read_file ... /> on the SAME target, then retry with the easiest edit_file shape: exact old_text/new_text, start_line/end_line, or insert_before/insert_after.',
        ]
        if advanced:
            lines.append('- Advanced tools are enabled, but use git/web/RAG indexing tools only when the stable local tools cannot answer the task.')
            if not cls.web_tools_enabled(settings_manager):
                lines.append('- Even with advanced tools enabled, <web_search> and <fetch_url> are still disabled unless web search is enabled in settings.')
        else:
            lines.append('- Advanced tools are OFF for this run. Do NOT use git tools, web tools, RAG search/indexing, or file move/copy/delete tools.')
        return '\n'.join(lines)

    @classmethod
    def build_tool_surface_notice(cls, settings_manager) -> str:
        if cls.advanced_tools_enabled(settings_manager):
            suffix = ' Web tools remain disabled.' if not cls.web_tools_enabled(settings_manager) else ''
            return 'TOOL SURFACE: Stable core tools plus advanced tools are enabled. Prefer the stable core first.' + suffix
        return (
            'TOOL SURFACE: Stable core only. Disabled by default: git_*, web_search/fetch_url, '
            'search_memory/search_codebase/index_codebase, and move/copy/delete file tools.'
        )