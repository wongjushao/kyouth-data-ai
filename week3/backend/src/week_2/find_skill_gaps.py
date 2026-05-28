from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

from .prompt_model import prompt_model
from .rate_limits import compute_batch_size, get_model_limits

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
    "cooking",
}

SKILL_PATTERNS = {
    "python": r"\bpython\b",
    "java": r"\bjava\b",
    "sql": r"\bsql\b",
    "r": r"\b(?:\br\b|\br\s+programming)\b",
    "pandas": r"\bpandas\b",
    "numpy": r"\bnumpy\b",
    "docker": r"\bdocker\b",
    "kubernetes": r"\b(?:kubernetes|k8s)\b",
    "git": r"\bgit\b",
    "aws": r"\baws\b",
    "azure": r"\bazure\b",
    "cloud": r"\bcloud\b",
    "ci/cd": r"ci/?cd",
    "node.js": r"node\.?\s*js",
    "mongodb": r"\bmongodb\b",
    "mysql": r"\bmysql\b",
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
    "spring framework": r"spring\s+framework",
    "tableau": r"\btableau\b",
    "a/b testing": r"a/?b\s+testing",
    "alibaba cloud": r"alibaba\s+cloud",
    "api integration": r"api\s+integration",
    "code reviews": r"code\s+reviews?",
    "data processing": r"data\s+processing",
    "datastudio": r"data\s*studio",
    "excel": r"\bexcel\b",
    "feature engineering": r"feature\s+engineering",
    "grafana": r"\bgrafana\b",
    "labeling": r"\blabel(?:l)?ing\b",
    "linux development environments": r"linux(?:\s+development(?:\s+environments?)?)?",
    "php": r"\bphp\b",
    "prometheus": r"\bprometheus\b",
    "restful api design": r"rest(?:ful)?\s+apis?",
    "testing": r"(?<!a/b\s)(?<!ab\s)\b(?:unit\s+)?testing\b",
    "web automation": r"web\s+automation",
    "c++": r"\bc\+\+\b",
    "c": r"(?<!\+)\bc\b(?!\+\+)",
    "powershell": r"powershell",
    "postgresql": r"postgresql",
}

ALIASES = {
    "nodejs": "node.js",
    "node js": "node.js",
    "gcp": "google cloud",
    "google cloud platform": "google cloud",
    "c/c++": "c++",
    "cicd": "ci/cd",
    "ci cd": "ci/cd",
    "powerbi": "power bi",
    "power bi": "power bi",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "ab testing": "a/b testing",
    "a b testing": "a/b testing",
    "rest apis": "restful api design",
    "rest api": "restful api design",
    "restful api": "restful api design",
    "restful apis": "restful api design",
    "microservices": "microservices",
    "k8s": "kubernetes",
    "data studio": "datastudio",
    "linux": "linux development environments",
    "linux development": "linux development environments",
    "llms": "llm",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "etl": "etl",
    "deep learning": "deep learning",
}


class SkillGapResult(BaseModel):
    gaps: list[str] = Field(default_factory=list)
    time: float = 0.0
    tokens: int = 0


def normalize_skill(skill: str) -> str:
    skill = skill.strip().lower()
    skill = re.sub(r"\s+", " ", skill)
    skill = skill.strip(".,;")
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


def _clean_skill_token(raw: str) -> str:
    token = re.sub(
        r"^(?:technical\s+)?skills?\s*:\s*",
        "",
        raw.strip(),
        flags=re.IGNORECASE,
    )
    return normalize_skill(token)


def parse_delimited_skills(text: str) -> set[str]:
    skills: set[str] = set()
    for part in re.split(r"[,;|]|(?:\s+and\s+)", text):
        token = _clean_skill_token(part)
        if not token or token in NON_TECH_SKILLS:
            continue
        if token in {"ci", "cd", "b testing"}:
            continue
        if len(token) == 1 and token not in {"c", "r"}:
            continue
        skills.add(token)
    return skills


def extract_skills_section(text: str) -> set[str]:
    skills: set[str] = set()
    in_skills = False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if in_skills:
                continue
            continue

        if re.match(r"(?i)^skills\b", stripped):
            in_skills = True
            if ":" in stripped:
                skills |= parse_delimited_skills(stripped.split(":", 1)[1])
            continue

        if in_skills and re.match(
            r"(?i)^(education|experience|certifications|summary|projects|work)\b",
            stripped,
        ):
            break

        if in_skills:
            skills |= parse_delimited_skills(stripped)

    return skills


def extract_regex_skills(text: str) -> set[str]:
    found: set[str] = set()

    for skill, pattern in SKILL_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            found.add(skill)

    return found


def resume_covers_skill(resume_skills: set[str], required: str) -> bool:
    required = normalize_skill(required)
    if required in resume_skills:
        return True

    for alias, canonical in ALIASES.items():
        normalized_alias = normalize_skill(alias)
        if canonical == required and normalized_alias in resume_skills:
            return True
        if normalized_alias == required and canonical in resume_skills:
            return True

    return False


def extract_resume_skills(text: str) -> set[str]:
    skills: set[str] = set()
    skills |= extract_skills_section(text)
    skills |= extract_regex_skills(text)
    return {s for s in skills if s and s not in NON_TECH_SKILLS}


def _max_resume_chars(model: str) -> int:
    limits = get_model_limits(model)
    batch = compute_batch_size(model)
    per_item = max(500, limits.tokens_per_minute // max(batch, 1))
    return min(5000, max(1000, per_item))


def build_prompt(resume: str) -> str:
    resume = resume[: _max_resume_chars(DEFAULT_MODEL)]

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

            skills = {normalize_skill(s) for s in extract_json_array(response)}

            skills = {s for s in skills if s and s not in NON_TECH_SKILLS}

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

        skills: set[str] = set()

        for tech_stack, description in rows:
            if tech_stack and str(tech_stack).strip():
                skills |= parse_delimited_skills(str(tech_stack))

            if description:
                skills |= extract_regex_skills(str(description))

        return {
            s
            for s in skills
            if s and s not in NON_TECH_SKILLS and s not in {"ci", "cd", "b testing"}
        }

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

        resume_skills = extract_resume_skills(resume)

        llm_skills, tokens = extract_llm_skills(resume)

        resume_skills = {
            normalize_skill(s) for s in resume_skills | llm_skills
        }

        required_skills = load_required_skills(db_url)

        gaps = sorted(
            skill
            for skill in required_skills
            if not resume_covers_skill(resume_skills, skill)
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

    resume_file = Path(resume_path)
    db_file = Path(db_path)

    missing: list[str] = []

    if not resume_file.is_file():
        missing.append(f"resume file not found: {resume_path}")

    if not db_file.is_file():
        missing.append(f"db file not found: {db_path}")

    if missing:
        for m in missing:
            print(f"Error: {m}", file=sys.stderr)
        print("Usage: python find_skill_gaps.py [resume_path] [db_path]", file=sys.stderr)
        sys.exit(2)

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
