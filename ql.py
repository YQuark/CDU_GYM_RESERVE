"""Entry helpers for running in QingLong (青龙面板) environments."""

from __future__ import annotations

import json
import os
from collections import ChainMap
from typing import Dict, List, Mapping, MutableMapping, Optional

from config import AppConfig, load_app_config
from config_utils import (
    parse_bool,
    parse_date_list,
    parse_delay,
    parse_int,
    parse_keywords,
)
from runner import run_tasks


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
    preferred_cards = parse_keywords(env.get("STYD_PREFERRED_CARDS"))

    title_keywords = parse_keywords(env.get("STYD_TITLE_KEYWORDS"))
    time_keywords = parse_keywords(env.get("STYD_TIME_KEYWORDS"))
    date_values = parse_date_list(env.get("STYD_DATE"))
    date_value = date_values[0] if len(date_values) == 1 else None
    strict_match = env.get("STYD_STRICT_MATCH")
    allow_fallback = env.get("STYD_ALLOW_FALLBACK")
    max_attempts = env.get("STYD_MAX_ATTEMPTS")
    delay_value = env.get("STYD_DELAY_MS")

    task_base: MutableMapping[str, object] = {}
    has_keywords = False
    if title_keywords:
        task_base["title_keywords"] = title_keywords
        has_keywords = True
    if time_keywords:
        task_base["time_keywords"] = time_keywords
        has_keywords = True

    if not has_keywords:
        if env.get("TASKS"):
            task_base.clear()
        else:
            raise ValueError(
                "至少需要配置 STYD_TITLE_KEYWORDS 或 STYD_TIME_KEYWORDS 才能生成任务。"
            )
    else:
        if date_value:
            task_base["date"] = date_value
        if strict_match is not None:
            task_base["strict_match"] = parse_bool(strict_match, True)
        if allow_fallback is not None:
            task_base["allow_fallback"] = parse_bool(allow_fallback, True)
        if max_attempts is not None and max_attempts != "":
            attempts = parse_int(max_attempts)
            if attempts is not None:
                task_base["max_attempts"] = max(1, attempts)
        if delay_value:
            delay = parse_delay(delay_value)
            if delay:
                task_base["delay_ms"] = list(delay)

    accounts_payload: List[MutableMapping[str, object]] = [
        {"name": account_name, "cookie": cookie}
    ]
    if preferred_cards:
        accounts_payload[0]["preferred_cards"] = preferred_cards

    tasks_payload: List[MutableMapping[str, object]]
    if task_base:
        if date_values and len(date_values) > 1:
            tasks_payload = []
            for date in date_values:
                task_copy = dict(task_base)
                task_copy["date"] = date
                tasks_payload.append(task_copy)
        else:
            tasks_payload = [task_base]
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

