import logging, os, docx2txt

from pathlib import Path
from typing import List

from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
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

# Fail fast if the API key isn't set, instead of silently failing later
if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
    logger.warning(
        "GOOGLE_API_KEY / GEMINI_API_KEY not found in environment. "
        "Embedding calls will fail. Check your .env file is in the same "
        "directory you're running the script from, and that load_dotenv() "
        "actually found it."
    )

## Embeddings model
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")

vectorstore = Chroma(
    collection_name="chatbot_docs",
    embedding_function=embeddings,
    persist_directory=str(CHROMA_DIR),
)


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
        # Without this, a corrupt/locked file just crashes with no context
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

    docs: List[Document] = [
        Document(
            page_content=chunk,
            # thread_id cast to str: Chroma metadata filters are strict about type,
            # an int thread_id here silently mismatches a str thread_id at query time
            metadata={"thread_id": str(thread_id), "source": Path(file_path).name},
        )
        for chunk in chunks
    ]

    try:
        vectorstore.add_documents(docs)
    except Exception as e:
        # This is almost always where things actually die: bad/missing API key,
        # rate limit, or network issue on the embedding call
        logger.exception(f"Embedding/insert failed for {file_path}: {e}")
        raise RuntimeError(f"Failed to embed/store document: {e}")

    logger.info(f"Stored {len(docs)} chunks for {Path(file_path).name}")
    return {"filename": Path(file_path).name, "chunks": len(docs)}


def retrieve_text(query: str, thread_id: str, k: int = 4) -> str:
    try:
        docs = vectorstore.similarity_search(
            query, k=k, filter={"thread_id": str(thread_id)}
        )
    except Exception as e:
        logger.exception(f"Retrieval failed: {e}")
        return f"Retrieval error: {e}"

    if not docs:
        logger.info(f"No matches for thread_id={thread_id}, query={query!r}")
        return "No relevant uploaded document content found."

    results = []
    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get("source", "uploaded document")
        results.append(f"[Source {i}: {source}]\n{doc.page_content}")

    return "\n\n".join(results)
