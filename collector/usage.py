"""Public usage collector with state, log, and cache fallbacks."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .codex_api import read_official_usage
from .codex_state import read_structured_usage
from .log_parser import read_log_usage
from .models import UsageSnapshot, UsageWindow


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "config.json"


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    config_path = Path(path).expanduser() if path else DEFAULT_CONFIG
    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle)


class UsageCollector:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.roots = [Path(item).expanduser() for item in config["state_roots"]]
        self.cache_path = Path(config["cache_file"]).expanduser()

    def collect(self) -> UsageSnapshot:
        official = (
            read_official_usage(
                timeout=float(self.config.get("codex_api_timeout_seconds", 8))
            )
            if self.config.get("use_codex_api", True)
            else None
        )
        if official:
            self._save_cache(official)
            return official

        state = read_structured_usage(
            self.roots, int(self.config.get("max_state_files", 100))
        )
        log = read_log_usage(
            self.roots,
            int(self.config.get("max_log_files", 0)),
            int(self.config.get("log_tail_bytes", 524_288)),
            token_budgets=self.config.get("token_budgets"),
        )
        if state and log:
            # Structured state owns quota percentages; logs own real token totals.
            five = self._merge_window(state.five_hour, log.five_hour)
            seven = self._merge_window(state.seven_day, log.seven_day)
            merged = replace(state, five_hour=five, seven_day=seven)
            self._save_cache(merged)
            return merged
        if state:
            self._save_cache(state)
            return state
        if log:
            self._save_cache(log)
            return log

        cached = self._load_cache()
        if cached:
            return replace(cached, source=f"cache:{cached.source}", stale=True)

        return UsageSnapshot(
            None,
            None,
            "unavailable",
            datetime.now(timezone.utc).timestamp(),
            error="Usage unavailable",
        )

    def _save_cache(self, snapshot: UsageSnapshot) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            file_descriptor, temporary = tempfile.mkstemp(
                prefix="usage-", suffix=".json", dir=self.cache_path.parent
            )
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                json.dump(snapshot.to_dict(), handle, indent=2)
                handle.write("\n")
            os.replace(temporary, self.cache_path)
        except OSError:
            return

    def _load_cache(self) -> UsageSnapshot | None:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None

        def window(name: str) -> UsageWindow | None:
            data = payload.get(name)
            if not isinstance(data, dict):
                return None
            return UsageWindow(
                (
                    float(data["used_percent"])
                    if data.get("used_percent") is not None
                    else None
                ),
                int(data["reset_seconds"]),
                data.get("reset_at"),
                data.get("window_minutes"),
                int(data.get("used_tokens", 0)),
            )

        try:
            return UsageSnapshot(
                window("five_hour"),
                window("seven_day"),
                str(payload.get("source", "unknown")),
                float(payload.get("collected_at", 0)),
                True,
                payload.get("error"),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _merge_window(
        state: UsageWindow | None, log: UsageWindow | None
    ) -> UsageWindow | None:
        if not state:
            return log
        if not log:
            return state
        percent = state.used_percent
        if percent == 0 and log.used_tokens > 0:
            percent = log.used_percent
        return replace(state, used_percent=percent, used_tokens=log.used_tokens)


def get_usage(config_path: Path | str | None = None) -> dict[str, Any]:
    """Return normalized usage without exposing the selected data source."""

    return UsageCollector(load_config(config_path)).collect().to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Read local Codex usage limits")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    print(json.dumps(get_usage(args.config), indent=2))


if __name__ == "__main__":
    main()
