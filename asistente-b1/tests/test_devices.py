"""Choosing microphone and speakers without opening a single device.

PortAudio is replaced by a table of endpoints that behaves like the real thing
in the two ways that matter: the same hardware appears several times (once per
host API) and some endpoints refuse the rate the assistant uses.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from b1 import devices
from b1.audio import Microphone

ENDPOINTS = [
    # index, name, hostapi, inputs, outputs
    {"name": "Microsoft Sound Mapper - Input", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "Micrófono integrado", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "Auriculares USB", "hostapi": 1, "max_input_channels": 1, "max_output_channels": 0},
    {"name": "default", "hostapi": 2, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "Micrófono integrado", "hostapi": 1, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "Parlantes Realtek", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "Auriculares USB", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "sysdefault", "hostapi": 2, "max_input_channels": 0, "max_output_channels": 2},
]


class FakeStream:
    def __init__(self, levels: list[int]) -> None:
        self.levels = list(levels)
        self.closed = False
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "FakeStream":
        self.started = True
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def read(self, size: int) -> tuple[list[list[int]], bool]:
        level = self.levels.pop(0) if self.levels else 0
        return [[level]] * size, False


class FakeSoundDevice(SimpleNamespace):
    """The slice of ``sounddevice`` this project touches."""

    def __init__(self, *, refuse=(), levels=None) -> None:
        super().__init__()
        self.default = SimpleNamespace(device=(1, 5))
        self.refuse = set(refuse)
        self.opened: list[dict] = []
        self.played: list[dict] = []
        self.levels = list(levels or [])

    def query_devices(self):
        return [dict(endpoint) for endpoint in ENDPOINTS]

    def query_hostapis(self):
        return [{"name": "MME"}, {"name": "WASAPI"}, {"name": "ALSA"}]

    def check_input_settings(self, device=None, samplerate=None, channels=None, dtype=None):
        if (device, "input") in self.refuse:
            raise RuntimeError("Invalid sample rate")

    def check_output_settings(self, device=None, samplerate=None, channels=None):
        if (device, "output") in self.refuse:
            raise RuntimeError("Device unavailable")

    def InputStream(self, **kwargs):  # noqa: N802 - mirrors sounddevice's API
        self.opened.append(kwargs)
        return FakeStream(self.levels)

    def play(self, samples, rate, device=None):
        self.played.append({"samples": len(samples), "rate": rate, "device": device})

    def wait(self):
        pass


@pytest.fixture()
def audio(monkeypatch):
    def install(**kwargs) -> FakeSoundDevice:
        fake = FakeSoundDevice(**kwargs)
        monkeypatch.setitem(sys.modules, "sounddevice", fake)
        devices.refresh()
        return fake

    yield install
    devices.refresh()


def test_system_aliases_are_not_offered_as_hardware(audio):
    audio()

    microphones = devices.list_devices(devices.INPUT)
    speakers = devices.list_devices(devices.OUTPUT)

    assert devices.DEFAULT_LABEL in {devices.DEFAULT_LABEL}
    assert "default" not in microphones
    assert "sysdefault" not in speakers
    assert not any("sound mapper" in name.casefold() for name in microphones)


def test_the_same_hardware_is_listed_once_per_direction(audio):
    audio()

    microphones = devices.list_devices(devices.INPUT)
    speakers = devices.list_devices(devices.OUTPUT)

    assert microphones.count("Micrófono integrado") == 1
    assert microphones == ["Micrófono integrado", "Auriculares USB"]
    assert "Auriculares USB" in speakers


def test_a_microphone_that_cannot_run_at_16_khz_is_left_out(audio):
    audio(refuse={(2, "input")})

    assert "Auriculares USB" not in devices.list_devices(devices.INPUT)
    # Only the input side was refused: the same name stays as a speaker.
    assert "Auriculares USB" in devices.list_devices(devices.OUTPUT)


def test_a_saved_name_beats_an_index_and_ignores_case(audio):
    audio()

    assert devices.resolve("Auriculares USB", devices.OUTPUT) == 6
    assert devices.resolve("auriculares usb", devices.OUTPUT) == 6
    assert devices.resolve("Micrófono integrado", devices.INPUT) == 1


def test_a_device_that_was_unplugged_means_system_default(audio):
    audio()

    assert devices.resolve("", devices.INPUT) is None
    assert devices.resolve("Micrófono del año pasado", devices.INPUT) is None
    assert "no está conectado" in devices.describe(devices.INPUT, "Micrófono del año pasado")
    assert "índice 1" in devices.describe(devices.INPUT, "Micrófono integrado")


def test_opening_the_microphone_passes_the_resolved_index(audio):
    fake = audio()

    with Microphone(device="Auriculares USB") as mic:
        assert mic.opened_at == 2
    assert fake.opened[0]["device"] == 2
    assert fake.opened[0]["samplerate"] == 16_000


def test_a_missing_microphone_degrades_to_the_default_instead_of_failing(audio):
    fake = audio()

    with Microphone(device="Micrófono del año pasado") as mic:
        assert mic.opened_at is None
    assert fake.opened[0]["device"] is None


def test_measuring_reports_what_actually_arrived(audio):
    quiet = audio(levels=[0] * 400)
    assert devices.probe_microphone("Micrófono integrado", seconds=0.2)["ok"] is False

    loud = audio(levels=[20_000] * 400)
    result = devices.probe_microphone("Micrófono integrado", seconds=0.2)
    assert result["ok"] is True
    assert result["peak"] > 0.5


def test_the_speaker_test_plays_through_the_chosen_output(audio):
    fake = audio()

    result = devices.tone("Auriculares USB", seconds=0.1)

    assert result["ok"] is True
    assert fake.played[0]["device"] == 6
    assert fake.played[0]["samples"] > 0


def test_without_the_audio_library_everything_answers_honestly(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    devices.refresh()

    assert devices.available() is False
    assert devices.list_devices(devices.INPUT) == []
    assert devices.resolve("Micrófono integrado", devices.INPUT) is None
    assert devices.probe_microphone("", seconds=0.1)["ok"] is False
    assert devices.tone("")["ok"] is False
    assert "predeterminado" in devices.describe(devices.OUTPUT, "")
