"""LangChain AI Agent orchestration with multi-step tool-calling and smart conflict resolution."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Callable

from .tools import (
    LOCAL_TZ,
    TIME_ZONE_NAME,
    analyse_booking_patterns,
    create_event,
    find_free_slots,
    get_calendar_events,
    load_dotenv,
    query_calendar_insights,
)

# Load environment
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

TOOLS = [
    create_event,
    get_calendar_events,
    find_free_slots,
    analyse_booking_patterns,
    query_calendar_insights,
]

TOOL_REGISTRY = {t.name: t for t in TOOLS}

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM_PROMPT = f"""
You are an intelligent, proactive executive scheduling assistant connected to Google Calendar.
Your primary responsibility is to schedule meetings accurately, resolve conflicts intelligently, and answer schedule queries.

USER ENVIRONMENT:
- Default Timezone: {TIME_ZONE_NAME}
- Working Hours: 09:00 to 18:00 (Monday to Friday)
- Current Date and Time will be provided in every user turn.

CORE OPERATIONAL RULES:
1. Meeting Scheduling:
   - When a user asks to schedule, book, or set up a meeting, call `create_event`.
   - Parse relative dates (e.g. "tomorrow", "this Friday", "next Monday") against the current date.
   - Use dates in YYYY-MM-DD format and 24-hour time in HH:MM format.
   - If no title is given, use "Meeting".
   - If no duration is specified, assume 30 minutes.
   - Extract attendee emails if mentioned (e.g. "raj@example.com").

2. SMART CONFLICT RESOLUTION WORKFLOW (CRITICAL):
   When `create_event` returns a message indicating a "Conflict detected":
   - NEVER simply say "The slot is taken" or give up.
   - You MUST proactively find and suggest 2 to 3 personalized alternative slots using this multi-step protocol:
     Step 1: Call `analyse_booking_patterns` to retrieve the user's 30-day habits (lightest days, preferred hours, avg duration).
     Step 2: Call `find_free_slots` for the originally requested date to see if another time on the same day works.
     Step 3: Call `find_free_slots` for one or two of the user's upcoming lightest days (from `upcoming_lightest_dates`).
     Step 4: Synthesize 2 to 3 distinct, high-quality alternative slots and present them to the user.
   - For EACH suggested alternative, provide a clear, data-backed justification:
     * Example reason A: "Slot available on your originally requested date."
     * Example reason B: "Scheduled on your historically lightest meeting day (e.g., Thursday)."
     * Example reason C: "Aligns with your preferred meeting window (e.g., 10:00 AM)."
   - Format alternatives clearly with numbers, day, date, time range, and reason.

3. Calendar Intelligence & Questions:
   - For schedule overview or queries about free days, busiest day, or total hours, invoke `query_calendar_insights`.
   - For inspecting a specific date's agenda, invoke `get_calendar_events`.

4. Response Style:
   - Professional, concise, and helpful.
   - Always inform the user clearly of the outcome and confirmation links.
""".strip()


def get_current_context() -> str:
    """Return formatted current timestamp and timezone."""
    now = dt.datetime.now(LOCAL_TZ)
    return now.strftime("%A, %Y-%m-%d %H:%M %Z")


# Optional imports with fallbacks for offline unit testing without external dependencies
try:
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
except ImportError:
    class Message:  # type: ignore
        def __init__(self, content: Any = "", **kwargs: Any) -> None:
            self.content = content
            self.tool_calls = kwargs.get("tool_calls", [])
            for k, v in kwargs.items():
                setattr(self, k, v)

        def __repr__(self) -> str:
            return f"{self.__class__.__name__}(content={self.content!r})"

    class HumanMessage(Message): pass  # type: ignore
    class SystemMessage(Message): pass  # type: ignore
    class ToolMessage(Message):  # type: ignore
        def __init__(self, content: str = "", tool_call_id: str = "", **kwargs: Any) -> None:
            super().__init__(content=content, **kwargs)
            self.tool_call_id = tool_call_id

    class ChatGoogleGenerativeAI:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any) -> None: pass
        def bind_tools(self, tools: Any) -> Any: return self

    class ChatGoogleGenerativeAIError(Exception): pass  # type: ignore


def create_scheduler_agent(
    model_name: str | None = None,
    llm_client: Any = None,
) -> Callable[[str], str]:
    """
    Initialize and return the scheduler agent chat runner.

    Args:
        model_name: Optional Gemini model override.
        llm_client: Optional pre-configured LLM instance (used for hermetic unit tests).

    Returns:
        Callable taking user prompt and returning assistant response string.
    """
    target_model = model_name or DEFAULT_MODEL

    if llm_client is not None:
        if hasattr(llm_client, "invoke"):
            llm_with_tools = llm_client
        elif hasattr(llm_client, "bind_tools"):
            llm_with_tools = llm_client.bind_tools(TOOLS)
        else:
            llm_with_tools = llm_client
    else:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY is missing. Please add your Gemini API key to .env file."
            )

        llm = ChatGoogleGenerativeAI(
            model=target_model,
            temperature=0,
        )
        llm_with_tools = llm.bind_tools(TOOLS)

    def run_agent(user_input: str) -> str:
        current_time_str = get_current_context()
        messages: list = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=f"[Context: Current Date/Time is {current_time_str}]\n\nUser request: {user_input}"
            ),
        ]

        # Multi-step tool-calling loop (up to 8 iterations)
        for step in range(8):
            try:
                response = llm_with_tools.invoke(messages)
            except ChatGoogleGenerativeAIError as exc:
                return f"Gemini API Error: {exc}"
            except Exception as exc:
                return f"Unexpected Agent Error: {exc}"

            messages.append(response)

            # If no tool calls requested, model has returned final synthesized response
            if not response.tool_calls:
                content = response.content
                if isinstance(content, list):
                    return " ".join([item.get("text", "") for item in content if isinstance(item, dict)]).strip()
                return content.strip() if content else "Done."

            # Execute tool calls
            for tool_call in response.tool_calls:
                t_name = tool_call.get("name")
                t_args = tool_call.get("args", {})
                t_id = tool_call.get("id", f"call_{t_name}_{step}")

                tool_obj = TOOL_REGISTRY.get(t_name)
                if tool_obj is None:
                    tool_output = f"Error: Tool '{t_name}' is not recognized."
                else:
                    # Provide sensible default parameters if omitted
                    if t_name == "create_event":
                        t_args.setdefault("title", "Meeting")
                        t_args.setdefault("duration_minutes", 30)

                    print(f"[Agent Execution] Invoking tool: {t_name}({t_args})")
                    try:
                        tool_output = tool_obj.invoke(t_args)
                    except Exception as exc:
                        tool_output = f"Execution error in {t_name}: {exc}"

                messages.append(
                    ToolMessage(
                        content=str(tool_output),
                        tool_call_id=t_id,
                    )
                )

        return (
            "I completed the maximum reasoning steps. Please refine your request or "
            "check your calendar directly."
        )

    return run_agent
