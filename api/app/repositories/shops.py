from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models import shop


@dataclass(frozen=True)
class ShopRow:
    shop_id: str
    platform: str
    allowed_origins: list[str]
    config: dict[str, Any]
    webhook_secret_ref: str | None


async def get_shop(conn: AsyncConnection, shop_id: str) -> ShopRow | None:
    row = (await conn.execute(select(shop).where(shop.c.shop_id == shop_id))).one_or_none()
    if row is None:
        return None
    return ShopRow(
        shop_id=row.shop_id,
        platform=row.platform,
        allowed_origins=list(row.allowed_origins),
        config=row.config,
        webhook_secret_ref=row.webhook_secret_ref,
    )


async def all_allowed_origins(conn: AsyncConnection) -> set[str]:
    rows = await conn.execute(select(shop.c.allowed_origins))
    return {o for (origins,) in rows for o in origins}
