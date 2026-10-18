"""Level 2 HTTP contract: /v1/verify, /v1/verify/stream and /v1/status.

The real pipeline runs offline (no providers, no research engines). Live
adapters, the legacy scorer and input persistence are forbidden.
"""

import gc
import json
import logging
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

with patch("dotenv.load_dotenv", return_value=False):
    from backend import main, store
    from backend.verification import budget, pipeline
    from backend.verification.contracts import Providers
    from backend.verification.report import VerificationRequest

VERIFY, STREAM = "/v1/verify", "/v1/verify/stream"
HEADERS = {"Authorization": "Bearer tl_fixture"}
TEXT = "Zorblax Labs was founded in 2019. Zorblax Labs has 40 employees."
BODY = {"response_text": TEXT}
CONFIG_INVALID = {"detail": "Verification configuration is invalid."}


def offline(run):
    """The real pipeline function with no providers and no research engines: no network."""
    return lambda request, **kw: run(request, **{**kw, "providers": Providers(), "engines": [[], [], []]})


@pytest.fixture
def client(monkeypatch):
    record = {"key": "tl_fixture", "daily_limit": 10}
    monkeypatch.setattr(store, "validate_key", lambda key: record if key == "tl_fixture" else None)
    monkeypatch.setattr(store, "check_and_increment_rate", Mock(return_value={"allowed": True}))
    for method in ("init_db", "close_pool"):
        monkeypatch.setattr(store, method, Mock())
    monkeypatch.setattr(store, "log_usage", Mock(side_effect=AssertionError("No input persistence")))
    monkeypatch.setattr(main, "get_scorer", Mock(side_effect=AssertionError("No model calls")))
    monkeypatch.setattr(pipeline, "configured_providers", Mock(side_effect=AssertionError("No live providers")))
    monkeypatch.setattr(pipeline, "default_engines", Mock(side_effect=AssertionError("No live engines")))
    # The real stream calls the module-level verify, so both paths stay offline.
    monkeypatch.setattr(pipeline, "stream_ndjson", offline(pipeline.stream_ndjson))
    monkeypatch.setattr(pipeline, "verify", Mock(side_effect=offline(pipeline.verify)))
    # One slot: a request that leaks its slot makes the next one in the test fail.
    monkeypatch.setattr(main, "_VERIFY_SLOTS", threading.BoundedSemaphore(1))
    with TestClient(main.app) as client:
        yield client


def test_verify_returns_report_without_logging_or_persisting_input(client, caplog):
    caplog.set_level(logging.DEBUG)
    response = client.post(VERIFY, headers=HEADERS, json=BODY)
    assert response.status_code == 200
    report = response.json()
    assert report["schema_version"] == "2.0" and report["response_text"] == TEXT
    assert report["claims"] and report["summary"]["supported"] == 0  # no sources, nothing SUPPORTED
    store.check_and_increment_rate.assert_called_once_with("tl_fixture", 10)
    store.log_usage.assert_not_called()
    assert "Zorblax" not in caplog.text


@pytest.mark.parametrize("path", [VERIFY, STREAM])
def test_auth_and_request_validation(client, path):
    assert client.post(path, json=BODY).status_code == 401
    assert client.post(path, headers=HEADERS, json={**BODY, "unexpected": True}).status_code == 422
    assert client.post(path, headers=HEADERS, json={"response_text": "   "}).status_code == 422
    store.check_and_increment_rate.assert_not_called()
    pipeline.verify.assert_not_called()


@pytest.mark.parametrize("path", [VERIFY, STREAM])
def test_quota_exhaustion_and_store_outage(client, path):
    store.check_and_increment_rate.return_value = {"allowed": False, "reset_at": "2030-01-01T00:00:00Z"}
    response = client.post(path, headers=HEADERS, json=BODY)
    assert response.status_code == 429
    assert response.json() == {"error": "rate_limit_exceeded", "message": "Daily request limit reached.",
                               "reset_at": "2030-01-01T00:00:00Z"}
    store.check_and_increment_rate.side_effect = store.StoreError("internal details")
    response = client.post(path, headers=HEADERS, json=BODY)
    assert response.status_code == 503 and "internal details" not in response.text
    pipeline.verify.assert_not_called()


@pytest.mark.parametrize("path", [VERIFY, STREAM])
def test_invalid_budget_config_fails_closed_per_mode(client, monkeypatch, path):
    monkeypatch.setenv("TRUSTLAYER_QUICK_MAX_SECONDS", "0")
    response = client.post(path, headers=HEADERS, json=BODY)
    assert response.status_code == 503 and response.json() == CONFIG_INVALID
    pipeline.verify.assert_not_called()
    # Deep limits are valid, and the refused request did not keep the only slot.
    assert client.post(path, headers=HEADERS, json={**BODY, "mode": "deep"}).status_code == 200


def test_config_error_inside_the_pipeline_is_503(client, monkeypatch):
    monkeypatch.setenv("TRUSTLAYER_CLAIM_MAX_CLAIMS", "0")
    response = client.post(VERIFY, headers=HEADERS, json=BODY)
    assert response.status_code == 503 and response.json() == CONFIG_INVALID
    assert main._VERIFY_SLOTS.acquire(blocking=False)


def test_busy_capacity_is_503_and_slots_are_released(client, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(main, "_VERIFY_SLOTS", slots)
    for path in (VERIFY, STREAM):
        response = client.post(path, headers=HEADERS, json=BODY)
        assert response.status_code == 503
        assert response.json() == {"detail": "Verification capacity is busy. Try again shortly."}
        assert response.headers["retry-after"] == "5"
    pipeline.verify.assert_not_called()
    slots.release()
    for path in (VERIFY, STREAM, VERIFY):
        assert client.post(path, headers=HEADERS, json=BODY).status_code == 200
    assert slots.acquire(blocking=False)


def test_concurrency_setting_is_validated(client, monkeypatch):
    for raw, valid in (("1", True), ("64", True), ("0", False), ("65", False), ("four", False)):
        monkeypatch.setenv("TRUSTLAYER_MAX_CONCURRENT_VERIFICATIONS", raw)
        assert (main._verification_slots() is not None) is valid
    monkeypatch.delenv("TRUSTLAYER_MAX_CONCURRENT_VERIFICATIONS")
    assert main._verification_slots() is not None
    monkeypatch.setattr(main, "_VERIFY_SLOTS", None)
    for path in (VERIFY, STREAM):
        response = client.post(path, headers=HEADERS, json=BODY)
        assert response.status_code == 503 and response.json() == CONFIG_INVALID


def test_unexpected_failures_are_generic_and_free_the_slot(client, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    leak = "Zorblax private page text"
    pipeline.verify.side_effect = RuntimeError(leak)
    response = client.post(VERIFY, headers=HEADERS, json=BODY)
    assert response.status_code == 500 and leak not in response.text

    def broken_stream(request, *, on_start=None, on_done=None, **kw):
        on_start()  # a worker that ran and finished, then a failure while streaming
        on_done()
        yield json.dumps({"type": "progress"}) + "\n"
        raise RuntimeError(leak)

    monkeypatch.setattr(pipeline, "stream_ndjson", broken_stream)
    response = client.post(STREAM, headers=HEADERS, json=BODY)
    assert response.status_code == 200 and leak not in response.text
    assert json.loads(response.text.splitlines()[-1])["type"] == "error"
    assert leak not in caplog.text and "RuntimeError" in caplog.text
    assert main._VERIFY_SLOTS.acquire(blocking=False)


def test_stream_is_ndjson_ending_with_the_report(client):
    response = client.post(STREAM, headers=HEADERS, json=BODY)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-ndjson"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"
    lines = [json.loads(line) for line in response.text.splitlines()]
    assert len(lines) > 1 and all(line["type"] == "progress" for line in lines[:-1])
    assert lines[-1]["type"] == "report" and lines[-1]["report"]["schema_version"] == "2.0"
    store.check_and_increment_rate.assert_called_once_with("tl_fixture", 10)
    store.log_usage.assert_not_called()


def test_stream_that_never_starts_still_frees_its_slot(client):
    # A client can leave before Starlette pulls the first line; the slot must not leak.
    response = main.verify_response_stream(VerificationRequest(**BODY), {"key": "tl_fixture", "daily_limit": 10})
    assert not main._VERIFY_SLOTS.acquire(blocking=False)
    del response
    gc.collect()
    assert main._VERIFY_SLOTS.acquire(blocking=False)
    pipeline.verify.assert_not_called()


def test_status_is_public_and_lists_names_never_secrets(client, monkeypatch):
    secrets = {"ANTHROPIC_API_KEY": "sk-ant-qz81-fixture", "GEMINI_API_KEY": "AIzaQZ81-fixture",
               "BRAVE_SEARCH_API_KEY": "BSAqz81-fixture"}
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("TRUSTLAYER_RESPECT_ROBOTS", raising=False)
    monkeypatch.setenv("TRUSTLAYER_REPORT_RETENTION_HOURS", "24")
    # The fakes hold the keys, so exposing whole provider objects would fail below.
    providers = [SimpleNamespace(name="brave", api_key=secrets["BRAVE_SEARCH_API_KEY"]),
                 SimpleNamespace(name="wikipedia", api_key=None)]
    monkeypatch.setitem(sys.modules, "backend.verification.search", SimpleNamespace(
        configured_search_providers=lambda mode: providers if mode == "deep" else []))
    monkeypatch.setitem(sys.modules, "backend.verification.llm", SimpleNamespace(
        available_providers=lambda: ["anthropic", "gemini"]))

    response = client.get("/v1/status")
    assert response.status_code == 200
    assert response.json() == {
        "service": "TrustLayer", "schema_version": "2.0",
        "modes": {mode: budget.limits_for(mode).public().model_dump() for mode in ("quick", "deep")},
        "search_providers": ["brave", "wikipedia"], "ai_providers": ["anthropic", "gemini"],
        "fetching": {"ssrf_protection": True, "respects_robots_txt": True},
        "retention_hours": 24,
    }
    for value in secrets.values():
        assert value[:6] not in response.text

    monkeypatch.setenv("TRUSTLAYER_RESPECT_ROBOTS", "False")
    assert client.get("/v1/status").json()["fetching"]["respects_robots_txt"] is False
    monkeypatch.setenv("TRUSTLAYER_DEEP_MAX_COST_USD", "nope")
    response = client.get("/v1/status")
    assert response.status_code == 503 and response.json() == CONFIG_INVALID


def test_legacy_routes_unchanged(client):
    paths = client.get("/openapi.json").json()["paths"]
    legacy = {"/": "get", "/info": "get", "/health": "get", "/score": "post", "/feedback": "post",
              "/chat": "post", "/chat/feedback": "post", "/v1/claims/extract": "post"}
    assert all(method in paths[path] for path, method in legacy.items())
    assert client.get("/info").json() == {"service": "TrustLayer", "tagline": "Confidence is not Trust.",
                                          "phase": 2, "endpoint": "POST /score", "docs": "/"}
    for path, method in ((VERIFY, "post"), (STREAM, "post"), ("/v1/status", "get")):
        assert paths[path][method]["tags"] == ["Verification"]


def test_a_dropped_stream_holds_its_slot_until_the_work_ends(monkeypatch):
    # Drop-and-reopen must not exceed the cap: the slot follows the work, not the client.
    from backend.verification.report import ProgressEvent

    running, unblock, finished = threading.Event(), threading.Event(), threading.Event()

    def slow_verify(request, *, emit=None, cancel=None, finalize=None, **kw):
        emit(ProgressEvent(type="stage", stage="evidence", status="started", message="x", elapsed_ms=0))
        running.set()
        unblock.wait(10)  # an in-flight provider call that ignores `cancel`
        finished.set()
        raise RuntimeError("done")

    monkeypatch.setattr(pipeline, "verify", slow_verify)
    slots = threading.BoundedSemaphore(1)
    assert slots.acquire(blocking=False)
    stream = main._stream_holding_slot(VerificationRequest(**BODY), slots, "tl_test")
    next(stream)  # the route's priming item
    assert json.loads(next(stream))["type"] == "progress" and running.wait(5)
    stream.close()  # the client disconnects
    assert not slots.acquire(blocking=False)
    unblock.set()
    assert finished.wait(5)
    for _ in range(250):
        if slots.acquire(blocking=False):
            break
        threading.Event().wait(0.02)
    else:
        pytest.fail("the slot was never released after the work ended")


def test_a_stream_closed_before_its_work_starts_releases_exactly_once(monkeypatch):
    monkeypatch.setattr(pipeline, "verify", Mock(side_effect=AssertionError("must not start")))
    slots = threading.BoundedSemaphore(1)
    assert slots.acquire(blocking=False)
    stream = main._stream_holding_slot(VerificationRequest(**BODY), slots, "tl_test")
    next(stream)
    stream.close()  # a second release would raise ValueError (BoundedSemaphore)
    assert slots.acquire(blocking=False)


def test_a_finished_stream_has_freed_its_slot_when_it_ends(client):
    for _ in range(3):  # one slot in the fixture: a slot still held would make the next call 503
        response = client.post(STREAM, headers=HEADERS, json=BODY)
        assert response.status_code == 200
        assert json.loads(response.text.splitlines()[-1])["type"] == "report"
    assert main._VERIFY_SLOTS.acquire(blocking=False)
