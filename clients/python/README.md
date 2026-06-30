# TrustLayer Python SDK

Detect AI **sycophancy** — when an AI tells a user what they want to hear instead
of what's true — in one line. Wraps the hosted TrustLayer API.

## Install

```bash
pip install trustlayer
# (during beta, from this repo:)
pip install ./clients/python
```

## Setup (once)

Get a key from TrustLayer, then:

```python
import trustlayer
trustlayer.api_key = "tl_your_key"     # or set env TRUSTLAYER_API_KEY
```

## Score a response

```python
result = trustlayer.score(
    user_query="My pizza has less cheese, I want a full refund!",
    ai_response="You're absolutely right, refunding you now!",
    domain="customer_service",          # fintech | customer_service | general
    image="complaint.jpg",              # bytes or a file path (optional)
)

print(result.verdict)               # "SYCOPHANTIC"
print(result.sycophancy_score)      # 83
print(result.suggested_honest_alternative)
print(result.request_id)            # use this for feedback below

if result.is_sycophantic:
    ...                              # block the refund, escalate, or use the rewrite
```

## Monitoring mode (never blocks or breaks your app)

```python
# fire-and-forget in a background thread — safe in a production request path
trustlayer.audit(
    user_query, bot_reply,
    domain="customer_service",
    image=image_bytes,
    callback=lambda r: print(r.verdict, r.sycophancy_score) if r else None,
)
```

## Report what actually happened (ground truth → trains the model)

```python
trustlayer.feedback(result.request_id, outcome="human_overrode",
                    feedback="refund denied — photo showed normal cheese")
```

## Result fields

`sycophancy_score` · `verdict` · `indicators` · `suggested_honest_alternative` ·
`intent_gap` · `response_honesty` · `domain_flagged` · `high_stakes` ·
`scoring_model_used` · `processing_time_ms` · `request_id`

Plus flags: `result.is_sycophantic`, `result.is_borderline`, `result.is_honest`.

## Errors

`AuthError` (401) · `RateLimitError` (429, has `.reset_at`) · `TrustLayerError` (base).
In monitoring mode (`audit`), all errors are swallowed so your app is never affected.
