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
from unittest.mock import MagicMock

from querybloom.llm import (
    ComplexityAugmentation,
    ComplexityIntroducerResult,
    QuestionQueryPair,
    RewordPairResult,
    RewordResult,
    SubgraphGenerationResult,
    VerificationPairResult,
    VerificationResult,
    load_complexity_system_template,
    load_complexity_template,
    load_generate_system_template,
    load_prompt_template,
    load_reword_system_template,
    load_reword_template,
    load_system_template,
    load_verify_system_template,
    load_verify_template,
    parse_structured_response,
    process_subgraphs_data,
    process_subgraphs_yaml,
    render_complexity_messages,
    render_complexity_prompt,
    render_prompt,
    render_prompt_messages,
    render_reword_messages,
    render_reword_prompt,
    render_verify_messages,
    render_verify_prompt,
    subsample_subgraph_entities,
)
from querybloom.llm.models import (
    QuestionQueryPair as QQPair_Direct,
    SubgraphGenerationResult as SGResult_Direct,
)


class TestLlmPackage(unittest.TestCase):
    def test_imports_and_models(self):
        """Verify that querybloom.llm exports models correctly."""
        self.assertIs(QuestionQueryPair, QQPair_Direct)
        self.assertIs(SubgraphGenerationResult, SGResult_Direct)
        self.assertTrue(callable(process_subgraphs_data))
        self.assertTrue(callable(process_subgraphs_yaml))

    def test_question_query_pair_model(self):
        """Test QuestionQueryPair validation."""
        pair = QuestionQueryPair(
            text_query="What are the books written by Tolkien?",
            sparql_query="SELECT ?book WHERE { ?book <http://ex.org/author> <http://ex.org/Tolkien> . }",
        )
        self.assertEqual(pair.text_query, "What are the books written by Tolkien?")
        self.assertIn("SELECT ?book", pair.sparql_query)

    def test_subgraph_generation_result_model(self):
        """Test SubgraphGenerationResult schema."""
        res = SubgraphGenerationResult(
            is_meaningful=True,
            questions=[
                QuestionQueryPair(text_query="Q1", sparql_query="SELECT ?x WHERE { ?x a ?t }"),
                QuestionQueryPair(text_query="Q2", sparql_query="SELECT ?y WHERE { ?y a ?t }"),
            ],
        )
        self.assertTrue(res.is_meaningful)
        self.assertEqual(res.skip_reason, "")
        self.assertEqual(len(res.questions), 2)

    def test_verification_models(self):
        """Test VerificationPairResult and VerificationResult schemas."""
        pair_v = VerificationPairResult(
            status="needs_fix",
            reason="Empty variable binding",
            fixed_text_query="Fixed Q",
            fixed_sparql_query="SELECT * WHERE { ?x ?y ?z }",
        )
        self.assertEqual(pair_v.status, "needs_fix")
        self.assertEqual(pair_v.fixed_text_query, "Fixed Q")
        unfixable = VerificationPairResult(status="unfixable", reason="No grounded repair")
        self.assertEqual(unfixable.status, "unfixable")

        v_res = VerificationResult(
            all_correct=False,
            pairs=[pair_v],
        )
        self.assertFalse(v_res.all_correct)

    def test_complexity_models(self):
        """Test ComplexityAugmentation and ComplexityIntroducerResult schemas."""
        aug = ComplexityAugmentation(
            skipped=False,
            reason="Filter to a publication year is a realistic expert constraint",
            complexity_types=["FILTER", "OPTIONAL"],
            augmented_text_query="What are books published after 2000?",
            augmented_sparql_query="SELECT ?b WHERE { ?b a :Book . FILTER(?year > 2000) }",
        )
        self.assertFalse(aug.skipped)
        self.assertEqual(aug.reason, "Filter to a publication year is a realistic expert constraint")
        self.assertEqual(aug.complexity_types, ["FILTER", "OPTIONAL"])

        ci_res = ComplexityIntroducerResult(augmentations=[aug])
        self.assertEqual(len(ci_res.augmentations), 1)

    def test_reword_models(self):
        """Test RewordPairResult and RewordResult schemas."""
        rw = RewordPairResult(
            status="needs_reword",
            reason="Grammar improvement",
            issue_types=["phrasing"],
            reworded_text_query="Which books were published by Tolkien?",
        )
        self.assertEqual(rw.status, "needs_reword")
        self.assertEqual(rw.issue_types, ["phrasing"])

        rw_res = RewordResult(pairs=[rw], most_meaningful_index=1)
        self.assertEqual(len(rw_res.pairs), 1)
        self.assertEqual(rw_res.most_meaningful_index, 1)

    def test_parse_structured_response_standard(self):
        """Test parsing standard OpenAI-style response."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"is_meaningful": true, "questions": [{"text_query": "Q", "sparql_query": "S"}]}'
                )
            )
        ]
        res = parse_structured_response(mock_response, SubgraphGenerationResult)
        self.assertTrue(res.is_meaningful)
        self.assertEqual(len(res.questions), 1)

    def test_parse_structured_response_anthropic_wrapper(self):
        """Test unwrapping Anthropic parameter envelope."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"parameter": {"is_meaningful": false, "questions": []}}'
                )
            )
        ]
        res = parse_structured_response(mock_response, SubgraphGenerationResult)
        self.assertFalse(res.is_meaningful)
        self.assertEqual(len(res.questions), 0)

    def test_subsample_subgraph_entities(self):
        """Test uniform entity subsampling across types."""
        sg = {
            "types": {
                "Person": {"sample_entities": [{"uri": f"http://ex.org/p{i}"} for i in range(10)]},
                "City": {"sample_entities": [{"uri": f"http://ex.org/c{i}"} for i in range(10)]},
            }
        }
        subsampled = subsample_subgraph_entities(sg, ents_ratio=0.4)
        person_ents = subsampled["types"]["Person"]["sample_entities"]
        city_ents = subsampled["types"]["City"]["sample_entities"]
        self.assertEqual(len(person_ents), 4)
        self.assertEqual(len(city_ents), 4)

    def test_jinja_templates_and_rendering(self):
        """Test legacy template loading and rendering."""
        gen_tmpl = load_prompt_template()
        prompt = render_prompt("pattern: test", 0, gen_tmpl)
        self.assertIn("pattern: test", prompt)

        mock_qa = [
            {
                "question": "Q",
                "sparql_query": "S",
                "execution_results": {"success": True, "count": 1, "result_preview": None},
            }
        ]
        c_tmpl = load_complexity_template()
        c_prompt = render_complexity_prompt("pattern: test", mock_qa, c_tmpl)
        self.assertIn("pattern: test", c_prompt)

        v_tmpl = load_verify_template()
        v_prompt = render_verify_prompt("pattern: test", mock_qa, v_tmpl)
        self.assertIn("pattern: test", v_prompt)

        rw_tmpl = load_reword_template()
        rw_prompt = render_reword_prompt(mock_qa, rw_tmpl)
        self.assertIn("Q", rw_prompt)

    def test_system_prompt_templates_and_messages(self):
        """Test system template loading and system/user messages rendering for all 4 agents."""
        mock_qa = [
            {
                "question": "Q",
                "sparql_query": "S",
                "execution_results": {"success": True, "count": 1, "result_preview": None},
            }
        ]

        # 1. Generator Agent
        gen_sys_tmpl = load_generate_system_template()
        self.assertIsNotNone(gen_sys_tmpl)
        gen_msgs = render_prompt_messages("pattern: test", 0)
        self.assertEqual(len(gen_msgs), 2)
        self.assertEqual(gen_msgs[0]["role"], "system")
        self.assertIn("expert in analyzing a subgraph", gen_msgs[0]["content"])
        self.assertEqual(gen_msgs[1]["role"], "user")
        self.assertIn("pattern: test", gen_msgs[1]["content"])

        # 2. Complexity Agent
        comp_sys_tmpl = load_complexity_system_template()
        self.assertIsNotNone(comp_sys_tmpl)
        comp_msgs = render_complexity_messages("pattern: test", mock_qa)
        self.assertEqual(len(comp_msgs), 2)
        self.assertEqual(comp_msgs[0]["role"], "system")
        self.assertIn("expert in SPARQL and knowledge graph question design", comp_msgs[0]["content"])
        self.assertEqual(comp_msgs[1]["role"], "user")
        self.assertIn("pattern: test", comp_msgs[1]["content"])

        # 3. Reword Agent
        rw_sys_tmpl = load_reword_system_template()
        self.assertIsNotNone(rw_sys_tmpl)
        rw_msgs = render_reword_messages(mock_qa)
        self.assertEqual(len(rw_msgs), 2)
        self.assertEqual(rw_msgs[0]["role"], "system")
        self.assertIn("expert in natural language question design", rw_msgs[0]["content"])
        self.assertEqual(rw_msgs[1]["role"], "user")
        self.assertIn("Pairs to Audit:", rw_msgs[1]["content"])

        # 4. Verify Agent
        ver_sys_tmpl = load_verify_system_template()
        self.assertIsNotNone(ver_sys_tmpl)
        ver_msgs = render_verify_messages("pattern: test", mock_qa)
        self.assertEqual(len(ver_msgs), 2)
        self.assertEqual(ver_msgs[0]["role"], "system")
        self.assertIn("expert in SPARQL and knowledge graph querying", ver_msgs[0]["content"])
        self.assertEqual(ver_msgs[1]["role"], "user")
        self.assertIn("pattern: test", ver_msgs[1]["content"])


if __name__ == "__main__":
    unittest.main()
