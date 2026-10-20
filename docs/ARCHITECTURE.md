# FireSight Architecture

This document describes the components, data flow and interfaces of the
FireSight prototype. It is descriptive, not aspirational: it reflects the code
in `backend/firesight/` and `frontend/src/`. Anything not implemented is
called out as such.

## Guiding invariants

- **Provenance on every record.** Values are drawn from
  `Provenance = {real, predicted, simulated, heuristic, manual}`. Simulated
  evidence is never mixed into real evaluation.
- **Demo mode needs nothing.** Zero credentials, datasets, weights or GPU.
  Deterministic seeds and static fixtures only.
- **Real mode fails loud, never falls back.** Missing data / weights /
  calibration / ground truth produces an explicit `unavailable` / `unvalidated`
  state with a reason.
- **No fabricated metrics.** Missing ground truth yields an unavailable metric
  with a reason, never a number.
- **Geometry is pure.** `firesight/geometry` has no I/O, DB or FastAPI imports
  and is testable against hand-computed cases.
- **Bounded resources.** Replays stream an iterator of frames; no whole-sequence
  loads. Frame persistence in SQLite is capped.
- **Path safety.** Dataset paths resolve under the configured data root; archive
  extraction prevents traversal.

## Component map

```
                 ┌────────────────────────────────────────────┐
   frames on disk │  replay/   discovery + threaded engine      │
   (or synthetic) │  → streams FramePacket (iterator)           │
                 └───────────────┬────────────────────────────┘
                                 ▼
                 ┌────────────────────────────────────────────┐
                 │  detection/  BaseDetector                   │
                 │  ClassicSmokeDetector (predicted)           │
                 │  YoloDetector (optional extra, untrained)   │
                 └───────────────┬────────────────────────────┘
                                 ▼
                 ┌────────────────────────────────────────────┐
                 │  temporal/  TemporalTracker                 │
                 │  3-hit + persistence gate + dedup           │
                 └───────────────┬────────────────────────────┘
                                 ▼
                 ┌────────────────────────────────────────────┐
                 │  geometry/  pixel→bearing (pure)            │
                 └───────────────┬────────────────────────────┘
                                 ▼
                 ┌────────────────────────────────────────────┐
                 │  association/  cross-camera candidates      │
                 └───────────────┬────────────────────────────┘
                                 ▼
                 ┌────────────────────────────────────────────┐
                 │  geometry/  least-squares triangulation     │
                 │  + uncertainty + ray separation             │
                 └───────────────┬────────────────────────────┘
                                 ▼
                 ┌────────────────────────────────────────────┐
                 │  services/incidents  lifecycle + history     │
                 │  services/eval_service  metrics              │
                 └───────────────┬────────────────────────────┘
                                 ▼
        ┌────────────────────────┴─────────────────────────┐
        ▼                        ▼                         ▼
   api/ (FastAPI)          db.py (SQLite)            export/ (GIF/ZIP)
```

## Backend packages

| Package | Responsibility |
|---------|----------------|
| `enums.py` | All StrEnums: provenance, incident status, geometry quality, replay status, severity, VLM assessment, calibration status. |
| `config.py` | `Settings` (+ `DetectorSettings`, `TemporalSettings`, `VlmSettings`), env prefix `FIRESIGHT_*` (`VLM_*` for the VLM), `redacted_dict()` for safe output. |
| `db.py` | Versioned SQLite initializer/migrations (WAL). Schema created through `SCHEMA_VERSION`, never by dropping tables. |
| `models.py` | Pydantic schemas: `BBox`, `Detection`, `FrameRef`, `CameraConfig`, `BearingObservation`, `TriangulationResult`, `TemporalAlert`, `VlmDecision`, `MetricResult`, `Incident`. |
| `replay/` | `discovery.py` (verified timestamp patterns, `CorruptFrameError`) and `engine.py` (a thread that streams frames from an iterator). |
| `demo/` | `scene.py` (deterministic synthetic renderer), `scenario.py` (cameras, sequences, ground truth). |
| `detection/` | `base.py` (`BaseDetector`, `build_detector`), `classic.py` (heuristic blob detector), `yolo.py` (lazy import, no auto-download), `drawing.py`. |
| `temporal/` | `tracker.py` — confirmation logic and lifecycle of tracks. |
| `geometry/` | `frames.py` (ENU↔lat/lon), `bearing.py` (pixel↔bearing), `uncertainty.py`, `triangulation.py`. Pure, no I/O. |
| `association/` | Groups simultaneous cross-camera bearings into candidate events. |
| `vlm/` | `provider.py` — `OpenAICompatibleVlm` (env-only key), `SimulatedVlmProvider` (demo), `NullVlmProvider` (real mode disabled). |
| `evaluation/` | `metrics.py` — scoring against ground truth; returns unavailable + reason when GT is missing. |
| `datasets/` | `paths.py` (path safety), `archive.py` (traversal-safe extraction), `inspect.py`, `manifest.py`, `figlib.py`, `pyrosdis.py`. |
| `services/` | `context.py` (`AppContext` lifecycle, overrides), `incidents.py`, `eval_service.py`, `replay_manager.py`. |
| `export/` | `demo_video.py` (animated GIF), `bundle.py` (incident ZIP). |
| `api/` | FastAPI factory + routers (below). |
| `cli.py` | `firesight` CLI entrypoint. |

### Runtime pipeline (`services/replay_manager.py`)

For each frame, a replay session:

1. decodes the frame and runs the detector;
2. feeds detections to the `TemporalTracker`;
3. draws an annotated JPEG for the live view;
4. persists the frame + detections (capped);
5. on confirmation, creates/updates a bearing observation;
6. attempts cross-camera association and triangulation;
7. creates or merges an incident and records status history;
8. broadcasts events over the WebSocket.

A replay can be `pause`d, `resume`d, `reset`, or driven deterministically with
`step?n=` — the latter is what the API tests use.

## API (all under `/api/v1`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness + version + mode. |
| GET | `/status` | Detector, VLM, cameras, incident counts. |
| GET | `/config` | Redacted effective configuration. |
| PUT | `/config` | Apply runtime overrides (allow-listed keys). |
| GET | `/models` | Detector/model registry and availability. |
| GET | `/datasets` | Datasets discovered under the data root. |
| POST | `/datasets/inspect` | Inspect a path under the data root. |
| GET | `/sequences` · `/sequences/{id}` | Registered sequences. |
| POST | `/replays` | Create a replay session. |
| GET | `/replays` · `/replays/{id}` | List / inspect replays. |
| POST | `/replays/{id}/pause\|resume\|reset` | Transport control. |
| POST | `/replays/{id}/step?n=` | Advance N frames synchronously. |
| GET | `/replays/{id}/frames/current` | Current annotated frame. |
| GET | `/replays/{id}/events?since=` | Event log tail. |
| WS | `/ws/replays/{id}` | Live events: `status`, `frame`, `temporal_alert`, `incident_created`, `error`. |
| GET | `/incidents` · `/incidents/{id}` | Query incidents / detail. |
| PATCH | `/incidents/{id}` | Apply an action (acknowledge/review/dismiss/confirm). |
| GET | `/reports/{id}` | Full JSON export. |
| GET | `/reports/{id}/download?format=json\|csv\|zip` | Downloadable export. |
| GET/POST/PUT | `/cameras` · `/cameras/{id}` | Camera CRUD with validation. |
| GET | `/geometry` | Recent triangulations. |
| GET | `/evaluation/metrics` | Metric overview. |
| POST/GET | `/evaluation/runs` · `/evaluation/runs/{id}` | Run/detail evaluations. |
| POST | `/verification/{id}` · GET | Optional VLM verification. |
| POST | `/inference` | One-off detection on a sequence frame. |

Response models are Pydantic schemas in `api/schemas.py`.

## Database (SQLite, versioned)

Tables: `schema_meta`, `cameras`, `sequences`, `replays`, `frames`,
`detections`, `tracks`, `incidents`, `incident_status_history`, `observations`,
`triangulations`, `vlm_verifications`, `eval_runs`, `eval_metrics`,
`audit_entries`, `settings_kv`.

Schema version is tracked in `schema_meta`; migrations are additive and
idempotent. `SCHEMA_VERSION = 2` added `settings_kv`; a v1 database upgrades
cleanly.

## Frontend

React 19 + TypeScript + Vite, styled with Tailwind v4. Files under
`frontend/src/`:

- `lib/api.ts` — the **only** module that talks to the backend (typed client +
  `wsUrl()`), mirroring the backend schemas.
- `lib/hooks.ts`, `lib/format.ts`, `lib/app-context.ts` — async state, polling,
  formatting, mode/known-state context.
- `components/` — `ui.tsx` (Card, badges incl. `ProvenanceBadge`, StatCard,
  states, `DemoBanner`), `Layout.tsx`, `nav.ts`.
- `pages/` — Overview, Replay (live WS frame + transport + event feed), Map
  (Leaflet dark tiles, cameras/estimates/bearing rays), Incidents,
  IncidentDetail, Cameras, Evaluation, Models, Datasets, System.

Routes are code-split with `React.lazy` + `Suspense`. The Vite dev server
proxies `/api` (including WebSockets) to the backend.

## Trust boundaries

- The frontend never receives secrets; `/config` is redacted server-side.
- The VLM key lives only in the backend process environment.
- Dataset paths from users resolve under the data root; archives are extracted
  safely (no traversal).
- Every number surfaced in the UI carries its provenance badge.
