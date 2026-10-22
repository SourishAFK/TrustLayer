"""Source helpers: domains, source types, passages, quotes, numbers, injection screening.

Pure functions, no I/O. Two properties keep evidence verifiable:
  * every passage is an exact slice of its source text, and
  * find_quote returns an exact slice of the passage (or None), so a model's
    paraphrase can never be stored as a quote.
"""

import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit

# ponytail: hand-picked multi-part suffixes; use the Public Suffix List if
# independence counting ever needs to be exact for every country.
MULTI_PART_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "edu.au", "gov.au",
    "co.in", "gov.in", "ac.in", "co.jp", "ac.jp", "go.jp", "com.br", "gov.br", "co.nz", "govt.nz",
    "ac.nz", "com.cn", "gov.cn", "edu.cn", "co.za", "gov.za", "ac.za", "com.sg", "gov.sg", "edu.sg",
    "com.mx", "gob.mx", "co.kr", "go.kr", "ac.kr", "nic.in", "gc.ca", "gouv.fr", "gov.ie",
}
OFFICIAL_DOMAINS = {"europa.eu", "who.int", "un.org"}
# Government / university second levels that only those institutions can register; an
# arbitrary "gov.xyz" or "ac.xyz" (or "go.com", "go.dev") is anyone's domain.
OFFICIAL_SUFFIXES = {"gov.uk", "gov.au", "gov.in", "nic.in", "gov.br", "govt.nz", "gov.cn", "gov.za",
                     "gov.sg", "gob.mx", "go.jp", "go.kr", "gc.ca", "gouv.fr", "gov.ie"}
ACADEMIC_SUFFIXES = {"ac.uk", "ac.in", "ac.jp", "ac.nz", "ac.za", "ac.kr", "edu.au", "edu.cn", "edu.sg"}
ACADEMIC_DOMAINS = {
    "doi.org", "arxiv.org", "nature.com", "science.org", "sciencedirect.com", "springer.com",
    "wiley.com", "plos.org", "jstor.org", "ssrn.com", "acm.org", "ieee.org", "biorxiv.org",
    "medrxiv.org", "semanticscholar.org", "openalex.org",
}
ACADEMIC_HOSTS = {"pubmed.ncbi.nlm.nih.gov"}
USER_CONTENT_EDU = {"academia.edu"}  # a .edu domain where anyone uploads documents
REFERENCE_DOMAINS = {"wikipedia.org", "britannica.com", "wikidata.org"}
NEWS_DOMAINS = {
    "reuters.com", "apnews.com", "bbc.co.uk", "bbc.com", "nytimes.com", "ft.com", "wsj.com",
    "bloomberg.com", "theguardian.com", "cnbc.com", "techcrunch.com", "theverge.com",
    "economist.com", "forbes.com", "wired.com", "washingtonpost.com", "axios.com", "npr.org",
}
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "did", "do", "does",
    "for", "from", "had", "has", "have", "he", "her", "his", "how", "if", "in", "into", "is", "it",
    "its", "of", "on", "or", "our", "she", "so", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "those", "to", "was", "we", "were", "what", "when", "which",
    "who", "will", "with", "would", "you", "your",
}
ENTITY_STOPWORDS = {"The", "A", "An", "In", "It", "Its", "This", "That", "Our", "We", "I", "They",
                    "He", "She", "As", "At", "On", "Of", "For", "By", "With", "And", "But"}


def _host(url_or_host: str) -> str:
    value = url_or_host.strip()
    if "://" in value:
        host = urlsplit(value).hostname or ""
    else:
        host = value.split("/")[0]
        if host.startswith("["):
            host = host[1:].split("]")[0]
        elif host.count(":") == 1:
            host = host.split(":")[0]
    host = host.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def registrable_domain(url_or_host: str) -> str:
    """'https://news.bbc.co.uk/x' -> 'bbc.co.uk'. Independence is counted per domain."""
    host = _host(url_or_host)
    if not host or _is_ip(host):
        return host
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in MULTI_PART_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def classify_source(url: str, *, claim_text: str = "", provider: str = "", corpus: str = "",
                    subject_is_name: bool = False) -> str:
    """One of report.SourceType: official, academic, reference, primary, news, other.

    "primary" means the subject's own site: its domain spells one of the names in
    `claim_text` (see subject_names; `corpus` is the whole response, used to tell a
    name from a capitalized sentence opener). `subject_is_name` treats `claim_text`
    as a name outright (a competitor's name).
    """
    if provider == "openalex":
        return "academic"
    host = _host(url)
    domain = registrable_domain(host)
    labels = host.split(".")
    suffix = ".".join(labels[-2:])
    if host in ACADEMIC_HOSTS:
        return "academic"
    if labels[-1] in ("gov", "mil", "int") or domain in OFFICIAL_DOMAINS or suffix in OFFICIAL_SUFFIXES:
        return "official"
    if ((labels[-1] == "edu" and domain not in USER_CONTENT_EDU) or domain in ACADEMIC_DOMAINS
            or suffix in ACADEMIC_SUFFIXES):
        return "academic"
    if domain in REFERENCE_DOMAINS:
        return "reference"
    label = domain.split(".")[0].replace("-", "")
    names = [claim_text] if subject_is_name else subject_names(claim_text, corpus)
    if len(label) >= 4 and any(label in _domain_forms(name) for name in names):
        return "primary"
    if domain in NEWS_DOMAINS:
        return "news"
    return "other"


CORPORATE_WORDS = {"inc", "corp", "corporation", "co", "company", "ltd", "llc", "plc", "gmbh", "ag", "sa",
                   "group", "holdings", "labs", "technologies", "tech", "hq", "fund", "funds", "capital", "app",
                   "ai", "software", "systems", "solutions", "partners", "ventures"}


def _domain_forms(name: str) -> set[str]:
    """'Brindle Labs Inc' -> {'brindlelabsinc', 'brindlelabs', 'brindle', 'brindlehq', ...}: the
    whole name, the name without trailing corporate words, and the first word plus one corporate
    word ("meridianfunds" for "Meridian") — never a lone generic word ('dental' for 'Rival Dental')."""
    words = [w for w in (re.sub(r"[^a-z0-9]", "", w.casefold()) for w in name.split()) if w]
    if not words:
        return set()
    forms = {"".join(words)}
    while len(words) > 1 and words[-1] in CORPORATE_WORDS:
        words = words[:-1]
        forms.add("".join(words))
    if len(words) == 1:
        forms |= {words[0] + suffix for suffix in CORPORATE_WORDS}
    return forms


# --------------------------------------------------------------------------- #
# Passages
# --------------------------------------------------------------------------- #

# A sentence ends at . ! or ? plus whitespace, unless a lowercase letter follows ("prime vs.
# composite", "e.g. the"). The lookahead also refuses whitespace, so the space run cannot
# backtrack around it.
_BREAK = re.compile(r"(?<=[.!?])\s+(?![\sa-z])|\n+")


def split_passages(text: str, *, max_chars: int = 700) -> list[str]:
    """Group consecutive sentences into passages of at most max_chars.

    Each passage is text[start:end] for some start/end, never rebuilt, so a
    quote found inside a passage is also found, unchanged, in the source.
    """
    pieces = []
    start = 0
    bounds = [(m.start(), m.end()) for m in _BREAK.finditer(text)] + [(len(text), len(text))]
    for end, next_start in bounds:
        while end - start > max_chars:  # hard-split an overlong sentence at a space
            cut = text.rfind(" ", start, start + max_chars)
            cut = cut if cut > start else start + max_chars
            pieces.append((start, cut))
            start = cut
            while start < end and text[start].isspace():
                start += 1
        if end > start:
            pieces.append((start, end))
        start = next_start
    passages = []
    group = None
    for s, e in pieces:
        if group and e - group[0] <= max_chars:
            group = (group[0], e)
        else:
            if group:
                passages.append(text[group[0]:group[1]])
            group = (s, e)
    if group:
        passages.append(text[group[0]:group[1]])
    return [p for p in passages if p.strip()]


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[0-9]+(?:[.,][0-9]+)*|[^\W\d_]+", text.casefold())
            if len(t) >= 2 and t not in STOPWORDS]


def rank_passages(passages: list[str], query: str, *, top_k: int) -> list[str]:
    """Most query-relevant passages first; numbers and named entities weigh more."""
    wanted = set(_tokens(query))
    entities = {e.casefold() for e in key_entities(query)}
    scored = []
    for index, passage in enumerate(passages):
        overlap = wanted & set(_tokens(passage))
        if not overlap:
            continue
        score = sum(2.0 if any(ch.isdigit() for ch in t) else 1.5 if t in entities else 1.0
                    for t in overlap)
        scored.append((-score, index, passage))
    scored.sort()
    return [p for _, _, p in scored[:top_k]]


# --------------------------------------------------------------------------- #
# Untrusted text: injection screening, normalization, exact quotes
# --------------------------------------------------------------------------- #

_INJECTION = [re.compile(p, re.I) for p in (
    r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+)?(?:the\s+|previous\s+|prior\s+|above\s+)+"
    r"(?:\w+\s+){0,2}(?:instructions?|prompts?|rules?)\b",
    r"\byou\s+are\s+(?:now\s+)?(?:an?\s+)?(?:ai|assistant|chatgpt|language\s+model|llm)\b",
    r"\bsystem\s+prompt\b",
    r"\b(?:mark|label|rate|classify|treat)\s+(?:this|the|all|every|each)\s+(?:claims?|statements?|answers?)"
    r"\s+as\s+(?:true|supported|verified|correct|accurate)\b",
    r"\brespond\s+only\s+with\b",
    r"</?\s*(?:system|assistant|user)\s*>",
    r"\bBEGIN\s+(?:SYSTEM|INSTRUCTIONS)\b",
)]


def injection_markers(text: str) -> list[str]:
    """Instruction-like snippets found in untrusted text (empty when clean)."""
    return [m.group(0) for pattern in _INJECTION for m in pattern.finditer(text)]


_QUOTE_CHARS = {"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
                "“": '"', "”": '"', "„": '"', "″": '"', "«": '"', "»": '"'}
_DASH_CHARS = set("‐‑‒–—―−")


def _normalized_with_map(text: str) -> tuple[str, list[int]]:
    """Normalized text plus, for each normalized character, its index in `text`."""
    out: list[str] = []
    origin: list[int] = []
    pending_space = False
    for index, char in enumerate(text):
        for c in unicodedata.normalize("NFKC", char):
            c = "-" if c in _DASH_CHARS else _QUOTE_CHARS.get(c, c)
            for folded in c.casefold():
                if folded.isspace():
                    pending_space = bool(out)
                    continue
                if pending_space:
                    out.append(" ")
                    origin.append(index)
                    pending_space = False
                out.append(folded)
                origin.append(index)
    return "".join(out), origin


def normalize_for_match(text: str) -> str:
    return _normalized_with_map(text)[0]


def find_quote(passage: str, quote: str) -> str | None:
    """The exact slice of `passage` that `quote` refers to, or None.

    Tolerates case, whitespace, quote/dash style and wrapping quote marks or
    ellipses; never tolerates different words.
    """
    candidate = (quote or "").strip().strip("\"'“”‘’«»").strip()
    candidate = re.sub(r"^(?:\.{3}|…)\s*|\s*(?:\.{3}|…)$", "", candidate)
    if not candidate:
        return None
    needle = normalize_for_match(candidate)
    haystack, origin = _normalized_with_map(passage)
    if len(needle) < 8 and needle != haystack:
        return None
    at = haystack.find(needle)
    if at < 0:
        return None
    return passage[origin[at]:origin[at + len(needle) - 1] + 1]


# --------------------------------------------------------------------------- #
# Numbers, years, entities
# --------------------------------------------------------------------------- #

_SCALE = {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6, "mn": 1e6, "mm": 1e6,
          "billion": 1e9, "b": 1e9, "bn": 1e9, "trillion": 1e12, "t": 1e12, "tn": 1e12}
_NUMBER = re.compile(
    r"(?<![\w.,])(?P<cur>[$€£₹]\s?)?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?"
    r"(?:(?P<pct>\s?%|\s?percent\b|\s?per cent\b)"
    r"|(?P<tight>bn|mn|tn|[kmbt])\b|\s(?P<word>thousand|million|billion|trillion|bn|mn|tn)\b)?",
    re.I,
)
# "FY2023" and "CY2024" are years too.
_YEAR = re.compile(r"(?<![\w.,$€£₹])(?:[Ff][Yy]|[Cc][Yy])?(1[6-9]\d{2}|20\d{2})(?![\w%]|[.,]\d)")
_UNITS = ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
          "sixteen seventeen eighteen nineteen").split()
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
         "ninety": 90}
_WORD_SCALES = {"hundred": 1e2, "thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
# "three", "twenty-five", "nine thousand", "a million"; a bare "one" or "a" is not a number.
_WORD_NUMBER = re.compile(
    r"\b(?:(?P<tens>" + "|".join(_TENS) + r")(?:[\s-](?P<unit>" + "|".join(_UNITS[:9]) + r"))?"
    r"|(?P<small>" + "|".join(_UNITS[1:]) + r")"
    r"|(?:one|a)(?=\s+(?:hundred|thousand|million|billion|trillion)\b))"
    r"(?:\s+(?P<scale>hundred|thousand|million|billion|trillion))?\b", re.I)


def _strip_markers(text: str) -> str:
    return re.sub(r"\[\d+\]", " ", text)


def numbers_in(text: str) -> list[float]:
    """Numeric values with scale words applied ("$50 billion" -> 5e10, "3.5%" -> 3.5, "nine thousand" -> 9000).

    Bare years are excluded (see years_in); citation markers like [1] are ignored.
    """
    text = _strip_markers(text)
    values = []
    for m in _NUMBER.finditer(text):
        raw = m.group("int").replace(",", "") + (m.group("dec") or "")
        value = float(raw)
        scale = (m.group("tight") or m.group("word") or "").lower()
        # "2015" is a year; "2,015" (with a thousands separator) is a quantity.
        is_year = (not m.group("cur") and not m.group("dec") and not m.group("pct") and not scale
                   and "," not in m.group("int") and len(raw) == 4 and 1600 <= value <= 2099)
        if is_year:
            continue
        values.append(value * _SCALE.get(scale, 1.0))
    for m in _WORD_NUMBER.finditer(text):
        if m.group("tens"):
            value = _TENS[m.group("tens").lower()] + (_UNITS.index(m.group("unit").lower()) + 1 if m.group("unit") else 0)
        elif m.group("small"):
            value = _UNITS.index(m.group("small").lower()) + 1
        else:
            value = 1
        values.append(value * _WORD_SCALES.get((m.group("scale") or "").lower(), 1.0))
    return values


def years_in(text: str) -> list[int]:
    return [int(y) for y in _YEAR.findall(_strip_markers(text))]


# Shared by the evidence and citation engines.
QUOTED = re.compile(r"[\"“]([^\"”\n]{12,400})[\"”]")  # a quotation inside a claim
STRONG = re.compile(r"\b(?:proves?|proven|cures?|guarantees?|eliminates?|always|definitely|causes?|"
                    r"confirms?)\b|100%", re.I)
HEDGE = re.compile(r"\b(?:may|might|could|suggests?|associated|linked|correlat\w*|preliminary|pilot|"
                   r"in mice|small (?:study|sample|trial)|observational|possibl[ey]|potential(?:ly)?)\b", re.I)
QUALIFIER_WORDS = {"current", "currently", "now", "today", "latest", "recent", "recently", "actually",
                   "really", "also", "very", "said", "says"}

_ENTITY = re.compile(r"\b(?:[A-Z]{2,}[a-z]?|[A-Z][a-zA-Z0-9&'’-]*[a-zA-Z0-9])\b")


def key_entities(text: str) -> list[str]:
    """Capitalized words and acronyms, in order, without common sentence starters."""
    found: list[str] = []
    for m in _ENTITY.finditer(text):
        word = m.group(0)
        if word not in ENTITY_STOPWORDS and word not in found:
            found.append(word)
    return found


# Capitalized words that never name a claim's subject: sentence openers, titles, roles,
# periods and metric/sector acronyms. ponytail: an English list; extend it when a real
# response trips it (the cost of a miss is an UNVERIFIED verdict, not a false one).
NOT_NAMES = set("""
today currently recently historically overall however also additionally furthermore moreover meanwhile
notably importantly generally typically usually studies study research researchers experts scientists
doctors analysts reports data according based despite although while since after before during yes no
here there now then so thus therefore later earlier first second third finally next most many some
several all every each both these those such other another his her their its our your my you
between during among across against around through throughout within without under over above below
beyond toward towards upon via per unlike like besides because when where why how what which who whose
whether if unless until once though even only just still yet instead tomorrow yesterday from with into
mr mrs ms dr prof sir st ceo cfo cto coo cmo cio vp svp evp
ai api saas b2b b2c arr mrr gmv roi kpi ipo llm gpu cpu gdp cagr yoy eps ebitda tam sam som
fy q1 q2 q3 q4 h1 h2
""".split())
ALIASES = {"us": ("united states", "u.s.", "usa"), "usa": ("united states", "u.s."),
           "uk": ("united kingdom", "britain", "u.k."), "eu": ("european union",), "un": ("united nations",),
           "uae": ("united arab emirates",)}


def names_in(text: str) -> list[str]:
    """The key entities that can name a subject: possessives off, openers/titles/acronyms out."""
    names: list[str] = []
    for entity in key_entities(text):
        name = re.sub(r"['’]s$", "", entity)
        if name.casefold() not in NOT_NAMES and name not in names:
            names.append(name)
    return names


def mentions(text: str, name: str) -> bool:
    """Whole-word, case-insensitive: "Acme" is not in "Acmeticals", "US" is not in "Thus"."""
    haystack = text.casefold()
    forms = (name.casefold(),) + ALIASES.get(name.casefold(), ())
    return any(re.search(rf"(?<!\w){re.escape(form)}(?!\w)", haystack) for form in forms)


_NAME_RUN = re.compile(r"(?<![\w&'’-])[A-Z][\w&'’-]*(?:[ \t]+[A-Z][\w&'’-]*){0,3}")


def _at_sentence_start(text: str, index: int) -> bool:
    before = text[max(0, index - 40):index].rstrip(" \t\"'“‘(")
    if index <= 40 and not text[:index].strip(" \t\"'“‘("):
        return True
    return not before or before[-1] in ".!?:;\n" or bool(re.search(r"\n\s*(?:[-*•]|\d{1,3}[.)])$", before))


def _used_as_name(word: str, corpus: str) -> bool:
    """Never written in lowercase in `corpus` (URLs, emails and domains aside), and used as a
    name — capitalized mid-sentence or at least twice: "Kelpcore" on kelpcore.com, but not
    "Health" (health.com writes "health" all over) or a lone "Coffee prices rose."."""
    found = list(re.finditer(rf"(?<![\w@./-]){re.escape(word)}(?![\w-]|\.[a-z])", corpus, re.I))
    return (bool(found) and all(m.group(0)[0].isupper() for m in found)
            and (len(found) >= 2 or any(not _at_sentence_start(corpus, m.start()) for m in found)))


def subject_names(text: str, corpus: str = "") -> list[str]:
    """Names that can identify a subject's own website.

    A name is a run of capitalized words that is multi-word ("Brindle Labs"), written with
    inner capitals or digits ("NovaLedger", "IBM", "3M"), or used as a name in `corpus` (the
    response plus the page: capitalized mid-sentence and never lowercase). A word capitalized
    only because it opens a sentence ("Health insurance costs rose") is not a name:
    health.com is not its site.
    """
    corpus = corpus or text
    found: list[str] = []
    for m in _NAME_RUN.finditer(text):
        tokens = [(m.start() + t.start(), re.sub(r"['’]s$", "", t.group(0))) for t in re.finditer(r"\S+", m.group(0))]
        while tokens and (tokens[0][1] in ENTITY_STOPWORDS or tokens[0][1].casefold() in NOT_NAMES):
            tokens.pop(0)
        if not tokens:
            continue
        start, first = tokens[0]
        distinctive = (len(tokens) > 1 or re.search(r"[A-Z0-9]", first[1:])
                       or not _at_sentence_start(text, start) or _used_as_name(first, corpus))
        name = " ".join(word for _, word in tokens)
        if distinctive and name not in found:
            found.append(name)
    return found


_DELIMITER = re.compile(r"<(?=\s*/?\s*(?:passage|question|response|claims?|context|documents?|system|assistant"
                        r"|user|instructions?)\b)", re.I)


def fence(text: str) -> str:
    """Untrusted text cannot open or close the tags that delimit it in a prompt (any case or spacing)."""
    return _DELIMITER.sub("‹", text)
