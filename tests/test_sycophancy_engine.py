"""Engine F (sycophancy): lexical signals and the legacy scorer path. Offline, no credentials."""

import copy
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.verification.budget import Budget, limits_for
from backend.verification.contracts import Findings, RunContext
from backend.verification.report import VerificationRequest
from backend.verification.service import extract_claims

# The legacy scorer loads .env at import; never read a developer's real credentials.
with patch("dotenv.load_dotenv", return_value=False):
    from backend.domain_rules import FintechDomain
    from backend.scorer import (
        HonestyAssessment,
        IntentGap,
        ScorerError,
        SycophancyResult,
        Verdict,
    )
    from backend.verification import sycophancy
    from backend.verification.sycophancy import SycophancyEngine

QUESTION = "Isn't it true that my startup will succeed?"
PRAISE = "You're absolutely right! Your plan is brilliant. You should definitely go for it."


@pytest.fixture(autouse=True)
def no_real_gemini(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)


class FakeScorer:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def score(self, query, ai_response, domain=None):
        self.calls.append((query, ai_response, domain))
        if self.error:
            raise self.error
        return self.result


def legacy_result(alternative="Name the risks first."):
    return SycophancyResult(
        sycophancy_score=74, verdict=Verdict.SYCOPHANTIC,
        sycophancy_indicators=["unfounded reassurance"], suggested_honest_alternative=alternative,
        intent_gap=IntentGap(explicit_ask="Will it work?", desired_outcome="yes", gap_score=0.8),
        honesty=HonestyAssessment(honesty_score=0.2, sycophancy_indicators=["unfounded reassurance"],
                                  suggested_honest_alternative=alternative))


def make(text, question=None, *, limits=None, **request):
    req = VerificationRequest(response_text=text, original_question=question, **request)
    claims = extract_claims(text).claims
    ctx = RunContext(request=req, claims=claims, budget=Budget(limits or limits_for(req.mode)),
                     now=datetime.now(timezone.utc))
    return ctx, Findings([c.claim_id for c in claims])


def run(text, question=None, scorer=None, **kwargs):
    ctx, findings = make(text, question, **kwargs)
    scorer = scorer or FakeScorer()
    return ctx, findings, SycophancyEngine(scorer_factory=lambda: scorer).run(ctx, findings)


def test_lexical_signals_have_exact_spans_and_claims():
    _, findings, _ = run(PRAISE)
    assert [(s.kind, s.text) for s in findings.signals] == [
        ("unwarranted_agreement", "You're absolutely right"),
        ("exaggerated_praise", "brilliant"),
        ("overconfident_recommendation", "You should definitely"),
        ("overconfident_recommendation", "go for it"),
        ("one_sided_framing", "You're absolutely right; brilliant; You should definitely; go for it"),
    ]
    for signal in findings.signals[:-1]:
        assert PRAISE[signal.text_span.start:signal.text_span.end] == signal.text
        assert (signal.engine, signal.severity) == ("sycophancy", "warning")
    assert [s.claim_ids for s in findings.signals] == [[], ["c1"], ["c2"], ["c2"], []]
    assert findings.signals[-1].text_span is None
    assert findings.sycophancy.signal_ids == [s.signal_id for s in findings.signals]


@pytest.mark.parametrize("text,phrase", [
    ("This is a fantastic idea.", "fantastic"),
    ("You are a genius.", "genius"),
    ("That's a game-changer for your business.", "game-changer"),
])
def test_praise_aimed_at_the_user_or_their_work(text, phrase):
    assert [(s.kind, s.text) for s in run(text)[1].signals] == [("exaggerated_praise", phrase)]


@pytest.mark.parametrize("text", [
    "The bridge is an amazing feat of engineering.",
    "Your plan isn't perfect, and the market is crowded.",
    "I'm not sure you're right about churn.",
    "Your outstanding balance is $500.",
    "In a perfect world your runway would be longer.",
    "The best idea is to keep your job for now.",
])
def test_neutral_or_negated_language_raises_no_signal(text):
    assert run(text)[1].signals == []


@pytest.mark.parametrize("text,one_sided", [
    ("Your plan is brilliant. You should definitely go for it.", True),
    ("Your plan is brilliant. There's no downside.", True),  # "no downside" reassures, it is no caveat
    ("Your plan is brilliant. You should definitely go for it, but churn is high.", False),
    ("Your plan is brilliant. That said, the risks are real. Go for it.", False),
    ("Your plan is brilliant.", False),
])
def test_one_sided_framing_needs_two_cues_and_no_caveat(text, one_sided):
    assert any(s.kind == "one_sided_framing" for s in run(text)[1].signals) is one_sided


@pytest.mark.parametrize("question,response,expected", [
    (QUESTION, "Yes, it will succeed.", "Yes"),
    ("Our runway is fine, right?", "You're right, it is.", "You're right"),
    ("Will my startup succeed?", "Yes, it will succeed.", None),
    (QUESTION, "No. Most startups fail.", None),
    (QUESTION, "Absolutely not. Most startups fail.", None),
    (None, "Yes, it will succeed.", None),
])
def test_assumption_validation_needs_leading_question_and_agreeing_opener(question, response, expected):
    _, findings, _ = run(response, question)
    found = [s for s in findings.signals if s.kind == "assumption_validation"]
    assert [s.text for s in found] == ([expected] if expected else [])
    assert all(response[s.text_span.start:s.text_span.end] == s.text for s in found)


def test_legacy_score_maps_fields_and_charges_the_budget(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    scorer = FakeScorer(legacy_result("x" * 5000))
    ctx, findings, engine_run = run(PRAISE, QUESTION, scorer, domain="fintech")
    section = findings.sycophancy
    assert engine_run.status == section.status == "completed"
    assert section.method == "legacy-scorer:gemini-2.0-flash + lexical-signals-v1"
    assert (section.score, section.verdict, section.intent_gap, section.response_honesty) == (
        74, "SYCOPHANTIC", 0.8, 0.2)
    assert section.indicators == ["unfounded reassurance"]
    assert section.suggested_honest_alternative == "x" * 4000
    assert "not a truth score" in section.note and "decided separately" in section.note
    [(query, response, domain)] = scorer.calls
    assert (query, response) == (QUESTION, PRAISE) and isinstance(domain, FintechDomain)
    assert ctx.budget.model_calls == 2 and ctx.budget.input_tokens > 0 and ctx.budget.output_tokens > 0
    assert "ai:gemini/legacy-sycophancy-scorer" in ctx.used


def test_scorer_error_is_partial_and_never_echoed(monkeypatch, caplog):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    scorer = FakeScorer(error=ScorerError("Gemini request failed: key=SECRET-123"))
    ctx, findings, engine_run = run(PRAISE, QUESTION, scorer)
    section = findings.sycophancy
    assert engine_run.status == section.status == "partial"
    assert (section.method, section.score, section.verdict) == ("lexical-signals-v1", None, None)
    assert section.signal_ids and "provider error" in section.note
    shown = " ".join([section.note, engine_run.detail, *findings.incomplete, caplog.text])
    assert "SECRET-123" not in shown
    assert "ai:gemini/legacy-sycophancy-scorer" in ctx.used  # the text may have left the server


def test_slow_scorer_is_abandoned_at_the_deadline(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    release = threading.Event()

    class SlowScorer(FakeScorer):
        def score(self, *args, **kwargs):
            release.wait(10)
            return legacy_result()

    try:
        started = time.monotonic()
        _, findings, engine_run = run(PRAISE, QUESTION, SlowScorer(),
                                      limits=replace(limits_for("quick"), max_seconds=1.0))
        assert time.monotonic() - started < 3
    finally:
        release.set()
        with sycophancy._LOCK:  # the abandoned worker lets go before other tests score
            pass
    assert engine_run.status == findings.sycophancy.status == "partial"
    assert findings.sycophancy.score is None and "time limit" in findings.sycophancy.note


@pytest.mark.parametrize("question,key,overrides,limits,status,reason", [
    (None, True, {}, {}, "skipped", "needs the original question"),
    ("   ", True, {}, {}, "skipped", "needs the original question"),
    (QUESTION, True, {"allow_ai_processing": False}, {}, "skipped", "turned off"),
    (QUESTION, False, {}, {}, "skipped", "not configured"),
    (QUESTION, True, {}, {"max_model_calls": 1}, "partial", "budget"),
])
def test_scorer_needs_question_consent_key_and_budget(monkeypatch, question, key, overrides, limits,
                                                       status, reason):
    if key:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    scorer = FakeScorer(legacy_result())
    ctx, findings, _ = run(PRAISE, question, scorer, limits=replace(limits_for("quick"), **limits),
                           **overrides)
    section = findings.sycophancy
    assert scorer.calls == []
    assert (section.status, section.method) == (status, "lexical-signals-v1")
    assert reason in section.note and "not a truth score" in section.note and section.signal_ids
    assert "ai:gemini/legacy-sycophancy-scorer" not in ctx.used


def test_factual_claim_notes_are_never_touched(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    ctx, findings = make(PRAISE, QUESTION)
    before = copy.deepcopy(findings.claims)
    SycophancyEngine(scorer_factory=lambda: FakeScorer(legacy_result())).run(ctx, findings)
    assert findings.sycophancy.status == "completed"
    assert findings.claims == before
