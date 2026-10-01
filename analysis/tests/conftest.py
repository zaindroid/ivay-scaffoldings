"""Fixtures for the gate-report tests.

They use the same Postgres test database as the API tests and its Alembic migrations (the schema
has one source), generate SIMULATED sessions with planted truth, write them, and run the real
loader and gate code against the database.
"""

import gzip
import os
import subprocess
import sys
from pathlib import Path

import pytest
from support import REPO, TEST_URL, Simulated, run_simulation

from ivay_analysis import config


@pytest.fixture(scope="session")
def migrated() -> str:
    """Build the test database from the API's migrations (alembic is the only source of schema)."""
    env = {**os.environ, "DATABASE_URL": TEST_URL}
    for args in (["downgrade", "base"], ["upgrade", "head"]):
        subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=REPO / "api",
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    return TEST_URL


@pytest.fixture(scope="session")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A stand-in production bundle of known gzipped size (the real one is built by `make size`)."""
    path = tmp_path_factory.mktemp("bundle") / "ivay.js"
    path.write_text("function f(){return 1}\n" * 400, encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def bundle_gzip_size(bundle: Path) -> int:
    return len(gzip.compress(bundle.read_bytes(), compresslevel=9, mtime=0))


@pytest.fixture(scope="session")
def cfg() -> config.GatesConfig:
    return config.load()


@pytest.fixture(scope="session")
def simulated(migrated: str, cfg: config.GatesConfig, bundle: Path) -> Simulated:
    """6,000 simulated sessions with the default planted effects."""
    return run_simulation(migrated, cfg, bundle, sessions=6000, seed=7)


@pytest.fixture(scope="session")
def simulated_null(migrated: str, cfg: config.GatesConfig, bundle: Path) -> Simulated:
    """Control: the same shop with every planted signal effect switched off."""
    return run_simulation(
        migrated,
        cfg,
        bundle,
        sessions=6000,
        seed=9,
        shop_id="sim_null",
        b_ship=0.0,
        b_size2=0.0,
        b_rev=0.0,
    )
