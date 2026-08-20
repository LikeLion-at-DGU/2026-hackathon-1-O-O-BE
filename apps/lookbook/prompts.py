"""화보 프롬프트 조립. 순수 함수만 둔다 — 네트워크도 DB도 여기서 만지지 않는다.

**모델에 넣는 이미지마다 역할을 말해줘야 한다.** 사진·레퍼런스·상품을 그냥 나란히
넣으면 모델은 뭘 보존하고 뭘 참고할지 모른다. 그래서 몇 번째 이미지가 무엇인지
문장으로 붙인다. 순서는 worker가 넣는 순서와 반드시 같아야 한다.

**레퍼런스에는 글자와 콜라주가 함께 있다.** AI는 글자·로고·인물 정체성을 베끼면 안
되지만, 빈 타이포 영역·패널·찢어진 종이 같은 레이아웃 구조는 화보 연출로 참고할 수
있다. 둘을 분리해서 지시하지 않으면 모델이 레이아웃까지 버리거나 글자를 뭉개서 그린다.

재생성은 구도·자세만 흔들고 무드는 유지한다. 매번 다른 세계관이 나오면 "다시 돌리기"가
아니라 "다른 서비스"가 된다.
"""

# 기획 시안(화보 시리즈 8장)에서 뽑은 팔레트. 인물·구도는 같고 배경색만 달랐다.
# 리포트에 무드가 실려 오면 그 값을 쓰고, 없으면 seed로 고른다 — 지금 분석 워커가
# 무드를 만들지 않아서 비워두면 배경 지시가 통째로 빠진다.
MOODS = (
    ("ivory", "warm ivory and cream", "soft warm light, calm and classic"),
    ("brown", "tan and deep brown", "warm earthy light, heritage feel"),
    ("charcoal", "charcoal grey and black", "high-contrast moody light"),
    ("coral", "apricot and coral", "bright airy light, playful"),
)

# 재생성마다 흔드는 값. seed로 고르므로 같은 회차는 항상 같은 문구가 나온다.
VARIATIONS = (
    "a relaxed three-quarter stance",
    "a straight-on frontal stance",
    "a slight turn of the shoulders with the gaze off-camera",
    "a subtle contrapposto with weight on one leg",
)

# 레퍼런스가 없을 때만 쓰는 최소한의 방향이다. 레퍼런스가 있으면 좌우 배치·배경을
# 고정하지 않고 Image 2의 구도를 우선한다.
FALLBACK_DIRECTION = (
    "Use a clean studio fashion editorial composition with balanced negative space "
    "and a simple textured backdrop."
)

BASE_RULES = (
    "Use photorealistic editorial fashion photography with believable human anatomy and "
    "natural skin texture. Do not render readable text, typography, captions, brand names, "
    "logos or watermarks. Graphic panels, empty text regions, borders, cutout shapes and "
    "collage divisions may be recreated as abstract layout elements, but they must remain "
    "free of readable text."
)


# 지시가 스무 개를 넘으면 모델이 일부를 버린다. 무엇을 먼저 버릴지 우리가 정해두지
# 않으면 모델이 임의로 고른다 — 얼굴이 딴사람이 되는 것이 가장 나쁜 실패다.
PRIORITY_HEAD = "When instructions compete, follow this priority order: "
PRIORITY_PERSON = "person identity and body accuracy from Image 1"
PRIORITY_PRODUCT_IMAGE = "product appearance accuracy from the product reference"
PRIORITY_PRODUCT_NAME = "product appearance accuracy"
PRIORITY_INTERACTION = "realistic interaction between the person and the product"
PRIORITY_REFERENCE = "editorial composition similarity to the editorial reference"
PRIORITY_STYLING = "general styling and atmosphere"


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
    has_product_image: bool = False,
) -> str:
    """이미지 편집 프롬프트 한 덩어리. 문장 단위로 이어 붙인다."""
    parts = [
        f"Editorial fashion lookbook photograph for {season} at {venue}.",
        _roles(has_reference, has_product_image),
        _mood_sentence(mood, seed),
        _product_sentence(product_names, has_product_image),
        _direction(composition_prompt, has_reference),
        _variation_sentence(seed, attempt),
        BASE_RULES,
        _priority(has_reference, has_product_image),
    ]
    return " ".join(part for part in parts if part)


def _roles(has_reference: bool, has_product_image: bool) -> str:
    """몇 번째 이미지가 무엇인지. worker가 넣는 순서와 같아야 한다.

    사진 → 레퍼런스 → 상품 순이고, 없는 것은 번호에서 빠진다. 번호가 밀리면
    모델이 상품 사진을 보존 대상으로 오해한다.
    """
    lines = [
        "Image 1 is the person reference and the exclusive source of the person's identity "
        "and body. Preserve the same recognizable person: facial features, face shape and "
        "proportions, eyes, nose, mouth, jawline, hairstyle and hair volume, glasses if "
        "present, skin tone and natural skin texture, body proportions, body build and "
        "overall silhouette. Do not replace the person, beautify, reshape, slim, enlarge, "
        "masculinize, feminize or significantly reinterpret their face or body.",
    ]
    index = 2
    if has_reference:
        lines.append(
            f"Image {index} is the editorial reference. Use it as the primary source for "
            "overall editorial composition, pose direction, camera angle, camera distance and "
            "crop, subject placement, visual hierarchy, negative space, background treatment, "
            "lighting direction, color relationships, graphic panels, empty text regions, "
            "cutout or collage structure, and placement of product-detail areas. Do not copy "
            "the identity, face, body, hairstyle or clothing of the person in this image. Do "
            "not reproduce readable text, typography, captions, logos, brand names or "
            "watermarks from it."
        )
        index += 1
    if has_product_image:
        lines.append(
            f"Image {index} is the product reference. Use the exact product shown: preserve "
            "its silhouette, dimensions and proportions, color, material and texture, handles, "
            "shoulder straps, pockets, seams, closures, hardware, patterns and construction "
            "details. Integrate it naturally with the person using the interaction and pose "
            "logic of the editorial reference. Keep realistic scale, correct hand grip, natural "
            "strap placement, contact, occlusion, gravity, shadows and fabric deformation. Do "
            "not invent handles or straps, redesign, simplify, replace or float the product."
        )
    return " ".join(lines)


def _priority(has_reference: bool, has_product_image: bool) -> str:
    """충돌 시 무엇을 먼저 지킬지. 뒤쪽 문장이 더 강하게 작용하므로 맨 마지막에 둔다.

    **넣지 않은 이미지는 언급하지 않는다.** 레퍼런스가 없는데 "레퍼런스를 따르라"고
    하면 모델이 없는 그림을 상상해서 구도가 튄다.
    """
    items = [
        PRIORITY_PERSON,
        PRIORITY_PRODUCT_IMAGE if has_product_image else PRIORITY_PRODUCT_NAME,
        PRIORITY_INTERACTION,
    ]
    if has_reference:
        items.append(PRIORITY_REFERENCE)
    items.append(PRIORITY_STYLING)

    ordered = ", ".join(f"{number}) {item}" for number, item in enumerate(items, start=1))
    return f"{PRIORITY_HEAD}{ordered}."


def _direction(composition_prompt: str, has_reference: bool) -> str:
    """구도 지시는 한 곳에서만 나간다.

    레퍼런스가 있으면 아무 말도 하지 않는다. 위에서 이미 "Image 2가 구도의 주인"이라고
    선언했는데 여기서 또 다른 구도를 지시하면 두 그림을 동시에 요구하는 셈이 된다.
    특히 콜라주 레퍼런스에 "얼굴이 화면을 채우는 클로즈업"을 겹쳐 넣으면 결과가 흔들린다.

    레퍼런스가 없을 때만 DB의 구도 문장을 쓰고, 그것도 없으면 최소한의 기본값으로 떨어진다.
    """
    if has_reference:
        return ""
    return composition_prompt.strip() or FALLBACK_DIRECTION


def _mood_sentence(mood: dict, seed: int) -> str:
    """리포트에서 박제된 무드가 있으면 그것을, 없으면 seed로 고른 팔레트를 쓴다.

    같은 방문은 seed가 고정이라 재생성해도 팔레트가 유지된다 — "무드는 비슷하게"를
    무드 데이터 없이도 지킨다.
    """
    name = (mood.get("name") or "").strip()
    palette = mood.get("palette") or []
    if name or palette:
        sentence = f"Overall mood: {name}." if name else ""
        if palette:
            sentence += f" Color palette: {', '.join(str(color) for color in palette)}."
        return sentence.strip()

    _, colors, light = MOODS[seed % len(MOODS)]
    return f"Color palette: {colors}. Lighting: {light}."


def _product_sentence(product_names: list[str], has_product_image: bool) -> str:
    """상품이 주인공이다. 사진이 없으면 이름만으로라도 형태를 지정한다."""
    if not product_names:
        return ""
    names = ", ".join(product_names)
    if has_product_image:
        return f"The product is: {names}."
    return f"The person is styled with: {names}. Keep the product's shape, color and details faithful."


def _variation_sentence(seed: int, attempt: int) -> str:
    """첫 컷은 흔들지 않는다. 재생성일 때만 자세·구도를 바꾼다."""
    if attempt <= 1:
        return ""
    return f"Vary the framing and pose from previous versions: use {VARIATIONS[seed % len(VARIATIONS)]}."
