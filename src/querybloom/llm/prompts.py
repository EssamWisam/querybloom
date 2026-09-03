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
    """Randomly subsample grounded instances shown to the LLM."""
    instances = subgraph.get("instances")
    if isinstance(instances, dict) and instances:
        keys = sorted(instances, key=lambda key: int(key) if str(key).isdigit() else str(key))
        num_to_keep = max(1, round(len(keys) * ents_ratio))
        kept_keys = sorted(random.sample(keys, min(num_to_keep, len(keys))))
        sg = copy.deepcopy(subgraph)
        sg["instances"] = {
            index + 1: instances[key] for index, key in enumerate(kept_keys)
        }
        return sg

    types = subgraph.get("types", {})
    if not isinstance(types, dict):
        return subgraph
    counts = [
        len(t.get("sample_entities", []))
        for t in types.values()
        if isinstance(t, dict)
    ]
    if not counts or max(counts) == 0:
        return subgraph

    max_count = max(counts)
    num_to_keep = max(1, round(max_count * ents_ratio))
    indices = sorted(random.sample(range(max_count), min(num_to_keep, max_count)))
    sg = copy.deepcopy(subgraph)
    for type_data in sg["types"].values():
        if not isinstance(type_data, dict):
            continue
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
    search_dirs = [_TEMPLATES_DIR, _PROMPTS_DIR, _ROOT_DIR]

    for search_dir in search_dirs:
        path = os.path.join(search_dir, base)
        if os.path.isfile(path):
            return path

    if os.path.isfile(filename):
        return os.path.abspath(filename)

    raise FileNotFoundError(
        f"Template not found: {filename} (searched {', '.join(search_dirs)})"
    )


def load_prompt_template(template_path: Optional[str] = None) -> Template:
    """Load and return a compiled Jinja2 template."""
    if template_path is None:
        resolved = _resolve_template_path("generate_user.jinja")
    else:
        resolved = _resolve_template_path(template_path)

    template_dir = os.path.dirname(resolved)
    template_name = os.path.basename(resolved)

    env = Environment(loader=FileSystemLoader(template_dir))
    return env.get_template(template_name)


def load_system_template(filename: str) -> Template:
    """Load a system prompt Jinja2 template."""
    return load_prompt_template(filename)


def load_generate_system_template(template_path: Optional[str] = None) -> Template:
    """Load the question generation system Jinja2 template."""
    return load_prompt_template(template_path or "generate_system.jinja")


def load_verify_template(template_path: Optional[str] = None) -> Template:
    """Load the verification user Jinja2 template."""
    return load_prompt_template(template_path or "verify_user.jinja")


def load_verify_system_template(template_path: Optional[str] = None) -> Template:
    """Load the verification system Jinja2 template."""
    return load_prompt_template(template_path or "verify_system.jinja")


def load_complexity_template(template_path: Optional[str] = None) -> Template:
    """Load the complexity introduction user Jinja2 template."""
    return load_prompt_template(template_path or "complexity_user.jinja")


def load_complexity_system_template(template_path: Optional[str] = None) -> Template:
    """Load the complexity introduction system Jinja2 template."""
    return load_prompt_template(template_path or "complexity_system.jinja")


def load_reword_template(template_path: Optional[str] = None) -> Template:
    """Load the question reword user Jinja2 template."""
    return load_prompt_template(template_path or "reword_user.jinja")


def load_reword_system_template(template_path: Optional[str] = None) -> Template:
    """Load the question reword system Jinja2 template."""
    return load_prompt_template(template_path or "reword_system.jinja")


def render_prompt_messages(
    subgraph_pattern: str,
    subgraph_index: int,
    template: Optional[Template] = None,
    system_template: Optional[Template] = None,
    focus_entity_qa: bool = False,
    additional_instructions: str = "",
    kg_title: Optional[str] = None,
    kg_description: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Render the generation system and user messages."""
    if system_template is None:
        system_template = load_generate_system_template()
    if template is None:
        template = load_prompt_template()

    system_prompt = system_template.render(focus_entity_qa=focus_entity_qa).strip()
    user_prompt = template.render(
        subgraph_pattern=subgraph_pattern,
        subgraph_index=subgraph_index,
        focus_entity_qa=focus_entity_qa,
        kg_title=kg_title,
        kg_description=kg_description,
    ).strip()

    if additional_instructions.strip():
        user_prompt = (
            f"{user_prompt}\n\n"
            f"### Additional Instructions\n{additional_instructions.strip()}"
        )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def render_prompt(
    subgraph_pattern: str,
    subgraph_index: int,
    template: Optional[Template] = None,
    focus_entity_qa: bool = False,
    additional_instructions: str = "",
    kg_title: Optional[str] = None,
    kg_description: Optional[str] = None,
) -> str:
    """Render the user prompt template with the given subgraph pattern (backward compatible)."""
    if template is None:
        template = load_prompt_template()

    prompt = template.render(
        subgraph_pattern=subgraph_pattern,
        subgraph_index=subgraph_index,
        focus_entity_qa=focus_entity_qa,
        kg_title=kg_title,
        kg_description=kg_description,
    )
    if additional_instructions.strip():
        prompt = (
            f"{prompt.rstrip()}\n\n"
            f"### Additional Instructions\n{additional_instructions.strip()}\n"
        )
    return prompt


def render_complexity_messages(
    subgraph_pattern: str,
    qa_pairs: List[Dict[str, Any]],
    complexity_template: Optional[Template] = None,
    system_template: Optional[Template] = None,
    additional_instructions: str = "",
    kg_title: Optional[str] = None,
    kg_description: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Render the complexity system and user messages."""
    if system_template is None:
        system_template = load_complexity_system_template()
    if complexity_template is None:
        complexity_template = load_complexity_template()

    system_prompt = system_template.render().strip()
    user_prompt = complexity_template.render(
        subgraph_pattern=subgraph_pattern,
        qa_pairs=qa_pairs,
        kg_title=kg_title,
        kg_description=kg_description,
    ).strip()

    if additional_instructions.strip():
        user_prompt = (
            f"{user_prompt}\n\n"
            f"### Additional Instructions\n{additional_instructions.strip()}"
        )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def render_complexity_prompt(
    subgraph_pattern: str,
    qa_pairs: List[Dict[str, Any]],
    complexity_template: Optional[Template] = None,
    additional_instructions: str = "",
    kg_title: Optional[str] = None,
    kg_description: Optional[str] = None,
) -> str:
    """Render the complexity introduction user prompt (backward compatible)."""
    if complexity_template is None:
        complexity_template = load_complexity_template()
    prompt = complexity_template.render(
        subgraph_pattern=subgraph_pattern,
        qa_pairs=qa_pairs,
        kg_title=kg_title,
        kg_description=kg_description,
    )
    if additional_instructions.strip():
        prompt = (
            f"{prompt.rstrip()}\n\n"
            f"### Additional Instructions\n{additional_instructions.strip()}\n"
        )
    return prompt


def render_reword_messages(
    qa_pairs: List[Dict[str, Any]],
    reword_template: Optional[Template] = None,
    system_template: Optional[Template] = None,
) -> List[Dict[str, str]]:
    """Render the reword system and user messages."""
    if system_template is None:
        system_template = load_reword_system_template()
    if reword_template is None:
        reword_template = load_reword_template()

    system_prompt = system_template.render().strip()
    user_prompt = reword_template.render(qa_pairs=qa_pairs).strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def render_reword_prompt(
    qa_pairs: List[Dict[str, Any]],
    reword_template: Optional[Template] = None,
) -> str:
    """Render the reword user prompt (backward compatible)."""
    if reword_template is None:
        reword_template = load_reword_template()
    return reword_template.render(qa_pairs=qa_pairs)


def render_verify_messages(
    subgraph_pattern: str,
    qa_pairs: List[Dict[str, Any]],
    verify_template: Optional[Template] = None,
    system_template: Optional[Template] = None,
    additional_instructions: str = "",
    kg_title: Optional[str] = None,
    kg_description: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Render the verification system and user messages."""
    if system_template is None:
        system_template = load_verify_system_template()
    if verify_template is None:
        verify_template = load_verify_template()

    system_prompt = system_template.render().strip()
    user_prompt = verify_template.render(
        subgraph_pattern=subgraph_pattern,
        qa_pairs=qa_pairs,
        kg_title=kg_title,
        kg_description=kg_description,
    ).strip()

    if additional_instructions.strip():
        user_prompt = (
            f"{user_prompt}\n\n"
            f"### Additional Instructions\n{additional_instructions.strip()}"
        )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def render_verify_prompt(
    subgraph_pattern: str,
    qa_pairs: List[Dict[str, Any]],
    verify_template: Optional[Template] = None,
    additional_instructions: str = "",
    kg_title: Optional[str] = None,
    kg_description: Optional[str] = None,
) -> str:
    """Render the verification user prompt (backward compatible)."""
    if verify_template is None:
        verify_template = load_verify_template()
    prompt = verify_template.render(
        subgraph_pattern=subgraph_pattern,
        qa_pairs=qa_pairs,
        kg_title=kg_title,
        kg_description=kg_description,
    )
    if additional_instructions.strip():
        prompt = (
            f"{prompt.rstrip()}\n\n"
            f"### Additional Instructions\n{additional_instructions.strip()}\n"
        )
    return prompt
