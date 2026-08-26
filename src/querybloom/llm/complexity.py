"""Complexity augmentation agent for introducing advanced SPARQL constructs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union
from litellm import completion

from querybloom.llm.client import parse_structured_response
from querybloom.llm.cost import extract_usage_and_cost
from querybloom.llm.models import ComplexityIntroducerResult
from querybloom.llm.prompts import render_complexity_messages


def introduce_complexity(
    subgraph_pattern: str,
    qa_pairs: List[Dict[str, Any]],
    model: str,
    complexity_template: Any = None,
    additional_instructions: str = "",
    return_usage: bool = False,
    kg_title: Optional[str] = None,
    kg_description: Optional[str] = None,
) -> Union[ComplexityIntroducerResult, Tuple[ComplexityIntroducerResult, Dict[str, Any]]]:
    """Call the LLM to augment each QA pair with one non-trivial complexity construct."""
    messages = render_complexity_messages(
        subgraph_pattern,
        qa_pairs,
        complexity_template=complexity_template,
        additional_instructions=additional_instructions,
        kg_title=kg_title,
        kg_description=kg_description,
    )
    response = completion(
        model=model,
        messages=messages,
        response_format=ComplexityIntroducerResult,
        reasoning_effort="high",
    )
    result = parse_structured_response(response, ComplexityIntroducerResult)
    if return_usage:
        usage = extract_usage_and_cost(response, model=model)
        return result, usage
    return result
