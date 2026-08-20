"""① 이벤트 집계. DB를 읽는 구간은 여기까지고, 이후 계산은 전부 순수 함수다.

수백 개 이벤트를 상품 단위로 압축한다. 쿼리는 방문당 4번(이벤트·대화·인기도·상품)
으로 고정되어 있다 — 상품 수가 늘어도 쿼리 수는 그대로다.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from django.db.models import Count

from apps.analysis.signals import ProductFacts, ProductSignal, SceneSignal, VisitSignals
from apps.catalog.models import ANALYSIS_AXES, Product, Scene
from apps.events.models import Event, EventType
from apps.events.services import DWELL_KEY, exposed_scene_ids
from apps.visits.models import Visit


@dataclass
class _Tally:
    """이벤트를 한 번 훑어 모은 집계. 조립은 collect_signals가 한다."""

    views: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    dwell: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    scene_dwell: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    questions: int = 0


def collect_signals(visit: Visit) -> VisitSignals:
    """이번 방문의 행동을 상품 단위로 압축한다."""
    tally = _tally_events(visit)
    mentions = _chat_mentions(visit)
    product_ids = sorted(set(tally.views) | set(tally.dwell) | set(mentions))

    return VisitSignals(
        products=tuple(
            ProductSignal(
                product_id=product_id,
                views=tally.views[product_id],
                dwell_ms=tally.dwell[product_id],
                chat_mentions=mentions.get(product_id, 0),
            )
            for product_id in product_ids
        ),
        scenes=_scene_signals(tally.scene_dwell),
        scenes_viewed=len(exposed_scene_ids(visit)),
        questions=tally.questions,
    )


def _tally_events(visit: Visit) -> _Tally:
    """이벤트 한 줄씩 세어 담는다. 쿼리는 이 한 번뿐이다."""
    tally = _Tally()
    rows = visit.events.values_list("event_type", "product_id", "scene_id", "product__scene_id", "metadata")
    for event_type, product_id, scene_id, product_scene_id, metadata in rows:
        if event_type == EventType.QUESTION_SUBMIT:
            tally.questions += 1
        elif product_id and event_type == EventType.PRODUCT_VIEW:
            tally.views[product_id] += 1
        elif product_id and event_type == EventType.PRODUCT_DWELL:
            _add_dwell(tally, product_id, product_scene_id, metadata)
        elif scene_id and event_type == EventType.SCENE_DWELL:
            tally.scene_dwell[scene_id] += _dwell_of(metadata)
    return tally


def _add_dwell(tally: _Tally, product_id: str, scene_id: str | None, metadata: dict) -> None:
    """상품 체류는 그 진열대의 체류이기도 하다.

    진열대 화면과 상품 화면은 라우트가 달라 두 체류가 겹치지 않으므로 그대로 더한다.
    """
    dwell_ms = _dwell_of(metadata)
    tally.dwell[product_id] += dwell_ms
    if scene_id:
        tally.scene_dwell[scene_id] += dwell_ms


def _scene_signals(dwell_by_scene: dict[str, int]) -> tuple[SceneSignal, ...]:
    """체류가 긴 진열대부터. 이름은 화면이 "1번 진열대"를 직접 조립하지 않게 함께 준다."""
    if not dwell_by_scene:
        return ()
    scenes = Scene.objects.filter(id__in=dwell_by_scene).values_list("id", "no", "name")
    signals = [
        SceneSignal(scene_no=no, scene_name=name, dwell_ms=dwell_by_scene[scene_id])
        for scene_id, no, name in scenes
    ]
    return tuple(sorted(signals, key=lambda signal: (-signal.dwell_ms, signal.scene_no)))


def load_catalog() -> tuple[ProductFacts, ...]:
    """스코어링 대상 전체. 리포트에 박제할 스냅샷도 이때 같이 들고 온다."""
    popularity = _popularity()
    products = Product.objects.select_related("scene").all()
    return tuple(
        ProductFacts(
            product_id=product.id,
            name=product.name,
            thumbnail=product.thumbnail,
            price=product.price,
            external_url=product.external_url,
            scene_no=product.scene.no,
            product_no=product.no,
            is_new=product.is_new,
            popularity=popularity.get(product.id, 0.0),
            axes={axis: getattr(product, axis) for axis in ANALYSIS_AXES},
        )
        for product in products
    )


def load_conversation(visit: Visit) -> list[tuple[str, str]]:
    """LLM에 넘길 대화. 클릭이 남긴 메시지도 문맥이라 함께 넣는다."""
    return list(visit.chat_logs.values_list("role", "content"))


def _dwell_of(metadata: dict) -> int:
    """저장 시점에 상한(5분)까지 씌워둔 값이다. 여기서는 형식만 확인한다."""
    value = metadata.get(DWELL_KEY, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _chat_mentions(visit: Visit) -> dict[str, int]:
    rows = (
        visit.chat_logs.filter(product__isnull=False).values("product_id").annotate(count=Count("message_id"))
    )
    return {row["product_id"]: row["count"] for row in rows}


def _popularity() -> dict[str, float]:
    """전체 방문 기준 조회 인기도. 최고 조회수를 1로 둔 상대값이다.

    이번 방문자와 무관한 집계라 익명성을 해치지 않으면서 "다들 보는 상품"을
    추천에 15% 반영할 수 있다.
    """
    rows = (
        Event.objects.filter(event_type=EventType.PRODUCT_VIEW, product__isnull=False)
        .values("product_id")
        .annotate(count=Count("event_id"))
    )
    counts = {row["product_id"]: row["count"] for row in rows}
    peak = max(counts.values(), default=0)
    if peak == 0:
        return {}
    return {product_id: round(count / peak, 4) for product_id, count in counts.items()}
