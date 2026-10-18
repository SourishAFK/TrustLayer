"""SSRF-safe fetcher: every hostile URL shape is refused before any connection. Offline."""

from datetime import timezone

import httpcore
import httpx
import pytest

from backend.verification.fetcher import (
    SafeFetcher,
    _PinnedBackend,
    allowed_ports,
    html_to_text,
    is_public_ip,
    respects_robots,
    safe_client,
    user_agent,
)

PUBLIC = "93.184.216.34"


def public(host, port):
    return [PUBLIC]


def fetcher(handler, resolver=public, **kw):
    kw.setdefault("respect_robots", False)
    return SafeFetcher(transport=httpx.MockTransport(handler), resolver=resolver, ports=(80, 443), **kw)


def html(body, status=200, ctype="text/html; charset=utf-8", headers=None):
    return httpx.Response(status, headers={"content-type": ctype, **(headers or {})}, content=body)


@pytest.mark.parametrize("ip,expected", [
    (PUBLIC, True), ("8.8.8.8", True), ("2606:4700:4700::1111", True),
    ("127.0.0.1", False), ("10.1.2.3", False), ("172.16.0.1", False), ("192.168.1.1", False),
    ("169.254.169.254", False), ("100.64.0.1", False), ("0.0.0.0", False), ("224.0.0.1", False),
    ("198.18.0.1", False), ("240.0.0.1", False), ("::1", False), ("fc00::1", False), ("fe80::1", False),
    ("::ffff:127.0.0.1", False), ("::ffff:10.0.0.1", False), ("2002:7f00:1::", False),
    ("64:ff9b::a00:1", False), ("not-an-ip", False),
])
def test_is_public_ip(ip, expected):
    assert is_public_ip(ip) is expected


def never(request):
    raise AssertionError("no request may be sent")


@pytest.mark.parametrize("url,error", [
    ("file:///etc/passwd", "invalid_url"), ("ftp://example.com/x", "invalid_url"),
    ("gopher://example.com/", "invalid_url"), ("javascript:alert(1)", "invalid_url"),
    ("http://user:pw@example.com/", "invalid_url"), ("http://example.com@127.0.0.1/", "invalid_url"),
    ("http://example.com:8080/", "blocked_port"), ("http://example.com:22/", "blocked_port"),
    ("http://localhost/", "blocked_address"), ("http://printer.local/", "blocked_address"),
    ("http://db.internal/", "blocked_address"), ("http://router.home.arpa/", "blocked_address"),
    ("http://intranet/", "blocked_address"), ("http://2130706433/", "blocked_address"),
    ("http://127.0.0.1/", "blocked_address"), ("http://[::1]/", "blocked_address"),
    ("http://169.254.169.254/latest/meta-data/", "blocked_address"), ("http://[::ffff:10.0.0.1]/", "blocked_address"),
    ("http://exa mple.com/", "invalid_url"), ("", "invalid_url"),
])
def test_hostile_urls_are_refused_before_connecting(url, error):
    page = fetcher(never).fetch(url, timeout=5)
    assert (page.ok, page.error) == (False, error)


def test_every_resolved_address_must_be_public():
    mixed = fetcher(never, resolver=lambda h, p: [PUBLIC, "10.0.0.5"])
    assert mixed.fetch("https://rebind.attacker.com/", timeout=5).error == "blocked_address"
    sneaky = fetcher(never, resolver=lambda h, p: ["127.0.0.1"])
    assert sneaky.fetch("https://0x7f.0.0.1.attacker.com/", timeout=5).error == "blocked_address"


def test_dns_failure():
    def broken(host, port):
        raise OSError("nxdomain")
    assert fetcher(never, resolver=broken).fetch("https://nope.example-dead.com/", timeout=5).error == "dns_failure"


def test_html_page_is_extracted():
    body = (b"<html><head><title>Acme  News</title><meta property='og:site_name' content='Acme Daily'>"
            b"<meta property='article:published_time' content='2026-05-01T10:00:00Z'>"
            b"<script>var secret = 1;</script><style>p{}</style></head>"
            b"<body><h1>Headline</h1><p>Acme was founded in 2015 &amp; grew.</p><nav>Menu</nav></body></html>")
    page = fetcher(lambda r: html(body)).fetch("https://acme-news.com/a", timeout=5)
    assert page.ok and page.status == 200 and page.title == "Acme News" and page.publisher == "Acme Daily"
    assert page.published_at.isoformat() == "2026-05-01T10:00:00+00:00"
    assert "Acme was founded in 2015 & grew." in page.text and "secret" not in page.text and "p{}" not in page.text


def test_redirects_are_revalidated_hop_by_hop():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://internal-admin.corp.com/"})
    resolver = lambda host, port: ["10.0.0.7"] if "corp" in host else [PUBLIC]  # noqa: E731
    page = fetcher(handler, resolver=resolver).fetch("https://short.link/x", timeout=5)
    assert page.error == "blocked_address" and page.final_url == "http://internal-admin.corp.com/"
    to_metadata = fetcher(lambda r: httpx.Response(301, headers={"location": "http://169.254.169.254/"}))
    assert to_metadata.fetch("https://short.link/y", timeout=5).error == "blocked_address"


def test_relative_redirects_and_limits():
    hops = []

    def handler(request):
        hops.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "/final"})
        return html(b"<p>Done.</p>")
    page = fetcher(handler).fetch("https://site.com/start", timeout=5)
    assert page.ok and page.final_url == "https://site.com/final" and len(hops) == 2
    loop = fetcher(lambda r: httpx.Response(302, headers={"location": "/again"}))
    assert loop.fetch("https://site.com/loop", timeout=5).error == "redirect_limit"


@pytest.mark.parametrize("response,error", [
    (html(b"missing", status=404), "http_error"),
    (html(b"%PDF-1.7", ctype="application/pdf"), "unsupported_content_type"),
    (html(b"x" * 5000), "too_large"),
])
def test_status_type_and_size_limits(response, error):
    page = fetcher(lambda r: response, max_bytes=1000).fetch("https://site.com/x", timeout=5)
    assert page.error == error
    if error == "http_error":
        assert page.status == 404


def test_timeouts_and_network_errors():
    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)
    assert fetcher(slow).fetch("https://site.com/x", timeout=5).error == "timeout"

    def refused(request):
        raise httpx.ConnectError("refused", request=request)
    assert fetcher(refused).fetch("https://site.com/x", timeout=5).error == "network_error"


@pytest.mark.parametrize("robots_response,allowed", [
    (httpx.Response(200, text="User-agent: *\nDisallow: /private\n"), False),
    (httpx.Response(200, text="User-agent: TrustLayerVerifier\nDisallow: /\n"), False),
    (httpx.Response(404, text="none"), True),
    (httpx.Response(503, text="busy"), False),
])
def test_robots_txt_rfc9309(robots_response, allowed):
    def handler(request):
        if request.url.path == "/robots.txt":
            return robots_response
        return html(b"<p>Private page.</p>")
    page = fetcher(handler, respect_robots=True).fetch("https://site.com/private/page", timeout=5)
    assert page.ok is allowed
    if not allowed:
        assert page.error == "robots_disallowed"


def test_robots_is_fetched_once_per_origin():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(404) if request.url.path == "/robots.txt" else html(b"<p>ok</p>")
    f = fetcher(handler, respect_robots=True)
    f.fetch("https://site.com/a", timeout=5)
    f.fetch("https://site.com/b", timeout=5)
    assert seen.count("/robots.txt") == 1


def test_garbage_html_never_raises():
    title, publisher, published, text = html_to_text("<html><head><title>x<<<</ti<p>unclosed &bogus; <script>")
    assert isinstance(text, str)
    _, _, date, body = html_to_text('<head><meta name="date" content="garbage"><body><p>Still here</p>')
    assert date is None and "Still here" in body


def test_time_and_jsonld_dates():
    assert html_to_text('<p><time datetime="2025-02-03">Feb</time></p>')[2].date().isoformat() == "2025-02-03"
    jsonld = '<script type="application/ld+json">{"datePublished": "2024-07-08"}</script><p>Body</p>'
    published = html_to_text(jsonld)[2]
    assert published.isoformat() == "2024-07-08T00:00:00+00:00" and published.tzinfo == timezone.utc


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.calls.append(host)
        return "stream"


def pinned(resolver):
    backend = _PinnedBackend(resolver)
    backend._inner = RecordingBackend()
    return backend


def test_pinned_backend_connects_to_the_validated_ip():
    backend = pinned(public)
    assert backend.connect_tcp("example.com", 443) == "stream"
    assert backend._inner.calls == [PUBLIC]


@pytest.mark.parametrize("host,resolved", [("rebind.attacker.com", ["10.0.0.1"]), ("127.0.0.1", None),
                                           ("[::1]", None), ("mixed.attacker.com", [PUBLIC, "127.0.0.1"])])
def test_pinned_backend_refuses_private_targets_without_opening_a_socket(host, resolved):
    backend = pinned(lambda h, p: resolved)
    with pytest.raises(httpcore.ConnectError):
        backend.connect_tcp(host, 443)
    assert backend._inner.calls == []
    with pytest.raises(httpcore.ConnectError):
        backend.connect_unix_socket("/var/run/docker.sock")


def test_client_settings_and_env(monkeypatch):
    monkeypatch.setenv("TRUSTLAYER_CONTACT", "https://github.com/acme/trust")
    client = safe_client(timeout=3)
    assert client.trust_env is False and client.headers["User-Agent"] == user_agent()
    assert user_agent() == "TrustLayerVerifier/2.0 (+https://github.com/acme/trust)"
    monkeypatch.setenv("TRUSTLAYER_CONTACT", "bad\nvalue")
    assert user_agent() == "TrustLayerVerifier/2.0"
    monkeypatch.setenv("TRUSTLAYER_RESPECT_ROBOTS", "OFF")
    assert respects_robots() is False
    monkeypatch.setenv("TRUSTLAYER_FETCH_ALLOWED_PORTS", "443,8443")
    assert allowed_ports() == (443, 8443)
    for bad in ("", "http", "0", "70000"):
        monkeypatch.setenv("TRUSTLAYER_FETCH_ALLOWED_PORTS", bad)
        with pytest.raises(ValueError):
            allowed_ports()


@pytest.mark.parametrize("unit", ["<a ", "<p a='", "<!--", "</a", "<?", "<!x", "&#", "<a " + "x" * 999])
def test_malformed_markup_parses_in_linear_time(unit):
    # html.parser alone was quadratic here: 21 KB of "<a " took 20 seconds.
    import time

    started = time.perf_counter()
    html_to_text(unit * (200_000 // len(unit)))
    assert time.perf_counter() - started < 2.0


def test_defusing_keeps_real_markup_and_text():
    title, publisher, published, text = html_to_text(
        '<html><head><title>T &amp; Co</title><meta property="og:site_name" content="Pub">'
        '<meta name="date" content="2024-05-01"></head><body><p>a < b and <b>bold</b></p>'
        '<script>if (a<b) x()</script><!-- hidden --><p>end</p></body></html>')
    assert (title, publisher, published.date().isoformat()) == ("T & Co", "Pub", "2024-05-01")
    assert text == "a < b and bold\nend"
    assert html_to_text("<p>kept</p><!-- never closed <p>hidden</p>")[3] == "kept"
