"""Render the overlay offscreen and verify it produces visible pixels."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

from collector.models import UsageSnapshot, UsageWindow
from overlay.window import OverlayWindow


def main() -> int:
    project = PROJECT
    config = json.loads((project / "config" / "config.json").read_text())
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = OverlayWindow(config)
    window.set_snapshot(
        UsageSnapshot(
            UsageWindow(72, 3600, window_minutes=300),
            UsageWindow(41, 86400, window_minutes=10080),
            "smoke-test",
            time.time(),
        )
    )

    image = QImage(window.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    window.render(painter)
    painter.end()

    visible = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 0:
                visible += 1
    if visible < image.width() * image.height() // 4:
        raise SystemExit(f"overlay rendered too few visible pixels: {visible}")
    if not window.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents):
        raise SystemExit("overlay is not mouse-transparent")

    output = project / "build" / "overlay-smoke.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(output)):
        raise SystemExit("failed to save smoke image")
    print(output)
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
