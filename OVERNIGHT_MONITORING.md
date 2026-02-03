# Overnight Run – What to Monitor and When to Fix

## Automatic monitoring (Cursor rule)

When you (or the AI) work in this project, the rule in `.cursor/rules/agent-automation-monitor.mdc` applies: **check overnight run health and fix issues** without being asked again. The AI will:

- Read `out/overnight.log` and `out/last_error.txt`
- Ensure learning persists (`out/learned.json`) and fix if not
- Look at latest `out/run_*/results.json` for repeated failures
- After any fix, tell you how to restart the overnight run if needed

## What to check

| Check | Where | Action if wrong |
|-------|--------|------------------|
| Runs finishing in &lt;30s repeatedly | `out/overnight.log` | main.py likely failing (e.g. no playwright). Use venv Python: `.\.venv312\Scripts\python.exe run_overnight.py` |
| Last error details | `out/last_error.txt` | Fix the cause (import, timeout, etc.) and restart overnight |
| Learning not persisting | `out/learned.json` | Should exist and grow across runs. If not, ensure `shared_learned_dir` is passed and `save_learned` writes to shared dir |
| Same step failing every run | `out/run_<latest>/results_iter_*.json` | Improve extraction/retry for that step (e.g. step 4/5 "submit did not advance") |
| Success | `out/OVERNIGHT_SUCCESS.txt` | Run completed: 30 steps in under 5 min |

## Quick status

From project root:

```bash
python scripts/check_overnight_status.py
```

Prints: success or not, last error snippet, last log lines, shared learned steps, latest run stats.

## Restarting the overnight run

If you fix something or need to start fresh:

```powershell
cd "C:\Users\harry\Documents\agent automation"
.\.venv312\Scripts\python.exe run_overnight.py
```

Leave the window open or run in background. Learning will continue from `out/learned.json` across restarts.
