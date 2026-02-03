"""Click, type, close popups, scroll."""
import re
from typing import Optional

from playwright.async_api import BrowserContext, Page

from .site import (
    CLOSE_BUTTON_TEXTS,
    CODE_INPUT_SELECTORS,
    DECOY_BUTTON_PATTERN,
    MODAL_SELECTORS,
    SUBMIT_BUTTON_SELECTORS,
)


async def _close_cookie_consent(page: Page) -> bool:
    """
    Close Cookie Consent overlay first. It often has z-[9999] and intercepts all clicks.
    Find the overlay that contains 'Cookie Consent' or '🍪' and click Accept/Close inside it only.
    """
    try:
        # Any container with Cookie Consent / cookie / 🍪 in text (often div.fixed with high z-index)
        container = page.locator(
            "div, [role=dialog], [class*='modal'], [class*='popup'], [class*='overlay']"
        ).filter(has_text=re.compile(r"Cookie\s*Consent|🍪|We use cookies|cookie consent", re.I)).first
        if await container.count() == 0:
            return False
        # Click only buttons INSIDE this container so we don't hit a decoy behind
        for btn_text in ["Accept", "Accept All", "Allow", "Allow All", "Close", "OK", "I agree", "Agree", "Got it", "Dismiss", "Continue"]:
            btn = container.get_by_role("button", name=re.compile(re.escape(btn_text), re.I)).first
            if await btn.count() > 0:
                try:
                    await btn.click(timeout=2000)
                    await page.wait_for_timeout(150)
                    return True
                except Exception:
                    pass
        # Fallback: any button inside the container
        any_btn = container.locator("button").first
        if await any_btn.count() > 0:
            try:
                await any_btn.click(timeout=2000)
                await page.wait_for_timeout(150)
                return True
            except Exception:
                pass
    except Exception:
        pass
    return False


async def _close_wrong_button_banner(page: Page) -> bool:
    """If 'Wrong Button! Try Again!' is visible, click X or close to dismiss. Returns True if dismissed."""
    try:
        # Any dialog/banner containing "Wrong Button" or "Try Again" (error feedback)
        for sel in ["[role=dialog]", "[class*='modal']", "[class*='alert']", "[class*='banner']"]:
            dialogs = page.locator(sel).filter(has_text=re.compile(r"Wrong Button|Try Again", re.I))
            if await dialogs.count() == 0:
                continue
            top = dialogs.last
            for close_text in ["×", "✕", "X", "Close", "Dismiss", "OK", "Try Again"]:
                try:
                    b = top.get_by_role("button", name=re.compile(re.escape(close_text), re.I)).first
                    if await b.count() > 0:
                        await b.click(timeout=1000)
                        await page.wait_for_timeout(80)
                        return True
                except Exception:
                    pass
            for close_sel in [".close", "button"]:
                try:
                    el = top.locator(close_sel).first
                    if await el.count() > 0:
                        await el.click(timeout=1000)
                        await page.wait_for_timeout(80)
                        return True
                except Exception:
                    pass
    except Exception:
        pass
    return False


async def _close_newsletter_popup(page: Page) -> bool:
    """Close 'Subscribe to our newsletter' or similar promotional popups. Returns True if closed."""
    try:
        # Find popups containing newsletter/subscribe text
        patterns = [
            r"subscribe.*newsletter",
            r"newsletter.*subscribe",
            r"sign up.*newsletter",
            r"join.*mailing",
            r"get.*updates",
            r"stay.*informed",
        ]
        for pattern in patterns:
            container = page.locator(
                "div, [role=dialog], [class*='modal'], [class*='popup'], [class*='overlay']"
            ).filter(has_text=re.compile(pattern, re.I)).first
            if await container.count() == 0:
                continue
            # Try common close buttons
            for btn_text in ["No thanks", "No, thanks", "Not now", "Maybe later", "Close", "×", "✕", "X", "Dismiss", "Skip"]:
                btn = container.get_by_role("button", name=re.compile(re.escape(btn_text), re.I)).first
                if await btn.count() > 0:
                    try:
                        await btn.click(timeout=1000)
                        await page.wait_for_timeout(80)
                        return True
                    except Exception:
                        pass
            # Fallback: any button that looks like decline/close
            for sel in ["button", ".close", "[class*='close']"]:
                el = container.locator(sel).first
                if await el.count() > 0:
                    try:
                        await el.click(timeout=1000)
                        await page.wait_for_timeout(80)
                        return True
                    except Exception:
                        pass
    except Exception:
        pass
    return False


async def _close_topmost_foreground_popup(page: Page) -> bool:
    """
    Find the topmost dialog/modal and click the right close action.
    Skips the "Please Select an Option" challenge modal (let handle_select_option_modal handle it).
    If the popup says "The close button is fake! Look for another way to close",
    only click Dismiss (never X/Close). Otherwise try Close, Dismiss, X.
    Peels nested popups from top to bottom.
    """
    # Cookie Consent overlay often has z-[9999] and intercepts all clicks – close it first by clicking inside it
    if await _close_cookie_consent(page):
        return True
    # Close newsletter/promotional popups
    if await _close_newsletter_popup(page):
        return True
    # Dismiss "Wrong Button! Try Again!" so we can retry selection
    if await _close_wrong_button_banner(page):
        return True
    for sel in ["[role=dialog]", "[class*='modal']", "[class*='popup']", "[class*='overlay']"]:
        try:
            dialogs = page.locator(sel)
            n = await dialogs.count()
            if n == 0:
                continue
            topmost = dialogs.nth(n - 1)
            try:
                dialog_text = (await topmost.inner_text()) or ""
                dialog_text_lower = dialog_text.lower()
            except Exception:
                dialog_text_lower = ""
            # Do NOT close the "Please Select an Option" modal – handle_select_option_modal handles it
            if "select an option" in dialog_text_lower or "select your choice" in dialog_text_lower:
                continue
            # Check if this popup says the close button is fake – then only use Dismiss
            # Also check for "Important Note" which typically has fake close button
            fake_close = (
                ("fake" in dialog_text_lower and ("another way" in dialog_text_lower or "close" in dialog_text_lower)) or
                ("important" in dialog_text_lower and "note" in dialog_text_lower) or
                ("popup" in dialog_text_lower and "message" in dialog_text_lower and "close" in dialog_text_lower)
            )
            if fake_close:
                # Only click Dismiss / Got it / OK – never X or "Close"
                for safe_text in ["Dismiss", "Got it", "OK", "I understand", "Continue"]:
                    btn = topmost.get_by_role("button", name=re.compile(re.escape(safe_text), re.I)).first
                    if await btn.count() > 0:
                        await btn.click(timeout=1000)
                        await page.wait_for_timeout(80)
                        return True
                # Fallback: look for any button that's NOT Close/X
                for btn_text in ["Dismiss", "Got it", "OK", "Continue", "I understand"]:
                    btn = topmost.locator(f"button:has-text('{btn_text}')").first
                    if await btn.count() > 0:
                        try:
                            await btn.click(timeout=1000)
                            await page.wait_for_timeout(80)
                            return True
                        except Exception:
                            pass
                continue
            # Normal popup: try Close, Dismiss, then X
            for close_text in ["Close", "Dismiss", "×", "✕", "X"]:
                btn = topmost.get_by_role("button", name=re.compile(re.escape(close_text), re.I)).first
                if await btn.count() > 0:
                    await btn.click(timeout=1000)
                    await page.wait_for_timeout(80)
                    return True
            for close_sel in [".close", "button.close"]:
                el = topmost.locator(close_sel).first
                if await el.count() > 0:
                    await el.click(timeout=1000)
                    await page.wait_for_timeout(80)
                    return True
        except Exception:
            pass
    return False


async def _close_overlays_one_round(page: Page, max_esc: int = 5, max_clicks: int = 15) -> bool:
    """One round: close topmost popup first, then ESC + global close buttons. Returns True if any click was done."""
    # 1) Explicitly close the topmost foreground dialog (e.g. newsletter, "You won a prize")
    if await _close_topmost_foreground_popup(page):
        return True
    # 2) ESC + click any Close/Dismiss/etc. on the page (only buttons not behind Cookie Consent / top overlay)
    for _ in range(max_esc):
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(40)
    found_any = False
    for text in ["Close", "Dismiss", "Accept", "OK", "×", "✕"]:
        try:
            buttons = page.get_by_role("button", name=re.compile(re.escape(text), re.I))
            for i in range(await buttons.count()):
                btn = buttons.nth(i)
                try:
                    # Skip if inside the "Please Select an Option" modal
                    in_select_modal = await btn.evaluate("""el => {
                        const d = el.closest('[role=dialog], [class*="modal"], [class*="popup"]');
                        return d && (d.textContent || '').toLowerCase().includes('select an option');
                    }""")
                    if in_select_modal:
                        continue
                    await btn.click(timeout=1000)
                    await page.wait_for_timeout(80)
                    return True
                except Exception:
                    pass
        except Exception:
            pass
    for sel in [".close", "button.close"]:
        try:
            el = page.locator(sel).first
            if await el.count() > 0:
                in_select_modal = await el.evaluate("""el => {
                    const d = el.closest('[role=dialog], [class*="modal"], [class*="popup"]');
                    return d && (d.textContent || '').toLowerCase().includes('select an option');
                }""")
                if not in_select_modal:
                    await el.click(timeout=1000)
                    await page.wait_for_timeout(80)
                    return True
        except Exception:
            pass
    return found_any


async def normalize_ui(page: Page, max_esc: int = 3, max_clicks: int = 8, rounds: int = 2) -> None:
    """
    Close overlays: Cookie Consent first (it intercepts clicks), then peel topmost, then ESC + Close.
    """
    # Cookie Consent often appears on load and blocks all clicks – clear it first
    for _ in range(3):
        if not await _close_cookie_consent(page):
            break
        await page.wait_for_timeout(50)
    for _ in range(2):
        if not await _close_topmost_foreground_popup(page):
            break
        await page.wait_for_timeout(30)
    for _ in range(rounds):
        found = await _close_overlays_one_round(page, max_esc=max_esc, max_clicks=max_clicks)
        if not found:
            break
        await page.wait_for_timeout(30)
    await page.wait_for_timeout(30)


async def close_popup_windows(context: BrowserContext, main_page: Page) -> None:
    """
    If the site opened separate popup windows/tabs, close them and stay on the main page.
    For each extra page: try to click Close/Dismiss/X on it, then close the page.
    """
    try:
        pages = context.pages
        if len(pages) <= 1:
            return
        for p in pages:
            if p is main_page or p.is_closed():
                continue
            try:
                await _close_overlays_one_round(p, max_esc=3, max_clicks=6)
                await p.wait_for_timeout(100)
            except Exception:
                pass
            try:
                if not p.is_closed():
                    await p.close()
            except Exception:
                pass
        await main_page.bring_to_front()
    except Exception:
        pass


async def handle_select_option_modal(page: Page) -> bool:
    """
    If a 'Please Select an Option' / 'Select Your Choice' modal is open,
    scroll it, select the correct option, and click Submit *inside the modal only*
    (never a background decoy). Returns True if we found and handled the modal.
    """
    try:
        # Resolve the dialog/container that contains "Please Select an Option"
        dialog = page.locator("[role=dialog], [class*='modal']").filter(
            has_text=re.compile(r"Please Select an Option|Select Your Choice|Select an Option", re.I)
        ).first
        if await dialog.count() == 0:
            # Fallback: any container with that text (e.g. div.popup, section)
            dialog = page.locator("div, section, [class*='popup'], [class*='dialog']").filter(
                has_text=re.compile(r"Please Select an Option|Select Your Choice|Select an Option", re.I)
            ).first
        if await dialog.count() == 0:
            return False

        # Scroll the modal so options and Submit are visible
        try:
            await dialog.evaluate("el => { el.scrollTop = el.scrollHeight; el.scrollBy(0, 300); }")
            await page.wait_for_timeout(100)
        except Exception:
            pass

        # Select correct option (prefer inside dialog so we don't hit background)
        try:
            semantic = dialog.locator("[data-correct='true'], [data-correct=true], [aria-selected='true']").first
            if await semantic.count() > 0:
                await semantic.click(timeout=1500)
                await page.wait_for_timeout(60)
        except Exception:
            pass
        correct_patterns = [
            ("Option B - Correct Choice", False),
            ("This is correct", False),
            ("The right choice", False),
            ("Correct choice", False),
            ("Option B - Correct", False),
            ("Correct Choice", False),
            (r"(?<!in)correct(?:\s*choice)?|the\s+right\s+choice|this\s+is\s+correct", True),
        ]
        for pattern, is_regex in correct_patterns:
            regex = re.compile(pattern, re.I) if is_regex else re.compile(re.escape(pattern), re.I)
            opt = dialog.get_by_role("radio", name=regex).first
            if await opt.count() > 0:
                await opt.click(timeout=1500)
                await page.wait_for_timeout(60)
                break
            if not is_regex:
                label = dialog.locator(f"label:has-text('{pattern}')").first
                if await label.count() > 0:
                    await label.click(timeout=1500)
                    await page.wait_for_timeout(60)
                    break

        # Click Submit ONLY inside this dialog (avoids "Wrong Button!" from background decoys)
        for btn_text in ["Submit & Continue", "Submit and Continue", "Submit"]:
            btn = dialog.get_by_role("button", name=re.compile(re.escape(btn_text), re.I)).first
            if await btn.count() > 0:
                await btn.scroll_into_view_if_needed(timeout=1500)
                await btn.click(timeout=1500)
                await page.wait_for_timeout(100)
                return True
        submit_btn = dialog.locator("button").filter(has_text=re.compile(r"Submit", re.I)).first
        if await submit_btn.count() > 0:
            await submit_btn.scroll_into_view_if_needed(timeout=1500)
            await submit_btn.click(timeout=1500)
            await page.wait_for_timeout(100)
            return True
    except Exception:
        pass
    return False


def _code_entry_section_locator(page: Page):
    """Locator for the section that contains 'Enter Code to Proceed' and the Submit Code button."""
    return page.locator("div, form, section").filter(
        has_text=re.compile(r"Enter Code to Proceed|Proceed to Step", re.I)
    ).filter(has=page.locator('button:has-text("Submit Code")')).first


async def find_and_fill_code_input(page: Page, code: str) -> bool:
    """
    Find input for code (placeholder containing 'code' or first visible input), fill and submit.
    Prefers clicking "Submit Code" inside the code-entry section (Enter Code to Proceed) to avoid
    decoy buttons; falls back to global submit buttons (skipping decoys).
    Returns True if filled and submitted.
    """
    for sel in CODE_INPUT_SELECTORS:
        try:
            inp = page.locator(sel).first
            if await inp.count() == 0:
                continue
            await inp.scroll_into_view_if_needed(timeout=3000)
            await inp.fill("")
            await inp.fill(code)
            await page.wait_for_timeout(50)
            # Prefer Submit Code inside the code-entry section (avoids decoys below)
            try:
                section = _code_entry_section_locator(page)
                if await section.count() > 0:
                    btn = section.locator('button:has-text("Submit Code")').first
                    if await btn.count() > 0:
                        await btn.scroll_into_view_if_needed(timeout=1500)
                        await btn.click(timeout=1500)
                        await page.wait_for_timeout(100)
                        return True
            except Exception:
                pass
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(100)
            # Fallback: first submit/proceed button that is NOT a decoy
            for btn_sel in SUBMIT_BUTTON_SELECTORS:
                try:
                    btn = page.locator(btn_sel).first
                    if await btn.count() == 0:
                        continue
                    text = (await btn.text_content() or "").strip()
                    if DECOY_BUTTON_PATTERN.match(text):
                        continue
                    await btn.click(timeout=1500)
                    await page.wait_for_timeout(100)
                    return True
                except Exception:
                    pass
            return True
        except Exception:
            continue
    return False


async def get_visible_buttons_text(page: Page, limit: int = 30) -> list[str]:
    """Return text of visible buttons (first N) for debug."""
    try:
        texts = await page.evaluate(f"""() => {{
            const nodes = document.querySelectorAll('button, [role="button"], a, input[type="submit"]');
            const out = [];
            for (const n of nodes) {{
                if (n.offsetParent === null) continue;
                const t = (n.textContent || n.value || '').trim().slice(0, 80);
                if (t) out.push(t);
                if (out.length >= {limit}) break;
            }}
            return out;
        }}""")
        return list(texts) if texts else []
    except Exception:
        return []


async def get_visible_inputs_count(page: Page) -> int:
    try:
        return await page.evaluate("""() => {
            return document.querySelectorAll('input:not([type=hidden])').length;
        }""")
    except Exception:
        return 0


async def scroll_to_bottom_and_back(page: Page) -> None:
    """Scroll down then up to trigger lazy content / reveal code."""
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(100)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(100)
    except Exception:
        pass
