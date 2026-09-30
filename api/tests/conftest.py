import os
from pathlib import Path

import pytest

from app.settings import Settings

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"


@pytest.fixture(scope="session")
def contracts_dir() -> Path:
    return CONTRACTS_DIR


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://ivay:ivay_dev@localhost:5432/ivay_test",
    )
    return Settings(database_url=url)
