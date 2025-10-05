from __future__ import annotations

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Sequence, Tuple

from config import AccountConfig, AppConfig, TaskConfig
from core import RunOutcome, RunRequest, run_once


@dataclass
class TaskOverrides:
    date: Optional[str] = None
    title_keywords: Optional[Sequence[str]] = None
    time_keywords: Optional[Sequence[str]] = None
    strict_match: Optional[bool] = None
    allow_fallback: Optional[bool] = None
    max_attempts: Optional[int] = None
    delay_ms: Optional[Tuple[int, int]] = None


@dataclass
class TaskRuntimeSpec:
    index: int
    account: AccountConfig
    original: TaskConfig
    date: str
    title_keywords: Sequence[str]
    time_keywords: Sequence[str]
    strict_match: bool
    allow_fallback: bool
    max_attempts: int
    delay_ms: Tuple[int, int]


@dataclass
class TaskExecutionRecord:
    spec: TaskRuntimeSpec
    outcome: RunOutcome
    attempts: int


def _compute_rule_date(rule: Optional[str]) -> Optional[str]:
    if not rule:
        return None
    now = datetime.now()
    if rule == "plus_7_after_17":
        delta_days = 6 if now.hour < 17 else 7
        target = now.date() + timedelta(days=delta_days)
        return target.isoformat()
    return None


def _resolve_date(task: TaskConfig, overrides: TaskOverrides, date_rule: Optional[str]) -> str:
    if overrides.date:
        return overrides.date
    if task.date:
        return task.date
    rule_date = _compute_rule_date(date_rule)
    if rule_date:
        return rule_date
    return datetime.now().date().isoformat()


def _resolve_keywords(source: Sequence[str], override: Optional[Sequence[str]]) -> Sequence[str]:
    if override is None:
        return source
    return [str(v) for v in override]


def _resolve_delay(task: TaskConfig, overrides: TaskOverrides) -> Tuple[int, int]:
    if overrides.delay_ms:
        a, b = overrides.delay_ms
        return int(a), int(b)
    return task.delay_ms


def _resolve_bool(value: bool, override: Optional[bool]) -> bool:
    if override is None:
        return value
    return bool(override)


def _resolve_attempts(task: TaskConfig, overrides: TaskOverrides) -> int:
    if overrides.max_attempts is None:
        return max(1, task.max_attempts)
    return max(1, int(overrides.max_attempts))


def _build_runtime_specs(
    config: AppConfig,
    overrides: TaskOverrides
) -> List[TaskRuntimeSpec]:
    specs: List[TaskRuntimeSpec] = []
    for account in config.accounts or []:
        tasks = config.tasks or []
        if not tasks:
            tasks = [TaskConfig()]
        for idx, task in enumerate(tasks):
            resolved_date = _resolve_date(task, overrides, config.date_rule)
            specs.append(
                TaskRuntimeSpec(
                    index=idx,
                    account=account,
                    original=task,
                    date=resolved_date,
                    title_keywords=_resolve_keywords(task.title_keywords, overrides.title_keywords),
                    time_keywords=_resolve_keywords(task.time_keywords, overrides.time_keywords),
                    strict_match=_resolve_bool(task.strict_match, overrides.strict_match),
                    allow_fallback=_resolve_bool(task.allow_fallback, overrides.allow_fallback),
                    max_attempts=_resolve_attempts(task, overrides),
                    delay_ms=_resolve_delay(task, overrides),
                )
            )
    return specs


def _run_single_task(spec: TaskRuntimeSpec, shop_id: str, deadline: Optional[float]) -> TaskExecutionRecord:
    attempts = 0
    outcome: Optional[RunOutcome] = None
    for attempt in range(1, spec.max_attempts + 1):
        attempts = attempt
        if deadline and time.monotonic() > deadline:
            outcome = RunOutcome(
                success=False,
                reason="UNKNOWN",
                http_status=None,
                code=None,
                msg="Global timeout reached",
                req_id=None,
                course=None,
            )
            break
        run_request = RunRequest(
            cookie=spec.account.cookie,
            date=spec.date,
            shop_id=shop_id,
            title_keywords=spec.title_keywords,
            time_keywords=spec.time_keywords,
            strict_match=spec.strict_match,
            allow_fallback=spec.allow_fallback,
            preferred_card_keywords=spec.account.preferred_cards,
        )
        outcome = run_once(run_request)
        if outcome.success:
            break
        if not outcome.retry_recommended or attempt == spec.max_attempts:
            break
        delay_low, delay_high = spec.delay_ms
        sleep_seconds = random.uniform(delay_low / 1000, delay_high / 1000)
        time.sleep(max(0.0, sleep_seconds))
    if outcome is None:
        outcome = RunOutcome(
            success=False,
            reason="UNKNOWN",
            http_status=None,
            code=None,
            msg="未执行",
            req_id=None,
            course=None,
        )
    return TaskExecutionRecord(spec=spec, outcome=outcome, attempts=attempts)


def run_tasks(
    config: AppConfig,
    *,
    overrides: Optional[TaskOverrides] = None,
    shop_id_override: Optional[str] = None,
) -> List[TaskExecutionRecord]:
    overrides = overrides or TaskOverrides()
    shop_id = shop_id_override or config.shop_id
    specs = _build_runtime_specs(config, overrides)
    if not specs:
        return []

    deadline = None
    if config.global_timeout_ms:
        deadline = time.monotonic() + config.global_timeout_ms / 1000

    records: List[TaskExecutionRecord] = []
    by_account: dict[str, List[TaskRuntimeSpec]] = {}
    for spec in specs:
        by_account.setdefault(spec.account.name, []).append(spec)

    for account_name, account_specs in by_account.items():
        print(f"\n[账号] {account_name} - 待执行任务 {len(account_specs)} 个")
        concurrency = max(1, config.concurrency)
        account_records: List[TaskExecutionRecord] = []
        if concurrency <= 1 or len(account_specs) == 1:
            for spec in account_specs:
                record = _run_single_task(spec, shop_id, deadline)
                _log_result(record, config.log_json)
                account_records.append(record)
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                future_map = {
                    executor.submit(_run_single_task, spec, shop_id, deadline): spec
                    for spec in account_specs
                }
                for future in as_completed(future_map):
                    record = future.result()
                    _log_result(record, config.log_json)
                    account_records.append(record)
        account_records.sort(key=lambda r: r.spec.index)
        records.extend(account_records)
    return records


def _log_result(record: TaskExecutionRecord, log_json: bool) -> None:
    spec = record.spec
    outcome = record.outcome
    course_info = outcome.course or {}
    status = "SUCCESS" if outcome.success else "FAIL"
    print(
        f"[任务][{spec.account.name}] {spec.date} | 标题关键字={spec.title_keywords} | 时段关键字={spec.time_keywords}"
    )
    print(
        f"  -> 结果: {status} | 原因: {outcome.reason} | HTTP: {outcome.http_status} | code: {outcome.code} | msg: {outcome.msg}"
    )
    if outcome.final_url:
        print(f"  -> 最终URL: {outcome.final_url}")
    if outcome.evidence:
        print(f"  -> 证据: {outcome.evidence}")
    if course_info:
        print(
            f"  -> 课程: {course_info.get('title')} | {course_info.get('time')} | 链接: {course_info.get('href')}"
        )
    if log_json:
        payload = {
            "ts": datetime.now().isoformat(),
            "account": spec.account.name,
            "task": {
                "date": spec.date,
                "title": list(spec.title_keywords),
                "time": list(spec.time_keywords),
            },
            "status": status,
            "reason": outcome.reason,
            "http": outcome.http_status,
            "code": outcome.code,
            "msg": outcome.msg,
            "req_id": outcome.req_id,
            "final_url": outcome.final_url,
        }
        print(json.dumps(payload, ensure_ascii=False))
