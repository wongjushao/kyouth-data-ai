from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_RATE_LIMITS_PATH = Path(__file__).resolve().parent / "rate_limits.txt"
DEFAULT_TOKENS_PER_ITEM = 800


@dataclass(frozen=True)
class ModelRateLimit:
    model: str
    requests_per_minute: int
    tokens_per_minute: int
    max_batch: int


def _parse_token_limit(raw: str) -> int:
    text = raw.strip().upper().replace("_", "")
    if text.endswith("K"):
        return int(float(text[:-1]) * 1_000)
    if text.endswith("M"):
        return int(float(text[:-1]) * 1_000_000)
    return int(text)


def load_rate_limits(path: Path | None = None) -> dict[str, ModelRateLimit]:
    limits_path = path or DEFAULT_RATE_LIMITS_PATH
    limits: dict[str, ModelRateLimit] = {}

    for raw in limits_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 4:
            raise ValueError(f"Invalid rate limit line: {raw!r}")

        model, rpm, tpm, max_batch = parts
        limits[model] = ModelRateLimit(
            model=model,
            requests_per_minute=int(rpm),
            tokens_per_minute=_parse_token_limit(tpm),
            max_batch=int(max_batch),
        )

    return limits


def get_model_limits(model: str, path: Path | None = None) -> ModelRateLimit:
    limits = load_rate_limits(path)
    if model in limits:
        return limits[model]

    for name, entry in limits.items():
        if model.startswith(name):
            return entry

    raise KeyError(f"No rate limits configured for model: {model}")


def compute_batch_size(
    model: str,
    *,
    estimated_tokens_per_item: int = DEFAULT_TOKENS_PER_ITEM,
    path: Path | None = None,
) -> int:
    """Derive batch size from RPM, TPM, and per-request cap in rate_limits.txt."""
    limits = get_model_limits(model, path)
    token_budget_batch = max(1, limits.tokens_per_minute // estimated_tokens_per_item)
    return max(
        1,
        min(
            limits.max_batch,
            token_budget_batch,
            limits.requests_per_minute,
        ),
    )
