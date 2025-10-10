"""Shared parsing helpers for environment/config inputs."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple


def parse_keywords(value: Optional[str]) -> List[str]:
    """Parse a delimiter-separated keyword string into a list."""
    if not value:
        return []
    raw = value.strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, Iterable) and not isinstance(parsed, (str, bytes)):
            return [str(item).strip() for item in parsed if str(item).strip()]
    for sep in ("|", ",", "\n", ";"):
        if sep in raw:
            return [part.strip() for part in raw.split(sep) if part.strip()]
    return [raw]


def parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:  # pragma: no cover - defensive branch
        raise ValueError(f"无法解析整数: {value}") from exc


def parse_delay(value: Optional[str]) -> Optional[Tuple[int, int]]:
    if value is None or not value.strip():
        return None
    raw = value.strip()
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"delay_ms JSON 解析失败: {exc}") from exc
        if isinstance(parsed, (list, tuple)) and len(parsed) == 2:
            return int(parsed[0]), int(parsed[1])
        raise ValueError("delay_ms 需要长度为 2 的数组")
    for sep in ("|", ",", ";", " "):
        if sep in raw:
            parts = [part for part in raw.split(sep) if part.strip()]
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
    raise ValueError("delay_ms 需要形如 '120,300' 的两个整数")


def parse_date_list(value: Optional[str]) -> List[str]:
    if value is None:
        return []
    raw = value.strip()
    if not raw:
        return []

    def _parse_single(date_str: str) -> date:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError as exc:  # pragma: no cover - defensive branch
            raise ValueError(f"无法解析日期: {date_str}") from exc

    def _expand(token: str) -> List[date]:
        token = token.strip()
        if not token:
            return []
        if "~" in token:
            start_raw, end_raw = [part.strip() for part in token.split("~", 1)]
            if not start_raw or not end_raw:
                raise ValueError(f"日期范围格式错误: {token}")
            start = _parse_single(start_raw)
            end = _parse_single(end_raw)
            if end < start:
                start, end = end, start
            days: List[date] = []
            current = start
            while current <= end:
                days.append(current)
                current += timedelta(days=1)
            return days
        return [_parse_single(token)]

    tokens: List[str]
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive branch
            raise ValueError(f"无法解析日期列表: {exc}") from exc
        if isinstance(parsed, Iterable) and not isinstance(parsed, (str, bytes)):
            tokens = [str(item) for item in parsed if str(item).strip()]
        else:
            raise ValueError("STYD_DATE 需要为字符串或字符串数组")
    else:
        tokens = [raw]
        for sep in ("|", ",", ";", "\n"):
            if sep in raw:
                tokens = [part for part in raw.split(sep) if part.strip()]
                break

    collected: dict[str, date] = {}
    for token in tokens:
        for item in _expand(token):
            collected[item.isoformat()] = item
    ordered = sorted(collected.items(), key=lambda kv: kv[1])
    return [iso for iso, _ in ordered]


__all__ = [
    "parse_keywords",
    "parse_bool",
    "parse_int",
    "parse_delay",
    "parse_date_list",
]
