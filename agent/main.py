import os
import re
from groq import RateLimitError
from langchain_groq import ChatGroq
from langchain_mistralai import ChatMistralAI
from langchain_core.messages import SystemMessage, trim_messages
from langgraph.graph import StateGraph, START, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from agent.tools import create_tools
from agent.prompt import SYSTEM_PROMPT as prompt

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = (
    os.getenv("DEFAULT_MODEL") or os.getenv("MISTRAL_MODEL") or "mistral-medium-latest"
)

# Models that are always routed to Groq.
GROQ_MODELS = {
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b"
}

GROQ_MODELS |= {
    name.strip()
    for name in os.getenv("GROQ_EXTRA_MODELS", "").split(",")
    if name.strip()
}
# FIX: previously checked MISTRAL_MODEL and then read GROQ_MODEL (KeyError / wrong var).
if (os.getenv("GROQ_MODEL") or "").strip():
    GROQ_MODELS.add(os.environ["GROQ_MODEL"].strip())

# Name prefixes that identify Mistral-hosted models.
MISTRAL_PREFIXES = (
    "mistral",
    "open-mistral",
    "open-mixtral",
    "codestral",
    "ministral",
    "pixtral",
    "magistral",
    "devstral",
    "voxtral",
)


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


MAX_CONTEXT_MESSAGES = _int_env("MAX_CONTEXT_MESSAGES", 40)
LLM_TIMEOUT_SECONDS = _int_env("LLM_TIMEOUT_SECONDS", 60)
LLM_MAX_RETRIES = _int_env("LLM_MAX_RETRIES", 2)


def normalize_model_name(model_name: str | None) -> str:
    if not model_name:
        return DEFAULT_MODEL
    model_name = model_name.strip()
    if not model_name:
        return DEFAULT_MODEL
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model_name):
        raise ValueError(
            "Model ID must contain only letters, numbers, '.', '_', ':', '/', or '-'."
        )

    return model_name


def is_mistral_model(model_name: str) -> bool:
    """Explicit Groq models win; otherwise Mistral-looking names go to Mistral;
    anything else (e.g. a custom ID typed in Settings) goes to Groq."""
    if model_name in GROQ_MODELS:
        return False
    return model_name.lower().startswith(MISTRAL_PREFIXES)


def _build_groq(model: str, api_key: str) -> ChatGroq:
    return ChatGroq(
        model=model,
        api_key=api_key,
        temperature=0.3,
        streaming=True,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
    )


def build_agent(
    model_name: str,
    thread_id: str,
    checkpointer,
    groq_api_key: str | None = None,
    tavily_api_key: str | None = None,
):
    selected_model = normalize_model_name(model_name)

    fallback_llm = None
    # FIX: condition was inverted (Groq models were sent to Mistral).
    if is_mistral_model(selected_model):
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError(
                "A Mistral model is selected, but no Mistral API key is configured. "
                "Select a Groq model or configure MISTRAL_API_KEY."
            )
        llm = ChatMistralAI(
            model=selected_model,
            api_key=api_key,
            temperature=0.3,
            streaming=True,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )
    else:
        shared_api_key = os.getenv("GROQ_API_KEY")
        api_key = shared_api_key or groq_api_key
        if not api_key:
            raise ValueError(
                "A Groq API key is required. Add your key in Settings or configure GROQ_API_KEY."
            )
        llm = _build_groq(selected_model, api_key)
        if shared_api_key and groq_api_key and groq_api_key != shared_api_key:
            fallback_llm = _build_groq(selected_model, groq_api_key)

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
        history = state["messages"]
        try:
            # start_on="human" guarantees we never begin with an orphaned tool message
            trimmed = trim_messages(
                history,
                strategy="last",
                token_counter=len,
                max_tokens=MAX_CONTEXT_MESSAGES,
                start_on="human",
                include_system=False,
                allow_partial=False,
            )
        except Exception:
            trimmed = history
        if not trimmed:
            trimmed = history

        messages = [SystemMessage(content=prompt)] + list(trimmed)
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
