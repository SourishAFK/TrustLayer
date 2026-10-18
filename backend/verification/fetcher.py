"""SSRF-safe page fetching for evidence and citation checks.

Every URL TrustLayer reads comes from untrusted input (AI responses, users,
search results), so each one is treated as hostile:

* only http/https, ports 80/443 by default, no credentials in URLs, no
  internal-looking or single-label host names;
* the host is resolved and EVERY address must be public; the TCP connection is
  then pinned to that validated address by a custom httpcore network backend,
  so a DNS answer that changes between the check and the connect (rebinding)
  cannot steer the request inward — TLS still verifies the real host name;
* redirects are followed by hand and every hop is validated again;
* environment proxies are ignored; bodies are streamed with a byte cap and a
  content-type allowlist; only GET is ever sent;
* robots.txt is honored (RFC 9309: 4xx allows, 5xx or unreachable disallows).

fetch() never raises: failures come back as FetchedPage(ok=False, error=code).
"""

import ipaddress
import json
import logging
import os
import re
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import certifi
import httpcore
import httpx

from backend.verification.contracts import FetchedPage

logger = logging.getLogger(__name__)
AGENT_TOKEN = "TrustLayerVerifier"
ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/json")
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
REDIRECTS = {301, 302, 303, 307, 308}
ROBOTS_MAX_BYTES = 512_000
_BLOCKED = "TrustLayer refused a non-public address"
_HOSTNAME = re.compile(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

def user_agent() -> str:
    """Identifying agent; Wikimedia and polite crawling expect a contact."""
    contact = os.getenv("TRUSTLAYER_CONTACT", "").strip()
    if contact and contact.isascii() and contact.isprintable():
        return f"{AGENT_TOKEN}/2.0 (+{contact})"
    return f"{AGENT_TOKEN}/2.0"


def respects_robots() -> bool:
    return os.getenv("TRUSTLAYER_RESPECT_ROBOTS", "true").strip().lower() not in ("0", "false", "no", "off")


def allowed_ports() -> tuple[int, ...]:
    raw = os.getenv("TRUSTLAYER_FETCH_ALLOWED_PORTS", "80,443")
    try:
        ports = tuple(int(p) for p in raw.split(",") if p.strip())
    except ValueError:
        raise ValueError("TRUSTLAYER_FETCH_ALLOWED_PORTS must list port numbers.") from None
    if not ports or any(not 1 <= p <= 65535 for p in ports):
        raise ValueError("TRUSTLAYER_FETCH_ALLOWED_PORTS must list ports between 1 and 65535.")
    return ports


# --------------------------------------------------------------------------- #
# Address checks and the pinned transport
# --------------------------------------------------------------------------- #

def is_public_ip(value: str) -> bool:
    """True only for globally routable unicast addresses (embedded IPv4 included)."""
    try:
        ip = ipaddress.ip_address(value.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = [ip.ipv4_mapped, ip.sixtofour, ip.teredo[1] if ip.teredo else None]
        if ip in _NAT64:
            embedded.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
        if any(e is not None and not is_public_ip(str(e)) for e in embedded):
            return False
    return bool(ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_loopback
                                      or ip.is_link_local or ip.is_unspecified or ip.is_private
                                      or getattr(ip, "is_site_local", False)))


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]").split("%")[0])
        return True
    except ValueError:
        return False


def _system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


class _PinnedBackend(httpcore.NetworkBackend):
    """Resolves and validates at connect time, then connects to the IP itself.

    httpcore passes the original host name here and again as the TLS
    server_hostname, so certificates are still checked against the real host.
    """

    def __init__(self, resolver):
        self._resolver = resolver
        self._inner = httpcore.SyncBackend()

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            addresses = [host.strip("[]")] if _is_ip_literal(host) else self._resolver(host, port)
        except (OSError, UnicodeError):
            raise httpcore.ConnectError("name resolution failed") from None
        if not addresses or not all(is_public_ip(a) for a in addresses):
            raise httpcore.ConnectError(_BLOCKED)
        return self._inner.connect_tcp(addresses[0], port, timeout=timeout,
                                       local_address=local_address, socket_options=socket_options)

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError(_BLOCKED)

    def sleep(self, seconds):
        self._inner.sleep(seconds)


class _PinnedTransport(httpx.HTTPTransport):
    def __init__(self, resolver):
        super().__init__(trust_env=False)
        # ponytail: swaps httpx's private _pool to inject the network backend;
        # re-run tests/test_fetcher.py on every httpx/httpcore upgrade.
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(cafile=certifi.where()),
            network_backend=_PinnedBackend(resolver), max_connections=20)


def safe_client(*, timeout: float = 10.0) -> httpx.Client:
    """An httpx client for JSON APIs with the same address pinning as SafeFetcher."""
    return httpx.Client(transport=_PinnedTransport(_system_resolver), trust_env=False,
                        follow_redirects=False, timeout=timeout,
                        headers={"User-Agent": user_agent()})


# --------------------------------------------------------------------------- #
# Fetcher
# --------------------------------------------------------------------------- #

def _failed(url: str, final_url: str, error: str, now: datetime, status: int | None = None) -> FetchedPage:
    return FetchedPage(url=url, final_url=final_url, ok=False, status=status, error=error,
                       content_type=None, title=None, publisher=None, published_at=None,
                       text="", fetched_at=now)


class SafeFetcher:
    def __init__(self, *, agent: str | None = None, max_bytes: int = 2_000_000, max_redirects: int = 4,
                 ports: tuple[int, ...] | None = None, respect_robots: bool | None = None,
                 resolver=None, transport: httpx.BaseTransport | None = None):
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.ports = tuple(ports) if ports else allowed_ports()
        self.respect_robots = respects_robots() if respect_robots is None else respect_robots
        self.resolver = resolver or _system_resolver
        self.client = httpx.Client(
            transport=transport or _PinnedTransport(self.resolver), trust_env=False,
            follow_redirects=False,
            headers={"User-Agent": agent or user_agent(),
                     "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,application/json;q=0.8",
                     "Accept-Language": "en;q=1.0, *;q=0.5"})
        self._robots: dict[str, object] = {}
        self._lock = threading.Lock()

    def fetch(self, url: str, *, timeout: float) -> FetchedPage:
        now = datetime.now(timezone.utc)
        try:
            return self._fetch(url, max(0.1, timeout), now)
        except Exception as exc:  # noqa: BLE001 — the contract is "never raise"
            logger.warning("Fetch failed (%s)", type(exc).__name__)
            return _failed(url, url, "network_error", now)

    # -- steps ---------------------------------------------------------------- #

    def _fetch(self, url: str, timeout: float, now: datetime) -> FetchedPage:
        deadline = time.monotonic() + timeout
        current = url.strip()
        for _hop in range(self.max_redirects + 1):
            error = self._check(current)
            if error:
                return _failed(url, current, error, now)
            if self.respect_robots and not self._robots_allow(current, deadline):
                return _failed(url, current, "robots_disallowed", now)
            outcome = self._get(current, deadline, self.max_bytes, any_type=False)
            if isinstance(outcome, str):
                return _failed(url, current, outcome, now)
            status, headers, body, content_type = outcome
            if status in REDIRECTS:
                location = headers.get("location")
                if not location:
                    return _failed(url, current, "http_error", now, status)
                current = urljoin(current, location)
                continue
            if status >= 400:
                return _failed(url, current, "http_error", now, status)
            text = _decode(body, headers.get("content-type", ""))
            title = publisher = published = None
            if content_type in ("text/html", "application/xhtml+xml"):
                title, publisher, published, text = html_to_text(text)
            return FetchedPage(url=url, final_url=current, ok=True, status=status, error=None,
                               content_type=content_type, title=title, publisher=publisher,
                               published_at=published, text=text, fetched_at=now)
        return _failed(url, current, "redirect_limit", now)

    def _check(self, url: str) -> str | None:
        """Error code when the URL may not be fetched, else None (resolves the host)."""
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return "invalid_url"
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return "invalid_url"
        if parts.username is not None or parts.password is not None or "@" in parts.netloc:
            return "invalid_url"
        port = port or (443 if parts.scheme.lower() == "https" else 80)
        if port not in self.ports:
            return "blocked_port"
        host = parts.hostname
        if _is_ip_literal(host):
            return None if is_public_ip(host) else "blocked_address"
        try:
            host = host.encode("idna").decode("ascii").rstrip(".")
        except UnicodeError:
            return "invalid_url"
        if not _HOSTNAME.fullmatch(host):
            return "invalid_url"
        if host == "localhost" or host.endswith(BLOCKED_SUFFIXES) or "." not in host:
            return "blocked_address"
        try:
            addresses = self.resolver(host, port)
        except (OSError, UnicodeError):
            return "dns_failure"
        if not addresses:
            return "dns_failure"
        return None if all(is_public_ip(a) for a in addresses) else "blocked_address"

    def _get(self, url: str, deadline: float, max_bytes: int, *, any_type: bool):
        """(status, headers, body, content_type) or an error code string."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timeout"
        try:
            with self.client.stream("GET", url, timeout=httpx.Timeout(remaining, connect=min(5.0, remaining))) as resp:
                content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if resp.status_code in REDIRECTS or resp.status_code >= 400:
                    return resp.status_code, resp.headers, b"", content_type
                if not any_type and content_type not in ALLOWED_TYPES:
                    return "unsupported_content_type"
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        if any_type:  # robots.txt: parse what fits (RFC 9309 allows a size cap)
                            break
                        return "too_large"
                    if time.monotonic() > deadline:
                        return "timeout"
                    chunks.append(chunk)
                return resp.status_code, resp.headers, b"".join(chunks), content_type
        except httpx.TimeoutException:
            return "timeout"
        except httpx.ConnectError as exc:
            return "blocked_address" if _BLOCKED in str(exc) else "network_error"
        except httpx.HTTPError:
            return "network_error"

    def _robots_allow(self, url: str, deadline: float) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme.lower()}://{parts.netloc.lower()}"
        with self._lock:
            rules = self._robots.get(origin)
        if rules is None:
            rules = self._load_robots(origin, deadline)
            with self._lock:
                self._robots[origin] = rules
        if isinstance(rules, bool):
            return rules
        return rules.can_fetch(AGENT_TOKEN, url)

    def _load_robots(self, origin: str, deadline: float):
        target = origin + "/robots.txt"
        for _ in range(5):
            if self._check(target):
                return False
            outcome = self._get(target, deadline, ROBOTS_MAX_BYTES, any_type=True)
            if isinstance(outcome, str):
                return False  # unreachable: assume complete disallow
            status, headers, body, _ = outcome
            if status in REDIRECTS:
                target = urljoin(target, headers.get("location", ""))
                continue
            if 400 <= status < 500:
                return True  # unavailable: crawling allowed
            if status >= 500:
                return False
            parser = RobotFileParser()
            parser.parse(body.decode("utf-8", "replace").splitlines())
            return parser
        return True  # more than five redirects: treat as unavailable


def _decode(body: bytes, content_type_header: str) -> str:
    match = re.search(r"charset=([\w.:-]+)", content_type_header, re.I)
    try:
        return body.decode(match.group(1) if match else "utf-8", errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# HTML to text
# --------------------------------------------------------------------------- #

_SKIP = {"script", "style", "noscript", "template", "svg", "head", "iframe", "object", "canvas"}
_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th",
          "section", "article", "header", "footer", "nav", "aside", "blockquote", "pre", "table",
          "main", "figure", "figcaption", "dd", "dt", "hr"}
_DATE_META = ("article:published_time", "og:published_time", "date", "pubdate", "dc.date",
              "dc.date.issued", "citation_publication_date", "citation_date", "publish-date",
              "publication_date")


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: list[str] = []
        self.meta: dict[str, str] = {}
        self.time: str | None = None
        self.jsonld: list[str] = []
        self.skip = 0
        self.in_title = False
        self.in_jsonld = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "body":
            self.skip = 0  # an unclosed <head> must not swallow the page
        elif tag == "title":
            self.in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])
        elif tag == "time" and self.time is None and a.get("datetime"):
            self.time = a["datetime"]
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self.in_jsonld = True
        if tag in _SKIP:
            self.skip += 1
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "script":
            self.in_jsonld = False
        if tag in _SKIP and self.skip:
            self.skip -= 1
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        if self.in_jsonld and sum(map(len, self.jsonld)) < 200_000:
            self.jsonld.append(data)
        if not self.skip:
            self.parts.append(data)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip().replace("/", "-")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:  # e.g. "2024-05-01 at 10am": keep the date part
            parsed = datetime.fromisoformat(value[:10])
        except ValueError:
            return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _jsonld_date(blobs: list[str]) -> str | None:
    for blob in blobs:
        match = re.search(r'"datePublished"\s*:\s*"([^"]{4,40})"', blob)
        if match:
            return match.group(1)
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("datePublished"), str):
            return data["datePublished"]
    return None


_TAG = re.compile(r"<[/!?]?[A-Za-z][^<>]{0,1000}>")


def _defuse(html: str) -> str:
    """Linear pre-pass so html.parser only sees well-formed tags.

    html.parser re-scans incomplete markup from the start of every construct, which is
    quadratic: 21 KB of "<a " took 20 s. Comments are dropped (an unterminated one hides the
    rest, as in browsers), bounded well-formed tags are kept, any other "<" becomes "&lt;".
    Every character is scanned a bounded number of times. ponytail: a ">" inside an attribute
    value ends the tag early; the text survives, only that attribute is cut.
    """
    out: list[str] = []
    i = 0
    while (j := html.find("<", i)) >= 0:
        out.append(html[i:j])
        if html.startswith("<!--", j):
            end = html.find("-->", j + 4)
            if end < 0:
                return "".join(out)
            i = end + 3
        elif m := _TAG.match(html, j):
            out.append(m.group(0))
            i = m.end()
        else:
            out.append("&lt;")
            i = j + 1
    out.append(html[i:])
    return "".join(out)


def html_to_text(html: str) -> tuple[str | None, str | None, datetime | None, str]:
    """(title, publisher, published_at, visible text) using only the standard library."""
    parser = _Extractor()
    try:
        parser.feed(_defuse(html))
        parser.close()
    except Exception as exc:  # noqa: BLE001 — keep whatever parsed before the error
        logger.debug("HTML parse stopped early (%s)", type(exc).__name__)
    lines = (re.sub(r"[ \t\r\f\v ]+", " ", line).strip() for line in "".join(parser.parts).split("\n"))
    text = "\n".join(line for line in lines if line)
    title = " ".join("".join(parser.title).split()) or parser.meta.get("og:title") or None
    publisher = parser.meta.get("og:site_name") or parser.meta.get("application-name") or None
    raw_date = next((parser.meta[k] for k in _DATE_META if k in parser.meta), None) or parser.time \
        or _jsonld_date(parser.jsonld)
    return (title[:300] if title else None, publisher[:200] if publisher else None,
            _parse_date(raw_date), text)
