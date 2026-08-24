"""
Derive empirical (data-driven) domain-range pairs for sockg-local using ABSTAT,
then write a YAML in the same format as sockg_property_domain_ranges.yaml:

  classes:
    <DomainLocalName>:
      <propertyLocalName>: <rangeLocalName>
"""

import sys
from pathlib import Path
from collections import defaultdict

import yaml

# ── path setup ────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent          # .../grasp/
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

from querybloom.subgraph_miner import SubgraphMiner  # noqa: E402

ENDPOINT    = "sockg-local"
MIN_SUPPORT = 10        # minimum occurrences to consider a (domain, prop, range) real
OUT_FILE    = _HERE / "sockg_empirical_domain_ranges.yaml"


# ── helpers ───────────────────────────────────────────────────────────────────

def local_name(uri: str) -> str:
    """Return the local fragment of a URI (after last # or /)."""
    for sep in ("#", "/"):
        idx = uri.rfind(sep)
        if idx != -1:
            return uri[idx + 1:]
    return uri


def build_domain_indexed(pattern_counts: dict, attribute_counts: dict) -> dict:
    """
    pattern_counts:  {(subject_type_uri, property_uri, object_type_uri): count}  — object props
    attribute_counts:{(subject_type_uri, property_uri, datatype_uri):    count}  — literal props
    Returns the same nested structure as the ontology file:
      { DomainLocal: { propLocal: rangeLocal | [rangeLocal, ...] } }
    """
    # domain -> property -> set of ranges
    by_domain: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for (s_uri, p_uri, o_uri), count in {**pattern_counts, **attribute_counts}.items():
        dom_key  = local_name(s_uri)
        prop_key = local_name(p_uri)
        rng_val  = local_name(o_uri)
        by_domain[dom_key][prop_key].add(rng_val)

    classes: dict = {}
    for dom_key in sorted(by_domain):
        props_out: dict = {}
        for prop_key in sorted(by_domain[dom_key]):
            ranges = sorted(by_domain[dom_key][prop_key])
            if len(ranges) == 1:
                props_out[prop_key] = ranges[0]
            else:
                props_out[prop_key] = ranges
        classes[dom_key] = props_out

    return classes


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    miner = SubgraphMiner(endpoint=ENDPOINT, min_support=MIN_SUPPORT)
    miner.preprocess(
        property_limit=100_000,
        max_triples=100_000,
        minimize_patterns=True,   # keep all patterns; we only need the flat list
    )

    pattern_counts   = miner.abstat.pattern_counts
    attribute_counts = miner.abstat.attribute_counts
    print(f"Object patterns: {len(pattern_counts)}, Attribute patterns: {len(attribute_counts)}")

    classes = build_domain_indexed(pattern_counts, attribute_counts)

    with open(OUT_FILE, "w") as f:
        yaml.dump({"classes": classes}, f, allow_unicode=True,
                  default_flow_style=False, sort_keys=False)

    total_props = sum(len(v) for v in classes.values())
    print(f"Written: {OUT_FILE}  ({len(classes)} domain classes, {total_props} property entries)")


if __name__ == "__main__":
    main()
