"""Deterministic FireSight demo scenario.

Everything here is SIMULATED: cameras, imagery, plume position, and the
second camera's observation. The geometry executed on the simulated bearings
is genuine — the same code path used for real data.

Scenario: two simulated ridge cameras watch a known simulated smoke source.
Camera A sees a distracting cloud first, then the growing plume; camera B
sees the plume slightly later. This exercises replay, detection, temporal
confirmation, association, triangulation and incident creation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2

from ..enums import CalibrationStatus, Provenance
from ..geometry.bearing import bearing_to_pixel, normalize_bearing
from ..geometry.frames import enu_to_latlon, latlon_to_enu
from ..models import CameraConfig
from .scene import render_frame

DEMO_ORIGIN = (37.2000, -119.5000)  # (lat, lon) Sierra Nevada-ish, simulated site
DEMO_FPS = 5.0
DEMO_BASE_TIME = datetime(2024, 7, 12, 15, 30, 0, tzinfo=UTC)

# Simulated smoke source, expressed in local ENU metres about DEMO_ORIGIN.
DEMO_SOURCE_ENU = (3500.0, 2500.0)


@dataclass(frozen=True)
class SequenceSpec:
    id: str
    name: str
    camera_id: str
    n_frames: int
    plume_start: int
    plume_end: int
    distractor_window: tuple[int, int] | None = None
    description: str = ""


DEMO_SEQUENCE_A = SequenceSpec(
    id="demo-alpha-ridge",
    name="Alpha Ridge (simulated)",
    camera_id="sim-cam-a",
    n_frames=50,
    plume_start=10,
    plume_end=50,
    distractor_window=(0, 12),
    description=(
        "Simulated 10 s fixed-camera sequence: a passing cloud distractor first, "
        "then a growing smoke plume that persists to the end of the sequence."
    ),
)

DEMO_SEQUENCE_B = SequenceSpec(
    id="demo-bravo-ridge",
    name="Bravo Ridge (simulated)",
    camera_id="sim-cam-b",
    n_frames=50,
    plume_start=16,
    plume_end=50,
    distractor_window=None,
    description=(
        "Simulated second-camera sequence of the same event, seen from ~3.2 km "
        "away; the plume becomes visible later than from camera A."
    ),
)


def _bearing_to_target(cam_e: float, cam_n: float) -> float:
    te, tn = DEMO_SOURCE_ENU
    import math

    return normalize_bearing(math.degrees(math.atan2(te - cam_e, tn - cam_n)))


def demo_cameras() -> list[CameraConfig]:
    olat, olon = DEMO_ORIGIN
    a_e, a_n = 0.0, 0.0
    b_e, b_n = 6000.0, 500.0
    a_lat, a_lon = enu_to_latlon(a_e, a_n, olat, olon)
    b_lat, b_lon = enu_to_latlon(b_e, b_n, olat, olon)
    return [
        CameraConfig(
            id="sim-cam-a",
            name="Alpha Ridge (simulated)",
            latitude=round(a_lat, 7),
            longitude=round(a_lon, 7),
            height_m=6.0,
            heading_deg=round(_bearing_to_target(a_e, a_n), 2),
            hfov_deg=55.0,
            image_width=640,
            image_height=360,
            calibration_status=CalibrationStatus.SIMULATED,
            calibration_source="scenario fixture",
            calibration_uncertainty_deg=1.0,
            provenance=Provenance.SIMULATED,
            notes="Simulated demo camera — not a real device.",
        ),
        CameraConfig(
            id="sim-cam-b",
            name="Bravo Ridge (simulated)",
            latitude=round(b_lat, 7),
            longitude=round(b_lon, 7),
            height_m=8.0,
            heading_deg=round(_bearing_to_target(b_e, b_n), 2),
            hfov_deg=55.0,
            image_width=640,
            image_height=360,
            calibration_status=CalibrationStatus.SIMULATED,
            calibration_source="scenario fixture",
            calibration_uncertainty_deg=1.0,
            provenance=Provenance.SIMULATED,
            notes="Simulated demo camera — not a real device.",
        ),
    ]


def demo_ground_truth_latlon() -> tuple[float, float]:
    olat, olon = DEMO_ORIGIN
    return enu_to_latlon(DEMO_SOURCE_ENU[0], DEMO_SOURCE_ENU[1], olat, olon)


def plume_pixel_position(
    camera: CameraConfig, frame_index: int, spec: SequenceSpec
) -> tuple[float, float, float] | None:
    """Projected plume centre (x, y, growth) for this camera/frame, or None."""
    if frame_index < spec.plume_start or frame_index >= spec.plume_end:
        return None
    olat, olon = DEMO_ORIGIN
    cam_e, cam_n = latlon_to_enu(camera.latitude, camera.longitude, olat, olon)
    bearing = _bearing_to_target(cam_e, cam_n)
    px = bearing_to_pixel(
        bearing,
        image_width=camera.image_width,
        heading_deg=camera.heading_deg,
        hfov_deg=camera.hfov_deg,
    )
    if px is None:
        return None
    t = (frame_index - spec.plume_start) / max(spec.plume_end - spec.plume_start - 1, 1)
    y = camera.image_height * (0.42 - 0.10 * t)  # plume rises as it grows
    growth = 0.25 + 0.75 * t
    return float(px), float(y), float(growth)


@dataclass
class DemoScenario:
    cameras: dict[str, CameraConfig]
    ground_truth_lat: float
    ground_truth_lon: float
    sequences: dict[str, SequenceSpec] = field(default_factory=dict)
    provenance: Provenance = Provenance.SIMULATED


def demo_scenario() -> DemoScenario:
    cams = {c.id: c for c in demo_cameras()}
    gt_lat, gt_lon = demo_ground_truth_latlon()
    return DemoScenario(
        cameras=cams,
        ground_truth_lat=gt_lat,
        ground_truth_lon=gt_lon,
        sequences={s.id: s for s in (DEMO_SEQUENCE_A, DEMO_SEQUENCE_B)},
    )


def _plume_params(growth: float, distance_frac: float = 1.0) -> dict:
    rx = (14 + 46 * growth) * distance_frac
    ry = (9 + 30 * growth) * distance_frac
    intensity = 55 + 105 * growth
    return {"rx": rx, "ry": ry, "intensity": intensity}


def generate_demo_sequence(
    out_dir: Path,
    camera: CameraConfig,
    spec: SequenceSpec,
    *,
    seed: int = 7,
) -> list[Path]:
    """Render the synthetic sequence to disk. Deterministic for a given seed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for i in range(spec.n_frames):
        ts = DEMO_BASE_TIME + timedelta(seconds=i / DEMO_FPS)
        stamp = ts.strftime("%Y-%m-%d_%H-%M-%S")
        frac = (i % int(DEMO_FPS)) / DEMO_FPS
        fname = f"{stamp}_{int(frac * 1_000_000):06d}_{camera.id}_{i:04d}.png"
        plume = None
        pos = plume_pixel_position(camera, i, spec)
        if pos is not None:
            x, y, growth = pos
            dist = 1.0 if camera.id == "sim-cam-a" else 0.85  # farther camera: smaller blob
            plume = {"x": x, "y": y, **_plume_params(growth, dist)}
        distractor = None
        if spec.distractor_window and spec.distractor_window[0] <= i < spec.distractor_window[1]:
            frac_d = (i - spec.distractor_window[0]) / max(
                spec.distractor_window[1] - spec.distractor_window[0] - 1, 1
            )
            distractor = {
                "x": camera.image_width * 0.22,
                "y": camera.image_height * 0.35,
                "rx": 16 + 6 * frac_d,
                "ry": 10 + 4 * frac_d,
                "intensity": 70 + 25 * frac_d,
            }
        frame = render_frame(
            width=camera.image_width,
            height=camera.image_height,
            frame_index=i,
            plume=plume,
            distractor=distractor,
            seed=seed + (0 if camera.id == "sim-cam-a" else 1000),
        )
        path = out_dir / fname
        ok, enc = cv2.imencode(".png", frame)
        if not ok:
            raise RuntimeError(f"Failed to encode demo frame {path}")
        path.write_bytes(enc.tobytes())
        written.append(path)
    return written


def ensure_demo_sequences(data_root: Path) -> dict[str, Path]:
    """Generate demo sequences under data_root/demo/ if missing. Returns seq dirs."""
    base = Path(data_root) / "demo"
    cams = {c.id: c for c in demo_cameras()}
    result: dict[str, Path] = {}
    for spec in (DEMO_SEQUENCE_A, DEMO_SEQUENCE_B):
        seq_dir = base / spec.id
        marker = seq_dir / ".complete"
        if marker.exists() and any(seq_dir.glob("*.png")):
            result[spec.id] = seq_dir
            continue
        if seq_dir.exists():
            for old in seq_dir.glob("*.png"):
                old.unlink()
        generate_demo_sequence(seq_dir, cams[spec.camera_id], spec)
        marker.write_text(f"generated seed=7 frames={spec.n_frames}\n")
        result[spec.id] = seq_dir
    return result
