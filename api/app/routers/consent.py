from fastapi import APIRouter, Request, Response

from app.guards import cors_headers, parse_model, read_limited
from app.repositories.events import increment_consent_ping
from app.routers.deps import authorised_shop
from app.routers.events import preflight
from app.schemas import ConsentPing
from app.settings import Settings

router = APIRouter(prefix="/v1")


@router.post("/consent-ping", status_code=204)
async def post_consent_ping(request: Request) -> Response:
    """Anonymous counter: `{ shop_id, consented }` and nothing else. Only a daily aggregate is
    kept, so there is no per-request row to link to anyone."""
    cfg: Settings = request.app.state.settings
    ping = parse_model(await read_limited(request, cfg.max_body_bytes), ConsentPing)
    async with request.app.state.engine.begin() as conn:
        shop, origin = await authorised_shop(request, conn, ping.shop_id)
        await increment_consent_ping(conn, shop.shop_id, ping.consented)
    return Response(status_code=204, headers=cors_headers(origin, shop.allowed_origins))


router.add_api_route("/consent-ping", preflight, methods=["OPTIONS"], status_code=204)
