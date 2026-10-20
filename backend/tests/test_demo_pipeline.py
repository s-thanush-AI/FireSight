"""End-to-end style tests: generated demo frames -> classic detector -> geometry.

These verify that the *pipeline mechanics* work. They do NOT validate the
detector on real wildfire imagery.
"""

import math

import numpy as np
import pytest

from firesight.demo.scenario import (
    DEMO_SEQUENCE_A,
    DEMO_SEQUENCE_B,
    demo_cameras,
    demo_scenario,
    generate_demo_sequence,
    plume_pixel_position,
)
from firesight.demo.scene import render_frame
from firesight.detection.classic import ClassicSmokeDetector
from firesight.enums import EvidenceType
from firesight.geometry.bearing import bearing_to_pixel
from firesight.geometry.frames import latlon_to_enu
from firesight.geometry.triangulation import triangulate
from firesight.models import BearingObservation, FrameRef, Provenance
from firesight.replay.discovery import discover_frames, load_frame


@pytest.fixture(scope="module")
def seq_a(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo") / DEMO_SEQUENCE_A.id
    cam = {c.id: c for c in demo_cameras()}[DEMO_SEQUENCE_A.camera_id]
    generate_demo_sequence(out, cam, DEMO_SEQUENCE_A, seed=7)
    return out, cam


@pytest.fixture(scope="module")
def seq_b(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo") / DEMO_SEQUENCE_B.id
    cam = {c.id: c for c in demo_cameras()}[DEMO_SEQUENCE_B.camera_id]
    generate_demo_sequence(out, cam, DEMO_SEQUENCE_B, seed=7)
    return out, cam


class TestSceneRendering:
    def test_render_deterministic(self):
        a = render_frame(width=320, height=180, frame_index=3, plume=None)
        b = render_frame(width=320, height=180, frame_index=3, plume=None)
        assert np.array_equal(a, b)
        assert a.shape == (180, 320, 3)

    def test_render_differs_with_plume(self):
        clean = render_frame(width=320, height=180, frame_index=3, plume=None)
        plumed = render_frame(
            width=320, height=180, frame_index=3,
            plume={"x": 160, "y": 60, "rx": 20, "ry": 12, "intensity": 120},
        )
        assert not np.array_equal(clean, plumed)

    def test_plume_brighter(self):
        clean = render_frame(width=320, height=180, frame_index=3, plume=None)
        plumed = render_frame(
            width=320, height=180, frame_index=3,
            plume={"x": 160, "y": 60, "rx": 20, "ry": 12, "intensity": 120},
        )
        region_clean = clean[40:80, 130:190].mean()
        region_plumed = plumed[40:80, 130:190].mean()
        assert region_plumed > region_clean + 15


class TestDemoScenario:
    def test_cameras_are_simulated(self):
        cams = demo_cameras()
        assert len(cams) == 2
        for c in cams:
            assert c.provenance == Provenance.SIMULATED
            assert c.calibration_status.value == "simulated"

    def test_ground_truth_within_both_fovs(self):
        sc = demo_scenario()
        for cam in sc.cameras.values():
            e, n = latlon_to_enu(sc.ground_truth_lat, sc.ground_truth_lon, 37.2, -119.5)
            bearing = math.degrees(math.atan2(e - 0, n - 0)) % 360 if cam.id.endswith("a") else None
            assert bearing is not None or cam.id.endswith("b")
            px = bearing_to_pixel(
                _true_bearing(cam, sc),
                image_width=cam.image_width,
                heading_deg=cam.heading_deg,
                hfov_deg=cam.hfov_deg,
            )
            assert px is not None, f"GT outside FOV of {cam.id}"

    def test_plume_absent_before_start(self):
        cam = {c.id: c for c in demo_cameras()}[DEMO_SEQUENCE_A.camera_id]
        assert plume_pixel_position(cam, 0, DEMO_SEQUENCE_A) is None
        assert plume_pixel_position(cam, DEMO_SEQUENCE_A.plume_start, DEMO_SEQUENCE_A) is not None

    def test_generation_deterministic(self, tmp_path):
        cam = {c.id: c for c in demo_cameras()}[DEMO_SEQUENCE_A.camera_id]
        d1 = tmp_path / "s1"
        d2 = tmp_path / "s2"
        generate_demo_sequence(d1, cam, DEMO_SEQUENCE_A, seed=7)
        generate_demo_sequence(d2, cam, DEMO_SEQUENCE_A, seed=7)
        f1 = sorted(p.name for p in d1.glob("*.png"))
        f2 = sorted(p.name for p in d2.glob("*.png"))
        assert f1 == f2
        for name in f1[:5]:
            assert (d1 / name).read_bytes() == (d2 / name).read_bytes()


def _true_bearing(cam, sc):
    olat, olon = 37.2, -119.5
    cam_e, cam_n = latlon_to_enu(cam.latitude, cam.longitude, olat, olon)
    te, tn = latlon_to_enu(sc.ground_truth_lat, sc.ground_truth_lon, olat, olon)
    return math.degrees(math.atan2(te - cam_e, tn - cam_n)) % 360


class TestClassicDetectorOnDemoFrames:
    def test_no_smoke_before_plume(self, seq_a):
        d, cam = seq_a
        frames = discover_frames(d)
        det = ClassicSmokeDetector(confidence_threshold=0.3)
        f0 = frames[0]
        img, _ = load_frame(f0)
        ref = FrameRef(sequence_id=DEMO_SEQUENCE_A.id, index=0, filename=f0.filename)
        dets = det.detect(img, ref, cam.id)
        # distractor cloud may or may not fire; nothing confident near plume location
        plume_pos = plume_pixel_position(cam, 0, DEMO_SEQUENCE_A)
        assert plume_pos is None
        for x in dets:
            assert x.confidence < 0.85

    def test_detects_plume_when_grown(self, seq_a):
        d, cam = seq_a
        frames = discover_frames(d)
        det = ClassicSmokeDetector(confidence_threshold=0.3)
        idx = DEMO_SEQUENCE_A.plume_start + 25
        f = frames[idx]
        img, _ = load_frame(f)
        ref = FrameRef(sequence_id=DEMO_SEQUENCE_A.id, index=idx, filename=f.filename)
        dets = det.detect(img, ref, cam.id)
        assert dets, "expected at least one detection on a grown plume frame"
        best = max(dets, key=lambda x: x.confidence)
        assert best.provenance == Provenance.PREDICTED
        assert best.model_name == "classic-smoke-blob"
        assert best.class_name == "smoke"
        px, py, _ = plume_pixel_position(cam, idx, DEMO_SEQUENCE_A)
        cx, cy = best.bbox.center()
        assert abs(cx - px) < 80, f"detected box centre {cx} far from projected plume {px}"

    def test_bearing_to_ground_truth_reasonable(self, seq_a):
        """Detection -> bearing -> compare with the known simulated source bearing."""
        d, cam = seq_a
        sc = demo_scenario()
        frames = discover_frames(d)
        det = ClassicSmokeDetector(confidence_threshold=0.3)
        idx = DEMO_SEQUENCE_A.plume_start + 28
        f = frames[idx]
        img, _ = load_frame(f)
        ref = FrameRef(sequence_id=DEMO_SEQUENCE_A.id, index=idx, filename=f.filename)
        dets = det.detect(img, ref, cam.id)
        assert dets
        best = max(dets, key=lambda x: x.confidence)
        px = (best.bbox.x1 + best.bbox.x2) / 2.0  # bottom-center x
        bearing = bearing_to_pixel.__module__  # noqa: F841 - keep import sanity
        from firesight.geometry.bearing import pixel_to_bearing

        est_bearing = pixel_to_bearing(
            px, image_width=cam.image_width, heading_deg=cam.heading_deg, hfov_deg=cam.hfov_deg
        )
        true_bearing = _true_bearing(cam, sc)
        diff = abs((est_bearing - true_bearing + 180) % 360 - 180)
        assert diff < 8.0, f"bearing error {diff:.1f} deg too large"


class TestDemoTriangulationLoop:
    def test_two_camera_end_to_end(self, seq_a, seq_b):
        """Projected plume in both cameras -> bearings -> triangulation near GT."""
        sc = demo_scenario()
        cams = sc.cameras
        frames_a = discover_frames(seq_a[0])
        frames_b = discover_frames(seq_b[0])
        idx_a = DEMO_SEQUENCE_A.plume_start + 25
        idx_b = DEMO_SEQUENCE_B.plume_start + 25
        obs = []
        det = ClassicSmokeDetector(confidence_threshold=0.3)
        for frames, cam, idx in ((frames_a, cams["sim-cam-a"], idx_a), (frames_b, cams["sim-cam-b"], idx_b)):
            f = frames[idx]
            img, _ = load_frame(f)
            ref = FrameRef(sequence_id="x", index=idx, filename=f.filename)
            dets = det.detect(img, ref, cam.id)
            best = max(dets, key=lambda d: d.confidence)
            px = (best.bbox.x1 + best.bbox.x2) / 2.0
            from firesight.geometry.bearing import pixel_to_bearing

            bearing = pixel_to_bearing(
                px, image_width=cam.image_width, heading_deg=cam.heading_deg, hfov_deg=cam.hfov_deg
            )
            obs.append(
                BearingObservation(
                    camera_id=cam.id,
                    bearing_deg=bearing,
                    pixel_x=px,
                    pixel_y=best.bbox.y2,
                    evidence_type=EvidenceType.SIMULATED_SECOND_CAMERA,
                    provenance=Provenance.PREDICTED,
                    confidence=best.confidence,
                    camera=cam,
                )
            )
        result = triangulate(obs, cams)
        assert result.latitude is not None, f"triangulation failed: {result.limitations}"
        err = _haversine(result.latitude, result.longitude, sc.ground_truth_lat, sc.ground_truth_lon)
        assert err < 800.0, f"demo triangulation error {err:.0f} m too large"
        assert result.uncertainty_m is not None and result.uncertainty_m > 0


def _haversine(lat1, lon1, lat2, lon2):
    from firesight.geometry.frames import geodesic_distance_m

    return geodesic_distance_m(lat1, lon1, lat2, lon2)
