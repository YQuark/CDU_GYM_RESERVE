"""Utilities for masking and sanitising sensitive values before logging or export."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, Mapping

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|pwd|token|cookie|session|shop_id|email|phone|account|url)", re.IGNORECASE
)

_TEXT_PATTERNS = [
    (re.compile(r"https?://[^\s'\"<>]+"), "<REDACTED_URL>"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<REDACTED_EMAIL>"),
    (re.compile(r"(?i)shop_id\s*[:=]\s*[^\s,;]+"), "shop_id: <REDACTED>"),
    (re.compile(r"(?i)(cookie|set-cookie)\s*:?[^\n]*"), "<REDACTED_COOKIE>"),
    (re.compile(r"(?i)(token|access_token|auth)[=:][^\s&;]+"), "<REDACTED_TOKEN>"),
]


def mask_identifier(value: str | None, *, placeholder: str = "<REDACTED>") -> str:
    """Return a stable masked representation for identifiers such as shop_id."""
    if not value:
        return placeholder
    clean = re.sub(r"[^A-Za-z0-9]", "", str(value))
    if not clean:
        return placeholder
    suffix = f"{abs(hash(clean)) & 0xFFFF:04x}"
    return f"{placeholder}_{suffix}" if placeholder else f"***_{suffix}"


def sanitize_text(value: str | None) -> str:
    """Apply regex-based sanitisation on free-form text."""
    if value is None:
        return ""
    text = str(value)
    for pattern, replacement in _TEXT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _sanitize_sequence(data: Iterable[Any]) -> list[Any]:
    return [sanitize_payload(item) for item in data]


def sanitize_payload(data: Any) -> Any:
    """Recursively sanitise dictionaries/lists before exporting."""
    if isinstance(data, str):
        return sanitize_text(data)
    if isinstance(data, Mapping):
        result: Dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(key, str) and _SENSITIVE_KEY_PATTERN.search(key):
                result[key] = "<REDACTED>"
            else:
                result[key] = sanitize_payload(value)
        return result
    if isinstance(data, (list, tuple, set)):
        return _sanitize_sequence(data)
    return data


def sanitise_and_dump_json(data: Any) -> str:
    """Serialise data to JSON after sanitising sensitive parts."""
    cleaned = sanitize_payload(data)
    return json.dumps(cleaned, ensure_ascii=False, indent=2)


__all__ = ["mask_identifier", "sanitize_text", "sanitize_payload", "sanitise_and_dump_json"]
