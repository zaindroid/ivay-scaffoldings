"""Shared steps of the public endpoints: shop lookup, rate limit, origin check."""

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncConnection

from app.guards import RateLimiter, require_origin
from app.repositories.shops import ShopRow, get_shop

UNKNOWN = "__unknown__"


def limiter(request: Request) -> RateLimiter:
    lim: RateLimiter = request.app.state.limiter
    return lim


async def known_shop(request: Request, conn: AsyncConnection, shop_id: str) -> ShopRow:
    """Unknown shops are rejected. They share one rate-limit bucket, so probing ids cannot
    grow memory or bypass the limit."""
    shop = await get_shop(conn, shop_id)
    if shop is None:
        limiter(request).check(UNKNOWN)
        raise HTTPException(status_code=404, detail="unknown shop")
    limiter(request).check(shop.shop_id)
    return shop


async def authorised_shop(
    request: Request, conn: AsyncConnection, shop_id: str
) -> tuple[ShopRow, str]:
    """For browser POSTs: known shop, within its rate limit, from one of its own origins."""
    shop = await known_shop(request, conn, shop_id)
    return shop, require_origin(request, shop.allowed_origins)
