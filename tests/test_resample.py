"""Tests for audio resampling between ACS (16kHz) and Voice Live (24kHz)."""
from __future__ import annotations
import array
import math

# Import the functions under test
from app.services.speech import _downsample_24k_to_16k, _upsample_16k_to_24k


def _make_sine_pcm(freq_hz: float, sample_rate: int, duration_ms: int) -> bytes:
    """Generate a sine wave as PCM16 mono bytes."""
    n_samples = sample_rate * duration_ms // 1000
    samples = array.array("h", [0] * n_samples)
    for i in range(n_samples):
        t = i / sample_rate
        samples[i] = int(16000 * math.sin(2 * math.pi * freq_hz * t))
    return samples.tobytes()


def test_downsample_sample_count():
    """24kHz 20ms frame (480 samples) should produce ~320 samples at 16kHz."""
    pcm_24k = _make_sine_pcm(440, 24000, 20)
    assert len(pcm_24k) == 960  # 480 samples * 2 bytes
    pcm_16k = _downsample_24k_to_16k(pcm_24k)
    samples_out = len(pcm_16k) // 2
    assert 318 <= samples_out <= 322  # ~320 samples (20ms @ 16kHz)


def test_upsample_sample_count():
    """16kHz 20ms frame (320 samples) should produce ~480 samples at 24kHz."""
    pcm_16k = _make_sine_pcm(440, 16000, 20)
    assert len(pcm_16k) == 640  # 320 samples * 2 bytes
    pcm_24k = _upsample_16k_to_24k(pcm_16k)
    samples_out = len(pcm_24k) // 2
    assert 478 <= samples_out <= 482  # ~480 samples (20ms @ 24kHz)


def test_roundtrip_preserves_length():
    """Downsample then upsample should approximately preserve sample count."""
    pcm_24k = _make_sine_pcm(440, 24000, 100)  # 100ms
    n_original = len(pcm_24k) // 2  # 2400 samples
    pcm_16k = _downsample_24k_to_16k(pcm_24k)
    pcm_back = _upsample_16k_to_24k(pcm_16k)
    n_roundtrip = len(pcm_back) // 2
    # Should be within ±2 samples of original
    assert abs(n_roundtrip - n_original) <= 3


def test_downsample_values_in_range():
    """Output samples should stay within int16 range."""
    # Max amplitude sine
    n = 480
    samples = array.array("h", [32767 if i % 2 == 0 else -32768 for i in range(n)])
    pcm = samples.tobytes()
    result = _downsample_24k_to_16k(pcm)
    out = array.array("h")
    out.frombytes(result)
    assert all(-32768 <= s <= 32767 for s in out)


def test_upsample_values_in_range():
    """Output samples should stay within int16 range."""
    n = 320
    samples = array.array("h", [32767 if i % 2 == 0 else -32768 for i in range(n)])
    pcm = samples.tobytes()
    result = _upsample_16k_to_24k(pcm)
    out = array.array("h")
    out.frombytes(result)
    assert all(-32768 <= s <= 32767 for s in out)


def test_empty_input():
    """Empty bytes should return empty bytes."""
    assert _downsample_24k_to_16k(b"") == b""
    assert _upsample_16k_to_24k(b"") == b""


def test_tiny_input():
    """Single sample should pass through unchanged."""
    one_sample = array.array("h", [1000]).tobytes()
    assert _downsample_24k_to_16k(one_sample) == one_sample
    assert _upsample_16k_to_24k(one_sample) == one_sample
