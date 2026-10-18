"""Pipeline orchestration and budgets: failures stay visible and never become verdicts."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.verification.budget import Budget, Limits, limits_for, model_cost
from backend.verification.contracts import Providers
from backend.verification.pipeline import stream_ndjson, verify
from backend.verification.report import EngineRun, VerificationRequest

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
TEXT = "Acme was founded in 2015. Acme has 40 staff. I think Acme is brilliant."


def request(**kw):
    return VerificationRequest(response_text=TEXT, **kw)


class Engine:
    def __init__(self, name, action):
        self.name, self.action = name, action

    def run(self, ctx, findings):
        self.action(ctx, findings)
        return EngineRun(engine=self.name, status="completed", duration_ms=0, detail="ok")


def run(*engines, stage=1, **kw):
    stages = [[], [], []]
    stages[stage] = list(engines)
    return verify(request(**kw), providers=Providers(), engines=stages, now=NOW)


def test_no_engines_no_providers_is_an_honest_partial_report():
    report = run()
    assert report.status == "partial"
    assert report.summary.supported == report.summary.contradicted == 0
    assert report.summary.not_checkable == 1 and report.summary.unverified == 2
    assert any("No search provider" in item for item in report.incomplete_checks)
    assert report.privacy.note == "No text left this server for third-party processing."
    assert report.privacy.ai_providers == [] and report.privacy.search_providers == []


def test_crashing_engine_becomes_a_visible_failed_check():
    def boom(ctx, findings):
        raise RuntimeError("secret-key-123 and user text")
    report = run(Engine("evidence", boom))
    failed = [e for e in report.engines if e.engine == "evidence"]
    assert failed[0].status == "failed"
    assert "secret-key-123" not in report.model_dump_json()
    assert any("evidence check stopped unexpectedly" in i for i in report.incomplete_checks)


def test_invalid_evidence_is_discarded_and_counted():
    def bad(ctx, findings):
        c = ctx.claims[0]
        findings.add_evidence(claim_id=c.claim_id, stance="supports", url="https://a.com/x", domain="a.com",
                              source_type="other", retrieval="search", provider="t", accessed_at=NOW,
                              passage="Acme was founded in 2015.", quote="Acme was founded in 1999", method="t")
    report = run(Engine("evidence", bad))
    assert report.claims[0].evidence == [] and report.summary.supported == 0
    assert any("failed validation and were discarded" in item for item in report.limitations)


def test_valid_evidence_can_support_through_the_full_path():
    def good(ctx, findings):
        c = ctx.claims[0]
        for domain in ("a.com", "b.org"):
            findings.add_evidence(claim_id=c.claim_id, stance="supports", url=f"https://{domain}/x",
                                  domain=domain, source_type="other", retrieval="search", provider="t",
                                  accessed_at=NOW, passage="Acme was founded in 2015 in Berlin.",
                                  quote="Acme was founded in 2015", method="t")
        findings.note(c.claim_id, investigated=True)
    report = run(Engine("evidence", good))
    assert report.claims[0].verification_status == "SUPPORTED"
    assert report.summary.supported == 1 and report.summary.investigated == 1


def test_inconsistent_report_withholds_every_verdict():
    def corrupt(ctx, findings):
        findings.add_signal(engine="t", kind="absolute_language", severity="warning", text="x",
                            claim_ids=["c999"], explanation="refers to a claim that does not exist")
    report = run(Engine("uncertainty", corrupt), stage=0)
    assert report.status == "failed" and report.claims == []
    assert report.summary.total_extracted == 0
    assert "withheld" in report.incomplete_checks[0]


def test_budget_exhaustion_is_reported():
    def spend(ctx, findings):
        while ctx.budget.try_fetch():
            pass
    report = run(Engine("evidence", spend))
    assert "page_fetches" in report.usage.exhausted
    assert any("page-read limit" in item for item in report.incomplete_checks)


def test_consent_switches_are_reported():
    report = run(allow_web_search=False, allow_ai_processing=False)
    assert any("turned off" in item for item in report.incomplete_checks)


def test_stream_emits_progress_then_report():
    lines = [json.loads(line) for line in stream_ndjson(request(), providers=Providers(), engines=[[], [], []])]
    assert lines[0]["type"] == "progress" and lines[-1]["type"] == "report"
    assert lines[-1]["report"]["schema_version"] == "2.0"


def test_stream_error_event_hides_details(monkeypatch):
    from backend.verification import pipeline

    def broken(*_args, **_kwargs):
        raise RuntimeError("internal detail")
    monkeypatch.setattr(pipeline, "verify", broken)
    lines = [json.loads(line) for line in pipeline.stream_ndjson(request())]
    assert lines == [{"type": "error", "message": "Verification could not complete. No verdicts were produced."}]


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #

def test_limits_env_overrides_and_fail_closed(monkeypatch):
    monkeypatch.setenv("TRUSTLAYER_DEEP_MAX_SEARCH_CALLS", "12")
    assert limits_for("deep").max_search_calls == 12
    for bad in ("0", "-1", "abc", "100000"):
        monkeypatch.setenv("TRUSTLAYER_QUICK_MAX_SECONDS", bad)
        with pytest.raises(ValueError):
            limits_for("quick")


def small(**kw):
    base = dict(max_seconds=10, max_search_calls=2, max_page_fetches=1, max_model_calls=2,
                max_model_tokens=1000, max_cost_usd=0.01, max_claims_investigated=1,
                max_queries_per_claim=1, max_results_per_query=1, max_pages_per_claim=1)
    return Limits(**{**base, **kw})


def test_budget_counts_and_denials():
    budget = Budget(small())
    assert budget.try_search("wikipedia") and budget.try_search("wikipedia")
    assert not budget.try_search("wikipedia") and "search_calls" in budget.exhausted
    assert budget.try_fetch() and not budget.try_fetch()
    assert not budget.try_model("unknown-model", 900, 200) and "model_tokens" in budget.exhausted


def test_budget_cost_cap_and_actual_usage():
    budget = Budget(small(max_cost_usd=0.001, max_model_tokens=10**6))
    assert not budget.try_model("claude-opus-5-5", 1000, 1000)  # worst case $0.024 > $0.001
    assert "cost" in budget.exhausted
    budget2 = Budget(small(max_model_tokens=10**6))
    assert budget2.try_model("gemini-2.5-flash-lite", 1000, 500)
    budget2.record_model("gemini-2.5-flash-lite", 1000, 500)
    assert budget2.cost_usd == pytest.approx(model_cost("gemini-2.5-flash-lite", 1000, 500))
    budget2.record_model("mystery-model", 10, 10)
    assert "mystery-model" in budget2.cost_basis()


def test_budget_deadline_uses_the_clock():
    t = [0.0]
    budget = Budget(small(max_seconds=5), clock=lambda: t[0])
    assert budget.try_fetch()
    t[0] = 4.8
    assert not budget.try_search("wikipedia") and "time" in budget.exhausted
    assert budget.timeout(30) == pytest.approx(0.2)


def test_cancelled_budget_refuses_everything():
    import threading

    cancel = threading.Event()
    budget = Budget(small(), cancel=cancel)
    assert budget.try_fetch()
    cancel.set()
    assert not budget.try_search("wikipedia") and not budget.try_model("m", 1, 1)
    assert budget.remaining_seconds() == 0 and "cancelled" in budget.exhausted


def test_closing_the_stream_cancels_the_run(monkeypatch):
    import threading

    from backend.verification import pipeline

    seen = {}
    gate = threading.Event()

    def slow_verify(req, *, emit, cancel, **_kw):
        seen["cancel"] = cancel
        emit(pipeline.ProgressEvent(type="stage", stage="extraction", status="completed",
                                    message="x", elapsed_ms=0))
        gate.wait(5)
        raise RuntimeError("stopped")
    monkeypatch.setattr(pipeline, "verify", slow_verify)
    stream = pipeline.stream_ndjson(request())
    assert json.loads(next(stream))["type"] == "progress"
    stream.close()  # what Starlette does when the client disconnects
    assert seen["cancel"].is_set()
    gate.set()


@pytest.mark.parametrize("name,value", [
    ("TRUSTLAYER_CLAIM_MAX_CLAIMS", "0"), ("TRUSTLAYER_FRESHNESS_DAYS", "0"),
    ("TRUSTLAYER_REPORT_RETENTION_HOURS", "-5"), ("TRUSTLAYER_DEEP_MAX_COST_USD", "999"),
])
def test_config_is_checked_before_any_work(monkeypatch, name, value):
    from backend.verification.pipeline import check_config

    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        check_config("deep")


def test_report_dates_are_reproducible():
    report = run()
    assert report.created_at == NOW and report.completed_at >= NOW - timedelta(seconds=1)
