import os
import re
from groq import RateLimitError
from langchain_groq import ChatGroq
from langchain_mistralai import ChatMistralAI
from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, START, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from agent.tools import create_tools
from agent.prompt import SYSTEM_PROMPT as prompt

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = (
    os.getenv("DEFAULT_MODEL")
    or os.getenv("MISTRAL_MODEL")
    or "mistral-medium-latest"
)

MISTRAL_MODELS = {
    "ministral-3b-latest",
    "ministral-8b-latest",
    "mistral-medium-latest",
}


def normalize_model_name(model_name: str | None) -> str:
    if not model_name:
        return DEFAULT_MODEL
    model_name = model_name.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model_name):
        raise ValueError("Model ID must contain only letters, numbers, '.', '_', ':', '/', or '-'.")

    return model_name


def build_agent(
    model_name: str,
    thread_id: str,
    checkpointer,
    groq_api_key: str | None = None,
    tavily_api_key: str | None = None,
):
    selected_model = normalize_model_name(model_name)

    fallback_llm = None
    if selected_model in MISTRAL_MODELS:
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError(
                "Mistral is selected, but no Mistral API key is configured. "
                "Select a Groq model or configure MISTRAL_API_KEY."
            )
        llm = ChatMistralAI(
            model=selected_model,
            api_key=api_key,
            temperature=0.3,
            streaming=True,
        )
    else:
        shared_api_key = os.getenv("GROQ_API_KEY")
        api_key = shared_api_key or groq_api_key
        if not api_key:
            raise ValueError(
                "A Groq API key is required. Add your key in Settings or configure GROQ_API_KEY."
            )
        llm = ChatGroq(
            model=selected_model,
            api_key=api_key,
            temperature=0.3,
            streaming=True,
        )
        if shared_api_key and groq_api_key and groq_api_key != shared_api_key:
            fallback_llm = ChatGroq(
                model=selected_model,
                api_key=groq_api_key,
                temperature=0.3,
                streaming=True,
            )

    tools = create_tools(
        thread_id=thread_id,
        tavily_api_key=tavily_api_key or os.getenv("TAVILY_API_KEY"),
    )
    llm_with_tools = llm.bind_tools(tools)
    if fallback_llm:
        llm_with_tools = llm_with_tools.with_fallbacks(
            [fallback_llm.bind_tools(tools)],
            exceptions_to_handle=(RateLimitError,),
        )

    def chatbot_node(state: MessagesState):
        messages = [SystemMessage(content=prompt)] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(tools)
    workflow = StateGraph(MessagesState)
    workflow.add_node("chatbot", chatbot_node)
    workflow.add_node("tools", tool_node)
    workflow.add_edge(START, "chatbot")
    workflow.add_conditional_edges("chatbot", tools_condition)
    workflow.add_edge("tools", "chatbot")

    return workflow.compile(checkpointer=checkpointer)


def get_agent(
    model_name: str | None,
    thread_id: str,
    checkpointer,
    groq_api_key: str | None = None,
    tavily_api_key: str | None = None,
):
    return build_agent(
        model_name=model_name or DEFAULT_MODEL,
        thread_id=thread_id,
        checkpointer=checkpointer,
        groq_api_key=groq_api_key,
        tavily_api_key=tavily_api_key,
    )
