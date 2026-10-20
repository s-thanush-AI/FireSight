import math

import pytest

from firesight.enums import CalibrationStatus, EvidenceType, GeometryQuality, Provenance
from firesight.geometry.bearing import (
    bearing_to_pixel,
    compass_point,
    normalize_bearing,
    pixel_to_bearing,
    proxy_point_from_bbox,
)
from firesight.geometry.frames import enu_to_latlon, geodesic_distance_m, latlon_to_enu
from firesight.geometry.triangulation import CartesianRay, ray_from_camera, triangulate
from firesight.geometry.uncertainty import bearing_sigma_deg, propagate_position_sigma_m
from firesight.models import BearingObservation, CameraConfig


def make_camera(
    cam_id: str,
    lat: float,
    lon: float,
    heading: float,
    hfov: float = 60.0,
    width: int = 640,
    status: CalibrationStatus = CalibrationStatus.CALIBRATED,
) -> CameraConfig:
    return CameraConfig(
        id=cam_id,
        name=cam_id,
        latitude=lat,
        longitude=lon,
        height_m=10.0,
        heading_deg=heading,
        hfov_deg=hfov,
        image_width=width,
        image_height=360,
        calibration_status=status,
        provenance=Provenance.MANUAL,
    )


def obs(cam_id: str, bearing: float, cam: CameraConfig) -> BearingObservation:
    return BearingObservation(
        camera_id=cam_id,
        bearing_deg=bearing,
        pixel_x=320.0,
        pixel_y=180.0,
        evidence_type=EvidenceType.REAL_UNPAIRED,
        provenance=Provenance.PREDICTED,
        camera=cam,
    )


class TestBearingBasics:
    def test_normalize(self):
        assert normalize_bearing(0) == 0.0
        assert normalize_bearing(360) == 0.0
        assert normalize_bearing(-90) == 270.0
        assert normalize_bearing(450) == 90.0

    def test_center_pixel_is_heading(self):
        assert pixel_to_bearing(320, image_width=640, heading_deg=45, hfov_deg=60) == pytest.approx(45)

    def test_right_of_centre_increases_bearing(self):
        b = pixel_to_bearing(480, image_width=640, heading_deg=0, hfov_deg=90)
        assert b == pytest.approx(22.5)

    def test_left_edge_is_heading_minus_half_hfov(self):
        b = pixel_to_bearing(0, image_width=640, heading_deg=0, hfov_deg=60)
        assert b == pytest.approx(330.0)

    def test_round_trip(self):
        for px in (0, 100, 320, 500, 639):
            b = pixel_to_bearing(px, image_width=640, heading_deg=30, hfov_deg=55)
            px2 = bearing_to_pixel(b, image_width=640, heading_deg=30, hfov_deg=55)
            assert px2 == pytest.approx(px, abs=1e-6)

    def test_outside_fov_returns_none(self):
        assert bearing_to_pixel(180, image_width=640, heading_deg=0, hfov_deg=60) is None

    def test_invalid_inputs(self):
        with pytest.raises(ValueError):
            pixel_to_bearing(10, image_width=0, heading_deg=0, hfov_deg=60)
        with pytest.raises(ValueError):
            pixel_to_bearing(10, image_width=640, heading_deg=0, hfov_deg=0)

    def test_proxy_points(self):
        assert proxy_point_from_bbox(0, 0, 100, 50, "bottom_center") == (50.0, 50.0)
        assert proxy_point_from_bbox(0, 0, 100, 50, "center") == (50.0, 25.0)
        with pytest.raises(ValueError):
            proxy_point_from_bbox(0, 0, 1, 1, "top")

    def test_compass_point(self):
        assert compass_point(0) == "N"
        assert compass_point(90) == "E"
        assert compass_point(45) == "NE"

    def test_wrapped_heading(self):
        # heading 350, pixel right of centre -> 350 + 10 = 0 after wrap
        b = pixel_to_bearing(640, image_width=640, heading_deg=350, hfov_deg=20)
        assert b == pytest.approx(0.0)


class TestFrames:
    def test_enu_round_trip(self):
        olat, olon = 37.0, -119.5
        for lat, lon in [(37.0, -119.5), (37.01, -119.49), (36.98, -119.52)]:
            e, n = latlon_to_enu(lat, lon, olat, olon)
            lat2, lon2 = enu_to_latlon(e, n, olat, olon)
            assert lat2 == pytest.approx(lat, abs=1e-9)
            assert lon2 == pytest.approx(lon, abs=1e-9)

    def test_known_north_offset(self):
        # 0.01 deg latitude ~ 1111.9 m north
        e, n = latlon_to_enu(37.01, -119.5, 37.0, -119.5)
        assert e == pytest.approx(0.0, abs=1.0)
        assert n == pytest.approx(1111.9, rel=0.01)

    def test_known_east_offset(self):
        # 0.01 deg longitude at lat 37 ~ 888 m east
        e, n = latlon_to_enu(37.0, -119.49, 37.0, -119.5)
        assert n == pytest.approx(0.0, abs=1.0)
        assert e == pytest.approx(888.0, rel=0.02)

    def test_geodesic(self):
        d = geodesic_distance_m(37.0, -119.5, 37.0, -119.49)
        assert d == pytest.approx(888.0, rel=0.02)
        assert geodesic_distance_m(37.0, -119.5, 37.0, -119.5) == pytest.approx(0.0, abs=0.5)


class TestRayMath:
    def test_ray_direction_convention(self):
        r = ray_from_camera(0, 0, 90, "a")
        assert r.direction_e == pytest.approx(1.0)
        assert r.direction_n == pytest.approx(0.0)
        r = ray_from_camera(0, 0, 0, "a")
        assert r.direction_e == pytest.approx(0.0)
        assert r.direction_n == pytest.approx(1.0)


class TestUncertainty:
    def test_bearing_sigma(self):
        # pixel noise 1% of width, hfov 60 -> 0.3 deg; heading 1.5 -> hypot
        s = bearing_sigma_deg(60.0, 640, 0.01, 1.5)
        assert s == pytest.approx(math.hypot(0.3, 1.5), rel=1e-6)

    def test_position_sigma_grows_as_parallel(self):
        s_open = propagate_position_sigma_m([1000.0], [1.0], 90.0)
        s_tight = propagate_position_sigma_m([1000.0], [1.0], 10.0)
        assert s_tight > s_open * 5
        assert math.isinf(propagate_position_sigma_m([1000.0], [1.0], 0.0))

    def test_position_sigma_value(self):
        # R=1000, sigma_b=1deg, theta=90 -> 1000 * pi/180 = 17.45 m
        assert propagate_position_sigma_m([1000.0], [1.0], 90.0) == pytest.approx(17.45, rel=1e-2)

    def test_bad_args(self):
        with pytest.raises(ValueError):
            propagate_position_sigma_m([], [], 90.0)
        with pytest.raises(ValueError):
            propagate_position_sigma_m([1.0], [1.0, 2.0], 90.0)


class TestTriangulation:
    def test_hand_computed_east_north_crossing(self):
        """Camera A at ENU(0,0) heading east; camera B at ENU(1000,1000) heading south.

        The east line from A (n=0) and the south line from B (e=1000) cross at
        (1000, 0): due east of A, due south of B. Both rays have range 1000 m.
        """
        olat, olon = 37.0, -119.5
        a_lat, a_lon = enu_to_latlon(0, 0, olat, olon)
        b_lat, b_lon = enu_to_latlon(1000, 1000, olat, olon)
        cam_a = make_camera("A", a_lat, a_lon, heading=90.0)
        cam_b = make_camera("B", b_lat, b_lon, heading=180.0)
        result = triangulate([obs("A", 90.0, cam_a), obs("B", 180.0, cam_b)], {"A": cam_a, "B": cam_b})
        assert result.quality in (GeometryQuality.STRONG, GeometryQuality.ACCEPTABLE)
        assert result.latitude is not None and result.longitude is not None
        e, n = latlon_to_enu(result.latitude, result.longitude, olat, olon)
        assert e == pytest.approx(1000.0, abs=2.0)
        assert n == pytest.approx(0.0, abs=2.0)
        assert result.ray_separation_deg == pytest.approx(90.0, abs=0.1)
        assert result.fit_residual_m == pytest.approx(0.0, abs=0.5)
        assert result.distances_per_camera_m["A"] == pytest.approx(1000.0, rel=0.01)
        assert result.distances_per_camera_m["B"] == pytest.approx(1000.0, rel=0.01)

    def test_hand_computed_ne_se_crossing(self):
        """A at (0,0) bearing NE (45); B at (0,1000) bearing SE (135) meet at (500,500)."""
        olat, olon = 37.0, -119.5
        a_lat, a_lon = enu_to_latlon(0, 0, olat, olon)
        b_lat, b_lon = enu_to_latlon(0, 1000, olat, olon)
        cam_a = make_camera("A", a_lat, a_lon, heading=45.0)
        cam_b = make_camera("B", b_lat, b_lon, heading=135.0)
        result = triangulate([obs("A", 45.0, cam_a), obs("B", 135.0, cam_b)], {"A": cam_a, "B": cam_b})
        e, n = latlon_to_enu(result.latitude, result.longitude, olat, olon)
        assert e == pytest.approx(500.0, abs=2.0)
        assert n == pytest.approx(500.0, abs=2.0)

    def test_near_parallel_rejected(self):
        olat, olon = 37.0, -119.5
        a_lat, a_lon = enu_to_latlon(0, 0, olat, olon)
        b_lat, b_lon = enu_to_latlon(0, 1000, olat, olon)
        cam_a = make_camera("A", a_lat, a_lon, heading=0.0)
        cam_b = make_camera("B", b_lat, b_lon, heading=1.0)
        result = triangulate([obs("A", 0.0, cam_a), obs("B", 1.0, cam_b)], {"A": cam_a, "B": cam_b})
        assert result.quality == GeometryQuality.REJECTED
        assert result.latitude is None
        assert any("parallel" in lim or "separation" in lim for lim in result.limitations)

    def test_behind_camera_rejected(self):
        olat, olon = 37.0, -119.5
        a_lat, a_lon = enu_to_latlon(0, 0, olat, olon)
        b_lat, b_lon = enu_to_latlon(0, 1000, olat, olon)
        # B points north (away from intersection at (1000,0) which is south of B)
        cam_a = make_camera("A", a_lat, a_lon, heading=90.0)
        cam_b = make_camera("B", b_lat, b_lon, heading=0.0)
        result = triangulate([obs("A", 90.0, cam_a), obs("B", 0.0, cam_b)], {"A": cam_a, "B": cam_b})
        assert result.quality == GeometryQuality.REJECTED
        assert any("behind camera" in lim for lim in result.limitations)

    def test_uncalibrated_camera_unavailable(self):
        olat, olon = 37.0, -119.5
        a_lat, a_lon = enu_to_latlon(0, 0, olat, olon)
        b_lat, b_lon = enu_to_latlon(0, 1000, olat, olon)
        cam_a = make_camera("A", a_lat, a_lon, 90.0, status=CalibrationStatus.UNCALIBRATED)
        cam_b = make_camera("B", b_lat, b_lon, 180.0)
        result = triangulate([obs("A", 90.0, cam_a), obs("B", 180.0, cam_b)], {"A": cam_a, "B": cam_b})
        assert result.quality == GeometryQuality.UNAVAILABLE
        assert any("not calibrated" in lim for lim in result.limitations)

    def test_single_observation_unavailable(self):
        cam = make_camera("A", 37.0, -119.5, 0.0)
        result = triangulate([obs("A", 10.0, cam)], {"A": cam})
        assert result.quality == GeometryQuality.UNAVAILABLE

    def test_missing_camera_config_unavailable(self):
        cam = make_camera("A", 37.0, -119.5, 0.0)
        result = triangulate([obs("A", 10.0, cam), obs("B", 20.0, cam)], {"A": cam})
        assert result.quality == GeometryQuality.UNAVAILABLE

    def test_too_far_rejected(self):
        olat, olon = 37.0, -119.5
        a_lat, a_lon = enu_to_latlon(0, 0, olat, olon)
        b_lat, b_lon = enu_to_latlon(100_000, 100_000, olat, olon)
        cam_a = make_camera("A", a_lat, a_lon, 90.0)
        cam_b = make_camera("B", b_lat, b_lon, 180.0)
        result = triangulate(
            [obs("A", 90.0, cam_a), obs("B", 180.0, cam_b)],
            {"A": cam_a, "B": cam_b},
            max_distance_m=50_000.0,
        )
        assert result.quality == GeometryQuality.REJECTED
        assert any("maximum" in lim for lim in result.limitations)

    def test_three_camera_lsq(self):
        olat, olon = 37.0, -119.5
        target = (2000.0, 1500.0)
        cams = {}
        bearings = []
        for cam_id, (e, n), heading in [
            ("A", (0, 0), 50.9),
            ("B", (4000, 0), 315.0),
            ("C", (2000, -500), 0.0),
        ]:
            lat, lon = enu_to_latlon(e, n, olat, olon)
            # true bearing to target
            true_bearing = math.degrees(math.atan2(target[0] - e, target[1] - n)) % 360
            cam = make_camera(cam_id, lat, lon, heading)
            cams[cam_id] = cam
            bearings.append(obs(cam_id, true_bearing, cam))
        result = triangulate(bearings, cams)
        assert result.quality in (GeometryQuality.STRONG, GeometryQuality.ACCEPTABLE)
        e, n = latlon_to_enu(result.latitude, result.longitude, olat, olon)
        assert e == pytest.approx(target[0], abs=5.0)
        assert n == pytest.approx(target[1], abs=5.0)
        assert result.uncertainty_m is not None and result.uncertainty_m > 0

    def test_simulated_calibration_noted(self):
        olat, olon = 37.0, -119.5
        a_lat, a_lon = enu_to_latlon(0, 0, olat, olon)
        b_lat, b_lon = enu_to_latlon(0, 1000, olat, olon)
        cam_a = make_camera("A", a_lat, a_lon, 90.0, status=CalibrationStatus.SIMULATED)
        cam_b = make_camera("B", b_lat, b_lon, 180.0, status=CalibrationStatus.SIMULATED)
        result = triangulate([obs("A", 90.0, cam_a), obs("B", 180.0, cam_b)], {"A": cam_a, "B": cam_b})
        assert result.quality in (GeometryQuality.STRONG, GeometryQuality.ACCEPTABLE)
        assert any("simulated" in lim for lim in result.limitations)

    def test_low_separation_inflates_uncertainty(self):
        """A shallow crossing must carry clearly larger uncertainty than an open one."""
        olat, olon = 37.0, -119.5
        a_lat, a_lon = enu_to_latlon(0, 0, olat, olon)
        b_lat, b_lon = enu_to_latlon(0, 2000, olat, olon)
        cam_a = make_camera("A", a_lat, a_lon, 90.0)
        cam_b = make_camera("B", b_lat, b_lon, 180.0)
        cams = {"A": cam_a, "B": cam_b}

        def bearing_to(e: float, n: float, from_e: float, from_n: float) -> float:
            return math.degrees(math.atan2(e - from_e, n - from_n)) % 360.0

        # open geometry: target at (3000, 1000) -> ~36.8 deg intersection
        open_res = triangulate(
            [
                obs("A", bearing_to(3000, 1000, 0, 0), cam_a),
                obs("B", bearing_to(3000, 1000, 0, 2000), cam_b),
            ],
            cams,
            min_separation_deg=4.0,
        )
        # shallow geometry: target at (15000, 1000) -> ~7.6 deg intersection
        shallow = triangulate(
            [
                obs("A", bearing_to(15000, 1000, 0, 0), cam_a),
                obs("B", bearing_to(15000, 1000, 0, 2000), cam_b),
            ],
            cams,
            min_separation_deg=4.0,
        )
        assert open_res.quality in (GeometryQuality.STRONG, GeometryQuality.ACCEPTABLE)
        assert shallow.quality in (GeometryQuality.WEAK, GeometryQuality.ACCEPTABLE)
        assert shallow.ray_separation_deg is not None and shallow.ray_separation_deg < 12
        assert open_res.uncertainty_m is not None and shallow.uncertainty_m is not None
        assert shallow.uncertainty_m > 5 * open_res.uncertainty_m
        assert any("low" in lim or "grows" in lim for lim in shallow.limitations)

    def test_min_separation_gate_rejects(self):
        olat, olon = 37.0, -119.5
        a_lat, a_lon = enu_to_latlon(0, 0, olat, olon)
        b_lat, b_lon = enu_to_latlon(0, 2000, olat, olon)
        cam_a = make_camera("A", a_lat, a_lon, 90.0)
        cam_b = make_camera("B", b_lat, b_lon, 180.0)
        result = triangulate(
            [obs("A", 80.0, cam_a), obs("B", 100.0, cam_b)],
            {"A": cam_a, "B": cam_b},
            min_separation_deg=25.0,
        )
        assert result.quality == GeometryQuality.REJECTED
        assert any("separation" in lim for lim in result.limitations)


class TestCartesianRay:
    def test_immutable(self):
        from dataclasses import FrozenInstanceError

        r = CartesianRay(0, 0, 1, 0, "x")
        with pytest.raises(FrozenInstanceError):
            r.origin_e = 5  # type: ignore[misc]
