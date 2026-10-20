"""Render an annotated demo video (animated GIF) from a replay sequence.

Deterministic and dependency-light: frames are decoded with OpenCV, annotated
with the project's own detector/drawing code, and encoded to an animated GIF
with Pillow. No ffmpeg, no network, no model downloads.

This is a demo aid only. The output is SIMULATED imagery annotated by a
heuristic detector; it is not evidence of model accuracy.
"""

from __future__ import annotations

from pathlib import Path

import cv2
from PIL import Image

from ..config import Settings
from ..detection.base import build_detector
from ..detection.drawing import draw_detections
from ..models import FrameRef


class DemoVideoError(RuntimeError):
    """Raised when a demo video cannot be produced (missing input, no frames)."""


def _list_frames(sequence_dir: Path) -> list[Path]:
    frames = sorted(p for p in sequence_dir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"})
    return frames


def render_annotated_video(
    sequence_dir: Path,
    out_path: Path,
    *,
    sequence_id: str,
    camera_id: str | None = None,
    settings: Settings | None = None,
    max_width: int = 480,
    frame_duration_ms: int = 200,
    every: int = 1,
    watermark: str = "SIMULATED - NOT OPERATIONAL",
) -> Path:
    """Annotate every ``every``-th frame and write an animated GIF to ``out_path``.

    Returns the written path. Raises :class:`DemoVideoError` if the sequence has
    no decodable frames or the detector is unavailable.
    """
    sequence_dir = Path(sequence_dir)
    if not sequence_dir.is_dir():
        raise DemoVideoError(f"sequence directory not found: {sequence_dir}")
    frame_paths = _list_frames(sequence_dir)
    if not frame_paths:
        raise DemoVideoError(f"no image frames found under {sequence_dir}")

    settings = settings or Settings()
    detector = build_detector(settings)
    if not detector.available:
        raise DemoVideoError(
            f"detector '{detector.name}' unavailable: {detector.unavailable_reason}"
        )

    images: list[Image.Image] = []
    for i, path in enumerate(frame_paths):
        if every > 1 and i % every != 0:
            continue
        raw = cv2.imread(str(path))
        if raw is None:
            raise DemoVideoError(f"failed to decode frame: {path}")
        ref = FrameRef(
            sequence_id=sequence_id,
            index=i,
            filename=path.name,
            image_width=raw.shape[1],
            image_height=raw.shape[0],
            rel_path=path.name,
        )
        detections = detector.detect(raw, ref, camera_id)
        annotated = draw_detections(
            raw,
            detections,
            watermark=watermark,
            metadata_lines=[
                f"{sequence_id}  frame {i}/{len(frame_paths) - 1}",
                f"detector {detector.name} v{detector.version} "
                f"({detector.provenance.value if detector.provenance else 'unknown'})",
                f"detections: {len(detections)}",
            ],
        )
        rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        if img.width > max_width:
            scale = max_width / img.width
            img = img.resize((max_width, int(img.height * scale)))
        images.append(img)

    if not images:
        raise DemoVideoError("no frames selected for export (check 'every')")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    duration = max(frame_duration_ms, 20)
    images[0].save(
        out_path,
        save_all=True,
        append_images=images[1:],
        duration=duration,
        loop=0,
        optimize=False,
    )
    return out_path
