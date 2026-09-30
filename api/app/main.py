from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import make_engine
from app.guards import RateLimiter
from app.routers import config, consent, events, health, webhooks
from app.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = make_engine(cfg.database_url)
        try:
            yield
        finally:
            await app.state.engine.dispose()

    # No docs or OpenAPI routes on a public ingest service.
    app = FastAPI(
        title="Ivay API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.settings = cfg
    app.state.limiter = RateLimiter(cfg.rate_limit_per_minute)
    for r in (health, events, consent, config, webhooks):
        app.include_router(r.router)
    return app


app = create_app()
