"""LLM package: multi-agent QA generation, SPARQL execution, complexity injection, verification, and rewording."""

from __future__ import annotations

from querybloom.llm.client import parse_structured_response
from querybloom.llm.complexity import introduce_complexity
from querybloom.llm.cost import calculate_completion_cost, extract_usage_and_cost
from querybloom.llm.execution import execute_sparql_and_get_result
from querybloom.llm.generation import (
    generate_and_execute,
    generate_questions_batch,
    generate_questions_single,
)
from querybloom.llm.models import (
    ComplexityAugmentation,
    ComplexityIntroducerResult,
    QuestionQueryPair,
    RewordPairResult,
    RewordResult,
    SubgraphGenerationResult,
    VerificationPairResult,
    VerificationResult,
)
from querybloom.llm.pipeline import (
    process_single_subgraph_pipeline,
    process_subgraphs_data,
    process_subgraphs_yaml,
)
from querybloom.llm.prompts import (
    load_complexity_system_template,
    load_complexity_template,
    load_generate_system_template,
    load_prompt_template,
    load_reword_system_template,
    load_reword_template,
    load_system_template,
    load_verify_system_template,
    load_verify_template,
    render_complexity_messages,
    render_complexity_prompt,
    render_prompt,
    render_prompt_messages,
    render_reword_messages,
    render_reword_prompt,
    render_verify_messages,
    render_verify_prompt,
    subsample_subgraph_entities,
)
from querybloom.llm.reword import reword_questions
from querybloom.llm.verification import verify_qa_pairs

__all__ = [
    "QuestionQueryPair",
    "SubgraphGenerationResult",
    "VerificationPairResult",
    "VerificationResult",
    "ComplexityAugmentation",
    "ComplexityIntroducerResult",
    "RewordPairResult",
    "RewordResult",
    "parse_structured_response",
    "calculate_completion_cost",
    "extract_usage_and_cost",
    "subsample_subgraph_entities",
    "load_prompt_template",
    "load_system_template",
    "load_generate_system_template",
    "load_verify_template",
    "load_verify_system_template",
    "load_complexity_template",
    "load_complexity_system_template",
    "load_reword_template",
    "load_reword_system_template",
    "render_prompt",
    "render_prompt_messages",
    "render_complexity_prompt",
    "render_complexity_messages",
    "render_reword_prompt",
    "render_reword_messages",
    "render_verify_prompt",
    "render_verify_messages",
    "execute_sparql_and_get_result",
    "generate_questions_batch",
    "generate_questions_single",
    "generate_and_execute",
    "introduce_complexity",
    "verify_qa_pairs",
    "reword_questions",
    "process_single_subgraph_pipeline",
    "process_subgraphs_data",
    "process_subgraphs_yaml",
]
