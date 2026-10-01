"""Shared helpers for the gate-report tests (not named `tests` on purpose: the API has a package
of that name and the two must not collide)."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import simulate_sessions as sim  # noqa: E402

from ivay_analysis import config, gates, rollup  # noqa: E402

TEST_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://ivay:ivay_dev@127.0.0.1:5432/ivay_test"
)


class Simulated:
    def __init__(self, generated: Any, rollup_: rollup.Rollup, gates_: gates.Gates) -> None:
        self.generated = generated
        self.truth: dict[str, Any] = generated.truth
        self.rollup = rollup_
        self.gates = gates_


def run_simulation(url: str, cfg: config.GatesConfig, bundle: Path, **params: Any) -> Simulated:
    p = sim.Params(**params)
    g = sim.generate(p)
    asyncio.run(sim.write(g, url, truncate=True))
    r = rollup.load(url, p.shop_id)
    return Simulated(g, r, gates.compute(r, cfg, bundle))
