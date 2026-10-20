"""Deterministic demo export helpers (Phase K).

These utilities produce shareable artefacts from SIMULATED demo data only.
They never touch real datasets or weights and require no external binaries:
animated frames are encoded as GIF via Pillow, and incident bundles are ZIP
archives of JSON/CSV built from the local database.

Provenance is preserved end to end. If a required input is missing the
functions raise an explicit error rather than silently substituting data.
"""

from __future__ import annotations

from .bundle import IncidentBundleError, export_incident_bundle
from .demo_video import DemoVideoError, render_annotated_video

__all__ = [
    "DemoVideoError",
    "IncidentBundleError",
    "export_incident_bundle",
    "render_annotated_video",
]
