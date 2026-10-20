# Camera calibration

FireSight converts a pixel in a camera image into a compass bearing using a
small, explicit calibration model. Real geolocation depends entirely on the
quality of this calibration — a camera that is not calibrated cannot produce a
trustworthy location, and FireSight says so instead of guessing.

## The model

A camera is described by `CameraConfig` (`models.py`):

| Field | Meaning |
|-------|---------|
| `latitude`, `longitude` | Camera position (WGS84). |
| `height_m` | Height above ground. |
| `heading_deg` | Compass heading (clockwise from north) of the image centre. |
| `hfov_deg` | Horizontal field of view, in `(0, 180]`. |
| `image_width`, `image_height` | Frame dimensions in pixels. |
| `calibration_status` | `simulated`, `uncalibrated`, `approximate`, or `validated`. |
| `calibration_source` | Free-text provenance of the calibration. |
| `calibration_uncertainty_deg` | 1σ heading uncertainty, if known. |
| `provenance` | `manual` / `simulated` / `real` for the record itself. |

### Pixel → bearing (`geometry/bearing.py`)

```
x_norm = (pixel_x / image_width) * 2 − 1          # −1 (left) … +1 (right)
x_norm = undistort(x_norm, lens)                   # optional radial (k1, k2)
angle  = x_norm * (hfov_deg / 2)
bearing = (heading_deg + angle) mod 360
```

`LensModel(k1, k2)` applies a radial polynomial. When `k1 = k2 = 0` the model
is purely linear (pinhole). Undistortion inverts the polynomial by a fixed-point
iteration; the forward projection (`bearing_to_pixel`) is used to draw bearing
rays on the map and returns `None` when a bearing falls outside the FOV.

The proxy point on a detection box defaults to its **bottom-centre**, which is
the standard choice for a ground-level source. `proxy_point_from_bbox` also
supports `center`.

## Calibration status and trust

`CalibrationStatus` gates how results are presented:

- `simulated` — demo cameras. Geometry is genuine but the camera is fake. The
  UI and exports label this clearly.
- `uncalibrated` — no reliable heading/FOV. Bearings are not trustworthy;
  incidents from such cameras should be treated as low-confidence and are
  flagged.
- `approximate` — heading from map/compass reading, coarse FOV.
- `validated` — heading and FOV established by a survey or reference targets.

When `calibration_uncertainty_deg` is present, it feeds directly into the
position uncertainty (see `docs/GEOLOCATION_AND_UNCERTAINTY.md`).

## How to calibrate a real fixed camera

1. **Position** — record latitude/longitude and height (GNSS or survey).
2. **Heading** — point the camera at a known landmark or use a reference mark
   at a known bearing; set `heading_deg` so the image centre matches.
3. **FOV** — use the lens/sensor spec, or two known references at known
   bearings spanning the frame, and solve for `hfov_deg`.
4. **Lens distortion** — if the lens is wide, estimate `k1`/`k2` from a grid
   target and store them in the `LensModel`.
5. **Validate** — project a few known ground features and compare predicted vs.
   measured pixel columns. Set `calibration_status=validated` and
   `calibration_uncertainty_deg` once the residual is acceptable.

## Managing cameras

Via the API (`/api/v1/cameras`) or the **Cameras** page in the dashboard.
Demo mode seeds two simulated cameras (`sim-cam-a`, `sim-cam-b`).

## Honest status

No camera in this repository has been calibrated against a real device. The
only cameras present are the `simulated` demo ones. See
[`docs/BUILD_STATUS.md`](BUILD_STATUS.md).
