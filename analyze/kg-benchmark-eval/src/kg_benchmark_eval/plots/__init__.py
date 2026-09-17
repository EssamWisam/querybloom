"""Plots and HTML diagnostics built exclusively from stored evaluation results."""

from .common import MissingMetricError
from .coverage import comprehensiveness, coverage_gaps
from .diversity import semantic_space, structural_diversity
from .entities import entities
from .redundancy import redundancy, redundancy_examples

__all__ = [
    "MissingMetricError",
    "comprehensiveness",
    "coverage_gaps",
    "entities",
    "redundancy",
    "redundancy_examples",
    "semantic_space",
    "structural_diversity",
]
