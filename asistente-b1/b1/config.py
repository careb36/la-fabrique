"""Settings, stored as one JSON file the user can edit by hand.

Precedence, highest first: environment variable, saved file, built-in default.
Every value has a working default except the model key, so a fresh install opens
the window and says what is missing instead of failing to start.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .i18n import normalize

ENV_PREFIX = "B1_"
DEFAULT_FACTORY_URL = "http://127.0.0.1:8000"
# NVIDIA's catalog gateway serves the Nemotron family; the launcher points the
# assistant at the local llm-proxy instead, which fronts whichever provider key
# the install actually has.
DEFAULT_MODEL_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"


_NUMERIC = {
    "model_temperature": float,
    "model_top_p": float,
    "model_max_tokens": int,
    "model_timeout": float,
}


def _coerce(field_name: str, value: str):
    """A saved/env value as the type its field declares (bad values are ignored)."""
    if field_name == "language":
        return normalize(value)
    if field_name == "vad":
        from .vad import normalize_choice  # noqa: PLC0415 - avoids an import cycle

        return normalize_choice(value)
    if field_name == "stt_language":
        text = str(value).strip().lower()
        if text in {"auto", "es", "en"}:
            return text
        return "auto"
    if field_name in {"model_thinking", "model_stream"}:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on", "si", "sí"}
    caster = _NUMERIC.get(field_name)
    if caster is None:
        return value
    try:
        return caster(value)
    except (TypeError, ValueError):
        return None


def app_dir() -> Path:
    """Per-user folder for the config, the logs and the model cache."""
    override = (os.getenv(ENV_PREFIX + "HOME") or "").strip()
    return Path(override).expanduser() if override else Path.home() / ".asistente-b1"


def config_file() -> Path:
    return app_dir() / "config.json"


@dataclass
class Settings:
    """Everything the assistant needs to talk and to reach the factory."""

    model_base_url: str = DEFAULT_MODEL_BASE_URL
    model: str = DEFAULT_MODEL
    model_api_key: str = ""
    # Nemotron reasons before answering when the chat template is told to:
    # the thinking tokens are billed against max_tokens, so it needs room.
    model_thinking: bool = False
    # Speak each sentence as soon as the model has written it, instead of
    # waiting for the whole answer. Off for a server that streams badly.
    model_stream: bool = True
    model_temperature: float = 0.6
    model_top_p: float = 0.95
    model_max_tokens: int = 4096
    model_timeout: float = 180.0

    factory_url: str = DEFAULT_FACTORY_URL
    voice_key: str = ""
    factory_company_id: int | None = None

    language: str = "es"
    briefing: bool = True
    open_build_in_browser: bool = True

    stt_model: str = "small"
    # "auto" lets Whisper decide; "es"/"en" pins the listening language and is
    # the difference between a transcript and a guess on short phrases.
    stt_language: str = "auto"
    # What ends a phrase: "silero" (a voice detector, from faster-whisper) or
    # "energy" (loudness alone). Silero falls back to energy when missing.
    vad: str = "silero"
    tts_voice: str = "es_ES-sharvard-medium"
    tts_voice_en: str = "en_US-amy-medium"
    assistant_name: str = "B1"
    # Device *names* (see b1/devices.py): "" means whatever the system chose.
    mic_device: str = ""
    speaker_device: str = ""

    def env_overrides(self) -> dict[str, str]:
        """Environment variables that win over the file, keyed by field name."""
        pairs = {
            "model_base_url": "MODEL_BASE_URL",
            "model": "MODEL",
            "model_api_key": "MODEL_API_KEY",
            "model_thinking": "MODEL_THINKING",
            "model_stream": "MODEL_STREAM",
            "model_temperature": "MODEL_TEMPERATURE",
            "model_top_p": "MODEL_TOP_P",
            "model_max_tokens": "MODEL_MAX_TOKENS",
            "model_timeout": "MODEL_TIMEOUT",
            "factory_url": "FACTORY_URL",
            "voice_key": "VOICE_KEY",
            "language": "LANGUAGE",
            "stt_language": "STT_LANGUAGE",
            "vad": "VAD",
            "tts_voice": "TTS_VOICE",
            "tts_voice_en": "TTS_VOICE_EN",
            "assistant_name": "NAME",
            "mic_device": "MIC_DEVICE",
            "speaker_device": "SPEAKER_DEVICE",
        }
        out: dict[str, str] = {}
        for field_name, env_name in pairs.items():
            value = (os.getenv(ENV_PREFIX + env_name) or "").strip()
            if value:
                out[field_name] = value
        return out

    def apply_env(self) -> "Settings":
        for field_name, value in self.env_overrides().items():
            coerced = _coerce(field_name, value)
            if coerced is not None:
                setattr(self, field_name, coerced)
        return self

    def speech_language(self, language: str | None = None) -> str:
        """The language the microphone should listen for this turn."""
        if self.stt_language in {"es", "en"}:
            return self.stt_language
        return normalize(language or self.language)

    def is_local_model(self) -> bool:
        """True for a model server on this machine, which usually needs no key."""
        host = (self.model_base_url.split("//", 1)[-1].split("/", 1)[0].split("@")[-1]
                .split(":")[0].strip("[]"))
        return host in {"127.0.0.1", "localhost", "0.0.0.0", "::1", ""}

    def missing(self) -> list[str]:
        """What a person has to fill in before the assistant can think."""
        gaps = []
        if not self.model_api_key and not self.is_local_model():
            gaps.append("model_api_key")
        if not self.model_base_url:
            gaps.append("model_base_url")
        if not self.model:
            gaps.append("model")
        return gaps

    def save(self, path: Path | None = None) -> Path:
        target = path or config_file()
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Created 0600 from the first byte: the file holds the model key and
        # the voice key, and a chmod after writing leaves a window when it is
        # readable by others. Windows ignores the mode; the folder is per-user.
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n")
        try:
            target.chmod(0o600)  # an existing file keeps its old mode otherwise
        except OSError:
            pass
        return target

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        source = path or config_file()
        data: dict = {}
        if source.exists():
            try:
                data = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}  # A broken file must not stop the app from opening.
        known = {f.name for f in fields(cls)}
        kept: dict = {}
        for name, value in data.items():
            if name not in known:
                continue
            coerced = _coerce(name, value)
            if coerced is not None:
                kept[name] = coerced
        return cls(**kept).apply_env()

    def factory_url_clean(self) -> str:
        return self.factory_url.rstrip("/")

    def model_url_clean(self) -> str:
        return self.model_base_url.rstrip("/")
