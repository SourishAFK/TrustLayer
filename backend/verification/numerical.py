"""Engine E (numbers): deterministic checks of the arithmetic a claim asserts.

Never eval/exec: numbers are parsed by hand and expressions are evaluated by a
tiny recursive-descent parser. Checked: explicit arithmetic, percent-of,
percent change, multiples, unit conversions and startup runway.

A calculation is "pure" only when the claim holds nothing but the math, so the
math alone can settle it ("20% of 150 is 30" -> SUPPORTED or CONTRADICTED).
Anything about a company or market is not pure: a consistent calculation then
only says the arithmetic adds up, never that the figures are true. A fragment
that borrows its inputs from the surrounding sentence ("an increase of 80%"
after "grew from $20M to $30M") is never pure either.
"""

import logging
import math
import re
import time
from dataclasses import dataclass

from backend.verification.contracts import Findings, RunContext
from backend.verification.report import Calculation, CheckRecord, EngineRun
from backend.verification.schemas import Claim

logger = logging.getLogger(__name__)
WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100, "thousand": 1000,
}
SCALES = {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6, "mm": 1e6, "mn": 1e6,
          "billion": 1e9, "b": 1e9, "bn": 1e9, "trillion": 1e12, "t": 1e12, "tn": 1e12}
_WORDS = "|".join(sorted(WORD_NUMBERS, key=len, reverse=True))
_N = r"\d+(?:,\d{3})*(?:\.\d+)?"
_NW = rf"(?:{_N}|\b(?:{_WORDS})\b)"
# A quantity: optional currency, a number, an optional scale ("$2.5 million", "$400k").
_Q = rf"[$€£₹]?\s?{_N}(?:\s?(?:thousand|million|billion|trillion|bn|mn|tn)\b|[kKmMbB]\b)?"
_VERB = (r"(?:\s*[=≈~]\s*|\s+(?:equals|is equal to|is|are|makes|gives|comes to)"
         r"(?:\s+(?:about|roughly|approximately|around|nearly|almost))?\s+)")
# Whitespace belongs only to operators and verbs (never to operands), and an expression has at
# most 12 operators: the pattern stays linear ("1 + 2 + ... + 14 is long" used to backtrack for
# minutes). "-" and "x" also write ranges and dimensions ("aged 18 - 24", "a 2 x 4"), so they
# count only in an equation with "="; "/" needs spaces ("24/7" is not a division).
_OPERAND = rf"(?:(?:\(\s*){{1,3}}[-−]?)?{_N}(?:\s*\)){{0,3}}"  # evaluate() rejects unbalanced parentheses
_OP_ANY = r"(?:\s*[+*^×÷]\s*|\s+/\s+|\s+(?:plus|minus|times|multiplied by|divided by)\s+)"
_OP_EQ = rf"(?:{_OP_ANY}|\s+[-−x]\s+)"
# A stated result may carry a scale word ("= 4 million"); a letter or another operation right
# after it ("= 4m", "is 2160p", "is 1.5 x 3.5") makes the statement ambiguous, so it is skipped.
_STATED = (rf"(?P<stated>[-−]?{_N}(?:\s?(?:thousand|million|billion|trillion|bn|mn|tn)\b)?)"
           r"(?![\w.,]*\d|\s?%|[a-zA-Z]|\s*[-−+*/^×÷x]\s*\d)")
_START = r"(?<![\w.$€£₹,%/\-−])"
_SIGN = r"(?:[-−](?=\d))?"  # only when attached ("-3"), never a markdown bullet ("- 3")
ARITHMETIC = (
    re.compile(rf"{_START}(?P<expr>{_SIGN}{_OPERAND}(?:{_OP_EQ}{_OPERAND}){{1,12}})\s*=\s*{_STATED}", re.I),
    re.compile(rf"{_START}(?P<expr>{_SIGN}{_OPERAND}(?:{_OP_ANY}{_OPERAND}){{1,12}})"
               rf"\s+(?:equals|is equal to|is|are|makes|gives|comes to)\s+{_STATED}", re.I),
)
PERCENT_OF = re.compile(
    rf"(?P<p>{_N})\s?(?:%|percent)\s+of\s+(?P<base>{_Q}){_VERB}(?P<stated>{_Q})(?!\s?%)", re.I)
PERCENT_OF_REVERSED = re.compile(
    rf"(?P<stated>{_Q})\s+(?:is|are|equals|=)\s+(?P<p>{_N})\s?(?:%|percent)\s+of\s+(?P<base>{_Q})", re.I)
# "from 80 units to 100 units", "from $12 million in 2024 to $18 million in 2025": an optional
# unit word and an optional "in <year>" after each quantity.
_IN_YEAR = r"(?:\s+in\s+(?:FY\s?)?(?:1[6-9]|20)\d{2})?"
FROM_TO = re.compile(rf"\bfrom\s+(?P<a>{_Q})(?:\s+[a-z]+)?{_IN_YEAR}\s+to\s+(?P<b>{_Q}){_IN_YEAR}", re.I)
CHANGE = (
    re.compile(rf"\b(?:an?\s+)?(?P<dir>increase|growth|rise|jump|gain|decline|decrease|drop|fall|reduction)"
               rf"\s+of\s+(?P<p>{_N})\s?(?:%|percent)", re.I),
    re.compile(rf"(?P<p>{_N})\s?(?:%|percent)\s+(?P<dir>increase|growth|rise|jump|gain|decline|decrease|drop|"
               rf"fall|reduction|higher|lower)", re.I),
    re.compile(rf"\b(?P<dir>grew|rose|increased|jumped|climbed|gained|fell|declined|dropped|decreased|shrank|up|down)"
               rf"\s+(?:by\s+)?(?P<p>{_N})\s?(?:%|percent)", re.I),
    re.compile(rf"\(\s*(?P<dir>[+\-−])\s*(?P<p>{_N})\s?%\s*\)"),
)
UP = {"increase", "growth", "rise", "jump", "gain", "higher", "grew", "rose", "increased", "jumped",
      "climbed", "gained", "up", "+"}
MULTIPLE_WORDS = {"doubled": 2.0, "tripled": 3.0, "trebled": 3.0, "quadrupled": 4.0, "halved": 0.5}
# The gap is bounded (linear on "doubled doubled ...") and may not cross a comma; a gap that
# introduces another subject ("doubled while prices went from ...") is rejected in _find.
MULTIPLE = (
    re.compile(rf"\b(?P<w>doubled|tripled|trebled|quadrupled|halved)\b(?P<gap>[^.;,]{{0,60}}?)\bfrom\s+(?P<a>{_Q})"
               rf"\s+to\s+(?P<b>{_Q})", re.I),
    re.compile(rf"\b(?:grew|rose|increased|jumped|expanded)\s+(?P<n>{_N})\s?(?:x|×|-fold|fold)\s+from\s+(?P<a>{_Q})"
               rf"\s+to\s+(?P<b>{_Q})", re.I),
)
CASH = re.compile(rf"(?P<cash>{_Q})\s+(?:in\s+(?:the\s+)?bank|in\s+cash|of\s+cash|cash\b|in\s+reserves)"
                  rf"|\bcash(?:\s+on\s+hand)?\s+of\s+(?P<cash2>{_Q})", re.I)
BURN = re.compile(rf"(?P<burn>{_Q})\s+(?:monthly\s+burn|burn\s+(?:rate\s+)?(?:per|a)\s+month|(?:per|a)\s+month)"
                  rf"|\b(?:monthly\s+)?burn(?:\s+rate)?\s+of\s+(?P<burn2>{_Q})", re.I)
RUNWAY = re.compile(rf"(?P<stated>{_N})\s+months?\s+of\s+runway|\brunway\s+of\s+(?P<stated2>{_N})\s+months?", re.I)

# Unit conversion: (dimension, factor to the base unit). Data units list every
# accepted factor so both decimal (1000) and binary (1024) readings count.
_UNITS = {
    "mm": ("length", [0.001]), "cm": ("length", [0.01]), "m": ("length", [1.0]), "km": ("length", [1000.0]),
    "in": ("length", [0.0254]), "ft": ("length", [0.3048]), "yd": ("length", [0.9144]),
    "mi": ("length", [1609.344]),
    "mg": ("mass", [1e-6]), "g": ("mass", [1e-3]), "kg": ("mass", [1.0]), "t": ("mass", [1000.0]),
    "oz": ("mass", [0.028349523125]), "lb": ("mass", [0.45359237]),
    "ml": ("volume", [0.001]), "l": ("volume", [1.0]), "gal": ("volume", [3.785411784]),
    "s": ("time", [1.0]), "min": ("time", [60.0]), "h": ("time", [3600.0]), "day": ("time", [86400.0]),
    "week": ("time", [604800.0]),
    "byte": ("data", [1.0]), "kb": ("data", [1e3, 1024.0]), "mb": ("data", [1e6, 1024.0 ** 2]),
    "gb": ("data", [1e9, 1024.0 ** 3]), "tb": ("data", [1e12, 1024.0 ** 4]), "kib": ("data", [1024.0]),
    "mib": ("data", [1024.0 ** 2]), "gib": ("data", [1024.0 ** 3]), "tib": ("data", [1024.0 ** 4]),
    "km/h": ("speed", [1000 / 3600]), "mph": ("speed", [1609.344 / 3600]),
    "c": ("temperature", []), "f": ("temperature", []), "kelvin": ("temperature", []),
}
_ALIASES = {
    "millimeter": "mm", "millimetre": "mm", "centimeter": "cm", "centimetre": "cm", "meter": "m",
    "metre": "m", "kilometer": "km", "kilometre": "km", "inch": "in", "inches": "in", "foot": "ft",
    "feet": "ft", "yard": "yd", "mile": "mi", "milligram": "mg", "gram": "g", "kilogram": "kg",
    "tonne": "t", "ounce": "oz", "pound": "lb", "lbs": "lb", "milliliter": "ml", "millilitre": "ml",
    "liter": "l", "litre": "l", "gallon": "gal", "second": "s", "sec": "s", "secs": "s",
    "minute": "min", "mins": "min", "hour": "h", "hr": "h", "hrs": "h", "days": "day", "weeks": "week",
    "bytes": "byte", "kph": "km/h", "°c": "c", "°f": "f", "celsius": "c", "fahrenheit": "f",
    "degrees celsius": "c", "degrees fahrenheit": "f",
}
_UNIT_WORDS = sorted(set(_UNITS) | set(_ALIASES) | {a + "s" for a in _ALIASES if a.isalpha() and len(a) > 3},
                     key=len, reverse=True)
_U = "(?:" + "|".join(re.escape(u) for u in _UNIT_WORDS) + ")"
CONVERSION = re.compile(
    rf"(?<![\w.\-−])(?P<n>[-−]?{_N}|\b(?:{_WORDS})\b)\s*(?P<u1>{_U})(?![\w/])\s*(?:=|≈|~|equals|is equal to|"
    rf"is the same as|converts to|is(?:\s+(?:about|roughly|approximately|around))?)\s*(?P<stated>[-−]?{_N})\s*"
    rf"(?P<u2>{_U})(?![\w/])", re.I)
# Between a from–to and the percent change describing it: punctuation, an optional unit word or
# period ("units", "in 2023") and connectors only — not another subject ("and headcount rose 15%").
_GAP = re.compile(
    r"(?:\s+[a-z]{1,15}\b)?(?:\s+(?:in|by|during|over|since)\s+[\w-]{1,15}(?:\s+\d{4})?)?[\s,;:(\[—–-]*"
    r"(?:(?:which|that)\s+(?:is|was|represents?|marks?|means)\s+|or\s+|i\.e\.,?\s+|representing\s+|marking\s+"
    r"|for\s+|up\s+|down\s+)?(?:an?\s+)?", re.I)
_OTHER_SUBJECT = re.compile(r"\b(?:while|whereas|and|but|as|although)\b", re.I)

FILLER = {"is", "are", "equals", "equal", "to", "of", "the", "a", "an", "makes", "gives", "comes", "plus",
          "minus", "times", "multiplied", "divided", "by", "about", "roughly", "approximately", "around",
          "exactly", "same", "as", "converts", "percent", "degrees", "x"} | set(WORD_NUMBERS)
ARITHMETIC_ONLY = "This checks the arithmetic only; the input figures were not independently verified."


@dataclass
class Quantity:
    value: float
    decimals: int
    scale: float
    scale_text: str
    currency: str
    trailing_zeros: int = 0  # "247,000" -> 3: read as rounded to the thousand when rounding is allowed


def parse_quantity(raw: str) -> Quantity | None:
    m = re.fullmatch(rf"\s*(?P<sign>[-−])?\s?(?P<cur>[$€£₹])?\s?(?P<num>{_N}|{_WORDS})\s?"
                     r"(?P<scale>thousand|million|billion|trillion|bn|mn|mm|tn|[kmbt])?\s*", raw, re.I)
    if not m:
        return None
    num = m.group("num")
    value = float(WORD_NUMBERS[num.lower()]) if num.isalpha() else float(num.replace(",", ""))
    if m.group("sign"):
        value = -value
    scale_text = m.group("scale") or ""
    scale = SCALES.get(scale_text.lower(), 1.0)
    decimals = len(num.split(".")[1]) if "." in num else 0
    digits = "" if num.isalpha() or decimals else num.replace(",", "")
    return Quantity(value * scale, decimals, scale, scale_text, m.group("cur") or "",
                    len(digits) - len(digits.rstrip("0")))


def _consistent(stated: Quantity, computed: float, *, rounded: bool = True, relative: bool = True) -> bool:
    """Equal at the stated precision and, when `relative`, never more than 10% off.

    "1 inch is 3 cm" (2.54) and "20% of 8 is 2" (1.6) are wrong even though they round.
    With `rounded`, an integer written with trailing zeros reads as rounded at its last non-zero
    digit ("247,000", "300 million"); explicit equations use the literal precision, so
    "1000 + 5 = 1000" fails. Temperatures turn `relative` off (their zero is arbitrary).
    """
    diff = abs(stated.value - computed)
    if diff <= 1e-9 * max(1.0, abs(computed)):
        return True
    unit = 10.0 ** (stated.trailing_zeros if rounded and not stated.decimals else -stated.decimals)
    return diff <= 0.5 * unit * stated.scale * (1 + 1e-9) and (not relative or diff <= 0.1 * abs(computed))


def _tolerance(stated: Quantity, *, rounded: bool = True, relative: bool = True) -> str:
    unit = 10.0 ** (stated.trailing_zeros if rounded and not stated.decimals else -stated.decimals)
    text = f"±{_number(0.5 * unit * stated.scale)} (rounding of the stated value)"
    return text + (", at most 10% of the computed value" if relative else "")


def _number(value: float) -> str:
    text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _like(value: float, stated: Quantity, suffix: str = "") -> str:
    """Format `value` the way the stated quantity was written ($2.5M, 30%, 8 km)."""
    if not stated.scale_text or abs(value) < stated.scale / 1000:  # 4 is not "0 million"
        return f"{stated.currency}{_number(value)}{suffix}"
    gap = " " if len(stated.scale_text) > 1 else ""
    return f"{stated.currency}{_number(value / stated.scale)}{gap}{stated.scale_text}{suffix}"


def _bare_year(raw: str) -> bool:
    """A year ("in 2023") is never a stated result: "revenue in 2023 is 15% of $2B"."""
    return bool(re.fullmatch(r"\s*(?:1[6-9]|20)\d{2}\s*", raw))


def evaluate(expression: str) -> float:
    """Evaluate + - * / ^ and parentheses over decimal numbers. Raises ValueError."""
    normalized = (expression.replace(",", "").replace("×", "*").replace("÷", "/").replace("−", "-"))
    normalized = re.sub(r"\bmultiplied by\b|\btimes\b|(?<=\s)x(?=\s)", "*", normalized, flags=re.I)
    normalized = re.sub(r"\bdivided by\b", "/", normalized, flags=re.I)
    normalized = re.sub(r"\bplus\b", "+", normalized, flags=re.I)
    normalized = re.sub(r"\bminus\b", "-", normalized, flags=re.I)
    tokens = re.findall(r"\d+(?:\.\d+)?|[-+*/^()]|\S", normalized)
    position = 0

    def peek():
        return tokens[position] if position < len(tokens) else None

    def take():
        nonlocal position
        if position >= len(tokens):
            raise ValueError("unexpected end of expression")
        position += 1
        return tokens[position - 1]

    def expr():
        value = term()
        while peek() in ("+", "-"):
            value = value + term() if take() == "+" else value - term()
        return value

    def term():
        value = power()
        while peek() in ("*", "/"):
            if take() == "*":
                value *= power()
            else:
                divisor = power()
                if divisor == 0:
                    raise ValueError("division by zero")
                value /= divisor
        return value

    def power():
        base = unary()
        if peek() == "^":
            take()
            exponent = power()
            if abs(exponent) > 12 or abs(base) > 1e6:
                raise ValueError("exponent out of range")
            result = base ** exponent
            if isinstance(result, complex) or not math.isfinite(result):  # "(2 - 10) ^ 0.5"
                raise ValueError("not a real number")
            return result
        return base

    def unary():
        if peek() == "-":
            take()
            return -unary()
        return atom()

    def atom():
        token = take() if peek() is not None else None
        if token == "(":
            value = expr()
            if take() != ")":
                raise ValueError("unbalanced parentheses")
            return value
        if token is None or not re.fullmatch(r"\d+(?:\.\d+)?", token):
            raise ValueError("not a number")
        return float(token)

    result = expr()
    if position != len(tokens):
        raise ValueError("unexpected token")
    return result


@dataclass
class Found:
    kind: str
    expression: str
    stated_text: str  # exactly as written, for the correction
    stated: Quantity
    computed: float
    computed_text: str
    consistent: bool
    extra_note: str = ""
    tolerance: str = ""


def _is_year_span(match: re.Match) -> bool:
    """'from 2015 to 2020' is a time span, not two values to compare."""
    return all(re.fullmatch(r"\s*(?:1[6-9]|20)\d{2}\s*", match.group(g)) for g in ("a", "b"))


def _unit(raw: str) -> str:
    key = raw.lower().strip()
    key = _ALIASES.get(key, key)
    if key not in _UNITS and key.endswith("s"):
        key = _ALIASES.get(key[:-1], key[:-1])
    return key


def _convert_temperature(value: float, source: str, target: str) -> float:
    celsius = {"c": value, "f": (value - 32) * 5 / 9, "kelvin": value - 273.15}[source]
    return {"c": celsius, "f": celsius * 9 / 5 + 32, "kelvin": celsius + 273.15}[target]


def _adjacent(text: str, end: int, start: int) -> bool:
    """Is text[end:start] only the connective tissue between a from–to and its percent change?"""
    return 0 <= start - end <= 40 and _GAP.fullmatch(text[end:start]) is not None


def _find(text: str) -> list[Found]:
    """Every checkable calculation stated in `text`."""
    found: list[Found] = []
    for pattern, worded in ((ARITHMETIC[0], False), (ARITHMETIC[1], True)):
        for m in pattern.finditer(text):
            stated_text = m.group("stated")
            stated = parse_quantity(stated_text)
            if stated is None or (worded and _bare_year(stated_text)):
                continue
            try:
                computed = evaluate(m.group("expr"))
            except (ValueError, OverflowError, ZeroDivisionError):
                continue
            found.append(Found("arithmetic", " ".join(m.group("expr").split()), stated_text, stated, computed,
                               _like(computed, stated), _consistent(stated, computed, rounded=False),
                               tolerance=_tolerance(stated, rounded=False)))
    for pattern in (PERCENT_OF, PERCENT_OF_REVERSED):
        for m in pattern.finditer(text):
            base, stated = parse_quantity(m.group("base")), parse_quantity(m.group("stated"))
            if base is None or stated is None or _bare_year(m.group("stated")):
                continue
            percent = float(m.group("p").replace(",", ""))
            computed = percent / 100 * base.value
            found.append(Found("percentage_of", f"{_number(percent)}% × {m.group('base').strip()}",
                               m.group("stated"), stated, computed, _like(computed, stated),
                               _consistent(stated, computed), tolerance=_tolerance(stated)))
    changes = [m for pattern in CHANGE for m in pattern.finditer(text)]
    used: set[int] = set()
    for span in FROM_TO.finditer(text):
        a, b = parse_quantity(span.group("a")), parse_quantity(span.group("b"))
        if _is_year_span(span) or not (a and b) or a.value == 0:
            continue
        # Only a change phrase attached to this from–to describes it: "from $20M to $30M, an
        # increase of 80%" — never "..., and headcount increased by 15%".
        m = next((c for c in changes if id(c) not in used and (
            _adjacent(text, span.end(), c.start()) or _adjacent(text, c.end(), span.start()))), None)
        stated = parse_quantity(m.group("p")) if m else None
        if stated is None:
            continue
        used.add(id(m))
        change = (b.value - a.value) / a.value * 100
        up = m.group("dir").lower() in UP
        direction_ok = (change > 0) == up or change == 0
        consistent = direction_ok and _consistent(stated, abs(change))
        note = "" if direction_ok else (f" The figures show a {'rise' if change > 0 else 'fall'}, "
                                        f"not a {'rise' if up else 'fall'}.")
        found.append(Found("percent_change", f"({span.group('b').strip()} − {span.group('a').strip()}) ÷ "
                           f"{span.group('a').strip()} × 100", m.group("p"), stated, abs(change),
                           f"{_number(change)}%", consistent, note, tolerance=_tolerance(stated)))
    for pattern in MULTIPLE:
        for m in pattern.finditer(text):
            if _OTHER_SUBJECT.search(m.groupdict().get("gap") or ""):
                continue  # "users doubled while prices went from $10 to $11"
            a, b = parse_quantity(m.group("a")), parse_quantity(m.group("b"))
            if _is_year_span(m) or not a or not b or a.value == 0:
                continue
            word = m.groupdict().get("w")
            factor = MULTIPLE_WORDS[word.lower()] if word else float(m.group("n").replace(",", ""))
            ratio = b.value / a.value
            found.append(Found("multiple", f"{m.group('b').strip()} ÷ {m.group('a').strip()}", word or m.group("n"),
                               Quantity(factor, 2, 1.0, "", ""), ratio, f"{_number(ratio)}×",
                               abs(ratio - factor) <= 0.02 * factor, tolerance="±2% of the stated multiple"))
    for m in CONVERSION.finditer(text):
        source, target = _unit(m.group("u1")), _unit(m.group("u2"))
        if source not in _UNITS or target not in _UNITS or _UNITS[source][0] != _UNITS[target][0]:
            continue
        n, stated = parse_quantity(m.group("n")), parse_quantity(m.group("stated"))
        if n is None or stated is None or _bare_year(m.group("stated")):
            continue
        temperature = _UNITS[source][0] == "temperature"
        if temperature:
            candidates = [_convert_temperature(n.value, source, target)]
        else:
            candidates = [n.value * f1 / f2 for f1 in _UNITS[source][1] for f2 in _UNITS[target][1]]
        computed = min(candidates, key=lambda c: abs(c - stated.value))
        # Degrees: no trailing-zero rounding and no relative bound ("-18 °C is 0 °F" is -0.4 °F).
        rule = {"rounded": not temperature, "relative": not temperature}
        consistent = _consistent(stated, computed, **rule)
        note = ""
        if _UNITS[source][0] == "data" and consistent and len(candidates) > 1:
            note = (" Matches the binary (1024-based) reading." if computed in candidates[1:2] + candidates[3:]
                    and computed != candidates[0] else " Matches the decimal (1000-based) reading.")
        found.append(Found("unit_conversion", f"{m.group('n')} {m.group('u1')} → {m.group('u2')}",
                           m.group("stated"), stated, computed, f"{_number(computed)} {m.group('u2')}",
                           consistent, note, tolerance=_tolerance(stated, **rule)))
    cash, burn, runway = CASH.search(text), BURN.search(text), RUNWAY.search(text)
    if cash and burn and runway:
        cash_q = parse_quantity(cash.group("cash") or cash.group("cash2"))
        burn_q = parse_quantity(burn.group("burn") or burn.group("burn2"))
        stated_text = runway.group("stated") or runway.group("stated2")
        stated = parse_quantity(stated_text)
        if cash_q and burn_q and stated and burn_q.value > 0:
            months = cash_q.value / burn_q.value
            found.append(Found("runway", f"{(cash.group('cash') or cash.group('cash2')).strip()} ÷ "
                               f"{(burn.group('burn') or burn.group('burn2')).strip()} per month", stated_text,
                               stated, months, f"{_number(months)} months", _consistent(stated, months),
                               tolerance=_tolerance(stated)))
    return found


def _pure(claim_text: str, item: Found) -> bool:
    if item.kind not in ("arithmetic", "percentage_of", "unit_conversion"):
        return False
    leftover = re.sub(rf"{_N}|[$€£₹%=+*/^×÷()≈~,.:;!?\-−]", " ", claim_text.lower())
    words = [w for w in re.findall(r"[a-z°/]+", leftover)
             if w not in FILLER and _unit(w) not in _UNITS and w not in SCALES]
    return len(words) <= 1


def calculations(claim: Claim) -> list[tuple[Calculation, str | None]]:
    """(Calculation, correction or None) for each calculation the claim states."""
    own = _find(claim.exact_text)
    borrowed = False
    if not own and claim.context != claim.exact_text:
        # A fragment such as "an increase of 80%": the inputs live in the sentence,
        # so only calculations whose stated result is written in this claim count
        # ("80%" — not the "80" inside "$80M").
        own = [f for f in _find(claim.context) if _stated_pattern(f).search(claim.exact_text)]
        borrowed = bool(own)
    results = []
    for item in own:
        pure = not borrowed and _pure(claim.exact_text, item)
        notes = {
            "arithmetic": "Recomputed from the numbers stated in the claim.",
            "percentage_of": "Recomputed the percentage of the stated base.",
            "percent_change": "Percent change = (new − old) ÷ old × 100.",
            "multiple": "Ratio of the final value to the starting value.",
            "unit_conversion": "Converted with standard conversion factors.",
            "runway": "Runway in months = cash ÷ monthly burn.",
        }[item.kind] + item.extra_note
        if not pure:
            notes += " " + ARITHMETIC_ONLY
        calc = Calculation(kind=item.kind, expression=item.expression, stated_value=item.stated_text.strip(),
                           computed_value=item.computed_text, consistent=item.consistent,
                           tolerance=item.tolerance, pure_math=pure, note=notes)
        correction = _correction(claim.exact_text, item) if not item.consistent else None
        results.append((calc, correction))
    return results


def _stated_pattern(item: Found) -> re.Pattern:
    """Where the stated value is written: a whole number, followed by % or 'months' when relevant."""
    follows = {"percent_change": r"(?=\s?(?:%|percent))", "runway": r"(?=\s+months?)"}.get(item.kind, r"(?![\w.,]*\d)")
    return re.compile(r"(?<![\w.$€£₹,])" + re.escape(item.stated_text.strip()) + follows)


def _correction(text: str, item: Found) -> str | None:
    """The claim with its stated value replaced by the computed one (last matching occurrence)."""
    if item.kind == "multiple":
        return f"{text} (the figures show a {item.computed_text} change)"
    replacement = {"arithmetic": item.computed_text, "percentage_of": item.computed_text}.get(
        item.kind, _number(item.computed))
    matches = list(_stated_pattern(item).finditer(text))
    if not matches:
        return None
    m = matches[-1]
    corrected = text[:m.start()] + replacement + text[m.end():]
    return corrected + "." + item.extra_note if item.extra_note else corrected


class NumericalEngine:
    name = "numerical"

    def run(self, ctx: RunContext, findings: Findings) -> EngineRun:
        started = time.perf_counter()
        checked = wrong = failed = 0
        for claim in ctx.claims:
            if not claim.objectively_checkable:
                continue
            try:
                results = calculations(claim)
            except Exception as exc:  # noqa: BLE001 — one claim's text must not stop the others
                logger.warning("Calculation check failed (%s)", type(exc).__name__)
                failed += 1
                findings.note(claim.claim_id, check=CheckRecord(
                    engine=self.name, status="failed", detail="The calculation check failed for this claim."))
                continue
            for calc, correction in results:
                checked += 1
                wrong += not calc.consistent
                findings.note(claim.claim_id, calculation=calc, method="deterministic_calculation",
                              investigated=True, check=CheckRecord(
                                  engine=self.name, status="completed",
                                  detail=f"{calc.expression} = {calc.computed_value} "
                                         f"({'consistent' if calc.consistent else 'inconsistent'} with "
                                         f"{calc.stated_value})"))
                if correction:
                    findings.note(claim.claim_id, correction=correction)
        status = "partial" if failed else "completed" if checked else "not_applicable"
        return EngineRun(engine=self.name, status=status,
                         duration_ms=round((time.perf_counter() - started) * 1000, 1),
                         detail=f"{checked} calculation(s) checked, {wrong} inconsistent"
                                + (f", {failed} claim(s) could not be checked." if failed else "."))
