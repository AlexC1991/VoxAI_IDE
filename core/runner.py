from PySide6.QtCore import QObject, Signal, QProcess, QProcessEnvironment

class Runner(QObject):
    execution_started = Signal(str)
    output_received = Signal(str, bool) # text, is_error
    execution_finished = Signal(int)

    def __init__(self):
        super().__init__()
        self.process = QProcess()
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.on_finished)

    def run_script(self, script_path):
        if self.process.state() == QProcess.Running:
            print("[Runner] Process already running. Terminating...")
            self.process.kill()
            self.process.waitForFinished(1000) # Wait up to 1s
            
        self.execution_started.emit(script_path)
        
        # Set environment to force unbuffered output
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self.process.setProcessEnvironment(env)
        
        # Start process based on extension
        import sys
        import os
        
        _, ext = os.path.splitext(script_path)
        ext = ext.lower()
        
        if ext == '.py':
            python_exe = sys.executable
            
            # Smart Venv Detection
            # Check if there's a venv in the script's directory or project root
            # This is a bit tricky since we don't strictly know "Project Root" here, 
            # but we can assume the script is likely inside the project.
            
            script_dir = os.path.dirname(os.path.abspath(script_path))
            start_dir = script_dir
            found_venv = False
            
            # Climb up 3 levels to find venv
            for _ in range(3):
                for venv_name in [".venv", "venv", "env"]:
                    venv_path = os.path.join(start_dir, venv_name)
                    if os.path.isdir(venv_path):
                        # Windows specific check
                        candidate = os.path.join(venv_path, "Scripts", "python.exe")
                        if os.path.exists(candidate):
                            python_exe = candidate
                            print(f"[Runner] Using Venv Python: {python_exe}")
                            found_venv = True
                            break
                        # Linux/Mac check (Scripts vs bin)
                        candidate = os.path.join(venv_path, "bin", "python")
                        if os.path.exists(candidate):
                            python_exe = candidate
                            print(f"[Runner] Using Venv Python: {python_exe}")
                            found_venv = True
                            break
                if found_venv: break
                parent = os.path.dirname(start_dir)
                if parent == start_dir: break # Root reached
                start_dir = parent
                
            self.process.start(python_exe, [script_path])
            self.process.start(python_exe, [script_path])
        
        elif ext in ['.js', '.mjs', '.cjs']:
            self.process.start("node", [script_path])
            
        elif ext == '.ts':
            # Check if ts-node is available, or use node with loader, or just try npx?
            # Simplest for now: ts-node if installed, else error/fallback
            # Let's assume user has `ts-node` in checks.
            self.process.start("ts-node", [script_path])
            
        elif ext == '.go':
            self.process.start("go", ["run", script_path])
            
        elif ext == '.rs':
            # Rust needs compilation or `cargo run` if in project.
            # Single file: rustc then run? Or use `cargo script` (experimental)?
            # Simplest single file: rustc -o temp.exe main.rs && temp.exe
            # But that's complex for a runner.
            # Let's try `rustc` to a temp bin then run it?
            # Or assume cargo is used if Cargo.toml exists?
            # For a single .rs file script, we can compile to a temp dir.
            import tempfile
            exe_name = os.path.join(tempfile.gettempdir(), f"{os.path.basename(script_path)}.exe")
            # We can't chain commands easily with QProcess unless we use shell.
            # Let's use shell for Rust for now.
            cmd = f"rustc \"{script_path}\" -o \"{exe_name}\" && \"{exe_name}\""
            self.process.start("cmd.exe", ["/c", cmd])
            
        elif ext in ['.cpp', '.cc']:
            # g++ or clang++
            import tempfile
            exe_name = os.path.join(tempfile.gettempdir(), f"{os.path.basename(script_path)}.exe")
            cmd = f"g++ \"{script_path}\" -o \"{exe_name}\" && \"{exe_name}\""
            self.process.start("cmd.exe", ["/c", cmd])
            
        elif ext == '.c':
            import tempfile
            exe_name = os.path.join(tempfile.gettempdir(), f"{os.path.basename(script_path)}.exe")
            cmd = f"gcc \"{script_path}\" -o \"{exe_name}\" && \"{exe_name}\""
            self.process.start("cmd.exe", ["/c", cmd])

        elif ext == '.java':
            # Single file source code execution (Java 11+)
            self.process.start("java", [script_path])
            
        elif ext == '.bat':
            self.process.start("cmd.exe", ["/c", script_path])
        elif ext in ['.sh', '.bash']:
            # Windows might have git bash or wsl.
            # Try bash.
            self.process.start("bash", [script_path])
        elif ext == '.ps1':
             self.process.start("powershell", ["-File", script_path])
        else:
            # Try to run directly (e.g. .exe or associated program)
            self.process.start(script_path, [])

    def handle_stdout(self):
        data = self.process.readAllStandardOutput()
        text = data.data().decode('utf-8', errors='replace')
        self.output_received.emit(text.strip(), False)

    def handle_stderr(self):
        data = self.process.readAllStandardError()
        text = data.data().decode('utf-8', errors='replace')
        self.output_received.emit(text.strip(), True)

    def on_finished(self, exit_code, exit_status):
        self.execution_finished.emit(exit_code)
