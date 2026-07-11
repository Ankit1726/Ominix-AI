import math
import re

from langchain_core.tools import tool
from langchain_tavily import TavilySearch

from src.db import save_memory, search_memory
from src.rag import retrieve_from_rag

from dotenv import load_dotenv
load_dotenv()

# Thread Context
CURRENT_THREAD_ID = "default"

def set_current_thread_id(thread_id: str):
    """Update the active conversation thread."""
    global CURRENT_THREAD_ID
    CURRENT_THREAD_ID = thread_id


# Web Search Tool
web_search = TavilySearch(
    max_results=5,
    topic="general",
    search_depth="advanced",
)

web_search.description = """
    - Search the web for recent, live, or factual information.
    - Use this tool when the user asks about:
        - latest news
        - current events
        - today's information
        - AI updates
        - software releases
        - prices
        - weather
        - sports
        - anything requiring real-time web knowledge

    - Do NOT use this tool for basic knowledge that the model already knows.
    """



# Calculator
@tool
def calculator(expression: str) -> str:
    """
        - Evaluate a mathematical expression.

        - Use this tool whenever the user asks for calculations,
        arithmetic, percentages, square roots, powers, or formulas.

        - Examples:
            - 25 * 18
            - math.sqrt(144)
            - (45 + 12) / 3
    """
    try:
        # Basic validation
        if not re.fullmatch(r"[0-9\s\+\-\*\/\%\(\)\.\,\w]+", expression):
            return "Invalid mathematical expression."

        allowed = {
            "math": math,
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
        }

        result = eval(
            expression,
            {"__builtins__": {}},
            allowed,
        )

        return str(result)
    except Exception as e:
        return f"Calculation error: {e}"



# RAG Search
@tool
def search_uploaded_documents(query: str) -> str:
    """
        - Search uploaded documents using the RAG knowledge base.

        - Use this tool whenever the user asks questions about:
                - uploaded PDFs
                - DOCX files
                - TXT files
                - resumes
                - notes
                - research papers
                - reports
                - previously uploaded documents
    """
    return retrieve_from_rag(
        query=query,
        thread_id=CURRENT_THREAD_ID,
    )


# Long-Term Memory
@tool
def remember_this(memory: str) -> str:
    """
        - Save important long-term user information.

        - Use this tool when the user says things like:
            - Remember this...
            - Save this...
            - Don't forget...
            - My preference is...
            - From now on...

        - Do not save temporary conversation details.
    """
    return save_memory(
        thread_id=CURRENT_THREAD_ID,
        memory=memory,
    )


@tool
def recall_memory(query: str) -> str:
    """
        - Retrieve previously saved long-term memories.

        - Use this tool when the user asks:
            - What do you remember about me?
            - Recall my preferences.
            - What did I tell you before?
            - Do you remember...?
    """
    return search_memory(
        thread_id=CURRENT_THREAD_ID,
        query=query,
    )


# Tool List
tools = [
    calculator,
    search_uploaded_documents,
    remember_this,
    recall_memory,
    web_search,
]