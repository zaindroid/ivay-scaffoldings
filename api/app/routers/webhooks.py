import json
import logging
import os
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response

from app.guards import read_limited
from app.repositories.events import upsert_webhook_order
from app.routers.deps import known_shop
from app.services.order_join import extract_order, verify_hmac
from app.settings import Settings

router = APIRouter(prefix="/v1")
log = logging.getLogger("ivay.webhooks")

# A shop row names the environment variable that holds its secret; only this prefix is read.
SECRET_PREFIX = "IVAY_WEBHOOK_SECRET_"
TOPICS = {"orders/create", "orders/paid"}


def _secret(ref: str | None) -> str | None:
    if not ref or not ref.startswith(SECRET_PREFIX):
        return None
    return os.environ.get(ref)


@router.post("/webhooks/shopify/orders", status_code=204)
async def shopify_orders(request: Request, shop_id: str) -> Response:
    """Order webhook: `?shop_id=` picks the shop, the HMAC proves the sender. Stores one
    order_completed outcome (session id and total) and nothing else from the order."""
    cfg: Settings = request.app.state.settings
    raw = await read_limited(request, cfg.webhook_max_body_bytes)
    async with request.app.state.engine.begin() as conn:
        shop = await known_shop(request, conn, shop_id)
        secret = _secret(shop.webhook_secret_ref)
        if secret is None:
            log.error("no webhook secret configured for shop=%s", shop.shop_id)
            raise HTTPException(status_code=401, detail="invalid signature")
        if not verify_hmac(raw, request.headers.get("x-shopify-hmac-sha256"), secret):
            raise HTTPException(status_code=401, detail="invalid signature")
        if request.headers.get("x-shopify-topic") not in TOPICS:
            return Response(status_code=204)
        try:
            payload = json.loads(raw)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid body") from None
        order = extract_order(payload)
        if order is None:
            return Response(status_code=204)  # an order without an Ivay session: nothing to join
        session_id, value = order
        await upsert_webhook_order(
            conn, shop_id=shop.shop_id, session_id=session_id, value=value, now=datetime.now(UTC)
        )
    log.info("order webhook shop=%s", shop.shop_id)
    return Response(status_code=204)
