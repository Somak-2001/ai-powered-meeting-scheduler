"""Unit tests for conflict detection, interval math, and past-date validation."""

from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import MagicMock, patch

from meeting_scheduler.tools import (
    LOCAL_TZ,
    create_event,
    extract_timed_events,
    get_calendar_events,
    has_overlap,
    is_past_datetime,
    parse_local_datetime,
)


class TestConflictDetection(unittest.TestCase):
    """Test suite for interval overlap logic, past-date guards, and create_event validation."""

    def setUp(self) -> None:
        self.base_date = dt.date(2026, 9, 15)
        self.t10_00 = dt.datetime.combine(self.base_date, dt.time(10, 0), LOCAL_TZ)
        self.t10_30 = dt.datetime.combine(self.base_date, dt.time(10, 30), LOCAL_TZ)
        self.t11_00 = dt.datetime.combine(self.base_date, dt.time(11, 0), LOCAL_TZ)
        self.t11_30 = dt.datetime.combine(self.base_date, dt.time(11, 30), LOCAL_TZ)
        self.t12_00 = dt.datetime.combine(self.base_date, dt.time(12, 0), LOCAL_TZ)
        self.t09_00 = dt.datetime.combine(self.base_date, dt.time(9, 0), LOCAL_TZ)

    def test_overlapping_events_detected(self) -> None:
        """Verify partially overlapping events are flagged as conflicts."""
        # [10:00, 11:00) vs [10:30, 11:30)
        self.assertTrue(has_overlap(self.t10_00, self.t11_00, self.t10_30, self.t11_30))
        # Reverse order
        self.assertTrue(has_overlap(self.t10_30, self.t11_30, self.t10_00, self.t11_00))

    def test_adjacent_events_accepted(self) -> None:
        """Verify back-to-back adjacent meetings are NOT treated as conflicts."""
        # [10:00, 11:00) vs [11:00, 12:00)
        self.assertFalse(has_overlap(self.t10_00, self.t11_00, self.t11_00, self.t12_00))
        # [09:00, 10:00) vs [10:00, 11:00)
        self.assertFalse(has_overlap(self.t09_00, self.t10_00, self.t10_00, self.t11_00))

    def test_containing_overlap(self) -> None:
        """Verify when a new event encapsulates an existing event, it is flagged."""
        # New [09:00, 12:00) contains Existing [10:00, 11:00)
        self.assertTrue(has_overlap(self.t09_00, self.t12_00, self.t10_00, self.t11_00))

    def test_contained_overlap(self) -> None:
        """Verify when an existing event encapsulates a new event, it is flagged."""
        # New [10:00, 11:00) inside Existing [09:00, 12:00)
        self.assertTrue(has_overlap(self.t10_00, self.t11_00, self.t09_00, self.t12_00))

    def test_past_event_rejected(self) -> None:
        """Verify past-date check correctly rejects datetimes prior to current time."""
        current_time = dt.datetime(2026, 9, 15, 14, 0, tzinfo=LOCAL_TZ)
        past_target = dt.datetime(2026, 9, 15, 10, 0, tzinfo=LOCAL_TZ)
        self.assertTrue(is_past_datetime(past_target, current_time))

    def test_future_event_accepted(self) -> None:
        """Verify future datetimes pass the past-date validation check."""
        current_time = dt.datetime(2026, 9, 15, 14, 0, tzinfo=LOCAL_TZ)
        future_target = dt.datetime(2026, 9, 15, 15, 0, tzinfo=LOCAL_TZ)
        self.assertFalse(is_past_datetime(future_target, current_time))

    @patch("meeting_scheduler.tools.fetch_events_between")
    def test_create_event_past_date_guard(self, mock_fetch: MagicMock) -> None:
        """Calling create_event with a date in the past returns a clear error without querying API."""
        result = create_event.invoke({
            "title": "Old Meeting",
            "date": "2020-01-01",
            "start_time": "10:00",
            "duration_minutes": 30,
        })
        self.assertIn("Error: Cannot schedule an event in the past", result)
        mock_fetch.assert_not_called()

    @patch("meeting_scheduler.tools.fetch_events_between")
    def test_create_event_conflict_detected(self, mock_fetch: MagicMock) -> None:
        """Calling create_event on an occupied slot reports conflict and alternative instructions."""
        future_date = (dt.datetime.now(LOCAL_TZ) + dt.timedelta(days=2)).strftime("%Y-%m-%d")

        # Mock an existing meeting from 10:00 to 11:00
        mock_fetch.return_value = [{
            "summary": "Existing Sprint Planning",
            "start": {"dateTime": f"{future_date}T10:00:00+05:30"},
            "end": {"dateTime": f"{future_date}T11:00:00+05:30"},
        }]

        # Try booking 10:30 to 11:30 (overlap)
        result = create_event.invoke({
            "title": "New Sync",
            "date": future_date,
            "start_time": "10:30",
            "duration_minutes": 60,
        })

        self.assertIn("Conflict detected", result)
        self.assertIn("Existing Sprint Planning", result)
        self.assertIn("analyse_booking_patterns", result)

    @patch("meeting_scheduler.tools.get_calendar_service")
    @patch("meeting_scheduler.tools.fetch_events_between")
    def test_create_event_success(self, mock_fetch: MagicMock, mock_get_service: MagicMock) -> None:
        """Calling create_event on a free slot succeeds and returns confirmation link."""
        future_date = (dt.datetime.now(LOCAL_TZ) + dt.timedelta(days=3)).strftime("%Y-%m-%d")
        mock_fetch.return_value = []

        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.return_value = {"htmlLink": "https://calendar.google.com/event?eid=mock123"}
        mock_events.insert.return_value = mock_insert
        mock_service.events.return_value = mock_events
        mock_get_service.return_value = mock_service

        result = create_event.invoke({
            "title": "Design Discussion",
            "date": future_date,
            "start_time": "14:00",
            "duration_minutes": 45,
            "attendee_email": "colleague@example.com",
        })

        self.assertIn("Event created successfully", result)
        self.assertIn("https://calendar.google.com/event?eid=mock123", result)
        mock_events.insert.assert_called_once()

    def test_all_day_event_safety(self) -> None:
        """Verify all-day events are safely extracted without exceptions."""
        sample_events = [
            {
                "summary": "Company Holiday",
                "start": {"date": "2026-09-15"},
                "end": {"date": "2026-09-16"},
                "transparency": "transparent",
            },
            {
                "summary": "Out of Office Busy",
                "start": {"date": "2026-09-17"},
                "end": {"date": "2026-09-18"},
                "transparency": "opaque",
            },
        ]
        parsed = extract_timed_events(sample_events)
        self.assertEqual(len(parsed), 2)
        self.assertTrue(parsed[0]["is_all_day"])
        self.assertEqual(parsed[0]["event"]["transparency"], "transparent")
        self.assertEqual(parsed[1]["event"]["transparency"], "opaque")

    @patch("meeting_scheduler.tools.fetch_events_between")
    def test_transparent_timed_event_ignored_as_conflict(self, mock_fetch: MagicMock) -> None:
        """Timed events marked transparent ('Show as Available') should not cause conflicts."""
        future_date = (dt.datetime.now(LOCAL_TZ) + dt.timedelta(days=4)).strftime("%Y-%m-%d")
        mock_fetch.return_value = [{
            "summary": "Reminder / Tentative",
            "start": {"dateTime": f"{future_date}T10:00:00+05:30"},
            "end": {"dateTime": f"{future_date}T11:00:00+05:30"},
            "transparency": "transparent",
        }]

        with patch("meeting_scheduler.tools.get_calendar_service") as mock_get_service:
            mock_service = MagicMock()
            mock_events = MagicMock()
            mock_insert = MagicMock()
            mock_insert.execute.return_value = {"htmlLink": "https://calendar.google.com/event?eid=transparent_ok"}
            mock_events.insert.return_value = mock_insert
            mock_service.events.return_value = mock_events
            mock_get_service.return_value = mock_service

            result = create_event.invoke({
                "title": "Real Meeting",
                "date": future_date,
                "start_time": "10:00",
                "duration_minutes": 60,
            })
            self.assertIn("Event created successfully", result)

    def test_cancelled_event_ignored(self) -> None:
        """Cancelled events should be filtered out from active calendar events."""
        events = [
            {
                "summary": "Deleted Standup",
                "status": "cancelled",
                "start": {"dateTime": "2026-09-15T10:00:00+05:30"},
                "end": {"dateTime": "2026-09-15T11:00:00+05:30"},
            },
            {
                "summary": "Active Standup",
                "status": "confirmed",
                "start": {"dateTime": "2026-09-15T11:00:00+05:30"},
                "end": {"dateTime": "2026-09-15T12:00:00+05:30"},
            },
        ]
        parsed = extract_timed_events(events)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["event"]["summary"], "Active Standup")

    @patch("meeting_scheduler.tools.fetch_events_between")
    def test_get_calendar_events_all_cancelled(self, mock_fetch: MagicMock) -> None:
        """When all events on a date are cancelled, return 'No events found on {date}'."""
        mock_fetch.return_value = [
            {
                "summary": "Old Cancelled Event",
                "status": "cancelled",
                "start": {"dateTime": "2026-09-15T10:00:00+05:30"},
                "end": {"dateTime": "2026-09-15T11:00:00+05:30"},
            }
        ]
        result = get_calendar_events.invoke({"date": "2026-09-15"})
        self.assertEqual(result, "No events found on 2026-09-15.")

    @patch("meeting_scheduler.tools.fetch_events_between")
    def test_create_event_midnight_crossover(self, mock_fetch: MagicMock) -> None:
        """Meeting spanning past midnight checks conflict against next day's early hours."""
        future_date = (dt.datetime.now(LOCAL_TZ) + dt.timedelta(days=2)).strftime("%Y-%m-%d")
        next_date = (dt.datetime.now(LOCAL_TZ) + dt.timedelta(days=3)).strftime("%Y-%m-%d")

        # Mock an event at 00:15 on the following day
        mock_fetch.return_value = [{
            "summary": "Midnight Release Deploy",
            "start": {"dateTime": f"{next_date}T00:15:00+05:30"},
            "end": {"dateTime": f"{next_date}T01:00:00+05:30"},
        }]

        # Request meeting from 23:45 to 00:45 (spans midnight)
        result = create_event.invoke({
            "title": "Late Sync",
            "date": future_date,
            "start_time": "23:45",
            "duration_minutes": 60,
        })
        self.assertIn("Conflict detected", result)
        self.assertIn("Midnight Release Deploy", result)


if __name__ == "__main__":
    unittest.main()


