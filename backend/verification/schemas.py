"""Versioned Level 1 contracts. Offsets count Unicode code points, end-exclusive."""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimType(str, Enum):
    factual = "factual"
    numerical = "numerical"
    logical = "logical"
    historical = "historical"
    time_sensitive = "time_sensitive"
    comparative = "comparative"
    business_market = "business_market"
    scientific = "scientific"
    predictive = "predictive"
    subjective_normative = "subjective_normative"
    negative_universal = "negative_universal"
    not_independently_checkable = "not_independently_checkable"


class VerificationStatus(str, Enum):
    supported = "SUPPORTED"
    contradicted = "CONTRADICTED"
    disputed = "DISPUTED"
    unverified = "UNVERIFIED"
    not_checkable = "NOT CHECKABLE"


class TextSpan(StrictModel):
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("Span end must exceed start.")
        return self


class Scope(StrictModel):
    dates: list[str] = Field(default_factory=list)
    geographical_scope: list[str] = Field(default_factory=list)


class ExtractionRequest(StrictModel):
    response_text: str = Field(min_length=1, max_length=24000)
    original_question: str | None = Field(default=None, max_length=8000)
    mode: Literal["quick", "deep"] = "quick"

    @model_validator(mode="after")
    def nonblank(self):
        # Preserve offsets: validate whitespace without normalizing the source.
        if not self.response_text.strip():
            raise ValueError("response_text must contain non-whitespace text.")
        return self


class ClaimCandidate(StrictModel):
    exact_text: str = Field(min_length=1)
    text_span: TextSpan
    claim_type: ClaimType
    context: str = Field(min_length=1)
    qualifiers: list[str] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)
    objectively_checkable: bool = Field(strict=True)
    limitations: list[str] = Field(default_factory=list)


class Claim(ClaimCandidate):
    claim_id: str
    verification_status: VerificationStatus
    # Evidence retrieval/schema is introduced in Level 2. Empty lists are the
    # only valid Level 1 value, so an extractor cannot smuggle in evidence.
    evidence: list = Field(default_factory=list, max_length=0)
    contradictions: list = Field(default_factory=list, max_length=0)
    explanation: str
    suggested_correction: None = None
    checked_at: None = None

    @model_validator(mode="after")
    def extraction_cannot_verify(self):
        expected = (VerificationStatus.unverified if self.objectively_checkable
                    else VerificationStatus.not_checkable)
        if self.verification_status != expected:
            raise ValueError("Extraction alone cannot assign an evidence verdict.")
        return self


class OmittedSegment(StrictModel):
    text_span: TextSpan
    reason: str


class CandidateBatch(StrictModel):
    claims: list[ClaimCandidate]
    omitted_segments: list[OmittedSegment] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ClaimSummary(StrictModel):
    total_extracted: int = Field(ge=0)
    supported: Literal[0] = 0
    contradicted: Literal[0] = 0
    disputed: Literal[0] = 0
    unverified: int = Field(ge=0)
    not_checkable: int = Field(ge=0)
    investigated: Literal[0] = 0


class Usage(StrictModel):
    duration_ms: float = Field(ge=0)
    model_tokens: Literal[0] = 0
    search_calls: Literal[0] = 0
    estimated_cost_usd: Literal[0] = 0


class ExtractionResponse(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    mode: Literal["quick", "deep"]
    response_text: str
    original_question: str | None
    extraction_status: Literal["completed", "partial", "failed"]
    method: str
    extracted_at: datetime
    claims: list[Claim]
    summary: ClaimSummary
    limitations: list[str]
    incomplete_checks: list[str]
    omitted_segments: list[OmittedSegment]
    usage: Usage
