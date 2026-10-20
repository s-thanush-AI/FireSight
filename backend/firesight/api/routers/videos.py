from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from ...services.context import get_context
from ...services.video_analysis import VideoAnalysisError
from ...services.video_library import VideoError
from ..schemas import VideoAnalysisRequest

router = APIRouter(tags=["videos"])


@router.get("/videos")
def list_videos() -> dict:
    ctx = get_context()
    items = ctx.videos.list()
    return {
        "videos": items,
        "count": len(items),
        "notice": (
            "Local video files only. Time-lapse clips are not continuous CCTV; "
            "video time is not a validated real capture timestamp."
        ),
    }


@router.get("/videos/{video_id}")
def get_video(video_id: str) -> dict:
    ctx = get_context()
    try:
        return ctx.videos.get(video_id)
    except VideoError as e:
        raise HTTPException(status_code=404 if e.reason == "not_found" else 400, detail=str(e)) from e


@router.get("/videos/{video_id}/stream")
def stream_video(video_id: str, request: Request):
    ctx = get_context()
    try:
        path = ctx.videos.path_for(video_id)
    except VideoError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    size = path.stat().st_size
    try:
        start, end, partial = ctx.videos.parse_range(request.headers.get("range"), size)
    except VideoError as e:
        raise HTTPException(
            status_code=416,
            detail=str(e),
            headers={"Content-Range": f"bytes */{size}"},
        ) from e
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Cache-Control": "no-store",
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    media_type = "video/mp4" if path.suffix.lower() == ".mp4" else "application/octet-stream"
    return StreamingResponse(
        ctx.videos.iter_bytes(path, start, end),
        status_code=206 if partial else 200,
        media_type=media_type,
        headers=headers,
    )


@router.post("/videos/{video_id}/analyze")
def analyze_video(video_id: str, req: VideoAnalysisRequest) -> dict:
    ctx = get_context()
    if req.camera_id and ctx.cameras.get(req.camera_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown camera: {req.camera_id}")
    try:
        return ctx.video_analysis.analyze(
            video_id,
            sample_every_s=req.sample_every_s,
            threshold=req.threshold,
            camera_id=req.camera_id,
            max_samples=req.max_samples,
            min_consecutive=req.min_consecutive,
        )
    except VideoError as e:
        raise HTTPException(status_code=404 if e.reason == "not_found" else 400, detail=str(e)) from e
    except VideoAnalysisError as e:
        status = 404 if e.reason == "not_found" else 400
        raise HTTPException(status_code=status, detail=str(e)) from e


@router.get("/videos/{video_id}/analyses")
def list_analyses(video_id: str, limit: int = Query(default=20, ge=1, le=100)) -> dict:
    ctx = get_context()
    try:
        ctx.videos.get(video_id)
    except VideoError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    rows = ctx.db.query(
        """SELECT id, video_id, created_at, sample_every_s, detector_name,
                  detector_version, frames_sampled, detections_total, output_dir
           FROM analysis_runs WHERE video_id=? ORDER BY created_at DESC LIMIT ?""",
        (video_id, limit),
    )
    for row in rows:
        row["report_url"] = f"/api/v1/videos/{video_id}/analyses/{row['id']}/report"
        row["csv_url"] = f"/api/v1/videos/{video_id}/analyses/{row['id']}/detections.csv"
    return {"analyses": rows, "count": len(rows)}


def _run_dir(video_id: str, run_id: str) -> Path:
    ctx = get_context()
    row = ctx.db.query_one(
        "SELECT output_dir FROM analysis_runs WHERE id=? AND video_id=?", (run_id, video_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown analysis run")
    root = ctx.settings.data_root / "analysis" / video_id
    candidate = (ctx.settings.data_root / row["output_dir"]).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown analysis run") from None
    if not candidate.is_dir():
        raise HTTPException(status_code=404, detail="Analysis output is no longer present")
    return candidate


@router.get("/videos/{video_id}/analyses/{run_id}/report")
def analysis_report(video_id: str, run_id: str):
    path = _run_dir(video_id, run_id) / "report.md"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(path, media_type="text/markdown", filename=f"{run_id}-report.md")


@router.get("/videos/{video_id}/analyses/{run_id}/detections.csv")
def analysis_csv(video_id: str, run_id: str):
    path = _run_dir(video_id, run_id) / "detections.csv"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CSV not found")
    return FileResponse(path, media_type="text/csv", filename=f"{run_id}-detections.csv")


@router.get("/videos/{video_id}/analyses/{run_id}/summary")
def analysis_summary(video_id: str, run_id: str) -> dict:
    path = _run_dir(video_id, run_id) / "summary.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Summary not found")
    return json.loads(path.read_text())


@router.get("/videos/{video_id}/analyses/{run_id}/image/{kind}/{name}")
def analysis_image(video_id: str, run_id: str, kind: str, name: str):
    if kind not in ("original", "annotated") or "/" in name or "\\" in name:
        raise HTTPException(status_code=404, detail="Image not found")
    path = (_run_dir(video_id, run_id) / kind / name).resolve()
    try:
        path.relative_to(_run_dir(video_id, run_id).resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Image not found") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, media_type="image/jpeg")
