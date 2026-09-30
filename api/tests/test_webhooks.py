import base64
import hashlib
import hmac
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import ORIGIN, Db, post_events

SECRET = "whsec-test-secret"
REF = "IVAY_WEBHOOK_SECRET_SHOP_DEV"
SID = "a1b2c3d4e5f6a7b8c9d0e1f2"


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REF, SECRET)


@pytest.fixture
def shop(db: Db) -> Db:
    db.seed_shop(secret_ref=REF)
    return db


def sign(body: bytes, secret: str = SECRET) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def order(sid: str | None = SID, total: str = "129.50", **extra: Any) -> dict[str, Any]:
    o: dict[str, Any] = {
        "id": 820982911946154508,
        "total_price": total,
        "email": "jane.doe@example.com",
        "shipping_address": {"city": "Bonn", "address1": "Musterstrasse 1"},
        "line_items": [{"title": "Ivay Tee", "price": "29.00"}],
        "customer": {"first_name": "Jane", "last_name": "Doe"},
        "note_attributes": [{"name": "gift", "value": "no"}],
    }
    if sid is not None:
        o["note_attributes"].append({"name": "ivay_sid", "value": sid})
    o.update(extra)
    return o


def webhook(
    client: TestClient,
    payload: Any,
    *,
    secret: str = SECRET,
    topic: str | None = "orders/create",
    shop_id: str = "shop_dev",
    signature: str | None = "auto",
    raw: bytes | None = None,
) -> Any:
    body = raw if raw is not None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signature == "auto":
        headers["X-Shopify-Hmac-SHA256"] = sign(body, secret)
    elif signature is not None:
        headers["X-Shopify-Hmac-SHA256"] = signature
    if topic:
        headers["X-Shopify-Topic"] = topic
    return client.post(
        f"/v1/webhooks/shopify/orders?shop_id={shop_id}", content=body, headers=headers
    )


class TestHmac:
    def test_valid_signature_writes_an_order_completed_outcome(
        self, client: TestClient, shop: Db
    ) -> None:
        assert webhook(client, order()).status_code == 204
        rows = shop.rows("SELECT * FROM outcome_event")
        assert len(rows) == 1
        r = rows[0]
        assert (r["kind"], r["source"], r["session_id"], r["shop_id"]) == (
            "order_completed",
            "webhook",
            SID,
            "shop_dev",
        )
        assert float(r["value"]) == 129.5

    def test_the_paid_topic_works_too(self, client: TestClient, shop: Db) -> None:
        assert webhook(client, order(), topic="orders/paid").status_code == 204
        assert shop.count("outcome_event") == 1

    @pytest.mark.parametrize(
        "how", ["wrong_secret", "tampered_body", "missing", "garbage", "empty", "unsigned_b64"]
    )
    def test_bad_signatures_are_401_and_store_nothing(
        self, client: TestClient, shop: Db, how: str
    ) -> None:
        body = json.dumps(order()).encode()
        if how == "wrong_secret":
            res = webhook(client, None, raw=body, secret="not-the-secret")
        elif how == "tampered_body":
            res = webhook(client, None, raw=body, signature=sign(body + b" "))
        elif how == "missing":
            res = webhook(client, None, raw=body, signature=None)
        elif how == "garbage":
            res = webhook(client, None, raw=body, signature="%%%")
        elif how == "empty":
            res = webhook(client, None, raw=body, signature="")
        else:
            res = webhook(client, None, raw=body, signature=base64.b64encode(b"x" * 32).decode())
        assert res.status_code == 401
        assert shop.count("outcome_event") == 0

    def test_signature_uses_the_raw_bytes_not_reparsed_json(
        self, client: TestClient, shop: Db
    ) -> None:
        raw = (
            b'{ "total_price" : "10.00",  "note_attributes":[{"name":"ivay_sid","value":"'
            + SID.encode()
            + b'"}] }'
        )
        assert webhook(client, None, raw=raw).status_code == 204
        assert shop.count("outcome_event") == 1

    def test_a_shop_without_a_secret_configured_is_401(self, client: TestClient, db: Db) -> None:
        db.seed_shop(secret_ref=None)
        assert webhook(client, order()).status_code == 401

    def test_a_secret_reference_outside_the_ivay_prefix_is_not_read(
        self, client: TestClient, db: Db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABASE_URL", SECRET)
        db.seed_shop(secret_ref="DATABASE_URL")
        assert webhook(client, order()).status_code == 401
        assert db.count("outcome_event") == 0

    def test_a_secret_reference_with_no_env_value_is_401(self, client: TestClient, db: Db) -> None:
        db.seed_shop(secret_ref="IVAY_WEBHOOK_SECRET_UNSET")
        assert webhook(client, order()).status_code == 401

    def test_unknown_shop_is_404(self, client: TestClient, shop: Db) -> None:
        assert webhook(client, order(), shop_id="ghost").status_code == 404

    def test_the_shop_id_query_parameter_is_required(self, client: TestClient, shop: Db) -> None:
        res = client.post("/v1/webhooks/shopify/orders", content=b"{}")
        assert res.status_code == 422


class TestOrderContent:
    def test_nothing_else_from_the_order_is_stored(self, client: TestClient, shop: Db) -> None:
        assert webhook(client, order()).status_code == 204
        dump = shop.dump_all()
        for needle in (
            "jane.doe@example.com",
            "Bonn",
            "Musterstrasse",
            "Jane",
            "Doe",
            "Ivay Tee",
            "820982911946154508",
            "gift",
        ):
            assert needle not in dump, needle

    def test_non_order_topics_are_acknowledged_and_ignored(
        self, client: TestClient, shop: Db
    ) -> None:
        for topic in ("orders/cancelled", "customers/create", None):
            assert webhook(client, order(), topic=topic).status_code == 204
        assert shop.count("outcome_event") == 0

    @pytest.mark.parametrize(
        "payload",
        [
            order(sid=None),
            order(note_attributes=[]),
            order(note_attributes=None),
            order(note_attributes=[{"name": "ivay_sid", "value": "bad sid!"}]),
            order(note_attributes=[{"name": "ivay_sid", "value": "short"}]),
            order(note_attributes=[{"name": "ivay_sid", "value": 12345678}]),
            order(note_attributes="nope"),
            [],
            "string",
        ],
    )
    def test_orders_without_a_usable_session_are_acknowledged_and_ignored(
        self, client: TestClient, shop: Db, payload: Any
    ) -> None:
        assert webhook(client, payload).status_code == 204
        assert shop.count("outcome_event") == 0

    def test_invalid_json_after_a_valid_signature_is_400(
        self, client: TestClient, shop: Db
    ) -> None:
        assert webhook(client, None, raw=b"not json").status_code == 400

    @pytest.mark.parametrize(
        "total,expected",
        [("0.00", 0.0), ("1999", 1999.0), ("abc", None), ("-5", None), ("NaN", None)],
    )
    def test_order_value_parsing(
        self, client: TestClient, shop: Db, total: str, expected: float | None
    ) -> None:
        assert webhook(client, order(total=total)).status_code == 204
        v = shop.rows("SELECT value FROM outcome_event")[0]["value"]
        assert (None if v is None else float(v)) == expected

    def test_a_large_order_payload_is_accepted(self, client: TestClient, shop: Db) -> None:
        big = order(line_items=[{"title": "x" * 200} for _ in range(2000)])
        assert len(json.dumps(big)) > 64 * 1024
        assert webhook(client, big).status_code == 204

    def test_an_oversize_body_is_413(self, client: TestClient, shop: Db) -> None:
        assert webhook(client, None, raw=b"x" * (1024 * 1024 + 1)).status_code == 413


def pixel_order(client: TestClient, value: float | None = 120.0, sid: str = SID) -> None:
    body = {
        "schema_version": "1.0",
        "shop_id": "shop_dev",
        "session_id": sid,
        "sent_at": 1790000000000,
        "events": [
            {
                "type": "outcome",
                "event_id": f"pxorder_{sid}",
                "ts": 1790000000000,
                "kind": "order_completed",
                "value": value,
                "source": "pixel",
            }
        ],
    }
    assert post_events(client, body, origin=ORIGIN).status_code == 204


class TestDeduplication:
    def test_webhook_after_pixel_keeps_one_row_and_takes_the_webhook_value(
        self, client: TestClient, shop: Db
    ) -> None:
        pixel_order(client, 120.0)
        assert webhook(client, order(total="129.50")).status_code == 204
        rows = shop.rows("SELECT source, value FROM outcome_event WHERE kind = 'order_completed'")
        assert len(rows) == 1
        assert rows[0]["source"] == "webhook" and float(rows[0]["value"]) == 129.5

    def test_pixel_after_webhook_does_not_replace_or_duplicate(
        self, client: TestClient, shop: Db
    ) -> None:
        webhook(client, order(total="129.50"))
        pixel_order(client, 120.0)
        rows = shop.rows("SELECT source, value FROM outcome_event WHERE kind = 'order_completed'")
        assert len(rows) == 1
        assert rows[0]["source"] == "webhook" and float(rows[0]["value"]) == 129.5

    def test_the_same_webhook_delivered_twice_is_one_row(
        self, client: TestClient, shop: Db
    ) -> None:
        for _ in range(3):
            assert webhook(client, order()).status_code == 204
        assert shop.count("outcome_event") == 1

    def test_the_same_pixel_outcome_twice_is_one_row(self, client: TestClient, shop: Db) -> None:
        pixel_order(client)
        pixel_order(client)
        assert shop.count("outcome_event") == 1

    def test_two_pixel_events_with_different_ids_for_one_session_are_still_one_order(
        self, client: TestClient, shop: Db
    ) -> None:
        pixel_order(client)
        body = {
            "schema_version": "1.0",
            "shop_id": "shop_dev",
            "session_id": SID,
            "sent_at": 1,
            "events": [
                {
                    "type": "outcome",
                    "event_id": "some-other-id",
                    "ts": 1,
                    "kind": "order_completed",
                    "value": 5,
                    "source": "pixel",
                }
            ],
        }
        assert post_events(client, body).status_code == 204
        assert shop.count("outcome_event") == 1

    def test_different_sessions_are_separate_orders(self, client: TestClient, shop: Db) -> None:
        webhook(client, order(sid="sessionaaaaaaaaaa"))
        webhook(client, order(sid="sessionbbbbbbbbbb"))
        assert shop.count("outcome_event") == 2

    def test_other_outcome_kinds_are_not_deduplicated_by_session(
        self, client: TestClient, shop: Db
    ) -> None:
        for i in range(3):
            body = {
                "schema_version": "1.0",
                "shop_id": "shop_dev",
                "session_id": SID,
                "sent_at": 1,
                "events": [
                    {
                        "type": "outcome",
                        "event_id": f"atc-event-{i:03d}",
                        "ts": 1,
                        "kind": "add_to_cart",
                        "value": None,
                        "source": "sdk",
                    }
                ],
            }
            post_events(client, body)
        assert shop.count("outcome_event") == 3
