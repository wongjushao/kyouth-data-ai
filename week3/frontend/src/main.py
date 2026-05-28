import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

_frontend_dir = Path(__file__).resolve().parents[1]
_week_dir = _frontend_dir.parent

load_dotenv(_week_dir / ".env")
load_dotenv(_frontend_dir / ".env")

app = FastAPI(title="Week 3 Frontend")
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")


@app.get("/", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "chat_page.html",
        {"backend_url": BACKEND_URL},
    )
