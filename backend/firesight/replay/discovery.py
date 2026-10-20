from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


class SequenceError(Exception):
    """Raised for missing/empty/unreadable sequences."""


class CorruptFrameError(Exception):
    """Raised when an image file cannot be decoded."""


# Timestamp conventions are parsed ONLY where the filename pattern is explicit.
#  * ISO-like:  2022-06-24_12-33-10_123456.jpg  (Pyro-SDIS style)
#  * Compact:   20220624_123310.jpg
#  * Optional explicit event-relative offset token:  ..._t12.500s
# Anything else -> timestamp None (we never guess).
_ISO_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})[_T]"
    r"(?P<h>\d{2})[-:](?P<mi>\d{2})[-:](?P<s>\d{2})(?:[._](?P<us>\d{1,6}))?"
)
_COMPACT_RE = re.compile(
    r"^(?P<y>\d{4})(?P<mo>\d{2})(?P<d>\d{2})[_-](?P<h>\d{2})(?P<mi>\d{2})(?P<s>\d{2})"
)
_OFFSET_RE = re.compile(r"_t(?P<off>\d+(?:\.\d+)?)s")


def parse_timestamp(filename: str) -> tuple[datetime | None, float | None]:
    """Return (timestamp, event_offset_seconds) parsed from a verified filename pattern."""
    stem = Path(filename).stem
    offset: float | None = None
    m_off = _OFFSET_RE.search(stem)
    if m_off:
        offset = float(m_off.group("off"))
        stem = stem[: m_off.start()]
    m = _ISO_RE.match(stem) or _COMPACT_RE.match(stem)
    if not m:
        return None, offset
    g = m.groupdict()
    us = int((g.get("us") or "0").ljust(6, "0"))
    try:
        ts = datetime(
            int(g["y"]), int(g["mo"]), int(g["d"]),
            int(g["h"]), int(g["mi"]), int(g["s"]), us,
        )
    except ValueError:
        return None, offset
    return ts, offset


@dataclass(frozen=True)
class FrameFile:
    path: Path
    rel_path: str
    filename: str
    index: int
    timestamp: datetime | None = None
    event_offset_s: float | None = None


def _sort_key(p: Path) -> tuple[str, int, str]:
    return (p.parent.as_posix(), len(p.stem), p.name)


def discover_frames(
    sequence_dir: Path | str,
    *,
    recursive: bool = True,
    extensions: set[str] | None = None,
) -> list[FrameFile]:
    root = Path(sequence_dir)
    if not root.exists():
        raise SequenceError(f"Sequence directory does not exist: {root}")
    if not root.is_dir():
        raise SequenceError(f"Not a directory: {root}")
    exts = {e.lower() for e in (extensions or IMAGE_EXTENSIONS)}
    if recursive:
        paths = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts]
    else:
        paths = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in exts]
    if not paths:
        raise SequenceError(f"No image files ({sorted(exts)}) found under: {root}")
    paths.sort(key=_sort_key)
    frames: list[FrameFile] = []
    for i, p in enumerate(paths):
        ts, off = parse_timestamp(p.name)
        frames.append(
            FrameFile(
                path=p,
                rel_path=p.relative_to(root).as_posix(),
                filename=p.name,
                index=i,
                timestamp=ts,
                event_offset_s=off,
            )
        )
    return frames


def load_frame(frame: FrameFile | Path) -> tuple[np.ndarray, FrameFile | None]:
    """Decode an image. Raises CorruptFrameError for unreadable files."""
    ff = None
    path: Path
    if isinstance(frame, FrameFile):
        ff = frame
        path = frame.path
    else:
        path = frame
    try:
        data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    except OSError as e:
        raise CorruptFrameError(f"Unreadable image file: {path} ({e})") from e
    if data.size == 0:
        raise CorruptFrameError(f"Empty image file: {path}")
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        raise CorruptFrameError(f"Corrupt or undecodable image: {path}")
    return img, ff
