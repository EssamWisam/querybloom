"""Redundancy bar plot: per-feature redundancy rates side-by-side."""

import numpy as np
import matplotlib.pyplot as plt
from concurrent.futures import ThreadPoolExecutor
from IPython.display import display, HTML

import html as _html

from pygments import highlight as _pygments_highlight
from pygments.lexers import SparqlLexer as _SparqlLexer
from pygments.formatters import HtmlFormatter as _HtmlFormatter

from .common import COLORS, save_fig

_SPARQL_LEXER = _SparqlLexer()
_SPARQL_FMT = _HtmlFormatter(nowrap=True, style="monokai")


def plot_redundancy(red1, red2, label1, label2, show=True):
    """Side-by-side bar chart of feature-redundancy rates.

    Parameters
    ----------
    red1, red2 : dict
        Output of ``measure_redundancy``; must contain ``redundancy_rates``
        and ``_counts``.
    """
    rates1 = red1["redundancy_rates"]
    rates2 = red2["redundancy_rates"]
    counts1 = red1["_counts"]
    counts2 = red2["_counts"]

    features = list(rates1.keys())
    x = np.arange(len(features))
    w = 0.35

    fig, ax = plt.subplots(figsize=(10, 5))

    bars1 = ax.bar(
        x - w / 2,
        [rates1[f] for f in features],
        w,
        label=label1,
        color=COLORS[0],
        edgecolor="k",
        alpha=0.85,
    )
    bars2 = ax.bar(
        x + w / 2,
        [rates2[f] for f in features],
        w,
        label=label2,
        color=COLORS[1],
        edgecolor="k",
        alpha=0.85,
    )

    # Annotate bars with "redundant / has" counts
    for bars, counts in [(bars1, counts1), (bars2, counts2)]:
        for bar, feat in zip(bars, features):
            c = counts[feat]
            if c["has"] > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 1,
                    f'{c["redundant"]}/{c["has"]}',
                    ha="center",
                    va="bottom",
                    fontsize=8,
                )

    ax.set_ylabel("Redundancy Rate (%)")
    ax.set_title("Feature Redundancy (same results after removal)")
    ax.set_xticks(x)
    ax.set_xticklabels(features, rotation=30, ha="right")
    ax.set_ylim(
        0,
        min(
            100,
            max(
                max(rates1.values(), default=0),
                max(rates2.values(), default=0),
            )
            + 15,
        ),
    )
    ax.legend()

    plt.tight_layout()
    save_fig(fig, "feature_redundancy")
    if show:
        plt.show()
    else:
        plt.close(fig)


def _get_css():
    """Build the CSS string including Pygments token styles."""
    pygments_css = _HtmlFormatter(style="monokai").get_style_defs(".sparql-hl")
    return f"""
<style>
{pygments_css}
.red-table {{ border-collapse: collapse; width: 100%; font-size: 12px; table-layout: fixed; }}
.red-table th {{ background: #1e1e2e; color: #cdd6f4; padding: 6px 10px; text-align: left; }}
.red-table th:first-child {{ width: 40%; }}
.red-table th:last-child  {{ width: 60%; }}
.red-table td {{ padding: 6px 10px; vertical-align: top; border-bottom: 1px solid #45475a; color: #cdd6f4; overflow: hidden; }}
.red-table tr:nth-child(even) td {{ background: #181825; }}
.red-table .sparql-hl {{ font-family: monospace; font-size: 11px; white-space: pre-wrap; word-break: break-all; text-align: left; direction: ltr; }}
.red-table .sparql-hl span {{ font-style: normal !important; font-weight: normal !important; }}
.nl  {{ font-style: italic; font-weight: bold; font-size: 13px; color: #89b4fa; text-align: left; }}
.feat-header {{ font-size: 15px; font-weight: bold; margin: 20px 0 6px 0;
               color: #cdd6f4; background: #313244; padding: 6px 12px;
               border-radius: 4px; display: inline-block; }}
</style>
"""


def _highlight_sparql(code):
    """Return syntax-highlighted HTML for a SPARQL snippet."""
    inner = _pygments_highlight(code, _SPARQL_LEXER, _SPARQL_FMT)
    return f'<div class="sparql-hl">{inner}</div>'


def show_redundancy_examples(
    queries, questions, query_endpoint, examples_per_feature=5, exclude=("DISTINCT",)
):
    """Display an HTML table of redundant queries per SPARQL feature.

    For each feature (DISTINCT, FILTER, OPTIONAL, …) finds every query where
    that feature is redundant (removing it yields identical results) and shows
    the paired NL question alongside the SPARQL, so you can judge whether the
    question itself justifies the feature or it is a spurious artefact.

    Parameters
    ----------
    queries : list[str]
        SPARQL queries to audit.
    questions : list[str]
        Parallel list of NL questions (same length as *queries*).
    query_endpoint : str
        Endpoint alias used to execute queries.
    examples_per_feature : int
        Max redundant examples to display per feature (default 5).
    """
    from metrics.redundancy import (
        REDUNDANCY_FEATURES,
        REMOVERS,
        _execute_cached,
        _add_safety_limit,
        _results_match,
    )
    from metrics.parsing import analyze_sparql_features

    features = [f for f in REDUNDANCY_FEATURES if f not in exclude]

    # 1. collect per-query feature flags
    print("Detecting redundant queries …")
    feature_flags = [analyze_sparql_features(q) for q in queries]

    # build work list: (query_idx, feature, original_sparql, modified_sparql)
    work = []
    for i, q in enumerate(queries):
        for feat in features:
            if feature_flags[i].get(feat, 0):
                modified = REMOVERS[feat](q)
                if modified.strip() == q.strip():
                    continue
                work.append((i, feat, q, _add_safety_limit(modified)))

    # deduplicate queries to execute
    all_queries = {}
    for _, _, orig, mod in work:
        all_queries[orig] = None
        all_queries[mod] = None

    def _run(query):
        return query, _execute_cached(query, query_endpoint)

    print(f"  Running / loading {len(all_queries)} unique queries …")
    with ThreadPoolExecutor(max_workers=4) as pool:
        for query, resp in pool.map(_run, all_queries.keys()):
            all_queries[query] = resp

    # 2. classify redundant (query_idx, feature) pairs
    redundant_examples = {f: [] for f in features}
    for idx, feat, orig, mod in work:
        order_sensitive = feat == "ORDER BY"
        if _results_match(
            all_queries[orig], all_queries[mod], order_sensitive=order_sensitive
        ):
            redundant_examples[feat].append(idx)

    # 3. render HTML
    html_parts = [_get_css()]
    for feat in features:
        idxs = redundant_examples[feat]
        total_with_feat = sum(1 for f in feature_flags if f.get(feat, 0))
        n_red = len(idxs)
        pct = (n_red / total_with_feat * 100) if total_with_feat else 0.0

        html_parts.append(
            f'<div class="feat-header">{feat} &nbsp;—&nbsp; '
            f"{n_red}/{total_with_feat} queries redundant ({pct:.0f}%)</div>"
        )

        if not idxs:
            html_parts.append("<p><em>No redundant instances found.</em></p>")
            continue

        rows = []
        for i in idxs[:examples_per_feature]:
            nl = questions[i] if i < len(questions) else "<no question>"
            sparql_html = _highlight_sparql(queries[i])
            rows.append(
                f"<tr>"
                f'<td class="nl">{_html.escape(nl)}</td>'
                f"<td>{sparql_html}</td>"
                f"</tr>"
            )

        html_parts.append(
            '<table class="red-table">'
            "<tr><th>NL Question</th><th>SPARQL Query</th></tr>"
            + "".join(rows)
            + "</table><br>"
        )

    display(HTML("".join(html_parts)))
    print("Done.")
