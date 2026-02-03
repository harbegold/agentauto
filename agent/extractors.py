"""DOM code extraction, localStorage/sessionStorage scan, network intercept."""
import json
import re
from typing import Any, Dict, Optional

from playwright.async_api import Page

from .site import CODE_LABEL_PATTERNS, code_like_token

# Type for network codes cache (step -> code); passed through call chain to avoid module-level state
NetworkCodesCache = Dict[int, str]

# Token pattern: letters/numbers/-/_ length >= 6
CODE_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9\-_]{6,}")


# Words that are likely button/label text or page copy, not step codes (avoid returning these)
DECOY_WORDS = re.compile(
    r"^(Proceed|Continue|Advance|Forward|Reading|Section|Challenge|Browser|Navigation|"
    r"Hidden|Complete|Click|Reveal|Submit|Enter|Next|Move|Going|Journey|Page|Step|Content|Block|Loaded|"
    r"Automation|Ultimate|Test|Inspect|Element|attributes|labels|tags|somewhere|Hint|Check|"
    r"Required|optional|character|filler|Keep|scrolling|find|button|Choose|option|Wrong|Correct|"
    r"Choice|Pick|Option|Select|Your|This|That|The|And|For|With|From|Have|Will|Would|"
    r"Scroll|appeared|revealed|clicked|loaded|failed|passed|button|submit|before|after|"
    r"inside|outside|within|without|below|above|between|during|before|number|string|"
    r"source|target|window|screen|element|parent|child|sibling|length|height|width)$",
    re.I,
)

# Prefer tokens that look like codes: contain a digit, or all-caps 6–8 chars (e.g. VRKT7A)
CODE_LIKE_PATTERN = re.compile(r"^(?:[A-Za-z0-9]*[0-9][A-Za-z0-9]*|[A-Z]{6,8})$")

# Reject tokens that look like CSS/units or plain numbers (e.g. 15px, 100ms, 2.5s) – they cause "submit did not advance"
UNIT_LIKE_SUFFIX = re.compile(r"(?:px|em|rem|ms|s\d?|%\d*)$", re.I)
MOSTLY_DIGITS = re.compile(r"^\d{2,}$")  # all digits >= 2 chars


def _is_unit_like_or_decoy(token: str) -> bool:
    """True if token looks like a unit/value or decoy, not a step code."""
    if not token or len(token) < 6:
        return True
    if UNIT_LIKE_SUFFIX.search(token) or MOSTLY_DIGITS.match(token):
        return True
    if DECOY_WORDS.match(token):
        return True
    return False


def is_valid_step_code(code: Optional[str]) -> bool:
    """True if code looks like a real step code (not decoy/unit); use to filter storage/network/input."""
    if not code or not isinstance(code, str):
        return False
    return not _is_unit_like_or_decoy(code.strip())


async def extract_codes_from_dom(page: Page) -> Optional[str]:
    """
    Look for code: click "click here 3 times" / reveal section first, then check data/aria, then body tokens.
    """
    try:
        # "Hidden DOM Challenge ... click here 3 more times to reveal" – click that element 3 times
        try:
            click_here = page.get_by_text("click here", exact=False).first
            if await click_here.count() > 0:
                for _ in range(3):
                    await click_here.click(timeout=2000)
                    await page.wait_for_timeout(200)
                await page.wait_for_timeout(400)
                # Code may appear in challenge section after 3 clicks; check data-* on any element and input
                code_after_reveal = await page.evaluate("""() => {
                    const walk = (el) => {
                        if (!el || el.nodeType !== 1) return null;
                        const c = el.getAttribute('data-code') || el.getAttribute('data-challenge-code') || el.getAttribute('data-value');
                        if (c && /^[A-Za-z0-9_-]{6,12}$/.test(c)) return c;
                        for (const child of el.children) { const r = walk(child); if (r) return r; }
                        return null;
                    };
                    const challenge = document.body.querySelector('[class*="challenge" i], [class*="Challenge"]') || document.body;
                    const fromWalk = walk(challenge);
                    if (fromWalk) return fromWalk;
                    const anyData = document.querySelector('[data-code], [data-challenge-code], [data-value]');
                    if (anyData) {
                        const c = anyData.getAttribute('data-code') || anyData.getAttribute('data-challenge-code') || anyData.getAttribute('data-value');
                        if (c && /^[A-Za-z0-9_-]{6,12}$/.test(c)) return c;
                    }
                    const inp = document.querySelector('input[placeholder*="code" i], input[name*="code" i]');
                    if (inp && inp.value && /^[A-Za-z0-9_-]{6,}$/.test(inp.value)) return inp.value;
                    return null;
                }""")
                if code_after_reveal and isinstance(code_after_reveal, str):
                    cand = code_after_reveal.strip()
                    if not _is_unit_like_or_decoy(cand):
                        return cand
        except Exception:
            pass

        # Click "Click to Reveal" / "reveal the code" section button
        for phrase in ["Click to Reveal", "reveal the code", "button to reveal", "Click the button"]:
            try:
                container = page.locator("div, section, [class*='card'], [class*='box']").filter(
                    has_text=re.compile(re.escape(phrase), re.I)
                ).first
                if await container.count() > 0:
                    btn = container.locator("button, a, [role='button']").first
                    if await btn.count() > 0:
                        await btn.click(timeout=2000)
                        await page.wait_for_timeout(300)
                        break
            except Exception:
                pass

        # Click "Reveal Code" or similar if present
        for label in ["Reveal Code", "Reveal", "Show Code", "Get Code", "Code Revealed"]:
            btn = page.locator(f"button:has-text('{label}'), a:has-text('{label}'), [role=button]:has-text('{label}')").first
            if await btn.count() > 0:
                try:
                    await btn.click(timeout=2000)
                    await page.wait_for_timeout(200)
                except Exception:
                    pass
                break

        # Hidden DOM: read from data-* and aria-* in challenge section
        try:
            code_from_dom = await page.evaluate("""() => {
                const sel = document.querySelector('[class*="challenge"], [class*="Challenge"], [data-code], [data-challenge]');
                const root = sel || document.body;
                const walk = (el) => {
                    if (!el || el.nodeType !== 1) return null;
                    const c = el.getAttribute('data-code') || el.getAttribute('data-challenge-code') || el.getAttribute('data-value');
                    if (c && /^[A-Za-z0-9_-]{6,}$/.test(c)) return c;
                    const aria = el.getAttribute('aria-label') || el.getAttribute('aria-description') || '';
                    const m = aria.match(/[A-Za-z0-9_-]{6,}/g);
                    if (m) return m.find(x => x.length >= 6 && x.length <= 12) || null;
                    for (const child of el.children) { const r = walk(child); if (r) return r; }
                    return null;
                };
                return walk(root);
            }""")
            if code_from_dom and isinstance(code_from_dom, str) and 6 <= len(code_from_dom) <= 64:
                cand = code_from_dom.strip()
                if not _is_unit_like_or_decoy(cand):
                    return cand
        except Exception:
            pass

        # Pre-filled code input (e.g. after reveal)
        prefill = await extract_code_from_input_value(page)
        if prefill and 6 <= len(prefill) <= 64 and not _is_unit_like_or_decoy(prefill):
            return prefill

        body = await page.evaluate("() => document.body.innerText")
        tokens = CODE_TOKEN_PATTERN.findall(body)
        # Prefer tokens that look like codes; reject unit-like (px, ms) and decoys
        for t in tokens:
            if 6 <= len(t) <= 12 and not _is_unit_like_or_decoy(t) and CODE_LIKE_PATTERN.match(t):
                return t
        for t in tokens:
            if 6 <= len(t) <= 64 and code_like_token(t, min_len=6) and not _is_unit_like_or_decoy(t):
                return t
        for t in tokens:
            if 6 <= len(t) <= 64 and not _is_unit_like_or_decoy(t):
                return t
    except Exception:
        pass
    return None


async def get_challenge_code_for_step_from_storage(page: Page, step: int) -> Optional[str]:
    """Get code for current step from localStorage key challenge_code_step_N (per LinkedIn comment)."""
    try:
        v = await page.evaluate(
            """(step) => {
                try {
                    return window.localStorage.getItem("challenge_code_step_" + step) || null;
                } catch (e) { return null; }
            }""",
            step,
        )
        if v and isinstance(v, str) and 4 <= len(v.strip()) <= 64:
            return v.strip()
    except Exception:
        pass
    return None


async def extract_code_from_input_value(page: Page) -> Optional[str]:
    """Get value from code input if it's pre-filled."""
    try:
        inp = page.locator('input[placeholder*="code" i], input[name*="code" i], input[id*="code" i]').first
        if await inp.count() > 0:
            val = await inp.input_value()
            if val and len(val.strip()) >= 6:
                return val.strip()
    except Exception:
        pass
    return None


def _parse_json_for_codes(data: Any, step_count: int = 30) -> Optional[dict[int, str]]:
    """
    Search JSON for arrays length 30 or dicts with step-indexed codes.
    Returns dict step_index (1-30) -> code string, or None.
    """
    result: dict[int, str] = {}

    def scan(obj: Any, path: str = "") -> None:
        if path.count("_") > 5:  # limit recursion
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                k_lower = str(k).lower()
                if isinstance(v, str) and code_like_token(v, 4):
                    # Key suggests step/code: step, code, answer, token, challenge
                    if any(x in k_lower for x in ("code", "answer", "step", "challenge", "token")):
                        # Try to infer step index from key (e.g. step_1, step1, "1")
                        step = None
                        if "step" in k_lower:
                            num = re.search(r"\d+", str(k))
                            if num:
                                step = int(num.group())
                        if step is None and re.match(r"^\d+$", str(k)):
                            step = int(k)
                        if step is not None and 1 <= step <= 30:
                            result[step] = v
                scan(v, path + "/" + str(k))
        elif isinstance(obj, list):
            if len(obj) == step_count:
                for i, v in enumerate(obj):
                    if isinstance(v, str) and code_like_token(v, 4):
                        result[i + 1] = v
                    elif isinstance(v, dict):
                        for k2, v2 in v.items():
                            if "code" in str(k2).lower() and isinstance(v2, str):
                                result[i + 1] = v2
                                break
            else:
                for i, v in enumerate(obj):
                    scan(v, path + f"/[{i}]")

    try:
        scan(data)
        if len(result) >= step_count or (result and max(result.keys()) <= 30):
            return result if result else None
    except Exception:
        pass
    return result if len(result) >= 10 else None  # partial use if many steps found


async def extract_codes_from_storage(page: Page) -> Optional[dict[int, str]]:
    """
    Dump localStorage and sessionStorage; detect JSON blobs; search for step->code mapping.
    """
    all_codes: dict[int, str] = {}

    async def dump_storage(storage_type: str) -> None:
        nonlocal all_codes
        try:
            if storage_type == "localStorage":
                items = await page.evaluate("""() => {
                    const o = {};
                    for (let i = 0; i < localStorage.length; i++) {
                        const k = localStorage.key(i);
                        o[k] = localStorage.getItem(k);
                    }
                    return o;
                }""")
            else:
                items = await page.evaluate("""() => {
                    const o = {};
                    for (let i = 0; i < sessionStorage.length; i++) {
                        const k = sessionStorage.key(i);
                        o[k] = sessionStorage.getItem(k);
                    }
                    return o;
                }""")
            for k, v in items.items():
                if not v or len(v) > 100_000:
                    continue
                key_lower = k.lower()
                # Explicit challenge keys: challenge_code_step_1, challenge_code_step_2, ... (plain string values)
                step_match = re.match(r"challenge_code_step_(\d+)", k, re.I)
                if step_match:
                    step_num = int(step_match.group(1))
                    if 1 <= step_num <= 30 and code_like_token(v.strip(), 4) and len(v.strip()) <= 64:
                        all_codes[step_num] = v.strip()
                    continue
                if not any(x in key_lower for x in ("code", "answer", "step", "challenge", "token", "state", "data")):
                    continue
                try:
                    data = json.loads(v)
                    mapping = _parse_json_for_codes(data, 30)
                    if mapping:
                        for step, code in mapping.items():
                            if step not in all_codes or len(code) >= 6:
                                all_codes[step] = code
                except (json.JSONDecodeError, TypeError):
                    if code_like_token(v, 6) and len(v) <= 64:
                        all_codes[1] = v.strip()
        except Exception:
            pass

    await dump_storage("localStorage")
    await dump_storage("sessionStorage")
    # Return any step->code map we found (partial ok: e.g. step 2–30 from challenge_code_step_N)
    return all_codes if all_codes else None


async def get_storage_debug_info(page: Page) -> dict[str, Any]:
    """Return storage keys and value lengths for debug log."""
    out: dict[str, Any] = {"localStorage": {}, "sessionStorage": {}}
    try:
        for name, key in [("localStorage", "localStorage"), ("sessionStorage", "sessionStorage")]:
            items = await page.evaluate(f"""() => {{
                const o = {{}};
                for (let i = 0; i < {key}.length; i++) {{
                    const k = {key}.key(i);
                    const v = {key}.getItem(k);
                    o[k] = v ? v.length : 0;
                }}
                return o;
            }}""")
            out[name] = items
    except Exception:
        pass
    return out


def get_network_codes(cache: NetworkCodesCache) -> dict[int, str]:
    """Return a copy of the network codes cache (safe for callers)."""
    return cache.copy()


def clear_network_codes_cache(cache: NetworkCodesCache) -> None:
    cache.clear()


def _inject_network_codes_from_json(data: Any, cache: NetworkCodesCache) -> None:
    try:
        mapping = _parse_json_for_codes(data, 30)
        if mapping:
            for step, code in mapping.items():
                cache[step] = code
    except Exception:
        pass


async def install_network_listener(page: Page, cache: NetworkCodesCache) -> None:
    """Attach response listener before any navigation; captures JSON responses into cache."""
    async def on_response(response):
        try:
            ct = response.headers.get("content-type") or ""
            if "json" not in ct:
                return
            body = await response.text()
            data = json.loads(body)
            _inject_network_codes_from_json(data, cache)
        except Exception:
            pass

    page.on("response", on_response)
