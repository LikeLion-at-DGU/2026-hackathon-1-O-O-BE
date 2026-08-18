"""손님에게 보여줄 표현. 내부 축 값을 그대로 말하지 않는다.

`TextChoices`의 label은 건드리지 않는다 — Admin 상품 목록과 시드 검수가 그 label을 쓴다.
`coated_canvas`의 label이 "생활 방수 되는 소재"로 바뀌면 상품 관리 화면이 이상해진다.
"""

from apps.catalog.models import (
    Category,
    Color,
    Material,
    Mood,
    Pattern,
    PriceBand,
    Silhouette,
    UseCase,
)

CUSTOMER_WORDS = {
    Mood.MINIMAL: "절제된 느낌",
    Mood.BOLD_STATEMENT: "눈에 띄는 느낌",
    Mood.CLASSIC_HERITAGE: "클래식한 느낌",
    Mood.Y2K_STREET: "스트리트한 느낌",
    Material.COATED_CANVAS: "생활 방수 되는 소재",
    Material.GRAINED_LEATHER: "스크래치에 강한 가죽",
    Material.SMOOTH_LEATHER: "매끄러운 가죽",
    Material.NYLON: "가벼운 나일론",
    Material.SUEDE: "스웨이드",
    Material.MIXED: "혼합 소재",
    Pattern.VISETOS_MONOGRAM: "패턴이 있는 쪽",
    Pattern.LOGO_PRINT: "로고가 들어간 쪽",
    Pattern.SOLID: "무지",
    Pattern.STUDDED: "스터드가 있는 쪽",
    Silhouette.STRUCTURED: "형태가 잡힌",
    Silhouette.SLOUCHY: "부드럽게 흐르는",
    Silhouette.BOXY: "박시한",
    Silhouette.COMPACT: "작고 단단한",
    Color.BLACK: "블랙",
    Color.WHITE: "화이트",
    Color.COGNAC: "코냑",
    Color.BEIGE: "베이지",
    Color.NAVY: "네이비",
    Color.RED: "레드",
    Color.PINK: "핑크",
    Color.METALLIC: "메탈릭",
    Color.VISETOS_MIX: "배색 패턴",
    UseCase.DAILY: "데일리",
    UseCase.WORK: "출근용",
    UseCase.TRAVEL: "여행용",
    UseCase.GOING_OUT: "나들이용",
    PriceBand.ENTRY: "가벼운 가격대",
    PriceBand.MID: "중간 가격대",
    PriceBand.HIGH: "높은 가격대",
    Category.BACKPACK: "백팩",
    Category.TOTE: "토트백",
    Category.CROSSBODY: "크로스백",
    Category.SHOULDER: "숄더백",
    Category.WALLET: "지갑",
    Category.ACCESSORY: "액세서리",
}

# 진영 이름은 2택 버튼 라벨로 그대로 쓴다.
CAMP_WORDS = {
    ("mood", "C"): "차분한 결",
    ("mood", "T"): "개성 있는 결",
    ("color", "N"): "차분한 색",
    ("color", "V"): "눈에 띄는 색",
    ("pattern", "P"): "깔끔한 쪽",
    ("pattern", "O"): "장식이 있는 쪽",
    ("use_case", "D"): "매일 쓸 것",
    ("use_case", "S"): "특별한 날",
}

AXIS_WORDS = {
    "mood": "결",
    "color": "색",
    "material": "소재",
    "pattern": "패턴",
    "silhouette": "형태",
    "use_case": "용도",
}


def with_subject(word: str) -> str:
    """받침에 따라 이/가를 붙인다. "용도이"처럼 나가면 손님이 바로 알아챈다."""
    last = word[-1]
    if "가" <= last <= "힣":
        has_final = (ord(last) - 0xAC00) % 28 != 0
        return f"{word}{'이' if has_final else '가'}"
    return f"{word}가"


def say(value: str) -> str:
    """축 값을 손님용 표현으로. 없으면 값을 그대로 쓴다(누락을 눈에 보이게)."""
    return CUSTOMER_WORDS.get(value, value)


def say_camp(axis: str, camp: str) -> str:
    return CAMP_WORDS[(axis, camp)]


def say_axis(axis: str) -> str:
    return AXIS_WORDS.get(axis, axis)
