from unittest.mock import patch

from querybloom.mining.support import get_support


def test_support_requires_distinct_targets_for_parallel_edges():
    arrest = "http://ex.org/Arrest"
    location = "http://ex.org/Location"
    reference_point = "http://ex.org/RelativeLocationReferencePoint"
    predicate = "http://ex.org/location"

    with patch(
        "querybloom.mining.support.execute",
        return_value={"success": True, "results": [{"count": 0}]},
    ) as execute:
        get_support(
            "unused",
            {arrest, location, reference_point},
            [
                (arrest, predicate, location),
                (arrest, predicate, reference_point),
            ],
        )

    query = execute.call_args.args[0]
    assert "FILTER(?v1 != ?v2)" in query


def test_support_does_not_separate_edges_with_different_predicates():
    person = "http://ex.org/Person"
    city = "http://ex.org/City"

    with patch(
        "querybloom.mining.support.execute",
        return_value={"success": True, "results": [{"count": 0}]},
    ) as execute:
        get_support(
            "unused",
            {person, city},
            [
                (person, "http://ex.org/birthPlace", city),
                (person, "http://ex.org/deathPlace", city),
            ],
        )

    assert "FILTER(" not in execute.call_args.args[0]