"""Run with python -m evaluation.run; no web requests or paid API baseline."""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from .metrics import COUNT_KEYS, evaluate_claims, summarize_counts

DATASET_PATH = Path(__file__).with_name("claims.json")


def load_dataset(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("cases"), list):
        raise ValueError("Expected a version 1 extraction dataset with a cases list")
    identifiers = set()
    for case in data["cases"]:
        if case["id"] in identifiers:
            raise ValueError(f"Duplicate case ID: {case['id']}")
        identifiers.add(case["id"])
        if case["split"] not in {"dev", "heldout"}:
            raise ValueError(f"Invalid split in {case['id']}")
        if case.get("review_status") not in {"draft", "human_reviewed"}:
            raise ValueError(f"Missing review status in {case['id']}")
        source = case["response_text"]
        spans = set()
        for claim in case["claims"]:
            start, end = claim["text_span"]["start"], claim["text_span"]["end"]
            if not (isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(source)):
                raise ValueError(f"Invalid span in {case['id']}")
            if source[start:end] != claim["exact_text"]:
                raise ValueError(f"Span does not match source in {case['id']}")
            if (start, end) in spans:
                raise ValueError(f"Duplicate gold span in {case['id']}")
            spans.add((start, end))
            if not isinstance(claim["objectively_checkable"], bool) or not isinstance(claim["claim_type"], str):
                raise ValueError(f"Invalid labels in {case['id']}")
    return data


def sentence_baseline(source: str) -> list[dict[str, Any]]:
    """Treat every nonempty sentence/line as one claim; no classification."""
    claims = []
    previous_end = 0
    for boundary in list(re.finditer(r"[.!?](?=\s|$)|\n", source)) + [None]:
        stop = boundary.start() if boundary else len(source)
        start = previous_end
        while start < stop and source[start].isspace():
            start += 1
        while stop > start and source[stop - 1].isspace():
            stop -= 1
        if start < stop:
            claims.append({
                "exact_text": source[start:stop],
                "text_span": {"start": start, "end": stop},
                "claim_type": None,
                "objectively_checkable": None,
                "verification_status": "UNVERIFIED",
            })
        if boundary:
            previous_end = boundary.end()
    return claims


def local_extractor(source: str) -> list[dict[str, Any]]:
    # Lazy imports keep fixture validation and metric tests independent of API dependencies.
    from backend.verification.schemas import ExtractionRequest
    from backend.verification.service import extract_response

    result = extract_response(ExtractionRequest(response_text=source, mode="quick"))
    if result.extraction_status == "failed":
        raise RuntimeError("Extraction service reported a validation or execution failure")
    return [claim.model_dump(mode="json") for claim in result.claims]


def evaluate_engine(cases: list[dict[str, Any]], engine: Callable[[str], list[dict[str, Any]]]) -> dict[str, Any]:
    per_case = []
    totals = {key: 0 for key in COUNT_KEYS}
    latencies = []
    failures = 0
    for case in cases:
        error = None
        start = perf_counter()
        try:
            predicted = engine(case["response_text"])
            for claim in predicted:
                span = claim["text_span"]
                if not (0 <= span["start"] < span["end"] <= len(case["response_text"])):
                    raise ValueError("Extractor returned an invalid source span")
                if case["response_text"][span["start"]:span["end"]] != claim["exact_text"]:
                    raise ValueError("Extractor returned text that differs from its source span")
        except Exception as exc:
            # A failed case contributes all gold claims as misses and remains visible.
            predicted = []
            error = f"{type(exc).__name__}: {exc}"
            failures += 1
        elapsed_ms = (perf_counter() - start) * 1000
        latencies.append(elapsed_ms)
        metrics = evaluate_claims(case["claims"], predicted)
        for key in COUNT_KEYS:
            totals[key] += metrics[key]
        per_case.append({"id": case["id"], "split": case["split"], "tags": case["tags"], "error": error, "latency_ms": round(elapsed_ms, 3), **metrics})
    return {
        "case_count": len(cases),
        "failed_case_count": failures,
        "estimated_cost_usd": 0.0,
        "cost_basis": "Local deterministic computation; no model or search API calls. Machine operation cost excluded.",
        "latency_ms": {
            "total": round(sum(latencies), 3),
            "mean": round(sum(latencies) / len(latencies), 3) if latencies else None,
            "max": round(max(latencies), 3) if latencies else None,
            "note": "Single local run including cold imports; not a production latency benchmark.",
        },
        "metrics": summarize_counts(totals),
        "cases": per_case,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--split", choices=("dev", "heldout", "all"), default="dev")
    parser.add_argument("--engine", choices=("extractor", "baseline", "both"), default="both")
    parser.add_argument("--output", type=Path, help="Write a JSON report; otherwise print it to stdout")
    args = parser.parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    splits = ("dev", "heldout") if args.split == "all" else (args.split,)
    engines = {"sentence_baseline": sentence_baseline, "local_extractor": local_extractor}
    if args.engine != "both":
        engines = {name: engine for name, engine in engines.items() if (name == "sentence_baseline") == (args.engine == "baseline")}
    report = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(args.dataset),
        "review_status": dataset.get("review_status", "draft"),
        "review_counts": dict(Counter(case["review_status"] for case in dataset["cases"])),
        "warning": "Draft annotations have not been independently human reviewed. This measures extraction, not factual verification or guaranteed coverage. Heldout fixtures are public local examples, not a sealed external test set.",
        "metric_definitions": {
            "exact_boundary": "Micro precision/recall with exact start, end, and original text; one prediction can match only one gold annotation.",
            "classification": "Category/checkability accuracy only among exactly matched claims with a predicted label; misses are reported separately.",
            "false_supported": "Count/rate of premature SUPPORTED labels in extraction-only output without independent evidence; not an estimate of verifier accuracy.",
            "empty_denominator": "null means unavailable; never substitute 100% for an empty denominator.",
        },
        "unavailable_measurements": {
            "verification_precision_and_recall": "Not run: evidence verification is not implemented in Level 1.",
            "citation_validity": "Not run: extraction recognizes text only and does not fetch citations.",
            "abstention_quality": "Not run: requires evidence-based gold verdicts; extraction-only UNVERIFIED is not measured as successful abstention.",
            "numerical_checking_accuracy": "Not run: calculation verification belongs to a later level.",
            "ordinary_llm_judge_baseline": "Not run: requires configured model credentials, explicit cost budget, and a separate verification dataset.",
            "original_trustlayer_baseline": "Not comparable for extraction: the existing sycophancy detector does not output atomic claim spans or factual verdicts. Its regressions are tested separately.",
        },
        "splits": {},
    }
    failures = 0
    for split in splits:
        cases = [case for case in dataset["cases"] if case["split"] == split]
        report["splits"][split] = {}
        for name, engine in engines.items():
            result = evaluate_engine(cases, engine)
            failures += result["failed_case_count"]
            report["splits"][split][name] = result
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Saved {args.output}; {failures} failed cases. Draft extraction metrics are not verification accuracy.")
    else:
        sys.stdout.write(rendered)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
