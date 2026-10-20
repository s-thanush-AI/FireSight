from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .. import __version__
from ..services.context import AppContext, get_context, set_context

log = logging.getLogger(__name__)


def create_app(ctx: AppContext | None = None) -> FastAPI:
    if ctx is not None:
        set_context(ctx)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        context = get_context()
        context.startup()
        yield
        context.shutdown()

    app = FastAPI(
        title="FireSight API",
        version=__version__,
        description=(
            "Wildfire smoke detection and geolocation research prototype. "
            "Demo mode uses clearly labeled SIMULATED data. Not an operational "
            "warning service."
        ),
        lifespan=lifespan,
    )

    settings = get_context().settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover - safety net
        log.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error. See server logs for details."},
        )

    from .routers import (
        alerts,
        cameras,
        datasets,
        evaluation,
        geometry,
        health,
        incidents,
        inference,
        live,
        models,
        replays,
        sequences,
        verification,
        videos,
        ws,
    )

    prefix = "/api/v1"
    app.include_router(health.router, prefix=prefix)
    app.include_router(models.router, prefix=prefix)
    app.include_router(datasets.router, prefix=prefix)
    app.include_router(sequences.router, prefix=prefix)
    app.include_router(replays.router, prefix=prefix)
    app.include_router(videos.router, prefix=prefix)
    app.include_router(alerts.router, prefix=prefix)
    app.include_router(live.router, prefix=prefix)
    app.include_router(incidents.router, prefix=prefix)
    app.include_router(cameras.router, prefix=prefix)
    app.include_router(geometry.router, prefix=prefix)
    app.include_router(evaluation.router, prefix=prefix)
    app.include_router(verification.router, prefix=prefix)
    app.include_router(inference.router, prefix=prefix)
    app.include_router(ws.router, prefix=prefix)
    return app
