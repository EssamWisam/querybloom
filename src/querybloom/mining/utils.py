"""Utilities for SPARQL result binding parsing and normalization."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def binding_value(binding: Any, variable: str) -> Optional[str]:
    """Extract a scalar or URI string value from a SPARQL binding object."""
    value = binding.get(variable) if isinstance(binding, dict) else None
    if isinstance(value, dict):
        return value.get("value")
    if value is not None:
        return str(value)
    return None


def extract_binding_rows(result: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extract a normalized list of variable-to-value dictionaries from SPARQL query execution results.
    Handles pandas DataFrames, raw list bindings, and JSON SPARQL result envelopes.
    """
    bindings = result.get("results", [])
    if hasattr(bindings, "to_dict") and callable(getattr(bindings, "to_dict")):
        records = bindings.to_dict("records")
        return [
            {key: str(value) for key, value in record.items() if value is not None}
            for record in records
        ]

    if isinstance(bindings, list):
        rows: List[Dict[str, str]] = []
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            row: Dict[str, str] = {}
            for variable, value in binding.items():
                if isinstance(value, dict) and value.get("value") is not None:
                    row[variable] = str(value["value"])
                elif value is not None:
                    row[variable] = str(value)
            if row:
                rows.append(row)
        return rows

    if isinstance(bindings, dict) and "bindings" in bindings:
        rows = []
        for binding in bindings["bindings"]:
            row = {}
            for variable, value in binding.items():
                if isinstance(value, dict) and value.get("value") is not None:
                    row[variable] = str(value["value"])
                elif value is not None:
                    row[variable] = str(value)
            if row:
                rows.append(row)
        return rows

    return []
