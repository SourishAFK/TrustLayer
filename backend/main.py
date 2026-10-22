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
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi import Path as FastAPIPath
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from backend import store
from backend.domain_rules import (
    CustomerServiceDomain,
    FintechDomain,
    GeneralDomain,
)
from backend.scorer import ScorerError, SycophancyScorer, scorer_from_env
from backend.verification import budget, pipeline
from backend.verification.report import VerificationReport, VerificationRequest
from backend.verification.schemas import ExtractionRequest, ExtractionResponse
from backend.verification.service import extract_response

logger = logging.getLogger(__name__)


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

# CORS: permissive by default (local dev, SDKs, the separate public chat page).
# Production should list its frontend origins in TRUSTLAYER_CORS_ORIGINS
# (comma-separated). Credentials are never allowed cross-origin.
_CORS_ORIGINS = [o.strip() for o in os.getenv("TRUSTLAYER_CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    """Cheap defense-in-depth headers for the HTML pages and JSON alike."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


@lru_cache(maxsize=1)
def get_scorer() -> SycophancyScorer:
    """Build the scorer once. Cached as a singleton.

    The domain is now injected per-request (see DOMAIN_ADAPTERS), so no default
    domain is baked in here. scorer_from_env reads GEMINI_API_KEY_2.._9 and
    GEMINI_FALLBACK_MODELS to build the (key, model) rotation chain — the same
    builder the verification pipeline's sycophancy engine uses.
    """
    return scorer_from_env()


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
    # Never echo the message: parse errors quote the model's raw output, which
    # can contain the caller's text. The type is enough for the server log.
    logger.warning("Scoring failed upstream (%s)", type(exc).__name__)
    return HTTPException(502, "Scoring failed upstream. Try again shortly.")


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
        # Scoped to the caller's key: a request_id from another customer is a 404.
        updated = store.record_feedback(req.request_id, req.feedback, req.outcome,
                                        owners=[key_record["key"]])
    except store.StoreError:
        raise HTTPException(503, "Feedback backend unavailable. Try again shortly.")
    if not updated:
        raise HTTPException(404, f"No scored request with id {req.request_id}.")
    return {"ok": True, "request_id": req.request_id}


@app.post("/v1/claims/extract", response_model=ExtractionResponse, tags=["Claim extraction"])
def extract_claims(req: ExtractionRequest, key_record: dict = Depends(authenticate)):
    """Level 1 only: bounded local extraction, no evidence verdicts or storage.

    Uses existing account authentication and atomic daily request limits. The
    submitted text is neither persisted nor sent to any model/search provider.
    """
    try:
        rate = store.check_and_increment_rate(key_record["key"], key_record["daily_limit"])
    except store.StoreError:
        raise HTTPException(503, "Rate-limit backend unavailable. Try again shortly.")
    if not rate["allowed"]:
        return JSONResponse(status_code=429, content={
            "error": "rate_limit_exceeded",
            "message": "Daily request limit reached.",
            "reset_at": rate["reset_at"],
        })
    try:
        return extract_response(req)
    except ValueError:
        raise HTTPException(503, "Claim extraction configuration is invalid.")


# --------------------------------------------------------------------------- #
# Level 2 verification — evidence-backed reports (schema 2.0).
# Same tl_ keys and daily quota as /score, plus a per-process cap on concurrent
# verifications: each one can hold a slot for its whole time budget. Request
# text is never logged or stored here; failures log exception types only.
# --------------------------------------------------------------------------- #

_CONFIG_INVALID = "Verification configuration is invalid."
_VERIFY_FAILED = "Verification could not complete. No verdicts were produced."


def _verification_slots() -> Optional[threading.BoundedSemaphore]:
    """Capacity from TRUSTLAYER_MAX_CONCURRENT_VERIFICATIONS (1..64, default 4).

    None means misconfigured: the verify routes then fail closed with 503 while
    every other route keeps working (raising at import would take them all down).
    """
    try:
        size = int(os.getenv("TRUSTLAYER_MAX_CONCURRENT_VERIFICATIONS", "4"))
    except ValueError:
        return None
    return threading.BoundedSemaphore(size) if 1 <= size <= 64 else None


_VERIFY_SLOTS = _verification_slots()


def _quota_rejection(key_record: dict) -> Optional[JSONResponse]:
    """Charge one request to the daily quota; same 429/503 contract as /v1/claims/extract."""
    try:
        rate = store.check_and_increment_rate(key_record["key"], key_record["daily_limit"])
    except store.StoreError:
        raise HTTPException(503, "Rate-limit backend unavailable. Try again shortly.")
    if rate["allowed"]:
        return None
    return JSONResponse(status_code=429, content={
        "error": "rate_limit_exceeded",
        "message": "Daily request limit reached.",
        "reset_at": rate["reset_at"],
    })


def _acquire_verification_slot(mode: str) -> threading.BoundedSemaphore:
    """Fail closed on bad config, then take a slot without waiting. The caller releases it."""
    try:
        pipeline.check_config(mode)
    except ValueError:  # the message names server settings; never echo it
        raise HTTPException(503, _CONFIG_INVALID)
    slots = _VERIFY_SLOTS
    if slots is None:
        raise HTTPException(503, _CONFIG_INVALID)
    if not slots.acquire(blocking=False):
        raise HTTPException(503, "Verification capacity is busy. Try again shortly.",
                            headers={"Retry-After": "5"})
    return slots


# One JSON line per finished verification: counts, timings, cost and the hashed
# owner — never request text, report text or keys. Ship stdout to your log store.
audit_log = logging.getLogger("trustlayer.audit")
if not audit_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    audit_log.addHandler(_handler)
    audit_log.setLevel(logging.INFO)
    audit_log.propagate = False


def _finalizer(api_key: str, retain: bool = True):
    """Report post-processing for one caller: optional retention, then the audit line."""
    def finalize(report: VerificationReport) -> VerificationReport:
        hours = pipeline.retention_hours() if retain else 0
        if hours:
            report.privacy.stored = True
            report.privacy.note += (f" This report is stored for {hours} hours; delete it any "
                                    f"time with DELETE /v1/reports/{report.report_id}.")
            try:
                store.save_report(report.report_id, api_key, report.model_dump_json(), hours)
            except store.StoreError as exc:
                logger.error("Report storage failed (%s)", type(exc).__name__)
                report.privacy.stored = False
                report.privacy.note += " Storage failed, so the report was not saved."
        s, u = report.summary, report.usage
        audit_log.info(json.dumps({
            "event": "verification", "report_id": report.report_id, "mode": report.mode,
            "status": report.status, "owner": store.owner_hash(api_key)[:12],
            "claims": s.total_extracted, "supported": s.supported, "contradicted": s.contradicted,
            "disputed": s.disputed, "unverified": s.unverified, "not_checkable": s.not_checkable,
            "investigated": s.investigated, "checks_incomplete": s.checks_incomplete,
            "signals_critical": s.signals_critical, "duration_ms": u.duration_ms,
            "model_calls": u.model_calls, "search_calls": u.search_calls,
            "pages_fetched": u.pages_fetched, "cost_usd": u.estimated_cost_usd,
            "exhausted": u.exhausted, "stored": report.privacy.stored,
            "engines": {e.engine: e.status for e in report.engines},
        }))
        return report
    return finalize


def _stream_holding_slot(req: VerificationRequest, slots: threading.BoundedSemaphore,
                         api_key: str, retain: bool = True) -> Iterator[str]:
    """Pipeline NDJSON lines while holding a capacity slot until the verification work ends.

    Once the worker thread runs, it frees the slot when it finishes: a client that drops the
    stream must not free capacity while its verification is still running (drop-and-reopen
    would otherwise exceed the cap). Before that, this generator frees it. Exactly once.
    """
    lock, state = threading.Lock(), {"released": False, "started": False}

    def release():
        with lock:
            if state["released"]:
                return
            state["released"] = True
        slots.release()

    def started():
        state["started"] = True

    try:
        # The route consumes this item, so the finally is armed before Starlette gets
        # the stream: a client that leaves before streaming starts still frees its slot.
        yield ""
        yield from pipeline.stream_ndjson(req, finalize=_finalizer(api_key, retain), on_start=started,
                                          on_done=release)
    except Exception as exc:  # noqa: BLE001 — status 200 is already sent; end with an error line
        logger.error("Verification stream failed (%s)", type(exc).__name__)
        yield json.dumps({"type": "error", "message": _VERIFY_FAILED}) + "\n"
    finally:
        if not state["started"]:
            release()


@app.post("/v1/verify", response_model=VerificationReport, tags=["Verification"])
def verify_response(req: VerificationRequest, key_record: dict = Depends(authenticate)):
    """Split the response into claims, research the risky ones, apply the verdict policy.

    Charges the daily quota (including requests refused because capacity is busy).
    The request is never stored; the report only when report retention is enabled.
    """
    rejection = _quota_rejection(key_record)
    if rejection is not None:
        return rejection
    slots = _acquire_verification_slot(req.mode)
    try:
        return pipeline.verify(req, finalize=_finalizer(key_record["key"]))
    except ValueError as exc:  # pipeline.verify raises ValueError only for invalid server config
        logger.error("Verification configuration is invalid (%s)", type(exc).__name__)
        raise HTTPException(503, _CONFIG_INVALID)
    except Exception as exc:  # noqa: BLE001
        logger.error("Verification failed (%s)", type(exc).__name__)
        raise HTTPException(500, _VERIFY_FAILED)
    finally:
        slots.release()


@app.post("/v1/verify/stream", tags=["Verification"])
def verify_response_stream(req: VerificationRequest, key_record: dict = Depends(authenticate)):
    """Same checks as /v1/verify with live progress as NDJSON.

    Lines are {"type": "progress"} events, then one {"type": "report"} (or
    {"type": "error"} when no report could be produced).
    """
    rejection = _quota_rejection(key_record)
    if rejection is not None:
        return rejection
    lines = _stream_holding_slot(req, _acquire_verification_slot(req.mode), key_record["key"])
    next(lines)
    return StreamingResponse(lines, media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


_REPORT_ID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


@app.get("/v1/reports/{report_id}", response_model=VerificationReport, tags=["Verification"])
def get_stored_report(report_id: str = FastAPIPath(..., pattern=_REPORT_ID),
                      key_record: dict = Depends(authenticate)):
    """A stored report (only when retention is enabled), visible to its owner only."""
    try:
        report = store.get_report(report_id, key_record["key"])
    except store.StoreError:
        raise HTTPException(503, "Report storage unavailable. Try again shortly.")
    if report is None:  # missing, expired, or another caller's: indistinguishable on purpose
        raise HTTPException(404, "No stored report with that id.")
    return report


@app.delete("/v1/reports/{report_id}", tags=["Verification"])
def delete_stored_report(report_id: str = FastAPIPath(..., pattern=_REPORT_ID),
                         key_record: dict = Depends(authenticate)) -> dict:
    """Delete a stored report now, before its retention period ends."""
    try:
        deleted = store.delete_report(report_id, key_record["key"])
    except store.StoreError:
        raise HTTPException(503, "Report storage unavailable. Try again shortly.")
    if not deleted:
        raise HTTPException(404, "No stored report with that id.")
    return {"deleted": True, "report_id": report_id}


@app.get("/v1/status", tags=["Verification"])
def verification_status() -> dict:
    """Public capability summary: limits per mode and provider names. Never secrets."""
    from backend.verification.llm import available_providers
    from backend.verification.search import configured_search_providers

    try:
        modes = {mode: budget.limits_for(mode).public().model_dump() for mode in ("quick", "deep")}
        retention = pipeline.retention_hours()
        # Names only: provider objects hold API keys.
        search_names = [p.name for p in configured_search_providers("deep")]
    except ValueError:
        raise HTTPException(503, _CONFIG_INVALID)
    from backend.verification.fetcher import respects_robots

    return {
        "service": "TrustLayer",
        "schema_version": "2.0",
        "modes": modes,
        "search_providers": search_names,
        "ai_providers": available_providers(),
        "fetching": {"ssrf_protection": True, "respects_robots_txt": respects_robots()},
        "retention_hours": retention,
    }


# --------------------------------------------------------------------------- #
# Website: "Get a free check" sign-ups and the public live demo.
# Both are keyless, so both are capped per visitor (salted IP hash) and site-wide.
# --------------------------------------------------------------------------- #

class _WindowLimit:
    """Sliding-window counter per key. ponytail: in-process memory; move it to the database if the
    API ever runs on several instances (each would otherwise allow its own share)."""

    def __init__(self, limit: int, seconds: int):
        self.limit, self.seconds = limit, seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: Optional[int] = None) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.seconds]
            allowed = len(hits) < (self.limit if limit is None else limit)
            if allowed:
                hits.append(now)
            self._hits[key] = hits
            if len(self._hits) > 10_000:  # bound memory: forget idle visitors
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.seconds}
            return allowed


_IP_SALT = os.getenv("TRUSTLAYER_IP_SALT") or secrets.token_hex(16)


def _visitor(request: Request) -> str:
    """Salted hash of the caller's address. Behind a proxy the last X-Forwarded-For entry is the
    one the proxy saw (earlier entries are whatever the client claimed)."""
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    address = forwarded[-1] if forwarded else (request.client.host if request.client else "unknown")
    return hashlib.sha256(f"{_IP_SALT}:{address}".encode()).hexdigest()[:16]


_EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s.]+(?:\.[^@\s.]+)+")
_SOURCE_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "page", "referrer"}


class LeadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audience: Literal["product-teams", "documents", "support-bots", "general"]
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=254)
    company: Optional[str] = Field(None, max_length=120)
    role: Optional[str] = Field(None, max_length=80)
    message: Optional[str] = Field(None, max_length=4000)
    link: Optional[str] = Field(None, max_length=2048)
    consent: bool
    # "Would you pay for a full check?": the first signal of who is a buyer, and at what price.
    would_pay: Optional[Literal["no", "up-to-50", "50-200", "200-plus"]] = None
    website: str = Field("", max_length=200)  # honeypot: hidden from people, filled by bots
    source: dict[str, str] = Field(default_factory=dict)  # utm_* tags, landing page, referrer

    @model_validator(mode="after")
    def valid(self):
        self.name, self.email = self.name.strip(), self.email.strip()
        if not self.name:
            raise ValueError("Please enter your name.")
        if not _EMAIL.fullmatch(self.email):
            raise ValueError("Please enter a valid email address.")
        if not self.consent:
            raise ValueError("Please agree to be contacted about your check.")
        if self.link and not self.link.strip().lower().startswith(("http://", "https://")):
            raise ValueError("Links must start with http:// or https://.")
        if set(self.source) - _SOURCE_KEYS or any(len(v) > 300 for v in self.source.values()):
            raise ValueError("Unknown or oversized source fields.")
        return self


_LEADS_PER_VISITOR = _WindowLimit(5, 3600)
_LEADS_PER_DAY = _WindowLimit(500, 86_400)


@app.post("/v1/leads", status_code=201, tags=["Website"])
def create_lead(lead: LeadRequest, request: Request) -> dict:
    """A "Get a free check" sign-up from the website, tagged with its audience lane."""
    if lead.website:  # a bot filled the honeypot: look successful, keep nothing
        return {"ok": True}
    visitor = _visitor(request)
    if not _LEADS_PER_VISITOR.allow(visitor) or not _LEADS_PER_DAY.allow("site"):
        raise HTTPException(429, "Too many requests right now. Please try again in a while.")
    try:
        lead_id = store.save_lead(lead.model_dump(exclude={"website", "consent"}), visitor)
    except store.StoreError:
        raise HTTPException(503, "We couldn't save your request just now. Please try again shortly.")
    logger.info("Lead saved (id=%s, audience=%s)", lead_id, lead.audience)  # never the person's details
    return {"ok": True}


class DemoDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=120)
    text: str = Field(..., min_length=1, max_length=6000)


class DemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response_text: str = Field(..., min_length=1, max_length=3000)
    original_question: Optional[str] = Field(None, max_length=500)
    # The support-bot demo: check the answer against this policy text only (no web search).
    answer_key: Optional[DemoDocument] = None
    source_model: Optional[str] = Field(None, max_length=80)


_DEMO_PER_VISITOR = _WindowLimit(5, 86_400)
_DEMO_PER_DAY = _WindowLimit(100, 86_400)


def _demo_enabled() -> bool:
    return os.getenv("TRUSTLAYER_PUBLIC_DEMO", "").strip().lower() in ("1", "true", "yes", "on")


def _demo_daily_limit() -> int:
    try:
        return max(0, int(os.getenv("TRUSTLAYER_DEMO_DAILY_LIMIT", "100")))
    except ValueError:
        return 0  # a typo must not mean "unlimited spend"


@app.post("/v1/demo/verify/stream", tags=["Website"])
def demo_verify_stream(req: DemoRequest, request: Request):
    """The website's live demo: a Quick Check of a short text, streamed as NDJSON.

    Off unless TRUSTLAYER_PUBLIC_DEMO is on. Capped per visitor and per day, never stored.
    """
    if not _demo_enabled():
        raise HTTPException(404, "Not Found")
    if not _DEMO_PER_VISITOR.allow(_visitor(request)) or not _DEMO_PER_DAY.allow("site", _demo_daily_limit()):
        raise HTTPException(429, "The live demo is busy right now. Try again later, or open the sample report.")
    key = req.answer_key
    verification = VerificationRequest(
        response_text=req.response_text, original_question=req.original_question, mode="quick",
        source_model=req.source_model, allow_web_search=key is None, share_documents_with_ai=key is not None,
        documents=[{"name": key.name, "text": key.text}] if key else [],
        documents_role="answer_key" if key else "context")
    lines = _stream_holding_slot(verification, _acquire_verification_slot("quick"), "public-demo", retain=False)
    next(lines)
    return StreamingResponse(lines, media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- #
# Public chat (TrustLayer Chat frontend) — generation + verification in one call.
# The static frontend holds no keys: Gemini runs here, scoring runs in-process.
# Identity comes from TRUSTLAYER_CHAT_KEY env (a normal tl_ key, so the existing
# rate limiter + logging gates apply); without it, an in-memory daily cap guards.
# --------------------------------------------------------------------------- #

class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(default="", max_length=8000)
    # 10 MB of bytes is ~13.4M base64 characters; reject bigger bodies before decoding.
    image_b64: Optional[str] = Field(default=None, max_length=14_000_000)
    image_mime: Optional[str] = Field(default=None, max_length=40)


MAX_CHAT_MESSAGES = 50
MAX_CHAT_IMAGES = 4


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1, max_length=MAX_CHAT_MESSAGES)

    @model_validator(mode="after")
    def bounded_images(self):
        if sum(bool(m.image_b64) for m in self.messages) > MAX_CHAT_IMAGES:
            raise ValueError(f"At most {MAX_CHAT_IMAGES} images per conversation.")
        return self


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
_public_chat_lock = threading.Lock()


def _public_chat_allowed() -> bool:
    """In-memory daily cap: used when TRUSTLAYER_CHAT_KEY isn't configured, and as
    the fallback when the database quota can't be checked (never fail open)."""
    import datetime as _dt
    today = _dt.datetime.now(_dt.timezone.utc).date()
    with _public_chat_lock:
        if _public_chat_counter["day"] != today:
            _public_chat_counter["day"] = today
            _public_chat_counter["count"] = 0
        _public_chat_counter["count"] += 1
        return _public_chat_counter["count"] <= _PUBLIC_CHAT_FALLBACK_LIMIT


def _chat_identities() -> list[str]:
    """api_key values the public chat logs under (see /chat)."""
    chat_key = os.getenv("TRUSTLAYER_CHAT_KEY")
    return ["public-chat"] + ([chat_key] if chat_key else [])


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
            # Quota store unreachable: fall back to the in-memory cap instead of
            # serving unlimited requests.
            if not _public_chat_allowed():
                raise HTTPException(429, "The chat's daily budget is used up. Try tomorrow.")
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
        # Keyless public chat logs raw text unless TRUSTLAYER_PUBLIC_CHAT_LOG_INPUTS
        # is false (the default keeps the original data-collection behavior).
        log_inputs = (bool(key_record.get("log_inputs")) if key_record else
                      os.getenv("TRUSTLAYER_PUBLIC_CHAT_LOG_INPUTS", "true").strip().lower()
                      not in ("0", "false", "no", "off"))
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
    """Thumbs up/down from the public chat — human ground truth, no auth needed.

    Unauthenticated, so it may only label public-chat rows, and only once:
    an enumerated request_id can't relabel API customers' rows or overwrite a label.
    """
    # ponytail: ids are still guessable; a per-response feedback token would also
    # stop someone labeling a stranger's unlabeled public-chat row first.
    try:
        updated = store.record_feedback(req.request_id, None, req.outcome,
                                        owners=_chat_identities(), first_write_only=True)
    except store.StoreError:
        raise HTTPException(503, "Feedback backend unavailable.")
    if not updated:
        raise HTTPException(404, f"No scored request with id {req.request_id}.")
    return {"ok": True}


# Additive UI: the original developer docs and Streamlit application remain.
# Build with `cd frontend/web && npm ci && npm run build`, then restart the API.
_WORKBENCH_DIST = Path(__file__).resolve().parent.parent / "frontend" / "web" / "dist"
if _WORKBENCH_DIST.is_dir():
    app.mount("/workbench", StaticFiles(directory=_WORKBENCH_DIST, html=True), name="workbench")
else:
    @app.get("/workbench/", response_class=HTMLResponse, include_in_schema=False)
    def workbench_not_built():
        return HTMLResponse(
            "<h1>TrustLayer workbench</h1><p>Build frontend/web, then restart the API.</p>",
            status_code=503,
        )
