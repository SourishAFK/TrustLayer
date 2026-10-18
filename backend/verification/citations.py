"""Engine C: citation parsing and validation.

A real-looking URL is not evidence. For every citation in the response this
engine finds the claim(s) it is attached to, then checks, in order:

  1. placeholder host (example.com, *.invalid ...)      -> invalid_or_fabricated
  2. DOI registered? (doi.org handle API)               -> invalid_or_fabricated
  3. page readable? (SSRF-safe fetcher, robots.txt)     -> broken / inaccessible / blocked
  4. does the page support the claim? (Engine B judge)  -> supports / does_not_support / contradicts
  5. quoted words really in the source?                 -> misleading_quotation signal
  6. source too old for a time-sensitive claim?         -> outdated_source signal
  7. claim says "proves", source says "may"?            -> possible_exaggeration signal

Supporting or contradicting passages become Evidence for the claim (retrieval
"citation"); every citation also gets a visible status and explanation.
"""

import itertools
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import quote, urlsplit

from backend.verification.aggregator import freshness_days
from backend.verification.contracts import FetchedPage, Findings, RunContext
from backend.verification.evidence import _candidates, judge_passages, query_for
from backend.verification.report import CheckRecord, CitationCheck, EngineRun, TextSpan
from backend.verification.schemas import Claim, ClaimType
from backend.verification.sources import (
    HEDGE,
    QUOTED,
    STRONG,
    classify_source,
    injection_markers,
    normalize_for_match,
    registrable_domain,
)

logger = logging.getLogger(__name__)
MAX_CITATIONS = 12
_TRAILING = ".,;:)]}'\"”’»…"
# Quotes, guillemets and CJK/fullwidth punctuation end a URL ("“https://x.org”", "见https://x.org。它").
_NOT_URL = "\\s<>\"'`“”‘’«»…。，、；：！？）】」』〉》"
_URL = re.compile(rf"https?://[^{_NOT_URL}]+", re.I)
# One level of balanced parentheses inside a markdown link target: (…/Python_(programming_language)).
_MD_LINK = re.compile(rf"\[[^\]\n]{{1,300}}\]\((https?://(?:[^{_NOT_URL}()]|\([^{_NOT_URL}()]*\))+)\)", re.I)
_DOI = re.compile(rf"\b(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?(10\.\d{{4,9}}/[^{_NOT_URL}]+)", re.I)
# The body starts and ends with a non-space, so the pattern never backtracks through whitespace.
_DEFINITION = re.compile(r"(?m)^[ \t]*(?:\[(\d{1,3})\]:?|(\d{1,3})[.)])[ \t]+(\S(?:[^\n]*\S)?)[ \t\r]*$")
_MARKER = re.compile(r"\[(\d{1,3})\]")
_CURRENT = re.compile(r"\b(?:current(?:ly)?|now|today|latest|as of|this year|at the moment|presently)\b", re.I)
_PLACEHOLDER_SUFFIXES = (".example", ".invalid", ".test", ".localhost")
_PLACEHOLDER_HOSTS = {"example.com", "example.net", "example.org", "localhost"}
_ERRORS = {
    "blocked_address": ("blocked", "TrustLayer did not fetch this link: it points at a private or "
                                   "internal address."),
    "blocked_port": ("blocked", "TrustLayer did not fetch this link: it uses a non-standard port."),
    "robots_disallowed": ("blocked", "The site's robots.txt asks automated readers not to fetch this page."),
    "dns_failure": ("broken", "The domain does not resolve, so the source does not exist at this address."),
    "unsupported_content_type": ("inaccessible", "The link is not a readable web page (for example a PDF)."),
    "too_large": ("inaccessible", "The page is too large to read safely."),
    "timeout": ("inaccessible", "The page did not respond in time."),
    "network_error": ("inaccessible", "The page could not be reached."),
    "redirect_limit": ("inaccessible", "The link redirects too many times."),
    "invalid_url": ("invalid_or_fabricated", "The link is malformed."),
    "budget_exhausted": ("not_checked", "Not checked: this run's page-reading budget was used up."),
    "fetch_disabled": ("not_checked", "Not checked: web access is turned off for this request."),
}


@dataclass
class ParsedCitation:
    citation_id: str
    raw_text: str
    start: int
    end: int
    url: str | None
    doi: str | None
    marker: str | None = None
    places: list[int] = field(default_factory=list)  # positions where the response points to it


def _clean(url: str) -> str:
    """Drop trailing sentence punctuation; keep a ")" that closes a "(" in the URL."""
    opens, closes, end = url.count("("), url.count(")"), len(url)
    while end and url[end - 1] in _TRAILING:
        if url[end - 1] == ")":
            if opens >= closes:
                break
            closes -= 1
        end -= 1
    return url[:end]


def _line_start(text: str, index: int) -> bool:
    """Only spaces between the start of the line and `index` (scans back over spaces only)."""
    while index > 0 and text[index - 1] in " \t\r":
        index -= 1
    return index == 0 or text[index - 1] == "\n"


def parse_citations(text: str) -> list[ParsedCitation]:
    """Citations in order of appearance; one per distinct URL/DOI."""
    found: dict[str, ParsedCitation] = {}
    taken: list[tuple[int, int]] = []

    def add(key: str, raw: str, start: int, end: int, url: str | None, doi: str | None,
            marker: str | None = None, points: bool = True):
        if key not in found:
            found[key] = ParsedCitation("", raw, start, end, url, doi, marker)
        citation = found[key]
        citation.marker = citation.marker or marker
        if points:  # reference-list lines only point at claims through their [n] markers
            citation.places.append(start)
        taken.append((start, end))

    def target(fragment: str) -> tuple[str | None, str | None]:
        url_match = _URL.search(fragment)
        url = _clean(url_match.group(0)) if url_match else None
        doi_match = _DOI.search(fragment)
        doi = _clean(doi_match.group(1)) if doi_match else None
        return url, doi

    # "1. Aspirin cures cancer (https://…)" is a numbered list of claims, not a reference list:
    # a "N." line is a definition only when the response also points at it with "[N]".
    inline_markers = {m.group(1) for m in _MARKER.finditer(text) if not _line_start(text, m.start())}
    for m in _DEFINITION.finditer(text):
        if m.group(2) and m.group(2) not in inline_markers:
            continue
        url, doi = target(m.group(3))
        if url or doi:
            start = m.start() + len(m.group(0)) - len(m.group(0).lstrip())
            end = m.end(3)  # raw_text == text[start:end], without trailing spaces or "\r"
            add(doi or url, text[start:end], start, end, url, doi, marker=m.group(1) or m.group(2), points=False)

    def free(start: int, end: int) -> bool:
        return not any(s <= start < e or s < end <= e for s, e in taken)

    for pattern in (_MD_LINK, _URL):
        for m in pattern.finditer(text):
            raw_url = m.group(1) if pattern is _MD_LINK else m.group(0)
            url = _clean(raw_url)
            start, end = (m.start(), m.end()) if pattern is _MD_LINK else (m.start(), m.start() + len(url))
            if not free(start, end):
                continue
            doi_match = _DOI.search(url)
            doi = _clean(doi_match.group(1)) if doi_match and "doi.org/" in url.lower() else None
            add(doi or url, text[start:end], start, end, url, doi)
    for m in _DOI.finditer(text):
        if free(m.start(), m.end()):
            doi = _clean(m.group(1))
            add(doi, text[m.start():m.start() + len(m.group(0).rstrip(_TRAILING))], m.start(),
                m.start() + len(m.group(0).rstrip(_TRAILING)), None, doi)

    by_marker = {c.marker: c for c in found.values() if c.marker}
    for m in _MARKER.finditer(text):
        if _line_start(text, m.start()):
            continue  # the definition line itself
        if m.group(1) in by_marker:
            by_marker[m.group(1)].places.append(m.start())
    ordered = sorted(found.values(), key=lambda c: c.start)
    for index, citation in enumerate(ordered, start=1):
        citation.citation_id = f"r{index}"
    return ordered


def _sentence_span(text: str, claim: Claim) -> tuple[int, int]:
    start = claim.text_span.start
    for m in re.finditer(re.escape(claim.context), text):
        if m.start() <= start < m.end():
            return m.start(), m.end()
    return start, claim.text_span.end


def attach(text: str, citations: list[ParsedCitation], claims: list[Claim]) -> dict[str, list[str]]:
    """citation_id -> claim ids whose span or sentence points at the citation."""
    spans = {c.claim_id: (c.text_span.start, c.text_span.end, *_sentence_span(text, c)) for c in claims}
    attached: dict[str, list[str]] = {}
    for citation in citations:
        ids = []
        for claim in claims:
            start, end, s_start, s_end = spans[claim.claim_id]
            # A marker right after the sentence's full stop ("...cancer.[1]") still belongs to it,
            # but not one that starts the next sentence.
            if any(start <= p <= end or s_start <= p <= s_end
                   or (s_end < p <= s_end + 4 and not text[s_end:p].strip(" .,;:!?)"))
                   for p in citation.places):
                ids.append(claim.claim_id)
        attached[citation.citation_id] = ids
    return attached


def _placeholder(url: str | None) -> bool:
    host = (urlsplit(url).hostname or "").lower().rstrip(".") if url else ""
    return bool(host) and (host in _PLACEHOLDER_HOSTS or host.endswith(_PLACEHOLDER_SUFFIXES)
                           or any(host.endswith("." + h) for h in _PLACEHOLDER_HOSTS))


def _time_sensitive(claim: Claim) -> bool:
    return claim.claim_type == ClaimType.time_sensitive or bool(_CURRENT.search(claim.exact_text))


class CitationEngine:
    name = "citations"

    def run(self, ctx: RunContext, findings: Findings) -> EngineRun:
        started = time.perf_counter()
        text = ctx.request.response_text
        citations = parse_citations(text)
        if not citations:
            return EngineRun(engine=self.name, status="not_applicable", duration_ms=0,
                             detail="No citations found in the response.")
        attached = attach(text, citations, ctx.claims)
        statuses = []
        for index, citation in enumerate(citations):
            claim_ids = attached[citation.citation_id]
            for cid in claim_ids:
                findings.note(cid, citation_id=citation.citation_id)
            if index >= MAX_CITATIONS:
                check = self._record(ctx, findings, citation, claim_ids, "not_checked",
                                     f"Not checked: at most {MAX_CITATIONS} citations are checked per report.")
                findings.incomplete_check(f"Only the first {MAX_CITATIONS} citations were checked.")
            else:
                ctx.progress(self.name, "progress", f"Checking citation {citation.citation_id}", kind="source")
                check = self._check(ctx, findings, citation, claim_ids)
            statuses.append(check.status)
        counts = {s: statuses.count(s) for s in dict.fromkeys(statuses)}
        status = "partial" if "not_checked" in counts else "completed"
        return EngineRun(engine=self.name, status=status,
                         duration_ms=round((time.perf_counter() - started) * 1000, 1),
                         detail=f"{len(citations)} citation(s): " +
                                ", ".join(f"{n} {s.replace('_', ' ')}" for s, n in counts.items()))

    # -- one citation --------------------------------------------------------- #

    def _check(self, ctx: RunContext, findings: Findings, citation: ParsedCitation,
               claim_ids: list[str]) -> CitationCheck:
        if _placeholder(citation.url):
            return self._record(ctx, findings, citation, claim_ids, "invalid_or_fabricated",
                                "The link uses a placeholder or reserved domain that cannot host a real source.")
        target = citation.url
        if citation.doi:
            handle = ctx.fetch("https://doi.org/api/handles/" + quote(citation.doi, safe="/:;()._-"))
            registered, resolved = _doi_status(handle)
            if registered is False:
                return self._record(ctx, findings, citation, claim_ids, "invalid_or_fabricated",
                                    "The DOI is not registered, so this reference may be fabricated.",
                                    http_status=handle.status)
            if registered is None:
                status, why = _ERRORS.get(handle.error or "", ("inaccessible", "doi.org could not be reached."))
                return self._record(ctx, findings, citation, claim_ids, status,
                                    f"The DOI could not be checked: {why[0].lower()}{why[1:]}")
            target = resolved or citation.url
            if not target or not claim_ids:
                return self._record(ctx, findings, citation, claim_ids, "accessible_unassessed",
                                    "The DOI is registered. Its content was not compared with a claim.")
        page = ctx.fetch(target)
        if not page.ok:
            return self._failed_page(ctx, findings, citation, claim_ids, page)
        return self._assess(ctx, findings, citation, claim_ids, page)

    def _failed_page(self, ctx, findings, citation, claim_ids, page: FetchedPage) -> CitationCheck:
        if page.error == "http_error":
            code = page.status or 0
            status = "inaccessible" if code in (401, 402, 403, 407, 429) else "broken"
            why = (f"The page refused access (HTTP {code})." if status == "inaccessible"
                   else f"The page returned HTTP {code}; the source is missing at this address.")
        else:
            status, why = _ERRORS.get(page.error or "", ("inaccessible", "The page could not be read."))
        if status == "not_checked":
            findings.incomplete_check("Some citations were not checked because of the run's budget or settings.")
        return self._record(ctx, findings, citation, claim_ids, status, why, http_status=page.status,
                            final_url=page.final_url)

    def _assess(self, ctx: RunContext, findings: Findings, citation: ParsedCitation, claim_ids: list[str],
                page: FetchedPage) -> CitationCheck:
        if not claim_ids:
            return self._record(ctx, findings, citation, claim_ids, "accessible_unassessed",
                                "The page is reachable. It is not attached to a specific claim, so its "
                                "content was not compared with one.", page=page)
        ids = itertools.count(1)
        domain = registrable_domain(page.final_url) or "unknown"
        outcomes: dict[str, str] = {}
        best_passages: dict[str, str] = {}
        poisoned = False
        for cid in claim_ids:
            claim = ctx.claim(cid)
            found = _candidates(
                page.text, f"{query_for(claim)} {claim.exact_text}", ids, url=page.final_url, title=page.title,
                publisher=page.publisher, domain=domain,
                source_type=classify_source(page.final_url, claim_text=claim.context, provider="cited",
                                            corpus=f"{ctx.request.response_text}\n{page.text}"),
                retrieval="citation", provider="cited", published_at=page.published_at,
                accessed_at=page.fetched_at)
            candidates = [c for c in found if not injection_markers(c.passage)]
            poisoned = poisoned or len(candidates) < len(found)
            if candidates:
                best_passages[cid] = candidates[0].passage
            if not candidates:
                outcomes[cid] = "does_not_support"
                continue
            judgments = judge_passages(ctx, claim, candidates)
            if judgments is None:
                outcomes[cid] = "unassessed"
                continue
            stances = {j.stance for j in judgments}
            for j in judgments:
                if j.stance in ("supports", "contradicts"):
                    findings.add_evidence(
                        claim_id=cid, stance=j.stance, url=j.candidate.url, title=(page.title or None),
                        publisher=page.publisher, domain=domain, source_type=j.candidate.source_type,
                        retrieval="citation", provider="cited", published_at=page.published_at,
                        accessed_at=page.fetched_at, passage=j.candidate.passage, quote=j.quote,
                        method=f"citation_check+llm_stance:{ctx.llm.model}", rationale=j.rationale or None)
                    if j.stance == "supports":
                        best_passages[cid] = j.candidate.passage
            outcomes[cid] = ("contradicts" if "contradicts" in stances else "supports" if "supports" in stances
                             else "does_not_support")
            findings.note(cid, investigated=True, method="citation_check",
                          check=CheckRecord(engine=self.name, status="completed",
                                            detail=f"Citation {citation.citation_id}: {outcomes[cid].replace('_', ' ')}"))
        values = set(outcomes.values())
        if "contradicts" in values:
            status, why = "contradicts", "The cited page conflicts with the claim it is attached to."
        elif values == {"supports"}:
            status, why = "supports", "The cited page supports the claim it is attached to."
        elif values <= {"unassessed"}:
            status, why = ("accessible_unassessed", "The page is reachable, but no AI reader was available to "
                                                    "assess whether it supports the claim.")
        else:
            status, why = ("does_not_support", "The page is reachable but does not support what it is cited "
                                               "for.")
        if poisoned:
            findings.add_signal(engine=self.name, kind="suspicious_source_instructions", severity="warning",
                                text=domain, claim_ids=claim_ids,
                                explanation=("The cited page contains instruction-like text aimed at AI systems; "
                                             "those passages were excluded from the assessment."))
        return self._record(ctx, findings, citation, claim_ids, status, why, page=page,
                            best_passages=best_passages)

    # -- reporting ------------------------------------------------------------ #

    def _record(self, ctx: RunContext, findings: Findings, citation: ParsedCitation, claim_ids: list[str],
                status: str, explanation: str, *, http_status: int | None = None, final_url: str | None = None,
                page: FetchedPage | None = None, best_passages: dict[str, str] | None = None) -> CitationCheck:
        claims = [ctx.claim(cid) for cid in claim_ids]
        quote_check, flags, outdated = "not_applicable", [], None
        if page is not None:
            quote_check = self._quote_check(claims, page.text)
            outdated = self._outdated(ctx, claims, page)
            flags = self._exaggerations(claims, best_passages or {})
        check = CitationCheck(
            citation_id=citation.citation_id, raw_text=citation.raw_text[:1000],
            text_span=TextSpan(start=citation.start, end=citation.end), url=citation.url, doi=citation.doi,
            claim_ids=claim_ids, status=status, http_status=page.status if page else http_status,
            final_url=page.final_url if page else final_url, title=page.title if page else None,
            published_at=page.published_at if page else None, outdated=outdated, quote_check=quote_check,
            exaggeration_flags=flags, explanation=explanation,
            checked_at=ctx.now if status != "not_checked" else None)
        with findings.lock:
            findings.citations.append(check)
        span = TextSpan(start=citation.start, end=citation.end)
        if status in ("invalid_or_fabricated", "broken", "does_not_support", "contradicts"):
            findings.add_signal(engine=self.name, kind="unsupported_citation", severity="critical",
                                text=citation.raw_text[:1000], text_span=span, claim_ids=claim_ids,
                                explanation=explanation)
        if quote_check == "not_found":
            findings.add_signal(engine=self.name, kind="misleading_quotation", severity="critical",
                                text=citation.raw_text[:1000], text_span=span, claim_ids=claim_ids,
                                explanation="Words presented as a quotation do not appear in the cited source.")
        if outdated:
            findings.add_signal(engine=self.name, kind="outdated_source", severity="warning",
                                text=citation.raw_text[:1000], text_span=span, claim_ids=claim_ids,
                                explanation=f"The cited source dates from {page.published_at:%Y-%m-%d}, older than "
                                            f"{freshness_days()} days, for a claim about the current situation.")
        for flag in flags:
            findings.add_signal(engine=self.name, kind="possible_exaggeration", severity="warning",
                                text=citation.raw_text[:1000], text_span=span, claim_ids=claim_ids, explanation=flag)
        return check

    @staticmethod
    def _quote_check(claims: list[Claim], page_text: str) -> str:
        quotes = [q for c in claims for q in QUOTED.findall(c.context) if len(q.split()) >= 4]
        if not quotes:
            return "not_applicable"
        haystack = normalize_for_match(page_text)
        return "verbatim" if all(normalize_for_match(q) in haystack for q in quotes) else "not_found"

    @staticmethod
    def _outdated(ctx: RunContext, claims: list[Claim], page: FetchedPage) -> bool | None:
        if page.published_at is None or not any(_time_sensitive(c) for c in claims):
            return None
        return page.published_at < ctx.now - timedelta(days=freshness_days())

    @staticmethod
    def _exaggerations(claims: list[Claim], passages: dict[str, str]) -> list[str]:
        flags = []
        for claim in claims:
            strong = STRONG.search(claim.exact_text)
            hedge = HEDGE.search(passages.get(claim.claim_id, ""))
            if strong and hedge:
                flags.append(f"The claim says \"{strong.group(0)}\" but the source only says "
                             f"\"{hedge.group(0)}\".")
        return flags


def _doi_status(page: FetchedPage) -> tuple[bool | None, str | None]:
    """(registered?, resolved URL). None when the registry could not be asked."""
    if not page.ok:
        return (False, None) if page.error == "http_error" and page.status == 404 else (None, None)
    try:
        data = json.loads(page.text)
    except ValueError:
        return None, None
    if data.get("responseCode") == 100:
        return False, None
    if data.get("responseCode") != 1:
        return None, None
    url = next((v.get("data", {}).get("value") for v in data.get("values", [])
                if isinstance(v, dict) and v.get("type") == "URL"), None)
    return True, url if isinstance(url, str) and url.startswith(("http://", "https://")) else None
