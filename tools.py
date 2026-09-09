"""Backward-compatibility re-export for tools module."""

import sys
from pathlib import Path

workspace_dir = str(Path(__file__).resolve().parent)
if workspace_dir not in sys.path:
    sys.path.insert(0, workspace_dir)

from meeting_scheduler.tools import (
    CREDENTIALS_PATH,
    DEFAULT_CALENDAR_ID,
    LOCAL_TZ,
    SCOPES,
    TIME_ZONE_NAME,
    TOKEN_PATH,
    WORKDAY_END_HOUR,
    WORKDAY_START_HOUR,
    analyse_booking_patterns,
    as_aware,
    calculate_free_slots,
    compute_booking_metrics,
    compute_calendar_insights,
    create_event,
    extract_timed_events,
    fetch_events_between,
    find_free_slots,
    format_duration_str,
    format_time_str,
    get_calendar_events,
    get_calendar_service,
    get_day_bounds,
    get_local_timezone,
    get_upcoming_date_for_weekday,
    has_overlap,
    is_past_datetime,
    merge_busy_intervals,
    parse_iso_datetime,
    parse_local_datetime,
    query_calendar_insights,
)

__all__ = [
    "SCOPES",
    "TIME_ZONE_NAME",
    "DEFAULT_CALENDAR_ID",
    "WORKDAY_START_HOUR",
    "WORKDAY_END_HOUR",
    "CREDENTIALS_PATH",
    "TOKEN_PATH",
    "LOCAL_TZ",
    "get_local_timezone",
    "as_aware",
    "parse_local_datetime",
    "parse_iso_datetime",
    "get_day_bounds",
    "format_time_str",
    "format_duration_str",
    "get_upcoming_date_for_weekday",
    "has_overlap",
    "is_past_datetime",
    "extract_timed_events",
    "merge_busy_intervals",
    "calculate_free_slots",
    "compute_booking_metrics",
    "compute_calendar_insights",
    "get_calendar_service",
    "fetch_events_between",
    "get_calendar_events",
    "create_event",
    "find_free_slots",
    "analyse_booking_patterns",
    "query_calendar_insights",
]
