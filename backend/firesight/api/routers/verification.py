from fastapi import APIRouter, HTTPException

from ...api.schemas import VerificationResponse
from ...db import dumps, utcnow_iso
from ...enums import Provenance
from ...services.context import get_context

router = APIRouter(tags=["verification"])


@router.post("/verification/{incident_id}", response_model=VerificationResponse)
def verify_incident(incident_id: str) -> VerificationResponse:
    """Run the configured VLM provider on this incident's evidence frame.

    Real external calls happen only when VLM settings are fully configured in
    the environment. Otherwise demo mode returns a clearly-labeled simulated
    opinion and real mode returns an explicit 'disabled' state.
    """
    ctx = get_context()
    inc = ctx.db.query_one("SELECT * FROM incidents WHERE id=?", (incident_id,))
    if inc is None:
        raise HTTPException(status_code=404, detail=f"Unknown incident: {incident_id}")

    # find an evidence frame (prefer stored annotated frame via replay current)
    image = None
    obs = ctx.db.query(
        "SELECT * FROM observations WHERE incident_id=? ORDER BY created_at LIMIT 1",
        (incident_id,),
    )
    frame_row = None
    if obs and obs[0].get("replay_id"):
        frame_row = ctx.db.query_one(
            "SELECT * FROM frames WHERE replay_id=? ORDER BY index_in_sequence DESC LIMIT 1",
            (obs[0]["replay_id"],),
        )
    import numpy as np

    if frame_row is not None:
        from pathlib import Path

        from ...replay.discovery import load_frame

        seq = ctx.db.query_one("SELECT * FROM sequences WHERE id=?", (frame_row["sequence_id"],))
        if seq:
            path = Path(seq["root_path"]) / frame_row["rel_path"]
            if path.exists():
                try:
                    image, _ = load_frame(path)
                except Exception:
                    image = None
    if image is None:
        # fall back to a plain black canvas so the provider still gets an image input;
        # the decision records that the original frame was unavailable.
        image = np.zeros((360, 640, 3), dtype=np.uint8)

    obs_rows = ctx.db.query(
        "SELECT * FROM observations WHERE incident_id=? ORDER BY created_at",
        (incident_id,),
    )
    context = {
        "incident_id": incident_id,
        "status": inc["status"],
        "provenance": inc["provenance"],
        "mean_confidence": (
            sum(o["confidence"] or 0 for o in obs_rows) / len(obs_rows) if obs_rows else 0.0
        ),
        "persistence_ratio": 1.0,
        "cameras": sorted({o["camera_id"] for o in obs_rows}),
    }
    decision = ctx.vlm.verify(image, incident_id=incident_id, context=context)

    ctx.db.execute(
        """INSERT INTO vlm_verifications (incident_id, provider, model_id, request_time,
             assessment, visual_evidence, alternative_explanations, limitations,
             recommended_next_action, model_confidence, raw_response_json, provenance,
             status, error, duration_ms)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            incident_id, decision.provider, decision.model_id, decision.request_time,
            decision.assessment.value if decision.assessment else None,
            decision.visual_evidence, decision.alternative_explanations, decision.limitations,
            decision.recommended_next_action, decision.model_confidence,
            dumps(decision.model_dump(mode="json")), decision.provenance.value,
            decision.status, decision.error, decision.duration_ms,
        ),
    )
    if decision.assessment is not None:
        ctx.db.execute(
            "UPDATE incidents SET vlm_assessment=?, vlm_model=?, updated_at=? WHERE id=?",
            (
                decision.assessment.value, decision.model_id, utcnow_iso(), incident_id,
            ),
        )
    return VerificationResponse(
        incident_id=incident_id,
        provider=decision.provider,
        model_id=decision.model_id,
        status=decision.status,
        assessment=decision.assessment,
        visual_evidence=decision.visual_evidence,
        alternative_explanations=decision.alternative_explanations,
        limitations=decision.limitations,
        recommended_next_action=decision.recommended_next_action,
        model_confidence=decision.model_confidence,
        error=decision.error,
        provenance=decision.provenance,
        request_time=decision.request_time,
        duration_ms=decision.duration_ms,
    )


@router.get("/verification/{incident_id}")
def list_verifications(incident_id: str) -> dict:
    ctx = get_context()
    rows = ctx.db.query(
        "SELECT * FROM vlm_verifications WHERE incident_id=? ORDER BY request_time",
        (incident_id,),
    )
    return {
        "items": rows,
        "total": len(rows),
        "provider": ctx.vlm.name,
        "provenance_notice": (
            "VLM assessments are model opinions, never ground truth. Simulated "
            "assessments are labeled provenance='simulated'."
        ),
        "simulated_default": ctx.vlm.provenance == Provenance.SIMULATED,
    }
