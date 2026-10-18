"""The verification benchmark itself: fixtures, judges, metrics and the runner."""

import json
from pathlib import Path

import pytest

from evaluation.verification.fixtures import (
    FixtureFetcher,
    FixtureSearch,
    NoisyJudge,
    OracleJudge,
    load_cases,
    same_claim,
)
from evaluation.verification.metrics import evaluate_case, match_claims, summarize
from evaluation.verification.run import SPLITS, main, naive_overlap, validate

CORPUS = [
    {"url": "https://a.com/x", "title": "Acme", "provider": "brave", "published_at": "2026-01-01",
     "text": "Acme Robotics was founded in 2015 in Berlin.",
     "judgments": [{"claim_text": "Acme Robotics was founded in 2015", "stance": "supports",
                    "quote": "Acme Robotics was founded in 2015"}]},
    {"url": "https://doi.org/10.1/p", "provider": "openalex", "text": "A study of Acme Robotics warehouses."},
    {"url": "https://gone.com/x", "fetch_error": "http_error", "status": 404, "searchable": False},
]
PROMPT = ('CLAIM: Acme Robotics was founded in 2015\nCONTEXT: Acme Robotics was founded in 2015\nPASSAGES:\n'
          '<passage id="P1" source="a.com" title="Acme">\nAcme Robotics was founded in 2015 in Berlin.\n</passage>\n'
          '<passage id="P2" source="b.com" title="">\nUnrelated text.\n</passage>')
STANCE = {"title": "stance_judgments"}


def test_fixture_search_ranks_and_splits_by_kind():
    web = FixtureSearch(CORPUS).search("Acme Robotics founded", count=5, timeout=1)
    assert [r.url for r in web] == ["https://a.com/x"] and web[0].content is None
    academic = FixtureSearch(CORPUS, kind="academic").search("Acme warehouses", count=5, timeout=1)
    assert [r.url for r in academic] == ["https://doi.org/10.1/p"] and academic[0].content


def test_fixture_fetcher_errors():
    fetcher = FixtureFetcher(CORPUS)
    assert fetcher.fetch("https://a.com/x", timeout=1).ok
    assert (fetcher.fetch("https://gone.com/x", timeout=1).error, fetcher.fetch("https://gone.com/x", timeout=1).status) == (
        "http_error", 404)
    assert fetcher.fetch("https://never.com/", timeout=1).error == "dns_failure"


def test_oracle_answers_from_annotations_only():
    result = OracleJudge(CORPUS).complete_json(system="", prompt=PROMPT, schema=STANCE, max_output_tokens=1, timeout=1)
    stances = {j["passage_id"]: (j["stance"], j["quote"]) for j in result.data["judgments"]}
    assert stances == {"P1": ("supports", "Acme Robotics was founded in 2015"), "P2": ("irrelevant", "")}


def test_noisy_judge_supports_everything():
    result = NoisyJudge(CORPUS).complete_json(system="", prompt=PROMPT, schema=STANCE, max_output_tokens=1, timeout=1)
    assert {j["stance"] for j in result.data["judgments"]} == {"supports"}


def test_oracle_refuses_unknown_tasks():
    from backend.verification.contracts import LLMError
    with pytest.raises(LLMError):
        OracleJudge(CORPUS).complete_json(system="", prompt="", schema={"title": "mystery"}, max_output_tokens=1,
                                          timeout=1)


def test_claim_matching_tolerates_small_differences():
    assert same_claim("Acme was founded in 2015", "Acme was founded in 2015 [1]")
    assert not same_claim("Acme was founded in 2015", "Beta sells robots")


def claim(cid, start, end, status, evidence=(), calcs=()):
    return {"claim_id": cid, "text_span": {"start": start, "end": end}, "verification_status": status,
            "evidence": list(evidence), "calculations": list(calcs)}


def test_matching_requires_half_the_gold_span():
    text = "Acme was founded in 2015. Beta sells robots."
    gold = [{"claim_text": "Acme was founded in 2015", "verdict": "SUPPORTED"},
            {"claim_text": "Beta sells robots", "verdict": "UNVERIFIED"}]
    rows = match_claims(text, gold, [claim("c1", 0, 24, "SUPPORTED"), claim("c2", 26, 30, "UNVERIFIED")])
    assert [r["predicted"] for r in rows] == ["SUPPORTED", None]


def test_metrics_math_and_null_denominators():
    case = {"id": "x", "request": {"response_text": "Acme was founded in 2015. Beta sells robots."},
            "corpus": [{"url": "https://a.com/x", "text": "Acme was founded in 2015."}],
            "gold": {"claims": [{"claim_text": "Acme was founded in 2015", "verdict": "CONTRADICTED"},
                                {"claim_text": "Beta sells robots", "verdict": "UNVERIFIED"}],
                     "citations": [{"url": "https://a.com/x", "status": "broken"}], "signal_kinds": ["absolute_language"]}}
    evidence = {"url": "https://a.com/x", "quote": "Acme was founded in 2015"}
    report = {"claims": [claim("c1", 0, 24, "SUPPORTED", [evidence]), claim("c2", 26, 43, "UNVERIFIED")],
              "citations": [{"url": "https://a.com/x", "doi": None, "status": "broken"}], "signals": []}
    result = evaluate_case(case, report)
    result.update(id="x", tags=[], error=None, latency_ms=1.0, cost_usd=0.0)
    m = summarize([result])
    assert m["false_supported_count"] == 1 and m["false_supported_rate"] == 1.0
    assert m["wrong_claim_detection_rate"] == 0.0 and m["abstention_rate_on_unverified_gold"] == 1.0
    assert m["evidence_integrity_rate"] == 1.0 and m["citation_status_accuracy"] == 1.0
    assert m["signal_recall"] == 0.0 and m["supported_recall"] is None and m["not_checkable_accuracy"] is None


def test_naive_baseline_inflates_support():
    case = {"request": {"response_text": "Acme Robotics was founded in 2019."}, "corpus": CORPUS}
    assert naive_overlap(case)["claims"][0]["verification_status"] == "SUPPORTED"  # wrong year, still "supported"


def test_dataset_validation_catches_bad_fixtures():
    data = load_cases(SPLITS["dev"])
    validate(data, "dev")
    broken = json.loads(json.dumps(data))
    broken["cases"][0]["gold"]["claims"][0]["claim_text"] = "not in the response"
    with pytest.raises(ValueError):
        validate(broken, "dev")


def test_runner_smoke_without_engines(tmp_path: Path):
    output = tmp_path / "report.json"
    assert main(["--split", "dev", "--judge", "oracle", "--output", str(output)], engines=[[], [], []]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    dev = report["splits"]["dev"]
    assert set(dev) == {"pipeline+oracle", "baseline:extraction_only", "baseline:naive_overlap"}
    assert dev["pipeline+oracle"]["metrics"]["false_supported_count"] == 0
    assert "oracle judge isolates" in report["warning"]
