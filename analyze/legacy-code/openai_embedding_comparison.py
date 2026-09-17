"""Compare balanced DBLP question sets using OpenAI text embeddings."""

import argparse
import hashlib
import json
import os
import random
from pathlib import Path

import numpy as np
import yaml


ROOT = Path(__file__).resolve().parent
QUERYBLOOM_PATH = ROOT / "new_data" / "dblp-full.yaml"
BASELINE_PATH = ROOT / "new_data" / "dblp-test.jsonl"


def load_openai_key():
    """Load OPENAI_API_KEY from the local .env file when the shell lacks it."""
    if os.environ.get("OPENAI_API_KEY"):
        return

    dotenv_path = ROOT / ".env"
    if not dotenv_path.exists():
        return

    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip().removeprefix("export ").strip() == "OPENAI_API_KEY":
            os.environ["OPENAI_API_KEY"] = value.strip().strip("\"'")
            return


def load_questions():
    with QUERYBLOOM_PATH.open(encoding="utf-8") as file:
        querybloom_records = yaml.safe_load(file)
    with BASELINE_PATH.open(encoding="utf-8") as file:
        baseline_records = [json.loads(line) for line in file if line.strip()]

    querybloom_questions = [record["text"] for record in querybloom_records]
    baseline_questions = [record["question"] for record in baseline_records]
    return querybloom_questions, baseline_questions


def cache_path(cache_dir, model, questions):
    digest = hashlib.sha256(
        json.dumps({"model": model, "questions": questions}, ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    return cache_dir / f"{digest}.npy"


def get_embeddings(client, questions, model, cache_dir):
    path = cache_path(cache_dir, model, questions)
    if path.exists():
        return np.load(path)

    vectors = []
    for start in range(0, len(questions), 100):
        response = client.embeddings.create(model=model, input=questions[start : start + 100])
        vectors.extend(item.embedding for item in response.data)

    embeddings = np.asarray(vectors, dtype=np.float64)
    np.save(path, embeddings)
    return embeddings


def diversity_metrics(embeddings):
    normalized = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
    similarities = normalized @ normalized.T
    upper_triangle = np.triu_indices(len(normalized), k=1)
    apd = float(np.mean(1 - similarities[upper_triangle]))
    eigenvalues = np.linalg.eigvalsh(similarities / len(normalized))
    eigenvalues = eigenvalues[eigenvalues > 1e-12]
    vendi = float(np.exp(-np.sum(eigenvalues * np.log(eigenvalues))))
    return {"apd": round(apd, 4), "vendi": round(vendi, 4)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="text-embedding-3-large")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "figures" / "openai_semantic_diversity.json"
    )
    args = parser.parse_args()

    querybloom_questions, all_baseline_questions = load_questions()
    baseline_questions = random.Random(args.seed).sample(
        all_baseline_questions, len(querybloom_questions)
    )

    print(f"QueryBloom: {len(querybloom_questions)} text questions")
    print(f"Baseline: {len(baseline_questions)} question values (seed={args.seed})")
    if args.dry_run:
        return

    load_openai_key()
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("Install the client with: python3 -m pip install openai") from error

    cache_dir = ROOT / "cache" / "openai_embeddings"
    cache_dir.mkdir(parents=True, exist_ok=True)
    client = OpenAI()
    querybloom_embeddings = get_embeddings(
        client, querybloom_questions, args.model, cache_dir
    )
    baseline_embeddings = get_embeddings(client, baseline_questions, args.model, cache_dir)

    result = {
        "model": args.model,
        "seed": args.seed,
        "sample_size": len(querybloom_questions),
        "question_fields": {"QueryBloom": "text", "Baseline": "question"},
        "QueryBloom": diversity_metrics(querybloom_embeddings),
        "Baseline": diversity_metrics(baseline_embeddings),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"Saved metrics to {args.output}")


if __name__ == "__main__":
    main()