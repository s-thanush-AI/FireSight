from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from ...services.context import get_context
from ...services.live import LiveSourceError
from ..schemas import LiveSourceCreateRequest

router = APIRouter(tags=["live"])


@router.get("/live/sources")
def list_sources() -> dict:
    ctx = get_context()
    return {
        "sources": ctx.live.list(),
        "stats": ctx.live.stats(),
        "notice": (
            "RTSP credentials are never returned. 'file' sources are local test "
            "videos, not live cameras. Detection alerts are experimental."
        ),
    }


@router.post("/live/sources", status_code=201)
def create_source(req: LiveSourceCreateRequest) -> dict:
    ctx = get_context()
    try:
        return ctx.live.create(req.model_dump())
    except LiveSourceError as e:
        status = {"not_found": 404, "bad_camera": 404, "limit": 409}.get(e.reason, 422)
        raise HTTPException(status_code=status, detail=str(e)) from e


@router.get("/live/stats")
def live_stats() -> dict:
    return get_context().live.stats()


@router.get("/live/sources/{source_id}")
def get_source(source_id: str) -> dict:
    try:
        return get_context().live.get(source_id).snapshot()
    except LiveSourceError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/live/sources/{source_id}/stop")
def stop_source(source_id: str) -> dict:
    try:
        return get_context().live.stop(source_id)
    except LiveSourceError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/live/sources/{source_id}", status_code=204)
def delete_source(source_id: str) -> Response:
    try:
        get_context().live.delete(source_id)
    except LiveSourceError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(status_code=204)


@router.get("/live/sources/{source_id}/frame")
def latest_frame(source_id: str) -> Response:
    try:
        runtime = get_context().live.get(source_id)
    except LiveSourceError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    frame = runtime.frame()
    if frame is None:
        raise HTTPException(
            status_code=404,
            detail=f"No frame received yet (status: {runtime.snapshot()['status']})",
        )
    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


@router.get("/live/sources/{source_id}/stream")
async def preview_stream(source_id: str) -> StreamingResponse:
    ctx = get_context()
    try:
        runtime = ctx.live.get(source_id)
    except LiveSourceError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    async def frames() -> AsyncIterator[bytes]:
        while True:
            if not runtime.is_alive() and runtime.frame() is None:
                break
            frame = runtime.frame()
            if frame is not None:
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
                    + frame
                    + b"\r\n"
                )
            await asyncio.sleep(0.25)

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )
