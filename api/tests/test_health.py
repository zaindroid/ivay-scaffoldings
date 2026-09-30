from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def test_health_ok_with_real_database(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "db": "ok"}


def test_health_degraded_when_database_unreachable() -> None:
    unreachable = Settings(database_url="postgresql+asyncpg://x:y@127.0.0.1:1/none")
    with TestClient(create_app(unreachable)) as client:
        res = client.get("/health")
    assert res.status_code == 503
    assert res.json() == {"status": "degraded", "db": "unavailable"}
