"""SPARQL query execution and result preview extraction for generated queries."""

from __future__ import annotations

from typing import Any, Dict, List
from querybloom.executor.sparql_executor import execute_sparql_query as execute


def execute_sparql_and_get_result(
    sparql_query: str,
    endpoint: str,
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Execute a SPARQL query and return structured execution results.

    Args:
        sparql_query: The SPARQL query to execute
        endpoint: SPARQL endpoint URL
        timeout: Query timeout in seconds

    Returns:
        Dict with success, count, error_message, and result_preview
    """
    res = execute(sparql_query, endpoint=endpoint, timeout=timeout)

    execution_result: Dict[str, Any] = {
        "success": res.get("success", False),
        "count": 0,
        "error_message": res.get("error", "") or "",
        "result_preview": None,
    }

    if res.get("success"):
        results = res.get("results", [])

        # Handle DataFrame results
        if hasattr(results, "to_dict") and callable(getattr(results, "to_dict")):
            records = results.to_dict("records")
            execution_result["count"] = len(records)
            if records:
                columns = list(records[0].keys())
                preview_rows = records[:5]
                execution_result["result_preview"] = {
                    "columns": columns,
                    "rows": preview_rows,
                }
        # Handle list of bindings
        elif isinstance(results, list):
            execution_result["count"] = len(results)
            if results:
                first = results[0]
                if isinstance(first, dict):
                    columns = list(first.keys())
                    preview_rows: List[Dict[str, Any]] = []
                    for row in results[:5]:
                        preview_row: Dict[str, Any] = {}
                        for k, v in row.items():
                            if isinstance(v, dict) and "value" in v:
                                preview_row[k] = v["value"]
                            else:
                                preview_row[k] = v
                        preview_rows.append(preview_row)
                    execution_result["result_preview"] = {
                        "columns": columns,
                        "rows": preview_rows,
                    }
        # Handle dict with nested results
        elif isinstance(results, dict) and "results" in results:
            bindings = results["results"].get("bindings", [])
            execution_result["count"] = len(bindings)
            if bindings:
                columns = list(bindings[0].keys())
                preview_rows = []
                for row in bindings[:5]:
                    preview_row = {k: v.get("value", "") for k, v in row.items()}
                    preview_rows.append(preview_row)
                execution_result["result_preview"] = {
                    "columns": columns,
                    "rows": preview_rows,
                }

    return execution_result
