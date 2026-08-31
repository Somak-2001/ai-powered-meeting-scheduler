from agent import create_scheduler_agent
from tools import get_calendar_service


def print_calendar_status() -> None:
    service = get_calendar_service()
    calendar = service.calendars().get(calendarId="primary").execute()
    print(f"Connected Calendar ID: {calendar.get('id', 'primary')}")


def main() -> None:
    print("AI Scheduler Ready! Type 'exit' to quit.")
    print_calendar_status()
    agent = create_scheduler_agent()

    while True:
        user_input = input("\n> ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue

        result = agent(user_input)
        print("\nAssistant:", result)


if __name__ == "__main__":
    main()
