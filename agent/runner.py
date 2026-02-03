"""Core loop across 30 steps: normalize UI, extract code (storage/network/DOM), submit, progress."""
import asyncio
import logging
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from playwright.async_api import Page, async_playwright

from .actions import (
    close_popup_windows,
    find_and_fill_code_input,
    get_visible_buttons_text,
    get_visible_inputs_count,
    handle_select_option_modal,
    normalize_ui,
    scroll_to_bottom_and_back,
)
from .extractors import (
    extract_code_from_input_value,
    extract_code_from_code_section,
    extract_codes_from_dom,
    extract_codes_from_storage,
    get_challenge_code_for_step_from_storage,
    get_network_codes,
    clear_network_codes_cache,
    install_network_listener,
    get_storage_debug_info,
    is_valid_step_code,
)
from .learning import load_learned, save_learned
from .metrics import RunStats, StepResult, redact_code, write_results
from .site import parse_step_from_page

DEBUG_LOG: Optional[logging.Logger] = None
OUT_DIR: Path = Path("out")


def setup_debug_log(out_dir: Path) -> logging.Logger:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "debug.log"
    logger = logging.getLogger("agent")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")  # fresh log per run
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)
    try:
        from rich.logging import RichHandler
        sh = RichHandler(rich_tracebacks=True, show_path=False)
    except ImportError:
        sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    logger.addHandler(sh)
    return logger


def log_debug(msg: str, *args, **kwargs) -> None:
    if DEBUG_LOG:
        DEBUG_LOG.debug(msg, *args, **kwargs)


async def get_current_step(page: Page) -> Optional[int]:
    """Parse step from body text, then fallbacks: [data-step], [aria-label*='step']."""
    try:
        text = await page.evaluate("() => document.body.innerText")
        step = parse_step_from_page(text)
        if step is not None:
            return step
        # Fallbacks for dynamic/iframe/localized content
        step = await page.evaluate("""() => {
            const el = document.querySelector('[data-step]');
            if (el) { const n = parseInt(el.getAttribute('data-step'), 10); if (n >= 1 && n <= 30) return n; }
            const label = document.querySelector('[aria-label*="step" i], [aria-label*="Step" i]');
            if (label) {
                const m = (label.getAttribute('aria-label') || '').match(/\\d+/);
                if (m) { const n = parseInt(m[0], 10); if (n >= 1 && n <= 30) return n; }
            }
            return null;
        }""")
        return int(step) if step is not None and 1 <= step <= 30 else None
    except Exception:
        return None


async def try_click_start(page: Page, log_debug: Optional[Callable[..., None]] = None) -> None:
    """Click START once to enter the challenge from landing screen."""
    log = log_debug or (lambda msg, *a, **k: None)
    for start_locator in [
        page.get_by_text("START", exact=True),
        page.locator('button:has-text("START")').first,
        page.locator('a:has-text("START")').first,
        page.locator('[role="button"]:has-text("START")').first,
        page.locator("text=START").first,
    ]:
        try:
            if await start_locator.count() > 0:
                await start_locator.click(timeout=5000)
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                await page.wait_for_timeout(1200)
                log("Clicked START to enter challenge")
                return
        except Exception as e:
            log("START click attempt failed: %s", e)


async def wait_for_ready_state(
    page: Page,
    get_current_step_fn: Optional[Callable] = None,
    log_debug: Optional[Callable[..., None]] = None,
) -> None:
    """Wait until step number or code input is present."""
    get_step = get_current_step_fn or get_current_step
    for _ in range(15):
        if await get_step(page) is not None:
            return
        inp_count = await page.evaluate("() => document.querySelectorAll('input:not([type=hidden])').length")
        if inp_count > 0:
            return
        await page.wait_for_timeout(150)


async def _try_storage(
    page: Page, step: int, storage_codes: Optional[dict[int, str]], use_fast_path: bool
) -> tuple[Optional[str], str]:
    """Try storage extraction; returns (code, method) or (None, 'localStorage')."""
    code = await get_challenge_code_for_step_from_storage(page, step)
    if code:
        return code, "localStorage"
    if use_fast_path and storage_codes and step in storage_codes:
        return storage_codes.get(step), "localStorage"
    return None, "localStorage"


def _try_network_sync(step: int, network_cache: dict[int, str]) -> tuple[Optional[str], str]:
    """Sync read from network cache; returns (code, method) or (None, 'network')."""
    codes = get_network_codes(network_cache)
    if step in codes:
        return codes[step], "network"
    return None, "network"


async def _try_dom(page: Page, step: int, skip_normalize: bool = False) -> tuple[Optional[str], str]:
    """Try DOM extraction (input value then reveal + body); returns (code, method) or (None, 'dom')."""
    code = await extract_code_from_input_value(page)
    if code and is_valid_step_code(code):
        return code, "dom"
    await scroll_to_bottom_and_back(page)
    # Only normalize if not already done by caller (avoid interference during parallel extraction)
    if not skip_normalize:
        await normalize_ui(page)
    code = await extract_codes_from_dom(page)
    # Defense-in-depth: verify DOM-extracted code passes decoy filter
    if code and is_valid_step_code(code):
        return code, "dom"
    return None, "dom"


async def run_step(
    page: Page,
    step: int,
    storage_codes: Optional[dict[int, str]],
    use_fast_path: bool,
    learned_method: Optional[str] = None,
    network_cache: Optional[dict[int, str]] = None,
) -> tuple[bool, float, str, str, Optional[str]]:
    """
    Run one step: get code (parallel extraction, then pick by learned preference), fill and submit.
    Returns (ok, seconds, method, notes, code_used).
    """
    start = time.perf_counter()
    method = "dom"
    notes = ""
    cache = network_cache if network_cache is not None else {}
    code_used: Optional[str] = None

    # 1) Close promotional popups first so Select Option modal is reachable
    await normalize_ui(page, rounds=2 if step == 1 else 1)
    await page.wait_for_timeout(40 if step == 1 else 25)

    # 2) Handle "Please Select an Option" modal (scroll, pick correct option, Submit inside modal only)
    await handle_select_option_modal(page)
    await page.wait_for_timeout(25)

    # 3) Dismiss "Wrong Button!" if it appeared, then retry modal submit if still open
    await normalize_ui(page, rounds=1)
    await page.wait_for_timeout(25)
    await handle_select_option_modal(page)
    await page.wait_for_timeout(25)

    # 4) Parallel extraction: storage (async), network (sync from cache), DOM (async)
    # Skip normalize in _try_dom since we already did popup handling above
    storage_future = asyncio.create_task(_try_storage(page, step, storage_codes, use_fast_path))
    dom_future = asyncio.create_task(_try_dom(page, step, skip_normalize=True))
    storage_result = await storage_future
    dom_result = await dom_future
    network_result = _try_network_sync(step, cache)

    # Pick first valid by learned preference; reject decoys (e.g. "Scroll") from any source
    try_first = learned_method or "localStorage"
    order = (
        ["localStorage", "network", "dom"]
        if try_first == "localStorage"
        else (["network", "localStorage", "dom"] if try_first == "network" else ["dom", "localStorage", "network"])
    )
    code: Optional[str] = None
    for src in order:
        cand = None
        if src == "localStorage" and storage_result[0]:
            cand, method = storage_result[0], storage_result[1]
        elif src == "network" and network_result[0]:
            cand, method = network_result[0], network_result[1]
        elif src == "dom" and dom_result[0]:
            cand, method = dom_result[0], dom_result[1]
        if cand and is_valid_step_code(cand):
            code = cand
            break
    if not code:
        # Fallback: take any non-None result that passes decoy filter
        for result in (storage_result, network_result, dom_result):
            if result[0] and is_valid_step_code(result[0]):
                code, method = result[0], result[1]
                break

    # 4b) Retry extraction if no code found - code may appear after modal interactions
    if not code:
        log_debug("Step %d: first extraction found no valid code, retrying after additional popup handling", step)
        # Additional cleanup: ensure all popups are closed
        await normalize_ui(page, rounds=2)
        await page.wait_for_timeout(50)
        # Re-check localStorage directly for this step's key (may have been set by modal submit)
        direct_storage_code = await get_challenge_code_for_step_from_storage(page, step)
        if direct_storage_code and is_valid_step_code(direct_storage_code):
            code = direct_storage_code
            method = "localStorage"
            log_debug("Step %d: retry found code in localStorage", step)
        else:
            # Try the code-entry section specifically
            code_section_code = await extract_code_from_code_section(page)
            if code_section_code and is_valid_step_code(code_section_code):
                code = code_section_code
                method = "dom"
                log_debug("Step %d: retry found code in code-entry section", step)
            else:
                # Re-try DOM extraction with full normalization
                retry_dom = await _try_dom(page, step, skip_normalize=False)
                if retry_dom[0] and is_valid_step_code(retry_dom[0]):
                    code = retry_dom[0]
                    method = retry_dom[1]
                    log_debug("Step %d: retry found code in DOM", step)

    if not code:
        elapsed = time.perf_counter() - start
        return False, elapsed, method, "no code found", None
    code_used = code

    # 5) Select correct option if step requires it (e.g. radio "Option B - Correct Choice")
    try:
        correct = page.locator('input[type="radio"]').filter(has_text="Correct").first
        if await correct.count() > 0:
            await correct.click(timeout=2000)
            await page.wait_for_timeout(50)
    except Exception:
        pass
    try:
        correct = page.locator('label:has-text("Correct"), input[value*="correct" i]').first
        if await correct.count() > 0:
            await correct.click(timeout=2000)
            await page.wait_for_timeout(50)
    except Exception:
        pass

    # 6) Fill code input and submit
    filled = await find_and_fill_code_input(page, code)
    elapsed = time.perf_counter() - start
    if not filled:
        return False, elapsed, method, "fill/submit failed", code_used
    notes = f"code_len={len(code)}"
    return True, elapsed, method, notes, code_used


async def solve_one_step(
    page: Page,
    step: int,
    storage_codes: Optional[dict[int, str]],
    use_fast_path: bool,
    max_retries: int,
    context: Optional[Any] = None,
    learned_method: Optional[str] = None,
    network_cache: Optional[dict[int, str]] = None,
) -> tuple[bool, float, str, str, Optional[str]]:
    """
    Solve one step with retries. Returns (ok, seconds, method, notes, code_used).
    If learned_method is set, try that method first for getting the code.
    """
    step_start = time.perf_counter()
    method = "dom"
    notes = ""
    last_code: Optional[str] = None
    cache = network_cache if network_cache is not None else {}
    for attempt in range(max_retries):
        if attempt > 0:
            await normalize_ui(page)
            if context is not None:
                await close_popup_windows(context, page)
        ok, elapsed, method, notes, code_used = await run_step(
            page, step, storage_codes, use_fast_path, learned_method=learned_method, network_cache=cache
        )
        if code_used is not None:
            last_code = code_used
        log_debug(
            "Step %d attempt %d: ok=%s method=%s time=%.2fs notes=%s",
            step, attempt + 1, ok, method, elapsed, notes,
        )
        if ok:
            return True, elapsed, method, notes, code_used
        await page.wait_for_timeout(200)
    return False, time.perf_counter() - step_start, method, notes, last_code


async def _diagnostic_screenshot_loop(page: Page, diagnostic_dir: Path, duration_sec: int = 60, interval_sec: float = 1.0) -> None:
    """Take a screenshot every interval_sec for duration_sec; filenames include index and UTC timestamp."""
    for i in range(duration_sec):
        try:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
            path = diagnostic_dir / f"diagnostic_{i + 1:03d}_{ts}.png"
            await page.screenshot(path=path)
            log_debug("Diagnostic screenshot %d/%d: %s", i + 1, duration_sec, path.name)
        except Exception as e:
            log_debug("Diagnostic screenshot %d failed: %s", i + 1, e)
        await asyncio.sleep(interval_sec)


def _write_live_status(path: Path, iteration: int, step_reached: int, extra: str = "") -> None:
    """Write live status file for user to watch: 'Iteration N: got to step X'."""
    try:
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Live Run Status\n\n")
            f.write(f"**Iteration {iteration}:** got to step **{step_reached}**\n\n")
            if extra:
                f.write(f"{extra}\n\n")
            f.write(f"*Updated: {ts}*\n")
    except Exception as e:
        log_debug("live_status write failed: %s", e)


async def run_challenge(
    url: str,
    out_dir: Path,
    headless: bool = True,
    slow_mo: Optional[int] = None,
    video: bool = True,
    trace: bool = False,
    timeout_minutes: int = 10,
    resource_blocking: bool = True,
    max_retries_per_step: int = 3,
    continue_on_error: bool = False,
    diagnostic_screenshots: bool = False,
    use_llm: bool = False,
    max_llm_calls: int = 10,
    llm_model: str = "gpt-4o-mini",
    openai_api_key: Optional[str] = None,
    live_status_path: Optional[Path] = None,
    iteration: Optional[int] = None,
    shared_learned_dir: Optional[Path] = None,
) -> RunStats:
    """Run full 30-step challenge; return RunStats."""
    global DEBUG_LOG
    DEBUG_LOG = setup_debug_log(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "videos").mkdir(parents=True, exist_ok=True)
    (out_dir / "traces").mkdir(parents=True, exist_ok=True)

    fast_mode = timeout_minutes <= 5
    # ~2x speed: shorter waits so we can finish 30 steps in under 5 min
    post_submit_wait_ms = 100 if fast_mode else 300
    advance_poll_count = 20 if fast_mode else 50
    advance_poll_ms = 50 if fast_mode else 150

    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    step_results: list[StepResult] = []
    attempted = 0
    solved = 0
    token_usage_accum: dict[str, int] = {}
    token_cost_usd_accum: float = 0.0

    if live_status_path is not None and iteration is not None:
        _write_live_status(live_status_path, iteration, 0, "Started.")
    run_start = time.perf_counter()
    run_end: Optional[float] = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            slow_mo=slow_mo,
        )

        # Block images/fonts/media if requested
        async def block_route(route):
            req = route.request
            if resource_blocking and req.resource_type in ("image", "media", "font"):
                await route.abort()
            else:
                await route.continue_()

        video_dir = str(out_dir / "videos") if video else None
        context = await browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1280, "height": 720},
            record_video_dir=video_dir,
            record_video_size={"width": 1280, "height": 720} if video else None,
        )
        if resource_blocking:
            await context.route("**/*", block_route)

        if trace:
            await context.tracing.start(screenshots=True, snapshots=True, sources=True)

        page = await context.new_page()

        # Network listener before any navigation so we capture preloaded / redirect responses
        network_cache: dict[int, str] = {}
        clear_network_codes_cache(network_cache)
        await install_network_listener(page, network_cache)

        screenshot_task: Optional[asyncio.Task[None]] = None
        try:
            log_debug("Navigating to %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(600 if fast_mode else 1200)

            # Clear Cookie Consent and other overlays first (they block all clicks)
            await normalize_ui(page, rounds=2)
            await page.wait_for_timeout(100 if fast_mode else 200)

            # Initial START if on landing
            current_after_load = await get_current_step(page)
            if current_after_load is None:
                await try_click_start(page, log_debug)
                await normalize_ui(page)
                await close_popup_windows(context, page)
                await wait_for_ready_state(page, get_current_step, log_debug)

            # Check for storage-based codes (fast path)
            storage_codes = await extract_codes_from_storage(page)
            # Use storage for any step we have a code for (e.g. challenge_code_step_2..30 in localStorage)
            use_fast_path = bool(storage_codes)
            if storage_codes:
                log_debug("Storage codes keys (count): %s", list(storage_codes.keys())[:50])

            current = await get_current_step(page)
            log_debug("Initial step detected: %s", current)

            learned = load_learned(out_dir, shared_dir=shared_learned_dir)
            if learned:
                log_debug("Loaded learned methods for steps: %s", list(learned.keys())[:10])

            if diagnostic_screenshots:
                run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
                diagnostic_dir = out_dir / "diagnostic" / f"run_{run_ts}"
                diagnostic_dir.mkdir(parents=True, exist_ok=True)
                screenshot_task = asyncio.create_task(
                    _diagnostic_screenshot_loop(page, diagnostic_dir, duration_sec=60, interval_sec=1.0)
                )
                log_debug("Diagnostic screenshots: every 1s for 60s -> %s", diagnostic_dir)

            llm_calls_used = 0
            expected_step = 1
            while expected_step <= 30:
                await close_popup_windows(context, page)

                page_step = await get_current_step(page)

                # If we're on a landing screen (no step), try START once
                if page_step is None:
                    await try_click_start(page, log_debug)
                    await normalize_ui(page)
                    await wait_for_ready_state(page, get_current_step, log_debug)
                    page_step = await get_current_step(page)

                # If the site reports a step: fast-forward if ahead; reset if regressed (e.g. session timeout)
                if page_step is not None:
                    if page_step < expected_step:
                        if expected_step - page_step >= 3:
                            log_debug("Step regression: page_step=%s expected=%s; resetting expected_step", page_step, expected_step)
                            expected_step = page_step
                        else:
                            log_debug("Page step %s behind expected %s; ignoring", page_step, expected_step)
                    elif page_step > expected_step:
                        log_debug("Page step %s ahead of expected %s; fast-forwarding", page_step, expected_step)
                        expected_step = page_step

                # ---- Step 1 debug: screenshot and log (skip in fast_mode to save time) ----
                if expected_step == 1 and not fast_mode:
                    try:
                        await page.screenshot(path=out_dir / "step1_before_anything.png")
                        body_snippet = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 500)")
                        storage_info = await get_storage_debug_info(page)
                        inputs_count = await get_visible_inputs_count(page)
                        log_debug("Step 1 debug: body (first 500 chars): %s", body_snippet)
                        log_debug("Step 1 debug: localStorage keys=%s sessionStorage keys=%s visible_inputs=%s",
                                  list(storage_info.get("localStorage", {}).keys()),
                                  list(storage_info.get("sessionStorage", {}).keys()),
                                  inputs_count)
                    except Exception as e:
                        log_debug("Step 1 debug capture failed: %s", e)

                # ---- Solve the currently expected step (deterministic-first; LLM fallback if enabled) ----
                attempted += 1
                ok, elapsed, method, notes, code_used = await solve_one_step(
                    page, expected_step, storage_codes, use_fast_path, max_retries_per_step, context,
                    learned_method=learned.get(expected_step),
                    network_cache=network_cache,
                )

                # Optional LLM fallback when deterministic failed and we have budget
                if not ok and use_llm and openai_api_key and llm_calls_used < max_llm_calls:
                    try:
                        from .llm_fallback import get_page_context, ask_llm_for_plan, execute_action_plan, estimate_cost_usd
                        context_dict = await get_page_context(page, step=expected_step)
                        plan, usage = await ask_llm_for_plan(context_dict, llm_model, openai_api_key)
                        if usage:
                            token_usage_accum["prompt_tokens"] = token_usage_accum.get("prompt_tokens", 0) + usage.get("prompt_tokens", 0)
                            token_usage_accum["completion_tokens"] = token_usage_accum.get("completion_tokens", 0) + usage.get("completion_tokens", 0)
                            token_usage_accum["total_tokens"] = token_usage_accum.get("total_tokens", 0) + usage.get("total_tokens", 0)
                            token_cost_usd_accum += estimate_cost_usd(llm_model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                        if plan:
                            llm_calls_used += 1
                            await execute_action_plan(page, plan)
                            await page.wait_for_timeout(250)
                            ok, elapsed, method, notes, code_used = await solve_one_step(
                                page, expected_step, storage_codes, use_fast_path, max_retries_per_step, context,
                                learned_method=learned.get(expected_step),
                                network_cache=network_cache,
                            )
                            if ok:
                                method = "llm"
                    except Exception as e:
                        log_debug("LLM fallback error: %s", e)

                if not ok:
                    step_results.append(StepResult(
                        step=expected_step, ok=False, seconds=elapsed, method=method, notes=notes,
                        code_redacted=redact_code(code_used) if code_used else None,
                    ))
                    try:
                        await page.screenshot(path=out_dir / f"fail_step_{expected_step:02d}.png")
                    except Exception:
                        pass
                    try:
                        storage_info = await get_storage_debug_info(page)
                        buttons = await get_visible_buttons_text(page, 30)
                        inputs_count = await get_visible_inputs_count(page)
                        log_debug("FAIL step %d: storage_keys=%s visible_buttons_count=%s inputs_count=%s",
                                  expected_step,
                                  list(storage_info.get("localStorage", {}).keys()) + list(storage_info.get("sessionStorage", {}).keys()),
                                  len(buttons), inputs_count)
                        log_debug("Visible buttons (first 30): %s", buttons[:30])
                    except Exception as e:
                        log_debug("Debug dump error: %s", traceback.format_exc())
                    if continue_on_error:
                        expected_step += 1
                        continue
                    break

                # ---- After submit, only advance when we have positive UI confirmation ----
                solved_step = expected_step  # step we just submitted
                await page.wait_for_timeout(post_submit_wait_ms)
                advanced = False
                for poll in range(advance_poll_count):
                    await page.wait_for_timeout(advance_poll_ms)
                    s = await get_current_step(page)
                    if s is not None and s >= expected_step + 1:
                        expected_step = s
                        advanced = True
                        break
                if advanced:
                    solved += 1
                    step_results.append(StepResult(
                        step=solved_step, ok=True, seconds=elapsed, method=method, notes=notes,
                        code_redacted=redact_code(code_used) if code_used else None,
                    ))
                    if live_status_path is not None and iteration is not None:
                        _write_live_status(live_status_path, iteration, solved)
                else:
                    s_final = await get_current_step(page)
                    # Page still on same step = submit did not advance (wrong code or wrong button)
                    if s_final == solved_step:
                        # Steps 1–5: retry once (reveal + extract + submit again) before failing
                        if solved_step in (1, 2, 3, 4, 5):
                            log_debug("Step %d: submit did not advance; retrying step %d once", solved_step, solved_step)
                            await page.wait_for_timeout(250)
                            ok_retry, elapsed_retry, method_retry, notes_retry, code_retry = await solve_one_step(
                                page, solved_step, storage_codes, use_fast_path, max_retries_per_step, context,
                                learned_method=learned.get(solved_step),
                                network_cache=network_cache,
                            )
                            retry_advanced = False
                            if ok_retry:
                                await page.wait_for_timeout(post_submit_wait_ms)
                                for _ in range(advance_poll_count):
                                    await page.wait_for_timeout(advance_poll_ms)
                                    s = await get_current_step(page)
                                    if s is not None and s >= solved_step + 1:
                                        expected_step = s
                                        solved += 1
                                        step_results.append(StepResult(step=solved_step, ok=True, seconds=elapsed_retry, method=method_retry, notes=notes_retry, code_redacted=redact_code(code_retry) if code_retry else None))
                                        if live_status_path is not None and iteration is not None:
                                            _write_live_status(live_status_path, iteration, solved)
                                        retry_advanced = True
                                        break
                                else:
                                    s_final = await get_current_step(page)
                                    if s_final is not None and s_final != solved_step:
                                        expected_step = s_final
                                        solved += 1
                                        step_results.append(StepResult(step=solved_step, ok=True, seconds=elapsed_retry, method=method_retry, notes=notes_retry, code_redacted=redact_code(code_retry) if code_retry else None))
                                        if live_status_path is not None and iteration is not None:
                                            _write_live_status(live_status_path, iteration, solved)
                                        retry_advanced = True
                                    else:
                                        log_debug("Step %d retry: submit still did not advance; treating as failure", solved_step)
                            if retry_advanced:
                                continue
                        if s_final == solved_step:
                            log_debug("Step %d: submit did not advance page (still on step %d); treating as failure", solved_step, s_final)
                            step_results.append(StepResult(step=solved_step, ok=False, seconds=elapsed, method=method, notes="submit did not advance", code_redacted=redact_code(code_used) if code_used else None))
                            try:
                                await page.screenshot(path=out_dir / f"fail_step_{solved_step:02d}.png")
                            except Exception:
                                pass
                            if continue_on_error:
                                expected_step += 1
                                continue
                            break
                        continue
                    # Page step unclear (None or other); infer advance and count as success
                    log_debug("Step advance not confirmed after 6s for step %d (page_step=%s); inferring advance", solved_step, s_final)
                    expected_step += 1
                    solved += 1
                    step_results.append(StepResult(step=solved_step, ok=True, seconds=elapsed, method=method, notes=notes, code_redacted=redact_code(code_used) if code_used else None))
                    if live_status_path is not None and iteration is not None:
                        _write_live_status(live_status_path, iteration, solved)

        except Exception as e:
            log_debug("Runner error: %s\n%s", e, traceback.format_exc())
            raise
        finally:
            run_end = time.perf_counter()
            if screenshot_task is not None:
                screenshot_task.cancel()
                try:
                    await screenshot_task
                except asyncio.CancelledError:
                    pass
            # Stop tracing first (so it's saved), then close context so video is finalized
            if trace:
                try:
                    await context.tracing.stop(path=out_dir / "traces" / "run_trace.zip")
                except Exception as ex:
                    log_debug("Tracing stop error: %s", ex)
            await context.close()
            # Video path is available after context close; log for debugging (especially on failure)
            if video and page.video:
                try:
                    video_path = await page.video.path()
                    log_debug("Video saved to %s", video_path)
                except Exception as ex:
                    log_debug("Video path error: %s (video dir: %s)", ex, video_dir)
            await browser.close()

    finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    total_seconds = (run_end - run_start) if run_end is not None else (sum(s.seconds for s in step_results) if step_results else 0)

    save_learned(out_dir, step_results, shared_dir=shared_learned_dir)

    import platform
    try:
        import playwright as pw
        playwright_version = getattr(pw, "__version__", "unknown")
    except Exception:
        playwright_version = "unknown"

    stats = RunStats(
        url=url,
        started_at=started_at,
        finished_at=finished_at,
        total_seconds=total_seconds,
        solved_count=solved,
        attempted_count=attempted,
        steps=step_results,
        environment={
            "python_version": sys.version.split()[0],
            "playwright_version": playwright_version,
            "platform": platform.platform(),
        },
        headless=headless,
        resource_blocking=resource_blocking,
        token_usage=token_usage_accum if token_usage_accum else None,
        token_cost_usd=token_cost_usd_accum if token_cost_usd_accum else None,
    )
    if live_status_path is not None and iteration is not None:
        _write_live_status(live_status_path, iteration, solved, f"Finished in {total_seconds:.1f}s.")
    return stats


def create_submission_zip(out_dir: Path, zip_path: Path) -> None:
    """Create submission.zip with source, README, out/results.json, out/debug.log. Exclude .venv, __pycache__, node_modules."""
    import zipfile
    root = Path(__file__).resolve().parent.parent
    exclude_dirs = {".venv", "__pycache__", "node_modules", ".git"}
    exclude_suffixes = (".pyc", ".pyo")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in root.rglob("*"):
            if f.is_file() and f.suffix not in exclude_suffixes:
                try:
                    rel = f.relative_to(root)
                except ValueError:
                    continue
                parts = rel.parts
                if any(d in parts for d in exclude_dirs):
                    continue
                if "submission.zip" in parts:
                    continue
                # Add out/results.json, out/debug.log, out/live_status.md only in the explicit loop below to avoid duplicate names
                if rel in (Path("out") / "results.json", Path("out") / "debug.log", Path("out") / "live_status.md"):
                    continue
                zf.write(f, rel)
        # Ensure out/ is included (single source to avoid duplicate name warning)
        for name in ["results.json", "debug.log", "live_status.md"]:
            p = out_dir / name
            if p.exists():
                zf.write(p, f"out/{name}")
    print(f"Created {zip_path}", file=sys.stderr)
