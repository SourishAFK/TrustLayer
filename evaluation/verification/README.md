# Verification benchmark (Levels 2–3)

An offline, deterministic benchmark for the full verification pipeline:
extraction → specialist engines → evidence research → verdict policy. Each case
brings its own **frozen web**: a small corpus of pages served by a fixture search
provider and a fixture fetcher, so a run needs no network, no keys and no money,
and gives the same answer every time.

```powershell
./.venv/Scripts/python.exe -m evaluation.verification.run --split all --judge both --output evaluation/results/verification.json
./.venv/Scripts/python.exe -m pytest -q evaluation/test_verification_harness.py
```

`--split dev|heldout|all`, `--judge oracle|noisy|both`. Without `--output` the
JSON goes to stdout and the summary table to stderr. Exit code 1 means a case
crashed (harness error), not a low score.

## The four systems

| System | What it is | What it measures |
| --- | --- | --- |
| `pipeline+oracle` | The real pipeline with every default engine; model tasks answered from the gold annotations | Retrieval, validation guards, specialist engines and the verdict policy — with model quality held perfect |
| `pipeline+noisy` | Same, but the "judge" says **supports** to every passage, quoting its first 60 characters | How many false supports the deterministic guards stop when the model is wrong |
| `baseline:extraction_only` | Level 1 behavior: every checkable claim UNVERIFIED | The floor: honest but uninformative |
| `baseline:naive_overlap` | SUPPORTED when any page shares ≥60% of the claim's words | Why "the page mentions it" is not evidence |

The oracle is not a model. It answers `stance_judgments` from each corpus page's
`judgments`, returns empty results for query generation and reviews, derives a
product profile from the response's first sentence, and names a competitor from
a contradicting judgment (`"competitor"` field, else the quote's first name). It
cannot measure how well a live model reads; it isolates everything else.

## Case format

See `docs/ARCHITECTURE.md` → *Evaluation*. In short: `request` (the
`VerificationRequest` fields), `corpus` (pages with `url`, `title`, `provider`,
`published_at`, `text`, `judgments`; or `fetch_error`/`status` for broken links;
`searchable: false` for pages only reachable as citations), and `gold`
(`claims` with exact `claim_text` substrings and verdicts, optional `citations`
statuses and `signal_kinds`). `run.validate` rejects malformed fixtures before
scoring: gold text must be in the response, judgment quotes in their pages.

## Metrics

Empty denominators are reported as `null` ("unavailable"), never as 100%.

- **verdict_accuracy** — matched gold claims whose predicted verdict equals the gold verdict. A gold claim matches the predicted claim covering ≥50% of its span; unmatched claims are listed as `extraction_misses`.
- **false_supported_count / rate** — predicted SUPPORTED where gold is anything else; rate over predicted SUPPORTED. Listed one by one in `false_approvals`. **The headline safety number.**
- **wrong_claim_detection_rate** — gold CONTRADICTED claims predicted CONTRADICTED or DISPUTED.
- **abstention_rate_on_unverified_gold** — gold UNVERIFIED claims kept UNVERIFIED (not promoted to a confident verdict).
- **evidence_integrity_rate** — predicted SUPPORTED claims whose every evidence quote occurs verbatim in a corpus page at that URL (or that rest on a passing pure calculation).
- **citation_status_accuracy**, **signal_recall** — against `gold.citations` and `gold.signal_kinds`.
- Per-tag breakdowns, latency and estimated cost (always $0 here).

## Results (October 17, 2026)

Result files: `evaluation/results/verification_dev.json`,
`verification_heldout_frozen.json` (the official blind run) and
`verification_heldout_posthoc.json` (after the fixes listed below).

**Dev split** (28 cases, 32 gold claims; written while building, not blind):

| System | Accuracy | False SUPPORTED | Wrong-claim detection |
| --- | --- | --- | --- |
| pipeline + oracle | 100% | 0 | 100% |
| pipeline + noisy | 87.5% | 0 | 66.7% |
| baseline: extraction only | 65.6% | 0 | 0% |
| baseline: naive overlap | 56.2% | 9 (75.0% of its SUPPORTED) | 0% |

**Heldout split** (24 cases, 103 gold claims). Two blind authors and two blind
auditors wrote and checked it from the policy documentation only. It was run
**once** with the engines frozen (engine source hash `ba208e8369e28e44`):

| System | Accuracy | False SUPPORTED | Wrong-claim detection | Abstention | Evidence integrity | Citations | Signals |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pipeline + oracle | 66.0% | **0** | 83.3% | 100% | 100% | 100% | 51.5% |
| pipeline + noisy | 42.7% | **4** (26.7%) | 25.0% | 100% | 100% | 64.3% | 48.5% |
| baseline: extraction only | 28.2% | 0 | 0% | 100% | n/a | 0% | 0% |
| baseline: naive overlap | 41.7% | 31 (55.4%) | 0% | 47.6% | 0% | 0% | 0% |

Where the oracle run went wrong (35 of 103 claims):

- 18 opinions or predictions were labeled UNVERIFIED instead of NOT CHECKABLE.
  This is the Level 1 extractor's checkability heuristic: the error is safe, but
  it costs accuracy.
- 12 true claims stayed UNVERIFIED and 4 false claims stayed UNVERIFIED; 1
  dispute was called a contradiction. The re-run below shows what caused them:
  9 came from a primary-source rule added earlier the same day (a single brand
  name opening a sentence, such as "Cartwise raised…", was no longer recognized
  as the company's own site, partly because the brand also appears in
  lowercase inside its own URL); 1 from "Between" being read as a name; 1 from
  a comparative claim being treated as self-serving; and 1 from a "from $12
  million in 2024 to $18 million in 2025" phrasing the math engine missed. The
  other 5 remain (see below).

The noisy judge's 4 false approvals: two negated quotes ("…is **not**
cleared…" accepted for "is FDA-cleared"), one scope mismatch ("highest above sea
level" accepted for "tallest base to summit"), and one opinion supported by the
company's own site.

**Post-heldout changes.** These were made *after* seeing the failures above, so
the heldout split is **no longer blind** for them; each is a general rule with
its own regression test:

1. A negated quote never supports an un-negated claim, or the reverse.
2. Superiority wording ("obvious choice", "largest", "lowest"…) is
   self-serving: the seller's own site can't confirm it.
3. "…of any…" / "…than any other…" claims are universal.
4. A lone brand name counts as a name when it is never written in lowercase in
   the response or on the page (URLs, emails and domains aside) and is used
   mid-sentence or at least twice. Domains formed from a name plus "funds",
   "labs" and similar words count as the company's own site.
5. The extractor's "comparative" label no longer makes a claim self-serving.
6. Sentence-opening function words ("Between", "During"…) are not names.
7. The from–to pattern accepts "in <year>" after each figure.

Heldout re-run after these changes (engine hash `fde86d8b3e372428`; **not a
blind result**):

| System | Accuracy | False SUPPORTED | Wrong-claim detection | Abstention |
| --- | --- | --- | --- | --- |
| pipeline + oracle | 77.7% | **0** | 91.7% | 100% |
| pipeline + noisy | 47.6% | **1** (6.7%) | 29.2% | 100% |

The remaining noisy-judge false approval is the scope mismatch, which
deterministic guards cannot catch; it depends on the judge reading carefully.
The 23 remaining oracle errors are 18 opinions labeled UNVERIFIED (extractor),
3 true and 2 false claims left UNVERIFIED (retrieval depth in Quick mode, a
claim the extractor tagged universal because of "every second", and a
multi-word fund name not matched to its domain). Dev results did not change. One intermediate step is worth
reporting: change 4 alone introduced two new noisy-judge false approvals
("the largest vendor", "the lowest fees of any index fund"), and changes 2 and
3 closed them. The noisy judge exists precisely to catch this kind of trade-off.

**Known weaknesses shown by heldout:** signal recall is 51.5%. Missed signals
are mostly the phrase-list language signals (absolute language, overconfident
predictions and recommendations, one-sided framing) and 2 internal
contradictions. NOT CHECKABLE detection is weak, and scope qualifiers ("measured
from base to summit") are left to the judge.

## Data and honesty notes

- **Dev split** (`cases_dev.json`, 28 cases, 32 gold claims) was written by the
  implementing agent while building the engines — it is *not* blind and several
  guards were tuned on it. Treat dev numbers as regression checks.
- **Heldout split** (`cases_heldout.json`, 24 cases, 103 gold claims) was written by
  two separate agents and checked by two blind auditors, all instructed not to read
  the implementation, dev cases or harness — only the policy and format
  documentation (their tool logs were checked for this). It was run once *after*
  the engines were frozen; everything changed after looking at its failures is
  listed above, and it is no longer blind for those changes. It is still
  agent-authored, public and small — not a sealed external test.
- All labels are **drafts awaiting independent human review**. Corpus pages are
  synthetic fixture text, including pages under real domain patterns
  (`en.wikipedia.org`, `*.gov`, `*.edu`); they are not quotes from those sites.
- Not measured offline: a live LLM-judge baseline (needs keys and a cost cap) and
  the original TrustLayer detector (it scores a whole response's sycophancy and
  emits no per-claim factual verdicts, so it is not comparable here).
