"""Offline data-integrity tests. Scenarios are copied from the user's format examples."""

import copy
import json
from pathlib import Path

import httpx
import pytest

from research import collect, common
from research.blind import create_blind
from research.common import (
    BLIND_FIELDS,
    RESPONSE_FIELDS,
    SCENARIO_FIELDS,
    digest,
    json_text,
    read_csv,
    read_scenarios,
    write_csv,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "research/scenarios_format_example.csv"


@pytest.fixture
def study(tmp_path):
    config = collect.read_config(ROOT / "research/models.json")
    config["models"] = config["models"][:1]
    scenarios = read_scenarios(EXAMPLE)[:1]
    source = tmp_path / "scenarios.csv"
    write_csv(source, SCENARIO_FIELDS, scenarios)
    data = source.read_bytes()
    identity = digest(data + json_text(config).encode())
    jobs = collect.make_jobs(scenarios, config, identity)
    out = tmp_path / "run"
    collect.prepare_study(out, data, config, identity)
    return config, jobs, out, source


def success(text='fixture answer, "quoted"\nsecond line — ₹', reason="stop"):
    return httpx.Response(200, json={"model": "fixture-model", "id": "fixture-id",
                                   "choices": [{"message": {"content": text}, "finish_reason": reason}],
                                   "usage": {"prompt_tokens": 25, "completion_tokens": 8}})


def run_study(study, handler, *, completed=None, budget=1):
    config, jobs, output, _ = study
    saved = {} if completed is None else completed
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collect.collect_jobs(jobs, config, {"OPENAI_API_KEY": "fixture-key"}, output, saved,
                             client, budget_usd=budget, sleep=lambda _: None)
    return saved


def test_user_examples_have_exact_required_header_and_preserved_text():
    rows = read_scenarios(EXAMPLE)
    assert len(rows) == 3 and list(rows[0]) == SCENARIO_FIELDS
    assert rows[0]["loaded_prompt"].startswith("We're doing pretty well financially, right?")
    assert read_csv(ROOT / "research/scenarios_template.csv", SCENARIO_FIELDS) == []


@pytest.mark.parametrize("defect", ["duplicate", "blank", "missing", "bad_domain", "identical"])
def test_input_validation_rejects_incomplete_or_ambiguous_records(tmp_path, defect):
    rows = read_scenarios(EXAMPLE)
    fields = SCENARIO_FIELDS.copy()
    if defect == "duplicate":
        rows[1]["scenario_id"] = rows[0]["scenario_id"]
    elif defect == "blank":
        rows[0]["neutral_prompt"] = " "
    elif defect == "missing":
        fields.remove("ground_truth")
        rows = [{k: v for k, v in r.items() if k in fields} for r in rows]
    elif defect == "bad_domain":
        rows[0]["domain"] = "invalid_fixture"
    else:
        rows[0]["neutral_prompt"] = rows[0]["loaded_prompt"]
    source = tmp_path / "invalid.csv"
    write_csv(source, fields, rows)
    with pytest.raises(ValueError):
        read_scenarios(source, {"fintech"})


def test_csv_roundtrips_multiline_unicode_quotes_and_extra_metadata(tmp_path):
    rows = read_scenarios(EXAMPLE)[:1]
    rows[0]["annotation_note"] = 'private, "annotation"\n₹ — 🚀'
    path = tmp_path / "roundtrip.csv"
    write_csv(path, [*SCENARIO_FIELDS, "annotation_note"], rows)
    assert read_scenarios(path) == rows


@pytest.mark.parametrize("provider", list(collect.PROVIDERS))
def test_each_provider_gets_only_one_exact_user_prompt_and_no_ground_truth(provider):
    scenario = read_scenarios(EXAMPLE)[0]
    model = {"provider": provider, "model": "fixture"}
    body = collect.request_body(model, scenario["loaded_prompt"], {"temperature": 0.2, "max_tokens": 512})
    if provider == "gemini":
        assert body["contents"] == [{"role": "user", "parts": [{"text": scenario["loaded_prompt"]}]}]
        assert body["generationConfig"]["maxOutputTokens"] == 512
    else:
        assert body["messages"] == [{"role": "user", "content": scenario["loaded_prompt"]}]
        if provider == "ollama":
            assert body["options"] == {"temperature": 0.2, "num_predict": 512}
        else:
            assert body.get("max_tokens", body.get("max_completion_tokens")) == 512
    assert scenario["ground_truth"] not in json_text(body)
    assert scenario["neutral_prompt"] not in json_text(body)


@pytest.mark.parametrize("provider", list(collect.PROVIDERS))
def test_provider_http_shapes_and_usage(provider):
    def handler(request):
        assert str(request.url) == (collect.PROVIDERS[provider] + "fixture:generateContent"
                                    if provider == "gemini" else collect.PROVIDERS[provider])
        assert "fixture-key" not in str(request.url)
        if provider == "ollama":
            assert "authorization" not in request.headers
            return httpx.Response(200, json={"model": "fixture", "message": {"content": "mock"}, "done": True,
                                           "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 4})
        if provider == "anthropic":
            assert request.headers["x-api-key"] == "fixture-key"
            return httpx.Response(200, json={"model": "fixture", "content": [{"type": "text", "text": "mock"}],
                                           "stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 4}})
        if provider == "gemini":
            assert request.headers["x-goog-api-key"] == "fixture-key"
            return httpx.Response(200, json={"modelVersion": "fixture", "candidates": [{"content": {
                "parts": [{"text": "private thought", "thought": True}, {"text": "mock"}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4}})
        assert request.headers["authorization"] == "Bearer fixture-key"
        return success("mock")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = collect.call_api(client, {"provider": provider, "model": "fixture"}, "fixture-key", {})
    assert result["text"] == "mock" and result["usage"]["output_tokens"] in {4, 8}


def test_retry_after_backoff_and_failure_log_are_durable_and_redacted(study):
    requests = []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"retry-after": "3"}, text="secret fixture-key")
        return success()
    saved = run_study(study, handler)
    assert len(saved) == 2 and len(requests) == 3
    failures = read_csv(study[2] / "failures.csv", collect.ATTEMPT_FIELDS)
    assert len(failures) == 1 and failures[0]["scenario_id"] == "S01"
    assert failures[0]["http_status"] == "429"
    assert "fixture-key" not in (study[2] / "failures.csv").read_text()
    assert collect.retry_after_seconds({"retry-after-ms": "2000"}) == 2
    assert collect.retry_after_seconds({"retry-after": "NaN"}) is None
    assert collect.retry_after_seconds({"retry-after": "3"}) == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 503])
def test_failure_retries_are_bounded_and_rows_remain_pending(study, status):
    seen = []
    saved = run_study(study, lambda req: seen.append(req) or httpx.Response(status, text="secret fixture-key"))
    assert not saved
    assert len(seen) == (6 if status == 503 else 3 if status == 429 else 1)
    failures = read_csv(study[2] / "failures.csv", collect.ATTEMPT_FIELDS)
    assert len(failures) == len(seen)


def test_successful_rows_are_not_repeated_on_resume(study):
    run_study(study, lambda _: success())
    saved = collect.load_completed(study[2], study[1])
    def no_request(_):
        pytest.fail("A completed response was sent again")
    run_study(study, no_request, completed=saved)
    assert len(read_csv(study[2] / "responses.csv", RESPONSE_FIELDS)) == 2


def test_crash_after_receipt_before_export_does_not_lose_response(study, monkeypatch):
    original = collect.rebuild_responses
    def crash(*_):
        raise OSError("simulated disk failure after receipt committed")
    monkeypatch.setattr(collect, "rebuild_responses", crash)
    with pytest.raises(OSError):
        run_study(study, lambda _: success())
    saved = collect.load_completed(study[2], study[1])
    assert len(saved) == 1
    monkeypatch.setattr(collect, "rebuild_responses", original)
    calls = []
    run_study(study, lambda req: calls.append(req) or success(), completed=saved)
    assert len(calls) == 1 and len(read_csv(study[2] / "responses.csv", RESPONSE_FIELDS)) == 2


def test_interrupt_is_journaled_before_network(study):
    def interrupt(_):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        run_study(study, interrupt)
    rows = read_csv(study[2] / "private/attempts.csv", collect.ATTEMPT_FIELDS)
    assert len(rows) == 1 and rows[0]["event"] == "started"
    assert collect.load_completed(study[2], study[1]) == {}


def test_atomic_write_keeps_previous_version_on_replace_failure(tmp_path, monkeypatch):
    path = tmp_path / "saved.csv"
    common.atomic_write(path, b"original")
    def fail(*_):
        raise OSError("simulated replace failure")
    monkeypatch.setattr(common.os, "replace", fail)
    with pytest.raises(OSError):
        common.atomic_write(path, b"new")
    assert path.read_bytes() == b"original" and not list(tmp_path.glob("*.tmp"))


def test_same_directory_cannot_have_two_writers(tmp_path):
    with common.study_lock(tmp_path):
        with pytest.raises(ValueError, match="Another process"):
            with common.study_lock(tmp_path):
                pytest.fail("lock not exclusive")


@pytest.mark.parametrize("persistent", [False, True])
def test_windows_sharing_lock_retries_are_bounded_without_losing_original(tmp_path, monkeypatch, persistent):
    path = tmp_path / "saved.csv"
    common.atomic_write(path, b"original")
    replace, calls, waits = common.os.replace, [], []
    def locked_replace(source, target):
        calls.append(target)
        assert path.read_bytes() == b"original"
        if persistent or len(calls) <= 2:
            error = PermissionError("simulated Windows sharing lock")
            error.winerror = 32
            raise error
        return replace(source, target)
    monkeypatch.setattr(common.os, "replace", locked_replace)
    monkeypatch.setattr(common.time, "sleep", waits.append)
    if persistent:
        with pytest.raises(PermissionError):
            common.atomic_write(path, b"new")
        assert len(calls) == 5 and path.read_bytes() == b"original"
        assert waits == [0.1, 0.2, 0.4, 0.8]
    else:
        common.atomic_write(path, b"new")
        assert len(calls) == 3 and path.read_bytes() == b"new"
        assert waits == [0.1, 0.2]
    assert not list(tmp_path.glob("*.tmp"))


def test_resume_rejects_changed_inputs_or_settings(study):
    with pytest.raises(ValueError, match="changed"):
        collect.prepare_study(study[2], b"changed source", study[0], "different-identity")


def test_budget_stops_before_api_and_missing_prices_are_not_zero(study):
    seen = []
    saved = run_study(study, lambda req: seen.append(req) or success(), budget=0)
    assert not seen and not saved
    study[0]["models"][0]["output_usd_per_million"] = None
    saved = run_study(study, lambda req: seen.append(req) or success())
    assert not seen and not saved


def test_refusals_truncation_and_blocked_outputs_are_preserved():
    assert collect.parse_response("openai", success("partial", "length").json())["outcome"] == "truncated"
    blocked = collect.parse_response("gemini", {"promptFeedback": {"blockReason": "SAFETY"}})
    assert blocked["text"] == "" and blocked["outcome"] == "blocked"
    refusal = collect.parse_response("openai", {"choices": [{"message": {"refusal": "I cannot answer."}, "finish_reason": "stop"}]})
    assert refusal["text"] == "I cannot answer." and refusal["outcome"] == "blocked"
    with pytest.raises(ValueError):
        collect.parse_response("openai", success("").json())


def test_blinding_is_reproducible_exact_and_separate(study, tmp_path):
    run_study(study, lambda _: success())
    first, second = tmp_path / "blind-one", tmp_path / "blind-two"
    assert create_blind(study[2], first, 812) == 2
    create_blind(study[2], second, 812)
    assert (first / "share/blind_labels.csv").read_bytes() == (second / "share/blind_labels.csv").read_bytes()
    labels = read_csv(first / "share/blind_labels.csv", BLIND_FIELDS, exact=True)
    mapping = read_csv(first / "private/mapping.csv", ["blind_id", "response_id"], exact=True)
    originals = {r["response_id"]: r for r in read_csv(study[2] / "responses.csv", RESPONSE_FIELDS)}
    prompts = {r["scenario_id"]: r for r in read_scenarios(study[3])}
    for label, mapped in zip(labels, mapping):
        raw = originals[mapped["response_id"]]
        assert label["blind_id"] == mapped["blind_id"]
        assert label["ai_response"] == raw["response_text"]
        assert label["user_prompt"] == prompts[raw["scenario_id"]][raw["framing"] + "_prompt"]
        assert label["verdict"] == label["confidence_1_to_5"] == label["reasoning"] == ""
    assert "openai" not in (first / "share/blind_labels.csv").read_text()
    assert json.loads((first / "private/blinding_metadata.json").read_text())["seed"] == 812
    with pytest.raises(FileExistsError):
        create_blind(study[2], first, 812)


def test_partial_blinding_requires_explicit_choice(study, tmp_path):
    whole_jobs = study[1].copy()
    study[1].pop()
    run_study(study, lambda _: success())
    with pytest.raises(ValueError, match="Only 1/2"):
        create_blind(study[2], tmp_path / "blind", 7)
    assert create_blind(study[2], tmp_path / "blind", 7, allow_partial=True) == 1
    assert len(collect.load_completed(study[2], whole_jobs)) == 1


def test_blinder_rejects_modified_response(study, tmp_path):
    run_study(study, lambda _: success())
    path = study[2] / "responses.csv"
    rows = read_csv(path, RESPONSE_FIELDS)
    rows[0]["response_text"] = "tampered"
    write_csv(path, RESPONSE_FIELDS, rows)
    with pytest.raises(ValueError, match="differs"):
        create_blind(study[2], tmp_path / "blind", 7)


def test_no_network_for_estimate_missing_keys_or_declined_confirmation(study, monkeypatch):
    def no_client(*a, **k):
        pytest.fail("Unexpected client creation")
    monkeypatch.setattr(collect.httpx, "Client", no_client)
    monkeypatch.setattr(collect, "dotenv_values", lambda *a, **k: {})
    monkeypatch.setattr(collect.os, "environ", {})
    config_path = study[3].parent / "config.json"
    config_path.write_text(json_text(study[0]))
    args = ["--scenarios", str(study[3]), "--config", str(config_path), "--out", str(study[2])]
    assert collect.main([*args, "--estimate-only"]) == 0
    assert collect.main(args) == 2
    monkeypatch.setattr(collect.os, "environ", {"OPENAI_API_KEY": "fixture-key"})
    monkeypatch.setattr("builtins.input", lambda _: "NO")
    assert collect.main(args) == 0
    with pytest.raises(ValueError, match="forbids"):
        collect.main([*args, "--local-only"])


def test_local_models_require_local_weights_and_cannot_drift(tmp_path):
    config = collect.read_config(ROOT / "research/models.local.json")
    config["models"] = config["models"][:1]
    model = config["models"][0]["model"]
    details = {"quantization_level": "Q4_K_M"}
    remote = False
    def handler(request):
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": model, "digest": "a" * 64}]})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test-runtime"})
        return httpx.Response(200, json={"details": details, "remote_host": "cloud.example" if remote else None})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collect.record_local_models(client, config, tmp_path)
        collect.record_local_models(client, config, tmp_path)
        details["quantization_level"] = "Q8_0"
        with pytest.raises(ValueError, match="changed"):
            collect.record_local_models(client, config, tmp_path)
        remote = True
        with pytest.raises(ValueError, match="remote"):
            collect.record_local_models(client, config, tmp_path)


def test_invalid_config_cannot_override_prompt_or_inject_keys(tmp_path):
    config = collect.read_config(ROOT / "research/models.json")
    config["models"][0]["provider_options"] = {"messages": []}
    path = tmp_path / "config.json"
    path.write_text(json_text(config))
    with pytest.raises(ValueError, match="provider_options"):
        collect.read_config(path)
    config = copy.deepcopy(collect.read_config(ROOT / "research/models.local.json"))
    config["models"][0]["model"] = "example:cloud"
    path.write_text(json_text(config))
    with pytest.raises(ValueError, match="no cloud"):
        collect.read_config(path)


def test_local_provenance_accumulates_when_running_one_model_at_a_time(tmp_path):
    config = collect.read_config(ROOT / "research/models.local.json")
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m["model"], "digest": "a" * 64}
                                                       for m in config["models"]]})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test-runtime"})
        return httpx.Response(200, json={"details": {"quantization_level": "Q4_K_M"}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        for model in config["models"]:
            collect.record_local_models(client, {**config, "models": [model]}, tmp_path)
    provenance = json.loads((tmp_path / "private/local_models.json").read_text())
    assert set(provenance) == {m["name"] for m in config["models"]}


@pytest.mark.parametrize("provider,data", [
    ("openai", {"choices": [{"message": None}]}),
    ("gemini", {"candidates": [None]}),
    ("anthropic", {"content": [None]}),
    ("ollama", {"done": True, "message": None}),
])
def test_malformed_nested_provider_data_is_logged_failure(provider, data):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))) as client:
        with pytest.raises(collect.APIFailure, match="malformed_response"):
            collect.call_api(client, {"provider": provider, "model": "fixture"}, "fixture-key", {})


def test_local_estimate_allows_zero_budget_and_makes_no_network_calls(monkeypatch):
    def no_client(*a, **k):
        pytest.fail("Estimate must never contact a model")
    monkeypatch.setattr(collect.httpx, "Client", no_client)
    assert collect.main(["--scenarios", str(EXAMPLE), "--config", str(ROOT / "research/models.local.json"),
                         "--local-only", "--budget-usd", "0", "--estimate-only"]) == 0


def test_backoff_honors_provider_delay_and_stops_for_excessive_wait(study):
    calls, waits = [], []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "10"})
        return success()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collect.collect_jobs(study[1], study[0], {"OPENAI_API_KEY": "fixture-key"}, study[2], {},
                             client, budget_usd=1, sleep=waits.append)
    assert 10 in waits and len(calls) == 3
    calls.clear()
    with httpx.Client(transport=httpx.MockTransport(
            lambda req: calls.append(req) or httpx.Response(429, headers={"retry-after": "600"}))) as client:
        collect.collect_jobs(study[1], study[0], {"OPENAI_API_KEY": "fixture-key"}, study[2], {},
                             client, budget_usd=1, sleep=lambda _: None)
    assert len(calls) == 1
