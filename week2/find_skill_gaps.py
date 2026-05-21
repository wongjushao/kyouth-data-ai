from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

from prompt_model import prompt_model

MAX_RETRIES = 3
RETRY_DELAY = 1

DEFAULT_MODEL = os.environ.get(
    "SKILL_GAP_MODEL",
    "gemini-2.5-flash-lite",
)

NON_TECH_SKILLS = {
    "leadership",
    "management",
    "communication",
    "teamwork",
    "problem solving",
    "english",
    "mandarin",
}

SKILL_PATTERNS = {
    "python": r"\bpython\b",
    "java": r"\bjava\b",
    "sql": r"\bsql\b",
    "docker": r"\bdocker\b",
    "git": r"\bgit\b",
    "aws": r"\baws\b",
    "azure": r"\bazure\b",
    "cloud": r"\bcloud\b",
    "ci/cd": r"ci/?cd",
    "node.js": r"node\.?\s*js",
    "mongodb": r"\bmongodb\b",
    "nginx": r"\bnginx\b",
    "tensorflow": r"\btensorflow\b",
    "pytorch": r"\bpytorch\b",
    "llm": r"\bllms?\b",
    "rag": r"\brag\b",
    "power bi": r"power\s*bi",
    "github actions": r"github\s+actions",
    "google cloud": r"\b(?:google\s+cloud|gcp)\b",
    "scikit-learn": r"scikit[\s-]?learn",
    "spring boot": r"spring\s+boot",
    "c++": r"\bc\+\+\b",
    "c": r"(?<!\+)\bc\b(?!\+\+)",
}

ALIASES = {
    "nodejs": "node.js",
    "node js": "node.js",
    "gcp": "google cloud",
    "c/c++": "c++",
    "cicd": "ci/cd",
    "powerbi": "power bi",
    "sklearn": "scikit-learn",
}


class SkillGapResult(BaseModel):
    gaps: list[str] = Field(default_factory=list)
    time: float = 0.0
    tokens: int = 0


def normalize_skill(skill: str) -> str:
    skill = skill.strip().lower()
    skill = re.sub(r"\s+", " ", skill)
    return ALIASES.get(skill, skill)

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


def extract_regex_skills(text: str) -> set[str]:
    found = set()

    for skill, pattern in SKILL_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            found.add(skill)

    return found


def build_prompt(resume: str) -> str:
    resume = resume[:5000]

    return f"""
Extract ONLY technical skills from this resume.

Rules:
- Return ONLY valid JSON array
- lowercase only
- no explanation
- ignore soft skills
- ignore certifications
- do not invent skills

Resume:
{resume}
"""


def call_model(prompt: str) -> tuple[str, int]:
    response = prompt_model(DEFAULT_MODEL, prompt)

    if (
        response.startswith("[Error]")
        or response.startswith("[Gemini Error]")
        or response.startswith("[Ollama Error]")
    ):
        raise RuntimeError(response)

    tokens = max(1, (len(prompt) + len(response)) // 4)

    return response, tokens


def extract_json_array(text: str) -> list[str]:
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text)
        text = re.sub(r"```$", "", text)

    match = re.search(r"\[[\s\S]*\]", text)

    if not match:
        raise ValueError("No JSON array found")

    data = json.loads(match.group(0))

    if not isinstance(data, list):
        raise ValueError("Invalid JSON array")

    return [normalize_skill(x) for x in data if isinstance(x, str)]


def extract_llm_skills(resume: str) -> tuple[set[str], int]:
    prompt = build_prompt(resume)

    total_tokens = 0

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response, tokens = call_model(prompt)

            total_tokens += tokens

            skills = set(extract_json_array(response))

            skills = {
                s
                for s in skills
                if s and s not in NON_TECH_SKILLS
            }

            return skills, total_tokens

        except Exception as exc:
            print(f"Attempt {attempt} failed: {exc}")

            if attempt < MAX_RETRIES:
                print(f"Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)

    return set(), total_tokens


def load_required_skills(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)

    try:
        rows = conn.execute(
            """
            SELECT tech_stack, description
            FROM jobs
            """
        ).fetchall()

        skills = set()

        for tech_stack, description in rows:
            combined = f"{tech_stack or ''}\n{description or ''}"

            skills.update(extract_regex_skills(combined))

        return skills

    finally:
        conn.close()


def find_skill_gaps(
    input_file_path: str,
    db_url: str,
) -> SkillGapResult:
    start = time.perf_counter()

    try:
        resume = Path(input_file_path).read_text(
            encoding="utf-8",
            errors="replace",
        )

        regex_skills = extract_regex_skills(resume)

        llm_skills, tokens = extract_llm_skills(resume)

        resume_skills = {
            normalize_skill(s)
            for s in regex_skills | llm_skills
        }

        required_skills = load_required_skills(db_url)

        gaps = sorted(
            skill
            for skill in required_skills
            if normalize_skill(skill) not in resume_skills
        )

        elapsed = time.perf_counter() - start

        return SkillGapResult(
            gaps=gaps,
            time=elapsed,
            tokens=tokens,
        )

    except Exception:
        return SkillGapResult(
            gaps=[],
            time=time.perf_counter() - start,
            tokens=0,
        )


def main() -> None:
    resume_path = "data/resources/resume_d3.txt"
    db_path = "data/resources/jobs_d1.db"
    _load_dotenv()
    if len(sys.argv) > 1:
        resume_path = sys.argv[1]

    if len(sys.argv) > 2:
        db_path = sys.argv[2]

    result = find_skill_gaps(
        resume_path,
        db_path,
    )

    print(
        f"gaps={result.gaps!r} "
        f"time={int(result.time)} "
        f"tokens={result.tokens}"
    )


if __name__ == "__main__":
    main()