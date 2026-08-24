from collections import deque, defaultdict
import time
import random
import os
import yaml
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Set, Tuple, Dict, Any, Optional, Union
from tqdm import tqdm
from querybloom.abstat_2 import ABSTAT_v2
from querybloom.events import EventSink, emit_event
from querybloom.graph_serialization import patterns_to_cytoscape, subgraph_to_cytoscape
from querybloom.executor.sparql_executor import execute_sparql_query as execute



@dataclass
class Candidate:
    """A candidate subgraph on the DFS stack."""

    types: set
    edges: list
    est_support: int
    is_verified: bool
    seed_pattern: tuple
    has_optional: bool
    target_k: Optional[int] = None


class SubgraphMiner:
    def __init__(self, endpoint: str, min_support: int = 100):
        """
        Initialize SubgraphMiner with SPARQL endpoint.

        Args:
            endpoint: SPARQL endpoint URL
            min_support: Minimum support threshold for patterns
        """
        self.endpoint = endpoint
        self.min_support = min_support
        self.patterns = []
        self.abstat = ABSTAT_v2(endpoint=endpoint)
        self._type_count_cache: Dict[str, int] = {}
        self.last_export_path: Optional[str] = None

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
        skip_event=None,
    ):
        """
        Run ABSTAT preprocessing to extract frequent patterns.
        This must be called before mining.

        Args:
            property_limit: Number of top properties to analyze (also used as limit for pattern extraction when seed_property is provided)
            max_triples: Maximum triples to sample per property
            exclude_properties: List of property URIs or short names to exclude (e.g., ['label', 'http://www.w3.org/2000/01/rdf-schema#label'])
            exclude_classes: List of URI prefixes — any type/class whose URI starts with one of these prefixes
                will be excluded before pattern processing (e.g. ['http://www.wikidata.org', 'http://schema.org'])
            include_classes: List of URI prefixes — ONLY types starting with one of these are kept
                (whitelist; cleaner alternative to a growing exclude_classes blacklist)
                (e.g. ['http://dbpedia.org/ontology/'])
            minimize_patterns: If False, skip minimization (faster but redundant patterns).
                When True, uses paper-faithful instance-level minimization with prefetched subclass graph.
            seed_property: If provided (URI), start pattern extraction from this seed property using dynamic
                discovery. No need to fetch properties beforehand. property_limit becomes the extraction limit.
            rand_offset: If True, counts total triples per property (cached) and uses a random OFFSET
                so that each run samples a different region of each property's triple space.
                Useful for large KGs like DBpedia where the default LIMIT always returns alphabetically-first entities.
            use_cache: If False, bypass on-disk ABSTAT preprocess caches for this run.
            persist_cache: If False, do not write refreshed ABSTAT preprocess caches for this run.
            graph_limit: Optional cap for graph serialization size when streaming live ontology updates.
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

        # Run ABSTAT processing
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

        # Check if we have patterns
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

        # Build pattern pool
        print(f"ABSTAT found {len(self.abstat.pattern_counts)} total patterns")

        # Build pattern pool
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

    def _build_pattern_pool(self):
        """
        Build the pool of frequent patterns from ABSTAT results.
        Filters patterns by min_support and allows self-loops.
        """
        self.patterns = []

        # We assume abstat.pattern_counts is populated (i.e. process_properties called)
        # We allow self-loops (S==O) as k types don't need to be distinct
        for (s, p, o), count in self.abstat.pattern_counts.items():
            if count >= self.min_support:
                self.patterns.append((s, p, o))

        # Adjacency for fast extension lookup
        self.adj = defaultdict(list)
        for s, p, o in self.patterns:
            pattern = (s, p, o)
            self.adj[s].append(pattern)
            self.adj[o].append(pattern)

    def sample_entities_for_type(
        self, type_uri: str, m: int = 5, timeout: int = 60
    ) -> List[Dict[str, str]]:
        """
        Sample m entities of a given type from the knowledge graph.
        Returns a list of dicts with 'uri' and optionally 'label'.
        """

        def _extract_entity_uris(result):
            uris = []
            bindings = result.get("results", [])
            if hasattr(bindings, "to_dict") and callable(getattr(bindings, "to_dict")):
                records = bindings.to_dict("records")
                for rec in records:
                    uri = rec.get("entity")
                    if uri:
                        uris.append(uri)
            elif isinstance(bindings, list):
                for b in bindings:
                    uri = b.get("entity", {}).get("value", "")
                    if uri:
                        uris.append(uri)
            elif isinstance(bindings, dict) and "results" in bindings:
                for b in bindings["results"].get("bindings", []):
                    uri = b.get("entity", {}).get("value", "")
                    if uri:
                        uris.append(uri)
            return uris

        # --- COUNT + random OFFSET sampling ---
        # Get (or cache) the total number of distinct entities of this type.
        if type_uri not in self._type_count_cache:
            count_query = f"""
            SELECT (COUNT(DISTINCT ?entity) AS ?count) WHERE {{
                ?entity a <{type_uri}> .
            }}
            """
            count_res = execute(count_query, endpoint=self.endpoint, timeout=timeout)
            total = 0
            if count_res.get("success"):
                try:
                    bindings = count_res.get("results", [])
                    if hasattr(bindings, "to_dict") and callable(
                        getattr(bindings, "to_dict")
                    ):
                        total = int(bindings.to_dict("records")[0].get("count", 0))
                    elif isinstance(bindings, list) and bindings:
                        total = int(bindings[0].get("count", {}).get("value", 0))
                    elif isinstance(bindings, dict) and "results" in bindings:
                        total = int(
                            bindings["results"]["bindings"][0]["count"]["value"]
                        )
                except Exception:
                    total = 0
            self._type_count_cache[type_uri] = total

        total = self._type_count_cache[type_uri]
        offset = random.randint(0, max(0, total - m)) if total > m else 0

        primary_query = f"""
        SELECT DISTINCT ?entity WHERE {{
            ?entity a <{type_uri}> .
        }}
        LIMIT {m}
        OFFSET {offset}
        """
        res = execute(primary_query, endpoint=self.endpoint, timeout=timeout)

        if not res.get("success"):
            print(
                f"[sample_entities] Primary query failed for {type_uri}: "
                f"status={res.get('status')}, error={res.get('error')}"
            )

        entity_uris = _extract_entity_uris(res) if res.get("success") else []
        if not entity_uris:
            print(
                f"[sample_entities] Primary query returned 0 rows for {type_uri}. "
                f"status={res.get('status')}, error={res.get('error')}, exec_time={res.get('execution_time')}"
            )
            return []

        values_clause = " ".join(f"<{uri}>" for uri in entity_uris)
        labels_query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?entity ?lbl WHERE {{
            VALUES ?entity {{ {values_clause} }}
            ?entity rdfs:label ?lbl .
            FILTER(LANG(?lbl) = "en" || LANG(?lbl) = "")
        }}
        """

        labels_res = execute(labels_query, endpoint=self.endpoint, timeout=timeout)
        label_map = {}
        if labels_res.get("success"):
            bindings = labels_res.get("results", [])
            if hasattr(bindings, "to_dict") and callable(getattr(bindings, "to_dict")):
                records = bindings.to_dict("records")
                for rec in records:
                    uri = rec.get("entity")
                    label = rec.get("lbl")
                    if uri and label:
                        label_map.setdefault(uri, label)
            elif isinstance(bindings, list):
                for b in bindings:
                    uri = b.get("entity", {}).get("value", "")
                    label = b.get("lbl", {}).get("value")
                    if uri and label:
                        label_map.setdefault(uri, label)
            elif isinstance(bindings, dict) and "results" in bindings:
                for b in bindings["results"].get("bindings", []):
                    uri = b.get("entity", {}).get("value", "")
                    label = b.get("lbl", {}).get("value")
                    if uri and label:
                        label_map.setdefault(uri, label)
        else:
            print(
                f"[sample_entities] Label query failed for {type_uri}: "
                f"status={labels_res.get('status')}, error={labels_res.get('error')}"
            )

        entities = []
        for uri in entity_uris:
            entity = {"uri": uri}
            if uri in label_map:
                entity["label"] = label_map[uri]
            entities.append(entity)

        return entities

    @staticmethod
    def _binding_value(binding: Any, variable: str) -> Optional[str]:
        value = binding.get(variable) if isinstance(binding, dict) else None
        if isinstance(value, dict):
            return value.get("value")
        if value is not None:
            return str(value)
        return None

    def _extract_binding_rows(self, result: dict[str, Any]) -> List[Dict[str, str]]:
        bindings = result.get("results", [])
        if hasattr(bindings, "to_dict") and callable(getattr(bindings, "to_dict")):
            records = bindings.to_dict("records")
            return [
                {key: value for key, value in record.items() if value is not None}
                for record in records
            ]

        if isinstance(bindings, list):
            rows = []
            for binding in bindings:
                if not isinstance(binding, dict):
                    continue
                row = {}
                for variable, value in binding.items():
                    if isinstance(value, dict) and value.get("value") is not None:
                        row[variable] = value["value"]
                    elif value is not None:
                        row[variable] = value
                if row:
                    rows.append(row)
            return rows

        if isinstance(bindings, dict) and "results" in bindings:
            rows = []
            for binding in bindings["results"].get("bindings", []):
                row = {}
                for variable, value in binding.items():
                    if isinstance(value, dict) and value.get("value") is not None:
                        row[variable] = value["value"]
                if row:
                    rows.append(row)
            return rows

        return []

    def get_entity_labels(
        self, entity_uris: List[str], timeout: int = 10
    ) -> Dict[str, str]:
        if not entity_uris:
            return {}

        unique_uris = list(dict.fromkeys(uri for uri in entity_uris if uri))
        values_clause = " ".join(f"<{uri}>" for uri in unique_uris)
        query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?entity ?label WHERE {{
            VALUES ?entity {{ {values_clause} }}
            OPTIONAL {{
                ?entity rdfs:label ?label .
                FILTER(LANG(?label) = "en" || LANG(?label) = "")
            }}
        }}
        """

        res = execute(query, endpoint=self.endpoint, timeout=timeout)
        label_map = {}
        if not res.get("success"):
            return label_map

        for row in self._extract_binding_rows(res):
            uri = row.get("entity")
            label = row.get("label")
            if uri and label:
                label_map.setdefault(uri, label)
        return label_map

    def sample_subgraph_instances(
        self,
        subgraph: Dict[str, Any],
        type_label_cache: Dict[str, str],
        m: int = 5,
        timeout: int = 60,
        max_attr_len: int = 200,
    ) -> Dict[str, Any]:
        type_uris = sorted(subgraph["types"])
        type_to_var = {type_uri: f"v{index}" for index, type_uri in enumerate(type_uris)}

        clauses = []
        for type_uri, variable in type_to_var.items():
            clauses.append(f"?{variable} a <{type_uri}> .")

        for edge in subgraph["edges"]:
            source_var = type_to_var[edge["s"]]
            target_var = type_to_var[edge["o"]]
            clauses.append(f"?{source_var} <{edge['p']}> ?{target_var} .")

        query = f"""
        SELECT DISTINCT {' '.join(f'?{var}' for var in type_to_var.values())} WHERE {{
            {' '.join(clauses)}
        }}
        LIMIT {m}
        """

        res = execute(query, endpoint=self.endpoint, timeout=timeout)
        rows = self._extract_binding_rows(res) if res.get("success") else []

        type_samples = {
            type_label_cache[type_uri]: {"uri": type_uri, "sample_entities": []}
            for type_uri in type_uris
        }
        instances = []
        attribute_uris = set()

        if not rows:
            return {
                "sample_mode": "grounded",
                "sample_query": query,
                "sample_query_success": False,
                "types": type_samples,
                "instances": instances,
                "attribute_uris": [],
            }

        entity_uris = []
        for row in rows:
            for variable in type_to_var.values():
                uri = row.get(variable)
                if uri:
                    entity_uris.append(uri)
        label_map = self.get_entity_labels(entity_uris)

        attribute_info_by_type = {}
        if "type_attributes" in subgraph:
            for type_uri, attrs_info in subgraph["type_attributes"].items():
                property_uris = [attr["property"] for attr in attrs_info]
                attribute_uris.update(property_uris)
                attribute_info_by_type[type_uri] = {
                    "property_uris": property_uris,
                    "property_labels": {
                        attr["property"]: attr["property_label"] for attr in attrs_info
                    },
                    "property_supports": {
                        attr["property"]: attr["support"] for attr in attrs_info
                    },
                    "property_datatype_labels": {
                        attr["property"]: attr["datatype_label"]
                        for attr in attrs_info
                    },
                }

        for row_index, row in enumerate(rows):
            bindings = {}
            instance_triples = []
            instance_attributes = []

            for type_uri in type_uris:
                variable = type_to_var[type_uri]
                entity_uri = row.get(variable)
                if not entity_uri:
                    continue

                sample = {"uri": entity_uri}
                if entity_uri in label_map:
                    sample["label"] = label_map[entity_uri]

                attrs_info = attribute_info_by_type.get(type_uri)
                attr_values = {}
                if attrs_info:
                    attr_values = self.get_attribute_values(
                        entity_uri=entity_uri,
                        properties=attrs_info["property_uris"],
                    )
                    if attr_values:
                        attr_parts = []
                        for prop, val in attr_values.items():
                            label = attrs_info["property_labels"][prop]
                            support = attrs_info["property_supports"][prop]
                            dtype_label = attrs_info["property_datatype_labels"][prop]
                            marker = "*" if support < self.min_support else ""
                            if isinstance(val, str):
                                if len(val) > max_attr_len:
                                    val_str = f"'{val[:max_attr_len]}...'"
                                else:
                                    val_str = f"'{val}'"
                            else:
                                val_str = str(val)
                            attr_parts.append(f"{label}{marker}:{dtype_label}={val_str}")
                            instance_attributes.append(
                                {
                                    "source_type": type_uri,
                                    "source": entity_uri,
                                    "property": prop,
                                    "property_label": label,
                                    "value": val,
                                    "datatype_label": dtype_label,
                                }
                            )
                        sample["attributes"] = f"({', '.join(attr_parts)})"

                type_label = type_label_cache[type_uri]
                type_samples[type_label]["sample_entities"].append(sample)
                bindings[type_label] = sample

            for edge in subgraph["edges"]:
                source_uri = row.get(type_to_var[edge["s"]])
                target_uri = row.get(type_to_var[edge["o"]])
                if source_uri and target_uri:
                    instance_triples.append(
                        {
                            "source_type": edge["s"],
                            "source": source_uri,
                            "predicate": edge["p"],
                            "target_type": edge["o"],
                            "target": target_uri,
                            "optional": bool(edge.get("is_optional")),
                        }
                    )

            instances.append(
                {
                    "index": row_index,
                    "bindings": bindings,
                    "triples": instance_triples,
                    "attributes": instance_attributes,
                }
            )

        return {
            "sample_mode": "grounded",
            "sample_query": query,
            "sample_query_success": True,
            "types": type_samples,
            "instances": instances,
            "attribute_uris": sorted(list(attribute_uris)),
        }

    def get_type_label(self, type_uri: str, timeout: int = 10) -> Optional[str]:
        """
        Get the rdfs:label for a type URI from the knowledge graph.
        Returns the label if found, otherwise None.
        """
        # Check ABSTAT's already-fetched label cache first (avoids a SPARQL round-trip)
        if type_uri in self.abstat.type_labels:
            return self.abstat.type_labels[type_uri]

        query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?label WHERE {{
            <{type_uri}> rdfs:label ?label .
            FILTER(LANG(?label) = "en" || LANG(?label) = "")
        }}
        ORDER BY DESC(LANG(?label) = "en")
        LIMIT 1
        """

        res = execute(query, endpoint=self.endpoint, timeout=timeout)

        if res.get("success"):
            bindings = res.get("results", [])

            # Handle different response formats
            if hasattr(bindings, "to_dict") and callable(getattr(bindings, "to_dict")):
                records = bindings.to_dict("records")
                if records:
                    return records[0].get("label")
            elif isinstance(bindings, list):
                if bindings:
                    return bindings[0].get("label", {}).get("value")
            elif isinstance(bindings, dict) and "results" in bindings:
                if bindings["results"].get("bindings"):
                    return (
                        bindings["results"]["bindings"][0].get("label", {}).get("value")
                    )

        print(
            f"[type_label] No label found for type URI: {type_uri} "
            f"(status={res.get('status')}, error={res.get('error')})"
        )

        return None

    def find_and_verify_attributes(
        self,
        type_uris: Set[str],
        num_attrs: int,
        verif_timeout: int = 5,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Find and verify attribute patterns for a set of types.
        Collects attributes from all types, randomly samples num_attrs total,
        and allows optional attributes (support >= 1 but < min_support).

        Args:
            type_uris: Set of type URIs to find attributes for
            num_attrs: Total number of attributes to sample across all types
            verif_timeout: Timeout for verification queries

        Returns:
            Dict mapping type_uri to list of verified attributes
        """
        if (
            not hasattr(self.abstat, "attribute_counts")
            or not self.abstat.attribute_counts
        ):
            return {}

        # Collect all attributes for all types (excluding label and description properties)
        all_attributes = []
        excluded_uris = {
            "http://www.w3.org/2000/01/rdf-schema#label",
            "http://www.w3.org/2000/01/rdf-schema#comment",
            "http://www.w3.org/2004/02/skos/core#prefLabel",
            "http://www.w3.org/2004/02/skos/core#altLabel",
            "http://www.w3.org/2004/02/skos/core#definition",
            "http://purl.org/dc/terms/description",
            "http://purl.org/dc/elements/1.1/description",
        }
        for (s, p, o), count in self.abstat.attribute_counts.items():
            if s in type_uris:
                # Filter out label and description properties
                p_lower = p.lower()
                if (
                    p not in excluded_uris
                    and "label" not in p_lower
                    and "description" not in p_lower
                    and "comment" not in p_lower
                ):
                    all_attributes.append((s, p, o, count))

        if not all_attributes:
            return {}

        # Randomly sample num_attrs from all available attributes
        if len(all_attributes) > num_attrs:
            all_attributes = random.sample(all_attributes, num_attrs)

        # Verify each attribute and organize by type
        type_attributes = defaultdict(list)
        for s, p, o, count in all_attributes:
            # Verification: check actual support using get_support
            support = self.get_support(
                types={s},
                edges=[(s, p, o)],
                timeout=verif_timeout,
                limit=self.min_support,
            )

            if support >= 1:
                # Get property label
                p_label = self.get_type_label(p)
                if not p_label:
                    p_label = p.split("/")[-1].split("#")[-1]

                # Get datatype label from URI
                o_label = o.split("/")[-1].split("#")[-1]

                type_attributes[s].append(
                    {
                        "property": p,
                        "property_label": p_label,
                        "datatype": o,
                        "datatype_label": o_label,
                        "support": support,
                    }
                )

        return dict(type_attributes)

    def get_attribute_values(
        self,
        entity_uri: str,
        properties: List[str],
        timeout: int = 10,
    ) -> Dict[str, Any]:
        """
        Fetch attribute values for a specific entity.

        Args:
            entity_uri: The entity URI to fetch attributes for
            properties: List of property URIs to fetch
            timeout: Query timeout

        Returns:
            Dict mapping property labels to their values
        """
        if not properties:
            return {}

        # Build query to fetch all properties at once
        property_vars = []
        optional_clauses = []
        for i, prop in enumerate(properties):
            var_name = f"val{i}"
            property_vars.append(var_name)
            optional_clauses.append(
                f"OPTIONAL {{ <{entity_uri}> <{prop}> ?{var_name} }}"
            )

        query = f"""
        SELECT {' '.join(f'?{v}' for v in property_vars)} WHERE {{
            {' '.join(optional_clauses)}
        }}
        """

        res = execute(query, endpoint=self.endpoint, timeout=timeout)

        values = {}
        if res.get("success"):
            bindings = res.get("results", [])
            if hasattr(bindings, "to_dict") and callable(getattr(bindings, "to_dict")):
                records = bindings.to_dict("records")
                if records:
                    record = records[0]
                    for i, prop in enumerate(properties):
                        var_name = f"val{i}"
                        if var_name in record and record[var_name] is not None:
                            values[prop] = record[var_name]
            elif isinstance(bindings, list) and bindings:
                record = bindings[0]
                if record is None:
                    return values
                for i, prop in enumerate(properties):
                    var_name = f"val{i}"
                    if var_name in record:
                        val_obj = record[var_name]
                        if isinstance(val_obj, dict) and "value" in val_obj:
                            values[prop] = val_obj["value"]
                        elif val_obj is not None:
                            values[prop] = val_obj

        return values

    def prepare_subgraph_yaml_data(
        self,
        subgraph: Dict[str, Any],
        index: int,
        m: int = 5,
        max_attr_len: int = 200,
    ) -> Dict[str, Any]:
        """
        Prepare subgraph data for YAML export with graph info and sample entities per type.

        Args:
            subgraph: Subgraph dictionary with types, edges, and attributes
            index: Subgraph index
            m: Number of sample entities per type
            max_attr_len: Maximum length for attribute values (truncated with '...' if exceeded)
        """
        # Build a cache of type labels to avoid repeated queries
        type_label_cache = {}
        for type_uri in subgraph["types"]:
            label = self.get_type_label(type_uri)
            if label:
                type_label_cache[type_uri] = label
            else:
                # Fallback to URI parsing if no label found
                type_label_cache[type_uri] = type_uri.split("/")[-1].split("#")[-1]

        sample_payload = self.sample_subgraph_instances(
            subgraph,
            type_label_cache=type_label_cache,
            m=m,
            max_attr_len=max_attr_len,
        )
        type_samples = sample_payload["types"]
        attribute_uris = set(sample_payload.get("attribute_uris", []))

        # Format edges as readable strings
        # Optional edges marked with asterisk at the end
        formatted_edges = []
        predicate_uris = []
        for edge in subgraph["edges"]:
            s, p, o = edge["s"], edge["p"], edge["o"]
            is_optional = edge.get("is_optional", False)

            # Collect predicate URI
            if p not in predicate_uris:
                predicate_uris.append(p)

            # Get labels for subject, predicate, object
            s_label = type_label_cache.get(s, s.split("/")[-1].split("#")[-1])
            o_label = type_label_cache.get(o, o.split("/")[-1].split("#")[-1])

            # Get predicate label
            p_label = self.get_type_label(p)
            if not p_label:
                p_label = p.split("/")[-1].split("#")[-1]

            # Create readable edge representation
            # Add asterisk for optional edges (support < min_support)
            arrow = "-->*" if is_optional else "-->"
            edge_str = f"{s_label} --{p_label} {arrow} {o_label}"
            formatted_edges.append(edge_str)

        # Build YAML structure
        yaml_data = {
            "subgraph_id": index + 1,
            "num_types": subgraph["num_types"],
            "min_support": subgraph["support"],
            "edges": formatted_edges,
            "predicate_uris": predicate_uris,
            "attribute_uris": sorted(list(attribute_uris)),
            "sample_mode": sample_payload.get("sample_mode", "grounded"),
            "sample_query": sample_payload.get("sample_query"),
            "sample_query_success": sample_payload.get("sample_query_success"),
            "instances": sample_payload.get("instances", []),
            "types": type_samples,
        }
        return yaml_data

    def save_all_subgraphs_to_yaml(
        self,
        subgraphs_data: List[Dict[str, Any]],
        output_dir: str,
    ) -> str:
        """
        Save all subgraphs to a YAML file with format: mm-dd-hh-endpoint.yaml
        Returns the path to the saved file.
        """
        os.makedirs(output_dir, exist_ok=True)

        # Generate timestamp: mm-dd-hh
        timestamp = datetime.now().strftime("%m-%d-%H")

        # Extract endpoint name from URL
        # Remove protocol and clean up the endpoint string
        endpoint_name = self.endpoint.replace("http://", "").replace("https://", "")
        endpoint_name = endpoint_name.replace("/", "-").replace(":", "-")
        # Remove trailing dashes and limit length
        endpoint_name = endpoint_name.strip("-")[:50]

        filename = f"{timestamp}-{endpoint_name}.yaml"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, "w") as f:
            yaml.dump(
                subgraphs_data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

        return filepath

    def get_support(
        self,
        types: Set[str],
        edges: List[Tuple[str, str, str]],
        timeout: int = 10,
        pbar=None,
        limit: int = None,
    ) -> int:
        """
        Returns the number of instances matching the subgraph pattern.
        Handles both entity-to-entity edges and entity-to-literal (attribute) edges.
        """
        sorted_types = sorted(list(types))
        type_to_var = {t: f"?v{i}" for i, t in enumerate(sorted_types)}

        clauses = []
        # Type constraints
        for t, var in type_to_var.items():
            clauses.append(f"{var} a <{t}> .")

        # Structure constraints
        for s, p, o in edges:
            v_s = type_to_var[s]

            # Check if this is an attribute edge (object is a datatype, not an entity type)
            if o not in type_to_var:
                # Attribute edge: entity -> literal
                # Use a variable for the literal value
                clauses.append(f"{v_s} <{p}> ?literalValue{len(clauses)} .")
            else:
                # Regular edge: entity -> entity
                v_o = type_to_var[o]
                clauses.append(f"{v_s} <{p}> {v_o} .")

        # Construct Count Query
        query_body = "\n".join(clauses)

        if limit is not None:
            # Optimization: Use LIMIT inner query to stop early
            # We use SELECT * to count embeddings up to the limit
            query = f"""
             SELECT (COUNT(*) as ?count) WHERE {{
                 {{
                     SELECT * WHERE {{
                         {query_body}
                     }} LIMIT {limit}
                 }}
             }}
             """
        else:
            query = f"""
             SELECT (COUNT(*) as ?count) WHERE {{
                 {query_body}
             }}
             """

        # Execute with timeout
        res = execute(query, endpoint=self.endpoint, timeout=timeout)

        if not res.get("success"):
            if pbar is not None:
                pbar.write(f"  [Skipped] Timeout or Error ({timeout}s)")
            return 0

        if res.get("success"):
            try:
                # The executor returns the list of bindings directly in 'results'
                bindings = res.get("results", [])

                val = None
                # Handling different response formats
                if hasattr(bindings, "to_dict") and callable(
                    getattr(bindings, "to_dict")
                ):
                    records = bindings.to_dict("records")
                    if records:
                        val = records[0].get("count")
                elif isinstance(bindings, list):
                    if bindings:
                        val = bindings[0].get("count", {}).get("value")
                elif isinstance(bindings, dict):
                    if "results" in bindings and "bindings" in bindings["results"]:
                        val = (
                            bindings["results"]["bindings"][0]
                            .get("count", {})
                            .get("value")
                        )

                if val is not None:
                    return int(val)
            except Exception as e:
                pass

        return 0

    @staticmethod
    def _compute_k_slots(k, num_subgraphs: int) -> Dict[int, int]:
        """Convert k spec (int, tuple, or dict) into {k_value: num_slots}."""
        if isinstance(k, int):
            return {k: num_subgraphs}
        elif isinstance(k, tuple):
            k_values = list(range(k[0], k[1] + 1))
            base, remainder = divmod(num_subgraphs, len(k_values))
            return {
                kv: base + (1 if i < remainder else 0) for i, kv in enumerate(k_values)
            }
        elif isinstance(k, dict):
            total_weight = sum(k.values())
            slots, assigned = {}, 0
            k_items = sorted(k.items())
            for i, (kv, w) in enumerate(k_items):
                if i == len(k_items) - 1:
                    slots[kv] = num_subgraphs - assigned
                else:
                    slots[kv] = round(num_subgraphs * w / total_weight)
                    assigned += slots[kv]
            return slots
        raise ValueError(f"k must be int, tuple, or dict, got {type(k)}")

    @staticmethod
    def _sample_target_k(k_slots: Dict[int, int]) -> Optional[int]:
        """Sample a target k from remaining unfilled slots, weighted by availability."""
        available = [(kv, slots) for kv, slots in k_slots.items() if slots > 0]
        if not available:
            return None
        k_values, weights = zip(*available)
        return random.choices(k_values, weights=weights, k=1)[0]

    def mine(
        self,
        k: Union[int, Tuple[int, int], Dict[int, float]],
        num_subgraphs: int = 5,
        exact_support=False,
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
        """
        DFS to find connected subgraphs with K types.
        Uses max_subgraphs_per_seed to enforce diversity by limiting how many subgraphs can spawn from a single initial frequent pattern.

        Args:
            k: Number of types in the subgraph. Can be:
               - int: exact k value (e.g., k=3)
               - tuple (min_k, max_k): uniform distribution over the range (e.g., k=(3, 5) → equal slots for k=3,4,5)
               - dict {k_value: weight}: weighted distribution (e.g., k={3: 0.6, 4: 0.3, 5: 0.1})
               Each seed is assigned a target k sampled from the distribution, ensuring balanced output.
            num_subgraphs: Number of subgraphs to find.
            exact_support: If True, computes exact support (slower).
            m: Number of sample entities to fetch per type (default 5).
            output_dir: If provided, saves each subgraph to a YAML file in this directory.
            max_subgraphs_per_seed: Max number of subgraphs allowed to be generated from the same initial seed pattern.
            verif_timeout: Timeout in seconds for support verification SPARQL queries.
            prob_optional: Probability/fraction of subgraphs that should contain optional edges (0.0 to 1.0).
                          Optional edges have support >= 1 but < min_support. Default 0.0 (no optional edges).
            num_attrs: Number of data attributes to verify for each subgraph.
                       Can be an int (exact) or a tuple (min_attrs, max_attrs) for a range.
                       When a range is provided, each subgraph randomly samples from the range. Default 0.
            max_attr_len: Maximum length for attribute values in YAML output. Values exceeding this
                         length will be truncated with '...' suffix. Default 200.
            strategy: Search strategy for exploring candidates. "rand" (default) pops from a random
                      position in the stack for diverse exploration. "dfs" pops from the top (depth-first).
            uniform_types: If True, each type in the current subgraph contributes exactly one randomly
                      chosen candidate edge during expansion, preventing high-degree hub types (e.g.
                      dbo:Person) from dominating and causing star-topology bias. Default False.
        """
        k_slots = self._compute_k_slots(k, num_subgraphs)

        if isinstance(num_attrs, int):
            num_attrs_range = (num_attrs, num_attrs)
        else:
            num_attrs_range = num_attrs
        # Check if patterns have been built
        if not self.patterns:
            raise RuntimeError(
                "Pattern pool is empty. Call preprocess() first to build patterns from querybloom."
            )

        emit_event(
            event_sink,
            "stage.started",
            "mining",
            "Mining subgraphs",
            {
                "k": k,
                "num_subgraphs": num_subgraphs,
                "max_subgraphs_per_seed": max_subgraphs_per_seed,
                "exact_support": exact_support,
                "output_dir": output_dir,
                "num_attrs": num_attrs,
                "uniform_types": uniform_types,
            },
        )

        found_subgraphs = []
        found_signatures = set()
        exported_subgraphs = []

        # Optional edge tracking
        target_optional = int(num_subgraphs * prob_optional)
        optional_count = 0  # Count of subgraphs with at least one optional edge

        pbar = tqdm(desc="Explored Candidates", total=num_subgraphs)

        # Track usage of initial seeds (patterns)
        seed_usage = defaultdict(int)

        stack = []
        visited = set()

        # Initialize stack with all frequent patterns
        # We shuffle them to ensure random start order, preventing bias towards the beginning of the list
        patterns_list = self.patterns.copy()
        random.shuffle(patterns_list)

        for p in patterns_list:
            s, pred, o = p
            count = self.abstat.pattern_counts.get(p, 0)
            edge_dict = {
                "s": s,
                "p": pred,
                "o": o,
                "support": count,
                "is_optional": False,
            }
            stack.append(
                Candidate(
                    types={s, o},
                    edges=[edge_dict],
                    est_support=count,
                    is_verified=True,
                    seed_pattern=p,
                    has_optional=False,
                )
            )

        try:
            while stack and len(found_subgraphs) < num_subgraphs:
                if stop_event is not None and stop_event.is_set():
                    emit_event(
                        event_sink,
                        "run.cancelled",
                        "mining",
                        "Mining cancelled",
                        {"num_subgraphs": len(found_subgraphs)},
                    )
                    break
                if skip_event is not None and skip_event.is_set():
                    emit_event(
                        event_sink,
                        "stage.skipped",
                        "mining",
                        "Mining skipped — proceeding to questions",
                        {"num_subgraphs": len(found_subgraphs)},
                    )
                    break

                # Pop candidate
                if strategy == "rand":
                    pop_idx = random.randint(0, len(stack) - 1)
                else:
                    pop_idx = -1
                c = stack.pop(pop_idx)

                if seed_usage[c.seed_pattern] >= max_subgraphs_per_seed:
                    continue

                # Assign target_k if not yet assigned
                if c.target_k is None:
                    c.target_k = self._sample_target_k(k_slots)
                    if c.target_k is None:
                        continue  # All slots filled

                # 1. VERIFY SUPPORT (Lazy Evaluation)
                cur_support = c.est_support
                if not c.is_verified:
                    last_edge = c.edges[-1]
                    s_name = last_edge["s"].split("/")[-1].split("#")[-1]
                    p_name = last_edge["p"].split("/")[-1].split("#")[-1]
                    o_name = last_edge["o"].split("/")[-1].split("#")[-1]
                    pbar.set_postfix_str(f"Verifying: ...--[{p_name}]-->{o_name}")

                    limit_val = None if exact_support else self.min_support
                    edges_tuples = [(e["s"], e["p"], e["o"]) for e in c.edges]
                    real_support = self.get_support(
                        c.types,
                        edges_tuples,
                        timeout=verif_timeout,
                        pbar=pbar,
                        limit=limit_val,
                    )

                    if real_support < self.min_support:
                        if real_support >= 1 and optional_count < target_optional:
                            last_edge["support"] = real_support
                            last_edge["is_optional"] = True
                            c.has_optional = True
                            cur_support = real_support
                        else:
                            continue
                    else:
                        last_edge["support"] = real_support
                        cur_support = real_support

                # Dedup check
                sig = frozenset((e["s"], e["p"], e["o"]) for e in c.edges)
                if sig in visited or sig in found_signatures:
                    continue
                visited.add(sig)

                # 2. CHECK GOAL: accept only at target_k
                cur_num_types = len(c.types)
                if cur_num_types == c.target_k:
                    if k_slots.get(c.target_k, 0) <= 0:
                        continue

                    sampled_num_attrs = random.randint(
                        num_attrs_range[0], num_attrs_range[1]
                    )
                    subgraph = {
                        "types": list(c.types),
                        "edges": c.edges,
                        "num_types": cur_num_types,
                        "support": cur_support,
                        "has_optional_edges": c.has_optional,
                    }

                    if sampled_num_attrs > 0:
                        type_attributes = self.find_and_verify_attributes(
                            type_uris=c.types,
                            num_attrs=sampled_num_attrs,
                            verif_timeout=verif_timeout,
                        )
                        if type_attributes:
                            subgraph["type_attributes"] = type_attributes

                    found_subgraphs.append(subgraph)
                    found_signatures.add(sig)
                    k_slots[c.target_k] -= 1

                    graph = subgraph_to_cytoscape(
                        subgraph,
                        type_labels=self.abstat.type_labels,
                        property_labels=self.abstat.property_labels,
                    )
                    emit_event(
                        event_sink,
                        "subgraph.discovered",
                        "mining",
                        f"Discovered subgraph {len(found_subgraphs)}",
                        {
                            "index": len(found_subgraphs) - 1,
                            "subgraph": subgraph,
                            "graph": graph,
                            "k": c.target_k,
                            "support": cur_support,
                            "remaining_slots": dict(k_slots),
                        },
                    )

                    if c.has_optional:
                        optional_count += 1
                    pbar.update(1)
                    seed_usage[c.seed_pattern] += 1

                    yaml_data = self.prepare_subgraph_yaml_data(
                        subgraph,
                        index=len(found_subgraphs) - 1,
                        m=m,
                        max_attr_len=max_attr_len,
                    )
                    emit_event(
                        event_sink,
                        "subgraph.samples",
                        "mining.samples",
                        f"Samples ready for subgraph {len(found_subgraphs)}",
                        {
                            "index": len(found_subgraphs) - 1,
                            "subgraph_id": yaml_data.get("subgraph_id"),
                            "types": yaml_data.get("types", {}),
                            "edges": yaml_data.get("edges", []),
                            "predicate_uris": yaml_data.get("predicate_uris", []),
                            "attribute_uris": yaml_data.get("attribute_uris", []),
                            "samples": yaml_data,
                        },
                    )

                    if output_dir:
                        exported_subgraphs.append(yaml_data)
                        filepath = self.save_all_subgraphs_to_yaml(
                            exported_subgraphs, output_dir=output_dir
                        )
                        self.last_export_path = filepath
                        pbar.write(
                            f"Updated {filepath} with subgraph {len(found_subgraphs)} (k={c.target_k}, Seed usage: {seed_usage[c.seed_pattern]})"
                        )

                    if seed_usage[c.seed_pattern] >= max_subgraphs_per_seed:
                        continue
                    continue  # Don't expand beyond target_k

                # If we've overshot target_k, discard
                if cur_num_types > c.target_k:
                    continue

                # 3. EXTENSIONS
                cur_edge_tuples = {(e["s"], e["p"], e["o"]) for e in c.edges}
                ext_candidates = set()
                if uniform_types:
                    # One random candidate per type — prevents high-degree hub types
                    # from dominating expansion and causing star-topology bias.
                    for t in c.types:
                        local = [
                            pat for pat in self.adj[t] if pat not in cur_edge_tuples
                        ]
                        if local:
                            ext_candidates.add(random.choice(local))
                else:
                    for t in c.types:
                        for pat in self.adj[t]:
                            if pat not in cur_edge_tuples:
                                ext_candidates.add(pat)

                cand_list = list(ext_candidates)
                random.shuffle(cand_list)

                for pat in cand_list:
                    s, p, o = pat
                    new_types = c.types | {s, o}

                    new_edge = {
                        "s": s,
                        "p": p,
                        "o": o,
                        "support": None,
                        "is_optional": False,
                    }
                    new_edges = c.edges + [new_edge]

                    new_sig = frozenset((e["s"], e["p"], e["o"]) for e in new_edges)
                    if new_sig in visited:
                        continue

                    pat_count = self.abstat.pattern_counts.get(pat, 0)
                    est_support = min(cur_support, pat_count)

                    if est_support >= self.min_support or (
                        est_support >= 1 and optional_count < target_optional
                    ):
                        stack.append(
                            Candidate(
                                types=new_types,
                                edges=new_edges,
                                est_support=est_support,
                                is_verified=False,
                                seed_pattern=c.seed_pattern,
                                has_optional=c.has_optional,
                                target_k=c.target_k,
                            )
                        )

        finally:
            pbar.close()

        emit_event(
            event_sink,
            "stage.completed",
            "mining",
            "Mining completed",
            {"num_subgraphs": len(found_subgraphs), "output_path": self.last_export_path},
        )

        return found_subgraphs

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
    ):
        """
        Visualize the discovered ontology using Graphviz.

        Args:
            sample: Number of top frequent patterns to plot.
            rankdir: Direction of graph layout ('TB', 'LR', etc.).
            format: Output format ('png', 'pdf', 'svg', etc.).
            view: Whether to open the rendered file in the default viewer. Default False for inline notebook use.
            filename: Base filename for the rendered output.
            include_attributes: If True, include attribute patterns (entity→literal). Default False.
            nodesep: Horizontal separation between nodes (default 0.5). Smaller = more compact.
            ranksep: Vertical separation between ranks (default 0.8). Smaller = more compact.

        Returns:
            The graphviz.Digraph object (renders inline in Jupyter).
        """
        try:
            from graphviz import Digraph
            import numpy as np  # Import numpy here if not at top level, though it probably is
        except ImportError:
            print(
                "Visualization requires the 'graphviz' library. Install with `pip inst101all graphviz`."
            )
            return None

        if not self.patterns and not (
            include_attributes and self.abstat.attribute_patterns
        ):
            print("No patterns found. Run preprocess() first.")
            return None

        # Sort patterns by frequency
        ranked_patterns = []
        for pat in self.patterns:
            count = self.abstat.pattern_counts.get(pat, 0)
            ranked_patterns.append((pat, count, False))  # False = object pattern

        # Include attribute patterns if requested
        if include_attributes:
            for pat in self.abstat.attribute_patterns:
                count = self.abstat.attribute_counts.get(pat, 0)
                ranked_patterns.append((pat, count, True))  # True = attribute pattern

        ranked_patterns.sort(key=lambda x: x[1], reverse=True)
        top_patterns = ranked_patterns[:sample]

        total_count = len(self.patterns) + (
            len(self.abstat.attribute_patterns) if include_attributes else 0
        )
        print(
            f"Plotting top {len(top_patterns)} frequent patterns (out of {total_count} total)..."
        )

        # Create Graphviz Digraph
        dot = Digraph(comment="Discovered Ontology", format=format)

        # Graph Attributes
        dot.attr(rankdir=rankdir)
        dot.attr(overlap="false")
        dot.attr(splines="true")
        dot.attr(nodesep=str(nodesep))
        dot.attr(ranksep=str(ranksep))
        dot.attr(layout="dot")  # 'dot' is best for hierarchical/directed graphs

        # Default Node Attributes
        dot.attr(
            "node",
            shape="box",
            style="filled",
            fillcolor="#e6f2ff",
            fontsize="9",
            fontname="Helvetica",
            height="0.2",
            margin="0.1",
        )

        # Default Edge Attributes
        dot.attr(
            "edge",
            fontsize="8",
            fontname="Helvetica",
            color="#292E2F9B",
            arrowsize="0.6",
        )

        nodes = set()
        literal_nodes = set()  # Track which nodes are literals/datatypes
        edges = []

        # Collect nodes and edges
        for (s, p, o), count, is_attribute in top_patterns:
            s_label = s.split("/")[-1].split("#")[-1] if s else "Unknown"
            o_label = o.split("/")[-1].split("#")[-1] if o else "Unknown"
            p_label = p.split("/")[-1].split("#")[-1] if p else "Unknown"

            nodes.add(s_label)
            nodes.add(o_label)

            # Mark object as literal if this is an attribute pattern
            if is_attribute:
                literal_nodes.add(o_label)

            # Use penwidth to represent frequency/strength
            # Thinner edges: base 0.3, mild log scaling
            width = 0.2 + (np.log(count + 1) * 0.2)

            edges.append((s_label, o_label, p_label, str(round(width, 2))))

        # Add nodes with different styling for literals
        for n in nodes:
            if n in literal_nodes:
                # Literal/datatype nodes: different shape and color
                dot.node(n, n, shape="ellipse", fillcolor="#ffe6cc", fontsize="8")
            else:
                # Regular entity nodes
                dot.node(n, n)

        # Add edges without labels
        for s, o, p_label, w in edges:
            dot.edge(s, o, penwidth=w)

        if len(nodes) == 0:
            print("Resulting graph is empty.")
            return None

        print(f"Graph stats: {len(nodes)} nodes, {len(edges)} edges")

        # Render and View
        try:
            # view=False prevents opening a new window
            output_path = dot.render(filename, view=view, cleanup=True)
            print(f"Graph rendered to {output_path}")
        except Exception as e:
            print(f"Error rendering graph: {e}")
            print("Make sure Graphviz executables are installed and on your PATH.")

        return dot
