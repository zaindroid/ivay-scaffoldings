"""Turns a validated envelope into rows for the four event tables."""

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection

from app.repositories import events as repo
from app.schemas import Envelope, Outcome, PageSummary, PageView, RuleFired

# Client clocks are not trusted (received_at is set here), but a timestamp that cannot be
# represented is a malformed batch. Year 2100 in ms.
MAX_TS_MS = 4_102_444_800_000


def _ts(ms: int) -> datetime:
    if ms > MAX_TS_MS:
        raise HTTPException(status_code=422, detail="timestamp out of range")
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


async def ingest(conn: AsyncConnection, env: Envelope, received_at: datetime) -> int:
    base = {"shop_id": env.shop_id, "session_id": env.session_id, "received_at": received_at}
    views: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    for e in env.events:
        if isinstance(e, PageView):
            views.append(
                {
                    **base,
                    "event_id": e.event_id,
                    "visitor_hash": env.visitor_hash,
                    "page_id": env.page_id,
                    "ts": _ts(e.ts),
                    "page_type": e.page_type,
                    "device": e.device,
                    "product_id": e.product_id,
                    "country": e.country,
                }
            )
        elif isinstance(e, RuleFired):
            decisions.append(
                {
                    **base,
                    "decision_id": e.decision_id,
                    "event_id": e.event_id,
                    "visitor_hash": env.visitor_hash,
                    "page_id": env.page_id,
                    "ts": _ts(e.ts),
                    "friction_state": e.friction_state,
                    "rule_id": e.rule_id,
                    "rule_version": e.rule_version,
                    "fire_seq": e.fire_seq,
                    "arm": e.arm,
                    "mode": e.mode,
                    "play": e.play,
                    "propensity": e.propensity,
                    "content_ref": e.content_ref,
                    "has_content": e.has_content,
                    "features": e.features,
                }
            )
        elif isinstance(e, PageSummary):
            summaries.append(
                {
                    **base,
                    "event_id": e.event_id,
                    "page_id": env.page_id,
                    "ts": _ts(e.ts),
                    "features": e.features,
                    "eval_count": e.eval_count,
                    "eval_p50_us": e.eval_p50_us,
                    "eval_max_us": e.eval_max_us,
                }
            )
        elif isinstance(e, Outcome):
            outcomes.append(
                {
                    **base,
                    "event_id": e.event_id,
                    "kind": e.kind,
                    "value": e.value,
                    "source": e.source,
                    "ts": _ts(e.ts),
                }
            )
    await repo.insert_page_views(conn, views)
    await repo.insert_decisions(conn, decisions)
    await repo.insert_summaries(conn, summaries)
    await repo.insert_outcomes(conn, outcomes)
    return len(env.events)
