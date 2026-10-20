from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from ..enums import Provenance
from ..models import BBox, Detection, FrameRef
from .base import BaseDetector, DetectorUnavailableError

log = logging.getLogger(__name__)


def is_ultralytics_available() -> bool:
    try:
        import ultralytics  # noqa: F401

        return True
    except Exception:
        return False


def select_device(preference: str = "auto") -> str:
    """Resolve the requested device to one that actually exists.

    Raises DetectorUnavailableError when an explicitly requested device is
    unavailable — never silently substitutes another device for 'cuda'.
    """
    if preference == "auto":
        try:
            import torch

            if torch.backends.mps.is_available():
                return "mps"
            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
        return "cpu"
    if preference == "cpu":
        return "cpu"
    try:
        import torch
    except Exception as e:
        raise DetectorUnavailableError(
            f"Device '{preference}' requested but PyTorch is not installed. "
            "Install extras with: uv sync --extra yolo"
        ) from e
    if preference == "mps":
        if torch.backends.mps.is_available():
            return "mps"
        raise DetectorUnavailableError("MPS requested but not available on this machine")
    if preference == "cuda":
        if torch.cuda.is_available():
            return "cuda"
        raise DetectorUnavailableError("CUDA requested but no CUDA device is available")
    raise DetectorUnavailableError(f"Unknown device preference: {preference}")


class YoloDetector(BaseDetector):
    """Ultralytics YOLO adapter with a configurable custom smoke-weights path.

    Weights are NEVER downloaded automatically. If ultralytics or the weights
    file is missing, `available` is False and callers must surface setup
    guidance instead of substituting fake predictions.
    """

    name = "yolo"
    version = "0.0.0"
    provenance = Provenance.PREDICTED

    def __init__(
        self,
        weights_path: Path | None,
        device: str = "auto",
        confidence_threshold: float = 0.25,
        iou_threshold: float = 0.45,
        image_size: int = 640,
        class_name: str = "smoke",
    ):
        self.weights_path = weights_path
        self.device_pref = device
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.image_size = image_size
        self.class_name = class_name
        self._model = None
        self._device: str | None = None
        self._load_error: str | None = None

    @property
    def available(self) -> bool:
        return self._ensure_loaded() is not None

    @property
    def unavailable_reason(self) -> str | None:
        if self._ensure_loaded() is not None:
            return None
        return self._load_error

    def _ensure_loaded(self):
        if self._model is not None:
            return self._model
        if self._load_error is not None:
            return None
        if not is_ultralytics_available():
            self._load_error = (
                "Ultralytics/PyTorch not installed. Install with: uv sync --extra yolo"
            )
            return None
        if self.weights_path is None or not self.weights_path.exists():
            self._load_error = (
                "No YOLO weights file found. Set FIRESIGHT_MODEL_PATH to a local .pt file "
                "trained for smoke detection; weights are never downloaded automatically."
            )
            return None
        try:
            from ultralytics import YOLO

            self._device = select_device(self.device_pref)
            model = YOLO(str(self.weights_path))
            names = model.names or {}
            self._class_ids = {
                int(k) for k, v in names.items() if str(v).lower() == self.class_name.lower()
            }
            if not self._class_ids:
                self._class_ids = set(names.keys())
                log.warning(
                    "Weights %s have no class named %r; classes present: %s",
                    self.weights_path, self.class_name, names,
                )
            else:
                # restrict to the configured class only
                pass
            self.version = getattr(model, "version", None) or "unknown"
            self._model = model
            return model
        except DetectorUnavailableError as e:
            self._load_error = str(e)
            return None
        except Exception as e:  # pragma: no cover - depends on local weights
            self._load_error = f"Failed to load YOLO weights: {e}"
            return None

    def detect(self, image: np.ndarray, frame: FrameRef, camera_id: str | None = None) -> list[Detection]:
        model = self._ensure_loaded()
        if model is None:
            raise DetectorUnavailableError(self._load_error or "YOLO detector unavailable")
        results = model.predict(
            source=image,
            conf=self.confidence_threshold,
            iou=self.iou_threshold,
            imgsz=self.image_size,
            device=self._device,
            verbose=False,
        )
        detections: list[Detection] = []
        for r in results:
            boxes = getattr(r, "boxes", None)
            if boxes is None or len(boxes) == 0:
                continue
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            clss = boxes.cls.cpu().numpy().astype(int)
            for (x1, y1, x2, y2), conf, cls in zip(xyxy, confs, clss, strict=False):
                if self._class_ids and int(cls) not in self._class_ids:
                    continue
                label = (model.names or {}).get(int(cls), str(cls))
                detections.append(
                    Detection(
                        frame=frame,
                        camera_id=camera_id,
                        class_name=str(label),
                        confidence=round(float(conf), 4),
                        bbox=BBox(x1=float(x1), y1=float(y1), x2=float(x2), y2=float(y2)),
                        model_name=f"yolo:{self.weights_path.name if self.weights_path else 'custom'}",
                        model_version=self.version,
                        provenance=Provenance.PREDICTED,
                    )
                )
        return detections
