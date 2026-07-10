"""Rendering primitives for the usage overlay."""

from __future__ import annotations

import time

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen

from collector.models import UsageSnapshot, UsageWindow


PANEL = QColor("#17191F")
PANEL.setAlpha(242)
TEXT = QColor("#F7F8FA")
MUTED = QColor("#A9B0BA")
TRACK = QColor("#353A43")
FIVE_HOUR = QColor("#32B6FF")
SEVEN_DAY = QColor("#FFC857")
WARNING = QColor("#FF6B6B")


def system_font(
    size: int, weight: QFont.Weight = QFont.Weight.Normal, fixed: bool = False
) -> QFont:
    return QFont("Menlo" if fixed else ".AppleSystemUIFont", size, weight)


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days}d {hours:02d}:{minutes:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_day_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86_400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    return f"{days}d {hours:02d}:{minutes:02d}"


def format_tokens(tokens: int) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.1f}K"
    return str(tokens)


def remaining_seconds(window: UsageWindow, collected_at: float) -> int:
    if window.reset_at is not None:
        return max(0, int(window.reset_at - time.time()))
    elapsed = max(0, time.time() - collected_at)
    return max(0, int(window.reset_seconds - elapsed))


class UsageRenderer:
    def paint(self, painter: QPainter, bounds: QRectF, snapshot: UsageSnapshot) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(PANEL)
        painter.drawRoundedRect(bounds.adjusted(1, 1, -1, -1), 8, 8)

        if not snapshot.available:
            self._draw_unavailable(painter, bounds)
            return

        self._draw_title(painter, bounds)
        center_x = bounds.center().x()
        ring_top = bounds.top() + 48
        outer = QRectF(center_x - 69, ring_top, 138, 138)
        inner = outer.adjusted(22, 22, -22, -22)
        self._draw_ring(painter, outer, snapshot.five_hour, FIVE_HOUR, 10)
        self._draw_ring(painter, inner, snapshot.seven_day, SEVEN_DAY, 8)

        five_value = self._main_value(snapshot.five_hour)
        seven_value = self._window_value(snapshot.seven_day)
        painter.setPen(TEXT)
        painter.setFont(system_font(18, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(center_x - 45, ring_top + 48, 90, 28),
            Qt.AlignmentFlag.AlignCenter,
            five_value,
        )
        painter.setPen(MUTED)
        painter.setFont(system_font(10, QFont.Weight.Medium))
        painter.drawText(
            QRectF(center_x - 45, ring_top + 76, 90, 18),
            Qt.AlignmentFlag.AlignCenter,
            f"7d  {seven_value}",
        )

        self._draw_legend(painter, bounds, snapshot)

    @staticmethod
    def _main_value(window: UsageWindow | None) -> str:
        if window and window.used_percent is not None:
            return f"{round(100 - window.used_percent)}%"
        return format_tokens(window.used_tokens if window else 0)

    @staticmethod
    def _window_value(window: UsageWindow | None) -> str:
        if window and window.used_percent is not None:
            return f"{round(100 - window.used_percent)}%"
        return f"{format_tokens(window.used_tokens if window else 0)} tok"

    def _draw_title(self, painter: QPainter, bounds: QRectF) -> None:
        painter.setPen(TEXT)
        painter.setFont(system_font(13, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(bounds.left() + 16, bounds.top() + 12, bounds.width() - 32, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "Codex usage",
        )

    def _draw_ring(
        self,
        painter: QPainter,
        rect: QRectF,
        window: UsageWindow | None,
        color: QColor,
        width: int,
    ) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(TRACK, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(rect, 90 * 16, -360 * 16)
        percent = 100 - window.used_percent if window and window.used_percent is not None else None
        if percent is not None:
            painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(rect, 90 * 16, -round(360 * 16 * percent / 100))

    def _draw_legend(
        self, painter: QPainter, bounds: QRectF, snapshot: UsageSnapshot
    ) -> None:
        rows = (
            ("5h", snapshot.five_hour, FIVE_HOUR, False),
            ("7d", snapshot.seven_day, SEVEN_DAY, True),
        )
        top = bounds.top() + 202
        for index, (label, window, color, show_days) in enumerate(rows):
            y = top + index * 31
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QRectF(bounds.left() + 17, y + 7, 7, 7))
            painter.setPen(TEXT)
            painter.setFont(system_font(10, QFont.Weight.Medium))
            painter.drawText(
                QRectF(bounds.left() + 31, y, 82, 21),
                Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            reset = (
                (
                    format_day_duration(
                        remaining_seconds(window, snapshot.collected_at)
                    )
                    if show_days
                    else format_duration(
                        remaining_seconds(window, snapshot.collected_at)
                    )
                )
                if window
                else ("--d --:--" if show_days else "--:--:--")
            )
            value = f"Reset {reset}"
            painter.setPen(MUTED)
            painter.setFont(system_font(9, fixed=True))
            painter.drawText(
                QRectF(bounds.left() + 85, y, bounds.width() - 102, 21),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                value,
            )

    def _draw_unavailable(self, painter: QPainter, bounds: QRectF) -> None:
        painter.setPen(WARNING)
        painter.setFont(system_font(13, QFont.Weight.DemiBold))
        painter.drawText(
            bounds.adjusted(18, 18, -18, -18),
            Qt.AlignmentFlag.AlignCenter,
            "Usage unavailable",
        )
