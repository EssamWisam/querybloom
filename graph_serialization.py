"""Graph serializers for ABSTAT ontology and sampled subgraphs."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def short_name(uri: str | None) -> str:
    if not uri:
        return ""
    value = str(uri).rstrip("/>")
    if "#" in value:
        return value.rsplit("#", 1)[-1]
    return value.rsplit("/", 1)[-1]


def _label(uri: str, labels: Mapping[str, str] | None = None) -> str:
    if labels and uri in labels and labels[uri]:
        return labels[uri]
    return short_name(uri)


def _node(uri: str, label: str, kind: str, **extra: Any) -> dict[str, Any]:
    data = {"id": uri, "label": label, "uri": uri, "kind": kind}
    data.update({k: v for k, v in extra.items() if v is not None})
    return {"data": data}


def _edge(
    source: str,
    target: str,
    predicate: str,
    label: str,
    edge_id: str,
    **extra: Any,
) -> dict[str, Any]:
    data = {
        "id": edge_id,
        "source": source,
        "target": target,
        "predicate": predicate,
        "label": label,
        "uri": predicate,
        "kind": "predicate",
    }
    data.update({k: v for k, v in extra.items() if v is not None})
    return {"data": data}


def patterns_to_cytoscape(
    patterns: Iterable[tuple[str, str, str]],
    pattern_counts: Mapping[tuple[str, str, str], int] | None = None,
    type_labels: Mapping[str, str] | None = None,
    property_labels: Mapping[str, str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Serialize ontology patterns into Cytoscape nodes and edges."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    ordered_patterns = list(patterns)
    if limit is not None:
        ordered_patterns = ordered_patterns[:limit]

    for index, pattern in enumerate(ordered_patterns):
        subject, predicate, obj = pattern
        nodes.setdefault(
            subject,
            _node(subject, _label(subject, type_labels), "type"),
        )
        nodes.setdefault(obj, _node(obj, _label(obj, type_labels), "type"))
        count = pattern_counts.get(pattern) if pattern_counts else None
        edges.append(
            _edge(
                subject,
                obj,
                predicate,
                _label(predicate, property_labels),
                f"pattern-{index}",
                support=count,
            )
        )

    return {
        "format": "cytoscape",
        "nodes": list(nodes.values()),
        "edges": edges,
        "elements": {"nodes": list(nodes.values()), "edges": edges},
        "stats": {"nodes": len(nodes), "edges": len(edges)},
    }


def subgraph_to_cytoscape(
    subgraph: Mapping[str, Any],
    type_labels: Mapping[str, str] | None = None,
    property_labels: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Serialize a raw mined subgraph into Cytoscape nodes and edges."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    type_uris = subgraph.get("types", [])

    for type_uri in type_uris:
        nodes.setdefault(
            type_uri,
            _node(type_uri, _label(type_uri, type_labels), "type"),
        )

    for index, edge in enumerate(subgraph.get("edges", [])):
        if isinstance(edge, Mapping):
            subject = edge.get("s")
            predicate = edge.get("p")
            obj = edge.get("o")
            support = edge.get("support")
            is_optional = bool(edge.get("is_optional", False))
        else:
            subject, predicate, obj = edge
            support = None
            is_optional = False

        if not subject or not predicate or not obj:
            continue

        nodes.setdefault(
            subject,
            _node(subject, _label(subject, type_labels), "type"),
        )
        nodes.setdefault(obj, _node(obj, _label(obj, type_labels), "type"))
        edges.append(
            _edge(
                subject,
                obj,
                predicate,
                _label(predicate, property_labels),
                f"subgraph-edge-{index}",
                support=support,
                optional=is_optional,
            )
        )

    return {
        "format": "cytoscape",
        "nodes": list(nodes.values()),
        "edges": edges,
        "elements": {"nodes": list(nodes.values()), "edges": edges},
        "stats": {"nodes": len(nodes), "edges": len(edges)},
    }
