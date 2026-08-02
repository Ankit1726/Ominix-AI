from langchain_core.tools import tool
from typing import Any
from langchain_tavily import TavilySearch
import os, requests, math

from agent.db import save_memory, search_memory
from agent.rag import retrieve_text

CURRENT_THREAD_ID = "default"


def set_current_thread_id(thread_id: str):
    global CURRENT_THREAD_ID
    CURRENT_THREAD_ID = thread_id


web_search = TavilySearch(max_results=5, topic="general", search_depth="advanced")


@tool
def search_uploaded_documents(query: str) -> str:
    """
    Search uploaded documents for relevant information.
    Use this when the user asks about uploaded PDFs, DOCX, TXT, notes, files, or documents.
    """

    return retrieve_text(query=query, thread_id=CURRENT_THREAD_ID)


@tool
def remember_this(memory: str) -> str:
    """
    Save an important user preference or fact into long-term memory.
    Use this when the user asks you to remember something.
    """

    return save_memory(thread_id=CURRENT_THREAD_ID, memory=memory)


@tool
def recall_memory(query: str) -> str:
    """
    Recall saved long-term memories about the user or this conversation.
    """

    return search_memory(thread_id=CURRENT_THREAD_ID, query=query)


## Calculator Tool
@tool
def calculator(expression: str) -> str:
    """
    - Useful for performing simple mathematical calculations.
    Input should be a valid mathematical expression.
    Examples:
    - 2 + 2
    - math.sqrt(16)
    - 10 * 5
    """
    try:
        allowed = {
            "math": math,
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
        }

        result = eval(expression, {"__builtins__": {}}, allowed)
        return str(result)

    except Exception as e:
        return f"Calculation error: {e}"


# Stock Price Tool
@tool
def get_stock_price(symbol: str) -> dict:
    """
    Fetch the latest stock price for a given stock symbol.
    Example: AAPL, TSLA, MSFT
    """
    try:
        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={os.getenv('ALPHA_VANTAGE_API_KEY')}"
        response = requests.get(url)
        return response.json()
    except Exception as e:
        return {"error": str(e)}


# Weather Tool
@tool
def get_current_weather(location: str) -> str:
    """
    Get the current weather for any city or location.

    Args:
        location: City or location name (e.g. "Delhi", "London, UK")

    Returns:
        A formatted weather report.
    """

    api_key = os.getenv("OPENWEATHER_API_KEY")

    if not api_key:
        return "OPENWEATHER_API_KEY is not configured."

    session = requests.Session()

    try:
        # -----------------------------
        # Step 1: Geocoding
        # -----------------------------
        geo_response = session.get(
            "https://api.openweathermap.org/geo/1.0/direct",
            params={
                "q": location,
                "limit": 1,
                "appid": api_key,
            },
            timeout=10,
        )

        geo_response.raise_for_status()

        locations: list[dict[str, Any]] = geo_response.json()

        if not locations:
            return f"No location found for '{location}'."

        place = locations[0]

        lat = place["lat"]
        lon = place["lon"]

        city = place.get("name", location)
        state = place.get("state")
        country = place.get("country")

        display_location = ", ".join(part for part in [city, state, country] if part)

        # -----------------------------
        # Step 2: Current Weather
        # -----------------------------
        weather_response = session.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "lat": lat,
                "lon": lon,
                "appid": api_key,
                "units": "metric",
            },
            timeout=10,
        )

        weather_response.raise_for_status()

        weather = weather_response.json()

        main = weather.get("main", {})
        wind = weather.get("wind", {})
        weather_info = weather.get("weather", [{}])[0]

        visibility = weather.get("visibility")

        visibility = f"{visibility / 1000:.1f} km" if visibility is not None else "N/A"

        return f"""
                🌍 Location: {display_location}
                🌤 Condition : {weather_info.get("description", "N/A").title()}
                🌡 Temperature : {main.get("temp", "N/A")}°C
                🥵 Feels Like : {main.get("feels_like", "N/A")}°C
                💧 Humidity : {main.get("humidity", "N/A")}%
                🌬 Wind Speed : {wind.get("speed", "N/A")} m/s
                📈 Pressure : {main.get("pressure", "N/A")} hPa
                👀 Visibility : {visibility}
            """.strip()

    except requests.Timeout:
        return "Weather service timed out."

    except requests.HTTPError as e:
        code = e.response.status_code

        if code == 401:
            return "Invalid OpenWeather API key."

        if code == 404:
            return "Weather data not found."

        if code == 429:
            return "OpenWeather API rate limit exceeded."

        return f"HTTP Error {code}"

    except requests.RequestException as e:
        return f"Network Error: {e}"

    except Exception as e:
        return f"Unexpected Error: {e}"


tools = [
    calculator,
    search_uploaded_documents,
    remember_this,
    recall_memory,
    web_search,
    get_stock_price,
    get_current_weather,
]