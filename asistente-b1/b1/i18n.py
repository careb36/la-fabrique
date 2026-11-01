"""Every sentence the person reads or hears, in Spanish and in English.

One dictionary, two columns. Anything that reaches a human — window labels,
console output, microphone verdicts, error sentences — goes through ``t()`` so a
missing translation fails in a test instead of showing up as half a Spanish
window in the middle of an English conversation.

The conversation itself is *not* translated here: the model answers in whatever
language the person just used. This module only covers the fixed text around it.
"""

from __future__ import annotations

DEFAULT = "es"
LANGUAGES = ("es", "en")

# Tokens a person may type or say to switch language explicitly.
SWITCH_TO = {
    "es": {"spanish", "español", "espanol", "castellano"},
    "en": {"english", "inglés", "ingles"},
}


def normalize(code: str | None) -> str:
    """``en`` for anything starting with ``en``, ``es`` otherwise."""
    text = (code or "").strip().lower()
    return "en" if text.startswith("en") else DEFAULT


def other(language: str) -> str:
    return "en" if normalize(language) == "es" else "es"


_TEXTS: dict[str, dict[str, str]] = {
    # -- console and command line ------------------------------------------
    "app.description": {
        "es": "asistente de escritorio: la fábrica de software, por voz",
        "en": "desktop assistant: the software factory, by voice",
    },
    "app.help_gui": {"es": "abrir la ventana (por defecto)", "en": "open the window (default)"},
    "app.help_orb": {"es": "abrir solo el orbe compacto", "en": "open the compact orb only"},
    "app.help_text": {
        "es": "charla por consola, sin micrófono",
        "en": "talk in the console, no microphone",
    },
    "app.help_guide": {"es": "imprimir la guía de la fábrica", "en": "print the factory guide"},
    "app.help_check": {"es": "diagnóstico de instalación y de voz", "en": "install and voice check"},
    "app.help_init": {
        "es": "crear config.json con valores por defecto",
        "en": "write config.json with defaults",
    },
    "app.help_help": {
        "es": "mostrar esta ayuda y salir",
        "en": "show this help and exit",
    },
    "app.help_speak": {
        "es": "decir una frase por la voz de salida y salir",
        "en": "say one sentence through the output voice and exit",
    },
    "app.options": {"es": "opciones", "en": "options"},
    "app.metavar_text": {"es": "TEXTO", "en": "TEXT"},
    "app.help_voices": {
        "es": "descargar las voces de Piper configuradas",
        "en": "download the configured Piper voices",
    },
    "app.voices_downloading": {
        "es": "Descargando voces de Piper: {names} …",
        "en": "Downloading Piper voices: {names} …",
    },
    "app.voices_ok": {"es": " ✓ {name}", "en": " ✓ {name}"},
    "app.voices_where": {"es": "Quedaron en {path}", "en": "They are in {path}"},
    "app.voices_paths_set": {
        "es": "Las voces configuradas ya son rutas a archivos .onnx: no hay nada que bajar.",
        "en": "The configured voices are already .onnx paths: nothing to download.",
    },
    "app.help_language": {
        "es": "es | en (por defecto: el de la config)",
        "en": "es | en (default: the one in config)",
    },
    "app.help_no_briefing": {
        "es": "no leer la guía al arrancar",
        "en": "do not read the guide at start-up",
    },
    "app.help_version": {"es": "mostrar la versión", "en": "show the version"},
    "app.qt_missing": {
        "es": "Qt no está instalado (pip install PyQt6). Arranco en modo texto.",
        "en": "Qt is not installed (pip install PyQt6). Starting in text mode.",
    },
    "app.window_failed": {
        "es": "No puedo abrir la ventana ({detail}). Uso el modo texto.",
        "en": "Cannot open the window ({detail}). Using text mode.",
    },
    "app.init_written": {"es": "Escribí la configuración en {path}", "en": "Wrote the settings to {path}"},
    "app.init_missing": {"es": "falta completar: {gap}", "en": "still missing: {gap}"},
    "app.check_config": {"es": "config:", "en": "config:"},
    "app.check_model": {"es": "modelo:", "en": "model:"},
    "app.check_factory": {"es": "fábrica:", "en": "factory:"},
    "app.check_language": {"es": "idioma:", "en": "language:"},
    "app.check_mic": {"es": "micrófono:", "en": "microphone:"},
    "app.check_input": {"es": "entrada:", "en": "input:"},
    "app.check_output": {"es": "salida:", "en": "output:"},
    "app.check_stt": {"es": "voz a texto:", "en": "speech to text:"},
    "app.check_vad": {"es": "fin de frase:", "en": "end of phrase:"},
    "vad.silero": {
        "es": "Silero VAD (distingue la voz del ruido)",
        "en": "Silero VAD (tells a voice from noise)",
    },
    "vad.energy_chosen": {
        "es": "por volumen (B1_VAD=energy)",
        "en": "by loudness (B1_VAD=energy)",
    },
    "vad.energy_fallback": {
        "es": "por volumen: Silero no está disponible (viene con faster-whisper)",
        "en": "by loudness: Silero is not available (it comes with faster-whisper)",
    },
    "app.check_tts": {"es": "voz de salida:", "en": "voice out:"},
    "app.check_qt": {"es": "Qt:", "en": "Qt:"},
    "app.check_key": {"es": "clave modelo:", "en": "model key:"},
    "app.yes": {"es": "sí", "en": "yes"},
    "app.no_mic": {"es": "no (sounddevice)", "en": "no (sounddevice)"},
    "app.no_stt": {"es": "no (faster-whisper)", "en": "no (faster-whisper)"},
    "app.no_qt": {"es": "no (PyQt6)", "en": "no (PyQt6)"},
    "app.key_loaded": {"es": "cargada", "en": "loaded"},
    "app.key_missing": {"es": "falta", "en": "missing"},
    "app.text_prompt": {"es": "vos> ", "en": "you> "},
    "app.text_hint": {"es": "Escribí y enter. «salir» termina.", "en": "Type and press enter. “exit” quits."},
    "app.text_no_model": {
        "es": "[sin modelo: falta {gaps} — podés probar la fábrica igual]",
        "en": "[no model: missing {gaps} — you can still try the factory]",
    },
    # -- assistant ---------------------------------------------------------
    "assistant.no_key": {
        "es": "Me falta la clave del modelo en los ajustes, así que no puedo pensar "
        "una respuesta. La fábrica sigue disponible en cuanto la cargues.",
        "en": "The model key is missing from my settings, so I cannot think of an "
        "answer. The factory is available as soon as you add it.",
    },
    "assistant.loop_limit": {
        "es": "Me quedé dando vueltas con las herramientas y corté para no repetir "
        "llamadas. Decime de nuevo qué necesitás, más corto.",
        "en": "I got stuck looping through tools, so I stopped to avoid repeating "
        "calls. Tell me again, shorter.",
    },
    "assistant.done": {"es": "Listo.", "en": "Done."},
    "assistant.model_failure": {
        "es": "No pude hablar con el modelo ({detail}). Revisá la URL y la clave.",
        "en": "I could not reach the model ({detail}). Check the URL and the key.",
    },
    # -- audio capture -----------------------------------------------------
    "audio.mic_not_open": {"es": "el micrófono no está abierto", "en": "the microphone is not open"},
    "audio.missing_sounddevice": {
        "es": "falta el paquete sounddevice: instalalo con «pip install sounddevice»",
        "en": "the sounddevice package is missing: install it with “pip install sounddevice”",
    },
    "audio.no_speech": {
        "es": "No escuché nada. Probá de nuevo, más cerca del micrófono.",
        "en": "I heard nothing. Try again, closer to the microphone.",
    },
    "audio.stopped": {"es": "corté la escucha", "en": "listening stopped"},
    # -- speech engines ----------------------------------------------------
    "speech.missing_faster_whisper": {
        "es": "falta faster-whisper: instalalo con «pip install faster-whisper»",
        "en": "faster-whisper is missing: install it with “pip install faster-whisper”",
    },
    "speech.audio_ready": {
        "es": "(audio listo en {path})",
        "en": "(audio ready at {path})",
    },
    "speech.console_only": {
        "es": "Sin motor de voz instalado: te contesto por escrito. "
        "En Windows alcanza con PowerShell; si no, «pip install piper-tts» y un modelo.",
        "en": "No speech engine installed: I answer in writing. On Windows PowerShell "
        "is enough; otherwise “pip install piper-tts” plus a voice model.",
    },
    "speech.voice_ok": {"es": "voz: {detail}", "en": "voice: {detail}"},
    "speech.voice_none": {
        "es": "ninguna (solo texto): {reason}",
        "en": "none (text only): {reason}",
    },
    "speech.no_piper": {
        "es": "no encontré piper-tts en ningún intérprete",
        "en": "no interpreter here has piper-tts",
    },
    "speech.no_piper_model": {
        "es": "no encontré el modelo de Piper «{path}»",
        "en": "Piper voice model “{path}” not found",
    },
    "speech.no_os_voice": {
        "es": "este sistema no trae un motor de voz utilizable",
        "en": "this system has no usable speech engine",
    },
    "speech.engine_failed": {
        "es": "el motor de voz no pudo sonar ({detail}); sigo por escrito",
        "en": "the speech engine could not play ({detail}); continuing in writing",
    },
    "speech.voice_hint": {
        "es": "b1 --voces las descarga una vez",
        "en": "b1 --voices downloads them once",
    },
    "speech.piper": {"es": "Piper ({voice})", "en": "Piper ({voice})"},
    "speech.kokoro": {"es": "Kokoro ({voice})", "en": "Kokoro ({voice})"},
    "app.kokoro_downloading": {
        "es": "Bajando la voz Kokoro (unos 120 MB, una sola vez) a {path}",
        "en": "Downloading the Kokoro voice (about 120 MB, once) to {path}",
    },
    "app.kokoro_missing": {
        "es": "Kokoro no está instalado (pip install kokoro-onnx); sigo con Piper.",
        "en": "Kokoro is not installed (pip install kokoro-onnx); going on with Piper.",
    },
    "speech.system_voice": {
        "es": "voz del sistema ({engine}, {voice})",
        "en": "system voice ({engine}, {voice})",
    },
    # -- devices -----------------------------------------------------------
    "dev.default_label": {"es": "Sistema (predeterminado)", "en": "System (default)"},
    "dev.mic": {"es": "micrófono", "en": "microphone"},
    "dev.output": {"es": "salida de audio", "en": "audio output"},
    "dev.missing_sounddevice": {"es": "falta sounddevice", "en": "sounddevice is missing"},
    "dev.cannot_open": {"es": "no pude abrirlo ({detail})", "en": "could not open it ({detail})"},
    "dev.strong": {"es": "se escucha fuerte y claro", "en": "loud and clear"},
    "dev.low": {
        "es": "llega sonido, pero bajo: acercate o subí el volumen",
        "en": "sound arrives, but quietly: get closer or raise the volume",
    },
    "dev.silent": {
        "es": "no llegó sonido: revisá el micrófono elegido y los permisos",
        "en": "no sound arrived: check the chosen microphone and the permissions",
    },
    "dev.tone_ok": {
        "es": "el pitido salió por {device}; ¿lo escuchaste?",
        "en": "the tone played through {device}; did you hear it?",
    },
    "dev.tone_missing": {
        "es": "falta sounddevice o no hay salida de audio",
        "en": "sounddevice is missing or there is no audio output",
    },
    "dev.tone_failed": {"es": "no pude reproducir: {detail}", "en": "could not play it: {detail}"},
    "dev.tone_heard": {
        "es": "tendrías que haber oído un pitido por {device}",
        "en": "you should have heard a beep through {device}",
    },
    "dev.not_connected": {
        "es": "{label}: «{name}» no está conectado, uso el predeterminado",
        "en": "{label}: “{name}” is not connected, using the default",
    },
    "dev.described": {
        "es": "{label}: «{name}» (índice {index})",
        "en": "{label}: “{name}” (index {index})",
    },
    # -- window ------------------------------------------------------------
    "ui.title": {"es": "Ajustes", "en": "Settings"},
    "ui.talk": {"es": "🎙  Hablar", "en": "🎙  Talk"},
    "ui.listening": {"es": "●  Escuchando", "en": "●  Listening"},
    "ui.already_listening": {"es": "Ya estoy escuchando… (clic de nuevo para cortar)", "en": "Already listening… (click again to stop)"},
    "ui.type_placeholder": {
        "es": "Escribí si preferís no hablar…",
        "en": "Type if you would rather not talk…",
    },
    "ui.guide": {"es": "Guía", "en": "Guide"},
    "ui.settings": {"es": "Ajustes", "en": "Settings"},
    "ui.state_idle": {"es": "en espera", "en": "idle"},
    "ui.state_listening": {"es": "escuchando", "en": "listening"},
    "ui.state_thinking": {"es": "pensando", "en": "thinking"},
    "ui.state_speaking": {"es": "hablando", "en": "speaking"},
    "ui.status_ready": {"es": "listo", "en": "ready"},
    "ui.role_you": {"es": "VOS", "en": "YOU"},
    "ui.role_system": {"es": "SYS", "en": "SYS"},
    "ui.role_factory": {"es": "FÁBRICA", "en": "FACTORY"},
    "ui.role_tool": {"es": "TOOL", "en": "TOOL"},
    "ui.missing_config": {
        "es": "Falta configurar: {gaps}. Abrí AJUSTES y cargalos.",
        "en": "Not configured yet: {gaps}. Open SETTINGS and fill them in.",
    },
    "ui.no_mic": {
        "es": "Sin micrófono: instalá sounddevice para hablar por voz.",
        "en": "No microphone: install sounddevice to talk by voice.",
    },
    "ui.no_stt": {
        "es": "Sin transcripción local: instalá faster-whisper, o escribí.",
        "en": "No local transcription: install faster-whisper, or type.",
    },
    "ui.saved": {"es": "Ajustes guardados. Reconectando…", "en": "Settings saved. Reconnecting…"},
    "ui.searching_devices": {"es": "Buscando dispositivos de audio…", "en": "Looking for audio devices…"},
    "ui.no_sounddevice": {
        "es": "Sin sounddevice: no puedo listar dispositivos.",
        "en": "No sounddevice: I cannot list devices.",
    },
    "ui.speak_now": {"es": "Hablá unos segundos…", "en": "Say something for a few seconds…"},
    "ui.playing_tone": {"es": "Reproduciendo un pitido…", "en": "Playing a tone…"},
    "ui.testing_model": {"es": "Probando el modelo…", "en": "Testing the model…"},
    "ui.model_ok": {"es": "✓ El modelo responde.", "en": "✓ The model answers."},
    "ui.testing_factory": {"es": "Probando la fábrica…", "en": "Testing the factory…"},
    "ui.test_mic": {"es": "Probar micrófono", "en": "Test microphone"},
    "ui.test_speaker": {"es": "Probar parlante", "en": "Test speaker"},
    "ui.refresh": {"es": "Refrescar", "en": "Refresh"},
    "ui.test_model": {"es": "Probar modelo", "en": "Test model"},
    "ui.test_factory": {"es": "Probar fábrica", "en": "Test factory"},
    "ui.model_url": {"es": "URL del modelo", "en": "Model URL"},
    "ui.model_name": {"es": "Modelo", "en": "Model"},
    "ui.model_key": {"es": "Clave del modelo", "en": "Model key"},
    "ui.factory_url": {"es": "URL de la fábrica", "en": "Factory URL"},
    "ui.voice_key": {"es": "Clave de voz (X-Voice-Key)", "en": "Voice key (X-Voice-Key)"},
    "ui.language": {"es": "Idioma", "en": "Language"},
    "ui.your_name": {"es": "Cómo te llamás vos", "en": "Your name"},
    "ui.mic": {"es": "Micrófono", "en": "Microphone"},
    "ui.speaker": {"es": "Audio de salida", "en": "Audio output"},
    "ui.briefing": {
        "es": "Leer la guía de la fábrica al arrancar",
        "en": "Read the factory guide at start-up",
    },
    "ui.voice_out": {"es": "Voz del asistente", "en": "Assistant voice"},
    "ui.voice_out_en": {
        "es": "Voz del asistente en inglés",
        "en": "Assistant voice, English",
    },
    "ui.offline": {"es": "no conectado", "en": "not connected"},
    "ui.stt_language": {"es": "Idioma al escuchar", "en": "Listening language"},
    "ui.stt_auto": {
        "es": "Automático (sigue la conversación)",
        "en": "Automatic (follows the conversation)",
    },
    "ui.save": {"es": "Guardar", "en": "Save"},
    "ui.cancel": {"es": "Cancelar", "en": "Cancel"},
    # -- factory client ----------------------------------------------------
    "model.answers": {"es": "{model} responde.", "en": "{model} answers."},
    "model.http": {"es": "HTTP {code} en {url}: {detail}", "en": "HTTP {code} at {url}: {detail}"},
    "model.unreachable": {
        "es": "no puedo alcanzar {url}: {reason}",
        "en": "cannot reach {url}: {reason}",
    },
    "model.timeout": {
        "es": "{url} no respondió en {seconds:.0f}s",
        "en": "{url} did not answer within {seconds:.0f}s",
    },
    "model.not_json": {
        "es": "la respuesta del modelo no es JSON",
        "en": "the model answered something that is not JSON",
    },
    "model.no_choices": {
        "es": "respuesta sin «choices»: {body}",
        "en": "answer without “choices”: {body}",
    },
    "factory.key_rejected": {
        "es": "la fábrica rechazó la clave de voz (revisá «voice_key» en los ajustes)",
        "en": "the factory rejected the voice key (check “voice_key” in the settings)",
    },
    "factory.no_voice": {
        "es": "la fábrica no tiene control por voz configurado (falta VOICE_API_KEY)",
        "en": "voice control is not configured in the factory (VOICE_API_KEY is missing)",
    },
    "factory.http": {"es": "HTTP {code} en {path}: {detail}", "en": "HTTP {code} at {path}: {detail}"},
    "factory.unreachable": {
        "es": "no puedo alcanzar la fábrica en {url}: {reason}",
        "en": "cannot reach the factory at {url}: {reason}",
    },
    "factory.timeout": {
        "es": "la fábrica no respondió en {seconds:.0f}s",
        "en": "the factory did not answer within {seconds:.0f}s",
    },
    "factory.not_json": {
        "es": "{url} no devolvió JSON (¿es la dirección de la API?); la respuesta "
        "empieza con {head}",
        "en": "{url} did not return JSON (is that the API address?); the answer "
        "starts with {head}",
    },
    "factory.unexpected": {
        "es": "la fábrica respondió un JSON inesperado",
        "en": "the factory answered with unexpected JSON",
    },
    "factory.connected": {"es": "conexión correcta", "en": "connection ok"},
}


def t(language: str | None, key: str, /, **fields) -> str:
    """The text for *key* in *language* (``es`` when anything is off)."""
    entries = _TEXTS.get(key)
    if entries is None:
        raise KeyError(f"texto sin traducir: {key}")
    template = entries.get(normalize(language), entries[DEFAULT])
    return template.format(**fields) if fields else template


def keys() -> list[str]:
    return sorted(_TEXTS)
