# Week 2: LLM-Powered Job Skill Analysis

## Project Overview

Week 2 builds on the Week 1 job warehouse by adding **large-language-model (LLM) workflows** on top of local SQLite data. The project has two main capabilities:

1. **Job tagging** — Extract a comma-separated `tech_stack` from job descriptions and write it back to the jobs database (`tag_data.py`).
2. **Skill gap analysis** — Compare skills inferred from a resume against skills required across all jobs in a database, and report what is missing (`find_skill_gaps.py`).

A shared **`prompt_model`** module routes prompts to **Google Gemini** (cloud API) or **Ollama** (local), so the same scripts can run with different models via environment variables or CLI arguments.

All code and sample data live under **`week2/`**.

---

## Setup Instructions

### Prerequisites

- **Python 3.12+** (`week2/pyproject.toml` sets `requires-python = ">=3.12"`).
- **[uv](https://docs.astral.sh/uv/)** — installs dependencies and runs scripts in an isolated environment.
- **Google Gemini API key** — required for the default models (`gemini-2.5-flash-lite`). Sign up via [Google AI Studio](https://aistudio.google.com/) and create an API key.
- **Ollama** (optional) — only needed if you switch models to local Ollama names such as `llama3.1` or `phi3`. Install from [ollama.com](https://ollama.com/) and ensure the daemon is running (`curl http://127.0.0.1:11434`).

### Install dependencies

From the repository root:

```bash
cd week2
uv sync
```

This reads `week2/pyproject.toml` and installs `google-genai`, `httpx`, `mcp`, and `pydantic` into uv’s project environment.

### Environment variables

Copy the example file and add your key **locally** (never commit real secrets):

```bash
cp .env.example .env
```

Edit `week2/.env`:

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `GOOGLE_API_KEY` | Yes (for Gemini defaults) | API key for Google Gemini. Loaded from `week2/.env` if not already in the shell environment. |
| `SKILL_GAP_MODEL` | No | Model for `find_skill_gaps.py` (default: `gemini-2.5-flash-lite`). |
| `TAG_MODEL` | No | Model for `tag_data.py` (default: `gemini-2.5-flash-lite`). |
| `OLLAMA_HOST` | No | Ollama base URL (default: `http://127.0.0.1:11434`). |

Scripts call `_load_dotenv()` at startup, which reads `week2/.env` and sets variables only when they are not already defined in the environment.

**Supported model names**

- **Gemini:** `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-3-flash-preview`, or any name starting with `gemini-`
- **Ollama:** `llama3.1`, `phi3`, `deepseek-r1:1.5b`

---

## Usage

All commands assume your working directory is **`week2/`** after `uv sync` and `.env` is configured.

### 1. Test the LLM adapter

```bash
uv run prompt_model.py gemini-2.5-flash-lite "Say hi in one word"
```

**Expected output:** a banner `--- RESPONSE ---` followed by the model’s text (e.g. `Hello`). Errors appear as `[Gemini Error] ...` or `[Ollama Error] ...` without raising to the shell.

### 2. Tag jobs (populate `tech_stack`)

Processes rows where `tech_stack` is NULL or empty, in batches of 5, using the LLM.

```bash
uv run tag_data.py
# or
uv run tag_data.py data/resources/jobs_d1.db
```

**Input:** SQLite file with a `jobs` table (see [Data / Assumptions](#data--assumptions)).

**Expected output (when rows need tagging):**

```text
Analyzed Job 91397216: SQL, Python, R, Tableau, ...
Total tokens used: 1234, took 4500.123ms
```

If every row already has `tech_stack`, you will see:

```text
No data to tag
Total tokens used: 0, took 13.895ms
```

### 3. Find skill gaps (resume vs jobs)

```bash
uv run find_skill_gaps.py
# or with explicit paths
uv run find_skill_gaps.py data/resources/resume_d3.txt data/resources/jobs_d1.db
```

**Inputs:**

- **Resume:** plain-text file (UTF-8). Default: `data/resources/resume_d3.txt`.
- **Database:** SQLite path. Default: `data/resources/jobs_d1.db`.

**Expected output (example with bundled sample data):**

```text
gaps=['aws', 'ci/cd', 'cloud', 'docker', 'git', 'github actions', 'google cloud', 'java', 'llm', 'mongodb', 'nginx', 'node.js', 'power bi', 'pytorch', 'rag', 'scikit-learn', 'spring boot', 'sql', 'tensorflow'] time=3 tokens=179
```

- **`gaps`:** sorted list of required skills (from jobs) not found on the resume.
- **`time`:** elapsed seconds (integer, truncated).
- **`tokens`:** estimated token usage for LLM resume extraction (not exact billing).

### Entry points via `pyproject.toml`

```bash
uv run prompt-model gemini-2.5-flash-lite "Your prompt"
```

`skills-mcp-server` is declared in `pyproject.toml` but no `skills_mcp_server.py` module is present in this tree yet.

---

## API / Function Reference

### Module interaction

```text
                    ┌─────────────────┐
                    │  prompt_model   │
                    │  (Gemini/Ollama)│
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
      ┌───────────────┐             ┌──────────────────┐
      │   tag_data    │             │ find_skill_gaps  │
      │  (jobs DB in) │             │ resume + jobs DB │
      └───────┬───────┘             └────────┬─────────┘
              │                              │
              ▼                              ▼
        UPDATE tech_stack              SkillGapResult
```

---

### `prompt_model.py`

#### `prompt_model(model: str, prompt: str) -> str`

| | |
| --- | --- |
| **Purpose** | Send a text prompt to the named model and return the model’s text response. |
| **Inputs** | `model` — Gemini or Ollama model id (see Setup). `prompt` — non-empty user text. |
| **Outputs** | Response string on success; on failure, a string starting with `[Error]`, `[Gemini Error]`, or `[Ollama Error]` (no exception propagated to callers). |
| **Routing** | Names in `GEMINI_MODELS` or starting with `gemini-` → Google GenAI SDK; otherwise → Ollama HTTP `/api/generate`. |

#### `main()`

CLI: `uv run prompt_model.py <model> <prompt...>` — prints the response under `--- RESPONSE ---`.

---

### `tag_data.py`

#### `tag_data(db_url: str) -> None`

| | |
| --- | --- |
| **Purpose** | Fill empty `tech_stack` columns by asking the LLM to extract technical skills from each job’s `description` (and `job_title` context in the prompt). |
| **Inputs** | `db_url` — filesystem path to a SQLite database. |
| **Outputs** | None; prints progress per job and a summary line `Total tokens used: N, took Xms`. Updates the database in place. |
| **Behavior** | Fetches untagged rows (`tech_stack` NULL or blank), processes in batches of 5 with up to 3 retries (exponential backoff). On batch failure, falls back to per-job calls; persistent failure uses placeholder `General software development`. |

**Internal helpers (not exported):** `_fetch_untagged`, `_build_batch_prompt`, `_normalize_batch_results`, `_update_tech_stack` — support batching, JSON parsing, and SQLite updates.

#### `main()`

CLI: `uv run tag_data.py [path/to/jobs.db]` — defaults to `data/resources/jobs_d1.db` if it exists.

---

### `find_skill_gaps.py`

#### `SkillGapResult` (Pydantic model)

| Field | Type | Description |
| ----- | ---- | ----------- |
| `gaps` | `list[str]` | Required job skills missing from the resume (normalized, sorted). |
| `time` | `float` | Wall-clock seconds for the run. |
| `tokens` | `int` | Estimated tokens used for LLM resume extraction. |

#### `find_skill_gaps(input_file_path: str, db_url: str) -> SkillGapResult`

| | |
| --- | --- |
| **Purpose** | Compare resume skills against aggregated job requirements and return gaps. |
| **Inputs** | `input_file_path` — path to resume text file. `db_url` — SQLite jobs database path. |
| **Outputs** | `SkillGapResult`; on unexpected errors, returns empty `gaps` with elapsed `time` and `tokens=0`. |

#### `extract_regex_skills(text: str) -> set[str]`

| | |
| --- | --- |
| **Purpose** | Deterministic skill detection using predefined regex patterns (`SKILL_PATTERNS`) and aliases (`ALIASES`). |
| **Inputs** | Arbitrary text (resume or job fields). |
| **Outputs** | Set of normalized lowercase skill names (e.g. `python`, `spring boot`). |

#### `extract_llm_skills(resume: str) -> tuple[set[str], int]`

| | |
| --- | --- |
| **Purpose** | Ask the LLM for a JSON array of technical skills from the resume (truncated to 5000 chars). |
| **Inputs** | Full resume text. |
| **Outputs** | `(skills, token_estimate)`; empty set if all retries fail. Filters `NON_TECH_SKILLS`. |

#### `load_required_skills(db_path: str) -> set[str]`

| | |
| --- | --- |
| **Purpose** | Union of regex-extracted skills from every row’s `tech_stack` and `description`. |
| **Inputs** | SQLite path. |
| **Outputs** | Set of required skill strings. |

#### `normalize_skill(skill: str) -> str`

Lowercases, collapses whitespace, applies `ALIASES` (e.g. `gcp` → `google cloud`).

#### `main()`

CLI: `uv run find_skill_gaps.py [resume_path] [db_path]` — prints `gaps`, `time`, `tokens`.

---

## Data / Assumptions

### Data sources

| Asset | Location | Role |
| ----- | -------- | ---- |
| Sample resume | `data/resources/resume_d3.txt` | Plain-text CV for gap analysis demos. |
| Sample jobs DB | `data/resources/jobs_d1.db` | SQLite warehouse with pre-tagged `tech_stack` for three jobs. |
| Optional DB | `jobs.db` (week2 root) | May be used if you copy or build a warehouse from Week 1. |

### Database schema

The scripts expect a **`jobs`** table compatible with Week 1 Gold layer:

```sql
CREATE TABLE jobs (
    source_id TEXT PRIMARY KEY,
    job_title TEXT NOT NULL,
    company TEXT NOT NULL,
    description TEXT NOT NULL,
    tech_stack TEXT
);
```

`tag_data.py` also accepts a numeric/text `id` column instead of `source_id` (auto-detected via `PRAGMA table_info`).

### Input format expectations

- **Resume:** UTF-8 text; encoding errors are replaced (`errors="replace"`). No structured PDF/DOCX parsing.
- **Job descriptions:** Free text in `description`; skills may already appear in `tech_stack` (comma-separated) from tagging or manual entry.
- **LLM responses:** JSON arrays (optionally wrapped in markdown code fences); parsers extract the first `[...]` block if needed.

### Data flow

1. **Tagging path:** `jobs` (empty `tech_stack`) → batch prompt → LLM JSON → `UPDATE jobs SET tech_stack = ?`.
2. **Gap path:** resume file → regex skills ∪ LLM skills → `resume_skills`; all jobs → regex on `tech_stack` + `description` → `required_skills`; **gaps** = `required_skills - resume_skills` (after `normalize_skill` on both sides).

### Assumptions and simplifications

- Skill vocabulary is **closed** to `SKILL_PATTERNS` keys plus whatever the LLM returns for resumes (not an open ontology).
- **Required skills** are inferred only from text already in the DB (not live job-board scraping).
- **Gap logic** is set difference: a skill is “missing” if its normalized form is absent from the resume skill set; partial synonyms beyond `ALIASES` are not handled.
- **Token counts** for `find_skill_gaps` use `(len(prompt) + len(response)) // 4` unless Gemini returns `usage_metadata` in `tag_data`.
- Soft skills (e.g. leadership, English) are excluded from LLM resume extraction via `NON_TECH_SKILLS` but may still appear in job text if regex patterns match.

---

## Testing

There is **no automated test suite** (`pytest` / unit tests) in `week2/`. Validation was done manually:

| Scenario | How to run | What to verify |
| -------- | ---------- | -------------- |
| LLM connectivity | `uv run prompt_model.py gemini-2.5-flash-lite "test"` | Non-error response under `--- RESPONSE ---`. |
| Tagging idempotency | `uv run tag_data.py data/resources/jobs_d1.db` twice | Second run prints `No data to tag` (all rows already have `tech_stack`). |
| Skill gaps (sample) | `uv run find_skill_gaps.py` | Non-empty `gaps` list consistent with resume (e.g. sample resume lacks Java, Docker, SQL despite jobs requiring them). |
| Missing API key | Rename/remove `GOOGLE_API_KEY` and run `prompt_model` | `[Gemini Error] Missing API key...` message. |
| Invalid DB path | `uv run tag_data.py /nonexistent.db` | `Database error: ...` and zero tokens. |

**Determinism:** Regex extraction is deterministic. LLM outputs can vary between runs; retries (`MAX_RETRIES = 3`) improve reliability but do not guarantee identical JSON every time.

**Correctness checks applied:**

- Pydantic validation on `SkillGapResult`.
- Strict batch size matching in `tag_data` (`len(items) == expected`).
- SQLite commits per batch; rollback on write errors.

To reproduce: use the commands in the table after `uv sync` and a valid `.env`.

---

## Limitations

- **Fixed skill catalog:** Only skills matching `SKILL_PATTERNS` (and LLM resume guesses) participate in gap analysis; uncommon stacks may be invisible.
- **LLM accuracy:** Tagging and resume extraction depend on model quality; hallucinated or omitted skills are possible. No human-in-the-loop review.
- **No semantic matching:** `nodejs` and `node.js` align via aliases, but `React` vs `React.js` or version-specific skills are not unified.
- **Performance:** Sequential LLM calls; large databases or long resumes increase latency and API cost. Resume text is capped at 5000 characters for the LLM prompt.
- **Error handling in gaps:** `find_skill_gaps` swallows exceptions and returns empty gaps, which can look like “no gaps” rather than a hard failure.
- **MCP server:** `skills-mcp-server` entry point in `pyproject.toml` is not implemented in the current codebase.
- **Ollama path:** Less tested than Gemini in this week’s workflows; token usage for Ollama is estimated, not read from the API.
- **Single resume:** No multi-candidate ranking or per-job gap report—only one resume vs the union of all job requirements.

---

## Architecture Reflection

### Design choices

The week is split into **three modules** with a narrow shared boundary:

- **`prompt_model`** — Single place for provider logic (HTTP to Ollama, SDK for Gemini), environment loading, and error strings. Downstream code does not import provider SDKs directly except `tag_data`’s optional fast path for Gemini token metadata.
- **`tag_data`** vs **`find_skill_gaps`** — Separate pipelines for **write-back enrichment** (jobs) and **read-only analysis** (resume vs DB). That keeps tagging batching and DB mutation out of the gap analyzer.
- **Hybrid extraction in `find_skill_gaps`** — Regex gives cheap, repeatable coverage for known keywords; the LLM catches skills not in the pattern list. Job requirements use regex only on stored text, avoiding an LLM call per job at query time.

This structure favors **clarity and local iteration** over a monolithic “AI service” layer.

### Trade-offs

| Prioritized | Sacrificed |
| ----------- | ---------- |
| Simplicity and scriptable CLIs | Scalable microservices, job queues, or caching |
| Reuse of Week 1 SQLite | Vector DB or skill taxonomy service |
| Fast gap queries (regex on DB) | Richer per-job LLM requirement parsing |
| Resilience (retries, soft failures) | Strict fail-fast semantics in `find_skill_gaps` |

Defaulting to **Gemini Flash Lite** balances cost and speed; quality-sensitive tagging could use a larger model at higher token cost.

### Improvements

With more time, the design could evolve toward:

- A **shared skill normalization module** (single patterns/aliases file used by tagging and gaps).
- **Structured outputs** (Gemini JSON schema or tool calling) instead of parsing free-form arrays.
- **Automated tests** with mocked LLM responses for deterministic CI.