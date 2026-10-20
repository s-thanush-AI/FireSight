from fastapi import APIRouter

from ...services.context import get_context

router = APIRouter(tags=["geometry"])


@router.get("/geometry")
def geometry() -> dict:
    ctx = get_context()
    cams = [c.model_dump() for c in ctx.cameras.list()]
    observations = ctx.db.query(
        """SELECT o.*, i.latitude AS incident_lat, i.longitude AS incident_lon,
                  i.geometry_quality
           FROM observations o
           LEFT JOIN incidents i ON i.id = o.incident_id
           ORDER BY o.created_at DESC LIMIT 200"""
    )
    triangulations = ctx.db.query(
        "SELECT * FROM triangulations ORDER BY created_at DESC LIMIT 100"
    )
    return {
        "cameras": cams,
        "observations": observations,
        "triangulations": triangulations,
        "notice": (
            "Camera markers with provenance 'simulated' are demo fixtures. Rays and "
            "intersections shown for them are computed by the real geometry engine from "
            "simulated bearings."
        ),
        "conventions": {
            "bearing": "degrees clockwise from true north",
            "enu": "local east-north metric frame centred on the mean camera position",
            "proxy_point": ctx.settings.proxy_point,
            "min_separation_deg": ctx.settings.triangulation_min_separation_deg,
            "max_distance_m": ctx.settings.triangulation_max_distance_m,
        },
    }
