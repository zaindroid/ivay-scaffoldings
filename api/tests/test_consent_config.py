import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from tests.conftest import CONTRACTS_DIR, ORIGIN, Db, fixture_json, full_config


def ping(client: TestClient, body: Any, origin: str | None = ORIGIN) -> Any:
    headers = {"Content-Type": "text/plain;charset=UTF-8"}
    if origin:
        headers["Origin"] = origin
    return client.post("/v1/consent-ping", content=json.dumps(body), headers=headers)


class TestConsentPing:
    def test_counts_per_day_and_outcome_with_no_per_request_rows(
        self, client: TestClient, db: Db
    ) -> None:
        db.seed_shop()
        for consented in (True, True, False):
            assert ping(client, {"shop_id": "shop_dev", "consented": consented}).status_code == 204
        rows = db.rows("SELECT consented, count FROM consent_ping_daily ORDER BY consented")
        assert rows == [{"consented": False, "count": 1}, {"consented": True, "count": 2}]

    def test_only_shop_id_and_consented_are_accepted(self, client: TestClient, db: Db) -> None:
        db.seed_shop()
        for body in (
            {"shop_id": "shop_dev", "consented": True, "visitor": "x"},
            {"shop_id": "shop_dev"},
            {"consented": True},
            {"shop_id": "shop_dev", "consented": "yes"},
            {"shop_id": "shop_dev", "consented": 1},
        ):
            assert ping(client, body).status_code == 422, body
        assert db.count("consent_ping_daily") == 0

    def test_origin_and_shop_are_enforced(self, client: TestClient, db: Db) -> None:
        db.seed_shop()
        assert (
            ping(
                client, {"shop_id": "shop_dev", "consented": True}, origin="https://evil.example"
            ).status_code
            == 403
        )
        assert (
            ping(client, {"shop_id": "shop_dev", "consented": True}, origin=None).status_code == 403
        )
        assert ping(client, {"shop_id": "nope", "consented": True}).status_code == 404
        assert db.count("consent_ping_daily") == 0

    def test_response_has_per_shop_cors(self, client: TestClient, db: Db) -> None:
        db.seed_shop()
        res = ping(client, {"shop_id": "shop_dev", "consented": True})
        assert res.headers["access-control-allow-origin"] == ORIGIN

    def test_table_has_no_identifier_columns(self, db: Db) -> None:
        cols = {
            r["column_name"]
            for r in db.rows(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'consent_ping_daily'"
            )
        }
        assert cols == {"shop_id", "day", "consented", "count"}


class TestConfig:
    def test_serves_the_shop_config_matching_the_contract(self, client: TestClient, db: Db) -> None:
        db.seed_shop()
        res = client.get("/v1/config/shop_dev")
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/json"
        body = res.json()
        schema = json.loads((CONTRACTS_DIR / "shop-config.schema.json").read_text())
        assert list(Draft202012Validator(schema).iter_errors(body)) == []
        assert body == full_config()

    def test_the_sdk_url_with_a_json_suffix_works(self, client: TestClient, db: Db) -> None:
        db.seed_shop()
        assert client.get("/v1/config/shop_dev.json").json()["shop_id"] == "shop_dev"

    def test_cache_headers_and_conditional_get(
        self, make_client: Callable[..., TestClient], db: Db
    ) -> None:
        db.seed_shop()
        c = make_client(config_cache_seconds=45)
        res = c.get("/v1/config/shop_dev")
        assert res.headers["cache-control"] == "public, max-age=45"
        etag = res.headers["etag"]
        again = c.get("/v1/config/shop_dev", headers={"If-None-Match": etag})
        assert again.status_code == 304
        assert again.content == b""
        stale = c.get("/v1/config/shop_dev", headers={"If-None-Match": '"other"'})
        assert stale.status_code == 200

    def test_etag_changes_when_the_config_changes(self, client: TestClient, db: Db) -> None:
        db.seed_shop()
        first = client.get("/v1/config/shop_dev").headers["etag"]
        cfg = full_config()
        cfg["kill_switch"] = True
        db.execute("UPDATE shop SET config = CAST(:c AS jsonb)", c=json.dumps(cfg))
        res = client.get("/v1/config/shop_dev")
        assert res.headers["etag"] != first
        assert res.json()["kill_switch"] is True

    def test_unknown_shop_is_404(self, client: TestClient, db: Db) -> None:
        assert client.get("/v1/config/ghost").status_code == 404

    def test_cors_only_for_the_shops_own_origin(self, client: TestClient, db: Db) -> None:
        db.seed_shop()
        ok = client.get("/v1/config/shop_dev", headers={"Origin": ORIGIN})
        assert ok.headers["access-control-allow-origin"] == ORIGIN
        bad = client.get("/v1/config/shop_dev", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in bad.headers
        none = client.get("/v1/config/shop_dev")
        assert "access-control-allow-origin" not in none.headers

    def test_an_invalid_stored_config_is_a_generic_500_never_served(
        self, client: TestClient, db: Db
    ) -> None:
        bad = full_config()
        bad["mode"] = "banana"
        db.seed_shop(config=bad)
        res = client.get("/v1/config/shop_dev")
        assert res.status_code == 500
        assert "banana" not in res.text

    def test_a_config_for_another_shop_is_refused(self, client: TestClient, db: Db) -> None:
        db.seed_shop("shop_dev", config=full_config("someone_else"))
        assert client.get("/v1/config/shop_dev").status_code == 500

    def test_a_config_over_the_size_limit_is_refused(
        self, make_client: Callable[..., TestClient], db: Db
    ) -> None:
        db.seed_shop()
        assert make_client(config_max_bytes=200).get("/v1/config/shop_dev").status_code == 500

    def test_the_default_size_limit_is_50_kb_and_the_full_fixture_fits(
        self, client: TestClient, db: Db
    ) -> None:
        db.seed_shop()
        body = client.get("/v1/config/shop_dev").content
        assert len(body) < 50 * 1024

    def test_kill_switch_fixture_is_served(self, client: TestClient, db: Db) -> None:
        db.seed_shop(config=fixture_json("valid", "shop-config.kill-switch.json"))
        shop_id = fixture_json("valid", "shop-config.kill-switch.json")["shop_id"]
        res = client.get(f"/v1/config/{shop_id}")
        assert res.status_code == 200 and res.json()["kill_switch"] is True

    @pytest.mark.parametrize("path", ["/v1/config/", "/v1/config"])
    def test_missing_shop_id_is_404(self, client: TestClient, path: str) -> None:
        assert client.get(path).status_code in (404, 405)
