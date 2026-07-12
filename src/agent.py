import os
import sqlite3
import requests

from langchain_tavily import TavilySearch
from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

# Local LLM support with graceful fallback
try:
    from langchain_ollama import ChatOllama
except ImportError:
    try:
        from langchain_community.chat_models import ChatOllama
    except ImportError:
        ChatOllama = None

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

# Local LLM (ollama)
LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL_NAME", "llama3.1:8b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
LOCAL_LLM_TEMPERATURE = float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.3"))

class LocalLLMManager:
    """
    Manages Ollama lifecycle:
    - Checks if Ollama server is running
    - Auto-pulls the model if not present
    - Provides a ChatOllama instance (cached)
    """

    def __init__(self, model_name: str = LOCAL_MODEL_NAME, base_url: str = OLLAMA_HOST):
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self._llm = None
        self._available = None

    def is_server_running(self) -> bool:
        """Check if Ollama server is reachable."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def is_model_available(self) -> bool:
        """Check if the specific model is already pulled locally."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            data = resp.json()
            models = [m.get("name") for m in data.get("models", [])]
            # Match exact name or model family (e.g., llama3.1 matches llama3.1:8b)
            return any(
                self.model_name in m or m.startswith(self.model_name.split(":")[0])
                for m in models
            )
        except Exception:
            return False

    def pull_model(self, blocking: bool = True) -> bool:
        """Pull the model from Ollama registry."""
        if not self.is_server_running():
            print(f"⚠️  Ollama server not running at {self.base_url}")
            print("   Install Ollama: https://ollama.com/download")
            return False

        print(f"⬇️  Pulling local model '{self.model_name}'... (this may take a few minutes)")
        try:
            resp = requests.post(
                f"{self.base_url}/api/pull",
                json={"name": self.model_name, "stream": False},
                timeout=600,  # Model downloads can take time
            )
            if resp.status_code == 200:
                print(f"✅ Local model '{self.model_name}' ready.")
                self._available = True
                return True
            else:
                print(f"❌ Failed to pull model: {resp.text}")
                return False
        except Exception as e:
            print(f"❌ Error pulling model: {e}")
            return False

    def ensure_model(self) -> bool:
        """Ensure model is available, pulling if necessary."""
        if self._available is True:
            return True
        if not self.is_server_running():
            return False
        if self.is_model_available():
            self._available = True
            return True
        return self.pull_model()

    def get_llm(self):
        """Get ChatOllama instance for tool binding."""
        if ChatOllama is None:
            raise ImportError(
                "langchain_ollama not installed. Run: pip install langchain-ollama"
            )
        if not self.ensure_model():
            raise RuntimeError(
                f"Local model '{self.model_name}' not available. Is Ollama running?"
            )
        if self._llm is None:
            self._llm = ChatOllama(
                model=self.model_name,
                base_url=self.base_url,
                temperature=LOCAL_LLM_TEMPERATURE,
            )
        return self._llm


# Global manager instance (lazy evaluation)
_local_manager = LocalLLMManager()


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


#  SMART 3-TIER LLM
class SmartLLM:
    """
    3-tier fallback:
    1. Primary (Groq)
    2. Backup (Gemini)
    3. Local (Ollama) — auto-downloaded, zero API cost, runs offline
    """

    def __init__(self, primary, backup, local_manager=None):
        self.primary = primary
        self.backup = backup
        self.local_manager = local_manager

    def bind_tools(self, tools):
        return SmartLLMBound(
            self.primary.bind_tools(tools),
            self.backup.bind_tools(tools),
            self.local_manager,
            tools,
        )


class SmartLLMBound:
    def __init__(self, primary, backup, local_manager, tools):
        self.primary = primary
        self.backup = backup
        self.local_manager = local_manager
        self.tools = tools
        self._local_bound = None

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
            if not self._is_rate_limit(e2):
                raise

        # Tier 3: Local (Ollama)
        if self.local_manager:
            try:
                print("🔴 API limits hit. Falling back to Local LLM (Ollama)...")
                local_llm = self.local_manager.get_llm()
                if self._local_bound is None:
                    self._local_bound = local_llm.bind_tools(self.tools)
                return self._local_bound.invoke(messages, **kwargs)
            except Exception as local_err:
                print(f"❌ Local LLM failed: {local_err}")
                raise RuntimeError(
                    "All LLM tiers failed:"
                    "  1. Groq: Rate limited"
                    "  2. Gemini: Rate limited"
                    f"  3. Local: {local_err}"
                    "Ensure Ollama is installed and running: https://ollama.com/download"
                )
        else:
            raise RuntimeError(
                "All API LLMs rate limited and no local fallback configured."
            )


agent_llm = SmartLLM(primary_llm, backup_llm, _local_manager)


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
    """Get LLM with tool binding. Supports 'groq', 'gemini', or 'local'."""
    if model_name not in _LLM_CACHE:
        if model_name == "gemini":
            # Swap priority: Gemini first, then Groq, then Local
            router = SmartLLM(backup_llm, primary_llm, _local_manager)
        elif model_name == "local":
            # Force local only
            local_llm = _local_manager.get_llm()
            _LLM_CACHE[model_name] = local_llm.bind_tools(tools)
            return _LLM_CACHE[model_name]
        else:
            # Default: Groq first, then Gemini, then Local
            router = SmartLLM(primary_llm, backup_llm, _local_manager)
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
def get_agent(model_name: str | None = None):
    """
    Returns a compiled LangGraph app with a SQLite checkpointer.

    Usage:
        from langchain_core.messages import HumanMessage

        # Set the thread ID for memory/RAG tools
        set_current_thread_id("user_123")

        agent = get_agent()
        inputs = {
            "messages": [HumanMessage(content="Hello")],
            "model_name": "groq",   # "groq" | "gemini" | "local"
        }
        config = {"configurable": {"thread_id": "user_123"}}

        for chunk in agent.stream(inputs, config=config, stream_mode="messages"):
            print(chunk)
    """
    if _local_manager.is_server_running() and not _local_manager.is_model_available():
        print("🔧 Local LLM not cached. Will auto-download on first fallback use.")

    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    compiled = workflow.compile(checkpointer=checkpointer)
    return compiled