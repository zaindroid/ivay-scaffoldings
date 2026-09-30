"""session_rollup on a small fixture: four sessions, built through the public endpoints."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import Db, post_events

T0 = 1790000000000


def env(
    sid: str, events: list[dict[str, Any]], vh: str | None = None, page: str = "page-00000001"
) -> dict[str, Any]:
    e: dict[str, Any] = {
        "schema_version": "1.0",
        "shop_id": "shop_dev",
        "session_id": sid,
        "sent_at": T0,
        "events": events,
    }
    if vh:
        e.update(visitor_hash=vh, page_id=page)
    return e


def pv(
    eid: str, page_type: str, ts: int, device: str = "desktop", country: str | None = "DE"
) -> dict[str, Any]:
    return {
        "type": "page_view",
        "event_id": eid,
        "ts": ts,
        "page_type": page_type,
        "device": device,
        "product_id": None,
        "country": country,
    }


def summary(eid: str, ts: int, **features: Any) -> dict[str, Any]:
    return {
        "type": "page_summary",
        "event_id": eid,
        "ts": ts,
        "features": features,
        "eval_count": 4,
        "eval_p50_us": 12.0,
        "eval_max_us": 30.0,
    }


def fired(
    eid: str, ts: int, state: str, seq: int, arm: str = "treatment", **features: Any
) -> dict[str, Any]:
    return {
        "type": "rule_fired",
        "event_id": eid,
        "ts": ts,
        "decision_id": "dec-" + eid,
        "friction_state": state,
        "rule_id": state[:4] + "_v1",
        "rule_version": "r1",
        "fire_seq": seq,
        "arm": arm,
        "mode": "shadow",
        "play": None,
        "propensity": None,
        "content_ref": None,
        "has_content": False,
        "features": features,
    }


def outcome(
    eid: str, ts: int, kind: str, source: str, value: float | None = None
) -> dict[str, Any]:
    return {
        "type": "outcome",
        "event_id": eid,
        "ts": ts,
        "kind": kind,
        "value": value,
        "source": source,
    }


S1, S2, S3, S4 = "sess-one-0001", "sess-two-0002", "sess-three-03", "sess-four-004"
VH1, VH2, VH4 = "1" * 64, "2" * 64, "4" * 64


@pytest.fixture
def populated(client: TestClient, db: Db) -> Db:
    db.seed_shop(secret_ref=None)

    def post(body: dict[str, Any]) -> int:
        status: int = post_events(client, body).status_code
        return status

    # S1: abandoned after touching shipping info; two pages, delivery rule fired in the holdout arm.
    assert (
        post(
            env(
                S1,
                [
                    pv("s1-pv-0001", "product", T0, device="mobile"),
                    outcome("s1-atc-001", T0 + 1000, "add_to_cart", "sdk"),
                    summary(
                        "s1-sm-0001",
                        T0 + 5000,
                        shipping_block_dwell_s=10,
                        scroll_reversals_30s=1,
                        cart_value=40,
                        shipping_page_visited=False,
                        pages_viewed=1,
                        cart_adds=1,
                        size_chart_opens=0,
                    ),
                ],
                vh=VH1,
                page="page-s1-0001",
            )
        )
        == 204
    )
    assert (
        post(
            env(
                S1,
                [
                    pv("s1-pv-0002", "shipping_policy", T0 + 10000, device="mobile"),
                    summary(
                        "s1-sm-0002",
                        T0 + 12000,
                        shipping_block_dwell_s=0,
                        cart_value=None,
                        shipping_page_visited=True,
                        pages_viewed=2,
                        cart_adds=1,
                        size_chart_opens=0,
                    ),
                ],
                vh=VH1,
                page="page-s1-0002",
            )
        )
        == 204
    )
    assert (
        post(
            env(
                S1,
                [
                    pv("s1-pv-0003", "product", T0 + 20000, device="mobile"),
                    fired(
                        "s1-fire-001",
                        T0 + 20100,
                        "delivery_uncertainty",
                        1,
                        arm="holdout",
                        shipping_page_visited=True,
                        pages_viewed=3,
                        cart_adds=1,
                    ),
                    summary(
                        "s1-sm-0003",
                        T0 + 40000,
                        shipping_block_dwell_s=45,
                        scroll_reversals_30s=3,
                        cart_value=50,
                        shipping_page_visited=True,
                        pages_viewed=3,
                        cart_adds=1,
                        size_chart_opens=0,
                        tab_hidden_count=2,
                    ),
                    outcome("px-start-s1", T0 + 41000, "checkout_started", "pixel", 50.0),
                ],
                vh=VH1,
                page="page-s1-0003",
            )
        )
        == 204
    )
    # S2: two rules fired, then an order (pixel first, then webhook with the authoritative value).
    assert (
        post(
            env(
                S2,
                [
                    pv("s2-pv-0001", "product", T0, country="DE"),
                    pv("s2-pv-0002", "cart", T0 + 5000, country=None),
                    fired(
                        "s2-fire-001",
                        T0 + 6000,
                        "returns_uncertainty",
                        1,
                        returns_page_visited=True,
                    ),
                    fired(
                        "s2-fire-002",
                        T0 + 6001,
                        "sizing_uncertainty",
                        2,
                        size_chart_opens=2,
                        returns_page_visited=True,
                    ),
                    summary(
                        "s2-sm-0001",
                        T0 + 9000,
                        size_block_dwell_s=20,
                        returns_page_visited=True,
                        size_chart_opens=2,
                        pages_viewed=2,
                        cart_adds=2,
                        variant_toggles_since_atc=3,
                        repeated_taps_5s=2,
                        cart_value=80,
                    ),
                ],
                vh=VH2,
            )
        )
        == 204
    )
    assert (
        post(env(S2, [outcome("px-order-s2", T0 + 20000, "order_completed", "pixel", 79.0)])) == 204
    )
    db.execute(
        "INSERT INTO outcome_event (event_id, shop_id, session_id, kind, value, source, ts) "
        "VALUES ('wh_x', 'shop_dev', :s, 'order_completed', 80, 'webhook', now()) "
        "ON CONFLICT (shop_id, session_id) WHERE kind = 'order_completed' "
        "DO UPDATE SET value = 80, source = 'webhook'",
        s=S2,
    )
    # S3: outcome only (a pixel event for a session that sent no page events).
    assert post(env(S3, [outcome("px-order-s3", T0 + 1, "order_completed", "pixel", 10.0)])) == 204
    # S4: only read the shipping policy: not an abandoning session (no product or cart view).
    assert post(env(S4, [pv("s4-pv-0001", "shipping_policy", T0)], vh=VH4)) == 204
    return db


def rollup(db: Db) -> dict[str, dict[str, Any]]:
    return {r["session_id"]: r for r in db.rows("SELECT * FROM session_rollup")}


def test_one_row_per_session(populated: Db) -> None:
    rows = populated.rows("SELECT shop_id, session_id FROM session_rollup")
    assert sorted(r["session_id"] for r in rows) == sorted([S1, S2, S3, S4])


def test_page_counts_and_context(populated: Db) -> None:
    r = rollup(populated)
    s1 = r[S1]
    assert (
        s1["page_views"],
        s1["product_views"],
        s1["cart_views"],
        s1["shipping_policy_views"],
    ) == (3, 2, 0, 1)
    assert s1["device"] == "mobile" and s1["country"] == "DE" and s1["visitor_hash"] == VH1
    s2 = r[S2]
    assert (s2["page_views"], s2["product_views"], s2["cart_views"]) == (2, 1, 1)
    assert s2["country"] == "DE"  # first non-null country
    assert (r[S3]["page_views"], r[S3]["visitor_hash"]) == (0, None)


def test_final_session_features_come_from_the_latest_snapshot(populated: Db) -> None:
    s1 = rollup(populated)[S1]
    assert s1["shipping_page_visited"] is True
    assert s1["pages_viewed"] == 3
    assert s1["tab_hidden_count"] == 2
    assert s1["cart_adds"] == 1
    s2 = rollup(populated)[S2]
    assert (s2["size_chart_opens"], s2["cart_adds"], s2["returns_page_visited"]) == (2, 2, True)
    s3 = rollup(populated)[S3]
    assert (s3["pages_viewed"], s3["shipping_page_visited"], s3["size_chart_opens"]) == (
        0,
        False,
        0,
    )


def test_page_scoped_features_are_the_max_over_the_session(populated: Db) -> None:
    s1 = rollup(populated)[S1]
    assert float(s1["max_shipping_block_dwell_s"]) == 45  # 10, 0 and 45 across three pages
    assert float(s1["max_scroll_reversals_30s"]) == 3
    assert float(s1["cart_value"]) == 50
    s2 = rollup(populated)[S2]
    assert float(s2["max_size_block_dwell_s"]) == 20
    assert float(s2["max_variant_toggles_since_atc"]) == 3
    assert float(s2["max_repeated_taps_5s"]) == 2
    assert rollup(populated)[S3]["max_shipping_block_dwell_s"] is None


def test_first_fired_state_is_the_lowest_fire_seq(populated: Db) -> None:
    r = rollup(populated)
    assert r[S1]["first_fired_state"] == "delivery_uncertainty" and r[S1]["arm"] == "holdout"
    assert r[S2]["first_fired_state"] == "returns_uncertainty"
    assert r[S3]["first_fired_state"] is None and r[S3]["arm"] is None
    assert (
        r[S2]["rules_fired"],
        r[S2]["fired_returns"],
        r[S2]["fired_sizing"],
        r[S2]["fired_delivery"],
    ) == (2, True, True, False)
    assert (r[S1]["rules_fired"], r[S1]["fired_delivery"]) == (1, True)
    assert r[S4]["rules_fired"] == 0


def test_outcome_flags_and_order_value_with_webhook_winning(populated: Db) -> None:
    r = rollup(populated)
    assert (
        r[S1]["has_add_to_cart"],
        r[S1]["has_checkout_started"],
        r[S1]["has_order_completed"],
    ) == (True, True, False)
    assert r[S1]["order_value"] is None
    assert r[S2]["has_order_completed"] is True and float(r[S2]["order_value"]) == 80
    assert r[S3]["has_order_completed"] is True and float(r[S3]["order_value"]) == 10
    assert (r[S4]["has_add_to_cart"], r[S4]["has_order_completed"]) == (False, False)


def test_touched_information_flags(populated: Db) -> None:
    r = rollup(populated)
    assert (r[S1]["touched_shipping"], r[S1]["touched_returns"], r[S1]["touched_size"]) == (
        True,
        False,
        False,
    )
    assert (r[S2]["touched_shipping"], r[S2]["touched_returns"], r[S2]["touched_size"]) == (
        False,
        True,
        True,
    )
    assert (r[S3]["touched_shipping"], r[S3]["touched_returns"], r[S3]["touched_size"]) == (
        False,
        False,
        False,
    )


def test_abandoned_means_product_or_cart_view_and_no_order(populated: Db) -> None:
    r = rollup(populated)
    assert r[S1]["abandoned"] is True  # viewed product pages, no order
    assert r[S2]["abandoned"] is False  # ordered
    assert r[S3]["abandoned"] is False  # no page views at all
    assert r[S4]["abandoned"] is False  # only a policy page


def test_view_is_empty_with_no_data(db: Db) -> None:
    assert db.rows("SELECT * FROM session_rollup") == []


def test_sessions_of_different_shops_are_not_merged(client: TestClient, db: Db) -> None:
    db.seed_shop("shop_dev")
    db.seed_shop("shop_two", origins=["https://two.example"])
    a = env("sess-shared-01", [pv("sh-pv-00001", "product", T0)], vh=VH1)
    b = {**env("sess-shared-01", [pv("sh-pv-00002", "product", T0)], vh=VH2), "shop_id": "shop_two"}
    assert post_events(client, a).status_code == 204
    assert post_events(client, b, origin="https://two.example").status_code == 204
    rows = db.rows("SELECT shop_id, page_views FROM session_rollup ORDER BY shop_id")
    assert rows == [
        {"shop_id": "shop_dev", "page_views": 1},
        {"shop_id": "shop_two", "page_views": 1},
    ]
