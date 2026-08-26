"""Verification agent for auditing generated question-query pairs and applying fixes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union
from litellm import completion

from querybloom.llm.client import parse_structured_response
from querybloom.llm.cost import extract_usage_and_cost
from querybloom.llm.models import VerificationResult
from querybloom.llm.prompts import render_verify_prompt


def verify_qa_pairs(
    subgraph_pattern: str,
    qa_pairs: List[Dict[str, Any]],
    model: str,
    verify_template: Any = None,
    additional_instructions: str = "",
    return_usage: bool = False,
) -> Union[VerificationResult, Tuple[VerificationResult, Dict[str, Any]]]:
    """Call the LLM to verify executed QA pairs and return structured result."""
    prompt = render_verify_prompt(
        subgraph_pattern,
        qa_pairs,
        verify_template,
        additional_instructions=additional_instructions,
    )
    response = completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=VerificationResult,
        reasoning_effort="high",
    )
    result = parse_structured_response(response, VerificationResult)
    if return_usage:
        usage = extract_usage_and_cost(response, model=model)
        return result, usage
    return result
