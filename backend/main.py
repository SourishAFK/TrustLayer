"""
main.py — TrustLayer API (FastAPI). PHASE 2: developer-facing scoring API.

Thin HTTP layer over the core scorer. The frontend (and the B2B SDK) talk to
this — never to Gemini directly. All scoring logic stays in scorer.py; all
domain knowledge stays in domain_rules.py; all persistence stays in store.py.
This file only does transport: request validation, domain routing, calling the
scorer, timing, usage logging, and mapping errors to HTTP status codes.

Run:  python -m uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import base64
import binascii
import os
import time
from contextlib import asynccontextmanager
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from backend import store
from backend.domain_rules import (
    CustomerServiceDomain,
    FintechDomain,
    GeneralDomain,
)
from backend.scorer import ScorerError, SycophancyScorer


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Best-effort schema init. If the DB is unreachable, scoring still works
    # (usage logging is best-effort); auth/rate-limiting will surface the error.
    try:
        store.init_db()
        print("[startup] DB schema ready.")
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] DB init skipped: {exc}")
    yield
    store.close_pool()


app = FastAPI(
    title="TrustLayer API",
    version="0.2.0",
    description="Detects sycophantic AI behavior — when AI tells you what you want to hear instead of the truth.",
    lifespan=lifespan,
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
    """Build the scorer once. Cached as a singleton.

    The domain is now injected per-request (see DOMAIN_ADAPTERS), so no default
    domain is baked in here. Reads optional GEMINI_API_KEY_2 and
    GEMINI_FALLBACK_MODELS from env to build the (key, model) rotation chain.
    """
    # Collect every extra key: GEMINI_API_KEY_2, _3, _4, ... Each is a separate
    # Google project = its own quota buckets, multiplying free-tier headroom.
    fallback_keys = [k for k in (os.getenv(f"GEMINI_API_KEY_{i}") for i in range(2, 10)) if k]
    raw_models = os.getenv("GEMINI_FALLBACK_MODELS", "")
    fallback_models = [m.strip() for m in raw_models.split(",") if m.strip()] or None
    return SycophancyScorer(
        fallback_keys=fallback_keys,
        fallback_models=fallback_models,
    )


# Per-request domain routing. Pluggable: a new vertical = a new entry here +
# a new adapter in domain_rules.py. The core scorer never changes.
DOMAIN_ADAPTERS = {
    "fintech": FintechDomain(),
    "customer_service": CustomerServiceDomain(),
    "general": GeneralDomain(),
}


# --------------------------------------------------------------------------- #
# Request / response models (Pydantic v2)
# --------------------------------------------------------------------------- #

class DomainName(str, Enum):
    fintech = "fintech"
    customer_service = "customer_service"
    general = "general"


class UnderlyingModel(str, Enum):
    gemini = "gemini"
    gpt = "gpt"
    claude = "claude"


# Gemini-supported binary attachment types (images + PDF). Office/text docs are
# extracted to text by the caller and arrive inside `context`.
ALLOWED_ATTACHMENT_MIMES = {
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp",
    "application/pdf",
}
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB per file
MAX_ATTACHMENTS = 6


class Attachment(BaseModel):
    mime_type: str = Field(..., description="e.g. image/png, application/pdf")
    data: str = Field(..., description="Base64-encoded file bytes.")
    name: Optional[str] = None


class ScoreRequest(BaseModel):
    """Phase 2 scoring request. Accepts `user_query` (canonical) or `query`."""
    model_config = ConfigDict(populate_by_name=True)

    user_query: str = Field(
        ..., min_length=1, max_length=8000,
        validation_alias=AliasChoices("user_query", "query"),
        description="The user's question to the AI.",
    )
    ai_response: str = Field(
        ..., min_length=1, max_length=8000,
        description="The AI's answer to score.",
    )
    domain: DomainName = Field(
        default=DomainName.general,
        description="Which domain rules to apply.",
    )
    underlying_model: Optional[UnderlyingModel] = Field(
        default=None,
        description="The model that produced ai_response. Logged for analytics; "
                    "cross-model scoring arrives in a later phase.",
    )
    user_id: Optional[str] = Field(
        default=None, description="Optional caller-supplied user id (Phase 3 profiles).",
    )
    context: Optional[str] = Field(
        default=None, description="Optional underlying facts/data to judge against.",
    )
    attachments: list[Attachment] = Field(
        default_factory=list, description="Images/PDFs as extra factual context.",
    )


class ScoreResponse(BaseModel):
    sycophancy_score: int = Field(..., ge=0, le=100)
    verdict: str
    indicators: list[str]
    suggested_honest_alternative: str
    intent_gap: float = Field(..., ge=0.0, le=1.0)
    response_honesty: float = Field(..., ge=0.0, le=1.0)
    domain_flagged: bool
    high_stakes: bool
    scoring_model_used: Optional[str]
    processing_time_ms: int
    # Handle for reporting real-world ground truth later via POST /feedback.
    request_id: Optional[int] = None


class FeedbackRequest(BaseModel):
    request_id: int = Field(..., description="The request_id returned by /score.")
    feedback: Optional[str] = Field(
        default=None, description="Free-text correction, e.g. 'verdict was wrong'.",
    )
    outcome: Optional[str] = Field(
        default=None,
        description="What actually happened, e.g. 'human_overrode', 'customer_disputed', 'upheld'.",
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
# Authentication
# --------------------------------------------------------------------------- #

def authenticate(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> dict:
    """Resolve and validate the caller's API key.

    Accepts either `Authorization: Bearer tl_...` (preferred) or `X-API-Key:
    tl_...`. Returns the key record on success; raises 401/503 otherwise.
    """
    key: Optional[str] = None
    if authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()
    elif x_api_key:
        key = x_api_key.strip()

    if not key:
        raise HTTPException(
            401, "Missing API key. Send 'Authorization: Bearer tl_...'.",
        )
    try:
        record = store.validate_key(key)
    except store.StoreError:
        raise HTTPException(503, "Authentication backend unavailable. Try again shortly.")
    if not record:
        raise HTTPException(401, "Invalid or inactive API key.")
    return record


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

_DOCS_PATH = Path(__file__).resolve().parent.parent / "docs" / "index.html"


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    """Serve the developer docs page. Falls back to plain text if the file is missing."""
    try:
        return _DOCS_PATH.read_text(encoding="utf-8")
    except OSError:
        return "<h1>TrustLayer API</h1><p>POST /score — see /info</p>"


@app.get("/info")
def info() -> dict:
    return {
        "service": "TrustLayer",
        "tagline": "Confidence is not Trust.",
        "phase": 2,
        "endpoint": "POST /score",
        "docs": "/",
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": get_scorer().model_name}


@app.post("/score", response_model=ScoreResponse)
def score(req: ScoreRequest, key_record: dict = Depends(authenticate)):
    api_key = key_record["key"]
    daily_limit = key_record["daily_limit"]
    tier = key_record["tier"]

    # Daily rate limit (resets midnight UTC). Counts authenticated requests.
    try:
        rate = store.check_and_increment_rate(api_key, daily_limit)
    except store.StoreError:
        raise HTTPException(503, "Rate-limit backend unavailable. Try again shortly.")
    if not rate["allowed"]:
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limit_exceeded",
                "message": f"{tier.capitalize()} tier limit of {daily_limit} "
                           f"requests/day reached.",
                "reset_at": rate["reset_at"],
            },
        )

    attachments = _decode_attachments(req.attachments)
    adapter = DOMAIN_ADAPTERS[req.domain.value]

    t0 = time.perf_counter()
    try:
        result = get_scorer().score(
            query=req.user_query,
            ai_response=req.ai_response,
            context=req.context,
            domain=adapter,
            attachments=attachments,
        )
    except ScorerError as exc:
        raise _http_from_scorer_error(exc)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    scoring_model = get_scorer().last_model_used
    domain_flagged = req.domain != DomainName.general

    resp = ScoreResponse(
        sycophancy_score=result.sycophancy_score,
        verdict=result.verdict.value,
        indicators=result.sycophancy_indicators,
        suggested_honest_alternative=result.suggested_honest_alternative,
        intent_gap=result.intent_gap.gap_score,
        response_honesty=result.honesty.honesty_score,
        domain_flagged=domain_flagged,
        high_stakes=result.is_high_stakes,
        scoring_model_used=scoring_model,
        processing_time_ms=elapsed_ms,
    )

    # Behavioral dataset — log every scored request (best-effort). Raw text
    # features (query/response/context) are only stored when the key opts in.
    log_inputs = bool(key_record.get("log_inputs"))
    log_id = store.log_usage(
        api_key=api_key,
        domain=req.domain.value,
        underlying_model=req.underlying_model.value if req.underlying_model else None,
        scoring_model_used=scoring_model,
        user_id=req.user_id,
        sycophancy_score=resp.sycophancy_score,
        verdict=resp.verdict,
        intent_gap=resp.intent_gap,
        response_honesty=resp.response_honesty,
        high_stakes=resp.high_stakes,
        processing_time_ms=elapsed_ms,
        user_query=req.user_query if log_inputs else None,
        ai_response=req.ai_response if log_inputs else None,
        context=req.context if log_inputs else None,
        attachment_count=len(attachments),
        indicators=resp.indicators,
        suggested_alternative=resp.suggested_honest_alternative,
    )
    resp.request_id = log_id

    return resp


@app.post("/feedback")
def feedback(req: FeedbackRequest, key_record: dict = Depends(authenticate)) -> dict:
    """Report what actually happened for a previously scored request.

    This is the ground-truth signal that lets a future in-house model surpass
    the current scorer: e.g. outcome='human_overrode' or feedback='verdict wrong'.
    """
    try:
        updated = store.record_feedback(req.request_id, req.feedback, req.outcome)
    except store.StoreError:
        raise HTTPException(503, "Feedback backend unavailable. Try again shortly.")
    if not updated:
        raise HTTPException(404, f"No scored request with id {req.request_id}.")
    return {"ok": True, "request_id": req.request_id}


# --------------------------------------------------------------------------- #
# Public chat (TrustLayer Chat frontend) — generation + verification in one call.
# The static frontend holds no keys: Gemini runs here, scoring runs in-process.
# Identity comes from TRUSTLAYER_CHAT_KEY env (a normal tl_ key, so the existing
# rate limiter + logging gates apply); without it, an in-memory daily cap guards.
# --------------------------------------------------------------------------- #

class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(default="", max_length=8000)
    image_b64: Optional[str] = None
    image_mime: Optional[str] = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)


class ChatResponse(BaseModel):
    reply: str
    original: Optional[str] = None
    replaced: bool = False
    verdict: Optional[str] = None
    score: Optional[int] = None
    request_id: Optional[int] = None
    unverified: bool = False
    processing_time_ms: int = 0


class ChatFeedbackRequest(BaseModel):
    request_id: int
    outcome: str = Field(..., max_length=40)


_PUBLIC_CHAT_FALLBACK_LIMIT = 500
_public_chat_counter = {"day": None, "count": 0}


def _public_chat_allowed() -> bool:
    """In-memory daily cap used only when TRUSTLAYER_CHAT_KEY isn't configured."""
    import datetime as _dt
    today = _dt.datetime.now(_dt.timezone.utc).date()
    if _public_chat_counter["day"] != today:
        _public_chat_counter["day"] = today
        _public_chat_counter["count"] = 0
    _public_chat_counter["count"] += 1
    return _public_chat_counter["count"] <= _PUBLIC_CHAT_FALLBACK_LIMIT


def _decode_chat_image(msg: ChatMessage) -> Optional[bytes]:
    if not msg.image_b64:
        return None
    try:
        raw = base64.b64decode(msg.image_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Image is not valid base64.")
    if len(raw) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(400, "Image too large (max 10 MB).")
    return raw or None


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    from backend.chat import generate_chat_reply

    # --- identity + rate limiting ---
    chat_key = os.getenv("TRUSTLAYER_CHAT_KEY")
    key_record = None
    if chat_key:
        try:
            key_record = store.validate_key(chat_key)
        except store.StoreError:
            key_record = None
    if key_record:
        try:
            rate = store.check_and_increment_rate(chat_key, key_record["daily_limit"])
            if not rate["allowed"]:
                return JSONResponse(  # type: ignore[return-value]
                    status_code=429,
                    content={"error": "rate_limit_exceeded",
                             "message": "The chat's daily budget is used up. "
                                        "It resets at midnight UTC.",
                             "reset_at": rate["reset_at"]},
                )
        except store.StoreError:
            pass
    elif not _public_chat_allowed():
        raise HTTPException(429, "The chat's daily budget is used up. Try tomorrow.")

    # --- decode messages (images included) ---
    msgs: list[dict] = []
    for m in req.messages:
        msgs.append({
            "role": m.role, "content": m.content,
            "image_bytes": _decode_chat_image(m),
            "image_mime": m.image_mime,
        })
    last_user = next((m for m in reversed(msgs) if m["role"] == "user"), None)
    if last_user is None or not (last_user["content"] or last_user["image_bytes"]):
        raise HTTPException(400, "The last user message is empty.")

    t0 = time.perf_counter()

    # --- 1) generate naturally ---
    try:
        reply = generate_chat_reply(msgs)
    except Exception:
        raise HTTPException(503, "The model is overloaded right now — try again shortly.")

    # --- 2) verify honesty in-process (fail open, never break the chat) ---
    resp = ChatResponse(reply=reply, unverified=True)
    try:
        attachments = None
        if last_user["image_bytes"]:
            attachments = [(last_user["image_bytes"],
                            last_user["image_mime"] or "image/jpeg")]
        result = get_scorer().score(
            query=last_user["content"] or "(image)",
            ai_response=reply,
            domain=DOMAIN_ADAPTERS["general"],
            attachments=attachments,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        resp.unverified = False
        resp.verdict = result.verdict.value
        resp.score = result.sycophancy_score
        alt = (result.suggested_honest_alternative or "").strip()
        if result.verdict.value in ("SYCOPHANTIC", "BORDERLINE") and alt:
            resp.original = reply
            resp.reply = alt
            resp.replaced = True

        identity = chat_key if key_record else "public-chat"
        log_inputs = bool(key_record.get("log_inputs")) if key_record else True
        log_id = store.log_usage(
            api_key=identity,
            domain="general",
            underlying_model="gemini",
            scoring_model_used=get_scorer().last_model_used,
            user_id=None,
            sycophancy_score=result.sycophancy_score,
            verdict=result.verdict.value,
            intent_gap=result.intent_gap.gap_score,
            response_honesty=result.honesty.honesty_score,
            high_stakes=result.is_high_stakes,
            processing_time_ms=elapsed_ms,
            user_query=(last_user["content"] if log_inputs else None),
            ai_response=(reply if log_inputs else None),
            context=None,
            attachment_count=1 if last_user["image_bytes"] else 0,
            indicators=result.sycophancy_indicators,
            suggested_alternative=alt,
        )
        resp.request_id = log_id
    except ScorerError:
        pass  # fail open: unverified reply, visibly labeled by the frontend
    except Exception:
        pass

    resp.processing_time_ms = int((time.perf_counter() - t0) * 1000)
    return resp


@app.post("/chat/feedback")
def chat_feedback(req: ChatFeedbackRequest) -> dict:
    """Thumbs up/down from the public chat — human ground truth, no auth needed."""
    try:
        updated = store.record_feedback(req.request_id, None, req.outcome)
    except store.StoreError:
        raise HTTPException(503, "Feedback backend unavailable.")
    if not updated:
        raise HTTPException(404, f"No scored request with id {req.request_id}.")
    return {"ok": True}
