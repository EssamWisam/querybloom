"""Jinja2 template loading and prompt rendering for LLM QA generation."""

from __future__ import annotations

import copy
import os
import random
from typing import Any, Dict, List, Optional
from jinja2 import Environment, FileSystemLoader, Template

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
_ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_PROMPTS_DIR = os.path.join(_ROOT_DIR, "prompts")


def subsample_subgraph_entities(
    subgraph: Dict[str, Any], ents_ratio: float = 0.4
) -> Dict[str, Any]:
    """
    Randomly subsample sample_entities in each type of the subgraph.

    All types are assumed to have the same number of entities (n). A fraction
    `ents_ratio` of n indices is sampled once and applied uniformly to every
    type, so the LLM always sees a consistent, varied slice rather than the
    fixed head of the list. If a type happens to have fewer entities than a
    sampled index, a random available entity (not already kept) is used as a
    fallback.
    """
    types = subgraph.get("types", {})
    if not types:
        return subgraph

    counts = [len(t.get("sample_entities", [])) for t in types.values()]
    if not counts or max(counts) == 0:
        return subgraph

    max_count = max(counts)
    num_to_keep = max(1, round(max_count * ents_ratio))
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
                fallback_pool = [
                    e for i, e in enumerate(entities) if i not in used and e not in kept
                ]
                if fallback_pool:
                    choice = random.choice(fallback_pool)
                    kept.append(choice)
                    used.add(entities.index(choice))
        type_data["sample_entities"] = kept
    return sg


def _resolve_template_path(filename: str) -> str:
    """Resolve a template file path, checking templates dir, prompts dir, root dir, or direct path."""
    if os.path.isabs(filename) and os.path.isfile(filename):
        return filename

    base = os.path.basename(filename)
    search_paths = [
        os.path.join(_TEMPLATES_DIR, base),
        os.path.join(_PROMPTS_DIR, base),
        os.path.join(_ROOT_DIR, base),
    ]

    for candidate in search_paths:
        if os.path.isfile(candidate):
            return candidate

    if os.path.isfile(filename):
        return os.path.abspath(filename)

    raise FileNotFoundError(f"Template not found: {filename} (searched {', '.join(search_paths)})")


def load_prompt_template(template_path: Optional[str] = None) -> Template:
    """Load and return a compiled Jinja2 template."""
    if template_path is None:
        resolved = _resolve_template_path("generate.jinja")
    else:
        resolved = _resolve_template_path(template_path)

    template_dir = os.path.dirname(resolved)
    template_name = os.path.basename(resolved)

    env = Environment(loader=FileSystemLoader(template_dir))
    return env.get_template(template_name)


def load_verify_template() -> Template:
    """Load the verification Jinja2 template."""
    return load_prompt_template("verify.jinja")


def load_complexity_template() -> Template:
    """Load the complexity introduction Jinja2 template."""
    return load_prompt_template("complexity.jinja")


def load_reword_template() -> Template:
    """Load the question reword Jinja2 template."""
    return load_prompt_template("reword.jinja")


def render_prompt(
    subgraph_pattern: str,
    subgraph_index: int,
    template: Optional[Template] = None,
    focus_entity_qa: bool = False,
    additional_instructions: str = "",
    kg_title: Optional[str] = None,
) -> str:
    """Render the prompt template with the given subgraph pattern."""
    if template is None:
        template = load_prompt_template()

    prompt = template.render(
        subgraph_pattern=subgraph_pattern,
        subgraph_index=subgraph_index,
        focus_entity_qa=focus_entity_qa,
        kg_title=kg_title,
    )
    if additional_instructions.strip():
        prompt = (
            f"{prompt.rstrip()}\n\n"
            f"### Additional Instructions\n{additional_instructions.strip()}\n"
        )
    return prompt


def render_complexity_prompt(
    subgraph_pattern: str,
    qa_pairs: List[Dict[str, Any]],
    complexity_template: Optional[Template] = None,
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


def render_reword_prompt(
    qa_pairs: List[Dict[str, Any]],
    reword_template: Optional[Template] = None,
) -> str:
    """Render the reword prompt with the correct pairs to audit."""
    if reword_template is None:
        reword_template = load_reword_template()
    return reword_template.render(qa_pairs=qa_pairs)


def render_verify_prompt(
    subgraph_pattern: str,
    qa_pairs: List[Dict[str, Any]],
    verify_template: Optional[Template] = None,
    additional_instructions: str = "",
) -> str:
    """Render the verification prompt with subgraph and execution results."""
    if verify_template is None:
        verify_template = load_verify_template()
    prompt = verify_template.render(
        subgraph_pattern=subgraph_pattern, qa_pairs=qa_pairs
    )
    if additional_instructions.strip():
        prompt = (
            f"{prompt.rstrip()}\n\n"
            f"### Additional Instructions\n{additional_instructions.strip()}\n"
        )
    return prompt
