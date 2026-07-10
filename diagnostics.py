"""Application diagnostics and macOS permission checks."""

from __future__ import annotations

import ctypes
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


LOGGER_NAME = "codex_pet_usage"


def configure_logging(config: dict[str, Any]) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    path = Path(
        config.get(
            "log_file", "~/Library/Logs/CodexPetUsage/hover.log"
        )
    ).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.DEBUG if config.get("debug_hover", False) else logging.INFO)
    return logger


def macos_permission_status() -> dict[str, bool | None]:
    """Return current trust status without prompting for permissions."""

    result: dict[str, bool | None] = {
        "accessibility": None,
        "input_monitoring": None,
    }
    try:
        services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/"
            "ApplicationServices"
        )
        services.AXIsProcessTrusted.restype = ctypes.c_bool
        result["accessibility"] = bool(services.AXIsProcessTrusted())
        preflight = services.CGPreflightListenEventAccess
        preflight.restype = ctypes.c_bool
        result["input_monitoring"] = bool(preflight())
    except (OSError, AttributeError):
        pass
    return result
