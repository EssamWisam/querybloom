"""Core ABSTAT 2.0 orchestrator class and public facade."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from querybloom.events import EventSink
from querybloom.abstat.cache import patterns_cache_path
from querybloom.abstat.hierarchy import is_subtype, minimal_types, prefetch_subclass_graph
from querybloom.abstat.patterns import (
    compute_minimal_patterns,
    emit_cached_pattern_property_events,
    process_properties,
)
from querybloom.abstat.properties import find_one_connected_property, get_distinct_properties
from querybloom.abstat.visualization import format_pattern_dataframe, plot_schema_graph


class ABSTAT_v2:
    """
    ABSTAT 2.0: Structural profiling and minimal type-pattern extraction for Knowledge Graphs.
    """

    def __init__(self, endpoint: str = "sockg"):
        self.endpoint = endpoint
        self.is_wikidata = "wikidata" in str(endpoint).lower()
        self.supertype_cache: dict[str, set[str]] = {}  # Cache: Type -> Set[Supertypes]
        self.subclass_graph: dict[str, set[str]] = defaultdict(set)  # subClass -> set(superClass)
        self.prefetch_subclass: bool = False
        self.subclass_prefetched: bool = False
        self.patterns: set[tuple[str, str, str]] = set()  # Minimal Type Patterns (C, P, D)
        self.pattern_counts: dict[tuple[str, str, str], int] = defaultdict(int)
        self.attribute_patterns: set[tuple[str, str, str]] = set()  # (C, P, LiteralType)
        self.attribute_counts: dict[tuple[str, str, str], int] = defaultdict(int)
        self.property_labels: dict[str, str] = {}  # Cache: PropertyURI -> Label
        self.type_labels: dict[str, str] = {}  # Cache: TypeURI -> Label
        # Resolve to project root cache directory (misc/querybloom/cache)
        self.cache_dir: Path = Path(__file__).resolve().parents[3] / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._property_triple_count_cache: dict[str, int] = {}  # Cache: predicate -> total triple count

    def prefetch_subclass_graph(
        self,
        use_cache: bool = True,
        persist_cache: bool = True,
        skip_event: Any | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        """
        Prefetches global subclass edges once and caches them on disk.
        Used to make is_subtype checks local during minimization.
        """
        graph, prefetched = prefetch_subclass_graph(
            endpoint=self.endpoint,
            cache_dir=self.cache_dir,
            is_wikidata=self.is_wikidata,
            use_cache=use_cache,
            persist_cache=persist_cache,
            skip_event=skip_event,
            event_sink=event_sink,
        )
        self.subclass_graph = graph
        self.subclass_prefetched = prefetched

    def _minimal_types(self, asserted_types: Iterable[str]) -> set[str]:
        """
        Given a set of asserted types, return the subset that are minimal
        (no strict subtype exists in the set). Paper-faithful instance-level minimization.
        """
        return minimal_types(
            asserted_types=asserted_types,
            is_subtype_fn=self.is_subtype,
        )

    def is_subtype(self, t1: str, t2: str) -> bool:
        """
        Returns True if t1 is a subtype of t2.
        Optimized: Fetches ALL supertypes of t1 once and caches them.
        """
        return is_subtype(
            t1=t1,
            t2=t2,
            subclass_graph=self.subclass_graph,
            supertype_cache=self.supertype_cache,
            endpoint=self.endpoint,
            is_wikidata=self.is_wikidata,
            prefetch_subclass=self.prefetch_subclass,
            subclass_prefetched=self.subclass_prefetched,
        )

    def get_distinct_properties(
        self,
        limit: int | None = None,
        frequency: bool = True,
        use_cache: bool = True,
        persist_cache: bool = True,
        event_sink: EventSink | None = None,
    ) -> list[tuple[str, int | None, str | None]]:
        """
        Fetches properties from the endpoint.
        If frequency=True, orders by occurrence count (slower).
        If frequency=False, just fetches distinct properties (faster).
        Returns list of (property_uri, count, label).
        """
        return get_distinct_properties(
            endpoint=self.endpoint,
            cache_dir=self.cache_dir,
            is_wikidata=self.is_wikidata,
            limit=limit,
            frequency=frequency,
            use_cache=use_cache,
            persist_cache=persist_cache,
            event_sink=event_sink,
        )

    def _emit_cached_pattern_property_events(
        self,
        event_sink: EventSink | None,
        *,
        cache_path: Path,
    ) -> None:
        emit_cached_pattern_property_events(
            event_sink=event_sink,
            patterns=self.patterns,
            attribute_patterns=self.attribute_patterns,
            property_labels=self.property_labels,
            type_labels=self.type_labels,
            cache_path=cache_path,
        )

    def find_one_connected_property(
        self,
        known_types: set[str],
        remaining_uris: set[str] | None = None,
        exclude_uris: set[str] | None = None,
    ) -> str | None:
        """
        Find a single unprocessed property connected to any of the known types.
        """
        return find_one_connected_property(
            endpoint=self.endpoint,
            is_wikidata=self.is_wikidata,
            known_types=known_types,
            remaining_uris=remaining_uris,
            exclude_uris=exclude_uris,
        )

    def process_properties(
        self,
        property_limit: int = 20,
        max_triples: int = 20000,
        exclude_properties: Sequence[str] | None = None,
        exclude_classes: Sequence[str] | None = None,
        include_classes: Sequence[str] | None = None,
        minimize_patterns: bool = True,
        seed_property: str | None = None,
        min_support: int = 1,
        rand_offset: bool = False,
        use_cache: bool = True,
        persist_cache: bool = True,
        graph_limit: int | None = None,
        event_sink: EventSink | None = None,
        skip_event: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Core ABSTAT 2.0 Logic:
        Iterates over frequent properties and fetches type pairs directly.
        When minimize_patterns=True, uses paper-faithful instance-level minimization.
        """
        process_properties(
            abstat_instance=self,
            property_limit=property_limit,
            max_triples=max_triples,
            exclude_properties=exclude_properties,
            exclude_classes=exclude_classes,
            include_classes=include_classes,
            minimize_patterns=minimize_patterns,
            seed_property=seed_property,
            min_support=min_support,
            rand_offset=rand_offset,
            use_cache=use_cache,
            persist_cache=persist_cache,
            graph_limit=graph_limit,
            event_sink=event_sink,
            skip_event=skip_event,
            **kwargs,
        )

    def compute_minimal_patterns(
        self,
        predicate: str,
        max_triples: int,
        min_support: int,
        exclude_class_prefixes: Sequence[str] | None = None,
        include_class_prefixes: Sequence[str] | None = None,
        pbar: Any | None = None,
        rand_offset: bool = False,
    ) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], int], set[str]]:
        """
        Paper-style instance-level minimization.
        For each entity, keeps only its most specific asserted types,
        then rebuilds pattern counts from minimal type assignments.
        """
        return compute_minimal_patterns(
            endpoint=self.endpoint,
            is_wikidata=self.is_wikidata,
            predicate=predicate,
            max_triples=max_triples,
            min_support=min_support,
            property_triple_count_cache=self._property_triple_count_cache,
            minimal_types_fn=self._minimal_types,
            exclude_class_prefixes=exclude_class_prefixes,
            include_class_prefixes=include_class_prefixes,
            pbar=pbar,
            rand_offset=rand_offset,
        )

    def plot_schema_graph(
        self,
        exclude_properties: Sequence[str] | None = None,
        max_edges: int | None = None,
    ) -> None:
        """
        Plots the schema graph derived from minimal type patterns.
        C — P —> D
        """
        plot_schema_graph(
            patterns=self.patterns,
            type_labels=self.type_labels,
            property_labels=self.property_labels,
            exclude_properties=exclude_properties,
            max_edges=max_edges,
        )

    def print_data(self) -> pd.DataFrame:
        """
        Returns a DataFrame of patterns, sorted by properties with the fewest combinations first.
        """
        return format_pattern_dataframe(
            pattern_counts=self.pattern_counts,
            type_labels=self.type_labels,
            property_labels=self.property_labels,
        )
