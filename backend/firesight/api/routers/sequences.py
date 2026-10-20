import json

from fastapi import APIRouter, HTTPException

from ...services.context import SequenceRegistrationError, get_context
from ..schemas import SequenceCreateRequest, SequenceCreateResponse

router = APIRouter(tags=["sequences"])


_REASON_STATUS = {
    "duplicate": 409,
    "bad_camera": 404,
    "bad_path": 422,
    "empty": 422,
}


def _row_to_seq(row: dict) -> dict:
    meta = {}
    try:
        meta = json.loads(row.get("manifest_json") or "{}")
    except json.JSONDecodeError:
        pass
    return {
        "id": row["id"],
        "name": row["name"],
        "dataset": row["dataset"],
        "dataset_provenance": row["dataset_provenance"],
        "frame_count": row["frame_count"],
        "image_width": row["image_width"],
        "image_height": row["image_height"],
        "start_ts": row["start_ts"],
        "end_ts": row["end_ts"],
        "provenance": row["provenance"],
        "camera_id": meta.get("camera_id"),
        "synthetic": meta.get("synthetic", False),
        "root_path": row["root_path"],
    }


@router.get("/sequences")
def list_sequences() -> dict:
    ctx = get_context()
    rows = ctx.db.query("SELECT * FROM sequences ORDER BY created_at")
    return {"items": [_row_to_seq(r) for r in rows], "total": len(rows)}


@router.get("/sequences/{sequence_id}")
def get_sequence(sequence_id: str) -> dict:
    ctx = get_context()
    row = ctx.db.query_one("SELECT * FROM sequences WHERE id=?", (sequence_id,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown sequence: {sequence_id}")
    seq = _row_to_seq(row)
    try:
        from ...replay.discovery import discover_frames

        frames = discover_frames(row["root_path"])
        seq["first_frames"] = [
            {
                "index": f.index,
                "filename": f.filename,
                "timestamp": f.timestamp.isoformat() if f.timestamp else None,
                "event_offset_s": f.event_offset_s,
            }
            for f in frames[:5]
        ]
        seq["last_frames"] = [
            {"index": f.index, "filename": f.filename} for f in frames[-3:]
        ]
    except Exception as e:
        seq["discovery_error"] = str(e)
    return seq


@router.post("/sequences", response_model=SequenceCreateResponse, status_code=201)
def create_sequence(payload: SequenceCreateRequest) -> SequenceCreateResponse:
    """Register a directory of JPG/JPEG/PNG frames (under the data root) as a REAL sequence."""
    ctx = get_context()
    try:
        result = ctx.register_sequence(
            sequence_id=payload.id,
            root_path=payload.root_path,
            camera_id=payload.camera_id,
            name=payload.name,
        )
    except SequenceRegistrationError as e:
        raise HTTPException(
            status_code=_REASON_STATUS.get(e.reason, 422), detail=str(e)
        ) from e
    return SequenceCreateResponse(**result)
