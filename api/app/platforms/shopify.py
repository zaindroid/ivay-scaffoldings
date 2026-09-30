"""Shopify implementation of the merchant audit, over the Admin GraphQL API.

Read-only: every operation here is a `query`. The HTTP layer is injected (a GraphQLClient), so
tests replay fixtures and never touch the network. Field names were checked against shopify.dev
(NOTES S12); the exact nesting is UNVERIFIED against a live shop (NOTES S13).
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx

from app.platforms.base import Coverage, ShippingCoverage

# Scopes needed: read_shipping (delivery profiles), read_legal_policies, read_products.
SHIPPING_QUERY = """
query IvayShippingAudit($cursor: String) {
  deliveryProfiles(first: 25, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      name
      profileLocationGroups {
        locationGroupZones(first: 50) {
          pageInfo { hasNextPage }
          nodes {
            zone { id name countries { code { countryCode restOfWorld } } }
            methodDefinitions(first: 50) {
              pageInfo { hasNextPage }
              nodes {
                id
                active
                rateProvider {
                  __typename
                  ... on DeliveryRateDefinition { price { amount currencyCode } }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

RETURNS_QUERY = """
query IvayReturnsAudit {
  shop { shopPolicies { type url body } }
}
"""

SIZING_QUERY = """
query IvaySizingAudit($cursor: String, $namespace: String!, $key: String!) {
  products(first: 100, after: $cursor, query: "status:active") {
    pageInfo { hasNextPage endCursor }
    nodes { id metafield(namespace: $namespace, key: $key) { value } }
  }
}
"""

QUERIES = (SHIPPING_QUERY, RETURNS_QUERY, SIZING_QUERY)
MAX_PAGES = 400  # 40,000 products: a runaway guard, reported as a warning if reached


class ShopifyError(Exception):
    """A failed Admin API call. Never carries the access token."""


class GraphQLClient(Protocol):
    async def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one query and return its `data`. Raises ShopifyError on any failure."""
        ...


class ShopifyAdminClient:
    """GraphQL over HTTPS with an injected httpx client."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        shop_domain: str,
        access_token: str,
        api_version: str = "2025-01",
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_retries: int = 3,
    ) -> None:
        self._http = http
        self._url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        self._token = access_token
        self._sleep = sleep
        self._max_retries = max_retries

    async def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            try:
                res = await self._http.post(
                    self._url,
                    json={"query": query, "variables": variables or {}},
                    headers={
                        "X-Shopify-Access-Token": self._token,
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as e:
                raise ShopifyError(f"request failed: {type(e).__name__}") from None
            throttled = res.status_code == 429
            body: dict[str, Any] = {}
            if res.status_code == 200:
                try:
                    body = res.json()
                except ValueError:
                    raise ShopifyError("response was not JSON") from None
                throttled = any(
                    (e.get("extensions") or {}).get("code") == "THROTTLED"
                    for e in body.get("errors") or []
                    if isinstance(e, dict)
                )
            if throttled and attempt < self._max_retries:
                wait = float(res.headers.get("Retry-After", 2 * (attempt + 1)))
                await self._sleep(wait)
                continue
            if res.status_code in (401, 403):
                raise ShopifyError(f"HTTP {res.status_code}: check the access token and scopes")
            if res.status_code != 200:
                raise ShopifyError(f"HTTP {res.status_code}")
            if body.get("errors"):
                messages = "; ".join(
                    str(e.get("message", e)) if isinstance(e, dict) else str(e)
                    for e in body["errors"]
                )
                raise ShopifyError(f"GraphQL errors: {messages}")
            data = body.get("data")
            if not isinstance(data, dict):
                raise ShopifyError("response had no data")
            return data
        raise ShopifyError("throttled")  # pragma: no cover (loop always returns or raises)


class ShopifyPlatform:
    def __init__(
        self, client: GraphQLClient, size_chart_metafield: str = "custom.size_chart"
    ) -> None:
        self._client = client
        namespace, _, key = size_chart_metafield.partition(".")
        if not namespace or not key:
            raise ValueError("size_chart_metafield must look like 'namespace.key'")
        self._ns, self._key = namespace, key

    async def _pages(
        self, query: str, root: str, variables: dict[str, Any] | None = None
    ) -> tuple[list[dict[str, Any]], bool]:
        """All nodes of a paginated root connection, and whether the page guard was hit."""
        nodes: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            data = await self._client.execute(query, {**(variables or {}), "cursor": cursor})
            conn = data[root]
            nodes.extend(conn["nodes"])
            if not conn["pageInfo"]["hasNextPage"]:
                return nodes, False
            cursor = conn["pageInfo"]["endCursor"]
        return nodes, True

    async def audit_shipping(self) -> ShippingCoverage:
        """A country counts as covered when, in every delivery profile that ships to it, a zone
        containing it has at least one active rate (a fixed price, even 0.00, or a carrier rate).
        The rest-of-world zone is not a country and is not counted."""
        profiles, capped = await self._pages(SHIPPING_QUERY, "deliveryProfiles")
        warnings: list[str] = []
        if capped:
            warnings.append("stopped at the page limit: shipping data is incomplete")
        listed: set[str] = set()
        incomplete: set[str] = set()
        for profile in profiles:
            has_rate: dict[str, bool] = {}
            for group in profile.get("profileLocationGroups") or []:
                zones = group["locationGroupZones"]
                if zones["pageInfo"]["hasNextPage"]:
                    warnings.append(f"profile {profile['id']}: more than 50 zones, rest not read")
                for zn in zones["nodes"]:
                    methods = zn["methodDefinitions"]
                    if methods["pageInfo"]["hasNextPage"]:
                        warnings.append(
                            f"profile {profile['id']}: a zone has more than 50 methods, "
                            "rest not read"
                        )
                    rated = any(_has_rate(m) for m in methods["nodes"])
                    for c in zn["zone"]["countries"]:
                        code = (c.get("code") or {}).get("countryCode")
                        if code:
                            has_rate[code] = has_rate.get(code, False) or rated
            for code, ok in has_rate.items():
                listed.add(code)
                if not ok:
                    incomplete.add(code)
        complete = sorted(listed - incomplete)
        return ShippingCoverage(
            covered=len(complete),
            total=len(listed),
            warnings=tuple(warnings),
            complete=tuple(complete),
            incomplete=tuple(sorted(incomplete)),
        )

    async def audit_returns(self) -> Coverage:
        data = await self._client.execute(RETURNS_QUERY)
        policies = (data.get("shop") or {}).get("shopPolicies") or []
        found = any(
            p.get("type") == "REFUND_POLICY" and str(p.get("body") or "").strip() for p in policies
        )
        return Coverage(covered=1 if found else 0, total=1)

    async def audit_sizing(self) -> Coverage:
        """Shopify has no native size chart object, so a product counts as covered when the
        configured metafield (default custom.size_chart) holds a non-empty value."""
        products, capped = await self._pages(
            SIZING_QUERY, "products", {"namespace": self._ns, "key": self._key}
        )
        covered = sum(
            1 for p in products if str((p.get("metafield") or {}).get("value") or "").strip()
        )
        warnings = ("stopped at the page limit: product data is incomplete",) if capped else ()
        return Coverage(covered=covered, total=len(products), warnings=warnings)


def _has_rate(method: dict[str, Any]) -> bool:
    if not method.get("active"):
        return False
    provider = method.get("rateProvider") or {}
    kind = provider.get("__typename")
    if kind == "DeliveryRateDefinition":
        return provider.get("price") is not None
    return kind == "DeliveryParticipant"  # carrier-calculated rate
