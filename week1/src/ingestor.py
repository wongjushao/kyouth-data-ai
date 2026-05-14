from __future__ import annotations

import quopri
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path


def _decode_html_payload(part: Message) -> bytes | None:
    """Return decoded HTML bytes for a MIME part, or None if empty."""
    cte = (part.get("Content-Transfer-Encoding") or "").lower().strip()
    payload = part.get_payload()

    if isinstance(payload, list):
        return None

    if cte == "quoted-printable":
        if isinstance(payload, str):
            raw = payload.encode("latin-1", errors="replace")
        elif isinstance(payload, bytes):
            raw = payload
        else:
            return None
        try:
            return quopri.decodestring(raw)
        except Exception:
            return None

    decoded = part.get_payload(decode=True)
    if decoded is None:
        return None
    if isinstance(decoded, str):
        return decoded.encode("utf-8", errors="replace")
    return decoded


def _first_text_html_part(msg: Message) -> Message | None:
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part
    return None


def _extract_html_from_mhtml(path: Path) -> bytes | None:
    raw = path.read_bytes()
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    part = _first_text_html_part(msg)
    if part is None:
        return None
    return _decode_html_payload(part)


def ingest_all_mhtml(input_dir: Path | str, output_dir: Path | str) -> tuple[int, int, int]:
    """
    Extract text/html from each .mhtml under input_dir, decode (quoted-printable via quopri),
    and write sibling .html files under output_dir.

    Returns (total, extracted, failed).
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    print("Bronze: extracting text/html from MHTML → HTML")

    output_path.mkdir(parents=True, exist_ok=True)

    if not input_path.is_dir():
        _print_summary(0, 0, 0)
        return (0, 0, 0)

    mhtml_files = sorted(input_path.glob("*.mhtml"))
    total = len(mhtml_files)
    extracted = 0
    failed = 0

    for mhtml in mhtml_files:
        name = mhtml.name
        try:
            html_bytes = _extract_html_from_mhtml(mhtml)
        except OSError:
            print(f"Could not read file: {name}")
            failed += 1
            continue
        except Exception:
            print(f"Failed to parse MHTML: {name}")
            failed += 1
            continue

        if not html_bytes or not html_bytes.strip():
            print(f"No HTML content found in: {name}")
            failed += 1
            continue

        out_file = output_path / f"{mhtml.stem}.html"
        try:
            text = html_bytes.decode("utf-8", errors="replace")
            out_file.write_text(text, encoding="utf-8", newline="\n")
        except OSError:
            print(f"Could not write output for: {name}")
            failed += 1
            continue

        print(f"Extracted: {name}")
        extracted += 1

    _print_summary(total, extracted, failed)
    return (total, extracted, failed)


def _print_summary(total: int, extracted: int, failed: int) -> None:
    print()
    print("Bronze Summary:")
    print(f"Total: {total} | Extracted: {extracted} | Failed: {failed}")
