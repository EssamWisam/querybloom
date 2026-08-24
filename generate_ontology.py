#!/usr/bin/env python3
"""
Script to extract common prefixes from sockg.pt triples and rewrite them
in a more readable format: ex:class --ex:prop--> ex:class
"""

import re
from collections import Counter
from urllib.parse import urlparse


def extract_namespace_and_local(uri):
    """
    Extract namespace and local name from a URI.
    Splits on # or the last / in the path.
    """
    if "#" in uri:
        namespace, local = uri.rsplit("#", 1)
        return namespace + "#", local
    else:
        # Split on the last /
        parts = uri.rsplit("/", 1)
        if len(parts) == 2:
            return parts[0] + "/", parts[1]
        else:
            return uri, ""


def get_common_prefix_name(namespace):
    """
    Generate a sensible prefix name from a namespace URI.
    """
    # Common mappings
    common_prefixes = {
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf",
        "http://www.w3.org/2000/01/rdf-schema#": "rdfs",
        "http://www.w3.org/2002/07/owl#": "owl",
        "http://www.w3.org/2001/XMLSchema#": "xsd",
        "http://www.w3.org/ns/sparql-service-description#": "sd",
        "https://idir.uta.edu/sockg-ontology#": "sockg",
        "http://www.openlinksw.com/schemas/virtrdf#": "virtrdf",
        "http://stko-kwg.geog.ucsb.edu/lod/ontology/": "kwg",
        "https://lod.nal.usda.gov/nalt/": "nalt",
        "http://purl.org/spatialai/spatial/spatial-full#": "spatial",
        "http://www.w3.org/2004/02/skos/core#": "skos",
        "http://www.w3.org/ns/prov#": "prov",
        "http://qudt.org/vocab/unit/": "unit",
        "http://qudt.org/2.1/vocab/unit/": "unit",
        "http://qudt.org/schema/qudt/": "qudt",
        "http://schema.org/": "schema",
        "https://schema.org/": "schema.org",
        "http://www.opengis.net/ont/geosparql#": "geo",
        "http://www.w3.org/2006/time#": "time",
        "http://purl.org/dc/terms/": "dcterms",
        "http://xmlns.com/foaf/0.1/": "foaf",
    }

    if namespace in common_prefixes:
        return common_prefixes[namespace]

    # Try to extract a meaningful name from the URI
    # Remove trailing # or /
    clean = namespace.rstrip("#/")

    # Get the last path component or domain
    if "/" in clean:
        parts = clean.split("/")
        # Look for ontology names, schema names, etc.
        for part in reversed(parts):
            if part and part not in ["lod", "ontology", "vocab", "schema", "schemas"]:
                # Convert to lowercase and remove hyphens
                return part.lower().replace("-", "").replace("_", "")[:10]

    # Fallback: use domain
    parsed = urlparse(namespace)
    domain_parts = parsed.netloc.split(".")
    if len(domain_parts) >= 2:
        return domain_parts[-2][:10]

    return "ns"


def load_triples(file_path):
    """
    Load triples from the .pt file.
    Returns tuple of (object_triples, attribute_triples) where attribute_triples is empty for .pt files.
    """
    with open(file_path, "r") as f:
        content = f.read()

    # Use eval to parse the Python list (safe here as we control the input)
    triples = eval(content)
    return triples, []


def load_from_miner(pattern_counts, attribute_counts):
    """
    Load triples from miner's pattern_counts and attribute_counts.

    Args:
        pattern_counts: Dict of {(s, p, o): count} for object properties
        attribute_counts: Dict of {(s, p, o): count} for datatype properties

    Returns:
        Tuple of (object_triples, attribute_triples)
    """
    object_triples = list(pattern_counts.keys())
    attribute_triples = list(attribute_counts.keys())
    return object_triples, attribute_triples


def extract_prefixes(object_triples, attribute_triples):
    """
    Extract all unique namespaces and create prefix mappings.
    """
    namespaces = set()

    # Process both object and attribute triples
    all_triples = list(object_triples) + list(attribute_triples)

    for s, p, o in all_triples:
        ns_s, _ = extract_namespace_and_local(s)
        ns_p, _ = extract_namespace_and_local(p)
        ns_o, _ = extract_namespace_and_local(o)

        namespaces.add(ns_s)
        namespaces.add(ns_p)
        namespaces.add(ns_o)

    # Create prefix mappings
    prefix_map = {}
    used_prefixes = set()

    for namespace in sorted(namespaces):
        prefix = get_common_prefix_name(namespace)

        # Ensure uniqueness
        original_prefix = prefix
        counter = 1
        while prefix in used_prefixes:
            prefix = f"{original_prefix}{counter}"
            counter += 1

        prefix_map[namespace] = prefix
        used_prefixes.add(prefix)

    return prefix_map


def format_uri(uri, prefix_map):
    """
    Format a URI using prefix notation.
    """
    namespace, local = extract_namespace_and_local(uri)

    if namespace in prefix_map:
        prefix = prefix_map[namespace]
        return f"{prefix}:{local}"
    else:
        return f"<{uri}>"


def rewrite_triples(object_triples, attribute_triples, prefix_map):
    """
    Rewrite triples in the format: ex:class --ex:prop--> ex:class
    Attributes appear at the end of each source class block.
    Filters out triples with virtrdf: and owl: prefixes.
    """
    # Prefixes to ignore
    ignore_prefixes = ["virtrdf:", "owl:"]

    # Format object triples
    formatted_objects = []
    for s, p, o in object_triples:
        s_formatted = format_uri(s, prefix_map)
        # Skip if subject has ignored prefix
        if any(s_formatted.startswith(prefix) for prefix in ignore_prefixes):
            continue
        p_formatted = format_uri(p, prefix_map)
        o_formatted = format_uri(o, prefix_map)
        formatted_objects.append((s_formatted, p_formatted, o_formatted, False))

    # Format attribute triples
    formatted_attrs = []
    for s, p, o in attribute_triples:
        s_formatted = format_uri(s, prefix_map)
        # Skip if subject has ignored prefix
        if any(s_formatted.startswith(prefix) for prefix in ignore_prefixes):
            continue
        p_formatted = format_uri(p, prefix_map)
        o_formatted = format_uri(o, prefix_map)
        formatted_attrs.append((s_formatted, p_formatted, o_formatted, True))

    # Combine and sort: by subject, then by is_attribute (False first), then by predicate, then by object
    all_formatted = formatted_objects + formatted_attrs
    all_formatted.sort(key=lambda x: (x[0], x[3], x[1], x[2]))

    # Convert to string format with blank lines between different source classes
    result = []
    prev_subject = None
    for s, p, o, is_attr in all_formatted:
        # Add blank line when source class changes
        if prev_subject is not None and s != prev_subject:
            result.append("")

        # Format object: wrap in parentheses for datatypes, as-is for object properties
        o_display = f"({o})" if is_attr else o
        result.append(f"{s} --{p}--> {o_display}")
        prev_subject = s

    return result


def main():
    import sys
    import os

    # Ensure we can import from parent directory
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from querybloom.subgraph_miner import SubgraphMiner

    # Configuration
    endpoint = "sockg-local"
    min_support = 5
    output_file = "ontology.txt"

    # Allow custom endpoint and min_support from command line
    if len(sys.argv) > 1:
        endpoint = sys.argv[1]
    if len(sys.argv) > 2:
        min_support = int(sys.argv[2])

    print(
        f"Initializing SubgraphMiner with endpoint: {endpoint}, min_support: {min_support}"
    )
    miner = SubgraphMiner(endpoint=endpoint, min_support=min_support)

    print("Running ABSTAT preprocessing to extract patterns...")
    miner.preprocess(property_limit=100000, max_triples=300000)

    print(f"\nExtracting patterns from miner...")
    object_triples, attribute_triples = load_from_miner(
        miner.abstat.pattern_counts, miner.abstat.attribute_counts
    )
    print(f"Loaded {len(object_triples)} object property patterns")
    print(f"Loaded {len(attribute_triples)} attribute property patterns")

    print("Extracting common prefixes...")
    prefix_map = extract_prefixes(object_triples, attribute_triples)
    print(f"Found {len(prefix_map)} unique namespaces")

    # Rewrite triples
    print(f"Rewriting triples...")
    formatted_triples = rewrite_triples(object_triples, attribute_triples, prefix_map)

    # Write formatted triples with prefixes at the top
    print(f"Writing formatted triples to {output_file}...")
    with open(output_file, "w") as f:
        # Write header
        f.write("# Ontology Schema in Compact Format\n")
        f.write("# Format: subject --predicate--> object\n")
        f.write(
            "# Datatypes are shown in parentheses: class --property--> (datatype)\n\n"
        )

        # Write prefix mappings
        f.write("# Prefix Mappings:\n")
        for namespace, prefix in sorted(prefix_map.items(), key=lambda x: x[1]):
            f.write(f"# @prefix {prefix}: <{namespace}>\n")
        f.write("\n")

        # Write triples
        for line in formatted_triples:
            f.write(line + "\n")

    print(f"\n✓ Done!")
    print(f"  - Output file: {output_file}")
    print(
        f"  - Total: {len(object_triples)} object + {len(attribute_triples)} attribute triples"
    )
    print(f"\nSample output:")
    for i, line in enumerate(formatted_triples[:5]):
        print(f"  {line}")


if __name__ == "__main__":
    main()
