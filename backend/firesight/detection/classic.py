from __future__ import annotations

import cv2
import numpy as np

from ..enums import Provenance
from ..models import BBox, Detection, FrameRef
from .base import BaseDetector


class ClassicSmokeDetector(BaseDetector):
    """Classic-CV smoke-candidate detector (no learned weights).

    Locates bright, low-saturation, diffuse blobs in the upper portion of the
    frame — a deliberately simple, explainable heuristic. It exists so demo
    mode runs *real image processing* on the generated frames without any
    model weights. It is NOT a trained wildfire smoke model and must always be
    reported with provenance 'predicted' plus this caveat.
    """

    name = "classic-smoke-blob"
    version = "0.1.0"
    provenance = Provenance.PREDICTED
    caveat = (
        "Classic intensity/saturation blob heuristic; not a trained smoke classifier. "
        "Clouds, haze and bright terrain can trigger it."
    )

    def __init__(
        self,
        confidence_threshold: float = 0.25,
        min_area_frac: float = 0.002,
        max_area_frac: float = 0.45,
        search_top_frac: float = 0.85,
    ):
        self.confidence_threshold = confidence_threshold
        self.min_area_frac = min_area_frac
        self.max_area_frac = max_area_frac
        self.search_top_frac = search_top_frac

    @property
    def available(self) -> bool:
        return True

    def detect(self, image: np.ndarray, frame: FrameRef, camera_id: str | None = None) -> list[Detection]:
        h, w = image.shape[:2]
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        sat, val = hsv[:, :, 1], hsv[:, :, 2]
        # Smoke: bright, weakly saturated. Threshold relative to frame stats so
        # global brightness changes do not flip behaviour.
        val_thr = int(max(110, np.percentile(val, 88)))
        sat_thr = int(min(90, np.percentile(sat, 55) + 40))
        mask = ((val >= val_thr) & (sat <= sat_thr)).astype(np.uint8) * 255

        search_h = int(h * self.search_top_frac)
        mask[search_h:, :] = 0

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        frame_area = float(w * h)
        detections: list[Detection] = []
        for cnt in sorted(contours, key=cv2.contourArea, reverse=True):
            area = float(cv2.contourArea(cnt))
            area_frac = area / frame_area
            if area_frac < self.min_area_frac or area_frac > self.max_area_frac:
                continue
            x, y, bw, bh = cv2.boundingRect(cnt)
            fill = area / max(float(bw * bh), 1.0)
            mean_val = float(np.mean(gray[y : y + bh, x : x + bw]))
            # Confidence from fill ratio, brightness and how much of the box is smoke-like.
            conf = float(
                np.clip(0.25 + 0.45 * fill + 0.30 * (mean_val / 255.0), 0.05, 0.92)
            )
            if conf < self.confidence_threshold:
                continue
            bbox = BBox(x1=float(x), y1=float(y), x2=float(x + bw), y2=float(y + bh))
            detections.append(
                Detection(
                    frame=frame,
                    camera_id=camera_id,
                    class_name="smoke",
                    confidence=round(conf, 4),
                    bbox=bbox,
                    model_name=self.name,
                    model_version=self.version,
                    provenance=Provenance.PREDICTED,
                )
            )
            if len(detections) >= 3:
                break
        return detections
