"""Microphone capture and end-of-speech detection.

Recording stops when the person stops talking, not on a fixed timer. Whether a
frame is speech is decided by a voice detector when one is given (Silero, see
``vad.py``) and otherwise by plain arithmetic on frame energy — no model, no
dependency — which is unit-tested with synthetic frames.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence

from .i18n import normalize, t

SAMPLE_RATE = 16_000
FRAME_MS = 30
BYTES_PER_SAMPLE = 2


def rms(frame: Sequence[float]) -> float:
    if not frame:
        return 0.0
    total = 0.0
    for value in frame:
        total += float(value) * float(value)
    return math.sqrt(total / len(frame))


def frames_to_pcm(frames: Iterable[Sequence[float]]) -> bytes:
    """Interleave-free mono PCM16, which is what every STT wants."""
    out = bytearray()
    for frame in frames:
        for value in frame:
            sample = int(max(-32768, min(32767, round(value))))
            out += sample.to_bytes(2, "little", signed=True)
    return bytes(out)


def pcm_to_floats(pcm: bytes) -> list[float]:
    if len(pcm) % 2:
        pcm = pcm[:-1]
    return [
        int.from_bytes(pcm[i : i + 2], "little", signed=True)
        for i in range(0, len(pcm), 2)
    ]


class Endpointer:
    """Feed it frames; it returns one utterance when speech has finished.

    ``speech_ratio`` is how many times louder than the running noise floor a
    frame must be to count as voice. The floor adapts only while idle, so a fan
    that switches on mid-phrase cannot swallow the end of the sentence.

    With a ``detector`` (anything with ``is_speech(frame) -> bool``), the
    detector decides what is voice instead of loudness: a fan or a keyboard no
    longer opens a phrase, and a soft voice still does.
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        frame_ms: int = FRAME_MS,
        *,
        speech_ratio: float = 3.0,
        floor_ceiling: float = 500.0,
        start_frames: int = 3,
        silence_ms: int = 700,
        preroll_ms: int = 240,
        max_ms: int = 20_000,
        detector=None,
    ) -> None:
        self.detector = detector
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.speech_ratio = speech_ratio
        self.floor_ceiling = floor_ceiling
        self.start_frames = max(1, start_frames)
        self.silence_frames = max(1, silence_ms // frame_ms)
        self.preroll_frames = max(0, preroll_ms // frame_ms)
        self.max_frames = max(1, max_ms // frame_ms)
        self.noise_floor = 60.0
        self.reset()

    def reset(self) -> None:
        self._voiced_run = 0
        self._silent_run = 0
        self._collecting = False
        self._frames: list[Sequence[float]] = []
        self._preroll: list[Sequence[float]] = []

    @property
    def threshold(self) -> float:
        return max(self.noise_floor * self.speech_ratio, 200.0)

    @property
    def collecting(self) -> bool:
        return self._collecting

    def feed(self, frame: Sequence[float]) -> bytes | None:
        """Consume one frame; return the finished utterance as PCM16, if any."""
        level = rms(frame)
        if self.detector is not None:
            loud = bool(self.detector.is_speech(frame))
        else:
            loud = level >= self.threshold

        if not self._collecting:
            self._preroll.append(frame)
            if len(self._preroll) > self.preroll_frames:
                self._preroll.pop(0)
            if not loud:
                # Only the quiet stretches teach the floor what "quiet" is here.
                self.noise_floor = min(
                    self.floor_ceiling, 0.95 * self.noise_floor + 0.05 * max(level, 20.0)
                )
                self._voiced_run = 0
                return None
            self._voiced_run += 1
            if self._voiced_run < self.start_frames:
                return None
            self._collecting = True
            self._frames = list(self._preroll)
            self._preroll = []
            self._silent_run = 0
            return None

        self._frames.append(frame)
        self._silent_run = 0 if loud else self._silent_run + 1
        too_long = len(self._frames) >= self.max_frames
        if self._silent_run >= self.silence_frames or too_long:
            utterance = frames_to_pcm(self._frames)
            self.reset()
            return utterance
        return None

    def flush(self) -> bytes | None:
        """Close the current utterance, e.g. when the user lets go of the button."""
        if not self._collecting or not self._frames:
            self.reset()
            return None
        utterance = frames_to_pcm(self._frames)
        self.reset()
        return utterance


class Microphone:
    """16 kHz mono capture via ``sounddevice``, from a chosen or default input.

    ``device`` is a name, not an index, so a saved setting survives a headset
    being plugged in: it is resolved again every time the stream opens.
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        frame_ms: int = FRAME_MS,
        device: str = "",
        language: str = "es",
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.frame_size = sample_rate * frame_ms // 1000
        self.device_name = device
        self.language = normalize(language)
        self.opened_at: int | None = None
        self._stream = None

    def _sd(self):
        try:
            import sounddevice  # noqa: PLC0415 - optional at import time
        except Exception as exc:  # noqa: BLE001 - reported as a sentence, not a trace
            raise RuntimeError(t(self.language, "audio.missing_sounddevice")) from exc
        return sounddevice

    def __enter__(self) -> "Microphone":
        from . import devices  # noqa: PLC0415 - avoids an import cycle

        sd = self._sd()
        self.opened_at = devices.resolve(
            self.device_name, devices.INPUT, rate=self.sample_rate
        )
        self._stream = sd.InputStream(
            device=self.opened_at,
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.frame_size,
        )
        self._stream.start()
        return self

    def __exit__(self, *exc_info) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    def frame(self) -> list[float]:
        if self._stream is None:
            raise RuntimeError(t(self.language, "audio.mic_not_open"))
        block, _overflowed = self._stream.read(self.frame_size)
        return [float(row[0]) for row in block]

    def listen(
        self,
        endpointer: Endpointer,
        on_level=None,
        should_stop: Callable[[], bool] | None = None,
    ) -> bytes | None:
        """Block until one utterance ends; returns its PCM16 bytes.

        ``should_stop`` is how the window's mic button cuts a phrase short: the
        audio captured so far is still transcribed instead of thrown away.
        """
        while True:
            if should_stop is not None and should_stop():
                return endpointer.flush()
            frame = self.frame()
            if on_level is not None:
                try:
                    on_level(rms(frame) / 32768.0)
                except Exception:  # noqa: BLE001 - UI cosmetics never stop capture.
                    pass
            utterance = endpointer.feed(frame)
            if utterance:
                return utterance


def record_phrase(
    *,
    on_level=None,
    max_seconds: float = 20.0,
    silence_ms: int = 700,
    device: str = "",
    language: str = "es",
    should_stop: Callable[[], bool] | None = None,
    vad: str = "silero",
) -> bytes:
    """Convenience wrapper: open the mic, listen for one phrase, close it."""
    from .vad import load_detector  # noqa: PLC0415 - optional model

    endpointer = Endpointer(
        silence_ms=silence_ms,
        max_ms=int(max_seconds * 1000),
        detector=load_detector(vad),
    )
    with Microphone(device=device, language=language) as mic:
        return mic.listen(endpointer, on_level=on_level, should_stop=should_stop) or b""
