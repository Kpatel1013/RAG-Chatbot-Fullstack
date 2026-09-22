# RAG Chatbot Fullstack

A retrieval-augmented generation (RAG) chatbot you can run locally with Docker or deploy to AWS.

Upload a PDF, text file, or screenshot → ask questions → get answers grounded in that document. Conversations are saved, attachments stay scoped to the active chat, and follow-ups keep using the same file until you attach a new one.

**Live stack (local):** React + TypeScript UI · FastAPI + LangChain backend · PostgreSQL + pgvector · DeepSeek LLM · AWS CDK (ECR / ECS Fargate)

---

## Features

- Chat UI with conversation sidebar (create / switch / delete)
- File upload and **screenshot paste** (PDF, TXT, MD, PNG, JPG, WEBP, GIF)
- OCR for images via Tesseract
- Document-scoped retrieval so “summarize this” uses the current attachment, not older uploads
- Docker Compose one-command local run
- Infrastructure-as-code deploy to AWS with CDK

---

## Architecture

```
Browser
  → Frontend (React / Vite / nginx)     :5173
  → Backend  (FastAPI / LangChain)      :8000
       → Postgres + pgvector            :5432
            • chat history (SQLAlchemy)
            • document chunks + embeddings (PGVector)
       → DeepSeek API (LLM)
```

| Path | Responsibility |
|---|---|
| `frontend/` | Chat UI |
| `backend/` | REST API, OCR, RAG, DeepSeek |
| `infra/` | AWS CDK stack + deploy scripts |
| `docker-compose.yml` | Local full stack |

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- A [DeepSeek API key](https://platform.deepseek.com/)
- (Optional, for AWS) AWS CLI, Node is not required for Compose-only runs

---

## Quick start (local)

```bash
git clone https://github.com/Kpatel1013/RAG-Chatbot-Fullstack.git
cd RAG-Chatbot-Fullstack

cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Edit `backend/.env` and set:

```env
DEEPSEEK_API_KEY=your_key_here
DEEPSEEK_MODEL=deepseek-flash
```

Start everything:

```bash
docker compose up --build
```

Then open:

- App: http://localhost:5173  
- API health: http://localhost:8000/health  
- API docs: http://localhost:8000/docs  

First backend build can take several minutes (embedding model download).

### Try it

1. Paste a screenshot or upload a PDF / `.txt`
2. Ask something about that file (e.g. “summarize this”)
3. Ask a follow-up without re-attaching — it keeps using the same document
4. Attach a new file to switch context, or delete chats from the sidebar

Stop the stack with `Ctrl+C` or:

```bash
docker compose stop
```

---

## Environment variables

### Backend (`backend/.env`)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres URL (Compose overrides this to use the `db` service) |
| `DEEPSEEK_API_KEY` | Required for chat |
| `DEEPSEEK_API_BASE` | Default `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | e.g. `deepseek-flash` |
| `EMBEDDING_MODEL` | Default `sentence-transformers/all-MiniLM-L6-v2` |
| `CORS_ORIGINS` | Comma-separated allowed origins |

`backend/.env` is gitignored. Commit only `backend/.env.example`.

### Frontend (`frontend/.env`)

| Variable | Purpose |
|---|---|
| `VITE_API_URL` | Backend base URL (default `http://localhost:8000`) |

In Docker, `VITE_API_URL` is also passed as a build arg in Compose.

---

## API overview

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `POST` | `/api/upload` | Ingest a file; returns `doc_id` |
| `POST` | `/api/chat` | Send a message (optional `conversation_id`, `doc_id`) |
| `GET` | `/api/conversations` | List chats |
| `GET` | `/api/conversations/{id}/messages` | Load messages |
| `DELETE` | `/api/conversations/{id}` | Delete a chat |

Interactive docs: http://localhost:8000/docs

---

## Deploy to AWS

Infrastructure lives under `infra/` (VPC, ALB, RDS Postgres, ECR, ECS Fargate).

```bash
cd infra
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export DEEPSEEK_API_KEY='your_key_here'
./scripts/deploy.sh          # CDK bootstrap + deploy stack
./scripts/deploy-images.sh   # Build/push images, restart ECS
```

Requires configured AWS credentials, Docker, and the AWS CLI. The second script prints the public app URL.

**Note:** This stack incurs AWS charges (RDS, Fargate, ALB, NAT-less public subnets still bill for compute/storage). Destroy the stack when you are done testing.

---

## Project structure

```
.
├── backend/           # FastAPI app, RAG pipeline, Dockerfile
├── frontend/          # React + TypeScript UI, nginx Dockerfile
├── infra/             # AWS CDK app + deploy scripts
├── docker-compose.yml # Local db + backend + frontend
└── README.md
```

---

## Tech stack

- **Frontend:** React 19, TypeScript, Vite, nginx  
- **Backend:** FastAPI, SQLAlchemy, LangChain, HuggingFace embeddings, Tesseract OCR  
- **Data:** PostgreSQL 16 + pgvector  
- **LLM:** DeepSeek (OpenAI-compatible API)  
- **Ops:** Docker Compose, AWS CDK, ECR, ECS Fargate  


---

## License

Personal / portfolio project.
