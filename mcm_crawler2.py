"""
MCM 크롤러 v2 — 403 봇 차단 대응판

v1 대비 달라진 점:
  1. 홈페이지를 먼저 방문해 쿠키를 받고 시작 (세션 워밍업)
  2. 실제 Chrome이 보내는 헤더 일습 (Sec-Fetch-*, sec-ch-ua 등)
  3. curl_cffi 가 설치돼 있으면 자동으로 사용 (브라우저 TLS 지문 흉내)
  4. 403을 만나면 더 오래 쉬었다가 재시도

사용법:
    pip install requests beautifulsoup4 lxml
    pip install curl_cffi          # 403이 계속되면 추가 설치
    python mcm_crawler2.py

출력:
    mcm_products.csv
"""

import csv
import io
import random
import re
import sys
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "https://kr.mcmworldwide.com"
HOME = BASE + "/ko_KR/home"

CATEGORIES = [
    ("가방-백팩",       "/ko_KR/%EA%B0%80%EB%B0%A9/%EB%B0%B1%ED%8C%A9"),
    ("가방-토트/쇼퍼",  "/ko_KR/%EA%B0%80%EB%B0%A9/%ED%86%A0%ED%8A%B8%EB%B0%B1-%EC%87%BC%ED%8D%BC%EB%B0%B1"),
    ("가방-숄더/크로스", "/ko_KR/%EA%B0%80%EB%B0%A9/%EC%88%84%EB%8D%94%EB%B0%B1-%ED%81%AC%EB%A1%9C%EC%8A%A4%EB%B0%B1"),
    ("가방-벨트백",     "/ko_KR/%EA%B0%80%EB%B0%A9/%EB%B2%A8%ED%8A%B8%EB%B0%B1"),
    ("가방-미니백",     "/ko_KR/%EA%B0%80%EB%B0%A9/%EB%AF%B8%EB%8B%88%EB%B0%B1"),
    ("트래블-전체",     "/ko_KR/%ED%8A%B8%EB%9E%98%EB%B8%94/%EB%AA%A8%EB%91%90%EB%B3%B4%EA%B8%B0"),
]

PAGE_SIZE = 48
DELAY = (2.0, 4.0)      # v1보다 넉넉하게 — 차단 회피에는 속도 조절이 가장 효과적
TIMEOUT = 30
MAX_RETRY = 3

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8"),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not;A=Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Connection": "keep-alive",
}


# ── 세션 생성: curl_cffi 우선, 없으면 requests ──────────
def make_session():
    try:
        from curl_cffi import requests as creq
        s = creq.Session(impersonate="chrome")
        s.headers.update(BROWSER_HEADERS)
        print("엔진: curl_cffi (브라우저 TLS 지문)")
        return s, "curl_cffi"
    except ImportError:
        import requests
        s = requests.Session()
        s.headers.update(BROWSER_HEADERS)
        print("엔진: requests   (403이 나면 pip install curl_cffi 후 재실행)")
        return s, "requests"


def polite_sleep():
    time.sleep(random.uniform(*DELAY))


def warmup(session):
    """홈페이지를 먼저 방문해 쿠키를 확보합니다."""
    print("세션 워밍업 중...")
    try:
        r = session.get(HOME, timeout=TIMEOUT)
        n = len(getattr(session, "cookies", []) or [])
        print(f"  홈 방문 HTTP {r.status_code}, 쿠키 {n}개")
        polite_sleep()
        return r.status_code == 200
    except Exception as e:
        print(f"  워밍업 실패: {e}")
        return False


def fetch(session, url, params=None):
    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = session.get(url, params=params,
                            headers={"Referer": HOME, "Sec-Fetch-Site": "same-origin"},
                            timeout=TIMEOUT)
            if r.status_code == 200:
                return r.text
            if r.status_code in (403, 429, 503):
                wait = 10 * attempt
                print(f"  HTTP {r.status_code} → {wait}초 대기 후 재시도 ({attempt}/{MAX_RETRY})")
                time.sleep(wait)
                continue
            print(f"  HTTP {r.status_code}")
            return None
        except Exception as e:
            print(f"  요청 실패({attempt}/{MAX_RETRY}): {e}")
            time.sleep(5 * attempt)
    return None


# ── 파싱 (v1과 동일) ──────────────────────────────────
def parse_price(text):
    if not text:
        return None
    d = re.sub(r"[^\d]", "", text)
    return int(d) if d else None


def parse_total_count(soup):
    for sel in [".result-count", ".search-result-count", "[class*='result-count']"]:
        el = soup.select_one(sel)
        if el:
            m = re.search(r"(\d[\d,]*)", el.get_text(" ", strip=True))
            if m:
                return int(m.group(1).replace(",", ""))
    m = re.search(r"(\d[\d,]*)\s*제품", soup.get_text(" ", strip=True))
    return int(m.group(1).replace(",", "")) if m else None


def parse_products(html, category_name):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tile in soup.select(".product-tile, .product, [class*='product-tile']"):
        pid = tile.get("data-pid")
        link = tile.select_one("a[href*='.html']")
        href = link["href"] if link and link.has_attr("href") else None
        if not pid and href:
            m = re.search(r"/([A-Z0-9]{10,})\.html", href)
            pid = m.group(1) if m else None

        name_el = tile.select_one(
            ".pdp-link a, .product-name, .tile-body .link, [class*='product-name']")
        name = name_el.get_text(" ", strip=True) if name_el else None
        if not name and link:
            name = link.get("title") or link.get_text(" ", strip=True)

        pe = tile.select_one(".sales .value, .price .sales, .price")
        price = parse_price(pe.get("content") or pe.get_text(" ", strip=True)) if pe else None

        img = tile.select_one("img")
        img_url = (img.get("data-src") or img.get("src")) if img else None

        if not (pid or name):
            continue
        rows.append({
            "category": category_name,
            "product_id": pid,
            "name": (name or "").strip(),
            "price_krw": price,
            "url": urljoin(BASE, href) if href else None,
            "image": img_url,
        })

    seen, unique = set(), []
    for r in rows:
        k = r["product_id"] or r["name"]
        if k in seen:
            continue
        seen.add(k)
        unique.append(r)
    return unique


def crawl_category(session, name, path):
    url = urljoin(BASE, path)
    print(f"\n▶ {name}")

    html = fetch(session, url, params={"start": 0, "sz": PAGE_SIZE})
    if not html:
        print("  건너뜀 (응답 없음)")
        return []

    total = parse_total_count(BeautifulSoup(html, "lxml"))
    results = parse_products(html, name)
    print(f"  전체 {total if total else '?'}개 / 누적 {len(results)}개")

    start = PAGE_SIZE
    while True:
        if total and start >= total:
            break
        polite_sleep()
        html = fetch(session, url, params={"start": start, "sz": PAGE_SIZE})
        if not html:
            break
        batch = parse_products(html, name)
        known = {r["product_id"] or r["name"] for r in results}
        new = [b for b in batch if (b["product_id"] or b["name"]) not in known]
        if not new:
            break
        results += new
        print(f"  start={start} → 누적 {len(results)}개")
        start += PAGE_SIZE
        if start > 2000:
            break
    return results


def main():
    session, engine = make_session()

    if not warmup(session):
        print("\n⚠️  워밍업 단계에서 이미 막혔습니다.")
        if engine == "requests":
            print("    pip install curl_cffi  후 다시 실행해 보세요.")
        else:
            print("    Playwright 방식이 필요할 수 있습니다. test_access.py 결과를 알려주세요.")

    all_rows = []
    for name, path in CATEGORIES:
        all_rows += crawl_category(session, name, path)
        polite_sleep()

    if not all_rows:
        print("\n❌ 수집된 상품이 없습니다. test_access.py 를 돌려 원인을 확인하세요.")
        return

    out = "mcm_products.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        w.writeheader()
        w.writerows(all_rows)

    no_price = sum(1 for r in all_rows if not r["price_krw"])
    print(f"\n✅ 총 {len(all_rows)}개 → {out}")
    print(f"   가격 결측: {no_price}/{len(all_rows)}")


if __name__ == "__main__":
    main()
