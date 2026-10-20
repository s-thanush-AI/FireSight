"""Offline detection over local video files.

Results are experimental. Detection boxes come from whatever detector the
application is configured with (by default a non-learned heuristic), so they
must never be presented as validated smoke detections or as confirmed
incidents.
"""

from __future__ import annotations

import csv
import json
import logging
import uuid
from pathlib import Path

from ..db import utcnow_iso
from ..models import FrameRef
from .alerts import AlertService, encode_evidence_jpeg
from .video_library import VideoLibrary

log = logging.getLogger(__name__)


class VideoAnalysisError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _bounded_jpeg(image, max_side: int = 1280, quality: int = 82) -> bytes | None:
    return encode_evidence_jpeg(image, max_side=max_side, quality=quality)


class VideoAnalysisService:
    def __init__(
        self,
        *,
        context,
        library: VideoLibrary,
        alerts: AlertService,
        data_root: Path,
    ):
        self.ctx = context
        self.library = library
        self.alerts = alerts
        self.data_root = Path(data_root)
        self.out_root = self.data_root / "analysis"
        self.out_root.mkdir(parents=True, exist_ok=True)

    def analyze(
        self,
        video_id: str,
        *,
        sample_every_s: float = 5.0,
        threshold: float | None = None,
        camera_id: str | None = None,
        max_samples: int = 120,
        min_consecutive: int = 2,
    ) -> dict:
        import cv2

        video = self.library.get(video_id)
        path = self.library.path_for(video_id)
        fps = float(video["fps"] or 0.0)
        if fps <= 0:
            raise VideoAnalysisError("unreadable", "Video reports zero FPS; cannot sample by time")
        threshold = (
            self.ctx.settings.detector.confidence_threshold if threshold is None else threshold
        )
        max_samples = max(1, min(int(max_samples), 240))
        sample_every_s = max(0.25, min(float(sample_every_s), 600.0))
        step = max(1, int(round(fps * sample_every_s)))

        run_id = f"anr_{uuid.uuid4().hex[:12]}"
        out_dir = self.out_root / video_id / run_id
        orig_dir = out_dir / "original"
        ann_dir = out_dir / "annotated"
        orig_dir.mkdir(parents=True, exist_ok=True)
        ann_dir.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise VideoAnalysisError("unreadable", f"Could not open video: {video_id}")

        detections_total = 0
        rows: list[dict] = []
        samples: list[dict] = []
        streak = 0
        alert_created = None
        max_conf = 0.0

        try:
            frame_index = 0
            count = 0
            while count < max_samples:
                ok, image = cap.read()
                if not ok:
                    break
                if frame_index % step != 0:
                    frame_index += 1
                    continue
                timestamp_s = frame_index / fps
                ref = FrameRef(
                    sequence_id=f"video:{video_id}",
                    index=frame_index,
                    filename=f"{video_id}@{timestamp_s:.2f}s",
                    timestamp=None,
                    image_width=image.shape[1],
                    image_height=image.shape[0],
                    rel_path=str(path.relative_to(self.data_root))
                    if path.is_relative_to(self.data_root)
                    else path.name,
                )
                dets = [
                    d
                    for d in self.ctx.detector.detect(image, ref, camera_id)
                    if d.confidence >= threshold
                ]
                detections_total += len(dets)
                for d in dets:
                    max_conf = max(max_conf, d.confidence)
                    rows.append(
                        {
                            "run_id": run_id,
                            "video_id": video_id,
                            "frame_index": frame_index,
                            "timestamp_s": round(timestamp_s, 3),
                            "class_name": d.class_name,
                            "confidence": round(d.confidence, 4),
                            "x1": round(d.bbox.x1, 1),
                            "y1": round(d.bbox.y1, 1),
                            "x2": round(d.bbox.x2, 1),
                            "y2": round(d.bbox.y2, 1),
                            "model_name": d.model_name,
                            "model_version": d.model_version,
                            "provenance": d.provenance.value,
                        }
                    )

                stem = f"frame_{frame_index:06d}_{timestamp_s:08.2f}s"
                original_jpeg = _bounded_jpeg(image, max_side=1280, quality=85)
                if original_jpeg:
                    (orig_dir / f"{stem}.jpg").write_bytes(original_jpeg)

                from ..detection.drawing import draw_detections

                annotated = draw_detections(
                    image,
                    dets,
                    metadata_lines=[
                        f"video={video_id}  t={timestamp_s:.2f}s  frame={frame_index}",
                        f"model={self.ctx.detector.name}:{self.ctx.detector.version}  "
                        f"dets={len(dets)}  experimental",
                    ],
                )
                annotated_jpeg = _bounded_jpeg(annotated, max_side=1280, quality=82)
                evidence_jpeg = None
                if annotated_jpeg:
                    (ann_dir / f"{stem}.jpg").write_bytes(annotated_jpeg)
                    if dets:
                        evidence_jpeg = annotated_jpeg

                if dets:
                    streak += 1
                else:
                    streak = 0
                if (
                    streak >= max(1, min_consecutive)
                    and alert_created is None
                    and evidence_jpeg is not None
                ):
                    alert_created = self.alerts.create(
                        source_type="video_analysis",
                        source_id=video_id,
                        camera_id=camera_id or video.get("camera_id"),
                        event_time=utcnow_iso(),
                        detector_name=self.ctx.detector.name,
                        detector_version=self.ctx.detector.version,
                        confidence=round(max(d.confidence for d in dets), 4),
                        severity="info",
                        verification_status="experimental",
                        frame_ref=f"{video_id}@{timestamp_s:.2f}s",
                        evidence_jpeg=evidence_jpeg,
                        dedupe_key=f"video_analysis:{video_id}:{camera_id or video.get('camera_id') or '-'}",
                        notes=(
                            f"Experimental detection in time-lapse video at video time "
                            f"{timestamp_s:.2f}s. Not a confirmed incident; real capture "
                            f"timestamp mapping is unverified."
                        ),
                    )

                samples.append(
                    {
                        "frame_index": frame_index,
                        "timestamp_s": round(timestamp_s, 3),
                        "detection_count": len(dets),
                        "max_confidence": round(max((d.confidence for d in dets), default=0.0), 4),
                        "original_image": str((orig_dir / f"{stem}.jpg").relative_to(self.data_root)),
                        "annotated_image": str((ann_dir / f"{stem}.jpg").relative_to(self.data_root)),
                    }
                )
                count += 1
                frame_index += 1
        finally:
            cap.release()

        learned = self.ctx.settings.detector.kind == "yolo"
        summary = {
            "run_id": run_id,
            "video_id": video_id,
            "video": video,
            "camera_id": camera_id or video.get("camera_id"),
            "created_at": utcnow_iso(),
            "detector": {
                "name": self.ctx.detector.name,
                "version": self.ctx.detector.version,
                "provenance": self.ctx.detector.provenance.value,
                "kind": "yolo" if learned else "heuristic",
                "config_kind": self.ctx.settings.detector.kind,
                "learned": learned,
                "caveat": getattr(self.ctx.detector, "caveat", None),
            },
            "sample_every_s": sample_every_s,
            "frames_sampled": len(samples),
            "detections_total": detections_total,
            "max_confidence": round(max_conf, 4),
            "first_detection_video_time_s": next(
                (s["timestamp_s"] for s in samples if s["detection_count"] > 0), None
            ),
            "threshold": threshold,
            "min_consecutive": min_consecutive,
            "alert_id": alert_created["id"] if alert_created else None,
            "verification_status": "experimental",
            "timestamp_mapping": "not_verified",
            "notes": [
                "Boxes are detector output, not ground truth.",
                "Video is a time-lapse compilation; video time is not a validated capture timestamp.",
                "Alert suppression is applied per video/camera for the configured cooldown.",
            ],
            "samples": samples,
            "output_dir": str(out_dir.relative_to(self.data_root)),
        }

        self._write_exports(out_dir, summary, rows, video)
        self.ctx.db.execute(
            """INSERT INTO analysis_runs (id, video_id, created_at, sample_every_s,
                 detector_name, detector_version, frames_sampled, detections_total,
                 summary_json, output_dir)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id, video_id, summary["created_at"], sample_every_s,
                self.ctx.detector.name, self.ctx.detector.version, len(samples),
                detections_total, json.dumps(summary), summary["output_dir"],
            ),
        )
        for row in rows:
            self.ctx.db.execute(
                """INSERT INTO video_detections (run_id, video_id, frame_index, timestamp_s,
                     class_name, confidence, x1, y1, x2, y2, model_name, model_version,
                     provenance, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, video_id, row["frame_index"], row["timestamp_s"], row["class_name"],
                    row["confidence"], row["x1"], row["y1"], row["x2"], row["y2"],
                    row["model_name"], row["model_version"], row["provenance"], utcnow_iso(),
                ),
            )
        return summary

    def _write_exports(self, out_dir: Path, summary: dict, rows: list[dict], video: dict) -> None:
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        fieldnames = [
            "run_id", "video_id", "frame_index", "timestamp_s", "class_name", "confidence",
            "x1", "y1", "x2", "y2", "model_name", "model_version", "provenance",
        ]
        with (out_dir / "detections.csv").open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        detector = summary["detector"]
        caveat = detector.get("caveat") or "No additional caveat supplied by the detector."
        (out_dir / "report.md").write_text(
            "# FireSight video analysis (experimental)\n\n"
            f"- Video: `{video['label']}` (`{video['id']}`)\n"
            f"- Duration: {video.get('duration_s')} s at {video.get('fps')} fps, "
            f"{video.get('frame_count')} frames\n"
            f"- Detector: `{detector['name']}` v{detector['version']} "
            f"({detector['provenance']}, learned={detector['learned']})\n"
            f"- Caveat: {caveat}\n"
            f"- Frames sampled: {summary['frames_sampled']} every "
            f"{summary['sample_every_s']} s of video time\n"
            f"- Detections: {summary['detections_total']} "
            f"(max confidence {summary['max_confidence']})\n"
            f"- First detection at video time: "
            f"{summary['first_detection_video_time_s']} s\n"
            f"- Alert: {summary['alert_id'] or 'none (suppressed or below threshold)'}\n"
            f"- Timestamp mapping: **{summary['timestamp_mapping']}**\n\n"
            "## Honest limits\n\n"
            "- Detections are not ground truth and are not confirmed incidents.\n"
            "- The configured detector may be a heuristic, not a trained smoke model.\n"
            "- Video time is not a validated real-world capture timestamp for this time-lapse.\n"
            "- Original and annotated samples are stored beside this report.\n"
        )
