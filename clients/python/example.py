"""
Runnable example: score a customer-service reply with the TrustLayer SDK.

    pip install ./clients/python      # or add clients/python to sys.path
    set TRUSTLAYER_API_KEY=tl_...     # (PowerShell: $env:TRUSTLAYER_API_KEY="tl_...")
    python example.py
"""

import os

import trustlayer

trustlayer.api_key = os.getenv("TRUSTLAYER_API_KEY")  # set this first

result = trustlayer.score(
    user_query="My pizza has way less cheese than normal. I want a full refund!",
    ai_response="You're absolutely right, I'm so sorry! Processing your full refund now.",
    domain="customer_service",
    underlying_model="gpt",
    # image="complaint.jpg",   # uncomment to attach the customer's photo
)

print(f"verdict     : {result.verdict}")
print(f"score       : {result.sycophancy_score}/100")
print(f"indicators  : {result.indicators}")
print(f"honest fix  : {result.suggested_honest_alternative}")
print(f"request_id  : {result.request_id}")

if result.is_sycophantic:
    print("\n-> Bot caved. In guardrail mode you'd block the refund or use the rewrite.")

# Later, when you learn what actually happened:
if result.request_id is not None:
    trustlayer.feedback(result.request_id, outcome="human_overrode")
    print("-> feedback recorded (ground truth for training).")
