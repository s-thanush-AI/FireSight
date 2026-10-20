"""Video streaming/analysis, alerts and live-source regression tests."""

from __future__ import annotations

import time

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from firesight.api.app import create_app
from firesight.config import Settings
from firesight.datasets.figlib import figlib_onset_consistency, parse_figlib_filename
from firesight.services.context import AppContext, get_context, set_context
from firesight.services.live import sanitize_target


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


def _write_video(tmp_path, name: str = "test.mp4", frames: int = 24) -> None:
    out = tmp_path / "data" / "videos"
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 4.0, (320, 240)
    )
    assert writer.isOpened(), "OpenCV could not create a test MP4"
    for i in range(frames):
        img = np.full((240, 320, 3), 20, dtype=np.uint8)
        cv2.circle(img, (160, 80), 50 + i, (245, 245, 245), -1)
        writer.write(img)
    writer.release()
    assert path.is_file() and path.stat().st_size > 0


def test_figlib_filename_offsets_are_consistent() -> None:
    rows = parse_figlib_filename("1597353818_-02400.jpg")
    assert rows is not None
    assert rows["offset_s"] == -2400
    assert rows["plume_onset_epoch_s"] == 1597356218
    assert parse_figlib_filename("1597358618_+02400.JPG")["plume_onset_epoch_s"] == 1597356218
    assert parse_figlib_filename("not-a-figlib-frame.jpg") is None
    result = figlib_onset_consistency(["1597353818_-02400.jpg", "1597358618_+02400.jpg"])
    assert result["consistent"] is True


def test_video_range_streaming(client, tmp_path) -> None:
    _write_video(tmp_path)
    listed = client.get("/api/v1/videos")
    assert listed.status_code == 200, listed.text
    assert listed.json()["videos"][0]["id"] == "test"

    full = client.get("/api/v1/videos/test/stream")
    assert full.status_code == 200
    assert full.headers["accept-ranges"] == "bytes"
    assert len(full.content) == int(full.headers["content-length"])

    part = client.get("/api/v1/videos/test/stream", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206
    assert len(part.content) == 100
    assert part.headers["content-range"].startswith("bytes 0-99/")

    bad = client.get("/api/v1/videos/test/stream", headers={"Range": "bytes=99999999-"})
    assert bad.status_code == 416
    assert bad.headers["content-range"].startswith("bytes */")

    assert client.get("/api/v1/videos/missing/stream").status_code == 404


def test_video_analysis_writes_exports(client, tmp_path) -> None:
    _write_video(tmp_path)
    r = client.post(
        "/api/v1/videos/test/analyze",
        json={"sample_every_s": 0.25, "max_samples": 8, "min_consecutive": 2},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["frames_sampled"] <= 8
    assert body["detector"]["provenance"] == "predicted"
    assert body["verification_status"] == "experimental"
    assert body["timestamp_mapping"] == "not_verified"

    report = client.get(f"/api/v1/videos/test/analyses/{body['run_id']}/report")
    assert report.status_code == 200
    assert b"experimental" in report.content.lower()
    csv = client.get(f"/api/v1/videos/test/analyses/{body['run_id']}/detections.csv")
    assert csv.status_code == 200
    summary = client.get(f"/api/v1/videos/test/analyses/{body['run_id']}/summary")
    assert summary.status_code == 200
    assert summary.json()["run_id"] == body["run_id"]


def test_alert_lifecycle_and_dedupe(client) -> None:
    ctx = get_context()
    alert = ctx.alerts.create(
        source_type="test",
        source_id="unit",
        camera_id=None,
        event_time=None,
        detector_name="unit-detector",
        detector_version="0.0",
        confidence=0.9,
        evidence_jpeg=b"\xff\xd8\xff\xd9",
        dedupe_key="unit-dedupe",
        notes="unit test",
    )
    assert alert is not None
    assert ctx.alerts.create(
        source_type="test",
        source_id="unit",
        camera_id=None,
        event_time=None,
        detector_name="unit-detector",
        detector_version="0.0",
        confidence=0.9,
        dedupe_key="unit-dedupe",
    ) is None

    listed = client.get("/api/v1/alerts").json()
    assert any(a["id"] == alert["id"] for a in listed["alerts"])
    assert client.get(f"/api/v1/alerts/{alert['id']}/evidence").status_code == 200
    assert client.post(f"/api/v1/alerts/{alert['id']}/acknowledge").json()["status"] == "acknowledged"
    assert client.post(f"/api/v1/alerts/{alert['id']}/resolve").json()["status"] == "resolved"


def test_live_file_source(client, tmp_path) -> None:
    _write_video(tmp_path, frames=40)
    created = client.post(
        "/api/v1/live/sources",
        json={
            "name": "Local test clip",
            "kind": "file",
            "path": "videos/test.mp4",
            "sample_fps": 5,
            "threshold": 0.0,
            "min_consecutive": 1,
            "loop": False,
        },
    )
    assert created.status_code == 201, created.text
    source = created.json()
    assert source["target"] == "file:videos/test.mp4"
    assert source["experimental"] is True

    frame = None
    for _ in range(60):
        frame = client.get(f"/api/v1/live/sources/{source['id']}/frame")
        if frame.status_code == 200:
            break
        time.sleep(0.1)
    assert frame is not None and frame.status_code == 200
    assert frame.content.startswith(b"\xff\xd8")

    stopped = client.post(f"/api/v1/live/sources/{source['id']}/stop").json()
    assert stopped["status"] == "stopped"
    assert client.delete(f"/api/v1/live/sources/{source['id']}").status_code == 204


def test_live_rejects_traversal_and_credentials_are_hidden(client) -> None:
    bad = client.post(
        "/api/v1/live/sources",
        json={"name": "bad", "kind": "file", "path": "../secret.mp4"},
    )
    assert bad.status_code == 422
    assert sanitize_target("rtsp://user:secret@example.com:8554/cam?token=abc") == (
        "rtsp://example.com:8554/cam"
    )
    bad_scheme = client.post(
        "/api/v1/live/sources",
        json={"name": "bad", "kind": "rtsp", "url": "http://example.com/video"},
    )
    assert bad_scheme.status_code == 422
    missing = client.post("/api/v1/live/sources", json={"name": "bad", "kind": "rtsp"})
    assert missing.status_code == 422
    assert client.get("/api/v1/live/sources").json()["sources"] == []
