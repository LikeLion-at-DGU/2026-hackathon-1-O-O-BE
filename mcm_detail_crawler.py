"""
MCM 2차 크롤러 — 상품 상세 페이지에서 소재·사이즈·디자인 서술 수집

mcm_products.csv 의 url 컬럼을 한 줄씩 방문해 상세 정보를 채웁니다.

수집 항목:
    summary       한 줄 요약   ("다이아몬드 모티프 퀼딩 나파가죽 백팩")
    description   디자인 서술   ← '디자이너의 의도'에 가장 가까운 원문
    features      스펙 불릿 전체 (| 구분)
    material      소재         ("나파 레더")
    lining        안감
    dimensions    치수         ("약 20 x 29 x 45 센티미터")
    origin        제조국
    color / size / availability
    images        이미지 주소 전체 (| 구분)
    collection    라인명       (Aren, Pina, Stark ...)

중단되어도 안전합니다. 이미 수집한 상품은 건너뛰고 이어서 진행합니다.

사용법:
    python mcm_detail_crawler.py            # 전체
    python mcm_detail_crawler.py 10         # 앞 10개만 (테스트용)
"""

import csv
import io
import json
import os
import random
import re
import sys
import time

from bs4 import BeautifulSoup

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

IN_CSV = "mcm_products.csv"
OUT_CSV = "mcm_products_detail.csv"

DELAY = (2.0, 4.0)
TIMEOUT = 30
MAX_RETRY = 3

HOME = "https://kr.mcmworldwide.com/ko_KR/home"

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

# 알려진 MCM 라인명 — 상품명 앞부분에서 찾아냅니다
LINES = ["Aren", "Pina", "Stark", "Toni", "Ella", "Tracy", "Ottomar", "Liz",
         "Dessau", "Federlite", "Visetos", "비세토스", "라우렐"]

FIELDS = ["product_id", "name", "price_krw", "collection", "summary", "description",
          "material", "lining", "dimensions", "origin", "color", "size",
          "availability", "features", "images", "url"]


# ── 세션 ──────────────────────────────────────────────
def make_session():
    try:
        from curl_cffi import requests as creq
        s = creq.Session(impersonate="chrome")
        s.headers.update(BROWSER_HEADERS)
        print("엔진: curl_cffi")
        return s
    except ImportError:
        import requests
        s = requests.Session()
        s.headers.update(BROWSER_HEADERS)
        print("엔진: requests  ⚠️  403 가능성 높음 → pip install curl_cffi 권장")
        return s


def fetch(session, url):
    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = session.get(url, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.text
            if r.status_code in (403, 429, 503):
                time.sleep(10 * attempt)
                continue
            return None
        except Exception:
            time.sleep(5 * attempt)
    return None


# ── 파싱 ──────────────────────────────────────────────
def get_jsonld(soup):
    """JSON-LD 구조화 데이터가 있으면 우선 사용 (가장 깨끗함)."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict) and it.get("@type") == "Product":
                return it
    return {}


def find_spec_ul(soup):
    """'바디:' 또는 '제조국'이 든 <li>를 찾아 그 부모 목록을 반환."""
    for li in soup.find_all("li"):
        t = li.get_text(" ", strip=True)
        if t.startswith("바디") or "제조국" in t or "센티미터" in t:
            return li.find_parent(["ul", "ol"])
    return None


def pick(features, *keywords):
    """스펙 불릿 중 키워드가 든 항목을 찾아 값 부분만 반환."""
    for f in features:
        for kw in keywords:
            if kw in f:
                return f.split(":", 1)[1].strip() if ":" in f else f.strip()
    return ""


def parse_detail(html, base_row):
    soup = BeautifulSoup(html, "lxml")
    ld = get_jsonld(soup)
    text = soup.get_text("\n", strip=True)

    # 스펙 불릿
    ul = find_spec_ul(soup)
    features = []
    if ul:
        features = [li.get_text(" ", strip=True) for li in ul.find_all("li")
                    if li.get_text(strip=True)]

    # 서술 문단 — 스펙 목록 바로 앞의 문단들
    summary, description = "", ""
    if ul:
        paras = []
        for sib in ul.find_previous_siblings():
            t = sib.get_text(" ", strip=True)
            if t and len(t) < 600:
                paras.append(t)
            if len(paras) >= 2:
                break
        paras.reverse()
        if len(paras) >= 2:
            summary, description = paras[0], paras[1]
        elif paras:
            description = paras[0]

    if not description:
        description = (ld.get("description") or "").strip()

    # 개별 항목
    material = pick(features, "바디", "소재")
    lining = pick(features, "라이닝", "안감")
    origin = pick(features, "제조국")
    dimensions = ""
    for f in features:
        if "센티미터" in f or re.search(r"\d+\s*[x×]\s*\d+", f):
            dimensions = f.strip()
            break

    # 색상 / 사이즈 / 재고
    color = ""
    m = re.search(r"색상\s*:\s*([^\n]+)", text)
    if m:
        color = m.group(1).strip()[:40]
    size = ""
    m = re.search(r"사이즈\s*:\s*사이즈 선택\s*([^\n]{1,20})", text)
    if m:
        size = m.group(1).strip()

    if "품절" in text:
        availability = "품절"
    elif "소량 재고" in text:
        availability = "소량 재고"
    else:
        availability = "판매중"

    # 이미지 (상품코드가 든 것만)
    pid = base_row.get("product_id") or ""
    images = []
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if pid and pid in src and src not in images:
            images.append(src.split("?")[0])

    # 라인명
    collection = ""
    for ln in LINES:
        if ln.lower() in (base_row.get("name") or "").lower():
            collection = ln
            break

    return {
        "product_id": pid,
        "name": base_row.get("name", ""),
        "price_krw": base_row.get("price_krw", ""),
        "collection": collection,
        "summary": summary,
        "description": description,
        "material": material,
        "lining": lining,
        "dimensions": dimensions,
        "origin": origin,
        "color": color,
        "size": size,
        "availability": availability,
        "features": " | ".join(features),
        "images": " | ".join(images),
        "url": base_row.get("url", ""),
    }


# ── 메인 ──────────────────────────────────────────────
def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None

    if not os.path.exists(IN_CSV):
        print(f"❌ {IN_CSV} 가 없습니다. mcm_crawler2.py 를 먼저 실행하세요.")
        return

    with open(IN_CSV, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r.get("url")]

    # 이어하기: 이미 끝난 상품은 건너뜀
    done = set()
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV, encoding="utf-8-sig") as f:
            done = {r["product_id"] for r in csv.DictReader(f)}
        print(f"이어하기: 이미 {len(done)}개 수집됨")

    todo = [r for r in rows if r.get("product_id") not in done]
    if limit:
        todo = todo[:limit]

    if not todo:
        print("✅ 모두 수집 완료된 상태입니다.")
        return

    print(f"대상 {len(todo)}개 (전체 {len(rows)}개)")
    print(f"예상 소요: 약 {len(todo) * 3 // 60}분 {len(todo) * 3 % 60}초\n")

    session = make_session()
    try:
        session.get(HOME, timeout=TIMEOUT)   # 워밍업
    except Exception:
        pass
    time.sleep(2)

    new_file = not os.path.exists(OUT_CSV)
    ok = failed = 0

    with open(OUT_CSV, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()

        for i, row in enumerate(todo, 1):
            html = fetch(session, row["url"])
            if not html:
                print(f"  [{i}/{len(todo)}] ❌ {row.get('name','')[:24]}")
                failed += 1
                continue

            d = parse_detail(html, row)
            w.writerow(d)
            f.flush()          # 즉시 저장 → 중간에 끊겨도 안전
            ok += 1

            mark = "✓" if d["material"] else "△"
            print(f"  [{i}/{len(todo)}] {mark} {d['name'][:24]:24} "
                  f"{d['material'][:14]:14} {d['dimensions'][:20]}")

            time.sleep(random.uniform(*DELAY))

    print(f"\n✅ 성공 {ok}개 / 실패 {failed}개 → {OUT_CSV}")
    if failed:
        print("   실패분은 다시 실행하면 이어서 시도합니다.")


if __name__ == "__main__":
    main()
