"""Tests for the deterministic demo export helpers (Phase K).

Covers animated-GIF rendering from a simulated sequence and incident bundle
ZIP creation. No network, no external binaries, no real data.
"""

from __future__ import annotations

import json
import zipfile

import pytest

from firesight.config import Settings
from firesight.db import Database
from firesight.demo.scenario import ensure_demo_sequences
from firesight.export import (
    DemoVideoError,
    IncidentBundleError,
    export_incident_bundle,
    render_annotated_video,
)
from firesight.services import incidents as incident_service


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        mode="demo",
        data_root=tmp_path / "data",
        models_root=tmp_path / "models",
        database_url=f"sqlite:///{tmp_path}/test.db",
    )


@pytest.fixture()
def demo_sequence(tmp_path):
    seqs = ensure_demo_sequences(tmp_path / "data")
    return seqs["demo-alpha-ridge"]


def test_render_annotated_video_writes_gif(tmp_path, demo_sequence):
    from PIL import Image

    out = tmp_path / "clip.gif"
    path = render_annotated_video(
        demo_sequence,
        out,
        sequence_id="demo-alpha-ridge",
        camera_id="sim-cam-a",
        settings=_settings(tmp_path),
        every=5,
        max_width=320,
    )
    assert path == out and out.exists()
    im = Image.open(out)
    assert im.n_frames >= 2
    assert im.width == 320


def test_render_annotated_video_missing_dir(tmp_path):
    with pytest.raises(DemoVideoError):
        render_annotated_video(
            tmp_path / "nope",
            tmp_path / "x.gif",
            sequence_id="missing",
            settings=_settings(tmp_path),
        )


def test_render_annotated_video_empty_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(DemoVideoError):
        render_annotated_video(
            empty,
            tmp_path / "x.gif",
            sequence_id="empty",
            settings=_settings(tmp_path),
        )


def _make_incident(db: Database) -> str:
    inc_id = incident_service.new_incident_id()
    db.execute(
        """INSERT INTO incidents (id, status, severity_tier, title, provenance, mode,
             latitude, longitude, location_uncertainty_m, geometry_quality,
             ray_separation_deg, vlm_assessment, ground_truth_available,
             first_seen_ts, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            inc_id, "candidate", "tier_2", "Test plume", "simulated", "demo",
            37.22, -119.46, 150.0, "strong", 106.0, None, 0,
            "2024-07-12T15:30:10+00:00", "2024-07-12T15:30:10+00:00",
            "2024-07-12T15:30:10+00:00",
        ),
    )
    return inc_id


def test_export_incident_bundle_writes_files(tmp_path):
    db = Database(_settings(tmp_path).database_path)
    db.initialize()
    inc_id = _make_incident(db)

    out = tmp_path / "bundle.zip"
    path = export_incident_bundle(db, inc_id, out)
    assert path == out and out.exists()

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert {"incident.json", "incident.csv", "manifest.json"} <= names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["incident_id"] == inc_id
        assert manifest["provenance"] == "simulated"
        assert manifest["ground_truth_available"] is False
        incident = json.loads(zf.read("incident.json"))
        assert incident["incident"]["id"] == inc_id


def test_export_incident_bundle_unknown_raises(tmp_path):
    db = Database(_settings(tmp_path).database_path)
    db.initialize()
    with pytest.raises(IncidentBundleError):
        export_incident_bundle(db, "inc_missing", tmp_path / "x.zip")
