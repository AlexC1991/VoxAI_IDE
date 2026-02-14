import os

class AgentToolHandler:
    @staticmethod
    def read_file(path, start_line=1, end_line=300):
        """Reads content of a file. Defaults to first 300 lines."""
        if not os.path.exists(path):
            return f"[Error: File not found: {path}]"
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            total_lines = len(lines)
            
            # Adjust indices (1-based to 0-based)
            start_idx = max(0, start_line - 1)
            end_idx = min(total_lines, end_line)
            
            content = "".join(lines[start_idx:end_idx])
            
            if total_lines > end_line:
                content += f"\n... (Showing lines {start_line}-{end_line} of {total_lines}. Use read_file with start_line/end_line to see more.)"
                
            return content
        except Exception as e:
            return f"[Error reading file: {e}]"

    @staticmethod
    def write_file(path, content):
        """Writes content to a file."""
        try:
            # Ensure dir exists
            full_path = os.path.abspath(path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"[Success: File written to {full_path}]"
        except Exception as e:
            return f"[Error writing file: {e}]"
            
    @staticmethod
    def list_files(root_dir="."):
        """Lists all files in the directory recursively."""
        file_list = []
        exclude_dirs = {'.git', '__pycache__', '.idea', 'venv', 'env', '.gemini'}
        
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                if file == "crash.log": continue
                
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, root_dir)
                file_list.append(rel_path)
        
        return "\n".join(file_list)

    @staticmethod
    def move_file(src, dst):
        """Moves or renaming a file or directory."""
        import shutil
        try:
            # Ensure dst dir exists if it looks like a path
            dst_dir = os.path.dirname(os.path.abspath(dst))
            if dst_dir and not os.path.exists(dst_dir):
                os.makedirs(dst_dir, exist_ok=True)
                
            shutil.move(src, dst)
            return f"[Success: Moved '{src}' to '{dst}']"
        except Exception as e:
            return f"[Error moving file: {e}]"

    @staticmethod
    def copy_file(src, dst):
        """Copies a file."""
        import shutil
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
        """Deletes a file or directory."""
        import shutil
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

    def execute_command(command, cwd=None):
        """Executes a shell command."""
        import subprocess
        try:
            # shell=True is dangerous but needed for some commands.
            # We trust the agent not to destroy the machine (scoped permission).
            result = subprocess.run(
                command, 
                shell=True, 
                cwd=cwd, 
                capture_output=True, 
                text=True,
                timeout=30 # Safety timeout
            )
            return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        except Exception as e:
            return f"[Error executing command: {e}]"

    @staticmethod
    def search_files(query, root_dir="."):
        """Searches for a string in all files (grep-like)."""
        matches = []
        exclude_dirs = {'.git', '__pycache__', '.idea', 'venv', 'env', '.gemini'}
        
        try:
            for root, dirs, files in os.walk(root_dir):
                dirs[:] = [d for d in dirs if d not in exclude_dirs]
                for file in files:
                    if file == "crash.log": continue
                    path = os.path.join(root, file)
                    rel_path = os.path.relpath(path, root_dir)
                    
                    try:
                        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                            lines = f.readlines()
                            for i, line in enumerate(lines):
                                if query in line:
                                    matches.append(f"{rel_path}:{i+1}: {line.strip()[:100]}")
                                    if len(matches) > 50: # Limit results
                                        return "\n".join(matches) + "\n... (Truncated)"
                    except:
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
            return f"[Info: structure extraction only supported for .py files]"
            
        try:
            import ast
            with open(path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read())
                
            structure = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    structure.append(f"Class: {node.name} (Line {node.lineno})")
                    for child in node.body:
                         if isinstance(child, ast.FunctionDef):
                             structure.append(f"  Method: {child.name} (Line {child.lineno})")
                elif isinstance(node, ast.FunctionDef):
                    # Only top-level functions (not inside class, handled above effectively or double counted?)
                    # ast.walk visits everything. We need a cleaner way or just list all.
                    # Let's just list only top level for now or specific visitor.
                    pass
            
            # Better approach: recursive visitor or just simple loop
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
    @staticmethod
    def validate_syntax(code, filename):
        """Checks code for syntax errors."""
        _, ext = os.path.splitext(filename)
        if ext == '.py':
            try:
                compile(code, filename, 'exec')
                return None # No error
            except SyntaxError as e:
                return f"SyntaxError line {e.lineno}: {e.msg}"
        return None # Not supported / assumed valid

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
            n=3 # Context lines
        )
        return "\n".join(list(diff))
