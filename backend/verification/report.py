"""Schema 2.0: the evidence-backed verification report (Levels 2-5).

This file is the API contract. The rules that protect a reader from a false
"SUPPORTED" live here, so no engine, model output or later refactor can skip them:

* SUPPORTED needs quoted evidence from a fetched source, or a passing
  deterministic calculation on a claim that is pure arithmetic.
* A universal or negative claim ("no competitors") is never SUPPORTED by search.
* Every evidence quote is an exact slice of the passage it came from.
* Summary counts must equal the per-claim verdicts. There is no truth score.

Offsets are Unicode code points, end-exclusive (same as schema 1.0).
"""

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from backend.verification.schemas import (
    ClaimType,
    OmittedSegment,
    Scope,
    StrictModel,
    TextSpan,
    VerificationStatus,
)

Mode = Literal["quick", "deep"]
RunStatus = Literal["completed", "partial", "skipped", "failed", "not_applicable"]
SourceType = Literal["primary", "official", "academic", "reference", "news", "user_provided", "other"]
Retrieval = Literal["search", "citation", "user_url", "user_document"]
Severity = Literal["info", "warning", "critical"]
Url = Annotated[str, Field(min_length=8, max_length=2048)]


# --------------------------------------------------------------------------- #
# Request
# --------------------------------------------------------------------------- #

class SourceDocument(StrictModel):
    """Text the user supplies as a source. Never sent to an AI provider unless
    the request sets share_documents_with_ai."""
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=50_000)


class VerificationRequest(StrictModel):
    response_text: str = Field(min_length=1, max_length=24_000)
    original_question: str | None = Field(default=None, max_length=8_000)
    mode: Mode = "quick"
    source_urls: list[Url] = Field(default_factory=list, max_length=5)
    documents: list[SourceDocument] = Field(default_factory=list, max_length=3)
    # Which model wrote the response (e.g. "gemini-2.5-flash", "gpt-5", "claude").
    # Used to prefer a judge from a different model family.
    source_model: str | None = Field(default=None, max_length=80)
    # Domain rules for the legacy sycophancy scorer (unchanged adapters).
    domain: Literal["general", "fintech", "customer_service"] = "general"
    # Consent switches. Claim text goes to search/AI providers only when allowed.
    allow_web_search: bool = True
    allow_ai_processing: bool = True
    share_documents_with_ai: bool = False

    @model_validator(mode="after")
    def bounded_and_nonblank(self):
        if not self.response_text.strip():
            raise ValueError("response_text must contain non-whitespace text.")
        if any(not u.lower().startswith(("http://", "https://")) for u in self.source_urls):
            raise ValueError("source_urls must be http(s) URLs.")
        if sum(len(d.text) for d in self.documents) > 100_000:
            raise ValueError("Documents may total at most 100,000 characters.")
        return self


# --------------------------------------------------------------------------- #
# Evidence and per-claim results
# --------------------------------------------------------------------------- #

class Evidence(StrictModel):
    """One quoted passage from one source, judged to support or contradict one claim."""
    evidence_id: str
    claim_id: str
    stance: Literal["supports", "contradicts"]
    url: Url
    title: str | None = Field(default=None, max_length=300)
    publisher: str | None = Field(default=None, max_length=200)
    domain: str = Field(min_length=1, max_length=253)
    source_type: SourceType
    retrieval: Retrieval
    provider: str
    published_at: datetime | None = None
    accessed_at: datetime
    passage: str = Field(min_length=1, max_length=1500)
    quote: str = Field(min_length=1, max_length=800)
    method: str
    # Short model-written reason. Untrusted text: displayed, never acted on.
    rationale: str | None = Field(default=None, max_length=600)

    @field_validator("published_at", "accessed_at")
    @classmethod
    def assume_utc(cls, value: datetime | None) -> datetime | None:
        # Sources often omit the zone; comparing naive and aware datetimes would crash.
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

    @model_validator(mode="after")
    def quote_comes_from_passage(self):
        if self.quote not in self.passage:
            raise ValueError("Evidence quote must be an exact slice of its passage.")
        return self


class SourceRef(StrictModel):
    """A source that was looked at but did not become evidence, kept for transparency."""
    url: Url
    title: str | None = Field(default=None, max_length=300)
    domain: str
    note: str


class Calculation(StrictModel):
    kind: Literal["arithmetic", "percentage_of", "percent_change", "multiple", "unit_conversion", "runway"]
    expression: str
    stated_value: str
    computed_value: str
    consistent: bool
    tolerance: str
    # True only when the claim asserts nothing but the calculation itself, so the
    # math alone can settle it. "Revenue grew 50% to $30M" is not pure math.
    pure_math: bool
    note: str


class CheckRecord(StrictModel):
    engine: str
    status: RunStatus
    detail: str


class Freshness(StrictModel):
    time_sensitive: bool
    claim_dates: list[str] = Field(default_factory=list)
    newest_evidence_at: datetime | None = None
    checked_at: datetime
    may_have_changed: bool
    note: str


class VerifiedClaim(StrictModel):
    # Extraction fields (schema 1.0)
    claim_id: str
    exact_text: str = Field(min_length=1)
    text_span: TextSpan
    claim_type: ClaimType
    context: str
    qualifiers: list[str] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)
    objectively_checkable: bool = Field(strict=True)
    # Verdict
    verification_status: VerificationStatus
    evidence_strength: Literal["strong", "moderate", "weak", "none"]
    evidence: list[Evidence] = Field(default_factory=list)
    contradictions: list[Evidence] = Field(default_factory=list)
    calculations: list[Calculation] = Field(default_factory=list)
    related_sources: list[SourceRef] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    verification_methods: list[str] = Field(default_factory=list)
    checks: list[CheckRecord] = Field(default_factory=list)
    explanation: str
    missing_evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    suggested_correction: str | None = None
    certainty_flags: list[str] = Field(default_factory=list)
    freshness: Freshness | None = None
    investigated: bool
    checked_at: datetime | None = None

    @model_validator(mode="after")
    def verdict_needs_evidence(self):
        status = VerificationStatus(self.verification_status)
        if any(e.claim_id != self.claim_id for e in self.evidence + self.contradictions):
            raise ValueError("Evidence must belong to its claim.")
        if any(e.stance != "supports" for e in self.evidence) or any(
            e.stance != "contradicts" for e in self.contradictions
        ):
            raise ValueError("Supporting and contradicting evidence must not be mixed.")
        if (status == VerificationStatus.not_checkable) != (not self.objectively_checkable):
            raise ValueError("NOT CHECKABLE is used exactly for statements that are not objectively checkable.")
        if self.investigated == (self.checked_at is None):
            raise ValueError("checked_at is set exactly when a claim was investigated.")
        calc_failed = any(not c.consistent for c in self.calculations)
        calc_settles = (
            bool(self.calculations)
            and all(c.consistent and c.pure_math for c in self.calculations)
            and "deterministic_calculation" in self.verification_methods
        )
        decisive = status in (VerificationStatus.supported, VerificationStatus.contradicted,
                              VerificationStatus.disputed)
        if decisive and (not self.investigated or self.evidence_strength == "none"):
            raise ValueError("A decisive verdict requires an investigation and evidence strength.")
        if status == VerificationStatus.supported:
            if self.contradictions or calc_failed:
                raise ValueError("SUPPORTED cannot carry contradicting evidence or a failed calculation.")
            if not (self.evidence or calc_settles):
                raise ValueError("SUPPORTED requires quoted evidence or a passing pure calculation.")
            if self.claim_type == ClaimType.negative_universal:
                raise ValueError("A universal or negative claim cannot be SUPPORTED by retrieval.")
        if status == VerificationStatus.contradicted and not (self.contradictions or calc_failed):
            raise ValueError("CONTRADICTED requires contradicting evidence or a failed calculation.")
        if status == VerificationStatus.disputed and not (self.evidence and self.contradictions):
            raise ValueError("DISPUTED requires both supporting and contradicting evidence.")
        return self


# --------------------------------------------------------------------------- #
# Response-level sections
# --------------------------------------------------------------------------- #

CitationStatus = Literal[
    "supports",                # page reachable and supports the attached claim(s)
    "does_not_support",        # reachable, but does not support what it is attached to
    "contradicts",             # reachable and conflicts with the attached claim(s)
    "accessible_unassessed",   # reachable; support could not be assessed (no AI/budget)
    "inaccessible",            # 401/403/paywall/unsupported format
    "broken",                  # 404/410/5xx, or the domain does not resolve
    "invalid_or_fabricated",   # placeholder/reserved domain, unregistered DOI, malformed
    "blocked",                 # private address, disallowed port or robots.txt
    "not_checked",             # out of budget, consent not given, or no URL/DOI
]


class CitationCheck(StrictModel):
    citation_id: str
    raw_text: str
    text_span: TextSpan
    url: str | None = None
    doi: str | None = None
    claim_ids: list[str] = Field(default_factory=list)
    status: CitationStatus
    http_status: int | None = None
    final_url: str | None = None
    title: str | None = None
    published_at: datetime | None = None
    outdated: bool | None = None
    quote_check: Literal["verbatim", "not_found", "not_applicable"] = "not_applicable"
    exaggeration_flags: list[str] = Field(default_factory=list)
    explanation: str
    checked_at: datetime | None = None


class Signal(StrictModel):
    """A response-level observation (not a verdict): certainty language, praise,
    internal contradictions, suspicious source text, misleading quotes..."""
    signal_id: str
    engine: str
    kind: str
    severity: Severity
    text: str = Field(max_length=1000)
    text_span: TextSpan | None = None
    claim_ids: list[str] = Field(default_factory=list)
    explanation: str


class SycophancySection(StrictModel):
    """Behavioral assessment, kept separate from factual verdicts by design."""
    status: RunStatus
    method: str
    score: int | None = Field(default=None, ge=0, le=100)
    verdict: Literal["HONEST", "BORDERLINE", "SYCOPHANTIC"] | None = None
    intent_gap: float | None = Field(default=None, ge=0, le=1)
    response_honesty: float | None = Field(default=None, ge=0, le=1)
    indicators: list[str] = Field(default_factory=list)
    suggested_honest_alternative: str | None = None
    signal_ids: list[str] = Field(default_factory=list)
    note: str


class SubQuestion(StrictModel):
    text: str
    coverage: Literal["addressed", "partially_addressed", "not_addressed", "unclear"]
    note: str


class OmissionItem(StrictModel):
    kind: Literal["unanswered_subquestion", "missing_qualification", "missing_limitation",
                  "unaddressed_constraint", "incomplete_comparison"]
    description: str
    question_quote: str | None = None


class CompletenessSection(StrictModel):
    status: Literal["completed", "partial", "limited", "skipped", "failed"]
    method: str
    subquestions: list[SubQuestion] = Field(default_factory=list)
    missing: list[OmissionItem] = Field(default_factory=list)
    note: str


class Competitor(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    relation: Literal["direct", "indirect", "substitute"]
    url: Url
    domain: str
    quote: str = Field(min_length=1, max_length=800)  # exact text from the source naming it
    description: str
    differentiation: str | None = None

    @model_validator(mode="after")
    def named_in_quote(self):
        if self.name.casefold() not in self.quote.casefold():
            raise ValueError("A competitor must be named in its source quote.")
        return self


class AcademicWork(StrictModel):
    title: str
    url: Url
    year: int | None = None
    venue: str | None = None
    note: str


class MarketInvestigation(StrictModel):
    investigation_id: str
    claim_ids: list[str]
    status: RunStatus
    method: str
    product_summary: str | None = None
    customers: list[str] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    competitors: list[Competitor] = Field(default_factory=list)
    academic_work: list[AcademicWork] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)
    search_limitations: list[str] = Field(min_length=1)
    conclusion: str


class EngineRun(StrictModel):
    engine: str
    status: RunStatus
    duration_ms: float = Field(ge=0)
    detail: str


class BudgetLimits(StrictModel):
    max_seconds: float
    max_search_calls: int
    max_page_fetches: int
    max_model_calls: int
    max_model_tokens: int
    max_cost_usd: float
    max_claims_investigated: int


class UsageReport(StrictModel):
    duration_ms: float = Field(ge=0)
    model_calls: int = Field(ge=0)
    model_input_tokens: int = Field(ge=0)
    model_output_tokens: int = Field(ge=0)
    search_calls: int = Field(ge=0)
    pages_fetched: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)
    cost_basis: str
    limits: BudgetLimits
    exhausted: list[str] = Field(default_factory=list)


class PrivacyNotice(StrictModel):
    web_search_used: bool
    search_providers: list[str] = Field(default_factory=list)
    ai_providers: list[str] = Field(default_factory=list)
    documents_sent_to_ai: bool
    stored: bool
    retention_hours: int = Field(ge=0)
    note: str


class ExtractionInfo(StrictModel):
    method: str
    status: Literal["completed", "partial", "failed"]
    omitted_segments: list[OmittedSegment] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ReportSummary(StrictModel):
    total_extracted: int = Field(ge=0)
    supported: int = Field(ge=0)
    contradicted: int = Field(ge=0)
    disputed: int = Field(ge=0)
    unverified: int = Field(ge=0)
    not_checkable: int = Field(ge=0)
    investigated: int = Field(ge=0)
    checks_incomplete: int = Field(ge=0)
    signals_critical: int = Field(ge=0)
    signals_warning: int = Field(ge=0)


class VerificationReport(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    report_id: str
    mode: Mode
    status: Literal["completed", "partial", "failed"]
    response_text: str
    original_question: str | None
    source_model: str | None
    created_at: datetime
    completed_at: datetime
    extraction: ExtractionInfo
    claims: list[VerifiedClaim]
    citations: list[CitationCheck]
    signals: list[Signal]
    sycophancy: SycophancySection
    completeness: CompletenessSection
    market: list[MarketInvestigation]
    engines: list[EngineRun]
    summary: ReportSummary
    limitations: list[str]
    incomplete_checks: list[str]
    usage: UsageReport
    privacy: PrivacyNotice

    @model_validator(mode="after")
    def internally_consistent(self):
        ids = [c.claim_id for c in self.claims]
        if len(set(ids)) != len(ids):
            raise ValueError("Claim ids must be unique.")
        last_end = 0
        for claim in self.claims:
            span = claim.text_span
            if span.start < last_end or self.response_text[span.start:span.end] != claim.exact_text:
                raise ValueError("Claim spans must be ordered exact slices of the response.")
            last_end = span.end
        evidence_ids = [e.evidence_id for c in self.claims for e in c.evidence + c.contradictions]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("Evidence ids must be unique.")
        known = set(ids)
        referenced = [cid for x in (*self.citations, *self.signals) for cid in x.claim_ids]
        referenced += [cid for m in self.market for cid in m.claim_ids]
        if not set(referenced) <= known:
            raise ValueError("Sections may only reference extracted claims.")
        counts = {s: 0 for s in VerificationStatus}
        for claim in self.claims:
            counts[VerificationStatus(claim.verification_status)] += 1
        s = self.summary
        expected = (len(self.claims), counts[VerificationStatus.supported],
                    counts[VerificationStatus.contradicted], counts[VerificationStatus.disputed],
                    counts[VerificationStatus.unverified], counts[VerificationStatus.not_checkable],
                    sum(c.investigated for c in self.claims), len(self.incomplete_checks),
                    sum(x.severity == "critical" for x in self.signals),
                    sum(x.severity == "warning" for x in self.signals))
        actual = (s.total_extracted, s.supported, s.contradicted, s.disputed, s.unverified,
                  s.not_checkable, s.investigated, s.checks_incomplete, s.signals_critical,
                  s.signals_warning)
        if expected != actual:
            raise ValueError("Summary counts must match the claims, checks and signals.")
        if self.status == "failed" and (s.supported or s.contradicted or s.disputed):
            raise ValueError("A failed run cannot carry decisive verdicts.")
        return self


class ProgressEvent(StrictModel):
    """One line of the /v1/verify/stream NDJSON feed. Never carries secrets."""
    type: Literal["stage", "claim", "source", "warning"]
    stage: str
    status: Literal["started", "progress", "completed", "skipped", "failed"]
    message: str = Field(max_length=500)
    claim_id: str | None = None
    elapsed_ms: float = Field(ge=0)
