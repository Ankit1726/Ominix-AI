import math
import os
import requests
import ast
import operator
import contextvars

from typing import Any
from langchain_core.tools import tool
from src.db import save_memory, search_memory
from src.rag import retrieve_from_rag

from dotenv import load_dotenv

load_dotenv()

_MATH_FUNCTIONS = {
    "sqrt",
    "sin",
    "cos",
    "tan",
    "log",
    "log10",
    "exp",
    "ceil",
    "floor",
    "pow",
    "fabs",
    "factorial",
    "gcd",
    "isclose",
    "isfinite",
    "isinf",
    "isnan",
    "trunc",
    "degrees",
    "radians",
    "hypot",
    "pi",
    "e",
}

_ALLOWED_NAMES = {
    "math": math,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "pi": math.pi,
    "e": math.e,
}

_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}


def _eval_expr(node):
    """Recursively evaluate an AST node with a strict whitelist."""
    if isinstance(node, ast.Expression):
        return _eval_expr(node.body)

    elif isinstance(node, ast.Constant):  # Python 3.8+
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("Only numeric constants are allowed")

    elif isinstance(node, ast.Num):  # Python < 3.8
        return node.n

    elif isinstance(node, ast.BinOp):
        left = _eval_expr(node.left)
        right = _eval_expr(node.right)
        op_type = type(node.op)
        if op_type not in _OPERATORS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        return _OPERATORS[op_type](left, right)

    elif isinstance(node, ast.UnaryOp):
        operand = _eval_expr(node.operand)
        op_type = type(node.op)
        if op_type not in _OPERATORS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        return _OPERATORS[op_type](operand)

    elif isinstance(node, ast.Call):
        func = _eval_expr(node.func)
        args = [_eval_expr(arg) for arg in node.args]
        return func(*args)

    elif isinstance(node, ast.Name):
        if node.id not in _ALLOWED_NAMES:
            raise ValueError(f"Unknown identifier: {node.id}")
        return _ALLOWED_NAMES[node.id]

    elif isinstance(node, ast.Attribute):
        # Block dunder attributes entirely (prevents sandbox escape)
        if node.attr.startswith("__"):
            raise ValueError("Private attributes are not allowed")
        if isinstance(node.value, ast.Name) and node.value.id == "math":
            if node.attr not in _MATH_FUNCTIONS:
                raise ValueError(f"math.{node.attr} is not allowed")
            return getattr(math, node.attr)
        raise ValueError("Only math.XXX attributes are allowed")

    elif isinstance(node, ast.List):
        return [_eval_expr(e) for e in node.elts]

    elif isinstance(node, ast.Tuple):
        return tuple(_eval_expr(e) for e in node.elts)

    else:
        raise ValueError(f"Unsupported expression: {type(node).__name__}")


@tool
def calculator(expression: str) -> str:
    """
    Perform simple mathematical calculations safely.

    Input should be a valid mathematical expression.
    Examples:
    - 2 + 2
    - math.sqrt(16)
    - 10 * 5
    - sum([1, 2, 3])
    """
    try:
        if not expression or not expression.strip():
            return "Error: Expression cannot be empty"
        tree = ast.parse(expression, mode="eval")
        result = _eval_expr(tree)
        return str(result)
    except Exception as e:
        return f"Calculation error: {e}"


# Stock Price Tool
@tool
def get_stock_price(symbol: str) -> str:
    """
    Fetch the latest stock price for a given stock symbol.
    Example: AAPL, TSLA, MSFT
    """
    try:
        symbol = symbol.strip().upper()
        if not symbol:
            return "Error: Stock symbol cannot be empty"
        api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        if not api_key:
            return "Error: ALPHA_VANTAGE_API_KEY environment variable is not set"

        url = (
            f"https://www.alphavantage.co/query"
            f"?function=GLOBAL_QUOTE"
            f"&symbol={symbol}"
            f"&apikey={api_key}"
        )
        response = requests.get(url, timeout=15)

        if response.status_code != 200:
            return f"Error: HTTP {response.status_code} from stock API"

        data = response.json()

        if "Error Message" in data:
            return f"Error: {data['Error Message']}"

        if "Note" in data:
            return f"Error: API rate limit reached. {data['Note']}"

        quote = data.get("Global Quote")
        if not quote:
            return f"Error: No data found for symbol {symbol}"

        price = quote.get("05. price", "N/A")
        change = quote.get("09. change", "N/A")
        change_pct = quote.get("10. change percent", "N/A")
        volume = quote.get("06. volume", "N/A")
        latest_day = quote.get("07. latest trading day", "N/A")

        return (
            f"Stock: {symbol}\n"
            f"Price: ${price}\n"
            f"Change: {change} ({change_pct})\n"
            f"Volume: {volume}\n"
            f"Latest Trading Day: {latest_day}"
        )

    except requests.Timeout:
        return "Error: Stock API request timed out"
    except Exception as e:
        return f"Error fetching stock price: {e}"


# Current Weather Tool
@tool
def get_current_weather(location: str) -> str:
    """
    Get the current real-time weather for a given city or location.

    Args:
        location: City or location name, for example:
                  "Dhaka", "London, UK", or "New York, US".

    Returns:
        A formatted current weather report.
    """
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key:
        return (
            "Weather API key is missing. "
            "Set the OPENWEATHER_API_KEY environment variable."
        )

    location = location.strip()
    if not location:
        return "Error: Location cannot be empty"

    try:
        # Step 1: Geocoding
        geocoding_url = "https://api.openweathermap.org/geo/1.0/direct"
        geo_response = requests.get(
            geocoding_url,
            params={"q": location, "limit": 1, "appid": api_key},
            timeout=10,
        )
        geo_response.raise_for_status()
        locations: list[dict[str, Any]] = geo_response.json()

        if not locations:
            return f"Could not find the location: {location}"

        lat = locations[0]["lat"]
        lon = locations[0]["lon"]
        resolved_name = locations[0].get("name", location)
        country = locations[0].get("country", "")
        state = locations[0].get("state", "")

        # Step 2: Weather
        weather_url = "https://api.openweathermap.org/data/2.5/weather"
        weather_response = requests.get(
            weather_url,
            params={"lat": lat, "lon": lon, "appid": api_key, "units": "metric"},
            timeout=10,
        )
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        temperature = weather_data["main"]["temp"]
        feels_like = weather_data["main"]["feels_like"]
        humidity = weather_data["main"]["humidity"]
        pressure = weather_data["main"]["pressure"]
        description = weather_data["weather"][0]["description"]
        wind_speed = weather_data.get("wind", {}).get("speed", "N/A")
        visibility_meters = weather_data.get("visibility")
        visibility_km = (
            round(visibility_meters / 1000, 1)
            if visibility_meters is not None
            else "N/A"
        )

        location_parts = [resolved_name]
        if state:
            location_parts.append(state)
        if country:
            location_parts.append(country)
        display_location = ", ".join(location_parts)

        return (
            f"Current weather in {display_location}:\n"
            f"- Condition: {description.title()}\n"
            f"- Temperature: {temperature}°C\n"
            f"- Feels like: {feels_like}°C\n"
            f"- Humidity: {humidity}%\n"
            f"- Pressure: {pressure} hPa\n"
            f"- Wind speed: {wind_speed} m/s\n"
            f"- Visibility: {visibility_km} km"
        )

    except requests.Timeout:
        return "The weather service request timed out. Please try again."
    except requests.HTTPError as error:
        status = error.response.status_code if error.response else "unknown"
        if status == 401:
            return "The OpenWeather API key is invalid or inactive."
        return f"Weather API returned an HTTP error: {status}"
    except requests.RequestException as error:
        return f"Could not connect to the weather service: {error}"
    except (KeyError, TypeError, ValueError) as error:
        return f"Unexpected weather API response: {error}"


_current_thread_id = contextvars.ContextVar("current_thread_id", default="default")


def set_current_thread_id(thread_id: str) -> None:
    """Update the active conversation thread (thread-safe)."""
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("thread_id must be a non-empty string")
    _current_thread_id.set(thread_id)


def get_current_thread_id() -> str:
    """Get the current conversation thread ID."""
    return _current_thread_id.get()


# RAG Search
@tool
def search_uploaded_documents(query: str) -> str:
    """
    Search uploaded documents using the RAG knowledge base.

    Use this tool whenever the user asks about:
    - uploaded PDFs, DOCX files, TXT files
    - resumes, notes, research papers, reports
    - previously uploaded documents
    """
    if not query or not query.strip():
        return "Error: Query cannot be empty"
    try:
        return retrieve_from_rag(
            query=query,
            thread_id=get_current_thread_id(),
        )
    except Exception as e:
        return f"Document search error: {e}"


# Long-Term Memory
@tool
def remember_this(memory: str) -> str:
    """
    Save important long-term user information.

    Use this tool when the user says things like:
    - Remember this...
    - Save this...
    - Don't forget...
    - My preference is...
    - From now on...

    Do not save temporary conversation details.
    """
    if not memory or not memory.strip():
        return "Error: Memory cannot be empty"
    try:
        return save_memory(
            thread_id=get_current_thread_id(),
            memory=memory,
        )
    except Exception as e:
        return f"Memory save error: {e}"


@tool
def recall_memory(query: str) -> str:
    """
    Retrieve previously saved long-term memories.

    Use this tool when the user asks:
    - What do you remember about me?
    - Recall my preferences.
    - What did I tell you before?
    - Do you remember...?
    """
    if not query or not query.strip():
        return "Error: Query cannot be empty"
    try:
        return search_memory(
            thread_id=get_current_thread_id(),
            query=query,
        )
    except Exception as e:
        return f"Memory recall error: {e}"
