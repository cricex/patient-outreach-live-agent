"""Configuration for /app aligned to Azure Voice Live GA.

Voice Live GA env variables:
    AZURE_VOICELIVE_ENDPOINT      -> voicelive_endpoint (required)
    VOICELIVE_MODEL               -> voicelive_model   (required)
    VOICELIVE_VOICE               -> voicelive_voice   (required)
    AZURE_VOICELIVE_API_VERSION   -> voicelive_api_version (optional, default here)
    AZURE_VOICELIVE_API_KEY       -> voicelive_api_key (optional if using Entra ID)

Application base URL:
    APP_BASE_URL (required for real ACS calls, MUST be https). All callback and media
    URLs now derive exclusively from APP_BASE_URL (dynamic WEBSITE_HOSTNAME fallback removed).

Legacy speech fields (SPEECH_KEY / SPEECH_REGION) remain optional but GA Voice Live
uses the dedicated endpoint + key or Entra token.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator


load_dotenv()
load_dotenv(dotenv_path=".env.local", override=True)


class Settings(BaseModel):
    """Strongly typed configuration for the FastAPI voice call service."""

    # Core service / ACS
    app_base_url: str
    acs_connection_string: str
    acs_outbound_caller_id: str
    target_phone_number: str | None = None

    # Voice Live GA (endpoint + model + voice + instructions)
    voicelive_endpoint: str | None = None
    voicelive_model: str | None = None
    voicelive_voice: str | None = None
    voicelive_system_prompt: str | None = None
    voicelive_api_version: str = "2025-10-01"
    voicelive_api_key: str | None = None
    default_system_prompt: str = "You are a helpful voice agent. Keep responses concise."
    voicelive_start_immediate: bool = False
    voicelive_language_hint: str | None = None
    voicelive_wait_for_caller: bool = True

    # Legacy / optional speech key-region (fallback)
    speech_key: str | None = None
    speech_region: str | None = None

    # Call lifecycle
    call_timeout_sec: int = 90
    call_idle_timeout_sec: int = 90

    # Media bridge basics
    media_bidirectional: bool = True
    media_start_at_create: bool = True
    media_audio_channel_type: str = "mixed"
    media_frame_bytes: int = 640
    media_frame_interval_ms: int = 20
    media_out_format: str = "json_simple"
    media_enable_voicelive_in: bool = True
    media_enable_voicelive_out: bool = True
    voicelive_upsample_16k_to_24k: bool = True
    voicelive_input_flush_target_frames: int = 4
    voicelive_input_flush_interval_ms: int = 60
    voicelive_input_flush_max_interval_ms: int = 180
    debug_voicelive_input_flush: bool = False

    @field_validator("app_base_url", "acs_connection_string", "acs_outbound_caller_id")
    @classmethod
    def _required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Required configuration value missing")
        return value

    def validate_voicelive(self) -> None:
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
        if self.media_out_format not in {"json_simple", "binary"}:
            raise ValueError("MEDIA_OUT_FORMAT must be 'json_simple' or 'binary'")
        if self.voicelive_input_flush_target_frames <= 0:
            raise ValueError("VOICELIVE_INPUT_FLUSH_FRAMES must be > 0")
        if self.voicelive_input_flush_interval_ms <= 0:
            raise ValueError("VOICELIVE_INPUT_FLUSH_INTERVAL_MS must be > 0")
        if self.voicelive_input_flush_max_interval_ms < self.voicelive_input_flush_interval_ms:
            raise ValueError("VOICELIVE_INPUT_FLUSH_MAX_INTERVAL_MS must be >= interval")

def load_settings() -> Settings:
    raw_conn = os.getenv("ACS_CONNECTION_STRING", "")
    if raw_conn.startswith(("'", '"')) and raw_conn.endswith(("'", '"')):
        raw_conn_clean = raw_conn[1:-1]
    else:
        raw_conn_clean = raw_conn

    settings = Settings(
        app_base_url=os.getenv("APP_BASE_URL", "http://localhost:8000"),
        acs_connection_string=raw_conn_clean.strip(),
        acs_outbound_caller_id=os.getenv("ACS_OUTBOUND_CALLER_ID", ""),
        target_phone_number=os.getenv("TARGET_PHONE_NUMBER"),
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
        voicelive_start_immediate=os.getenv("VOICELIVE_START_IMMEDIATE", "false").lower() == "true",
        voicelive_language_hint=os.getenv("VOICELIVE_LANGUAGE_HINT"),
        voicelive_wait_for_caller=os.getenv("VOICELIVE_WAIT_FOR_CALLER", "true").lower() == "true",
        speech_key=os.getenv("SPEECH_KEY"),
        speech_region=os.getenv("SPEECH_REGION"),
        call_timeout_sec=int(os.getenv("CALL_TIMEOUT_SEC", "90")),
        call_idle_timeout_sec=int(
            os.getenv("CALL_IDLE_TIMEOUT_SEC", os.getenv("CALL_TIMEOUT_SEC", "90"))
        ),
        media_bidirectional=os.getenv("MEDIA_BIDIRECTIONAL", "true").lower() == "true",
        media_start_at_create=os.getenv("MEDIA_START_AT_CREATE", "true").lower() == "true",
        media_audio_channel_type=os.getenv("MEDIA_AUDIO_CHANNEL_TYPE", "mixed").lower(),
        media_frame_bytes=int(os.getenv("MEDIA_FRAME_BYTES", "640")),
        media_frame_interval_ms=int(os.getenv("MEDIA_FRAME_INTERVAL_MS", "20")),
        media_out_format=os.getenv("MEDIA_OUT_FORMAT", "json_simple").lower(),
        media_enable_voicelive_in=os.getenv("MEDIA_ENABLE_VL_IN", "true").lower() == "true",
        media_enable_voicelive_out=os.getenv("MEDIA_ENABLE_VL_OUT", "true").lower() == "true",
        voicelive_upsample_16k_to_24k=
            os.getenv("VOICELIVE_UPSAMPLE_16K_TO_24K", "true").lower() == "true",
        voicelive_input_flush_target_frames=int(os.getenv("VOICELIVE_INPUT_FLUSH_FRAMES", "4")),
        voicelive_input_flush_interval_ms=int(os.getenv("VOICELIVE_INPUT_FLUSH_INTERVAL_MS", "60")),
        voicelive_input_flush_max_interval_ms=int(os.getenv("VOICELIVE_INPUT_FLUSH_MAX_INTERVAL_MS", "180")),
        debug_voicelive_input_flush=os.getenv("DEBUG_VOICELIVE_INPUT_FLUSH", "false").lower() == "true",
    )
    settings.validate_voicelive()
    return settings


settings = load_settings()

