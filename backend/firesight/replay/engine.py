from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .discovery import CorruptFrameError, FrameFile, load_frame

log = logging.getLogger(__name__)


@dataclass
class FramePacket:
    index: int
    filename: str
    rel_path: str
    image: np.ndarray
    timestamp: datetime | None
    event_offset_s: float | None
    sequence_id: str = ""

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])


def iter_frames(
    frames: list[FrameFile],
    *,
    sequence_id: str = "",
    start: int = 0,
    stop_on_error: bool = False,
) -> Iterator[FramePacket]:
    """Stream frames one at a time without loading the whole sequence."""
    for i in range(start, len(frames)):
        ff = frames[i]
        try:
            img, _ = load_frame(ff)
        except CorruptFrameError as e:
            log.warning("Skipping corrupt frame %s: %s", ff.rel_path, e)
            if stop_on_error:
                raise
            continue
        yield FramePacket(
            index=ff.index,
            filename=ff.filename,
            rel_path=ff.rel_path,
            image=img,
            timestamp=ff.timestamp,
            event_offset_s=ff.event_offset_s,
            sequence_id=sequence_id,
        )


class ReplayEngine:
    """Deterministic, pausable replay of an image sequence.

    Thread-safe. Drives frames to `on_frame` at `base_fps / speed` Hz.
    With `no_wait` (tests/CLI) frames are emitted as fast as possible.
    """

    def __init__(
        self,
        frames: list[FrameFile],
        *,
        sequence_id: str = "",
        speed: float = 1.0,
        base_fps: float = 5.0,
        no_wait: bool = False,
        loop: bool = False,
        on_frame: Callable[[FramePacket], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_finish: Callable[[], None] | None = None,
    ):
        if speed <= 0:
            raise ValueError("speed must be > 0")
        if not frames:
            raise ValueError("ReplayEngine requires a non-empty frame list")
        self.frames = frames
        self.sequence_id = sequence_id
        self.speed = speed
        self.base_fps = base_fps
        self.no_wait = no_wait
        self.loop = loop
        self.on_frame = on_frame
        self.on_error = on_error
        self.on_finish = on_finish

        self._index = 0
        self._position_lock = threading.Lock()
        self._control_lock = threading.Lock()
        self._pause_event = threading.Event()
        self._pause_event.set()  # not paused
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._step_sem = threading.Semaphore(0)
        self._last_packet: FramePacket | None = None
        self._error: str | None = None
        self.emitted = 0

    # ---- state -----------------------------------------------------
    @property
    def position(self) -> int:
        with self._position_lock:
            return self._index

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def finished(self) -> bool:
        return self._stop_event.is_set() and not self.loop

    @property
    def paused(self) -> bool:
        return not self._pause_event.is_set()

    @property
    def error(self) -> str | None:
        return self._error

    def last_frame(self) -> FramePacket | None:
        return self._last_packet

    # ---- controls --------------------------------------------------
    def start(self) -> None:
        with self._control_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="replay", daemon=True)
            self._thread.start()

    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()

    def reset(self) -> None:
        with self._position_lock:
            self._index = 0
        self._last_packet = None
        self.emitted = 0
        self._error = None
        self._stop_event.clear()
        self._pause_event.set()

    def step(self, n: int = 1) -> FramePacket | None:
        """Advance exactly n frames synchronously (works while paused/stopped)."""
        packet: FramePacket | None = None
        for _ in range(n):
            packet = self._emit_one()
            if packet is None:
                break
        return packet

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        self._pause_event.set()  # unblock
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=timeout)

    # ---- internals -------------------------------------------------
    def _next_index(self) -> int | None:
        with self._position_lock:
            if self._index >= len(self.frames):
                if self.loop:
                    self._index = 0
                else:
                    return None
            idx = self._index
            self._index += 1
            return idx

    def _emit_one(self) -> FramePacket | None:
        idx = self._next_index()
        if idx is None:
            if self.on_finish:
                self.on_finish()
            return None
        ff = self.frames[idx]
        try:
            img, _ = load_frame(ff)
        except CorruptFrameError as e:
            self._error = str(e)
            log.warning("Corrupt frame at index %d (%s): %s", idx, ff.rel_path, e)
            if self.on_error:
                self.on_error(e)
            return None
        packet = FramePacket(
            index=ff.index,
            filename=ff.filename,
            rel_path=ff.rel_path,
            image=img,
            timestamp=ff.timestamp,
            event_offset_s=ff.event_offset_s,
            sequence_id=self.sequence_id,
        )
        self._last_packet = packet
        self.emitted += 1
        if self.on_frame:
            self.on_frame(packet)
        return packet

    def _run(self) -> None:
        interval = self.base_fps and (1.0 / self.base_fps) or 0.2
        while not self._stop_event.is_set():
            self._pause_event.wait()
            if self._stop_event.is_set():
                break
            start = time.monotonic()
            packet = self._emit_one()
            if packet is None:
                break
            if self.no_wait:
                continue
            elapsed = time.monotonic() - start
            delay = max(0.0, interval / self.speed - elapsed)
            if delay:
                self._stop_event.wait(delay)
        if self.on_finish and not self._stop_event.is_set():
            self.on_finish()
