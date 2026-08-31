import datetime as dt
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from langchain_core.tools import tool


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TIME_ZONE = os.getenv("CALENDAR_TIME_ZONE", "Asia/Kolkata")
DEFAULT_CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")
WORKDAY_START_HOUR = 9
WORKDAY_END_HOUR = 18

TOKEN_PATH = BASE_DIR / "token.json"
CREDENTIALS_PATH = BASE_DIR / "credentials.json"


def _local_timezone() -> dt.timezone:
    if TIME_ZONE == "Asia/Kolkata":
        return dt.timezone(dt.timedelta(hours=5, minutes=30), name=TIME_ZONE)
    return dt.datetime.now().astimezone().tzinfo or dt.timezone.utc


LOCAL_TZ = _local_timezone()


def _as_aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def _parse_local_datetime(date: str, time_value: str) -> dt.datetime:
    parsed = dt.datetime.strptime(f"{date} {time_value}", "%Y-%m-%d %H:%M")
    return parsed.replace(tzinfo=LOCAL_TZ)


def _event_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return _as_aware(dt.datetime.fromisoformat(normalized))


def _day_bounds(date: str) -> tuple[dt.datetime, dt.datetime]:
    day = dt.datetime.strptime(date, "%Y-%m-%d").date()
    start = dt.datetime.combine(day, dt.time.min, LOCAL_TZ)
    end = start + dt.timedelta(days=1)
    return start, end


def _format_time(value: dt.datetime | None) -> str:
    if value is None:
        return "all day"
    return _as_aware(value).strftime("%H:%M")


def _format_duration(minutes: float) -> str:
    hours = int(minutes // 60)
    remaining_minutes = int(minutes % 60)
    if hours and remaining_minutes:
        return f"{hours}h {remaining_minutes}m"
    if hours:
        return f"{hours}h"
    return f"{remaining_minutes}m"


def _upcoming_date_for_weekday(weekday_name: str, after: dt.date | None = None) -> str:
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    base = after or dt.datetime.now(LOCAL_TZ).date()
    target = weekdays.index(weekday_name)
    days_ahead = (target - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (base + dt.timedelta(days=days_ahead)).isoformat()


def get_calendar_service():
    """Authenticate with Google Calendar and return a Calendar API service."""
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds or not creds.valid:
        if not CREDENTIALS_PATH.exists():
            raise FileNotFoundError(
                f"Missing {CREDENTIALS_PATH}. Download OAuth credentials from "
                "Google Cloud Console, rename the file to credentials.json, and "
                "place it inside the meeting_scheduler folder."
            )

        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(
            port=0,
            open_browser=False,
            authorization_prompt_message="\n-> Go to this URL:\n{url}\n",
            success_message="Authentication complete. You can close this browser tab.",
            timeout_seconds=300,
            prompt="consent",
        )

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=creds)


def _list_events_between(start: dt.datetime, end: dt.datetime) -> list[dict[str, Any]]:
    service = get_calendar_service()
    response = (
        service.events()
        .list(
            calendarId=DEFAULT_CALENDAR_ID,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return response.get("items", [])


def _timed_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timed = []
    for event in events:
        start = _event_time(event.get("start", {}).get("dateTime"))
        end = _event_time(event.get("end", {}).get("dateTime"))
        if start and end:
            timed.append({"event": event, "start": start, "end": end})
    return timed


def _find_free_slots_for_date(date: str, duration_minutes: int) -> list[tuple[dt.datetime, dt.datetime]]:
    day = dt.datetime.strptime(date, "%Y-%m-%d").date()
    window_start = dt.datetime.combine(day, dt.time(WORKDAY_START_HOUR, 0), LOCAL_TZ)
    window_end = dt.datetime.combine(day, dt.time(WORKDAY_END_HOUR, 0), LOCAL_TZ)
    required = dt.timedelta(minutes=duration_minutes)

    events = _timed_events(_list_events_between(window_start, window_end))
    busy_ranges = sorted(
        (
            (max(item["start"], window_start), min(item["end"], window_end))
            for item in events
            if item["start"] < window_end and item["end"] > window_start
        ),
        key=lambda item: item[0],
    )

    free_slots: list[tuple[dt.datetime, dt.datetime]] = []
    cursor = window_start
    for busy_start, busy_end in busy_ranges:
        if busy_start > cursor and busy_start - cursor >= required:
            free_slots.append((cursor, busy_start))
        cursor = max(cursor, busy_end)

    if window_end > cursor and window_end - cursor >= required:
        free_slots.append((cursor, window_end))

    return free_slots


@tool
def get_calendar_events(date: str) -> str:
    """
    Fetch all Google Calendar events on a date.

    Args:
        date: Date in YYYY-MM-DD format.

    Returns:
        A readable list with event title, start time, and end time.
    """
    start, end = _day_bounds(date)
    events = _list_events_between(start, end)

    if not events:
        return f"No events found on {date}."

    lines = [f"Events on {date}:"]
    for event in events:
        title = event.get("summary", "Untitled event")
        start_value = event.get("start", {})
        end_value = event.get("end", {})
        start_time = _event_time(start_value.get("dateTime"))
        end_time = _event_time(end_value.get("dateTime"))
        if not start_time and start_value.get("date"):
            lines.append(f"- {title}: all day")
        else:
            lines.append(f"- {title}: {_format_time(start_time)} to {_format_time(end_time)}")

    return "\n".join(lines)


@tool
def create_event(
    title: str,
    date: str,
    start_time: str,
    duration_minutes: int,
    attendee_email: str | None = None,
) -> str:
    """
    Create a conflict-aware Google Calendar event.

    Args:
        title: Meeting title.
        date: Date in YYYY-MM-DD format.
        start_time: Start time in HH:MM 24-hour format.
        duration_minutes: Duration of the meeting in minutes.
        attendee_email: Optional attendee email address.

    Returns:
        Confirmation link, or a clear error if the time is invalid or blocked.
    """
    try:
        start_dt = _parse_local_datetime(date, start_time)
    except ValueError:
        return "Error: date must be YYYY-MM-DD and start_time must be HH:MM in 24-hour format."

    end_dt = start_dt + dt.timedelta(minutes=duration_minutes)
    if duration_minutes <= 0:
        return "Error: duration_minutes must be greater than 0."

    now = dt.datetime.now(LOCAL_TZ)
    if start_dt < now:
        return (
            f"Error: Cannot create an event in the past. Requested start was "
            f"{start_dt.strftime('%Y-%m-%d %H:%M %Z')}; current time is "
            f"{now.strftime('%Y-%m-%d %H:%M %Z')}."
        )

    existing_events = _timed_events(_list_events_between(*_day_bounds(date)))
    conflicts = [
        item
        for item in existing_events
        if start_dt < item["end"] and end_dt > item["start"]
    ]

    if conflicts:
        conflict_text = "; ".join(
            f"{item['event'].get('summary', 'Untitled event')} "
            f"({_format_time(item['start'])}-{_format_time(item['end'])})"
            for item in conflicts
        )
        return (
            f"Conflict detected: {date} {start_time} for {duration_minutes} minutes "
            f"overlaps with {conflict_text}. Please call analyse_booking_patterns "
            "and find_free_slots to suggest alternatives."
        )

    service = get_calendar_service()
    event_body: dict[str, Any] = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": TIME_ZONE},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": TIME_ZONE},
    }
    if attendee_email:
        event_body["attendees"] = [{"email": attendee_email}]

    created_event = (
        service.events()
        .insert(calendarId=DEFAULT_CALENDAR_ID, body=event_body)
        .execute()
    )
    return f"Event created successfully: {created_event.get('htmlLink')}"


@tool
def find_free_slots(date: str, duration_minutes: int) -> str:
    """
    Find available working-hours slots on a date.

    Args:
        date: Date in YYYY-MM-DD format.
        duration_minutes: Required meeting duration in minutes.

    Returns:
        Every 9am-6pm gap large enough for the meeting.
    """
    if duration_minutes <= 0:
        return "Error: duration_minutes must be greater than 0."

    slots = _find_free_slots_for_date(date, duration_minutes)
    if not slots:
        return f"No free slots of at least {duration_minutes} minutes found on {date} between 09:00 and 18:00."

    lines = [f"Free slots on {date} for a {duration_minutes}-minute meeting:"]
    for start, end in slots:
        lines.append(f"- {start.strftime('%H:%M')} to {end.strftime('%H:%M')}")
    return "\n".join(lines)


@tool
def analyse_booking_patterns() -> str:
    """
    Analyse the user's calendar history from the last 30 days.

    Returns:
        Structured summary with busiest days, lightest days, preferred hours, and average duration.
    """
    now = dt.datetime.now(LOCAL_TZ)
    start = now - dt.timedelta(days=30)
    service = get_calendar_service()
    response = (
        service.events()
        .list(
            calendarId=DEFAULT_CALENDAR_ID,
            timeMin=start.isoformat(),
            timeMax=now.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=200,
        )
        .execute()
    )
    events = _timed_events(response.get("items", []))

    if not events:
        return "No timed meetings found in the last 30 days. Any normal working-hour slot is likely reasonable."

    day_counts = Counter(item["start"].strftime("%A") for item in events)
    hour_counts = Counter(item["start"].hour for item in events)
    durations = [
        (item["end"] - item["start"]).total_seconds() / 60
        for item in events
        if item["end"] > item["start"]
    ]
    average_duration = sum(durations) / len(durations) if durations else 0

    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    busiest = day_counts.most_common(3)
    lightest = sorted(weekdays, key=lambda day: (day_counts.get(day, 0), weekdays.index(day)))[:3]
    preferred_hours = hour_counts.most_common(3)

    summary = {
        "period": f"{start.date()} to {now.date()}",
        "total_timed_meetings": len(events),
        "busiest_days": [{"day": day, "meetings": count} for day, count in busiest],
        "lightest_days": [{"day": day, "meetings": day_counts.get(day, 0)} for day in lightest],
        "upcoming_lightest_dates": [
            {
                "day": day,
                "date": _upcoming_date_for_weekday(day, now.date()),
                "past_30_day_meetings": day_counts.get(day, 0),
            }
            for day in lightest
        ],
        "preferred_start_hours": [
            {"hour": f"{hour:02d}:00", "meetings": count} for hour, count in preferred_hours
        ],
        "average_duration": _format_duration(average_duration),
    }
    return json.dumps(summary, indent=2)


@tool
def query_calendar_insights(question: str) -> str:
    """
    Answer calendar intelligence questions using computed calendar statistics.

    Args:
        question: Natural-language question about the calendar.

    Returns:
        A data-backed answer for common questions such as free days, busiest day, or meeting hours.
    """
    now = dt.datetime.now(LOCAL_TZ)
    question_lower = question.lower()

    if "month" in question_lower:
        start = dt.datetime(now.year, now.month, 1, tzinfo=LOCAL_TZ)
        if now.month == 12:
            end = dt.datetime(now.year + 1, 1, 1, tzinfo=LOCAL_TZ)
        else:
            end = dt.datetime(now.year, now.month + 1, 1, tzinfo=LOCAL_TZ)
        label = f"{start.strftime('%B %Y')}"
    elif "last 30" in question_lower or "past 30" in question_lower:
        start = now - dt.timedelta(days=30)
        end = now
        label = "the last 30 days"
    else:
        start = dt.datetime.combine((now - dt.timedelta(days=now.weekday())).date(), dt.time.min, LOCAL_TZ)
        end = start + dt.timedelta(days=7)
        label = "this week"

    events = _timed_events(_list_events_between(start, end))
    total_minutes = sum((item["end"] - item["start"]).total_seconds() / 60 for item in events)

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in events:
        by_date[item["start"].date().isoformat()].append(item)

    if "free" in question_lower:
        days = []
        cursor = start.date()
        while cursor < end.date():
            if cursor.isoformat() not in by_date:
                days.append(cursor.strftime("%A, %Y-%m-%d"))
            cursor += dt.timedelta(days=1)
        if days:
            return f"Free days in {label}: " + "; ".join(days)
        return f"No completely free days found in {label}."

    if "busiest" in question_lower:
        if not by_date:
            return f"No meetings found in {label}."
        busiest_date, busiest_events = max(by_date.items(), key=lambda item: len(item[1]))
        return f"Busiest day in {label}: {busiest_date} with {len(busiest_events)} meetings."

    if "how many hours" in question_lower or "meeting hours" in question_lower:
        return f"You have {_format_duration(total_minutes)} of meetings in {label} across {len(events)} events."

    return (
        f"For {label}: {len(events)} timed events, {_format_duration(total_minutes)} total meeting time. "
        f"Ask specifically about free days, busiest day, or meeting hours for a more focused answer."
    )
