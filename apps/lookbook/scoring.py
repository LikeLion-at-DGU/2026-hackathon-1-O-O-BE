"""화보 후보 스코어링. 순수 함수만 둔다 — DB도 LLM도 여기서 부르지 않는다.

**순위도 근거도 LLM에 맡기지 않는다.** AI가 만든 건 `preference_tags` / `avoid_tags`
뿐이고, 그걸 재료로 쓰는 계산은 전부 결정론적이다. 같은 방문은 몇 번을 조회해도
같은 순서가 나와야 한다.
"""

import math
from dataclasses import dataclass, field

# 명세 "점수 산출" 표. 체류시간이 가장 강한 신호라는 기존 원칙 그대로다.
WEIGHT_DWELL = 0.35
WEIGHT_REVISIT = 0.15
WEIGHT_CHAT = 0.15
WEIGHT_PREFER = 0.25
WEIGHT_AVOID = -0.20
WEIGHT_NEW = 0.10

REVISIT_CAP = 3  # 반복 조회는 3회까지만 센다. 그 이상은 관심이 아니라 헤맨 것에 가깝다
DWELL_UNIT_MS = 1000  # log 정규화 단위(초)
DWELL_SATURATION_MS = 120_000  # 2분을 만점으로 본다

CANDIDATE_COUNT = 6  # Figma P01이 6칸 그리드
MAX_SELECT = 1
MIN_SELECT = 1


class ReasonCode:
    """추천 근거. 카드 뱃지로 노출되고 선택 이벤트에도 실린다."""

    MOST_DWELLED = "most_dwelled"
    REVISITED = "revisited"
    CHAT_MENTIONED = "chat_mentioned"
    TASTE_MATCH = "taste_match"
    NEW_ARRIVAL = "new_arrival"
    POPULAR = "popular"  # 후보가 부족해 인기순으로 채운 자리


REASON_TEXTS = {
    ReasonCode.MOST_DWELLED: "오늘 가장 오래 보신 상품",
    ReasonCode.REVISITED: "여러 번 돌아와 보신 상품",
    ReasonCode.CHAT_MENTIONED: "챗봇에서 물어보신 상품",
    ReasonCode.TASTE_MATCH: "선호하신 소재·색과 맞아요",
    ReasonCode.NEW_ARRIVAL: "이번 시즌 신상품",
    ReasonCode.POPULAR: "다른 분들이 많이 보신 상품",
}


@dataclass(frozen=True)
class ProductSignals:
    """한 상품이 이번 방문에서 받은 신호. 계산에 필요한 것만 담는다."""

    dwell_ms: int = 0
    views: int = 0
    chat_mentions: int = 0
    matched_tags: int = 0  # preference_tags와 겹친 축 값 개수
    avoided_tags: int = 0  # avoid_tags와 겹친 축 값 개수
    is_new: bool = False
    popularity: float = 0.0  # 전체 방문 기준 조회 인기도. 자리를 채울 때만 쓴다


@dataclass(frozen=True)
class ScoredCandidate:
    product_id: str
    score: float
    reason_code: str
    contributions: dict[str, float] = field(default_factory=dict)

    @property
    def reason(self) -> str:
        return REASON_TEXTS[self.reason_code]


def score(product_id: str, signals: ProductSignals) -> ScoredCandidate:
    """가중치 x 신호. 가장 크게 기여한 항목이 그대로 추천 근거가 된다."""
    contributions = {
        ReasonCode.MOST_DWELLED: WEIGHT_DWELL * _dwell_ratio(signals.dwell_ms),
        ReasonCode.REVISITED: WEIGHT_REVISIT * _revisit_ratio(signals.views),
        ReasonCode.CHAT_MENTIONED: WEIGHT_CHAT * _mention_ratio(signals.chat_mentions),
        ReasonCode.TASTE_MATCH: WEIGHT_PREFER * _tag_ratio(signals.matched_tags),
        ReasonCode.NEW_ARRIVAL: WEIGHT_NEW * (1.0 if signals.is_new else 0.0),
    }
    penalty = WEIGHT_AVOID * _tag_ratio(signals.avoided_tags)
    total = sum(contributions.values()) + penalty

    return ScoredCandidate(
        product_id=product_id,
        score=round(max(0.0, total), 4),
        reason_code=_reason_of(contributions),
        contributions={key: round(value, 4) for key, value in contributions.items()},
    )


def rank(scored: list[ScoredCandidate], fillers: list[ScoredCandidate]) -> list[ScoredCandidate]:
    """상위 6개. 신호가 있는 후보를 먼저 채우고 모자라면 인기순으로 메운다.

    **items는 정확히 6개여야 한다.** 프론트가 6칸 그리드를 그리므로 빈칸이 생기면
    화면이 깨진다. 대화도 행동도 거의 없는 방문에서도 6개가 나와야 한다.
    """
    ordered = sorted(
        [item for item in scored if item.score > 0],
        key=lambda item: (-item.score, item.product_id),
    )
    if len(ordered) >= CANDIDATE_COUNT:
        return ordered[:CANDIDATE_COUNT]

    chosen = {item.product_id for item in ordered}
    for filler in fillers:
        if len(ordered) >= CANDIDATE_COUNT:
            break
        if filler.product_id in chosen:
            continue
        ordered.append(filler)
        chosen.add(filler.product_id)
    return ordered[:CANDIDATE_COUNT]


def _dwell_ratio(dwell_ms: int) -> float:
    """log 정규화. 2분 본 사람과 20분 본 사람의 차이를 20분 쪽으로 몰지 않는다."""
    if dwell_ms <= 0:
        return 0.0
    return min(1.0, math.log1p(dwell_ms / DWELL_UNIT_MS) / math.log1p(DWELL_SATURATION_MS / DWELL_UNIT_MS))


def _revisit_ratio(views: int) -> float:
    return min(views, REVISIT_CAP) / REVISIT_CAP if views > 0 else 0.0


def _mention_ratio(mentions: int) -> float:
    """한 번이라도 물어봤으면 신호는 이미 분명하다. 횟수로 더 벌리지 않는다."""
    return 1.0 if mentions > 0 else 0.0


def _tag_ratio(matched: int) -> float:
    """겹친 축이 2개면 만점. 8축 중 2개만 맞아도 취향이 통했다고 본다."""
    return min(1.0, matched / 2)


def _reason_of(contributions: dict[str, float]) -> str:
    """가중치 x 점수가 가장 큰 항목에서 기계적으로 정한다."""
    best_code, best_value = max(contributions.items(), key=lambda pair: (pair[1], pair[0]))
    return best_code if best_value > 0 else ReasonCode.POPULAR
