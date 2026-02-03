# Browser Navigation Challenge Agent – System Note

**Purpose:** Give this note to Claude Code (or another reviewer) so they can assess the design and suggest changes. Ask them: *“Review this system note and the codebase. What should be changed—architecture, module layout, robustness, performance, or correctness—and why?”*

---

## 1. Goal

- **What:** A Python + Playwright (async) agent that completes all 30 steps of the Brett Adcock “Browser Navigation Challenge” in one run.
- **Where:** Challenge URL is typically shared as `https://lnkd.in/e-YBMMv7` (redirects to the real site, e.g. `serene-frangipane-7fd25b.netlify.app`).
- **Per step:** The agent must interact with the page (close popups, handle “Please Select an Option” modals, possibly reveal a code), obtain a **step code** (never hardcoded), enter it into an “Enter Code to Proceed”–style input, and submit (Enter or Proceed/Next) to advance.
- **Target:** Finish all 30 steps as fast as possible (goal &lt; 5 minutes); support optional live view and video/trace for debugging.

---

## 2. High-Level Flow

1. **CLI** (`main.py`): Parse args (URL, headful, slowmo, video, trace, timeout, out-dir). Ensure `out/`, `out/videos/`, `out/traces/` exist. Run up to N iterations (default 5); each iteration calls `run_challenge`. Best run’s results are written; then `submission.zip` is created (source, README, `out/results.json`, `out/debug.log`).
2. **Runner** (`agent/runner.py`): Launch headless Chromium (or headful if `--headful`), optionally with `slow_mo`. Create a context with optional video recording and optional tracing. Navigate to URL, wait for load. If the page shows no “Step X of 30”, click **START** once and wait for the step page. Load **learned** strategy from `out/learned.json` (if present). For steps 1..30:
   - Close any popup **windows** (extra tabs) and bring focus back to main page.
   - Read current step from page (“Step X of 30”).
   - If on landing (no step), click START again and wait.
   - **Solve** the current step (with retries): handle “Please Select an Option” modal, normalize UI (close in-page popups), get code (learned method first, then localStorage / network / DOM), fill code input, submit.
   - Wait for step to advance (poll “Step X of 30”); if it doesn’t advance soon, increment expected step anyway.
3. After the run, **save learned** from successful steps to `out/learned.json` (method per step: dom / localStorage / network). Next run loads this and tries the learned method first per step.

No step codes are ever hardcoded; codes come from DOM, localStorage, sessionStorage, or network only.

---

## 3. Module Layout

| Module | Role |
|--------|------|
| **main.py** | CLI, iterations, timeout wrapper, `write_results`, `create_submission_zip`. |
| **agent/runner.py** | Browser launch, context (video/trace), main loop (expected_step 1..30), START click, load/save learned, call `solve_one_step` and `run_step`. |
| **agent/actions.py** | `normalize_ui` (close in-page popups: topmost dialog first, then ESC + Close/Dismiss), `close_popup_windows` (close extra tabs), `handle_select_option_modal` (scroll modal, select correct option, Submit), `find_and_fill_code_input`, scroll/visibility helpers. |
| **agent/extractors.py** | DOM code extraction (Reveal Code click, token regex), `get_challenge_code_for_step_from_storage` (localStorage `challenge_code_step_N`), `extract_codes_from_storage` (dump localStorage/sessionStorage, parse JSON or plain `challenge_code_step_N` keys), network response listener to harvest codes from JSON. |
| **agent/site.py** | Selectors and patterns: “Step X of 30”, code input placeholders, submit buttons, close button texts, modal/dialog selectors, code-like token heuristic. |
| **agent/metrics.py** | `StepResult`, `RunStats`, `write_results` → `out/results.json`. |
| **agent/learning.py** | `load_learned(out_dir)` → `dict[step, method]`, `save_learned(out_dir, step_results)` → `out/learned.json`. |

---

## 4. Two Solving Paths (No Hardcoded Codes)

- **Normal UI path:** Interact like a user: close popups, handle “Please Select an Option” (scroll modal, choose correct option, Submit), optionally click “Reveal Code”, then extract code from DOM (body text / input value) with a token regex (e.g. 6+ alphanumeric/dash/underscore), find the code input (placeholder/label containing “code”), fill and submit (Enter or Proceed/Next).
- **Fast path:** Before relying on DOM, try:
  1. **localStorage:** Read `challenge_code_step_{step}` (and optionally full dump with keys like `challenge_code_step_1` … `challenge_code_step_30`). Use any step→code map found (partial is OK).
  2. **sessionStorage:** Same idea; scan for step-indexed or JSON blobs with 30-ish codes.
  3. **Network:** Listener on responses; if JSON, search for arrays of length 30 or step-keyed codes; cache by step.
  If a code is found for the current step from storage/network, use it and submit; otherwise fall back to DOM.

Learned strategy only reorders **which** path is tried first per step (dom vs localStorage vs network); it does not inject codes.

---

## 5. UI Normalization and Popups

- **In-page popups:**  
  - **Topmost first:** Find dialogs (`[role=dialog]`, `[class*='modal']`), take the last in DOM (topmost), and inside it click Close / Dismiss / × / .close. Repeat a few times to peel nested modals (e.g. “Subscribe to our newsletter!” then “You have won a prize!”).  
  - **Then:** ESC several times, then click any visible button with text Close / Dismiss / Accept / OK / ×, or `.close` / `button.close`. Rounds and waits were tuned for speed (fewer rounds, shorter waits).
- **“Please Select an Option” modal:** Treated as **content**, not something to close. Before general normalize_ui, the runner calls `handle_select_option_modal`: detect modal by title text, scroll the modal container to bottom so options and Submit are visible, select the correct option (e.g. “This is correct”, “The right choice”, “Option B - Correct”) and click Submit & Continue / Submit / Continue. Then normalize_ui runs to close any other overlays.
- **Separate windows/tabs:** `close_popup_windows(context, main_page)` lists `context.pages`; for every page that isn’t the main one, run a quick close round (ESC + close buttons) and then `page.close()`, then bring main page to front.

---

## 6. Learning From Runs

- **Persist:** After each run, `save_learned(out_dir, step_results)` writes `out/learned.json` with `method_per_step`: for each successful step, the method that worked (`dom`, `localStorage`, or `network`).
- **Reuse:** At start of run, `load_learned(out_dir)` reads that map. In `run_step`, if there is a learned method for the current step, we try that path first (localStorage first, network first, or dom first), then fall back to the other paths. So the second and later runs tend to be faster when the same method keeps working.

No “training” in the ML sense; only “last successful method per step” is stored and preferred.

---

## 7. Configuration and Outputs

- **CLI:** `--headful`, `--slowmo MS`, `--video` / `--no-video`, `--trace`, `--timeout-minutes`, `--out-dir`, `--max-iterations`, `--no-block-resources`. Default: headless, video on, timeout 10 minutes, resource blocking on (images/fonts/media aborted).
- **Outputs under `out/`:**  
  - `results.json`: url, started_at, finished_at, total_seconds, solved_count, attempted_count, per-step (step, ok, seconds, method, notes), environment (python/playwright version, platform), headless, resource_blocking.  
  - `debug.log`: detailed log (navigation, step detected, method used per step, storage keys, failures, visible buttons).  
  - `fail_step_XX.png`: screenshot on failure for step XX.  
  - `videos/*.webm`: one recording per run (finalized on context close).  
  - `traces/run_trace.zip`: Playwright trace when `--trace` is used.  
  - `learned.json`: method_per_step, last_updated, steps_count.
- **Submission:** `submission.zip` contains source, README, `out/results.json`, `out/debug.log`; excludes `.venv`, `__pycache__`, `node_modules`, large binaries.

---

## 8. Assumptions and Edge Cases

- **Step detection:** “Step X of 30” is parsed from `document.body.innerText` with a regex. If the site changes wording or structure, parsing may break.
- **Code input:** Located by placeholder/name/id/aria-label containing “code”, or fallback to first visible text input. Submit by Enter or button text Proceed/Continue/Next.
- **localStorage keys:** We explicitly handle `challenge_code_step_N` (N = 1..30) as reported in the challenge; other keys are still scanned for JSON or step-like patterns.
- **No step 1 in storage:** If only `challenge_code_step_2` … `challenge_code_step_30` exist, step 1 is solved via DOM; other steps use storage when available.
- **Performance:** Many short `wait_for_timeout` calls and multiple normalize/close rounds were reduced for speed; if the site is slow or flaky, increasing rounds or waits might be needed.
- **Iterations:** Main loop runs up to `--max-iterations` (default 5); it stops earlier if 30/30 steps are solved. Each iteration is a full run (new browser/context).

---

## 9. What a Reviewer Might Check

- Whether the **order of operations** (e.g. handle_select_option_modal before normalize_ui, learned method first) is optimal.
- If **selectors** and **patterns** (Step X of 30, code input, submit button, correct option, close buttons) are robust across challenge versions.
- If **learning** should also persist things like “which close button worked” or “which selector found the code” for even faster runs.
- If **resource blocking** or **timeouts** (navigation, click, step-advance wait) are too aggressive or too loose.
- Whether **error recovery** (retries, screenshot on failure, re-reading step from page) is sufficient.
- Whether **submission.zip** and **results.json** contain everything required for grading/reproducibility.

---

## 10. How to Run

```bash
cd "C:\Users\harry\Documents\agent automation"
.venv312\Scripts\Activate.ps1
python main.py "https://lnkd.in/e-YBMMv7"
```

With live browser and slowmo:

```bash
python main.py "https://lnkd.in/e-YBMMv7" --headful --slowmo 50
```

Python 3.12 recommended (`.venv312`); dependencies in `requirements.txt`; `playwright install chromium` required.

---

## 11. Implementation Details (for reviewers)

**Updates from review (addressed):**
- **Step advance:** Only advance `expected_step` when we see `s >= expected_step + 1`; extended wait (20 polls). Fallback increment after no UI confirmation is logged.
- **Step regression:** If `page_step` is ≥3 behind `expected_step`, we reset `expected_step = page_step`.
- **Network cache:** No module-level state; `network_cache` dict is created in `run_challenge`, passed to `install_network_listener(page, cache)` and to `run_step`/`solve_one_step`. Listener is installed before `page.goto`.
- **Parallel extraction:** Storage, network (cache read), and DOM are run in parallel (`asyncio.create_task`); result is chosen by learned preference, then first valid.
- **Continue on error:** `--continue-on-error` continues to next step on failure instead of breaking.
- **Step detection:** Fallbacks for `[data-step]` and `[aria-label*="step"]` in `get_current_step`.
- **Correct option:** Semantic fallbacks `[data-correct='true']`, `[aria-selected='true']` in `handle_select_option_modal`.
- **Code input:** Negative selectors to exclude `type=search`, `name*="email"`, `name*="search"` in `CODE_INPUT_SELECTORS`.

- **Step progression:** `expected_step` (1..30) is the step we are solving. We never decrement it: if the page shows a higher step (e.g. 5), we set `expected_step = page_step`; if the page shows a lower step, we ignore it and keep solving `expected_step`. After a successful submit we poll “Step X of 30” for up to ~1.5s; if we see `s >= expected_step + 1` we set `expected_step = s`, else we increment `expected_step` once.
- **Retries:** `solve_one_step` runs `run_step` up to `max_retries_per_step` (default 3). Between retries it calls `normalize_ui` and `close_popup_windows`. No backoff; short fixed wait (200 ms) between attempts.
- **Network cache:** `_network_codes` in `extractors.py` is a module-level dict filled by the response listener. It is cleared at the start of each run (`clear_network_codes_cache()` before `install_network_listener`). All JSON response bodies are parsed and scanned with `_parse_json_for_codes` (step-indexed dicts or arrays of length 30).
- **Learned method:** Only `dom`, `localStorage`, and `network` are persisted. If `learned.json` has an invalid or unknown method for a step, that step falls back to the default order (localStorage → network → dom).
- **Failure behavior:** On first step failure we append the failed `StepResult`, take a screenshot `fail_step_XX.png`, log storage keys and visible buttons to `debug.log`, then **break** out of the main loop (run ends). We do not continue to the next step after a failure.
- **Resource blocking:** Implemented in runner via `context.route("**/*", block_route)`; `block_route` aborts when `resource_type in ("image", "media", "font")`. Disabled with `--no-block-resources`.
- **Submission zip:** Built from the repo root; excludes dirs containing `.venv`, `__pycache__`, `node_modules`, `.git`; excludes `submission.zip` itself; explicitly adds `out/results.json` and `out/debug.log` if present. No videos or traces in the zip.

---

## 12. Known Gotchas / Past Fixes

- **Python / greenlet:** Use Python 3.10–3.12. A venv created with Python 3.14 can cause `ModuleNotFoundError: greenlet._greenlet`; recreate the venv with 3.12 and reinstall.
- **Landing vs Step 1:** If after load the page has no “Step X of 30”, we assume landing and click START (multiple selectors tried). Then we wait for “ready” (step number or any visible input) before reading `expected_step`.
- **Select-option modal order:** `handle_select_option_modal` is called **before** `normalize_ui` in `run_step` so we don’t close the modal with ESC before selecting the correct option.
- **Topmost popup:** In-page dialogs are closed from topmost first (`dialogs.nth(n - 1)`) so nested modals (e.g. newsletter then “you won”) are peeled in the right order.

---

## 13. File and Key Symbols Quick Reference

| Path | Key items |
|------|-----------|
| `main.py` | `main()`, argparse, `run_challenge`, `write_results`, `create_submission_zip`, `TARGET_STEPS=30`, `MAX_ITERATIONS=5` |
| `agent/runner.py` | `run_challenge`, `run_step`, `solve_one_step`, `get_current_step`, `try_click_start`, `wait_for_ready_state`, `setup_debug_log` |
| `agent/actions.py` | `normalize_ui`, `_close_topmost_foreground_popup`, `_close_overlays_one_round`, `close_popup_windows`, `handle_select_option_modal`, `find_and_fill_code_input`, `scroll_to_bottom_and_back` |
| `agent/extractors.py` | `extract_codes_from_dom`, `get_challenge_code_for_step_from_storage`, `extract_codes_from_storage`, `extract_code_from_input_value`, `install_network_listener`, `get_network_codes_cache`, `clear_network_codes_cache`, `_parse_json_for_codes` |
| `agent/site.py` | `STEP_PATTERN`, `parse_step_from_page`, `CODE_INPUT_SELECTORS`, `SUBMIT_BUTTON_SELECTORS`, `CLOSE_BUTTON_TEXTS`, `MODAL_SELECTORS`, `code_like_token` |
| `agent/learning.py` | `load_learned`, `save_learned`, `LEARNED_FILENAME="learned.json"` |
| `agent/metrics.py` | `StepResult`, `RunStats`, `write_results` |

---

End of system note.
