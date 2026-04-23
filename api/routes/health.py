from __future__ import annotations

from fastapi import APIRouter, Request

from api.schemas import HealthResponse
from api.services.replay_service import get_replay_artifacts

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    artifacts_available = False
    try:
        get_replay_artifacts(settings)
        artifacts_available = True
    except Exception:
        artifacts_available = False

    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        docs_dir=str(settings.docs_dir),
        sample_props_path=str(settings.sample_props_path),
        replay_artifacts_available=artifacts_available,
        default_replay_years=list(settings.default_replay_years),
        weather_source=settings.weather_source,
        llama_cpp_base_url=settings.llama_cpp_base_url,
    )
