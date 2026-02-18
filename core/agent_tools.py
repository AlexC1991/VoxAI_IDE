import os
import logging

log = logging.getLogger(__name__)

# Resolved at runtime when user selects a project folder
_project_root = None


def set_project_root(path):
    """Set the active project root. Called when user selects a project folder."""
    global _project_root
    _project_root = os.path.realpath(path)
    log.info("Project root set to: %s", _project_root)


def get_ide_root():
    """Returns the root directory of the IDE installation (where main.py resides)."""
    # This file is in core/agent_tools.py, so we go up one level
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_path(relative_path):
    """Returns an absolute path to a resource relative to the IDE root."""
    return os.path.join(get_ide_root(), relative_path)


def get_project_root():
    global _project_root
    if _project_root is None:
        _project_root = os.path.realpath(os.getcwd())
    return _project_root


def _is_inside_project(path):
    """Return True if *path* resolves inside the project root."""
    real = os.path.realpath(os.path.abspath(path))
    root = get_project_root()
    try:
        return os.path.commonpath([real, root]) == root
    except ValueError:
        return False


def _require_inside_project(path, action="modify"):
    """Raise if the resolved path is outside the project directory."""
    if not _is_inside_project(path):
        raise PermissionError(
            f"Cannot {action} '{path}' — it is outside the project directory ({get_project_root()}). "
            f"Only read operations are allowed outside the project."
        )


class AgentToolHandler:
    """File-system tool-belt for the AI agent.

    Permissions model:
      - READ / LIST / SEARCH / STRUCTURE are allowed anywhere (so the AI can
        reference external projects for patterns, conventions, etc.).
      - WRITE / MOVE / COPY / DELETE / EXECUTE are restricted to the project dir.
    """

    EXCLUDE_DIRS = {
        '.git', '__pycache__', '.idea', 'venv', 'env',
        '.gemini', 'node_modules', 'target', 'build', 'dist',
    }

    # ------------------------------------------------------------------
    # READ (allowed everywhere)
    # ------------------------------------------------------------------
    @staticmethod
    def read_file(path, start_line=1, end_line=300):
        """Reads content of a file. Defaults to first 300 lines."""
        if not os.path.exists(path):
            return f"[Error: File not found: {path}]"
        if "crash.log" in os.path.basename(path):
            return "[Skipping crash.log to prevent file lock issues]"
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            total_lines = len(lines)
            start_idx = max(0, start_line - 1)
            end_idx = min(total_lines, end_line)

            content = "".join(lines[start_idx:end_idx])

            if total_lines > end_line:
                content += (
                    f"\n... (Showing lines {start_line}-{end_line} of {total_lines}. "
                    f"Use read_file with start_line/end_line to see more.)"
                )
            return content
        except Exception as e:
            return f"[Error reading file: {e}]"

    @staticmethod
    def list_files(root_dir="."):
        """Lists all files in the directory recursively."""
        file_list = []
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in AgentToolHandler.EXCLUDE_DIRS]
            for file in files:
                if file == "crash.log":
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, root_dir)
                file_list.append(rel_path)
        return "\n".join(file_list)

    @staticmethod
    def search_files(query, root_dir=".", file_pattern=None, case_insensitive=False):
        """Searches for a string or regex pattern in files.
        Supports optional file_pattern glob (e.g. '*.py') and case_insensitive flag."""
        import re as _re
        import fnmatch
        matches = []
        max_results = 100
        try:
            flags = _re.IGNORECASE if case_insensitive else 0
            try:
                pattern = _re.compile(query, flags)
                use_regex = True
            except _re.error:
                use_regex = False

            for root, dirs, files in os.walk(root_dir):
                dirs[:] = [d for d in dirs if d not in AgentToolHandler.EXCLUDE_DIRS]
                for file in files:
                    if file == "crash.log":
                        continue
                    if file_pattern and not fnmatch.fnmatch(file, file_pattern):
                        continue
                    path = os.path.join(root, file)
                    rel_path = os.path.relpath(path, root_dir)
                    try:
                        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                            for i, line in enumerate(f):
                                hit = (pattern.search(line) if use_regex
                                       else (query.lower() in line.lower() if case_insensitive
                                             else query in line))
                                if hit:
                                    matches.append(f"{rel_path}:{i+1}: {line.strip()[:120]}")
                                    if len(matches) >= max_results:
                                        return "\n".join(matches) + f"\n... (Showing first {max_results} results)"
                    except Exception:
                        continue
            if not matches:
                return f"No matches found for '{query}'"
            return "\n".join(matches)
        except Exception as e:
            return f"[Error searching files: {e}]"

    @staticmethod
    def get_file_structure(path):
        """Returns the structure (classes/methods) of a Python file."""
        if not os.path.exists(path):
            return f"[Error: File not found: {path}]"
        if not path.endswith('.py'):
            return "[Info: structure extraction only supported for .py files]"
        try:
            import ast
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read())

            structure = []

            def visit(node, indent=0):
                if isinstance(node, ast.ClassDef):
                    structure.append(f"{'  ' * indent}Class: {node.name} (Line {node.lineno})")
                    for child in node.body:
                        visit(child, indent + 1)
                elif isinstance(node, ast.FunctionDef):
                    structure.append(f"{'  ' * indent}Function/Method: {node.name} (Line {node.lineno})")

            for node in tree.body:
                visit(node)

            return "\n".join(structure) if structure else "[No classes/functions found]"
        except Exception as e:
            return f"[Error parsing file structure: {e}]"

    # ------------------------------------------------------------------
    # WRITE (project-only)
    # ------------------------------------------------------------------
    @staticmethod
    def write_file(path, content):
        """Writes content to a file. Must be inside the project directory."""
        try:
            _require_inside_project(path, action="write to")
        except PermissionError as e:
            return f"[Permission Denied: {e}]"
        try:
            full_path = os.path.abspath(path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"[Success: File written to {full_path}]"
        except Exception as e:
            return f"[Error writing file: {e}]"

    @staticmethod
    def move_file(src, dst):
        """Moves or renames a file or directory. Both paths must be in the project."""
        import shutil
        try:
            _require_inside_project(src, action="move from")
            _require_inside_project(dst, action="move to")
        except PermissionError as e:
            return f"[Permission Denied: {e}]"
        try:
            dst_dir = os.path.dirname(os.path.abspath(dst))
            if dst_dir and not os.path.exists(dst_dir):
                os.makedirs(dst_dir, exist_ok=True)
            shutil.move(src, dst)
            return f"[Success: Moved '{src}' to '{dst}']"
        except Exception as e:
            return f"[Error moving file: {e}]"

    @staticmethod
    def copy_file(src, dst):
        """Copies a file. Destination must be inside the project directory."""
        import shutil
        try:
            _require_inside_project(dst, action="copy to")
        except PermissionError as e:
            return f"[Permission Denied: {e}]"
        try:
            dst_dir = os.path.dirname(os.path.abspath(dst))
            if dst_dir and not os.path.exists(dst_dir):
                os.makedirs(dst_dir, exist_ok=True)
            shutil.copy2(src, dst)
            return f"[Success: Copied '{src}' to '{dst}']"
        except Exception as e:
            return f"[Error copying file: {e}]"

    @staticmethod
    def delete_file(path):
        """Deletes a file or directory. Must be inside the project directory."""
        import shutil
        try:
            _require_inside_project(path, action="delete")
        except PermissionError as e:
            return f"[Permission Denied: {e}]"
        try:
            if os.path.isfile(path):
                os.remove(path)
                return f"[Success: Deleted file '{path}']"
            elif os.path.isdir(path):
                shutil.rmtree(path)
                return f"[Success: Deleted directory '{path}']"
            else:
                return f"[Error: Path not found '{path}']"
        except Exception as e:
            return f"[Error deleting '{path}': {e}]"

    @staticmethod
    def execute_command(command, cwd=None, timeout=120):
        """Executes a shell command with streaming output capture.
        Working directory must be inside the project. Default timeout: 120s."""
        import subprocess
        effective_cwd = cwd or os.getcwd()
        try:
            _require_inside_project(effective_cwd, action="execute commands in")
        except PermissionError as e:
            return f"[Permission Denied: {e}]"
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=effective_cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = ""
            if result.stdout:
                output += f"STDOUT:\n{result.stdout}"
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"
            if result.returncode != 0:
                output += f"\n[Exit code: {result.returncode}]"
            return output.strip() or "[Command completed with no output]"
        except subprocess.TimeoutExpired:
            return f"[Error: Command timed out after {timeout}s. Consider running it manually.]"
        except Exception as e:
            return f"[Error executing command: {e}]"

    @staticmethod
    def edit_file(path, old_text, new_text):
        """Replaces a specific text block in a file (surgical edit).
        Much more token-efficient than rewriting the whole file."""
        try:
            _require_inside_project(path, action="edit")
        except PermissionError as e:
            return f"[Permission Denied: {e}]"
        full_path = os.path.abspath(path)
        if not os.path.exists(full_path):
            return f"[Error: File not found: {full_path}]"
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if old_text not in content:
                return (
                    f"[Error: old_text not found in {path}. "
                    f"Make sure the text matches exactly (including whitespace).]"
                )
            count = content.count(old_text)
            if count > 1:
                return (
                    f"[Error: old_text matches {count} locations in {path}. "
                    f"Provide more surrounding context to make it unique.]"
                )
            new_content = content.replace(old_text, new_text, 1)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return f"[Success: Edited {full_path} — replaced {len(old_text)} chars with {len(new_text)} chars]"
        except Exception as e:
            return f"[Error editing file: {e}]"

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    @staticmethod
    def validate_syntax(code, filename):
        """Checks code for syntax errors."""
        _, ext = os.path.splitext(filename)
        if ext == '.py':
            try:
                compile(code, filename, 'exec')
                return None
            except SyntaxError as e:
                return f"SyntaxError line {e.lineno}: {e.msg}"
        return None

    @staticmethod
    def get_diff(old_content, new_content, filename):
        """Generates a unified diff."""
        import difflib
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=3,
        )
        return "\n".join(list(diff))
