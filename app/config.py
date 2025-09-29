"""Configuration helpers for loading environment-driven runtime settings."""

import os
from pydantic import BaseModel, field_validator
from typing import Optional
from dotenv import load_dotenv

# Load default environment variables for deployment
load_dotenv()
# Load local environment variables, overriding the default ones for local development
load_dotenv(dotenv_path=".env.local", override=True)

class Settings(BaseModel):
    """Strongly typed configuration for the FastAPI voice call service."""
    app_base_url: str
    acs_connection_string: str
    acs_endpoint: Optional[str] = None
    acs_outbound_caller_id: str
    default_system_prompt: str
    target_phone_number: Optional[str] = None
    call_timeout_sec: int = 90
    call_idle_timeout_sec: int = 90
    enable_voice_live: bool = True
    ai_foundry_endpoint: Optional[str] = None
    ai_foundry_api_key: Optional[str] = None
    voice_live_model: Optional[str] = None
    default_voice: Optional[str] = None
    media_bidirectional: bool = True
    media_start_at_create: bool = False
    media_bidi_send_ack: bool = False
    media_token_mode: str = "opaque"  # opaque | callid
    media_dump_wav: bool = False
    media_wav_path: str = "media_capture.wav"
    media_frame_bytes: int = 640  # 20ms @16k mono 16-bit
    media_frame_interval_ms: int = 20
    media_enable_voicelive_out: bool = True
    media_send_zero_frame: bool = False
    media_log_all_text_frames: bool = False
    media_audio_channel_type: str = "mixed"  # mixed | unmixed
    media_enable_voicelive_in: bool = True
    media_vl_in_commit_every: int = 1
    media_vl_in_start_frames: int = 10      # minimum non-silent frames before starting bridge (~200ms)
    media_vl_in_start_rms: int = 60         # minimum rolling RMS average before starting bridge
    media_out_format: str = "multi"  # json_simple | json_wrapped | binary | multi (tries several)
    media_out_max_queue_frames: int = 10
    vl_input_min_ms: int = 160  # raised default minimum ms buffered before commit to model (was 120)
    vl_input_safety_ms: int = 40  # additional safety margin added to adaptive minimum when computing commit threshold
    voice_live_force_input_rate: int | None = None  # optional override if service does not report numeric rate
    voice_live_force_output_rate: int | None = None  # optional override for model output assumed rate
    # --- Added VAD / latency control fields (centralizing previously scattered env vars) ---
    vl_dynamic_rms_offset: int = 300               # base additive offset above noise floor after bootstrap
    vl_dynamic_rms_min: int = 40                   # minimum adaptive RMS threshold floor
    vl_dynamic_rms_max: int = 1600                 # maximum adaptive RMS threshold ceiling
    vl_min_speech_frames: int = 5                  # minimum speech frames (~20ms each) required for commit (steady-state)
    vl_max_buffer_ms: int = 2000                   # safety cap before forced commit
    vl_bootstrap_duration_ms: int = 2000           # window using lowered offset to detect first speech quickly
    vl_bootstrap_rms_offset: int = 80              # temporary reduced offset during bootstrap window
    vl_bootstrap_min_speech_frames: int = 3        # minimum frames during bootstrap (faster first turn)
    vl_silence_commit_ms: int = 140                # silence gap to treat end-of-phrase (early commit)
    vl_offset_decay_step: int = 10                 # amount to reduce offset during prolonged no-speech search
    vl_offset_decay_interval_ms: int = 200         # interval for applying decay while hunting for first speech
    vl_offset_decay_min: int = 40                  # floor for decayed offset during bootstrap
    vl_barge_in_enabled: bool = True               # enable barge-in detection when agent is speaking
    vl_barge_in_offset: int = 40                   # additive offset used for barge-in detection (lower than normal)
    vl_barge_in_consecutive_frames: int = 3        # frames above barge-in threshold to trigger interruption
    # Enhanced barge-in tuning (new)
    vl_barge_in_min_agent_ms: int = 800            # minimum agent speech ms before barge-in allowed
    vl_barge_in_min_user_ms: int = 160             # minimum continuous user speech ms to qualify
    vl_barge_in_relative_factor: float = 1.3       # require rms >= factor * noise_floor (in addition to offset)
    vl_barge_in_cooldown_ms: int = 1200            # cooldown after a barge-in before another can trigger
    vl_barge_in_release_frames: int = 6            # hysteresis: frames below lower threshold to re-arm
    # Further barge-in hardening (new)
    vl_barge_in_lock_ms: int = 1200                # hard lock window after agent starts where barge-in cannot begin tracking
    vl_barge_in_min_snr_db: int = 10               # minimum SNR (dB) above noise baseline for candidate
    vl_barge_in_abs_min_rms: int = 100             # absolute RMS floor to qualify (filters faint echo)
    # Commit gating: enforce minimum user speech duration before we allow a phrase commit (except hard safeties)
    vl_commit_min_user_ms: int = 600               # 0 disables; prevents agent from replying mid-utterance
    vl_log_first_commit: bool = True               # emit structured first-commit timing log

    @field_validator("app_base_url", "acs_connection_string", "acs_outbound_caller_id", "default_system_prompt")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Required environment variable missing or empty")
        return v

    @classmethod
    def from_env(cls) -> "Settings":
        """Build a ``Settings`` instance, normalizing legacy or truncated variables."""
        raw_cs = os.getenv("ACS_CONNECTION_STRING", "").strip()
        # Fallback: if environment variable was exported without quotes and got truncated at ';'
        if raw_cs and 'accesskey=' not in raw_cs:
            try:
                from pathlib import Path
                env_path = Path('.env')
                if env_path.exists():
                    for line in env_path.read_text().splitlines():
                        if line.startswith('ACS_CONNECTION_STRING='):
                            full = line.split('=', 1)[1].strip()
                            # Remove optional surrounding quotes
                            if (full.startswith('"') and full.endswith('"')) or (full.startswith("'") and full.endswith("'")):
                                full = full[1:-1]
                            if 'accesskey=' in full:
                                raw_cs = full
                                break
            except Exception:
                pass
        return cls(
            app_base_url=os.getenv("APP_BASE_URL", "http://localhost:8000"),
            acs_connection_string=raw_cs,
            acs_endpoint=os.getenv("ACS_ENDPOINT"),
            acs_outbound_caller_id=os.getenv("ACS_OUTBOUND_CALLER_ID", ""),
            default_system_prompt=os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful English voice agent. Keep answers concise."),
            target_phone_number=os.getenv("TARGET_PHONE_NUMBER"),
            call_timeout_sec=int(os.getenv("CALL_TIMEOUT_SEC", "90")),
            call_idle_timeout_sec=int(os.getenv("CALL_IDLE_TIMEOUT_SEC", os.getenv("CALL_TIMEOUT_SEC", "90"))),
            enable_voice_live=os.getenv("ENABLE_VOICE_LIVE", "true").lower() == "true",
            ai_foundry_endpoint=os.getenv("AI_FOUNDRY_ENDPOINT"),
            ai_foundry_api_key=os.getenv("AI_FOUNDRY_API_KEY"),
            voice_live_model=os.getenv("VOICE_LIVE_MODEL"),
            default_voice=os.getenv("DEFAULT_VOICE"),
            media_bidirectional=os.getenv("MEDIA_BIDIRECTIONAL", "true").lower() == "true",
            media_start_at_create=os.getenv("MEDIA_START_AT_CREATE", "false").lower() == "true",
            media_bidi_send_ack=os.getenv("MEDIA_BIDI_SEND_ACK", "false").lower() == "true",
            media_token_mode=os.getenv("MEDIA_TOKEN_MODE", "opaque").lower(),
            media_send_zero_frame=os.getenv("MEDIA_SEND_ZERO_FRAME", "false").lower() == "true",
            media_dump_wav=os.getenv("MEDIA_DUMP_WAV", "false").lower() == "true",
            media_wav_path=os.getenv("MEDIA_WAV_PATH", "media_capture.wav"),
            media_frame_bytes=int(os.getenv("MEDIA_FRAME_BYTES", "640")),
            media_frame_interval_ms=int(os.getenv("MEDIA_FRAME_INTERVAL_MS", "20")),
            media_enable_voicelive_out=os.getenv("MEDIA_ENABLE_VL_OUT", os.getenv("MEDIA_ENABLE_VOICELIVE_OUT", "true")).lower() == "true",
            media_log_all_text_frames=os.getenv("MEDIA_LOG_ALL_TEXT_FRAMES", "false").lower() == "true",
            media_audio_channel_type=os.getenv("MEDIA_AUDIO_CHANNEL_TYPE", "mixed").lower(),
            media_enable_voicelive_in=os.getenv("MEDIA_ENABLE_VL_IN", os.getenv("MEDIA_ENABLE_VOICELIVE_IN", "true")).lower() == "true",
            media_vl_in_commit_every=int(os.getenv("MEDIA_VL_IN_COMMIT_EVERY", "1")),
            media_vl_in_start_frames=int(os.getenv("MEDIA_VL_IN_START_FRAMES", "10")),
            media_vl_in_start_rms=int(os.getenv("MEDIA_VL_IN_START_RMS", "60")),
            media_out_format=os.getenv("MEDIA_OUT_FORMAT", "multi").lower(),
            media_out_max_queue_frames=int(os.getenv("MEDIA_OUT_MAX_QUEUE_FRAMES", "10")),
            vl_input_min_ms=int(os.getenv("VL_INPUT_MIN_MS", os.getenv("MEDIA_VL_INPUT_MIN_MS", "160"))),
            vl_input_safety_ms=int(os.getenv("VL_INPUT_SAFETY_MS", "40")),
            voice_live_force_input_rate=(int(os.getenv("VOICE_LIVE_FORCE_INPUT_RATE")) if os.getenv("VOICE_LIVE_FORCE_INPUT_RATE") else None),
            voice_live_force_output_rate=(int(os.getenv("VOICE_LIVE_FORCE_OUTPUT_RATE")) if os.getenv("VOICE_LIVE_FORCE_OUTPUT_RATE") else None),
            # New VAD / barge-in settings (fallback to existing env vars if set)
            vl_dynamic_rms_offset=int(os.getenv("VL_DYNAMIC_RMS_OFFSET", os.getenv("VL_DYNAMIC_RMS_OFFSET_STEADY", "300"))),
            vl_dynamic_rms_min=int(os.getenv("VL_DYNAMIC_RMS_MIN", "40")),
            vl_dynamic_rms_max=int(os.getenv("VL_DYNAMIC_RMS_MAX", "1600")),
            vl_min_speech_frames=int(os.getenv("VL_MIN_SPEECH_FRAMES", "5")),
            vl_max_buffer_ms=int(os.getenv("VL_MAX_BUFFER_MS", "2000")),
            vl_bootstrap_duration_ms=int(os.getenv("VL_BOOTSTRAP_DURATION_MS", "2000")),
            vl_bootstrap_rms_offset=int(os.getenv("VL_BOOTSTRAP_RMS_OFFSET", os.getenv("VL_DYNAMIC_RMS_OFFSET_BOOTSTRAP", "80"))),
            vl_bootstrap_min_speech_frames=int(os.getenv("VL_BOOTSTRAP_MIN_SPEECH_FRAMES", "3")),
            vl_silence_commit_ms=int(os.getenv("VL_SILENCE_COMMIT_MS", "140")),
            vl_offset_decay_step=int(os.getenv("VL_OFFSET_DECAY_STEP", "10")),
            vl_offset_decay_interval_ms=int(os.getenv("VL_OFFSET_DECAY_INTERVAL_MS", "200")),
            vl_offset_decay_min=int(os.getenv("VL_OFFSET_DECAY_MIN", "40")),
            vl_barge_in_enabled=os.getenv("VL_BARGE_IN_ENABLED", "true").lower() == "true",
            vl_barge_in_offset=int(os.getenv("VL_BARGE_IN_OFFSET", "40")),
            vl_barge_in_consecutive_frames=int(os.getenv("VL_BARGE_IN_CONSECUTIVE_FRAMES", "3")),
            vl_barge_in_min_agent_ms=int(os.getenv("VL_BARGE_IN_MIN_AGENT_MS", "800")),
            vl_barge_in_min_user_ms=int(os.getenv("VL_BARGE_IN_MIN_USER_MS", "160")),
            vl_barge_in_relative_factor=float(os.getenv("VL_BARGE_IN_RELATIVE_FACTOR", "1.3")),
            vl_barge_in_cooldown_ms=int(os.getenv("VL_BARGE_IN_COOLDOWN_MS", "1200")),
            vl_barge_in_release_frames=int(os.getenv("VL_BARGE_IN_RELEASE_FRAMES", "6")),
            vl_barge_in_lock_ms=int(os.getenv("VL_BARGE_IN_LOCK_MS", "1200")),
            vl_barge_in_min_snr_db=int(os.getenv("VL_BARGE_IN_MIN_SNR_DB", "10")),
            vl_barge_in_abs_min_rms=int(os.getenv("VL_BARGE_IN_ABS_MIN_RMS", "100")),
            vl_commit_min_user_ms=int(os.getenv("VL_COMMIT_MIN_USER_MS", "600")),
            vl_log_first_commit=os.getenv("VL_LOG_FIRST_COMMIT", "true").lower() == "true",
        )

    def validate_voice_live(self):
        """Validate Voice Live related flags before the app starts serving traffic."""
        if self.enable_voice_live:
            missing = []
            if not self.ai_foundry_endpoint:
                missing.append("AI_FOUNDRY_ENDPOINT")
            if not self.ai_foundry_api_key:
                missing.append("AI_FOUNDRY_API_KEY")
            if not self.voice_live_model:
                missing.append("VOICE_LIVE_MODEL")
            if not self.default_voice:
                missing.append("DEFAULT_VOICE")
            if missing:
                raise ValueError(f"Voice Live enabled but missing required env: {', '.join(missing)}")
        if self.media_token_mode not in {"opaque", "callid"}:
            raise ValueError("MEDIA_TOKEN_MODE must be 'opaque' or 'callid'")
        if self.media_audio_channel_type not in {"mixed", "unmixed"}:
            raise ValueError("MEDIA_AUDIO_CHANNEL_TYPE must be 'mixed' or 'unmixed'")


settings = Settings.from_env()
settings.validate_voice_live()
