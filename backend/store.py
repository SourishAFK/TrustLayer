"""
store.py — TrustLayer PERSISTENCE LAYER (Postgres / Supabase).

The durable backbone for Phase 2: API keys, usage logging, and daily rate
counters. Everything here is behind a thin, dependency-free interface so the
rest of the app (main.py) never writes raw SQL — and so the backend could later
be swapped (SQLite, another Postgres) without touching the API.

DESIGN NOTES:
  * Connects via DATABASE_URL (Supabase Session pooler). Reads it from env.
  * One process-wide connection pool, opened lazily on first use.
  * No LLM calls, no business logic beyond storage — pure persistence.
  * Every scored request is logged to `usage_log`: this IS the behavioral
    dataset that future fine-tuning will train on. Log everything.
"""

from __future__ import annotations

import json
import os
import secrets
import string
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# --------------------------------------------------------------------------- #
# Connection pool
# --------------------------------------------------------------------------- #

_pool: Optional[ConnectionPool] = None


def _get_pool() -> ConnectionPool:
    """Lazily build the process-wide pool. Small max_size to respect the
    Supabase free-tier connection ceiling."""
    global _pool
    if _pool is None:
        url = os.getenv("DATABASE_URL")
        if not url:
            raise StoreError("DATABASE_URL is not set. Add your Supabase connection string to .env.")
        _pool = ConnectionPool(
            url,
            min_size=1,
            max_size=3,
            open=True,
            kwargs={"connect_timeout": 15, "row_factory": dict_row},
        )
    return _pool


def close_pool() -> None:
    """Close the connection pool cleanly (call on app shutdown)."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


class StoreError(RuntimeError):
    """Raised when persistence fails (connection/SQL error)."""


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    key         TEXT PRIMARY KEY,
    owner       TEXT,
    tier        TEXT NOT NULL DEFAULT 'free',
    daily_limit INTEGER NOT NULL DEFAULT 100,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    log_inputs  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS usage_log (
    id                    BIGSERIAL PRIMARY KEY,
    api_key               TEXT,
    domain                TEXT,
    underlying_model      TEXT,
    scoring_model_used    TEXT,
    user_id               TEXT,
    sycophancy_score      INTEGER,
    verdict               TEXT,
    intent_gap            REAL,
    response_honesty      REAL,
    high_stakes           BOOLEAN,
    processing_time_ms    INTEGER,
    -- TRAINABLE FEATURES (raw inputs) — only stored when the key opts in (PII).
    user_query            TEXT,
    ai_response           TEXT,
    context               TEXT,
    attachment_count      INTEGER,
    -- LABELS (our system's output) — always stored.
    indicators            TEXT,
    suggested_alternative TEXT,
    -- GROUND TRUTH (backfilled later via /feedback) — the real moat.
    feedback              TEXT,
    outcome               TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_usage_log_api_key ON usage_log (api_key);
CREATE INDEX IF NOT EXISTS idx_usage_log_created ON usage_log (created_at);

CREATE TABLE IF NOT EXISTS rate_counter (
    api_key TEXT NOT NULL,
    day     DATE NOT NULL,
    count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (api_key, day)
);

-- Migrations for already-created tables (idempotent).
ALTER TABLE api_keys  ADD COLUMN IF NOT EXISTS log_inputs BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE usage_log ADD COLUMN IF NOT EXISTS user_query TEXT;
ALTER TABLE usage_log ADD COLUMN IF NOT EXISTS ai_response TEXT;
ALTER TABLE usage_log ADD COLUMN IF NOT EXISTS context TEXT;
ALTER TABLE usage_log ADD COLUMN IF NOT EXISTS attachment_count INTEGER;
ALTER TABLE usage_log ADD COLUMN IF NOT EXISTS indicators TEXT;
ALTER TABLE usage_log ADD COLUMN IF NOT EXISTS suggested_alternative TEXT;
ALTER TABLE usage_log ADD COLUMN IF NOT EXISTS feedback TEXT;
ALTER TABLE usage_log ADD COLUMN IF NOT EXISTS outcome TEXT;
"""


def init_db() -> None:
    """Create tables/indexes if they don't exist. Idempotent — safe to run on
    every startup."""
    try:
        with _get_pool().connection() as conn:
            conn.execute(_SCHEMA)
    except Exception as exc:  # noqa: BLE001
        raise StoreError(f"Schema init failed: {exc}") from exc


# --------------------------------------------------------------------------- #
# API keys
# --------------------------------------------------------------------------- #

_KEY_ALPHABET = string.ascii_lowercase + string.digits

# Free-tier daily request cap per key. Sized so 70 profiles share the Gemini
# free-tier budget safely (each /score = 2 Gemini calls). Tune via env without
# touching code; raise it once more API keys are added and usage_log shows
# headroom.
DEFAULT_DAILY_LIMIT = int(os.getenv("FREE_TIER_DAILY_LIMIT") or 10)


def generate_api_key(owner: Optional[str] = None, tier: str = "free",
                     daily_limit: int = DEFAULT_DAILY_LIMIT,
                     log_inputs: bool = False) -> str:
    """Create and persist a new `tl_`-prefixed API key. Returns the key string.

    `log_inputs` controls whether this key's raw request text (the customer's
    query, the AI response, the context) is stored for model training. Off by
    default — turn it on per key only with the customer's consent (PII).
    """
    key = "tl_" + "".join(secrets.choice(_KEY_ALPHABET) for _ in range(20))
    try:
        with _get_pool().connection() as conn:
            conn.execute(
                "INSERT INTO api_keys (key, owner, tier, daily_limit, log_inputs) "
                "VALUES (%s, %s, %s, %s, %s)",
                (key, owner, tier, daily_limit, log_inputs),
            )
    except Exception as exc:  # noqa: BLE001
        raise StoreError(f"Could not create API key: {exc}") from exc
    return key


def validate_key(key: str) -> Optional[dict]:
    """Return the active key record (dict) or None if missing/inactive."""
    try:
        with _get_pool().connection() as conn:
            row = conn.execute(
                "SELECT key, owner, tier, daily_limit, active, log_inputs, created_at "
                "FROM api_keys WHERE key = %s AND active = TRUE",
                (key,),
            ).fetchone()
        return row
    except Exception as exc:  # noqa: BLE001
        raise StoreError(f"Key lookup failed: {exc}") from exc


def set_log_inputs(key: str, enabled: bool) -> bool:
    """Toggle input logging for a key. Returns True if a key was updated."""
    try:
        with _get_pool().connection() as conn:
            res = conn.execute(
                "UPDATE api_keys SET log_inputs = %s WHERE key = %s",
                (enabled, key),
            )
        return bool(res.rowcount)
    except Exception as exc:  # noqa: BLE001
        raise StoreError(f"Could not update key: {exc}") from exc


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #

def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _next_utc_midnight() -> datetime:
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)


def check_and_increment_rate(key: str, daily_limit: int) -> dict:
    """Atomically bump today's counter for `key` and report whether it's allowed.

    Returns: {allowed: bool, count: int, limit: int, reset_at: ISO8601 str}.
    `count` is the request number this call represents (1 = first today).
    """
    today = _utc_today()
    try:
        with _get_pool().connection() as conn:
            row = conn.execute(
                "INSERT INTO rate_counter (api_key, day, count) VALUES (%s, %s, 1) "
                "ON CONFLICT (api_key, day) "
                "DO UPDATE SET count = rate_counter.count + 1 "
                "RETURNING count",
                (key, today),
            ).fetchone()
        count = row["count"]
    except Exception as exc:  # noqa: BLE001
        raise StoreError(f"Rate check failed: {exc}") from exc
    return {
        "allowed": count <= daily_limit,
        "count": count,
        "limit": daily_limit,
        "reset_at": _next_utc_midnight().isoformat().replace("+00:00", "Z"),
    }


# --------------------------------------------------------------------------- #
# Usage logging (the behavioral dataset)
# --------------------------------------------------------------------------- #

def log_usage(
    api_key: Optional[str],
    domain: Optional[str],
    underlying_model: Optional[str],
    scoring_model_used: Optional[str],
    user_id: Optional[str],
    sycophancy_score: Optional[int],
    verdict: Optional[str],
    intent_gap: Optional[float],
    response_honesty: Optional[float],
    high_stakes: Optional[bool],
    processing_time_ms: Optional[int],
    *,
    user_query: Optional[str] = None,
    ai_response: Optional[str] = None,
    context: Optional[str] = None,
    attachment_count: Optional[int] = None,
    indicators: Optional[list[str]] = None,
    suggested_alternative: Optional[str] = None,
) -> Optional[int]:
    """Record one scored request and return its row id (for later /feedback).

    The raw-text features (`user_query`, `ai_response`, `context`) are only
    passed in when the key opts into input logging — the caller enforces that.
    Best-effort: never let logging break a scoring request (returns None on fail).
    """
    indicators_json = json.dumps(indicators) if indicators is not None else None
    try:
        with _get_pool().connection() as conn:
            row = conn.execute(
                "INSERT INTO usage_log ("
                " api_key, domain, underlying_model, scoring_model_used, user_id,"
                " sycophancy_score, verdict, intent_gap, response_honesty,"
                " high_stakes, processing_time_ms,"
                " user_query, ai_response, context, attachment_count,"
                " indicators, suggested_alternative"
                ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "RETURNING id",
                (
                    api_key, domain, underlying_model, scoring_model_used, user_id,
                    sycophancy_score, verdict, intent_gap, response_honesty,
                    high_stakes, processing_time_ms,
                    user_query, ai_response, context, attachment_count,
                    indicators_json, suggested_alternative,
                ),
            ).fetchone()
        return row["id"] if row else None
    except Exception:  # noqa: BLE001 — logging must never break a scoring request
        return None


def record_feedback(
    log_id: int, feedback: Optional[str] = None, outcome: Optional[str] = None
) -> bool:
    """Attach ground-truth feedback/outcome to a logged request. The real moat:
    'a human reversed this', 'the customer disputed', 'verdict was wrong'.

    Returns True if the row existed and was updated.
    """
    try:
        with _get_pool().connection() as conn:
            res = conn.execute(
                "UPDATE usage_log SET "
                " feedback = COALESCE(%s, feedback), "
                " outcome  = COALESCE(%s, outcome) "
                "WHERE id = %s",
                (feedback, outcome, log_id),
            )
        return bool(res.rowcount)
    except Exception as exc:  # noqa: BLE001
        raise StoreError(f"Could not record feedback: {exc}") from exc
