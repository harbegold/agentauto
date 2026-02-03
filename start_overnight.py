#!/usr/bin/env python3
"""
Stop any existing overnight run, then start run_overnight.py with venv Python in the background.
Run from project root:  python start_overnight.py
"""
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DIR = SCRIPT_DIR / "out"
RUN_OVERNIGHT = SCRIPT_DIR / "run_overnight.py"


def _get_venv_python() -> Path:
    for name in (".venv312", ".venv", "venv"):
        venv = SCRIPT_DIR / name / "Scripts" / "python.exe"
        if venv.exists():
            return venv
        venv = SCRIPT_DIR / name / "bin" / "python"
        if venv.exists():
            return venv
    return Path(sys.executable)


def _kill_existing_overnight() -> None:
    """Stop any process whose command line contains run_overnight.py (Windows or Unix)."""
    try:
        if sys.platform == "win32":
            # PowerShell: get processes with CommandLine containing run_overnight, then stop them
            cmd = [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run_overnight*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            ]
            subprocess.run(cmd, cwd=SCRIPT_DIR, capture_output=True, timeout=15)
        else:
            # Unix: pkill -f run_overnight.py
            subprocess.run(["pkill", "-f", "run_overnight.py"], capture_output=True, timeout=5)
    except Exception:
        pass


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    _kill_existing_overnight()

    python_exe = _get_venv_python()
    if not RUN_OVERNIGHT.exists():
        print("run_overnight.py not found", file=sys.stderr)
        return 1

    pid_path = OUT_DIR / "overnight.pid"

    if sys.platform == "win32":
        # Start via PowerShell Start-Process so it's a separate process tree and won't die when we exit
        py = str(python_exe).replace("'", "''")
        wd = str(SCRIPT_DIR).replace("'", "''")
        pid_file = str(pid_path).replace("'", "''")
        cmd = [
            "powershell", "-NoProfile", "-Command",
            f"$p = Start-Process -FilePath '{py}' -ArgumentList 'run_overnight.py' -WorkingDirectory '{wd}' -WindowStyle Hidden -PassThru; Set-Content -Path '{pid_file}' -Value $p.Id"
        ]
        r = subprocess.run(cmd, cwd=SCRIPT_DIR, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            print(f"Start-Process failed: {r.stderr or r.stdout}", file=sys.stderr)
            return 1
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except Exception:
            pid = 0
        print(f"Overnight started (PID {pid}). Log: out/overnight.log")
    else:
        # Unix: Popen with detach
        proc = subprocess.Popen(
            [str(python_exe), str(RUN_OVERNIGHT)],
            cwd=str(SCRIPT_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        pid_path.write_text(str(proc.pid), encoding="utf-8")
        print(f"Overnight started (PID {proc.pid}). Log: out/overnight.log")

    return 0


if __name__ == "__main__":
    sys.exit(main())
