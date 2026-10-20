"""Evaluation run management. Metrics are only produced where ground truth exists."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..db import Database, dumps, utcnow_iso
from ..demo.scenario import (
    DEMO_SEQUENCE_A,
    DEMO_SEQUENCE_B,
    demo_scenario,
    generate_demo_sequence,
    plume_pixel_position,
)
from ..detection.classic import ClassicSmokeDetector
from ..enums import EvidenceType, MetricValidity, Provenance
from ..evaluation.metrics import (
    detection_latency_seconds,
    detection_metrics,
    false_alerts_per_camera_hour,
    location_error_m,
)
from ..geometry.bearing import pixel_to_bearing
from ..models import BBox, BearingObservation, FrameRef
from ..replay.discovery import discover_frames, load_frame


def _store_run(
    db: Database,
    *,
    name: str,
    dataset: str,
    config: dict,
    model_name: str,
    model_version: str,
    provenance: Provenance,
    split: str,
    notes: str,
    metrics: list,
    manifest: dict | None = None,
) -> dict:
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    now = utcnow_iso()
    db.execute(
        """INSERT INTO eval_runs (id, name, dataset, dataset_manifest_json, config_json,
             model_name, model_version, provenance, split, notes, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            run_id, name, dataset, dumps(manifest or {}), dumps(config), model_name,
            model_version, provenance.value, split, notes, now,
        ),
    )
    for m in metrics:
        db.execute(
            """INSERT INTO eval_metrics (run_id, name, value, unit, sample_count, data_source,
                 ground_truth_available, valid, limitation, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id, m.name, m.value, m.unit, m.sample_count, m.data_source,
                int(m.ground_truth_available),
                int(m.validity == MetricValidity.VALID), m.limitation, now,
            ),
        )
    return {"run_id": run_id, "created_at": now, "metric_count": len(metrics)}


def evaluate_demo_fixture(db: Database, *, data_root, seed: int = 7) -> dict:
    """Evaluate the classic detector against the demo scene's synthetic ground truth.

    Everything here is SYNTHETIC: the 'ground truth' boxes come from the same
    generative model that drew the plume. These numbers validate the pipeline,
    NOT real-world accuracy, and are stored with provenance 'simulated'.
    """
    sc = demo_scenario()
    spec = DEMO_SEQUENCE_A
    cam = sc.cameras[spec.camera_id]
    seq_dir = Path(data_root) / "demo" / spec.id
    if not (seq_dir.exists() and any(seq_dir.glob("*.png"))):
        generate_demo_sequence(seq_dir, cam, spec, seed=seed)
    frames = discover_frames(seq_dir)
    detector = ClassicSmokeDetector(confidence_threshold=0.25)

    all_preds: list[BBox] = []
    all_gts: list[BBox] = []
    onset_idx: int | None = spec.plume_start
    first_alert_idx: int | None = None
    fps = 5.0

    for ff in frames:
        img, _ = load_frame(ff)
        ref = FrameRef(sequence_id=spec.id, index=ff.index, filename=ff.filename)
        dets = detector.detect(img, ref, cam.id)
        pos = plume_pixel_position(cam, ff.index, spec)
        gt_box: BBox | None = None
        if pos is not None:
            x, y, growth = pos
            rx = (14 + 46 * growth) * 0.9
            ry = (9 + 30 * growth) * 0.9
            gt_box = BBox(
                x1=max(0.0, x - rx), y1=max(0.0, y - ry),
                x2=min(float(cam.image_width), x + rx),
                y2=min(float(cam.image_height), y + ry),
            )
            all_gts.append(gt_box)
        if dets and first_alert_idx is None and ff.index >= (onset_idx or 0):
            best = max(dets, key=lambda d: d.confidence)
            if gt_box is not None and best.bbox.iou(gt_box) > 0.1:
                first_alert_idx = ff.index
        for d in dets:
            all_preds.append(d.bbox)

    metrics = detection_metrics(
        all_preds, all_gts, iou_threshold=0.3,
        data_source=f"synthetic demo sequence {spec.id} (generated, seed={seed})",
        provenance=Provenance.SIMULATED,
    )
    latency = detection_latency_seconds(
        datetime.fromtimestamp((onset_idx or 0) / fps, tz=UTC) if onset_idx is not None else None,
        datetime.fromtimestamp(first_alert_idx / fps, tz=UTC) if first_alert_idx is not None else None,
        data_source="synthetic demo sequence",
        frame_timing_sufficient=True,
        provenance=Provenance.SIMULATED,
    )
    metrics.append(latency)
    metrics.append(
        false_alerts_per_camera_hour(
            None, None, data_source="synthetic demo sequence",
            negatives_labelled=False, provenance=Provenance.SIMULATED,
        )
    )

    # geolocation: replay the two-camera loop at the alert frame
    from ..association.associate import associate_observations

    obs = []
    for seq_spec in (DEMO_SEQUENCE_A, DEMO_SEQUENCE_B):
        c = sc.cameras[seq_spec.camera_id]
        sdir = Path(data_root) / "demo" / seq_spec.id
        if not (sdir.exists() and any(sdir.glob("*.png"))):
            generate_demo_sequence(sdir, c, seq_spec, seed=seed)
        sframes = discover_frames(sdir)
        idx = min(seq_spec.plume_start + 25, len(sframes) - 1)
        ff = sframes[idx]
        img, _ = load_frame(ff)
        ref = FrameRef(sequence_id=seq_spec.id, index=idx, filename=ff.filename)
        dets = detector.detect(img, ref, c.id)
        if not dets:
            continue
        best = max(dets, key=lambda d: d.confidence)
        px = (best.bbox.x1 + best.bbox.x2) / 2.0
        bearing = pixel_to_bearing(
            px, image_width=c.image_width, heading_deg=c.heading_deg, hfov_deg=c.hfov_deg
        )
        obs.append(
            BearingObservation(
                camera_id=c.id, bearing_deg=bearing,
                timestamp=ff.timestamp.isoformat() if ff.timestamp else None,
                pixel_x=px, pixel_y=best.bbox.y2, confidence=best.confidence,
                evidence_type=EvidenceType.SIMULATED_SECOND_CAMERA,
                provenance=Provenance.PREDICTED, camera=c,
            )
        )
    loc_metric = location_error_m(None, None, sc.ground_truth_lat, sc.ground_truth_lon,
                                  data_source="synthetic demo", provenance=Provenance.SIMULATED)
    if len(obs) == 2:
        assoc = associate_observations(
            [obs[0]], [obs[1]], sc.cameras,
            timestamp_tolerance_s=5.0,
        )
        valid = [a for a in assoc if a.valid]
        if valid:
            tri = valid[0].triangulation
            loc_metric = location_error_m(
                tri.latitude, tri.longitude, sc.ground_truth_lat, sc.ground_truth_lon,
                data_source="synthetic demo triangulation (simulated cameras, real geometry)",
                provenance=Provenance.SIMULATED,
            )
    metrics.append(loc_metric)

    return _store_run(
        db,
        name="Demo fixture evaluation (synthetic)",
        dataset=f"fireSight demo fixtures / {spec.id}",
        config={"seed": seed, "iou_threshold": 0.3, "detector": detector.name},
        model_name=detector.name,
        model_version=detector.version,
        provenance=Provenance.SIMULATED,
        split="synthetic-fixture",
        notes=(
            "Synthetic evaluation on generated demo imagery. Ground-truth boxes come from "
            "the generative model itself. These figures validate pipeline mechanics only "
            "and MUST NOT be reported as real-world wildfire detection accuracy."
        ),
        metrics=metrics,
        manifest={"synthetic": True, "seed": seed, "frames": len(frames)},
    )


def list_runs(db: Database) -> list[dict]:
    runs = db.query("SELECT * FROM eval_runs ORDER BY created_at DESC")
    for run in runs:
        run["metrics"] = db.query(
            "SELECT * FROM eval_metrics WHERE run_id=? ORDER BY name", (run["id"],)
        )
    return runs


def get_run(db: Database, run_id: str) -> dict | None:
    run = db.query_one("SELECT * FROM eval_runs WHERE id=?", (run_id,))
    if run is None:
        return None
    run["metrics"] = db.query(
        "SELECT * FROM eval_metrics WHERE run_id=? ORDER BY name", (run_id,)
    )
    return run


def unavailable_metric(name: str, reason: str, data_source: str = "user data") -> dict:
    return {
        "name": name, "value": None, "unit": "", "sample_count": None,
        "data_source": data_source, "ground_truth_available": False,
        "valid": False, "limitation": reason, "provenance": Provenance.HEURISTIC.value,
    }
