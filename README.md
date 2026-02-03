# Browser Navigation Challenge Agent

Automation agent that completes all 30 steps of the Brett Adcock browser navigation challenge in **under 5 minutes** using **Python 3.12** and **Playwright (async)**. Deterministic-first extraction (DOM + storage + network); optional **LLM fallback** when stuck.

**LinkedIn instructions:** Solve all 30 challenges in under 5 minutes; use any tools; provide zip with run instructions and run statistics (time, token usage, token cost).

## Stack

- **Language:** Python 3.12 (stable for Playwright)
- **Browser automation:** Playwright (async)
- **Optional LLM layer:** OpenAI API (fallback when deterministic logic can’t solve a step)
- **Logging:** Python `logging` + optional **Rich** for console
- **Debug artifacts:** Playwright video, optional tracing, failure screenshots, **live_status.md** (live view during run)

**Rationale:** Playwright is reliable and fast for adversarial UI (popups, overlays, storage, network). Deterministic extraction is fastest and reproducible; LLM is used only when enabled and when deterministic methods fail.

## Setup

```bash
# Create virtual environment (in repo or outside, e.g. C:\venvs)
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Unix/macOS)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright Chromium
playwright install chromium
```

**Requirements:** `playwright`, `rich` (prettier console logs). For LLM fallback: `pip install openai` and set `OPENAI_API_KEY`.

## Run

### Default: run until 30 steps in under 5 minutes (live status file)

The agent runs up to 30 iterations (5 min each). Each run uses **fast mode** (shorter waits) to stay under 5 minutes. Watch **`out/live_status.md`** for live progress: *"Iteration N: got to step X"*.

```bash
python main.py "https://lnkd.in/e-YBMMv7"
```

### Headful (watch the browser)

```bash
python main.py "https://lnkd.in/e-YBMMv7" --headful
```

### Single run only (no loop until 30)

```bash
python main.py "https://lnkd.in/e-YBMMv7" --no-run-until-30
```

### LLM fallback (when deterministic fails)

Set `OPENAI_API_KEY` and opt in:

```bash
set OPENAI_API_KEY=sk-...
python main.py "https://lnkd.in/e-YBMMv7" --use-llm
```

Optional: `--max-llm-calls 10` (default), `--model gpt-4o-mini`.

## CLI options

| Option | Description |
|--------|-------------|
| `--headful` | Run browser visible |
| `--slowmo MS` | Slow down operations by MS milliseconds |
| `--video` / `--no-video` | Record video to `out/videos` (default: on) |
| `--trace` | Enable Playwright tracing → `out/traces/run_trace.zip` |
| `--timeout-minutes N` | Timeout per run in minutes (default: 5) |
| `--no-block-resources` | Do not block images/fonts/media |
| `--out-dir DIR` | Output directory (default: `out`) |
| `--max-iterations N` | Max iterations until 30 steps in <5 min (default: 30) |
| `--run-until-30` / `--no-run-until-30` | Keep running until 30 steps in under 5 min (default: on) |
| `--continue-on-error` | On step failure, continue to next step |
| `--use-llm` | Use LLM fallback when deterministic extraction fails (requires `OPENAI_API_KEY`) |
| `--max-llm-calls N` | Max LLM calls per run (default: 10) |
| `--model MODEL` | OpenAI model for LLM fallback (default: gpt-4o-mini) |
| `--diagnostic-screenshots` | Screenshot every second for 60s → `out/diagnostic/` |

## Outputs (under `out/` or `--out-dir`)

- **results.json** — Run statistics: time taken (wall clock), solved/attempted counts, per-step timing and method, **token_usage** (when LLM used), **token_cost_usd**
- **live_status.md** — **Live view:** *Iteration N: got to step X* (updated on every step advance)
- **results_iter_N.json** — Per-iteration results for inspection
- **debug.log** — Detailed debug (storage keys, extraction source, errors, video path)
- **fail_step_XX.png** — Screenshot on failure for step XX
- **videos/*.webm** — Recording of each run
- **traces/run_trace.zip** — Playwright trace when `--trace` is used
- **learned.json** — Method that worked per step; next run tries those first

## Approach

1. **Deterministic-first**
   - Try code extraction via **DOM** (reveal button, regex), then **localStorage/sessionStorage**, then **network** (intercepted JSON).
   - Normalize UI: close promotional popups; handle “Please Select an Option” modal (correct option + Submit inside modal only); avoid decoy buttons.
   - Fill code input and submit via the “Enter Code to Proceed” section only (never decoys).

2. **Fast path**
   - If codes are present in storage or network cache, use them to submit without DOM extraction.

3. **LLM fallback** (only with `--use-llm` and `OPENAI_API_KEY`)
   - When deterministic extraction fails, the agent sends the model: URL, visible buttons/inputs, body snippet (~2k chars), current step.
   - Model returns a small JSON action plan: `click`, `type`, `press`, `scroll`.
   - Actions are validated and executed with Playwright; then deterministic extraction is retried.

4. **Performance**
   - Headless by default; block images/fonts/media via request routing; short waits (250 ms polling where used).

## Run statistics (LinkedIn requirements)

- **Time taken:** Wall-clock seconds in `results.json` (`total_seconds`) and in console.
- **Token usage:** When `--use-llm` is set, `results.json` includes `token_usage` (e.g. `prompt_tokens`, `completion_tokens`, `total_tokens`) and **token_cost_usd** (estimated cost for the run).

## Submission

After the run, **submission.zip** is created with source, README, RUN_INSTRUCTIONS.md, `out/results.json`, and `out/debug.log`. Excluded: `.venv`, `__pycache__`, `node_modules`.
