import numpy as np
import pytest

from firesight.config import VlmSettings
from firesight.enums import Provenance, VlmAssessment
from firesight.vlm.provider import (
    NullVlmProvider,
    OpenAICompatibleVlm,
    SimulatedVlmProvider,
    VlmProviderError,
    _decision_from_payload,
    _encode_image,
    _parse_structured,
    build_vlm_provider,
)


def img():
    return np.zeros((64, 64, 3), dtype=np.uint8)


class TestStructuredParsing:
    def test_plain_json(self):
        obj = _parse_structured('{"assessment": "uncertain"}')
        assert obj["assessment"] == "uncertain"

    def test_fenced_json(self):
        obj = _parse_structured('```json\n{"assessment": "likely_smoke"}\n```')
        assert obj["assessment"] == "likely_smoke"

    def test_embedded_json(self):
        obj = _parse_structured('Here you go: {"assessment": "likely_non_smoke"} done')
        assert obj["assessment"] == "likely_non_smoke"

    def test_no_json_raises(self):
        with pytest.raises(VlmProviderError):
            _parse_structured("I cannot tell.")

    def test_malformed_json_raises(self):
        with pytest.raises(VlmProviderError):
            _parse_structured('{"assessment": }')

    def test_non_object_raises(self):
        with pytest.raises(VlmProviderError):
            _parse_structured("[1,2,3]")


class TestDecisionValidation:
    def _payload(self, **kw):
        base = {
            "assessment": "likely_smoke",
            "visual_evidence": "grey plume",
            "alternative_explanations": "cloud",
            "limitations": "single view",
            "recommended_next_action": "monitor",
            "model_confidence": 0.7,
        }
        base.update(kw)
        return base

    def test_valid(self):
        d = _decision_from_payload(
            self._payload(), provider="t", model_id="m",
            provenance=Provenance.PREDICTED, duration_ms=5,
        )
        assert d.assessment == VlmAssessment.LIKELY_SMOKE
        assert d.model_confidence == 0.7
        assert d.status == "ok"

    def test_invalid_assessment_raises(self):
        with pytest.raises(VlmProviderError):
            _decision_from_payload(
                self._payload(assessment="definitely_fire"), provider="t", model_id="m",
                provenance=Provenance.PREDICTED, duration_ms=5,
            )

    def test_confidence_out_of_range_dropped(self):
        d = _decision_from_payload(
            self._payload(model_confidence=3.2), provider="t", model_id="m",
            provenance=Provenance.PREDICTED, duration_ms=5,
        )
        assert d.model_confidence is None

    def test_confidence_non_numeric_dropped(self):
        d = _decision_from_payload(
            self._payload(model_confidence="pretty sure"), provider="t", model_id="m",
            provenance=Provenance.PREDICTED, duration_ms=5,
        )
        assert d.model_confidence is None

    def test_error_status_skips_assessment_check(self):
        d = _decision_from_payload(
            {}, provider="t", model_id=None, provenance=Provenance.PREDICTED,
            duration_ms=1, status="error", error="timeout",
        )
        assert d.status == "error" and d.error == "timeout"

    def test_long_strings_bounded(self):
        d = _decision_from_payload(
            self._payload(visual_evidence="x" * 10_000), provider="t", model_id="m",
            provenance=Provenance.PREDICTED, duration_ms=5,
        )
        assert len(d.visual_evidence) <= 2000


class TestProviders:
    def test_encode_image_respects_max_side(self):
        big = np.zeros((1000, 2000, 3), dtype=np.uint8)
        uri = _encode_image(big, 256)
        assert uri and len(uri) < 200_000  # jpeg of a downscaled black frame

    def test_simulated_deterministic(self):
        p = SimulatedVlmProvider()
        d1 = p.verify(img(), context={"mean_confidence": 0.8, "persistence_ratio": 0.9})
        d2 = p.verify(img(), context={"mean_confidence": 0.8, "persistence_ratio": 0.9})
        assert d1.assessment == d2.assessment == VlmAssessment.LIKELY_SMOKE
        assert d1.provenance == Provenance.SIMULATED
        assert "SIMULATED" in (d1.visual_evidence or "")
        assert d1.model_confidence is None  # never invented

    def test_simulated_low_confidence_uncertain(self):
        p = SimulatedVlmProvider()
        d = p.verify(img(), context={"mean_confidence": 0.3, "persistence_ratio": 0.5})
        assert d.assessment == VlmAssessment.UNCERTAIN

    def test_null_provider_disabled(self):
        p = NullVlmProvider()
        d = p.verify(img())
        assert d.status == "disabled"
        assert "VLM_BASE_URL" in (d.error or "")

    def test_build_requires_settings_for_real(self):
        disabled = VlmSettings(base_url=None, api_key=None, model=None)
        assert isinstance(build_vlm_provider(disabled, mode="demo"), SimulatedVlmProvider)
        assert isinstance(build_vlm_provider(disabled, mode="real"), NullVlmProvider)

    def test_openai_provider_requires_full_settings(self):
        with pytest.raises(VlmProviderError):
            OpenAICompatibleVlm(VlmSettings(base_url="https://x", api_key=None, model="m"))

    def test_rate_limit(self):
        settings = VlmSettings(
            base_url="https://example.invalid/v1", api_key="k", model="m",
            requests_per_minute=2,
        )
        p = OpenAICompatibleVlm(settings)
        # two failures from unreachable host are fine; third must be rate-limited
        d1 = p.verify(img())
        d2 = p.verify(img())
        d3 = p.verify(img())
        assert d3.status == "error"
        assert "rate limit" in (d3.error or "").lower()
        assert d1.status == "error"  # unreachable host surfaces as error, not crash
        assert d2.status == "error"
        assert d1.provenance == Provenance.PREDICTED

    def test_timeout_is_graceful(self, monkeypatch):
        import httpx

        settings = VlmSettings(
            base_url="https://example.invalid/v1", api_key="secret-key",
            model="m", max_retries=0, timeout_seconds=1.0,
        )
        p = OpenAICompatibleVlm(settings)

        def boom(*a, **k):
            raise httpx.TimeoutException("timeout")

        monkeypatch.setattr(httpx, "post", boom)
        d = p.verify(img())
        assert d.status == "error"
        assert "timed out" in (d.error or "")
        assert "secret-key" not in str(d.model_dump())

    def test_never_logs_key_in_decision(self):
        settings = VlmSettings(
            base_url="https://example.invalid/v1", api_key="sk-super-secret",
            model="m", max_retries=0,
        )
        p = OpenAICompatibleVlm(settings)
        import httpx

        def resp_500(*a, **k):
            raise httpx.ConnectError("refused")

        monkeypatch_httpx = httpx.post
        try:
            httpx.post = resp_500  # type: ignore[assignment]
            d = p.verify(img())
        finally:
            httpx.post = monkeypatch_httpx  # type: ignore[assignment]
        dump = str(d.model_dump())
        assert "sk-super-secret" not in dump
