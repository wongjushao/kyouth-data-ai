# Week 3: Microservices Chat Application

## Project Overview

This project builds and containerizes a **full-stack chat application** with three layers:

1. **Frontend** — A FastAPI service that serves a Jinja2 chat page. Users type prompts and optionally attach a PDF resume; the browser extracts text from the PDF and sends JSON to the backend.
2. **Backend** — A FastAPI API with a `POST /chat` endpoint that validates requests and delegates to Week 2 AI modules (`prompt_model`, `find_skill_gaps`).
3. **AI integration** — Week 2 code lives under `backend/src/week_2/` and calls Google Gemini (or Ollama) for general chat, or runs skill-gap analysis when resume text and a jobs database are available.

The goal is to practice **microservices**, **Docker containerization**, and **service orchestration** with Docker Compose, while reusing the LLM workflows from Week 2.

### Project layout

```
week3/
├── frontend/              # Chat UI (FastAPI + Jinja2 + client-side JS)
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── src/
│       ├── main.py
│       └── templates/chat_page.html
├── backend/               # REST API + Week 2 LLM modules
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── src/
│       ├── app.py
│       └── week_2/        # prompt_model, find_skill_gaps, tag_data
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Setup Instructions

### Prerequisites

- **[Docker](https://docs.docker.com/get-started/get-docker/)** and **Docker Compose** (included with Docker Desktop, or install separately on Linux).
- For **local development without Docker** (optional):
  - **Python 3.12+**
  - **[uv](https://docs.astral.sh/uv/) 0.8.x** — install with: `curl -LsSf https://astral.sh/uv/0.8.22/install.sh | sh`
- **Google Gemini API key** — required for default models. Create one at [Google AI Studio](https://aistudio.google.com/).
- **Week 2 jobs database** (optional, for skill-gap analysis) — `week2/data/jobs_d1.db`

### Environment variables

Copy the example file and fill in secrets **locally** (never commit `.env`):

```bash
cd week3
cp .env.example .env
```

Edit `week3/.env`:

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `GOOGLE_API_KEY` | Yes (for Gemini) | API key for Google Gemini. |
| `BACKEND_URL` | No | URL the **browser** uses to call the backend. Default: `http://127.0.0.1:8000`. |
| `OLLAMA_HOST` | No | Ollama base URL. Local: `http://127.0.0.1:11434`. Docker: `http://host.docker.internal:11434`. |
| `JOBS_DB_PATH` | No | Path to `jobs_d1.db`. Docker default: `/app/data/jobs_d1.db` (mounted from `week2/data`). |
| `SKILL_GAP_MODEL` | No | Model for skill-gap analysis (default: `gemini-2.5-flash-lite`). |
| `TAG_MODEL` | No | Model for tagging (default: `gemini-2.5-flash-lite`). |

See `week3/.env.example` for a template with empty values.

### Run with Docker Compose (recommended)

From the `week3/` directory:

```bash
cp .env.example .env          # add GOOGLE_API_KEY and other values
docker compose up --build
```

- **Frontend (chat UI):** http://localhost:3000
- **Backend API:** http://localhost:8000
- **Health check:** http://localhost:8000/health

Stop the stack:

```bash
docker compose down
```

**Jobs database in Docker:** Compose mounts `../week2/data` into the backend container at `/app/data` (read-only). Ensure `week2/data/jobs_d1.db` exists before using PDF skill-gap analysis.

**Ollama from Docker:** The backend reaches the host Ollama API via `host.docker.internal`. Set `OLLAMA_HOST=http://host.docker.internal:11434` in `.env` when running on Linux/WSL.

### Manual setup (without Docker)

**Backend:**

```bash
cd week3/backend
cp ../.env.example ../.env    # add GOOGLE_API_KEY
uv sync
uv run uvicorn src.app:app --reload --port 8000
```

**Frontend** (separate terminal):

```bash
cd week3/frontend
uv sync
uv run uvicorn --app-dir src main:app --reload --port 3000
```

Set `BACKEND_URL=http://127.0.0.1:8000` in `week3/.env` so the chat page knows where to send API requests.

Open http://localhost:3000 for the chat page.

---

## Usage

### Start the application

```bash
cd week3
docker compose up --build
```

Wait until both containers log `Uvicorn running on http://0.0.0.0:8000`.

### Access the frontend

Open **http://localhost:3000** in your browser.

> The frontend container listens on port 8000 internally; Compose maps it to **host port 3000**. The backend is on **host port 8000**.

### Expected inputs

| Input | Description |
| ----- | ----------- |
| **Message** | Text in the textarea (required to submit the form). |
| **PDF (optional)** | A resume PDF; text is extracted in the browser before sending. |

### Expected outputs

| Scenario | Output |
| -------- | ------ |
| General question (no PDF, or PDF without jobs DB) | Assistant reply from `prompt_model` (Gemini/Ollama). |
| PDF + jobs DB available | Skill-gap list compared to jobs in `jobs_d1.db`. |
| Empty message and no PDF text | `"Please enter a message or attach a PDF."` |
| PDF but no jobs DB | Message explaining `JOBS_DB_PATH` / mount is missing. |
| Backend unreachable | Red error bubble in the chat history. |

### Example workflow

1. Open http://localhost:3000
2. Type: `What skills should I highlight for a data role?`
3. Click **Send** — your message appears on the right; the assistant reply appears on the left.
4. (Optional) Attach a PDF resume, then send another message — the UI shows how many characters were extracted from the PDF.

---

## API / Function Reference

### Backend endpoints

#### `GET /health`

Returns service status.

**Response:**

```json
{ "status": "ok" }
```

#### `POST /chat`

Main chat endpoint. Accepts JSON and returns JSON.

**Request body:**

```json
{
  "message": "your question or prompt",
  "pdf_text": "optional plain text extracted from a PDF resume"
}
```

| Field | Type | Required | Description |
| ----- | ---- | -------- | ----------- |
| `message` | string | Yes (schema) | User message. May be empty if `pdf_text` is provided. |
| `pdf_text` | string | No | Resume text extracted on the frontend (default: `""`). |

**Success response (200):**

```json
{ "reply": "assistant response text" }
```

**Validation error (422)** — missing `message` field:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "message"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

**Backend logic (`backend/src/app.py`):**

- If both `message` and `pdf_text` are empty → friendly reply (not 422).
- If `pdf_text` is set and `jobs_d1.db` is found → `find_skill_gaps` (Week 2).
- If `pdf_text` is set but no DB → explanatory reply.
- Otherwise → `prompt_model` (Week 2) with the user message and optional resume context.

### Frontend routes and JavaScript

#### `GET /` (`frontend/src/main.py`)

Renders `chat_page.html` and injects `backend_url` from the `BACKEND_URL` environment variable.

#### Key JavaScript functions (`frontend/src/templates/chat_page.html`)

| Function | Role |
| -------- | ---- |
| `appendMessage(text, role)` | Adds a user, assistant, or error bubble to `#chat-history`. |
| `extractPdfText(file)` | Uses pdf.js to read all pages of a PDF and return plain text. |
| Form `submit` handler | Extracts PDF text (if any), calls `appendMessage` for the user message, `fetch`es `POST ${BACKEND_URL}/chat` with JSON, then renders `data.reply` or an error. |

`BACKEND_URL` is set server-side when the page is rendered:

```javascript
const BACKEND_URL = /* from env, e.g. "http://127.0.0.1:8000" */;
const CHAT_ENDPOINT = `${BACKEND_URL.replace(/\/$/, "")}/chat`;
```

### How frontend and backend interact (Docker)

```
Browser (host)
    │
    ├─ GET http://localhost:3000/     → frontend container (published 3000→8000)
    │
    └─ POST http://localhost:8000/chat → backend container (published 8000→8000)
```

Both services join the **`app-network`** bridge network in `docker-compose.yml`. Chat API calls are made **from the user’s browser** to the backend’s **published host port**, not from the frontend container to `http://backend:8000`. The frontend container only serves HTML/JS; it injects `BACKEND_URL` (default `http://127.0.0.1:8000`) so the browser can reach the API.

Container-to-container communication on `app-network` is available (e.g. `http://backend:8000` from another service) but is not used for the chat `fetch` in this design.

---

## Data / Assumptions

### JSON message format

**Frontend → backend:**

```json
{
  "message": "string",
  "pdf_text": "string"
}
```

**Backend → frontend:**

```json
{
  "reply": "string"
}
```

Field names use **snake_case** (`pdf_text`) to match the Pydantic models in the backend.

### Assumptions

| Topic | Assumption |
| ----- | ---------- |
| **PDF handling** | Only PDFs are accepted (`accept="application/pdf"`). Text extraction runs **in the browser** via pdf.js; the raw PDF file is **not** uploaded to the backend. |
| **PDF content** | Extraction works for text-based PDFs. Scanned/image-only PDFs may yield empty `pdf_text`. |
| **Message length** | No explicit frontend cap; Week 2 `prompt_model` may truncate or limit very long prompts depending on the provider. |
| **Jobs DB** | Skill-gap mode expects `jobs_d1.db` from Week 2 at a known path (see `JOBS_DB_PATH` / Docker volume). |
| **AI models** | Default: `gemini-2.5-flash-lite` via `GOOGLE_API_KEY`. Ollama is supported by Week 2 code if configured. |
| **Authentication** | None — the API is open on localhost for development. |
| **Chat history** | Stored only in the DOM for the current page session; not persisted to a database. |

### Data flow (end to end)

1. User opens the chat page → frontend serves HTML with embedded `BACKEND_URL`.
2. User types a message and optionally selects a PDF.
3. On submit, JavaScript runs `extractPdfText` (if a file is selected) → plain text string.
4. Browser sends `POST /chat` with `{ message, pdf_text }` as JSON.
5. Backend validates the body, resolves the jobs DB path, and chooses:
   - **Skill gaps** — `find_skill_gaps` (Week 2) when `pdf_text` and DB exist.
   - **LLM chat** — `prompt_model` (Week 2) otherwise.
6. Backend returns `{ "reply": "..." }`.
7. Frontend calls `appendMessage` to show the reply in the chat history.

---

## Testing

### Frontend (manual)

| Test | Steps | Expected result |
| ---- | ----- | ---------------- |
| Page loads | Open http://localhost:3000 | Chat UI with title, history area, message box, PDF upload. |
| Send message | Type a message → **Send** | User bubble on the right; assistant reply on the left (if backend + API key work). |
| PDF upload | Attach a text-based PDF → send | Status shows character count; backend may return skill gaps if DB is mounted. |
| Backend down | Stop backend container → send message | Red error bubble mentioning `Could not reach the backend`. |

### Backend (`curl`)

With Compose running and `GOOGLE_API_KEY` set in `.env`:

**Health:**

```bash
curl -s http://localhost:8000/health
# {"status":"ok"}
```

**Chat (LLM):**

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Say hi in one word"}'
# {"reply":"Hello"}
```

**Empty message:**

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":""}'
# {"reply":"Please enter a message or attach a PDF."}
```

**Malformed request (missing `message` field):**

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{}'
# 422 with JSON "detail" array
```

### Docker integration

1. `docker compose up --build` — both images build; containers stay running.
2. `curl http://localhost:3000/` — returns HTML (200).
3. `curl http://localhost:8000/health` — returns `{"status":"ok"}`.
4. Use the browser chat UI — confirms frontend HTML and backend API work together via published ports.

---

## Limitations

| Area | Limitation |
| ---- | ---------- |
| **PDF processing** | Client-side only; large or image-only PDFs may fail or return little text. No server-side PDF parsing. |
| **AI quality** | Replies depend on the chosen model and prompt; no grounding or citation of sources. |
| **Skill gaps** | Requires Week 2 `jobs_d1.db`; analysis is resume vs. aggregated job skills, not per-job reports. |
| **Performance** | Each chat call may invoke an external LLM API (latency and cost). No caching or streaming responses. |
| **Security** | No authentication, rate limiting, or input sanitization beyond basic validation. Not suitable for production as-is. |
| **Chat history** | Lost on page refresh; no database or session store. |
| **CORS** | Backend allows all origins (`*`) for development convenience. |
| **Networking** | Chat uses browser → host port → backend, not an internal frontend proxy to `backend:8000`. |

---

## Architecture Reflection

### Design choices

**Microservices (frontend / backend separation)**  
The UI and API are separate processes with their own `Dockerfile`, dependencies, and ports. This mirrors how teams deploy web apps: the frontend can be scaled or replaced independently of the API, and the backend can serve other clients (mobile, CLI) without changing the HTML service.

**Containerization with Docker**  
Each service runs in an image built from `python:3-bookworm` with `uv sync --frozen` for reproducible installs. Docker Compose wires ports, environment files, volumes (Week 2 data), and a shared **bridge network** (`app-network`) without using the host network driver.

**Week 2 integration in the backend only**  
LLM and database logic stay in `backend/src/week_2/`. The frontend stays thin: templates plus JavaScript for PDF extraction and `fetch`. That keeps secrets (`GOOGLE_API_KEY`) and business logic off the client.

**Browser-side API calls**  
`BACKEND_URL` is injected into the page so the user’s browser posts directly to the backend’s published port (`localhost:8000`). This avoids building a server-side proxy in the frontend container while still keeping the backend URL configurable via environment variables.

### Trade-offs

| Prioritized | Sacrificed |
| ----------- | ---------- |
| Simple deployment with Docker Compose | Kubernetes, separate staging/prod configs, or CI/CD pipelines |
| FastAPI + Jinja + vanilla JS | React/Vue, SSR frameworks, or WebSocket streaming |
| Reuse of Week 2 scripts as modules | A dedicated AI microservice with its own container |
| Developer-friendly open CORS and no auth | Production-grade security and multi-tenant isolation |
| PDF text extraction in the browser | Server-side upload, virus scanning, or OCR for scanned resumes |

### Improvements

With more time, the system could evolve toward:

- **Server-side proxy** — Frontend container forwards `/api/chat` to `http://backend:8000` so the browser only talks to one origin and true container-to-container networking is used.
- **Persistent chat history** — PostgreSQL or Redis for sessions and message storage.
- **Robust PDF pipeline** — Server-side parsing, size limits, and OCR for scanned documents.
- **Structured API errors** — Consistent error codes instead of mixing 422 validation JSON with 200 responses carrying error text in `reply`.
- **Cloud deployment** — Images pushed to a registry, Compose or Terraform on AWS/GCP, secrets via a vault.
- **Automated tests** — pytest for the backend, Playwright for the chat UI, mocked LLM responses in CI.
- **Observability** — Request logging, metrics, and health checks wired to orchestration restarts.

---

## Dependencies

Installed per service with `uv` (`pyproject.toml` + `uv.lock`):

| Service | Key packages |
| ------- | ------------ |
| **Frontend** | `fastapi`, `jinja2`, `uvicorn`, `python-dotenv` |
| **Backend** | `fastapi`, `jinja2`, `uvicorn`, `python-dotenv`, `google-genai`, `httpx`, `mcp`, `pydantic` |

Client-side: **Bootstrap 5**, **pdf.js** (loaded from CDN in `chat_page.html`).
