"""Command line entry point.

    b1                 open the window
    b1 --orb           open the compact orb (frameless, always on top)
    b1 --text          talk in the terminal, no microphone and no GUI
    b1 --guide         print the factory guide and exit
    b1 --check         report what is installed, what speaks and whether the services answer
    b1 --speak "hola"  make the voice say one sentence and exit
    b1 --language en   start the session in English (or es)
    b1 --init          write a config file with defaults, then exit

The flags mirror the situations this app is actually used in: demoing to a
room, working next to other windows, testing on a machine with no audio,
checking why nobody speaks, and setting it up for the first time.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from . import APP_NAME, __version__
from .assistant import build_assistant
from .config import Settings, config_file
from .fabrica import FactoryClient, FactoryError, guide_text, guide_title
from .i18n import normalize, t
from .vad import describe as describe_vad
from .speech import (
    ConsoleSpeaker,
    describe_voice,
    download_voices,
    mic_ready,
    stt_ready,
    voice_name,
    voices_dir,
)


def _build_parser(language: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="b1",
        description=f"{APP_NAME} — {t(language, 'app.description')}",
        add_help=False,
    )
    parser.add_argument(
        "-h", "--help", action="help", help=t(language, "app.help_help")
    )
    # argparse writes "options:" and the help of ``-h`` itself; both are text
    # the person reads, so they follow the same language as the rest.
    parser._optionals.title = t(language, "app.options")  # noqa: SLF001
    parser.add_argument("--gui", action="store_true", help=t(language, "app.help_gui"))
    parser.add_argument("--orb", action="store_true", help=t(language, "app.help_orb"))
    parser.add_argument("--text", action="store_true", help=t(language, "app.help_text"))
    parser.add_argument("--guide", action="store_true", help=t(language, "app.help_guide"))
    parser.add_argument("--check", action="store_true", help=t(language, "app.help_check"))
    parser.add_argument(
        "--speak",
        default=None,
        metavar=t(language, "app.metavar_text"),
        help=t(language, "app.help_speak"),
    )
    parser.add_argument("--init", action="store_true", help=t(language, "app.help_init"))
    parser.add_argument("--voices", action="store_true", help=t(language, "app.help_voices"))
    parser.add_argument(
        "--language",
        default=None,
        metavar="es|en",
        help=t(language, "app.help_language"),
    )
    parser.add_argument(
        "--no-briefing", action="store_true", help=t(language, "app.help_no_briefing")
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser


def _parser(language: str = "es") -> argparse.ArgumentParser:
    return _build_parser(normalize(language))


def _parse(argv: list[str] | None) -> tuple[argparse.Namespace, str]:
    """Parse twice: the saved language picks the language of the help text.

    The first pass runs without ``-h``: asking for help must not freeze the
    screen in the saved language before ``--language`` has been read.
    """
    saved = Settings.load()
    arguments = list(sys.argv[1:] if argv is None else argv)
    quiet = [item for item in arguments if item not in ("-h", "--help")]
    first = _build_parser(saved.language).parse_known_args(quiet)[0]
    language = normalize(first.language) if first.language else normalize(saved.language)
    return _build_parser(language).parse_args(arguments), language


def main(argv: list[str] | None = None) -> int:
    args, requested = _parse(argv)
    settings = Settings.load()
    settings.language = requested
    if args.no_briefing:
        settings.briefing = False
    language = settings.language

    if args.init:
        path = settings.save()
        print(t(language, "app.init_written", path=path))
        for gap in settings.missing():
            print(t(language, "app.init_missing", gap=gap))
        return 0

    if args.guide:
        print(guide_title(language))
        print()
        print(guide_text(language))
        return 0

    if args.check:
        return _check(settings)

    if args.voices:
        return _download_voices(settings)

    if args.speak:
        speaker, description = describe_voice(language=language, settings=settings)
        print(t(language, "app.check_tts"), description)
        speaker.say(args.speak)
        return 0

    if args.text:
        return asyncio.run(_text_mode(settings))

    if not _qt_available():
        print(t(language, "app.qt_missing"))
        print()
        return asyncio.run(_text_mode(settings))

    try:
        from .ui import run_gui
    except Exception as exc:  # noqa: BLE001 - a missing Qt must not stop the app
        print(t(language, "app.window_failed", detail=exc))
        print()
        return asyncio.run(_text_mode(settings))

    return run_gui(settings, compact=args.orb)


def _download_voices(settings: Settings) -> int:
    """Fetch Kokoro and the configured Piper voices once, to speak offline."""
    from . import kokoro  # noqa: PLC0415 - optional engine

    language = settings.language
    failed = 0
    if kokoro.engine_installed():
        print(t(language, "app.kokoro_downloading", path=kokoro.kokoro_dir()))
        for name, error in kokoro.download().items():
            if error:
                failed += 1
                print(f" ✕ {name}: {error}")
            else:
                print(t(language, "app.voices_ok", name=name))
    else:
        print(t(language, "app.kokoro_missing"))
    names = [voice_name(settings.tts_voice), voice_name(settings.tts_voice_en)]
    names = [name for name in names if name]
    if not names:
        print(t(language, "app.voices_paths_set"))
        return 1 if failed else 0
    print(t(language, "app.voices_downloading", names=", ".join(names)))
    results = download_voices(names)
    for name, error in results.items():
        if error:
            failed += 1
            print(f" ✕ {name}: {error}")
        else:
            print(t(language, "app.voices_ok", name=name))
    print(t(language, "app.voices_where", path=voices_dir()))
    return 1 if failed else 0


def _qt_available() -> bool:
    try:
        import PyQt6  # noqa: F401,PLC0415 - presence check only
    except Exception:  # noqa: BLE001
        return False
    return True


def _check(settings: Settings) -> int:
    language = settings.language
    yes = t(language, "app.yes")
    speaker, voice = describe_voice(language=language, settings=settings)
    rows: list[tuple[str, str]] = [
        ("app.check_config", str(config_file())),
        ("app.check_model", f"{settings.model} @ {settings.model_url_clean()}"),
        ("app.check_factory", settings.factory_url_clean()),
        ("app.check_language", language),
        ("app.check_mic", yes if mic_ready() else t(language, "app.no_mic")),
        ("app.check_stt", yes if stt_ready() else t(language, "app.no_stt")),
        ("app.check_vad", describe_vad(settings.vad, language)),
        ("app.check_tts", voice),
        ("app.check_qt", yes if _qt_available() else t(language, "app.no_qt")),
        (
            "app.check_key",
            t(language, "app.key_missing") if settings.missing() else t(language, "app.key_loaded"),
        ),
    ]
    labels = [t(language, key) for key, _value in rows]
    width = max(len(label) for label in labels) + 1
    print(f"{APP_NAME} {__version__}")
    for (key, value), label in zip(rows, labels):
        print(f"{label:<{width}}{value}")

    if mic_ready():
        from . import devices  # noqa: PLC0415 - only needed for the report

        prefix = " " * width
        print(
            f"{prefix}{t(language, 'app.check_input')} "
            f"{devices.describe(devices.INPUT, settings.mic_device, language=language)}"
        )
        print(
            f"{prefix}{t(language, 'app.check_output')} "
            f"{devices.describe(devices.OUTPUT, settings.speaker_device, language=language)}"
        )
    if isinstance(speaker, ConsoleSpeaker):
        print(f"{' ' * width}{t(language, 'speech.console_only')}")

    gaps = settings.missing()
    if not gaps:
        from .llm import model_from_settings

        client = model_from_settings(settings)
        ok, detail = client.ping()
        print(f"{' ' * width}{'✓' if ok else '✕'} {detail}")

    factory = FactoryClient(settings.factory_url_clean(), settings.voice_key, language=language)
    try:
        ok, detail = factory.ping()
        print(f"{' ' * width}{'✓' if ok else '✕'} {detail}")
    except FactoryError as exc:
        print(f"{' ' * width}✕ {exc}")
    return 0 if not gaps else 1



async def _text_mode(settings: Settings) -> int:
    language = settings.language
    assistant = build_assistant(settings)
    assistant.speaker = ConsoleSpeaker(language)
    await assistant.startup()
    gaps = settings.missing()
    if gaps:
        print(t(language, "app.text_no_model", gaps=", ".join(gaps)))
    print(t(language, "app.text_hint"))
    print()
    while True:
        try:
            line = await asyncio.to_thread(input, t(assistant.language, "app.text_prompt"))
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line.strip().lower() in {"salir", "exit", "quit"}:
            return 0
        if not line.strip():
            continue
        await assistant.handle(line)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
