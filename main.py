"""Convenience entry point for AI-Powered Meeting Scheduler."""

import sys
from pathlib import Path

# Add workspace directory to python path if not present
workspace_dir = str(Path(__file__).resolve().parent)
if workspace_dir not in sys.path:
    sys.path.insert(0, workspace_dir)

from meeting_scheduler.main import main

if __name__ == "__main__":
    main()
