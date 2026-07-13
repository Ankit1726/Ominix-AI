import asyncio
import json
import logging
import re
import uuid

from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk, ToolMessage

from src.rag import add_document_to_rag
from src.tool import set_current_thread_id
from src.agent import get_agent
from src.db import (
    init_db,
    save_chat_message,
    get_chat_history,
    create_or_update_conversation,
    list_conversations,
)


# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


# App Setup
app = FastAPI(title="AnkitGPT", version="1.1.0")

# CORS — allow frontend on any local port during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure directories exist before mounting
Path("templates").mkdir(exist_ok=True)
Path("static").mkdir(exist_ok=True)
Path("uploads").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Init DB
init_db()


# Constants
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".py", ".csv"}
MAX_UPLOAD_SIZE_MB = 50
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024


def _sse_data(payload: dict) -> str:
    return f"data:{json.dumps(payload, ensure_ascii=False)}\n\n"


def _validate_thread_id(thread_id: str) -> str:
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("thread_id must be a non-empty string")
    return thread_id.strip()


def _sanitize_filename(filename: str) -> str:
    """
    Strip path traversal, null bytes, and control characters from a filename.
    Returns a safe basename or raises ValueError if nothing usable remains.
    """
    if not filename:
        raise ValueError("No filename provided")

    basename = Path(filename).name
    basename = basename.replace("\x00", "")
    basename = re.sub(r"[\x00-\x1f\x7f]", "", basename)
    basename = basename.replace("/", "_").replace("\\", "_")
    basename = " ".join(basename.split())

    if not basename or basename in {".", "..", ""}:
        raise ValueError("Invalid filename after sanitization")

    return basename


def _extract_attr(obj: Any, attr: str, default: Any = None) -> Any:
    """Safely get an attribute or dict key, handling both ORM objects and dicts."""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _isoformat(value: Any) -> str | None:
    """Safely call .isoformat() on a datetime or return None."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def should_stream_chunk(chunk, metadata) -> bool:
    """
    Filter out tool messages, tool call chunks, and raw tool outputs
    so only AI text reaches the frontend.
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


def extract_text_from_chunk(chunk) -> str:
    """Extract plain text from an LLM chunk (handles str, list, dict content)."""
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
                text = item.get("text") or item.get("content") or ""
                if isinstance(text, str):
                    text_parts.append(text)
        return "".join(text_parts)
    return ""


# ==================== ROUTES ====================

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health():
    """
    Health check that reports which LLM tiers are ready.
    Useful for frontend model selector and diagnostics.
    """
    return {
        "status": "ok",
        "version": "1.1.0",
        "llm_tiers": {
            "groq": {"ready": True, "note": "Cloud API"},
            "gemini": {"ready": True, "note": "Cloud API"},
        },
    }


@app.get("/conversations")
async def conversations():
    try:
        items = await asyncio.to_thread(list_conversations)
    except Exception as e:
        logger.exception("Failed to list conversations")
        return JSONResponse({"error": str(e)}, status_code=500)

    return {
        "conversations": [
            {
                "thread_id": _extract_attr(item, "thread_id"),
                "title": _extract_attr(item, "title"),
                "created_at": _isoformat(_extract_attr(item, "created_at")),
                "updated_at": _isoformat(_extract_attr(item, "updated_at")),
            }
            for item in items
        ]
    }


@app.get("/history/{thread_id}")
async def history(thread_id: str):
    try:
        thread_id = _validate_thread_id(thread_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    try:
        msgs = await asyncio.to_thread(get_chat_history, thread_id)
    except Exception as e:
        logger.exception("Failed to get chat history")
        return JSONResponse({"error": str(e)}, status_code=500)

    return {
        "messages": [
            {
                "role": _extract_attr(m, "role"),
                "content": _extract_attr(m, "content"),
                "created_at": _isoformat(_extract_attr(m, "created_at")),
            }
            for m in msgs
        ]
    }


@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    thread_id: str = Form(...),
):
    try:
        thread_id = _validate_thread_id(thread_id)
    except ValueError as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

    try:
        filename = _sanitize_filename(file.filename or "uploaded_file")
    except ValueError as e:
        return JSONResponse(
            {"success": False, "message": str(e)},
            status_code=400,
        )

    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            {
                "success": False,
                "message": (
                    f"Unsupported file type '{suffix}'. "
                    f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
                ),
            },
            status_code=400,
        )

    try:
        contents = await file.read()
    except Exception as e:
        logger.exception("Failed to read uploaded file")
        return JSONResponse(
            {"success": False, "message": f"Failed to read file: {e}"},
            status_code=400,
        )

    if len(contents) > MAX_UPLOAD_SIZE_BYTES:
        return JSONResponse(
            {
                "success": False,
                "message": (
                    f"File too large ({len(contents) / (1024 * 1024):.1f} MB). "
                    f"Max: {MAX_UPLOAD_SIZE_MB} MB"
                ),
            },
            status_code=413,
        )

    file_id = str(uuid.uuid4())
    safe_filename = filename.replace(" ", "_")
    file_path = Path("uploads") / f"{file_id}_{safe_filename}"

    try:
        file_path.write_bytes(contents)
    except Exception as e:
        logger.exception("Failed to write uploaded file")
        return JSONResponse(
            {"success": False, "message": f"Failed to save file: {e}"},
            status_code=500,
        )

    try:
        await asyncio.to_thread(create_or_update_conversation, thread_id, "uploaded document")
        result = await asyncio.to_thread(add_document_to_rag, file_path=str(file_path), thread_id=thread_id)
    except Exception as e:
        logger.exception("RAG ingestion failed")
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
        return JSONResponse(
            {"success": False, "message": f"Ingestion failed: {e}"},
            status_code=500,
        )

    return JSONResponse(
        {
            "success": True,
            "message": (
                f"Uploaded {result.get('filename', filename)} "
                f"and created {result.get('chunks', '?')} chunks."
            ),
        }
    )


@app.post("/chat/stream")
async def chat_stream(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body."}, status_code=400)

    user_message = data.get("message", "")
    thread_id = data.get("thread_id", "default")
    selected_model = data.get("model", "groq")

    if not isinstance(user_message, str) or not user_message.strip():
        return JSONResponse({"error": "Message is required."}, status_code=400)

    try:
        thread_id = _validate_thread_id(thread_id)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    try:
        await asyncio.to_thread(create_or_update_conversation, thread_id, user_message)
        await asyncio.to_thread(save_chat_message, thread_id, "user", user_message)
    except Exception as e:
        logger.exception("Pre-stream DB write failed")
        return JSONResponse({"error": f"Failed to initialize conversation: {e}"}, status_code=500)

    try:
        agent = await asyncio.to_thread(get_agent, selected_model)
    except Exception as e:
        logger.exception("Failed to load agent")
        return JSONResponse({"error": f"Failed to load agent: {e}"}, status_code=500)

    config = {"configurable": {"thread_id": thread_id}}

    async def event_generator():
        final_answer = ""
        queue: asyncio.Queue = asyncio.Queue()

        # asyncio.Queue is NOT thread-safe. _sync_stream below runs in a
        # worker thread via run_in_executor, so all writes from that thread
        # must be marshalled back onto the event loop.
        loop = asyncio.get_running_loop()

        def _put(item):
            loop.call_soon_threadsafe(queue.put_nowait, item)

        def _sync_stream():
            nonlocal final_answer
            try:
                # BUG FIX: loop.run_in_executor spawns a real OS thread and
                # does NOT copy the caller's contextvars.Context into it
                # (unlike asyncio.to_thread, which does). set_current_thread_id
                # must be called here, inside the worker thread, or every
                # tool call in the graph (RAG search, memory) silently falls
                # back to the default thread_id instead of the real one.
                set_current_thread_id(thread_id)
                inputs = {
                    "messages": [HumanMessage(content=user_message)],
                    "model_name": selected_model,
                }
                for chunk, metadata in agent.stream(
                    inputs, config=config, stream_mode="messages"
                ):
                    if not should_stream_chunk(chunk, metadata):
                        continue
                    token = extract_text_from_chunk(chunk)
                    if token:
                        final_answer += token
                        _put(("token", token))
                _put(("done", final_answer))
            except Exception as e:
                logger.exception("Error during agent stream")
                _put(("error", str(e)))
                _put(("done", ""))

        stream_task = loop.run_in_executor(None, _sync_stream)

        try:
            while True:
                msg_type, data = await queue.get()
                if msg_type == "token":
                    yield _sse_data({"token": data})
                elif msg_type == "error":
                    err_msg = str(data)
                    if "All LLM tiers failed" in err_msg:
                        yield _sse_data({
                            "error": (
                                "All AI models are currently unavailable.\n\n"
                                "Please check your internet connection and "
                                "Groq/Gemini API keys.\n\n"
                                f"Technical: {err_msg}"
                            )
                        })
                    else:
                        yield _sse_data({"error": err_msg})
                    yield _sse_data({"done": True})
                    break
                elif msg_type == "done":
                    if data and isinstance(data, str) and data.strip():
                        try:
                            await asyncio.to_thread(
                                save_chat_message, thread_id, "assistant", data
                            )
                        except Exception:
                            logger.exception("Failed to save assistant message")
                    yield _sse_data({"done": True})
                    break
        finally:
            if not stream_task.done():
                stream_task.cancel()
            try:
                await stream_task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=False)