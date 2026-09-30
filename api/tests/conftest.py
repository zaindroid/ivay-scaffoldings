import asyncio
import json
import os
from collections.abc import Callable, Coroutine, Iterator
from pathlib import Path
from typing import Any, TypeVar

import pytest
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.main import create_app
from app.settings import Settings

T = TypeVar("T")
API_DIR = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = API_DIR.parent / "contracts"
ORIGIN = "https://shop.example"
TABLES = [
    "page_view",
    "decision_log",
    "page_summary",
    "outcome_event",
    "consent_ping_daily",
    "shop",
]


@pytest.fixture(scope="session")
def contracts_dir() -> Path:
    return CONTRACTS_DIR


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://ivay:ivay_dev@127.0.0.1:5432/ivay_test",
    )
    return Settings(database_url=url)


@pytest.fixture(scope="session")
def migrated(test_settings: Settings) -> Settings:
    """Alembic is the only source of schema: build the test database from the migrations."""
    os.environ["DATABASE_URL"] = test_settings.database_url
    cfg = AlembicConfig(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return test_settings


class Db:
    """Direct database access for assertions, on its own connection and event loop."""

    def __init__(self, url: str) -> None:
        self.url = url

    def _run(self, fn: Callable[[Any], Coroutine[Any, Any, T]]) -> T:
        async def go() -> T:
            engine = create_async_engine(self.url, poolclass=NullPool)
            try:
                async with engine.begin() as conn:
                    return await fn(conn)
            finally:
                await engine.dispose()

        return asyncio.run(go())

    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        async def q(conn: Any) -> list[dict[str, Any]]:
            res = await conn.execute(text(sql), params)
            return [dict(r._mapping) for r in res]

        return self._run(q)

    def execute(self, sql: str, **params: Any) -> None:
        async def q(conn: Any) -> None:
            await conn.execute(text(sql), params)

        self._run(q)

    def count(self, table: str) -> int:
        return int(self.rows(f"SELECT count(*) AS n FROM {table}")[0]["n"])

    def dump_all(self) -> str:
        """Every stored value as one string, to prove something was never stored."""
        out: list[str] = []
        for t in TABLES:
            out.append(json.dumps(self.rows(f"SELECT * FROM {t}"), default=str))
        return "\n".join(out)

    def seed_shop(
        self,
        shop_id: str = "shop_dev",
        origins: list[str] | None = None,
        secret_ref: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config if config is not None else full_config(shop_id)
        self.execute(
            "INSERT INTO shop (shop_id, platform, allowed_origins, config, webhook_secret_ref) "
            "VALUES (:id, 'shopify', :origins, CAST(:cfg AS jsonb), :ref)",
            id=shop_id,
            origins=origins if origins is not None else [ORIGIN],
            cfg=json.dumps(cfg),
            ref=secret_ref,
        )


def full_config(shop_id: str = "shop_dev") -> dict[str, Any]:
    cfg: dict[str, Any] = json.loads(
        (CONTRACTS_DIR / "fixtures" / "valid" / "shop-config.full.json").read_text()
    )
    cfg["shop_id"] = shop_id
    return cfg


def fixture_json(kind: str, name: str) -> Any:
    return json.loads((CONTRACTS_DIR / "fixtures" / kind / name).read_text())


@pytest.fixture
def db(migrated: Settings) -> Iterator[Db]:
    d = Db(migrated.database_url)
    d.execute(f"TRUNCATE {', '.join(TABLES)}")
    yield d


@pytest.fixture
def make_client(db: Db, migrated: Settings) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def make(**overrides: Any) -> TestClient:
        c = TestClient(create_app(Settings(database_url=migrated.database_url, **overrides)))
        c.__enter__()
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


def post_events(
    client: TestClient,
    body: Any,
    origin: str | None = ORIGIN,
    content_type: str = "text/plain;charset=UTF-8",
    extra_headers: dict[str, str] | None = None,
) -> Any:
    """POST the way navigator.sendBeacon does: a JSON string as text/plain."""
    headers = {"Content-Type": content_type, **(extra_headers or {})}
    if origin is not None:
        headers["Origin"] = origin
    content = body if isinstance(body, bytes) else json.dumps(body)
    return client.post("/v1/events", content=content, headers=headers)
