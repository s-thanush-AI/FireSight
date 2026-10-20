from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .enums import (
    CalibrationStatus,
    EvidenceType,
    GeometryQuality,
    IncidentStatus,
    MetricValidity,
    Provenance,
    SeverityTier,
    VlmAssessment,
)


class BBox(BaseModel):
    """Axis-aligned box in pixel coordinates."""

    x1: float
    y1: float
    x2: float
    y2: float

    @field_validator("x2")
    @classmethod
    def _x2_ge_x1(cls, v: float, info) -> float:
        x1 = info.data.get("x1")
        if x1 is not None and v < x1:
            raise ValueError("x2 must be >= x1")
        return v

    @field_validator("y2")
    @classmethod
    def _y2_ge_y1(cls, v: float, info) -> float:
        y1 = info.data.get("y1")
        if y1 is not None and v < y1:
            raise ValueError("y2 must be >= y1")
        return v

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return self.width * self.height

    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def bottom_center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, self.y2)

    def iou(self, other: BBox) -> float:
        ix1 = max(self.x1, other.x1)
        iy1 = max(self.y1, other.y1)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        inter = (ix2 - ix1) * (iy2 - iy1)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def clip(self, width: float, height: float) -> BBox:
        return BBox(
            x1=max(0.0, min(self.x1, width)),
            y1=max(0.0, min(self.y1, height)),
            x2=max(0.0, min(self.x2, width)),
            y2=max(0.0, min(self.y2, height)),
        )


class FrameRef(BaseModel):
    sequence_id: str
    index: int
    filename: str
    timestamp: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    rel_path: str | None = None


class Detection(BaseModel):
    frame: FrameRef
    camera_id: str | None = None
    class_name: str = "smoke"
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BBox
    model_name: str
    model_version: str | None = None
    provenance: Provenance


class CameraConfig(BaseModel):
    id: str
    name: str
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    height_m: float = Field(ge=0.0, le=1000.0)
    heading_deg: float = Field(ge=0.0, lt=360.0)
    hfov_deg: float = Field(gt=0.0, le=180.0)
    image_width: int = Field(ge=1, le=20000)
    image_height: int = Field(ge=1, le=20000)
    calibration_status: CalibrationStatus
    calibration_source: str | None = None
    calibration_uncertainty_deg: float | None = Field(default=None, ge=0.0, le=90.0)
    provenance: Provenance
    notes: str | None = None


class BearingObservation(BaseModel):
    """A single camera's bearing estimate toward a smoke proxy point."""

    camera_id: str
    bearing_deg: float = Field(ge=0.0, lt=360.0)
    timestamp: str | None = None
    pixel_x: float
    pixel_y: float
    proxy_kind: str = "bottom_center"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_type: EvidenceType
    provenance: Provenance
    camera: CameraConfig | None = None


class Distances(BaseModel):
    per_camera_m: dict[str, float] = Field(default_factory=dict)


class TriangulationResult(BaseModel):
    quality: GeometryQuality
    latitude: float | None = None
    longitude: float | None = None
    uncertainty_m: float | None = None
    ray_separation_deg: float | None = None
    intersection_angle_deg: float | None = None
    fit_residual_m: float | None = None
    distances_per_camera_m: dict[str, float] = Field(default_factory=dict)
    method: str = "least_squares_ray_intersection"
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    provenance: Provenance = Provenance.HEURISTIC


class TrackSummary(BaseModel):
    track_id: str
    camera_id: str | None
    positive_count: int
    state: str
    first_ts: str | None
    last_ts: str | None


class TemporalAlert(BaseModel):
    """Output of the temporal verification layer for one camera stream."""

    track_id: str
    camera_id: str | None
    confirmed: bool
    positive_count: int
    expected_count: int
    persistence_ratio: float
    mean_confidence: float
    first_ts: str | None
    last_ts: str | None
    latest_bbox: BBox | None = None
    reason: str
    provenance: Provenance = Provenance.HEURISTIC


class VlmDecision(BaseModel):
    provider: str
    model_id: str | None
    status: str
    assessment: VlmAssessment | None = None
    visual_evidence: str | None = None
    alternative_explanations: str | None = None
    limitations: str | None = None
    recommended_next_action: str | None = None
    model_confidence: float | None = None
    error: str | None = None
    duration_ms: int | None = None
    request_time: str
    provenance: Provenance


class MetricResult(BaseModel):
    name: str
    value: float | None
    unit: str = ""
    sample_count: int | None = None
    data_source: str
    ground_truth_available: bool
    validity: MetricValidity
    limitation: str | None = None
    provenance: Provenance


class Incident(BaseModel):
    id: str
    status: IncidentStatus
    severity_tier: SeverityTier
    title: str
    summary: str | None = None
    provenance: Provenance
    mode: str
    latitude: float | None = None
    longitude: float | None = None
    location_uncertainty_m: float | None = None
    location_method: str | None = None
    calibration_status: str | None = None
    geometry_quality: str | None = None
    ray_separation_deg: float | None = None
    intersection_angle_deg: float | None = None
    fit_residual_m: float | None = None
    ground_truth_lat: float | None = None
    ground_truth_lon: float | None = None
    ground_truth_available: bool = False
    vlm_assessment: str | None = None
    vlm_model: str | None = None
    source_dataset: str | None = None
    first_seen_ts: str | None = None
    last_seen_ts: str | None = None
    created_at: str
    updated_at: str
