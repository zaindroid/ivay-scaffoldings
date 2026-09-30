"""Create or update the dev shop row. Idempotent. Usage: DATABASE_URL=... python scripts/seed_dev.py

The row holds the valid full fixture config, the demo store origins, and the *name* of the
environment variable that holds the webhook secret (never the secret).
"""

import asyncio
import json
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "postgresql+asyncpg://ivay:ivay_dev@127.0.0.1:5432/ivay"


async def main() -> None:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    api_port = os.environ.get("API_PORT", "8000")
    static_port = os.environ.get("STATIC_PORT", "8080")
    config = json.loads(
        (ROOT / "contracts" / "fixtures" / "valid" / "shop-config.full.json").read_text()
    )
    config["log_endpoint"] = f"http://localhost:{api_port}/v1/events"
    origins = [f"http://localhost:{static_port}", f"http://127.0.0.1:{static_port}"]
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO shop (shop_id, platform, allowed_origins, config, webhook_secret_ref) "
                "VALUES ('shop_dev', 'shopify', :origins, CAST(:cfg AS jsonb), "
                "'IVAY_WEBHOOK_SECRET_SHOP_DEV') "
                "ON CONFLICT (shop_id) DO UPDATE SET allowed_origins = :origins, "
                "config = CAST(:cfg AS jsonb), webhook_secret_ref = EXCLUDED.webhook_secret_ref"
            ),
            {"origins": origins, "cfg": json.dumps(config)},
        )
    await engine.dispose()
    print(f"shop_dev ready (origins {origins}, events -> {config['log_endpoint']})")


if __name__ == "__main__":
    asyncio.run(main())
