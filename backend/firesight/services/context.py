"""Application context: wiring of settings, database, detectors and services."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from ..config import Settings, get_settings
from ..db import Database, utcnow_iso
from ..detection.base import BaseDetector, build_detector
from ..enums import CalibrationStatus, Provenance
from ..models import CameraConfig
from ..vlm.provider import BaseVlmProvider, build_vlm_provider

log = logging.getLogger(__name__)


class SequenceRegistrationError(ValueError):
    """Sequence registration failed; ``reason`` maps to an HTTP status in the router."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class CameraRepo:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, cam: CameraConfig) -> None:
        now = utcnow_iso()
        self.db.execute(
            """INSERT INTO cameras (id, name, latitude, longitude, height_m, heading_deg,
                 hfov_deg, image_width, image_height, calibration_status, calibration_source,
                 calibration_uncertainty_deg, provenance, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name, latitude=excluded.latitude, longitude=excluded.longitude,
                 height_m=excluded.height_m, heading_deg=excluded.heading_deg,
                 hfov_deg=excluded.hfov_deg, image_width=excluded.image_width,
                 image_height=excluded.image_height, calibration_status=excluded.calibration_status,
                 calibration_source=excluded.calibration_source,
                 calibration_uncertainty_deg=excluded.calibration_uncertainty_deg,
                 provenance=excluded.provenance, notes=excluded.notes, updated_at=excluded.updated_at""",
            (
                cam.id, cam.name, cam.latitude, cam.longitude, cam.height_m, cam.heading_deg,
                cam.hfov_deg, cam.image_width, cam.image_height, cam.calibration_status.value,
                cam.calibration_source, cam.calibration_uncertainty_deg, cam.provenance.value,
                cam.notes, now, now,
            ),
        )

    def get(self, camera_id: str) -> CameraConfig | None:
        row = self.db.query_one("SELECT * FROM cameras WHERE id=?", (camera_id,))
        return self._row_to_cam(row) if row else None

    def list(self) -> list[CameraConfig]:
        rows = self.db.query("SELECT * FROM cameras ORDER BY id")
        return [self._row_to_cam(r) for r in rows]

    def as_dict(self) -> dict[str, CameraConfig]:
        return {c.id: c for c in self.list()}

    @staticmethod
    def _row_to_cam(row: dict) -> CameraConfig:
        return CameraConfig(
            id=row["id"], name=row["name"], latitude=row["latitude"], longitude=row["longitude"],
            height_m=row["height_m"], heading_deg=row["heading_deg"], hfov_deg=row["hfov_deg"],
            image_width=row["image_width"], image_height=row["image_height"],
            calibration_status=CalibrationStatus(row["calibration_status"]),
            calibration_source=row["calibration_source"],
            calibration_uncertainty_deg=row["calibration_uncertainty_deg"],
            provenance=Provenance(row["provenance"]), notes=row["notes"],
        )


class AppContext:
    """Holds the process-wide application state (single-process prototype)."""

    def __init__(self, settings: Settings | None = None, db: Database | None = None):
        self.settings = settings or get_settings()
        self.db = db or Database(self.settings.database_path)
        self.db.initialize()
        self.cameras = CameraRepo(self.db)
        self.detector: BaseDetector = build_detector(self.settings)
        self.vlm: BaseVlmProvider = build_vlm_provider(self.settings.vlm, mode=self.settings.mode)
        self._lock = threading.Lock()
        self.replay_manager = None  # set below to avoid circular import
        from .replay_manager import ReplayManager

        self.replay_manager = ReplayManager(self)

        from .alerts import AlertService
        from .live import LiveSourceManager
        from .video_analysis import VideoAnalysisService
        from .video_library import VideoLibrary

        data_root = Path(self.settings.data_root).expanduser().resolve()
        self.alerts = AlertService(
            self.db,
            data_root / "alerts",
            cooldown_s=self.settings.alert_cooldown_s,
        )
        self.videos = VideoLibrary(data_root)
        self.video_analysis = VideoAnalysisService(
            context=self,
            library=self.videos,
            alerts=self.alerts,
            data_root=data_root,
        )
        self.live = LiveSourceManager(context=self, alerts=self.alerts, data_root=data_root)
        self._overrides: dict[str, object] = {}

    # -- startup -----------------------------------------------------
    def startup(self) -> None:
        self.apply_db_overrides()
        if self.settings.mode == "demo":
            self.seed_demo()
        log.info(
            "FireSight started (mode=%s, detector=%s, vlm=%s)",
            self.settings.mode, self.detector.name, self.vlm.name,
        )

    def shutdown(self) -> None:
        """Stop all replay sessions and release background threads."""
        if self.replay_manager is not None:
            for rid in list(self.replay_manager.sessions):
                self.replay_manager.cleanup(rid)
        if getattr(self, "live", None) is not None:
            self.live.shutdown()
        log.info("FireSight context shut down")

    def seed_demo(self) -> None:
        """Register the deterministic demo scenario: cameras + sequences."""
        from ..demo.scenario import demo_cameras, ensure_demo_sequences
        from ..replay.discovery import discover_frames

        for cam in demo_cameras():
            self.cameras.upsert(cam)
        seq_dirs = ensure_demo_sequences(self.settings.data_root)
        for seq_id, seq_dir in seq_dirs.items():
            frames = discover_frames(seq_dir)
            spec_name = seq_id
            camera_id = "sim-cam-a" if "alpha" in seq_id else "sim-cam-b"
            from ..db import dumps

            self.db.execute(
                """INSERT INTO sequences (id, name, dataset, dataset_provenance, root_path,
                     frame_count, image_width, image_height, start_ts, end_ts, manifest_json,
                     provenance, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     frame_count=excluded.frame_count, root_path=excluded.root_path,
                     start_ts=excluded.start_ts, end_ts=excluded.end_ts""",
                (
                    seq_id, spec_name, "FireSight demo fixtures (synthetic)",
                    "simulated", str(seq_dir), len(frames),
                    640, 360,
                    frames[0].timestamp.isoformat() if frames and frames[0].timestamp else None,
                    frames[-1].timestamp.isoformat() if frames and frames[-1].timestamp else None,
                    dumps({"camera_id": camera_id, "synthetic": True, "fps": 5}),
                    Provenance.SIMULATED.value, utcnow_iso(),
                ),
            )

    def register_sequence(
        self,
        *,
        sequence_id: str,
        root_path: str,
        camera_id: str | None = None,
        name: str | None = None,
    ) -> dict:
        """Register a directory of image frames as a REAL sequence.

        The directory must live under the configured data root, contain at least
        one JPG/JPEG/PNG frame, and (if a camera_id is given) reference an
        existing camera. Existing sequence IDs are never overwritten.

        Raises :class:`SequenceRegistrationError` with ``reason`` in
        {"duplicate", "bad_path", "empty", "bad_camera"}.
        """
        import json as _json

        from ..datasets.paths import PathSafetyError, resolve_under
        from ..replay.discovery import SequenceError, discover_frames, load_frame

        if self.db.query_one("SELECT id FROM sequences WHERE id=?", (sequence_id,)):
            raise SequenceRegistrationError(
                "duplicate", f"Sequence already exists: {sequence_id}"
            )

        if camera_id is not None and self.cameras.get(camera_id) is None:
            raise SequenceRegistrationError("bad_camera", f"Unknown camera: {camera_id}")

        try:
            seq_dir = resolve_under(self.settings.data_root, root_path)
        except PathSafetyError as e:
            raise SequenceRegistrationError("bad_path", str(e)) from e
        if not seq_dir.exists() or not seq_dir.is_dir():
            raise SequenceRegistrationError(
                "bad_path", f"Directory does not exist under the data root: {root_path}"
            )

        try:
            frames = discover_frames(seq_dir)
        except SequenceError as e:
            raise SequenceRegistrationError("empty", str(e)) from e
        if not frames:
            raise SequenceRegistrationError(
                "empty", f"No JPG/JPEG/PNG frames found under: {root_path}"
            )

        warnings: list[str] = []
        with_ts = [f for f in frames if f.timestamp is not None]
        timestamps_available = len(with_ts) == len(frames)
        if not with_ts:
            warnings.append(
                "No frame filenames matched a supported timestamp pattern; timestamps "
                "are unknown. Cross-camera time association will be unreliable."
            )
        elif not timestamps_available:
            warnings.append(
                f"Only {len(with_ts)}/{len(frames)} frames have a parsed timestamp; the "
                "remainder are treated as unknown."
            )

        width: int | None = None
        height: int | None = None
        try:
            img, _ = load_frame(frames[0].path)
            height, width = int(img.shape[0]), int(img.shape[1])
        except Exception as e:  # pragma: no cover - unreadable first frame
            warnings.append(f"Could not decode the first frame for dimensions: {e}")

        if height is not None and width is not None and camera_id is not None:
            cam = self.cameras.get(camera_id)
            if cam is not None and (cam.image_width, cam.image_height) != (width, height):
                warnings.append(
                    f"Camera {camera_id} is {cam.image_width}x{cam.image_height} but the "
                    f"footage is {width}x{height}; pixel-to-bearing assumes matching dimensions."
                )

        start_ts = with_ts[0].timestamp.isoformat() if with_ts else None
        end_ts = with_ts[-1].timestamp.isoformat() if with_ts else None
        seq_name = name or sequence_id
        manifest = {
            "camera_id": camera_id,
            "synthetic": False,
            "timestamps_available": timestamps_available,
            "frames_with_timestamp": len(with_ts),
        }
        self.db.execute(
            """INSERT INTO sequences (id, name, dataset, dataset_provenance, root_path,
                 frame_count, image_width, image_height, start_ts, end_ts, manifest_json,
                 provenance, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sequence_id, seq_name, "User-supplied footage (registered)", "real",
                str(seq_dir), len(frames), width, height, start_ts, end_ts,
                _json.dumps(manifest), Provenance.REAL.value, utcnow_iso(),
            ),
        )
        return {
            "id": sequence_id,
            "name": seq_name,
            "root_path": str(seq_dir),
            "frame_count": len(frames),
            "image_width": width,
            "image_height": height,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "timestamps_available": timestamps_available,
            "camera_id": camera_id,
            "provenance": Provenance.REAL.value,
            "synthetic": False,
            "warnings": warnings,
        }

    # -- runtime config overrides -----------------------------------
    def apply_db_overrides(self) -> None:
        rows = self.db.query("SELECT key, value_json FROM settings_kv")
        import json

        for row in rows:
            try:
                self._overrides[row["key"]] = json.loads(row["value_json"])
            except json.JSONDecodeError:
                continue
        self._apply_overrides_to_settings()

    OVERRIDE_KEYS = {
        "mode",
        "detector.kind", "detector.confidence_threshold", "detector.iou_threshold",
        "detector.image_size",
        "temporal.window_seconds", "temporal.min_positive_observations",
        "temporal.min_confidence", "temporal.min_persistence_ratio",
        "temporal.max_gap_seconds", "temporal.grace_seconds",
        "replay_speed_default",
        "vlm.base_url", "vlm.model", "vlm.timeout_seconds",
    }

    def _apply_overrides_to_settings(self) -> None:
        s = self.settings
        for key, value in self._overrides.items():
            try:
                if key == "mode":
                    s.mode = value  # type: ignore[assignment]
                elif key == "detector.kind":
                    s.detector.kind = value  # type: ignore[assignment]
                elif key == "detector.confidence_threshold":
                    s.detector.confidence_threshold = float(value)  # type: ignore[arg-type]
                elif key == "detector.iou_threshold":
                    s.detector.iou_threshold = float(value)  # type: ignore[arg-type]
                elif key == "detector.image_size":
                    s.detector.image_size = int(value)  # ignore: arg-type
                elif key.startswith("temporal."):
                    attr = key.split(".", 1)[1]
                    current = getattr(s.temporal, attr)
                    setattr(s.temporal, attr, type(current)(value))
                elif key == "replay_speed_default":
                    s.replay_speed_default = float(value)  # type: ignore[arg-type]
                elif key == "vlm.base_url":
                    s.vlm.base_url = str(value) if value else None
                elif key == "vlm.model":
                    s.vlm.model = str(value) if value else None
                elif key == "vlm.timeout_seconds":
                    s.vlm.timeout_seconds = float(value)  # type: ignore[arg-type]
            except (ValueError, TypeError) as e:
                log.warning("Ignoring bad override %s=%r: %s", key, value, e)

    def set_overrides(self, values: dict[str, object]) -> list[str]:
        import json

        applied: list[str] = []
        for key, value in values.items():
            if key not in self.OVERRIDE_KEYS:
                raise ValueError(f"Unknown or non-configurable setting: {key}")
            self._overrides[key] = value
            self.db.execute(
                "INSERT INTO settings_kv(key, value_json, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
                "updated_at=excluded.updated_at",
                (key, json.dumps(value), utcnow_iso()),
            )
            applied.append(key)
        self._apply_overrides_to_settings()
        # rebuild detector/vlm if their inputs changed
        self.detector = build_detector(self.settings)
        self.vlm = build_vlm_provider(self.settings.vlm, mode=self.settings.mode)
        return applied

    @property
    def overrides(self) -> dict[str, object]:
        return dict(self._overrides)


_context: AppContext | None = None
_context_lock = threading.Lock()


def get_context() -> AppContext:
    global _context
    with _context_lock:
        if _context is None:
            _context = AppContext()
        return _context


def set_context(ctx: AppContext | None) -> None:
    global _context
    with _context_lock:
        _context = ctx
