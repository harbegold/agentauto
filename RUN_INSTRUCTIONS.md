# How to Run the Agent and Reproduce Results

## Quick start

1. **Setup**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   # source .venv/bin/activate   # Unix/macOS
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Run the challenge (default: run until 30 steps in under 5 minutes)**
   ```bash
   python main.py "https://lnkd.in/e-YBMMv7"
   ```
   - Watch **`out/live_status.md`** for live progress: *Iteration N: got to step X*.
   - Each iteration has a 5-minute timeout and uses fast mode.

3. **Run with browser visible**
   ```bash
   python main.py "https://lnkd.in/e-YBMMv7" --headful
   ```

4. **Optional: LLM fallback when stuck**
   ```bash
   set OPENAI_API_KEY=sk-...
   python main.py "https://lnkd.in/e-YBMMv7" --use-llm
   ```

## Reproducing results

- **Run statistics** are in `out/results.json`: `total_seconds` (wall clock), `solved_count`, `attempted_count`, per-step timing and method, and (when LLM used) `token_usage` and `token_cost_usd`.
- **Per-iteration results** are in `out/results_iter_1.json`, `out/results_iter_2.json`, etc.
- **Debug log** is in `out/debug.log`.
- **Submission zip** is created at the end: `submission.zip` (source, README, RUN_INSTRUCTIONS.md, out/results.json, out/debug.log).

## Success criteria (LinkedIn challenge)

- Solve all 30 challenges in under 5 minutes.
- The agent stops when it completes 30 steps in a single run with `total_seconds` ≤ 300, or when `--max-iterations` is reached.
