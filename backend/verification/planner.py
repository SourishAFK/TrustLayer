"""Verification planner: which claims get researched, and in what order.

Research (search, page reads, model calls) costs money and time, so it is
rationed. Risky claims go first: money and numbers, market and competitor
statements, universal claims, time-sensitive facts. Free deterministic checks
(math, certainty language) already ran on every claim before planning, so a
claim that pure arithmetic settles is not sent to the web at all.
"""

import re

from backend.verification.budget import Limits
from backend.verification.contracts import Findings, Plan
from backend.verification.report import VerificationRequest
from backend.verification.schemas import Claim, ClaimType

PRIORITY = {
    ClaimType.numerical: 0, ClaimType.business_market: 0,
    ClaimType.negative_universal: 1, ClaimType.time_sensitive: 1,
    ClaimType.comparative: 2, ClaimType.scientific: 2,
    ClaimType.historical: 3, ClaimType.factual: 3, ClaimType.logical: 4,
}
MARKET = re.compile(
    r"\b(?:(?:no|zero|not (?:a single|one)) (?:\w+\s+){0,2}(?:competitors?|competition|alternatives?|rivals?|"
    r"compan(?:y|ies))"
    r"|(?:the )?(?:only|first|sole) (?:\w+\s+){0,2}(?:company|startup|product|platform|tool|solution|service|"
    r"provider|vendor|supplier|maker)"
    r"|nobody else|no one else|no other (?:company|product|tool|startup)|unrivall?ed|unmatched"
    r"|unique in the market|market (?:size|leader)|\btam\b)",
    re.I,
)


def is_market_claim(claim: Claim) -> bool:
    return claim.objectively_checkable and bool(MARKET.search(claim.exact_text))


def make_plan(claims: list[Claim], request: VerificationRequest, limits: Limits,
              findings: Findings, *, can_research: bool, mode_label: str) -> Plan:
    plan = Plan()
    settled = {cid for cid, notes in findings.claims.items()
               if notes.calculations and all(c.pure_math for c in notes.calculations)}
    ranked = sorted((c for c in claims if c.objectively_checkable and c.claim_id not in settled),
                    key=lambda c: (PRIORITY.get(c.claim_type, 3), c.text_span.start))
    for claim in ranked:
        if not can_research:
            plan.deferred[claim.claim_id] = ("No evidence source was available for this run (no "
                                             "permitted search provider and no supplied sources).")
        elif len(plan.evidence) < limits.max_claims_investigated:
            plan.evidence.append(claim.claim_id)
        else:
            plan.deferred[claim.claim_id] = (f"{mode_label} researches at most "
                                             f"{limits.max_claims_investigated} claims; this one had "
                                             "lower priority.")
    if request.mode == "deep" and can_research:
        plan.market = [c.claim_id for c in claims if is_market_claim(c)]
    for claim_id, reason in plan.deferred.items():
        findings.note(claim_id, missing=f"Not researched: {reason}")
    return plan
