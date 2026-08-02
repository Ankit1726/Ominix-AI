import json, uvicorn
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk, ToolMessage

from agent.tools import set_current_thread_id
from agent.main import get_agent
from agent.db import (
    init_db,
    save_chat_message,
    get_chat_history,
    create_conversation,
    list_conversations,
)

app = FastAPI()
templates = Jinja2Templates(directory="frontend/templates")

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

Path("data").mkdir(exist_ok=True)
init_db()


# Home Route
@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})


# Conversation Route
@app.get("/conversations")
async def conversations():
    items = list_conversations()
    return {
        "conversations": [
            {
                "thread_id": item.thread_id,
                "title": item.title,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
            for item in items
        ]
    }


# History Route
@app.get("/history/{thread_id}")
async def history(thread_id: str):
    messages = get_chat_history(thread_id)
    return {
        "messages": [{"role": msg.role, "content": msg.content} for msg in messages]
    }


def sse_data(payload: dict) -> str:
    return f"data:{json.dumps(payload,ensure_ascii=False)}\n\n"


def stream_chunk(chunk, metadata) -> bool:
    """
    This prevents raw tool/search JSON from appearing in the frontend.

    We only stream normal AI text chunks.
    We do NOT stream:
    - ToolMessage
    - messages from tool nodes
    - tool call chunks
    - raw tool outputs
    """
    metadata = metadata or {}

    node_name = str(metadata.get("langgraph_node", "")).lower()

    if "tool" in node_name:
        return False

    if isinstance(chunk, ToolMessage):
        return False

    if not isinstance(chunk, (AIMessage, AIMessageChunk)):
        return False

    if getattr(chunk, "tool_calls", None):
        return False

    if getattr(chunk, "invalid_tool_calls", None):
        return False

    additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}

    if additional_kwargs.get("tool_calls"):
        return False

    return True


def extract_chunk(chunk) -> str:
    content = getattr(chunk, "content", "")

    if not content:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts = []

        for item in content:
            if isinstance(item, str):
                text_parts.append(item)

            elif isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    text_parts.append(item["text"])
                elif isinstance(item.get("text"), str):
                    text_parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    text_parts.append(item["content"])

        return "".join(text_parts)

    return ""


@app.post("/chat/stream")
async def chat_stream(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body."}, status_code=400)

    user_message = data.get("message", "")
    thread_id = data.get("thread_id", "default")
    selected_model = data.get("model", "gemini-2.5-flash")

    if not user_message.strip():
        return JSONResponse({"error": "Message is required."}, status_code=400)

    agent = get_agent(selected_model)

    create_conversation(thread_id, user_message)
    save_chat_message(thread_id, "user", user_message)
    set_current_thread_id(thread_id)

    config = {"configurable": {"thread_id": thread_id}}

    def event_generator():
        final_answer = ""

        try:
            inputs = {"messages": [HumanMessage(content=user_message)]}

            for chunk, metadata in agent.stream(
                inputs, config=config, stream_mode="messages"
            ):
                if not stream_chunk(chunk, metadata):
                    continue

                token = extract_chunk(chunk)

                if token:
                    final_answer += token
                    yield sse_data({"token": token})

            if final_answer.strip():
                save_chat_message(thread_id, "assistant", final_answer)

            yield sse_data({"done": True})

        except Exception as e:
            yield sse_data({"error": str(e)})
            yield sse_data({"done": True})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)
