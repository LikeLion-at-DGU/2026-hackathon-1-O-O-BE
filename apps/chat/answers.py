"""가설 응답 처리. 손님이 버튼을 누른 결과를 좌표에 반영한다.

`맞아요`는 즉시 물건으로 착지시킨다 — 확인의 대가로 새 물건을 받아야 손님이
왜 답했는지 안다. `아니에요`는 트리거 종류에 따라 다르게 처리한다.
"""

import logging
import re
from dataclasses import dataclass

from apps.analysis import recommend
from apps.analysis import taste as taste_module
from apps.analysis.recommend import Suggestion
from apps.analysis.taste import ALL_AXES, CAMPS, profile_of
from apps.catalog.models import Color, Product
from apps.chat.models import ChatLog, Role
from apps.chat.wording import say, say_camp
from apps.visits.models import Visit
from common.llm import LLMUnavailable, complete_json

logger = logging.getLogger(__name__)

AXIS_DENY_RATE = 0.6  # 축 확인 `아니에요` — "싫다"가 아니라 "그게 이유는 아니다"
AVOID_RATE = 1.0  # 회피형 `맞아요` · 발화 부정 — 확정
CONTRAST_ATTRIBUTABLE = 3  # 두 상품의 축 차이가 이 이하면 갈린 축을 특정할 수 있다
# 손님이 먼저 인지하는 순서. 대비 2택에서 어느 축이 갈렸는지 고를 때 쓴다.
CONTRAST_PRIORITY = ("color", "mood", "material", "pattern", "silhouette", "use_case")
# 진영 대표값. 2택 버튼(`use_daily` 등)은 값 하나로 진영 전체를 lock한다.
CAMP_OPTIONS = {
    "use_daily": ("use_case", "D"),
    "use_special": ("use_case", "S"),
    "color_neutral": ("color", "N"),
    "color_vivid": ("color", "V"),
}


@dataclass
class Outcome:
    """응답 처리 결과. 그대로 API 응답이 된다."""

    messages: list[ChatLog]
    suggestions: list[Suggestion]
    completion: float


def apply(visit: Visit, action_type: str, product: Product | None, option: str) -> Outcome:
    profile = profile_of(visit)
    vector = dict(profile.vector)
    pending = vector.get("pending") or {}

    if option == "browse_only":
        vector["browse_only"] = True
        vector["pending"] = None
        return _finish(visit, profile, vector, "알겠어요. 편하게 둘러보세요.", suggest=False)

    if option in CAMP_OPTIONS:
        follow = _apply_camp_option(vector, option)
    elif pending.get("kind") == "contrast":
        follow = _apply_contrast(vector, pending, product)
    elif action_type == "hypothesis_yes":
        follow = _apply_yes(vector, pending)
    else:
        follow = _apply_no(vector, pending)

    vector["pending"] = None
    return _finish(visit, profile, vector, follow.text, suggest=follow.suggest)


@dataclass
class _Follow:
    text: str
    suggest: bool = True


def _apply_camp_option(vector: dict, option: str) -> _Follow:
    axis, camp = CAMP_OPTIONS[option]
    representative = CAMPS[axis][camp][0]
    vector.setdefault("locks", {})[axis] = representative
    _mark_asked(vector, axis)
    return _Follow(f"{say_camp(axis, camp)} 쪽으로 볼게요. 이런 것들이 있어요.")


def _apply_contrast(vector: dict, pending: dict, product: Product | None) -> _Follow:
    """차이 축이 적으면 갈린 축을 특정해 lock한다. 많으면 귀속이 불가능하다."""
    ids = pending.get("products", [])
    winner_id = product.id if product else None
    loser_id = next((pid for pid in ids if pid != winner_id), None)
    if winner_id is None or loser_id is None:
        return _Follow("알겠어요. 이런 것들도 보실래요?")

    vector.setdefault("confirmed", []).append(winner_id)
    winner, loser = Product.objects.get(pk=winner_id), Product.objects.get(pk=loser_id)
    differing = [axis for axis in ALL_AXES if getattr(winner, axis) != getattr(loser, axis)]

    if len(differing) <= CONTRAST_ATTRIBUTABLE:
        axis = next(a for a in CONTRAST_PRIORITY if a in differing)
        value = getattr(winner, axis)
        vector.setdefault("locks", {})[axis] = value
        _mark_asked(vector, axis)
        return _Follow(f"{say(value)} 쪽이시군요. 그럼 이런 것도 보실래요?")

    vector.setdefault("rejected", []).append(loser_id)
    return _Follow("알겠어요. 그럼 이런 것도 보실래요?")


def _apply_yes(vector: dict, pending: dict) -> _Follow:
    kind, axis, value = pending.get("kind"), pending.get("axis"), pending.get("value")

    if kind == "product_confirm":
        for product_id in pending.get("products", []):
            vector.setdefault("confirmed", []).append(product_id)
        return _Follow("그럼 이런 것도 보실래요?")

    if kind == "axis_confirm" and axis and value:
        vector.setdefault("locks", {})[axis] = value
        _mark_asked(vector, axis)
        return _Follow(f"{say(value)} 쪽으로 읽었어요. 이런 것도 맞으실 거예요.")

    if kind == "avoidance" and axis and value:
        vector.setdefault("avoided", {}).setdefault(axis, {})[value] = AVOID_RATE
        _mark_asked(vector, axis)
        return _Follow("알겠어요. 그 쪽은 빼고 보여드릴게요.")

    if kind == "shift" and axis:
        vector.get("locks", {}).pop(axis, None)
        vector.get("spoken", {}).pop(axis, None)
        vector["shift_asked"] = True
        return _Follow("다시 읽어볼게요. 지금 보고 계신 결로 맞춰드릴게요.")

    return _Follow("알겠어요. 이런 것도 보실래요?")


def _apply_no(vector: dict, pending: dict) -> _Follow:
    kind, axis, value = pending.get("kind"), pending.get("axis"), pending.get("value")

    if kind == "product_confirm":
        for product_id in pending.get("products", []):
            vector.setdefault("rejected", []).append(product_id)
        return _Follow("그러셨군요. 무엇이 걸리세요? 채팅으로 알려주세요.", suggest=False)

    if kind == "axis_confirm" and axis and value:
        vector.setdefault("avoided", {}).setdefault(axis, {})[value] = AXIS_DENY_RATE
        _mark_asked(vector, axis)
        return _Follow("그렇다면 뮤즈님의 취향은 어떤 것인지 알려주실 수 있나요?", suggest=False)

    if kind == "avoidance" and axis:
        _mark_asked(vector, axis)
        return _Follow("제가 잘못 봤네요. 계속 둘러보세요.", suggest=False)

    if kind == "shift":
        vector["shift_asked"] = True
        return _Follow("알겠어요. 그대로 맞춰드릴게요.", suggest=False)

    return _Follow("알겠어요.", suggest=False)


def _mark_asked(vector: dict, axis: str) -> None:
    asked = vector.setdefault("asked", [])
    if axis not in asked:
        asked.append(axis)


def _finish(visit: Visit, profile, vector: dict, follow_text: str, *, suggest: bool) -> Outcome:
    profile.vector = vector
    profile.save(update_fields=["vector", "updated_at"])

    taste = taste_module.read(visit)
    suggestions = recommend.suggest(visit, taste) if suggest else []
    content = _speak(follow_text, suggestions) if suggestions else follow_text
    messages = [ChatLog.objects.create(visit=visit, role=Role.ASSISTANT, content=content)]
    return Outcome(messages=messages, suggestions=suggestions, completion=taste.confidence)


SPOKEN_LIMIT = 2  # 문장에 이름을 올리는 상품 수. 셋을 나열하면 문장이 목록이 된다

SPEAK_PROMPT = """당신은 명품 매장 O&O의 큐레이터입니다. 손님이 방금 버튼으로 답했고,
그 답에 맞춰 고른 상품을 한두 문장으로 권하는 차례입니다.

규칙:
- 아래 목록이 곧 권할 수 있는 전부입니다. 목록에 없는 상품·색·진열대 번호는
  존재하지 않습니다. 같은 모델의 다른 색도 목록에 있을 때만 말합니다.
- 상품 이름은 목록에 적힌 철자 그대로, 마지막 낱말까지 옮깁니다. 손님이 진열대에서
  찾아야 하는 이름이라 한글로 옮기거나 줄이거나 어순을 바꾸면 못 찾습니다.
  ("Milla"를 "밀라"로 바꾸지 않습니다)
  이름이 길어도 자르지 않습니다. 끝에 붙은 한 낱말이 상품 종류를 가릅니다 —
  "모노그램 프린트 레더 2D Stark 비세토스 백팩 참"에서 "참"을 떼면
  4번 진열대의 액세서리가 2번 진열대의 백팩이 되어 손님이 엉뚱한 곳으로 갑니다.
- "몇 번 진열대의 무슨 상품" 순서로 말합니다. 손님은 문장만 보고 걸어가야 하므로
  번호가 먼저 나와야 발이 먼저 움직입니다.
- 목록에 둘이 있으면 둘, 하나뿐이면 하나만 말합니다. 수를 채우려고 없는 상품을
  만들지 않습니다. (셋 이상을 나열하면 문장이 목록이 되어 읽히지 않으므로 둘이 상한입니다)
- 색은 굳이 말하지 않습니다. 목록에 **같은 이름이 둘** 있을 때만 색을 붙여 구분합니다.
  이름이 서로 다르면 이름만으로 찾을 수 있습니다.
- 주어진 첫 문장으로 시작하고, 이어서 상품을 말합니다. 전체 2~3문장입니다.
- 손님의 "선택"을 해석하고 손님이라는 "사람"을 단정하지 않습니다.
- 목록의 표기를 그대로 옮기지 않습니다. 슬래시·괄호·상품 번호는 목록을 읽기 쉽게
  적어 둔 것이지 사람이 하는 말이 아닙니다. 풀어서 문장으로 말합니다.
  (O: "그럼 이런 것도 보실래요? 1번 진열대의 Milla 그레인 가죽 토트를 추천드려요.")
  (O: 이름이 같을 때 — "2번 진열대의 Stark 사이드 스터드 비세토스 백팩이
       코냑과 블랙으로 있어요.")
  (X: "1번 진열대 2번 Milla 스페니시 엠보스드 레더 토트 / 블랙과 1번 진열대 3번
       Milla 그레인 가죽 토트 / 코냑을 추천드립니다.")"""


def _speak(lead: str, suggestions: list[Suggestion]) -> str:
    """추천을 문장으로 만든다. 카드가 사라져서 문장이 유일한 전달 수단이 됐다.

    예전에는 "그럼 이런 것도 보실래요?"만 내보내고 상품은 recommendations 배열에
    담았다. 그 배열을 그리던 카드 UI가 빠지면서 **손님 화면에는 가리키는 말만 남고
    가리킬 대상이 없어졌다.**

    LLM을 쓰는 이유는 앞 대화와 이어지는 문장이 필요해서다. 버튼을 누른 직후라
    호출이 하나 붙지만, 실패해도 기존 문구가 그대로 나가므로 답이 끊기지 않는다.
    """
    spoken = suggestions[:SPOKEN_LIMIT]
    try:
        raw = complete_json(SPEAK_PROMPT, _speak_prompt(lead, spoken), schema=_speak_schema())
    except LLMUnavailable:
        logger.info("추천 문장 생성 실패. 기존 문구로 내보낸다: %s", lead)
        return lead
    message = str(raw.get("message") or "").strip()
    if not message or _invented(message, spoken):
        return lead
    return message


def _speak_prompt(lead: str, spoken: list[Suggestion]) -> str:
    lines = [
        f"- {item.product.name} / {item.product.get_color_display()} "
        f"({item.product.scene.no}번 진열대 {item.product.no}번) — {item.reason}"
        for item in spoken
    ]
    # 개수를 문장으로 못 박는다. "두 개까지"만 적어 두면 목록이 하나일 때 모델이
    # 정원으로 읽고 없는 색 변형을 만들어 채운다(6번 중 4번 그랬다).
    header = f"고른 상품 {len(lines)}개 — 이게 전부입니다:"
    return f"첫 문장: {lead}\n\n{header}\n" + "\n".join(lines)


def _invented(message: str, spoken: list[Suggestion]) -> bool:
    """이름을 그대로 말했는지, 없는 색·진열대를 지어냈는지 본다.

    프롬프트로 지시해도 확률적으로 샌다. 명품 매장에서 없는 상품을 안내하는 것은
    즉시 사고이므로 서버가 대조한다. 걸리면 상품 없이 기존 문구만 내보낸다 —
    틀린 안내보다 낫다.

    이름을 문자열 그대로 요구하는 이유는 끝의 한 낱말이 종류를 가르기 때문이다.
    "…비세토스 백팩 참"에서 "참"이 떨어지면 4번 진열대의 액세서리가 2번 진열대의
    백팩이 되어 손님이 엉뚱한 곳으로 걸어간다(지시 전에는 5번 중 5번 떨어졌다).
    """
    missing = [item.product.name for item in spoken if item.product.name not in message]
    if missing:
        logger.info("상품 이름이 훼손돼 폐기했다: %s / %s", missing, message[:60])
        return True
    allowed_colors = {item.product.get_color_display() for item in spoken}
    if any(color.label in message and color.label not in allowed_colors for color in Color):
        logger.info("목록에 없는 색을 말해 폐기했다: %s", message[:60])
        return True
    allowed_scenes = {str(item.product.scene.no) for item in spoken}
    said = set(re.findall(r"(\d+)번 진열대", message))
    if said - allowed_scenes:
        logger.info("목록에 없는 진열대를 말해 폐기했다: %s", message[:60])
        return True
    return False


def _speak_schema() -> dict:
    return {
        "type": "object",
        "properties": {"message": {"type": "string"}},
        "required": ["message"],
        "additionalProperties": False,
    }
