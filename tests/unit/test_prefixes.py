from querybloom.abstat.prefixes import PrefixExtractor


def test_extracts_prefixes_and_compresses_uris_losslessly():
    uris = [
        "http://dbpedia.org/ontology/Person",
        "http://dbpedia.org/ontology/birthPlace",
        "http://dbpedia.org/resource/Albert_Einstein",
        "http://xmlns.com/foaf/0.1/name",
    ]

    extractor = PrefixExtractor(uris)

    assert extractor.prefixes == {
        "doo": "http://dbpedia.org/ontology/",
        "dor": "http://dbpedia.org/resource/",
        "xcf": "http://xmlns.com/foaf/0.1/",
    }
    assert extractor.uri_map[uris[0]] == "doo:Person"
    assert all(extractor.expand(extractor.compress(uri)) == uri for uri in uris)


def test_resolves_generated_prefix_collisions_deterministically():
    extractor = PrefixExtractor(
        [
            "https://alpha.example.org/ontology/Person",
            "https://another.example.org/ontology/Place",
        ]
    )

    assert extractor.prefixes == {
        "aeoo": "https://alpha.example.org/ontology/",
        "aeoo2": "https://another.example.org/ontology/",
    }


def test_supports_non_http_iris_and_falls_back_for_unsafe_local_names():
    uris = [
        "urn:isbn:9780134685991",
        "http://example.org/resource/John%20Smith",
        "http://example.org/no-local/",
        "http://example.org/item?id=123",
    ]

    extractor = PrefixExtractor(uris)

    assert extractor.compress(uris[0]).endswith(":9780134685991")
    assert extractor.compress(uris[1]) == f"<{uris[1]}>"
    assert extractor.compress(uris[2]) == f"<{uris[2]}>"
    assert extractor.compress(uris[3]) == f"<{uris[3]}>"
    assert all(extractor.expand(extractor.compress(uri)) == uri for uri in uris)


def test_output_is_independent_of_input_order_and_duplicates():
    uris = [
        "http://example.org/ontology/Person",
        "http://example.org/resource/Alice",
    ]

    first = PrefixExtractor(uris)
    second = PrefixExtractor([uris[1], uris[0], uris[0]])

    assert first.prefixes == second.prefixes
    assert first.uri_map == second.uri_map