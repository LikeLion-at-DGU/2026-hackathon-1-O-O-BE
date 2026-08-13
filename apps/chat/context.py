"""프롬프트 조립. 클라이언트가 문맥을 다시 보내지 않아도 서버가 chat_logs에서 만든다.

이게 O&O 챗봇의 핵심이다. 사용자는 "이 상품의 디자이너 의도 설명해줘"처럼
상품명을 말하지 않아도 되고, 서버가 지금 어떤 상품 얘기 중인지 알고 있다.
"""

from apps.catalog.models import PresetKey, Product
from apps.chat.messages import current_context, timeline
from apps.chat.models import Role
from apps.chat.prompts import CONTEXT_HEADER, SYSTEM_PROMPT, TIMELINE_HEADER
from apps.visits.models import Visit

TIMELINE_WINDOW = 12  # 프롬프트에 넣는 최근 메시지 수. 토큰을 아끼면서 흐름은 유지한다.

ROLE_TO_OPENAI = {
    Role.USER: "user",
    Role.USER_ACTION: "user",  # 클릭도 손님의 행동이므로 user 쪽에 둔다
    Role.ASSISTANT: "assistant",
    Role.PRESET: "assistant",  # 프리셋 답변도 챗봇이 이미 한 말이다
}


def build_messages(visit: Visit, question: str, override: dict | None = None) -> list[dict]:
    """system + 상품 문맥 + 최근 타임라인 + 이번 질문."""
    context = override or current_context(visit)
    product = _target_product(context)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if product is not None:
        messages.append({"role": "system", "content": _describe(product)})
    messages.append({"role": "system", "content": _describe_visitor(visit)})
    messages.extend(_recent_turns(visit))
    messages.append({"role": "user", "content": question})
    return messages


def _target_product(context: dict) -> Product | None:
    product_id = context.get("product_id")
    if not product_id:
        return None
    return Product.objects.select_related("scene").filter(id=product_id).first()


def _describe(product: Product) -> str:
    """상품에 대해 서버가 아는 사실을 전부 넣는다.

    llm_context만 넣었더니 "디자이너 의도는 정보에 없다"는 답이 나왔다. 스토리와
    프리셋 문구에 그 답이 들어 있었다. 프리셋은 브랜드가 직접 작성한 문장이라
    근거로 삼기에 가장 안전하다. 이 내용은 프롬프트 안에서만 쓰이고 응답으로는 나가지 않는다.
    """
    lines = [
        CONTEXT_HEADER,
        f"- 이름: {product.name}",
        f"- 위치: {product.scene.no}번 진열대 {product.no}번",
        f"- 가격: {product.price:,}원",
        f"- 설명: {product.llm_context}",
        f"- 브랜드 스토리: {product.story}",
        f"- 특징: {product.get_color_display()} / {product.get_material_display()} / "
        f"{product.get_pattern_display()} / {product.get_silhouette_display()} / "
        f"{product.get_mood_display()} / {product.get_use_case_display()}",
    ]
    lines += [
        f"- {PresetKey(key).label}: {answer}"
        for key, answer in product.preset_answers.items()
        if answer and key in PresetKey.values
    ]
    return "\n".join(lines)


def _describe_visitor(visit: Visit) -> str:
    """연령대·성별은 말투를 고르는 참고값이다. 단정적인 추측 근거로 쓰지 않는다."""
    visitor = visit.visitor
    if not visitor.age_band and not visitor.gender:
        return "손님 정보: 밝히지 않았습니다. 중립적인 말투를 씁니다."
    parts = [visitor.get_age_band_display() or "연령대 미상", visitor.get_gender_display() or "성별 미상"]
    return f"손님 정보: {' · '.join(parts)}. 말투를 맞추는 참고만 하고 취향을 단정하지 않습니다."


def _recent_turns(visit: Visit) -> list[dict]:
    recent = timeline(visit)[-TIMELINE_WINDOW:]
    turns = [{"role": ROLE_TO_OPENAI[log.role], "content": log.content} for log in recent]
    if not turns:
        return []
    return [{"role": "system", "content": TIMELINE_HEADER}, *turns]
