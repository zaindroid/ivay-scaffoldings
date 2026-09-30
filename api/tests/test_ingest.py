import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CONTRACTS_DIR, ORIGIN, Db, fixture_json, post_events

VALID = sorted(p.name for p in (CONTRACTS_DIR / "fixtures" / "valid").glob("event-envelope.*.json"))
INVALID = sorted(
    p.name for p in (CONTRACTS_DIR / "fixtures" / "invalid").glob("event-envelope.*.json")
)
TABLES = ["page_view", "decision_log", "page_summary", "outcome_event"]


def batch(events: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    b: dict[str, Any] = {
        "schema_version": "1.0",
        "shop_id": "shop_dev",
        "visitor_hash": "a" * 64,
        "session_id": "sess-aaaaaaaa",
        "page_id": "page-aaaaaaaa",
        "sent_at": 1790000000000,
        "events": events,
    }
    b.update(over)
    return b


def page_view(eid: str = "ev-pv-0001", ts: int = 1790000000000) -> dict[str, Any]:
    return {
        "type": "page_view",
        "event_id": eid,
        "ts": ts,
        "page_type": "product",
        "device": "desktop",
        "product_id": "4821",
        "country": "DE",
    }


@pytest.fixture
def shop(db: Db) -> Db:
    db.seed_shop()
    return db


class TestValidBatches:
    @pytest.mark.parametrize("name", VALID)
    def test_every_valid_fixture_is_accepted(self, client: TestClient, shop: Db, name: str) -> None:
        res = post_events(client, fixture_json("valid", name))
        assert res.status_code == 204, res.text
        assert res.content == b""

    def test_events_are_routed_to_their_tables(self, client: TestClient, shop: Db) -> None:
        res = post_events(
            client, fixture_json("valid", "event-envelope.rule-fired-and-summary.json")
        )
        assert res.status_code == 204
        assert shop.count("decision_log") == 1
        assert shop.count("page_summary") == 1
        assert (
            post_events(client, fixture_json("valid", "event-envelope.page-view.json")).status_code
            == 204
        )
        assert shop.count("page_view") == 1
        assert (
            post_events(
                client, fixture_json("valid", "event-envelope.sdk-outcome.json")
            ).status_code
            == 204
        )
        assert shop.count("outcome_event") >= 1
        d = shop.rows("SELECT * FROM decision_log")[0]
        assert d["friction_state"] and d["arm"] in ("holdout", "treatment")
        assert isinstance(d["features"], dict)
        assert d["visitor_hash"] and d["page_id"]

    def test_pixel_outcome_needs_no_visitor_or_page(self, client: TestClient, shop: Db) -> None:
        assert (
            post_events(
                client, fixture_json("valid", "event-envelope.pixel-outcome.json")
            ).status_code
            == 204
        )
        row = shop.rows("SELECT * FROM outcome_event")[0]
        assert row["source"] == "pixel" and row["kind"] in ("checkout_started", "order_completed")

    def test_text_plain_application_json_and_no_content_type_all_parse(
        self, client: TestClient, shop: Db
    ) -> None:
        for i, ct in enumerate(["text/plain;charset=UTF-8", "application/json", "text/plain", ""]):
            res = post_events(client, batch([page_view(f"ev-ct-{i:04d}")]), content_type=ct)
            assert res.status_code == 204, (ct, res.text)
        assert shop.count("page_view") == 4

    def test_received_at_is_server_time_and_client_ts_is_kept_separately(
        self, client: TestClient, shop: Db
    ) -> None:
        client_ts = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp() * 1000)
        assert post_events(client, batch([page_view(ts=client_ts)])).status_code == 204
        row = shop.rows("SELECT ts, received_at FROM page_view")[0]
        assert row["ts"] == datetime(2020, 1, 1, tzinfo=UTC)
        assert abs(datetime.now(UTC) - row["received_at"]) < timedelta(seconds=30)

    def test_a_full_hundred_event_batch(self, client: TestClient, shop: Db) -> None:
        events = [page_view(f"ev-big-{i:04d}") for i in range(100)]
        assert post_events(client, batch(events)).status_code == 204
        assert shop.count("page_view") == 100


class TestInvalidBatches:
    @pytest.mark.parametrize("name", INVALID)
    def test_every_invalid_fixture_is_422_and_stores_nothing(
        self, client: TestClient, shop: Db, name: str
    ) -> None:
        res = post_events(client, fixture_json("invalid", name))
        assert res.status_code == 422, name
        assert sum(shop.count(t) for t in TABLES) == 0

    def test_error_body_never_echoes_the_submitted_data(self, client: TestClient, shop: Db) -> None:
        bad = batch([{**page_view(), "device": "SECRET-DEVICE-VALUE"}])
        res = post_events(client, bad)
        assert res.status_code == 422
        assert "SECRET-DEVICE-VALUE" not in res.text

    @pytest.mark.parametrize(
        "body",
        [b"", b"not json", b"[]", b"null", b'{"a":', b"\xff\xfe\x00", b"[" * 30000 + b"]" * 30000],
        ids=["empty", "text", "array", "null", "truncated", "bad-utf8", "deeply-nested"],
    )
    def test_malformed_bodies_are_422(self, client: TestClient, shop: Db, body: bytes) -> None:
        assert post_events(client, body).status_code == 422

    def test_timestamp_out_of_range_is_422_and_rolls_back_the_whole_batch(
        self, client: TestClient, shop: Db
    ) -> None:
        res = post_events(
            client, batch([page_view("ev-ok-0001"), page_view("ev-bad-001", ts=10**15)])
        )
        assert res.status_code == 422
        assert shop.count("page_view") == 0

    def test_more_than_100_events_is_422(self, client: TestClient, shop: Db) -> None:
        events = [page_view(f"ev-big-{i:04d}") for i in range(101)]
        assert post_events(client, batch(events)).status_code == 422

    def test_bool_is_not_an_integer(self, client: TestClient, shop: Db) -> None:
        assert post_events(client, batch([page_view()], sent_at=True)).status_code == 422


class TestIdempotency:
    def test_duplicate_event_ids_change_nothing(self, client: TestClient, shop: Db) -> None:
        body = fixture_json("valid", "event-envelope.rule-fired-and-summary.json")
        assert post_events(client, body).status_code == 204
        before = {t: shop.count(t) for t in TABLES}
        for _ in range(3):
            assert post_events(client, body).status_code == 204
        assert {t: shop.count(t) for t in TABLES} == before

    def test_a_partly_repeated_batch_inserts_only_the_new_events(
        self, client: TestClient, shop: Db
    ) -> None:
        assert post_events(client, batch([page_view("ev-dup-0001")])).status_code == 204
        res = post_events(client, batch([page_view("ev-dup-0001"), page_view("ev-dup-0002")]))
        assert res.status_code == 204
        assert shop.count("page_view") == 2

    def test_a_repeated_decision_id_is_ignored(self, client: TestClient, shop: Db) -> None:
        body = fixture_json("valid", "event-envelope.rule-fired-and-summary.json")
        post_events(client, body)
        again = json.loads(json.dumps(body))
        for e in again["events"]:
            e["event_id"] = e["event_id"] + "x"
        assert post_events(client, again).status_code == 204
        assert shop.count("decision_log") == 1


class TestShopAndOrigin:
    def test_unknown_shop_is_404_and_stores_nothing(self, client: TestClient, shop: Db) -> None:
        res = post_events(client, batch([page_view()], shop_id="no_such_shop"))
        assert res.status_code == 404
        assert shop.count("page_view") == 0

    def test_wrong_origin_is_403(self, client: TestClient, shop: Db) -> None:
        res = post_events(client, batch([page_view()]), origin="https://evil.example")
        assert res.status_code == 403
        assert shop.count("page_view") == 0

    def test_missing_origin_is_403(self, client: TestClient, shop: Db) -> None:
        assert post_events(client, batch([page_view()]), origin=None).status_code == 403

    def test_origin_must_match_exactly(self, client: TestClient, shop: Db) -> None:
        for o in [ORIGIN + ".evil.example", "http://shop.example", ORIGIN + "/", ORIGIN.upper()]:
            assert post_events(client, batch([page_view()]), origin=o).status_code == 403, o

    def test_cors_is_per_shop_never_a_wildcard(self, client: TestClient, shop: Db) -> None:
        res = post_events(client, batch([page_view()]))
        assert res.headers["access-control-allow-origin"] == ORIGIN
        assert res.headers["vary"] == "Origin"

    def test_one_shops_origin_cannot_write_to_another_shop(
        self, client: TestClient, db: Db
    ) -> None:
        db.seed_shop("shop_a", origins=["https://a.example"])
        db.seed_shop("shop_b", origins=["https://b.example"])
        ok = post_events(
            client, batch([page_view("ev-a-00001")], shop_id="shop_a"), origin="https://a.example"
        )
        assert ok.status_code == 204
        cross = post_events(
            client, batch([page_view("ev-b-00001")], shop_id="shop_b"), origin="https://a.example"
        )
        assert cross.status_code == 403
        assert db.count("page_view") == 1

    def test_shop_with_several_origins(self, client: TestClient, db: Db) -> None:
        db.seed_shop(origins=["https://a.example", "https://b.example"])
        for i, o in enumerate(["https://a.example", "https://b.example"]):
            assert (
                post_events(client, batch([page_view(f"ev-mo-{i:04d}")]), origin=o).status_code
                == 204
            )

    def test_preflight_allows_only_origins_some_shop_allows(
        self, client: TestClient, shop: Db
    ) -> None:
        ok = client.options(
            "/v1/events", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"}
        )
        assert ok.status_code == 204
        assert ok.headers["access-control-allow-origin"] == ORIGIN
        bad = client.options("/v1/events", headers={"Origin": "https://evil.example"})
        assert bad.status_code == 204
        assert "access-control-allow-origin" not in bad.headers


class TestLimits:
    def test_body_over_64kb_is_413(self, client: TestClient, shop: Db) -> None:
        body = json.dumps(batch([page_view()], padding="x" * 70000)).encode()
        assert len(body) > 65536
        assert post_events(client, body).status_code == 413
        assert shop.count("page_view") == 0

    def test_body_over_limit_without_content_length_is_413(
        self, client: TestClient, shop: Db
    ) -> None:
        def chunks() -> Any:
            for _ in range(8):
                yield b"x" * 10000

        res = client.post("/v1/events", content=chunks(), headers={"Origin": ORIGIN})
        assert res.status_code == 413

    def test_body_just_under_the_limit_is_read(self, client: TestClient, shop: Db) -> None:
        body = json.dumps(batch([page_view()])).encode()
        padded = body[:-1] + b" " * (65536 - len(body)) + b"}"
        assert len(padded) == 65536
        assert post_events(client, padded).status_code == 204

    def test_rate_limit_per_shop_with_retry_after(
        self, make_client: Callable[..., TestClient], db: Db
    ) -> None:
        db.seed_shop("shop_a", origins=["https://a.example"])
        db.seed_shop("shop_b", origins=["https://b.example"])
        c = make_client(rate_limit_per_minute=3)
        for i in range(3):
            assert (
                post_events(
                    c,
                    batch([page_view(f"ev-rl-{i:04d}")], shop_id="shop_a"),
                    origin="https://a.example",
                ).status_code
                == 204
            )
        res = post_events(
            c, batch([page_view("ev-rl-9999")], shop_id="shop_a"), origin="https://a.example"
        )
        assert res.status_code == 429
        assert int(res.headers["retry-after"]) >= 1
        other = post_events(
            c, batch([page_view("ev-rl-b001")], shop_id="shop_b"), origin="https://b.example"
        )
        assert other.status_code == 204  # another shop is unaffected

    def test_rate_limit_window_slides(self, make_client: Callable[..., TestClient], db: Db) -> None:
        db.seed_shop()
        c = make_client(rate_limit_per_minute=2)
        now = [1000.0]
        c.app.state.limiter.clock = lambda: now[0]  # type: ignore[attr-defined]
        assert post_events(c, batch([page_view("ev-sw-0001")])).status_code == 204
        assert post_events(c, batch([page_view("ev-sw-0002")])).status_code == 204
        assert post_events(c, batch([page_view("ev-sw-0003")])).status_code == 429
        now[0] += 61
        assert post_events(c, batch([page_view("ev-sw-0003")])).status_code == 204

    def test_unknown_shops_share_one_bucket(
        self, make_client: Callable[..., TestClient], db: Db
    ) -> None:
        c = make_client(rate_limit_per_minute=2)
        codes = [
            post_events(c, batch([page_view()], shop_id=f"ghost_{i}")).status_code for i in range(4)
        ]
        assert codes == [404, 404, 429, 429]


class TestPrivacy:
    def test_no_column_holds_an_ip_address_or_user_agent(self, shop: Db) -> None:
        cols = shop.rows(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        )
        for c in cols:
            name = c["column_name"].lower()
            assert "ip" not in name.split("_"), c
            assert "user_agent" not in name and "useragent" not in name and "ua" != name, c
            assert "address" not in name and "email" not in name, c

    def test_ip_and_user_agent_are_neither_stored_nor_logged(
        self, client: TestClient, shop: Db, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level("DEBUG")
        res = post_events(
            client,
            batch([page_view()]),
            extra_headers={
                "User-Agent": "SECRET-UA-STRING/1.0",
                "X-Forwarded-For": "203.0.113.77",
            },
        )
        assert res.status_code == 204
        stored = shop.dump_all()
        logs = "\n".join(r.getMessage() for r in caplog.records)
        for needle in ("SECRET-UA-STRING", "203.0.113.77", "testclient", "127.0.0.1"):
            assert needle not in stored, needle
            assert needle not in logs, needle
        assert "events shop=shop_dev n=1" in logs  # only the shop and a count

    def test_failed_requests_do_not_log_the_payload(
        self, client: TestClient, shop: Db, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level("DEBUG")
        post_events(client, batch([{**page_view(), "device": "SECRET-DEVICE-VALUE"}]))
        assert "SECRET-DEVICE-VALUE" not in "\n".join(r.getMessage() for r in caplog.records)

    def test_docs_and_openapi_are_not_exposed(self, client: TestClient) -> None:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404
