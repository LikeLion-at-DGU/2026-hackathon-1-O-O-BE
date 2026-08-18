"""가설 응답 처리. 손님이 버튼을 누른 결과를 좌표에 반영한다.

`맞아요`는 즉시 물건으로 착지시킨다 — 확인의 대가로 새 물건을 받아야 손님이
왜 답했는지 안다. `아니에요`는 트리거 종류에 따라 다르게 처리한다.
"""

from dataclasses import dataclass

from apps.analysis import recommend
from apps.analysis import taste as taste_module
from apps.analysis.recommend import Suggestion
from apps.analysis.taste import ALL_AXES, CAMPS, profile_of
from apps.catalog.models import Product
from apps.chat.models import ChatLog, Role
from apps.chat.wording import say, say_camp
from apps.visits.models import Visit

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
    messages = [ChatLog.objects.create(visit=visit, role=Role.ASSISTANT, content=follow_text)]
    return Outcome(messages=messages, suggestions=suggestions, completion=taste.confidence)
