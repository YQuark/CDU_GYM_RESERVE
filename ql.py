"""Entry helpers for running in QingLong (青龙面板) environments."""

from __future__ import annotations

import json
import os
from collections import ChainMap
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

from config import AppConfig, load_app_config
from runner import run_tasks


def _parse_keywords(value: Optional[str]) -> List[str]:
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


def _parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:  # pragma: no cover - defensive branch
        raise ValueError(f"无法解析整数: {value}") from exc


def _parse_delay(value: Optional[str]) -> Optional[Tuple[int, int]]:
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


def _build_simple_env(env: Mapping[str, str]) -> Dict[str, str]:
    if env.get("ACCOUNTS"):
        return {}

    cookie = (
        env.get("STYD_COOKIE")
        or env.get("QL_COOKIE")
        or env.get("COOKIE")
    )
    if not cookie:
        return {}

    account_name = env.get("STYD_ACCOUNT_NAME", "QL-Account")
    preferred_cards = _parse_keywords(env.get("STYD_PREFERRED_CARDS"))

    title_keywords = _parse_keywords(env.get("STYD_TITLE_KEYWORDS"))
    time_keywords = _parse_keywords(env.get("STYD_TIME_KEYWORDS"))
    date_value = env.get("STYD_DATE") or None
    strict_match = env.get("STYD_STRICT_MATCH")
    allow_fallback = env.get("STYD_ALLOW_FALLBACK")
    max_attempts = env.get("STYD_MAX_ATTEMPTS")
    delay_value = env.get("STYD_DELAY_MS")

    task: MutableMapping[str, object] = {}
    has_keywords = False
    if title_keywords:
        task["title_keywords"] = title_keywords
        has_keywords = True
    if time_keywords:
        task["time_keywords"] = time_keywords
        has_keywords = True

    if not has_keywords:
        if env.get("TASKS"):
            task.clear()
        else:
            raise ValueError(
                "至少需要配置 STYD_TITLE_KEYWORDS 或 STYD_TIME_KEYWORDS 才能生成任务。"
            )
    else:
        if date_value:
            task["date"] = date_value
        if strict_match is not None:
            task["strict_match"] = _parse_bool(strict_match, True)
        if allow_fallback is not None:
            task["allow_fallback"] = _parse_bool(allow_fallback, True)
        if max_attempts is not None and max_attempts != "":
            attempts = _parse_int(max_attempts)
            if attempts is not None:
                task["max_attempts"] = max(1, attempts)
        if delay_value:
            delay = _parse_delay(delay_value)
            if delay:
                task["delay_ms"] = list(delay)

    accounts_payload: List[MutableMapping[str, object]] = [
        {"name": account_name, "cookie": cookie}
    ]
    if preferred_cards:
        accounts_payload[0]["preferred_cards"] = preferred_cards

    tasks_payload: List[MutableMapping[str, object]]
    if task:
        tasks_payload = [task]
    else:
        tasks_payload = []

    merged: Dict[str, str] = {
        "ACCOUNTS": json.dumps(accounts_payload, ensure_ascii=False),
    }
    if tasks_payload:
        merged["TASKS"] = json.dumps(tasks_payload, ensure_ascii=False)

    if env.get("STYD_SHOP_ID"):
        merged["SHOP_ID"] = env["STYD_SHOP_ID"]
    if env.get("STYD_DATE_RULE"):
        merged["DATE_RULE"] = env["STYD_DATE_RULE"]
    if env.get("STYD_GLOBAL_TIMEOUT_MS"):
        merged["GLOBAL_TIMEOUT_MS"] = env["STYD_GLOBAL_TIMEOUT_MS"]
    if env.get("STYD_CONCURRENCY"):
        merged["CONCURRENCY"] = env["STYD_CONCURRENCY"]
    if env.get("STYD_LOG_JSON"):
        merged["LOG_JSON"] = env["STYD_LOG_JSON"]

    return merged


def _load_config_for_ql() -> AppConfig:
    env = os.environ
    simple_env = _build_simple_env(env)
    if simple_env:
        combined = ChainMap(simple_env, env)
    else:
        combined = env
    return load_app_config(env=combined)


def run_in_ql_mode() -> int:
    try:
        config = _load_config_for_ql()
    except ValueError as exc:
        print(f"[配置错误] {exc}")
        return 1

    if not config.accounts:
        print("[配置错误] 未检测到账户信息，请设置 STYD_COOKIE 或 ACCOUNTS 环境变量。")
        return 1

    if not config.tasks:
        print("[配置错误] 未配置预约任务，请设置 STYD_TITLE_KEYWORDS/STYD_TIME_KEYWORDS 或 TASKS。")
        return 1

    records = run_tasks(config)
    if not records:
        print("[提示] 没有可执行的任务，请检查配置。")
        return 1
    success = all(record.outcome.success for record in records)
    return 0 if success else 1


__all__ = ["run_in_ql_mode"]

