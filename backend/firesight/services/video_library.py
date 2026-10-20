"""Local, bounded video catalogue and HTTP range helpers.

Only files under ``<data_root>/videos`` are exposed. Video files are never
copied into memory; streaming yields fixed-size chunks so a large replay does
not exhaust RAM.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
CHUNK = 256 * 1024


class VideoError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class VideoLibrary:
    def __init__(self, data_root: Path):
        self.data_root = Path(data_root)
        self.root = (self.data_root / "videos").resolve()
        self.manifest_path = self.root / "manifest.json"
        self._cache: dict[str, tuple[float, int, dict]] = {}

    def _manifest(self) -> dict:
        try:
            raw = json.loads(self.manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _resolve(self, video_id: str) -> Path:
        if not ID_RE.match(video_id or ""):
            raise VideoError("not_found", f"Unknown video: {video_id}")
        for suffix in VIDEO_SUFFIXES:
            candidate = (self.root / f"{video_id}{suffix}").resolve()
            try:
                candidate.relative_to(self.root)
            except ValueError:
                continue
            if candidate.is_file():
                return candidate
        raise VideoError("not_found", f"Unknown video: {video_id}")

    def _probe(self, video_id: str, path: Path) -> dict:
        import cv2

        st = path.stat()
        cached = self._cache.get(video_id)
        if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
            return cached[2]
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise VideoError("unreadable", f"Could not open video: {video_id}")
        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        finally:
            cap.release()
        meta = self._manifest().get(video_id, {})
        duration = frame_count / fps if fps > 0 else None
        info = {
            "id": video_id,
            "filename": path.name,
            "size_bytes": st.st_size,
            "fps": round(fps, 3),
            "frame_count": frame_count,
            "width": width,
            "height": height,
            "duration_s": round(duration, 3) if duration is not None else None,
            "label": meta.get("label") or video_id,
            "is_time_lapse": bool(meta.get("is_time_lapse", False)),
            "camera_id": meta.get("camera_id"),
            "capture_start_utc": meta.get("capture_start_utc"),
            "capture_end_utc": meta.get("capture_end_utc"),
            "source_archive": meta.get("source_archive"),
            "notes": meta.get(
                "notes",
                "Time-lapse compilation of still frames; not continuous CCTV. "
                "Frame-to-still alignment is not independently verified.",
            ),
            "stream_url": f"/api/v1/videos/{video_id}/stream",
        }
        self._cache[video_id] = (st.st_mtime, st.st_size, info)
        return info

    def list(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        items: list[dict] = []
        for path in sorted(self.root.iterdir()):
            if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES and ID_RE.match(path.stem):
                try:
                    items.append(self._probe(path.stem, path))
                except VideoError as e:
                    log.warning("Skipping video %s: %s", path.name, e)
        return items

    def get(self, video_id: str) -> dict:
        return self._probe(video_id, self._resolve(video_id))

    def path_for(self, video_id: str) -> Path:
        return self._resolve(video_id)

    def parse_range(self, header: str | None, size: int) -> tuple[int, int, bool]:
        """Return (start, end_inclusive, partial). Raises VideoError on bad ranges."""
        if not header:
            return 0, size - 1, False
        match = re.match(r"^bytes=(\d*)-(\d*)$", header.strip())
        if not match:
            raise VideoError("bad_range", "Only a single 'bytes=start-end' range is supported")
        raw_start, raw_end = match.groups()
        if raw_start == "" and raw_end == "":
            raise VideoError("bad_range", "Empty byte range")
        if raw_start == "":
            length = int(raw_end)
            if length <= 0:
                raise VideoError("bad_range", "Invalid suffix range")
            start = max(0, size - length)
            end = size - 1
        else:
            start = int(raw_start)
            end = int(raw_end) if raw_end else size - 1
        if start >= size or start > end:
            raise VideoError("bad_range", "Range starts beyond the file")
        return start, min(end, size - 1), True

    def iter_bytes(self, path: Path, start: int, end: int):
        remaining = end - start + 1
        with path.open("rb") as fh:
            fh.seek(start)
            while remaining > 0:
                chunk = fh.read(min(CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
