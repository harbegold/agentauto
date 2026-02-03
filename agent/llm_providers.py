"""Multi-provider LLM support for browser automation fallback (OpenAI, Anthropic)."""
from typing import Optional

# Supported providers and their env var for API key
LLM_PROVIDERS = {"openai", "anthropic"}
DEFAULT_PROVIDER = "openai"


def get_api_key_for_provider(provider: str) -> str:
    """Return API key for provider from environment. Empty string if not set."""
    import os
    key_env = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    env_var = key_env.get(provider.lower(), "")
    if not env_var:
        return ""
    return (os.environ.get(env_var) or "").strip()


async def call_llm(
    provider: str,
    model: str,
    api_key: str,
    prompt: str,
    max_tokens: int = 500,
) -> tuple[str, Optional[dict]]:
    """
    Call the configured LLM provider. Returns (response_text, usage_dict).
    usage_dict has prompt_tokens, completion_tokens, total_tokens when available.
    """
    provider = (provider or DEFAULT_PROVIDER).lower()
    if not api_key:
        return "", None

    if provider == "openai":
        return await _call_openai(model, api_key, prompt, max_tokens)
    if provider == "anthropic":
        return await _call_anthropic(model, api_key, prompt, max_tokens)
    # Fallback to OpenAI if unknown
    return await _call_openai(model, api_key, prompt, max_tokens)


async def _call_openai(
    model: str, api_key: str, prompt: str, max_tokens: int
) -> tuple[str, Optional[dict]]:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return "", None
    client = AsyncOpenAI(api_key=api_key)
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.2,
        )
        raw = (resp.choices[0].message.content or "").strip()
        usage = None
        if getattr(resp, "usage", None):
            u = resp.usage
            usage = {
                "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                "total_tokens": getattr(u, "total_tokens", 0) or 0,
            }
        return raw, usage
    except Exception:
        return "", None


async def _call_anthropic(
    model: str, api_key: str, prompt: str, max_tokens: int
) -> tuple[str, Optional[dict]]:
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        return "", None
    client = AsyncAnthropic(api_key=api_key)
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = ""
        for block in getattr(resp, "content", []):
            if getattr(block, "type", None) == "text":
                raw = (getattr(block, "text", None) or "").strip()
                break
        usage = None
        if getattr(resp, "usage", None):
            u = resp.usage
            usage = {
                "prompt_tokens": getattr(u, "input_tokens", 0) or 0,
                "completion_tokens": getattr(u, "output_tokens", 0) or 0,
                "total_tokens": (getattr(u, "input_tokens", 0) or 0) + (getattr(u, "output_tokens", 0) or 0),
            }
        return raw, usage
    except Exception:
        return "", None


def estimate_cost_usd(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Rough cost in USD for the given provider/model and token counts."""
    provider = (provider or DEFAULT_PROVIDER).lower()
    model_lower = (model or "").lower()

    if provider == "openai":
        if "gpt-4o-mini" in model_lower:
            return (prompt_tokens / 1e6) * 0.15 + (completion_tokens / 1e6) * 0.60
        if "gpt-4o" in model_lower:
            return (prompt_tokens / 1e6) * 2.50 + (completion_tokens / 1e6) * 10.00
        return (prompt_tokens / 1e6) * 0.15 + (completion_tokens / 1e6) * 0.60

    if provider == "anthropic":
        # Claude 3.5 Sonnet / Haiku approximate
        if "claude-3-5-sonnet" in model_lower:
            return (prompt_tokens / 1e6) * 3.00 + (completion_tokens / 1e6) * 15.00
        if "claude-3-5-haiku" in model_lower or "claude-3-haiku" in model_lower:
            return (prompt_tokens / 1e6) * 0.25 + (completion_tokens / 1e6) * 1.25
        return (prompt_tokens / 1e6) * 0.25 + (completion_tokens / 1e6) * 1.25

    return (prompt_tokens / 1e6) * 0.15 + (completion_tokens / 1e6) * 0.60
