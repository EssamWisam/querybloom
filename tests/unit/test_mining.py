import sys
from pathlib import Path

# Ensure root and src directories are in sys.path
root_dir = str(Path(__file__).resolve().parent.parent.parent)
src_dir = str(Path(__file__).resolve().parent.parent.parent / "src")
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

import unittest

from querybloom.mining import (
    Candidate,
    SubgraphMiner,
    compute_k_slots,
    sample_target_k,
)
from querybloom.mining.utils import extract_binding_rows


class TestMiningPackage(unittest.TestCase):
    def test_imports_and_classes(self):
        """Verify that querybloom.mining exports expected classes."""
        self.assertTrue(callable(SubgraphMiner))
        self.assertTrue(callable(Candidate))

    def test_subgraph_miner_attributes(self):
        """Verify SubgraphMiner state attributes and method presence."""
        miner = SubgraphMiner(endpoint="sockg-local", min_support=50)
        self.assertEqual(miner.endpoint, "sockg-local")
        self.assertEqual(miner.min_support, 50)
        self.assertTrue(hasattr(miner, "abstat"))
        self.assertTrue(hasattr(miner, "patterns"))
        self.assertTrue(hasattr(miner, "adj"))
        self.assertTrue(hasattr(miner, "preprocess"))
        self.assertTrue(hasattr(miner, "mine"))
        self.assertTrue(hasattr(miner, "plot"))
        self.assertTrue(hasattr(miner, "get_support"))
        self.assertTrue(hasattr(miner, "sample_entities_for_type"))
        self.assertTrue(hasattr(miner, "sample_subgraph_instances"))
        self.assertTrue(hasattr(miner, "find_and_verify_attributes"))
        self.assertTrue(hasattr(miner, "prepare_subgraph_yaml_data"))
        self.assertTrue(hasattr(miner, "save_all_subgraphs_to_yaml"))

    def test_candidate_dataclass(self):
        """Verify Candidate initialization and target_k handling."""
        cand = Candidate(
            types={"http://ex.org/Person", "http://ex.org/City"},
            edges=[{"s": "http://ex.org/Person", "p": "http://ex.org/livesIn", "o": "http://ex.org/City"}],
            est_support=100,
            is_verified=True,
            seed_pattern=("http://ex.org/Person", "http://ex.org/livesIn", "http://ex.org/City"),
            has_optional=False,
            target_k=3,
        )
        self.assertEqual(cand.est_support, 100)
        self.assertEqual(cand.target_k, 3)
        self.assertEqual(len(cand.types), 2)

    def test_compute_k_slots_int(self):
        """Verify k_slots with integer k."""
        slots = compute_k_slots(k=3, num_subgraphs=10)
        self.assertEqual(slots, {3: 10})

    def test_compute_k_slots_tuple(self):
        """Verify k_slots with range tuple."""
        slots = compute_k_slots(k=(2, 4), num_subgraphs=9)
        self.assertEqual(sum(slots.values()), 9)
        self.assertEqual(set(slots.keys()), {2, 3, 4})

    def test_compute_k_slots_dict(self):
        """Verify k_slots with weighted dictionary."""
        k_weights = {3: 0.5, 4: 0.5}
        slots = compute_k_slots(k=k_weights, num_subgraphs=20)
        self.assertEqual(sum(slots.values()), 20)
        self.assertEqual(slots[3], 10)
        self.assertEqual(slots[4], 10)

    def test_sample_target_k(self):
        """Verify weighted sampling of target k from slots."""
        slots = {3: 5, 4: 0}
        target = sample_target_k(slots)
        self.assertEqual(target, 3)

        empty_slots = {3: 0, 4: 0}
        self.assertIsNone(sample_target_k(empty_slots))

    def test_extract_binding_rows(self):
        """Verify extraction from JSON-style SPARQL bindings."""
        mock_result = {
            "results": {
                "bindings": [
                    {"v0": {"value": "http://ex.org/1"}, "v1": {"value": "http://ex.org/2"}},
                    {"v0": {"value": "http://ex.org/3"}, "v1": {"value": "http://ex.org/4"}},
                ]
            }
        }
        rows = extract_binding_rows(mock_result)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["v0"], "http://ex.org/1")
        self.assertEqual(rows[1]["v1"], "http://ex.org/4")


if __name__ == "__main__":
    unittest.main()
