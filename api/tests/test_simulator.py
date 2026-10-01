"""The simulator's planted truth: it must be internally consistent, conform to the contract, and
survive a round trip through the database and the session_rollup view."""

import asyncio
import hashlib
import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app.schemas import Outcome, PageSummary, PageView, RuleFired
from tests.conftest import API_DIR, Db

REPO = API_DIR.parent
sys.path.insert(0, str(REPO / "scripts"))
import simulate_sessions as sim  # noqa: E402

STATES = ("delivery_uncertainty", "returns_uncertainty", "sizing_uncertainty")


@pytest.fixture(scope="module")
def gen() -> sim.Generated:
    return sim.generate(sim.Params(sessions=4000, seed=11))


def ms(d: datetime) -> int:
    return int(d.timestamp() * 1000)


def within(observed: float, expected: float, n: int, sigmas: float = 4.0) -> bool:
    sd = math.sqrt(max(expected * (1 - expected), 1e-9) / n)
    return abs(observed - expected) <= sigmas * sd


class TestDeterminism:
    def test_same_seed_same_data_different_seed_different_data(self) -> None:
        a = sim.generate(sim.Params(sessions=200, seed=3))
        b = sim.generate(sim.Params(sessions=200, seed=3))
        c = sim.generate(sim.Params(sessions=200, seed=4))
        assert a.page_views == b.page_views and a.decisions == b.decisions and a.truth == b.truth
        assert a.page_views != c.page_views

    def test_the_generator_never_reads_the_clock(self) -> None:
        src = (REPO / "scripts" / "simulate_sessions.py").read_text(encoding="utf-8")
        assert "datetime.now" not in src and "time.time" not in src and "utcnow" not in src


class TestContract:
    """Generated rows, turned back into events, satisfy the same models the API enforces."""

    def test_rows_validate_as_events(self, gen: sim.Generated) -> None:
        for r in gen.page_views[:400]:
            PageView.model_validate(
                {
                    "type": "page_view",
                    "event_id": r["event_id"],
                    "ts": ms(r["ts"]),
                    "page_type": r["page_type"],
                    "device": r["device"],
                    "product_id": r["product_id"],
                    "country": r["country"],
                }
            )
        for r in gen.decisions[:400]:
            RuleFired.model_validate(
                {
                    "type": "rule_fired",
                    "event_id": r["event_id"],
                    "ts": ms(r["ts"]),
                    **{
                        k: r[k]
                        for k in (
                            "decision_id",
                            "friction_state",
                            "rule_id",
                            "rule_version",
                            "fire_seq",
                            "arm",
                            "mode",
                            "play",
                            "propensity",
                            "content_ref",
                            "has_content",
                            "features",
                        )
                    },
                }
            )
        for r in gen.summaries[:400]:
            PageSummary.model_validate(
                {
                    "type": "page_summary",
                    "event_id": r["event_id"],
                    "ts": ms(r["ts"]),
                    "features": r["features"],
                    "eval_count": r["eval_count"],
                    "eval_p50_us": r["eval_p50_us"],
                    "eval_max_us": r["eval_max_us"],
                }
            )
        for r in gen.outcomes[:400]:
            Outcome.model_validate(
                {
                    "type": "outcome",
                    "event_id": r["event_id"],
                    "ts": ms(r["ts"]),
                    "kind": r["kind"],
                    "value": r["value"],
                    "source": r["source"],
                }
            )

    def test_ids_are_unique(self, gen: sim.Generated) -> None:
        ids = [r["event_id"] for r in gen.page_views + gen.decisions + gen.summaries + gen.outcomes]
        assert len(ids) == len(set(ids))
        dec = [r["decision_id"] for r in gen.decisions]
        assert len(dec) == len(set(dec))

    def test_the_sim_config_is_a_valid_shop_config(self, gen: sim.Generated) -> None:
        from app.schemas import ShopConfig

        ShopConfig.model_validate(gen.config)
        assert gen.config["shop_id"] == "sim_shop"


class TestInvariants:
    def test_decisions_follow_the_sdk_rules(self, gen: sim.Generated) -> None:
        by_session: dict[str, list[dict[str, Any]]] = {}
        for d in gen.decisions:
            by_session.setdefault(d["session_id"], []).append(d)
        for sid, ds in by_session.items():
            assert sorted(d["fire_seq"] for d in ds) == list(range(1, len(ds) + 1)), sid
            assert len({d["friction_state"] for d in ds}) == len(ds), "a state fired twice"
            assert {d["arm"] for d in ds} == {ds[0]["arm"]}
            for d in ds:
                assert (d["mode"], d["play"], d["propensity"]) == ("shadow", None, None)
                f = d["features"]
                if d["friction_state"] == "delivery_uncertainty":
                    assert f["shipping_page_visited"] or (
                        f["shipping_block_dwell_s"] >= 40 and f["scroll_reversals_30s"] >= 2
                    )
                elif d["friction_state"] == "returns_uncertainty":
                    assert f["returns_page_visited"]
                else:
                    assert f["page_type"] == "product"
                    assert f["size_chart_opens"] >= 2 or f["variant_toggles_since_atc"] >= 3
                assert f["page_type"] in ("product", "cart")

    def test_the_outcome_funnel_is_nested(self, gen: sim.Generated) -> None:
        kinds: dict[str, set[str]] = {}
        for o in gen.outcomes:
            kinds.setdefault(o["session_id"], set()).add(o["kind"])
        for sid, k in kinds.items():
            if "order_completed" in k:
                assert {"checkout_started", "add_to_cart"} <= k, sid
            if "checkout_started" in k:
                assert "add_to_cart" in k, sid
        orders = [o["session_id"] for o in gen.outcomes if o["kind"] == "order_completed"]
        assert len(orders) == len(set(orders))
        assert all(o["value"] is None or o["value"] >= 0 for o in gen.outcomes)

    def test_every_session_views_a_product_or_cart_page(self, gen: sim.Generated) -> None:
        pages: dict[str, set[str]] = {}
        for v in gen.page_views:
            pages.setdefault(v["session_id"], set()).add(v["page_type"])
        assert len(pages) == gen.params.sessions
        assert all(p & {"product", "cart"} for p in pages.values())

    def test_arm_is_the_sdk_formula_and_stable_per_visitor(self, gen: sim.Generated) -> None:
        seen: dict[str, str] = {}
        for d in gen.decisions:
            expected = (
                "holdout"
                if int(hashlib.sha256((d["visitor_hash"] + sim.SALT).encode()).hexdigest()[:8], 16)
                % 10000
                < sim.HOLDOUT_BPS
                else "treatment"
            )
            assert d["arm"] == expected
            assert seen.setdefault(d["visitor_hash"], d["arm"]) == d["arm"]

    def test_the_timeline_spans_the_planted_days(self, gen: sim.Generated) -> None:
        days = {v["ts"].date() for v in gen.page_views}
        assert len(days) >= gen.params.days - 1
        assert all(v["received_at"] >= v["ts"] for v in gen.page_views)

    def test_auc_helper(self) -> None:
        assert sim.auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0
        assert sim.auc([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1]) == 0.0
        assert sim.auc([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1]) == 0.5


class TestPlantedTruth:
    def test_trigger_rates_match_the_closed_form(self, gen: sim.Generated) -> None:
        n = gen.truth["consented_sessions"]
        for st in STATES:
            emp = gen.truth["empirical"]["trigger_rate"][st]
            par = gen.truth["parameters"]["trigger_rate"][st]
            assert within(emp, par, n), (st, emp, par)

    def test_grounded_coverage_matches_the_planted_coverage(self, gen: sim.Generated) -> None:
        for st in STATES:
            n = gen.truth["empirical"]["fired_decisions"][st]
            emp = gen.truth["empirical"]["grounded_coverage"][st]
            par = gen.truth["parameters"]["grounded_coverage"][st]
            assert within(emp, par, n), (st, emp, par)

    def test_consent_rate_holdout_share_and_latency(self, gen: sim.Generated) -> None:
        e, p = gen.truth["empirical"], gen.truth["parameters"]
        pings = sum(gen.pings.values())
        assert within(e["consent_rate"], p["consent_rate"], pings)
        assert within(e["holdout_share"], p["holdout_share"], gen.truth["consented_sessions"])
        assert (
            abs(e["median_eval_p50_us"] - p["median_eval_p50_us"]) / p["median_eval_p50_us"] < 0.05
        )

    def test_the_planted_signal_effect_is_real_and_sized(self, gen: sim.Generated) -> None:
        e = gen.truth["empirical"]
        assert 0.03 < e["oracle_auc_lift"] < 0.15
        assert e["oracle_auc_full"] > e["oracle_auc_baseline"] > 0.5

    def test_the_addressable_share_is_between_zero_and_one_and_not_trivial(
        self, gen: sim.Generated
    ) -> None:
        s = gen.truth["empirical"]["addressable_share"]
        assert 0.2 < s < 0.9

    def test_the_truth_is_labelled_simulated(self, gen: sim.Generated) -> None:
        assert gen.truth["note"] == "SIMULATED: pipeline check only"


class TestDatabaseRoundTrip:
    def test_written_rows_reproduce_the_planted_truth_through_session_rollup(
        self, db: Db, migrated: Any
    ) -> None:
        # A real shop's data must be left alone.
        db.seed_shop("shop_dev")
        db.execute(
            "INSERT INTO page_view (event_id, shop_id, visitor_hash, session_id, page_id, ts, "
            "page_type, device) "
            "VALUES ('real-event-1', 'shop_dev', 'h', 'real-session', 'p', now(), "
            "'product', 'desktop')"
        )
        g = sim.generate(sim.Params(sessions=500, seed=5, days=4, shop_id="sim_test"))
        asyncio.run(sim.write(g, migrated.database_url, truncate=True))
        asyncio.run(
            sim.write(g, migrated.database_url, truncate=True)
        )  # idempotent with --truncate

        assert db.count("page_view") == len(g.page_views) + 1
        rows = db.rows("SELECT * FROM session_rollup WHERE shop_id = 'sim_test'")
        assert len(rows) == 500

        e = g.truth["empirical"]
        abandoned = [r for r in rows if r["abandoned"]]
        assert len(abandoned) == e["abandoning_sessions"]
        touched = [
            r
            for r in abandoned
            if r["touched_shipping"] or r["touched_returns"] or r["touched_size"]
        ]
        assert len(touched) == e["addressable_sessions"]
        assert len(touched) / len(abandoned) == pytest.approx(e["addressable_share"])
        for st, col in zip(
            STATES, ("fired_delivery", "fired_returns", "fired_sizing"), strict=True
        ):
            assert sum(1 for r in rows if r[col]) == e["fired_sessions"][st]
        assert sum(1 for r in rows if r["has_order_completed"]) == sum(
            1 for o in g.outcomes if o["kind"] == "order_completed"
        )
        # the real shop's row is untouched and not part of the simulated rollup
        assert (
            db.rows("SELECT count(*) AS n FROM page_view WHERE shop_id = 'shop_dev'")[0]["n"] == 1
        )

        pings = db.rows(
            "SELECT consented, sum(count) AS n FROM consent_ping_daily "
            "WHERE shop_id = 'sim_test' GROUP BY consented"
        )
        by = {r["consented"]: int(r["n"]) for r in pings}
        assert by[True] / (by[True] + by[False]) == pytest.approx(e["consent_rate"])


class TestCli:
    def test_it_refuses_to_write_under_a_real_looking_shop_id(self) -> None:
        for shop in ("shop_dev", "acme", "production"):
            res = subprocess.run(
                [
                    sys.executable,
                    str(REPO / "scripts" / "simulate_sessions.py"),
                    "--shop",
                    shop,
                    "--sessions",
                    "10",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert res.returncode != 0, shop
            assert "refusing" in (res.stderr + res.stdout)


def test_the_truth_file_location_is_ignored_by_git() -> None:
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "analysis/out/" in ignore
    assert Path(REPO / "scripts" / "simulate_sessions.py").exists()
