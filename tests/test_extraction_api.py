from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

with patch("dotenv.load_dotenv", return_value=False):
    from backend import main, store


@pytest.fixture
def client(monkeypatch):
    record = {"key": "tl_fixture", "daily_limit": 10}
    monkeypatch.setattr(store, "validate_key", lambda key: record if key == "tl_fixture" else None)
    monkeypatch.setattr(store, "check_and_increment_rate", Mock(return_value={"allowed": True}))
    for method in ("init_db", "close_pool"):
        monkeypatch.setattr(store, method, Mock())
    monkeypatch.setattr(store, "log_usage", Mock(side_effect=AssertionError("No input persistence")))
    monkeypatch.setattr(main, "get_scorer", Mock(side_effect=AssertionError("No model calls")))
    with TestClient(main.app) as client:
        yield client


PATH = "/v1/claims/extract"
HEADERS = {"Authorization": "Bearer tl_fixture"}


def test_api_round_trip_uses_auth_and_existing_rate_limits(client):
    response = client.post(PATH, headers=HEADERS, json={"response_text": "Acme has no competitors."})
    assert response.status_code == 200
    data = response.json()
    assert data["claims"][0]["verification_status"] == "UNVERIFIED"
    assert data["summary"]["investigated"] == 0
    assert data["usage"]["model_tokens"] == 0
    store.check_and_increment_rate.assert_called_once_with("tl_fixture", 10)
    store.log_usage.assert_not_called()


def test_auth_and_invalid_requests(client):
    assert client.post(PATH, json={"response_text": "Acme is private."}).status_code == 401
    assert client.post(PATH, headers=HEADERS, json={"response_text": " "}).status_code == 422
    assert client.post(PATH, headers=HEADERS, json={"response_text": "x" * 24001}).status_code == 422


def test_rate_exhaustion_and_store_failure(client):
    store.check_and_increment_rate.return_value = {"allowed": False, "reset_at": "2030-01-01"}
    assert client.post(PATH, headers=HEADERS, json={"response_text": "Acme is private."}).status_code == 429
    store.check_and_increment_rate.side_effect = store.StoreError("internal details")
    response = client.post(PATH, headers=HEADERS, json={"response_text": "Acme is private."})
    assert response.status_code == 503
    assert "internal details" not in response.text


def test_invalid_server_config_is_visible(client, monkeypatch):
    monkeypatch.setenv("TRUSTLAYER_CLAIM_MAX_CLAIMS", "0")
    assert client.post(PATH, headers=HEADERS, json={"response_text": "Acme is private."}).status_code == 503
