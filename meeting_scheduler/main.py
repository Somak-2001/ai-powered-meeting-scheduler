"""Command-line interface entry point for AI-Powered Meeting Scheduler."""

from __future__ import annotations

import sys
from pathlib import Path

from .agent import create_scheduler_agent
from .tools import (
    CREDENTIALS_PATH,
    DEFAULT_CALENDAR_ID,
    TIME_ZONE_NAME,
    get_calendar_service,
)


def verify_environment() -> bool:
    """Verify that credentials and environment configuration are available."""
    if not CREDENTIALS_PATH.exists() and not (Path.cwd() / "credentials.json").exists():
        print("\n" + "=" * 60)
        print("⚠️  [Setup Required] Google OAuth Credentials Missing")
        print("=" * 60)
        print(f"Expected file: {CREDENTIALS_PATH}")
        print("To fix this:")
        print("1. Go to Google Cloud Console -> APIs & Services -> Credentials")
        print("2. Create an OAuth 2.0 Client ID with application type 'Desktop App'")
        print("3. Download JSON, rename it to 'credentials.json', and place it in the project root.")
        print("=" * 60 + "\n")
        return False
    return True


def display_banner() -> None:
    """Print welcome header and connection status."""
    print("=" * 65)
    print(" 📅  AI-Powered Meeting Scheduler (LangChain + Gemini)")
    print("=" * 65)
    print(f" Timezone:        {TIME_ZONE_NAME}")
    print(f" Calendar Target: {DEFAULT_CALENDAR_ID}")

    try:
        service = get_calendar_service()
        calendar_info = service.calendars().get(calendarId=DEFAULT_CALENDAR_ID).execute()
        cal_id = calendar_info.get("id", DEFAULT_CALENDAR_ID)
        print(f" Status:          Connected to Google Calendar ({cal_id})")
    except Exception as exc:
        print(f" Status:          ⚠️ Calendar connection pending or error: {exc}")

    print("=" * 65)
    print("Type your scheduling request in plain English, or 'exit' to quit.\n")


def main() -> None:
    """Run interactive REPL loop."""
    display_banner()

    try:
        agent = create_scheduler_agent()
    except Exception as exc:
        print(f"\n❌ Failed to initialize AI Agent: {exc}")
        print("Ensure GOOGLE_API_KEY is defined in your .env file.")
        sys.exit(1)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting AI Scheduler. Goodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit", "q"}:
            print("Goodbye!")
            break

        try:
            response = agent(user_input)
            print(f"\nAssistant:\n{response}")
        except Exception as exc:
            print(f"\nAssistant Error: {exc}")


if __name__ == "__main__":
    main()

