# TrustLayer 2.0 — Verification architecture (Levels 2–5)

Status: living design document. The code is the source of truth; when they
disagree, fix this file. Level 0/1 history is in [LEVEL_0_AUDIT.md](LEVEL_0_AUDIT.md).

## The idea in one paragraph

An AI answer is a bundle of claims. TrustLayer splits the answer into claims,
runs cheap deterministic checks on every claim (math, certainty language,
internal contradictions), spends a bounded budget researching the riskiest
claims against independent sources, and then applies a fixed, deterministic
policy to decide one of five verdicts per claim. Models are used to *read*
(does this passage support this claim?) and their outputs are validated
(quotes must exist verbatim, numbers must match) before they count. Models
never decide verdicts and never invent evidence. When evidence is missing, the
answer is UNVERIFIED with the reason — never a guess, never a truth score.

## Pipeline

```text
POST /v1/verify  (or /v1/verify/stream for live NDJSON progress)
  │  auth (existing tl_ keys) → daily quota → concurrency guard
  ▼
pipeline.verify(request)
  1. extraction      service.extract_claims         rules-v1 (Level 1), exact spans
  2. deterministic   numerical, consistency, uncertainty            (Level 3)
  3. planning        planner.make_plan               rank + ration research
  4. research        evidence, citations, market, sycophancy, completeness  (parallel)
  5. post-research   freshness                                       (Level 3)
  6. verdicts        aggregator.decide               deterministic policy
  7. report          report.VerificationReport       schema 2.0, self-validating
```

Every engine runs isolated: an exception becomes a visible failed check
(`engines[]`, `incomplete_checks[]`), never a crash and never a positive verdict.

## Module map (`backend/verification/`)

| Module | Role | Level |
| --- | --- | --- |
| `schemas.py` | Schema 1.0 extraction contracts (unchanged) | 1 |
| `extractor.py` | `rules-v1` English claim extractor | 1 |
| `service.py` | `extract_claims()` shared core + Level 1 report | 1 |
| `report.py` | Schema 2.0 request/report models and their safety invariants | 2 |
| `contracts.py` | Provider Protocols, `RunContext` (budgeted calls), `Findings` blackboard, `Engine` | 2 |
| `budget.py` | Per-mode limits from env, thread-safe `Budget`, price table | 2 |
| `planner.py` | Ranks claims and rations research | 2 |
| `aggregator.py` | The verdict policy (no model calls) | 2 |
| `pipeline.py` | Orchestration, report assembly, NDJSON streaming | 2 |
| `fetcher.py` | SSRF-safe page fetching, robots.txt, HTML→text | 2 |
| `search.py` | Search adapters: Brave (web), Wikipedia (reference), OpenAlex (academic) | 2 |
| `llm.py` / `llm_anthropic.py` | Model adapters: Gemini / Anthropic, cross-family judge selection | 2 |
| `sources.py` | Domains, source types, passages, quote matching, injection screening | 2 |
| `evidence.py` | Engine B: factual verification (search → read → judge → validate) | 2 |
| `citations.py` | Engine C: citation parsing and validation | 2 |
| `numerical.py` | Engine E: deterministic arithmetic, percentages, units | 3 |
| `consistency.py` | Engine E: internal contradictions and reasoning checks | 3 |
| `market.py` | Engine D: competitor / market investigation | 3 |
| `sycophancy.py` | Engine F: lexical signals + the unchanged legacy scorer | 3 |
| `completeness.py` | Engine G: omissions versus the original question | 3 |
| `freshness.py` | Engine H: certainty language, time sensitivity, staleness | 3 |

The legacy sycophancy detector (`backend/scorer.py`, `backend/domain_rules.py`)
is reused as-is through `sycophancy.py`; its formula and bands do not change.

## Contracts every part follows

- **Providers** (`contracts.py`): `LLMProvider.complete_json(system, prompt,
  schema, max_output_tokens, timeout) -> LLMResult`, `SearchProvider.search(query,
  count, timeout) -> list[SearchResult]`, `Fetcher.fetch(url, timeout) -> FetchedPage`.
  Real adapters and test fakes both satisfy them. Tests never need credentials.
- **Engines never call providers directly.** They call `ctx.search_with`,
  `ctx.fetch`, `ctx.ask_llm`. Those charge the Budget, respect the request's
  consent switches, enforce the deadline, cache pages per run, and turn provider
  errors into "did not run" (`None`) — distinct from "ran and found nothing" (`[]`).
- **Engines write to the blackboard** (`Findings`): `add_evidence` (validated;
  invalid items are discarded and counted), `add_signal`, `note(claim_id, ...)`,
  `incomplete_check`, `limitation`, and response sections (`citations`,
  `sycophancy`, `completeness`, `market`). Only the aggregator turns notes into verdicts.
- **Model JSON schemas** passed to `complete_json` are strict: every object has
  `"additionalProperties": false` and lists all of its properties in `required`;
  only `type/properties/required/items/enum/description/title` are used; the top
  level carries a `title` naming the task (e.g. `stance_judgments`) so test fakes
  can dispatch on it.
- **Untrusted text** (AI responses, web pages, user documents) is always data.
  Prompts wrap it in tagged blocks and say so, and `sources.fence` neutralizes any
  tag-like text inside it (so a page cannot close or open a `<passage>`); passages
  containing instruction-like text are excluded — whether they came from search,
  the user's own links or documents, or a cited page — and reported as a signal.
- **No secrets or user text in logs or error messages.** Log exception *types*.

## Signal vocabulary

Signals are response-level observations, not verdicts. `kind` is one of:

| Engine | Kinds |
| --- | --- |
| evidence | `suspicious_source_instructions` |
| citations | `unsupported_citation`, `misleading_quotation`, `possible_exaggeration`, `outdated_source`, `suspicious_source_instructions` |
| consistency | `internal_contradiction`, `non_sequitur` |
| freshness (uncertainty) | `absolute_language`, `overconfident_prediction`, `missing_caveat` |
| sycophancy | `exaggerated_praise`, `unwarranted_agreement`, `assumption_validation`, `overconfident_recommendation`, `one_sided_framing` |

Severity: `critical` (likely misleading: fabricated/unsupported citation,
misquote, internal contradiction), `warning` (needs a closer look), `info`.

## Verdict policy (`aggregator.py`)

Threshold for one side: **two independent domains**, or **one authoritative
source** (`primary`, `official`, `academic`, `reference`). User-provided sources
count but are never authoritative, and all of a user's uploaded documents count
as **one** source. The subject's own site (`primary`) is not authoritative about
its own efficacy, safety or superiority ("our gummies cure insomnia", "the
fastest platform"); such claims need independent sources.

A model's "supports" only becomes evidence after deterministic checks (see
`evidence._passes_guards`): the passage names **every** subject of the claim
(whole words), and the quote states **every** number and year of the claim and
shares a content word with it (or names all of its entities); a negated quote
never supports an un-negated claim (or the reverse); quoted words must be
verbatim; a hedged finding never supports "proves"/"cures". A "contradicts"
must be about one of the claim's subjects. Superiority claims ("the largest",
"the obvious choice") are self-serving, and "…of any…" claims are universal.

| Situation | Verdict |
| --- | --- |
| Not objectively checkable (opinion, prediction, unobservable) | NOT CHECKABLE |
| A deterministic calculation fails | CONTRADICTED (+ corrected value) |
| Contradictions meet the threshold, support does not | CONTRADICTED (correction only from a counted source) |
| Both sides have evidence and either meets the threshold | DISPUTED |
| Support meets the threshold, nothing contradicts | SUPPORTED |
| …but the claim is universal/negative ("no competitors", "zero rivals", "the sole provider", "unrivaled", "nobody else") | UNVERIFIED — absence of a counterexample proves nothing |
| …but part of the claim's investigation failed (an engine error on that claim) | UNVERIFIED — the failure may have hidden contradicting evidence |
| …but the claim is time-sensitive and evidence is undated/older than `TRUSTLAYER_FRESHNESS_DAYS` | stale items move to related sources; decided on current evidence only |
| A claim pinned to a past date ("As of 2019, the CEO was …") | a dated snapshot: evidence from that time counts; the report notes the situation may have changed since. With "currently/still/today" it is a claim about now. |
| A pure-math claim whose calculation passes | SUPPORTED (method `deterministic_calculation`) |
| Anything else | UNVERIFIED, with `missing_evidence` explaining what is needed |

`report.py` re-checks the invariants (SUPPORTED needs quoted evidence or a
passing pure calculation; quotes are exact slices; summary counts match). If a
bug produces an inconsistent report, `pipeline.py` withholds all verdicts.

## Model use (and its limits)

| Task | Model output | Deterministic guard |
| --- | --- | --- |
| Stance judgment (Engine B/C) | per passage: supports / contradicts / irrelevant / insufficient + quote | quote must be found verbatim in the passage; a "supports" must name every subject of the claim (whole words), its quote must state every number and year of the claim and be on topic; else downgraded |
| Query generation (Deep) | up to 3 search queries | length/URL checks; deterministic query always runs first |
| Market profile & competitor mentions (Engine D) | product summary, queries, company mentions | a competitor counts only if named in an exact quote from a fetched source |
| Completeness / logic review (Deep, Engines E/G) | findings with quotes | quotes must exist in the question/response |
| Legacy sycophancy scorer (Engine F) | unchanged two-pass Gemini scoring | separate section; never changes factual verdicts |

Judge selection (`llm.select_llm`): providers in `TRUSTLAYER_LLM_PROVIDERS`
order (default `anthropic,gemini`), skipping any whose model family matches the
request's `source_model` when another is available — "never let a model judge
itself". If only a same-family judge exists, the report says so.

## Security model

- **SSRF**: only `http`/`https`, ports 80/443 by default, no credentials in URLs.
  Hostnames are resolved and *every* address must be public (no loopback,
  private, link-local, CGNAT, multicast, reserved, unspecified, IPv4-mapped
  private). The connection is pinned to the validated IP inside a custom httpcore
  network backend, so DNS rebinding between check and connect is impossible.
  Redirects are followed manually (max 4) and re-validated hop by hop. Proxies
  from the environment are ignored. Responses are streamed with a byte cap and a
  content-type allowlist. `robots.txt` is honored (RFC 9309; 5xx → disallow).
- **Prompt injection**: untrusted text is data inside tagged blocks and fenced
  (tag-like text cannot forge a block boundary, in any case or spacing); passages
  with instruction-like text are excluded and flagged; outputs are schema-checked
  and quote-checked; evidence objects are built by code from fetch records, so a
  model cannot introduce a URL; and even a fully compromised judge cannot produce
  SUPPORTED without passing the deterministic guards.
- **Resource limits**: input caps (24k-char response, 8k question, 5 URLs, 3
  documents ≤100k chars), claim cap, per-mode budgets, per-process concurrency cap
  (a streamed verification keeps its slot until its worker finishes, so dropping
  and reopening streams cannot exceed the cap), existing per-key daily quota.
  Every pattern that runs on untrusted text is linear (bounded repetition, no
  overlapping quantifiers), and HTML passes a linear pre-pass before `html.parser`
  (which is quadratic on malformed markup); each has a timing regression test.
- **Secrets** stay server-side; the workbench only ever holds the caller's own `tl_` key.

## Budgets and cost

`budget.limits_for(mode)` returns per-mode limits (env `TRUSTLAYER_<MODE>_<FIELD>`):

| Limit | Quick | Deep |
| --- | --- | --- |
| Time | 25 s | 90 s |
| Search calls | 8 | 30 |
| Page fetches | 10 | 40 |
| Model calls / tokens | 12 / 60k | 50 / 300k |
| Estimated cost cap | $0.10 | $1.00 |
| Claims researched | 6 | 25 |

When a limit is hit, remaining work is skipped and listed in `incomplete_checks`;
affected claims stay UNVERIFIED. Cost is an estimate from `budget.SEARCH_PRICES`
and `budget.MODEL_PRICES` (overridable with `TRUSTLAYER_PRICE_*`).

## Privacy and consent

`VerificationRequest` carries `allow_web_search`, `allow_ai_processing` (default
true for API callers; the workbench shows both switches) and
`share_documents_with_ai` (default **false**). The report's `privacy` block
lists the providers that were actually used. Reports are not stored unless
retention is configured (Level 5).

## Evaluation (Levels 2–3)

Verification cases live in `evaluation/verification/` as a frozen web: each
case brings its own small corpus, so runs are deterministic and offline.

```json
{
  "id": "vdev_001", "split": "dev", "tags": ["historical", "correct_factual"],
  "notes": "Why this case exists.",
  "request": {"response_text": "...", "original_question": null, "mode": "quick"},
  "corpus": [
    {"url": "https://en.wikipedia.org/wiki/Example", "title": "Example", "provider": "wikipedia",
     "published_at": "2026-05-01", "text": "Plain text of the page ...",
     "judgments": [{"claim_text": "exact claim substring", "stance": "supports",
                    "quote": "exact substring of text"}]},
    {"url": "https://broken.example.com/x", "fetch_error": "http_error", "status": 404}
  ],
  "gold": {
    "claims": [{"claim_text": "exact substring of response_text", "verdict": "SUPPORTED"}],
    "citations": [{"url": "https://...", "status": "invalid_or_fabricated"}]
  }
}
```

The harness serves `corpus` through a lexical fixture search provider and a
fixture fetcher, and answers stance prompts with an **oracle judge** built from
`judgments` (everything not annotated is "irrelevant"). This isolates retrieval,
validation and policy from model quality. A **noisy judge** (says "supports" to
every passage) measures how many false approvals the deterministic guards stop,
and two baselines (no evidence; naive word overlap) bound the result. Live
providers are not part of the harness; a manual live smoke run is recorded in
[DEPLOYMENT.md](DEPLOYMENT.md). See [evaluation/verification/README.md](../evaluation/verification/README.md).
