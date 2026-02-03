# Handoff Note for Claude – Browser Navigation Challenge Agent

**Purpose:** Give this note (and the codebase) to Claude so it can diagnose and fix issues. The agent often fails to get past **step 5** (and sometimes step 4); goal is to complete all **30 steps in under 5 minutes**.

---

## 1. Goal and Challenge

- **Challenge:** [Browser Navigation Challenge](https://serene-frangipane-7fd25b.netlify.app/) – 30 steps; each step requires entering a **6+ character code** (never hardcoded) and submitting to advance.
- **Target:** Complete all 30 steps in **under 5 minutes**.
- **Stack:** Python 3.12, Playwright (async), optional OpenAI LLM fallback when deterministic extraction fails.
- **Challenge URL (current default):** `https://serene-frangipane-7fd25b.netlify.app/`

---

## 2. Project Structure

```
agent automation/
├── main.py              # CLI: iterations, timeout, writes out/run_<timestamp>/
├── run_overnight.py     # Loops main.py until 30 steps in <5 min or 8h
├── start_overnight.py   # Kills existing overnight, starts new detached
├── agent/
│   ├── runner.py       # Main loop: navigate, solve steps 1–30, advance detection
│   ├── actions.py      # normalize_ui, handle_select_option_modal, find_and_fill_code_input
│   ├── extractors.py   # DOM/storage/network code extraction, decoy filtering
│   ├── site.py         # Selectors: Step X of 30, code input, submit/close buttons
│   ├── learning.py     # load_learned / save_learned (method per step → out/learned.json)
│   ├── metrics.py      # StepResult, RunStats, write_results
│   └── llm_fallback.py # Optional OpenAI fallback when no code found
├── scripts/check_overnight_status.py
├── out/                # Per-run: out/run_<timestamp>/{results_iter_*.json, debug.log, fail_step_*.png}
├── SYSTEM_NOTE.md      # Full design and assumptions
└── OVERNIGHT_MONITORING.md
```

---

## 3. High-Level Flow (per step)

1. **Normalize UI:** Close Cookie Consent, then topmost popups (newsletter, “Important Note”, etc.), then ESC + Close/Dismiss. Do **not** close the “Please Select an Option” modal (that’s content).
2. **Handle “Please Select an Option” modal:** Find modal by title, scroll it, select correct option (e.g. “Option B - Correct Choice”), click **Submit inside the modal only** (not a background “Submit Code”).
3. **Get code:** In parallel try: (a) `localStorage` key `challenge_code_step_{step}`, (b) network cache (JSON responses), (c) DOM (reveal clicks, data-* attributes, body tokens). Pick first **valid** code by learned preference; **reject decoys** (e.g. “Scroll”, “Submit”, “button”).
4. **Fill code input and submit:** Find input (placeholder/name/id containing “code”), fill, submit via Enter or “Submit Code” button. Prefer the **code-entry section** (container with “Enter Code to Proceed” + “Submit Code”) so we don’t click a decoy.
5. **Advance detection:** Poll page for “Step X of 30”; if we see `step >= expected_step + 1`, we advanced. If still on same step → “submit did not advance” (wrong code or wrong button); for steps 1–5 we **retry once** (normalize + extract + submit again).

---

## 4. Known Issues and Failure Modes

### 4.1 Step 5 (and sometimes step 4) – “submit did not advance”

- **Symptom:** Agent submits a code but the page stays on the same step. In results: `"ok": false`, `"notes": "submit did not advance"`, `"code_redacted": "Sc****ll"` (i.e. **“Scroll”**).
- **Cause:** The challenge page has **decoy text** (e.g. “Scroll”, “This is a popup message. Click X to close.”). The agent was picking “Scroll” as the step code from visible text or pre-filled input. Decoys are now filtered in **DOM body** extraction (`DECOY_WORDS` in `extractors.py`) and we added **`is_valid_step_code()`** so that **storage, network, and pre-filled input** are also filtered in `runner.run_step`. If all sources return decoys, we get “no code found” instead of submitting a decoy.
- **Step 5 UI (from fail screenshot):** Multiple overlays: “Subscribe to our newsletter!” (top), “Important Note” (“This is a popup m fake! Look for anc…”), “Please Select an Option” (options + Submit). Bottom: “Enter Code to Proceed to Step 6” + input + “Submit Code”. The agent must close **topmost popups first**, then handle Select Option modal, then **extract the real code** (not “Scroll”) and submit via the **code input + Submit Code** in the main page.

### 4.2 Popups and modal order

- **Cookie Consent** often blocks all clicks; we close it first by finding the overlay and clicking Accept/Close **inside** it.
- **“Wrong Button!”** appears if we click a decoy Submit; we detect and dismiss it, then retry.
- **“The close button is fake!”** – we only click Dismiss (not X/Close) for that popup.
- **“Please Select an Option”** is **not** closed by normalize_ui; we handle it with `handle_select_option_modal` (scroll modal, select correct option, Submit **inside** modal).

### 4.3 Submit button vs decoys

- We must submit the **step code** via the **code input** and the **“Submit Code”** (or Proceed) button in the **code-entry section** (the block with “Enter Code to Proceed to Step N+1”). Clicking a generic “Submit” inside “Please Select an Option” is correct for that modal; clicking a **background** “Submit” or “Submit Code” before entering the code can cause “Wrong Button!” or no advance. See `actions.py`: `_code_entry_section_locator` and `find_and_fill_code_input` prefer the code-entry section.

### 4.4 Extraction order and learning

- **Order:** By default we try localStorage → network → dom. If `out/learned.json` has a method for a step (e.g. `dom`), we try that first. No codes are hardcoded; all from DOM / storage / network.
- **Learning:** Successful steps write the method that worked to `out/learned.json` (shared across runs). If step 5 keeps failing, learning won’t help until we fix extraction/decoy/popup logic.

---

## 5. Key Code Locations

| What | Where |
|------|--------|
| Step loop, advance detection, retry on “submit did not advance” | `agent/runner.py`: `run_challenge` (main while expected_step <= 30), block after “submit”, retry for steps 1–5 |
| Code choice (storage/network/dom + decoy filter) | `agent/runner.py`: `run_step` – `is_valid_step_code(cand)` for each source |
| DOM extraction, decoy list, `is_valid_step_code` | `agent/extractors.py`: `DECOY_WORDS`, `_is_unit_like_or_decoy`, `is_valid_step_code`, `extract_codes_from_dom` |
| Pre-filled input (must pass decoy check in _try_dom) | `agent/runner.py`: `_try_dom` – only return `extract_code_from_input_value` if `is_valid_step_code(code)` |
| Popups: Cookie Consent, topmost, “fake close”, Select Option | `agent/actions.py`: `_close_cookie_consent`, `_close_topmost_foreground_popup`, `normalize_ui`, `handle_select_option_modal` |
| Code input + submit (prefer code-entry section) | `agent/actions.py`: `find_and_fill_code_input`, `_code_entry_section_locator` |
| Step detection | `agent/site.py`: `STEP_PATTERN` (“Step X of 30”), `agent/runner.py`: `get_current_step` |

---

## 6. Recent Fixes Already Applied

- **Decoy filtering for all sources:** Storage, network, and DOM (including pre-filled input) are filtered with `is_valid_step_code()` in `run_step` and `_try_dom`; “Scroll” and other `DECOY_WORDS` are rejected.
- **Retry for step 5:** “Submit did not advance” retry extended from steps 1–3 to **steps 1–5** in `runner.py`.
- **Default URL** set to `https://serene-frangipane-7fd25b.netlify.app/` in `main.py` and `run_overnight.py`.

---

## 7. Sample Failure Data

**Typical result when failing at step 5:**

```json
{
  "url": "https://lnkd.in/e-YBMMv7",
  "solved_count": 4,
  "attempted_count": 5,
  "steps": [
    {"step": 1, "ok": true, "method": "dom", "notes": "code_len=6", "code_redacted": "75****ST"},
    {"step": 2, "ok": true, "method": "dom", "notes": "code_len=6", "code_redacted": "KT****ZP"},
    {"step": 3, "ok": true, "method": "dom", "notes": "code_len=6", "code_redacted": "PR****FF"},
    {"step": 4, "ok": true, "method": "dom", "notes": "code_len=6", "code_redacted": "Y6****NQ"},
    {"step": 5, "ok": false, "method": "dom", "notes": "submit did not advance", "code_redacted": "Sc****ll"}
  ]
}
```

So steps 1–4 often succeed; step 5 fails with a decoy code “Scroll” (redacted as `Sc****ll`). After the fixes above, if extraction only finds decoys we should see “no code found” for step 5 instead of submitting “Scroll”; the remaining issue may be **where the real code is** (e.g. hidden in DOM, behind popups, or in storage only after correct interaction).

---

## 8. How to Run and Verify

```powershell
cd "C:\Users\harry\Documents\agent automation"
.venv312\Scripts\python main.py
```

- **Single run (no loop):** `main.py --no-run-until-30`
- **With browser visible:** `main.py --headful`
- **Overnight loop:** `run_overnight.py` or `start_overnight.py`

**Output:** `out/run_<timestamp>/` – `results_iter_*.json`, `results.json`, `debug.log`, `live_status.md`, `fail_step_*.png` on failure.

**Check status:** `python scripts/check_overnight_status.py` or read `out/overnight.log` and `out/last_error.txt`.

---

## 9. What to Fix / Questions for Claude

1. **Step 5 (and 4) reliability:** After rejecting “Scroll”, does the agent find the **real** code for step 5? If not, where might the challenge expose it (DOM structure, storage after a specific action, network)? Should we scroll or focus the code-entry section before extracting?
2. **Popup ordering on step 5:** Are we closing “Subscribe to our newsletter!” and “Important Note” before reading the code input / DOM? Is the code visible only after closing the right overlay?
3. **Submit target:** Are we always submitting via the **code input + “Submit Code”** in the section that says “Enter Code to Proceed to Step 6”, and never accidentally clicking a modal Submit or a decoy?
4. **Extraction robustness:** For steps where the code is in the DOM (e.g. in a section that’s scrolled into view or revealed), is our selector order and decoy filter missing valid codes (e.g. codes that look like words but aren’t in DECOY_WORDS)?
5. **Timing and fast mode:** With `timeout_minutes=5` we use “fast mode” (shorter waits). Could step 5 need a longer wait after closing popups before extracting (e.g. for dynamic content)?
6. **Learning:** Should we avoid learning “dom” for step 5 if it previously submitted a decoy, or add step-level “last failed code” to avoid retrying the same wrong code?

Use **SYSTEM_NOTE.md** for full architecture and assumptions; **OVERNIGHT_MONITORING.md** for run monitoring. Inspect **out/run_\<latest\>/debug.log** and **fail_step_05.png** (if present) for concrete failure context.
