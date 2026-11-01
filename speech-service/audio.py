"""WAV in, samples out, and back: the little audio plumbing the service needs.

Clients send 16-bit PCM WAV at any rate; the recognizer wants float samples
at 16 kHz; the voice answers with 16-bit PCM WAV at its own rate. Pure
functions on bytes and arrays, no I/O.
"""

from __future__ import annotations

import io
import wave

import numpy as np

SAMPLE_RATE = 16_000


class AudioError(ValueError):
    """The bytes are not a WAV this service reads."""


def decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    """Float32 mono samples in [-1, 1] and their rate, from 16-bit PCM WAV bytes."""
    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            if handle.getsampwidth() != 2:
                raise AudioError("only 16-bit PCM WAV is accepted")
            channels = handle.getnchannels()
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
    except (wave.Error, EOFError) as exc:
        raise AudioError(f"not a WAV file: {exc or 'truncated'}") from None
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    return pcm, rate


def resample(samples: np.ndarray, rate: int, target: int = SAMPLE_RATE) -> np.ndarray:
    """Linear resampling: enough for speech on its way to a recognizer."""
    if rate == target or not len(samples):
        return samples.astype(np.float32)
    duration = len(samples) / rate
    n = int(round(duration * target))
    src = np.linspace(0.0, duration, num=len(samples), endpoint=False)
    dst = np.linspace(0.0, duration, num=n, endpoint=False)
    return np.interp(dst, src, samples).astype(np.float32)


def encode_wav(samples: np.ndarray, rate: int) -> bytes:
    """16-bit PCM mono WAV bytes from float samples in [-1, 1]."""
    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2")
    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(rate))
        handle.writeframes(pcm.tobytes())
    return out.getvalue()


def padded(samples: np.ndarray, seconds: float = 0.5, rate: int = SAMPLE_RATE) -> np.ndarray:
    """Silence before and after: a recognizer is unsure of a clip that starts mid-breath."""
    pad = np.zeros(int(seconds * rate), dtype=np.float32)
    return np.concatenate([pad, samples, pad])
