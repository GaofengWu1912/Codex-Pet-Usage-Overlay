"""Configuration-based pet hover detection."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QGuiApplication

from diagnostics import LOGGER_NAME
from collector.pet_state import pet_bounds_from_state
from .hover_state import HoverStateMachine


class PetHoverTracker(QObject):
    hoverChanged = pyqtSignal(bool)
    regionChanged = pyqtSignal(object)

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self.visible = False
        self.force_visible = False
        self.was_inside = False
        self.hover_state = HoverStateMachine()
        self.dragging = False
        self.drag_offset = QPoint()
        self.option_was_down = False
        self.codex_state_mtime = 0
        self.last_logged_region: QRect | None = None
        self.last_debug_log = 0.0
        self.logger = logging.getLogger(LOGGER_NAME)
        self.apply_config(config)
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self._hover_elapsed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(self.poll_ms)

    def apply_config(self, config: dict[str, Any]) -> None:
        region = config["pet_region"]
        self.region = QRect(
            int(region["x"]),
            int(region["y"]),
            int(region["width"]),
            int(region["height"]),
        )
        self.poll_ms = int(config.get("mouse_poll_ms", 100))
        self.show_delay_ms = int(config.get("hover_show_delay_ms", 1000))
        self.debug_hover = bool(config.get("debug_hover", False))
        self.follow_codex_pet = bool(config.get("follow_codex_pet", True))
        self.codex_state_file = Path(
            config.get("codex_state_file", "~/.codex/.codex-global-state.json")
        ).expanduser()
        if hasattr(self, "timer"):
            self.timer.setInterval(self.poll_ms)

    def set_force_visible(self, value: bool) -> None:
        self.force_visible = value
        if value:
            self.hover_timer.stop()
            self.hover_state.force(True)
            self._set_visible(True)
        else:
            self.hover_timer.stop()
            self.hover_state.force(False)
            self.was_inside = False
            self._set_visible(False)

    def _poll(self) -> None:
        now = time.monotonic()
        self._sync_codex_region()
        cursor = QCursor.pos()
        option_down = bool(
            QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier
        )
        if option_down and not self.option_was_down:
            self.region.moveCenter(cursor)
            self.regionChanged.emit(self.region_dict())
        self.option_was_down = option_down

        left_down = bool(
            QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton
        )
        if left_down and not self.dragging and self.region.contains(cursor):
            self.dragging = True
            self.drag_offset = cursor - self.region.center()
        elif self.dragging and left_down:
            self.region.moveCenter(cursor - self.drag_offset)
            self.regionChanged.emit(self.region_dict())
        elif self.dragging:
            self.dragging = False
            self.regionChanged.emit(self.region_dict())

        inside = self.region.contains(cursor)
        if self.debug_hover and now - self.last_debug_log >= 0.5:
            screen = QGuiApplication.screenAt(self.region.center())
            self.logger.debug(
                "Mouse x=%d y=%d Pet x=%d y=%d width=%d height=%d "
                "screen=%s Inside=%s state=%s",
                cursor.x(),
                cursor.y(),
                self.region.x(),
                self.region.y(),
                self.region.width(),
                self.region.height(),
                screen.name() if screen else "unknown",
                inside,
                self.hover_state.phase.value,
            )
            self.last_debug_log = now

        if inside and not self.was_inside:
            self._mouse_enter()
        elif not inside and self.was_inside:
            self._mouse_leave()
        self.was_inside = inside

    def _mouse_enter(self) -> None:
        if self.force_visible:
            return
        if not self.hover_state.enter():
            return
        self.logger.info("ENTER")
        self.hover_timer.start(self.show_delay_ms)
        self.logger.info("Timer Started delay_ms=%d", self.show_delay_ms)

    def _mouse_leave(self) -> None:
        self.hover_timer.stop()
        self.hover_state.leave()
        self.logger.info("LEAVE Timer Cancelled HIDE OVERLAY")
        self._set_visible(False)

    def _hover_elapsed(self) -> None:
        self.logger.info("%gs elapsed", self.show_delay_ms / 1000)
        self._sync_codex_region()
        inside = self.region.contains(QCursor.pos())
        if self.force_visible:
            return
        if not self.hover_state.elapsed(inside):
            return
        self.logger.info("SHOW OVERLAY")
        self._set_visible(True)

    def _set_visible(self, value: bool) -> None:
        if value == self.visible:
            return
        self.visible = value
        self.hoverChanged.emit(value)

    def contains(self, point: QPoint) -> bool:
        return self.region.contains(point)

    def region_dict(self) -> dict[str, int]:
        return {
            "x": self.region.x(),
            "y": self.region.y(),
            "width": self.region.width(),
            "height": self.region.height(),
        }

    def _sync_codex_region(self) -> None:
        if not self.follow_codex_pet:
            return
        try:
            mtime = self.codex_state_file.stat().st_mtime_ns
            if mtime == self.codex_state_mtime:
                return
            payload = json.loads(self.codex_state_file.read_text(encoding="utf-8"))
            bounds = pet_bounds_from_state(payload)
            if bounds is None:
                return
            region = QRect(
                bounds.x,
                bounds.y,
                bounds.width,
                bounds.height,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return
        self.codex_state_mtime = mtime
        if self.last_logged_region != region:
            screen = QGuiApplication.screenAt(region.center())
            self.logger.info(
                "Pet Bounds x=%d y=%d width=%d height=%d screen=%s display_id=%s "
                "display_bounds=%d,%d,%dx%d coordinates=top-left-logical-dip",
                region.x(),
                region.y(),
                region.width(),
                region.height(),
                screen.name() if screen else "unknown",
                bounds.display_id,
                bounds.display_x,
                bounds.display_y,
                bounds.display_width,
                bounds.display_height,
            )
            self.last_logged_region = QRect(region)
        if region != self.region:
            self.region = region
            self.regionChanged.emit(self.region_dict())
