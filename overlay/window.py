"""Borderless, click-through overlay window."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QPainter
from PyQt6.QtWidgets import QWidget

from collector.models import UsageSnapshot
from .renderer import UsageRenderer


class OverlayWindow(QWidget):
    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self.renderer = UsageRenderer()
        self.snapshot = UsageSnapshot(None, None, "startup", 0, error="Loading")
        self._configure_window()
        self.apply_config(config)
        self.repaint_timer = QTimer(self)
        self.repaint_timer.timeout.connect(self.update)
        self.repaint_timer.start(1000)

    def _configure_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def apply_config(self, config: dict[str, Any]) -> None:
        overlay = config["overlay"]
        self.resize(int(overlay["width"]), int(overlay["height"]))
        self.position_near(config["pet_region"], overlay)

    def position_near(
        self, pet_region: dict[str, Any], overlay: dict[str, Any]
    ) -> None:
        pet_x = int(pet_region["x"])
        pet_width = int(pet_region["width"])
        x = pet_x + int(overlay.get("offset_x", 0))
        y = int(pet_region["y"]) + int(overlay.get("offset_y", 0))
        target = QRect(x, y, self.width(), self.height())
        screen = QGuiApplication.screenAt(target.center()) or QGuiApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            if x + self.width() > available.right() + 1:
                left_x = pet_x - self.width() - 12
                if left_x >= available.left():
                    x = left_x
                else:
                    x = pet_x + pet_width + 12
            x = min(max(x, available.left()), available.right() - self.width() + 1)
            y = min(max(y, available.top()), available.bottom() - self.height() + 1)
        self.move(x, y)

    def set_snapshot(self, snapshot: UsageSnapshot) -> None:
        self.snapshot = snapshot
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        self.renderer.paint(painter, QRectF(self.rect()), self.snapshot)
