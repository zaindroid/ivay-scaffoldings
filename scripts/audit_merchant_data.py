"""Read-only audit of what a merchant's own data can answer, per friction state.

  python scripts/audit_merchant_data.py --dry      # sample data, no network, no credentials
  SHOPIFY_SHOP_DOMAIN=shop.myshopify.com SHOPIFY_ADMIN_TOKEN=... \\
      python scripts/audit_merchant_data.py        # live, queries only

Live runs need an Admin API token with the scopes read_shipping, read_legal_policies and
read_products. Optional: SHOPIFY_API_VERSION (default 2025-01) and SHOPIFY_SIZE_CHART_METAFIELD
(default custom.size_chart). The script only ever sends GraphQL queries.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import httpx  # noqa: E402

from app.platforms.base import MerchantPlatform, ShippingCoverage  # noqa: E402
from app.platforms.replay import SAMPLE_DIR, ReplayClient  # noqa: E402
from app.platforms.shopify import (  # noqa: E402
    GraphQLClient,
    ShopifyAdminClient,
    ShopifyError,
    ShopifyPlatform,
)

MISSING = (
    "No credentials: set SHOPIFY_SHOP_DOMAIN (for example my-shop.myshopify.com) and "
    "SHOPIFY_ADMIN_TOKEN in the environment, or run with --dry to use sample data."
)


async def audit(platform: MerchantPlatform) -> dict[str, Any]:
    shipping = await platform.audit_shipping()
    returns = await platform.audit_returns()
    sizing = await platform.audit_sizing()
    return {
        "delivery_uncertainty": {
            "what": "shipping countries with complete rates",
            "covered": shipping.covered,
            "total": shipping.total,
            "share": shipping.share,
            "complete": list(shipping.complete) if isinstance(shipping, ShippingCoverage) else [],
            "incomplete": (
                list(shipping.incomplete) if isinstance(shipping, ShippingCoverage) else []
            ),
            "warnings": list(shipping.warnings),
        },
        "returns_uncertainty": {
            "what": "return policy exists",
            "covered": returns.covered,
            "total": returns.total,
            "share": returns.share,
            "warnings": list(returns.warnings),
        },
        "sizing_uncertainty": {
            "what": "products with a size chart",
            "covered": sizing.covered,
            "total": sizing.total,
            "share": sizing.share,
            "warnings": list(sizing.warnings),
        },
    }


def render(result: dict[str, Any], dry: bool) -> str:
    lines = []
    if dry:
        lines.append("DRY RUN: sample data from api/app/platforms/sample_data, not a real shop")
    for state, r in result.items():
        share = "n/a" if r["share"] is None else f"{r['share']:.0%}"
        lines.append(f"{state}: {r['what']}: {r['covered']}/{r['total']} ({share})")
        if r.get("complete") or r.get("incomplete"):
            lines.append(
                f"    complete: {', '.join(r['complete']) or '-'}; "
                f"incomplete: {', '.join(r['incomplete']) or '-'}"
            )
        for w in r["warnings"]:
            lines.append(f"    WARNING: {w}")
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    if args.dry:
        client: GraphQLClient = ReplayClient.from_file(SAMPLE_DIR / "dry_run.json")
        platform = ShopifyPlatform(client)
        print_result(await audit(platform), True, args.json)
        return 0
    domain = os.environ.get("SHOPIFY_SHOP_DOMAIN")
    token = os.environ.get("SHOPIFY_ADMIN_TOKEN")
    if not domain or not token:
        print(MISSING, file=sys.stderr)
        return 2
    async with httpx.AsyncClient(timeout=30) as http:
        live = ShopifyAdminClient(
            http, domain, token, os.environ.get("SHOPIFY_API_VERSION", "2025-01")
        )
        platform = ShopifyPlatform(
            live, os.environ.get("SHOPIFY_SIZE_CHART_METAFIELD", "custom.size_chart")
        )
        try:
            result = await audit(platform)
        except ShopifyError as e:
            print(f"Audit failed: {e}", file=sys.stderr)
            return 1
    print_result(result, False, args.json)
    return 0


def print_result(result: dict[str, Any], dry: bool, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"dry_run": dry, "coverage": result}, indent=2))
    else:
        print(render(result, dry))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry", action="store_true", help="use sample data, no network")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
