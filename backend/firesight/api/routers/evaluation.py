from fastapi import APIRouter, HTTPException

from ...api.schemas import EvalRunCreateRequest
from ...services import eval_service
from ...services.context import get_context

router = APIRouter(tags=["evaluation"])


@router.get("/evaluation/metrics")
def metrics(run_id: str | None = None) -> dict:
    ctx = get_context()
    if run_id:
        run = eval_service.get_run(ctx.db, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")
        return {"run": run}
    runs = eval_service.list_runs(ctx.db)
    latest = runs[0] if runs else None
    return {
        "latest": latest,
        "runs_count": len(runs),
        "definitions": {
            "detection_precision": "TP / (TP + FP) at the configured IoU match threshold.",
            "detection_recall": "TP / (TP + FN); requires ground-truth annotations.",
            "detection_f1": "harmonic mean of precision and recall.",
            "detection_latency_s": "event onset -> first model alert; needs known onset and frame timing.",
            "false_alerts_per_camera_hour": "false alerts / labelled negative camera-hours.",
            "geolocation_error_m": "estimated vs ground-truth coordinate; needs both.",
        },
        "honesty_notice": (
            "Metrics computed on synthetic demo fixtures validate pipeline mechanics only. "
            "Unavailable metrics are returned with value=null and a reason — never invented."
        ),
    }


@router.post("/evaluation/runs")
def create_run(body: EvalRunCreateRequest) -> dict:
    ctx = get_context()
    if body.kind == "demo_fixture":
        result = eval_service.evaluate_demo_fixture(ctx.db, data_root=ctx.settings.data_root)
        return {**result, "kind": body.kind, "provenance": "simulated"}
    raise HTTPException(status_code=422, detail=f"Unknown evaluation kind: {body.kind}")


@router.get("/evaluation/runs")
def list_runs() -> dict:
    ctx = get_context()
    runs = eval_service.list_runs(ctx.db)
    return {"items": runs, "total": len(runs)}


@router.get("/evaluation/runs/{run_id}")
def get_run(run_id: str) -> dict:
    ctx = get_context()
    run = eval_service.get_run(ctx.db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")
    return run
