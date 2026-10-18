"""Model adapters and judge selection. Offline: fake SDK clients, no credentials.

The anthropic SDK is faked through sys.modules (llm_anthropic imports it lazily),
so these tests run whether or not it is installed.
"""

import sys
from types import SimpleNamespace

import pytest
from google.genai import errors

from backend.verification import llm
from backend.verification.contracts import LLMError, LLMResult
from backend.verification.llm import (
    GeminiProvider,
    available_providers,
    family_of,
    independence_note,
    select_llm,
)
from backend.verification.llm_anthropic import AnthropicProvider

SCHEMA = {"title": "stance_judgments", "type": "object", "additionalProperties": False,
          "properties": {"stance": {"type": "string", "enum": ["supports", "irrelevant"]}},
          "required": ["stance"]}
USER_TEXT = "Acme was founded in 2015"
ENV = ("GEMINI_API_KEY", *(f"GEMINI_API_KEY_{i}" for i in range(2, 10)), "GEMINI_MODEL",
       "TRUSTLAYER_GEMINI_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "TRUSTLAYER_ANTHROPIC_EFFORT",
       "TRUSTLAYER_LLM_PROVIDERS")
BOTH = {"ANTHROPIC_API_KEY": "sk-test", "GEMINI_API_KEY": "g-test"}


def no_network(**_kwargs):
    raise AssertionError("a real SDK client was created")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Clear model env; creating a real SDK client fails the test."""
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(llm, "genai", SimpleNamespace(Client=no_network))
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=no_network))


def setenv(monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)


def ask(provider, timeout=12.5):
    return provider.complete_json(system="Judge each passage.", prompt=f"<claim>{USER_TEXT}</claim>",
                                  schema=SCHEMA, max_output_tokens=512, timeout=timeout)


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #

class FakeGemini:
    """genai.Client stand-in: records generate_content calls and replays outcomes in order."""

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def reply(text='{"stance": "supports"}', prompt=120, candidates=30, thoughts=None):
    return SimpleNamespace(text=text, usage_metadata=SimpleNamespace(
        prompt_token_count=prompt, candidates_token_count=candidates, thoughts_token_count=thoughts))


def quota():
    return errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                              "message": f"Quota exceeded: {USER_TEXT}"}})


def keyed_clients(monkeypatch, clients):
    """Serve genai.Client(api_key=k) from clients[k]; returns the keys used, in order."""
    made = []

    def client(*, api_key):
        made.append(api_key)
        return clients[api_key]
    monkeypatch.setattr(llm, "genai", SimpleNamespace(Client=client))
    return made


def test_gemini_sends_a_strict_json_config_and_maps_usage():
    client = FakeGemini(reply(thoughts=7), reply())
    provider = GeminiProvider(model="gemini-judge", client=client)
    result = ask(provider)
    call = client.calls[0]
    assert (call.model, call.contents) == ("gemini-judge", f"<claim>{USER_TEXT}</claim>")
    config = call.config
    assert config.system_instruction == "Judge each passage." and config.temperature == 0.0
    assert config.response_mime_type == "application/json" and config.response_json_schema == SCHEMA
    assert config.max_output_tokens == 512
    assert config.http_options.timeout == 12_500  # google-genai counts milliseconds
    assert result == LLMResult(data={"stance": "supports"}, model="gemini-judge", input_tokens=120,
                               output_tokens=37)
    ask(provider, timeout=0.0001)
    assert client.calls[1].config.http_options.timeout == 1  # 0 would mean "no timeout"


def test_gemini_missing_usage_counts_as_zero():
    client = FakeGemini(SimpleNamespace(text='{"stance": "irrelevant"}', usage_metadata=None),
                        reply(prompt=None, candidates=None))
    provider = GeminiProvider(client=client)
    for result in (ask(provider), ask(provider)):
        assert (result.input_tokens, result.output_tokens) == (0, 0)


def test_gemini_identity_and_model_settings(monkeypatch):
    provider = GeminiProvider()
    assert (provider.name, provider.family, provider.model) == ("gemini", "gemini", "gemini-2.5-flash-lite")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-legacy")
    assert GeminiProvider().model == "gemini-legacy"
    monkeypatch.setenv("TRUSTLAYER_GEMINI_MODEL", "gemini-judge")
    assert GeminiProvider().model == "gemini-judge"
    assert GeminiProvider(model="gemini-arg").model == "gemini-arg"


@pytest.mark.parametrize("text", ['```json\n{"stance": "supports"}\n```', '```JSON {"stance": "supports"}```',
                                  '\n {"stance": "supports"} \n'])
def test_gemini_accepts_one_json_object_even_in_a_fence(text):
    assert ask(GeminiProvider(client=FakeGemini(reply(text)))).data == {"stance": "supports"}


@pytest.mark.parametrize("text", [None, "", f"It supports: {USER_TEXT}", '["supports"]', '{"stance": "supports"',
                                  'Answer: ```json\n{"stance": "supports"}\n```'])
def test_gemini_rejects_anything_but_one_json_object(text):
    with pytest.raises(LLMError) as err:
        ask(GeminiProvider(client=FakeGemini(reply(text))))
    assert str(err.value).startswith("gemini: response was not") and USER_TEXT not in str(err.value)


def test_gemini_rotates_keys_only_on_quota_errors(monkeypatch):
    setenv(monkeypatch, {"GEMINI_API_KEY": "key-1", "GEMINI_API_KEY_2": "key-1", "GEMINI_API_KEY_5": "key-5",
                         "GEMINI_API_KEY_9": "key-9"})
    clients = {"key-1": FakeGemini(quota()), "key-5": FakeGemini(quota()), "key-9": FakeGemini(reply(), reply())}
    made = keyed_clients(monkeypatch, clients)
    provider = GeminiProvider()
    assert made == []  # no SDK client (or network) before the first call
    assert ask(provider).data == {"stance": "supports"}
    assert made == ["key-1", "key-5", "key-9"]  # the duplicate key is tried once
    ask(provider)  # later calls start at the key that still has quota
    assert made == ["key-1", "key-5", "key-9"]
    assert [len(c.calls) for c in clients.values()] == [1, 1, 2]


@pytest.mark.parametrize("exc", [
    errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": f"Bad: {USER_TEXT}"}}),
    errors.ClientError(403, {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "key-1 is invalid"}}),
    errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "overloaded"}}),
    TimeoutError(f"timed out sending {USER_TEXT}"),
])
def test_gemini_other_errors_neither_rotate_nor_leak(monkeypatch, exc):
    setenv(monkeypatch, {"GEMINI_API_KEY": "key-1", "GEMINI_API_KEY_2": "key-2"})
    made = keyed_clients(monkeypatch, {"key-1": FakeGemini(exc), "key-2": FakeGemini(reply())})
    with pytest.raises(LLMError) as err:
        ask(GeminiProvider())
    assert str(err.value) == f"gemini: {type(exc).__name__}" and made == ["key-1"]
    assert err.value.__cause__ is None and err.value.__suppress_context__


def test_gemini_without_a_key_or_quota_fails_cleanly(monkeypatch):
    with pytest.raises(LLMError, match="^gemini: no API key configured$"):
        ask(GeminiProvider())
    monkeypatch.setenv("GEMINI_API_KEY", "key-1")
    keyed_clients(monkeypatch, {"key-1": FakeGemini(quota())})
    with pytest.raises(LLMError, match="^gemini: ClientError$"):
        ask(GeminiProvider())


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #

class FakeAnthropic:
    """anthropic.Anthropic stand-in: records beta.messages.create kwargs; returns or raises outcome."""

    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []
        self.beta = SimpleNamespace(messages=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def text(value):
    return SimpleNamespace(type="text", text=value)


def message(content=None, *, stop_reason="end_turn", model="claude-opus-5-5"):
    if content is None:  # adaptive thinking comes back as an empty thinking block first
        content = [SimpleNamespace(type="thinking", thinking=""), text('{"stance": "supports"}')]
    return SimpleNamespace(stop_reason=stop_reason, model=model, content=content,
                           usage=SimpleNamespace(input_tokens=210, output_tokens=40))


def test_anthropic_request_shape_with_server_side_fallback():
    client = FakeAnthropic(message())
    result = ask(AnthropicProvider(client=client), timeout=30.0)
    # Exact kwargs: no thinking, budget_tokens, temperature or assistant prefill.
    assert client.calls == [{
        "model": "claude-opus-5-5", "max_tokens": 512, "system": "Judge each passage.",
        "messages": [{"role": "user", "content": f"<claim>{USER_TEXT}</claim>"}],
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        "timeout": 30.0, "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}]
    assert result == LLMResult(data={"stance": "supports"}, model="claude-opus-5-5", input_tokens=210,
                               output_tokens=40)


def test_anthropic_haiku_is_never_sent_to_a_fallback(monkeypatch):
    setenv(monkeypatch, {"ANTHROPIC_MODEL": "claude-haiku-5-5", "TRUSTLAYER_ANTHROPIC_EFFORT": "medium"})
    client = FakeAnthropic(message(model="claude-haiku-5-5"))
    ask(AnthropicProvider(client=client))
    [kwargs] = client.calls
    assert kwargs["model"] == "claude-haiku-5-5" and kwargs["output_config"]["effort"] == "medium"
    assert "betas" not in kwargs and "fallbacks" not in kwargs


def test_anthropic_settings(monkeypatch):
    provider = AnthropicProvider()
    assert (provider.name, provider.family, provider.model, provider.effort) == \
        ("anthropic", "claude", "claude-opus-5-5", "low")
    setenv(monkeypatch, {"ANTHROPIC_MODEL": "claude-sonnet-5-5", "TRUSTLAYER_ANTHROPIC_EFFORT": "high"})
    assert (AnthropicProvider().model, AnthropicProvider().effort) == ("claude-sonnet-5-5", "high")
    explicit = AnthropicProvider(model="claude-opus-5", effort="max")
    assert (explicit.model, explicit.effort) == ("claude-opus-5", "max")
    with pytest.raises(ValueError):
        AnthropicProvider(effort="extreme")


def test_anthropic_sdk_client_is_made_on_first_use(monkeypatch):
    made = []

    def sdk(**kwargs):
        made.append(kwargs)
        return FakeAnthropic(message())
    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=sdk))
    provider = AnthropicProvider(api_key="sk-test")
    assert made == []
    ask(provider)
    ask(provider)
    assert made == [{"api_key": "sk-test", "max_retries": 1}]


def test_anthropic_reports_the_model_that_answered():
    # After a server-side fallback the content starts with a fallback marker block.
    client = FakeAnthropic(message([SimpleNamespace(type="fallback"), text('{"stance": "irrelevant"}')],
                                   model="claude-opus-4-8"))
    result = ask(AnthropicProvider(client=client))
    assert (result.model, result.data) == ("claude-opus-4-8", {"stance": "irrelevant"})


@pytest.mark.parametrize("stop_reason,error", [("refusal", "anthropic: refused"),
                                               ("max_tokens", "anthropic: truncated")])
def test_anthropic_checks_stop_reason_before_reading_content(stop_reason, error):
    # The text is valid JSON, yet a refused or cut-off answer is never a judgment.
    with pytest.raises(LLMError, match=f"^{error}$"):
        ask(AnthropicProvider(client=FakeAnthropic(message(stop_reason=stop_reason))))


@pytest.mark.parametrize("content", [[], [SimpleNamespace(type="thinking", thinking="")],
                                     [text(f"It supports: {USER_TEXT}")], [text("[1, 2]")]])
def test_anthropic_needs_one_json_object(content):
    with pytest.raises(LLMError) as err:
        ask(AnthropicProvider(client=FakeAnthropic(message(content))))
    assert str(err.value).startswith("anthropic: response was not") and USER_TEXT not in str(err.value)


class RateLimitError(Exception):
    """Named like the SDK's errors, whose messages can quote the request."""


@pytest.mark.parametrize("exc", [RateLimitError(f"rate limited: {USER_TEXT}"),
                                 TimeoutError(f"timed out sending {USER_TEXT}")])
def test_anthropic_sdk_errors_name_only_their_type(exc):
    with pytest.raises(LLMError) as err:
        ask(AnthropicProvider(client=FakeAnthropic(exc)))
    assert str(err.value) == f"anthropic: {type(exc).__name__}"
    assert err.value.__cause__ is None and err.value.__suppress_context__


def test_anthropic_without_the_sdk_installed_fails_cleanly(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)  # makes "import anthropic" fail
    with pytest.raises(LLMError, match="^anthropic: ModuleNotFoundError$"):
        ask(AnthropicProvider())


# --------------------------------------------------------------------------- #
# Families and judge selection
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("model,family", [
    ("gemini-2.5-flash", "gemini"), ("models/gemini-1.5-pro", "gemini"), ("google/gemma-2-9b-it", "gemini"),
    ("Bard", "gemini"), ("PaLM 2", "gemini"),
    ("claude-opus-5-5", "claude"), ("us.anthropic.claude-sonnet-5-5", "claude"), ("Anthropic", "claude"),
    ("gpt-4o", "gpt"), ("ChatGPT-4o-latest", "gpt"), ("openai/gpt-oss-120b", "gpt"), ("o1", "gpt"),
    ("o3-mini", "gpt"), ("openai/o4-mini-high", "gpt"),
    ("meta-llama/Llama-3.1-70B-Instruct", "llama"), ("Meta AI", "llama"),
    ("mistral-large-latest", "mistral"), ("mixtral-8x7b", "mistral"),
    ("grok-4", "grok"), ("deepseek-r1", "deepseek"), ("Qwen2.5-72B", "qwen"),
    ("proto1", None), ("co3-model", None), ("o10", None), ("in-house-model", None), ("", None), (None, None),
])
def test_family_of(model, family):
    assert family_of(model) == family


@pytest.mark.parametrize("env,expected", [
    ({}, []),
    ({"GEMINI_API_KEY": "g-test"}, ["gemini"]),
    (BOTH, ["anthropic", "gemini"]),
    ({**BOTH, "TRUSTLAYER_LLM_PROVIDERS": " Gemini, openai ,anthropic,gemini"}, ["gemini", "anthropic"]),
    ({**BOTH, "TRUSTLAYER_LLM_PROVIDERS": "gemini"}, ["gemini"]),
    ({"ANTHROPIC_API_KEY": "  ", "GEMINI_API_KEY": "g-test"}, ["gemini"]),
])
def test_available_providers_follow_order_and_credentials(monkeypatch, env, expected):
    setenv(monkeypatch, env)
    assert available_providers() == expected


@pytest.mark.parametrize("env,source,judge,same_family", [
    (BOTH, "claude-opus-5-5", "gemini", False),  # never let a model judge itself
    (BOTH, "gemini-2.5-pro", "anthropic", False),
    (BOTH, "gpt-4o", "anthropic", False),  # independent of both: first in order
    (BOTH, None, "anthropic", False),
    ({**BOTH, "TRUSTLAYER_LLM_PROVIDERS": "gemini,anthropic"}, "llama-3.1-70b", "gemini", False),
    ({**BOTH, "TRUSTLAYER_LLM_PROVIDERS": "gemini,anthropic"}, "gemini-2.5-pro", "anthropic", False),
    ({"GEMINI_API_KEY": "g-test"}, "gemini-2.5-pro", "gemini", True),  # only a same-family judge
    ({"ANTHROPIC_API_KEY": "sk-test"}, "claude-sonnet-5-5", "anthropic", True),
    ({"ANTHROPIC_API_KEY": "sk-test"}, "gemini-2.5-pro", "anthropic", False),
])
def test_select_llm_prefers_a_judge_from_another_family(monkeypatch, env, source, judge, same_family):
    setenv(monkeypatch, env)
    provider = select_llm(source)  # building judges creates no SDK client (see the offline fixture)
    assert provider.name == judge
    note = independence_note(provider, source)
    assert (note is not None) == same_family
    if same_family:
        assert provider.model in note and "same model family" in note


def test_select_llm_without_credentials_is_none():
    assert select_llm("gpt-4o") is None
