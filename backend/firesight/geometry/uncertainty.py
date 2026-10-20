"""Uncertainty propagation for bearing-based geolocation.

Stated assumptions (surfaced in every result):
  * detector horizontal localisation noise ~ N(0, (pixel_sigma_frac * width)^2)
  * camera heading noise ~ N(0, heading_sigma_deg^2), independent per camera
  * bearings are horizontal (azimuth) measurements; plume elevation is ignored
  * first-order propagation: sigma_pos ~= R * sigma_bearing / sin(theta)
    where R is the range to the intersection and theta the ray intersection
    angle. This diverges for near-parallel rays (reported as huge sigma).
"""

from __future__ import annotations

import math


def bearing_sigma_deg(
    hfov_deg: float,
    image_width: int,
    pixel_sigma_frac: float,
    heading_sigma_deg: float,
) -> float:
    """Total per-camera bearing standard deviation in degrees."""
    if image_width <= 0:
        raise ValueError("image_width must be positive")
    pixel_sigma_deg = (pixel_sigma_frac * hfov_deg) / 2.0
    return math.hypot(pixel_sigma_deg, heading_sigma_deg)


def propagate_position_sigma_m(
    distances_m: list[float],
    bearing_sigmas_deg: list[float],
    intersection_angle_deg: float,
) -> float:
    """First-order position sigma (metres) at a ray intersection.

    Uses the worst (largest) per-camera contribution. Diverges as the
    intersection angle approaches 0 or 180 degrees.
    """
    if not distances_m or len(distances_m) != len(bearing_sigmas_deg):
        raise ValueError("distances_m and bearing_sigmas_deg must be non-empty and equal length")
    sin_theta = math.sin(math.radians(min(max(intersection_angle_deg, 0.0), 180.0)))
    if sin_theta < 1e-6:
        return float("inf")
    worst = 0.0
    for r, s in zip(distances_m, bearing_sigmas_deg, strict=True):
        worst = max(worst, abs(r) * math.radians(s) / sin_theta)
    return worst
