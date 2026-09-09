"""Google Calendar tools and scheduling logic for LangChain agent."""

from __future__ import annotations

import datetime as dt
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        """Lightweight .env loader fallback if python-dotenv is not installed."""
        env_file = args[0] if args else Path(".env")
        try:
            p = Path(env_file)
            if p.exists() and p.is_file():
                for line in p.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
                return True
        except Exception:
            pass
        return False

# Optional import of langchain_core tool decorator with lightweight fallback for pure testing
try:
    from langchain_core.tools import tool
except ImportError:
    def tool(func: Callable | None = None, *args: Any, **kwargs: Any) -> Any:
        def decorator(f: Callable) -> Callable:
            setattr(f, "name", f.__name__)
            setattr(f, "invoke", lambda args_dict: f(**args_dict))
            return f

        if func is not None:
            return decorator(func)
        return decorator


# ---------------------------------------------------------------------------
# Paths and Environment Configuration
# ---------------------------------------------------------------------------
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

# Load .env from project root if present, else package dir
if (PROJECT_ROOT / ".env").exists():
    load_dotenv(PROJECT_ROOT / ".env")
elif (PACKAGE_DIR / ".env").exists():
    load_dotenv(PACKAGE_DIR / ".env")
else:
    load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TIME_ZONE_NAME = os.getenv("CALENDAR_TIME_ZONE", "Asia/Kolkata")
DEFAULT_CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")
WORKDAY_START_HOUR = int(os.getenv("WORKDAY_START_HOUR", "9"))
WORKDAY_END_HOUR = int(os.getenv("WORKDAY_END_HOUR", "18"))


def _resolve_file_path(env_var: str, default_name: str) -> Path:
    """Find a configuration file by checking env var, project root, and package dir."""
    if os.getenv(env_var):
        return Path(os.getenv(env_var)).resolve()
    if (PROJECT_ROOT / default_name).exists():
        return PROJECT_ROOT / default_name
    return PROJECT_ROOT / default_name


CREDENTIALS_PATH = _resolve_file_path("CREDENTIALS_PATH", "credentials.json")
TOKEN_PATH = _resolve_file_path("TOKEN_PATH", "token.json")


# ---------------------------------------------------------------------------
# Timezone Utilities
# ---------------------------------------------------------------------------
def get_local_timezone() -> dt.tzinfo:
    """Return timezone object for configured TIME_ZONE_NAME."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TIME_ZONE_NAME)
    except Exception:
        if TIME_ZONE_NAME == "Asia/Kolkata":
            return dt.timezone(dt.timedelta(hours=5, minutes=30), name=TIME_ZONE_NAME)
        return dt.datetime.now().astimezone().tzinfo or dt.timezone.utc


LOCAL_TZ = get_local_timezone()


def as_aware(value: dt.datetime) -> dt.datetime:
    """Ensure datetime is timezone-aware and aligned with LOCAL_TZ."""
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def parse_local_datetime(date_str: str, time_str: str) -> dt.datetime:
    """Parse 'YYYY-MM-DD' and 'HH:MM' (or 'HH:MM:SS') into a timezone-aware datetime."""
    clean_date = date_str.strip()
    clean_time = time_str.strip()
    if len(clean_time.split(":")) == 3:
        parsed = dt.datetime.strptime(f"{clean_date} {clean_time}", "%Y-%m-%d %H:%M:%S")
    else:
        parsed = dt.datetime.strptime(f"{clean_date} {clean_time}", "%Y-%m-%d %H:%M")
    return parsed.replace(tzinfo=LOCAL_TZ)


def parse_iso_datetime(value: str | None) -> dt.datetime | None:
    """Parse an ISO 8601 string from Google Calendar API into a timezone-aware datetime."""
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return as_aware(dt.datetime.fromisoformat(normalized))


def get_day_bounds(date_str: str) -> tuple[dt.datetime, dt.datetime]:
    """Return timezone-aware [start_of_day, end_of_day) for a 'YYYY-MM-DD' string."""
    day = dt.datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    start = dt.datetime.combine(day, dt.time.min, LOCAL_TZ)
    end = start + dt.timedelta(days=1)
    return start, end


def format_time_str(value: dt.datetime | None) -> str:
    """Format datetime as HH:MM 24-hour string."""
    if value is None:
        return "all day"
    return as_aware(value).strftime("%H:%M")


def format_duration_str(minutes: float) -> str:
    """Format minutes into human-readable hours and minutes."""
    hours = int(minutes // 60)
    rem_min = int(minutes % 60)
    if hours and rem_min:
        return f"{hours}h {rem_min}m"
    if hours:
        return f"{hours}h"
    return f"{rem_min}m"


def get_upcoming_date_for_weekday(weekday_name: str, after: dt.date | None = None) -> str:
    """Return next occurrence of a weekday in 'YYYY-MM-DD' format."""
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    base = after or dt.datetime.now(LOCAL_TZ).date()
    weekday_clean = weekday_name.strip().capitalize()
    if weekday_clean not in weekdays:
        return base.isoformat()
    target = weekdays.index(weekday_clean)
    days_ahead = (target - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (base + dt.timedelta(days=days_ahead)).isoformat()


# ---------------------------------------------------------------------------
# Pure Algorithmic Scheduling Logic (Unit-Testable without Mocks)
# ---------------------------------------------------------------------------
def has_overlap(start_a: dt.datetime, end_a: dt.datetime, start_b: dt.datetime, end_b: dt.datetime) -> bool:
    """
    Standard half-open interval overlap check:
    Returns True if intervals [start_a, end_a) and [start_b, end_b) overlap.
    Adjacent events (end_a == start_b) do NOT overlap.
    """
    return start_a < end_b and end_a > start_b


def is_past_datetime(dt_target: dt.datetime, current_time: dt.datetime | None = None) -> bool:
    """Check if target datetime is strictly in the past relative to current_time."""
    now = current_time or dt.datetime.now(LOCAL_TZ)
    return as_aware(dt_target) < as_aware(now)


def extract_timed_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract and parse start and end datetimes for timed and opaque all-day events."""
    parsed_events: list[dict[str, Any]] = []
    for item in events:
        if item.get("status") == "cancelled":
            continue
        start_raw = item.get("start", {})
        end_raw = item.get("end", {})

        # Timed event
        if start_raw.get("dateTime"):
            start_dt = parse_iso_datetime(start_raw.get("dateTime"))
            end_dt = parse_iso_datetime(end_raw.get("dateTime"))
            if start_dt and end_dt:
                parsed_events.append({
                    "event": item,
                    "start": start_dt,
                    "end": end_dt,
                    "is_all_day": False,
                })
        # All-day event
        elif start_raw.get("date"):
            start_date_str = start_raw.get("date")
            end_date_str = end_raw.get("date", start_date_str)
            try:
                start_date = dt.datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = dt.datetime.strptime(end_date_str, "%Y-%m-%d").date()
                start_dt = dt.datetime.combine(start_date, dt.time.min, LOCAL_TZ)
                end_dt = dt.datetime.combine(end_date, dt.time.min, LOCAL_TZ)
                parsed_events.append({
                    "event": item,
                    "start": start_dt,
                    "end": end_dt,
                    "is_all_day": True,
                })
            except ValueError:
                continue
    return parsed_events


def merge_busy_intervals(
    intervals: list[tuple[dt.datetime, dt.datetime]]
) -> list[tuple[dt.datetime, dt.datetime]]:
    """Sort and merge overlapping or contiguous busy intervals."""
    if not intervals:
        return []
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged: list[tuple[dt.datetime, dt.datetime]] = [sorted_intervals[0]]

    for current_start, current_end in sorted_intervals[1:]:
        last_start, last_end = merged[-1]
        if current_start <= last_end:  # Overlapping or contiguous
            merged[-1] = (last_start, max(last_end, current_end))
        else:
            merged.append((current_start, current_end))
    return merged


def calculate_free_slots(
    events: list[dict[str, Any]],
    date_str: str,
    duration_minutes: int,
    current_time: dt.datetime | None = None,
) -> list[tuple[dt.datetime, dt.datetime]]:
    """
    Calculate all available slots of at least duration_minutes between 09:00 and 18:00.
    Merges busy intervals and filters out past time if date_str is today.
    """
    day = dt.datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    window_start = dt.datetime.combine(day, dt.time(WORKDAY_START_HOUR, 0), LOCAL_TZ)
    window_end = dt.datetime.combine(day, dt.time(WORKDAY_END_HOUR, 0), LOCAL_TZ)
    required = dt.timedelta(minutes=duration_minutes)

    now = current_time or dt.datetime.now(LOCAL_TZ)
    # If checking today, working window cannot start in the past
    if day == now.date() and now > window_start:
        window_start = now

    if window_start >= window_end:
        return []

    parsed = extract_timed_events(events)
    raw_busy = [
        (max(item["start"], window_start), min(item["end"], window_end))
        for item in parsed
        if item["start"] < window_end and item["end"] > window_start
        # If it's all-day, only count if opaque (busy)
        and (not item["is_all_day"] or item["event"].get("transparency") != "transparent")
    ]

    merged_busy = merge_busy_intervals(raw_busy)

    free_slots: list[tuple[dt.datetime, dt.datetime]] = []
    cursor = window_start
    for busy_start, busy_end in merged_busy:
        if busy_start > cursor and (busy_start - cursor) >= required:
            free_slots.append((cursor, busy_start))
        cursor = max(cursor, busy_end)

    if window_end > cursor and (window_end - cursor) >= required:
        free_slots.append((cursor, window_end))

    return free_slots


def compute_booking_metrics(
    events: list[dict[str, Any]],
    start_date: dt.date,
    end_date: dt.date,
) -> dict[str, Any]:
    """Compute booking patterns from timed events within a date range."""
    parsed = extract_timed_events(events)
    # Filter to strictly timed events for meeting patterns
    timed = [item for item in parsed if not item["is_all_day"]]

    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    if not timed:
        return {
            "period": f"{start_date} to {end_date}",
            "total_timed_meetings": 0,
            "busiest_days": [],
            "lightest_days": [{"day": day, "meetings": 0} for day in weekdays[:3]],
            "upcoming_lightest_dates": [
                {"day": day, "date": get_upcoming_date_for_weekday(day, end_date), "past_30_day_meetings": 0}
                for day in weekdays[:3]
            ],
            "preferred_start_hours": [],
            "average_duration": "0m",
            "message": "No timed meetings found in the period. Normal working-hour slots are available.",
        }

    day_counts = Counter(item["start"].strftime("%A") for item in timed)
    hour_counts = Counter(item["start"].hour for item in timed)
    durations = [
        (item["end"] - item["start"]).total_seconds() / 60
        for item in timed
        if item["end"] > item["start"]
    ]
    avg_duration = sum(durations) / len(durations) if durations else 0

    busiest = [{"day": d, "meetings": c} for d, c in day_counts.most_common(3)]
    lightest_names = sorted(weekdays, key=lambda d: (day_counts.get(d, 0), weekdays.index(d)))[:3]
    lightest = [{"day": d, "meetings": day_counts.get(d, 0)} for d in lightest_names]
    preferred_hours = [
        {"hour": f"{h:02d}:00", "meetings": c}
        for h, c in hour_counts.most_common(3)
    ]

    return {
        "period": f"{start_date} to {end_date}",
        "total_timed_meetings": len(timed),
        "busiest_days": busiest,
        "lightest_days": lightest,
        "upcoming_lightest_dates": [
            {
                "day": d,
                "date": get_upcoming_date_for_weekday(d, end_date),
                "past_30_day_meetings": day_counts.get(d, 0),
            }
            for d in lightest_names
        ],
        "preferred_start_hours": preferred_hours,
        "average_duration": format_duration_str(avg_duration),
    }


def compute_calendar_insights(
    question: str,
    events: list[dict[str, Any]],
    period_start: dt.datetime,
    period_end: dt.datetime,
    label: str,
) -> str:
    """Compute deterministic answers for calendar intelligence questions."""
    parsed = extract_timed_events(events)
    timed = [item for item in parsed if not item["is_all_day"]]
    q_lower = question.lower()

    total_minutes = sum((item["end"] - item["start"]).total_seconds() / 60 for item in timed)

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in timed:
        by_date[item["start"].date().isoformat()].append(item)

    if "free" in q_lower:
        free_days: list[str] = []
        cursor = period_start.date()
        while cursor < period_end.date():
            if cursor.isoformat() not in by_date:
                free_days.append(cursor.strftime("%A, %Y-%m-%d"))
            cursor += dt.timedelta(days=1)
        if free_days:
            return f"Free days in {label}: " + "; ".join(free_days)
        return f"No completely free days found in {label}."

    if "busiest" in q_lower:
        if not by_date:
            return f"No meetings found in {label}."
        busiest_date, busiest_list = max(by_date.items(), key=lambda item: len(item[1]))
        date_obj = dt.datetime.strptime(busiest_date, "%Y-%m-%d").date()
        formatted_day = date_obj.strftime("%A, %Y-%m-%d")
        return f"Busiest day in {label}: {formatted_day} with {len(busiest_list)} meetings."

    if "how many hours" in q_lower or "hours" in q_lower or "meeting time" in q_lower:
        return f"You have {format_duration_str(total_minutes)} of meetings in {label} across {len(timed)} events."

    return (
        f"For {label}: {len(timed)} meetings, {format_duration_str(total_minutes)} total scheduled time. "
        f"You can ask about free days, your busiest day, or total meeting hours."
    )


# ---------------------------------------------------------------------------
# Google Calendar Service Authentication
# ---------------------------------------------------------------------------
_calendar_service_instance = None


def get_calendar_service():
    """
    Authenticate with Google Calendar API using cached token or OAuth credentials.
    Returns a Google Calendar API service resource.
    """
    global _calendar_service_instance
    if _calendar_service_instance is not None:
        return _calendar_service_instance

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = None

    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except Exception as exc:
            print(f"[Auth Warning] Failed to load token from {TOKEN_PATH}: {exc}")
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            print(f"[Auth Warning] Failed to refresh token: {exc}")
            creds = None

    if not creds or not creds.valid:
        if not CREDENTIALS_PATH.exists():
            raise FileNotFoundError(
                f"Missing OAuth credentials file at {CREDENTIALS_PATH}. "
                "Download your OAuth 2.0 Client ID (Desktop App) from Google Cloud Console, "
                "rename it to credentials.json, and place it in the project root."
            )

        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(
            port=0,
            open_browser=False,
            authorization_prompt_message="\n-> Go to this URL to authorize Google Calendar:\n{url}\n",
            success_message="Authentication complete. You may return to the terminal.",
            timeout_seconds=300,
            prompt="consent",
        )

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    _calendar_service_instance = build("calendar", "v3", credentials=creds)
    return _calendar_service_instance


def fetch_events_between(start: dt.datetime, end: dt.datetime) -> list[dict[str, Any]]:
    """Fetch all events between start and end RFC3339 timestamps."""
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


# ---------------------------------------------------------------------------
# LangChain Tools
# ---------------------------------------------------------------------------
@tool
def get_calendar_events(date: str) -> str:
    """
    Fetch all events on a given date from Google Calendar.

    Args:
        date: Target date in YYYY-MM-DD format.

    Returns:
        A human-readable list showing each event title, start time, and end time.
    """
    try:
        start, end = get_day_bounds(date)
    except ValueError:
        return "Error: date must be in YYYY-MM-DD format."

    try:
        events = fetch_events_between(start, end)
    except Exception as exc:
        return f"Error accessing Google Calendar: {exc}"

    if not events:
        return f"No events found on {date}."

    lines = [f"Events on {date}:"]
    for event in events:
        if event.get("status") == "cancelled":
            continue
        title = event.get("summary", "Untitled event")
        start_val = event.get("start", {})
        end_val = event.get("end", {})
        start_dt = parse_iso_datetime(start_val.get("dateTime"))
        end_dt = parse_iso_datetime(end_val.get("dateTime"))
        if not start_dt and start_val.get("date"):
            lines.append(f"- {title}: all day")
        else:
            lines.append(f"- {title}: {format_time_str(start_dt)} to {format_time_str(end_dt)}")

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
    Create a new meeting in Google Calendar with conflict and past-date validation.

    Args:
        title: Meeting title.
        date: Meeting date in YYYY-MM-DD format.
        start_time: Start time in HH:MM (24-hour) format.
        duration_minutes: Length of the meeting in minutes.
        attendee_email: Optional email address of an attendee to invite.

    Returns:
        A confirmation link on success, or a descriptive conflict/validation error message.
    """
    if not title or not title.strip():
        title = "Meeting"

    try:
        start_dt = parse_local_datetime(date, start_time)
    except ValueError:
        return "Error: date must be YYYY-MM-DD and start_time must be HH:MM in 24-hour format."

    if duration_minutes <= 0:
        return "Error: duration_minutes must be greater than 0."

    end_dt = start_dt + dt.timedelta(minutes=duration_minutes)
    now = dt.datetime.now(LOCAL_TZ)

    # Guard 1: Past date check
    if is_past_datetime(start_dt, now):
        return (
            f"Error: Cannot schedule an event in the past. Requested start time was "
            f"{start_dt.strftime('%Y-%m-%d %H:%M %Z')}, but current time is "
            f"{now.strftime('%Y-%m-%d %H:%M %Z')}."
        )

    # Guard 2: Overlap check
    try:
        day_start, day_end = get_day_bounds(date)
        day_events = fetch_events_between(day_start, day_end)
    except Exception as exc:
        return f"Error fetching calendar events for conflict check: {exc}"

    parsed_events = extract_timed_events(day_events)
    conflicts: list[dict[str, Any]] = []
    for item in parsed_events:
        # Check overlap
        if has_overlap(start_dt, end_dt, item["start"], item["end"]):
            # Skip transparent (free) events (both timed and all-day)
            if item["event"].get("transparency") == "transparent":
                continue
            conflicts.append(item)

    if conflicts:
        conflict_descriptions = [
            f"{c['event'].get('summary', 'Untitled event')} ({format_time_str(c['start'])}-{format_time_str(c['end'])})"
            for c in conflicts
        ]
        return (
            f"Conflict detected: The requested slot {date} {start_time} ({duration_minutes} min) "
            f"overlaps with: {'; '.join(conflict_descriptions)}. "
            "Please call analyse_booking_patterns and find_free_slots to suggest 2-3 personalized alternatives."
        )

    # Insert event
    event_payload: dict[str, Any] = {
        "summary": title.strip(),
        "start": {"dateTime": start_dt.isoformat(), "timeZone": TIME_ZONE_NAME},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": TIME_ZONE_NAME},
    }
    if attendee_email and attendee_email.strip():
        clean_emails = [e.strip() for e in attendee_email.split(",") if "@" in e.strip()]
        if clean_emails:
            event_payload["attendees"] = [{"email": e} for e in clean_emails]

    try:
        service = get_calendar_service()
        created = service.events().insert(calendarId=DEFAULT_CALENDAR_ID, body=event_payload).execute()
        return f"Event created successfully! Link: {created.get('htmlLink')}"
    except Exception as exc:
        return f"Error creating event in Google Calendar: {exc}"


@tool
def find_free_slots(date: str, duration_minutes: int) -> str:
    """
    Find available slots of required duration within working hours (09:00 - 18:00) on a given date.

    Args:
        date: Date in YYYY-MM-DD format.
        duration_minutes: Meeting duration in minutes.

    Returns:
        List of all free time windows that can accommodate the meeting.
    """
    if duration_minutes <= 0:
        return "Error: duration_minutes must be greater than 0."

    try:
        start, end = get_day_bounds(date)
        events = fetch_events_between(start, end)
    except Exception as exc:
        return f"Error fetching calendar data: {exc}"

    slots = calculate_free_slots(events, date, duration_minutes)
    if not slots:
        return (
            f"No free slots of at least {duration_minutes} minutes found on {date} "
            f"between {WORKDAY_START_HOUR:02d}:00 and {WORKDAY_END_HOUR:02d}:00."
        )

    lines = [f"Free slots on {date} for a {duration_minutes}-minute meeting:"]
    for s_start, s_end in slots:
        lines.append(f"- {s_start.strftime('%H:%M')} to {s_end.strftime('%H:%M')}")
    return "\n".join(lines)


@tool
def analyse_booking_patterns() -> str:
    """
    Analyze the user's Google Calendar history from the past 30 days to identify scheduling habits.

    Returns:
        A JSON summary with busiest days, lightest days, upcoming lightest dates,
        preferred start hours, and average meeting duration.
    """
    now = dt.datetime.now(LOCAL_TZ)
    start = now - dt.timedelta(days=30)

    try:
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
        events = response.get("items", [])
    except Exception as exc:
        return f"Error analyzing booking patterns: {exc}"

    metrics = compute_booking_metrics(events, start.date(), now.date())
    return json.dumps(metrics, indent=2)


@tool
def query_calendar_insights(question: str) -> str:
    """
    Answer analytical questions about the user's schedule using deterministic calendar calculations.

    Supported queries:
    - Free days ("Which days am I free this week?")
    - Busiest day ("What was my busiest day this month?")
    - Meeting hours ("How many hours of meetings do I have this week?")

    Args:
        question: Natural-language question about calendar statistics.

    Returns:
        A data-backed response computed directly from calendar events.
    """
    now = dt.datetime.now(LOCAL_TZ)
    q_lower = question.lower()

    if "month" in q_lower:
        period_start = dt.datetime(now.year, now.month, 1, tzinfo=LOCAL_TZ)
        if now.month == 12:
            period_end = dt.datetime(now.year + 1, 1, 1, tzinfo=LOCAL_TZ)
        else:
            period_end = dt.datetime(now.year, now.month + 1, 1, tzinfo=LOCAL_TZ)
        label = f"this month ({now.strftime('%B %Y')})"
    elif "last 30" in q_lower or "past 30" in q_lower:
        period_start = now - dt.timedelta(days=30)
        period_end = now
        label = "the last 30 days"
    else:  # default to this week (Monday to Sunday)
        monday = (now - dt.timedelta(days=now.weekday())).date()
        period_start = dt.datetime.combine(monday, dt.time.min, LOCAL_TZ)
        period_end = period_start + dt.timedelta(days=7)
        label = f"this week ({period_start.strftime('%b %d')} - {(period_end - dt.timedelta(days=1)).strftime('%b %d')})"

    try:
        events = fetch_events_between(period_start, period_end)
    except Exception as exc:
        return f"Error querying calendar insights: {exc}"

    return compute_calendar_insights(question, events, period_start, period_end, label)
