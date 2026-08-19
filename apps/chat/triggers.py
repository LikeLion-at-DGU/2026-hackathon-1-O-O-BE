"""트리거 평가. 묻기 전에 관찰하고, 관찰한 것을 확인받는다.

`POST /events` 배치를 받은 직후 한 번 평가한다. 조건에 걸리면 가설 말풍선을
타임라인에 넣고, 손님은 버튼 한 번으로 답한다. 대놓고 묻는 설문을 피하려는 구조다.
"""

from dataclasses import dataclass, field

from django.db.models import Count
from django.utils import timezone

from apps.analysis.taste import CAMPS, CORE_AXES, profile_of
from apps.catalog.models import Product
from apps.chat.wording import say, say_axis, say_camp, with_object, with_subject
from apps.events.models import EventType
from apps.events.services import exposed_scene_ids
from apps.visits.models import Visit

CONFIRM_BUDGET = 3  # 확인형 총량
GENERAL_BUDGET = 2  # 상품·대비·회피의 몫. 남은 1회는 축 확인 몫으로 예약한다
WARMUP_VIEWS = 3
WARMUP_SECONDS = 60
COOLDOWN_VIEWS = 2  # 확인 사이에 상품을 이만큼은 더 봐야 한다

CONFIRM_DWELL_MS = 30_000  # 질문을 던지는 체류 기준 (집합 진입 20초보다 높다)
SKIM_DWELL_MS = 5_000
SKIM_VIEWS = 4
AXIS_MIN_VIEWS = 5
AXIS_SHARE = 0.6
AXIS_STRONG_SHARE = 0.8
AXIS_SCENES = 2
AXIS_RUNNER_UP = 1  # 2등 값이 이보다 많으면 쏠린 게 아니다
AVOIDANCE_MIN = 2
SHIFT_VIEWS = 3

# 축 확인 대상. price_band(무례) · category(자명) · silhouette(인지 어려움)은 뺀다.
ASKABLE_AXES = ("mood", "color", "material", "pattern")


@dataclass
class Hypothesis:
    """서버가 만든 가설 하나. 그대로 assistant 말풍선이 된다."""

    kind: str
    message: str
    options: list[dict]
    axis: str = ""
    asked_value: str = ""  # 축 가설이 물은 값. 응답 처리 때 문구를 다시 파싱하지 않으려고 담는다
    products: list[Product] = field(default_factory=list)

    @property
    def is_axis_confirm(self) -> bool:
        return self.kind == "axis_confirm"


def evaluate(visit: Visit) -> Hypothesis | None:
    """지금 던질 가설 하나. 없으면 None. 한 번에 하나만 묻는다."""
    stored = profile_of(visit).vector
    if not _can_ask(visit, stored):
        return None

    general_left = stored.get("general_count", 0) < GENERAL_BUDGET
    axis_left = not stored.get("axis_asked", False)

    builders = []
    if general_left:
        # 대비(2군)를 먼저 본다. 왕복 조회는 재조회의 특수한 경우라서, 1군을 앞에 두면
        # 항상 1군이 먹고 2군은 영원히 발동하지 않는다(도달 불가 코드가 된다).
        builders += [_contrast, _product_confirm]
    if axis_left:
        builders.append(_axis_confirm)
    if general_left:
        builders.append(_avoidance)
    builders += [_shift, _quick_browse]  # 특수 트리거는 예산 밖

    for build in builders:
        hypothesis = build(visit, stored)
        if hypothesis is not None:
            return hypothesis
    return None


def _can_ask(visit: Visit, stored: dict) -> bool:
    if stored.get("browse_only"):
        return False
    if stored.get("confirm_count", 0) >= CONFIRM_BUDGET:
        return False
    views = _view_count(visit)
    if views < WARMUP_VIEWS:
        return False
    if (timezone.now() - visit.started_at).total_seconds() < WARMUP_SECONDS:
        return False
    return views - stored.get("asked_at_views", 0) >= COOLDOWN_VIEWS


# ─────────────────────────── 1군 · 상품 확인 ───────────────────────────


def _product_confirm(visit: Visit, stored: dict) -> Hypothesis | None:
    """재조회·장기 체류한 상품을 짚는다. 상품 하나로 8축을 한 번에 가져온다."""
    handled = set(stored.get("asked_products", [])) | set(stored.get("confirmed", []))
    handled |= set(stored.get("rejected", []))

    for product_id, revisited in _candidates(visit):
        if product_id in handled:
            continue
        product = Product.objects.filter(id=product_id).first()
        if product is None:
            continue
        message = (
            f"{product.name}에 다시 돌아오셨네요. 마음에 남으셨어요?"
            if revisited
            else f"{with_object(product.name)} 오래 보고 계세요. 이런 쪽이 끌리시나요?"
        )
        return Hypothesis(
            kind="product_confirm",
            message=message,
            options=_yes_no(),
            products=[product],
        )
    return None


def _candidates(visit: Visit) -> list[tuple[str, bool]]:
    """(상품, 재조회인가). 최근 신호를 먼저 본다."""
    revisits = [
        row["product_id"]
        for row in visit.events.filter(event_type=EventType.PRODUCT_VIEW, product__isnull=False)
        .values("product_id")
        .annotate(n=Count("event_id"))
        if row["n"] >= 2
    ]
    dwelled = [
        event.product_id
        for event in visit.events.filter(event_type=EventType.PRODUCT_DWELL, product__isnull=False).order_by(
            "-server_received_at"
        )
        if event.metadata.get("dwell_ms", 0) >= CONFIRM_DWELL_MS
    ]
    return [(pid, True) for pid in revisits] + [(pid, False) for pid in dwelled]


# ─────────────────────────── 2군 · 대비 2택 ───────────────────────────


def _contrast(visit: Visit, stored: dict) -> Hypothesis | None:
    """왕복 조회(A→B→A)는 지금 고민 중이라는 가장 확실한 신호다."""
    pair = _round_trip(visit)
    if pair is None or stored.get("contrast_asked"):
        return None
    first, second = pair
    return Hypothesis(
        kind="contrast",
        message="두 개를 견주고 계시네요. 어느 쪽이 더 끌리세요?",
        options=[
            {"label": product.name, "type": "choice", "product_id": product.id} for product in (first, second)
        ],
        products=[first, second],
    )


def _round_trip(visit: Visit) -> tuple[Product, Product] | None:
    ids = list(
        visit.events.filter(event_type=EventType.PRODUCT_VIEW, product__isnull=False)
        .order_by("server_received_at")
        .values_list("product_id", flat=True)
    )
    if len(ids) < 3 or ids[-1] != ids[-3] or ids[-1] == ids[-2]:
        return None
    products = {p.id: p for p in Product.objects.filter(id__in=(ids[-1], ids[-2]))}
    if len(products) < 2:
        return None
    return products[ids[-1]], products[ids[-2]]


# ─────────────────────────── 3군 · 축 확인 ───────────────────────────


def _axis_confirm(visit: Visit, stored: dict) -> Hypothesis | None:
    """조건 7개를 전부 만족할 때만. 유일하게 단일 축에 lock을 준다."""
    viewed = _viewed_products(visit)
    if len(viewed) < AXIS_MIN_VIEWS:
        return None

    asked = set(stored.get("asked", []))
    locks = {**stored.get("spoken", {}), **stored.get("locks", {})}

    for axis in ASKABLE_AXES:
        if axis in asked or axis in locks:
            continue
        if axis in CORE_AXES and axis not in _unlocked_core(locks):
            continue
        value = _dominant(viewed, axis)
        if value is None:
            continue
        if not _spread_over_scenes(viewed, axis, value):
            continue
        if not _has_prior_ground(stored, axis, value, viewed):
            continue
        return Hypothesis(
            kind="axis_confirm",
            message=(
                f"진열대를 옮겨가면서도 {say(value)} 쪽을 보셨네요. "
                f"{with_subject(say_axis(axis))} 이쪽이 편하세요?"
            ),
            options=_yes_no(),
            axis=axis,
            asked_value=value,
        )
    return None


def _unlocked_core(locks: dict) -> tuple[str, ...]:
    return tuple(axis for axis in CORE_AXES if axis not in locks)


def _dominant(viewed: list[Product], axis: str) -> str | None:
    """한 값이 60% 이상이고 다른 값은 1개 이하일 때만 지배값으로 본다."""
    counts: dict[str, int] = {}
    for product in viewed:
        key = getattr(product, axis)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    value, top = max(counts.items(), key=lambda pair: pair[1])
    if top / len(viewed) < AXIS_SHARE:
        return None
    # "다른 값의 총합이 1 이하"로 보면 60% 조건과 충돌한다(5개 중 3개면 나머지가 2개).
    # 원래 의도는 "한쪽으로 쏠렸는가"이므로 2등 값의 개수를 본다.
    rest = sorted((count for key, count in counts.items() if key != value), reverse=True)
    return value if not rest or rest[0] <= AXIS_RUNNER_UP else None


def _spread_over_scenes(viewed: list[Product], axis: str, value: str) -> bool:
    """한 진열대에서만 나온 신호는 취향이 아니라 동선이다.

    전시존이 무드로 나뉘어 있어서, 한 존만 둘러봐도 같은 무드가 여러 개 걸린다.
    """
    scenes = {product.scene_id for product in viewed if getattr(product, axis) == value}
    return len(scenes) >= AXIS_SCENES


def _has_prior_ground(stored: dict, axis: str, value: str, viewed: list[Product]) -> bool:
    """축 확인은 처음 던지는 질문이 아니라 **이미 쌓인 가설을 못 박는** 질문이다.

    근거는 둘 중 하나다.
    1) 손님이 `맞아요` 한 상품(confirmed)이 그 축 값을 갖고 있다 — 1군이 깔아둔 근거
    2) 조회가 그 값으로 80% 이상 쏠렸다 — 1군 없이도 신호가 뚜렷한 경우

    처음엔 축값(taste.score) 0.7 이상으로 뒀는데, shrinkage 때문에 집합이 5개
    전부 같은 값이어야 0.71이 되어 사실상 발동 불가였다. 축값은 표본을 눌러주는
    장치이지 "확인을 받았는가"를 재는 값이 아니다.
    """
    confirmed = set(stored.get("confirmed", []))
    if confirmed and Product.objects.filter(id__in=confirmed, **{axis: value}).exists():
        return True
    same = sum(1 for product in viewed if getattr(product, axis) == value)
    return same / len(viewed) >= AXIS_STRONG_SHARE


# ─────────────────────────── 4군 · 회피형 ───────────────────────────


def _avoidance(visit: Visit, stored: dict) -> Hypothesis | None:
    """안 본 것도 정보다. 같은 존에서 A는 열고 B는 안 열었을 때만 성립한다."""
    asked = set(stored.get("asked", []))
    opened = {product.id for product in _viewed_products(visit)}
    scene_ids = exposed_scene_ids(visit)
    if not scene_ids or not opened:
        return None

    exposed = list(Product.objects.filter(scene_id__in=scene_ids).select_related("scene"))
    for axis in ("color", "mood"):
        if axis in asked:
            continue
        for value, products in _group(exposed, axis).items():
            if len(products) < AVOIDANCE_MIN:
                continue
            if any(product.id in opened for product in products):
                continue
            camp = _camp_of_value(axis, value)
            other = _other_camp(axis, camp) if camp else None
            if other is None:
                continue
            return Hypothesis(
                kind="avoidance",
                message=(
                    f"{say(value)} 쪽은 눈에 안 들어오시는 것 같아요. {say_camp(axis, other)} 쪽이 편하세요?"
                ),
                options=_yes_no(),
                axis=axis,
            )
    return None


def _group(products: list[Product], axis: str) -> dict[str, list[Product]]:
    grouped: dict[str, list[Product]] = {}
    for product in products:
        grouped.setdefault(getattr(product, axis), []).append(product)
    return grouped


def _camp_of_value(axis: str, value: str) -> str | None:
    for camp, members in CAMPS.get(axis, {}).items():
        if value in members:
            return camp
    return None


def _other_camp(axis: str, camp: str) -> str | None:
    return next((name for name in CAMPS[axis] if name != camp), None)


# ─────────────────────────── 특수 트리거 ───────────────────────────


def _shift(visit: Visit, stored: dict) -> Hypothesis | None:
    """확정한 축의 반대 진영을 계속 보고 있으면 다시 묻는다.

    20~30분 관람 중 마음이 바뀌는 건 정상이다. `같은 축 1회` 제한의 유일한 예외다.
    """
    locks = {**stored.get("spoken", {}), **stored.get("locks", {})}
    if not locks or stored.get("shift_asked"):
        return None
    viewed = _viewed_products(visit)
    # 원래는 찜한 상품을 봤다. 찜 기능이 빠지면서 이 조건이 영원히 거짓이 되어
    # 트리거가 통째로 죽어 있었다. confirmed는 손님이 "맞아요"로 직접 고른 상품이라
    # 찜보다 강한 신호이고, 이미 vector에 들어 있어 쿼리도 늘지 않는다.
    confirmed = set(stored.get("confirmed", []))
    for axis, value in locks.items():
        camp = _camp_of_value(axis, value)
        other = _other_camp(axis, camp) if camp else None
        if other is None:
            continue
        members = CAMPS[axis][other]
        opposite = [p for p in viewed if getattr(p, axis) in members]
        if len(opposite) >= SHIFT_VIEWS and any(p.id in confirmed for p in opposite):
            return Hypothesis(
                kind="shift",
                message=(
                    f"아까는 {say(value)} 쪽이라고 하셨는데, 지금은 "
                    f"{say_camp(axis, other)} 쪽을 보고 계세요. 마음이 바뀌셨나요?"
                ),
                options=[
                    {"label": "바뀌었어요", "type": "hypothesis_yes"},
                    {"label": "그대로예요", "type": "hypothesis_no"},
                ],
                axis=axis,
                asked_value=value,
            )
    return None


def _quick_browse(visit: Visit, stored: dict) -> Hypothesis | None:
    """훑고 나가는 손님을 구제한다. 아무 신호도 없이 리포트가 나가는 걸 막는다."""
    if stored.get("quick_asked"):
        return None
    # 조회 총 개수로 센다. _viewed_products(체류 5초+)로 세면 훑는 손님은 항상 0이라
    # 이 트리거가 절대 발동하지 않는다.
    if _view_count(visit) < SKIM_VIEWS:
        return None
    lingered = any(
        event.metadata.get("dwell_ms", 0) >= SKIM_DWELL_MS
        for event in visit.events.filter(event_type=EventType.PRODUCT_DWELL)
    )
    if lingered:
        return None
    return Hypothesis(
        kind="quick_browse",
        message="찾으시는 게 있으세요? 방향만 알려주시면 좁혀드릴게요.",
        options=[
            {"label": "매일 쓸 것", "type": "choice", "option": "use_daily"},
            {"label": "특별한 날", "type": "choice", "option": "use_special"},
            {"label": "그냥 둘러봐요", "type": "choice", "option": "browse_only"},
        ],
        axis="use_case",
    )


# ─────────────────────────── 공통 ───────────────────────────


def _yes_no() -> list[dict]:
    return [
        {"label": "맞아요", "type": "hypothesis_yes"},
        {"label": "아니에요", "type": "hypothesis_no"},
    ]


def _view_count(visit: Visit) -> int:
    return visit.events.filter(event_type=EventType.PRODUCT_VIEW).count()


def _viewed_products(visit: Visit) -> list[Product]:
    """체류 5초 이상인 조회만 센다. 스친 것과 본 것을 같게 두면 안 된다."""
    lingered = {
        event.product_id
        for event in visit.events.filter(event_type=EventType.PRODUCT_DWELL, product__isnull=False)
        if event.metadata.get("dwell_ms", 0) >= SKIM_DWELL_MS
    }
    ids = set(
        visit.events.filter(event_type=EventType.PRODUCT_VIEW, product__isnull=False).values_list(
            "product_id", flat=True
        )
    )
    return list(Product.objects.filter(id__in=ids & lingered).select_related("scene"))
