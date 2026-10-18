"""Verdict policy: blackboard findings in, one of five statuses out.

Deterministic on purpose. Models only produced stance judgments upstream, and
those were validated (exact quotes, number guards) before reaching the board.
The policy prefers abstaining (UNVERIFIED) over a confident mistake:

  NOT CHECKABLE  opinions, predictions, unobservable statements (from extraction)
  CONTRADICTED   a pure calculation fails, or credible contradicting evidence
                 meets the threshold while support does not
  DISPUTED       both sides have evidence and at least one side meets the threshold
  SUPPORTED      support meets the threshold, nothing contradicts, the claim is
                 not universal/negative, and time-sensitive evidence is current
  UNVERIFIED     everything else — with the reason in missing_evidence

Threshold: two independent domains, or one authoritative source (primary,
official, academic or reference). User-provided sources never count as
authoritative, and a subject's own site (primary) is not authoritative about its
own efficacy or superiority ("our gummies cure insomnia", "the fastest platform").

Universal/negative wording is detected from the text as well as the extracted
category, so a misclassified "no vendor offers this" still cannot be SUPPORTED.
A claim whose investigation failed partway is never SUPPORTED: the failure may
have hidden contradicting evidence.
"""

import os
import re
from datetime import datetime, timedelta

from backend.verification.contracts import ClaimNotes
from backend.verification.report import Evidence, SourceRef, VerifiedClaim
from backend.verification.schemas import Claim, ClaimType, VerificationStatus

AUTHORITATIVE = {"primary", "official", "academic", "reference"}
S = VerificationStatus
# Existential / exclusivity wording that search can never confirm ("absence of
# evidence"). Checked on the text too, so the guard does not depend on the
# extractor's category, which misses some of these.
UNIVERSAL = re.compile(
    r"\b(?:(?:no|zero|not (?:a single|one)) (?:\w+\s+){0,3}(?:competitors?|competition|alternatives?|rivals?|"
    r"substitutes?|vendors?|companies|company|startups?|products?|tools?|one else)"
    r"|no one|nobody|none of|no other|the only|(?:the )?sole (?:\w+\s+){0,2}(?:providers?|suppliers?|makers?|"
    r"manufacturers?|compan(?:y|ies)|vendors?|sources?|sellers?|producers?|platforms?|options?|players?)"
    r"|unrivall?ed|unmatched|unparall?eled|without (?:any )?(?:competitors?|competition|rivals?)"
    r"|(?:of|than) any(?: other)?"  # "the lowest fees of any index fund": needs every fund checked
    r"|(?:the )?first ever|unique in the (?:market|world|industry))\b",
    re.I,
)
# Claims a seller's own site cannot vouch for: efficacy, safety and superiority.
SELF_SERVING = re.compile(
    r"\b(?:cur(?:e|es|ed|ing)|treats?|prevents?|heals?|reverses?|boosts?|improves?|reduces? (?:the )?risk|"
    r"lowers?|clinically|proven|guarantee[sd]?|safe(?:st|r)?|best|fastest|leading|#1|number one|"
    r"most (?:popular|trusted|effective|advanced|accurate|secure)|better than|outperforms?|more effective|"
    r"(?:obvious|right|smart) choice|ideal|perfect|superior|unbeatable|must-have|(?:faster|cheaper) than|"
    r"largest|biggest|lowest|cheapest|highest|top|dominant|most)\b",
    re.I,
)


def is_universal(claim: Claim) -> bool:
    return claim.claim_type == ClaimType.negative_universal or bool(UNIVERSAL.search(claim.exact_text))


def authoritative_types(claim: Claim) -> set[str]:
    # Not the extractor's "comparative" label: "has more than 140 customers" is a self-reported fact.
    if claim.claim_type == ClaimType.scientific or SELF_SERVING.search(claim.exact_text):
        return AUTHORITATIVE - {"primary"}
    return AUTHORITATIVE


def freshness_days() -> int:
    value = int(os.getenv("TRUSTLAYER_FRESHNESS_DAYS", "365"))
    if not 1 <= value <= 3650:
        raise ValueError("TRUSTLAYER_FRESHNESS_DAYS must be between 1 and 3650.")
    return value


def weigh(items: list[Evidence], authoritative_kinds: set[str] = AUTHORITATIVE) -> tuple[bool, str]:
    """(meets threshold, strength) for evidence that shares one stance."""
    domains = {e.domain for e in items}
    authoritative = any(e.source_type in authoritative_kinds for e in items)
    if not domains:
        return False, "none"
    if not (len(domains) >= 2 or authoritative):
        return False, "weak"
    strong = (len(domains) >= 2 and authoritative) or len(domains) >= 3
    return True, "strong" if strong else "moderate"


def _domains(items: list[Evidence]) -> str:
    names = list(dict.fromkeys(e.domain for e in items))
    shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
    return f"{len(names)} independent source{'s' if len(names) != 1 else ''} ({shown})"


def _current(items: list[Evidence], now: datetime, days: int) -> list[Evidence]:
    cutoff = now - timedelta(days=days)
    return [e for e in items if e.published_at is not None and e.published_at >= cutoff]


def decide(claim: Claim, notes: ClaimNotes, now: datetime) -> VerifiedClaim:
    support, contra = list(notes.evidence), list(notes.contradictions)
    related = list(notes.related_sources)
    missing = list(notes.missing)
    explanation: list[str] = []
    investigated = notes.investigated or bool(support or contra or notes.calculations)
    fields = {k: getattr(claim, k) for k in ("claim_id", "exact_text", "text_span", "claim_type",
                                             "context", "qualifiers", "scope", "objectively_checkable")}

    time_sensitive = (notes.freshness.time_sensitive if notes.freshness
                      else claim.claim_type == ClaimType.time_sensitive)
    if time_sensitive and claim.objectively_checkable:
        # Only current evidence may decide a time-sensitive claim. Older or undated
        # sources stay visible as related sources instead of silently vanishing.
        days = freshness_days()
        current_support, current_contra = _current(support, now, days), _current(contra, now, days)
        stale = [e for e in support + contra if e not in current_support + current_contra]
        for e in stale:
            related.append(SourceRef(url=e.url, title=e.title, domain=e.domain,
                                     note=f"Undated or older than {days} days; not counted for "
                                          f"this time-sensitive claim (it {e.stance} it)."))
        if stale:
            missing.append(f"{len(stale)} source(s) were undated or older than {days} days; "
                           "this time-sensitive claim needs current evidence.")
        support, contra = current_support, current_contra

    common = dict(
        calculations=notes.calculations, related_sources=related,
        citation_ids=notes.citation_ids, verification_methods=notes.methods, checks=notes.checks,
        limitations=list(dict.fromkeys(claim.limitations + notes.limitations)),
        certainty_flags=notes.certainty_flags, freshness=notes.freshness,
    )

    if not claim.objectively_checkable:
        return VerifiedClaim(
            **fields, **common, verification_status=S.not_checkable, evidence_strength="none",
            explanation=" ".join(notes.notes) or claim.explanation, missing_evidence=missing,
            investigated=False, checked_at=None)

    def build(status, strength, correction=None):
        return VerifiedClaim(
            **fields, **common, verification_status=status, evidence_strength=strength,
            evidence=support, contradictions=contra, explanation=" ".join(explanation + notes.notes),
            missing_evidence=list(dict.fromkeys(missing)), suggested_correction=correction,
            investigated=investigated, checked_at=now if investigated else None)

    failed = [c for c in notes.calculations if not c.consistent]
    if failed:
        calc = failed[0]
        explanation.append(f"The stated figures do not add up: {calc.expression} gives "
                           f"{calc.computed_value}, not {calc.stated_value}.")
        if not calc.pure_math:
            explanation.append("This checks the arithmetic only; the input figures were not verified.")
        return build(S.contradicted, "strong", correction=_correction(notes, None))

    support_counted, contra_counted = support, contra
    counted_against = {e.domain for e in contra_counted}

    sup_ok, sup_strength = weigh(support_counted, authoritative_types(claim))
    con_ok, con_strength = weigh(contra_counted)
    needs_more = ("Needs a second independent source, or one primary, official, academic "
                  "or reference source.")
    if not sup_ok and support_counted and weigh(support_counted)[0]:
        missing.append("The subject's own website cannot by itself confirm claims about its own "
                       "efficacy, safety or superiority; an independent source is needed.")
    broken = [c for c in notes.checks if c.status == "failed"]
    withheld = sup_ok and bool(broken)
    if withheld:
        sup_ok = False
        explanation.append("Part of this claim's investigation failed, so it cannot be confirmed: the "
                           "failure may have hidden contradicting evidence.")
        missing.append("A complete investigation of this claim.")

    if support_counted and contra_counted:
        if con_ok and not sup_ok:
            explanation.append(f"Credible evidence conflicts with this claim: {_domains(contra_counted)}. "
                               f"Weaker evidence agrees: {_domains(support_counted)}.")
            return build(S.contradicted, con_strength, correction=_correction(notes, counted_against))
        if sup_ok or con_ok:
            explanation.append(f"Sources disagree. Supporting: {_domains(support_counted)}. "
                               f"Contradicting: {_domains(contra_counted)}.")
            return build(S.disputed, "moderate")
        explanation.append("Only weak, conflicting evidence was found.")
        missing.append(needs_more)
        return build(S.unverified, "weak")

    if contra_counted:
        if con_ok:
            explanation.append(f"Credible evidence conflicts with this claim: {_domains(contra_counted)}.")
            return build(S.contradicted, con_strength, correction=_correction(notes, counted_against))
        explanation.append(f"One weaker source conflicts with this claim ({_domains(contra_counted)}); "
                           "that is not enough to call it contradicted.")
        missing.append(needs_more)
        return build(S.unverified, "weak")

    if support_counted:
        if is_universal(claim):
            explanation.append("Sources agree with parts of this statement, but a universal or "
                               "negative claim cannot be confirmed by search results: not finding "
                               "a counterexample does not prove none exists.")
            missing.append("A universal or negative claim needs an exhaustive, authoritative source.")
            return build(S.unverified, "weak")
        if sup_ok:
            explanation.append(f"Supported by {_domains(support_counted)}. No contradicting "
                               "evidence was found in the sources checked.")
            if all(e.source_type == "user_provided" for e in support_counted):
                explanation.append("All supporting sources were provided by you, not found independently.")
            return build(S.supported, sup_strength)
        if not withheld:
            explanation.append(f"Only {_domains(support_counted)} supports this claim.")
            missing.append(needs_more)
        return build(S.unverified, "weak")

    if notes.calculations and all(c.consistent and c.pure_math for c in notes.calculations) \
            and "deterministic_calculation" in notes.methods and not broken:
        calc = notes.calculations[0]
        explanation.append(f"Checked by calculation: {calc.expression} = {calc.computed_value}.")
        return build(S.supported, "strong")

    if notes.calculations:
        explanation.append("The arithmetic is internally consistent, but the figures it uses "
                           "were not independently verified.")
    elif investigated:
        explanation.append("No source found during this check adequately supports or contradicts "
                           "this claim.")
    else:
        explanation.append("This claim was not researched in this run.")
    if not missing:
        missing.append("No independent evidence was retrieved for this claim.")
    return build(S.unverified, "weak" if support or contra else "none")


def _correction(notes: ClaimNotes, domains: set[str] | None) -> str | None:
    """The first correction from a counted source (domains), or from a calculation (None)."""
    for item in notes.corrections:
        text, domain = (item, None) if isinstance(item, str) else item
        if (domain is None) if domains is None else (domain in domains):
            return text
    return None
