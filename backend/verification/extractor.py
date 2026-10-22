"""Bounded English rule baseline, never an evidence source or LLM judge.

The API has one primary category, so category order is an annotation policy,
not a probability: private experience, inference, prediction, opinion, changing
fact, calculation, historical event, science, universal, comparison, business,
quantity, factual. Domain claims keep their domain when they contain a number;
scientific universals remain scientific and retain their universal qualifier.
Subjective framing does not make an embedded objective assertion uncheckable.

shortcut: lexical rules cannot resolve arbitrary syntax; replace this adapter
with a separately evaluated structured extractor before a reliability claim.
"""

import re
from typing import Protocol

from backend.verification.schemas import (
    CandidateBatch,
    ClaimCandidate,
    ClaimType,
    OmittedSegment,
    Scope,
    TextSpan,
)


class ClaimExtractor(Protocol):
    method: str

    def extract(self, text: str) -> CandidateBatch: ...


_VERBS = r"(?:(?:is|are|was|were|has|have|had|does|do|did|ca|wo|could|should|would|must)n['’]t|is|are|was|were|has|have|had|does|do|did|can|cannot|will|would|should|must|may|might|could|generates?|offers?|costs?|grew|grows?|rose|fell|increased?|decreased?|supports?|contains?|employs?|operates?|provides?|launched?|founded|equals?|requires?|reduces?|improves?|outperforms?|earns?|makes?|made|sells?|sold|serves?|uses?|used|raised|reported|reports?|reached|reaches|accounts?|process(?:es)?|includes?|excludes?|loves?|likes?|prefers?|thinks?|believes?|looks?|seems?|feels?|works?|runs?|stores?|collects?|exports?|saves?|handles?)"
_PREDICATE = re.compile(rf"^{_VERBS}\b", re.I)
_FINITE = re.compile(rf"\b{_VERBS}\b", re.I)
_JOIN = re.compile(r",(?!\d)\s*(?:(?:and|but)\s+)?|\s+(?:and|but|whereas|while)\s+", re.I)
_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "inc", "ltd", "vs", "e.g", "i.e", "u.s", "u.k"}
_DATES = re.compile(r"\b(?:1[6-9]\d{2}|20\d{2})(?:-\d{2}(?:-\d{2})?)?\b|\b(?:today|currently|yesterday|tomorrow|this year|next year)\b", re.I)
_QUALIFIERS = re.compile(r"\b(?:always|never|guaranteed|no competitors|not|no|cannot|all|every|none|only|approximately|about|roughly|at least|at most|up to|may|might|could|will|would|likely|possibly|reportedly|allegedly|according to|if|unless|provided that|assuming)\b|\b\w+n['’]t\b", re.I)
_GEO = re.compile(r"\b(?:United States|United Kingdom|European Union|Europe|North America|South America|Asia|Africa|Australia|India|China|Japan|Canada|Germany|France|US|USA|UK|EU|globally|worldwide)\b")
_LOGICAL = re.compile(r"\b(?:therefore|implies|it follows|hence|if|unless|provided that|assuming that|only when)\b", re.I)
_REQUEST = re.compile(r"^(?:please\b|(?:could|would|can|will) you\b|(?:tell|show|give) me\b|(?:do not|don't)\b|(?:ignore|consider|imagine|assume|compare|list|explain|describe|summarize|summarise|calculate|verify|include|find|check|provide)\b)", re.I)
_CITATION_ONLY = re.compile(r"^(?:\[\d+\]\s*:?\s*)?(?:(?:https?://|www\.)\S+|<https?://[^>]+>|\[[^\]]+\]\(https?://[^)]+\))\.?$", re.I)
_FRAMING = re.compile(r"^(?:i (?:think|believe)(?: that)?|you(?:['’]re| are) (?:absolutely )?right that)\s+", re.I)
_MODAL = re.compile(r"\b(?:may|might|could|will|would|can|must|should)\b", re.I)


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and (text[end - 1].isspace() or text[end - 1] in ".!?;,:"):
        end -= 1
    return start, end


def _sentences(text: str, start: int, end: int):
    cursor = start
    for match in re.finditer(r"[.!?](?=\s|$)|\n+|;", text[start:end]):
        boundary = start + match.start()
        if text[boundary] == ".":
            line_start = text.rfind("\n", 0, boundary) + 1
            if re.fullmatch(r"\s*\d+", text[line_start:boundary]):
                continue  # A numbered-list marker is not a sentence.
            token = re.search(r"[\w.]+$", text[cursor:boundary])
            if token and token.group().lower() in _ABBREVIATIONS:
                continue
        yield cursor, boundary + (1 if text[boundary] in ".!?" else 0)
        cursor = start + match.end()
    if cursor < end:
        yield cursor, end


def _atomic_spans(text: str, start: int, end: int):
    """Split coordinated predicates, but keep noun lists and joint subjects."""
    sentence = text[start:end]
    # Dropping a condition or premise can turn a qualified assertion into an
    # unconditional one. Keep dependent logic intact for a specialist engine.
    if _LOGICAL.search(sentence) or re.search(r"\b(?:either|neither|or|nor)\b", sentence, re.I):
        yield start, end
        return
    cursor = start
    for match in _JOIN.finditer(text, start, end):
        left = text[cursor:match.start()]
        right = text[match.end():end]
        # A clause on the left and a predicate / subject+verb on the right
        # prevents splitting 'research and development' or 'Alice and Bob'.
        right_clause = bool(_PREDICATE.search(right))
        subject_verb = _FINITE.search(right)
        if subject_verb and 0 < subject_verb.start() <= 65:
            prefix = right[:subject_verb.start()].strip()
            right_clause = right_clause or bool(
                re.fullmatch(r"[\w$'’ -]{1,65}", prefix)
                and len(prefix.split()) <= 7
            )
        # Commas introducing relative clauses/qualifiers are not conjunctions.
        if re.match(r"(?:which|who|whose|when|where|although|because|if|according|that)\b", right, re.I):
            right_clause = False
        if _FINITE.search(left) and right_clause:
            yield _trim(text, cursor, match.start())
            cursor = match.end()
    yield _trim(text, cursor, end)


# Praise with no yardstick is opinion: "the best analytics tool", "an amazing team". Measurable
# superlatives stay checkable ("best-selling", "the fastest", "the cheapest", "the largest").
# ponytail: word list, not a model; a ranked "best" ("best university in the QS ranking") reads
# as opinion too, which errs toward NOT CHECKABLE rather than toward a verdict.
_OPINION = re.compile(
    r"\b(?:i (?:feel|prefer|love|hate)|in my opinion|beautiful|delicious|wonderful|brilliant|genius"
    r"|you(?:'re| are) (?:absolutely )?right|should|ought to|best idea"
    r"|amazing|awesome|excellent|fantastic|incredible|outstanding|superb|stunning|world-class|greatest|finest"
    r"|(?:the|our|its|their|your) (?:very )?(?:best|worst)(?![- ](?:selling|sellers?|known|performing|rated|ranked)))\b")


def _classify(text: str) -> tuple[ClaimType, bool]:
    t = _FRAMING.sub("", text.lower())
    if re.search(r"\b(?:i (?:secretly )?(?:imagined|dreamed|dreamt)|my (?:dream|private thoughts)|secret thoughts|private thoughts|unobservable|unknowable)\b", t):
        return ClaimType.not_independently_checkable, False
    if _LOGICAL.search(t):
        return ClaimType.logical, True
    if re.search(r"\b(?:will|predicts?|forecasts?|next year|tomorrow)\b", t):
        return ClaimType.predictive, False
    if _OPINION.search(t):
        return ClaimType.subjective_normative, False
    if re.search(r"\b(?:currently|today|latest|current|now)\b", t) or (
        re.search(r"\b(?:ceo|president|prime minister|exchange rate)\b", t)
        and re.search(r"\b(?:is|are)\b", t)
    ):
        return ClaimType.time_sensitive, True
    if re.search(r"\d\s*(?:[+*/=×÷]|-(?=\s*\d))|\b(?:equals?|multiplied by|divided by)\b|\d\s*(?:%|percent)\s+of\b", t):
        return ClaimType.numerical, True
    if re.search(r"\b(?:founded|born|died|launched|invented|discovered|established)\b", t):
        return ClaimType.historical, True
    if re.search(r"\b(?:study|studies|research|trial|scientific|gravity|water|cells|protein|vaccine|temperature|boils|treatment|cancer|clinical)\b", t):
        return ClaimType.scientific, True
    if re.search(r"\b(?:no (?:\w+\s+){0,3}(?:competitors?|companies|one|evidence)|never|always|every|all|none|guaranteed|only)\b", t):
        return ClaimType.negative_universal, True
    if re.search(r"\b(?:more than|less than|faster|slower|better|worse|largest|smallest|compared|than|outperforms?)\b", t):
        return ClaimType.comparative, True
    if re.search(r"\b(?:market|competitors?|startups?|customers?|revenue|profit|business|companies|sales)\b|\b(?:generates?|earns?|earned|raised)\s+[$€£]", t):
        return ClaimType.business_market, True
    # Years and citation indices do not make an otherwise factual claim a
    # calculation. Quantities still use a heuristic primary category.
    without_labels = re.sub(r"\[\d+\]|\b(?:1[6-9]\d{2}|20\d{2})(?:-\d{2}(?:-\d{2})?)?\b", "", t)
    if re.search(r"\d|\b(?:percent|million|billion|twice|half)\b", without_labels):
        return ClaimType.numerical, True
    return ClaimType.factual, True


def _omission_reason(sentence: str, *, question: bool) -> str | None:
    if question:
        return "Question omitted; embedded assumptions may still require review."
    if _CITATION_ONLY.fullmatch(sentence):
        return "Standalone citation reference omitted; this is not citation validation."
    if _REQUEST.match(sentence):
        return "Request or instruction omitted; no factual assertion was extracted."
    # An equation made only of digits and symbols ("2 + 2 = 5") is still a claim.
    if re.fullmatch(r"[\W\d_]+", sentence) and not re.search(r"\d\s*[=<>≈]\s*-?\d", sentence):
        return "Presentation marker or isolated number omitted; review for missing context."
    if not _FINITE.search(sentence) and not re.search(r"\d|[=<>]", sentence):
        if len(sentence.split()) < 4 or sentence.endswith(":"):
            return "Short fragment may be a heading; review for missed claims."
    return None


class RuleClaimExtractor:
    method = "rules-v1"

    def extract(self, text: str) -> CandidateBatch:
        claims = []
        omissions = []
        regions = []
        cursor = 0
        # Fenced code is data, never executed; acknowledge its exclusion.
        for fence in re.finditer(r"```[\s\S]*?(?:```|$)", text):
            regions.append((cursor, fence.start()))
            omissions.append(OmittedSegment(
                text_span=TextSpan(start=fence.start(), end=fence.end()),
                reason="Code block skipped; code correctness is outside this extractor.",
            ))
            cursor = fence.end()
        regions.append((cursor, len(text)))
        for region_start, region_end in regions:
            for start, end in _sentences(text, region_start, region_end):
                raw = text[start:end].strip()
                if not raw or raw.endswith("?"):
                    continue
                # Strip presentation markers without changing original offsets.
                prefix = re.match(r"\s*(?:(?:[-*+#>]\s+)|(?:\d+[.)]\s+))*", text[start:end])
                start += prefix.end()
                start, end = _trim(text, start, end)
                if end <= start:
                    continue
                sentence = text[start:end]
                # Requests, standalone citations and headings are not claims, but
                # stay visible as omissions instead of silently disappearing.
                reason = _omission_reason(sentence, question=False)
                if reason:
                    omissions.append(OmittedSegment(text_span=TextSpan(start=start, end=end), reason=reason))
                    continue
                for a, b in _atomic_spans(text, start, end):
                    if a >= b:
                        continue
                    exact = text[a:b]
                    claim_type, checkable = _classify(exact)
                    limits = []
                    if a > start:
                        limits.append("This clause may inherit its subject and qualifiers from the original context.")
                    if re.search(r"\b(?:and|but|whereas|while)\b", exact, re.I):
                        limits.append("A remaining conjunction may contain additional claims; review atomicity.")
                    claims.append(ClaimCandidate(
                        exact_text=exact, text_span=TextSpan(start=a, end=b),
                        claim_type=claim_type, context=sentence,
                        qualifiers=list(dict.fromkeys(_QUALIFIERS.findall(exact))),
                        scope=Scope(dates=list(dict.fromkeys(_DATES.findall(exact))),
                                    geographical_scope=list(dict.fromkeys(_GEO.findall(exact)))),
                        objectively_checkable=checkable, limitations=limits,
                    ))
        return CandidateBatch(claims=claims, omitted_segments=omissions)
