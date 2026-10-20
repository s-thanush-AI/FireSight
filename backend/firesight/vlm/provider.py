"""Optional vision-language model verification.

Providers:
  * OpenAICompatibleVlm — real HTTP calls to a user-configured
    OpenAI-compatible chat-completions endpoint. Disabled unless base URL,
    API key and model id are all present in the environment.
  * SimulatedVlmProvider — deterministic, clearly-labeled simulated opinion
    for demo mode. Never presented as external verification.
  * NullVlmProvider — explicit "disabled" state.

A VLM opinion is never ground truth and never the sole basis for an incident.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime

import cv2
import numpy as np

from ..config import VlmSettings
from ..db import utcnow_iso
from ..enums import Provenance, VlmAssessment
from ..models import VlmDecision

log = logging.getLogger(__name__)

_PROMPT = """You are assisting a wildfire smoke monitoring review system.
Assess whether the main hazy/cloudy region in this camera frame is most
consistent with WILDFIRE SMOKE, something else (cloud, fog, haze, dust,
steam, lens artefact), or you are UNCERTAIN.

Answer ONLY with a JSON object with these exact keys:
{
  "assessment": "likely_smoke" | "likely_non_smoke" | "uncertain",
  "visual_evidence": "<short description of what you actually see>",
  "alternative_explanations": "<plausible non-smoke explanations>",
  "limitations": "<what you cannot determine from this image>",
  "recommended_next_action": "<e.g. monitor, request another camera angle, dismiss>",
  "model_confidence": <number 0-1 ONLY if your API provides a meaningful score, else null>
}
Be conservative: "uncertain" is a valid and often correct answer. A single
image cannot confirm a wildfire."""


class VlmProviderError(RuntimeError):
    pass


class BaseVlmProvider(ABC):
    name: str = "base"
    provenance: Provenance = Provenance.PREDICTED

    @abstractmethod
    def verify(
        self,
        image: np.ndarray,
        *,
        incident_id: str | None = None,
        context: dict | None = None,
    ) -> VlmDecision: ...

    def metadata(self) -> dict:
        return {"name": self.name, "provenance": self.provenance.value}


def _encode_image(image: np.ndarray, max_side: int) -> str:
    h, w = image.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, enc = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        raise VlmProviderError("Failed to encode image for VLM request")
    return base64.b64encode(enc.tobytes()).decode("ascii")


def _parse_structured(text: str) -> dict:
    text = text.strip()
    # tolerate markdown fences
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise VlmProviderError("No JSON object found in VLM response")
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise VlmProviderError(f"Malformed JSON in VLM response: {e}") from e
    if not isinstance(obj, dict):
        raise VlmProviderError("VLM response JSON is not an object")
    return obj


def _decision_from_payload(
    obj: dict, *, provider: str, model_id: str | None, provenance: Provenance,
    duration_ms: int, status: str = "ok", error: str | None = None,
) -> VlmDecision:
    assessment = None
    raw_a = str(obj.get("assessment", "")).lower().strip()
    for a in VlmAssessment:
        if raw_a == a.value:
            assessment = a
            break
    if assessment is None and status == "ok":
        raise VlmProviderError(f"Invalid assessment value: {obj.get('assessment')!r}")
    conf = obj.get("model_confidence")
    if conf is not None:
        try:
            conf = float(conf)
            if not (0.0 <= conf <= 1.0):
                conf = None
        except (TypeError, ValueError):
            conf = None

    def _bounded(key: str, limit: int = 2000) -> str | None:
        v = obj.get(key)
        if v is None:
            return None
        return str(v)[:limit]

    return VlmDecision(
        provider=provider,
        model_id=model_id,
        status=status,
        assessment=assessment,
        visual_evidence=_bounded("visual_evidence"),
        alternative_explanations=_bounded("alternative_explanations"),
        limitations=_bounded("limitations"),
        recommended_next_action=_bounded("recommended_next_action"),
        model_confidence=conf,
        error=error,
        duration_ms=duration_ms,
        request_time=datetime.now(UTC).isoformat(),
        provenance=provenance,
    )


class SimulatedVlmProvider(BaseVlmProvider):
    """Deterministic simulated VLM opinion for demo mode.

    Uses only the numeric context (mean detection confidence, persistence) —
    it does not pretend to interpret pixels. Labeled 'simulated' everywhere.
    """

    name = "simulated-vlm"
    provenance = Provenance.SIMULATED

    def verify(
        self,
        image: np.ndarray,
        *,
        incident_id: str | None = None,
        context: dict | None = None,
    ) -> VlmDecision:
        ctx = context or {}
        mean_conf = float(ctx.get("mean_confidence", 0.0))
        persistence = float(ctx.get("persistence_ratio", 0.0))
        if mean_conf >= 0.55 and persistence >= 0.75:
            assessment = VlmAssessment.LIKELY_SMOKE
            action = "monitor and seek a second camera angle"
        elif mean_conf < 0.4:
            assessment = VlmAssessment.UNCERTAIN
            action = "request additional frames or another camera"
        else:
            assessment = VlmAssessment.UNCERTAIN
            action = "keep under review"
        return VlmDecision(
            provider=self.name,
            model_id="simulated-heuristic-v0",
            status="ok",
            assessment=assessment,
            visual_evidence=(
                "SIMULATED decision derived from detection statistics only; "
                "the image is synthetic demo imagery."
            ),
            alternative_explanations="cloud, haze, or dust (simulated assessment)",
            limitations=(
                "This is a deterministic simulation of a VLM response for demo "
                "purposes. It is not an external model's opinion and must never "
                "be treated as verification."
            ),
            recommended_next_action=action,
            model_confidence=None,
            request_time=utcnow_iso(),
            provenance=Provenance.SIMULATED,
        )


class NullVlmProvider(BaseVlmProvider):
    name = "disabled-vlm"
    provenance = Provenance.HEURISTIC

    def verify(
        self,
        image: np.ndarray,
        *,
        incident_id: str | None = None,
        context: dict | None = None,
    ) -> VlmDecision:
        return VlmDecision(
            provider=self.name,
            model_id=None,
            status="disabled",
            error=(
                "VLM verification is disabled: set VLM_BASE_URL, VLM_API_KEY and "
                "VLM_MODEL in the environment to enable real verification."
            ),
            request_time=utcnow_iso(),
            provenance=Provenance.HEURISTIC,
        )


class OpenAICompatibleVlm(BaseVlmProvider):
    """OpenAI-compatible chat-completions adapter with bounded retries."""

    name = "openai-compatible-vlm"
    provenance = Provenance.PREDICTED

    def __init__(self, settings: VlmSettings):
        if not settings.enabled:
            raise VlmProviderError("VLM settings incomplete")
        self.settings = settings
        self._window_start = time.monotonic()
        self._window_count = 0

    def _rate_limit(self) -> None:
        now = time.monotonic()
        if now - self._window_start >= 60.0:
            self._window_start = now
            self._window_count = 0
        if self._window_count >= self.settings.requests_per_minute:
            raise VlmProviderError("VLM rate limit reached; try again in a minute")
        self._window_count += 1

    def verify(
        self,
        image: np.ndarray,
        *,
        incident_id: str | None = None,
        context: dict | None = None,
    ) -> VlmDecision:
        import httpx

        started = time.monotonic()
        try:
            self._rate_limit()
        except VlmProviderError as e:
            return _decision_from_payload(
                {}, provider=self.name, model_id=self.settings.model,
                provenance=self.provenance, duration_ms=0, status="error", error=str(e),
            )

        data_uri = f"data:image/jpeg;base64,{_encode_image(image, self.settings.max_image_side)}"
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": _PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": data_uri},
                        },
                        {"type": "text", "text": f"Context: {json.dumps(context or {})[:500]}"},
                    ],
                },
            ],
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        url = self.settings.base_url.rstrip("/") + "/chat/completions"
        last_error: str | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                resp = httpx.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.settings.timeout_seconds,
                )
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = f"HTTP {resp.status_code}"
                    time.sleep(min(2.0**attempt, 8.0))
                    continue
                resp.raise_for_status()
                body = resp.json()
                content = body["choices"][0]["message"]["content"]
                obj = _parse_structured(content)
                return _decision_from_payload(
                    obj,
                    provider=self.name,
                    model_id=str(body.get("model") or self.settings.model),
                    provenance=self.provenance,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            except httpx.TimeoutException:
                last_error = "request timed out"
                time.sleep(min(2.0**attempt, 8.0))
            except httpx.HTTPError as e:
                last_error = f"HTTP error: {type(e).__name__}"
                break
            except (KeyError, IndexError, TypeError) as e:
                last_error = f"unexpected response shape: {type(e).__name__}"
                break
            except VlmProviderError as e:
                last_error = str(e)
                break
        return _decision_from_payload(
            {},
            provider=self.name,
            model_id=self.settings.model,
            provenance=self.provenance,
            duration_ms=int((time.monotonic() - started) * 1000),
            status="error",
            error=last_error or "unknown VLM error",
        )


def build_vlm_provider(settings: VlmSettings, *, mode: str) -> BaseVlmProvider:
    if settings.enabled:
        return OpenAICompatibleVlm(settings)
    if mode == "demo":
        return SimulatedVlmProvider()
    return NullVlmProvider()
