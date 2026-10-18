"""Engine E (logic): contradictions inside one response, without false alarms. Offline."""

from datetime import datetime, timezone

import pytest

from backend.verification.budget import Budget, limits_for
from backend.verification.consistency import ConsistencyEngine
from backend.verification.contracts import Findings, LLMResult, RunContext
from backend.verification.report import VerificationRequest
from backend.verification.service import extract_claims

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


class Reviewer:
    name, family, model = "fake", "fake", "fake-reviewer"

    def __init__(self, data):
        self.data, self.calls = data, 0

    def complete_json(self, *, system, prompt, schema, max_output_tokens, timeout):
        self.calls += 1
        assert schema["title"] == "consistency_review" and "<claims>" in prompt
        return LLMResult(self.data, self.model, 10, 10)


def run(text, mode="quick", llm=None):
    claims = extract_claims(text).claims
    ctx = RunContext(request=VerificationRequest(response_text=text, mode=mode), claims=claims,
                     budget=Budget(limits_for(mode)), now=NOW, llm=llm)
    findings = Findings([c.claim_id for c in claims])
    engine_run = ConsistencyEngine().run(ctx, findings)
    return claims, findings, engine_run


@pytest.mark.parametrize("text,severity", [
    ("Acme's revenue was $10 million in 2025. Later analysis: Acme generated $12 million in revenue in 2025.",
     "critical"),
    ("Acme was founded in 2015. Acme was established in 2017.", "critical"),
    ("Acme is profitable. Acme is not profitable.", "critical"),
    ("Acme isn't profitable. Acme is profitable.", "critical"),
    ("OpenAI generates $50 billion annually. OpenAI makes $3 billion a year.", "critical"),
    ("Exactly 12 people attended the meeting. Exactly 15 people attended that same meeting.", "warning"),
])
def test_contradictions_are_flagged(text, severity):
    claims, findings, _ = run(text)
    assert [(s.kind, s.severity, s.claim_ids) for s in findings.signals] == [
        ("internal_contradiction", severity, ["c1", "c2"])]
    later = claims[1]
    assert (findings.signals[0].text_span.start, findings.signals[0].text_span.end) == (
        later.text_span.start, later.text_span.end)
    assert findings.claims["c1"].limitations[0].startswith("Conflicts with c2")


@pytest.mark.parametrize("text", [
    "Acme's revenue was $10 million in 2024. Acme's revenue was $12 million in 2025.",
    "Acme's revenue was $10 million in 2025. Beta's revenue was $12 million in 2025.",
    "Acme's revenue was $10 million in 2025. Acme's revenue was $10.05 million in 2025.",
    "Our team has 10 people. The client team has 20 people.",
    "Acme has 40 staff in India. Acme has 100 staff worldwide.",
    "Acme and Beta both sell robots. Acme has 40 employees. Beta has 90 employees.",
    "Acme was founded in 2015. Acme raised $5 million in 2016.",
])
def test_compatible_statements_are_not_flagged(text):
    assert run(text)[1].signals == []


def test_elliptical_clauses_inherit_their_subject():
    _, findings, _ = run("OpenAI was founded in 2015, has no competitors, and generates $50 billion annually. "
                         "OpenAI makes $3 billion a year.")
    assert findings.signals[0].claim_ids == ["c3", "c4"]


def test_quick_mode_never_calls_a_model():
    reviewer = Reviewer({"contradictions": [], "non_sequiturs": []})
    run("Acme is in Paris. Acme sells robots.", llm=reviewer)
    assert reviewer.calls == 0


def test_deep_mode_model_findings_are_validated_and_softer():
    text = ("Acme is a three-year-old startup. Acme has operated since 1990. "
            "If Acme grows, therefore every competitor will fail.")
    reviewer = Reviewer({
        "contradictions": [{"a": "c1", "b": "c2", "explanation": "A 3-year-old firm cannot date from 1990."},
                           {"a": "c1", "b": "c99", "explanation": "unknown id"},
                           {"a": "c2", "b": "c2", "explanation": "self pair"}],
        "non_sequiturs": [{"claim_id": "c3", "explanation": "Growth does not imply every rival fails."},
                          {"claim_id": "c1", "explanation": "not a logical claim"}]})
    claims, findings, engine_run = run(text, mode="deep", llm=reviewer)
    assert claims[2].claim_type == "logical"
    kinds = [(s.kind, s.severity, s.claim_ids) for s in findings.signals]
    assert kinds == [("internal_contradiction", "warning", ["c1", "c2"]), ("non_sequitur", "warning", ["c3"])]
    assert findings.signals[0].explanation.startswith("Possible contradiction (model-flagged)")
    assert "3 invalid item(s) discarded" in engine_run.detail


def test_deep_mode_without_a_model_says_so():
    _, _, engine_run = run("Acme is in Paris. Acme sells robots.", mode="deep")
    assert "No AI reviewer" in engine_run.detail


def test_single_claim_is_not_applicable():
    assert run("Acme sells robots.")[2].status == "not_applicable"


@pytest.mark.parametrize("text", [
    "Acme's ARR is $5M. Beta's ARR is $9M.",
    "In January, Acme had 500 users. In January, Beta had 900 users.",
    "Acme's SaaS revenue was $10M in 2023. Beta's SaaS revenue was $12M in 2023.",
    "In Q3, Acme's revenue was $10M. In Q3, Beta's revenue was $12M.",
    "Acme's US revenue was $10M. Beta's US revenue was $12M.",
    "The AI startup Acme has 50 employees. The AI startup Beta has 80 employees.",
    "Acme was founded in 2010. Acme's rival Beta was founded in 2015.",
    "Stripe raised $600M in 2021. Stripe's rival Adyen raised $250M in 2021.",
    "In Q3 2024, Acme's revenue was $10M. In Q4 2024, Acme's revenue was $12M.",
    "Acme's US revenue was $10M. Acme's EU revenue was $12M.",
    "In February, Acme had 500 users. In March, Acme had 900 users.",
])
def test_different_companies_periods_or_regions_never_conflict(text):
    # Shared tokens that are not subjects (ARR, SaaS, AI, Q3, months, regions, "Acme's rival")
    # used to make different companies look like one and raise critical false alarms.
    _, findings, _ = run(text)
    assert findings.signals == []


@pytest.mark.parametrize("text", [
    "In January, Acme had 500 users. In January, Acme had 900 users.",
    "In Q3, Acme's revenue was $10M. In Q3, Acme's revenue was $12M.",
    "In Feb 2024, Acme had 500 users. In February 2024, Acme had 900 users.",
])
def test_same_company_same_period_still_conflicts(text):
    _, findings, _ = run(text)
    assert [(s.kind, s.severity) for s in findings.signals] == [("internal_contradiction", "critical")]
