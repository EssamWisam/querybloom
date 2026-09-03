from querybloom.mining.yaml_v5 import (
    build_subgraph_yaml,
    dump_subgraph_yaml,
    format_value,
    is_v5_subgraph,
    parse_relationship_line,
)


PERSON = "http://dbpedia.org/ontology/Person"
CITY = "http://dbpedia.org/ontology/City"
BIRTH_PLACE = "http://dbpedia.org/ontology/birthPlace"
DEATH_PLACE = "http://dbpedia.org/ontology/deathPlace"
BIRTH_DATE = "http://dbpedia.org/ontology/birthDate"
NAME = "http://xmlns.com/foaf/0.1/name"
POPULATION = "http://dbpedia.org/ontology/populationTotal"
EINSTEIN = "http://dbpedia.org/resource/Albert_Einstein"
ULM = "http://dbpedia.org/resource/Ulm"
PRINCETON = "http://dbpedia.org/resource/Princeton"


def _mined_inputs():
    return {
        "subgraph_id": 3,
        "support": 150,
        "type_uris": [PERSON, CITY],
        "type_labels": {PERSON: "Person", CITY: "City"},
        "edges": [
            {"s": PERSON, "p": BIRTH_PLACE, "o": CITY, "is_optional": False},
            {"s": PERSON, "p": DEATH_PLACE, "o": CITY, "is_optional": True},
        ],
        "type_attributes": {
            PERSON: [
                {
                    "property": BIRTH_DATE,
                    "property_label": "date of birth",
                    "datatype": "http://www.w3.org/2001/XMLSchema#date",
                    "datatype_label": "date",
                    "support": 200,
                    "label_from_rdfs": True,
                },
                {
                    "property": NAME,
                    "property_label": "name",
                    "datatype": "http://www.w3.org/2001/XMLSchema#string",
                    "datatype_label": "string",
                    "support": 20,
                    "label_from_rdfs": False,
                },
            ],
            CITY: [
                {
                    "property": POPULATION,
                    "property_label": "populationTotal",
                    "datatype": "http://www.w3.org/2001/XMLSchema#integer",
                    "datatype_label": "integer",
                    "support": 180,
                    "label_from_rdfs": False,
                },
            ],
        },
        "instance_rows": [
            {
                "index": 0,
                "bindings": {
                    "Person": {"uri": EINSTEIN, "label": "Albert Einstein"},
                    "City": {"uri": ULM, "label": "Ulm"},
                },
                "triples": [
                    {
                        "source": EINSTEIN,
                        "predicate": BIRTH_PLACE,
                        "target": ULM,
                        "optional": False,
                    },
                    {
                        "source": EINSTEIN,
                        "predicate": DEATH_PLACE,
                        "target": PRINCETON,
                        "optional": True,
                    },
                ],
                "attributes": [
                    {
                        "source": EINSTEIN,
                        "property": BIRTH_DATE,
                        "property_label": "date of birth",
                        "value": "1879-03-14",
                        "label_from_rdfs": True,
                    },
                    {
                        "source": EINSTEIN,
                        "property": NAME,
                        "property_label": "name",
                        "value": "Albert Einstein",
                        "label_from_rdfs": False,
                    },
                    {
                        "source": ULM,
                        "property": POPULATION,
                        "property_label": "populationTotal",
                        "value": 126329,
                        "label_from_rdfs": False,
                    },
                    {
                        "source": PRINCETON,
                        "property": POPULATION,
                        "property_label": "populationTotal",
                        "value": 28572,
                        "label_from_rdfs": False,
                    },
                ],
            }
        ],
        "min_support": 150,
    }


def test_native_v5_schema_uses_curies_carets_and_optional_arrows():
    v5 = build_subgraph_yaml(**_mined_inputs())

    assert is_v5_subgraph(v5)
    assert v5["subgraph_id"] == 3
    assert v5["support"] == 150
    assert v5["prefixes"]["doo"] == "http://dbpedia.org/ontology/"
    assert v5["prefixes"]["dor"] == "http://dbpedia.org/resource/"
    assert v5["types"] == {"Person": "doo:Person", "City": "doo:City"}
    assert v5["attributes"]["Person"] == (
        "--date of birth^ (doo:birthDate)--> date | --name (xcf:name)-->* string"
    )
    assert v5["attributes"]["City"] == "--populationTotal (doo:populationTotal)--> integer"
    assert v5["relationships"] == [
        "Person --doo:birthPlace--> City",
        "Person --doo:deathPlace-->* City",
    ]


def test_native_v5_instances_mark_rdfs_labels_and_keep_curies():
    v5 = build_subgraph_yaml(**_mined_inputs())
    instance = v5["instances"][1]

    assert instance["relationships"] == [
        "Albert Einstein^ (dor:Albert_Einstein) --doo:birthPlace--> Ulm^ (dor:Ulm)",
        "Albert Einstein^ (dor:Albert_Einstein) --doo:deathPlace-->* Princeton (dor:Princeton)",
    ]
    assert instance["attributes"]["Albert Einstein^"] == (
        "(date of birth^='1879-03-14', name='Albert Einstein')"
    )
    assert instance["attributes"]["Ulm^"] == "(populationTotal=126329)"
    assert instance["attributes"]["Princeton"] == "(populationTotal=28572)"


def test_native_v5_dump_is_yaml_and_omits_legacy_fields():
    dumped = dump_subgraph_yaml(build_subgraph_yaml(**_mined_inputs()))

    assert "subgraph_id: 3" in dumped
    assert "support: 150" in dumped
    assert "sample_query" not in dumped
    assert "predicate_uris" not in dumped
    assert "sample_entities" not in dumped
    assert "num_types" not in dumped
    assert "min_support" not in dumped
    assert "-->*" in dumped


def test_format_value_doubles_inner_quotes():
    assert format_value("O'Brien") == "'O''Brien'"
    assert format_value("plain") == "'plain'"


def test_parse_relationship_line_accepts_old_and_v5_arrows():
    old = parse_relationship_line("Person --birthPlace --> City")
    v5 = parse_relationship_line("Person --doo:deathPlace-->* City")

    assert old == {
        "source": "Person",
        "predicate": "birthPlace",
        "optional": False,
        "target": "City",
    }
    assert v5 == {
        "source": "Person",
        "predicate": "doo:deathPlace",
        "optional": True,
        "target": "City",
    }
