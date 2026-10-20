from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from ..config import Settings
from ..models import Detection, FrameRef


class DetectorUnavailableError(RuntimeError):
    """Raised when a configured detector cannot run (missing weights/deps/device)."""


class BaseDetector(ABC):
    """Detector interface. Implementations: classic (demo), YOLO (real), mock (tests)."""

    name: str = "base"
    version: str = "0.0.0"
    provenance = None  # set by implementations

    @property
    @abstractmethod
    def available(self) -> bool: ...

    @property
    def unavailable_reason(self) -> str | None:
        return None

    @abstractmethod
    def detect(self, image: np.ndarray, frame: FrameRef, camera_id: str | None = None) -> list[Detection]:
        """Run inference on one BGR image and return schema-stable detections."""

    def metadata(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "provenance": self.provenance.value if self.provenance else None,
        }


def build_detector(settings: Settings) -> BaseDetector:
    """Build the detector configured for the current mode.

    In real mode with a YOLO weights path configured, returns a YoloDetector.
    Never silently substitutes a simulated detector in real mode.
    """
    from .classic import ClassicSmokeDetector
    from .yolo import YoloDetector

    if settings.detector.kind == "yolo" or (settings.mode == "real" and settings.model_path):
        weights = settings.model_weights_path()
        return YoloDetector(
            weights_path=weights,
            device=settings.device,
            confidence_threshold=settings.detector.confidence_threshold,
            iou_threshold=settings.detector.iou_threshold,
            image_size=settings.detector.image_size,
        )
    return ClassicSmokeDetector(
        confidence_threshold=settings.detector.confidence_threshold,
    )
