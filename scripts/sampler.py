#!/usr/bin/env python3
"""
Subgraph mining script for a single knowledge graph.
Usage: python sampler.py <kg_name>
"""

import sys
import os
from datetime import datetime

# Mining configuration
MIN_SUPPORT = 10
PROPERTY_LIMIT = 100000
MAX_TRIPLES = 300000
MINIMIZE_PATTERNS = True
NUM_SUBGRAPHS = 120
MAX_SUBGRAPHS_PER_SEED = 1
EXACT_SUPPORT = False
VERIF_TIMEOUT = 30
M = 7
NUM_ATTRS = (5, 9)
K_DISTRIBUTION = {3: 0.7, 4: 0.2, 5: 0.1}

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from querybloom.sampling_service import (
    SamplingMineConfig,
    SamplingPreprocessConfig,
    SamplingRunConfig,
    run_sampling,
)


def main():
    """
    Process a single knowledge graph.
    """
    if len(sys.argv) != 2:
        print("Usage: python sampler.py <kg_name>")
        print("Example: python sampler.py dream-kg")
        sys.exit(1)

    kg_name = sys.argv[1]

    print(f"\n{'='*60}")
    print(f"SUBGRAPH MINING: {kg_name}")
    print(f"{'='*60}")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\nConfiguration:")
    print(f"  Min Support: {MIN_SUPPORT}")
    print(f"  Property Limit: {PROPERTY_LIMIT}")
    print(f"  Max Triples: {MAX_TRIPLES}")
    print(f"  Num Subgraphs: {NUM_SUBGRAPHS}")
    print(f"  K Distribution: {K_DISTRIBUTION}")
    print(f"{'='*60}\n")

    try:
        print(f"Initializing sampling service with min_support={MIN_SUPPORT}")
        config = SamplingRunConfig(
            endpoint=kg_name,
            min_support=MIN_SUPPORT,
            preprocess=SamplingPreprocessConfig(
                property_limit=PROPERTY_LIMIT,
                max_triples=MAX_TRIPLES,
                minimize_patterns=MINIMIZE_PATTERNS,
            ),
            mine=SamplingMineConfig(
                k=K_DISTRIBUTION,
                num_subgraphs=NUM_SUBGRAPHS,
                max_subgraphs_per_seed=MAX_SUBGRAPHS_PER_SEED,
                exact_support=EXACT_SUPPORT,
                verif_timeout=VERIF_TIMEOUT,
                m=M,
                output_dir="./subgraphs_output",
                num_attrs=NUM_ATTRS,
            ),
        )
        result = run_sampling(config)
        num_subgraphs = result.num_subgraphs
        print(f"\n{'='*60}")
        print(f"✓ SUCCESS: Found {num_subgraphs} subgraphs!")
        print(f"Output saved to: {result.output_path or './subgraphs_output/'}")
        print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

        sys.exit(0)

    except Exception as e:
        print(f"\n{'='*60}")
        print(f"✗ ERROR: {str(e)}")
        print(f"{'='*60}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
