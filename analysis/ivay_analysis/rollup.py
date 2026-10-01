"""Reads everything the gate report needs from Postgres, for one shop.

The sessions come from the session_rollup view (spec 9.1). Three more small reads supply what
the view does not carry: the first page type and first cart value per session (so the AUC
baseline uses only what was known at the start of the session), the decisions (for content
coverage), the page summaries (for latency) and the consent pings.
"""

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import create_engine, text

SESSIONS_SQL = """
SELECT r.*,
  (SELECT v.page_type FROM page_view v
    WHERE v.shop_id = r.shop_id AND v.session_id = r.session_id
    ORDER BY v.ts, v.event_id LIMIT 1) AS first_page_type,
  (SELECT (s.features->>'cart_value')::numeric FROM page_summary s
    WHERE s.shop_id = r.shop_id AND s.session_id = r.session_id
      AND s.features->>'cart_value' IS NOT NULL
    ORDER BY s.ts, s.event_id LIMIT 1) AS first_cart_value
FROM session_rollup r
WHERE r.shop_id = :shop
"""

DECISIONS_SQL = """
SELECT friction_state, has_content, arm, visitor_hash, session_id
FROM decision_log WHERE shop_id = :shop
"""

SUMMARIES_SQL = """
SELECT eval_count, eval_p50_us, eval_max_us FROM page_summary WHERE shop_id = :shop
"""

PINGS_SQL = """
SELECT day, consented, count FROM consent_ping_daily WHERE shop_id = :shop
"""


@dataclass(frozen=True)
class Rollup:
    shop_id: str
    sessions: pd.DataFrame
    decisions: pd.DataFrame
    summaries: pd.DataFrame
    pings: pd.DataFrame


def psycopg_url(url: str) -> str:
    """The API uses asyncpg; pandas needs a synchronous driver."""
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


def load(database_url: str, shop_id: str) -> Rollup:
    engine = create_engine(psycopg_url(database_url))
    try:
        with engine.connect() as conn:
            params = {"shop": shop_id}
            return Rollup(
                shop_id=shop_id,
                sessions=pd.read_sql(text(SESSIONS_SQL), conn, params=params),
                decisions=pd.read_sql(text(DECISIONS_SQL), conn, params=params),
                summaries=pd.read_sql(text(SUMMARIES_SQL), conn, params=params),
                pings=pd.read_sql(text(PINGS_SQL), conn, params=params),
            )
    finally:
        engine.dispose()
