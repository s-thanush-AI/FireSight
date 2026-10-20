# FireSight — Build Status

Honest progress and handoff record. Update after every phase. Never record a
verification result that was not actually executed.

## Plan (phases)

| Phase | Scope | Status |
|-------|-------|--------|
| A | Repo inspection, architecture, AGENTS.md | done |
| B | Environment, configuration, schemas, database | done |
| C | Dataset manifests, fixtures, deterministic replay | done |
| D | YOLO adapter, training + data-prep utilities | done (classic detector active; YOLO adapter lazy, untrained/untested on real data) |
| E | Temporal tracking and event verification | done |
| F | Pure geometry, triangulation, uncertainty | done |
| G | Cross-camera association with simulated fallback | done |
| H | Optional VLM provider adapter | done |
| I | FastAPI integration, persistence, replay controls | done |
| J | React dashboard + full API integration | done |
| K | Evaluation metrics, exports, demo video tools | done (metrics + JSON/CSV/ZIP exports + annotated demo GIF) |
| L | Tests, security checks, documentation, E2E verification | done |
| M | Real footage sequence registration | done |
| N | Video playback/analysis, live sources, alerts | done (RTSP verified via local MediaMTX loopback, not a physical camera) |

## Environment observed at start

- macOS 26.6.2 (arm64 / Apple Silicon), 8 GB RAM, 54 GB free disk.
- System `python3` = 3.9.6 (too old); Homebrew `python3.11` present.
- `uv` 0.13.3 installed via official installer (`~/.local/bin/uv`).
- Node v25.6.0, npm 11.8.0, git 2.x, Homebrew available.
- Repository contained only `.git` (no commits yet, no prior user work to
  preserve).

## Log

### 2026-10-20 — Phase A
- Created repo skeleton: `backend/`, `frontend/`, `scripts/`, `docs/`,
  `backend/tests/`.
- Wrote `.gitignore`, `.env.example` (placeholders only), `AGENTS.md`.
- Wrote this plan. Next: Phase B (uv environment, config, DB schema).

### 2026-10-20 — Phases B–H (backend core)
- `backend/pyproject.toml` (uv-managed, Python ≥3.11) with deps: fastapi,
  pydantic-settings, numpy, pillow, opencv-python-headless, pyproj, httpx,
  pyyaml; dev group pytest/pytest-asyncio/ruff. Optional extra `yolo`
  (torch/ultralytics) NOT installed by default.
- `firesight/enums.py` — provenance, incident status, geometry quality,
  evidence types, replay status, severity, VLM assessment (StrEnums).
- `firesight/config.py` — `Settings`/`DetectorSettings`/`TemporalSettings`/
  `VlmSettings`, env prefix `FIRESIGHT_*` (`VLM_*` for VLM), `redacted_dict()`.
- `firesight/db.py` — versioned SQLite schema (WAL), `Database` with
  per-call connections and `:memory:` support.
- `firesight/models.py` — BBox, Detection, CameraConfig, BearingObservation,
  TriangulationResult, TemporalAlert, VlmDecision, MetricResult, Incident.
- `firesight/replay/` — deterministic discovery (verified timestamp patterns
  only, `CorruptFrameError`) and a threaded `ReplayEngine` streaming frames
  from an iterator (no full-sequence load).
- `firesight/demo/` — deterministic synthetic scene renderer + scenario
  (2 cameras, 2 sequences, 50 frames @5fps, GT source at ENU (3500, 2500)).
- `firesight/detection/` — `BaseDetector`/`build_detector`,
  `ClassicSmokeDetector` (CV blob heuristic, provenance `predicted`, NOT a
  trained model), lazy-import `YoloDetector` (no auto-download), drawing.
- `firesight/temporal/` — `TemporalTracker` (min 3 hits + persistence gate +
  dedup).
- `firesight/geometry/` — pure (no I/O) frames/bearing/uncertainty/
  triangulation incl. least-squares ray intersection and pairwise separation.
- `firesight/association/` — cross-camera association candidates.
- `firesight/vlm/` — `OpenAICompatibleVlm` (env-only key, never logged),
  `SimulatedVlmProvider` (demo), `NullVlmProvider` (real mode).

### 2026-10-20 — Phase I (API + services + CLI)
- `firesight/services/` — `AppContext` (startup/seeding/config overrides/
  shutdown), `CameraRepo`, incident service (filter/action/export),
  `eval_service`, `ReplayManager` (per-session pipeline: detect → temporal →
  annotated JPEG → persist → confirmation → bearing → cross-camera
  triangulation → merge duplicate; WS broadcast).
- `firesight/api/` — app factory with CORS + lifespan; routers under
  `/api/v1`: health, status, config, models, datasets, sequences, replays
  (+ WS `/ws/replays/{id}`), incidents, reports, cameras, geometry,
  evaluation, verification, inference.
- `firesight/cli.py` — entrypoint `firesight`: serve, db-init, inspect,
  sequences, replay, infer, geometry, evaluate, status.
- DB migration **v2** adds `settings_kv` (cleanly upgrades a v1 DB).

### 2026-10-20 — Phase J (React dashboard + integration)
- Frontend scaffolded with Vite 8 + React 19 + TypeScript; Tailwind v4 via
  `@tailwindcss/vite`, `recharts`, `leaflet`/`react-leaflet`, `lucide-react`,
  `react-router-dom`, linted with `oxlint`.
- `src/lib/api.ts` — single typed client for every backend endpoint plus
  `wsUrl()`; `ApiError` carries status + detail.
- Components: `ui.tsx` (Card, Badge, ProvenanceBadge, StatusBadge,
  GeometryBadge, StatCard, Spinner, EmptyState, ErrorState, DemoBanner),
  `Layout.tsx`, `nav.ts`.
- Pages (route-level code-split via lazy + Suspense): Overview, Replay
  (live WebSocket frame image + step/pause/resume/reset + event feed), Map
  (react-leaflet dark tiles, camera/estimate markers, bearing rays,
  FitBounds), Incidents, IncidentDetail (actions, VLM verify, observations /
  triangulation / history), Cameras (CRUD), Evaluation (recharts), Models,
  Datasets, System (config overrides).
- `vite.config.ts` proxies `/api` (incl. WebSocket) to the backend.
- Fixed a real WebSocket integration bug found during E2E: the router called
  a nonexistent manager method (`register_client`); it now registers the
  socket on the replay *session* (`add_ws`/`remove_ws`).
- Enriched the `frame` WS event to carry the full `LiveFrame` contract
  (`frame` metadata, `image_jpeg_base64`, detection list) so the Replay page
  renders real annotated frames. Added 2 API tests covering WS streaming and
  the unknown-replay error path.

### 2026-10-20 — Phase K (exports + demo video)
- `firesight/export/` — `demo_video.py` renders an annotated animated GIF
  from a sequence using the project detector, deterministic, no ffmpeg/network;
  `bundle.py` packages an incident as a ZIP (incident.json, incident.csv,
  manifest.json). Both raise explicit errors on missing input (no silent
  substitution).
- CLI: `firesight export-video <sequence_id> [--every N]` and
  `firesight export-incident <incident_id>`.
- API: `GET /api/v1/reports/{id}/download?format=zip` added alongside
  json/csv.
- `tests/test_export.py` — 5 tests (GIF rendering, missing/empty dir errors,
  bundle contents, unknown-incident error).

### 2026-10-20 — Phase L (docs + final verification)
- Docs written: `README.md`, `docs/ARCHITECTURE.md`, `docs/DATASETS.md`,
  `docs/MODEL_TRAINING.md`, `docs/CAMERA_CALIBRATION.md`,
  `docs/GEOLOCATION_AND_UNCERTAINTY.md`, `docs/EVALUATION.md`,
  `docs/DEMO_SCRIPT.md`.
- `scripts/dev.sh` — launcher for API :8000 + frontend :5173 with Ctrl-C
  cleanup; verified live.
- `.gitignore` extended with `*.gif`, `exports/`.
- Secret scan over the tree found only synthetic `.invalid`-host fixtures in
  `tests/test_vlm.py`; `tests/test_api.py` asserts `/config` never emits `sk-`.

### 2026-10-20 — Phase M (real CCTV footage registration)
- New `POST /api/v1/sequences` (`backend/firesight/api/routers/sequences.py`)
  registers a directory of JPG/JPEG/PNG frames as a **real** sequence.
  Validation: id pattern, path resolved with `resolve_under` (rejects absolute,
  traversal, symlink escapes, missing dir), non-empty image directory, optional
  camera must already exist, duplicate IDs rejected (409, never overwritten).
  Inserted with `provenance=real`, `synthetic=false`, preserving seeded demo
  sequences.
- Service logic in `AppContext.register_sequence`
  (`backend/firesight/services/context.py`) with `SequenceRegistrationError`
  and reason→HTTP mapping in the router. Response returns frame count, parsed
  start/end timestamps (or `timestamps_available: false`), camera association,
  provenance and validation warnings.
- Schemas: `SequenceCreateRequest` (requires `provenance: "real"`),
  `SequenceCreateResponse` (`backend/firesight/api/schemas.py`).
- Frontend: `api.registerSequence` + `RegisteredSequence` type
  (`frontend/src/lib/api.ts`); "Register footage sequence" form on the Datasets
  page with validation errors, result, warnings, and a
  `firesight:sequences-changed` event so Replay refreshes its sequence list.
- Tests: 13 new in `backend/tests/test_api.py::TestSequenceRegistration`
  (success with timestamps, camera + dimension warning, missing dir, empty dir,
  absolute/traversal, symlink escape, invalid camera, duplicate, demo not
  overwritten, unknown timestamps warning, replayable, bad id, wrong
  provenance). README documents the timestamp filename patterns and the
  extract→register→replay flow.

### 2026-10-20 — Phase N (video, live sources, alerts)
- Added `GET /api/v1/videos`, metadata, and byte-range streaming; two real
  Ranch2 FIgLib time-lapse MP4s now live under `backend/data/videos/` with a
  provenance manifest. Range requests return `206` with correct
  `Content-Range`; invalid ranges return `416`.
- Added sampled video analysis (`POST /videos/{id}/analyze`) with bounded
  original/annotated JPEGs, `summary.json`, `detections.csv`, `report.md`,
  DB rows, and explicit `experimental` / `timestamp_mapping: not_verified`
  labels. It creates one deduped alert per video/camera cooldown.
- Added persistent `alerts` table and service/API/WebSocket: list, stats,
  evidence, acknowledge, resolve, `new → acknowledged → resolved`.
- Added in-memory live-source manager and API/UI: RTSP (`rtsp://`, `rtsps://`)
  and looping local video. Credentials are stripped from API responses/logs;
  invalid schemes/paths are rejected; RTSP reconnects with backoff; previews
  and alerts are bounded. At implementation time no RTSP endpoint was
  available, so transport was marked unverified (see the 2026-10-20 RTSP
  loopback test below).
- Frontend: Replay page now has an image-sequence tab and a native `<video>`
  local-file tab; a polled fallback fixes blank initial frames and WS frames
  are downscaled from 3072×2048 to a bounded preview. New Live Sources and
  Alerts pages, nav routes, evidence views, and a global alert toast.
- Geolocation map no longer uses CARTO tiles (which can respond “API key
  required”). It now defaults to keyless OpenStreetMap tiles and includes an
  **Offline schematic** toggle that draws only the geometry on a local grid.
- `scripts/dev.sh` clears macOS `UF_HIDDEN` on the editable `.pth` after
  `uv sync`; without this, Python 3.11 silently skips the editable install and
  the backend fails with `ModuleNotFoundError: No module named 'firesight'`.
- Tests: 6 new in `backend/tests/test_videos_live_alerts.py` (FIgLib offset
  parsing, range streaming, analysis exports, alert lifecycle/dedupe, live
  file source, traversal and credential redaction).

### 2026-10-20 — RTSP loopback end-to-end test (real footage)
- Used the real Ranch2 FIgLib MP4 (`backend/data/videos/ranch2-sjh.mp4`) as the
  test source. A temporary MediaMTX v1.21.2 binary was run from the OS temp
  directory with a loopback-only config (`127.0.0.1:8554`, TCP, RTMP/HLS/
  WebRTC/SRT/API/metrics disabled). MediaMTX is **not** installed system-wide;
  `brew install mediamtx` would be needed for a persistent setup.
- FFmpeg republished the MP4 continuously:
  `ffmpeg -re -stream_loop -1 -i ranch2-sjh.mp4 -vf scale=1280:-2 -r 4
  -c:v libx264 ... -f rtsp -rtsp_transport tcp
  rtsp://127.0.0.1:8554/firesight-test`. `ffprobe` confirmed H.264,
  `1280x854`, `4/1` fps over `rtsp`. A captured frame was a valid 960×640 JPEG
  of the real Ranch2 view.
- FireSight source `liv_ce9cdf590e` (`Ranch2 Fire RTSP Test`, sample 1 fps,
  threshold 0.25, min_consecutive 3) reached `running` with `error: null` and
  advanced to 660 frames read / 130 processed / 338 detections while the
  preview endpoint returned `200 image/jpeg` with detector overlays.
- One deduped alert was persisted: `alr_877d53f12a9c`, detector
  `classic-smoke-blob` v0.1.0, confidence 0.7109, `verification_status:
  experimental`, evidence JPEG 960×640. `POST /acknowledge` then `/resolve`
  moved it `new → acknowledged → resolved` with timestamps.
- Negative test: source `liv_5528aaf310` pointed at closed port 8555 reported
  `status: reconnecting`, `error: "Could not open the stream/source"`,
  `has_frame: false`, and the preview endpoint returned `404` — no simulated
  success or placeholder frame.
- Cleanup: deleted the invalid source, stopped `liv_ce9cdf590e`
  (`status: stopped`), terminated the recorded FFmpeg and MediaMTX PIDs, and
  confirmed port 8554 had no listener. Backend (:8000) and Vite (:5173)
  processes were left running.

## Verification actually run

- `cd backend && uv run pytest -q` → **204 passed** (was 198; +6 for video,
  live sources and alerts). Geometry 32, demo
  pipeline 11, replay, temporal, association 7, vlm, evaluation, datasets,
  api 38 incl. 2 WebSocket tests, export 5.
- `cd backend && uv run ruff check .` → **All checks passed!**
- `uv run firesight status` / `replay demo-alpha-ridge --frames 45` /
  `evaluate` → run successfully.
- `uv run firesight serve` on :8123 → `/api/v1/health`, `/sequences`,
  `/replays` (create) and `/incidents` all returned live data; replay
  produced incidents.
- Two-camera replay produced 5 triangulations of quality `strong`
  (ray separation ~106°, uncertainty ~140–220 m). Best fix was within ~2 m
  of the demo ground-truth source coordinate — a sanity check of the geometry
  engine on synthetic data only.
- Frontend: `npm run build` → success, route-level code splitting (largest
  chunk 361 kB, gzip 105 kB); `npm run lint` → **0 warnings, 0 errors**.
- Phase N live checks against `127.0.0.1:8000`: both real MP4s listed
  (78/77 frames, 4 fps, 3072×2048); `Range: bytes=0-99` → `206` with 100
  bytes and `Content-Range: bytes 0-99/24682288`; sampled SJH analysis (4
  frames, 12 heuristic detections, alert `alr_…`) wrote exports and evidence;
  live file source reached `running` with 16 frames read / 8 processed / 24
  detections and a 63 KB preview; real replay WS delivered a 152,072-byte
  base64 preview (downscaled) and accepted `pause`.
- RTSP loopback test (see log above) succeeded end-to-end: real Ranch2 MP4
  republished by MediaMTX/FFmpeg → FireSight source `liv_ce9cdf590e` reached
  660 frames read / 338 detections, preview `200 image/jpeg`, alert
  `alr_877d53f12a9c` acknowledged and resolved. Invalid RTSP source produced an
  explicit error and `404` preview, and cleanup released port 8554.
- E2E smoke (backend on :8000, Vite dev on :5173): frontend served the app
  shell; `/api/v1/health` through the Vite proxy returned
  `{"status":"ok","mode":"demo"}`; replay creation, incidents list, and the
  WebSocket stream (status → frame with JPEG → temporal_alert →
  incident_created) all verified through the proxy.

### 2026-10-20 — Replay concurrency lifecycle correction
- Replay capacity now counts only non-terminal sessions; finished/error
  sessions remain available for history without consuming concurrency slots.
- In-memory status now reports `finished` when a non-looping sequence reaches
  its final frame, matching the finish callback's persisted state.
- Added an API regression covering the eight-session limit and slot reuse
  after completion. `uv run pytest -q
  tests/test_api.py::TestReplayLifecycle` → **5 passed**;
  `uv run ruff check firesight/services/replay_manager.py tests/test_api.py` →
  **All checks passed** (one existing Starlette/httpx deprecation warning).

## Blocked / not verified

- No trained smoke model: `ClassicSmokeDetector` is a heuristic and the YOLO
  path is untrained/untested on real imagery.
- Real FIgLib Ranch2 stills and time-lapse MP4s are now local, but Pyro-SDIS
  is not downloaded. No real-world detection accuracy has been measured.
- RTSP transport was exercised only against a **local MediaMTX loopback**
  republishing an MP4. No physical camera, authenticated RTSP, TLS (`rtsps://`)
  or long-duration network loss/reconnect test has been performed.
- Browser video playback, live previews and alert toasts are verified only by
  build/lint and HTTP/WS checks, not by automated DOM/browser tests.
- No camera calibration performed on real devices; demo cameras are
  `calibration_status=simulated`.
- No external VLM calls made (no credentials); demo uses the simulated
  provider, real mode returns an explicit disabled state.
- Phase J frontend is verified by build/lint and an HTTP+WebSocket smoke
  test, **not** by automated browser (DOM) tests — no Playwright/headless
  browser run was performed. Visual layout is unverified by tooling.
- Demo video/export tooling and documentation are complete; only the items
  above remain genuinely unverified.
- `detection_latency_s` on the demo fixture reads 0.0 s because the synthetic
  plume appears exactly at the labelled onset and the heuristic fires on the
  same frame. This is a property of the fixture, not a real-world result, and
  the metric is stored with `provenance=simulated`.

## Overall status

All phases A–N are implemented. Backend: 204 tests passing, ruff clean.
Frontend: builds and lints clean, integrated against a live backend over HTTP
and WebSocket. The project is a **research/portfolio prototype** — it has real
FIgLib footage but no trained smoke model, no real camera calibration, and
reports no real-world accuracy. RTSP ingestion is verified end-to-end over a
local MediaMTX loopback (real footage republished), but not against a physical
camera. Every one of those gaps is surfaced as an explicit
unavailable/experimental state with a reason rather than a fabricated number.

