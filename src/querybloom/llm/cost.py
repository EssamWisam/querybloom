"""LLM cost and token usage tracking utilities."""

from __future__ import annotations

from typing import Any, Dict, Optional
from litellm import completion_cost, cost_per_token
from litellm.cost_calculator import get_response_cost_from_hidden_params


def calculate_completion_cost(
    response: Any,
    model: Optional[str] = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> float:
    """Calculate the estimated USD cost of a LiteLLM completion response safely.

    Returns 0.0 if cost calculation fails or is unavailable for the model.
    """
    resolved_model = model or getattr(response, "model", None)
    if isinstance(response, dict) and not resolved_model:
        resolved_model = response.get("model")

    # 0. Provider-reported cost. OpenRouter returns `usage.cost` and LiteLLM stores it in
    # `_hidden_params["additional_headers"]`. `completion_cost` does not read that field, so
    # OpenRouter models absent from LiteLLM's price map (for example
    # `openrouter/anthropic/claude-haiku-5.5`) returned 0.0 before this step existed.
    hidden_params = getattr(response, "_hidden_params", None)
    if isinstance(hidden_params, dict):
        provider_cost = get_response_cost_from_hidden_params(hidden_params)
        if provider_cost is not None:
            return float(provider_cost)

    # 1. Try standard completion_cost with response object
    try:
        cost = completion_cost(completion_response=response, model=resolved_model)
        if isinstance(cost, (int, float)) and cost > 0:
            return float(cost)
    except Exception:
        pass

    try:
        cost = completion_cost(completion_response=response)
        if isinstance(cost, (int, float)) and cost > 0:
            return float(cost)
    except Exception:
        pass

    # 2. Fallback to cost_per_token if token counts and model are available
    if resolved_model and (prompt_tokens > 0 or completion_tokens > 0):
        try:
            p_cost, c_cost = cost_per_token(
                model=str(resolved_model),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            total = float(p_cost + c_cost)
            if total >= 0:
                return total
        except Exception:
            pass

    return 0.0


def extract_usage_and_cost(
    response: Any, model: Optional[str] = None
) -> Dict[str, Any]:
    """Extract token usage metrics and calculated USD cost from a completion response."""
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0

    usage = getattr(response, "usage", None)
    if usage is not None:
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(
            getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens)
        )
    elif isinstance(response, dict) and "usage" in response:
        u = response["usage"]
        if isinstance(u, dict):
            prompt_tokens = int(u.get("prompt_tokens", 0) or 0)
            completion_tokens = int(u.get("completion_tokens", 0) or 0)
            total_tokens = int(
                u.get("total_tokens", 0) or (prompt_tokens + completion_tokens)
            )

    cost_usd = calculate_completion_cost(
        response,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
    }
