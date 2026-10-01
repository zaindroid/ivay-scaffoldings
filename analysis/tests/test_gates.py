"""On simulated data the pipeline recovers the planted values (spec M8 "done when").

Two kinds of check, because they prove different things:
  * the empirical truth (computed from the generator's latent variables) must be reproduced
    EXACTLY: no information may be lost between the generator, the database, the rollup view and
    the gate code;
  * the planted parameters (closed forms) must be recovered within statistical tolerance, four
    standard deviations, which shows the estimates are right and not merely self-consistent.
"""

import math

import pytest
from support import Simulated

from ivay_analysis import STATES
from ivay_analysis.gates import proof_test_days, ratio


def within(observed: float, expected: float, n: float, sigmas: float = 4.0) -> bool:
    sd = math.sqrt(max(expected * (1 - expected), 1e-9) / n)
    return abs(observed - expected) <= sigmas * sd


class TestNumber1AddressableShare:
    def test_equals_the_planted_empirical_share_exactly(self, simulated: Simulated) -> None:
        a, b = simulated.gates.addressable
        e = simulated.truth["empirical"]
        assert (a, b) == (e["addressable_sessions"], e["abandoning_sessions"])
        assert a / b == pytest.approx(e["addressable_share"], abs=1e-12)

    def test_definition_abandoning_means_product_or_cart_view_and_no_order(
        self, simulated: Simulated
    ) -> None:
        s = simulated.rollup.sessions
        ab = s[s["abandoned"]]
        assert (ab["product_views"] + ab["cart_views"] > 0).all()
        assert not ab["has_order_completed"].any()
        assert len(ab) == simulated.truth["empirical"]["abandoning_sessions"]


class TestNumber2TriggerRate:
    def test_equals_the_planted_empirical_rate_exactly(self, simulated: Simulated) -> None:
        for st in STATES:
            f, n = simulated.gates.trigger[st]
            assert f == simulated.truth["empirical"]["fired_sessions"][st]
            assert n == simulated.truth["consented_sessions"]

    def test_recovers_the_closed_form_from_the_planted_parameters(
        self, simulated: Simulated
    ) -> None:
        for st in STATES:
            f, n = simulated.gates.trigger[st]
            planted = simulated.truth["parameters"]["trigger_rate"][st]
            assert within(f / n, planted, n), (st, f / n, planted)


class TestNumber3GroundedCoverage:
    def test_equals_the_planted_empirical_coverage_exactly(self, simulated: Simulated) -> None:
        for st in STATES:
            c, n = simulated.gates.coverage[st]
            assert n == simulated.truth["empirical"]["fired_decisions"][st]
            assert c / n == pytest.approx(simulated.truth["empirical"]["grounded_coverage"][st])

    def test_recovers_the_planted_coverage_parameters(self, simulated: Simulated) -> None:
        for st in STATES:
            c, n = simulated.gates.coverage[st]
            assert within(c / n, simulated.truth["parameters"]["grounded_coverage"][st], n), st


class TestNumber4ConsentRate:
    def test_equals_the_planted_empirical_rate_and_recovers_the_parameter(
        self, simulated: Simulated
    ) -> None:
        assert simulated.gates.consent is not None
        yes, total = simulated.gates.consent
        assert yes / total == pytest.approx(simulated.truth["empirical"]["consent_rate"])
        assert within(yes / total, simulated.truth["parameters"]["consent_rate"], total)

    def test_without_ping_data_the_number_is_unavailable_not_zero(
        self, simulated: Simulated
    ) -> None:
        from ivay_analysis.gates import consent_counts

        empty = simulated.rollup.pings.iloc[0:0]
        assert consent_counts(empty) is None


class TestNumber5SignalLift:
    def test_recovers_the_planted_signal_effect(self, simulated: Simulated) -> None:
        u = simulated.gates.auc
        oracle = simulated.truth["empirical"]["oracle_auc_lift"]
        assert u.lift > 0.03, "the planted effect must be detectable"
        assert abs(u.lift - oracle) <= 0.03, (u.lift, oracle)
        assert u.auc_full > u.auc_base > 0.5

    def test_cannot_beat_the_ceiling_set_by_the_true_probabilities(
        self, simulated: Simulated
    ) -> None:
        # an estimate from data cannot do much better than the oracle that knows the true model
        assert (
            simulated.gates.auc.auc_full <= simulated.truth["empirical"]["oracle_auc_full"] + 0.02
        )

    def test_uses_the_default_outcome_and_population(self, simulated: Simulated) -> None:
        u = simulated.gates.auc
        s = simulated.rollup.sessions
        prod = s[(s["page_views"] > 0) & (s["product_views"] > 0)]
        assert u.n == len(prod)
        assert u.positives == int(prod["has_add_to_cart"].sum())
        assert u.n == simulated.truth["empirical"]["product_sessions"]

    def test_no_planted_effect_means_no_lift(self, simulated_null: Simulated) -> None:
        assert abs(simulated_null.truth["empirical"]["oracle_auc_lift"]) < 0.01
        assert abs(simulated_null.gates.auc.lift) < 0.015, simulated_null.gates.auc


class TestNumber6SdkSize:
    def test_is_the_gzipped_size_of_the_bundle(
        self, simulated: Simulated, bundle_gzip_size: int
    ) -> None:
        assert simulated.gates.sdk_size_bytes == bundle_gzip_size

    def test_a_missing_bundle_is_unavailable(self, simulated: Simulated, tmp_path: object) -> None:
        from pathlib import Path

        from ivay_analysis.gates import gzipped_size

        assert gzipped_size(Path(str(tmp_path)) / "nope.js") is None


class TestNumber7DecisionLatency:
    def test_p50_recovers_the_planted_median(self, simulated: Simulated) -> None:
        planted = simulated.truth["parameters"]["median_eval_p50_us"]
        assert simulated.gates.latency_p50_us == pytest.approx(planted, rel=0.05)

    def test_max_is_the_worst_evaluation_seen(self, simulated: Simulated) -> None:
        assert simulated.gates.latency_max_us == pytest.approx(
            simulated.truth["empirical"]["max_eval_max_us"]
        )

    def test_pages_with_no_evaluations_are_ignored(self) -> None:
        import pandas as pd

        from ivay_analysis.gates import latency

        df = pd.DataFrame(
            {"eval_count": [0, 0], "eval_p50_us": [9999.0, 9999.0], "eval_max_us": [9999.0, 9999.0]}
        )
        assert latency(df) == (None, None)
        df2 = pd.DataFrame(
            {"eval_count": [0, 10], "eval_p50_us": [9999.0, 5.0], "eval_max_us": [9999.0, 7.0]}
        )
        assert latency(df2) == (5.0, 7.0)

    def test_weighted_median(self) -> None:
        import pandas as pd

        from ivay_analysis.gates import weighted_median

        assert weighted_median(pd.Series([1.0, 2.0, 3.0]), pd.Series([1, 1, 1])) == 2.0
        assert weighted_median(pd.Series([1.0, 100.0]), pd.Series([99, 1])) == 1.0
        assert weighted_median(pd.Series([1.0, 100.0]), pd.Series([1, 99])) == 100.0


class TestNumber8ProofTestDuration:
    def test_formula(self) -> None:
        assert proof_test_days(2300, 500, 0.1) == pytest.approx(92.0)
        assert proof_test_days(2300, 500, 0.0) == math.inf
        assert proof_test_days(100, 10, 0.5) == pytest.approx(40.0)

    def test_sessions_per_day_recovers_the_planted_volume(self, simulated: Simulated) -> None:
        planted = simulated.truth["empirical"]["sessions_per_day"]
        assert simulated.gates.sessions_per_day == pytest.approx(planted, rel=0.03)
        assert simulated.gates.span_days == pytest.approx(simulated.generated.params.days, rel=0.03)

    def test_recovers_the_duration_implied_by_the_planted_parameters(
        self, simulated: Simulated, cfg: object
    ) -> None:
        n_per_arm = 2300
        days = simulated.generated.params.days
        per_day = simulated.truth["consented_sessions"] / days
        for st in STATES:
            planted = 2 * n_per_arm / (per_day * simulated.truth["parameters"]["trigger_rate"][st])
            assert simulated.gates.proof_days[st] == pytest.approx(planted, rel=0.12), st

    def test_is_consistent_with_the_reported_trigger_rate(self, simulated: Simulated) -> None:
        g = simulated.gates
        for st in STATES:
            f, n = g.trigger[st]
            expected = 2 * 2300 / (g.sessions_per_day * (ratio(f, n) or 0))
            assert g.proof_days[st] == pytest.approx(expected)


class TestInputs:
    def test_consented_sessions_are_the_ones_the_sdk_ran_in(self, simulated: Simulated) -> None:
        assert simulated.gates.consented_sessions == simulated.generated.params.sessions

    def test_only_the_requested_shop_is_read(
        self, simulated: Simulated, simulated_null: Simulated
    ) -> None:
        assert set(simulated.rollup.sessions["shop_id"]) == {"sim_shop"}
        assert set(simulated_null.rollup.sessions["shop_id"]) == {"sim_null"}
