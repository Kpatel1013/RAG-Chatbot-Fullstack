from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Conversation, Message, get_db, get_default_user, init_db
from app.rag import ALLOWED_EXTS, ask, ingest_file, warm_up

# --- request/response schemas ---


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str


class ConversationOut(BaseModel):
    id: str
    title: str
    updatedAt: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    createdAt: str


class UploadResponse(BaseModel):
    filename: str
    chunks: int
    message: str


# --- app setup ---


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    warm_up()
    yield


app = FastAPI(title="RAG Chatbot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# --- routes ---


@app.post("/api/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "No filename")

    ext = "." + file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"Allowed types: {', '.join(sorted(ALLOWED_EXTS))}")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")

    try:
        chunks = ingest_file(file.filename, content)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if chunks == 0:
        raise HTTPException(400, "No text found in file")

    return UploadResponse(
        filename=file.filename,
        chunks=chunks,
        message=f"Added {chunks} chunks from {file.filename}. You can ask about it now.",
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    if not body.message.strip():
        raise HTTPException(400, "Message cannot be empty")
    if not settings.deepseek_api_key:
        raise HTTPException(503, "DEEPSEEK_API_KEY is not configured")

    user = get_default_user(db)
    text = body.message.strip()

    conv = None
    if body.conversation_id:
        conv = db.query(Conversation).filter_by(id=body.conversation_id, user_id=user.id).first()
        if not conv:
            raise HTTPException(404, "Conversation not found")

    if not conv:
        conv = Conversation(user_id=user.id, title=text[:40])
        db.add(conv)
        db.flush()

    db.add(Message(conversation_id=conv.id, role="user", content=text))
    reply = ask(text)
    db.add(Message(conversation_id=conv.id, role="assistant", content=reply))
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()

    return ChatResponse(reply=reply, conversation_id=conv.id)


@app.get("/api/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    user = get_default_user(db)
    rows = db.query(Conversation).filter_by(user_id=user.id).order_by(Conversation.updated_at.desc()).all()
    return [ConversationOut(id=c.id, title=c.title, updatedAt=c.updated_at.isoformat()) for c in rows]


@app.get("/api/conversations/{conv_id}/messages", response_model=list[MessageOut])
def list_messages(conv_id: str, db: Session = Depends(get_db)):
    user = get_default_user(db)
    if not db.query(Conversation).filter_by(id=conv_id, user_id=user.id).first():
        raise HTTPException(404, "Conversation not found")
    rows = db.query(Message).filter_by(conversation_id=conv_id).order_by(Message.created_at).all()
    return [MessageOut(id=m.id, role=m.role, content=m.content, createdAt=m.created_at.isoformat()) for m in rows]
