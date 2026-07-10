"""Parse Codex pet bounds in Chromium/Qt logical desktop coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PetBounds:
    x: int
    y: int
    width: int
    height: int
    display_id: str
    display_x: int
    display_y: int
    display_width: int
    display_height: int

    def region_dict(self) -> dict[str, int]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


def pet_bounds_from_state(payload: Any) -> PetBounds | None:
    """Return logical-pixel bounds; Chromium and Qt both use top-left DIPs."""

    if not isinstance(payload, dict):
        return None
    bounds = payload.get("electron-avatar-overlay-bounds")
    if not isinstance(bounds, dict):
        return None
    anchor = bounds.get("anchor")
    display = bounds.get("displayBounds")
    if not isinstance(anchor, dict) or not isinstance(display, dict):
        return None
    try:
        parsed = PetBounds(
            x=int(anchor["x"]),
            y=int(anchor["y"]),
            width=int(anchor["width"]),
            height=int(anchor["height"]),
            display_id=str(bounds.get("displayId", "unknown")),
            display_x=int(display["x"]),
            display_y=int(display["y"]),
            display_width=int(display["width"]),
            display_height=int(display["height"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if parsed.width <= 0 or parsed.height <= 0:
        return None
    return parsed
