"""Order webhook: verify the signature, pull out only the session id and order value."""

import base64
import hashlib
import hmac
import re
from decimal import Decimal, InvalidOperation
from typing import Any

SESSION_ATTRIBUTE = "ivay_sid"  # must match the SDK's cart attribute key
_SID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def verify_hmac(body: bytes, header: str | None, secret: str) -> bool:
    """Shopify signs the raw body with HMAC-SHA256 and sends it base64 encoded."""
    if not header or not secret:
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), header.strip())


def extract_order(payload: Any) -> tuple[str, Decimal | None] | None:
    """Return (session_id, order value) or None when the order carries no Ivay session.
    Nothing else from the payload is read, let alone stored."""
    if not isinstance(payload, dict):
        return None
    sid = None
    for attr in payload.get("note_attributes") or []:
        if isinstance(attr, dict) and attr.get("name") == SESSION_ATTRIBUTE:
            v = attr.get("value")
            if isinstance(v, str) and _SID.fullmatch(v):
                sid = v
            break
    if sid is None:
        return None
    value: Decimal | None = None
    raw = payload.get("total_price")
    if isinstance(raw, str | int | float) and not isinstance(raw, bool):
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            value = None
        if value is not None and (not value.is_finite() or value < 0):
            value = None
    return sid, value
