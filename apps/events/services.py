"""이벤트 적립. 저장은 append-only이고 event_id로 멱등성을 보장한다."""

from uuid import UUID, uuid4

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.catalog.models import Product, Scene
from apps.events.models import Event, EventType
from apps.visits.models import Visit

DWELL_KEY = "dwell_ms"

# 한 번에 저장하는 수. 초과분은 버리지 않고 rejected로 알려서 다음 배치에 다시 받는다.
# 매장 와이파이가 끊겼다 복구되면 밀린 버퍼가 한 번에 몰리는데, 그때 버려지는 기록은
# 클라이언트에도 서버에도 남지 않는다.
EVENT_BATCH_MAX = 200

# 관람의 시작·끝은 서버가 판단한다. 프론트가 같이 보내면 퍼널의 분모가 두 배가 된다.
SERVER_OWNED_TYPES = frozenset({EventType.STORE_ENTER, EventType.VISIT_START, EventType.VISIT_END})

# 관람이 끝난 뒤에도 받는 타입. 화보는 /finish 이후에 일어나므로 이 문이 열려 있어야 한다.
# 반대로 관람 이벤트는 여기서 막는다 — 리포트는 /finish 시점에 박제되므로 뒤늦게 들어온
# 상품 조회는 반영될 수 없고, 그대로 저장하면 원본과 리포트가 어긋난다.
POST_VISIT_TYPES = frozenset(
    {
        EventType.LOOKBOOK_CANDIDATES_VIEW,
        EventType.LOOKBOOK_PRODUCT_SELECT,
        EventType.PHOTO_CONSENT,
        EventType.PHOTO_CAPTURE,
        EventType.PHOTO_RETAKE,
        EventType.LOOKBOOK_GENERATE_REQUEST,
        EventType.LOOKBOOK_REGENERATE,
        EventType.LOOKBOOK_COMPLETE,
        EventType.LOOKBOOK_SHARE,
        EventType.LOOKBOOK_SAVE,
    }
)


def record(
    visit: Visit,
    event_type: str,
    *,
    scene: Scene | None = None,
    product: Product | None = None,
    metadata: dict | None = None,
) -> Event:
    """서버가 직접 남기는 이벤트. 서버 생성이라 client_timestamp도 서버 시각을 쓴다."""
    return Event.objects.create(
        event_id=uuid4(),
        visit=visit,
        event_type=event_type,
        scene=scene,
        product=product,
        client_timestamp=timezone.now(),
        metadata=metadata or {},
    )


def append_batch(visit: Visit, items: list[dict]) -> dict:
    """프론트가 모아 보낸 배치를 저장한다.

    같은 배치를 두 번 보내도 결과가 같아야 한다(멱등). 그래서 실패 시 클라이언트는
    그냥 재전송하면 되고, 브라우저가 닫혀도 직전 기록이 날아가지 않는다.
    """
    batch, rejected_count = items[:EVENT_BATCH_MAX], max(0, len(items) - EVENT_BATCH_MAX)

    accepted_items, ignored_count = _drop_unaccepted(visit, batch)
    _assert_references_exist(accepted_items)

    unique_items = _dedupe_within_batch(accepted_items)
    known_ids = _existing_event_ids(visit, [item["event_id"] for item in unique_items])
    fresh_items = [item for item in unique_items if item["event_id"] not in known_ids]

    Event.objects.bulk_create([_build_event(visit, item) for item in fresh_items], ignore_conflicts=True)

    return {
        "accepted": len(fresh_items),
        "duplicated": len(accepted_items) - len(fresh_items),
        "ignored": ignored_count,
        "rejected": rejected_count,
    }


def _drop_unaccepted(visit: Visit, items: list[dict]) -> tuple[list[dict], int]:
    """서버 소유 타입과, 관람이 끝난 뒤에 온 관람 이벤트를 걸러낸다."""
    allowed = _allowed_types(visit)
    kept = [item for item in items if item["event_type"] in allowed]
    return kept, len(items) - len(kept)


def _allowed_types(visit: Visit) -> frozenset[str]:
    if visit.is_open:
        return frozenset(EventType.values) - SERVER_OWNED_TYPES
    return POST_VISIT_TYPES


def _assert_references_exist(items: list[dict]) -> None:
    """없는 전시존·상품을 가리키는 이벤트는 받지 않는다.

    프론트는 /enter가 내려준 목록에서 id를 얻으므로, 모르는 id가 오면 코드 버그다.
    조용히 버리면 분석 수치가 눈에 안 보이게 틀어진다.
    """
    for model, key in ((Scene, "scene_id"), (Product, "product_id")):
        requested = {item[key] for item in items if item[key]}
        if not requested:
            continue
        found = set(model.objects.filter(id__in=requested).values_list("id", flat=True))
        unknown = requested - found
        if unknown:
            raise ValidationError({key: [f"존재하지 않습니다: {', '.join(sorted(unknown))}"]})


def _dedupe_within_batch(items: list[dict]) -> list[dict]:
    """같은 배치에 같은 event_id가 두 번 들어온 경우. 먼저 온 것만 남긴다."""
    seen: set[UUID] = set()
    unique = []
    for item in items:
        if item["event_id"] in seen:
            continue
        seen.add(item["event_id"])
        unique.append(item)
    return unique


def _existing_event_ids(visit: Visit, event_ids: list[UUID]) -> set[UUID]:
    """이미 저장된 것을 미리 조회한다. bulk_create는 몇 건이 무시됐는지 알려주지 않는다."""
    return set(Event.objects.filter(visit=visit, event_id__in=event_ids).values_list("event_id", flat=True))


def _build_event(visit: Visit, item: dict) -> Event:
    return Event(
        event_id=item["event_id"],
        visit=visit,
        event_type=item["event_type"],
        scene_id=item["scene_id"] or None,
        product_id=item["product_id"] or None,
        client_timestamp=item["client_timestamp"],
        metadata=_clamp_dwell(item["metadata"]),
    )


def _clamp_dwell(metadata: dict) -> dict:
    """체류시간 상한을 씌운다.

    탭을 백그라운드에 두면 30분이 찍힌다. 가장 중요한 관심 신호를 검증 없이 믿으면
    취향 프로필이 한 상품에 끌려간다. (형식·음수 검증은 시리얼라이저가 이미 했다)
    """
    if DWELL_KEY not in metadata:
        return metadata
    return {**metadata, DWELL_KEY: min(metadata[DWELL_KEY], settings.DWELL_MAX_MS)}
