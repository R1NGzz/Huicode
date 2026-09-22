from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live(request: Request):
    return {"status": "alive", "request_id": request.state.request_id}


@router.get("/ready")
async def ready(request: Request):
    dependencies = await request.app.state.health.check()
    available = all(value == "ok" for value in dependencies.values())
    return JSONResponse(
        status_code=200 if available else 503,
        content={
            "status": "ready" if available else "not_ready",
            "dependencies": dependencies,
            "request_id": request.state.request_id,
        },
    )
