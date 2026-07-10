"""Structured Codex state discovery and parsing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .models import UsageSnapshot, snapshot_from_payload


MATCH_TERMS = ("usage", "rate", "limit", "quota", "reset")
FIXED_NAMES = (
    ".codex-global-state.json",
    "usage.json",
    "rate_limits.json",
    "rate-limit.json",
    "quota.json",
)


def _candidate_files(roots: Iterable[Path], maximum: int) -> list[Path]:
    candidates: dict[Path, float] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for name in FIXED_NAMES:
            path = root / name
            if path.is_file():
                candidates[path] = path.stat().st_mtime

        try:
            for path in root.glob("**/*.json"):
                if len(candidates) >= maximum * 3:
                    break
                lowered = path.name.lower()
                if any(term in lowered for term in MATCH_TERMS):
                    try:
                        if path.stat().st_size <= 5 * 1024 * 1024:
                            candidates[path] = path.stat().st_mtime
                    except OSError:
                        continue
        except OSError:
            continue

    return [
        path
        for path, _ in sorted(
            candidates.items(), key=lambda item: item[1], reverse=True
        )[:maximum]
    ]


def read_structured_usage(
    roots: Iterable[Path], maximum_files: int = 100
) -> UsageSnapshot | None:
    """Return the newest usable structured snapshot, if Codex exposes one."""

    for path in _candidate_files(roots, maximum_files):
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        snapshot = snapshot_from_payload(payload, source=f"state:{path}")
        if snapshot and snapshot.available:
            return snapshot
    return None

