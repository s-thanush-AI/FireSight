from fastapi import APIRouter, HTTPException

from ...api.schemas import CameraModel
from ...models import CameraConfig
from ...services.context import get_context

router = APIRouter(tags=["cameras"])


@router.get("/cameras")
def list_cameras() -> dict:
    ctx = get_context()
    cams = ctx.cameras.list()
    return {
        "items": [c.model_dump() for c in cams],
        "total": len(cams),
        "notice": (
            "Cameras with calibration_status 'simulated' are demo fixtures, not real devices."
        ),
    }


def _validate_calibration(cam: CameraConfig) -> None:
    if cam.calibration_status.value == "calibrated" and not cam.calibration_source:
        raise HTTPException(
            status_code=422,
            detail="calibration_source is required when calibration_status is 'calibrated'",
        )


@router.post("/cameras", status_code=201)
def create_camera(body: CameraModel) -> dict:
    ctx = get_context()
    if ctx.cameras.get(body.id) is not None:
        raise HTTPException(status_code=409, detail=f"Camera already exists: {body.id}")
    cam = CameraConfig(**body.model_dump())
    _validate_calibration(cam)
    ctx.cameras.upsert(cam)
    return ctx.cameras.get(body.id).model_dump()  # type: ignore[union-attr]


@router.put("/cameras/{camera_id}")
def update_camera(camera_id: str, body: CameraModel) -> dict:
    ctx = get_context()
    if body.id != camera_id:
        raise HTTPException(status_code=422, detail="Camera id in path and body must match")
    if ctx.cameras.get(camera_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown camera: {camera_id}")
    cam = CameraConfig(**body.model_dump())
    _validate_calibration(cam)
    ctx.cameras.upsert(cam)
    return ctx.cameras.get(camera_id).model_dump()  # type: ignore[union-attr]


@router.get("/cameras/{camera_id}")
def get_camera(camera_id: str) -> dict:
    ctx = get_context()
    cam = ctx.cameras.get(camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail=f"Unknown camera: {camera_id}")
    return cam.model_dump()
