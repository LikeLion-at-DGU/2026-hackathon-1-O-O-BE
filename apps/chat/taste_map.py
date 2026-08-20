"""발화를 축으로 바꾸는 사전.

LLM보다 먼저 훑는다. 흔한 표현은 항상 같은 결과가 나오고 비용·지연이 0이다.
모호한 표현("무난한" → classic인지 minimal인지)은 **넣지 않는다.** 사전이 한 값만
주면 틀린 추천이 나가므로, 그런 표현은 LLM 폴백이 문맥을 보고 판단하게 한다.
"""

import logging

from apps.catalog.models import (
    ANALYSIS_AXES,
    Category,
    Color,
    Material,
    PriceBand,
    Silhouette,
    UseCase,
)
from common.llm import LLMUnavailable, complete_json

logger = logging.getLogger(__name__)

# 어휘 → [(축, 값)]. 한 표현이 여러 축을 짚을 수 있다.
# 무드 형용사("차분한"·"화려한"·"클래식")는 여기 없다. 그 말들이 어느 축을
# 가리키는지는 뒤에 붙는 명사가 정하기 때문이다 — "차분한 색"은 color고 "차분한
# 결"은 mood인데, 사전은 단어만 보므로 둘을 구분할 수 없다. 실제로 트리거가
# 손님에게 "차분한 색 쪽이 편하세요?"라고 물어 놓고, 손님이 그대로 따라 말하면
# mood로 받아 색을 하나도 못 걸렀다(추천 1순위가 핑크였다).
#
# 그래서 축이 문맥에 달린 표현은 사전에서 빼고 LLM이 읽게 한다. 축이 단어 자체로
# 확정되는 것(색 이름·용도·물성·크기)만 남긴다 — 이쪽은 호출 없이 끝나는 게 이득이다.
VOCABULARY: dict[str, list[tuple[str, str]]] = {
    "오래 쓸": [("material", Material.GRAINED_LEATHER), ("silhouette", Silhouette.STRUCTURED)],
    "튼튼": [("material", Material.GRAINED_LEATHER)],
    "가벼운": [("material", Material.NYLON)],
    "비 와도": [("material", Material.COATED_CANVAS)],
    "관리 편": [("material", Material.COATED_CANVAS)],
    "출근": [("use_case", UseCase.WORK)],
    "노트북": [("use_case", UseCase.WORK)],
    "데일리": [("use_case", UseCase.DAILY)],
    "매일": [("use_case", UseCase.DAILY)],
    # use_case=travel 상품이 없다. 여행 얘기는 큰 가방(백팩·토트)으로 받는다.
    "여행": [("category", Category.BACKPACK), ("category", Category.TOTE)],
    "모임": [("use_case", UseCase.GOING_OUT)],
    "나들이": [("use_case", UseCase.GOING_OUT)],
    "선물": [("price_band", PriceBand.ENTRY)],
    "부담 없": [("price_band", PriceBand.ENTRY)],
    "입문": [("price_band", PriceBand.ENTRY)],
    "큰 거": [("category", Category.BACKPACK), ("category", Category.TOTE)],
    "많이 들어가": [("category", Category.BACKPACK), ("category", Category.TOTE)],
    # wallet은 취급하지 않는다. 이 매장에서 작은 것은 참·스카프(액세서리)이고,
    # lock은 축당 한 값이라 목록의 첫 값이 잡힌다(services._absorb). 재고가 많은
    # 쪽을 앞에 둬야 crossbody 1건에 갇히지 않는다.
    "작은 거": [("category", Category.ACCESSORY), ("category", Category.CROSSBODY)],
}

# 색 동의어. label("블랙")만 매칭하면 "검정"·"검은색"을 놓친다 — 손님은 셋을 섞어 쓴다.
COLOR_WORDS: dict[str, str] = {
    "검정": Color.BLACK,
    "검은": Color.BLACK,
    "블랙": Color.BLACK,
    "흰": Color.WHITE,
    "하얀": Color.WHITE,
    "화이트": Color.WHITE,
    "베이지": Color.BEIGE,
    "아이보리": Color.BEIGE,
    "네이비": Color.NAVY,
    "남색": Color.NAVY,
    "코냑": Color.COGNAC,
    "갈색": Color.COGNAC,
    "브라운": Color.COGNAC,
    "빨간": Color.RED,
    "빨강": Color.RED,
    "레드": Color.RED,
    "분홍": Color.PINK,
    "핑크": Color.PINK,
    "메탈": Color.METALLIC,
    "은색": Color.METALLIC,
    "금색": Color.METALLIC,
}
NEGATIONS = ("싫", "빼고", "말고", "아니")
# 절 분리는 두 단계다.
#   ① 부정어가 든 "-고"("싫고"·"말고"·"빼고")를 먼저 보호 마커로 끊는다.
#      "고 "를 그냥 분리 기호로 쓰면 "말고"가 쪼개져 부정어가 사라진다
#      ("검은색 말고" → 검은색 선호로 뒤집힘).
#   ② 그다음 남은 "고 "를 분리한다. 이게 없으면 "A는 좋고 B는 싫어요"에서
#      절이 하나로 붙어 문장 전체가 부정이 된다(차분한·검정까지 비선호로 먹힘).
MARK = "\x00"
CLAUSE_BREAKS = {"싫고": f"싫{MARK}", "말고": f"말고{MARK}", "빼고": f"빼고{MARK}"}
SEPARATORS = (MARK, ",", "고 ", "지만", "는데")


def extract(text: str) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(선호, 비선호)를 축 → 값 목록으로 돌려준다.

    한 축에 값이 여럿 올 수 있다 — "빨강도 핑크도 싫어"는 두 값을 모두 빼야 한다.
    부정어가 든 절에서 잡힌 값은 비선호로 넘긴다.
    """
    preferred: dict[str, list[str]] = {}
    rejected: dict[str, list[str]] = {}

    for clause in _split(text):
        negative = any(mark in clause for mark in NEGATIONS)
        target = rejected if negative else preferred
        for axis, value in _match(clause):
            values = target.setdefault(axis, [])
            if value not in values:
                values.append(value)

    # 같은 축이라도 값이 다르면 둘 다 유효하다 — "미니멀은 좋고 볼드는 싫다"는 정합하다.
    # 같은 축 + 같은 값이 양쪽에 걸린 경우만 선호를 남긴다.
    for axis, values in list(rejected.items()):
        keep = [value for value in values if value not in preferred.get(axis, [])]
        if keep:
            rejected[axis] = keep
        else:
            del rejected[axis]
    return preferred, rejected


def _split(text: str) -> list[str]:
    marked = text
    for word, replacement in CLAUSE_BREAKS.items():
        marked = marked.replace(word, replacement)
    parts = [marked]
    for sep in SEPARATORS:
        parts = [chunk for part in parts for chunk in part.split(sep)]
    return [part.strip() for part in parts if part.strip()]


def _match(clause: str) -> list[tuple[str, str]]:
    found = [pair for word, pairs in VOCABULARY.items() if word in clause for pair in pairs]
    found += [("color", value) for word, value in COLOR_WORDS.items() if word in clause]
    return found


# ─────────────────────────── 2차 · LLM 폴백 ───────────────────────────
# 사전이 아무것도 못 잡았을 때만 부른다. "검은색"처럼 축이 단어에 박힌 말은 1차에서
# 끝나고, "차분한 색"·"무해한"처럼 축이 문맥에 달린 표현이 여기로 온다.
# 부를지 말지를 LLM에게 물어보지 않는 이유: 그 판단을 위한 호출이 아끼려는 호출보다
# 비싸다. 사전이 빈손이라는 건 서버가 이미 아는 사실이다.

LLM_SYSTEM_PROMPT = """너는 명품 매장 손님의 한마디를 상품 분류 축으로 옮기는 도구다.

규칙:
- 반드시 아래 "허용 값"에 있는 값만 쓴다. 없는 값을 만들지 않는다.
- 어느 축인지는 형용사가 아니라 뒤에 붙는 말이 정한다.
  ("차분한 색" → color, "차분한 결" → mood, "차분한 무늬" → pattern)
- 손님이 축을 짚어 말했으면 그 축은 반드시 채운다. 여러 값을 아우르는 표현이어도
  가장 대표적인 값 하나를 고른다 — 축 하나에 값 하나만 저장되기 때문이다.
  ("차분한 색"은 블랙·화이트·베이지·네이비·코냑을 아우르지만 하나만 고른다)
- 짚은 축이 없고 근거도 약하면 비운다. 억지로 채우면 손님이 말하지 않은 취향이 확정된다.
- "~는 싫어", "~말고"처럼 부정하는 대상은 avoided에 넣는다."""


def llm_extract(text: str) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """사전이 못 읽은 발화를 축으로 옮긴다. 실패하면 빈손을 돌려준다.

    축 하나 못 잡는 것과 챗봇이 죽는 것은 무게가 다르다. 폴백이 실패해도 답변은
    나가야 하므로 여기서 예외를 삼키고 로그만 남긴다.
    """
    try:
        raw = complete_json(LLM_SYSTEM_PROMPT, _llm_user_prompt(text), schema=_llm_schema())
    except LLMUnavailable:
        logger.info("축 추출 폴백 실패. 사전 결과만 쓴다: %s", text[:40])
        return {}, {}
    return _resolve(raw.get("preferred")), _resolve(raw.get("avoided"))


def _llm_user_prompt(text: str) -> str:
    allowed = "\n".join(f"- {axis}: {', '.join(choices.values)}" for axis, choices in ANALYSIS_AXES.items())
    return f"허용 값:\n{allowed}\n\n손님의 말: {text}"


def _llm_schema() -> dict:
    """축마다 enum을 박는다. 프롬프트 지시와 달리 모델이 벗어날 수 없다."""
    axis_property = {
        "type": "object",
        "properties": {
            axis: {"type": ["string", "null"], "enum": [*choices.values, None]}
            for axis, choices in ANALYSIS_AXES.items()
        },
        "required": list(ANALYSIS_AXES),
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"preferred": axis_property, "avoided": axis_property},
        "required": ["preferred", "avoided"],
        "additionalProperties": False,
    }


def _resolve(raw: object) -> dict[str, list[str]]:
    """스키마를 통과했어도 한 번 더 본다. 모델·스키마가 바뀌면 조용히 새기 때문이다."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for axis, value in raw.items():
        if axis not in ANALYSIS_AXES or not value:
            continue
        if value not in ANALYSIS_AXES[axis].values:
            logger.info("허용 목록에 없는 값을 버렸다: %s=%s", axis, value)
            continue
        out[axis] = [value]
    return out
