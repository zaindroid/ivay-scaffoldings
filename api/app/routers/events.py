import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response

from app.guards import cors_headers, parse_model, read_limited
from app.repositories.shops import all_allowed_origins
from app.routers.deps import authorised_shop
from app.schemas import Envelope
from app.services.ingest import ingest
from app.settings import Settings

router = APIRouter(prefix="/v1")
log = logging.getLogger("ivay.events")


@router.post("/events", status_code=204)
async def post_events(request: Request) -> Response:
    cfg: Settings = request.app.state.settings
    body = await read_limited(request, cfg.max_body_bytes)
    env = parse_model(body, Envelope)
    async with request.app.state.engine.begin() as conn:
        shop, origin = await authorised_shop(request, conn, env.shop_id)
        n = await ingest(conn, env, datetime.now(UTC))
    # Only the shop and a count are logged: no IP, no user agent, no payload.
    log.info("events shop=%s n=%d", shop.shop_id, n)
    return Response(status_code=204, headers=cors_headers(origin, shop.allowed_origins))


async def preflight(request: Request) -> Response:
    """The SDK sends text/plain (a simple request), so it never preflights. This answers the
    rare client that does, for any origin some shop allows; the POST itself is then checked
    against the one shop it names."""
    origin = request.headers.get("origin")
    async with request.app.state.engine.connect() as conn:
        allowed = await all_allowed_origins(conn)
    if origin is None or origin not in allowed:
        return Response(status_code=204)
    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "content-type",
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
        },
    )


router.add_api_route("/events", preflight, methods=["OPTIONS"], status_code=204)
