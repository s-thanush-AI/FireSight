"""Local metric coordinate frames.

Cameras are configured in WGS84 lat/lon. Geometry runs in a local East-North-Up
(ENU) metric frame centred on the mean camera position. Conversion uses a WGS84
azimuthal-equidistant projection via pyproj when available, with a documented
equirectangular fallback (adequate below ~50 km).
"""

from __future__ import annotations

import math
from functools import lru_cache

try:  # optional accelerator; fallback keeps geometry pure-stdlib testable
    from pyproj import CRS, Geod, Transformer

    _HAS_PYPROJ = True
    _GEOD = Geod(ellps="WGS84")
except Exception:  # pragma: no cover - exercised only without pyproj
    _HAS_PYPROJ = False
    _GEOD = None

EARTH_RADIUS_M = 6_371_000.0


@lru_cache(maxsize=8)
def _aeqd_transformers(origin_lat: float, origin_lon: float):
    crs_local = CRS.from_proj4(
        f"+proj=aeqd +lat_0={origin_lat} +lon_0={origin_lon} +ellps=WGS84 +units=m +no_defs"
    )
    crs_wgs = CRS.from_epsg(4326)
    fwd = Transformer.from_crs(crs_wgs, crs_local, always_xy=True)
    inv = Transformer.from_crs(crs_local, crs_wgs, always_xy=True)
    return fwd, inv


def latlon_to_enu(
    lat: float, lon: float, origin_lat: float, origin_lon: float
) -> tuple[float, float]:
    """Convert WGS84 (lat, lon) to local East/North metres about the origin.

    Returns (east, north).
    """
    if _HAS_PYPROJ:
        fwd, _ = _aeqd_transformers(origin_lat, origin_lon)
        e, n = fwd.transform(lon, lat)
        return float(e), float(n)
    # Equirectangular fallback (documented approximation).
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    olat_r = math.radians(origin_lat)
    olon_r = math.radians(origin_lon)
    n = (lat_r - olat_r) * EARTH_RADIUS_M
    e = (lon_r - olon_r) * EARTH_RADIUS_M * math.cos((lat_r + olat_r) / 2.0)
    return e, n


def enu_to_latlon(
    east: float, north: float, origin_lat: float, origin_lon: float
) -> tuple[float, float]:
    """Inverse of latlon_to_enu. Returns (lat, lon)."""
    if _HAS_PYPROJ:
        _, inv = _aeqd_transformers(origin_lat, origin_lon)
        lon, lat = inv.transform(east, north)
        return float(lat), float(lon)
    olat_r = math.radians(origin_lat)
    lat_r = olat_r + north / EARTH_RADIUS_M
    lon_r = math.radians(origin_lon) + east / (
        EARTH_RADIUS_M * math.cos((lat_r + olat_r) / 2.0)
    )
    return math.degrees(lat_r), math.degrees(lon_r)


def geodesic_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (WGS84 when pyproj is available)."""
    if _HAS_PYPROJ and _GEOD is not None:
        _, _, d = _GEOD.inv(lon1, lat1, lon2, lat2)
        return float(d)
    # Haversine fallback
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
