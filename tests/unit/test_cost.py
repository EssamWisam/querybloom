import sys
from pathlib import Path
from unittest.mock import MagicMock

# Ensure root and src directories are in sys.path
root_dir = str(Path(__file__).resolve().parent.parent.parent)
src_dir = str(Path(__file__).resolve().parent.parent.parent / "src")
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

import unittest
from querybloom.llm.cost import calculate_completion_cost, extract_usage_and_cost
from querybloom.llm import process_single_subgraph_pipeline


class TestLlmCost(unittest.TestCase):
    def test_extract_usage_and_cost_from_model_response(self):
        """Test extraction from standard ModelResponse-like object."""
        mock_response = MagicMock()
        mock_response.model = "gpt-4o-mini"
        mock_response.usage.prompt_tokens = 120
        mock_response.usage.completion_tokens = 80
        mock_response.usage.total_tokens = 200

        usage = extract_usage_and_cost(mock_response, model="gpt-4o-mini")
        self.assertEqual(usage["prompt_tokens"], 120)
        self.assertEqual(usage["completion_tokens"], 80)
        self.assertEqual(usage["total_tokens"], 200)
        self.assertIsInstance(usage["cost_usd"], float)
        self.assertGreater(usage["cost_usd"], 0.0)

    def test_extract_usage_and_cost_from_dict(self):
        """Test extraction from dictionary format."""
        resp_dict = {
            "model": "gpt-4o-mini",
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 25,
                "total_tokens": 75,
            },
        }
        usage = extract_usage_and_cost(resp_dict, model="gpt-4o-mini")
        self.assertEqual(usage["prompt_tokens"], 50)
        self.assertEqual(usage["completion_tokens"], 25)
        self.assertEqual(usage["total_tokens"], 75)
        self.assertIsInstance(usage["cost_usd"], float)

    def test_calculate_completion_cost_fallback(self):
        """Test graceful fallback for unknown/unsupported models."""
        mock_response = MagicMock()
        mock_response.model = "unsupported-model-999"
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_response.usage.total_tokens = 150

        cost = calculate_completion_cost(mock_response, model="unsupported-model-999")
        self.assertEqual(cost, 0.0)

    def test_pipeline_cost_aggregation(self):
        """Test that process_single_subgraph_pipeline aggregates cost and llm_usage."""
        from unittest.mock import patch
        from querybloom.llm.models import (
            SubgraphGenerationResult,
            QuestionQueryPair,
            ComplexityIntroducerResult,
            ComplexityAugmentation,
            RewordResult,
            RewordPairResult,
        )

        mock_gen_result = SubgraphGenerationResult(
            is_meaningful=True,
            questions=[QuestionQueryPair(text_query="Q1", sparql_query="SELECT ?x WHERE { ?x a ?t }")],
        )
        mock_qa_pairs = [
            {
                "question": "Q1",
                "sparql_query": "SELECT ?x WHERE { ?x a ?t }",
                "execution_results": {"count": 1},
            }
        ]
        mock_gen_usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "cost_usd": 0.0015,
        }

        mock_ci_result = ComplexityIntroducerResult(
            augmentations=[ComplexityAugmentation(skipped=True)]
        )
        mock_ci_usage = {
            "prompt_tokens": 60,
            "completion_tokens": 20,
            "total_tokens": 80,
            "cost_usd": 0.0008,
        }

        mock_rw_result = RewordResult(
            pairs=[RewordPairResult(status="clean")],
            most_meaningful_index=1,
        )
        mock_rw_usage = {
            "prompt_tokens": 40,
            "completion_tokens": 10,
            "total_tokens": 50,
            "cost_usd": 0.0005,
        }

        with patch("querybloom.llm.pipeline.generate_and_execute", return_value=(mock_gen_result, mock_qa_pairs, mock_gen_usage)), \
             patch("querybloom.llm.pipeline.introduce_complexity", return_value=(mock_ci_result, mock_ci_usage)), \
             patch("querybloom.llm.pipeline.reword_questions", return_value=(mock_rw_result, mock_rw_usage)), \
             patch("querybloom.llm.pipeline.load_prompt_template", return_value=MagicMock()):

            subgraph = {"subgraph_index": 0, "types": {}}
            events = []
            result = process_single_subgraph_pipeline(
                subgraph=subgraph,
                subgraph_index=0,
                endpoint="http://example.org/sparql",
                model="gpt-4o-mini",
                template=None,
                timeout=10,
                introduce_complexity_step=True,
                reword_questions_step=True,
                event_sink=events.append,
            )

            self.assertIn("cost_usd", result)
            self.assertIn("llm_usage", result)
            expected_cost = round(0.0015 + 0.0008 + 0.0005, 6)
            self.assertEqual(result["cost_usd"], expected_cost)
            self.assertEqual(result["llm_usage"]["total_tokens"], 280)
            self.assertEqual(result["llm_usage"]["prompt_tokens"], 200)
            self.assertEqual(result["llm_usage"]["completion_tokens"], 80)

            # Check that subgraph.completed event was emitted with cost
            completed_events = [e for e in events if e.type == "subgraph.completed"]
            self.assertTrue(len(completed_events) > 0)
            self.assertEqual(completed_events[-1].data.get("cost_usd"), expected_cost)


if __name__ == "__main__":
    unittest.main()

