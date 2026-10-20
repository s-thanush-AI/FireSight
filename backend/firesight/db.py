from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 3

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cameras (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    height_m REAL NOT NULL DEFAULT 2.0,
    heading_deg REAL NOT NULL,
    hfov_deg REAL NOT NULL,
    image_width INTEGER NOT NULL,
    image_height INTEGER NOT NULL,
    calibration_status TEXT NOT NULL,
    calibration_source TEXT,
    calibration_uncertainty_deg REAL,
    provenance TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sequences (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dataset TEXT NOT NULL,
    dataset_provenance TEXT NOT NULL,
    root_path TEXT NOT NULL,
    frame_count INTEGER NOT NULL DEFAULT 0,
    image_width INTEGER,
    image_height INTEGER,
    start_ts TEXT,
    end_ts TEXT,
    manifest_json TEXT,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS replays (
    id TEXT PRIMARY KEY,
    sequence_id TEXT NOT NULL,
    camera_id TEXT,
    status TEXT NOT NULL,
    speed REAL NOT NULL DEFAULT 1.0,
    frame_index INTEGER NOT NULL DEFAULT 0,
    frame_count INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL,
    provenance TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    replay_id TEXT NOT NULL,
    sequence_id TEXT NOT NULL,
    index_in_sequence INTEGER NOT NULL,
    filename TEXT NOT NULL,
    timestamp TEXT,
    rel_path TEXT NOT NULL,
    image_width INTEGER,
    image_height INTEGER,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_frames_replay ON frames(replay_id, index_in_sequence);

CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frame_id INTEGER REFERENCES frames(id) ON DELETE SET NULL,
    replay_id TEXT,
    camera_id TEXT,
    track_id TEXT,
    class_name TEXT NOT NULL,
    confidence REAL NOT NULL,
    x1 REAL NOT NULL,
    y1 REAL NOT NULL,
    x2 REAL NOT NULL,
    y2 REAL NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_detections_replay ON detections(replay_id);

CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    camera_id TEXT,
    replay_id TEXT,
    first_ts TEXT,
    last_ts TEXT,
    positive_count INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL,
    last_bbox_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    severity_tier TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    provenance TEXT NOT NULL,
    mode TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    location_uncertainty_m REAL,
    location_method TEXT,
    calibration_status TEXT,
    geometry_quality TEXT,
    ray_separation_deg REAL,
    intersection_angle_deg REAL,
    fit_residual_m REAL,
    ground_truth_lat REAL,
    ground_truth_lon REAL,
    ground_truth_available INTEGER NOT NULL DEFAULT 0,
    vlm_assessment TEXT,
    vlm_model TEXT,
    source_dataset TEXT,
    first_seen_ts TEXT,
    last_seen_ts TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);

CREATE TABLE IF NOT EXISTS incident_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT,
    camera_id TEXT NOT NULL,
    replay_id TEXT,
    detection_id INTEGER,
    track_id TEXT,
    bearing_deg REAL NOT NULL,
    pixel_x REAL NOT NULL,
    pixel_y REAL NOT NULL,
    proxy_kind TEXT NOT NULL,
    timestamp TEXT,
    evidence_type TEXT NOT NULL,
    provenance TEXT NOT NULL,
    confidence REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_incident ON observations(incident_id);

CREATE TABLE IF NOT EXISTS triangulations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT,
    latitude REAL,
    longitude REAL,
    uncertainty_m REAL,
    ray_separation_deg REAL,
    intersection_angle_deg REAL,
    fit_residual_m REAL,
    distance_from_cameras_json TEXT,
    quality TEXT NOT NULL,
    method TEXT NOT NULL,
    assumptions_json TEXT,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vlm_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT,
    provider TEXT NOT NULL,
    model_id TEXT,
    request_time TEXT NOT NULL,
    assessment TEXT,
    visual_evidence TEXT,
    alternative_explanations TEXT,
    limitations TEXT,
    recommended_next_action TEXT,
    model_confidence REAL,
    raw_response_json TEXT,
    provenance TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dataset TEXT,
    dataset_manifest_json TEXT,
    config_json TEXT,
    model_name TEXT,
    model_version TEXT,
    provenance TEXT NOT NULL,
    split TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    name TEXT NOT NULL,
    value REAL,
    unit TEXT,
    sample_count INTEGER,
    data_source TEXT,
    ground_truth_available INTEGER NOT NULL DEFAULT 0,
    valid INTEGER NOT NULL DEFAULT 0,
    limitation TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_metrics_run ON eval_metrics(run_id);

CREATE TABLE IF NOT EXISTS audit_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    details_json TEXT,
    created_at TEXT NOT NULL
);
"""

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS settings_kv (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT,
    camera_id TEXT,
    event_time TEXT NOT NULL,
    created_at TEXT NOT NULL,
    detector_name TEXT NOT NULL,
    detector_version TEXT,
    confidence REAL,
    severity TEXT NOT NULL DEFAULT 'info',
    status TEXT NOT NULL DEFAULT 'new',
    verification_status TEXT NOT NULL DEFAULT 'experimental',
    frame_ref TEXT,
    evidence_path TEXT,
    dedupe_key TEXT,
    acknowledged_at TEXT,
    resolved_at TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_dedupe ON alerts(dedupe_key, created_at DESC);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sample_every_s REAL NOT NULL,
    detector_name TEXT NOT NULL,
    detector_version TEXT,
    frames_sampled INTEGER NOT NULL,
    detections_total INTEGER NOT NULL,
    summary_json TEXT,
    output_dir TEXT
);

CREATE TABLE IF NOT EXISTS video_detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    frame_index INTEGER NOT NULL,
    timestamp_s REAL NOT NULL,
    class_name TEXT NOT NULL,
    confidence REAL NOT NULL,
    x1 REAL NOT NULL,
    y1 REAL NOT NULL,
    x2 REAL NOT NULL,
    y2 REAL NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_video_detections_run ON video_detections(run_id);
CREATE INDEX IF NOT EXISTS idx_video_detections_video ON video_detections(video_id, timestamp_s);
"""

_MIGRATIONS: dict[int, list[str]] = {
    1: [s for s in _SCHEMA_V1.split(";") if s.strip()],
    2: [s for s in _SCHEMA_V2.split(";") if s.strip()],
    3: [s for s in _SCHEMA_V3.split(";") if s.strip()],
}


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path) if str(path) != ":memory:" else Path(":memory:")
        self._memory_conn: sqlite3.Connection | None = None
        if str(path) == ":memory:":
            self._memory_conn = self._new_connection()
        elif self.path.parent and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=15.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        if self._memory_conn is not None:
            yield self._memory_conn
            self._memory_conn.commit()
            return
        c = self._new_connection()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def initialize(self) -> None:
        with self.conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = c.execute(
                "SELECT value FROM schema_meta WHERE key='version'"
            ).fetchone()
            current = int(row["value"]) if row else 0
            for version in range(current + 1, SCHEMA_VERSION + 1):
                for stmt in _MIGRATIONS[version]:
                    c.executescript(stmt)
                c.execute(
                    "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
                    (str(version),),
                )
            c.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('initialized_at', ?)",
                (utcnow_iso(),),
            )

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self.conn() as c:
            rows = c.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def query_one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        with self.conn() as c:
            row = c.execute(sql, params).fetchone()
            return dict(row) if row else None

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self.conn() as c:
            cur = c.execute(sql, params)
            return int(cur.lastrowid or 0)

    def executemany(self, sql: str, seq: list[tuple]) -> None:
        with self.conn() as c:
            c.executemany(sql, seq)


def dumps(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True)
