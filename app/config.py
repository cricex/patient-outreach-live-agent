"""Configuration for the v2 patient-outreach voice agent.

Env-file layering: .env -> .env.local (last wins).  The load_settings()
factory reads os.getenv() so any env-file, Azure App Service setting,
or shell export is honoured identically.

Voice Live GA 1.1.0 adds server-side noise reduction, echo cancellation,
and configurable Server VAD — all exposed here.  Legacy Speech SDK fields
and manual input-flush tuning are removed; the GA SDK handles both.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

load_dotenv()
load_dotenv(dotenv_path=".env.local", override=True)

logger = logging.getLogger("app.config")


class Settings(BaseModel):
    """Strongly-typed configuration populated from environment variables.

    Use ``load_settings()`` to construct; do not instantiate directly.
    Fields map 1-to-1 with env vars documented in ``ENV.md``.
    """

    # ── Core service / ACS ──────────────────────────────────────────────
    app_base_url: str
    acs_connection_string: str
    acs_outbound_caller_id: str
    target_phone_number: str | None = None

    # ── Voice Live GA ───────────────────────────────────────────────────
    voicelive_endpoint: str | None = None
    voicelive_model: str | None = None
    voicelive_voice: str | None = None
    voicelive_system_prompt: str | None = None
    voicelive_api_version: str = "2025-10-01"
    voicelive_api_key: str | None = None
    default_system_prompt: str = "You are a helpful voice agent. Keep responses concise."
    voicelive_language_hint: str | None = None
    voicelive_wait_for_caller: bool = True

    # Voice Live GA 1.1.0 audio-processing features
    voicelive_noise_reduction: bool = True
    voicelive_echo_cancellation: bool = True

    # Server VAD tuning — the SDK's ServerVad replaces manual flush gating
    voicelive_vad_threshold: float = 0.5
    voicelive_vad_prefix_padding_ms: int = 300
    voicelive_vad_silence_duration_ms: int = 500

    # ── Foundry inference (prompt generation via chat completions) ─────
    foundry_inference_endpoint: str | None = None
    foundry_inference_model: str = "gpt-4o"
    foundry_inference_api_key: str | None = None

    # ── Call lifecycle ──────────────────────────────────────────────────
    call_timeout_sec: int = 90
    call_idle_timeout_sec: int = 90

    # ── Media bridge ────────────────────────────────────────────────────
    media_bidirectional: bool = True
    media_start_at_create: bool = True
    media_audio_channel_type: str = "mixed"
    media_frame_bytes: int = 640
    media_frame_interval_ms: int = 20
    media_enable_voicelive_in: bool = True
    media_enable_voicelive_out: bool = True

    # ── Application ─────────────────────────────────────────────────────
    log_level: str = "INFO"
    websites_port: int = 8000

    # ── Validators ──────────────────────────────────────────────────────

    @field_validator("app_base_url", "acs_connection_string", "acs_outbound_caller_id")
    @classmethod
    def _required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Required configuration value missing")
        return value

    def validate_voicelive(self) -> None:
        """Check Voice Live fields for consistency after construction.

        Raises:
            ValueError: If required Voice Live fields are missing or
                VAD / media values are out of range.
        """
        missing: list[str] = []
        if not self.voicelive_endpoint:
            missing.append("AZURE_VOICELIVE_ENDPOINT")
        if not self.voicelive_model:
            missing.append("VOICELIVE_MODEL")
        if not self.voicelive_voice:
            missing.append("VOICELIVE_VOICE")
        if missing:
            raise ValueError("Voice Live GA config missing: " + ", ".join(missing))

        if self.media_audio_channel_type not in {"mixed", "unmixed"}:
            raise ValueError("MEDIA_AUDIO_CHANNEL_TYPE must be 'mixed' or 'unmixed'")

        # VAD threshold is a probability; must be in [0.0, 1.0]
        if not 0.0 <= self.voicelive_vad_threshold <= 1.0:
            raise ValueError("VOICELIVE_VAD_THRESHOLD must be between 0.0 and 1.0")
        if self.voicelive_vad_prefix_padding_ms <= 0:
            raise ValueError("VOICELIVE_VAD_PREFIX_PADDING_MS must be > 0")
        if self.voicelive_vad_silence_duration_ms <= 0:
            raise ValueError("VOICELIVE_VAD_SILENCE_DURATION_MS must be > 0")


def _env_bool(name: str, default: str = "false") -> bool:
    """Read an env var as a boolean (case-insensitive 'true')."""
    return os.getenv(name, default).lower() == "true"


def load_settings() -> Settings:
    """Build a ``Settings`` instance from the current environment.

    ACS_CONNECTION_STRING gets extra quote-stripping because Azure portal
    sometimes wraps the value in quotes when copied.
    """
    raw_conn = os.getenv("ACS_CONNECTION_STRING", "")
    if raw_conn.startswith(("'", '"')) and raw_conn.endswith(("'", '"')):
        raw_conn = raw_conn[1:-1]

    s = Settings(
        # Core / ACS
        app_base_url=os.getenv("APP_BASE_URL", "http://localhost:8000"),
        acs_connection_string=raw_conn.strip(),
        acs_outbound_caller_id=os.getenv("ACS_OUTBOUND_CALLER_ID", ""),
        target_phone_number=os.getenv("TARGET_PHONE_NUMBER"),
        # Voice Live GA
        voicelive_endpoint=os.getenv("AZURE_VOICELIVE_ENDPOINT"),
        voicelive_model=os.getenv("VOICELIVE_MODEL"),
        voicelive_voice=os.getenv("VOICELIVE_VOICE"),
        voicelive_system_prompt=os.getenv("VOICELIVE_SYSTEM_PROMPT"),
        voicelive_api_version=os.getenv("AZURE_VOICELIVE_API_VERSION", "2025-10-01"),
        voicelive_api_key=os.getenv("AZURE_VOICELIVE_API_KEY"),
        default_system_prompt=os.getenv(
            "DEFAULT_SYSTEM_PROMPT",
            "You are a helpful voice agent. Keep responses concise.",
        ),
        voicelive_language_hint=os.getenv("VOICELIVE_LANGUAGE_HINT"),
        voicelive_wait_for_caller=_env_bool("VOICELIVE_WAIT_FOR_CALLER", "true"),
        # GA 1.1.0 audio processing
        voicelive_noise_reduction=_env_bool("VOICELIVE_NOISE_REDUCTION", "true"),
        voicelive_echo_cancellation=_env_bool("VOICELIVE_ECHO_CANCELLATION", "true"),
        # Server VAD
        voicelive_vad_threshold=float(os.getenv("VOICELIVE_VAD_THRESHOLD", "0.5")),
        voicelive_vad_prefix_padding_ms=int(os.getenv("VOICELIVE_VAD_PREFIX_PADDING_MS", "300")),
        voicelive_vad_silence_duration_ms=int(os.getenv("VOICELIVE_VAD_SILENCE_DURATION_MS", "500")),
        # Foundry inference
        foundry_inference_endpoint=os.getenv("FOUNDRY_INFERENCE_ENDPOINT"),
        foundry_inference_model=os.getenv("FOUNDRY_INFERENCE_MODEL", "gpt-4o"),
        foundry_inference_api_key=os.getenv("FOUNDRY_INFERENCE_API_KEY"),
        # Call lifecycle
        call_timeout_sec=int(os.getenv("CALL_TIMEOUT_SEC", "90")),
        call_idle_timeout_sec=int(
            os.getenv("CALL_IDLE_TIMEOUT_SEC", os.getenv("CALL_TIMEOUT_SEC", "90"))
        ),
        # Media bridge
        media_bidirectional=_env_bool("MEDIA_BIDIRECTIONAL", "true"),
        media_start_at_create=_env_bool("MEDIA_START_AT_CREATE", "true"),
        media_audio_channel_type=os.getenv("MEDIA_AUDIO_CHANNEL_TYPE", "mixed").lower(),
        media_frame_bytes=int(os.getenv("MEDIA_FRAME_BYTES", "640")),
        media_frame_interval_ms=int(os.getenv("MEDIA_FRAME_INTERVAL_MS", "20")),
        media_enable_voicelive_in=_env_bool("MEDIA_ENABLE_VL_IN", "true"),
        media_enable_voicelive_out=_env_bool("MEDIA_ENABLE_VL_OUT", "true"),
        # Application
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        websites_port=int(os.getenv("WEBSITES_PORT", "8000")),
    )
    s.validate_voicelive()
    logger.info("settings loaded  vl_endpoint=%s  model=%s", s.voicelive_endpoint, s.voicelive_model)
    return s


settings = load_settings()

