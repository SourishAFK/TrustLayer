"""Verdict policy: every path to each of the five statuses, offline."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from backend.verification.aggregator import decide
from backend.verification.contracts import ClaimNotes
from backend.verification.report import Calculation, Evidence, VerifiedClaim
from backend.verification.service import extract_claims

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


def claim(text):
    found = extract_claims(text).claims
    assert len(found) == 1, found
    return found[0]


def ev(c, domain, stance="supports", source_type="other", published_at=None, n=[0]):
    n[0] += 1
    passage = f"{c.exact_text} according to {domain}."
    return Evidence(evidence_id=f"e{n[0]}", claim_id=c.claim_id, stance=stance,
                    url=f"https://{domain}/page", domain=domain, source_type=source_type,
                    retrieval="search", provider="fixture", published_at=published_at,
                    accessed_at=NOW, passage=passage, quote=c.exact_text, method="test")


def notes(c, support=(), contra=(), **kw):
    n = ClaimNotes(evidence=list(support), contradictions=list(contra), **kw)
    n.investigated = bool(support or contra or n.calculations)
    return n


def calc(consistent=True, pure=True):
    return Calculation(kind="percentage_of", expression="20% × 150", stated_value="40",
                       computed_value="30", consistent=consistent, tolerance="±0.5", pure_math=pure,
                       note="")


def status(v: VerifiedClaim):
    return str(v.verification_status.value if hasattr(v.verification_status, "value") else v.verification_status)


def test_opinion_is_not_checkable_and_never_investigated():
    c = claim("I think this is a beautiful product.")
    v = decide(c, ClaimNotes(), NOW)
    assert status(v) == "NOT CHECKABLE" and not v.investigated and v.checked_at is None


def test_failed_pure_calculation_contradicts_with_correction():
    c = claim("20% of 150 is 40.")
    v = decide(c, ClaimNotes(calculations=[calc(False)], methods=["deterministic_calculation"],
                             corrections=["20% of 150 is 30"], investigated=True), NOW)
    assert status(v) == "CONTRADICTED" and v.suggested_correction == "20% of 150 is 30"
    assert "do not add up" in v.explanation


def test_passing_pure_calculation_supports_without_web_evidence():
    c = claim("20% of 150 is 30.")
    v = decide(c, ClaimNotes(calculations=[calc(True)], methods=["deterministic_calculation"],
                             investigated=True), NOW)
    assert status(v) == "SUPPORTED" and v.evidence == []


def test_consistent_math_on_unverified_inputs_stays_unverified():
    c = claim("Acme sales grew 50% from 20 units to 30 units in 2025.")
    v = decide(c, ClaimNotes(calculations=[calc(True, pure=False)], methods=["deterministic_calculation"],
                             investigated=True), NOW)
    assert status(v) == "UNVERIFIED"
    assert "not independently verified" in v.explanation


@pytest.mark.parametrize("sources,expected,strength", [
    ([("a.com", "other"), ("b.org", "other")], "SUPPORTED", "moderate"),
    ([("en.wikipedia.org", "reference")], "SUPPORTED", "moderate"),
    ([("en.wikipedia.org", "reference"), ("b.org", "news")], "SUPPORTED", "strong"),
    ([("blog.com", "other")], "UNVERIFIED", "weak"),
    ([("blog.com", "other"), ("blog.com", "other")], "UNVERIFIED", "weak"),
])
def test_support_threshold(sources, expected, strength):
    c = claim("Acme was founded in 2015.")
    support = [ev(c, d, source_type=t) for d, t in sources]
    v = decide(c, notes(c, support), NOW)
    assert (status(v), v.evidence_strength) == (expected, strength)
    if expected == "UNVERIFIED":
        assert v.missing_evidence


@pytest.mark.parametrize("text", [
    "Acme has no competitors.",
    "No vendor anywhere offers a substitute for Acme.",  # misclassified as factual by rules-v1
    "Acme is the only company that sells this.",
])
def test_universal_claims_are_never_supported_by_search(text):
    c = claim(text)
    support = [ev(c, "en.wikipedia.org", source_type="reference"), ev(c, "b.org")]
    v = decide(c, notes(c, support), NOW)
    assert status(v) == "UNVERIFIED"
    assert "universal or negative" in v.explanation


def test_universal_claim_can_be_contradicted_by_a_counterexample():
    c = claim("Acme has no competitors.")
    v = decide(c, notes(c, contra=[ev(c, "rival.io", "contradicts", "primary")],
                        corrections=[("Rival offers the same product (per rival.io)", "rival.io")]), NOW)
    assert status(v) == "CONTRADICTED" and v.suggested_correction


def test_weak_single_contradiction_does_not_contradict():
    c = claim("Acme was founded in 2015.")
    v = decide(c, notes(c, contra=[ev(c, "blog.com", "contradicts")]), NOW)
    assert status(v) == "UNVERIFIED" and v.contradictions and v.evidence_strength == "weak"


@pytest.mark.parametrize("support,contra,expected", [
    ([("a.com", "other"), ("b.com", "other")], [("c.gov", "official")], "DISPUTED"),
    ([("a.com", "other"), ("b.com", "other")], [("blog.com", "other")], "DISPUTED"),
    ([("blog.com", "other")], [("c.gov", "official")], "CONTRADICTED"),
    ([("blog.com", "other")], [("other.com", "other")], "UNVERIFIED"),
])
def test_conflicting_evidence(support, contra, expected):
    c = claim("Acme was founded in 2015.")
    v = decide(c, notes(c, [ev(c, d, source_type=t) for d, t in support],
                        [ev(c, d, "contradicts", t) for d, t in contra]), NOW)
    assert status(v) == expected


def test_time_sensitive_claims_need_current_evidence():
    c = claim("The current CEO of Acme is Jane Doe.")
    old = ev(c, "en.wikipedia.org", source_type="reference", published_at=NOW - timedelta(days=900))
    v = decide(c, notes(c, [old]), NOW)
    assert status(v) == "UNVERIFIED" and v.evidence == []
    assert v.related_sources and "older than" in v.related_sources[0].note
    fresh = ev(c, "en.wikipedia.org", source_type="reference", published_at=NOW - timedelta(days=30))
    assert status(decide(c, notes(c, [fresh]), NOW)) == "SUPPORTED"


def test_unresearched_claim_says_so():
    c = claim("Acme was founded in 2015.")
    v = decide(c, ClaimNotes(missing=["Not researched: budget"]), NOW)
    assert status(v) == "UNVERIFIED" and not v.investigated and v.evidence_strength == "none"
    assert "not researched" in v.explanation


def test_schema_refuses_supported_without_evidence():
    c = claim("Acme was founded in 2015.")
    v = decide(c, notes(c, [ev(c, "a.com"), ev(c, "b.com")]), NOW)
    data = v.model_dump()
    with pytest.raises(ValidationError):
        VerifiedClaim(**{**data, "evidence": []})
    with pytest.raises(ValidationError):
        VerifiedClaim(**{**data, "contradictions": [{**data["evidence"][0], "stance": "contradicts",
                                                      "evidence_id": "x9"}]})
    with pytest.raises(ValidationError):
        Evidence(**{**data["evidence"][0], "quote": "a fabricated quote"})


@pytest.mark.parametrize("text", [
    "Acme has zero competitors.", "Acme is the sole provider of satellite internet in Antarctica.",
    "Acme is unrivaled in its market.", "Not a single company competes with Acme.",
])
def test_more_universal_wordings_are_never_supported(text):
    c = claim(text)
    v = decide(c, notes(c, [ev(c, "acme.com", source_type="primary"), ev(c, "a.com"), ev(c, "b.org")]), NOW)
    assert status(v) == "UNVERIFIED" and "universal or negative" in v.explanation


def test_a_sellers_own_site_cannot_confirm_its_own_efficacy():
    c = claim("SleepWell Gummies cure insomnia in 7 days.")
    v = decide(c, notes(c, [ev(c, "sleepwellgummies.com", source_type="primary")]), NOW)
    assert status(v) == "UNVERIFIED" and any("own website" in m for m in v.missing_evidence)
    plain = claim("Acme was founded in 2015.")  # facts about itself: the own site still counts
    assert status(decide(plain, notes(plain, [ev(plain, "acme.com", source_type="primary")]), NOW)) == "SUPPORTED"


def test_a_failed_investigation_step_blocks_supported():
    from backend.verification.report import CheckRecord

    c = claim("Acme was founded in 2015.")
    broken = CheckRecord(engine="evidence", status="failed", detail="Research failed unexpectedly.")
    v = decide(c, notes(c, [ev(c, "a.com"), ev(c, "b.com")], checks=[broken]), NOW)
    assert status(v) == "UNVERIFIED" and "investigation failed" in v.explanation


def test_corrections_come_only_from_counted_sources():
    c = claim("Jane Doe is currently the CEO of Acme.")
    old = ev(c, "old-news.com", "contradicts", published_at=NOW - timedelta(days=900))
    current = [ev(c, d, "contradicts", published_at=NOW - timedelta(days=5)) for d in ("a.com", "b.com")]
    corrections = [("Mary Major is the CEO of Acme. (per old-news.com)", "old-news.com"),
                   ("John Smith is the CEO of Acme. (per a.com)", "a.com")]
    v = decide(c, notes(c, contra=[old, *current], corrections=corrections), NOW)
    assert status(v) == "CONTRADICTED" and v.suggested_correction.startswith("John Smith")


def test_superiority_needs_independent_sources_but_self_reported_counts_do_not():
    c = claim("Tallyhive is the obvious choice for independent restaurants.")
    assert status(decide(c, notes(c, [ev(c, "tallyhive.com", source_type="primary")]), NOW)) == "UNVERIFIED"
    c = claim("Greenvane has more than 140 farm customers.")
    assert status(decide(c, notes(c, [ev(c, "greenvane.com", source_type="primary")]), NOW)) == "SUPPORTED"


def test_superlatives_are_neither_self_confirmed_nor_confirmable_by_search():
    c = claim("Tailclaim is the largest vendor in AI pet-insurance claims automation.")
    assert status(decide(c, notes(c, [ev(c, "tailclaim.ai", source_type="primary")]), NOW)) == "UNVERIFIED"
    c = claim("Meridian's fund has the lowest fees of any index fund.")
    v = decide(c, notes(c, [ev(c, "meridianfunds.com", source_type="primary"), ev(c, "a.com"), ev(c, "b.org")]), NOW)
    assert status(v) == "UNVERIFIED" and "universal or negative" in v.explanation
