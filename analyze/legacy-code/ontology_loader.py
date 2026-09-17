"""Ontology loader: read class/property sets from per-KG YAML files."""

import os
import warnings
import yaml


# Well-known meta namespaces that should never be treated as domain-specific
# classes or properties of a KG.  URIs starting with any of these prefixes
# are filtered out by the loaders below.
_META_PREFIXES = (
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2001/XMLSchema#",
)


def _filter_meta(uris):
    """Remove URIs that belong to well-known RDF/RDFS/OWL/XSD namespaces."""
    return {u for u in uris if not any(u.startswith(p) for p in _META_PREFIXES)}


# Primary path: kg-index/ beside this file
_DEFAULT_KG_INDEX = os.path.join(os.path.dirname(__file__), "kg-index")

# Legacy fallback: nl2sparql/kgs_data/
_LEGACY_KGS_DATA = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "..", "nl2sparql", "kgs_data"
)


def _find_file(kg_name, filename, legacy_filename, kgs_data_dir=None):
    """Resolve a YAML file, trying kg-index first, then legacy kgs_data."""
    if kgs_data_dir:
        # Explicit override: try new name, then legacy name
        for name in (filename, legacy_filename):
            path = os.path.join(kgs_data_dir, kg_name, name)
            if os.path.isfile(path):
                return path
        return None

    # Try primary kg-index location (classes.yaml / properties.yaml)
    path = os.path.join(_DEFAULT_KG_INDEX, kg_name, filename)
    if os.path.isfile(path):
        return path

    # Try legacy kgs_data location ({kg_name}_classes.yaml / {kg_name}_props.yaml)
    path = os.path.join(_LEGACY_KGS_DATA, kg_name, legacy_filename)
    if os.path.isfile(path):
        return path

    return None


def load_ontology_classes(kg_name, kgs_data_dir=None):
    """Return the set of all class URIs for a KG.

    Args:
        kg_name: directory name under kg-index/ (e.g. 'dbpedia', 'sockg').
        kgs_data_dir: override path to kgs_data/ if needed.

    Returns:
        set[str] of class URIs (empty set if the file is missing).
    """
    path = _find_file(kg_name, "classes.yaml", f"{kg_name}_classes.yaml", kgs_data_dir)
    if path is None:
        warnings.warn(f"Classes file not found for KG '{kg_name}'")
        return set()
    with open(path) as f:
        items = yaml.safe_load(f)
    return _filter_meta({item["class"] for item in items if "class" in item})


def load_ontology_properties(kg_name, kgs_data_dir=None):
    """Return the set of all property URIs for a KG (deduplicated across domain-range pairs).

    Args:
        kg_name: directory name under kg-index/ (e.g. 'dbpedia', 'sockg').
        kgs_data_dir: override path to kgs_data/ if needed.

    Returns:
        set[str] of property URIs (empty set if the file is missing).
    """
    path = _find_file(kg_name, "properties.yaml", f"{kg_name}_props.yaml", kgs_data_dir)
    if path is None:
        warnings.warn(f"Properties file not found for KG '{kg_name}'")
        return set()
    with open(path) as f:
        items = yaml.safe_load(f)
    return _filter_meta({item["property"] for item in items if "property" in item})
