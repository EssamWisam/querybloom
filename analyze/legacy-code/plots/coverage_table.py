"""Coverage gap table: show sample classes/properties unique to each benchmark or missing from both."""

import random
import matplotlib.pyplot as plt

from .common import COLORS, save_fig

from metrics.comprehensiveness import gather_coverage_sets
from ontology_loader import load_ontology_classes, load_ontology_properties


_KNOWN_PREFIXES = {
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf:",
    "http://www.w3.org/2000/01/rdf-schema#": "rdfs:",
    "http://www.w3.org/2002/07/owl#": "owl:",
    "http://www.w3.org/2001/XMLSchema#": "xsd:",
    "http://xmlns.com/foaf/0.1/": "foaf:",
    "http://purl.org/dc/terms/": "dct:",
    "http://purl.org/dc/elements/1.1/": "dc:",
}


def _shorten(uri, max_len=50):
    """Shorten a URI for display using known prefixes or the last path/fragment segment."""
    for prefix, short in _KNOWN_PREFIXES.items():
        if uri.startswith(prefix):
            return (short + uri[len(prefix) :])[:max_len]
    for sep in ("#", "/"):
        if sep in uri:
            local = uri.rsplit(sep, 1)[-1]
            if local:
                return local[:max_len]
    return uri[:max_len]


def _sample(s, n):
    """Return a sorted random sample of up to *n* items from set *s*."""
    items = sorted(s)
    if len(items) <= n:
        return items
    return sorted(random.sample(items, n))


def plot_coverage_table(
    queries1,
    queries2,
    kg_name,
    label1,
    label2,
    endpoint="dblp",
    n_sample=8,
    seed=42,
    show=True,
):
    """Render a figure with two tables (classes & properties) showing coverage gaps.

    Columns:
        Only in <label1> | Only in <label2> | In Neither (uncovered by both)
    """
    random.seed(seed)

    cls1, prp1 = gather_coverage_sets(queries1, endpoint, kg_name)
    cls2, prp2 = gather_coverage_sets(queries2, endpoint, kg_name)

    onto_cls = load_ontology_classes(kg_name)
    onto_prp = load_ontology_properties(kg_name)

    # Keep only ontology-level terms (filter out meta-level URIs like
    # rdf:type, owl:Class, rdfs:Class that leak in from parsing / entity-type
    # resolution but are not part of the KG's own schema).
    cls1 = cls1 & onto_cls
    cls2 = cls2 & onto_cls
    prp1 = prp1 & onto_prp
    prp2 = prp2 & onto_prp

    # --- Classes ---
    cls_only1 = cls1 - cls2
    cls_only2 = cls2 - cls1
    cls_neither = onto_cls - cls1 - cls2

    # --- Properties ---
    prp_only1 = prp1 - prp2
    prp_only2 = prp2 - prp1
    prp_neither = onto_prp - prp1 - prp2

    datasets = [
        ("Classes", cls_only1, cls_only2, cls_neither),
        ("Properties", prp_only1, prp_only2, prp_neither),
    ]

    fig, axes = plt.subplots(2, 1, figsize=(14, 7))

    for ax, (kind, only1, only2, neither) in zip(axes, datasets):
        s1 = [_shorten(u) for u in _sample(only1, n_sample)]
        s2 = [_shorten(u) for u in _sample(only2, n_sample)]
        sn = [_shorten(u) for u in _sample(neither, n_sample)]

        n_rows = max(len(s1), len(s2), len(sn), 1)
        # Pad shorter columns with empty strings
        s1 += [""] * (n_rows - len(s1))
        s2 += [""] * (n_rows - len(s2))
        sn += [""] * (n_rows - len(sn))

        col_labels = [
            f"Only in {label1} ({len(only1)})",
            f"Only in {label2} ({len(only2)})",
            f"In Neither ({len(neither)})",
        ]
        cell_text = list(zip(s1, s2, sn))

        ax.axis("off")
        ax.set_title(f"{kind}", fontsize=14, fontweight="bold", pad=12)

        table = ax.table(
            cellText=cell_text,
            colLabels=col_labels,
            loc="center",
            cellLoc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1, 1.4)

        # Style header row
        for j, color in enumerate([COLORS[0], COLORS[1], "#7B7D7D"]):
            cell = table[0, j]
            cell.set_facecolor(color)
            cell.set_text_props(color="white", fontweight="bold")

        # Alternate row shading
        for i in range(1, n_rows + 1):
            for j in range(3):
                cell = table[i, j]
                cell.set_facecolor("#F8F9F9" if i % 2 == 0 else "white")
                cell.set_edgecolor("#D5D8DC")

    fig.suptitle(
        "Coverage Gaps: Classes & Properties", fontsize=15, fontweight="bold", y=0.98
    )
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    save_fig(fig, "coverage_gaps", extensions=("pdf", "png"))
    if show:
        plt.show()
    else:
        plt.close(fig)
