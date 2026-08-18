"""대화에서 취향을 뽑고 리포트 문장을 만든다. 워커에서 유일하게 LLM을 쓰는 곳.

**호출은 1회다.** 취향 추출(③′)과 문장 생성(⑦′)은 같은 대화를 재료로 쓰므로
하나의 JSON으로 함께 받는다 — 비용과 지연이 절반이 된다.

대화가 없는 방문은 호출을 아예 건너뛴다. 행동 데이터만으로도 리포트가 나오고
워커가 즉시 끝난다.
"""

import logging
from dataclasses import dataclass

from apps.catalog.models import ANALYSIS_AXES
from common.llm import LLMUnavailable, complete_json

logger = logging.getLogger(__name__)

# 대화로 인정하는 역할. 클릭이 남긴 user_action만 있는 방문은 "대화 없음"이다.
CONVERSATION_ROLES = frozenset({"user", "assistant"})

SYSTEM_PROMPT = """너는 명품 매장 방문자의 대화를 분석하는 도구다.
아래 대화에서 취향과 구매 심리를 뽑아 JSON 하나로만 답한다.

규칙:
- preference_tags와 avoid_tags에는 반드시 주어진 "허용 태그" 목록에 있는 값만 넣는다. 없는 값을 만들지 않는다.
- 대화에 근거가 없으면 빈 배열로 둔다. 추측해서 채우지 않는다.
- purchase_intent는 0~1 사이 숫자다. 구매 의사가 드러날수록 높다.
- hesitation에는 망설임의 이유를 한국어 단어로 넣는다 (예: 가격, 크기, 관리).
- report_summary는 방문자에게 보여줄 한국어 한 문장이다. 존댓말로 쓴다.

응답 형식:
{"preference_tags": [], "avoid_tags": [], "purchase_intent": 0.0, "hesitation": [], "report_summary": ""}"""


@dataclass(frozen=True)
class Insight:
    """LLM이 뽑아낸 것. 태그는 이미 8개 축 값으로 검증된 상태다."""

    preferences: tuple[tuple[str, str], ...] = ()  # (축, 값)
    avoids: tuple[tuple[str, str], ...] = ()
    purchase_intent: float = 0.0
    hesitation: tuple[str, ...] = ()
    summary: str = ""

    def as_dict(self) -> dict:
        """TasteProfile.insight에 박제할 형태. /admin/chat-insights가 이걸 집계한다."""
        return {
            "preference_tags": [value for _, value in self.preferences],
            "avoid_tags": [value for _, value in self.avoids],
            "purchase_intent": self.purchase_intent,
            "hesitation": list(self.hesitation),
            "report_summary": self.summary,
        }


def extract(conversation: list[tuple[str, str]]) -> Insight | None:
    """대화 → Insight. 대화가 없거나 LLM이 실패하면 None을 준다.

    None이어도 리포트는 나온다. 행동 데이터만으로 계산이 성립하도록 설계했기
    때문에, LLM 장애가 리포트 실패로 번지지 않는다.
    """
    if not _has_conversation(conversation):
        return None

    try:
        raw = complete_json(SYSTEM_PROMPT, _build_user_prompt(conversation))
    except LLMUnavailable as error:
        logger.warning("취향 추출을 건너뛴다: %s", error)
        return None

    return _parse(raw)


def _has_conversation(conversation: list[tuple[str, str]]) -> bool:
    return any(role in CONVERSATION_ROLES for role, _ in conversation)


def _build_user_prompt(conversation: list[tuple[str, str]]) -> str:
    lines = [f"{role}: {content}" for role, content in conversation]
    return f"허용 태그: {', '.join(_allowed_tags())}\n\n대화:\n" + "\n".join(lines)


def _allowed_tags() -> list[str]:
    return [value for choices in ANALYSIS_AXES.values() for value, _ in choices.choices]


def _parse(raw: dict) -> Insight:
    return Insight(
        preferences=_resolve_tags(raw.get("preference_tags")),
        avoids=_resolve_tags(raw.get("avoid_tags")),
        purchase_intent=_clamp_intent(raw.get("purchase_intent")),
        hesitation=tuple(str(item) for item in _as_list(raw.get("hesitation"))),
        summary=str(raw.get("report_summary") or ""),
    )


def _resolve_tags(tags) -> tuple[tuple[str, str], ...]:
    """태그를 (축, 값)으로 바꾼다. 허용 목록 밖의 값은 버린다.

    프롬프트로 제약을 걸어도 LLM은 없는 값을 만들어낼 수 있다. 그대로 벡터에
    더하면 아무 상품과도 매칭되지 않는 유령 키가 쌓인다.
    """
    resolved = []
    for tag in _as_list(tags):
        axis = _axis_of(str(tag))
        if axis is None:
            logger.info("허용 목록에 없는 태그를 버렸다: %s", tag)
            continue
        resolved.append((axis, str(tag)))
    return tuple(resolved)


def _axis_of(value: str) -> str | None:
    for axis, choices in ANALYSIS_AXES.items():
        if value in choices.values:
            return axis
    return None


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _clamp_intent(value) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return 0.0
    return round(min(1.0, max(0.0, float(value))), 2)
