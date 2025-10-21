from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple


@dataclass
class AccountConfig:
    name: str
    cookie: str
    preferred_cards: List[str] = field(default_factory=list)


@dataclass
class TaskConfig:
    title_keywords: List[str] = field(default_factory=list)
    time_keywords: List[str] = field(default_factory=list)
    date: Optional[str] = None
    strict_match: bool = True
    allow_fallback: bool = True
    max_attempts: int = 1
    delay_ms: Tuple[int, int] = (120, 300)


@dataclass
class AppConfig:
    shop_id: str
    accounts: List[AccountConfig] = field(default_factory=list)
    tasks: List[TaskConfig] = field(default_factory=list)
    date_rule: Optional[str] = None
    global_timeout_ms: Optional[int] = None
    concurrency: int = 1
    log_json: bool = False


def _load_env_file(path: str) -> Dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}
    data: Dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        data[key] = value
    return data


def _merge_sources(
    defaults: Mapping[str, Any],
    env_file: Mapping[str, Any],
    env_vars: Mapping[str, str],
    cli_overrides: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(defaults)
    for source in (env_file, env_vars, cli_overrides or {}):
        for key, value in source.items():
            if value is None:
                continue
            merged[key] = value
    return merged


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    value_str = str(value).strip().lower()
    return value_str in {"1", "true", "yes", "on"}


def _to_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"无法将 {value!r} 转换为整数") from None


def _to_list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 解析失败: {exc}") from exc
        if isinstance(parsed, list):
            return parsed
    raise ValueError(f"期望列表 JSON，但得到 {value!r}")


def _normalise_keywords(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        if not value.strip():
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
    return [str(value)]


def _parse_accounts(data: Any) -> List[AccountConfig]:
    accounts_raw = _to_list(data)
    accounts: List[AccountConfig] = []
    for idx, item in enumerate(accounts_raw):
        if not isinstance(item, MutableMapping):
            raise ValueError(f"ACCOUNTS[{idx}] 不是对象：{item!r}")
        name = str(item.get("name") or f"account-{idx+1}")
        cookie = str(item.get("cookie") or "")
        if not cookie:
            raise ValueError(f"ACCOUNTS[{idx}] 缺少 cookie")
        preferred_cards = _normalise_keywords(item.get("preferred_cards"))
        accounts.append(AccountConfig(name=name, cookie=cookie, preferred_cards=preferred_cards))
    return accounts


def _parse_task(item: MutableMapping[str, Any]) -> TaskConfig:
    title_keywords = _normalise_keywords(item.get("title_keywords"))
    time_keywords = _normalise_keywords(item.get("time_keywords"))
    date = item.get("date")
    strict_match = bool(item.get("strict_match", True))
    allow_fallback = bool(item.get("allow_fallback", True))
    max_attempts = int(item.get("max_attempts", 1) or 1)
    delay_val = item.get("delay_ms")
    delay: Tuple[int, int]
    if isinstance(delay_val, (list, tuple)) and len(delay_val) == 2:
        delay = (int(delay_val[0]), int(delay_val[1]))
    elif isinstance(delay_val, str) and delay_val:
        try:
            parsed = json.loads(delay_val)
        except json.JSONDecodeError as exc:
            raise ValueError(f"TASKS.delay_ms JSON 解析失败: {exc}") from exc
        if isinstance(parsed, list) and len(parsed) == 2:
            delay = (int(parsed[0]), int(parsed[1]))
        else:
            raise ValueError("delay_ms 需要长度为 2 的数组")
    else:
        delay = (120, 300)
    return TaskConfig(
        title_keywords=title_keywords,
        time_keywords=time_keywords,
        date=str(date) if date else None,
        strict_match=strict_match,
        allow_fallback=allow_fallback,
        max_attempts=max(1, max_attempts),
        delay_ms=delay,
    )


def _parse_tasks(data: Any) -> List[TaskConfig]:
    tasks_raw = _to_list(data)
    tasks: List[TaskConfig] = []
    for idx, item in enumerate(tasks_raw):
        if not isinstance(item, MutableMapping):
            raise ValueError(f"TASKS[{idx}] 不是对象：{item!r}")
        tasks.append(_parse_task(item))
    return tasks


def load_app_config(
    cli_overrides: Optional[Mapping[str, Any]] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    env_path: str = ".env",
) -> AppConfig:
    defaults: Dict[str, Any] = {
        "SHOP_ID": "SHOP_0001",
        "ACCOUNTS": [],
        "TASKS": [],
        "DATE_RULE": None,
        "GLOBAL_TIMEOUT_MS": None,
        "CONCURRENCY": 1,
        "LOG_JSON": False,
    }
    env_values = _load_env_file(env_path)
    merged = _merge_sources(defaults, env_values, env or os.environ, cli_overrides)

    shop_id = str(merged.get("SHOP_ID") or defaults["SHOP_ID"])
    accounts = _parse_accounts(merged.get("ACCOUNTS")) if merged.get("ACCOUNTS") else []
    tasks = _parse_tasks(merged.get("TASKS")) if merged.get("TASKS") else []
    date_rule = merged.get("DATE_RULE")
    global_timeout_ms = _to_int(merged.get("GLOBAL_TIMEOUT_MS"))
    concurrency = merged.get("CONCURRENCY", 1)
    try:
        concurrency = int(concurrency)
    except (TypeError, ValueError):
        raise ValueError("CONCURRENCY 需要为整数") from None
    log_json = _to_bool(merged.get("LOG_JSON"))

    return AppConfig(
        shop_id=shop_id,
        accounts=accounts,
        tasks=tasks,
        date_rule=str(date_rule) if date_rule else None,
        global_timeout_ms=global_timeout_ms,
        concurrency=max(1, concurrency),
        log_json=log_json,
    )
