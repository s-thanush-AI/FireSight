from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="firesight",
        description=(
            "FireSight CLI — wildfire smoke detection research prototype. "
            "Demo mode needs no credentials, datasets, weights or GPU."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the FastAPI server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true", help="Auto-reload (dev only)")

    p_init = sub.add_parser("db-init", help="Initialise the SQLite database")
    p_init.add_argument("--json", action="store_true")

    p_inspect = sub.add_parser("inspect", help="Inspect a dataset under the data root")
    p_inspect.add_argument("path", help="Path relative to the data root")
    p_inspect.add_argument("--name", default=None)
    p_inspect.add_argument("--json", action="store_true")

    p_seq = sub.add_parser("sequences", help="List registered sequences")
    p_seq.add_argument("--json", action="store_true")

    p_replay = sub.add_parser("replay", help="Run a demo replay in the terminal")
    p_replay.add_argument("sequence_id", help="e.g. demo-alpha-ridge")
    p_replay.add_argument("--camera", default=None)
    p_replay.add_argument("--frames", type=int, default=50)
    p_replay.add_argument("--json", action="store_true")

    p_inf = sub.add_parser("infer", help="Run detection on one frame of a sequence")
    p_inf.add_argument("sequence_id")
    p_inf.add_argument("--frame", type=int, default=0)
    p_inf.add_argument("--camera", default=None)
    p_inf.add_argument("--json", action="store_true")

    p_geo = sub.add_parser("geometry", help="Triangulate from demo bearings and print report")
    p_geo.add_argument("--json", action="store_true")

    p_eval = sub.add_parser("evaluate", help="Run the demo fixture evaluation")
    p_eval.add_argument("--json", action="store_true")

    p_status = sub.add_parser("status", help="Print runtime status")
    p_status.add_argument("--json", action="store_true")

    p_vid = sub.add_parser(
        "export-video", help="Render an annotated demo sequence to an animated GIF"
    )
    p_vid.add_argument("sequence_id", help="e.g. demo-alpha-ridge")
    p_vid.add_argument("--out", default=None, help="Output .gif path")
    p_vid.add_argument("--every", type=int, default=1, help="Annotate every N-th frame")
    p_vid.add_argument("--max-width", type=int, default=480)

    p_bundle = sub.add_parser(
        "export-incident", help="Export one incident as a portable ZIP bundle"
    )
    p_bundle.add_argument("incident_id")
    p_bundle.add_argument("--out", default=None, help="Output .zip path")

    args = parser.parse_args(argv)
    handlers = {
        "serve": _cmd_serve,
        "db-init": _cmd_db_init,
        "inspect": _cmd_inspect,
        "sequences": _cmd_sequences,
        "replay": _cmd_replay,
        "infer": _cmd_infer,
        "geometry": _cmd_geometry,
        "evaluate": _cmd_evaluate,
        "status": _cmd_status,
        "export-video": _cmd_export_video,
        "export-incident": _cmd_export_incident,
    }
    return handlers[args.command](args)


def _print(data: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, default=str))
    else:
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"{k}: {v}")
        else:
            print(data)


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api.app import create_app

    create_app()
    uvicorn.run(
        "firesight.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def _cmd_db_init(args: argparse.Namespace) -> int:
    from .config import get_settings
    from .db import SCHEMA_VERSION, Database

    s = get_settings()
    db = Database(s.database_path)
    db.initialize()
    tables = [r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    info = {"schema_version": SCHEMA_VERSION, "tables": tables}
    _print({"database_path": str(s.database_path), **info}, args.json)
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    from .config import get_settings
    from .datasets.inspect import inspect_dataset
    from .datasets.paths import PathSafetyError, resolve_under

    s = get_settings()
    try:
        target = resolve_under(s.data_root, args.path)
    except PathSafetyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    report = inspect_dataset(target, name=args.name)
    _print(report.to_dict(), args.json)
    return 0


def _cmd_sequences(args: argparse.Namespace) -> int:
    from .config import get_settings
    from .db import Database

    s = get_settings()
    db = Database(s.database_path)
    db.initialize()
    rows = db.query("SELECT * FROM sequences ORDER BY created_at")
    items = [
        {"id": r["id"], "frames": r["frame_count"], "provenance": r["provenance"]}
        for r in rows
    ]
    if args.json:
        _print({"items": items, "total": len(items)}, True)
    else:
        if not items:
            print("No sequences registered. Demo sequences are created at API startup.")
        for it in items:
            print(f"{it['id']:24} frames={it['frames']:<4} provenance={it['provenance']}")
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    from .config import get_settings
    from .services.context import AppContext

    s = get_settings()
    ctx = AppContext(s)
    ctx.startup()
    try:
        session = ctx.replay_manager.create(args.sequence_id, args.camera, speed=None)
        n = 0
        for _ in range(min(args.frames, len(session.frames))):
            meta = session.step()
            if meta is None:
                break
            n += 1
        result = {
            "replay_id": session.id,
            "frames_stepped": n,
            "detections_total": session.detections_total,
            "alerts_total": session.alerts_total,
            "status": session.status.value,
            "events": list(session.events),
        }
        _print(result, args.json)
        if not args.json:
            for ev in list(session.events)[:20]:
                print(f"  [{ev.get('type')}] {ev.get('message') or ev}")
    finally:
        ctx.replay_manager.cleanup(session.id)
        ctx.shutdown()
    return 0


def _cmd_infer(args: argparse.Namespace) -> int:
    import base64

    import cv2

    from .config import get_settings
    from .models import FrameRef
    from .replay.discovery import discover_frames, load_frame
    from .services.context import AppContext

    s = get_settings()
    ctx = AppContext(s)
    ctx.startup()
    try:
        if not ctx.detector.available:
            print(f"detector unavailable: {ctx.detector.unavailable_reason}", file=sys.stderr)
            return 3
        seq = ctx.db.query_one("SELECT * FROM sequences WHERE id=?", (args.sequence_id,))
        if seq is None:
            print(f"error: unknown sequence {args.sequence_id}", file=sys.stderr)
            return 2
        frames = discover_frames(seq["root_path"])
        if not (0 <= args.frame < len(frames)):
            print(f"error: frame {args.frame} out of range 0..{len(frames)-1}", file=sys.stderr)
            return 2
        ff = frames[args.frame]
        image, _ = load_frame(ff)
        ref = FrameRef(
            sequence_id=seq["id"], index=ff.index, filename=ff.filename,
            timestamp=ff.timestamp.isoformat() if ff.timestamp else None,
            image_width=image.shape[1], image_height=image.shape[0],
        )
        dets = ctx.detector.detect(image, ref, args.camera)
        from .detection.drawing import draw_detections

        annotated = draw_detections(image, dets, metadata_lines=[ff.filename])
        ok, enc = cv2.imencode(".jpg", annotated)
        out = {
            "sequence_id": seq["id"],
            "frame_index": ff.index,
            "filename": ff.filename,
            "detections": [d.model_dump() for d in dets],
            "detector": ctx.detector.metadata(),
            "annotated_jpeg_base64": base64.b64encode(enc.tobytes()).decode() if ok else None,
        }
        if args.json:
            _print(out, True)
        else:
            print(f"detector={out['detector']['name']}:{out['detector']['version']} "
                  f"detections={len(dets)}")
            for d in dets:
                print(f"  bbox={d.bbox} conf={d.confidence:.2f} provenance={d.provenance}")
            if out["annotated_jpeg_base64"]:
                print(f"annotated_jpeg_bytes={len(base64.b64decode(out['annotated_jpeg_base64']))}")
    finally:
        ctx.shutdown()
    return 0


def _cmd_geometry(args: argparse.Namespace) -> int:
    from .config import get_settings
    from .services.context import AppContext

    s = get_settings()
    ctx = AppContext(s)
    ctx.startup()
    try:
        rows = ctx.db.query(
            """SELECT t.* FROM triangulations t ORDER BY t.created_at DESC LIMIT 5"""
        )
        if not rows:
            print("No triangulations yet. Run: firesight replay demo-alpha-ridge")
            return 0
        _print({"triangulations": rows, "total": len(rows)}, args.json)
    finally:
        ctx.shutdown()
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    from .config import get_settings
    from .services import eval_service
    from .services.context import AppContext

    s = get_settings()
    ctx = AppContext(s)
    ctx.startup()
    try:
        result = eval_service.evaluate_demo_fixture(ctx.db, data_root=s.data_root)
        _print(result, args.json)
    finally:
        ctx.shutdown()
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    from . import __version__
    from .config import get_settings
    from .services.context import AppContext

    s = get_settings()
    ctx = AppContext(s)
    ctx.startup()
    try:
        from .services.incidents import counts_by_status

        data = {
            "version": __version__,
            "mode": s.mode,
            "detector": ctx.detector.metadata(),
            "vlm": {"provider": ctx.vlm.name, "configured": s.vlm.enabled},
            "cameras": len(ctx.cameras.list()),
            "incidents_by_status": counts_by_status(ctx.db),
            "sequences": ctx.db.query_one("SELECT COUNT(*) AS n FROM sequences")["n"],
        }
        _print(data, args.json)
    finally:
        ctx.shutdown()
    return 0


def _cmd_export_video(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .config import get_settings
    from .export import DemoVideoError, render_annotated_video
    from .services.context import AppContext

    s = get_settings()
    ctx = AppContext(s)
    ctx.startup()
    try:
        row = ctx.db.query_one("SELECT * FROM sequences WHERE id=?", (args.sequence_id,))
        if row is None:
            print(f"error: unknown sequence '{args.sequence_id}'", file=sys.stderr)
            return 2
        camera_id = None
        try:
            camera_id = json.loads(row.get("manifest_json") or "{}").get("camera_id")
        except (TypeError, ValueError):
            camera_id = None
        out = (
            Path(args.out)
            if args.out
            else Path(s.data_root).parent / "exports" / f"{args.sequence_id}.gif"
        )
        try:
            path = render_annotated_video(
                Path(row["root_path"]),
                out,
                sequence_id=args.sequence_id,
                camera_id=camera_id,
                settings=s,
                max_width=args.max_width,
                every=args.every,
            )
        except DemoVideoError as e:
            print(f"error: {e}", file=sys.stderr)
            return 3
        print(f"wrote {path}")
    finally:
        ctx.shutdown()
    return 0


def _cmd_export_incident(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .config import get_settings
    from .export import IncidentBundleError, export_incident_bundle
    from .services.context import AppContext

    s = get_settings()
    ctx = AppContext(s)
    ctx.startup()
    try:
        out = (
            Path(args.out)
            if args.out
            else Path(s.data_root).parent / "exports" / f"{args.incident_id}.zip"
        )
        try:
            path = export_incident_bundle(ctx.db, args.incident_id, out)
        except IncidentBundleError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"wrote {path}")
    finally:
        ctx.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
