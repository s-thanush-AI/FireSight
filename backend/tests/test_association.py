from datetime import UTC, datetime, timedelta

from firesight.association.associate import associate_observations
from firesight.enums import CalibrationStatus, EvidenceType, GeometryQuality, Provenance
from firesight.geometry.frames import enu_to_latlon
from firesight.models import BearingObservation, CameraConfig

T0 = datetime(2024, 7, 12, 15, 30, 0, tzinfo=UTC)
ORIGIN = (37.0, -119.5)


def cam(cam_id, e, n, heading, status=CalibrationStatus.CALIBRATED, prov=Provenance.MANUAL):
    lat, lon = enu_to_latlon(e, n, *ORIGIN)
    return CameraConfig(
        id=cam_id, name=cam_id, latitude=lat, longitude=lon, height_m=5.0,
        heading_deg=heading, hfov_deg=60.0, image_width=640, image_height=360,
        calibration_status=status, provenance=prov,
    )


def bearing_obs(camera, bearing, ts, evidence=EvidenceType.REAL_UNPAIRED, prov=Provenance.PREDICTED):
    return BearingObservation(
        camera_id=camera.id, bearing_deg=bearing,
        timestamp=ts.isoformat() if ts is not None else None,
        pixel_x=320, pixel_y=180, evidence_type=evidence, provenance=prov, camera=camera,
    )


def setup_pair():
    a = cam("A", 0, 0, 90.0)
    b = cam("B", 1000, 1000, 180.0)
    return {"A": a, "B": b}


class TestAssociation:
    def test_valid_pair(self):
        cams = setup_pair()
        left = [bearing_obs(cams["A"], 90.0, T0)]
        right = [bearing_obs(cams["B"], 180.0, T0 + timedelta(seconds=0.5))]
        result = associate_observations(left, right, cams, timestamp_tolerance_s=2.0)
        pairs = [r for r in result if r.valid]
        assert len(pairs) == 1
        p = pairs[0]
        assert p.evidence_type == EvidenceType.REAL_PAIRED
        assert p.timestamp_delta_s == 0.5
        assert p.triangulation.quality in (GeometryQuality.STRONG, GeometryQuality.ACCEPTABLE)

    def test_outside_tolerance_unpaired(self):
        cams = setup_pair()
        left = [bearing_obs(cams["A"], 90.0, T0)]
        right = [bearing_obs(cams["B"], 180.0, T0 + timedelta(seconds=10))]
        result = associate_observations(left, right, cams, timestamp_tolerance_s=2.0)
        unpaired = [r for r in result if not r.valid]
        assert unpaired
        assert unpaired[0].evidence_type == EvidenceType.REAL_UNPAIRED
        assert "no partner" in unpaired[0].reason

    def test_simulated_evidence_type(self):
        cams = setup_pair()
        left = [bearing_obs(cams["A"], 90.0, T0, prov=Provenance.SIMULATED)]
        right = [bearing_obs(cams["B"], 180.0, T0, prov=Provenance.SIMULATED)]
        result = associate_observations(left, right, cams)
        assert result[0].evidence_type == EvidenceType.SIMULATED_SECOND_CAMERA
        # geometry itself is genuine regardless of provenance
        assert result[0].valid
        assert result[0].triangulation.latitude is not None

    def test_nearest_in_time_wins(self):
        cams = setup_pair()
        left = [bearing_obs(cams["A"], 90.0, T0)]
        right = [
            bearing_obs(cams["B"], 180.0, T0 + timedelta(seconds=1.8)),
            bearing_obs(cams["B"], 180.0, T0 + timedelta(seconds=0.2)),
        ]
        result = associate_observations(left, right, cams, timestamp_tolerance_s=2.0)
        valid = [r for r in result if r.valid]
        assert len(valid) == 1
        assert valid[0].timestamp_delta_s == 0.2

    def test_same_camera_not_paired(self):
        cams = setup_pair()
        left = [bearing_obs(cams["A"], 90.0, T0)]
        right = [bearing_obs(cams["A"], 91.0, T0)]
        result = associate_observations(left, right, cams)
        assert all(not r.valid for r in result)

    def test_incompatible_bearings_invalid(self):
        cams = setup_pair()
        # B points north (away); residual/behind-camera must fail validation
        cams["B"] = cam("B", 1000, 1000, 0.0)
        left = [bearing_obs(cams["A"], 90.0, T0)]
        right = [bearing_obs(cams["B"], 0.0, T0)]
        result = associate_observations(left, right, cams)
        assert result
        assert all(not r.valid for r in result)

    def test_missing_timestamps_yield_unpaired(self):
        cams = setup_pair()
        left = [bearing_obs(cams["A"], 90.0, None)]
        right = [bearing_obs(cams["B"], 180.0, None)]
        result = associate_observations(left, right, cams)
        assert all(not r.valid for r in result)
        assert all(r.timestamp_delta_s is None for r in result)
