"""Engine G: completeness versus the original question. Offline, fake reviewer."""

from datetime import datetime, timezone

from backend.verification.budget import Budget, limits_for
from backend.verification.completeness import (
    NOTE,
    CompletenessEngine,
    lexical_review,
    subquestions,
)
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
        assert schema["title"] == "completeness_review" and "<question>" in prompt
        return LLMResult(self.data, self.model, 10, 10)


def run(response, question=None, mode="quick", llm=None):
    claims = extract_claims(response).claims
    ctx = RunContext(request=VerificationRequest(response_text=response, original_question=question, mode=mode),
                     claims=claims, budget=Budget(limits_for(mode)), now=NOW, llm=llm)
    findings = Findings([c.claim_id for c in claims])
    engine_run = CompletenessEngine().run(ctx, findings)
    return findings.completeness, engine_run


def kinds(missing):
    return [(m.kind, m.question_quote) for m in missing]


def test_unanswered_part_of_a_two_part_question():
    q = "What is Acme's pricing? And who are Acme's main competitors?"
    section, run_ = run("Acme charges $49 per month for the pro plan.", q)
    assert [(s.text, s.coverage) for s in section.subquestions] == [
        ("What is Acme's pricing?", "addressed"), ("And who are Acme's main competitors?", "not_addressed")]
    assert kinds(section.missing) == [("unanswered_subquestion", "And who are Acme's main competitors?")]
    assert all(m.question_quote in q for m in section.missing)
    assert NOTE in section.note and run_.status == "completed"


def test_budget_constraint():
    q = "Recommend a laptop under $500 for students."
    assert kinds(lexical_review(q, "The Zenbook 14 laptop costs $899 and suits students.")[1]) == [
        ("unaddressed_constraint", "under $500")]
    assert lexical_review(q, "The Zenbook 14 laptop costs $480 and suits students.")[1] == []


def test_comparison_needs_both_sides():
    q = "Compare Notion and Obsidian for note-taking."
    assert ("incomplete_comparison", "Compare Notion and Obsidian for note-taking") in kinds(
        lexical_review(q, "Notion offers databases, templates and team sharing.")[1])
    both = lexical_review(q, "Notion has databases; Obsidian stores local markdown notes.")[1]
    assert not any(m.kind == "incomplete_comparison" for m in both)


def test_place_and_deadline_constraints():
    missing = lexical_review("Which startups sell robots in Germany within 30 days?", "Acme sells robots.")[1]
    assert kinds(missing) == [("unaddressed_constraint", "within 30 days"), ("unaddressed_constraint", "in Germany")]


def test_fully_answered_numbered_questions():
    q = "1. What does Acme sell?\n2. Where is Acme based?"
    assert subquestions(q) == ["What does Acme sell?", "Where is Acme based?"]
    section, _ = run("Acme sells warehouse robots. Acme is based in Berlin.", q)
    assert section.missing == [] and {s.coverage for s in section.subquestions} == {"addressed"}


def test_missing_question_is_limited():
    section, run_ = run("Acme sells robots.")
    assert section.status == "limited" and run_.status == "skipped" and "not supplied" in section.note


def test_deep_review_requires_exact_quotes():
    q = "What does Acme sell, and is it safe for small warehouses?"
    reviewer = Reviewer({
        "subquestions": [
            {"question_quote": "What does Acme sell", "coverage": "addressed",
             "response_quote": "Acme sells warehouse robots", "note": "answered"},
            {"question_quote": "is it safe for small warehouses", "coverage": "addressed",
             "response_quote": "fully certified for safety", "note": "claims safety"},  # quote not in response
            {"question_quote": "an invented question", "coverage": "not_addressed", "response_quote": "", "note": ""}],
        "missing": [
            {"kind": "missing_limitation", "description": "No safety caveats.",
             "question_quote": "is it safe for small warehouses"},
            {"kind": "missing_limitation", "description": "Fabricated quote.", "question_quote": "budget of $5"}]})
    section, _ = run("Acme sells warehouse robots.", q, mode="deep", llm=reviewer)
    assert [(s.text, s.coverage) for s in section.subquestions] == [
        ("What does Acme sell", "addressed"), ("is it safe for small warehouses", "unclear")]
    assert ("missing_limitation", "is it safe for small warehouses") in kinds(section.missing)
    assert not any(m.question_quote == "budget of $5" for m in section.missing)
    assert section.method.startswith("llm-completeness:fake-reviewer") and "2 AI finding(s)" in section.note


def test_quick_mode_never_calls_the_model():
    reviewer = Reviewer({"subquestions": [], "missing": []})
    run("Acme sells robots.", "What does Acme sell?", llm=reviewer)
    assert reviewer.calls == 0


def test_each_missing_comparison_side_is_reported_once():
    _, missing = lexical_review("Compare Notion vs Obsidian. Which is better, Figma or Sketch?",
                                "Notion is great. Figma is fast.")
    assert [m.description.rsplit(" ", 1)[-1] for m in missing if m.kind == "incomplete_comparison"] == \
        ["Obsidian.", "Sketch."]
    _, missing = lexical_review(("a vs b, " * 2000)[:8000], "The answer covers general topics only.")
    assert len(missing) == 1


def test_repeated_constraints_are_checked_and_reported_once():
    _, missing = lexical_review(("in Paris " * 2000)[:8000], "The answer covers general topics only.")
    assert [m.kind for m in missing] == ["unaddressed_constraint"]


def test_adversarial_questions_stay_fast():
    import time

    response = ("The answer covers general topics only. " * 700)[:24000]
    for question in (("compare x and " * 600)[:8000], "compare " + "to " * 2660 + "(", ("a vs b, " * 2000)[:8000],
                     ("in Paris " * 2000)[:8000], ("under $5 " * 2000)[:8000],
                     ("difference between x and " * 400)[:8000], ("which is better, x or " * 400)[:8000]):
        started = time.perf_counter()
        lexical_review(question, response)
        assert time.perf_counter() - started < 1.0
