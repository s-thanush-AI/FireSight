from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "FireSight"

Mode = Literal["demo", "real"]
Device = Literal["auto", "cpu", "mps", "cuda"]


class TemporalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FIRESIGHT_TEMPORAL_", extra="ignore")

    window_seconds: float = Field(8.0, ge=0.5, le=120.0)
    min_positive_observations: int = Field(3, ge=1, le=100)
    min_confidence: float = Field(0.30, ge=0.0, le=1.0)
    min_persistence_ratio: float = Field(0.5, ge=0.0, le=1.0)
    max_gap_seconds: float = Field(2.5, ge=0.0, le=60.0)
    grace_seconds: float = Field(10.0, ge=0.0, le=300.0)
    match_iou_min: float = Field(0.1, ge=0.0, le=1.0)
    match_center_max_norm: float = Field(0.35, ge=0.01, le=1.0)


class DetectorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FIRESIGHT_DETECTOR_", extra="ignore")

    kind: Literal["simulated", "yolo"] = "simulated"
    confidence_threshold: float = Field(0.25, ge=0.0, le=1.0)
    iou_threshold: float = Field(0.45, ge=0.0, le=1.0)
    image_size: int = Field(640, ge=64, le=4096)
    class_name: str = "smoke"


class VlmSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VLM_", extra="ignore")

    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout_seconds: float = Field(30.0, ge=1.0, le=300.0)
    max_retries: int = Field(2, ge=0, le=5)
    max_image_side: int = Field(768, ge=128, le=2048)
    requests_per_minute: int = Field(6, ge=1, le=120)

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FIRESIGHT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = APP_NAME
    mode: Mode = "demo"
    database_url: str = "sqlite:///./firesight.db"
    data_root: Path = Path("./data")
    models_root: Path = Path("./models")
    model_path: Path | None = None
    device: Device = "auto"

    api_host: str = "127.0.0.1"
    api_port: int = Field(8000, ge=1, le=65535)
    frontend_port: int = Field(5173, ge=1, le=65535)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    replay_speed_default: float = Field(2.0, ge=0.1, le=60.0)
    replay_max_stored_frames: int = Field(250, ge=1, le=10000)
    replay_frame_bytes_max: int = Field(4_000_000, ge=10_000, le=50_000_000)
    replay_ui_max_side: int = Field(1280, ge=320, le=4096)
    replay_ui_quality: int = Field(78, ge=30, le=95)
    max_replays: int = Field(8, ge=1, le=64)

    alert_cooldown_s: float = Field(120.0, ge=0.0, le=86_400.0)
    alert_min_consecutive: int = Field(3, ge=1, le=100)
    alert_evidence_max_side: int = Field(1280, ge=320, le=4096)
    live_max_sources: int = Field(8, ge=1, le=64)
    live_sample_fps: float = Field(1.0, ge=0.1, le=10.0)
    live_stall_seconds: float = Field(10.0, ge=2.0, le=300.0)

    proxy_point: Literal["bottom_center", "center"] = "bottom_center"
    triangulation_min_separation_deg: float = Field(4.0, ge=0.1, le=90.0)
    triangulation_max_distance_m: float = Field(60_000.0, ge=100.0, le=1_000_000.0)
    association_timestamp_tolerance_s: float = Field(2.0, ge=0.0, le=60.0)
    association_max_residual_m: float = Field(2_500.0, ge=10.0, le=100_000.0)

    bearing_pixel_sigma_frac: float = Field(
        0.01, ge=0.0005, le=0.2,
        description="Assumed horizontal detector localisation noise as a fraction of image width.",
    )
    bearing_heading_sigma_deg: float = Field(1.5, ge=0.05, le=45.0)

    detector: DetectorSettings = Field(default_factory=DetectorSettings)
    temporal: TemporalSettings = Field(default_factory=TemporalSettings)
    vlm: VlmSettings = Field(default_factory=lambda: VlmSettings(_env_file=".env"))

    @field_validator("mode")
    @classmethod
    def _mode_known(cls, v: str) -> str:
        if v not in ("demo", "real"):
            raise ValueError("mode must be 'demo' or 'real'")
        return v

    @field_validator("data_root", "models_root", mode="before")
    @classmethod
    def _expand(cls, v: object) -> object:
        if isinstance(v, str):
            return Path(v).expanduser()
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def database_path(self) -> Path:
        url = self.database_url
        if url.startswith("sqlite:///"):
            raw = url[len("sqlite:///") :]
            if raw in (":memory:", ""):
                return Path(":memory:")
            return Path(raw).expanduser().resolve()
        raise ValueError(f"Unsupported database_url: {url!r} (only sqlite:/// is supported)")

    def model_weights_path(self) -> Path | None:
        if self.model_path is None:
            return None
        return Path(self.model_path).expanduser().resolve()

    def redacted_dict(self) -> dict[str, object]:
        """Settings for API exposure. Never contains secrets."""
        return {
            "app_name": self.app_name,
            "mode": self.mode,
            "database_url": self.database_url,
            "data_root": str(self.data_root),
            "models_root": str(self.models_root),
            "model_path": str(self.model_path) if self.model_path else None,
            "device": self.device,
            "api_host": self.api_host,
            "api_port": self.api_port,
            "frontend_port": self.frontend_port,
            "cors_origins": self.cors_origin_list,
            "replay_speed_default": self.replay_speed_default,
            "replay_max_stored_frames": self.replay_max_stored_frames,
            "replay_ui_max_side": self.replay_ui_max_side,
            "max_replays": self.max_replays,
            "alert_cooldown_s": self.alert_cooldown_s,
            "live_max_sources": self.live_max_sources,
            "proxy_point": self.proxy_point,
            "triangulation_min_separation_deg": self.triangulation_min_separation_deg,
            "triangulation_max_distance_m": self.triangulation_max_distance_m,
            "association_timestamp_tolerance_s": self.association_timestamp_tolerance_s,
            "association_max_residual_m": self.association_max_residual_m,
            "bearing_pixel_sigma_frac": self.bearing_pixel_sigma_frac,
            "bearing_heading_sigma_deg": self.bearing_heading_sigma_deg,
            "detector": self.detector.model_dump(),
            "temporal": self.temporal.model_dump(),
            "vlm": {
                "configured": self.vlm.enabled,
                "base_url": self.vlm.base_url or None,
                "model": self.vlm.model or None,
                "timeout_seconds": self.vlm.timeout_seconds,
                "max_retries": self.vlm.max_retries,
                "max_image_side": self.vlm.max_image_side,
                "requests_per_minute": self.vlm.requests_per_minute,
                "api_key_present": bool(self.vlm.api_key),
            },
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
