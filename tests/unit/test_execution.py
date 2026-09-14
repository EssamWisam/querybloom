from unittest.mock import patch

import pytest

from querybloom.llm.execution import execute_sparql_and_get_result


@pytest.mark.parametrize("answer", [True, False])
def test_execute_sparql_preserves_ask_answer(answer):
    with patch("querybloom.llm.execution.execute") as execute:
        execute.return_value = {
            "success": True,
            "results": answer,
            "count": 1,
            "error": None,
        }

        result = execute_sparql_and_get_result(
            "ASK { ?subject ?predicate ?object }",
            "https://example.test/sparql",
        )

    assert result == {
        "success": True,
        "count": 1,
        "error_message": "",
        "result_preview": None,
        "boolean": answer,
    }