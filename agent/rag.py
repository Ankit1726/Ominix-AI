import logging, os, docx2txt
from pathlib import Path
from typing import List, Optional

from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("uploads")
CHROMA_DIR = Path("data/chroma_db")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)


GOOGLE_QUOTA_EXHAUSTED = False
_google_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

google_embeddings: Optional[GoogleGenerativeAIEmbeddings] = None
if _google_api_key:
    try:
        google_embeddings = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001"
        )
    except Exception as e:
        logger.warning(
            f"Could not initialize Google embeddings, will use local only: {e}"
        )
        google_embeddings = None
else:
    logger.warning(
        "GOOGLE_API_KEY / GEMINI_API_KEY not set. Using local embeddings only."
    )

local_embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True},
)

google_vectorstore: Optional[Chroma] = None
if google_embeddings is not None:
    google_vectorstore = Chroma(
        collection_name="chatbot_docs_google",
        embedding_function=google_embeddings,
        persist_directory=str(CHROMA_DIR),
    )

local_vectorstore = Chroma(
    collection_name="chatbot_docs_local",
    embedding_function=local_embeddings,
    persist_directory=str(CHROMA_DIR),
)


def _is_quota_error(e: Exception) -> bool:
    msg = str(e).lower()
    keywords = [
        "quota",
        "rate limit",
        "rate_limit",
        "429",
        "resourceexhausted",
        "resource exhausted",
        "exceeded",
        "too many requests",
    ]
    return any(k in msg for k in keywords)


def _mark_google_exhausted(e: Exception):
    global GOOGLE_QUOTA_EXHAUSTED
    if not GOOGLE_QUOTA_EXHAUSTED:
        GOOGLE_QUOTA_EXHAUSTED = True
        logger.warning(
            f"Google embedding quota/rate-limit hit ({e}). "
            "Switching to local embeddings for the rest of this session."
        )


def _google_available() -> bool:
    return google_vectorstore is not None and not GOOGLE_QUOTA_EXHAUSTED


def read_file(file_path: str) -> str:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found on disk: {file_path}")

    suffix = path.suffix.lower()

    try:
        if suffix == ".pdf":
            reader = PdfReader(file_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
                text += "\n"
            return text

        if suffix == ".docx":
            return docx2txt.process(file_path)

        if suffix in [".txt", ".md", ".py", ".csv"]:
            return path.read_text(encoding="utf-8", errors="ignore")

    except Exception as e:
        logger.exception(f"Failed to read {file_path}: {e}")
        raise ValueError(f"Could not extract text from {path.name}: {e}")

    raise ValueError("Unsupported file type. Upload PDF, DOCX, TXT, MD, PY, or CSV.")


def add_document(file_path: str, thread_id: str):
    logger.info(f"Processing upload: {file_path} (thread_id={thread_id})")

    text = read_file(file_path)

    if not text.strip():
        raise ValueError("No text could be extracted from this file.")

    splitter = RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=150)
    chunks = splitter.split_text(text)

    if not chunks:
        raise ValueError("Text was extracted but produced zero chunks.")

    source_name = Path(file_path).name

    docs: List[Document] = [
        Document(
            page_content=chunk,
            metadata={"thread_id": str(thread_id), "source": source_name},
        )
        for chunk in chunks
    ]

    delete_where = {
        "$and": [
            {"thread_id": {"$eq": str(thread_id)}},
            {"source": {"$eq": source_name}},
        ]
    }

    # Clear any previous chunks for this file (in whichever store they were added to)
    for store in [google_vectorstore, local_vectorstore]:
        if store is None:
            continue
        try:
            store.delete(where=delete_where)
        except Exception as e:
            logger.warning(f"Could not clear old chunks for {source_name}: {e}")

    # Try Google first (if available), fall back to local automatically
    if _google_available():
        try:
            google_vectorstore.add_documents(docs)
            logger.info(
                f"Stored {len(docs)} chunks for {source_name} via Google embeddings"
            )
            return {"filename": source_name, "chunks": len(docs), "embedding": "google"}
        except Exception as e:
            if _is_quota_error(e):
                _mark_google_exhausted(e)
            else:
                logger.exception(f"Google embedding failed for {file_path}: {e}")
                # Non-quota error: still fall back to local rather than failing the upload

    try:
        local_vectorstore.add_documents(docs)
    except Exception as e:
        logger.exception(f"Local embedding/insert failed for {file_path}: {e}")
        raise RuntimeError(f"Failed to embed/store document: {e}")

    logger.info(f"Stored {len(docs)} chunks for {source_name} via local embeddings")
    return {"filename": source_name, "chunks": len(docs), "embedding": "local"}


def retrieve_text(query: str, thread_id: str, k: int = 4) -> str:
    all_docs = []

    # Query Google-embedded docs, if Google is still available
    if _google_available():
        try:
            g_docs = google_vectorstore.similarity_search(
                query, k=k, filter={"thread_id": {"$eq": str(thread_id)}}
            )
            all_docs.extend(g_docs)
        except Exception as e:
            if _is_quota_error(e):
                _mark_google_exhausted(e)
            else:
                logger.exception(f"Google retrieval failed: {e}")

    # Always also query the local-embedded docs
    try:
        l_docs = local_vectorstore.similarity_search(
            query, k=k, filter={"thread_id": {"$eq": str(thread_id)}}
        )
        all_docs.extend(l_docs)
    except Exception as e:
        logger.exception(f"Local retrieval failed: {e}")

    if not all_docs:
        logger.info(f"No matches for thread_id={thread_id}, query={query!r}")
        return "No relevant uploaded document content found."

    # Merge results from both stores, cap at k total
    all_docs = all_docs[:k]

    results = []
    for i, doc in enumerate(all_docs, start=1):
        source = doc.metadata.get("source", "uploaded document")
        results.append(f"[Source {i}: {source}]\n{doc.page_content}")

    return "\n\n".join(results)
