#!/usr/bin/env python3
"""
Run the agent in a loop until 30 steps completed in under 5 minutes, or max wall time (8 hours).
Logs to out/overnight.log. Writes out/OVERNIGHT_SUCCESS.txt on success, out/last_error.txt on failure.
Use the project venv's Python so playwright is available when run in background.
"""
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DIR = SCRIPT_DIR / "out"
MAX_WALL_SECONDS = 8 * 3600  # 8 hours
URL = "https://serene-frangipane-7fd25b.netlify.app/"
RUN_TIMEOUT = 2100  # 35 min per main.py run (30 iters × ~1 min; success would be <5 min)
LAST_ERROR_PATH = OUT_DIR / "last_error.txt"


def _get_python_exe() -> Path:
    """Use venv Python if present (e.g. .venv312 or .venv), else sys.executable."""
    for name in (".venv312", ".venv", "venv"):
        venv = SCRIPT_DIR / name / "Scripts" / "python.exe"
        if venv.exists():
            return venv
        venv = SCRIPT_DIR / name / "bin" / "python"
        if venv.exists():
            return venv
    return Path(sys.executable)


def _clear_last_error() -> None:
    if LAST_ERROR_PATH.exists():
        try:
            LAST_ERROR_PATH.unlink()
        except Exception:
            pass


def _write_last_error(err: BaseException) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(LAST_ERROR_PATH, "w", encoding="utf-8") as f:
            f.write(datetime.now(timezone.utc).isoformat() + "\n")
            f.write(str(err) + "\n\n")
            f.write(traceback.format_exc())
    except Exception:
        pass


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUT_DIR / "overnight.log"
    start = datetime.now(timezone.utc)
    run_count = 0
    consecutive_fast_failures = 0  # detect repeated instant failure (e.g. no playwright)

    with open(log_path, "a", encoding="utf-8") as log:
        def log_msg(msg: str) -> None:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            line = f"[{ts}] {msg}\n"
            log.write(line)
            log.flush()
            print(line.strip(), flush=True)

        log_msg("Overnight run started.")

        while (datetime.now(timezone.utc) - start).total_seconds() < MAX_WALL_SECONDS:
            run_count += 1
            log_msg(f"--- Run #{run_count} ---")
            run_start = datetime.now(timezone.utc)

            try:
                python_exe = _get_python_exe()
                result = subprocess.run(
                    [
                        str(python_exe), "main.py", URL,
                        "--no-video",
                    ],
                    cwd=SCRIPT_DIR,
                    timeout=RUN_TIMEOUT,
                    capture_output=True,
                    text=True,
                )
                elapsed = (datetime.now(timezone.utc) - run_start).total_seconds()

                if result.returncode == 0:
                    _clear_last_error()
                    log_msg("SUCCESS: 30 steps in under 5 minutes.")
                    (OUT_DIR / "OVERNIGHT_SUCCESS.txt").write_text(
                        f"Completed at run #{run_count}\n{datetime.now(timezone.utc).isoformat()}\n"
                    )
                    return 0

                # Log stderr so we can see why main.py failed
                if result.stderr:
                    for line in result.stderr.strip().splitlines()[-20:]:
                        log_msg(f"  stderr: {line}")
                if elapsed < 30:
                    consecutive_fast_failures += 1
                    if consecutive_fast_failures >= 3:
                        log_msg("WARNING: 3+ runs failed in under 30s. Check last_error or stderr above; ensure venv has playwright.")
                        _write_last_error(RuntimeError(result.stderr or "main.py exited non-zero quickly"))
                else:
                    consecutive_fast_failures = 0

            except subprocess.TimeoutExpired as e:
                consecutive_fast_failures = 0
                log_msg("Run timed out; restarting.")
                _write_last_error(e)
            except Exception as e:
                log_msg(f"Run error: {type(e).__name__}: {e}; restarting.")
                _write_last_error(e)

        log_msg("Stopped after max wall time (8 hours).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
