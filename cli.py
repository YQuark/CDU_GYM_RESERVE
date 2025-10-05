from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Sequence

from config import AppConfig, TaskConfig, load_app_config
from core import (
    RunRequest,
    create_session,
    fetch_search,
    parse_courses_from_html,
    run_once,
)
from runner import TaskOverrides, run_tasks


def _parse_keywords(values: Optional[Sequence[str]]) -> List[str]:
    if not values:
        return []
    result: List[str] = []
    for value in values:
        if value is None:
            continue
        result.append(str(value))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="styd.cn 自动预约 CLI")
    parser.add_argument("--date", dest="compat_date")
    parser.add_argument("--shop", dest="compat_shop")
    parser.add_argument("--show", dest="compat_show", action="store_true")
    parser.add_argument("--title", dest="compat_title", action="append")
    parser.add_argument("--time", dest="compat_time", action="append")

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run-tasks", help="执行多账号多任务预约")
    run_parser.add_argument("--date")
    run_parser.add_argument("--shop")
    run_parser.add_argument("--title", action="append")
    run_parser.add_argument("--time", action="append")
    run_parser.add_argument("--strict-match", dest="strict_match", action="store_true")
    run_parser.add_argument("--no-strict-match", dest="strict_match", action="store_false")
    run_parser.set_defaults(strict_match=None)
    run_parser.add_argument("--allow-fallback", dest="allow_fallback", action="store_true")
    run_parser.add_argument("--disallow-fallback", dest="allow_fallback", action="store_false")
    run_parser.set_defaults(allow_fallback=None)
    run_parser.add_argument("--max-attempts", type=int)
    run_parser.add_argument("--delay-ms", nargs=2, type=int)
    run_parser.add_argument("--concurrency", type=int)
    run_parser.add_argument("--global-timeout-ms", type=int)
    run_parser.add_argument("--log-json", dest="log_json", action="store_true")
    run_parser.add_argument("--no-log-json", dest="log_json", action="store_false")
    run_parser.set_defaults(log_json=None)

    reserve_parser = subparsers.add_parser("reserve", help="单次直约入口")
    reserve_parser.add_argument("--date", required=True)
    reserve_parser.add_argument("--shop")
    reserve_parser.add_argument("--title", action="append")
    reserve_parser.add_argument("--time", action="append")
    reserve_parser.add_argument("--cookie")
    reserve_parser.add_argument("--strict-match", dest="strict_match", action="store_true")
    reserve_parser.add_argument("--no-strict-match", dest="strict_match", action="store_false")
    reserve_parser.set_defaults(strict_match=None)
    reserve_parser.add_argument("--allow-fallback", dest="allow_fallback", action="store_true")
    reserve_parser.add_argument("--disallow-fallback", dest="allow_fallback", action="store_false")
    reserve_parser.set_defaults(allow_fallback=None)

    show_parser = subparsers.add_parser("show-courses", help="仅展示课程列表")
    show_parser.add_argument("--date", required=True)
    show_parser.add_argument("--shop")
    show_parser.add_argument("--cookie")

    return parser


def _apply_cli_overrides(args: argparse.Namespace) -> dict:
    overrides = {}
    if getattr(args, "shop", None):
        overrides["SHOP_ID"] = args.shop
    if getattr(args, "concurrency", None) is not None:
        overrides["CONCURRENCY"] = args.concurrency
    if getattr(args, "global_timeout_ms", None) is not None:
        overrides["GLOBAL_TIMEOUT_MS"] = args.global_timeout_ms
    if getattr(args, "log_json", None) is not None:
        overrides["LOG_JSON"] = args.log_json
    return overrides


def _build_task_overrides(args: argparse.Namespace) -> TaskOverrides:
    titles = _parse_keywords(getattr(args, "title", None))
    times = _parse_keywords(getattr(args, "time", None))
    overrides = TaskOverrides()
    if getattr(args, "date", None):
        overrides.date = args.date
    if titles:
        overrides.title_keywords = titles
    if times:
        overrides.time_keywords = times
    if getattr(args, "strict_match", None) is not None:
        overrides.strict_match = args.strict_match
    if getattr(args, "allow_fallback", None) is not None:
        overrides.allow_fallback = args.allow_fallback
    if getattr(args, "max_attempts", None) is not None:
        overrides.max_attempts = args.max_attempts
    if getattr(args, "delay_ms", None) is not None:
        delay = getattr(args, "delay_ms")
        overrides.delay_ms = (int(delay[0]), int(delay[1]))
    return overrides


def _resolve_cookie(args: argparse.Namespace, config: AppConfig) -> Optional[str]:
    if getattr(args, "cookie", None):
        return args.cookie
    if config.accounts:
        return config.accounts[0].cookie
    return None


def _resolve_keywords_from_config(config: AppConfig) -> TaskConfig:
    if config.tasks:
        return config.tasks[0]
    return TaskConfig()


def _handle_run_tasks(args: argparse.Namespace) -> int:
    cli_overrides = _apply_cli_overrides(args)
    if getattr(args, "shop", None):
        cli_overrides["SHOP_ID"] = args.shop
    config = load_app_config(cli_overrides)
    task_overrides = _build_task_overrides(args)
    records = run_tasks(
        config,
        overrides=task_overrides,
        shop_id_override=getattr(args, "shop", None),
    )
    if not records:
        print("未发现可执行的任务，请检查 ACCOUNTS/TASKS 配置。")
        return 1
    success = all(record.outcome.success for record in records)
    return 0 if success else 1


def _handle_reserve(args: argparse.Namespace) -> int:
    cli_overrides = {}
    if getattr(args, "shop", None):
        cli_overrides["SHOP_ID"] = args.shop
    config = load_app_config(cli_overrides)
    cookie = _resolve_cookie(args, config)
    if not cookie:
        print("[E] 未提供 Cookie，请通过 --cookie 或 ACCOUNTS 配置。")
        return 1
    shop_id = args.shop or config.shop_id
    titles = _parse_keywords(getattr(args, "title", None))
    times = _parse_keywords(getattr(args, "time", None))
    base_task = _resolve_keywords_from_config(config)
    strict_match = (
        args.strict_match if args.strict_match is not None else base_task.strict_match
    )
    allow_fallback = (
        args.allow_fallback if args.allow_fallback is not None else base_task.allow_fallback
    )
    if not titles:
        titles = base_task.title_keywords
    if not times:
        times = base_task.time_keywords
    run_request = RunRequest(
        cookie=cookie,
        date=args.date,
        shop_id=shop_id,
        title_keywords=titles,
        time_keywords=times,
        strict_match=strict_match,
        allow_fallback=allow_fallback,
        preferred_card_keywords=(config.accounts[0].preferred_cards if config.accounts else None),
    )
    outcome = run_once(run_request)
    status = "SUCCESS" if outcome.success else "FAIL"
    print(f"[reserve] 状态={status} 原因={outcome.reason} HTTP={outcome.http_status} code={outcome.code}")
    if outcome.final_url:
        print(f"[reserve] 最终URL: {outcome.final_url}")
    if outcome.evidence:
        print(f"[reserve] 证据: {outcome.evidence}")
    if outcome.course:
        print(
            f"[reserve] 课程: {outcome.course.get('title')} | {outcome.course.get('time')} | {outcome.course.get('href')}"
        )
    print(f"[reserve] 消息: {outcome.msg}")
    return 0 if outcome.success else 1


def _handle_show(args: argparse.Namespace) -> int:
    cli_overrides = {}
    if getattr(args, "shop", None):
        cli_overrides["SHOP_ID"] = args.shop
    config = load_app_config(cli_overrides)
    cookie = _resolve_cookie(args, config)
    if not cookie:
        print("[E] 未提供 Cookie，请通过 --cookie 或 ACCOUNTS 配置。")
        return 1
    shop_id = args.shop or config.shop_id
    session = create_session(cookie)
    try:
        data = fetch_search(session, date=args.date, shop_id=shop_id, tp="1")
    except Exception as exc:  # pragma: no cover - network specific
        print(f"[E] search 请求失败: {exc}")
        return 1
    class_list_html = (data.get("data") or {}).get("class_list") or ""
    courses = parse_courses_from_html(class_list_html)
    if not courses:
        print("未找到课程，可能未放号或 Cookie 失效。")
        return 1
    for course in courses:
        print(
            f"- {course['title']} | {course['time']} | {course['taken']}/{course['total']} | {course['status']} | {course['href']}"
        )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run-tasks":
        return _handle_run_tasks(args)
    if args.command == "reserve":
        return _handle_reserve(args)
    if args.command == "show-courses":
        return _handle_show(args)

    # 兼容旧参数：--show 表示展示课程
    if getattr(args, "compat_show", False):
        if not args.compat_date:
            parser.error("--show 需要同时提供 --date")
        compat_args = argparse.Namespace(
            date=args.compat_date,
            shop=args.compat_shop,
            cookie=None,
        )
        return _handle_show(compat_args)

    # 没有子命令但传入了 date/shop -> 默认执行 reserve
    if args.compat_date:
        reserve_args = argparse.Namespace(
            date=args.compat_date,
            shop=args.compat_shop,
            title=args.compat_title,
            time=args.compat_time,
            cookie=None,
            strict_match=None,
            allow_fallback=None,
        )
        return _handle_reserve(reserve_args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
