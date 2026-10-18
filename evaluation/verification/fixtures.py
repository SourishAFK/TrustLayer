"""Frozen-web fixtures for the verification benchmark: search, fetch and judges.

Every case brings its own small corpus, so runs are deterministic, offline and
free. OracleJudge answers each model task from the corpus annotations, which
isolates retrieval, validation and the verdict policy from model quality.
NoisyJudge answers "supports" to every passage, to measure how many false
supports the deterministic guards stop.
"""

import json
import re
from datetime import datetime, timezone

from backend.verification.contracts import (
    FetchedPage,
    LLMError,
    LLMResult,
    SearchResult,
)
from backend.verification.sources import STOPWORDS, key_entities, normalize_for_match

FIXED_NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
_PASSAGE = re.compile(r'<passage id="(P\d+)"[^>]*>\n(.*?)\n</passage>', re.S)


def parse_date(value) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=timezone.utc)


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.casefold()) if len(t) >= 2 and t not in STOPWORDS}


def same_claim(gold: str, claim: str) -> bool:
    a, b = normalize_for_match(gold), normalize_for_match(claim)
    if a in b or b in a:
        return True
    ta, tb = tokens(a), tokens(b)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.6


class FixtureSearch:
    """Lexical search over a case corpus. kind 'academic' serves only OpenAlex-style entries."""

    def __init__(self, corpus: list[dict], name: str = "fixture", kind: str = "web"):
        self.name, self.kind = name, kind
        wanted = (lambda e: e.get("provider") == "openalex") if kind == "academic" else (
            lambda e: e.get("provider") != "openalex")
        self.entries = [e for e in corpus if e.get("text") and e.get("searchable", True) and wanted(e)]

    def search(self, query: str, *, count: int, timeout: float) -> list[SearchResult]:
        wanted = tokens(query)
        scored = sorted(((len(wanted & tokens(f"{e.get('title', '')} {e['text']}")), i, e)
                         for i, e in enumerate(self.entries)), key=lambda item: (-item[0], item[1]))
        return [SearchResult(title=e.get("title") or e["url"], url=e["url"], snippet=e["text"][:200],
                             provider=e.get("provider", "brave"), published_at=parse_date(e.get("published_at")),
                             content=e["text"] if e.get("provider") in ("wikipedia", "openalex") else None)
                for score, _, e in scored if score > 0][:count]


class FixtureFetcher:
    """Serves corpus pages; unknown URLs behave like a domain that does not resolve."""

    def __init__(self, corpus: list[dict]):
        self.pages = {e["url"]: e for e in corpus}

    def fetch(self, url: str, *, timeout: float) -> FetchedPage:
        entry = self.pages.get(url)
        if entry is None or entry.get("fetch_error"):
            error = entry.get("fetch_error") if entry else "dns_failure"
            return FetchedPage(url, url, False, entry.get("status") if entry else None, error, None, None,
                               None, None, "", FIXED_NOW)
        text = entry.get("text", "")
        content_type = "application/json" if text.lstrip().startswith("{") else "text/html"
        return FetchedPage(url, url, True, entry.get("status", 200), None, content_type, entry.get("title"),
                           entry.get("publisher"), parse_date(entry.get("published_at")), text, FIXED_NOW)


class OracleJudge:
    """A perfect reader for the annotated corpus: every model task answered from the gold annotations."""

    name, family, model = "oracle", "oracle", "oracle-judge"

    def __init__(self, corpus: list[dict]):
        self.judgments = [j for e in corpus for j in e.get("judgments", [])]
        self.calls: dict[str, int] = {}

    def complete_json(self, *, system: str, prompt: str, schema: dict, max_output_tokens: int,
                      timeout: float) -> LLMResult:
        title = schema.get("title")
        self.calls[title] = self.calls.get(title, 0) + 1
        handler = {"stance_judgments": self._stances, "search_queries": lambda p: {"queries": []},
                   "market_profile": self._profile, "competitor_mentions": self._mentions,
                   "consistency_review": lambda p: {"contradictions": [], "non_sequiturs": []},
                   "completeness_review": lambda p: {"subquestions": [], "missing": []}}.get(title)
        if handler is None:
            raise LLMError("oracle: unsupported task")
        return LLMResult(handler(prompt), self.model, 0, 0)

    def _stance(self, claim: str, passage: str) -> dict:
        for j in self.judgments:
            if same_claim(j["claim_text"], claim) and j["quote"] in passage:
                return {"stance": j["stance"], "quote": j["quote"], "rationale": "annotated",
                        "correction": j.get("correction", "")}
        return {"stance": "irrelevant", "quote": "", "rationale": "", "correction": ""}

    def _stances(self, prompt: str) -> dict:
        claim = re.search(r"^CLAIM: (.*)$", prompt, re.M).group(1)
        return {"judgments": [{"passage_id": pid, **self._stance(claim, text)}
                              for pid, text in _PASSAGE.findall(prompt)]}

    @staticmethod
    def _profile(prompt: str) -> dict:
        # A real model would summarize the product; the first sentence of the response is a fair stand-in.
        response = re.search(r"<response>\n(.*?)\n</response>", prompt, re.S).group(1)
        first = re.split(r"(?<=[.!?])\s", response.strip(), maxsplit=1)[0]
        subject = (key_entities(first) or [""])[0]
        query = " ".join(first.replace(subject, " ", 1).split()).strip(" .")
        return {"product_summary": first[:400], "category": "", "customers": [], "use_cases": [],
                "queries": [query] if 2 <= len(query.split()) <= 12 else []}

    def _mentions(self, prompt: str) -> dict:
        mentions = []
        for pid, text in _PASSAGE.findall(prompt):
            for j in self.judgments:
                if j["stance"] != "contradicts" or j["quote"] not in text:
                    continue
                name = j.get("competitor") or next(iter(key_entities(j["quote"])), "")
                if name and name in j["quote"]:
                    mentions.append({"passage_id": pid, "name": name, "relation": j.get("relation", "direct"),
                                     "quote": j["quote"], "description": j["quote"], "differentiation": ""})
        return {"mentions": mentions}


class NoisyJudge(OracleJudge):
    """Says every passage supports the claim: what slips through is what the guards miss."""

    name, model = "noisy", "noisy-judge"

    def _stances(self, prompt: str) -> dict:
        return {"judgments": [{"passage_id": pid, "stance": "supports", "quote": text[:60],
                               "rationale": "noisy", "correction": ""}
                              for pid, text in _PASSAGE.findall(prompt)]}


def load_cases(path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("cases"), list):
        raise ValueError(f"{path.name}: expected schema_version 1 with a cases list")
    return data
