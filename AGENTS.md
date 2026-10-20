# AGENTS.md — FireSight project rules

FireSight is a **research/portfolio prototype**: wildfire smoke detection and
geolocation from fixed observation cameras. It is **not** an operational
warning service. Never claim production readiness, real emergency capability,
or measured accuracy that the repository cannot demonstrate.

## Repository layout

```
backend/     Python package `firesight` (FastAPI API, CV, geometry, evaluation)
frontend/    React + TypeScript + Vite dashboard
scripts/     developer launcher and helper shell scripts
docs/        architecture, datasets, training, calibration, evaluation, status
data/        local datasets / sequences (gitignored)
models/      model weights (gitignored)
```

## Hard rules

1. **Provenance is sacred.** Every observation, incident, bearing, metric and
   VLM decision carries `provenance` from: `real`, `predicted`, `simulated`,
   `heuristic`, `manual`. Never mix simulated evidence into real evaluation.
2. **Demo mode must work with zero credentials, zero datasets, zero weights,
   zero GPU.** Deterministic seeds and static fixtures only.
3. **Real-data mode never silently falls back to simulation.** Missing data,
   weights, calibration or ground truth → explicit "unavailable"/"unvalidated"
   state with a reason.
4. **No fabricated metrics.** If ground truth is missing, return an
   unavailable metric with a reason instead of a number.
5. **No secrets in code, UI, logs, API responses or the frontend bundle.**
   API keys come from environment only; never echo them back.
6. **No destructive git operations.** Do not commit, push, reset, or rewrite
   history unless a human explicitly asks.
7. **No giant untested dumps.** Implement in phases; run tests after each
   phase and fix genuine failures. Never weaken or delete a test to pass.
8. **Geometry stays pure.** `backend/firesight/geometry` has no I/O, no DB,
   no FastAPI imports. It must be testable with hand-computed cases.
9. **Bounded resources.** Replays stream frames (iterator), never load a
   whole sequence into memory. Frame persistence in SQLite is capped.
10. **Path safety.** No arbitrary filesystem browsing through user input;
    dataset paths resolve under the configured data root; archive extraction
    prevents path traversal.

## Verification commands

Run from the repository root:

```bash
# Backend environment (uv)
cd backend && uv sync --all-extras   # or: uv sync  (core only, no YOLO)

# Backend lint + tests
cd backend && uv run ruff check .
cd backend && uv run pytest -q

# Frontend
cd frontend && npm install
cd frontend && npm run build         # tsc -b && vite build
cd frontend && npm run lint

# Full local launch (API :8000 + frontend :5173)
./scripts/dev.sh                     # stop with Ctrl-C, kills children
```

Optional YOLO extras (downloads torch, only when you ask for it):

```bash
cd backend && uv sync --extra yolo
```

## Conventions

- Python ≥ 3.11, managed with `uv`. Package lives in `backend/` (`uv run …`).
- Ruff is the linter. Type hints everywhere in public functions.
- API is versioned under `/api/v1`; response models are Pydantic schemas in
  `backend/firesight/api/schemas.py`.
- SQLite schema is created through a versioned initializer
  (`firesight/db.py`), never by dropping tables at startup.
- Frontend talks to the backend through one typed client
  (`frontend/src/lib/api.ts`) only.
- Update `docs/BUILD_STATUS.md` at the end of every phase with honest,
  verified results — including what could not be verified and why.
