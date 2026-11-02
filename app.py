import asyncio
from contextlib import asynccontextmanager
import json
import hashlib
import logging
import os
import re
import secrets
import sqlite3
import zipfile
from io import BytesIO
import uvicorn
from pathlib import Path
from xml.etree import ElementTree

import uvicorn
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import text

from agent.db import (
    create_conversation,
    conversation_belongs_to,
    delete_document,
    get_chat_history,
    list_conversations,
    list_documents,
    save_chat_message,
    save_document,
)
from agent.main import DEFAULT_MODEL, get_agent, normalize_model_name
from agent.schema import engine, init_db

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
MAX_MESSAGE_LENGTH = 20_000
MAX_API_KEY_LENGTH = 512
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_DOCUMENT_CHARS = 1_000_000
THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SESSION_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
ALLOWED_DOCUMENT_TYPES = {".txt", ".md", ".pdf", ".docx"}

@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(init_db)
    yield


app = FastAPI(title="Ominix AI", version="1.0.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "frontend" / "templates"))
app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "frontend" / "static")),
    name="static",
)

(BASE_DIR / "data").mkdir(exist_ok=True)


@app.middleware("http")
async def private_workspace(request: Request, call_next):
    session_token = request.cookies.get("ominix_session", "")
    new_session = not SESSION_PATTERN.fullmatch(session_token)
    if new_session:
        session_token = secrets.token_urlsafe(32)
    request.state.owner_id = hashlib.sha256(
        session_token.encode("utf-8")
    ).hexdigest()

    response = await call_next(request)
    if new_session:
        response.set_cookie(
            "ominix_session",
            session_token,
            max_age=60 * 60 * 24 * 365,
            httponly=True,
            secure=request.url.scheme == "https"
            or bool(os.getenv("RENDER_EXTERNAL_URL")),
            samesite="lax",
            path="/",
        )
    return response


@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={},
    )


@app.get("/healthz")
async def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:
        logger.error("Health check failed: %s", type(error).__name__)
        return JSONResponse({"status": "unhealthy"}, status_code=503)
    return {"status": "ok"}


@app.get("/config")
async def config():
    return {
        "default_model": DEFAULT_MODEL,
        "groq_key_configured": bool(os.getenv("GROQ_API_KEY")),
        "tavily_key_configured": bool(os.getenv("TAVILY_API_KEY")),
        "mistral_key_configured": bool(os.getenv("MISTRAL_API_KEY")),
        "max_document_bytes": MAX_DOCUMENT_BYTES,
        "document_types": sorted(ALLOWED_DOCUMENT_TYPES),
    }


@app.get("/conversations")
async def conversations(request: Request):
    items = list_conversations(request.state.owner_id)
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


def valid_thread_id(thread_id: str) -> bool:
    return bool(THREAD_ID_PATTERN.fullmatch(thread_id))


@app.get("/history/{thread_id}")
async def history(thread_id: str, request: Request):
    if not valid_thread_id(thread_id):
        return JSONResponse({"error": "Invalid conversation ID."}, status_code=400)
    request_owner = request.state.owner_id
    if not conversation_belongs_to(thread_id, request_owner):
        return JSONResponse({"error": "Conversation not found."}, status_code=404)
    messages = get_chat_history(thread_id, request_owner)
    return {
        "messages": [{"role": msg.role, "content": msg.content} for msg in messages]
    }


@app.get("/documents/{thread_id}")
async def documents(thread_id: str, request: Request):
    if not valid_thread_id(thread_id):
        return JSONResponse({"error": "Invalid conversation ID."}, status_code=400)
    if not conversation_belongs_to(thread_id, request.state.owner_id):
        return JSONResponse({"error": "Conversation not found."}, status_code=404)
    items = list_documents(thread_id)
    return {
        "documents": [
            {
                "id": item.id,
                "filename": item.filename,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ]
    }


def extract_document_text(filename: str, content: bytes) -> str:
    extension = Path(filename).suffix.lower()
    if extension in {".txt", ".md"}:
        extracted = content.decode("utf-8-sig").strip()
    elif extension == ".pdf":
        reader = PdfReader(BytesIO(content))
        if len(reader.pages) > 200:
            raise ValueError("PDF files must contain 200 pages or fewer.")
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    elif extension == ".docx":
        with zipfile.ZipFile(BytesIO(content)) as archive:
            document = archive.getinfo("word/document.xml")
            if document.file_size > MAX_DOCUMENT_CHARS * 4:
                raise ValueError("The document contains too much text to process.")
            root = ElementTree.fromstring(archive.read(document))
        extracted = " ".join(
            node.text or "" for node in root.findall(".//{*}t")
        ).strip()
    else:
        raise ValueError("Supported file types are TXT, Markdown, PDF, and DOCX.")

    if not extracted:
        raise ValueError("No readable text was found in that file.")
    if len(extracted) > MAX_DOCUMENT_CHARS:
        raise ValueError("Documents must contain 1,000,000 characters or fewer.")
    return extracted


def split_document(text_content: str) -> list[str]:
    chunk_size = 1200
    overlap = 200
    return [
        text_content[start : start + chunk_size]
        for start in range(0, len(text_content), chunk_size - overlap)
    ]


@app.post("/documents/{thread_id}")
async def upload_document(thread_id: str, request: Request, file: UploadFile):
    if not valid_thread_id(thread_id):
        return JSONResponse({"error": "Invalid conversation ID."}, status_code=400)
    if not conversation_belongs_to(thread_id, request.state.owner_id):
        if not create_conversation(thread_id, request.state.owner_id):
            return JSONResponse({"error": "Conversation not found."}, status_code=404)
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    extension = Path(filename).suffix.lower()
    if not filename or len(filename) > 255 or extension not in ALLOWED_DOCUMENT_TYPES:
        return JSONResponse(
            {"error": "Choose a TXT, Markdown, PDF, or DOCX file."},
            status_code=400,
        )

    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        return JSONResponse(
            {"error": "Files must be 5 MB or smaller."},
            status_code=413,
        )
    if not content:
        return JSONResponse({"error": "The selected file is empty."}, status_code=400)

    try:
        extracted = extract_document_text(filename, content)
    except (
        UnicodeDecodeError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        PdfReadError,
        KeyError,
        OSError,
        ValueError,
    ) as error:
        if isinstance(error, ValueError):
            message = str(error)
        else:
            message = "That file could not be read. Check that it is not damaged or encrypted."
        return JSONResponse({"error": message}, status_code=400)

    document = save_document(thread_id, filename, split_document(extracted))
    return {
        "document": {
            "id": document["id"],
            "filename": document["filename"],
            "created_at": document["created_at"].isoformat(),
        }
    }


@app.delete("/documents/{thread_id}/{document_id}")
async def remove_document(thread_id: str, document_id: int, request: Request):
    if not valid_thread_id(thread_id):
        return JSONResponse({"error": "Invalid conversation ID."}, status_code=400)
    if not conversation_belongs_to(thread_id, request.state.owner_id):
        return JSONResponse({"error": "Conversation not found."}, status_code=404)
    if document_id < 1:
        return JSONResponse({"error": "Invalid document ID."}, status_code=400)
    if not delete_document(thread_id, document_id):
        return JSONResponse({"error": "Document not found."}, status_code=404)
    return {"deleted": True}


def sse_data(payload: dict) -> str:
    return f"data:{json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_chunk(chunk, metadata) -> bool:
    metadata = metadata or {}
    node_name = str(metadata.get("langgraph_node", "")).lower()
    if "tool" in node_name or isinstance(chunk, ToolMessage):
        return False
    if not isinstance(chunk, (AIMessage, AIMessageChunk)):
        return False
    if getattr(chunk, "tool_calls", None) or getattr(chunk, "invalid_tool_calls", None):
        return False
    return not (getattr(chunk, "additional_kwargs", {}) or {}).get("tool_calls")


def extract_chunk(chunk) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item
            if isinstance(item, str)
            else item.get("text", item.get("content", ""))
            if isinstance(item, dict)
            else ""
            for item in content
        )
    return ""


@app.post("/chat/stream")
async def chat_stream(request: Request):
    try:
        data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return JSONResponse({"error": "Invalid JSON body."}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "A JSON object is required."}, status_code=400)

    user_message = data.get("message")
    thread_id = data.get("thread_id")
    selected_model = data.get("model", DEFAULT_MODEL)
    if not isinstance(user_message, str) or not user_message.strip():
        return JSONResponse({"error": "Message is required."}, status_code=400)
    if len(user_message) > MAX_MESSAGE_LENGTH:
        return JSONResponse(
            {"error": f"Messages must be {MAX_MESSAGE_LENGTH} characters or fewer."},
            status_code=413,
        )
    if not isinstance(thread_id, str) or not valid_thread_id(thread_id):
        return JSONResponse({"error": "Invalid conversation ID."}, status_code=400)
    if not isinstance(selected_model, str) or len(selected_model) > 128:
        return JSONResponse({"error": "Invalid model ID."}, status_code=400)
    try:
        selected_model = normalize_model_name(selected_model)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    for key_name in ("groq_api_key", "tavily_api_key"):
        key_value = data.get(key_name)
        if key_value is not None and (
            not isinstance(key_value, str) or len(key_value) > MAX_API_KEY_LENGTH
        ):
            return JSONResponse({"error": "Invalid API key value."}, status_code=400)

    groq_api_key = (data.get("groq_api_key") or "").strip() or None
    tavily_api_key = (data.get("tavily_api_key") or "").strip() or None
    if not create_conversation(thread_id, request.state.owner_id, user_message):
        return JSONResponse({"error": "Conversation not found."}, status_code=404)
    save_chat_message(thread_id, "user", user_message)
    checkpoint_path = Path(
        os.getenv("CHECKPOINT_DB_PATH", str(BASE_DIR / "data" / "langgraph_checkpoints.sqlite"))
    )

    def event_generator():
        final_answer = ""
        connection = None
        try:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                checkpoint_path,
                timeout=30,
                check_same_thread=False,
            )
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("PRAGMA journal_mode=WAL")
            checkpointer = SqliteSaver(connection)
            agent = get_agent(
                selected_model,
                thread_id,
                checkpointer,
                groq_api_key=groq_api_key,
                tavily_api_key=tavily_api_key,
            )
            config = {"configurable": {"thread_id": thread_id}}
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
        except ValueError as error:
            yield sse_data({"error": str(error)})
            yield sse_data({"done": True})
        except Exception as error:
            logger.error("Chat stream failed: %s", type(error).__name__)
            yield sse_data(
                {
                    "error": (
                        "The AI request failed. Check your API key, model ID, "
                        "provider quota, and network connection."
                    )
                }
            )
            yield sse_data({"done": True})
        finally:
            if connection is not None:
                connection.close()

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
