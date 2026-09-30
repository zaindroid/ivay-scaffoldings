from fastapi import APIRouter, Request, Response
from sqlalchemy import text

router = APIRouter()


@router.get("/health")
async def health(request: Request, response: Response) -> dict[str, str]:
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        # Deliberately no detail: connection errors can carry host names.
        response.status_code = 503
        return {"status": "degraded", "db": "unavailable"}
    return {"status": "ok", "db": "ok"}
