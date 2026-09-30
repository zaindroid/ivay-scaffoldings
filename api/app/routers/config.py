import logging

from fastapi import APIRouter, Request, Response

from app.guards import cors_headers
from app.routers.deps import known_shop
from app.services.config_builder import ConfigError, build_config
from app.settings import Settings

router = APIRouter(prefix="/v1")
log = logging.getLogger("ivay.config")


@router.get("/config/{shop_ref}")
async def get_config(shop_ref: str, request: Request) -> Response:
    """The SDK fetches `${configBase}/${shopId}.json`, so a trailing .json is accepted."""
    cfg: Settings = request.app.state.settings
    async with request.app.state.engine.connect() as conn:
        shop = await known_shop(request, conn, shop_ref.removesuffix(".json"))
    try:
        body, etag = build_config(shop, cfg.config_max_bytes)
    except ConfigError as e:
        log.error("config unavailable: %s", e)
        return Response(
            status_code=500,
            content='{"detail":"config unavailable"}',
            media_type="application/json",
        )
    headers = {
        "ETag": etag,
        "Cache-Control": f"public, max-age={cfg.config_cache_seconds}",
        **cors_headers(request.headers.get("origin"), shop.allowed_origins),
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)
