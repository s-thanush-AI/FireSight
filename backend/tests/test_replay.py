from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from firesight.replay.discovery import (
    CorruptFrameError,
    FrameFile,
    SequenceError,
    discover_frames,
    load_frame,
    parse_timestamp,
)
from firesight.replay.engine import ReplayEngine, iter_frames


def _write_img(path: Path, value: int = 128) -> None:
    img = np.full((8, 8, 3), value, dtype=np.uint8)
    ok, enc = cv2.imencode(".png", img)
    assert ok
    path.write_bytes(enc.tobytes())


@pytest.fixture
def seq_dir(tmp_path):
    d = tmp_path / "seq"
    d.mkdir()
    for i in range(5):
        _write_img(d / f"frame_{i:03d}.png", i * 10)
    return d


class TestDiscovery:
    def test_discovers_sorted(self, seq_dir):
        frames = discover_frames(seq_dir)
        assert [f.filename for f in frames] == [f"frame_{i:03d}.png" for i in range(5)]
        assert [f.index for f in frames] == list(range(5))

    def test_missing_dir_raises(self, tmp_path):
        with pytest.raises(SequenceError):
            discover_frames(tmp_path / "nope")

    def test_empty_dir_raises(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        with pytest.raises(SequenceError):
            discover_frames(d)

    def test_not_a_dir_raises(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        with pytest.raises(SequenceError):
            discover_frames(f)

    def test_extension_filter(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"x")
        (tmp_path / "b.PNG").write_bytes(b"x")
        (tmp_path / "c.gif").write_bytes(b"x")
        frames = discover_frames(tmp_path)
        assert sorted(f.filename for f in frames) == ["a.jpg", "b.PNG"]

    def test_non_recursive_flag(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        _write_img(tmp_path / "top.png")
        _write_img(sub / "nested.png")
        assert len(discover_frames(tmp_path, recursive=True)) == 2
        assert len(discover_frames(tmp_path, recursive=False)) == 1

    def test_numeric_ordering_not_lexicographic(self, tmp_path):
        for i in (1, 2, 10, 11):
            _write_img(tmp_path / f"f_{i:05d}.png")
        frames = discover_frames(tmp_path)
        assert [f.filename for f in frames] == [
            "f_00001.png", "f_00002.png", "f_00010.png", "f_00011.png",
        ]


class TestTimestamps:
    def test_iso_pattern(self):
        ts, off = parse_timestamp("2024-07-12_15-30-00_000500.png")
        assert ts == datetime(2024, 7, 12, 15, 30, 0, 500)
        assert off is None
        ts2, _ = parse_timestamp("2024-07-12_15-30-00_123456.png")
        assert ts2 == datetime(2024, 7, 12, 15, 30, 0, 123456)

    def test_compact_pattern(self):
        ts, off = parse_timestamp("20240712_153000.jpg")
        assert ts == datetime(2024, 7, 12, 15, 30, 0)
        assert off is None

    def test_offset_token(self):
        ts, off = parse_timestamp("2024-07-12_15-30-00_000000_t12.500s.png")
        assert off == pytest.approx(12.5)
        assert ts == datetime(2024, 7, 12, 15, 30, 0)

    def test_unknown_convention_returns_none(self):
        ts, off = parse_timestamp("IMG_9381.PNG")
        assert ts is None and off is None
        ts, off = parse_timestamp("fire_day2_frame17.jpg")
        assert ts is None and off is None

    def test_invalid_date_returns_none(self):
        ts, _ = parse_timestamp("2024-13-45_99-99-99.png")
        assert ts is None


class TestLoadFrame:
    def test_load_ok(self, seq_dir):
        frames = discover_frames(seq_dir)
        img, ff = load_frame(frames[0])
        assert img.shape == (8, 8, 3)
        assert ff is frames[0]

    def test_corrupt_raises(self, tmp_path):
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not an image at all")
        with pytest.raises(CorruptFrameError):
            load_frame(bad)

    def test_empty_file_raises(self, tmp_path):
        bad = tmp_path / "empty.png"
        bad.write_bytes(b"")
        with pytest.raises(CorruptFrameError):
            load_frame(bad)


class TestEngine:
    def _frames(self, tmp_path, n=5):
        d = tmp_path / "s"
        d.mkdir()
        for i in range(n):
            _write_img(d / f"f_{i:04d}.png")
        return discover_frames(d)

    def test_iter_frames_streams(self, tmp_path):
        frames = self._frames(tmp_path)
        packets = list(iter_frames(frames, sequence_id="s1"))
        assert len(packets) == 5
        assert packets[0].sequence_id == "s1"
        assert packets[2].index == 2

    def test_iter_frames_skips_corrupt(self, tmp_path):
        frames = self._frames(tmp_path, 4)
        frames[1].path.write_bytes(b"garbage")
        packets = list(iter_frames(frames))
        assert [p.index for p in packets] == [0, 2, 3]

    def test_iter_frames_stop_on_error(self, tmp_path):
        frames = self._frames(tmp_path, 3)
        frames[1].path.write_bytes(b"garbage")
        with pytest.raises(CorruptFrameError):
            list(iter_frames(frames, stop_on_error=True))

    def test_step_and_pause(self, tmp_path):
        frames = self._frames(tmp_path)
        seen = []
        eng = ReplayEngine(frames, sequence_id="s", no_wait=True, on_frame=lambda p: seen.append(p.index))
        p1 = eng.step()
        assert p1.index == 0 and seen == [0]
        eng.step(2)
        assert eng.position == 3
        assert seen == [0, 1, 2]
        eng.pause()
        assert eng.paused
        eng.resume()
        assert not eng.paused

    def test_reset(self, tmp_path):
        frames = self._frames(tmp_path)
        eng = ReplayEngine(frames, no_wait=True)
        eng.step(5)
        assert eng.position == 5
        eng.reset()
        assert eng.position == 0
        assert eng.emitted == 0

    def test_run_to_completion(self, tmp_path):
        frames = self._frames(tmp_path, 4)
        seen = []
        finished = []
        eng = ReplayEngine(
            frames, no_wait=True, speed=10.0,
            on_frame=lambda p: seen.append(p.index),
            on_finish=lambda: finished.append(True),
        )
        eng.start()
        import time

        deadline = time.time() + 5
        while len(seen) < 4 and time.time() < deadline:
            time.sleep(0.01)
        eng.stop()
        assert seen == [0, 1, 2, 3]
        assert finished

    def test_background_thread_with_speed(self, tmp_path):
        frames = self._frames(tmp_path, 3)
        seen = []
        eng = ReplayEngine(frames, speed=50.0, base_fps=50.0, on_frame=lambda p: seen.append(p.index))
        eng.start()
        import time

        deadline = time.time() + 5
        while len(seen) < 3 and time.time() < deadline:
            time.sleep(0.02)
        eng.stop()
        assert seen == [0, 1, 2]

    def test_invalid_speed(self, tmp_path):
        frames = self._frames(tmp_path)
        with pytest.raises(ValueError):
            ReplayEngine(frames, speed=0)

    def test_empty_frames_rejected(self):
        with pytest.raises(ValueError):
            ReplayEngine([], no_wait=True)

    def test_corrupt_current_frame_stops_cleanly(self, tmp_path):
        frames = self._frames(tmp_path, 3)
        frames[0].path.write_bytes(b"bad")
        errors = []
        eng = ReplayEngine(frames, no_wait=True, on_error=lambda e: errors.append(e))
        result = eng.step()
        assert result is None
        assert errors and isinstance(errors[0], CorruptFrameError)
        assert eng.error is not None
        # frame 1 still reachable
        p = eng.step()
        assert p is not None and p.index == 1

    def test_frame_file_frozen(self):
        from dataclasses import FrozenInstanceError

        ff = FrameFile(
            path=Path("/tmp/x.png"), rel_path="x.png", filename="x.png", index=0,
            timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        )
        with pytest.raises(FrozenInstanceError):
            ff.index = 5  # type: ignore[misc]
