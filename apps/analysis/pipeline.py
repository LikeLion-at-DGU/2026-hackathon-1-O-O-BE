"""워커 파이프라인 ②~⑤. 전부 순수 함수다 — DB도 LLM도 여기서 부르지 않는다.

명세 기준 이 구간은 10ms 미만이다. 계산 도중 트랜잭션을 열어두면 SQLite가 그
시간만큼 통째로 잠기므로, 계산과 저장을 분리한 것이 이 파일의 존재 이유다.
"""

import math

from apps.analysis import scoring
from apps.analysis.insight import Insight
from apps.analysis.signals import ProductFacts, ScoredProduct, VisitSignals
from apps.analysis.vector import axis_value_key


def compute_interest(signals: VisitSignals) -> dict[str, float]:
    """② 관심도. log 가중합 후 최고점을 1로 정규화한다.

    log를 쓰는 이유는 한 상품만 30번 본 사람이 프로필 전체를 지배하지 않게 하려는
    것이다. 30번이 3번의 10배 관심은 아니다.
    """
    raw = {signal.product_id: _raw_interest(signal) for signal in signals.products}
    peak = max(raw.values(), default=0.0)
    if peak <= 0:
        return {}
    return {product_id: round(value / peak, 4) for product_id, value in raw.items()}


def compute_confidence(signals: VisitSignals) -> float:
    """③ 신호 총량. 데이터가 적을 때 틀린 개인화를 하지 않기 위한 억제 장치.

    약한 신호(단순 조회)에 낮은 상한을, 의도가 분명한 행동(질문)에 비중을 준다.
    """
    parts = (
        (scoring.CONFIDENCE_VIEW_WEIGHT, len(signals.products), scoring.CONFIDENCE_VIEW_TARGET),
        (scoring.CONFIDENCE_DWELL_WEIGHT, signals.total_dwell_ms, scoring.CONFIDENCE_DWELL_TARGET_MS),
        (scoring.CONFIDENCE_QUESTION_WEIGHT, signals.questions, scoring.CONFIDENCE_QUESTION_TARGET),
    )
    total = sum(weight * min(1.0, actual / target) for weight, actual, target in parts)
    return round(min(1.0, total), 4)


def build_vector(
    interest: dict[str, float],
    facts_by_id: dict[str, ProductFacts],
    insight: Insight | None,
) -> dict[str, float]:
    """④ 개별 상품 선호를 속성 선호로 바꾼다.

    "이 백팩이 좋다"는 다음 방문에 못 쓰지만 "블랙·레더·미니멀이 좋다"는 안 본
    상품까지 확장할 수 있다. 대화에서 뽑은 선호는 가산, 비선호는 감점한다.
    """
    vector: dict[str, float] = {}
    for product_id, weight in interest.items():
        facts = facts_by_id.get(product_id)
        if facts is None:
            continue  # 상품이 지워진 경우. 원본 이벤트는 남지만 축을 알 수 없다
        for axis, value in facts.axis_values():
            key = axis_value_key(axis, value)
            vector[key] = round(vector.get(key, 0.0) + weight, 4)

    if insight is not None:
        _apply_insight(vector, insight)
    return _normalize(vector)


def score_products(
    vector: dict[str, float],
    catalog: tuple[ProductFacts, ...],
    viewed_product_ids: frozenset[str],
) -> list[ScoredProduct]:
    """⑤ 전체 상품 스코어링. 개인 취향 75% + 인기 15% + 신상품 10%.

    안 본 상품에 발견 가산을 주는 이유는, 이미 본 것만 다시 보여주는 추천은
    "내가 방금 본 목록"과 다를 게 없기 때문이다.
    """
    scored = [
        ScoredProduct(
            facts=facts,
            score=_total_score(vector, facts, is_viewed=facts.product_id in viewed_product_ids),
            is_viewed=facts.product_id in viewed_product_ids,
        )
        for facts in catalog
    ]
    # 점수가 같으면 상품 id로 정렬해 순서를 고정한다. 리포트는 박제되므로 흔들리면 안 된다.
    return sorted(scored, key=lambda item: (-item.score, item.facts.product_id))


def _raw_interest(signal) -> float:
    return (
        scoring.WEIGHT_VIEW * math.log1p(signal.views)
        + scoring.WEIGHT_DWELL * math.log1p(signal.dwell_ms / scoring.DWELL_UNIT_MS)
        + scoring.WEIGHT_CHAT * math.log1p(signal.chat_mentions)
    )


def _apply_insight(vector: dict[str, float], insight: Insight) -> None:
    for axis, value in insight.preferences:
        key = axis_value_key(axis, value)
        vector[key] = round(vector.get(key, 0.0) + scoring.CHAT_PREFERENCE_BONUS, 4)
    for axis, value in insight.avoids:
        key = axis_value_key(axis, value)
        vector[key] = round(vector.get(key, 0.0) - scoring.CHAT_AVOID_PENALTY, 4)


def _normalize(vector: dict[str, float]) -> dict[str, float]:
    """최대 절댓값을 1로 맞춘다. 방문마다 이벤트 수가 달라 절대값끼리는 비교가 안 된다."""
    peak = max((abs(value) for value in vector.values()), default=0.0)
    if peak <= 0:
        return {}
    return {key: round(value / peak, 4) for key, value in vector.items()}


def _total_score(vector: dict[str, float], facts: ProductFacts, *, is_viewed: bool) -> float:
    personal = _personal_score(vector, facts)
    total = (
        scoring.WEIGHT_PERSONAL * personal
        + scoring.WEIGHT_POPULAR * facts.popularity
        + scoring.WEIGHT_NEW * (1.0 if facts.is_new else 0.0)
    )
    if not is_viewed:
        total += scoring.DISCOVERY_BONUS
    return round(min(1.0, total), 4)


def _personal_score(vector: dict[str, float], facts: ProductFacts) -> float:
    """상품의 축 값들이 취향 벡터에서 얼마나 높은 점수를 받는지. 0~1."""
    axis_values = facts.axis_values()
    if not axis_values:
        return 0.0
    matched = sum(vector.get(axis_value_key(axis, value), 0.0) for axis, value in axis_values)
    return max(0.0, matched / len(axis_values))
