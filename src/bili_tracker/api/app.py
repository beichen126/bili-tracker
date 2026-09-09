from __future__ import annotations

from fastapi import FastAPI

from bili_tracker import __version__
from bili_tracker.config.runtime import RuntimeConfig


def create_app(config: RuntimeConfig | None = None) -> FastAPI:
    settings = config or RuntimeConfig.from_env()
    app = FastAPI(title="bili-tracker", version=__version__)

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/v1/readiness")
    def readiness() -> dict[str, object]:
        return {
            "status": "ready",
            "capabilities": {"local_api": True, "bilibili": settings.enable_bilibili},
        }

    return app
