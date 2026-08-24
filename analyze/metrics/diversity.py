"""Diversity metrics: semantic, structural, and complexity spread."""

import os
import sys
import re
import json
import hashlib
import numpy as np
import warnings
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))
try:
    from querybloom.executor.sparql_executor import (
        execute_sparql_query as _execute_sparql_query,
    )
except Exception:
    _execute_sparql_query = None

from .parsing import (
    analyze_sparql_features,
    extract_filter_subtypes,
    extract_filter_templates,
    parse_and_extract_rdflib_metrics,
    anonymise_query,
    FEATURE_KEYS,
)

try:
    from sentence_transformers import SentenceTransformer

    HAS_SBERT = True
except ImportError:
    HAS_SBERT = False


# ---------------------------------------------------------------------------
# 1a. Semantic Diversity (NL questions)
# ---------------------------------------------------------------------------


from ._cache import _make_key, _CACHE_ROOT

_EMB_CACHE_DIR = os.path.join(_CACHE_ROOT, "embeddings")


def _get_model_name(model):
    """Extract a stable model name string from a SentenceTransformer instance."""
    model_name = getattr(model, "model_card_data", None)
    if model_name is None:
        model_name = ""
    else:
        model_name = getattr(model_name, "model_name", "") or ""
    if not model_name:
        try:
            model_name = model[0].auto_model.config._name_or_path
        except Exception:
            model_name = ""
    return model_name


def compute_embeddings(questions, model):
    """Encode questions with given SentenceTransformer model, L2-normalised.

    Results are cached on disk (as .npy) so repeated calls with the same
    questions and model skip the encoding step.
    """
    if os.environ.get("METRICS_NO_CACHE") != "1":
        model_name = _get_model_name(model)
        cache_key = _make_key(model_name, sorted(questions))
        os.makedirs(_EMB_CACHE_DIR, exist_ok=True)
        cache_path = os.path.join(_EMB_CACHE_DIR, f"{cache_key}.npy")

        if os.path.exists(cache_path):
            return np.load(cache_path)
    else:
        model_name = _get_model_name(model)
        cache_path = None

    prefix = ""
    if "bge" in model_name.lower():
        prefix = "Represent this sentence: "
    embs = model.encode([prefix + q for q in questions], normalize_embeddings=True)

    if cache_path is not None:
        np.save(cache_path, embs)
    return embs


def embedding_diversity_metrics(embs: np.ndarray) -> tuple[float, float]:
    """Return (APD, Vendi Score) for a set of L2-normalised embeddings.

    The Vendi Score is the matrix-entropy-based diversity measure:
        VS(K) = exp( -sum_i lambda_i * log(lambda_i) )
    where lambda_i are the eigenvalues of the normalised kernel matrix K/n
    and K_ij = cosine_similarity(i, j).
    """
    sim = embs @ embs.T
    n = len(embs)
    mask = np.triu(np.ones((n, n), dtype=bool), k=1)
    apd = float(np.mean(1 - sim[mask]))
    eigenvalues = np.linalg.eigvalsh(sim / n)
    eigenvalues = eigenvalues[eigenvalues > 0]
    vendi = float(np.exp(-np.sum(eigenvalues * np.log(eigenvalues))))
    return apd, vendi


# ---------------------------------------------------------------------------
# 1b. Structural Diversity (SPARQL queries)
# ---------------------------------------------------------------------------


def unique_template_ratio(queries):
    """Fraction of structurally distinct query skeletons after anonymisation."""
    templates = [anonymise_query(q) for q in queries]
    return len(set(templates)) / len(queries) if queries else 0.0


def filter_template_ratio(queries):
    """Fraction of structurally distinct FILTER clause templates.

    Extracts every FILTER clause from every query, anonymises each one,
    and returns unique_filter_templates / total_filter_clauses.
    Returns 0.0 if no FILTER clauses exist.
    """
    all_templates = []
    for q in queries:
        all_templates.extend(extract_filter_templates(q))
    if not all_templates:
        return 0.0
    return len(set(all_templates)) / len(all_templates)


def feature_distribution_entropy(feature_matrix: np.ndarray) -> float:
    """Shannon entropy of the column-mean probability vector of the binary feature matrix.

    A uniform distribution across all 10 features → max entropy;
    all queries using only SELECT → low entropy.
    """
    col_means = feature_matrix.mean(axis=0)
    total = col_means.sum()
    if total == 0:
        return 0.0
    p = col_means / total
    p = p[p > 0]
    return float(-np.sum(p * np.log2(p)))


def entity_diversity_ratio(queries, endpoint="dblp"):
    """unique entities / total entity mentions across all queries."""
    unique = set()
    total = 0
    for q in queries:
        m = parse_and_extract_rdflib_metrics(q, endpoint)
        unique.update(m["entities"])
        total += len(m["entities"])
    return len(unique) / total if total > 0 else 0.0


# ---------------------------------------------------------------------------
# 1c. Complexity Spread (per-query distributions)
# ---------------------------------------------------------------------------


def per_query_operator_count(queries):
    """Sum of binary feature flags per query (excluding SELECT/ASK form flags)."""
    structural_keys = [k for k in FEATURE_KEYS if k not in ("SELECT", "ASK")]
    counts = []
    for q in queries:
        feats = analyze_sparql_features(q)
        counts.append(sum(feats[k] for k in structural_keys))
    return np.array(counts)


def per_query_triple_count(queries, endpoint="dblp"):
    """Number of triple patterns per query."""
    return np.array(
        [parse_and_extract_rdflib_metrics(q, endpoint)["num_triples"] for q in queries]
    )


def per_query_result_and_column_count(queries, query_endpoint=None, max_workers=7):
    """Execute each query and return (row_counts, col_counts) arrays.

    Queries are dispatched in parallel (up to *max_workers* concurrent requests).
    Results are cached on disk so repeated calls with the same queries and
    endpoint skip the network entirely.

    Falls back to zeros if query_endpoint is None or executor unavailable.
    """
    if _execute_sparql_query is None or query_endpoint is None:
        return np.zeros(len(queries), dtype=int), np.zeros(len(queries), dtype=int)

    _CACHE_DIR = os.path.join(
        os.path.dirname(__file__), "..", "..", "cache", "query_counts"
    )
    os.makedirs(_CACHE_DIR, exist_ok=True)

    def _cache_key(q: str) -> str:
        return hashlib.md5(f"{query_endpoint}||{q}".encode()).hexdigest()

    def _cache_path(key: str) -> str:
        return os.path.join(_CACHE_DIR, f"{key}.json")

    def _fetch(idx: int, q: str):
        key = _cache_key(q)
        path = _cache_path(key)
        is_ask = bool(re.search(r"\bASK\b", q, re.IGNORECASE))
        if os.path.exists(path):
            try:
                with open(path) as f:
                    cached = json.load(f)
                rows, cols = cached["rows"], cached["cols"]
                # Correct stale cache entries for ASK queries (previously stored as rows/cols=0)
                if is_ask and cols == 0:
                    cols = 1
                if is_ask and rows == 0:
                    rows = 1
                return idx, rows, cols
            except Exception:
                pass
        rows, cols = 0, 0
        try:
            res = _execute_sparql_query(q, endpoint=query_endpoint)
            if is_ask:
                # ASK queries return a single boolean — treat as 1 row, 1 col
                rows, cols = 1, 1
            elif res.get("success") and res.get("results") is not None:
                results = res["results"]
                rows = len(results) if isinstance(results, list) else 0
                if results:
                    cols = len(results[0])
                else:
                    try:
                        raw = json.loads(res.get("full_response") or "{}")
                        cols = len(raw.get("head", {}).get("vars", []))
                    except Exception:
                        cols = 0
        except Exception:
            pass
        try:
            with open(_cache_path(key), "w") as f:
                json.dump({"rows": rows, "cols": cols}, f)
        except Exception:
            pass
        return idx, rows, cols

    row_counts = [0] * len(queries)
    col_counts = [0] * len(queries)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch, i, q): i for i, q in enumerate(queries)}
        for future in as_completed(futures):
            idx, rows, cols = future.result()
            row_counts[idx] = rows
            col_counts[idx] = cols

    return np.array(row_counts), np.array(col_counts)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def measure_diversity(
    queries, questions, endpoint="dblp", sbert_model=None, query_endpoint=None
):
    """Compute all diversity metrics for one benchmark.

    Args:
        queries: list of SPARQL strings.
        questions: list of NL question strings.
        endpoint: SPARQL endpoint name for entity-type resolution.
        sbert_model: a loaded SentenceTransformer instance (or None to skip semantic).
        query_endpoint: SPARQL endpoint to execute queries against for result-row counts.
                        If None, result counts will be all zeros.

    Returns:
        dict with scalar metrics and per-query arrays.
    """
    result = {}

    # -- Semantic --
    if sbert_model is not None and questions:
        embs = compute_embeddings(questions, sbert_model)
        apd, vendi = embedding_diversity_metrics(embs)
        result["apd"] = round(apd, 4)
        result["vendi"] = round(vendi, 4)
        result["_embeddings"] = embs  # kept for plotting, prefixed _ = not a metric

    # -- Structural --
    if queries:
        result["unique_template_ratio"] = round(unique_template_ratio(queries), 4)
        result["filter_template_ratio"] = round(filter_template_ratio(queries), 4)
        result["entity_diversity_ratio"] = round(
            entity_diversity_ratio(queries, endpoint), 4
        )

        # Feature matrix (N × 10)
        feat_rows = [analyze_sparql_features(q) for q in queries]
        feat_matrix = np.array([[r[k] for k in FEATURE_KEYS] for r in feat_rows])
        result["feature_entropy"] = round(feature_distribution_entropy(feat_matrix), 4)
        # Feature percentages for plotting
        result["_feature_pcts"] = {
            k: round(float(feat_matrix[:, i].mean() * 100), 1)
            for i, k in enumerate(FEATURE_KEYS)
        }

        # -- Filter subtype percentages (auto-discovered from SPARQL spec) --
        n = len(queries)
        subtype_counts: dict[str, int] = {}
        for q in queries:
            for st in extract_filter_subtypes(q):
                subtype_counts[st] = subtype_counts.get(st, 0) + 1
        filter_subtype_pcts = {
            st: round(count / n * 100, 1) for st, count in subtype_counts.items()
        }
        result["_feature_pcts"].update(filter_subtype_pcts)
        result["_filter_subtype_keys"] = sorted(filter_subtype_pcts.keys())

        # -- Complexity spread --
        result["_operator_counts"] = per_query_operator_count(queries)
        result["_result_counts"], result["_column_counts"] = (
            per_query_result_and_column_count(queries, query_endpoint)
        )
        result["operator_count_std"] = round(float(result["_operator_counts"].std()), 4)
        result["result_count_std"] = round(float(result["_result_counts"].std()), 4)
        result["column_count_std"] = round(float(result["_column_counts"].std()), 4)

    return result
