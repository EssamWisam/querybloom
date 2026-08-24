import os

# Prevent tokenizers and OpenMP from crashing the Jupyter kernel on MacOS
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.manifold import TSNE
import warnings
from collections import defaultdict

from sentence_transformers import SentenceTransformer
from sparql_utils import analyze_sparql_features, analyze_query_size

import pandas as pd

# Styling for paper-ready plots
plt.style.use("seaborn-v0_8-whitegrid")
sns.set_context("paper", font_scale=1.5)
plt.rcParams["figure.dpi"] = 150  # Higher display resolution
plt.rcParams["savefig.dpi"] = 600  # Publication quality
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Arial", "DejaVu Sans"]

# Load the SBERT model globally for the module
sbert_model = SentenceTransformer("BAAI/bge-large-en-v1.5")
BGE_PREFIX = "Represent this sentence: "


def _embedding_diversity_metrics(embs: np.ndarray) -> tuple[float, float]:
    """Return (avg_pairwise_cosine_dist, mean_nn_cosine_dist) for a set of L2-normalised embeddings."""
    # Cosine similarity matrix → distance = 1 - sim
    sim = embs @ embs.T
    n = len(embs)
    # Average pairwise distance (upper triangle, excluding diagonal)
    mask = np.triu(np.ones((n, n), dtype=bool), k=1)
    apd = float(np.mean(1 - sim[mask]))
    # Mean nearest-neighbour distance: for each point, closest other point
    np.fill_diagonal(sim, -np.inf)
    nn_sim = sim.max(axis=1)
    mnnd = float(np.mean(1 - nn_sim))
    return apd, mnnd


def plot_semantic_embeddings(data1, data2, label1, label2):
    q1 = [item.get("question", "") for item in data1 if "question" in item]
    q2 = [item.get("question", "") for item in data2 if "question" in item]
    all_questions = q1 + q2
    labels = [label1] * len(q1) + [label2] * len(q2)

    print("Computing embeddings...")
    embeddings = sbert_model.encode(
        [BGE_PREFIX + q for q in all_questions], normalize_embeddings=True
    )

    idx1 = [i for i, l in enumerate(labels) if l == label1]
    idx2 = [i for i, l in enumerate(labels) if l == label2]

    embs1 = embeddings[idx1]
    embs2 = embeddings[idx2]

    apd1, mnnd1 = _embedding_diversity_metrics(embs1)
    apd2, mnnd2 = _embedding_diversity_metrics(embs2)

    print("Computing t-SNE projection...")
    perplexity = min(30, len(all_questions) - 1)
    tsne = TSNE(n_components=2, perplexity=perplexity, random_state=42)
    proj = tsne.fit_transform(embeddings)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    colors = ["#2E86C1", "#E67E22"]
    axes[0].scatter(
        proj[idx1, 0], proj[idx1, 1], alpha=0.7, color=colors[0], edgecolor="k", s=60
    )
    axes[0].set_title(f"{label1}\nAPD={apd1:.4f}  |  MNND={mnnd1:.4f}")
    axes[0].set_xlabel("t-SNE Dimension 1")
    axes[0].set_ylabel("t-SNE Dimension 2")

    axes[1].scatter(
        proj[idx2, 0], proj[idx2, 1], alpha=0.7, color=colors[1], edgecolor="k", s=60
    )
    axes[1].set_title(f"{label2}\nAPD={apd2:.4f}  |  MNND={mnnd2:.4f}")
    axes[1].set_xlabel("t-SNE Dimension 1")
    axes[1].set_ylabel("t-SNE Dimension 2")

    plt.tight_layout()
    plt.savefig("figures/semantic_space.pdf", dpi=300, bbox_inches="tight")
    plt.show()


def plot_sparql_features(data1, data2, label1, label2):
    q1 = [item.get("sparql", "") for item in data1 if "sparql" in item]
    q2 = [item.get("sparql", "") for item in data2 if "sparql" in item]

    FEATURE_KEYS = [
        "SELECT",
        "ASK",
        "OPTIONAL",
        "UNION",
        "FILTER",
        "EXISTS",
        "GROUP BY",
        "ORDER BY",
        "LIMIT",
        "Property Paths",
    ]

    def get_feature_dist(queries):
        if not queries:
            return {k: 0 for k in FEATURE_KEYS}

        counts = defaultdict(int)
        for q in queries:
            features = analyze_sparql_features(q)
            for k, v in features.items():
                counts[k] += v

        total = len(queries)
        return {k: (counts[k] / total) * 100 for k in FEATURE_KEYS}

    dist1 = get_feature_dist(q1)
    dist2 = get_feature_dist(q2)

    categories = FEATURE_KEYS
    values1 = [dist1[k] for k in categories]
    values2 = [dist2[k] for k in categories]

    x = np.arange(len(categories))
    width = 0.35

    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ["#2E86C1", "#E67E22"]  # Professional Steel Blue and Pumpkin Orange
    rects1 = ax.bar(
        x - width / 2,
        values1,
        width,
        label=label1,
        color=colors[0],
        edgecolor="k",
        alpha=0.8,
    )
    rects2 = ax.bar(
        x + width / 2,
        values2,
        width,
        label=label2,
        color=colors[1],
        edgecolor="k",
        alpha=0.8,
    )

    ax.set_ylabel("Percentage of Queries (%)")
    ax.set_title("SPARQL 1.1 Feature Distribution")
    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=45, ha="right")
    ax.legend()

    plt.tight_layout()
    plt.savefig("figures/sparql_features.pdf", dpi=300, bbox_inches="tight")
    plt.show()


def plot_query_sizes(data1, data2, label1, label2):
    q1 = [item.get("sparql", "") for item in data1 if "sparql" in item]
    q2 = [item.get("sparql", "") for item in data2 if "sparql" in item]

    records = []
    for q in q1:
        sizes = analyze_query_size(q)
        records.append(
            {
                "Dataset": label1,
                "Variables": sizes["num_variables"],
                "Triples": sizes["num_triples"],
            }
        )
    for q in q2:
        sizes = analyze_query_size(q)
        records.append(
            {
                "Dataset": label2,
                "Variables": sizes["num_variables"],
                "Triples": sizes["num_triples"],
            }
        )

    df = pd.DataFrame(records)

    fig, axes = plt.subplots(1, 2, figsize=(12, 6))

    colors = ["#2E86C1", "#E67E22"]
    sns.boxplot(data=df, x="Dataset", y="Variables", ax=axes[0], palette=colors)
    axes[0].set_title("Number of Variables per Query")
    axes[0].set_ylabel("Count")

    sns.boxplot(data=df, x="Dataset", y="Triples", ax=axes[1], palette=colors)
    axes[1].set_title("Number of Triples per Query")
    axes[1].set_ylabel("Count")

    plt.tight_layout()
    plt.savefig("figures/query_sizes.pdf", dpi=300, bbox_inches="tight")
    plt.show()


def plot_radar_summary(
    metrics_text, metrics_sparql, label1, label2, chart_type="radar"
):
    # Professional color palette
    colors = ["#2E86C1", "#E67E22"]  # Steel Blue and Pumpkin Orange

    def extract_radar_data(bench_text, bench_sparql, count):
        return [
            # bench_text.get('ttr', 0.5),                          # Vocab TTR
            bench_sparql.get("num_unique_entities", 0) / count,
            bench_sparql.get("num_unique_classes", 0)
            / count,  # Unique Class contribution
            bench_sparql.get("num_unique_relations", 0) / count,
            bench_sparql.get("num_variables_median", 0),
            bench_sparql.get("num_triples_median", 0),
            bench_sparql.get("num_classes_median", 0),
            bench_sparql.get("unique_templates_ratio", 1.0),
        ]

    labels = [
        "Unique Entities",
        "Unique Classes",
        "Unique Rel.",
        "Variables",
        "Triples",
        "Classes/Q",
        "Unique Temp.",
    ]

    values1 = extract_radar_data(
        metrics_text["benchmark1"],
        metrics_sparql["benchmark1"],
        metrics_sparql.get("bm1_size", 1),
    )
    values2 = extract_radar_data(
        metrics_text["benchmark2"],
        metrics_sparql["benchmark2"],
        metrics_sparql.get("bm2_size", 1),
    )

    if chart_type == "radar":
        angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()

        values1_radar = values1 + values1[:1]
        values2_radar = values2 + values2[:1]
        angles += angles[:1]

        r_max = max(
            max(values1), max(values2)
        )  # needed by both gridlines and annotation offset

        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True), dpi=150)

        ax.plot(
            angles, values1_radar, color=colors[0], linewidth=3, label=label1, alpha=0.9
        )
        ax.fill(angles, values1_radar, color=colors[0], alpha=0.15)
        ax.scatter(
            angles[:-1],
            values1,
            color=colors[0],
            s=50,
            zorder=5,
            edgecolor=colors[0],
            linewidth=1.5,
        )

        ax.plot(
            angles, values2_radar, color=colors[1], linewidth=3, label=label2, alpha=0.9
        )
        ax.fill(angles, values2_radar, color=colors[1], alpha=0.15)
        ax.scatter(
            angles[:-1],
            values2,
            color=colors[1],
            s=50,
            zorder=5,
            edgecolor=colors[1],
            linewidth=1.5,
        )

        # Annotate values at each dot
        for i, (angle, v1, v2) in enumerate(zip(angles[:-1], values1, values2)):
            # Increase margin slightly for specific blue numbers
            v1_offset = r_max * 0.16 if i in [3, 4, 5] else r_max * 0.10

            # Distinct margin adjustments for orange numbers
            if i in [4, 5]:  # Triples, Classes/Q
                v2_offset = r_max * 0.18
            elif i in [0, 3]:  # Unique Entities, Variables
                v2_offset = r_max * 0.14
            else:
                v2_offset = r_max * 0.10

            ax.annotate(
                f"{v1:.2f}",
                xy=(angle, v1),
                xytext=(angle, v1 + v1_offset),
                ha="center",
                va="bottom",
                fontsize=10,
                color=colors[0],
                fontweight="bold",
                textcoords="data",
            )
            ax.annotate(
                f"{v2:.2f}",
                xy=(angle, v2),
                xytext=(angle, v2 - v2_offset),
                ha="center",
                va="top",
                fontsize=10,
                color=colors[1],
                fontweight="bold",
                textcoords="data",
            )

        ax.set_theta_offset(np.pi / 2)
        ax.set_theta_direction(-1)
        ax.set_thetagrids(
            np.degrees(angles[:-1]), labels, fontsize=12, fontweight="bold"
        )

        # Refined gridlines
        ax.grid(True, color="#D5D8DC", linestyle="--", linewidth=0.7)
        ax.spines["polar"].set_visible(False)

        # Numbered concentric circles
        tick_values = np.linspace(0, r_max, 5)[1:]  # 4 circles, skip 0
        ax.set_yticks(tick_values)

        # Shift the radial labels so they don't collide with data/lines (e.g. angle them at 22.5 or 67.5 degrees)
        ax.set_rlabel_position(22.5)

        y_labels = [f"{v:.2f}" for v in tick_values]
        y_labels[0] = ""  # Hide the innermost circle's number

        ax.set_yticklabels(
            y_labels,
            fontsize=9,
            color="#7B7D7D",
        )
        ax.set_ylim(0, r_max * 1.25)

        # Legend: No border, shifted up slightly
        ax.legend(
            loc="lower center", bbox_to_anchor=(0.5, -0.05), ncol=2, frameon=False
        )

        plt.tight_layout()
        plt.savefig("figures/radar_summary.pdf", dpi=600, bbox_inches="tight")
        plt.savefig("figures/radar_summary.png", dpi=600, bbox_inches="tight")
        plt.show()
    elif chart_type == "bar":
        x = np.arange(len(labels))
        width = 0.35

        fig, ax = plt.subplots(figsize=(10, 6))
        rects1 = ax.bar(
            x - width / 2,
            values1,
            width,
            label=label1,
            color=colors[0],
            edgecolor="k",
            alpha=0.8,
        )
        rects2 = ax.bar(
            x + width / 2,
            values2,
            width,
            label=label2,
            color=colors[1],
            edgecolor="k",
            alpha=0.8,
        )

        ax.set_ylabel("Scores")
        ax.set_title("Holistic Benchmarking Diversity Space")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.legend()

        plt.tight_layout()
        plt.savefig("figures/bar_summary.pdf", dpi=300, bbox_inches="tight")
        plt.show()
    elif chart_type == "table":
        from IPython.display import display

        df = pd.DataFrame(
            {label1: values1, label2: values2},
            index=labels,
        ).round(4)
        display(df)
    else:
        raise ValueError("chart_type must be either 'radar' or 'bar'")


def plot_unique_entities_relations(metrics_sparql, label1, label2):
    labels = ["Unique Entities", "Unique Relations"]

    values1 = [
        metrics_sparql["benchmark1"].get("num_unique_entities", 0),
        metrics_sparql["benchmark1"].get("num_unique_relations", 0),
    ]

    values2 = [
        metrics_sparql["benchmark2"].get("num_unique_entities", 0),
        metrics_sparql["benchmark2"].get("num_unique_relations", 0),
    ]

    x = np.arange(len(labels))
    width = 0.35

    colors = ["#2E86C1", "#E67E22"]
    fig, ax = plt.subplots(figsize=(8, 6))
    rects1 = ax.bar(
        x - width / 2,
        values1,
        width,
        label=label1,
        color=colors[0],
        edgecolor="k",
        alpha=0.8,
    )
    rects2 = ax.bar(
        x + width / 2,
        values2,
        width,
        label=label2,
        color=colors[1],
        edgecolor="k",
        alpha=0.8,
    )

    ax.set_ylabel("Count")
    ax.set_title("Unique Entities and Relations Comparison")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()

    # Add exact counts on top of bars
    for rect in rects1:
        height = rect.get_height()
        ax.annotate(
            f"{height}",
            xy=(rect.get_x() + rect.get_width() / 2, height),
            xytext=(0, 3),  # 3 points vertical offset
            textcoords="offset points",
            ha="center",
            va="bottom",
        )

    for rect in rects2:
        height = rect.get_height()
        ax.annotate(
            f"{height}",
            xy=(rect.get_x() + rect.get_width() / 2, height),
            xytext=(0, 3),  # 3 points vertical offset
            textcoords="offset points",
            ha="center",
            va="bottom",
        )

    plt.tight_layout()
    plt.savefig("figures/unique_terms_comparison.pdf", dpi=300, bbox_inches="tight")
    plt.show()
