"""
LLM utilities for generating question-query pairs from subgraph patterns.
Uses litellm with structured output and batch completion.
"""

from typing import List, Literal, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from pydantic import BaseModel, Field
from litellm import batch_completion, completion
from jinja2 import Environment, FileSystemLoader, Template
import os
import yaml
from tqdm import tqdm

from querybloom.events import EventSink, emit_event
from querybloom.executor.sparql_executor import execute_sparql_query as execute




class QuestionQueryPair(BaseModel):
    """A single generated question with its corresponding SPARQL query."""

    text_query: str = Field(description="Natural language question")
    sparql_query: str = Field(description="Corresponding SPARQL query")


class SubgraphGenerationResult(BaseModel):
    """Result of generating questions for a single subgraph."""

    is_meaningful: bool = Field(
        description="Whether the subgraph allows for meaningful questions about the knowledge graph"
    )
    questions: List[QuestionQueryPair] = Field(
        default_factory=list,
        description="List of generated question-query pairs (empty if is_meaningful is False)",
    )


class VerificationPairResult(BaseModel):
    """Verification result for a single QA pair."""

    status: Literal["correct", "needs_fix"] = Field(
        description="Whether the pair is correct or needs fixing"
    )
    reason: str = Field(default="", description="Brief explanation if needs_fix")
    fixed_text_query: Optional[str] = Field(
        default=None, description="Fixed natural language question (only if needs_fix)"
    )
    fixed_sparql_query: Optional[str] = Field(
        default=None, description="Fixed SPARQL query (only if needs_fix)"
    )


class VerificationResult(BaseModel):
    """Aggregated verification result for all QA pairs of a subgraph."""

    all_correct: bool = Field(description="True only if every pair is correct")
    pairs: List[VerificationPairResult] = Field(
        description="Per-pair verification results, aligned with input order"
    )
    most_meaningful_index: int = Field(
        description="1-based index of the single most meaningful and informative question-query pair"
    )


class ComplexityAugmentation(BaseModel):
    """Complexity augmentation result for a single QA pair."""

    skipped: bool = Field(
        description="True if no meaningful non-trivial complexity can be added to this pair"
    )
    skip_reason: str = Field(
        default="", description="Explanation of why augmentation was skipped"
    )
    complexity_types: Optional[
        List[
            Literal[
                "FILTER",
                "OPTIONAL",
                "UNION",
                "ORDER_BY_LIMIT",
                "EXISTS",
                "SUBQUERY",
                "PROPERTY_PATH",
            ]
        ]
    ] = Field(
        default=None,
        description="The types of complexities introduced (null if skipped)",
    )
    augmented_text_query: Optional[str] = Field(
        default=None,
        description="Rewritten NL question reflecting all added complexities",
    )
    augmented_sparql_query: Optional[str] = Field(
        default=None,
        description="Rewritten SPARQL query encoding all added complexities",
    )


class ComplexityIntroducerResult(BaseModel):
    """Result of the complexity introduction step for all QA pairs of a subgraph."""

    augmentations: List[ComplexityAugmentation] = Field(
        description="One augmentation entry per input QA pair, in the same order"
    )


class RewordPairResult(BaseModel):
    """Reword audit result for a single NL question."""

    status: Literal["clean", "needs_reword"] = Field(
        description="Whether the question is clean or needs rewording"
    )
    reason: str = Field(
        default="", description="Brief and short explanation if needs_reword"
    )
    reworded_text_query: Optional[str] = Field(
        default=None,
        description="Reworded natural language question (only if needs_reword)",
    )


class RewordResult(BaseModel):
    """Aggregated reword result for all QA pairs of a subgraph."""

    pairs: List[RewordPairResult] = Field(
        description="Per-pair reword results, aligned with input order"
    )


def subsample_subgraph_entities(
    subgraph: Dict[str, Any], ents_ratio: float = 0.4
) -> Dict[str, Any]:
    """
    Randomly subsample sample_entities in each type of the subgraph.

    All types are assumed to have the same number of entities (n). A fraction
    `ents_ratio` of n indices is sampled once and applied uniformly to every
    type, so the LLM always sees a consistent, varied slice rather than the
    fixed head of the list.  If a type happens to have fewer entities than a
    sampled index, a random available entity (not already kept) is used as a
    fallback.
    """
    import copy, random

    types = subgraph.get("types", {})
    if not types:
        return subgraph

    counts = [len(t.get("sample_entities", [])) for t in types.values()]
    if not counts or max(counts) == 0:
        return subgraph

    max_count = max(counts)
    num_to_keep = max(1, round(max_count * ents_ratio))
    # Sample indices in [0, max_count) — freshly every call, so different
    # subgraphs that share a class will naturally get different entities.
    indices = sorted(random.sample(range(max_count), min(num_to_keep, max_count)))

    sg = copy.deepcopy(subgraph)
    for type_data in sg["types"].values():
        entities = type_data.get("sample_entities", [])
        if not entities:
            continue
        kept = []
        used = set()
        for idx in indices:
            if idx < len(entities):
                kept.append(entities[idx])
                used.add(idx)
            else:
                # Fallback: pick any entity not already selected
                fallback_pool = [
                    e for i, e in enumerate(entities) if i not in used and e not in kept
                ]
                if fallback_pool:
                    choice = random.choice(fallback_pool)
                    kept.append(choice)
                    used.add(entities.index(choice))
        type_data["sample_entities"] = kept
    return sg


def load_prompt_template(template_path: Optional[str] = None) -> Template:
    """Load and return a compiled Jinja2 template."""
    if template_path is None:
        template_path = os.path.join(os.path.dirname(__file__), "generate.jinja")

    template_dir = os.path.dirname(template_path)
    template_name = os.path.basename(template_path)

    env = Environment(loader=FileSystemLoader(template_dir))
    return env.get_template(template_name)


def render_prompt(
    subgraph_pattern: str,
    subgraph_index: int,
    template: Optional[Template] = None,
    focus_entity_qa: bool = False,
    additional_instructions: str = "",
) -> str:
    """Render the prompt template with the given subgraph pattern."""
    if template is None:
        template = load_prompt_template()

    prompt = template.render(
        subgraph_pattern=subgraph_pattern,
        subgraph_index=subgraph_index,
        focus_entity_qa=focus_entity_qa,
    )
    if additional_instructions.strip():
        prompt = (
            f"{prompt.rstrip()}\n\n"
            f"### Additional Instructions\n{additional_instructions.strip()}\n"
        )
    return prompt


def _parse_structured_response(response, model_class: type):
    """Parse a litellm response into a Pydantic model.

    Anthropic returns structured output via tool-calling, which LiteLLM sometimes
    wraps in a top-level ``{"parameter": {...}}`` envelope.  This helper unwraps
    that envelope before validation so both OpenAI and Anthropic responses are
    handled uniformly.
    """
    import json

    content = response.choices[0].message.content

    # Anthropic may put the actual payload in tool_calls when content is empty.
    if not content:
        tool_calls = getattr(response.choices[0].message, "tool_calls", None)
        if tool_calls:
            content = tool_calls[0].function.arguments

    parsed = json.loads(content)
    # Unwrap the Anthropic "parameter" wrapper if present.
    if (
        isinstance(parsed, dict)
        and list(parsed.keys()) == ["parameter"]
        and isinstance(parsed["parameter"], dict)
    ):
        parsed = parsed["parameter"]
    return model_class.model_validate(parsed)


def load_verify_template():
    """Load the verification Jinja2 template."""
    path = os.path.join(os.path.dirname(__file__), "verify.jinja")
    return load_prompt_template(path)


def load_complexity_template():
    """Load the complexity introduction Jinja2 template."""
    path = os.path.join(os.path.dirname(__file__), "complexity.jinja")
    return load_prompt_template(path)


def render_complexity_prompt(
    subgraph_pattern: str,
    qa_pairs: List[Dict],
    complexity_template=None,
    additional_instructions: str = "",
) -> str:
    """Render the complexity introduction prompt with subgraph and executed pairs."""
    if complexity_template is None:
        complexity_template = load_complexity_template()
    prompt = complexity_template.render(
        subgraph_pattern=subgraph_pattern, qa_pairs=qa_pairs
    )
    if additional_instructions.strip():
        prompt = (
            f"{prompt.rstrip()}\n\n"
            f"### Additional Instructions\n{additional_instructions.strip()}\n"
        )
    return prompt


def introduce_complexity(
    subgraph_pattern: str,
    qa_pairs: List[Dict],
    model: str,
    complexity_template=None,
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
    return _parse_structured_response(response, ComplexityIntroducerResult)


def load_reword_template():
    """Load the question reword Jinja2 template."""
    path = os.path.join(os.path.dirname(__file__), "reword.jinja")
    return load_prompt_template(path)


def render_reword_prompt(qa_pairs: List[Dict], reword_template=None) -> str:
    """Render the reword prompt with the correct pairs to audit."""
    if reword_template is None:
        reword_template = load_reword_template()
    return reword_template.render(qa_pairs=qa_pairs)


def reword_questions(
    qa_pairs: List[Dict],
    model: str,
    reword_template=None,
) -> RewordResult:
    """Call the LLM to audit and fix NL question phrasing for the given pairs."""
    prompt = render_reword_prompt(qa_pairs, reword_template)
    response = completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=RewordResult,
        reasoning_effort="high",
    )
    return _parse_structured_response(response, RewordResult)


def render_verify_prompt(
    subgraph_pattern: str,
    qa_pairs: List[Dict],
    verify_template=None,
    additional_instructions: str = "",
) -> str:
    """Render the verification prompt with subgraph and execution results."""
    if verify_template is None:
        verify_template = load_verify_template()
    prompt = verify_template.render(subgraph_pattern=subgraph_pattern, qa_pairs=qa_pairs)
    if additional_instructions.strip():
        prompt = (
            f"{prompt.rstrip()}\n\n"
            f"### Additional Instructions\n{additional_instructions.strip()}\n"
        )
    return prompt


def verify_qa_pairs(
    subgraph_pattern: str,
    qa_pairs: List[Dict],
    model: str,
    verify_template=None,
    additional_instructions: str = "",
) -> VerificationResult:
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
    return _parse_structured_response(response, VerificationResult)


def _generate_and_execute(
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
) -> tuple:
    """Generate QA pairs and execute them. Returns (gen_result, qa_pairs_dicts)."""
    prompt = render_prompt(
        pattern_str,
        subgraph_index,
        template,
        focus_entity_qa=focus_entity_qa,
        additional_instructions=additional_instructions,
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
    gen_result = _parse_structured_response(response, SubgraphGenerationResult)
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


def process_single_subgraph_pipeline(
    subgraph: Dict[str, Any],
    subgraph_index: int,
    endpoint: str,
    model: str,
    template: Any,
    timeout: int,
    fail_empty: bool = True,
    verify_iterations: int = 0,
    verify_template: Any = None,
    focus_entity_qa: bool = False,
    ents_ratio: float = 0.4,
    additional_instructions: str = "",
    introduce_complexity_step: bool = True,
    complexity_template: Any = None,
    reword_questions_step: bool = True,
    reword_template: Any = None,
    event_sink: EventSink | None = None,
) -> Dict[str, Any]:
    """
    Process a single subgraph: Generate questions -> Execute SPARQL -> (optional) Complexity Introduction -> (optional) Verify -> (optional) Reword.

    Args:
        verify_iterations: Number of verification rounds (0 = no verification, behaves as before).
            1 = generate, execute, verify & mark but don't re-generate.
            N>1 = up to N-1 re-generation attempts on failure; last verify is final.
        introduce_complexity_step: If True, run the complexity introducer after initial generation
            and before the verifier. Each pair is augmented with one non-trivial complexity
            construct (FILTER, OPTIONAL, UNION, ORDER_BY_LIMIT, EXISTS, or SUBQUERY).
        reword_questions_step: If True, audit NL questions for KG terminology / URI leakage
            and rewrite only the question text of clean (correct) pairs.
    """
    emit_event(
        event_sink,
        "subgraph.started",
        "llm.subgraph",
        f"Processing subgraph {subgraph_index}",
        {"subgraph_index": subgraph_index},
    )
    subgraph_for_prompt = subsample_subgraph_entities(subgraph, ents_ratio=ents_ratio)
    pattern_str = yaml.dump(
        subgraph_for_prompt, default_flow_style=False, sort_keys=False
    )
    emit_event(
        event_sink,
        "prompt.ready",
        "llm.prompt",
        f"Prompt pattern ready for subgraph {subgraph_index}",
        {"subgraph_index": subgraph_index, "pattern": pattern_str},
    )

    # --- Initial generate + execute ---
    gen_result, qa_pairs = _generate_and_execute(
        subgraph,
        subgraph_index,
        endpoint,
        model,
        template,
        timeout,
        fail_empty,
        pattern_str,
        focus_entity_qa,
        additional_instructions,
        event_sink,
    )

    output_sg = dict(subgraph)
    output_sg["is_meaningful"] = gen_result.is_meaningful

    # --- Complexity introduction step ---
    if introduce_complexity_step and gen_result.is_meaningful and qa_pairs:
        emit_event(
            event_sink,
            "stage.started",
            "llm.complexity",
            f"Introducing complexity for subgraph {subgraph_index}",
            {"subgraph_index": subgraph_index, "num_pairs": len(qa_pairs)},
        )
        ci_result = introduce_complexity(
            pattern_str,
            qa_pairs,
            model,
            complexity_template,
            additional_instructions=additional_instructions,
        )
        for i, aug in enumerate(ci_result.augmentations):
            if aug.skipped or i >= len(qa_pairs):
                continue
            exec_result = execute_sparql_and_get_result(
                aug.augmented_sparql_query,
                endpoint=endpoint,
                timeout=timeout,
                fail_empty=fail_empty,
            )
            qa_pairs[i]["question"] = aug.augmented_text_query
            qa_pairs[i]["sparql_query"] = aug.augmented_sparql_query
            qa_pairs[i]["execution_results"] = exec_result
            qa_pairs[i]["complexity_types"] = aug.complexity_types
        emit_event(
            event_sink,
            "stage.completed",
            "llm.complexity",
            f"Complexity step completed for subgraph {subgraph_index}",
            {
                "subgraph_index": subgraph_index,
                "augmentations": [a.model_dump() for a in ci_result.augmentations],
            },
        )

    # No verification requested — original behaviour
    if verify_iterations == 0 or not gen_result.is_meaningful:
        if reword_questions_step and gen_result.is_meaningful and qa_pairs:
            emit_event(
                event_sink,
                "stage.started",
                "llm.reword",
                f"Rewording questions for subgraph {subgraph_index}",
                {"subgraph_index": subgraph_index, "num_pairs": len(qa_pairs)},
            )
            rw_result = reword_questions(qa_pairs, model, reword_template)
            for idx, rw in enumerate(rw_result.pairs):
                if (
                    idx < len(qa_pairs)
                    and rw.status == "needs_reword"
                    and rw.reworded_text_query
                ):
                    qa_pairs[idx]["pre_reword_question"] = qa_pairs[idx]["question"]
                    qa_pairs[idx]["question"] = rw.reworded_text_query
                    qa_pairs[idx]["reword_reason"] = rw.reason
            emit_event(
                event_sink,
                "stage.completed",
                "llm.reword",
                f"Rewording completed for subgraph {subgraph_index}",
                {
                    "subgraph_index": subgraph_index,
                    "pairs": [p.model_dump() for p in rw_result.pairs],
                },
            )
        output_sg["qa_pairs"] = qa_pairs
        emit_event(
            event_sink,
            "subgraph.completed",
            "llm.subgraph",
            f"Completed subgraph {subgraph_index}",
            {"subgraph_index": subgraph_index, "result": output_sg},
        )
        return output_sg

    # --- Verification loop ---
    for qa in qa_pairs:
        qa["pre_verify_question"] = qa["question"]
        qa["pre_verify_sparql_query"] = qa["sparql_query"]
    for iteration in range(1, verify_iterations + 1):
        emit_event(
            event_sink,
            "stage.started",
            "llm.verify",
            f"Verification cycle {iteration} for subgraph {subgraph_index}",
            {"subgraph_index": subgraph_index, "iteration": iteration},
        )
        v_result = verify_qa_pairs(
            pattern_str,
            qa_pairs,
            model,
            verify_template,
            additional_instructions=additional_instructions,
        )
        emit_event(
            event_sink,
            "stage.completed",
            "llm.verify",
            f"Verification cycle {iteration} completed for subgraph {subgraph_index}",
            {
                "subgraph_index": subgraph_index,
                "iteration": iteration,
                "verification": v_result.model_dump(),
            },
        )

        # Annotate each pair with verification result
        for i, qa in enumerate(qa_pairs):
            pair_v = v_result.pairs[i] if i < len(v_result.pairs) else None
            status = pair_v.status if pair_v else "correct"
            qa["verification_status"] = status
            qa["verification_reason"] = pair_v.reason if pair_v else ""
            qa.setdefault("verification_status_by_cycle", []).append(status)

        if v_result.all_correct or iteration == verify_iterations:
            break

        # Apply fixes and re-execute only the fixed pairs
        for i, qa in enumerate(qa_pairs):
            pair_v = v_result.pairs[i] if i < len(v_result.pairs) else None
            if pair_v and pair_v.status == "needs_fix":
                qa["question"] = pair_v.fixed_text_query or qa["question"]
                qa["sparql_query"] = pair_v.fixed_sparql_query or qa["sparql_query"]
                qa["execution_results"] = execute_sparql_and_get_result(
                    qa["sparql_query"],
                    endpoint=endpoint,
                    timeout=timeout,
                    fail_empty=fail_empty,
                )

    output_sg["qa_pairs"] = qa_pairs
    output_sg["finalized_at_iteration"] = iteration
    output_sg["verification_status"] = (
        "correct" if v_result.all_correct else "needs_fix"
    )
    output_sg["most_meaningful_index"] = v_result.most_meaningful_index
    # Mark the chosen pair directly for easy downstream access
    chosen = v_result.most_meaningful_index - 1  # convert to 0-based
    if 0 <= chosen < len(qa_pairs):
        qa_pairs[chosen]["is_most_meaningful"] = True

    # --- Question reword step ---
    if reword_questions_step and qa_pairs:
        correct_indices = [
            i
            for i, qa in enumerate(qa_pairs)
            if qa.get("verification_status", "correct") == "correct"
        ]
        correct_pairs = [qa_pairs[i] for i in correct_indices]
        if correct_pairs:
            emit_event(
                event_sink,
                "stage.started",
                "llm.reword",
                f"Rewording correct questions for subgraph {subgraph_index}",
                {"subgraph_index": subgraph_index, "num_pairs": len(correct_pairs)},
            )
            rw_result = reword_questions(correct_pairs, model, reword_template)
            for ci, rw in zip(correct_indices, rw_result.pairs):
                if rw.status == "needs_reword" and rw.reworded_text_query:
                    qa_pairs[ci]["pre_reword_question"] = qa_pairs[ci]["question"]
                    qa_pairs[ci]["question"] = rw.reworded_text_query
                    qa_pairs[ci]["reword_reason"] = rw.reason
            emit_event(
                event_sink,
                "stage.completed",
                "llm.reword",
                f"Rewording completed for subgraph {subgraph_index}",
                {
                    "subgraph_index": subgraph_index,
                    "pairs": [p.model_dump() for p in rw_result.pairs],
                },
            )

    emit_event(
        event_sink,
        "subgraph.completed",
        "llm.subgraph",
        f"Completed subgraph {subgraph_index}",
        {"subgraph_index": subgraph_index, "result": output_sg},
    )
    return output_sg


def generate_questions_batch(
    subgraph_patterns: List[str],
    model: str = "gpt-5",
    template_path: str = None,
    focus_entity_qa: bool = False,
    additional_instructions: str = "",
) -> List[SubgraphGenerationResult]:
    """
    Generate question-query pairs for multiple subgraphs using batch completion.

    Args:
        subgraph_patterns: List of YAML subgraph pattern strings
        model: LLM model to use (default: gpt-4o-mini)
        template_path: Path to the Jinja2 template (default: generate.jinja)

    Returns:
        List of SubgraphGenerationResult for each subgraph
    """
    template = load_prompt_template(template_path)

    # Prepare messages for batch completion
    messages_batch = []
    for i, pattern in enumerate(subgraph_patterns):
        prompt = render_prompt(
            pattern,
            i,
            template,
            focus_entity_qa=focus_entity_qa,
            additional_instructions=additional_instructions,
        )
        messages_batch.append([{"role": "user", "content": prompt}])

    # Call batch_completion with structured output
    responses = batch_completion(
        model=model,
        messages=messages_batch,
        response_format=SubgraphGenerationResult,
        # reasoning_effort="high",
    )

    # Parse responses
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
) -> SubgraphGenerationResult:
    """
    Generate question-query pairs for a single subgraph.

    Args:
        subgraph_pattern: YAML subgraph pattern string
        subgraph_index: Index of the subgraph (for prompt rendering)
        model: LLM model to use (default: gpt-4o-mini)
        template_path: Path to the Jinja2 template (default: generate.jinja)

    Returns:
        SubgraphGenerationResult with is_meaningful flag and questions
    """
    results = generate_questions_batch(
        [subgraph_pattern],
        model=model,
        template_path=template_path,
        focus_entity_qa=focus_entity_qa,
        additional_instructions=additional_instructions,
    )
    return results[0]


def execute_sparql_and_get_result(
    sparql_query: str,
    endpoint: str,
    timeout: int = 30,
    fail_empty: bool = True,
) -> Dict[str, Any]:
    """
    Execute a SPARQL query and return execution results.

    Args:
        sparql_query: The SPARQL query to execute
        endpoint: SPARQL endpoint URL
        timeout: Query timeout in seconds
        fail_empty: If True, set success=False when result count is 0 (default: True)

    Returns:
        Dict with success, count, error_message, and result_preview
    """
    res = execute(sparql_query, endpoint=endpoint, timeout=timeout)

    execution_result = {
        "success": res.get("success", False),
        "count": 0,
        "error_message": res.get("error", "") or "",
        "result_preview": None,
    }

    if res.get("success"):
        results = res.get("results", [])

        # Handle DataFrame results
        if hasattr(results, "to_dict") and callable(getattr(results, "to_dict")):
            records = results.to_dict("records")
            execution_result["count"] = len(records)
            # Get column names and top 3 rows
            if records:
                columns = list(records[0].keys())
                preview_rows = records[:5]
                execution_result["result_preview"] = {
                    "columns": columns,
                    "rows": preview_rows,
                }
        # Handle list of bindings
        elif isinstance(results, list):
            execution_result["count"] = len(results)
            if results:
                # Extract column names from first result
                first = results[0]
                if isinstance(first, dict):
                    columns = list(first.keys())
                    # Extract values for preview
                    preview_rows = []
                    for row in results[:5]:
                        preview_row = {}
                        for k, v in row.items():
                            if isinstance(v, dict) and "value" in v:
                                preview_row[k] = v["value"]
                            else:
                                preview_row[k] = v
                        preview_rows.append(preview_row)
                    execution_result["result_preview"] = {
                        "columns": columns,
                        "rows": preview_rows,
                    }
        # Handle dict with nested results
        elif isinstance(results, dict) and "results" in results:
            bindings = results["results"].get("bindings", [])
            execution_result["count"] = len(bindings)
            if bindings:
                columns = list(bindings[0].keys())
                preview_rows = []
                for row in bindings[:5]:
                    preview_row = {k: v.get("value", "") for k, v in row.items()}
                    preview_rows.append(preview_row)
                execution_result["result_preview"] = {
                    "columns": columns,
                    "rows": preview_rows,
                }

    if fail_empty and execution_result["count"] == 0:
        execution_result["success"] = False

    return execution_result


def process_subgraphs_data(
    subgraphs: List[Dict[str, Any]],
    endpoint: str,
    model: str = "gpt-5",
    template_path: str = None,
    output_dir: str = None,
    timeout: int = 70,
    max_workers: int = 10,
    fail_empty: bool = False,
    verify_iterations: int = 0,
    max_subgraphs: int = None,
    subgraph_indices: List[int] | None = None,
    focus_entity_qa: bool = False,
    ents_ratio: float = 0.4,
    additional_instructions: str = "",
    introduce_complexity_step: bool = True,
    reword_questions_step: bool = True,
    input_label: str = "in-memory",
    input_filename: str = "subgraphs.yaml",
    event_sink: EventSink | None = None,
) -> tuple[List[Dict[str, Any]], str | None]:
    """
    Process subgraphs in memory, generate questions, execute queries,
    and optionally save the results to YAML.

    Args:
        subgraphs: Subgraphs to process
        endpoint: SPARQL endpoint URL for query execution
        model: LLM model to use for question generation
        template_path: Path to the Jinja2 template
        output_dir: Output directory. When omitted, results stay in memory only.
        timeout: Query execution timeout in seconds
        max_workers: Maximum number of parallel workers for query execution (default: 10)
        fail_empty: If True, mark execution as failed if 0 results (default: True)

    Returns:
        Tuple of processed subgraphs and optional output YAML path
    """
    indexed_subgraphs = list(enumerate(subgraphs))
    if subgraph_indices is not None:
        requested = {int(index) for index in subgraph_indices}
        indexed_subgraphs = [
            (index, subgraph)
            for index, subgraph in indexed_subgraphs
            if index in requested
        ]

    if (
        subgraph_indices is None
        and max_subgraphs is not None
        and max_subgraphs < len(indexed_subgraphs)
    ):
        import random

        indexed_subgraphs = random.sample(indexed_subgraphs, max_subgraphs)

    subgraphs = [subgraph for _, subgraph in indexed_subgraphs]

    output_path = None
    if output_dir is not None:
        os.makedirs(output_dir, exist_ok=True)

        base, ext = os.path.splitext(os.path.basename(input_filename))
        if not ext:
            ext = ".yaml"
        model_slug = (
            model.split("/")[-1].replace(".", "").replace("-", "").replace("_", "").lower()
        )
        base_with_model = f"{base}-{model_slug}"
        output_path = os.path.join(output_dir, f"{base_with_model}{ext}")
        if os.path.exists(output_path):
            counter = 1
            while os.path.exists(
                os.path.join(output_dir, f"{base_with_model}-{counter}{ext}")
            ):
                counter += 1
            output_path = os.path.join(output_dir, f"{base_with_model}-{counter}{ext}")

    # Load templates once
    template = load_prompt_template(template_path)
    v_template = load_verify_template() if verify_iterations > 0 else None
    c_template = load_complexity_template() if introduce_complexity_step else None
    rw_template = load_reword_template() if reword_questions_step else None

    label = "Gen + Exec"
    if introduce_complexity_step:
        label += " + Complexity"
    if verify_iterations > 0:
        label += f" + Verify(×{verify_iterations})"
    if reword_questions_step:
        label += " + Reword"
    print(
        f"Processing {len(indexed_subgraphs)} subgraphs [{label}] with {max_workers} workers..."
    )
    emit_event(
        event_sink,
        "run.started",
        "llm.batch",
        "LLM subgraph processing started",
        {
            "input_source": input_label,
            "endpoint": endpoint,
            "model": model,
            "num_subgraphs": len(indexed_subgraphs),
            "subgraph_indices": [index for index, _ in indexed_subgraphs],
            "max_workers": max_workers,
            "label": label,
        },
    )

    output_subgraphs = [None] * len(indexed_subgraphs)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(
                process_single_subgraph_pipeline,
                sg,
                source_index,
                endpoint,
                model,
                template,
                timeout,
                fail_empty,
                verify_iterations,
                v_template,
                focus_entity_qa,
                ents_ratio,
                additional_instructions,
                introduce_complexity_step,
                c_template,
                reword_questions_step,
                rw_template,
                event_sink,
            ): (output_index, source_index)
            for output_index, (source_index, sg) in enumerate(indexed_subgraphs)
        }

        # Use as_completed for progress bar for the entire pipeline
        for future in tqdm(
            as_completed(future_to_index),
            total=len(subgraphs),
            desc="Pipeline Progress (Gen + Exec)",
        ):
            output_index, source_index = future_to_index[future]
            try:
                result = future.result()
                result["source_subgraph_index"] = source_index
                output_subgraphs[output_index] = result
                emit_event(
                    event_sink,
                    "subgraph.completed",
                    "llm.batch",
                    f"Stored result for subgraph {source_index}",
                    {"subgraph_index": source_index, "result": result},
                )
            except Exception as e:
                # Handle failure for a single subgraph
                print(f"Error processing subgraph {source_index}: {e}")
                source_subgraph = indexed_subgraphs[output_index][1]
                output_subgraphs[output_index] = {
                    **source_subgraph,
                    "is_meaningful": False,
                    "error": str(e),
                    "qa_pairs": [],
                    "source_subgraph_index": source_index,
                }
                emit_event(
                    event_sink,
                    "error",
                    "llm.batch",
                    f"Error processing subgraph {source_index}",
                    {"subgraph_index": source_index, "error": str(e)},
                )

    if output_path is not None:
        with open(output_path, "w") as f:
            yaml.dump(
                output_subgraphs,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    # --- Correctness summary (only when verification was requested) ---
    if verify_iterations > 0:
        print("\n── Verification Summary ──")
        from collections import defaultdict

        for it in range(1, verify_iterations + 1):
            correct = 0
            total = 0
            for sg in output_subgraphs:
                if sg is None or sg.get("finalized_at_iteration") is None:
                    continue
                for qa in sg.get("qa_pairs", []):
                    history = qa.get("verification_status_by_cycle", [])
                    if it <= len(history):
                        status = history[it - 1]
                    else:
                        # Subgraph finalized before this cycle (all_correct=True), so all pairs were correct
                        status = "correct"
                    total += 1
                    correct += int(status == "correct")
            rate = f"{correct}/{total} ({100*correct/total:.1f}%)" if total else "—"
            print(f"  After cycle {it}: {rate} pairs correct")
        print("──────────────────────────")

    emit_event(
        event_sink,
        "run.completed",
        "llm.batch",
        "LLM subgraph processing completed",
        {
            "output_path": output_path,
            "num_subgraphs": len(output_subgraphs),
            "subgraph_indices": [index for index, _ in indexed_subgraphs],
        },
    )
    return output_subgraphs, output_path


def process_subgraphs_yaml(
    input_yaml_path: str,
    endpoint: str,
    model: str = "gpt-5",
    template_path: str = None,
    output_dir: str = None,
    timeout: int = 70,
    max_workers: int = 10,
    fail_empty: bool = False,
    verify_iterations: int = 0,
    max_subgraphs: int = None,
    subgraph_indices: List[int] | None = None,
    focus_entity_qa: bool = False,
    ents_ratio: float = 0.4,
    additional_instructions: str = "",
    introduce_complexity_step: bool = True,
    reword_questions_step: bool = True,
    event_sink: EventSink | None = None,
) -> str:
    """Backward-compatible file-based wrapper around process_subgraphs_data."""
    with open(input_yaml_path, "r") as f:
        subgraphs = yaml.safe_load(f)

    if output_dir is None:
        input_dir = os.path.dirname(input_yaml_path)
        output_dir = os.path.join(input_dir, "qa_output")

    _, output_path = process_subgraphs_data(
        subgraphs=subgraphs,
        endpoint=endpoint,
        model=model,
        template_path=template_path,
        output_dir=output_dir,
        timeout=timeout,
        max_workers=max_workers,
        fail_empty=fail_empty,
        verify_iterations=verify_iterations,
        max_subgraphs=max_subgraphs,
        subgraph_indices=subgraph_indices,
        focus_entity_qa=focus_entity_qa,
        ents_ratio=ents_ratio,
        additional_instructions=additional_instructions,
        introduce_complexity_step=introduce_complexity_step,
        reword_questions_step=reword_questions_step,
        input_label=input_yaml_path,
        input_filename=os.path.basename(input_yaml_path),
        event_sink=event_sink,
    )
    assert output_path is not None
    return output_path
