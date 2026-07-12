from contextlib import contextmanager
from datetime import datetime, UTC
from pathlib import Path
from typing import Generator, List, Optional

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Index, or_
from sqlalchemy.orm import declarative_base, sessionmaker, Session

Path("data").mkdir(exist_ok=True)
DATABASE_URL = "sqlite:///data/chatbot_memory.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    # SQLite is file-based; reduce pool size to avoid "database locked" errors
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# Models
class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, default="New Chat")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String, index=True, nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class LongTermMemory(Base):
    __tablename__ = "long_term_memory"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String, index=True, nullable=False)
    memory = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    # Add a functional index for text search (SQLite supports this via LIKE)
    __table_args__ = (
        Index("ix_memory_content", "memory"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "memory": self.memory,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# Session Context Manager (handles rollback + close automatically)
@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Yield a database session with automatic rollback on exception."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _validate_thread_id(thread_id: str) -> str:
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("thread_id must be a non-empty string")
    return thread_id.strip()


def _validate_non_empty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _now() -> datetime:
    """Return the current UTC-aware datetime."""
    return datetime.now(UTC)


# DB Initialization
def init_db() -> None:
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)


# Conversation CRUD
def create_or_update_conversation(thread_id: str, first_message: Optional[str] = None) -> dict:
    """
    Create a new conversation or update its updated_at timestamp.

    Args:
        thread_id: Unique thread identifier.
        first_message: Optional first message to use as the title (truncated to 40 chars).

    Returns:
        Dict representation of the conversation.
    """
    thread_id = _validate_thread_id(thread_id)

    with get_db() as db:
        conversation = (
            db.query(Conversation)
            .filter(Conversation.thread_id == thread_id)
            .first()
        )

        if not conversation:
            title = "New Chat"
            if first_message:
                clean = first_message.strip()
                title = clean[:40] + ("..." if len(clean) > 40 else "")

            conversation = Conversation(
                thread_id=thread_id,
                title=title,
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(conversation)
        else:
            conversation.updated_at = _now()

        # commit is handled by get_db() context manager
        return conversation.to_dict()


def list_conversations() -> List[dict]:
    """Return all conversations ordered by most recently updated first."""
    with get_db() as db:
        rows = (
            db.query(Conversation)
            .order_by(Conversation.updated_at.desc())
            .all()
        )
        return [row.to_dict() for row in rows]

# Chat Message CRUD
def save_chat_message(thread_id: str, role: str, content: str) -> dict:
    """
    Save a chat message and bump the conversation updated_at timestamp.

    Args:
        thread_id: Conversation thread ID.
        role: Message role (e.g., "user", "assistant", "system").
        content: Message content.

    Returns:
        Dict representation of the saved message.
    """
    thread_id = _validate_thread_id(thread_id)
    role = _validate_non_empty(role, "role")
    content = _validate_non_empty(content, "content")

    with get_db() as db:
        msg = ChatMessage(
            thread_id=thread_id,
            role=role,
            content=content,
            created_at=_now(),
        )
        db.add(msg)

        conversation = (
            db.query(Conversation)
            .filter(Conversation.thread_id == thread_id)
            .first()
        )
        if conversation:
            conversation.updated_at = _now()

        return msg.to_dict()


def get_chat_history(thread_id: str, limit: Optional[int] = None) -> List[dict]:
    """
    Retrieve chat messages for a thread, oldest first.

    Args:
        thread_id: Conversation thread ID.
        limit: Optional max number of messages to return.

    Returns:
        List of message dicts.
    """
    thread_id = _validate_thread_id(thread_id)

    with get_db() as db:
        query = (
            db.query(ChatMessage)
            .filter(ChatMessage.thread_id == thread_id)
            .order_by(ChatMessage.created_at.asc())
        )
        if limit is not None and limit > 0:
            query = query.limit(limit)
        rows = query.all()
        return [row.to_dict() for row in rows]


# Long-Term Memory CRUD
def save_memory(thread_id: str, memory: str) -> str:
    """
    Save a long-term memory, skipping exact duplicates (after whitespace normalization).

    Args:
        thread_id: Conversation thread ID.
        memory: The memory text to save.

    Returns:
        Status message.
    """
    thread_id = _validate_thread_id(thread_id)
    memory = _validate_non_empty(memory, "memory")

    normalized = " ".join(memory.split())  # collapse all whitespace

    with get_db() as db:
        existing = (
            db.query(LongTermMemory)
            .filter(
                LongTermMemory.thread_id == thread_id,
                LongTermMemory.memory == normalized,
            )
            .first()
        )
        if existing:
            return "Memory already exists."

        item = LongTermMemory(
            thread_id=thread_id,
            memory=normalized,
            created_at=_now(),
        )
        db.add(item)
        return "Memory saved successfully."


def search_memory(thread_id: str, query: str) -> str:
    """
    Search long-term memories for a thread.

    Performs a case-insensitive LIKE search on the memory text.
    If the query is empty or generic, returns the 20 most recent memories.

    Args:
        thread_id: Conversation thread ID.
        query: Search query string.

    Returns:
        Formatted string of matching memories.
    """
    thread_id = _validate_thread_id(thread_id)
    query = (query or "").strip()

    with get_db() as db:
        base_query = (
            db.query(LongTermMemory)
            .filter(LongTermMemory.thread_id == thread_id)
        )

        if query:
            # Case-insensitive substring search
            pattern = f"%{query}%"
            base_query = base_query.filter(
                or_(
                    LongTermMemory.memory.ilike(pattern),
                )
            )
            base_query = base_query.order_by(LongTermMemory.created_at.desc())
            rows = base_query.limit(20).all()
        else:
            # No query — return most recent memories
            rows = base_query.order_by(LongTermMemory.created_at.desc()).limit(20).all()

        if not rows:
            return "No saved memory found."

        return "\n".join([f"- {m.memory}" for m in rows])