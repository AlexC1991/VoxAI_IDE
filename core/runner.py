from PySide6.QtCore import QObject, Signal, QProcess, QProcessEnvironment
import sys
import os
import tempfile
import logging

log = logging.getLogger(__name__)


class Runner(QObject):
    execution_started = Signal(str)
    output_received = Signal(str, bool)  # text, is_error
    execution_finished = Signal(int)

    def __init__(self):
        super().__init__()
        self.process = QProcess()
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.on_finished)
        self._temp_exe: str | None = None

    def run_script(self, script_path):
        if self.process.state() == QProcess.Running:
            log.info("Process already running — terminating")
            self.process.kill()
            self.process.waitForFinished(1000)

        self._cleanup_temp()
        self.execution_started.emit(script_path)

        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self.process.setProcessEnvironment(env)

        _, ext = os.path.splitext(script_path)
        ext = ext.lower()

        if ext == '.py':
            python_exe = self._find_python(script_path)
            self.process.start(python_exe, [script_path])

        elif ext in ('.js', '.mjs', '.cjs'):
            self.process.start("node", [script_path])

        elif ext == '.ts':
            self.process.start("ts-node", [script_path])

        elif ext == '.go':
            self.process.start("go", ["run", script_path])

        elif ext == '.rs':
            self._run_compiled("rustc", script_path)

        elif ext in ('.cpp', '.cc'):
            self._run_compiled("g++", script_path)

        elif ext == '.c':
            self._run_compiled("gcc", script_path)

        elif ext == '.java':
            self.process.start("java", [script_path])

        elif ext == '.bat':
            self.process.start("cmd.exe", ["/c", script_path])

        elif ext in ('.sh', '.bash'):
            shell = "bash" if os.name != "nt" else "wsl"
            self.process.start(shell, [script_path])

        elif ext == '.ps1':
            self.process.start("powershell", ["-File", script_path])

        else:
            self.process.start(script_path, [])

    def _find_python(self, script_path: str) -> str:
        python_exe = sys.executable
        script_dir = os.path.dirname(os.path.abspath(script_path))
        search_dir = script_dir
        for _ in range(3):
            for venv_name in (".venv", "venv", "env"):
                venv_path = os.path.join(search_dir, venv_name)
                if not os.path.isdir(venv_path):
                    continue
                candidates = [
                    os.path.join(venv_path, "Scripts", "python.exe"),
                    os.path.join(venv_path, "bin", "python"),
                ]
                for candidate in candidates:
                    if os.path.exists(candidate):
                        log.info("Using venv Python: %s", candidate)
                        return candidate
            parent = os.path.dirname(search_dir)
            if parent == search_dir:
                break
            search_dir = parent
        return python_exe

    def _run_compiled(self, compiler: str, script_path: str):
        """Compile-then-run for C/C++/Rust — cross-platform."""
        suffix = ".exe" if os.name == "nt" else ""
        exe_name = os.path.join(tempfile.gettempdir(),
                                f"voxai_run_{os.path.basename(script_path)}{suffix}")
        self._temp_exe = exe_name
        if os.name == "nt":
            chain = f'{compiler} "{script_path}" -o "{exe_name}" && "{exe_name}"'
            self.process.start("cmd.exe", ["/c", chain])
        else:
            chain = f'{compiler} "{script_path}" -o "{exe_name}" && "{exe_name}"'
            self.process.start("sh", ["-c", chain])

    def _cleanup_temp(self):
        if self._temp_exe and os.path.exists(self._temp_exe):
            try:
                os.remove(self._temp_exe)
            except OSError:
                pass
        self._temp_exe = None

    def handle_stdout(self):
        data = self.process.readAllStandardOutput()
        text = data.data().decode('utf-8', errors='replace')
        self.output_received.emit(text.strip(), False)

    def handle_stderr(self):
        data = self.process.readAllStandardError()
        text = data.data().decode('utf-8', errors='replace')
        self.output_received.emit(text.strip(), True)

    def on_finished(self, exit_code, exit_status):
        self._cleanup_temp()
        self.execution_finished.emit(exit_code)
