# Geolocation and uncertainty

FireSight estimates a smoke-source location by intersecting **horizontal
bearings** from two or more calibrated cameras. It is a bearing-only
(azimuth) method: no range is measured directly, so a location is only as good
as the *crossing geometry* between the cameras.

All of this geometry is pure and lives in `firesight/geometry/` — no I/O, no
DB, no FastAPI. It is tested against hand-computed cases
(`tests/test_geometry.py`).

## 1. Coordinates

Bearings are converted into a local **ENU** (East-North-Up, metres) frame
centred on the mean of the participating cameras
(`geometry/frames.py`). `latlon_to_enu` / `enu_to_latlon` do the local
projection; the resulting metres are converted back to WGS84.

## 2. From pixel to bearing

See [`docs/CAMERA_CALIBRATION.md`](CAMERA_CALIBRATION.md). A detection box's
**bottom-centre** proxy point becomes a compass bearing:
`bearing = heading + x_norm * (hfov/2)`.

## 3. Rays and least-squares intersection

Each observation becomes a ray from the camera in ENU (`ray_from_camera`):

```
direction_e = sin(bearing)
direction_n = cos(bearing)
```

The intersection point minimises the sum of squared **perpendicular**
distances to all rays:

```
min_x  Σ_i  || (I − d_i d_iᵀ)(x − o_i) ||²
```

which reduces to a 2×2 linear system (`_lsq_intersection`). If the determinant
is ~0 the rays are (nearly) parallel and the system is degenerate.

## 4. Quality gates

`triangulate` refuses to emit a number when the geometry cannot support one.
Each rejection carries a `quality` and an explicit limitation string:

| Condition | Quality | Meaning |
|-----------|---------|---------|
| < 2 observations | `unavailable` | Cannot intersect a single bearing. |
| Missing camera config | `unavailable` | Position/heading unknown. |
| Any camera `uncalibrated` | `unavailable` | Refuses to guess a location. |
| Parallel rays (degenerate) | `rejected` | Ill-conditioned intersection. |
| Intersection behind a camera | `rejected` | Bearings are mutually incompatible. |
| Distance > `max_distance_m` (default 60 km) | `rejected` | Unreasonable range. |
| Ray separation < `min_separation_deg` (default 4°) | `rejected` | Crossing angle too weak. |

Accepted estimates are graded:

| Min pairwise ray separation | Quality |
|-----------------------------|---------|
| ≥ 30° | `strong` |
| 15°–30° | `acceptable` |
| 4°–15° | `weak` |

A large **fit residual** downgrades quality to `weak` regardless of separation
(`residual_limit = max(30 m, 2% of range)`), signalling that the bearings do
not cross cleanly (detector or association error).

## 5. Uncertainty

Two error sources are modelled as independent per-camera Gaussians
(`geometry/uncertainty.py`):

- **Detector localisation**: `pixel_sigma_deg = (pixel_sigma_frac · hfov) / 2`
  with `pixel_sigma_frac = 0.01` by default (1% of frame width).
- **Camera heading**: `heading_sigma_deg = 1.5°` by default, plus the camera's
  own `calibration_uncertainty_deg` combined in quadrature.

Per-camera bearing sigma:

```
sigma_bearing = hypot(pixel_sigma_deg, heading_sigma_deg)
```

First-order position sigma at the crossing, using the worst (largest) camera
contribution:

```
sigma_pos ≈ R · radians(sigma_bearing) / sin(theta)
```

where `R` is the range to the intersection and `theta` the ray intersection
angle. This **diverges** as the rays become parallel (`theta → 0`/`180°`) and
is reported as `inf` (an unavailable number) rather than a large finite value.
This is the key intuition: two cameras nearly in line with the plume cannot
localise it along the range direction no matter how precise each bearing is.

## 6. Reported fields

`TriangulationResult` carries: `quality`, `latitude`, `longitude`,
`uncertainty_m` (1σ), `ray_separation_deg`, `intersection_angle_deg`,
`fit_residual_m`, `distances_per_camera_m`, `method`, plus `assumptions` and
`limitations` lists. `provenance` is `heuristic` — geometry is not simulated or
real imagery; it is a computation over whatever bearings it was given.

## 7. What the estimate is *not*

- It is a **smoke-source proxy**, not a proven fire origin. Smoke is
  wind-driven and the plume drifts.
- Elevation is ignored; bearings are horizontal azimuths.
- Terrain, haze and imperfect detector boxes add error that the simple
  Gaussian model does not capture.

## Honest status — demo numbers

The only location error reported anywhere in this repository is a
**synthetic self-consistency check** on the deterministic demo scenario: two
simulated cameras ~6 km apart see a synthetic plume whose true ENU position is
known exactly. Two-camera replays produced `strong` triangulations (ray
separation ~106°, uncertainty ~140–220 m) with the best fix within ~2 m of the
synthetic ground-truth coordinate. This validates that the geometry pipeline is
self-consistent on perfect simulated bearings. **It says nothing about real
accuracy.** See [`docs/EVALUATION.md`](EVALUATION.md).
