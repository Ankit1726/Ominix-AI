import os
import hashlib
import docx2txt

from pathlib import Path
from typing import List, Optional
from pypdf import PdfReader

from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from dotenv import load_dotenv
load_dotenv()

# Configuration
UPLOAD_DIR = Path("uploads")
DB_DIR = Path("chroma_db")
MAX_FILE_SIZE_MB = 100
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".py", ".csv"}

UPLOAD_DIR.mkdir(exist_ok=True)
DB_DIR.mkdir(exist_ok=True)


# Embeddings (lazy init to avoid import-time crash)
_embeddings: Optional[GoogleGenerativeAIEmbeddings] = None
_vectorstore: Optional[Chroma] = None


def _get_embeddings() -> GoogleGenerativeAIEmbeddings:
    global _embeddings
    if _embeddings is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY environment variable is not set. "
                "Please set it to use document search."
            )
        _embeddings = GoogleGenerativeAIEmbeddings(
            model="gemini-embedding-001",
            google_api_key=api_key,
        )
    return _embeddings


def _get_vectorstore() -> Chroma:
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = Chroma(
            collection_name="omnix_docs",
            embedding_function=_get_embeddings(),
            persist_directory=str(DB_DIR),
        )
    return _vectorstore


# File Reading (with path traversal protection)
def _resolve_upload_path(file_path: str) -> Path:
    """
    Resolve a file path safely within the uploads directory.
    Raises ValueError if the path escapes the uploads folder.
    """
    raw = Path(file_path)

    # If already absolute, verify it's inside UPLOAD_DIR
    if raw.is_absolute():
        resolved = raw.resolve()
        upload_resolved = UPLOAD_DIR.resolve()
        try:
            resolved.relative_to(upload_resolved)
        except ValueError:
            raise ValueError(
                f"Path traversal detected: {file_path} is outside uploads directory"
            )
        return resolved

    # Relative path — join with UPLOAD_DIR
    resolved = (UPLOAD_DIR / raw).resolve()
    upload_resolved = UPLOAD_DIR.resolve()
    try:
        resolved.relative_to(upload_resolved)
    except ValueError:
        raise ValueError(
            f"Path traversal detected: {file_path} is outside uploads directory"
        )
    return resolved


def _check_file(path: Path) -> None:
    """Validate file exists, is a file, is allowed type, and is within size limits."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {path.suffix}. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise ValueError(
            f"File too large: {size_mb:.1f} MB (max {MAX_FILE_SIZE_MB} MB)"
        )


def read_file_text(file_path: str) -> str:
    """
    Extract text from a supported file.

    Args:
        file_path: Path relative to uploads/ or absolute path inside uploads/.

    Returns:
        Extracted text as a single string.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If file type is unsupported or path is outside uploads.
    """
    safe_path = _resolve_upload_path(file_path)
    _check_file(safe_path)

    suffix = safe_path.suffix.lower()

    if suffix == ".pdf":
        reader = PdfReader(str(safe_path))
        text_parts = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        text = "\n".join(text_parts)
        if not text.strip():
            raise ValueError(
                "No text extracted from PDF. "
                "The file may be scanned/image-based. Try an OCR tool first."
            )
        return text

    elif suffix == ".docx":
        text = docx2txt.process(str(safe_path))
        if not text.strip():
            raise ValueError("No text extracted from DOCX file.")
        return text

    elif suffix in (".txt", ".md", ".py", ".csv"):
        text = safe_path.read_text(encoding="utf-8", errors="ignore")
        if not text.strip():
            raise ValueError("File is empty.")
        return text

    # Should never reach here due to _check_file
    raise ValueError(f"Unsupported file type: {suffix}")


# Chunking & Embedding
def _generate_chunk_id(thread_id: str, chunk_text: str) -> str:
    """
    Generate a deterministic ID for a chunk based on its actual content
    (scoped per thread) so identical content is deduplicated correctly
    even if it arrives via a different file path or a shifted chunk index.

    NOTE: previously this hashed (thread_id, file_path, chunk_index) —
    a position-based key that could silently skip re-ingesting changed
    content (if index/path happened to match) or fail to dedupe identical
    content arriving under a different path. Content-based hashing fixes
    both.
    """
    content = f"{thread_id}:{chunk_text}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def add_document_to_rag(file_path: str, thread_id: str) -> dict:
    """
    Ingest a file, chunk it, embed it, and store in ChromaDB.

    Args:
        file_path: Path to the file (relative to uploads/ or absolute inside uploads/).
        thread_id: Conversation thread ID for scoping retrieval.

    Returns:
        Dict with filename, chunks count, and whether new chunks were added.

    Raises:
        ValueError: If no text is extracted or file is unsupported.
    """
    if not thread_id or not thread_id.strip():
        raise ValueError("thread_id cannot be empty")

    text = read_file_text(file_path)

    if not text.strip():
        raise ValueError("No text extracted from file.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100,
    )
    chunks = splitter.split_text(text)

    if not chunks:
        raise ValueError("Text was extracted but could not be chunked.")

    filename = Path(file_path).name

    docs: List[Document] = []
    ids: List[str] = []

    for i, chunk in enumerate(chunks):
        chunk_id = _generate_chunk_id(thread_id, chunk)
        docs.append(
            Document(
                page_content=chunk,
                metadata={
                    "thread_id": thread_id,
                    "source": filename,
                    "chunk_index": i,
                },
            )
        )
        ids.append(chunk_id)

    vectorstore = _get_vectorstore()

    # Check which IDs already exist to avoid duplicates
    existing = vectorstore.get(ids=ids)
    existing_ids = set(existing.get("ids", []))
    new_docs = [d for d, cid in zip(docs, ids) if cid not in existing_ids]
    new_ids = [cid for cid in ids if cid not in existing_ids]

    if new_docs:
        vectorstore.add_documents(documents=new_docs, ids=new_ids)

    return {
        "filename": filename,
        "chunks": len(docs),
        "new_chunks": len(new_docs),
        "skipped_duplicates": len(docs) - len(new_docs),
    }


# Retrieval
def retrieve_from_rag(
    query: str,
    thread_id: str,
    k: int = 5,
) -> str:
    """
    Search uploaded documents using semantic similarity.

    Args:
        query: Search query string.
        thread_id: Scope search to this conversation thread.
        k: Number of results to return.

    Returns:
        Formatted string of matching document chunks, or a message if none found.
    """
    if not query or not query.strip():
        return "Error: Query cannot be empty"
    if not thread_id or not thread_id.strip():
        return "Error: thread_id cannot be empty"
    if k < 1:
        return "Error: k must be at least 1"

    vectorstore = _get_vectorstore()

    docs = vectorstore.similarity_search(
        query=query,
        k=k,
        filter={"thread_id": {"$eq": thread_id}},
    )

    if not docs:
        return "No relevant content found in uploaded documents for this thread."

    results = []
    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source", "Uploaded Document")
        results.append(
            f"Document {i}\n"
            f"Source: {source}\n"
            f"Content:\n{doc.page_content.strip()}"
        )

    return "\n\n".join(results)
