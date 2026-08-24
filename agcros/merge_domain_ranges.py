"""
Merge sockg_property_domain_ranges.yaml (ontological, source of truth)
with   sockg_empirical_domain_ranges.yaml (ABSTAT-derived).

Annotation rules per (class, property, object) triple:
  - both          →  prop: obj        (plain)
  - empirical only→  prop: obj*
  - ontology only →  prop: obj&

Output: ABSTAT/agcros/sockg_merged_domain_ranges.yaml
"""

from pathlib import Path
from collections import defaultdict
import yaml

_HERE    = Path(__file__).resolve().parent
ONT_FILE = _HERE / "sockg_property_domain_ranges.yaml"
EMP_FILE = _HERE / "sockg_empirical_domain_ranges.yaml"
OUT_FILE = _HERE / "sockg_merged_domain_ranges.yaml"


# ── load ──────────────────────────────────────────────────────────────────────

def load_ont(path: Path) -> dict[str, dict[str, set[str]]]:
    """Load ontological file  →  {class: {prop: {obj, ...}}}"""
    with open(path) as f:
        raw = yaml.safe_load(f)
    classes_raw = raw.get("classes", raw)   # tolerate missing wrapper
    out: dict[str, dict[str, set[str]]] = {}
    for cls, props in classes_raw.items():
        if not isinstance(props, dict):
            continue
        out[str(cls)] = {}
        for prop, val in props.items():
            if val is None:
                objects = set()
            elif isinstance(val, list):
                objects = {str(v) for v in val}
            else:
                objects = {str(val)}
            out[str(cls)][str(prop)] = objects
    return out


def load_emp(path: Path) -> dict[str, dict[str, set[str]]]:
    """Load empirical file  →  same shape (unwraps 'classes:' if present)."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    classes_raw = raw.get("classes", raw)
    out: dict[str, dict[str, set[str]]] = {}
    for cls, props in classes_raw.items():
        if not isinstance(props, dict):
            continue
        out[str(cls)] = {}
        for prop, val in props.items():
            if val is None:
                objects = set()
            elif isinstance(val, list):
                objects = {str(v) for v in val}
            else:
                objects = {str(val)}
            out[str(cls)][str(prop)] = objects
    return out


# ── merge ─────────────────────────────────────────────────────────────────────

def annotate(value: str, suffix: str) -> str:
    return f"{value}{suffix}"


def merge(ont: dict, emp: dict) -> dict:
    """
    Produce merged structure:
      {class: {prop: single_annotated_str | [annotated_str, ...]}}
    """
    all_classes = sorted(set(ont) | set(emp))
    result: dict = {}

    for cls in all_classes:
        ont_props = ont.get(cls, {})
        emp_props = emp.get(cls, {})

        all_prop_set = set(ont_props) | set(emp_props)
        # bucket: 0 = ontology only, 1 = empirical only, 2 = both
        def _bucket(p):
            in_ont = p in ont_props
            in_emp = p in emp_props
            if in_ont and not in_emp: return 0
            if in_emp and not in_ont: return 1
            return 2
        all_props = sorted(all_prop_set, key=lambda p: (_bucket(p), p))

        props_out: dict = {}
        for prop in all_props:
            ont_objs = ont_props.get(prop, set())
            emp_objs = emp_props.get(prop, set())

            annotated: list[str] = []

            # objects in both
            for obj in sorted(ont_objs & emp_objs):
                annotated.append(obj)
            # ontology only
            for obj in sorted(ont_objs - emp_objs):
                annotated.append(annotate(obj, "&"))
            # empirical only
            for obj in sorted(emp_objs - ont_objs):
                annotated.append(annotate(obj, "*"))

            # prop with no objects at all
            if not annotated:
                # mark with source
                if prop in ont_props and prop not in emp_props:
                    props_out[prop] = "&"
                elif prop in emp_props and prop not in ont_props:
                    props_out[prop] = "*"
                else:
                    props_out[prop] = None
            elif len(annotated) == 1:
                props_out[prop] = annotated[0]
            else:
                props_out[prop] = annotated

        result[cls] = props_out

    return result


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ont = load_ont(ONT_FILE)
    emp = load_emp(EMP_FILE)

    print(f"Ontological classes : {len(ont)}")
    print(f"Empirical classes   : {len(emp)}")

    merged = merge(ont, emp)
    print(f"Merged classes      : {len(merged)}")

    with open(OUT_FILE, "w") as f:
        yaml.dump(merged, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"Written: {OUT_FILE}")


if __name__ == "__main__":
    main()
