"""LiteLLM structured response parsing utilities."""

from __future__ import annotations

import json
from typing import Any, Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def parse_structured_response(response: Any, model_class: Type[T]) -> T:
    """Parse a litellm structured output response into a Pydantic model.

    Anthropic returns structured output via tool-calling, which LiteLLM sometimes
    wraps in a top-level ``{"parameter": {...}}`` envelope. This helper unwraps
    that envelope before validation so OpenAI, Anthropic, and Gemini responses are
    handled uniformly.
    """
    content = response.choices[0].message.content

    # Anthropic may put the payload in tool_calls when content is empty.
    if not content:
        tool_calls = getattr(response.choices[0].message, "tool_calls", None)
        if tool_calls:
            content = tool_calls[0].function.arguments

    if isinstance(content, str):
        parsed = json.loads(content)
    elif isinstance(content, dict):
        parsed = content
    else:
        parsed = json.loads(str(content))

    # Unwrap the Anthropic "parameter" wrapper if present.
    if (
        isinstance(parsed, dict)
        and list(parsed.keys()) == ["parameter"]
        and isinstance(parsed["parameter"], dict)
    ):
        parsed = parsed["parameter"]

    return model_class.model_validate(parsed)
