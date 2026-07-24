from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from collector.codex_state import read_structured_usage
from collector.log_parser import read_log_usage
from collector.models import UsageSnapshot, UsageWindow, snapshot_from_payload
from collector.pet_state import pet_bounds_from_state
from collector.usage import UsageCollector
from overlay.renderer import (
    UsageRenderer,
    format_day_duration,
    format_duration,
    format_reset_countdown,
)
from overlay.hover_state import HoverPhase, HoverStateMachine


class SchemaAdapterTests(unittest.TestCase):
    def test_normalized_schema(self) -> None:
        snapshot = snapshot_from_payload(
            {
                "five_hour": {"used_percent": 35, "reset_seconds": 3600},
                "seven_day": {"used_percent": 60, "reset_seconds": 86400},
            },
            "test",
            now=1000,
        )
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.five_hour.used_percent, 35)
        self.assertEqual(snapshot.seven_day.reset_seconds, 86400)

    def test_codex_rate_limit_schema(self) -> None:
        snapshot = snapshot_from_payload(
            {
                "primary": {
                    "used_percent": 22.5,
                    "window_minutes": 300,
                    "resets_at": 4600,
                },
                "secondary": {
                    "used_percent": 48,
                    "window_minutes": 10080,
                    "resets_at": 87400,
                },
            },
            "test",
            now=1000,
        )
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.five_hour.reset_seconds, 3600)
        self.assertEqual(snapshot.seven_day.used_percent, 48)

    def test_official_app_server_camel_case_schema(self) -> None:
        snapshot = snapshot_from_payload(
            {
                "rateLimits": {
                    "primary": {
                        "usedPercent": 51,
                        "windowDurationMins": 300,
                        "resetsAt": 4600,
                    },
                    "secondary": {
                        "usedPercent": 25,
                        "windowDurationMins": 10080,
                        "resetsAt": 87400,
                    },
                }
            },
            "codex:app-server",
            now=1000,
        )
        assert snapshot is not None
        self.assertEqual(snapshot.five_hour.used_percent, 51)
        self.assertEqual(snapshot.five_hour.window_minutes, 300)
        self.assertEqual(snapshot.five_hour.reset_seconds, 3600)
        self.assertEqual(snapshot.seven_day.used_percent, 25)

    def test_long_duration_uses_days(self) -> None:
        self.assertEqual(format_duration(160 * 3600), "6d 16:00")
        self.assertEqual(format_duration(4 * 3600 + 58 * 60 + 55), "04:58:55")
        self.assertEqual(format_day_duration(16 * 3600 + 51 * 60), "0d 16:51")

    def test_renderer_converts_used_to_remaining(self) -> None:
        window = UsageWindow(54, 100)
        self.assertEqual(UsageRenderer._main_value(window), "46%")

    def test_reset_countdown_uses_day_hour_minute_labels(self) -> None:
        self.assertEqual(
            format_reset_countdown(6 * 86_400 + 23 * 3600 + 41 * 60),
            "6d 23h 41min",
        )


class HoverStateTests(unittest.TestCase):
    def test_short_hover_is_cancelled_and_never_visible(self) -> None:
        state = HoverStateMachine()
        self.assertTrue(state.enter())
        self.assertEqual(state.phase, HoverPhase.WAITING)
        self.assertTrue(state.leave())
        self.assertEqual(state.phase, HoverPhase.IDLE)
        self.assertFalse(state.elapsed(True))

    def test_pet_bounds_preserve_multidisplay_logical_coordinates(self) -> None:
        bounds = pet_bounds_from_state(
            {
                "electron-avatar-overlay-bounds": {
                    "anchor": {"x": -800, "y": 120, "width": 113, "height": 123},
                    "displayBounds": {
                        "x": -1470,
                        "y": 0,
                        "width": 1470,
                        "height": 956,
                    },
                    "displayId": 2,
                }
            }
        )
        assert bounds is not None
        self.assertEqual(bounds.region_dict()["x"], -800)
        self.assertEqual(bounds.region_dict()["y"], 120)
        self.assertEqual(bounds.display_id, "2")

    def test_current_direct_pet_bounds_schema_uses_stable_dimensions(self) -> None:
        bounds = pet_bounds_from_state(
            {
                "electron-avatar-overlay-bounds": {
                    "x": 1211,
                    "y": 316,
                    "displayBounds": {
                        "x": 0,
                        "y": 0,
                        "width": 1470,
                        "height": 956,
                    },
                    "displayId": 1,
                    "placement": "bottom-end",
                }
            }
        )
        assert bounds is not None
        self.assertEqual(
            bounds.region_dict(),
            {"x": 1211, "y": 316, "width": 113, "height": 123},
        )
        self.assertEqual(bounds.display_id, "1")

    def test_elapsed_hover_shows_then_leave_hides(self) -> None:
        state = HoverStateMachine()
        self.assertTrue(state.enter())
        self.assertTrue(state.elapsed(True))
        self.assertEqual(state.phase, HoverPhase.VISIBLE)
        self.assertTrue(state.leave())
        self.assertEqual(state.phase, HoverPhase.IDLE)

    def test_reentry_starts_a_new_wait(self) -> None:
        state = HoverStateMachine()
        state.enter()
        state.leave()
        self.assertTrue(state.enter())
        self.assertEqual(state.phase, HoverPhase.WAITING)

    def test_remaining_and_millisecond_reset_are_normalized(self) -> None:
        snapshot = snapshot_from_payload(
            {
                "primary": {
                    "remaining": 75,
                    "window_minutes": 300,
                    "resets_at": 4_600_000_000_000,
                }
            },
            "test",
            now=4_599_999_000,
        )
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.five_hour.used_percent, 25)
        self.assertEqual(snapshot.five_hour.reset_seconds, 1000)


class SourceTests(unittest.TestCase):
    def test_structured_state_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "usage.json").write_text(
                json.dumps(
                    {
                        "five_hour": {
                            "used_percent": 12,
                            "reset_seconds": 100,
                        },
                        "seven_day": {
                            "used_percent": 34,
                            "reset_seconds": 200,
                        },
                    }
                ),
                encoding="utf-8",
            )
            snapshot = read_structured_usage([root])
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertTrue(snapshot.source.startswith("state:"))

    def test_latest_rate_limit_is_read_from_log_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "sessions" / "2026" / "07" / "10"
            session.mkdir(parents=True)
            event = {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "rate_limits": {
                        "primary": {
                            "used_percent": 41,
                            "window_minutes": 300,
                            "resets_at": 5000,
                        },
                        "secondary": {
                            "used_percent": 62,
                            "window_minutes": 10080,
                            "resets_at": 9000,
                        },
                    },
                },
            }
            (session / "rollout.jsonl").write_text(
                json.dumps(event) + "\n", encoding="utf-8"
            )
            snapshot = read_log_usage([root], tail_bytes=4096)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.five_hour.used_percent, 41)
            self.assertTrue(snapshot.source.startswith("log:"))

    def test_real_tokens_are_rolled_up_and_duplicate_events_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "sessions" / "2026" / "07" / "10"
            session.mkdir(parents=True)
            now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc).timestamp()

            def event(hours_ago: int, tokens: int) -> dict:
                stamp = datetime.fromtimestamp(
                    now - hours_ago * 3600, timezone.utc
                ).isoformat().replace("+00:00", "Z")
                return {
                    "timestamp": stamp,
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {"last_token_usage": {"total_tokens": tokens}},
                        "rate_limits": {
                            "primary": {
                                "used_percent": 0,
                                "window_minutes": 300,
                                "resets_at": now + 100,
                            },
                            "secondary": {
                                "used_percent": 0,
                                "window_minutes": 10080,
                                "resets_at": now + 200,
                            },
                        },
                    },
                }

            recent = json.dumps(event(1, 1_000))
            older = json.dumps(event(24, 2_000))
            content = recent + "\n" + older + "\n"
            (session / "one.jsonl").write_text(content, encoding="utf-8")
            (session / "duplicate.jsonl").write_text(recent + "\n", encoding="utf-8")

            snapshot = read_log_usage([root], now=now)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.five_hour.used_tokens, 1_000)
            self.assertEqual(snapshot.seven_day.used_tokens, 3_000)
            self.assertIsNone(snapshot.five_hour.used_percent)
            self.assertIsNone(snapshot.seven_day.used_percent)

    def test_configured_token_budget_produces_percent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "sessions"
            session.mkdir()
            now = datetime.now(timezone.utc).timestamp()
            event = {
                "timestamp": datetime.fromtimestamp(now - 60, timezone.utc).isoformat(),
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"last_token_usage": {"total_tokens": 250}},
                    "rate_limits": {
                        "primary": {"used_percent": 0, "window_minutes": 300},
                        "secondary": {"used_percent": 0, "window_minutes": 10080},
                    },
                },
            }
            (session / "rollout.jsonl").write_text(
                json.dumps(event) + "\n", encoding="utf-8"
            )
            snapshot = read_log_usage(
                [root], now=now, token_budgets={"five_hour": 1_000}
            )
            assert snapshot is not None
            self.assertEqual(snapshot.five_hour.used_percent, 25)

    def test_null_token_info_does_not_abort_log_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "sessions"
            session.mkdir()
            now = datetime.now(timezone.utc).timestamp()
            event = {
                "timestamp": datetime.fromtimestamp(now - 60, timezone.utc).isoformat(),
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": None,
                    "rate_limits": {
                        "primary": {"used_percent": 17, "window_minutes": 300},
                        "secondary": {"used_percent": 29, "window_minutes": 10080},
                    },
                },
            }
            (session / "rollout.jsonl").write_text(
                json.dumps(event) + "\n", encoding="utf-8"
            )

            snapshot = read_log_usage([root], now=now)

            assert snapshot is not None
            self.assertEqual(snapshot.five_hour.used_percent, 17)
            self.assertEqual(snapshot.seven_day.used_percent, 29)

    def test_cache_is_used_when_live_sources_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache.json"
            config = {
                "use_codex_api": False,
                "state_roots": [str(root / "missing")],
                "cache_file": str(cache),
                "max_state_files": 5,
                "max_log_files": 5,
                "log_tail_bytes": 4096,
            }
            collector = UsageCollector(config)
            collector._save_cache(
                UsageSnapshot(
                    UsageWindow(10, 20),
                    UsageWindow(30, 40),
                    "test",
                    1,
                )
            )
            snapshot = collector.collect()
            self.assertTrue(snapshot.stale)
            self.assertEqual(snapshot.five_hour.used_percent, 10)


if __name__ == "__main__":
    unittest.main()
