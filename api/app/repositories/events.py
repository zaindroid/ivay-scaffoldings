from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models import (
    consent_ping_daily,
    decision_log,
    outcome_event,
    page_summary,
    page_view,
)


async def insert_ignore(conn: AsyncConnection, table: Any, rows: list[dict[str, Any]]) -> None:
    """Idempotent insert: a beacon that arrives twice changes nothing (spec 9.2)."""
    if rows:
        await conn.execute(insert(table).on_conflict_do_nothing(), rows)


async def insert_page_views(conn: AsyncConnection, rows: list[dict[str, Any]]) -> None:
    await insert_ignore(conn, page_view, rows)


async def insert_decisions(conn: AsyncConnection, rows: list[dict[str, Any]]) -> None:
    await insert_ignore(conn, decision_log, rows)


async def insert_summaries(conn: AsyncConnection, rows: list[dict[str, Any]]) -> None:
    await insert_ignore(conn, page_summary, rows)


async def insert_outcomes(conn: AsyncConnection, rows: list[dict[str, Any]]) -> None:
    await insert_ignore(conn, outcome_event, rows)


async def upsert_webhook_order(
    conn: AsyncConnection,
    *,
    shop_id: str,
    session_id: str,
    value: Decimal | None,
    now: datetime,
) -> None:
    """One order_completed per session. The webhook is authoritative: it replaces a pixel row
    (taking the order value) and is never replaced by one. Re-deliveries change nothing."""
    stmt = insert(outcome_event).values(
        event_id=f"wh_{session_id}",
        shop_id=shop_id,
        session_id=session_id,
        kind="order_completed",
        value=value,
        source="webhook",
        ts=now,
        received_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[outcome_event.c.shop_id, outcome_event.c.session_id],
        index_where=outcome_event.c.kind == "order_completed",
        set_={
            "value": stmt.excluded.value,
            "source": "webhook",
            "event_id": stmt.excluded.event_id,
        },
        where=outcome_event.c.source != "webhook",
    )
    await conn.execute(stmt)


async def increment_consent_ping(
    conn: AsyncConnection, shop_id: str, consented: bool, day: date | None = None
) -> None:
    today = day or datetime.now(UTC).date()
    stmt = insert(consent_ping_daily).values(
        shop_id=shop_id, day=today, consented=consented, count=1
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            consent_ping_daily.c.shop_id,
            consent_ping_daily.c.day,
            consent_ping_daily.c.consented,
        ],
        set_={"count": consent_ping_daily.c.count + 1},
    )
    await conn.execute(stmt)
