"""Incident queries, status transitions and evidence export."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime

from ..db import Database, dumps, utcnow_iso
from ..enums import IncidentStatus

ALLOWED_ACTIONS: dict[str, tuple[IncidentStatus | None, str]] = {
    # action -> (target status or None to keep, actor label)
    "acknowledge": (IncidentStatus.ACKNOWLEDGED, "human"),
    "dismiss": (IncidentStatus.DISMISSED, "human"),
    "reopen": (IncidentStatus.CANDIDATE, "human"),
    "mark_reviewed": (IncidentStatus.REVIEWED, "human"),
}

STATUS_FILTERS = {s.value for s in IncidentStatus}


class IncidentError(ValueError):
    pass


def list_incidents(
    db: Database,
    *,
    status: str | None = None,
    provenance: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    search: str | None = None,
    sort: str = "created_at:desc",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    where: list[str] = []
    params: list[object] = []
    if status:
        if status not in STATUS_FILTERS:
            raise IncidentError(f"Unknown status filter: {status}")
        where.append("status = ?")
        params.append(status)
    if provenance:
        where.append("provenance = ?")
        params.append(provenance)
    if severity:
        where.append("severity_tier = ?")
        params.append(severity)
    if source:
        where.append("source_dataset LIKE ?")
        params.append(f"%{source}%")
    if search:
        where.append("(title LIKE ? OR summary LIKE ? OR id LIKE ?)")
        params.extend([f"%{search}%"] * 3)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    sort_col, _, direction = sort.partition(":")
    allowed_cols = {"created_at", "updated_at", "severity_tier", "status", "last_seen_ts"}
    if sort_col not in allowed_cols:
        raise IncidentError(f"Cannot sort by {sort_col}")
    direction = "ASC" if direction.lower() == "asc" else "DESC"
    total = db.query_one(f"SELECT COUNT(*) AS n FROM incidents {clause}", tuple(params))["n"]
    rows = db.query(
        f"SELECT * FROM incidents {clause} ORDER BY {sort_col} {direction} LIMIT ? OFFSET ?",
        (*params, min(int(limit), 200), max(int(offset), 0)),
    )
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def get_incident(db: Database, incident_id: str) -> dict | None:
    inc = db.query_one("SELECT * FROM incidents WHERE id=?", (incident_id,))
    if inc is None:
        return None
    observations = db.query(
        "SELECT * FROM observations WHERE incident_id=? ORDER BY created_at", (incident_id,)
    )
    triangulations = db.query(
        "SELECT * FROM triangulations WHERE incident_id=? ORDER BY created_at", (incident_id,)
    )
    history = db.query(
        "SELECT * FROM incident_status_history WHERE incident_id=? ORDER BY created_at",
        (incident_id,),
    )
    vlm = db.query(
        "SELECT * FROM vlm_verifications WHERE incident_id=? ORDER BY request_time",
        (incident_id,),
    )
    # related frames: replays that produced this incident's observations
    replay_ids = {o["replay_id"] for o in observations if o.get("replay_id")}
    frames: list[dict] = []
    for rid in replay_ids:
        frames.extend(
            db.query(
                "SELECT * FROM frames WHERE replay_id=? ORDER BY index_in_sequence LIMIT 5",
                (rid,),
            )
        )
    return {
        "incident": inc,
        "observations": observations,
        "triangulations": triangulations,
        "history": history,
        "vlm_verifications": vlm,
        "frames": frames[:10],
    }


def apply_action(db: Database, incident_id: str, action: str, reason: str | None) -> dict:
    inc = db.query_one("SELECT * FROM incidents WHERE id=?", (incident_id,))
    if inc is None:
        raise IncidentError(f"Unknown incident: {incident_id}")
    if action not in ALLOWED_ACTIONS:
        raise IncidentError(
            f"Unknown action '{action}'. Allowed: {', '.join(sorted(ALLOWED_ACTIONS))}"
        )
    target, actor = ALLOWED_ACTIONS[action]
    current = IncidentStatus(inc["status"])
    if action == "reopen" and current not in (
        IncidentStatus.DISMISSED, IncidentStatus.REVIEWED, IncidentStatus.ACKNOWLEDGED
    ):
        raise IncidentError("Only dismissed/reviewed/acknowledged incidents can be reopened")
    if action == "acknowledge" and current == IncidentStatus.DISMISSED:
        raise IncidentError("Dismissed incidents cannot be acknowledged; reopen first")
    now = utcnow_iso()
    new_status = target.value if target else current.value
    db.execute(
        "UPDATE incidents SET status=?, updated_at=? WHERE id=?",
        (new_status, now, incident_id),
    )
    db.execute(
        """INSERT INTO incident_status_history (incident_id, from_status, to_status,
             action, actor, reason, created_at) VALUES (?,?,?,?,?,?,?)""",
        (incident_id, current.value, new_status, action, actor, reason, now),
    )
    db.execute(
        """INSERT INTO audit_entries (entity_type, entity_id, action, actor, details_json,
             created_at) VALUES (?,?,?,?,?,?)""",
        (
            "incident", incident_id, action, actor,
            dumps({"reason": reason, "from": current.value, "to": new_status}), now,
        ),
    )
    return db.query_one("SELECT * FROM incidents WHERE id=?", (incident_id,))


def export_json(db: Database, incident_id: str) -> dict | None:
    data = get_incident(db, incident_id)
    if data is None:
        return None
    return {
        "exported_at": utcnow_iso(),
        "incident": data["incident"],
        "observations": data["observations"],
        "triangulations": data["triangulations"],
        "history": data["history"],
        "vlm_verifications": data["vlm_verifications"],
        "frames": data["frames"],
        "disclaimer": (
            "FireSight research prototype export. Provenance fields distinguish real, "
            "predicted, simulated, heuristic and manual evidence. Estimates are not "
            "operational warnings."
        ),
    }


EXPORT_COLUMNS = [
    "incident_id", "status", "severity_tier", "title", "provenance", "mode",
    "latitude", "longitude", "location_uncertainty_m", "geometry_quality",
    "ray_separation_deg", "vlm_assessment", "ground_truth_available",
    "first_seen_ts", "created_at", "updated_at",
]


def export_csv(db: Database, incident_id: str) -> str | None:
    inc = db.query_one("SELECT * FROM incidents WHERE id=?", (incident_id,))
    if inc is None:
        return None
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    row = {k: inc.get(k) for k in EXPORT_COLUMNS}
    row["incident_id"] = inc["id"]
    row["ground_truth_available"] = bool(inc["ground_truth_available"])
    writer.writerow(row)
    return buf.getvalue()


def counts_by_status(db: Database) -> dict[str, int]:
    rows = db.query("SELECT status, COUNT(*) AS n FROM incidents GROUP BY status")
    out = {s.value: 0 for s in IncidentStatus}
    for r in rows:
        out[r["status"]] = r["n"]
    return out


def now_utc() -> datetime:
    return datetime.now(UTC)


def new_incident_id() -> str:
    return f"inc_{uuid.uuid4().hex[:12]}"
