from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routes.analyst import router as analyst_router
from api.telemetry import setup_telemetry
from api.routes.fantasy import router as fantasy_router
from api.routes.health import router as health_router
from api.routes.parlays import router as parlays_router
from api.routes.players import router as players_router
from api.routes.props import router as props_router
from api.routes.slate import router as slate_router
from api.settings import AppSettings, get_settings


def _error_body(code: str, message: str) -> dict:
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "request_id": str(uuid.uuid4())},
    }


def create_app(settings: AppSettings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    app = FastAPI(title=app_settings.app_name)
    app.state.settings = app_settings

    # `*` is incompatible with `allow_credentials=True` in the CORS spec; browsers reject
    # the response, which surfaces as the frontend "Failed to fetch" for cross-origin calls.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://tauri.localhost", "tauri://localhost", "http://localhost:1420"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(str(exc.status_code), str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body("validation_error", str(exc)),
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=_error_body("internal_error", str(exc)),
        )

    app.include_router(health_router, prefix=app_settings.api_prefix)
    app.include_router(slate_router, prefix=app_settings.api_prefix)
    app.include_router(players_router, prefix=app_settings.api_prefix)
    app.include_router(props_router, prefix=app_settings.api_prefix)
    app.include_router(fantasy_router, prefix=app_settings.api_prefix)
    app.include_router(parlays_router, prefix=app_settings.api_prefix)
    app.include_router(analyst_router, prefix=app_settings.api_prefix)

    setup_telemetry(app, app_settings.docs_dir / "telemetry")
    return app


app = create_app()
