from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..enums import (
    CalibrationStatus,
    GeometryQuality,
    IncidentStatus,
    Provenance,
    ReplayStatus,
    SeverityTier,
    VlmAssessment,
)


class HealthResponse(BaseModel):
    status: str
    version: str
    mode: str


class DetectorInfo(BaseModel):
    name: str
    version: str
    available: bool
    unavailable_reason: str | None = None
    provenance: str | None = None
    kind: str
    confidence_threshold: float
    iou_threshold: float
    image_size: int
    device: str
    weights_path: str | None = None


class VlmInfo(BaseModel):
    configured: bool
    provider: str
    model: str | None = None
    base_url: str | None = None
    api_key_present: bool = False


class StatusResponse(BaseModel):
    mode: str
    version: str
    demo_banner: bool
    detector: DetectorInfo
    vlm: VlmInfo
    active_replays: int
    incidents_by_status: dict[str, int]
    cameras: int
    sequences: int
    simulated_data_notice: str


class ConfigResponse(BaseModel):
    settings: dict
    overrides: dict
    configurable_keys: list[str]


class ConfigUpdateRequest(BaseModel):
    values: dict[str, object] = Field(default_factory=dict)


class CameraModel(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=128)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    height_m: float = Field(ge=0, le=1000)
    heading_deg: float = Field(ge=0, lt=360)
    hfov_deg: float = Field(gt=0, le=180)
    image_width: int = Field(ge=1, le=20000)
    image_height: int = Field(ge=1, le=20000)
    calibration_status: CalibrationStatus
    calibration_source: str | None = None
    calibration_uncertainty_deg: float | None = Field(default=None, ge=0, le=90)
    provenance: Provenance = Provenance.MANUAL
    notes: str | None = None


class SequenceInfoResponse(BaseModel):
    id: str
    name: str
    dataset: str
    dataset_provenance: str
    frame_count: int
    image_width: int | None
    image_height: int | None
    start_ts: str | None
    end_ts: str | None
    provenance: str
    camera_id: str | None = None


class SequenceCreateRequest(BaseModel):
    """Register a directory of image frames (relative to the data root) as a sequence."""

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    root_path: str = Field(min_length=1, max_length=500)
    name: str | None = Field(default=None, max_length=128)
    camera_id: str | None = Field(default=None, max_length=64)
    provenance: Literal["real"] = "real"


class SequenceCreateResponse(BaseModel):
    id: str
    name: str
    root_path: str
    frame_count: int
    image_width: int | None
    image_height: int | None
    start_ts: str | None
    end_ts: str | None
    timestamps_available: bool
    camera_id: str | None
    provenance: str
    synthetic: bool
    warnings: list[str] = Field(default_factory=list)


class ReplayCreateRequest(BaseModel):
    sequence_id: str
    camera_id: str | None = None
    speed: float | None = Field(default=None, gt=0, le=60)


class ReplayStatusResponse(BaseModel):
    id: str
    sequence_id: str
    camera_id: str | None
    status: ReplayStatus
    speed: float
    frame_index: int
    frame_count: int
    frames_emitted: int
    detections_total: int
    alerts_total: int
    mode: str
    provenance: str
    error: str | None = None
    created_at: str | None = None


class ReplayFrameResponse(BaseModel):
    replay_id: str
    frame: dict | None = None
    image_jpeg_base64: str | None = None
    original_jpeg_base64: str | None = None
    detections: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)


class IncidentSummary(BaseModel):
    id: str
    status: IncidentStatus
    severity_tier: SeverityTier
    title: str
    summary: str | None
    provenance: Provenance
    mode: str
    latitude: float | None
    longitude: float | None
    location_uncertainty_m: float | None
    geometry_quality: GeometryQuality | None
    vlm_assessment: VlmAssessment | None
    first_seen_ts: str | None
    created_at: str


class IncidentPatchRequest(BaseModel):
    action: str = Field(pattern=r"^(acknowledge|dismiss|reopen|mark_reviewed)$")
    reason: str | None = Field(default=None, max_length=1000)


class DatasetInspectRequest(BaseModel):
    path: str = Field(max_length=500)
    name: str | None = Field(default=None, max_length=128)


class InferenceRequest(BaseModel):
    sequence_id: str
    frame_index: int = Field(ge=0)
    camera_id: str | None = None


class TriangulationResponse(BaseModel):
    quality: GeometryQuality
    latitude: float | None
    longitude: float | None
    uncertainty_m: float | None
    ray_separation_deg: float | None
    intersection_angle_deg: float | None
    fit_residual_m: float | None
    distances_per_camera_m: dict[str, float]
    assumptions: list[str]
    limitations: list[str]
    provenance: Provenance


class GeometryLayerResponse(BaseModel):
    cameras: list[CameraModel]
    observations: list[dict]
    triangulations: list[dict]
    notice: str


class VerificationResponse(BaseModel):
    incident_id: str
    provider: str
    model_id: str | None
    status: str
    assessment: VlmAssessment | None
    visual_evidence: str | None
    alternative_explanations: str | None
    limitations: str | None
    recommended_next_action: str | None
    model_confidence: float | None
    error: str | None
    provenance: Provenance
    request_time: str
    duration_ms: int | None


class EvalRunCreateRequest(BaseModel):
    name: str = Field(default="Demo fixture evaluation", max_length=200)
    kind: str = Field(default="demo_fixture", pattern=r"^demo_fixture$")


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None


class LiveSourceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["rtsp", "file"]
    url: str | None = Field(default=None, max_length=2000)
    path: str | None = Field(default=None, max_length=500)
    camera_id: str | None = Field(default=None, max_length=64)
    sample_fps: float = Field(default=1.0, ge=0.1, le=10.0)
    threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    loop: bool = True
    min_consecutive: int = Field(default=3, ge=1, le=100)


class VideoAnalysisRequest(BaseModel):
    sample_every_s: float = Field(default=5.0, ge=0.25, le=600.0)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    camera_id: str | None = None
    max_samples: int = Field(default=120, ge=1, le=240)
    min_consecutive: int = Field(default=2, ge=1, le=100)


class AlertStatusResponse(BaseModel):
    id: str
    status: str
    acknowledged_at: str | None = None
    resolved_at: str | None = None
