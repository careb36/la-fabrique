"""The desktop window: orb, transcript, guide panel and the settings dialog.

Threading rule: Qt stays on the main thread; the assistant runs in one asyncio
loop owned by a daemon thread; microphone capture and STT run in a short-lived
worker per utterance. Everything crosses back through signals, so no widget is
ever touched from a worker.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__, devices
from ..assistant import Assistant, build_assistant
from ..config import Settings
from ..i18n import normalize, t
from ..speech import make_speaker, make_transcriber, mic_ready, stt_ready
from .orb import Orb

OVERLAY_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
)

STYLE = """
QWidget { background: #0b1018; color: #dfe7f3; font-size: 13px; }
QTextEdit, QTextBrowser { background: #0f1520; border: 1px solid #1e2a3d; border-radius: 10px; }
QPushButton { background: #16233a; border: 1px solid #24354f; border-radius: 8px; padding: 7px 14px; }
QPushButton:hover { background: #1d2e4b; }
QPushButton:disabled { color: #61708a; }
QPushButton#mic { background: #1b3b52; border: 1px solid #2f6f92; font-weight: 600; }
QLineEdit, QComboBox { background: #0f1520; border: 1px solid #24354f; border-radius: 8px; padding: 6px; }
QLabel#state { color: #8ea6c8; }
QLabel#brand { color: #9fc2ee; font-size: 15px; font-weight: 600; }
"""


class Bridge(QObject):
    """Turns assistant events into Qt signals (safe across threads)."""

    guide = pyqtSignal(str, str)
    reply = pyqtSignal(str)
    # A streamed answer: each sentence as it is spoken, then its end.
    reply_part = pyqtSignal(str)
    reply_done = pyqtSignal(str)
    state = pyqtSignal(str)
    tool = pyqtSignal(str, str)
    error = pyqtSignal(str)
    factory = pyqtSignal(bool, dict)
    language = pyqtSignal(str)

    def push(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "guide":
            self.guide.emit(str(event.get("title")), str(event.get("text")))
        elif kind == "reply" and event.get("streamed"):
            self.reply_done.emit(str(event.get("text")))
        elif kind == "reply":
            self.reply.emit(str(event.get("text")))
        elif kind == "reply_part":
            self.reply_part.emit(str(event.get("text")))
        elif kind == "state":
            self.state.emit(str(event.get("value")))
        elif kind == "tool":
            self.tool.emit(str(event.get("name")), str(event.get("result")))
        elif kind == "error":
            self.error.emit(str(event.get("message")))
        elif kind == "factory":
            self.factory.emit(bool(event.get("ok")), dict(event.get("data") or {}))
        elif kind == "language":
            self.language.emit(str(event.get("value")))


class LoopRunner:
    """One asyncio loop on its own thread, for the assistant's lifetime."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="b1-asyncio", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def close(self) -> None:
        """Cancel what is still running, then stop the loop.

        Without the cancellation asyncio prints "Task was destroyed but it is
        pending" on exit: the startup turn and any speak() continue running
        after the window is gone.
        """

        async def drain(tasks) -> None:
            await asyncio.gather(*tasks, return_exceptions=True)
            self.loop.stop()

        def cancel_all() -> None:
            tasks = [task for task in asyncio.all_tasks(self.loop) if not task.done()]
            for task in tasks:
                task.cancel()
            if tasks:
                self.loop.create_task(drain(tasks))
            else:
                self.loop.stop()

        try:
            self.loop.call_soon_threadsafe(cancel_all)
        except RuntimeError:  # the loop was already closed
            return
        self._thread.join(timeout=2.0)


class VoiceWorker(QThread):
    """Record one phrase, transcribe it, hand the text and its language back."""

    heard = pyqtSignal(str, str)
    failed = pyqtSignal(str)
    level = pyqtSignal(float)

    def __init__(
        self,
        transcriber,
        device: str = "",
        language: str = "es",
        parent=None,
        vad: str = "silero",
    ) -> None:
        super().__init__(parent)
        self.transcriber = transcriber
        self.device = device
        self.vad = vad
        self.language = normalize(language)
        self._stop = threading.Event()

    def run(self) -> None:  # noqa: D102 - QThread entry point
        from ..audio import Endpointer, Microphone
        from ..vad import load_detector

        try:
            endpointer = Endpointer(detector=load_detector(self.vad))
            with Microphone(device=self.device, language=self.language) as mic:
                pcm = mic.listen(
                    endpointer, on_level=self.level.emit, should_stop=self._stop.is_set
                )
            text = self.transcriber.transcribe(pcm or b"", language=self.language) if pcm else ""
            if text:
                detected = getattr(self.transcriber, "last_language", "") or self.language
                self.heard.emit(text, detected)
            elif self._stop.is_set():
                self.failed.emit(t(self.language, "audio.stopped"))
            else:
                self.failed.emit(t(self.language, "audio.no_speech"))
        except Exception as exc:  # noqa: BLE001 - surfaced in the log, not a crash
            self.failed.emit(str(exc))

    def stop(self) -> None:
        self._stop.set()


class AudioProbe(QThread):
    """Runs a blocking audio test off the UI thread and reports one sentence."""

    done = pyqtSignal(str)
    level = pyqtSignal(float)

    def __init__(self, work, parent=None) -> None:
        super().__init__(parent)
        self._work = work

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            result = self._work(self.level.emit)
        except Exception as exc:  # noqa: BLE001 - shown in the panel
            self.done.emit(f"✕ {exc}")
            return
        mark = "✓ " if result.get("ok") else "✕ "
        self.done.emit(mark + str(result.get("verdict", "")))



class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.language = normalize(settings.language)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        self.form = QFormLayout()

        self.base_url = QLineEdit(settings.model_base_url)
        self.model = QLineEdit(settings.model)
        self.api_key = QLineEdit(settings.model_api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.factory_url = QLineEdit(settings.factory_url)
        self.voice_key = QLineEdit(settings.voice_key)
        self.voice_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.language_box = QComboBox()
        self.language_box.addItems(["es", "en"])
        self.language_box.setCurrentText(self.language)
        self.assistant_name = QLineEdit(settings.assistant_name)
        self.briefing = QCheckBox()
        self.briefing.setChecked(settings.briefing)
        self.tts_voice = QLineEdit(settings.tts_voice)
        self.tts_voice_en = QLineEdit(settings.tts_voice_en)
        self.stt_language = QComboBox()
        for code in ("auto", "es", "en"):
            self.stt_language.addItem(code, code)
        self.stt_language.setCurrentIndex(
            max(0, self.stt_language.findData(settings.stt_language))
        )
        self.mic = QComboBox()
        self.speaker = QComboBox()
        self.probe: AudioProbe | None = None

        self.rows = {
            "model_url": QLabel(),
            "model_name": QLabel(),
            "model_key": QLabel(),
            "factory_url": QLabel(),
            "voice_key": QLabel(),
            "language": QLabel(),
            "stt_language": QLabel(),
            "your_name": QLabel(),
            "voice_es": QLabel(),
            "voice_en": QLabel(),
            "mic": QLabel(),
            "speaker": QLabel(),
        }
        self._fill_form()
        layout.addLayout(self.form)

        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setVisible(False)
        layout.addWidget(self.meter)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.test_mic = QPushButton()
        self.test_speaker = QPushButton()
        self.rescan = QPushButton()
        self.test_model = QPushButton()
        self.test_factory = QPushButton()
        self.test_mic.clicked.connect(self._test_mic)
        self.test_speaker.clicked.connect(self._test_speaker)
        self.rescan.clicked.connect(lambda: self._fill_devices(self.settings, refresh=True))
        self.test_model.clicked.connect(self._test_model)
        self.test_factory.clicked.connect(self._test_factory)
        for button in (
            self.test_mic,
            self.test_speaker,
            self.rescan,
            self.test_model,
            self.test_factory,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        layout.addWidget(self.box)

        self.language_box.currentTextChanged.connect(self._switch_language)
        self._retranslate()
        self._fill_devices(settings)

    # -- language -----------------------------------------------------------
    def _switch_language(self, code: str) -> None:
        self.language = normalize(code)
        self._retranslate()

    def _retranslate(self) -> None:
        language = self.language
        self.setWindowTitle(t(language, "ui.title"))
        for key, label in (
            ("model_url", "ui.model_url"),
            ("model_name", "ui.model_name"),
            ("model_key", "ui.model_key"),
            ("factory_url", "ui.factory_url"),
            ("voice_key", "ui.voice_key"),
            ("language", "ui.language"),
            ("stt_language", "ui.stt_language"),
            ("your_name", "ui.your_name"),
            ("voice_es", "ui.voice_out"),
            ("voice_en", "ui.voice_out_en"),
            ("mic", "ui.mic"),
            ("speaker", "ui.speaker"),
        ):
            self.rows[key].setText(t(language, label))
        self.briefing.setText(t(language, "ui.briefing"))
        for button, key in (
            (self.test_mic, "ui.test_mic"),
            (self.test_speaker, "ui.test_speaker"),
            (self.rescan, "ui.refresh"),
            (self.test_model, "ui.test_model"),
            (self.test_factory, "ui.test_factory"),
        ):
            button.setText(t(language, key))
        self.stt_language.setItemText(0, t(language, "ui.stt_auto"))
        save = self.box.button(QDialogButtonBox.StandardButton.Save)
        cancel = self.box.button(QDialogButtonBox.StandardButton.Cancel)
        if save is not None:
            save.setText(t(language, "ui.save"))
        if cancel is not None:
            cancel.setText(t(language, "ui.cancel"))

    def _fill_form(self) -> None:
        """Rows in the order the dictionary of labels declares them."""
        self.form.addRow(self.rows["model_url"], self.base_url)
        self.form.addRow(self.rows["model_name"], self.model)
        self.form.addRow(self.rows["model_key"], self.api_key)
        self.form.addRow(self.rows["factory_url"], self.factory_url)
        self.form.addRow(self.rows["voice_key"], self.voice_key)
        self.form.addRow(self.rows["language"], self.language_box)
        self.form.addRow(self.rows["stt_language"], self.stt_language)
        self.form.addRow(self.rows["your_name"], self.assistant_name)
        self.form.addRow(self.rows["voice_es"], self.tts_voice)
        self.form.addRow(self.rows["voice_en"], self.tts_voice_en)
        self.form.addRow(self.rows["mic"], self.mic)
        self.form.addRow(self.rows["speaker"], self.speaker)
        self.form.addRow("", self.briefing)

    # -- devices ------------------------------------------------------------
    @staticmethod
    def _chosen(combo: QComboBox) -> str:
        """The saved value behind the visible label ("" is system default)."""
        return str(combo.currentData() or "")

    def _fill_devices(self, settings: Settings, refresh: bool = False) -> None:
        self.status.setText(t(self.language, "ui.searching_devices"))
        QApplication.processEvents()
        default_label = devices.default_label(self.language)
        for combo, kind, saved in (
            (self.mic, devices.INPUT, settings.mic_device),
            (self.speaker, devices.OUTPUT, settings.speaker_device),
        ):
            combo.clear()
            combo.addItem(default_label, devices.DEFAULT_VALUE)
            for name in devices.list_devices(kind, refresh=refresh):
                combo.addItem(name, name)
            # A saved device that has since been unplugged stays visible as a
            # choice, so the value is not lost by merely opening this window.
            if saved and combo.findData(saved) < 0:
                combo.addItem(f"{saved} ({t(self.language, 'ui.offline')})", saved)
            combo.setCurrentIndex(max(0, combo.findData(saved)))
        if not devices.available():
            self.status.setText(t(self.language, "ui.no_sounddevice"))
        else:
            self.status.setText("")

    def _test_mic(self) -> None:
        name = self._chosen(self.mic)
        language = self.language
        self.status.setText(t(language, "ui.speak_now"))
        self.meter.setVisible(True)
        self.meter.setValue(0)
        self.probe = AudioProbe(
            lambda on_level: devices.probe_microphone(
                name, 3.0, on_level, language=language
            ),
            self,
        )
        self.probe.level.connect(lambda value: self.meter.setValue(int(value * 100)))
        self.probe.done.connect(self._probe_done)
        self.probe.start()

    def _test_speaker(self) -> None:
        name = self._chosen(self.speaker)
        language = self.language
        self.status.setText(t(language, "ui.playing_tone"))
        self.probe = AudioProbe(lambda _level: devices.tone(name, language=language), self)
        self.probe.done.connect(self.status.setText)
        self.probe.start()

    def _probe_done(self, sentence: str) -> None:
        self.meter.setValue(0)
        self.status.setText(sentence)

    # -- actions ------------------------------------------------------------
    def _test_model(self) -> None:
        from ..llm import ModelError, OpenAICompatModel

        self.status.setText(t(self.language, "ui.testing_model"))
        QApplication.processEvents()
        client = OpenAICompatModel(
            self.base_url.text().strip(),
            self.api_key.text().strip(),
            self.model.text().strip(),
            language=self.language,
        )
        try:
            client.complete([{"role": "user", "content": "ping"}], [])
        except ModelError as exc:
            self.status.setText(f"✕ {exc}")
            return
        self.status.setText(t(self.language, "ui.model_ok"))

    def _test_factory(self) -> None:
        from ..fabrica import FactoryClient, FactoryError

        self.status.setText(t(self.language, "ui.testing_factory"))
        QApplication.processEvents()
        client = FactoryClient(
            self.factory_url.text().strip(),
            self.voice_key.text().strip(),
            language=self.language,
        )
        try:
            ok, sentence = client.ping()
        except FactoryError as exc:
            self.status.setText(f"✕ {exc}")
            return
        self.status.setText(("✓ " if ok else "✕ ") + sentence)

    def values(self) -> Settings:
        return replace(
            self.settings,
            model_base_url=self.base_url.text().strip(),
            model=self.model.text().strip(),
            model_api_key=self.api_key.text().strip(),
            factory_url=self.factory_url.text().strip(),
            voice_key=self.voice_key.text().strip(),
            language=self.language_box.currentText(),
            assistant_name=self.assistant_name.text().strip() or "B1",
            briefing=self.briefing.isChecked(),
            stt_language=str(self.stt_language.currentData() or "auto"),
            tts_voice=self.tts_voice.text().strip(),
            tts_voice_en=self.tts_voice_en.text().strip(),
            mic_device=self._chosen(self.mic),
            speaker_device=self._chosen(self.speaker),
        )


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, *, compact: bool = False) -> None:
        super().__init__()
        self.settings = settings
        self.compact = compact
        self._live_reply: str | None = None
        self.language = normalize(settings.language)
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(340, 420) if compact else self.resize(980, 660)
        self.setStyleSheet(STYLE)
        if compact:
            self._make_overlay()

        self.bridge = Bridge()
        self.runner = LoopRunner()
        self.assistant: Assistant = build_assistant(settings, on_event=self.bridge.push)
        self.assistant.speaker = self._speaker(settings)
        self.transcriber = make_transcriber(
            settings.stt_model, language=settings.speech_language()
        )
        self.voice_worker: VoiceWorker | None = None
        # Warm the device cache off the UI thread so the picker opens instantly.
        for kind in (devices.INPUT, devices.OUTPUT):
            threading.Thread(target=devices.list_devices, args=(kind,), daemon=True).start()

        self._build_ui()
        self._connect()
        self._retranslate()
        self._start()

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _speaker(settings: Settings):
        """Piper, the system voice or the console — in the session language."""
        language = normalize(settings.language)
        speaker = make_speaker(
            settings.tts_voice,
            settings.speaker_device,
            voice_en=settings.tts_voice_en,
            language=language,
        )
        try:
            speaker.language = language
        except Exception:  # noqa: BLE001 - a read-only speaker is still a speaker
            pass
        return speaker

    # -- layout -------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(18)

        left = QVBoxLayout()
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        brand.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        left.addWidget(brand)

        self.orb = Orb(200 if not self.compact else 150)
        left.addWidget(self.orb, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.state_label = QLabel()
        self.state_label.setObjectName("state")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        left.addWidget(self.state_label)

        self.mic_button = QPushButton()
        self.mic_button.setObjectName("mic")
        self.mic_button.setMinimumHeight(40)
        left.addWidget(self.mic_button)

        self.input = QLineEdit()
        left.addWidget(self.input)

        row = QHBoxLayout()
        self.guide_button = QPushButton()
        self.settings_button = QPushButton()
        row.addWidget(self.guide_button)
        row.addWidget(self.settings_button)
        left.addLayout(row)
        left.addStretch(1)
        root.addLayout(left)

        right = QVBoxLayout()
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Segoe UI", 11))
        right.addWidget(self.log, stretch=3)

        self.panel = QTextBrowser()
        self.panel.setOpenExternalLinks(True)
        right.addWidget(self.panel, stretch=2)
        if self.compact:
            self.log.hide()
            self.panel.hide()
        root.addLayout(right, stretch=3)

        self.setCentralWidget(central)

    def _connect(self) -> None:
        self.mic_button.clicked.connect(self._toggle_mic)
        self.input.returnPressed.connect(self._send_typed)
        self.guide_button.clicked.connect(self._show_guide)
        self.settings_button.clicked.connect(self._open_settings)

        self.bridge.guide.connect(self._on_guide)
        self.bridge.reply.connect(self._on_reply)
        self.bridge.reply_part.connect(self._on_reply_part)
        self.bridge.reply_done.connect(lambda _text: self._close_live_reply())
        self.bridge.state.connect(self._on_state)
        self.bridge.tool.connect(self._on_tool)
        self.bridge.error.connect(self._on_error)
        self.bridge.factory.connect(self._on_factory)
        self.bridge.language.connect(self._on_language)

    def _retranslate(self) -> None:
        """Every fixed label, in the language being spoken right now."""
        language = self.language
        if self.voice_worker is None:
            self.mic_button.setText(t(language, "ui.talk"))
        self.input.setPlaceholderText(t(language, "ui.type_placeholder"))
        self.guide_button.setText(t(language, "ui.guide"))
        self.settings_button.setText(t(language, "ui.settings"))
        self.state_label.setText(t(language, "ui.state_idle"))
        self.statusBar().showMessage(t(language, "ui.status_ready"))

    def _start(self) -> None:
        self._warn_missing()
        self.runner.submit(self.assistant.startup())

    def _warn_missing(self) -> None:
        language = self.language
        gaps = self.settings.missing()
        if gaps:
            self._append(
                t(language, "ui.role_system"),
                t(language, "ui.missing_config", gaps=", ".join(gaps)),
            )
        if not mic_ready():
            self._append(t(language, "ui.role_system"), t(language, "ui.no_mic"))
        if not stt_ready():
            self._append(t(language, "ui.role_system"), t(language, "ui.no_stt"))

    # -- voice --------------------------------------------------------------
    def _toggle_mic(self) -> None:
        if self.voice_worker is not None:
            # Second click: stop recording and transcribe what was heard so far.
            self.voice_worker.stop()
            self.state_label.setText(t(self.language, "ui.state_thinking"))
            return
        worker = VoiceWorker(
            self.transcriber,
            self.settings.mic_device,
            self.language,
            self,
            vad=getattr(self.settings, "vad", "silero"),
        )
        worker.heard.connect(self._on_heard)
        worker.failed.connect(self._on_error)
        worker.level.connect(self.orb.set_level)
        worker.finished.connect(self._on_worker_done)
        self.voice_worker = worker
        self.orb.set_state("listening")
        self.state_label.setText(t(self.language, "ui.state_listening"))
        self.mic_button.setText(t(self.language, "ui.listening"))
        worker.start()

    def _on_worker_done(self) -> None:
        self.voice_worker = None
        self.mic_button.setText(t(self.language, "ui.talk"))
        if self.orb._state == "listening":
            self.orb.set_state("idle")
            self.state_label.setText(t(self.language, "ui.state_idle"))

    def _on_heard(self, text: str, language: str = "") -> None:
        self._append(t(self.language, "ui.role_you"), text)
        self.runner.submit(self.assistant.handle(text, language=language))

    def _send_typed(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._append(t(self.language, "ui.role_you"), text)
        self.runner.submit(self.assistant.handle(text))

    def _show_guide(self) -> None:
        from ..fabrica import guide_text, guide_title

        language = self.language
        self.panel.setPlainText(f"{guide_title(language)}\n\n{guide_text(language)}")

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.settings = dialog.values()
        self.settings.save()
        self._append(t(self.language, "ui.role_system"), t(self.language, "ui.saved"))
        try:
            self.assistant.speaker.stop()
        except Exception:  # noqa: BLE001 - nothing was playing.
            pass
        self.assistant = build_assistant(self.settings, on_event=self.bridge.push)
        self.assistant.speaker = self._speaker(self.settings)
        self.transcriber = make_transcriber(
            self.settings.stt_model, language=self.settings.speech_language()
        )
        self.language = normalize(self.settings.language)
        self.assistant.set_language(self.language)
        self._retranslate()
        self._warn_missing()
        self.runner.submit(self.assistant.startup())

    # -- bridge handlers ----------------------------------------------------
    def _on_guide(self, title: str, text: str) -> None:
        self.panel.setPlainText(f"{title}\n\n{text}")

    def _on_reply(self, text: str) -> None:
        self._append(self.settings.assistant_name or "B1", text)

    def _on_reply_part(self, text: str) -> None:
        """Grow the answer on screen as each sentence is spoken."""
        who = self.settings.assistant_name or "B1"
        first = self._live_reply is None
        self._live_reply = text if first else f"{self._live_reply} {text}"
        if self.compact:
            self.statusBar().showMessage(f"{who}: {self._live_reply}"[:200])
            return
        self._insert(f"\n{who}: {text}" if first else f" {text}")

    def _close_live_reply(self) -> None:
        if self._live_reply is None:
            return
        self._live_reply = None
        if not self.compact:
            self._insert("\n")

    def _on_state(self, value: str) -> None:
        self.orb.set_state(value)
        self.state_label.setText(
            {
                "thinking": t(self.language, "ui.state_thinking"),
                "speaking": t(self.language, "ui.state_speaking"),
                "listening": t(self.language, "ui.state_listening"),
                "idle": t(self.language, "ui.state_idle"),
            }.get(value, value)
        )

    def _on_language(self, code: str) -> None:
        """The assistant switched language: the window follows in the same turn."""
        if normalize(code) == self.language:
            return
        self.language = normalize(code)
        # In memory only: the saved ``language`` is the one the app starts in,
        # and a conversation should not rewrite the file behind the person.
        self.settings.language = self.language
        self._retranslate()
        self._show_guide()

    def _on_tool(self, name: str, result: str) -> None:
        self.statusBar().showMessage(f"{t(self.language, 'ui.role_tool').lower()}: {name}")
        role = (
            t(self.language, "ui.role_factory")
            if name.startswith("factory")
            else t(self.language, "ui.role_tool")
        )
        self._append(role, result[:400])

    def _on_error(self, message: str) -> None:
        self._append(t(self.language, "ui.role_system"), message)
        self.orb.set_state("error")
        self.statusBar().showMessage(message[:120])

    def _on_factory(self, ok: bool, data: dict) -> None:
        bits = [
            f"{key}: {value}"
            for key, value in data.items()
            if key in ("sprint", "sprint_name", "progress", "pending", "files", "seconds")
        ]
        if bits:
            self.statusBar().showMessage(" · ".join(str(b) for b in bits)[:200])

    def _make_overlay(self) -> None:
        """Frameless, on top of everything: the orb alone, no title bar."""
        self.setWindowFlags(OVERLAY_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _append(self, who: str, text: str) -> None:
        self._close_live_reply()
        if self.compact:
            self.statusBar().showMessage(f"{who}: {text}"[:200])
            return
        self._insert(f"\n{who}: {text}\n")

    def _insert(self, text: str) -> None:
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log.setTextCursor(cursor)
        self.log.insertPlainText(text)
        self.log.ensureCursorVisible()

    # -- teardown -----------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        try:
            self.assistant.speaker.stop()
        except Exception:  # noqa: BLE001
            pass
        if self.voice_worker is not None:
            self.voice_worker.stop()
            self.voice_worker.wait(1500)
        self.runner.close()
        super().closeEvent(event)


def run_gui(settings: Settings, *, compact: bool = False) -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(settings, compact=compact)
    window.show()
    return app.exec()

