"""Persistent, experimental detection alerts.

Alerts are operational hints from the configured detector, not confirmed
incidents. Every alert keeps its detector provenance and an evidence image so a
human can review it. No alert is ever generated without a detection that the
detector actually returned.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..db import Database, utcnow_iso

log = logging.getLogger(__name__)


class AlertService:
    def __init__(self, db: Database, evidence_dir: Path, cooldown_s: float = 120.0):
        self.db = db
        self.evidence_dir = evidence_dir
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.cooldown_s = cooldown_s
        self._ws_clients: dict[Any, asyncio.AbstractEventLoop] = {}
        self._lock = threading.Lock()

    # -- websocket fan-out -------------------------------------------
    def add_ws(self, ws: Any, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._ws_clients[ws] = loop

    def remove_ws(self, ws: Any) -> None:
        with self._lock:
            self._ws_clients.pop(ws, None)

    def _broadcast(self, alert: dict) -> None:
        event = {"type": "alert", "ts": utcnow_iso(), "data": alert}
        with self._lock:
            clients = list(self._ws_clients.items())
        dead = []
        for ws, loop in clients:
            try:
                asyncio.run_coroutine_threadsafe(ws.send_json(event), loop)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove_ws(ws)

    # -- evidence ----------------------------------------------------
    def save_evidence(self, jpeg_bytes: bytes, stem: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:80]
        name = f"{utcnow_iso().replace(':', '').replace('+', 'Z')}_{safe}.jpg"
        path = self.evidence_dir / name
        path.write_bytes(jpeg_bytes)
        return name

    def evidence_path(self, name: str) -> Path | None:
        candidate = (self.evidence_dir / Path(name).name).resolve()
        try:
            candidate.relative_to(self.evidence_dir.resolve())
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    # -- CRUD --------------------------------------------------------
    def recent_duplicate(self, dedupe_key: str) -> dict | None:
        cutoff = (datetime.now(UTC) - timedelta(seconds=self.cooldown_s)).isoformat()
        return self.db.query_one(
            """SELECT * FROM alerts WHERE dedupe_key=? AND created_at>=?
               ORDER BY created_at DESC LIMIT 1""",
            (dedupe_key, cutoff),
        )

    def create(
        self,
        *,
        source_type: str,
        source_id: str | None,
        camera_id: str | None,
        event_time: str | None,
        detector_name: str,
        detector_version: str | None,
        confidence: float | None,
        severity: str = "info",
        verification_status: str = "experimental",
        frame_ref: str | None = None,
        evidence_jpeg: bytes | None = None,
        dedupe_key: str | None = None,
        notes: str | None = None,
    ) -> dict | None:
        """Create an alert unless an identical one fired inside the cooldown."""
        key = dedupe_key or f"{source_type}:{source_id or '-'}:{camera_id or '-'}"
        if self.recent_duplicate(key) is not None:
            return None
        alert_id = f"alr_{uuid.uuid4().hex[:12]}"
        evidence_name = None
        if evidence_jpeg:
            evidence_name = self.save_evidence(evidence_jpeg, alert_id)
        now = utcnow_iso()
        self.db.execute(
            """INSERT INTO alerts (id, source_type, source_id, camera_id, event_time, created_at,
                 detector_name, detector_version, confidence, severity, status,
                 verification_status, frame_ref, evidence_path, dedupe_key, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                alert_id, source_type, source_id, camera_id, event_time or now, now,
                detector_name, detector_version, confidence, severity, "new",
                verification_status, frame_ref, evidence_name, key, notes,
            ),
        )
        alert = self.get(alert_id)
        if alert is not None:
            self._broadcast(alert)
        return alert

    def get(self, alert_id: str) -> dict | None:
        return self.db.query_one("SELECT * FROM alerts WHERE id=?", (alert_id,))

    def list(
        self, *, limit: int = 100, status: str | None = None, source_type: str | None = None
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if source_type:
            clauses.append("source_type=?")
            params.append(source_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        return self.db.query(
            f"SELECT * FROM alerts {where} ORDER BY created_at DESC LIMIT ?", tuple(params)
        )

    def acknowledge(self, alert_id: str) -> dict | None:
        if self.get(alert_id) is None:
            return None
        self.db.execute(
            "UPDATE alerts SET status='acknowledged', acknowledged_at=? WHERE id=?",
            (utcnow_iso(), alert_id),
        )
        alert = self.get(alert_id)
        if alert is not None:
            self._broadcast(alert)
        return alert

    def resolve(self, alert_id: str) -> dict | None:
        if self.get(alert_id) is None:
            return None
        self.db.execute(
            "UPDATE alerts SET status='resolved', resolved_at=? WHERE id=?",
            (utcnow_iso(), alert_id),
        )
        alert = self.get(alert_id)
        if alert is not None:
            self._broadcast(alert)
        return alert

    def stats(self) -> dict:
        row = self.db.query_one(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN status='new' THEN 1 ELSE 0 END) AS new,
                      SUM(CASE WHEN status='acknowledged' THEN 1 ELSE 0 END) AS acknowledged,
                      SUM(CASE WHEN status='resolved' THEN 1 ELSE 0 END) AS resolved
               FROM alerts"""
        ) or {}
        return {k: int(v or 0) for k, v in row.items()}


def encode_evidence_jpeg(image, max_side: int = 1280, quality: int = 82) -> bytes | None:
    """Encode a BGR frame as a bounded-size JPEG for alert evidence."""
    import cv2

    h, w = image.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        image = cv2.resize(
            image, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA
        )
    ok, enc = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return enc.tobytes() if ok else None


def alert_summary_json(alert: dict) -> str:
    return json.dumps(alert, sort_keys=True, default=str)


def b64(jpeg: bytes) -> str:
    return base64.b64encode(jpeg).decode("ascii")
