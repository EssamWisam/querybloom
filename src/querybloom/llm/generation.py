"""Question and query generation agents for subgraph patterns."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from litellm import batch_completion, completion

from querybloom.events import EventSink, emit_event
from querybloom.llm.client import parse_structured_response
from querybloom.llm.execution import execute_sparql_and_get_result
from querybloom.llm.models import SubgraphGenerationResult
from querybloom.llm.prompts import load_prompt_template, render_prompt


def generate_questions_batch(
    subgraph_patterns: List[str],
    model: str = "gpt-5",
    template_path: str = None,
    focus_entity_qa: bool = False,
    additional_instructions: str = "",
    kg_title: Optional[str] = None,
) -> List[SubgraphGenerationResult]:
    """
    Generate question-query pairs for multiple subgraphs using batch completion.
    """
    template = load_prompt_template(template_path)

    messages_batch = []
    for i, pattern in enumerate(subgraph_patterns):
        prompt = render_prompt(
            pattern,
            i,
            template,
            focus_entity_qa=focus_entity_qa,
            additional_instructions=additional_instructions,
            kg_title=kg_title,
        )
        messages_batch.append([{"role": "user", "content": prompt}])

    responses = batch_completion(
        model=model,
        messages=messages_batch,
        response_format=SubgraphGenerationResult,
    )

    results = []
    for response in responses:
        content = response.choices[0].message.content
        result = SubgraphGenerationResult.model_validate_json(content)
        results.append(result)

    return results


def generate_questions_single(
    subgraph_pattern: str,
    model: str = "gpt-5",
    template_path: str = None,
    focus_entity_qa: bool = False,
    additional_instructions: str = "",
    kg_title: Optional[str] = None,
) -> SubgraphGenerationResult:
    """
    Generate question-query pairs for a single subgraph.
    """
    results = generate_questions_batch(
        [subgraph_pattern],
        model=model,
        template_path=template_path,
        focus_entity_qa=focus_entity_qa,
        additional_instructions=additional_instructions,
        kg_title=kg_title,
    )
    return results[0]


def generate_and_execute(
    subgraph: Dict[str, Any],
    subgraph_index: int,
    endpoint: str,
    model: str,
    template: Any,
    timeout: int,
    fail_empty: bool,
    pattern_str: str,
    focus_entity_qa: bool,
    additional_instructions: str = "",
    event_sink: EventSink | None = None,
    kg_title: Optional[str] = None,
) -> Tuple[SubgraphGenerationResult, List[Dict[str, Any]]]:
    """Generate QA pairs and execute them. Returns (gen_result, qa_pairs_dicts)."""
    prompt = render_prompt(
        pattern_str,
        subgraph_index,
        template,
        focus_entity_qa=focus_entity_qa,
        additional_instructions=additional_instructions,
        kg_title=kg_title,
    )
    emit_event(
        event_sink,
        "stage.started",
        "llm.generate",
        f"Generating questions for subgraph {subgraph_index}",
        {"subgraph_index": subgraph_index, "model": model},
    )
    response = completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=SubgraphGenerationResult,
        reasoning_effort="high",
    )
    gen_result = parse_structured_response(response, SubgraphGenerationResult)
    emit_event(
        event_sink,
        "stage.completed",
        "llm.generate",
        f"Generated questions for subgraph {subgraph_index}",
        {
            "subgraph_index": subgraph_index,
            "is_meaningful": gen_result.is_meaningful,
            "num_questions": len(gen_result.questions),
            "questions": [q.model_dump() for q in gen_result.questions],
        },
    )

    qa_pairs = []
    if gen_result.is_meaningful:
        for qa_index, qa in enumerate(gen_result.questions):
            emit_event(
                event_sink,
                "stage.started",
                "sparql.execute",
                f"Executing generated query {qa_index + 1}",
                {
                    "subgraph_index": subgraph_index,
                    "qa_index": qa_index,
                    "question": qa.text_query,
                    "sparql_query": qa.sparql_query,
                },
            )
            exec_result = execute_sparql_and_get_result(
                qa.sparql_query,
                endpoint=endpoint,
                timeout=timeout,
                fail_empty=fail_empty,
            )
            emit_event(
                event_sink,
                "stage.completed",
                "sparql.execute",
                f"Executed generated query {qa_index + 1}",
                {
                    "subgraph_index": subgraph_index,
                    "qa_index": qa_index,
                    "execution_results": exec_result,
                },
            )
            qa_pairs.append(
                {
                    "question": qa.text_query,
                    "sparql_query": qa.sparql_query,
                    "execution_results": exec_result,
                    "original_question": qa.text_query,
                    "original_sparql_query": qa.sparql_query,
                }
            )
    return gen_result, qa_pairs
