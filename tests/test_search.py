"""Search adapters: request shape, parsing and failure handling. Offline (httpx.MockTransport)."""

import sys
import types
from datetime import datetime, timezone

import httpx
import pytest

from backend.verification.search import (
    BraveSearch,
    OpenAlexSearch,
    SearchError,
    WikipediaSearch,
    configured_search_providers,
)

KEY = "brv-secret-key-123"
QUERY = "Acme Corp was founded in 2015"
SELECT = "id,display_name,doi,publication_date,primary_location,abstract_inverted_index"
ENV = ("BRAVE_SEARCH_API_KEY", "TRUSTLAYER_CONTACT", "TRUSTLAYER_ENABLE_WIKIPEDIA",
       "TRUSTLAYER_ENABLE_OPENALEX")


def recorder(*responses):
    """A client answering with `responses` in order; returns (client, requests seen)."""
    seen, queue = [], list(responses)

    def handler(request):
        seen.append(request)
        return queue.pop(0)
    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def brave(*responses):
    http, seen = recorder(*responses)
    return BraveSearch(KEY, client=http), seen


# --------------------------------------------------------------------------- #
# Brave
# --------------------------------------------------------------------------- #

def test_brave_request_shape_and_parsing():
    provider, seen = brave(httpx.Response(200, json={"web": {"results": [
        {"title": "Acme &amp; Co", "url": "https://acme.example.com/about",
         "description": "Acme <strong>was founded</strong> in 2015 &mdash; per\n records.",
         "page_age": "2025-03-01T10:00:00"},
        {"title": "No link"},
        {"title": "Script", "url": "javascript:alert(1)"},
        "not an object",
        {"title": "Undated", "url": "http://b.example.org/x", "page_age": "last week"},
    ]}}))
    results = provider.search(QUERY, count=50, timeout=5)
    request = seen[0]
    assert (request.url.host, request.url.path) == ("api.search.brave.com", "/res/v1/web/search")
    assert dict(request.url.params) == {"q": QUERY, "count": "20", "text_decorations": "false"}
    assert request.headers["X-Subscription-Token"] == KEY
    assert request.headers["Accept"] == "application/json"
    assert [r.url for r in results] == ["https://acme.example.com/about", "http://b.example.org/x"]
    first = results[0]
    assert first.title == "Acme & Co" and first.snippet == "Acme was founded in 2015 — per records."
    assert first.published_at == datetime(2025, 3, 1, 10, tzinfo=timezone.utc)
    assert first.content is None and first.provider == "brave"
    assert results[1].published_at is None


def test_brave_without_web_section_found_nothing():
    provider, _ = brave(httpx.Response(200, json={"type": "search", "query": {"original": QUERY}}))
    assert provider.search(QUERY, count=3, timeout=5) == []


@pytest.mark.parametrize("status", [401, 422, 429, 500, 302])
def test_brave_http_errors_raise_without_key_or_query(status):
    provider, _ = brave(httpx.Response(status, json={"error": f"bad token {KEY} for {QUERY}"}))
    with pytest.raises(SearchError) as err:
        provider.search(QUERY, count=3, timeout=5)
    assert str(err.value) == f"brave: HTTP {status}"


@pytest.mark.parametrize("body", [b"<html>busy</html>", b"[1, 2]", b'{"web": {"results": {}}}',
                                  b'{"web": "none"}'])
def test_brave_malformed_payloads_raise(body):
    provider, _ = brave(httpx.Response(200, content=body, headers={"content-type": "application/json"}))
    with pytest.raises(SearchError, match="^brave: "):
        provider.search(QUERY, count=3, timeout=5)


def test_transport_errors_never_echo_the_query_or_key():
    def handler(request):
        raise httpx.ConnectError(f"cannot reach {request.url} with {KEY}")
    provider = BraveSearch(KEY, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(SearchError) as err:
        provider.search(QUERY, count=3, timeout=5)
    assert str(err.value) == "brave: ConnectError"
    assert err.value.__cause__ is None and err.value.__suppress_context__


def test_queries_become_plain_keywords_with_capped_length():
    provider, seen = brave(*[httpx.Response(200, json={"web": {"results": []}})] * 3)
    provider.search("  site:evil.example  Acme\n\tfounded insource:/a.*b/ in 10:30 ", count=3, timeout=5)
    assert seen[0].url.params["q"] == "evil.example Acme founded /a.*b/ in 10:30"
    provider.search(" ".join(["abcdefghij"] * 45), count=3, timeout=5)
    assert seen[1].url.params["q"] == " ".join(["abcdefghij"] * 36)  # <= 400 chars, whole words
    provider.search("Note: Acme was founded in 2015 site:\n", count=3, timeout=5)
    assert seen[2].url.params["q"] == "Note: Acme was founded in 2015"  # prose stays, a dangling operator goes
    with pytest.raises(ValueError):
        provider.search(" \n site: ", count=3, timeout=5)
    assert len(seen) == 3


def test_brave_needs_a_key():
    with pytest.raises(ValueError):
        BraveSearch("  ", client=recorder()[0])


# --------------------------------------------------------------------------- #
# Wikipedia
# --------------------------------------------------------------------------- #

BASE = {"action": "query", "format": "json", "formatversion": "2"}


def page_params(page_id):
    return {**BASE, "prop": "extracts|info|revisions", "explaintext": "1", "exsectionformat": "plain",
            "inprop": "url", "rvprop": "timestamp", "pageids": page_id}


def test_wikipedia_sends_contact_user_agent_and_reads_one_extract_per_page():
    long_text = "Acme   Corp is a company.\n" + "x" * 30_000
    http, seen = recorder(
        httpx.Response(200, json={"batchcomplete": True, "query": {"search": [
            {"pageid": 11, "title": "Acme Corp"}, {"pageid": 22, "title": "Gone"}, {"title": "No id"}]}}),
        httpx.Response(200, json={"query": {"pages": [{
            "pageid": 11, "title": "Acme Corp", "extract": long_text,
            "fullurl": "https://en.wikipedia.org/wiki/Acme_Corp",
            "revisions": [{"timestamp": "2026-05-01T12:30:00Z"}]}]}}),
        httpx.Response(200, json={"query": {"pages": [{"pageid": 22, "missing": True}]}}))
    results = WikipediaSearch("ops@example.com", client=http).search(QUERY, count=3, timeout=10)
    assert {r.headers["User-Agent"] for r in seen} == {"TrustLayerVerifier/2.0 (+ops@example.com)"}
    assert {(r.url.host, r.url.path) for r in seen} == {("en.wikipedia.org", "/w/api.php")}
    assert dict(seen[0].url.params) == {**BASE, "list": "search", "srsearch": QUERY, "srlimit": "3"}
    assert [dict(r.url.params) for r in seen[1:]] == [page_params("11"), page_params("22")]
    [result] = results
    assert result.title == "Acme Corp" and result.url == "https://en.wikipedia.org/wiki/Acme_Corp"
    assert result.snippet == ("Acme Corp is a company. " + "x" * 200)[:200]
    assert result.published_at == datetime(2026, 5, 1, 12, 30, tzinfo=timezone.utc)
    assert result.content == long_text[:20_000] and result.provider == "wikipedia"


@pytest.mark.parametrize("contact", ["", "   ", "ops@example.com\r\nX-Injected: 1", "kontakt@exämple.de"])
def test_wikipedia_requires_printable_contact_details(contact):
    with pytest.raises(ValueError):
        WikipediaSearch(contact, client=recorder()[0])


def test_wikipedia_language_must_be_a_language_code():
    with pytest.raises(ValueError):
        WikipediaSearch("ops@example.com", client=recorder()[0], lang="evil.example/#")
    assert WikipediaSearch("ops@example.com", client=recorder()[0], lang="zh-yue").endpoint == \
        "https://zh-yue.wikipedia.org/w/api.php"


@pytest.mark.parametrize("payload", [
    {"error": {"code": "srsearch-text-too-long", "info": f"Search request too long: {QUERY}"}},
    {"batchcomplete": True},
    {"query": {"search": "nope"}},
])
def test_wikipedia_api_errors_and_malformed_payloads_raise(payload):
    http, _ = recorder(httpx.Response(200, json=payload))
    with pytest.raises(SearchError) as err:
        WikipediaSearch("ops@example.com", client=http).search(QUERY, count=2, timeout=10)
    assert str(err.value).startswith("wikipedia: ") and QUERY not in str(err.value)


def test_wikipedia_page_errors_fail_the_search():
    http, _ = recorder(httpx.Response(200, json={"query": {"search": [{"pageid": 11}]}}),
                       httpx.Response(503))
    with pytest.raises(SearchError, match="^wikipedia: HTTP 503$"):
        WikipediaSearch("ops@example.com", client=http).search(QUERY, count=2, timeout=10)


def test_wikipedia_stops_reading_extracts_when_time_is_up():
    http, seen = recorder(httpx.Response(200, json={"query": {"search": [{"pageid": 11}, {"pageid": 12}]}}))
    assert WikipediaSearch("ops@example.com", client=http).search(QUERY, count=2, timeout=0) == []
    assert len(seen) == 1


# --------------------------------------------------------------------------- #
# OpenAlex
# --------------------------------------------------------------------------- #

def test_openalex_request_shape_links_and_abstracts():
    http, seen = recorder(httpx.Response(200, json={"meta": {"count": 5}, "results": [
        {"id": "https://openalex.org/W1", "display_name": "Effects of CO<sub>2</sub> on growth",
         "doi": "https://doi.org/10.1000/xyz", "publication_date": "2023-04-15",
         "primary_location": {"landing_page_url": "https://journal.example.org/a/1"},
         "abstract_inverted_index": {"founded": [2], "Acme": [0], "was": [1, 5], "in": [3], "2015,": [4]}},
        {"id": "https://openalex.org/W2", "display_name": "Landing page only", "doi": None,
         "primary_location": {"landing_page_url": "https://journal.example.org/a/2"},
         "abstract_inverted_index": None},
        {"id": "https://openalex.org/W3", "display_name": "Bare DOI", "doi": "10.1000/abc"},
        {"id": "https://openalex.org/W4", "display_name": "Record only", "primary_location": None},
        {"id": "not-a-url", "display_name": "No usable link"},
        {"id": "https://openalex.org/W6", "display_name": None},
    ]}))
    results = OpenAlexSearch(client=http, mailto="ops@example.com").search(QUERY, count=6, timeout=10)
    request = seen[0]
    assert (request.url.host, request.url.path) == ("api.openalex.org", "/works")
    assert dict(request.url.params) == {"search": QUERY, "per-page": "6", "select": SELECT,
                                        "mailto": "ops@example.com"}
    assert [r.url for r in results] == ["https://doi.org/10.1000/xyz", "https://journal.example.org/a/2",
                                        "https://doi.org/10.1000/abc", "https://openalex.org/W4"]
    first = results[0]
    assert first.title == "Effects of CO2 on growth" and first.provider == "openalex"
    assert first.content == "Acme was founded in 2015, was" and first.snippet == first.content
    assert first.published_at == datetime(2023, 4, 15, tzinfo=timezone.utc)
    assert results[1].content is None and results[1].snippet == "" and results[1].published_at is None


@pytest.mark.parametrize("mailto", [None, "", "https://example.com/contact", "not an email"])
def test_openalex_sends_mailto_only_for_an_email(mailto):
    http, seen = recorder(httpx.Response(200, json={"results": []}))
    assert OpenAlexSearch(client=http, mailto=mailto).search(QUERY, count=2, timeout=10) == []
    assert "mailto" not in seen[0].url.params


@pytest.mark.parametrize("payload", [{"error": "Invalid query"}, {"results": None}])
def test_openalex_malformed_payloads_raise(payload):
    http, _ = recorder(httpx.Response(200, json=payload))
    with pytest.raises(SearchError, match="^openalex: unexpected response shape$"):
        OpenAlexSearch(client=http).search(QUERY, count=2, timeout=10)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

@pytest.fixture
def safe_requests(monkeypatch):
    """Stand in for fetcher.safe_client and clear search env; returns the requests made."""
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"results": []})

    def safe_client(*, timeout=10.0):
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)

    fetcher = types.ModuleType("backend.verification.fetcher")
    fetcher.safe_client = safe_client
    monkeypatch.setitem(sys.modules, "backend.verification.fetcher", fetcher)
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    return seen


@pytest.mark.parametrize("env,expected", [
    ({}, [("openalex", "academic")]),
    ({"BRAVE_SEARCH_API_KEY": KEY, "TRUSTLAYER_CONTACT": "ops@example.com"},
     [("brave", "web"), ("wikipedia", "reference"), ("openalex", "academic")]),
    ({"TRUSTLAYER_CONTACT": "ops@example.com", "TRUSTLAYER_ENABLE_WIKIPEDIA": "false"},
     [("openalex", "academic")]),
    ({"BRAVE_SEARCH_API_KEY": KEY, "TRUSTLAYER_ENABLE_OPENALEX": "FALSE"}, [("brave", "web")]),
    ({"BRAVE_SEARCH_API_KEY": "  ", "TRUSTLAYER_ENABLE_OPENALEX": "false"}, []),
])
def test_configured_search_providers_follow_env(safe_requests, monkeypatch, env, expected):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert [(p.name, p.kind) for p in configured_search_providers("quick")] == expected
    assert safe_requests == []  # building providers never touches the network


@pytest.mark.parametrize("contact,mailto", [("ops@example.com", "ops@example.com"),
                                            ("https://example.com/contact", None)])
def test_openalex_mailto_comes_from_the_contact(safe_requests, monkeypatch, contact, mailto):
    monkeypatch.setenv("TRUSTLAYER_CONTACT", contact)
    openalex = configured_search_providers("deep")[-1]
    assert openalex.name == "openalex" and openalex.search(QUERY, count=1, timeout=5) == []
    assert safe_requests[-1].url.params.get("mailto") == mailto
