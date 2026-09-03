"""Core SubgraphMiner class orchestrator."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from querybloom.abstat import ABSTAT_v2
from querybloom.events import EventSink, emit_event
from querybloom.graph_serialization import patterns_to_cytoscape
from querybloom.mining.attributes import (
    find_and_verify_attributes,
    get_attribute_values,
)
from querybloom.mining.candidate import Candidate, compute_k_slots, sample_target_k
from querybloom.mining.instances import (
    sample_entities_for_type,
    sample_subgraph_instances,
)
from querybloom.mining.search import mine_subgraphs
from querybloom.mining.serialization import (
    prepare_subgraph_yaml_data,
    save_all_subgraphs_to_yaml,
)
from querybloom.mining.support import (
    get_entity_labels,
    get_support,
    get_type_label,
)
from querybloom.mining.utils import binding_value, extract_binding_rows
from querybloom.mining.visualization import plot_ontology_graph


class SubgraphMiner:
    """
    Mines connected subgraphs matching minimum support criteria from a Knowledge Graph.
    """

    def __init__(self, endpoint: str, min_support: int = 100):
        self.endpoint = endpoint
        self.min_support = min_support
        self.patterns: List[Tuple[str, str, str]] = []
        self.abstat = ABSTAT_v2(endpoint=endpoint)
        self._type_count_cache: Dict[str, int] = {}
        self.last_export_path: Optional[str] = None
        self.adj: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)

    def preprocess(
        self,
        property_limit: int = 20,
        max_triples: int = 20000,
        exclude_properties: list = None,
        exclude_classes: list = None,
        include_classes: list = None,
        minimize_patterns: bool = True,
        seed_property: str = None,
        rand_offset: bool = False,
        use_cache: bool = True,
        persist_cache: bool = True,
        graph_limit: int | None = None,
        event_sink: EventSink | None = None,
        skip_event: Any | None = None,
    ) -> None:
        """
        Run ABSTAT preprocessing to extract frequent patterns.
        """
        print(f"\n=== Running ABSTAT Preprocessing ===")
        print(
            f"Property limit: {property_limit}, Max triples per property: {max_triples}"
        )
        if seed_property is not None:
            print(f"Seed property (dynamic discovery): {seed_property}")
        if exclude_properties:
            print(f"Excluding properties: {exclude_properties}")
        if exclude_classes:
            print(f"Excluding class prefixes: {exclude_classes}")
        if include_classes:
            print(f"Including only class prefixes (whitelist): {include_classes}")
        if minimize_patterns:
            print(
                "Type minimization: paper-style instance-level (prefetched subclass graph)"
            )
        if not minimize_patterns:
            print(f"Pattern minimization: DISABLED (keeping all patterns)")

        emit_event(
            event_sink,
            "stage.started",
            "abstat.preprocess",
            "ABSTAT preprocessing started",
            {
                "endpoint": self.endpoint,
                "property_limit": property_limit,
                "max_triples": max_triples,
                "min_support": self.min_support,
                "minimize_patterns": minimize_patterns,
                "seed_property": seed_property,
            },
        )

        self.abstat.process_properties(
            property_limit=property_limit,
            max_triples=max_triples,
            exclude_properties=exclude_properties,
            exclude_classes=exclude_classes,
            include_classes=include_classes,
            minimize_patterns=minimize_patterns,
            seed_property=seed_property,
            min_support=self.min_support,
            rand_offset=rand_offset,
            use_cache=use_cache,
            persist_cache=persist_cache,
            graph_limit=graph_limit,
            event_sink=event_sink,
            skip_event=skip_event,
        )

        if not self.abstat.pattern_counts:
            print("WARNING: No patterns found after ABSTAT processing!")
            emit_event(
                event_sink,
                "warning",
                "abstat.preprocess",
                "No patterns found after ABSTAT processing",
            )
            return

        print(f"ABSTAT found {len(self.abstat.pattern_counts)} total patterns")
        self._build_pattern_pool()

        ontology_graph = patterns_to_cytoscape(
            self.patterns,
            pattern_counts=self.abstat.pattern_counts,
            type_labels=self.abstat.type_labels,
            property_labels=self.abstat.property_labels,
        )
        emit_event(
            event_sink,
            "graph.updated",
            "ontology",
            "Pattern pool built",
            {
                "num_patterns": len(self.patterns),
                "graph": ontology_graph,
            },
        )

        print(
            f"Built pattern pool with {len(self.patterns)} patterns (min_support={self.min_support})"
        )
        print("=== ABSTAT Preprocessing Complete ===\n")
        emit_event(
            event_sink,
            "stage.completed",
            "abstat.preprocess",
            "ABSTAT preprocessing completed",
            {"num_patterns": len(self.patterns)},
        )

    def _build_pattern_pool(self) -> None:
        """Build the pool of frequent patterns from ABSTAT results."""
        self.patterns = []
        for (s, p, o), count in self.abstat.pattern_counts.items():
            if count >= self.min_support:
                self.patterns.append((s, p, o))

        self.adj = defaultdict(list)
        for s, p, o in self.patterns:
            pattern = (s, p, o)
            self.adj[s].append(pattern)
            self.adj[o].append(pattern)

    def sample_entities_for_type(
        self, type_uri: str, m: int = 5, timeout: int = 60
    ) -> List[Dict[str, str]]:
        return sample_entities_for_type(
            endpoint=self.endpoint,
            type_uri=type_uri,
            type_count_cache=self._type_count_cache,
            m=m,
            timeout=timeout,
        )

    @staticmethod
    def _binding_value(binding: Any, variable: str) -> Optional[str]:
        return binding_value(binding, variable)

    def _extract_binding_rows(self, result: Dict[str, Any]) -> List[Dict[str, str]]:
        return extract_binding_rows(result)

    def get_entity_labels(
        self, entity_uris: List[str], timeout: int = 10
    ) -> Dict[str, str]:
        return get_entity_labels(
            endpoint=self.endpoint,
            entity_uris=entity_uris,
            timeout=timeout,
        )

    def sample_subgraph_instances(
        self,
        subgraph: Dict[str, Any],
        type_label_cache: Dict[str, str],
        m: int = 5,
        timeout: int = 60,
        max_attr_len: int = 200,
    ) -> List[Dict[str, Any]]:
        return sample_subgraph_instances(
            endpoint=self.endpoint,
            subgraph=subgraph,
            type_label_cache=type_label_cache,
            min_support=self.min_support,
            m=m,
            timeout=timeout,
            max_attr_len=max_attr_len,
        )

    def get_type_label(self, type_uri: str, timeout: int = 10) -> Optional[str]:
        return get_type_label(
            endpoint=self.endpoint,
            type_uri=type_uri,
            abstat_labels=self.abstat.type_labels if hasattr(self, "abstat") else None,
            timeout=timeout,
        )

    def find_and_verify_attributes(
        self,
        type_uris: Set[str],
        num_attrs: int,
        verif_timeout: int = 5,
    ) -> Dict[str, List[Dict[str, Any]]]:
        return find_and_verify_attributes(
            endpoint=self.endpoint,
            attribute_counts=self.abstat.attribute_counts if hasattr(self, "abstat") else {},
            type_uris=type_uris,
            num_attrs=num_attrs,
            verif_timeout=verif_timeout,
            min_support=self.min_support,
            abstat_labels=self.abstat.type_labels if hasattr(self, "abstat") else None,
        )

    def get_attribute_values(
        self,
        entity_uri: str,
        properties: List[str],
        timeout: int = 10,
    ) -> Dict[str, Any]:
        return get_attribute_values(
            endpoint=self.endpoint,
            entity_uri=entity_uri,
            properties=properties,
            timeout=timeout,
        )

    def prepare_subgraph_yaml_data(
        self,
        subgraph: Dict[str, Any],
        index: int,
        m: int = 5,
        max_attr_len: int = 200,
    ) -> Dict[str, Any]:
        return prepare_subgraph_yaml_data(
            subgraph=subgraph,
            index=index,
            endpoint=self.endpoint,
            min_support=self.min_support,
            m=m,
            max_attr_len=max_attr_len,
            abstat_labels=self.abstat.type_labels if hasattr(self, "abstat") else None,
        )

    def save_all_subgraphs_to_yaml(
        self,
        subgraphs_data: List[Dict[str, Any]],
        output_dir: str,
    ) -> str:
        return save_all_subgraphs_to_yaml(
            subgraphs_data=subgraphs_data,
            endpoint=self.endpoint,
            output_dir=output_dir,
        )

    def get_support(
        self,
        types: Set[str],
        edges: List[Tuple[str, str, str]],
        timeout: int = 10,
        pbar: Any = None,
        limit: Optional[int] = None,
    ) -> int:
        return get_support(
            endpoint=self.endpoint,
            types=types,
            edges=edges,
            timeout=timeout,
            pbar=pbar,
            limit=limit,
        )

    @staticmethod
    def _compute_k_slots(k: Union[int, Tuple[int, int], Dict[int, float]], num_subgraphs: int) -> Dict[int, int]:
        return compute_k_slots(k, num_subgraphs)

    @staticmethod
    def _sample_target_k(k_slots: Dict[int, int]) -> Optional[int]:
        return sample_target_k(k_slots)

    def mine(
        self,
        k: Union[int, Tuple[int, int], Dict[int, float]],
        num_subgraphs: int = 5,
        exact_support: bool = False,
        m: int = 5,
        output_dir: Optional[str] = None,
        max_subgraphs_per_seed: int = 1,
        verif_timeout: int = 5,
        prob_optional: float = 0.0,
        num_attrs: Union[int, Tuple[int, int]] = 0,
        max_attr_len: int = 200,
        strategy: str = "rand",
        uniform_types: bool = False,
        event_sink: EventSink | None = None,
        stop_event: Any | None = None,
        skip_event: Any | None = None,
    ) -> List[Dict[str, Any]]:
        subgraphs, export_path = mine_subgraphs(
            endpoint=self.endpoint,
            patterns=self.patterns,
            pattern_counts=self.abstat.pattern_counts,
            type_labels=self.abstat.type_labels,
            property_labels=self.abstat.property_labels,
            attribute_counts=self.abstat.attribute_counts,
            adj=self.adj,
            min_support=self.min_support,
            k=k,
            num_subgraphs=num_subgraphs,
            exact_support=exact_support,
            m=m,
            output_dir=output_dir,
            max_subgraphs_per_seed=max_subgraphs_per_seed,
            verif_timeout=verif_timeout,
            prob_optional=prob_optional,
            num_attrs=num_attrs,
            max_attr_len=max_attr_len,
            strategy=strategy,
            uniform_types=uniform_types,
            event_sink=event_sink,
            stop_event=stop_event,
            skip_event=skip_event,
        )
        self.last_export_path = export_path
        return subgraphs

    def plot(
        self,
        sample: int = 500,
        rankdir: str = "TB",
        format: str = "png",
        view: bool = False,
        filename: str = "ontology_graph",
        include_attributes: bool = False,
        nodesep: float = 0.5,
        ranksep: float = 0.8,
    ) -> Any:
        return plot_ontology_graph(
            patterns=self.patterns,
            pattern_counts=self.abstat.pattern_counts if hasattr(self, "abstat") else {},
            attribute_patterns=self.abstat.attribute_patterns if hasattr(self, "abstat") else set(),
            attribute_counts=self.abstat.attribute_counts if hasattr(self, "abstat") else {},
            sample=sample,
            rankdir=rankdir,
            format=format,
            view=view,
            filename=filename,
            include_attributes=include_attributes,
            nodesep=nodesep,
            ranksep=ranksep,
        )
