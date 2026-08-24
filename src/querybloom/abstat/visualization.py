"""Matplotlib schema graph plotting and tabular pattern analysis."""

from __future__ import annotations

import random
from typing import Any, Sequence

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd


def plot_schema_graph(
    patterns: set[tuple[str, str, str]],
    type_labels: dict[str, str],
    property_labels: dict[str, str],
    exclude_properties: Sequence[str] | None = None,
    max_edges: int | None = None,
) -> None:
    """
    Plots the schema graph derived from minimal type patterns.
    C — P —> D
    """
    if exclude_properties is None:
        exclude_properties = []

    patterns_to_plot: list[tuple[str, str, str]] = []
    for sub_type, pred, obj_type in patterns:
        p_name = pred.split("/")[-1].split("#")[-1]
        if p_name not in exclude_properties:
            patterns_to_plot.append((sub_type, pred, obj_type))

    if max_edges and len(patterns_to_plot) > max_edges:
        print(f"Sampling {max_edges} patterns from {len(patterns_to_plot)} available...")
        patterns_to_plot = random.sample(patterns_to_plot, max_edges)

    PG = nx.MultiDiGraph()
    print(f"Plotting schema graph with {len(patterns_to_plot)} patterns...")

    edge_labels: dict[tuple[str, str], str] = {}
    node_labels: dict[str, str] = {}

    def get_name(uri: str) -> str:
        return uri.split("/")[-1].split("#")[-1]

    for sub_type, pred, obj_type in patterns_to_plot:
        p_name = get_name(pred)
        u = get_name(sub_type)
        v = get_name(obj_type)

        PG.add_edge(u, v)

        if sub_type in type_labels:
            node_labels[u] = type_labels[sub_type]
        else:
            node_labels[u] = u

        if obj_type in type_labels:
            node_labels[v] = type_labels[obj_type]
        else:
            node_labels[v] = v

        if pred in property_labels:
            edge_labels[(u, v)] = property_labels[pred]
        else:
            edge_labels[(u, v)] = p_name

    if PG.number_of_nodes() == 0:
        print("Graph is empty. No patterns to plot.")
        return

    plt.figure(figsize=(15, 10))
    pos = nx.spring_layout(PG, k=2, iterations=100)

    nx.draw_networkx_nodes(
        PG, pos, node_size=2000, node_color="lightblue", alpha=0.9
    )
    nx.draw_networkx_labels(
        PG, pos, labels=node_labels, font_size=8, font_weight="bold"
    )

    ax = plt.gca()
    for (u, v), label in edge_labels.items():
        if u not in pos or v not in pos:
            continue

        start = pos[u]
        end = pos[v]

        arrow = patches.FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=15,
            color="gray",
            alpha=0.6,
            shrinkA=20,
            shrinkB=20,
        )
        ax.add_patch(arrow)

        mid_point = (start + end) / 2
        plt.text(
            mid_point[0],
            mid_point[1],
            label,
            horizontalalignment="center",
            verticalalignment="center",
            fontsize=7,
            color="darkblue",
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.8),
        )

    plt.title("ABSTAT 2.0 Schema Summary")
    plt.axis("off")
    plt.show()


def format_pattern_dataframe(
    pattern_counts: dict[tuple[str, str, str], int],
    type_labels: dict[str, str],
    property_labels: dict[str, str],
) -> pd.DataFrame:
    """
    Returns a DataFrame of patterns, sorted by properties with the fewest combinations first.
    """
    data: list[dict[str, Any]] = []
    for (s, p, o), count in pattern_counts.items():
        p_name = p.split("/")[-1].split("#")[-1]
        s_name = s.split("/")[-1].split("#")[-1]
        o_name = o.split("/")[-1].split("#")[-1]

        if s in type_labels:
            s_display = f"{s_name} ({type_labels[s]})"
        else:
            s_display = s_name

        if o in type_labels:
            o_display = f"{o_name} ({type_labels[o]})"
        else:
            o_display = o_name

        if p in property_labels:
            label = property_labels[p]
            p_display = f"{p_name} ({label})"
        else:
            p_display = p_name

        data.append(
            {
                "Subject Type": s_display,
                "Property": p_display,
                "Object Type": o_display,
                "Count": count,
            }
        )

    if not data:
        print("No patterns found.")
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df["complexity"] = df.groupby("Property")["Property"].transform("count")
    df_sorted = df.sort_values(
        by=["complexity", "Property", "Count"], ascending=[True, True, False]
    )
    return df_sorted.drop(columns=["complexity"])
