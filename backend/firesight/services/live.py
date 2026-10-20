"""Bounded live-source workers for RTSP and looping local test videos.

An RTSP source is only reported as running after a frame has actually been
read. Credentials are stripped from every API response and log line. The
worker keeps only the latest preview frame in memory (no unbounded buffering).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from ..db import utcnow_iso
from .alerts import AlertService, encode_evidence_jpeg

log = logging.getLogger(__name__)

VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}


class LiveSourceError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def sanitize_target(raw: str) -> str:
    """Never expose URL userinfo or query parameters (tokens)."""
    parts = urlsplit(raw)
    if parts.scheme in ("rtsp", "rtsps"):
        host = parts.hostname or "-"
        port = f":{parts.port}" if parts.port else ""
        return urlunsplit((parts.scheme, f"{host}{port}", parts.path or "/", "", ""))
    return raw


class LiveRuntime:
    def __init__(self, manager: LiveSourceManager, spec: dict):
        self.manager = manager
        self.spec = spec
        self.id = spec["id"]
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest_jpeg: bytes | None = None
        self._status = "idle"
        self._error: str | None = None
        self._last_frame_at: str | None = None
        self._frames_read = 0
        self._frames_processed = 0
        self._detections_total = 0
        self._last_processed = 0.0
        self._last_alert_at = 0.0
        self._streak = 0

    # -- public control ----------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._status = "starting"
        self._error = None
        self._thread = threading.Thread(
            target=self._run, name=f"live-{self.id}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=5.0)
        self._thread = None
        self._set_status("stopped", None)

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def snapshot(self) -> dict:
        with self._lock:
            latest = self._latest_jpeg is not None
            return {
                "id": self.id,
                "name": self.spec["name"],
                "kind": self.spec["kind"],
                "target": self.spec["display_target"],
                "camera_id": self.spec.get("camera_id"),
                "sample_fps": self.spec["sample_fps"],
                "threshold": self.spec["threshold"],
                "loop": self.spec.get("loop", False),
                "status": self._status,
                "error": self._error,
                "last_frame_at": self._last_frame_at,
                "frames_read": self._frames_read,
                "frames_processed": self._frames_processed,
                "detections_total": self._detections_total,
                "has_frame": latest,
                "experimental": True,
                "frame_url": f"/api/v1/live/sources/{self.id}/frame",
                "stream_url": f"/api/v1/live/sources/{self.id}/stream",
            }

    def frame(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    # -- internals ---------------------------------------------------
    def _set_status(self, status: str, error: str | None) -> None:
        with self._lock:
            self._status = status
            self._error = error

    def _sleep(self, seconds: float) -> bool:
        return self._stop.wait(seconds)

    def _open(self):
        import cv2

        target = self.spec["target"]
        if self.spec["kind"] == "rtsp":
            cap = cv2.VideoCapture(target, cv2.CAP_FFMPEG)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
            return cap
        return cv2.VideoCapture(str(target))

    def _run(self) -> None:
        backoff = 1.0
        try:
            while not self._stop.is_set():
                cap = self._open()
                if not cap.isOpened():
                    self._set_status(
                        "reconnecting" if self.spec["kind"] == "rtsp" else "error",
                        "Could not open the stream/source",
                    )
                    cap.release()
                    if self.spec["kind"] == "file":
                        return
                    if self._sleep(backoff):
                        return
                    backoff = min(backoff * 2, 30.0)
                    continue

                self._set_status("running", None)
                backoff = 1.0
                opened_at = time.monotonic()
                while not self._stop.is_set():
                    ok, image = cap.read()
                    if not ok:
                        break
                    self._frames_read += 1
                    with self._lock:
                        self._last_frame_at = utcnow_iso()
                    delay = 1.0 / max(0.1, float(self.spec.get("file_fps", 0) or 0))
                    if self.spec["kind"] == "file" and delay:
                        if self._sleep(min(delay, 1.0)):
                            break
                    now = time.monotonic()
                    if now - self._last_processed < 1.0 / max(0.1, self.spec["sample_fps"]):
                        continue
                    self._last_processed = now
                    self._process(image, cap, now)

                cap.release()
                if self._stop.is_set():
                    break
                if self.spec["kind"] == "file":
                    if self.spec.get("loop", False):
                        continue
                    self._set_status("finished", None)
                    return
                elapsed = time.monotonic() - opened_at
                if elapsed < 2.0:
                    self._set_status("reconnecting", "Stream dropped shortly after connecting")
                else:
                    self._set_status("reconnecting", "Stream ended; retrying")
                if self._sleep(backoff):
                    return
                backoff = min(backoff * 2, 30.0)
        except Exception as e:  # pragma: no cover - defensive thread boundary
            log.warning("Live source %s failed: %s", self.id, type(e).__name__)
            self._set_status("error", "Live source worker failed")
        finally:
            if self._status == "running":
                self._set_status("stopped", None)

    def _process(self, image, cap, now: float) -> None:
        import cv2

        from ..detection.drawing import draw_detections
        from ..models import FrameRef

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_index = int(cap.get(cv2.CAP_PROP_POS_FRAMES) or self._frames_read)
        ref = FrameRef(
            sequence_id=f"live:{self.id}",
            index=frame_index,
            filename=f"{self.id}@{utcnow_iso()}",
            timestamp=utcnow_iso(),
            image_width=image.shape[1],
            image_height=image.shape[0],
            rel_path=self.spec["display_target"],
        )
        try:
            dets = [
                d
                for d in self.manager.ctx.detector.detect(image, ref, self.spec.get("camera_id"))
                if d.confidence >= self.spec["threshold"]
            ]
        except Exception:
            log.warning("Live source %s detector failed", self.id)
            self._set_status("error", "Detector failed on a live frame")
            return
        self._frames_processed += 1
        self._detections_total += len(dets)
        self._streak = self._streak + 1 if dets else 0

        annotated = draw_detections(
            image,
            dets,
            metadata_lines=[
                f"live={self.spec['name']}  {self.spec['kind']}  frame={frame_index}",
                f"model={self.manager.ctx.detector.name}  dets={len(dets)}  experimental",
            ],
        )
        preview = encode_evidence_jpeg(annotated, max_side=960, quality=76)
        if preview:
            with self._lock:
                self._latest_jpeg = preview

        if (
            self._streak >= max(1, self.spec.get("min_consecutive", 3))
            and now - self._last_alert_at > self.manager.alert_cooldown_s
        ):
            self._last_alert_at = now
            self._streak = 0
            alert = self.manager.alerts.create(
                source_type=f"live_{self.spec['kind']}",
                source_id=self.id,
                camera_id=self.spec.get("camera_id"),
                event_time=utcnow_iso(),
                detector_name=self.manager.ctx.detector.name,
                detector_version=self.manager.ctx.detector.version,
                confidence=round(max((d.confidence for d in dets), default=0.0), 4),
                severity="info",
                verification_status="experimental",
                frame_ref=f"{self.spec['name']} frame {frame_index}",
                evidence_jpeg=preview,
                dedupe_key=f"live:{self.id}",
                notes=(
                    f"Experimental alert from live {self.spec['kind']} source "
                    f"'{self.spec['name']}'. Not a confirmed incident."
                ),
            )
            if alert:
                log.info("Live source %s created alert %s", self.id, alert["id"])
        _ = fps


class LiveSourceManager:
    def __init__(self, *, context, alerts: AlertService, data_root: Path):
        self.ctx = context
        self.alerts = alerts
        self.data_root = Path(data_root).expanduser().resolve()
        self.alert_cooldown_s = float(context.settings.alert_cooldown_s)
        self.max_sources = int(context.settings.live_max_sources)
        self._sources: dict[str, LiveRuntime] = {}
        self._lock = threading.Lock()

    def _validate_file(self, path_value: str) -> tuple[Path, str]:
        from ..datasets.paths import PathSafetyError, resolve_under

        try:
            path = resolve_under(self.data_root, path_value)
        except PathSafetyError as e:
            raise LiveSourceError("bad_path", str(e)) from e
        if not path.is_file() or path.suffix.lower() not in VIDEO_SUFFIXES:
            raise LiveSourceError(
                "bad_path", "Local test source must be an existing video under the data root"
            )
        return path, str(path.relative_to(self.data_root))

    def create(self, payload: dict) -> dict:
        with self._lock:
            if len(self._sources) >= self.max_sources:
                raise LiveSourceError("limit", "Maximum number of live sources reached")
        name = str(payload.get("name") or "").strip()
        if not (1 <= len(name) <= 80):
            raise LiveSourceError("invalid", "name must be 1-80 characters")
        kind = payload.get("kind")
        sample_fps = float(payload.get("sample_fps", 1.0))
        if not (0.1 <= sample_fps <= 10.0):
            raise LiveSourceError("invalid", "sample_fps must be between 0.1 and 10")
        threshold = float(payload.get("threshold", self.ctx.settings.detector.confidence_threshold))
        if not (0.0 <= threshold <= 1.0):
            raise LiveSourceError("invalid", "threshold must be between 0 and 1")
        camera_id = payload.get("camera_id")
        if camera_id and self.ctx.cameras.get(camera_id) is None:
            raise LiveSourceError("bad_camera", f"Unknown camera: {camera_id}")

        source_id = f"liv_{uuid.uuid4().hex[:10]}"
        if kind == "rtsp":
            raw = str(payload.get("url") or "").strip()
            parts = urlsplit(raw)
            if parts.scheme not in ("rtsp", "rtsps") or not parts.hostname:
                raise LiveSourceError("invalid", "A valid rtsp:// or rtsps:// URL is required")
            spec = {
                "id": source_id, "name": name, "kind": "rtsp", "target": raw,
                "display_target": sanitize_target(raw), "camera_id": camera_id,
                "sample_fps": sample_fps, "threshold": threshold, "loop": False,
                "min_consecutive": max(1, int(payload.get("min_consecutive", 3))),
            }
        elif kind == "file":
            path, rel = self._validate_file(str(payload.get("path") or "").strip())
            import cv2

            cap = cv2.VideoCapture(str(path))
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) if cap.isOpened() else 0.0
            cap.release()
            spec = {
                "id": source_id, "name": name, "kind": "file", "target": str(path),
                "display_target": f"file:{rel}", "camera_id": camera_id,
                "sample_fps": sample_fps, "threshold": threshold,
                "loop": bool(payload.get("loop", True)),
                "min_consecutive": max(1, int(payload.get("min_consecutive", 2))),
                "file_fps": fps,
            }
        else:
            raise LiveSourceError("invalid", "kind must be 'rtsp' or 'file'")

        runtime = LiveRuntime(self, spec)
        with self._lock:
            self._sources[source_id] = runtime
        runtime.start()
        return runtime.snapshot()

    def get(self, source_id: str) -> LiveRuntime:
        with self._lock:
            runtime = self._sources.get(source_id)
        if runtime is None:
            raise LiveSourceError("not_found", f"Unknown live source: {source_id}")
        return runtime

    def list(self) -> list[dict]:
        with self._lock:
            runtimes = list(self._sources.values())
        return [r.snapshot() for r in runtimes]

    def stop(self, source_id: str) -> dict:
        runtime = self.get(source_id)
        runtime.stop()
        return runtime.snapshot()

    def delete(self, source_id: str) -> None:
        runtime = self.get(source_id)
        runtime.stop()
        with self._lock:
            self._sources.pop(source_id, None)

    def shutdown(self) -> None:
        with self._lock:
            runtimes = list(self._sources.values())
            self._sources.clear()
        for runtime in runtimes:
            runtime.stop()

    def stats(self) -> dict:
        with self._lock:
            return {
                "total": len(self._sources),
                "running": sum(1 for r in self._sources.values() if r.snapshot()["status"] == "running"),
            }


def timestamp_now() -> str:
    return datetime.now(UTC).isoformat()
