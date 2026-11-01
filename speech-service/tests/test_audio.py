from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio import AudioError, decode_wav, encode_wav, padded, resample  # noqa: E402
from models import KOKORO_FILES, download_kokoro, kokoro_present  # noqa: E402


def test_wav_round_trip_keeps_the_samples_and_the_rate():
    samples = np.linspace(-1, 1, 1000, dtype=np.float32)
    back, rate = decode_wav(encode_wav(samples, 22_050))
    assert rate == 22_050
    # One step of 16-bit quantization, plus the 32767/32768 scale at the ends.
    assert np.allclose(back, samples, atol=2 / 32767)


def test_decode_refuses_other_widths_and_garbage():
    with pytest.raises(AudioError):
        decode_wav(b"RIFF....WAVE")
    with pytest.raises(AudioError):
        decode_wav(b"")


def test_resample_changes_the_length_and_keeps_the_duration():
    second = np.ones(48_000, dtype=np.float32)
    assert len(resample(second, 48_000)) == 16_000
    assert len(resample(second, 16_000)) == 48_000  # already at the target rate: untouched
    assert len(resample(np.zeros(0, dtype=np.float32), 8_000)) == 0


def test_padded_adds_half_a_second_each_side():
    out = padded(np.ones(100, dtype=np.float32), seconds=0.5, rate=100)
    assert len(out) == 200 and out[0] == 0 and out[-1] == 0 and out[50] == 1


class _Response:
    def __init__(self, data: bytes) -> None:
        self._data = io_bytes(data)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n: int) -> bytes:
        return self._data.read(n)


def io_bytes(data: bytes):
    import io

    return io.BytesIO(data)


def test_download_keeps_only_files_whose_hash_matches(tmp_path):
    results = download_kokoro(tmp_path, opener=lambda url, timeout: _Response(b"not the model"))
    assert all("does not match" in error for error in results.values())
    assert not kokoro_present(tmp_path)
    assert not list(tmp_path.glob("*.part"))
    assert set(results) == set(KOKORO_FILES)
