"""
main.py — TrustLayer API (FastAPI).

Thin HTTP layer over the core scorer. The frontend (and, later, the B2B SDK)
talks to this — never to Gemini directly. All scoring logic stays in scorer.py;
all domain knowledge stays in domain_rules.py. This file only does transport:
request validation, calling the scorer, and mapping errors to HTTP status codes.

Run:  python -m uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import base64
import binascii
import os
from functools import lru_cache
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.domain_rules import FintechDomain
from backend.scorer import ScorerError, SycophancyResult, SycophancyScorer

app = FastAPI(
    title="TrustLayer API",
    version="0.1.0",
    description="Detects sycophantic AI behavior in high-stakes fintech decisions.",
)

# Permissive CORS for local dev / future JS SDK. Tighten for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def get_scorer() -> SycophancyScorer:
    """Build the scorer once, wired with the fintech domain. Cached as a singleton.

    Reads optional GEMINI_API_KEY_2 and GEMINI_FALLBACK_MODELS from env to build
    a rotation chain — on quota exhaustion (429) the scorer advances to the next
    (key, model) slot automatically, transparent to all callers.
    """
    fallback_keys = [k for k in [os.getenv("GEMINI_API_KEY_2")] if k]
    raw_models = os.getenv("GEMINI_FALLBACK_MODELS", "")
    fallback_models = [m.strip() for m in raw_models.split(",") if m.strip()] or None
    return SycophancyScorer(
        default_domain=FintechDomain(),
        fallback_keys=fallback_keys,
        fallback_models=fallback_models,
    )


# --------------------------------------------------------------------------- #
# Request model (response model is SycophancyResult from the core)
# --------------------------------------------------------------------------- #

# Gemini-supported binary attachment types (images + PDF). Office/text docs are
# extracted to text by the frontend and arrive inside `context`.
ALLOWED_ATTACHMENT_MIMES = {
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp",
    "application/pdf",
}
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024  # 8 MB per file
MAX_ATTACHMENTS = 6


class Attachment(BaseModel):
    mime_type: str = Field(..., description="e.g. image/png, application/pdf")
    data: str = Field(..., description="Base64-encoded file bytes.")
    name: Optional[str] = None


class ScoreRequest(BaseModel):
    query: str = Field(..., min_length=1, description="The user's question to the AI.")
    ai_response: str = Field(..., min_length=1, description="The AI's answer to score.")
    context: Optional[str] = Field(
        default=None, description="Optional underlying facts/data to judge against."
    )
    attachments: list[Attachment] = Field(
        default_factory=list, description="Images/PDFs as extra factual context."
    )


def _decode_attachments(attachments: list[Attachment]) -> list[tuple[bytes, str]]:
    """Validate + decode base64 attachments into (bytes, mime_type) tuples."""
    if len(attachments) > MAX_ATTACHMENTS:
        raise HTTPException(400, f"Too many attachments (max {MAX_ATTACHMENTS}).")
    decoded: list[tuple[bytes, str]] = []
    for att in attachments:
        mime = att.mime_type.lower().strip()
        if mime not in ALLOWED_ATTACHMENT_MIMES:
            raise HTTPException(400, f"Unsupported attachment type: {att.mime_type}")
        try:
            raw = base64.b64decode(att.data, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, f"Attachment '{att.name or mime}' is not valid base64.")
        if not raw:
            continue
        if len(raw) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                400, f"Attachment '{att.name or mime}' exceeds "
                     f"{MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB."
            )
        decoded.append((raw, mime))
    return decoded


# --------------------------------------------------------------------------- #
# Error mapping
# --------------------------------------------------------------------------- #

def _http_from_scorer_error(exc: ScorerError) -> HTTPException:
    msg = str(exc)
    if "GEMINI_API_KEY" in msg:
        return HTTPException(500, "Server is missing GEMINI_API_KEY.")
    if "must not be empty" in msg:
        return HTTPException(400, msg)
    if "All API quota exhausted" in msg:
        return HTTPException(429, "All Gemini quota exhausted across all keys. Try again later.")
    if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
        return HTTPException(429, "Gemini free-tier quota exceeded. Try again later.")
    if "UNAVAILABLE" in msg or "503" in msg:
        return HTTPException(503, "Gemini is temporarily overloaded. Try again shortly.")
    return HTTPException(502, f"Scoring failed upstream: {msg}")


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.get("/")
def root() -> dict:
    return {
        "service": "TrustLayer",
        "tagline": "Confidence is not Trust.",
        "phase": 1,
        "endpoint": "POST /score",
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": get_scorer().model_name}


@app.post("/score", response_model=SycophancyResult)
def score(req: ScoreRequest) -> SycophancyResult:
    attachments = _decode_attachments(req.attachments)
    try:
        return get_scorer().score(
            query=req.query,
            ai_response=req.ai_response,
            context=req.context,
            attachments=attachments,
        )
    except ScorerError as exc:
        raise _http_from_scorer_error(exc)
