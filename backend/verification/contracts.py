"""Runtime contracts shared by every part of the verification pipeline.

Three kinds of things live here:

1. Provider interfaces (Protocols): LLMProvider, SearchProvider, Fetcher.
   Real adapters (Gemini, Anthropic, Brave, Wikipedia, OpenAlex, SafeFetcher)
   and test fakes both satisfy them, so tests never need paid credentials.
2. RunContext: the per-request toolbox. Engines never call a provider directly;
   they call ctx.search_with / ctx.fetch / ctx.ask_llm, which charge the Budget,
   enforce the deadline, cache pages and swallow provider errors into "not run".
3. Findings: a shared blackboard. Engines write evidence, calculations, signals
   and notes onto it; the aggregator alone turns it into verdicts.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Literal, Protocol

from pydantic import ValidationError

from backend.verification.budget import Budget, estimate_tokens
from backend.verification.report import (
    Calculation,
    CheckRecord,
    CitationCheck,
    CompletenessSection,
    EngineRun,
    Evidence,
    Freshness,
    MarketInvestigation,
    ProgressEvent,
    Signal,
    SourceRef,
    SycophancySection,
    VerificationRequest,
)
from backend.verification.schemas import Claim

logger = logging.getLogger(__name__)
MAX_URL = 2048  # report.Url


# --------------------------------------------------------------------------- #
# Provider interfaces
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    provider: str
    published_at: datetime | None = None
    # Full text when the provider returns it (e.g. Wikipedia extracts), so no
    # page fetch is needed. None means "fetch the URL to read it".
    content: str | None = None


class SearchProvider(Protocol):
    name: str
    kind: Literal["web", "reference", "academic"]

    def search(self, query: str, *, count: int, timeout: float) -> list[SearchResult]: ...


@dataclass(frozen=True)
class FetchedPage:
    url: str
    final_url: str
    ok: bool
    status: int | None
    # Machine-readable failure code when not ok: invalid_url, blocked_address,
    # blocked_port, robots_disallowed, dns_failure, timeout, http_error,
    # unsupported_content_type, too_large, redirect_limit, network_error,
    # budget_exhausted, fetch_disabled.
    error: str | None
    content_type: str | None
    title: str | None
    publisher: str | None
    published_at: datetime | None
    text: str
    fetched_at: datetime


class Fetcher(Protocol):
    def fetch(self, url: str, *, timeout: float) -> FetchedPage: ...


@dataclass(frozen=True)
class LLMResult:
    data: dict
    model: str
    input_tokens: int
    output_tokens: int


class LLMError(RuntimeError):
    """Provider failure. The message must never contain secrets or user text."""


class LLMProvider(Protocol):
    name: str    # adapter name: "gemini" | "anthropic"
    family: str  # model family, for "never let a model judge itself"
    model: str

    def complete_json(self, *, system: str, prompt: str, schema: dict,
                      max_output_tokens: int, timeout: float) -> LLMResult: ...


@dataclass
class Providers:
    llm: LLMProvider | None = None
    search: list[SearchProvider] = field(default_factory=list)
    fetcher: Fetcher | None = None
    # Builds the original TrustLayer sycophancy scorer (Gemini). None = not available,
    # so Providers() means "no external calls at all".
    legacy_scorer: Callable[[], object] | None = None


# --------------------------------------------------------------------------- #
# Plan, blackboard, engine interface
# --------------------------------------------------------------------------- #

@dataclass
class Plan:
    evidence: list[str] = field(default_factory=list)       # claim ids to research, priority order
    deferred: dict[str, str] = field(default_factory=dict)  # claim id -> why not researched
    market: list[str] = field(default_factory=list)         # claim ids for competitor research


@dataclass
class ClaimNotes:
    evidence: list[Evidence] = field(default_factory=list)
    contradictions: list[Evidence] = field(default_factory=list)
    calculations: list[Calculation] = field(default_factory=list)
    related_sources: list[SourceRef] = field(default_factory=list)
    citation_ids: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    checks: list[CheckRecord] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)       # plain-language explanation fragments
    missing: list[str] = field(default_factory=list)     # what evidence would be needed
    limitations: list[str] = field(default_factory=list)
    # (text, source domain) — or a bare string from a calculation, which has no source.
    corrections: list[tuple[str, str | None] | str] = field(default_factory=list)
    certainty_flags: list[str] = field(default_factory=list)
    freshness: Freshness | None = None
    investigated: bool = False


class Findings:
    """Thread-safe blackboard. Engines only append; the aggregator only reads."""

    def __init__(self, claim_ids: list[str]):
        self.lock = threading.RLock()
        self.claims = {cid: ClaimNotes() for cid in claim_ids}
        self.citations: list[CitationCheck] = []
        self.signals: list[Signal] = []
        self.sycophancy: SycophancySection | None = None
        self.completeness: CompletenessSection | None = None
        self.market: list[MarketInvestigation] = []
        self.incomplete: list[str] = []
        self.limitations: list[str] = []
        self._evidence_seq = 0
        self._signal_seq = 0
        self.rejected_evidence = 0

    def add_evidence(self, **fields) -> Evidence | None:
        """Validate and attach one evidence item (evidence_id is assigned here).

        Invalid items (quote not in passage, bad URL...) are discarded and counted,
        never repaired: fabricated evidence must not reach the report.
        """
        with self.lock:
            self._evidence_seq += 1
            try:
                item = Evidence(evidence_id=f"e{self._evidence_seq}", **fields)
            except ValidationError:
                self.rejected_evidence += 1
                return None
            notes = self.claims[item.claim_id]
            target = notes.evidence if item.stance == "supports" else notes.contradictions
            if any(e.url == item.url and e.quote == item.quote for e in target):
                return None  # same quote from the same page is not new evidence
            target.append(item)
            return item

    def add_signal(self, **fields) -> Signal | None:
        with self.lock:
            self._signal_seq += 1
            try:
                item = Signal(signal_id=f"s{self._signal_seq}", **fields)
            except ValidationError:
                logger.warning("Discarded an invalid signal from %s", fields.get("engine"))
                return None
            self.signals.append(item)
            return item

    def note(self, claim_id: str, **items) -> None:
        """Append to a claim's lists, e.g. note("c1", method="x", missing="y", check=CheckRecord(...)).

        Keys: method, note, missing, limitation, correction, flag, related,
        calculation, citation_id, check, freshness (replaces), investigated (bool).
        """
        plural = {"method": "methods", "note": "notes", "missing": "missing",
                  "limitation": "limitations", "correction": "corrections",
                  "flag": "certainty_flags", "related": "related_sources",
                  "calculation": "calculations", "citation_id": "citation_ids", "check": "checks"}
        with self.lock:
            notes = self.claims[claim_id]
            for key, value in items.items():
                if key == "freshness":
                    notes.freshness = value
                elif key == "investigated":
                    notes.investigated = notes.investigated or bool(value)
                else:
                    target = getattr(notes, plural[key])
                    if value not in target:
                        target.append(value)

    def incomplete_check(self, message: str) -> None:
        with self.lock:
            if message not in self.incomplete:
                self.incomplete.append(message)

    def limitation(self, message: str) -> None:
        with self.lock:
            if message not in self.limitations:
                self.limitations.append(message)


def _ignore(_event: ProgressEvent) -> None:
    return None


@dataclass
class RunContext:
    request: VerificationRequest
    claims: list[Claim]
    budget: Budget
    now: datetime
    llm: LLMProvider | None = None
    search: list[SearchProvider] = field(default_factory=list)
    fetcher: Fetcher | None = None
    emit: Callable[[ProgressEvent], None] = _ignore
    plan: Plan = field(default_factory=Plan)
    legacy_scorer: Callable[[], object] | None = None
    llm_failures: int = 0
    # What actually happened, for the report's privacy notice: "search:brave",
    # "ai:anthropic/claude-opus-5-5", "ai:gemini/legacy-sycophancy-scorer".
    used: set[str] = field(default_factory=set)
    documents_sent_to_ai: bool = False
    _pages: dict[str, FetchedPage] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark_used(self, label: str) -> None:
        with self._lock:
            self.used.add(label)

    def claim(self, claim_id: str) -> Claim:
        return next(c for c in self.claims if c.claim_id == claim_id)

    def progress(self, stage: str, status: str, message: str, *, claim_id: str | None = None,
                 kind: str = "stage") -> None:
        """Best-effort progress event; a broken listener never breaks verification."""
        try:
            self.emit(ProgressEvent(type=kind, stage=stage, status=status, message=message[:500],
                                    claim_id=claim_id,
                                    elapsed_ms=round(self.budget.elapsed() * 1000, 1)))
        except Exception:  # noqa: BLE001
            logger.debug("Progress listener failed", exc_info=True)

    def search_with(self, provider: SearchProvider, query: str, count: int) -> list[SearchResult] | None:
        """Budgeted search. None = did not run (budget/failure); [] = ran, found nothing."""
        if not self.request.allow_web_search or not self.budget.try_search(provider.name):
            return None
        self.mark_used(f"search:{provider.name}")
        try:
            return provider.search(query, count=count, timeout=self.budget.timeout(12.0))
        except Exception as exc:  # noqa: BLE001 — provider failure becomes "not run"
            logger.warning("Search provider %s failed (%s)", provider.name, type(exc).__name__)
            return None

    def fetch(self, url: str) -> FetchedPage:
        """Budgeted, cached page fetch through the SSRF-safe fetcher."""
        with self._lock:
            cached = self._pages.get(url)
        if cached is not None:
            return cached
        if self.fetcher is None or not self.request.allow_web_search:
            return _failed_page(url, "fetch_disabled", self.now)
        if not self.budget.try_fetch():
            return _failed_page(url, "budget_exhausted", self.now)
        try:
            page = self.fetcher.fetch(url, timeout=self.budget.timeout(15.0))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fetcher raised (%s)", type(exc).__name__)
            page = _failed_page(url, "network_error", self.now)
        if page.ok and len(page.final_url) > MAX_URL:
            # A redirect to a URL no Evidence/SourceRef can hold: treat it as unreadable here,
            # not as a validation error halfway through recording a claim's judgments.
            page = _failed_page(url, "invalid_url", self.now)
        with self._lock:
            self._pages[url] = page
        return page

    def ask_llm(self, *, purpose: str, system: str, prompt: str, schema: dict,
                max_output_tokens: int = 1024) -> dict | None:
        """Budgeted structured model call. None = not run or failed (never a guess)."""
        if self.llm is None or not self.request.allow_ai_processing:
            return None
        estimate = estimate_tokens(system + prompt)
        if not self.budget.try_model(self.llm.model, estimate, max_output_tokens):
            return None
        self.mark_used(f"ai:{self.llm.name}/{self.llm.model}")
        try:
            result = self.llm.complete_json(system=system, prompt=prompt, schema=schema,
                                            max_output_tokens=max_output_tokens,
                                            timeout=self.budget.timeout(45.0))
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM call for %s failed (%s)", purpose, type(exc).__name__)
            with self._lock:
                self.llm_failures += 1
            self.budget.record_model(self.llm.model, estimate, 0)  # assume input was billed
            return None
        self.budget.record_model(result.model, result.input_tokens, result.output_tokens)
        return result.data if isinstance(result.data, dict) else None


def _failed_page(url: str, error: str, now: datetime) -> FetchedPage:
    return FetchedPage(url=url, final_url=url, ok=False, status=None, error=error,
                       content_type=None, title=None, publisher=None, published_at=None,
                       text="", fetched_at=now)


class Engine(Protocol):
    """A specialist check. Must never raise for expected failures: record them
    on the blackboard and return an EngineRun with status partial/skipped/failed."""
    name: str

    def run(self, ctx: RunContext, findings: Findings) -> EngineRun: ...
