# Benchmark Evaluation Redesign Plan

## Current State (Status Quo)

The analysis pipeline lives in three files under `analyze/`:

### `sparql_utils.py` — SPARQL-side metrics
- **Per-query feature flags:** binary presence of SPARQL keywords (`SELECT`, `ASK`, `OPTIONAL`, `UNION`, `FILTER`, `EXISTS`, `GROUP BY`, `ORDER BY`, `LIMIT`, Property Paths).
- **Per-query size metrics via rdflib AST:** number of variables, triples, classes used.
- **Corpus-level aggregates:** means/medians/stds of the above; unique template ratio (anonymised query skeleton deduplication); unique entity/relation/class counts and ratios.
- Entry point: `measure_syntactic_diversity(data1, data2)` → returns a flat dict of aggregated numbers per benchmark.

### `text_utils.py` — NL question-side metrics
- **Lexical:** word/char length stats, Type-Token Ratio (TTR).
- **Semantic:** pairwise cosine distance (SBERT or TF-IDF fallback).
- **Self-BLEU:** generation diversity (lower = more diverse).
- **Syntactic complexity (spaCy):** parse tree depth, noun-chunk density.
- Entry point: `measure_semantic_diversity(data1, data2)` → flat dict per benchmark.

### `visualization_utils.py` — Plotting
| Plot | What it shows |
|------|---------------|
| `plot_semantic_embeddings` | t-SNE of NL questions with APD/MNND annotations |
| `plot_sparql_features` | Grouped bar chart of SPARQL keyword % |
| `plot_query_sizes` | Box plots of #variables and #triples per query |
| `plot_radar_summary` | Radar/bar/table combining a mix of everything |
| `plot_unique_entities_relations` | Bar chart of raw unique entity/relation counts |

### Problems with the status quo
1. **No conceptual separation.** Diversity, comprehensiveness, and complexity metrics are entangled. The radar lumps "unique entities per query" (comprehensiveness) with "median triples" (complexity) and "unique template ratio" (diversity).
2. **Comprehensiveness is never measured.** We count unique entities/relations/classes in the benchmark but never compare them to what the KG actually contains. 200 unique classes out of 200 available is very different from 200 out of 50,000.
3. **Redundant metrics.** Self-BLEU measures surface n-gram overlap — a strictly weaker signal than pairwise embedding distance, which already captures semantic similarity. TTR is known to be corpus-size-dependent and unstable. Question length is superficial and not informative for structural analysis.
4. **Complexity is underspecified.** Only parse-tree depth and noun chunks on the NL side; SPARQL keyword presence shows feature variety across the corpus but not per-query structural difficulty.

---

## Design Principles

1. **Two dimensions, not three.** Complexity is not a useful standalone claim ("our benchmark is harder") — what matters is that a benchmark *spans a range* of difficulty levels. That's a diversity argument. Complexity metrics (operator count, triple count, nesting depth) are absorbed into diversity as "structural complexity spread."
2. **No redundancy.** Every metric captures information not subsumed by another. If two metrics correlate strongly by construction, keep only the more interpretable one.
3. **Reference-grounded where possible.** Comprehensiveness is meaningless without a reference (the KG ontology). Raw counts alone are not metrics.
4. **Distribution-aware.** Where a per-query quantity exists, show the distribution (violin/box), not just a mean.
5. **One figure per dimension, zero redundancy.** Each metric appears in exactly one figure. The radar is the *base* comprehensiveness figure (not a summary that re-plots diversity metrics).

---

## Why Not a Separate Complexity Dimension?

Claiming "our benchmark generates harder queries" is a weak paper argument:
- A reviewer can respond "so what? harder doesn't mean better."
- If the baseline happens to be more complex, you'd be arguing against yourself.

What *is* meaningful: the benchmark **spans a range of complexity levels** — simple 1-triple ASK queries *and* multi-join OPTIONAL+FILTER+GROUP BY queries co-exist. This is evidence of **structural diversity**, not a separate axis. The spread/variance of complexity distributions is what tells the story, and that's a diversity sub-metric.

---

## Proposed Taxonomy

Two orthogonal dimensions: **Diversity** and **Comprehensiveness**.

### Dimension 1 — Diversity

> *"How varied are the benchmark items — semantically, structurally, and in difficulty?"*

Diversity measures intra-benchmark spread across three facets: semantic spread of NL questions, structural variety of SPARQL queries, and range of complexity levels.

#### 1a. Semantic Diversity (NL questions)

| Metric | What it captures | Notes |
|--------|-----------------|-------|
| **Average Pairwise Distance (APD)** | Global semantic spread of NL questions in embedding space (SBERT). | Scalar ∈ [0, 1]. Higher = more spread. Existing. |
| **Mean Nearest-Neighbour Distance (MNND)** | Local clustering — are there near-duplicate questions? | Complementary to APD: APD can be high while MNND is low if points form well-separated clusters. Existing in `visualization_utils`; consolidate into compute module. |

#### 1b. Structural Diversity (SPARQL queries)

| Metric | What it captures | Notes |
|--------|-----------------|-------|
| **Unique Template Ratio** | Fraction of structurally distinct query skeletons after anonymising variables, URIs, and literals. | Scalar ∈ [0, 1]. Higher = more structural variety. Existing. |
| **Feature Distribution Entropy** | Shannon entropy of the SPARQL feature presence vector (column means of the 10-dim binary vector, normalised to a probability distribution). | Captures how *evenly* operators are used across the corpus, not just which ones appear. **New.** |
| **Entity Diversity Ratio** | unique entities / total entity mentions across all queries. | High → each query touches fresh parts of the KG. Existing (rename from `unique_to_total_entities_ratio`). |

#### 1c. Complexity Spread (diversity *of* difficulty)

These are per-query quantities whose **distributions** (violin/box plots) show that the benchmark spans a range of difficulty levels. Their **standard deviations** serve as scalar diversity metrics on the radar.

| Metric | What it captures | Notes |
|--------|-----------------|-------|
| **Operator Count per Query** | Sum of binary feature flags for each query (e.g., OPTIONAL + FILTER + GROUP BY = 3). | Best single proxy for SPARQL structural complexity. **New** (trivial from existing per-query feature extraction). |
| **Triple Count per Query** | Number of triple patterns per query. | Measures query *size*. Existing; show distribution. |

**Dropped from current codebase:**
- *Self-BLEU:* Noisier proxy for the same latent quantity APD captures. Redundant.
- *TTR:* Corpus-size-dependent and unstable. Unreliable for comparison.
- *Question length stats:* Superficial side-effect of complexity, not independently informative.
- *Noun-chunk density:* Correlates strongly with parse-tree depth. Not independent.
- *Parse-tree depth:* Spacy-dependent, fragile on short questions, and the SPARQL-side complexity metrics already capture structural difficulty more directly. Deferred.

#### Figures: Diversity

**Figure 1 — Semantic Diversity:** t-SNE scatter (one subplot per benchmark), annotated with APD and MNND.

**Figure 2 — Structural & Complexity Diversity (3 panels):**

| Panel | Content |
|-------|---------|
| **(a) SPARQL Feature Distribution** | Grouped bar chart of % of queries using each operator, with Feature Entropy annotated. |
| **(b) Complexity Distributions** | Violin or box plots of Operator Count and Triple Count — side-by-side per benchmark. Shows the *spread* of difficulty levels. |
| **(c) Template & Entity Diversity** | Two grouped bars: Unique Template Ratio and Entity Diversity Ratio per benchmark. |

---

### Dimension 2 — Comprehensiveness

> *"How much of the knowledge graph's schema does the benchmark exercise?"*

Comprehensiveness is a coverage metric requiring a **reference**: the KG's ontology. We have YAML schemas for SoCKG; for DBpedia the ontology OWL file or a SPARQL endpoint provides the reference.

| Metric | What it captures | Notes |
|--------|-----------------|-------|
| **Class Coverage** | \|classes in benchmark\| / \|classes in ontology\| | Classes from `rdf:type` objects + entity-type resolution. **New ratio.** Ontology reference from `kgs_data/<kg>/<kg>_classes.yaml`. |
| **Property Coverage** | \|properties in benchmark\| / \|properties in ontology\| | Properties from predicate positions. **New ratio.** Ontology reference from `kgs_data/<kg>/<kg>_props.yaml`. |
| **Feature Coverage** | \|SPARQL 1.1 features used at least once\| / \|total tracked features\| | How much of the SPARQL language the benchmark exercises. **New ratio.** |

**Not included (and why):**
- *Entity coverage (unique entities / total KG entities):* Negligibly small for large KGs (~6M entities in DBpedia). Uninformative.
- *Domain coverage (top-level ontology branches):* Requires standardised class hierarchies not all KGs provide. Deferred.
- *Answer-Type Entropy:* Requires execution results (not stored in JSONL) or query-form inference that is unreliable for bare SELECT queries. Dropped.
- *Nesting Depth:* rdflib normalises queries into left-deep trees; the algebra depth does not reflect user-perceived nesting. Operator Count already captures structural complexity. Dropped.

#### Figure 3 — Comprehensiveness Radar

A radar chart with **3 spokes**, one per comprehensiveness metric. Each benchmark is a polygon overlay. This is not a summary figure — it IS the comprehensiveness visualization. No bar chart is needed because the radar already shows the coverage profile across all three axes.

| Spoke | Scalar | Normalisation |
|-------|--------|---------------|
| **Class Coverage** | \|classes in benchmark\| / \|classes in ontology\| | Already ∈ [0, 1] |
| **Property Coverage** | \|properties in benchmark\| / \|properties in ontology\| | Already ∈ [0, 1] |
| **Feature Coverage** | \|features used\| / \|features tracked\| | Already ∈ [0, 1] |

Annotate each spoke with raw counts (e.g., "42 / 685") so the reader sees both the ratio and the absolute numbers. Legend distinguishes benchmarks by color.

#### Prerequisite: `ontology_loader.py`
A small module that:
1. Loads per-KG `_classes.yaml` and `_props.yaml` from `nl2sparql/kgs_data/<kg>/`.
2. Returns `set[str]` of all class URIs and `set[str]` of all property URIs (deduplicated).
3. YAML format: list of `{class: URI, count: N}` / `{property: URI, ...}`.

---

## Orthogonality Check

| | Diversity | Comprehensiveness |
|---|-----------|-------------------|
| **Question** | How *different* are items from each other (semantically, structurally, in difficulty)? | How much of the *reference space* is touched? |
| **Can be high while other is low?** | Yes: many varied queries all touching the same 3 classes. | Yes: covers 90% of properties but all queries are identical ASK with 1 triple. |
| **Key distinction** | Intra-set variance | Coverage against external reference |

---

## Figure Summary

| Figure | Dimension | Content |
|--------|-----------|--------|
| **Fig 1** | Diversity: Semantic | t-SNE scatter with APD/MNND |
| **Fig 2** | Diversity: Structural & Complexity | Feature bars + complexity violins + template/entity bars |
| **Fig 3** | Comprehensiveness | Radar chart (4 spokes: class/property/feature coverage + answer-type entropy) |

Three figures, zero redundancy — each metric appears in exactly one figure.

---

## File Organisation

```
analyze/
├── metrics/
│   ├── __init__.py          # Re-exports measure_diversity, measure_comprehensiveness
│   ├── parsing.py           # Shared: rdflib AST walk, feature extraction, query anonymisation
│   ├── diversity.py         # APD, MNND, unique template ratio, feature entropy, entity diversity,
│   │                        #   operator count, triple count distributions
│   └── comprehensiveness.py # Class/property/feature coverage
├── plots/
│   ├── __init__.py
│   ├── common.py            # Shared styling, color palette, save helper
│   ├── diversity_plots.py   # Figure 1 (t-SNE) + Figure 2 (structural & complexity distributions)
│   └── comprehensiveness_plots.py  # Figure 3 (comprehensiveness radar + raw-count annotations)
├── ontology_loader.py       # Load ontology reference (YAML / OWL / SPARQL fallback)
├── visualize.ipynb          # Main notebook: load data → 4 figures + summary table
├── metrics.md               # Updated metric definitions
└── REDESIGN_PLAN.md         # This file
```

### Migration path
1. Extract `parsing.py` from the shared AST-walk and feature-extraction code currently in `sparql_utils.py`.
2. Build `diversity.py` by moving APD/MNND (from `visualization_utils`), template ratio / entity diversity (from `sparql_utils`), and adding feature entropy + per-query complexity distributions (operator count, nesting depth).
3. Build `comprehensiveness.py` + `ontology_loader.py` (entirely new).
4. Build the plot modules with consistent styling from `plots/common.py` (radar logic lives in `comprehensiveness_plots.py`).
5. Rewrite the notebook to produce 3 figures in sequence + a summary table.

---

## Notebook Outline

| Section | Figures | Code |
|---------|---------|------|
| Load data | — | Load JSONL, balance sizes |
| **Diversity: Semantic** | Fig 1: t-SNE with APD/MNND | `measure_diversity()` → `plot_semantic_space()` |
| **Diversity: Structural & Complexity** | Fig 2: Feature bars + complexity violins + template/entity bars | `plot_structural_diversity()` |
| **Comprehensiveness** | Fig 3: Radar (4 spokes) | `measure_comprehensiveness()` → `plot_comprehensiveness_radar()` |
| Metrics table | — | Print all scalars in a comparison table |
