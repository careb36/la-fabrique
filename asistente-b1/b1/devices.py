"""Which microphone and which speakers B1 uses.

PortAudio hands out numbers, and those numbers are reassigned whenever a headset
appears or disappears, so a saved index can silently mean a different endpoint
tomorrow. The setting therefore keeps the device *name* and this module turns it
back into an index at the moment a stream is opened.

Two things are filtered out of the list a person sees: aliases for "whatever the
operating system picks" (``default``, ``sysdefault``, the Windows sound mapper)
because the picker already opens with that option, and endpoints that cannot run
at the rate the assistant needs. The list is cached, because enumerating devices
takes long enough on a busy machine to be visible in the window.
"""

from __future__ import annotations

import math
import threading
import time

from .i18n import normalize, t

DEFAULT_LABEL = t("es", "dev.default_label")
DEFAULT_VALUE = ""
INPUT = "input"
OUTPUT = "output"
STT_RATE = 16_000

# How long a cached device list is trusted before it is refreshed once.
_TTL_SECONDS = 30.0

_lock = threading.Lock()
_cache: dict = {}
_ALIASES = {
    "",
    "default",
    "default input",
    "default output",
    "sysdefault",
    "sysdefault input",
    "sysdefault output",
    "dmix",
    "pulse",
    "pipewire",
    "jack",
    "primary sound driver",
    "primary sound capture driver",
    "microsoft sound mapper",
    "microsoft sound mapper - input",
    "microsoft sound mapper - output",
}


def _sounddevice():
    try:
        import sounddevice  # noqa: PLC0415 - optional dependency
    except Exception:  # noqa: BLE001
        return None
    return sounddevice


def available() -> bool:
    """True when the audio library can be imported at all."""
    return _sounddevice() is not None


def _is_alias(name: str) -> bool:
    folded = " ".join(name.split()).casefold()
    return folded in _ALIASES or "sound mapper" in folded


def _opens(sd, index: int, kind: str, rate: int) -> bool:
    """Whether this endpoint really accepts the rate and channel count we use."""
    try:
        if kind == INPUT:
            sd.check_input_settings(
                device=index, samplerate=rate, channels=1, dtype="int16"
            )
        else:
            sd.check_output_settings(device=index, samplerate=rate, channels=1)
    except Exception:  # noqa: BLE001 - an endpoint that refuses is simply skipped
        return False
    return True


def _default_api(sd, devices: list, kind: str):
    """Host API of the system default in that direction, preferred when listing."""
    try:
        wanted = sd.default.device[0 if kind == INPUT else 1]
    except Exception:  # noqa: BLE001
        return None
    if isinstance(wanted, int) and 0 <= wanted < len(devices):
        return devices[wanted].get("hostapi")
    return None


def _probe(sd) -> dict:
    """Build ``{"input": [...], "output": [...]}`` of ``(name, index, api)``."""
    devices = list(sd.query_devices())
    channels = {INPUT: "max_input_channels", OUTPUT: "max_output_channels"}
    found: dict = {}
    for kind, field in channels.items():
        preferred = _default_api(sd, devices, kind)
        entries: list = []
        for index, device in enumerate(devices):
            if not device.get(field):
                continue
            name = " ".join(str(device.get("name") or "").split())
            if not name or _is_alias(name):
                continue
            # The microphone rate is fixed (the STT and endpointer both assume
            # 16 kHz); speakers are only filtered by rate when one is asked for.
            if kind == INPUT and not _opens(sd, index, kind, STT_RATE):
                continue
            entries.append((name, index, device.get("hostapi")))
        # Stable sort: endpoints on the system default's API come first, the
        # rest keep PortAudio's order.
        entries.sort(key=lambda item: item[2] != preferred)
        unique: list = []
        seen: set = set()
        for entry in entries:
            key = entry[0].casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(entry)
        found[kind] = unique
    return found


def _entries(kind: str, refresh: bool = False) -> list:
    if kind not in (INPUT, OUTPUT):
        raise ValueError(f"tipo de dispositivo desconocido: {kind}")
    sd = _sounddevice()
    if sd is None:
        return []
    with _lock:
        cached = _cache.get(kind)
        fresh = cached is not None and (time.monotonic() - cached[0]) < _TTL_SECONDS
        if fresh and not refresh:
            return list(cached[1])
    try:
        probed = _probe(sd)
    except Exception:  # noqa: BLE001 - no PortAudio, no devices, no crash
        return []
    stamp = time.monotonic()
    with _lock:
        for name, entries in probed.items():
            _cache[name] = (stamp, entries)
        return list(_cache.get(kind, (stamp, []))[1])


def list_devices(kind: str, refresh: bool = False) -> list[str]:
    """Names a person can choose from, in preference order."""
    return [name for name, _index, _api in _entries(kind, refresh=refresh)]


def refresh() -> None:
    """Drop the cache so the next listing talks to the host again."""
    with _lock:
        _cache.clear()


def resolve(name: str, kind: str, rate: int | None = None) -> int | None:
    """Index for a saved device name, or ``None`` to mean "system default".

    A name from a headset that is no longer plugged in also resolves to ``None``:
    losing the chosen microphone must fall back to the built-in one, never to an
    error on startup. When several endpoints share a name, the first that opens
    at ``rate`` wins.
    """
    wanted = " ".join((name or "").split())
    if not wanted:
        return None
    entries = _entries(kind)
    folded = wanted.casefold()
    tiers = (
        lambda value: value == folded,
        lambda value: value.startswith(folded),
        lambda value: folded in value,
    )
    sd = _sounddevice()
    for matches in tiers:
        candidates = [
            index for label, index, _api in entries if matches(label.casefold())
        ]
        if not candidates:
            continue
        if rate is not None and sd is not None:
            for index in candidates:
                if _opens(sd, index, kind, rate):
                    return index
        return candidates[0]
    return None


def default_label(language: str = "es") -> str:
    return t(normalize(language), "dev.default_label")


def describe(
    kind: str, name: str, rate: int | None = None, *, language: str = "es"
) -> str:
    """One line for ``--check``: what will actually be opened."""
    language = normalize(language)
    label = t(language, "dev.mic" if kind == INPUT else "dev.output")
    wanted = (name or "").strip()
    if not wanted:
        return f"{label}: {default_label(language).lower()}"
    index = resolve(wanted, kind, rate=rate)
    if index is None:
        return t(language, "dev.not_connected", label=label, name=wanted)
    return t(language, "dev.described", label=label, name=wanted, index=index)


def probe_microphone(
    name: str = "", seconds: float = 3.0, on_level=None, *, language: str = "es"
) -> dict:
    """Listen to one input for a moment and judge the level that came in.

    Answers ``{"ok", "peak", "verdict"}``. ``on_level`` is called around twenty
    times a second with 0.0-1.0 so a window can move a bar while the person is
    still speaking; without it, a test that takes three seconds looks frozen.
    """
    language = normalize(language)
    sd = _sounddevice()
    if sd is None:
        return {"ok": False, "peak": 0.0, "verdict": t(language, "dev.missing_sounddevice")}
    index = resolve(name, INPUT, rate=STT_RATE)
    block = max(1, STT_RATE // 20)
    peak = 0.0
    try:
        with sd.InputStream(
            device=index,
            samplerate=STT_RATE,
            channels=1,
            dtype="int16",
            blocksize=block,
        ) as stream:
            deadline = time.monotonic() + max(0.5, seconds)
            while time.monotonic() < deadline:
                chunk, _overflow = stream.read(block)
                level = max(abs(int(row[0])) for row in chunk) / 32768.0
                peak = max(peak, level)
                if on_level is not None:
                    try:
                        on_level(min(1.0, level * 3.0))
                    except Exception:  # noqa: BLE001 - cosmetics never fail a test
                        pass
    except Exception as exc:  # noqa: BLE001 - reported as a sentence
        return {
            "ok": False,
            "peak": 0.0,
            "verdict": t(language, "dev.cannot_open", detail=exc),
        }
    if peak >= 0.15:
        verdict = t(language, "dev.strong")
    elif peak >= 0.03:
        verdict = t(language, "dev.low")
    else:
        verdict = t(language, "dev.silent")
    return {"ok": peak >= 0.03, "peak": peak, "verdict": verdict}


def tone(name: str, seconds: float = 0.7, *, language: str = "es") -> dict:
    """Play a short beep through one output; only the person can confirm it."""
    language = normalize(language)
    sd = _sounddevice()
    if sd is None:
        return {"ok": False, "verdict": t(language, "dev.tone_missing")}
    index = resolve(name, OUTPUT, rate=24_000)
    rate = 24_000
    total = int(rate * max(0.1, seconds))
    samples = [int(9_000 * math.sin(2 * math.pi * 660 * step / rate)) for step in range(total)]
    try:
        sd.play(samples, rate, device=index)
        sd.wait()
    except Exception as exc:  # noqa: BLE001 - reported as a sentence
        return {"ok": False, "verdict": t(language, "dev.tone_failed", detail=exc)}
    return {
        "ok": True,
        "verdict": t(language, "dev.tone_heard", device=name or default_label(language)),
    }
