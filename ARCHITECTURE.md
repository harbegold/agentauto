# Architecture – Browser Navigation Challenge Agent

**Summary:** AI agent with **multi-provider LLM support**, **DOM parsing**, and **retry logic**. Built for execution excellence on the 30-step browser challenge in under 5 minutes.

---

## High-level design

| Layer | Role |
|-------|------|
| **CLI** (`main.py`) | URL, headful/video/trace, timeout, iterations; chooses LLM provider and resolves API key from env. |
| **Runner** (`agent/runner.py`) | Single run: launch browser, navigate, loop steps 1–30; normalize UI → extract code → submit → advance; optional LLM fallback when a step fails. |
| **Actions** (`agent/actions.py`) | Popups (cookie, newsletter, wrong button, fake close), Select Option modal, code input locate/fill/submit. |
| **Extractors** (`agent/extractors.py`) | Code sources: DOM (reveal clicks, data-*, body tokens, code-entry section), localStorage/sessionStorage, network listener; decoy filtering. |
| **LLM** (`agent/llm_fallback.py` + `agent/llm_providers.py`) | When stuck: gather page context, ask LLM for a short JSON action plan, execute with Playwright. **Multi-provider:** OpenAI or Anthropic. |
| **Learning** (`agent/learning.py`) | Persist which method worked per step (dom / localStorage / network) across runs. |
| **Metrics** (`agent/metrics.py`) | Step results, run stats, token usage/cost, write `results.json`. |

No step codes are hardcoded; codes come only from DOM, storage, network, or LLM-driven actions.

---

## Multi-provider LLM support

- **Providers:** `openai`, `anthropic`.
- **Env vars:** `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`.
- **Usage:** `--use-llm --llm-provider openai` or `--llm-provider anthropic`. Model is set with `--model` (e.g. `gpt-4o-mini`, `claude-3-5-haiku-20241022`).
- **Cost:** `llm_providers.estimate_cost_usd(provider, model, prompt_tokens, completion_tokens)` for rough USD; reported in run stats.

---

## DOM parsing and code extraction

- **Order:** Learned method first, then localStorage → network → DOM. Within DOM: input value (if valid) → scroll/reveal → data-* / aria → body tokens; retry uses code-entry section and full normalize.
- **Decoys:** `DECOY_WORDS` and `is_valid_step_code()` filter button/label/popup text (e.g. Scroll, Escape, Subscribe) so they are never submitted as codes.
- **Code-entry section:** `extract_code_from_code_section()` looks for codes in the “Enter Code to Proceed” block (data attributes, spans/labels near the input).

---

## Retry logic

- **Per-step:** `solve_one_step` runs `run_step` up to `max_retries_per_step` (default 3); between retries: normalize_ui, close popup windows.
- **Submit did not advance:** For steps 1–5, if the page does not advance after submit, we retry the step once (normalize + extract + submit again).
- **No code found:** If first extraction finds no valid code, we run extra popup handling, then retry localStorage, code-entry section, and full DOM extraction.

---

## Research-backed methods (for speed and reliability)

- **State-based verification:** After submit, we use `page.wait_for_function()` to wait until the DOM shows "Step N of 30" with N ≥ expected+1, instead of only fixed polling. Proceed as soon as the page updates (Playwright best practice: avoid hard waits).
- **Exponential backoff with jitter:** Retries use `_retry_backoff_ms(attempt)` (base 60ms, cap 500ms, plus jitter) so we don’t hammer the page and avoid thundering herd (AWS/Google pattern).
- **Retry on “submit did not advance” for all steps:** Any step can retry once with backoff before failing; no longer limited to steps 1–5.
- **Turbo fast mode:** When `timeout_minutes <= 5`, all step and advance waits are reduced (post_submit 50ms, advance poll 35ms, step waits 15–20ms), and `fast_mode` is passed into `run_step` / `solve_one_step` for shorter internal delays.
- **Event-driven advance:** Primary check is `_wait_for_step_advance(page, min_step, timeout)`; polling is fallback only if that times out.

---

## Execution flow (one step)

1. Normalize UI (cookie → newsletter → wrong button → topmost popups).
2. Handle “Please Select an Option” modal (scroll, select correct option, Submit inside modal).
3. Parallel extraction: storage, network, DOM (with `skip_normalize=True` to avoid interference).
4. Pick first valid code by learned preference; reject decoys.
5. If no code: extra normalize, then retry storage / code-entry section / DOM.
6. Fill code input and submit (code-entry section preferred).
7. Poll for step advance; if no advance and step in 1–5, retry step once.
8. If step still failed and `--use-llm`, call LLM for action plan, execute, then re-solve step.

---

## Files

| Path | Purpose |
|------|--------|
| `main.py` | CLI, iterations, LLM provider/key resolution, run_challenge args. |
| `agent/runner.py` | run_challenge, run_step, solve_one_step, advance detection, LLM fallback invocation. |
| `agent/actions.py` | normalize_ui, handle_select_option_modal, find_and_fill_code_input, popup helpers. |
| `agent/extractors.py` | DOM/storage/network extraction, decoy filter, extract_code_from_code_section. |
| `agent/llm_providers.py` | call_llm(provider, model, api_key, prompt), get_api_key_for_provider, estimate_cost_usd. |
| `agent/llm_fallback.py` | get_page_context, build_llm_prompt, parse_action_plan, execute_action_plan, ask_llm_for_plan. |
| `agent/site.py` | Step/input/submit/close selectors and patterns. |
| `agent/learning.py` | load_learned, save_learned. |
| `agent/metrics.py` | StepResult, RunStats, write_results. |
