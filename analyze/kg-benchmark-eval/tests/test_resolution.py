from __future__ import annotations

from kg_benchmark_eval import Ontology, SparqlEndpoint
from kg_benchmark_eval.execution import ExecutionObservation
from kg_benchmark_eval.preprocessing import ParsedQuery
from kg_benchmark_eval.resolution import TermResolver


class FakeTransport:
    def __init__(self, types, instances):
        self.types = types
        self.instances = instances
        self.calls = []

    def execute(self, query, *, endpoint):
        self.calls.append(query)
        uri = query.split("<", 1)[1].split(">", 1)[0]
        if query.startswith("SELECT"):
            value = self.types[uri]
            if value is None:
                return ExecutionObservation(kind="failure", error="offline")
            rows = tuple({"t": {"type": "uri", "value": item}} for item in value)
            return ExecutionObservation(kind="select", head_vars=("t",), rows=rows)
        value = self.instances[uri]
        if value is None:
            return ExecutionObservation(kind="failure", error="offline")
        return ExecutionObservation(kind="ask", boolean=value)

    def close(self):
        pass


def parsed(*entities, classes=()):
    return ParsedQuery(
        num_triples=0,
        variables=frozenset(),
        raw_entities=tuple(entities),
        literals=(),
        syntactic_classes=frozenset(classes),
        properties=frozenset(),
        parse_status="ok",
    )


def test_resolver_preserves_order_dependent_class_pool_and_duplicates():
    first = "https://example.org/first"
    implied = "https://example.org/Implied"
    transport = FakeTransport({first: {implied}}, {first: False})
    resolver = TermResolver(
        ontology=Ontology.from_sets(classes=set(), properties=set(), name="example"),
        endpoint=SparqlEndpoint(url="https://example.org/sparql", snapshot_id="s1"),
        transport=transport,
    )

    resolved = resolver.resolve(parsed(first, implied, first))

    assert resolved.classes == frozenset({implied})
    assert resolved.entities == (first, first)
    assert len(transport.calls) == 1


def test_meta_type_and_empty_type_with_true_instance_mark_uri_as_class():
    meta_uri = "https://example.org/meta"
    instance_uri = "https://example.org/instance-class"
    transport = FakeTransport(
        {
            meta_uri: {"http://www.w3.org/2002/07/owl#Class"},
            instance_uri: set(),
        },
        {meta_uri: False, instance_uri: True},
    )
    resolver = TermResolver(
        ontology=Ontology.from_sets(classes=set(), properties=set(), name="example"),
        endpoint=SparqlEndpoint(url="https://example.org/sparql", snapshot_id="s1"),
        transport=transport,
    )

    resolved = resolver.resolve(parsed(meta_uri, instance_uri))

    assert resolved.classes == frozenset({meta_uri, instance_uri})
    assert resolved.entities == ()


def test_failed_lookup_uses_indexed_fallback_and_marks_degraded():
    indexed = "https://example.org/Indexed"
    transport = FakeTransport({indexed: None}, {indexed: None})
    resolver = TermResolver(
        ontology=Ontology.from_sets(
            classes={indexed}, properties=set(), name="example"
        ),
        endpoint=SparqlEndpoint(url="https://example.org/sparql", snapshot_id="s1"),
        transport=transport,
    )

    resolved = resolver.resolve(parsed(indexed))

    assert resolved.classes == frozenset({indexed})
    assert resolved.entities == ()
    assert resolved.degraded is True


def test_no_endpoint_uses_ontology_without_transport():
    indexed = "https://example.org/Indexed"
    resolver = TermResolver(
        ontology=Ontology.from_sets(classes={indexed}, properties=set(), name="example")
    )

    resolved = resolver.resolve(parsed(indexed, indexed))

    assert resolved.classes == frozenset({indexed})
    assert resolved.entities == ()
    assert resolved.degraded is True
