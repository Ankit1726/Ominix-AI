import os
import sqlite3
from pathlib import Path

from langchain_core.messages import SystemMessage
from langchain_google_genai import GoogleGenerativeAI
from langchain_groq import ChatGroq

from langgraph.graph import StateGraph, START,END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.sqlite import SqliteSaver
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

from src.tool import tools
from dotenv import load_dotenv
load_dotenv()



# Create data directory
Path("data").mkdir(exist_ok=True)


# Models
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

ALLOWED_MODELS = {
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3-32b",
    "kimi-k2-instruct",
}

FALLBACK_MODEL = "gemini-2.5-flash"


# System Prompt
SYSTEM_PROMPT = """
        - You are AnkitGPT, a helpful Agentic AI assistant similar to ChatGPT.

        - You can:
            - Answer general questions.
            - Use tools whenever they improve the answer.
            - Search uploaded documents using the RAG tool.
            - Search the web using Tavily Search.
            - Remember important user information.
            - Recall saved memories.
            - Solve mathematical calculations.

        - Tool Usage Rules:
            1. Web Search
            - Use Tavily Search whenever the user asks about:
                - latest news
                - current events
                - today's information
                - recent updates
                - weather
                - stock prices
                - cryptocurrency
                - AI models
                - software versions
                - anything that changes over time
            Always mention that the answer is based on web search.

            2. Uploaded Documents
            If the user asks about uploaded PDFs, resumes, notes, or files, use the document search tool.

            3. Memory
            If the user asks you to remember something, use the memory tool.

            If previous memories can help answer the question, recall them.

            4. Calculator
              - Use the calculator tool for arithmetic instead of estimating.
              - General Rules:
                - Be accurate.
                - Be concise.
                - Never guess when a tool can provide a better answer.
                - Never fabricate search results.
            """



# Model Validation
def normalize_model_name(model_name: str | None) -> str:
    if not model_name:
        return DEFAULT_MODEL

    model_name = model_name.strip()
    if model_name not in ALLOWED_MODELS:
        return DEFAULT_MODEL
    return model_name



# Build Agent
def build_agent(model_name: str):
    """
    - Build an LLM with:
        Primary -> Groq
        Fallback -> Gemini
    """

    selected_model = normalize_model_name(model_name)

    primary_llm = ChatGroq(
        model=selected_model,
        temperature=0.3,
        streaming=True,
    )

    fallback_llm = GoogleGenerativeAI(
        model=FALLBACK_MODEL,
        temperature=0.3,
        streaming=True,
    )
    llm = primary_llm.with_fallbacks([fallback_llm])
    return llm.bind_tools(tools)



# Agent Cache
_AGENT_CACHE = {}


def get_agent(model_name: str | None = None):
    selected_model = normalize_model_name(model_name)
    if selected_model not in _AGENT_CACHE:
        _AGENT_CACHE[selected_model] = build_agent(selected_model)
    return _AGENT_CACHE[selected_model]



# Chatbot Node

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    model_name: str

def chatbot_node(state: AgentState):
    model_name = state.get("model_name", DEFAULT_MODEL)
    llm = get_agent(model_name)

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


# SQLite Checkpointer
DB_PATH = Path("data") / "checkpoints.sqlite"
conn = sqlite3.connect(
    DB_PATH,
    check_same_thread=False
)
checkpointer = SqliteSaver(conn)
workflow.compile(checkpointer=checkpointer)