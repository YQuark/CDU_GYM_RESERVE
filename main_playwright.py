# -*- coding: utf-8 -*-
"""
styd.cn 自动预约（Playwright 异步版）
- 查询可约课程 -> 选定目标 -> 打开订单页 -> 点击"确认预约" -> 弹窗"确定" -> 监听 order_confirm 响应
- 需要：有效 Cookie（含 PHPSESSID / sass_gym_* 等）
"""

import re
import json
import time
import random
import argparse
import asyncio
import sys
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple, Iterable, Union

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ====== 基本配置（按需修改） ======
BASE = "https://www.styd.cn"
SPACE = "e74abd6e"
SEARCH_API = f"{BASE}/m/{SPACE}/default/search"
ORDER_URL_TMPL = f"{BASE}/m/{SPACE}/course/order?id={{cid}}"

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
             "Mobile/15E148 Safari/604.1 Edg/140.0.0.0")

# 把你抓到的一整串 Cookie 原样粘进来
#RAW_COOKIE = r"""acw_tc=...; PHPSESSID=...; sass_gym_wap=...; sass_gym_base=...; club_gym_fav_shop_id=..."""
RAW_COOKIE = r"""acw_tc=0aef82d717595077534875864ee3c54e2b8152570af745e9d511f9ed422776; sass_gym_shop_owner=8d5c1b09e9bcdb787f2b00cd3a730d49b1f1142fa0a7ae9f7f6ac4e329a3a985a%3A2%3A%7Bi%3A0%3Bs%3A19%3A%22sass_gym_shop_owner%22%3Bi%3A1%3Bs%3A8%3A%22e74abd6e%22%3B%7D; Hm_lvt_f4a079b93f8455a44b27c20205cbb8b3=1759507757; HMACCOUNT=DDF29FB8313FFB52; rsource=1320acdbe79dceaac8a47a5bb72c36af3f9a292693e3bf536e960a7c67631e56a%3A2%3A%7Bi%3A0%3Bs%3A7%3A%22rsource%22%3Bi%3A1%3Bs%3A7%3A%22styd.cn%22%3B%7D; PHPSESSID=95hglj7jri5edbittpub3ol2o0; sass_gym_wap=d2500380f34de647cdbee6ac749a9897275e10ee31db81dcb912a3fb28bbc58fa%3A2%3A%7Bi%3A0%3Bs%3A12%3A%22sass_gym_wap%22%3Bi%3A1%3Bs%3A41%3A%222f4f340d142c1cc5c5173fe49fbc1c92%2329356716%22%3B%7D; sass_gym_base=d647e2f758cbb4b43c34e53b57eefc2f55d24ae78e5ab30df0dc8043d5a427cca%3A2%3A%7Bi%3A0%3Bs%3A13%3A%22sass_gym_base%22%3Bi%3A1%3Bs%3A41%3A%222f4f340d142c1cc5c5173fe49fbc1c92%2329356716%22%3B%7D; club_gym_fav_shop_id=dc8d145bd76114fc5213fa9e22c6ac58f7879d80a53a57872cb0d2fd4ef0dabca%3A2%3A%7Bi%3A0%3Bs%3A20%3A%22club_gym_fav_shop_id%22%3Bi%3A1%3Bi%3A612773420%3B%7D; saas_gym_buy_referer=3909ac13f0218caf1d861b024048b94123b89f38fba14ca389d1735ed62f8528a%3A2%3A%7Bi%3A0%3Bs%3A20%3A%22saas_gym_buy_referer%22%3Bi%3A1%3Bs%3A55%3A%22https%3A%2F%2Fwww.styd.cn%2Fm%2Fe74abd6e%2Fcourse%2Forder%3Fid%3D89007443%22%3B%7D; Hm_lpvt_f4a079b93f8455a44b27c20205cbb8b3=1759509539"""

# 订单页上的按钮与弹窗
ORDER_BUTTON_SELECTORS = [
    "#do_order",
]

# 选课策略
PREFERRED_KEYWORDS = ["健身中心（午）"]
PREFERRED_TIME_RANGES = ["12:30 - 14:00", "19:00 - 21:00"]
# 当设置了关键词时，是否必须命中其一；若无匹配可回退到全部课程
REQUIRE_KEYWORD_MATCH = True

# 拥挤限制
MAX_OCCUPANCY_RATIO = 0.98
MAX_ABSOLUTE_TAKEN = None

# 重试与退避
FETCH_RETRIES = 3
SUBMIT_RETRIES = 2
RETRY_SLEEP = (0.7, 1.3)
# ====== 配置结束 ======


@dataclass
class Course:
    title: str
    time_range: str
    taken: int
    total: int
    status: str
    order_href: str
    raw_li_html: str


def parse_cookie_dict(raw_cookie: str) -> Dict[str, str]:
    kv = {}
    for p in re.split(r";\s*", raw_cookie.strip()):
        if not p:
            continue
        if "=" in p:
            k, v = p.split("=", 1)
            kv[k] = v
    return kv


def parse_courses(html_ul: str) -> List[Course]:
    soup = BeautifulSoup(html_ul, "lxml")
    result: List[Course] = []
    for li in soup.select("ul.course_list > li"):
        a = li.select_one("a.course_link")
        if not a:
            continue
        href = a.get("href", "")
        title_el = li.select_one(".course_detail .name")
        time_el = li.select_one(".course_detail .date b")
        title = title_el.get_text(strip=True) if title_el else ""
        time_range = time_el.get_text(strip=True) if time_el else ""

        taken, total = 0, 0
        span = li.select_one(".course_thumbs span")
        if span and "/" in span.text:
            try:
                taken, total = [int(x.strip()) for x in span.text.strip().split("/", 1)]
            except:
                pass

        status = "unknown"
        status_i = li.select_one(".book_status i.course_status")
        if status_i:
            classes = " ".join(status_i.get("class", []))
            for k in ["available", "hot", "full", "stop", "queue"]:
                if k in classes:
                    status = k
                    break

        result.append(Course(
            title=title,
            time_range=time_range,
            taken=taken,
            total=total,
            status=status,
            order_href=href,
            raw_li_html=str(li)
        ))
    return result


def norm_url(href: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return BASE + href
    return BASE + "/" + href


def pick_course(courses: List[Course]) -> Optional[Course]:
    pool = [c for c in courses if c.status in ("available", "hot", "queue")]
    if not pool:
        return None

    matched_pool = pool
    if PREFERRED_KEYWORDS and REQUIRE_KEYWORD_MATCH:
        matched_pool = [
            c for c in pool if any(kw in c.title for kw in PREFERRED_KEYWORDS)
        ]
        if not matched_pool:
            print("[!] 未找到匹配关键字的课程，将回退至全部可预约课程。")
            matched_pool = pool

    def score(c: Course) -> Tuple[int, int, float]:
        kw_rank = min((i for i, kw in enumerate(PREFERRED_KEYWORDS) if kw in c.title), default=999)
        t_rank = min((i for i, tr in enumerate(PREFERRED_TIME_RANGES) if tr in c.time_range), default=999)
        ratio = (c.taken / c.total) if c.total else 1.0
        return (kw_rank, t_rank, ratio)

    matched_pool.sort(key=score)

    for c in matched_pool:
        ratio_ok = (c.taken / c.total) < MAX_OCCUPANCY_RATIO if c.total else True
        abs_ok = (c.taken <= MAX_ABSOLUTE_TAKEN) if (MAX_ABSOLUTE_TAKEN is not None) else True
        if ratio_ok and abs_ok:
            return c
    return matched_pool[0] if matched_pool else None


SelectorInput = Union[Iterable[str], str, None]


def _as_selector_list(selectors: SelectorInput) -> List[str]:
    if not selectors:
        return []
    if isinstance(selectors, str):
        return [selectors]
    return [s for s in selectors if s]


async def _click_first_selector(page, selectors: Iterable[str], timeout: int) -> bool:
    last_err: Optional[Exception] = None
    for sel in selectors:
        try:
            if sel == "#do_order":
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_function(
                    """
                    selector => {
                      const el = document.querySelector(selector);
                      if (!el) return false;
                      const style = window.getComputedStyle(el);
                      if (!style) return false;
                      const hidden = style.visibility === 'hidden' || style.display === 'none';
                      const disabled = el.hasAttribute('disabled')
                        || el.getAttribute('aria-disabled') === 'true'
                        || el.classList.contains('disabled');
                      return !hidden && !disabled;
                    }
                    """,
                    arg=sel,
                    timeout=timeout,
                )
            await page.wait_for_selector(sel, timeout=timeout)
            loc = page.locator(sel)
            await loc.scroll_into_view_if_needed()
            try:
                await loc.click()
            except Exception:
                await loc.click(force=True)
            return True
        except Exception as e:  # noqa: BLE001
            last_err = e
    if last_err:
        print(f"[E] 未能点击任何按钮选择器：{selectors}。最后错误：{last_err}")
    else:
        print("[E] 未配置有效的按钮选择器。")
    return False


async def add_cookies(context, raw_cookie: str):
    cookies = []
    for k, v in parse_cookie_dict(raw_cookie).items():
        cookies.append({
            "name": k,
            "value": v,
            "domain": "www.styd.cn",
            "path": "/",
            "httpOnly": False,
            "secure": True
        })
    await context.add_cookies(cookies)


async def fetch_search(context, date: str, shop_id: str, tp: str = "1") -> Dict[str, Any]:
    last_err = None
    for _ in range(FETCH_RETRIES):
        try:
            resp = await context.request.get(
                SEARCH_API,
                params={"date": date, "shop_id": shop_id, "type": tp},
                headers={
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{BASE}/m/{SPACE}/default/index?type=1",
                    "User-Agent": MOBILE_UA,
                },
                timeout=15_000
            )
            if resp.ok:
                return await resp.json()
            last_err = f"HTTP {resp.status}"
        except Exception as e:
            last_err = str(e)
        await asyncio.sleep(random.uniform(*RETRY_SLEEP))
    raise RuntimeError(f"search 重试失败：{last_err}")


async def book_with_playwright(course_id: str, raw_cookie: str, show: bool = False) -> bool:
    async with async_playwright() as p:
        browser = await p.webkit.launch(headless=not show)
        try:
            context = await browser.new_context(
                user_agent=MOBILE_UA,
                viewport={"width": 390, "height": 844},
            )
            await add_cookies(context, raw_cookie)
            page = await context.new_page()

            order_url = ORDER_URL_TMPL.format(cid=course_id)
            await page.goto(order_url, wait_until="domcontentloaded", timeout=20000)

            html = await page.content()
            if any(x in html for x in ["登录", "请先登录", "手机号"]):
                print("[E] Cookie 失效或未登录。")
                return False

            ok = False
            submit_selectors = _as_selector_list(ORDER_BUTTON_SELECTORS)
            if not submit_selectors:
                print("[E] 未配置下单按钮选择器，请设置 ORDER_BUTTON_SELECTORS。")
                return False

            try:
                async with page.expect_response(
                    lambda r: (
                        r.request.method == "POST"
                        and f"/m/{SPACE}/course/order_confirm" in r.url
                    ),
                    timeout=15000,
                ) as resp_info:
                    primary_selector = submit_selectors[0]
                    if primary_selector == "#do_order":
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await page.wait_for_function(
                            """
                            selector => {
                              const el = document.querySelector(selector);
                              if (!el) return false;
                              const style = window.getComputedStyle(el);
                              if (!style) return false;
                              const hidden = style.visibility === 'hidden' || style.display === 'none';
                              const disabled = el.hasAttribute('disabled')
                                || el.getAttribute('aria-disabled') === 'true'
                                || el.classList.contains('disabled');
                              return !hidden && !disabled;
                            }
                            """,
                            arg=primary_selector,
                            timeout=10000,
                        )
                    await page.wait_for_selector(primary_selector, timeout=10000)
                    async with page.expect_dialog() as dlg_info:
                        loc = page.locator(primary_selector)
                        await loc.scroll_into_view_if_needed()
                        try:
                            await loc.click()
                        except Exception:
                            await loc.click(force=True)
                    dlg = await dlg_info.value
                    await dlg.accept()

                resp = await resp_info.value
                ctype = resp.headers.get("content-type", "")
                if "application/json" in ctype:
                    data = await resp.json()
                else:
                    txt = await resp.text()
                    try:
                        data = json.loads(txt)
                    except Exception:
                        data = {"raw": txt}
                if isinstance(data, dict):
                    code = str(data.get("code", "")).strip()
                    msg = str(data.get("msg", ""))
                    if (
                        code in ("0", "1", "200")
                        or data.get("success") is True
                        or "成功" in msg
                    ):
                        ok = True
            except Exception as e:
                print("[W] 响应解析异常：", e)

            if not ok:
                await asyncio.sleep(0.8)
                if re.search(r"/order/detail|/mine/order|success", page.url):
                    ok = True

            if show:
                await page.wait_for_timeout(1500)

            return ok
        finally:
            await browser.close()


async def main_async():
    ap = argparse.ArgumentParser(description="styd.cn 自动预约（Playwright 异步版）")
    ap.add_argument("--date", required=True, help="目标日期，如 2025-10-09")
    ap.add_argument("--shop", required=True, help="shop_id，如 612773420")
    ap.add_argument("--type", default="1", help="type=1（移动端分类）")
    ap.add_argument("--course-id", default=None, help="指定课程ID，跳过筛选，直冲该课程")
    ap.add_argument("--show", action="store_true", help="有头模式")
    ap.add_argument("--tries", type=int, default=SUBMIT_RETRIES, help="下单失败重试次数")
    args = ap.parse_args()

    async with async_playwright() as p:
        browser = await p.webkit.launch(headless=not args.show)
        context = await browser.new_context(
            user_agent=MOBILE_UA,
            viewport={"width": 390, "height": 844},
        )
        await add_cookies(context, RAW_COOKIE)

        target_course_id = args.course_id

        if not target_course_id:
            data = await fetch_search(context, date=args.date, shop_id=args.shop, tp=args.type)
            class_list_html = (data.get("data") or {}).get("class_list") or ""
            if not class_list_html.strip():
                print("[E] search 返回无 class_list，Cookie 失效或风控。")
                print(json.dumps(data, ensure_ascii=False))
                await browser.close()
                return

            courses = parse_courses(class_list_html)
            if not courses:
                print("[E] 未解析到课程节点。页面结构可能更新。")
                await browser.close()
                return

            print("=== 课程列表 ===")
            for c in courses:
                print(f"- {c.title} | {c.time_range} | {c.taken}/{c.total} | {c.status} | {norm_url(c.order_href)}")

            chosen = pick_course(courses)
            if not chosen:
                print("[!] 当日无可预约课程或均不满足策略。")
                await browser.close()
                return

            m = re.search(r"[?&]id=(\d+)", chosen.order_href)
            target_course_id = m.group(1) if m else None
            if not target_course_id:
                print("[E] 无法从 href 提取 course id：", chosen.order_href)
                await browser.close()
                return

            print("\n>>> 目标课程：", chosen.title, chosen.time_range, f"{chosen.taken}/{chosen.total}", chosen.status)
            print(">>> 订单页：", ORDER_URL_TMPL.format(cid=target_course_id))

        # 关闭临时查询浏览器实例，避免与正式下单实例冲突
        await browser.close()

    # 正式下单（用独立实例，干净）
    ok = False
    for i in range(1, max(1, args.tries) + 1):
        print(f"[{i}/{args.tries}] 提交预约 …")
        ok = await book_with_playwright(target_course_id, RAW_COOKIE, show=args.show)
        if ok:
            print("[√] 预约成功。")
            break
        sleep_s = random.uniform(*RETRY_SLEEP)
        print(f"[x] 本次失败，退避 {sleep_s:.2f}s 后重试 …")
        await asyncio.sleep(sleep_s)

    if not ok:
        print("[!] 预约未成功。可能原因：")
        print("  - Cookie 失效/未登录；")
        print("  - 需要先选择附加项（人数/协议/场地）或页面改版；")
        print("  - 浏览器弹窗被拦截或页面改版；")
        print("  - 名额瞬间抢空/风控/验证码。")


if __name__ == "__main__":
    # Windows 下若报 loop policy 问题，可解开下面两行：
    # if sys.platform.startswith("win"):
    #     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main_async())
