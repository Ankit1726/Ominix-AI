from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASE_URL = f"sqlite:///{DATA_DIR / 'ominix.db'}"

connect_args = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(String, unique=True, index=True)
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


def init_db():
    Base.metadata.create_all(bind=engine)
