"""Resolve parsed SPARQL terms against ontology and endpoint evidence."""

from __future__ import annotations

from dataclasses import dataclass

from .config import SparqlEndpoint
from .execution import ExecutionObservation, SparqlTransport
from .ontology import Ontology
from .preprocessing import ParsedQuery

_META_TYPES = frozenset(
    {
        "http://www.w3.org/2002/07/owl#Class",
        "http://www.w3.org/2000/01/rdf-schema#Class",
        "http://www.w3.org/2000/01/rdf-schema#Datatype",
    }
)


@dataclass(frozen=True)
class ResolvedTerms:
    """Entity and class terms resolved from a parsed query."""

    entities: tuple[str, ...]
    classes: frozenset[str]
    evidence_ids: tuple[str, ...]
    degraded: bool


class TermResolver:
    """Classify query entities with ontology and optional endpoint evidence."""

    def __init__(
        self,
        *,
        ontology: Ontology,
        endpoint: SparqlEndpoint | None = None,
        transport: SparqlTransport | None = None,
    ) -> None:
        if (endpoint is None) != (transport is None):
            raise ValueError(
                "classification endpoint and transport must be configured together"
            )
        self.ontology = ontology
        self.endpoint = endpoint
        self.transport = transport
        self._type_cache: dict[str, tuple[frozenset[str] | None, str | None]] = {}
        self._instance_cache: dict[str, tuple[bool | None, str | None]] = {}

    def resolve(self, parsed: ParsedQuery) -> ResolvedTerms:
        classes = set(parsed.syntactic_classes)
        evidence_ids: list[str] = []
        degraded = False

        for entity_uri in dict.fromkeys(parsed.raw_entities):
            if entity_uri in classes:
                continue
            entity_types, type_evidence = self._entity_types(entity_uri)
            if type_evidence is not None:
                evidence_ids.append(type_evidence)
            if entity_types is None:
                degraded = True
            else:
                classes.update(entity_types - _META_TYPES)

            if entity_types is not None and entity_types & _META_TYPES:
                classes.add(entity_uri)
            elif entity_types is not None and not (entity_types - _META_TYPES):
                has_instances, instance_evidence = self._has_instances(entity_uri)
                if instance_evidence is not None:
                    evidence_ids.append(instance_evidence)
                if has_instances is None:
                    degraded = True
                if (
                    has_instances is True
                    or not entity_types
                    and entity_uri in self.ontology.classes
                ):
                    classes.add(entity_uri)
            elif not entity_types and entity_uri in self.ontology.classes:
                classes.add(entity_uri)

        entities = tuple(
            entity_uri
            for entity_uri in parsed.raw_entities
            if entity_uri not in classes
        )
        return ResolvedTerms(
            entities=entities,
            classes=frozenset(classes),
            evidence_ids=tuple(evidence_ids),
            degraded=degraded,
        )

    def _entity_types(
        self, entity_uri: str
    ) -> tuple[frozenset[str] | None, str | None]:
        if entity_uri in self._type_cache:
            return self._type_cache[entity_uri]
        result: tuple[frozenset[str] | None, str | None]
        if self.endpoint is None or self.transport is None:
            result = (None, None)
        else:
            observation = self.transport.execute(
                f"SELECT DISTINCT ?t WHERE {{ <{entity_uri}> a ?t }}",
                endpoint=self.endpoint,
            )
            result = (_types_from_observation(observation), observation.id)
        self._type_cache[entity_uri] = result
        return result

    def _has_instances(self, entity_uri: str) -> tuple[bool | None, str | None]:
        if entity_uri in self._instance_cache:
            return self._instance_cache[entity_uri]
        result: tuple[bool | None, str | None]
        if self.endpoint is None or self.transport is None:
            result = (None, None)
        else:
            observation = self.transport.execute(
                f"ASK {{ ?x a <{entity_uri}> }}", endpoint=self.endpoint
            )
            result = (
                observation.boolean if observation.kind == "ask" else None,
                observation.id,
            )
        self._instance_cache[entity_uri] = result
        return result


def _types_from_observation(
    observation: ExecutionObservation,
) -> frozenset[str] | None:
    if observation.kind != "select":
        return None
    return frozenset(
        binding["value"]
        for row in observation.rows
        if (binding := row.get("t")) is not None and "value" in binding
    )
