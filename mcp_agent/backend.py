import os 
import certifi
from dotenv import load_dotenv

load_dotenv()

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from typing import TypedDict, Annotated
import operator
import uuid

import asyncio
import psycopg
from groq import APIStatusError
from psycopg.rows import dict_row
from mcp_agent.mcp_client import (
    aviation_mcp_call,
    tavily_mcp_search,
    extract_destination,
    weather_mcp_search,
    forecast_mcp_search,
)

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langchain_groq import ChatGroq


def get_database_url():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. Please add your Render PostgreSQL External Database URL to .env"
        )

    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    return database_url


GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is missing. Please add it to your .env file.")


# =========================
# LLM
# =========================

llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=GROQ_API_KEY,
)


def truncate_for_prompt(value: str, max_chars: int = 1600) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 180] + "\n...[truncated to stay within model limits]"


def sanitize_text(value: str) -> str:
    if value is None:
        return ""
    text = str(value)
    return text.encode("ascii", "ignore").decode("ascii")


def invoke_llm_with_fallback(system_prompt: str, user_prompt: str, fallback_text: str):
    prompt = truncate_for_prompt(user_prompt, 1200)
    for _ in range(3):
        try:
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ], max_tokens=300)
            response.content = sanitize_text(response.content)
            return response
        except APIStatusError as exc:
            if exc.status_code not in {400, 413, 429}:
                raise
            if len(prompt) <= 600:
                break
            prompt = truncate_for_prompt(prompt, 800)
    return AIMessage(content=sanitize_text(fallback_text))


# =========================
# State
# =========================

class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    user_query: str
    flight_results: str
    hotel_results: str
    itinerary: str
    llm_calls: int
    weather_results: str



FLIGHT_AGENT_PROMPT = """
You are a travel flight expert.

User Query:
{query}

Airport Information:
{airport_data}

Airline Information:
{airline_data}

Generate:

1. Likely departure airport
2. Likely arrival airport
3. Airlines serving this route
4. Typical flight duration
5. Estimated airfare range
6. Peak season pricing warning
7. Booking advice

Return concise travel guidance.
"""

def flight_agent(state: TravelState):
    print("\nINSIDE FLIGHT AGENT\n")

    query = state["user_query"]

    try:

        airports = asyncio.run(
            aviation_mcp_call(
                "list_airports"
            )
        )

        airlines = asyncio.run(
            aviation_mcp_call(
                "list_airlines"
            )
        )


        print("\nAIRPORTS:", airports)
        print("\nAIRLINES:", airlines)

        prompt = FLIGHT_AGENT_PROMPT.format(
            query=query,
            airport_data=str(airports)[:3000],
            airline_data=str(airlines)[:3000]
        )

        response = llm.invoke([
            SystemMessage(
                content="You are an expert travel flight planner."
            ),
            HumanMessage(content=prompt)
        ])

        flight_data = sanitize_text(response.content)

    except Exception as e:

        flight_data = sanitize_text(f"Flight information unavailable: {str(e)}")

    return {
        "flight_results": flight_data,
        "messages": [
            AIMessage(
                content="Flight recommendations generated"
            )
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }


def hotel_agent(state: TravelState):
    query = f"Best hotels for {state['user_query']}"
    # hotel_results = tavily_search(query)
    hotel_results = asyncio.run(tavily_mcp_search(query))

    return {
        "hotel_results": hotel_results,
        "messages": [
            AIMessage(content="Hotel information fetched.")
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }


def weather_agent(state: TravelState):

    city = extract_destination(state["user_query"])

    weather_data = asyncio.run(
        weather_mcp_search(city)
    )

    forecast_data = asyncio.run(
        forecast_mcp_search(city)
    )

    return {
        "weather_results": f"""
        Current Weather:
        {weather_data}

        Forecast:
        {forecast_data}
        """,
        "messages": [
            AIMessage(
                content="Weather information fetched"
            )
        ]
    }

def itinerary_agent(state: TravelState):
    prompt = f"""
Create a complete travel itinerary.

User Query:
{state['user_query']}

Flight Results:
{truncate_for_prompt(state.get('flight_results', ''), 900)}

Hotel Results:
{truncate_for_prompt(state.get('hotel_results', ''), 900)}

Weather Results:
{truncate_for_prompt(state.get('weather_results', ''), 700)}

Make the itinerary practical, budget-aware, and easy to follow.
"""

    response = invoke_llm_with_fallback(
        system_prompt="You are an expert travel planner.",
        user_prompt=prompt,
        fallback_text="I created a concise travel plan based on the available data, but the external search results were incomplete."
    )

    response.content = sanitize_text(response.content)
    return {
        "itinerary": response.content,
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def final_agent(state: TravelState):
    final_prompt = f"""
Generate the final travel response for the user.

User Request:
{state['user_query']}

Flights:
{truncate_for_prompt(state.get('flight_results', ''), 700)}

Hotels:
{truncate_for_prompt(state.get('hotel_results', ''), 700)}

Weather:
{truncate_for_prompt(state.get('weather_results', ''), 500)}

Itinerary:
{truncate_for_prompt(state.get('itinerary', ''), 700)}

Format the final answer beautifully using these sections:

1. Trip Summary
2. Flight Information
3. Hotel Suggestions
4. Weather Information
5. Day-by-Day Itinerary
6. Estimated Budget
7. Final Recommendations

Important:
- Be clear and practical.
- Mention that live flight API may not provide ticket prices if pricing is unavailable.
- Include weather-based travel advice.
- Keep the response useful for real travel planning.
"""

    response = invoke_llm_with_fallback(
        system_prompt="You are a professional AI travel booking assistant.",
        user_prompt=final_prompt,
        fallback_text="I could not generate a full final travel plan because the upstream travel data or model quota was limited. Please retry in a moment."
    )

    response.content = sanitize_text(response.content)
    return {
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }

graph = StateGraph(TravelState)

graph.add_node("flight_agent", flight_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_node("itinerary_agent", itinerary_agent)
graph.add_node("final_agent", final_agent)

graph.add_edge(START, "flight_agent")
graph.add_edge("flight_agent", "hotel_agent")
graph.add_edge("hotel_agent", "weather_agent")
graph.add_edge("weather_agent", "itinerary_agent")
graph.add_edge("itinerary_agent", "final_agent")
graph.add_edge("final_agent", END)

DATABASE_URL = get_database_url()

_conn = psycopg.connect(
    DATABASE_URL,
    autocommit=True,
    row_factory=dict_row
)

checkpointer = PostgresSaver(_conn)
checkpointer.setup()

travel_graph = graph.compile(checkpointer=checkpointer)


def run_travel_agent(user_input: str, thread_id: str | None = None):
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    result = travel_graph.invoke(
        {
            "messages": [
                HumanMessage(content=user_input)
            ],
            "user_query": user_input,
            "flight_results": "",
            "hotel_results": "",
            "weather_results": "",
            "itinerary": "",
            "llm_calls": 0
        },
        config=config
    )

    final_answer = sanitize_text(result["messages"][-1].content)

    return {
        "thread_id": thread_id,
        "answer": final_answer,
        "flight_results": sanitize_text(result.get("flight_results", "")),
        "hotel_results": sanitize_text(result.get("hotel_results", "")),
        "weather_results": sanitize_text(result.get("weather_results", "")),
        "itinerary": sanitize_text(result.get("itinerary", "")),
        "llm_calls": result.get("llm_calls", 0),
    }