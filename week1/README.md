# kyouth-data-ai

## Project Description

This repository contains a **Week 1 local data pipeline** that ingests saved Jobstreet-style job listings (vendor **MHTML** snapshots), moves them through a **Medallion-style folder layout** (`0_source` → `1_bronze` → `2_silver` → `3_gold`), and lands curated rows in a **SQLite “Gold” warehouse** (`jobs.db`). A small CLI orchestrator runs extract, transform, load, and a lightweight **data quality profile** in sequence or as separate steps.

Pipeline code, dependencies, and sample data live under **`week1/`**.

---

## Setup Instructions

### Prerequisites

- **Python 3.14** (see `week1/.python-version`; `pyproject.toml` declares `requires-python = ">=3.14"`).
- **[uv](https://docs.astral.sh/uv/) 0.8.x** — `pyproject.toml` requires `>=0.8.0,<0.9.0`. Install with: `curl -LsSf https://astral.sh/uv/0.8.22/install.sh | sh`

### Install dependencies

From the repository root:

```bash
cd week1
uv sync
```

This reads `week1/pyproject.toml` and `week1/uv.lock` and installs packages (including `bs4`, `pydantic`, and `ruff`) into uv’s project environment.

### Environment variables

This pipeline **does not read API keys or other secrets** from the environment. All inputs are local files under `week1/data/`. If you extend the project (for example, to fetch listings over HTTP), add variables such as `JOBSTREET_API_KEY` to your shell or a `.env` file **and document the names only here**—never commit real secret values.

---

## Usage

All commands below assume your working directory is **`week1/`** (after `uv sync`).

### CLI overview

`main.py` exposes:

| Command   | What it does |
| --------- | -------------- |
| `ingest`  | Read `data/0_source/*.mhtml`, extract HTML → `data/1_bronze/*.html` |
| `process` | Parse Bronze HTML → validated JSON → `data/2_silver/*.json` |
| `load`    | Load Silver JSON → `data/3_gold/jobs.db` (SQLite) |
| `profile` | Print a data quality report from `jobs.db` |
| `all`     | Run `ingest`, then `process`, then `load`, then `profile` |

### Examples

**Full pipeline (recommended for a clean end-to-end run):**

```bash
uv run python main.py all
```

**Run one stage at a time:**

```bash
uv run python main.py ingest
uv run python main.py process
uv run python main.py load
uv run python main.py profile
```

**Expected behavior (high level)**

- **Inputs:** `.mhtml` files in `week1/data/0_source/` (saved pages). The repo may already include sample data; add your own `.mhtml` files there to ingest new sources.
- **Outputs:**
  - Bronze: one `.html` per successful MHTML (console lines like `Extracted: <file>.mhtml`, plus a summary).
  - Silver: one `.json` per successfully parsed listing (`Processed: <file>.html`); files with missing required fields are **skipped** with messages such as `Missing job_title in: ...`.
  - Gold: SQLite database at `week1/data/3_gold/jobs.db`; new rows print `Inserted: ...`, duplicates print `Skipped (duplicate): ...`.
  - Profile: a printed **DATA QUALITY REPORT** (row counts, null checks, description length stats).

If you run `ingest` with an empty or missing `0_source` directory, you will see a Bronze summary with zeros and no new HTML files.

---

## Technical Reflections

### Module 1: The Extractor (Medallion & Lakehouses)

- **What We Did:** Setup folder-based Medallion Architecture `(0_source to 3_gold)`. Extracted raw `.mhtml` files to `1_bronze/`.
- **Industry Context:** Modern data platforms often use ***Data Lakes*** to store raw files before transforming them into structured, query-ready data in a ***Data Warehouse**.*
- **Reflection:** Why is it useful to keep the original raw HTML files instead of directly inserting processed data into the database? What problems become easier to debug or recover from?
- **Answer:** Auditability and disputes. For research, compliance, or “what did the page actually say on date X?”, raw captures support provenance: you can show what was ingested, not just your interpretation of it.

### Module 2: Treatment Plant (ETL vs ELT & Scale)

- **What We Did:** Clean HTML `(transform into 2_silver/)` before database load `(load into 3_gold/)` (ETL).
- **Industry Context:** Cloud platforms ***(Snowflake/BigQuery)*** often store raw data first then transform later ***(ELT)***. Enterprise systems use ***Apache Spark*** to process large amounts of data in parallel instead of one file at a time.
- **Reflection:** Why do cloud systems prefer loading raw data first before cleaning it (ELT)? What problems happen when processing files sequentially, and how does distributed processing help?
- **Answer:** Separation of concerns. Landing raw data gives you a durable source of truth. Cleaning rules change over time; with raw data stored, you can re-run transformations without re-extracting from operational systems.

### Module 3: The Blueprint & The Vault (Storage & Contracts)

- **What We Did:** Used SQLite as Gold “warehouse” layer. Enforced basic data integrity via idempotency during load.
- **Industry Context:** Production systems often separate databases used for day-to-day application operations ***(OLTP)*** from databases optimized for analytics and reporting ***(OLAP)***. Strict Data Contracts help ensure incomplete or corrupted data does not break dashboards, analytics, or downstream systems.
- **Reflection:** What should happen if an important field like `job_title` disappears? Why fail early instead of silently inserting `nulls` into DB? How does `INSERT OR IGNORE` help prevent duplicate records?
- **Answer:** Schema and constraints. SQLite will reject inserts that violate NOT NULL on job_title. Silently turning missing into NULL either breaks the insert anyway or forces you to weaken the schema (e.g. drop NOT NULL), which makes bad data look “valid.”

### Module 4: The QA Inspector & Orchestrator (Orchestration & DAGs)

- **What We Did:** `main.py` acts as manual orchestrator, `all` command finalizes sequence
- **Industry Context:** Real-world pipelines usually use orchestration tools like ***Airflow***, which automate execution, retries, scheduling, and dependency management.
- **Reflection:** What happens if `processor.py` crashes halfway? How are automated orchestration tools more reliable than manual retries with Python scripts?
- **Answer:** Observability. Run history, logs per task, alerts when a DAG/task fails. Manual runs often leave no durable audit trail.