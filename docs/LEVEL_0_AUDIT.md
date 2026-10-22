# TrustLayer 2.0 — Level 0 audit and implementation plan

Audit date: October 10, 2026. Source inspection, deterministic fixtures and mocked
integrations are the evidence for this report. Historical claims in CONTEXT.md
were not treated as proof of live functionality. No paid provider or live
Postgres instance was contacted.

## Existing architecture

```text
Streamlit frontend/app.py ── API mode ── FastAPI backend/main.py
                         └─ direct mode ── SycophancyScorer
Python SDK / developer docs ──────────── /score, /feedback
Public chat ──────────────────────────── /chat, /chat/feedback
                                         │
                       ┌─────────────────┴────────────────┐
                 scorer.py + domain_rules.py           store.py
                       │                                  │
                  Gemini API                    Postgres / Supabase
```

| Component | Implemented behavior | Reuse decision |
| --- | --- | --- |
| `backend/scorer.py` | Two Gemini passes: intent gap and response honesty; model/key fallback and RPM tracking; Pydantic output types | Preserve formula, dimensions, scorer API and domain seam |
| `backend/domain_rules.py` | General, fintech and customer-service domain adapters; high-stakes keyword rules and verdict bands | Preserve all adapters |
| `backend/main.py` | Typed HTTP routes, query alias, bearer or X-API-Key auth, attachment validation, daily limits, usage logging, public chat | Add a versioned extraction endpoint; keep existing contracts |
| `backend/store.py` | Lazy Postgres pool, API keys, atomic per-key daily counters, usage data and feedback | Reuse auth/rate accounting; do not put extraction input into legacy usage rows |
| `backend/admin.py` | Key creation/list/revoke, input-logging controls and usage export | Preserve administration |
| `backend/chat.py` | Gemini generation before the existing sycophancy assessment | Preserve; separate from independent verification |
| `frontend/app.py` | Streamlit examples, context/attachment ingestion, result cards, rewrite and detail displays; direct and API modes | Keep as legacy UI; add React workbench alongside it |
| `clients/python/trustlayer` | `score`, `feedback`, background `audit`, dictionary/attribute result access, typed SDK errors and image encoding | Preserve SDK signatures and payloads |
| `docs/index.html`, `render.yaml`, `.github/workflows/keepwarm.yml` | Developer docs, API deployment blueprint and warm-up workflow | Preserve; new web build has separate explicit instructions |

The sycophancy score is `round((1 - honesty) * (0.6 + 0.4 * gap) * 100)`.
Generic/non-high-stakes bands are 30/60; GeneralDomain uses 15/45; high-stakes
fintech and customer service use 20/45. These are **behavioral scores**, not
probabilities of factual truth. The new reports do not combine them into a truth score.

No independent search, safe page retrieval, citation checking, atomic extraction,
verification dataset, or automated test suite existed at the start of this audit.
No enterprise vendor-specific integrations beyond the API/SDK, Postgres,
deployment and domain adapters were found. Model provenance is logged; routing
to a different judge model based on that provenance is not implemented.

## Level 0 regression demonstration

New offline regression suites verify the actual score formula, domain thresholds,
two-pass scoring using a mock Gemini response, original route availability,
authentication, request aliases, response shape, quota handling, attachments,
input-logging selection, chat failure labeling and SDK calls/callbacks.

Result: **46 passed, 3 expected failures**. The expected failures below record
existing defects; they do not endorse those behaviors. This demonstrates tested
compatibility of local logic and API contracts, not that a deployed service or
live Gemini/Postgres integration is healthy.

## Existing debt and risks

| Priority | Finding | Evidence / follow-up |
| --- | --- | --- |
| High | Missing `honesty_score` becomes 1.0; missing `gap_score` becomes 0.0 | `SycophancyScorer.assess_honesty` / `detect_intent_gap`; strict expected-failure tests. Harden validation in a separately reviewed change without changing valid-score mathematics |
| High | Feedback writes are not scoped to authenticated ownership; public chat feedback uses sequential row IDs | `main.feedback`, `main.chat_feedback`, `store.record_feedback`; add ownership/token design and DB integration tests before pilots |
| High | Existing public chat can log raw inputs by default; generated alternatives may contain sensitive content even when raw-input logging is off | `main.chat`, `main.score`, `store.log_usage`; retention, deletion and explicit consent remain unimplemented |
| High | Public chat's database quota failure can fail open; fallback counter is per-process; message count is unbounded | `main.chat`, `_public_chat_allowed`, `ChatRequest`; harden before production beta |
| Medium | Mutable singleton scorer attribution/quota state has no concurrency protection; no end-to-end timeout, output-token or cost budgets | `get_scorer`, `_acquire_slot`, `_call_gemini_json`; introduce bounded provider adapter without changing legacy score formula |
| Medium | Provider parsing errors can echo raw model output through the HTTP error mapper | `_parse_json`, `_http_from_scorer_error`; redact errors before shared deployment |
| Medium | Streamlit API mode posts no API-key header and expects nested scorer fields instead of the flat `/score` response | `frontend/app.py` API call / `render_result`; direct mode remains separate. Repair with contract tests before claiming API mode works |
| Medium | Unpinned backend dependencies; no migration framework; no DB/real-provider tests | Requirements and store schema initialization; add version policy and migration/rollback checks |
| Medium | CORS is permissive; health route constructs the scorer | `main.py`; production origin configuration and independent health semantics need review |

This increment does not silently alter these legacy semantics. The new extraction
path assigns no positive evidence verdicts, does not use the model, fetch URLs or
persist text, and fails closed on authentication/quota-store outages.

### Status of these findings (updated October 17, 2026)

The table above is the October 10 snapshot. Fixes landed with Levels 2–5, each
with a regression test (the strict expected-failure tests became ordinary tests):

| Finding | Status | Where |
| --- | --- | --- |
| Missing `honesty_score` / `gap_score` defaults | **Fixed**: missing, non-numeric, NaN or boolean scores raise `ScorerError` (fail closed); valid-score math unchanged | `scorer._required_score` |
| Feedback ownership | **Mitigated**: feedback updates are scoped in SQL to the owning key (`api_key = ANY(owners)`); public chat feedback can be written once per entry. Public chat log ids are still sequential and visitors share the chat identity, so one visitor could label another's entry once | `store.record_feedback`, `main.feedback`, `main.chat_feedback` |
| Public chat raw-input logging | **Configurable**: `TRUSTLAYER_PUBLIC_CHAT_LOG_INPUTS` (default `true` keeps the original behavior; DEPLOYMENT.md recommends `false` without consent). Legacy usage-row retention/deletion is still not implemented | `main.chat` |
| Public chat quota fail-open, unbounded messages | **Fixed**: a quota-store failure falls back to the in-memory daily cap; at most 50 messages and 4 images per request | `main.chat`, `ChatRequest` |
| Singleton scorer state, no budgets | **Partly**: the new verification pipeline has per-request budgets, deadlines, cancellation and a concurrency cap; the legacy scorer singleton is unchanged | `verification/budget.py`, `main._VERIFY_SLOTS` |
| Raw model output echoed in errors | **Fixed**: upstream failures return fixed messages; logs record exception types only | `main._http_from_scorer_error` |
| Streamlit API mode mismatch | **Open** (frontend; out of scope for this pass) | `frontend/app.py` |
| Unpinned dependencies, no migrations, no DB tests | **Partly**: new dependencies are range-pinned (`httpx`, `anthropic`); schema creation is additive (`CREATE TABLE IF NOT EXISTS`); no migration framework or real-Postgres tests | `requirements*.txt`, `store.init_db` |
| Permissive CORS, health builds the scorer | **Partly**: origins configurable (`TRUSTLAYER_CORS_ORIGINS`; default `*` preserved) and every response gets `nosniff`/`no-referrer`/`DENY` headers; `/health` unchanged | `main.py` |

## Recommended architecture

Keep FastAPI and Python for the pipeline. Add `backend/verification/` with typed
source spans, candidates and reports; inject a `ClaimExtractor` protocol. Keep
the deterministic baseline independently runnable without API credentials.

```text
/v1/claims/extract → request validation → ClaimExtractor
                                     → exact-span validation and claim cap
                                     → extraction report → React workbench

Later: /v1/verifications → extraction → planner → authorized search adapter
    → safe evidence fetcher → specialist engines → verdict aggregator → report
```

Only the top pipeline is implemented now. In later levels:

- LLM adapters produce validated reasoning/extraction outputs with provider usage;
  they cannot invent externally sourced evidence or directly grant permissions.
- Search adapters return search results; evidence retrieval independently resolves
  safe URLs, captures passages and timestamps, and records publisher/source lineage.
- Engines consume claim/context/evidence and emit findings, missing evidence and
  execution status. Deterministic math stays separate from model reasoning.
- Aggregation alone maps findings into the five verdicts, retaining disagreements
  and source independence. Retrieval absence never proves a universal negative.
- Persistence records tenant ownership, consent and expiry. Report schemas carry
  dates, evidence provenance and incomplete checks; retention is an explicit policy.
- Future routing/autonomy modules can consume these reports. No routing, model
  intelligence product, autonomy controller or consequential actions are built now.

No speculative engine scaffolds or new database tables are needed for Level 1.
Keep the extraction endpoint versioned; evolve reports deliberately when evidence
objects become available. Unicode spans use code-point indices, not UTF-16 units.

## Concrete milestones and rough complexity

Estimates are engineering effort ranges for one experienced engineer after access
and product decisions are available; they exclude external pilot/review wait time.
They are planning estimates, not delivery promises.

| Level | Deliverables | Complexity / estimate | Exit gate |
| --- | --- | --- | --- |
| 0 | Source audit, compatibility suite, credential map, plan | Small; 1–2 days | Original behavior passes mocked regression tests; live integrations separately checked |
| 1 | Schemas, exact spans, categories, local extraction adapter, bounded endpoint, workbench, evaluation | Medium; 3–6 days for baseline; further extraction research needed | Human-reviewed extraction P/R and failure review; robust categories and genuinely unseen examples |
| 2 | Search-provider interface, authorized search, SSRF-safe retrieval, citation/quote association, evidence verdicts | Large; 1–2 weeks | Every SUPPORTED verdict has sufficient retrieved evidence; adversarial and unavailable-source cases abstain |
| 3 | Deterministic math/units, contradiction logic, market investigation, freshness/uncertainty, separate legacy sycophancy integration | Large; 2–3 weeks | Reviewed unseen cases; false approvals measured; negative market assertions never inferred from empty searches |
| 4 | Full evidence dashboard, evidence navigation, partial reports, readable/JSON exports, accessibility | Medium/large; 1–2 weeks | Nontechnical usability study shows users understand what remains unverified |
| 5 | Consent, tenant isolation, budgets, deadlines, monitoring, retention/deletion, deployment/runbooks, pilots | Large; 2–3 weeks plus pilots | Three real external users complete investigations without hidden failures or fabricated evidence |

### Checklist

- [x] Inspect all original application layers and record actual implementation.
- [x] Add offline original-scorer, API and SDK regression tests.
- [x] Preserve existing score formula, routes, SDK and domain integrations.
- [x] Add typed Level 1 extraction and a separately testable extractor protocol.
- [x] Add exact spans, context, lexical qualifiers/scope, categories and safe statuses.
- [x] Add request/claim limits, auth/rate accounting and visible partial failures.
- [x] Add draft evaluation fixtures, sentence baseline, strict metrics and failure report.
- [x] Add and browser-test the responsive workbench, claim highlighting, report exports and reduced-motion behavior.
- [ ] Independently review/adjudicate annotation boundaries and overlapping categories.
- [ ] Meet the Level 1 reliability gate; the current rule baseline has weak category accuracy.
- [x] Implement Level 2 independent evidence and citation verification (`/v1/verify`, see ARCHITECTURE.md).
- [x] Implement Level 3 specialist engines and separate sycophancy result in the new report.
- [x] Build the Level 4 verification UI: the website's live demo (verdict-colored claims, evidence, progress) and the sample report (`frontend/site`, October 2026).
- [ ] Run a usability study of the demo and report with real visitors.
- [x] Resolve most legacy privacy/ownership/fail-open debt (see the status table above).
- [x] Level 5 controls: consent switches, budgets, deadlines, concurrency cap, audit log, opt-in retention and deletion, runbook (DEPLOYMENT.md).
- [ ] Level 5 exit gate: production deployment and three external pilot users (requires real people).

## Credentials, costs and privacy

Existing authenticated routes require a Postgres `DATABASE_URL` and provisioned
TrustLayer API key. Existing `/score` needs `GEMINI_API_KEY`; additional keys,
models and RPM/retry options already exist. Existing public chat optionally uses
`TRUSTLAYER_CHAT_KEY`. These belong on the server. The workbench accepts only a
caller-owned TrustLayer access key and keeps it in memory.

Level 1 has **zero model/search API calls** and no extraction persistence. Its
endpoint increments the existing per-key daily request counter. Existing scoring
normally uses two model calls; chat normally adds a generation call; retries and
fallbacks increase usage. Provider billing depends on configured models, token
counts and the account's current pricing. No live price or spend was measured.

Level 2 will require an authorized search API credential and possibly an LLM
credential, explicit per-mode budgets, and documented provider terms. No search
provider has been selected or wired up in this increment. Confidential document
upload/third-party transmission is not enabled in the new workbench.
