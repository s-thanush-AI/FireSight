# Evaluation

FireSight's evaluation layer is built around one rule: **never report a number
you cannot justify.** When ground truth is missing, unlabelled, or of a
different provenance than the estimate, a metric is returned as
`UNAVAILABLE` **with a reason** instead of a value.

Code: `evaluation/metrics.py`, `services/eval_service.py`.
Tests: `tests/test_evaluation.py`.

## MetricResult

Every metric is a `MetricResult` carrying enough context to be trusted or
discarded:

| Field | Meaning |
|-------|---------|
| `name`, `value`, `unit` | The measurement. |
| `sample_count` | How many items the number is based on. |
| `data_source` | Human-readable provenance of the input data. |
| `ground_truth_available` | Whether trustworthy GT existed. |
| `validity` | `valid` or `unavailable`. |
| `limitation` | Why it is unavailable / what limits it. |
| `provenance` | `simulated`, `predicted`, `heuristic`, `real`, … |

## Implemented metrics

- **Detection precision / recall / F1** — greedy IoU matching
  (`match_boxes`, default IoU 0.3) producing a confusion count. Unavailable if
  there is no labelled ground truth.
- **Detection latency** — time from a known onset to the first matching alert.
  Requires sufficient frame timing and a known onset.
- **False alerts per camera-hour** — needs *labelled negatives*. In demo mode
  negatives are unlabelled, so this metric is **unavailable with a reason**
  rather than a fabricated rate.
- **Geolocation error (metres)** — geodesic distance between the estimate and
  a reliable ground-truth coordinate. Unavailable unless both exist.

## Provenance gating

Simulated evidence is never scored against real ground truth, and vice versa.
The demo-fixture evaluation is stored with `provenance = simulated` and a note
stating it validates **pipeline mechanics only**. The UI shows a
`ProvenanceBadge` on every metric.

## Running an evaluation

```bash
cd backend && uv run firesight evaluate           # demo fixture
# or, via the API:
curl -X POST localhost:8000/api/v1/evaluation/runs \
     -H 'content-type: application/json' \
     -d '{"name":"api run","kind":"demo_fixture"}'
```

Results appear at `GET /api/v1/evaluation/runs` and in the dashboard's
**Evaluation** page (a bar chart plus per-metric detail including any
limitation text).

## What the demo numbers mean (and do not)

The demo fixture compares `ClassicSmokeDetector` against boxes produced by the
*same synthetic generator* that drew the plume. This checks that the pipeline
wires up, that the detector responds to the plume, and that the geometry is
self-consistent. It is **not** real-world detection accuracy.

The only location error reported in this repo is a synthetic self-consistency
check: two simulated cameras with perfect bearings localising a synthetic
source whose position is known exactly (best fix within ~2 m; see
[`docs/GEOLOCATION_AND_UNCERTAINTY.md`](GEOLOCATION_AND_UNCERTAINTY.md)).

## What has *not* been evaluated

- No real wildfire imagery was scored. No precision/recall/mAP on real data.
- No false-alarm rate was measured (requires labelled negatives / long
  background periods).
- No VLM verification accuracy (no model was called).
- No camera calibration residuals on real hardware.

These are stated as unavailable, not estimated. See
[`docs/BUILD_STATUS.md`](BUILD_STATUS.md) for the machine-checked record.
