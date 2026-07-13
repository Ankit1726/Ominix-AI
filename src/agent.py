import os
import sqlite3
import threading

from langchain_tavily import TavilySearch
from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

from src.tool import (
    calculator,
    get_current_weather,
    get_stock_price,
    remember_this,
    recall_memory,
    search_uploaded_documents,
)

from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# Setup
Path("data").mkdir(exist_ok=True)
DEFAULT_MODEL = "groq"


# CLOUD LLMs
primary_llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    api_key=os.getenv("GROQ_API_KEY"),
    streaming=True,
)

backup_llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,
    api_key=os.getenv("GOOGLE_API_KEY"),
    streaming=True,
)


#  SMART 2-TIER LLM
class SmartLLM:
    """
    2-tier fallback:
    1. Primary (Groq)
    2. Backup (Gemini)
    """

    def __init__(self, primary, backup):
        self.primary = primary
        self.backup = backup

    def bind_tools(self, tools):
        return SmartLLMBound(
            self.primary.bind_tools(tools),
            self.backup.bind_tools(tools),
        )


class SmartLLMBound:
    def __init__(self, primary, backup):
        self.primary = primary
        self.backup = backup

    def _is_rate_limit(self, error: Exception) -> bool:
        """Detect rate-limit / quota errors from any provider."""
        err = str(error).lower()
        retry_errors = [
            "429",
            "rate limit",
            "quota",
            "resource exhausted",
            "too many requests",
            "tokens per day",
            "request too large",
            "daily limit",
            "limit",
            "exceeded",
            "capacity",
        ]
        return any(x in err for x in retry_errors)

    def invoke(self, messages, **kwargs):
        # Tier 1: Primary (Groq)
        try:
            print("🟢 Using Groq (Primary)")
            return self.primary.invoke(messages, **kwargs)
        except Exception as e:
            if not self._is_rate_limit(e):
                raise  # Not a rate limit, bubble up immediately

        # Tier 2: Backup (Gemini)
        try:
            print("🟡 Groq limit reached. Switching to Gemini (Backup)...")
            return self.backup.invoke(messages, **kwargs)
        except Exception as e2:
            raise RuntimeError(
                "All LLM tiers failed:"
                "  1. Groq: Rate limited"
                f"  2. Gemini: {e2}"
            )


# TOOLS
search_tool = TavilySearch(
    max_results=5,
    topic="general",
    search_depth="advanced",
    tavily_api_key=os.getenv("TAVILY_API_KEY"),
)

tools = [
    search_tool,
    calculator,
    get_current_weather,
    get_stock_price,
    remember_this,
    recall_memory,
    search_uploaded_documents,
]


SYSTEM_PROMPT = """You are AnkitGPT, a helpful Agentic AI assistant similar to ChatGPT.

You can:
- Answer general questions.
- Use tools whenever they improve the answer.
- Search uploaded documents using the RAG tool.
- Search the web using Tavily Search.
- Remember important user information.
- Recall saved memories.
- Solve mathematical calculations.

Tool Usage Rules:

1. Web Search
   Use Tavily Search whenever the user asks about:
   - latest news, current events, today's information, recent updates
   - weather, stock prices, cryptocurrency
   - AI models, software versions
   - anything that changes over time
   Always mention that the answer is based on web search.

2. Uploaded Documents
   If the user asks about uploaded PDFs, resumes, notes, or files, use the document search tool.

3. Memory
   If the user asks you to remember something, use the memory tool.
   If previous memories can help answer the question, recall them.

4. Calculator
   Use the calculator tool for arithmetic instead of estimating.

General Rules:
- Be accurate and concise.
- Never guess when a tool can provide a better answer.
- Never fabricate search results."""


# LLM CACHE
_LLM_CACHE = {}
def get_llm(model_name: str = DEFAULT_MODEL):
    """Get LLM with tool binding. Supports 'groq' or 'gemini'."""
    if model_name not in _LLM_CACHE:
        if model_name == "gemini":
            # Swap priority: Gemini first, then Groq
            router = SmartLLM(backup_llm, primary_llm)
        else:
            # Default: Groq first, then Gemini
            router = SmartLLM(primary_llm, backup_llm)
        _LLM_CACHE[model_name] = router.bind_tools(tools)
    return _LLM_CACHE[model_name]


# STATE & NODES
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    model_name: str


def chatbot_node(state: AgentState):
    model_name = state.get("model_name", DEFAULT_MODEL)
    llm = get_llm(model_name)
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


# LANGGRAPH WORKFLOW
tool_node = ToolNode(tools)
workflow = StateGraph(AgentState)

workflow.add_node("chatbot", chatbot_node)
workflow.add_node("tools", tool_node)

workflow.add_edge(START, "chatbot")
workflow.add_conditional_edges("chatbot", tools_condition)
workflow.add_edge("tools", "chatbot")


DB_PATH = Path("data") / "checkpoints.sqlite"

# Compiled graph + sqlite connection are built once and cached, instead of
# reconnecting/recompiling on every request.
_compiled_agent = None
_agent_build_lock = threading.Lock()


def get_agent(model_name: str | None = None):
    """
    Returns a compiled LangGraph app with a SQLite checkpointer.
    The compiled graph is built once and reused across calls.

    Usage:
        from langchain_core.messages import HumanMessage

        # Set the thread ID for memory/RAG tools
        set_current_thread_id("user_123")

        agent = get_agent()
        inputs = {
            "messages": [HumanMessage(content="Hello")],
            "model_name": "groq",   # "groq" | "gemini"
        }
        config = {"configurable": {"thread_id": "user_123"}}

        for chunk in agent.stream(inputs, config=config, stream_mode="messages"):
            print(chunk)
    """
    global _compiled_agent
    if _compiled_agent is None:
        with _agent_build_lock:
            if _compiled_agent is None:
                conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
                checkpointer = SqliteSaver(conn)
                _compiled_agent = workflow.compile(checkpointer=checkpointer)
    return _compiled_agent