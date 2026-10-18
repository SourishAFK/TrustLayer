"""Original HTTP contracts with deterministic provider and database doubles."""

import base64
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

with patch("dotenv.load_dotenv", return_value=False):
    from backend import main, store
    from backend.scorer import (
        HonestyAssessment,
        IntentGap,
        ScorerError,
        SycophancyResult,
        Verdict,
    )

@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-only-not-a-real-key")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TRUSTLAYER_CHAT_KEY", raising=False)
    # Unexpected provider calls fail the test instead of spending money.
    monkeypatch.setattr("google.genai.Client", Mock(side_effect=AssertionError("Live Gemini forbidden")))
    for method in ("init_db", "close_pool"):
        monkeypatch.setattr(store, method, Mock())
    monkeypatch.setattr(store, "_get_pool", Mock(side_effect=AssertionError("Live database forbidden")))
    key = {"key": "tl_fixture", "tier": "free", "daily_limit": 10, "log_inputs": False}
    monkeypatch.setattr(store, "validate_key", Mock(side_effect=lambda value: key if value == "tl_fixture" else None))
    monkeypatch.setattr(store, "check_and_increment_rate", Mock(return_value={
        "allowed": True, "count": 1, "limit": 10, "reset_at": "2030-01-01T00:00:00Z",
    }))
    monkeypatch.setattr(store, "log_usage", Mock(return_value=42))
    monkeypatch.setattr(store, "record_feedback", Mock(return_value=True))
    result = SycophancyResult(
        sycophancy_score=74, verdict=Verdict.SYCOPHANTIC,
        is_high_stakes=True, domain="fintech", matched_categories=["runway"],
        sycophancy_indicators=["unfounded reassurance"],
        suggested_honest_alternative="There are two months of runway.",
        intent_gap=IntentGap(explicit_ask="Assess runway", desired_outcome="reassurance", gap_score=.8),
        honesty=HonestyAssessment(honesty_score=.2, sycophancy_indicators=["unfounded reassurance"],
                                  suggested_honest_alternative="There are two months of runway."),
    )
    scorer = SimpleNamespace(score=Mock(return_value=result), model_name="fixture-model", last_model_used="fixture-model")
    monkeypatch.setattr(main, "get_scorer", lambda: scorer)
    with TestClient(main.app) as client:
        yield SimpleNamespace(client=client, scorer=scorer, key=key)


PAYLOAD = {"user_query": "What is my runway?", "ai_response": "You are doing great!", "domain": "fintech"}
HEADERS = {"Authorization": "Bearer tl_fixture"}


def test_original_routes_remain_available(api):
    paths = api.client.get("/openapi.json").json()["paths"]
    assert {"/", "/info", "/health", "/score", "/feedback", "/chat", "/chat/feedback"} <= paths.keys()
    assert api.client.get("/health").json() == {"status": "ok", "model": "fixture-model"}
    assert api.client.get("/").status_code == 200


@pytest.mark.parametrize("query_name", ["user_query", "query"])
@pytest.mark.parametrize("headers", [HEADERS, {"X-API-Key": "tl_fixture"}])
def test_scoring_contract_query_aliases_and_auth_headers(api, query_name, headers):
    payload = {query_name: PAYLOAD["user_query"], "ai_response": PAYLOAD["ai_response"], "domain": "fintech"}
    response = api.client.post("/score", headers=headers, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "sycophancy_score": 74, "verdict": "SYCOPHANTIC",
        "indicators": ["unfounded reassurance"],
        "suggested_honest_alternative": "There are two months of runway.",
        "intent_gap": .8, "response_honesty": .2, "domain_flagged": True,
        "high_stakes": True, "scoring_model_used": "fixture-model",
        "processing_time_ms": body["processing_time_ms"], "request_id": 42,
    }
    assert body["processing_time_ms"] >= 0
    args = store.log_usage.call_args.kwargs
    assert args["user_query"] is None and args["ai_response"] is None and args["context"] is None


def test_opt_in_input_logging_and_binary_attachment(api):
    api.key["log_inputs"] = True
    attachment = {"mime_type": "image/png", "data": base64.b64encode(b"fixture image").decode()}
    response = api.client.post("/score", headers=HEADERS, json={**PAYLOAD, "attachments": [attachment]})
    assert response.status_code == 200
    assert api.scorer.score.call_args.kwargs["attachments"] == [(b"fixture image", "image/png")]
    assert store.log_usage.call_args.kwargs["user_query"] == PAYLOAD["user_query"]


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_missing_or_invalid_key_blocks_scoring(api, headers):
    assert api.client.post("/score", headers=headers, json=PAYLOAD).status_code == 401
    api.scorer.score.assert_not_called()


def test_auth_storage_failure_is_unavailable(api):
    store.validate_key.side_effect = store.StoreError("fixture database outage")
    assert api.client.post("/score", headers=HEADERS, json=PAYLOAD).status_code == 503
    api.scorer.score.assert_not_called()


def test_daily_limit_preserves_error_shape_and_does_not_score(api):
    store.check_and_increment_rate.return_value["allowed"] = False
    response = api.client.post("/score", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 429
    assert response.json()["error"] == "rate_limit_exceeded"
    assert response.json()["reset_at"] == "2030-01-01T00:00:00Z"
    api.scorer.score.assert_not_called()


def test_rate_storage_failure_is_unavailable(api):
    store.check_and_increment_rate.side_effect = store.StoreError("fixture outage")
    assert api.client.post("/score", headers=HEADERS, json=PAYLOAD).status_code == 503
    api.scorer.score.assert_not_called()


@pytest.mark.parametrize("attachment", [
    {"mime_type": "text/html", "data": "aA=="},
    {"mime_type": "image/png", "data": "not base64!"},
])
def test_invalid_attachments_fail_before_provider(api, attachment):
    response = api.client.post("/score", headers=HEADERS, json={**PAYLOAD, "attachments": [attachment]})
    assert response.status_code == 400
    api.scorer.score.assert_not_called()


@pytest.mark.parametrize("error,status", [("RESOURCE_EXHAUSTED", 429), ("503 UNAVAILABLE", 503), ("invalid model output", 502)])
def test_provider_failures_preserve_http_contract(api, error, status):
    api.scorer.score.side_effect = ScorerError(error)
    assert api.client.post("/score", headers=HEADERS, json=PAYLOAD).status_code == status
    store.log_usage.assert_not_called()


def test_feedback_round_trip(api):
    response = api.client.post("/feedback", headers=HEADERS, json={"request_id": 42, "outcome": "human_overrode"})
    assert response.json() == {"ok": True, "request_id": 42}
    store.record_feedback.assert_called_once_with(42, None, "human_overrode", owners=["tl_fixture"])


# Fixed in Level 5 (previously a strict expected failure from the audit).
def test_feedback_must_pass_authenticated_owner_to_storage(api):
    api.client.post("/feedback", headers=HEADERS, json={"request_id": 42, "outcome": "upheld"})
    assert store.record_feedback.call_args.kwargs["owners"] == ["tl_fixture"]


def test_another_customers_request_id_is_not_found(api):
    store.record_feedback.return_value = False  # the owner-scoped UPDATE matched no row
    response = api.client.post("/feedback", headers=HEADERS, json={"request_id": 7, "outcome": "upheld"})
    assert response.status_code == 404


def test_chat_feedback_only_labels_public_chat_rows_once(api, monkeypatch):
    monkeypatch.setenv("TRUSTLAYER_CHAT_KEY", "tl_chatfixture")
    assert api.client.post("/chat/feedback", json={"request_id": 5, "outcome": "thumbs_up"}).status_code == 200
    kwargs = store.record_feedback.call_args.kwargs
    assert kwargs == {"owners": ["public-chat", "tl_chatfixture"], "first_write_only": True}


def test_upstream_errors_never_echo_model_output(api):
    api.scorer.score.side_effect = ScorerError("Could not parse Gemini output.\nRaw output:\nUSER SECRET TEXT")
    response = api.client.post("/score", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 502 and "USER SECRET TEXT" not in response.text


def test_chat_quota_store_outage_falls_back_to_memory_cap(api, monkeypatch):
    monkeypatch.setenv("TRUSTLAYER_CHAT_KEY", "tl_fixture")
    monkeypatch.setattr("backend.chat.generate_chat_reply", Mock(return_value="A generated reply."))
    store.check_and_increment_rate.side_effect = store.StoreError("fixture outage")
    monkeypatch.setattr(main, "_public_chat_allowed", lambda: False)
    response = api.client.post("/chat", json={"messages": [{"role": "user", "content": "Hello"}]})
    assert response.status_code == 429  # previously failed open


@pytest.mark.parametrize("messages", [
    [{"role": "user", "content": "x"}] * 51,
    [{"role": "user", "content": "x", "image_b64": "aGk=", "image_mime": "image/png"}] * 5,
])
def test_chat_request_size_limits(api, messages):
    assert api.client.post("/chat", json={"messages": messages}).status_code == 422


def test_security_headers(api):
    headers = api.client.get("/info").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"


def test_chat_marks_scorer_failure_unverified(api, monkeypatch):
    monkeypatch.setattr("backend.chat.generate_chat_reply", Mock(return_value="A generated reply."))
    monkeypatch.setattr(main, "_public_chat_allowed", lambda: True)
    api.scorer.score.side_effect = ScorerError("fixture failure")
    response = api.client.post("/chat", json={"messages": [{"role": "user", "content": "Hello"}]})
    assert response.status_code == 200
    assert response.json()["unverified"] is True
    assert response.json()["reply"] == "A generated reply."
