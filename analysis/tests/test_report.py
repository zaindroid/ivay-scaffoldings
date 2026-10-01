"""The report prints all eight numbers with thresholds, labels simulated data, and hides nothing."""

import copy
import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from support import TEST_URL, Simulated

from ivay_analysis import STATES, config
from ivay_analysis.report import (
    NOT_AVAILABLE_CONSENT,
    SIMULATED_LABEL,
    as_json,
    is_simulated,
    main,
    render,
    rows,
)


def numbers_in(text: str) -> set[int]:
    return {int(m.group(1)) for m in re.finditer(r"^\s*(\d)\s{2}\S", text, re.MULTILINE)}


class TestSimulatedLabel:
    def test_only_sim_shop_ids_are_simulated(self) -> None:
        assert is_simulated("sim_shop") and is_simulated("sim_null") and is_simulated("simulation")
        assert (
            not is_simulated("shop_dev")
            and not is_simulated("pilot_shop")
            and not is_simulated("acme")
        )

    def test_a_simulated_report_is_labelled_at_the_top_and_at_the_end(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        text = render(simulated.gates, cfg, "sim_shop", True)
        lines = text.splitlines()
        assert lines[0] == f"{SIMULATED_LABEL}."
        assert "NOT gate results" in lines[1]
        assert lines[-1].startswith(SIMULATED_LABEL)
        assert "Do not read these verdicts as gate results" in lines[-1]

    def test_every_row_of_a_simulated_report_says_simulated(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        text = render(simulated.gates, cfg, "sim_shop", True)
        body = [ln for ln in text.splitlines() if re.match(r"^\s*\d\s{2}\S", ln)]
        assert body and all(ln.rstrip().endswith("(simulated)") for ln in body)

    def test_a_report_on_real_data_carries_no_simulated_label(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        text = render(simulated.gates, cfg, "pilot_shop", False)
        assert "SIMULATED" not in text.upper()
        assert "simulated" not in text


class TestAllEightNumbers:
    def test_all_eight_numbers_are_printed_with_a_threshold(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        text = render(simulated.gates, cfg, "sim_shop", True)
        assert numbers_in(text) == set(range(1, 9))
        rs = rows(simulated.gates, cfg)
        assert {r.number for r in rs} == set(range(1, 9))
        for r in rs:
            assert r.threshold.describe() in text

    def test_per_state_numbers_have_one_row_per_friction_state(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        rs = rows(simulated.gates, cfg)
        for number in (2, 3, 8):
            labels = [r.label for r in rs if r.number == number]
            assert [any(st in label for label in labels) for st in STATES] == [True] * 3
            assert len(labels) == 3
        assert len([r for r in rs if r.number == 7]) == 2  # p50 and max

    def test_provisional_thresholds_are_declared_as_such(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        text = render(simulated.gates, cfg, "sim_shop", True)
        assert "PROVISIONAL (proposed by Claude)" in text
        assert "(spec)" in text  # the SDK size limit is fixed by the spec

    def test_values_match_the_computed_gates(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        rs = rows(simulated.gates, cfg)
        first = next(r for r in rs if r.number == 1)
        a, b = simulated.gates.addressable
        assert first.value == pytest.approx(a / b)
        size = next(r for r in rs if r.number == 6)
        assert size.value == simulated.gates.sdk_size_bytes


class TestNothingIsHidden:
    def _strict(self, cfg: config.GatesConfig) -> config.GatesConfig:
        """A configuration no real number can satisfy."""
        raw: dict[str, Any] = yaml.safe_load(config.DEFAULT_PATH.read_text(encoding="utf-8"))
        t = copy.deepcopy(raw["thresholds"])
        for k, v in t.items():
            if "min" in v:
                v["min"] = 2.0 if k != "signal_lift_auc" else 0.99
            else:
                v["max"] = 0.0
        raw["thresholds"] = t
        return config.parse(raw)

    def test_failing_rows_are_listed_and_counted(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        strict = self._strict(cfg)
        text = render(simulated.gates, strict, "sim_shop", True)
        rs = rows(simulated.gates, strict)
        assert all(r.verdict == "FAIL" for r in rs)
        assert f"0 of {len(rs)} rows pass, {len(rs)} fail" in text
        assert text.count("  FAILING: ") == len(rs)
        assert text.count(" FAIL (simulated)") == len(rs)

    def test_a_number_that_fails_the_real_thresholds_is_shown(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        text = render(simulated.gates, cfg, "sim_shop", True)
        failing = [r for r in rows(simulated.gates, cfg) if r.verdict == "FAIL"]
        assert failing, "the simulated shop is expected to fail some provisional thresholds"
        for r in failing:
            assert f"FAILING: {r.number} {r.label}" in text

    def test_missing_consent_data_is_reported_as_not_available_never_as_a_number(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        g = dataclasses.replace(simulated.gates, consent=None)
        text = render(g, cfg, "sim_shop", True)
        row = next(r for r in rows(g, cfg) if r.number == 4)
        assert row.verdict == "not available" and row.value is None
        assert NOT_AVAILABLE_CONSENT in text
        assert "NOT AVAILABLE: 4 Consent rate" in text

    def test_a_missing_bundle_is_not_available(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        g = dataclasses.replace(simulated.gates, sdk_size_bytes=None)
        row = next(r for r in rows(g, cfg) if r.number == 6)
        assert row.verdict == "not available"

    def test_no_triggers_means_the_proof_test_never_finishes(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        g = dataclasses.replace(simulated.gates, proof_days={st: float("inf") for st in STATES})
        text = render(g, cfg, "sim_shop", True)
        assert text.count("never (no triggers)") == 3
        rs = [r for r in rows(g, cfg) if r.number == 8]
        assert all(r.verdict == "FAIL" for r in rs)

    def test_an_oversize_bundle_fails_the_size_row(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        g = dataclasses.replace(simulated.gates, sdk_size_bytes=10241)
        assert next(r for r in rows(g, cfg) if r.number == 6).verdict == "FAIL"
        g = dataclasses.replace(simulated.gates, sdk_size_bytes=10240)
        assert next(r for r in rows(g, cfg) if r.number == 6).verdict == "pass"


class TestJsonAndCli:
    def test_json_has_the_label_and_every_row(
        self, simulated: Simulated, cfg: config.GatesConfig
    ) -> None:
        doc = as_json(simulated.gates, cfg, "sim_shop", True)
        assert doc["simulated"] is True and doc["label"] == SIMULATED_LABEL
        rs = doc["rows"]
        assert isinstance(rs, list) and len(rs) == 15
        assert {r["number"] for r in rs} == set(range(1, 9))
        json.dumps(doc)  # serialisable

    def test_cli_on_the_simulated_shop(
        self, simulated: Simulated, bundle: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["--shop", "sim_shop", "--database-url", TEST_URL, "--bundle", str(bundle)])
        out = capsys.readouterr().out
        assert code == 0
        assert out.startswith(SIMULATED_LABEL)
        assert numbers_in(out) == set(range(1, 9))

    def test_cli_json(
        self, simulated: Simulated, bundle: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            main(
                [
                    "--shop",
                    "sim_shop",
                    "--database-url",
                    TEST_URL,
                    "--bundle",
                    str(bundle),
                    "--json",
                ]
            )
            == 0
        )
        assert json.loads(capsys.readouterr().out)["simulated"] is True

    def test_cli_with_a_missing_database_url_explains_itself(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert main(["--shop", "sim_shop"]) == 2
        assert "DATABASE_URL" in capsys.readouterr().err

    def test_cli_for_a_shop_with_no_sessions(
        self, simulated: Simulated, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--shop", "nobody", "--database-url", TEST_URL]) == 1
        assert "No sessions" in capsys.readouterr().err

    def test_a_custom_config_is_honoured(
        self, simulated: Simulated, bundle: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        raw = yaml.safe_load(config.DEFAULT_PATH.read_text(encoding="utf-8"))
        raw["thresholds"]["addressable_share"]["min"] = 0.99
        path = tmp_path / "gates.yaml"
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        main(
            [
                "--shop",
                "sim_shop",
                "--database-url",
                TEST_URL,
                "--bundle",
                str(bundle),
                "--config",
                str(path),
            ]
        )
        out = capsys.readouterr().out
        assert ">= 0.99" in out and "FAILING: 1 Addressable share" in out
