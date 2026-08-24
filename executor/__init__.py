"""
Executor package for standalone ABSTAT.

Contains SPARQL execution utilities and functions.
"""

from querybloom.executor.sparql_executor import execute_sparql_query
from querybloom.executor.sparql_executor_utils import (
    SparqlStatus,
    SparqlExecutionResult,
)

__all__ = [
    "execute_sparql_query",
    "SparqlStatus",
    "SparqlExecutionResult",
]

