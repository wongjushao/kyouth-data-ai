from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            source_id TEXT PRIMARY KEY,
            job_title TEXT NOT NULL,
            company TEXT NOT NULL,
            description TEXT NOT NULL,
            tech_stack TEXT
        )
        """
    )
    conn.commit()


def _print_gold_summary(total: int, inserted: int, skipped: int, failed: int) -> None:
    print()
    print("Gold Summary:")
    line = f"Total: {total} | Inserted: {inserted} | Skipped: {skipped}"
    if failed:
        line += f" | Failed: {failed}"
    print(line)


def load_all_jsons(input_dir: Path | str, output_dir: Path | str) -> tuple[int, int, int, int]:
    """
    Read each ``*.json`` under ``input_dir``, upsert into ``output_dir/jobs.db`` with
    ``INSERT OR IGNORE`` on ``source_id`` (idempotent re-runs).

    Returns ``(total, inserted, skipped, failed)``.
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    print("Gold: loading Silver JSON → SQLite (jobs.db)")

    output_path.mkdir(parents=True, exist_ok=True)
    db_path = output_path / "jobs.db"

    if not input_path.is_dir():
        _print_gold_summary(0, 0, 0, 0)
        return (0, 0, 0, 0)

    json_files = sorted(input_path.glob("*.json"))
    total = len(json_files)
    inserted = 0
    skipped = 0
    failed = 0

    conn = sqlite3.connect(db_path)
    try:
        _init_schema(conn)
        cur = conn.cursor()
        sql = """
            INSERT OR IGNORE INTO jobs (source_id, job_title, company, description, tech_stack)
            VALUES (?, ?, ?, ?, ?)
        """

        for json_path in json_files:
            name = json_path.name
            try:
                raw = json_path.read_text(encoding="utf-8")
                data = json.loads(raw)
            except OSError:
                print(f"Failed (read error): {name}")
                failed += 1
                continue
            except json.JSONDecodeError:
                print(f"Failed (invalid JSON): {name}")
                failed += 1
                continue

            if not isinstance(data, dict):
                print(f"Failed (expected object): {name}")
                failed += 1
                continue

            source_id = data.get("source_id")
            job_title = data.get("job_title")
            company = data.get("company")
            description = data.get("description")
            tech_stack = data.get("tech_stack")

            if not isinstance(source_id, str) or not source_id.strip():
                print(f"Failed (missing source_id): {name}")
                failed += 1
                continue
            if not isinstance(job_title, str) or not job_title.strip():
                print(f"Failed (missing job_title): {name}")
                failed += 1
                continue
            if not isinstance(company, str) or not company.strip():
                print(f"Failed (missing company): {name}")
                failed += 1
                continue
            if not isinstance(description, str) or not description.strip():
                print(f"Failed (missing description): {name}")
                failed += 1
                continue

            if tech_stack is None:
                tech_db: str | None = None
            elif isinstance(tech_stack, str):
                tech_db = tech_stack if tech_stack.strip() else None
            else:
                print(f"Failed (invalid tech_stack): {name}")
                failed += 1
                continue

            try:
                cur.execute(
                    sql,
                    (
                        source_id.strip(),
                        job_title.strip(),
                        company.strip(),
                        description.strip(),
                        tech_db,
                    ),
                )
            except sqlite3.Error:
                print(f"Failed (database error): {name}")
                failed += 1
                continue

            if cur.rowcount == 1:
                print(f"Inserted: {name}")
                inserted += 1
            else:
                print(f"⏭️ Skipped (duplicate): {name}")
                skipped += 1

        conn.commit()
    finally:
        conn.close()

    _print_gold_summary(total, inserted, skipped, failed)
    return (total, inserted, skipped, failed)
