"""Question rewording agent for refining natural language phrasing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from litellm import completion

from querybloom.llm.client import parse_structured_response
from querybloom.llm.models import RewordResult
from querybloom.llm.prompts import render_reword_prompt


def reword_questions(
    qa_pairs: List[Dict[str, Any]],
    model: str,
    reword_template: Any = None,
) -> RewordResult:
    """Call the LLM to audit and fix NL question phrasing for the given pairs."""
    prompt = render_reword_prompt(qa_pairs, reword_template)
    response = completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=RewordResult,
        reasoning_effort="high",
    )
    return parse_structured_response(response, RewordResult)
