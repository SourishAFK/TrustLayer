"""Website endpoints: audience-tagged sign-ups and the capped public demo. Offline; store mocked."""

import json
import threading
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

with patch("dotenv.load_dotenv", return_value=False):
    from backend import main, store
    from backend.verification import pipeline
    from backend.verification.contracts import Providers

LEAD = {"audience": "documents", "name": "Asha Rao", "email": "asha@lawfirm.example", "company": "Rao & Co",
        "message": "Our associates use AI for first drafts.", "consent": True, "would_pay": "maybe",
        "source": {"utm_source": "linkedin", "page": "/check/?for=documents"}}


@pytest.fixture
def client(monkeypatch):
    for method in ("init_db", "close_pool"):
        monkeypatch.setattr(store, method, Mock())
    monkeypatch.setattr(store, "save_lead", Mock(return_value=7))
    monkeypatch.setattr(store, "log_usage", Mock(side_effect=AssertionError("No input persistence")))
    monkeypatch.setattr(main, "_LEADS_PER_VISITOR", main._WindowLimit(5, 3600))
    monkeypatch.setattr(main, "_LEADS_PER_DAY", main._WindowLimit(500, 86_400))
    monkeypatch.setattr(main, "_DEMO_PER_VISITOR", main._WindowLimit(5, 86_400))
    monkeypatch.setattr(main, "_DEMO_PER_DAY", main._WindowLimit(100, 86_400))
    monkeypatch.setattr(main, "_VERIFY_SLOTS", threading.BoundedSemaphore(1))
    with TestClient(main.app) as c:
        yield c


def test_a_lead_is_stored_with_its_audience_and_nothing_extra(client):
    response = client.post("/v1/leads", json=LEAD)
    assert response.status_code == 201 and response.json() == {"ok": True}
    saved, visitor = store.save_lead.call_args.args
    assert saved["audience"] == "documents" and saved["email"] == "asha@lawfirm.example"
    assert saved["would_pay"] == "maybe"
    assert "consent" not in saved and "website" not in saved and len(visitor) == 16


@pytest.mark.parametrize("change", [
    {"email": "not-an-email"}, {"email": "x@localhost"}, {"consent": False}, {"name": "   "},
    {"audience": "everyone"}, {"link": "javascript:alert(1)"}, {"source": {"cookie": "x"}}, {"extra": 1},
    {"would_pay": "definitely"},
])
def test_invalid_leads_are_rejected(client, change):
    assert client.post("/v1/leads", json={**LEAD, **change}).status_code == 422
    store.save_lead.assert_not_called()


def test_the_honeypot_looks_successful_but_stores_nothing(client):
    assert client.post("/v1/leads", json={**LEAD, "website": "http://spam.example"}).status_code == 201
    store.save_lead.assert_not_called()


def test_one_visitor_cannot_flood_the_form(client):
    codes = [client.post("/v1/leads", json=LEAD).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]


def test_a_storage_outage_is_a_retryable_error_without_details(client):
    store.save_lead.side_effect = store.StoreError("connection string with secrets")
    response = client.post("/v1/leads", json=LEAD)
    assert response.status_code == 503 and "secrets" not in response.text


def offline(run):
    return lambda request, **kw: run(request, **{**kw, "providers": Providers(), "engines": [[], [], []]})


def test_the_public_demo_is_off_unless_enabled(client, monkeypatch):
    monkeypatch.delenv("TRUSTLAYER_PUBLIC_DEMO", raising=False)
    assert client.post("/v1/demo/verify/stream", json={"response_text": "2 + 2 = 5."}).status_code == 404


def test_the_public_demo_streams_a_report_and_never_stores_it(client, monkeypatch):
    monkeypatch.setenv("TRUSTLAYER_PUBLIC_DEMO", "true")
    monkeypatch.setenv("TRUSTLAYER_REPORT_RETENTION_HOURS", "24")
    monkeypatch.setattr(store, "save_report", Mock(side_effect=AssertionError("demo reports are never stored")))
    monkeypatch.setattr(pipeline, "stream_ndjson", offline(pipeline.stream_ndjson))
    monkeypatch.setattr(pipeline, "verify", offline(pipeline.verify))
    response = client.post("/v1/demo/verify/stream", json={"response_text": "2 + 2 = 5."})
    assert response.status_code == 200 and response.headers["content-type"] == "application/x-ndjson"
    report = json.loads(response.text.splitlines()[-1])["report"]
    assert report["mode"] == "quick" and report["privacy"]["stored"] is False


def test_the_demo_checks_a_bot_against_its_policy_only(client, monkeypatch):
    monkeypatch.setenv("TRUSTLAYER_PUBLIC_DEMO", "1")
    seen = {}

    def capture(request, **kw):
        seen["request"] = request
        yield json.dumps({"type": "report", "report": {}}) + "\n"

    monkeypatch.setattr(pipeline, "stream_ndjson", capture)
    body = {"response_text": "You can get a refund within 60 days.",
            "answer_key": {"name": "Refund policy", "text": "Refunds must be requested within 30 days."}}
    assert client.post("/v1/demo/verify/stream", json=body).status_code == 200
    req = seen["request"]
    assert req.documents_role == "answer_key" and req.share_documents_with_ai and not req.allow_web_search
    assert req.mode == "quick" and req.documents[0].name == "Refund policy"


def test_the_demo_is_capped_per_visitor_and_rejects_long_text(client, monkeypatch):
    monkeypatch.setenv("TRUSTLAYER_PUBLIC_DEMO", "on")
    monkeypatch.setattr(pipeline, "stream_ndjson", lambda request, **kw: iter([json.dumps({"type": "report"}) + "\n"]))
    assert client.post("/v1/demo/verify/stream", json={"response_text": "x" * 3001}).status_code == 422
    codes = [client.post("/v1/demo/verify/stream", json={"response_text": "2 + 2 = 4."}).status_code
             for _ in range(6)]
    assert codes == [200] * 5 + [429]


def test_a_bad_daily_limit_setting_closes_the_demo(client, monkeypatch):
    monkeypatch.setenv("TRUSTLAYER_PUBLIC_DEMO", "true")
    monkeypatch.setenv("TRUSTLAYER_DEMO_DAILY_LIMIT", "lots")
    assert client.post("/v1/demo/verify/stream", json={"response_text": "2 + 2 = 4."}).status_code == 429
