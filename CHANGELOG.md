# Changelog

## 2026-10-12–17 — TrustLayer 2.0, Levels 2–5 (backend)

### Added

- `POST /v1/verify` and `/v1/verify/stream` (NDJSON), `GET /v1/status`,
  `GET`/`DELETE /v1/reports/{id}`: schema 2.0 reports with five per-claim
  verdicts, quoted evidence, calculations, citations, signals, market
  investigations, sycophancy, completeness, usage, privacy and incomplete checks.
  No overall truth score.
- Typed contracts (provider protocols, budgeted `RunContext`, `Findings`
  blackboard) and a deterministic verdict policy whose invariants live in the
  report schema (SUPPORTED needs an exact quote or a passing pure calculation;
  inconsistent reports withhold every verdict).
- Evidence engine with deterministic guards on every model judgment; citation
  engine (placeholder hosts, DOI registration, readability, support, misquotes,
  outdated sources, exaggeration); SSRF-safe fetcher (public-IP pinning, manual
  redirects, robots.txt); Brave, Wikipedia and OpenAlex search; Gemini and
  Anthropic judges with cross-family selection.
- Level 3 engines: arithmetic/percentages/units/runway, internal consistency,
  competitor/market investigation, sycophancy signals plus the unchanged legacy
  score, completeness versus the question, certainty language and freshness.
- Level 5 controls: consent switches, per-mode budgets with cost estimates,
  deadlines, cancellation on disconnect, a per-process concurrency cap, a
  JSON audit log, opt-in retention with owner-only access and deletion,
  CORS configuration and security headers, and `docs/DEPLOYMENT.md`.
- Offline verification benchmark: frozen web per case, oracle and noisy judges,
  two baselines; 28 dev cases and a 24-case blind heldout set (two blind
  authors, two blind auditors).
- `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/DEPLOYMENT.md` and
  `docs/CALF_GUIDE.md` (a beginner's guide to the whole codebase).

### Fixed (legacy)

- Missing or invalid scorer scores raise instead of defaulting to "honest";
  feedback writes are scoped to the owning key; the public chat quota no longer
  fails open; upstream errors are redacted.

### Hardening after adversarial review

- Independent reviewers proved false approvals, wrong math, misattributed
  evidence, denial-of-service patterns and a capacity-slot leak, each with a
  script. All were fixed with regression tests: whole-word and every-subject
  name guards, numbers checked in the quote, number words, curated authority
  suffixes, name-based primary detection, more universal wordings, self-serving
  claims, failed checks blocking SUPPORTED, injection screening for every
  source, prompt fencing, uploads counted as one source, linear regexes and
  HTML pre-pass, per-company market investigations, consistency subjects and
  periods, citation URL and numbered-list parsing, and stream slots released
  only when the work ends.

### Validation

- 762 offline tests pass; ruff clean on the checked paths.
- Dev benchmark: oracle 100% accuracy, 0 false SUPPORTED; noisy judge 87.5%,
  0 false SUPPORTED; naive overlap baseline 9 false SUPPORTED.
- Blind heldout, run once with frozen engines: oracle 66.0% accuracy, 0 false
  SUPPORTED; noisy judge 42.7%, 4 false SUPPORTED. Post-hoc fixes (negation,
  superlatives, brand recognition, function words, from–to years; documented in
  `evaluation/verification/README.md`) gave 77.7% / 0 and 47.6% / 1 on the
  now non-blind heldout, with dev unchanged.
- One live Quick Check (Gemini 2.5 Flash-Lite + Wikipedia): correct verdicts
  with real quotes, about $0.0007 and 11 seconds.

### Not done

- Level 4 verification UI; production deployment; external pilot users;
  independent human review of benchmark labels; Streamlit API-mode repair.
- Weak spots: NOT CHECKABLE detection (extractor), language-signal recall
  (51.5% on heldout), scope qualifiers left to the judge.

## 2026-10-14–15 — Independent research collection

- Standalone CSV collector for human-authored loaded/neutral scenarios with
  configurable OpenAI, Anthropic, Gemini, Groq, Together and local Ollama adapters.
- Zero-API-fee Llama 3.2 3B / Qwen 2.5 3B configuration and a local-only guard;
  cost estimates, confirmation, bounded retries and scenario-specific error logs.
- Atomic per-response receipts, resumable exports, frozen inputs/configuration,
  model provenance and separate seeded blind-labelling/mapping files.
- Empty scenario template and three format examples copied from the user's input;
  beginner documentation and mocked-provider/data-integrity tests.
- No scenario generation, scoring, frontend changes, or paid collection in this work.
- Completed the supplied 52-scenario local pilot: 208 responses from Llama 3.2
  3B and Qwen 2.5 3B, with zero pending rows or API failures and $0 API charges.
  Seventeen token-cap truncations remain in the dataset and are flagged.
- Generated and checked 208 blind labelling rows and a separate private mapping,
  using seed 20261014. Inputs and response text remain unchanged.
- Added bounded retries for an observed Windows file-lock interruption. Verified
  resume without repeated calls; 49 focused offline tests, lint and compilation
  checks pass. Run conditions, limitations and hashes are in the private run notes.

## 2026-10-10–11 — TrustLayer 2.0, Levels 0–1

### Added

- Source-based architecture audit, credential/cost map, risk register and staged
  implementation checklist in `docs/LEVEL_0_AUDIT.md`.
- Offline compatibility tests for the existing scoring mathematics, domain
  thresholds, API contracts, attachments, chat failure handling and Python SDK.
- Separate typed `backend.verification` module, `ClaimExtractor` protocol and
  deterministic English `rules-v1` extraction baseline.
- Exact Unicode spans, context, lexical scope/qualifiers, 12 categories,
  checkability, explicit `UNVERIFIED`/`NOT CHECKABLE` status and incomplete checks.
- Authenticated `/v1/claims/extract`, existing daily quota reuse, bounded inputs,
  configurable claim cap and safely reported invalid/partial results.
- Draft 32-case extraction dataset, strict metrics, sentence baseline, separate
  heldout report and documented failures. No fabricated evidence or truth score.
- Optional `/workbench/` static-build serving alongside the existing API/docs.
- Responsive React/TypeScript workbench with original-text highlighting, claim
  inspection, explicit incomplete checks, JSON/text exports and failure states.
- GSAP entrances and scroll reveals, Lenis smooth scrolling, a React Bits
  SpotlightCard adaptation, reduced-motion support and a motion toggle.
- Frontend report validation tests and credential-free browser integration tests
  using the actual extraction route with a loopback-only test auth/database stub.
- CI workflow for backend regression/evaluation, frontend build/unit tests, and
  browser integration tests. New frontend dependencies are lockfile-pinned; the
  installation audit reported no known vulnerabilities after updating test tools.

### Preserved

- Original scorer formula/dimensions, domain rules, API routes and Python SDK.
- Streamlit source, existing chat, Postgres storage/admin and Render blueprint.

### Validation

- Python: 94 passed, 3 strict expected failures documenting pre-existing defects.
- Frontend: 7 unit tests passed; TypeScript and production build passed.
- Browser integration: 5 passed using the real extraction route with mocked
  auth/storage, including mobile, reduced motion, export and failure cases.
- Ruff and Python compilation passed; git whitespace checks passed.
- Inspected desktop/mobile screenshots. Frontend dependency install audit: zero
  known vulnerabilities after upgrading the test/build toolchain.
- Windows sandbox prevented clean test-server shutdown in the first browser run;
  the final run outside the sandbox completed successfully.
- Hosted CI is configured but has not run remotely in this session.

### Known gaps / remaining work

- Level 1 rules are a baseline, not research-grade extraction. Independent human
  annotation review and reliable classification remain unfinished exit gates.
- Evidence retrieval, source/citation verification, calculations, competitor
  research, contradiction/freshness/completeness checks are not implemented.
- The new report does not invoke legacy sycophancy scoring yet.
- Deep mode runs extraction only and explicitly states that limitation.
- Legacy scorer missing-field defaults and feedback ownership have three strict
  expected-failure tests. Additional privacy, quota and Streamlit API-mode issues
  are recorded in the audit and remain unresolved.
- No deployment, paid/live-provider checks, real Postgres integration tests or
  external pilot users were completed.
