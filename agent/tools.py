import ast
import json
import logging
import math
import operator
import os
import re
from typing import Any

import requests
from langchain_core.tools import tool
from langchain_tavily import TavilySearch
from langchain_tavily._utilities import TavilySearchAPIWrapper

from agent.db import save_memory, search_documents, search_memory

logger = logging.getLogger(__name__)

MAX_INT_BITS = 4096


def _redact(message: str) -> str:
    """Remove API keys from text so they never reach logs or the LLM."""
    for name in ("ALPHA_VANTAGE_API_KEY", "OPENWEATHER_API_KEY", "TAVILY_API_KEY"):
        value = os.getenv(name)
        if value:
            message = message.replace(value, "***")
    return re.sub(r"(apikey|appid|api_key)=[^&\s'\"]+", r"\1=***", message, flags=re.I)


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

    def is_number(value) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def evaluate(node, depth: int = 0):
        if depth > 30:
            raise ValueError("expression is too complex")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in binary_operators:
            left = evaluate(node.left, depth + 1)
            right = evaluate(node.right, depth + 1)
            # Only plain numbers: blocks things like [0] * 999999999 (memory DoS)
            if not (is_number(left) and is_number(right)):
                raise ValueError("unsupported operation")
            if isinstance(node.op, ast.Pow):
                if abs(right) > 100:
                    raise ValueError("exponent is too large")
                if (
                    isinstance(left, int)
                    and isinstance(right, int)
                    and right > 0
                    and left.bit_length() * right > MAX_INT_BITS
                ):
                    raise ValueError("result is too large")
            result = binary_operators[type(node.op)](left, right)
            if isinstance(result, complex):
                raise ValueError("result is not a real number")
            if isinstance(result, int) and result.bit_length() > MAX_INT_BITS:
                raise ValueError("result is too large")
            return result
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
        tree = ast.parse(expression.strip(), mode="eval")
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
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        return {"error": "ALPHA_VANTAGE_API_KEY is not configured."}

    symbol = (symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9.\-]{1,12}", symbol):
        return {"error": f"Invalid stock symbol: '{symbol}'."}

    try:
        response = requests.get(
            "https://www.alphavantage.co/query",
            params={"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": api_key},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except requests.Timeout:
        return {"error": "Stock service timed out."}
    except requests.RequestException as e:
        return {"error": f"Stock service error: {_redact(str(e))}"}
    except ValueError:
        return {"error": "Stock service returned an invalid response."}

    quote = data.get("Global Quote") or {}
    if not quote:
        # Alpha Vantage reports rate limits / bad symbols in these fields
        message = (
            data.get("Note") or data.get("Information") or data.get("Error Message")
        )
        return {"error": message or f"No data found for '{symbol}'."}

    return {
        "symbol": quote.get("01. symbol", symbol),
        "price": quote.get("05. price"),
        "change": quote.get("09. change"),
        "change_percent": quote.get("10. change percent"),
        "open": quote.get("02. open"),
        "high": quote.get("03. high"),
        "low": quote.get("04. low"),
        "previous_close": quote.get("08. previous close"),
        "volume": quote.get("06. volume"),
        "latest_trading_day": quote.get("07. latest trading day"),
    }


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

    location = (location or "").strip()
    if not location:
        return "Please provide a city or location name."

    session = requests.Session()

    try:
        # Step 1: Geocoding
        geo_response = session.get(
            "https://api.openweathermap.org/geo/1.0/direct",
            params={"q": location, "limit": 1, "appid": api_key},
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

        # Step 2: Current Weather
        weather_response = session.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"lat": lat, "lon": lon, "appid": api_key, "units": "metric"},
            timeout=10,
        )
        weather_response.raise_for_status()

        weather = weather_response.json()

        main = weather.get("main", {})
        wind = weather.get("wind", {})
        weather_list = weather.get("weather") or [{}]
        weather_info = weather_list[0]

        visibility = weather.get("visibility")
        visibility = f"{visibility / 1000:.1f} km" if visibility is not None else "N/A"

        lines = [
            f"🌍 Location: {display_location}",
            f"🌤 Condition : {weather_info.get('description', 'N/A').title()}",
            f"🌡 Temperature : {main.get('temp', 'N/A')}°C",
            f"🥵 Feels Like : {main.get('feels_like', 'N/A')}°C",
            f"💧 Humidity : {main.get('humidity', 'N/A')}%",
            f"🌬 Wind Speed : {wind.get('speed', 'N/A')} m/s",
            f"📈 Pressure : {main.get('pressure', 'N/A')} hPa",
            f"👀 Visibility : {visibility}",
        ]
        return "\n".join(lines)

    except requests.Timeout:
        return "Weather service timed out."

    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "unknown"

        if code == 401:
            return "Invalid OpenWeather API key."
        if code == 404:
            return "Weather data not found."
        if code == 429:
            return "OpenWeather API rate limit exceeded."
        return f"HTTP Error {code}"

    except requests.RequestException as e:
        return f"Network Error: {_redact(str(e))}"

    except Exception as e:
        logger.exception("Unexpected weather tool error")
        return f"Unexpected Error: {_redact(str(e))}"


def create_tools(thread_id: str, tavily_api_key: str | None = None):
    @tool
    def remember_this(memory: str) -> str:
        """Save an important user preference or fact into long-term memory."""
        try:
            return save_memory(thread_id=thread_id, memory=memory)
        except Exception:
            logger.exception("save_memory failed")
            return "Memory is temporarily unavailable. Please try again shortly."

    @tool
    def recall_memory(query: str) -> str:
        """Recall saved long-term memories for this conversation."""
        try:
            return search_memory(thread_id=thread_id, query=query)
        except Exception:
            logger.exception("search_memory failed")
            return "Memory is temporarily unavailable. Please try again shortly."

    @tool
    def search_uploaded_documents(query: str) -> str:
        """Search documents uploaded to this conversation for relevant passages."""
        try:
            matches = search_documents(thread_id=thread_id, query=query)
        except Exception:
            logger.exception("search_documents failed")
            return (
                "Document search is temporarily unavailable. Please try again shortly."
            )
        if not matches:
            return "No matching uploaded document passages were found."
        return "\n\n".join(
            f"Source: {item['filename']}\n{item['content']}" for item in matches
        )

    shared_tavily_api_key = os.getenv("TAVILY_API_KEY")
    tavily_keys = [
        key for key in dict.fromkeys((shared_tavily_api_key, tavily_api_key)) if key
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
            last_error: Exception | None = None
            # Try every configured key (shared first, then the user's own)
            for search_tool in tavily_search_tools:
                try:
                    result = search_tool.invoke({"query": query})
                    if isinstance(result, str):
                        return result
                    return json.dumps(result, ensure_ascii=False, default=str)
                except Exception as error:  # noqa: BLE001
                    last_error = error
                    logger.warning("Tavily search failed: %s", _redact(str(error)))
            return f"Web search failed: {_redact(str(last_error))}"

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
