"""브랜드가 보는 집계. 사용자 API가 쌓은 같은 이벤트를 그대로 읽는다.

별도 집계 테이블을 두지 않는 이유는 이벤트가 append-only라 언제 계산해도 같은 답이
나오고, 지표 정의가 바뀔 때 과거 데이터를 다시 만들 필요가 없기 때문이다. 상품 수가
60개, 방문이 수백 건인 규모에서는 매 호출 집계가 캐시보다 단순하고 정확하다.
"""

from collections import defaultdict

from django.db.models import Count, Q

from apps.analysis.models import Report, ReportStatus
from apps.catalog.models import Product
from apps.events.models import Event, EventType
from apps.events.services import DWELL_KEY
from apps.lookbook.models import Lookbook, LookbookStatus
from apps.visits.models import Visit

# 퍼널 단계. 앞 단계를 거치지 않고 뒤 단계에 도달할 수 없으므로 순서가 곧 정의다.
FUNNEL_STAGES = (
    ("entered", "입장"),
    ("viewed_product", "상품 조회"),
    ("asked_question", "질문"),
    ("finished", "관람 종료"),
    ("got_report", "리포트 완료"),
    ("made_lookbook", "화보 완성"),
)


def funnel(store_id: str) -> dict:
    """단계별 방문 수와 전환율.

    전환율의 분모는 직전 단계가 아니라 **입장**이다. 직전 단계 대비로 보면 뒤로 갈수록
    수치가 좋아 보여서, 어디서 사람이 빠지는지가 오히려 안 보인다.
    """
    visits = Visit.objects.filter(store_id=store_id)
    entered = visits.count()
    counts = {
        "entered": entered,
        "viewed_product": _visits_with(store_id, EventType.PRODUCT_VIEW),
        "asked_question": _visits_with(store_id, EventType.QUESTION_SUBMIT),
        "finished": visits.filter(ended_at__isnull=False).count(),
        "got_report": Report.objects.filter(visit__store_id=store_id, status=ReportStatus.READY).count(),
        "made_lookbook": Lookbook.objects.filter(
            report__visit__store_id=store_id, status=LookbookStatus.READY
        )
        .values("report__visit")
        .distinct()
        .count(),
    }
    return {
        "store_id": store_id,
        "stages": [
            {
                "key": key,
                "label": label,
                "visits": counts[key],
                "rate": round(counts[key] / entered, 4) if entered else 0.0,
            }
            for key, label in FUNNEL_STAGES
        ],
        # 방치돼 서버가 닫은 방문. 평균 체류·완료율을 볼 때 분모에서 빼야 한다.
        "auto_closed": visits.filter(is_auto_closed=True).count(),
    }


def product_stats(store_id: str) -> list[dict]:
    """상품별 관심 지표. 체류가 긴 순서.

    "오래 봤는데 화보로 안 이어진 상품"을 찾는 것이 이 표의 목적이다. 진열·설명·직원
    개입을 어디에 넣을지가 거기서 나온다.
    """
    dwell = _dwell_by_product(store_id)
    picked = _lookbook_picks(store_id)
    rows = (
        Event.objects.filter(visit__store_id=store_id, product__isnull=False)
        .values("product_id")
        .annotate(
            views=Count("event_id", filter=Q(event_type=EventType.PRODUCT_VIEW)),
            hotspots=Count("event_id", filter=Q(event_type=EventType.HOTSPOT_CLICK)),
            impressions=Count("event_id", filter=Q(event_type=EventType.RECOMMENDATION_IMPRESSION)),
            clicks=Count("event_id", filter=Q(event_type=EventType.RECOMMENDATION_CLICK)),
        )
    )
    products = {
        product.id: product
        for product in Product.objects.filter(scene__store_id=store_id).select_related("scene")
    }

    stats = []
    for row in rows:
        product = products.get(row["product_id"])
        if product is None:
            continue
        impressions = row["impressions"]
        stats.append(
            {
                "product_id": product.id,
                "name": product.name,
                "scene_no": product.scene.no,
                "views": row["views"],
                "dwell_ms": dwell.get(product.id, 0),
                "hotspot_clicks": row["hotspots"],
                "recommendation_impressions": impressions,
                "recommendation_clicks": row["clicks"],
                "click_rate": round(row["clicks"] / impressions, 4) if impressions else 0.0,
                "lookbook_picks": picked.get(product.id, 0),
            }
        )
    return sorted(stats, key=lambda row: (-row["dwell_ms"], row["product_id"]))


def _visits_with(store_id: str, event_type: str) -> int:
    return (
        Event.objects.filter(visit__store_id=store_id, event_type=event_type)
        .values("visit_id")
        .distinct()
        .count()
    )


def _dwell_by_product(store_id: str) -> dict[str, int]:
    """체류는 metadata(JSON) 안에 있어 DB가 더하지 못한다. 파이썬에서 합친다."""
    totals: dict[str, int] = defaultdict(int)
    rows = Event.objects.filter(
        visit__store_id=store_id,
        event_type=EventType.PRODUCT_DWELL,
        product__isnull=False,
    ).values_list("product_id", "metadata")
    for product_id, metadata in rows:
        value = metadata.get(DWELL_KEY, 0)
        if isinstance(value, int) and not isinstance(value, bool):
            totals[product_id] += value
    return totals


def _lookbook_picks(store_id: str) -> dict[str, int]:
    """화보에 담긴 횟수. 상품 id가 JSON 배열이라 여기도 파이썬에서 센다."""
    picks: dict[str, int] = defaultdict(int)
    rows = Lookbook.objects.filter(report__visit__store_id=store_id, status=LookbookStatus.READY).values_list(
        "product_ids", flat=True
    )
    for product_ids in rows:
        for product_id in product_ids or []:
            picks[product_id] += 1
    return picks
