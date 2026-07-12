import os
import sqlite3
from pathlib import Path

from langchain_tavily import TavilySearch
from langchain_core.messages import SystemMessage, HumanMessage
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

from dotenv import load_dotenv

load_dotenv()

# Setup
Path("data").mkdir(exist_ok=True)
DEFAULT_MODEL = "groq"


#  LLMs 
primary_llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    api_key=os.getenv("GROQ_API_KEY"),
    streaming=True
)

backup_llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.3,
    api_key=os.getenv("GOOGLE_API_KEY"),
    streaming=True
)

class SmartLLM:
    """
    Automatically switches to backup model when
    primary model hits rate limits or quota.
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

    def invoke(self, messages, **kwargs):

        try:
            print("🟢 Using Groq")
            return self.primary.invoke(messages, **kwargs)

        except Exception as e:

            err = str(e).lower()

            retry_errors = [
                "429",
                "rate limit",
                "quota",
                "resource exhausted",
                "too many requests",
                "tokens per day",
                "request too large",
                "daily limit",
            ]

            if any(x in err for x in retry_errors):
                print("🟡 Groq limit reached. Switching to Gemini...")
                return self.backup.invoke(messages, **kwargs)

            raise

agent_llm = SmartLLM(primary_llm, backup_llm)


# Web search
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


# System Prompt
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


# LLM Cache (binds tools once per model config)
_LLM_CACHE = {}

def get_llm(model_name: str = DEFAULT_MODEL):
    if model_name not in _LLM_CACHE:
        if model_name == "gemini":
            router = SmartLLM(backup_llm, primary_llm)
        else:
            router = SmartLLM(primary_llm, backup_llm)

        _LLM_CACHE[model_name] = router.bind_tools(tools)
    return _LLM_CACHE[model_name]


# State & Nodes
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    model_name: str


def chatbot_node(state: AgentState):
    model_name = state.get("model_name", DEFAULT_MODEL)
    llm = get_llm(model_name)

    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}



# LangGraph Workflow
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
            "model_name": "groq",   # or "gemini"
        }
        config = {"configurable": {"thread_id": "user_123"}}

        for chunk in agent.stream(inputs, config=config, stream_mode="messages"):
            print(chunk)
    """
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    compiled = workflow.compile(checkpointer=checkpointer)
    return compiled
