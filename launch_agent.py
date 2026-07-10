"""LaunchAgent installation for starting the packaged app at login."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path


LABEL = "com.codex.pet-usage"


class LaunchAgentManager:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

    @property
    def installed(self) -> bool:
        return self.path.is_file()

    def install(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if getattr(sys, "frozen", False):
            arguments = [sys.executable, "--config", str(self.config_path)]
        else:
            arguments = [
                sys.executable,
                str(Path(__file__).resolve().parent / "main.py"),
                "--config",
                str(self.config_path),
            ]
        payload = {
            "Label": LABEL,
            "ProgramArguments": arguments,
            "RunAtLoad": True,
            "KeepAlive": False,
            "ProcessType": "Interactive",
            "StandardOutPath": str(
                Path.home() / "Library" / "Logs" / "CodexPetUsage.log"
            ),
            "StandardErrorPath": str(
                Path.home() / "Library" / "Logs" / "CodexPetUsage.error.log"
            ),
        }
        with self.path.open("wb") as handle:
            plistlib.dump(payload, handle)
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(self.path)],
            check=False,
            capture_output=True,
        )

    def uninstall(self) -> None:
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}", str(self.path)],
            check=False,
            capture_output=True,
        )
        self.path.unlink(missing_ok=True)

