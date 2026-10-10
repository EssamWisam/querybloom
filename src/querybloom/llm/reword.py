"""Question rewording agent for refining natural language phrasing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union
from litellm import completion

from querybloom.llm.client import litellm_model_kwargs, parse_structured_response
from querybloom.llm.cost import extract_usage_and_cost
from querybloom.llm.models import RewordResult
from querybloom.llm.prompts import render_reword_messages


def reword_questions(
    qa_pairs: List[Dict[str, Any]],
    model: str,
    reword_template: Any = None,
    return_usage: bool = False,
    openrouter_provider: Optional[str] = None,
) -> Union[RewordResult, Tuple[RewordResult, Dict[str, Any]]]:
    """Call the LLM to audit and fix NL question phrasing for the given pairs."""
    messages = render_reword_messages(qa_pairs, reword_template=reword_template)
    call = litellm_model_kwargs(
        model,
        openrouter_provider=openrouter_provider,
    )
    response = completion(
        messages=messages,
        response_format=RewordResult,
        reasoning_effort="high",
        **call,
    )
    result = parse_structured_response(response, RewordResult)
    if return_usage:
        usage = extract_usage_and_cost(response, model=call["model"])
        return result, usage
    return result
