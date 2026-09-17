import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery

from metrics.parsing import anonymise_query, get_entity_classes, normalize_sparql, resolve_terms


QALD9_PATH = Path(__file__).parent / "new_data" / "qald9-test.jsonl"


class NormalizeSparqlTests(unittest.TestCase):
    def assert_parses(self, query):
        translateQuery(parseQuery(query))

    def test_final_triple_does_not_need_a_dot(self):
        query = "SELECT ?s WHERE { ?s <http://example.org/p> ?o }"
        self.assertEqual(normalize_sparql(query), query)
        self.assert_parses(query)

    def test_repairs_literal_suffix_spacing(self):
        query = (
            'SELECT ?s WHERE { ?s <http://example.org/p> "English" @en ; '
            '<http://example.org/q> "1" ^^ <http://www.w3.org/2001/XMLSchema#integer> }'
        )
        normalized = normalize_sparql(query)
        self.assertIn('"English"@en', normalized)
        self.assertIn('"1"^^<http://www.w3.org/2001/XMLSchema#integer>', normalized)
        self.assert_parses(normalized)

    def test_adds_only_used_qald9_prefixes(self):
        query = "SELECT ?s WHERE { ?s dct:subject dbc:People }"
        normalized = normalize_sparql(query, QALD9_PATH)
        self.assertIn("PREFIX dct: <http://purl.org/dc/terms/>", normalized)
        self.assertIn(
            "PREFIX dbc: <http://dbpedia.org/resource/Category:", normalized
        )
        self.assertNotIn("PREFIX yago:", normalized)
        self.assert_parses(normalized)

    def test_does_not_add_qald9_prefixes_to_other_datasets(self):
        query = "SELECT ?s WHERE { ?s dct:subject dbc:People }"
        self.assertEqual(normalize_sparql(query, "other.jsonl"), query)

    def test_preserves_graph_and_service_patterns(self):
        query = (
            "SELECT ?s WHERE { GRAPH ?g { ?s <http://example.org/p> ?o } "
            "SERVICE <http://example.org/sparql> { ?s <http://example.org/q> ?o } }"
        )
        normalized = normalize_sparql(query)
        self.assertNotIn("GRAPH ?g .", normalized)
        self.assertNotIn("SERVICE <http://example.org/sparql> .", normalized)
        self.assert_parses(normalized)

    def test_all_qald9_queries_translate(self):
        with QALD9_PATH.open() as dataset:
            queries = [json.loads(line)["sparql"] for line in dataset if line.strip()]

        self.assertEqual(len(queries), 150)
        for index, query in enumerate(queries, start=1):
            with self.subTest(query_index=index):
                self.assert_parses(normalize_sparql(query, QALD9_PATH))


class AnonymiseQueryTests(unittest.TestCase):
    def test_removes_inline_prefix_declarations(self):
        query = "PREFIX ex: <http://example.org/> SELECT ?item WHERE { ?item ex:p ?value }"

        self.assertEqual(
            anonymise_query(query),
            "SELECT ?VAR WHERE { ?VAR <URI> ?VAR }",
        )

    def test_replaces_single_quoted_and_numeric_literals(self):
        query = (
            "SELECT ?item WHERE { ?item <http://example.org/p> 'LWA' . "
            '?item <http://example.org/q> 3.14 . '
            '?item <http://example.org/r> "English"^^<http://example.org/type> }'
        )

        self.assertEqual(
            anonymise_query(query),
            "SELECT ?VAR WHERE { ?VAR <URI> <LITERAL> . ?VAR <URI> <LITERAL> . "
            "?VAR <URI> <LITERAL> }",
        )


class ResolveTermsTests(unittest.TestCase):
    def test_classification_uses_syntax_endpoint_evidence_and_yaml_fallback(self):
        syntactic_class = "http://example.org/SyntacticClass"
        meta_class = "http://example.org/MetaClass"
        inferred_class = "http://example.org/InferredClass"
        punned_entity = "http://example.org/PunnedEntity"
        implied_class = "http://example.org/ImpliedClass"
        indexed_class = "http://example.org/IndexedClass"
        entity = "http://example.org/Entity"
        parsed = {
            "classes": {syntactic_class},
            "entities": [meta_class, inferred_class, punned_entity, indexed_class, entity],
        }
        type_lookup = {
            meta_class: {"http://www.w3.org/2002/07/owl#Class"},
            inferred_class: set(),
            punned_entity: {implied_class},
            indexed_class: set(),
            entity: set(),
        }

        with patch("metrics.parsing.get_entity_classes", side_effect=lambda uri, *_: type_lookup[uri]), \
             patch("metrics.parsing.uri_has_instances", side_effect=lambda uri, *_: uri == inferred_class), \
             patch("ontology_loader.load_ontology_classes", return_value={indexed_class}):
            resolved = resolve_terms(parsed, kg_name="example")

        self.assertEqual(
            resolved["classes"],
            {
                syntactic_class,
                meta_class,
                inferred_class,
                implied_class,
                indexed_class,
            },
        )
        self.assertEqual(resolved["entities"], [punned_entity, entity])

    def test_duplicate_entities_are_looked_up_once_and_preserve_multiplicity(self):
        entity = "http://example.org/Entity"
        parsed = {"classes": set(), "entities": [entity, entity]}

        with patch("metrics.parsing.get_entity_classes", return_value={"http://example.org/Type"}) as lookup:
            resolved = resolve_terms(parsed)

        lookup.assert_called_once()
        self.assertEqual(resolved["entities"], [entity, entity])

    def test_malformed_type_response_is_not_cached(self):
        with tempfile.TemporaryDirectory() as cache_dir, \
             patch("metrics.parsing._ENTITY_TYPE_CACHE_DIR", cache_dir), \
             patch(
                 "metrics.parsing.execute_sparql_query",
                 return_value={"success": True, "results": None},
             ):
            result = get_entity_classes(
                "http://example.org/Entity", query_source="dataset", query_index=1
            )

            self.assertIsNone(result)
            self.assertEqual(os.listdir(cache_dir), [])


if __name__ == "__main__":
    unittest.main()