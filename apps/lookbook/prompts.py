"""화보 프롬프트 조립. 순수 함수만 둔다 — 네트워크도 DB도 여기서 만지지 않는다.

**레퍼런스가 없으면 레퍼런스 문장을 아예 넣지 않는다.** "레퍼런스를 따르라"고 써놓고
그림을 안 주면 모델이 없는 것을 상상해서 구도가 제멋대로 튄다. 있을 때만 말한다.

재생성은 구도·자세만 흔들고 무드는 유지한다. 매번 다른 세계관이 나오면 "다시 돌리기"가
아니라 "다른 서비스"가 된다.
"""

# 재생성마다 흔드는 값. seed로 고르므로 같은 회차는 항상 같은 문구가 나온다.
VARIATIONS = (
    "a relaxed three-quarter stance",
    "a straight-on frontal stance",
    "a slight turn of the shoulders with the gaze off-camera",
    "a subtle contrapposto with weight on one leg",
)

BASE_RULES = (
    "Preserve the person's face, hair, body proportions and skin tone from the first image exactly. "
    "Do not beautify, slim, reshape or change their age. "
    "Photorealistic editorial fashion photography, natural skin texture, no text, no watermark, no logos."
)


def build(
    *,
    mood: dict,
    composition_prompt: str,
    product_names: list[str],
    venue: str,
    season: str,
    seed: int,
    attempt: int,
    has_reference: bool,
) -> str:
    """이미지 편집 프롬프트 한 덩어리. 문장 단위로 이어 붙인다."""
    parts = [
        f"Editorial fashion lookbook photograph for {season} at {venue}.",
        _mood_sentence(mood),
        _product_sentence(product_names),
        composition_prompt.strip(),
        _reference_sentence(has_reference),
        _variation_sentence(seed, attempt),
        BASE_RULES,
    ]
    return " ".join(part for part in parts if part)


def _mood_sentence(mood: dict) -> str:
    """리포트에서 박제된 무드. 재생성해도 이 값은 그대로라 분위기가 유지된다."""
    name = (mood.get("name") or "").strip()
    palette = mood.get("palette") or []
    if not name and not palette:
        return ""

    sentence = f"Overall mood: {name}." if name else ""
    if palette:
        sentence += f" Color palette: {', '.join(str(color) for color in palette)}."
    return sentence.strip()


def _product_sentence(product_names: list[str]) -> str:
    """상품이 주인공이다. 이름을 그대로 넣어 벤더가 형태를 지어내지 않게 한다."""
    if not product_names:
        return ""
    return (
        f"The person is styled with: {', '.join(product_names)}. "
        "Keep the product's shape, color and details faithful."
    )


def _reference_sentence(has_reference: bool) -> str:
    if not has_reference:
        return ""
    return (
        "Follow the layout, framing and camera angle of the attached reference image. "
        "Use it for composition only - do not copy the person, face or clothing from it."
    )


def _variation_sentence(seed: int, attempt: int) -> str:
    """첫 컷은 흔들지 않는다. 재생성일 때만 자세·구도를 바꾼다."""
    if attempt <= 1:
        return ""
    return f"Vary the framing and pose from previous versions: use {VARIATIONS[seed % len(VARIATIONS)]}."
