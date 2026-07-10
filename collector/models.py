"""Normalized usage models and schema adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


FIVE_HOURS_MINUTES = 300
SEVEN_DAYS_MINUTES = 10_080


@dataclass(frozen=True)
class UsageWindow:
    used_percent: float | None
    reset_seconds: int
    reset_at: float | None = None
    window_minutes: int | None = None
    used_tokens: int = 0

    def to_dict(self) -> dict[str, int | float | None]:
        return {
            "used_percent": (
                round(self.used_percent, 2) if self.used_percent is not None else None
            ),
            "reset_seconds": self.reset_seconds,
            "reset_at": self.reset_at,
            "window_minutes": self.window_minutes,
            "used_tokens": self.used_tokens,
        }


@dataclass(frozen=True)
class UsageSnapshot:
    five_hour: UsageWindow | None
    seven_day: UsageWindow | None
    source: str
    collected_at: float
    stale: bool = False
    error: str | None = None

    @property
    def available(self) -> bool:
        return self.five_hour is not None or self.seven_day is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "five_hour": self.five_hour.to_dict() if self.five_hour else None,
            "seven_day": self.seven_day.to_dict() if self.seven_day else None,
            "source": self.source,
            "collected_at": self.collected_at,
            "stale": self.stale,
            "error": self.error,
        }


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().rstrip("%"))
        except ValueError:
            return None
    return None


def _reset_at(value: Any) -> float | None:
    number = _number(value)
    if number is not None:
        return number / 1000 if number > 10_000_000_000 else number
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _window(data: Any, now: float) -> UsageWindow | None:
    if not isinstance(data, dict):
        return None
    used = _number(
        data.get("used_percent", data.get("usedPercent", data.get("used")))
    )
    if used is None and (remaining := _number(data.get("remaining_percent"))) is not None:
        used = 100 - remaining
    if used is None and (remaining := _number(data.get("remaining"))) is not None:
        used = 100 - remaining if 0 <= remaining <= 100 else None
    if used is None:
        return None

    reset_at = _reset_at(
        data.get(
            "resets_at",
            data.get("reset_at", data.get("resetAt", data.get("resetsAt"))),
        )
    )
    reset_seconds = _number(
        data.get("reset_seconds", data.get("resetSeconds"))
    )
    if reset_seconds is None:
        reset_seconds = max(0, reset_at - now) if reset_at is not None else 0
    minutes = _number(
        data.get(
            "window_minutes",
            data.get("windowMinutes", data.get("windowDurationMins")),
        )
    )
    return UsageWindow(
        used_percent=max(0.0, min(100.0, used)),
        reset_seconds=max(0, int(reset_seconds)),
        reset_at=reset_at,
        window_minutes=int(minutes) if minutes is not None else None,
    )


def _from_mapping(mapping: dict[str, Any], source: str, now: float) -> UsageSnapshot | None:
    five_data = mapping.get("five_hour", mapping.get("fiveHour"))
    seven_data = mapping.get("seven_day", mapping.get("sevenDay"))

    primary = mapping.get("primary")
    secondary = mapping.get("secondary")
    if five_data is None or seven_data is None:
        candidates = [value for value in (primary, secondary) if isinstance(value, dict)]
        for candidate in candidates:
            minutes = _number(
                candidate.get(
                    "window_minutes",
                    candidate.get("windowMinutes", candidate.get("windowDurationMins")),
                )
            )
            if minutes == FIVE_HOURS_MINUTES:
                five_data = candidate
            elif minutes == SEVEN_DAYS_MINUTES:
                seven_data = candidate
        if five_data is None:
            five_data = primary
        if seven_data is None:
            seven_data = secondary

    five = _window(five_data, now)
    seven = _window(seven_data, now)
    if not five and not seven:
        return None
    return UsageSnapshot(five, seven, source, now)


def snapshot_from_payload(
    payload: Any, source: str, now: float | None = None
) -> UsageSnapshot | None:
    """Recursively adapt known and future Codex usage JSON shapes."""

    collected = now if now is not None else datetime.now(timezone.utc).timestamp()
    queue = [payload]
    seen: set[int] = set()
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            snapshot = _from_mapping(current, source, collected)
            if snapshot:
                return snapshot
            queue.extend(current.values())
        elif isinstance(current, list):
            queue.extend(current)
    return None
