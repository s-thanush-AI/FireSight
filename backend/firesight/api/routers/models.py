from fastapi import APIRouter

from ...services.context import get_context

router = APIRouter(tags=["models"])


@router.get("/models")
def list_models() -> dict:
    ctx = get_context()
    s = ctx.settings
    det = ctx.detector.metadata()
    return {
        "detectors": [
            {
                "name": det["name"],
                "version": det["version"],
                "available": det["available"],
                "unavailable_reason": det["unavailable_reason"],
                "provenance": det["provenance"],
                "kind": s.detector.kind,
                "confidence_threshold": s.detector.confidence_threshold,
                "iou_threshold": s.detector.iou_threshold,
                "image_size": s.detector.image_size,
                "device": s.device,
                "weights_path": str(s.model_path) if s.model_path else None,
                "active": True,
            },
            {
                "name": "yolo",
                "version": None,
                "available": False if s.mode == "demo" and not s.model_path else None,
                "unavailable_reason": (
                    None if s.detector.kind == "yolo" else
                    "Not selected. Set FIRESIGHT_DETECTOR_KIND=yolo and FIRESIGHT_MODEL_PATH "
                    "to local smoke-detection weights (uv sync --extra yolo required)."
                ),
                "provenance": "predicted",
                "kind": "yolo",
                "active": s.detector.kind == "yolo",
            },
        ],
        "vlm": {
            "provider": ctx.vlm.name,
            "configured": s.vlm.enabled,
            "model": s.vlm.model,
            "base_url": s.vlm.base_url,
            "api_key_present": bool(s.vlm.api_key),
            "note": (
                "VLM calls are only made on explicit user request per incident. "
                "Keys are environment-only and never returned by the API."
            ),
        },
        "training": {
            "available": True,
            "command": "firesight train --config training/smoke_yolo.yaml",
            "note": "Training is never started automatically; it requires an explicit user action.",
        },
    }
