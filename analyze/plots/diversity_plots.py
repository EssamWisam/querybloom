"""Diversity plots: Fig 1 (semantic t-SNE) and Fig 2 (structural + complexity)."""

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.manifold import TSNE

from .common import COLORS, save_fig

# ---------------------------------------------------------------------------
# Figure 1: Semantic space (t-SNE with APD / MNND annotations)
# ---------------------------------------------------------------------------


def plot_semantic_embeddings(
    metrics1, metrics2, label1, label2, show=True, trim_outlier_pct=5.0
):
    """Side-by-side t-SNE scatter plots from pre-computed embedding arrays.

    Parameters
    ----------
    metrics1, metrics2 : dict
        Output of ``measure_diversity``; must contain ``_embeddings``, ``apd``, ``mnnd``.
    trim_outlier_pct : float
        Percentage of points to drop from each set before t-SNE, based on
        distance from the set's centroid (top ``trim_outlier_pct`` % removed).
        Default is 5.0.
    """

    def _trim(embs, pct):
        if pct <= 0:
            return embs
        centroid = embs.mean(axis=0)
        dists = np.linalg.norm(embs - centroid, axis=1)
        threshold = np.percentile(dists, 100 - pct)
        return embs[dists <= threshold]

    embs1 = _trim(np.array(metrics1["_embeddings"]), trim_outlier_pct)
    embs2 = _trim(np.array(metrics2["_embeddings"]), trim_outlier_pct)
    all_embs = np.vstack([embs1, embs2])

    n1 = len(embs1)
    perplexity = min(30, len(all_embs) - 1)
    proj = TSNE(n_components=2, perplexity=perplexity, random_state=42).fit_transform(
        all_embs
    )

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    x_min, x_max = proj[:, 0].min(), proj[:, 0].max()
    y_min, y_max = proj[:, 1].min(), proj[:, 1].max()
    x_pad = (x_max - x_min) * 0.05
    y_pad = (y_max - y_min) * 0.05

    for ax, idx_slice, label, color, m in [
        (axes[0], slice(0, n1), label1, COLORS[0], metrics1),
        (axes[1], slice(n1, None), label2, COLORS[1], metrics2),
    ]:
        ax.scatter(
            proj[idx_slice, 0],
            proj[idx_slice, 1],
            alpha=0.7,
            color=color,
            edgecolor="k",
            s=60,
        )
        ax.set_xlim(x_min - x_pad, x_max + x_pad)
        ax.set_ylim(y_min - y_pad, y_max + y_pad)
        ax.set_title(f"{label}\nAPD={m['apd']:.4f}  |  Vendi={m['vendi']:.2f}")
        ax.set_xlabel("t-SNE Dimension 1")
        ax.set_ylabel("t-SNE Dimension 2")

    plt.tight_layout()
    save_fig(fig, "semantic_space")
    if show:
        plt.show()
    else:
        plt.close(fig)


# ---------------------------------------------------------------------------
# Figure 2: Structural diversity — 3-panel
#   (a) Feature bars  (b) Complexity violins  (c) Template/entity bars
# ---------------------------------------------------------------------------


def plot_structural_diversity(
    metrics1,
    metrics2,
    label1,
    label2,
    show=True,
    red1=None,
    red2=None,
    complexity_spread="histogram",
    comp1=None,
    comp2=None,
):
    """Three-panel figure from pre-computed diversity dicts.

    Panel (a): SPARQL feature frequency bars.  When *red1* / *red2* (output of
               ``measure_redundancy``) are supplied, each bar is split: the
               redundant portion is drawn in a lighter shade on top.
    Panel (b): Complexity spread.  *complexity_spread* selects the style:
               ``"histogram"`` (default) — back-to-back integer histogram halves;
               ``"kde"`` — overlaid Gaussian KDE curves per metric in subplots.
    Panel (c): Template / entity diversity scalars on a radar chart.
    """
    import matplotlib.patches as mpatches
    from matplotlib.gridspec import GridSpec

    fig = plt.figure(figsize=(22, 6))
    gs = GridSpec(1, 3, figure=fig, width_ratios=[3.0, 3.1, 3.1], wspace=0.22)

    ax_r = fig.add_subplot(gs[0], projection="polar")
    ax_vio = fig.add_subplot(gs[1])
    ax_feat = fig.add_subplot(gs[2])

    # ---- (a) Feature distribution bars --------------------------------
    from metrics.parsing import FEATURE_KEYS, BAR_CHART_EXCLUDE

    pcts1 = metrics1["_feature_pcts"]
    pcts2 = metrics2["_feature_pcts"]

    # Build ordered key list: main features, keeping FILTER as a single bar.
    _exclude = BAR_CHART_EXCLUDE - {"FILTER"} | {"DISTINCT"}
    ordered_keys = [k for k in FEATURE_KEYS if k not in _exclude]

    # Keep only features with ≥5% in either dataset
    visible_keys = [
        k for k in ordered_keys if pcts1.get(k, 0) >= 5 or pcts2.get(k, 0) >= 5
    ]

    def _redundancy_frac(red, feat):
        """Return fraction (0-1) of queries with *feat* that are redundant."""
        if red is None:
            return 0.0
        return red["redundancy_rates"].get(feat, 0.0) / 100.0

    # ---- (a) Back-to-back vertical bar chart (population-pyramid style, vertical) ----
    # label1 (QueryBloom) extends UP (+y), label2 extends DOWN (-y).
    x = np.arange(len(visible_keys))
    bar_w = 0.55

    for pcts, red, color, sign in [
        (pcts1, red1, COLORS[0], +1),
        (pcts2, red2, COLORS[1], -1),
    ]:
        heights = [pcts.get(k, 0) for k in visible_keys]
        fracs = [_redundancy_frac(red, k) for k in visible_keys]
        solid = [h * (1 - f) for h, f in zip(heights, fracs)]
        redund = [h * f for h, f in zip(heights, fracs)]

        ax_feat.bar(
            x,
            [sign * s for s in solid],
            bar_w,
            color=color,
            edgecolor="k",
            linewidth=0.5,
            alpha=0.85,
        )
        ax_feat.bar(
            x,
            [sign * r for r in redund],
            bar_w,
            bottom=[sign * s for s in solid],
            color=color,
            edgecolor="k",
            linewidth=0.5,
            hatch="///",
            alpha=0.85,
        )

    # Central spine
    ax_feat.axhline(0, color="k", linewidth=0.8)

    # Symmetric y-axis; use absolute tick labels
    y_max = (
        max(
            max((pcts1.get(k, 0) for k in visible_keys), default=0),
            max((pcts2.get(k, 0) for k in visible_keys), default=0),
        )
        * 1.15
    )
    ax_feat.set_ylim(-y_max, y_max)
    ticks = np.linspace(0, y_max, 4)
    ax_feat.set_yticks(np.concatenate([-ticks[1:][::-1], ticks]))
    ax_feat.set_yticklabels(
        [f"{abs(t):.0f}" for t in np.concatenate([-ticks[1:][::-1], ticks])], fontsize=8
    )

    # Feature labels on the bottom x-axis
    ax_feat.set_xticks(x)
    ax_feat.set_xticklabels(visible_keys, rotation=45, ha="right", fontsize=8.5)
    ax_feat.xaxis.set_ticks_position("bottom")

    ax_feat.set_ylabel("Percentage of Queries (%)")
    ax_feat.set_title("(c) Feature Distribution")

    # Legend
    # Redundant-portion indicator for panel (c) only
    if red1 is not None or red2 is not None:
        ax_feat.legend(
            handles=[
                mpatches.Patch(
                    facecolor="white",
                    edgecolor="k",
                    hatch="///",
                    alpha=0.85,
                    label="Redundant portion",
                )
            ],
            fontsize=9,
            loc="lower right",
        )

    # ---- (b) Complexity spread ------------------------------------------------
    # metric_pairs: (name, arr1, arr2, clip_pct, x_max, clamp1, clamp2)
    # clip_pct — percentile filter applied before computing histogram / KDE
    # x_max    — explicit display ceiling (also used as filter)
    # clamp1/2 — winsorise arr1/arr2 values above this threshold to this value
    metric_pairs = [
        (
            "Operators",
            metrics1["_operator_counts"],
            metrics2["_operator_counts"],
            None,
            12,
            None,
            None,
        ),
        (
            "Output Rows",
            metrics1["_result_counts"],
            metrics2["_result_counts"],
            95,
            12,
            10,
            None,
        ),
        (
            "Columns",
            metrics1["_column_counts"],
            metrics2["_column_counts"],
            None,
            12,
            None,
            None,
        ),
    ]

    if complexity_spread == "kde":
        from scipy.stats import gaussian_kde
        from matplotlib.gridspec import GridSpecFromSubplotSpec

        # Replace ax_vio with 3 vertical sub-panels sharing the x-axis
        gs_vio = GridSpecFromSubplotSpec(
            3, 1, subplot_spec=gs[1], hspace=0.15
        )  # gs[1] = centre
        ax_vio.set_visible(False)
        kde_axes = [fig.add_subplot(gs_vio[i]) for i in range(3)]

        for i, (mname, arr1, arr2, clip, x_max, clamp1, clamp2) in enumerate(
            metric_pairs
        ):
            ax = kde_axes[i]
            for arr, color, lbl, clamp in [
                (arr1, COLORS[0], label1, clamp1),
                (arr2, COLORS[1], label2, clamp2),
            ]:
                a = np.asarray(arr, dtype=float)
                if clip is not None:
                    a = a[a <= np.percentile(a, clip)]
                if clamp is not None:
                    a = np.clip(a, None, clamp)
                elif x_max is not None:
                    a = a[a <= x_max]
                if len(a) < 2 or a.std() == 0:
                    continue
                kde = gaussian_kde(a, bw_method="scott")
                hi = x_max if x_max is not None else a.max()
                xs = np.linspace(max(a.min(), 0), hi, 300)
                ys = kde(xs)
                ax.plot(xs, ys, color=color, linewidth=1.8, label=lbl)
                ax.fill_between(xs, ys, alpha=0.15, color=color)
                ax.axvline(
                    np.median(a), color=color, linewidth=1, linestyle="--", alpha=0.7
                )
            ax.set_ylabel(mname, fontsize=8.5)
            ax.set_yticks([])
            if x_max is not None:
                ax.set_xlim(0, x_max)
            else:
                ax.set_xlim(left=0)
            if i < 2:
                ax.set_xticklabels([])
        kde_axes[0].set_title("(b) Complexity Spread")
        kde_axes[2].set_xlabel("Count per Query")

    else:  # default: back-to-back histogram

        def _half_histogram(
            ax,
            data,
            x_pos,
            side,
            color,
            max_half_w=0.4,
            clip_pct=None,
            y_max=12,
            cap=None,
        ):
            arr = np.asarray(data, dtype=float)
            if clip_pct is not None:
                arr = arr[arr <= np.percentile(arr, clip_pct)]
            if cap is not None:
                arr = np.clip(arr, None, cap)
                y_max = cap
            bins = np.arange(-0.5, y_max + 1.5)
            counts, edges = np.histogram(arr, bins=bins)
            norm = (
                counts / counts.max() * max_half_w
                if counts.max() > 0
                else counts.astype(float)
            )
            bin_centers = edges[:-1] + 0.5
            if side == "left":
                ax.barh(
                    bin_centers,
                    -norm,
                    left=x_pos,
                    height=0.85,
                    color=color,
                    alpha=0.75,
                    edgecolor="k",
                    linewidth=0.5,
                )
            else:
                ax.barh(
                    bin_centers,
                    norm,
                    left=x_pos,
                    height=0.85,
                    color=color,
                    alpha=0.75,
                    edgecolor="k",
                    linewidth=0.5,
                )
            ax.plot(
                x_pos,
                np.median(arr),
                "o",
                color="w",
                ms=8,
                zorder=5,
                markeredgecolor="k",
                markeredgewidth=0.5,
            )

        for xi, (mname, arr1, arr2, clip, _x_max, _c1, _c2) in enumerate(metric_pairs):
            cap = _c1 if _c1 is not None else _c2
            _half_histogram(ax_vio, arr1, xi, "left", COLORS[0], clip_pct=clip, cap=cap)
            _half_histogram(
                ax_vio, arr2, xi, "right", COLORS[1], clip_pct=clip, cap=cap
            )
            ax_vio.plot([xi, xi], [0, 10], color="k", lw=0.6)

        ax_vio.set_xticks([0, 1, 2])
        ax_vio.set_xticklabels(["Operators", "Output Rows", "Columns"])
        ax_vio.set_xlim(-0.6, 2.6)
        ax_vio.set_ylim(0, 10)
        ax_vio.set_yticks([0, 2, 4, 6, 8, 10])
        ax_vio.set_yticklabels(["0", "2", "4", "6", "8", "10+"])
        ax_vio.set_ylabel("Count per Query")
        ax_vio.set_title("(b) Complexity Spread")  # noqa: duplicate label kept

    # ---- (c) Radar: 6-spoke (diversity + comprehensiveness) or 3-spoke fallback ----
    if comp1 is not None and comp2 is not None:
        # Comprehensiveness spokes — mirror logic from plot_comprehensiveness_radar
        low_cov = (
            comp1["property_coverage"] < 0.10 and comp2["property_coverage"] < 0.10
        )
        if low_cov:
            n1 = max(comp1["n_queries"], 1)
            n2 = max(comp2["n_queries"], 1)
            comp_labels = [
                "Avg New Classes\n/ Query",
                "Avg New Props\n/ Query",
                "Feature\nCoverage",
            ]
            comp_vals1 = [
                comp1["n_bench_classes"] / n1,
                comp1["n_bench_properties"] / n1,
                comp1["feature_coverage"],
            ]
            comp_vals2 = [
                comp2["n_bench_classes"] / n2,
                comp2["n_bench_properties"] / n2,
                comp2["feature_coverage"],
            ]
            comp_raw1 = [f"{v:.2f}" for v in comp_vals1]
            comp_raw2 = [f"{v:.2f}" for v in comp_vals2]
        else:
            comp_labels = ["Class\nCoverage", "Property\nCoverage", "Feature\nCoverage"]
            _keys = ["class_coverage", "property_coverage", "feature_coverage"]
            comp_vals1 = [comp1[k] for k in _keys]
            comp_vals2 = [comp2[k] for k in _keys]
            comp_raw1 = [comp1[f"{k}_raw"] for k in _keys]
            comp_raw2 = [comp2[f"{k}_raw"] for k in _keys]

        div_labels = ["Template\nRatio", "Entity\nDiversity", "Feature\nEntropy"]
        div_vals1 = [
            metrics1["unique_template_ratio"],
            metrics1["entity_diversity_ratio"],
            metrics1["feature_entropy"],
        ]
        div_vals2 = [
            metrics2["unique_template_ratio"],
            metrics2["entity_diversity_ratio"],
            metrics2["feature_entropy"],
        ]
        div_raw1 = [f"{v:.3f}" for v in div_vals1]
        div_raw2 = [f"{v:.3f}" for v in div_vals2]

        spoke_labels = div_labels + comp_labels
        vals1_actual = div_vals1 + comp_vals1
        vals2_actual = div_vals2 + comp_vals2
        raw1 = div_raw1 + comp_raw1
        raw2 = div_raw2 + comp_raw2

        # Normalise each spoke independently to [0, 1]
        vals1_norm, vals2_norm = [], []
        for v1, v2 in zip(vals1_actual, vals2_actual):
            spoke_max = max(v1, v2, 1e-9)
            vals1_norm.append(v1 / spoke_max)
            vals2_norm.append(v2 / spoke_max)

        r_angles = np.linspace(0, 2 * np.pi, len(spoke_labels), endpoint=False).tolist()
        r_angles_closed = r_angles + r_angles[:1]
        vals1_r = vals1_norm + vals1_norm[:1]
        vals2_r = vals2_norm + vals2_norm[:1]
        r_max = 1.0

        ax_r.set_theta_offset(np.pi / 2)
        ax_r.set_theta_direction(-1)

        for v_norm, v_r, raw, color, lbl in [
            (vals1_norm, vals1_r, raw1, COLORS[0], label1),
            (vals2_norm, vals2_r, raw2, COLORS[1], label2),
        ]:
            ax_r.plot(
                r_angles_closed, v_r, color=color, linewidth=2, label=lbl, alpha=0.9
            )
            ax_r.fill(r_angles_closed, v_r, color=color, alpha=0.15)
            ax_r.scatter(r_angles, v_norm, color=color, s=40, zorder=5)
            for angle, v, r in zip(r_angles, v_norm, raw):
                offset = r_max * 0.12
                ax_r.annotate(
                    r,
                    xy=(angle, v),
                    xytext=(angle, v + offset),
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    color=color,
                    fontweight="bold",
                    textcoords="data",
                )

        ax_r.set_thetagrids(
            np.degrees(r_angles), spoke_labels, fontsize=8, fontweight="bold"
        )
        ax_r.grid(True, color="#D5D8DC", linestyle="--", linewidth=0.7)
        ax_r.spines["polar"].set_visible(False)
        tick_values = np.linspace(0, r_max, 5)[1:]
        ax_r.set_yticks(tick_values)
        ax_r.set_rlabel_position(22.5)
        y_labels = [f"{v:.1f}" for v in tick_values]
        y_labels[0] = ""
        ax_r.set_yticklabels(y_labels, fontsize=7, color="#7B7D7D")
        ax_r.set_ylim(0, r_max * 1.4)
        ax_r.set_title("(a) Diversity & Comprehensiveness", pad=20)
    else:
        # Fallback: original 3-spoke diversity-only radar
        scalar_labels = [
            "Template Ratio",
            "Filter Template Ratio",
            "Entity Diversity",
            "Feature Entropy",
        ]
        vals1 = [
            metrics1["unique_template_ratio"],
            metrics1.get("filter_template_ratio", 0.0),
            metrics1["entity_diversity_ratio"],
            metrics1["feature_entropy"],
        ]
        vals2 = [
            metrics2["unique_template_ratio"],
            metrics2.get("filter_template_ratio", 0.0),
            metrics2["entity_diversity_ratio"],
            metrics2["feature_entropy"],
        ]
        N = len(scalar_labels)
        angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
        angles += angles[:1]
        vals1_closed = vals1 + vals1[:1]
        vals2_closed = vals2 + vals2[:1]
        ax_r.plot(
            angles, vals1_closed, "o-", color=COLORS[0], linewidth=2, label=label1
        )
        ax_r.fill(angles, vals1_closed, color=COLORS[0], alpha=0.15)
        ax_r.plot(
            angles, vals2_closed, "o-", color=COLORS[1], linewidth=2, label=label2
        )
        ax_r.fill(angles, vals2_closed, color=COLORS[1], alpha=0.15)
        ax_r.set_xticks(angles[:-1])
        ax_r.set_xticklabels(scalar_labels, fontsize=10)
        ax_r.set_title("(a) Structural Diversity Scalars", pad=20)

    # Single shared legend at the bottom
    legend_handles = [
        mpatches.Patch(color=COLORS[0], alpha=0.85, label=label1),
        mpatches.Patch(color=COLORS[1], alpha=0.85, label=label2),
    ]
    fig.legend(
        handles=legend_handles,
        loc="lower center",
        ncol=2,
        fontsize=11,
        frameon=False,
        bbox_to_anchor=(0.5, -0.04),
    )
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.15)
    save_fig(fig, "structural_diversity")
    if show:
        plt.show()
    else:
        plt.close(fig)
