"""Export a single incident as a portable ZIP bundle.

The bundle contains machine-readable JSON, a flat CSV row, and a small
manifest describing provenance and the disclaimer. It is built only from the
local SQLite database and never fabricates missing evidence: if the incident
does not exist, an explicit error is raised.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from ..db import Database, utcnow_iso
from ..services import incidents as incident_service


class IncidentBundleError(RuntimeError):
    """Raised when an incident bundle cannot be produced."""


def export_incident_bundle(db: Database, incident_id: str, out_path: Path) -> Path:
    """Write a ZIP bundle for ``incident_id`` to ``out_path`` and return it."""
    export = incident_service.export_json(db, incident_id)
    if export is None:
        raise IncidentBundleError(f"incident not found: {incident_id}")
    csv_text = incident_service.export_csv(db, incident_id)
    if csv_text is None:
        raise IncidentBundleError(f"incident not found: {incident_id}")

    inc = export["incident"]
    manifest = {
        "bundle_version": 1,
        "generated_at": utcnow_iso(),
        "incident_id": incident_id,
        "status": inc.get("status"),
        "provenance": inc.get("provenance"),
        "mode": inc.get("mode"),
        "geometry_quality": inc.get("geometry_quality"),
        "location_uncertainty_m": inc.get("location_uncertainty_m"),
        "ground_truth_available": bool(inc.get("ground_truth_available")),
        "files": ["incident.json", "incident.csv", "manifest.json"],
        "disclaimer": export["disclaimer"],
    }

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("incident.json", json.dumps(export, indent=2, default=str))
        zf.writestr("incident.csv", csv_text)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))
    out_path.write_bytes(buf.getvalue())
    return out_path
