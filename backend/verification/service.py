"""Validate extraction boundaries, apply limits, and build an honest report."""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.verification.extractor import ClaimExtractor, RuleClaimExtractor
from backend.verification.schemas import (
    CandidateBatch,
    Claim,
    ClaimSummary,
    ExtractionRequest,
    ExtractionResponse,
    OmittedSegment,
    TextSpan,
    Usage,
    VerificationStatus,
)

logger = logging.getLogger(__name__)
BASELINE_NOTE = "English rule-based extraction is a baseline: it can miss claims, merge clauses or misclassify them."
INCOMPLETE_CHECKS = [
    "Independent evidence retrieval and factual verification have not run (Level 2).",
    "Citation validation has not run (Level 2).",
    "Numerical, logical, market and freshness checks have not run (Level 3).",
    "Sycophancy has not run in this report; the existing /score service remains separate.",
    "Completeness and omission analysis have not run.",
]


def claim_limit() -> int:
    value = int(os.getenv("TRUSTLAYER_CLAIM_MAX_CLAIMS", "80"))
    if not 1 <= value <= 200:
        raise ValueError("TRUSTLAYER_CLAIM_MAX_CLAIMS must be between 1 and 200.")
    return value


def _validate_batch(batch: CandidateBatch, text: str) -> None:
    previous_end = 0
    for candidate in batch.claims:
        span = candidate.text_span
        if (span.start < previous_end or span.end > len(text)
                or text[span.start:span.end] != candidate.exact_text
                or candidate.exact_text not in candidate.context
                or candidate.context not in text):
            raise ValueError("Extractor returned an invalid source span or context.")
        previous_end = span.end
    for omission in batch.omitted_segments:
        if omission.text_span.end > len(text):
            raise ValueError("Extractor returned an invalid omitted span.")


@dataclass
class ExtractionResult:
    status: str  # completed | partial | failed
    method: str
    claims: list[Claim] = field(default_factory=list)
    omitted_segments: list[OmittedSegment] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def extract_claims(text: str, extractor: ClaimExtractor | None = None) -> ExtractionResult:
    """Run an extractor and keep only validated, exactly-located claims.

    Shared by the Level 1 endpoint and the verification pipeline. Raises
    ValueError only for invalid server configuration; extractor failures become
    a visible failed result with no claims.
    """
    extractor = extractor or RuleClaimExtractor()
    limit = claim_limit()
    result = ExtractionResult(status="completed", method=extractor.method)
    try:
        raw_batch = extractor.extract(text)
        batch = CandidateBatch.model_validate(
            raw_batch.model_dump() if isinstance(raw_batch, CandidateBatch) else raw_batch
        )
        _validate_batch(batch, text)
        result.omitted_segments = batch.omitted_segments.copy()
        result.limitations.extend(batch.limitations)
        for index, candidate in enumerate(batch.claims[:limit], start=1):
            result.claims.append(Claim(
                **candidate.model_dump(), claim_id=f"c{index}",
                verification_status=(VerificationStatus.unverified if candidate.objectively_checkable
                                     else VerificationStatus.not_checkable),
                explanation=("Identified as potentially checkable. No evidence investigation has run."
                             if candidate.objectively_checkable else
                             "Classified as opinion, prediction or a statement not independently checkable now; review the classification."),
            ))
        if len(batch.claims) > limit:
            first = batch.claims[limit].text_span.start
            result.omitted_segments.append(OmittedSegment(
                text_span=TextSpan(start=first, end=len(text)),
                reason=f"Claim limit ({limit}) reached; remaining claims were not returned.",
            ))
            result.limitations.append(f"Claim limit ({limit}) reached. Extraction is incomplete.")
        if result.omitted_segments or any(c.limitations for c in result.claims):
            result.status = "partial"
        if not result.claims:
            result.limitations.append("No claims identified. This does not establish that the response contains no claims.")
    except Exception as exc:
        # Never echo untrusted source/provider text into errors or logs.
        logger.warning("Claim extraction failed (%s)", type(exc).__name__)
        result = ExtractionResult(status="failed", method=extractor.method, limitations=[
            "Extraction failed validation or execution. No claim verdicts were produced."])
    return result


def extract_response(request: ExtractionRequest, extractor: ClaimExtractor | None = None) -> ExtractionResponse:
    started = time.perf_counter()
    result = extract_claims(request.response_text, extractor)
    limitations = [
        BASELINE_NOTE,
        "Counts describe extracted statements, not guaranteed verification coverage or a truth score.",
        "No independent evidence was retrieved. No factual claims were verified.",
    ]
    if not request.original_question or not request.original_question.strip():
        limitations.append("Original question not supplied; completeness assessment would be limited.")
    if request.mode == "deep":
        limitations.append("Deep Investigation is not implemented yet; this request ran extraction only.")
    limitations.extend(result.limitations)
    unverified = sum(c.objectively_checkable for c in result.claims)
    return ExtractionResponse(
        mode=request.mode, response_text=request.response_text,
        original_question=request.original_question, extraction_status=result.status,
        method=result.method, extracted_at=datetime.now(timezone.utc),
        claims=result.claims,
        summary=ClaimSummary(total_extracted=len(result.claims), unverified=unverified,
                             not_checkable=len(result.claims) - unverified),
        limitations=limitations, incomplete_checks=INCOMPLETE_CHECKS.copy(),
        omitted_segments=result.omitted_segments,
        usage=Usage(duration_ms=round((time.perf_counter() - started) * 1000, 3)),
    )
