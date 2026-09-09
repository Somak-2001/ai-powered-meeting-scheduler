"""Unit tests for free-slot calculation, busy interval merging, and duration filtering."""

from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import MagicMock, patch

from meeting_scheduler.tools import (
    LOCAL_TZ,
    calculate_free_slots,
    find_free_slots,
    merge_busy_intervals,
)


class TestFreeSlots(unittest.TestCase):
    """Test suite for free slot search algorithms and find_free_slots tool."""

    def setUp(self) -> None:
        self.date_str = "2026-10-20"
        self.day = dt.date(2026, 10, 20)
        # Mock current time as early morning on a different date so full working day is eligible
        self.fake_now = dt.datetime(2026, 10, 19, 8, 0, tzinfo=LOCAL_TZ)

    def test_free_slots_empty_calendar(self) -> None:
        """On an empty day, the entire 09:00 to 18:00 window is free."""
        events: list[dict] = []
        slots = calculate_free_slots(events, self.date_str, duration_minutes=60, current_time=self.fake_now)
        self.assertEqual(len(slots), 1)
        start, end = slots[0]
        self.assertEqual(start.strftime("%H:%M"), "09:00")
        self.assertEqual(end.strftime("%H:%M"), "18:00")

    def test_free_slots_with_intermediate_meetings(self) -> None:
        """Intermediate meetings divide the day into correct free chunks."""
        events = [
            {
                "summary": "Morning Standup",
                "start": {"dateTime": f"{self.date_str}T10:00:00+05:30"},
                "end": {"dateTime": f"{self.date_str}T11:00:00+05:30"},
            },
            {
                "summary": "Team Sync",
                "start": {"dateTime": f"{self.date_str}T14:00:00+05:30"},
                "end": {"dateTime": f"{self.date_str}T15:00:00+05:30"},
            },
        ]
        slots = calculate_free_slots(events, self.date_str, duration_minutes=30, current_time=self.fake_now)
        self.assertEqual(len(slots), 3)
        self.assertEqual((slots[0][0].strftime("%H:%M"), slots[0][1].strftime("%H:%M")), ("09:00", "10:00"))
        self.assertEqual((slots[1][0].strftime("%H:%M"), slots[1][1].strftime("%H:%M")), ("11:00", "14:00"))
        self.assertEqual((slots[2][0].strftime("%H:%M"), slots[2][1].strftime("%H:%M")), ("15:00", "18:00"))

    def test_merge_busy_intervals(self) -> None:
        """Overlapping and contiguous busy ranges should merge cleanly."""
        t1 = dt.datetime(2026, 10, 20, 10, 0, tzinfo=LOCAL_TZ)
        t2 = dt.datetime(2026, 10, 20, 11, 0, tzinfo=LOCAL_TZ)
        t3 = dt.datetime(2026, 10, 20, 10, 30, tzinfo=LOCAL_TZ)
        t4 = dt.datetime(2026, 10, 20, 11, 30, tzinfo=LOCAL_TZ)
        t5 = dt.datetime(2026, 10, 20, 14, 0, tzinfo=LOCAL_TZ)
        t6 = dt.datetime(2026, 10, 20, 15, 0, tzinfo=LOCAL_TZ)

        merged = merge_busy_intervals([(t1, t2), (t3, t4), (t5, t6)])
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0], (t1, t4))  # 10:00 to 11:30 merged
        self.assertEqual(merged[1], (t5, t6))  # 14:00 to 15:00

    def test_free_slots_no_slots_available(self) -> None:
        """When meetings span the entire 09:00-18:00 window, 0 free slots are returned."""
        events = [
            {
                "summary": "All Day Workshop",
                "start": {"dateTime": f"{self.date_str}T09:00:00+05:30"},
                "end": {"dateTime": f"{self.date_str}T18:00:00+05:30"},
            }
        ]
        slots = calculate_free_slots(events, self.date_str, duration_minutes=30, current_time=self.fake_now)
        self.assertEqual(len(slots), 0)

    def test_free_slots_duration_filtering(self) -> None:
        """Gaps smaller than the requested duration are omitted."""
        events = [
            {
                "summary": "Early Sync",
                "start": {"dateTime": f"{self.date_str}T09:00:00+05:30"},
                "end": {"dateTime": f"{self.date_str}T09:45:00+05:30"},
            },
            {
                "summary": "Second Sync",
                "start": {"dateTime": f"{self.date_str}T10:00:00+05:30"},
                "end": {"dateTime": f"{self.date_str}T18:00:00+05:30"},
            },
        ]
        # The 09:45 to 10:00 gap is 15 minutes.
        # A 30-minute meeting cannot fit, but a 15-minute meeting can.
        slots_30m = calculate_free_slots(events, self.date_str, duration_minutes=30, current_time=self.fake_now)
        self.assertEqual(len(slots_30m), 0)

        slots_15m = calculate_free_slots(events, self.date_str, duration_minutes=15, current_time=self.fake_now)
        self.assertEqual(len(slots_15m), 1)
        self.assertEqual((slots_15m[0][0].strftime("%H:%M"), slots_15m[0][1].strftime("%H:%M")), ("09:45", "10:00"))

    def test_free_slots_today_past_time_excluded(self) -> None:
        """When checking today's schedule, hours that have already passed are excluded."""
        today_str = "2026-10-20"
        # Current time is 14:00 today
        current_time_today = dt.datetime(2026, 10, 20, 14, 0, tzinfo=LOCAL_TZ)

        events: list[dict] = []
        slots = calculate_free_slots(events, today_str, duration_minutes=60, current_time=current_time_today)

        # Free slot should only start from 14:00 to 18:00
        self.assertEqual(len(slots), 1)
        start, end = slots[0]
        self.assertEqual(start.strftime("%H:%M"), "14:00")
        self.assertEqual(end.strftime("%H:%M"), "18:00")

    @patch("meeting_scheduler.tools.fetch_events_between")
    def test_find_free_slots_tool_formatting(self, mock_fetch: MagicMock) -> None:
        """The find_free_slots tool formats output as a readable string."""
        mock_fetch.return_value = []
        result = find_free_slots.invoke({"date": "2026-10-25", "duration_minutes": 45})
        self.assertIn("Free slots on 2026-10-25 for a 45-minute meeting:", result)
        self.assertIn("09:00 to 18:00", result)

    def test_find_free_slots_tool_invalid_duration(self) -> None:
        """Negative or zero durations return an explicit validation error."""
        result = find_free_slots.invoke({"date": "2026-10-25", "duration_minutes": 0})
        self.assertIn("Error: duration_minutes must be greater than 0", result)


if __name__ == "__main__":
    unittest.main()

