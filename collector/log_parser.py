"""Fallback parser for Codex JSONL session logs."""

from __future__ import annotations

import json
import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import (
    FIVE_HOURS_MINUTES,
    SEVEN_DAYS_MINUTES,
    UsageSnapshot,
    UsageWindow,
    snapshot_from_payload,
)


def _tail_lines(path: Path, byte_limit: int) -> list[bytes]:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - byte_limit))
        data = handle.read()
    lines = data.splitlines()
    if size > byte_limit and lines:
        lines = lines[1:]
    return lines


def _log_files(roots: Iterable[Path], maximum: int) -> list[Path]:
    files: list[tuple[float, Path]] = []
    for root in roots:
        sessions = root / "sessions"
        if not sessions.is_dir():
            continue
        try:
            for path in sessions.glob("**/*.jsonl"):
                try:
                    files.append((path.stat().st_mtime, path))
                except OSError:
                    continue
        except OSError:
            continue
    files.sort(reverse=True)
    return [path for _, path in files[:maximum]]


def read_log_usage(
    roots: Iterable[Path],
    maximum_files: int = 0,
    tail_bytes: int = 524_288,
    now: float | None = None,
    token_budgets: dict[str, int | float | None] | None = None,
) -> UsageSnapshot | None:
    """Read rate limits and sum real token increments over rolling windows."""

    collected = now if now is not None else datetime.now(timezone.utc).timestamp()
    files = _log_files(roots, maximum_files or 100_000)
    latest: UsageSnapshot | None = None
    latest_timestamp = 0.0
    five_tokens = 0
    seven_tokens = 0
    seen: set[bytes] = set()
    seven_cutoff = collected - SEVEN_DAYS_MINUTES * 60
    five_cutoff = collected - FIVE_HOURS_MINUTES * 60

    for path in files:
        try:
            if path.stat().st_mtime < seven_cutoff:
                continue
        except OSError:
            continue
        try:
            lines = path.read_bytes().splitlines()
        except OSError:
            continue
        for raw_line in lines:
            try:
                event = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            payload = event.get("payload") if isinstance(event, dict) else None
            if not isinstance(payload, dict):
                continue
            if payload.get("type") != "token_count":
                continue

            timestamp = _event_timestamp(event.get("timestamp"))
            if timestamp is not None and seven_cutoff <= timestamp <= collected + 60:
                info = payload.get("info")
                usage = info.get("last_token_usage") if isinstance(info, dict) else None
                tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
                if isinstance(tokens, (int, float)) and not isinstance(tokens, bool):
                    digest = hashlib.sha1(raw_line).digest()
                    if digest not in seen:
                        seen.add(digest)
                        seven_tokens += max(0, int(tokens))
                        if timestamp >= five_cutoff:
                            five_tokens += max(0, int(tokens))

            rate_limits = payload.get("rate_limits")
            if not isinstance(rate_limits, dict):
                continue
            snapshot = snapshot_from_payload(
                rate_limits, source=f"log:{path}", now=collected
            )
            ordering = timestamp or path.stat().st_mtime
            if snapshot and snapshot.available and ordering >= latest_timestamp:
                latest = snapshot
                latest_timestamp = ordering

    if not latest and not (five_tokens or seven_tokens):
        return None

    budgets = token_budgets or {}
    five = _with_tokens(
        latest.five_hour if latest else None,
        five_tokens,
        FIVE_HOURS_MINUTES,
        budgets.get("five_hour"),
    )
    seven = _with_tokens(
        latest.seven_day if latest else None,
        seven_tokens,
        SEVEN_DAYS_MINUTES,
        budgets.get("seven_day"),
    )
    source = latest.source if latest else "log:token-count"
    return UsageSnapshot(five, seven, source, collected)


def _event_timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _with_tokens(
    window: UsageWindow | None,
    tokens: int,
    minutes: int,
    budget: int | float | None,
) -> UsageWindow:
    percent = window.used_percent if window else None
    if isinstance(budget, (int, float)) and budget > 0:
        percent = min(100.0, tokens / float(budget) * 100)
    elif percent == 0 and tokens > 0:
        # Current Codex builds can emit 0.0 as an unavailable placeholder.
        percent = None
    base = window or UsageWindow(None, 0, window_minutes=minutes)
    return replace(base, used_percent=percent, used_tokens=tokens)
