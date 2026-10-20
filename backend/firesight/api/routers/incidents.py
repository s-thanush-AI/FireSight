from fastapi import APIRouter, HTTPException, Query, Response

from ...api.schemas import IncidentPatchRequest
from ...services import incidents as incidents_service
from ...services.context import get_context

router = APIRouter(tags=["incidents"])


@router.get("/incidents")
def list_incidents(
    status: str | None = None,
    provenance: str | None = None,
    severity: str | None = None,
    source: str | None = None,
    search: str | None = None,
    sort: str = Query("created_at:desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    ctx = get_context()
    try:
        return incidents_service.list_incidents(
            ctx.db, status=status, provenance=provenance, severity=severity,
            source=source, search=search, sort=sort, limit=limit, offset=offset,
        )
    except incidents_service.IncidentError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str) -> dict:
    ctx = get_context()
    data = incidents_service.get_incident(ctx.db, incident_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident: {incident_id}")
    return data


@router.patch("/incidents/{incident_id}")
def patch_incident(incident_id: str, body: IncidentPatchRequest) -> dict:
    ctx = get_context()
    try:
        row = incidents_service.apply_action(ctx.db, incident_id, body.action, body.reason)
    except incidents_service.IncidentError as e:
        code = 404 if "Unknown incident" in str(e) else 422
        raise HTTPException(status_code=code, detail=str(e)) from e
    return row


@router.get("/reports/{incident_id}")
def report(incident_id: str) -> dict:
    ctx = get_context()
    data = incidents_service.export_json(ctx.db, incident_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident: {incident_id}")
    return data


@router.get("/reports/{incident_id}/download")
def download(incident_id: str, format: str = Query("json", pattern=r"^(json|csv|zip)$")):
    ctx = get_context()
    if format == "json":
        data = incidents_service.export_json(ctx.db, incident_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Unknown incident")
        import json

        return Response(
            content=json.dumps(data, indent=2, default=str),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{incident_id}.json"'},
        )
    if format == "zip":
        import tempfile
        from pathlib import Path

        from ...export import IncidentBundleError, export_incident_bundle

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / f"{incident_id}.zip"
            try:
                export_incident_bundle(ctx.db, incident_id, out)
            except IncidentBundleError as e:
                raise HTTPException(status_code=404, detail=str(e)) from e
            payload = out.read_bytes()
        return Response(
            content=payload,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{incident_id}.zip"'},
        )
    csv_text = incidents_service.export_csv(ctx.db, incident_id)
    if csv_text is None:
        raise HTTPException(status_code=404, detail="Unknown incident")
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{incident_id}.csv"'},
    )
