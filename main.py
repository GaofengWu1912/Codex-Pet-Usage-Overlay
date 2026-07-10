"""Codex Pet Usage Overlay application entry point."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QLockFile, QObject, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from collector.usage import UsageCollector
from diagnostics import configure_logging, macos_permission_status
from launch_agent import LaunchAgentManager
from overlay.debug_window import DetectionAreaWindow
from overlay.tracker import PetHoverTracker
from overlay.window import OverlayWindow


APP_NAME = "CodexPetUsage"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def ensure_config(explicit: Path | None) -> Path:
    if explicit:
        return explicit.expanduser().resolve()
    destination = (
        Path.home() / "Library" / "Application Support" / APP_NAME / "config.json"
    )
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resource_path("config/config.json"), destination)
    return destination


def read_config(path: Path) -> dict[str, Any]:
    with resource_path("config/config.json").open(encoding="utf-8") as handle:
        defaults = json.load(handle)
    with path.open(encoding="utf-8") as handle:
        configured = json.load(handle)
    defaults.update(configured)
    return defaults


def tray_icon() -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2389DA"))
    painter.drawEllipse(QRectF(3, 3, 26, 26))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    pen = QPen(QColor("#FFFFFF"), 3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawArc(QRectF(8, 8, 16, 16), 90 * 16, -260 * 16)
    painter.end()
    return QIcon(pixmap)


class UsageFetcher(QObject):
    snapshotReady = pyqtSignal(object)

    def __init__(self, collector: UsageCollector):
        super().__init__()
        self.collector = collector
        self.lock = threading.Lock()

    def request(self) -> None:
        if not self.lock.acquire(blocking=False):
            return

        def run() -> None:
            try:
                self.snapshotReady.emit(self.collector.collect())
            finally:
                self.lock.release()

        threading.Thread(target=run, daemon=True, name="usage-collector").start()


class AppController(QObject):
    def __init__(self, app: QApplication, config_path: Path, force_show: bool):
        super().__init__()
        self.app = app
        self.config_path = config_path
        self.config = read_config(config_path)
        self.logger = configure_logging(self.config)
        self.collector = UsageCollector(self.config)
        self.overlay = OverlayWindow(self.config)
        self.debug_window = DetectionAreaWindow()
        self.debug_window.set_region(self.config["pet_region"])
        self.tracker = PetHoverTracker(self.config)
        self.tracker.hoverChanged.connect(self.set_overlay_visible)
        self.tracker.regionChanged.connect(self.update_pet_region)
        self.fetcher = UsageFetcher(self.collector)
        self.fetcher.snapshotReady.connect(self.overlay.set_snapshot)
        self.launch_agent = LaunchAgentManager(config_path)
        self._build_tray()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.fetcher.request)
        self.refresh_timer.start(int(self.config.get("refresh_seconds", 45)) * 1000)
        self.config_save_timer = QTimer(self)
        self.config_save_timer.setSingleShot(True)
        self.config_save_timer.timeout.connect(self.save_config)
        self.tracker.set_force_visible(force_show)
        self.show_action.setChecked(force_show)
        self.fetcher.request()
        QTimer.singleShot(1000, self.check_permissions)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(tray_icon(), self.app)
        self.tray.setToolTip("Codex Pet Usage")
        self.menu = QMenu()
        menu = self.menu

        self.show_action = QAction("Show overlay", menu, checkable=True)
        self.show_action.toggled.connect(self.tracker.set_force_visible)
        menu.addAction(self.show_action)

        self.debug_action = QAction("Show detection area", menu, checkable=True)
        self.debug_action.toggled.connect(self.debug_window.setVisible)
        menu.addAction(self.debug_action)

        refresh_action = QAction("Refresh now", menu)
        refresh_action.triggered.connect(self.fetcher.request)
        menu.addAction(refresh_action)

        config_action = QAction("Open config", menu)
        config_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config_path)))
        )
        menu.addAction(config_action)

        reload_action = QAction("Reload config", menu)
        reload_action.triggered.connect(self.reload_config)
        menu.addAction(reload_action)

        menu.addSeparator()
        self.login_action = QAction("Start at login", menu, checkable=True)
        self.login_action.setChecked(self.launch_agent.installed)
        self.login_action.toggled.connect(self.set_start_at_login)
        menu.addAction(self.login_action)

        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.app.quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def reload_config(self) -> None:
        try:
            config = read_config(self.config_path)
        except (OSError, json.JSONDecodeError) as error:
            self.tray.showMessage(
                "Codex Pet Usage", f"Config error: {error}", QSystemTrayIcon.MessageIcon.Warning
            )
            return
        self.config = config
        self.collector = UsageCollector(config)
        self.fetcher.collector = self.collector
        self.tracker.apply_config(config)
        self.overlay.apply_config(config)
        self.refresh_timer.setInterval(int(config.get("refresh_seconds", 45)) * 1000)
        self.fetcher.request()

    def set_overlay_visible(self, visible: bool) -> None:
        self.logger.info("Overlay setVisible=%s", visible)
        self.overlay.setVisible(visible)
        if visible:
            self.overlay.raise_()

    def check_permissions(self) -> None:
        status = macos_permission_status()
        self.logger.info(
            "Permissions accessibility=%s input_monitoring=%s",
            status["accessibility"],
            status["input_monitoring"],
        )
        if status["accessibility"] is False and status["input_monitoring"] is False:
            self.tray.showMessage(
                "Codex Pet Usage",
                "Mouse monitoring permission is unavailable. If hover does not "
                "respond, enable CodexPetUsage in System Settings > Privacy & Security "
                "> Accessibility and Input Monitoring.",
                QSystemTrayIcon.MessageIcon.Warning,
            )

    def set_start_at_login(self, enabled: bool) -> None:
        try:
            if enabled:
                self.launch_agent.install()
            else:
                self.launch_agent.uninstall()
        except OSError as error:
            self.login_action.blockSignals(True)
            self.login_action.setChecked(self.launch_agent.installed)
            self.login_action.blockSignals(False)
            self.tray.showMessage(
                "Codex Pet Usage", str(error), QSystemTrayIcon.MessageIcon.Warning
            )

    def update_pet_region(self, region: dict[str, int]) -> None:
        self.config["pet_region"] = region
        self.overlay.position_near(region, self.config["overlay"])
        self.debug_window.set_region(region)
        self.config_save_timer.start(500)

    def save_config(self) -> None:
        temporary = self.config_path.with_suffix(".json.tmp")
        try:
            temporary.write_text(
                json.dumps(self.config, indent=2) + "\n", encoding="utf-8"
            )
            temporary.replace(self.config_path)
        except OSError as error:
            self.tray.showMessage(
                "Codex Pet Usage",
                f"Could not save pet position: {error}",
                QSystemTrayIcon.MessageIcon.Warning,
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex pet usage overlay")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--show", action="store_true", help="show without hover")
    parser.add_argument("--once", action="store_true", help="print usage and exit")
    parser.add_argument("--install-launch-agent", action="store_true")
    parser.add_argument("--uninstall-launch-agent", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = ensure_config(args.config)
    if args.once:
        snapshot = UsageCollector(read_config(config_path)).collect()
        print(json.dumps(snapshot.to_dict(), indent=2))
        return 0

    launch_agent = LaunchAgentManager(config_path)
    if args.install_launch_agent:
        launch_agent.install()
        return 0
    if args.uninstall_launch_agent:
        launch_agent.uninstall()
        return 0

    lock = QLockFile(str(config_path.parent / "app.lock"))
    if not lock.tryLock(100):
        return 0

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    controller = AppController(app, config_path, args.show)
    app.instance_lock = lock  # type: ignore[attr-defined]
    app.controller = controller  # type: ignore[attr-defined]
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
