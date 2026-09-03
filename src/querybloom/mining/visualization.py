"""Graphviz and Matplotlib/NetworkX ontology graph visualization for mined pattern pools and subgraphs."""

from __future__ import annotations

from collections import defaultdict
import math
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import yaml

from querybloom.mining.yaml_v5 import parse_relationship_line


def plot_ontology_graph(
    patterns: List[Tuple[str, str, str]],
    pattern_counts: Dict[Tuple[str, str, str], int],
    attribute_patterns: Set[Tuple[str, str, str]],
    attribute_counts: Dict[Tuple[str, str, str], int],
    sample: int = 500,
    rankdir: str = "TB",
    format: str = "png",
    view: bool = False,
    filename: str = "ontology_graph",
    include_attributes: bool = False,
    nodesep: float = 0.5,
    ranksep: float = 0.8,
) -> Any:
    """
    Visualize the discovered ontology using Graphviz.
    """
    try:
        from graphviz import Digraph
        import numpy as np
    except ImportError:
        print(
            "Visualization requires the 'graphviz' library. Install with `pip install graphviz`."
        )
        return None

    if not patterns and not (include_attributes and attribute_patterns):
        print("No patterns found. Run preprocess() first.")
        return None

    ranked_patterns = []
    for pat in patterns:
        count = pattern_counts.get(pat, 0)
        ranked_patterns.append((pat, count, False))

    if include_attributes:
        for pat in attribute_patterns:
            count = attribute_counts.get(pat, 0)
            ranked_patterns.append((pat, count, True))

    ranked_patterns.sort(key=lambda x: x[1], reverse=True)
    top_patterns = ranked_patterns[:sample]

    total_count = len(patterns) + (
        len(attribute_patterns) if include_attributes else 0
    )
    print(
        f"Plotting top {len(top_patterns)} frequent patterns (out of {total_count} total)..."
    )

    dot = Digraph(comment="Discovered Ontology", format=format)
    dot.attr(rankdir=rankdir)
    dot.attr(overlap="false")
    dot.attr(splines="true")
    dot.attr(nodesep=str(nodesep))
    dot.attr(ranksep=str(ranksep))
    dot.attr(layout="dot")

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

    dot.attr(
        "edge",
        fontsize="8",
        fontname="Helvetica",
        color="#292E2F9B",
        arrowsize="0.6",
    )

    nodes = set()
    literal_nodes = set()
    edges = []

    for (s, p, o), count, is_attribute in top_patterns:
        s_label = s.split("/")[-1].split("#")[-1] if s else "Unknown"
        o_label = o.split("/")[-1].split("#")[-1] if o else "Unknown"
        p_label = p.split("/")[-1].split("#")[-1] if p else "Unknown"

        nodes.add(s_label)
        nodes.add(o_label)

        if is_attribute:
            literal_nodes.add(o_label)

        width = 0.2 + (np.log(count + 1) * 0.2)
        edges.append((s_label, o_label, p_label, str(round(width, 2))))

    for n in nodes:
        if n in literal_nodes:
            dot.node(n, n, shape="ellipse", fillcolor="#ffe6cc", fontsize="8")
        else:
            dot.node(n, n)

    for s, o, p_label, w in edges:
        dot.edge(s, o, penwidth=w)

    if len(nodes) == 0:
        print("Resulting graph is empty.")
        return None

    print(f"Graph stats: {len(nodes)} nodes, {len(edges)} edges")

    try:
        output_path = dot.render(filename, view=view, cleanup=True)
        print(f"Graph rendered to {output_path}")
    except Exception as e:
        print(f"Error rendering graph: {e}")
        print("Make sure Graphviz executables are installed and on your PATH.")

    return dot


# ---------------------------------------------------------------------------
# NetworkX & Matplotlib Subgraph Plotting Helpers
# ---------------------------------------------------------------------------

def _relationship_lines(subgraph: Dict[str, Any]) -> List[str]:
    relationships = subgraph.get("relationships")
    if isinstance(relationships, list) and relationships:
        return [str(line) for line in relationships]
    return [str(line) for line in subgraph.get("edges") or []]


def _schema_attribute_names(subgraph: Dict[str, Any]) -> Dict[str, List[str]]:
    names: Dict[str, List[str]] = {}
    attributes = subgraph.get("attributes")
    if isinstance(attributes, dict):
        for type_name, value in attributes.items():
            if not isinstance(value, str):
                continue
            parsed = []
            for part in value.split("|"):
                line = part.strip()
                if " --" in line or line.startswith("--"):
                    label = line.lstrip("-").split("(", 1)[0].strip()
                    if label:
                        parsed.append(label)
            if parsed:
                names[type_name] = parsed
        if names:
            return names
    for type_name, type_data in (subgraph.get("types") or {}).items():
        if not isinstance(type_data, dict):
            continue
        attr_names = []
        for entity in type_data.get("sample_entities") or []:
            attr_str = entity.get("attributes") or ""
            if attr_str.startswith("(") and attr_str.endswith(")"):
                attr_str = attr_str[1:-1]
            for attr_pair in attr_str.split(","):
                attr_pair = attr_pair.strip()
                if "=" in attr_pair:
                    attr_names.append(attr_pair.split("=")[0].strip().rstrip("*"))
        if attr_names:
            names[type_name] = sorted(set(attr_names))
    return names


def _build_class_graph(subgraph: Dict[str, Any]):
    import networkx as nx
    G = nx.DiGraph()
    type_names = list(subgraph.get("types", {}).keys())
    for type_name in type_names:
        G.add_node(type_name)
    for edge_str in _relationship_lines(subgraph):
        parsed = parse_relationship_line(str(edge_str))
        if not parsed:
            continue
        source, target = parsed["source"], parsed["target"]
        if source in type_names and target in type_names:
            G.add_edge(source, target)
    return G


def _classify_shape(G) -> str:
    import networkx as nx
    n = G.number_of_nodes()
    if n == 0:
        return "empty"
    if n == 1:
        return "single"
    if n == 2:
        return "pair"

    U = G.to_undirected()
    degrees = sorted([d for _, d in U.degree()], reverse=True)

    if degrees[0] == n - 1 and all(d == 1 for d in degrees[1:]):
        return "star"

    if nx.is_connected(U) and degrees.count(1) == 2 and all(d <= 2 for d in degrees):
        return "path"

    if all(d == 2 for d in degrees) and nx.is_connected(U):
        return "cycle"

    if nx.is_connected(U) and U.number_of_edges() == n - 1:
        return "tree"

    if U.number_of_edges() == n * (n - 1) // 2:
        return "complete"

    return "other"


def _shape_layout(G, shape: str) -> Dict:
    import networkx as nx
    nodes = list(G.nodes())
    n = len(nodes)

    if n == 1:
        return {nodes[0]: (0.0, 0.0)}

    if n == 2:
        return {nodes[0]: (-1.0, 0.0), nodes[1]: (1.0, 0.0)}

    if shape == "star":
        U = G.to_undirected()
        hub = max(nodes, key=lambda nd: U.degree(nd))
        leaves = [nd for nd in nodes if nd != hub]
        pos = {hub: (0.0, 0.0)}
        for i, leaf in enumerate(leaves):
            angle = 2 * math.pi * i / len(leaves) - math.pi / 2
            pos[leaf] = (math.cos(angle), math.sin(angle))
        return pos

    if shape in ("cycle", "complete"):
        pos = {}
        for i, nd in enumerate(nodes):
            angle = 2 * math.pi * i / n - math.pi / 2
            pos[nd] = (math.cos(angle), math.sin(angle))
        return pos

    if shape == "path":
        U = G.to_undirected()
        endpoints = [nd for nd in nodes if U.degree(nd) == 1]
        start = endpoints[0] if endpoints else nodes[0]
        ordered = list(nx.dfs_preorder_nodes(U, source=start))
        half = (n + 1) // 2
        pos = {}
        for i, nd in enumerate(ordered):
            col = float(i // half)
            row = -float(i % half)
            pos[nd] = (col, row)
        return pos

    if shape == "tree":
        in_degrees = dict(G.in_degree())
        roots = [nd for nd, deg in in_degrees.items() if deg == 0]
        root = roots[0] if roots else max(nodes, key=lambda nd: G.to_undirected().degree(nd))
        U = G.to_undirected()
        levels: Dict = {}
        queue = [root]
        levels[root] = 0
        while queue:
            nxt = []
            for nd in queue:
                for nb in U.neighbors(nd):
                    if nb not in levels:
                        levels[nb] = levels[nd] + 1
                        nxt.append(nb)
            queue = nxt
        level_nodes: Dict = defaultdict(list)
        for nd, lv in levels.items():
            level_nodes[lv].append(nd)
        pos = {}
        for lv, nds in level_nodes.items():
            w = len(nds)
            for j, nd in enumerate(nds):
                pos[nd] = ((j - (w - 1) / 2.0), -float(lv))
        return pos

    cols = math.ceil(math.sqrt(n))
    pos = {}
    for i, nd in enumerate(nodes):
        row = i // cols
        col = i % cols
        pos[nd] = (float(col), -float(row))
    return pos


def _group_by_isomorphism(subgraphs: List[Dict[str, Any]]):
    import networkx as nx
    groups: List[tuple] = []
    for sg in subgraphs:
        G = _build_class_graph(sg)
        matched = False
        for g_rep, rep_sg, ids in groups:
            if nx.is_isomorphic(G, g_rep):
                ids.append(sg["subgraph_id"])
                matched = True
                break
        if not matched:
            groups.append((G, sg, [sg["subgraph_id"]]))
    groups.sort(key=lambda t: len(t[2]), reverse=True)
    return [(rep_sg, len(ids), ids) for _, rep_sg, ids in groups]


def _plot_shape(subgraph: Dict[str, Any], ax, count: int = 1, ids: List = None):
    import networkx as nx
    G = _build_class_graph(subgraph)
    shape = _classify_shape(G)
    pos = _shape_layout(G, shape)

    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    pos = {nd: ((p[0] - cx) / span * 1.6, (p[1] - cy) / span * 1.6) for nd, p in pos.items()}

    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_color="#5B2C8D",
        node_size=500,
        node_shape="o",
        linewidths=0,
    )
    nx.draw_networkx_edges(
        G, pos, ax=ax,
        edge_color="black",
        arrows=True,
        arrowsize=12,
        arrowstyle="-|>",
        width=1.4,
        min_source_margin=12,
        min_target_margin=12,
    )

    n_types = subgraph.get("num_types", len(subgraph.get("types", {})))
    count_label = f"  ×{count}" if count > 1 else ""
    id_summary = f"#{ids[0]}" if ids and len(ids) == 1 else f"#{ids[0]}…" if ids else ""
    ax.set_title(
        f"{id_summary}{count_label}  [{shape}]\n{n_types} nodes",
        fontsize=7, fontweight="bold", pad=6,
    )
    ax.set_xlim(-1.9, 1.9)
    ax.set_ylim(-1.9, 1.9)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_aspect("equal")


def _plot_single_subgraph(subgraph: Dict[str, Any], ax):
    import networkx as nx
    G = nx.DiGraph()
    type_names = list(subgraph.get("types", {}).keys())

    for type_name in type_names:
        G.add_node(type_name, node_type="class")

    edge_labels = {}
    for edge_str in _relationship_lines(subgraph):
        parsed = parse_relationship_line(str(edge_str))
        if not parsed:
            continue
        source, target, predicate = parsed["source"], parsed["target"], parsed["predicate"]
        if source and target:
            G.add_edge(source, target, edge_type="object_property")
            edge_labels[(source, target)] = predicate

    attribute_edges = []
    for type_name, attr_names in _schema_attribute_names(subgraph).items():
        if type_name not in type_names:
            continue
        for attr_name in attr_names:
            attr_node = f"{attr_name}"
            G.add_node(attr_node, node_type="attribute")
            G.add_edge(type_name, attr_node, edge_type="datatype_property")
            attribute_edges.append((type_name, attr_node))

    pos = nx.spring_layout(G, k=1.5, iterations=50, seed=42, scale=0.9)
    class_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "class"]
    attr_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "attribute"]

    object_property_edges = [
        (u, v) for u, v, d in G.edges(data=True) if d.get("edge_type") == "object_property"
    ]
    datatype_property_edges = [
        (u, v) for u, v, d in G.edges(data=True) if d.get("edge_type") == "datatype_property"
    ]

    if class_nodes:
        nx.draw_networkx_nodes(
            G, pos, nodelist=class_nodes, ax=ax,
            node_color="lightblue", node_size=2000, node_shape="o",
        )
    if attr_nodes:
        nx.draw_networkx_nodes(
            G, pos, nodelist=attr_nodes, ax=ax,
            node_color="lightgrey", node_size=800, node_shape="s",
        )
    if object_property_edges:
        nx.draw_networkx_edges(
            G, pos, edgelist=object_property_edges, ax=ax,
            edge_color="gray", arrows=True, arrowsize=25, arrowstyle="-|>", width=2,
        )
    if datatype_property_edges:
        nx.draw_networkx_edges(
            G, pos, edgelist=datatype_property_edges, ax=ax,
            edge_color="orange", arrows=False, style="dotted", width=1,
        )

    nx.draw_networkx_labels(G, pos, ax=ax, font_size=6, font_weight="bold")
    nx.draw_networkx_edge_labels(G, pos, edge_labels, ax=ax, font_size=4, font_color="red")

    subgraph_id = subgraph.get("subgraph_id", "unknown")
    num_types = subgraph.get("num_types", len(type_names))
    support = subgraph.get("support", subgraph.get("min_support", 0))
    has_optional = subgraph.get("has_optional_edges", False)
    optional_marker = "*" if has_optional else ""

    ax.set_title(
        f"Subgraph {subgraph_id}{optional_marker}\n{num_types} types, support={support}",
        fontsize=7, fontweight="bold", pad=10,
    )
    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-1.2, 1.2)
    ax.set_xticks([])
    ax.set_yticks([])


def plot_subgraphs_from_yaml(
    yaml_path: str,
    graphs_per_row: int = 4,
    rows_per_figure: int = 4,
    figsize_per_graph: tuple = (4, 4.5),
    save_path: Optional[str] = None,
    shapes: bool = False,
) -> List[Any]:
    """
    Plot all subgraphs from a YAML file using NetworkX and Matplotlib.
    """
    import matplotlib.pyplot as plt

    with open(yaml_path, "r") as f:
        subgraphs = yaml.safe_load(f)

    if not subgraphs:
        print("No subgraphs found in YAML file")
        return []

    if shapes:
        plot_items = _group_by_isomorphism(subgraphs)
    else:
        plot_items = [(sg, 1, [sg.get("subgraph_id")]) for sg in subgraphs]

    graphs_per_figure = graphs_per_row * rows_per_figure
    num_figures = (len(plot_items) + graphs_per_figure - 1) // graphs_per_figure
    figures = []

    for fig_idx in range(num_figures):
        start_idx = fig_idx * graphs_per_figure
        end_idx = min(start_idx + graphs_per_figure, len(plot_items))
        graphs_in_this_fig = end_idx - start_idx
        actual_rows = (graphs_in_this_fig + graphs_per_row - 1) // graphs_per_row

        fig_width = figsize_per_graph[0] * graphs_per_row
        fig_height = figsize_per_graph[1] * actual_rows
        fig, axes = plt.subplots(
            actual_rows, graphs_per_row, figsize=(fig_width, fig_height), dpi=150
        )

        if actual_rows == 1 and graphs_per_row == 1:
            axes = [[axes]]
        elif actual_rows == 1:
            axes = [axes]
        elif graphs_per_row == 1:
            axes = [[ax] for ax in axes]

        for i, item_idx in enumerate(range(start_idx, end_idx)):
            row = i // graphs_per_row
            col = i % graphs_per_row
            ax = axes[row][col]

            subgraph, count, ids = plot_items[item_idx]
            if shapes:
                _plot_shape(subgraph, ax, count=count, ids=ids)
            else:
                _plot_single_subgraph(subgraph, ax)

            for spine in ax.spines.values():
                spine.set_edgecolor("black")
                spine.set_linewidth(1.5)
                spine.set_visible(True)

        for i in range(graphs_in_this_fig, actual_rows * graphs_per_row):
            row = i // graphs_per_row
            col = i % graphs_per_row
            axes[row][col].axis("off")

        plt.tight_layout(pad=2.0, h_pad=3.0, w_pad=2.0)
        figures.append(fig)

        if save_path:
            fig.savefig(
                f"{save_path}_fig{fig_idx + 1}.png", dpi=150, bbox_inches="tight"
            )
            print(f"Saved figure {fig_idx + 1} to {save_path}_fig{fig_idx + 1}.png")

    unique = len(plot_items)
    total = len(subgraphs)
    if shapes and unique < total:
        print(f"\nPlotted {unique} unique shapes (merged from {total} subgraphs) across {num_figures} figure(s)")
    else:
        print(f"\nPlotted {total} subgraphs across {num_figures} figure(s)")
    return figures
