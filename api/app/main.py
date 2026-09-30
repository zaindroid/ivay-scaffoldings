from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import make_engine
from app.routers import health
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

    app = FastAPI(title="Ivay API", lifespan=lifespan)
    app.include_router(health.router)
    return app


app = create_app()
