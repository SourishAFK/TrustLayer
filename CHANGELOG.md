# Changelog

## 2026-10-18–22 — The website, answer-key checks, and two reliability fixes

### Added

- `frontend/site`: the public website (Vite, React 19, TypeScript, Tailwind 4, GSAP,
  Lenis, three.js). A landing page with a 3D "Trust Clock", cited incidents, one section
  and one sign-up link per audience, how a check works, the pushback test, the Trust
  Clock (simulated data, labelled), the blind-benchmark results with their caveats, and
  the "trust grade for every AI" vision. Also an audience-tagged sign-up page, a live
  demo that streams a real Quick Check (with labelled, dated recordings when the demo is
  off), and a printable sample Bot Check-up report for a fictional lender. Every number
  links to its source. Unit tests (vitest) and browser tests (Playwright, API mocked).
- `POST /v1/leads`: website sign-ups tagged with their audience, campaign and landing
  page; consent required, honeypot, per-visitor and daily limits, salted IP hash.
  `python -m backend.admin leads` counts sign-ups per audience.
- `POST /v1/demo/verify/stream`: the website's live demo. Off unless
  `TRUSTLAYER_PUBLIC_DEMO` is on; Quick Checks only; capped per visitor and per day;
  never stored. With an answer key it checks a bot's answer only against that policy.
- Answer-key mode (`documents_role: "answer_key"`): the caller's documents become the
  ground truth for the check (authoritative, labelled as such in the report).
- `frontend/site/record_demo.py` re-records the demo's fallback runs through the real
  engine, and refuses to save a run whose AI calls failed.
- `render.yaml` gains the `trustlayer-site` static service and the website settings.

### Fixed

- Gemini judge calls whose connection dropped before any reply (`RemoteProtocolError`)
  failed the claim outright. They are now retried once; timeouts are still not retried.
  The website's support-bot example went from 2 of 4 runs right to 4 of 4.
- Passages were cut at abbreviations ("prime vs. | composite"), so the sentence holding
  the evidence could be split and a real citation judged "does not support". A period
  followed by a lowercase letter no longer ends a sentence. Offline benchmark unchanged
  (dev 100% / 0 false approvals with the ideal reader; held-out post-hoc 77.7% / 0).
- Corrections drawn from the caller's documents read "(per your answer key)" instead of
  the internal "(per answer-key)".

### After an outside review (Playwright, desktop and phone)

- Fixed: the home page scrolled sideways by 144px on desktop, and on phones the overflow
  widened the page so the menu button sat half off screen. The section glows bled 10%
  past each side; they now bleed only above and below. Browser tests now check page and
  nav width on every page at 390px (with phone emulation) and 1440px.
- Praise with no yardstick ("the best analytics tool", "amazing", "the most beautiful")
  is now NOT CHECKABLE instead of UNVERIFIED. Measurable superlatives ("best-selling",
  "the fastest", "the lowest fees") stay checkable. Both benchmarks unchanged.
- The demo's main example now shows a fact confirmed from Wikipedia, a math slip caught,
  and an opinion marked not checkable. Its step list and claim labels use plain words
  instead of engine messages, and the recorded-run banner says "Live checks are paused,
  so here's a recorded run…" instead of sounding broken.
- Sign-ups: a "Would you pay for a full check?" question (stored as `would_pay`, counted
  by `admin leads`), and a fallback when sending fails: a pre-filled email to
  `VITE_CONTACT_EMAIL` and a "Copy my details" button.
- Readability: every visible text is at least 12px (now a browser test), muted labels are
  lighter, the light streaks stay out of text and forms, and the custom cursor gives way
  to the normal one over forms, buttons and messages. The build warns when `SITE_URL`
  is missing, since link previews then have no image.

### Second review round

- Fixed: on a 390px phone with animations running, the home page still widened to 426px.
  The cause was the fanned report pages in "What you get": their 3D spread reached past
  the screen edge only while animating, so the reduced-motion test missed it. The fan is
  narrower on phones, the section clips sideways, and `html` clips as well as `body`. The
  width test now runs with animations on and real phone emulation, after the intro and
  after scrolling to the bottom, and checks that the viewport itself stays 390px wide
  (it fails on the old code with 426).
- "Would you pay for a full check?" now asks for a price: No, just curious / Up to $50 /
  $50–200 / $200+. `admin leads` breaks the answers down by audience.
- Optional cookie-free analytics (Plausible), off unless `VITE_ANALYTICS_DOMAIN` is set:
  pageviews, scroll depth, and clicks on the audience buttons.

### Known gaps

- "Revenue grew from $10M to $30M, a 2x increase" is not caught: extraction splits the
  appositive "a 2x increase" into its own claim, so the multiple has nothing to compare.
  "Revenue grew 50% from $10M to $30M" is caught. Arithmetic written with currency
  symbols ("12 × $20 = $260") is not checked; plain numbers are.

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
