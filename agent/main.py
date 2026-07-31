import os, sqlite3
from pathlib import Path
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, START, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.sqlite import SqliteSaver
from agent.tools import tools
from agent.prompt import SYSTEM_PROMPT as prompt

from dotenv import load_dotenv

load_dotenv()

Path("data").mkdir(exist_ok=True)
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

ALLOWED_MODELS = {
    "llama-3.1-8b-instant",
    "qwen/qwen3-32b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "deepseek-r1-distill-llama-70b",
}


def normalize_model_name(model_name: str | None) -> str:
    """
    Validate selected model from frontend.
    If model is missing or not allowed, fallback to DEFAULT_MODEL.
    """

    if not model_name:
        return DEFAULT_MODEL

    model_name = model_name.strip()

    if model_name not in ALLOWED_MODELS:
        return DEFAULT_MODEL

    return model_name


def build_agent(model_name: str):
    """
    Build one LangGraph agent for a selected Gemini model.
    """

    selected_model = normalize_model_name(model_name)

    # Initialize Groq Model
    llm = ChatGroq(model=selected_model, temperature=0.3, streaming=True)

    llm_with_tools = llm.bind_tools(tools)

    def chatbot_node(state: MessagesState):
        messages = [SystemMessage(content=prompt)] + state["messages"]

        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    # Build Graph
    tool_node = ToolNode(tools)
    workflow = StateGraph(MessagesState)
    workflow.add_node("chatbot", chatbot_node)
    workflow.add_node("tools", tool_node)

    workflow.add_edge(START, "chatbot")
    workflow.add_conditional_edges("chatbot", tools_condition)
    workflow.add_edge("tools", "chatbot")

    conn = sqlite3.connect("data/langgraph_checkpoints.sqlite", check_same_thread=False)

    checkpointer = SqliteSaver(conn)
    return workflow.compile(checkpointer=checkpointer)


_AGENT_CACHE = {}


def get_agent(model_name: str | None = None):
    """
    Return cached LangGraph agent for selected model.
    If not created yet, create it once and reuse it.
    """

    selected_model = normalize_model_name(model_name)

    if selected_model not in _AGENT_CACHE:
        _AGENT_CACHE[selected_model] = build_agent(selected_model)

    return _AGENT_CACHE[selected_model]
