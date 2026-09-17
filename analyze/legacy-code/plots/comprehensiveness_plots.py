"""Comprehensiveness plot: Fig 3 (3-spoke radar)."""

import numpy as np
import matplotlib.pyplot as plt

from .common import COLORS, save_fig


def _low_coverage(comp1, comp2, threshold=0.10):
    """Return True when property coverage is below *threshold* for both benchmarks."""
    return (
        comp1["property_coverage"] < threshold
        and comp2["property_coverage"] < threshold
    )


def _build_avg_per_query_data(comp1, comp2):
    """Derive avg-new-classes/query and avg-new-props/query from comp dicts."""
    n1 = max(comp1["n_queries"], 1)
    n2 = max(comp2["n_queries"], 1)
    avg_cls1 = comp1["n_bench_classes"] / n1
    avg_cls2 = comp2["n_bench_classes"] / n2
    avg_prp1 = comp1["n_bench_properties"] / n1
    avg_prp2 = comp2["n_bench_properties"] / n2
    return avg_cls1, avg_cls2, avg_prp1, avg_prp2


def plot_comprehensiveness_radar(comp1, comp2, label1, label2, show=True):
    """3-spoke radar (Class Coverage, Property Coverage, Feature Coverage).

    When property coverage is < 10 % for both benchmarks the class / property
    spokes are replaced with *Avg New Classes / Query* and *Avg New Props / Query*
    so that near-zero coverage percentages are replaced with a more informative
    metric.

    Parameters
    ----------
    comp1, comp2 : dict
        Output of ``measure_comprehensiveness``.
    """
    low_cov = _low_coverage(comp1, comp2)

    if low_cov:
        avg_cls1, avg_cls2, avg_prp1, avg_prp2 = _build_avg_per_query_data(comp1, comp2)
        spoke_labels = [
            "Avg New Classes / Query",
            "Avg New Props / Query",
            "Feature Coverage",
        ]

        values1 = [avg_cls1, avg_prp1, comp1["feature_coverage"]]
        values2 = [avg_cls2, avg_prp2, comp2["feature_coverage"]]

        # Normalize each spoke to [0, 1] so the radar shape is meaningful
        actual1, actual2 = list(values1), list(values2)
        for i in range(len(values1)):
            spoke_max = max(values1[i], values2[i], 1e-9)
            values1[i] /= spoke_max
            values2[i] /= spoke_max

        raw1 = [f"{v:.2f}" for v in actual1]
        raw2 = [f"{v:.2f}" for v in actual2]
    else:
        spoke_labels = ["Class Coverage", "Property Coverage", "Feature Coverage"]
        keys = ["class_coverage", "property_coverage", "feature_coverage"]

        values1 = [comp1[k] for k in keys]
        values2 = [comp2[k] for k in keys]
        raw1 = [comp1[f"{k}_raw"] for k in keys]
        raw2 = [comp2[f"{k}_raw"] for k in keys]

    angles = np.linspace(0, 2 * np.pi, len(spoke_labels), endpoint=False).tolist()
    # close the polygon
    values1_r = values1 + values1[:1]
    values2_r = values2 + values2[:1]
    angles_r = angles + angles[:1]

    r_max = max(max(values1), max(values2), 0.01)

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True), dpi=150)

    for vals, vals_r, raw, color, label in [
        (values1, values1_r, raw1, COLORS[0], label1),
        (values2, values2_r, raw2, COLORS[1], label2),
    ]:
        ax.plot(angles_r, vals_r, color=color, linewidth=3, label=label, alpha=0.9)
        ax.fill(angles_r, vals_r, color=color, alpha=0.15)
        ax.scatter(
            angles, vals, color=color, s=60, zorder=5, edgecolor=color, linewidth=1.5
        )
        # Annotate with decimal values
        for angle, v, r in zip(angles, vals, raw):
            offset = r_max * 0.12
            ax.annotate(
                r,
                xy=(angle, v),
                xytext=(angle, v + offset),
                ha="center",
                va="bottom",
                fontsize=9,
                color=color,
                fontweight="bold",
                textcoords="data",
            )

    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_thetagrids(np.degrees(angles), spoke_labels, fontsize=12, fontweight="bold")

    ax.grid(True, color="#D5D8DC", linestyle="--", linewidth=0.7)
    ax.spines["polar"].set_visible(False)

    tick_values = np.linspace(0, r_max, 5)[1:]
    ax.set_yticks(tick_values)
    ax.set_rlabel_position(22.5)
    y_labels = [f"{v:.2f}" for v in tick_values]
    y_labels[0] = ""
    ax.set_yticklabels(y_labels, fontsize=9, color="#7B7D7D")
    ax.set_ylim(0, r_max * 1.35)

    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.05), ncol=2, frameon=False)

    plt.tight_layout()
    save_fig(fig, "comprehensiveness_radar", extensions=("pdf", "png"))
    if show:
        plt.show()
    else:
        plt.close(fig)
