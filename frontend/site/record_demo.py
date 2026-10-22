"""Re-record the live demo's fallback runs (src/pages/demo/recorded/*.json).

The site replays these, clearly labelled, when the live demo is off or busy. Each run sends
exactly the request POST /v1/demo/verify/stream would build, through the real engine and the
providers configured in the repo's .env (a few cents at most). Run from the repo root:

    .venv/Scripts/python.exe frontend/site/record_demo.py [answer,document,support] [--force]

A run whose AI calls failed (quota, outage) is not saved unless --force: a replay should show
what the engine does, not a bad day at the provider.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
SITE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from backend.verification import pipeline  # noqa: E402
from backend.verification.report import VerificationRequest  # noqa: E402


def demo_request(body: dict) -> VerificationRequest:
    """Mirror of backend.main.demo_verify_stream's request."""
    key = body.get("answer_key")
    return VerificationRequest(
        response_text=body["response_text"], original_question=body.get("original_question"), mode="quick",
        allow_web_search=key is None, share_documents_with_ai=key is not None,
        documents=[{"name": key["name"], "text": key["text"]}] if key else [],
        documents_role="answer_key" if key else "context")


def main() -> None:
    presets = json.loads((SITE / "src/pages/demo/presets.json").read_text(encoding="utf-8"))
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    names = args[0].split(",") if args else list(presets)
    for i, name in enumerate(names):
        if i:
            time.sleep(65)  # free-tier model quotas are per minute
        lines = [json.loads(line) for line in pipeline.stream_ndjson(demo_request(presets[name]["body"]))]
        final = lines[-1]
        if final["type"] != "report":
            print(f"{name}: no report ({final.get('message')}); kept the old recording")
            continue
        report = final["report"]
        print(f"{name}: {report['status']}, " + ", ".join(c["verification_status"] for c in report["claims"]))
        for note in report["incomplete_checks"]:
            print(f"  not covered: {note}")
        if any("AI call(s) failed" in note for note in report["incomplete_checks"]) and not force:
            print("  AI calls failed; kept the old recording (use --force to save anyway)")
            continue
        out = SITE / f"src/pages/demo/recorded/{name}.json"
        out.write_text(json.dumps({"recorded_at": datetime.now(timezone.utc).isoformat(), "lines": lines}, indent=1),
                       encoding="utf-8")


if __name__ == "__main__":
    main()
