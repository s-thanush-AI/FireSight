"""Temporal verification of smoke detections.

A deliberately simple, explainable rolling-window heuristic — NOT a trained
temporal model. A detection only escalates to a confirmed event after
sufficient persistence on one camera:

  * at least `min_positive_observations` detections above `min_confidence`
  * within `window_seconds`, with no gap larger than `max_gap_seconds`
  * persistence ratio (hits / frames that could have been observed) above
    `min_persistence_ratio`
  * matching by IoU or normalized centre distance between consecutive boxes

Alerts are deduplicated per track: the confirmation transition is emitted once;
further confirmations on the same track are logged as suppressed updates.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..config import TemporalSettings
from ..enums import Provenance
from ..models import BBox, Detection, TemporalAlert

log = logging.getLogger(__name__)


@dataclass
class TrackedDetection:
    detection: Detection
    ts: datetime


@dataclass
class SuppressedDetection:
    track_id: str
    camera_id: str | None
    confidence: float
    reason: str


@dataclass
class _Track:
    id: str
    camera_id: str | None
    hits: list[TrackedDetection] = field(default_factory=list)
    confirmed: bool = False
    alert_emitted: bool = False
    last_seen: datetime | None = None
    last_bbox: BBox | None = None

    def prune(self, now: datetime, window_seconds: float) -> None:
        cutoff_ts = now.timestamp() - window_seconds
        self.hits = [h for h in self.hits if h.ts.timestamp() >= cutoff_ts]


class TemporalTracker:
    """Per-camera temporal verification state machine."""

    def __init__(self, camera_id: str | None, settings: TemporalSettings | None = None):
        self.camera_id = camera_id
        self.settings = settings or TemporalSettings()
        self.tracks: dict[str, _Track] = {}
        self.suppressed: list[SuppressedDetection] = []
        self._closed: set[str] = set()

    # -- matching ----------------------------------------------------
    @staticmethod
    def _match_score(a: BBox, b: BBox, iou_min: float, center_max_norm: float, width: int) -> bool:
        iou = a.iou(b)
        if iou >= iou_min:
            return True
        acx, acy = a.center()
        bcx, bcy = b.center()
        dist_norm = ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5 / max(float(width), 1.0)
        return dist_norm <= center_max_norm

    # -- update ------------------------------------------------------
    def update(
        self, detections: list[Detection], timestamp: datetime | None = None
    ) -> list[TemporalAlert]:
        """Feed one frame's detections; return alerts whose state changed this call."""
        ts = timestamp or datetime.now(UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        s = self.settings
        alerts: list[TemporalAlert] = []

        kept = [
            d
            for d in detections
            if d.confidence >= s.min_confidence and (d.camera_id == self.camera_id or self.camera_id is None)
        ]
        for d in detections:
            if d not in kept:
                self.suppressed.append(
                    SuppressedDetection(
                        track_id="",
                        camera_id=self.camera_id,
                        confidence=d.confidence,
                        reason=f"confidence {d.confidence:.2f} below temporal min {s.min_confidence:.2f}",
                    )
                )

        # prune old hits on every track
        for track in self.tracks.values():
            track.prune(ts, s.window_seconds)

        used: set[str] = set()
        for det in kept:
            matched_id = None
            width = det.frame.image_width or 1
            for tid, track in self.tracks.items():
                if tid in used or tid in self._closed:
                    continue
                if track.last_bbox is None or track.last_seen is None:
                    continue
                gap = (ts - track.last_seen).total_seconds()
                if gap > s.max_gap_seconds:
                    continue
                if self._match_score(track.last_bbox, det.bbox, s.match_iou_min, s.match_center_max_norm, width):
                    matched_id = tid
                    break
            if matched_id is None:
                track = _Track(id=f"trk_{uuid.uuid4().hex[:10]}", camera_id=self.camera_id)
                self.tracks[track.id] = track
                matched_id = track.id
            used.add(matched_id)
            track = self.tracks[matched_id]
            track.hits.append(TrackedDetection(detection=det, ts=ts))
            track.last_seen = ts
            track.last_bbox = det.bbox

            hits = len(track.hits)
            span = max((track.hits[-1].ts - track.hits[0].ts).total_seconds(), 0.0)
            expected = max(int(span / max(s.max_gap_seconds, 0.1)) + 1, hits)
            persistence = hits / expected if expected else 0.0
            mean_conf = sum(h.detection.confidence for h in track.hits) / hits

            should_confirm = (
                hits >= s.min_positive_observations
                and persistence >= s.min_persistence_ratio
            )
            if should_confirm and not track.confirmed:
                track.confirmed = True
                alerts.append(
                    TemporalAlert(
                        track_id=track.id,
                        camera_id=self.camera_id,
                        confirmed=True,
                        positive_count=hits,
                        expected_count=expected,
                        persistence_ratio=round(persistence, 3),
                        mean_confidence=round(mean_conf, 4),
                        first_ts=track.hits[0].ts.isoformat(),
                        last_ts=ts.isoformat(),
                        latest_bbox=det.bbox,
                        reason=(
                            f"{hits}/{expected} positive observations within "
                            f"{s.window_seconds:.1f}s (persistence {persistence:.0%}, "
                            f"min {s.min_persistence_ratio:.0%})"
                        ),
                        provenance=Provenance.HEURISTIC,
                    )
                )
            elif should_confirm and track.confirmed:
                track.alert_emitted = True
                self.suppressed.append(
                    SuppressedDetection(
                        track_id=track.id,
                        camera_id=self.camera_id,
                        confidence=det.confidence,
                        reason="duplicate confirmation on an already-confirmed track (deduplicated)",
                    )
                )
        return alerts

    # -- closing -----------------------------------------------------
    def close_idle_tracks(self, now: datetime | None = None) -> list[TemporalAlert]:
        """Expire tracks idle beyond the grace period; emit 'lost' state updates."""
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        alerts: list[TemporalAlert] = []
        for tid, track in list(self.tracks.items()):
            if track.last_seen is None:
                continue
            idle = (now - track.last_seen).total_seconds()
            if idle > self.settings.grace_seconds and tid not in self._closed:
                self._closed.add(tid)
                if track.confirmed:
                    hits = len(track.hits)
                    alerts.append(
                        TemporalAlert(
                            track_id=tid,
                            camera_id=self.camera_id,
                            confirmed=False,
                            positive_count=hits,
                            expected_count=hits,
                            persistence_ratio=1.0,
                            mean_confidence=0.0,
                            first_ts=track.hits[0].ts.isoformat() if track.hits else None,
                            last_ts=track.last_seen.isoformat(),
                            latest_bbox=track.last_bbox,
                            reason=f"track idle for {idle:.1f}s beyond grace period {self.settings.grace_seconds:.1f}s",
                            provenance=Provenance.HEURISTIC,
                        )
                    )
        return alerts

    def summary(self) -> dict[str, int]:
        confirmed = sum(1 for t in self.tracks.values() if t.confirmed and t.id not in self._closed)
        return {
            "tracks": len(self.tracks),
            "confirmed": confirmed,
            "suppressed": len(self.suppressed),
            "closed": len(self._closed),
        }
