from fastapi import APIRouter, HTTPException

from ... import __version__
from ...api.schemas import (
    ConfigResponse,
    ConfigUpdateRequest,
    DetectorInfo,
    HealthResponse,
    StatusResponse,
    VlmInfo,
)
from ...services.context import AppContext, get_context
from ...services.incidents import counts_by_status

router = APIRouter(tags=["health", "config", "status"])


def _detector_info(ctx: AppContext) -> DetectorInfo:
    s = ctx.settings
    d = ctx.detector.metadata()
    return DetectorInfo(
        name=d["name"],
        version=str(d["version"]),
        available=bool(d["available"]),
        unavailable_reason=d["unavailable_reason"],
        provenance=d["provenance"],
        kind=s.detector.kind,
        confidence_threshold=s.detector.confidence_threshold,
        iou_threshold=s.detector.iou_threshold,
        image_size=s.detector.image_size,
        device=s.device,
        weights_path=str(s.model_path) if s.model_path else None,
    )


def _vlm_info(ctx: AppContext) -> VlmInfo:
    return VlmInfo(
        configured=ctx.settings.vlm.enabled,
        provider=ctx.vlm.name,
        model=ctx.settings.vlm.model,
        base_url=ctx.settings.vlm.base_url,
        api_key_present=bool(ctx.settings.vlm.api_key),
    )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    ctx = get_context()
    return HealthResponse(status="ok", version=__version__, mode=ctx.settings.mode)


@router.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    ctx = get_context()
    rm = ctx.replay_manager
    active = sum(1 for s in rm.sessions.values() if s.status.value == "running") if rm else 0
    return StatusResponse(
        mode=ctx.settings.mode,
        version=__version__,
        demo_banner=ctx.settings.mode == "demo",
        detector=_detector_info(ctx),
        vlm=_vlm_info(ctx),
        active_replays=active,
        incidents_by_status=counts_by_status(ctx.db),
        cameras=len(ctx.cameras.list()),
        sequences=ctx.db.query_one("SELECT COUNT(*) AS n FROM sequences")["n"],
        simulated_data_notice=(
            "This instance runs in DEMO mode with clearly labeled simulated data."
            if ctx.settings.mode == "demo"
            else "Real-data mode: only user-supplied data and configured models are used."
        ),
    )


@router.get("/config", response_model=ConfigResponse)
def get_config() -> ConfigResponse:
    ctx = get_context()
    return ConfigResponse(
        settings=ctx.settings.redacted_dict(),
        overrides=ctx.overrides,
        configurable_keys=sorted(AppContext.OVERRIDE_KEYS),
    )


@router.put("/config", response_model=ConfigResponse)
def put_config(body: ConfigUpdateRequest) -> ConfigResponse:
    ctx = get_context()
    try:
        ctx.set_overrides(body.values)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return ConfigResponse(
        settings=ctx.settings.redacted_dict(),
        overrides=ctx.overrides,
        configurable_keys=sorted(AppContext.OVERRIDE_KEYS),
    )
