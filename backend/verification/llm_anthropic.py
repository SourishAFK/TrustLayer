"""Anthropic adapter: Claude as a structured-output judge, through the official SDK.

Safety rules:
* No network at construction; the SDK client is created on first use.
* stop_reason is checked before content is read: a refusal or a truncated answer
  is an error, never parsed as a judgment.
* Failures surface as LLMError("anthropic: <ExceptionType>"). SDK messages can
  quote the request, so they are never copied or chained.
* Current models reject sampling parameters, thinking budgets and assistant
  prefill, so none are sent; the JSON shape comes from output_config.format.
"""

import os

from backend.verification.contracts import LLMError, LLMResult
from backend.verification.llm import parse_json_object

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "low"  # judging is classification-style work
EFFORTS = ("low", "medium", "high", "xhigh", "max")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    """Claude via client.beta.messages.create with a JSON-schema output format."""

    name = "anthropic"
    family = "claude"

    def __init__(self, api_key: str | None = None, model: str | None = None, *, client=None,
                 effort: str | None = None):
        self.model = model or os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL
        self.effort = effort or os.getenv("TRUSTLAYER_ANTHROPIC_EFFORT") or DEFAULT_EFFORT
        if self.effort not in EFFORTS:
            raise ValueError(f"Anthropic effort must be one of: {', '.join(EFFORTS)}.")
        self._api_key = api_key
        self._client = client

    def complete_json(self, *, system: str, prompt: str, schema: dict, max_output_tokens: int,
                      timeout: float) -> LLMResult:
        kwargs = dict(model=self.model, max_tokens=max_output_tokens, system=system,
                      messages=[{"role": "user", "content": prompt}],
                      output_config={"effort": self.effort,
                                     "format": {"type": "json_schema", "schema": schema}},
                      timeout=timeout)
        if "haiku" not in self.model.casefold():
            # A policy decline is retried server-side on Anthropic's recommended fallback
            # model. Claude Haiku has no server-side fallback, so it is never sent there.
            kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
        try:
            response = self._sdk().beta.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — SDK messages may quote the request
            raise LLMError(f"anthropic: {type(exc).__name__}") from None
        if response.stop_reason == "refusal":
            raise LLMError("anthropic: refused")
        if response.stop_reason in ("max_tokens", "model_context_window_exceeded"):
            raise LLMError("anthropic: truncated")
        text = next((block.text for block in response.content if block.type == "text"), None)
        # response.model is the model that answered, which may be the fallback.
        return LLMResult(data=parse_json_object(text, self.name), model=response.model,
                         input_tokens=response.usage.input_tokens,
                         output_tokens=response.usage.output_tokens)

    def _sdk(self):
        if self._client is None:
            import anthropic  # lazy: only a real call needs the SDK client

            self._client = anthropic.Anthropic(api_key=self._api_key, max_retries=1)
        return self._client
