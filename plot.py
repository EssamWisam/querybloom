import re
import math
import yaml
import matplotlib.pyplot as plt
import networkx as nx
from collections import defaultdict
from typing import List, Dict, Any


def plot_subgraphs_from_yaml(
    yaml_path: str,
    graphs_per_row: int = 4,
    rows_per_figure: int = 4,
    figsize_per_graph: tuple = (4, 4.5),
    save_path: str = None,
    shapes: bool = False,
):
    """
    Plot all subgraphs from a YAML file using NetworkX and Matplotlib.

    Args:
        yaml_path: Path to the YAML file containing subgraphs
        graphs_per_row: Number of graphs per row (default: 4)
        rows_per_figure: Number of rows per figure (default: 4)
        figsize_per_graph: Size of each individual graph subplot (default: (4, 4.5))
        save_path: Optional path prefix to save figures (e.g., 'output/subgraphs')
                  Will save as 'output/subgraphs_fig1.png', 'output/subgraphs_fig2.png', etc.        shapes: If True, plot each subgraph's topological shape (star, path, cycle, tree, …)
                instead of the full annotated subgraph (default: False).
    Returns:
        List of figure objects
    """
    # Load YAML data
    with open(yaml_path, "r") as f:
        subgraphs = yaml.safe_load(f)

    if not subgraphs:
        print("No subgraphs found in YAML file")
        return []

    # When showing shapes, deduplicate by graph isomorphism
    if shapes:
        plot_items = _group_by_isomorphism(subgraphs)   # list of (subgraph, count, ids)
    else:
        plot_items = [(sg, 1, [sg["subgraph_id"]]) for sg in subgraphs]

    # Calculate layout
    graphs_per_figure = graphs_per_row * rows_per_figure
    num_figures = (len(plot_items) + graphs_per_figure - 1) // graphs_per_figure

    figures = []

    for fig_idx in range(num_figures):
        # Calculate how many graphs in this figure
        start_idx = fig_idx * graphs_per_figure
        end_idx = min(start_idx + graphs_per_figure, len(plot_items))
        graphs_in_this_fig = end_idx - start_idx

        # Calculate actual rows needed for this figure
        actual_rows = (graphs_in_this_fig + graphs_per_row - 1) // graphs_per_row

        # Create figure
        fig_width = figsize_per_graph[0] * graphs_per_row
        fig_height = figsize_per_graph[1] * actual_rows
        fig, axes = plt.subplots(
            actual_rows, graphs_per_row, figsize=(fig_width, fig_height), dpi=150
        )

        # Handle single subplot case
        if actual_rows == 1 and graphs_per_row == 1:
            axes = [[axes]]
        elif actual_rows == 1:
            axes = [axes]
        elif graphs_per_row == 1:
            axes = [[ax] for ax in axes]

        # Plot each subgraph
        for i, item_idx in enumerate(range(start_idx, end_idx)):
            row = i // graphs_per_row
            col = i % graphs_per_row
            ax = axes[row][col]

            subgraph, count, ids = plot_items[item_idx]
            if shapes:
                _plot_shape(subgraph, ax, count=count, ids=ids)
            else:
                _plot_single_subgraph(subgraph, ax)

            # Add border around each subplot
            for spine in ax.spines.values():
                spine.set_edgecolor("black")
                spine.set_linewidth(1.5)
                spine.set_visible(True)

        # Hide unused subplots
        for i in range(graphs_in_this_fig, actual_rows * graphs_per_row):
            row = i // graphs_per_row
            col = i % graphs_per_row
            axes[row][col].axis("off")

        plt.tight_layout(pad=2.0, h_pad=3.0, w_pad=2.0)
        figures.append(fig)

        # Save if path provided
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


# ---------------------------------------------------------------------------
# Shape helpers
# ---------------------------------------------------------------------------

def _group_by_isomorphism(subgraphs: List[Dict[str, Any]]):
    """
    Group subgraphs by directed-graph isomorphism of their class-level structure.
    Returns a list of (representative_subgraph, count, [ids]) tuples,
    one entry per unique isomorphism class, sorted by descending count.
    """
    groups: List[tuple] = []   # (DiGraph, representative_subgraph, [ids])
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


def _build_class_graph(subgraph: Dict[str, Any]) -> nx.DiGraph:
    """Return a DiGraph containing only class nodes and object-property edges."""
    G = nx.DiGraph()
    type_names = list(subgraph["types"].keys())
    for type_name in type_names:
        G.add_node(type_name)
    for edge_str in subgraph["edges"]:
        if "-->*" in edge_str:
            left_part, right_part = edge_str.split("-->*", 1)
        elif "-->" in edge_str:
            left_part, right_part = edge_str.split("-->", 1)
        else:
            continue
        left_parts = left_part.strip().split(" ")
        source = left_parts[0] if left_parts else ""
        target = right_part.strip()
        if source in type_names and target in type_names:
            G.add_edge(source, target)
    return G


def _classify_shape(G: nx.DiGraph) -> str:
    """Classify the topological shape of a class-level directed graph."""
    n = G.number_of_nodes()
    if n == 0:
        return "empty"
    if n == 1:
        return "single"
    if n == 2:
        return "pair"

    U = G.to_undirected()
    degrees = sorted([d for _, d in U.degree()], reverse=True)

    # Star: one hub connected to all others; leaves have degree 1
    if degrees[0] == n - 1 and all(d == 1 for d in degrees[1:]):
        return "star"

    # Path: connected, exactly two degree-1 endpoints, rest degree-2
    if (
        nx.is_connected(U)
        and degrees.count(1) == 2
        and all(d <= 2 for d in degrees)
    ):
        return "path"

    # Cycle: every node has degree 2, connected
    if all(d == 2 for d in degrees) and nx.is_connected(U):
        return "cycle"

    # Tree: connected, exactly n-1 edges (acyclic)
    if nx.is_connected(U) and U.number_of_edges() == n - 1:
        return "tree"

    # Complete: all pairs connected
    if U.number_of_edges() == n * (n - 1) // 2:
        return "complete"

    return "other"


def _shape_layout(G: nx.DiGraph, shape: str) -> Dict:
    """Return purely geometric, deterministic node positions for the detected shape."""
    nodes = list(G.nodes())
    n = len(nodes)

    if n == 1:
        return {nodes[0]: (0.0, 0.0)}

    if n == 2:
        return {nodes[0]: (-1.0, 0.0), nodes[1]: (1.0, 0.0)}

    if shape == "star":
        # Hub at centre, leaves evenly spaced on unit circle
        U = G.to_undirected()
        hub = max(nodes, key=lambda nd: U.degree(nd))
        leaves = [nd for nd in nodes if nd != hub]
        pos = {hub: (0.0, 0.0)}
        for i, leaf in enumerate(leaves):
            angle = 2 * math.pi * i / len(leaves) - math.pi / 2
            pos[leaf] = (math.cos(angle), math.sin(angle))
        return pos

    if shape in ("cycle", "complete"):
        # Regular polygon, first node at top
        pos = {}
        for i, nd in enumerate(nodes):
            angle = 2 * math.pi * i / n - math.pi / 2
            pos[nd] = (math.cos(angle), math.sin(angle))
        return pos

    if shape == "path":
        # Traverse the path; lay nodes in a 2-column grid (snake top-to-bottom)
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
        # BFS hierarchical layout: root at top, children spread horizontally
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

    # "other" / fallback: pack nodes into a grid
    cols = math.ceil(math.sqrt(n))
    pos = {}
    for i, nd in enumerate(nodes):
        row = i // cols
        col = i % cols
        pos[nd] = (float(col), -float(row))
    return pos


def _abbrev(name: str) -> str:
    """Return a short display label for a class name."""
    parts = re.findall(r"[A-Z][a-z]*|[a-z]+", name)
    if len(parts) <= 2:
        return name[:10]
    return "".join(p[0].upper() for p in parts)


def _plot_shape(subgraph: Dict[str, Any], ax, count: int = 1, ids: List = None):
    """Plot a canonical shape diagram for the subgraph's class-level structure."""
    G = _build_class_graph(subgraph)
    shape = _classify_shape(G)
    pos = _shape_layout(G, shape)

    # Normalise positions to [-1, 1] so every shape fills the panel uniformly
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    pos = {nd: ((p[0] - cx) / span * 1.6, (p[1] - cy) / span * 1.6)
           for nd, p in pos.items()}

    # Small dark-purple filled nodes — no labels
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_color="#5B2C8D",
        node_size=500,
        node_shape="o",
        linewidths=0,
    )
    # Black edges with clean arrows
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

    n_types = subgraph["num_types"]
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


# ---------------------------------------------------------------------------

def _plot_single_subgraph(subgraph: Dict[str, Any], ax):
    """
    Plot a single subgraph on the given axes.

    Args:
        subgraph: Dictionary containing subgraph data from YAML
        ax: Matplotlib axes to plot on
    """
    G = nx.DiGraph()

    # Extract type names from the types dictionary
    type_names = list(subgraph["types"].keys())

    # Add nodes (types)
    for type_name in type_names:
        G.add_node(type_name, node_type="class")

    # Parse edges and add to graph
    edge_labels = {}
    for edge_str in subgraph["edges"]:
        # Parse edge string like "WeatherObservation --usesTreatment --> Resource"
        # or "SimulationModel --usesSoilPhysicalSample -->* SoilPhysicalSample"
        # Handle cases where arrow might be stuck to target like "-->*Resource"

        # Split by the arrow pattern
        if "-->*" in edge_str:
            left_part, right_part = edge_str.split("-->*", 1)
            is_optional = True
        elif "-->" in edge_str:
            left_part, right_part = edge_str.split("-->", 1)
            is_optional = False
        else:
            continue  # Skip malformed edges

        # Parse left side (source and predicate)
        left_parts = left_part.strip().split(" ")
        if len(left_parts) >= 2:
            source = left_parts[0]
            predicate = " ".join(left_parts[1:]).strip("-").strip()
        else:
            continue

        # Parse right side (target)
        target = right_part.strip()

        if source and target:
            # Add edge
            G.add_edge(source, target, edge_type="object_property")
            edge_labels[(source, target)] = predicate

    # Add attribute nodes from sample entities
    attribute_edges = []
    for type_name, type_data in subgraph["types"].items():
        if type_name in type_names and "sample_entities" in type_data:
            # Collect unique attribute names from all samples
            attr_names = set()
            for entity in type_data["sample_entities"]:
                if "attributes" in entity:
                    # Parse attributes string like "(date='1948-10-07', badValueFlag='0')"
                    attr_str = entity["attributes"]
                    if attr_str.startswith("(") and attr_str.endswith(")"):
                        attr_str = attr_str[1:-1]  # Remove parentheses
                        # Split by comma and extract attribute names
                        for attr_pair in attr_str.split(","):
                            attr_pair = attr_pair.strip()
                            if "=" in attr_pair:
                                attr_name = attr_pair.split("=")[0].strip().rstrip("*")
                                attr_names.add(attr_name)

            # Add attribute nodes and edges
            for attr_name in attr_names:
                attr_node = f"{attr_name}"
                G.add_node(attr_node, node_type="attribute")
                G.add_edge(type_name, attr_node, edge_type="datatype_property")
                attribute_edges.append((type_name, attr_node))

    # Layout with better spacing
    pos = nx.spring_layout(G, k=1.5, iterations=50, seed=42, scale=0.9)

    # Separate nodes by type
    class_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "class"]
    attr_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") == "attribute"]

    # Separate edges by type
    object_property_edges = [
        (u, v)
        for u, v, d in G.edges(data=True)
        if d.get("edge_type") == "object_property"
    ]
    datatype_property_edges = [
        (u, v)
        for u, v, d in G.edges(data=True)
        if d.get("edge_type") == "datatype_property"
    ]

    # Draw class nodes (larger, blue)
    if class_nodes:
        nx.draw_networkx_nodes(
            G,
            pos,
            nodelist=class_nodes,
            ax=ax,
            node_color="lightblue",
            node_size=2000,
            node_shape="o",
        )

    # Draw attribute nodes (smaller, grey)
    if attr_nodes:
        nx.draw_networkx_nodes(
            G,
            pos,
            nodelist=attr_nodes,
            ax=ax,
            node_color="lightgrey",
            node_size=800,
            node_shape="s",
        )

    # Draw object property edges (solid, with arrows)
    if object_property_edges:
        nx.draw_networkx_edges(
            G,
            pos,
            edgelist=object_property_edges,
            ax=ax,
            edge_color="gray",
            arrows=True,
            arrowsize=25,
            arrowstyle="-|>",
            width=2,
        )

    # Draw datatype property edges (dotted, thinner)
    if datatype_property_edges:
        nx.draw_networkx_edges(
            G,
            pos,
            edgelist=datatype_property_edges,
            ax=ax,
            edge_color="orange",
            arrows=False,
            style="dotted",
            width=1,
        )

    # Draw node labels
    nx.draw_networkx_labels(G, pos, ax=ax, font_size=6, font_weight="bold")

    # Draw edge labels
    nx.draw_networkx_edge_labels(
        G, pos, edge_labels, ax=ax, font_size=4, font_color="red"
    )

    # Title
    subgraph_id = subgraph["subgraph_id"]
    num_types = subgraph["num_types"]
    support = subgraph["min_support"]
    has_optional = subgraph.get("has_optional_edges", False)
    optional_marker = "*" if has_optional else ""

    ax.set_title(
        f"Subgraph {subgraph_id}{optional_marker}\n{num_types} types, support={support}",
        fontsize=7,
        fontweight="bold",
        pad=10,
    )

    # Set limits with padding to prevent nodes from hitting edges
    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-1.2, 1.2)

    # Make axis invisible but keep the box
    ax.set_xticks([])
    ax.set_yticks([])


if __name__ == "__main__":
    # Example usage
    import sys

    if len(sys.argv) > 1:
        yaml_path = sys.argv[1]
        save_path = sys.argv[2] if len(sys.argv) > 2 else None

        figures = plot_subgraphs_from_yaml(yaml_path, save_path=save_path)
        plt.show()
    else:
        print("Usage: python plot.py <yaml_path> [save_path_prefix]")
        print("Example: python plot.py subgraphs.yaml output/graphs")
