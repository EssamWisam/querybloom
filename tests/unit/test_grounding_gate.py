from unittest.mock import patch

from querybloom.mining.search import mine_subgraphs


TYPE_A = "http://example.org/A"
TYPE_B = "http://example.org/B"
PREDICATE = "http://example.org/p"
PATTERN = (TYPE_A, PREDICATE, TYPE_B)


def test_mining_rejects_subgraph_without_grounded_instances():
    events = []
    empty_yaml = {
        "subgraph_id": 1,
        "support": 5,
        "types": {"A": "ex:A", "B": "ex:B"},
        "relationships": ["A --ex:p--> B"],
        "instances": {},
    }

    with patch(
        "querybloom.mining.search.prepare_subgraph_yaml_data",
        return_value=empty_yaml,
    ):
        found, _ = mine_subgraphs(
            endpoint="unused",
            patterns=[PATTERN],
            pattern_counts={PATTERN: 5},
            type_labels={TYPE_A: "A", TYPE_B: "B"},
            property_labels={PREDICATE: "p"},
            attribute_counts={},
            adj={},
            min_support=1,
            k=2,
            num_subgraphs=1,
            event_sink=events.append,
        )

    assert found == []
    assert any(event.type == "subgraph.rejected" for event in events)
    assert not any(event.type == "subgraph.discovered" for event in events)