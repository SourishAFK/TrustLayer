"""Strict, one-to-one span matching without paid providers or NLP dependencies."""

from collections import defaultdict, deque
from typing import Any


def _key(claim: dict[str, Any]) -> tuple[int, int, str]:
    span = claim["text_span"]
    return span["start"], span["end"], claim["exact_text"]


def ratio(numerator: int, denominator: int) -> float | None:
    """An empty denominator is unavailable, not perfect performance."""
    return numerator / denominator if denominator else None


def summarize_counts(counts: dict[str, int]) -> dict[str, Any]:
    precision = ratio(counts["matched"], counts["predicted"])
    recall = ratio(counts["matched"], counts["gold"])
    f1 = None
    if precision is not None and recall is not None:
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        **counts,
        "exact_boundary_precision": precision,
        "exact_boundary_recall": recall,
        "exact_boundary_f1": f1,
        "matched_category_accuracy": ratio(counts["category_correct"], counts["category_evaluated"]),
        "matched_checkability_accuracy": ratio(counts["checkability_correct"], counts["checkability_evaluated"]),
        "false_supported_rate": ratio(counts["false_supported_count"], counts["predicted"]),
    }


COUNT_KEYS = (
    "gold", "predicted", "matched", "category_correct", "category_evaluated",
    "checkability_correct", "checkability_evaluated", "false_supported_count",
)


def evaluate_claims(gold: list[dict[str, Any]], predicted: list[dict[str, Any]]) -> dict[str, Any]:
    """Match boundaries AND exact text; repeated predictions never reuse gold."""
    available: dict[tuple[int, int, str], deque[int]] = defaultdict(deque)
    for index, claim in enumerate(gold):
        available[_key(claim)].append(index)
    counts = {key: 0 for key in COUNT_KEYS}
    counts.update(gold=len(gold), predicted=len(predicted))
    matched_indices = set()
    extras = []
    label_errors = []
    for prediction in predicted:
        # At extraction-only Level 1 there is no independent evidence for SUPPORT.
        # This measures premature approval, not factual verification accuracy.
        if prediction.get("verification_status") == "SUPPORTED":
            counts["false_supported_count"] += 1
        candidates = available[_key(prediction)]
        if not candidates:
            extras.append(prediction)
            continue
        index = candidates.popleft()
        matched_indices.add(index)
        counts["matched"] += 1
        annotation = gold[index]
        errors = {}
        for field, prefix in (("claim_type", "category"), ("objectively_checkable", "checkability")):
            if prediction.get(field) is None:
                continue
            counts[f"{prefix}_evaluated"] += 1
            if prediction[field] == annotation[field]:
                counts[f"{prefix}_correct"] += 1
            else:
                errors[field] = {"expected": annotation[field], "actual": prediction[field]}
        if errors:
            label_errors.append({"exact_text": annotation["exact_text"], "text_span": annotation["text_span"], **errors})
    return {
        **summarize_counts(counts),
        "misses": [claim for index, claim in enumerate(gold) if index not in matched_indices],
        "extras": extras,
        "label_errors": label_errors,
    }
