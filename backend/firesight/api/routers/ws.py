from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...services.context import get_context
from ...services.replay_manager import ReplayManager

log = logging.getLogger(__name__)

router = APIRouter(tags=["replays", "ws"])


@router.websocket("/ws/replays/{replay_id}")
async def replay_stream(ws: WebSocket, replay_id: str) -> None:
    await ws.accept()
    ctx = get_context()
    rm = ctx.replay_manager
    if rm is None:
        await ws.send_text(json.dumps({"type": "error", "detail": "Replay manager not running"}))
        await ws.close()
        return
    try:
        session = rm.get(replay_id)
    except Exception:
        await ws.send_text(json.dumps({"type": "error", "detail": f"Unknown replay {replay_id}"}))
        await ws.close()
        return

    loop = asyncio.get_running_loop()
    session.add_ws(ws, loop)
    try:
        await ws.send_text(json.dumps({"type": "status", "data": session.to_dict()}))
        if session.current_meta is not None:
            await ws.send_text(
                json.dumps(
                    {
                        "type": "frame",
                        "data": {
                            "replay_id": replay_id,
                            "frame": session.current_meta,
                            "image_jpeg_base64": session.current_jpeg_b64,
                            "detections": session.last_detections,
                        },
                    }
                )
            )
        while True:
            msg = await ws.receive_text()
            await _handle_command(ws, rm, replay_id, msg)
    except WebSocketDisconnect:
        pass
    finally:
        session.remove_ws(ws)


async def _handle_command(ws: WebSocket, rm: ReplayManager, replay_id: str, msg: str) -> None:
    try:
        payload = json.loads(msg)
        action = payload.get("action")
    except json.JSONDecodeError:
        action = msg
    try:
        session = rm.get(replay_id)
        if action == "pause":
            session.pause()
        elif action == "resume":
            session.resume()
        elif action == "reset":
            session.reset()
        elif action == "step":
            n = int(payload.get("n", 1))
            session.step(max(1, min(n, 100)))
        else:
            await ws.send_text(json.dumps({"type": "error", "detail": f"Unknown action: {action}"}))
            return
        await ws.send_text(json.dumps({"type": "status", "data": session.to_dict()}))
    except Exception as e:
        log.debug("WS command failed: %s", e)
        with contextlib.suppress(Exception):
            await ws.send_text(json.dumps({"type": "error", "detail": str(e)}))
