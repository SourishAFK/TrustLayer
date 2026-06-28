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
    key = store.generate_api_key(owner=args.owner, tier=args.tier, daily_limit=args.limit)
    print("\n  New API key created — send this to the developer:\n")
    print(f"    {key}\n")
    print(f"  owner: {args.owner or '(none)'} | tier: {args.tier} | limit: {args.limit}/day\n")


def cmd_list(args: argparse.Namespace) -> None:
    with store._get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT key, owner, tier, daily_limit, active, created_at "
            "FROM api_keys ORDER BY created_at DESC"
        ).fetchall()
    if not rows:
        print("No API keys yet.")
        return
    print(f"\n{'KEY':<26} {'ACTIVE':<7} {'TIER':<8} {'LIMIT':<6} OWNER")
    print("-" * 70)
    for r in rows:
        print(f"{r['key']:<26} {str(r['active']):<7} {r['tier']:<8} "
              f"{r['daily_limit']:<6} {r['owner'] or ''}")
    print()


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
    c.set_defaults(func=cmd_create)

    l = sub.add_parser("list", help="List all API keys.")
    l.set_defaults(func=cmd_list)

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
