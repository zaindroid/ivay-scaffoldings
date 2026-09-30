import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.platforms.base import Coverage, MerchantPlatform, ShippingCoverage
from app.platforms.replay import SAMPLE_DIR, ReplayClient
from app.platforms.shopify import (
    QUERIES,
    ShopifyAdminClient,
    ShopifyError,
    ShopifyPlatform,
)
from app.platforms.shopware import ShopwarePlatform
from tests.conftest import API_DIR

REPO = API_DIR.parent
SCRIPT = REPO / "scripts" / "audit_merchant_data.py"


def sample() -> ReplayClient:
    return ReplayClient.from_file(SAMPLE_DIR / "dry_run.json")


def sample_data() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((SAMPLE_DIR / "dry_run.json").read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return data


class TestCoverage:
    def test_share(self) -> None:
        assert Coverage(1, 4).share == 0.25
        assert Coverage(0, 0).share is None
        assert Coverage(3, 3).share == 1.0


class TestShopifyAudit:
    async def test_shipping_counts_a_country_only_when_every_profile_that_ships_there_has_a_rate(
        self,
    ) -> None:
        r = await ShopifyPlatform(sample()).audit_shipping()
        # DE: rated in the general profile but the bulky profile has no method -> incomplete.
        # AT: rated. FR: carrier-calculated rate. CH: only an inactive method -> incomplete.
        # Rest of world is not a country and is not counted.
        assert (r.covered, r.total) == (2, 4)
        assert r.complete == ("AT", "FR")
        assert r.incomplete == ("CH", "DE")
        assert r.share == 0.5

    async def test_shipping_reads_every_page(self) -> None:
        client = sample()
        await ShopifyPlatform(client).audit_shipping()
        ops = [(op, v["cursor"]) for op, v in client.calls]
        assert ops == [("IvayShippingAudit", None), ("IvayShippingAudit", "cursor-1")]

    async def test_a_free_rate_of_zero_is_a_rate(self) -> None:
        data = sample_data()
        node = data["IvayShippingAudit"][0]["deliveryProfiles"]["nodes"][0]
        zone = node["profileLocationGroups"][0]["locationGroupZones"]["nodes"][0]
        zone["methodDefinitions"]["nodes"] = [
            {
                "id": "m",
                "active": True,
                "rateProvider": {
                    "__typename": "DeliveryRateDefinition",
                    "price": {"amount": "0.0", "currencyCode": "EUR"},
                },
            }
        ]
        data["IvayShippingAudit"][1]["deliveryProfiles"]["nodes"] = []
        r = await ShopifyPlatform(ReplayClient(data)).audit_shipping()
        assert "DE" in r.complete and "AT" in r.complete

    async def test_no_delivery_profiles_is_zero_of_zero(self) -> None:
        empty = {
            "deliveryProfiles": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}
        }
        r = await ShopifyPlatform(ReplayClient({"IvayShippingAudit": [empty]})).audit_shipping()
        assert (r.covered, r.total, r.share) == (0, 0, None)

    async def test_truncated_nested_pages_are_reported_not_hidden(self) -> None:
        data = sample_data()
        node = data["IvayShippingAudit"][0]["deliveryProfiles"]["nodes"][0]
        group = node["profileLocationGroups"][0]["locationGroupZones"]
        group["pageInfo"]["hasNextPage"] = True
        group["nodes"][0]["methodDefinitions"]["pageInfo"]["hasNextPage"] = True
        r = await ShopifyPlatform(ReplayClient(data)).audit_shipping()
        assert len(r.warnings) == 2
        assert any("more than 50 zones" in w for w in r.warnings)
        assert any("more than 50 methods" in w for w in r.warnings)

    async def test_returns_policy_present(self) -> None:
        r = await ShopifyPlatform(sample()).audit_returns()
        assert (r.covered, r.total) == (1, 1)

    @pytest.mark.parametrize(
        "policies",
        [
            [],
            [{"type": "SHIPPING_POLICY", "url": "u", "body": "text"}],
            [{"type": "REFUND_POLICY", "url": "u", "body": ""}],
            [{"type": "REFUND_POLICY", "url": "u", "body": "   \n"}],
            [{"type": "REFUND_POLICY", "url": "u", "body": None}],
        ],
        ids=["none", "other-type-only", "empty-body", "blank-body", "null-body"],
    )
    async def test_returns_policy_absent_or_empty(self, policies: list[dict[str, Any]]) -> None:
        client = ReplayClient({"IvayReturnsAudit": [{"shop": {"shopPolicies": policies}}]})
        r = await ShopifyPlatform(client).audit_returns()
        assert (r.covered, r.total) == (0, 1)

    async def test_sizing_counts_products_whose_metafield_has_a_value(self) -> None:
        client = sample()
        r = await ShopifyPlatform(client).audit_sizing()
        assert (r.covered, r.total) == (2, 5)
        assert r.share == 0.4
        assert [c[1]["cursor"] for c in client.calls] == [None, "cursor-p1"]

    async def test_sizing_uses_the_configured_metafield(self) -> None:
        client = sample()
        await ShopifyPlatform(client, size_chart_metafield="my_ns.chart").audit_sizing()
        assert client.calls[0][1]["namespace"] == "my_ns"
        assert client.calls[0][1]["key"] == "chart"

    def test_a_malformed_metafield_setting_is_refused(self) -> None:
        for bad in ("nokey", ".key", "ns."):
            with pytest.raises(ValueError):
                ShopifyPlatform(sample(), size_chart_metafield=bad)

    async def test_a_replay_with_no_recorded_operation_fails_loudly(self) -> None:
        with pytest.raises(ShopifyError):
            await ShopifyPlatform(ReplayClient({})).audit_returns()

    def test_the_audit_only_sends_queries_never_mutations(self) -> None:
        assert len(QUERIES) == 3
        for q in QUERIES:
            stripped = q.strip()
            assert stripped.startswith("query "), stripped[:30]
            assert not re.search(r"\bmutation\b", q, re.IGNORECASE)
            assert not re.search(r"\bsubscription\b", q, re.IGNORECASE)

    def test_platforms_satisfy_the_protocol(self) -> None:
        shopify: MerchantPlatform = ShopifyPlatform(sample())
        shopware: MerchantPlatform = ShopwarePlatform()
        assert shopify and shopware

    def test_shipping_result_type(self) -> None:
        assert issubclass(ShippingCoverage, Coverage)


class TestShopware:
    async def test_every_audit_raises_not_implemented(self) -> None:
        p = ShopwarePlatform()
        for call in (p.audit_shipping, p.audit_returns, p.audit_sizing):
            with pytest.raises(NotImplementedError):
                await call()


def http_client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestAdminClient:
    async def test_posts_the_query_to_the_versioned_endpoint_with_the_token_header(self) -> None:
        seen: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen.append(req)
            return httpx.Response(200, json={"data": {"ok": True}})

        async with http_client(handler) as http:
            client = ShopifyAdminClient(http, "shop.myshopify.com", "tok-123", "2025-01")
            data = await client.execute("query Q { a }", {"x": 1})
        assert data == {"ok": True}
        req = seen[0]
        assert req.method == "POST"
        assert str(req.url) == "https://shop.myshopify.com/admin/api/2025-01/graphql.json"
        assert req.headers["x-shopify-access-token"] == "tok-123"
        assert json.loads(req.content) == {"query": "query Q { a }", "variables": {"x": 1}}

    async def test_graphql_errors_raise_with_the_messages(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"errors": [{"message": "Field 'x' doesn't exist"}]})

        async with http_client(handler) as http:
            with pytest.raises(ShopifyError, match="Field 'x' doesn't exist"):
                await ShopifyAdminClient(http, "s.myshopify.com", "t").execute("query Q { x }")

    @pytest.mark.parametrize("status", [401, 403])
    async def test_auth_failures_name_the_cause_and_never_the_token(self, status: int) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(status, text="nope")

        async with http_client(handler) as http:
            with pytest.raises(ShopifyError) as e:
                await ShopifyAdminClient(http, "s.myshopify.com", "SECRET-TOKEN").execute(
                    "query Q { x }"
                )
        assert "token" in str(e.value) and "SECRET-TOKEN" not in str(e.value)

    async def test_other_http_errors_and_bad_bodies(self) -> None:
        for resp, match in (
            (httpx.Response(500), "HTTP 500"),
            (httpx.Response(200, text="<html>"), "not JSON"),
            (httpx.Response(200, json={"data": None}), "no data"),
        ):
            async with http_client(lambda req, r=resp: r) as http:
                with pytest.raises(ShopifyError, match=match):
                    await ShopifyAdminClient(http, "s.myshopify.com", "t").execute("query Q { x }")

    async def test_network_failure_never_leaks_the_token(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom SECRET-TOKEN")

        async with http_client(handler) as http:
            with pytest.raises(ShopifyError) as e:
                await ShopifyAdminClient(http, "s.myshopify.com", "SECRET-TOKEN").execute(
                    "query Q { x }"
                )
        assert "SECRET-TOKEN" not in str(e.value)
        assert e.value.__cause__ is None

    async def test_throttled_responses_are_retried_then_succeed(self) -> None:
        calls = 0
        sleeps: list[float] = []

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429, headers={"Retry-After": "3"})
            if calls == 2:
                return httpx.Response(
                    200,
                    json={
                        "errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]
                    },
                )
            return httpx.Response(200, json={"data": {"ok": 1}})

        async def fake_sleep(s: float) -> None:
            sleeps.append(s)

        async with http_client(handler) as http:
            client = ShopifyAdminClient(http, "s.myshopify.com", "t", sleep=fake_sleep)
            assert await client.execute("query Q { x }") == {"ok": 1}
        assert calls == 3
        assert sleeps[0] == 3.0 and len(sleeps) == 2

    async def test_gives_up_after_the_retry_limit(self) -> None:
        async def fake_sleep(s: float) -> None:
            return None

        async with http_client(lambda req: httpx.Response(429)) as http:
            client = ShopifyAdminClient(
                http, "s.myshopify.com", "t", sleep=fake_sleep, max_retries=2
            )
            with pytest.raises(ShopifyError):
                await client.execute("query Q { x }")

    async def test_end_to_end_platform_over_a_mock_transport(self) -> None:
        data = sample_data()

        def handler(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content)
            op = re.search(r"query\s+(\w+)", body["query"])
            assert op is not None
            page = data[op.group(1)].pop(0)
            return httpx.Response(200, json={"data": page})

        async with http_client(handler) as http:
            platform = ShopifyPlatform(ShopifyAdminClient(http, "s.myshopify.com", "t"))
            assert (await platform.audit_shipping()).covered == 2
            assert (await platform.audit_returns()).covered == 1
            assert (await platform.audit_sizing()).covered == 2


def run_script(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if not k.startswith("SHOPIFY_")}
    clean.update(env or {})
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=clean,
        timeout=60,
        cwd=str(Path(SCRIPT).parent),
    )


class TestAuditScript:
    def test_dry_mode_runs_without_credentials_or_network(self) -> None:
        res = run_script("--dry")
        assert res.returncode == 0, res.stderr
        out = res.stdout
        assert "DRY RUN" in out
        assert "delivery_uncertainty: shipping countries with complete rates: 2/4 (50%)" in out
        assert "complete: AT, FR; incomplete: CH, DE" in out
        assert "returns_uncertainty: return policy exists: 1/1 (100%)" in out
        assert "sizing_uncertainty: products with a size chart: 2/5 (40%)" in out

    def test_dry_mode_json(self) -> None:
        res = run_script("--dry", "--json")
        assert res.returncode == 0, res.stderr
        doc = json.loads(res.stdout)
        assert doc["dry_run"] is True
        assert doc["coverage"]["sizing_uncertainty"]["covered"] == 2
        assert doc["coverage"]["delivery_uncertainty"]["incomplete"] == ["CH", "DE"]

    def test_without_credentials_it_exits_with_a_clear_message(self) -> None:
        res = run_script()
        assert res.returncode == 2
        assert "SHOPIFY_SHOP_DOMAIN" in res.stderr and "SHOPIFY_ADMIN_TOKEN" in res.stderr
        assert "--dry" in res.stderr
        assert res.stdout == ""

    def test_one_missing_credential_is_still_a_clear_refusal(self) -> None:
        res = run_script(env={"SHOPIFY_SHOP_DOMAIN": "s.myshopify.com"})
        assert res.returncode == 2 and "SHOPIFY_ADMIN_TOKEN" in res.stderr

    def test_the_script_contains_no_mutation(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        assert not re.search(r"\bmutation\b", text, re.IGNORECASE)
