"""Unit tests for 30-day booking pattern analytics and heuristic metrics."""

from __future__ import annotations

import datetime as dt
import json
import unittest
from unittest.mock import MagicMock, patch

from meeting_scheduler.tools import (
    LOCAL_TZ,
    analyse_booking_patterns,
    compute_booking_metrics,
)


class TestBookingPatterns(unittest.TestCase):
    """Test suite for booking pattern aggregation and metrics generation."""

    def test_compute_booking_metrics_distribution(self) -> None:
        """Verify accurate aggregation of busiest days, lightest days, and preferred hours."""
        start_date = dt.date(2026, 8, 1)
        end_date = dt.date(2026, 8, 31)

        # Create 3 meetings on Monday at 10:00 (60 mins each)
        # Create 1 meeting on Wednesday at 14:00 (30 mins)
        # Create 0 meetings on Thursday, Friday, etc.
        events = [
            # Monday meetings (Aug 3, Aug 10, Aug 17)
            {
                "summary": "Monday Sprint",
                "start": {"dateTime": "2026-08-03T10:00:00+05:30"},
                "end": {"dateTime": "2026-08-03T11:00:00+05:30"},
            },
            {
                "summary": "Monday Review",
                "start": {"dateTime": "2026-08-10T10:00:00+05:30"},
                "end": {"dateTime": "2026-08-10T11:00:00+05:30"},
            },
            {
                "summary": "Monday Sync",
                "start": {"dateTime": "2026-08-17T10:00:00+05:30"},
                "end": {"dateTime": "2026-08-17T11:00:00+05:30"},
            },
            # Wednesday meeting (Aug 05)
            {
                "summary": "Wednesday 1-on-1",
                "start": {"dateTime": "2026-08-05T14:00:00+05:30"},
                "end": {"dateTime": "2026-08-05T14:30:00+05:30"},
            },
        ]

        metrics = compute_booking_metrics(events, start_date, end_date)

        self.assertEqual(metrics["total_timed_meetings"], 4)
        # Monday should be the busiest day with 3 meetings
        self.assertEqual(metrics["busiest_days"][0]["day"], "Monday")
        self.assertEqual(metrics["busiest_days"][0]["meetings"], 3)

        # Lightest days should have 0 meetings (e.g. Tuesday, Thursday, etc.)
        lightest_counts = [d["meetings"] for d in metrics["lightest_days"]]
        self.assertIn(0, lightest_counts)

        # Preferred hour should be 10:00 (3 meetings)
        self.assertEqual(metrics["preferred_start_hours"][0]["hour"], "10:00")
        self.assertEqual(metrics["preferred_start_hours"][0]["meetings"], 3)

        # Average duration: (60 + 60 + 60 + 30) / 4 = 52.5 mins -> "52m"
        self.assertEqual(metrics["average_duration"], "52m")

        # Upcoming lightest dates should exist and have dates
        self.assertTrue(len(metrics["upcoming_lightest_dates"]) > 0)
        self.assertIn("date", metrics["upcoming_lightest_dates"][0])

    def test_compute_booking_metrics_empty_calendar(self) -> None:
        """When no timed events exist in the period, metrics return safely without division by zero."""
        start_date = dt.date(2026, 8, 1)
        end_date = dt.date(2026, 8, 31)

        metrics = compute_booking_metrics([], start_date, end_date)
        self.assertEqual(metrics["total_timed_meetings"], 0)
        self.assertEqual(metrics["average_duration"], "0m")
        self.assertEqual(len(metrics["busiest_days"]), 0)
        self.assertTrue(len(metrics["lightest_days"]) > 0)
        self.assertIn("No timed meetings found", metrics["message"])

    @patch("meeting_scheduler.tools.get_calendar_service")
    def test_analyse_booking_patterns_tool_json(self, mock_get_service: MagicMock) -> None:
        """The analyse_booking_patterns tool returns a valid structured JSON string."""
        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_list = MagicMock()
        mock_list.execute.return_value = {"items": []}
        mock_events.list.return_value = mock_list
        mock_service.events.return_value = mock_events
        mock_get_service.return_value = mock_service

        raw_result = analyse_booking_patterns.invoke({})
        parsed = json.loads(raw_result)
        self.assertIn("total_timed_meetings", parsed)
        self.assertIn("busiest_days", parsed)
        self.assertIn("lightest_days", parsed)
        self.assertIn("average_duration", parsed)


if __name__ == "__main__":
    unittest.main()

