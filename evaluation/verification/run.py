"""Run with python -m evaluation.verification.run; offline, deterministic and free by default."""

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from backend.verification.contracts import Providers
from backend.verification.pipeline import verify
from backend.verification.report import VerificationRequest
from backend.verification.service import extract_claims

from .fixtures import (
    FIXED_NOW,
    FixtureFetcher,
    FixtureSearch,
    NoisyJudge,
    OracleJudge,
    load_cases,
    tokens,
)
from .metrics import VERDICTS, evaluate_case, summarize

HERE = Path(__file__).parent
SPLITS = {"dev": HERE / "cases_dev.json", "heldout": HERE / "cases_heldout.json"}
CITATION_STATUSES = {"supports", "does_not_support", "contradicts", "accessible_unassessed", "inaccessible",
                     "broken", "invalid_or_fabricated", "blocked", "not_checked"}


def validate(data: dict, split: str) -> None:
    """Fail loudly on malformed fixtures instead of silently mis-scoring them."""
    ids = set()
    for case in data["cases"]:
        cid = case["id"]
        if cid in ids:
            raise ValueError(f"duplicate case id {cid}")
        ids.add(cid)
        text = case["request"]["response_text"]
        if case.get("split") != split:
            raise ValueError(f"{cid}: split is not {split}")
        for gold in case["gold"].get("claims", []):
            if gold["claim_text"] not in text:
                raise ValueError(f"{cid}: gold claim_text not in response_text: {gold['claim_text']!r}")
            if gold["verdict"] not in VERDICTS:
                raise ValueError(f"{cid}: unknown verdict {gold['verdict']!r}")
        for gold in case["gold"].get("citations", []):
            if gold["url"] not in text or gold["status"] not in CITATION_STATUSES:
                raise ValueError(f"{cid}: bad gold citation {gold}")
        for entry in case.get("corpus", []):
            for judgment in entry.get("judgments", []):
                if judgment["quote"] not in entry.get("text", ""):
                    raise ValueError(f"{cid}: judgment quote not in {entry['url']}")
                if judgment["stance"] not in ("supports", "contradicts"):
                    raise ValueError(f"{cid}: bad stance in {entry['url']}")


def pipeline_system(judge_cls, engines=None):
    def run(case: dict) -> dict:
        corpus = case.get("corpus", [])
        providers = Providers(llm=judge_cls(corpus),
                              search=[FixtureSearch(corpus), FixtureSearch(corpus, "fixture-academic", "academic")],
                              fetcher=FixtureFetcher(corpus))
        report = verify(VerificationRequest(**case["request"]), providers=providers, engines=engines,
                        now=FIXED_NOW)
        return report.model_dump(mode="json")
    return run


def _baseline(case: dict, decide) -> dict:
    claims = []
    for claim in extract_claims(case["request"]["response_text"]).claims:
        status = decide(claim) if claim.objectively_checkable else "NOT CHECKABLE"
        claims.append({"claim_id": claim.claim_id, "text_span": claim.text_span.model_dump(),
                       "verification_status": status, "evidence": [], "calculations": []})
    return {"claims": claims, "citations": [], "signals": [], "usage": {"estimated_cost_usd": 0.0}}


def extraction_only(case: dict) -> dict:
    """Level 1 behavior: every checkable claim stays UNVERIFIED."""
    return _baseline(case, lambda claim: "UNVERIFIED")


def naive_overlap(case: dict) -> dict:
    """SUPPORTED when any corpus page shares >= 60% of the claim's words — why naive retrieval misleads."""
    pages = [tokens(e.get("text", "")) for e in case.get("corpus", [])]

    def decide(claim):
        words = tokens(claim.exact_text)
        return "SUPPORTED" if words and any(len(words & page) / len(words) >= 0.6 for page in pages) else "UNVERIFIED"
    return _baseline(case, decide)


def run_system(cases: list[dict], system) -> dict:
    results = []
    for case in cases:
        started = time.perf_counter()
        error = None
        try:
            report = system(case)
        except Exception as exc:  # noqa: BLE001 — a crash is a visible failed case, never a silent pass
            error = f"{type(exc).__name__}: {exc}"
            report = {"claims": [], "citations": [], "signals": [], "usage": {"estimated_cost_usd": 0.0}}
        result = evaluate_case(case, report)
        result.update(id=case["id"], tags=case.get("tags", []), error=error,
                      latency_ms=(time.perf_counter() - started) * 1000,
                      cost_usd=report.get("usage", {}).get("estimated_cost_usd", 0.0))
        results.append(result)
    by_tag = defaultdict(list)
    for result in results:
        for tag in result["tags"]:
            by_tag[tag].append(result)
    return {
        "metrics": summarize(results),
        "per_tag": {tag: {k: v for k, v in summarize(items).items()
                          if k in ("gold_claims", "verdict_accuracy", "false_supported_count",
                                   "wrong_claim_detection_rate", "citation_status_accuracy", "signal_recall")}
                    for tag, items in sorted(by_tag.items())},
        "cases": [{k: r[k] for k in ("id", "tags", "error", "rows", "citations", "signals")} for r in results],
    }


def _pct(value) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def markdown(report: dict) -> str:
    lines = ["| Split | System | Claims | Accuracy | False SUPPORTED | Wrong-claim detection | Abstention | "
             "Evidence integrity | Citations | Signals |", "|" + " --- |" * 10]
    for split, systems in report["splits"].items():
        if not isinstance(systems, dict) or "unavailable" in systems:
            lines.append(f"| {split} | unavailable | | | | | | | | |")
            continue
        for name, result in systems.items():
            m = result["metrics"]
            lines.append(f"| {split} | {name} | {m['matched_claims']}/{m['gold_claims']} | {_pct(m['verdict_accuracy'])} "
                         f"| {m['false_supported_count']} ({_pct(m['false_supported_rate'])}) "
                         f"| {_pct(m['wrong_claim_detection_rate'])} | {_pct(m['abstention_rate_on_unverified_gold'])} "
                         f"| {_pct(m['evidence_integrity_rate'])} | {_pct(m['citation_status_accuracy'])} "
                         f"| {_pct(m['signal_recall'])} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, engines=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "heldout", "all"), default="all")
    parser.add_argument("--judge", choices=("oracle", "noisy", "both"), default="both")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    systems = {}
    if args.judge in ("oracle", "both"):
        systems["pipeline+oracle"] = pipeline_system(OracleJudge, engines)
    if args.judge in ("noisy", "both"):
        systems["pipeline+noisy"] = pipeline_system(NoisyJudge, engines)
    systems["baseline:extraction_only"] = extraction_only
    systems["baseline:naive_overlap"] = naive_overlap
    report = {
        "schema_version": 1, "checked_at": datetime.now(timezone.utc).isoformat(), "fixed_now": FIXED_NOW.isoformat(),
        "warning": ("Synthetic frozen-web corpora with agent-authored draft labels (not yet human reviewed). "
                    "The oracle judge isolates retrieval, validation and the verdict policy from model "
                    "quality; it does not measure a live model's reading accuracy."),
        "unavailable_measurements": {
            "live_llm_judge_baseline": "Not run offline: needs provider credentials and an explicit cost cap.",
            "original_trustlayer_baseline": "Not comparable: the legacy detector scores sycophancy for a whole "
                                            "response and emits no per-claim factual verdicts.",
        },
        "splits": {},
    }
    failures = 0
    for split in (("dev", "heldout") if args.split == "all" else (args.split,)):
        path = SPLITS[split]
        if not path.exists():
            report["splits"][split] = {"unavailable": f"{path.name} not found"}
            continue
        data = load_cases(path)
        validate(data, split)
        report["splits"][split] = {}
        for name, system in systems.items():
            result = run_system(data["cases"], system)
            failures += len(result["metrics"]["failed_cases"])
            report["splits"][split][name] = result
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    print(markdown(report), file=sys.stderr if not args.output else sys.stdout)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
