"""Learn from runs: persist which method worked per step and try it first next time."""
import json
import time
from pathlib import Path
from typing import Optional

from .metrics import StepResult


LEARNED_FILENAME = "learned.json"


def load_learned(out_dir: Path, shared_dir: Optional[Path] = None) -> dict[int, str]:
    """
    Load learned.json if it exists. Returns dict step -> method (e.g. 1 -> "dom", 2 -> "localStorage").
    If shared_dir is set, load from shared_dir first (so learning persists across runs), then out_dir.
    """
    for base in (shared_dir, out_dir):
        if base is None:
            continue
        path = base / LEARNED_FILENAME
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            method_per_step = data.get("method_per_step")
            if isinstance(method_per_step, dict):
                return {int(k): str(v) for k, v in method_per_step.items() if str(v) in ("dom", "localStorage", "network")}
        except Exception:
            pass
    return {}


def save_learned(out_dir: Path, step_results: list[StepResult], shared_dir: Optional[Path] = None) -> None:
    """
    From successful steps, write method_per_step to learned.json so next run tries those methods first.
    If shared_dir is set, merge this run's successes into shared learned.json so learning persists across runs.
    """
    if not step_results:
        return
    method_per_step: dict[str, str] = {}
    for s in step_results:
        if s.ok and s.method:
            method_per_step[str(s.step)] = s.method
    if not method_per_step:
        return
    data = {
        "method_per_step": method_per_step,
        "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "steps_count": len(method_per_step),
    }
    # Always save to run folder (this run's record)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / LEARNED_FILENAME, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    # Merge into shared so overnight runs learn from each other
    if shared_dir:
        try:
            existing = load_learned(Path("."), shared_dir=shared_dir)  # load from shared only
            merged = {str(k): v for k, v in existing.items()}
            for s in step_results:
                if s.ok and s.method:
                    merged[str(s.step)] = s.method
            shared_dir.mkdir(parents=True, exist_ok=True)
            path = shared_dir / LEARNED_FILENAME
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "method_per_step": merged,
                    "last_updated": data["last_updated"],
                    "steps_count": len(merged),
                }, f, indent=2)
        except Exception:
            pass
