"""The verification pipeline: one request in, one schema-2.0 report out.

    extract claims -> deterministic checks -> plan -> research (engines in parallel)
                   -> post-research checks -> verdicts (aggregator) -> report

Every engine is isolated: an exception becomes a visible failed check, never a
crash and never a positive verdict. Every outbound call goes through RunContext,
which charges the per-request Budget. Nothing in this module stores the request.
"""

import json
import logging
import os
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Iterator

from pydantic import ValidationError

from backend.verification.aggregator import decide
from backend.verification.budget import Budget, limits_for
from backend.verification.contracts import Engine, Findings, Providers, RunContext
from backend.verification.planner import make_plan
from backend.verification.report import (
    CompletenessSection,
    EngineRun,
    ExtractionInfo,
    PrivacyNotice,
    ProgressEvent,
    ReportSummary,
    SycophancySection,
    UsageReport,
    VerificationReport,
    VerificationRequest,
    VerifiedClaim,
)
from backend.verification.schemas import Claim, VerificationStatus
from backend.verification.service import BASELINE_NOTE, extract_claims

logger = logging.getLogger(__name__)
MODE_LABEL = {"quick": "Quick Check", "deep": "Deep Investigation"}
EXHAUSTED = {
    "time": "The time limit was reached; checks still running were cut short.",
    "search_calls": "The search-call limit was reached; later searches did not run.",
    "page_fetches": "The page-read limit was reached; later sources were not read.",
    "model_calls": "The AI-call limit was reached; later sources were not assessed.",
    "model_tokens": "The AI token limit was reached; later sources were not assessed.",
    "cost": "The cost limit was reached; remaining paid checks did not run.",
    "cancelled": "The request was cancelled before every check finished.",
}
GENERAL_LIMITATIONS = [
    "Verdicts reflect only the sources TrustLayer could retrieve and read in this run; "
    "they are not a guarantee of truth.",
    "Counts describe extracted claims, not guaranteed verification coverage. There is no overall truth score.",
]


def configured_providers(request: VerificationRequest) -> Providers:
    """Real adapters from server configuration, filtered by the request's consent."""
    from backend.verification.fetcher import SafeFetcher
    from backend.verification.llm import select_llm
    from backend.verification.search import configured_search_providers
    from backend.verification.sycophancy import legacy_scorer

    ai = request.allow_ai_processing
    return Providers(
        llm=select_llm(request.source_model) if ai else None,
        search=configured_search_providers(request.mode) if request.allow_web_search else [],
        fetcher=SafeFetcher() if request.allow_web_search else None,
        legacy_scorer=legacy_scorer if ai and os.getenv("GEMINI_API_KEY") else None,
    )


def default_engines() -> list[list[Engine]]:
    """Three stages: deterministic checks, research (parallel), post-research checks."""
    from backend.verification.citations import CitationEngine
    from backend.verification.completeness import CompletenessEngine
    from backend.verification.consistency import ConsistencyEngine
    from backend.verification.evidence import EvidenceEngine
    from backend.verification.freshness import FreshnessEngine, UncertaintyEngine
    from backend.verification.market import MarketEngine
    from backend.verification.numerical import NumericalEngine
    from backend.verification.sycophancy import SycophancyEngine

    return [
        [NumericalEngine(), ConsistencyEngine(), UncertaintyEngine()],
        [EvidenceEngine(), CitationEngine(), MarketEngine(), SycophancyEngine(), CompletenessEngine()],
        [FreshnessEngine()],
    ]


def retention_hours() -> int:
    value = int(os.getenv("TRUSTLAYER_REPORT_RETENTION_HOURS", "0") or 0)
    if not 0 <= value <= 24 * 365:
        raise ValueError("TRUSTLAYER_REPORT_RETENTION_HOURS must be between 0 and 8760.")
    return value


def check_config(mode: str) -> None:
    """Validate every setting a run needs, before any work starts. Raises ValueError."""
    from backend.verification.aggregator import freshness_days
    from backend.verification.fetcher import allowed_ports
    from backend.verification.service import claim_limit

    limits_for(mode)
    claim_limit()
    freshness_days()
    retention_hours()
    allowed_ports()


def _run_engine(engine: Engine, ctx: RunContext, findings: Findings) -> EngineRun:
    started = time.perf_counter()
    ctx.progress(engine.name, "started", f"Running {engine.name} check")
    try:
        run = engine.run(ctx, findings)
    except Exception as exc:  # noqa: BLE001 — isolate engines; never echo exception text
        logger.warning("Engine %s failed (%s)", engine.name, type(exc).__name__)
        findings.incomplete_check(f"The {engine.name} check stopped unexpectedly; claims it had not "
                                  "reached remain unverified.")
        run = EngineRun(engine=engine.name, status="failed",
                        duration_ms=round((time.perf_counter() - started) * 1000, 1),
                        detail="Stopped unexpectedly. Results recorded before the failure were "
                               "individually validated and kept.")
    progress_status = {"completed": "completed", "not_applicable": "skipped",
                       "skipped": "skipped", "partial": "completed"}.get(run.status, "failed")
    ctx.progress(engine.name, progress_status, run.detail)
    return run


def _safe_decide(claim: Claim, findings: Findings, now: datetime) -> VerifiedClaim:
    try:
        return decide(claim, findings.claims[claim.claim_id], now)
    except Exception as exc:  # noqa: BLE001 — any bug here must withhold, not crash
        logger.warning("Verdict for %s failed validation (%s)", claim.claim_id, type(exc).__name__)
        findings.incomplete_check(f"The verdict for {claim.claim_id} could not be assembled safely; "
                                  "it is shown as unverified.")
        checkable = claim.objectively_checkable
        return VerifiedClaim(
            **{k: getattr(claim, k) for k in ("claim_id", "exact_text", "text_span", "claim_type",
                                              "context", "qualifiers", "scope", "objectively_checkable")},
            verification_status=VerificationStatus.unverified if checkable else VerificationStatus.not_checkable,
            evidence_strength="none", explanation="Findings for this claim failed validation and were withheld.",
            missing_evidence=["A valid investigation of this claim."], investigated=False, checked_at=None)


def _incomplete(ctx: RunContext, findings: Findings, providers: Providers) -> list[str]:
    request, plan = ctx.request, ctx.plan
    items = list(findings.incomplete)
    items += [EXHAUSTED[r] for r in ctx.budget.exhausted if r in EXHAUSTED]
    if plan.deferred:
        items.append(f"{len(plan.deferred)} checkable claim(s) were not researched in this run; "
                     "each one lists the reason.")
    if not request.allow_web_search:
        items.append("Web search and page reading were turned off for this request.")
    elif not providers.search:
        items.append("No search provider is configured on this server; claims could only be "
                     "checked against sources you supplied.")
    if not request.allow_ai_processing:
        items.append("AI processing was turned off; retrieved sources could not be assessed for support.")
    elif providers.llm is None:
        items.append("No AI provider is configured; retrieved sources could not be assessed for support.")
    if ctx.llm_failures:
        items.append(f"{ctx.llm_failures} AI call(s) failed; the affected claims remain unverified.")
    if findings.sycophancy is None:
        items.append("Sycophancy assessment did not run in this report.")
    if findings.completeness is None:
        items.append("Completeness and omission analysis did not run in this report.")
    return list(dict.fromkeys(items))


def _privacy(ctx: RunContext) -> PrivacyNotice:
    retention = retention_hours()
    search = sorted(u.split(":", 1)[1] for u in ctx.used if u.startswith("search:"))
    ai = sorted(u.split(":", 1)[1] for u in ctx.used if u.startswith("ai:"))
    used_web = bool(search) or ctx.budget.page_fetches > 0
    note = ("Claim text was sent only to the providers listed here." if (search or ai)
            else "No text left this server for third-party processing.")
    if ctx.request.documents and not ctx.documents_sent_to_ai:
        note += " Your documents were not sent to any AI provider."
    return PrivacyNotice(web_search_used=used_web, search_providers=search, ai_providers=ai,
                         documents_sent_to_ai=ctx.documents_sent_to_ai, stored=False,
                         retention_hours=max(0, retention), note=note)


def verify(request: VerificationRequest, *, providers: Providers | None = None,
           engines: list[list[Engine]] | None = None,
           emit: Callable[[ProgressEvent], None] | None = None,
           now: datetime | None = None,
           cancel: threading.Event | None = None,
           finalize: Callable[[VerificationReport], VerificationReport] | None = None,
           ) -> VerificationReport:
    """Run a full verification. Raises ValueError only for invalid server config.

    `finalize` (optional) post-processes the finished report — the API uses it to
    persist reports when retention is enabled and to write the audit log line.
    """
    report = _verify(request, providers=providers, engines=engines, emit=emit, now=now, cancel=cancel)
    if finalize is None:
        return report
    try:
        return finalize(report)
    except Exception as exc:  # noqa: BLE001 — post-processing must never lose the report
        logger.warning("Report finalizer failed (%s)", type(exc).__name__)
        return report


def _verify(request: VerificationRequest, *, providers, engines, emit, now, cancel) -> VerificationReport:
    started = time.perf_counter()
    created_at = now or datetime.now(timezone.utc)
    check_config(request.mode)
    limits = limits_for(request.mode)
    budget = Budget(limits, cancel=cancel)
    providers = providers if providers is not None else configured_providers(request)
    stages = engines if engines is not None else default_engines()

    extraction = extract_claims(request.response_text)
    ctx = RunContext(request=request, claims=extraction.claims, budget=budget, now=created_at,
                     llm=providers.llm, search=providers.search, fetcher=providers.fetcher,
                     legacy_scorer=providers.legacy_scorer, **({"emit": emit} if emit else {}))
    ctx.progress("extraction", "completed" if extraction.status != "failed" else "failed",
                 f"Found {len(extraction.claims)} claim(s)")
    findings = Findings([c.claim_id for c in extraction.claims])
    runs: list[EngineRun] = []

    if extraction.status != "failed":
        deterministic, research, post = stages
        runs += [_run_engine(e, ctx, findings) for e in deterministic]
        can_research = bool(providers.search) or bool(request.documents) or bool(
            request.source_urls and providers.fetcher)
        ctx.plan = make_plan(extraction.claims, request, limits, findings,
                             can_research=can_research, mode_label=MODE_LABEL[request.mode])
        checkable = sum(c.objectively_checkable for c in extraction.claims)
        ctx.progress("planning", "completed",
                     f"Researching {len(ctx.plan.evidence)} of {checkable} checkable claim(s)")
        if research:
            with ThreadPoolExecutor(max_workers=len(research), thread_name_prefix="engine") as pool:
                runs += list(pool.map(lambda e: _run_engine(e, ctx, findings), research))
        runs += [_run_engine(e, ctx, findings) for e in post]

    claims = [_safe_decide(c, findings, created_at) for c in extraction.claims]
    if providers.llm is not None and request.source_model and providers.llm.name in ("gemini", "anthropic"):
        from backend.verification.llm import independence_note

        note = independence_note(providers.llm, request.source_model)
        if note:
            findings.limitation(note)
    if findings.rejected_evidence:
        findings.limitation(f"{findings.rejected_evidence} evidence item(s) failed validation and "
                            "were discarded rather than shown.")
    incomplete = _incomplete(ctx, findings, providers)
    if extraction.status == "failed":
        incomplete.insert(0, "Claim extraction failed; no claims were checked.")
    counts = {s: sum(VerificationStatus(c.verification_status) == s for c in claims)
              for s in VerificationStatus}
    engine_trouble = any(r.status in ("partial", "failed") for r in runs)
    status = ("failed" if extraction.status == "failed"
              else "partial" if incomplete or engine_trouble or extraction.status == "partial"
              else "completed")
    signals = findings.signals
    report_fields = dict(
        report_id=str(uuid.uuid4()), mode=request.mode, status=status,
        response_text=request.response_text, original_question=request.original_question,
        source_model=request.source_model, created_at=created_at,
        extraction=ExtractionInfo(method=extraction.method, status=extraction.status,
                                  omitted_segments=extraction.omitted_segments,
                                  limitations=[BASELINE_NOTE] + extraction.limitations),
        claims=claims, citations=findings.citations, signals=signals,
        sycophancy=findings.sycophancy or SycophancySection(
            status="skipped", method="none", note="Sycophancy assessment did not run."),
        completeness=findings.completeness or CompletenessSection(
            status="skipped", method="none", note="Completeness analysis did not run."),
        market=findings.market, engines=runs,
        summary=ReportSummary(
            total_extracted=len(claims), supported=counts[VerificationStatus.supported],
            contradicted=counts[VerificationStatus.contradicted],
            disputed=counts[VerificationStatus.disputed],
            unverified=counts[VerificationStatus.unverified],
            not_checkable=counts[VerificationStatus.not_checkable],
            investigated=sum(c.investigated for c in claims), checks_incomplete=len(incomplete),
            signals_critical=sum(s.severity == "critical" for s in signals),
            signals_warning=sum(s.severity == "warning" for s in signals)),
        limitations=GENERAL_LIMITATIONS + findings.limitations,
        incomplete_checks=incomplete,
        privacy=_privacy(ctx),
    )
    usage = UsageReport(
        duration_ms=round((time.perf_counter() - started) * 1000, 1), model_calls=budget.model_calls,
        model_input_tokens=budget.input_tokens, model_output_tokens=budget.output_tokens,
        search_calls=budget.search_calls, pages_fetched=budget.page_fetches,
        estimated_cost_usd=round(budget.cost_usd, 6), cost_basis=budget.cost_basis(),
        limits=limits.public(), exhausted=list(budget.exhausted))
    try:
        return VerificationReport(**report_fields, usage=usage, completed_at=datetime.now(timezone.utc))
    except ValidationError as exc:
        # A bug upstream produced an inconsistent report. Withhold every verdict.
        logger.error("Report failed validation (%s errors)", exc.error_count())
        return _withheld(report_fields, usage)


def _withheld(fields: dict, usage: UsageReport) -> VerificationReport:
    note = "The report failed internal consistency checks, so all verdicts were withheld."
    fields = {**fields, "status": "failed", "claims": [], "citations": [], "signals": [], "market": [],
              "incomplete_checks": [note],
              "summary": ReportSummary(total_extracted=0, supported=0, contradicted=0, disputed=0,
                                       unverified=0, not_checkable=0, investigated=0,
                                       checks_incomplete=1, signals_critical=0, signals_warning=0)}
    return VerificationReport(**fields, usage=usage, completed_at=datetime.now(timezone.utc))


def stream_ndjson(request: VerificationRequest, *, on_start: Callable[[], None] | None = None,
                  on_done: Callable[[], None] | None = None, **kwargs) -> Iterator[str]:
    """Progress events, then the report, as newline-delimited JSON.

    `on_start` runs once the verification thread is running and `on_done` when it finishes —
    not when the consumer stops reading — so a caller can hold a capacity slot for the real work.
    """
    events: queue.Queue = queue.Queue()
    outcome: dict = {}
    cancel = threading.Event()

    def work():
        try:
            outcome["report"] = verify(request, emit=events.put, cancel=cancel, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Streaming verification failed (%s)", type(exc).__name__)
        finally:
            try:
                if on_done is not None:
                    on_done()  # before the end marker: the slot is free by the time the stream ends
            finally:
                events.put(None)

    threading.Thread(target=work, name="verify-stream", daemon=True).start()
    if on_start is not None:
        on_start()
    try:
        while (event := events.get()) is not None:
            yield json.dumps({"type": "progress", "event": event.model_dump(mode="json")}) + "\n"
    finally:
        # Runs on normal completion and when the consumer closes the stream early
        # (client disconnect): remaining provider calls are refused immediately.
        cancel.set()
    if "report" in outcome:
        yield json.dumps({"type": "report", "report": outcome["report"].model_dump(mode="json")}) + "\n"
    else:
        yield json.dumps({"type": "error",
                          "message": "Verification could not complete. No verdicts were produced."}) + "\n"
