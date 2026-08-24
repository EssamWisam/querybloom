"""Complexity augmentation agent for introducing advanced SPARQL constructs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from litellm import completion

from querybloom.llm.client import parse_structured_response
from querybloom.llm.models import ComplexityIntroducerResult
from querybloom.llm.prompts import render_complexity_prompt


def introduce_complexity(
    subgraph_pattern: str,
    qa_pairs: List[Dict[str, Any]],
    model: str,
    complexity_template: Any = None,
    additional_instructions: str = "",
) -> ComplexityIntroducerResult:
    """Call the LLM to augment each QA pair with one non-trivial complexity construct."""
    prompt = render_complexity_prompt(
        subgraph_pattern,
        qa_pairs,
        complexity_template,
        additional_instructions=additional_instructions,
    )
    response = completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=ComplexityIntroducerResult,
        reasoning_effort="high",
    )
    return parse_structured_response(response, ComplexityIntroducerResult)
