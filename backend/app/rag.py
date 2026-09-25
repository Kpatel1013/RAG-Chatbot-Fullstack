import io
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path

import pytesseract
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.vectorstores import PGVector
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from PIL import Image
from sqlalchemy import text

from app.config import settings
from app.database import engine

ALLOWED_EXTS = {".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SPLITTER = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)

CHAT_PROMPT = """You are a helpful assistant. Answer the user naturally.
No document is attached to this conversation, so do not invent or recall document contents."""

RAG_PROMPT = """Answer using ONLY the context below. That context is the document attached to this chat.
If they say "this" or "summarize this", they mean that attached document.
If the context is empty, say you don't have a document to use.

Context:
{context}"""


@lru_cache
def _embeddings():
    return HuggingFaceEmbeddings(model_name=settings.embedding_model)


@lru_cache
def _store():
    return PGVector(
        embedding_function=_embeddings(),
        collection_name="document_chunks",
        connection_string=settings.db_url,
        use_jsonb=True,
    )


@lru_cache
def _llm():
    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_api_base,
        temperature=0.2,
    )


def warm_up():
    _embeddings()


def _chunks_for_doc(doc_id: str) -> list[Document]:
    """Load every chunk that belongs to one uploaded file."""
    query = text("""
        SELECT e.document
        FROM langchain_pg_embedding e
        JOIN langchain_pg_collection c ON e.collection_id = c.uuid
        WHERE c.name = 'document_chunks'
          AND e.cmetadata->>'doc_id' = :doc_id
        """)

    with engine.connect() as conn:
        rows = conn.execute(query, {"doc_id": doc_id}).fetchall()

    return [Document(page_content=row[0]) for row in rows if row[0]]


def ask(question: str, doc_id: str | None = None) -> str:
    # No attachment / no saved doc on this chat → plain chat, no vector search.
    # Searching the whole store would leak old uploads into a "new" conversation.
    if not doc_id:
        chain = (
            ChatPromptTemplate.from_messages(
                [("system", CHAT_PROMPT), ("human", "{question}")]
            )
            | _llm()
            | StrOutputParser()
        )
        return chain.invoke({"question": question})

    docs = _chunks_for_doc(doc_id)
    context = "\n\n---\n\n".join(d.page_content for d in docs) or "No documents found."
    chain = (
        ChatPromptTemplate.from_messages(
            [("system", RAG_PROMPT), ("human", "{question}")]
        )
        | _llm()
        | StrOutputParser()
    )
    return chain.invoke({"context": context, "question": question})


def _read_file(filename: str, content: bytes, doc_id: str) -> list[Document]:
    ext = Path(filename).suffix.lower()
    meta = {"source": filename, "doc_id": doc_id}

    # Screenshots / photos → OCR
    if ext in IMAGE_EXTS:
        text_from_image = pytesseract.image_to_string(Image.open(io.BytesIO(content))).strip()
        if not text_from_image:
            return []
        return [Document(page_content=text_from_image, metadata=meta)]

    # PDF / text files → write to a temp file, then load
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        path = tmp.name

    try:
        if ext == ".pdf":
            docs = PyPDFLoader(path).load()
        else:
            docs = TextLoader(path, encoding="utf-8").load()

        for doc in docs:
            doc.metadata.update(meta)
        return docs
    finally:
        Path(path).unlink(missing_ok=True)


def ingest_file(filename: str, content: bytes) -> tuple[int, str]:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(f"Unsupported type: {ext}")

    doc_id = str(uuid.uuid4())
    docs = _read_file(filename, content, doc_id)
    if not docs:
        return 0, doc_id

    chunks = SPLITTER.split_documents(docs)
    for chunk in chunks:
        chunk.metadata.update({"source": filename, "doc_id": doc_id})

    _store().add_documents(chunks)
    return len(chunks), doc_id
