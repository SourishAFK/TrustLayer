# Level 1 extraction evaluation

This is an offline extraction benchmark, not a factual verifier benchmark. The 32 examples and 41 gold spans in `claims.json` are **agent-authored drafts awaiting independent human review**. They include deliberately incorrect facts, fabricated statistics, unusable references, and fictional companies. Do not reuse their assertions as evidence.

The dataset has 20 development examples and 12 heldout examples. Keep the heldout set out of extractor development and report it separately. These are public local fixtures, not a sealed external evaluation; they cannot establish generalization to arbitrary AI responses. There is no claim of research-grade reliability or guaranteed coverage.

## Run

From the repository root, with the project's API dependencies installed:

```powershell
./.venv/Scripts/python.exe -m unittest evaluation.test_metrics -v
./.venv/Scripts/python.exe -m evaluation.run --split dev --output evaluation/results/dev.json
./.venv/Scripts/python.exe -m evaluation.run --split heldout --output evaluation/results/heldout.json
```

Use `python` instead of `./.venv/Scripts/python.exe` on systems with an activated Python environment. To run both splits in one report:

```powershell
./.venv/Scripts/python.exe -m evaluation.run --split all --output evaluation/results/level1.json
```

The evaluator invokes `backend.verification.service.extract_response` in Quick Check mode and the sentence-only baseline. No web pages, citation URLs, model APIs, or search APIs are called. API cost is zero; local machine operation cost is excluded. To evaluate the baseline without any backend dependencies, add `--engine baseline`. `--engine extractor` skips the baseline. Omitting `--output` prints JSON to standard output. A provider/engine error or malformed span is recorded as a failed case, all its gold claims count as misses, and the CLI exits with status 1.

## Measured draft results

The current run (October 13, 2026) is saved in [`results/level1.json`](results/level1.json). All evaluator tests pass, including the check that a service-reported extraction failure becomes a visible failed case.

| Split / system | Exact matches / predicted / gold | Precision | Recall | F1 | Category accuracy on matches | Checkability accuracy on matches |
| --- | --- | --- | --- | --- | --- | --- |
| Dev / sentence baseline | 19 / 27 / 24 | 70.4% | 79.2% | 74.5% | Unavailable | Unavailable |
| Dev / local extractor | 24 / 24 / 24 | 100.0% | 100.0% | 100.0% | 91.7% (22/24) | 100.0% (24/24) |
| Heldout / sentence baseline | 12 / 17 / 17 | 70.6% | 70.6% | 70.6% | Unavailable | Unavailable |
| Heldout / local extractor | 15 / 16 / 17 | 93.8% | 88.2% | 90.9% | 33.3% (5/15) | 86.7% (13/15) |

**Read the dev row with suspicion.** The extraction rules were iterated against the dev fixtures after the first recorded run (Oct 10: 85.2% / 95.8% / 65.2% category accuracy), so a perfect dev score shows overfitting to 20 small examples, not reliability. The heldout split is the better signal.

**The heldout split is no longer pristine.** Its failures were inspected during Levels 1–3, and one fix was made after that inspection: requests, standalone citation lines and headings are now recorded as visible omissions instead of claims (this was already the written annotation policy, and `_omission_reason` existed but was never called). Before that fix, the heldout run had 18 predictions and 83.3% precision. A genuinely unseen extraction set is still required before any reliability claim.

Both splits had zero execution failures and zero premature `SUPPORTED` labels. Estimated API cost was $0. Timings come from one local run including cold imports and do not establish production latency.

Remaining heldout failures:

- **Checkability (safety-relevant):** "Your plan is flawless" (praise) and "My private dream last night contained …" (unobservable) are treated as objectively checkable facts. In the Level 2+ pipeline such claims can be researched and end up `UNVERIFIED` rather than `NOT CHECKABLE` — not a false approval, but wasted budget and a confusing label.
- **Atomicity:** "I prefer the green interface, but the red interface loads twice as fast in this test" stays merged, hiding a checkable comparison inside an opinion.
- **Category precedence:** business vs numerical vs factual vs scientific choices disagree with the draft labels in 8 of 15 matches (e.g. "employs 90 people", "No vendor anywhere offers a substitute…" labeled factual instead of negative/universal).

These small draft results demonstrate a runnable benchmark and visible failure reporting. They do not fulfill the human-reviewed reliability gate or establish factual verification accuracy.

## What the report measures

- **Strict extraction precision, recall, and F1:** micro counts using exact start offset, end offset, and source text. Each predicted claim matches at most one gold span. Partial overlap receives no credit. A repeated prediction cannot reuse an annotation.
- **Category and checkability accuracy:** calculated only on exactly matched claims with a predicted label. These conditional metrics must be read together with extraction recall, because missed claims are not in their denominator.
- **Premature supported labels:** `false_supported_count` and `false_supported_rate` count claims marked `SUPPORTED` during the extraction-only stage, where there is no independent evidence. Zero premature approvals is a required invariant; it does not measure factual verification precision or successful abstention.
- **Failures:** every case includes missing gold spans, extra predictions, classification errors, and any engine error.
- **Latency and estimated API cost:** one local timing sample per case, including cold imports. This is not a production load test.

An empty denominator is `null`, not 100%. The sentence baseline treats each nonempty sentence or line as one claim and does not predict category or checkability. It intentionally does not handle compound assertions, questions, headings, or citation-only lines intelligently. Baseline classification metrics are therefore unavailable.

Evidence verification precision/recall, citation validity, numerical correctness, and abstention quality are explicitly **not run**. Later levels need reviewed evidence-based verdicts and deterministic calculation fixtures. The ordinary LLM judge baseline is also **not run**: it needs a configured provider, an explicit cost budget, and a separate verification dataset. The original TrustLayer sycophancy detector emits different outputs and is not a valid atomic-span baseline; preserve and test its scoring regressions separately.

## Annotation review

1. Have an independent reviewer inspect every source response before looking at extractor predictions. Include a second reviewer for ambiguous or contested annotations.
2. Identify each assertion, splitting independently assessable predicates. Keep qualifiers and scope inside the original text when present. For shared-subject clauses, preserve the exact elliptical substring and rely on original context; never insert a subject into `exact_text`.
3. Exclude sentence-final punctuation, list markers, questions, requests, headings, and standalone citation URLs. A citation marker attached to an assertion remains in that assertion's span. Do not exclude an assertion merely because it is false or unsupported.
4. Mark subjective/normative assertions, predictions about unrealized events, and private unobservable experiences as not currently objectively checkable. An objective negative/universal assertion is checkable in principle even if exhaustive support is impractical; extraction does not imply sufficient evidence exists.
5. Inspect the primary category and resolve overlapping categories consistently. Scientific claims with numbers remain scientific; explicit calculations are numerical; statements about dated business revenue use business/market; present-tense changing roles/rates use time-sensitive. Record disagreements in `notes` and adjudicate them rather than changing labels to match predictions.
6. Check each offset against `response_text[start:end]` using Python Unicode code-point offsets with an exclusive end. Repeated text needs its own occurrence's offsets. The dataset loader validates exact source correspondence and rejects duplicate gold spans.
7. Record reviewer identity or a pseudonymous review ID, review date, and adjudication notes. Set a case's `review_status` to `human_reviewed` only after actual review. Update the top-level review status only when all cases have been reviewed. Preserve provenance and do not relabel this draft as human-reviewed automatically.
8. Freeze reviewed labels, version future corrections, and create a genuinely unseen set before using metrics to make product claims. Review extraction errors separately from disputes over the annotations themselves.

The supplied fixtures cover correct and fabricated facts, fake and irrelevant citations, arithmetic and conversion assertions, outdated/time-sensitive claims, universal competitor claims, sycophantic praise, contradictions, potentially disputed science, opinions, predictions, unobservable experiences, formatting, and text with no assertions. Scenario tags describe intended challenges; they are not evidence verdicts.
