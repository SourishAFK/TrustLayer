"""Engine E (numbers): deterministic math, pure vs borrowed inputs, verdicts. Offline."""

from datetime import datetime, timezone

import pytest

from backend.verification.aggregator import decide
from backend.verification.budget import Budget, limits_for
from backend.verification.contracts import Findings, RunContext
from backend.verification.numerical import NumericalEngine, calculations, evaluate
from backend.verification.report import VerificationRequest
from backend.verification.service import extract_claims

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


def run(text):
    claims = extract_claims(text).claims
    ctx = RunContext(request=VerificationRequest(response_text=text), claims=claims,
                     budget=Budget(limits_for("quick")), now=NOW)
    findings = Findings([c.claim_id for c in claims])
    engine_run = NumericalEngine().run(ctx, findings)
    return claims, findings, engine_run, [decide(c, findings.claims[c.claim_id], NOW) for c in claims]


def only_calc(text):
    found = [(c, calc, corr) for c in extract_claims(text).claims for calc, corr in calculations(c)]
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize("text,kind,computed,consistent,pure", [
    ("20% of 150 is 40.", "percentage_of", "30", False, True),
    ("20% of 150 is 30.", "percentage_of", "30", True, True),
    ("30 is 20% of 150.", "percentage_of", "30", True, True),
    ("One kilometer equals 1,000 meters.", "unit_conversion", "1,000 meters", True, True),
    ("5 miles is 8 km.", "unit_conversion", "8.05 km", True, True),
    ("10 miles is 20 km.", "unit_conversion", "16.09 km", False, True),
    ("100°F is 37.8°C.", "unit_conversion", "37.78 °C", True, True),
    ("1 GB is 1,024 MB.", "unit_conversion", "1,024 MB", True, True),
    ("1 GB is 1,000 MB.", "unit_conversion", "1,000 MB", True, True),
    ("2 + 2 = 5.", "arithmetic", "4", False, True),
    ("12 × 3 is 36.", "arithmetic", "36", True, True),
    ("(2 + 3) * 4 = 20.", "arithmetic", "20", True, True),
    ("Revenue fell from $50M to $40M, a 25% decline.", "percent_change", "-20%", False, False),
    ("Users doubled from 10 to 25.", "multiple", "2.5×", False, False),
    ("$400k in the bank and a $200k monthly burn gives 6 months of runway.", "runway", "2 months", False, False),
])
def test_calculations(text, kind, computed, consistent, pure):
    _, calc, _ = only_calc(text)
    assert (calc.kind, calc.computed_value, calc.consistent, calc.pure_math) == (kind, computed, consistent, pure)
    if not pure:
        assert "arithmetic only" in calc.note


def test_rounded_statements_are_consistent():
    assert only_calc("1 out of 3 is 33%... no: 100 / 3 = 33.")[1].consistent
    assert only_calc("Revenue rose from $30M to $40M, a 33% increase.")[1].consistent


def test_direction_must_match_the_numbers():
    _, calc, correction = only_calc("Sales went from 50 to 40, an increase of 20%.")
    assert not calc.consistent and "fall, not a rise" in correction


def test_fragment_borrows_inputs_and_is_never_pure():
    claims = extract_claims("The market grew from $20 million to $30 million, an increase of 80%.").claims
    assert [c.exact_text for c in claims] == ["The market grew from $20 million to $30 million",
                                              "an increase of 80%"]
    assert calculations(claims[0]) == []  # "$20 million" is not the stated 80%
    calc, correction = calculations(claims[1])[0]
    assert (calc.computed_value, calc.consistent, calc.pure_math) == ("50%", False, False)
    assert correction == "an increase of 50%"


def test_the_right_occurrence_is_corrected():
    _, calc, correction = only_calc("Revenue rose from 80 units to 100 units in 2025 (+80%).")
    assert correction == "Revenue rose from 80 units to 100 units in 2025 (+25%)"


@pytest.mark.parametrize("text", [
    "Acme was founded in 2015.", "Acme has 10-20 employees.", "Between 2015-2020 sales grew.",
    "Call 555-1234 for details.", "10 / 0 = 5.", "Revenue will double next year.",
    "Acme grew from $20 million to $30 million.", "We serve 3 continents in 5 languages.",
    "Revenue grew 20% from 2015 to 2020.",
    # Ranges, dimensions and idioms are not arithmetic.
    "Adults aged 18 - 24 are 12 percent of voters.", "Pages 10 - 20 are 11 pages.", "Weeks 1 - 4 are 28 days.",
    "A 2 x 4 is 1.5 x 3.5 inches.", "Its 4K resolution (3840 x 2160) is 2160p.", "We are open 24/7 = 168 hours a week.",
    "Scores of 24/7 are 3 points.", "The match ended 3-2.", "Screens use a 16:9 ratio.", "(2 - 10) ^ 0.5 = 3.",
    # A percent change describes only the from–to it is attached to.
    "Revenue grew from $20M to $30M last year, and headcount increased by 15%.",
    "Prices went from $10 to $12 in 2023 while wages grew 3%.", "Profit rose 10% while costs went from $100 to $150.",
    "Stock price went from $50 to $100 and the market fell 3%.", "Revenue rose 50% as sales went from $20M to $30M.",
    "Users doubled while prices went from $10 to $11.", "Users doubled, while prices went from $10 to $11.",
    # A year is never the stated result.
    "Acme's revenue in 2023 is 15% of $2B.", "Exports in 2023 are 30% of 500 billion dollars.",
])
def test_no_false_positives(text):
    assert [c for claim in extract_claims(text).claims for c in calculations(claim)] == []


@pytest.mark.parametrize("text", [
    "1 foot is 0 meters.", "20% of 8 is 2.", "1 inch is 3 cm.", "1 mile is 2 km.", "10 / 4 = 2.", "10 / 4 = 3.",
    "1000 + 5 = 1000.", "200 + 1 = 200.", "0.4 + 0.4 = 1.", "0.1 + 0.1 = 0.", "7 / 2 = 3.", "15% of 10 is 1.",
    "30°C is 90°F.", "2 + 2 = 4 million.", "3 × 4 = 12 billion.",
])
def test_wrong_math_is_never_rounded_into_agreement(text):
    assert not only_calc(text)[1].consistent


@pytest.mark.parametrize("text", [
    "5 km is about 3.1 miles.", "22 / 7 = 3.14.", "1 / 3 = 0.33.", "20% of 1,234,567 is about 247,000.",
    "-18 °C is 0 °F.", "-10 °C is 14 °F.", "-3 + 5 = 2.", "5 - 10 = -5.", "- 3 + 5 = 8.",
    "1,000 × 1,000 = 1 million.", "10^6 = 1 million.", "500 × 100 = 50 thousand.", "3 x 4 = 12.",
    "Revenue went from $20M to $30M (a 50% increase).", "Revenue rose 50% from $20M to $30M.",
    "Revenue grew by 50%, from $20M to $30M.", "Sales grew from 80 units to 100 units, an increase of 25%.",
    "Revenue grew from $20M to $30M in 2023, an increase of 50%.",
])
def test_rounding_signs_and_scales_that_agree(text):
    assert only_calc(text)[1].consistent


def test_a_scaled_result_is_corrected_without_the_scale():
    assert only_calc("2 + 2 = 4 million.")[2] == "2 + 2 = 4"


def test_one_unreadable_value_never_stops_the_engine():
    _, _, engine_run, verdicts = run("5 - 7 = -2. Also 2 + 2 = 5.")
    assert [v.verification_status for v in verdicts] == ["SUPPORTED", "CONTRADICTED"]
    assert engine_run.status == "completed"


def test_a_crashing_claim_is_isolated_and_cannot_be_supported(monkeypatch):
    import backend.verification.numerical as numerical

    real = numerical.calculations

    def flaky(claim):
        if "2 + 2" in claim.exact_text:
            raise RuntimeError("boom")
        return real(claim)

    monkeypatch.setattr(numerical, "calculations", flaky)
    _, findings, engine_run, verdicts = run("20% of 150 is 30. Also 2 + 2 = 4.")
    assert engine_run.status == "partial" and "could not be checked" in engine_run.detail
    assert [v.verification_status for v in verdicts] == ["SUPPORTED", "UNVERIFIED"]
    assert verdicts[1].checks[0].status == "failed"


@pytest.mark.parametrize("text", [
    "The series " + " + ".join(str(i) for i in range(1, 41)) + " is long.", "1 + " * 6000 + "1",
    "Our revenue was " + "1  +  " * 7 + "1 dollars in 2024.", "1  +  " * 4000 + "x", "doubled " * 3000,
    "( 1 )  +  " * 2000 + "( 1 ) ?",
])
def test_patterns_stay_linear_on_adversarial_text(text):
    import time

    from backend.verification.numerical import _find

    started = time.perf_counter()
    _find(text)
    assert time.perf_counter() - started < 1.0


def test_evaluator_is_not_eval():
    assert evaluate("2 + 3 * 4") == 14 and evaluate("(2 + 3) * 4") == 20 and evaluate("2 ^ 3 ^ 2") == 512
    for hostile in ("__import__('os')", "9 ^ 9999", "1 / 0", "2 +", "(1 + 2", "(2 - 10) ^ 0.5"):
        with pytest.raises(ValueError):
            evaluate(hostile)


def test_verdicts_through_the_aggregator():
    _, findings, engine_run, verdicts = run(
        "20% of 150 is 40. One kilometer equals 1,000 meters. "
        "The market grew from $20 million to $30 million, an increase of 50%.")
    statuses = [v.verification_status for v in verdicts]
    assert statuses == ["CONTRADICTED", "SUPPORTED", "UNVERIFIED", "UNVERIFIED"]
    assert verdicts[0].suggested_correction == "20% of 150 is 30"
    assert "deterministic_calculation" in verdicts[1].verification_methods
    assert "not independently verified" in verdicts[3].explanation
    assert engine_run.status == "completed" and "3 calculation(s) checked, 1 inconsistent" in engine_run.detail


def test_not_checkable_claims_are_skipped():
    _, _, engine_run, _ = run("I think 2 + 2 = 5 is a beautiful idea.")
    assert engine_run.status == "not_applicable"


def test_from_to_with_a_year_after_each_figure():
    claims = extract_claims("Greenvane's revenue grew from $12 million in 2024 to $18 million in 2025, "
                            "an increase of 60%.").claims
    calc, correction = calculations(claims[-1])[0]
    assert (calc.computed_value, calc.consistent, correction) == ("50%", False, "an increase of 50%")
