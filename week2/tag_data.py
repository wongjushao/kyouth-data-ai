from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from prompt_model import prompt_model
from rate_limits import compute_batch_size

MAX_RETRIES = 3
RETRY_BASE_SECONDS = 2.0
MAX_DESCRIPTION_CHARS = 2500
DEFAULT_MODEL = os.environ.get("TAG_MODEL", "gemini-2.5-flash-lite")


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


def _resolve_db_path(db_url: str) -> Path:
    path = Path(db_url).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    return path


def _id_column(conn: sqlite3.Connection) -> str:
    cur = conn.execute("PRAGMA table_info(jobs)")
    columns = {row[1] for row in cur.fetchall()}
    if "source_id" in columns:
        return "source_id"
    if "id" in columns:
        return "id"
    raise ValueError("jobs table must have source_id or id column")


def _fetch_untagged(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    id_col = _id_column(conn)
    cur = conn.execute(
        f"""
        SELECT {id_col}, job_title, description
        FROM jobs
        WHERE tech_stack IS NULL OR TRIM(COALESCE(tech_stack, '')) = ''
        ORDER BY {id_col}
        """
    )
    rows: list[tuple[str, str, str]] = []
    for job_id, title, description in cur.fetchall():
        rows.append(
            (
                str(job_id),
                str(title or "").strip(),
                str(description or "").strip(),
            )
        )
    return rows


def _truncate(text: str, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _build_batch_prompt(batch: list[tuple[str, str, str]]) -> str:
    blocks: list[str] = []
    for idx, (job_id, title, desc) in enumerate(batch, start=1):
        blocks.append(
            f"Job {idx}\n"
            f"source_id: {job_id}\n"
            f"job_title: {title}\n"
            f"description:\n{_truncate(desc)}"
        )
    jobs_text = "\n\n".join(blocks)
    n = len(batch)
    return (
        f"Extract the technical stack for each of the {n} job postings below.\n"
        "Return ONLY a JSON array with exactly "
        f"{n} objects, in the same order as the jobs.\n"
        'Each object must be: {"source_id": "<id>", "tech_stack": "<comma-separated skills>"}\n'
        "Include programming languages, frameworks, databases, cloud platforms, and key tools "
        "mentioned or strongly implied. No markdown, no explanation.\n\n"
        f"{jobs_text}"
    )


def _extract_json_array(text: str) -> list[Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", cleaned)
        if not match:
            raise ValueError("Response does not contain valid JSON array") from None
        parsed = json.loads(match.group(0))

    if isinstance(parsed, dict):
        for key in ("jobs", "results", "data"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break

    if not isinstance(parsed, list):
        raise ValueError("Response is not a JSON array")
    return parsed


def _normalize_batch_results(
    batch: list[tuple[str, str, str]], raw: str
) -> list[tuple[str, str]]:
    expected = len(batch)
    items = _extract_json_array(raw)
    if len(items) != expected:
        raise ValueError("Mismatch between batch size and response")

    results: list[tuple[str, str]] = []
    for idx, (job_id, _title, _desc) in enumerate(batch):
        item = items[idx] if idx < len(items) else {}
        if not isinstance(item, dict):
            raise ValueError("Mismatch between batch size and response")

        sid = str(item.get("source_id") or item.get("id") or job_id).strip()
        stack = item.get("tech_stack") or item.get("tech") or item.get("skills") or ""
        if isinstance(stack, list):
            stack = ", ".join(str(s).strip() for s in stack if str(s).strip())
        stack = str(stack).strip()
        if not stack:
            stack = "General software development"
        results.append((sid or job_id, stack))

    return results


def _call_model(model: str, prompt: str) -> tuple[str, int]:
    """Return model text and estimated token count for this call."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key and model.startswith("gemini"):
        try:
            from google import genai

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model=model, contents=prompt)
            text = getattr(response, "text", None) or ""
            if not text.strip():
                try:
                    parts = response.candidates[0].content.parts
                    text = "".join(p.text for p in parts if getattr(p, "text", None))
                except (AttributeError, IndexError, TypeError):
                    text = ""

            tokens = 0
            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                tokens = int(getattr(usage, "total_token_count", 0) or 0)
            if tokens <= 0:
                tokens = max(1, (len(prompt) + len(text)) // 4)
            return text.strip(), tokens
        except Exception:
            pass

    text = prompt_model(model, prompt)
    if text.startswith("[Gemini Error]") or text.startswith("[Ollama Error]") or text.startswith(
        "[Error]"
    ):
        raise RuntimeError(text)
    return text, max(1, (len(prompt) + len(text)) // 4)


def _process_batch(
    batch: list[tuple[str, str, str]],
    batch_index: int,
    model: str,
    tokens_used: list[int],
) -> list[tuple[str, str]]:
    prompt = _build_batch_prompt(batch)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw, tokens = _call_model(model, prompt)
            tokens_used[0] += tokens
            return _normalize_batch_results(batch, raw)
        except (ValueError, json.JSONDecodeError, RuntimeError) as exc:
            print(f"[Batch {batch_index}] Attempt {attempt} failed: {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_SECONDS * (2 ** (attempt - 1)))

    combined: list[tuple[str, str]] = []
    for job_id, title, desc in batch:
        try:
            raw, tokens = _call_model(model, _build_batch_prompt([(job_id, title, desc)]))
            tokens_used[0] += tokens
            combined.extend(_normalize_batch_results([(job_id, title, desc)], raw))
        except (ValueError, json.JSONDecodeError, RuntimeError) as exc:
            print(f"[Job {job_id}] Skipped after error: {exc}")
            combined.append((job_id, "General software development"))
    return combined


def _update_tech_stack(
    conn: sqlite3.Connection, job_id: str, tech_stack: str, id_col: str
) -> None:
    conn.execute(
        f"UPDATE jobs SET tech_stack = ? WHERE {id_col} = ?",
        (tech_stack, job_id),
    )


def tag_data(db_url: str) -> None:
    """Populate empty tech_stack values from job descriptions using batched LLM calls."""
    _load_dotenv()
    start = time.perf_counter()
    total_tokens = 0

    try:
        db_path = _resolve_db_path(db_url)
    except (OSError, ValueError) as exc:
        print(f"Database error: {exc}")
        elapsed_ms = (time.perf_counter() - start) * 1000
        print(f"Total tokens used: 0, took {elapsed_ms:.3f}ms")
        return

    model = DEFAULT_MODEL
    batch_size = compute_batch_size(model)
    tokens_holder = [0]

    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error as exc:
        print(f"Database error: {exc}")
        elapsed_ms = (time.perf_counter() - start) * 1000
        print(f"Total tokens used: 0, took {elapsed_ms:.3f}ms")
        return

    try:
        try:
            id_col = _id_column(conn)
            rows = _fetch_untagged(conn)
        except (sqlite3.Error, ValueError) as exc:
            print(f"Database error: {exc}")
            elapsed_ms = (time.perf_counter() - start) * 1000
            print(f"Total tokens used: 0, took {elapsed_ms:.3f}ms")
            return

        if not rows:
            print("No data to tag")
            elapsed_ms = (time.perf_counter() - start) * 1000
            print(f"Total tokens used: 0, took {elapsed_ms:.3f}ms")
            return

        batch_index = 0
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset : offset + batch_size]
            results = _process_batch(batch, batch_index, model, tokens_holder)
            batch_index += 1

            try:
                for job_id, tech_stack in results:
                    _update_tech_stack(conn, job_id, tech_stack, id_col)
                    print(f"Analyzed Job {job_id}: {tech_stack}")
                conn.commit()
            except sqlite3.Error as exc:
                print(f"Database error: {exc}")
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass

        total_tokens = tokens_holder[0]
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    elapsed_ms = (time.perf_counter() - start) * 1000
    print(f"Total tokens used: {total_tokens}, took {elapsed_ms:.3f}ms")


def main() -> None:
    _load_dotenv()
    default_paths = [
        Path(__file__).resolve().parent / "data" / "resources" / "jobs_d1.db",
    ]
    if len(sys.argv) > 1:
        db_url = sys.argv[1]
    else:
        db_url = next((str(p) for p in default_paths if p.is_file()), str(default_paths[0]))

    try:
        tag_data(db_url)
    except Exception as exc:
        print(f"Unexpected error: {exc}")
        print("Total tokens used: 0, took 0.000ms")


if __name__ == "__main__":
    main()
