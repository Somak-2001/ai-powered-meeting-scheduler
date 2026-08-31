# AI-Powered Meeting Scheduler using LangChain

This project implements the LangChain lab assignment for an AI-powered meeting scheduler connected to Google Calendar.

## Submitted Files

- `tools.py`: Google Calendar authentication, event creation, conflict detection, free-slot search, 30-day booking pattern analysis, and calendar insight queries.
- `agent.py`: Gemini + LangChain tool-calling agent with a multi-step loop using `ToolMessage`.
- `main.py`: Terminal chat interface that authenticates with Google Calendar and prints the connected Calendar ID.

## Features Implemented

- Natural-language meeting creation through LangChain tool calls.
- Google Calendar OAuth authentication.
- Past date and invalid duration checks.
- Conflict detection using the overlap rule:

```text
A_start < B_end AND A_end > B_start
```

- Free-slot search between 09:00 and 18:00.
- Booking-pattern analysis from the previous 30 days.
- Alternative meeting suggestions after a conflict.
- Bonus calendar intelligence queries such as free days, busiest day, and meeting hours.

## Setup

Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install langchain langchain-google-genai
pip install google-auth google-auth-oauthlib google-api-python-client
pip install python-dotenv
```

Create a `.env` file in this folder:

```bash
GOOGLE_API_KEY=your_gemini_api_key_here
CALENDAR_ID=primary
CALENDAR_TIME_ZONE=Asia/Kolkata
```

Download the Google OAuth Desktop App credentials from Google Cloud Console, rename the file to `credentials.json`, and place it in this folder. Enable the Google Calendar API and add your Gmail as a test user in the OAuth consent screen if the app is in testing mode.

## Run

```bash
python main.py
```

On first run, the app prints a Google authorization URL. Open it in a browser, approve Calendar access, and the app will create `token.json` automatically. Future runs reuse `token.json`.

## Example Prompts

```text
Schedule a 1-hour meeting called Team Sync tomorrow at 10am
Book a 30-minute standup at 9am this Friday
Set up a 45-min call with raj@example.com on Monday at 3pm
Which days am I free this week?
What was my busiest day this month?
How many hours of meetings do I have this week?
```
