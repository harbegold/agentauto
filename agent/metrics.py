"""Step and run metrics, JSON writer."""
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def redact_code(code: str) -> str:
    """Redact code for logging: first 2 + **** + last 2, or **** if too short."""
    if not code or len(code) < 4:
        return "****"
    return code[:2] + "****" + code[-2:]


@dataclass
class StepResult:
    step: int
    ok: bool
    seconds: float
    method: str  # dom, localStorage, sessionStorage, network, llm
    notes: str = ""
    code_redacted: Optional[str] = None  # e.g. "VR****7A" for debugging


@dataclass
class RunStats:
    url: str
    started_at: str
    finished_at: str
    total_seconds: float
    solved_count: int
    attempted_count: int
    steps: list[StepResult] = field(default_factory=list)
    environment: dict = field(default_factory=dict)
    headless: bool = True
    resource_blocking: bool = True
    token_usage: Optional[dict] = None  # e.g. {"prompt_tokens": N, "completion_tokens": M, "total_tokens": ...}
    token_cost_usd: Optional[float] = None  # estimated cost when LLM used

    def to_dict(self) -> dict:
        d = asdict(self)
        d["steps"] = [asdict(s) for s in self.steps]
        return d


def write_results(out_dir: Path, stats: RunStats, iteration: Optional[int] = None) -> None:
    """Write stats to results.json. If iteration is set, also write to results_iter_N.json for inspection."""
    out_dir.mkdir(parents=True, exist_ok=True)
    data = stats.to_dict()
    path = out_dir / "results.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote {path}", file=sys.stderr)
    if iteration is not None:
        iter_path = out_dir / f"results_iter_{iteration}.json"
        with open(iter_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"Wrote {iter_path}", file=sys.stderr)
