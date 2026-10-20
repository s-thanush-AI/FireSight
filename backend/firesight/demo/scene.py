"""Deterministic synthetic scene rendering for the FireSight demo.

These frames exist to exercise the *pipeline* (replay, detection, temporal
verification, geometry, UI). They are NOT real wildfire imagery and must never
be presented as evidence that any detector works on real fires.
"""

from __future__ import annotations

import numpy as np


def _sky_background(h: int, w: int) -> np.ndarray:
    """Vertical sky gradient with a distant hill silhouette."""
    img = np.zeros((h, w, 3), dtype=np.float32)
    top = np.array([38, 34, 30], dtype=np.float32)     # dark dusk blue-grey (BGR)
    bottom = np.array([120, 140, 165], dtype=np.float32)
    for y in range(h):
        t = y / max(h - 1, 1)
        img[y, :, :] = top * (1 - t) + bottom * t

    horizon = int(h * 0.78)
    x = np.arange(w)
    ridge = (
        horizon
        - 18 * np.sin(x / 47.0)
        - 9 * np.sin(x / 13.0 + 1.3)
        - 5 * np.sin(x / 7.0 + 0.4)
    ).astype(int)
    for xi in range(w):
        y_top = int(max(0, min(horizon + 30, ridge[xi])))
        img[y_top:, xi, :] = np.array([46, 52, 48], dtype=np.float32)
        img[y_top : y_top + 2, xi, :] = np.array([60, 70, 62], dtype=np.float32)
    return img


def _soft_blob(
    img: np.ndarray,
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    intensity: float,
) -> None:
    """Add a soft elliptical bright blob in place (float image)."""
    h, w = img.shape[:2]
    y0 = max(int(cy - ry * 2.5), 0)
    y1 = min(int(cy + ry * 2.5) + 1, h)
    x0 = max(int(cx - rx * 2.5), 0)
    x1 = min(int(cx + rx * 2.5) + 1, w)
    if y0 >= y1 or x0 >= x1:
        return
    ys, xs = np.mgrid[y0:y1, x0:x1]
    d = ((xs - cx) / max(rx, 1e-3)) ** 2 + ((ys - cy) / max(ry, 1e-3)) ** 2
    falloff = np.exp(-d * 1.4)
    # smoke is grey-white: lifts all channels, slightly more red (warm light)
    blob = falloff[..., None] * intensity * np.array([1.0, 0.97, 0.92], dtype=np.float32)
    region = img[y0:y1, x0:x1]
    img[y0:y1, x0:x1] = np.clip(region + blob, 0, 255)


def render_frame(
    *,
    width: int,
    height: int,
    frame_index: int,
    plume: dict | None,
    distractor: dict | None = None,
    seed: int = 7,
) -> np.ndarray:
    """Render one synthetic camera frame.

    plume/distractor: {"x": px, "y": px, "rx": px, "ry": px, "intensity": 0..1}
    """
    rng = np.random.default_rng(seed * 100003 + frame_index)
    img = _sky_background(height, width)

    if distractor is not None:
        _soft_blob(
            img,
            distractor["x"] + float(rng.normal(0, 0.6)),
            distractor["y"] + float(rng.normal(0, 0.4)),
            distractor["rx"],
            distractor["ry"],
            distractor["intensity"],
        )

    if plume is not None:
        wobble_x = float(rng.normal(0, 1.2))
        wobble_y = float(rng.normal(0, 0.8))
        _soft_blob(
            img,
            plume["x"] + wobble_x,
            plume["y"] + wobble_y,
            plume["rx"],
            plume["ry"],
            plume["intensity"],
        )
        # faint trailing drift to look plume-like
        _soft_blob(
            img,
            plume["x"] + wobble_x + plume["rx"] * 0.9,
            plume["y"] + wobble_y - plume["ry"] * 0.35,
            plume["rx"] * 1.6,
            plume["ry"] * 0.7,
            plume["intensity"] * 0.55,
        )

    noise = rng.normal(0, 1.6, img.shape).astype(np.float32)
    img = np.clip(img + noise, 0, 255)
    return img.astype(np.uint8)
