from datetime import datetime
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import (
    create_engine,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    DateTime,
    inspect,
    text,
)

load_dotenv()
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def get_database_url():
    db_url = os.getenv("DATABASE_URL")

    if db_url:
        if db_url.startswith("postgres://"):
            db_url = "postgresql://" + db_url[len("postgres://") :]
        if db_url.startswith(("postgresql://", "postgresql+")) and "sslmode" not in db_url:
            separator = "&" if "?" in db_url else "?"
            db_url = f"{db_url}{separator}sslmode=require"
        return db_url
    return f"sqlite:///{(DATA_DIR / 'ominix.db').as_posix()}"


DATABASE_URL = get_database_url()
connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String, unique=True, index=True)
    owner_id = Column(String(64), index=True, nullable=True)
    title = Column(String, default="New Chat")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String, index=True)
    role = Column(String)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class LongTermMemory(Base):
    __tablename__ = "long_term_memory"
    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String, index=True)
    memory = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String, index=True)
    filename = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("uploaded_documents.id"), index=True)
    content = Column(Text)


def init_db():
    Base.metadata.create_all(bind=engine)
    if "owner_id" not in {
        column["name"] for column in inspect(engine).get_columns("conversations")
    }:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE conversations ADD COLUMN owner_id VARCHAR(64)")
            )
