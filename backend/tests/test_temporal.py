from datetime import UTC, datetime, timedelta

import pytest

from firesight.config import TemporalSettings
from firesight.enums import Provenance
from firesight.models import BBox, Detection, FrameRef
from firesight.temporal.tracker import TemporalTracker

T0 = datetime(2024, 7, 12, 15, 30, 0, tzinfo=UTC)


def det(x1, y1, x2, y2, conf=0.6, cam="cam-a", idx=0):
    return Detection(
        frame=FrameRef(sequence_id="seq", index=idx, filename=f"f{idx}.png", image_width=640),
        camera_id=cam,
        class_name="smoke",
        confidence=conf,
        bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2),
        model_name="test",
        provenance=Provenance.PREDICTED,
    )


def settings(**kw):
    base = dict(
        window_seconds=8.0,
        min_positive_observations=3,
        min_confidence=0.3,
        min_persistence_ratio=0.5,
        max_gap_seconds=2.0,
        grace_seconds=5.0,
    )
    base.update(kw)
    return TemporalSettings(**base)


class TestTemporalConfirmation:
    def test_confirms_after_min_observations(self):
        tr = TemporalTracker("cam-a", settings())
        alerts = []
        for i in range(3):
            alerts += tr.update([det(10, 10, 50, 40, 0.6, idx=i)], T0 + timedelta(seconds=i))
        assert len(alerts) == 1
        a = alerts[0]
        assert a.confirmed is True
        assert a.positive_count == 3
        assert a.provenance == Provenance.HEURISTIC
        assert "3/3" in a.reason or "3/" in a.reason

    def test_not_confirmed_with_too_few_hits(self):
        tr = TemporalTracker("cam-a", settings(min_positive_observations=5))
        alerts = []
        for i in range(3):
            alerts += tr.update([det(10, 10, 50, 40, idx=i)], T0 + timedelta(seconds=i))
        assert alerts == []

    def test_low_confidence_detections_suppressed(self):
        tr = TemporalTracker("cam-a", settings())
        alerts = []
        for i in range(5):
            alerts += tr.update([det(10, 10, 50, 40, conf=0.1, idx=i)], T0 + timedelta(seconds=i))
        assert alerts == []
        assert any("below temporal min" in s.reason for s in tr.suppressed)

    def test_deduplicates_repeat_alerts(self):
        tr = TemporalTracker("cam-a", settings())
        alerts = []
        for i in range(6):
            alerts += tr.update([det(10 + i, 10, 50 + i, 40, idx=i)], T0 + timedelta(seconds=i))
        assert len(alerts) == 1  # one confirmation transition only
        assert any("duplicate" in s.reason for s in tr.suppressed)

    def test_persistence_ratio_gate(self):
        """A track with long gaps relative to hit count must not confirm."""
        tr = TemporalTracker("cam-a", settings(min_persistence_ratio=0.9, max_gap_seconds=2.0))
        alerts = []
        for i in range(4):
            # spread hits 4 s apart -> gaps exceed max_gap, each becomes its own short track
            alerts += tr.update([det(10, 10, 50, 40, idx=i)], T0 + timedelta(seconds=i * 4))
        confirmed = [a for a in alerts if a.confirmed]
        assert confirmed == []

    def test_track_follows_moving_box(self):
        tr = TemporalTracker("cam-a", settings())
        alerts = []
        for i in range(4):
            x = 100 + i * 15
            alerts += tr.update([det(x, 10, x + 40, 40, idx=i)], T0 + timedelta(seconds=i))
        assert len(alerts) == 1
        assert len(tr.tracks) == 1  # matched into a single track

    def test_two_simultaneous_blobs_two_tracks(self):
        tr = TemporalTracker("cam-a", settings())
        for i in range(3):
            tr.update(
                [det(10, 10, 50, 40, idx=i), det(400, 10, 440, 40, idx=i)],
                T0 + timedelta(seconds=i),
            )
        assert len(tr.tracks) == 2

    def test_other_camera_detections_ignored(self):
        tr = TemporalTracker("cam-a", settings())
        alerts = []
        for i in range(5):
            alerts += tr.update([det(10, 10, 50, 40, cam="cam-b", idx=i)], T0 + timedelta(seconds=i))
        assert alerts == []

    def test_grace_period_closes_track(self):
        tr = TemporalTracker("cam-a", settings())
        for i in range(3):
            tr.update([det(10, 10, 50, 40, idx=i)], T0 + timedelta(seconds=i))
        # still inside grace: no close alerts
        assert tr.close_idle_tracks(T0 + timedelta(seconds=3)) == []
        closed = tr.close_idle_tracks(T0 + timedelta(seconds=10))
        assert len(closed) == 1
        assert closed[0].confirmed is False
        assert "grace" in closed[0].reason
        s = tr.summary()
        assert s["closed"] == 1 and s["confirmed"] == 0

    def test_old_hits_pruned_by_window(self):
        tr = TemporalTracker("cam-a", settings(window_seconds=3.0, max_gap_seconds=5.0))
        tr.update([det(10, 10, 50, 40, idx=0)], T0)
        # 10 s later: outside window and gap > max_gap; hit pruned, new track starts
        alerts = tr.update([det(10, 10, 50, 40, idx=1)], T0 + timedelta(seconds=10))
        assert alerts == []
        assert len(tr.tracks) == 2
        assert all(len(t.hits) <= 1 for t in tr.tracks.values())

    def test_naive_datetime_treated_as_utc(self):
        tr = TemporalTracker("cam-a", settings())
        naive = datetime(2024, 7, 12, 15, 30, 0)
        tr.update([det(10, 10, 50, 40)], naive)

    def test_iou_or_center_matching(self):
        tr = TemporalTracker("cam-a", settings(match_iou_min=0.5, match_center_max_norm=0.05))
        # zero IoU but centres close
        tr.update([det(100, 100, 200, 200, idx=0)], T0)
        tr.update([det(101, 101, 201, 201, idx=1)], T0 + timedelta(seconds=1))
        assert len(tr.tracks) == 1
        # centres far apart -> new track
        tr.update([det(500, 100, 600, 200, idx=2)], T0 + timedelta(seconds=2))
        assert len(tr.tracks) == 2


class TestSettingsValidation:
    def test_invalid_ranges_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TemporalSettings(min_positive_observations=0)
        with pytest.raises(ValidationError):
            TemporalSettings(min_confidence=1.5)
        with pytest.raises(ValidationError):
            TemporalSettings(window_seconds=0.1)
        with pytest.raises(ValidationError):
            TemporalSettings(min_persistence_ratio=2.0)
