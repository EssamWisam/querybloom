from __future__ import annotations

from kg_benchmark_eval.preprocessing import (
    FEATURE_KEYS,
    analyze_text,
    normalize_sparql,
    parse_sparql,
)


def test_normalization_repairs_escapes_suffixes_and_only_used_qald_prefixes():
    query = (
        "SELECT ?s WHERE { <https://example.org/Armageddon_\\(2008\\)> "
        'dct:subject dbc:Films ; <https://example.org/name> "English" @en ; '
        '<https://example.org/count> "1" ^^ <http://www.w3.org/2001/XMLSchema#integer> }'
    )

    normalized = normalize_sparql(query, profile="qald9")

    assert "Armageddon_(2008)" in normalized
    assert '"English"@en' in normalized
    assert '"1"^^<http://www.w3.org/2001/XMLSchema#integer>' in normalized
    assert "PREFIX dct:" in normalized
    assert "PREFIX dbc:" in normalized
    assert "PREFIX yago:" not in normalized
    assert normalize_sparql(query, profile="standard").startswith("SELECT")


def test_text_analysis_preserves_whole_template_whitespace_but_strips_lang_gate():
    query = (
        "PREFIX ex: <https://example.org/>\n"
        "SELECT  ?item WHERE {\n"
        "  ?item ex:name ?name . FILTER(lang(?name) = 'en')\n"
        "}"
    )

    analysis = analyze_text(query)

    assert "SELECT  ?VAR" in analysis.template
    assert analysis.features["FILTER"] == 0
    assert analysis.filter_templates == ()


def test_filter_templates_preserve_occurrences_and_subtypes_are_distinct():
    query = (
        "SELECT ?s WHERE { ?s ?p ?o . "
        "FILTER(regex(str(?o), 'x')) FILTER(regex(str(?o), 'y')) "
        "FILTER(?o != 2) }"
    )

    analysis = analyze_text(query)

    assert len(analysis.filter_templates) == 3
    assert analysis.filter_subtypes == frozenset({"FILTER:REGEX", "FILTER:!="})
    assert tuple(analysis.features) == FEATURE_KEYS


def test_parser_preserves_entity_occurrences_and_separates_terms():
    query = (
        "SELECT ?person WHERE { "
        "<https://example.org/Alice> a <https://example.org/Person> . "
        "<https://example.org/Alice> <https://example.org/name> 'Alice' . "
        "?person ?predicate <https://example.org/Alice> }"
    )

    parsed = parse_sparql(query)

    assert parsed.parse_status == "ok"
    assert parsed.num_triples == 3
    assert parsed.variables == frozenset({"person"})
    assert parsed.syntactic_classes == frozenset({"https://example.org/Person"})
    assert parsed.properties == frozenset(
        {
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
            "https://example.org/name",
        }
    )
    assert parsed.raw_entities.count("https://example.org/Alice") == 3
    assert parsed.literals == ("Alice",)


def test_parse_failure_keeps_text_features_available():
    query = "SELECT ?s WHERE { ?s ?p ?o FILTER(?o > 2)"

    parsed = parse_sparql(query)
    analysis = analyze_text(query)

    assert parsed.parse_status == "failed"
    assert parsed.num_triples == 0
    assert analysis.features["SELECT"] == 1
    assert analysis.features["FILTER"] == 1
