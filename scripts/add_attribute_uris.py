#!/usr/bin/env python3
"""
Usage: python add_attribute_uris.py <kg_endpoint_name> <path_to_yaml>
Example: python add_attribute_uris.py climatemodelskg subgraphs_output/04-14-21-climatemodelskg.yaml
"""

import sys
import os
import yaml
import re
from tqdm import tqdm

from querybloom.executor.sparql_executor import execute_sparql_query as execute


def uri_local_name(uri):
    """Return URI local name (after last '/' or '#')."""
    return uri.split("/")[-1].split("#")[-1]


def normalize_name(name):
    """Normalize names for robust matching across formatting differences."""
    if name is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())

def get_literal_properties(endpoint, entity_uri):
    """Fetch all property URIs for an entity that point to a literal (attribute)."""
    query = f"""
    SELECT DISTINCT ?p WHERE {{
        <{entity_uri}> ?p ?o .
        FILTER(isLiteral(?o))
    }}
    """
    res = execute(query, endpoint=endpoint, timeout=15)
    props = []
    if res.get("success"):
        bindings = res.get("results", [])
        if hasattr(bindings, "to_dict") and callable(getattr(bindings, "to_dict")):
            records = bindings.to_dict("records")
            props = [r.get("p") for r in records if r.get("p")]
        elif isinstance(bindings, list):
            props = [b.get("p", {}).get("value") for b in bindings if "p" in b]
        elif isinstance(bindings, dict) and "results" in bindings:
            props = [b.get("p", {}).get("value") for b in bindings["results"].get("bindings", [])]
    return props

def main():
    if len(sys.argv) != 3:
        print("Usage: python add_attribute_uris.py <endpoint> <path_to_yaml>")
        sys.exit(1)

    endpoint = sys.argv[1]
    yaml_path = sys.argv[2]
    
    if not os.path.exists(yaml_path):
        print(f"File not found: {yaml_path}")
        sys.exit(1)

    print(f"Loading {yaml_path}...")
    with open(yaml_path, 'r') as f:
        subgraphs = yaml.safe_load(f)
        
    print(f"Processing {len(subgraphs)} subgraphs...")
    for sg in tqdm(subgraphs, desc="Appending Attribute URIs"):
        if "attribute_uris" in sg:
            continue # already has it
            
        found_attr_uris = set()
        
        for type_name, type_info in sg.get("types", {}).items():
            sample_entities = type_info.get("sample_entities", [])
            for entity in sample_entities:
                attrs_str = entity.get("attributes", "")
                if not attrs_str or attrs_str == "()":
                    continue
                
                # Extract the attribute labels from the string "(Label*:type='val', Label2:type=val...)"
                # We can grab everything before the colon
                attr_labels = re.findall(r"([^:,()]+)\*?:", attrs_str)
                attr_labels_norm = {normalize_name(x.strip()) for x in attr_labels}
                
                if attr_labels_norm:
                    entity_uri = entity.get("uri")
                    # Query actual literal properties for this entity
                    actual_props = get_literal_properties(endpoint, entity_uri)
                    
                    # Match by URI local name only (no label lookup needed).
                    for prop_uri in actual_props:
                        p_local = uri_local_name(prop_uri)
                        if normalize_name(p_local) in attr_labels_norm:
                            found_attr_uris.add(prop_uri)

        sg["attribute_uris"] = sorted(list(found_attr_uris))
        
    out_path = yaml_path.replace(".yaml", "_with_attrs.yaml")
    print(f"Saving to {out_path}...")
    with open(out_path, 'w') as f:
        yaml.dump(subgraphs, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    print("Done!")

if __name__ == "__main__":
    main()
