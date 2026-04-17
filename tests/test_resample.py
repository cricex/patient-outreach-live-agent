"""Tests for audio helpers after resampling removal (24kHz unified pipeline)."""
from __future__ import annotations
import array
import math

from app.services.speech import _calculate_rms, FRAME_BYTES


def _make_sine_pcm(freq_hz: float, sample_rate: int, duration_ms: int) -> bytes:
    """Generate a sine wave as PCM16 mono bytes."""
    n_samples = sample_rate * duration_ms // 1000
    samples = array.array("h", [0] * n_samples)
    for i in range(n_samples):
        t = i / sample_rate
        samples[i] = int(16000 * math.sin(2 * math.pi * freq_hz * t))
    return samples.tobytes()


def test_frame_bytes_is_960():
    """FRAME_BYTES should be 960 (20ms @ 24kHz = 480 samples * 2 bytes)."""
    assert FRAME_BYTES == 960


def test_rms_silence():
    """RMS of silence should be 0."""
    silence = bytes(960)
    assert _calculate_rms(silence) == 0.0


def test_rms_full_scale():
    """RMS of max-amplitude square wave should be 1.0 (clamped)."""
    n = 480
    samples = array.array("h", [32767] * n)
    pcm = samples.tobytes()
    rms = _calculate_rms(pcm)
    assert rms > 0.9


def test_rms_in_range():
    """RMS of a sine wave should be between 0 and 1."""
    pcm = _make_sine_pcm(440, 24000, 20)
    rms = _calculate_rms(pcm)
    assert 0.0 < rms < 1.0


def test_rms_empty():
    """RMS of empty bytes should be 0."""
    assert _calculate_rms(b"") == 0.0


def test_rms_one_sample():
    """RMS of a single sample should work without error."""
    one = array.array("h", [1000]).tobytes()
    rms = _calculate_rms(one)
    assert rms > 0.0


def test_rms_louder_is_higher():
    """Louder audio should produce higher RMS than quieter audio."""
    quiet = array.array("h", [100] * 480).tobytes()
    loud = array.array("h", [10000] * 480).tobytes()
    assert _calculate_rms(loud) > _calculate_rms(quiet)
