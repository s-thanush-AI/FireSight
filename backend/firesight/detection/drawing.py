from __future__ import annotations

import cv2
import numpy as np

from ..models import Detection

_BOX_COLOR = (60, 200, 255)  # BGR amber
_LABEL_BG = (20, 20, 20)


def draw_detections(
    image: np.ndarray,
    detections: list[Detection],
    *,
    watermark: str | None = None,
    metadata_lines: list[str] | None = None,
) -> np.ndarray:
    """Return a copy of the image with boxes, confidences and metadata drawn."""
    out = image.copy()
    for d in detections:
        x1, y1, x2, y2 = (int(round(v)) for v in (d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2))
        cv2.rectangle(out, (x1, y1), (x2, y2), _BOX_COLOR, 2)
        label = f"{d.class_name} {d.confidence:.2f}"
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ty = max(y1 - 4, th + 4)
        cv2.rectangle(out, (x1, ty - th - 4), (x1 + tw + 4, ty + baseline - 4), _LABEL_BG, -1)
        cv2.putText(
            out, label, (x1 + 2, ty - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
            (255, 255, 255), 1, cv2.LINE_AA,
        )
    y = 18
    for line in metadata_lines or []:
        cv2.putText(
            out, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 230, 230), 1, cv2.LINE_AA
        )
        y += 16
    if watermark:
        h, w = out.shape[:2]
        (tw, _), _ = cv2.getTextSize(watermark, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        cv2.putText(
            out, watermark, ((w - tw) // 2, h - 14),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (40, 40, 230), 2, cv2.LINE_AA,
        )
    return out
