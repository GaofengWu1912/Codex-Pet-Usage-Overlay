"""Read usage through Codex's official local app-server protocol."""

from __future__ import annotations

import json
import select
import subprocess
import time
from pathlib import Path
from typing import Iterable

from .models import UsageSnapshot, snapshot_from_payload


DEFAULT_BINARIES = (
    Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
    Path("/Applications/Codex.app/Contents/Resources/codex"),
)


def read_official_usage(
    binaries: Iterable[Path] = DEFAULT_BINARIES, timeout: float = 8.0
) -> UsageSnapshot | None:
    binary = next((path for path in binaries if path.is_file()), None)
    if binary is None:
        return None

    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [str(binary), "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(
            json.dumps(
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "codex-pet-usage",
                            "version": "0.1.0",
                        },
                        "capabilities": None,
                    },
                }
            )
            + "\n"
        )
        process.stdin.flush()
        if not _wait_for_id(process.stdout, 1, time.monotonic() + timeout):
            return None

        process.stdin.write(
            json.dumps(
                {"id": 2, "method": "account/rateLimits/read", "params": None}
            )
            + "\n"
        )
        process.stdin.flush()
        response = _wait_for_id(process.stdout, 2, time.monotonic() + timeout)
        if not response or not isinstance(response.get("result"), dict):
            return None
        return snapshot_from_payload(response["result"], source="codex:app-server")
    except (OSError, BrokenPipeError, ValueError):
        return None
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()


def _wait_for_id(stream: object, request_id: int, deadline: float) -> dict | None:
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        readable, _, _ = select.select([stream], [], [], remaining)
        if not readable:
            return None
        line = stream.readline()  # type: ignore[attr-defined]
        if not line:
            return None
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("id") == request_id:
            return payload
    return None
