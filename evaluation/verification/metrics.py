"""Verification metrics. An empty denominator is None (unavailable), never 100%."""

from collections import Counter, defaultdict
from typing import Any

VERDICTS = ("SUPPORTED", "CONTRADICTED", "DISPUTED", "UNVERIFIED", "NOT CHECKABLE")


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def match_claims(response_text: str, gold_claims: list[dict], predicted: list[dict]) -> list[dict]:
    """Pair each gold claim with the predicted claim overlapping >= 50% of its span (or None)."""
    rows = []
    for gold in gold_claims:
        start = response_text.find(gold["claim_text"])
        end = start + len(gold["claim_text"])
        best, best_overlap = None, 0
        for claim in predicted:
            span = claim["text_span"]
            overlap = max(0, min(end, span["end"]) - max(start, span["start"]))
            if overlap > best_overlap:
                best, best_overlap = claim, overlap
        matched = best if best and best_overlap >= 0.5 * (end - start) else None
        rows.append({"claim_text": gold["claim_text"], "gold": gold["verdict"],
                     "predicted": matched["verification_status"] if matched else None,
                     "claim_id": matched["claim_id"] if matched else None,
                     "evidence_backed": evidence_backed(matched, None) if matched else None})
    return rows


def evidence_backed(claim: dict | None, sources: dict[str, str] | None) -> bool | None:
    """SUPPORTED must rest on quotes found in the corpus, or on a passing pure calculation."""
    if not claim or claim["verification_status"] != "SUPPORTED":
        return None
    if not claim["evidence"]:
        return any(c["consistent"] and c["pure_math"] for c in claim["calculations"])
    if sources is None:
        return True  # checked again in evaluate_case, where the corpus is known
    return all(e["url"] in sources and e["quote"] in sources[e["url"]] for e in claim["evidence"])


def evaluate_case(case: dict, report: dict) -> dict:
    """Claim rows, citation and signal results for one case and one system's report."""
    sources = {e["url"]: e.get("text", "") for e in case.get("corpus", [])}
    for index, document in enumerate(case["request"].get("documents", []), start=1):
        sources[f"document://{index}"] = document["text"]
    rows = match_claims(case["request"]["response_text"], case["gold"].get("claims", []), report["claims"])
    by_id = {c["claim_id"]: c for c in report["claims"]}
    for row in rows:
        row["evidence_backed"] = evidence_backed(by_id.get(row["claim_id"]), sources)
    statuses = {c.get("url") or c.get("doi"): c["status"] for c in report.get("citations", [])}
    for c in report.get("citations", []):
        if c.get("doi"):
            statuses.setdefault(f"https://doi.org/{c['doi']}", c["status"])
    citations = [{"url": g["url"], "gold": g["status"], "predicted": statuses.get(g["url"])}
                 for g in case["gold"].get("citations", [])]
    present = {s["kind"] for s in report.get("signals", [])}
    signals = [{"kind": kind, "found": kind in present} for kind in case["gold"].get("signal_kinds", [])]
    return {"rows": rows, "citations": citations, "signals": signals}


def summarize(results: list[dict]) -> dict[str, Any]:
    """Aggregate evaluate_case outputs (each carrying case id/tags/latency/cost)."""
    rows = [dict(r, case=res["id"]) for res in results for r in res["rows"]]
    matched = [r for r in rows if r["predicted"] is not None]
    confusion: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        confusion[r["gold"]][r["predicted"] or "MISSED"] += 1
    pred_supported = [r for r in matched if r["predicted"] == "SUPPORTED"]
    gold_supported = [r for r in matched if r["gold"] == "SUPPORTED"]
    gold_non_supported = [r for r in matched if r["gold"] != "SUPPORTED"]
    false_supported = [r for r in pred_supported if r["gold"] != "SUPPORTED"]
    gold_contradicted = [r for r in matched if r["gold"] == "CONTRADICTED"]
    pred_contradicted = [r for r in matched if r["predicted"] == "CONTRADICTED"]
    gold_unverified = [r for r in matched if r["gold"] == "UNVERIFIED"]
    gold_not_checkable = [r for r in matched if r["gold"] == "NOT CHECKABLE"]
    backed = [r for r in pred_supported if r["evidence_backed"] is not None]
    citations = [c for res in results for c in res["citations"]]
    signals = [s for res in results for s in res["signals"]]
    latencies = [res["latency_ms"] for res in results]
    return {
        "gold_claims": len(rows), "matched_claims": len(matched),
        "extraction_misses": [{"case": r["case"], "claim_text": r["claim_text"]} for r in rows if r["predicted"] is None],
        "verdict_accuracy": ratio(sum(r["gold"] == r["predicted"] for r in matched), len(matched)),
        "confusion": {gold: dict(counts) for gold, counts in sorted(confusion.items())},
        "supported_precision": ratio(len(pred_supported) - len(false_supported), len(pred_supported)),
        "supported_recall": ratio(sum(r["predicted"] == "SUPPORTED" for r in gold_supported), len(gold_supported)),
        "false_supported_count": len(false_supported),
        "false_supported_rate": ratio(len(false_supported), len(pred_supported)),
        "false_supported_share_of_non_supported_gold": ratio(len(false_supported), len(gold_non_supported)),
        "false_approvals": [{"case": r["case"], "claim_text": r["claim_text"], "gold": r["gold"]}
                            for r in false_supported],
        "wrong_claim_detection_rate": ratio(sum(r["predicted"] in ("CONTRADICTED", "DISPUTED")
                                                for r in gold_contradicted), len(gold_contradicted)),
        "contradicted_precision": ratio(sum(r["gold"] == "CONTRADICTED" for r in pred_contradicted),
                                        len(pred_contradicted)),
        "abstention_rate_on_unverified_gold": ratio(sum(r["predicted"] == "UNVERIFIED" for r in gold_unverified),
                                                    len(gold_unverified)),
        "not_checkable_accuracy": ratio(sum(r["predicted"] == "NOT CHECKABLE" for r in gold_not_checkable),
                                        len(gold_not_checkable)),
        "evidence_integrity_rate": ratio(sum(bool(r["evidence_backed"]) for r in backed), len(backed)),
        "citation_status_accuracy": ratio(sum(c["gold"] == c["predicted"] for c in citations), len(citations)),
        "citation_errors": [c for c in citations if c["gold"] != c["predicted"]],
        "signal_recall": ratio(sum(s["found"] for s in signals), len(signals)),
        "signals_missed": [s["kind"] for s in signals if not s["found"]],
        "latency_ms": {"mean": round(sum(latencies) / len(latencies), 1) if latencies else None,
                       "max": round(max(latencies), 1) if latencies else None},
        "estimated_cost_usd": round(sum(res.get("cost_usd", 0.0) for res in results), 6),
        "failed_cases": [res["id"] for res in results if res.get("error")],
    }
