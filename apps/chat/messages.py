"""클릭을 말풍선으로 쌓고, 그 기록에서 AI의 문맥을 뽑는다.

O&O의 채팅창은 빈 화면에서 시작하지 않는다. 진열대·상품을 누른 행적이 이미 쌓여
있고, "채팅으로 대화하기"로 넘어가면 서버가 그 기록을 읽어 AI가 지금 어떤 상품
얘기를 하는 중인지 알게 된다. 그래서 사용자는 상품명을 말하지 않아도 된다.
"""

import logging

from django.conf import settings

from apps.catalog.models import PresetKey, Product, Scene
from apps.chat.models import ActionType, ChatLog, Role
from apps.visits.models import Visit

logger = logging.getLogger(__name__)

GREETING = "저와 함께 MCM을 경험해 보아요!\n각 진열대를 눌러 상품에 대해 알아보세요."
PRESET_FALLBACK = "안내 문구가 아직 준비되지 않았습니다."

# 진열대·상품 클릭은 직전과 같으면 말풍선을 새로 쌓지 않는다. 화면이 같은 말풍선으로
# 도배되기 때문이다. 조회 횟수 같은 수치는 POST /events가 따로 남기므로 잃는 게 없다.
# 프리셋은 제외한다 — 같은 걸 다시 물어보는 것 자체가 의미 있는 행동이다.
DEDUPE_TYPES = frozenset({ActionType.SCENE_CLICK, ActionType.PRODUCT_CLICK})


def append_greeting(visit: Visit) -> ChatLog:
    """입장 직후 챗봇 인사를 타임라인 맨 위에 둔다.

    프론트가 하드코딩하지 않고 서버가 쌓는 이유: GET /chat/messages 하나로 화면이
    완전히 복원돼야 한다. 이어하기로 돌아왔을 때도 인사가 제자리에 있어야 한다.
    """
    return ChatLog.objects.create(visit=visit, role=Role.ASSISTANT, content=GREETING)


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
