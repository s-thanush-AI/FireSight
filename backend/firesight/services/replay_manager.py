"""Replay session lifecycle and the per-frame processing pipeline."""

from __future__ import annotations

import asyncio
import base64
import logging
import threading
import uuid
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import cv2

from ..db import dumps, utcnow_iso
from ..enums import (
    EvidenceType,
    GeometryQuality,
    IncidentStatus,
    Provenance,
    ReplayStatus,
    SeverityTier,
)
from ..geometry.bearing import pixel_to_bearing, proxy_point_from_bbox
from ..geometry.triangulation import triangulate
from ..models import BearingObservation, Detection, FrameRef
from ..replay.discovery import SequenceError, discover_frames
from ..replay.engine import FramePacket, ReplayEngine
from ..temporal.tracker import TemporalTracker

if TYPE_CHECKING:
    from .context import AppContext

log = logging.getLogger(__name__)

DEMO_FPS = 5.0
MAX_EVENT_LOG = 500


class ReplayError(RuntimeError):
    pass


class ReplaySession:
    def __init__(
        self,
        ctx: AppContext,
        replay_id: str,
        sequence_id: str,
        camera_id: str | None,
        speed: float,
    ):
        self.ctx = ctx
        self.id = replay_id
        self.sequence_id = sequence_id
        row = ctx.db.query_one("SELECT * FROM sequences WHERE id=?", (sequence_id,))
        if row is None:
            raise ReplayError(f"Unknown sequence: {sequence_id}")
        self.sequence_row = row
        # Default the camera from the sequence manifest when not given, so a
        # registered (e.g. demo) sequence produces real bearings without extra input.
        self.camera_id = camera_id or self._manifest_camera_id(row)
        self.speed = speed
        try:
            self.frames = discover_frames(row["root_path"])
        except SequenceError as e:
            raise ReplayError(str(e)) from e
        self.trackers: dict[str, TemporalTracker] = {}
        self.current_jpeg_b64: str | None = None
        self.current_original_b64: str | None = None
        self.current_meta: dict | None = None
        self.last_detections: list[dict] = []
        self.events: deque[dict] = deque(maxlen=MAX_EVENT_LOG)
        self.frames_emitted = 0
        self.detections_total = 0
        self.alerts_total = 0
        self._ws_clients: dict[object, asyncio.AbstractEventLoop] = {}
        self._incident_by_track: dict[str, str] = {}
        self.engine = ReplayEngine(
            self.frames,
            sequence_id=sequence_id,
            speed=speed,
            base_fps=DEMO_FPS,
            on_frame=self._on_frame,
            on_error=lambda e: self._set_error(str(e)),
            on_finish=self._on_finish,
        )
        self._persisted_frames = 0
        self._store_lock = threading.Lock()

    # ---- status ----------------------------------------------------
    @staticmethod
    def _manifest_camera_id(row: dict) -> str | None:
        import json

        try:
            meta = json.loads(row.get("manifest_json") or "{}")
        except json.JSONDecodeError:
            return None
        cam = meta.get("camera_id")
        return cam if isinstance(cam, str) and cam else None

    @property
    def status(self) -> ReplayStatus:
        if self.engine.error:
            return ReplayStatus.ERROR
        if not self.engine.loop and self.engine.position >= len(self.frames):
            return ReplayStatus.FINISHED
        if self.engine.paused:
            return ReplayStatus.PAUSED if self.engine.emitted else ReplayStatus.IDLE
        return ReplayStatus.RUNNING

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sequence_id": self.sequence_id,
            "camera_id": self.camera_id,
            "status": self.status.value,
            "speed": self.speed,
            "frame_index": self.engine.position,
            "frame_count": self.engine.frame_count,
            "frames_emitted": self.frames_emitted,
            "detections_total": self.detections_total,
            "alerts_total": self.alerts_total,
            "mode": self.ctx.settings.mode,
            "provenance": (
                Provenance.SIMULATED.value
                if self.sequence_row["provenance"] == Provenance.SIMULATED.value
                else Provenance.REAL.value
            ),
            "error": self.engine.error,
            "created_at": utcnow_iso(),
        }

    # ---- event log / websockets ------------------------------------
    def emit(self, event_type: str, data: dict) -> None:
        event = {"type": event_type, "replay_id": self.id, "ts": utcnow_iso(), "data": data}
        self.events.append(event)
        dead = []
        for ws, loop in list(self._ws_clients.items()):
            try:
                asyncio.run_coroutine_threadsafe(ws.send_json(event), loop)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._ws_clients.pop(ws, None)

    def add_ws(self, ws, loop: asyncio.AbstractEventLoop) -> None:
        self._ws_clients[ws] = loop

    def remove_ws(self, ws) -> None:
        self._ws_clients.pop(ws, None)

    def _set_error(self, msg: str) -> None:
        self.ctx.db.execute(
            "UPDATE replays SET status=?, error=?, updated_at=? WHERE id=?",
            (ReplayStatus.ERROR.value, msg, utcnow_iso(), self.id),
        )
        self.emit("error", {"error": msg})

    def _on_finish(self) -> None:
        self.ctx.db.execute(
            "UPDATE replays SET status=?, updated_at=? WHERE id=?",
            (ReplayStatus.FINISHED.value, utcnow_iso(), self.id),
        )
        # run the grace-period close check for any lingering tracks
        now = datetime.now(UTC)
        for tracker in self.trackers.values():
            for alert in tracker.close_idle_tracks(now):
                self.emit("track_lost", alert.model_dump())
        self.emit("finished", {"frames": self.frames_emitted})

    # ---- frame pipeline --------------------------------------------
    def _frame_timestamp(self, packet: FramePacket) -> datetime:
        if packet.timestamp is not None:
            ts = packet.timestamp
            return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
        base = self.sequence_row["start_ts"]
        if base:
            try:
                start = datetime.fromisoformat(base)
                if start.tzinfo is None:
                    start = start.replace(tzinfo=UTC)
                return start + timedelta(seconds=packet.index / DEMO_FPS)
            except ValueError:
                pass
        return datetime.now(UTC)

    def _on_frame(self, packet: FramePacket) -> None:
        ctx = self.ctx
        ts = self._frame_timestamp(packet)
        ref = FrameRef(
            sequence_id=self.sequence_id,
            index=packet.index,
            filename=packet.filename,
            timestamp=ts.isoformat(),
            image_width=packet.width,
            image_height=packet.height,
            rel_path=packet.rel_path,
        )
        try:
            detections = ctx.detector.detect(packet.image, ref, self.camera_id)
        except Exception as e:
            self._set_error(f"detector failed: {e}")
            self.engine.stop()
            return

        tracker = self.trackers.setdefault(
            self.camera_id or "default", TemporalTracker(self.camera_id, ctx.settings.temporal)
        )
        alerts = tracker.update(detections, ts)

        # annotated frame for the UI
        from ..detection.drawing import draw_detections

        seq_prov = self.sequence_row["provenance"]
        watermark = "SIMULATED DEMO DATA" if seq_prov == Provenance.SIMULATED.value else None
        annotated = draw_detections(
            packet.image,
            detections,
            watermark=watermark,
            metadata_lines=[
                f"cam={self.camera_id or '-'}  frame={packet.index}  {ref.filename}",
                f"model={ctx.detector.name}:{ctx.detector.version}  dets={len(detections)}",
            ],
        )
        ui_max = int(ctx.settings.replay_ui_max_side)
        quality = int(ctx.settings.replay_ui_quality)
        self.current_jpeg_b64 = self._encode_ui(annotated, ui_max, quality)
        self.current_original_b64 = self._encode_ui(packet.image, 960, 72)
        self.current_meta = {
            "index": packet.index,
            "filename": packet.filename,
            "timestamp": ts.isoformat(),
            "width": packet.width,
            "height": packet.height,
            "camera_id": self.camera_id,
            "sequence_id": self.sequence_id,
            "provenance": seq_prov,
            "detector_name": ctx.detector.name,
            "detector_version": ctx.detector.version,
            "detector_provenance": ctx.detector.provenance.value,
            "detector_caveat": getattr(ctx.detector, "caveat", None),
        }
        self.last_detections = [d.model_dump() for d in detections]
        self.frames_emitted += 1
        self.detections_total += len(detections)

        self._persist_frame(ref, seq_prov, detections)

        for alert in alerts:
            self.alerts_total += 1
            self.emit("temporal_alert", alert.model_dump())
            self._handle_confirmation(alert, detections, ts)

        self.emit(
            "frame",
            {
                "replay_id": self.id,
                "frame": self.current_meta,
                "image_jpeg_base64": self.current_jpeg_b64,
                "detections": self.last_detections,
                "detection_count": len(detections),
                "confirmed_tracks": sum(
                    1 for t in tracker.tracks.values() if t.confirmed
                ),
            },
        )

    @staticmethod
    def _encode_ui(image, max_side: int, quality: int) -> str | None:
        """Encode a bounded preview; full 3072px frames stall the websocket UI."""
        h, w = image.shape[:2]
        scale = min(1.0, max_side / max(h, w))
        if scale < 1.0:
            image = cv2.resize(
                image,
                (max(1, int(w * scale)), max(1, int(h * scale))),
                interpolation=cv2.INTER_AREA,
            )
        ok, enc = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        return base64.b64encode(enc.tobytes()).decode("ascii") if ok else None

    def _persist_frame(self, ref: FrameRef, seq_prov: str, detections: list[Detection]) -> None:
        with self._store_lock:
            if self._persisted_frames >= self.ctx.settings.replay_max_stored_frames:
                return
            frame_id = self.ctx.db.execute(
                """INSERT INTO frames (replay_id, sequence_id, index_in_sequence, filename,
                     timestamp, rel_path, image_width, image_height, provenance, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.id, self.sequence_id, ref.index, ref.filename, ref.timestamp,
                    ref.rel_path, ref.image_width, ref.image_height, seq_prov, utcnow_iso(),
                ),
            )
            self._persisted_frames += 1
            for d in detections:
                self.ctx.db.execute(
                    """INSERT INTO detections (frame_id, replay_id, camera_id, track_id,
                         class_name, confidence, x1, y1, x2, y2, model_name, model_version,
                         provenance, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        frame_id, self.id, self.camera_id, None, d.class_name, d.confidence,
                        d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2, d.model_name,
                        d.model_version, d.provenance.value, utcnow_iso(),
                    ),
                )

    # ---- incident creation -----------------------------------------
    def _bearing_observation(self, det: Detection, ts: datetime) -> BearingObservation | None:
        ctx = self.ctx
        if self.camera_id is None:
            return None
        cam = ctx.cameras.get(self.camera_id)
        if cam is None:
            return None
        proxy_kind = ctx.settings.proxy_point
        px, py = proxy_point_from_bbox(
            det.bbox.x1, det.bbox.y1, det.bbox.x2, det.bbox.y2, proxy_kind
        )
        bearing = pixel_to_bearing(
            px, image_width=cam.image_width, heading_deg=cam.heading_deg, hfov_deg=cam.hfov_deg
        )
        seq_prov = self.sequence_row["provenance"]
        evidence = (
            EvidenceType.SIMULATED_SECOND_CAMERA
            if seq_prov == Provenance.SIMULATED.value
            else EvidenceType.REAL_UNPAIRED
        )
        return BearingObservation(
            camera_id=cam.id,
            bearing_deg=bearing,
            timestamp=ts.isoformat(),
            pixel_x=px,
            pixel_y=py,
            proxy_kind=proxy_kind,
            confidence=det.confidence,
            evidence_type=evidence,
            provenance=Provenance.PREDICTED,
            camera=cam,
        )

    def _handle_confirmation(self, alert, detections: list[Detection], ts: datetime) -> None:
        ctx = self.ctx
        if alert.track_id in self._incident_by_track:
            return
        det = None
        if alert.latest_bbox is not None:
            for d in detections:
                if d.bbox == alert.latest_bbox:
                    det = d
                    break
            if det is None and detections:
                det = max(detections, key=lambda d: d.confidence)
        if det is None:
            return
        obs = self._bearing_observation(det, ts)
        if obs is None:
            return
        seq_prov = self.sequence_row["provenance"]
        provenance = (
            Provenance.SIMULATED if seq_prov == Provenance.SIMULATED.value else Provenance.PREDICTED
        )
        severity = SeverityTier.LOW if alert.mean_confidence >= 0.6 else SeverityTier.INFO
        incident_id = f"inc_{uuid.uuid4().hex[:12]}"
        now = utcnow_iso()
        title = (
            f"Smoke candidate #{incident_id[-6:]} "
            f"({'simulated' if provenance == Provenance.SIMULATED else 'model-confirmed'})"
        )
        summary = (
            f"Temporal verification confirmed a smoke track on {self.camera_id} "
            f"({alert.positive_count} observations, mean confidence "
            f"{alert.mean_confidence:.2f}). "
            + (
                "All evidence is from the SIMULATED demo scenario."
                if provenance == Provenance.SIMULATED
                else "Awaiting cross-camera confirmation and human review."
            )
        )
        ctx.db.execute(
            """INSERT INTO incidents (id, status, severity_tier, title, summary, provenance,
                 mode, location_method, calibration_status, geometry_quality,
                 ground_truth_available, source_dataset, first_seen_ts, last_seen_ts,
                 created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                incident_id, IncidentStatus.CANDIDATE.value, severity.value, title, summary,
                provenance.value, ctx.settings.mode, None, None, GeometryQuality.UNAVAILABLE.value,
                0, self.sequence_row["name"], ts.isoformat(), ts.isoformat(), now, now,
            ),
        )
        ctx.db.execute(
            """INSERT INTO incident_status_history (incident_id, from_status, to_status,
                 action, actor, reason, created_at) VALUES (?,?,?,?,?,?,?)""",
            (
                incident_id, None, IncidentStatus.CANDIDATE.value, "created",
                "temporal-verifier", alert.reason, now,
            ),
        )
        self._insert_observation(incident_id, obs, det.confidence, ts)
        self._incident_by_track[alert.track_id] = incident_id
        self.emit(
            "incident_created",
            {"incident_id": incident_id, "status": IncidentStatus.CANDIDATE.value, "title": title},
        )
        self._try_cross_camera(incident_id, obs, ts)

    def _insert_observation(
        self, incident_id: str, obs: BearingObservation, confidence: float, ts: datetime
    ) -> int:
        return self.ctx.db.execute(
            """INSERT INTO observations (incident_id, camera_id, replay_id, detection_id,
                 track_id, bearing_deg, pixel_x, pixel_y, proxy_kind, timestamp,
                 evidence_type, provenance, confidence, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                incident_id, obs.camera_id, self.id, None, None, obs.bearing_deg, obs.pixel_x,
                obs.pixel_y, obs.proxy_kind, ts.isoformat(), obs.evidence_type.value,
                obs.provenance.value, confidence, utcnow_iso(),
            ),
        )

    def _try_cross_camera(self, incident_id: str, obs: BearingObservation, ts: datetime) -> None:
        """Look for a recent confirmed observation from another camera and triangulate."""
        ctx = self.ctx
        rows = ctx.db.query(
            """SELECT o.*, i.id as inc_id FROM observations o
               JOIN incidents i ON i.id = o.incident_id
               WHERE o.camera_id != ? AND i.status != 'dismissed'
               ORDER BY o.created_at DESC LIMIT 20""",
            (obs.camera_id,),
        )
        tol = ctx.settings.association_timestamp_tolerance_s
        best = None
        for row in rows:
            if not row["timestamp"]:
                continue
            try:
                other_ts = datetime.fromisoformat(row["timestamp"])
            except ValueError:
                continue
            if other_ts.tzinfo is None:
                other_ts = other_ts.replace(tzinfo=UTC)
            if abs((other_ts - ts).total_seconds()) <= tol:
                best = row
                break
        if best is None:
            return
        partner_cam = ctx.cameras.get(best["camera_id"])
        if partner_cam is None or obs.camera is None:
            return
        partner_obs = BearingObservation(
            camera_id=best["camera_id"],
            bearing_deg=best["bearing_deg"],
            timestamp=best["timestamp"],
            pixel_x=best["pixel_x"],
            pixel_y=best["pixel_y"],
            proxy_kind=best["proxy_kind"],
            confidence=best["confidence"],
            evidence_type=EvidenceType(best["evidence_type"]),
            provenance=Provenance(best["provenance"]),
            camera=partner_cam,
        )
        s = ctx.settings
        result = triangulate(
            [partner_obs, obs],
            ctx.cameras.as_dict(),
            min_separation_deg=s.triangulation_min_separation_deg,
            max_distance_m=s.triangulation_max_distance_m,
            pixel_sigma_frac=s.bearing_pixel_sigma_frac,
            heading_sigma_deg=s.bearing_heading_sigma_deg,
        )
        partner_incident = best["inc_id"]
        now = utcnow_iso()
        ev_type = (
            EvidenceType.SIMULATED_SECOND_CAMERA
            if Provenance.SIMULATED in (partner_obs.provenance, obs.provenance)
            else EvidenceType.REAL_PAIRED
        )
        self._insert_observation(partner_incident, partner_obs, partner_obs.confidence or 0.0, ts)
        ctx.db.execute(
            """INSERT INTO triangulations (incident_id, latitude, longitude, uncertainty_m,
                 ray_separation_deg, intersection_angle_deg, fit_residual_m,
                 distance_from_cameras_json, quality, method, assumptions_json, provenance,
                 created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                partner_incident, result.latitude, result.longitude, result.uncertainty_m,
                result.ray_separation_deg, result.intersection_angle_deg, result.fit_residual_m,
                dumps(result.distances_per_camera_m), result.quality.value, result.method,
                dumps({"assumptions": result.assumptions, "limitations": result.limitations,
                       "evidence_type": ev_type.value}),
                result.provenance.value, now,
            ),
        )
        if result.quality not in (GeometryQuality.UNAVAILABLE, GeometryQuality.REJECTED):
            new_status = IncidentStatus.CONFIRMED.value
            ctx.db.execute(
                """UPDATE incidents SET status=?, latitude=?, longitude=?,
                     location_uncertainty_m=?, location_method=?, calibration_status=?,
                     geometry_quality=?, ray_separation_deg=?, intersection_angle_deg=?,
                     fit_residual_m=?, updated_at=?, last_seen_ts=?
                   WHERE id=?""",
                (
                    new_status, result.latitude, result.longitude, result.uncertainty_m,
                    "two-camera bearing triangulation (least squares)",
                    obs.camera.calibration_status.value, result.quality.value,
                    result.ray_separation_deg, result.intersection_angle_deg,
                    result.fit_residual_m, now, ts.isoformat(), partner_incident,
                ),
            )
            ctx.db.execute(
                """INSERT INTO incident_status_history (incident_id, from_status, to_status,
                     action, actor, reason, created_at) VALUES (?,?,?,?,?,?,?)""",
                (
                    partner_incident, IncidentStatus.CANDIDATE.value, new_status,
                    "cross_camera_confirmation", "geometry-service",
                    (
                        f"{ev_type.value}: rays separated "
                        f"{result.ray_separation_deg}°, quality {result.quality.value}"
                        + (
                            f", uncertainty ±{result.uncertainty_m} m"
                            if result.uncertainty_m is not None
                            else ""
                        )
                    ),
                    now,
                ),
            )
            self.emit(
                "incident_updated",
                {
                    "incident_id": partner_incident,
                    "status": new_status,
                    "latitude": result.latitude,
                    "longitude": result.longitude,
                    "quality": result.quality.value,
                },
            )
            # the duplicate incident from this camera is merged conceptually
            ctx.db.execute(
                """UPDATE incidents SET status=?, summary=?, updated_at=? WHERE id=?""",
                (
                    IncidentStatus.REVIEWED.value,
                    "Superseded: the same event was confirmed by the partner camera; "
                    f"see incident {partner_incident}.",
                    now, incident_id,
                ),
            )

    # ---- controls --------------------------------------------------
    def start(self) -> None:
        self.ctx.db.execute(
            "UPDATE replays SET status=?, updated_at=? WHERE id=?",
            (ReplayStatus.RUNNING.value, utcnow_iso(), self.id),
        )
        self.engine.start()

    def pause(self) -> None:
        self.engine.pause()
        self.ctx.db.execute(
            "UPDATE replays SET status=?, updated_at=? WHERE id=?",
            (ReplayStatus.PAUSED.value, utcnow_iso(), self.id),
        )

    def resume(self) -> None:
        self.engine.resume()
        self.ctx.db.execute(
            "UPDATE replays SET status=?, updated_at=? WHERE id=?",
            (ReplayStatus.RUNNING.value, utcnow_iso(), self.id),
        )

    def reset(self) -> None:
        self.engine.reset()
        self.frames_emitted = 0
        self.detections_total = 0
        self.alerts_total = 0
        self.current_jpeg_b64 = None
        self.current_meta = None
        self.last_detections = []
        self.trackers.clear()
        self._incident_by_track.clear()
        self.ctx.db.execute(
            "UPDATE replays SET status=?, frame_index=0, updated_at=? WHERE id=?",
            (ReplayStatus.IDLE.value, utcnow_iso(), self.id),
        )

    def step(self, n: int = 1) -> dict | None:
        # Pause the background thread so it cannot race the synchronous step and
        # consume frames out of order (which would break temporal confirmation).
        self.engine.pause()
        packet = self.engine.step(n)
        if packet is None:
            return None
        return self.current_meta

    def stop(self) -> None:
        self.engine.stop()


class ReplayManager:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.sessions: dict[str, ReplaySession] = {}

    def create(self, sequence_id: str, camera_id: str | None, speed: float | None) -> ReplaySession:
        active_count = sum(
            session.status not in (ReplayStatus.FINISHED, ReplayStatus.ERROR)
            for session in self.sessions.values()
        )
        if active_count >= self.ctx.settings.max_replays:
            raise ReplayError(
                f"Maximum number of concurrent replays ({self.ctx.settings.max_replays}) reached"
            )
        replay_id = f"rp_{uuid.uuid4().hex[:12]}"
        eff_speed = speed or self.ctx.settings.replay_speed_default
        session = ReplaySession(self.ctx, replay_id, sequence_id, camera_id, eff_speed)
        self.ctx.db.execute(
            """INSERT INTO replays (id, sequence_id, camera_id, status, speed, frame_index,
                 frame_count, mode, provenance, error, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                replay_id, sequence_id, camera_id, ReplayStatus.IDLE.value, eff_speed, 0,
                len(session.frames), self.ctx.settings.mode,
                self.sequence_provenance(sequence_id), None, utcnow_iso(), utcnow_iso(),
            ),
        )
        self.sessions[replay_id] = session
        session.start()
        return session

    def sequence_provenance(self, sequence_id: str) -> str:
        row = self.ctx.db.query_one("SELECT provenance FROM sequences WHERE id=?", (sequence_id,))
        return row["provenance"] if row else Provenance.REAL.value

    def get(self, replay_id: str) -> ReplaySession:
        session = self.sessions.get(replay_id)
        if session is None:
            raise ReplayError(f"Unknown replay: {replay_id}")
        return session

    def list(self) -> list[dict]:
        rows = self.ctx.db.query("SELECT * FROM replays ORDER BY created_at DESC")
        out = []
        for row in rows:
            session = self.sessions.get(row["id"])
            if session:
                out.append(session.to_dict())
            else:
                out.append(
                    {
                        "id": row["id"],
                        "sequence_id": row["sequence_id"],
                        "camera_id": row["camera_id"],
                        "status": row["status"],
                        "speed": row["speed"],
                        "frame_index": row["frame_index"],
                        "frame_count": row["frame_count"],
                        "frames_emitted": 0,
                        "detections_total": 0,
                        "alerts_total": 0,
                        "mode": row["mode"],
                        "provenance": row["provenance"],
                        "error": row["error"],
                        "created_at": row["created_at"],
                    }
                )
        return out

    def cleanup(self, replay_id: str) -> None:
        session = self.sessions.pop(replay_id, None)
        if session:
            session.stop()
