"""Native v5 subgraph YAML: compact schema plus grounded instances."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import yaml

from querybloom.abstat.prefixes import PrefixExtractor


def local_name(uri: Optional[str]) -> str:
    if not uri:
        return ""
    value = str(uri).rstrip("/")
    if "#" in value:
        return value.rsplit("#", 1)[-1]
    if "/" in value:
        return value.rsplit("/", 1)[-1]
    if ":" in value:
        return value.rsplit(":", 1)[-1]
    return value


def mark_label(display: str, is_rdfs_label: bool) -> str:
    name = str(display or "").strip()
    if not name:
        return name
    if is_rdfs_label and not name.endswith("^"):
        return f"{name}^"
    return name


def format_value(value: Any, max_attr_len: int = 200) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = "" if value is None else str(value)
    if len(text) > max_attr_len:
        text = f"{text[:max_attr_len]}..."
    return f"'{text}'"


def parse_relationship_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse schema or instance relationship lines in old or v5 arrow form."""
    text = str(line or "").strip()
    if "-->*" in text:
        left, right = text.split("-->*", 1)
        optional = True
    elif "-->" in text:
        left, right = text.split("-->", 1)
        optional = False
    else:
        return None
    if " --" in left:
        source, predicate = left.rsplit(" --", 1)
        predicate = predicate.lstrip("-").strip()
    else:
        parts = left.strip().split(" ", 1)
        source = parts[0] if parts else ""
        predicate = parts[1].strip("- ").strip() if len(parts) > 1 else ""
    source = source.strip()
    target = right.strip()
    if not source or not predicate or not target:
        return None
    return {
        "source": source,
        "predicate": predicate,
        "optional": optional,
        "target": target,
    }


def is_v5_subgraph(subgraph: Mapping[str, Any]) -> bool:
    types = subgraph.get("types")
    return bool(
        subgraph.get("prefixes") is not None
        and isinstance(subgraph.get("relationships"), list)
        and isinstance(types, dict)
        and any(isinstance(value, str) for value in types.values())
    )


def build_subgraph_yaml(
    *,
    subgraph_id: Any,
    support: Any,
    type_uris: Sequence[str],
    type_labels: Mapping[str, str],
    edges: Sequence[Mapping[str, Any]],
    type_attributes: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    instance_rows: Sequence[Mapping[str, Any]] | None = None,
    min_support: Any = None,
    max_attr_len: int = 200,
) -> Dict[str, Any]:
    """Build v5 YAML data from mined types, edges, attributes, and grounded rows."""
    type_uris = [uri for uri in type_uris if uri]
    type_names = {
        uri: type_labels.get(uri) or local_name(uri) for uri in type_uris
    }
    type_attributes = type_attributes or {}
    instance_rows = list(instance_rows or [])
    extractor = PrefixExtractor(
        _collect_uris(type_uris, edges, type_attributes, instance_rows)
    )

    attributes: Dict[str, str] = {}
    for type_uri, attrs in type_attributes.items():
        type_name = type_names.get(type_uri) or local_name(type_uri)
        items = [
            _format_schema_attribute(attr, extractor, min_support)
            for attr in attrs or []
            if attr.get("property")
        ]
        if items:
            attributes[type_name] = " | ".join(items)

    relationships = []
    for edge in edges:
        source = type_names.get(edge.get("s")) or local_name(edge.get("s"))
        target = type_names.get(edge.get("o")) or local_name(edge.get("o"))
        predicate = edge.get("p")
        if not source or not predicate or not target:
            continue
        arrow = "-->*" if edge.get("is_optional") else "-->"
        relationships.append(
            f"{source} --{extractor.compress(predicate)}{arrow} {target}"
        )

    instances: Dict[int, Dict[str, Any]] = {}
    for index, row in enumerate(instance_rows, start=1):
        labels = _row_labels(row)
        rels = []
        for triple in row.get("triples") or []:
            source = triple.get("source")
            predicate = triple.get("predicate")
            target = triple.get("target")
            if not source or not predicate or not target:
                continue
            arrow = "-->*" if triple.get("optional") else "-->"
            rels.append(
                f"{_format_entity(source, labels.get(source), extractor)} "
                f"--{extractor.compress(predicate)}{arrow} "
                f"{_format_entity(target, labels.get(target), extractor)}"
            )
        grouped: Dict[str, List[str]] = {}
        seen: Dict[str, set[str]] = {}
        for attr in row.get("attributes") or []:
            source = attr.get("source")
            if not source:
                continue
            key = _format_entity_name(source, labels.get(source))
            name = mark_label(
                attr.get("property_label") or local_name(attr.get("property")),
                bool(attr.get("label_from_rdfs")),
            )
            identity = attr.get("property") or name
            bucket = seen.setdefault(key, set())
            if identity in bucket:
                continue
            bucket.add(identity)
            grouped.setdefault(key, []).append(
                f"{name}={format_value(attr.get('value'), max_attr_len=max_attr_len)}"
            )
        instances[index] = {
            "relationships": rels,
            "attributes": {
                key: f"({', '.join(parts)})" for key, parts in grouped.items() if parts
            },
        }

    return {
        "subgraph_id": subgraph_id,
        "support": support,
        "prefixes": extractor.prefixes,
        "types": {
            type_names[uri]: extractor.compress(uri) for uri in type_uris
        },
        "attributes": attributes,
        "relationships": relationships,
        "instances": instances,
    }


def dump_subgraph_yaml(subgraph: Mapping[str, Any]) -> str:
    """Serialize a v5 subgraph dict to YAML."""
    return yaml.dump(
        dict(subgraph),
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


def _format_entity(uri: str, label: Optional[str], extractor: PrefixExtractor) -> str:
    return f"{_format_entity_name(uri, label)} ({extractor.compress(uri)})"


def _format_entity_name(uri: str, label: Optional[str]) -> str:
    if label:
        return mark_label(label, True)
    return mark_label(local_name(uri), False)


def _format_schema_attribute(
    attr: Mapping[str, Any], extractor: PrefixExtractor, min_support: Any
) -> str:
    prop = attr["property"]
    label = attr.get("property_label") or local_name(prop)
    name = mark_label(label, bool(attr.get("label_from_rdfs")))
    datatype = attr.get("datatype_label") or local_name(attr.get("datatype")) or "literal"
    optional = attr.get("optional")
    if optional is None:
        optional = _is_optional_support(attr.get("support"), min_support)
    arrow = "-->*" if optional else "-->"
    return f"--{name} ({extractor.compress(prop)}){arrow} {datatype}"


def _is_optional_support(support: Any, min_support: Any) -> bool:
    try:
        return support is not None and min_support is not None and int(support) < int(min_support)
    except (TypeError, ValueError):
        return False


def _row_labels(row: Mapping[str, Any]) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for sample in (row.get("bindings") or {}).values():
        if isinstance(sample, dict) and sample.get("uri") and sample.get("label"):
            labels[sample["uri"]] = sample["label"]
    return labels


def _collect_uris(
    type_uris: Iterable[str],
    edges: Sequence[Mapping[str, Any]],
    type_attributes: Mapping[str, Sequence[Mapping[str, Any]]],
    instance_rows: Sequence[Mapping[str, Any]],
) -> List[str]:
    uris: List[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value:
            uris.append(value)

    for uri in type_uris:
        add(uri)
    for edge in edges:
        add(edge.get("s"))
        add(edge.get("p"))
        add(edge.get("o"))
    for attrs in type_attributes.values():
        for attr in attrs or []:
            add(attr.get("property"))
    for row in instance_rows:
        for sample in (row.get("bindings") or {}).values():
            if isinstance(sample, dict):
                add(sample.get("uri"))
            elif isinstance(sample, str):
                add(sample)
        for triple in row.get("triples") or []:
            add(triple.get("source"))
            add(triple.get("predicate"))
            add(triple.get("target"))
        for attr in row.get("attributes") or []:
            add(attr.get("source"))
            add(attr.get("property"))
    return uris
