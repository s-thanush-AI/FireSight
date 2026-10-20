# Demo script

A guided walkthrough of FireSight in **demo mode** — no credentials, datasets,
weights or GPU required. It runs the full pipeline on a deterministic synthetic
scenario.

> FireSight is a research/portfolio prototype, **not an operational warning
> service**. Everything below uses simulated imagery; the geometry is genuine
> but the cameras, plume and ground truth are synthetic.

## 0. Launch

```bash
cd backend && uv sync --all-extras
cd ../frontend && npm install
cd .. && ./scripts/dev.sh
```

Open <http://127.0.0.1:5173>. A **DemoBanner** indicates simulated mode. The
backend API docs are at <http://127.0.0.1:8000/docs>.

Alternatively, drive everything from the CLI:

```bash
cd backend
uv run firesight status
uv run firesight replay demo-alpha-ridge --frames 45
```

## 1. Overview

The landing page summarises system status: mode, active detector (with
availability + provenance), VLM status, camera count and incident counts. Note
the detector reads `classic-smoke-blob` with `provenance = predicted` — a
heuristic, not a trained model.

## 2. Detection Replay

Navigate to **Detection Replay**.

1. Choose sequence **Alpha Ridge (simulated)** and create a replay.
2. The live frame shows the annotated image over the WebSocket; the event feed
   streams `status`, `frame`, `temporal_alert` and `incident_created`.
3. Use **Pause / Resume / Reset**; use **Step** to advance frames one at a time
   (deterministic — ideal for a live demo).
4. Watch the first ~10 frames: a passing **cloud distractor** is detected but
   does **not** persist, so the temporal tracker never confirms it — no
   incident. From frame ~10 the **plume** grows and persists; once it passes the
   tracker's gate (≥3 hits + persistence), a `temporal_alert` fires and an
   incident is created.

This demonstrates the persistence gate suppressing a transient false positive —
a core design choice.

## 3. Geolocation Map

Run **Bravo Ridge (simulated)** as a second replay (or replay both via the
CLI), then open **Geolocation Map**.

- Camera markers for `sim-cam-a` and `sim-cam-b` (~6 km apart).
- Bearing **rays** from each camera.
- An **estimate** marker where the rays cross, with an uncertainty circle.
- Click to see `ray_separation_deg`, `fit_residual_m`, distances per camera,
  `geometry_quality` (`strong`/`acceptable`/`weak`) and `uncertainty_m`.

With two well-separated simulated cameras the crossing is `strong`
(~106° separation, ~140–220 m uncertainty). The estimate lands within a couple
of metres of the synthetic ground-truth source — a **self-consistency check on
perfect bearings**, not a claim about real accuracy.

## 4. Incidents

Open **Incidents**, then a specific incident.

- Status flow: `candidate → confirmed → reviewed / acknowledged / dismissed`.
- Apply an action (e.g. **Acknowledge**) and see it recorded in the **history**
  table with a timestamp.
- Inspect **observations** (per-camera bearings + provenance) and
  **triangulation** (location, uncertainty, geometry notes).
- **Verify with VLM** — in demo mode this uses the simulated provider and
  returns a clearly-labelled assessment. In real mode with no credentials it
  returns an explicit disabled state (never a fabricated verdict).
- **Export**: download JSON, CSV, or a ZIP bundle
  (`GET /api/v1/reports/{id}/download?format=zip`).

## 5. Evaluation

Open **Evaluation** and run the demo-fixture evaluation.

- Metrics are shown with a **provenance badge** and per-metric limitation text.
- Some metrics are intentionally **UNAVAILABLE with a reason** — e.g. false
  alerts per camera-hour, because demo negatives are unlabelled. This is the
  honest-metrics behaviour, not a bug.

## 6. Models & VLM, Datasets, System

- **Models & VLM** — detector registry and VLM configuration state.
- **Datasets** — registered sequences (the two demo sequences) and a
  path-safe inspect box.
- **System** — effective (redacted) configuration; runtime overrides for
  allow-listed keys.

## 7. Exports (CLI)

```bash
cd backend
uv run firesight export-video demo-alpha-ridge --every 5   # animated GIF
uv run firesight export-incident <incident_id>             # JSON+CSV+manifest ZIP
```

## Wrap-up talking points

- **Provenance everywhere** — simulated vs predicted vs heuristic vs manual is
  visible on every record and never mixed.
- **Honest metrics** — missing ground truth yields "unavailable + reason", not
  a number.
- **Pure geometry** — the ENU/bearing/triangulation code has no I/O and is
  hand-tested.
- **Fails loud in real mode** — missing weights/calibration produce explicit
  unavailable states; no silent fallback to simulation.
- **Bounded resources & path safety** — streaming replays, capped persistence,
  traversal-safe dataset handling.
