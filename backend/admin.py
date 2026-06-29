"""
admin.py — TrustLayer key administration (CLI).

Phase 2 has no signup page: you mint keys manually and DM them to developers.
This is that tool. It talks to the same Supabase store as the API.

Usage:
    python -m backend.admin create --owner "Jane (Acme)" --limit 100
    python -m backend.admin list
    python -m backend.admin revoke tl_xxxxxxxxxxxxxxxxxxxx
    python -m backend.admin usage           # recent scored requests
"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

load_dotenv()

from backend import store  # noqa: E402  (after load_dotenv so DATABASE_URL is set)


def cmd_create(args: argparse.Namespace) -> None:
    store.init_db()
    key = store.generate_api_key(owner=args.owner, tier=args.tier,
                                 daily_limit=args.limit, log_inputs=args.log_inputs)
    print("\n  New API key created — send this to the developer:\n")
    print(f"    {key}\n")
    print(f"  owner: {args.owner or '(none)'} | tier: {args.tier} | "
          f"limit: {args.limit}/day | log_inputs: {args.log_inputs}\n")


def cmd_list(args: argparse.Namespace) -> None:
    with store._get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT key, owner, tier, daily_limit, active, log_inputs, created_at "
            "FROM api_keys ORDER BY created_at DESC"
        ).fetchall()
    if not rows:
        print("No API keys yet.")
        return
    print(f"\n{'KEY':<26} {'ACTIVE':<7} {'LOG':<5} {'TIER':<8} {'LIMIT':<6} OWNER")
    print("-" * 76)
    for r in rows:
        print(f"{r['key']:<26} {str(r['active']):<7} {str(r['log_inputs']):<5} "
              f"{r['tier']:<8} {r['daily_limit']:<6} {r['owner'] or ''}")
    print()


def cmd_logging(args: argparse.Namespace) -> None:
    enabled = args.state == "on"
    ok = store.set_log_inputs(args.key, enabled)
    print(f"Input logging {'ENABLED' if enabled else 'disabled'} for {args.key}."
          if ok else "Key not found.")


def cmd_export(args: argparse.Namespace) -> None:
    """Export logged rows as JSONL for model training. Only rows with stored
    input text are useful as features, so we require user_query to be present."""
    import json
    with store._get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT domain, user_query, ai_response, context, attachment_count, "
            "sycophancy_score, verdict, intent_gap, response_honesty, indicators, "
            "suggested_alternative, feedback, outcome, created_at "
            "FROM usage_log WHERE user_query IS NOT NULL ORDER BY created_at"
        ).fetchall()
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            r["created_at"] = r["created_at"].isoformat()
            f.write(json.dumps(r, default=str) + "\n")
    print(f"Exported {len(rows)} trainable rows -> {args.out}")


def cmd_revoke(args: argparse.Namespace) -> None:
    with store._get_pool().connection() as conn:
        res = conn.execute(
            "UPDATE api_keys SET active = FALSE WHERE key = %s", (args.key,)
        )
    print("Revoked." if res.rowcount else "Key not found.")


def cmd_usage(args: argparse.Namespace) -> None:
    with store._get_pool().connection() as conn:
        total = conn.execute("SELECT count(*) AS c FROM usage_log").fetchone()["c"]
        rows = conn.execute(
            "SELECT created_at, api_key, domain, verdict, sycophancy_score, "
            "scoring_model_used, processing_time_ms "
            "FROM usage_log ORDER BY created_at DESC LIMIT %s", (args.limit,)
        ).fetchall()
    print(f"\nTotal logged requests: {total}\n")
    for r in rows:
        ts = r["created_at"].strftime("%Y-%m-%d %H:%M")
        print(f"  {ts}  {(r['api_key'] or '-'):<24} {r['domain']:<16} "
              f"{r['verdict']:<12} {r['sycophancy_score']:>3}  "
              f"{r['scoring_model_used']}  {r['processing_time_ms']}ms")
    print()


def main() -> None:
    p = argparse.ArgumentParser(prog="trustlayer-admin", description="Manage API keys.")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="Mint a new API key.")
    c.add_argument("--owner", default=None, help="Who the key is for (free text).")
    c.add_argument("--tier", default="free", help="Tier label (default: free).")
    c.add_argument("--limit", type=int, default=store.DEFAULT_DAILY_LIMIT,
                   help=f"Daily request limit (default: {store.DEFAULT_DAILY_LIMIT}).")
    c.add_argument("--log-inputs", dest="log_inputs", action="store_true",
                   help="Store raw request text for training (requires consent — PII).")
    c.set_defaults(func=cmd_create)

    l = sub.add_parser("list", help="List all API keys.")
    l.set_defaults(func=cmd_list)

    g = sub.add_parser("logging", help="Toggle input logging for a key.")
    g.add_argument("key", help="The tl_ key.")
    g.add_argument("state", choices=["on", "off"], help="on = store inputs, off = don't.")
    g.set_defaults(func=cmd_logging)

    e = sub.add_parser("export", help="Export trainable rows as JSONL.")
    e.add_argument("--out", default="trustlayer_dataset.jsonl", help="Output file.")
    e.set_defaults(func=cmd_export)

    r = sub.add_parser("revoke", help="Deactivate a key.")
    r.add_argument("key", help="The tl_ key to revoke.")
    r.set_defaults(func=cmd_revoke)

    u = sub.add_parser("usage", help="Show recent scored requests.")
    u.add_argument("--limit", type=int, default=20, help="How many rows to show.")
    u.set_defaults(func=cmd_usage)

    args = p.parse_args()
    try:
        args.func(args)
    finally:
        store.close_pool()


if __name__ == "__main__":
    main()
