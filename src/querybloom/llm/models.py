"""Pydantic schemas and structured response models for LLM QA generation."""

from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


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
