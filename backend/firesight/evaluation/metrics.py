"""Evaluation metrics with strict availability rules.

Every metric returns a MetricResult. When the required ground truth is
missing the result is explicitly UNAVAILABLE with a reason — a number is
never invented. Object-detection matching uses IoU >= threshold, greedy
highest-IoU assignment, one prediction per ground-truth box.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from ..enums import MetricValidity, Provenance
from ..geometry.frames import geodesic_distance_m
from ..models import BBox, MetricResult


@dataclass
class ConfusionCounts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.fn + self.tn


def match_boxes(
    predictions: list[BBox], ground_truth: list[BBox], iou_threshold: float = 0.5
) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    """Greedy IoU matching. Returns (matches[(pi, gi, iou)], fp_indices, fn_indices)."""
    candidates: list[tuple[float, int, int]] = []
    for pi, p in enumerate(predictions):
        for gi, g in enumerate(ground_truth):
            iou = p.iou(g)
            if iou >= iou_threshold:
                candidates.append((iou, pi, gi))
    candidates.sort(reverse=True)
    matched_p: set[int] = set()
    matched_g: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for iou, pi, gi in candidates:
        if pi in matched_p or gi in matched_g:
            continue
        matched_p.add(pi)
        matched_g.add(gi)
        matches.append((pi, gi, iou))
    fp = [i for i in range(len(predictions)) if i not in matched_p]
    fn = [i for i in range(len(ground_truth)) if i not in matched_g]
    return matches, fp, fn


def detection_metrics(
    predictions: list[BBox],
    ground_truth: list[BBox] | None,
    *,
    iou_threshold: float = 0.5,
    data_source: str,
    provenance: Provenance = Provenance.PREDICTED,
) -> list[MetricResult]:
    """Precision / recall / F1 / confusion counts for one evaluated split."""
    stamp = dict(
        data_source=data_source,
        ground_truth_available=ground_truth is not None,
        provenance=provenance,
    )
    if ground_truth is None:
        reason = (
            "No compatible ground-truth annotations were provided for this split; "
            "precision/recall cannot be computed."
        )
        return [
            MetricResult(
                name=name, value=None, unit="ratio", sample_count=None,
                validity=MetricValidity.UNAVAILABLE, limitation=reason, **stamp,
            )
            for name in ("detection_precision", "detection_recall", "detection_f1")
        ]

    matches, fp, fn = match_boxes(predictions, ground_truth, iou_threshold)
    tp = len(matches)
    counts = ConfusionCounts(tp=tp, fp=len(fp), fn=len(fn))
    prf = precision_recall_f1(counts)
    n_gt = max(len(ground_truth), 1)
    out = [
        MetricResult(
            name="detection_precision", value=prf["precision"], unit="ratio",
            sample_count=len(predictions), validity=MetricValidity.VALID,
            limitation=f"IoU >= {iou_threshold}; greedy one-to-one matching", **stamp,
        ),
        MetricResult(
            name="detection_recall", value=prf["recall"], unit="ratio",
            sample_count=len(ground_truth), validity=MetricValidity.VALID,
            limitation=f"IoU >= {iou_threshold}; greedy one-to-one matching", **stamp,
        ),
        MetricResult(
            name="detection_f1", value=prf["f1"], unit="ratio",
            sample_count=n_gt, validity=MetricValidity.VALID,
            limitation=None, **stamp,
        ),
        MetricResult(
            name="confusion_tp", value=float(tp), unit="count",
            sample_count=counts.total, validity=MetricValidity.VALID, limitation=None, **stamp,
        ),
        MetricResult(
            name="confusion_fp", value=float(len(fp)), unit="count",
            sample_count=counts.total, validity=MetricValidity.VALID, limitation=None, **stamp,
        ),
        MetricResult(
            name="confusion_fn", value=float(len(fn)), unit="count",
            sample_count=counts.total, validity=MetricValidity.VALID, limitation=None, **stamp,
        ),
    ]
    return out


def precision_recall_f1(counts: ConfusionCounts) -> dict[str, float | None]:
    precision = counts.tp / (counts.tp + counts.fp) if (counts.tp + counts.fp) else None
    recall = counts.tp / (counts.tp + counts.fn) if (counts.tp + counts.fn) else None
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def detection_latency_seconds(
    onset: datetime | None,
    first_alert: datetime | None,
    *,
    data_source: str,
    frame_timing_sufficient: bool,
    provenance: Provenance = Provenance.HEURISTIC,
) -> MetricResult:
    if onset is None or first_alert is None or not frame_timing_sufficient:
        return MetricResult(
            name="detection_latency_s", value=None, unit="seconds", sample_count=None,
            data_source=data_source, ground_truth_available=False,
            validity=MetricValidity.UNAVAILABLE,
            limitation=(
                "Event onset and/or sufficiently precise frame timing is missing; "
                "latency cannot be computed."
            ),
            provenance=provenance,
        )
    latency = (first_alert - onset).total_seconds()
    if latency < 0:
        return MetricResult(
            name="detection_latency_s", value=None, unit="seconds", sample_count=1,
            data_source=data_source, ground_truth_available=True,
            validity=MetricValidity.UNAVAILABLE,
            limitation="First alert precedes the labelled event onset (clock/label error).",
            provenance=provenance,
        )
    return MetricResult(
        name="detection_latency_s", value=round(latency, 3), unit="seconds", sample_count=1,
        data_source=data_source, ground_truth_available=True,
        validity=MetricValidity.VALID, limitation=None, provenance=provenance,
    )


def false_alerts_per_camera_hour(
    false_alert_count: int | None,
    monitored_seconds: float | None,
    *,
    data_source: str,
    negatives_labelled: bool,
    provenance: Provenance = Provenance.HEURISTIC,
) -> MetricResult:
    if (
        not negatives_labelled
        or false_alert_count is None
        or monitored_seconds is None
        or monitored_seconds <= 0
    ):
        return MetricResult(
            name="false_alerts_per_camera_hour", value=None, unit="alerts/camera-hour",
            sample_count=None, data_source=data_source, ground_truth_available=False,
            validity=MetricValidity.UNAVAILABLE,
            limitation=(
                "Requires labelled negative monitoring time (camera-hours with verified "
                "no-fire labels). This dataset does not provide it."
            ),
            provenance=provenance,
        )
    rate = false_alert_count / (monitored_seconds / 3600.0)
    return MetricResult(
        name="false_alerts_per_camera_hour", value=round(rate, 4),
        unit="alerts/camera-hour", sample_count=false_alert_count,
        data_source=data_source, ground_truth_available=True,
        validity=MetricValidity.VALID, limitation=None, provenance=provenance,
    )


def location_error_m(
    estimate_lat: float | None,
    estimate_lon: float | None,
    gt_lat: float | None,
    gt_lon: float | None,
    *,
    data_source: str,
    provenance: Provenance = Provenance.HEURISTIC,
) -> MetricResult:
    if None in (estimate_lat, estimate_lon, gt_lat, gt_lon):
        return MetricResult(
            name="geolocation_error_m", value=None, unit="metres", sample_count=None,
            data_source=data_source, ground_truth_available=False,
            validity=MetricValidity.UNAVAILABLE,
            limitation=(
                "Location error needs both an estimate and a reliable ground-truth "
                "coordinate; one or both are missing."
            ),
            provenance=provenance,
        )
    err = geodesic_distance_m(estimate_lat, estimate_lon, gt_lat, gt_lon)  # type: ignore[arg-type]
    if math.isnan(err):
        value = None
        limitation = "Geodesic computation returned NaN."
        validity = MetricValidity.UNAVAILABLE
    else:
        value = round(err, 1)
        limitation = None
        validity = MetricValidity.VALID
    return MetricResult(
        name="geolocation_error_m", value=value, unit="metres", sample_count=1,
        data_source=data_source, ground_truth_available=True,
        validity=validity, limitation=limitation, provenance=provenance,
    )
