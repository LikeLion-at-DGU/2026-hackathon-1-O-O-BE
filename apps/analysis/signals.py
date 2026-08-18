"""파이프라인이 주고받는 자료구조.

DB 모델을 파이프라인에 그대로 넘기지 않는다. 순수 함수로 유지해야 테스트가
쉽고, SQLite 쓰기 잠금을 피하려면 계산 구간에 쿼리가 없어야 하기 때문이다.
"""

from dataclasses import dataclass, field

from apps.catalog.models import ANALYSIS_AXES


@dataclass(frozen=True)
class ProductSignal:
    """① 집계 결과 — 이번 방문에서 상품 하나가 받은 관심."""

    product_id: str
    views: int = 0  # 재조회 횟수를 겸한다 (같은 상품을 다시 볼 때마다 쌓인다)
    dwell_ms: int = 0
    saves: int = 0
    chat_mentions: int = 0


@dataclass(frozen=True)
class VisitSignals:
    """한 방문의 행동 전부. ②③④가 이것만 보고 계산한다."""

    products: tuple[ProductSignal, ...] = ()
    scenes_viewed: int = 0
    questions: int = 0

    @property
    def total_dwell_ms(self) -> int:
        return sum(signal.dwell_ms for signal in self.products)

    @property
    def total_saves(self) -> int:
        return sum(signal.saves for signal in self.products)

    @property
    def viewed_product_ids(self) -> frozenset[str]:
        return frozenset(signal.product_id for signal in self.products)


@dataclass(frozen=True)
class ProductFacts:
    """⑤ 스코어링 대상. 8개 축 + 리포트에 박제할 스냅샷을 함께 들고 다닌다.

    스냅샷을 여기 둔 이유는 ⑦단계에서 상품을 다시 조회하지 않기 위해서다.
    """

    product_id: str
    name: str
    thumbnail: str | None
    price: int
    external_url: str
    scene_no: int
    product_no: int
    is_new: bool
    popularity: float  # 0~1. 전체 방문 기준 조회 인기도
    axes: dict[str, str] = field(default_factory=dict)  # {"color": "black", ...}

    def axis_values(self) -> list[tuple[str, str]]:
        return [(axis, self.axes[axis]) for axis in ANALYSIS_AXES if axis in self.axes]


@dataclass(frozen=True)
class ScoredProduct:
    """⑤ 결과. 추천 카드 하나가 되기 직전의 상태."""

    facts: ProductFacts
    score: float
    is_viewed: bool
