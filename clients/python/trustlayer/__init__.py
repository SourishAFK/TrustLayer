"""
TrustLayer Python SDK — detect AI sycophancy in one line.

Quickstart:

    import trustlayer
    trustlayer.api_key = "tl_your_key"        # or set env TRUSTLAYER_API_KEY

    result = trustlayer.score(
        user_query="My pizza has less cheese, I want a refund!",
        ai_response="You're absolutely right, refunding you now!",
        domain="customer_service",
        image="complaint.jpg",                # bytes or a file path (optional)
    )
    print(result.verdict, result.sycophancy_score)   # SYCOPHANTIC 83

    # Report what actually happened later (ground truth → trains the model):
    trustlayer.feedback(result.request_id, outcome="human_overrode")

    # Or fire-and-forget monitoring (never blocks / breaks your app):
    trustlayer.audit(user_query, ai_response, domain="customer_service")

Every call flows through the hosted TrustLayer API, so usage is metered to your
key and (if your key opts in) logged as training data automatically.
"""

from __future__ import annotations

import base64
import os
import threading
from typing import Any, Callable, Optional, Union

import requests

__version__ = "0.1.0"
__all__ = [
    "TrustLayer", "ScoreResult", "score", "feedback", "audit",
    "TrustLayerError", "AuthError", "RateLimitError",
    "api_key", "base_url", "timeout",
]

DEFAULT_BASE_URL = "https://trustlayer-api-thcj.onrender.com"

# --- module-level config (set once) ---------------------------------------- #
api_key: Optional[str] = os.getenv("TRUSTLAYER_API_KEY")
base_url: str = os.getenv("TRUSTLAYER_BASE_URL", DEFAULT_BASE_URL)
timeout: float = 90.0


# --- errors ----------------------------------------------------------------- #
class TrustLayerError(RuntimeError):
    """Base class for all SDK errors."""


class AuthError(TrustLayerError):
    """Missing or invalid API key (HTTP 401)."""


class RateLimitError(TrustLayerError):
    """Daily rate limit reached (HTTP 429)."""

    def __init__(self, message: str, reset_at: Optional[str] = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


# --- result object ---------------------------------------------------------- #
class ScoreResult(dict):
    """The /score response as a dict with attribute access + handy flags.

    Access fields either way: result["verdict"] or result.verdict.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    @property
    def is_sycophantic(self) -> bool:
        return self.get("verdict") == "SYCOPHANTIC"

    @property
    def is_borderline(self) -> bool:
        return self.get("verdict") == "BORDERLINE"

    @property
    def is_honest(self) -> bool:
        return self.get("verdict") == "HONEST"


_MIME_BY_EXT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
    "pdf": "application/pdf",
}


def _prepare_attachment(
    image: Optional[Union[bytes, bytearray, str]], image_mime: Optional[str]
) -> Optional[list]:
    """Turn a bytes blob or a file path into the API's attachment format."""
    if image is None:
        return None
    if isinstance(image, (bytes, bytearray)):
        data = bytes(image)
        mime = image_mime or "image/jpeg"
        name = "attachment"
    else:  # treat as a file path
        with open(image, "rb") as fh:
            data = fh.read()
        ext = str(image).rsplit(".", 1)[-1].lower() if "." in str(image) else ""
        mime = image_mime or _MIME_BY_EXT.get(ext, "image/jpeg")
        name = os.path.basename(str(image))
    return [{
        "mime_type": mime,
        "data": base64.b64encode(data).decode("ascii"),
        "name": name,
    }]


# --- client ----------------------------------------------------------------- #
class TrustLayer:
    """Explicit client. Most users can skip this and call the module-level
    ``trustlayer.score(...)`` after setting ``trustlayer.api_key``."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("TRUSTLAYER_API_KEY")
        self.base_url = (base_url or os.getenv("TRUSTLAYER_BASE_URL")
                         or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = 90.0 if timeout is None else timeout

    def _headers(self) -> dict:
        if not self.api_key:
            raise AuthError(
                "No API key set. Do `trustlayer.api_key = 'tl_...'` or set the "
                "TRUSTLAYER_API_KEY environment variable."
            )
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    def score(
        self,
        user_query: str,
        ai_response: str,
        *,
        domain: str = "general",
        context: Optional[str] = None,
        image: Optional[Union[bytes, bytearray, str]] = None,
        image_mime: Optional[str] = None,
        underlying_model: Optional[str] = None,
        user_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> ScoreResult:
        """Score one AI response for sycophancy. Returns a ScoreResult.

        `image` may be raw bytes or a path to an image/PDF; it's sent as
        factual context for the honesty judgment.
        """
        payload: dict = {
            "user_query": user_query,
            "ai_response": ai_response,
            "domain": domain,
        }
        if context is not None:
            payload["context"] = context
        if underlying_model is not None:
            payload["underlying_model"] = underlying_model
        if user_id is not None:
            payload["user_id"] = user_id
        attachments = _prepare_attachment(image, image_mime)
        if attachments:
            payload["attachments"] = attachments

        resp = requests.post(
            f"{self.base_url}/score", headers=self._headers(),
            json=payload, timeout=timeout or self.timeout,
        )
        return self._handle(resp, ScoreResult)

    def feedback(
        self,
        request_id: Optional[int],
        *,
        outcome: Optional[str] = None,
        feedback: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> bool:
        """Report what actually happened for a scored request (ground truth).

        Pass the `request_id` from a ScoreResult. No-op if request_id is None.
        """
        if request_id is None:
            return False
        payload: dict = {"request_id": request_id}
        if outcome is not None:
            payload["outcome"] = outcome
        if feedback is not None:
            payload["feedback"] = feedback
        resp = requests.post(
            f"{self.base_url}/feedback", headers=self._headers(),
            json=payload, timeout=timeout or self.timeout,
        )
        self._handle(resp, dict)
        return True

    def audit(
        self,
        user_query: str,
        ai_response: str,
        *,
        callback: Optional[Callable[[Optional[ScoreResult]], None]] = None,
        **kwargs: Any,
    ) -> None:
        """Fire-and-forget scoring for monitoring mode.

        Runs in a background thread; never blocks and never raises — safe to call
        directly in a production request path. `callback(result_or_None)` runs
        when scoring finishes (e.g. to log the verdict or send /feedback).
        """
        def _run() -> None:
            try:
                result: Optional[ScoreResult] = self.score(
                    user_query, ai_response, **kwargs
                )
            except Exception:
                result = None
            if callback is not None:
                try:
                    callback(result)
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()

    @staticmethod
    def _handle(resp: requests.Response, cls: type):
        if resp.status_code == 401:
            raise AuthError("Invalid or missing API key (401).")
        if resp.status_code == 429:
            try:
                body = resp.json()
            except Exception:
                body = {}
            raise RateLimitError(
                body.get("message", "Rate limit reached (429)."),
                reset_at=body.get("reset_at"),
            )
        if not resp.ok:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise TrustLayerError(f"TrustLayer error {resp.status_code}: {detail}")
        return cls(resp.json())


# --- module-level convenience (default client bound to module config) ------- #
_default_client: Optional[TrustLayer] = None


def _client() -> TrustLayer:
    global _default_client
    if (_default_client is None
            or _default_client.api_key != api_key
            or _default_client.base_url != base_url.rstrip("/")):
        _default_client = TrustLayer(api_key=api_key, base_url=base_url, timeout=timeout)
    return _default_client


def score(user_query: str, ai_response: str, **kwargs: Any) -> ScoreResult:
    """Module-level shortcut for ``TrustLayer().score(...)``."""
    return _client().score(user_query, ai_response, **kwargs)


def feedback(request_id: Optional[int], **kwargs: Any) -> bool:
    """Module-level shortcut for ``TrustLayer().feedback(...)``."""
    return _client().feedback(request_id, **kwargs)


def audit(user_query: str, ai_response: str, **kwargs: Any) -> None:
    """Module-level shortcut for ``TrustLayer().audit(...)`` (fire-and-forget)."""
    return _client().audit(user_query, ai_response, **kwargs)
