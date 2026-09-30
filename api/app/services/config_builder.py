"""Builds the config the SDK fetches from a shop row (spec 7.1)."""

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from app.repositories.shops import ShopRow
from app.schemas import ShopConfig, dump


class ConfigError(Exception):
    """The stored config cannot be served. The message is for logs, never for clients."""


def build_config(shop: ShopRow, max_bytes: int) -> tuple[bytes, str]:
    """Return the canonical JSON body and its ETag. Output is validated against the contract,
    so a bad row can never reach an SDK."""
    try:
        cfg = ShopConfig.model_validate(shop.config)
    except ValidationError as e:
        raise ConfigError(
            f"stored config for {shop.shop_id} is invalid ({e.error_count()} errors)"
        ) from e
    if cfg.shop_id != shop.shop_id:
        raise ConfigError(f"stored config shop_id does not match row {shop.shop_id}")
    data: dict[str, Any] = dump(cfg)
    body = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
    if len(body) > max_bytes:
        raise ConfigError(f"config for {shop.shop_id} is {len(body)} bytes, limit {max_bytes}")
    etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
    return body, etag
