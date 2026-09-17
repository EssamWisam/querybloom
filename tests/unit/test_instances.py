import querybloom.mining.instances as instances_module
from querybloom.mining.instances import (
    _instance_query,
    _sample_instance_rows,
    build_instance_sparql,
    mixed_row_is_complete,
    select_sampled_rows,
)


PERSON = "http://ex.org/Person"
CITY = "http://ex.org/City"
BIRTH = "http://ex.org/birthPlace"
DEATH = "http://ex.org/deathPlace"

EDGES = [
    {"s": PERSON, "p": BIRTH, "o": CITY, "is_optional": False},
    {"s": PERSON, "p": DEATH, "o": CITY, "is_optional": True},
]


def test_full_match_query_keeps_optional_edges_required():
    query = build_instance_sparql([PERSON, CITY], EDGES, optionalize=False, limit=5)
    assert "OPTIONAL" not in query
    assert f"?v1 <{BIRTH}> ?v0 . ?v0 a <{CITY}>" in query
    assert f"?v1 <{DEATH}> ?v0 . ?v0 a <{CITY}>" in query
    assert f"?v1 a <{PERSON}>" in query


def test_mixed_query_wraps_optional_edges():
    query = build_instance_sparql([PERSON, CITY], EDGES, optionalize=True, limit=5)
    assert f"?v1 <{BIRTH}> ?v0 . ?v0 a <{CITY}>" in query
    assert (
        f"OPTIONAL {{ ?v1 <{DEATH}> ?v0 . ?v0 a <{CITY}> . "
        "BIND(true AS ?opt1) }"
    ) in query


def test_converging_edges_share_the_target_type_variable():
    case = "http://ex.org/Case"
    charge_subject = "http://ex.org/ChargeSubject"
    charge = "http://ex.org/Charge"
    edges = [
        {"s": charge_subject, "p": "http://ex.org/personCharge", "o": charge},
        {"s": case, "p": "http://ex.org/caseCharge", "o": charge},
    ]

    query = build_instance_sparql(
        [case, charge_subject, charge], edges, optionalize=False, limit=5
    )

    assert f"<http://ex.org/personCharge> ?v1" in query
    assert f"<http://ex.org/caseCharge> ?v1" in query


def test_parallel_same_predicate_edges_require_distinct_targets():
    arrest = "http://ex.org/Arrest"
    location = "http://ex.org/Location"
    reference_point = "http://ex.org/RelativeLocationReferencePoint"
    predicate = "http://ex.org/location"
    edges = [
        {"s": arrest, "p": predicate, "o": location},
        {"s": arrest, "p": predicate, "o": reference_point},
    ]

    query = build_instance_sparql(
        [arrest, location, reference_point], edges, optionalize=False, limit=5
    )

    assert "FILTER(?v1 != ?v2)" in query


def test_different_predicates_do_not_require_distinct_targets():
    query = build_instance_sparql([PERSON, CITY], EDGES, optionalize=False, limit=5)

    assert "FILTER(" not in query


def test_query_excludes_saturated_entity_bindings():
    query = build_instance_sparql(
        [PERSON, CITY],
        EDGES,
        optionalize=False,
        limit=5,
        excluded_values={"v0": {"http://ex.org/Paris", "http://ex.org/Ulm"}},
    )

    assert (
        "FILTER(?v0 NOT IN (<http://ex.org/Paris>, <http://ex.org/Ulm>))"
        in query
    )


def test_optional_parallel_edge_is_distinct_regardless_of_edge_order():
    arrest = "http://ex.org/Arrest"
    location = "http://ex.org/Location"
    reference_point = "http://ex.org/RelativeLocationReferencePoint"
    predicate = "http://ex.org/location"
    edges = [
        {
            "s": arrest,
            "p": predicate,
            "o": reference_point,
            "is_optional": True,
        },
        {"s": arrest, "p": predicate, "o": location, "is_optional": False},
    ]

    query = build_instance_sparql(
        [arrest, location, reference_point], edges, optionalize=True, limit=5
    )

    assert "OPTIONAL" in query
    assert "FILTER((?v2 != ?v1))" in query


def test_mixed_row_is_complete_requires_optional_bindings():
    assert mixed_row_is_complete({"v1": "einstein", "opt1": "princeton"}, EDGES)
    assert not mixed_row_is_complete({"v0": "ulm", "v1": "einstein"}, EDGES)
    assert not mixed_row_is_complete({"v1": "turing"}, EDGES)


def test_select_uses_complete_mixed_row_without_full_query():
    type_to_var = {CITY: "v0", PERSON: "v1"}
    mixed = [
        {"v1": "curie"},
        {"v1": "einstein", "opt1": "princeton"},
        {"v1": "turing"},
    ]
    selected = select_sampled_rows(
        mixed, [], type_to_var, m=3, edges=EDGES
    )
    assert [kind for kind, _ in selected] == ["mixed", "mixed", "mixed"]
    assert selected[0][1]["v1"] == "einstein"
    assert {row["v1"] for _, row in selected} == {"einstein", "curie", "turing"}


def test_select_falls_back_to_full_query_when_mixed_has_no_complete():
    type_to_var = {CITY: "v0", PERSON: "v1"}
    mixed = [
        {"v1": "curie"},
        {"v1": "turing"},
    ]
    full = [{"v0": "ulm", "v1": "einstein"}]
    selected = select_sampled_rows(
        mixed, full, type_to_var, m=3, edges=EDGES
    )
    assert [kind for kind, _ in selected] == ["full", "mixed", "mixed"]
    assert selected[0][1]["v1"] == "einstein"
    assert {row["v1"] for _, row in selected} == {"einstein", "curie", "turing"}


def test_select_enforces_reuse_cap_across_full_and_mixed_rows():
    type_to_var = {CITY: "v0", PERSON: "v1"}
    mixed = [
        {"v0": "ulm", "v1": "curie"},
        {"v0": "ulm", "v1": "turing"},
        {"v0": "ulm", "v1": "lovelace"},
    ]
    full = [{"v0": "ulm", "v1": "einstein"}]

    selected = select_sampled_rows(
        mixed,
        full,
        type_to_var,
        m=4,
        edges=EDGES,
        max_entity_reuse=3,
    )

    assert len(selected) == 3
    assert all(row["v0"] == "ulm" for _, row in selected)


def test_sampling_requeries_after_entity_reaches_reuse_cap(monkeypatch):
    batches = [
        [
            {"v0": "city-a", "v1": f"person-{index}"}
            for index in range(5)
        ],
        [
            {"v0": "city-b", "v1": "person-3"},
            {"v0": "city-b", "v1": "person-4"},
        ],
    ]
    exclusions = []

    def fake_query(*args, excluded_values=None, **kwargs):
        exclusions.append(excluded_values)
        return batches[len(exclusions) - 1]

    monkeypatch.setattr(instances_module, "_instance_query", fake_query)

    rows = _sample_instance_rows(
        "endpoint",
        [PERSON, CITY],
        [EDGES[0]],
        optionalize=False,
        timeout=60,
        m=5,
        max_entity_reuse=3,
    )

    assert len(rows) == 5
    assert exclusions[1]["v0"] == {"city-a"}
    assert [row["v0"] for row in rows].count("city-a") == 3


def test_instance_query_preserves_rdf_term_types(monkeypatch):
    monkeypatch.setattr(
        instances_module,
        "execute",
        lambda *args, **kwargs: {
            "success": True,
            "results": [
                {
                    "v0": {"type": "uri", "value": "http://ex.org/person"},
                    "v1": {"type": "bnode", "value": "signature-1"},
                }
            ],
        },
    )

    rows = _instance_query(
        "endpoint",
        [PERSON, CITY],
        [EDGES[0]],
        optionalize=False,
        timeout=60,
        limit=1,
    )

    assert rows[0]["v0"] == "http://ex.org/person"
    assert rows[0]["v1"] == "signature-1"
    assert rows[0]["__term_types__"] == {"v0": "uri", "v1": "bnode"}


def test_sampling_does_not_push_blank_node_exclusions(monkeypatch):
    batches = [
        [
            {
                "v0": "city-a",
                "v1": f"signature-{index}",
                "__term_types__": {"v0": "uri", "v1": "bnode"},
            }
            for index in range(5)
        ],
        [
            {
                "v0": "city-b",
                "v1": "signature-3",
                "__term_types__": {"v0": "uri", "v1": "bnode"},
            },
            {
                "v0": "city-b",
                "v1": "signature-4",
                "__term_types__": {"v0": "uri", "v1": "bnode"},
            },
        ],
    ]
    exclusions = []

    def fake_query(*args, excluded_values=None, **kwargs):
        exclusions.append(excluded_values)
        return batches[len(exclusions) - 1]

    monkeypatch.setattr(instances_module, "_instance_query", fake_query)

    rows = _sample_instance_rows(
        "endpoint",
        [PERSON, CITY],
        [EDGES[0]],
        optionalize=False,
        timeout=60,
        m=5,
        max_entity_reuse=3,
    )

    assert len(rows) == 5
    assert exclusions[1]["v0"] == {"city-a"}
    assert exclusions[1]["v1"] == set()
