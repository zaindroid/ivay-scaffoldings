"""Prints the eight gate numbers next to their thresholds. A failing number is never hidden.

Numbers from simulated data only verify the pipeline: every simulated report carries the label
"SIMULATED: pipeline check only" and says so again at the end (spec section 2).
"""

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ivay_analysis import STATES
from ivay_analysis.config import GatesConfig, Threshold
from ivay_analysis.config import load as load_config
from ivay_analysis.gates import DEFAULT_BUNDLE, Gates, compute, ratio
from ivay_analysis.rollup import load

SIMULATED_LABEL = "SIMULATED: pipeline check only"
NOT_AVAILABLE_CONSENT = "not available (consent_ping disabled)"


def is_simulated(shop_id: str) -> bool:
    """The simulator only writes under shop ids that start with `sim`."""
    return shop_id.startswith("sim")


@dataclass(frozen=True)
class Row:
    number: int
    label: str
    value: float | None
    shown: str  # the value as text
    threshold: Threshold
    verdict: str  # "pass", "FAIL" or "not available"
    detail: str = ""


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _verdict(t: Threshold, v: float | None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "not available"
    return "pass" if t.passes(v) else "FAIL"


def rows(g: Gates, cfg: GatesConfig) -> list[Row]:
    t = cfg.thresholds
    out: list[Row] = []

    a, b = g.addressable
    share = ratio(a, b)
    out.append(
        Row(
            1,
            "Addressable share of abandoning sessions",
            share,
            _pct(share),
            t["addressable_share"],
            _verdict(t["addressable_share"], share),
            f"{a} of {b} abandoning sessions touched shipping, returns or size information",
        )
    )
    for st in STATES:
        f, n = g.trigger[st]
        v = ratio(f, n)
        out.append(
            Row(
                2,
                f"Trigger rate: {st}",
                v,
                _pct(v),
                t["trigger_rate"],
                _verdict(t["trigger_rate"], v),
                f"{f} fired of {n} consented sessions",
            )
        )
    for st in STATES:
        c, n = g.coverage[st]
        v = ratio(c, n)
        shown = _pct(v) if v is not None else "n/a (nothing fired)"
        out.append(
            Row(
                3,
                f"Grounded-answer coverage: {st}",
                v,
                shown,
                t["grounded_coverage"],
                _verdict(t["grounded_coverage"], v),
                f"{c} of {n} fired decisions had content",
            )
        )
    if g.consent is None:
        out.append(
            Row(4, "Consent rate", None, NOT_AVAILABLE_CONSENT, t["consent_rate"], "not available")
        )
    else:
        v = ratio(*g.consent)
        out.append(
            Row(
                4,
                "Consent rate",
                v,
                _pct(v),
                t["consent_rate"],
                _verdict(t["consent_rate"], v),
                f"{g.consent[0]} consented of {g.consent[1]} page loads",
            )
        )
    u = g.auc
    shown = "not computable" if math.isnan(u.lift) else f"{u.lift:+.3f}"
    detail = u.note or (
        f"AUC {u.auc_full:.3f} with signals vs {u.auc_base:.3f} baseline; {u.n} sessions, "
        f"{u.positives} positive, {u.folds}-fold CV"
    )
    out.append(
        Row(
            5,
            "Signal lift (cross-validated AUC)",
            None if math.isnan(u.lift) else u.lift,
            shown,
            t["signal_lift_auc"],
            _verdict(t["signal_lift_auc"], u.lift),
            detail,
        )
    )
    sz = g.sdk_size_bytes
    out.append(
        Row(
            6,
            "SDK size (gzipped bytes)",
            None if sz is None else float(sz),
            "not available (build the SDK: make size)" if sz is None else f"{sz}",
            t["sdk_size_bytes"],
            _verdict(t["sdk_size_bytes"], None if sz is None else float(sz)),
        )
    )
    for key, label, v in (
        ("decision_latency_p50_us", "Decision latency p50 (us)", g.latency_p50_us),
        ("decision_latency_max_us", "Decision latency max (us)", g.latency_max_us),
    ):
        out.append(
            Row(
                7,
                label,
                v,
                "not available" if v is None else f"{v:.1f}",
                t[key],
                _verdict(t[key], v),
            )
        )
    for st in STATES:
        d = g.proof_days[st]
        shown = "never (no triggers)" if math.isinf(d) else f"{d:.1f}"
        out.append(
            Row(
                8,
                f"Proof-test duration (days): {st}",
                None if math.isinf(d) else d,
                shown,
                t["proof_test_days"],
                "FAIL" if math.isinf(d) else _verdict(t["proof_test_days"], d),
                f"2 x {cfg.n_per_arm} / ({g.sessions_per_day:.1f} consented sessions per day "
                f"x trigger rate)",
            )
        )
    return out


def render(g: Gates, cfg: GatesConfig, shop_id: str, simulated: bool) -> str:
    rs = rows(g, cfg)
    lines: list[str] = []
    if simulated:
        lines += [
            f"{SIMULATED_LABEL}.",
            "These numbers verify the pipeline. They say nothing about any shop and are "
            "NOT gate results.",
            "",
        ]
    lines.append(
        f"Shop: {shop_id}   consented sessions: {g.consented_sessions}   "
        f"observed span: {g.span_days:.1f} days"
    )
    lines.append("")
    head = f"{'#':>2}  {'Number':<52} {'Value':>22}  {'Threshold':<16} Verdict"
    lines += [head, "-" * len(head)]
    for r in rs:
        flag = "" if r.threshold.provisional else " (spec)"
        lines.append(
            f"{r.number:>2}  {r.label:<52} {r.shown:>22}  {r.threshold.describe() + flag:<16} "
            f"{r.verdict}{' (simulated)' if simulated else ''}"
        )
        if r.detail:
            lines.append(f"      {r.detail}")
    lines.append("")
    failing = [f"{r.number} {r.label}" for r in rs if r.verdict == "FAIL"]
    missing = [f"{r.number} {r.label}" for r in rs if r.verdict == "not available"]
    prov = sorted(k for k, v in cfg.thresholds.items() if v.provisional)
    lines.append(
        f"{sum(r.verdict == 'pass' for r in rs)} of {len(rs)} rows pass, {len(failing)} fail, "
        f"{len(missing)} not available."
    )
    for label, items in (("FAILING", failing), ("NOT AVAILABLE", missing)):
        for item in items:
            lines.append(f"  {label}: {item}")
    lines.append(
        "Thresholds are PROVISIONAL (proposed by Claude) except the SDK size limit, which the spec "
        "fixes: " + ", ".join(prov)
    )
    if simulated:
        lines += ["", f"{SIMULATED_LABEL}. Do not read these verdicts as gate results."]
    return "\n".join(lines)


def as_json(g: Gates, cfg: GatesConfig, shop_id: str, simulated: bool) -> dict[str, object]:
    return {
        "label": SIMULATED_LABEL if simulated else "pilot data",
        "simulated": simulated,
        "shop_id": shop_id,
        "consented_sessions": g.consented_sessions,
        "span_days": g.span_days,
        "rows": [
            {
                "number": r.number,
                "label": r.label,
                "value": r.value,
                "shown": r.shown,
                "threshold": r.threshold.describe(),
                "threshold_status": r.threshold.status,
                "verdict": r.verdict,
                "detail": r.detail,
            }
            for r in rows(g, cfg)
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 0 gate report")
    ap.add_argument("--shop", required=True, help="shop id; ids starting with 'sim' are simulated")
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument(
        "--config", type=Path, default=None, help="gates.yaml (default: analysis/gates.yaml)"
    )
    ap.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE, help="the production SDK bundle")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.database_url:
        print("No database: pass --database-url or set DATABASE_URL.", file=sys.stderr)
        return 2
    cfg = load_config(args.config)
    r = load(args.database_url, args.shop)
    if r.sessions.empty:
        print(f"No sessions for shop {args.shop!r}. Nothing to report.", file=sys.stderr)
        return 1
    g = compute(r, cfg, args.bundle)
    sim = is_simulated(args.shop)
    if args.json:
        print(json.dumps(as_json(g, cfg, args.shop, sim), indent=2))
    else:
        print(render(g, cfg, args.shop, sim))
    return 0


if __name__ == "__main__":
    sys.exit(main())
