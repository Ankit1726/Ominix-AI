from datetime import datetime

from agent.schema import (
    Conversation,
    ChatMessage,
    LongTermMemory,
    UploadedDocument,
    DocumentChunk,
    SessionLocal,
)

def create_conversation(
    thread_id: str,
    owner_id: str,
    first_message: str | None = None,
) -> bool:
    db = SessionLocal()
    try:
        conversation = (
            db.query(Conversation).filter(Conversation.thread_id == thread_id).first()
        )
        if not conversation:
            title = "New Chat"
            if first_message:
                title = first_message.strip()[:40]
                if len(first_message.strip()) > 40:
                    title += "..."
            conversation = Conversation(
                thread_id=thread_id,
                owner_id=owner_id,
                title=title,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(conversation)
        elif conversation.owner_id is None:
            conversation.owner_id = owner_id
            conversation.updated_at = datetime.utcnow()
        elif conversation.owner_id != owner_id:
            return False
        else:
            conversation.updated_at = datetime.utcnow()
        db.commit()
        return True
    finally:
        db.close()


def list_conversations(owner_id: str):
    db = SessionLocal()
    try:
        return (
            db.query(Conversation)
            .filter(Conversation.owner_id == owner_id)
            .order_by(Conversation.updated_at.desc())
            .all()
        )
    finally:
        db.close()


def save_chat_message(thread_id: str, role: str, content: str):
    db = SessionLocal()
    try:
        msg = ChatMessage(
            thread_id=thread_id,
            role=role,
            content=content,
            created_at=datetime.utcnow(),
        )
        db.add(msg)
        conversation = (
            db.query(Conversation).filter(Conversation.thread_id == thread_id).first()
        )
        if conversation:
            conversation.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def conversation_belongs_to(thread_id: str, owner_id: str) -> bool:
    db = SessionLocal()
    try:
        conversation = (
            db.query(Conversation)
            .filter(Conversation.thread_id == thread_id)
            .first()
        )
        if not conversation:
            return False
        if conversation.owner_id is None:
            conversation.owner_id = owner_id
            db.commit()
            return True
        return conversation.owner_id == owner_id
    finally:
        db.close()


def get_chat_history(thread_id: str, owner_id: str):
    db = SessionLocal()
    try:
        return (
            db.query(ChatMessage)
            .join(Conversation, Conversation.thread_id == ChatMessage.thread_id)
            .filter(
                ChatMessage.thread_id == thread_id,
                Conversation.owner_id == owner_id,
            )
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
    finally:
        db.close()


def save_memory(thread_id: str, memory: str):
    db = SessionLocal()
    try:
        item = LongTermMemory(
            thread_id=thread_id, memory=memory, created_at=datetime.utcnow()
        )
        db.add(item)
        db.commit()
        return "Memory saved successfully."
    finally:
        db.close()


def search_memory(thread_id: str, query: str):
    db = SessionLocal()
    try:
        memories = (
            db.query(LongTermMemory)
            .filter(LongTermMemory.thread_id == thread_id)
            .order_by(LongTermMemory.created_at.desc())
            .limit(20)
            .all()
        )
        if not memories:
            return "No saved memory found."

        terms = {term.casefold() for term in query.split() if len(term) > 2}
        ranked = sorted(
            memories,
            key=lambda item: sum(
                term in item.memory.casefold() for term in terms
            ),
            reverse=True,
        )
        return "\n".join([f"- {m.memory}" for m in ranked])

    finally:
        db.close()


def save_document(thread_id: str, filename: str, chunks: list[str]):
    db = SessionLocal()
    try:
        document = UploadedDocument(
            thread_id=thread_id,
            filename=filename,
            created_at=datetime.utcnow(),
        )
        db.add(document)
        db.flush()
        db.add_all(
            [
                DocumentChunk(document_id=document.id, content=chunk)
                for chunk in chunks
            ]
        )
        db.commit()
        return {
            "id": document.id,
            "filename": document.filename,
            "created_at": document.created_at,
        }
    finally:
        db.close()


def list_documents(thread_id: str):
    db = SessionLocal()
    try:
        return (
            db.query(UploadedDocument)
            .filter(UploadedDocument.thread_id == thread_id)
            .order_by(UploadedDocument.created_at.desc())
            .all()
        )
    finally:
        db.close()


def delete_document(thread_id: str, document_id: int) -> bool:
    db = SessionLocal()
    try:
        document = (
            db.query(UploadedDocument)
            .filter(
                UploadedDocument.id == document_id,
                UploadedDocument.thread_id == thread_id,
            )
            .first()
        )
        if not document:
            return False
        db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document_id
        ).delete()
        db.delete(document)
        db.commit()
        return True
    finally:
        db.close()


def search_documents(thread_id: str, query: str, limit: int = 5) -> list[dict[str, str]]:
    db = SessionLocal()
    try:
        chunks = (
            db.query(DocumentChunk, UploadedDocument.filename)
            .join(UploadedDocument, DocumentChunk.document_id == UploadedDocument.id)
            .filter(UploadedDocument.thread_id == thread_id)
            .limit(1000)
            .all()
        )
        terms = {term.casefold() for term in query.split() if len(term) > 2}
        ranked = sorted(
            chunks,
            key=lambda item: sum(
                term in item[0].content.casefold() for term in terms
            ),
            reverse=True,
        )
        return [
            {"filename": filename, "content": chunk.content}
            for chunk, filename in ranked[:limit]
            if not terms
            or any(term in chunk.content.casefold() for term in terms)
        ]
    finally:
        db.close()


def cloud_db() -> str:
    """
        Kept for backward compatibility with any code that still imports/calls
        cloud_db() directly. The actual cloud-vs-local decision now happens
        automatically inside agent/schema.py based on whether DATABASE_URL is
        set, so this just returns the resolved URL that's already in use.
    """
    return DATABASE_URL
