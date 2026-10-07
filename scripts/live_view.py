"""Follow a shop's incoming events in the terminal. Usage:
DATABASE_URL=... python scripts/live_view.py [--shop shop_dev] [--interval 1] [--from-start]

Prints each new page view, decision, page summary and outcome as it lands, plus a one-line
running total. Read-only.
"""

import argparse
import asyncio
import os
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DEFAULT_URL = "postgresql+asyncpg://ivay:ivay_dev@127.0.0.1:5432/ivay"

QUERIES = {
    "page_view": "SELECT received_at, session_id, page_type, device, product_id, country "
    "FROM page_view WHERE shop_id=:s AND received_at > :t ORDER BY received_at",
    "decision": "SELECT received_at, session_id, friction_state, rule_id, arm, mode, has_content "
    "FROM decision_log WHERE shop_id=:s AND received_at > :t ORDER BY received_at",
    "summary": "SELECT received_at, session_id, eval_count, eval_p50_us, eval_max_us "
    "FROM page_summary WHERE shop_id=:s AND received_at > :t ORDER BY received_at",
    "outcome": "SELECT received_at, session_id, kind, value, source "
    "FROM outcome_event WHERE shop_id=:s AND received_at > :t ORDER BY received_at",
}
TOTALS = (
    "SELECT (SELECT count(DISTINCT session_id) FROM page_view WHERE shop_id=:s) AS sessions, "
    "(SELECT count(*) FROM page_view WHERE shop_id=:s) AS views, "
    "(SELECT count(*) FROM decision_log WHERE shop_id=:s) AS decisions, "
    "(SELECT count(*) FROM outcome_event WHERE shop_id=:s) AS outcomes"
)


def fmt(v: object) -> str:
    if isinstance(v, datetime):
        return v.astimezone().strftime("%H:%M:%S")
    if isinstance(v, str) and len(v) > 12:
        return v[
            :8
        ]  # ids are long; the first characters are enough to tell sessions apart
    if isinstance(v, float):
        return f"{v:.0f}"
    return str(v)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", default="shop_dev")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--from-start", action="store_true")
    args = ap.parse_args()
    engine = create_async_engine(os.environ.get("DATABASE_URL", DEFAULT_URL))
    async with engine.connect() as conn:
        since = datetime(1970, 1, 1, tzinfo=UTC)
        if not args.from_start:
            since = (await conn.execute(text("SELECT now()"))).scalar_one()
        print(f"following {args.shop} (Ctrl+C to stop)")
        while True:
            await conn.rollback()  # fresh snapshot each poll
            newest = since
            rows = []
            for kind, sql in QUERIES.items():
                res = await conn.execute(text(sql), {"s": args.shop, "t": since})
                for r in res.mappings():
                    rows.append((r["received_at"], kind, r))
            for ts, kind, r in sorted(rows, key=lambda x: x[0]):
                body = "  ".join(
                    f"{k}={fmt(v)}" for k, v in r.items() if k != "received_at"
                )
                print(f"{fmt(ts)}  {kind:<9} {body}")
                newest = max(newest, ts)
            if rows:
                t = (
                    (await conn.execute(text(TOTALS), {"s": args.shop}))
                    .mappings()
                    .one()
                )
                print(
                    f"          totals: {t['sessions']} sessions, {t['views']} views, "
                    f"{t['decisions']} decisions, {t['outcomes']} outcomes"
                )
            since = newest
            await asyncio.sleep(args.interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
