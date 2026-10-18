"""Level 5: opt-in report retention, owner-scoped access/deletion, audit log lines."""

import json
import logging
import threading
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

with patch("dotenv.load_dotenv", return_value=False):
    from backend import main, store
    from backend.verification import pipeline
    from backend.verification.contracts import Providers

HEADERS = {"Authorization": "Bearer tl_fixture"}
TEXT = "Zorblax Labs was founded in 2019. Zorblax Labs has 40 employees."
REPORT_ID = "1b4e28ba-2fa1-41d2-883f-0016d3cca427"


def offline(run):
    return lambda request, **kw: run(request, **{**kw, "providers": Providers(), "engines": [[], [], []]})


@pytest.fixture
def client(monkeypatch):
    record = {"key": "tl_fixture", "daily_limit": 10}
    monkeypatch.setattr(store, "validate_key", lambda key: record if key == "tl_fixture" else None)
    monkeypatch.setattr(store, "check_and_increment_rate", Mock(return_value={"allowed": True}))
    for name in ("init_db", "close_pool", "save_report"):
        monkeypatch.setattr(store, name, Mock())
    monkeypatch.setattr(store, "get_report", Mock(return_value=None))
    monkeypatch.setattr(store, "delete_report", Mock(return_value=False))
    monkeypatch.setattr(store, "log_usage", Mock(side_effect=AssertionError("No input persistence")))
    monkeypatch.setattr(pipeline, "stream_ndjson", offline(pipeline.stream_ndjson))
    monkeypatch.setattr(pipeline, "verify", offline(pipeline.verify))
    monkeypatch.setattr(main, "_VERIFY_SLOTS", threading.BoundedSemaphore(2))
    with TestClient(main.app) as c:
        yield c


def test_reports_are_not_stored_by_default(client):
    lines = []
    handler = logging.Handler()
    handler.emit = lambda record: lines.append(record.getMessage())
    main.audit_log.addHandler(handler)
    try:
        report = client.post("/v1/verify", headers=HEADERS, json={"response_text": TEXT}).json()
    finally:
        main.audit_log.removeHandler(handler)
    assert report["privacy"]["stored"] is False and report["privacy"]["retention_hours"] == 0
    store.save_report.assert_not_called()
    audit = [json.loads(line) for line in lines]
    assert audit[-1]["report_id"] == report["report_id"] and audit[-1]["claims"] == 2
    assert "Zorblax" not in json.dumps(audit) and "tl_fixture" not in json.dumps(audit)


def test_retention_stores_owner_scoped_and_says_so(client, monkeypatch):
    monkeypatch.setenv("TRUSTLAYER_REPORT_RETENTION_HOURS", "24")
    report = client.post("/v1/verify", headers=HEADERS, json={"response_text": TEXT}).json()
    assert report["privacy"]["stored"] is True and report["privacy"]["retention_hours"] == 24
    assert f"DELETE /v1/reports/{report['report_id']}" in report["privacy"]["note"]
    report_id, owner, body, hours = store.save_report.call_args.args
    assert (report_id, owner, hours) == (report["report_id"], "tl_fixture", 24)
    assert json.loads(body)["privacy"]["stored"] is True


def test_storage_failure_never_loses_the_report(client, monkeypatch):
    monkeypatch.setenv("TRUSTLAYER_REPORT_RETENTION_HOURS", "24")
    store.save_report.side_effect = store.StoreError("db down")
    response = client.post("/v1/verify", headers=HEADERS, json={"response_text": TEXT})
    assert response.status_code == 200
    assert response.json()["privacy"]["stored"] is False
    assert "Storage failed" in response.json()["privacy"]["note"]


def test_stream_reports_are_finalized_too(client, monkeypatch):
    monkeypatch.setenv("TRUSTLAYER_REPORT_RETENTION_HOURS", "6")
    lines = client.post("/v1/verify/stream", headers=HEADERS, json={"response_text": TEXT}).text.splitlines()
    final = json.loads(lines[-1])
    assert final["type"] == "report" and final["report"]["privacy"]["stored"] is True
    store.save_report.assert_called_once()


def test_get_report_is_owner_scoped(client):
    assert client.get(f"/v1/reports/{REPORT_ID}", headers=HEADERS).status_code == 404
    store.get_report.assert_called_once_with(REPORT_ID, "tl_fixture")
    assert client.get(f"/v1/reports/{REPORT_ID}").status_code == 401
    assert client.get("/v1/reports/../../etc", headers=HEADERS).status_code == 404
    assert client.get("/v1/reports/not-a-uuid", headers=HEADERS).status_code == 422


def test_get_report_round_trip_and_outage(client):
    report = client.post("/v1/verify", headers=HEADERS, json={"response_text": TEXT}).json()
    store.get_report.return_value = report
    fetched = client.get(f"/v1/reports/{report['report_id']}", headers=HEADERS)
    assert fetched.status_code == 200 and fetched.json()["report_id"] == report["report_id"]
    store.get_report.side_effect = store.StoreError("internal detail")
    outage = client.get(f"/v1/reports/{REPORT_ID}", headers=HEADERS)
    assert outage.status_code == 503 and "internal detail" not in outage.text


def test_delete_report(client):
    assert client.delete(f"/v1/reports/{REPORT_ID}", headers=HEADERS).status_code == 404
    store.delete_report.return_value = True
    assert client.delete(f"/v1/reports/{REPORT_ID}", headers=HEADERS).json() == {
        "deleted": True, "report_id": REPORT_ID}
    store.delete_report.assert_called_with(REPORT_ID, "tl_fixture")


def test_owner_hash_is_stable_and_not_the_key():
    assert store.owner_hash("tl_abc") == store.owner_hash("tl_abc")
    assert "tl_abc" not in store.owner_hash("tl_abc") and len(store.owner_hash("tl_abc")) == 64
