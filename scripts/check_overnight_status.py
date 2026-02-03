#!/usr/bin/env python3
"""Print a short status summary of the overnight run. Run from project root."""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT = PROJECT_ROOT / "out"


def main() -> int:
    print("--- Overnight run status ---\n")

    # Success?
    success_path = OUT / "OVERNIGHT_SUCCESS.txt"
    if success_path.exists():
        print("SUCCESS: 30 steps in under 5 min.")
        print(success_path.read_text(encoding="utf-8").strip())
        return 0

    # Last error?
    last_err = OUT / "last_error.txt"
    if last_err.exists():
        print("Last error (out/last_error.txt):")
        print(last_err.read_text(encoding="utf-8").strip()[:800])
        print()

    # Log tail
    log_path = OUT / "overnight.log"
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        print("Last 15 log lines:")
        for line in lines[-15:]:
            print(line)
        print()

    # Shared learned
    learned_path = OUT / "learned.json"
    if learned_path.exists():
        try:
            data = json.loads(learned_path.read_text(encoding="utf-8"))
            steps = data.get("method_per_step", {})
            print(f"Shared learned: {len(steps)} steps (method_per_step: {list(steps.keys())})")
        except Exception:
            print("Shared learned: (could not read learned.json)")
    else:
        print("Shared learned: no out/learned.json yet")
    print()

    # Latest run folder
    run_dirs = sorted(OUT.glob("run_*"), key=lambda p: p.name, reverse=True)
    if run_dirs:
        latest = run_dirs[0]
        results_path = latest / "results.json"
        if results_path.exists():
            try:
                data = json.loads(results_path.read_text(encoding="utf-8"))
                print(f"Latest run: {latest.name}")
                print(f"  solved_count: {data.get('solved_count', '?')}, total_seconds: {data.get('total_seconds', '?'):.1f}")
                print(f"  steps: {[s.get('step') for s in data.get('steps', [])]}")
            except Exception:
                print(f"Latest run: {latest.name} (could not read results)")
        else:
            print(f"Latest run: {latest.name} (no results.json yet)")
    else:
        print("No run_* folders yet")

    return 0


if __name__ == "__main__":
    sys.exit(main())
