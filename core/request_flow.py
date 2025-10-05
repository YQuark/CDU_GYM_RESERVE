from __future__ import annotations

import re
import time
import urllib.parse as urlparse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from bs4 import BeautifulSoup

BASE = "https://www.styd.cn"
SPACE = "e74abd6e"
SEARCH_API = f"{BASE}/m/{SPACE}/default/search"
ORDER_CONFIRM = f"{BASE}/m/{SPACE}/course/order_confirm"

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
    "Mobile/15E148 Safari/604.1 Edg/140.0.0.0"
)

DEFAULT_MEMBER_CARD_ID = "13413533"
DEFAULT_CARD_CAT_ID = "8566400"
DEFAULT_COURSE_ID = "8225475"

_AVAILABLE_STATUSES = {"available", "hot", "queue"}
_BUSY_KEYWORDS = ("系统繁忙", "稍后再试", "操作频繁", "频繁")
_FULL_KEYWORDS = ("课程已满", "排队", "不在可预约时间", "已满", "名额已满", "约满")
_LOGIN_KEYWORDS = ("请先登录", "登录后访问", "手机号", "验证码")
_CARD_KEYWORDS = ("请选择会员卡", "会员卡", "卡")
_SUCCESS_KEYWORDS = ("成功", "预约成功", "success")


@dataclass
class Course:
    title: str
    time: str
    taken: int
    total: int
    status: str
    href: str


@dataclass
class RunRequest:
    cookie: str
    date: str
    shop_id: str
    title_keywords: Sequence[str]
    time_keywords: Sequence[str]
    strict_match: bool = True
    allow_fallback: bool = True
    preferred_card_keywords: Optional[Sequence[str]] = None
    default_member_card_id: Optional[str] = DEFAULT_MEMBER_CARD_ID
    default_card_cat_id: Optional[str] = DEFAULT_CARD_CAT_ID
    default_course_id: Optional[str] = DEFAULT_COURSE_ID


@dataclass
class RunOutcome:
    success: bool
    reason: str
    http_status: Optional[int]
    code: Optional[int]
    msg: Optional[str]
    req_id: Optional[str]
    course: Optional[Dict[str, str]]
    final_url: Optional[str] = None
    evidence: Optional[str] = None
    raw_response: Optional[str] = None
    retry_recommended: bool = False


def create_session(cookie: str) -> requests.Session:
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": MOBILE_UA,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{BASE}/m/{SPACE}/default/index?type=1",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    cookie = cookie or ""
    for kv in re.split(r";\s*", cookie.strip()):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        sess.cookies.set(k, v, domain="www.styd.cn")
    return sess


def fetch_search(session: requests.Session, date: str, shop_id: str, tp: str = "1") -> Dict[str, Any]:
    response = session.get(
        SEARCH_API,
        params={"date": date, "shop_id": shop_id, "type": tp},
        timeout=12,
    )
    response.raise_for_status()
    return response.json()


def parse_courses_from_html(html_ul: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html_ul or "", "lxml")
    courses: List[Dict[str, Any]] = []
    for li in soup.select("ul.course_list > li"):
        a = li.select_one("a.course_link")
        if not a:
            continue
        href = a.get("href", "")
        title = (li.select_one(".course_detail .name") or {}).get_text(strip=True)
        timer = (li.select_one(".course_detail .date b") or {}).get_text(strip=True)
        taken, total = 0, 0
        span = li.select_one(".course_thumbs span")
        if span and "/" in span.text:
            try:
                taken, total = [int(x.strip()) for x in span.text.strip().split("/", 1)]
            except Exception:
                pass
        status = "unknown"
        status_node = li.select_one(".book_status i.course_status")
        if status_node:
            classes = " ".join(status_node.get("class", []))
            for st in ("available", "hot", "full", "stop", "queue"):
                if st in classes:
                    status = st
                    break
        courses.append(
            {
                "title": title,
                "time": timer,
                "taken": taken,
                "total": total,
                "status": status,
                "href": href,
            }
        )
    return courses


def _keyword_match(value: str, keywords: Sequence[str]) -> bool:
    if not keywords:
        return True
    value = value or ""
    return any(kw in value for kw in keywords)


def _score_course(course: Dict[str, Any], title_keywords: Sequence[str], time_keywords: Sequence[str]) -> Tuple[int, int, float]:
    kw_rank = min(
        (i for i, kw in enumerate(title_keywords) if kw and kw in (course.get("title") or "")),
        default=999,
    )
    time_rank = min(
        (i for i, kw in enumerate(time_keywords) if kw and kw in (course.get("time") or "")),
        default=999,
    )
    total = course.get("total") or 0
    taken = course.get("taken") or 0
    ratio = (taken / total) if total else 1.0
    return kw_rank, time_rank, ratio


def select_course(
    courses: Sequence[Dict[str, Any]],
    title_keywords: Sequence[str],
    time_keywords: Sequence[str],
    strict_match: bool,
    allow_fallback: bool,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    available = [c for c in courses if c.get("status") in _AVAILABLE_STATUSES]
    if not available:
        if courses:
            return None, "COURSE_FULL"
        return None, "NO_MATCH"

    strict_pool = [
        c
        for c in available
        if _keyword_match(c.get("title", ""), title_keywords)
        and _keyword_match(c.get("time", ""), time_keywords)
    ]

    if strict_match:
        if strict_pool:
            candidates = strict_pool
        elif allow_fallback:
            candidates = available
        else:
            return None, "NO_MATCH"
    else:
        candidates = strict_pool or available

    candidates = sorted(
        candidates,
        key=lambda c: _score_course(c, title_keywords, time_keywords),
    )
    return (candidates[0] if candidates else None, None)


def norm_url(href: str) -> str:
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return BASE + href
    return BASE + "/" + href


def get_html_with_browser_headers(session: requests.Session, url: str, referer: str) -> requests.Response:
    headers = {
        "User-Agent": MOBILE_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": referer,
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
    }
    response = requests.get(
        url,
        headers=headers,
        cookies=session.cookies.get_dict(),
        timeout=12,
        allow_redirects=True,
    )
    return response


def extract_hidden_fields(order_html: str) -> Dict[str, str]:
    soup = BeautifulSoup(order_html or "", "lxml")
    fields: Dict[str, str] = {}
    for inp in soup.select("input[type='hidden'][name]"):
        name = inp.get("name")
        if not name:
            continue
        fields[name] = inp.get("value", "")
    for sel in soup.select("select[name]"):
        name = sel.get("name")
        opt = sel.select_one("option[selected]") or sel.select_one("option")
        if name and opt:
            fields.setdefault(name, opt.get("value", ""))
    fields.setdefault("note", "")
    fields.setdefault("quantity", fields.get("quantity") or "1")
    fields.setdefault("is_waiting", fields.get("is_waiting") or "")
    return fields


def fetch_cards_from_user_card(session: requests.Session) -> List[Dict[str, str]]:
    url = f"{BASE}/m/{SPACE}/user/card"
    response = get_html_with_browser_headers(
        session,
        url,
        referer=f"{BASE}/m/{SPACE}/default/index?type=1",
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    cards: List[Dict[str, str]] = []
    for li in soup.select(".user_card ul.card_list > li"):
        name = (li.select_one(".card_overview .name p") or {}).get_text(strip=True)
        a = li.select_one(".card_overview .charge a.charge_card[href]")
        if not a:
            continue
        href = a.get("href", "")
        query = urlparse.urlparse(href).query
        qs = dict(urlparse.parse_qsl(query))
        member_card_id = qs.get("member_card_id")
        card_cat_id = qs.get("id")
        if member_card_id and card_cat_id:
            cards.append(
                {
                    "name": name or "",
                    "member_card_id": str(member_card_id),
                    "card_cat_id": str(card_cat_id),
                }
            )
    return cards


def pick_card_by_keywords(cards: Sequence[Dict[str, str]], keywords: Sequence[str]) -> Optional[Dict[str, str]]:
    if not cards:
        return None

    def score(card: Dict[str, str]) -> int:
        text = card.get("name", "")
        for idx, kw in enumerate(keywords or []):
            if kw and kw in text:
                return idx
        return 999

    return sorted(cards, key=score)[0]


def post_order_confirm(session: requests.Session, referer: str, payload: Dict[str, str]) -> requests.Response:
    headers = {
        "User-Agent": MOBILE_UA,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": BASE,
        "Referer": referer,
    }
    last_response: Optional[requests.Response] = None
    for attempt in range(2):
        response = session.post(
            ORDER_CONFIRM,
            data=payload,
            headers=headers,
            timeout=10,
        )
        last_response = response
        retry = False
        if any(word in response.text for word in _BUSY_KEYWORDS):
            retry = True
        else:
            try:
                data = response.json()
            except ValueError:
                data = None
            if isinstance(data, dict) and data.get("code") == -1:
                retry = True
        if not retry or attempt == 1:
            break
        time.sleep(0.2)
    return last_response  # type: ignore[return-value]


def run_once(request: RunRequest) -> RunOutcome:
    session = create_session(request.cookie)
    try:
        search_data = fetch_search(session, date=request.date, shop_id=request.shop_id, tp="1")
    except requests.HTTPError as exc:  # pragma: no cover - network specific
        status = exc.response.status_code if exc.response else None
        if status in (401, 403):
            reason = "COOKIE_INVALID"
        elif status == 429:
            reason = "RATE_LIMIT"
        else:
            reason = "UNKNOWN"
        return RunOutcome(
            success=False,
            reason=reason,
            http_status=status,
            code=None,
            msg=str(exc),
            req_id=None,
            course=None,
            final_url=None,
            evidence=f"search HTTP error: status={status} err={exc}",
            retry_recommended=(reason == "RATE_LIMIT"),
        )
    except Exception as exc:  # pragma: no cover - network specific
        return RunOutcome(
            success=False,
            reason="UNKNOWN",
            http_status=None,
            code=None,
            msg=str(exc),
            req_id=None,
            course=None,
            final_url=None,
            evidence=f"search exception: {exc}",
        )

    class_list_html = (search_data.get("data") or {}).get("class_list") or ""
    if not class_list_html.strip():
        msg = search_data.get("msg") if isinstance(search_data, dict) else None
        reason = "COOKIE_INVALID"
        if msg and any(word in msg for word in _BUSY_KEYWORDS):
            reason = "RATE_LIMIT"
        return RunOutcome(
            success=False,
            reason=reason,
            http_status=None,
            code=search_data.get("code") if isinstance(search_data, dict) else None,
            msg=msg,
            req_id=None,
            course=None,
            final_url=None,
            evidence=f"search data missing class_list msg={msg}",
            retry_recommended=(reason == "RATE_LIMIT"),
        )

    courses = parse_courses_from_html(class_list_html)
    selected_course, failure_reason = select_course(
        courses,
        title_keywords=request.title_keywords,
        time_keywords=request.time_keywords,
        strict_match=request.strict_match,
        allow_fallback=request.allow_fallback,
    )
    if not selected_course:
        reason = failure_reason or "NO_MATCH"
        msg = "课程未匹配" if reason == "NO_MATCH" else "目标课程不可预约"
        return RunOutcome(
            success=False,
            reason=reason,
            http_status=None,
            code=search_data.get("code") if isinstance(search_data, dict) else None,
            msg=msg,
            req_id=None,
            course=None,
            final_url=None,
            evidence=f"选课失败: reason={reason} strict={request.strict_match} allow_fallback={request.allow_fallback}",
        )

    order_url = norm_url(selected_course.get("href", ""))
    match = re.search(r"[?&]id=(\d+)", order_url)
    class_id = match.group(1) if match else ""

    referer = f"{BASE}/m/{SPACE}/default/index?type=1"
    order_response = get_html_with_browser_headers(session, order_url, referer)
    final_order_url = order_response.url or order_url
    if order_response.status_code != 200:
        return RunOutcome(
            success=False,
            reason="UNKNOWN",
            http_status=order_response.status_code,
            code=None,
            msg="订单页拉取失败",
            req_id=None,
            course=selected_course,
            final_url=final_order_url,
            evidence=f"订单页返回状态码 {order_response.status_code}",
        )
    if any(k in final_order_url for k in ("/login", "/passport")) and "course/order" not in final_order_url:
        return RunOutcome(
            success=False,
            reason="COOKIE_INVALID",
            http_status=order_response.status_code,
            code=None,
            msg="订单页重定向至登录",
            req_id=None,
            course=selected_course,
            final_url=final_order_url,
            evidence=f"订单页被重定向到 {final_order_url}",
        )
    if any(word in order_response.text for word in _LOGIN_KEYWORDS):
        snippet = order_response.text[:120]
        return RunOutcome(
            success=False,
            reason="COOKIE_INVALID",
            http_status=order_response.status_code,
            code=None,
            msg="页面提示需要登录",
            req_id=None,
            course=selected_course,
            final_url=final_order_url,
            evidence=f"订单页提示登录: {snippet}",
        )

    fields = extract_hidden_fields(order_response.text)
    if class_id:
        fields.setdefault("class_id", class_id)

    if not fields.get("course_id") and request.default_course_id:
        for pattern in [
            r'name="course_id"\s+value="(\d+)"',
            r"course_id\"?\s*[:=]\s*\"?(\d+)",
        ]:
            m = re.search(pattern, order_response.text)
            if m:
                fields["course_id"] = m.group(1)
                break
        fields.setdefault("course_id", request.default_course_id)

    if not fields.get("course_id"):
        return RunOutcome(
            success=False,
            reason="COURSE_ID_MISSING",
            http_status=order_response.status_code,
            code=None,
            msg="未解析到 course_id",
            req_id=None,
            course=selected_course,
            final_url=final_order_url,
            evidence="订单页缺少 course_id 字段",
        )

    preferred_keywords = list(request.preferred_card_keywords or [])
    if (not fields.get("member_card_id")) or (not fields.get("card_cat_id")):
        try:
            cards = fetch_cards_from_user_card(session)
        except Exception as exc:  # pragma: no cover - network specific
            cards = []
            last_err = str(exc)
        else:
            last_err = ""
        chosen = pick_card_by_keywords(cards, preferred_keywords)
        if chosen:
            fields.setdefault("member_card_id", chosen.get("member_card_id", ""))
            fields.setdefault("card_cat_id", chosen.get("card_cat_id", ""))
        elif cards:
            first = cards[0]
            fields.setdefault("member_card_id", first.get("member_card_id", ""))
            fields.setdefault("card_cat_id", first.get("card_cat_id", ""))
        elif request.default_member_card_id and request.default_card_cat_id:
            fields.setdefault("member_card_id", request.default_member_card_id)
            fields.setdefault("card_cat_id", request.default_card_cat_id)
        else:
            if not fields.get("member_card_id") or not fields.get("card_cat_id"):
                return RunOutcome(
                    success=False,
                    reason="CARD_MISSING",
                    http_status=order_response.status_code,
                    code=None,
                    msg=last_err or "未找到可用卡",
                    req_id=None,
                    course=selected_course,
                    final_url=final_order_url,
                    evidence="未能解析到 member_card_id/card_cat_id",
                )

    if not fields.get("member_card_id") or not fields.get("card_cat_id"):
        return RunOutcome(
            success=False,
            reason="CARD_MISSING",
            http_status=order_response.status_code,
            code=None,
            msg="缺少卡信息",
            req_id=None,
            course=selected_course,
            final_url=final_order_url,
            evidence="提交订单所需卡信息缺失",
        )

    fields.setdefault("time_from_stamp", "0")
    fields.setdefault("time_to_stamp", "0")
    fields.setdefault("quantity", "1")
    fields.setdefault("is_waiting", "")

    confirm_response = post_order_confirm(session, referer=order_url, payload=fields)
    http_status = confirm_response.status_code
    final_confirm_url = confirm_response.url or order_url
    text_head = confirm_response.text[:300]
    code = None
    msg = None
    req_id = None
    try:
        data = confirm_response.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        code = data.get("code")
        msg = data.get("msg")
        req_id = data.get("req_id")
    else:
        msg = text_head

    success = False
    if isinstance(data, dict) and data.get("code") == 200:
        success = True
    if not success and msg and any(word in msg for word in _SUCCESS_KEYWORDS):
        success = True
    if not success and confirm_response.text and any(
        word in confirm_response.text for word in _SUCCESS_KEYWORDS
    ):
        success = True

    body = confirm_response.text or ""
    evidence = ""
    reason = "OK" if success else "UNKNOWN"
    if success:
        evidence = f"order_confirm成功: code={code} msg={msg}"
    else:
        evidence = f"order_confirm返回: code={code} msg={msg or text_head}"
        if any(k in final_confirm_url for k in ("/login", "/passport")):
            reason = "REDIRECT_LOGIN"
        elif any(word in body for word in _BUSY_KEYWORDS):
            reason = "RATE_LIMIT"
        elif any(word in body for word in _CARD_KEYWORDS):
            reason = "CARD_MISSING"
        elif any(word in body for word in _FULL_KEYWORDS):
            reason = "COURSE_FULL"
        elif any(word in body for word in _LOGIN_KEYWORDS):
            reason = "REDIRECT_LOGIN"
        else:
            reason = "UNKNOWN"

    return RunOutcome(
        success=success,
        reason=reason,
        http_status=http_status,
        code=code,
        msg=msg,
        req_id=req_id,
        course={
            "title": selected_course.get("title", ""),
            "time": selected_course.get("time", ""),
            "href": order_url,
        },
        final_url=final_confirm_url,
        evidence=evidence,
        raw_response=text_head,
        retry_recommended=(reason == "RATE_LIMIT"),
    )
