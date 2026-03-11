import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = ROOT / "dist" / "windows"
WORK_ROOT = ROOT / "build" / "pyinstaller"
SPEC_ROOT = ROOT / "build" / "specs"
GUI_NAME = "VoxAI_IDE"
TERMINAL_NAME = "VoxAI_Terminal"


def data_arg(source: str, dest: str) -> str:
    return f"--add-data={ROOT / source};{dest}"


def run_pyinstaller(*args: str) -> None:
    cmd = [sys.executable, "-m", "PyInstaller", *args]
    print("[build]", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def build_gui() -> Path:
    run_pyinstaller(
        "--noconfirm",
        "--clean",
        "--windowed",
        f"--name={GUI_NAME}",
        f"--distpath={DIST_ROOT}",
        f"--workpath={WORK_ROOT / 'gui'}",
        f"--specpath={SPEC_ROOT}",
        data_arg("resources", "resources"),
        data_arg("Vox_RIG", "Vox_RIG"),
        data_arg("keys/secrets.template.json", "keys"),
        "main.py",
    )
    return DIST_ROOT / GUI_NAME


def build_terminal() -> Path:
    run_pyinstaller(
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        f"--name={TERMINAL_NAME}",
        f"--distpath={DIST_ROOT}",
        f"--workpath={WORK_ROOT / 'terminal'}",
        f"--specpath={SPEC_ROOT}",
        data_arg("resources", "resources"),
        data_arg("Vox_RIG", "Vox_RIG"),
        data_arg("keys/secrets.template.json", "keys"),
        "cli/terminal_mode.py",
    )
    return DIST_ROOT / f"{TERMINAL_NAME}.exe"


def build_portable_zip(gui_dir: Path) -> Path:
    archive_base = DIST_ROOT / f"{GUI_NAME}_portable"
    archive_path = shutil.make_archive(str(archive_base), "zip", root_dir=gui_dir)
    return Path(archive_path)


def main() -> None:
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    SPEC_ROOT.mkdir(parents=True, exist_ok=True)

    gui_dir = build_gui()
    terminal_exe = build_terminal()

    bundled_terminal = gui_dir / terminal_exe.name
    shutil.copy2(terminal_exe, bundled_terminal)
    portable_zip = build_portable_zip(gui_dir)

    print(f"[done] GUI folder: {gui_dir}")
    print(f"[done] Terminal exe: {bundled_terminal}")
    print(f"[done] Portable zip: {portable_zip}")


if __name__ == "__main__":
    main()