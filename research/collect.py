"""Collect human-authored prompts as independent, single-turn API requests.

Run from the repository root: python -m research.collect --help
No scoring, ground-truth injection, model fallback or scenario generation.
"""

import argparse
import csv
import json
import math
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import dotenv_values

from research.common import (
    RESPONSE_FIELDS,
    atomic_write,
    digest,
    json_text,
    read_csv,
    read_scenarios,
    study_lock,
    utc_now,
    write_csv,
)

PROVIDERS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "together": "https://api.together.ai/v1/chat/completions",
    "ollama": "http://127.0.0.1:11434/api/chat",
}
OPTION_KEYS = {"openai": {"reasoning_effort"}, "anthropic": {"thinking"},
               "gemini": {"thinkingConfig"}, "groq": {"reasoning_effort", "reasoning_format"},
               "together": {"reasoning", "reasoning_effort"},
               "ollama": {"num_ctx", "seed", "top_p", "top_k", "repeat_penalty"}}
ATTEMPT_FIELDS = ["attempt_id", "response_id", "scenario_id", "framing", "model",
                  "attempt", "timestamp", "event", "http_status", "error_type",
                  "provider_request_id", "reserved_usd"]


def number(value, low, high, label, *, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high
            or (integer and not isinstance(value, int))):
        raise ValueError(f"Invalid configuration: {label}")


def read_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    allowed = {"schema_version", "generation", "expected_output_tokens", "order_seed",
               "max_attempts", "timeout_seconds", "backoff_seconds", "max_backoff_seconds",
               "domains", "models"}
    if not isinstance(config, dict) or set(config) != allowed or config["schema_version"] != 1:
        raise ValueError("Invalid config fields/schema_version; see research/models.json.")
    gen = config["generation"]
    if not isinstance(gen, dict) or set(gen) != {"temperature", "max_tokens"}:
        raise ValueError("generation must contain temperature and max_tokens.")
    number(gen["temperature"], 0, 1, "temperature")
    number(gen["max_tokens"], 1, 32768, "max_tokens", integer=True)
    number(config["expected_output_tokens"], 1, gen["max_tokens"], "expected_output_tokens", integer=True)
    number(config["order_seed"], 0, 2**32 - 1, "order_seed", integer=True)
    number(config["max_attempts"], 1, 10, "max_attempts", integer=True)
    for name in ("timeout_seconds", "backoff_seconds", "max_backoff_seconds"):
        number(config[name], 0.1, 600, name)
    if not isinstance(config["domains"], list) or not config["domains"]:
        raise ValueError("domains must be a nonempty list.")
    if not all(isinstance(d, str) and d.strip() for d in config["domains"]):
        raise ValueError("Invalid domain name.")
    if not isinstance(config["models"], list) or not config["models"]:
        raise ValueError("At least one model is required.")
    required = {"name", "provider", "model", "key_env", "requests_per_minute",
                "input_usd_per_million", "output_usd_per_million", "pricing_checked", "pricing_url", "notes"}
    optional = {"enabled", "send_temperature", "max_tokens_parameter", "provider_options"}
    seen = set()
    for model in config["models"]:
        if not isinstance(model, dict) or not required <= set(model) or set(model) - required - optional:
            raise ValueError("Invalid model configuration fields.")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", model["name"]) or model["name"] in seen:
            raise ValueError("Model names must be unique letters/digits/hyphens/underscores.")
        seen.add(model["name"])
        if model["provider"] not in PROVIDERS or not isinstance(model["model"], str) or not model["model"]:
            raise ValueError("Unsupported provider or missing model ID.")
        if model["provider"] == "ollama" and ("cloud" in model["model"].lower() or "/" in model["model"]):
            raise ValueError("Only local Ollama library model names are allowed; no cloud models.")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", model["key_env"]):
            raise ValueError("key_env must name an environment variable, never contain a secret.")
        number(model["requests_per_minute"], 0.1, 10000, "requests_per_minute")
        for name in ("input_usd_per_million", "output_usd_per_million"):
            if model[name] is not None:
                number(model[name], 0, 100000, name)
        for name in ("enabled", "send_temperature"):
            if name in model and not isinstance(model[name], bool):
                raise ValueError(f"{name} must be a boolean.")
        if model.get("max_tokens_parameter", "max_completion_tokens") not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError("Unsupported output token parameter.")
        options = model.get("provider_options", {})
        if not isinstance(options, dict) or set(options) - OPTION_KEYS[model["provider"]]:
            raise ValueError("provider_options may only change documented reasoning settings.")
        if not model.get("send_temperature", True) and not model["notes"]:
            raise ValueError("Document the temperature mismatch in notes.")
    return config


def credential(model, environment):
    if model["provider"] == "ollama":
        return "local-no-api-key"
    value = str(environment.get(model["key_env"]) or "").strip()
    if not value or value.lower().startswith(("your_", "replace_", "<")):
        return None
    return value


def make_jobs(scenarios, config, study_id):
    jobs = []
    for scenario in scenarios:
        for framing in ("loaded", "neutral"):
            for model in config["models"]:
                if not model.get("enabled", True):
                    continue
                identity = json_text([study_id, scenario["scenario_id"], framing, model["name"]])
                jobs.append({"response_id": digest(identity.encode()), "scenario_id": scenario["scenario_id"],
                             "domain": scenario["domain"], "framing": framing, "model": model["name"],
                             "prompt": scenario[f"{framing}_prompt"]})
    random.Random(config["order_seed"]).shuffle(jobs)
    if all(m["provider"] == "ollama" for m in config["models"]):
        # Small GPUs cannot keep both models resident. Preserve random order within each block.
        jobs.sort(key=lambda job: job["model"])
    return jobs


def request_body(model, prompt, generation):
    """Exactly one user message. Metadata and reference answers never enter this body."""
    provider = model["provider"]
    options = dict(model.get("provider_options", {}))
    if provider == "ollama":
        options.update(temperature=generation["temperature"], num_predict=generation["max_tokens"])
        return {"model": model["model"], "messages": [{"role": "user", "content": prompt}],
                "options": options, "stream": False, "keep_alive": "5m"}
    if provider == "gemini":
        options["maxOutputTokens"] = generation["max_tokens"]
        if model.get("send_temperature", True):
            options["temperature"] = generation["temperature"]
        return {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": options}
    body = {"model": model["model"], "messages": [{"role": "user", "content": prompt}], **options}
    token_parameter = model.get("max_tokens_parameter", "max_completion_tokens" if provider in {"openai", "groq"} else "max_tokens")
    body[token_parameter] = generation["max_tokens"]
    if model.get("send_temperature", True):
        body["temperature"] = generation["temperature"]
    if provider == "openai":
        body["store"] = False
    return body


class APIFailure(Exception):
    def __init__(self, kind, status=None, request_id="", retry_after=None, retryable=False):
        super().__init__(kind)
        self.kind, self.status, self.request_id = kind, status, request_id
        self.retry_after, self.retryable = retry_after, retryable


def retry_after_seconds(headers):
    raw = headers.get("retry-after")
    if raw is None:
        raw_ms = headers.get("retry-after-ms")
        try:
            value = float(raw_ms) / 1000
        except (TypeError, ValueError):
            return None
    else:
        try:
            value = float(raw)
        except ValueError:
            try:
                value = (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError):
                return None
    return max(0, value) if math.isfinite(value) else None


def parse_response(provider, data):
    """Retain refusals and truncation; do not sample again for a preferable answer."""
    if not isinstance(data, dict):
        raise ValueError("Malformed API response")
    if provider == "ollama":
        if data.get("done") is not True:
            raise ValueError("Incomplete local response")
        text = data["message"]["content"]
        stop, blocked = data.get("done_reason"), False
        raw = {k: data[k] for k in ("prompt_eval_count", "eval_count", "total_duration", "load_duration",
                                   "prompt_eval_duration", "eval_duration") if k in data}
        usage = {"input_tokens": data.get("prompt_eval_count"), "output_tokens": data.get("eval_count"), "raw": raw}
        served, response_ref = data.get("model"), None
    elif provider == "gemini":
        candidates = data.get("candidates", [])
        feedback = data.get("promptFeedback", {})
        candidate = candidates[0] if candidates else {}
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(p["text"] for p in parts if "text" in p and not p.get("thought"))
        stop = candidate.get("finishReason") or feedback.get("blockReason")
        blocked = bool(feedback.get("blockReason")) or stop in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
        raw = data.get("usageMetadata", {})
        usage = {"input_tokens": raw.get("promptTokenCount"), "output_tokens": raw.get("candidatesTokenCount"),
                 "reasoning_tokens": raw.get("thoughtsTokenCount"), "raw": raw}
        served, response_ref = data.get("modelVersion"), data.get("responseId")
    elif provider == "anthropic":
        text = "".join(p["text"] for p in data["content"] if p.get("type") == "text")
        stop = data.get("stop_reason")
        blocked = stop == "refusal"
        raw = data.get("usage", {})
        usage = {"input_tokens": raw.get("input_tokens"), "output_tokens": raw.get("output_tokens"), "raw": raw}
        served, response_ref = data.get("model"), data.get("id")
    else:
        choice = data["choices"][0]
        content = choice["message"].get("content")
        refusal = choice["message"].get("refusal")
        text = content if content is not None else (refusal or "")
        stop = choice.get("finish_reason")
        blocked = bool(refusal) or stop == "content_filter"
        raw = data.get("usage", {})
        usage = {"input_tokens": raw.get("prompt_tokens"), "output_tokens": raw.get("completion_tokens"), "raw": raw}
        served, response_ref = data.get("model"), data.get("id")
    truncated = stop in {"length", "max_tokens", "MAX_TOKENS"}
    if not isinstance(text, str) or (not text.strip() and not (blocked or truncated)) or not stop:
        raise ValueError("Missing text or finish reason")
    return {"text": text, "finish_reason": stop, "outcome": "blocked" if blocked else "truncated" if truncated else "completed",
            "usage": usage, "returned_model": served, "provider_response_id": response_ref,
            "system_fingerprint": data.get("system_fingerprint")}


def call_api(client, model, key, body):
    provider = model["provider"]
    url = PROVIDERS[provider]
    headers = {"Content-Type": "application/json"}
    if provider == "gemini":
        url += quote(model["model"], safe="") + ":generateContent"
        headers["x-goog-api-key"] = key
    elif provider == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    elif provider != "ollama":
        headers["Authorization"] = "Bearer " + key
    try:
        response = client.post(url, headers=headers, json=body)
    except httpx.TransportError as exc:
        # Exception messages and provider error bodies can echo credentials/prompts.
        raise APIFailure(type(exc).__name__, retryable=True) from None
    request_id = response.headers.get("x-request-id", response.headers.get("request-id", ""))
    # Log only an opaque, bounded identifier supplied by the provider.
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{0,200}", request_id) or key in request_id:
        request_id = ""
    if not response.is_success:
        code = response.status_code
        raise APIFailure(f"http_{code}", code, request_id, retry_after_seconds(response.headers),
                         code in {408, 409, 429, 500, 502, 503, 504, 529})
    try:
        result = parse_response(provider, response.json())
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise APIFailure("malformed_response", response.status_code, request_id) from None
    return {**result, "provider_request_id": request_id}


def token_estimate(prompt):
    # shortcut: cross-provider tokenization differs; use actual usage for final cost analysis.
    return math.ceil(len(prompt.encode("utf-8")) / 3) + 16


def cost(model, input_tokens, output_tokens):
    if model["input_usd_per_million"] is None or model["output_usd_per_million"] is None:
        return None
    return (input_tokens * model["input_usd_per_million"] + output_tokens * model["output_usd_per_million"]) / 1_000_000


def estimate(jobs, config, environment):
    rows = []
    for model in config["models"]:
        subset = [j for j in jobs if j["model"] == model["name"]]
        inputs = sum(token_estimate(j["prompt"]) for j in subset)
        expected_outputs = len(subset) * config["expected_output_tokens"]
        capped_outputs = len(subset) * config["generation"]["max_tokens"]
        available = bool(credential(model, environment))
        enabled = model.get("enabled", True)
        status = "ready" if enabled and available else "disabled" if not enabled else "missing_key"
        capped_cost = cost(model, inputs, capped_outputs)
        if status == "ready" and capped_cost is None:
            status = "missing_price"
        rows.append({"model": model["name"], "api_model": model["model"], "status": status,
                     "prompts": len(subset), "estimated_input_tokens": inputs,
                     "expected_output_tokens": expected_outputs, "capped_output_tokens": capped_outputs,
                     "expected_usd": cost(model, inputs, expected_outputs), "capped_usd": capped_cost})
    return rows


def print_estimate(rows, config):
    def usd(value):
        return "unknown" if value is None else f"${value:.4f}"

    for row in rows:
        print(f"{row['model']}: {row['status']}; {row['prompts']} prompts; "
              f"~{row['estimated_input_tokens']:,} input tokens; "
              f"{row['expected_output_tokens']:,} expected / {row['capped_output_tokens']:,} capped output tokens; "
              f"{usd(row['expected_usd'])} expected / {usd(row['capped_usd'])} at output cap")
    total = sum(row["capped_usd"] or 0 for row in rows if row["status"] == "ready")
    print(f"Ready models: ~${total:.4f} at output cap, ~${total * config['max_attempts']:.4f} "
          f"if every prompt uses all {config['max_attempts']} attempts.")
    print("Estimates use UTF-8 bytes/3 + 16 input tokens, not provider tokenizers. "
          "Prices exclude discounts/tax; retries or lost replies may be billed. This is not a guaranteed bill cap.")
    if all(m["provider"] == "ollama" for m in config["models"]):
        print("Local-only run: $0 API fees. Electricity, download bandwidth and computer time are not included.")


def load_completed(output, jobs):
    known = {j["response_id"]: j for j in jobs}
    rows = {}
    for path in sorted((output / "private" / "receipts").glob("*.csv")):
        values = read_csv(path, RESPONSE_FIELDS, exact=True)
        if len(values) != 1:
            raise ValueError(f"Invalid durable receipt: {path.name}")
        row = values[0]
        job = known.get(row["response_id"])
        if job is None or path.stem != row["response_id"] or row["response_id"] in rows:
            raise ValueError("Foreign or duplicate receipt; use a separate study directory.")
        if any(row[k] != job[k] for k in ("scenario_id", "domain", "framing", "model")):
            raise ValueError("Receipt metadata mismatch.")
        params = json.loads(row["generation_params"])
        if params.get("prompt_sha256") != digest(job["prompt"].encode()):
            raise ValueError("Receipt prompt hash mismatch.")
        rows[row["response_id"]] = row
    return rows


def rebuild_responses(output, completed):
    write_csv(output / "responses.csv", RESPONSE_FIELDS, [completed[k] for k in sorted(completed)])


def record_local_models(client, config, output):
    models = [m for m in config["models"] if m["provider"] == "ollama" and m.get("enabled", True)]
    if not models:
        return
    base = "http://127.0.0.1:11434"
    try:
        tags = client.get(base + "/api/tags")
        tags.raise_for_status()
        version = client.get(base + "/api/version")
        version.raise_for_status()
        runtime_version = version.json()["version"]
        if not isinstance(runtime_version, str) or not runtime_version:
            raise ValueError("Missing Ollama runtime version.")
        installed = {m["name"]: m for m in tags.json()["models"]}
        records = {}
        for model in models:
            entry = installed.get(model["model"])
            if not entry or not re.fullmatch(r"[a-f0-9]{64}", entry.get("digest", "")):
                raise ValueError(f"Local model {model['model']} is not downloaded. Run ollama pull first.")
            show = client.post(base + "/api/show", json={"model": model["model"]})
            show.raise_for_status()
            info = show.json()
            if (entry.get("remote_host") or info.get("remote_host")
                    or not info.get("details", {}).get("quantization_level")):
                raise ValueError("Model is remote or has no local quantization metadata; refusing it.")
            records[model["name"]] = {"digest": entry["digest"], "model": model["model"],
                                      "ollama_version": runtime_version,
                                      "details": info["details"], "template": info.get("template"),
                                      "system": info.get("system"), "parameters": info.get("parameters")}
    except httpx.HTTPError:
        raise ValueError("Could not inspect local Ollama models. Start ollama serve and pull the configured models.") from None
    path = output / "private" / "local_models.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if any(name in previous and previous[name] != record for name, record in records.items()):
        raise ValueError("Local model weights/template/runtime changed. Use the original setup or a new study directory.")
    atomic_write(path, json_text({**previous, **records}).encode())


def prepare_study(output, source_bytes, config, study_id):
    private = output / "private"
    private.mkdir(parents=True, exist_ok=True)
    manifest_path = private / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["study_id"] != study_id:
            raise ValueError("CSV or config changed. Resume with the original files, or choose a new --out directory.")
        if (private / "scenarios.csv").read_bytes() != source_bytes:
            raise ValueError("Scenario snapshot differs from the input.")
    else:
        if (output / "responses.csv").exists() or list((private / "receipts").glob("*.csv")):
            raise ValueError("Responses exist without a study manifest; refusing to overwrite them.")
        atomic_write(private / "scenarios.csv", source_bytes)
        atomic_write(manifest_path, json_text({"schema_version": 1, "study_id": study_id,
                     "created_at": utc_now(), "scenarios_sha256": digest(source_bytes), "config": config}).encode())


class EventLog:
    def __init__(self, output):
        self.path = output / "private" / "attempts.csv"
        self.failures_path = output / "failures.csv"
        self.rows = read_csv(self.path, ATTEMPT_FIELDS, exact=True) if self.path.exists() else []

    def append(self, row):
        self.rows.append({name: row.get(name, "") for name in ATTEMPT_FIELDS})
        write_csv(self.path, ATTEMPT_FIELDS, self.rows)
        write_csv(self.failures_path, ATTEMPT_FIELDS, [r for r in self.rows if r["event"] == "failed"])

    @property
    def reserved(self):
        return sum(float(r["reserved_usd"] or 0) for r in self.rows if r["event"] == "started")


def collect_jobs(jobs, config, environment, output, completed, client, *, budget_usd,
                 sleep=time.sleep, monotonic=time.monotonic):
    """Sequential scheduling avoids concurrent writes and keeps rate accounting simple."""
    models = {m["name"]: m for m in config["models"]}
    events = EventLog(output)
    last_call = {}
    suspended = set()
    failures = 0
    for job in jobs:
        model = models[job["model"]]
        key = credential(model, environment)
        if job["response_id"] in completed or key is None or model["name"] in suspended:
            continue
        ceiling = cost(model, token_estimate(job["prompt"]), config["generation"]["max_tokens"])
        if ceiling is None:
            continue
        body = request_body(model, job["prompt"], config["generation"])
        for attempt in range(1, config["max_attempts"] + 1):
            if events.reserved + ceiling > budget_usd:
                print("Estimated cumulative attempt budget reached; remaining rows are pending.")
                return failures
            bucket = (model["provider"], model["key_env"])
            minimum_gap = 60 / min(m["requests_per_minute"] for m in models.values()
                                   if (m["provider"], m["key_env"]) == bucket)
            sleep(max(0, last_call.get(bucket, -math.inf) + minimum_gap - monotonic()))
            last_call[bucket] = monotonic()
            event = {"attempt_id": str(len(events.rows) + 1), "response_id": job["response_id"],
                     "scenario_id": job["scenario_id"], "framing": job["framing"], "model": job["model"],
                     "attempt": attempt, "timestamp": utc_now()}
            events.append({**event, "event": "started", "reserved_usd": ceiling})
            started = monotonic()
            try:
                result = call_api(client, model, key, body)
            except APIFailure as exc:
                events.append({**event, "timestamp": utc_now(), "event": "failed", "error_type": exc.kind,
                               "http_status": exc.status or "", "provider_request_id": exc.request_id})
                print(f"Failed {job['scenario_id']}/{job['framing']}/{job['model']}: {exc.kind}, attempt {attempt}", flush=True)
                delay = max(exc.retry_after or 0, min(config["max_backoff_seconds"],
                            config["backoff_seconds"] * 2 ** (attempt - 1) + random.uniform(0, 1)))
                if exc.retryable and attempt < config["max_attempts"] and delay <= config["max_backoff_seconds"]:
                    sleep(delay)
                    continue
                failures += 1
                if exc.status in {400, 401, 403, 404, 429} or (exc.retry_after or 0) > config["max_backoff_seconds"]:
                    suspended.add(model["name"])
                    print(f"Suspending {model['name']} for this invocation; its remaining rows stay pending.")
                break
            params = {"provider": model["provider"], "requested_model": model["model"],
                      "requested": config["generation"], "effective": {
                          k: v for k, v in body.items() if k not in {"messages", "contents"}},
                      "notes": model["notes"], "prompt_sha256": digest(job["prompt"].encode()),
                      "latency_ms": round((monotonic() - started) * 1000, 2),
                      **{k: v for k, v in result.items() if k != "text"}}
            row = {k: job[k] for k in ("response_id", "scenario_id", "domain", "framing", "model")}
            row.update(response_text=result["text"], timestamp=utc_now(), generation_params=json_text(params))
            # Commit the receipt before touching the derived CSV or completion journal.
            write_csv(output / "private" / "receipts" / (job["response_id"] + ".csv"), RESPONSE_FIELDS, [row])
            completed[job["response_id"]] = row
            rebuild_responses(output, completed)
            events.append({**event, "timestamp": utc_now(), "event": "saved", "provider_request_id": result["provider_request_id"]})
            print(f"Saved {job['scenario_id']}/{job['framing']}/{job['model']} ({result['outcome']})", flush=True)
            break
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("models.json"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--out", type=Path, default=Path("research/runs/study"))
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--local-only", action="store_true", help="Refuse every cloud provider, regardless of configured keys")
    parser.add_argument("--yes", action="store_true", help="Explicitly accept the printed cost estimate for unattended use")
    parser.add_argument("--budget-usd", type=float, default=1.0, help="Cumulative estimated attempt reservations; not a billing guarantee")
    parser.add_argument("--model", action="append", help="Configured model name; repeat to select several")
    parser.add_argument("--scenario-id", action="append", help="Retry selected scenarios, skipping already saved rows")
    parser.add_argument("--framing", choices=["loaded", "neutral"])
    args = parser.parse_args(argv)
    number(args.budget_usd, 0, 100000, "budget-usd")
    config = read_config(args.config)
    if args.local_only and any(m["provider"] != "ollama" for m in config["models"] if m.get("enabled", True)):
        raise ValueError("--local-only forbids cloud models. Use --config research/models.local.json.")
    source = args.scenarios.read_bytes()
    scenarios = read_scenarios(args.scenarios, config["domains"])
    if args.scenarios.read_bytes() != source:
        raise ValueError("Scenarios changed while being read. Close the editor and retry.")
    study_id = digest(source + json_text(config).encode())
    all_jobs = make_jobs(scenarios, config, study_id)
    for chosen, known, label in ((args.model, {m["name"] for m in config["models"]}, "model"),
                                 (args.scenario_id, {r["scenario_id"] for r in scenarios}, "scenario-id")):
        if chosen and set(chosen) - known:
            raise ValueError(f"Unknown --{label} selection.")
    environment = {**dotenv_values(args.env, interpolate=False), **os.environ}
    manifest = args.out / "private" / "manifest.json"
    if manifest.exists() and json.loads(manifest.read_text(encoding="utf-8"))["study_id"] != study_id:
        raise ValueError("CSV/config changed; choose a new output directory.")
    completed = load_completed(args.out, all_jobs)
    selected = [j for j in all_jobs if j["response_id"] not in completed
                and (not args.model or j["model"] in args.model)
                and (not args.scenario_id or j["scenario_id"] in args.scenario_id)
                and (not args.framing or j["framing"] == args.framing)]
    projections = estimate(selected, config, environment)
    print(f"{len(scenarios)} scenarios; {len(scenarios) * 2} prompts/model; {len(completed)} saved responses.")
    print_estimate(projections, config)
    print(f"Output: {args.out.resolve()}; cumulative estimated attempt budget: ${args.budget_usd:.2f}")
    if args.estimate_only:
        return 0
    ready = {r["model"] for r in projections if r["status"] == "ready" and r["prompts"]}
    if selected and not ready:
        print("No runnable pending models. Set keys/prices; no API calls made.")
        return 2
    if ready and not args.yes:
        try:
            notice = "Run these prompts locally ($0 API fees)?" if args.local_only else "Send these prompts and incur API charges?"
            confirmed = input(notice + " Type RUN to continue: ") == "RUN"
        except EOFError:
            confirmed = False
        if not confirmed:
            print("Cancelled; no API calls made.")
            return 0
    with study_lock(args.out):
        prepare_study(args.out, source, config, study_id)
        completed = load_completed(args.out, all_jobs)
        rebuild_responses(args.out, completed)
        with httpx.Client(timeout=config["timeout_seconds"], follow_redirects=False, trust_env=False) as client:
            record_local_models(client, {**config, "models": [m for m in config["models"] if m["name"] in ready]}, args.out)
            collect_jobs(selected, config, environment, args.out, completed, client, budget_usd=args.budget_usd)
        pending = [{"response_id": j["response_id"], "scenario_id": j["scenario_id"],
                    "framing": j["framing"], "model": j["model"]} for j in all_jobs if j["response_id"] not in completed]
        write_csv(args.out / "pending.csv", ["response_id", "scenario_id", "framing", "model"], pending)
        print(f"Saved {len(completed)}/{len(all_jobs)} responses; {len(pending)} pending. See pending.csv and failures.csv.")
        return 2 if pending else 0


def cli():
    try:
        return main()
    except KeyboardInterrupt:
        print("Interrupted. Saved receipts are safe; rerun the same command to resume.", file=sys.stderr)
        return 130
    except (ValueError, OSError, csv.Error) as exc:
        # Validation errors are safe; OS errors disclose paths only, never HTTP bodies.
        print(f"Cannot run: {exc}", file=sys.stderr)
        return 1
if __name__ == "__main__":
    sys.exit(cli())
