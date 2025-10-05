# -*- coding: utf-8 -*-
"""
styd.cn 自动预约（requests 直发版）
流程：search -> 选课 -> GET 订单页解析隐藏字段 -> POST order_confirm -> 成功校验
注意：Cookie 必须有效（含 PHPSESSID / sass_gym_* 等）
可能需更新：若站点字段名变更或页面结构改版
"""

import re
import time
import random
import argparse
from typing import Dict, Any, List, Optional, Tuple
import urllib.parse as urlparse

import requests
from bs4 import BeautifulSoup

# ===== 配置 =====
BASE = "https://www.styd.cn"
SPACE = "e74abd6e"
SEARCH_API = f"{BASE}/m/{SPACE}/default/search"
ORDER_URL_TMPL = f"{BASE}/m/{SPACE}/course/order?id={{cid}}"
ORDER_CONFIRM = f"{BASE}/m/{SPACE}/course/order_confirm"

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
             "Mobile/15E148 Safari/604.1 Edg/140.0.0.0")

DEFAULT_MEMBER_CARD_ID = "13413533"  # 你的 member_card_id
DEFAULT_CARD_CAT_ID    = "8566400"   # 你的 card_cat_id
DEFAULT_COURSE_ID      = "8225475"   # 兜底 course_id（仅在无法解析时使用）

# 把浏览器里的整串 Cookie 粘进来（同一账号、同一设备）
RAW_COOKIE = r"""acw_tc=0aef82d717595077534875864ee3c54e2b8152570af745e9d511f9ed422776; sass_gym_shop_owner=8d5c1b09e9bcdb787f2b00cd3a730d49b1f1142fa0a7ae9f7f6ac4e329a3a985a%3A2%3A%7Bi%3A0%3Bs%3A19%3A%22sass_gym_shop_owner%22%3Bi%3A1%3Bs%3A8%3A%22e74abd6e%22%3B%7D; Hm_lvt_f4a079b93f8455a44b27c20205cbb8b3=1759507757; HMACCOUNT=DDF29FB8313FFB52; rsource=1320acdbe79dceaac8a47a5bb72c36af3f9a292693e3bf536e960a7c67631e56a%3A2%3A%7Bi%3A0%3Bs%3A7%3A%22rsource%22%3Bi%3A1%3Bs%3A7%3A%22styd.cn%22%3B%7D; PHPSESSID=95hglj7jri5edbittpub3ol2o0; sass_gym_wap=d2500380f34de647cdbee6ac749a9897275e10ee31db81dcb912a3fb28bbc58fa%3A2%3A%7Bi%3A0%3Bs%3A12%3A%22sass_gym_wap%22%3Bi%3A1%3Bs%3A41%3A%222f4f340d142c1cc5c5173fe49fbc1c92%2329356716%22%3B%7D; sass_gym_base=d647e2f758cbb4b43c34e53b57eefc2f55d24ae78e5ab30df0dc8043d5a427cca%3A2%3A%7Bi%3A0%3Bs%3A13%3A%22sass_gym_base%22%3Bi%3A1%3Bs%3A41%3A%222f4f340d142c1cc5c5173fe49fbc1c92%2329356716%22%3B%7D; club_gym_fav_shop_id=dc8d145bd76114fc5213fa9e22c6ac58f7879d80a53a57872cb0d2fd4ef0dabca%3A2%3A%7Bi%3A0%3Bs%3A20%3A%22club_gym_fav_shop_id%22%3Bi%3A1%3Bi%3A612773420%3B%7D; saas_gym_buy_referer=3909ac13f0218caf1d861b024048b94123b89f38fba14ca389d1735ed62f8528a%3A2%3A%7Bi%3A0%3Bs%3A20%3A%22saas_gym_buy_referer%22%3Bi%3A1%3Bs%3A55%3A%22https%3A%2F%2Fwww.styd.cn%2Fm%2Fe74abd6e%2Fcourse%2Forder%3Fid%3D89007443%22%3B%7D; Hm_lpvt_f4a079b93f8455a44b27c20205cbb8b3=1759509539"""

# 你想抢的目标（标题关键字 + 时间段关键字；命中越多优先级越高）
TARGET_TITLE_KEYWORDS = ["游泳馆（午）", "游泳馆"]   # 可改为 ["健身中心（午）", "健身中心"]
TARGET_TIMERANGE_KEYWORDS = ["12:30 - 14:00"]       # 也可加入 "19:00 - 21:00"

# 如果有多张卡，按卡名/卡类型关键字挑一张（可留空：自动选第一张可用卡）
PREFERRED_CARD_KEYWORDS = ["游泳", "次卡"]  # 例：先匹配含“游泳”的卡，再匹配“次卡”
# ===== 配置结束 =====


def sess_with_cookie() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": MOBILE_UA,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/m/{SPACE}/default/index?type=1",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": BASE,
    })
    # 注入 Cookie
    for kv in re.split(r";\s*", RAW_COOKIE.strip()):
        if "=" in kv:
            k, v = kv.split("=", 1)
            s.cookies.set(k, v, domain="www.styd.cn")
    return s


def fetch_search(s: requests.Session, date: str, shop_id: str, tp: str = "1") -> Dict[str, Any]:
    r = s.get(SEARCH_API, params={"date": date, "shop_id": shop_id, "type": tp}, timeout=12)
    r.raise_for_status()
    return r.json()


def parse_courses_from_html(html_ul: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html_ul, "lxml")
    out = []
    for li in soup.select("ul.course_list > li"):
        a = li.select_one("a.course_link")
        if not a:
            continue
        href = a.get("href", "")
        title = (li.select_one(".course_detail .name") or {}).get_text(strip=True)
        timer = (li.select_one(".course_detail .date b") or {}).get_text(strip=True)
        # 人数
        taken, total = 0, 0
        span = li.select_one(".course_thumbs span")
        if span and "/" in span.text:
            try:
                taken, total = [int(x.strip()) for x in span.text.strip().split("/", 1)]
            except:
                pass
        # 状态
        status = "unknown"
        st = li.select_one(".book_status i.course_status")
        if st:
            classes = " ".join(st.get("class", []))
            for k in ["available", "hot", "full", "stop", "queue"]:
                if k in classes:
                    status = k
                    break
        out.append({
            "title": title,
            "time": timer,
            "taken": taken,
            "total": total,
            "status": status,
            "href": href
        })
    return out


def score_course(c: Dict[str, Any]) -> Tuple[int, int, float]:
    kw_rank = min([i for i, kw in enumerate(TARGET_TITLE_KEYWORDS) if kw in c["title"]] or [999])
    t_rank = min([i for i, kw in enumerate(TARGET_TIMERANGE_KEYWORDS) if kw in c["time"]] or [999])
    ratio = (c["taken"] / c["total"]) if c["total"] else 1.0
    return kw_rank, t_rank, ratio


def pick_target(courses: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    pool = [c for c in courses if c["status"] in ("available", "hot", "queue")]
    if not pool:
        return None
    pool.sort(key=score_course)
    return pool[0]


def norm_url(href: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return BASE + href
    return BASE + "/" + href


def extract_hidden_fields(order_html: str) -> Dict[str, str]:
    """
    从订单页解析所有隐藏字段与潜在 script 变量。
    不能猜字段名：原样拿就对了。
    """
    soup = BeautifulSoup(order_html, "lxml")
    fields: Dict[str, str] = {}

    # 1) hidden inputs
    for inp in soup.select("input[type='hidden'][name]"):
        name = inp.get("name")
        val = inp.get("value", "")
        if name:
            fields[name] = val

    # 2) select / option 之类（人数/卡）
    # 如果页面用 select 提供人数或卡，可尝试拿默认选中的值
    for sel in soup.select("select[name]"):
        name = sel.get("name")
        opt = sel.select_one("option[selected]") or sel.select_one("option")
        if name and opt:
            fields.setdefault(name, opt.get("value", ""))

    # 3) 常见表单键的兜底：note/quantity 等
    fields.setdefault("note", "")
    fields.setdefault("quantity", fields.get("quantity") or "1")
    fields.setdefault("is_waiting", fields.get("is_waiting") or "")

    return fields


def choose_card(fields: Dict[str, str], html: str) -> Dict[str, str]:
    """
    如果页面上存在多张卡，常见做法是：
    - 有一组 .card-item 或 radio[name=member_card_id]
    我们尽力在 HTML 里找到卡列表并按关键字选择。
    若找不到，保持订单页默认（通常后端会按默认卡扣除）。
    """
    soup = BeautifulSoup(html, "lxml")

    # radio 场景
    radios = soup.select("input[type='radio'][name='member_card_id']")
    if radios:
        def card_score(label_text: str) -> int:
            text = label_text or ""
            for i, kw in enumerate(PREFERRED_CARD_KEYWORDS):
                if kw in text:
                    return i
            return 999

        best_id, best_score = None, 999
        for r in radios:
            cid = r.get("value", "")
            # 找 label 文本
            label_txt = ""
            lab = soup.select_one(f"label[for='{r.get('id','')}']")
            if lab:
                label_txt = lab.get_text(strip=True)
            # 也可能在父节点
            if not label_txt:
                label_txt = r.find_parent().get_text(" ", strip=True) if r.find_parent() else ""

            sc = card_score(label_txt)
            if sc < best_score:
                best_id, best_score = cid, sc

        if best_id:
            fields["member_card_id"] = best_id

    # card_cat_id 通常和卡绑定；若没解析到，保留原值
    return fields


def post_order_confirm(s: requests.Session, referer: str, payload: Dict[str, str]) -> requests.Response:
    headers = {
        "User-Agent": MOBILE_UA,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": BASE,
        "Referer": referer,
    }
    # 直接表单提交
    last_resp = None
    for attempt in range(2):
        r = s.post(ORDER_CONFIRM, data=payload, headers=headers, timeout=10)
        last_resp = r
        retry = False
        if "系统繁忙" in r.text:
            retry = True
        else:
            try:
                data = r.json()
                if data.get("code") == -1:
                    retry = True
            except ValueError:
                pass
        if not retry or attempt == 1:
            break
        time.sleep(0.2)
    return last_resp
def fetch_cards_from_user_card(s: requests.Session) -> list[dict]:
    """从 我的卡 页面解析可用卡，返回 [{name, member_card_id, card_cat_id}]"""
    url = f"{BASE}/m/{SPACE}/user/card"
    r = get_html_with_browser_headers(s, url, referer=f"{BASE}/m/{SPACE}/default/index?type=1")
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    cards = []
    for li in soup.select(".user_card ul.card_list > li"):
        name = (li.select_one(".card_overview .name p") or {}).get_text(strip=True)
        a = li.select_one(".card_overview .charge a.charge_card[href]")
        if not a:
            continue
        href = a.get("href", "")
        q = urlparse.urlparse(href).query
        qs = dict(urlparse.parse_qsl(q))
        member_card_id = qs.get("member_card_id")
        card_cat_id = qs.get("id")  # 这个 id 就是 card_cat_id
        if member_card_id and card_cat_id:
            cards.append({
                "name": name or "",
                "member_card_id": str(member_card_id),
                "card_cat_id": str(card_cat_id),
            })
    return cards

def pick_card_by_keywords(cards: list[dict], keywords: list[str]) -> dict | None:
    """按关键字挑卡；匹配不到就返回第一张"""
    if not cards:
        return None
    def score(c):
        nm = c.get("name", "")
        for i, kw in enumerate(keywords):
            if kw in nm:
                return i
        return 999
    cards_sorted = sorted(cards, key=score)
    return cards_sorted[0]

# ---- 新增一个工具函数（放到文件上方任意位置）----
def get_html_with_browser_headers(s: requests.Session, url: str, referer: str) -> requests.Response:
    """用浏览器风格的请求头抓取 HTML 页面，避免带上 Session 里全局的 X-Requested-With。"""
    html_headers = {
        "User-Agent": MOBILE_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": referer,
        "Upgrade-Insecure-Requests": "1",
        # 可选：这三行让服务器更像“正常页面导航”，有些站点会看
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
    }
    # 不用 s.get，避免 session.headers 里残留的 X-Requested-With；但要把 Cookie 带上
    r = requests.get(
        url,
        headers=html_headers,
        cookies=s.cookies.get_dict(),
        timeout=12,
        allow_redirects=True,   # 跟随 302
    )
    return r


def run_once(date: str, shop_id: str) -> bool:
    s = sess_with_cookie()
    data = fetch_search(s, date=date, shop_id=shop_id, tp="1")
    class_list_html = (data.get("data") or {}).get("class_list") or ""
    if not class_list_html.strip():
        print("[E] search 没拿到 class_list，Cookie 失效或风控。")
        return False

    courses = parse_courses_from_html(class_list_html)
    for c in courses:
        print(f"- {c['title']} | {c['time']} | {c['taken']}/{c['total']} | {c['status']} | {norm_url(c['href'])}")

    target = pick_target(courses)
    if not target:
        print("[!] 没有可预约的目标。")
        return False

    print("\n>>> 目标：", target["title"], target["time"], f"{target['taken']}/{target['total']}", target["status"])
    order_url = norm_url(target["href"])
    print(">>> 订单页：", order_url)

    # 从 href 提取 class_id
    m = re.search(r"[?&]id=(\d+)", order_url)
    class_id = m.group(1) if m else ""
    if not class_id:
        print("[E] 订单链接无 id。")
        return False

    # 新代码（纯浏览器头，允许重定向，并做登录判定）
    referer = f"{BASE}/m/{SPACE}/default/index?type=1"
    r = get_html_with_browser_headers(s, order_url, referer)

    # 调试：看看是否发生了重定向
    if r.history:
        print("[i] redirects:",
              " -> ".join([h.headers.get("Location", h.url) for h in r.history if hasattr(h, "headers")] + [r.url]))

    # 被踢到登录/首页的判定（按站点文案自定义）
    if r.status_code != 200:
        print("[E] 订单页拉取失败：", r.status_code)
        return False
    if any(key in r.url for key in ("/login", "/passport", "/default/index")) and "course/order" not in r.url:
        print("[E] 看起来被重定向了，可能 Cookie 失效或风控。当前URL:", r.url)
        return False
    if any(x in r.text for x in ("请先登录", "登录后访问", "手机号", "验证码")):
        print("[E] 页面提示需要登录，Cookie 失效。")
        return False

    fields = extract_hidden_fields(r.text)
    # 确保关键字段存在/校正
    fields["class_id"] = fields.get("class_id") or class_id

    if not fields.get("course_id"):
        m = re.search(r'name=["\']course_id["\']\s+value=["\'](\d+)["\']', r.text)
        if m:
            fields["course_id"] = m.group(1)
    if not fields.get("course_id"):
        m = re.search(r'["\']course_id["\']\s*[:=]\s*["\']?(\d+)["\']?', r.text)
        if m:
            fields["course_id"] = m.group(1)
    if not fields.get("course_id") and DEFAULT_COURSE_ID:
        fields["course_id"] = DEFAULT_COURSE_ID

    # 部分站点把 course_id 写在隐藏域或 script 里；如果没拿到，就用你提供的上次值兜底（不推荐长期依赖）
    if not fields.get("course_id"):
        # 尝试在脚本里搜 course_id
        m2 = re.search(r'course_id"\s*[:=]\s*"?(?P<v>\d+)"?', r.text)
        if m2:
            fields["course_id"] = m2.group("v")

    # —— 自动获取我的卡 ——
    if not fields.get("member_card_id") or not fields.get("card_cat_id"):
        try:
            cards = fetch_cards_from_user_card(s)
            chosen = pick_card_by_keywords(cards, PREFERRED_CARD_KEYWORDS or ["游泳", "健身", "次卡"])
            if chosen:
                fields.setdefault("member_card_id", chosen["member_card_id"])
                fields.setdefault("card_cat_id", chosen["card_cat_id"])
            else:
                print("[W] 我的卡列表为空，可能未登录或无可用卡。")
        except Exception as e:
            print("[W] 解析我的卡失败：", e)

    # 若有多卡，按关键字选一张
    fields = choose_card(fields, r.text)

    need = ("member_card_id", "card_cat_id", "course_id", "class_id")
    print("[payload]", {k: fields.get(k) for k in need})
    missing = [k for k in need if not fields.get(k)]
    if missing:
        print("[E] Missing critical fields:", missing)
        return False

    # 最后再兜底：必须键（按你抓包的例子）
    for k in ("member_card_id", "card_cat_id", "course_id"):
        if not fields.get(k):
            print(f"[W] 未解析到关键字段 {k}，可能需更新解析规则。字段集：{list(fields.keys())}")

    # 固化你抓到的通用键（不破坏已有值）
    fields.setdefault("time_from_stamp", "0")
    fields.setdefault("time_to_stamp", "0")
    fields.setdefault("quantity", "1")
    fields.setdefault("is_waiting", "")

    # 提交
    resp = post_order_confirm(s, referer=order_url, payload=fields)
    txt_head = resp.text[:300]
    print("[order_confirm] HTTP", resp.status_code)
    print("[resp head]", txt_head.replace("\n", " ")[:300])

    # 有的返回不是 JSON，而是直接渲染成功页或返回“success”的 HTML 片段
    ok = (resp.status_code == 200) and ("success" in resp.url or "/course/success" in resp.text or "成功" in resp.text)
    if not ok:
        # 有些会 302 跳转到 /success；我们手动试探一下
        try:
            r2 = s.get(f"{BASE}/m/{SPACE}/course/success", timeout=6)
            if r2.status_code == 200 and ("成功" in r2.text or "预约成功" in r2.text):
                ok = True
        except Exception:
            pass

    print("[结果]", "成功" if ok else "失败")
    return ok


def main():
    ap = argparse.ArgumentParser(description="styd.cn 自动预约（requests 直发版）")
    ap.add_argument("--date", required=True, help="目标日期，如 2025-10-13")
    ap.add_argument("--shop", required=True, help="shop_id，例如 612773420")
    args = ap.parse_args()

    ok = run_once(date=args.date, shop_id=args.shop)
    if not ok:
        # 提示可能原因
        print("可能原因：字段名变化 / Cookie 失效 / 无可用卡 / 名额被抢空 / 站点改版。")


if __name__ == "__main__":
    main()
