import copy
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml

from ivay_analysis import auc, config


def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(config.DEFAULT_PATH.read_text(encoding="utf-8"))
    return copy.deepcopy(data)


class TestGatesYaml:
    def test_loads_with_the_spec_defaults(self) -> None:
        cfg = config.load()
        assert cfg.n_per_arm == 2300
        assert (cfg.auc.outcome, cfg.auc.population) == ("add_to_cart", "product_sessions")
        assert set(cfg.thresholds) == set(config.REQUIRED)

    def test_every_threshold_is_provisional_except_the_size_limit_fixed_by_the_spec(self) -> None:
        cfg = config.load()
        for key, t in cfg.thresholds.items():
            if key == "sdk_size_bytes":
                assert not t.provisional and "SPEC" in t.status.upper()
                assert (t.kind, t.value) == ("max", 10240)
            else:
                assert t.status == "PROVISIONAL (proposed by Claude)", key
            assert t.why, f"{key} has no stated reason"

    def test_comparisons(self) -> None:
        cfg = config.load()
        assert cfg.thresholds["addressable_share"].passes(0.30)
        assert not cfg.thresholds["addressable_share"].passes(0.29)
        assert cfg.thresholds["sdk_size_bytes"].passes(10240)
        assert not cfg.thresholds["sdk_size_bytes"].passes(10241)

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d.pop("n_per_arm"),
            lambda d: d.update(n_per_arm=0),
            lambda d: d.update(n_per_arm=True),
            lambda d: d["auc"].update(outcome="clicks"),
            lambda d: d["auc"].update(population="everyone"),
            lambda d: d["auc"].update(folds=1),
            lambda d: d["thresholds"].pop("trigger_rate"),
            lambda d: d["thresholds"]["trigger_rate"].update(max=1),
            lambda d: d["thresholds"]["trigger_rate"].pop("min"),
            lambda d: d["thresholds"]["trigger_rate"].update(min="high"),
            lambda d: d["thresholds"]["trigger_rate"].pop("status"),
            lambda d: d.pop("thresholds"),
        ],
        ids=[
            "no-n",
            "zero-n",
            "bool-n",
            "bad-outcome",
            "bad-population",
            "one-fold",
            "no-threshold",
            "both-min-max",
            "neither",
            "string-value",
            "no-status",
            "no-section",
        ],
    )
    def test_invalid_configs_are_refused(self, mutate: Any) -> None:
        d = raw()
        mutate(d)
        with pytest.raises(config.ConfigError):
            config.parse(d)

    def test_a_non_mapping_is_refused(self) -> None:
        with pytest.raises(config.ConfigError):
            config.parse(["not", "a", "mapping"])


def sessions(
    n: int, rng: np.random.Generator, effect: float = 0.0, leak: bool = False
) -> pd.DataFrame:
    """Synthetic rollup rows. `effect` ties add_to_cart to a behavioural signal."""
    touched = rng.random(n) < 0.3
    dwell = np.where(touched, rng.integers(1, 60, n), 0)
    logit = -0.5 + effect * touched
    atc = rng.random(n) < 1 / (1 + np.exp(-logit))
    df = pd.DataFrame(
        {
            "page_views": 1,
            "product_views": 1,
            "device": rng.choice(["mobile", "desktop"], n),
            "first_cart_value": rng.uniform(10, 100, n),
            "first_page_type": "product",
            "has_add_to_cart": atc,
            "shipping_page_visited": touched,
            "returns_page_visited": False,
            "size_chart_opens": 0,
            "tab_hidden_count": 0,
            "max_shipping_block_dwell_s": dwell,
            "max_returns_block_dwell_s": 0,
            "max_size_block_dwell_s": 0,
            "max_scroll_reversals_30s": 0,
            "max_variant_toggles_since_atc": 0,
            "max_repeated_taps_5s": 0,
            # columns that must never be used as features
            "cart_adds": atc.astype(int) if leak else 0,
            "pages_viewed": np.where(atc, 2, 1) if leak else 1,
        }
    )
    return df


CFG = config.AucConfig("add_to_cart", "product_sessions", 5, 0)


class TestCrossValidatedLift:
    def test_a_strong_signal_gives_a_clear_lift(self) -> None:
        r = auc.cross_validated_lift(sessions(4000, np.random.default_rng(1), effect=-2.0), CFG)
        assert r.lift > 0.08
        assert r.auc_full > r.auc_base

    def test_no_signal_gives_roughly_zero(self) -> None:
        r = auc.cross_validated_lift(sessions(4000, np.random.default_rng(2), effect=0.0), CFG)
        assert abs(r.lift) < 0.02
        assert r.auc_base == pytest.approx(0.5, abs=0.04)

    def test_leaky_columns_are_never_used_even_when_they_predict_the_outcome(self) -> None:
        df = sessions(4000, np.random.default_rng(3), effect=0.0, leak=True)
        assert df["cart_adds"].astype(bool).eq(df["has_add_to_cart"]).all()  # a perfect leak exists
        r = auc.cross_validated_lift(df, CFG)
        assert r.auc_full < 0.6, "a leaked column reached the model"
        assert abs(r.lift) < 0.02

    def test_signal_and_leaky_column_lists_do_not_overlap(self) -> None:
        assert not set(auc.SIGNAL_COLUMNS) & set(auc.EXCLUDED_AS_LEAKY)
        frame = auc.signal_frame(sessions(50, np.random.default_rng(4)))
        assert not {c.removesuffix("_any") for c in frame.columns} & set(auc.EXCLUDED_AS_LEAKY)

    def test_baseline_uses_only_start_of_session_context(self) -> None:
        cols = set(auc.baseline_frame(sessions(50, np.random.default_rng(5))).columns)
        assert cols == {
            "device_mobile",
            "device_tablet",
            "log_cart_value",
            "first_page_cart",
            "first_page_product",
        }

    def test_one_class_is_not_computable_not_a_number(self) -> None:
        df = sessions(200, np.random.default_rng(6))
        df["has_add_to_cart"] = False
        r = auc.cross_validated_lift(df, CFG)
        assert np.isnan(r.lift) and "not computable" in r.note

    def test_a_tiny_class_is_not_computable(self) -> None:
        df = sessions(200, np.random.default_rng(7))
        df["has_add_to_cart"] = False
        df.loc[:2, "has_add_to_cart"] = True  # 3 positives, fewer than the 5 folds
        assert "not computable" in auc.cross_validated_lift(df, CFG).note

    def test_the_population_excludes_sessions_without_product_views_or_page_views(self) -> None:
        df = sessions(100, np.random.default_rng(8))
        df.loc[:9, "product_views"] = 0
        df.loc[10:19, "page_views"] = 0
        assert len(auc.select_population(df, "product_sessions")) == 80
        assert len(auc.select_population(df, "all_sessions")) == 90

    def test_it_is_deterministic(self) -> None:
        df = sessions(1500, np.random.default_rng(9), effect=-1.0)
        assert auc.cross_validated_lift(df, CFG) == auc.cross_validated_lift(df, CFG)

    def test_outcome_is_configurable(self) -> None:
        df = sessions(1500, np.random.default_rng(10), effect=-1.0)
        df["has_order_completed"] = df["has_add_to_cart"] & (
            np.random.default_rng(11).random(len(df)) < 0.5
        )
        r = auc.cross_validated_lift(
            df, config.AucConfig("order_completed", "product_sessions", 5, 0)
        )
        assert r.positives == int(df["has_order_completed"].sum())
