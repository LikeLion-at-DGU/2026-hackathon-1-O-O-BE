"""
403 진단 스크립트 — 어떤 접근 방식이 통하는지 찾아냅니다.

세 가지를 순서대로 시도합니다:
  A. requests + 완전한 브라우저 헤더 + 쿠키 워밍업
  B. curl_cffi (브라우저 TLS 지문 흉내)
  C. Playwright (실제 브라우저)

사용법:
    python check_mcm_access.py
"""

import io
import re
import sys
import time

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

LINE = "─" * 58
BASE = "https://kr.mcmworldwide.com"
HOME = BASE + "/ko_KR/home"
CAT = BASE + "/ko_KR/%EA%B0%80%EB%B0%A9/%EB%B0%B1%ED%8C%A9"

# 실제 Chrome이 보내는 헤더 일습
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


def looks_ok(html):
    """상품 페이지를 제대로 받았는지 대략 판정."""
    if not html or len(html) < 20000:
        return False
    # 상품코드 패턴이 여러 개 보이면 진짜 목록 페이지
    return len(re.findall(r"[A-Z]{3}[A-Z0-9]{7,}\.html", html)) >= 3


def count_products(html):
    return len(set(re.findall(r"/([A-Z]{3}[A-Z0-9]{7,})\.html", html)))


def report(name, ok, detail):
    mark = "✅" if ok else "❌"
    print(f"  {mark} {name}: {detail}")
    return ok


print(LINE)
print(" MCM 접속 방식 진단")
print(LINE)

winner = None

# ── A. requests + 헤더 + 워밍업 ────────────────────────
print("\n[A] requests + 브라우저 헤더 + 쿠키 워밍업")
try:
    import requests

    s = requests.Session()
    s.headers.update(BROWSER_HEADERS)

    # 1) 먼저 홈페이지를 방문해 쿠키를 받는다 (사람의 동선 흉내)
    r0 = s.get(HOME, timeout=30)
    print(f"      홈 방문     : HTTP {r0.status_code}, 쿠키 {len(s.cookies)}개")

    time.sleep(2)

    # 2) Referer를 붙여 카테고리로 '이동'
    h = {"Referer": HOME, "Sec-Fetch-Site": "same-origin"}
    r1 = s.get(CAT, params={"start": 0, "sz": 12}, headers=h, timeout=30)
    ok = r1.status_code == 200 and looks_ok(r1.text)
    report("결과", ok, f"HTTP {r1.status_code}, {len(r1.text):,}자, "
                       f"상품 {count_products(r1.text)}개")
    if ok:
        winner = "A"
except Exception as e:
    report("결과", False, f"오류: {e}")

# ── B. curl_cffi ─────────────────────────────────────
if not winner:
    print("\n[B] curl_cffi (브라우저 TLS 지문 흉내)")
    try:
        from curl_cffi import requests as creq

        s = creq.Session(impersonate="chrome")
        r0 = s.get(HOME, timeout=30)
        print(f"      홈 방문     : HTTP {r0.status_code}")
        time.sleep(2)
        r1 = s.get(CAT + "?start=0&sz=12", timeout=30)
        ok = r1.status_code == 200 and looks_ok(r1.text)
        report("결과", ok, f"HTTP {r1.status_code}, {len(r1.text):,}자, "
                           f"상품 {count_products(r1.text)}개")
        if ok:
            winner = "B"
    except ImportError:
        report("결과", False, "curl_cffi 미설치 → pip install curl_cffi 후 재실행")
    except Exception as e:
        report("결과", False, f"오류: {e}")

# ── C. Playwright ────────────────────────────────────
if not winner:
    print("\n[C] Playwright (실제 브라우저)")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            page = b.new_page(locale="ko-KR")
            page.goto(CAT + "?start=0&sz=12", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            html = page.content()
            b.close()
        ok = looks_ok(html)
        report("결과", ok, f"{len(html):,}자, 상품 {count_products(html)}개")
        if ok:
            winner = "C"
    except ImportError:
        report("결과", False,
               "playwright 미설치 → pip install playwright && playwright install chromium")
    except Exception as e:
        report("결과", False, f"오류: {e}")

# ── 결론 ─────────────────────────────────────────────
print("\n" + LINE)
if winner == "A":
    print(" ✅ A 방식으로 통과. mcm_crawler2.py 를 그대로 실행하세요.")
    print("    python mcm_crawler2.py")
elif winner == "B":
    print(" ✅ B 방식(curl_cffi)으로 통과.")
    print("    mcm_crawler2.py 가 curl_cffi 를 자동 감지해 사용합니다.")
    print("    python mcm_crawler2.py")
elif winner == "C":
    print(" ✅ C 방식(Playwright)만 통과. 브라우저 자동화가 필요합니다.")
    print("    이 결과를 알려주시면 Playwright 버전 크롤러를 만들어 드립니다.")
else:
    print(" ❌ 세 방식 모두 실패.")
    print("    아직 안 깔린 게 있다면 설치 후 다시 돌려보세요:")
    print("      pip install curl_cffi")
    print("      pip install playwright && playwright install chromium")
    print("    전부 깔았는데도 막히면 출력 전체를 알려주세요.")
print(LINE)