"""Lean configuration model for the greenfield /app2 implementation."""
from __future__ import annotations
import os
from pydantic import BaseModel, field_validator
from dotenv import load_dotenv
from typing import Optional

load_dotenv()
load_dotenv(dotenv_path=".env.local", override=True)

class Settings(BaseModel):
    # Core service
    app_base_url: str
    acs_connection_string: str
    acs_outbound_caller_id: str
    default_system_prompt: str = "You are a helpful voice agent. Keep responses concise."
    target_phone_number: Optional[str] = None

    # Call lifecycle
    call_timeout_sec: int = 90
    call_idle_timeout_sec: int = 90

    # Speech GA
    enable_voice_live: bool = True
    speech_key: str | None = None
    speech_region: str | None = None
    default_voice: str | None = None

    # Media basics
    media_bidirectional: bool = True
    media_start_at_create: bool = False
    media_audio_channel_type: str = "mixed"  # mixed|unmixed
    media_frame_bytes: int = 640            # 20ms @16k PCM16 mono
    media_frame_interval_ms: int = 20
    media_out_format: str = "json_simple"   # json_simple|binary

    # Bridge toggles
    media_enable_voicelive_in: bool = True
    media_enable_voicelive_out: bool = True

    @field_validator("app_base_url", "acs_connection_string", "acs_outbound_caller_id")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Missing required configuration value")
        return v

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_base_url=os.getenv("APP_BASE_URL", "http://localhost:8000"),
            acs_connection_string=os.getenv("ACS_CONNECTION_STRING", ""),
            acs_outbound_caller_id=os.getenv("ACS_OUTBOUND_CALLER_ID", ""),
            default_system_prompt=os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful voice agent. Keep responses concise."),
            target_phone_number=os.getenv("TARGET_PHONE_NUMBER"),
            call_timeout_sec=int(os.getenv("CALL_TIMEOUT_SEC", "90")),
            call_idle_timeout_sec=int(os.getenv("CALL_IDLE_TIMEOUT_SEC", os.getenv("CALL_TIMEOUT_SEC", "90"))),
            enable_voice_live=os.getenv("ENABLE_VOICE_LIVE", "true").lower() == "true",
            speech_key=os.getenv("SPEECH_KEY"),
            speech_region=os.getenv("SPEECH_REGION"),
            default_voice=os.getenv("DEFAULT_VOICE"),
            media_bidirectional=os.getenv("MEDIA_BIDIRECTIONAL", "true").lower() == "true",
            media_start_at_create=os.getenv("MEDIA_START_AT_CREATE", "false").lower() == "true",
            media_audio_channel_type=os.getenv("MEDIA_AUDIO_CHANNEL_TYPE", "mixed").lower(),
            media_frame_bytes=int(os.getenv("MEDIA_FRAME_BYTES", "640")),
            media_frame_interval_ms=int(os.getenv("MEDIA_FRAME_INTERVAL_MS", "20")),
            media_out_format=os.getenv("MEDIA_OUT_FORMAT", "json_simple").lower(),
            media_enable_voicelive_in=os.getenv("MEDIA_ENABLE_VL_IN", os.getenv("MEDIA_ENABLE_VOICELIVE_IN", "true")).lower() == "true",
            media_enable_voicelive_out=os.getenv("MEDIA_ENABLE_VL_OUT", os.getenv("MEDIA_ENABLE_VOICELIVE_OUT", "true")).lower() == "true",
        )

    def validate(self):
        if self.enable_voice_live:
            missing = []
            if not self.speech_key: missing.append("SPEECH_KEY")
            if not self.speech_region: missing.append("SPEECH_REGION")
            if not self.default_voice: missing.append("DEFAULT_VOICE")
            if missing:
                raise ValueError(f"Voice Live enabled but missing: {', '.join(missing)}")
        if self.media_audio_channel_type not in {"mixed", "unmixed"}:
            raise ValueError("MEDIA_AUDIO_CHANNEL_TYPE must be mixed or unmixed")
        if self.media_out_format not in {"json_simple", "binary"}:
            raise ValueError("MEDIA_OUT_FORMAT must be json_simple or binary")

settings = Settings.from_env()
settings.validate()
