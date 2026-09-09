"""Unit tests for calendar intelligence queries, analytics, and summary statistics."""

from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import MagicMock, patch

from meeting_scheduler.tools import (
    LOCAL_TZ,
    compute_calendar_insights,
    query_calendar_insights,
)


class TestCalendarInsights(unittest.TestCase):
    """Test suite for calendar intelligence analytics and deterministic answers."""

    def setUp(self) -> None:
        self.period_start = dt.datetime(2026, 9, 14, 0, 0, tzinfo=LOCAL_TZ)  # Monday
        self.period_end = dt.datetime(2026, 9, 21, 0, 0, tzinfo=LOCAL_TZ)    # Next Monday
        self.label = "this week"

        # Mock events: 2 meetings on Monday, 1 meeting on Wednesday, other days free
        self.events = [
            {
                "summary": "Design Sync",
                "start": {"dateTime": "2026-09-14T10:00:00+05:30"},
                "end": {"dateTime": "2026-09-14T11:00:00+05:30"},  # 60m
            },
            {
                "summary": "Code Review",
                "start": {"dateTime": "2026-09-14T15:00:00+05:30"},
                "end": {"dateTime": "2026-09-14T16:00:00+05:30"},  # 60m
            },
            {
                "summary": "Architecture Discussion",
                "start": {"dateTime": "2026-09-16T11:00:00+05:30"},
                "end": {"dateTime": "2026-09-16T12:30:00+05:30"},  # 90m
            },
        ]

    def test_free_days_query(self) -> None:
        """'Which days am I free this week?' should identify days with 0 timed events."""
        ans = compute_calendar_insights(
            "Which days am I free this week?",
            self.events,
            self.period_start,
            self.period_end,
            self.label,
        )
        self.assertIn("Free days in this week:", ans)
        # Tuesday, Thursday, Friday, Saturday, Sunday should be in free days
        self.assertIn("Tuesday", ans)
        self.assertIn("Thursday", ans)
        self.assertIn("Friday", ans)
        # Monday and Wednesday have meetings so shouldn't be listed as completely free
        self.assertNotIn("Monday, 2026-09-14", ans)
        self.assertNotIn("Wednesday, 2026-09-16", ans)

    def test_busiest_day_query(self) -> None:
        """'What was my busiest day this month?' should pinpoint the day with the highest count."""
        ans = compute_calendar_insights(
            "What was my busiest day this week?",
            self.events,
            self.period_start,
            self.period_end,
            self.label,
        )
        self.assertIn("Busiest day in this week:", ans)
        self.assertIn("Monday, 2026-09-14 with 2 meetings", ans)

    def test_meeting_hours_query(self) -> None:
        """'How many hours of meetings do I have this week?' correctly sums meeting durations."""
        # Total minutes: 60 + 60 + 90 = 210 minutes = 3h 30m
        ans = compute_calendar_insights(
            "How many hours of meetings do I have this week?",
            self.events,
            self.period_start,
            self.period_end,
            self.label,
        )
        self.assertIn("3h 30m of meetings in this week across 3 events", ans)

    def test_empty_calendar_insights(self) -> None:
        """Empty calendar returns clear, polite indicators."""
        ans_busiest = compute_calendar_insights(
            "What was my busiest day this week?",
            [],
            self.period_start,
            self.period_end,
            self.label,
        )
        self.assertEqual(ans_busiest, "No meetings found in this week.")

        ans_hours = compute_calendar_insights(
            "How many hours of meetings do I have this week?",
            [],
            self.period_start,
            self.period_end,
            self.label,
        )
        self.assertIn("0m of meetings in this week across 0 events", ans_hours)

    @patch("meeting_scheduler.tools.fetch_events_between")
    def test_query_calendar_insights_tool_invocation(self, mock_fetch: MagicMock) -> None:
        """Calling query_calendar_insights tool handles dispatch and returns answer."""
        mock_fetch.return_value = self.events
        res = query_calendar_insights.invoke({"question": "Which days am I free this week?"})
        self.assertIn("Free days in this week", res)


if __name__ == "__main__":
    unittest.main()

