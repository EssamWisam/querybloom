"""
SPARQL query execution utilities for the standalone ABSTAT package.

NOTE FOR DEVELOPERS:
This module is part of the standalone ABSTAT package and mirrors
`src/kg_voyager/executor/sparql_executor.py`. If modifying execution logic,
ensure changes remain in sync with kg_voyager.
"""

import json
import re
import requests
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from querybloom.executor.sparql_executor_utils import (
    SparqlExecutionResult,
    SparqlStatus,
    handle_http_response,
    should_retry_status,
    determine_optimal_format,
    make_request,
)

# Load endpoints catalog from local querybloom package
_endpoints_file = Path(__file__).resolve().parent / "endpoints.json"
if not _endpoints_file.is_file():
    raise FileNotFoundError(
        f"SPARQL endpoints catalog not found at '{_endpoints_file}'. "
        f"Please ensure querybloom/executor/endpoints.json is present."
    )
with open(_endpoints_file) as f:
    _data = json.load(f)
    # Support both "name": "url" and "name": {"url": "url", "description": "..."}
    ENDPOINTS: Dict[str, str] = {
        k: (v["url"] if isinstance(v, dict) else v)
        for k, v in _data.items()
        if k != "_metadata"  # Reserve for root-level metadata if used
    }
    # Keep raw data for cases that might want descriptions later
    RAW_ENDPOINTS: Dict[str, Any] = _data

# Federated endpoint URL for FRINK KGs
_federated_raw = _data.get("federated", "https://apps.okn.us/federation/sparql")
FEDERATED_URL: str = (
    _federated_raw.get("url", "https://apps.okn.us/federation/sparql")
    if isinstance(_federated_raw, dict)
    else _federated_raw
)


def _endpoint_is_frink(endpoint_name: str) -> bool:
    """Return True if the named endpoint uses FRINK federation (default True for apps.okn.us / frink.apps.renci.org)."""
    raw = RAW_ENDPOINTS.get(endpoint_name)
    if raw is None:
        return False
    return _raw_endpoint_is_frink(raw)


def _raw_endpoint_is_frink(raw: Any) -> bool:
    if isinstance(raw, str):
        return True  # plain-URL entries default to frink=True
    return raw.get("frink", True)  # dict entries default to True when key is absent


def _normalized_endpoint_url(endpoint_url: str) -> str:
    return str(endpoint_url).rstrip("/")


def _endpoint_url_is_frink(endpoint_url: str) -> bool:
    """Return True if a URL belongs to a FRINK KG that should use federation."""
    normalized_url = _normalized_endpoint_url(endpoint_url)
    if normalized_url == _normalized_endpoint_url(FEDERATED_URL):
        return False

    for key, raw in RAW_ENDPOINTS.items():
        if key in {"_metadata", "federated"}:
            continue
        raw_url = raw.get("url") if isinstance(raw, dict) else raw
        if raw_url and _normalized_endpoint_url(raw_url) == normalized_url:
            return _raw_endpoint_is_frink(raw)

    return bool(re.search(r"(?:frink\.apps\.renci\.org|apps\.okn\.us)/[^/]+/sparql/?$", endpoint_url))


def _endpoint_should_use_federation(
    endpoint_name: Optional[str], endpoint_url: str
) -> bool:
    return bool(endpoint_name and endpoint_name in RAW_ENDPOINTS and _endpoint_is_frink(endpoint_name))


def _endpoint_url_to_graph_uri(endpoint_url: str) -> str:
    """Convert a FRINK endpoint URL to its named graph URI.

    e.g. https://apps.okn.us/sockg/sparql
         -> https://purl.org/okn/frink/kg/sockg
    """
    match = re.search(r"(?:frink\.apps\.renci\.org|apps\.okn\.us)/([^/]+)/sparql", endpoint_url)
    if match:
        return f"https://purl.org/okn/frink/kg/{match.group(1)}"
    return endpoint_url  # fallback: use the URL itself as the graph name


_NOISE_RE = re.compile(r"""<[^>]*>|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'""")


def _insert_from_clause(query: str, graph_uri: str) -> str:
    """Inject a FROM <graph_uri> dataset clause into a SPARQL query.

    Works for all query forms (SELECT / ASK / CONSTRUCT / DESCRIBE) by
    inserting the clause immediately before the WHERE keyword.  When no
    WHERE keyword is present (e.g. bare ASK { } shorthand) the FROM is
    inserted before the opening '{' of the graph pattern instead.
    PREFIX declarations are preserved unchanged.

    URIs (<…>) and string literals ("…" / '…') are blanked out before
    searching so that keywords or braces embedded in them are ignored.
    """
    # Blank out IRIs and string literals (same length so positions stay valid)
    sanitized = _NOISE_RE.sub(lambda m: " " * len(m.group()), query)

    where_match = re.search(r"\bWHERE\b", sanitized, re.IGNORECASE)
    if where_match:
        pos = where_match.start()
        return query[:pos] + f"FROM <{graph_uri}>\n" + query[pos:]

    # Fallback: insert before the first '{' that starts the graph pattern
    brace_match = re.search(r"\{", sanitized)
    if brace_match:
        pos = brace_match.start()
        return query[:pos] + f"FROM <{graph_uri}>\n" + query[pos:]

    # Last resort: append (shouldn't happen for valid SPARQL)
    return query + f"\nFROM <{graph_uri}>"



def execute_single_sparql_request(
    query: str,
    timeout: int = 60,
    endpoint_url: str = "https://query.wikidata.org/sparql",
    format_type: str = "json",
) -> Tuple[SparqlExecutionResult, bool]:
    start_time = time.time()

    # Override format based on query type when necessary
    actual_format = determine_optimal_format(query, format_type)

    try:
        user_agent = "NL2SPARQL-Enhanced-Evaluator"

        # Make initial request with the determined format
        response = make_request(endpoint_url, query, actual_format, user_agent, timeout)
        execution_time = time.time() - start_time

        result = handle_http_response(response, execution_time, actual_format)

        should_retry = should_retry_status(response.status_code)

        return result, should_retry

    except requests.exceptions.Timeout:
        execution_time = time.time() - start_time
        result = SparqlExecutionResult(
            status=SparqlStatus.TIMEOUT,
            error_message=f"Request timed out after {timeout} seconds",
            execution_time=execution_time,
        )
        return result, True  # Timeout is retryable

    except requests.exceptions.ConnectionError as e:
        execution_time = time.time() - start_time
        result = SparqlExecutionResult(
            status=SparqlStatus.CONNECTION_ERROR,
            error_message=f"Connection error: {str(e)}",
            execution_time=execution_time,
        )
        return result, True  # Connection errors are retryable

    except Exception as e:
        execution_time = time.time() - start_time
        result = SparqlExecutionResult(
            status=SparqlStatus.OTHER_ERROR,
            error_message=f"Unexpected error: {str(e)}",
            execution_time=execution_time,
        )
        return result, False  # Unknown errors are not retryable


def execute_sparql_enhanced(
    query: str,
    timeout: int = 30,
    max_retries: int = 0,
    retry_delay: float = 1.0,
    endpoint_url: str = "https://query.wikidata.org/sparql",
    format_type: str = "json",
    endpoint_name: Optional[str] = None,
    federated: bool = False,
) -> SparqlExecutionResult:
    """Execute a SPARQL query with optional retry logic.

    FRINK-hosted KGs are automatically wrapped with the appropriate FROM clause
    and routed through the FRINK federation endpoint. This works for catalog
    aliases and for raw FRINK endpoint URLs.
    """
    # Apply FRINK federation wrapping when requested
    actual_query = query
    actual_url = endpoint_url
    should_federate = _endpoint_should_use_federation(endpoint_name, endpoint_url)
    if should_federate:
        graph_uri = _endpoint_url_to_graph_uri(endpoint_url)
        actual_query = _insert_from_clause(query, graph_uri)
        actual_url = FEDERATED_URL

    def _with_execution_metadata(result: SparqlExecutionResult) -> SparqlExecutionResult:
        result.executed_query = actual_query
        result.executed_endpoint_url = actual_url
        return result

    last_result = None

    for attempt in range(max_retries + 1):
        result, should_retry = execute_single_sparql_request(
            actual_query, timeout, actual_url, format_type
        )
        last_result = result

        # If successful or not retryable, return immediately
        if result.success or not should_retry:
            return _with_execution_metadata(result)

        # If this was our last attempt, don't sleep
        if attempt < max_retries:
            delay = retry_delay * (2**attempt)
            time.sleep(delay)

    # If we get here, all attempts failed
    # Update the error message to indicate max retries exceeded
    if last_result:
        last_result.error_message = f"Max retries ({max_retries}) exceeded. Last error: {last_result.error_message}"
        return _with_execution_metadata(last_result)

    return _with_execution_metadata(SparqlExecutionResult(
        status=SparqlStatus.OTHER_ERROR,
        error_message="Maximum retries exceeded with no response",
    ))


def execute_sparql_query(
    query: str,
    endpoint: str = "wikidata",
    timeout: int = 60,
    max_retries: int = 0,
    retry_delay: float = 1.0,
    format_type: str = "json",
    federated: bool = False,
) -> Dict[str, Any]:
    """Execute a SPARQL query against a named endpoint.

    Known FRINK endpoint aliases are automatically routed through the federation
    SPARQL service with an injected FROM dataset clause. Raw/custom endpoint URLs
    execute directly.
    """
    # If endpoint is a known shortname, use its URL; otherwise treat it as a custom URL
    endpoint_url = ENDPOINTS.get(endpoint, endpoint)

    return execute_sparql_enhanced(
        query=query,
        timeout=timeout,
        max_retries=max_retries,
        retry_delay=retry_delay,
        endpoint_url=endpoint_url,
        format_type=format_type,
        endpoint_name=endpoint,
        federated=federated,
    ).to_dict()
