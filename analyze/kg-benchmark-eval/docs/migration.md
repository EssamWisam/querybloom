# Migration from the legacy analysis modules

The package ports algorithms from `metrics/parsing.py`, `metrics/diversity.py`,
`metrics/comprehensiveness.py`, `metrics/redundancy.py`, `ontology_loader.py`,
and the QALD visualization workflow. It does not import those files at runtime.

## Intentional corrections

| Legacy behavior | Package behavior |
| --- | --- |
| Entity breadth was rounded to an integer by the top-level aggregator. | `distinct_entities_per_query` returns the unrounded documented ratio. |
| Embedding cache keys sorted questions but stored vectors in input order. | Keys include the ordered question sequence, including duplicates. |
| Redundancy cache keys omitted endpoint identity. | Keys include URL, snapshot/session, graphs, access scope, timeout, and exact text. |
| Executor exceptions escaped redundancy evaluation. | They become typed failure observations and count as eligible, non-redundant pairs. |
| The QALD notebook omitted the filename-dependent repair argument. | `Benchmark` stores an explicit resolved `qald9` normalization profile. |
| Missing ontology files could leave nonzero raw numerators with a zero ratio. | This value is retained and marked `degraded`. |
| Coverage plots reparsed and re-resolved queries. | Plots use stored covered sets and ontology universes. |
| Entity diagnostics counted raw parser candidates. | Entity diagnostics use stored resolved entities. |
| Redundancy HTML re-detected features and re-executed queries. | HTML uses stored pair outcomes and the metric's eligible denominator. |
| Histogram/KDE row handling was asymmetric and could clip operator count 11. | Both inputs use the same display rules and a 0-12 axis. |
| Plot imports changed global style and wrote fixed filenames. | Plot functions use local style state, return figures, and perform no writes. |

The resolver intentionally retains endpoint-implied types, query-local evolving
class classification, indexed fallback on falsey type evidence, duplicate entity
occurrences, heuristic property-path detection, and set-based redundancy values.
Those are methodology constraints, not implementation accidents corrected here.