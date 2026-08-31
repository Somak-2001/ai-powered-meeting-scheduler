import datetime as dt
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv(Path(__file__).resolve().parent / ".env")

from tools import (
    analyse_booking_patterns,
    create_event,
    find_free_slots,
    get_calendar_events,
    query_calendar_insights,
)

TOOLS = [
    create_event,
    get_calendar_events,
    find_free_slots,
    analyse_booking_patterns,
    query_calendar_insights,
]

TOOL_BY_NAME = {tool.name: tool for tool in TOOLS}


def _today_context() -> str:
    now = dt.datetime.now().astimezone()
    return now.strftime("%A, %Y-%m-%d %H:%M %Z")


SYSTEM_PROMPT = """
You are an AI-powered meeting scheduler connected to Google Calendar tools.

STRICT RULES:
- For ANY scheduling request, you MUST call the create_event tool.
- NEVER ask follow-up questions.
- If title is missing, use title = "Meeting".
- If duration is missing, assume 30 minutes.
- Always infer missing fields.
- Do NOT respond directly without calling the tool.

GENERAL RULES:
- The user's timezone is Asia/Kolkata unless specified.
- Today is provided in the user message.
- Use YYYY-MM-DD for dates and HH:MM (24-hour) for time.

WORKFLOW:
- First call create_event.
- If conflict occurs, then:
  → call analyse_booking_patterns
  → call find_free_slots
  → suggest alternatives (do NOT create automatically)

- For general questions:
  → use query_calendar_insights or get_calendar_events

Be concise and clear.
""".strip()


def create_scheduler_agent():
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.1-flash-lite-preview",
        temperature=0,
    )

    llm_with_tools = llm.bind_tools(TOOLS)

    def run_agent(user_input: str) -> str:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=f"Current date/time: {_today_context()}\n\nUser input: {user_input}"
            ),
        ]

        for _ in range(8):
            try:
                response = llm_with_tools.invoke(messages)
            except ChatGoogleGenerativeAIError as exc:
                return f"Gemini model error: {exc}"
            except Exception as exc:
                return f"Agent error: {exc}"

            messages.append(response)

            # ✅ If NO tool call → enforce scheduling logic
            if not response.tool_calls:
                content = response.content
                if isinstance(content, list):
                    return " ".join([item.get("text", "") for item in content]).strip()
                return content.strip() if content else "Done."

            # ✅ Execute tool calls
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                selected_tool = TOOL_BY_NAME.get(tool_name)

                if selected_tool is None:
                    result = f"Error: unknown tool {tool_name}."
                else:
                    args = tool_call.get("args", {})

                    # 🔥 Auto-fill missing title
                    if tool_name == "create_event":
                        args.setdefault("title", "Meeting")
                        args.setdefault("duration_minutes", 30)

                    print(f"\n[Tool] {tool_name}({args})")

                    try:
                        result = selected_tool.invoke(args)
                    except Exception as exc:
                        result = f"Tool error from {tool_name}: {exc}"

                messages.append(
                    ToolMessage(
                        content=str(result),
                        tool_call_id=tool_call["id"],
                    )
                )

        return "I reached the tool-call limit. Try a more specific request."

    return run_agent
