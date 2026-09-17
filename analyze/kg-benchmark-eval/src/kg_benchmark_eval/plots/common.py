"""Shared optional-dependency and validation helpers for plots."""

from __future__ import annotations

from collections.abc import Iterable
from importlib import import_module
from typing import Any

COLORS = ("#176B87", "#D95D39")


class MissingMetricError(ValueError):
    """Raised when a plot's required stored metrics are unavailable."""


def require(values: Iterable[tuple[str, object | None]]) -> None:
    missing = [metric for metric, value in values if value is None]
    if missing:
        raise MissingMetricError("missing required metrics: " + ", ".join(missing))


def pyplot() -> Any:
    try:
        plt = import_module("matplotlib.pyplot")
    except ImportError as exc:
        raise ImportError("plotting requires kg-benchmark-eval[plots]") from exc
    return plt
