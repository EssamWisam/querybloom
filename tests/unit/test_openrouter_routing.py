import unittest

from querybloom.api.models import LLMRunRequest
from querybloom.llm.client import litellm_model_kwargs


class OpenRouterRoutingTests(unittest.TestCase):
    def test_direct_model_is_unchanged_without_a_provider(self):
        self.assertEqual(
            litellm_model_kwargs("openai/gpt-5.4"),
            {"model": "openai/gpt-5.4"},
        )

    def test_openrouter_model_prefix_is_kept(self):
        self.assertEqual(
            litellm_model_kwargs("openrouter/anthropic/claude-sonnet-4.5"),
            {"model": "openrouter/anthropic/claude-sonnet-4.5"},
        )

    def test_provider_prefixes_openrouter_and_disables_fallbacks(self):
        self.assertEqual(
            litellm_model_kwargs(
                "anthropic/claude-sonnet-4.5",
                openrouter_provider="anthropic",
            ),
            {
                "model": "openrouter/anthropic/claude-sonnet-4.5",
                "extra_body": {
                    "provider": {
                        "order": ["anthropic"],
                        "allow_fallbacks": False,
                    }
                },
            },
        )

    def test_provider_does_not_double_prefix_an_openrouter_model(self):
        kwargs = litellm_model_kwargs(
            "openrouter/google/gemini-2.5-pro",
            openrouter_provider="google-vertex",
        )
        self.assertEqual(kwargs["model"], "openrouter/google/gemini-2.5-pro")
        self.assertEqual(
            kwargs["extra_body"]["provider"],
            {"order": ["google-vertex"], "allow_fallbacks": False},
        )

    def test_blank_provider_is_ignored(self):
        self.assertEqual(
            litellm_model_kwargs("openai/gpt-5.4", openrouter_provider="  "),
            {"model": "openai/gpt-5.4"},
        )

    def test_request_normalizes_blank_provider(self):
        request = LLMRunRequest(
            endpoint="https://example.test/sparql",
            model="  openrouter/meta-llama/llama-3.3-70b-instruct  ",
            openrouter_provider="  ",
        )
        self.assertEqual(
            request.model,
            "openrouter/meta-llama/llama-3.3-70b-instruct",
        )
        self.assertIsNone(request.openrouter_provider)


if __name__ == "__main__":
    unittest.main()
