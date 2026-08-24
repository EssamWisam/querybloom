"""Disk caching utilities and filename builders for ABSTAT."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence


def get_safe_endpoint_name(endpoint: str) -> str:
    """Convert an endpoint URL or name to a filesystem-safe string."""
    return str(endpoint).replace("/", "_").replace(":", "_").replace(".", "_")


def subclass_cache_path(cache_dir: Path, endpoint: str) -> Path:
    """Return cache filepath for pre-fetched subclass graph."""
    safe_endpoint = get_safe_endpoint_name(endpoint)
    return cache_dir / f"subclass_edges_{safe_endpoint}.json"


def properties_cache_path(
    cache_dir: Path,
    endpoint: str,
    limit: int | None,
    frequency: bool,
) -> Path:
    """Return cache filepath for distinct or frequency-ranked properties."""
    safe_endpoint = get_safe_endpoint_name(endpoint)
    return cache_dir / f"props_{safe_endpoint}_lim{limit}_freq{frequency}.json"


def patterns_cache_path(
    cache_dir: Path,
    endpoint: str,
    property_limit: int,
    max_triples: int,
    minimize_patterns: bool,
    min_support: int,
    exclude_properties: Sequence[str] | None = None,
    exclude_classes: Sequence[str] | None = None,
    include_classes: Sequence[str] | None = None,
    seed_property: str | None = None,
) -> Path:
    """Return cache filepath for discovered type patterns."""
    safe_endpoint = get_safe_endpoint_name(endpoint)
    exclude_key = "_".join(sorted(exclude_properties)) if exclude_properties else "none"
    exclude_hash = hashlib.md5(exclude_key.encode()).hexdigest()[:8]

    classes_key = "_".join(sorted(exclude_classes)) if exclude_classes else "none"
    classes_hash = hashlib.md5(classes_key.encode()).hexdigest()[:8]

    include_key = "_".join(sorted(include_classes)) if include_classes else "none"
    include_hash = hashlib.md5(include_key.encode()).hexdigest()[:8]

    seed_tag = (
        f"_seed{hashlib.md5(seed_property.encode()).hexdigest()[:8]}"
        if seed_property is not None
        else ""
    )

    filename = (
        f"patterns_{safe_endpoint}_lim{property_limit}_max{max_triples}_"
        f"min{minimize_patterns}_ms{min_support}_ex{exclude_hash}_cl{classes_hash}_"
        f"inc{include_hash}_paper{seed_tag}.json"
    )
    return cache_dir / filename


def load_json_file(path: Path) -> Any:
    """Read and decode JSON from a file path."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_file(path: Path, data: Any, indent: int | None = None) -> None:
    """Encode and write JSON to a file path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent)
