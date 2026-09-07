from typing import Optional, Dict, Any
import logging
import requests
import json
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from enum import Enum
import pandas as pd
from io import StringIO

from rdflib.plugins.sparql import parser
from rdflib.plugins.sparql.parser import parseQuery

_logger = logging.getLogger(__name__)

# Bound the number of concurrently abandoned (wall-clock-timed-out) requests so
# stuck HTTP calls cannot exhaust threads or sockets during a long mining run.
_DEADLINE_POOL = ThreadPoolExecutor(
    max_workers=16, thread_name_prefix="sparql-deadline"
)


def check_sparql_syntax(query):
    try:
        # Attempt to parse the SPARQL query
        parse_result = parseQuery(query)
        # If parsing succeeds, the query is syntactically correct
        return True
    except Exception as e:
        # If parsing fails, the query is syntactically incorrect
        return False


class SparqlStatus(str, Enum):
    """Enumeration of possible SPARQL execution statuses"""

    SUCCESS = "success"
    SYNTAX_ERROR = "syntax_error"
    TIMEOUT = "timeout"
    TOO_LARGE = "too_large"
    CONNECTION_ERROR = "connection_error"
    SERVER_ERROR = "server_error"
    OTHER_ERROR = "other_error"


class SparqlExecutionResult:
    """Container for SPARQL execution results with rich status information"""

    def __init__(
        self,
        results: list = None,
        status: SparqlStatus = SparqlStatus.SUCCESS,
        error_message: str = None,
        count: int = 0,
        execution_time: float = None,
        full_response: str = None,
        executed_query: str = None,
        executed_endpoint_url: str = None,
    ):
        # Append full response to error message if there's an error and a response
        if status != SparqlStatus.SUCCESS and error_message and full_response:
            error_message = f"{error_message}\nGot response: {full_response}"

        self.results = (
            results if (status == SparqlStatus.SUCCESS) else error_message
        )  # because we may return it only sometimes
        self.status = status
        self.error_message = error_message
        self.count = count
        self.execution_time = execution_time
        self.success = status == SparqlStatus.SUCCESS
        self.full_response = full_response
        self.executed_query = executed_query
        self.executed_endpoint_url = executed_endpoint_url

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for backward compatibility"""
        return {
            "success": self.success,
            "results": self.results,
            "count": self.count,
            "status": self.status.value,
            "error": self.error_message,
            "execution_time": self.execution_time,
            "full_response": self.full_response,
            "executed_query": self.executed_query,
            "executed_endpoint_url": self.executed_endpoint_url,
        }


def handle_http_response(
    response: requests.Response,
    execution_time: float,
    format_type: str = "json",
) -> SparqlExecutionResult:
    status_code = response.status_code

    if status_code == 200:
        if format_type.lower() == "json":
            try:
                data = response.json()

                # Handle ASK queries (return boolean directly)
                if "boolean" in data:
                    results = data["boolean"]
                    return SparqlExecutionResult(
                        results=results,
                        status=SparqlStatus.SUCCESS,
                        count=count_results(results, format_type),
                        execution_time=execution_time,
                        full_response=response.text,
                    )

                # Handle SELECT/CONSTRUCT queries (return bindings)
                elif "results" in data and "bindings" in data["results"]:
                    results = data["results"]["bindings"]

                    # Check for empty results
                    if results == [] or (len(results) == 1 and results[0] == {}):
                        results = []

                    return SparqlExecutionResult(
                        results=results,
                        status=SparqlStatus.SUCCESS,
                        count=count_results(results, format_type),
                        execution_time=execution_time,
                        full_response=response.text,
                    )

                # Fallback for unexpected JSON structure
                else:
                    return SparqlExecutionResult(
                        results=data,  # Return raw data
                        status=SparqlStatus.SUCCESS,
                        count=1,
                        execution_time=execution_time,
                        full_response=response.text,
                    )

            except json.JSONDecodeError:
                return SparqlExecutionResult(
                    status=SparqlStatus.OTHER_ERROR,
                    error_message="Invalid JSON response from server",
                    execution_time=execution_time,
                    full_response=response.text,
                )

        elif format_type.lower() == "csv":
            # Convert CSV response to DataFrame
            try:
                df = pd.read_csv(StringIO(response.text))
                return SparqlExecutionResult(
                    results=df,
                    status=SparqlStatus.SUCCESS,
                    count=count_results(response.text, format_type),
                    execution_time=execution_time,
                    full_response=response.text,
                )
            except Exception as e:
                return SparqlExecutionResult(
                    status=SparqlStatus.OTHER_ERROR,
                    error_message=f"Error parsing CSV response: {str(e)}",
                    execution_time=execution_time,
                    full_response=response.text,
                )
        else:
            return SparqlExecutionResult(
                results=response.text,  # Raw XML
                status=SparqlStatus.SUCCESS,
                count=count_results(response.text, format_type),
                execution_time=execution_time,
                full_response=response.text,
            )

    elif status_code == 400:
        # Bad request - usually syntax error
        syntax_error = extract_wikidata_syntax_error(response.text)
        error_msg = syntax_error or f"Bad Request: {response.text[:200]}..."

        return SparqlExecutionResult(
            status=SparqlStatus.SYNTAX_ERROR,
            error_message=error_msg,
            execution_time=execution_time,
            full_response=response.text,
        )

    elif status_code == 413:
        return SparqlExecutionResult(
            status=SparqlStatus.TOO_LARGE,
            error_message="Query result too large",
            execution_time=execution_time,
            full_response=response.text,
        )

    elif status_code == 414:
        return SparqlExecutionResult(
            status=SparqlStatus.TOO_LARGE,
            error_message="Query URL too long",
            execution_time=execution_time,
            full_response=response.text,
        )

    elif status_code == 429:
        # Rate limited - caller should retry
        return SparqlExecutionResult(
            status=SparqlStatus.OTHER_ERROR,
            error_message="Rate limited - too many requests",
            execution_time=execution_time,
            full_response=response.text,
        )

    elif status_code >= 500:
        # Server error - caller might retry
        return SparqlExecutionResult(
            status=SparqlStatus.SERVER_ERROR,
            error_message=f"Server Error {status_code}: {response.reason}",
            execution_time=execution_time,
            full_response=response.text,
        )

    else:
        return SparqlExecutionResult(
            status=SparqlStatus.OTHER_ERROR,
            error_message=f"HTTP {status_code}: {response.reason}",
            execution_time=execution_time,
            full_response=response.text,
        )


def extract_wikidata_syntax_error(error_text: str) -> Optional[str]:

    # Look for Java ExecutionException (syntax errors)
    if "java.util.concurrent.ExecutionException" in error_text:
        index = error_text.find("java.util.concurrent.ExecutionException")
        index_end = error_text.find("at java.util.concurrent", index)
        if index_end > index:
            error_detail = error_text[index:index_end].strip()
            return f"SPARQL Syntax Error: {error_detail}"

    # Look for TimeoutException
    elif "java.util.concurrent.TimeoutException" in error_text:
        return "Query execution timeout"

    # return full error text if no specific pattern matched
    return error_text


def should_retry_status(status_code: int) -> bool:
    # 429 Rate limiting - server is temporarily unavailable due to too many requests
    # Server errors (5xx) - internal server errors, bad gateway, service unavailable, etc.
    return status_code == 429 or status_code >= 500


def detect_query_type_with_rdflib(query: str) -> str:
    """
    Detect SPARQL query type using RDFLib parser.
    Returns 'SelectQuery', 'AskQuery', 'ConstructQuery', 'DescribeQuery', or 'UNKNOWN'
    """
    try:
        parsed = parser.parseQuery(query)  # raises if invalid
        kind = (
            parsed[1].name if len(parsed) > 1 and hasattr(parsed[1], "name") else None
        )
        if kind:
            return kind
        else:
            print(
                f"Warning: Could not determine query type for query starting with: {query[:50]}..."
            )
            return "UNKNOWN"
    except Exception as e:
        # RDFLib 6.0+ sometimes has issues with certain query structures or threading
        # resulting in lambda errors. We catch this and return UNKNOWN.
        # print(f"Error parsing query with RDFLib: {str(e)} for query: {query[:50]}...")
        return "UNKNOWN"


def determine_optimal_format(query: str, requested_format: str) -> str:
    query_type = detect_query_type_with_rdflib(query)

    if query_type == "AskQuery":
        if requested_format != "json":
            print(f"Forcing format to JSON for ASK query (was {requested_format})")
        return "json"
    elif query_type in ["ConstructQuery", "DescribeQuery"]:
        if requested_format != "xml":
            print(f"Forcing format to XML for {query_type} (was {requested_format})")
        return "xml"
    else:  # SelectQuery or UNKNOWN - use requested format
        return requested_format


def count_results(results, format_type: str) -> int:
    """Count the number of results based on the format type"""
    if format_type.lower() == "json":
        if isinstance(results, list):
            return len(results)
        elif isinstance(results, bool):
            return 1  # ASK query returns a single boolean
        else:
            return 0
    elif format_type.lower() == "xml":
        return results.count("</") if results else 0
    elif format_type.lower() == "csv":
        if results.strip():
            return len(results.strip().split("\n")) - 1
        return 0
    return 0


def make_request(
    endpoint_url: str, query: str, fmt: str, user_agent: str, timeout: int = 30
):
    """Helper function to make HTTP request with given format"""
    if fmt.lower() == "csv":
        if "wikidata" in endpoint_url.lower():
            params = {"query": query}  # No format parameter for Wikidata CSV
        else:
            params = {"query": query, "format": "csv"}
        headers = {"User-Agent": user_agent, "Accept": "text/csv"}
    elif fmt.lower() == "xml":
        params = {"query": query, "format": "xml"}
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/sparql-results+xml,application/rdf+xml",
        }
    else:  # JSON
        params = {"query": query, "format": "json"}
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/sparql-results+json",
        }

    return requests.get(endpoint_url, params=params, headers=headers, timeout=timeout)


def execute_with_deadline(
    endpoint_url: str,
    query: str,
    fmt: str,
    user_agent: str,
    timeout: int,
) -> requests.Response:
    """Run an HTTP SPARQL request with a hard wall-clock deadline.

    The scalar ``timeout`` passed to ``requests.get`` only bounds the time
    between received bytes, so a server that keeps the connection alive (e.g.
    Virtuoso streaming a slow result) can hold a call open indefinitely. This
    wrapper runs the request in a worker thread and abandons it once the
    wall-clock deadline passes, closing the response to release the socket.

    Raises ``FuturesTimeoutError`` when the deadline is exceeded.
    """
    future = _DEADLINE_POOL.submit(
        make_request, endpoint_url, query, fmt, user_agent, timeout
    )
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        future.cancel()  # best effort: only stops the task if it hasn't started
        _logger.warning(
            "SPARQL wall-clock deadline exceeded after %ss for %s (query prefix: %.120r)",
            timeout,
            endpoint_url,
            query,
        )
        raise
