import base64

import cv2
from fastapi import APIRouter, HTTPException

from ...api.schemas import InferenceRequest
from ...detection.base import DetectorUnavailableError
from ...detection.drawing import draw_detections
from ...models import FrameRef
from ...replay.discovery import discover_frames, load_frame
from ...services.context import get_context

router = APIRouter(tags=["inference"])


@router.post("/inference")
def run_inference(body: InferenceRequest) -> dict:
    """Run the configured detector on a single frame of a registered sequence."""
    ctx = get_context()
    seq = ctx.db.query_one("SELECT * FROM sequences WHERE id=?", (body.sequence_id,))
    if seq is None:
        raise HTTPException(status_code=404, detail=f"Unknown sequence: {body.sequence_id}")
    if not ctx.detector.available:
        raise HTTPException(
            status_code=503,
            detail=ctx.detector.unavailable_reason or "Detector unavailable",
        )
    try:
        frames = discover_frames(seq["root_path"])
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Sequence unreadable: {e}") from e
    if body.frame_index >= len(frames):
        raise HTTPException(
            status_code=422,
            detail=f"frame_index {body.frame_index} out of range (0..{len(frames)-1})",
        )
    ff = frames[body.frame_index]
    try:
        image, _ = load_frame(ff)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    ref = FrameRef(
        sequence_id=body.sequence_id,
        index=ff.index,
        filename=ff.filename,
        timestamp=ff.timestamp.isoformat() if ff.timestamp else None,
        image_width=image.shape[1],
        image_height=image.shape[0],
    )
    try:
        detections = ctx.detector.detect(image, ref, body.camera_id)
    except DetectorUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    watermark = "SIMULATED DEMO DATA" if seq["provenance"] == "simulated" else None
    annotated = draw_detections(
        image, detections, watermark=watermark,
        metadata_lines=[f"{ff.filename}  model={ctx.detector.name}:{ctx.detector.version}"],
    )
    ok, enc = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return {
        "sequence_id": body.sequence_id,
        "frame_index": ff.index,
        "filename": ff.filename,
        "detections": [d.model_dump() for d in detections],
        "detector": ctx.detector.metadata(),
        "annotated_jpeg_base64": base64.b64encode(enc.tobytes()).decode("ascii") if ok else None,
        "provenance": seq["provenance"],
        "notice": (
            "Detection output is a model prediction (provenance 'predicted'), "
            "not confirmed fire evidence."
        ),
    }
