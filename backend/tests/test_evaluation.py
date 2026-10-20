from datetime import UTC, datetime, timedelta

from firesight.enums import MetricValidity, Provenance
from firesight.evaluation.metrics import (
    ConfusionCounts,
    detection_latency_seconds,
    detection_metrics,
    false_alerts_per_camera_hour,
    location_error_m,
    match_boxes,
    precision_recall_f1,
)
from firesight.models import BBox


def box(x1, y1, x2, y2):
    return BBox(x1=x1, y1=y1, x2=x2, y2=y2)


class TestMatchBoxes:
    def test_perfect_match(self):
        preds = [box(0, 0, 10, 10)]
        gts = [box(0, 0, 10, 10)]
        matches, fp, fn = match_boxes(preds, gts, 0.5)
        assert len(matches) == 1 and fp == [] and fn == []
        assert matches[0][2] == 1.0

    def test_no_overlap(self):
        matches, fp, fn = match_boxes([box(0, 0, 10, 10)], [box(50, 50, 60, 60)], 0.5)
        assert matches == [] and fp == [0] and fn == [0]

    def test_partial_overlap_below_threshold(self):
        # 10x10 boxes overlapping 4x4 -> IoU = 16/(100+100-16) = 0.09
        matches, fp, fn = match_boxes([box(0, 0, 10, 10)], [box(6, 6, 16, 16)], 0.5)
        assert matches == []

    def test_partial_overlap_above_threshold(self):
        # boxes 10x10 overlapping 8x8 -> IoU = 64/(200-64) = 0.47
        matches, fp, fn = match_boxes([box(0, 0, 10, 10)], [box(2, 2, 12, 12)], 0.45)
        assert len(matches) == 1

    def test_one_to_one_greedy(self):
        gts = [box(0, 0, 10, 10), box(20, 0, 30, 10)]
        preds = [box(0, 0, 10, 10), box(1, 1, 11, 11)]  # both overlap gt 0
        matches, fp, fn = match_boxes(preds, gts, 0.5)
        assert len(matches) == 1
        assert len(fp) == 1
        assert len(fn) == 1

    def test_hand_calculated_counts(self):
        gts = [box(0, 0, 10, 10), box(50, 50, 60, 60)]
        preds = [box(0, 0, 10, 10), box(100, 100, 110, 110)]
        matches, fp, fn = match_boxes(preds, gts, 0.5)
        assert (len(matches), len(fp), len(fn)) == (1, 1, 1)


class TestPrecisionRecall:
    def test_hand_calculated(self):
        # tp=3 fp=1 fn=2 -> p=0.75 r=0.6 f1=2*.75*.6/1.35=0.666..
        prf = precision_recall_f1(ConfusionCounts(tp=3, fp=1, fn=2))
        assert prf["precision"] == 0.75
        assert prf["recall"] == 0.6
        assert prf["f1"] == 2 * 0.75 * 0.6 / 1.35

    def test_zero_predictions(self):
        prf = precision_recall_f1(ConfusionCounts(tp=0, fp=0, fn=2))
        assert prf["precision"] is None
        assert prf["recall"] == 0.0

    def test_zero_ground_truth(self):
        prf = precision_recall_f1(ConfusionCounts(tp=0, fp=2, fn=0))
        assert prf["recall"] is None
        assert prf["precision"] == 0.0


class TestDetectionMetrics:
    def test_with_ground_truth(self):
        preds = [box(0, 0, 10, 10), box(50, 50, 60, 60)]
        gts = [box(0, 0, 10, 10), box(200, 200, 210, 210)]
        results = {m.name: m for m in detection_metrics(preds, gts, data_source="synthetic-fixture")}
        assert results["detection_precision"].value == 0.5
        assert results["detection_recall"].value == 0.5
        assert results["detection_precision"].validity == MetricValidity.VALID
        assert results["confusion_tp"].value == 1
        assert results["confusion_fp"].value == 1
        assert results["confusion_fn"].value == 1

    def test_without_ground_truth_all_unavailable(self):
        results = detection_metrics([box(0, 0, 1, 1)], None, data_source="no-labels")
        for m in results:
            assert m.validity == MetricValidity.UNAVAILABLE
            assert m.value is None
            assert m.limitation
            assert m.ground_truth_available is False


class TestLatencyAndRates:
    def test_latency_available(self):
        onset = datetime(2024, 7, 12, 15, 30, 0, tzinfo=UTC)
        alert = onset + timedelta(seconds=2.5)
        m = detection_latency_seconds(onset, alert, data_source="demo", frame_timing_sufficient=True)
        assert m.validity == MetricValidity.VALID
        assert m.value == 2.5

    def test_latency_missing_onset(self):
        m = detection_latency_seconds(None, datetime.now(UTC), data_source="x", frame_timing_sufficient=True)
        assert m.validity == MetricValidity.UNAVAILABLE and m.value is None

    def test_latency_insufficient_timing(self):
        m = detection_latency_seconds(
            datetime.now(UTC), datetime.now(UTC), data_source="x", frame_timing_sufficient=False
        )
        assert m.validity == MetricValidity.UNAVAILABLE

    def test_latency_negative(self):
        onset = datetime(2024, 7, 12, 15, 30, 5, tzinfo=UTC)
        alert = datetime(2024, 7, 12, 15, 30, 0, tzinfo=UTC)
        m = detection_latency_seconds(onset, alert, data_source="x", frame_timing_sufficient=True)
        assert m.validity == MetricValidity.UNAVAILABLE
        assert "precedes" in (m.limitation or "")

    def test_false_alert_rate(self):
        m = false_alerts_per_camera_hour(3, 7200.0, data_source="labelled", negatives_labelled=True)
        assert m.value == 1.5
        assert m.validity == MetricValidity.VALID

    def test_false_alert_rate_unlabelled(self):
        m = false_alerts_per_camera_hour(3, 7200.0, data_source="unlabelled", negatives_labelled=False)
        assert m.validity == MetricValidity.UNAVAILABLE and m.value is None

    def test_location_error(self):
        # 37.0,-119.5 vs ~111 m north
        m = location_error_m(37.001, -119.5, 37.0, -119.5, data_source="gt")
        assert m.validity == MetricValidity.VALID
        assert m.value == 111.2 or abs(m.value - 111.2) < 2

    def test_location_error_missing_gt(self):
        m = location_error_m(37.0, -119.5, None, None, data_source="gt")
        assert m.validity == MetricValidity.UNAVAILABLE and m.value is None

    def test_provenance_recorded(self):
        m = location_error_m(None, None, None, None, data_source="x")
        assert m.provenance == Provenance.HEURISTIC
