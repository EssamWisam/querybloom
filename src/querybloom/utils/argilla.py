import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SUPPORTED_ENDPOINT_KEYS = ["sockg", "dbpedia", "dblp", "uniprot"]


def resolve_existing_path(path_str: str) -> Path:
    """Resolve a path from cwd or any parent directory."""
    expanded = os.path.expanduser(path_str.strip())
    p = Path(expanded)

    if p.is_absolute() and p.exists():
        return p.resolve()

    candidates = [Path.cwd() / p]
    candidates.extend(parent / p for parent in Path.cwd().parents)
    candidates.append(p)

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    return p


def resolve_add_results_script(file_path: str) -> Path:
    """Locate ABSTAT/add_sparql_results.py from cwd or input-file ancestry."""
    fp = Path(file_path).resolve()
    candidates: list[Path] = []

    for base in [Path.cwd(), *Path.cwd().parents]:
        candidates.append(base / "querybloom" / "add_sparql_results.py")
        candidates.append(base / "add_sparql_results.py")

    for base in [fp.parent, *fp.parents]:
        candidates.append(base / "querybloom" / "add_sparql_results.py")
        candidates.append(base / "add_sparql_results.py")

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    raise FileNotFoundError("Could not locate ABSTAT/add_sparql_results.py")


def infer_endpoint_from_file_path(file_path: str) -> str:
    """Infer endpoint from file name, with optional SPARQL_ENDPOINT override."""
    env_endpoint = os.getenv("SPARQL_ENDPOINT")
    if env_endpoint:
        return env_endpoint

    name = Path(file_path).name.lower()
    for key in SUPPORTED_ENDPOINT_KEYS:
        if key in name:
            return "sockg-local" if key == "sockg" else key

    return "sockg-local"


def load_jsonl_entries(jsonl_path: str) -> list[dict[str, Any]]:
    """Load all valid JSONL rows from a file path."""
    entries: list[dict[str, Any]] = []
    with open(jsonl_path, "r") as f:
        for line in f:
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Skipping invalid JSON line: {e}")
    return entries


def should_add_execution_results(entries: list[dict[str, Any]]) -> bool:
    """Return True if any query-carrying row has no execution_results object."""
    entries_with_query = [
        e for e in entries if e.get("sparql") or e.get("sparql_query")
    ]
    if not entries_with_query:
        return False

    return any(
        not isinstance(e.get("execution_results"), dict)
        for e in entries_with_query
    )


def ensure_execution_results_inplace(jsonl_path: str) -> list[dict[str, Any]]:
    """Populate execution_results in-place by running add_sparql_results.py when needed."""
    entries = load_jsonl_entries(jsonl_path)
    if not should_add_execution_results(entries):
        return entries

    endpoint = infer_endpoint_from_file_path(jsonl_path)
    script_path = resolve_add_results_script(jsonl_path)

    print("execution_results missing in JSONL; running add_sparql_results.py in place...")
    print(f"Script: {script_path}")
    print(f"Endpoint: {endpoint}")

    cmd = [
        sys.executable,
        str(script_path),
        jsonl_path,
        "--output_file",
        jsonl_path,
        "--endpoint",
        endpoint,
    ]
    env = os.environ.copy()
    project_root = str(Path(script_path).parent.parent)
    src_path = os.path.join(project_root, "src")
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{src_path}:{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = src_path
        
    subprocess.run(cmd, check=True, env=env)

    print("Finished enriching JSONL with execution_results.")
    return load_jsonl_entries(jsonl_path)


def results_to_markdown(results: list[dict[str, Any]], max_rows: int = 50) -> str:
    """Format SPARQL JSON bindings into a markdown table."""
    if not results:
        return "*No output available*"

    simplified_data: list[dict[str, str]] = []
    for row in results:
        new_row: dict[str, str] = {}
        for k, v in row.items():
            if isinstance(v, dict) and "value" in v:
                new_row[k] = str(v["value"])
            else:
                new_row[k] = str(v)
        simplified_data.append(new_row)

    if not simplified_data:
        return "*No output available*"

    try:
        import pandas as pd

        df = pd.DataFrame(simplified_data)
        total_rows = len(df)
        if total_rows > max_rows:
            table_md = df.head(max_rows).to_markdown(index=False)
            table_md += (
                f"\n\n*... truncated ({total_rows - max_rows} more rows not shown, {total_rows} total)*"
            )
            return table_md
        return df.to_markdown(index=False)
    except Exception as e:
        return f"Error formatting table: {str(e)}"
