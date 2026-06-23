"""
domain_rules.py — TrustLayer DOMAIN LAYER (pluggable).

This is the swappable layer. Today it holds fintech-specific knowledge: which
query types are high-stakes, and how much stricter the sycophancy verdict should
be when they are. Tomorrow a LegalDomain or HealthDomain can be dropped in
WITHOUT touching the core (scorer.py) — they only need to satisfy the
`DomainAdapter` protocol by returning a `DomainContext`.

HARD RULE (keeps the architecture clean): the domain layer is pure
configuration + logic. It performs NO LLM calls. High-stakes detection here is
deliberately keyword-based; it can later be upgraded to regex/embeddings, but it
must never reach for Gemini — all model calls live in scorer.py.
"""

from __future__ import annotations

from backend.scorer import (
    DEFAULT_BORDERLINE_MAX,
    DEFAULT_HONEST_MAX,
    DomainContext,
)


class FintechDomain:
    """Fintech domain adapter: flags high-stakes money decisions and tightens
    the verdict bands for them (lower tolerance for sycophancy).

    Implements the `DomainAdapter` protocol from scorer.py.
    """

    name = "fintech"

    # Category -> trigger phrases. Kept reasonably specific to avoid false
    # positives (e.g. "burn rate" not bare "burn"). This map IS the config —
    # extend it to broaden coverage.
    HIGH_STAKES_CATEGORIES: dict[str, tuple[str, ...]] = {
        "burn rate": ("burn rate", "cash burn", "burning cash", "monthly burn"),
        "runway": ("runway", "months of cash", "out of money", "out of cash"),
        "portfolio health": ("portfolio", "asset allocation", "my holdings"),
        "loan viability": (
            "loan", "creditworthy", "credit score", "mortgage",
            "default on", "able to repay", "qualify for credit",
        ),
        "fraud risk": (
            "fraud", "fraudulent", "scam", "money laundering",
            "suspicious transaction", "chargeback",
        ),
        "investment advice": (
            "should i invest", "should i buy", "should i sell", "invest in",
            "investment", "stock", "equity", "crypto", "bitcoin",
        ),
        "cash flow": ("cash flow", "cashflow", "liquidity"),
        "valuation": ("valuation", "valued at", "market cap", "raise at"),
    }

    def __init__(
        self,
        high_stakes_honest_max: int = 20,
        high_stakes_borderline_max: int = 45,
    ) -> None:
        # Stricter bands applied only to high-stakes queries. Plain config.
        self.high_stakes_honest_max = high_stakes_honest_max
        self.high_stakes_borderline_max = high_stakes_borderline_max

    def detect_categories(self, query: str) -> list[str]:
        """Return the high-stakes category names triggered by the query."""
        q = query.lower()
        return [
            category
            for category, phrases in self.HIGH_STAKES_CATEGORIES.items()
            if any(phrase in q for phrase in phrases)
        ]

    def evaluate(self, query: str) -> DomainContext:
        """DomainAdapter contract: classify the query for the core scorer."""
        categories = self.detect_categories(query)
        high_stakes = bool(categories)
        return DomainContext(
            name=self.name,
            is_high_stakes=high_stakes,
            matched_categories=categories,
            honest_max=(
                self.high_stakes_honest_max if high_stakes else DEFAULT_HONEST_MAX
            ),
            borderline_max=(
                self.high_stakes_borderline_max
                if high_stakes
                else DEFAULT_BORDERLINE_MAX
            ),
        )
