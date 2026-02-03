"""LLM fallback: when deterministic extraction fails, ask model for a small JSON action plan and execute with Playwright."""
import json
import re
from typing import Any, Optional

from playwright.async_api import Page

# Allowed action types in JSON plan
ALLOWED_ACTIONS = {"click", "type", "press", "scroll"}


async def get_page_context(page: Page, step: Optional[int] = None, max_body_chars: int = 2000) -> dict[str, Any]:
    """Gather URL, visible buttons, inputs, and main text for the LLM."""
    try:
        url = page.url
    except Exception:
        url = ""
    buttons: list[dict[str, str]] = []
    inputs_list: list[dict[str, str]] = []
    try:
        buttons = await page.evaluate("""() => {
            const nodes = document.querySelectorAll('button, [role="button"], a[href], input[type="submit"]');
            const out = [];
            for (const n of nodes) {
                if (n.offsetParent === null) continue;
                const text = (n.textContent || n.value || '').trim().slice(0, 120);
                const role = (n.getAttribute('role') || n.tagName.toLowerCase()).toLowerCase();
                if (text || role === 'button') out.push({ role, text });
            }
            return out.slice(0, 80);
        }""")
    except Exception:
        pass
    try:
        inputs_list = await page.evaluate("""() => {
            const nodes = document.querySelectorAll('input:not([type=hidden])');
            const out = [];
            for (const n of nodes) {
                const ph = (n.getAttribute('placeholder') || '').slice(0, 80);
                const label = (n.getAttribute('aria-label') || '').slice(0, 80);
                const name = (n.getAttribute('name') || '').slice(0, 40);
                out.push({ placeholder: ph, ariaLabel: label, name });
            }
            return out.slice(0, 30);
        }""")
    except Exception:
        pass
    heading_body = ""
    try:
        heading_body = await page.evaluate(f"""() => {{
            const body = document.body?.innerText || '';
            return body.slice(0, {max_body_chars});
        }}""")
    except Exception:
        pass
    return {
        "url": url,
        "step": step,
        "buttons": buttons,
        "inputs": inputs_list,
        "bodySnippet": heading_body,
    }


def build_llm_prompt(context: dict[str, Any]) -> str:
    """Build a single prompt asking for a small JSON action plan."""
    step = context.get("step")
    step_line = f"Current step (if known): {step}." if step else "Current step unknown."
    return f"""You are helping a browser automation agent. The agent is stuck and needs a SHORT sequence of actions.

{step_line}
URL: {context.get('url', '')}

Visible buttons (role, text): {json.dumps(context.get('buttons', [])[:50])}
Visible inputs (placeholder, ariaLabel, name): {json.dumps(context.get('inputs', [])[:20])}

Page text (first 2000 chars):
{context.get('bodySnippet', '')[:2000]}

Reply with ONLY a JSON array of actions. Each action is an object with one key: "action" (one of: click, type, press, scroll) and extra fields as below.
- click: include "selector" (CSS selector) OR "role" and "name" (e.g. role=button, name=Submit)
- type: include "selector" and "text"
- press: include "key" (e.g. Enter, Escape)
- scroll: include "amount" (number, positive=down) or "direction" ("up"/"down")

Example: [{{"action": "click", "role": "button", "name": "Submit"}}, {{"action": "press", "key": "Escape"}}]
Keep the list SHORT (1-5 actions). Output ONLY the JSON array, no markdown or explanation."""


def parse_action_plan(raw: str) -> list[dict[str, Any]]:
    """Parse LLM response into a list of action dicts; validate and filter to allowed actions only."""
    raw = raw.strip()
    # Strip markdown code block if present
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(plan, list):
        return []
    out = []
    for item in plan:
        if not isinstance(item, dict):
            continue
        action = (item.get("action") or "").strip().lower()
        if action not in ALLOWED_ACTIONS:
            continue
        out.append({"action": action, **{k: v for k, v in item.items() if k != "action"}})
    return out[:10]


async def execute_action_plan(page: Page, plan: list[dict[str, Any]]) -> None:
    """Execute a parsed action plan with Playwright. Ignores invalid or failing actions."""
    for item in plan:
        action = item.get("action")
        if not action:
            continue
        try:
            if action == "click":
                if item.get("role") and item.get("name"):
                    await page.get_by_role(item["role"], name=re.compile(re.escape(str(item["name"])), re.I)).first.click(timeout=3000)
                elif item.get("selector"):
                    await page.locator(item["selector"]).first.click(timeout=3000)
                await page.wait_for_timeout(250)
            elif action == "type":
                sel = item.get("selector")
                text = item.get("text", "")
                if sel:
                    await page.locator(sel).first.fill("")
                    await page.locator(sel).first.fill(str(text))
                await page.wait_for_timeout(200)
            elif action == "press":
                key = item.get("key", "Escape")
                await page.keyboard.press(str(key))
                await page.wait_for_timeout(200)
            elif action == "scroll":
                amount = item.get("amount", 300)
                direction = (item.get("direction") or "").lower()
                if direction == "up":
                    amount = -abs(int(amount) if isinstance(amount, (int, float)) else 300)
                else:
                    amount = abs(int(amount) if isinstance(amount, (int, float)) else 300)
                await page.evaluate(f"window.scrollBy(0, {amount})")
                await page.wait_for_timeout(250)
        except Exception:
            pass


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int, provider: str = "openai") -> float:
    """Rough cost in USD; delegates to llm_providers for multi-provider support."""
    from .llm_providers import estimate_cost_usd as _estimate
    return _estimate(provider, model, prompt_tokens, completion_tokens)


async def ask_llm_for_plan(
    context: dict[str, Any],
    model: str,
    api_key: Optional[str] = None,
    provider: str = "openai",
) -> tuple[list[dict[str, Any]], Optional[dict[str, Any]]]:
    """Call LLM (OpenAI or Anthropic) and return (parsed action plan, usage dict)."""
    from .llm_providers import call_llm, get_api_key_for_provider
    key = (api_key or "").strip() or get_api_key_for_provider(provider)
    if not key:
        return [], None
    prompt = build_llm_prompt(context)
    raw, usage = await call_llm(provider, model, key, prompt, max_tokens=500)
    plan = parse_action_plan(raw)
    return plan, usage
