from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

OLLAMA_BASE_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"

GEMINI_MODELS = frozenset(
    {
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-3-flash-preview",
    }
)

OLLAMA_MODELS = frozenset(
    {
        "llama3.1",
        "phi3",
        "deepseek-r1:1.5b",
    }
)


def _load_dotenv() -> None:
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.is_file():
        return
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


def _is_gemini_model(model: str) -> bool:
    return model in GEMINI_MODELS or model.startswith("gemini-")


def _prompt_ollama(model: str, prompt: str) -> str:
    payload = {"model": model, "prompt": prompt, "stream": False}
    try:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(OLLAMA_GENERATE_URL, json=payload)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
    except httpx.ConnectError:
        return (
            "[Ollama Error] Cannot connect to Ollama at "
            f"{OLLAMA_BASE_URL}. Ensure Ollama is running (curl 127.0.0.1:11434)."
        )
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip() or str(exc)
        return f"[Ollama Error] {exc.response.status_code} {detail}"
    except httpx.TimeoutException:
        return "[Ollama Error] Request timed out. The model may still be loading; try again."
    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
        return f"[Ollama Error] {exc}"

    text = data.get("response")
    if isinstance(text, str) and text.strip():
        return text

    if data.get("error"):
        return f"[Ollama Error] {data['error']}"
    return "[Ollama Error] Empty response from Ollama."


def _prompt_gemini(model: str, prompt: str) -> str:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return (
            "[Gemini Error] Missing API key. Set GOOGLE_API_KEY"
            "in your environment or week2/.env"
        )

    try:
        from google import genai
    except ImportError:
        return "[Gemini Error] google-genai package is not installed. Run: uv sync"

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=prompt)
    except Exception as exc:
        if exc.__class__.__module__.startswith("google.genai"):
            return f"[Gemini Error] {exc}"
        return f"[Gemini Error] {exc}"

    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text

    try:
        candidates = response.candidates or []
        if candidates:
            parts = candidates[0].content.parts or []
            chunks = [p.text for p in parts if getattr(p, "text", None)]
            joined = "".join(chunks).strip()
            if joined:
                return joined
    except (AttributeError, IndexError, TypeError):
        pass

    return "[Gemini Error] Empty response from Gemini."


def prompt_model(model: str, prompt: str) -> str:
    """Send *prompt* to *model* and return the model's text response."""
    model = model.strip()
    prompt = prompt.strip()
    if not model:
        return "[Error] Model name is required."
    if not prompt:
        return "[Error] Prompt is required."

    try:
        if _is_gemini_model(model):
            return _prompt_gemini(model, prompt)
        return _prompt_ollama(model, prompt)
    except Exception as exc:
        prefix = "[Gemini Error]" if _is_gemini_model(model) else "[Ollama Error]"
        return f"{prefix} {exc}"


def main() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage: uv run prompt_model.py <model> <prompt>\n"
            "  Gemini: gemini-2.5-flash, gemini-2.5-flash-lite, gemini-3-flash-preview\n"
            "  Ollama: llama3.1, phi3, deepseek-r1:1.5b",
            file=sys.stderr,
        )
        sys.exit(1)

    _load_dotenv()
    model = sys.argv[1]
    user_prompt = " ".join(sys.argv[2:])
    result = prompt_model(model, user_prompt)
    print("\n--- RESPONSE ---\n")
    print(result)


if __name__ == "__main__":
    main()
