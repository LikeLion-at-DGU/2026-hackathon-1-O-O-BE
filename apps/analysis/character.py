"""⑥ 16유형 매핑. 취향 벡터 → 4축 점수 → 4글자 코드.

**결정론적이어야 한다.** 같은 벡터는 언제 돌려도 같은 코드가 나온다. 그래야
"같은 유형이면 같은 캐릭터 이미지"라는 박제가 성립한다.

축 정의는 `tasks/결정사항.md` §4-3 확정안이다.
"""

from dataclasses import dataclass

from apps.analysis.vector import axis_value_key


@dataclass(frozen=True)
class TasteAxis:
    """대립하는 두 성향 한 쌍. 점수의 부호가 코드 한 글자를 정한다."""

    name: str  # 사람이 읽는 축 이름
    axis: str  # 어느 상품 축을 보는지 (mood / color / ...)
    positive_code: str
    negative_code: str
    positive_label: str
    negative_label: str
    positive_values: tuple[str, ...]
    negative_values: tuple[str, ...]

    @property
    def key(self) -> str:
        """axis_scores의 키. 예: "CT"."""
        return f"{self.positive_code}{self.negative_code}"

    def label_of(self, code: str) -> str:
        return self.positive_label if code == self.positive_code else self.negative_label


TASTE_AXES = (
    TasteAxis(
        name="무드",
        axis="mood",
        positive_code="C",  # Classic
        negative_code="T",  # Trend
        positive_label="클래식",
        negative_label="트렌드",
        positive_values=("classic_heritage", "minimal"),
        negative_values=("y2k_street", "bold_statement"),
    ),
    TasteAxis(
        name="색",
        axis="color",
        positive_code="N",  # Neutral
        negative_code="V",  # Vivid
        positive_label="무채",
        negative_label="비비드",
        positive_values=("black", "white", "beige", "navy"),
        negative_values=("red", "pink", "metallic", "visetos_mix"),
    ),
    TasteAxis(
        name="장식",
        axis="pattern",
        positive_code="P",  # Plain
        negative_code="O",  # Ornate
        positive_label="심플",
        negative_label="장식적",
        positive_values=("solid", "logo_print"),
        negative_values=("visetos_monogram", "studded"),
    ),
    TasteAxis(
        name="용도",
        axis="use_case",
        positive_code="D",  # Daily
        negative_code="S",  # Special
        positive_label="데일리",
        negative_label="스페셜",
        positive_values=("daily", "work"),
        negative_values=("travel", "going_out"),
    ),
)


def score_axes(vector: dict[str, float]) -> dict[str, float]:
    """축마다 (양극 합 - 음극 합)을 -1~1로 정규화한다."""
    return {axis.key: _axis_score(vector, axis) for axis in TASTE_AXES}


def map_type_code(axis_scores: dict[str, float]) -> str:
    """4축 점수를 4글자 코드로. 0점(신호 없음·동점)은 양극으로 보낸다.

    동점을 한쪽으로 고정하는 이유는 결정론 때문이다. 임의로 고르면 같은 데이터가
    다른 캐릭터를 내놓는다.
    """
    return "".join(
        axis.positive_code if axis_scores.get(axis.key, 0.0) >= 0 else axis.negative_code
        for axis in TASTE_AXES
    )


def _axis_score(vector: dict[str, float], axis: TasteAxis) -> float:
    positive = _sum_values(vector, axis.axis, axis.positive_values)
    negative = _sum_values(vector, axis.axis, axis.negative_values)
    total = positive + negative
    if total == 0:
        return 0.0
    return round((positive - negative) / total, 4)


def _sum_values(vector: dict[str, float], axis: str, values: tuple[str, ...]) -> float:
    """음수(대화에서 비선호로 감점된 값)는 0으로 본다. 축 비율 계산이 뒤집히기 때문이다."""
    return sum(max(vector.get(axis_value_key(axis, value), 0.0), 0.0) for value in values)
