from __future__ import annotations

import asyncio
import contextlib
import json

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from ...services.context import get_context

router = APIRouter(tags=["alerts"])


@router.get("/alerts/stats")
def alert_stats() -> dict:
    ctx = get_context()
    return {
        **ctx.alerts.stats(),
        "notice": (
            "Alerts are experimental detector outputs, not confirmed incidents. "
            "Each alert keeps its detector identity and evidence."
        ),
    }


@router.get("/alerts")
def list_alerts(
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
) -> dict:
    ctx = get_context()
    items = ctx.alerts.list(limit=limit, status=status, source_type=source_type)
    return {
        "alerts": items,
        "count": len(items),
        "notice": (
            "Experimental alerts with detector provenance. Review evidence before acting. "
            "This is not an operational warning service."
        ),
    }


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: str) -> dict:
    ctx = get_context()
    alert = ctx.alerts.get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str) -> dict:
    ctx = get_context()
    alert = ctx.alerts.acknowledge(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str) -> dict:
    ctx = get_context()
    alert = ctx.alerts.resolve(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.get("/alerts/{alert_id}/evidence")
def alert_evidence(alert_id: str):
    ctx = get_context()
    alert = ctx.alerts.get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not alert.get("evidence_path"):
        raise HTTPException(status_code=404, detail="No evidence image for this alert")
    path = ctx.alerts.evidence_path(alert["evidence_path"])
    if path is None:
        raise HTTPException(status_code=404, detail="Evidence image is no longer present")
    return FileResponse(path, media_type="image/jpeg")


@router.websocket("/ws/alerts")
async def alerts_stream(ws: WebSocket) -> None:
    await ws.accept()
    ctx = get_context()
    loop = asyncio.get_running_loop()
    ctx.alerts.add_ws(ws, loop)
    try:
        await ws.send_text(
            json.dumps(
                {
                    "type": "ready",
                    "data": {"stats": ctx.alerts.stats(), "experimental": True},
                }
            )
        )
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ctx.alerts.remove_ws(ws)
        with contextlib.suppress(Exception):
            await ws.close()
