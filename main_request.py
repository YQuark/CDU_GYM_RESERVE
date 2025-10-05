from __future__ import annotations

import argparse

from config import load_app_config
from core import RunRequest, run_once


def main() -> None:
    parser = argparse.ArgumentParser(description="styd.cn 自动预约（requests 直发版）")
    parser.add_argument("--date", required=True, help="目标日期，如 2025-10-13")
    parser.add_argument("--shop", help="shop_id，例如 612773420")
    parser.add_argument("--title", action="append", help="标题关键字，可多次传入")
    parser.add_argument("--time", action="append", help="时间关键字，可多次传入")
    parser.add_argument("--cookie", help="覆盖默认账号 Cookie")
    args = parser.parse_args()

    cli_overrides = {}
    if args.shop:
        cli_overrides["SHOP_ID"] = args.shop
    config = load_app_config(cli_overrides)

    if args.cookie:
        cookie = args.cookie
        preferred_cards = []
    elif config.accounts:
        cookie = config.accounts[0].cookie
        preferred_cards = config.accounts[0].preferred_cards
    else:
        parser.error("未提供 Cookie，请通过 --cookie 或 ACCOUNTS 配置。")
        return

    titles = [t for t in (args.title or []) if t]
    times = [t for t in (args.time or []) if t]
    if not titles and config.tasks:
        titles = config.tasks[0].title_keywords
    if not times and config.tasks:
        times = config.tasks[0].time_keywords

    strict_match = config.tasks[0].strict_match if config.tasks else True
    allow_fallback = config.tasks[0].allow_fallback if config.tasks else True

    request = RunRequest(
        cookie=cookie,
        date=args.date,
        shop_id=args.shop or config.shop_id,
        title_keywords=titles,
        time_keywords=times,
        strict_match=strict_match,
        allow_fallback=allow_fallback,
        preferred_card_keywords=preferred_cards,
    )
    outcome = run_once(request)
    if outcome.success:
        print("[结果] 成功")
    else:
        print(f"[结果] 失败：{outcome.reason} -> {outcome.msg}")


if __name__ == "__main__":
    main()
