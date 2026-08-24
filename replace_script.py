import sys

filename = (
    "/Users/essamwisam/Desktop/UTA/Projects/NL2SparQL/misc/grasp/querybloom/abstat_2.py"
)
with open(filename, "r") as f:
    lines = f.readlines()

start_idx = -1
end_idx = -1
for i, line in enumerate(lines):
    if line.strip().startswith('df_triples = res_triples.get("results")'):
        start_idx = i
    if (
        start_idx != -1
        and line.strip().startswith("if pbar:")
        and "Property {display_name}: {len(subject_types)} typed subjects"
        in "".join(lines[i : i + 4])
    ):
        end_idx = i
        break

if start_idx == -1 or end_idx == -1:
    print(f"Could not find indices! start_idx={start_idx}, end_idx={end_idx}")
    sys.exit(1)

print(f"Indices: {start_idx} to {end_idx}")
print("Removing:", lines[start_idx:end_idx][:3])

new_code = """        df_triples = res_triples.get("results")
        if not isinstance(df_triples, pd.DataFrame) or df_triples.empty:
            if pbar:
                pbar.write(f"Property {display_name}: No triples returned.")
            return set()

        # Collect unique (s, o) pairs and literal datatypes
        triples = set()          # unique (s, o) pairs
        object_dtypes = {}       # o -> dType  (literal objects)

        unique_subjects = set()
        unique_iri_objects = set()

        for row in df_triples.itertuples(index=False):
            s = str(row.s) if pd.notna(getattr(row, 's', None)) else None
            o = str(row.o) if pd.notna(getattr(row, 'o', None)) else None
            if not s or not o:
                continue
            triples.add((s, o))
            if s.startswith('http'):
                unique_subjects.add(s)
            
            dType = str(row.dType) if pd.notna(getattr(row, 'dType', None)) else None
            if dType:
                object_dtypes[o] = dType
            else:
                if o.startswith('http'):
                    unique_iri_objects.add(o)

        if pbar:
            pbar.write(
                f"Property {display_name}: {len(triples)} triples, "
                f"~{len(unique_iri_objects)} IRI objects, "
                f"{len(object_dtypes)} literal objects"
            )

        # --- Query 2 & 3: Types via VALUES chunking ---
        # Chunking helper to avoid header too large errors or query limits
        def fetch_types(uris, is_subject=True):
            type_map = defaultdict(set)
            uris_list = list(uris)
            chunk_size = 500  # Conservative chunk size for public endpoints
            
            type_pred = "wdt:P31" if self.is_wikidata else "a"
            prefixes = "PREFIX wdt: <http://www.wikidata.org/prop/direct/>\\n" if self.is_wikidata else ""
            var_name = "?s" if is_subject else "?o"
            filter_str = s_filter if is_subject else o_filter
            t_var = "?sType" if is_subject else "?oType"
            
            for i in range(0, len(uris_list), chunk_size):
                chunk = uris_list[i:i + chunk_size]
                # Format IRIs
                values_block = " ".join([f"<{uri}>" for uri in chunk])
                
                query = f\"\"\"
                {prefixes}
                SELECT {var_name} {t_var} WHERE {{
                    VALUES {var_name} {{ {values_block} }}
                    {var_name} {type_pred} {t_var} .
                    {filter_str}
                }}
                \"\"\"
                
                res = execute_sparql_query(query, endpoint=self.endpoint, format_type="csv")
                if res.get("success"):
                    df = res.get("results")
                    if isinstance(df, pd.DataFrame) and not df.empty:
                        for row in df.itertuples(index=False):
                            ent = str(getattr(row, var_name.strip('?'))) if pd.notna(getattr(row, var_name.strip('?'), None)) else None
                            t = str(getattr(row, t_var.strip('?'))) if pd.notna(getattr(row, t_var.strip('?'), None)) else None
                            if ent and t:
                                type_map[ent].add(t)
            return type_map

        subject_types = fetch_types(unique_subjects, is_subject=True)
        object_types = fetch_types(unique_iri_objects, is_subject=False)

"""

lines[start_idx:end_idx] = [new_code]

with open(filename, "w") as f:
    f.writelines(lines)
print("Replaced lines successfully")
