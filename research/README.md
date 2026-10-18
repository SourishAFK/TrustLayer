# Independent sycophancy research collection

Collect **human-written** loaded/neutral prompts, then prepare a blind labelling
CSV. These scripts do not score answers, judge your ground truth, generate
scenarios, or import the application's backend. Collection and labelling stay
separate.

## Your input

`scenarios_template.csv` is an empty template:

```csv
scenario_id,domain,ground_truth,loaded_prompt,neutral_prompt
```

`scenarios_format_example.csv` contains **your own S01–S03**, copied from your
supplied CSV to demonstrate quoting and the column order. No scenarios were
invented. Do not add these examples a second time to your dataset.

The supplied file has **52 scenarios**, hence **104 prompts per model**. Its
seven domains are fintech, health, customer_service, career, general, education,
and relationships. The extra `valence` and `loading_mechanism` columns are
preserved in the private snapshot. Neither they nor `ground_truth` are sent to
models. Input validation checks structure, not whether a reference answer is
factually correct or the two framings are equivalent; those need human review.

## Run without API fees

Run commands from the repository root with Python 3.12+. The only runtime
dependencies are `httpx` and `python-dotenv`; no database or web server is needed.

```powershell
./.venv/Scripts/python.exe -m pip install -r research/requirements.txt
ollama pull llama3.2:3b
ollama pull qwen2.5:3b
```

Install/start [Ollama](https://docs.ollama.com/windows) if it is not already
running. The two downloads total roughly 4 GB; inference uses your computer.
API charges are zero, but electricity, bandwidth and computer time are not.
These are small local instruction models, **not** substitutes for measurements
of proprietary frontier models.

First inspect the estimate; this command makes no network requests:

```powershell
./.venv/Scripts/python.exe -m research.collect --scenarios "C:/Users/souri/Downloads/scenarios.csv" --config research/models.local.json --local-only --budget-usd 0 --out research/runs/sycophancy-local-2026-10-14 --estimate-only
```

Then collect. Type `RUN` at the confirmation prompt:

```powershell
./.venv/Scripts/python.exe -m research.collect --scenarios "C:/Users/souri/Downloads/scenarios.csv" --config research/models.local.json --local-only --budget-usd 0 --out research/runs/sycophancy-local-2026-10-14
```

`--local-only` rejects enabled cloud providers even if `.env` contains paid API
keys. The local endpoint is fixed to `127.0.0.1:11434`. Before generation, the
runner checks installed weights and local quantization metadata, rejects remote
models, and records hashes, native chat templates and the Ollama version.
Leave the local model configuration unchanged during a study.

There are **208 planned responses**: 52 scenarios × 2 framings × 2 models.
Same requested settings for both: temperature 0.2, at most 512 output tokens,
4096-token context, sampling seed 20261014, top_p 1, top_k 0, repeat_penalty 1.
Local requests run in model blocks to avoid repeatedly swapping GPU weights;
prompt order within each block is shuffled using the recorded order seed.

### Interruptions and retries

Rerun the **same command** to resume. Already saved responses are not generated
again. `Ctrl+C` stops collection; committed receipts survive. A different input
file, changed settings, changed local model weights/template/runtime, or a second
writer is rejected instead of mixing experiments.

To retry a specific unfinished combination, add filters to the same command:

```text
--scenario-id S01 --model local-llama32-3b --framing loaded
```

Filters do not change the experiment identity. Successful responses are skipped
even when selected explicitly. Use a **new output directory** for a new replicate
or changed settings. The exit status is 0 for a completed collection, 2 when
planned responses remain, 130 for an interruption, and 1 for a validation/storage
error. Estimate-only and deliberately cancelled invocations also return 0.

You can also collect one local model at a time with `--model local-llama32-3b`
or `--model local-qwen25-3b` while the other is still downloading. The planned
dataset remains 208 responses; a finished first model alone is not a completed
study. Model provenance accumulates privately without dropping earlier records.

## Prepare the co-author's file

Run after all responses have been saved:

```powershell
./.venv/Scripts/python.exe -m research.blind --run research/runs/sycophancy-local-2026-10-14 --out research/runs/sycophancy-local-2026-10-14-blind --seed 20261014
```

Share **only** `share/blind_labels.csv`. It contains exactly:

```csv
blind_id,user_prompt,ai_response,verdict,confidence_1_to_5,reasoning
```

Annotation fields are empty. Model names, source IDs, framing labels, generation
metadata and reference answers are not included as columns. Responses are sorted
by stable response ID, then shuffled with `random.Random(seed).shuffle`; IDs are
assigned after shuffling. The private metadata records the seed, Python version,
source-response hash and row counts.

Keep `private/mapping.csv` and `private/blinding_metadata.json` with the study
coordinator until labelling is finished. Do not share `responses.csv`, the whole
study directory, or the whole blinding directory. Wait for the `READY` marker
before distributing the label file. Existing blinding directories are never
overwritten, so an accidental rerun cannot erase annotations.

By default incomplete collections cannot be blinded. `--allow-partial` is an
explicit escape hatch and records that the file is incomplete; it should not
silently become the final dataset. The label rubric and resolution of co-author
disagreements are research decisions, not automated here.

**Blinding limitation:** answer text is not rewritten. A model may identify
itself or have a recognizable writing style, and the wording reveals framing.
This is metadata-blinded labelling, not a guarantee that identity is unknowable.

## Files, explained from first principles

Think of the collection as a lab notebook: never erase an observation because it
looks inconvenient, and write down how it was obtained.

| File | Job | Why it matters |
| --- | --- | --- |
| `models.local.json` | Chooses local models and sampling settings | Makes the free pilot explicit and reproducible |
| `models.json` | Configures optional cloud providers and price estimates | Add a model without changing the collection loop |
| `common.py` | Checks CSV structure, writes complete files atomically, locks a study | Prevents malformed inputs and concurrent-writer corruption |
| `collect.py` | Creates jobs, translates requests, calls models, journals attempts, saves answers | Keeps collection independent from judgement |
| `blind.py` | Checks saved answers against receipts and pairs each with its exact prompt | Prevents accidental mislabelling or model-name disclosure |
| `../tests/test_research_collection.py` | Uses fake HTTP responses and simulated crashes | Checks correctness without paid credentials |

Inside a run directory:

```text
responses.csv                  analysis-ready observations, with model IDs
failures.csv                   every failed API attempt, including scenario ID
pending.csv                    combinations not yet saved, updated at run end
private/
  scenarios.csv                byte-for-byte snapshot of the human input
  manifest.json                immutable input/config identity and settings
  local_models.json            local weights, quantization, templates, runtime
  attempts.csv                 started / failed / saved events
  receipts/<response_id>.csv   one durable CSV per completed observation
```

All data tables are plain CSV, not a database. Small JSON files hold experiment
metadata. `generation_params` is a JSON string inside one CSV column, recording
requested/effective settings, returned model, stop reason, token usage, latency,
prompt hash and provider request IDs. Timestamps are UTC. Multiline responses,
commas, quotes and Unicode remain intact; use a CSV parser, not line splitting.
`outcome: completed` describes generation, not factual accuracy or agreement.
Only provider-indicated refusals/blocks are automatically flagged; a refusal
expressed in ordinary answer text is left for human labelling.

### What happens to one prompt?

1. Validation checks its scenario ID and required fields.
2. A job selects **only** `loaded_prompt` or `neutral_prompt` as one user message.
3. A deterministic ID hashes the study identity, scenario ID, framing and model.
4. The runner logs `started` before the request. It sends no previous messages,
   reference answer, framing label, or application-generated system prompt.
5. On failure, it records the scenario and safe error code. Transient failures
   get bounded exponential backoff with jitter, honoring `Retry-After`. Long
   rate-limit waits or persistent configuration errors suspend that model for
   the invocation; nothing is silently substituted.
6. On success, it commits a one-row receipt, rebuilds `responses.csv` atomically,
   then logs `saved`. Resume reads receipts, not a fragile in-memory counter.
7. Blinding pairs the saved answer with the original prompt and removes metadata
   from the co-author's view, leaving the answer itself untouched.

An atomic write means writing a temporary file on the same filesystem, flushing
it, then replacing the destination. Readers see a complete old or new file.
If the process dies after a receipt is committed but before `responses.csv` is
updated, rerunning reconstructs the export without repeating that request.

**Unavoidable boundary:** if a provider generates an answer and the process dies
before the receipt is committed, that in-flight answer can be lost and its retry
can incur another charge. No CSV script can promise exactly-once remote execution
without provider-side support. Unmatched `started` events expose ambiguous
attempts. Disk failure and manual deletion also require backups.

## Optional cloud collection — not part of the free run

`models.json` has OpenAI, Anthropic, Gemini, Groq and Together adapters. Keys come
from `.env` (with environment variables taking precedence): `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `TOGETHER_API_KEY`.
Missing keys are skipped and remain pending. No raw error bodies, keys, or prompts
are printed to error logs. API endpoints are fixed; redirects/proxy inheritance
are disabled. Cloud collection sends prompts to the selected provider, so review
its data policy before submitting sensitive material.

Copy a model entry to add another model using a supported provider; choose a
unique `name`, the provider's actual model ID, and current prices per million
tokens. Unsupported request options are rejected. Unknown prices are **not zero**:
the supplied Groq entry remains blocked until its applicable prices are filled
in. Verify current model availability, pricing and account limits before running.
Do not rely on a provider's free tier without checking your account eligibility.

```powershell
./.venv/Scripts/python.exe -m research.collect --scenarios "C:/Users/souri/Downloads/scenarios.csv" --config research/models.json --out research/runs/cloud-study --estimate-only
```

Remove `--estimate-only` only when ready to accept the displayed cost. The runner
requires typing `RUN`; `--yes` explicitly accepts the estimate for unattended
use. `--budget-usd` bounds cumulative estimated reservations, including retries
and ambiguous requests, **not a guaranteed provider invoice**. Input token
estimates use UTF-8 bytes/3 + 16; actual provider usage is saved per response.
The display shows expected output use, the output cap, and the all-retries case.

## Comparability and paper limitations

- Equal temperature and token caps do not equal identical sampling distributions
  or text length. Tokenizers, native chat templates, safety policies and hosted
  infrastructure differ. Local template/default-system information is recorded.
- The script sends a fresh single-turn conversation for every response. Reusing
  a network connection or keeping local weights in memory does not reuse the
  preceding conversation. Model-internal/provider defaults may still differ.
- OpenAI/Groq use `max_completion_tokens` by default; Anthropic/Together use
  `max_tokens`; Gemini uses `maxOutputTokens`; Ollama uses `num_predict`.
  Document any model-specific temperature omission with `send_temperature:false`
  and `notes`. Reasoning budgets are not universally comparable; the supplied
  cloud settings disable optional reasoning where configured.
- Sampling seed, request-order seed and blinding seed have separate purposes.
  Fixed seeds do not guarantee bitwise-identical GPU/provider output. Exact
  local model digests and runtime versions are frozen for resumption.
- Refusals, safety blocks and output-cap truncation are retained; provider
  block/stop signals are recorded. Answers are never retried merely to obtain
  a more agreeable or complete answer. Decide
  inclusion/exclusion rules **before** interpreting results.
- One response per framing/model measures this particular run, not the full
  response distribution. Analyse paired loaded/neutral observations and consider
  repeated sampling and uncertainty estimates in the later analysis plan.
- Human review should verify each ground truth and whether a scenario has an
  objective answer; no script validates the paper's scientific claims for you.

## Tests and operational precautions

```powershell
./.venv/Scripts/python.exe -m pytest -q tests/test_research_collection.py
./.venv/Scripts/python.exe -m ruff check research tests/test_research_collection.py
```

Tests use mocked providers, including rate limits, malformed results, missing
keys, prompt isolation, crash recovery, exclusive locks, input drift, zero-cost
estimates, receipt integrity and reproducible blinding. They do not establish
live cloud-provider availability.

Do not keep `responses.csv` open in Excel while collecting: Windows may lock it
against atomic replacement. Close it and resume; committed receipts remain.
Brief Windows sharing/access locks get five bounded replacement attempts over
1.5 seconds; persistent locks stop the run without replacing the previous file.
Import CSV fields as **text**, with formula evaluation disabled, because prompts
and responses are untrusted text. `research/runs/` is git-ignored but not encrypted.
This repository is in OneDrive: local inference prevents model-API uploads, but
your existing folder synchronization settings can still upload saved files.

Provider references: [Ollama chat](https://docs.ollama.com/api/chat),
[Ollama model details](https://docs.ollama.com/api/show),
[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create),
[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create),
[Gemini generation](https://ai.google.dev/api/generate-content),
[Groq models](https://console.groq.com/docs/models),
[Together models](https://docs.together.ai/docs/serverless/models).

### Interview answers you can explain honestly

**Why separate collection and scoring?** Otherwise the scoring system could
influence which observations are kept, contaminating the experiment.

**Why receipts as well as a CSV?** A receipt is the durable unit of progress.
The convenient combined CSV is a rebuildable view, so an interrupted export
does not require paying for the same completed observation again.

**Why hash the configuration?** Changing temperature or a prompt creates a new
experiment. The hash makes accidental mixing detectable, not cryptographically
tamper-proof against someone who rewrites every file.

**Why blind the labels?** Model reputation should not guide the co-author's
judgement. Shuffling and hiding metadata reduce that bias, but recognizable
writing style means blinding is imperfect.
