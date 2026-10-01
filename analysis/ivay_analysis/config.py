"""Loads and validates analysis/gates.yaml."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "gates.yaml"
REQUIRED = (
    "addressable_share",
    "trigger_rate",
    "grounded_coverage",
    "consent_rate",
    "signal_lift_auc",
    "sdk_size_bytes",
    "decision_latency_p50_us",
    "decision_latency_max_us",
    "proof_test_days",
)
OUTCOMES = ("add_to_cart", "checkout_started", "order_completed")
POPULATIONS = ("product_sessions", "all_sessions")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Threshold:
    kind: str  # "min" or "max"
    value: float
    status: str
    why: str

    def passes(self, x: float) -> bool:
        return x >= self.value if self.kind == "min" else x <= self.value

    def describe(self) -> str:
        sign = ">=" if self.kind == "min" else "<="
        return f"{sign} {self.value:g}"

    @property
    def provisional(self) -> bool:
        return self.status.upper().startswith("PROVISIONAL")


@dataclass(frozen=True)
class AucConfig:
    outcome: str
    population: str
    folds: int
    seed: int


@dataclass(frozen=True)
class GatesConfig:
    n_per_arm: int
    auc: AucConfig
    thresholds: dict[str, Threshold]


def parse(raw: Any) -> GatesConfig:
    if not isinstance(raw, dict):
        raise ConfigError("gates.yaml must be a mapping")
    n = raw.get("n_per_arm")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ConfigError("n_per_arm must be a positive integer")
    a = raw.get("auc")
    if not isinstance(a, dict):
        raise ConfigError("auc section is missing")
    if a.get("outcome") not in OUTCOMES:
        raise ConfigError(f"auc.outcome must be one of {OUTCOMES}")
    if a.get("population") not in POPULATIONS:
        raise ConfigError(f"auc.population must be one of {POPULATIONS}")
    folds, seed = a.get("folds"), a.get("seed")
    if not isinstance(folds, int) or folds < 2 or not isinstance(seed, int):
        raise ConfigError("auc.folds must be an integer >= 2 and auc.seed an integer")
    t = raw.get("thresholds")
    if not isinstance(t, dict):
        raise ConfigError("thresholds section is missing")
    out: dict[str, Threshold] = {}
    for key in REQUIRED:
        entry = t.get(key)
        if not isinstance(entry, dict):
            raise ConfigError(f"threshold {key} is missing")
        kinds = [k for k in ("min", "max") if k in entry]
        if len(kinds) != 1:
            raise ConfigError(f"threshold {key} needs exactly one of min or max")
        value = entry[kinds[0]]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConfigError(f"threshold {key}.{kinds[0]} must be a number")
        status = entry.get("status")
        if not isinstance(status, str) or not status:
            raise ConfigError(f"threshold {key} needs a status (PROVISIONAL or FIXED BY SPEC)")
        out[key] = Threshold(kinds[0], float(value), status, str(entry.get("why", "")))
    return GatesConfig(n, AucConfig(a["outcome"], a["population"], folds, seed), out)


def load(path: Path | None = None) -> GatesConfig:
    return parse(yaml.safe_load((path or DEFAULT_PATH).read_text(encoding="utf-8")))
