"""Voice in and voice out, with every engine behind the same two methods.

``Transcriber.transcribe(pcm, language=...)`` and ``Speaker.say(text)`` are all
the assistant knows. Both take a language hint: the two languages this app
speaks sound nothing alike, and a hint is the difference between a transcript
and a guess.

Speaking tries, in order, a Piper voice model if one is on disk, the operating
system's own voice (SAPI on Windows, ``say`` on macOS, ``spd-say``/``espeak`` on
Linux) and, as a last resort, the console. The system voice matters: Piper is a
download, and an assistant that goes silent because a file is missing is
indistinguishable from a broken assistant.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Protocol

from .audio import SAMPLE_RATE
from .i18n import normalize, t


class Transcriber(Protocol):
    language: str

    def transcribe(
        self, pcm: bytes, sample_rate: int = SAMPLE_RATE, language: str | None = None
    ) -> str:
        ...


class Speaker(Protocol):
    language: str

    def say(self, text: str) -> None:
        ...

    def stop(self) -> None:
        ...


class Silence:
    """Swallows speech: headless runs and tests."""

    language = "es"

    def say(self, text: str) -> None:
        return None

    def stop(self) -> None:
        return None


class ConsoleSpeaker:
    """Prints what would be spoken — the last fallback, always available."""

    prefix = "◂"

    def __init__(self, language: str = "es") -> None:
        self.language = normalize(language)

    def say(self, text: str) -> None:
        if text:
            print(f"{self.prefix} {text}", flush=True)

    def stop(self) -> None:
        return None


def _player_available() -> bool:
    """True when the WAV can actually be played from inside this process."""
    try:
        import sounddevice  # noqa: F401,PLC0415 - presence check only
    except Exception:  # noqa: BLE001
        return False
    return True


def _resolve_model(value: str | Path | None) -> Path | None:
    """The file behind a setting: a path that exists, or a name in ``voces``."""
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(os.path.expanduser(text))
    if path.is_file():
        return path
    name = voice_name(text)
    if name:
        candidate = voices_dir() / f"{name}.onnx"
        if candidate.is_file():
            return candidate
    return None


def _voice_models(voice: str | Path, voice_en: str | Path = "") -> dict[str, Path]:
    """Language -> model path, keeping only models that can be opened."""
    models: dict[str, Path] = {}
    for language, value in (("es", voice), ("en", voice_en)):
        resolved = _resolve_model(value)
        if resolved is not None:
            models[language] = resolved
    return models


class PiperSpeaker:
    """Local neural TTS through the ``piper`` binary plus ``sounddevice``.

    One model per language: a Spanish voice reading English is worse than the
    system voice, so ``say`` picks by ``self.language`` and falls back to any
    model that is actually on disk.
    """

    def __init__(
        self,
        models: dict[str, Path] | str | Path,
        *,
        executable: str = "piper",
        output: str = "",
        language: str = "es",
    ) -> None:
        if isinstance(models, (str, Path)):
            # Construction trusts the caller (tests, explicit setup) and only
            # upgrades a bare name to the downloaded file when there is one.
            text = str(models).strip()
            resolved = _resolve_model(text) if text else None
            models = {"es": resolved or Path(os.path.expanduser(text))} if text else {}
        self.models = dict(models)
        self.model_path = next(iter(self.models.values()), Path(""))
        self.executable = executable
        self.output = output
        self.language = normalize(language)

    @classmethod
    def if_available(
        cls,
        voice: str | Path,
        output: str = "",
        *,
        voice_en: str | Path = "",
        language: str = "es",
    ) -> "PiperSpeaker | None":
        binary = shutil.which("piper") or shutil.which("piper.exe")
        models = _voice_models(voice, voice_en)
        if not binary or not models:
            return None
        return cls(models, executable=binary, output=output, language=language)

    def model_for(self, language: str | None = None) -> Path | None:
        wanted = normalize(language or self.language)
        if wanted in self.models:
            return self.models[wanted]
        return next(iter(self.models.values()), None)

    def say(self, text: str) -> None:
        text = (text or "").strip()
        model = self.model_for()
        if not text or model is None:
            return
        playable = _player_available()
        # Without a player the WAV is the only thing left to hand over, so it has
        # to outlive this call instead of vanishing with a temporary folder.
        folder = tempfile.TemporaryDirectory(prefix="b1-tts-") if playable else None
        try:
            base = Path(folder.name) if folder else Path(tempfile.gettempdir())
            target = base / "b1-voz.wav"
            try:
                subprocess.run(
                    [self.executable, "--model", str(model), "--output_file", str(target)],
                    input=text.encode("utf-8"),
                    check=True,
                    capture_output=True,
                    timeout=120,
                )
            except (OSError, subprocess.SubprocessError):
                ConsoleSpeaker(self.language).say(text)
                return
            if not target.exists():
                ConsoleSpeaker(self.language).say(text)
            elif playable:
                self._play(target)
            else:
                ConsoleSpeaker(self.language).say(
                    t(self.language, "speech.audio_ready", path=target)
                )
        finally:
            if folder is not None:
                folder.cleanup()

    def _play(self, path: Path) -> None:
        from . import devices  # noqa: PLC0415 - avoids an import cycle

        try:
            import numpy as np  # noqa: PLC0415 - comes with sounddevice
            import sounddevice as sd  # noqa: PLC0415 - optional dependency
        except Exception:  # noqa: BLE001 - the caller prints the file instead
            ConsoleSpeaker(self.language).say(t(self.language, "speech.audio_ready", path=path))
            return
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            raw = handle.readframes(handle.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16)
        # The name is resolved per playback: a headset plugged in between two
        # answers should start receiving the next one.
        sd.play(samples, rate, device=devices.resolve(self.output, devices.OUTPUT, rate=rate))
        sd.wait()

    def stop(self) -> None:
        try:
            import sounddevice as sd  # noqa: PLC0415

            sd.stop()
        except Exception:  # noqa: BLE001 - nothing playing, nothing to stop.
            pass


#: What libasound, espeak and friends print when there is no device to play on.
_BROKEN = re.compile(r"(no such file|unable to|cannot open|error:)", re.IGNORECASE)

#: ``say -v '?'`` on macOS prints ``Name    locale    # sample``.
_SAY_LINE = re.compile(r"^(?P<name>.+?)\s{2,}(?P<locale>[a-z]{2}[_-][A-Za-z]{2})\s")


class SystemSpeaker:
    """Whatever the operating system already has, which needs no download.

    Windows ships SAPI (``System.Speech``), macOS ships ``say``, and most Linux
    desktops ship ``spd-say`` or ``espeak-ng``. The Windows text travels inside
    an encoded PowerShell script, so accents never depend on the console code
    page.
    """

    MAX_CHARS = 4_000

    def __init__(
        self,
        engine: str,
        *,
        voices: dict[str, str] | None = None,
        language: str = "es",
        runner=None,
    ) -> None:
        self.engine = engine
        self.voices = dict(voices or {})
        self.language = normalize(language)
        self._runner = runner or subprocess.run
        self._warned = False

    # -- discovery ----------------------------------------------------------
    @classmethod
    def detect(cls, *, language: str = "es") -> "SystemSpeaker | None":
        """The first engine this machine can actually run, or ``None``."""
        if os.name == "nt":
            shell = shutil.which("powershell") or shutil.which("powershell.exe")
            return cls("sapi", language=language) if shell else None
        if shutil.which("say"):
            return cls("say", voices=cls._say_voices(), language=language)
        for engine in ("spd-say", "espeak-ng", "espeak"):
            if shutil.which(engine):
                return cls(engine, language=language)
        return None

    @classmethod
    def if_available(cls, *, language: str = "es") -> "SystemSpeaker | None":
        return cls.detect(language=language)

    @staticmethod
    def _say_voices(runner=None) -> dict[str, str]:
        """Language -> voice name, from ``say -v '?'``."""
        run = runner or subprocess.run
        try:
            result = run(["say", "-v", "?"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return {}
        voices: dict[str, str] = {}
        for line in (result.stdout or "").splitlines():
            match = _SAY_LINE.match(line)
            if not match:
                continue
            voices.setdefault(normalize(match.group("locale")[:2]), match.group("name").strip())
        return voices

    # -- speaking -----------------------------------------------------------
    def voice_for(self, language: str | None = None) -> str:
        wanted = normalize(language or self.language)
        return self.voices.get(wanted, "")

    def command(self, text: str) -> list[str]:
        """The argv that speaks *text*; empty when this engine cannot."""
        body = (text or "").strip()[: self.MAX_CHARS]
        if not body:
            return []
        wanted = normalize(self.language)
        if self.engine == "sapi":
            script = (
                f"$want = '{wanted}';"
                "if (-not ('System.Speech.Synthesis.SpeechSynthesizer' -as [type])) {"
                " Add-Type -AssemblyName System.Speech };"
                "$engine = [System.Speech.Synthesis.SpeechSynthesizer]::new();"
                "$hit = $engine.GetInstalledVoices() | Where-Object { $_.Enabled -and "
                '$_.VoiceInfo.Culture.Name -like "$want*" } | Select-Object -First 1;'
                "if ($hit) { $engine.SelectVoice($hit.VoiceInfo.Name) };"
                "$engine.Speak('" + body.replace("'", "''") + "');"
            )
            encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
            shell = shutil.which("powershell") or shutil.which("powershell.exe") or "powershell"
            return [shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
        if self.engine == "say":
            voice = self.voice_for(wanted)
            return (["say", "-v", voice] if voice else ["say"]) + [body]
        if self.engine == "spd-say":
            return ["spd-say", "-w", "-l", wanted, body]
        return [self.engine, "-v", wanted, body]

    def say(self, text: str) -> None:
        command = self.command(text)
        if not command:
            return
        seconds = 15.0 + len(text) / 12.0
        try:
            result = self._runner(command, capture_output=True, timeout=min(seconds, 180.0))
        except (OSError, subprocess.SubprocessError) as exc:
            self._fall_back(text, str(exc))
            return
        # ``espeak`` exits 0 with "error: No such file or directory" when there
        # is no sound card, so the status code alone would report success and
        # leave the person in silence.
        reason = _output_of(result)
        if getattr(result, "returncode", 0) != 0 or _BROKEN.search(reason):
            self._fall_back(text, reason)

    def _fall_back(self, text: str, detail: str) -> None:
        """Say it in writing, and explain why only the first time."""
        ConsoleSpeaker(self.language).say(text)
        if self._warned:
            return
        self._warned = True
        print(
            t(self.language, "speech.engine_failed", detail=_reason_line(detail)),
            file=sys.stderr,
        )

    def stop(self) -> None:
        return None

    def describe(self) -> str:
        return f"{self.engine}, {self.voice_for() or '-'}"


class WhisperTranscriber:
    """Local speech-to-text with faster-whisper (MIT).

    The language hint is not a formality: on a two-second phrase the automatic
    detector is wrong often enough to answer English with Spanish text. When the
    hint produces nothing, the transcript is retried without it instead of
    returning silence.
    """

    def __init__(
        self, model_size: str = "small", *, device: str = "cpu", language: str = "auto"
    ) -> None:
        self.model_size = model_size
        self.device = device
        hint = (language or "auto").strip().lower()
        self.language = "auto" if hint in {"", "auto", "none"} else normalize(hint)
        self.last_language = ""
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel  # noqa: PLC0415
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(t(self.language, "speech.missing_faster_whisper")) from exc
            self._model = WhisperModel(
                self.model_size, device=self.device, compute_type="int8"
            )
        return self._model

    def _attempts(self, language: str | None) -> list[str | None]:
        hint = (language or self.language or "auto").strip().lower()
        if hint in {"auto", "", "none"}:
            return [None]
        return [normalize(hint), None]

    def transcribe(
        self, pcm: bytes, sample_rate: int = SAMPLE_RATE, language: str | None = None
    ) -> str:
        if not pcm:
            return ""
        import numpy as np  # noqa: PLC0415 - only needed with real audio

        model = self._load()
        audio = np.frombuffer(pcm, dtype=np.int16).astype("float32") / 32768.0
        text = ""
        for attempt in self._attempts(language):
            segments, info = model.transcribe(
                audio,
                language=attempt,
                beam_size=5,
                # The capture loop already cut the phrase at the silence, so a
                # second VAD can only eat short answers.
                vad_filter=False,
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            if text:
                detected = getattr(info, "language", "") or attempt or "es"
                self.last_language = normalize(detected)
                break
        return text


def _reason_line(text: str) -> str:
    """The line worth reading out of an audio library's wall of complaints."""
    lines = [" ".join(line.split()) for line in (text or "").splitlines() if line.strip()]
    for line in lines:
        if not line.lower().startswith(("alsa lib", "jack server is not running")):
            return line[:150]
    return lines[0][:150] if lines else "?"


def _output_of(result) -> str:
    """stderr (or stdout) of a finished process, as one line of text."""
    for stream in ("stderr", "stdout"):
        raw = getattr(result, stream, b"") or b""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        if raw.strip():
            return raw
    return ""


def voice_name(value: str | Path | None) -> str:
    """The bare Piper voice name in a setting, or "" when it is a file path."""
    text = str(value or "").strip()
    if not text or Path(os.path.expanduser(text)).is_file():
        return ""
    if any(sep in text for sep in (os.sep, "/", "\\")) or text.endswith(".onnx"):
        return ""
    return text


def voices_dir() -> Path:
    from .config import app_dir  # noqa: PLC0415 - avoids an import cycle

    return app_dir() / "voces"


def download_voices(
    names: list[str], target: Path | None = None, *, runner=None
) -> dict[str, str]:
    """Fetch Piper voices by name, one shot; returns name -> "" or an error.

    ``piper-tts`` ships the voices' *engine* but not the voices, so a fresh
    install can speak only through the system voice until this runs.
    """
    folder = Path(target or voices_dir())
    folder.mkdir(parents=True, exist_ok=True)
    run = runner or subprocess.run
    results: dict[str, str] = {}
    for name in names:
        wanted = (name or "").strip()
        if not wanted:
            continue
        if (folder / f"{wanted}.onnx").is_file():
            results[wanted] = ""
            continue
        error = t("es", "speech.no_piper")
        for python in _python_candidates():
            try:
                done = run(
                    [python, "-m", "piper.download_voices", wanted],
                    cwd=str(folder),
                    capture_output=True,
                    text=True,
                    timeout=900,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                error = str(exc)
                continue
            if (folder / f"{wanted}.onnx").is_file():
                error = ""
                break
            error = _reason_line(_output_of(done)) or str(getattr(done, "returncode", ""))
        results[wanted] = error
    return results


def _python_candidates() -> list[str]:
    """Interpreters that may own ``piper-tts``: ours first, then its console script."""
    found = [sys.executable]
    piper = shutil.which("piper")
    if piper:
        folder = Path(piper).resolve().parent
        for name in ("python", "python3", "python.exe"):
            if (folder / name).is_file():
                found.append(str(folder / name))
    for name in ("python3", "python"):
        executable = shutil.which(name)
        if executable:
            found.append(executable)
    return list(dict.fromkeys(found))


def make_speaker(
    voice: str = "",
    output: str = "",
    *,
    voice_en: str = "",
    language: str = "es",
) -> Speaker:
    """Best speaker available: Piper, else the system voice, else the console."""
    piper = PiperSpeaker.if_available(voice, output, voice_en=voice_en, language=language)
    if piper is not None:
        return piper
    system = SystemSpeaker.if_available(language=language)
    if system is not None:
        return system
    return ConsoleSpeaker(language)


def describe_voice(
    voice: str = "", voice_en: str = "", *, language: str = "es"
) -> tuple[Speaker, str]:
    """The speaker plus one sentence naming it (used by ``b1 --check``)."""
    speaker = make_speaker(voice, "", voice_en=voice_en, language=language)
    if isinstance(speaker, PiperSpeaker):
        model = speaker.model_for()
        return speaker, t(language, "speech.piper", voice=model.name if model else "?")
    if isinstance(speaker, SystemSpeaker):
        return speaker, t(
            language,
            "speech.system_voice",
            engine=speaker.engine,
            voice=speaker.voice_for() or "-",
        )
    wanted = [str(voice or "").strip(), str(voice_en or "").strip()]
    missing = [path for path in wanted if path and not Path(os.path.expanduser(path)).is_file()]
    if missing:
        reason = t(language, "speech.no_piper_model", path=missing[0])
        if voice_name(missing[0]):
            reason += " · " + t(language, "speech.voice_hint")
    else:
        reason = t(language, "speech.no_os_voice")
    return speaker, t(language, "speech.voice_none", reason=reason)


def make_transcriber(model_size: str = "small", *, language: str = "auto") -> Transcriber:
    return WhisperTranscriber(model_size, language=language)


def stt_ready() -> bool:
    try:
        import faster_whisper  # noqa: F401,PLC0415 - presence check only
    except Exception:  # noqa: BLE001
        return False
    return True


def mic_ready() -> bool:
    try:
        import sounddevice  # noqa: F401,PLC0415 - presence check only
    except Exception:  # noqa: BLE001
        return False
    return True


def piper_ready(*model_paths: str | None) -> bool:
    if not (shutil.which("piper") or shutil.which("piper.exe")):
        return False
    return any(
        path and Path(os.path.expanduser(path)).is_file() for path in model_paths if path
    )


def system_voice_ready() -> bool:
    return SystemSpeaker.detect() is not None
