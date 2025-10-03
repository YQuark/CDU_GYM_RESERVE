# -*- coding: utf-8 -*-
"""
styd.cn 自动预约脚本
- 步骤：查询 -> 解析 -> 选课 -> 打开订单页 -> 点击预约 -> 结果判定
- 适用：你已登录过并且有有效 Cookie（含 PHPSESSID / sass_gym_* 等）
- 说明：下单动作默认用 Playwright（更稳），查询用 requests（更快）
"""

import re
import sys
import time
import json
import random
import argparse
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple

import requests
from bs4 import BeautifulSoup

# ====== 配置区 ======
BASE = "https://www.styd.cn"
SEARCH_PATH = "/m/e74abd6e/default/search"  # 你的门店空间 e74abd6e
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
             "Mobile/15E148 Safari/604.1 Edg/140.0.0.0")

# 你捕获到的 Cookie（建议直接粘贴你浏览器里“请求标头”的 Cookie 字符串）
RAW_COOKIE = r"""acw_tc=0aef82d717595077534875864ee3c54e2b8152570af745e9d511f9ed422776; sass_gym_shop_owner=8d5c1b09e9bcdb787f2b00cd3a730d49b1f1142fa0a7ae9f7f6ac4e329a3a985a%3A2%3A%7Bi%3A0%3Bs%3A19%3A%22sass_gym_shop_owner%22%3Bi%3A1%3Bs%3A8%3A%22e74abd6e%22%3B%7D; Hm_lvt_f4a079b93f8455a44b27c20205cbb8b3=1759507757; HMACCOUNT=DDF29FB8313FFB52; rsource=1320acdbe79dceaac8a47a5bb72c36af3f9a292693e3bf536e960a7c67631e56a%3A2%3A%7Bi%3A0%3Bs%3A7%3A%22rsource%22%3Bi%3A1%3Bs%3A7%3A%22styd.cn%22%3B%7D; PHPSESSID=95hglj7jri5edbittpub3ol2o0; sass_gym_wap=d2500380f34de647cdbee6ac749a9897275e10ee31db81dcb912a3fb28bbc58fa%3A2%3A%7Bi%3A0%3Bs%3A12%3A%22sass_gym_wap%22%3Bi%3A1%3Bs%3A41%3A%222f4f340d142c1cc5c5173fe49fbc1c92%2329356716%22%3B%7D; sass_gym_base=d647e2f758cbb4b43c34e53b57eefc2f55d24ae78e5ab30df0dc8043d5a427cca%3A2%3A%7Bi%3A0%3Bs%3A13%3A%22sass_gym_base%22%3Bi%3A1%3Bs%3A41%3A%222f4f340d142c1cc5c5173fe49fbc1c92%2329356716%22%3B%7D; club_gym_fav_shop_id=dc8d145bd76114fc5213fa9e22c6ac58f7879d80a53a57872cb0d2fd4ef0dabca%3A2%3A%7Bi%3A0%3Bs%3A20%3A%22club_gym_fav_shop_id%22%3Bi%3A1%3Bi%3A612773420%3B%7D; saas_gym_buy_referer=3909ac13f0218caf1d861b024048b94123b89f38fba14ca389d1735ed62f8528a%3A2%3A%7Bi%3A0%3Bs%3A20%3A%22saas_gym_buy_referer%22%3Bi%3A1%3Bs%3A55%3A%22https%3A%2F%2Fwww.styd.cn%2Fm%2Fe74abd6e%2Fcourse%2Forder%3Fid%3D89007443%22%3B%7D; Hm_lpvt_f4a079b93f8455a44b27c20205cbb8b3=1759509539"""

# 订单页里“点击预约/提交”的按钮选择器（**需要你实际看一次订单页确定**）
# 例如：button:text("立即预约") 或者 'a#submitBtn' 或 '.confirm-btn'
ORDER_SUBMIT_SELECTOR = 'button:has-text("确认预约")'  # 占位：请按实际页面改

# 如果存在确认弹窗（如“确认预约？”），可填写第二次点击
ORDER_DIALOG_CONFIRM_SELECTOR = 'button:has-text("确定")'  # 没有可留空

# 选课策略：优先匹配的关键词（按优先级从高到低）
PREFERRED_KEYWORDS = ["健身中心（午）"]

# 时间窗口过滤（字符串包含即可，留空不过滤）
PREFERRED_TIME_RANGES = []

# 人数上限过滤（报名数/总数）
MAX_OCCUPANCY_RATIO = 0.98  # 98% 以上视为太拥挤（可调）
MAX_ABSOLUTE_TAKEN = None   # 例如 95，超过不抢；None 表示不按绝对人数限制

# 查询重试与下单重试
FETCH_RETRIES = 3
SUBMIT_RETRIES = 2
RETRY_SLEEP = (0.8, 1.6)  # 随机 sleep 区间，减少被风控概率
# ====== 配置区结束 ======


@dataclass
class Course:
    title: str
    time_range: str
    taken: int
    total: int
    status: str        # available/hot/full/stop/queue
    order_href: str    # 订单页链接，可能是相对路径
    raw_li_html: str


def parse_cookie_dict(raw_cookie: str) -> Dict[str, str]:
    pairs = re.split(r";\s*", raw_cookie.strip())
    kv = {}
    for p in pairs:
        if not p:
            continue
        if "=" in p:
            k, v = p.split("=", 1)
            kv[k] = v
    return kv


def request_session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": MOBILE_UA,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": f"{BASE}/m/e74abd6e/default/index?type=1",
        "X-Requested-With": "XMLHttpRequest",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
    })
    # 携带 Cookie
    for k, v in parse_cookie_dict(RAW_COOKIE).items():
        sess.cookies.set(k, v, domain="www.styd.cn")
    return sess


def fetch_search(sess: requests.Session, date: str, shop_id: str, tp: str = "1") -> Dict[str, Any]:
    url = BASE + SEARCH_PATH
    params = {"date": date, "shop_id": shop_id, "type": tp}
    last_err = None
    for i in range(FETCH_RETRIES):
        try:
            r = sess.get(url, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
            last_err = f"HTTP {r.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(random.uniform(*RETRY_SLEEP))
    raise RuntimeError(f"fetch_search 重试失败：{last_err}")


def parse_courses(html_ul: str) -> List[Course]:
    soup = BeautifulSoup(html_ul, "lxml")
    result: List[Course] = []
    for li in soup.select("ul.course_list > li"):
        a = li.select_one("a.course_link")
        if not a:
            continue
        href = a.get("href", "")
        title = (li.select_one(".course_detail .name") or {}).get_text(strip=True)
        time_range = (li.select_one(".course_detail .date b") or {}).get_text(strip=True)

        # 人数：在缩略图 span 里 “X/100”
        span = li.select_one(".course_thumbs span")
        taken, total = 0, 0
        if span and "/" in span.text:
            try:
                taken, total = [int(x.strip()) for x in span.text.strip().split("/", 1)]
            except:
                pass

        # 状态 class 里有 available / full ...
        status_i = li.select_one(".book_status i.course_status")
        status = "unknown"
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


def pick_course(courses: List[Course]) -> Optional[Course]:
    # 过滤掉非可约状态
    pool = [c for c in courses if c.status in ("available", "hot", "queue")]
    if not pool:
        return None

    # 时间与关键词优先
    def score(c: Course) -> Tuple[int, int, float]:
        # 关键词优先级（越小越好）
        kw_rank = min((i for i, kw in enumerate(PREFERRED_KEYWORDS) if kw in c.title), default=999)
        # 时间优先级
        t_rank = min((i for i, tr in enumerate(PREFERRED_TIME_RANGES) if tr in c.time_range), default=999)
        # 拥挤程度（越小越好）
        ratio = (c.taken / c.total) if c.total else 1.0
        return (kw_rank, t_rank, ratio)

    pool.sort(key=score)

    # 拥挤过滤
    for c in pool:
        ratio_ok = (c.taken / c.total) < MAX_OCCUPANCY_RATIO if c.total else True
        abs_ok = (c.taken <= MAX_ABSOLUTE_TAKEN) if (MAX_ABSOLUTE_TAKEN is not None) else True
        if ratio_ok and abs_ok:
            return c
    # 如果都很挤，退而求其次拿第一名
    return pool[0] if pool else None


def norm_url(href: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return BASE + href
    return BASE + "/" + href


def playwright_book(order_url: str, headless: bool = True) -> bool:
    """
    用 Playwright 打开订单页并点击“立即预约”。
    会把 RAW_COOKIE 注入浏览器上下文，继承你的登录态。
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.webkit.launch(headless=headless)  # 移动端站点，用 webkit 更贴近 iOS UA
        context = browser.new_context(
            user_agent=MOBILE_UA,
            viewport={"width": 390, "height": 844},  # iPhone 12 视口
        )
        # 注入 Cookie（域必须匹配）
        cookies = []
        for k, v in parse_cookie_dict(RAW_COOKIE).items():
            cookies.append({
                "name": k, "value": v,
                "domain": "www.styd.cn", "path": "/",
                "httpOnly": False, "secure": True
            })
        context.add_cookies(cookies)
        page = context.new_page()

        # 打开订单页
        page.goto(order_url, wait_until="domcontentloaded", timeout=20000)

        # 这里可选：如果页面需要先选择日期/场地/人数，补充相应点击逻辑
        # 例如：page.click("text=选择日期"); page.click("text=今天")

        # 点击“立即预约”
        try:
            page.wait_for_selector(ORDER_SUBMIT_SELECTOR, timeout=10000)
            page.click(ORDER_SUBMIT_SELECTOR)
        except Exception as e:
            print(f"[E] 未找到预约按钮选择器：{ORDER_SUBMIT_SELECTOR}，请检查。{e}")
            return False

        # 确认弹窗（如有）
        if ORDER_DIALOG_CONFIRM_SELECTOR:
            try:
                page.wait_for_selector(ORDER_DIALOG_CONFIRM_SELECTOR, timeout=5000)
                page.click(ORDER_DIALOG_CONFIRM_SELECTOR)
            except Exception:
                pass

        # 结果判定：监听典型提示
        ok = False
        try:
            # 常见成功提示关键词，可按页面实际改
            page.wait_for_timeout(800)  # 等一会儿
            content = page.content()
            if any(k in content for k in ["预约成功", "提交成功", "预订成功", "已预约"]):
                ok = True
        except Exception:
            pass

        # 也可：检查是否跳转到“我的预约/订单详情”界面
        current_url = page.url
        if re.search(r"/order/detail|/mine/order|success", current_url):
            ok = True

        if not ok:
            # 再粗暴一点：看有没有“已满/爆满/失败”等字样
            content = page.content()
            if any(k in content for k in ["已满", "失败", "异常", "请稍后重试", "爆棚"]):
                ok = False

        if not headless:
            # 留个 3 秒观察
            page.wait_for_timeout(3000)

        browser.close()
        return ok


def main():
    ap = argparse.ArgumentParser(description="styd.cn 自动预约脚本")
    ap.add_argument("--date", required=True, help="目标日期，例如 2025-10-09")
    ap.add_argument("--shop", required=True, help="shop_id，例如 612773420")
    ap.add_argument("--type", default="1", help="type=1（移动端分类）")
    ap.add_argument("--dry", action="store_true", help="仅查询与筛选，不下单")
    ap.add_argument("--show", action="store_true", help="有头模式，便于观察页面点击")
    args = ap.parse_args()

    sess = request_session()
    data = fetch_search(sess, date=args.date, shop_id=args.shop, tp=args.type)

    # 兼容后端返回结构
    class_list_html = (data.get("data") or {}).get("class_list") or ""
    if not class_list_html.strip():
        print("[E] 返回里没有 class_list，可能需要更新 Cookie 或已被风控。")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(1)

    courses = parse_courses(class_list_html)
    if not courses:
        print("[E] 没解析到课程节点。页面结构可能变了。")
        sys.exit(1)

    # 打印一份可读表
    print("=== 课程列表 ===")
    for c in courses:
        print(f"- {c.title} | {c.time_range} | {c.taken}/{c.total} | {c.status} | {norm_url(c.order_href)}")

    target = pick_course(courses)
    if not target:
        print("[!] 没有可预约/符合条件的课程。")
        sys.exit(0)

    print("\n>>> 目标：", target.title, target.time_range, f"{target.taken}/{target.total}", target.status)
    order_url = norm_url(target.order_href)
    print("订单页：", order_url)

    if args.dry:
        print("[DRY RUN] 仅演示，不执行预约。")
        sys.exit(0)

    ok = False
    for i in range(1, SUBMIT_RETRIES + 1):
        print(f"[{i}/{SUBMIT_RETRIES}] 尝试预约 …")
        ok = playwright_book(order_url, headless=(not args.show))
        if ok:
            print("[√] 预约成功。")
            break
        sleep_s = random.uniform(*RETRY_SLEEP)
        print(f"[x] 本次失败，等待 {sleep_s:.2f}s 后重试 …")
        time.sleep(sleep_s)

    if not ok:
        print("[!] 预约未成功。可能原因：")
        print("  - Cookie 失效/未登录；")
        print("  - 需要先选择具体场地/人数/勾选协议；")
        print("  - 页面按钮选择器不匹配（请更新 ORDER_SUBMIT_SELECTOR）；")
        print("  - 被风控或名额瞬间抢空；")
        print("  - 存在验证码（需要人工介入）。")
        sys.exit(2)


if __name__ == "__main__":
    main()
