import sys
from pathlib import Path

# Ensure root and src directories are in sys.path
root_dir = str(Path(__file__).resolve().parent.parent.parent)
src_dir = str(Path(__file__).resolve().parent.parent.parent / "src")
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from querybloom.abstat import (
    ABSTAT,
    ABSTAT_v2,
    get_property_domain_range,
    is_subtype,
    minimal_types,
)

import unittest


class TestAbstatPackage(unittest.TestCase):
    def test_abstat_symbols(self):
        """Verify that querybloom.abstat exports expected classes and functions."""
        self.assertTrue(callable(ABSTAT_v2))
        self.assertTrue(callable(ABSTAT))
        self.assertTrue(callable(get_property_domain_range))

    def test_abstat_instance_attributes(self):
        """Verify that ABSTAT_v2 has all expected state attributes and methods."""
        ab = ABSTAT_v2(endpoint="sockg-local")
        self.assertEqual(ab.endpoint, "sockg-local")
        self.assertTrue(hasattr(ab, "patterns"))
        self.assertTrue(hasattr(ab, "pattern_counts"))
        self.assertTrue(hasattr(ab, "attribute_patterns"))
        self.assertTrue(hasattr(ab, "attribute_counts"))
        self.assertTrue(hasattr(ab, "type_labels"))
        self.assertTrue(hasattr(ab, "property_labels"))
        self.assertTrue(hasattr(ab, "prefetch_subclass_graph"))
        self.assertTrue(hasattr(ab, "is_subtype"))
        self.assertTrue(hasattr(ab, "process_properties"))
        self.assertTrue(hasattr(ab, "compute_minimal_patterns"))
        self.assertTrue(hasattr(ab, "plot_schema_graph"))
        self.assertTrue(hasattr(ab, "print_data"))

    def test_is_subtype_taxonomy(self):
        """Verify local transitive closure resolution in is_subtype."""
        subclass_graph = {
            "http://ex.org/Child": {"http://ex.org/Parent"},
            "http://ex.org/Parent": {"http://ex.org/Grandparent"},
        }
        cache = {}

        # Reflexive
        self.assertTrue(is_subtype("http://ex.org/Child", "http://ex.org/Child", subclass_graph, cache, "dummy", False, True, True))

        # Transitive subtype
        self.assertTrue(is_subtype("http://ex.org/Child", "http://ex.org/Grandparent", subclass_graph, cache, "dummy", False, True, True))

        # Not a subtype
        self.assertFalse(is_subtype("http://ex.org/Grandparent", "http://ex.org/Child", subclass_graph, cache, "dummy", False, True, True))

    def test_minimal_types_reduction(self):
        """Verify that minimal_types retains only the most specific types."""
        subclass_graph = {
            "http://ex.org/Dog": {"http://ex.org/Canine"},
            "http://ex.org/Canine": {"http://ex.org/Animal"},
        }
        cache = {}

        def is_sub(x, y):
            return is_subtype(x, y, subclass_graph, cache, "dummy", False, True, True)

        types = {"http://ex.org/Dog", "http://ex.org/Canine", "http://ex.org/Animal"}
        result = minimal_types(types, is_sub)
        self.assertEqual(result, {"http://ex.org/Dog"})


if __name__ == "__main__":
    unittest.main()
