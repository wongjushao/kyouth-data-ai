from __future__ import annotations

import sqlite3
from pathlib import Path


def run_data_profile(db_path: Path | str) -> None:
    """
    Print data quality metrics for ``jobs`` in ``db_path``.
    If the database file does not exist, print an error and return (no exception).
    """
    path = Path(db_path)
    if not path.is_file():
        print(f"Database not found at {path}")
        return

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        print(f"Database not found at {path}")
        return

    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM jobs")
        row = cur.fetchone()
        total = int(row[0]) if row and row[0] is not None else 0

        cur.execute(
            """
            SELECT
                SUM(job_title IS NULL OR TRIM(COALESCE(job_title, '')) = ''),
                SUM(company IS NULL OR TRIM(COALESCE(company, '')) = ''),
                SUM(description IS NULL OR TRIM(COALESCE(description, '')) = '')
            FROM jobs
            """
        )
        null_row = cur.fetchone()
        if null_row:
            nj, nc, nd = (int(x or 0) for x in null_row)
        else:
            nj = nc = nd = 0

        cur.execute("SELECT AVG(LENGTH(description)) FROM jobs")
        avg_row = cur.fetchone()
        avg_len = float(avg_row[0]) if avg_row and avg_row[0] is not None else 0.0

        shortest_len = 0
        shortest_id = ""
        shortest_title = ""
        longest_len = 0
        longest_id = ""
        longest_title = ""

        if total > 0:
            cur.execute(
                """
                SELECT source_id, job_title, LENGTH(description) AS dlen
                FROM jobs
                ORDER BY dlen ASC, source_id ASC
                LIMIT 1
                """
            )
            s = cur.fetchone()
            if s:
                shortest_id, shortest_title, shortest_len = s[0] or "", s[1] or "", int(s[2] or 0)

            cur.execute(
                """
                SELECT source_id, job_title, LENGTH(description) AS dlen
                FROM jobs
                ORDER BY dlen DESC, source_id ASC
                LIMIT 1
                """
            )
            lrow = cur.fetchone()
            if lrow:
                longest_id, longest_title, longest_len = lrow[0] or "", lrow[1] or "", int(lrow[2] or 0)

    finally:
        conn.close()

    print("--- DATA QUALITY REPORT ---")
    print(f"Total Records: {total}")
    print(f"Missing Values -> job_title: {nj}, company: {nc}, description: {nd}")
    print(f"Avg Description Length: {round(avg_len):.0f} chars")
    print(f"Shortest Description: {shortest_len} chars")
    print(f"source_id: {shortest_id} | job_title: {shortest_title}")
    print(f"Longest Description: {longest_len} chars")
    print(f"source_id: {longest_id} | job_title: {longest_title}")
