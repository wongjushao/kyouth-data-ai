from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.week_2.find_skill_gaps import SkillGapResult, find_skill_gaps
from src.week_2.prompt_model import prompt_model

_backend_dir = Path(__file__).resolve().parents[1]
_week_dir = _backend_dir.parent

load_dotenv(_week_dir / ".env")
load_dotenv(_backend_dir / ".env")

DEFAULT_MODEL = os.getenv("SKILL_GAP_MODEL", "gemini-2.5-flash-lite")

app = FastAPI(title="Week 3 Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    pdf_text: str = ""


class ChatResponse(BaseModel):
    reply: str


def _resolve_jobs_db() -> Path | None:
    env_path = os.getenv("JOBS_DB_PATH", "").strip()
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))

    candidates.extend(
        [
            _backend_dir / "data" / "jobs_d1.db",
            _backend_dir / "data" / "resources" / "jobs_d1.db",
            _week_dir.parent / "week2" / "data" / "jobs_d1.db",
            _week_dir.parent / "week2" / "data" / "resources" / "jobs_d1.db",
        ]
    )

    for path in candidates:
        if path.is_file():
            return path
    return None


def _run_skill_gaps(resume_text: str, db_path: Path) -> SkillGapResult:
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write(resume_text)
        resume_path = handle.name

    try:
        return find_skill_gaps(resume_path, str(db_path))
    finally:
        Path(resume_path).unlink(missing_ok=True)


def _format_skill_gaps(result: SkillGapResult) -> str:
    if not result.gaps:
        return (
            "No skill gaps were found compared to the jobs in the database. "
            f"(analysis took {result.time:.1f}s)"
        )

    lines = [f"- {skill}" for skill in result.gaps]
    return (
        "Skill gaps compared to jobs in the database:\n"
        + "\n".join(lines)
        + f"\n\n(analysis took {result.time:.1f}s, ~{result.tokens} tokens)"
    )


def _build_llm_prompt(message: str, pdf_text: str) -> str:
    if pdf_text.strip():
        return (
            "You are a resume and career assistant.\n"
            f"User message: {message.strip()}\n\n"
            f"Resume text:\n{pdf_text.strip()}"
        )
    return message.strip()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    message = body.message.strip()
    pdf_text = body.pdf_text.strip()

    if not message and not pdf_text:
        return ChatResponse(reply="Please enter a message or attach a PDF.")

    jobs_db = _resolve_jobs_db()

    if pdf_text and jobs_db is not None:
        result = _run_skill_gaps(pdf_text, jobs_db)
        reply = _format_skill_gaps(result)
        if message:
            reply = f"{message}\n\n{reply}"
        return ChatResponse(reply=reply)

    if pdf_text and jobs_db is None:
        return ChatResponse(
            reply=(
                "A resume PDF was provided but the jobs database was not found. "
                "Set JOBS_DB_PATH or mount week2/data (see README)."
            )
        )

    prompt = _build_llm_prompt(message, pdf_text)
    reply = prompt_model(DEFAULT_MODEL, prompt)
    return ChatResponse(reply=reply)
