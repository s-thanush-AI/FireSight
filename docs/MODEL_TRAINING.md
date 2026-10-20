# Model training

FireSight ships **no trained smoke model**. Out of the box it runs a classic
computer-vision detector so demo mode works with zero downloads. A YOLO
adapter exists for real deployments but is *untrained here* and is imported
lazily so torch/ultralytics are never installed unless you ask for them.

## Detectors

### `ClassicSmokeDetector` (default, demo + no-weights)

- Location: `detection/classic.py`.
- A colour/texture blob heuristic over the frame; emits boxes with
  `provenance = predicted` and `model_name = classic-smoke-blob`.
- **Not a trained model.** It is a stand-in that makes the pipeline runnable
  and testable. Its outputs are not evidence of detection accuracy.

### `YoloDetector` (optional, real mode)

- Location: `detection/yolo.py`.
- Selected by `build_detector` when `FIRESIGHT_DETECTOR__KIND=yolo` or when
  `FIRESIGHT_MODE=real` with a weights path configured.
- **Lazy import**: importing the module is cheap; `ultralytics`/`torch` are
  imported only when a detector is built. No weights are auto-downloaded.
- If weights/deps/device are missing, it reports `available = False` with an
  explicit `unavailable_reason`; the pipeline surfaces an error state rather
  than silently substituting a simulated detector.

## Enabling the YOLO extra

```bash
cd backend
uv sync --extra yolo          # downloads torch + ultralytics
```

Set the weights path via environment:

```bash
export FIRESIGHT_MODE=real
export FIRESIGHT_MODEL_PATH=/absolute/path/to/smoke.pt
export FIRESIGHT_DEVICE=auto      # auto | cpu | mps | cuda
```

## Preparing training data

FireSight provides **preparation helpers only** — you supply the data (see
`docs/DATASETS.md`).

```python
from pathlib import Path
from firesight.datasets.pyrosdis import prepare_pyrosdis, make_event_split

events = prepare_pyrosdis(Path("data/pyro-sdis-raw"), Path("data/pyro-sdis"))
train, val = make_event_split(sorted(events), val_fraction=0.25, seed=7)
```

`make_event_split` splits at the **event** level so frames from one fire never
appear in both train and val (no frame-level leakage). The split is
deterministic for a given seed.

## Training (reference recipe, not run here)

The following is a reference recipe to train a smoke detector. It was **not**
executed in this repository, and no resulting metrics are reported.

```bash
# Example only — requires the `yolo` extra and a local dataset.
cd backend && uv sync --extra yolo
uv run yolo detect train \
  data=data/pyro-sdis/dataset.yaml \
  model=yolov8n.pt \
  epochs=50 imgsz=640
```

Findings to record honestly when you do train:

- dataset provenance and license;
- event-level split definition;
- per-class precision/recall and mAP, with the confidence/IoU thresholds;
- the exact model version and weights hash.

## Wiring a trained model back in

Set `FIRESIGHT_MODEL_PATH` to the `.pt` file and restart. `/api/v1/models`
reports the detector metadata, and `firesight status` prints whether it is
available. In `real` mode FireSight **never** falls back to the classic
heuristic; a missing model is reported as unavailable.

## Honest status

As of the last build: no smoke model has been trained or evaluated on real
imagery in this repository. See
[`docs/BUILD_STATUS.md`](BUILD_STATUS.md) for the machine-checked record.
