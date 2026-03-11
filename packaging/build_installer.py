import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "packaging" / "VoxAI_installer.iss"
SOURCE_DIR = ROOT / "dist" / "windows" / "VoxAI_IDE"
OUTPUT_DIR = ROOT / "dist" / "installer"


def find_iscc() -> str:
    candidates = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    on_path = shutil.which("iscc")
    if on_path:
        return on_path
    raise FileNotFoundError("ISCC.exe not found. Install Inno Setup first.")


def main() -> None:
    if not SOURCE_DIR.exists():
        raise FileNotFoundError(f"Packaged app folder not found: {SOURCE_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        find_iscc(),
        f"/DSourceDir={SOURCE_DIR}",
        f"/DOutputDir={OUTPUT_DIR}",
        "/DAppVersion=2.0.0",
        str(SCRIPT_PATH),
    ]
    print("[build]", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)
    print(f"[done] Installer output dir: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()