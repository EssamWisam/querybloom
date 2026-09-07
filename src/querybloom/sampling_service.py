"""Reusable orchestration for ABSTAT subgraph sampling."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from querybloom.events import EventSink, emit_event
from querybloom.graph_serialization import patterns_to_cytoscape
from querybloom.mining import SubgraphMiner


DEFAULT_K_DISTRIBUTION = {3: 0.7, 4: 0.2, 5: 0.1}

CLIMATEMODELSKG_SAMPLING_CONFIG = {
    "endpoint": "climatemodelskg",
    "min_support": 5,
    "preprocess": {
        "property_limit": 300,
        "max_triples": 30000,
        "seed_property": "",
        "minimize_patterns": True,
        "rand_offset": True,
        "use_cache": False,
        "include_classes": [],
        "exclude_classes": [],
        "exclude_properties": ["label", "description", "identifier"],
    },
    "mine": {
        "k": {2: 0.1, 3: 0.4, 4: 0.3, 5: 0.2},
        "num_subgraphs": 120,
        "max_subgraphs_per_seed": 3,
        "exact_support": False,
        "verif_timeout": 10,
        "m": 10,
        "num_attrs": [6, 10],
        "uniform_types": False,
    },
}


import logging

_logger = logging.getLogger(__name__)


def _load_endpoint_catalog() -> dict[str, Any]:
    endpoints_path = Path(__file__).resolve().parent / "executor" / "endpoints.json"
    if not endpoints_path.is_file():
        raise FileNotFoundError(f"Endpoints catalog not found at {endpoints_path}")
    with endpoints_path.open() as f:
        return json.load(f)



def _is_frink_endpoint(endpoint: Any) -> bool:
    if isinstance(endpoint, str):
        return True
    if isinstance(endpoint, dict):
        return "url" in endpoint and endpoint.get("frink", True)
    return False


def _is_intuitive_endpoint(endpoint: Any) -> bool:
    return isinstance(endpoint, dict) and endpoint.get("intuitive") is True


def _endpoint_label(endpoint_id: str, endpoint: Any) -> str:
    if isinstance(endpoint, dict):
        return endpoint.get("title") or endpoint_id
    return endpoint_id


def _climatemodelskg_config_for_endpoint(endpoint_id: str) -> dict[str, Any]:
    config = deepcopy(CLIMATEMODELSKG_SAMPLING_CONFIG)
    config["endpoint"] = endpoint_id
    return config


def _frink_sampling_presets() -> dict[str, dict[str, Any]]:
    return {
        endpoint_id: {
            "label": _endpoint_label(endpoint_id, endpoint),
            "config": _climatemodelskg_config_for_endpoint(endpoint_id),
        }
        for endpoint_id, endpoint in _load_endpoint_catalog().items()
        if endpoint_id != "federated"
        and _is_frink_endpoint(endpoint)
        and _is_intuitive_endpoint(endpoint)
    }

SAMPLING_UI_FIELDS = {
    "preset": {
        "label": "Preset",
        "description": "Loads a starter sampling configuration for a known knowledge graph. Choose Custom to edit from scratch.",
    },
    "endpoint": {
        "label": "Endpoint",
        "description": "SPARQL endpoint name or URL the backend will query. Presets use aliases from the backend config.",
    },
    "preprocess.seed_property": {
        "label": "Seed property",
        "description": "Optional predicate URI used to start BFS-style property discovery near a known relation. Leave empty for the normal property scan.",
    },
    "min_support": {
        "label": "Min support",
        "description": "Minimum occurrence count required for a type-predicate-type pattern to be kept.",
    },
    "mine.num_subgraphs": {
        "label": "Subgraphs",
        "description": "Target number of representative subgraphs to mine after ABSTAT preprocessing.",
    },
    "mine.k": {
        "label": "Concept Size",
        "description": "Allowed subgraph sizes by number of types. Use one number or comma-separated sizes.",
    },
    "preprocess.use_cache": {
        "label": "Use cache",
        "description": "Reuse cached property and pattern results when available to avoid re-querying the endpoint.",
    },
    "preprocess.minimize_patterns": {
        "label": "Minimize patterns",
        "description": "Apply paper-style instance-level type minimization. This can be expensive because it may prefetch subclass hierarchies and run additional type checks.",
    },
    "preprocess.property_limit": {
        "label": "Property limit",
        "description": "Maximum number of properties to inspect during preprocessing, or the BFS expansion budget when using a seed property.",
    },
    "mine.k_weights": {
        "label": "Type size weights",
        "description": "Optional comma-separated weights matching the type sizes. They are normalized automatically to bias sampled subgraph sizes.",
    },
    "preprocess.max_triples": {
        "label": "Max triples per property",
        "description": "Maximum triples sampled for each property when estimating pattern counts.",
    },
    "preprocess.include_classes": {
        "label": "Include class prefixes",
        "description": "Only keep patterns whose classes start with one of these comma-separated URI prefixes.",
    },
    "preprocess.exclude_classes": {
        "label": "Exclude class prefixes",
        "description": "Drop patterns whose classes start with one of these comma-separated URI prefixes.",
    },
    "preprocess.exclude_properties": {
        "label": "Exclude property substrings",
        "description": "Skip properties whose URI contains any of these comma-separated substrings.",
    },
}

# Single source of truth for sampling presets. The web UI loads these from
# GET /api/v1/abstat/defaults and must not redefine them.
SAMPLING_PRESETS = {
    "custom": {
        "label": "Custom",
        "config": {
            "endpoint": "",
            "min_support": 10,
            "preprocess": {
                "property_limit": 50,
                "max_triples": 50000,
                "seed_property": "",
                "minimize_patterns": True,
                "rand_offset": False,
                "use_cache": False,
                "include_classes": [],
                "exclude_classes": [],
                "exclude_properties": [],
            },
            "mine": {
                "k": 3,
                "num_subgraphs": 30,
                "max_subgraphs_per_seed": 1,
                "exact_support": False,
                "verif_timeout": 30,
                "m": 7,
                "num_attrs": [5, 9],
                "uniform_types": False,
            },
        },
    },
    "dbpedia-notebook": {
        "label": "DBPedia",
        "config": {
            "endpoint": "dbpedia-qlever",
            "min_support": 100,
            "preprocess": {
                "property_limit": 1500,
                "max_triples": 30000,
                "seed_property": "http://dbpedia.org/ontology/spouse",
                "minimize_patterns": True,
                "rand_offset": True,
                "use_cache": False,
                "include_classes": ["http://dbpedia.org/ontology/"],
                "exclude_classes": [],
                "exclude_properties": ["label", "description", "identifier"],
            },
            "mine": {
                "k": {3: 0.1, 4: 0.3, 5: 0.4, 6: 0.2},
                "num_subgraphs": 500,
                "max_subgraphs_per_seed": 1,
                "exact_support": False,
                "verif_timeout": 20,
                "m": 10,
                "num_attrs": [9, 13],
                "uniform_types": True,
            },
        },
    },
    "dblp-notebook": {
        "label": "DBLP",
        "config": {
            "endpoint": "dblp",
            "min_support": 10,
            "preprocess": {
                "property_limit": 1500,
                "max_triples": 30000,
                "seed_property": "",
                "minimize_patterns": True,
                "rand_offset": True,
                "use_cache": False,
                "include_classes": [],
                "exclude_classes": [],
                "exclude_properties": ["label", "description", "identifier"],
            },
            "mine": {
                "k": {3: 0.1, 4: 0.3, 5: 0.4, 6: 0.2},
                "num_subgraphs": 500,
                "max_subgraphs_per_seed": 1,
                "exact_support": False,
                "verif_timeout": 20,
                "m": 10,
                "num_attrs": [9, 13],
                "uniform_types": True,
            },
        },
    },
    **_frink_sampling_presets(),
}


class SamplingPreprocessConfig(BaseModel):
    property_limit: int = 100000
    max_triples: int = 300000
    exclude_properties: list[str] | None = None
    exclude_classes: list[str] | None = None
    include_classes: list[str] | None = None
    minimize_patterns: bool = True
    seed_property: str | None = None
    rand_offset: bool = False
    use_cache: bool = False
    persist_cache: bool = True


class SamplingMineConfig(BaseModel):
    k: int | tuple[int, int] | dict[int, float] = Field(
        default_factory=lambda: dict(DEFAULT_K_DISTRIBUTION)
    )
    num_subgraphs: int = 120
    exact_support: bool = False
    m: int = 7
    output_dir: str | None = "./subgraphs_output"
    max_subgraphs_per_seed: int = 1
    verif_timeout: int = 30
    prob_optional: float = 0.0
    num_attrs: int | tuple[int, int] = (5, 9)
    max_attr_len: int = 200
    strategy: str = "rand"
    uniform_types: bool = False


class SamplingRunConfig(BaseModel):
    endpoint: str
    min_support: int = 10
    preprocess: SamplingPreprocessConfig = Field(
        default_factory=SamplingPreprocessConfig
    )
    mine: SamplingMineConfig = Field(default_factory=SamplingMineConfig)
    graph_limit: int | None = 1000
    run_id: str | None = None


class SamplingRunResult(BaseModel):
    endpoint: str
    min_support: int
    num_patterns: int
    num_subgraphs: int
    output_path: str | None = None
    ontology_graph: dict[str, Any] | None = None
    subgraphs: list[dict[str, Any]]


def sampling_defaults() -> dict[str, Any]:
    """Return API-friendly defaults matching the legacy sampler script."""
    return SamplingRunConfig(endpoint="").model_dump()


def sampling_ui_metadata() -> dict[str, Any]:
    """Return frontend metadata owned by the backend config surface."""
    return {
        "fields": SAMPLING_UI_FIELDS,
        "presets": deepcopy(SAMPLING_PRESETS),
    }


def run_sampling(
    config: SamplingRunConfig | dict[str, Any],
    event_sink: EventSink | None = None,
    stop_event: Any | None = None,
    skip_event: Any | None = None,
    skip_mining_event: Any | None = None,
) -> SamplingRunResult:
    """Run preprocessing and mining without depending on CLI or notebooks."""
    if not isinstance(config, SamplingRunConfig):
        config = SamplingRunConfig.model_validate(config)

    run_id = config.run_id or str(uuid4())
    bound_event_sink = event_sink
    if event_sink is not None:

        def _with_run_id(event):
            if event.run_id is None:
                event.run_id = run_id
            event_sink(event)

        bound_event_sink = _with_run_id

    emit_event(
        event_sink,
        "run.started",
        "sampling",
        f"Sampling started for {config.endpoint}",
        {"config": config.model_dump()},
        run_id=run_id,
    )

    miner = SubgraphMiner(endpoint=config.endpoint, min_support=config.min_support)

    preprocess_args = config.preprocess.model_dump()
    emit_event(
        event_sink,
        "stage.started",
        "preprocess",
        "ABSTAT preprocessing started",
        preprocess_args,
        run_id=run_id,
    )
    miner.preprocess(**preprocess_args, event_sink=bound_event_sink, skip_event=skip_event)
    emit_event(
        event_sink,
        "stage.completed",
        "preprocess",
        "ABSTAT preprocessing completed",
        {
            "num_patterns": len(miner.patterns),
            "num_attribute_patterns": len(miner.abstat.attribute_patterns),
        },
        run_id=run_id,
    )

    ontology_graph = patterns_to_cytoscape(
        miner.patterns,
        pattern_counts=miner.abstat.pattern_counts,
        type_labels=miner.abstat.type_labels,
        property_labels=miner.abstat.property_labels,
        limit=config.graph_limit,
    )
    emit_event(
        event_sink,
        "graph.updated",
        "ontology",
        "Ontology graph ready",
        {"graph": ontology_graph},
        run_id=run_id,
    )

    if stop_event is not None and stop_event.is_set():
        emit_event(
            event_sink,
            "run.cancelled",
            "sampling",
            "Sampling cancelled before mining",
            run_id=run_id,
        )
        return SamplingRunResult(
            endpoint=config.endpoint,
            min_support=config.min_support,
            num_patterns=len(miner.patterns),
            num_subgraphs=0,
            output_path=miner.last_export_path,
            ontology_graph=ontology_graph,
            subgraphs=[],
        )

    mine_args = config.mine.model_dump()
    emit_event(
        event_sink,
        "stage.started",
        "mining",
        "Subgraph mining started",
        mine_args,
        run_id=run_id,
    )
    subgraphs = miner.mine(
        **mine_args,
        event_sink=bound_event_sink,
        stop_event=stop_event,
        skip_event=skip_mining_event,
    )
    emit_event(
        event_sink,
        "stage.completed",
        "mining",
        "Subgraph mining completed",
        {"num_subgraphs": len(subgraphs), "output_path": miner.last_export_path},
        run_id=run_id,
    )

    result = SamplingRunResult(
        endpoint=config.endpoint,
        min_support=config.min_support,
        num_patterns=len(miner.patterns),
        num_subgraphs=len(subgraphs),
        output_path=miner.last_export_path,
        ontology_graph=ontology_graph,
        subgraphs=subgraphs,
    )
    emit_event(
        event_sink,
        "run.completed",
        "sampling",
        "Sampling completed",
        result.model_dump(exclude={"subgraphs"}),
        run_id=run_id,
    )
    return result
