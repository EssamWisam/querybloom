from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

from querybloom.sampling_service import SamplingRunConfig


class LLMRunRequest(BaseModel):
    input_yaml_path: str | None = None
    sample_run_id: str | None = None
    endpoint: str
    model: str = "openai/gpt-5.4"
    template_path: str | None = None
    kg_title: str | None = None
    output_dir: str | None = None
    timeout: int = 70
    max_workers: int = 10
    verify_iterations: int = 0
    max_subgraphs: int | None = None
    subgraph_indices: list[int] | None = None
    focus_entity_qa: bool = False
    ents_ratio: float = 0.4
    additional_instructions: str = ""
    introduce_complexity_step: bool = True
    reword_questions_step: bool = True
    run_id: str | None = None


LLM_UI_FIELDS = {
    "model": {
        "label": "Model",
        "description": "LiteLLM model identifier used by the generation, complexity, verifier, and rewording agents.",
    },
    "verify_iterations": {
        "label": "Verify iterations",
        "description": "How many verifier repair cycles to run. Use 0 to skip verification.",
    },
    "ents_ratio": {
        "label": "Entity sample ratio",
        "description": "Fraction of sampled entities from each subgraph shown to the LLM as examples.",
    },
    "additional_instructions": {
        "label": "Additional instructions",
        "description": "Optional extra prompt guidance appended to the generator, complexity, and verifier agents.",
    },
    "focus_entity_qa": {
        "label": "Entity-focused QA",
        "description": "Bias generation toward questions about concrete sample entities instead of only schema-level relations.",
    },
    "introduce_complexity_step": {
        "label": "Introduce complexity",
        "description": "Run the complexity agent after generation to add SPARQL constructs such as OPTIONAL, FILTER, or aggregations.",
    },
    "reword_questions_step": {
        "label": "Reword questions",
        "description": "Run the rewording agent to remove KG URIs and jargon from natural-language questions.",
    },
    "timeout": {
        "label": "SPARQL timeout (s)",
        "description": "Seconds allowed for each SPARQL execution against the live endpoint during generation and verification.",
    },
    "max_workers": {
        "label": "Parallel workers",
        "description": "How many subgraphs to process in parallel during QA generation.",
    },
    "kg_title": {
        "label": "KG title",
        "description": "Optional knowledge-graph name shown to the LLM for context, for example DBLP or DBpedia.",
    },
}


def llm_ui_metadata() -> dict[str, Any]:
    return {"fields": LLM_UI_FIELDS}


RunKind = Literal["sample", "llm", "chat", "sparql"]
RunStatus = Literal["queued", "running", "completed", "failed", "cancelled", "interrupted"]
ArtifactKind = Literal["yaml", "json", "graph", "subgraphs", "qa", "log", "other"]


class AuthSignupRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None


class AuthLoginRequest(BaseModel):
    email: str
    password: str


class AuthRefreshRequest(BaseModel):
    refresh_token: str


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = None


class RunCreate(BaseModel):
    project_id: str | None = None
    kind: RunKind
    status: RunStatus = "queued"
    title: str | None = None
    kg: str | None = None
    endpoint: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None


class RunUpdate(BaseModel):
    project_id: str | None = None
    kind: RunKind | None = None
    status: RunStatus | None = None
    title: str | None = None
    kg: str | None = None
    endpoint: str | None = None
    config: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class EventCreate(BaseModel):
    event_type: str
    stage: str | None = None
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class ArtifactCreate(BaseModel):
    kind: ArtifactKind = "other"
    label: str | None = None
    storage_bucket: str | None = None
    storage_path: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] | None = None


class SubgraphCreate(BaseModel):
    subgraph_index: int
    support: int | None = None
    num_types: int | None = None
    graph: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class QAPairCreate(BaseModel):
    subgraph_id: str | None = None
    question: str
    sparql_query: str
    execution_result: dict[str, Any] = Field(default_factory=dict)
    verification_status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ABSTATSampleRunRequest(BaseModel):
    project_id: str | None = None
    title: str | None = None
    config: SamplingRunConfig


class ABSTATLLMRunRequest(BaseModel):
    project_id: str | None = None
    title: str | None = None
    request: LLMRunRequest
