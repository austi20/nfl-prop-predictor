from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.analyst import router as analyst_router
from api.routes.fantasy import router as fantasy_router
from api.routes.health import router as health_router
from api.routes.parlays import router as parlays_router
from api.routes.players import router as players_router
from api.routes.props import router as props_router
from api.routes.slate import router as slate_router
from api.settings import AppSettings, get_settings


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

    app.include_router(health_router, prefix=app_settings.api_prefix)
    app.include_router(slate_router, prefix=app_settings.api_prefix)
    app.include_router(players_router, prefix=app_settings.api_prefix)
    app.include_router(props_router, prefix=app_settings.api_prefix)
    app.include_router(fantasy_router, prefix=app_settings.api_prefix)
    app.include_router(parlays_router, prefix=app_settings.api_prefix)
    app.include_router(analyst_router, prefix=app_settings.api_prefix)
    return app


app = create_app()
