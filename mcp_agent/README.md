# MCP Agent

This folder contains the Model Context Protocol (MCP) integration layer used by the travel planner. It connects the LangGraph workflow to external data sources through standardized MCP tools instead of embedding every API client directly in the main app flow.

## Purpose

The `mcp_agent` package is responsible for:

- fetching hotel results through Tavily MCP,
- retrieving airline and airport metadata through AviationStack MCP,
- exposing weather tools through a local custom MCP server,
- providing a clean interface for the main workflow in `backend.py`.

This keeps the travel agents modular and makes it easier to swap or extend service integrations.

## Files

### `mcp_client.py`

This file configures a `MultiServerMCPClient` and connects to three MCP services:

- `tavily`: remote Tavily MCP server for web search
- `aviationstack`: local stdio-based AviationStack MCP server via `uvx aviationstack-mcp`
- `weather`: local stdio-based custom OpenWeather MCP server

It exposes helper functions such as:

- `initialize_mcp()`
- `tavily_mcp_search(query)`
- `initialize_aviation_tools()`
- `aviation_mcp_call(tool_name, tool_args=None)`
- `weather_mcp_search(city)`
- `forecast_mcp_search(city)`
- `extract_destination(query)`

These helpers are called by the travel agents in `backend.py`.

### `custom_weather_mcp_server.py`

This file defines a small local MCP server with OpenWeather API tools. It exposes two tools:

- `get_current_weather(city: str)`
- `get_forecast(city: str)`

The server is launched as a stdio process from `mcp_client.py` and provides weather data to the rest of the app.

### `backend.py`

The main workflow is wired in the project root `backend.py`, which imports the MCP helpers and uses them in:

- the hotel research agent,
- the weather agent,
- the flight research agent,
- the itinerary synthesis flow.

## Environment variables

Create a `.env` file with the required keys before running the app:

```env
TAVILY_API_KEY=your_tavily_key
AVIATIONSTACK_API_KEY=your_aviationstack_key
OPENWEATHER_API_KEY=your_openweather_key
GROQ_API_KEY=your_groq_key
DATABASE_URL=postgresql://user:password@localhost:5432/travel_db
```

## Runtime notes

The project currently uses a Windows-specific path for the weather server in `mcp_client.py`:

```python
"command": r"D:\projects\TravelMateAI\TravelMate-AI---a-multiagent-travel-planner-\.venv\Scripts\python.exe"
```

and

```python
"args": [
    r"D:\projects\TravelMateAI\TravelMate-AI---a-multiagent-travel-planner-\mcp_agent\custom_weather_mcp_server.py"
]
```

This is convenient for local development on this machine, but it should be made project-relative or configurable if the application is moved to another environment.

## Typical flow

1. The user submits a trip request.
2. The flight agent calls AviationStack MCP tools.
3. The hotel agent calls Tavily MCP search.
4. The weather agent calls the custom MCP weather server.
5. The itinerary agent combines all results into a final travel plan.

## Developer tips

- Keep MCP server failures isolated so one broken provider does not block the entire flow.
- Prefer tool names and structured arguments over ad hoc raw API calls.
- Log MCP tool availability during startup to quickly identify missing or misconfigured services.
- Keep environment-specific paths out of source code when deploying to a shared or cloud environment.
