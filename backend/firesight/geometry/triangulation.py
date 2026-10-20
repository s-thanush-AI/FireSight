"""Least-squares intersection of camera bearing rays in a local ENU frame.

Convention: bearings are compass azimuths (degrees clockwise from true north).
In the ENU frame a bearing b maps to unit direction (east, north) =
(sin b, cos b). Rays are horizontal; the intersection is the ground-plane
point where the two azimuth lines cross. It estimates a *smoke-source
direction proxy*, not a proven fire origin.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..enums import GeometryQuality, Provenance
from ..models import BearingObservation, CameraConfig, TriangulationResult
from .bearing import normalize_bearing
from .frames import enu_to_latlon, geodesic_distance_m, latlon_to_enu
from .uncertainty import bearing_sigma_deg, propagate_position_sigma_m


@dataclass(frozen=True)
class CartesianRay:
    """2-D ray in local ENU (east, north) metres."""

    origin_e: float
    origin_n: float
    direction_e: float
    direction_n: float
    camera_id: str

    @property
    def direction(self) -> tuple[float, float]:
        return (self.direction_e, self.direction_n)


def ray_from_camera(east: float, north: float, bearing_deg: float, camera_id: str) -> CartesianRay:
    b = math.radians(normalize_bearing(bearing_deg))
    return CartesianRay(
        origin_e=east,
        origin_n=north,
        direction_e=math.sin(b),
        direction_n=math.cos(b),
        camera_id=camera_id,
    )


def _lsq_intersection(rays: list[CartesianRay]) -> tuple[tuple[float, float], list[float]]:
    """Solve min_x sum_i ||(I - d_i d_i^T)(x - o_i)||^2. Returns (point, per-ray residuals)."""
    a11 = a12 = a22 = 0.0
    b1 = b2 = 0.0
    for r in rays:
        dx, dy = r.direction_e, r.direction_n
        # P = I - d d^T
        p11 = 1.0 - dx * dx
        p12 = -dx * dy
        p22 = 1.0 - dy * dy
        a11 += p11
        a12 += p12
        a22 += p22
        b1 += p11 * r.origin_e + p12 * r.origin_n
        b2 += p12 * r.origin_e + p22 * r.origin_n
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-9:
        raise ValueError("degenerate least-squares system (parallel rays)")
    x = (b1 * a22 - b2 * a12) / det
    y = (a11 * b2 - a12 * b1) / det
    residuals = []
    for r in rays:
        px, py = x - r.origin_e, y - r.origin_n
        t = px * r.direction_e + py * r.direction_n
        cx = px - t * r.direction_e
        cy = py - t * r.direction_n
        residuals.append(math.hypot(cx, cy))
    return (x, y), residuals


def _min_pairwise_separation(rays: list[CartesianRay]) -> float:
    def ang(r: CartesianRay) -> float:
        return math.degrees(math.atan2(r.direction_e, r.direction_n)) % 360.0

    worst = 180.0
    for i in range(len(rays)):
        for j in range(i + 1, len(rays)):
            d = abs((ang(rays[i]) - ang(rays[j]) + 180.0) % 360.0 - 180.0)
            worst = min(worst, d)
    return worst


def triangulate(
    observations: list[BearingObservation],
    cameras: dict[str, CameraConfig],
    *,
    min_separation_deg: float = 4.0,
    max_distance_m: float = 60_000.0,
    pixel_sigma_frac: float = 0.01,
    heading_sigma_deg: float = 1.5,
) -> TriangulationResult:
    """Triangulate an estimated smoke-source location from >= 2 camera bearings."""
    base_assumptions = [
        "bearings are horizontal azimuths; plume elevation is ignored",
        "camera positions and headings are treated as point estimates with stated noise",
        "linear pixel->bearing model (see geometry.bearing) without distortion unless calibrated",
    ]
    limitations = [
        "a smoke plume is wind-driven; the estimated point is a smoke-source proxy, "
        "not a proven fire origin",
        "terrain, haze and detector box placement all add unmodelled error",
    ]

    if len(observations) < 2:
        return TriangulationResult(
            quality=GeometryQuality.UNAVAILABLE,
            assumptions=base_assumptions,
            limitations=limitations + ["at least two camera observations are required"],
            provenance=Provenance.HEURISTIC,
        )

    missing = [o.camera_id for o in observations if o.camera_id not in cameras]
    if missing:
        return TriangulationResult(
            quality=GeometryQuality.UNAVAILABLE,
            assumptions=base_assumptions,
            limitations=limitations + [f"camera configuration missing for: {', '.join(sorted(set(missing)))}"],
            provenance=Provenance.HEURISTIC,
        )

    cams = [cameras[o.camera_id] for o in observations]
    uncalibrated = [c.id for c in cams if c.calibration_status.value == "uncalibrated"]
    if uncalibrated:
        return TriangulationResult(
            quality=GeometryQuality.UNAVAILABLE,
            assumptions=base_assumptions,
            limitations=limitations
            + [f"camera(s) not calibrated, refusing to estimate location: {', '.join(sorted(set(uncalibrated)))}"],
            provenance=Provenance.HEURISTIC,
        )

    origin_lat = sum(c.latitude for c in cams) / len(cams)
    origin_lon = sum(c.longitude for c in cams) / len(cams)

    rays: list[CartesianRay] = []
    for o, c in zip(observations, cams, strict=True):
        e, n = latlon_to_enu(c.latitude, c.longitude, origin_lat, origin_lon)
        rays.append(ray_from_camera(e, n, o.bearing_deg, c.id))

    try:
        (pe, pn), residuals = _lsq_intersection(rays)
    except ValueError:
        return TriangulationResult(
            quality=GeometryQuality.REJECTED,
            assumptions=base_assumptions,
            limitations=limitations + ["rays are (nearly) parallel: the intersection is ill-conditioned"],
            ray_separation_deg=_min_pairwise_separation(rays),
            provenance=Provenance.HEURISTIC,
        )

    separation = _min_pairwise_separation(rays)
    mean_residual = sum(residuals) / len(residuals)
    distances: dict[str, float] = {}
    behind: list[str] = []
    along: dict[str, float] = {}
    for r in rays:
        t = (pe - r.origin_e) * r.direction_e + (pn - r.origin_n) * r.direction_n
        along[r.camera_id] = t
        distances[r.camera_id] = math.hypot(pe - r.origin_e, pn - r.origin_n)
        if t < 0:
            behind.append(r.camera_id)

    lat, lon = enu_to_latlon(pe, pn, origin_lat, origin_lon)
    mean_distance = sum(distances.values()) / len(distances)

    if behind:
        return TriangulationResult(
            quality=GeometryQuality.REJECTED,
            latitude=None,
            longitude=None,
            ray_separation_deg=separation,
            intersection_angle_deg=separation,
            fit_residual_m=mean_residual,
            distances_per_camera_m=distances,
            assumptions=base_assumptions,
            limitations=limitations
            + [f"intersection lies behind camera(s): {', '.join(sorted(set(behind)))} — bearings are incompatible"],
            provenance=Provenance.HEURISTIC,
        )

    if mean_distance > max_distance_m:
        return TriangulationResult(
            quality=GeometryQuality.REJECTED,
            latitude=None,
            longitude=None,
            ray_separation_deg=separation,
            intersection_angle_deg=separation,
            fit_residual_m=mean_residual,
            distances_per_camera_m=distances,
            assumptions=base_assumptions,
            limitations=limitations
            + [f"estimated distance {mean_distance:.0f} m exceeds the configured maximum {max_distance_m:.0f} m"],
            provenance=Provenance.HEURISTIC,
        )

    if separation < min_separation_deg:
        return TriangulationResult(
            quality=GeometryQuality.REJECTED,
            latitude=None,
            longitude=None,
            ray_separation_deg=separation,
            intersection_angle_deg=separation,
            fit_residual_m=mean_residual,
            distances_per_camera_m=distances,
            assumptions=base_assumptions,
            limitations=limitations
            + [
                f"ray separation {separation:.1f}° is below the minimum {min_separation_deg:.1f}°; "
                "crossing geometry is too weak for a meaningful estimate"
            ],
            provenance=Provenance.HEURISTIC,
        )

    sigmas = []
    for c in cams:
        s = bearing_sigma_deg(c.hfov_deg, c.image_width, pixel_sigma_frac, heading_sigma_deg)
        if c.calibration_uncertainty_deg:
            s = math.hypot(s, c.calibration_uncertainty_deg)
        sigmas.append(s)
    sigma_m = propagate_position_sigma_m(list(distances.values()), sigmas, separation)

    residual_limit = max(30.0, 0.02 * mean_distance)
    if mean_residual > residual_limit:
        quality = GeometryQuality.WEAK
        limitations.append(
            f"fit residual {mean_residual:.0f} m exceeds {residual_limit:.0f} m — "
            "the bearings do not cross cleanly (detector localisation or association error likely)"
        )
    elif separation >= 30.0:
        quality = GeometryQuality.STRONG
    elif separation >= 15.0:
        quality = GeometryQuality.ACCEPTABLE
    else:
        quality = GeometryQuality.WEAK
        limitations.append(
            f"ray separation {separation:.1f}° is low; location error along the "
            "bisector direction grows quickly"
        )

    for c, sigma in zip(cams, sigmas, strict=True):
        if c.calibration_status.value in ("approximate", "simulated"):
            limitations.append(
                f"camera {c.id} calibration status is '{c.calibration_status.value}' "
                f"(heading sigma {sigma:.2f}°); heading/FOV errors propagate into this estimate"
            )

    return TriangulationResult(
        quality=quality,
        latitude=lat,
        longitude=lon,
        uncertainty_m=None if math.isinf(sigma_m) else round(sigma_m, 1),
        ray_separation_deg=round(separation, 2),
        intersection_angle_deg=round(separation, 2),
        fit_residual_m=round(mean_residual, 2),
        distances_per_camera_m={k: round(v, 1) for k, v in distances.items()},
        assumptions=base_assumptions,
        limitations=limitations,
        provenance=Provenance.HEURISTIC,
    )


def geodesic_error_m(
    est_lat: float, est_lon: float, gt_lat: float, gt_lon: float
) -> float:
    return geodesic_distance_m(est_lat, est_lon, gt_lat, gt_lon)
