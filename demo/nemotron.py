"""Lo mínimo para hablar con Token Factory, sin SDK ni dependencias.

La demo y el verificador del hackathon necesitan tres cosas: saber a qué
puertas preguntar, repartir el catálogo en dos niveles de coste y hacer una
llamada ``/chat/completions``. Todo eso vive aquí, con la biblioteca estándar,
para que un clon limpio del repositorio funcione sin el checkout de referencia
``profesor3/`` (que no se distribuye).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

KEY_NAME = "NEBIUS_API_KEY"
# Nebius tiene dos puertas para el mismo catálogo y cada una con su clave.
NEBIUS_URLS = (
    "https://api.tokenfactory.nebius.com/v1",
    "https://api.studio.nebius.com/v1",
)
# NVIDIA NIM sirve los mismos Nemotron con una clave que también empieza por
# ``nvapi-``: el prefijo no dice en qué puerta vale.
NVIDIA_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NEMOTRON_URL = NEBIUS_URLS[0]
DEFAULT_NEMOTRON_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
DEFAULT_FAST_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DOORS = (
    ("NVIDIA NIM", NVIDIA_URL),
    ("Nebius Token Factory", NEBIUS_URLS[0]),
    ("Nebius AI Studio", NEBIUS_URLS[1]),
)
# Los nombres son los de ``AgentRole.value`` en la fábrica, en minúsculas.
FACTORY_ROLES = ("po", "architect", "scrummaster", "developer", "qa",
                 "secops", "techwriter", "engramprocessor")
# Un catálogo trae de todo: esto no es un modelo de chat y no debe elegirse.
_NON_CHAT = ("embed", "rerank", "guard", "parse", "whisper", "tts", "-vl",
             "vision")


class ModelError(Exception):
    """El proveedor contestó algo que no se puede usar."""


def clean_key(value: str | None) -> str:
    """La clave como la quiere el encabezado, no como se pega."""
    key = str(value or "").strip().strip('"').strip("'")
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key


def factory_dir() -> Path | None:
    """La carpeta de la fábrica, buscando desde este archivo y desde el cwd."""
    candidates: list[Path] = []
    configured = os.getenv("FABRICA_HOME")
    if configured:
        candidates.append(Path(configured))
    here = Path(__file__).resolve()
    # In this repository the factory is the root; a checkout that nests it
    # under ``la-fabrique/`` is found too.
    candidates.extend(here.parents)
    candidates.extend(parent / "la-fabrique" for parent in here.parents)
    cwd = Path.cwd()
    candidates.extend((cwd, cwd / "la-fabrique", cwd.parent / "la-fabrique"))
    for folder in candidates:
        if (folder / "backend").is_dir():
            return folder
    return None


def read_env() -> dict[str, str]:
    """Las claves del ``.env`` de la fábrica; vacío si todavía no existe."""
    folder = factory_dir()
    path = folder / ".env" if folder else None
    if path is None or not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = raw.partition("=")
        if not sep or name.strip().startswith("#"):
            continue
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def tier_models(offered: list[str], default: str = "") -> tuple[str, str]:
    """Reparte el catálogo en (razonamiento, rápido).

    Sólo devuelve ids que el proveedor publicó: un id inventado falla en el
    primer turno. Si no hay nada que se parezca a Ultra o a Super/Nano, el
    nivel que falta vuelve vacío.
    """
    ids = [str(model).strip() for model in (offered or [])
           if str(model).strip()]
    chat = [model for model in ids
            if not any(bad in model.lower() for bad in _NON_CHAT)]

    def pick(words: tuple[str, ...]) -> str:
        for word in words:
            for model in chat:
                if word in model.lower():
                    return model
        return ""

    chosen = str(default or "").strip()
    strategic = pick(("ultra",)) or (chosen if chosen in chat else "")
    fast = pick(("nano", "super", "flash"))
    if fast == strategic:
        fast = ""
    return strategic, fast


class ChatClient:
    """Cliente mínimo de ``/chat/completions`` y ``/models``.

    Acepta la configuración como diccionario (``base_url``, ``model``,
    ``api_key``...) para que la demo y el verificador compartan la misma forma
    de construirlo. No hay streaming a propósito: una respuesta completa es lo
    que necesita el bucle de código.
    """

    def __init__(self, cfg: dict[str, Any] | None = None,
                 **kwargs: Any) -> None:
        data: dict[str, Any] = dict(cfg or {})
        data.update(kwargs)
        self.base = str(data.get("base_url") or data.get("base")
                        or DEFAULT_NEMOTRON_URL).rstrip("/")
        self.api_key = clean_key(data.get("api_key") or "")
        self.model = str(data.get("model") or DEFAULT_NEMOTRON_MODEL)
        self.temperature = float(data.get("temperature", 0.2))
        self.max_tokens = int(data.get("max_tokens", 8192))
        self.timeout = float(data.get("timeout", 180))
        self.thinking = bool(data.get("thinking", False))

    @property
    def base_url(self) -> str:
        return self.base

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _json(self, request: urllib.request.Request, timeout: float) -> Any:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            raise ModelError(f"HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise ModelError(str(exc.reason)) from exc
        except (ValueError, OSError) as exc:
            raise ModelError(str(exc)) from exc

    def models(self, timeout: float = 8.0) -> list[str]:
        request = urllib.request.Request(f"{self.base}/models",
                                         headers=self._headers())
        body = self._json(request, timeout)
        rows = body.get("data", body) if isinstance(body, dict) else body
        if not isinstance(rows, list):
            raise ModelError("el catálogo no es una lista")
        return [str(row["id"]) for row in rows
                if isinstance(row, dict) and row.get("id")]

    def complete(self, messages: list[dict[str, Any]],
                 temperature: float | None = None,
                 max_tokens: int | None = None,
                 tools: list[dict[str, Any]] | None = None
                 ) -> tuple[str, str]:
        """Devuelve ``(texto, razonamiento)``; el razonamiento no se habla."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": (self.temperature if temperature is None
                            else temperature),
            "max_tokens": (self.max_tokens if max_tokens is None
                           else int(max_tokens)),
        }
        if self.thinking and self._speaks_nemotron():
            payload["chat_template_kwargs"] = {"enable_thinking": True}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        request = urllib.request.Request(
            f"{self.base}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(), method="POST")
        body = self._json(request, self.timeout)
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("la respuesta no trae choices[0].message") from exc
        return (str(message.get("content") or ""),
                str(message.get("reasoning_content") or ""))

    def _speaks_nemotron(self) -> bool:
        host = self.base.split("//", 1)[-1].split("/", 1)[0].lower()
        return ("nemotron" in self.model.lower()
                or host.endswith(("integrate.api.nvidia.com",
                                  "api.tokenfactory.nebius.com")))
