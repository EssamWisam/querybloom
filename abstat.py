import networkx as nx
import matplotlib.pyplot as plt
from typing import Set, Dict, List, Tuple
from collections import defaultdict
from querybloom.executor.sparql_executor import execute_sparql_query


class ABSTAT:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.subtype_graph = nx.DiGraph()
        self.minimal_type_patterns = set()

    def load_terminology(self, limit: int = 10000):
        """
        Loads the subclass hierarchy (T-Box) from the KG.
        Excludes equivalence relations to form a strict partial order if possible.
        """
        print(f"Loading terminology from {self.endpoint}...")
        query = f"""
        SELECT DISTINCT ?sub ?super WHERE {{
            ?sub rdfs:subClassOf ?super .
            FILTER(?sub != ?super)
        }}
        LIMIT {limit}
        """
        result = execute_sparql_query(query, endpoint=self.endpoint)

        if result and result.get("success") and "results" in result:
            bindings = result["results"]
            if isinstance(bindings, list):
                for b in bindings:
                    sub = b["sub"]["value"]
                    sup = b["super"]["value"]
                    self.subtype_graph.add_edge(sub, sup)
            else:
                print(f"Warning: Unexpected results format: {type(bindings)}")
        else:
            print(f"Warning: No valid results from terminology query.")
            if result and result.get("error"):
                print(f"Error: {result['error']}")

        print(f"Loaded {self.subtype_graph.number_of_edges()} subclass relationships.")

    def _is_subtype(self, type_a: str, type_b: str) -> bool:
        """
        Checks if type_a is a subtype of type_b (type_a < type_b).
        In the graph, edge goes sub -> super.
        So we check if there is a path from type_a to type_b.
        """
        if type_a == type_b:
            return True  # Reflexive
        if not self.subtype_graph.has_node(type_a) or not self.subtype_graph.has_node(
            type_b
        ):
            return False
        return nx.has_path(self.subtype_graph, type_a, type_b)

    def compute_minimal_types(self, types: Set[str]) -> Set[str]:
        """
        Given a set of types for an entity, return the set of minimal types.
        M_x = {C in types | not exists C' in types s.t. C' < C (strictly)}
        Wait, if C' is subtype of C, then C' is MORE specific.
        Minimal type usually means "most specific".
        The paper says: "there does not exist a type C' such that C'(a) and C' < G C"
        Yes, so we keep the most specific ones.
        """
        if not types:
            return {"http://www.w3.org/2002/07/owl#Thing"}

        # If terminology is empty or types not in graph, we can't do much reduction based on graph,
        # but we treat unknown types as minimal by default (as per paper).

        # We need to remove T if T is a supertype of any other type T' in the set.
        to_remove = set()
        sorted_types = sorted(list(types))  # Sort for deterministic behavior if needed

        for t1 in sorted_types:
            for t2 in sorted_types:
                if t1 == t2:
                    continue
                # If t2 is a subtype of t1, then t1 is a supertype (less specific).
                # We want to keep specific types. So we remove t1.
                if self._is_subtype(t2, t1):
                    to_remove.add(t1)
                    break  # t1 is redundant

        minimal = types - to_remove
        return minimal

    def extract_patterns(self, sample_limit: int = 100):
        """
        Extracts minimal type patterns from the KG.
        1. Fetches a sample of triples (Relational Assertions - A_P).
        2. Fetches types for subjects and objects involved (Typing Assertions - A_C).
        3. Computes minimal types.
        4.Generates patterns.
        """
        print(f"Fetching sample triples (limit={sample_limit})...")
        # 1. Fetch Relational Assertions (exclude rdf:type)
        triples_query = f"""
        SELECT ?s ?p ?o WHERE {{
            ?s ?p ?o .
            FILTER(?p != rdf:type)
            FILTER(isIRI(?s))
            # FILTER(isIRI(?o)) # Object can be literal? Paper says b is named individual or literal.
        }}
        LIMIT {sample_limit}
        """
        triples_res = execute_sparql_query(triples_query, endpoint=self.endpoint)

        triples = []
        entities = set()

        if triples_res and triples_res.get("success") and "results" in triples_res:
            bindings = triples_res["results"]
            if isinstance(bindings, list):
                for b in bindings:
                    s = b["s"]["value"]
                    p = b["p"]["value"]
                    o = b["o"]["value"]
                    o_type = b["o"]["type"]  # 'uri', 'literal', 'bnode'

                    triples.append((s, p, o, o_type))
                    entities.add(s)
                    if o_type == "uri":
                        entities.add(o)
            else:
                print(f"Warning: Unexpected results format: {type(bindings)}")
        else:
            print(f"Warning: No valid results from triples query.")
            if triples_res and triples_res.get("error"):
                print(f"Error: {triples_res['error']}")

        print(
            f"Fetched {len(triples)} triples. Resolving types for {len(entities)} entities..."
        )

        # 2. Fetch Types
        entity_types = defaultdict(set)
        # Batch query types? Might be too large for one query if entities are many.
        # Let's chunk it.
        entity_list = list(entities)
        chunk_size = 50

        for i in range(0, len(entity_list), chunk_size):
            chunk = entity_list[i : i + chunk_size]
            values = " ".join([f"<{e}>" for e in chunk])
            type_query = f"""
            SELECT ?s ?type WHERE {{
                VALUES ?s {{ {values} }}
                ?s a ?type .
            }}
            """
            type_res = execute_sparql_query(type_query, endpoint=self.endpoint)
            # handle failures?
            if type_res and type_res.get("success") and "results" in type_res:
                bindings = type_res["results"]
                if isinstance(bindings, list):
                    for b in bindings:
                        s = b["s"]["value"]
                        t = b["type"]["value"]
                        entity_types[s].add(t)

        # 3. Compute Minimal Types & 4. Generate Patterns
        self.minimal_type_patterns = set()

        print("Computing patterns...")
        for s, p, o, o_type_desc in triples:
            # Minimal types for Subject
            s_types = entity_types.get(s, set())
            min_s = self.compute_minimal_types(s_types)

            # Minimal types for Object
            if o_type_desc == "uri":
                o_types = entity_types.get(o, set())
                min_o = self.compute_minimal_types(o_types)
            else:
                # Literal handling
                # If datatype is present, use it? Or rdfs:Literal
                # For simplicity, let's assume one "type" for literal which is its datatype or rdfs:Literal
                # In SPARQL results, 'datatype' might be in the binding
                # For now, let's just say "rdfs:Literal" or try to find datatype if available in specific logic
                # But ABSTAT says: "if y is a literal... consider its explicit type if present, rdfs:Literal otherwise"
                # We didn't capture specific datatype in the tuple above effectively for this draft.
                # Let's assume rdfs:Literal for now for generic implementation
                min_o = {"http://www.w3.org/2000/01/rdf-schema#Literal"}

            # Cartesian Product
            for t_s in min_s:
                for t_o in min_o:
                    self.minimal_type_patterns.add((t_s, p, t_o))

        print(f"Extracted {len(self.minimal_type_patterns)} minimal type patterns.")
        return self.minimal_type_patterns

    def _shorten_uri(self, uri: str) -> str:
        """Extract the last part of a URI (after # or last /)"""
        if "#" in uri:
            return uri.split("#")[-1]
        return uri.split("/")[-1]

    def plot_schema_graph(self, figsize=(14, 10), exclude_properties: List[str] = None):
        """
        Visualize the schema graph from discovered patterns.
        Classes are nodes, properties are labeled edges.
        args:
            figsize: Tuple of (width, height)
            exclude_properties: List of property names (short form) to exclude (e.g. ['label', 'type'])
        """
        if exclude_properties is None:
            exclude_properties = []

        if not self.minimal_type_patterns:
            print("No patterns to plot. Run extract_patterns() first.")
            return

        # Build directed multigraph (allows multiple edges between same nodes)
        G = nx.MultiDiGraph()

        # Add edges with property labels
        for subj_type, prop, obj_type in self.minimal_type_patterns:
            subj_short = self._shorten_uri(subj_type)
            obj_short = self._shorten_uri(obj_type)
            prop_short = self._shorten_uri(prop)

            if prop_short in exclude_properties:
                continue

            G.add_edge(subj_short, obj_short, label=prop_short)

        # Layout and plot
        plt.figure(figsize=figsize)
        pos = nx.spring_layout(G, k=2, iterations=50, seed=42)

        # Draw nodes
        nx.draw_networkx_nodes(
            G, pos, node_color="lightblue", node_size=3000, alpha=0.9
        )

        # Draw node labels
        nx.draw_networkx_labels(G, pos, font_size=9, font_weight="bold")

        # Draw edges with property labels
        # Use straight edges to ensure labels align perfectly with the edge line
        nx.draw_networkx_edges(
            G,
            pos,
            edge_color="gray",
            arrows=True,
            arrowsize=20,
            arrowstyle="-|>",
            width=1.5,
            alpha=0.6,
        )

        # Edge labels (properties)
        edge_labels = {}
        for u, v, data in G.edges(data=True):
            if u == v:
                continue  # Skip labeling self-loops to avoid clutter on node
            key = (u, v)
            if key in edge_labels:
                edge_labels[key] += f", {data['label']}"
            else:
                edge_labels[key] = data["label"]

        nx.draw_networkx_edge_labels(
            G,
            pos,
            edge_labels,
            font_size=8,
            font_color="darkred",
            font_weight="bold",
            bbox=dict(
                boxstyle="round,pad=0.2",
                facecolor="white",
                edgecolor="lightgray",
                alpha=0.9,
            ),
            verticalalignment="center",
        )

        # Handle self-loops separately (if any)
        self_loops = [(u, v) for u, v in G.edges() if u == v]
        if self_loops:
            nx.draw_networkx_edges(
                G,
                pos,
                edgelist=self_loops,
                edge_color="gray",
                arrows=True,
                arrowsize=20,
                arrowstyle="-|>",
                connectionstyle="arc3,rad=0.2",  # Curve self-loops
                width=1.5,
                alpha=0.6,
            )
            # Label self loops (offset slightly?) - Difficult in standard NX, skipped to keep simple

        plt.title(
            f"Schema Graph ({len(self.minimal_type_patterns)} patterns)",
            fontsize=14,
            fontweight="bold",
        )
        plt.axis("off")
        plt.tight_layout()
        plt.show()
