"""Backward-compatibility re-export for agent module."""

import sys
from pathlib import Path

workspace_dir = str(Path(__file__).resolve().parent)
if workspace_dir not in sys.path:
    sys.path.insert(0, workspace_dir)

from meeting_scheduler.agent import (
    DEFAULT_MODEL,
    SYSTEM_PROMPT,
    TOOLS,
    create_scheduler_agent,
    get_current_context,
)

__all__ = [
    "DEFAULT_MODEL",
    "SYSTEM_PROMPT",
    "TOOLS",
    "create_scheduler_agent",
    "get_current_context",
]
