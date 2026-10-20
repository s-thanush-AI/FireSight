from enum import StrEnum


class Provenance(StrEnum):
    """Where a piece of evidence came from. Never mix these in evaluation."""

    REAL = "real"
    PREDICTED = "predicted"
    SIMULATED = "simulated"
    HEURISTIC = "heuristic"
    MANUAL = "manual"


class IncidentStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"
    ACKNOWLEDGED = "acknowledged"


class SeverityTier(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CalibrationStatus(StrEnum):
    CALIBRATED = "calibrated"
    APPROXIMATE = "approximate"
    UNCALIBRATED = "uncalibrated"
    SIMULATED = "simulated"


class EvidenceType(StrEnum):
    REAL_PAIRED = "real_paired"
    REAL_UNPAIRED = "real_unpaired"
    SIMULATED_SECOND_CAMERA = "simulated_second_camera"


class GeometryQuality(StrEnum):
    STRONG = "strong"
    ACCEPTABLE = "acceptable"
    WEAK = "weak"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


class ReplayStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"
    ERROR = "error"


class VlmAssessment(StrEnum):
    LIKELY_SMOKE = "likely_smoke"
    LIKELY_NON_SMOKE = "likely_non_smoke"
    UNCERTAIN = "uncertain"


class MetricValidity(StrEnum):
    VALID = "valid"
    UNAVAILABLE = "unavailable"
