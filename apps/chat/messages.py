"""클릭을 말풍선으로 쌓고, 그 기록에서 AI의 문맥을 뽑는다.

O&O의 채팅창은 빈 화면에서 시작하지 않는다. 진열대·상품을 누른 행적이 이미 쌓여
있고, "채팅으로 대화하기"로 넘어가면 서버가 그 기록을 읽어 AI가 지금 어떤 상품
얘기를 하는 중인지 알게 된다. 그래서 사용자는 상품명을 말하지 않아도 된다.
"""

import logging

from django.conf import settings

from apps.analysis.taste import profile_of
from apps.catalog.models import PresetKey, Product, Scene
from apps.chat.models import ActionType, ChatLog, Role
from apps.chat.triggers import Hypothesis
from apps.visits.models import Visit

logger = logging.getLogger(__name__)

PRESET_FALLBACK = "안내 문구가 아직 준비되지 않았습니다."

# 진열대·상품 클릭은 직전과 같으면 말풍선을 새로 쌓지 않는다. 화면이 같은 말풍선으로
# 도배되기 때문이다. 조회 횟수 같은 수치는 POST /events가 따로 남기므로 잃는 게 없다.
# 프리셋은 제외한다 — 같은 걸 다시 물어보는 것 자체가 의미 있는 행동이다.
DEDUPE_TYPES = frozenset({ActionType.SCENE_CLICK, ActionType.PRODUCT_CLICK})


def append_action(
    visit: Visit,
    action_type: str,
    *,
    scene: Scene | None = None,
    product: Product | None = None,
    preset_key: str = "",
) -> tuple[ChatLog, bool]:
    """액션 메시지를 쌓고 (대표 메시지, 새로 쌓았는지)를 돌려준다.

    프리셋 열람은 두 줄이 된다 — 누른 버튼(user_action)과 미리 작성된 답변(preset).
    답변만 남기면 타임라인이 "갑자기 가격 얘기가 나오는" 것처럼 읽힌다.
    """
    content = _render(action_type, scene, product, preset_key)

    if action_type in DEDUPE_TYPES and _is_repeat(visit, content):
        return _last_action(visit), False

    action = ChatLog.objects.create(
        visit=visit, role=Role.USER_ACTION, content=content, scene=scene, product=product
    )
    if action_type != ActionType.PRESET_VIEW:
        return action, True

    answer = ChatLog.objects.create(
        visit=visit,
        role=Role.PRESET,
        content=_preset_answer(product, preset_key),
        scene=scene,
        product=product,
    )
    return answer, True


def timeline(visit: Visit) -> list[ChatLog]:
    """타임라인 전량. 페이지네이션하지 않는다 — 화면과 AI 문맥이 모두 전체를 본다."""
    messages = visit.chat_logs.order_by("-created_at")[: settings.CHAT_TIMELINE_LIMIT]
    return list(reversed(messages))


def current_context(visit: Visit) -> dict:
    """가장 최근에 클릭한 진열대·상품. POST /chat이 이걸 기본 문맥으로 쓴다."""
    latest_product = (
        visit.chat_logs.filter(product__isnull=False)
        .select_related("product")
        .order_by("-created_at")
        .first()
    )
    latest_scene = visit.chat_logs.filter(scene__isnull=False).order_by("-created_at").first()

    product_id = latest_product.product_id if latest_product else None
    scene_id = latest_scene.scene_id if latest_scene else None
    if scene_id is None and latest_product is not None:
        # 상품만 클릭했어도 챗봇이 "3번 진열대 2번 상품"으로 안내할 수 있어야 한다.
        scene_id = latest_product.product.scene_id

    return {"scene_id": scene_id, "product_id": product_id}


def _render(action_type: str, scene: Scene | None, product: Product | None, preset_key: str) -> str:
    """표시 문구는 서버가 만든다. 클라이언트가 보낸 문장을 그대로 AI 프롬프트에 넣을 수 없다."""
    if action_type == ActionType.SCENE_CLICK:
        return f"{scene.no}번 진열대 클릭"
    if action_type == ActionType.PRODUCT_CLICK:
        return f"{product.name} 상품 클릭"
    return PresetKey(preset_key).label


def _preset_answer(product: Product, preset_key: str) -> str:
    answer = product.preset_answers.get(preset_key)
    if not answer:
        logger.warning("프리셋 문구 누락: product=%s key=%s", product.id, preset_key)
        return PRESET_FALLBACK
    return answer


def _is_repeat(visit: Visit, content: str) -> bool:
    last = _last_action(visit)
    return last is not None and last.content == content


def _last_action(visit: Visit) -> ChatLog | None:
    return visit.chat_logs.filter(role=Role.USER_ACTION).order_by("-created_at").first()


def append_hypothesis(visit: Visit, hypothesis: Hypothesis) -> ChatLog:
    """가설을 말풍선으로 넣고, 예산·쿨다운 상태를 갱신한다.

    가설의 종류·축·대상 상품을 `TasteProfile.vector["pending"]`에 저장한다.
    응답(`맞아요`)이 왔을 때 그게 무슨 가설이었는지 알아야 좌표에 반영할 수 있고,
    `chat_logs`에는 문구만 남아 복원이 불가능하다.
    """
    from apps.events.models import EventType

    message = ChatLog.objects.create(visit=visit, role=Role.ASSISTANT, content=hypothesis.message)
    profile = profile_of(visit)
    vector = dict(profile.vector)

    vector["pending"] = {
        "message_id": message.message_id,
        "kind": hypothesis.kind,
        "axis": hypothesis.axis,
        "value": hypothesis.asked_value,
        "products": [product.id for product in hypothesis.products],
        "options": hypothesis.options,
    }
    vector["confirm_count"] = vector.get("confirm_count", 0) + 1
    vector["asked_at_views"] = visit.events.filter(event_type=EventType.PRODUCT_VIEW).count()

    if hypothesis.kind == "axis_confirm":
        vector["axis_asked"] = True
    elif hypothesis.kind in ("product_confirm", "contrast", "avoidance"):
        vector["general_count"] = vector.get("general_count", 0) + 1

    if hypothesis.kind == "contrast":
        vector["contrast_asked"] = True
    elif hypothesis.kind == "quick_browse":
        vector["quick_asked"] = True
    elif hypothesis.kind == "shift":
        vector["shift_asked"] = True

    if hypothesis.kind == "product_confirm":
        asked = vector.setdefault("asked_products", [])
        asked += [product.id for product in hypothesis.products if product.id not in asked]

    profile.vector = vector
    profile.save(update_fields=["vector", "updated_at"])
    return message


def pending_action(visit: Visit) -> dict | None:
    """지금 답해야 할 버튼. 답하면 서버가 지운다."""
    pending = profile_of(visit).vector.get("pending")
    if not pending:
        return None
    return {
        "kind": pending["kind"],
        "reply_to": pending["message_id"],
        "options": pending["options"],
    }


def append_answer(visit: Visit, payload: dict) -> ChatLog:
    """손님이 누른 버튼을 말풍선으로 남긴다. 문구는 가설에 딸린 라벨에서 가져온다."""
    pending = profile_of(visit).vector.get("pending") or {}
    label = _label_of(pending, payload)
    return ChatLog.objects.create(
        visit=visit,
        role=Role.USER_ACTION,
        content=label,
        product=payload.get("product"),
    )


def _label_of(pending: dict, payload: dict) -> str:
    for option in pending.get("options", []):
        if option.get("type") != payload["type"]:
            continue
        if payload["option"] and option.get("option") != payload["option"]:
            continue
        if payload.get("product") and option.get("product_id") != payload["product"].id:
            continue
        return option["label"]
    return "선택"


def assert_pending(visit: Visit, reply_to: str) -> None:
    """이미 답한 가설이나 다른 가설에 답하는 것을 막는다(중복 클릭·화면 복원 시차)."""
    from rest_framework.exceptions import ValidationError

    from api.exceptions import Unauthorized  # noqa: F401  (아래 ValidationError와 대비용)

    pending = profile_of(visit).vector.get("pending")
    if not pending or pending.get("message_id") != reply_to:
        raise ValidationError({"reply_to": ["이미 답했거나 유효하지 않은 가설입니다."]})


def messages_after(visit: Visit, message: ChatLog) -> list[ChatLog]:
    """그 메시지 이후에 서버가 덧붙인 것까지 함께 돌려준다(프리셋 답변 등)."""
    return list(visit.chat_logs.filter(created_at__gte=message.created_at).order_by("created_at"))


def completion(visit: Visit) -> float:
    from apps.analysis import taste as taste_module

    return taste_module.read(visit).confidence
