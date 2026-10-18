"""Python SDK compatibility; no server or provider credentials required."""

import base64
import importlib.util
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

SDK_PATH = Path(__file__).resolve().parents[1] / "clients/python/trustlayer/__init__.py"
sdk_spec = importlib.util.spec_from_file_location("legacy_sdk_under_test", SDK_PATH)
sdk = importlib.util.module_from_spec(sdk_spec)
with patch.dict("os.environ", {"TRUSTLAYER_API_KEY": "tl_fixture_only"}):
    sdk_spec.loader.exec_module(sdk)


@pytest.fixture
def sdk_post(monkeypatch):
    post = Mock(return_value=SimpleNamespace(status_code=200, ok=True, json=lambda: {
        "verdict": "SYCOPHANTIC", "sycophancy_score": 74, "request_id": 42,
    }))
    monkeypatch.setattr(sdk.requests, "post", post)
    return post


def test_python_sdk_payload_and_result_contract(sdk_post):
    client = sdk.TrustLayer(api_key="tl_fixture", base_url="https://fixture.invalid/", timeout=12)
    result = client.score("question", "answer", domain="fintech", context="context", image=b"fixture",
                          image_mime="image/png", underlying_model="claude", user_id="fixture-user")
    assert result.verdict == "SYCOPHANTIC" and result.is_sycophantic
    assert not result.is_honest and not result.is_borderline
    assert sdk_post.call_args.args == ("https://fixture.invalid/score",)
    kwargs = sdk_post.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer tl_fixture"
    assert kwargs["timeout"] == 12
    assert kwargs["json"]["context"] == "context"
    assert kwargs["json"]["underlying_model"] == "claude"
    assert kwargs["json"]["user_id"] == "fixture-user"
    assert kwargs["json"]["attachments"][0]["data"] == base64.b64encode(b"fixture").decode()


def test_python_sdk_feedback_none_is_noop(sdk_post):
    assert sdk.TrustLayer(api_key="tl_fixture").feedback(None) is False
    sdk_post.assert_not_called()


@pytest.mark.parametrize("fails", [False, True])
def test_python_sdk_background_audit_callback_is_preserved(monkeypatch, fails):
    client = sdk.TrustLayer(api_key="tl_fixture")
    result = sdk.ScoreResult(verdict="HONEST", sycophancy_score=0)
    monkeypatch.setattr(client, "score", Mock(
        return_value=result, side_effect=sdk.TrustLayerError("fixture outage") if fails else None,
    ))
    completed = threading.Event()
    observed = []

    def callback(value):
        observed.append(value)
        completed.set()

    assert client.audit("question", "answer", callback=callback) is None
    assert completed.wait(2), "Background audit did not complete"
    assert observed == [None if fails else result]


@pytest.mark.parametrize("status,error", [(401, sdk.AuthError), (429, sdk.RateLimitError), (503, sdk.TrustLayerError)])
def test_python_sdk_error_contract(sdk_post, status, error):
    sdk_post.return_value = SimpleNamespace(status_code=status, ok=False, text="fixture error", json=lambda: {
        "detail": "fixture error", "message": "daily limit", "reset_at": "2030-01-01T00:00:00Z",
    })
    with pytest.raises(error) as caught:
        sdk.TrustLayer(api_key="tl_fixture").score("question", "answer")
    if status == 429:
        assert caught.value.reset_at == "2030-01-01T00:00:00Z"
