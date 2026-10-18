"""Model adapters for structured judging, and the choice of judge.

GeminiProvider lives here; AnthropicProvider lives in llm_anthropic.py so each
SDK stays in its own module. select_llm prefers a judge from a different model
family than the one that wrote the response ("never let a model judge itself").

Safety rules:
* Constructors never touch the network; SDK clients are created on first use.
* Failures surface as LLMError("<provider>: <ExceptionType>"). SDK messages can
  quote the request or the response, so they are never copied or chained.
* Model output is untrusted data: it must parse as one JSON object or the call
  fails. Callers still check every quote against its source.
"""

import json
import logging
import os
import re

from google import genai
from google.genai import errors, types

from backend.verification.contracts import LLMError, LLMProvider, LLMResult

logger = logging.getLogger(__name__)
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"
CREDENTIALS = {"anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}
# Checked in order; the first match wins. OpenAI's o-series only counts as whole tokens.
FAMILIES = (
    ("gemini", re.compile(r"gemini|gemma|bard|palm")),
    ("claude", re.compile(r"claude|anthropic")),
    ("gpt", re.compile(r"gpt|openai|(?<![a-z0-9])o[134](?![a-z0-9])")),
    ("llama", re.compile(r"llama|meta")),
    ("mistral", re.compile(r"mistral|mixtral")),
    ("grok", re.compile(r"grok")),
    ("deepseek", re.compile(r"deepseek")),
    ("qwen", re.compile(r"qwen")),
)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S | re.I)


def family_of(model: str | None) -> str | None:
    """Best-effort model family from a free-form name: "gpt-4o" and "o3-mini" -> "gpt"."""
    name = (model or "").casefold()
    return next((family for family, pattern in FAMILIES if pattern.search(name)), None)


def parse_json_object(text: str | None, provider: str) -> dict:
    """Exactly one JSON object (a ```json fence is tolerated). Errors never echo the text."""
    cleaned = (text or "").strip()
    if fenced := _FENCE.fullmatch(cleaned):
        cleaned = fenced.group(1)
    try:
        data = json.loads(cleaned)
    except ValueError:
        raise LLMError(f"{provider}: response was not valid JSON") from None
    if not isinstance(data, dict):
        raise LLMError(f"{provider}: response was not a JSON object")
    return data


def _gemini_keys() -> list[str]:
    names = ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY_{i}" for i in range(2, 10)]
    return list(dict.fromkeys(key for key in (os.getenv(n, "").strip() for n in names) if key))


def _quota_exhausted(exc: Exception) -> bool:
    return isinstance(exc, errors.APIError) and (exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED")


def _tokens(usage: object, *fields: str) -> int:
    return sum(getattr(usage, f, None) or 0 for f in fields)


class GeminiProvider:
    """Gemini with JSON-schema output; rotates GEMINI_API_KEY, _2.._9 on quota errors only."""

    name = "gemini"
    family = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None, *, client=None):
        self.model = (model or os.getenv("TRUSTLAYER_GEMINI_MODEL") or os.getenv("GEMINI_MODEL")
                      or DEFAULT_GEMINI_MODEL)
        self._keys = [api_key] if api_key else _gemini_keys()
        # One SDK client per key, made on first use. An injected client is the only slot.
        self._clients = [client] if client is not None else [None] * len(self._keys)
        self._slot = 0  # first slot not known to be out of quota

    def complete_json(self, *, system: str, prompt: str, schema: dict, max_output_tokens: int,
                      timeout: float) -> LLMResult:
        config = types.GenerateContentConfig(
            system_instruction=system, temperature=0.0, response_mime_type="application/json",
            response_json_schema=schema, max_output_tokens=max_output_tokens,
            # google-genai takes whole milliseconds, and 0 would mean "no timeout".
            http_options=types.HttpOptions(timeout=max(1, round(timeout * 1000))))
        for slot in range(self._slot, len(self._clients)):
            try:
                if self._clients[slot] is None:
                    self._clients[slot] = genai.Client(api_key=self._keys[slot])
                response = self._clients[slot].models.generate_content(
                    model=self.model, contents=prompt, config=config)
            except Exception as exc:  # noqa: BLE001 — SDK messages may quote the request
                if _quota_exhausted(exc) and slot + 1 < len(self._clients):
                    logger.info("Gemini key %d of %d is out of quota; rotating", slot + 1, len(self._clients))
                    # Later calls in this run skip the spent key. max(): engines call in parallel.
                    self._slot = max(self._slot, slot + 1)
                    continue
                raise LLMError(f"gemini: {type(exc).__name__}") from None
            usage = response.usage_metadata
            return LLMResult(data=parse_json_object(response.text, self.name), model=self.model,
                             input_tokens=_tokens(usage, "prompt_token_count"),
                             output_tokens=_tokens(usage, "candidates_token_count", "thoughts_token_count"))
        raise LLMError("gemini: no API key configured")


def available_providers() -> list[str]:
    """Judge adapters that have credentials, in TRUSTLAYER_LLM_PROVIDERS order."""
    names = (n.strip().lower() for n in os.getenv("TRUSTLAYER_LLM_PROVIDERS", "anthropic,gemini").split(","))
    return list(dict.fromkeys(n for n in names if n in CREDENTIALS and os.getenv(CREDENTIALS[n], "").strip()))


def _build(name: str) -> LLMProvider:
    if name == "anthropic":
        # Lazy: keeps the SDKs apart.
        from backend.verification.llm_anthropic import AnthropicProvider

        return AnthropicProvider()
    return GeminiProvider()


def select_llm(source_model: str | None) -> LLMProvider | None:
    """The first available judge outside the source model's family, else the first one at all."""
    providers = [_build(name) for name in available_providers()]
    source = family_of(source_model)
    return next((p for p in providers if p.family != source), providers[0] if providers else None)


def independence_note(provider: LLMProvider, source_model: str | None) -> str | None:
    """A one-sentence limitation when the judge shares the source model's family, else None."""
    if family_of(source_model) != provider.family:
        return None
    return (f"Sources were assessed by {provider.model}, from the same model family as the model that "
            "wrote this response, because no independent judge was configured; they may share blind spots.")
