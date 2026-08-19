"""축 기반 추천. 챗봇과 리포트 워커가 같은 스코어링을 쓴다.

챗봇은 axis_score만 쓰고, 리포트는 여기에 인기·신상품 가중을 더한다.
같은 함수를 공유해야 "챗봇이 권한 것과 리포트에 나온 것"이 어긋나지 않는다.
"""

from dataclasses import dataclass

from apps.analysis.taste import AXIS_WEIGHTS, Taste
from apps.catalog.models import Product
from apps.events.models import EventType
from apps.visits.models import Visit

SUGGESTION_LIMIT = 3
# 같은 모델(이름이 같고 색만 다른 상품)을 한 번에 몇 개까지 보여줄지.
# 이름이 겹치는 상품이 60개 중 33개고 한 모델이 6색까지 간다. 걸러내지 않으면
# 추천 세 칸이 한 가방의 색 나열이 된다.
# 1이 아니라 2인 이유: 같은 가방을 여러 번 본 것 자체가 신호라 색 선택지를 함께
# 보여주는 게 맞다. 다만 3이면 한 모델이 세 칸을 다 먹어 원래 문제로 돌아간다.
MAX_PER_MODEL = 2
# 추천 이유로 밝힐 축. price_band는 예산을 근거로 대는 셈이고(축 확인에서 뺀 이유와 같다),
# category는 "백팩 쪽과 맞아요"처럼 자명해서 이유가 되지 못한다. 스코어링에는 남긴다.
REASON_AXES = ("mood", "color", "material", "pattern", "silhouette", "use_case")


@dataclass
class Suggestion:
    """추천 카드 하나. scene_no·product_no가 있어야 손님이 걸어가서 찾을 수 있다."""

    product: Product
    score: float
    reason: str

    def as_dict(self) -> dict:
        return {
            "product_id": self.product.id,
            "name": self.product.name,
            "thumbnail": self.product.thumbnail,
            "price": self.product.price,
            "scene_no": self.product.scene.no,
            "product_no": self.product.no,
            "reason": self.reason,
        }


def axis_score(product: Product, taste: Taste) -> float:
    """상품이 지금까지 읽은 취향에 얼마나 맞는지. 무효 축은 가중치 0이다."""
    total = 0.0
    for axis, weight in AXIS_WEIGHTS.items():
        if axis in taste.ratios and _is_muted(axis, taste):
            continue
        total += weight * taste.score(axis, getattr(product, axis))
    return total


def _is_muted(axis: str, taste: Taste) -> bool:
    """16유형 4축 중 판정 보류된 축은 추천에서도 빼야 한다.

    4축이 아닌 축(material·silhouette·price_band)은 유효성 개념이 없으므로 그대로 쓴다.
    """
    from apps.analysis.taste import CORE_AXES

    return axis in CORE_AXES and axis not in taste.valid_axes


def suggest(visit: Visit, taste: Taste, limit: int = SUGGESTION_LIMIT) -> list[Suggestion]:
    """이번 방문에서 이미 상세를 본 상품은 제외한다 — 새로운 발견을 주려고."""
    seen = set(visit.events.filter(event_type=EventType.PRODUCT_VIEW).values_list("product_id", flat=True))
    candidates = Product.objects.select_related("scene").exclude(id__in=seen)

    scored = [(product, axis_score(product, taste)) for product in candidates]
    scored = [(product, score) for product, score in scored if score > 0]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    return [
        Suggestion(product=product, score=round(score, 2), reason=_reason(product, taste))
        for product, score in _cap_per_model(scored)[:limit]
    ]


def _cap_per_model(scored: list[tuple[Product, float]]) -> list[tuple[Product, float]]:
    """모델당 MAX_PER_MODEL개까지만 남긴다. 점수순으로 들어오므로 상위 색이 살아남는다."""
    counts: dict[str, int] = {}
    kept = []
    for product, score in scored:
        if counts.get(product.name, 0) >= MAX_PER_MODEL:
            continue
        counts[product.name] = counts.get(product.name, 0) + 1
        kept.append((product, score))
    return kept


def _reason(product: Product, taste: Taste) -> str:
    """가장 크게 기여한 축 하나를 근거로 밝힌다. 이유 없는 추천은 신뢰를 못 준다.

    축 이름은 붙이지 않는다 — "형태가 형태가 잡힌 쪽"처럼 겹치고, 손님용 표현만으로
    무슨 축인지 이미 읽힌다("절제된 느낌 쪽", "생활 방수 되는 소재 쪽").
    """
    from apps.chat.wording import say

    contributions = [
        (axis, weight * taste.score(axis, getattr(product, axis)))
        for axis, weight in AXIS_WEIGHTS.items()
        if axis in REASON_AXES and not _is_muted(axis, taste)
    ]
    contributions = [pair for pair in contributions if pair[1] > 0]
    if not contributions:
        return "지금까지 보신 것과 결이 비슷해요"
    axis, _ = max(contributions, key=lambda pair: pair[1])
    return f"{say(getattr(product, axis))} 쪽과 맞아요"
