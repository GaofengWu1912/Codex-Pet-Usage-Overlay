"""Deterministic hover state transitions independent of the GUI timer."""

from __future__ import annotations

from enum import Enum


class HoverPhase(str, Enum):
    IDLE = "IDLE"
    WAITING = "WAITING"
    VISIBLE = "VISIBLE"


class HoverStateMachine:
    def __init__(self) -> None:
        self.phase = HoverPhase.IDLE

    def enter(self) -> bool:
        if self.phase is not HoverPhase.IDLE:
            return False
        self.phase = HoverPhase.WAITING
        return True

    def elapsed(self, still_inside: bool) -> bool:
        if self.phase is not HoverPhase.WAITING:
            return False
        self.phase = HoverPhase.VISIBLE if still_inside else HoverPhase.IDLE
        return still_inside

    def leave(self) -> bool:
        was_active = self.phase is not HoverPhase.IDLE
        self.phase = HoverPhase.IDLE
        return was_active

    def force(self, visible: bool) -> None:
        self.phase = HoverPhase.VISIBLE if visible else HoverPhase.IDLE
