"""API tests: health, config, sequences, replay control, incidents, cameras,
geometry, evaluation, verification, inference and dataset path safety.

Uses TestClient with an isolated temp data root and database. Replay sessions
are created with a very slow speed so frames advance only when we step them
explicitly (deterministic tests).
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from firesight.api.app import create_app
from firesight.config import Settings
from firesight.services.context import AppContext, set_context

SLOW_SPEED = 0.1  # frames would advance every 10s; tests drive frames via /step


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        mode="demo",
        data_root=tmp_path / "data",
        models_root=tmp_path / "models",
        database_url=f"sqlite:///{tmp_path}/test.db",
    )


@pytest.fixture()
def app(tmp_path) -> FastAPI:
    ctx = AppContext(_settings(tmp_path))
    application = create_app(ctx)
    yield application
    ctx.shutdown()
    set_context(None)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def _create_replay(client, sequence_id: str) -> dict:
    r = client.post("/api/v1/replays", json={"sequence_id": sequence_id, "speed": SLOW_SPEED})
    assert r.status_code == 200, r.text
    return r.json()


def _step(client, replay_id: str, n: int) -> dict:
    r = client.post(f"/api/v1/replays/{replay_id}/step?n={n}")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def module_probe(tmp_path_factory):
    """Cheap sanity that demo sequences exist for the module (generated per test here)."""
    return tmp_path_factory.mktemp("probe")


class TestHealthStatusConfig:
    def test_health(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["mode"] == "demo"
        assert body["version"]

    def test_status_shape(self, client):
        r = client.get("/api/v1/status")
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "demo"
        assert body["demo_banner"] is True
        assert body["detector"]["available"] is True
        assert body["detector"]["provenance"] == "predicted"
        assert body["vlm"]["api_key_present"] in (True, False)
        assert body["simulated_data_notice"]
        assert isinstance(body["incidents_by_status"], dict)

    def test_config_never_exposes_secrets(self, client):
        r = client.get("/api/v1/config")
        assert r.status_code == 200
        body = r.json()
        flat = str(body)
        assert "sk-" not in flat
        # VLM key must appear only as a presence flag, never the value
        vlm_section = body["settings"].get("vlm", {})
        key = vlm_section.get("api_key")
        assert key in (None, "", "***") or not isinstance(key, str) or key == "***"
        assert "api_key" not in "".join(body["overrides"].keys())

    def test_config_override_roundtrip(self, client):
        r = client.put(
            "/api/v1/config",
            json={"values": {"temporal.min_positive_observations": 4}},
        )
        assert r.status_code == 200
        assert r.json()["settings"]["temporal"]["min_positive_observations"] == 4
        r2 = client.put("/api/v1/config", json={"values": {"nope_unknown": 1}})
        assert r2.status_code == 422


class TestSequencesDatasets:
    def test_demo_sequences_registered(self, client):
        r = client.get("/api/v1/sequences")
        assert r.status_code == 200
        body = r.json()
        ids = {i["id"] for i in body["items"]}
        assert "demo-alpha-ridge" in ids
        assert "demo-bravo-ridge" in ids
        for item in body["items"]:
            if item["id"].startswith("demo-"):
                assert item["provenance"] == "simulated"
                assert item["dataset_provenance"] == "simulated"
                assert item["frame_count"] == 50

    def test_sequence_detail_and_404(self, client):
        r = client.get("/api/v1/sequences/demo-alpha-ridge")
        assert r.status_code == 200
        assert r.json()["first_frames"], "frame discovery should return frames"
        assert client.get("/api/v1/sequences/nope").status_code == 404

    def test_datasets_listing(self, client):
        r = client.get("/api/v1/datasets")
        assert r.status_code == 200
        body = r.json()
        assert body["data_root_exists"] is True
        assert body["docs"]["figlib"].startswith("https://")

    def test_inspect_rejects_path_traversal(self, client):
        for bad in ("../", "/etc", "data/../../etc", "../../secret"):
            r = client.post("/api/v1/datasets/inspect", json={"path": bad})
            assert r.status_code == 422, f"path {bad!r} should be rejected"

    def test_inspect_valid_relative_path(self, client):
        r = client.post("/api/v1/datasets/inspect", json={"path": "demo", "name": "demo"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("safety") is None or "path" in str(body).lower()


class TestReplayLifecycle:
    def test_replay_create_step_frame_and_controls(self, client):
        created = _create_replay(client, "demo-alpha-ridge")
        rid = created["id"]
        assert created["status"] in ("idle", "running")
        assert created["provenance"] == "simulated"

        listed = client.get("/api/v1/replays").json()
        assert any(i["id"] == rid for i in listed["items"])

        meta = _step(client, rid, 15)
        assert meta["frame"] is not None or meta["status"]["frame_index"] >= 1

        cur = client.get(f"/api/v1/replays/{rid}/frames/current").json()
        assert cur["image_jpeg_base64"], "annotated frame should be produced"
        assert cur["frame"]["index"] >= 14

        assert client.post(f"/api/v1/replays/{rid}/pause").status_code == 200
        assert client.get(f"/api/v1/replays/{rid}").json()["status"] == "paused"
        assert client.post(f"/api/v1/replays/{rid}/resume").status_code == 200
        assert client.post(f"/api/v1/replays/{rid}/reset").status_code == 200
        assert client.get(f"/api/v1/replays/{rid}").json()["frame_index"] == 0

    def test_unknown_replay_404(self, client):
        assert client.get("/api/v1/replays/rp_missing").status_code == 404
        assert client.post("/api/v1/replays/rp_missing/step").status_code == 404

    def test_unknown_sequence_create_422(self, client):
        r = client.post("/api/v1/replays", json={"sequence_id": "not-a-sequence"})
        assert r.status_code == 422

    def test_finished_replays_do_not_consume_concurrency_slots(self, client):
        replay_ids = [_create_replay(client, "demo-alpha-ridge")["id"] for _ in range(8)]

        blocked = client.post("/api/v1/replays", json={"sequence_id": "demo-alpha-ridge"})
        assert blocked.status_code == 422
        assert "Maximum number of concurrent replays (8) reached" in blocked.text

        _step(client, replay_ids[0], 50)
        assert client.get(f"/api/v1/replays/{replay_ids[0]}").json()["status"] == "finished"

        created = client.post("/api/v1/replays", json={"sequence_id": "demo-alpha-ridge"})
        assert created.status_code == 200, created.text

    def test_replay_events_streamed(self, client):
        rid = _create_replay(client, "demo-alpha-ridge")["id"]
        _step(client, rid, 20)
        r = client.get(f"/api/v1/replays/{rid}/events")
        assert r.status_code == 200
        assert r.json()["total"] >= 1


class TestIncidentFlow:
    def test_pipeline_creates_and_updates_incident(self, client):
        # Drive one camera far enough for the temporal tracker to confirm a track.
        rid = _create_replay(client, "demo-alpha-ridge")["id"]
        _step(client, rid, 45)

        r = client.get("/api/v1/incidents")
        assert r.status_code == 200
        items = r.json()["items"]
        assert items, "temporal confirmation should create at least one incident"
        inc = items[0]
        assert inc["status"] in ("candidate", "confirmed", "reviewed")
        assert inc["provenance"] in ("simulated", "predicted")
        assert inc["first_seen_ts"]

        detail = client.get(f"/api/v1/incidents/{inc['id']}").json()
        assert detail["incident"]["id"] == inc["id"]
        assert "history" in detail and "observations" in detail

        # Human action on the incident.
        p = client.patch(
            f"/api/v1/incidents/{inc['id']}", json={"action": "acknowledge", "reason": "reviewed"}
        )
        assert p.status_code == 200
        assert p.json()["status"] == "acknowledged"

        rep = client.get(f"/api/v1/reports/{inc['id']}")
        assert rep.status_code == 200
        assert rep.json()["incident"]["id"] == inc["id"]

        dl = client.get(f"/api/v1/reports/{inc['id']}/download?format=csv")
        assert dl.status_code == 200
        assert "text/csv" in dl.headers["content-type"]

        zb = client.get(f"/api/v1/reports/{inc['id']}/download?format=zip")
        assert zb.status_code == 200
        assert "application/zip" in zb.headers["content-type"]
        assert zb.content[:2] == b"PK"

        bad = client.patch(
            f"/api/v1/incidents/{inc['id']}", json={"action": "not-a-action"}
        )
        assert bad.status_code == 422
        assert client.get("/api/v1/incidents/does-not-exist").status_code == 404

    def test_incident_filters(self, client):
        rid = _create_replay(client, "demo-alpha-ridge")["id"]
        _step(client, rid, 30)
        r = client.get("/api/v1/incidents", params={"provenance": "simulated", "limit": 5})
        assert r.status_code == 200
        for item in r.json()["items"]:
            assert item["provenance"] == "simulated"


class TestCameras:
    def test_list_contains_demo_cameras(self, client):
        r = client.get("/api/v1/cameras")
        assert r.status_code == 200
        body = r.json()
        ids = {c["id"] for c in body["items"]}
        assert {"sim-cam-a", "sim-cam-b"} <= ids
        assert body["notice"]

    def test_crud_and_validation(self, client):
        valid = {
            "id": "test-cam-1",
            "name": "Test camera",
            "latitude": 37.3,
            "longitude": -119.6,
            "height_m": 12.0,
            "heading_deg": 45.0,
            "hfov_deg": 60.0,
            "image_width": 1920,
            "image_height": 1080,
            "calibration_status": "simulated",
            "provenance": "simulated",
        }
        assert client.post("/api/v1/cameras", json=valid).status_code == 201
        assert client.post("/api/v1/cameras", json=valid).status_code == 409
        assert client.get("/api/v1/cameras/test-cam-1").status_code == 200
        assert (
            client.put("/api/v1/cameras/test-cam-1", json={**valid, "id": "other"})
            .status_code == 422
        )
        upd = client.put(
            "/api/v1/cameras/test-cam-1", json={**valid, "height_m": 14.0}
        )
        assert upd.status_code == 200
        assert upd.json()["height_m"] == 14.0

        # heading out of range rejected
        bad = {**valid, "id": "test-cam-2", "heading_deg": 400}
        assert client.post("/api/v1/cameras", json=bad).status_code == 422

        # calibrated requires a calibration_source
        calib = {**valid, "id": "test-cam-3", "calibration_status": "calibrated"}
        r = client.post("/api/v1/cameras", json=calib)
        assert r.status_code == 422
        calib["calibration_source"] = "checkerboard 2026-10-01"
        assert client.post("/api/v1/cameras", json=calib).status_code == 201

        assert client.get("/api/v1/cameras/nope").status_code == 404


class TestGeometry:
    def test_geometry_layers(self, client):
        r = client.get("/api/v1/geometry")
        assert r.status_code == 200
        body = r.json()
        assert len(body["cameras"]) >= 2
        assert body["notice"]
        assert body["conventions"]["bearing"]
        assert isinstance(body["observations"], list)
        assert isinstance(body["triangulations"], list)


class TestEvaluation:
    def test_run_demo_fixture_evaluation(self, client):
        r = client.post(
            "/api/v1/evaluation/runs", json={"name": "api test", "kind": "demo_fixture"}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["provenance"] == "simulated"
        assert body["metric_count"] >= 1

        run = client.get(f"/api/v1/evaluation/runs/{body['run_id']}").json()
        metrics = run["metrics"]
        assert metrics, "run should contain metrics"
        # Every metric must carry either a numeric value or an explicit reason.
        for m in metrics:
            if m["value"] is None:
                assert m.get("limitation"), m

        runs = client.get("/api/v1/evaluation/runs")
        assert runs.status_code == 200
        assert runs.json()["total"] >= 1
        assert client.get("/api/v1/evaluation/runs/nope").status_code == 404

        m = client.get("/api/v1/evaluation/metrics").json()
        assert m["definitions"] and m["honesty_notice"]
        assert client.post(
            "/api/v1/evaluation/runs", json={"name": "x", "kind": "unknown_kind"}
        ).status_code == 422


class TestVerification:
    def test_vlm_verification_stored_and_labeled(self, client):
        rid = _create_replay(client, "demo-alpha-ridge")["id"]
        _step(client, rid, 45)
        items = client.get("/api/v1/incidents").json()["items"]
        assert items, "need an incident to verify"
        inc_id = items[0]["id"]

        r = client.post(f"/api/v1/verification/{inc_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["provider"]
        assert body["status"] in ("simulated", "ok", "disabled", "error")
        if body["status"] == "simulated":
            assert body["provenance"] == "simulated"
            assert body["assessment"] in ("likely_smoke", "uncertain", "likely_not_smoke")

        listed = client.get(f"/api/v1/verification/{inc_id}").json()
        assert listed["total"] >= 1
        assert listed["provenance_notice"]
        assert client.post("/api/v1/verification/nope").status_code == 404


class TestInference:
    def test_single_frame_inference(self, client):
        r = client.post(
            "/api/v1/inference", json={"sequence_id": "demo-alpha-ridge", "frame_index": 30}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["detector"]["available"] is True
        assert isinstance(body["detections"], list)
        assert body["annotated_jpeg_base64"]
        assert body["provenance"] == "simulated"
        assert body["notice"]

    def test_inference_errors(self, client):
        r = client.post(
            "/api/v1/inference", json={"sequence_id": "missing-seq", "frame_index": 0}
        )
        assert r.status_code == 404
        r2 = client.post(
            "/api/v1/inference", json={"sequence_id": "demo-alpha-ridge", "frame_index": 9999}
        )
        assert r2.status_code == 422


class TestWebSocket:
    def test_replay_ws_streams_frames_and_accepts_step(self, client):
        rid = _create_replay(client, "demo-alpha-ridge")["id"]
        with client.websocket_connect(f"/api/v1/ws/replays/{rid}") as ws:
            ws.send_text(json.dumps({"action": "step", "n": 20}))
            seen: list[str] = []
            frame_indexes: list[int] = []
            for _ in range(20):
                msg = ws.receive_json()
                seen.append(msg["type"])
                if msg["type"] == "frame":
                    idx = msg["data"]["frame"]["index"]
                    frame_indexes.append(idx)
                if "status" in seen and frame_indexes and len(seen) >= 4:
                    break
            assert "status" in seen
            assert frame_indexes, "expected at least one frame over the socket"
            assert max(frame_indexes) >= 1

    def test_replay_ws_unknown_replay_errors(self, client):
        with client.websocket_connect("/api/v1/ws/replays/rp_missing") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"


class TestModelsEndpoint:
    def test_models_and_training_declared(self, client):
        r = client.get("/api/v1/models")
        assert r.status_code == 200
        body = r.json()
        names = {d["name"] for d in body["detectors"]}
        assert "classic" in names or "yolo" in names
        for d in body["detectors"]:
            if d.get("unavailable_reason"):
                assert len(d["unavailable_reason"]) > 10
        assert body["training"]["available"] is True
        assert "explicit" in body["vlm"]["note"].lower() or "request" in body["vlm"]["note"].lower()


def _write_frames(directory, names, size=(32, 24)) -> None:
    import cv2
    import numpy as np

    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        img = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        img[:] = (30, 60, 90)
        assert cv2.imwrite(str(directory / name), img)


class TestSequenceRegistration:
    def test_register_success_with_timestamps(self, client, tmp_path):
        frames_dir = tmp_path / "data" / "cctv1"
        _write_frames(
            frames_dir,
            [
                "2024-07-12_15-30-00_000000.png",
                "2024-07-12_15-30-01_000000.png",
                "2024-07-12_15-30-02_000000.png",
            ],
        )
        r = client.post(
            "/api/v1/sequences",
            json={"id": "cctv-ridge-1", "root_path": "cctv1", "name": "Ridge CCTV"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["id"] == "cctv-ridge-1"
        assert body["frame_count"] == 3
        assert body["provenance"] == "real"
        assert body["synthetic"] is False
        assert body["timestamps_available"] is True
        assert body["start_ts"].startswith("2024-07-12T15:30:00")
        assert body["end_ts"].startswith("2024-07-12T15:30:02")
        assert body["image_width"] == 32 and body["image_height"] == 24
        assert body["warnings"] == []

        listed = client.get("/api/v1/sequences").json()
        item = next(i for i in listed["items"] if i["id"] == "cctv-ridge-1")
        assert item["provenance"] == "real"
        assert item["synthetic"] is False

    def test_register_with_camera_and_dimension_warning(self, client, tmp_path):
        _write_frames(tmp_path / "data" / "cam", ["2024-07-12_15-30-00_000000.png"], size=(16, 16))
        cams = client.post(
            "/api/v1/cameras",
            json={
                "id": "cam-x",
                "name": "Cam X",
                "latitude": 40.0,
                "longitude": -120.0,
                "height_m": 10.0,
                "heading_deg": 90.0,
                "hfov_deg": 60.0,
                "image_width": 1920,
                "image_height": 1080,
                "calibration_status": "uncalibrated",
            },
        )
        assert cams.status_code in (200, 201), cams.text
        r = client.post(
            "/api/v1/sequences",
            json={"id": "cam-seq", "root_path": "cam", "camera_id": "cam-x"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["camera_id"] == "cam-x"
        assert any("dimensions" in w for w in body["warnings"])

    def test_register_missing_directory(self, client):
        r = client.post("/api/v1/sequences", json={"id": "nope", "root_path": "does-not-exist"})
        assert r.status_code == 422
        assert "does not exist" in r.json()["detail"].lower()

    def test_register_empty_directory(self, client, tmp_path):
        (tmp_path / "data" / "empty").mkdir(parents=True)
        (tmp_path / "data" / "empty" / "notes.txt").write_text("not an image")
        r = client.post("/api/v1/sequences", json={"id": "empty-seq", "root_path": "empty"})
        assert r.status_code == 422
        assert "no image files" in r.json()["detail"].lower()

    def test_register_rejects_absolute_and_traversal(self, client):
        for bad in ("/etc", "../outside", "data/../../etc", "../../secret"):
            r = client.post("/api/v1/sequences", json={"id": "escape", "root_path": bad})
            assert r.status_code == 422, f"path {bad!r} should be rejected"

    def test_register_rejects_symlink_escape(self, client, tmp_path):
        outside = tmp_path / "outside"
        _write_frames(outside, ["2024-07-12_15-30-00_000000.png"])
        link = tmp_path / "data" / "sneaky"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(outside, target_is_directory=True)
        r = client.post("/api/v1/sequences", json={"id": "sym", "root_path": "sneaky"})
        assert r.status_code == 422, r.text

    def test_register_invalid_camera(self, client, tmp_path):
        _write_frames(tmp_path / "data" / "c", ["2024-07-12_15-30-00_000000.png"])
        r = client.post(
            "/api/v1/sequences",
            json={"id": "c-seq", "root_path": "c", "camera_id": "ghost-camera"},
        )
        assert r.status_code == 404
        assert "unknown camera" in r.json()["detail"].lower()
        assert "c-seq" not in {i["id"] for i in client.get("/api/v1/sequences").json()["items"]}

    def test_register_duplicate_id_rejected(self, client, tmp_path):
        _write_frames(tmp_path / "data" / "d", ["2024-07-12_15-30-00_000000.png"])
        first = client.post("/api/v1/sequences", json={"id": "dup-seq", "root_path": "d"})
        assert first.status_code == 201
        second = client.post("/api/v1/sequences", json={"id": "dup-seq", "root_path": "d"})
        assert second.status_code == 409
        assert "already exists" in second.json()["detail"].lower()

    def test_register_does_not_overwrite_demo_sequence(self, client):
        r = client.post(
            "/api/v1/sequences",
            json={"id": "demo-alpha-ridge", "root_path": "demo"},
        )
        assert r.status_code == 409
        detail = client.get("/api/v1/sequences/demo-alpha-ridge")
        assert detail.status_code == 200
        assert detail.json()["frame_count"] == 50

    def test_register_unknown_timestamps_warns(self, client, tmp_path):
        _write_frames(tmp_path / "data" / "nots", ["frame_0001.png", "frame_0002.png"])
        r = client.post("/api/v1/sequences", json={"id": "nots-seq", "root_path": "nots"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["timestamps_available"] is False
        assert body["start_ts"] is None and body["end_ts"] is None
        assert any("unknown" in w.lower() for w in body["warnings"])

    def test_registered_sequence_is_replayable(self, client, tmp_path):
        _write_frames(
            tmp_path / "data" / "play",
            ["2024-07-12_15-30-00_000000.png", "2024-07-12_15-30-01_000000.png"],
        )
        reg = client.post("/api/v1/sequences", json={"id": "play-seq", "root_path": "play"})
        assert reg.status_code == 201, reg.text
        created = _create_replay(client, "play-seq")
        assert created["provenance"] == "real"
        meta = _step(client, created["id"], 1)
        assert meta["status"]["frame_index"] >= 1 or meta["frame"] is not None

    def test_register_invalid_id_pattern(self, client):
        r = client.post("/api/v1/sequences", json={"id": "bad id!", "root_path": "demo"})
        assert r.status_code == 422

    def test_register_requires_provenance_real(self, client):
        r = client.post(
            "/api/v1/sequences",
            json={"id": "p", "root_path": "demo", "provenance": "simulated"},
        )
        assert r.status_code == 422
