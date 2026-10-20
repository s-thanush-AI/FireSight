from pathlib import Path

from fastapi import APIRouter, HTTPException

from ...datasets.inspect import inspect_dataset
from ...datasets.paths import PathSafetyError, resolve_under
from ...services.context import get_context

router = APIRouter(tags=["datasets"])


@router.get("/datasets")
def list_datasets() -> dict:
    ctx = get_context()
    sequences = ctx.db.query("SELECT * FROM sequences ORDER BY created_at")
    items = []
    for row in sequences:
        import json

        meta = {}
        try:
            meta = json.loads(row["manifest_json"] or "{}")
        except json.JSONDecodeError:
            pass
        items.append(
            {
                "id": row["id"],
                "name": row["name"],
                "dataset": row["dataset"],
                "dataset_provenance": row["dataset_provenance"],
                "frame_count": row["frame_count"],
                "image_width": row["image_width"],
                "image_height": row["image_height"],
                "start_ts": row["start_ts"],
                "end_ts": row["end_ts"],
                "provenance": row["provenance"],
                "camera_id": meta.get("camera_id"),
                "synthetic": meta.get("synthetic", False),
            }
        )
    data_root = ctx.settings.data_root
    local_dirs = []
    if Path(data_root).exists():
        for p in sorted(Path(data_root).iterdir()):
            if p.is_dir() and p.name != "demo":
                local_dirs.append({"name": p.name, "path": str(p)})
    return {
        "registered": items,
        "data_root": str(data_root),
        "data_root_exists": Path(data_root).exists(),
        "local_dirs_not_registered": local_dirs,
        "docs": {
            "figlib": "https://www.hpwren.ucsd.edu/FIgLib/",
            "pyro_sdis": "https://huggingface.co/datasets/pyronear/pyro-sdis",
        },
    }


@router.post("/datasets/inspect")
def inspect(body: dict) -> dict:
    ctx = get_context()
    path = body.get("path")
    if not path or not isinstance(path, str):
        raise HTTPException(status_code=422, detail="'path' (string, relative to data root) required")
    try:
        target = resolve_under(ctx.settings.data_root, path)
    except PathSafetyError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    report = inspect_dataset(target, name=body.get("name"))
    return report.to_dict()
