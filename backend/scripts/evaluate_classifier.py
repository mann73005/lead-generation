#!/usr/bin/env python
"""Measure reply-classification accuracy against the hand-labelled set.

    python scripts/evaluate_classifier.py            # uses the configured LLM
    python scripts/evaluate_classifier.py --keyword  # deterministic pass only

Reports overall accuracy and a per-label breakdown. On a set this small the
breakdown matters more than the headline number: eight examples cannot
establish an accuracy figure to any precision, but they do show when a whole
label is never predicted, which is the failure worth catching.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.classification import classify_by_keywords, classify_reply  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.policy import load_product_config  # noqa: E402

DATASET = Path(__file__).resolve().parents[1] / "data" / "labelled_replies.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keyword", action="store_true", help="Evaluate the deterministic classifier only."
    )
    parser.add_argument("--dataset", type=Path, default=DATASET)
    args = parser.parse_args()

    data = json.loads(args.dataset.read_text(encoding="utf-8"))
    examples = data["examples"]

    use_llm = not args.keyword and settings.llm_enabled
    if not use_llm and not args.keyword:
        print("GEMINI_API_KEY is not set - evaluating the keyword classifier instead.\n")

    llm = None
    product = None
    if use_llm:
        from app.providers import get_llm_provider

        llm = get_llm_provider()
        product = load_product_config().identity

    mode = "LLM" if use_llm else "keyword"
    print(f"Reply classification accuracy - {mode} classifier")
    print(f"Dataset: {args.dataset.name} ({len(examples)} examples)\n")

    correct = 0
    per_label: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [correct, total]
    confusions: list[tuple[str, str, str]] = []

    for example in examples:
        expected = example["label"]
        if use_llm:
            predicted = classify_reply(
                example["text"], product=product, sender_name="Sales", llm=llm
            ).intent
        else:
            predicted, _, _ = classify_by_keywords(example["text"])

        hit = predicted == expected
        correct += hit
        per_label[expected][1] += 1
        per_label[expected][0] += hit
        if not hit:
            confusions.append((example["text"], expected, predicted))

        status = "PASS" if hit else "FAIL"
        print(f"  {status}  #{example['id']}  expected={expected:<13} predicted={predicted}")

    total = len(examples)
    accuracy = correct / total if total else 0.0

    print(f"\nAccuracy: {correct}/{total} = {accuracy:.1%}\n")
    print("Per label:")
    for label in data["label_set"]:
        got, seen = per_label.get(label, [0, 0])
        if seen:
            print(f"  {label:<13} {got}/{seen}")
        else:
            print(f"  {label:<13} (not represented in the dataset)")

    if confusions:
        print("\nMisclassified:")
        for text, expected, predicted in confusions:
            print(f'  "{text[:68]}..."')
            print(f"      expected {expected}, got {predicted}")

    # Non-zero exit on a clearly broken classifier, so this is usable in CI.
    return 0 if accuracy >= 0.5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
