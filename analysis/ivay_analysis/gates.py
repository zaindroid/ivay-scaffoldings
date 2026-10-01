"""The eight numbers of spec section 2, computed from a Rollup.

Definitions are implemented exactly as written in the spec:

  1  Addressable share   of abandoning sessions, the share touching shipping, returns or size info
  2  Trigger rate        per friction state: sessions where the rule fired / consented sessions
  3  Grounded coverage   per friction state: fired decisions with content / fired decisions
  4  Consent rate        consented page loads / all page loads (from the anonymous ping)
  5  Signal lift         cross-validated AUC(baseline + signals) minus AUC(baseline)
  6  SDK size            gzipped bytes of the production bundle
  7  Decision latency    p50 and max of rule-evaluation time, measured by the SDK in the field
  8  Proof-test days     2n / (sessions_per_day x consent_rate x trigger_rate)
"""

import gzip
import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ivay_analysis import STATES
from ivay_analysis.auc import AucResult, cross_validated_lift
from ivay_analysis.config import GatesConfig
from ivay_analysis.rollup import Rollup

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = REPO / "sdk" / "dist" / "ivay.js"


@dataclass(frozen=True)
class Gates:
    consented_sessions: int
    span_days: float
    addressable: tuple[int, int]  # (addressable, abandoning)
    trigger: dict[str, tuple[int, int]]  # state -> (fired sessions, consented sessions)
    coverage: dict[str, tuple[int, int]]  # state -> (decisions with content, fired decisions)
    consent: tuple[int, int] | None  # (consented loads, all loads); None without ping data
    auc: AucResult
    sdk_size_bytes: int | None
    latency_p50_us: float | None
    latency_max_us: float | None
    sessions_per_day: float  # consented sessions per day
    proof_days: dict[str, float] = field(default_factory=dict)


def ratio(a: int, b: int) -> float | None:
    return None if b == 0 else a / b


def addressable_share(sessions: pd.DataFrame) -> tuple[int, int]:
    """Abandoning session: viewed a product or cart page and has no order_completed outcome."""
    abandoning = sessions[sessions["abandoned"]]
    touched = (
        abandoning["touched_shipping"] | abandoning["touched_returns"] | abandoning["touched_size"]
    )
    return int(touched.sum()), len(abandoning)


def trigger_counts(consented: pd.DataFrame) -> dict[str, tuple[int, int]]:
    n = len(consented)
    col = {
        "delivery_uncertainty": "fired_delivery",
        "returns_uncertainty": "fired_returns",
        "sizing_uncertainty": "fired_sizing",
    }
    return {st: (int(consented[col[st]].sum()), n) for st in STATES}


def coverage_counts(decisions: pd.DataFrame) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for st in STATES:
        d = decisions[decisions["friction_state"] == st]
        out[st] = (int(d["has_content"].sum()), len(d))
    return out


def consent_counts(pings: pd.DataFrame) -> tuple[int, int] | None:
    if pings.empty:
        return None
    total = int(pings["count"].sum())
    return int(pings.loc[pings["consented"], "count"].sum()), total


def weighted_median(values: pd.Series, weights: pd.Series) -> float:
    order = values.argsort()
    v, w = values.to_numpy()[order], weights.to_numpy()[order].astype(float)
    cum = w.cumsum()
    return float(v[int((cum >= cum[-1] / 2).argmax())])


def latency(summaries: pd.DataFrame) -> tuple[float | None, float | None]:
    """p50: the median of the pages' p50s weighted by how many evaluations each page made (an
    approximation of the overall median). max: the worst single evaluation seen anywhere."""
    s = summaries[summaries["eval_count"] > 0]
    if s.empty:
        return None, None
    return weighted_median(s["eval_p50_us"], s["eval_count"]), float(s["eval_max_us"].max())


def gzipped_size(path: Path) -> int | None:
    """Same measure as `make size`: gzip level 9 of the production bundle."""
    if not path.exists():
        return None
    return len(gzip.compress(path.read_bytes(), compresslevel=9, mtime=0))


def proof_test_days(n_per_arm: int, sessions_per_day: float, trigger_rate: float) -> float:
    """days = 2n / (sessions_per_day x consent_rate x trigger_rate), where sessions_per_day x
    consent_rate is the number of consented sessions per day. Never fewer than 0 triggers: with no
    triggers the test can never finish and the answer is infinity."""
    rate = sessions_per_day * trigger_rate
    return math.inf if rate <= 0 else 2 * n_per_arm / rate


def compute(r: Rollup, cfg: GatesConfig, bundle: Path | None = None) -> Gates:
    s = r.sessions
    consented = s[s["page_views"] > 0]  # sessions in which the SDK ran
    first, last = consented["first_ts"].min(), consented["last_ts"].max()
    span = 1.0 if pd.isna(first) else max(1.0, float((last - first).total_seconds() / 86400))
    per_day = len(consented) / span
    trig = trigger_counts(consented)
    p50, pmax = latency(r.summaries)
    return Gates(
        consented_sessions=len(consented),
        span_days=span,
        addressable=addressable_share(consented),
        trigger=trig,
        coverage=coverage_counts(r.decisions),
        consent=consent_counts(r.pings),
        auc=cross_validated_lift(s, cfg.auc),
        sdk_size_bytes=gzipped_size(bundle or DEFAULT_BUNDLE),
        latency_p50_us=p50,
        latency_max_us=pmax,
        sessions_per_day=per_day,
        proof_days={
            st: proof_test_days(cfg.n_per_arm, per_day, ratio(f, n) or 0.0)
            for st, (f, n) in trig.items()
        },
    )
