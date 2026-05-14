from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field


class JobListing(BaseModel):
    """Structured job row for the Silver layer (all fields are strings)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str = Field(min_length=1)
    job_title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    description: str = Field(min_length=1)


_JOB_TITLE_ATTRS: tuple[str, ...] = (
    "data-job-title",
    "data-jobtitle",
    "data-role-title",
    "data-position-title",
)

_COMPANY_ATTRS: tuple[str, ...] = (
    "data-company",
    "data-company-name",
    "data-employer",
    "data-employer-name",
    "data-org-name",
)

_DESCRIPTION_ATTRS: tuple[str, ...] = (
    "data-description",
    "data-job-description",
    "data-jobdetail-description",
    "data-job-details",
)


def _normalize_plain(value: str) -> str:
    s = value.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t\f\v]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _normalize_text(value: str) -> str:
    plain = _normalize_plain(value)
    if "<" in plain and ">" in plain:
        stripped = BeautifulSoup(plain, "html.parser").get_text(separator=" ", strip=True)
        return _normalize_plain(stripped)
    return plain


def _find_by_data_automation(soup: BeautifulSoup, automation_value: str) -> str | None:
    """Jobstreet / SEEK use ``data-automation="<role>"`` (still a ``data-*`` attribute)."""
    hit = soup.find(attrs={"data-automation": automation_value})
    if hit is None:
        return None
    text = hit.get_text(separator=" ", strip=True)
    if text:
        return _normalize_text(text)
    return None


def _extract_job_title_from_meta(soup: BeautifulSoup) -> str | None:
    """Jobstreet encodes the listing title in Open Graph / Twitter meta tags."""
    candidates: list[dict[str, str]] = [
        {"property": "og:title"},
        {"name": "twitter:title"},
        {"property": "twitter:title"},
    ]
    for attrs in candidates:
        tag = soup.find("meta", attrs=attrs)
        content = tag.get("content") if tag else None
        if not content or not isinstance(content, str):
            continue
        raw = content.strip()
        if " Job in " in raw:
            return _normalize_text(raw.split(" Job in ", 1)[0])
        suffix = " - Jobstreet"
        if raw.lower().endswith(suffix.lower()):
            return _normalize_text(raw[: -len(suffix)].strip())
        if raw:
            return _normalize_text(raw)
    return None


def _extract_description_from_meta(soup: BeautifulSoup) -> str | None:
    """Some saved pages omit ``jobAdDetails``; meta tags still carry a short summary."""
    for attrs in (
        {"property": "og:description"},
        {"name": "description"},
        {"property": "twitter:description"},
    ):
        tag = soup.find("meta", attrs=attrs)
        content = tag.get("content") if tag else None
        if not content or not isinstance(content, str):
            continue
        raw = content.strip()
        if raw:
            return _normalize_text(raw)
    return None


def _extract_source_id(soup: BeautifulSoup) -> str | None:
    tag = soup.find("meta", attrs={"property": "og:url"})
    if tag is None:
        tag = soup.find("meta", attrs={"name": "og:url"})
    if tag is None:
        return None
    content = tag.get("content")
    if not content or not isinstance(content, str):
        return None
    parsed = urlparse(content.strip())
    segment = parsed.path.rstrip("/").split("/")[-1]
    return segment or None


def _attr_value(tag, name: str) -> str | None:
    raw = tag.get(name)
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _find_by_data_attrs(soup: BeautifulSoup, attr_names: tuple[str, ...]) -> str | None:
    for name in attr_names:
        hit = soup.find(attrs={name: True})
        if hit is None:
            continue
        from_attr = _attr_value(hit, name)
        if from_attr:
            return _normalize_text(from_attr)
        from_tree = hit.get_text(separator=" ", strip=True)
        if from_tree:
            return _normalize_text(from_tree)
    return None


def _fuzzy_data_field(soup: BeautifulSoup, substrings: tuple[str, ...]) -> str | None:
    """Fallback: first ``data-*`` key whose normalized suffix contains every substring."""
    for tag in soup.find_all(True):
        attrs = getattr(tag, "attrs", None) or {}
        for attr_name in attrs:
            if not isinstance(attr_name, str) or not attr_name.startswith("data-"):
                continue
            tail = re.sub(r"[^a-z0-9]", "", attr_name[5:].lower())
            if not tail or not all(s in tail for s in substrings):
                continue
            val = _attr_value(tag, attr_name)
            if val:
                return _normalize_text(val)
            blob = tag.get_text(separator=" ", strip=True)
            if blob:
                return _normalize_text(blob)
    return None


def _extract_job_title(soup: BeautifulSoup) -> str | None:
    found = _find_by_data_attrs(soup, _JOB_TITLE_ATTRS)
    if found:
        return found
    detail_title = _find_by_data_automation(soup, "job-detail-title")
    if detail_title:
        return detail_title
    meta_title = _extract_job_title_from_meta(soup)
    if meta_title:
        return meta_title
    return _fuzzy_data_field(soup, ("job", "title"))


def _extract_company(soup: BeautifulSoup) -> str | None:
    auto = _find_by_data_automation(soup, "advertiser-name")
    if auto:
        return auto
    found = _find_by_data_attrs(soup, _COMPANY_ATTRS)
    if found:
        return found
    for subs in (("company",), ("employer",)):
        hit = _fuzzy_data_field(soup, subs)
        if hit:
            return hit
    return None


def _extract_description(soup: BeautifulSoup) -> str | None:
    auto = _find_by_data_automation(soup, "jobAdDetails")
    if auto:
        return auto
    found = _find_by_data_attrs(soup, _DESCRIPTION_ATTRS)
    if found:
        return found
    hit = _fuzzy_data_field(soup, ("description",))
    if hit:
        return hit
    fuzzy2 = _fuzzy_data_field(soup, ("job", "description"))
    if fuzzy2:
        return fuzzy2
    return _extract_description_from_meta(soup)


def _print_silver_summary(total: int, processed: int, skipped: int) -> None:
    print()
    print("Silver Summary:")
    print(f"Total: {total} | Processed: {processed} | Skipped: {skipped}")


def process_all_html(input_dir: Path | str, output_dir: Path | str) -> tuple[int, int, int]:
    """
    Read each ``*.html`` under ``input_dir``, strip/normalize text with BeautifulSoup,
    validate as ``JobListing`` (Pydantic), and write ``*.json`` under ``output_dir`` (UTF-8).

    Returns ``(total, processed, skipped)``.
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    print("Silver: cleaning Bronze HTML → structured JSON")

    output_path.mkdir(parents=True, exist_ok=True)

    if not input_path.is_dir():
        _print_silver_summary(0, 0, 0)
        return (0, 0, 0)

    html_files = sorted(input_path.glob("*.html"))
    total = len(html_files)
    processed = 0
    skipped = 0

    for html_path in html_files:
        name = html_path.name
        try:
            raw = html_path.read_text(encoding="utf-8")
        except OSError:
            print(f"Could not read file: {name}")
            skipped += 1
            continue

        soup = BeautifulSoup(raw, "html.parser")

        source_id = _extract_source_id(soup)
        job_title = _extract_job_title(soup)
        company = _extract_company(soup)
        description = _extract_description(soup)

        candidates: dict[str, str | None] = {
            "source_id": source_id,
            "job_title": job_title,
            "company": company,
            "description": description,
        }

        field_order = ("source_id", "job_title", "company", "description")
        missing = [k for k in field_order if not (candidates[k] or "").strip()]
        if missing:
            for field in missing:
                print(f"Missing {field} in: {name}")
            skipped += 1
            continue

        try:
            listing = JobListing.model_validate(
                {k: candidates[k] for k in field_order},
            )
        except Exception:
            print(f"Validation failed for: {name}")
            skipped += 1
            continue

        out_file = output_path / f"{html_path.stem}.json"
        try:
            payload = listing.model_dump()
            out_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            print(f"Could not write output for: {name}")
            skipped += 1
            continue

        print(f"Processed: {name}")
        processed += 1

    _print_silver_summary(total, processed, skipped)
    return (total, processed, skipped)
