import json
import random

import pytest

from kg_benchmark_eval import (
    Benchmark,
    BenchmarkValidationError,
    balance_benchmarks,
)


def test_jsonl_preserves_pairs_lines_and_resolves_qald_profile(tmp_path):
    path = tmp_path / "qald9-test.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"question": "First?", "sparql": "ASK {}"}),
                "",
                json.dumps(
                    {"id": "given", "question": "Second?", "sparql": "SELECT * {}"}
                ),
            ]
        ),
        encoding="utf-8",
    )

    benchmark = Benchmark.from_jsonl(path, name="QALD", normalization="auto")

    assert benchmark.normalization == "qald9"
    assert benchmark.ordered_ids == ("source-1", "given")
    assert [record.source_line for record in benchmark.records] == [1, 3]
    assert benchmark.source_checksum is not None


@pytest.mark.parametrize(
    "record, message",
    [
        ({"sparql": "ASK {}"}, "missing field 'question'"),
        ({"question": "Question?"}, "missing field 'sparql'"),
        ({"question": None, "sparql": "ASK {}"}, "must be a nonempty string"),
    ],
)
def test_invalid_records_cannot_misalign_pairs(record, message):
    with pytest.raises(BenchmarkValidationError, match=message):
        Benchmark.from_records([record], name="invalid")


def test_duplicate_supplied_ids_are_rejected():
    records = [
        {"id": "same", "question": "One?", "sparql": "ASK {}"},
        {"id": "same", "question": "Two?", "sparql": "ASK {}"},
    ]
    with pytest.raises(BenchmarkValidationError, match="duplicate record ID"):
        Benchmark.from_records(records, name="duplicates")


def test_balance_samples_only_larger_input_without_global_rng_changes():
    large = Benchmark.from_records(
        [
            {"id": str(index), "question": f"Q{index}", "sparql": "ASK {}"}
            for index in range(5)
        ],
        name="large",
    )
    small = Benchmark.from_records(
        [{"id": "x", "question": "Q", "sparql": "ASK {}"}], name="small"
    )
    random.seed(123)
    expected_next = random.random()
    random.seed(123)

    sampled, unchanged = balance_benchmarks(large, small, seed=40)

    assert random.random() == expected_next
    assert unchanged is small
    assert sampled.ordered_ids == ("3",)
    assert sampled.sampling is not None
    assert sampled.sampling.selected_ids == sampled.ordered_ids
    assert large.size == 5


def test_in_memory_auto_normalization_is_rejected():
    with pytest.raises(BenchmarkValidationError, match="explicit normalization"):
        Benchmark.from_records([], name="empty", normalization="auto")
