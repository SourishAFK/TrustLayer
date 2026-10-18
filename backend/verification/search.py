"""Search adapters: Brave (web), Wikipedia (reference), OpenAlex (academic).

Each adapter satisfies contracts.SearchProvider and only reports what a search
returned; whether a result supports a claim is decided later, from quotes.

Safety rules:
* Constructors never touch the network. Production requests go through the
  SSRF-safe client (fetcher.safe_client); tests inject MockTransport clients.
* search() raises on HTTP errors and malformed payloads, and the caller records
  the search as "not run". Error messages name the provider and the failure
  kind only: never the API key, the query or response text.
* Queries are untrusted text: whitespace is collapsed, length is capped and
  operator prefixes (site:, insource:, ...) are neutralized, so a response
  cannot steer which sources get searched.
* Titles, snippets and content are untrusted data for the caller to quote.
"""

import html
import os
import re
import time
from datetime import datetime, timezone

import httpx

from backend.verification.contracts import SearchProvider, SearchResult

MAX_COUNT = 20
MAX_QUERY_WORDS = 50
TITLE_CHARS = 300  # report.Evidence.title limit
SNIPPET_CHARS = 200
CONTENT_CHARS = 20_000
USER_AGENT = "TrustLayerVerifier/2.0"
_TAG = re.compile(r"<[^>]*>")
# "site:x", "insource:/re/" and a dangling "site:"; "Note: ..." is prose and stays.
_OPERATOR = re.compile(r"\b[A-Za-z]+:(?!\s)")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_LANG = re.compile(r"[a-z]{2,12}(?:-[a-z]{1,12})*")


class SearchError(RuntimeError):
    """A search failed. The message names the provider and failure kind, nothing else."""


def _http(client: httpx.Client | None) -> httpx.Client:
    if client is not None:
        return client
    # Lazy: tests inject a client instead.
    from backend.verification.fetcher import safe_client

    return safe_client()


def _query(text: str, max_chars: int) -> str:
    """Untrusted text -> a plain keyword query. Raises ValueError when nothing is left."""
    # Collapse first so an operator left dangling at the end is seen as one.
    words = _OPERATOR.sub("", " ".join(text.split())).split()
    query = " ".join(words[:MAX_QUERY_WORDS])
    if len(query) > max_chars:  # cut at a word boundary
        query = query[:max_chars + 1].rsplit(" ", 1)[0][:max_chars]
    if not query:
        raise ValueError("Search query is empty.")
    return query


def _count(count: int) -> int:
    return max(1, min(count, MAX_COUNT))


def _get_json(client: httpx.Client, provider: str, url: str, params: dict, headers: dict,
              timeout: float) -> dict:
    try:
        response = client.get(url, params=params, headers=headers, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — transport errors can echo the URL, which holds the query
        raise SearchError(f"{provider}: {type(exc).__name__}") from None
    if not response.is_success:
        raise SearchError(f"{provider}: HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        raise SearchError(f"{provider}: response is not JSON") from None
    if not isinstance(data, dict):
        raise SearchError(f"{provider}: unexpected response shape")
    return data


def _plain(value: object) -> str:
    """HTML fragment -> one line of plain text ("" for non-strings)."""
    if not isinstance(value, str):
        return ""
    return " ".join(html.unescape(_TAG.sub("", value)).split())


def _snippet(text: str) -> str:
    return " ".join(text.split())[:SNIPPET_CHARS]


def _web_url(value: object) -> str | None:
    if isinstance(value, str) and value.startswith(("https://", "http://")) and len(value) <= 2048:
        return value
    return None


def _date(value: object) -> datetime | None:
    """ISO date or timestamp -> aware UTC datetime; None when missing or malformed."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


class BraveSearch:
    """Brave web search. Snippets only; pages are fetched separately (content=None)."""

    name = "brave"
    kind = "web"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None):
        if not api_key or not api_key.strip():
            raise ValueError("Brave Search needs an API key.")
        self._headers = {"Accept": "application/json", "X-Subscription-Token": api_key.strip()}
        self._client = _http(client)

    def search(self, query: str, *, count: int, timeout: float) -> list[SearchResult]:
        params = {"q": _query(query, 400), "count": _count(count), "text_decorations": "false"}
        data = _get_json(self._client, self.name, self.endpoint, params, self._headers, timeout)
        web = data.get("web", {})  # may be absent when nothing matched
        items = web.get("results", []) if isinstance(web, dict) else None
        if not isinstance(items, list):
            raise SearchError("brave: unexpected response shape")
        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title, url = _plain(item.get("title"))[:TITLE_CHARS], _web_url(item.get("url"))
            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=_plain(item.get("description")),
                                            provider=self.name, published_at=_date(item.get("page_age"))))
        return results


class WikipediaSearch:
    """Wikipedia full-text search; plain-text extracts come back as content, so no page fetch."""

    name = "wikipedia"
    kind = "reference"

    def __init__(self, contact: str, *, client: httpx.Client | None = None, lang: str = "en"):
        contact = (contact or "").strip()
        # Wikimedia's User-Agent policy requires a way to reach the operator.
        if not contact or not (contact.isascii() and contact.isprintable()):
            raise ValueError("Wikipedia search needs contact details (URL or email) in printable ASCII.")
        if not _LANG.fullmatch(lang):
            raise ValueError("Unknown Wikipedia language code.")
        self.endpoint = f"https://{lang}.wikipedia.org/w/api.php"
        self._headers = {"Accept": "application/json", "User-Agent": f"{USER_AGENT} (+{contact})"}
        self._client = _http(client)

    def search(self, query: str, *, count: int, timeout: float) -> list[SearchResult]:
        deadline = time.monotonic() + timeout  # one time budget for the search and every extract
        limit = _count(count)
        hits = self._api({"list": "search", "srsearch": _query(query, 300), "srlimit": limit},
                         timeout).get("search")
        if not isinstance(hits, list):
            raise SearchError("wikipedia: unexpected response shape")
        results = []
        for hit in hits[:limit]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break  # out of time: keep the extracts already read
            page_id = hit.get("pageid") if isinstance(hit, dict) else None
            if isinstance(page_id, int) and (result := self._page(page_id, remaining)):
                results.append(result)
        return results

    def _page(self, page_id: int, timeout: float) -> SearchResult | None:
        # TextExtracts returns a whole-article extract for one page per request.
        pages = self._api({"prop": "extracts|info|revisions", "explaintext": "1",
                           "exsectionformat": "plain", "inprop": "url", "rvprop": "timestamp",
                           "pageids": page_id}, timeout).get("pages")
        page = pages[0] if isinstance(pages, list) and pages else None
        if not isinstance(page, dict):
            raise SearchError("wikipedia: unexpected response shape")
        text, title, url = page.get("extract"), page.get("title"), _web_url(page.get("fullurl"))
        if not (isinstance(text, str) and text.strip() and isinstance(title, str) and title and url):
            return None  # missing, deleted or empty page
        revisions = page.get("revisions")
        latest = revisions[0] if isinstance(revisions, list) and revisions else None
        text = text.strip()
        return SearchResult(title=title[:TITLE_CHARS], url=url, snippet=_snippet(text), provider=self.name,
                            published_at=_date(latest.get("timestamp") if isinstance(latest, dict) else None),
                            content=text[:CONTENT_CHARS])

    def _api(self, params: dict, timeout: float) -> dict:
        data = _get_json(self._client, self.name, self.endpoint,
                         {"action": "query", "format": "json", "formatversion": "2", **params},
                         self._headers, timeout)
        if "error" in data:  # MediaWiki reports API errors with HTTP 200
            raise SearchError("wikipedia: API error")
        query = data.get("query")
        if not isinstance(query, dict):
            raise SearchError("wikipedia: unexpected response shape")
        return query


class OpenAlexSearch:
    """OpenAlex scholarly works. The abstract, when OpenAlex has one, is the content."""

    name = "openalex"
    kind = "academic"
    endpoint = "https://api.openalex.org/works"
    fields = "id,display_name,doi,publication_date,primary_location,abstract_inverted_index"

    def __init__(self, *, client: httpx.Client | None = None, mailto: str | None = None):
        mailto = (mailto or "").strip()
        # The polite pool identifies callers by email; anything else (e.g. a URL) is not sent.
        self._mailto = mailto if _EMAIL.fullmatch(mailto) else None
        self._client = _http(client)

    def search(self, query: str, *, count: int, timeout: float) -> list[SearchResult]:
        params = {"search": _query(query, 400), "per-page": _count(count), "select": self.fields}
        if self._mailto:
            params["mailto"] = self._mailto
        data = _get_json(self._client, self.name, self.endpoint, params, {"Accept": "application/json"},
                         timeout)
        works = data.get("results")
        if not isinstance(works, list):
            raise SearchError("openalex: unexpected response shape")
        results = []
        for work in works:
            if not isinstance(work, dict):
                continue
            title, url = _plain(work.get("display_name"))[:TITLE_CHARS], _work_url(work)
            if not (title and url):
                continue
            abstract = _abstract(work.get("abstract_inverted_index"))
            results.append(SearchResult(title=title, url=url, snippet=_snippet(abstract), provider=self.name,
                                        published_at=_date(work.get("publication_date")),
                                        content=abstract[:CONTENT_CHARS] or None))
        return results


def _work_url(work: dict) -> str | None:
    """DOI link first (stable), then the publisher's landing page, then the OpenAlex record."""
    doi = work.get("doi")
    if isinstance(doi, str) and doi.startswith("10."):
        doi = f"https://doi.org/{doi}"
    location = work.get("primary_location")
    landing = location.get("landing_page_url") if isinstance(location, dict) else None
    return _web_url(doi) or _web_url(landing) or _web_url(work.get("id"))


def _abstract(index: object) -> str:
    """Rebuild the text of OpenAlex's {word: [positions]} abstract index ("" when absent)."""
    if not isinstance(index, dict):
        return ""
    words = {pos: word for word, positions in index.items() if isinstance(positions, list)
             for pos in positions if isinstance(pos, int)}
    return " ".join(words[pos] for pos in sorted(words))


def _disabled(flag: str) -> bool:
    return os.getenv(flag, "").strip().lower() == "false"


def configured_search_providers(mode: str) -> list[SearchProvider]:
    """Adapters enabled by server env, ordered web, reference, academic. Cheap; no network.

    Every mode gets the same providers; the per-mode budget decides how much they are used.
    """
    providers: list[SearchProvider] = []
    if key := os.getenv("BRAVE_SEARCH_API_KEY", "").strip():
        providers.append(BraveSearch(key))
    contact = os.getenv("TRUSTLAYER_CONTACT", "").strip()
    if contact and not _disabled("TRUSTLAYER_ENABLE_WIKIPEDIA"):
        providers.append(WikipediaSearch(contact))
    if not _disabled("TRUSTLAYER_ENABLE_OPENALEX"):
        providers.append(OpenAlexSearch(mailto=contact or None))
    return providers
