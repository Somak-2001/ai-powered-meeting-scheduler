"""Hermetic unit tests for LangChain multi-step agent tool-calling loop and ToolMessage cycles."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from meeting_scheduler.agent import create_scheduler_agent


class MockAIMessage:
    """Mock LLM response message simulating ChatGoogleGenerativeAI output."""

    def __init__(self, content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []


class TestAgentToolLoop(unittest.TestCase):
    """Test suite simulating iterative tool calling, ToolMessage propagation, and terminal responses."""

    @patch("meeting_scheduler.tools.get_calendar_service")
    def test_direct_single_shot_scheduling_loop(self, mock_calendar_service: MagicMock) -> None:
        """Verify the agent handles a single-turn meeting creation request."""
        mock_service = MagicMock()
        mock_events = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.return_value = {"htmlLink": "https://calendar.google.com/event?eid=single_turn"}
        mock_events.insert.return_value = mock_insert
        # Mock empty events on that date (no conflict)
        mock_list = MagicMock()
        mock_list.execute.return_value = {"items": []}
        mock_events.list.return_value = mock_list
        mock_service.events.return_value = mock_events
        mock_calendar_service.return_value = mock_service

        # Step 1: Model emits create_event tool call
        # Step 2: Model receives ToolMessage and outputs final confirmation text
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            MockAIMessage(
                content="",
                tool_calls=[{
                    "name": "create_event",
                    "args": {
                        "title": "One-on-One",
                        "date": "2026-10-15",
                        "start_time": "14:00",
                        "duration_minutes": 30,
                    },
                    "id": "call_create_99",
                }],
            ),
            MockAIMessage(
                content="I have scheduled your One-on-One meeting for 2026-10-15 at 14:00.",
                tool_calls=[],
            ),
        ]

        agent = create_scheduler_agent(llm_client=mock_llm)
        response = agent("Schedule a one-on-one on Oct 15 2026 at 2pm")

        self.assertIn("scheduled your One-on-One", response)
        self.assertEqual(mock_llm.invoke.call_count, 2)

        # Inspect the message history passed to step 2
        second_call_messages = mock_llm.invoke.call_args_list[1][0][0]
        # History should contain SystemMessage, HumanMessage, AIMessage, ToolMessage
        tool_messages = [m for m in second_call_messages if getattr(m, "tool_call_id", None) == "call_create_99"]
        self.assertEqual(len(tool_messages), 1)
        self.assertIn("Event created successfully", tool_messages[0].content)

    @patch("meeting_scheduler.tools.get_calendar_service")
    def test_multi_step_conflict_resolution_protocol(self, mock_calendar_service: MagicMock) -> None:
        """
        Verify Phase 10 required simulation:
        1. LLM requests create_event.
        2. create_event detects conflict.
        3. Agent sends ToolMessage with matching tool_call_id.
        4. LLM requests analyse_booking_patterns.
        5. Tool returns booking history.
        6. LLM requests find_free_slots.
        7. Tool returns candidate slots.
        8. LLM synthesizes and returns final response.
        """
        # Calendar mock returning an existing overlapping meeting for create_event
        mock_service = MagicMock()
        mock_events = MagicMock()

        # Overlap meeting from 10:00 to 11:00 on 2026-10-15
        mock_list = MagicMock()
        mock_list.execute.return_value = {
            "items": [
                {
                    "summary": "Existing Executive Sync",
                    "start": {"dateTime": "2026-10-15T10:00:00+05:30"},
                    "end": {"dateTime": "2026-10-15T11:00:00+05:30"},
                }
            ]
        }
        mock_events.list.return_value = mock_list
        mock_service.events.return_value = mock_events
        mock_calendar_service.return_value = mock_service

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            # Turn 1: Model requests create_event
            MockAIMessage(
                content="",
                tool_calls=[{
                    "name": "create_event",
                    "args": {
                        "title": "Strategy Sync",
                        "date": "2026-10-15",
                        "start_time": "10:30",
                        "duration_minutes": 60,
                    },
                    "id": "call_create_001",
                }],
            ),
            # Turn 2: After conflict in ToolMessage, model requests analyse_booking_patterns
            MockAIMessage(
                content="",
                tool_calls=[{
                    "name": "analyse_booking_patterns",
                    "args": {},
                    "id": "call_patterns_002",
                }],
            ),
            # Turn 3: After pattern stats in ToolMessage, model requests find_free_slots
            MockAIMessage(
                content="",
                tool_calls=[{
                    "name": "find_free_slots",
                    "args": {
                        "date": "2026-10-15",
                        "duration_minutes": 60,
                    },
                    "id": "call_slots_003",
                }],
            ),
            # Turn 4: Model synthesizes 2-3 ranked alternatives
            MockAIMessage(
                content=(
                    "The requested 10:30 slot conflicts with 'Existing Executive Sync'.\n"
                    "Here are 2 alternative options based on your schedule:\n"
                    "1. 2026-10-15 at 11:00 AM (Available immediately following your morning meeting)\n"
                    "2. 2026-10-15 at 02:00 PM (Matches your typical afternoon focus block)"
                ),
                tool_calls=[],
            ),
        ]

        agent = create_scheduler_agent(llm_client=mock_llm)
        result = agent("Schedule Strategy Sync on 2026-10-15 at 10:30am for 1 hour")

        # Verify LLM was invoked exactly 4 times in the multi-step loop
        self.assertEqual(mock_llm.invoke.call_count, 4)
        self.assertIn("Existing Executive Sync", result)
        self.assertIn("alternative options", result)

        # Verify ToolMessage IDs in history for each step
        final_history = mock_llm.invoke.call_args_list[3][0][0]
        tool_messages = [m for m in final_history if hasattr(m, "tool_call_id")]

        tool_ids = [m.tool_call_id for m in tool_messages]
        self.assertEqual(tool_ids, ["call_create_001", "call_patterns_002", "call_slots_003"])

        # Tool 1 result should contain Conflict detected
        self.assertIn("Conflict detected", tool_messages[0].content)
        # Tool 2 result should contain booking metrics
        self.assertIn("total_timed_meetings", tool_messages[1].content)
        # Tool 3 result should contain free slots
        self.assertIn("Free slots on 2026-10-15", tool_messages[2].content)

    def test_loop_iteration_limit(self) -> None:
        """Verify the agent does not loop infinitely if model continually requests tools."""
        # LLM that keeps emitting tool calls on every step
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MockAIMessage(
            content="",
            tool_calls=[{
                "name": "find_free_slots",
                "args": {"date": "2026-10-20", "duration_minutes": 30},
                "id": "call_loop_test",
            }],
        )

        with patch("meeting_scheduler.tools.fetch_events_between", return_value=[]):
            agent = create_scheduler_agent(llm_client=mock_llm)
            result = agent("Infinite loop test request")

        self.assertIn("I completed the maximum reasoning steps", result)
        self.assertEqual(mock_llm.invoke.call_count, 8)

    def test_tool_call_id_none_fallback(self) -> None:
        """When LLM returns a tool call with id=None, agent supplies a valid string tool_call_id."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            MockAIMessage(
                content="",
                tool_calls=[{
                    "name": "find_free_slots",
                    "args": {"date": "2026-10-20"},
                    "id": None,  # Simulating LLM returning None as id
                }],
            ),
            MockAIMessage(
                content="Here are your free slots.",
                tool_calls=[],
            ),
        ]

        with patch("meeting_scheduler.tools.fetch_events_between", return_value=[]):
            agent = create_scheduler_agent(llm_client=mock_llm)
            response = agent("Find free slots on Oct 20 2026")

        self.assertIn("Here are your free slots.", response)
        # Verify ToolMessage received a valid string tool_call_id
        second_call_messages = mock_llm.invoke.call_args_list[1][0][0]
        tool_msg = [m for m in second_call_messages if hasattr(m, "tool_call_id")][0]
        self.assertIsNotNone(tool_msg.tool_call_id)
        self.assertTrue(len(tool_msg.tool_call_id) > 0)
        self.assertIn("call_find_free_slots_0", tool_msg.tool_call_id)


if __name__ == "__main__":
    unittest.main()


