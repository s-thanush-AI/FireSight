"""Pixel <-> bearing conversion for fixed observation cameras.

Approximation (documented): we use a linear gnomonic-free model — the angular
offset of a pixel column from the image centre is proportional to its
normalized offset, scaled by the calibrated horizontal FOV:

    bearing = heading + (2 * pixel_x / width - 1) * hfov / 2

This ignores lens distortion. If radial coefficients (k1, k2) are available
they are applied to the normalized coordinate as a first-order radial
correction before the linear mapping. Accuracy is limited by heading/FOV
calibration, not by this model, for typical narrow-FOV monitoring lenses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LensModel:
    """Optional radial distortion (normalized image coordinates)."""

    k1: float = 0.0
    k2: float = 0.0

    @property
    def enabled(self) -> bool:
        return self.k1 != 0.0 or self.k2 != 0.0


def normalize_bearing(deg: float) -> float:
    """Normalize to [0, 360)."""
    return deg % 360.0


def _distort(x: float, lens: LensModel) -> float:
    r2 = x * x
    return x * (1.0 + lens.k1 * r2 + lens.k2 * r2 * r2)


def _undistort(x: float, lens: LensModel, iterations: int = 8) -> float:
    if not lens.enabled:
        return x
    xd = x
    for _ in range(iterations):
        r2 = xd * xd
        num = xd * (1.0 + lens.k1 * r2 + lens.k2 * r2 * r2)
        # fixed-point inversion of the radial polynomial
        denom = 1.0 + lens.k1 * r2 + lens.k2 * r2 * r2
        xd = xd - (num - x) / max(denom, 1e-6)
    return xd


def pixel_to_bearing(
    pixel_x: float,
    *,
    image_width: int,
    heading_deg: float,
    hfov_deg: float,
    lens: LensModel | None = None,
) -> float:
    """Convert a pixel column to a compass bearing (degrees clockwise from north).

    Positive image-x is to the right of centre; bearings increase clockwise.
    """
    if image_width <= 0:
        raise ValueError("image_width must be positive")
    if not (0.0 < hfov_deg <= 180.0):
        raise ValueError("hfov_deg must be in (0, 180]")
    x_norm = (pixel_x / image_width) * 2.0 - 1.0  # -1 .. +1
    if lens and lens.enabled:
        x_norm = _undistort(x_norm, lens)
    x_norm = max(-1.0, min(1.0, x_norm))
    angle = x_norm * (hfov_deg / 2.0)
    return normalize_bearing(heading_deg + angle)


def bearing_to_pixel(
    bearing_deg: float,
    *,
    image_width: int,
    heading_deg: float,
    hfov_deg: float,
    lens: LensModel | None = None,
) -> float | None:
    """Project a compass bearing into a pixel column, or None if outside the FOV."""
    if image_width <= 0:
        raise ValueError("image_width must be positive")
    if not (0.0 < hfov_deg <= 180.0):
        raise ValueError("hfov_deg must be in (0, 180]")
    delta = (bearing_deg - heading_deg + 540.0) % 360.0 - 180.0  # [-180, 180)
    if abs(delta) > hfov_deg / 2.0 + 1e-9:
        return None
    x_norm = delta / (hfov_deg / 2.0)
    if lens and lens.enabled:
        x_norm = _distort(x_norm, lens)
    return (x_norm + 1.0) / 2.0 * image_width


def proxy_point_from_bbox(
    x1: float, y1: float, x2: float, y2: float, kind: str = "bottom_center"
) -> tuple[float, float]:
    """Proxy point on a detection box used for bearing estimation."""
    if kind == "center":
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
    if kind == "bottom_center":
        return ((x1 + x2) / 2.0, y2)
    raise ValueError(f"Unknown proxy point kind: {kind}")


def angle_between_bearings(a_deg: float, b_deg: float) -> float:
    """Smallest angle between two bearings, in [0, 180]."""
    d = abs((a_deg - b_deg + 180.0) % 360.0 - 180.0)
    return d


def compass_point(bearing_deg: float) -> str:
    points = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    idx = int(math.floor((normalize_bearing(bearing_deg) + 11.25) / 22.5)) % 16
    return points[idx]
