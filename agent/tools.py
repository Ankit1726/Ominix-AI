import ast
import math
import os
import operator
from typing import Any

import requests
from langchain_core.tools import ToolException, tool
from langchain_tavily import TavilySearch
from langchain_tavily._utilities import TavilySearchAPIWrapper

from agent.db import save_memory, search_documents, search_memory


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
    if not expression or len(expression) > 500:
        return "Calculation error: expression must be 1–500 characters."

    binary_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    unary_operators = {ast.UAdd: operator.pos, ast.USub: operator.neg}
    functions = {
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "sqrt": math.sqrt,
    }

    def evaluate(node, depth: int = 0):
        if depth > 30:
            raise ValueError("expression is too complex")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in binary_operators:
            left = evaluate(node.left, depth + 1)
            right = evaluate(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("exponent is too large")
            return binary_operators[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in unary_operators:
            return unary_operators[type(node.op)](evaluate(node.operand, depth + 1))
        if isinstance(node, (ast.List, ast.Tuple)):
            return [evaluate(item, depth + 1) for item in node.elts]
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in functions
            and not node.keywords
        ):
            return functions[node.func.id](
                *(evaluate(argument, depth + 1) for argument in node.args)
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "math"
            and node.func.attr == "sqrt"
            and not node.keywords
        ):
            return math.sqrt(*(evaluate(argument, depth + 1) for argument in node.args))
        raise ValueError("unsupported operation")

    try:
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError("expression is too complex")
        result = evaluate(tree.body)
        if isinstance(result, (int, float)) and (
            not math.isfinite(result) or abs(result) > 1e100
        ):
            raise ValueError("result is too large")
        return str(result)
    except (ArithmeticError, SyntaxError, TypeError, ValueError) as error:
        return f"Calculation error: {error}"


# Stock Price Tool
@tool
def get_stock_price(symbol: str) -> dict:
    """
    Fetch the latest stock price for a given stock symbol.
    Example: AAPL, TSLA, MSFT
    """
    try:
        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={os.getenv('ALPHA_VANTAGE_API_KEY')}"
        response = requests.get(url, timeout=10)
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


def create_tools(thread_id: str, tavily_api_key: str | None = None):
    @tool
    def remember_this(memory: str) -> str:
        """Save an important user preference or fact into long-term memory."""
        return save_memory(thread_id=thread_id, memory=memory)

    @tool
    def recall_memory(query: str) -> str:
        """Recall saved long-term memories for this conversation."""
        return search_memory(thread_id=thread_id, query=query)

    @tool
    def search_uploaded_documents(query: str) -> str:
        """Search documents uploaded to this conversation for relevant passages."""
        matches = search_documents(thread_id=thread_id, query=query)
        if not matches:
            return "No matching uploaded document passages were found."
        return "\n\n".join(
            f"Source: {item['filename']}\n{item['content']}" for item in matches
        )

    shared_tavily_api_key = os.getenv("TAVILY_API_KEY")
    tavily_keys = [
        key
        for key in dict.fromkeys((shared_tavily_api_key, tavily_api_key))
        if key
    ]
    if tavily_keys:
        tavily_search_tools = [
            TavilySearch(
                max_results=5,
                topic="general",
                search_depth="advanced",
                handle_tool_error=False,
                api_wrapper=TavilySearchAPIWrapper(tavily_api_key=key),
            )
            for key in tavily_keys
        ]

        @tool
        def tavily_search(query: str) -> str:
            """Search the current web for recent information using Tavily."""
            try:
                return tavily_search_tools[0].invoke({"query": query})
            except ToolException:
                if len(tavily_search_tools) == 1:
                    raise
                return tavily_search_tools[1].invoke({"query": query})

    else:
        @tool
        def tavily_search(query: str) -> str:
            """Search the current web for recent information using Tavily."""
            return (
                "Web search is unavailable because no Tavily API key is configured. "
                "Add a key in Settings to enable current web research."
            )

    return [
        calculator,
        remember_this,
        recall_memory,
        search_uploaded_documents,
        tavily_search,
        get_stock_price,
        get_current_weather,
    ]
