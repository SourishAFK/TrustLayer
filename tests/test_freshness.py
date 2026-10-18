"""Engine H (uncertainty + freshness): certainty language, predictions, caveats, staleness. Offline."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.verification.aggregator import decide
from backend.verification.budget import Budget, limits_for
from backend.verification.contracts import Findings, RunContext
from backend.verification.freshness import (
    PREDICTION_NOTE,
    FreshnessEngine,
    UncertaintyEngine,
)
from backend.verification.report import VerificationRequest
from backend.verification.service import extract_claims

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
CEO = "The current CEO of Acme is Jane Doe."


@pytest.fixture(autouse=True)
def default_freshness_window(monkeypatch):
    monkeypatch.delenv("TRUSTLAYER_FRESHNESS_DAYS", raising=False)  # 365 days


def make(text):
    claims = extract_claims(text).claims
    ctx = RunContext(request=VerificationRequest(response_text=text), claims=claims,
                     budget=Budget(limits_for("quick")), now=NOW)
    return ctx, Findings([c.claim_id for c in claims])


def uncertainty(text):
    ctx, findings = make(text)
    UncertaintyEngine().run(ctx, findings)
    return ctx, findings


def kinds(findings):
    return [(s.kind, s.text) for s in findings.signals]


def add(findings, claim, domain, age_days, source_type="news"):
    item = findings.add_evidence(
        claim_id=claim.claim_id, stance="supports", url=f"https://{domain}/acme", domain=domain,
        source_type=source_type, retrieval="search", provider="fixture",
        published_at=NOW - timedelta(days=age_days), accessed_at=NOW,
        passage=f"{claim.exact_text}, {domain} reported.", quote=claim.exact_text, method="test")
    assert item is not None


def fresh(text, *ages, source_type="news"):
    """Freshness of the first claim after adding one supporting source per age (days)."""
    ctx, findings = make(text)
    for n, age in enumerate(ages):
        add(findings, ctx.claims[0], f"source{n}.example", age, source_type)
    run = FreshnessEngine().run(ctx, findings)
    return ctx, findings, run, findings.claims[ctx.claims[0].claim_id].freshness


# --------------------------------------------------------------------------- #
# UncertaintyEngine
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("prefix", ["", "🚀🔥 "])
def test_absolute_phrases_have_exact_code_point_spans_and_flags(prefix):
    text = prefix + "Returns are guaranteed and the fund is risk-free. We have no competitors."
    ctx, findings = uncertainty(text)
    assert kinds(findings) == [("absolute_language", "guaranteed"), ("absolute_language", "risk-free"),
                               ("absolute_language", "no competitors")]
    assert findings.signals[0].text_span.start == len(prefix) + len("Returns are ")
    for signal in findings.signals:
        assert text[signal.text_span.start:signal.text_span.end] == signal.text
        assert (signal.engine, signal.severity) == ("uncertainty", "warning")
        [cid] = signal.claim_ids
        span = ctx.claim(cid).text_span
        assert span.start <= signal.text_span.start and signal.text_span.end <= span.end
    assert [findings.claims[c.claim_id].certainty_flags for c in ctx.claims] == [
        ["guaranteed"], ["risk-free"], ["no competitors"]]


@pytest.mark.parametrize("text,expected", [
    ("100% of revenue comes from Europe.", []),
    ("We are 100% sure revenue comes from Europe.", [("absolute_language", "100% sure")]),
    ("Returns are not guaranteed.", []),
    ("We charge no fees and offer guaranteed returns.", [("absolute_language", "guaranteed")]),
    ('Critics joke that the fund is "risk-free".', []),
])
def test_measured_shares_negation_and_quotes(text, expected):
    assert kinds(uncertainty(text)[1]) == expected


@pytest.mark.parametrize("text,claim_type,expected", [
    ("None of our competitors offer refunds.", "negative_universal", [("absolute_language", "None")]),
    ("None of the cells survived the treatment.", "scientific", []),
])
def test_weak_universals_count_only_in_universal_claims(text, claim_type, expected):
    ctx, findings = uncertainty(text)
    assert [c.claim_type.value for c in ctx.claims] == [claim_type]
    assert kinds(findings) == expected
    assert all(s.severity == "info" for s in findings.signals)


@pytest.mark.parametrize("text,expected", [
    ("The stock will definitely double next year.", [("overconfident_prediction", "will definitely")]),
    ("Prices will undoubtedly rise and will always stay high.",
     [("overconfident_prediction", "will undoubtedly"), ("overconfident_prediction", "always")]),
    ("Our revenue will probably double next year.", []),
])
def test_certain_predictions_are_overconfident_and_every_prediction_is_noted(text, expected):
    ctx, findings = uncertainty(text)
    assert {c.claim_type.value for c in ctx.claims} == {"predictive"}
    assert kinds(findings) == expected
    assert all(s.severity == "warning" and len(s.claim_ids) == 1 for s in findings.signals)
    for claim in ctx.claims:
        assert findings.claims[claim.claim_id].notes == [PREDICTION_NOTE]


def test_prediction_note_is_the_not_checkable_explanation():
    ctx, findings = uncertainty("Our revenue will double next year.")
    run = FreshnessEngine().run(ctx, findings)
    [claim] = ctx.claims
    verdict = decide(claim, findings.claims[claim.claim_id], NOW)
    assert verdict.verification_status == "NOT CHECKABLE"
    assert verdict.explanation == PREDICTION_NOTE
    assert run.status == "not_applicable" and verdict.freshness is None  # nothing checkable to date


@pytest.mark.parametrize("text,expected", [
    ("You should put your savings into Bitcoin now.", "You should"),
    ("You should put your savings into Bitcoin now, but this carries risk.", None),
    ("You should buy Bitcoin today. You should also put your savings into gold.", "You should"),
    ("You should water your plants every morning.", None),
])
def test_missing_caveat_needs_unhedged_high_stakes_advice(text, expected):
    _, findings = uncertainty(text)
    found = [s for s in findings.signals if s.kind == "missing_caveat"]
    assert [s.text for s in found] == ([expected] if expected else [])  # one per response
    for signal in found:
        assert text[signal.text_span.start:signal.text_span.end] == signal.text
        assert (signal.severity, signal.claim_ids) == ("warning", ["c1"])


# --------------------------------------------------------------------------- #
# FreshnessEngine
# --------------------------------------------------------------------------- #

def test_current_role_without_evidence_may_have_changed():
    _, findings, run, result = fresh(CEO)
    assert run.status == "completed"
    assert (result.time_sensitive, result.may_have_changed, result.newest_evidence_at) == (True, True, None)
    assert result.checked_at == NOW
    assert findings.claims["c1"].notes == [result.note]  # surfaces in the verdict explanation


def test_current_role_with_recent_evidence_is_current():
    _, findings, _, result = fresh(CEO, 30)
    assert (result.time_sensitive, result.may_have_changed) == (True, False)
    assert result.newest_evidence_at == NOW - timedelta(days=30)
    assert findings.claims["c1"].notes == []


def test_every_checkable_claim_is_assessed_and_history_is_not_time_sensitive():
    ctx, findings, _, _ = fresh(CEO + " Acme was founded in 2015. Prices will rise next year.")
    results = {cid: notes.freshness for cid, notes in findings.claims.items()}
    assert [c.objectively_checkable for c in ctx.claims] == [True, True, False]
    assert results["c3"] is None
    founded = results["c2"]
    assert (founded.time_sensitive, founded.may_have_changed, founded.claim_dates) == (False, False, ["2015"])


def test_old_as_of_date_is_a_dated_snapshot():
    # "As of 2019" pins the claim to 2019: judged on sources from then, flagged as possibly changed.
    _, findings, _, result = fresh("As of 2019, Acme had 200 employees.", 30)
    assert not result.time_sensitive and result.may_have_changed
    assert "2019" in result.claim_dates
    assert "as of 2019" in result.note and result.note in findings.claims["c1"].notes


def test_period_sources_can_support_an_as_of_claim():
    ctx, findings, _, result = fresh("As of 2019, Acme had 200 employees.", 2400, source_type="reference")
    verdict = decide(ctx.claims[0], findings.claims["c1"], NOW)
    assert verdict.verification_status == "SUPPORTED" and verdict.freshness.may_have_changed


def test_stale_evidence_cannot_support_a_time_sensitive_claim():
    ctx, findings, _, result = fresh(CEO, 800, 900, source_type="reference")
    assert result.may_have_changed
    verdict = decide(ctx.claims[0], findings.claims["c1"], NOW)
    assert verdict.verification_status == "UNVERIFIED" and verdict.evidence == []
    assert {r.url for r in verdict.related_sources} == {"https://source0.example/acme",
                                                        "https://source1.example/acme"}
    assert any("current evidence" in m for m in verdict.missing_evidence)


def test_old_evidence_still_supports_a_historical_claim():
    ctx, findings, _, result = fresh("Acme was founded in 2015.", 800, source_type="reference")
    assert not result.time_sensitive
    verdict = decide(ctx.claims[0], findings.claims["c1"], NOW)
    assert verdict.verification_status == "SUPPORTED" and verdict.related_sources == []


@pytest.mark.parametrize("text", [
    "As of 2019 and still today, Jane Doe is currently the CEO of Acme.",
    "Jane Doe, CEO as of 2019, is currently the CEO of Acme.",
])
def test_an_old_date_with_now_words_is_a_claim_about_now(text):
    # Old sources must not support "still/currently": the snapshot exemption needs a pure past date.
    ctx, findings, _, result = fresh(text, 2400, source_type="reference")
    assert result.time_sensitive and result.may_have_changed
    assert decide(ctx.claims[0], findings.claims["c1"], NOW).verification_status == "UNVERIFIED"
