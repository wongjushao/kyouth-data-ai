# Week 3: Microservices Chat Application

Week 3 splits the application into a **frontend** (Jinja chat UI) and **backend** (FastAPI API), orchestrated with Docker Compose. Week 2 LLM modules live under `backend/src/week_2/`.

## Project layout

```
week3/
├── frontend/          # Chat UI (FastAPI + Jinja)
├── backend/           # API + week_2 LLM code
├── docker-compose.yml
├── .env.example
└── README.md
```

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 0.8.x
- [Docker](https://docs.docker.com/get-started/get-docker/)

## Local development (without Docker)

### Backend

```bash
cd week3/backend
cp ../.env.example ../.env   # add GOOGLE_API_KEY
uv sync
uv run uvicorn src.app:app --reload --port 8000
```

### Frontend

```bash
cd week3/frontend
uv sync
uv run uvicorn --app-dir src main:app --reload --port 3000
```

Open http://localhost:3000 for the chat page (or http://localhost:8000 if you run the frontend on port 8000).

Copy `week3/.env.example` to `week3/.env` and set `BACKEND_URL` (defaults to `http://127.0.0.1:8000`).

## Docker (Day 4 orchestration)

Each service has its own `Dockerfile` (Python `3-bookworm` base, app code under `/app`). `docker-compose.yml` builds both images and attaches them to a shared bridge network (`app-network`) so the frontend reaches the backend at `http://backend:8000`.

From `week3/`:

```bash
cp .env.example .env   # add GOOGLE_API_KEY and other secrets
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- Backend health: http://localhost:8000/health

Stop with `docker compose down`.

### Ollama from Docker

The backend container reaches the host Ollama API via `host.docker.internal` (see `docker-compose.yml` and [this Stack Overflow answer](https://stackoverflow.com/questions/24319662/from-inside-of-a-docker-container-how-do-i-connect-to-the-localhost-of-the-mach)). Set `OLLAMA_HOST=http://host.docker.internal:11434` in `.env` when using Docker on Linux/WSL.

### Jobs database

Skill-gap analysis needs `week2/data/jobs_d1.db`. Docker Compose mounts `../week2/data` into the backend at `/app/data`. Locally, place the DB under `week2/data/` or set `JOBS_DB_PATH`.

## API

`POST /chat` — JSON body:

```json
{ "message": "your question", "pdf_text": "optional resume text from PDF" }
```

Response: `{ "reply": "..." }`. With `pdf_text` and a jobs DB, the backend runs `find_skill_gaps`; otherwise it uses `prompt_model`.

## Dependencies

Installed with `uv add` in each service:

- **Shared:** `fastapi`, `jinja2`, `uvicorn`, `python-dotenv`
- **Backend (week 2):** `google-genai`, `httpx`, `mcp`, `pydantic`
