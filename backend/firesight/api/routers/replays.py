from fastapi import APIRouter, HTTPException

from ...api.schemas import ReplayCreateRequest, ReplayFrameResponse, ReplayStatusResponse
from ...services.context import get_context
from ...services.replay_manager import ReplayError

router = APIRouter(tags=["replays"])


@router.post("/replays", response_model=ReplayStatusResponse)
def create_replay(body: ReplayCreateRequest) -> ReplayStatusResponse:
    ctx = get_context()
    try:
        session = ctx.replay_manager.create(body.sequence_id, body.camera_id, body.speed)
    except ReplayError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return ReplayStatusResponse(**session.to_dict())


@router.get("/replays")
def list_replays() -> dict:
    ctx = get_context()
    items = ctx.replay_manager.list()
    return {"items": items, "total": len(items)}


@router.get("/replays/{replay_id}", response_model=ReplayStatusResponse)
def get_replay(replay_id: str) -> ReplayStatusResponse:
    ctx = get_context()
    try:
        session = ctx.replay_manager.get(replay_id)
    except ReplayError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ReplayStatusResponse(**session.to_dict())


def _control(replay_id: str, action: str) -> ReplayStatusResponse:
    ctx = get_context()
    try:
        session = ctx.replay_manager.get(replay_id)
    except ReplayError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if action == "pause":
        session.pause()
    elif action == "resume":
        session.resume()
    elif action == "reset":
        session.reset()
    return ReplayStatusResponse(**session.to_dict())


@router.post("/replays/{replay_id}/pause", response_model=ReplayStatusResponse)
def pause_replay(replay_id: str) -> ReplayStatusResponse:
    return _control(replay_id, "pause")


@router.post("/replays/{replay_id}/resume", response_model=ReplayStatusResponse)
def resume_replay(replay_id: str) -> ReplayStatusResponse:
    return _control(replay_id, "resume")


@router.post("/replays/{replay_id}/reset", response_model=ReplayStatusResponse)
def reset_replay(replay_id: str) -> ReplayStatusResponse:
    return _control(replay_id, "reset")


@router.post("/replays/{replay_id}/step")
def step_replay(replay_id: str, n: int = 1) -> dict:
    ctx = get_context()
    if not (1 <= n <= 100):
        raise HTTPException(status_code=422, detail="n must be between 1 and 100")
    try:
        session = ctx.replay_manager.get(replay_id)
    except ReplayError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    meta = session.step(n)
    return {
        "replay_id": replay_id,
        "frame": meta,
        "status": session.to_dict(),
    }


@router.get("/replays/{replay_id}/frames/current", response_model=ReplayFrameResponse)
def current_frame(replay_id: str) -> ReplayFrameResponse:
    ctx = get_context()
    try:
        session = ctx.replay_manager.get(replay_id)
    except ReplayError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return ReplayFrameResponse(
        replay_id=replay_id,
        frame=session.current_meta,
        image_jpeg_base64=session.current_jpeg_b64,
        original_jpeg_base64=session.current_original_b64,
        detections=session.last_detections,
        events=list(session.events)[-30:],
    )


@router.get("/replays/{replay_id}/events")
def replay_events(replay_id: str, since: int = 0) -> dict:
    ctx = get_context()
    try:
        session = ctx.replay_manager.get(replay_id)
    except ReplayError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    events = list(session.events)
    return {"events": events[since:], "total": len(events)}
