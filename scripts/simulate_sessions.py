"""Session simulator with planted ground truth (spec M7).

It generates the rows the SDK, pixel and webhook would have produced, for consented sessions,
from a generative model whose parameters are known. The gate report (M8) must recover them.
Everything it produces is SIMULATED: it verifies the pipeline and says nothing about any shop.

  python scripts/simulate_sessions.py --sessions 5000 --days 10 --seed 7 --truncate

writes to Postgres under the shop id `sim_shop` (never a real shop) and saves the planted truth
to analysis/out/planted_truth.json.

The generator (`generate`) is pure: no database, no clock, only `random.Random(seed)`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import sys
from bisect import bisect_right
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

SALT = "sim-public-salt"
HOLDOUT_BPS = 5000
EPOCH = datetime(2026, 3, 2, tzinfo=UTC)  # a fixed Monday: the simulator never reads the clock

COUNTRIES = {"DE": 0.50, "AT": 0.10, "FR": 0.15, "NL": 0.10, "US": 0.15}
COVERED_COUNTRIES = ("DE", "AT", "FR")  # the sim shop's config has delivery content for these
N_PRODUCTS = 20
COVERED_PRODUCTS = 11  # sizing content exists for product ids 1..11 (planted coverage 0.55)
SIZE_OPENS = ((0, 0.75), (1, 0.14), (2, 0.07), (3, 0.04))  # distribution of size_chart_opens
MEAN_SHIP_DWELL = 30.0
P_SHIP_BLOCK_VIEWED = 0.25
MEAN_REV = 0.7  # scroll_reversals_30s ~ Poisson
MEAN_TOGGLES = 1.2  # variant_toggles_since_atc ~ Poisson


@dataclass(frozen=True)
class Params:
    sessions: int = 5000  # consented sessions to generate
    days: int = 10
    seed: int = 7
    shop_id: str = "sim_shop"
    p_product_session: float = 0.85  # otherwise the session only has a cart page
    p_ship_visit: float = 0.12
    p_ret_visit: float = 0.06
    consent_rate: float = 0.62
    # outcome model for add_to_cart on product sessions (logit scale)
    b0: float = -0.2
    b_mobile: float = -0.4
    b_cart: float = 0.5  # per ln(cart_value / 50)
    b_ship: float = -0.9  # touched shipping information
    b_size2: float = -0.7  # opened the size chart twice or more
    b_rev: float = -0.25  # per scroll reversal
    p_cart_only_atc: float = 1.0
    p_checkout_given_atc: float = 0.6
    p_order_given_checkout: float = 0.55
    p_cart_only_order: float = 0.3
    median_eval_p50_us: float = 45.0


@dataclass
class Generated:
    params: Params
    config: dict[str, Any]
    page_views: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    summaries: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    pings: dict[tuple[str, bool], int] = field(default_factory=dict)  # (day iso, consented) -> n
    truth: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------- helpers


def poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def pick(rng: random.Random, table: dict[str, float] | tuple[tuple[Any, float], ...]) -> Any:
    items = list(table.items()) if isinstance(table, dict) else list(table)
    r, acc = rng.random(), 0.0
    for value, p in items:
        acc += p
        if r < acc:
            return value
    return items[-1][0]


def hexid(rng: random.Random, n: int = 12) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(n * 2))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def arm_for(visitor_hash: str, salt: str = SALT, bps: int = HOLDOUT_BPS) -> str:
    """Same formula as the SDK: first 8 hex of SHA-256(visitor_hash + salt) mod 10000."""
    return "holdout" if int(sha256(visitor_hash + salt)[:8], 16) % 10000 < bps else "treatment"


def auc(scores: list[float], labels: list[int]) -> float:
    """Rank-based AUC with average ranks for ties."""
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    pos = sum(labels)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return float("nan")
    return (sum(r for r, y in zip(ranks, labels, strict=True) if y) - pos * (pos + 1) / 2) / (
        pos * neg
    )


def sim_config(shop_id: str) -> dict[str, Any]:
    """The simulated shop's config: the valid full fixture with coverage and ids of its own."""
    cfg: dict[str, Any] = json.loads(
        (ROOT / "contracts" / "fixtures" / "valid" / "shop-config.full.json").read_text(
            encoding="utf-8"
        )
    )
    cfg["shop_id"] = shop_id
    cfg["holdout_salt"] = SALT
    cfg["holdout_bps"] = HOLDOUT_BPS
    cfg["consent_ping"] = True
    cfg["log_endpoint"] = "https://sim.example/v1/events"
    cfg["content"] = {
        "delivery_uncertainty": {"by_country": {c: f"shipping_eta:{c}" for c in COVERED_COUNTRIES}},
        "returns_uncertainty": {"shop": "returns_policy:v1"},
        "sizing_uncertainty": {"product_ids": [str(i) for i in range(1, COVERED_PRODUCTS + 1)]},
    }
    return cfg


# ----------------------------------------------------------------------------- the model


def generate(params: Params) -> Generated:
    rng = random.Random(params.seed)
    cfg = sim_config(params.shop_id)
    out = Generated(params=params, config=cfg)
    n_visitors = max(1, int(params.sessions * 0.7))
    visitors = [
        sha256(f"visitor-{params.seed}-{i}") for i in range(n_visitors)
    ]  # already hashed ids
    sessions: list[dict[str, Any]] = []

    for _ in range(params.sessions):
        s = _session(rng, params, visitors, out)
        sessions.append(s)

    out.truth = _truth(params, sessions, out)
    return out


def _session(rng: random.Random, p: Params, visitors: list[str], out: Generated) -> dict[str, Any]:
    sid = hexid(rng, 12)
    vh = rng.choice(visitors)
    device = pick(rng, {"mobile": 0.55, "tablet": 0.05, "desktop": 0.40})
    country = pick(rng, COUNTRIES)
    is_product = rng.random() < p.p_product_session
    product_id = str(rng.randint(1, N_PRODUCTS)) if is_product else None

    ship_visit = rng.random() < p.p_ship_visit
    ret_visit = rng.random() < p.p_ret_visit
    opens = pick(rng, SIZE_OPENS) if is_product else 0
    toggles = poisson(rng, MEAN_TOGGLES) if is_product else 0
    reversals = poisson(rng, MEAN_REV)
    viewed = rng.random() < P_SHIP_BLOCK_VIEWED
    ship_dwell = int(rng.expovariate(1 / MEAN_SHIP_DWELL)) if viewed else 0
    ret_dwell = int(rng.expovariate(1 / 15.0)) if rng.random() < 0.08 else 0
    size_dwell = int(rng.expovariate(1 / 15.0)) if (is_product and rng.random() < 0.15) else 0
    taps = poisson(rng, 0.5)
    hidden = poisson(rng, 0.4)
    cart_value = round(math.exp(rng.gauss(math.log(55), 0.5)), 2)

    touched_ship = ship_visit or ship_dwell > 0
    touched_ret = ret_visit or ret_dwell > 0
    touched_size = opens > 0 or size_dwell > 0

    # outcomes
    if is_product:
        logit = (
            p.b0
            + p.b_mobile * (device == "mobile")
            + p.b_cart * math.log(cart_value / 50)
            + p.b_ship * touched_ship
            + p.b_size2 * (opens >= 2)
            + p.b_rev * reversals
        )
        p_atc = 1 / (1 + math.exp(-logit))
        atc = rng.random() < p_atc
    else:
        p_atc = p.p_cart_only_atc
        atc = rng.random() < p_atc
    checkout = atc and rng.random() < (p.p_checkout_given_atc if is_product else 0.7)
    order = checkout and rng.random() < (
        p.p_order_given_checkout if is_product else p.p_cart_only_order / 0.7
    )

    # the page sequence; the main page is where the page-scoped features live and rules are judged
    main_type = "product" if is_product else "cart"
    seq: list[str] = []
    if is_product:
        seq += ["product"] * poisson(rng, 0.5)
    seq.append(main_type)
    if ship_visit:
        seq.append("shipping_policy")
    if ret_visit:
        seq.append("returns_policy")
    if ship_visit or ret_visit:
        seq.append(main_type)
    main_idx = len(seq) - 1
    if atc and is_product and rng.random() < 0.5:
        seq.append("cart")

    start = EPOCH + timedelta(days=rng.randrange(p.days), seconds=rng.randrange(86400))
    shipping_seen = returns_seen = False
    summaries_feats: list[dict[str, Any]] = []
    for i, page_type in enumerate(seq):
        ts = start + timedelta(seconds=40 * i + rng.randrange(30))
        shipping_seen = shipping_seen or page_type == "shipping_policy"
        returns_seen = returns_seen or page_type == "returns_policy"
        at_or_after_main = i >= main_idx
        is_main = i == main_idx
        feats: dict[str, Any] = {
            "page_type": page_type,
            "device": device,
            "cart_value": cart_value if page_type in ("product", "cart") else None,
            "shipping_block_dwell_s": ship_dwell if is_main else 0,
            "returns_block_dwell_s": ret_dwell if is_main else 0,
            "size_block_dwell_s": size_dwell if is_main else 0,
            "scroll_reversals_30s": reversals if is_main else 0,
            "variant_toggles_since_atc": toggles if is_main else 0,
            "repeated_taps_5s": taps if is_main else 0,
            "shipping_page_visited": shipping_seen,
            "returns_page_visited": returns_seen,
            "size_chart_opens": opens if at_or_after_main else 0,
            "tab_hidden_count": hidden if at_or_after_main else 0,
            "pages_viewed": i + 1,
            "cart_adds": 1 if (atc and at_or_after_main) else 0,
        }
        summaries_feats.append(feats)
        pv_country = country if rng.random() < 0.97 else None
        out.page_views.append(
            {
                "event_id": hexid(rng),
                "shop_id": p.shop_id,
                "visitor_hash": vh,
                "session_id": sid,
                "page_id": hexid(rng),
                "ts": ts,
                "received_at": ts + timedelta(seconds=1),
                "page_type": page_type,
                "device": device,
                "product_id": product_id if page_type == "product" else None,
                "country": pv_country,
            }
        )
        n_eval = 5 + poisson(rng, 12)
        p50 = round(math.exp(rng.gauss(math.log(p.median_eval_p50_us), 0.25)), 1)
        out.summaries.append(
            {
                "event_id": hexid(rng),
                "shop_id": p.shop_id,
                "session_id": sid,
                "page_id": hexid(rng),
                "ts": ts + timedelta(seconds=30),
                "received_at": ts + timedelta(seconds=31),
                "features": feats,
                "eval_count": n_eval,
                "eval_p50_us": p50,
                "eval_max_us": round(p50 * (1 + math.exp(rng.gauss(1.2, 0.6))), 1),
            }
        )

    # rules, judged on the main page's features exactly as the SDK's interpreter would
    mf = summaries_feats[main_idx]
    fired: list[str] = []
    if mf["shipping_page_visited"] or (
        mf["shipping_block_dwell_s"] >= 40 and mf["scroll_reversals_30s"] >= 2
    ):
        fired.append("delivery_uncertainty")
    if mf["returns_page_visited"]:
        fired.append("returns_uncertainty")
    if main_type == "product" and (
        mf["size_chart_opens"] >= 2 or mf["variant_toggles_since_atc"] >= 3
    ):
        fired.append("sizing_uncertainty")
    rng.shuffle(fired)  # the simulator does not model the order in which conditions became true
    arm = arm_for(vh)
    main_ts = out.page_views[-len(seq) + main_idx]["ts"]
    for seq_no, state in enumerate(fired, start=1):
        if state == "delivery_uncertainty":
            ref = out.config["content"]["delivery_uncertainty"]["by_country"].get(country)
            covered = ref is not None
        elif state == "returns_uncertainty":
            ref, covered = "returns_policy:v1", True
        else:
            covered = product_id is not None and int(product_id) <= COVERED_PRODUCTS
            ref = f"size_chart:{product_id}" if covered else None
        out.decisions.append(
            {
                "decision_id": hexid(rng),
                "event_id": hexid(rng),
                "shop_id": p.shop_id,
                "visitor_hash": vh,
                "session_id": sid,
                "page_id": hexid(rng),
                "ts": main_ts + timedelta(seconds=5),
                "received_at": main_ts + timedelta(seconds=6),
                "friction_state": state,
                "rule_id": state.split("_")[0] + "_v1",
                "rule_version": "r1",
                "fire_seq": seq_no,
                "arm": arm,
                "mode": "shadow",
                "play": None,
                "propensity": None,
                "content_ref": ref,
                "has_content": covered,
                "features": mf,
            }
        )

    end = start + timedelta(seconds=40 * len(seq) + 60)
    for kind, happened, source, value in (
        ("add_to_cart", atc, "sdk", None),
        ("checkout_started", checkout, "pixel", cart_value),
        ("order_completed", order, "webhook", cart_value),
    ):
        if happened:
            out.outcomes.append(
                {
                    "event_id": hexid(rng),
                    "shop_id": p.shop_id,
                    "session_id": sid,
                    "kind": kind,
                    "value": value,
                    "source": source,
                    "ts": end,
                    "received_at": end + timedelta(seconds=1),
                }
            )

    # consent pings: every consented page load, plus the loads that were not consented (added later)
    day = start.date().isoformat()
    out.pings[(day, True)] = out.pings.get((day, True), 0) + len(seq)

    return {
        "sid": sid,
        "vh": vh,
        "arm": arm,
        "is_product": is_product,
        "device": device,
        "country": country,
        "cart_value": cart_value,
        "p_atc": p_atc if is_product else None,
        "atc": atc,
        "order": order,
        "touched": (touched_ship, touched_ret, touched_size),
        "fired": fired,
        "day": day,
        "product_id": product_id,
        "viewed_product_or_cart": True,
        "n_pages": len(seq),
    }


def _truth(p: Params, sessions: list[dict[str, Any]], out: Generated) -> dict[str, Any]:
    # add the pings of page loads that were not consented, so the planted consent rate holds
    rng = random.Random(p.seed + 1)
    for (day, consented), n in list(out.pings.items()):
        if consented:
            failures = sum(
                int(math.log(1 - rng.random()) / math.log(1 - p.consent_rate)) for _ in range(n)
            )
            out.pings[(day, False)] = out.pings.get((day, False), 0) + failures

    n = len(sessions)
    abandoning = [s for s in sessions if not s["order"]]
    addressable = [s for s in abandoning if any(s["touched"])]
    fired = {
        st: sum(st in s["fired"] for s in sessions)
        for st in ("delivery_uncertainty", "returns_uncertainty", "sizing_uncertainty")
    }
    decisions = {st: [d for d in out.decisions if d["friction_state"] == st] for st in fired}

    # closed-form trigger rates from the planted parameters
    p_dwell40 = P_SHIP_BLOCK_VIEWED * math.exp(-40 / MEAN_SHIP_DWELL)
    p_rev2 = 1 - math.exp(-MEAN_REV) * (1 + MEAN_REV)
    p_delivery = p.p_ship_visit + (1 - p.p_ship_visit) * p_dwell40 * p_rev2
    p_opens2 = sum(pr for k, pr in SIZE_OPENS if k >= 2)
    p_tog3 = 1 - math.exp(-MEAN_TOGGLES) * (1 + MEAN_TOGGLES + MEAN_TOGGLES**2 / 2)
    p_sizing = p.p_product_session * (1 - (1 - p_opens2) * (1 - p_tog3))
    param_trigger = {
        "delivery_uncertainty": p_delivery,
        "returns_uncertainty": p.p_ret_visit,
        "sizing_uncertainty": p_sizing,
    }
    param_coverage = {
        "delivery_uncertainty": sum(COUNTRIES[c] for c in COVERED_COUNTRIES),
        "returns_uncertainty": 1.0,
        "sizing_uncertainty": COVERED_PRODUCTS / N_PRODUCTS,
    }

    # oracle AUC lift of signals over the baseline, from the true add_to_cart probabilities
    prod = [s for s in sessions if s["is_product"]]
    y = [int(s["atc"]) for s in prod]
    p_full = [s["p_atc"] for s in prod]
    cuts = sorted(s["cart_value"] for s in prod)
    bucket = [min(9, bisect_right(cuts, s["cart_value"]) * 10 // max(1, len(cuts))) for s in prod]
    sums: dict[tuple[str, int], list[float]] = {}
    for s, b, pf in zip(prod, bucket, p_full, strict=True):
        sums.setdefault((s["device"], b), []).append(pf)
    p_base = [
        sum(sums[(s["device"], b)]) / len(sums[(s["device"], b)])
        for s, b in zip(prod, bucket, strict=True)
    ]
    oracle_full, oracle_base = auc(p_full, y), auc(p_base, y)

    all_p50 = sorted(s["eval_p50_us"] for s in out.summaries)
    holdout = sum(s["arm"] == "holdout" for s in sessions) / n
    pings_yes = sum(v for (d, c), v in out.pings.items() if c)
    pings_all = sum(out.pings.values())
    return {
        "note": "SIMULATED: pipeline check only",
        "params": asdict(p),
        "consented_sessions": n,
        "parameters": {  # closed form from the planted parameters
            "consent_rate": p.consent_rate,
            "trigger_rate": param_trigger,
            "grounded_coverage": param_coverage,
            "median_eval_p50_us": p.median_eval_p50_us,
            "holdout_share": HOLDOUT_BPS / 10000,
        },
        "empirical": {  # computed from the latent variables of the generated sessions
            "abandoning_sessions": len(abandoning),
            "addressable_sessions": len(addressable),
            "addressable_share": len(addressable) / len(abandoning),
            "fired_sessions": fired,
            "trigger_rate": {st: v / n for st, v in fired.items()},
            "fired_decisions": {st: len(d) for st, d in decisions.items()},
            "grounded_coverage": {
                st: (sum(d["has_content"] for d in ds) / len(ds) if ds else None)
                for st, ds in decisions.items()
            },
            "consent_rate": pings_yes / pings_all,
            "holdout_share": holdout,
            "median_eval_p50_us": all_p50[len(all_p50) // 2],
            "max_eval_max_us": max(s["eval_max_us"] for s in out.summaries),
            "oracle_auc_full": oracle_full,
            "oracle_auc_baseline": oracle_base,
            "oracle_auc_lift": oracle_full - oracle_base,
            "product_sessions": len(prod),
            "add_to_cart_rate_product": sum(y) / len(y),
            "sessions_per_day": n / p.days,
        },
    }


# ----------------------------------------------------------------------------- database


async def write(gen: Generated, database_url: str, truncate: bool) -> None:
    from sqlalchemy import delete, text
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.ext.asyncio import create_async_engine

    from app import models as m

    shop_id = gen.params.shop_id
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        if truncate:
            for table in (
                m.page_view,
                m.decision_log,
                m.page_summary,
                m.outcome_event,
                m.consent_ping_daily,
            ):
                await conn.execute(delete(table).where(table.c.shop_id == shop_id))
        await conn.execute(
            text(
                "INSERT INTO shop (shop_id, platform, allowed_origins, config, webhook_secret_ref) "
                "VALUES (:id, 'shopify', ARRAY['https://sim.example'], CAST(:cfg AS jsonb), NULL) "
                "ON CONFLICT (shop_id) DO UPDATE SET config = CAST(:cfg AS jsonb)"
            ),
            {"id": shop_id, "cfg": json.dumps(gen.config)},
        )
        for table, rows in (
            (m.page_view, gen.page_views),
            (m.decision_log, gen.decisions),
            (m.page_summary, gen.summaries),
            (m.outcome_event, gen.outcomes),
        ):
            for i in range(0, len(rows), 2000):
                await conn.execute(insert(table).on_conflict_do_nothing(), rows[i : i + 2000])
        for (day, consented), n in gen.pings.items():
            await conn.execute(
                text(
                    "INSERT INTO consent_ping_daily (shop_id, day, consented, count) "
                    "VALUES (:s, :d, :c, :n) "
                    "ON CONFLICT (shop_id, day, consented) DO UPDATE SET count = :n"
                ),
                {"s": shop_id, "d": date.fromisoformat(day), "c": consented, "n": n},
            )
    await engine.dispose()


def main() -> None:
    ap = argparse.ArgumentParser(description="Write simulated sessions with planted ground truth.")
    ap.add_argument("--sessions", type=int, default=5000)
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--shop", default="sim_shop")
    ap.add_argument("--truncate", action="store_true", help="delete this shop's rows first")
    ap.add_argument("--truth", default=str(ROOT / "analysis" / "out" / "planted_truth.json"))
    args = ap.parse_args()
    if args.shop in ("shop_dev",) or not args.shop.startswith("sim"):
        sys.exit("refusing to write simulated data under a non-simulation shop id (use sim_*)")
    gen = generate(
        Params(sessions=args.sessions, days=args.days, seed=args.seed, shop_id=args.shop)
    )
    url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://ivay:ivay_dev@127.0.0.1:5432/ivay")
    asyncio.run(write(gen, url, args.truncate))
    Path(args.truth).parent.mkdir(parents=True, exist_ok=True)
    Path(args.truth).write_text(json.dumps(gen.truth, indent=2, default=str), encoding="utf-8")
    e = gen.truth["empirical"]
    print(
        f"SIMULATED: pipeline check only. shop={args.shop} sessions={args.sessions} "
        f"page_views={len(gen.page_views)} decisions={len(gen.decisions)} "
        f"outcomes={len(gen.outcomes)}\n"
        f"planted truth saved to {args.truth}\n"
        f"addressable share {e['addressable_share']:.3f}, trigger rates "
        + ", ".join(f"{k.split('_')[0]} {v:.3f}" for k, v in e["trigger_rate"].items())
    )


if __name__ == "__main__":
    main()
