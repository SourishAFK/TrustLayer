"""Engine H: certainty language, overconfident predictions, missing caveats, freshness.

Two deterministic engines share this module (no model calls in either mode):

* UncertaintyEngine (deterministic stage) flags absolute or exclusive wording
  inside claim spans, predictions stated as certain, and high-stakes advice
  (money, health, law, tax) given with no hedge or caveat anywhere in the
  response. Signals are observations, never verdicts. Every prediction gets a
  note that becomes its NOT CHECKABLE explanation.
* FreshnessEngine (post-research stage) decides whether each checkable claim
  describes a changing situation (a current role, price, rate, "as of" figure)
  and compares it with the newest dated evidence other engines found. The
  aggregator then counts only current evidence for time-sensitive claims.

Limits: English phrase lists. Negation is read only in the few words before a
phrase within its clause ("not always", "no guarantee") and quoted phrases are skipped; sarcasm,
reported speech ("they promise guaranteed returns") and long-range negation are
not understood. Time sensitivity widens the extractor's classification, never
narrows it, so a mistake costs an UNVERIFIED verdict rather than a false SUPPORTED.
"""

import re
import time
from datetime import datetime, timedelta, timezone

from backend.verification.aggregator import freshness_days
from backend.verification.contracts import Findings, RunContext
from backend.verification.report import EngineRun, Freshness
from backend.verification.schemas import Claim, ClaimType, TextSpan

PREDICTION_NOTE = "This is a prediction about an unrealized event; it cannot be verified now."

# ponytail: fixed English phrase lists; paraphrases ("can't lose") slip through.
# A Deep-mode model reader with quote validation is the upgrade path.
ABSOLUTE = re.compile(
    r"\b(?:(?P<certainty>guarantee[sd]?|definitely|certainly(?![,!])|undoubtedly"
    r"|without (?:a|any) doubt|proven|impossible|zero[ -]risk|risk[ -]free|no risks?(?!-)"
    r"|(?:cannot|can['’]t) fail|will never|never fails|(?<!\bas )always(?!-)"
    # A bare "100%" is usually a measured share ("100% of revenue"); only certainty uses count.
    r"|100(?:\s?%| percent) (?:sure|certain|confident|chance|guaranteed|safe|secure|accurate"
    r"|effective|reliable|foolproof|proven|correct|risk[ -]free|of the time))"
    r"|(?P<exclusive>no (?:[\w-]+ )?competit(?:ors?|ion)|no one else|nobody else|first[ -]ever"
    r"|unmatched|unrivall?ed|the only (?:[\w-]+ )?(?:compan(?:y|ies)|products?|platforms?"
    r"|tools?|solutions?|ways?))"
    # Weak universals; frequencies ("every 4 hours") and idioms ("after all") are not claims.
    r"|(?P<universal>everyone|nothing|none|every(?! (?:\d|other\b|few\b|(?:second|minute|hour"
    r"|day|week|month|quarter|year|morning|evening|night)s?\b))"
    r"|(?<!\bafter )(?<!\babove )(?<!\bat )(?<!\bof )(?<!\bin )all(?! in all\b)(?!-)))\b",
    re.I,
)
# Prediction-only certainty phrases. In a predictive claim the certainty group of ABSOLUTE
# ("always", "guaranteed", "100% sure") also counts as an overconfident prediction.
PREDICTION = re.compile(r"\b(?:will (?:definitely|certainly|surely|undoubtedly|inevitably)"
                        r"|(?:is|are) (?:bound|certain|sure) to|guaranteed to|no doubt)\b", re.I)
NEGATED = re.compile(r"(?:\b(?:not|no|never|neither|nor|without|cannot|nothing|almost|nearly|virtually"
                     r"|practically|hardly)|n['’]t)\s+(?:[\w'’-]+\s+){0,2}$", re.I)
# Negation does not reach across a clause break: "no fees and guaranteed returns".
CLAUSE = re.compile(r"[,;:()—–]|\b(?:and|but)\b", re.I)
EXPLAIN = {
    "certainty": "Certainty wording: this is stated as certain or risk-free, leaving no room for "
                 "exceptions.",
    "exclusive": "Exclusivity wording: claims like this are hard to prove, and finding no "
                 "counterexample does not confirm them.",
    "universal": "Universal wording: a single counterexample would make this statement false.",
    "prediction": "A prediction about an unrealized event is stated as a certainty.",
}

# ponytail: topic and recommendation must share a sentence; advice whose topic is named
# one sentence earlier is missed.
HIGH_STAKES = re.compile(
    r"\b(?:invest\w*|stocks|(?<!\bin )stock|equities|crypto\w*|bitcoin|ethereum|savings|retirement"
    r"|portfolio|loans?|mortgages?|medical|medicines?|medications?|drugs?|doses?|dosages?"
    r"|diagnos\w*|treatments?|prescri\w*|symptoms?|legal|lawsuits?|sue|tax(?:es)?)\b"
    r"|\b\d+(?:\.\d+)?\s?(?:mg|mcg)\b", re.I)
RECOMMENDS = re.compile(r"\byou (?:should|must|need to|ought to)\b"
                        r"|\bI(?:['’]d| would)?(?: strongly| highly)? (?:recommend|suggest|advise)\b"
                        r"|\bgo ahead and\b", re.I)
IMPERATIVE = re.compile(r"(?:buy|sell|invest in|take|stop taking)\b", re.I)  # only at sentence start
HEDGES = re.compile(
    r"\b(?:not (?:financial|investment|medical|legal|tax) advice|consult\w*|professional\w*|risk\w*"
    r"|may|might|could|depend\w*|however|but|although|keep in mind|caution\w*|careful\w*|doctors?"
    r"|physicians?|pharmacists?|advis[eo]rs?|lawyers?|attorneys?)\b", re.I)
SENTENCE = re.compile(r"(?:[^.!?\n]|[.!?](?=\S))+")

# ponytail: fixed vocabulary of changing facts; other live metrics (users, revenue run-rate)
# rely on the extractor's own time_sensitive class.
VOLATILE = re.compile(r"\b(?:current(?:ly)?|now|today|latest|as of|this year|at the moment|presently"
                      r"|recent(?:ly)?|so far|to date)\b", re.I)
ROLES = re.compile(r"\b(?:CEO|president|prime minister|chair(?:man|woman|person)|prices?|exchange rates?"
                   r"|interest rates?|rank(?:ing|ed|s)?|market share|population|headcount|employ(?:s|ees)"
                   r"|staff)\b", re.I)
PRESENT = re.compile(r"\b(?:is|are|has|have|remains?|stands?|trades?|holds?|leads?|serves?|ranks?"
                     r"|employs?)\b", re.I)
PAST = re.compile(r"\b(?:was|were|had|did|\w+ed)\b", re.I)
# Words that put a claim in the present even when it also cites an old date.
NOW_WORDS = re.compile(r"\b(?:current(?:ly)?|now|today|still|presently|at present|at the moment|these days"
                       r"|nowadays)\b", re.I)
YEAR = re.compile(r"\b(?:1[6-9]|20)\d{2}\b")
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
AS_OF = re.compile(
    r"\bas of (?P<date>(?:(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?"
    r"|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+"
    r"(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?)?(?P<year>(?:1[6-9]|20)\d{2}))\b", re.I)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _skip(before: str) -> bool:
    """Negated in its own clause ("not always", "no guarantee") or inside quotation marks."""
    clause = CLAUSE.split(before[-80:])[-1]
    return bool(NEGATED.search(clause)) or sum(before.count(q) for q in '"“”') % 2 == 1


def _phrases(claim: Claim) -> list[tuple[re.Match, str]]:
    """(match, group) for each unnegated, unquoted phrase in text order; prediction phrases
    win overlaps, and weak universals count only in universal/negative claims."""
    text = claim.exact_text
    found = ([(m, "prediction") for m in PREDICTION.finditer(text)]
             if claim.claim_type == ClaimType.predictive else [])
    found += [(m, m.lastgroup) for m in ABSOLUTE.finditer(text)
              if m.lastgroup != "universal" or claim.claim_type == ClaimType.negative_universal]
    kept: list[tuple[re.Match, str]] = []
    for m, group in found:
        if not _skip(text[:m.start()]) and all(m.end() <= k.start() or k.end() <= m.start()
                                               for k, _ in kept):
            kept.append((m, group))
    return sorted(kept, key=lambda item: item[0].start())


def _span(claim: Claim, match: re.Match) -> TextSpan:
    start = claim.text_span.start + match.start()
    return TextSpan(start=start, end=start + len(match.group()))


def _unhedged_advice(text: str) -> tuple[int, int] | None:
    """Span of the first recommendation in a money/health/legal/tax sentence, when the
    response carries no hedge or caveat anywhere."""
    if HEDGES.search(text):
        return None
    for sentence in SENTENCE.finditer(text):
        body = sentence.group()
        if not HIGH_STAKES.search(body):
            continue
        lead = re.match(r"[\W\d_]*", body).end()
        found = IMPERATIVE.match(body, lead) or RECOMMENDS.search(body)
        if found:
            return sentence.start() + found.start(), sentence.start() + found.end()
    return None


class UncertaintyEngine:
    """Deterministic stage: certainty language, overconfident predictions, missing caveats."""
    name = "uncertainty"

    def run(self, ctx: RunContext, findings: Findings) -> EngineRun:
        started = time.perf_counter()
        phrases = predictions = 0
        for claim in ctx.claims:
            cid = claim.claim_id
            predictive = claim.claim_type == ClaimType.predictive
            if predictive:
                findings.note(cid, note=PREDICTION_NOTE)
            for m, group in _phrases(claim):
                overconfident = predictive and group in ("prediction", "certainty")
                predictions += overconfident
                phrases += not overconfident
                findings.add_signal(
                    engine=self.name,
                    kind="overconfident_prediction" if overconfident else "absolute_language",
                    severity="info" if group == "universal" else "warning", text=m.group(),
                    text_span=_span(claim, m), claim_ids=[cid],
                    explanation=EXPLAIN["prediction" if overconfident else group])
                findings.note(cid, flag=m.group().lower())

        response = ctx.request.response_text
        advice = _unhedged_advice(response)
        if advice:
            start, end = advice
            findings.add_signal(
                engine=self.name, kind="missing_caveat", severity="warning",
                text=response[start:end], text_span=TextSpan(start=start, end=end),
                claim_ids=[c.claim_id for c in ctx.claims
                           if c.text_span.start <= start < c.text_span.end],
                explanation="High-stakes advice (money, health, legal or tax) is given as a "
                            "recommendation with no caveat, risk note or suggestion to consult a "
                            "professional anywhere in the response.")
        if not ctx.claims and not advice:
            return EngineRun(engine=self.name, status="not_applicable", duration_ms=_elapsed_ms(started),
                             detail="No claims to examine and no unhedged high-stakes advice.")
        return EngineRun(
            engine=self.name, status="completed", duration_ms=_elapsed_ms(started),
            detail=f"Examined {len(ctx.claims)} claim(s): {phrases} absolute-language phrase(s), "
                   f"{predictions} overconfident prediction(s), {int(bool(advice))} missing caveat(s).")


def _utc(value: datetime) -> datetime:
    # Parsed dates ("2026-05-01") arrive naive; treat them as UTC so comparisons never raise.
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _period_end(match: re.Match) -> datetime:
    """First instant after the stated period: "March 2019" -> 2019-04-01, "2019" -> 2020-01-01."""
    year, month = int(match.group("year")), match.group("month")
    m = MONTHS.index(month[:3].lower()) + 1 if month else 12
    return datetime(year + m // 12, m % 12 + 1, 1, tzinfo=timezone.utc)


def _assess(claim: Claim, newest: datetime | None, now: datetime, checked_at: datetime,
           days: int) -> Freshness:
    """Freshness of one checkable claim. `now` and `newest` are UTC-aware."""
    exact = claim.exact_text
    cutoff = now - timedelta(days=days)
    as_of = list(AS_OF.finditer(exact))
    present_role = bool(ROLES.search(exact) and PRESENT.search(exact))
    past = claim.claim_type == ClaimType.historical or (
        bool(PAST.search(exact)) and any(int(y) < now.year for y in YEAR.findall(exact)))
    # Earlier clauses of the sentence lend their qualifiers ("Today, X ... and Y ..."); later
    # clauses do not, so "founded in 2015 and currently has" keeps the founding date stable.
    lead_in = claim.context[:claim.context.find(exact)] + exact
    # "As of 2019 and still today, X is currently CEO" describes now, not a 2019 snapshot.
    old = None if NOW_WORDS.search(exact) else next(
        (m.group("date") for m in as_of if _period_end(m) <= cutoff), None)
    # "As of 2019, ..." pins the claim to a past date: a dated snapshot that sources
    # from that time can support. It is not judged against today's evidence, but
    # the reader is still told the situation may have changed.
    sensitive = old is None and (claim.claim_type == ClaimType.time_sensitive or bool(as_of)
                                 or present_role or (not past and bool(VOLATILE.search(lead_in))))
    changed = old is not None or (sensitive and (newest is None or newest < cutoff))
    if old:
        note = (f"The claim describes the situation as of {old}: sources from that time can "
                "support it, but it may have changed since.")
    elif not sensitive:
        note = ("Not time-sensitive: the claim describes a dated past event." if past else
                "Not time-sensitive: the claim does not describe a current role, price, rate or "
                "other changing figure.")
    elif newest is None:
        note = ("This describes a situation that changes over time, and no dated evidence was "
                "found; it may have changed.")
    elif newest < cutoff:
        note = (f"This describes a situation that changes over time; the newest dated evidence "
                f"({newest:%Y-%m-%d}) is older than {days} days, so it may have changed.")
    else:
        note = (f"This describes a situation that changes over time; the newest dated evidence is "
                f"from {newest:%Y-%m-%d}.")
    return Freshness(time_sensitive=sensitive,
                     claim_dates=list(dict.fromkeys(claim.scope.dates + [m.group("date") for m in as_of])),
                     newest_evidence_at=newest, checked_at=checked_at, may_have_changed=changed, note=note)


class FreshnessEngine:
    """Post-research stage: time sensitivity and evidence age for every checkable claim."""
    name = "freshness"

    def run(self, ctx: RunContext, findings: Findings) -> EngineRun:
        started = time.perf_counter()
        days, now = freshness_days(), _utc(ctx.now)
        checked = sensitive = changed = 0
        for claim in ctx.claims:
            if not claim.objectively_checkable:
                continue
            with findings.lock:
                notes = findings.claims[claim.claim_id]
                newest = max((_utc(e.published_at) for e in notes.evidence + notes.contradictions
                              if e.published_at is not None), default=None)
            fresh = _assess(claim, newest, now, ctx.now, days)
            findings.note(claim.claim_id, freshness=fresh)
            if fresh.may_have_changed:
                findings.note(claim.claim_id, note=fresh.note)  # surfaces in the verdict explanation
            checked += 1
            sensitive += fresh.time_sensitive
            changed += fresh.may_have_changed
        return EngineRun(
            engine=self.name, status="completed" if checked else "not_applicable",
            duration_ms=_elapsed_ms(started),
            detail=f"Checked {checked} claim(s): {sensitive} time-sensitive, {changed} may have "
                   f"changed (freshness window {days} days).")
