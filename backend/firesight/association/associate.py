"""Cross-camera observation association.

Pairs bearing observations from two cameras by timestamp proximity, then
validates the pair geometrically (triangulation must produce a usable
intersection within the configured residual limit).

Evidence types are explicit:
  * real_paired           — both observations are real, independently located
  * real_unpaired         — only one real observation (no valid partner)
  * simulated_second_camera — one side is a simulated demo observation; the
                              *geometry computation itself is genuine*
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..enums import EvidenceType, GeometryQuality, Provenance
from ..geometry.triangulation import triangulate
from ..models import BearingObservation, CameraConfig, TriangulationResult


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


@dataclass
class AssociationCandidate:
    left: BearingObservation
    right: BearingObservation
    timestamp_delta_s: float | None
    triangulation: TriangulationResult
    evidence_type: EvidenceType
    valid: bool
    reason: str


def _evidence_type(left: BearingObservation, right: BearingObservation) -> EvidenceType:
    if Provenance.SIMULATED in (left.provenance, right.provenance):
        return EvidenceType.SIMULATED_SECOND_CAMERA
    if EvidenceType.SIMULATED_SECOND_CAMERA in (left.evidence_type, right.evidence_type):
        return EvidenceType.SIMULATED_SECOND_CAMERA
    return EvidenceType.REAL_PAIRED


def associate_observations(
    left: list[BearingObservation],
    right: list[BearingObservation],
    cameras: dict[str, CameraConfig],
    *,
    timestamp_tolerance_s: float = 2.0,
    max_residual_m: float = 2500.0,
    min_separation_deg: float = 4.0,
    max_distance_m: float = 60_000.0,
    pixel_sigma_frac: float = 0.01,
    heading_sigma_deg: float = 1.5,
) -> list[AssociationCandidate]:
    """Greedy 1-1 nearest-in-time pairing, geometrically validated."""
    pairs: list[tuple[float, BearingObservation, BearingObservation]] = []
    for lo in left:
        lts = _parse_ts(lo.timestamp)
        for ro in right:
            if lo.camera_id == ro.camera_id:
                continue
            rts = _parse_ts(ro.timestamp)
            if lts is None or rts is None:
                # Without timestamps only a single unpaired candidate is possible.
                continue
            dt = abs((lts - rts).total_seconds())
            if dt <= timestamp_tolerance_s:
                pairs.append((dt, lo, ro))
    pairs.sort(key=lambda p: p[0])

    used_left: set[int] = set()
    used_right: set[int] = set()
    results: list[AssociationCandidate] = []
    for dt, lo, ro in pairs:
        if id(lo) in used_left or id(ro) in used_right:
            continue
        used_left.add(id(lo))
        used_right.add(id(ro))
        tri = triangulate(
            [lo, ro],
            cameras,
            min_separation_deg=min_separation_deg,
            max_distance_m=max_distance_m,
            pixel_sigma_frac=pixel_sigma_frac,
            heading_sigma_deg=heading_sigma_deg,
        )
        ev = _evidence_type(lo, ro)
        if tri.quality in (GeometryQuality.UNAVAILABLE, GeometryQuality.REJECTED):
            valid = False
            reason = "; ".join(tri.limitations[-1:]) or "triangulation not usable"
        elif tri.fit_residual_m is not None and tri.fit_residual_m > max_residual_m:
            valid = False
            reason = (
                f"fit residual {tri.fit_residual_m:.0f} m exceeds association limit "
                f"{max_residual_m:.0f} m — observations likely describe different sources"
            )
        else:
            valid = True
            reason = (
                f"timestamp delta {dt:.2f}s within {timestamp_tolerance_s:.2f}s; "
                f"geometry {tri.quality.value}"
            )
        results.append(
            AssociationCandidate(
                left=lo,
                right=ro,
                timestamp_delta_s=round(dt, 3),
                triangulation=tri,
                evidence_type=ev,
                valid=valid,
                reason=reason,
            )
        )

    # Unpaired leftovers are surfaced so callers never mistake them for pairs.
    for lo in left:
        if id(lo) not in used_left:
            results.append(
                AssociationCandidate(
                    left=lo,
                    right=lo,
                    timestamp_delta_s=None,
                    triangulation=triangulate(
                        [lo], cameras,
                        min_separation_deg=min_separation_deg,
                        max_distance_m=max_distance_m,
                    ),
                    evidence_type=(
                        EvidenceType.SIMULATED_SECOND_CAMERA
                        if lo.provenance == Provenance.SIMULATED
                        else EvidenceType.REAL_UNPAIRED
                    ),
                    valid=False,
                    reason="no partner observation within the timestamp tolerance",
                )
            )
    return results
