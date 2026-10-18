"""Per-request budgets: time, search calls, page fetches, model calls/tokens, cost.

Every outbound call asks the Budget first. When a limit is reached the call is
refused, the limit is recorded in `exhausted`, and the affected claims stay
UNVERIFIED with a visible "incomplete" note — never a silent success.

Limits come from env (TRUSTLAYER_<MODE>_<FIELD>, e.g. TRUSTLAYER_DEEP_MAX_COST_USD)
and fail closed on invalid values. Prices are estimates for budgeting only; set
TRUSTLAYER_PRICE_* to your contract rates. No provider bill is read here.
"""

import os
import threading
import time
from dataclasses import dataclass, fields

from backend.verification.report import BudgetLimits


@dataclass(frozen=True)
class Limits:
    max_seconds: float
    max_search_calls: int
    max_page_fetches: int
    max_model_calls: int
    max_model_tokens: int
    max_cost_usd: float
    max_claims_investigated: int
    max_queries_per_claim: int
    max_results_per_query: int
    max_pages_per_claim: int

    def public(self) -> BudgetLimits:
        """The subset of limits shown in reports."""
        return BudgetLimits(**{name: getattr(self, name) for name in BudgetLimits.model_fields})


DEFAULTS = {
    "quick": Limits(max_seconds=25, max_search_calls=8, max_page_fetches=10, max_model_calls=12,
                    max_model_tokens=60_000, max_cost_usd=0.10, max_claims_investigated=6,
                    max_queries_per_claim=1, max_results_per_query=3, max_pages_per_claim=2),
    "deep": Limits(max_seconds=90, max_search_calls=30, max_page_fetches=40, max_model_calls=50,
                   max_model_tokens=300_000, max_cost_usd=1.00, max_claims_investigated=25,
                   max_queries_per_claim=3, max_results_per_query=5, max_pages_per_claim=4),
}
# Hard ceilings an env override may not exceed (protects the shared service).
CEILINGS = Limits(max_seconds=300, max_search_calls=200, max_page_fetches=200, max_model_calls=300,
                  max_model_tokens=2_000_000, max_cost_usd=10.0, max_claims_investigated=80,
                  max_queries_per_claim=6, max_results_per_query=10, max_pages_per_claim=8)


def limits_for(mode: str) -> Limits:
    """Mode defaults with env overrides. Raises ValueError on invalid config."""
    base = DEFAULTS[mode]
    values = {}
    for f in fields(Limits):
        raw = os.getenv(f"TRUSTLAYER_{mode.upper()}_{f.name.upper()}")
        if raw is None:
            values[f.name] = getattr(base, f.name)
            continue
        cast = float if f.type in (float, "float") else int
        try:
            value = cast(raw)
        except ValueError:
            raise ValueError(f"TRUSTLAYER_{mode.upper()}_{f.name.upper()} is not a number.") from None
        if not 0 < value <= getattr(CEILINGS, f.name):
            raise ValueError(f"TRUSTLAYER_{mode.upper()}_{f.name.upper()} is out of range.")
        values[f.name] = value
    return Limits(**values)


# USD estimates. Search: per call. Models: per million input/output tokens.
# Basis (Oct 2026): Anthropic list prices; Gemini and Brave public price pages as
# reported by aggregators. Free-tier keys cost $0 in practice; override per contract.
SEARCH_PRICES = {"brave": 0.005, "wikipedia": 0.0, "openalex": 0.0, "doi": 0.0}
MODEL_PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-3.5-flash": (1.50, 9.00),
}


def search_price(provider: str) -> float:
    raw = os.getenv(f"TRUSTLAYER_PRICE_SEARCH_{provider.upper()}")
    return float(raw) if raw else SEARCH_PRICES.get(provider, 0.0)


def model_price(model: str) -> tuple[float, float] | None:
    """(input, output) USD per million tokens, or None when the model is unpriced."""
    raw_in = os.getenv("TRUSTLAYER_PRICE_MODEL_INPUT_PER_MTOK")
    raw_out = os.getenv("TRUSTLAYER_PRICE_MODEL_OUTPUT_PER_MTOK")
    if raw_in and raw_out:
        return float(raw_in), float(raw_out)
    return MODEL_PRICES.get(model)


def model_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price = model_price(model)
    if price is None:
        return 0.0
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000


class Budget:
    """Thread-safe counters with check-then-spend semantics.

    `cancel` (optional threading.Event) ends the run early: once set, every
    further call is refused, e.g. when a streaming client disconnects.
    """

    def __init__(self, limits: Limits, clock=time.monotonic, cancel: threading.Event | None = None):
        self.limits = limits
        self._clock = clock
        self._start = clock()
        self._cancel = cancel
        self._lock = threading.Lock()
        self.search_calls = 0
        self.page_fetches = 0
        self.model_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0
        self.unpriced_models: set[str] = set()
        self.exhausted: list[str] = []

    # -- time --------------------------------------------------------------- #

    def elapsed(self) -> float:
        return self._clock() - self._start

    def remaining_seconds(self) -> float:
        if self._cancel is not None and self._cancel.is_set():
            return 0.0
        return max(0.0, self.limits.max_seconds - self.elapsed())

    def timeout(self, cap: float) -> float:
        """An HTTP/model timeout that never outlives the request deadline."""
        return max(0.1, min(cap, self.remaining_seconds()))

    # -- spending ----------------------------------------------------------- #

    def _deny(self, reason: str) -> bool:
        if reason not in self.exhausted:
            self.exhausted.append(reason)
        return False

    def _time_ok(self) -> bool:
        if self._cancel is not None and self._cancel.is_set():
            return self._deny("cancelled")
        return self.remaining_seconds() > 0.5 or self._deny("time")

    def try_search(self, provider: str) -> bool:
        price = search_price(provider)
        with self._lock:
            if not self._time_ok():
                return False
            if self.search_calls >= self.limits.max_search_calls:
                return self._deny("search_calls")
            if self.cost_usd + price > self.limits.max_cost_usd:
                return self._deny("cost")
            self.search_calls += 1
            self.cost_usd += price
            return True

    def try_fetch(self) -> bool:
        with self._lock:
            if not self._time_ok():
                return False
            if self.page_fetches >= self.limits.max_page_fetches:
                return self._deny("page_fetches")
            self.page_fetches += 1
            return True

    def try_model(self, model: str, estimated_input_tokens: int, max_output_tokens: int) -> bool:
        """Reserve one model call if its worst case fits the token and cost limits."""
        worst_cost = model_cost(model, estimated_input_tokens, max_output_tokens)
        with self._lock:
            if not self._time_ok():
                return False
            if self.model_calls >= self.limits.max_model_calls:
                return self._deny("model_calls")
            if (self.input_tokens + self.output_tokens + estimated_input_tokens
                    + max_output_tokens > self.limits.max_model_tokens):
                return self._deny("model_tokens")
            if self.cost_usd + worst_cost > self.limits.max_cost_usd:
                return self._deny("cost")
            self.model_calls += 1
            return True

    def record_model(self, model: str, input_tokens: int, output_tokens: int) -> None:
        """Charge the actual usage reported by the provider."""
        with self._lock:
            self.input_tokens += max(0, input_tokens)
            self.output_tokens += max(0, output_tokens)
            self.cost_usd += model_cost(model, input_tokens, output_tokens)
            if model_price(model) is None:
                self.unpriced_models.add(model)

    def cost_basis(self) -> str:
        basis = ("Estimate from configured per-call search prices and per-token model prices; "
                 "not a provider invoice. Free-tier usage may cost $0.")
        if self.unpriced_models:
            basis += f" Unpriced models counted as $0: {', '.join(sorted(self.unpriced_models))}."
        return basis


def estimate_tokens(text: str) -> int:
    """Pessimistic pre-call estimate (~3 characters per token) used only for budgeting."""
    return len(text) // 3 + 1
