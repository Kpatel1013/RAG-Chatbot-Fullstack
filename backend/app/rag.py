import io
import sys
import tempfile
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

from app.config import settings

ALLOWED_EXTS = {".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SPLITTER = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)

SYSTEM = """Answer using the context below. If you don't know, say so.

Context:
{context}"""


@lru_cache
def _embeddings():
    return HuggingFaceEmbeddings(model_name=settings.embedding_model)


@lru_cache
def _vectorstore():
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


def ask(question: str) -> str:
    docs = _vectorstore().similarity_search(question, k=4)
    context = "\n\n---\n\n".join(d.page_content for d in docs) or "No documents found."
    chain = (
        ChatPromptTemplate.from_messages([("system", SYSTEM), ("human", "{question}")])
        | _llm()
        | StrOutputParser()
    )
    return chain.invoke({"context": context, "question": question})


def _read_file(filename: str, content: bytes) -> list[Document]:
    ext = Path(filename).suffix.lower()

    if ext in IMAGE_EXTS:
        text = pytesseract.image_to_string(Image.open(io.BytesIO(content))).strip()
        return [Document(page_content=text, metadata={"source": filename})] if text else []

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        path = tmp.name

    try:
        loader = PyPDFLoader(path) if ext == ".pdf" else TextLoader(path, encoding="utf-8")
        return loader.load()
    finally:
        Path(path).unlink(missing_ok=True)


def ingest_file(filename: str, content: bytes) -> int:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(f"Unsupported type: {ext}")

    docs = _read_file(filename, content)
    if not docs:
        return 0

    chunks = SPLITTER.split_documents(docs)
    _vectorstore().add_documents(chunks)
    return len(chunks)


def ingest_path(path: Path) -> int:
    if path.is_file():
        return ingest_file(path.name, path.read_bytes())

    total = 0
    for file in path.rglob("*"):
        if file.is_file() and file.suffix.lower() in ALLOWED_EXTS:
            total += ingest_file(file.name, file.read_bytes())
    return total


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.rag <file-or-folder>")
        sys.exit(1)
    print(f"Ingested {ingest_path(Path(sys.argv[1]))} chunks.")
