from __future__ import annotations

import pytest

from kg_benchmark_eval.ontology import Ontology, OntologyLoadError


def test_from_sets_filters_meta_namespaces_and_is_immutable():
    ontology = Ontology.from_sets(
        classes={
            "https://example.org/Person",
            "http://www.w3.org/2002/07/owl#Class",
        },
        properties={
            "https://example.org/name",
            "http://www.w3.org/2000/01/rdf-schema#label",
        },
        name="example",
    )

    assert ontology.classes == frozenset({"https://example.org/Person"})
    assert ontology.properties == frozenset({"https://example.org/name"})
    assert ontology.missing_classes is False
    assert ontology.missing_properties is False
    assert len(ontology.fingerprint) == 64


def test_from_directory_loads_modern_files_and_deduplicates(tmp_path):
    kg_dir = tmp_path / "example"
    kg_dir.mkdir()
    (kg_dir / "classes.yaml").write_text(
        "- class: https://example.org/Person\n"
        "- class: https://example.org/Person\n"
        "- ignored: https://example.org/Other\n",
        encoding="utf-8",
    )
    (kg_dir / "properties.yaml").write_text(
        "- property: https://example.org/name\n",
        encoding="utf-8",
    )

    ontology = Ontology.from_directory(tmp_path, kg="example")

    assert ontology.classes == frozenset({"https://example.org/Person"})
    assert ontology.properties == frozenset({"https://example.org/name"})
    assert ontology.class_source is not None
    assert ontology.property_source is not None
    assert ontology.class_source.sha256


def test_from_directory_falls_back_to_legacy_filenames(tmp_path):
    kg_dir = tmp_path / "legacy"
    kg_dir.mkdir()
    (kg_dir / "legacy_classes.yaml").write_text(
        "- class: https://example.org/Class\n", encoding="utf-8"
    )
    (kg_dir / "legacy_props.yaml").write_text(
        "- property: https://example.org/property\n", encoding="utf-8"
    )

    ontology = Ontology.from_directory(tmp_path, kg="legacy")

    assert ontology.classes == frozenset({"https://example.org/Class"})
    assert ontology.properties == frozenset({"https://example.org/property"})


def test_missing_files_are_explicit_empty_universes(tmp_path):
    ontology = Ontology.from_directory(tmp_path, kg="missing")

    assert ontology.classes == frozenset()
    assert ontology.properties == frozenset()
    assert ontology.missing_classes is True
    assert ontology.missing_properties is True
    assert {diagnostic.code for diagnostic in ontology.diagnostics} == {
        "missing_ontology_classes",
        "missing_ontology_properties",
    }


def test_malformed_yaml_names_the_source_path(tmp_path):
    kg_dir = tmp_path / "broken"
    kg_dir.mkdir()
    path = kg_dir / "classes.yaml"
    path.write_text("- class: [\n", encoding="utf-8")

    with pytest.raises(OntologyLoadError, match="classes.yaml"):
        Ontology.from_directory(tmp_path, kg="broken")
