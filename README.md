# TrustLayer

**Confidence is not trust.** TrustLayer checks AI-generated answers claim by
claim. It splits an answer into individual claims, researches the risky ones
against independent sources, and gives each claim one evidence-backed verdict:

| Verdict | Meaning |
| --- | --- |
| **SUPPORTED** | Retrieved evidence (an exact quote from a fetched source) or a deterministic calculation supports it |
| **CONTRADICTED** | Credible evidence conflicts with it, or its own arithmetic is wrong (with a correction) |
| **DISPUTED** | Credible sources disagree |
| **UNVERIFIED** | Not enough evidence either way — and the report says what is missing |
| **NOT CHECKABLE** | Opinion, prediction or private experience |

There is no overall "truth score". Models only *read* passages; deterministic
code checks every quote, number and source, and a fixed policy decides the
verdict. Alongside the facts, the report flags citations that are fabricated or
don't say what they're cited for, wrong math, contradictions inside the answer,
over-confident or flattering language, missing parts of the question, stale
facts, and — for startup and market research — whether "no competitors" claims
survive a competitor search. The original sycophancy score is kept as a
separate section.

## Status

| Level | What | Status |
| --- | --- | --- |
| 0 | Audit of the original sycophancy detector, regression tests | Done ([audit](docs/LEVEL_0_AUDIT.md)) |
| 1 | Claim extraction with exact spans (`/v1/claims/extract`), React workbench | Done; extraction categories are weak |
| 2 | Evidence research, SSRF-safe fetching, citation checks, verdict policy (`/v1/verify`) | Done |
| 3 | Math, consistency, market/competitor, sycophancy, completeness, freshness engines | Done |
| 4 | Website ([frontend/site](frontend/site/README.md)): landing page, audience-tagged sign-ups, live demo with claims colored by verdict and their evidence, printable sample Bot Check-up report | Built and tested; the live demo stays off until a paid model key is set (labelled recordings play meanwhile) |
| 5 | Consent, budgets, deadlines, concurrency cap, audit log, retention, runbook | Done; **not deployed, no external pilots yet** |

Read: [architecture](docs/ARCHITECTURE.md) · [security model](docs/SECURITY.md) ·
[deployment and operations](docs/DEPLOYMENT.md) · [verification benchmark](evaluation/verification/README.md) ·
[extraction benchmark](evaluation/README.md) · [changelog](CHANGELOG.md) ·
[a beginner's guide to the whole codebase](docs/CALF_GUIDE.md).

## Quick start

Python 3.12+.

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env   # edit it; never commit secrets
./.venv/Scripts/python.exe -m uvicorn backend.main:app --reload --port 8000
```

On macOS/Linux use `.venv/bin/python`. Authenticated routes need
`DATABASE_URL` (Postgres/Supabase) and a caller key from the admin CLI
(`python -m backend.admin --help`). Everything else is optional:

- **AI judges**: `ANTHROPIC_API_KEY` and/or `GEMINI_API_KEY`. With both, a judge
  from a different model family than the answer's author is preferred.
- **Search**: `BRAVE_SEARCH_API_KEY` (web), `TRUSTLAYER_CONTACT` (required by
  Wikipedia), OpenAlex (free).
- Without any keys the service still runs every deterministic check and marks
  what it could not research as UNVERIFIED.

All options, including per-mode budgets, are documented in [.env.example](.env.example)
and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Verification API

```bash
curl -X POST http://127.0.0.1:8000/v1/verify \
  -H "Authorization: Bearer tl_..." -H "Content-Type: application/json" \
  -d '{"response_text": "Acme was founded in 2015, has no competitors, and its revenue grew from $2M to $3M, an increase of 80%.",
       "original_question": "Is Acme a good investment?", "mode": "quick"}'
```

| Field | Notes |
| --- | --- |
| `response_text` | The AI answer, up to 24,000 characters |
| `original_question` | Optional; enables sycophancy and completeness checks |
| `mode` | `quick` (≤25 s, ≤$0.10 by default) or `deep` (≤90 s, ≤$1.00; adds competitor research and extra queries) |
| `source_urls`, `documents` | Optional sources of your own (≤5 URLs, ≤3 documents) |
| `source_model` | Who wrote the answer, e.g. `gpt-4o`, so a different family judges it |
| `allow_web_search`, `allow_ai_processing`, `share_documents_with_ai` | Consent switches (documents are never sent to an AI provider unless the last one is `true`) |
| `documents_role` | `context` (default) or `answer_key`: your documents become the ground truth, e.g. checking a support bot against your own policy |

The report (schema 2.0) contains every claim with its exact span, verdict,
evidence (URL, domain, source type, dates, passage and exact quote),
contradictions, calculations, related sources, what is missing, and the checks
that ran; plus citations, signals, market investigations, sycophancy,
completeness, usage (time, calls, estimated cost), privacy (which providers
received text) and `incomplete_checks`.

- `POST /v1/verify/stream` — the same, as NDJSON progress lines ending with the report.
- `GET /v1/status` — limits per mode and configured provider names (never keys).
- `GET`/`DELETE /v1/reports/{id}` — only when `TRUSTLAYER_REPORT_RETENTION_HOURS` > 0; owner-only.

## Website

`frontend/site` is the public site: a landing page with a 3D "Trust Clock", one section
and one sign-up link per audience (AI product teams, AI-written documents, support
bots), a live demo that streams a real Quick Check, and a printable sample report.
Sign-ups land in the `leads` table tagged with their audience; count them with
`python -m backend.admin leads`. See [its README](frontend/site/README.md) to run,
test and deploy it.

## Independent research collection

For human-authored loaded/neutral prompt experiments, use the separate
[research runner and blind-labelling guide](research/README.md). It includes
a zero-API-fee local Llama/Qwen configuration, resumable CSV collection and
offline tests. It does not call the application or score any responses.

## Claim extraction (Level 1) and the workbench

`POST /v1/claims/extract` returns schema 1.0 claims (exact Unicode code-point
spans, end-exclusive; context, qualifiers, 12 categories, checkability) without
any research. The React workbench in `frontend/web` displays them:

```powershell
cd frontend/web; npm ci; npm run dev     # open the Vite URL at /workbench/
```

Or `npm run build` and visit `http://127.0.0.1:8000/workbench/`. The workbench
shows extraction only; the full verification view is the website's live demo
(`frontend/site`).

## Original detector and SDK

The original sycophancy detector (`/score`, `/feedback`, `/chat`,
`/chat/feedback`, Streamlit app `frontend/app.py`) is unchanged in formula and
bands, and now fails closed on malformed model output. See the
[Python SDK](clients/python/README.md). Sycophancy measures behavior, not truth.

## Tests and evaluation (no paid credentials)

```powershell
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check backend/verification backend/main.py backend/store.py tests evaluation research
./.venv/Scripts/python.exe -m evaluation.verification.run --split all --judge both
./.venv/Scripts/python.exe -m evaluation.run --split all
```

Every external service is faked; the suite (750+ tests) runs offline in seconds.

**Verification benchmark** ([details](evaluation/verification/README.md)) — a
frozen web per case, an oracle judge (perfect reader), a noisy judge (says
"supports" to everything) and two baselines:

| Split | System | Accuracy | False SUPPORTED |
| --- | --- | --- | --- |
| dev (28 cases, 32 claims; not blind) | pipeline + oracle | 100% | 0 |
| dev | pipeline + noisy judge | 87.5% | **0** |
| dev | baseline: naive word overlap | 56.2% | 9 (75% of its SUPPORTED) |

| heldout (24 cases, 103 claims; blind, run once frozen) | pipeline + oracle | 66.0% | **0** |
| heldout, same run | pipeline + noisy judge | 42.7% | 4 (26.7%) |
| heldout, same run | baseline: naive word overlap | 41.7% | 31 (55.4%) |
| heldout after post-hoc fixes (no longer blind) | pipeline + oracle / noisy | 77.7% / 47.6% | 0 / 1 |

The blind heldout run exposed real defects (negated quotes, superlatives,
brand-name recognition); the fixes made after seeing it, and the error
analysis, are documented in the [benchmark README](evaluation/verification/README.md#results-october-17-2026).
Most remaining errors are opinions the extractor fails to mark NOT CHECKABLE;
language-signal recall is 51.5%.

Labels are agent-written drafts awaiting independent human review, and the
corpora are synthetic. The extraction benchmark's honest numbers (heldout
precision 93.8%, recall 88.2%, category accuracy 33.3%) are in
[evaluation/README.md](evaluation/README.md).

## Costs

Measured live: a Quick Check of three claims with Gemini 2.5 Flash-Lite as judge
and Wikipedia as search used 3 model calls, 3,744 tokens and 3 searches —
about **$0.0007** in 11 seconds. Brave Search costs about $5 per 1,000 requests
($5/month free credit); Wikipedia, OpenAlex and doi.org are free. Every report
carries its own cost estimate, and per-request caps are enforced before each
paid call. Details: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#4-costs).
