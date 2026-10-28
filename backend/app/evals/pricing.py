"""Cost of one arm's calls, from its token counts.

USD per million tokens: Anthropic first-party list prices from the Claude API
reference (cached 2026-10-06). Cache writes use the 5-minute rate, 1.25x input,
which is what the shared prompt prefix uses. Thinking tokens are billed as
output and already included in output_tokens.

Add or override models with OT_MODEL_PRICES, e.g.
  OT_MODEL_PRICES='{"my-model": {"input": 1, "output": 5, "cache_read": 0.1, "cache_write": 1.25}}'
A model with no price is reported as "not computed", never as $0.
"""

from app.config import settings

DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write": 6.25},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25},
}


def price_for(model: str) -> dict[str, float] | None:
    return {**DEFAULT_PRICES, **settings.model_prices}.get(model)


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int) -> dict | None:
    """{total, input, output, cache_read, cache_write} in USD, or None if the model has no price."""
    p = price_for(model)
    if p is None:
        return None
    parts = {
        "input": input_tokens * p["input"],
        "output": output_tokens * p["output"],
        "cache_read": cache_read * p["cache_read"],
        "cache_write": cache_write * p["cache_write"],
    }
    parts = {k: v / 1_000_000 for k, v in parts.items()}
    return {"total": sum(parts.values()), **parts}
