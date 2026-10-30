"""The orb: the only graphic in the app, drawn with QPainter.

Three rings, each one reacting to a different thing — microphone level while
listening, a slow sweep while thinking, a breathing glow while speaking — so the
state is readable at a glance and in the corner of an eye.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QConicalGradient, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

ACCENTS = {
    "idle": QColor(90, 170, 255),
    "listening": QColor(80, 220, 170),
    "thinking": QColor(255, 190, 90),
    "speaking": QColor(150, 140, 255),
    "error": QColor(255, 110, 110),
}


class Orb(QWidget):
    def __init__(self, size: int = 190, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._state = "idle"
        self._level = 0.0
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # -- public API ---------------------------------------------------------
    def set_state(self, state: str) -> None:
        if state in ACCENTS and state != self._state:
            self._state = state
            self.update()

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))

    # -- animation ----------------------------------------------------------
    def _tick(self) -> None:
        speed = {"idle": 0.012, "listening": 0.05, "thinking": 0.09, "speaking": 0.06}
        self._phase = (self._phase + speed.get(self._state, 0.02)) % (2 * math.pi)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = QPointF(self.width() / 2, self.height() / 2)
        radius = min(self.width(), self.height()) / 2 - 12
        accent = ACCENTS[self._state]

        glow = QRadialGradient(center, radius)
        inner = QColor(accent)
        inner.setAlpha(120 + int(60 * self._level))
        glow.setColorAt(0.0, inner)
        edge = QColor(accent)
        edge.setAlpha(0)
        glow.setColorAt(1.0, edge)
        painter.setBrush(glow)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, radius, radius)

        core = 1.0 + (0.10 * self._level if self._state == "listening" else 0.0)
        core += 0.03 * math.sin(self._phase) if self._state == "speaking" else 0.0
        painter.setBrush(QColor(12, 18, 30, 235))
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 200), 2))
        painter.drawEllipse(center, radius * 0.62 * core, radius * 0.62 * core)

        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 190), 2))
        for index, scale in enumerate((0.72, 0.83, 0.94)):
            offset = self._phase * (1 if index % 2 == 0 else -1)
            span = 70 + 20 * self._level + (10 if self._state != "idle" else 0)
            painter.drawArc(
                QRectF(
                    center.x() - radius * scale,
                    center.y() - radius * scale,
                    radius * scale * 2,
                    radius * scale * 2,
                ),
                int(math.degrees(offset)) * 16,
                int(span) * 16,
            )

        if self._state == "thinking":
            sweep = QConicalGradient(center, math.degrees(self._phase))
            sweep.setColorAt(0.0, QColor(accent))
            sweep.setColorAt(0.25, QColor(accent.red(), accent.green(), accent.blue(), 20))
            painter.setBrush(sweep)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(center, radius * 0.34, radius * 0.34)
        else:
            bars = 4
            width = radius * 0.10
            span = radius * 0.34
            for index in range(bars):
                amount = 0.35 + 0.65 * abs(math.sin(self._phase + index * 0.9))
                height = span * (0.35 + 0.65 * self._level) * amount
                x = center.x() - (bars - 1) * width * 0.6 + index * width * 1.2
                painter.setBrush(accent)
                painter.drawRoundedRect(
                    QRectF(x - width * 0.28, center.y() - height / 2, width * 0.56, height),
                    width * 0.28,
                    width * 0.28,
                )
        painter.end()
