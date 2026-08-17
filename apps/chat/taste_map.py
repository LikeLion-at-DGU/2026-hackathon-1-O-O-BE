"""발화를 축으로 바꾸는 사전.

LLM보다 먼저 훑는다. 흔한 표현은 항상 같은 결과가 나오고 비용·지연이 0이다.
모호한 표현("무난한" → classic인지 minimal인지)은 **넣지 않는다.** 사전이 한 값만
주면 틀린 추천이 나가므로, 그런 표현은 LLM 폴백이 문맥을 보고 판단하게 한다.
"""

from apps.catalog.models import (
    Category,
    Color,
    Material,
    Mood,
    PriceBand,
    Silhouette,
    UseCase,
)

# 어휘 → [(축, 값)]. 한 표현이 여러 축을 짚을 수 있다.
VOCABULARY: dict[str, list[tuple[str, str]]] = {
    "차분한": [("mood", Mood.MINIMAL)],
    "조용한": [("mood", Mood.MINIMAL)],
    "과하지 않": [("mood", Mood.MINIMAL)],
    "심플": [("mood", Mood.MINIMAL)],
    "화려한": [("mood", Mood.BOLD_STATEMENT)],
    "튀는": [("mood", Mood.BOLD_STATEMENT)],
    "눈에 띄": [("mood", Mood.BOLD_STATEMENT)],
    "포인트": [("mood", Mood.BOLD_STATEMENT)],
    "클래식": [("mood", Mood.CLASSIC_HERITAGE)],
    "정통": [("mood", Mood.CLASSIC_HERITAGE)],
    "힙한": [("mood", Mood.Y2K_STREET)],
    "스트리트": [("mood", Mood.Y2K_STREET)],
    "개성": [("mood", Mood.Y2K_STREET)],
    "꾸안꾸": [("mood", Mood.MINIMAL), ("use_case", UseCase.DAILY)],
    "오래 쓸": [("material", Material.GRAINED_LEATHER), ("silhouette", Silhouette.STRUCTURED)],
    "튼튼": [("material", Material.GRAINED_LEATHER)],
    "가벼운": [("material", Material.NYLON)],
    "비 와도": [("material", Material.COATED_CANVAS)],
    "관리 편": [("material", Material.COATED_CANVAS)],
    "출근": [("use_case", UseCase.WORK)],
    "노트북": [("use_case", UseCase.WORK)],
    "데일리": [("use_case", UseCase.DAILY)],
    "매일": [("use_case", UseCase.DAILY)],
    "여행": [("use_case", UseCase.TRAVEL)],
    "모임": [("use_case", UseCase.GOING_OUT)],
    "나들이": [("use_case", UseCase.GOING_OUT)],
    "선물": [("price_band", PriceBand.ENTRY)],
    "부담 없": [("price_band", PriceBand.ENTRY)],
    "입문": [("price_band", PriceBand.ENTRY)],
    "큰 거": [("category", Category.BACKPACK), ("category", Category.TOTE)],
    "많이 들어가": [("category", Category.BACKPACK), ("category", Category.TOTE)],
    "작은 거": [("category", Category.CROSSBODY), ("category", Category.WALLET)],
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
    "배색": Color.VISETOS_MIX,
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
